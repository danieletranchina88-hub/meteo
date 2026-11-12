"""Global front tracking, motion classification and uncertainty (v18).

Tracking is a central part of the algorithm, not a persistence filter.
Candidates from consecutive hours are linked into tracks by a **global**
(Hungarian) assignment on a geometric cost that uses the track's predicted
position, symmetric line-to-line distance, orientation, length change and
warm-side consistency. Births and deaths are represented explicitly; a
split or merge is intentionally treated as the end of one identity and the
birth of another, rather than being claimed as a continuously tracked front.

Classification is the **median** of three independent estimates of the
boundary's speed toward the warm air (positive = cold front):

 1. geometric motion  - the real displacement of the line between hours,
    measured locally along the line and projected on the warm-ward normal;
 2. phase speed       - from the local theta-w tendency at the line;
 3. wind              - Hewson's OFA speed and the flow normal to the line.

Two estimates always bracket the median, so one wrong family neither
decides nor vetoes the type.  Disagreement lowers ``classificationCertainty``
instead of hiding the front: a detected, persistent air-mass boundary is
published with its best type and an honest confidence.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment

EARTH_KM_PER_DEG = 111.32
COLD_WARM_THRESHOLD_KMH = 5.4  # 1.5 m/s, Hewson/Berry/Sansom-Catto

# Physical diagnostics carried per hour and summarised per track. Shared by
# the track medians and the per-hour observations so the two views can never
# drift apart.
DIAGNOSTIC_KEYS = (
    "medianTfpStrength", "medianAbzGradient", "deltaThetaW",
    "deltaThetaE", "deltaTemperature", "deltaThetaV", "dryThermalGradient",
    "thermalAlignment", "windShiftMs", "convergenceMs",
    "thermalContrastFraction", "thermalAlignmentFraction",
    "crossDistanceThermalSupport",
    "windShiftAngleDeg", "windBoundaryFraction",
    "convergenceFraction", "airmassMotionKmh",
    "vorticity1e5", "frontogenesis", "pressureTroughHpa",
    "pressureTroughFraction", "linePressureTendencyHpa3h",
    "coldPressureTendencyHpa3h", "warmPressureTendencyHpa3h",
    "lowerLevelSupport", "deltaThetaW925", "omega700PaS",
    "deltaThetaW700", "upperValidFraction", "frontWidth700Km",
    "windShift700Ms", "upperWindValidFraction",
    "verticalCoherence700", "verticalCoherence3Level",
    "frontalTiltKm", "frontalTiltConsistency",
    "terrainFraction", "frontogenesisFraction", "thermalWindAlignment", "candidateEvidence",
    "physicalCandidateEvidence", "preConsensusEvidence",
    "consensusEvidenceBonus",
    "consensusSupport", "methodAgreementCount", "methodAvailability",
    "locatorAgreementCount", "positionUncertaintyKm",
    "parfittF", "parfittSupport", "parfittSupportFraction",
    "wndChangeMs6h", "wndTurnDeg", "wndSupport", "wndSupportFraction",
    "wndColdSupportFraction", "mlFrontProbability",
    "mlFrontProbabilityQ75", "mlSupportFraction", "fusionEvidenceBonus",
    "synopticSupport", "lengthKm", "sinuosity",
    "profileValidFraction", "profileThermalSupport", "profilePeakGradient",
    "frontWidthKm", "frontOffsetKm", "airMassHomogeneity",
    "verticalCoherence", "frontWidth925Km",
    "steeringUMs", "steeringVMs", "steeringSpeedMs",
    "steeringBearingDeg", "deepLayerWindChangeMs",
    "height500M", "deltaHeight500M",
)


def _finite_median(values, default=np.nan) -> float:
    array = np.asarray(values, dtype=float)
    finite = array[np.isfinite(array)]
    return float(np.median(finite)) if finite.size else float(default)


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------
def _project_km(coordinates: np.ndarray, mean_lat_rad: float) -> np.ndarray:
    scale_lon = EARTH_KM_PER_DEG * np.cos(mean_lat_rad)
    return np.column_stack((coordinates[:, 0] * scale_lon,
                            coordinates[:, 1] * EARTH_KM_PER_DEG))


def _resample(coordinates: np.ndarray, count: int = 32) -> np.ndarray:
    if len(coordinates) < 2:
        return np.repeat(coordinates, count, axis=0)[:count]
    deltas = np.diff(coordinates, axis=0)
    seg = np.hypot(deltas[:, 0], deltas[:, 1])
    cumulative = np.concatenate(([0.0], np.cumsum(seg)))
    total = max(cumulative[-1], 1.0e-9)
    targets = np.linspace(0.0, total, count)
    return np.column_stack((
        np.interp(targets, cumulative, coordinates[:, 0]),
        np.interp(targets, cumulative, coordinates[:, 1]),
    ))


def _aligned_resample(reference: np.ndarray, candidate: np.ndarray,
                      count: int = 32) -> tuple[np.ndarray, np.ndarray]:
    """Resample two lines and orient the second like the first."""
    first = _resample(reference, count)
    second = _resample(candidate, count)
    forward = float(np.mean(np.hypot(*(first - second).T)))
    backward = float(np.mean(np.hypot(*(first - second[::-1]).T)))
    if backward < forward:
        second = second[::-1]
    return first, second


def _length_km(coordinates: np.ndarray) -> float:
    if len(coordinates) < 2:
        return 0.0
    lon1, lat1 = coordinates[:-1, 0], coordinates[:-1, 1]
    lon2, lat2 = coordinates[1:, 0], coordinates[1:, 1]
    mean_lat = np.deg2rad((lat1 + lat2) * 0.5)
    dx = (lon2 - lon1) * EARTH_KM_PER_DEG * np.cos(mean_lat)
    dy = (lat2 - lat1) * EARTH_KM_PER_DEG
    return float(np.sum(np.hypot(dx, dy)))


def _symmetric_distance_km(line_a: np.ndarray, line_b: np.ndarray) -> float:
    """Mean symmetric nearest-neighbour distance between two lines (km)."""
    mean_lat = math_mean_lat(line_a, line_b)
    a = _project_km(_resample(line_a), mean_lat)
    b = _project_km(_resample(line_b), mean_lat)
    dab = np.min(np.hypot(a[:, None, 0] - b[None, :, 0],
                          a[:, None, 1] - b[None, :, 1]), axis=1)
    dba = np.min(np.hypot(b[:, None, 0] - a[None, :, 0],
                          b[:, None, 1] - a[None, :, 1]), axis=1)
    return 0.5 * (float(np.mean(dab)) + float(np.mean(dba)))


def _shorter_line_overlap_fraction(
    line_a: np.ndarray, line_b: np.ndarray, radius_km: float
) -> float:
    """Fraction of the shorter line supported by the longer one.

    This deliberately differs from a symmetric distance.  A front may grow
    or shrink by hundreds of kilometres along its own axis while retaining
    the same physical core; in that case its centroid moves but the shorter
    geometry still lies on the longer one.  Conversely, two disjoint pieces
    of the same long thermal ridge have almost no direct overlap and must not
    be linked merely because their infinite-axis orientation is similar.
    """
    line_a = np.asarray(line_a, dtype=float)
    line_b = np.asarray(line_b, dtype=float)
    mean_lat = math_mean_lat(line_a, line_b)
    a = _project_km(_resample(line_a), mean_lat)
    b = _project_km(_resample(line_b), mean_lat)
    shorter, longer = (
        (a, b) if _length_km(line_a) <= _length_km(line_b) else (b, a)
    )
    distances = np.hypot(
        shorter[:, None, 0] - longer[None, :, 0],
        shorter[:, None, 1] - longer[None, :, 1],
    )
    return float(np.mean(np.min(distances, axis=1) <= radius_km))


def _dense_km(line: np.ndarray, mean_lat_rad: float,
              spacing_km: float = 25.0, max_points: int = 240) -> np.ndarray:
    """Project a line to km, sampled every ``spacing_km`` along itself.

    The fixed 32-point resampling puts a vertex every 100 km on a 3000-km
    front: nearest-vertex distances between two such lines are then wrong by
    tens of kilometres, the same order as the hourly gates.
    """
    line = np.asarray(line, dtype=float)
    count = int(np.clip(np.ceil(_length_km(line) / spacing_km) + 1, 16, max_points))
    return _project_km(_resample(line, count), mean_lat_rad)


def _overlap_metrics(line_a: np.ndarray, line_b: np.ndarray,
                     radius_km: float) -> tuple[float, float]:
    """Extent-tolerant closeness of two lines.

    Returns the median distance from the shorter line to the longer one and
    the fraction of the shorter line lying within ``radius_km`` of it.  A
    synoptic front is detected over a different extent every hour (2900 km,
    then 1850 km, then 2760 km of the same boundary): a symmetric distance
    reads that as a 100-km jump and ends the identity, although every point
    of the shorter line still sits on the longer one.
    """
    line_a = np.asarray(line_a, dtype=float)
    line_b = np.asarray(line_b, dtype=float)
    mean_lat = math_mean_lat(line_a, line_b)
    a = _dense_km(line_a, mean_lat)
    b = _dense_km(line_b, mean_lat)
    shorter, longer = (
        (a, b) if _length_km(line_a) <= _length_km(line_b) else (b, a)
    )
    near = np.min(np.hypot(shorter[:, None, 0] - longer[None, :, 0],
                           shorter[:, None, 1] - longer[None, :, 1]), axis=1)
    return float(np.median(near)), float(np.mean(near <= radius_km))


def _normal_shift_deg(previous: np.ndarray, last: np.ndarray,
                      hours: float) -> np.ndarray:
    """Displacement (deg lon, deg lat) of a line between two detections.

    Measured point-to-nearest-point where the two lines overlap, so it is the
    motion ACROSS the line.  Matching points by index instead turns a change
    of extent into a fictitious slide of hundreds of kilometres along the
    front, and the prediction built on it misses the next detection.
    """
    previous = np.asarray(previous, dtype=float)
    last = np.asarray(last, dtype=float)
    mean_lat = math_mean_lat(previous, last)
    a = _dense_km(previous, mean_lat)
    b = _dense_km(last, mean_lat)
    gaps = np.hypot(a[:, None, 0] - b[None, :, 0], a[:, None, 1] - b[None, :, 1])
    nearest = np.argmin(gaps, axis=1)
    near = gaps[np.arange(len(a)), nearest]
    keep = near <= 120.0 * max(float(hours), 1.0)
    if np.mean(keep) < 0.30:
        return np.zeros(2)
    shift_km = np.median(b[nearest[keep]] - a[keep], axis=0)
    scale_lon = EARTH_KM_PER_DEG * max(np.cos(mean_lat), 0.25)
    return np.array([shift_km[0] / scale_lon, shift_km[1] / EARTH_KM_PER_DEG])


def math_mean_lat(*lines: np.ndarray) -> float:
    lats = np.concatenate([line[:, 1] for line in lines])
    return float(np.deg2rad(np.mean(lats)))


def _orientation_deg(coordinates: np.ndarray) -> float:
    tangent = coordinates[-1] - coordinates[0]
    mean_lat = np.deg2rad(float(np.mean(coordinates[:, 1])))
    angle = np.degrees(np.arctan2(tangent[1], tangent[0] * np.cos(mean_lat)))
    return angle % 180.0


def _orientation_diff(a: np.ndarray, b: np.ndarray) -> float:
    diff = abs(_orientation_deg(a) - _orientation_deg(b)) % 180.0
    return min(diff, 180.0 - diff)


def geometric_motion_kmh(
    line_prev: np.ndarray, line_next: np.ndarray,
    warm_normal_prev: np.ndarray, hours: float,
) -> float:
    """Signed displacement of the line along the warm-ward normal, km/h.

    Positive = the line moved toward the warm air (cold front); negative =
    toward the cold air (warm front).  Measured locally: each resampled
    point of the previous line is displaced to its nearest point on the
    next line and projected on the local warm normal.
    """
    mean_lat = math_mean_lat(line_prev, line_next)
    prev_km = _project_km(_resample(line_prev), mean_lat)
    next_km = _project_km(_resample(line_next), mean_lat)
    normal = _resample_vectors(warm_normal_prev, len(prev_km))
    scale_lon = EARTH_KM_PER_DEG * np.cos(mean_lat)
    normal_km = np.column_stack((normal[:, 0] * scale_lon,
                                 normal[:, 1] * EARTH_KM_PER_DEG))
    norm = np.hypot(normal_km[:, 0], normal_km[:, 1])
    normal_km /= np.maximum(norm[:, None], 1.0e-9)
    displacement = np.empty(len(prev_km))
    for i, point in enumerate(prev_km):
        j = np.argmin(np.hypot(next_km[:, 0] - point[0], next_km[:, 1] - point[1]))
        displacement[i] = np.dot(next_km[j] - point, normal_km[i])
    return float(np.median(displacement)) / max(hours, 1.0e-6)


def _resample_vectors(vectors: np.ndarray, count: int) -> np.ndarray:
    idx = np.linspace(0, len(vectors) - 1, count)
    lo = np.floor(idx).astype(int)
    hi = np.minimum(lo + 1, len(vectors) - 1)
    frac = (idx - lo)[:, None]
    return vectors[lo] * (1 - frac) + vectors[hi] * frac


# --------------------------------------------------------------------------
# Track objects
# --------------------------------------------------------------------------
class Track:
    __slots__ = ("id", "hours", "lines")

    def __init__(self, track_id: int, hour: int, candidate: dict):
        self.id = track_id
        self.hours = [hour]
        self.lines = {hour: candidate}

    def last_hour(self) -> int:
        return self.hours[-1]

    def predicted_line(self, hour: int) -> np.ndarray:
        """Predict geometry at ``hour`` by extrapolating the last motion."""
        last_candidate = self.lines[self.hours[-1]]
        last = last_candidate["coordinates"]
        if len(self.hours) < 2:
            # A first association has no geometric velocity yet.  ICON's
            # 700--500 hPa steering flow is useful only as a weak prior:
            # fronts do not move exactly with the mid-level wind, therefore
            # advect just one quarter of that displacement.  The hard
            # continuity gates below remain authoritative.
            try:
                u = float(last_candidate.get("steeringUMs"))
                v = float(last_candidate.get("steeringVMs"))
            except (TypeError, ValueError):
                return last
            speed = float(np.hypot(u, v))
            if not np.isfinite(speed) or speed > 90.0:
                return last
            elapsed = max(hour - self.hours[-1], 0)
            latitude = float(np.mean(last[:, 1]))
            lon_km = EARTH_KM_PER_DEG * max(np.cos(np.deg2rad(latitude)), 0.25)
            shift = np.array([
                0.25 * u * 3.6 * elapsed / lon_km,
                0.25 * v * 3.6 * elapsed / EARTH_KM_PER_DEG,
            ])
            return last + shift
        prev = self.lines[self.hours[-2]]["coordinates"]
        dt_hist = self.hours[-1] - self.hours[-2]
        dt_pred = hour - self.hours[-1]
        # rigid translation by the median cross-line displacement
        shift = _normal_shift_deg(prev, last, dt_hist) * (
            dt_pred / max(dt_hist, 1)
        )
        return last + shift


def _assignment_cost(track: Track, candidate: dict, hour: int,
                     gate_km: float) -> float:
    predicted = track.predicted_line(hour)
    line = candidate["coordinates"]
    gap_hours = max(hour - track.last_hour(), 1)
    # An hourly front cannot jump 250 km. Keep a hard ceiling for sparse
    # 6-hour steps while using a physical gate for ICON's hourly sequence.
    physical_gate = min(gate_km, 45.0 + 35.0 * gap_hours)
    # Distance from the shorter line to the longer: the same boundary seen
    # over a different extent is still the same boundary.  At least half of
    # the shorter line must lie on the longer one.
    distance, shared = _overlap_metrics(predicted, line, physical_gate)
    if distance > physical_gate or shared < 0.50:
        return np.inf
    # Symmetric nearest-line distance is insufficient for long fronts: two
    # disjoint fragments can sit on the same axis and look deceptively close
    # after one fragment grows.  Reject a centroid teleport unless a large
    # part of the shorter line is still the same boundary.
    previous_line = np.asarray(
        track.lines[track.hours[-1]]["coordinates"], dtype=float
    )
    mean_lat = math_mean_lat(previous_line, line)
    previous_centroid = _project_km(previous_line, mean_lat).mean(axis=0)
    candidate_centroid = _project_km(np.asarray(line, dtype=float), mean_lat).mean(axis=0)
    centroid_speed = float(np.hypot(*(candidate_centroid - previous_centroid))) / gap_hours
    direct_overlap = _shorter_line_overlap_fraction(
        previous_line, line, 55.0 + 20.0 * max(gap_hours - 1, 0)
    )
    if centroid_speed > 100.0 and direct_overlap < 0.45:
        return np.inf
    orient = _orientation_diff(predicted, line)
    if orient > 70.0:
        return np.inf
    length_prev = track.lines[track.hours[-1]]["lengthKm"]
    length_change = abs(candidate["lengthKm"] - length_prev) / max(length_prev, 1.0)
    previous_normal = _resample_vectors(
        track.lines[track.hours[-1]]["warmNormal"], 32
    )
    candidate_normal = _resample_vectors(candidate["warmNormal"], 32)
    predicted_points = _resample(predicted, 32)
    candidate_points = _resample(line, 32)
    forward = float(np.mean(np.hypot(*(predicted_points - candidate_points).T)))
    backward = float(np.mean(np.hypot(*(predicted_points - candidate_points[::-1]).T)))
    if backward < forward:
        candidate_normal = candidate_normal[::-1]
    normal_alignment = float(np.nanmedian(
        np.sum(previous_normal * candidate_normal, axis=1)
    ))
    if not np.isfinite(normal_alignment) or normal_alignment < 0.0:
        return np.inf
    return (
        distance
        + 2.0 * orient
        + 60.0 * min(length_change, 2.0)
        + 55.0 * (1.0 - np.clip(normal_alignment, 0.0, 1.0))
    )


def _global_assign(tracks: list[Track], candidates: list[dict], hour: int,
                   gate_km: float):
    """Hungarian assignment of candidates to active tracks (birth/death)."""
    if not tracks:
        return {}, list(range(len(candidates)))
    if not candidates:
        return {}, []
    cost = np.full((len(tracks), len(candidates)), 1.0e6)
    for i, track in enumerate(tracks):
        for j, candidate in enumerate(candidates):
            c = _assignment_cost(track, candidate, hour, gate_km)
            cost[i, j] = c if np.isfinite(c) else 1.0e6
    rows, cols = linear_sum_assignment(cost)
    matches, matched_candidates = {}, set()
    for r, c in zip(rows, cols):
        if cost[r, c] < 1.0e6:
            matches[r] = c
            matched_candidates.add(c)
    unmatched = [j for j in range(len(candidates)) if j not in matched_candidates]
    return matches, unmatched


# --------------------------------------------------------------------------
# Classification (consensus)
# --------------------------------------------------------------------------
def _stitch_cost(a: "Track", b: "Track", max_gap: int) -> float:
    """Cost of continuing track ``a`` with track ``b`` across a short gap.

    A physical front that briefly drops below detection for a single hour is
    split by the online (causal) tracker into two consecutive tracks, because
    the 2-hour forward prediction that would re-link them is deliberately
    strict. With both pieces now in hand we re-test the link with hindsight:
    across exactly one missing hour the end of ``a`` and the start of ``b``
    must be physically close (centroid travel under ~65 km/h, small line-to-
    line distance), similarly oriented and facing the same warm side.
    Returns +inf when any condition fails.
    """
    gap = b.hours[0] - a.hours[-1]
    # Up to ``max_gap`` missing hours. The same-boundary test is the extent-
    # tolerant one: most of the shorter line must lie within physical front
    # travel of the longer, and the cross-line shift is speed-capped.
    if gap < 1 or gap > max_gap + 1:
        return np.inf
    return _recovery_cost(
        a.lines[a.hours[-1]]["coordinates"], a.lines[a.hours[-1]]["warmNormal"],
        b.lines[b.hours[0]]["coordinates"], b.lines[b.hours[0]]["warmNormal"],
        gap,
    )


def _continuity_cost(a_line, a_normal, b_line, b_normal, gap: int) -> float:
    """Physical same-boundary cost between two lines ``gap`` hours apart.

    Shared by track stitching and weak-candidate recovery. A front's centroid
    does not exceed ~65 km/h (the decisive teleport guard: the symmetric
    distance alone is fooled by two long parallel lines that overlap
    end-to-end); the lines must also be directly close, similarly oriented,
    of comparable length, and facing the same warm side. +inf when any
    condition fails.
    """
    a_line = np.asarray(a_line, dtype=float)
    b_line = np.asarray(b_line, dtype=float)
    mean_lat = math_mean_lat(a_line, b_line)
    ca = _project_km(a_line, mean_lat).mean(axis=0)
    cb = _project_km(b_line, mean_lat).mean(axis=0)
    if float(np.hypot(*(cb - ca))) > 65.0 * gap:
        return np.inf
    distance = _symmetric_distance_km(a_line, b_line)
    if distance > 40.0 + 45.0 * gap:
        return np.inf
    if _orientation_diff(a_line, b_line) > 45.0:
        return np.inf
    length_a = _length_km(a_line)
    length_b = _length_km(b_line)
    if max(length_a, length_b) > 2.5 * max(min(length_a, length_b), 1.0):
        return np.inf
    normal_a = _resample_vectors(np.asarray(a_normal, dtype=float), 32)
    normal_b = _resample_vectors(np.asarray(b_normal, dtype=float), 32)
    pa = _resample(a_line, 32)
    pb = _resample(b_line, 32)
    if float(np.mean(np.hypot(*(pa - pb[::-1]).T))) < float(np.mean(np.hypot(*(pa - pb).T))):
        normal_b = normal_b[::-1]
    facing = float(np.nanmedian(np.sum(normal_a * normal_b, axis=1)))
    if not np.isfinite(facing) or facing < 0.0:
        return np.inf
    return distance + 2.0 * _orientation_diff(a_line, b_line)


def _recovery_cost(a_line, a_normal, b_line, b_normal, gap: int) -> float:
    """Same-boundary cost for weak-phase recovery, elongation-tolerant.

    Weak-phase detections of one boundary fragment and change extent hour to
    hour, so the full-centroid guard of ``_continuity_cost`` wrongly punishes
    a line that merely grew along itself. Physically a front moves normal to
    itself: only the CROSS-line component of the centroid displacement is
    speed-capped (~80 km/h, generous for a noisy weak phase), while along-
    line growth is free. Proximity uses the median one-sided distance from
    the shorter line to the longer, again robust to extent changes.
    """
    a_line = np.asarray(a_line, dtype=float)
    b_line = np.asarray(b_line, dtype=float)
    if _orientation_diff(a_line, b_line) > 45.0:
        return np.inf
    length_a = _length_km(a_line)
    length_b = _length_km(b_line)
    # Extent changes are the NORM in the weak phase (the detected window of
    # one long boundary slides and fragments), so the ratio guard is loose:
    # the overlap fraction below is what really decides same-boundary.
    if max(length_a, length_b) > 4.0 * max(min(length_a, length_b), 1.0):
        return np.inf
    mean_lat = math_mean_lat(a_line, b_line)
    a_km = _project_km(_resample(a_line), mean_lat)
    b_km = _project_km(_resample(b_line), mean_lat)
    dense_a = _dense_km(a_line, mean_lat)
    dense_b = _dense_km(b_line, mean_lat)
    short, long_ = (dense_a, dense_b) if length_a <= length_b else (dense_b, dense_a)
    gaps = np.hypot(short[:, None, 0] - long_[None, :, 0],
                    short[:, None, 1] - long_[None, :, 1])
    near = np.min(gaps, axis=1)
    # Decisive same-boundary gate: a substantial fraction of the shorter
    # line must lie within physical front travel (~65 km/h) of the longer.
    # Fragments of one long boundary whose detected window slides along it
    # keep a large overlap; a nearby but distinct boundary (e.g. an alpine
    # lee line north of a cold front) has almost none.
    if float(np.mean(near <= 65.0 * gap)) < 0.40:
        return np.inf
    distance = float(np.median(near))
    if distance > 60.0 + 50.0 * gap:
        return np.inf
    # cross-line displacement of the centroid, along the reference normal
    normal_a = _resample_vectors(np.asarray(a_normal, dtype=float), 32)
    scale_lon = EARTH_KM_PER_DEG * np.cos(mean_lat)
    normal_km = np.column_stack((normal_a[:, 0] * scale_lon,
                                 normal_a[:, 1] * EARTH_KM_PER_DEG))
    mean_normal = np.nanmean(
        normal_km / np.maximum(np.hypot(*normal_km.T)[:, None], 1.0e-9), axis=0
    )
    mean_normal /= max(float(np.hypot(*mean_normal)), 1.0e-9)
    shift = b_km.mean(axis=0) - a_km.mean(axis=0)
    if abs(float(np.dot(shift, mean_normal))) > 80.0 * gap:
        return np.inf
    normal_b = _resample_vectors(np.asarray(b_normal, dtype=float), 32)
    if float(np.mean(np.hypot(*(a_km - b_km[::-1]).T))) < float(
            np.mean(np.hypot(*(a_km - b_km).T))):
        normal_b = normal_b[::-1]
    facing = float(np.nanmedian(np.sum(
        _resample_vectors(np.asarray(a_normal, dtype=float), 32) * normal_b,
        axis=1,
    )))
    if not np.isfinite(facing) or facing < 0.0:
        return np.inf
    return distance + 2.0 * _orientation_diff(a_line, b_line)


def _extend_track_weak(
    track: "Track", weak_by_hour: dict, used: set, max_extend: int = 18,
) -> list[int]:
    """Reclaim a track's weak-phase hours from gate-rejected candidates.

    A real boundary often exists for hours below the hard publication gates
    (weak thermal core early in its life) before strengthening into a
    published track. Those hours were detected, diagnosed ``synoptic-front``
    and rejected — the evidence is on file. With the published track in hand,
    its identity extends backward/forward through consecutive matching weak
    candidates (same ``_continuity_cost`` physics as stitching, one skipped
    hour allowed). Weak candidates can only EXTEND an established track:
    they never create one, so noise cannot bootstrap itself into a front.
    Mutates the track; returns the recovered hours.
    """
    recovered = []
    for direction in (-1, 1):
        for _ in range(max_extend):
            edge = track.hours[0] if direction < 0 else track.hours[-1]
            found = None
            for gap in (1, 2):
                hour = edge + direction * gap
                best = np.inf
                for index, candidate in enumerate(weak_by_hour.get(hour, [])):
                    if (hour, index) in used:
                        continue
                    cost = _recovery_cost(
                        track.lines[edge]["coordinates"],
                        track.lines[edge]["warmNormal"],
                        candidate["coordinates"], candidate["warmNormal"], gap,
                    )
                    if cost < best:
                        best, found = cost, (hour, index, candidate)
                if found is not None:
                    break
            if found is None:
                break
            hour, index, candidate = found
            used.add((hour, index))
            entry = dict(candidate)
            entry["gateStatus"] = "weak-continuation"
            track.lines[hour] = entry
            track.hours = sorted(set(track.hours) | {hour})
            recovered.append(hour)
    return sorted(recovered)


def _stitch_tracks(tracks: list["Track"], max_gap: int) -> list["Track"]:
    """Greedily merge consecutive same-identity tracks split by a short gap.

    Repeatedly joins the globally cheapest compatible (earlier -> later) pair
    until none qualifies. The missing hours are left as a gap in the merged
    track's ``hours``: the publisher bridges single-hour gaps between equal
    types by blending, so the boundary is drawn as one continuous, non-
    flickering front instead of two tracks with a hole between them.
    """
    tracks = list(tracks)
    while True:
        best = None
        best_cost = np.inf
        for i, a in enumerate(tracks):
            for j, b in enumerate(tracks):
                if i == j or b.hours[0] <= a.hours[-1]:
                    continue
                cost = _stitch_cost(a, b, max_gap)
                if cost < best_cost:
                    best_cost, best = cost, (i, j)
        if best is None:
            return tracks
        i, j = best
        a, b = tracks[i], tracks[j]
        a.hours = sorted(set(a.hours) | set(b.hours))
        a.lines.update(b.lines)
        tracks.pop(j)


def _type_from_speed(speed_kmh: float) -> str:
    if speed_kmh >= COLD_WARM_THRESHOLD_KMH:
        return "cold"
    if speed_kmh <= -COLD_WARM_THRESHOLD_KMH:
        return "warm"
    return "stationary"


def classify_track(track: Track, window_hours: int, wind_sampler=None) -> dict:
    """Classify only when three independent motion families agree.

    Geometry measures where the analysed boundary actually moved; phase
    speed follows the theta-w tendency; the wind family combines Hewson OFA
    speed and flow normal to the air-mass boundary.  Wind is deliberately a
    single family because its two diagnostics are not independent.
    """
    hours = track.hours
    geo_speeds = []
    motion_bearings = []
    for h_prev, h_next in zip(hours[:-1], hours[1:]):
        line_prev = track.lines[h_prev]["coordinates"]
        line_next = track.lines[h_next]["coordinates"]
        warm_prev = track.lines[h_prev]["warmNormal"]
        geo_speeds.append(
            geometric_motion_kmh(line_prev, line_next, warm_prev, h_next - h_prev)
        )
        previous_center = np.nanmean(np.asarray(line_prev, dtype=float), axis=0)
        next_center = np.nanmean(np.asarray(line_next, dtype=float), axis=0)
        mean_latitude = np.deg2rad(
            0.5 * (previous_center[1] + next_center[1])
        )
        east_km = (
            (next_center[0] - previous_center[0])
            * 111.195
            * np.cos(mean_latitude)
        )
        north_km = (next_center[1] - previous_center[1]) * 111.195
        if np.hypot(east_km, north_km) >= 2.0:
            motion_bearings.append(
                np.deg2rad(
                    (np.degrees(np.arctan2(east_km, north_km)) + 360.0)
                    % 360.0
                )
            )
    geo_motion = float(np.median(geo_speeds)) if geo_speeds else 0.0
    geo_mad = _finite_median(np.abs(np.asarray(geo_speeds) - geo_motion), 0.0) if geo_speeds else 0.0
    # The net displacement over the whole window divides the line's hourly
    # jitter (some 10 km) by the elapsed hours instead of keeping it in every
    # hourly speed: it is the better estimate whenever first and last line
    # still overlap.
    if len(hours) >= 3:
        first_line = track.lines[hours[0]]["coordinates"]
        last_line = track.lines[hours[-1]]["coordinates"]
        elapsed = hours[-1] - hours[0]
        _, shared = _overlap_metrics(first_line, last_line, 60.0 * elapsed)
        if shared >= 0.5:
            geo_motion = geometric_motion_kmh(
                first_line, last_line, track.lines[hours[0]]["warmNormal"], elapsed
            )
    geo_type = _type_from_speed(geo_motion) if geo_speeds else None
    if motion_bearings:
        bearing_sine = float(np.mean(np.sin(motion_bearings)))
        bearing_cosine = float(np.mean(np.cos(motion_bearings)))
        motion_bearing = (
            np.degrees(np.arctan2(bearing_sine, bearing_cosine)) + 360.0
        ) % 360.0
    else:
        motion_bearing = np.nan

    ofa_values = [
        track.lines[h].get("ofaSpeedMps", np.nan) for h in hours
    ]
    # Standard OFA speed is negative for cold fronts.  Convert to the common
    # convention used here: positive motion points toward warm air (cold).
    ofa_motion = -_finite_median(ofa_values) * 3.6
    tendency_motion = _finite_median([
        track.lines[h].get("tendencyMotionKmh", np.nan) for h in hours
    ])
    airmass_motion = _finite_median([
        track.lines[h].get("airmassMotionKmh", np.nan) for h in hours
    ])

    # Backward-compatible fallback for synthetic callers that provide winds
    # but not precomputed OFA diagnostics.
    if not np.isfinite(ofa_motion) and wind_sampler is not None:
        fallback = []
        for hour in hours:
            candidate = track.lines[hour]
            u, v = wind_sampler(hour, candidate["coordinates"])
            hewson = candidate["hewsonDir"]
            fallback.append(-np.nanmedian(
                u * hewson[:, 0] + v * hewson[:, 1]
            ) * 3.6)
        ofa_motion = _finite_median(fallback)

    ofa_type = _type_from_speed(ofa_motion) if np.isfinite(ofa_motion) else None
    airmass_type = (
        _type_from_speed(airmass_motion) if np.isfinite(airmass_motion) else None
    )
    wind_parts = [value for value in (ofa_type, airmass_type) if value]
    wind_moving = {value for value in wind_parts if value != "stationary"}
    wind_conflict = len(wind_moving) > 1
    if wind_conflict:
        wind_type = "uncertain"
    elif wind_moving:
        wind_type = next(iter(wind_moving))
    elif wind_parts:
        wind_type = "stationary"
    else:
        wind_type = None

    phase_type = (
        _type_from_speed(tendency_motion)
        if np.isfinite(tendency_motion) else None
    )
    family_votes = {
        "geometry": geo_type,
        "phase": phase_type,
        "wind": wind_type,
    }
    # Three independent estimates of the same quantity -- the speed of the
    # boundary toward the warm air -- in km/h.  The decision is their MEDIAN:
    # with three estimates it is the value two of them bracket, so one
    # family that is wrong (a jittering line, a wind that blows along the
    # front) cannot decide the type, and cannot veto it either.  The former
    # rule asked for unanimity and answered "uncertain" at the first
    # disagreement, which left real fronts without a type.
    wind_values = [
        value for value in (ofa_motion, airmass_motion) if np.isfinite(value)
    ]
    estimates = {
        "geometry": geo_motion if geo_speeds else np.nan,
        "phase": tendency_motion,
        "wind": float(np.mean(wind_values)) if wind_values else np.nan,
    }
    available = [value for value in estimates.values() if np.isfinite(value)]
    if not available:
        front_type, certainty, consensus_speed = "uncertain", 0.0, np.nan
    else:
        consensus_speed = float(np.median(available))
        front_type = _type_from_speed(consensus_speed)
        types = [_type_from_speed(value) for value in available]
        agree = sum(value == front_type for value in types)
        opposite = {"cold": "warm", "warm": "cold"}.get(front_type)
        against = sum(value == opposite for value in types)
        moving_types = {value for value in types if value != "stationary"}
        if len(available) == 2 and len(moving_types) == 2:
            # Two estimates only, and they say opposite things: there is no
            # third to bracket a median, and their mean would call a clearly
            # moving boundary "stationary".  This is the one honest
            # "uncertain".
            front_type, certainty = "uncertain", 0.10
        elif len(available) == 1:
            certainty = 0.45
        elif agree == len(available):
            certainty = 0.84 if len(available) >= 3 else 0.74
        elif agree >= 2:
            certainty = 0.56 if against else 0.72
        else:
            # every family reads something different: the median is still
            # the best estimate, but it is said to be weak
            certainty = 0.36
        # A speed sitting on the cold/warm threshold is a weaker statement
        # than one well clear of it.
        margin = abs(abs(consensus_speed) - COLD_WARM_THRESHOLD_KMH)
        certainty *= 0.80 + 0.20 * float(np.clip(margin / 4.0, 0.0, 1.0))

    # An unstable wind sign over the track lowers the confidence; it does
    # not erase the type.
    hourly_motion_types = []
    for h in hours:
        ofa_value = track.lines[h].get("ofaSpeedMps", np.nan)
        air_value = track.lines[h].get("airmassMotionKmh", np.nan)
        if np.isfinite(ofa_value):
            hourly_motion_types.append(_type_from_speed(-float(ofa_value) * 3.6))
        if np.isfinite(air_value):
            hourly_motion_types.append(_type_from_speed(float(air_value)))
    if hourly_motion_types and front_type != "uncertain":
        contradiction = float(np.mean([
            value not in (front_type, "stationary")
            for value in hourly_motion_types
        ])) if front_type != "stationary" else 0.0
        certainty *= 1.0 - 0.35 * contradiction

    motion_mad = _finite_median(np.abs(np.asarray(geo_speeds) - geo_motion), 0.0)
    return {
        "frontType": front_type,
        "geoMotionKmh": round(geo_motion, 1),
        "motionBearingDeg": (
            None if not np.isfinite(motion_bearing)
            else round(float(motion_bearing), 1)
        ),
        "ofaSpeedKmh": None if not np.isfinite(ofa_motion) else round(ofa_motion, 1),
        "tendencyMotionKmh": None if not np.isfinite(tendency_motion) else round(tendency_motion, 1),
        "airmassMotionKmh": None if not np.isfinite(airmass_motion) else round(airmass_motion, 1),
        "motionVotes": family_votes,
        "consensusMotionKmh": (
            None if not np.isfinite(consensus_speed)
            else round(consensus_speed, 1)
        ),
        "windMotionConflict": bool(wind_conflict),
        "motionMadKmh": round(float(motion_mad), 1),
        "classificationCertainty": round(float(certainty), 2),
    }


_TYPE_STATES = ("cold", "warm", "stationary", "uncertain")


def _transition_prob(previous: str, current: str, gap_hours: int) -> float:
    """Physical plausibility of a per-hour type change.

    A cold front cannot become a warm front from one hour to the next: that
    transition is near-forbidden. Slowing to stationary (or the reverse) is
    ordinary. Over a longer gap every transition relaxes toward uniform.
    """
    if previous == current:
        base = {"cold": 0.88, "warm": 0.88, "stationary": 0.82}.get(current, 0.55)
    elif {previous, current} == {"cold", "warm"}:
        base = 0.012  # a warm front does not become a cold front in 1 h
    elif "uncertain" in (previous, current):
        base = 0.12
    else:  # moving <-> stationary: a front slowing down or accelerating
        base = 0.14
    if gap_hours > 1:
        # relax toward uniform (0.25) as the identity gap widens
        weight = min(1.0, (gap_hours - 1) / 3.0)
        base = (1.0 - weight) * base + weight * 0.25
    return base


def _emission_prob(state: str, assigned: str, certainty: float) -> float:
    """How well an hour's own evidence supports each type."""
    if state == assigned:
        return 0.35 + 0.65 * float(np.clip(certainty, 0.0, 1.0))
    if state == "uncertain" or assigned == "uncertain":
        return 0.30
    if {state, assigned} == {"cold", "warm"}:
        return 0.04  # the hour's evidence argues against the opposite type
    return 0.18


