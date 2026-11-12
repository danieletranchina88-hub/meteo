#!/usr/bin/env python3
"""Fronti sinottici da ICON-EU (DWD open data).

Perche' un secondo modello solo per i fronti
--------------------------------------------
Un fronte e' un oggetto di scala sinottica: mille, duemila chilometri.  Il
dominio di ICON-2I ne contiene quasi sempre solo un pezzo, e a 2,2 km il
gradiente termico si frantuma in tratti che il motore scarta perche' troppo
corti.  Misurato sul run dell'11/11/2026 00Z, stesso motore: ICON-2I pubblica
1 fronte per 5 ore, ICON-EU ne pubblica 10 lungo tutte le 73 ore, e il fronte
principale coincide con l'analisi al suolo del DWD.  ICON-2I resta il modello
di tutto il resto (pioggia, vento, temperatura): qui si prende da ICON-EU
soltanto cio' che ICON-EU sa fare meglio.

Che cosa fa
-----------
1. sceglie l'ultimo run 00Z/12Z di ICON-EU pubblicato per intero;
2. scarica i campi orari che servono al motore (T, umidita', vento a
   925/850/700 hPa, vento e geopotenziale a 500, omega a 700, PMSL, PS,
   vento a 10 m, orografia) e li riunisce in un GRIB per variabile, la forma
   che ``IconSynopticFrontAnalyzer`` gia' legge per ICON-2I;
3. gira lo stesso motore su un dominio europeo;
4. scrive un JSON con i fronti di ogni ora, indicizzati per ORA DI VALIDITA':
   ``process_data.py`` li abbina alle proprie scadenze anche quando i due
   modelli non hanno lo stesso run.

ICON-EU non pubblica l'umidita' specifica sui livelli di pressione: si ricava
da RELHUM e T dello stesso livello (Magnus sull'acqua, la definizione che il
DWD usa per RELHUM).

Se qualcosa manca lo script esce con codice 0 e senza file: la pipeline
ripiega sui fronti di ICON-2I e lo dichiara.
"""

from __future__ import annotations

import argparse
import bz2
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import numpy as np

BASE_URL = "https://opendata.dwd.de/weather/nwp/icon-eu/grib"
MODEL = "ICON-EU"
# Dominio di analisi: abbastanza largo da contenere un fronte intero in
# arrivo dall'Atlantico o dal Baltico (lon_min, lon_max, lat_min, lat_max).
ANALYSIS_BOUNDS = (-15.0, 35.0, 31.0, 60.0)
# 0,0625 gradi (circa 7 km) dimezzati: 14 km, ben sotto la scala di 150 km a
# cui il motore analizza, e un quarto del tempo di calcolo.
ANALYSIS_DOWNSAMPLE = 2
# Che cosa resta nel file pubblicato: il dominio della mappa (3-22 E,
# 33,7-48,9 N) con un margine largo, per vedere il fronte prima che entri.
PUBLISH_BOX = (-6.0, 31.0, 30.0, 56.0)
MIN_PUBLISHED_PIECE_KM = 200.0
MAX_LEAD_HOURS = 78  # oltre, ICON-EU non e' piu' orario
DEFAULT_OUTPUT = "icon_eu_fronts.json"

PRESSURE_FIELDS = (
    ("t", "T", (925, 850, 700)),
    ("relhum", "RELHUM", (925, 850, 700)),
    ("u", "U", (925, 850, 700, 500)),
    ("v", "V", (925, 850, 700, 500)),
    ("fi", "FI", (500,)),
    ("omega", "OMEGA", (700,)),
)
SINGLE_FIELDS = (("pmsl", "PMSL"), ("ps", "PS"), ("u_10m", "U_10M"), ("v_10m", "V_10M"))
# Senza questi il motore non puo' tracciare la linea; il resto arricchisce la
# diagnosi e puo' mancare.
REQUIRED = {"t850", "relhum850", "u850", "v850", "hsurf"}


