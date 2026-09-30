"""La copertura nuvolosa per livelli di ICON-EU (DWD, dati aperti).

ICON-2I su MeteoHub pubblica sei livelli isobarici e solo la copertura per
piani (bassa, media, alta).  ICON-EU, il modello da cui ICON-2I prende i bordi
nella catena europea del DWD, pubblica invece la frazione di nube CLC su
venti livelli isobarici (1000-50 hPa) a 0,0625 gradi (circa 6,5 km), senza
registrazione, su https://opendata.dwd.de/weather/nwp/icon-eu/grib/.

E' la struttura verticale che il satellite non vede: quanti strati ci sono,
a che quota, con che copertura -- anche sotto una coltre alta.  Qui si
scaricano i livelli fino a 200 hPa per le ore del run ICON-2I, si ritagliano
sul dominio del volume e si interpolano sulla griglia ICON-2I.

Tutto facoltativo: un file che manca lascia il livello assente, un run non
ancora pubblicato fa ripiegare sul run precedente (il DWD gira ogni 3 ore).
"""

from __future__ import annotations

import bz2
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import numpy as np
import requests

BASE_URL = "https://opendata.dwd.de/weather/nwp/icon-eu/grib"
# Dal suolo alla tropopausa: sotto 200 hPa (11,8 km) le nubi del nostro volume.
LEVELS = (1000, 950, 925, 900, 875, 850, 825, 800, 775, 700, 600, 500, 400, 300, 250, 200)
# Quote dell'atmosfera standard ICAO dei livelli, km: le usa anche il browser.
LEVEL_HEIGHT_KM = {
    1000: 0.111, 950: 0.540, 925: 0.762, 900: 0.988, 875: 1.220, 850: 1.457,
    825: 1.700, 800: 1.949, 775: 2.204, 700: 3.012, 600: 4.206, 500: 5.574,
    400: 7.185, 300: 9.164, 250: 10.363, 200: 11.784,
}
# Il DWD pubblica un run ogni 3 ore; si risale al massimo di 12.
# Il dominio del volume in Europa: dove il satellite MTG vede bene e ICON-EU
# ha dati (ICON-EU copre 23,5 W - 62,5 E, 29,5 - 70,5 N).
EU_DOMAIN = {"south": 29.5, "north": 66.0, "west": -23.5, "east": 42.0}
# ICON-EU e' a 0,0625 gradi: mediato 2x2 fa 0,125 gradi (circa 12 km), piu'
# fine della struttura verticale che serve e un quarto dei byte.
COARSEN = 2
METHOD = "icon-eu-cloud-profile-v1"
RUN_STEP_HOURS = 3
MAX_RUN_LOOKBACK_HOURS = 12
MAX_STEP_HOURS = 120
WORKERS = 8
USER_AGENT = "MeteoHub-Mobile-Synoptic/1.0 (nubi 3D)"


def field_name(level: int) -> str:
    """Nome del campo nella piastrella ambiente (8 caratteri al massimo)."""
    return f"c{int(level)}"


def clc_url(run: datetime, step: int, level: int) -> str:
    return (f"{BASE_URL}/{run:%H}/clc/icon-eu_europe_regular-lat-lon_pressure-level_"
            f"{run:%Y%m%d%H}_{int(step):03d}_{int(level)}_CLC.grib2.bz2")


def decode_regular_grib(data: bytes):
    """Valori, latitudini e longitudini (crescenti) di un GRIB2 regular_ll."""
    import eccodes

    gid = eccodes.codes_new_from_message(data)
    try:
        ni = eccodes.codes_get(gid, "Ni")
        nj = eccodes.codes_get(gid, "Nj")
        lat0 = eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
        lat1 = eccodes.codes_get(gid, "latitudeOfLastGridPointInDegrees")
        lon0 = eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
        lon1 = eccodes.codes_get(gid, "longitudeOfLastGridPointInDegrees")
        values = eccodes.codes_get_values(gid).reshape(nj, ni).astype(np.float32)
        missing = eccodes.codes_get(gid, "missingValue")
    finally:
        eccodes.codes_release(gid)
    values[values == missing] = np.nan
    if lon0 > 180:
        lon0 -= 360
    if lon1 > 180:
        lon1 -= 360
    lats = np.linspace(lat0, lat1, nj)
    lons = np.linspace(lon0, lon1, ni)
    if lats[0] > lats[-1]:
        lats, values = lats[::-1], values[::-1, :]
    return values, lats, lons


