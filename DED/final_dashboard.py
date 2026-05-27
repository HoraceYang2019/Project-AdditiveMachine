from __future__ import annotations

import cgi
import csv
import io
import json
import mimetypes
import re
import shutil
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import parse_qs, quote, urlparse


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = BASE_DIR / "output"
DEFAULT_OUTPUT_NAME = "202603237504150010_modified"
TEMPLATES_DIR = BASE_DIR / "dashboard_templates"
STATIC_DIR = BASE_DIR / "dashboard_static"
UPLOAD_ROOT = BASE_DIR / "uploaded_inputs"
GENERATED_MPF_ROOT = BASE_DIR / "generated_mpf"
EXPORTED_MPF_ROOT = BASE_DIR / "exported_mpf"
THERMAL_EXAMPLE_PATH = BASE_DIR / "examples" / "thermal-imager.example.json"
RECORDER_JSON_DIR = BASE_DIR / "json"
THERMAL_REFERENCE_DIR = BASE_DIR / "csv"
THERMAL_DATA_FILENAME = "thermal-data.json"
EDGE_DATA_FILENAME = "edge-data.json"
SOURCE_MPF_DIRNAME = "source_mpf"
SOURCE_ENCODINGS = ("utf-8", "utf-8-sig", "cp950", "mbcs", "latin-1")
SENSOR_DISPLAY_LIMIT = 600
ALIGNMENT_DISPLAY_LIMIT = 400
TIME_FIELD_CANDIDATES = (
    "time",
    "timestamp",
    "datetime",
    "date_time",
    "recorded_at",
    "captured_at",
    "sample_time",
)
RELATIVE_TIME_FIELD_CANDIDATES = (
    "sample_ms",
    "elapsed_ms",
    "time_ms",
    "relative_ms",
    "offset_ms",
)
THERMAL_VALUE_CANDIDATES = ("g_high", "ghigh", "g-high")
THERMAL_TSPAN_CANDIDATES = ("tspan(s)", "tspan_s", "tspan", "elapsed_s", "elapsed")
EDGE_X_FIELD_CANDIDATES = ("x_mm", "x", "machine_x_mm", "machine_x")
EDGE_Y_FIELD_CANDIDATES = ("y_mm", "y", "machine_y_mm", "machine_y")
EDGE_Z_FIELD_CANDIDATES = ("z_mm", "z", "machine_z_mm", "machine_z")
EDGE_TRAJECTORY_FIELD_CANDIDATES = ("trajectory_id", "trajectory", "track_id", "path_id")
EDGE_ALIGN_ERROR_FIELD_CANDIDATES = ("align_error_ms", "alignment_error_ms", "time_error_ms")
EDGE_IGNORED_VALUE_FIELDS = {
    "cycle",
    "no",
    "number",
    "index",
    "idx",
    "id",
    "row",
    "rows",
    "sample",
    "sampleno",
    "samplenumber",
    "tspan",
    "tspans",
}
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
DEMO_OUTPUT_NAMES = {"202603237504150010", "202603237504150010_modified"}


def is_relative_time_field_name(field_name: str | None) -> bool:
    return normalize_field_name(field_name) in {
        normalize_field_name(candidate) for candidate in RELATIVE_TIME_FIELD_CANDIDATES
    }


def format_relative_time_ms(timestamp_ms: int | float) -> str:
    rounded = int(round(float(timestamp_ms)))
    sign = "-" if rounded < 0 else ""
    return f"T{sign}+{abs(rounded)} ms"


