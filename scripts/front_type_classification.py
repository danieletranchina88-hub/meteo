"""Frontal type classification: cold, warm, occluded, stationary.

Extends front_character.py with a complete synoptic classification based on:
1. Thermal advection (cold vs warm)
2. Front movement (active vs stationary)
3. Vertical thermal structure (occluded detection)
4. Surface pressure pattern (trough vs ridge)

The classification follows the classical Norwegian school definitions,
adapted for objective detection on ICON-2I 2km fields.

References:
- Petterssen (1956), Weather Analysis and Forecasting
- Sanders (1955), An investigation of the structure and dynamics of an intense cold front
- Hewson (1998), Objective fronts
- Sansom & Catto (2024), Objective front climatology
"""

from __future__ import annotations

import numpy as np

import front_locator as fl
import front_character as fch


# Classification thresholds - calibrated for Mediterranean region
COLD_ADVECTION_THRESHOLD = -1.5    # K/(3h) - strong cold advection
WARM_ADVECTION_THRESHOLD = 1.0     # K/(3h) - moderate warm advection
STATIONARY_SPEED_THRESHOLD = 5.0   # km/h - below this, front is stationary
OCCLUSION_THERMAL_CUTOFF = 0.5     # K - weak thermal gradient aloft
OCCLUSION_VERTICAL_RATIO = 0.3     # upper/lower gradient ratio for occlusion


def thermal_advection(
    theta_w: np.ndarray,
    u_wind: np.ndarray,
    v_wind: np.ndarray,
    longitudes: np.ndarray,
    latitudes: np.ndarray,
    metrics: dict | None = None,
    sigma_km: float = 100.0,
    dt_hours: float = 3.0,
) -> np.ndarray:
    """Compute thermal advection in K per dt_hours.

    Advection = -V . grad(theta_w)

    Negative values indicate cold advection (wind blowing from cold to warm).
    Positive values indicate warm advection (wind blowing from warm to cold).

    The result is scaled to K/(3h) for comparison with synoptic analysis.
    """
    metrics = metrics or fl.grid_metrics(longitudes, latitudes)

    # Smooth fields to synoptic scale
    theta = fl.smooth_km(np.asarray(theta_w, dtype=float), sigma_km, metrics)
    u = fl.smooth_km(np.asarray(u_wind, dtype=float), sigma_km, metrics)
    v = fl.smooth_km(np.asarray(v_wind, dtype=float), sigma_km, metrics)

    # Compute gradient of theta
    grad_e, grad_n = fl.gradient(theta, metrics)

    # Advection: -V . grad(theta) in K/s, then scale to K/(dt_hours)
    advection_per_s = -(u * grad_e + v * grad_n)
    advection_per_dt = advection_per_s * dt_hours * 3600.0

    return advection_per_dt


def front_speed(
    coordinates: np.ndarray,
    warm_normal: np.ndarray,
    u_wind: np.ndarray,
    v_wind: np.ndarray,
    longitudes: np.ndarray,
    latitudes: np.ndarray,
    metrics: dict | None = None,
) -> float:
    """Estimate front speed perpendicular to the front in km/h.

    Uses the component of the wind normal to the front, following
    Hewson\'s K3 speed rule adapted for objective detection.
    """
    if metrics is None:
        metrics = fl.grid_metrics(longitudes, latitudes)

    line = np.asarray(coordinates, dtype=float)
    normal = np.asarray(warm_normal, dtype=float)

    if len(line) < 2 or len(normal) != len(line):
        return float('nan')

    # Sample wind along the front
    u = fl._sample(u_wind, line, longitudes, latitudes,
                   float(metrics["dlon"]), float(metrics["dlat"]))
    v = fl._sample(v_wind, line, longitudes, latitudes,
                   float(metrics["dlon"]), float(metrics["dlat"]))

    # Normal component of wind (positive = moving toward warm air)
    normal_wind = u * normal[:, 0] + v * normal[:, 1]

    # Front moves opposite to the cold air advection
    speed_ms = -np.nanmedian(normal_wind)
    speed_kmh = speed_ms * 3.6

    return float(speed_kmh)