class IconEuCloudProfile:
    """CLC per livello e per ora di validita', ritagliata sul dominio."""

    def __init__(self, lat_bounds, lon_bounds, margin_deg: float = 0.2, factor: int = 1) -> None:
        self.factor = max(1, int(factor))
        self.south, self.north = min(lat_bounds) - margin_deg, max(lat_bounds) + margin_deg
        self.west, self.east = min(lon_bounds) - margin_deg, max(lon_bounds) + margin_deg
        self.latitudes = None
        self.longitudes = None
        # valid time -> livello -> copertura % (uint8, 255 = mancante)
        self.data: dict[datetime, dict[int, np.ndarray]] = {}
        # valid time -> base/cima delle nubi convettive (m sul mare)
        self.single: dict[datetime, dict[str, np.ndarray]] = {}
        self.run: datetime | None = None
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    # --- scaricamento --------------------------------------------------------
    def _crop(self, result):
        if result is None:
            return None
        values, lats, lons = result
        jlat = (lats >= self.south) & (lats <= self.north)
        jlon = (lons >= self.west) & (lons <= self.east)
        crop = values[np.ix_(jlat, jlon)].astype(np.float32)
        clat, clon = lats[jlat], lons[jlon]
        f = self.factor
        if f > 1:
            ny, nx = (crop.shape[0] // f) * f, (crop.shape[1] // f) * f
            with np.errstate(invalid="ignore"):
                crop = np.nanmean(np.nanmean(crop[:ny, :nx].reshape(ny // f, f, nx // f, f), axis=3), axis=1)
            clat = clat[:ny].reshape(-1, f).mean(axis=1)
            clon = clon[:nx].reshape(-1, f).mean(axis=1)
        if self.latitudes is None:
            self.latitudes, self.longitudes = clat, clon
        return crop if crop.shape == (self.latitudes.size, self.longitudes.size) else None

    def _get(self, url):
        for _ in range(3):
            try:
                r = self.session.get(url, timeout=(15, 120))
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return decode_regular_grib(bz2.decompress(r.content))
            except Exception:
                continue
        return None

    def _exists(self, url: str) -> bool:
        try:
            r = self.session.head(url, timeout=(10, 30), allow_redirects=True)
            return r.status_code == 200
        except Exception:
            return False

    def choose_run(self, target_run: datetime, first_lead: int = 0):
        """Il run ICON-EU piu' recente, non successivo a quello ICON-2I, che
        ha gia' pubblicato l'ora di validita' iniziale."""
        base = target_run.replace(minute=0, second=0, microsecond=0)
        base -= timedelta(hours=base.hour % RUN_STEP_HOURS)
        for back in range(0, MAX_RUN_LOOKBACK_HOURS + 1, RUN_STEP_HOURS):
            run = base - timedelta(hours=back)
            step = int((target_run - run).total_seconds() // 3600) + int(first_lead)
            if 0 <= step <= MAX_STEP_HOURS and self._exists(clc_url(run, step, LEVELS[-1])):
                return run
        return None

    def _fetch(self, run: datetime, step: int, level: int):
        url = clc_url(run, step, level)
        for _ in range(3):
            try:
                r = self.session.get(url, timeout=(15, 120))
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return decode_regular_grib(bz2.decompress(r.content))
            except Exception:
                continue
        return None

    def download(self, target_run: datetime, leads, workers: int = WORKERS) -> int:
        """Scarica le ore ``target_run + lead``; restituisce i campi letti."""
        leads = sorted({int(v) for v in leads})
        if not leads:
            return 0
        run = self.choose_run(target_run, leads[0])
        if run is None:
            return 0
        self.run = run
        offset = int((target_run - run).total_seconds() // 3600)
        jobs = [(lead, level) for lead in leads for level in LEVELS
                if 0 <= lead + offset <= MAX_STEP_HOURS]

        def one(job):
            lead, level = job
            return job, self._fetch(run, lead + offset, level)

        count = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for (lead, level), result in pool.map(one, jobs):
                if result is None:
                    continue
                values, lats, lons = result
                jlat = (lats >= self.south) & (lats <= self.north)
                jlon = (lons >= self.west) & (lons <= self.east)
                if not jlat.any() or not jlon.any():
                    continue
                crop = values[np.ix_(jlat, jlon)]
                clat, clon = lats[jlat], lons[jlon]
                if self.factor > 1:
                    f = self.factor
                    ny, nx = (crop.shape[0] // f) * f, (crop.shape[1] // f) * f
                    blocchi = crop[:ny, :nx].reshape(ny // f, f, nx // f, f)
                    with np.errstate(invalid="ignore"):
                        crop = np.nanmean(np.nanmean(blocchi, axis=3), axis=1)
                    clat = clat[:ny].reshape(-1, f).mean(axis=1)
                    clon = clon[:nx].reshape(-1, f).mean(axis=1)
                if self.latitudes is None:
                    self.latitudes, self.longitudes = clat, clon
                if crop.shape != (self.latitudes.size, self.longitudes.size):
                    continue
                packed = np.where(np.isfinite(crop), np.clip(np.round(crop), 0, 100), 255).astype(np.uint8)
                valid = target_run + timedelta(hours=lead)
                self.data.setdefault(valid, {})[level] = packed
                count += 1
        # Base e cima delle nubi convettive: la scala delle torri in Europa.
        singoli = [(lead, var) for lead in leads for var in ("HBAS_CON", "HTOP_CON")
                   if 0 <= lead + offset <= MAX_STEP_HOURS]

        def singolo(job):
            lead, var = job
            return job, self._crop(self._get(single_level_url(run, lead + offset, var)))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for (lead, var), arr in pool.map(singolo, singoli):
                valid = target_run + timedelta(hours=lead)
                if arr is not None and valid in self.data:
                    self.single.setdefault(valid, {})[var.lower().replace("_con", "")] = arr
        return count

    # --- lettura ---------------------------------------------------------------
    def levels_at(self, valid: datetime, lat, lon) -> dict:
        """Copertura % per livello sulla griglia (lat, lon) data, o {}."""
        found = self.data.get(valid)
        if not found or self.latitudes is None:
            return {}
        from scipy.interpolate import RegularGridInterpolator

        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        la, lo = np.meshgrid(lat, lon, indexing="ij")
        points = np.stack([np.clip(la, self.latitudes[0], self.latitudes[-1]),
                           np.clip(lo, self.longitudes[0], self.longitudes[-1])], axis=-1)
        out = {}
        for level, packed in found.items():
            values = packed.astype(np.float32)
            values[packed == 255] = np.nan
            interp = RegularGridInterpolator((self.latitudes, self.longitudes), values,
                                             bounds_error=False, fill_value=np.nan)
            out[level] = interp(points)
        return out

    # --- piastrelle per il browser ---------------------------------------------
    def write(self, directory, target_run: datetime) -> dict:
        """Una piastrella per ora (formato NUBA, campi c<livello> in %) e
        ``index.json``; la stessa struttura dell'ambiente ICON-2I, cosi' il
        browser e l'unione delle ore passate funzionano uguali."""
        import json
        import os

        from .environment import Tile, _write_atomic, iso, tile_name

        if not self.data or self.latitudes is None:
            raise ValueError("nessuna ora ICON-EU")
        os.makedirs(directory, exist_ok=True)
        entries = []
        for valid in sorted(self.data):
            fields = {}
            for level, packed in self.data[valid].items():
                values = packed.astype(np.float64)
                values[packed == 255] = np.nan
                fields[field_name(level)] = values
            for name, values in self.single.get(valid, {}).items():
                # HBAS/HTOP: -999 o 0 dove non c'e' convezione nel modello.
                v = np.asarray(values, dtype=np.float64)
                fields[name] = np.where(v > 10.0, v, np.nan)
            tile = Tile(valid, self.latitudes, self.longitudes, fields)
            name = tile_name(valid)
            _write_atomic(os.path.join(directory, name), tile.to_bytes())
            lead = int((valid - target_run).total_seconds() // 3600)
            entries.append({"valid": iso(valid), "run": iso(self.run or target_run), "lead": lead, "file": name})
        index = {"method": METHOD, "latestRun": iso(target_run), "hours": entries}
        _write_atomic(os.path.join(directory, "index.json"),
                      json.dumps(index, separators=(",", ":")).encode("utf-8"))
        return index


# --- i livelli NATIVI del modello (74, dal suolo a ~23 km) ---------------------
# Sotto i 15 km ce ne sono una sessantina, a 130-300 m l'uno dall'altro: tre
# volte i livelli isobarici. Per ognuno: frazione di nube CLC e acqua e
# ghiaccio di nube (QC, QI), cioe' QUANTO e' densa la nube, non solo se c'e'.
# Le quote vengono dal file fisso HHL (quota dei mezzi livelli sul mare).
NATIVE_FIRST_LEVEL = 14          # ~15-16 km: sopra non ci sono nubi del volume
NATIVE_LAST_LEVEL = 74           # il livello piu' basso, sul suolo
VOLUME_DZ_KM = 0.25              # la colonna ricampionata a quote regolari
VOLUME_TOP_KM = 16.0
VOLUME_METHOD = "icon-eu-cloud-volume-v2"
VOLUME_MAGIC = b"NUBV"
# Il contenuto d'acqua + ghiaccio (g/kg) in 8 bit: quadratico fino a 2 g/kg,
# fine dove la nube e' tenue.
CONDENSATE_MAX_G_KG = 2.0
# LA NUBE FISICA (v2): per ogni voxel il contenuto d'acqua liquida e di
# ghiaccio in g/m3 (q * densita' dell'aria), la temperatura (la fase), la
# corrente verticale (dove sale l'aria: le cupole) e la turbolenza (quanto e'
# frastagliato il bordo). In 8 bit:
#  - LWC quadratico fino a 3 g/m3 (i cumuli arrivano a 1-3, gli strati 0,1-0,5);
#  - IWC quadratico fino a 1 g/m3 (i cirri 0,001-0,1, le incudini fino a ~1);
#  - T lineare a 0,5 K, da -90 a +37 C;
#  - w lineare a 0,1 m/s, +-12,7 m/s (codice 127 = fermo);
#  - TKE quadratica fino a 25 m2/s2.
LWC_MAX_G_M3 = 3.0
IWC_MAX_G_M3 = 1.0
TKE_MAX = 25.0
R_SECCA = 287.05       # J/(kg K), costante dei gas dell'aria secca
VOLUME_FULL_VARS = ("CLC", "QC", "QI", "T", "P")
VOLUME_HALF_VARS = ("W", "TKE")


def model_level_url(run: datetime, step: int, level: int, var: str) -> str:
    return (f"{BASE_URL}/{run:%H}/{var.lower()}/icon-eu_europe_regular-lat-lon_model-level_"
            f"{run:%Y%m%d%H}_{int(step):03d}_{int(level)}_{var.upper()}.grib2.bz2")


def hhl_url(run: datetime, half_level: int) -> str:
    return (f"{BASE_URL}/{run:%H}/hhl/icon-eu_europe_regular-lat-lon_time-invariant_"
            f"{run:%Y%m%d%H}_{int(half_level)}_HHL.grib2.bz2")


def single_level_url(run: datetime, step: int, var: str) -> str:
    return (f"{BASE_URL}/{run:%H}/{var.lower()}/icon-eu_europe_regular-lat-lon_single-level_"
            f"{run:%Y%m%d%H}_{int(step):03d}_{var.upper()}.grib2.bz2")


def resample_columns(values, heights_km, dz_km=VOLUME_DZ_KM, top_km=VOLUME_TOP_KM):
    """Da livelli nativi (k, ny, nx; quote decrescenti con k) a quote regolari.

    Interpolazione lineare in quota fra i due livelli che racchiudono ogni
    quota; sotto il livello piu' basso (sottosuolo) e sopra il piu' alto 0.
    """
    values = np.asarray(values, dtype=np.float32)
    heights = np.asarray(heights_km, dtype=np.float32)
    zs = np.arange(0.0, top_km + 1e-6, dz_km, dtype=np.float32)
    out = np.zeros((zs.size,) + values.shape[1:], dtype=np.float32)
    for j, z in enumerate(zs):
        found = np.zeros(values.shape[1:], dtype=bool)
        for k in range(values.shape[0] - 1):
            upper, lower = heights[k], heights[k + 1]
            inside = (~found) & (z <= upper) & (z >= lower)
            if not inside.any():
                continue
            w = np.where(upper > lower, (z - lower) / np.maximum(upper - lower, 1e-6), 0.0)
            v = values[k + 1] + (values[k] - values[k + 1]) * w
            out[j] = np.where(inside, v, out[j])
            found |= inside
    return zs, out


def air_density(p_pa, t_k):
    """Densita' dell'aria (kg/m3) dall'equazione di stato: rho = p / (R T).
    (Il vapore la cambia di meno dell'1%: trascurato.)"""
    t = np.maximum(np.asarray(t_k, dtype=np.float32), 150.0)
    return np.asarray(p_pa, dtype=np.float32) / (R_SECCA * t)


def half_to_full(half):
    """Dai mezzi livelli (k+1, ...) ai livelli pieni (k, ...): la media dei
    due mezzi livelli che racchiudono ogni livello pieno (W e TKE in ICON)."""
    half = np.asarray(half, dtype=np.float32)
    return 0.5 * (half[:-1] + half[1:])


def encode_quadratic(values, maximum):
    v = np.clip(np.nan_to_num(np.asarray(values, dtype=np.float32), nan=0.0), 0.0, maximum)
    return np.round(np.sqrt(v / maximum) * 254).astype(np.uint8)


def encode_linear(values, scale, offset):
    v = np.nan_to_num(np.asarray(values, dtype=np.float32), nan=offset)
    return np.clip(np.round((v - offset) / scale), 0, 254).astype(np.uint8)


def physical_volume_fields(clc, qc, qi, t_k, p_pa, w_half, tke_half, heights_km):
    """I campi fisici del volume, ricampionati ogni 250 m.

    clc, qc, qi, t_k, p_pa: livelli pieni (k, ny, nx); w_half, tke_half:
    mezzi livelli (k+1, ny, nx). Restituisce (quote, campi per volume_to_bytes).
    """
    rho = air_density(p_pa, t_k)
    lwc = np.maximum(np.nan_to_num(qc), 0.0) * rho * 1000.0     # g/m3
    iwc = np.maximum(np.nan_to_num(qi), 0.0) * rho * 1000.0
    w = half_to_full(np.nan_to_num(w_half))
    tke = half_to_full(np.maximum(np.nan_to_num(tke_half), 0.0))
    zs, clc_z = resample_columns(np.nan_to_num(clc), heights_km)
    _, lwc_z = resample_columns(lwc, heights_km)
    _, iwc_z = resample_columns(iwc, heights_km)
    _, t_z = resample_columns(np.nan_to_num(t_k - 273.15, nan=0.0), heights_km)
    _, w_z = resample_columns(w, heights_km)
    _, tke_z = resample_columns(tke, heights_km)
    # Sotto il suolo la colonna ricampionata vale 0: la temperatura li' non ha
    # senso, e 0 C sarebbe un falso zero termico. Si marca mancante (255).
    sotto = np.zeros_like(t_z, dtype=bool)
    sotto[:] = np.asarray(heights_km)[-1][None] > zs[:, None, None]
    t_codes = encode_linear(t_z, 0.5, -90.0)
    t_codes[sotto] = 255
    fields = {
        "clc": (0, np.clip(np.round(clc_z), 0, 100).astype(np.uint8), 1.0, 0.0),
        "lwc": (1, encode_quadratic(lwc_z, LWC_MAX_G_M3), LWC_MAX_G_M3, 0.0),
        "iwc": (1, encode_quadratic(iwc_z, IWC_MAX_G_M3), IWC_MAX_G_M3, 0.0),
        "t": (0, t_codes, 0.5, -90.0),
        "w": (0, encode_linear(w_z, 0.1, -12.7), 0.1, -12.7),
        "tke": (1, encode_quadratic(tke_z, TKE_MAX), TKE_MAX, 0.0),
    }
    return zs, fields


def encode_condensate(q_kg_kg):
    g = np.clip(np.nan_to_num(np.asarray(q_kg_kg, dtype=np.float32), nan=0.0) * 1000.0, 0.0, CONDENSATE_MAX_G_KG)
    return np.round(np.sqrt(g / CONDENSATE_MAX_G_KG) * 254).astype(np.uint8)


def volume_to_bytes(valid, lats, lons, zs, fields) -> bytes:
    """Piastrella di volume (gzip, little-endian)::

        "NUBV" u8 versione u8 campi u16 nx u16 ny u16 nz
        f32 sud f32 nord f32 ovest f32 est  f32 z0_km f32 dz_km
        per campo: 8 byte nome, u8 codifica (0 lineare, 1 quadratica),
                   f32 scala, f32 offset
        per campo: nz*ny*nx uint8, ordine (z, y, x), riga 0 = sud; 255 = mancante
    """
    import gzip
    import struct

    nz, ny, nx = next(iter(fields.values()))[1].shape
    head = VOLUME_MAGIC + struct.pack("<BBHHH", 1, len(fields), nx, ny, nz)
    head += struct.pack("<ffffff", float(lats[0]), float(lats[-1]), float(lons[0]), float(lons[-1]),
                        float(zs[0]), float(zs[1] - zs[0]))
    body = b""
    for name, (encoding, codes, scale, offset) in fields.items():
        head += name.encode("ascii").ljust(8, b"\0") + struct.pack("<Bff", encoding, scale, offset)
        body += np.ascontiguousarray(codes, dtype=np.uint8).tobytes()
    return gzip.compress(head + body, compresslevel=9, mtime=0)


def volume_from_bytes(data: bytes):
    import gzip
    import struct

    raw = gzip.decompress(data)
    if raw[:4] != VOLUME_MAGIC:
        raise ValueError("piastrella di volume non riconosciuta")
    _, count, nx, ny, nz = struct.unpack_from("<BBHHH", raw, 4)
    s, n, w, e, z0, dz = struct.unpack_from("<ffffff", raw, 12)
    pos, specs = 36, []
    for _ in range(count):
        name = raw[pos:pos + 8].rstrip(b"\0").decode("ascii")
        encoding, scale, offset = struct.unpack_from("<Bff", raw, pos + 8)
        specs.append((name, encoding, scale, offset))
        pos += 17
    fields = {}
    for name, encoding, scale, offset in specs:
        codes = np.frombuffer(raw, dtype=np.uint8, count=nx * ny * nz, offset=pos).reshape(nz, ny, nx)
        pos += nx * ny * nz
        if encoding == 1:
            values = (codes.astype(np.float32) / 254.0) ** 2 * scale + offset
        else:
            values = codes.astype(np.float32) * scale + offset
        fields[name] = np.where(codes == 255, np.nan, values)
    return {"south": s, "north": n, "west": w, "east": e, "z0": z0, "dz": dz, "fields": fields}


class IconEuCloudVolume(IconEuCloudProfile):
    """La colonna di nube di ICON-EU sui livelli nativi, a quote regolari."""

    def __init__(self, lat_bounds, lon_bounds, factor: int = 3) -> None:
        super().__init__(lat_bounds, lon_bounds, margin_deg=0.0, factor=factor)
        self.tiles: dict[datetime, bytes] = {}
        self.heights_km = None  # (livelli, ny, nx) quote dei livelli pieni

    def load_heights(self, run: datetime, workers: int = WORKERS) -> bool:
        halves = list(range(NATIVE_FIRST_LEVEL, NATIVE_LAST_LEVEL + 2))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            got = list(pool.map(lambda h: self._crop(self._get(hhl_url(run, h))), halves))
        if any(g is None for g in got):
            return False
        half = np.stack(got) / 1000.0
        self.heights_km = 0.5 * (half[:-1] + half[1:])   # livelli pieni
        return True

    def download(self, target_run: datetime, leads, workers: int = WORKERS) -> int:
        leads = sorted({int(v) for v in leads})
        run = self.choose_run(target_run, leads[0]) if leads else None
        if run is None or not self.load_heights(run, workers):
            return 0
        self.run = run
        offset = int((target_run - run).total_seconds() // 3600)
        levels = list(range(NATIVE_FIRST_LEVEL, NATIVE_LAST_LEVEL + 1))
        count = 0
        for lead in leads:
            step = lead + offset
            if not 0 <= step <= MAX_STEP_HOURS:
                continue
            halves = levels + [NATIVE_LAST_LEVEL + 1]
            jobs = ([(var, lv) for var in VOLUME_FULL_VARS for lv in levels]
                    + [(var, lv) for var in VOLUME_HALF_VARS for lv in halves])
            with ThreadPoolExecutor(max_workers=workers) as pool:
                got = list(pool.map(lambda j: self._crop(self._get(model_level_url(run, step, j[1], j[0]))), jobs))
            per = {var: [] for var in VOLUME_FULL_VARS + VOLUME_HALF_VARS}
            for (var, _), arr in zip(jobs, got):
                per[var].append(arr)
            # Senza copertura, temperatura o pressione la colonna non si ricostruisce.
            if any(a is None for v in ("CLC", "T", "P") for a in per[v]):
                continue
            zero = np.zeros_like(per["CLC"][0])
            pila = lambda v: np.stack([a if a is not None else zero for a in per[v]])
            zs, fields = physical_volume_fields(
                pila("CLC"), pila("QC"), pila("QI"), pila("T"), pila("P"),
                pila("W"), pila("TKE"), self.heights_km)
            valid = target_run + timedelta(hours=lead)
            self.tiles[valid] = volume_to_bytes(valid, self.latitudes, self.longitudes, zs, fields)
            count += 1
        return count

    def write(self, directory, target_run: datetime) -> dict:
        import json
        import os

        from .environment import _write_atomic, iso, tile_name

        if not self.tiles:
            raise ValueError("nessuna ora del volume ICON-EU")
        os.makedirs(directory, exist_ok=True)
        entries = []
        for valid in sorted(self.tiles):
            name = tile_name(valid).replace(".bin.gz", ".vol.gz")
            _write_atomic(os.path.join(directory, name), self.tiles[valid])
            lead = int((valid - target_run).total_seconds() // 3600)
            entries.append({"valid": iso(valid), "run": iso(self.run or target_run), "lead": lead, "file": name})
        index = {"method": VOLUME_METHOD, "latestRun": iso(target_run), "hours": entries}
        _write_atomic(os.path.join(directory, "index.json"),
                      json.dumps(index, separators=(",", ":")).encode("utf-8"))
        return index