def _viterbi_smooth_types(local: dict[int, dict]) -> dict[int, dict]:
    """Most physically-consistent type sequence over a track (Viterbi/HMM).

    Removes short, unphysical flips (a slowing front briefly read as its
    opposite) by finding the maximum-likelihood path through the type states
    under transition penalties that forbid cold<->warm swaps between hours.
    Hours whose smoothed type differs from their own reading keep a reduced
    certainty and a ``typeSmoothed`` flag, so the change stays transparent.
    """
    hours = sorted(local)
    if len(hours) < 3:
        return local
    log = lambda p: float(np.log(max(p, 1.0e-6)))
    scores = {}
    back = {}
    first = hours[0]
    a0 = local[first].get("frontType", "uncertain")
    c0 = local[first].get("classificationCertainty", 0.0)
    for s in _TYPE_STATES:
        scores[s] = log(_emission_prob(s, a0, c0))
        back[s] = [s]
    for index in range(1, len(hours)):
        hour = hours[index]
        gap = hour - hours[index - 1]
        assigned = local[hour].get("frontType", "uncertain")
        certainty = local[hour].get("classificationCertainty", 0.0)
        new_scores, new_back = {}, {}
        for s in _TYPE_STATES:
            emission = log(_emission_prob(s, assigned, certainty))
            best_prev, best_val = None, -np.inf
            for sp in _TYPE_STATES:
                val = scores[sp] + log(_transition_prob(sp, s, gap))
                if val > best_val:
                    best_val, best_prev = val, sp
            new_scores[s] = emission + best_val
            new_back[s] = back[best_prev] + [s]
        scores, back = new_scores, new_back
    best_state = max(_TYPE_STATES, key=lambda s: scores[s])
    path = back[best_state]

    smoothed: dict[int, dict] = {}
    for hour, state in zip(hours, path):
        entry = dict(local[hour])
        if entry.get("frontType") != state:
            entry["typeSmoothed"] = True
            entry["rawFrontType"] = entry.get("frontType")
            entry["classificationCertainty"] = round(
                float(entry.get("classificationCertainty", 0.0)) * 0.85, 2
            )
            entry["frontType"] = state
        smoothed[hour] = entry
    return smoothed