def iso_hour(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")


def pressure_url(run: str, step: int, folder: str, name: str, level: int) -> str:
    return (f"{BASE_URL}/{run[8:10]}/{folder}/icon-eu_europe_regular-lat-lon_"
            f"pressure-level_{run}_{step:03d}_{level}_{name}.grib2.bz2")


def single_url(run: str, step: int, folder: str, name: str) -> str:
    return (f"{BASE_URL}/{run[8:10]}/{folder}/icon-eu_europe_regular-lat-lon_"
            f"single-level_{run}_{step:03d}_{name}.grib2.bz2")


def invariant_url(run: str) -> str:
    return (f"{BASE_URL}/{run[8:10]}/hsurf/icon-eu_europe_regular-lat-lon_"
            f"time-invariant_{run}_HSURF.grib2.bz2")


def wanted_files(run: str, hours: int) -> dict[tuple[str, int], str]:
    """(chiave campo, scadenza) -> URL.  La chiave e' ``t850``, ``pmsl``..."""
    wanted: dict[tuple[str, int], str] = {("hsurf", 0): invariant_url(run)}
    for step in range(hours + 1):
        for folder, name, levels in PRESSURE_FIELDS:
            for level in levels:
                wanted[(f"{folder}{level}", step)] = pressure_url(
                    run, step, folder, name, level
                )
        for folder, name in SINGLE_FIELDS:
            wanted[(folder.replace("_10m", "10"), step)] = single_url(
                run, step, folder, name
            )
    return wanted


def candidate_runs(now: datetime, count: int = 4) -> list[str]:
    """Gli ultimi run 00Z/12Z, dal piu' recente."""
    start = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start -= timedelta(hours=start.hour % 12)
    return [(start - timedelta(hours=12 * index)).strftime("%Y%m%d%H")
            for index in range(count)]


def _session():
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = "front-analysis/1.0"
    return session


def run_is_complete(session, run: str, hours: int) -> bool:
    """Un run e' pubblicato a pezzi: e' completo quando c'e' l'ultima ora."""
    try:
        for url in (pressure_url(run, hours, "t", "T", 850),
                    pressure_url(run, hours, "v", "V", 500)):
            if session.head(url, timeout=30).status_code != 200:
                return False
        return True
    except Exception:
        return False


def _download(session, url: str, destination: str, attempts: int = 4) -> None:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=120)
            if response.status_code == 404:
                raise FileNotFoundError(url)
            response.raise_for_status()
            data = bz2.decompress(response.content)
            if data[:4] != b"GRIB":
                raise ValueError("non e' un GRIB")
            with open(destination + ".part", "wb") as handle:
                handle.write(data)
            os.replace(destination + ".part", destination)
            return
        except FileNotFoundError:
            raise
        except Exception as error:  # rete, bz2 troncato
            last_error = error
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"{url}: {last_error}")


def download_run(run: str, hours: int, raw_dir: str, workers: int = 12,
                 *, reuse: bool = False) -> dict:
    """Scarica e decomprime.  Restituisce {chiave: {scadenza: percorso}}."""
    os.makedirs(raw_dir, exist_ok=True)
    wanted = wanted_files(run, hours)
    session = _session()
    got: dict[str, dict[int, str]] = {}
    failures: list[str] = []

    def fetch(item):
        (key, step), url = item
        destination = os.path.join(raw_dir, f"{key}_{step:03d}.grib2")
        # I file già scaricati appartengono a questo run e sono stati
        # rinominati solo a scrittura conclusa. I .part si riscaricano.
        if not reuse or not os.path.isfile(destination):
            _download(session, url, destination)
        return key, step, destination

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch, item) for item in wanted.items()]
        for future in as_completed(futures):
            try:
                key, step, destination = future.result()
                got.setdefault(key, {})[step] = destination
            except Exception as error:
                failures.append(str(error))
    if failures:
        print(f"   ICON-EU: {len(failures)} file non scaricati "
              f"(es. {failures[0][-90:]})", flush=True)
    return got