def vertical_thermal_structure(
    theta_w_lower: np.ndarray,
    theta_w_upper: np.ndarray,
    longitudes: np.ndarray,
    latitudes: np.ndarray,
    metrics: dict | None = None,
    sigma_km: float = 100.0,
) -> dict:
    """Analyze vertical thermal structure for occlusion detection.

    An occluded front has a weak thermal gradient at the surface but
    retains structure aloft, or vice versa.

    Returns a dict with diagnostic ratios and structure classification.
    """
    if metrics is None:
        metrics = fl.grid_metrics(longitudes, latitudes)

    if theta_w_lower is None or theta_w_upper is None:
        return {
            "structure": "unknown",
            "lower_gradient": float('nan'),
            "upper_gradient": float('nan'),
            "ratio": float('nan'),
        }

    lower = fl.smooth_km(np.asarray(theta_w_lower, dtype=float), sigma_km, metrics)
    upper = fl.smooth_km(np.asarray(theta_w_upper, dtype=float), sigma_km, metrics)

    lower_e, lower_n = fl.gradient(lower, metrics)
    upper_e, upper_n = fl.gradient(upper, metrics)

    lower_mag = np.hypot(lower_e, lower_n)
    upper_mag = np.hypot(upper_e, upper_n)

    lower_median = float(np.nanmedian(lower_mag))
    upper_median = float(np.nanmedian(upper_mag))

    ratio = upper_median / max(lower_median, 1e-9)

    # Classify structure
    if lower_median < OCCLUSION_THERMAL_CUTOFF * 1e-5 and upper_median > OCCLUSION_THERMAL_CUTOFF * 1e-5:
        structure = "occluded-cold-type"
    elif lower_median > OCCLUSION_THERMAL_CUTOFF * 1e-5 and upper_median < OCCLUSION_THERMAL_CUTOFF * 1e-5:
        structure = "occluded-warm-type"
    elif ratio < OCCLUSION_VERTICAL_RATIO:
        structure = "shallow"
    elif ratio > 1.0 / OCCLUSION_VERTICAL_RATIO:
        structure = "upper-level"
    else:
        structure = "deep"

    return {
        "structure": structure,
        "lower_gradient": lower_median,
        "upper_gradient": upper_median,
        "ratio": ratio,
    }


