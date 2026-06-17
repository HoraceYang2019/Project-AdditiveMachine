from __future__ import annotations

from typing import Any


IDENTIFICATION_RESULT_SCHEMA_VERSION = "ded-identification-result-v1"
INFERENCE_RESULT_SCHEMA_VERSION = "ded-inference-result-v1"
DECISION_RESULT_SCHEMA_VERSION = "ded-decision-result-v1"


def _as_number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if numeric == numeric else None
    try:
        numeric = float(str(value))
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def build_identification_output_contract() -> dict[str, Any]:
    return {
        "schema_version": IDENTIFICATION_RESULT_SCHEMA_VERSION,
        "title": "DED IdentificationResult",
        "description": "Runtime status identification at one synchronized playback point.",
        "required_fields": [
            "identified_status",
            "status_label",
            "status_confidence",
            "status_source",
            "status_reason",
            "status_evidence",
            "time_context",
        ],
        "identified_status_values": [
            "not_identified",
            "normal_deposition",
            "heat_accumulation_warning",
            "abnormal_heat_or_process",
            "unknown",
        ],
        "confidence_range": [0.0, 1.0],
    }


def build_default_identification_result() -> dict[str, Any]:
    return {
        "schema_version": IDENTIFICATION_RESULT_SCHEMA_VERSION,
        "identification_stage": "format_v1",
        "identified_status": "not_identified",
        "status_label": "尚未辨識",
        "status_confidence": 0.0,
        "status_source": [],
        "status_reason": "等待目前播放點的同步熱像、Edge 與路徑資料後再建立製程狀態辨識結果。",
        "status_evidence": {
            "g_high": None,
            "layer_index": None,
            "timestamp_ms": None,
            "x_mm": None,
            "y_mm": None,
            "z_mm": None,
            "laser_on": None,
            "feed_rate_mm_min": None,
        },
        "time_context": {
            "source": "dashboard_payload",
            "playback_progress": None,
        },
    }


def build_inference_output_contract() -> dict[str, Any]:
    return {
        "schema_version": INFERENCE_RESULT_SCHEMA_VERSION,
        "title": "DED InferenceResult",
        "description": "Explainable recommendation output derived from the current synchronized playback point.",
        "required_fields": [
            "state",
            "cause",
            "confidence",
            "recommended_action",
            "recommended_parameter_change",
            "related_rule",
            "related_parameter",
            "evidence",
            "time_context",
        ],
        "state_values": ["not_evaluated", "good", "warning", "abnormal", "unknown"],
        "confidence_range": [0.0, 1.0],
    }


def build_default_inference_result() -> dict[str, Any]:
    return {
        "schema_version": INFERENCE_RESULT_SCHEMA_VERSION,
        "inference_stage": "format_v1",
        "state": "not_evaluated",
        "state_label": "尚未推論",
        "cause": "等待 Identification 結果與同步播放點資料後再建立參數建議。",
        "confidence": 0.0,
        "recommended_action": "目前尚未產生推論建議。",
        "recommended_parameter_change": [],
        "related_rule": None,
        "related_parameter": [],
        "evidence": {
            "g_high": None,
            "layer_index": None,
            "timestamp_ms": None,
            "x_mm": None,
            "y_mm": None,
            "z_mm": None,
        },
        "time_context": {
            "source": "dashboard_payload",
            "playback_progress": None,
        },
    }


def build_decision_output_contract() -> dict[str, Any]:
    return {
        "schema_version": DECISION_RESULT_SCHEMA_VERSION,
        "title": "DED DecisionResult",
        "description": "Decision layer that links identification, inference, and adaptation preview at one playback point.",
        "required_fields": [
            "decision_state",
            "decision_label",
            "decision_ready",
            "summary",
            "selected_response",
            "recommended_parameter_change",
            "evidence",
            "time_context",
            "identification_result",
            "inference_result",
        ],
        "decision_state_values": ["pending", "maintain", "adjust", "inspect", "unknown"],
    }


