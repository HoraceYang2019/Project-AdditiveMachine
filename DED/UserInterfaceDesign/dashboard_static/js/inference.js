function renderMetricCards(ctx, summary) {
    const metrics = [
        { label: "熱像樣本", value: ctx.formatInteger(summary?.thermal_samples) },
        { label: "Edge 樣本", value: ctx.formatInteger(summary?.edge_samples) },
        { label: "參數事件", value: ctx.formatInteger(summary?.parameter_event_count) },
        { label: "路徑段數", value: ctx.formatInteger(summary?.toolpath_segment_count) },
    ];

    return metrics.map((metric) => `
        <article class="inference-rule-metric-card">
            <span>${metric.label}</span>
            <strong>${metric.value}</strong>
        </article>
    `).join("");
}

function asNumberOrNull(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
}

function normalizeIdentificationResult(ctx, rawResult) {
    const fallback = ctx.state.identification_current_result || {};
    const result = rawResult && typeof rawResult === "object" ? rawResult : fallback;
    return {
        schema_version: result.schema_version || "ded-identification-result-v1",
        identification_stage: result.identification_stage || "format_v1",
        identified_status: result.identified_status || "not_identified",
        status_label: result.status_label || "尚未辨識",
        status_confidence: Number.isFinite(Number(result.status_confidence)) ? Number(result.status_confidence) : 0,
        status_source: Array.isArray(result.status_source) ? result.status_source : [],
        status_reason: result.status_reason || "等待同步播放點資料後再建立目前製程狀態。",
        status_evidence: result.status_evidence && typeof result.status_evidence === "object" ? result.status_evidence : {},
        time_context: result.time_context && typeof result.time_context === "object" ? result.time_context : {},
    };
}

function normalizeInferenceResult(ctx, rawResult) {
    const fallback = ctx.state.inference_current_result || {};
    const result = rawResult && typeof rawResult === "object" ? rawResult : fallback;
    return {
        schema_version: result.schema_version || "ded-inference-result-v1",
        inference_stage: result.inference_stage || "format_v1",
        state: result.state || "not_evaluated",
        state_label: result.state_label || "尚未推論",
        cause: result.cause || "等待 Identification 結果後再建立參數建議。",
        confidence: Number.isFinite(Number(result.confidence)) ? Number(result.confidence) : 0,
        recommended_action: result.recommended_action || "目前尚未產生參數建議。",
        recommended_parameter_change: Array.isArray(result.recommended_parameter_change)
            ? result.recommended_parameter_change
            : [],
        related_rule: result.related_rule ?? null,
        related_parameter: Array.isArray(result.related_parameter) ? result.related_parameter : [],
        evidence: result.evidence && typeof result.evidence === "object" ? result.evidence : {},
        time_context: result.time_context && typeof result.time_context === "object" ? result.time_context : {},
    };
}

function mapIdentificationStatusToInferenceState(identifiedStatus) {
    if (identifiedStatus === "normal_deposition") {
        return "good";
    }
    if (identifiedStatus === "heat_accumulation_warning") {
        return "warning";
    }
    if (identifiedStatus === "abnormal_heat_or_process") {
        return "abnormal";
    }
    if (identifiedStatus === "unknown") {
        return "unknown";
    }
    return "not_evaluated";
}

function identificationTone(result) {
    if (result.identified_status === "normal_deposition") {
        return "good";
    }
    if (result.identified_status === "heat_accumulation_warning") {
        return "warning";
    }
    if (result.identified_status === "abnormal_heat_or_process") {
        return "abnormal";
    }
    return "unknown";
}

function findRuleForState(ruleTable, stateKey) {
    const rules = Array.isArray(ruleTable?.rules) ? ruleTable.rules : [];
    return rules.find((rule) => String(rule.state_key || "") === String(stateKey || "")) || null;
}