def classify_track_locally(
    track: Track, window_hours: int, wind_sampler=None
) -> dict[int, dict]:
    """Classify the same identity in a moving temporal window.

    A front may slow down or reverse without ceasing to be the same air-mass
    boundary. One label for a 20-hour track would therefore be physically
    misleading. Endpoints use the nearest three detections when available. A
    final Viterbi pass enforces temporal consistency so the published type
    cannot flip cold->warm->stationary from hour to hour.
    """
    radius = max(2, int(window_hours))
    local: dict[int, dict] = {}
    for center in track.hours:
        selected = [h for h in track.hours if abs(h - center) <= radius]
        if len(selected) < 3:
            selected = sorted(
                sorted(track.hours, key=lambda h: (abs(h - center), h))[:3]
            )
        if len(selected) < 2:
            local[center] = {
                "frontType": "uncertain",
                "classificationCertainty": 0.0,
            }
            continue
        subset = Track(track.id, selected[0], track.lines[selected[0]])
        for hour in selected[1:]:
            subset.hours.append(hour)
            subset.lines[hour] = track.lines[hour]
            local[center] = classify_track(subset, window_hours, wind_sampler)
    return _viterbi_smooth_types(local)


# --------------------------------------------------------------------------
# Per-segment (spatial) classification along a single line
# --------------------------------------------------------------------------
def _point_motion_kmh(track: Track, hour: int, count: int = 40) -> np.ndarray | None:
    """Signed motion (km/h) of each point of the line at ``hour``.

    Uses the geometric displacement of the line toward the warm air between
    ``hour`` and its temporal neighbour, measured **per point** (not a
    median). Positive = toward warm (cold-front character). No wind needed.
    """
    hours = track.hours
    if len(hours) < 2:
        return None
    index = hours.index(hour)
    if index + 1 < len(hours):
        h_from, h_to = hour, hours[index + 1]
    else:
        h_from, h_to = hours[index - 1], hour
    line_from = np.asarray(track.lines[h_from]["coordinates"], dtype=float)
    line_to = np.asarray(track.lines[h_to]["coordinates"], dtype=float)
    warm = np.asarray(track.lines[hour]["warmNormal"], dtype=float)
    mean_lat = math_mean_lat(line_from, line_to)
    a = _project_km(_resample(line_from, count), mean_lat)
    b = _project_km(_resample(line_to, count), mean_lat)
    normal = _resample_vectors(warm, count)
    scale_lon = EARTH_KM_PER_DEG * np.cos(mean_lat)
    normal_km = np.column_stack((normal[:, 0] * scale_lon,
                                 normal[:, 1] * EARTH_KM_PER_DEG))
    normal_km /= np.maximum(np.hypot(normal_km[:, 0], normal_km[:, 1])[:, None], 1.0e-9)
    displacement = np.empty(count)
    for i, point in enumerate(a):
        j = int(np.argmin(np.hypot(b[:, 0] - point[0], b[:, 1] - point[1])))
        displacement[i] = float(np.dot(b[j] - point, normal_km[i]))
    return displacement / max(abs(h_to - h_from), 1.0e-6)


