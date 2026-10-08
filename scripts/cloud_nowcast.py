"""Nowcast di un'ora del moto delle nubi da due immagini satellitari.

Non è un modello. Due fotogrammi dell'infrarosso 10.5 µm di MTG-FCI, a
trenta minuti di distanza, danno il vento delle nubi con la stessa tecnica
dei vettori atmosferici operativi: correlazione normalizzata di finestre,
controllo del picco, poi avvezione semi-lagrangiana del fotogramma più
recente fino a +60 minuti.

La posizione prevista è dove la nube è andata, non dove il modello pensa
che sarà. Oltre i quaranta minuti l'errore cresce perché le nubi nascono e
muoiono: il prodotto lo dichiara, non lo nasconde.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image, ImageFilter
from scipy.ndimage import map_coordinates, median_filter

# Dominio ICON-2I, lo stesso della carta.
WEST, EAST = 3.0, 22.0
SOUTH, NORTH = 33.7, 48.9
# 100 km/h per 30 minuti sono 50 km. Sotto i 4 km/pixel bastano 16 pixel
# di ricerca; il tetto evita di inseguire un picco casuale.
MAX_SPEED_KMH = 140.0
MIN_CORRELATION = 0.45
LEAD_MINUTES = 60
STEP_MINUTES = 10


def brightness(image: Image.Image) -> np.ndarray:
    """Proxy di cima fredda: nell'infrarosso EUMETSAT la nube è chiara."""
    grey = np.asarray(image.convert("L"), dtype=np.float32)
    return grey


def _peak(corr: np.ndarray) -> tuple[float, float, int, int]:
    flat = corr.ravel()
    order = np.argpartition(flat, -2)[-2:]
    first, second = order[np.argmax(flat[order])], order[np.argmin(flat[order])]
    py, px = np.unravel_index(first, corr.shape)
    return float(flat[first]), float(flat[second]), int(px), int(py)


def cloud_motion(
    earlier: np.ndarray,
    later: np.ndarray,
    *,
    dt_minutes: float,
    km_per_pixel: float,
    window: int = 32,
    stride: int = 24,
) -> dict:
    """Vettori di moto nube, in pixel del fotogramma recente per ora.

    Correlazione di fase su finestre: è il calcolo dei vettori atmosferici
    da satellite, non un flusso ottico da video. Il picco dice di quanti
    pixel la nube si è spostata in ``dt_minutes``.
    """
    from numpy.fft import fft2, ifft2

    height, width = later.shape
    max_shift = max(4, int(round(MAX_SPEED_KMH * (dt_minutes / 60.0) / km_per_pixel)))
    vectors = []
    hann = np.hanning(window * 2).astype(np.float32)
    hann = hann[:, None] * hann[None, :]
    for y in range(window + max_shift, height - window - max_shift, stride):
        for x in range(window + max_shift, width - window - max_shift, stride):
            template = later[y - window:y + window, x - window:x + window]
            if float(template.std()) < 4.0:
                continue
            search = earlier[y - window:y + window, x - window:x + window]
            a = (template - template.mean()) * hann
            b = (search - search.mean()) * hann
            fa = fft2(a)
            fb = fft2(b)
            cross = fa * np.conj(fb)
            denom = np.maximum(np.abs(cross), 1.0e-6)
            corr = np.real(ifft2(cross / denom))
            score, second, px, py = _peak(corr)
            dx = px if px < window else px - window * 2
            dy = py if py < window else py - window * 2
            if abs(dx) > max_shift or abs(dy) > max_shift:
                continue
            if score < 0.08 or score < second * 1.15:
                continue
            per_hour = 60.0 / dt_minutes
            vectors.append({
                "x": x,
                "y": y,
                "uPxPerHour": dx * per_hour,
                "vPxPerHour": dy * per_hour,
                "correlation": round(score, 3),
            })
    return {
        "vectors": vectors,
        "maxShiftPx": max_shift,
        "kmPerPixel": km_per_pixel,
    }