function fallbackParameterChanges(stateKey) {
    if (stateKey === "good") {
        return [
            { parameter: "laser_power_w", label: "雷射功率", direction: "maintain", magnitude: "0%", unit: "W", basis: "Rule_Good" },
            { parameter: "feed_rate_mm_min", label: "進給速度", direction: "maintain", magnitude: "0%", unit: "mm/min", basis: "Rule_Good" },
        ];
    }
    if (stateKey === "warning") {
        return [
            { parameter: "laser_power_w", label: "雷射功率", direction: "decrease", magnitude: "2% to 5%", unit: "W", basis: "Rule_Warning" },
            { parameter: "feed_rate_mm_min", label: "進給速度", direction: "increase", magnitude: "2% to 5%", unit: "mm/min", basis: "Rule_Warning" },
            { parameter: "powder_supply_on", label: "送粉狀態", direction: "inspect", magnitude: "check", unit: "", basis: "Rule_Warning" },
        ];
    }
    if (stateKey === "abnormal") {
        return [
            { parameter: "laser_power_w", label: "雷射功率", direction: "decrease", magnitude: "5% to 10%", unit: "W", basis: "Rule_Abnormal" },
            { parameter: "feed_rate_mm_min", label: "進給速度", direction: "increase", magnitude: "5% to 8%", unit: "mm/min", basis: "Rule_Abnormal" },
            { parameter: "powder_supply_on", label: "送粉狀態", direction: "inspect", magnitude: "check", unit: "", basis: "Rule_Abnormal" },
            { parameter: "spot_diameter_mm", label: "光斑直徑", direction: "inspect", magnitude: "check", unit: "mm", basis: "Rule_Abnormal" },
            { parameter: "dwell_s", label: "停留時間", direction: "inspect", magnitude: "check", unit: "s", basis: "Rule_Abnormal" },
        ];
    }
    return [];
}

function buildPlaybackIdentificationResult(ctx, geometry, snapshot) {
    if (!geometry || !snapshot?.headPoint) {
        return normalizeIdentificationResult(ctx, ctx.state.identification_current_result);
    }

    const point = snapshot.headPoint;
    const gHigh = asNumberOrNull(point?.heat_g_high);
    const feedRate = asNumberOrNull(point?.feed_rate_mm_min);
    const timestampMs = asNumberOrNull(point?.heat_timestamp_ms ?? point?.timestamp_ms);
    const laserOn = typeof point?.laser_on === "boolean" ? point.laser_on : true;
    const status = ctx.classifyHeatAlert(gHigh);
    const sourceList = ["thermal.G_High", "heat_playback"];

    if (asNumberOrNull(point?.z_mm) !== null) {
        sourceList.push("edge.machine_z_mm");
    }
    if (feedRate !== null) {
        sourceList.push("toolpath.feed_rate_mm_min");
    }
    if (typeof point?.laser_on === "boolean") {
        sourceList.push("toolpath.laser_on");
    }

    let identifiedStatus = "unknown";
    let statusLabel = "未知狀態";
    let confidence = 0;
    let reason = "目前播放點的同步證據不足，還不能穩定辨識製程狀態。";

    if (gHigh === null) {
        identifiedStatus = "not_identified";
        statusLabel = "尚未辨識";
        reason = "目前播放點沒有有效的熱像溫度資料，無法建立製程狀態。";
    } else if (!laserOn || feedRate === 0) {
        identifiedStatus = "abnormal_heat_or_process";
        statusLabel = "製程異常";
        confidence = status.key === "abnormal" ? 0.88 : 0.74;
        reason = "同步播放點顯示熱像與預期沉積狀態不一致，建議先視為異常點並檢查送粉、噴嘴與雷射狀態。";
    } else if (status.key === "good") {
        identifiedStatus = "normal_deposition";
        statusLabel = "正常沉積";
        confidence = 0.72;
        reason = "G_High 落在穩定區間，且目前點位處於有效沉積路徑，可先視為正常沉積狀態。";
    } else if (status.key === "warning") {
        identifiedStatus = "heat_accumulation_warning";
        statusLabel = "熱累積警示";
        confidence = 0.78;
        reason = "G_High 已進入警示帶，代表熱輸入或冷卻行為開始偏離正常沉積基準。";
    } else if (status.key === "abnormal") {
        identifiedStatus = "abnormal_heat_or_process";
        statusLabel = "異常熱輸入 / 製程異常";
        confidence = 0.9;
        reason = "G_High 已落入異常帶，應優先視為異常製程點並交由後續推論與調參模組處理。";
    }

    if (geometry?.sourceMode === "ratio-fallback" && confidence > 0) {
        confidence = Math.max(0, confidence - 0.06);
    }

    return normalizeIdentificationResult(ctx, {
        schema_version: "ded-identification-result-v1",
        identification_stage: "playback_point_v1",
        identified_status: identifiedStatus,
        status_label: statusLabel,
        status_confidence: confidence,
        status_source: sourceList,
        status_reason: reason,
        status_evidence: {
            g_high: gHigh,
            layer_index: Number(geometry.layerIndex || ctx.selectedLayerIndex || 0) || null,
            timestamp_ms: timestampMs,
            x_mm: asNumberOrNull(point?.x_mm),
            y_mm: asNumberOrNull(point?.y_mm),
            z_mm: asNumberOrNull(point?.z_mm),
            laser_on: typeof point?.laser_on === "boolean" ? point.laser_on : true,
            feed_rate_mm_min: feedRate,
        },
        time_context: {
            source: "heat_playback",
            playback_progress: asNumberOrNull(snapshot.progressRatio),
            time_label: ctx.formatChartTime(timestampMs),
        },
    });
}

