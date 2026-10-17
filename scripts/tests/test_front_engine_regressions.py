"""Regression tests for the v22 repairs of front_engine.

Each case is a defect found on the operational product, written so that it
fails on the v21 code and passes once repaired:

1. ``merge_fragments`` compared the forward tangent of the first fragment with
   the *backward* tangent of the second, so no genuine continuation could
   ever join: two collinear segments 12 km apart stayed two lines.  On the
   run of 2026-10-17 00Z the engine produced ~60 raw lines an hour and ~57 of
   them were dropped as too short.
2. Short bridges were held to 5 degrees, i.e. to a lateral offset far below
   the half-cell uncertainty of a sub-pixel ridge point.
3. A NaN gradient on a vertex produced a NaN normal that crashed the whole
   forecast hour downstream.
4. The fallback geometry -- a TFL contour already on the warm edge -- was
   moved a second time toward the warm air.
5. The cut of a polished line into pieces read the point evidence instead
   of the neighbourhood gate the ridge mask is built on.
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import front_engine as fe
import front_locator as fl

ok = True


def report(passed, message, detail=""):
    global ok
    if not passed:
        ok = False
        print("  FAIL: " + message + (("  " + detail) if detail else ""))
    elif detail:
        print("    " + detail)


def zonal(lon_start, lon_end, latitude=44.0, count=30):
    return np.column_stack((np.linspace(lon_start, lon_end, count),
                            np.full(count, latitude)))


# --------------------------------------------------------------------------
print("1) Ricucitura: i frammenti collineari diventano una linea")
# --------------------------------------------------------------------------
first = zonal(8.0, 10.0)
second = zonal(10.15, 12.0)
merged = fe.merge_fragments([first, second])
report(len(merged) == 1,
       "due segmenti collineari a 12 km restano separati",
       "linee dopo il merge: %d" % len(merged))
merged_reversed = fe.merge_fragments([first, second[::-1]])
report(len(merged_reversed) == 1,
       "la ricucitura dipende dal verso (casuale) del frammento",
       "secondo frammento invertito: %d linee" % len(merged_reversed))
if len(merged) == 1:
    report(abs(fe.line_length_km(merged[0])
               - fe.line_length_km(zonal(8.0, 12.0))) < 1.0,
           "la linea ricucita non copre i due frammenti",
           "lunghezza %.0f km" % fe.line_length_km(merged[0]))

elbow = np.column_stack((np.full(30, 10.1), np.linspace(44.05, 46.0, 30)))
report(len(fe.merge_fragments([first, elbow])) == 2,
       "un gomito a 90 gradi viene saldato")
beside = zonal(8.5, 9.5, latitude=44.3, count=15)
report(len(fe.merge_fragments([first, beside])) == 2,
       "un frammento affiancato (non oltre l'estremo) viene saldato")
report(len(fe.merge_fragments([first, second],
                              bridge_ok=lambda tail, head: False)) == 2,
       "il ponte senza evidenza viene attraversato lo stesso")

# --------------------------------------------------------------------------
print("\n2) Ponte corto: l'angolo si misura con l'incertezza del punto")
# --------------------------------------------------------------------------
# A 16 km gap with a 4 km lateral step: well inside one cell of a 4.4 km
# grid, but 14 degrees of bridge angle.
offset_deg = 4.0 / 111.195
stepped = zonal(10.2, 12.0, latitude=44.0 + offset_deg)
strict = fe.merge_fragments([first, stepped])
tolerant = fe.merge_fragments([first, stepped], position_jitter_km=math.hypot(3.2, 4.4))
report(len(strict) == 2 and len(tolerant) == 1,
       "la tolleranza sub-pixel non cambia l'esito di un ponte corto",
       "senza tolleranza %d linee, con una cella di tolleranza %d"
       % (len(strict), len(tolerant)))
far_step = zonal(10.2, 12.0, latitude=44.0 + 30.0 / 111.195)
report(len(fe.merge_fragments([first, far_step],
                              position_jitter_km=math.hypot(3.2, 4.4))) == 2,
       "un salto laterale di 30 km viene saldato come se fosse rumore")

# --------------------------------------------------------------------------
print("\n3) Normali sempre finite")
# --------------------------------------------------------------------------
east = np.array([1.0, np.nan, 0.0, np.nan, np.nan])
north = np.array([0.0, np.nan, 2.0, np.nan, np.nan])
vectors = fe._unit_vectors(east, north)
# Vertex 1 is equidistant from both donors and takes the earlier one; the
# trailing vertices take the last finite direction.
report(np.all(np.isfinite(vectors))
       and np.allclose(np.hypot(vectors[:, 0], vectors[:, 1]), 1.0)
       and np.allclose(vectors[1], [1.0, 0.0])
       and np.allclose(vectors[3:], [0.0, 1.0]),
       "una direzione mancante resta NaN o non viene presa dal vicino",
       "vettori %s" % np.round(vectors, 2).tolist())

# --------------------------------------------------------------------------
print("\n4) Il ripiego non viene spostato due volte verso il caldo")
# --------------------------------------------------------------------------
LON = np.arange(5.0, 17.001, 0.08)
LAT = np.arange(37.0, 47.001, 0.08)
LONG, LATG = np.meshgrid(LON, LAT)
METRICS = fl.grid_metrics(LON, LAT)
NORTH_KM = (LATG - 42.0) * fl.EARTH_KM_PER_DEG
erf = np.vectorize(math.erf)
theta_w = 286.0 - 3.5 * erf(NORTH_KM / (math.sqrt(2.0) * 80.0))   # warm south
u = 6.0 - 12.0 * erf(NORTH_KM / (math.sqrt(2.0) * 80.0)) * 0.5
v = -1.0e-5 * NORTH_KM * 1000.0                                    # confluence
candidates, fields = fe.detect_fronts(
    theta_w, u, v, LON, LAT, metrics=METRICS, return_fields=True,
)
supplied = zonal(9.0, 13.0, latitude=42.0, count=60)
moved = fe.score_lines([supplied], fields, min_length_km=150.0)
kept = fe.score_lines([supplied], fields, min_length_km=150.0, on_warm_edge=True)
report(bool(moved) and bool(kept),
       "il vaglio dell'evidenza scarta una linea sulla zona baroclina")
if moved and kept:
    shift_moved = (np.mean(moved[0]["coordinates"][:, 1]) - 42.0) * fl.EARTH_KM_PER_DEG
    shift_kept = (np.mean(kept[0]["coordinates"][:, 1]) - 42.0) * fl.EARTH_KM_PER_DEG
    report(abs(shift_kept) < 1.0 and shift_moved < -30.0
           and kept[0]["warmEdgeOffsetKm"] == 0.0,
           "una geometria gia' sul bordo caldo viene spostata di nuovo",
           "spostamento: motore %.0f km, ripiego %.0f km" % (shift_moved, shift_kept))

funnel = {}
fe.score_lines([zonal(9.0, 9.5, latitude=42.0, count=8)], fields,
               min_length_km=150.0, funnel=funnel)
report(funnel.get("fallbackDroppedTooShort", 0) == 1,
       "una linea scartata dal vaglio non lascia traccia nell'imbuto",
       "imbuto: %s" % funnel)

# --------------------------------------------------------------------------
print("\n5) Il taglio usa lo stesso cancello della maschera")
# --------------------------------------------------------------------------
evidence = fields["evidence"]
gate = fe.neighbourhood_gate(evidence)
point = np.nan_to_num(evidence["probability"], nan=0.0)
finite = np.isfinite(gate)
report(np.all(gate[finite] >= point[finite] - 1.0e-12),
       "il cancello di vicinato toglie evidenza invece di colmare i buchi")
report(fe.neighbourhood_gate(evidence) is gate,
       "il cancello viene ricalcolato a ogni uso nella stessa ora")
funnel = fields["funnel"]
report(funnel["candidatePieces"] >= funnel["droppedTooShort"],
       "l'imbuto conta piu' linee corte che pezzi",
       "pezzi %d, troppo corti %d" % (funnel["candidatePieces"],
                                     funnel["droppedTooShort"]))

print("\nESITO:", "SUPERATO" if ok else "DA RIVEDERE")
raise SystemExit(0 if ok else 1)
