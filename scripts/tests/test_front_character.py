"""Synthetic verification of front_character.py (physical character gates).

 1) thermal wind: a textbook baroclinic zone (warm south, westerly shear)
    must ALIGN (cosine near +1) and the opposite shear must not.  The sign
    was once inverted and rejected every real front in the domain;
 2) frontal character: ascent on the warm side (omega < 0, Pa/s) votes for
    an anafront, descent for a katafront;
 3) zone_axis undoes the published warm-edge offset exactly;
 4) snap_to_zone_axis moves a line drawn 110 km into the warm air back onto
    the |grad theta_w| maximum, smoothly, and leaves NaN normals in place.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import front_character as fch
import front_locator as fl

LON = np.arange(3.0, 22.01, 0.1)
LAT = np.arange(34.0, 49.01, 0.1)
LONG, LATG = np.meshgrid(LON, LAT)
METRICS = fl.grid_metrics(LON, LAT)

line = np.column_stack((np.linspace(7.0, 18.0, 60), np.full(60, 42.0)))
warm_normal = np.tile([0.0, -1.0], (60, 1))   # warm air to the south

ok = True

# 1) thermal wind -----------------------------------------------------------
# Warm south, cold north: thermal wind is westerly, u grows with height.
u_low = np.full_like(LONG, 5.0)
v_low = np.zeros_like(LONG)
u_up = np.full_like(LONG, 15.0)
v_up = np.zeros_like(LONG)
right = fch.thermal_wind_alignment(
    line, warm_normal, u_low, v_low, u_up, v_up, LON, LAT, METRICS
)
wrong = fch.thermal_wind_alignment(
    line, warm_normal, u_low, v_low, u_low - 10.0, v_up, LON, LAT, METRICS
)
print("1) vento termico: corretto", round(right, 2), "opposto", round(wrong, 2))
if not right > 0.9:
    print("  FAIL: il taglio da manuale non e' allineato al vento termico")
    ok = False
if not wrong < -0.9:
    print("  FAIL: il taglio opposto non e' riconosciuto come tale")
    ok = False

# 2) ana / kata from omega --------------------------------------------------
ascent = np.full_like(LONG, -0.3)    # Pa/s, rising on the warm side
descent = np.full_like(LONG, 0.3)
ana = fch.frontal_character(
    line, warm_normal, None, None, LON, LAT, METRICS, omega=ascent
)
kata = fch.frontal_character(
    line, warm_normal, None, None, LON, LAT, METRICS, omega=descent
)
print("2) carattere: ascesa ->", ana, "| subsidenza ->", kata)
if ana != "anafront" or kata != "katafront":
    print("  FAIL: ascesa e subsidenza non danno ana/kata")
    ok = False
# The engine hands its evidence["omega"] to frontal_character: it must keep
# the model's sign, or every engine-scored line gets ana/kata swapped.
import front_engine as fe
theta_front = 290.0 + 4.0 * np.tanh(-(LATG - 42.0) / 0.35)
evidence = fe.frontal_evidence(
    theta_front, u_low, v_low, LON, LAT, metrics=METRICS, omega=ascent,
)
engine_character = fch.frontal_character(
    line, warm_normal, None, None, LON, LAT, METRICS, omega=evidence["omega"]
)
print("   motore: omega", round(float(np.nanmedian(evidence["omega"])), 2),
      "->", engine_character)
if engine_character != "anafront":
    print("  FAIL: il segno di omega nell'evidenza del motore e' invertito")
    ok = False

# 3) zone_axis --------------------------------------------------------------
published = fch.place_on_warm_edge(line, warm_normal, 34.0)
axis = fch.zone_axis({
    "coordinates": published, "warmNormal": warm_normal,
    "warmEdgeOffsetKm": 34.0,
})
error_km = float(np.max(np.abs(axis[:, 1] - line[:, 1]))) * 111.32
print("3) asse ricostruito: errore massimo", round(error_km, 3), "km")
if error_km > 0.01:
    print("  FAIL: zone_axis non annulla lo spostamento sul bordo caldo")
    ok = False

# 4) snap_to_zone_axis ------------------------------------------------------
theta = 290.0 + 4.0 * np.tanh(-(LATG - 42.0) / 0.35)   # zone axis at 42 N
theta_smooth = fl.smooth_km(theta, 45.0, METRICS)
gx, gy = fl.gradient(theta_smooth, METRICS)
gradient = np.hypot(gx, gy)


def sampler(field, points):
    return fl._sample(field, points, LON, LAT,
                      float(METRICS["dlon"]), float(METRICS["dlat"]))


drawn = fch.place_on_warm_edge(line, warm_normal, 110.0)
snapped, shift = fch.snap_to_zone_axis(drawn, warm_normal, gradient, sampler)
residual_km = float(np.median(np.abs(snapped[:, 1] - 42.0))) * 111.32
roughness_km = float(np.max(np.abs(np.diff(shift))))
print("4) aggancio: residuo", round(residual_km, 1), "km, salto massimo",
      round(roughness_km, 2), "km")
if residual_km > 6.0:
    print("  FAIL: la linea non torna sull'asse della zona")
    ok = False
if roughness_km > 3.0:
    print("  FAIL: lo spostamento non e' liscio lungo la linea")
    ok = False
broken = warm_normal.copy()
broken[10] = np.nan
kept, _ = fch.snap_to_zone_axis(drawn, broken, gradient, sampler)
if not np.all(np.isfinite(kept)):
    print("  FAIL: una normale NaN produce coordinate NaN")
    ok = False

print("\nESITO:", "SUPERATO" if ok else "DA RIVEDERE")
raise SystemExit(0 if ok else 1)
