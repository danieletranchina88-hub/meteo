"""Climatologia della temperatura a 850 hPa da ERA5 1990-2019 (WeatherBench 2).

Si leggono i blocchi zarr del livello 850 hPa (indice 10), si ritaglia il
dominio e si compatta il ciclo annuale in armoniche: media + 4 armoniche per
ogni punto e per ciascuna delle 4 ore sinottiche (00, 06, 12, 18 UTC).
"""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, numcodecs, urllib.request

BASE = "https://storage.googleapis.com/weatherbench2/datasets/era5-hourly-climatology/1990-2019_6h_1440x721.zarr"
LAT_S, LAT_N, LON_W, LON_E = 30.0, 52.0, -2.0, 28.0
ARMONICHE = 4
blosc = numcodecs.Blosc()

def leggi(url):
    for tentativo in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except Exception as errore:
            if tentativo == 3: raise
            time.sleep(2 * (tentativo + 1))

def coord(nome, dtype):
    return np.frombuffer(blosc.decode(leggi(f"{BASE}/{nome}/0")), dtype=dtype)

lat = coord("latitude", "<f4"); lon = coord("longitude", "<f4"); livelli = coord("level", "<i8")
ore = coord("hour", "<i8"); giorni = coord("dayofyear", "<i8")
k850 = int(np.where(livelli == 850)[0][0])
print("livello", k850, "ore", ore, "giorni", giorni[0], giorni[-1], "lat", lat[0], lat[-1], "lon", lon[0], lon[-1])
# Longitudini 0..360: il dominio attraversa Greenwich, si gira la griglia.
lon_180 = np.where(lon > 180, lon - 360, lon)
j_lat = np.where((lat >= LAT_S) & (lat <= LAT_N))[0]
i_lon = np.where((lon_180 >= LON_W) & (lon_180 <= LON_E))[0]
i_lon = i_lon[np.argsort(lon_180[i_lon])]
lat_d = lat[j_lat]; lon_d = lon_180[i_lon]
campo = np.full((4, 366, len(j_lat), len(i_lon)), np.nan, dtype=np.float32)

def blocco(hd):
    h, d = hd
    grezzo = blosc.decode(leggi(f"{BASE}/temperature/{h}.{d}.{k850}.0.0"))
    a = np.frombuffer(grezzo, dtype="<f4").reshape(3, 3, 1, 721, 1440)
    return h, d, a[:, :, 0][:, :, j_lat][:, :, :, i_lon]

lavori = [(h, d) for h in range(2) for d in range(122)]
t0 = time.time(); fatti = 0
with ThreadPoolExecutor(8) as ex:
    for h, d, a in ex.map(blocco, lavori):
        for hh in range(3):
            for dd in range(3):
                H, D = 3 * h + hh, 3 * d + dd
                if H < 4 and D < 366: campo[H, D] = a[hh, dd]
        fatti += 1
        if fatti % 40 == 0: print(fatti, "/", len(lavori), round(time.time() - t0), "s", flush=True)
assert np.isfinite(campo).all(), "buchi nella climatologia"
# Armoniche del ciclo annuale (giorno 1..366, periodo 365,25).
t = (giorni.astype(float) - 1) / 365.25 * 2 * np.pi
base = [np.ones_like(t)]
for k in range(1, ARMONICHE + 1): base += [np.cos(k * t), np.sin(k * t)]
X = np.stack(base, axis=1)                                   # 366 x (2K+1)
Y = campo.transpose(1, 0, 2, 3).reshape(366, -1).astype(float)  # 366 x (4*ny*nx)
coeff, *_ = np.linalg.lstsq(X, Y, rcond=None)
ricostruita = (X @ coeff).reshape(366, 4, len(lat_d), len(lon_d)).transpose(1, 0, 2, 3)
scarto = ricostruita - campo
print("scarto armoniche: rms", float(np.sqrt(np.mean(scarto ** 2))), "max", float(np.abs(scarto).max()))
coeff = coeff.reshape(2 * ARMONICHE + 1, 4, len(lat_d), len(lon_d)).transpose(1, 0, 2, 3).astype(np.float32)
np.savez_compressed(sys.argv[1], coefficienti=coeff, latitudini=lat_d.astype(np.float32),
                    longitudini=lon_d.astype(np.float32), ore_utc=np.array([0, 6, 12, 18], dtype=np.int8),
                    armoniche=np.int8(ARMONICHE))
json.dump({"fonte": "ERA5 1990-2019, WeatherBench 2 era5-hourly-climatology 1440x721",
           "livello_hPa": 850, "rms_armoniche_K": float(np.sqrt(np.mean(scarto ** 2)))},
          open(sys.argv[1].replace(".npz", "_info.json"), "w"), indent=1)
print("fatto", round(time.time() - t0), "s")