def build_default_decision_result() -> dict[str, Any]:
    identification = build_default_identification_result()
    inference = build_default_inference_result()
    return {
        "schema_version": DECISION_RESULT_SCHEMA_VERSION,
        "decision_stage": "format_v1",
        "decision_state": "pending",
        "decision_label": "尚未決策",
        "decision_ready": False,
        "summary": "等待同步播放點資料後再建立決策結果。",
        "selected_response": None,
        "recommended_parameter_change": [],
        "evidence": dict(inference["evidence"]),
        "time_context": dict(inference["time_context"]),
        "identification_result": identification,
        "inference_result": inference,
    }


def _has_parameter_value(parameter_events: list[dict[str, Any]], field_name: str) -> bool:
    for event in parameter_events:
        value = event.get(field_name)
        if isinstance(value, bool):
            return True
        if value not in (None, "", []):
            return True
    return False


def _has_toolpath_value(toolpath_segments: list[dict[str, Any]], field_name: str) -> bool:
    for segment in toolpath_segments:
        value = segment.get(field_name)
        if value not in (None, "", []):
            return True
    return False


def build_decision_rule_table(
    thermal: dict[str, Any],
    edge: dict[str, Any],
    parameter_events: list[dict[str, Any]],
    toolpath_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    thresholds = {
        "good_max_exclusive": 1300.0,
        "warning_min_inclusive": 1300.0,
        "warning_max_exclusive": 1500.0,
        "abnormal_min_inclusive": 1500.0,
    }

    available_fields = [
        {
            "source": "thermal",
            "field": "Time",
            "label": "熱像時間戳記",
            "available": bool(thermal.get("sample_count", 0)),
        },
        {
            "source": "thermal",
            "field": "G_High",
            "label": "熱像 G_High",
            "available": bool(thermal.get("sample_count", 0)),
        },
        {
            "source": "edge",
            "field": "sample_ms",
            "label": "Edge 取樣時間",
            "available": bool(edge.get("sample_count", 0)),
        },
        {
            "source": "edge",
            "field": "machine_z_mm",
            "label": "Edge Z 位置",
            "available": bool(edge.get("has_machine_coordinates")),
        },
        {
            "source": "mpf",
            "field": "laser_power_w",
            "label": "雷射功率",
            "available": _has_parameter_value(parameter_events, "laser_power_w"),
        },
        {
            "source": "mpf",
            "field": "spot_diameter_mm",
            "label": "光斑直徑",
            "available": _has_parameter_value(parameter_events, "spot_diameter_mm"),
        },
        {
            "source": "mpf",
            "field": "powder_supply_on",
            "label": "送粉狀態",
            "available": _has_parameter_value(parameter_events, "powder_supply_on"),
        },
        {
            "source": "mpf",
            "field": "dwell_s",
            "label": "停留時間",
            "available": _has_parameter_value(parameter_events, "dwell_s"),
        },
        {
            "source": "toolpath",
            "field": "feed_rate_mm_min",
            "label": "進給速度",
            "available": _has_toolpath_value(toolpath_segments, "feed_rate_mm_min"),
        },
    ]

    rules = [
        {
            "rule_id": "Rule_Good",
            "state_key": "good",
            "state_label": "優良",
            "min_inclusive": None,
            "max_exclusive": thresholds["good_max_exclusive"],
            "threshold_text": "G_High < 1300 °C",
            "range_label": "< 1300 °C",
            "diagnosis": "熱輸入維持在穩定區間，優先維持目前參數。",
            "cause_hint": "目前同步點落在正常沉積與正常冷卻的穩定區間。",
            "recommended_adjustments": [
                "維持目前雷射功率與進給速度。",
                "持續監看同 layer 後段是否仍維持穩定。",
            ],
            "recommended_parameter_change": [
                {
                    "parameter": "laser_power_w",
                    "label": "雷射功率",
                    "direction": "maintain",
                    "magnitude": "0%",
                    "unit": "W",
                    "basis": "RecRule_Good_Maintain",
                },
                {
                    "parameter": "feed_rate_mm_min",
                    "label": "進給速度",
                    "direction": "maintain",
                    "magnitude": "0%",
                    "unit": "mm/min",
                    "basis": "RecRule_Good_Maintain",
                },
            ],
        },
        {
            "rule_id": "Rule_Warning",
            "state_key": "warning",
            "state_label": "警示",
            "min_inclusive": thresholds["warning_min_inclusive"],
            "max_exclusive": thresholds["warning_max_exclusive"],
            "threshold_text": "1300 <= G_High < 1500 °C",
            "range_label": "1300 ~ 1500 °C",
            "diagnosis": "熱輸入開始偏高或冷卻不穩，建議先做微調。",
            "cause_hint": "可能是熱累積、進給偏慢、能量密度偏高，或送粉/噴嘴狀態開始漂移。",
            "recommended_adjustments": [
                "先微幅降低雷射功率 2% ~ 5%。",
                "再微幅提高進給速度 2% ~ 5%。",
                "同步檢查送粉與光斑直徑是否穩定。",
            ],
            "recommended_parameter_change": [
                {
                    "parameter": "laser_power_w",
                    "label": "雷射功率",
                    "direction": "decrease",
                    "magnitude": "2% to 5%",
                    "unit": "W",
                    "basis": "RecRule_Warning_AdjustHeatInput",
                },
                {
                    "parameter": "feed_rate_mm_min",
                    "label": "進給速度",
                    "direction": "increase",
                    "magnitude": "2% to 5%",
                    "unit": "mm/min",
                    "basis": "RecRule_Warning_AdjustHeatInput",
                },
                {
                    "parameter": "powder_supply_on",
                    "label": "送粉狀態",
                    "direction": "inspect",
                    "magnitude": "check",
                    "unit": "boolean",
                    "basis": "RecRule_Warning_AdjustHeatInput",
                },
                {
                    "parameter": "spot_diameter_mm",
                    "label": "光斑直徑",
                    "direction": "inspect",
                    "magnitude": "check",
                    "unit": "mm",
                    "basis": "RecRule_Warning_AdjustHeatInput",
                },
            ],
        },
        {
            "rule_id": "Rule_Abnormal",
            "state_key": "abnormal",
            "state_label": "異常",
            "min_inclusive": thresholds["abnormal_min_inclusive"],
            "max_exclusive": None,
            "threshold_text": "G_High >= 1500 °C",
            "range_label": ">= 1500 °C",
            "diagnosis": "目前點位已落入異常區，應優先檢查製程狀態與設備健康。",
            "cause_hint": "可能是熱輸入過高、進給過慢、送粉異常，或噴嘴/雷射系統有異常。",
            "recommended_adjustments": [
                "降低雷射功率 5% ~ 10%，並提高進給速度 5% ~ 8%。",
                "檢查送粉、噴嘴、光斑與停留時間是否異常。",
                "將此區段送入後續 inference / adaptation 模組。",
            ],
            "recommended_parameter_change": [
                {
                    "parameter": "laser_power_w",
                    "label": "雷射功率",
                    "direction": "decrease",
                    "magnitude": "5% to 10%",
                    "unit": "W",
                    "basis": "RecRule_Abnormal_ImmediateCorrection",
                },
                {
                    "parameter": "feed_rate_mm_min",
                    "label": "進給速度",
                    "direction": "increase",
                    "magnitude": "5% to 8%",
                    "unit": "mm/min",
                    "basis": "RecRule_Abnormal_ImmediateCorrection",
                },
                {
                    "parameter": "powder_supply_on",
                    "label": "送粉狀態",
                    "direction": "inspect",
                    "magnitude": "check",
                    "unit": "boolean",
                    "basis": "RecRule_Abnormal_ImmediateCorrection",
                },
                {
                    "parameter": "spot_diameter_mm",
                    "label": "光斑直徑",
                    "direction": "inspect",
                    "magnitude": "check",
                    "unit": "mm",
                    "basis": "RecRule_Abnormal_ImmediateCorrection",
                },
                {
                    "parameter": "dwell_s",
                    "label": "停留時間",
                    "direction": "inspect",
                    "magnitude": "check",
                    "unit": "s",
                    "basis": "RecRule_Abnormal_ImmediateCorrection",
                },
            ],
        },
    ]

    return {
        "module_id": "ded-decision-runtime",
        "title": "製程狀態與參數建議",
        "subtitle": "用 Heat Playback 的同步點資料建立可解釋的辨識、推論與決策規則表。",
        "ontology_sources": [
            "LPBFOntology/Knowledge/amh350-knowledge.ttl",
            "LPBFOntology/Knowledge/amh350-semantic-graph.ttl",
        ],
        "data_summary": {
            "thermal_samples": int(thermal.get("sample_count") or 0),
            "edge_samples": int(edge.get("sample_count") or 0),
            "parameter_event_count": len(parameter_events),
            "toolpath_segment_count": len(toolpath_segments),
        },
        "input_fields": available_fields,
        "decision_basis": [
            {
                "basis_id": "absolute-threshold",
                "label": "絕對溫度門檻",
                "description": "先用 G_High 的絕對值區間分優良、警示與異常。",
            },
            {
                "basis_id": "same-parameter-reference",
                "label": "同參數基準",
                "description": "再和相同製程參數的歷史分布比較，判斷是否偏高、偏低或漂移。",
            },
            {
                "basis_id": "same-path-reference",
                "label": "同路徑位置基準",
                "description": "最後和同 layer、同路徑位置的基準曲線比較，避免把冷卻尾段誤判成製程異常。",
            },
        ],
        "adaptation_targets": [
            {"field": "laser_power_w", "label": "雷射功率", "unit": "W"},
            {"field": "feed_rate_mm_min", "label": "進給速度", "unit": "mm/min"},
            {"field": "powder_supply_on", "label": "送粉狀態", "unit": "boolean"},
            {"field": "spot_diameter_mm", "label": "光斑直徑", "unit": "mm"},
            {"field": "dwell_s", "label": "停留時間", "unit": "s"},
        ],
        "identification_output_contract": build_identification_output_contract(),
        "inference_output_contract": build_inference_output_contract(),
        "decision_output_contract": build_decision_output_contract(),
        "thresholds": thresholds,
        "rules": rules,
    }


def build_inference_rule_table(
    thermal: dict[str, Any],
    edge: dict[str, Any],
    parameter_events: list[dict[str, Any]],
    toolpath_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    return build_decision_rule_table(thermal, edge, parameter_events, toolpath_segments)


def _find_rule_for_state(rule_table: dict[str, Any] | None, state_key: str) -> dict[str, Any] | None:
    rules = rule_table.get("rules", []) if isinstance(rule_table, dict) else []
    for rule in rules:
        if str(rule.get("state_key") or "") == str(state_key or ""):
            return rule
    return None


def _classify_heat_state(g_high: float | None, rule_table: dict[str, Any] | None = None) -> dict[str, Any]:
    if g_high is None:
        return {
            "key": "unknown",
            "label": "未知",
            "description": "目前沒有可用的 G_High 數值。",
        }

    thresholds = (rule_table or {}).get("thresholds", {})
    good_max = _as_number_or_none(thresholds.get("good_max_exclusive")) or 1300.0
    abnormal_min = _as_number_or_none(thresholds.get("abnormal_min_inclusive")) or 1500.0

    if g_high < good_max:
        key = "good"
    elif g_high < abnormal_min:
        key = "warning"
    else:
        key = "abnormal"

    rule = _find_rule_for_state(rule_table, key)
    return {
        "key": key,
        "label": str((rule or {}).get("state_label") or key),
        "description": str((rule or {}).get("diagnosis") or ""),
    }


def evaluate_identification_result(
    playback_point: dict[str, Any] | None,
    *,
    layer_index: int | None = None,
    playback_progress: float | None = None,
    source_mode: str | None = None,
    rule_table: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(playback_point, dict):
        return build_default_identification_result()

    g_high = _as_number_or_none(
        playback_point.get("heat_g_high", playback_point.get("g_high", playback_point.get("G_High")))
    )
    feed_rate = _as_number_or_none(playback_point.get("feed_rate_mm_min"))
    timestamp_ms = _as_number_or_none(
        playback_point.get("heat_timestamp_ms", playback_point.get("timestamp_ms", playback_point.get("sample_ms")))
    )
    laser_on_value = playback_point.get("laser_on")
    laser_on = laser_on_value if isinstance(laser_on_value, bool) else True
    heat_state = _classify_heat_state(g_high, rule_table)

    status_source = ["thermal.G_High", "heat_playback"]
    if _as_number_or_none(playback_point.get("z_mm")) is not None:
        status_source.append("edge.machine_z_mm")
    if feed_rate is not None:
        status_source.append("toolpath.feed_rate_mm_min")
    if isinstance(laser_on_value, bool):
        status_source.append("toolpath.laser_on")

    identified_status = "unknown"
    status_label = "未知狀態"
    confidence = 0.0
    reason = "目前資料不足，暫時無法完成狀態辨識。"

    if g_high is None:
        identified_status = "not_identified"
        status_label = "尚未辨識"
        reason = "目前同步點缺少熱像 G_High，無法建立狀態辨識結果。"
    elif not laser_on or feed_rate == 0:
        identified_status = "abnormal_heat_or_process"
        status_label = "製程中斷 / 非沉積"
        confidence = 0.74 if heat_state["key"] != "abnormal" else 0.88
        reason = "目前點位顯示非連續沉積狀態，需先確認是否為暫停、空走或製程中斷。"
    elif heat_state["key"] == "good":
        identified_status = "normal_deposition"
        status_label = "正常沉積"
        confidence = 0.72
        reason = "G_High 落在穩定區間，判定為正常沉積與正常冷卻。"
    elif heat_state["key"] == "warning":
        identified_status = "heat_accumulation_warning"
        status_label = "熱累積警示"
        confidence = 0.78
        reason = "G_High 進入警示區間，顯示熱輸入偏高或冷卻不穩。"
    elif heat_state["key"] == "abnormal":
        identified_status = "abnormal_heat_or_process"
        status_label = "異常熱輸入 / 製程異常"
        confidence = 0.90
        reason = "G_High 已落入異常區，需優先檢查製程與設備狀態。"

    if source_mode == "ratio-fallback" and confidence > 0:
        confidence = max(0.0, confidence - 0.06)

    return {
        "schema_version": IDENTIFICATION_RESULT_SCHEMA_VERSION,
        "identification_stage": "playback_point_v1",
        "identified_status": identified_status,
        "status_label": status_label,
        "status_confidence": confidence,
        "status_source": status_source,
        "status_reason": reason,
        "status_evidence": {
            "g_high": g_high,
            "layer_index": layer_index,
            "timestamp_ms": timestamp_ms,
            "x_mm": _as_number_or_none(playback_point.get("x_mm")),
            "y_mm": _as_number_or_none(playback_point.get("y_mm")),
            "z_mm": _as_number_or_none(playback_point.get("z_mm")),
            "laser_on": laser_on,
            "feed_rate_mm_min": feed_rate,
        },
        "time_context": {
            "source": "heat_playback",
            "playback_progress": playback_progress,
        },
    }


def _map_identification_to_inference_state(identified_status: str) -> str:
    return {
        "normal_deposition": "good",
        "heat_accumulation_warning": "warning",
        "abnormal_heat_or_process": "abnormal",
        "unknown": "unknown",
        "not_identified": "not_evaluated",
    }.get(identified_status, "not_evaluated")


def _default_recommendation_copy(state_key: str) -> str:
    if state_key == "good":
        return "目前熱輸入維持在穩定區間，優先維持目前參數並持續監看。"
    if state_key == "warning":
        return "建議先從微調熱輸入開始，優先降低雷射功率或提高進給速度。"
    if state_key == "abnormal":
        return "建議優先檢查設備與送粉狀態，再執行較明顯的參數修正。"
    return "目前資料不足，暫時無法提供有效的參數建議。"


def _resolve_inference_state_label(state_key: str, rule: dict[str, Any] | None) -> str:
    if rule and rule.get("state_label"):
        return str(rule["state_label"])
    return {
        "good": "優良",
        "warning": "警示",
        "abnormal": "異常",
        "unknown": "未知",
        "not_evaluated": "尚未推論",
    }.get(state_key, "尚未推論")


def evaluate_inference_result(
    identification_result: dict[str, Any] | None,
    playback_point: dict[str, Any] | None,
    *,
    layer_index: int | None = None,
    playback_progress: float | None = None,
    rule_table: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identification = identification_result or build_default_identification_result()
    if not isinstance(playback_point, dict):
        return build_default_inference_result()

    state_key = _map_identification_to_inference_state(str(identification.get("identified_status") or ""))
    rule = _find_rule_for_state(rule_table, state_key)
    parameter_changes = []
    if state_key in {"good", "warning", "abnormal"} and isinstance(rule, dict):
        parameter_changes = list(rule.get("recommended_parameter_change") or [])

    related_parameters = [
        str(change.get("parameter") or "").strip()
        for change in parameter_changes
        if str(change.get("parameter") or "").strip()
    ]

    return {
        "schema_version": INFERENCE_RESULT_SCHEMA_VERSION,
        "inference_stage": "identification_driven_preview"
        if identification.get("identified_status") != "not_identified"
        else "format_v1",
        "state": state_key,
        "state_label": _resolve_inference_state_label(state_key, rule),
        "cause": str(identification.get("status_reason") or (rule or {}).get("cause_hint") or "目前資料不足，暫時無法解釋原因。"),
        "confidence": _as_number_or_none(identification.get("status_confidence")) or 0.0,
        "recommended_action": str((rule or {}).get("diagnosis") or _default_recommendation_copy(state_key)),
        "recommended_parameter_change": parameter_changes,
        "related_rule": (rule or {}).get("rule_id"),
        "related_parameter": related_parameters,
        "evidence": {
            "g_high": _as_number_or_none(
                playback_point.get("heat_g_high", playback_point.get("g_high", playback_point.get("G_High")))
            ),
            "layer_index": layer_index,
            "timestamp_ms": _as_number_or_none(
                playback_point.get("heat_timestamp_ms", playback_point.get("timestamp_ms", playback_point.get("sample_ms")))
            ),
            "x_mm": _as_number_or_none(playback_point.get("x_mm")),
            "y_mm": _as_number_or_none(playback_point.get("y_mm")),
            "z_mm": _as_number_or_none(playback_point.get("z_mm")),
            "identified_status": identification.get("identified_status"),
        },
        "time_context": {
            "source": "heat_playback",
            "playback_progress": playback_progress,
        },
    }


def evaluate_decision_result(
    playback_point: dict[str, Any] | None,
    *,
    layer_index: int | None = None,
    playback_progress: float | None = None,
    source_mode: str | None = None,
    rule_table: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identification = evaluate_identification_result(
        playback_point,
        layer_index=layer_index,
        playback_progress=playback_progress,
        source_mode=source_mode,
        rule_table=rule_table,
    )
    inference = evaluate_inference_result(
        identification,
        playback_point,
        layer_index=layer_index,
        playback_progress=playback_progress,
        rule_table=rule_table,
    )

    state = str(inference.get("state") or "not_evaluated")
    if state == "good":
        decision_state = "maintain"
        decision_label = "維持參數"
    elif state == "warning":
        decision_state = "adjust"
        decision_label = "建議微調"
    elif state == "abnormal":
        decision_state = "inspect"
        decision_label = "先檢查再調整"
    elif state == "unknown":
        decision_state = "unknown"
        decision_label = "未知"
    else:
        decision_state = "pending"
        decision_label = "尚未決策"

    changes = list(inference.get("recommended_parameter_change") or [])
    selected_response = changes[0] if changes else None
    return {
        "schema_version": DECISION_RESULT_SCHEMA_VERSION,
        "decision_stage": "identification_inference_bridge_v1",
        "decision_state": decision_state,
        "decision_label": decision_label,
        "decision_ready": decision_state not in {"pending", "unknown"},
        "summary": str(inference.get("recommended_action") or ""),
        "selected_response": selected_response,
        "recommended_parameter_change": changes,
        "evidence": inference.get("evidence", {}),
        "time_context": inference.get("time_context", {}),
        "identification_result": identification,
        "inference_result": inference,
    }


def build_decision_result(
    playback_point: dict[str, Any] | None,
    *,
    layer_index: int | None = None,
    playback_progress: float | None = None,
    source_mode: str | None = None,
    rule_table: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return evaluate_decision_result(
        playback_point,
        layer_index=layer_index,
        playback_progress=playback_progress,
        source_mode=source_mode,
        rule_table=rule_table,
    )


__all__ = [
    "DECISION_RESULT_SCHEMA_VERSION",
    "IDENTIFICATION_RESULT_SCHEMA_VERSION",
    "INFERENCE_RESULT_SCHEMA_VERSION",
    "build_decision_output_contract",
    "build_decision_result",
    "build_decision_rule_table",
    "build_default_decision_result",
    "build_default_identification_result",
    "build_default_inference_result",
    "build_identification_output_contract",
    "build_inference_output_contract",
    "build_inference_rule_table",
    "evaluate_decision_result",
    "evaluate_identification_result",
    "evaluate_inference_result",
]
