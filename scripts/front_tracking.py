"""Temporal tracking of frontal systems across time steps.

Implements geometric matching between consecutive time steps to:
1. Identify the same front across time
2. Compute front speed and direction
3. Detect frontogenesis/frontolysis
4. Enable nowcasting of front position

The tracking uses a combination of:
- Geometric overlap (bidirectional support fraction)
- Orientation consistency
- Displacement vector coherence

References:
- Hewson (1998), Objective fronts - K3 speed rule
- Bengtsson & Andrae (2001), Front tracking methods
"""

from __future__ import annotations

import numpy as np

import front_locator as fl
import front_detection as fd


# Tracking parameters
MAX_FRONT_SPEED_KMH = 80.0
MAX_TRACK_GAP_HOURS = 12.0
MIN_OVERLAP_FOR_MATCH = 0.40
MIN_ORIENTATION_COSINE = 0.70


def front_displacement(
    front_a: np.ndarray,
    front_b: np.ndarray,
    longitudes: np.ndarray,
    latitudes: np.ndarray,
    metrics: dict | None = None,
) -> dict:
    """Compute displacement vector between two front positions.

    Returns the mean displacement vector and its statistics.
    The displacement is computed by matching points along the fronts.
    """
    if metrics is None:
        metrics = fl.grid_metrics(longitudes, latitudes)

    spacing_km = 20.0
    a = fd._resample_km(front_a, spacing_km)
    b = fd._resample_km(front_b, spacing_km)

    if len(a) < 2 or len(b) < 2:
        return {
            "meanDisplacementKm": float('nan'),
            "meanDirectionDeg": float('nan'),
            "displacementStdKm": float('nan'),
        }

    mean_lat = np.deg2rad(float(np.mean(a[:, 1])))
    scale_lon = 111.32 * np.cos(mean_lat)
    scale_lat = 111.32

    a_km = np.column_stack((a[:, 0] * scale_lon, a[:, 1] * scale_lat))
    b_km = np.column_stack((b[:, 0] * scale_lon, b[:, 1] * scale_lat))

    displacements = []
    for point_a in a_km:
        distances = np.hypot(b_km[:, 0] - point_a[0], b_km[:, 1] - point_a[1])
        nearest_idx = np.argmin(distances)
        if distances[nearest_idx] < 200.0:
            disp = b_km[nearest_idx] - point_a
            displacements.append(disp)

    if len(displacements) < 3:
        return {
            "meanDisplacementKm": float('nan'),
            "meanDirectionDeg": float('nan'),
            "displacementStdKm": float('nan'),
        }

    displacements = np.array(displacements)
    mean_disp = np.mean(displacements, axis=0)
    mean_distance = np.hypot(mean_disp[0], mean_disp[1])
    mean_direction = np.degrees(np.arctan2(mean_disp[0], mean_disp[1]))
    std_distance = np.std(np.hypot(displacements[:, 0], displacements[:, 1]))

    return {
        "meanDisplacementKm": round(float(mean_distance), 2),
        "meanDirectionDeg": round(float(mean_direction), 1),
        "displacementStdKm": round(float(std_distance), 2),
    }


