"""Fronti sinottici da ICON-EU: le regole che non devono rompersi.

Lo script scarica dal DWD e gira il motore: qui non si scarica nulla.  Si
provano le parti che decidono che cosa finisce sulla mappa -- quale run, quali
file, come si ricava l'umidita', come si ritaglia una linea senza perderne il
tipo -- e l'abbinamento con le scadenze di ICON-2I, ripiego compreso.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import icon_eu_fronts as eu

ok = True


def prova(nome, condizione, dettaglio=""):
    global ok
    print(("PASS " if condizione else "FALLITO ") + nome + (" " + dettaglio if dettaglio else ""))
    ok = ok and bool(condizione)


# 1) Run: solo 00Z e 12Z, dal piu' recente.
runs = eu.candidate_runs(datetime(2026, 11, 12, 14, 49, tzinfo=timezone.utc))
prova("i run candidati sono 00Z/12Z a ritroso",
      runs[:3] == ["2026111212", "2026111200", "2026111112"], str(runs[:3]))

# 2) File: nomi del DWD e niente umidita' specifica (non e' pubblicata).
files = eu.wanted_files("2026111200", 72)
prova("un file per campo e scadenza", len(files) == 73 * 20 + 1, str(len(files)))
prova("nome DWD dei livelli di pressione",
      files[("t850", 6)].endswith(
          "/00/t/icon-eu_europe_regular-lat-lon_pressure-level_2026111200_006_850_T.grib2.bz2"))
prova("nome DWD dei campi al suolo",
      files[("u10", 72)].endswith(
          "/00/u_10m/icon-eu_europe_regular-lat-lon_single-level_2026111200_072_U_10M.grib2.bz2"))
prova("l'umidita' arriva come RELHUM",
      ("relhum850", 0) in files and not any(k[0].startswith("q") for k in files))

# 3) q da RH: aria satura a 10 gradi e 850 hPa ha circa 9 g/kg.
q = float(eu.specific_humidity(100.0, 283.15, 85000.0))
prova("umidita' specifica da RELHUM", 0.0088 < q < 0.0093, f"{q * 1000:.2f} g/kg")
prova("RH oltre 100 non crea vapore in piu'",
      abs(float(eu.specific_humidity(130.0, 283.15, 85000.0)) - q) < 1e-9)

# 4) Ritaglio: la linea esce dal riquadro a ovest; il tipo dei tratti resta.
lon = np.linspace(-14.0, 20.0, 69)
linea = {
    "type": "Feature",
    "geometry": {"type": "LineString",
                 "coordinates": [[float(x), 48.0] for x in lon]},
    "properties": {
        "frontType": "cold",
        "segmentTypes": [
            {"start": 0.0, "end": 0.6, "type": "cold", "certainty": 0.9},
            {"start": 0.6, "end": 1.0, "type": "warm", "certainty": 0.8},
        ],
    },
}
pezzi = eu.clip_feature(linea)
prova("il ritaglio tiene un solo pezzo", len(pezzi) == 1, str(len(pezzi)))
if pezzi:
    c = np.asarray(pezzi[0]["geometry"]["coordinates"])
    tratti = pezzi[0]["properties"]["segmentTypes"]
    prova("il pezzo sta dentro il riquadro",
          c[:, 0].min() >= eu.PUBLISH_BOX[0] and c[:, 0].max() <= eu.PUBLISH_BOX[1])
    # la linea intera cambia tipo a lon 6,4; nel pezzo (-6..20) e' a 0,477
    confine = (-14.0 + 0.6 * 34.0 - c[0, 0]) / (c[-1, 0] - c[0, 0])
    prova("i tratti coprono tutto il pezzo",
          tratti[0]["start"] == 0.0 and tratti[-1]["end"] == 1.0)
    prova("il cambio di tipo resta nello stesso punto geografico",
          abs(tratti[0]["end"] - confine) < 0.01,
          f"{tratti[0]['end']} atteso {confine:.3f}")
    prova("il tipo principale segue il tratto piu' lungo rimasto",
          pezzi[0]["properties"]["frontType"] == "warm",
          pezzi[0]["properties"]["frontType"])
dentro = dict(linea, geometry={"type": "LineString",
                               "coordinates": [[5.0, 44.0], [12.0, 45.0]]})
prova("una linea tutta dentro resta intatta", eu.clip_feature(dentro) == [dentro])
fuori = dict(linea, geometry={"type": "LineString",
                              "coordinates": [[-14.0, 58.0], [-8.0, 59.0]]})
prova("una linea tutta fuori sparisce", eu.clip_feature(fuori) == [])
moncone = dict(linea, geometry={"type": "LineString",
                                "coordinates": [[-9.0, 45.0], [-5.0, 45.0]]})
prova("un moncone sotto 200 km non si pubblica", eu.clip_feature(moncone) == [])

# 5) Abbinamento con ICON-2I per ora di validita', e ripiego.
import process_data

run_2i = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)


def scrivi(cartella, run_time, ore):
    percorso = os.path.join(cartella, "eu.json")
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump({"schemaVersion": 1, "model": "ICON-EU", "runTime": run_time,
                   "method": "prova", "hours": ore}, f)
    return percorso


buona = {"type": "FeatureCollection", "features": [linea],
         "properties": {"analysisStatus": "fronts-detected"}}
persa = {"type": "FeatureCollection", "features": [],
         "properties": {"analysisStatus": "unavailable"}}
with tempfile.TemporaryDirectory() as cartella:
    percorso = scrivi(cartella, "2026-11-12T00:00:00Z",
                      {"2026-11-12T12:00:00Z": buona, "2026-11-12T13:00:00Z": persa})
    ore, info = process_data.load_icon_eu_fronts(run_2i, percorso)
    prova("run ICON-EU di 12 ore prima: abbinato per ora di validita'",
          list(ore) == ["2026-11-12T12:00:00Z"] and info["runLagHours"] == 12.0)
    prova("un'ora non analizzata non si spaccia per 'nessun fronte'",
          "2026-11-12T13:00:00Z" not in ore)
    prova("la chiave e' quella che usa la pipeline",
          process_data.iso_z(run_2i) in ore)
    percorso = scrivi(cartella, "2026-11-11T00:00:00Z", {"2026-11-12T12:00:00Z": buona})
    prova("run ICON-EU di 36 ore prima: scartato, si usa ICON-2I",
          process_data.load_icon_eu_fronts(run_2i, percorso) == ({}, None))
    percorso = scrivi(cartella, "2026-11-13T00:00:00Z", {"2026-11-13T00:00:00Z": buona})
    prova("run ICON-EU successivo a ICON-2I: scartato",
          process_data.load_icon_eu_fronts(run_2i, percorso) == ({}, None))
    prova("file assente: ripiego silenzioso su ICON-2I",
          process_data.load_icon_eu_fronts(run_2i, os.path.join(cartella, "no.json")) == ({}, None))
    with open(os.path.join(cartella, "rotto.json"), "w") as f:
        f.write("{")
    prova("file rotto: ripiego su ICON-2I",
          process_data.load_icon_eu_fronts(run_2i, os.path.join(cartella, "rotto.json")) == ({}, None))

print("\nESITO: " + ("SUPERATO" if ok else "DA RIVEDERE"))
sys.stdout.flush()
os._exit(0 if ok else 1)