def _mode_filter(labels: list[str], radius: int = 2) -> list[str]:
    out = list(labels)
    n = len(labels)
    for i in range(n):
        window = labels[max(0, i - radius):min(n, i + radius + 1)]
        out[i] = max(set(window), key=window.count)
    return out


def _merge_short_runs(labels: list[str], min_run: int) -> list[list]:
    """Run-length encode and absorb runs shorter than ``min_run`` into the
    longer neighbour, so a single line is not chopped into tiny segments and a
    stray cold point inside a warm stretch cannot survive."""
    def runs_of(seq):
        segments, i = [], 0
        while i < len(seq):
            j = i
            while j < len(seq) and seq[j] == seq[i]:
                j += 1
            segments.append([i, j, seq[i]])
            i = j
        return segments

    segments = runs_of(labels)
    changed = True
    while changed and len(segments) > 1:
        changed = False
        for k, seg in enumerate(segments):
            if seg[1] - seg[0] >= min_run:
                continue
            left = segments[k - 1] if k > 0 else None
            right = segments[k + 1] if k + 1 < len(segments) else None
            if left and right:
                target = left if (left[1] - left[0]) >= (right[1] - right[0]) else right
            else:
                target = left or right
            for idx in range(seg[0], seg[1]):
                labels[idx] = target[2]
            changed = True
            break
        if changed:
            segments = runs_of(labels)
    return segments


