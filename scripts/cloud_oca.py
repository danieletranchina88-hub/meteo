"""Nubi 3D, fase 3b: le proprieta' ottiche delle nubi misurate da EUMETSAT.

Il prodotto OCA (Optimal Cloud Analysis) di MTG-FCI, EO:EUM:DAT:0684, esce
ogni 10 minuti sul disco intero a 2 km: per ogni pixel lo spessore ottico
(fino a due strati), il raggio efficace delle particelle, la fase, la
pressione e la quota della cima. Qui si scarica dal Data Store con le
credenziali del repository (segreti EUMETSAT_CONSUMER_KEY/SECRET, mai
stampati), si riporta sulla griglia nativa del volume ICON-EU (0,1875 gradi,
le stesse colonne che il browser assimila) e si pubblica come piastrella
NUBV a un solo livello.

Per ogni colonna, fra i pixel OCA che vi cadono:
  frac  frazione di pixel nuvolosi
  cot1  log10 dello spessore ottico medio dello strato alto (dentro la nube)
  cot2  log10 dello spessore ottico medio dello strato basso (solo dove c'e')
  ml    frazione dei pixel nuvolosi con due strati
  zt1   quota della cima dello strato alto, km
  zt2   quota della cima dello strato basso, km (dalla pressione)
  reff  raggio efficace, um
  ice   frazione di ghiaccio (fase OCA)

    python scripts/cloud_oca.py --out data_weather/cloud_oca --hours 3
    python scripts/cloud_oca.py --probe      # struttura di un file, niente pubblicazione
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import struct
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import numpy as np

COLLECTION = "EO:EUM:DAT:0684"
API = "https://api.eumetsat.int"
METHOD = "eumetsat-oca-mtg-v1"
MAGIC = b"NUBV"

# La griglia del volume ICON-EU (NUBV v2): stesse colonne.
SUD, NORD, OVEST, EST, PASSO = 29.5625, 65.9375, -23.4375, 41.8125, 0.1875
NY = int(round((NORD - SUD) / PASSO)) + 1
NX = int(round((EST - OVEST) / PASSO)) + 1

# nome -> (scala, offset): valore = codice * scala + offset, 255 mancante
CAMPI = {
    "frac": (1 / 254, 0.0),
    "cot1": (3.5 / 254, -1.0),
    "cot2": (3.5 / 254, -1.0),
    "ml": (1 / 254, 0.0),
    "zt1": (0.1, 0.0),
    "zt2": (0.1, 0.0),
    "reff": (0.5, 0.0),
    "ice": (1 / 254, 0.0),
}


def log(msg: str) -> None:
    print(msg, flush=True)


# --- Data Store ------------------------------------------------------------

def token(session) -> str:
    key = os.environ.get("EUMETSAT_CONSUMER_KEY", "")
    secret = os.environ.get("EUMETSAT_CONSUMER_SECRET", "")
    log("credenziali EUMETSAT: " + ("presenti" if key and secret else "ASSENTI"))
    if not (key and secret):
        raise SystemExit(2)
    r = session.post(API + "/token", data={"grant_type": "client_credentials"},
                     auth=(key, secret), timeout=60)
    log("token: HTTP %d" % r.status_code)
    r.raise_for_status()
    return r.json()["access_token"]


def cerca(session, inizio: datetime, fine: datetime) -> list[dict]:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    r = session.get(API + "/data/search-products/1.0.0/os", params={
        "pi": COLLECTION, "dtstart": inizio.strftime(fmt), "dtend": fine.strftime(fmt),
        "format": "json", "c": 100}, timeout=60)
    r.raise_for_status()
    prodotti = []
    for f in r.json().get("features", []):
        p = f.get("properties", {})
        m = re.search(r"_(\d{14})_(\d{14})_N_", f["id"])
        voci = [e.get("title", "") for e in p.get("links", {}).get("sip-entries", [])]
        nc = [v for v in voci if v.endswith(".nc")]
        if not m or not nc:
            continue
        t0 = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        prodotti.append({"id": f["id"], "inizio": t0, "nc": nc[0]})
    prodotti.sort(key=lambda p: p["inizio"])
    return prodotti


def scarica(session, tok: str, prodotto: dict, dove: str) -> str:
    url = "%s/data/download/1.0.0/collections/%s/products/%s/entry" % (
        API, quote(COLLECTION, safe=""), quote(prodotto["id"], safe=""))
    percorso = os.path.join(dove, "oca.nc")
    t = time.time()
    with session.get(url, params={"name": prodotto["nc"]}, headers={"Authorization": "Bearer " + tok},
                     stream=True, timeout=(30, 300)) as r:
        log("download %s: HTTP %d" % (prodotto["inizio"].strftime("%H:%M"), r.status_code))
        r.raise_for_status()
        with open(percorso, "wb") as out:
            for pezzo in r.iter_content(1 << 20):
                out.write(pezzo)
    log("  %.0f MB in %.0f s" % (os.path.getsize(percorso) / 1e6, time.time() - t))
    return percorso


# --- geometria geostazionaria ----------------------------------------------

def proiezione(ds):
    p = ds.variables["mtg_geos_projection"]
    a = float(p.getncattr("semi_major_axis"))
    h = float(p.getncattr("perspective_point_height"))
    rf = float(p.getncattr("inverse_flattening")) if "inverse_flattening" in p.ncattrs() else 298.257223563
    lon0 = float(p.getncattr("longitude_of_projection_origin")) if "longitude_of_projection_origin" in p.ncattrs() else 0.0
    return a, h, rf, lon0


def trasformatori(a, h, rf, lon0):
    from pyproj import CRS, Transformer
    geos = CRS.from_dict({"proj": "geos", "a": a, "rf": rf, "h": h, "lon_0": lon0,
                          "sweep": "y", "units": "m"})
    avanti = Transformer.from_crs("EPSG:4326", geos, always_xy=True)
    indietro = Transformer.from_crs(geos, "EPSG:4326", always_xy=True)
    return avanti, indietro


def ritaglio(x, y, h, avanti):
    """Righe e colonne del file che coprono il dominio (con margine).

    Come nel lettore satpy fci_l2_nc: la coordinata proiettata e' -x*h in
    orizzontale e y*h in verticale (x, y angoli di scansione in radianti).
    """
    lon = np.concatenate([np.linspace(OVEST, EST, 200), np.full(200, EST),
                          np.linspace(EST, OVEST, 200), np.full(200, OVEST)])
    lat = np.concatenate([np.full(200, SUD), np.linspace(SUD, NORD, 200),
                          np.full(200, NORD), np.linspace(NORD, SUD, 200)])
    X, Y = avanti.transform(lon, lat)
    ok = np.isfinite(X) & np.isfinite(Y)
    fx, fy = -np.asarray(X)[ok] / h, np.asarray(Y)[ok] / h
    dx, dy = float(x[1] - x[0]), float(y[1] - y[0])
    cols = (fx - float(x[0])) / dx
    rows = (fy - float(y[0])) / dy
    c0 = max(0, int(np.floor(cols.min())) - 4)
    c1 = min(len(x), int(np.ceil(cols.max())) + 5)
    r0 = max(0, int(np.floor(rows.min())) - 4)
    r1 = min(len(y), int(np.ceil(rows.max())) + 5)
    return r0, r1, c0, c1


def lettura(var, r0, r1, c0, c1, righe, colonne):
    """Legge una variabile (eventualmente con la dimensione degli strati)."""
    dims = var.dimensions
    idx = []
    for d in dims:
        if d == righe:
            idx.append(slice(r0, r1))
        elif d == colonne:
            idx.append(slice(c0, c1))
        else:
            idx.append(slice(None))
    arr = var[tuple(idx)]
    arr = np.ma.filled(np.ma.masked_invalid(np.ma.asarray(arr, dtype=np.float64)), np.nan)
    # le dimensioni riga/colonna in fondo
    perm = [i for i, d in enumerate(dims) if d not in (righe, colonne)] + [dims.index(righe), dims.index(colonne)]
    return np.transpose(arr, perm)


def quota_da_pressione(p_hpa):
    return 44.3308 * (1.0 - np.power(np.clip(p_hpa, 1.0, 1100.0) / 1013.25, 0.190263))


# --- elaborazione ---------------------------------------------------------

def descrivi(ds) -> None:
    log("dimensioni: " + ", ".join("%s=%d" % (k, len(v)) for k, v in ds.dimensions.items()))
    for nome, v in ds.variables.items():
        attrs = {k: v.getncattr(k) for k in v.ncattrs()
                 if k in ("units", "long_name", "flag_values", "flag_meanings", "scale_factor",
                          "add_offset", "_FillValue", "valid_range")}
        log("  %s %s %s %s" % (nome, v.dtype, v.dimensions, attrs))
    p = ds.variables.get("mtg_geos_projection")
    if p is not None:
        log("proiezione: " + str({k: p.getncattr(k) for k in p.ncattrs()}))
    x, y = ds.variables["x"][:], ds.variables["y"][:]
    log("x: %.6f .. %.6f  y: %.6f .. %.6f (radianti)" % (x[0], x[-1], y[0], y[-1]))


def fase_ghiaccio(var):
    """Dai valori della fase: quali sono ghiaccio (o strato alto di ghiaccio).

    Nel netCDF OCA la fase e' un tipo enum (nome -> valore); nei prodotti che
    usano i flag CF ci sono flag_values e flag_meanings.
    """
    enum = getattr(getattr(var, "datatype", None), "enum_dict", None)
    if enum:
        nomi, valori = list(enum.keys()), list(enum.values())
    else:
        try:
            valori = np.atleast_1d(var.getncattr("flag_values")).tolist()
            nomi = str(var.getncattr("flag_meanings")).split()
        except (AttributeError, KeyError):
            return None, None
    ghiaccio = [v for v, n in zip(valori, nomi) if "ice" in n.lower()]
    # Nube: acqua, ghiaccio, due strati. Non elaborato (sereno), polvere e
    # cenere no. Nei due strati la cima e' quasi sempre ghiaccio.
    nuvola = [v for v, n in zip(valori, nomi)
              if any(s in n.lower() for s in ("water", "ice", "liquid"))
              and not any(s in n.lower() for s in ("dust", "ash", "not processed", "clear"))]
    return ghiaccio, nuvola


def elabora(percorso: str, sonda: bool = False) -> bytes:
    import netCDF4

    ds = netCDF4.Dataset(percorso)
    ds.set_auto_maskandscale(True)
    if sonda:
        descrivi(ds)
        dt = getattr(ds.variables["retrieved_cloud_phase"], "datatype", None)
        log("fase: " + str(getattr(dt, "enum_dict", dt)))
    x = np.asarray(ds.variables["x"][:], dtype=np.float64)
    y = np.asarray(ds.variables["y"][:], dtype=np.float64)
    righe = ds.variables["y"].dimensions[0]
    colonne = ds.variables["x"].dimensions[0]
    a, h, rf, lon0 = proiezione(ds)
    avanti, indietro = trasformatori(a, h, rf, lon0)
    r0, r1, c0, c1 = ritaglio(x, y, h, avanti)
    log("ritaglio righe %d-%d colonne %d-%d" % (r0, r1, c0, c1))

    XX, YY = np.meshgrid(-x[c0:c1] * h, y[r0:r1] * h)
    lon, lat = indietro.transform(XX, YY)
    lon, lat = np.asarray(lon), np.asarray(lat)

    v = ds.variables
    cot = lettura(v["retrieved_cloud_optical_thickness"], r0, r1, c0, c1, righe, colonne)
    err = lettura(v["retrieval_error_cloud_optical_thickness"], r0, r1, c0, c1, righe, colonne) \
        if "retrieval_error_cloud_optical_thickness" in v else np.zeros_like(cot)
    ctp = lettura(v["retrieved_cloud_top_pressure"], r0, r1, c0, c1, righe, colonne)
    cth = lettura(v["retrieved_cloud_top_height"], r0, r1, c0, c1, righe, colonne) \
        if "retrieved_cloud_top_height" in v else None
    reff = lettura(v["retrieved_cloud_particle_effective_radius"], r0, r1, c0, c1, righe, colonne)
    fase = lettura(v["retrieved_cloud_phase"], r0, r1, c0, c1, righe, colonne)
    ghiaccio_v, nuvola_v = fase_ghiaccio(v["retrieved_cloud_phase"])
    unita_reff = str(getattr(v["retrieved_cloud_particle_effective_radius"], "units", ""))
    unita_ctp = str(getattr(v["retrieved_cloud_top_pressure"], "units", ""))
    unita_cth = str(getattr(v["retrieved_cloud_top_height"], "units", "")) if cth is not None else ""
    ds.close()

    cot1, cot2 = cot[0], cot[1] if cot.shape[0] > 1 else np.full_like(cot[0], np.nan)
    # Lo spessore ottico conta solo dove e' misurato: errore entro un fattore
    # 2 (0,3 in log10). Di notte, con il solo infrarosso, una nube spessa e'
    # opaca e il suo tau non si recupera: copertura e quote restano.
    err1 = err[0]
    err2 = err[1] if err.shape[0] > 1 else np.full_like(err1, np.nan)
    ctp1, ctp2 = ctp[0], ctp[1] if ctp.shape[0] > 1 else np.full_like(ctp[0], np.nan)
    reff = reff.reshape(reff.shape[-2:]) if reff.ndim > 2 else reff
    fase = fase.reshape(fase.shape[-2:]) if fase.ndim > 2 else fase
    # unita': pressione in hPa, raggio in um, quota in km
    if unita_ctp.lower() in ("pa", "pascal") or np.nanmedian(ctp1) > 2000:
        ctp1, ctp2 = ctp1 / 100.0, ctp2 / 100.0
    if unita_reff.lower() in ("m", "meter", "metre", "meters") or np.nanmedian(reff) < 1e-3:
        reff = reff * 1e6
    zt1 = quota_da_pressione(ctp1)
    if cth is not None:
        cth = cth.reshape(cth.shape[-2:]) if cth.ndim > 2 else cth
        if unita_cth.lower() in ("m", "meter", "metre", "meters") or np.nanmedian(cth) > 100:
            cth = cth / 1000.0
        zt1 = np.where(np.isfinite(cth), cth, zt1)
    zt2 = quota_da_pressione(ctp2)

    iy = np.rint((lat - SUD) / PASSO)
    ix = np.rint((lon - OVEST) / PASSO)
    dentro = np.isfinite(lat) & np.isfinite(lon) & (iy >= 0) & (iy < NY) & (ix >= 0) & (ix < NX)
    cella = np.where(dentro, iy * NX + ix, 0).astype(np.int64)
    visto = dentro & (np.isfinite(fase) | np.isfinite(cot1))
    nuvola = visto & np.isfinite(cot1)
    if nuvola_v:
        nuvola &= np.isin(fase, nuvola_v) | ~np.isfinite(fase)
    # Il secondo strato solo sotto il primo (qualche recupero lo mette oltre
    # i 16 km: non e' fisico).
    due = nuvola & np.isfinite(cot2) & np.isfinite(ctp2) & (zt2 < zt1 - 1.0)
    ghiaccio = nuvola & np.isin(fase, ghiaccio_v or [])

    n = NY * NX
    conta = lambda m, w=None: np.bincount(cella[m], weights=None if w is None else w[m], minlength=n)
    n_visti, n_nubi, n_due = conta(visto), conta(nuvola), conta(due)
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(n_visti > 0, n_nubi / np.maximum(n_visti, 1), np.nan)
        buono1 = nuvola & (np.nan_to_num(err1, nan=9.0) <= 0.3)
        buono2 = due & (np.nan_to_num(err2, nan=9.0) <= 0.3)
        tau1 = conta(buono1, np.power(10.0, cot1)) / conta(buono1)
        tau2 = conta(buono2, np.power(10.0, cot2)) / conta(buono2)
        ml = np.where(n_nubi > 0, n_due / np.maximum(n_nubi, 1), np.nan)
        okz = nuvola & np.isfinite(zt1)
        z1 = conta(okz, zt1) / conta(okz)
        z2 = conta(due, zt2) / n_due
        okr = nuvola & np.isfinite(reff)
        re = conta(okr, reff) / conta(okr)
        ice = np.where(n_nubi > 0, conta(ghiaccio) / np.maximum(n_nubi, 1), np.nan)
        valori = {"frac": frac, "cot1": np.log10(tau1), "cot2": np.log10(tau2), "ml": ml,
                  "zt1": z1, "zt2": z2, "reff": re, "ice": ice}

    if sonda:
        log("pixel nel dominio: %d, visti %d, nuvolosi %d, due strati %d, ghiaccio %d, tau misurato %d" % (
            dentro.sum(), visto.sum(), nuvola.sum(), due.sum(), ghiaccio.sum(), buono1.sum()))
        log("fase ghiaccio %s, nuvola %s; unita' reff '%s' ctp '%s' cth '%s'" % (
            ghiaccio_v, nuvola_v, unita_reff, unita_ctp, unita_cth))
        for k, val in valori.items():
            f = val[np.isfinite(val)]
            if f.size:
                log("  %-5s celle %6d  p5 %.3g  mediana %.3g  p95 %.3g" % (
                    k, f.size, *np.percentile(f, [5, 50, 95])))
        # La copertura in caratteri (nord in alto): la si confronta a occhio
        # con l'immagine satellitare dello stesso istante per la geometria.
        f = np.nan_to_num(frac.reshape(NY, NX), nan=-1)
        for riga in range(NY - 1, -1, -6):
            log("  |" + "".join(" " if v < 0 else " .:-=+*#%@"[min(9, int(v * 9.99))]
                                for v in f[riga, ::4]) + "|")
        # un controllo geografico: la colonna sopra Milano
        k = int(round((45.46 - SUD) / PASSO)) * NX + int(round((9.19 - OVEST) / PASSO))
        log("Milano: " + ", ".join("%s=%.3g" % (c, valori[c].ravel()[k]) for c in valori))
    return piastrella(valori)


def piastrella(valori: dict) -> bytes:
    head = MAGIC + struct.pack("<BBHHH", 1, len(CAMPI), NX, NY, 1)
    head += struct.pack("<ffffff", SUD, NORD, OVEST, EST, 0.0, 1.0)
    body = b""
    for nome, (scala, offset) in CAMPI.items():
        val = np.asarray(valori[nome], dtype=np.float64).reshape(NY, NX)
        codici = np.where(np.isfinite(val), np.clip(np.rint((val - offset) / scala), 0, 254), 255)
        head += nome.encode("ascii").ljust(8, b"\0") + struct.pack("<Bff", 0, scala, offset)
        body += codici.astype(np.uint8).tobytes()
    return gzip.compress(head + body, compresslevel=9, mtime=0)


# --- indice e finestra temporale -------------------------------------------

def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def nome_file(t: datetime) -> str:
    return t.strftime("%Y%m%dT%H%MZ") + ".oca.gz"


def indice_esistente(url: str | None, session) -> list[dict]:
    if not url:
        return []
    try:
        r = session.get(url, params={"t": int(time.time())}, timeout=30)
        if r.ok:
            return r.json().get("frames", [])
    except Exception as errore:  # noqa: BLE001 -- l'indice vecchio e' facoltativo
        log("indice precedente non letto: %s" % type(errore).__name__)
    return []


def main(argv=None) -> int:
    import requests

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="data_weather/cloud_oca")
    ap.add_argument("--hours", type=float, default=3.0)
    ap.add_argument("--max-new", type=int, default=6)
    ap.add_argument("--index-url", default=None, help="index.json gia' pubblicato")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args(argv)

    session = requests.Session()
    adesso = datetime.now(timezone.utc)
    prodotti = cerca(session, adesso - timedelta(hours=args.hours), adesso)
    log("prodotti OCA nelle ultime %.1f ore: %d" % (args.hours, len(prodotti)))
    if not prodotti:
        return 0
    tok = token(session)

    if args.probe:
        with tempfile.TemporaryDirectory() as tmp:
            elabora(scarica(session, tok, prodotti[-1], tmp), sonda=True)
        return 0

    limite = adesso - timedelta(hours=args.hours)
    vecchi = [f for f in indice_esistente(args.index_url, session)
              if datetime.strptime(f["valid"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) >= limite]
    gia = {f["valid"] for f in vecchi}
    nuovi = [p for p in prodotti if iso(p["inizio"]) not in gia]
    # prima i piu' recenti: sono quelli che si guardano
    nuovi = sorted(nuovi, key=lambda p: p["inizio"], reverse=True)[:args.max_new]
    os.makedirs(args.out, exist_ok=True)
    frames = list(vecchi)
    for p in nuovi:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dati = elabora(scarica(session, tok, p, tmp))
        except Exception as errore:  # noqa: BLE001 -- un prodotto rotto non ferma gli altri
            log("prodotto %s saltato: %s" % (iso(p["inizio"]), errore))
            continue
        nome = nome_file(p["inizio"])
        with open(os.path.join(args.out, nome), "wb") as f:
            f.write(dati)
        frames.append({"valid": iso(p["inizio"]), "file": nome})
        log("  %s -> %s (%d KB)" % (iso(p["inizio"]), nome, len(dati) // 1024))
    frames.sort(key=lambda f: f["valid"])
    indice = {"method": METHOD, "updated": iso(adesso), "frames": frames,
              "grid": {"south": SUD, "north": NORD, "west": OVEST, "east": EST, "nx": NX, "ny": NY}}
    with open(os.path.join(args.out, "index.json"), "w") as f:
        json.dump(indice, f, separators=(",", ":"))
    log("indice: %d istanti (%d nuovi)" % (len(frames), len(frames) - len(vecchi)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
