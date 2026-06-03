export function initAlignmentSection(ctx) {
    function syncAlignmentControls(alignment, enabled) {
        const range = ctx.byId("alignment-offset-range");
        const numberInput = ctx.byId("alignment-offset-number");
        const autoButton = ctx.byId("alignment-auto-button");
        const offsetLabel = ctx.byId("alignment-offset-label");
        const methodLabel = ctx.byId("alignment-method-label");
        const offsetRange = Math.max(Number(alignment?.manual_offset_range_ms || 5000), 0);
        const autoOffsetMs = Number(alignment?.auto_offset_ms || 0);

        ctx.alignmentManualOffsetMs = ctx.clamp(ctx.alignmentManualOffsetMs, -offsetRange, offsetRange);

        if (range) {
            range.min = String(-offsetRange);
            range.max = String(offsetRange);
            range.step = "10";
            range.value = String(ctx.alignmentManualOffsetMs);
            range.disabled = !enabled;
        }
        if (numberInput) {
            numberInput.min = String(-offsetRange);
            numberInput.max = String(offsetRange);
            numberInput.step = "10";
            numberInput.value = String(ctx.alignmentManualOffsetMs);
            numberInput.disabled = !enabled;
        }
        if (autoButton) {
            autoButton.disabled = !enabled;
        }
        if (offsetLabel) {
            offsetLabel.textContent = `目前 ${ctx.formatSignedMilliseconds(autoOffsetMs + ctx.alignmentManualOffsetMs)}`;
        }
        if (methodLabel) {
            const pieces = [];
            if (alignment?.method_label) {
                pieces.push(alignment.method_label);
            }
            if (enabled) {
                pieces.push(`自動 ${ctx.formatSignedMilliseconds(autoOffsetMs)}`);
                pieces.push(`手動 ${ctx.formatSignedMilliseconds(ctx.alignmentManualOffsetMs)}`);
            }
            methodLabel.textContent = pieces.join(" / ") || "尚未建立對齊";
        }
    }

    function bindAlignmentControls() {
        const range = ctx.byId("alignment-offset-range");
        const numberInput = ctx.byId("alignment-offset-number");
        const autoButton = ctx.byId("alignment-auto-button");

        if (range && !range.dataset.bound) {
            range.addEventListener("input", (event) => {
                ctx.alignmentManualOffsetMs = Number(event.target.value) || 0;
                ctx.selectedAlignmentPoint = null;
                renderAlignment();
                ctx.renderCoordinateAlignment?.();
            });
            range.dataset.bound = "true";
        }
        if (numberInput && !numberInput.dataset.bound) {
            numberInput.addEventListener("input", (event) => {
                ctx.alignmentManualOffsetMs = Number(event.target.value) || 0;
                ctx.selectedAlignmentPoint = null;
                renderAlignment();
                ctx.renderCoordinateAlignment?.();
            });
            numberInput.dataset.bound = "true";
        }
        if (autoButton && !autoButton.dataset.bound) {
            autoButton.addEventListener("click", () => {
                ctx.alignmentManualOffsetMs = Number(ctx.state.alignment?.manual_offset_default_ms || 0);
                ctx.selectedAlignmentPoint = null;
                renderAlignment();
                ctx.renderCoordinateAlignment?.();
            });
            autoButton.dataset.bound = "true";
        }
    }

    function renderAlignment() {
        const alignment = ctx.state.alignment || {};
        const statsNode = ctx.byId("alignment-stats");
        const svg = ctx.byId("alignment-chart");
        if (!svg || !statsNode) {
            return;
        }
        const edgeLabel = alignment.edge_label || ctx.state.edge?.value_label || "Edge";
        const thermalTrace = Array.isArray(ctx.state.thermal?.thermal_trace) ? ctx.state.thermal.thermal_trace : [];
        const edgeTrace = Array.isArray(ctx.state.edge?.edge_trace) ? ctx.state.edge.edge_trace : [];
        const autoOffsetMs = Number(alignment.auto_offset_ms || 0);
        const appliedOffsetMs = autoOffsetMs + ctx.alignmentManualOffsetMs;
        const thermalFeature = alignment.thermal_feature || null;
        const machineFeature = alignment.machine_feature || null;

        const stats = alignment.available
            ? [
                { label: "對齊方法", value: alignment.method_label || "-" },
                { label: "自動 Offset", value: ctx.formatSignedMilliseconds(autoOffsetMs) },
                { label: "手動微調", value: ctx.formatSignedMilliseconds(ctx.alignmentManualOffsetMs) },
                { label: "總 Offset", value: ctx.formatSignedMilliseconds(appliedOffsetMs) },
                { label: "熱像特徵", value: thermalFeature?.time || "-" },
                { label: "機台特徵", value: machineFeature?.time || "-" },
            ]
            : [
                { label: "對齊狀態", value: alignment.message || "尚未建立對齊" },
                { label: "熱像來源", value: ctx.state.thermal?.source_file || "-" },
                { label: "Edge 來源", value: ctx.state.edge?.source_file || "-" },
                { label: "Edge 欄位", value: edgeLabel },
            ];

        statsNode.replaceChildren(
            ...stats.map((metric) => {
                const article = document.createElement("article");
                article.className = "metric-card";
                article.innerHTML = `<span>${metric.label}</span><strong>${metric.value}</strong>`;
                return article;
            }),
        );

        const enabled = Boolean(alignment.available && thermalTrace.length && edgeTrace.length);
        syncAlignmentControls(alignment, enabled);

        if (!enabled) {
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">${alignment.message || "尚未建立對齊資料"}</text>`;
            ctx.setText("alignment-window-label", "尚未建立時間視窗");
            ctx.renderPointDetail("alignment-point-detail", null, "點選對齊圖中的熱像或 Edge 資料點後，這裡會顯示完整時間戳與數值。");
            return;
        }

        ctx.clampChartView(ctx.alignmentChartView);

        const rawThermalSeries = thermalTrace
            .map((item) => ({
                timestampMs: Number(item.timestamp_ms),
                originalTimestampMs: Number(item.timestamp_ms),
                value: Number(item.g_high),
            }))
            .filter((item) => Number.isFinite(item.timestampMs) && Number.isFinite(item.value));
        const alignedThermalSeries = thermalTrace
            .map((item) => ({
                timestampMs: Number(item.timestamp_ms) + appliedOffsetMs,
                originalTimestampMs: Number(item.timestamp_ms),
                value: Number(item.g_high),
            }))
            .filter((item) => Number.isFinite(item.timestampMs) && Number.isFinite(item.value));
        const edgeSeries = edgeTrace
            .map((item) => ({
                timestampMs: Number(item.timestamp_ms),
                value: Number(item.value),
            }))
            .filter((item) => Number.isFinite(item.timestampMs) && Number.isFinite(item.value));

        if (!rawThermalSeries.length || !alignedThermalSeries.length || !edgeSeries.length) {
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">缺少足夠的對齊樣本</text>`;
            ctx.setText("alignment-window-label", "尚未建立時間視窗");
            ctx.renderPointDetail("alignment-point-detail", null, "點選對齊圖中的熱像或 Edge 資料點後，這裡會顯示完整時間戳與數值。");
            return;
        }

        const allTimestamps = rawThermalSeries.concat(alignedThermalSeries, edgeSeries).map((item) => item.timestampMs);
        const width = 900;
        const height = 320;
        const left = 76;
        const right = 76;
        const top = 28;
        const bottom = 58;
        const plotWidth = width - left - right;
        const plotHeight = height - top - bottom;
        const minTimestamp = Math.min(...allTimestamps);
        const maxTimestamp = Math.max(...allTimestamps);
        const totalSpan = Math.max(maxTimestamp - minTimestamp, 1);
        const visibleStart = minTimestamp + totalSpan * ctx.alignmentChartView.startRatio;
        const visibleEnd = minTimestamp + totalSpan * ctx.alignmentChartView.endRatio;
        const visibleRawThermal = rawThermalSeries.filter((point) => point.timestampMs >= visibleStart && point.timestampMs <= visibleEnd);
        const visibleAlignedThermal = ctx.sliceVisiblePoints(alignedThermalSeries, visibleStart, visibleEnd);
        const visibleEdge = ctx.sliceVisiblePoints(edgeSeries, visibleStart, visibleEnd);
        const thermalValues = visibleRawThermal.concat(visibleAlignedThermal).map((point) => point.value);
        const edgeValues = visibleEdge.map((point) => point.value);
        const thermalMin = Math.min(...thermalValues);
        const thermalMax = Math.max(...thermalValues);
        const edgeMin = Math.min(...edgeValues);
        const edgeMax = Math.max(...edgeValues);
        const thermalSpan = Math.max(thermalMax - thermalMin, 1);
        const edgeSpan = Math.max(edgeMax - edgeMin, 1);
        const scaleX = (timestampMs) => left + ((timestampMs - visibleStart) / Math.max(visibleEnd - visibleStart, 1)) * plotWidth;
        const scaleThermalY = (value) => top + (1 - (value - thermalMin) / thermalSpan) * plotHeight;
        const scaleEdgeY = (value) => top + (1 - (value - edgeMin) / edgeSpan) * plotHeight;
        const visibleTickSource = Array.from(new Map(
            visibleAlignedThermal.concat(visibleEdge).map((point) => [Math.round(point.timestampMs), point]),
        ).values());
        const tickTimestamps = ctx.buildTimeTicks(
            visibleStart,
            visibleEnd,
            6,
            visibleTickSource.length <= 8 ? visibleTickSource : [],
        );
        const rawThermalPath = ctx.buildPolylinePath(visibleRawThermal, scaleX, scaleThermalY);
        const alignedThermalPath = ctx.buildPolylinePath(visibleAlignedThermal, scaleX, scaleThermalY);
        const edgePath = ctx.buildPolylinePath(visibleEdge, scaleX, scaleEdgeY);

        const interactivePoints = [];
        const rawThermalCircles = visibleRawThermal.map((point) => {
            const pointId = interactivePoints.length;
            const key = ctx.buildPointKey("thermal-raw", point.timestampMs);
            interactivePoints.push({
                key,
                title: "熱像原始時間",
                seriesLabel: "Raw Thermal",
                rows: [
                    { label: "顯示時間", value: ctx.formatFullTimestamp(point.timestampMs) },
                    { label: "原始時間", value: ctx.formatFullTimestamp(point.originalTimestampMs) },
                    { label: "G_High", value: ctx.formatNumber(point.value, 2) },
                    { label: "Offset", value: "0 ms" },
                ],
            });
            const isSelected = ctx.selectedAlignmentPoint?.key === key;
            return `
                <circle
                    cx="${scaleX(point.timestampMs).toFixed(2)}"
                    cy="${scaleThermalY(point.value).toFixed(2)}"
                    r="${isSelected ? "4.8" : "3.3"}"
                    class="thermal-point-raw chart-point${isSelected ? " chart-point-selected" : ""}"
                    data-point-id="${pointId}"
                />
            `;
        }).join("");

        const alignedThermalCircles = visibleAlignedThermal.map((point) => {
            const pointId = interactivePoints.length;
            const key = ctx.buildPointKey("thermal-aligned", point.timestampMs, point.originalTimestampMs);
            interactivePoints.push({
                key,
                title: "熱像對齊後",
                seriesLabel: "Aligned Thermal",
                rows: [
                    { label: "顯示時間", value: ctx.formatFullTimestamp(point.timestampMs) },
                    { label: "原始時間", value: ctx.formatFullTimestamp(point.originalTimestampMs) },
                    { label: "G_High", value: ctx.formatNumber(point.value, 2) },
                    { label: "總 Offset", value: ctx.formatSignedMilliseconds(appliedOffsetMs) },
                ],
            });
            const isSelected = ctx.selectedAlignmentPoint?.key === key;
            return `
                <circle
                    cx="${scaleX(point.timestampMs).toFixed(2)}"
                    cy="${scaleThermalY(point.value).toFixed(2)}"
                    r="${isSelected ? "5.2" : "3.8"}"
                    class="thermal-point chart-point${isSelected ? " chart-point-selected" : ""}"
                    data-point-id="${pointId}"
                />
            `;
        }).join("");

        const edgeCircles = visibleEdge.map((point) => {
            const pointId = interactivePoints.length;
            const key = ctx.buildPointKey("edge", point.timestampMs);
            interactivePoints.push({
                key,
                title: "Edge 資料點",
                seriesLabel: edgeLabel,
                rows: [
                    { label: "完整時間", value: ctx.formatFullTimestamp(point.timestampMs) },
                    { label: edgeLabel, value: ctx.formatNumber(point.value, 4) },
                    { label: "Edge 格式", value: ctx.state.edge?.edge_format || "-" },
                    { label: "來源檔案", value: ctx.state.edge?.source_file || "-" },
                ],
            });
            const isSelected = ctx.selectedAlignmentPoint?.key === key;
            return `
                <circle
                    cx="${scaleX(point.timestampMs).toFixed(2)}"
                    cy="${scaleEdgeY(point.value).toFixed(2)}"
                    r="${isSelected ? "4.8" : "3.4"}"
                    class="edge-point chart-point${isSelected ? " chart-point-selected" : ""}"
                    data-point-id="${pointId}"
                />
            `;
        }).join("");

        const tickMarkup = tickTimestamps.map((timestampMs, index) => {
            const x = scaleX(timestampMs);
            const anchor = index === 0 ? "start" : (index === tickTimestamps.length - 1 ? "end" : "middle");
            return `
                <line x1="${x.toFixed(2)}" y1="${top}" x2="${x.toFixed(2)}" y2="${(top + plotHeight).toFixed(2)}" class="grid-line" />
                <text x="${x.toFixed(2)}" y="${height - 18}" text-anchor="${anchor}" class="chart-axis-tick">${ctx.formatChartTime(timestampMs)}</text>
            `;
        }).join("");

        const markerLines = [];
        const markerLabels = [];
        const addMarker = (timestampMs, label, cssClass, anchor = "start", y = top + 16) => {
            if (!Number.isFinite(timestampMs) || timestampMs < visibleStart || timestampMs > visibleEnd) {
                return;
            }
            const x = scaleX(timestampMs);
            const labelX = anchor === "end" ? x - 8 : x + 8;
            markerLines.push(
                `<line x1="${x.toFixed(2)}" y1="${top}" x2="${x.toFixed(2)}" y2="${(top + plotHeight).toFixed(2)}" class="${cssClass}" />`,
            );
            markerLabels.push(
                `<text x="${labelX.toFixed(2)}" y="${y}" text-anchor="${anchor}" class="feature-label">${label}</text>`,
            );
        };

        addMarker(Number(thermalFeature?.timestamp_ms), "熱像起點", "feature-line thermal-feature-line", "start", top + 16);
        addMarker(Number(thermalFeature?.timestamp_ms) + appliedOffsetMs, "熱像對齊後", "feature-line thermal-feature-line", "start", top + 32);
        addMarker(Number(machineFeature?.timestamp_ms), "LASER ON", "feature-line machine-feature-line", "end", top + 16);

        svg._interactivePoints = interactivePoints;
        svg.dataset.viewWidth = String(width);
        svg.dataset.plotLeft = String(left);
        svg.dataset.plotRight = String(right);
        svg.innerHTML = `
            <rect x="${left}" y="${top}" width="${plotWidth}" height="${plotHeight}" class="chart-hitbox" />
            <line x1="${left}" y1="${top + plotHeight}" x2="${width - right}" y2="${top + plotHeight}" class="grid-line" />
            <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="grid-line" />
            <line x1="${width - right}" y1="${top}" x2="${width - right}" y2="${top + plotHeight}" class="grid-line" />
            ${tickMarkup}
            ${markerLines.join("")}
            <path d="${rawThermalPath}" class="thermal-path-raw" />
            <path d="${alignedThermalPath}" class="thermal-path" />
            <path d="${edgePath}" class="edge-path" />
            ${rawThermalCircles}
            ${alignedThermalCircles}
            ${edgeCircles}
            ${markerLabels.join("")}
            <text x="${left}" y="18" class="axis-label">熱像 ${ctx.formatNumber(thermalMin, 2)} ~ ${ctx.formatNumber(thermalMax, 2)}</text>
            <text x="${width - right}" y="18" text-anchor="end" class="axis-label">${edgeLabel} ${ctx.formatNumber(edgeMin, 2)} ~ ${ctx.formatNumber(edgeMax, 2)}</text>
        `;

        ctx.setText("alignment-window-label", `${ctx.formatFullTimestamp(visibleStart)} -> ${ctx.formatFullTimestamp(visibleEnd)}`);
        ctx.renderPointDetail("alignment-point-detail", ctx.selectedAlignmentPoint, "點選對齊圖中的熱像或 Edge 資料點後，這裡會顯示完整時間戳與數值。");
    }

    function bindAlignmentInteractions() {
        ctx.bindInteractiveChart({
            svgId: "alignment-chart",
            resetButtonId: "alignment-reset-view",
            viewState: ctx.alignmentChartView,
            onRender: renderAlignment,
            onSelectPoint: (point) => {
                ctx.selectedAlignmentPoint = point;
            },
            onClearSelection: () => {
                ctx.selectedAlignmentPoint = null;
            },
        });
    }

    return {
        renderAlignment,
        bindAlignmentControls,
        bindAlignmentInteractions,
    };
}