function defaultRecommendationCopy(stateKey) {
    if (stateKey === "good") {
        return "熱輸入維持在穩定區間，優先維持目前參數，並持續監看同 layer 後段是否仍穩定。";
    }
    if (stateKey === "warning") {
        return "建議先做小幅調整，優先比對同路徑位置基準，再微調雷射功率與進給速度。";
    }
    if (stateKey === "abnormal") {
        return "建議先檢查噴嘴、送粉與雷射狀態，再決定是否降低熱輸入或暫停製程。";
    }
    return "目前證據不足，請先確認同步熱像、Edge 與 MPF 資料是否完整。";
}

function resolveInferenceStateLabel(stateKey, rule) {
    if (rule?.state_label) {
        return rule.state_label;
    }
    if (stateKey === "good") {
        return "優良";
    }
    if (stateKey === "warning") {
        return "警示";
    }
    if (stateKey === "abnormal") {
        return "異常";
    }
    if (stateKey === "unknown") {
        return "未知";
    }
    return "尚未推論";
}

function buildPlaybackInferenceResult(ctx, geometry, snapshot, identificationResult) {
    if (!geometry || !snapshot?.headPoint) {
        return normalizeInferenceResult(ctx, ctx.state.inference_current_result);
    }

    const point = snapshot.headPoint;
    const identification = normalizeIdentificationResult(ctx, identificationResult || ctx.currentIdentificationResult);
    const inferenceState = mapIdentificationStatusToInferenceState(identification.identified_status);
    const ruleTable = ctx.state.inference_rule_table || {};
    const rule = findRuleForState(ruleTable, inferenceState);
    const changes = inferenceState === "good" || inferenceState === "warning" || inferenceState === "abnormal"
        ? (Array.isArray(rule?.recommended_parameter_change) && rule.recommended_parameter_change.length
            ? rule.recommended_parameter_change
            : fallbackParameterChanges(inferenceState))
        : [];
    const relatedParameters = changes
        .map((change) => String(change.parameter || "").trim())
        .filter(Boolean);

    return normalizeInferenceResult(ctx, {
        schema_version: "ded-inference-result-v1",
        inference_stage: identification.identified_status === "not_identified"
            ? "format_v1"
            : "identification_driven_preview",
        state: inferenceState,
        state_label: resolveInferenceStateLabel(inferenceState, rule),
        cause: identification.status_reason || rule?.cause_hint || "目前尚未取得足夠的辨識原因。",
        confidence: identification.status_confidence || 0,
        recommended_action: rule?.diagnosis || defaultRecommendationCopy(inferenceState),
        recommended_parameter_change: changes,
        related_rule: rule?.rule_id || null,
        related_parameter: relatedParameters,
        evidence: {
            g_high: asNumberOrNull(point?.heat_g_high),
            layer_index: Number(geometry.layerIndex || ctx.selectedLayerIndex || 0) || null,
            timestamp_ms: asNumberOrNull(point?.heat_timestamp_ms ?? point?.timestamp_ms),
            x_mm: asNumberOrNull(point?.x_mm),
            y_mm: asNumberOrNull(point?.y_mm),
            z_mm: asNumberOrNull(point?.z_mm),
            identified_status: identification.identified_status,
        },
        time_context: {
            source: "heat_playback",
            playback_progress: asNumberOrNull(snapshot.progressRatio),
            time_label: ctx.formatChartTime(point?.heat_timestamp_ms ?? point?.timestamp_ms ?? null),
        },
    });
}