SEGMENT_WINDOW_HOURS = 3
SEGMENT_MIN_KM = 250.0
OPPOSITE_SEGMENT_KMH = 8.0


def _along_line(values, coordinates: np.ndarray, count: int) -> np.ndarray | None:
    """Resample a per-vertex quantity to ``count`` points equally spaced
    along the line (the same points ``_resample`` returns)."""
    if values is None:
        return None
    values = np.asarray(values, dtype=float)
    coordinates = np.asarray(coordinates, dtype=float)
    if values.ndim != 1 or len(values) != len(coordinates) or len(values) < 2:
        return None
    steps = np.hypot(*np.diff(coordinates, axis=0).T)
    arc = np.concatenate(([0.0], np.cumsum(steps)))
    finite = np.isfinite(values)
    if arc[-1] <= 0.0 or int(np.count_nonzero(finite)) < 2:
        return None
    targets = np.linspace(0.0, arc[-1], count)
    out = np.interp(targets, arc[finite], values[finite])
    # do not invent values far from any finite vertex
    gap = np.abs(targets[:, None] - arc[finite][None, :]).min(axis=1)
    out[gap > 0.08 * arc[-1] + 1.0e-9] = np.nan
    return out


def _point_window_motion_kmh(track: Track, hour: int, count: int) -> np.ndarray | None:
    """Per-point speed toward the warm air from the track's own displacement.

    Each point of the line at ``hour`` is located on the same track up to
    ``SEGMENT_WINDOW_HOURS`` earlier and later; the net displacement between
    those two detections, along the local warm-ward normal, is its speed.
    Six hours of travel dwarf the hourly jitter of the line that makes a
    single-hour displacement useless point by point.
    """
    inside = [h for h in track.hours if abs(h - hour) <= SEGMENT_WINDOW_HOURS]
    if len(inside) < 2 or inside[-1] == inside[0]:
        return None
    h_from, h_to = inside[0], inside[-1]
    line = np.asarray(track.lines[hour]["coordinates"], dtype=float)
    line_from = np.asarray(track.lines[h_from]["coordinates"], dtype=float)
    line_to = np.asarray(track.lines[h_to]["coordinates"], dtype=float)
    mean_lat = math_mean_lat(line, line_from, line_to)
    here = _project_km(_resample(line, count), mean_lat)
    before = _dense_km(line_from, mean_lat)
    after = _dense_km(line_to, mean_lat)
    normal = _resample_vectors(
        np.asarray(track.lines[hour]["warmNormal"], dtype=float), count
    )
    scale_lon = EARTH_KM_PER_DEG * np.cos(mean_lat)
    normal_km = np.column_stack((normal[:, 0] * scale_lon,
                                 normal[:, 1] * EARTH_KM_PER_DEG))
    normal_km /= np.maximum(np.hypot(*normal_km.T)[:, None], 1.0e-9)
    gap_before = np.hypot(here[:, None, 0] - before[None, :, 0],
                          here[:, None, 1] - before[None, :, 1])
    gap_after = np.hypot(here[:, None, 0] - after[None, :, 0],
                         here[:, None, 1] - after[None, :, 1])
    i_before = np.argmin(gap_before, axis=1)
    i_after = np.argmin(gap_after, axis=1)
    rows = np.arange(count)
    reach_before = 60.0 + 60.0 * abs(hour - h_from)
    reach_after = 60.0 + 60.0 * abs(h_to - hour)
    valid = (
        (gap_before[rows, i_before] <= reach_before)
        & (gap_after[rows, i_after] <= reach_after)
    )
    travel = np.sum((after[i_after] - before[i_before]) * normal_km, axis=1)
    speed = travel / float(h_to - h_from)
    speed[~valid] = np.nan
    return speed