def match_fronts_between_steps(
    fronts_t0: list[dict],
    fronts_t1: list[dict],
    longitudes: np.ndarray,
    latitudes: np.ndarray,
    dt_hours: float = 3.0,
    metrics: dict | None = None,
) -> list[dict]:
    """Match fronts between two consecutive time steps.

    Returns a list of matches, each containing:
    - front_t0_index: index in fronts_t0
    - front_t1_index: index in fronts_t1
    - overlap: bidirectional support fraction
    - displacement: computed displacement vector
    - speed_kmh: estimated front speed
    - confidence: matching confidence
    """
    if metrics is None:
        metrics = fl.grid_metrics(longitudes, latitudes)

    if not fronts_t0 or not fronts_t1:
        return []

    n_t0 = len(fronts_t0)
    n_t1 = len(fronts_t1)
    overlaps = np.zeros((n_t0, n_t1))

    for i, front_t0 in enumerate(fronts_t0):
        coords_t0 = np.asarray(front_t0["coordinates"], dtype=float)
        for j, front_t1 in enumerate(fronts_t1):
            coords_t1 = np.asarray(front_t1["coordinates"], dtype=float)
            overlap = fd._overlap_fraction(coords_t0, coords_t1, 55.0)
            overlaps[i, j] = overlap

    matches = []
    used_t0 = set()
    used_t1 = set()

    sorted_pairs = []
    for i in range(n_t0):
        for j in range(n_t1):
            if overlaps[i, j] >= MIN_OVERLAP_FOR_MATCH:
                sorted_pairs.append((overlaps[i, j], i, j))
    sorted_pairs.sort(reverse=True)

    for overlap, i, j in sorted_pairs:
        if i in used_t0 or j in used_t1:
            continue

        front_t0 = fronts_t0[i]
        front_t1 = fronts_t1[j]
        coords_t0 = np.asarray(front_t0["coordinates"], dtype=float)
        coords_t1 = np.asarray(front_t1["coordinates"], dtype=float)

        orientation_t0 = _front_orientation(coords_t0)
        orientation_t1 = _front_orientation(coords_t1)
        orientation_cosine = abs(np.dot(orientation_t0, orientation_t1))

        if orientation_cosine < MIN_ORIENTATION_COSINE:
            continue

        displacement = front_displacement(
            coords_t0, coords_t1, longitudes, latitudes, metrics
        )

        if np.isfinite(displacement["meanDisplacementKm"]):
            speed_kmh = displacement["meanDisplacementKm"] / dt_hours
        else:
            speed_kmh = float('nan')

        if np.isfinite(speed_kmh) and speed_kmh > MAX_FRONT_SPEED_KMH:
            continue

        confidence = overlap * orientation_cosine
        if np.isfinite(speed_kmh) and speed_kmh < MAX_FRONT_SPEED_KMH:
            confidence *= min(1.0, speed_kmh / 20.0 + 0.5)

        matches.append({
            "front_t0_index": i,
            "front_t1_index": j,
            "overlap": round(overlap, 3),
            "orientationCosine": round(orientation_cosine, 3),
            "displacement": displacement,
            "speedKmh": round(speed_kmh, 2) if np.isfinite(speed_kmh) else None,
            "confidence": round(confidence, 3),
            "front_t0_id": front_t0.get("trackId"),
            "front_t1_id": front_t1.get("trackId"),
        })

        used_t0.add(i)
        used_t1.add(j)

    return matches


def _front_orientation(coordinates: np.ndarray) -> np.ndarray:
    """Compute the mean orientation vector of a front."""
    if len(coordinates) < 2:
        return np.array([1.0, 0.0])

    points = fd._resample_km(coordinates, 30.0)
    if len(points) < 2:
        return np.array([1.0, 0.0])

    delta = points[-1] - points[0]
    length = np.hypot(delta[0], delta[1])
    if length < 1e-6:
        return np.array([1.0, 0.0])

    return delta / length


def assign_track_ids(
    fronts_by_time: list[list[dict]],
    longitudes: np.ndarray,
    latitudes: np.ndarray,
    dt_hours: float = 3.0,
    metrics: dict | None = None,
) -> list[list[dict]]:
    """Assign unique track IDs to fronts across all time steps.

    This enables tracking the same front through time.
    Each front gets a trackId and trackStep field.
    """
    if metrics is None:
        metrics = fl.grid_metrics(longitudes, latitudes)

    if not fronts_by_time:
        return fronts_by_time

    track_counter = 0
    for front in fronts_by_time[0]:
        front["trackId"] = track_counter
        front["trackStep"] = 0
        track_counter += 1

    for t in range(1, len(fronts_by_time)):
        fronts_prev = fronts_by_time[t - 1]
        fronts_curr = fronts_by_time[t]

        matches = match_fronts_between_steps(
            fronts_prev, fronts_curr,
            longitudes, latitudes,
            dt_hours=dt_hours, metrics=metrics
        )

        track_mapping = {}
        for match in matches:
            prev_idx = match["front_t0_index"]
            curr_idx = match["front_t1_index"]
            prev_track = fronts_prev[prev_idx].get("trackId")
            if prev_track is not None:
                track_mapping[curr_idx] = prev_track

        for j, front in enumerate(fronts_curr):
            if j in track_mapping:
                front["trackId"] = track_mapping[j]
            else:
                front["trackId"] = track_counter
                track_counter += 1
            front["trackStep"] = t

    return fronts_by_time