function renderSourcePills(sourceList) {
    if (!Array.isArray(sourceList) || !sourceList.length) {
        return `<p class="inference-result-muted">目前沒有可顯示的辨識來源。</p>`;
    }
    return `
        <div class="inference-source-pill-row">
            ${sourceList.map((source) => `<span class="inference-source-pill">${source}</span>`).join("")}
        </div>
    `;
}

function renderParameterChangeList(changes) {
    if (!Array.isArray(changes) || !changes.length) {
        return `<p class="inference-result-muted">目前沒有建議調整的參數。</p>`;
    }
    const directionLabels = {
        maintain: "維持",
        increase: "提高",
        decrease: "降低",
        inspect: "檢查",
        mark: "標記",
    };
    return `
        <div class="inference-result-change-list">
            ${changes.map((change) => `
                <article class="inference-result-change-card">
                    <span>${change.label || change.parameter || "-"}</span>
                    <strong>${directionLabels[change.direction] || change.direction || "-"}</strong>
                    <small>${change.magnitude || "-"} ${change.unit || ""}</small>
                </article>
            `).join("")}
        </div>
    `;
}

function identificationStageLabel(stage) {
    const labels = {
        format_v1: "等待辨識",
        playback_point_v1: "同步辨識",
    };
    return labels[stage] || stage || "未定義";
}

function inferenceStageLabel(stage) {
    const labels = {
        format_v1: "等待推論",
        threshold_preview: "閾值預覽",
        identification_driven_preview: "辨識驅動預覽",
    };
    return labels[stage] || stage || "未定義";
}

function identificationHeadline(result) {
    if (result.identified_status === "normal_deposition") {
        return "正常沉積：目前製程穩定";
    }
    if (result.identified_status === "heat_accumulation_warning") {
        return "熱累積警示：熱輸入開始偏高";
    }
    if (result.identified_status === "abnormal_heat_or_process") {
        return "異常點：請優先檢查製程狀態";
    }
    if (result.identified_status === "not_identified") {
        return "尚未辨識目前製程狀態";
    }
    return `${result.status_label || "未知狀態"}：目前證據不足`;
}

function recommendationHeadline(result) {
    if (result.state === "good") {
        return "優良：維持目前製程參數";
    }
    if (result.state === "warning") {
        return "警示：建議微調製程參數";
    }
    if (result.state === "abnormal") {
        return "異常：建議立即檢查並調整";
    }
    if (result.state === "not_evaluated") {
        return "尚未產生參數建議";
    }
    return `${result.state_label || "未知"}：暫時無法給出建議`;
}

