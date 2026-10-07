"""Physical character of a located front: warm edge, frontogenesis, ana/kata.

A published line is not the ridge of |grad theta_w|. An analyst draws the
warm boundary of the baroclinic zone. The line is a front only if Petterssen
frontogenesis is positive along it and the vertical wind shear agrees with
the thermal wind. Anafront and katafront are a shear diagnosis, not a style.
"""

from __future__ import annotations

import math

import numpy as np

import front_locator as fl

EARTH_KM_PER_DEG = 111.32
# Gaussian |grad| falls to about 70% of its peak at 0.35 widths. That is the
# warm boundary an analyst marks, short of the half-power point, which already
# sits in the warm air and would move the line off the zone.
WARM_EDGE_FRACTION = 0.35
MIN_FRONTOGENESIS_FRACTION = 0.40
MIN_THERMAL_WIND_ALIGNMENT = 0.20


def place_on_warm_edge(
    coordinates: np.ndarray,
    warm_normal: np.ndarray,
    offset_km: float,
) -> np.ndarray:
    """Move each vertex toward the warm air by ``offset_km``."""
    line = np.asarray(coordinates, dtype=float)
    normal = np.asarray(warm_normal, dtype=float)
    if offset_km <= 0.0 or len(line) < 2 or len(normal) != len(line):
        return line.copy()
    latitude = np.deg2rad(line[:, 1])
    lon_scale = EARTH_KM_PER_DEG * np.maximum(np.cos(latitude), 0.25)
    shifted = line.copy()
    shifted[:, 0] = line[:, 0] + normal[:, 0] * offset_km / lon_scale
    shifted[:, 1] = line[:, 1] + normal[:, 1] * offset_km / EARTH_KM_PER_DEG
    return shifted


def _sample(field, line, longitudes, latitudes, metrics):
    return fl._sample(
        field, line, longitudes, latitudes,
        float(metrics["dlon"]), float(metrics["dlat"]),
    )


def frontogenesis_fraction(frontogenesis, line, longitudes, latitudes, metrics) -> float:
    """Share of the line where Petterssen frontogenesis is positive."""
    values = _sample(frontogenesis, line, longitudes, latitudes, metrics)
    finite = values[np.isfinite(values)]
    if len(finite) < 3:
        return float("nan")
    return float(np.mean(finite > 0.0))


def thermal_wind_alignment(
    line: np.ndarray,
    warm_normal: np.ndarray,
    u_lower, v_lower, u_upper, v_upper,
    longitudes, latitudes, metrics,
) -> float:
    """Agreement between observed shear and the thermal-wind direction.

    Thermal wind puts the shear (upper minus lower) parallel to k x grad T,
    so in the northern hemisphere it points with the warm air to the right.
    The score is the median cosine of that angle, in [-1, 1].
    """
    if u_lower is None or u_upper is None:
        return float("nan")
    normal = np.asarray(warm_normal, dtype=float)
    # k x warm-normal points along the front with warm air to the right.
    expected_east = normal[:, 1]
    expected_north = -normal[:, 0]
    lower_u = _sample(u_lower, line, longitudes, latitudes, metrics)
    lower_v = _sample(v_lower, line, longitudes, latitudes, metrics)
    upper_u = _sample(u_upper, line, longitudes, latitudes, metrics)
    upper_v = _sample(v_upper, line, longitudes, latitudes, metrics)
    shear_east = upper_u - lower_u
    shear_north = upper_v - lower_v
    shear = np.hypot(shear_east, shear_north)
    cosine = (shear_east * expected_east + shear_north * expected_north) / np.maximum(shear, 1.0e-6)
    finite = cosine[np.isfinite(cosine) & (shear >= 2.0)]
    if len(finite) < 3:
        return float("nan")
    return float(np.median(finite))