def saturation_pressure_water(temperature_k: np.ndarray) -> np.ndarray:
    celsius = temperature_k - 273.15
    return 611.2 * np.exp(17.62 * celsius / (243.12 + celsius))


def specific_humidity(relative_humidity_pct, temperature_k, pressure_pa):
    """q da RH (%), T (K) e p (Pa): Magnus sull'acqua, come RELHUM del DWD."""
    vapour = (np.clip(relative_humidity_pct, 0.0, 100.0) / 100.0
              * saturation_pressure_water(np.asarray(temperature_k, dtype=float)))
    return 0.622 * vapour / (pressure_pa - 0.378 * vapour)


def assemble(got: dict, grib_dir: str, hours: int) -> dict[str, str]:
    """Un GRIB per variabile con tutte le scadenze in ordine.

    Restituisce {nome: percorso} solo per i campi COMPLETI: una variabile a
    cui manca un'ora sfaserebbe l'intera serie rispetto alle altre.
    """
    import eccodes as ec

    os.makedirs(grib_dir, exist_ok=True)
    steps = list(range(hours + 1))
    paths: dict[str, str] = {}

    def complete(key: str) -> bool:
        if key == "hsurf":
            return 0 in got.get(key, {})
        return all(step in got.get(key, {}) for step in steps)

    for key in sorted(got):
        if key.startswith("relhum") or not complete(key):
            continue
        destination = os.path.join(grib_dir, f"{key}.grib")
        with open(destination, "wb") as out:
            for step in ([0] if key == "hsurf" else steps):
                with open(got[key][step], "rb") as handle:
                    out.write(handle.read())
        paths[key] = destination

    for level in (925, 850, 700):
        rh_key, t_key = f"relhum{level}", f"t{level}"
        if not (complete(rh_key) and complete(t_key)):
            continue
        destination = os.path.join(grib_dir, f"q{level}.grib")
        with open(destination, "wb") as out:
            for step in steps:
                with open(got[rh_key][step], "rb") as handle:
                    rh_message = ec.codes_new_from_message(handle.read())
                with open(got[t_key][step], "rb") as handle:
                    t_message = ec.codes_new_from_message(handle.read())
                try:
                    q = specific_humidity(
                        ec.codes_get_values(rh_message),
                        ec.codes_get_values(t_message),
                        level * 100.0,
                    )
                    # disciplina 0, categoria 1 (umidita'), numero 0:
                    # umidita' specifica
                    ec.codes_set(rh_message, "parameterNumber", 0)
                    ec.codes_set_values(rh_message, q)
                    out.write(ec.codes_get_message(rh_message))
                finally:
                    ec.codes_release(rh_message)
                    ec.codes_release(t_message)
        paths[f"q{level}"] = destination
    return paths


# --------------------------------------------------------------------------
# Ritaglio sul riquadro pubblicato
# --------------------------------------------------------------------------
def _piece_length_km(points: np.ndarray) -> float:
    if len(points) < 2:
        return 0.0
    mean_lat = np.deg2rad((points[:-1, 1] + points[1:, 1]) * 0.5)
    dx = (points[1:, 0] - points[:-1, 0]) * 111.32 * np.cos(mean_lat)
    dy = (points[1:, 1] - points[:-1, 1]) * 111.32
    return float(np.sum(np.hypot(dx, dy)))


def _arc_fractions(points: np.ndarray) -> np.ndarray:
    steps = np.hypot(*np.diff(points, axis=0).T)
    arc = np.concatenate(([0.0], np.cumsum(steps)))
    return arc / max(arc[-1], 1.0e-12)


