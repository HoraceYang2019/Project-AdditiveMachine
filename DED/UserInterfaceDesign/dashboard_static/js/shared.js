import {
    createChartViewState,
    formatNumber,
    formatInteger,
    formatSignedMilliseconds,
    isRelativeTimestamp,
    formatRelativeTimestamp,
    formatChartTime,
    formatFullTimestamp,
    clamp,
    clampIndex,
} from "./shared-format.js";
import {
    setText,
    setStatus,
    setEditorStatus,
    normalizeMpfFileName,
    updateEditorLineCount,
    setEditorDownloadLink,
    syncEditorControls,
    setEditorBusy,
    setEditorEditable,
} from "./shared-editor.js";
import {
    bindInteractiveChart,
    resetChartView,
    clampChartView,
    zoomChartView,
    buildTimeTicks,
    sliceVisiblePoints,
    buildPolylinePath,
    buildPointKey,
    projectPoint,
    createLineMarkup,
    interpolatePoint,
    coordinateHeatColor,
    cancelAnimationFrameLoop,
    pauseAnimationPlayback,
} from "./shared-chart.js";

function buildHeatAlertConfig(ruleTable) {
    const fallbackBands = [
        {
            key: "good",
            label: "優良",
            rangeLabel: "< 1300 °C",
            description: "目前溫度落在穩定區間。",
            badgeClass: "is-good",
            minInclusive: null,
            maxExclusive: 1300,
        },
        {
            key: "warning",
            label: "警示",
            rangeLabel: "1300 至 1500 °C",
            description: "目前溫度偏高，建議檢查是否有熱累積或參數漂移。",
            badgeClass: "is-warning",
            minInclusive: 1300,
            maxExclusive: 1500,
        },
        {
            key: "abnormal",
            label: "異常",
            rangeLabel: ">= 1500 °C",
            description: "目前溫度過高，應立即檢查製程狀態與調整參數。",
            badgeClass: "is-abnormal",
            minInclusive: 1500,
            maxExclusive: null,
        },
    ];

    const configuredRules = Array.isArray(ruleTable?.rules) ? ruleTable.rules : [];
    const configuredBands = configuredRules
        .map((rule) => {
            if (!rule?.state_key) {
                return null;
            }
            return {
                key: String(rule.state_key),
                label: String(rule.state_label || rule.state_key),
                rangeLabel: String(rule.range_label || rule.threshold_text || "-"),
                description: String(rule.diagnosis || rule.cause_hint || ""),
                badgeClass: `is-${String(rule.state_key)}`,
                minInclusive: Number.isFinite(Number(rule.min_inclusive)) ? Number(rule.min_inclusive) : null,
                maxExclusive: Number.isFinite(Number(rule.max_exclusive)) ? Number(rule.max_exclusive) : null,
            };
        })
        .filter(Boolean);

    const bands = configuredBands.length ? configuredBands : fallbackBands;
    return {
        thresholds: {
            goodMax: Number.isFinite(Number(ruleTable?.thresholds?.good_max_exclusive))
                ? Number(ruleTable.thresholds.good_max_exclusive)
                : 1300,
            abnormalMin: Number.isFinite(Number(ruleTable?.thresholds?.abnormal_min_inclusive))
                ? Number(ruleTable.thresholds.abnormal_min_inclusive)
                : 1500,
        },
        bands,
    };
}

function classifyHeatAlert(ctx, value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return {
            key: "unknown",
            label: "未知",
            rangeLabel: "-",
            description: "目前沒有可用的熱像數值，無法判定狀態。",
            badgeClass: "is-unknown",
        };
    }
    for (const band of ctx.heatAlertBands) {
        const minInclusive = Number.isFinite(Number(band.minInclusive)) ? Number(band.minInclusive) : null;
        const maxExclusive = Number.isFinite(Number(band.maxExclusive)) ? Number(band.maxExclusive) : null;
        const meetsMin = minInclusive === null || numeric >= minInclusive;
        const meetsMax = maxExclusive === null || numeric < maxExclusive;
        if (meetsMin && meetsMax) {
            return { ...band, value: numeric };
        }
    }
    if (numeric <= ctx.heatAlertThresholds.goodMax) {
        return { ...ctx.heatAlertBands.find((item) => item.key === "good"), value: numeric };
    }
    if (numeric < ctx.heatAlertThresholds.abnormalMin) {
        return { ...ctx.heatAlertBands.find((item) => item.key === "warning"), value: numeric };
    }
    return { ...ctx.heatAlertBands.find((item) => item.key === "abnormal"), value: numeric };
}