def frontal_character(
    line: np.ndarray,
    warm_normal: np.ndarray,
    u_wind, v_wind,
    longitudes, latitudes, metrics,
    *,
    u_upper=None, v_upper=None,
    omega=None,
) -> str:
    """Anafront, katafront, or undetermined.

    Anafront: the front-normal wind weakens with height and the warm side
    ascends (rearward sloping ascent). Katafront: the normal wind strengthens
    with height, or the warm side descends (forward sloping, split front).
    """
    normal = np.asarray(warm_normal, dtype=float)
    normal_wind = None
    if u_wind is not None and v_wind is not None:
        u = _sample(u_wind, line, longitudes, latitudes, metrics)
        v = _sample(v_wind, line, longitudes, latitudes, metrics)
        normal_wind = u * normal[:, 0] + v * normal[:, 1]
    shear = float("nan")
    if u_upper is not None and v_upper is not None and normal_wind is not None:
        upper_u = _sample(u_upper, line, longitudes, latitudes, metrics)
        upper_v = _sample(v_upper, line, longitudes, latitudes, metrics)
        upper_normal = upper_u * normal[:, 0] + upper_v * normal[:, 1]
        delta = upper_normal - normal_wind
        finite = delta[np.isfinite(delta)]
        if len(finite) >= 3:
            shear = float(np.median(finite))
    warm_ascent = float("nan")
    if omega is not None:
        offset = place_on_warm_edge(line, normal, 40.0)
        sampled = _sample(omega, offset, longitudes, latitudes, metrics)
        finite = sampled[np.isfinite(sampled)]
        if len(finite) >= 3:
            # Pa/s: negative is ascent.
            warm_ascent = float(-np.median(finite))
    ana_votes = 0
    kata_votes = 0
    if np.isfinite(shear):
        if shear <= -1.5:
            ana_votes += 1
        elif shear >= 1.5:
            kata_votes += 1
    if np.isfinite(warm_ascent):
        if warm_ascent > 0.02:
            ana_votes += 1
        elif warm_ascent < -0.02:
            kata_votes += 1
    if ana_votes > kata_votes and ana_votes > 0:
        return "anafront"
    if kata_votes > ana_votes and kata_votes > 0:
        return "katafront"
    return "undetermined"


def annotate_candidate(
    candidate: dict,
    evidence: dict,
    longitudes, latitudes,
    *,
    u_lower=None, v_lower=None,
    u_upper=None, v_upper=None,
    omega=None,
) -> dict:
    """Attach the physical character and drop the line if a necessary witness fails."""
    metrics = evidence["metrics"]
    line = np.asarray(candidate["coordinates"], dtype=float)
    normal = np.asarray(candidate["warmNormal"], dtype=float)
    fraction = frontogenesis_fraction(
        evidence["frontogenesis"], line, longitudes, latitudes, metrics
    )
    candidate["frontogenesisFraction"] = (
        None if not np.isfinite(fraction) else round(fraction, 2)
    )
    alignment = thermal_wind_alignment(
        line, normal, u_lower, v_lower, u_upper, v_upper,
        longitudes, latitudes, metrics,
    )
    candidate["thermalWindAlignment"] = (
        None if not np.isfinite(alignment) else round(alignment, 2)
    )
    candidate["frontalCharacter"] = frontal_character(
        line, normal, u_lower, v_lower, longitudes, latitudes, metrics,
        u_upper=u_upper, v_upper=v_upper, omega=omega,
    )
    failed = []
    if np.isfinite(fraction) and fraction < MIN_FRONTOGENESIS_FRACTION:
        failed.append("frontogenesis")
    if np.isfinite(alignment) and alignment < MIN_THERMAL_WIND_ALIGNMENT:
        failed.append("thermal-wind")
    candidate["physicalGate"] = "pass" if not failed else "fail:" + "+".join(failed)
    return candidate


def passes_physical_gate(candidate: dict) -> bool:
    return not str(candidate.get("physicalGate", "pass")).startswith("fail")
