"""Anomalia della temperatura a 850 hPa rispetto alla media 1990-2019.

La media viene da ERA5 (climatologia oraria di WeatherBench 2, 0,25 gradi,
00/06/12/18 UTC per ogni giorno dell'anno). Per tenerla nel repository il
ciclo annuale di ogni punto e di ogni ora e' compresso in media piu' quattro
armoniche: lo scarto rispetto ai valori ERA5 e' 0,14 K in media quadratica
e 0,48 K al massimo, trascurabile per un'anomalia sinottica. Il file si
rigenera con scripts/strumenti/build_t850_climatology.py.

L'anomalia e' T850 del modello meno la media dello stesso giorno dell'anno e
della stessa ora, interpolata in tempo (fra le quattro ore sinottiche) e in
spazio (bilineare). Nessuna correzione per la quota: dove la superficie a
850 hPa e' sotto terra (Alpi) anche il modello estrapola, e il campo va
letto con la stessa cautela del T850.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

FILE = Path(__file__).with_name("era5_t850_1990_2019.npz")
CELSIUS0 = 273.15


@lru_cache(maxsize=1)
def _dati(path: str = str(FILE)) -> dict:
    with np.load(path) as archivio:
        return {
            "coefficienti": archivio["coefficienti"].astype(float),  # ore x (2K+1) x lat x lon
            "latitudini": archivio["latitudini"].astype(float),
            "longitudini": archivio["longitudini"].astype(float),
            "ore": archivio["ore_utc"].astype(int),
            "armoniche": int(archivio["armoniche"]),
        }


def _base_armonica(istante: datetime, armoniche: int) -> np.ndarray:
    giorno = istante.timetuple().tm_yday - 1 + (istante.hour + istante.minute / 60.0) / 24.0
    angolo = giorno / 365.25 * 2.0 * np.pi
    base = [1.0]
    for k in range(1, armoniche + 1):
        base += [np.cos(k * angolo), np.sin(k * angolo)]
    return np.asarray(base)


def media_climatologica(istante: datetime) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Media 1990-2019 sulla griglia ERA5 del file (K), lat e lon crescenti."""
    if istante.tzinfo is None:
        istante = istante.replace(tzinfo=timezone.utc)
    istante = istante.astimezone(timezone.utc)
    d = _dati()
    base = _base_armonica(istante, d["armoniche"])
    per_ora = np.einsum("k,hkyx->hyx", base, d["coefficienti"])
    ora = istante.hour + istante.minute / 60.0
    passo = 24.0 / len(d["ore"])
    prima = int(ora // passo) % len(d["ore"])
    dopo = (prima + 1) % len(d["ore"])
    peso = (ora - prima * passo) / passo
    campo = (1.0 - peso) * per_ora[prima] + peso * per_ora[dopo]
    latitudini = d["latitudini"]
    if latitudini[0] > latitudini[-1]:
        latitudini = latitudini[::-1]
        campo = campo[::-1]
    return campo, latitudini, d["longitudini"]


def _bilineare(campo, lat_src, lon_src, lat_dst, lon_dst):
    fy = np.interp(lat_dst, lat_src, np.arange(len(lat_src)), left=np.nan, right=np.nan)
    fx = np.interp(lon_dst, lon_src, np.arange(len(lon_src)), left=np.nan, right=np.nan)
    Y, X = np.meshgrid(fy, fx, indexing="ij")
    fuori = ~np.isfinite(Y) | ~np.isfinite(X)
    Y = np.nan_to_num(Y); X = np.nan_to_num(X)
    y0 = np.clip(np.floor(Y).astype(int), 0, len(lat_src) - 2)
    x0 = np.clip(np.floor(X).astype(int), 0, len(lon_src) - 2)
    ty, tx = Y - y0, X - x0
    valori = ((campo[y0, x0] * (1 - tx) + campo[y0, x0 + 1] * tx) * (1 - ty)
              + (campo[y0 + 1, x0] * (1 - tx) + campo[y0 + 1, x0 + 1] * tx) * ty)
    valori[fuori] = np.nan
    return valori


def anomalia_su_griglia(temperatura_c: np.ndarray, latitudini: np.ndarray,
                        longitudini: np.ndarray, istante: datetime) -> np.ndarray:
    """T850 (gradi C, righe = latitudini) meno la media dello stesso giorno e ora."""
    campo, lat_src, lon_src = media_climatologica(istante)
    media = _bilineare(campo, lat_src, lon_src, np.asarray(latitudini, float), np.asarray(longitudini, float))
    return np.asarray(temperatura_c, dtype=float) + CELSIUS0 - media


def anomalia_per_payload(livello: dict, istante: datetime, decimali: int = 1) -> list | None:
    """Anomalia per il livello 850 pubblicato al browser (righe da nord a sud)."""
    valori = livello.get("t")
    if not valori:
        return None
    nx, ny = int(livello["nx"]), int(livello["ny"])
    latitudini = float(livello["la1"]) - np.arange(ny) * float(livello["dy"])
    longitudini = float(livello["lo1"]) + np.arange(nx) * float(livello["dx"])
    temperatura = np.array([np.nan if v is None else v for v in valori], dtype=float).reshape(ny, nx)
    anomalia = anomalia_su_griglia(temperatura, latitudini, longitudini, istante)
    piatta = np.round(anomalia, decimali).ravel()
    return [None if not np.isfinite(v) else float(v) for v in piatta]