def clip_feature(feature: dict, box=PUBLISH_BOX,
                 min_km: float = MIN_PUBLISHED_PIECE_KM) -> list[dict]:
    """Tiene i tratti della linea dentro il riquadro.

    I tratti per tipo (``segmentTypes``, in frazioni di lunghezza) vengono
    riportati sul pezzo ritagliato: un fronte freddo a ovest e caldo a est
    resta tale anche se del tratto freddo si vede solo l'ultima parte.
    """
    geometry = feature.get("geometry") or {}
    if geometry.get("type") != "LineString":
        return []
    points = np.asarray(geometry.get("coordinates"), dtype=float)
    if points.ndim != 2 or len(points) < 2:
        return []
    lon_min, lon_max, lat_min, lat_max = box
    inside = ((points[:, 0] >= lon_min) & (points[:, 0] <= lon_max)
              & (points[:, 1] >= lat_min) & (points[:, 1] <= lat_max))
    if bool(np.all(inside)):
        return [feature]
    fractions = _arc_fractions(points)
    segments = (feature.get("properties") or {}).get("segmentTypes")
    pieces = []
    index = 0
    while index < len(points):
        if not inside[index]:
            index += 1
            continue
        stop = index
        while stop + 1 < len(points) and inside[stop + 1]:
            stop += 1
        piece = points[index:stop + 1]
        if len(piece) >= 2 and _piece_length_km(piece) >= min_km:
            start_fraction, end_fraction = fractions[index], fractions[stop]
            span = max(end_fraction - start_fraction, 1.0e-9)
            properties = dict(feature.get("properties") or {})
            if isinstance(segments, list) and segments:
                remapped = []
                for segment in segments:
                    low = max(float(segment.get("start", 0.0)), start_fraction)
                    high = min(float(segment.get("end", 1.0)), end_fraction)
                    if high - low <= 1.0e-6:
                        continue
                    remapped.append({
                        **segment,
                        "start": round((low - start_fraction) / span, 3),
                        "end": round((high - start_fraction) / span, 3),
                    })
                if remapped:
                    remapped[0]["start"] = 0.0
                    remapped[-1]["end"] = 1.0
                    properties["segmentTypes"] = remapped
                    coverage: dict[str, float] = {}
                    for segment in remapped:
                        coverage[segment["type"]] = coverage.get(
                            segment["type"], 0.0
                        ) + segment["end"] - segment["start"]
                    if properties.get("frontType") != "occluded":
                        properties["frontType"] = max(coverage, key=coverage.get)
            properties["clippedToPublishBox"] = True
            pieces.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[round(float(x), 4), round(float(y), 4)]
                                    for x, y in piece],
                },
                "properties": properties,
            })
        index = stop + 1
    return pieces


def clip_collection(collection: dict, box=PUBLISH_BOX) -> dict:
    features = []
    for feature in collection.get("features", []):
        features.extend(clip_feature(feature, box))
    return {**collection, "features": features}