function summarizeHeatAlertSamples(ctx, points, valueSelector = (point) => point) {
    const summary = {
        total: 0,
        good: 0,
        warning: 0,
        abnormal: 0,
    };
    for (const point of points || []) {
        const numeric = Number(valueSelector(point));
        if (!Number.isFinite(numeric)) {
            continue;
        }
        const level = classifyHeatAlert(ctx, numeric).key;
        if (level === "good" || level === "warning" || level === "abnormal") {
            summary[level] += 1;
            summary.total += 1;
        }
    }
    return summary;
}

function renderPointDetail(ctx, containerId, selectedPoint, emptyMessage) {
    const container = ctx.byId(containerId);
    if (!container) {
        return;
    }
    if (!selectedPoint) {
        container.innerHTML = `<div class="chart-detail-empty">${emptyMessage}</div>`;
        return;
    }
    const rows = Array.isArray(selectedPoint.rows) ? selectedPoint.rows : [];
    container.innerHTML = `
        <div class="chart-detail-header">
            <strong>${selectedPoint.title || "資料點"}</strong>
            <span>${selectedPoint.seriesLabel || "-"}</span>
        </div>
        <div class="chart-detail-grid">
            ${rows.map((row) => `
                <article class="chart-detail-card">
                    <span>${row.label}</span>
                    <strong>${row.value}</strong>
                </article>
            `).join("")}
        </div>
    `;
}