def format_timestamp_ms(timestamp_ms: int | float, time_mode: str = "absolute") -> str:
    if time_mode == "relative_ms":
        return format_relative_time_ms(timestamp_ms)
    return format_timestamp(datetime.fromtimestamp(float(timestamp_ms) / 1000.0))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def read_text_any_encoding(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in SOURCE_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return path.read_text()


def discover_output_dir(output_name: str | None = None) -> Path:
    if output_name:
        candidate = OUTPUT_ROOT / output_name
        if candidate.is_dir():
            return candidate

    default_dir = OUTPUT_ROOT / DEFAULT_OUTPUT_NAME
    if default_dir.is_dir():
        return default_dir

    for child in sorted(OUTPUT_ROOT.iterdir()):
        if child.is_dir():
            return child

    raise FileNotFoundError("在 Final/output 中找不到儀表板輸出資料夾。")


def list_available_outputs() -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    manifest_path = OUTPUT_ROOT / "run-manifest.json"

    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        if isinstance(manifest, list):
            for entry in manifest:
                if not isinstance(entry, dict):
                    continue
                output_name = str(entry.get("output_dir") or "").strip()
                if not output_name or output_name in seen:
                    continue
                output_dir = OUTPUT_ROOT / output_name
                if not output_dir.is_dir():
                    continue

                summary = entry.get("summary")
                summary = summary if isinstance(summary, dict) else {}
                file_name = str(
                    summary.get("file_name") or entry.get("input_file") or output_name
                ).strip()
                source_variant = str(summary.get("source_variant") or "").strip()
                label = file_name
                if source_variant and source_variant.lower() not in file_name.lower():
                    label = f"{file_name} ({source_variant})"

                options.append({"value": output_name, "label": label})
                seen.add(output_name)

    for child in sorted(OUTPUT_ROOT.iterdir()):
        if not child.is_dir() or child.name in seen:
            continue

        file_name = child.name
        source_variant = ""
        nc_file_path = child / "NC-file.json"
        if nc_file_path.is_file():
            nc_file = read_json(nc_file_path)
            file_name = str(nc_file.get("file_name") or child.name).strip()
            source_variant = str(nc_file.get("source_variant") or "").strip()

        label = file_name
        if source_variant and source_variant.lower() not in file_name.lower():
            label = f"{file_name} ({source_variant})"

        options.append({"value": child.name, "label": label})
        seen.add(child.name)

    return options


def normalize_field_name(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").strip().lower())


def format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def format_duration_label_from_ms(duration_ms: float | int | None) -> str:
    if duration_ms in (None, ""):
        return "-"
    try:
        total_ms = int(round(float(duration_ms)))
    except (TypeError, ValueError):
        return "-"
    if total_ms < 0:
        total_ms = 0
    total_seconds, milliseconds = divmod(total_ms, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"


def parse_timestamp_value(raw_value: Any) -> datetime:
    if raw_value is None:
        raise ValueError("缺少時間欄位。")

    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        number = float(raw_value)
        if abs(number) >= 1_000_000_000_000:
            return datetime.fromtimestamp(number / 1000.0)
        return datetime.fromtimestamp(number)

    text = str(raw_value).strip()
    if not text:
        raise ValueError("空白時間欄位。")

    if re.search(r"\d{2}:\d{2}:\d{2}:\d{1,6}$", text):
        head, fraction = text.rsplit(":", 1)
        text = f"{head}.{fraction}"

    normalized = text.replace("T", " ")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        pass

    formats = (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S.%f",
        "%m/%d/%Y %H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    raise ValueError(f"無法解析時間格式：{text}")


def parse_numeric_value(raw_value: Any) -> float:
    if raw_value is None:
        raise ValueError("缺少數值欄位。")
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        return float(raw_value)

    text = str(raw_value).strip()
    if not text:
        raise ValueError("空白數值欄位。")
    text = text.replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    return float(text)


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


def make_empty_thermal_data(program_id: str) -> dict[str, Any]:
    return {
        "program_id": program_id,
        "sensor_type": "thermal-camera",
        "source_kind": "missing",
        "source_file": "-",
        "time_field": "Time",
        "time_mode": "absolute",
        "value_field": "G_High",
        "start_time": "-",
        "end_time": "-",
        "sample_count": 0,
        "g_high_min": None,
        "g_high_max": None,
        "g_high_avg": None,
        "thermal_trace": [],
        "full_trace": [],
    }


def make_empty_edge_data(program_id: str) -> dict[str, Any]:
    return {
        "program_id": program_id,
        "sensor_type": "edge-sensor",
        "source_kind": "missing",
        "source_file": "-",
        "time_field": "-",
        "time_mode": "absolute",
        "value_field": "-",
        "value_label": "Edge 值",
        "start_time": "-",
        "end_time": "-",
        "sample_count": 0,
        "value_min": None,
        "value_max": None,
        "value_avg": None,
        "edge_trace": [],
        "full_trace": [],
        "available_value_fields": [],
        "machine_events": [],
        "sample_interval_ms": None,
        "edge_format": "generic-timeseries",
        "coordinate_fields": {"x": None, "y": None, "z": None},
        "has_machine_coordinates": False,
        "trajectory_field": None,
        "trajectory_summaries": [],
        "embedded_thermal": None,
    }


def normalize_loaded_thermal_payload(payload: Any, program_id: str, source_kind: str) -> dict[str, Any]:
    thermal = make_empty_thermal_data(program_id)
    if isinstance(payload, dict):
        thermal.update(payload)
    thermal["program_id"] = program_id or str(thermal.get("program_id") or "")
    thermal["time_mode"] = str(thermal.get("time_mode") or "absolute")
    if str(thermal.get("source_kind") or "").strip() in ("", "missing"):
        thermal["source_kind"] = source_kind
    else:
        thermal["source_kind"] = str(thermal.get("source_kind"))

    full_trace = thermal.get("full_trace")
    if not isinstance(full_trace, list):
        full_trace = []
    normalized_full_trace: list[dict[str, Any]] = []
    for item in full_trace:
        if not isinstance(item, dict):
            continue
        try:
            timestamp_ms = int(item.get("timestamp_ms"))
            g_high = float(item.get("g_high"))
        except (TypeError, ValueError):
            continue
        time_text = str(item.get("time") or "")
        if not time_text:
            try:
                time_text = format_timestamp_ms(timestamp_ms, thermal["time_mode"])
            except (OSError, OverflowError, ValueError):
                time_text = "-"
        normalized_item = {"time": time_text, "timestamp_ms": timestamp_ms, "g_high": g_high}
        if item.get("tspan_s") not in (None, ""):
            try:
                normalized_item["tspan_s"] = float(item.get("tspan_s"))
            except (TypeError, ValueError):
                pass
        normalized_full_trace.append(normalized_item)

    if not normalized_full_trace:
        for item in thermal.get("thermal_trace", []):
            if not isinstance(item, dict):
                continue
            try:
                g_high = parse_numeric_value(item.get("g_high"))
            except (TypeError, ValueError):
                continue
            time_mode = str(thermal.get("time_mode") or "absolute")
            try:
                if time_mode == "relative_ms":
                    timestamp_ms = int(round(parse_numeric_value(item.get("timestamp_ms", item.get("time")))))
                    time_text = format_timestamp_ms(timestamp_ms, time_mode)
                else:
                    timestamp = parse_timestamp_value(item.get("time"))
                    timestamp_ms = int(round(timestamp.timestamp() * 1000))
                    time_text = format_timestamp(timestamp)
            except (TypeError, ValueError):
                continue
            normalized_item = {
                "time": time_text,
                "timestamp_ms": timestamp_ms,
                "g_high": float(g_high),
            }
            if item.get("tspan_s") not in (None, ""):
                try:
                    normalized_item["tspan_s"] = float(item.get("tspan_s"))
                except (TypeError, ValueError):
                    pass
            normalized_full_trace.append(normalized_item)

    normalized_full_trace.sort(key=lambda item: item["timestamp_ms"])
    thermal["full_trace"] = normalized_full_trace
    thermal["thermal_trace"] = downsample_points(normalized_full_trace, SENSOR_DISPLAY_LIMIT)
    if normalized_full_trace:
        thermal["start_time"] = normalized_full_trace[0]["time"]
        thermal["end_time"] = normalized_full_trace[-1]["time"]
    return thermal


def normalize_loaded_edge_payload(payload: Any, program_id: str, source_kind: str) -> dict[str, Any]:
    edge = make_empty_edge_data(program_id)
    if isinstance(payload, dict):
        edge.update(payload)
    edge["program_id"] = program_id or str(edge.get("program_id") or "")
    edge["time_mode"] = str(edge.get("time_mode") or "absolute")
    if str(edge.get("source_kind") or "").strip() in ("", "missing"):
        edge["source_kind"] = source_kind
    else:
        edge["source_kind"] = str(edge.get("source_kind"))

    full_trace = edge.get("full_trace")
    if not isinstance(full_trace, list):
        full_trace = []
    normalized_full_trace: list[dict[str, Any]] = []
    for item in full_trace:
        if not isinstance(item, dict):
            continue
        try:
            timestamp_ms = int(item.get("timestamp_ms"))
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        time_text = str(item.get("time") or "")
        if not time_text:
            try:
                time_text = format_timestamp_ms(timestamp_ms, edge["time_mode"])
            except (OSError, OverflowError, ValueError):
                time_text = "-"
        normalized_item = {"time": time_text, "timestamp_ms": timestamp_ms, "value": value}
        for source_key, target_key in (
            ("sample_ms", "sample_ms"),
            ("trajectory_id", "trajectory_id"),
            ("machine_x_mm", "machine_x_mm"),
            ("machine_y_mm", "machine_y_mm"),
            ("machine_z_mm", "machine_z_mm"),
            ("work_x_mm", "work_x_mm"),
            ("work_y_mm", "work_y_mm"),
            ("work_z_mm", "work_z_mm"),
            ("g_high", "g_high"),
            ("align_error_ms", "align_error_ms"),
            ("accurate_tspan_s", "accurate_tspan_s"),
        ):
            if source_key not in item:
                continue
            raw_value = item.get(source_key)
            if source_key == "trajectory_id":
                normalized_item[target_key] = str(raw_value)
                continue
            try:
                normalized_item[target_key] = parse_numeric_value(raw_value)
            except (TypeError, ValueError):
                continue
        if item.get("accurate_time_source") not in (None, ""):
            normalized_item["accurate_time_source"] = str(item.get("accurate_time_source"))
        normalized_full_trace.append(normalized_item)

    if not normalized_full_trace:
        for item in edge.get("edge_trace", []):
            if not isinstance(item, dict):
                continue
            try:
                value = parse_numeric_value(item.get("value"))
            except (TypeError, ValueError):
                continue
            time_mode = str(edge.get("time_mode") or "absolute")
            try:
                if time_mode == "relative_ms":
                    timestamp_ms = int(round(parse_numeric_value(item.get("timestamp_ms", item.get("time")))))
                    time_text = format_timestamp_ms(timestamp_ms, time_mode)
                else:
                    timestamp = parse_timestamp_value(item.get("time"))
                    timestamp_ms = int(round(timestamp.timestamp() * 1000))
                    time_text = format_timestamp(timestamp)
            except (TypeError, ValueError):
                continue
            normalized_item = {"time": time_text, "timestamp_ms": timestamp_ms, "value": float(value)}
        for source_key, target_key in (
            ("sample_ms", "sample_ms"),
            ("trajectory_id", "trajectory_id"),
            ("machine_x_mm", "machine_x_mm"),
            ("machine_y_mm", "machine_y_mm"),
            ("machine_z_mm", "machine_z_mm"),
            ("work_x_mm", "work_x_mm"),
            ("work_y_mm", "work_y_mm"),
            ("work_z_mm", "work_z_mm"),
            ("g_high", "g_high"),
            ("align_error_ms", "align_error_ms"),
            ("accurate_tspan_s", "accurate_tspan_s"),
        ):
            if source_key not in item:
                continue
            raw_value = item.get(source_key)
            if source_key == "trajectory_id":
                normalized_item[target_key] = str(raw_value)
                continue
            try:
                normalized_item[target_key] = parse_numeric_value(raw_value)
            except (TypeError, ValueError):
                continue
        if item.get("accurate_time_source") not in (None, ""):
            normalized_item["accurate_time_source"] = str(item.get("accurate_time_source"))
        normalized_full_trace.append(normalized_item)

    normalized_full_trace.sort(key=lambda item: item["timestamp_ms"])
    edge["full_trace"] = normalized_full_trace
    edge["edge_trace"] = downsample_points(normalized_full_trace, SENSOR_DISPLAY_LIMIT)
    embedded_thermal = edge.get("embedded_thermal")
    if embedded_thermal:
        edge["embedded_thermal"] = normalize_loaded_thermal_payload(
            embedded_thermal,
            program_id,
            str(edge.get("source_kind") or source_kind),
        )
    edge["has_machine_coordinates"] = any(
        all(key in item for key in ("machine_x_mm", "machine_y_mm", "machine_z_mm"))
        for item in normalized_full_trace
    )
    if not edge.get("trajectory_summaries"):
        edge["trajectory_summaries"] = build_edge_trajectory_summaries(normalized_full_trace)
    if normalized_full_trace:
        edge["start_time"] = normalized_full_trace[0]["time"]
        edge["end_time"] = normalized_full_trace[-1]["time"]
    return edge


def strip_internal_sensor_fields(sensor: dict[str, Any]) -> dict[str, Any]:
    payload = dict(sensor)
    payload.pop("full_trace", None)
    embedded_thermal = payload.get("embedded_thermal")
    if isinstance(embedded_thermal, dict):
        embedded_copy = dict(embedded_thermal)
        embedded_copy.pop("full_trace", None)
        payload["embedded_thermal"] = embedded_copy
    return payload


def choose_field_name(
    field_names: list[str],
    explicit_name: str | None,
    candidates: tuple[str, ...] = (),
) -> str | None:
    normalized_map = {
        normalize_field_name(name): name
        for name in field_names
        if str(name).strip()
    }

    if explicit_name:
        explicit_key = normalize_field_name(explicit_name)
        if explicit_key in normalized_map:
            return normalized_map[explicit_key]
        raise ValueError(f"找不到指定欄位：{explicit_name}")

    for candidate in candidates:
        candidate_key = normalize_field_name(candidate)
        if candidate_key in normalized_map:
            return normalized_map[candidate_key]
    return None


def resolve_time_field_and_mode(
    field_names: list[str],
    explicit_name: str | None = None,
) -> tuple[str | None, str]:
    if explicit_name:
        resolved_name = choose_field_name(field_names, explicit_name)
        if resolved_name is None:
            return None, "absolute"
        if is_relative_time_field_name(resolved_name):
            return resolved_name, "relative_ms"
        return resolved_name, "absolute"

    resolved_name = choose_field_name(field_names, None, TIME_FIELD_CANDIDATES)
    if resolved_name is not None:
        if is_relative_time_field_name(resolved_name):
            return resolved_name, "relative_ms"
        return resolved_name, "absolute"

    resolved_name = choose_field_name(field_names, None, RELATIVE_TIME_FIELD_CANDIDATES)
    if resolved_name is not None:
        return resolved_name, "relative_ms"

    return None, "absolute"


def detect_coordinate_fields(field_names: list[str]) -> dict[str, str | None]:
    return {
        "x": choose_field_name(field_names, None, EDGE_X_FIELD_CANDIDATES),
        "y": choose_field_name(field_names, None, EDGE_Y_FIELD_CANDIDATES),
        "z": choose_field_name(field_names, None, EDGE_Z_FIELD_CANDIDATES),
    }


def detect_numeric_fields(
    rows: list[dict[str, Any]],
    exclude_names: set[str] | None = None,
) -> list[str]:
    exclude_names = exclude_names or set()
    field_names: list[str] = []
    seen: set[str] = set()
    for row in rows[:50]:
        for key in row:
            if key not in seen:
                field_names.append(key)
                seen.add(key)

    scored_fields: list[tuple[float, str]] = []
    for field_name in field_names:
        normalized_name = normalize_field_name(field_name)
        if normalized_name in exclude_names:
            continue

        total = 0
        success = 0
        for row in rows[:250]:
            if field_name not in row:
                continue
            raw_value = row.get(field_name)
            if raw_value in (None, ""):
                continue
            total += 1
            try:
                parse_numeric_value(raw_value)
                success += 1
            except (TypeError, ValueError):
                continue

        if total and success:
            scored_fields.append((success / total, field_name))

    scored_fields.sort(key=lambda item: item[0], reverse=True)
    return [field_name for _, field_name in scored_fields]


def load_rows_from_json_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    if isinstance(payload, dict):
        for key in ("rows", "records", "samples", "data", "trace", "thermal_trace", "edge_trace"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]

    raise ValueError("JSON 內容需為物件陣列，或包含 rows / records / samples / trace。")


def load_tabular_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_rows_from_json_payload(read_json(path))

    text = read_text_any_encoding(path)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    reader.fieldnames = [str(name or "").strip() for name in reader.fieldnames or []]

    rows: list[dict[str, Any]] = []
    for row in reader:
        cleaned = {str(key or "").strip(): value for key, value in row.items()}
        if any(str(value or "").strip() for value in cleaned.values()):
            rows.append(cleaned)
    return rows


def is_sinumerik_edge_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    header = payload.get("Header")
    body = payload.get("Payload")
    if not isinstance(header, dict) or not isinstance(body, list):
        return False
    signal_defs = header.get("SignalListHFData")
    return isinstance(signal_defs, list) and any(isinstance(item, dict) for item in signal_defs)


def extract_signal_names(signal_defs: Any) -> list[str]:
    names: list[str] = []
    for item in signal_defs if isinstance(signal_defs, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "").strip()
        if name:
            names.append(name)
    return names


def resolve_hf_row_signal_names(signal_names: list[str], body: list[Any]) -> list[str]:
    value_counts: list[int] = []
    for item in body[:200]:
        if not isinstance(item, dict):
            continue
        hf_rows = item.get("HFData")
        if not isinstance(hf_rows, list):
            continue
        for row in hf_rows[:20]:
            if isinstance(row, list) and len(row) >= 2:
                value_counts.append(len(row) - 1)
        if len(value_counts) >= 20:
            break

    if not value_counts:
        return signal_names

    observed_value_count = max(value_counts)
    if observed_value_count >= len(signal_names):
        return signal_names

    cycle_filtered = [
        name
        for name in signal_names
        if normalize_field_name(name) != "cycle"
    ]
    if len(cycle_filtered) == observed_value_count:
        return cycle_filtered

    return signal_names[-observed_value_count:]


def interpolate_probe_counter_timestamp_ms(
    probe_counter: int,
    sorted_anchors: list[tuple[int, datetime]],
    cycle_time_ms: float,
) -> int:
    anchor_counters = [item[0] for item in sorted_anchors]
    anchor_index = max(bisect_right(anchor_counters, probe_counter) - 1, 0)
    anchor_counter, anchor_time = sorted_anchors[anchor_index]
    timestamp = anchor_time.timestamp() + ((probe_counter - anchor_counter) * cycle_time_ms / 1000.0)
    return int(round(timestamp * 1000))


def classify_machine_event_type(g_code: str) -> str:
    upper_code = str(g_code or "").upper()
    if "M717" in upper_code:
        return "laser_on"
    if "M718" in upper_code:
        return "laser_off"
    if "M721" in upper_code:
        return "powder_on"
    if "M722" in upper_code:
        return "powder_off"
    if "G4 F1" in upper_code:
        return "trigger_on"
    if "M30" in upper_code:
        return "trigger_off"
    if upper_code.startswith("G01") or upper_code.startswith("G1 ") or upper_code.startswith("G0"):
        return "motion"
    return "other"


def extract_machine_events_from_edge_payload(
    body: list[Any],
    sorted_anchors: list[tuple[int, datetime]],
    cycle_time_ms: float,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        event_block = item.get("HFBlockEvent")
        if not isinstance(event_block, dict):
            continue
        try:
            probe_counter = int(event_block.get("HFProbeCounter"))
        except (TypeError, ValueError):
            continue

        g_code = str(event_block.get("GCode") or "").strip()
        event_type = classify_machine_event_type(g_code)
        if event_type == "other":
            continue

        timestamp_ms = interpolate_probe_counter_timestamp_ms(
            probe_counter,
            sorted_anchors,
            cycle_time_ms,
        )
        events.append(
            {
                "time": format_timestamp(datetime.fromtimestamp(timestamp_ms / 1000.0)),
                "timestamp_ms": timestamp_ms,
                "probe_counter": probe_counter,
                "event_type": event_type,
                "g_code": g_code,
                "ipo_gc": str(event_block.get("IpoGC") or "").strip(),
            }
        )

    return events


def build_sinumerik_edge_points(
    payload: dict[str, Any],
    value_field: str | None = None,
) -> tuple[list[dict[str, Any]], str, list[str], float, list[dict[str, Any]]]:
    header = payload.get("Header")
    body = payload.get("Payload")
    if not isinstance(header, dict) or not isinstance(body, list):
        raise ValueError("Edge JSON 格式缺少 Header 或 Payload。")

    header_signal_names = extract_signal_names(header.get("SignalListHFData"))
    if not header_signal_names:
        raise ValueError("Edge JSON 找不到 SignalListHFData 欄位定義。")
    signal_names = resolve_hf_row_signal_names(header_signal_names, body)

    try:
        cycle_time_ms = float(header.get("CycleTimeMs", 2) or 2)
    except (TypeError, ValueError):
        cycle_time_ms = 2.0
    if cycle_time_ms <= 0:
        cycle_time_ms = 2.0

    anchors: dict[int, datetime] = {}
    initial = header.get("Initial")
    if isinstance(initial, dict):
        try:
            initial_counter = int(initial.get("HFProbeCounter"))
            initial_time = parse_timestamp_value(initial.get("Time"))
            anchors[initial_counter] = initial_time
        except (TypeError, ValueError):
            pass

    for item in body:
        if not isinstance(item, dict):
            continue
        timestamp_block = item.get("HFTimestamp")
        if not isinstance(timestamp_block, dict):
            continue
        try:
            anchor_counter = int(timestamp_block.get("HFProbeCounter"))
            anchor_time = parse_timestamp_value(timestamp_block.get("Time"))
        except (TypeError, ValueError):
            continue
        anchors[anchor_counter] = anchor_time

    if not anchors:
        raise ValueError("Edge JSON 找不到可用的時間錨點。")

    sorted_anchors = sorted(anchors.items(), key=lambda item: item[0])
    machine_events = extract_machine_events_from_edge_payload(body, sorted_anchors, cycle_time_ms)
    available_value_fields = [
        name
        for name in signal_names
        if normalize_field_name(name) not in EDGE_IGNORED_VALUE_FIELDS
    ]
    if not available_value_fields:
        available_value_fields = list(signal_names)

    resolved_value_field = choose_field_name(
        available_value_fields,
        value_field,
    )
    if resolved_value_field is None:
        resolved_value_field = available_value_fields[0]

    try:
        resolved_value_index = signal_names.index(resolved_value_field)
    except ValueError as exc:
        raise ValueError(f"找不到指定的 Edge 數值欄位：{resolved_value_field}") from exc

    points: list[dict[str, Any]] = []
    anchor_index = 0
    current_anchor_counter, current_anchor_time = sorted_anchors[anchor_index]

    for item in body:
        if not isinstance(item, dict):
            continue
        hf_rows = item.get("HFData")
        if not isinstance(hf_rows, list):
            continue

        for row in hf_rows:
            if not isinstance(row, list) or len(row) <= resolved_value_index + 1:
                continue
            try:
                probe_counter = int(row[0])
                value = parse_numeric_value(row[resolved_value_index + 1])
            except (TypeError, ValueError):
                continue

            while (
                anchor_index + 1 < len(sorted_anchors)
                and sorted_anchors[anchor_index + 1][0] <= probe_counter
            ):
                anchor_index += 1
                current_anchor_counter, current_anchor_time = sorted_anchors[anchor_index]

            delta_counter = probe_counter - current_anchor_counter
            timestamp = current_anchor_time.timestamp() + (delta_counter * cycle_time_ms / 1000.0)
            sample_time = datetime.fromtimestamp(timestamp)
            points.append(
                {
                    "time": format_timestamp(sample_time),
                    "timestamp_ms": int(round(timestamp * 1000)),
                    "value": float(value),
                    "probe_counter": probe_counter,
                }
            )

    points.sort(key=lambda item: item["timestamp_ms"])
    return points, resolved_value_field, available_value_fields, cycle_time_ms, machine_events


def build_series_points(
    rows: list[dict[str, Any]],
    time_field: str,
    value_field: str,
    output_value_key: str,
    time_mode: str = "absolute",
    extra_numeric_fields: dict[str, str] | None = None,
    extra_text_fields: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    extra_numeric_fields = extra_numeric_fields or {}
    extra_text_fields = extra_text_fields or {}
    points: list[dict[str, Any]] = []
    for row in rows:
        try:
            value = parse_numeric_value(row.get(value_field))
        except (TypeError, ValueError):
            continue

        try:
            if time_mode == "relative_ms":
                timestamp_ms = int(round(parse_numeric_value(row.get(time_field))))
                time_text = format_timestamp_ms(timestamp_ms, time_mode)
            else:
                timestamp = parse_timestamp_value(row.get(time_field))
                timestamp_ms = int(round(timestamp.timestamp() * 1000))
                time_text = format_timestamp(timestamp)
        except (TypeError, ValueError):
            continue

        point = {
            "time": time_text,
            "timestamp_ms": timestamp_ms,
            output_value_key: float(value),
        }
        if time_mode == "relative_ms":
            point["sample_ms"] = timestamp_ms

        for source_field, target_field in extra_numeric_fields.items():
            if source_field not in row:
                continue
            raw_value = row.get(source_field)
            if raw_value in (None, ""):
                continue
            try:
                point[target_field] = float(parse_numeric_value(raw_value))
            except (TypeError, ValueError):
                continue

        for source_field, target_field in extra_text_fields.items():
            if source_field not in row:
                continue
            raw_value = str(row.get(source_field) or "").strip()
            if raw_value:
                point[target_field] = raw_value

        points.append(point)

    points.sort(key=lambda item: item["timestamp_ms"])
    return points


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


def build_thermal_dataset(
    source_path: Path,
    program_id: str,
    time_field: str | None = None,
    value_field: str | None = None,
    source_kind: str = "uploaded",
) -> dict[str, Any]:
    rows = load_tabular_rows(source_path)
    if not rows:
        raise ValueError("熱像資料檔案沒有可讀取的資料列。")

    field_names = list(rows[0].keys())
    resolved_time_field, time_mode = resolve_time_field_and_mode(field_names, time_field)
    if resolved_time_field is None:
        raise ValueError("熱像資料找不到時間欄位，請指定欄位名稱。")

    resolved_value_field = choose_field_name(field_names, value_field, THERMAL_VALUE_CANDIDATES)
    if resolved_value_field is None:
        numeric_fields = detect_numeric_fields(rows, {normalize_field_name(resolved_time_field)})
        if not numeric_fields:
            raise ValueError("熱像資料找不到數值欄位。")
        resolved_value_field = numeric_fields[0]

    points = build_series_points(
        rows,
        resolved_time_field,
        resolved_value_field,
        "g_high",
        time_mode=time_mode,
    )
    if not points:
        raise ValueError("熱像資料解析後沒有有效的時間序列點。")

    values = [point["g_high"] for point in points]
    return {
        "program_id": program_id,
        "sensor_type": "thermal-camera",
        "source_kind": source_kind,
        "source_file": source_path.name,
        "time_field": resolved_time_field,
        "time_mode": time_mode,
        "value_field": resolved_value_field,
        "start_time": points[0]["time"],
        "end_time": points[-1]["time"],
        "sample_count": len(points),
        "g_high_min": round(min(values), 4),
        "g_high_max": round(max(values), 4),
        "g_high_avg": round(sum(values) / len(values), 4),
        "thermal_trace": downsample_points(points, SENSOR_DISPLAY_LIMIT),
        "full_trace": points,
    }


def find_accurate_thermal_source(output_dir: Path) -> Path | None:
    uploaded_dir = output_dir / "uploaded_sources"
    candidate_paths: list[Path] = []
    if uploaded_dir.is_dir():
        candidate_paths.extend(sorted(uploaded_dir.glob("Channel_*.csv")))
    if THERMAL_REFERENCE_DIR.is_dir():
        candidate_paths.extend(sorted(THERMAL_REFERENCE_DIR.glob("Channel_*.csv")))
    if not candidate_paths:
        return None
    candidate_paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidate_paths[0]


def build_accurate_thermal_reference(source_path: Path, program_id: str) -> dict[str, Any]:
    rows = load_tabular_rows(source_path)
    if not rows:
        raise ValueError("The accurate thermal CSV does not contain readable rows.")

    field_names = list(rows[0].keys())
    resolved_time_field = choose_field_name(field_names, "Time", TIME_FIELD_CANDIDATES)
    if resolved_time_field is None:
        raise ValueError("The accurate thermal CSV does not contain a usable Time field.")

    resolved_value_field = choose_field_name(field_names, "G_High", THERMAL_VALUE_CANDIDATES)
    if resolved_value_field is None:
        raise ValueError("The accurate thermal CSV does not contain a usable G_High field.")

    resolved_tspan_field = choose_field_name(field_names, "Tspan(s)", THERMAL_TSPAN_CANDIDATES)
    extra_numeric_fields = {resolved_tspan_field: "tspan_s"} if resolved_tspan_field else {}
    points = build_series_points(
        rows,
        resolved_time_field,
        resolved_value_field,
        "g_high",
        time_mode="absolute",
        extra_numeric_fields=extra_numeric_fields,
    )
    if not points:
        raise ValueError("The accurate thermal CSV does not contain usable thermal samples.")

    values = [point["g_high"] for point in points]
    return {
        "program_id": program_id,
        "sensor_type": "thermal-camera",
        "source_kind": "reference",
        "source_file": source_path.name,
        "time_field": resolved_time_field,
        "time_mode": "absolute",
        "value_field": resolved_value_field,
        "value_label": resolved_value_field,
        "start_time": points[0]["time"],
        "end_time": points[-1]["time"],
        "sample_count": len(points),
        "g_high_min": round(min(values), 4),
        "g_high_max": round(max(values), 4),
        "g_high_avg": round(sum(values) / len(values), 4),
        "thermal_trace": downsample_points(points, SENSOR_DISPLAY_LIMIT),
        "full_trace": points,
    }


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
    if not thermal_index_by_signature:
        return edge_payload

    probe_points = select_alignment_probe_points(candidate_edge_points, thermal_frequency)
    if not probe_points:
        return edge_payload

    offset_bins: dict[float, list[float]] = defaultdict(list)
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
            offset_bins[round(exact_offset, 2)].append(exact_offset)

    if not offset_bins:
        return edge_payload

    thermal_tspans = [float(point["tspan_s"]) for point in candidate_thermal_points]
    candidate_offsets: list[float] = []
    for _, exact_offsets in sorted(offset_bins.items(), key=lambda item: len(item[1]), reverse=True)[:12]:
        candidate_offsets.append(float(median(exact_offsets)))

    best_offset_s: float | None = None
    best_mae = float("inf")
    best_exact_matches = -1
    for offset_s in candidate_offsets:
        mae, exact_matches = evaluate_edge_thermal_offset(
            candidate_edge_points,
            candidate_thermal_points,
            thermal_tspans,
            offset_s,
        )
        if exact_matches > best_exact_matches or (exact_matches == best_exact_matches and mae < best_mae):
            best_offset_s = offset_s
            best_mae = mae
            best_exact_matches = exact_matches

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
    edge_payload["trajectory_summaries"] = build_edge_trajectory_summaries(edge_payload["full_trace"])
    if edge_payload["full_trace"]:
        edge_payload["start_time"] = edge_payload["full_trace"][0]["time"]
        edge_payload["end_time"] = edge_payload["full_trace"][-1]["time"]
    edge_payload["embedded_thermal"] = thermal_reference
    edge_payload["accurate_time_mapping"] = {
        "source_file": thermal_reference.get("source_file"),
        "mapping_method": "g_high_sequence_match",
        "offset_s": round(refined_offset_s, 3),
        "scale": 1.0,
        "matched_samples": matched_samples,
        "total_samples": len(candidate_edge_points),
        "mean_absolute_g_high_error": round(best_mae, 6) if best_mae != float("inf") else None,
    }
    return edge_payload


def build_edge_dataset(
    source_path: Path,
    program_id: str,
    time_field: str | None = None,
    value_field: str | None = None,
    source_kind: str = "uploaded",
) -> dict[str, Any]:
    if source_path.suffix.lower() == ".json":
        raw_payload = read_json(source_path)
        if is_sinumerik_edge_payload(raw_payload):
            points, resolved_value_field, available_value_fields, cycle_time_ms, machine_events = (
                build_sinumerik_edge_points(raw_payload, value_field=value_field)
            )
            if not points:
                raise ValueError("Edge JSON 解析後沒有有效的高頻取樣點。")

            values = [point["value"] for point in points]
            return {
                "program_id": program_id,
                "sensor_type": "edge-sensor",
                "source_kind": source_kind,
                "source_file": source_path.name,
                "time_field": "Time",
                "time_mode": "absolute",
                "value_field": resolved_value_field,
                "value_label": resolved_value_field,
                "start_time": points[0]["time"],
                "end_time": points[-1]["time"],
                "sample_count": len(points),
                "value_min": round(min(values), 4),
                "value_max": round(max(values), 4),
                "value_avg": round(sum(values) / len(values), 4),
                "edge_trace": downsample_points(points, SENSOR_DISPLAY_LIMIT),
                "full_trace": points,
                "available_value_fields": available_value_fields,
                "machine_events": machine_events,
                "edge_format": "sinumerik-hf-json",
                "sample_interval_ms": cycle_time_ms,
            }

    rows = load_tabular_rows(source_path)
    if not rows:
        raise ValueError("Edge 資料檔案沒有可讀取的資料列。")

    field_names = list(rows[0].keys())
    resolved_time_field, time_mode = resolve_time_field_and_mode(field_names, time_field)
    if resolved_time_field is None:
        raise ValueError("Edge 資料找不到可用的時間欄位。")

    coordinate_fields = detect_coordinate_fields(field_names)
    trajectory_field = choose_field_name(field_names, None, EDGE_TRAJECTORY_FIELD_CANDIDATES)
    g_high_field = choose_field_name(field_names, None, THERMAL_VALUE_CANDIDATES)
    align_error_field = choose_field_name(field_names, None, EDGE_ALIGN_ERROR_FIELD_CANDIDATES)

    exclude_names = {normalize_field_name(resolved_time_field)} | EDGE_IGNORED_VALUE_FIELDS
    for field_name in coordinate_fields.values():
        if field_name:
            exclude_names.add(normalize_field_name(field_name))
    if trajectory_field:
        exclude_names.add(normalize_field_name(trajectory_field))
    if g_high_field:
        exclude_names.add(normalize_field_name(g_high_field))

    numeric_fields = detect_numeric_fields(rows, exclude_names)
    if value_field:
        resolved_value_field = choose_field_name(field_names, value_field)
        if resolved_value_field is None:
            raise ValueError("找不到指定的 Edge 數值欄位。")
    else:
        if align_error_field and align_error_field in numeric_fields:
            resolved_value_field = align_error_field
        elif numeric_fields:
            resolved_value_field = numeric_fields[0]
        elif g_high_field:
            resolved_value_field = g_high_field
        elif coordinate_fields.get("z"):
            resolved_value_field = coordinate_fields["z"]
        else:
            raise ValueError("Edge 資料找不到可用的數值欄位。")

    extra_numeric_fields: dict[str, str] = {}
    if coordinate_fields.get("x"):
        extra_numeric_fields[coordinate_fields["x"]] = "machine_x_mm"
    if coordinate_fields.get("y"):
        extra_numeric_fields[coordinate_fields["y"]] = "machine_y_mm"
    if coordinate_fields.get("z"):
        extra_numeric_fields[coordinate_fields["z"]] = "machine_z_mm"
    if g_high_field:
        extra_numeric_fields[g_high_field] = "g_high"
    if align_error_field:
        extra_numeric_fields[align_error_field] = "align_error_ms"

    extra_text_fields: dict[str, str] = {}
    if trajectory_field:
        extra_text_fields[trajectory_field] = "trajectory_id"

    points = build_series_points(
        rows,
        resolved_time_field,
        resolved_value_field,
        "value",
        time_mode=time_mode,
        extra_numeric_fields=extra_numeric_fields,
        extra_text_fields=extra_text_fields,
    )
    if not points:
        raise ValueError("Edge 資料解析後沒有有效的時間序列點。")

    values = [point["value"] for point in points]
    embedded_thermal = None
    if g_high_field:
        thermal_points = build_series_points(
            rows,
            resolved_time_field,
            g_high_field,
            "g_high",
            time_mode=time_mode,
        )
        if thermal_points:
            thermal_values = [point["g_high"] for point in thermal_points]
            embedded_thermal = {
                "program_id": program_id,
                "sensor_type": "thermal-camera",
                "source_kind": source_kind,
                "source_file": source_path.name,
                "time_field": resolved_time_field,
                "time_mode": time_mode,
                "value_field": g_high_field,
                "start_time": thermal_points[0]["time"],
                "end_time": thermal_points[-1]["time"],
                "sample_count": len(thermal_points),
                "g_high_min": round(min(thermal_values), 4),
                "g_high_max": round(max(thermal_values), 4),
                "g_high_avg": round(sum(thermal_values) / len(thermal_values), 4),
                "thermal_trace": downsample_points(thermal_points, SENSOR_DISPLAY_LIMIT),
                "full_trace": thermal_points,
            }

    return {
        "program_id": program_id,
        "sensor_type": "edge-sensor",
        "source_kind": source_kind,
        "source_file": source_path.name,
        "time_field": resolved_time_field,
        "time_mode": time_mode,
        "value_field": resolved_value_field,
        "value_label": resolved_value_field,
        "start_time": points[0]["time"],
        "end_time": points[-1]["time"],
        "sample_count": len(points),
        "value_min": round(min(values), 4),
        "value_max": round(max(values), 4),
        "value_avg": round(sum(values) / len(values), 4),
        "edge_trace": downsample_points(points, SENSOR_DISPLAY_LIMIT),
        "full_trace": points,
        "available_value_fields": numeric_fields,
        "machine_events": [],
        "sample_interval_ms": None,
        "edge_format": "generic-timeseries",
        "coordinate_fields": coordinate_fields,
        "has_machine_coordinates": bool(
            coordinate_fields.get("x") and coordinate_fields.get("y") and coordinate_fields.get("z")
        ),
        "trajectory_field": trajectory_field,
        "trajectory_summaries": build_edge_trajectory_summaries(points),
        "embedded_thermal": embedded_thermal,
    }


def load_saved_thermal_data(output_dir: Path, program_id: str) -> dict[str, Any]:
    thermal_path = output_dir / THERMAL_DATA_FILENAME
    if thermal_path.is_file():
        return normalize_loaded_thermal_payload(read_json(thermal_path), program_id, "uploaded")

    if output_dir.name in DEMO_OUTPUT_NAMES and THERMAL_EXAMPLE_PATH.is_file():
        return normalize_loaded_thermal_payload(read_json(THERMAL_EXAMPLE_PATH), program_id, "example")

    return make_empty_thermal_data(program_id)


def repair_saved_edge_payload(
    output_dir: Path,
    edge_path: Path,
    payload: Any,
    program_id: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if str(payload.get("edge_format") or "") != "sinumerik-hf-json":
        return None
    if payload.get("machine_events"):
        return None

    uploaded_dir = output_dir / "uploaded_sources"
    if not uploaded_dir.is_dir():
        return None

    source_name = Path(str(payload.get("source_file") or "")).name
    candidate_paths: list[Path] = []
    if source_name:
        direct_path = uploaded_dir / source_name
        if direct_path.is_file():
            candidate_paths.append(direct_path)

        source_stem = Path(source_name).stem
        candidate_paths.extend(
            path
            for path in sorted(uploaded_dir.glob(f"{source_stem}*.json"))
            if path not in candidate_paths
        )

    candidate_paths.extend(
        path for path in sorted(uploaded_dir.glob("*.json")) if path not in candidate_paths
    )

    value_field = str(payload.get("value_field") or "").strip() or None
    source_kind = str(payload.get("source_kind") or "uploaded")

    for candidate_path in candidate_paths:
        try:
            repaired_edge = build_edge_dataset(
                candidate_path,
                program_id,
                value_field=value_field,
                source_kind=source_kind,
            )
        except (FileNotFoundError, ValueError, TypeError):
            continue

        if repaired_edge.get("machine_events"):
            write_json(edge_path, repaired_edge)
            return repaired_edge

    return None


def load_saved_edge_data(output_dir: Path, program_id: str) -> dict[str, Any]:
    edge_path = output_dir / EDGE_DATA_FILENAME
    if edge_path.is_file():
        raw_payload = read_json(edge_path)
        repaired_payload = repair_saved_edge_payload(output_dir, edge_path, raw_payload, program_id)
        if repaired_payload is not None:
            return repaired_payload
        return normalize_loaded_edge_payload(raw_payload, program_id, "uploaded")
    return make_empty_edge_data(program_id)


def resolve_effective_thermal_data(
    thermal: dict[str, Any],
    edge: dict[str, Any],
    program_id: str,
) -> dict[str, Any]:
    if thermal.get("sample_count", 0):
        return thermal

    embedded_thermal = edge.get("embedded_thermal")
    if isinstance(embedded_thermal, dict) and embedded_thermal.get("sample_count", 0):
        return normalize_loaded_thermal_payload(
            embedded_thermal,
            program_id,
            str(edge.get("source_kind") or "embedded"),
        )

    return thermal


def make_empty_recorder_timing() -> dict[str, Any]:
    return {
        "available": False,
        "message": "No recorder timing JSON was found.",
        "source_file": None,
        "job_description": [],
        "cycle_time_ms": None,
        "initial_time": None,
        "initial_counter": None,
        "g4_event": None,
        "laser_on_event": None,
        "m30_event": None,
        "g4_to_m30_ms": None,
        "g4_to_laser_on_ms": None,
        "laser_on_to_m30_ms": None,
        "g4_to_m30_label": "-",
        "g4_to_laser_on_label": "-",
        "laser_on_to_m30_label": "-",
    }


def find_recorder_timing_source(output_dir: Path) -> Path | None:
    uploaded_dir = output_dir / "uploaded_sources"
    candidate_paths: list[Path] = []
    if uploaded_dir.is_dir():
        candidate_paths.extend(sorted(uploaded_dir.glob("sample_job*.json")))
    if RECORDER_JSON_DIR.is_dir():
        candidate_paths.extend(sorted(RECORDER_JSON_DIR.glob("sample_job*.json")))
    if not candidate_paths:
        return None
    candidate_paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidate_paths[0]


def build_recorder_timing_data(source_path: Path | None) -> dict[str, Any]:
    if source_path is None or not source_path.is_file():
        return make_empty_recorder_timing()

    try:
        payload = read_json(source_path)
    except Exception as exc:  # pragma: no cover - defensive
        empty = make_empty_recorder_timing()
        empty["message"] = f"Failed to read recorder JSON: {exc}"
        return empty

    if not is_sinumerik_edge_payload(payload):
        empty = make_empty_recorder_timing()
        empty["message"] = "The recorder JSON is not in the expected SINUMERIK HF format."
        empty["source_file"] = source_path.name
        return empty

    header = payload.get("Header") or {}
    body = payload.get("Payload") or []
    try:
        cycle_time_ms = float(header.get("CycleTimeMs", 2) or 2)
    except (TypeError, ValueError):
        cycle_time_ms = 2.0
    if cycle_time_ms <= 0:
        cycle_time_ms = 2.0

    anchors: dict[int, datetime] = {}
    initial = header.get("Initial")
    if isinstance(initial, dict):
        try:
            initial_counter = int(initial.get("HFProbeCounter"))
            initial_time = parse_timestamp_value(initial.get("Time"))
            anchors[initial_counter] = initial_time
        except (TypeError, ValueError):
            initial_counter = None
            initial_time = None
    else:
        initial_counter = None
        initial_time = None

    block_event_count = 0
    for item in body:
        if not isinstance(item, dict):
            continue
        timestamp_block = item.get("HFTimestamp")
        if isinstance(timestamp_block, dict):
            try:
                anchor_counter = int(timestamp_block.get("HFProbeCounter"))
                anchor_time = parse_timestamp_value(timestamp_block.get("Time"))
            except (TypeError, ValueError):
                anchor_counter = None
                anchor_time = None
            if anchor_counter is not None and anchor_time is not None:
                anchors[anchor_counter] = anchor_time
        if isinstance(item.get("HFBlockEvent"), dict):
            block_event_count += 1

    if not anchors:
        empty = make_empty_recorder_timing()
        empty["message"] = "The recorder JSON does not contain usable timing anchors."
        empty["source_file"] = source_path.name
        return empty

    sorted_anchors = sorted(anchors.items(), key=lambda item: item[0])
    machine_events = extract_machine_events_from_edge_payload(body, sorted_anchors, cycle_time_ms)
    g4_event = next((event for event in machine_events if event.get("event_type") == "trigger_on"), None)
    laser_on_event = next((event for event in machine_events if event.get("event_type") == "laser_on"), None)
    m30_event = next((event for event in machine_events if event.get("event_type") == "trigger_off"), None)

    def duration_between(first_event: dict[str, Any] | None, second_event: dict[str, Any] | None) -> int | None:
        if not first_event or not second_event:
            return None
        try:
            return int(second_event["timestamp_ms"]) - int(first_event["timestamp_ms"])
        except (KeyError, TypeError, ValueError):
            return None

    g4_to_m30_ms = duration_between(g4_event, m30_event)
    g4_to_laser_on_ms = duration_between(g4_event, laser_on_event)
    laser_on_to_m30_ms = duration_between(laser_on_event, m30_event)

    return {
        "available": True,
        "message": "Recorder timing was loaded successfully.",
        "source_file": source_path.name,
        "job_description": header.get("JobDescription") or [],
        "cycle_time_ms": cycle_time_ms,
        "initial_time": format_timestamp(initial_time) if initial_time is not None else None,
        "initial_counter": initial_counter,
        "block_event_count": block_event_count,
        "g4_event": g4_event,
        "laser_on_event": laser_on_event,
        "m30_event": m30_event,
        "g4_to_m30_ms": g4_to_m30_ms,
        "g4_to_laser_on_ms": g4_to_laser_on_ms,
        "laser_on_to_m30_ms": laser_on_to_m30_ms,
        "g4_to_m30_label": format_duration_label_from_ms(g4_to_m30_ms),
        "g4_to_laser_on_label": format_duration_label_from_ms(g4_to_laser_on_ms),
        "laser_on_to_m30_label": format_duration_label_from_ms(laser_on_to_m30_ms),
    }


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
    hot_machine_point = find_first_hot_edge_point(edge_points) or first_machine_point
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
        "offset_method": "first-hot-point-to-first-deposit" if process_offset else "first-sample-to-first-anchor",
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
        "toolpath_preposition_anchor": first_travel_anchor,
        "toolpath_process_anchor": first_deposit_anchor,
        "work_trace": downsample_points(transformed_points, ALIGNMENT_DISPLAY_LIMIT),
        "trajectory_summaries": trajectory_summaries,
        "trajectory_count": len(trajectory_summaries),
        "nc_reference_trace": downsample_points(nc_reference_trace, ALIGNMENT_DISPLAY_LIMIT),
    }


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
    if len(thermal_points) < 5:
        return None

    raw_values = [float(point["g_high"]) for point in thermal_points]
    if not raw_values:
        return None

    half_window = 2
    smoothed_values: list[float] = []
    for index in range(len(raw_values)):
        start = max(0, index - half_window)
        end = min(len(raw_values), index + half_window + 1)
        smoothed_values.append(sum(raw_values[start:end]) / (end - start))

    baseline_count = min(max(24, len(smoothed_values) // 25), 240)
    baseline_values = smoothed_values[:baseline_count]
    baseline = median_value(baseline_values)
    peak_value = percentile_value(smoothed_values, 0.98)
    rise_margin = max((peak_value - baseline) * 0.08, 1.0)
    threshold = baseline + rise_margin

    for index in range(1, len(smoothed_values) - 1):
        current = smoothed_values[index]
        previous = smoothed_values[index - 1]
        next_value = smoothed_values[index + 1]
        if current < threshold:
            continue
        if current <= previous:
            continue
        if next_value < threshold:
            continue

        point = thermal_points[index]
        return {
            "label": "熱像升溫起點",
            "time": point["time"],
            "timestamp_ms": int(point["timestamp_ms"]),
            "g_high": round(float(point["g_high"]), 4),
            "baseline": round(baseline, 4),
            "threshold": round(threshold, 4),
        }

    return None


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


def build_alignment_data(thermal: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
    thermal_points = thermal.get("full_trace") or []
    edge_points = edge.get("full_trace") or []
    edge_label = edge.get("value_label", "Edge 值")
    time_mode = "relative_ms" if (
        str(thermal.get("time_mode") or "") == "relative_ms"
        and str(edge.get("time_mode") or "") == "relative_ms"
    ) else "absolute"

    if not thermal_points and not edge_points:
        return {
            "available": False,
            "message": "尚未上傳熱像與 Edge 時序資料。",
            "trace": [],
            "sample_count": 0,
            "edge_label": edge_label,
        }
    if not thermal_points:
        return {
            "available": False,
            "message": "尚未上傳熱像時間序列資料。",
            "trace": [],
            "sample_count": 0,
            "edge_label": edge_label,
        }
    if not edge_points:
        return {
            "available": False,
            "message": "尚未上傳 Edge 時序資料。",
            "trace": [],
            "sample_count": 0,
            "edge_label": edge_label,
        }

    machine_feature = find_first_machine_laser_on_feature(edge)
    thermal_feature = detect_thermal_rise_feature(thermal_points)
    auto_offset_ms = 0
    method = "timestamp-overlap"
    method_label = "時間戳最近點"
    message = "已根據原始時間戳記建立熱像與 Edge 比對。"

    if machine_feature is not None and thermal_feature is not None:
        auto_offset_ms = int(machine_feature["timestamp_ms"]) - int(thermal_feature["timestamp_ms"])
        method = "feature-laser-onset"
        method_label = "第一個 LASER ON 對第一個熱像升溫起點"
        message = "已用機台 LASER ON 與熱像升溫特徵建立自動對齊。"

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

    if not raw_pairs and not aligned_pairs:
        return {
            "available": False,
            "message": "熱像與 Edge 的時間範圍沒有重疊，暫時無法建立比較圖。",
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
        "machine_feature": machine_feature,
        "thermal_feature": thermal_feature,
        "raw_pair_count": len(raw_pairs),
        "aligned_pair_count": len(aligned_pairs),
        "raw_start_time": thermal_points[0]["time"],
        "raw_end_time": thermal_points[-1]["time"],
        "aligned_start_time": aligned_start_time,
        "aligned_end_time": aligned_end_time,
    }


def build_layer_records(
    nc_blocks: list[dict[str, Any]],
    toolpath_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    points_by_layer: dict[int, list[dict[str, Any]]] = defaultdict(list)
    segments_by_layer: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for block in nc_blocks:
        if block.get("block_type") != "motion":
            continue
        if "x_mm" not in block or "y_mm" not in block or "z_mm" not in block:
            continue

        layer_index = int(block.get("layer_index") or 0)
        if layer_index <= 0:
            continue

        points_by_layer[layer_index].append(
            {
                "line_no": int(block["line_no"]),
                "command": block.get("command", ""),
                "x_mm": float(block["x_mm"]),
                "y_mm": float(block["y_mm"]),
                "z_mm": float(block["z_mm"]),
                "a_deg": float(block.get("a_deg", 0.0)),
                "c_deg": float(block.get("c_deg", 0.0)),
                "feed_rate_mm_min": float(block.get("feed_rate_mm_min", 0.0))
                if "feed_rate_mm_min" in block
                else None,
                "laser_on": bool(block.get("laser_on", False)),
                "powder_supply_on": bool(block.get("powder_supply_on", False)),
            }
        )

    for segment in toolpath_segments:
        layer_index = int(segment.get("layer_index") or 0)
        if layer_index <= 0:
            continue

        segments_by_layer[layer_index].append(
            {
                "segment_id": segment.get("segment_id"),
                "parameter_event_id": segment.get("parameter_event_id"),
                "path_type": segment.get("path_type", "unknown"),
                "motion_code": segment.get("motion_code"),
                "source_range": segment.get("source_range"),
                "start_line_no": segment.get("start_line_no"),
                "end_line_no": segment.get("end_line_no"),
                "point_count": segment.get("point_count", 0),
                "feed_rate_mm_min": segment.get("feed_rate_mm_min"),
                "laser_on": bool(segment.get("laser_on", False)),
                "powder_supply_on": bool(segment.get("powder_supply_on", False)),
                "work_offset": segment.get("work_offset"),
                "transform_mode": segment.get("transform_mode"),
                "z_layer_mm": segment.get("z_layer_mm"),
                "start_point": segment.get("start_point"),
                "end_point": segment.get("end_point"),
                "bounding_box": segment.get("bounding_box"),
            }
        )

    layers: list[dict[str, Any]] = []
    layer_ids = sorted(set(points_by_layer) | set(segments_by_layer))
    for layer_index in layer_ids:
        raw_points = sorted(points_by_layer.get(layer_index, []), key=lambda item: item["line_no"])
        raw_segments = sorted(
            segments_by_layer.get(layer_index, []),
            key=lambda item: (item.get("start_line_no") or 0, item.get("segment_id") or ""),
        )

        points = raw_points
        segments = raw_segments
        line_start = None
        line_end = None
        z_level = None

        deposit_segments = [segment for segment in raw_segments if segment.get("path_type") == "deposit"]
        if deposit_segments:
            deposit_start_lines = [
                int(segment["start_line_no"])
                for segment in deposit_segments
                if segment.get("start_line_no") is not None
            ]
            deposit_end_lines = [
                int(segment["end_line_no"])
                for segment in deposit_segments
                if segment.get("end_line_no") is not None
            ]
            if deposit_start_lines and deposit_end_lines:
                line_start = min(deposit_start_lines)
                line_end = max(deposit_end_lines)
                points = [
                    point for point in raw_points if line_start <= int(point["line_no"]) <= line_end
                ]
                segments = [
                    segment
                    for segment in raw_segments
                    if (segment.get("start_line_no") is not None)
                    and (segment.get("end_line_no") is not None)
                    and line_start <= int(segment["start_line_no"]) <= int(segment["end_line_no"]) <= line_end
                ]

            deposit_z_levels = [
                float(segment["z_layer_mm"])
                for segment in deposit_segments
                if segment.get("z_layer_mm") is not None
            ]
            if deposit_z_levels:
                z_level = round(deposit_z_levels[0], 3)

        if points:
            xs = [point["x_mm"] for point in points]
            ys = [point["y_mm"] for point in points]
            z_values = [point["z_mm"] for point in points]
            bounds = {
                "x_min_mm": min(xs),
                "x_max_mm": max(xs),
                "y_min_mm": min(ys),
                "y_max_mm": max(ys),
                "z_min_mm": min(z_values),
                "z_max_mm": max(z_values),
            }
            if line_start is None:
                line_start = min(point["line_no"] for point in points)
            if line_end is None:
                line_end = max(point["line_no"] for point in points)
            if z_level is None:
                z_level = round(points[0]["z_mm"], 3)
        else:
            bounds = None

        layers.append(
            {
                "layer_index": layer_index,
                "z_level_mm": z_level,
                "line_range": {"start": line_start, "end": line_end},
                "event_line_range": {
                    "start": min((point["line_no"] for point in raw_points), default=None),
                    "end": max((point["line_no"] for point in raw_points), default=None),
                },
                "point_count": len(points),
                "segment_count": len(segments),
                "deposit_segment_count": sum(
                    1 for segment in segments if segment.get("path_type") == "deposit"
                ),
                "travel_segment_count": sum(
                    1 for segment in segments if segment.get("path_type") == "travel"
                ),
                "bounds": bounds,
                "motion_points": points,
                "segments": segments,
            }
        )

    return layers


def update_output_metadata_after_upload(
    output_dir: Path,
    original_filename: str,
) -> None:
    update_output_metadata_fields(output_dir, file_name=original_filename)


def update_run_manifest(entry: dict[str, Any]) -> None:
    manifest_path = OUTPUT_ROOT / "run-manifest.json"
    manifest: list[dict[str, Any]] = []
    if manifest_path.is_file():
        existing = read_json(manifest_path)
        if isinstance(existing, list):
            manifest = [item for item in existing if isinstance(item, dict)]

    output_dir = str(entry.get("output_dir") or "")
    manifest = [item for item in manifest if str(item.get("output_dir") or "") != output_dir]
    manifest.append(entry)
    write_json(manifest_path, manifest)


def safe_stem(name: str) -> str:
    stem = SAFE_NAME_RE.sub("_", Path(name).stem.strip()).strip("._")
    return stem or "upload"


def choose_unique_file_path(directory: Path, stem: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def choose_unique_generated_mpf_path(file_name: str) -> Path:
    normalized_name = Path(file_name or "edited_output.MPF").name
    suffix = Path(normalized_name).suffix or ".MPF"
    stem = safe_stem(normalized_name)
    GENERATED_MPF_ROOT.mkdir(parents=True, exist_ok=True)
    candidate = GENERATED_MPF_ROOT / f"{stem}{suffix}"
    counter = 1
    while candidate.exists() or (OUTPUT_ROOT / candidate.stem).exists():
        candidate = GENERATED_MPF_ROOT / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def normalize_mpf_file_name(value: str, fallback_stem: str = "edited_output") -> str:
    cleaned = Path(str(value or "").strip()).name
    if not cleaned:
        cleaned = f"{fallback_stem}.MPF"
    suffix = Path(cleaned).suffix
    if not suffix:
        cleaned = f"{cleaned}.MPF"
    elif suffix.lower() != ".mpf":
        cleaned = f"{Path(cleaned).stem}.MPF"
    return cleaned


def copy_file_if_exists(source_path: Path, destination_path: Path) -> bool:
    if not source_path.is_file():
        return False
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)
    return True


def update_output_metadata_fields(output_dir: Path, **fields: Any) -> None:
    filtered_fields = {
        key: value
        for key, value in fields.items()
        if value is not None and value != ""
    }
    if not filtered_fields:
        return

    for file_name in ("NC-file.json", "summary.json"):
        payload_path = output_dir / file_name
        if not payload_path.is_file():
            continue
        payload = read_json(payload_path)
        if not isinstance(payload, dict):
            continue
        payload.update(filtered_fields)
        write_json(payload_path, payload)


def stage_source_mpf_text(
    output_dir: Path,
    file_name: str,
    mpf_text: str,
) -> Path:
    source_dir = output_dir / SOURCE_MPF_DIRNAME
    source_dir.mkdir(parents=True, exist_ok=True)
    target_name = normalize_mpf_file_name(file_name, fallback_stem=output_dir.name)
    target_path = source_dir / target_name
    write_text_file(target_path, mpf_text)
    update_output_metadata_fields(
        output_dir,
        editable_source_file=target_path.name,
        editable_source_origin="staged",
    )
    return target_path


def stage_source_mpf_copy(
    output_dir: Path,
    source_path: Path,
    original_file_name: str | None = None,
) -> Path:
    source_dir = output_dir / SOURCE_MPF_DIRNAME
    source_dir.mkdir(parents=True, exist_ok=True)
    target_name = normalize_mpf_file_name(
        original_file_name or source_path.name,
        fallback_stem=source_path.stem,
    )
    target_path = source_dir / target_name
    shutil.copy2(source_path, target_path)
    update_output_metadata_fields(
        output_dir,
        editable_source_file=target_path.name,
        editable_source_origin="copied",
    )
    return target_path


def find_uploaded_mpf_by_name(file_name: str) -> Path | None:
    upload_dir = UPLOAD_ROOT / "mpf"
    if not upload_dir.is_dir():
        return None
    candidates = [
        path
        for path in upload_dir.iterdir()
        if path.is_file() and path.name.lower() == file_name.lower()
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)[0]


def find_output_source_mpf(output_dir: Path, nc_file: dict[str, Any]) -> Path | None:
    stored_name = str(nc_file.get("editable_source_file") or "").strip()
    if stored_name:
        candidate = output_dir / SOURCE_MPF_DIRNAME / Path(stored_name).name
        if candidate.is_file():
            return candidate

    source_dir = output_dir / SOURCE_MPF_DIRNAME
    if source_dir.is_dir():
        files = sorted(
            [
                path
                for path in source_dir.iterdir()
                if path.is_file() and path.suffix.lower() == ".mpf"
            ],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if files:
            return files[0]

    file_name = str(nc_file.get("file_name") or "").strip()
    if file_name:
        project_candidate = BASE_DIR / Path(file_name).name
        if project_candidate.is_file():
            return project_candidate

        uploaded_candidate = find_uploaded_mpf_by_name(Path(file_name).name)
        if uploaded_candidate is not None:
            return uploaded_candidate

    return None


def load_output_source_mpf(output_name: str | None) -> dict[str, Any]:
    output_dir = discover_output_dir(output_name)
    nc_file = read_json(output_dir / "NC-file.json")
    if not isinstance(nc_file, dict):
        raise FileNotFoundError("找不到 MPF 來源資訊。")

    source_path = find_output_source_mpf(output_dir, nc_file)
    if source_path is None:
        raise FileNotFoundError("目前找不到可編輯的 MPF 原始檔。")

    text = read_text_any_encoding(source_path)
    return {
        "ok": True,
        "output_name": output_dir.name,
        "file_name": source_path.name,
        "line_count": text.count("\n") + (1 if text else 0),
        "text": text,
        "download_url": f"/api/download-output-mpf?output_name={quote(output_dir.name)}",
    }


def clone_sensor_payloads(source_output_dir: Path, target_output_dir: Path, program_id: str) -> None:
    source_nc_file = read_json(source_output_dir / "NC-file.json")
    if not isinstance(source_nc_file, dict):
        return
    source_program_id = str(source_nc_file.get("program_id") or "")

    thermal = load_saved_thermal_data(source_output_dir, source_program_id)
    if thermal.get("sample_count", 0):
        thermal["program_id"] = program_id
        write_json(target_output_dir / THERMAL_DATA_FILENAME, thermal)

    edge = load_saved_edge_data(source_output_dir, source_program_id)
    if edge.get("sample_count", 0):
        edge["program_id"] = program_id
        write_json(target_output_dir / EDGE_DATA_FILENAME, edge)


def process_mpf_text_to_new_output(
    mpf_text: str,
    preferred_file_name: str,
    source_output_name: str | None = None,
    source_variant: str = "edited-preview",
) -> dict[str, Any]:
    normalized_name = normalize_mpf_file_name(preferred_file_name)
    generated_path = choose_unique_generated_mpf_path(normalized_name)
    write_text_file(generated_path, mpf_text)

    from parse_mpf_to_json import process_file

    result_entry = process_file(generated_path, OUTPUT_ROOT, validate=False)
    output_dir = OUTPUT_ROOT / str(result_entry["output_dir"])

    if source_output_name:
        try:
            source_output_dir = discover_output_dir(source_output_name)
            source_nc_file = read_json(source_output_dir / "NC-file.json")
            if not isinstance(source_nc_file, dict):
                source_nc_file = {}
            target_nc_file = read_json(output_dir / "NC-file.json")
            target_program_id = ""
            if isinstance(target_nc_file, dict):
                target_program_id = str(target_nc_file.get("program_id") or "")
            staged_source = find_output_source_mpf(source_output_dir, source_nc_file)
            if staged_source is not None and staged_source.resolve() != generated_path.resolve():
                clone_sensor_payloads(source_output_dir, output_dir, target_program_id)
        except FileNotFoundError:
            pass

    stage_source_mpf_text(output_dir, generated_path.name, mpf_text)
    update_output_metadata_fields(
        output_dir,
        file_name=generated_path.name,
        source_variant=source_variant,
        parent_output_name=source_output_name or "",
    )

    if result_entry.get("summary") and isinstance(result_entry["summary"], dict):
        result_entry["summary"]["file_name"] = generated_path.name
        result_entry["summary"]["source_variant"] = source_variant
        if source_output_name:
            result_entry["summary"]["parent_output_name"] = source_output_name
    update_run_manifest(result_entry)

    return {
        "result_entry": result_entry,
        "output_dir": output_dir,
        "generated_path": generated_path,
    }


def handle_preview_request(payload: dict[str, Any]) -> dict[str, Any]:
    source_output_name = str(payload.get("output_name") or "").strip() or None
    mpf_text = str(payload.get("mpf_text") or "")
    file_name = normalize_mpf_file_name(
        str(payload.get("file_name") or ""),
        fallback_stem=(source_output_name or "edited_preview"),
    )
    if not mpf_text.strip():
        raise ValueError("MPF 內容不可為空白。")

    processed = process_mpf_text_to_new_output(
        mpf_text=mpf_text,
        preferred_file_name=file_name,
        source_output_name=source_output_name,
        source_variant="edited-preview",
    )
    output_dir = processed["output_dir"]
    generated_path = processed["generated_path"]
    return {
        "ok": True,
        "message": f"已建立新的預覽版本：{output_dir.name}",
        "selected_output_name": output_dir.name,
        "output_name": output_dir.name,
        "file_name": generated_path.name,
        "download_url": f"/api/download-output-mpf?output_name={quote(output_dir.name)}",
    }


def handle_export_request(payload: dict[str, Any]) -> dict[str, Any]:
    mpf_text = str(payload.get("mpf_text") or "")
    source_output_name = str(payload.get("output_name") or "").strip()
    requested_name = normalize_mpf_file_name(
        str(payload.get("file_name") or ""),
        fallback_stem=(source_output_name or "exported_mpf"),
    )
    if not mpf_text.strip():
        raise ValueError("MPF 內容不可為空白。")

    export_path = choose_unique_file_path(
        EXPORTED_MPF_ROOT,
        safe_stem(Path(requested_name).stem),
        ".MPF",
    )
    write_text_file(export_path, mpf_text)
    return {
        "ok": True,
        "message": f"新 MPF 已輸出到 {export_path}",
        "file_name": export_path.name,
        "saved_path": str(export_path),
        "download_url": f"/api/download-exported-mpf?file_name={quote(export_path.name)}",
    }

def save_uploaded_file(field_item: cgi.FieldStorage, subdirectory: str) -> Path:
    original_name = Path(str(field_item.filename or "upload.bin")).name
    suffix = Path(original_name).suffix or ".bin"
    stem = safe_stem(original_name)
    destination = choose_unique_file_path(UPLOAD_ROOT / subdirectory, stem, suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        shutil.copyfileobj(field_item.file, handle)
    return destination


def save_sensor_copy_to_output(upload_path: Path, output_dir: Path) -> Path:
    sensor_dir = output_dir / "uploaded_sources"
    sensor_dir.mkdir(parents=True, exist_ok=True)
    destination = choose_unique_file_path(sensor_dir, safe_stem(upload_path.name), upload_path.suffix)
    shutil.copy2(upload_path, destination)
    return destination


def get_form_value(form: cgi.FieldStorage, key: str) -> str:
    if key not in form:
        return ""
    item = form[key]
    if isinstance(item, list):
        item = item[0]
    return str(getattr(item, "value", "") or "").strip()


def get_uploaded_file_item(form: cgi.FieldStorage, key: str) -> cgi.FieldStorage | None:
    if key not in form:
        return None
    item = form[key]
    if isinstance(item, list):
        item = item[0]
    if not getattr(item, "filename", None):
        return None
    return item


def handle_upload_request(form: cgi.FieldStorage) -> dict[str, Any]:
    mpf_item = get_uploaded_file_item(form, "mpf_file")
    thermal_item = get_uploaded_file_item(form, "thermal_file")
    edge_item = get_uploaded_file_item(form, "edge_file")
    target_output_name = get_form_value(form, "target_output_name")
    thermal_time_field = get_form_value(form, "thermal_time_field") or None
    thermal_value_field = get_form_value(form, "thermal_value_field") or None
    edge_time_field = get_form_value(form, "edge_time_field") or None
    edge_value_field = get_form_value(form, "edge_value_field") or None

    if all(item is None for item in (mpf_item, thermal_item, edge_item)):
        raise ValueError("請至少上傳一個 MPF、熱像或 Edge 資料檔。")

    messages: list[str] = []
    output_dir: Path | None = None
    result_entry: dict[str, Any] | None = None

    if mpf_item is not None:
        uploaded_mpf_path = save_uploaded_file(mpf_item, "mpf")
        from parse_mpf_to_json import process_file

        result_entry = process_file(uploaded_mpf_path, OUTPUT_ROOT, validate=False)
        output_dir = OUTPUT_ROOT / str(result_entry["output_dir"])
        update_output_metadata_after_upload(output_dir, Path(str(mpf_item.filename)).name)
        stage_source_mpf_copy(
            output_dir,
            uploaded_mpf_path,
            original_file_name=Path(str(mpf_item.filename)).name,
        )
        if result_entry.get("summary") and isinstance(result_entry["summary"], dict):
            result_entry["summary"]["file_name"] = Path(str(mpf_item.filename)).name
        update_run_manifest(result_entry)
        target_output_name = output_dir.name
        messages.append(f"MPF 已解析為 {target_output_name}")
    elif target_output_name:
        output_dir = discover_output_dir(target_output_name)

    if output_dir is None:
        raise ValueError("若未上傳 MPF，請先選擇要綁定感測資料的 MPF 輸出。")

    nc_file = read_json(output_dir / "NC-file.json")
    program_id = str(nc_file.get("program_id") or "")

    if thermal_item is not None:
        thermal_upload_path = save_uploaded_file(thermal_item, "thermal")
        thermal_source_path = save_sensor_copy_to_output(thermal_upload_path, output_dir)
        thermal_data = build_thermal_dataset(
            source_path=thermal_source_path,
            program_id=program_id,
            time_field=thermal_time_field,
            value_field=thermal_value_field,
            source_kind="uploaded",
        )
        write_json(output_dir / THERMAL_DATA_FILENAME, thermal_data)
        messages.append(f"熱像資料已綁定到 {target_output_name}")

    if edge_item is not None:
        edge_upload_path = save_uploaded_file(edge_item, "edge")
        edge_source_path = save_sensor_copy_to_output(edge_upload_path, output_dir)
        edge_data = build_edge_dataset(
            source_path=edge_source_path,
            program_id=program_id,
            time_field=edge_time_field,
            value_field=edge_value_field,
            source_kind="uploaded",
        )
        write_json(output_dir / EDGE_DATA_FILENAME, edge_data)
        messages.append(f"Edge 資料已綁定到 {target_output_name}")

    return {
        "ok": True,
        "message": "；".join(messages) if messages else "上傳完成。",
        "selected_output_name": target_output_name,
        "output_name": target_output_name,
    }


def build_dashboard_payload(output_name: str | None = None) -> dict[str, Any]:
    output_dir = discover_output_dir(output_name)
    available_outputs = list_available_outputs()
    nc_file = read_json(output_dir / "NC-file.json")
    summary = read_json(output_dir / "summary.json")
    nc_blocks = read_jsonl(output_dir / "NC-blocks.jsonl")
    toolpath_segments = read_jsonl(output_dir / "toolpath-segments.jsonl")
    parameter_events = read_jsonl(output_dir / "laser-process-parameters.jsonl")
    program_id = str(nc_file.get("program_id") or "")
    source_mpf_path = find_output_source_mpf(output_dir, nc_file if isinstance(nc_file, dict) else {})
    edge = load_saved_edge_data(output_dir, program_id)
    recorder_timing = build_recorder_timing_data(find_recorder_timing_source(output_dir))
    accurate_thermal_reference = None
    accurate_thermal_source = find_accurate_thermal_source(output_dir)
    if accurate_thermal_source is not None:
        try:
            accurate_thermal_reference = build_accurate_thermal_reference(accurate_thermal_source, program_id)
        except ValueError:
            accurate_thermal_reference = None
    if accurate_thermal_reference is not None:
        edge = match_edge_g_high_to_accurate_thermal(edge, accurate_thermal_reference)
    else:
        edge = apply_recorder_timing_mapping(edge, recorder_timing)

    thermal = resolve_effective_thermal_data(
        load_saved_thermal_data(output_dir, program_id),
        edge,
        program_id,
    )
    if accurate_thermal_reference is not None:
        thermal = normalize_loaded_thermal_payload(accurate_thermal_reference, program_id, "reference")
    alignment = build_alignment_data(thermal, edge)
    coordinate_alignment = build_coordinate_alignment_data(edge, toolpath_segments)

    layers = build_layer_records(nc_blocks, toolpath_segments)
    preview_events = [
        {
            "parameter_event_id": item.get("parameter_event_id"),
            "line_no": item.get("line_no"),
            "parameter_action": item.get("parameter_action"),
            "raw_command": item.get("raw_command"),
            "laser_power_w": item.get("laser_power_w"),
            "spot_diameter_mm": item.get("spot_diameter_mm"),
            "laser_on": bool(item.get("laser_on", False)),
            "powder_supply_on": bool(item.get("powder_supply_on", False)),
            "dwell_s": item.get("dwell_s"),
            "notes": item.get("notes"),
        }
        for item in parameter_events
    ]

    thermal_max = thermal.get("g_high_max")
    header_cards = [
        {"label": "機台", "value": nc_file.get("machine", "-")},
        {"label": "來源版本", "value": nc_file.get("source_variant", "-")},
        {"label": "層數", "value": str(summary.get("layer_count", 0))},
        {"label": "路徑段數", "value": str(summary.get("toolpath_segment_count", 0))},
        {
            "label": "熱像最大值",
            "value": "-" if thermal_max in (None, "") else f"{float(thermal_max):.2f}",
        },
    ]
    if edge.get("sample_count", 0):
        header_cards.append({"label": "Edge 取樣數", "value": str(edge.get("sample_count", 0))})
    if coordinate_alignment.get("available"):
        header_cards.append(
            {
                "label": "Work X Offset",
                "value": f'{float(coordinate_alignment["applied_offset_mm"]["x_mm"]):.2f}',
            }
        )

    return {
        "header": {
            "title": "DED成型儀表板",
            "subtitle": "在同一個畫面整合 NC 程式、刀具路徑、製程參數、熱像與 Edge 時序資料。",
            "program_id": nc_file.get("program_id"),
            "header_cards": header_cards,
        },
        "nc_file": nc_file,
        "summary": summary,
        "layers": layers,
        "parameter_events": preview_events,
        "thermal": strip_internal_sensor_fields(thermal),
        "edge": strip_internal_sensor_fields(edge),
        "alignment": alignment,
        "coordinate_alignment": coordinate_alignment,
        "recorder_timing": recorder_timing,
        "accurate_time_mapping": edge.get("accurate_time_mapping"),
        "output_name": output_dir.name,
        "available_outputs": available_outputs,
        "selected_output_name": output_dir.name,
        "upload_help": {
            "edge_example_url": "/static/edge_timeseries_example.csv",
            "edge_accept": ".csv,.json,.txt",
            "thermal_accept": ".csv,.json,.txt",
            "mpf_accept": ".mpf,.MPF",
        },
        "mpf_editor": {
            "source_available": source_mpf_path is not None,
            "source_file_name": source_mpf_path.name if source_mpf_path is not None else str(nc_file.get("file_name") or ""),
            "load_url": f"/api/mpf-source?output_name={quote(output_dir.name)}",
            "preview_url": "/api/preview-mpf",
            "export_url": "/api/export-mpf",
            "download_url": f"/api/download-output-mpf?output_name={quote(output_dir.name)}",
        },
    }


class DashboardRequestHandler(BaseHTTPRequestHandler):
    def send_localized_error(self, code: HTTPStatus, explain: str) -> None:
        self.send_error(code, explain=explain)

    def send_json_response(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_download_response(self, path: Path, download_name: str | None = None) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"找不到檔案：{path.name}")

        file_name = Path(download_name or path.name).name
        content = path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(path))
        encoded_name = quote(file_name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{encoded_name}",
        )
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length > 0 else b""
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON 內容格式不正確。")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/":
            self.serve_file(TEMPLATES_DIR / "final_dashboard.html", "text/html; charset=utf-8")
            return
        if route == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if route == "/api/dashboard-data":
            output_name = parse_qs(parsed.query).get("output_name", [None])[0]
            payload = build_dashboard_payload(output_name)
            self.send_json_response(HTTPStatus.OK, payload)
            return
        if route == "/api/mpf-source":
            try:
                output_name = parse_qs(parsed.query).get("output_name", [None])[0]
                payload = load_output_source_mpf(output_name)
                self.send_json_response(HTTPStatus.OK, payload)
            except FileNotFoundError as exc:
                self.send_json_response(HTTPStatus.NOT_FOUND, {"ok": False, "message": str(exc)})
            return
        if route == "/api/download-output-mpf":
            try:
                output_name = parse_qs(parsed.query).get("output_name", [None])[0]
                output_dir = discover_output_dir(output_name)
                nc_file = read_json(output_dir / "NC-file.json")
                if not isinstance(nc_file, dict):
                    raise FileNotFoundError("找不到 MPF 來源資訊。")
                source_path = find_output_source_mpf(output_dir, nc_file)
                if source_path is None:
                    raise FileNotFoundError("找不到目前輸出的 MPF 原始檔。")
                self.send_download_response(source_path, nc_file.get("file_name") or source_path.name)
            except FileNotFoundError as exc:
                self.send_json_response(HTTPStatus.NOT_FOUND, {"ok": False, "message": str(exc)})
            return
        if route == "/api/download-exported-mpf":
            try:
                file_name = normalize_mpf_file_name(
                    parse_qs(parsed.query).get("file_name", [""])[0],
                    fallback_stem="exported_mpf",
                )
                export_path = EXPORTED_MPF_ROOT / Path(file_name).name
                self.send_download_response(export_path, export_path.name)
            except FileNotFoundError as exc:
                self.send_json_response(HTTPStatus.NOT_FOUND, {"ok": False, "message": str(exc)})
            return
        if route == "/health":
            self.send_json_response(HTTPStatus.OK, {"status": "ok"})
            return
        if route.startswith("/static/"):
            relative = route.removeprefix("/static/")
            self.serve_static(relative)
            return
        self.send_localized_error(HTTPStatus.NOT_FOUND, "找不到頁面")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/preview-mpf":
            try:
                payload = handle_preview_request(self.read_json_body())
                self.send_json_response(HTTPStatus.OK, payload)
            except FileNotFoundError as exc:
                self.send_json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(exc)})
            except ValueError as exc:
                self.send_json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(exc)})
            except json.JSONDecodeError:
                self.send_json_response(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "message": "無法解析預覽請求 JSON。"},
                )
            except Exception as exc:  # noqa: BLE001
                self.send_json_response(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "message": f"預覽解析失敗：{exc}"},
                )
            return

        if parsed.path == "/api/export-mpf":
            try:
                payload = handle_export_request(self.read_json_body())
                self.send_json_response(HTTPStatus.OK, payload)
            except ValueError as exc:
                self.send_json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(exc)})
            except json.JSONDecodeError:
                self.send_json_response(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "message": "無法解析輸出請求 JSON。"},
                )
            except Exception as exc:  # noqa: BLE001
                self.send_json_response(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "message": f"輸出 MPF 失敗：{exc}"},
                )
            return

        if parsed.path != "/api/upload-data":
            self.send_json_response(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "message": "找不到 API。"},
            )
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type.lower():
            self.send_json_response(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "message": "請使用 multipart/form-data 方式上傳檔案。"},
            )
            return

        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type,
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                },
                keep_blank_values=True,
            )
            payload = handle_upload_request(form)
            self.send_json_response(HTTPStatus.OK, payload)
        except FileNotFoundError as exc:
            self.send_json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(exc)})
        except ValueError as exc:
            self.send_json_response(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self.send_json_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "message": f"上傳處理失敗：{exc}"},
            )

    def serve_static(self, relative_path: str) -> None:
        safe_path = Path(relative_path)
        file_path = (STATIC_DIR / safe_path).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.is_file():
            self.send_localized_error(HTTPStatus.NOT_FOUND, "找不到靜態檔案")
            return

        mime_type, _ = mimetypes.guess_type(str(file_path))
        self.serve_file(file_path, mime_type or "application/octet-stream")

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_localized_error(HTTPStatus.NOT_FOUND, f"找不到檔案：{path.name}")
            return

        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8010), DashboardRequestHandler)
    print("儀表板伺服器已啟動：http://127.0.0.1:8010")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