def detect_frontogenesis_frontolysis(
    fronts_by_time: list[list[dict]],
    dt_hours: float = 3.0,
) -> list[dict]:
    """Detect frontogenesis (strengthening) and frontolysis (weakening).

    Compares front characteristics between consecutive time steps
    to identify strengthening or weakening trends.
    """
    events = []

    for t in range(1, len(fronts_by_time)):
        fronts_prev = fronts_by_time[t - 1]
        fronts_curr = fronts_by_time[t]

        prev_by_track = {f["trackId"]: f for f in fronts_prev if "trackId" in f}
        curr_by_track = {f["trackId"]: f for f in fronts_curr if "trackId" in f}

        for track_id in prev_by_track:
            if track_id not in curr_by_track:
                events.append({
                    "trackId": track_id,
                    "timeStep": t,
                    "event": "frontolysis-complete",
                    "description": "Front completely dissipated",
                })
                continue

            front_prev = prev_by_track[track_id]
            front_curr = curr_by_track[track_id]

            length_prev = front_prev.get("lengthKm", 0)
            length_curr = front_curr.get("lengthKm", 0)
            length_change = (length_curr - length_prev) / max(length_prev, 1)

            confidence_prev = front_prev.get("locatorConfidence", 0)
            confidence_curr = front_curr.get("locatorConfidence", 0)
            confidence_change = confidence_curr - confidence_prev

            gradient_prev = front_prev.get("medianAbzGradient", 0)
            gradient_curr = front_curr.get("medianAbzGradient", 0)
            gradient_change = (gradient_curr - gradient_prev) / max(gradient_prev, 1e-6)

            if length_change > 0.2 and confidence_change > 0.1:
                event = "frontogenesis"
            elif length_change < -0.2 and confidence_change < -0.1:
                event = "frontolysis"
            else:
                event = "steady"

            events.append({
                "trackId": track_id,
                "timeStep": t,
                "event": event,
                "lengthChangePercent": round(length_change * 100, 1),
                "confidenceChange": round(confidence_change, 3),
                "gradientChangePercent": round(gradient_change * 100, 1),
            })

    return events


def nowcast_front_position(
    front: dict,
    speed_kmh: float,
    direction_deg: float,
    forecast_hours: float = 6.0,
) -> np.ndarray:
    """Predict future front position based on current speed and direction.

    Simple linear extrapolation for nowcasting.
    """
    coordinates = np.asarray(front["coordinates"], dtype=float)

    if len(coordinates) < 2 or not np.isfinite(speed_kmh) or not np.isfinite(direction_deg):
        return coordinates

    direction_rad = np.deg2rad(direction_deg)
    displacement_km = speed_kmh * forecast_hours

    dx_km = displacement_km * np.sin(direction_rad)
    dy_km = displacement_km * np.cos(direction_rad)

    mean_lat = np.deg2rad(float(np.mean(coordinates[:, 1])))
    dx_deg = dx_km / (111.32 * np.cos(mean_lat))
    dy_deg = dy_km / 111.32

    forecast_coords = coordinates.copy()
    forecast_coords[:, 0] += dx_deg
    forecast_coords[:, 1] += dy_deg

    return forecast_coords
