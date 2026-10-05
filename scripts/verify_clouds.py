"""Nubi 3D: la verifica con le misure indipendenti.

Quanto sono giuste le nubi del sito? Due confronti con misure vere, sugli
stessi dati che il browser usa (gh-pages):

A. BASI: i ceilometri degli aeroporti (METAR, solo casi a uno strato
   coprente BKN/OVC) contro
   - la base del modello ICON-EU (il fondo dello strato del volume sotto la
     cima osservata), e
   - la base dello spessore adiabatico (cima OCA meno H da tau e r_e), per le
     colonne d'acqua a uno strato, come nel browser.
B. STRATI: i radiosondaggi italiani (Univ. del Wyoming, alta risoluzione):
   strati nuvolosi dall'umidita' (UR >= 95% rispetto all'acqua sopra 0 C, al
   ghiaccio sotto) contro la copertura del volume ICON-EU (>= 50%) nella
   colonna della stazione, livello per livello (0-12 km, passo 250 m).

    python scripts/verify_clouds.py --data <cartella con data_weather> [--out report.json]
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from meteo_analysis.clouds.icon_eu import volume_from_bytes  # noqa: E402

SONDE_ITALIANE = {16045: "Udine", 16064: "Cameri", 16113: "Cuneo", 16144: "S. Pietro Capofiume",
                  16245: "Pratica di Mare", 16332: "Brindisi", 16429: "Trapani", 16546: "Cagliari"}
WYOMING = "https://weather.uwyo.edu/wsgi/sounding?datetime={}&id={}&type=TEXT:CSV"


def leggi(percorso):
    with open(percorso, "rb") as f:
        return volume_from_bytes(f.read())


def quando(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def indice_cella(v, lat, lon):
    nz, ny, nx = next(iter(v["fields"].values())).shape
    iy = round((lat - v["south"]) / ((v["north"] - v["south"]) / (ny - 1)))
    ix = round((lon - v["west"]) / ((v["east"] - v["west"]) / (nx - 1)))
    return (iy, ix) if 0 <= iy < ny and 0 <= ix < nx else None


# --- la fisica, identica al browser (index.html) ---------------------------
def condensazione_adiabatica(tK, pPa):
    Lv, cp, Rd, Rv, g = 2.501e6, 1005.0, 287.05, 461.5, 9.81
    es = 611.2 * math.exp(17.67 * (tK - 273.15) / (tK - 29.65))
    rs = 0.622 * es / max(pPa - es, 1.0)
    gm = g * (1 + Lv * rs / (Rd * tK)) / (cp + Lv * Lv * rs / (Rv * tK * tK))
    return max(0.0, (cp / Lv) * (g / cp - gm) * pPa / (Rd * tK) * 1000.0)


def spessore_adiabatico_km(tau, re, tK, pPa, f_ad=0.8):
    lwp = 5 / 9 * tau * re
    cw = condensazione_adiabatica(tK, pPa)
    return math.sqrt(2 * lwp / (f_ad * cw)) / 1000.0 if lwp > 0 and cw > 1e-5 else float("nan")


def base_modello(vol, iy, ix, cima_km):
    """Il fondo dello strato del volume sotto la cima (come spessoreDalModello)."""
    clc = vol["fields"]["clc"][:, iy, ix]
    z0, dz = vol["z0"], vol["dz"]
    alto = min(len(clc) - 1, int((cima_km + 0.5) / dz))
    primo = -1
    for z in range(alto, -1, -1):
        if cima_km - (z0 + z * dz) > 1.5:
            break
        if clc[z] >= 25:
            primo = z
            break
    if primo < 0:
        return float("nan")
    fondo, buchi = primo, 0
    for z in range(primo - 1, -1, -1):
        if clc[z] >= 20:
            fondo, buchi = z, 0
        else:
            buchi += 1
            if buchi > 2:
                break
    return max(0.0, z0 + fondo * dz - 0.5 * dz)


def statistiche(errori):
    e = np.asarray([x for x in errori if np.isfinite(x)])
    if not e.size:
        return {"n": 0}
    return {"n": int(e.size), "bias_m": round(float(e.mean()) * 1000), "mae_m": round(float(np.abs(e).mean()) * 1000),
            "rmse_m": round(float(np.sqrt((e ** 2).mean())) * 1000)}


# --- A. basi: METAR contro modello e adiabatico ----------------------------
def verifica_basi(cartella):
    oca_dir = os.path.join(cartella, "data_weather", "cloud_oca")
    vol_dir = os.path.join(cartella, "data_weather", "cloud_eu_vol")
    metar = json.load(open(os.path.join(oca_dir, "metar.json")))
    frames = json.load(open(os.path.join(oca_dir, "index.json")))["frames"]
    ore_vol = {quando(h["valid"]): h["file"] for h in json.load(open(os.path.join(vol_dir, "index.json")))["hours"]}
    stazioni = metar["stazioni"]
    err_mod, err_ad, casi = [], [], []
    for fr in frames:
        t = quando(fr["valid"])
        ora = min(ore_vol, key=lambda h: abs(h - t))
        if abs(ora - t) > timedelta(minutes=40):
            continue
        oca, vol = leggi(os.path.join(oca_dir, fr["file"])), leggi(os.path.join(vol_dir, ore_vol[ora]))
        minuti = t.timestamp() / 60
        for o in metar["oss"]:
            if abs(o[1] - minuti) > 10:
                continue
            strati = o[6] or []
            if len(strati) != 1 or strati[0][0] < 3 or strati[0][2]:
                continue                       # un solo strato coprente, niente CB/TCU
            icao, lat, lon, quota = stazioni[o[0]]
            misurata = quota / 1000 + strati[0][1] * 0.0003048
            c = indice_cella(oca, lat, lon)
            if not c:
                continue
            f = {k: float(v[0, c[0], c[1]]) for k, v in oca["fields"].items()}
            zt = f["zt1"]
            if not (zt > misurata + 0.05):
                continue                       # la cima vista deve stare sopra la base misurata
            cv = indice_cella(vol, lat, lon)
            bm = base_modello(vol, cv[0], cv[1], zt) if cv else float("nan")
            ba = float("nan")
            tau, re = 10 ** f["cot1"] if np.isfinite(f["cot1"]) else float("nan"), f["reff"]
            if (0.5 < tau < 150 and 3 <= re <= 30 and f["ice"] < 0.3 and not (f["ml"] > 0.3)
                    and f["frac"] > 0.3 and zt > 0.2):
                zmid = max(0.1, zt - 0.3)
                tK = 288.15 - 6.5 * zmid
                if cv is not None:
                    tt = vol["fields"]["t"][:, cv[0], cv[1]]
                    iz = int(round((zt - vol["z0"]) / vol["dz"]))
                    if 0 <= iz < len(tt) and np.isfinite(tt[iz]):
                        tK = tt[iz] + 273.15 + 2
                if tK >= 248:
                    pPa = 101325 * (1 - zmid / 44.33) ** 5.255
                    H = min(3.0, max(0.08, spessore_adiabatico_km(tau, re, tK, pPa)))
                    ba = max(0.0, zt - H)
            if np.isfinite(bm):
                err_mod.append(bm - misurata)
            if np.isfinite(ba):
                err_ad.append(ba - misurata)
            casi.append([icao, fr["valid"], round(misurata, 2), round(zt, 2),
                         None if not np.isfinite(bm) else round(bm, 2), None if not np.isfinite(ba) else round(ba, 2)])
    # LASCIA-FUORI-UNO per le basi METAR del browser (campiMetar/basiDaiMetar):
    # la base di ogni aeroporto stimata dalle SOLE altre stazioni (gaussiana
    # del valore 15 km, fiducia 35 km, peso 0,9 W/(W+0,35)) applicata alla
    # base del modello, contro la misura vera.
    err_lfo, err_lfo_mod = [], []
    for c_ in casi:
        if c_[4] is None:
            continue
        t_ = quando(c_[1]).timestamp() / 60
        st_ = next(s for s in stazioni if s[0] == c_[0])
        sv = sw = W = 0.0
        for o in metar["oss"]:
            if abs(o[1] - t_) > 60:
                continue
            s2 = stazioni[o[0]]
            if s2[0] == c_[0]:
                continue
            tetti = [s3 for s3 in (o[6] or []) if s3[0] >= 3]
            if o[4] is not None:
                tetto = s2[3] / 1000 + o[4] * 0.0003048
            elif tetti:
                tetto = s2[3] / 1000 + min(s3[1] for s3 in tetti) * 0.0003048
            else:
                continue
            dy = (s2[1] - st_[1]) * 111.2
            dx = (s2[2] - st_[2]) * 111.2 * math.cos(math.radians(st_[1]))
            d2 = dx * dx + dy * dy
            if d2 > 105 ** 2:
                continue
            w = math.exp(-d2 / (2 * 35 ** 2))
            wv = math.exp(-d2 / (2 * 15 ** 2)) + 1e-3 * w
            sv += wv * tetto; sw += wv; W += w
        if W < 0.02 or sw <= 0:
            continue
        stima = sv / sw
        if not (stima < c_[3] - 0.05 and stima > c_[3] - 3.5):
            continue
        peso = 0.9 * W / (W + 0.35)
        corretta = c_[4] + (stima - c_[4]) * peso
        err_lfo.append(corretta - c_[2]); err_lfo_mod.append(c_[4] - c_[2])
    lascia_fuori = {"modello": statistiche(err_lfo_mod), "modello_piu_metar_vicini": statistiche(err_lfo)}
    # Confronto alla pari: solo i casi in cui ci sono entrambe le stime.
    pari = [(c[4] - c[2], c[5] - c[2]) for c in casi if c[4] is not None and c[5] is not None]
    return {"modello": statistiche(err_mod), "adiabatico": statistiche(err_ad), "lascia_fuori_uno": lascia_fuori,
            "stessi_casi": {"modello": statistiche([p[0] for p in pari]),
                            "adiabatico": statistiche([p[1] for p in pari])},
            "casi": casi[:200]}


# --- B. strati: radiosondaggi contro il volume -------------------------------
def sondaggio(sessione, istante, wmo):
    url = WYOMING.format(istante.strftime("%Y-%m-%d%%20%H:%M:%S"), wmo)
    r = sessione.get(url, timeout=60)
    if not r.ok or not r.text.startswith("time"):
        return None
    righe = [l.split(",") for l in r.text.strip().splitlines()[1:]]
    z, ur, urg, tc = [], [], [], []
    for p in righe:
        try:
            z.append(float(p[4]) / 1000), tc.append(float(p[5])), ur.append(float(p[8])), urg.append(float(p[9]))
        except (ValueError, IndexError):
            continue
    return np.array(z), np.array(tc), np.array(ur), np.array(urg)


def verifica_strati(cartella, sessione):
    vol_dir = os.path.join(cartella, "data_weather", "cloud_eu_vol")
    ore_vol = {quando(h["valid"]): h["file"] for h in json.load(open(os.path.join(vol_dir, "index.json")))["hours"]}
    livelli = np.arange(0.125, 12.0, 0.25)
    tp = fp = fn = tn = 0
    righe = []
    for ora in sorted(h for h in ore_vol if h.hour in (0, 12)):
        vol = None
        for wmo, nome in SONDE_ITALIANE.items():
            s = sondaggio(sessione, ora, wmo)
            if s is None or len(s[0]) < 20:
                continue
            vol = vol or leggi(os.path.join(vol_dir, ore_vol[ora]))
            z, tc, ur, urg = s
            # coordinate della stazione dal primo campo del CSV non servono:
            # le prendiamo dal sondaggio stesso (lat/lon della partenza)
            r = sessione.get(WYOMING.format(ora.strftime("%Y-%m-%d%%20%H:%M:%S"), wmo), timeout=60).text.splitlines()[1].split(",")
            lon, lat = float(r[1]), float(r[2])
            c = indice_cella(vol, lat, lon)
            if not c:
                continue
            umido = np.where(tc >= 0, ur, urg)
            nube_sonda = np.interp(livelli, z, (umido >= 95).astype(float), left=0, right=0) >= 0.5
            clc = vol["fields"]["clc"][:, c[0], c[1]]
            zv = vol["z0"] + np.arange(len(clc)) * vol["dz"]
            nube_mod = np.interp(livelli, zv, np.nan_to_num(clc) >= 50) >= 0.5
            sotto = livelli <= z.max()
            a, b = nube_sonda[sotto], nube_mod[sotto]
            tp += int((a & b).sum()); fp += int((~a & b).sum()); fn += int((a & ~b).sum()); tn += int((~a & ~b).sum())
            righe.append([nome, ora.strftime("%Y-%m-%dT%HZ"), int(a.sum()), int(b.sum()), int((a & b).sum())])
    pod = tp / (tp + fn) if tp + fn else None
    far = fp / (tp + fp) if tp + fp else None
    return {"livelli_nube_sonda_e_modello": tp, "solo_modello": fp, "solo_sonda": fn, "sereni_entrambi": tn,
            "POD": None if pod is None else round(pod, 2), "FAR": None if far is None else round(far, 2),
            "sondaggi": righe}


def main(argv=None) -> int:
    import requests

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    rapporto = {"creato": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        rapporto["basi"] = verifica_basi(args.data)
    except Exception as errore:  # noqa: BLE001
        rapporto["basi"] = {"errore": str(errore)}
    try:
        rapporto["strati"] = verifica_strati(args.data, requests.Session())
    except Exception as errore:  # noqa: BLE001
        rapporto["strati"] = {"errore": str(errore)}
    sintesi = {k: v for k, v in rapporto.items() if k != "casi"}
    print(json.dumps({"basi": {k: v for k, v in rapporto["basi"].items() if k != "casi"},
                      "strati": {k: v for k, v in rapporto["strati"].items() if k != "sondaggi"}}, indent=1))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(rapporto, f, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