def _point_consensus_kmh(
    track: Track, hour: int, count: int
) -> tuple[np.ndarray | None, int]:
    """Per-point median of the geometric, phase and wind speed estimates.

    Also returns how many independent families contributed.
    """
    candidate = track.lines[hour]
    coordinates = candidate["coordinates"]
    families = []
    geometric = _point_window_motion_kmh(track, hour, count)
    if geometric is not None:
        families.append(geometric)
    phase = _along_line(candidate.get("pointTendencyKmh"), coordinates, count)
    if phase is not None:
        families.append(phase)
    wind_parts = [
        part for part in (
            _along_line(candidate.get("pointAirmassKmh"), coordinates, count),
            _along_line(candidate.get("pointOfaKmh"), coordinates, count),
        ) if part is not None
    ]
    if wind_parts:
        with np.errstate(invalid="ignore"):
            families.append(np.nanmean(np.stack(wind_parts), axis=0))
    if not families:
        return None, 0
    stack = np.stack(families)
    finite = np.isfinite(stack)
    if not np.any(finite):
        return None, 0
    speed = np.full(stack.shape[1], np.nan)
    some = np.any(finite, axis=0)
    speed[some] = np.nanmedian(stack[:, some], axis=0)
    # running mean along the line (about an eighth of its length): the type
    # of a stretch, not of a point
    radius = max(1, int(round(count * 0.06)))
    smoothed = np.full(count, np.nan)
    for index in range(count):
        window = speed[max(0, index - radius):index + radius + 1]
        if np.any(np.isfinite(window)):
            smoothed[index] = float(np.nanmean(window))
    return smoothed, len(families)


def segment_types_for_track(
    track: Track, local: dict[int, dict],
    *, count: int = 40, min_segment_fraction: float = 0.12,
) -> dict[int, list[dict]]:
    """Classify each hour's line into contiguous cold/warm/stationary segments.

    One air-mass boundary is routinely a warm front ahead of a wave and a
    cold front behind it, or cold on one end and quasi-stationary on the
    other, at the SAME hour.  A single label for 2500 km of line is then
    wrong for most of it.  This returns, per hour, segments as normalised
    arc-length ranges [start, end] with a type and a certainty, so the
    geometry stays one continuous line while its character varies along it.

    The speed of each point toward the warm air is the median of three
    estimates (displacement of the track over +-3 h, theta-w phase speed,
    wind normal to the line), smoothed along the line.  Four guards keep a
    noisy point from becoming a symbol: a 3-hour majority vote on each
    point's label, a minimum segment length (250 km and an eighth of the
    line), a higher speed (8 km/h) for a stretch whose type is OPPOSITE to
    the line's own -- a warm stretch on a cold front must earn it -- and
    the requirement of a second, physical family: the displacement of the
    line alone, whose two ends change length every hour, may slow a stretch
    to stationary but never turns it into the opposite front.
    Where no per-point estimate exists the hour's whole-line type is used.
    """
    dominant_types = [
        value.get("frontType") for value in local.values()
        if value.get("frontType") in ("cold", "warm", "stationary")
    ]
    dominant_type = (
        max(set(dominant_types), key=dominant_types.count)
        if dominant_types else "uncertain"
    )
    speeds: dict[int, np.ndarray | None] = {}
    confirmed: dict[int, bool] = {}
    labels: dict[int, list[str] | None] = {}
    points: dict[int, np.ndarray] = {}
    anchors: dict[int, str] = {}
    for hour in track.hours:
        anchor = local.get(hour, {}).get("frontType", "uncertain")
        if anchor not in ("cold", "warm", "stationary"):
            anchor = dominant_type
        anchors[hour] = anchor
        line = np.asarray(track.lines[hour]["coordinates"], dtype=float)
        points[hour] = _resample(line, count)
        speed, families = _point_consensus_kmh(track, hour, count)
        speeds[hour] = speed
        confirmed[hour] = families >= 2
        if speed is None:
            labels[hour] = None
            continue
        raw = [
            _type_from_speed(float(value)) if np.isfinite(value) else anchor
            for value in speed
        ]
        if not confirmed[hour]:
            if anchor == "stationary":
                raw = ["stationary"] * count
            else:
                opposite = "warm" if anchor == "cold" else "cold"
                raw = ["stationary" if label == opposite else label for label in raw]
        labels[hour] = raw

    def neighbour_labels(hour: int, other: int) -> list[str] | None:
        if labels.get(other) is None or abs(other - hour) > 2:
            return None
        mean_lat = math_mean_lat(points[hour], points[other])
        here = _project_km(points[hour], mean_lat)
        there = _project_km(points[other], mean_lat)
        gaps = np.hypot(here[:, None, 0] - there[None, :, 0],
                        here[:, None, 1] - there[None, :, 1])
        nearest = np.argmin(gaps, axis=1)
        reach = 120.0 * abs(other - hour)
        return [
            labels[other][j] if gaps[i, j] <= reach else None
            for i, j in enumerate(nearest)
        ]

    result: dict[int, list[dict]] = {}
    ordered = list(track.hours)
    for position, hour in enumerate(ordered):
        anchor = anchors[hour]
        raw = labels[hour]
        if raw is None:
            result[hour] = [{"start": 0.0, "end": 1.0,
                             "type": anchor, "certainty": 0.3}]
            continue
        voted = list(raw)
        around = []
        if position > 0:
            around.append(neighbour_labels(hour, ordered[position - 1]))
        if position + 1 < len(ordered):
            around.append(neighbour_labels(hour, ordered[position + 1]))
        around = [item for item in around if item is not None]
        if around:
            for index in range(count):
                ballot = [raw[index]] + [
                    item[index] for item in around if item[index] is not None
                ]
                if len(ballot) >= 3:
                    voted[index] = max(set(ballot), key=ballot.count)
        length_km = max(_length_km(track.lines[hour]["coordinates"]), 1.0)
        min_run = max(2, int(np.ceil(count * max(
            min_segment_fraction, SEGMENT_MIN_KM / length_km
        ))))
        smoothed = _mode_filter(voted, radius=1)
        segments = _merge_short_runs(smoothed, min(min_run, count))
        speed = speeds[hour]
        if anchor in ("cold", "warm"):
            opposite = "warm" if anchor == "cold" else "cold"
            changed = False
            for start, stop, label in segments:
                if label != opposite:
                    continue
                stretch = speed[start:stop]
                mean_speed = (
                    float(np.nanmean(np.abs(stretch)))
                    if np.any(np.isfinite(stretch)) else 0.0
                )
                if mean_speed < OPPOSITE_SEGMENT_KMH:
                    for index in range(start, stop):
                        smoothed[index] = "stationary"
                    changed = True
            if changed:
                segments = _merge_short_runs(smoothed, min(min_run, count))
        pieces = []
        for start, stop, label in segments:
            agree = float(np.mean([raw[i] == label for i in range(start, stop)]))
            stretch = speed[start:stop]
            pieces.append({
                "start": round(start / count, 3),
                "end": round(stop / count, 3),
                "type": label,
                "certainty": round(agree, 2),
                "motionKmh": (
                    round(float(np.nanmean(stretch)), 1)
                    if np.any(np.isfinite(stretch)) else None
                ),
            })
        result[hour] = pieces
    return result