export async function createDashboardContext() {
    const dashboardUrl = window.location.search
        ? `/api/dashboard-data${window.location.search}`
        : "/api/dashboard-data";
    const response = await fetch(dashboardUrl);
    const state = await response.json();
    const heatAlertConfig = buildHeatAlertConfig(state.inference_rule_table);

    const ctx = {
        state,
        byId: (id) => document.getElementById(id),
        selectedLayerIndex: state.layers?.[0]?.layer_index ?? 1,
        progressSliderMax: 1000,
        playback: {
            isPlaying: false,
            speedMultiplier: 1,
            progressUnits: 0,
            totalUnits: 0,
            layerKey: "",
            geometry: null,
            rafId: 0,
            lastFrameMs: 0,
        },
        coordinatePlayback: {
            isPlaying: false,
            speedMultiplier: 1,
            progressUnits: 0,
            totalUnits: 0,
            geometryKey: "",
            geometry: null,
            rafId: 0,
            lastFrameMs: 0,
        },
        editor: {
            sourceText: "",
            sourceFileName: "",
            canEdit: false,
            isBusy: false,
        },
        alignmentManualOffsetMs: Number(state.alignment?.manual_offset_default_ms || 0),
        thermalChartView: createChartViewState(),
        alignmentChartView: createChartViewState(),
        selectedThermalPoint: null,
        selectedAlignmentPoint: null,
        heatAlertThresholds: heatAlertConfig.thresholds,
        heatAlertBands: [
            {
                key: "good",
                label: "優良",
                rangeLabel: "<= 1300 °C",
                description: "目前熱像值位於穩定製程區間。",
                badgeClass: "is-good",
            },
            {
                key: "warning",
                label: "警示",
                rangeLabel: "1300 < T < 1500 °C",
                description: "目前熱像值偏高，建議持續觀察。",
                badgeClass: "is-warning",
            },
            {
                key: "abnormal",
                label: "異常",
                rangeLabel: ">= 1500 °C",
                description: "目前熱像值明顯偏高，可能存在製程異常。",
                badgeClass: "is-abnormal",
            },
        ],
        heatAlertBands: heatAlertConfig.bands,
        segmentTypeLabels: {
            deposit: "沉積",
            travel: "移動",
            retract: "抬刀",
            approach: "進刀",
            unknown: "未知",
        },
        eventActionLabels: {
            set: "設定",
            clear: "清除",
        },
        noteLabels: {
            Dwell: "停留",
            "Powder supply": "送粉",
            "LASER safety lock on": "雷射安全鎖",
            "WAIT FOR THE POWDER REFILL ALL THE SPACE IN TUBE": "等待粉末重新填滿管路",
            "LASER ON": "雷射開啟",
            "LASER OFF": "雷射關閉",
            "Laser on": "雷射開啟",
            "Laser off": "雷射關閉",
        },
    };

    ctx.layerRecord = () => (
        ctx.state.layers.find((item) => Number(item.layer_index) === Number(ctx.selectedLayerIndex))
        || ctx.state.layers[0]
        || null
    );
    ctx.formatNumber = formatNumber;
    ctx.formatInteger = formatInteger;
    ctx.formatSignedMilliseconds = formatSignedMilliseconds;
    ctx.formatChartTime = formatChartTime;
    ctx.formatFullTimestamp = formatFullTimestamp;
    ctx.formatRelativeTimestamp = formatRelativeTimestamp;
    ctx.isRelativeTimestamp = isRelativeTimestamp;
    ctx.clamp = clamp;
    ctx.clampIndex = clampIndex;
    ctx.setText = (id, text) => setText(ctx.byId, id, text);
    ctx.setStatus = (text, type = "info") => setStatus(ctx.byId, text, type);
    ctx.setEditorStatus = (text, type = "info") => setEditorStatus(ctx.byId, text, type);
    ctx.translateSegmentType = (value) => ctx.segmentTypeLabels[value] || value || "-";
    ctx.translateEventAction = (value) => ctx.eventActionLabels[value] || value || "-";
    ctx.translateNote = (value) => ctx.noteLabels[value] || value || "-";
    ctx.normalizeMpfFileName = normalizeMpfFileName;
    ctx.updateEditorLineCount = (text) => updateEditorLineCount(ctx, text);
    ctx.setEditorDownloadLink = (url, label, enabled = true) => setEditorDownloadLink(ctx, url, label, enabled);
    ctx.syncEditorControls = () => syncEditorControls(ctx);
    ctx.setEditorBusy = (isBusy) => setEditorBusy(ctx, isBusy);
    ctx.setEditorEditable = (canEdit) => setEditorEditable(ctx, canEdit);
    ctx.classifyHeatAlert = (value) => classifyHeatAlert(ctx, value);
    ctx.summarizeHeatAlertSamples = (points, selector = (point) => point) => summarizeHeatAlertSamples(ctx, points, selector);
    ctx.resetChartView = resetChartView;
    ctx.clampChartView = clampChartView;
    ctx.zoomChartView = zoomChartView;
    ctx.buildTimeTicks = buildTimeTicks;
    ctx.sliceVisiblePoints = sliceVisiblePoints;
    ctx.buildPolylinePath = buildPolylinePath;
    ctx.buildPointKey = buildPointKey;
    ctx.renderPointDetail = (containerId, selectedPoint, emptyMessage) => renderPointDetail(ctx, containerId, selectedPoint, emptyMessage);
    ctx.bindInteractiveChart = (options) => bindInteractiveChart(ctx, options);
    ctx.projectPoint = projectPoint;
    ctx.createLineMarkup = createLineMarkup;
    ctx.interpolatePoint = interpolatePoint;
    ctx.coordinateHeatColor = coordinateHeatColor;
    ctx.cancelPlaybackLoop = () => cancelAnimationFrameLoop(ctx.playback);
    ctx.pausePlayback = () => pauseAnimationPlayback(ctx.playback);
    ctx.cancelCoordinatePlaybackLoop = () => cancelAnimationFrameLoop(ctx.coordinatePlayback);
    ctx.pauseCoordinatePlayback = () => pauseAnimationPlayback(ctx.coordinatePlayback);

    return ctx;
}
