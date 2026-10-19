"""Regression: optional front inputs are validated by unit, and never dropped silently.

 1) omega at 700 hPa with a convective tail (p99.9 |omega| ~ 45 Pa/s, as in a
    2.2-km model on a stormy day) is LOADED.  The former p99.9 < 20 Pa/s test
    dropped it on run 2026-10-07 00Z without a word;
 2) omega in the wrong unit (hPa/s) is still rejected, and the reason reaches
    both the log and analysis_summary["inputRejections"].

Small GRIB2 files are written with eccodes, read back through cfgrib exactly
as in production.
"""

import io
import os
import sys
import tempfile
from contextlib import redirect_stdout

import eccodes
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import front_analysis_v12 as v12

NI, NJ = 41, 31
LON0, LAT0, STEP = 10.0, 40.0, 0.1
HOURS = (0, 1, 2)
PARAM = {"t": 130, "q": 133, "u": 131, "v": 132, "w": 135}


def write_grib(path, name, level, fields):
    sample = eccodes.codes_grib_new_from_samples("regular_ll_pl_grib2")
    with open(path, "wb") as output:
        for hour, values in zip(HOURS, fields):
            handle = eccodes.codes_clone(sample)
            for key, value in (
                ("Ni", NI), ("Nj", NJ),
                ("latitudeOfFirstGridPointInDegrees", LAT0 + STEP * (NJ - 1)),
                ("latitudeOfLastGridPointInDegrees", LAT0),
                ("longitudeOfFirstGridPointInDegrees", LON0),
                ("longitudeOfLastGridPointInDegrees", LON0 + STEP * (NI - 1)),
                ("iDirectionIncrementInDegrees", STEP),
                ("jDirectionIncrementInDegrees", STEP),
                ("dataDate", 20261007), ("dataTime", 0),
                ("paramId", PARAM[name]), ("level", level), ("step", hour),
            ):
                eccodes.codes_set(handle, key, value)
            eccodes.codes_set_values(handle, np.asarray(values, float).ravel())
            eccodes.codes_write(handle, output)
            eccodes.codes_release(handle)
    eccodes.codes_release(sample)


def build(directory, omega_scale):
    rng = np.random.default_rng(7)
    shape = (NJ, NI)
    paths = {}
    for name, base, spread in (
        ("t", 283.0, 3.0), ("q", 0.006, 0.002), ("u", 5.0, 4.0), ("v", 2.0, 4.0),
    ):
        paths[name] = os.path.join(directory, f"{name}850.grib")
        write_grib(paths[name], name, 850,
                   [base + spread * rng.standard_normal(shape) for _ in HOURS])
    omega = []
    for _ in HOURS:
        field = 0.25 * rng.standard_normal(shape)        # median |omega| ~0.17
        field.ravel()[:3] = (-60.0, -45.0, -40.0)        # convective updrafts
        omega.append(field * omega_scale)
    paths["w"] = os.path.join(directory, "omega700.grib")
    write_grib(paths["w"], "w", 700, omega)
    log = io.StringIO()
    with redirect_stdout(log):
        analyzer = v12.FrontalAnalysisV12(
            paths["t"], paths["q"], paths["u"], paths["v"], None,
            omega_700_path=paths["w"], downsample=1,
            bounds=(LON0, LON0 + STEP * (NI - 1), LAT0, LAT0 + STEP * (NJ - 1)),
        )
    return analyzer, log.getvalue()


ok = True
with tempfile.TemporaryDirectory() as directory:
    stormy, _ = build(directory, 1.0)
    print("1) omega con coda convettiva (fino a 60 Pa/s): caricato =",
          "omega700" in stormy.datasets,
          "| scarti:", getattr(stormy, "input_rejections", {}))
    if "omega700" not in stormy.datasets:
        print("  FAIL: omega reale scartato per i moti convettivi")
        ok = False
    stormy.close()

with tempfile.TemporaryDirectory() as directory:
    wrong, log = build(directory, 0.01)                  # hPa/s
    rejections = getattr(wrong, "input_rejections", {})
    print("2) omega in hPa/s: caricato =", "omega700" in wrong.datasets,
          "| motivo:", rejections.get("omega700"))
    if "omega700" in wrong.datasets:
        print("  FAIL: omega in unita' sbagliate accettato")
        ok = False
    if "omega700" not in rejections or "omega700 scartato" not in log:
        print("  FAIL: lo scarto non e' registrato nel log e nel riepilogo")
        ok = False
    wrong.close()

print("\nESITO:", "SUPERATO" if ok else "DA RIVEDERE", flush=True)
# os._exit skips interpreter teardown: on some hosts the eccodes/cfgrib
# finalisers abort there ("double free"), which would hide the verdict.
os._exit(0 if ok else 1)