def classify_front_type(
    candidate: dict,
    theta_w: np.ndarray,
    u_wind: np.ndarray,
    v_wind: np.ndarray,
    longitudes: np.ndarray,
    latitudes: np.ndarray,
    metrics: dict | None = None,
    theta_w_lower: np.ndarray | None = None,
    theta_w_upper: np.ndarray | None = None,
    pressure: np.ndarray | None = None,
    dt_hours: float = 3.0,
    sigma_km: float = 100.0,
) -> dict:
    """Complete frontal type classification.

    Returns a dict with:
    - frontType: "cold", "warm", "occluded", "stationary", "unclassified"
    - confidence: classification confidence [0, 1]
    - diagnostics: supporting evidence for the classification
    """
    if metrics is None:
        metrics = fl.grid_metrics(longitudes, latitudes)

    line = np.asarray(candidate["coordinates"], dtype=float)
    warm_normal = np.asarray(candidate.get("warmNormal", np.zeros_like(line)), dtype=float)

    if len(line) < 2:
        return {
            "frontType": "unclassified",
            "confidence": 0.0,
            "diagnostics": {"reason": "insufficient geometry"},
        }

    # 1. Compute thermal advection along the front
    advection = thermal_advection(
        theta_w, u_wind, v_wind, longitudes, latitudes,
        metrics=metrics, sigma_km=sigma_km, dt_hours=dt_hours
    )
    line_advection = fl._sample(
        advection, line, longitudes, latitudes,
        float(metrics["dlon"]), float(metrics["dlat"])
    )
    median_advection = float(np.nanmedian(line_advection)) if len(line_advection) > 0 else float('nan')

    # 2. Estimate front speed
    speed_kmh = front_speed(
        line, warm_normal, u_wind, v_wind,
        longitudes, latitudes, metrics
    )

    # 3. Analyze vertical structure for occlusion detection
    vertical = vertical_thermal_structure(
        theta_w_lower, theta_w_upper,
        longitudes, latitudes, metrics, sigma_km
    )

    # 4. Pressure pattern (trough vs ridge)
    pressure_pattern = "unknown"
    if pressure is not None:
        p = fl.smooth_km(np.asarray(pressure, dtype=float), sigma_km, metrics)
        lap = fl.laplacian(p, metrics) * 1e4
        line_pressure = fl._sample(
            lap, line, longitudes, latitudes,
            float(metrics["dlon"]), float(metrics["dlat"])
        )
        median_lap = float(np.nanmedian(line_pressure)) if len(line_pressure) > 0 else 0.0
        if median_lap < -0.3:
            pressure_pattern = "trough"
        elif median_lap > 0.3:
            pressure_pattern = "ridge"
        else:
            pressure_pattern = "neutral"

    # Classification decision tree
    front_type = "unclassified"
    confidence = 0.0
    reasons = []

    # Check for stationary first
    if np.isfinite(speed_kmh) and abs(speed_kmh) < STATIONARY_SPEED_THRESHOLD:
        front_type = "stationary"
        confidence = min(1.0, 1.0 - abs(speed_kmh) / STATIONARY_SPEED_THRESHOLD)
        reasons.append(f"speed={speed_kmh:.1f} km/h < {STATIONARY_SPEED_THRESHOLD} km/h")

    # Check for occlusion based on vertical structure
    elif vertical["structure"] in ("occluded-cold-type", "occluded-warm-type"):
        front_type = "occluded"
        confidence = 0.8
        reasons.append(f"vertical structure: {vertical['structure']}")

    # Classify based on thermal advection
    elif np.isfinite(median_advection):
        if median_advection <= COLD_ADVECTION_THRESHOLD:
            front_type = "cold"
            confidence = min(1.0, abs(median_advection) / (2 * abs(COLD_ADVECTION_THRESHOLD)))
            reasons.append(f"cold advection: {median_advection:.2f} K/3h")

            if pressure_pattern == "trough":
                confidence = min(1.0, confidence + 0.15)
                reasons.append("pressure trough supports cold front")

            if candidate.get("frontalCharacter") == "anafront":
                confidence = min(1.0, confidence + 0.10)
                reasons.append("anafront character supports cold front")

        elif median_advection >= WARM_ADVECTION_THRESHOLD:
            front_type = "warm"
            confidence = min(1.0, median_advection / (2 * WARM_ADVECTION_THRESHOLD))
            reasons.append(f"warm advection: {median_advection:.2f} K/3h")

            if candidate.get("frontalCharacter") == "katafront":
                confidence = min(1.0, confidence + 0.10)
                reasons.append("katafront character supports warm front")

        else:
            front_type = "stationary" if abs(median_advection) < 0.5 else "unclassified"
            confidence = 0.4
            reasons.append(f"weak advection: {median_advection:.2f} K/3h")

    else:
        reasons.append("advection data unavailable")

    return {
        "frontType": front_type,
        "confidence": round(confidence, 3),
        "diagnostics": {
            "medianThermalAdvectionK3h": round(median_advection, 3) if np.isfinite(median_advection) else None,
            "frontSpeedKmh": round(speed_kmh, 2) if np.isfinite(speed_kmh) else None,
            "verticalStructure": vertical["structure"],
            "pressurePattern": pressure_pattern,
            "reasons": reasons,
        },
    }


def annotate_with_type(
    candidate: dict,
    theta_w: np.ndarray,
    u_wind: np.ndarray,
    v_wind: np.ndarray,
    longitudes: np.ndarray,
    latitudes: np.ndarray,
    metrics: dict | None = None,
    theta_w_lower: np.ndarray | None = None,
    theta_w_upper: np.ndarray | None = None,
    pressure: np.ndarray | None = None,
) -> dict:
    """Add front type classification to an existing candidate."""
    classification = classify_front_type(
        candidate, theta_w, u_wind, v_wind,
        longitudes, latitudes, metrics,
        theta_w_lower, theta_w_upper, pressure,
    )

    candidate["frontType"] = classification["frontType"]
    candidate["frontTypeConfidence"] = classification["confidence"]
    candidate["frontTypeDiagnostics"] = classification["diagnostics"]

    return candidate


# Color mapping for visualization
FRONT_TYPE_COLORS = {
    "cold": "#1e88e5",
    "warm": "#e53935",
    "occluded": "#8e24aa",
    "stationary": "#43a047",
    "unclassified": "#757575",
}

FRONT_TYPE_SYMBOLS = {
    "cold": "triangles",
    "warm": "semicircles",
    "occluded": "alternating",
    "stationary": "alternating-both-sides",
    "unclassified": "plain",
}


def get_front_style(front_type: str) -> dict:
    """Get visualization style for a front type."""
    return {
        "color": FRONT_TYPE_COLORS.get(front_type, FRONT_TYPE_COLORS["unclassified"]),
        "symbol": FRONT_TYPE_SYMBOLS.get(front_type, FRONT_TYPE_SYMBOLS["unclassified"]),
        "lineWidth": 3.0 if front_type in ("cold", "warm", "occluded") else 2.0,
        "dashArray": None if front_type != "stationary" else [8, 4],
    }
