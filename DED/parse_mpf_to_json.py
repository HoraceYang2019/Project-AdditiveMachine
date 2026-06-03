from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output"
SCHEMA_DIR = SCRIPT_DIR / "schema"
MOTION_CODES = {"G0", "G1", "G01", "G2", "G02", "G3", "G03"}
WORK_OFFSET_RE = re.compile(r"\bG5[4-9]\b", re.IGNORECASE)
G_CODE_RE = re.compile(r"(?<![A-Z0-9])G\d+\b", re.IGNORECASE)
M_CODE_RE = re.compile(r"/?M\d+\b", re.IGNORECASE)
AXIS_RE = re.compile(r"([XYZACF])([+-]?(?:\d+(?:\.\d*)?|\.\d+))\.?", re.IGNORECASE)
D_RE = re.compile(r"(?<![A-Z0-9])D(\d+)\b", re.IGNORECASE)
LASER_PARA_RE = re.compile(r"LASER_PARA\((.*?)\)", re.IGNORECASE)
SOURCE_ENCODINGS = ("utf-8", "utf-8-sig", "cp950", "mbcs", "latin-1")


@dataclass
class ModalState:
    x_mm: float | None = None
    y_mm: float | None = None
    z_mm: float | None = None
    a_deg: float | None = None
    c_deg: float | None = None
    feed_rate_mm_min: float | None = None
    modal_motion_code: str | None = None
    coordinate_plane: str = "G17"
    coordinate_mode: str = "G90"
    work_offset: str = "G54"
    path_control_mode: str = "G64"
    transform_mode: str = "TRAFOOF"
    d_number: int | None = None
    laser_on: bool = False
    powder_supply_on: bool = False
    safety_lock_on: bool = False
    active_parameter_event_id: str | None = None
    active_layer_index: int | None = None
    active_layer_z: float | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse Siemens-style MPF files into JSON and JSONL artifacts.",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="MPF files to parse. If omitted, all .MPF files in Final/ are processed.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where parsed outputs will be written.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate generated records against the local JSON schemas if jsonschema is available.",
    )
    return parser.parse_args()


def discover_inputs(raw_inputs: list[str]) -> list[Path]:
    if raw_inputs:
        return [Path(item).resolve() for item in raw_inputs]
    return sorted(SCRIPT_DIR.glob("*.MPF"))