# --------------------------------------------------------------------------
# Per-hour quality (NOT a probability)
# --------------------------------------------------------------------------
def _hourly_tracking_confidence(track: Track) -> dict[int, float]:
    """Reliability of the temporal link at each hour, in [0, 1].

    A detection tightly continued by its neighbours (small line-to-line
    displacement per hour, no gap) is a reliable link; an isolated hour, a
    bridged gap or a weak-phase recovery is progressively less so. This is
    about the LINK, deliberately independent from how strong the physics of
    the hour is (that is detectionQuality).
    """
    status_factor = {
        "strong": 1.0, "continuation": 0.92, "weak-continuation": 0.72,
    }
    hours = sorted(track.hours)
    confidence: dict[int, float] = {}
    for index, hour in enumerate(hours):
        neighbours = []
        if index > 0:
            neighbours.append(hours[index - 1])
        if index < len(hours) - 1:
            neighbours.append(hours[index + 1])
        if not neighbours:
            continuity = 0.30
        else:
            scores = []
            for other in neighbours:
                gap = abs(hour - other)
                speed = _symmetric_distance_km(
                    track.lines[hour]["coordinates"],
                    track.lines[other]["coordinates"],
                ) / max(gap, 1)
                link = float(np.clip(1.0 - speed / 90.0, 0.05, 1.0))
                scores.append(link * (1.0 if gap == 1 else 0.85))
            continuity = float(np.max(scores))
        factor = status_factor.get(
            track.lines[hour].get("gateStatus", "strong"), 0.85
        )
        confidence[hour] = round(min(1.0, continuity * factor), 3)
    return confidence


def hourly_quality(track: Track, local_classifications: dict,
                   quality: dict) -> dict:
    """Per-hour quality view of a track: what THIS hour supports.

    The published track keeps its track-level score for the publication
    decision; each hour additionally gets an instantaneous score so a front
    that weakens at one lead time shows that weakening instead of repeating
    the track median. Diagnostic blend (not a probability):
    58% physical evidence of the hour, 22% temporal-link reliability,
    10% structural support, 10% classification confidence.
    """
    tracking_confidence = _hourly_tracking_confidence(track)
    fallback_structural = float(
        (quality.get("qualityComponents") or {}).get("structuralSupport", 0.5)
    )
    observations: dict[int, dict] = {}
    hourly: dict[int, float] = {}
    hourly_uncertainty: dict[int, float] = {}
    detection: dict[int, float] = {}
    classification_confidence: dict[int, float] = {}
    for hour in track.hours:
        line = track.lines[hour]
        evidence = float(line.get("candidateEvidence") or 0.0)
        components = line.get("evidenceComponents") or {}
        structural = float(components.get("structural", np.nan))
        if not np.isfinite(structural):
            structural = fallback_structural
        thermal = float(components.get("thermal", np.nan))
        certainty = float(
            (local_classifications.get(hour) or {})
            .get("classificationCertainty", 0.0) or 0.0
        )
        score = float(np.clip(
            0.58 * evidence
            + 0.22 * tracking_confidence.get(hour, 0.30)
            + 0.10 * structural
            + 0.10 * certainty,
            0.0, 1.0,
        ))
        # Same existence-core penalty used by the track uncertainty: a weak
        # thermal core or an incoherent structure keeps THIS hour uncertain
        # even when the temporal link is excellent.
        core = min(thermal if np.isfinite(thermal) else structural, structural)
        penalty = max(0.0, 0.50 - core) * 0.35
        detection[hour] = round(evidence, 3)
        classification_confidence[hour] = round(certainty, 2)
        hourly[hour] = round(score, 2)
        hourly_uncertainty[hour] = round(
            float(np.clip(1.0 - score + penalty, 0.0, 1.0)), 2
        )
        observations[hour] = {
            "gateStatus": line.get("gateStatus", "strong"),
            "diagnosis": line.get("diagnosis", "synoptic-front"),
            "fusionDecision": line.get("fusionDecision", "physics-only"),
            "mlAssisted": bool(line.get("mlAssisted", False)),
            "candidateEvidence": round(evidence, 3),
            "thermalSupport": round(thermal, 2) if np.isfinite(thermal) else None,
            "structuralSupport": round(structural, 2),
            "diagnostics": {
                key: line.get(key) for key in DIAGNOSTIC_KEYS if key in line
            },
        }
    return {
        "observations": observations,
        "hourlyQuality": hourly,
        "hourlyUncertainty": hourly_uncertainty,
        "detectionQuality": detection,
        "trackingConfidence": tracking_confidence,
        "classificationConfidence": classification_confidence,
    }


# --------------------------------------------------------------------------
# Quality score (NOT a probability)
# --------------------------------------------------------------------------
def _quality_score(track: Track, classification: dict, window_hours: int) -> dict:
    hours = track.hours
    candidate_evidence = _finite_median([
        track.lines[h].get("candidateEvidence", np.nan) for h in hours
    ], 0.0)
    component_names = ("thermal", "dynamic", "pressure", "vertical", "activity", "structural")
    physical_components = {
        name: _finite_median([
            track.lines[h].get("evidenceComponents", {}).get(name, np.nan)
            for h in hours
        ], 0.0)
        for name in component_names
    }
    span = hours[-1] - hours[0]
    coverage = float(np.clip(len(hours) / max(span + 1, 1), 0.0, 1.0))
    lifetime = float(np.clip((span - 3.0) / 6.0, 0.0, 1.0))
    strong_fraction = float(np.mean([
        track.lines[h].get("gateStatus", "strong") == "strong"
        for h in hours
    ]))
    motion_consistency = float(np.clip(
        1.0 - classification.get("motionMadKmh", 0.0) / 25.0, 0.0, 1.0
    ))
    temporal = (
        0.38 * coverage + 0.20 * lifetime
        + 0.22 * motion_consistency + 0.20 * strong_fraction
    )
    certainty = float(classification["classificationCertainty"])
    structural = physical_components["structural"]
    components = {
        "physicalEvidence": round(candidate_evidence, 2),
        "thermalSupport": round(physical_components["thermal"], 2),
        "dynamicSupport": round(physical_components["dynamic"], 2),
        "pressureSupport": round(physical_components["pressure"], 2),
        "verticalSupport": round(physical_components["vertical"], 2),
        "temporalSupport": round(temporal, 2),
        "structuralSupport": round(structural, 2),
        "classificationCertainty": round(certainty, 2),
        "strongDetectionFraction": round(strong_fraction, 2),
    }
    overall = float(np.clip(
        0.55 * candidate_evidence + 0.25 * temporal
        + 0.12 * structural + 0.08 * certainty,
        0.0, 1.0,
    ))
    # Diagnostic uncertainty also accounts for a weak *existence* dimension:
    # a high temporal score cannot hide a poor thermal contrast or an
    # incoherent structure. Dynamics are deliberately excluded here - a
    # genuine quasi-stationary front legitimately has weak cross-front wind
    # and convergence, and must not be labelled "uncertain" (and dropped)
    # for that. Weak dynamics already lower qualityScore through the dynamic
    # evidence component; they must not additionally erase a thermally and
    # structurally solid boundary.
    core_penalty = max(
        0.0,
        0.50 - min(
            physical_components["thermal"],
            structural,
        ),
    ) * 0.35
    uncertainty = float(np.clip(1.0 - overall + core_penalty, 0.0, 1.0))
    uncertainty_class = "low" if uncertainty <= 0.36 else (
        "moderate" if uncertainty <= 0.52 else "high"
    )
    return {
        "qualityScore": round(overall, 2),
        "uncertaintyIndex": round(uncertainty, 2),
        "uncertaintyClass": uncertainty_class,
        "qualityComponents": components,
    }


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
PERSISTENT_ANCHOR_HOURS = 6
PERSISTENT_ANCHOR_LENGTH_KM = 500.0