# --------------------------------------------------------------------------
# Analisi
# --------------------------------------------------------------------------
def analyse(paths: dict[str, str], run_dt: datetime, hours: int) -> dict:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from front_analysis_v12 import FRONT_METHOD, IconSynopticFrontAnalyzer

    def optional(name):
        return paths.get(name)

    analyzer = IconSynopticFrontAnalyzer(
        paths["t850"], paths["q850"], paths["u850"], paths["v850"], paths["hsurf"],
        pressure_path=optional("pmsl"),
        lower_temperature_path=optional("t925"),
        lower_humidity_path=optional("q925"),
        lower_u_wind_path=optional("u925"),
        lower_v_wind_path=optional("v925"),
        upper_temperature_path=optional("t700"),
        upper_humidity_path=optional("q700"),
        upper_u_wind_path=optional("u700"),
        upper_v_wind_path=optional("v700"),
        mid_u_wind_path=optional("u500"),
        mid_v_wind_path=optional("v500"),
        geopotential_500_path=optional("fi500"),
        surface_u_wind_path=optional("u10"),
        surface_v_wind_path=optional("v10"),
        surface_pressure_path=optional("ps"),
        omega_700_path=optional("omega700"),
        downsample=ANALYSIS_DOWNSAMPLE,
        bounds=ANALYSIS_BOUNDS,
        method=FRONT_METHOD,
        source=MODEL,
        tendency_window_hours=3,
        ml_guidance=None,
    )
    by_valid_time = {}
    grid_km = round(analyzer.dy_km, 1)
    try:
        if analyzer.available_hours != list(range(hours + 1)):
            raise ValueError("scadenze ICON-EU diverse da quelle orarie richieste")
        for hour in analyzer.available_hours:
            collection = clip_collection(analyzer.analyze(hour))
            collection["properties"]["analysisGridKm"] = grid_km
            collection["leadHours"] = int(hour)
            by_valid_time[iso_hour(run_dt + timedelta(hours=int(hour)))] = collection
        summary = dict(analyzer.analysis_summary or {})
        pipeline = {
            str(hour): dict(values)
            for hour, values in analyzer._pipeline_diag.items()
        }
    finally:
        analyzer.close()
    return {
        "schemaVersion": 1,
        "model": MODEL,
        "runTime": iso_hour(run_dt),
        "method": FRONT_METHOD,
        "analysisBounds": list(ANALYSIS_BOUNDS),
        "analysisGridKm": grid_km,
        "publishBox": list(PUBLISH_BOX),
        "analysisSummary": summary,
        "pipelineByHour": pipeline,
        "hours": by_valid_time,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run", help="run YYYYMMDDHH (default: ultimo completo)")
    parser.add_argument("--hours", type=int, default=72)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--workdir", default="icon_eu_tmp")
    parser.add_argument("--keep", action="store_true",
                        help="conserva e riusa i GRIB dello stesso run")
    args = parser.parse_args(argv)
    hours = int(np.clip(args.hours, 6, MAX_LEAD_HOURS))

    if os.path.exists(args.output):
        os.remove(args.output)  # mai lasciare i fronti di un run precedente
    run_dir = None
    try:
        session = _session()
        run = args.run
        if not run:
            for candidate in candidate_runs(datetime.now(timezone.utc)):
                if run_is_complete(session, candidate, hours):
                    run = candidate
                    break
        if not run:
            print("ICON-EU: nessun run completo disponibile.", flush=True)
            return 0
        run_dt = datetime.strptime(run, "%Y%m%d%H").replace(tzinfo=timezone.utc)
        print(f"ICON-EU: run {run}, {hours + 1} scadenze orarie.", flush=True)
        started = time.time()
        run_dir = os.path.join(args.workdir, run)
        raw_dir = os.path.join(run_dir, "raw")
        got = download_run(run, hours, raw_dir, reuse=args.keep)
        print(f"ICON-EU: {sum(len(steps) for steps in got.values())} GRIB disponibili "
              f"in {time.time() - started:.0f} s.", flush=True)
        paths = assemble(got, os.path.join(run_dir, "grib"), hours)
        if not args.keep:
            shutil.rmtree(raw_dir, ignore_errors=True)
        missing = sorted(
            name.replace("relhum", "q") for name in REQUIRED
            if name.replace("relhum", "q") not in paths
        )
        if missing:
            print(f"ICON-EU: campi indispensabili incompleti {missing}.", flush=True)
            return 0
        print(f"ICON-EU: {len(paths)} campi pronti in "
              f"{time.time() - started:.0f} s.", flush=True)
        result = analyse(paths, run_dt, hours)
        with open(args.output + ".part", "w", encoding="utf-8") as handle:
            json.dump(result, handle, allow_nan=False, separators=(",", ":"))
        os.replace(args.output + ".part", args.output)
        counts = [len(item["features"]) for item in result["hours"].values()]
        print(f"ICON-EU: fronti in {sum(bool(c) for c in counts)}/{len(counts)} "
              f"ore, {sum(counts)} linee, {time.time() - started:.0f} s.", flush=True)
    except Exception as error:  # la pipeline ripiega su ICON-2I
        print(f"ICON-EU: analisi non riuscita ({error}).", flush=True)
        if os.path.exists(args.output):
            os.remove(args.output)
    finally:
        if run_dir and not args.keep:
            shutil.rmtree(run_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