def _dense_flow(shape: tuple[int, int], motion: dict) -> tuple[np.ndarray, np.ndarray]:
    height, width = shape
    u = np.zeros(shape, dtype=np.float32)
    v = np.zeros(shape, dtype=np.float32)
    weight = np.zeros(shape, dtype=np.float32)
    radius = 28
    yy, xx = np.mgrid[0:height, 0:width]
    for vector in motion["vectors"]:
        mask = (xx - vector["x"]) ** 2 + (yy - vector["y"]) ** 2 <= radius ** 2
        fade = np.exp(-((xx - vector["x"]) ** 2 + (yy - vector["y"]) ** 2) / (2 * 12 ** 2))
        fade = np.where(mask, fade, 0.0) * vector["correlation"]
        u += fade * vector["uPxPerHour"]
        v += fade * vector["vPxPerHour"]
        weight += fade
    valid = weight > 1.0e-3
    u = np.divide(u, weight, out=np.zeros_like(u), where=valid)
    v = np.divide(v, weight, out=np.zeros_like(v), where=valid)
    u = median_filter(u, size=9)
    v = median_filter(v, size=9)
    return u, v


def advect(field: np.ndarray, u_per_hour: np.ndarray, v_per_hour: np.ndarray, minutes: float) -> np.ndarray:
    """Avvezione semi-lagrangiana all'indietro: da dove arriva il pixel."""
    hours = minutes / 60.0
    height, width = field.shape
    yy, xx = np.mgrid[0:height, 0:width]
    source_x = xx - u_per_hour * hours
    source_y = yy - v_per_hour * hours
    advected = map_coordinates(
        field, [source_y, source_x], order=1, mode="nearest"
    ).astype(np.float32)
    return advected


def nowcast(earlier: np.ndarray, later: np.ndarray, *, dt_minutes: float, km_per_pixel: float) -> dict:
    motion = cloud_motion(
        earlier, later, dt_minutes=dt_minutes, km_per_pixel=km_per_pixel
    )
    u, v = _dense_flow(later.shape, motion)
    frames = {}
    for minute in range(0, LEAD_MINUTES + 1, STEP_MINUTES):
        frames[minute] = advect(later, u, v, minute) if minute else later.copy()
    speed = np.hypot(u, v) * km_per_pixel
    return {
        "motion": motion,
        "frames": frames,
        "medianSpeedKmh": float(np.median(speed)),
        "vectorCount": len(motion["vectors"]),
    }


def km_per_pixel(width: int) -> float:
    mean_lat = math.radians(0.5 * (SOUTH + NORTH))
    return (EAST - WEST) * 111.32 * math.cos(mean_lat) / width



def blend_motion(satellite_u, satellite_v, model_u, model_v, confidence):
    """Dove il satellite ha un picco chiaro comanda lui, altrove il vento del modello.

    ``confidence`` è 0..1, alta solo sui vettori accettati. Il modello riempie
    il cielo sereno e le finestre ambigue, che sono quelle che nell'avvezione
    pura producevano i riccioli.
    """
    weight = np.clip(np.asarray(confidence, dtype=np.float32), 0.0, 1.0)
    u = weight * satellite_u + (1.0 - weight) * model_u
    v = weight * satellite_v + (1.0 - weight) * model_v
    return u.astype(np.float32), v.astype(np.float32)


def blend_clouds(advected_satellite, model_cloud, minutes: float):
    """La nube osservata resta, la nube prevista dal modello entra col tempo.

    A +0 minuti il peso del modello è zero. A +60 è un terzo: abbastanza per
    far comparire uno sviluppo che il satellite non può inventare, non abbastanza
    per cancellare una nube che il modello non ha.
    """
    model_weight = 0.35 * min(max(minutes, 0.0) / 60.0, 1.0)
    observed = np.asarray(advected_satellite, dtype=np.float32)
    forecast = np.asarray(model_cloud, dtype=np.float32)
    if forecast.shape != observed.shape:
        raise ValueError("modello e satellite devono stare sulla stessa griglia")
    return (1.0 - model_weight) * observed + model_weight * forecast


def save_frame(field: np.ndarray, path: str) -> None:
    image = Image.fromarray(np.clip(field, 0, 255).astype(np.uint8), mode="L")
    image = image.filter(ImageFilter.SMOOTH)
    image.save(path)


if __name__ == "__main__":
    import sys
    earlier = brightness(Image.open(sys.argv[1]))
    later = brightness(Image.open(sys.argv[2]))
    dt = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
    result = nowcast(earlier, later, dt_minutes=dt, km_per_pixel=km_per_pixel(earlier.shape[1]))
    print(json.dumps({
        "vectorCount": result["vectorCount"],
        "medianSpeedKmh": round(result["medianSpeedKmh"], 1),
        "leadMinutes": LEAD_MINUTES,
    }))