def _persistent_anchor(track: "Track") -> bool:
    """A long, long-lived, thermally sharp boundary anchors itself.

    The "strong" grade asks for wind shift, pressure trough and low-level
    agreement all at once.  A slow warm or quasi-stationary front lying along
    the flow has little of the first two for its whole life, yet it separates
    two air masses by several kelvin over a thousand kilometres for a day.
    Persistence, length and the air-mass contrast itself are the evidence a
    forecaster uses for such a front; noise does not hold all three for six
    hours.
    """
    hours = track.hours
    if len(hours) < PERSISTENT_ANCHOR_HOURS:
        return False
    def median(key):
        return _finite_median([track.lines[h].get(key, np.nan) for h in hours])
    return bool(
        median("lengthKm") >= PERSISTENT_ANCHOR_LENGTH_KM
        and median("deltaThetaW") >= 1.55
        and median("deltaTemperature") >= 0.80
        and median("dryThermalGradient") >= 0.95
        and median("thermalAlignment") >= 0.50
    )


def track_fronts(
    hourly_candidates: dict[int, list],
    *,
    window_hours: int = 3,
    gate_km: float = 250.0,
    min_lifetime_hours: int = 6,
    min_detections: int = 2,
    min_coverage: float = 0.5,
    wind_sampler=None,
    require_physical_support: bool = False,
    min_dry_gradient: float = 1.2,
    min_wind_shift_ms: float = 1.5,
    min_convergence_ms: float = 0.15,
    max_terrain_fraction: float = 0.25,
    min_strong_detections: int = 1,
    weak_candidates: dict[int, list] | None = None,
):
    """Link hourly candidates into classified, quality-scored tracks.

    ``hourly_candidates`` maps forecast hour -> list of candidate dicts
    (from front_detection).  ``wind_sampler(hour, points_lonlat)`` -> (u, v)
    in m/s enables the advection and OFA cross-checks (optional).
    Returns a list of accepted track summaries.
    """
    hours = sorted(hourly_candidates)
    tracks: list[Track] = []
    active: list[Track] = []
    next_id = 0
    # A front absent longer than the declared tracking window is a new
    # identity, not the continuation of the old one. This prevents an
    # hourly line from disappearing for 4-6 hours and reappearing with the
    # same track id and an inflated lifetime.
    max_gap = window_hours

    for hour in hours:
        candidates = list(hourly_candidates[hour])
        active = [t for t in active if hour - t.last_hour() <= max_gap]
        matches, unmatched = _global_assign(active, candidates, hour, gate_km)
        for track_index, cand_index in matches.items():
            track = active[track_index]
            track.hours.append(hour)
            track.lines[hour] = candidates[cand_index]
        for cand_index in unmatched:
            # Every unmatched candidate reaching this point already passed the
            # hard, non-compensating physical gates (continuationPass): it is a
            # genuine synoptic-front segment, not mesoscale noise. It may
            # therefore start a track even when it is only "continuation" grade.
            # A real but rarely-"strong" synoptic front (a slow, quasi-
            # stationary boundary is the textbook case) would otherwise never be
            # born and would be lost entirely. Ephemeral or spurious segments
            # are still removed downstream by the lifetime, detection and
            # coverage thresholds.
            track = Track(next_id, hour, candidates[cand_index])
            next_id += 1
            tracks.append(track)
            active.append(track)

    # Re-link tracks that the online (causal) assignment split across a brief
    # detection dropout. Done here, with the whole sequence in hand, so a
    # single physical boundary becomes one continuous track instead of two
    # with a one-hour hole between them (the "front vanishes for an hour"
    # artefact). Max gap mirrors the online tracking window.
    tracks = _stitch_tracks(tracks, max_gap=max(2, window_hours))

    available = sorted(hourly_candidates)
    results = []
    weak_used: set = set()
    for track in tracks:
        span = track.hours[-1] - track.hours[0]
        if len(track.hours) < max(2, int(min_detections)) or span < min_lifetime_hours:
            continue
        # A single "strong"-grade hour anchors the track's identity, but a
        # coherent front that stays at "continuation" grade for many hours
        # (a slow synoptic boundary passing every hard physical gate) must NOT
        # be discarded for lacking repeated "strong" hours. Track quality and
        # coverage below, plus the qualityScore, weigh a continuation-heavy
        # track down without erasing it. The former "no long marginal run"
        # rule erased exactly these real long-lived boundaries and is gone.
        strong_hours = [
            h for h in track.hours
            if track.lines[h].get("gateStatus", "strong") == "strong"
        ]
        if (
            len(strong_hours) < max(1, int(min_strong_detections))
            and not _persistent_anchor(track)
        ):
            continue
        expected = [h for h in available if track.hours[0] <= h <= track.hours[-1]]
        if len(track.hours) / max(len(expected), 1) < min_coverage:
            continue
        diagnostics = {
            key: _finite_median([
                track.lines[h].get(key, np.nan) for h in track.hours
            ])
            for key in DIAGNOSTIC_KEYS
        }
        if require_physical_support:
            dry_gradient = diagnostics["dryThermalGradient"]
            wind_shift_value = diagnostics["windShiftMs"]
            convergence_value = diagnostics["convergenceMs"]
            terrain_fraction = diagnostics["terrainFraction"]
            if not np.isfinite(dry_gradient) or dry_gradient < min_dry_gradient:
                continue
            if (
                (not np.isfinite(wind_shift_value) or wind_shift_value < min_wind_shift_ms)
                and (
                    not np.isfinite(convergence_value)
                    or convergence_value < min_convergence_ms
                )
            ):
                continue
            if np.isfinite(terrain_fraction) and terrain_fraction > max_terrain_fraction:
                continue
        classification = classify_track(track, window_hours, wind_sampler)
        local_classifications = classify_track_locally(
            track, window_hours, wind_sampler
        )
        local_certainties = [
            value.get("classificationCertainty", 0.0)
            for value in local_classifications.values()
            if value.get("frontType") != "uncertain"
        ]
        quality_classification = dict(classification)
        if local_certainties:
            quality_classification["classificationCertainty"] = float(
                np.median(local_certainties)
            )
        quality = _quality_score(track, quality_classification, window_hours)
        # Weak-phase recovery AFTER classification and quality: identity and
        # confidence come from the strong core alone, so recovered hours can
        # only extend where the boundary is drawn, never inflate its score.
        core_hours = list(track.hours)
        recovered_hours: list[int] = []
        if weak_candidates:
            recovered_hours = _extend_track_weak(track, weak_candidates, weak_used)
            if recovered_hours:
                local_classifications = classify_track_locally(
                    track, window_hours, wind_sampler
                )
        diagnoses = [
            str(track.lines[h].get("diagnosis", "synoptic-front"))
            for h in track.hours
        ]
        dominant_diagnosis = max(set(diagnoses), key=diagnoses.count)
        segment_types = segment_types_for_track(track, local_classifications)
        per_hour = hourly_quality(track, local_classifications, quality)
        characters = {
            h: track.lines[h].get("frontalCharacter", "undetermined")
            for h in track.hours
        }
        named = [value for value in characters.values() if value not in (None, "undetermined")]
        dominant_character = max(set(named), key=named.count) if named else "undetermined"
        results.append({
            "id": track.id,
            "hours": list(track.hours),
            "frontalCharacter": dominant_character,
            "characters": characters,
            "coreHours": core_hours,
            "recoveredHours": recovered_hours,
            "lifetimeH": span,
            "lines": {h: track.lines[h]["coordinates"] for h in track.hours},
            "diagnostics": diagnostics,
            "diagnosis": dominant_diagnosis,
            "localClassifications": local_classifications,
            "segmentTypes": segment_types,
            **per_hour,
            **classification,
            **quality,
            # Explicit names for the two quality levels: the track-level
            # score (publication persistence) stays in "qualityScore" for
            # backward compatibility; the per-feature hourly score replaces
            # it only in the exported GeoJSON.
            "trackQualityScore": quality["qualityScore"],
            "trackUncertaintyIndex": quality["uncertaintyIndex"],
        })
    results.sort(key=lambda r: r["qualityScore"], reverse=True)
    return results