def read_source_text(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in SOURCE_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return path.read_text()


def split_comment(line: str) -> tuple[str, str | None]:
    if ";" not in line:
        return line.strip(), None
    code, comment = line.split(";", 1)
    return code.strip(), comment.strip() or None


def has_dwell_code(g_codes: list[str]) -> bool:
    normalized = {item.upper() for item in g_codes}
    return "G4" in normalized or "G04" in normalized


def normalize_motion_code(code: str | None) -> str | None:
    if code is None:
        return None
    upper = code.upper()
    if upper == "G01":
        return "G1"
    if upper == "G00":
        return "G0"
    if upper == "G02":
        return "G2"
    if upper == "G03":
        return "G3"
    return upper


def extract_axis_values(code: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for axis, raw_value in AXIS_RE.findall(code):
        values[axis.upper()] = float(raw_value)
    return values


def current_point(state: ModalState) -> dict[str, float | None]:
    return {
        "x_mm": state.x_mm,
        "y_mm": state.y_mm,
        "z_mm": state.z_mm,
        "a_deg": state.a_deg,
        "c_deg": state.c_deg,
    }


def point_complete(point: dict[str, float | None]) -> bool:
    return all(point.get(key) is not None for key in ("x_mm", "y_mm", "z_mm", "a_deg", "c_deg"))


def clean_point(point: dict[str, float | None]) -> dict[str, float]:
    return {key: float(value) for key, value in point.items() if value is not None}


def block_type_for_line(
    line_no: int,
    raw_line: str,
    code: str,
    comment: str | None,
    explicit_motion_code: str | None,
    state: ModalState,
    axis_values: dict[str, float],
) -> str:
    stripped = raw_line.strip()
    upper_code = code.upper()

    if not stripped:
        return "misc"
    if stripped.startswith(";"):
        return "header" if line_no <= 8 else "comment"
    if "M30" in upper_code:
        return "end"
    if "/M01" in stripped.upper():
        return "optional_stop"
    if upper_code.startswith("LASER_PARA") or "/M717" in stripped.upper() or "/M718" in stripped.upper() or "/M713" in stripped.upper():
        return "laser_command"
    if "/M721" in stripped.upper() or "/M722" in stripped.upper():
        return "powder_command"
    if upper_code.startswith("TRAORI") or upper_code.startswith("TRAFOOF"):
        return "transform"
    if upper_code.startswith("CYCLE"):
        return "cycle"
    if has_dwell_code([match.upper() for match in G_CODE_RE.findall(upper_code)]):
        return "dwell"
    if explicit_motion_code or (axis_values and state.modal_motion_code in MOTION_CODES):
        return "motion"
    if D_RE.search(upper_code):
        return "tool"
    if upper_code.startswith("G") or upper_code.startswith("M"):
        return "setup"
    return "misc"


def first_command(code: str, raw_line: str) -> str:
    stripped = raw_line.strip()
    if not stripped:
        return "BLANK"
    if stripped.startswith(";"):
        return "COMMENT"
    token = code.split(maxsplit=1)[0] if code else stripped.split(maxsplit=1)[0]
    return token.upper()


def infer_machine(post_header_value: str | None) -> str:
    if not post_header_value:
        return "unknown"
    stem = Path(post_header_value).stem
    for token in reversed(stem.split("_")):
        if any(character.isdigit() for character in token):
            return token.upper()
    return stem.upper()


def format_cam_system(raw_value: str | None) -> str:
    if not raw_value:
        return "Mastercam"
    if raw_value.upper().startswith("MASTERCAM"):
        return raw_value.title()
    return f"Mastercam {raw_value}".strip()


def parse_laser_para(code: str) -> dict[str, Any]:
    match = LASER_PARA_RE.search(code)
    if not match:
        return {}
    raw_args = [item.strip() for item in match.group(1).split(",")] if match.group(1) else []
    if not raw_args or all(not item for item in raw_args):
        return {"parameter_action": "clear"}

    payload: dict[str, Any] = {"parameter_action": "set"}
    if len(raw_args) >= 1 and raw_args[0]:
        payload["laser_power_w"] = float(raw_args[0])
    if len(raw_args) >= 3 and raw_args[2]:
        payload["spot_diameter_mm"] = float(raw_args[2])
    if len(raw_args) >= 4 and raw_args[3]:
        payload["laser_mode"] = int(float(raw_args[3]))
    return payload


def estimate_nominal_layer_height(levels: list[float]) -> float | None:
    if len(levels) < 2:
        return None
    diffs = [
        round(levels[index + 1] - levels[index], 6)
        for index in range(len(levels) - 1)
        if levels[index + 1] > levels[index]
    ]
    if not diffs:
        return None
    counts = Counter(round(item, 3) for item in diffs if item > 0)
    return float(counts.most_common(1)[0][0])


def classify_path_type(
    motion_code: str,
    laser_on: bool,
    start_point: dict[str, float | None],
    end_point: dict[str, float | None],
) -> str:
    if laser_on:
        return "deposit"
    if motion_code == "G0":
        start_z = start_point.get("z_mm")
        end_z = end_point.get("z_mm")
        if start_z is not None and end_z is not None:
            if end_z > start_z + 0.05:
                return "retract"
            if end_z < start_z - 0.05:
                return "approach"
        return "travel"
    return "travel"


def point_changed(start_point: dict[str, float | None], end_point: dict[str, float | None]) -> bool:
    for key in ("x_mm", "y_mm", "z_mm", "a_deg", "c_deg"):
        start_value = start_point.get(key)
        end_value = end_point.get(key)
        if start_value is None or end_value is None:
            continue
        if not math.isclose(float(start_value), float(end_value), abs_tol=1e-9):
            return True
    return False


def maybe_add_parameter_event(
    events: list[dict[str, Any]],
    state: ModalState,
    line_no: int,
    raw_line: str,
    code: str,
    comment: str | None,
    g_codes: list[str],
    event_counter: int,
) -> tuple[int, str | None]:
    upper_code = code.upper()
    stripped_upper = raw_line.strip().upper()
    event: dict[str, Any] | None = None

    if upper_code.startswith("LASER_PARA"):
        laser_values = parse_laser_para(code)
        action = laser_values.pop("parameter_action", "set")
        event = {
            "parameter_event_id": f"LPP_{event_counter:04d}",
            "program_id": "",
            "line_no": line_no,
            "parameter_action": action,
            "raw_command": raw_line.strip(),
            "laser_on": state.laser_on,
            "powder_supply_on": state.powder_supply_on,
            "safety_lock_on": state.safety_lock_on,
        }
        event.update(laser_values)
        if action == "set":
            state.active_parameter_event_id = event["parameter_event_id"]
        else:
            state.active_parameter_event_id = None

    elif "/M713" in stripped_upper:
        state.safety_lock_on = True
        event = {
            "parameter_event_id": f"LPP_{event_counter:04d}",
            "program_id": "",
            "line_no": line_no,
            "parameter_action": "set",
            "raw_command": raw_line.strip(),
            "safety_lock_on": True,
            "laser_on": state.laser_on,
            "powder_supply_on": state.powder_supply_on,
            "notes": comment or "Laser safety lock on",
        }

    elif "/M717" in stripped_upper:
        state.laser_on = True
        event = {
            "parameter_event_id": f"LPP_{event_counter:04d}",
            "program_id": "",
            "line_no": line_no,
            "parameter_action": "set",
            "raw_command": raw_line.strip(),
            "laser_on": True,
            "powder_supply_on": state.powder_supply_on,
            "safety_lock_on": state.safety_lock_on,
            "notes": comment or "Laser on",
        }

    elif "/M718" in stripped_upper:
        state.laser_on = False
        event = {
            "parameter_event_id": f"LPP_{event_counter:04d}",
            "program_id": "",
            "line_no": line_no,
            "parameter_action": "clear",
            "raw_command": raw_line.strip(),
            "laser_on": False,
            "powder_supply_on": state.powder_supply_on,
            "safety_lock_on": state.safety_lock_on,
            "notes": comment or "Laser off",
        }

    elif "/M721" in stripped_upper:
        state.powder_supply_on = True
        event = {
            "parameter_event_id": f"LPP_{event_counter:04d}",
            "program_id": "",
            "line_no": line_no,
            "parameter_action": "set",
            "raw_command": raw_line.strip(),
            "laser_on": state.laser_on,
            "powder_supply_on": True,
            "safety_lock_on": state.safety_lock_on,
            "powder_emptying_requested": bool(comment and "empty powder tube" in comment.lower()),
            "notes": comment or "Powder supply on",
        }

    elif "/M722" in stripped_upper:
        state.powder_supply_on = False
        event = {
            "parameter_event_id": f"LPP_{event_counter:04d}",
            "program_id": "",
            "line_no": line_no,
            "parameter_action": "clear",
            "raw_command": raw_line.strip(),
            "laser_on": state.laser_on,
            "powder_supply_on": False,
            "safety_lock_on": state.safety_lock_on,
            "notes": comment or "Powder supply off",
        }

    elif has_dwell_code(g_codes):
        dwell_value = extract_axis_values(code).get("F")
        event = {
            "parameter_event_id": f"LPP_{event_counter:04d}",
            "program_id": "",
            "line_no": line_no,
            "parameter_action": "set",
            "raw_command": raw_line.strip(),
            "laser_on": state.laser_on,
            "powder_supply_on": state.powder_supply_on,
            "safety_lock_on": state.safety_lock_on,
            "dwell_s": dwell_value,
            "notes": comment or "Dwell",
        }

    if event is None:
        return event_counter, None

    events.append(compact_dict(event))
    return event_counter + 1, event["parameter_event_id"]


def compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def unique_preserve(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        if value in seen or value is None:
            continue
        seen.add(value)
        result.append(value)
    return result


def public_nc_block(block: dict[str, Any]) -> dict[str, Any]:
    drop_keys = {
        "d_number",
        "transform_mode",
        "work_offset",
        "safety_lock_on",
        "segment_id",
    }
    return {key: value for key, value in block.items() if key not in drop_keys}


def parse_mpf_file(path: Path) -> dict[str, Any]:
    lines = read_source_text(path).splitlines()
    state = ModalState()
    header_map: dict[str, str] = {}
    blocks: list[dict[str, Any]] = []
    motion_records: list[dict[str, Any]] = []
    parameter_events: list[dict[str, Any]] = []
    layer_lookup: dict[float, int] = {}
    parameter_event_counter = 1
    last_laser_parameter_id: str | None = None

    file_variant = "modified" if "_modified" in path.stem.lower() else "original"
    header_program_name = ""

    for line_no, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        code, comment = split_comment(raw_line)
        upper_code = code.upper()

        if stripped.startswith(";"):
            header_text = stripped[1:].strip()
            if " - " in header_text:
                key, value = header_text.split(" - ", 1)
                header_map[key.strip().upper()] = value.strip()
            elif header_text.upper().startswith("MASTERCAM"):
                header_map["MASTERCAM"] = header_text

        g_codes = [match.upper() for match in G_CODE_RE.findall(upper_code)]
        m_codes = [match.upper().lstrip("/") for match in M_CODE_RE.findall(stripped.upper())]
        axis_values = extract_axis_values(code)
        explicit_motion_code = next((normalize_motion_code(item) for item in g_codes if normalize_motion_code(item) in MOTION_CODES), None)
        effective_motion_code = explicit_motion_code or (state.modal_motion_code if axis_values else None)

        for g_code in g_codes:
            upper_g = g_code.upper()
            if upper_g in {"G17", "G18", "G19"}:
                state.coordinate_plane = upper_g
            elif upper_g in {"G90", "G91"}:
                state.coordinate_mode = upper_g
            elif upper_g == "G64":
                state.path_control_mode = upper_g
            elif WORK_OFFSET_RE.fullmatch(upper_g):
                state.work_offset = upper_g

        if explicit_motion_code:
            state.modal_motion_code = explicit_motion_code

        if upper_code.startswith("TRAORI"):
            state.transform_mode = code.strip()
        elif upper_code.startswith("TRAFOOF"):
            state.transform_mode = "TRAFOOF"

        d_match = D_RE.search(upper_code)
        if d_match:
            state.d_number = int(d_match.group(1))

        parameter_event_counter, created_event_id = maybe_add_parameter_event(
            events=parameter_events,
            state=state,
            line_no=line_no,
            raw_line=raw_line,
            code=code,
            comment=comment,
            g_codes=g_codes,
            event_counter=parameter_event_counter,
        )

        if upper_code.startswith("LASER_PARA") and created_event_id:
            last_laser_parameter_id = created_event_id if parse_laser_para(code).get("parameter_action", "set") == "set" else None

        block_type = block_type_for_line(
            line_no=line_no,
            raw_line=raw_line,
            code=code,
            comment=comment,
            explicit_motion_code=effective_motion_code,
            state=state,
            axis_values=axis_values,
        )

        start_point = current_point(state)
        if block_type == "motion":
            if "F" in axis_values and effective_motion_code in MOTION_CODES:
                state.feed_rate_mm_min = axis_values["F"]

            for axis_key, target_key in (
                ("X", "x_mm"),
                ("Y", "y_mm"),
                ("Z", "z_mm"),
                ("A", "a_deg"),
                ("C", "c_deg"),
            ):
                if axis_key in axis_values:
                    setattr(state, target_key, axis_values[axis_key])

        end_point = current_point(state)

        layer_index: int | None = None
        z_layer_mm: float | None = None
        if block_type == "motion":
            if state.laser_on and state.z_mm is not None:
                rounded_z = round(state.z_mm, 3)
                if rounded_z not in layer_lookup:
                    layer_lookup[rounded_z] = len(layer_lookup) + 1
                layer_index = layer_lookup[rounded_z]
                z_layer_mm = rounded_z
                state.active_layer_index = layer_index
                state.active_layer_z = rounded_z
            else:
                layer_index = state.active_layer_index or 1
                z_layer_mm = state.active_layer_z if state.active_layer_z is not None else state.z_mm

        block: dict[str, Any] = {
            "program_id": "",
            "line_no": line_no,
            "raw_line": raw_line.rstrip(),
            "command": first_command(code, raw_line),
            "block_type": block_type,
            "m_codes": m_codes,
            "x_mm": state.x_mm,
            "y_mm": state.y_mm,
            "z_mm": state.z_mm,
            "a_deg": state.a_deg,
            "c_deg": state.c_deg,
            "feed_rate_mm_min": state.feed_rate_mm_min if block_type == "motion" else None,
            "d_number": state.d_number,
            "transform_mode": state.transform_mode,
            "work_offset": state.work_offset,
            "laser_on": state.laser_on,
            "powder_supply_on": state.powder_supply_on,
            "safety_lock_on": state.safety_lock_on,
            "optional_block": stripped.startswith("/"),
            "layer_index": layer_index,
            "segment_id": None,
        }
        blocks.append(compact_dict(block))

        if (
            block_type == "motion"
            and effective_motion_code in MOTION_CODES
            and point_complete(start_point)
            and point_complete(end_point)
            and point_changed(start_point, end_point)
        ):
            motion_records.append(
                {
                    "program_id": "",
                    "line_no": line_no,
                    "motion_code": effective_motion_code,
                    "laser_on": state.laser_on,
                    "powder_supply_on": state.powder_supply_on,
                    "feed_rate_mm_min": state.feed_rate_mm_min,
                    "work_offset": state.work_offset,
                    "transform_mode": state.transform_mode,
                    "layer_index": layer_index or 1,
                    "z_layer_mm": z_layer_mm,
                    "parameter_event_id": last_laser_parameter_id or state.active_parameter_event_id,
                    "path_type": classify_path_type(effective_motion_code, state.laser_on, start_point, end_point),
                    "start_point": clean_point(start_point),
                    "end_point": clean_point(end_point),
                }
            )

    program_name = header_map.get("PROGRAM", path.name)
    header_program_name = Path(program_name).stem
    program_id = header_program_name.replace("_modified", "") if header_program_name else path.stem.replace("_modified", "")
    machine = infer_machine(header_map.get("POST"))
    z_levels = sorted(layer_lookup.keys())

    for record in blocks:
        record["program_id"] = program_id
    for record in parameter_events:
        record["program_id"] = program_id
    for record in motion_records:
        record["program_id"] = program_id

    segments = build_segments(program_id=program_id, blocks=blocks, motion_records=motion_records)
    process_blocks = build_process_blocks(
        program_id=program_id,
        lines=blocks,
        motion_records=motion_records,
        parameter_events=parameter_events,
    )
    file_meta = {
        "program_id": program_id,
        "file_name": path.name,
        "source_format": "Siemens MPF",
        "source_variant": file_variant,
        "cam_system": format_cam_system(header_map.get("MASTERCAM")),
        "source_cam_file": header_map.get("MCAM FILE"),
        "machine": machine,
        "machine_type": "Laser-Directed-Energy-Deposition",
        "created_date": header_map.get("DATE"),
        "created_time": header_map.get("TIME"),
        "unit_system": "mm",
        "coordinate_plane": state.coordinate_plane,
        "coordinate_mode": state.coordinate_mode,
        "work_offset": "G54",
        "path_control_mode": state.path_control_mode,
        "transform_mode": "TRAORI(2)" if any("TRAORI" in (item.get("transform_mode") or "") for item in blocks) else state.transform_mode,
        "home_position_used": any("SUPA" in item["raw_line"].upper() for item in blocks),
        "has_laser_process": any(item["command"] == "LASER_PARA" or item.get("laser_on") for item in blocks),
        "has_powder_supply": any(item.get("powder_supply_on") or "M721" in " ".join(item.get("m_codes", [])) for item in blocks),
    }

    summary = {
        "program_id": program_id,
        "file_name": path.name,
        "source_variant": file_variant,
        "line_count": len(lines),
        "line_record_count": len(blocks),
        "motion_line_count": len(motion_records),
        "parameter_event_count": len(parameter_events),
        "process_block_count": len(process_blocks),
        "toolpath_segment_count": len(segments),
        "deposit_segment_count": sum(1 for item in segments if item["path_type"] == "deposit"),
        "layer_count": len(z_levels),
        "nominal_layer_height_mm": estimate_nominal_layer_height(z_levels),
        "observed_deposition_z_levels_mm": z_levels,
        "z_levels_mm": z_levels,
    }
    public_lines = [public_nc_block(compact_dict(record)) for record in blocks]

    return {
        "nc_file": compact_dict(file_meta),
        "lines": public_lines,
        "parameter_events": parameter_events,
        "process_blocks": process_blocks,
        "segments": segments,
        "summary": summary,
    }


def build_segments(
    program_id: str,
    blocks: list[dict[str, Any]],
    motion_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current_group: list[dict[str, Any]] = []
    current_key: tuple[Any, ...] | None = None
    track_counter = 0

    def flush_group(group: list[dict[str, Any]]) -> None:
        nonlocal track_counter
        if not group:
            return

        track_counter += 1
        layer_index = int(group[0]["layer_index"])
        z_layer = group[0]["z_layer_mm"]
        points = [group[0]["start_point"], *[item["end_point"] for item in group]]
        x_values = [point["x_mm"] for point in points]
        y_values = [point["y_mm"] for point in points]
        z_values = [point["z_mm"] for point in points]
        segment_id = f"SEG_L{layer_index:02d}_T{track_counter:03d}"
        segment = {
            "program_id": program_id,
            "segment_id": segment_id,
            "parameter_event_id": group[0]["parameter_event_id"],
            "start_line_no": group[0]["line_no"],
            "end_line_no": group[-1]["line_no"],
            "source_range": f"L{group[0]['line_no']:05d}-L{group[-1]['line_no']:05d}",
            "path_type": group[0]["path_type"],
            "motion_code": group[0]["motion_code"],
            "laser_on": group[0]["laser_on"],
            "powder_supply_on": group[0]["powder_supply_on"],
            "feed_rate_mm_min": group[0]["feed_rate_mm_min"],
            "work_offset": group[0]["work_offset"],
            "transform_mode": group[0]["transform_mode"],
            "track_index": track_counter,
            "layer_index": layer_index,
            "z_layer_mm": z_layer if z_layer is not None else group[-1]["end_point"]["z_mm"],
            "start_point": group[0]["start_point"],
            "end_point": group[-1]["end_point"],
            "point_count": len(points),
            "bounding_box": {
                "x_min_mm": min(x_values),
                "x_max_mm": max(x_values),
                "y_min_mm": min(y_values),
                "y_max_mm": max(y_values),
                "z_min_mm": min(z_values),
                "z_max_mm": max(z_values),
            },
        }
        segments.append(compact_dict(segment))
        line_to_segment = {int(item["line_no"]): segment_id for item in group}
        for block in blocks:
            if int(block["line_no"]) in line_to_segment:
                block["segment_id"] = line_to_segment[int(block["line_no"])]

    for item in motion_records:
        key = (
            item["path_type"],
            item["motion_code"],
            item["laser_on"],
            item["powder_supply_on"],
            item["layer_index"],
            round(item["z_layer_mm"], 6) if item["z_layer_mm"] is not None else None,
            item["work_offset"],
            item["transform_mode"],
            item["parameter_event_id"],
        )
        is_contiguous = bool(current_group) and item["line_no"] == current_group[-1]["line_no"] + 1
        if current_key == key and is_contiguous:
            current_group.append(item)
            continue
        flush_group(current_group)
        current_group = [item]
        current_key = key

    flush_group(current_group)
    return segments


def build_process_blocks(
    program_id: str,
    lines: list[dict[str, Any]],
    motion_records: list[dict[str, Any]],
    parameter_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    process_blocks: list[dict[str, Any]] = []
    anchor_lines = [
        line for line in lines if line.get("block_type") == "optional_stop" and "M01" in line.get("raw_line", "").upper()
    ]
    if not anchor_lines:
        return process_blocks

    line_lookup = {int(line["line_no"]): line for line in lines}
    sorted_line_nos = sorted(line_lookup.keys())
    max_line_no = sorted_line_nos[-1]
    block_counter_by_layer: dict[int, int] = {}

    for index, anchor in enumerate(anchor_lines):
        anchor_line_no = int(anchor["line_no"])
        next_anchor_line_no = int(anchor_lines[index + 1]["line_no"]) if index + 1 < len(anchor_lines) else max_line_no + 1
        start_line_no = anchor_line_no
        end_line_no = next_anchor_line_no - 1

        range_lines = [line for line in lines if start_line_no <= int(line["line_no"]) <= end_line_no]
        range_motion = [item for item in motion_records if start_line_no <= int(item["line_no"]) <= end_line_no]
        if not range_motion:
            continue

        layer_motion = next((item for item in range_motion if item.get("z_layer_mm") is not None), range_motion[0])
        layer_index = int(layer_motion.get("layer_index") or 1)
        z_level_mm = float(layer_motion.get("z_layer_mm") if layer_motion.get("z_layer_mm") is not None else layer_motion["end_point"]["z_mm"])
        block_counter_by_layer[layer_index] = block_counter_by_layer.get(layer_index, 0) + 1
        process_block_id = f"PB_L{layer_index:02d}_B{block_counter_by_layer[layer_index]:03d}"

        parameter_event_ids = unique_preserve(
            [
                event["parameter_event_id"]
                for event in parameter_events
                if start_line_no <= int(event["line_no"]) <= end_line_no
            ]
        )
        segment_ids = unique_preserve([line.get("segment_id") for line in range_lines if line.get("segment_id")])

        points = [range_motion[0]["start_point"], *[item["end_point"] for item in range_motion]]
        x_values = [point["x_mm"] for point in points]
        y_values = [point["y_mm"] for point in points]
        z_values = [point["z_mm"] for point in points]
        path_type = "deposit" if any(bool(item.get("laser_on")) for item in range_motion) else range_motion[0]["path_type"]
        feed_rate = next((item.get("feed_rate_mm_min") for item in range_motion if item.get("feed_rate_mm_min") is not None), None)

        process_block = {
            "program_id": program_id,
            "process_block_id": process_block_id,
            "anchor_line_no": anchor_line_no,
            "anchor_line_id": f"L{anchor_line_no:05d}",
            "start_line_no": start_line_no,
            "end_line_no": end_line_no,
            "first_motion_line_no": int(range_motion[0]["line_no"]),
            "last_motion_line_no": int(range_motion[-1]["line_no"]),
            "source_range": f"L{start_line_no:05d}-L{end_line_no:05d}",
            "trigger_command": "M01",
            "layer_index": layer_index,
            "z_level_mm": round(z_level_mm, 3),
            "path_type": path_type,
            "line_count": len(range_lines),
            "motion_line_count": len(range_motion),
            "segment_ids": segment_ids or None,
            "parameter_event_ids": parameter_event_ids or None,
            "laser_on": any(bool(item.get("laser_on")) for item in range_motion),
            "powder_supply_on": any(bool(item.get("powder_supply_on")) for item in range_motion),
            "feed_rate_mm_min": feed_rate,
            "work_offset": range_motion[0].get("work_offset"),
            "transform_mode": range_motion[0].get("transform_mode"),
            "start_point": range_motion[0]["start_point"],
            "end_point": range_motion[-1]["end_point"],
            "point_count": len(points),
            "bounding_box": {
                "x_min_mm": min(x_values),
                "x_max_mm": max(x_values),
                "y_min_mm": min(y_values),
                "y_max_mm": max(y_values),
                "z_min_mm": min(z_values),
                "z_max_mm": max(z_values),
            },
            "notes": "Manufacturing-oriented process block grouped from one M01 anchor through the subsequent same-Z process lines.",
        }
        process_blocks.append(compact_dict(process_block))

    return process_blocks


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def validate_outputs(package: dict[str, Any]) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema not installed; skipped schema validation."]

    messages: list[str] = []
    schema_map = {
        "nc_file": SCHEMA_DIR / "NC-file.schema.json",
        "lines": SCHEMA_DIR / "NC-block.schema.json",
        "parameter_events": SCHEMA_DIR / "laser-process-parameters.schema.json",
        "segments": SCHEMA_DIR / "toolpath-segment.schema.json",
    }

    validators: dict[str, Any] = {}
    for key, path in schema_map.items():
        schema = json.loads(path.read_text(encoding="utf-8"))
        validators[key] = jsonschema.Draft202012Validator(schema)

    validators["nc_file"].validate(package["nc_file"])
    for row in package["lines"]:
        validators["lines"].validate(row)
    for row in package["parameter_events"]:
        validators["parameter_events"].validate(row)
    for row in package["segments"]:
        validators["segments"].validate(row)

    messages.append("Schema validation passed.")
    return messages


def process_file(input_path: Path, output_root: Path, validate: bool) -> dict[str, Any]:
    package = parse_mpf_file(input_path)
    target_dir = output_root / input_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)

    write_json(target_dir / "NC-file.json", package["nc_file"])
    write_json(target_dir / "summary.json", package["summary"])
    write_jsonl(target_dir / "NC-blocks.jsonl", package["lines"])
    write_jsonl(target_dir / "laser-process-parameters.jsonl", package["parameter_events"])
    write_jsonl(target_dir / "toolpath-segments.jsonl", package["segments"])

    validation_messages = validate_outputs(package) if validate else []

    return {
        "input_file": input_path.name,
        "output_dir": str(target_dir.relative_to(output_root)),
        "summary": package["summary"],
        "validation": validation_messages,
    }


def main() -> int:
    args = parse_args()
    inputs = discover_inputs(args.inputs)
    if not inputs:
        raise SystemExit("No MPF files found.")

    output_root = Path(args.output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    for input_path in inputs:
        result = process_file(input_path=input_path, output_root=output_root, validate=args.validate)
        manifest.append(result)
        summary = result["summary"]
        print(
            f"[OK] {result['input_file']}: "
            f"{summary['line_record_count']} line records, "
            f"{summary['parameter_event_count']} parameter events, "
            f"{summary['process_block_count']} process blocks, "
            f"{summary['toolpath_segment_count']} toolpath segments, "
            f"{summary['layer_count']} layers"
        )
        for message in result["validation"]:
            print(f"      {message}")

    write_json(output_root / "run-manifest.json", manifest)
    print(f"[DONE] Wrote outputs to {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