function renderInferenceCurrentResult(ctx) {
    const container = ctx.byId("inference-current-result");
    if (!container) {
        return;
    }

    const identification = normalizeIdentificationResult(ctx, ctx.currentIdentificationResult);
    const result = normalizeInferenceResult(ctx, ctx.currentInferenceResult);
    const identificationEvidence = identification.status_evidence || {};
    const inferenceEvidence = result.evidence || {};
    const identificationConfidenceText = `${Math.round(ctx.clamp(identification.status_confidence, 0, 1) * 100)}%`;
    const recommendationConfidenceText = `${Math.round(ctx.clamp(result.confidence, 0, 1) * 100)}%`;

    container.innerHTML = `
        <article class="inference-result-card is-${identificationTone(identification)}">
            <section class="inference-result-section">
                <div class="inference-result-head">
                    <div>
                        <p class="inference-rule-kicker">Identification / Current Process State</p>
                        <h3>${identificationHeadline(identification)}</h3>
                    </div>
                    <span class="inference-result-state">${identificationStageLabel(identification.identification_stage)}</span>
                </div>
                <p class="inference-result-cause">${identification.status_reason}</p>
                <div class="inference-result-meta-grid">
                    <article>
                        <span>辨識信心</span>
                        <strong>${identificationConfidenceText}</strong>
                    </article>
                    <article>
                        <span>目前狀態</span>
                        <strong>${identification.status_label}</strong>
                    </article>
                    <article>
                        <span>G_High</span>
                        <strong>${ctx.formatNumber(identificationEvidence.g_high, 2)} °C</strong>
                    </article>
                    <article>
                        <span>Playback Time</span>
                        <strong>${identification.time_context?.time_label || "-"}</strong>
                    </article>
                </div>
                ${renderSourcePills(identification.status_source)}
            </section>

            <div class="inference-section-divider"></div>

            <section class="inference-result-section">
                <div class="inference-result-head">
                    <div>
                        <p class="inference-rule-kicker">Inference / Process Recommendation</p>
                        <h3>${recommendationHeadline(result)}</h3>
                    </div>
                    <span class="inference-result-state">${inferenceStageLabel(result.inference_stage)}</span>
                </div>
                <p class="inference-result-cause">${result.cause}</p>
                <div class="inference-result-meta-grid">
                    <article>
                        <span>推論信心</span>
                        <strong>${recommendationConfidenceText}</strong>
                    </article>
                    <article>
                        <span>對應規則</span>
                        <strong>${result.related_rule || "-"}</strong>
                    </article>
                    <article>
                        <span>建議項目</span>
                        <strong>${ctx.formatInteger(result.recommended_parameter_change?.length || 0)} 項</strong>
                    </article>
                    <article>
                        <span>辨識狀態</span>
                        <strong>${identification.status_label}</strong>
                    </article>
                </div>
                <div class="inference-result-action">
                    <strong>目前建議</strong>
                    <p>${result.recommended_action}</p>
                </div>
                ${renderParameterChangeList(result.recommended_parameter_change)}
                <p class="inference-result-muted">
                    座標 X ${ctx.formatNumber(inferenceEvidence.x_mm, 2)} / Y ${ctx.formatNumber(inferenceEvidence.y_mm, 2)} / Z ${ctx.formatNumber(inferenceEvidence.z_mm, 3)} mm
                </p>
            </section>
        </article>
    `;
}

function renderFieldPills(fields) {
    return fields.map((field) => `
        <span class="inference-rule-pill ${field.available ? "is-available" : "is-missing"}">
            <strong>${field.source}</strong>
            <span>${field.label}</span>
        </span>
    `).join("");
}

function renderBasisCards(basisList) {
    return basisList.map((basis) => `
        <article class="inference-basis-card">
            <strong>${basis.label}</strong>
            <p>${basis.description || "-"}</p>
        </article>
    `).join("");
}

function renderRuleCards(rules) {
    return rules.map((rule) => {
        const actions = Array.isArray(rule.recommended_adjustments) ? rule.recommended_adjustments : [];
        return `
            <article class="inference-rule-card is-${rule.state_key || "unknown"}">
                <div class="inference-rule-card-head">
                    <strong>${rule.state_label || "-"}</strong>
                    <span class="inference-rule-card-range">${rule.range_label || rule.threshold_text || "-"}</span>
                </div>
                <p class="inference-rule-card-diagnosis">${rule.diagnosis || "-"}</p>
                <p class="inference-rule-card-cause">${rule.cause_hint || "-"}</p>
                <ul class="inference-rule-action-list">
                    ${actions.map((action) => `<li>${action}</li>`).join("")}
                </ul>
            </article>
        `;
    }).join("");
}

