from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
from statistics import median
from typing import Any

SENSOR_DISPLAY_LIMIT = 600
SENSOR_PLAYBACK_LIMIT = 6000
ALIGNMENT_DISPLAY_LIMIT = 400


def format_relative_time_ms(timestamp_ms: int | float) -> str:
    rounded = int(round(float(timestamp_ms)))
    sign = "-" if rounded < 0 else ""
    return f"T{sign}+{abs(rounded)} ms"


def format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def format_timestamp_ms(timestamp_ms: int | float, time_mode: str = "absolute") -> str:
    if time_mode == "relative_ms":
        return format_relative_time_ms(timestamp_ms)
    return format_timestamp(datetime.fromtimestamp(float(timestamp_ms) / 1000.0))


def downsample_points(points: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or len(points) <= limit:
        return [dict(point) for point in points]
    if limit == 1:
        return [dict(points[0])]

    last_index = len(points) - 1
    indices = sorted(
        {
            round(index * last_index / (limit - 1))
            for index in range(limit)
        }
    )
    return [dict(points[index]) for index in indices]


def build_edge_trajectory_summaries(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in points:
        trajectory_id = str(point.get("trajectory_id") or "").strip()
        if not trajectory_id:
            continue
        grouped[trajectory_id].append(point)

    def sort_key(value: str) -> tuple[int, Any]:
        return (0, int(value)) if str(value).isdigit() else (1, str(value))

    summaries: list[dict[str, Any]] = []
    for trajectory_id in sorted(grouped, key=sort_key):
        group = grouped[trajectory_id]
        group.sort(key=lambda item: item["timestamp_ms"])
        first = group[0]
        last = group[-1]
        summary = {
            "trajectory_id": trajectory_id,
            "sample_count": len(group),
            "start_time": first.get("time"),
            "end_time": last.get("time"),
        }
        if all(key in first for key in ("machine_x_mm", "machine_y_mm", "machine_z_mm")):
            summary["machine_start"] = {
                "x_mm": first["machine_x_mm"],
                "y_mm": first["machine_y_mm"],
                "z_mm": first["machine_z_mm"],
            }
        if all(key in last for key in ("machine_x_mm", "machine_y_mm", "machine_z_mm")):
            summary["machine_end"] = {
                "x_mm": last["machine_x_mm"],
                "y_mm": last["machine_y_mm"],
                "z_mm": last["machine_z_mm"],
            }
        summaries.append(summary)

    return summaries


def g_high_signature(value: Any) -> int | None:
    try:
        return int(round(float(value) * 100.0))
    except (TypeError, ValueError):
        return None


def nearest_thermal_index_by_tspan(thermal_tspans: list[float], target_tspan_s: float) -> int:
    if not thermal_tspans:
        return 0
    insert_at = bisect_right(thermal_tspans, target_tspan_s)
    if insert_at <= 0:
        return 0
    if insert_at >= len(thermal_tspans):
        return len(thermal_tspans) - 1
    before_index = insert_at - 1
    after_index = insert_at
    before_gap = abs(thermal_tspans[before_index] - target_tspan_s)
    after_gap = abs(thermal_tspans[after_index] - target_tspan_s)
    return before_index if before_gap <= after_gap else after_index


def select_alignment_probe_points(
    edge_points: list[dict[str, Any]],
    thermal_frequency: dict[int, int],
) -> list[dict[str, Any]]:
    if not edge_points:
        return []

    step = max(1, len(edge_points) // 240)
    probes: list[dict[str, Any]] = []
    for index in range(0, len(edge_points), step):
        point = edge_points[index]
        if point.get("sample_ms") in (None, "") or point.get("g_high") in (None, ""):
            continue
        signature = g_high_signature(point.get("g_high"))
        if signature is None:
            continue
        frequency = thermal_frequency.get(signature, 0)
        previous_value = edge_points[index - 1].get("g_high") if index > 0 else point.get("g_high")
        next_value = edge_points[index + 1].get("g_high") if index + 1 < len(edge_points) else point.get("g_high")
        try:
            local_delta = max(
                abs(float(point.get("g_high")) - float(previous_value)),
                abs(float(next_value) - float(point.get("g_high"))),
            )
        except (TypeError, ValueError):
            local_delta = 0.0
        if frequency <= 150 or local_delta >= 1.0:
            probes.append(point)

    if len(probes) >= 25:
        return probes
    return [
        point
        for point in edge_points[::step]
        if point.get("sample_ms") not in (None, "") and point.get("g_high") not in (None, "")
    ]


def evaluate_edge_thermal_offset(
    edge_points: list[dict[str, Any]],
    thermal_points: list[dict[str, Any]],
    thermal_tspans: list[float],
    offset_s: float,
) -> tuple[float, int]:
    if not edge_points or not thermal_points or not thermal_tspans:
        return float("inf"), 0

    total_error = 0.0
    compared = 0
    exact_matches = 0
    step = max(1, len(edge_points) // 480)
    for point in edge_points[::step]:
        try:
            sample_ms = float(point.get("sample_ms"))
            edge_g_high = float(point.get("g_high"))
        except (TypeError, ValueError):
            continue
        target_tspan_s = offset_s + sample_ms / 1000.0
        center_index = nearest_thermal_index_by_tspan(thermal_tspans, target_tspan_s)
        candidate_indices = range(max(0, center_index - 3), min(len(thermal_points), center_index + 4))
        best_point: dict[str, Any] | None = None
        best_score: tuple[float, float] | None = None
        for candidate_index in candidate_indices:
            candidate_point = thermal_points[candidate_index]
            try:
                candidate_g_high = float(candidate_point.get("g_high"))
                candidate_tspan_s = float(candidate_point.get("tspan_s"))
            except (TypeError, ValueError):
                continue
            score = (abs(candidate_g_high - edge_g_high), abs(candidate_tspan_s - target_tspan_s))
            if best_score is None or score < best_score:
                best_score = score
                best_point = candidate_point
        if best_point is None:
            continue
        error = abs(float(best_point["g_high"]) - edge_g_high)
        total_error += error
        compared += 1
        if error <= 0.05:
            exact_matches += 1

    if compared == 0:
        return float("inf"), 0
    return total_error / compared, exact_matches


def get_first_toolpath_anchor_point(
    toolpath_segments: list[dict[str, Any]],
    path_type: str | None = None,
) -> dict[str, Any] | None:
    for segment in toolpath_segments:
        if path_type and segment.get("path_type") != path_type:
            continue
        point = segment.get("start_point")
        if isinstance(point, dict) and all(key in point for key in ("x_mm", "y_mm", "z_mm")):
            return point
    return None


def get_first_toolpath_end_point(toolpath_segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    for segment in toolpath_segments:
        point = segment.get("end_point")
        if isinstance(point, dict) and all(key in point for key in ("x_mm", "y_mm", "z_mm")):
            return point
    return None


def get_edge_z_value(point: dict[str, Any]) -> float | None:
    for key in ("machine_z_mm", "work_z_mm", "z_mm", "machine_z", "z"):
        try:
            value = point.get(key)
        except AttributeError:
            value = None
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric == numeric:
            return numeric
    return None


def find_edge_point_near_timestamp(
    edge_points: list[dict[str, Any]],
    target_timestamp_ms: int | float | None,
    max_gap_ms: int | None = None,
) -> dict[str, Any] | None:
    if target_timestamp_ms is None:
        return None
    valid_points = [
        point
        for point in edge_points
        if isinstance(point, dict) and point.get("timestamp_ms") is not None
    ]
    if not valid_points:
        return None

    target_timestamp = int(target_timestamp_ms)
    nearest = min(
        valid_points,
        key=lambda item: abs(int(item.get("timestamp_ms") or 0) - target_timestamp),
    )
    if max_gap_ms is not None:
        nearest_gap = abs(int(nearest.get("timestamp_ms") or 0) - target_timestamp)
        if nearest_gap > int(max_gap_ms):
            return None
    return nearest


def median_value(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(float(value) for value in values)
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2.0


def percentile_value(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(float(value) for value in values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = max(0.0, min(1.0, ratio)) * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    blend = position - lower
    return sorted_values[lower] * (1.0 - blend) + sorted_values[upper] * blend


def detect_thermal_rise_feature(thermal_points: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(thermal_points) < 8:
        return None

    raw_values = [float(point["g_high"]) for point in thermal_points if point.get("g_high") is not None]
    if len(raw_values) < 8:
        return None

    half_window = 2
    smoothed_values: list[float] = []
    for index in range(len(raw_values)):
        start = max(0, index - half_window)
        end = min(len(raw_values), index + half_window + 1)
        smoothed_values.append(sum(raw_values[start:end]) / (end - start))

    baseline_count = min(max(24, len(smoothed_values) // 25), 240)
    baseline = median_value(smoothed_values[:baseline_count])
    peak_value = percentile_value(smoothed_values, 0.98)
    dynamic_range = max(peak_value - baseline, 0.0)
    if dynamic_range <= 0.0:
        return None

    positive_deltas = [
        smoothed_values[index] - smoothed_values[index - 1]
        for index in range(1, len(smoothed_values))
        if smoothed_values[index] > smoothed_values[index - 1]
    ]
    sustain_count = max(2, min(6, len(smoothed_values) // 400 or 2))

    def locate_rise(
        *,
        threshold_ratio: float,
        minimum_margin: float,
        jump_ratio: float,
    ) -> dict[str, Any] | None:
        threshold = baseline + max(dynamic_range * threshold_ratio, minimum_margin)
        jump_threshold = max(
            percentile_value(positive_deltas, 0.88) if positive_deltas else 0.0,
            dynamic_range * jump_ratio,
            minimum_margin * 0.03,
            1.2,
        )
        limit = max(1, len(smoothed_values) - sustain_count)
        for index in range(1, limit):
            current = smoothed_values[index]
            previous = smoothed_values[index - 1]
            rise_delta = current - previous
            if current < threshold or rise_delta < jump_threshold:
                continue

            future_window = smoothed_values[index : index + sustain_count]
            if len(future_window) < sustain_count:
                future_window = smoothed_values[index:]
            if sum(1 for value in future_window if value >= threshold) < max(2, sustain_count - 1):
                continue

            smoothed_feature_index = next(
                (index + offset for offset, value in enumerate(future_window) if value >= threshold),
                index,
            )
            raw_threshold = baseline + max(dynamic_range * 0.10, max(minimum_margin * 0.6, 18.0))
            raw_search_end = min(len(raw_values), smoothed_feature_index + sustain_count + 4)
            feature_index = next(
                (
                    candidate_index
                    for candidate_index in range(index, raw_search_end)
                    if raw_values[candidate_index] >= raw_threshold
                ),
                smoothed_feature_index,
            )
            feature_current = smoothed_values[feature_index]
            feature_previous = smoothed_values[max(0, feature_index - 1)]
            point = thermal_points[feature_index]
            return {
                "label": "thermal-rise-onset",
                "time": point["time"],
                "timestamp_ms": int(point["timestamp_ms"]),
                "g_high": round(float(point["g_high"]), 4),
                "tspan_s": round(float(point["tspan_s"]), 6)
                if point.get("tspan_s") not in (None, "")
                else None,
                "baseline": round(baseline, 4),
                "peak": round(peak_value, 4),
                "threshold": round(threshold, 4),
                "rise_delta": round(feature_current - feature_previous, 4),
                "jump_threshold": round(jump_threshold, 4),
                "detection_mode": f"ratio-{threshold_ratio:.2f}",
            }
        return None

    strict_feature = locate_rise(
        threshold_ratio=0.18,
        minimum_margin=40.0,
        jump_ratio=0.07,
    )
    if strict_feature is not None:
        return strict_feature

    return locate_rise(
        threshold_ratio=0.12,
        minimum_margin=20.0,
        jump_ratio=0.045,
    )


def find_first_machine_laser_on_feature(edge: dict[str, Any]) -> dict[str, Any] | None:
    machine_events = edge.get("machine_events") or []
    for event in machine_events:
        if not isinstance(event, dict):
            continue
        if event.get("event_type") != "laser_on":
            continue
        return {
            "label": "機台 LASER ON",
            "time": str(event.get("time") or "-"),
            "timestamp_ms": int(event.get("timestamp_ms") or 0),
            "g_code": str(event.get("g_code") or ""),
            "probe_counter": int(event.get("probe_counter") or 0),
        }
    return None


def find_machine_z_laser_feature(edge: dict[str, Any]) -> dict[str, Any] | None:
    edge_points = [
        point
        for point in edge.get("full_trace") or []
        if isinstance(point, dict) and point.get("timestamp_ms") is not None
    ]
    laser_feature = find_first_machine_laser_on_feature(edge)
    if not edge_points:
        return laser_feature

    z_points: list[tuple[dict[str, Any], float]] = []
    for point in edge_points:
        z_value = get_edge_z_value(point)
        if z_value is None:
            continue
        z_points.append((point, z_value))

    if not z_points:
        return laser_feature

    min_z = min(z_value for _, z_value in z_points)
    max_z = max(z_value for _, z_value in z_points)
    z_tolerance_mm = max(0.02, min(0.2, (max_z - min_z) * 0.02))
    lowest_candidates = [
        point
        for point, z_value in z_points
        if z_value <= min_z + z_tolerance_mm
    ]
    if not lowest_candidates:
        return laser_feature

    z_anchor_point = min(lowest_candidates, key=lambda item: int(item.get("timestamp_ms") or 0))
    z_anchor_timestamp_ms = int(z_anchor_point.get("timestamp_ms") or 0)
    machine_events = [
        event
        for event in (edge.get("machine_events") or [])
        if isinstance(event, dict) and event.get("event_type") == "laser_on"
    ]

    selected_event: dict[str, Any] | None = None
    if machine_events:
        future_events = [
            event
            for event in machine_events
            if 0 <= int(event.get("timestamp_ms") or 0) - z_anchor_timestamp_ms <= 20000
        ]
        if future_events:
            selected_event = min(
                future_events,
                key=lambda item: int(item.get("timestamp_ms") or 0),
            )
        else:
            selected_event = min(
                machine_events,
                key=lambda item: abs(int(item.get("timestamp_ms") or 0) - z_anchor_timestamp_ms),
            )

    feature_timestamp_ms = (
        int(selected_event.get("timestamp_ms") or z_anchor_timestamp_ms)
        if selected_event
        else z_anchor_timestamp_ms
    )
    feature_point = find_edge_point_near_timestamp(edge_points, feature_timestamp_ms) or z_anchor_point
    feature_z_mm = get_edge_z_value(feature_point)
    feature_source = "z_min_laser_on" if selected_event is not None else "z_minimum"
    label = "Z 最低點後 LASER ON" if selected_event is not None else "Z 最低點"

    return {
        "label": label,
        "time": str(selected_event.get("time") if selected_event else feature_point.get("time") or "-"),
        "timestamp_ms": feature_timestamp_ms,
        "g_code": str(selected_event.get("g_code") or "") if selected_event else "",
        "probe_counter": int(selected_event.get("probe_counter") or 0)
        if selected_event
        else int(feature_point.get("probe_counter") or 0),
        "feature_source": feature_source,
        "z_min_mm": round(float(min_z), 6),
        "z_tolerance_mm": round(float(z_tolerance_mm), 6),
        "z_min_time": str(z_anchor_point.get("time") or "-"),
        "z_min_timestamp_ms": z_anchor_timestamp_ms,
        "machine_x_mm": round(float(feature_point.get("machine_x_mm")), 6)
        if feature_point.get("machine_x_mm") is not None
        else None,
        "machine_y_mm": round(float(feature_point.get("machine_y_mm")), 6)
        if feature_point.get("machine_y_mm") is not None
        else None,
        "machine_z_mm": round(float(feature_z_mm), 6) if feature_z_mm is not None else None,
        "laser_delay_ms": feature_timestamp_ms - z_anchor_timestamp_ms,
    }


def find_first_hot_edge_point(edge_points: list[dict[str, Any]]) -> dict[str, Any] | None:
    thermal_like_points = [
        {
            "time": point.get("time"),
            "timestamp_ms": point.get("timestamp_ms"),
            "g_high": point.get("g_high"),
        }
        for point in edge_points
        if point.get("g_high") is not None
    ]
    feature = detect_thermal_rise_feature(thermal_like_points)
    if feature is None:
        return None

    target_timestamp = int(feature["timestamp_ms"])
    return min(
        (
            point
            for point in edge_points
            if all(key in point for key in ("machine_x_mm", "machine_y_mm", "machine_z_mm"))
        ),
        key=lambda item: abs(int(item["timestamp_ms"]) - target_timestamp),
        default=None,
    )


def compute_xyz_offset(
    target_point: dict[str, Any] | None,
    source_point: dict[str, Any] | None,
    source_prefix: str = "machine",
) -> dict[str, float] | None:
    if not target_point or not source_point:
        return None
    try:
        return {
            "x_mm": round(float(target_point["x_mm"]) - float(source_point[f"{source_prefix}_x_mm"]), 6),
            "y_mm": round(float(target_point["y_mm"]) - float(source_point[f"{source_prefix}_y_mm"]), 6),
            "z_mm": round(float(target_point["z_mm"]) - float(source_point[f"{source_prefix}_z_mm"]), 6),
        }
    except (KeyError, TypeError, ValueError):
        return None


def apply_xyz_offset(point: dict[str, Any], offset: dict[str, float]) -> dict[str, Any]:
    transformed = dict(point)
    transformed["work_x_mm"] = round(float(point["machine_x_mm"]) + float(offset["x_mm"]), 6)
    transformed["work_y_mm"] = round(float(point["machine_y_mm"]) + float(offset["y_mm"]), 6)
    transformed["work_z_mm"] = round(float(point["machine_z_mm"]) + float(offset["z_mm"]), 6)
    return transformed


def build_coordinate_alignment_data(
    edge: dict[str, Any],
    toolpath_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    edge_points = [
        point
        for point in edge.get("full_trace") or []
        if all(key in point for key in ("machine_x_mm", "machine_y_mm", "machine_z_mm"))
    ]
    if not edge_points:
        return {
            "available": False,
            "message": "No machine-coordinate edge samples are available.",
            "work_trace": [],
            "trajectory_summaries": [],
            "nc_reference_trace": [],
        }

    first_travel_anchor = get_first_toolpath_end_point(toolpath_segments)
    first_deposit_anchor = get_first_toolpath_anchor_point(toolpath_segments, "deposit")
    if not first_travel_anchor and not first_deposit_anchor:
        return {
            "available": False,
            "message": "No toolpath anchor points were found for coordinate conversion.",
            "work_trace": [],
            "trajectory_summaries": [],
            "nc_reference_trace": [],
        }

    first_machine_point = edge_points[0]
    machine_process_feature = find_machine_z_laser_feature(edge)
    process_machine_point = (
        find_edge_point_near_timestamp(
            edge_points,
            int(machine_process_feature["timestamp_ms"]),
            max_gap_ms=5000,
        )
        if machine_process_feature is not None
        else None
    )
    hot_machine_point = process_machine_point or find_first_hot_edge_point(edge_points) or first_machine_point
    preposition_offset = compute_xyz_offset(first_travel_anchor, first_machine_point)
    process_offset = compute_xyz_offset(first_deposit_anchor, hot_machine_point)
    applied_offset = process_offset or preposition_offset

    if applied_offset is None:
        return {
            "available": False,
            "message": "The dashboard could not derive a usable machine-to-work offset.",
            "work_trace": [],
            "trajectory_summaries": [],
            "nc_reference_trace": [],
        }

    transformed_points = [apply_xyz_offset(point, applied_offset) for point in edge_points]

    trajectory_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in transformed_points:
        trajectory_id = str(point.get("trajectory_id") or "trace").strip() or "trace"
        trajectory_groups[trajectory_id].append(point)

    def sort_key(value: str) -> tuple[int, str]:
        return (0, f"{int(value):06d}") if value.isdigit() else (1, value)

    trajectory_summaries: list[dict[str, Any]] = []
    for trajectory_id in sorted(trajectory_groups, key=sort_key):
        group = sorted(trajectory_groups[trajectory_id], key=lambda item: int(item["timestamp_ms"]))
        first = group[0]
        last = group[-1]
        trajectory_summaries.append(
            {
                "trajectory_id": trajectory_id,
                "sample_count": len(group),
                "start_time": first.get("time"),
                "end_time": last.get("time"),
                "machine_start": {
                    "x_mm": first["machine_x_mm"],
                    "y_mm": first["machine_y_mm"],
                    "z_mm": first["machine_z_mm"],
                },
                "machine_end": {
                    "x_mm": last["machine_x_mm"],
                    "y_mm": last["machine_y_mm"],
                    "z_mm": last["machine_z_mm"],
                },
                "work_start": {
                    "x_mm": first["work_x_mm"],
                    "y_mm": first["work_y_mm"],
                    "z_mm": first["work_z_mm"],
                },
                "work_end": {
                    "x_mm": last["work_x_mm"],
                    "y_mm": last["work_y_mm"],
                    "z_mm": last["work_z_mm"],
                },
            }
        )

    nc_reference_trace: list[dict[str, float]] = []
    last_end: dict[str, Any] | None = None
    for segment in toolpath_segments:
        if segment.get("path_type") != "deposit":
            continue
        start_point = segment.get("start_point")
        end_point = segment.get("end_point")
        if isinstance(start_point, dict) and all(key in start_point for key in ("x_mm", "y_mm", "z_mm")):
            if last_end is None or any(
                abs(float(start_point[key]) - float(last_end[key])) > 1e-9
                for key in ("x_mm", "y_mm", "z_mm")
            ):
                nc_reference_trace.append(
                    {
                        "x_mm": float(start_point["x_mm"]),
                        "y_mm": float(start_point["y_mm"]),
                        "z_mm": float(start_point["z_mm"]),
                    }
                )
        if isinstance(end_point, dict) and all(key in end_point for key in ("x_mm", "y_mm", "z_mm")):
            nc_reference_trace.append(
                {
                    "x_mm": float(end_point["x_mm"]),
                    "y_mm": float(end_point["y_mm"]),
                    "z_mm": float(end_point["z_mm"]),
                }
            )
            last_end = end_point

    return {
        "available": True,
        "message": "Machine-frame edge samples were converted into the MPF workpiece frame.",
        "machine_frame_label": "machine_absolute",
        "work_frame_label": "g54_workpiece",
        "time_mode": str(edge.get("time_mode") or "absolute"),
        "coordinate_fields": edge.get("coordinate_fields") or {"x": None, "y": None, "z": None},
        "applied_offset_mm": applied_offset,
        "preposition_offset_mm": preposition_offset,
        "process_offset_mm": process_offset,
        "offset_method": (
            "z-min-laser-on-to-first-deposit"
            if process_offset and machine_process_feature is not None
            else "first-hot-point-to-first-deposit"
            if process_offset
            else "first-sample-to-first-anchor"
        ),
        "first_machine_point": {
            "time": first_machine_point.get("time"),
            "x_mm": first_machine_point["machine_x_mm"],
            "y_mm": first_machine_point["machine_y_mm"],
            "z_mm": first_machine_point["machine_z_mm"],
        },
        "hot_machine_point": (
            {
                "time": hot_machine_point.get("time"),
                "x_mm": hot_machine_point["machine_x_mm"],
                "y_mm": hot_machine_point["machine_y_mm"],
                "z_mm": hot_machine_point["machine_z_mm"],
                "g_high": hot_machine_point.get("g_high"),
            }
            if hot_machine_point
            else None
        ),
        "process_machine_feature": machine_process_feature,
        "toolpath_preposition_anchor": first_travel_anchor,
        "toolpath_process_anchor": first_deposit_anchor,
        "work_trace": downsample_points(transformed_points, ALIGNMENT_DISPLAY_LIMIT),
        "trajectory_summaries": trajectory_summaries,
        "trajectory_count": len(trajectory_summaries),
        "nc_reference_trace": downsample_points(nc_reference_trace, ALIGNMENT_DISPLAY_LIMIT),
    }


def build_aligned_pair_trace(
    thermal_points: list[dict[str, Any]],
    edge_points: list[dict[str, Any]],
    thermal_offset_ms: int = 0,
    time_mode: str = "absolute",
) -> list[dict[str, Any]]:
    if not thermal_points or not edge_points:
        return []

    shifted_thermal = [
        {
            "time": point["time"],
            "shifted_time": format_timestamp_ms(
                int(point["timestamp_ms"]) + thermal_offset_ms,
                time_mode,
            ),
            "timestamp_ms": int(point["timestamp_ms"]) + thermal_offset_ms,
            "thermal_g_high": float(point["g_high"]),
        }
        for point in thermal_points
    ]

    overlap_start = max(shifted_thermal[0]["timestamp_ms"], edge_points[0]["timestamp_ms"])
    overlap_end = min(shifted_thermal[-1]["timestamp_ms"], edge_points[-1]["timestamp_ms"])
    if overlap_start > overlap_end:
        return []

    thermal_overlap = [
        point for point in shifted_thermal if overlap_start <= point["timestamp_ms"] <= overlap_end
    ]
    edge_overlap = [
        point for point in edge_points if overlap_start <= point["timestamp_ms"] <= overlap_end
    ]
    if not thermal_overlap or not edge_overlap:
        return []

    base_points = thermal_overlap if len(thermal_overlap) <= len(edge_overlap) else edge_overlap
    other_points = edge_overlap if base_points is thermal_overlap else thermal_overlap
    base_is_thermal = base_points is thermal_overlap

    aligned_points: list[dict[str, Any]] = []
    other_index = 0
    for base_point in base_points:
        base_timestamp = int(base_point["timestamp_ms"])
        while (
            other_index + 1 < len(other_points)
            and abs(int(other_points[other_index + 1]["timestamp_ms"]) - base_timestamp)
            <= abs(int(other_points[other_index]["timestamp_ms"]) - base_timestamp)
        ):
            other_index += 1

        other_point = other_points[other_index]
        if base_is_thermal:
            thermal_value = base_point["thermal_g_high"]
            edge_value = other_point["value"]
            point_time = base_point["shifted_time"]
        else:
            thermal_value = other_point["thermal_g_high"]
            edge_value = base_point["value"]
            point_time = other_point["shifted_time"]

        aligned_points.append(
            {
                "time": point_time,
                "timestamp_ms": base_timestamp,
                "thermal_g_high": round(float(thermal_value), 4),
                "edge_value": round(float(edge_value), 4),
            }
        )

    return aligned_points


def detect_thermal_active_window(thermal_points: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(thermal_points) < 8:
        return None

    raw_values = [float(point["g_high"]) for point in thermal_points if point.get("g_high") is not None]
    if len(raw_values) < 8:
        return None

    half_window = 2
    smoothed_values: list[float] = []
    for index in range(len(raw_values)):
        start = max(0, index - half_window)
        end = min(len(raw_values), index + half_window + 1)
        smoothed_values.append(sum(raw_values[start:end]) / (end - start))

    baseline_count = min(max(24, len(smoothed_values) // 25), 240)
    baseline = median_value(smoothed_values[:baseline_count])
    peak_value = percentile_value(smoothed_values, 0.98)
    dynamic_range = max(peak_value - baseline, 0.0)
    if dynamic_range < 12.0:
        return None

    start_threshold = baseline + max(dynamic_range * 0.15, 28.0)
    end_threshold = baseline + max(dynamic_range * 0.11, 20.0)
    raw_start_threshold = baseline + max(dynamic_range * 0.10, 18.0)
    raw_end_threshold = baseline + max(dynamic_range * 0.08, 15.0)
    sustain_count = max(3, min(8, len(smoothed_values) // 320 or 3))

    start_index: int | None = None
    for index in range(len(smoothed_values)):
        window = smoothed_values[index : index + sustain_count]
        if len(window) < sustain_count:
            break
        if sum(1 for value in window if value >= start_threshold) >= sustain_count - 1:
            smoothed_start_index = next(
                (index + offset for offset, value in enumerate(window) if value >= start_threshold),
                index,
            )
            raw_search_end = min(len(raw_values), smoothed_start_index + sustain_count + 4)
            start_index = next(
                (
                    candidate_index
                    for candidate_index in range(index, raw_search_end)
                    if raw_values[candidate_index] >= raw_start_threshold
                ),
                smoothed_start_index,
            )
            break

    end_index: int | None = None
    for index in range(len(smoothed_values) - sustain_count, -1, -1):
        window = smoothed_values[max(0, index - sustain_count + 1) : index + 1]
        if len(window) < sustain_count:
            continue
        if sum(1 for value in window if value >= end_threshold) >= sustain_count - 1:
            smoothed_end_index = next(
                (
                    max(0, index - sustain_count + 1) + offset
                    for offset, value in reversed(list(enumerate(window)))
                    if value >= end_threshold
                ),
                index,
            )
            raw_search_start = max(0, smoothed_end_index - sustain_count - 4)
            end_index = next(
                (
                    candidate_index
                    for candidate_index in range(smoothed_end_index, raw_search_start - 1, -1)
                    if raw_values[candidate_index] >= raw_end_threshold
                ),
                smoothed_end_index,
            )
            break

    if start_index is None or end_index is None or end_index < start_index:
        return None

    start_point = thermal_points[start_index]
    end_point = thermal_points[end_index]
    rise_feature = detect_thermal_rise_feature(thermal_points)

    return {
        "baseline": round(baseline, 4),
        "peak": round(peak_value, 4),
        "dynamic_range": round(dynamic_range, 4),
        "start_threshold": round(start_threshold, 4),
        "end_threshold": round(end_threshold, 4),
        "start_time": start_point["time"],
        "start_timestamp_ms": int(start_point["timestamp_ms"]),
        "end_time": end_point["time"],
        "end_timestamp_ms": int(end_point["timestamp_ms"]),
        "duration_ms": int(end_point["timestamp_ms"]) - int(start_point["timestamp_ms"]),
        "rise_feature": rise_feature,
    }


def match_edge_g_high_to_accurate_thermal(
    edge_payload: dict[str, Any],
    thermal_reference: dict[str, Any],
) -> dict[str, Any]:
    full_trace = edge_payload.get("full_trace")
    thermal_points = thermal_reference.get("full_trace")
    if not isinstance(full_trace, list) or not isinstance(thermal_points, list):
        return edge_payload
    if not full_trace or not thermal_points:
        return edge_payload

    candidate_edge_points = [
        point
        for point in full_trace
        if isinstance(point, dict)
        and point.get("sample_ms") not in (None, "")
        and point.get("g_high") not in (None, "")
    ]
    candidate_thermal_points = [
        point
        for point in thermal_points
        if isinstance(point, dict)
        and point.get("tspan_s") not in (None, "")
        and point.get("g_high") not in (None, "")
        and point.get("timestamp_ms") not in (None, "")
    ]
    if not candidate_edge_points or not candidate_thermal_points:
        return edge_payload

    machine_feature = find_machine_z_laser_feature(edge_payload) or find_first_machine_laser_on_feature(edge_payload)
    thermal_feature = detect_thermal_rise_feature(candidate_thermal_points)
    feature_seed_s: float | None = None
    if (
        machine_feature is not None
        and thermal_feature is not None
        and thermal_feature.get("tspan_s") not in (None, "")
    ):
        feature_seed_s = float(thermal_feature["tspan_s"]) - (int(machine_feature["timestamp_ms"]) / 1000.0)

    thermal_index_by_signature: dict[int, list[float]] = defaultdict(list)
    thermal_frequency: dict[int, int] = defaultdict(int)
    for point in candidate_thermal_points:
        signature = g_high_signature(point.get("g_high"))
        if signature is None:
            continue
        try:
            tspan_s = float(point.get("tspan_s"))
        except (TypeError, ValueError):
            continue
        thermal_index_by_signature[signature].append(tspan_s)
        thermal_frequency[signature] += 1
    if not thermal_index_by_signature and feature_seed_s is None:
        return edge_payload

    probe_points = select_alignment_probe_points(candidate_edge_points, thermal_frequency)
    if not probe_points and feature_seed_s is None:
        return edge_payload

    offset_bins: dict[float, list[float]] = defaultdict(list)
    feature_window_s = 20.0 if feature_seed_s is not None else None
    for point in probe_points:
        signature = g_high_signature(point.get("g_high"))
        if signature is None:
            continue
        candidate_tspans = thermal_index_by_signature.get(signature) or []
        if not candidate_tspans:
            continue
        try:
            sample_s = float(point.get("sample_ms")) / 1000.0
        except (TypeError, ValueError):
            continue
        for tspan_s in candidate_tspans:
            exact_offset = tspan_s - sample_s
            if feature_window_s is not None and abs(exact_offset - feature_seed_s) > feature_window_s:
                continue
            offset_bins[round(exact_offset, 2)].append(exact_offset)

    thermal_tspans = [float(point["tspan_s"]) for point in candidate_thermal_points]
    candidate_offsets: list[float] = []
    if feature_seed_s is not None:
        candidate_offsets.append(float(feature_seed_s))
    for _, exact_offsets in sorted(offset_bins.items(), key=lambda item: len(item[1]), reverse=True)[:12]:
        candidate_offsets.append(float(median(exact_offsets)))
    if not candidate_offsets:
        return edge_payload

    unique_offsets: list[float] = []
    seen_offsets: set[float] = set()
    for offset_s in candidate_offsets:
        rounded_key = round(float(offset_s), 4)
        if rounded_key in seen_offsets:
            continue
        seen_offsets.add(rounded_key)
        unique_offsets.append(float(offset_s))

    best_offset_s: float | None = None
    best_mae = float("inf")
    best_exact_matches = -1
    best_adjusted_mae = float("inf")
    for offset_s in unique_offsets:
        mae, exact_matches = evaluate_edge_thermal_offset(
            candidate_edge_points,
            candidate_thermal_points,
            thermal_tspans,
            offset_s,
        )
        feature_penalty = abs(offset_s - feature_seed_s) * 0.6 if feature_seed_s is not None else 0.0
        adjusted_mae = mae + feature_penalty
        if (
            exact_matches > best_exact_matches
            or (exact_matches == best_exact_matches and adjusted_mae < best_adjusted_mae)
            or (
                exact_matches == best_exact_matches
                and abs(adjusted_mae - best_adjusted_mae) < 1e-9
                and mae < best_mae
            )
        ):
            best_offset_s = offset_s
            best_mae = mae
            best_exact_matches = exact_matches
            best_adjusted_mae = adjusted_mae

    if best_offset_s is None:
        return edge_payload

    matched_exact_offsets: list[float] = []
    matched_samples = 0
    for point in candidate_edge_points:
        try:
            sample_ms = float(point.get("sample_ms"))
            edge_g_high = float(point.get("g_high"))
        except (TypeError, ValueError):
            continue
        target_tspan_s = best_offset_s + sample_ms / 1000.0
        center_index = nearest_thermal_index_by_tspan(thermal_tspans, target_tspan_s)
        candidate_indices = range(max(0, center_index - 3), min(len(candidate_thermal_points), center_index + 4))
        best_point: dict[str, Any] | None = None
        best_score: tuple[float, float] | None = None
        for candidate_index in candidate_indices:
            candidate_point = candidate_thermal_points[candidate_index]
            candidate_g_high = float(candidate_point["g_high"])
            candidate_tspan_s = float(candidate_point["tspan_s"])
            score = (abs(candidate_g_high - edge_g_high), abs(candidate_tspan_s - target_tspan_s))
            if best_score is None or score < best_score:
                best_score = score
                best_point = candidate_point
        if best_point is None:
            continue
        matched_samples += 1
        point["time"] = str(best_point.get("time") or point.get("time") or "-")
        point["timestamp_ms"] = int(best_point["timestamp_ms"])
        point["accurate_tspan_s"] = round(float(best_point["tspan_s"]), 3)
        point["accurate_time_source"] = thermal_reference.get("source_file")
        if abs(float(best_point["g_high"]) - edge_g_high) <= 0.05:
            matched_exact_offsets.append(float(best_point["tspan_s"]) - sample_ms / 1000.0)

    refined_offset_s = best_offset_s
    if matched_exact_offsets:
        refined_offset_s = float(median(matched_exact_offsets))

    mapped_full_trace = [
        point
        for point in full_trace
        if isinstance(point, dict) and point.get("timestamp_ms") is not None
    ]
    mapped_full_trace.sort(key=lambda item: int(item["timestamp_ms"]))
    edge_payload["time_mode"] = "absolute"
    edge_payload["full_trace"] = mapped_full_trace
    edge_payload["edge_trace"] = downsample_points(edge_payload["full_trace"], SENSOR_DISPLAY_LIMIT)
    edge_payload["playback_trace"] = downsample_points(edge_payload["full_trace"], SENSOR_PLAYBACK_LIMIT)
    edge_payload["trajectory_summaries"] = build_edge_trajectory_summaries(edge_payload["full_trace"])
    if edge_payload["full_trace"]:
        edge_payload["start_time"] = edge_payload["full_trace"][0]["time"]
        edge_payload["end_time"] = edge_payload["full_trace"][-1]["time"]
    edge_payload["embedded_thermal"] = thermal_reference
    edge_payload["accurate_time_mapping"] = {
        "source_file": thermal_reference.get("source_file"),
        "mapping_method": "feature-seeded-g_high_match" if feature_seed_s is not None else "g_high_sequence_match",
        "offset_s": round(refined_offset_s, 3),
        "feature_seed_s": round(feature_seed_s, 3) if feature_seed_s is not None else None,
        "feature_gap_s": round(refined_offset_s - feature_seed_s, 3) if feature_seed_s is not None else None,
        "scale": 1.0,
        "matched_samples": matched_samples,
        "total_samples": len(candidate_edge_points),
        "mean_absolute_g_high_error": round(best_mae, 6) if best_mae != float("inf") else None,
        "machine_feature": machine_feature,
        "thermal_feature": thermal_feature,
    }
    return edge_payload


def apply_recorder_timing_mapping(
    sensor_payload: dict[str, Any],
    recorder_timing: dict[str, Any],
) -> dict[str, Any]:
    if not recorder_timing.get("available"):
        return sensor_payload

    full_trace = sensor_payload.get("full_trace")
    if not isinstance(full_trace, list) or not full_trace:
        return sensor_payload

    if str(sensor_payload.get("time_mode") or "") != "relative_ms":
        return sensor_payload

    timestamp_values = [
        int(point["timestamp_ms"])
        for point in full_trace
        if isinstance(point, dict) and point.get("timestamp_ms") is not None
    ]
    if len(timestamp_values) < 2:
        return sensor_payload

    trace_start_ms = min(timestamp_values)
    trace_end_ms = max(timestamp_values)
    trace_duration_ms = trace_end_ms - trace_start_ms
    if trace_duration_ms <= 0:
        return sensor_payload

    candidate_windows: list[tuple[str, int, int]] = []
    process_duration_ms = recorder_timing.get("laser_on_to_m30_ms")
    preamble_ms = recorder_timing.get("g4_to_laser_on_ms")
    program_duration_ms = recorder_timing.get("g4_to_m30_ms")
    if process_duration_ms not in (None, ""):
        candidate_windows.append(("laser_on_to_m30", int(process_duration_ms), int(preamble_ms or 0)))
    if program_duration_ms not in (None, ""):
        candidate_windows.append(("g4_to_m30", int(program_duration_ms), 0))
    if not candidate_windows:
        return sensor_payload

    mapping_mode, target_duration_ms, program_offset_ms = min(
        candidate_windows,
        key=lambda item: abs(item[1] - trace_duration_ms),
    )
    scale = target_duration_ms / trace_duration_ms if trace_duration_ms > 0 else 1.0

    for point in full_trace:
        try:
            relative_ms = int(point["timestamp_ms"]) - trace_start_ms
        except (KeyError, TypeError, ValueError):
            continue
        process_elapsed_ms = int(round(relative_ms * scale))
        program_elapsed_ms = int(round(program_offset_ms + process_elapsed_ms))
        point["process_elapsed_ms"] = process_elapsed_ms
        point["program_elapsed_ms"] = program_elapsed_ms
        point["program_time"] = format_relative_time_ms(program_elapsed_ms)

    sensor_payload["recorder_timing_alignment"] = {
        "mapping_mode": mapping_mode,
        "edge_duration_ms": trace_duration_ms,
        "target_duration_ms": target_duration_ms,
        "program_offset_ms": program_offset_ms,
        "scale": round(scale, 6),
        "start_program_time": format_relative_time_ms(program_offset_ms),
        "end_program_time": format_relative_time_ms(program_offset_ms + target_duration_ms),
    }
    return sensor_payload


def build_alignment_data(thermal: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
    thermal_points = thermal.get("full_trace") or []
    edge_points = edge.get("full_trace") or []
    edge_label = edge.get("value_label", "Edge")
    time_mode = str(edge.get("time_mode") or thermal.get("time_mode") or "absolute")

    if not thermal_points and not edge_points:
        return {
            "available": False,
            "message": "No thermal or edge samples are available.",
            "trace": [],
            "sample_count": 0,
            "edge_label": edge_label,
        }
    if not thermal_points:
        return {
            "available": False,
            "message": "No thermal samples are available.",
            "trace": [],
            "sample_count": 0,
            "edge_label": edge_label,
        }
    if not edge_points:
        return {
            "available": False,
            "message": "No edge samples are available.",
            "trace": [],
            "sample_count": 0,
            "edge_label": edge_label,
        }

    machine_feature = find_machine_z_laser_feature(edge) or find_first_machine_laser_on_feature(edge)
    thermal_active_window = detect_thermal_active_window(thermal_points)
    thermal_feature = (
        thermal_active_window.get("rise_feature")
        if isinstance(thermal_active_window, dict) and thermal_active_window.get("rise_feature")
        else detect_thermal_rise_feature(thermal_points)
    )
    auto_offset_ms = 0
    method = "timestamp-overlap"
    method_label = "timestamp overlap"
    message = "The dashboard aligned thermal and edge samples by timestamp overlap."

    if machine_feature is not None and thermal_feature is not None:
        auto_offset_ms = int(machine_feature["timestamp_ms"]) - int(thermal_feature["timestamp_ms"])
        feature_source = str(machine_feature.get("feature_source") or "")
        if feature_source == "z_min_laser_on":
            method = "feature-z-laser-rise"
            method_label = "z-min + laser-on vs thermal rise"
            message = "The dashboard aligned thermal time using the first effective thermal rise and the z-min laser-on machine feature."
        elif feature_source == "z_minimum":
            method = "feature-z-min-rise"
            method_label = "z-min vs thermal rise"
            message = "The dashboard aligned thermal time using the first effective thermal rise and the machine z-min feature."
        else:
            method = "feature-laser-onset"
            method_label = "laser-on vs thermal rise"
            message = "The dashboard aligned thermal time using the first effective thermal rise and the first machine laser-on event."

    raw_pairs = build_aligned_pair_trace(
        thermal_points,
        edge_points,
        thermal_offset_ms=0,
        time_mode=time_mode,
    )
    aligned_pairs = build_aligned_pair_trace(
        thermal_points,
        edge_points,
        thermal_offset_ms=auto_offset_ms,
        time_mode=time_mode,
    )
    display_trace = downsample_points(aligned_pairs or raw_pairs, ALIGNMENT_DISPLAY_LIMIT)

    aligned_window: dict[str, Any] | None = None
    if isinstance(thermal_active_window, dict):
        aligned_start_ms = int(thermal_active_window["start_timestamp_ms"]) + auto_offset_ms
        aligned_end_ms = int(thermal_active_window["end_timestamp_ms"]) + auto_offset_ms
        aligned_window = {
            **thermal_active_window,
            "aligned_start_timestamp_ms": aligned_start_ms,
            "aligned_end_timestamp_ms": aligned_end_ms,
            "aligned_start_time": format_timestamp_ms(aligned_start_ms, time_mode),
            "aligned_end_time": format_timestamp_ms(aligned_end_ms, time_mode),
        }

    if not raw_pairs and not aligned_pairs:
        return {
            "available": False,
            "message": "The thermal and edge timelines do not overlap after alignment.",
            "trace": [],
            "sample_count": 0,
            "edge_label": edge_label,
            "auto_offset_ms": auto_offset_ms,
            "manual_offset_default_ms": 0,
            "manual_offset_range_ms": 60000,
            "applied_offset_ms": auto_offset_ms,
            "method": method,
            "method_label": method_label,
            "machine_feature": machine_feature,
            "thermal_feature": thermal_feature,
            "thermal_active_window": aligned_window,
            "raw_trace": [],
            "aligned_trace": [],
            "raw_pair_count": 0,
            "aligned_pair_count": 0,
        }

    aligned_start_time = (
        format_timestamp_ms(int(thermal_points[0]["timestamp_ms"]) + auto_offset_ms, time_mode)
        if thermal_points
        else "-"
    )
    aligned_end_time = (
        format_timestamp_ms(int(thermal_points[-1]["timestamp_ms"]) + auto_offset_ms, time_mode)
        if thermal_points
        else "-"
    )

    confidence = "low"
    if machine_feature is not None and thermal_feature is not None:
        confidence = "high" if aligned_window is not None else "medium"
    elif aligned_pairs:
        confidence = "medium"

    return {
        "available": True,
        "message": message,
        "edge_label": edge_label,
        "start_time": display_trace[0]["time"] if display_trace else "-",
        "end_time": display_trace[-1]["time"] if display_trace else "-",
        "sample_count": len(aligned_pairs or raw_pairs),
        "thermal_sample_count": thermal.get("sample_count", 0),
        "edge_sample_count": edge.get("sample_count", 0),
        "trace": display_trace,
        "raw_trace": downsample_points(raw_pairs, ALIGNMENT_DISPLAY_LIMIT),
        "aligned_trace": downsample_points(aligned_pairs, ALIGNMENT_DISPLAY_LIMIT),
        "auto_offset_ms": auto_offset_ms,
        "manual_offset_default_ms": 0,
        "manual_offset_range_ms": 60000,
        "applied_offset_ms": auto_offset_ms,
        "time_mode": time_mode,
        "method": method,
        "method_label": method_label,
        "confidence": confidence,
        "machine_feature": machine_feature,
        "thermal_feature": thermal_feature,
        "thermal_active_window": aligned_window,
        "raw_pair_count": len(raw_pairs),
        "aligned_pair_count": len(aligned_pairs),
        "raw_start_time": thermal_points[0]["time"],
        "raw_end_time": thermal_points[-1]["time"],
        "aligned_start_time": aligned_start_time,
        "aligned_end_time": aligned_end_time,
    }


def apply_time_alignment(
    *,
    edge: dict[str, Any],
    recorder_timing: dict[str, Any],
    accurate_thermal_reference: dict[str, Any] | None,
) -> dict[str, Any]:
    if accurate_thermal_reference is not None:
        return match_edge_g_high_to_accurate_thermal(edge, accurate_thermal_reference)
    return apply_recorder_timing_mapping(edge, recorder_timing)



def build_alignment_views(
    *,
    thermal: dict[str, Any],
    edge: dict[str, Any],
    toolpath_segments: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    alignment = build_alignment_data(thermal, edge)
    coordinate_alignment = build_coordinate_alignment_data(edge, toolpath_segments)
    return alignment, coordinate_alignment



__all__ = [
    "apply_time_alignment",
    "build_alignment_views",
    "apply_recorder_timing_mapping",
    "match_edge_g_high_to_accurate_thermal",
    "build_alignment_data",
    "build_coordinate_alignment_data",
]
