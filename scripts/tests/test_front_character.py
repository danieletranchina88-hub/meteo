"""Regression tests for front_character: thermal-wind gate and ana/kata.

Until v21 this module had no test, and two sign errors went to production:

* the expected thermal-wind direction was -k x grad T, so a front in perfect
  thermal-wind balance scored -1 and was dropped as ``fail:thermal-wind``.
  On the operational run of 2026-10-17 00Z that gate removed every engine
  and fallback candidate in all 73 hours;
* the engine handed the *ascent* field (-omega) to a function that reads
  omega with its physical sign, so the omega vote of the ana/kata diagnosis
  came out swapped.

Every expectation below is set by the physics in closed form, not by the
current output of the code.
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import front_character as fch
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


LON = np.linspace(5.0, 15.0, 81)
LAT = np.linspace(38.0, 48.0, 81)
LONG, LATG = np.meshgrid(LON, LAT)
METRICS = fl.grid_metrics(LON, LAT)
ZERO = np.zeros_like(LONG)


def zonal_line(latitude=43.0, count=12):
    return np.column_stack((np.linspace(7.0, 13.0, count), np.full(count, latitude)))


# --------------------------------------------------------------------------
print("1) Vento termico: k x grad T, aria calda a destra del taglio")
# --------------------------------------------------------------------------
# Warm air to the south: grad T points south and the warm normal is (0, -1).
# Thermal wind then blows from the west (cold air on its left), so a westerly
# shear between 850 and 700 hPa is the balanced case.
line = zonal_line()
warm_south = np.tile([0.0, -1.0], (len(line), 1))
balanced = fch.thermal_wind_alignment(
    line, warm_south, ZERO, ZERO, np.full_like(LONG, 8.0), ZERO,
    LON, LAT, METRICS,
)
report(abs(balanced - 1.0) < 1.0e-9,
       "un fronte in equilibrio di vento termico non ha allineamento +1",
       "aria calda a sud, taglio da ovest: %.2f" % balanced)

reversed_shear = fch.thermal_wind_alignment(
    line, warm_south, ZERO, ZERO, np.full_like(LONG, -8.0), ZERO,
    LON, LAT, METRICS,
)
report(abs(reversed_shear + 1.0) < 1.0e-9,
       "un taglio opposto al vento termico non vale -1",
       "taglio da est: %.2f" % reversed_shear)

# An arbitrary orientation: warm air toward the south-east.
angle = math.radians(-35.0)
normal = np.array([math.cos(angle), math.sin(angle)])
expected = np.array([-normal[1], normal[0]])          # k x n
oblique = fch.thermal_wind_alignment(
    line, np.tile(normal, (len(line), 1)), ZERO, ZERO,
    np.full_like(LONG, 10.0 * expected[0]), np.full_like(LONG, 10.0 * expected[1]),
    LON, LAT, METRICS,
)
report(abs(oblique - 1.0) < 1.0e-9,
       "l'allineamento dipende dall'orientazione del fronte",
       "fronte obliquo in equilibrio: %.2f" % oblique)

weak = fch.thermal_wind_alignment(
    line, warm_south, ZERO, ZERO, np.full_like(LONG, 1.0), ZERO,
    LON, LAT, METRICS,
)
report(not np.isfinite(weak),
       "un taglio sotto la soglia di significativita' vota comunque",
       "taglio 1 m/s: %s" % weak)

candidate = {"coordinates": line, "warmNormal": warm_south}
evidence = {"frontogenesis": np.full_like(LONG, 1.0), "metrics": METRICS}
fch.annotate_candidate(
    candidate, evidence, LON, LAT,
    u_lower=ZERO, v_lower=ZERO,
    u_upper=np.full_like(LONG, 8.0), v_upper=ZERO,
)
report(fch.passes_physical_gate(candidate),
       "il cancello fisico scarta un fronte frontogenetico e bilanciato",
       "physicalGate=%s" % candidate["physicalGate"])

# --------------------------------------------------------------------------
print("\n2) Omega con il suo segno fisico: negativo = ascesa")
# --------------------------------------------------------------------------
ascent_everywhere = np.full_like(LONG, -0.3)      # Pa/s, rising air
character = fch.frontal_character(
    line, warm_south, ZERO, ZERO, LON, LAT, METRICS, omega=ascent_everywhere,
)
report(character == "anafront",
       "ascesa sul lato caldo non letta come anafronte",
       "omega -0.3 Pa/s -> %s" % character)
character = fch.frontal_character(
    line, warm_south, ZERO, ZERO, LON, LAT, METRICS, omega=-ascent_everywhere,
)
report(character == "katafront",
       "subsidenza sul lato caldo non letta come katafronte",
       "omega +0.3 Pa/s -> %s" % character)

# The engine must export omega with the same physical sign, and keep the
# sign-flipped field under its own name.
theta = 286.0 + 3.0 * np.vectorize(math.erf)((LATG - 43.0) / 1.0)
fields = fe.frontal_evidence(
    theta, np.full_like(LONG, 5.0), ZERO, LON, LAT, metrics=METRICS,
    omega=ascent_everywhere,
)
interior = np.isfinite(fields["omega"])
report(np.allclose(fields["omega"][interior], -0.3)
       and np.allclose(fields["ascent"][interior], 0.3),
       "il motore esporta omega con il segno invertito",
       "omega %.2f, ascent %.2f" % (
           float(np.nanmedian(fields["omega"])),
           float(np.nanmedian(fields["ascent"]))))

# --------------------------------------------------------------------------
print("\n3) Bordo caldo: una sola costante, una sola volta")
# --------------------------------------------------------------------------
width = fe.reference_front_scales(fe.SYNOPTIC_SIGMA_KM)["widthKm"]
gradient_left = math.exp(-0.5 * fch.WARM_EDGE_FRACTION ** 2)
report(0.0 < fch.WARM_EDGE_FRACTION < 0.5 and gradient_left > 0.9,
       "il bordo caldo esce dalla zona frontale",
       "offset %.1f km = %.2f w', gradiente residuo %.0f%%"
       % (fch.WARM_EDGE_FRACTION * width, fch.WARM_EDGE_FRACTION,
          100.0 * gradient_left))

print("\nESITO:", "SUPERATO" if ok else "DA RIVEDERE")
raise SystemExit(0 if ok else 1)