export function initInferenceSection(ctx) {
    ctx.currentIdentificationResult = normalizeIdentificationResult(ctx, ctx.state.identification_current_result);
    ctx.currentInferenceResult = normalizeInferenceResult(ctx, ctx.state.inference_current_result);

    function updateInferencePlaybackResult(geometry, snapshot) {
        ctx.currentIdentificationResult = buildPlaybackIdentificationResult(ctx, geometry, snapshot);
        ctx.currentInferenceResult = buildPlaybackInferenceResult(
            ctx,
            geometry,
            snapshot,
            ctx.currentIdentificationResult,
        );
        renderInferenceCurrentResult(ctx);
    }

    function renderInferenceRuleTable() {
        const panel = ctx.byId("inference-rule-panel");
        if (!panel) {
            return;
        }

        const ruleTable = ctx.state.inference_rule_table || {};
        const rules = Array.isArray(ruleTable.rules) ? ruleTable.rules : [];
        const basisList = Array.isArray(ruleTable.decision_basis) ? ruleTable.decision_basis : [];
        const fields = Array.isArray(ruleTable.input_fields) ? ruleTable.input_fields : [];
        const targets = Array.isArray(ruleTable.adaptation_targets) ? ruleTable.adaptation_targets : [];

        if (!rules.length) {
            panel.innerHTML = `
                <div class="inference-rule-empty">
                    <strong>尚未建立 Ontology 規則表</strong>
                    <p>請先確認後端 payload 是否已提供 inference rule table。</p>
                </div>
            `;
            return;
        }

        const availableCount = fields.filter((field) => field.available).length;
        panel.innerHTML = `
            <div class="inference-rule-overview">
                <div class="inference-rule-copy">
                    <p class="inference-rule-kicker">Inference / Adaptation</p>
                    <p class="inference-rule-title">製程狀態與參數建議</p>
                    <p class="inference-rule-summary">
                        先用同步播放點建立目前製程狀態，再把辨識結果交給規則表，輸出可解釋的調參建議。
                    </p>
                </div>
                <span class="inference-rule-badge">即時預覽</span>
            </div>

            <div id="inference-current-result" class="inference-current-result"></div>

            <details class="inference-rule-details">
                <summary>
                    <span>查看判斷依據 / Knowledge Rules</span>
                    <strong>${ctx.formatInteger(rules.length)} rules</strong>
                </summary>

                <div class="inference-rule-metric-strip">
                    ${renderMetricCards(ctx, ruleTable.data_summary || {})}
                </div>

                <div class="inference-rule-field-block">
                    <div class="inference-rule-section-head">
                        <strong>目前可讀取輸入</strong>
                        <span>${ctx.formatInteger(availableCount)} / ${ctx.formatInteger(fields.length)} 項</span>
                    </div>
                    <div class="inference-rule-pill-row">
                        ${renderFieldPills(fields)}
                    </div>
                </div>

                <div class="inference-rule-basis-block">
                    <div class="inference-rule-section-head">
                        <strong>判斷基準</strong>
                        <span>${ctx.formatInteger(basisList.length)} 層</span>
                    </div>
                    <div class="inference-basis-grid">
                        ${renderBasisCards(basisList)}
                    </div>
                </div>

                <div class="inference-rule-table-block">
                    <div class="inference-rule-section-head">
                        <strong>Rule Table</strong>
                        <span>${targets.map((target) => target.label).join(" / ")}</span>
                    </div>
                    <div class="inference-rule-grid">
                        ${renderRuleCards(rules)}
                    </div>
                </div>
            </details>
        `;
        renderInferenceCurrentResult(ctx);
    }

    return {
        renderInferenceRuleTable,
        updateInferencePlaybackResult,
    };
}
