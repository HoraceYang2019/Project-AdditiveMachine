export function initThermalSection(ctx) {
    function renderThermal() {
        const thermal = ctx.state.thermal || {};
        const stats = [
            { label: "樣本數", value: ctx.formatInteger(thermal.sample_count) },
            { label: "G_High 最低", value: ctx.formatNumber(thermal.g_high_min, 2) },
            { label: "G_High 平均", value: ctx.formatNumber(thermal.g_high_avg, 2) },
            { label: "G_High 最高", value: ctx.formatNumber(thermal.g_high_max, 2) },
        ];

        const statsNode = ctx.byId("thermal-stats");
        if (statsNode) {
            statsNode.replaceChildren(
                ...stats.map((metric) => {
                    const article = document.createElement("article");
                    article.className = "metric-card";
                    article.innerHTML = `<span>${metric.label}</span><strong>${metric.value}</strong>`;
                    return article;
                }),
            );
        }

        const svg = ctx.byId("thermal-chart");
        if (!svg) {
            return;
        }

        const trace = Array.isArray(thermal.thermal_trace) ? thermal.thermal_trace : [];
        const points = trace
            .map((item) => ({
                timestampMs: Number(item.timestamp_ms),
                value: Number(item.g_high),
            }))
            .filter((item) => Number.isFinite(item.timestampMs) && Number.isFinite(item.value));

        if (!points.length) {
            const message = thermal.source_kind === "missing" ? "目前沒有熱像資料。" : "熱像圖沒有可用樣本。";
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">${message}</text>`;
            ctx.setText("thermal-window-label", "尚未建立時間視窗");
            ctx.renderPointDetail("thermal-point-detail", null, "點選熱像圖中的資料點後，這裡會顯示完整時間戳與數值。");
            return;
        }

        ctx.clampChartView(ctx.thermalChartView);

        const width = 900;
        const height = 320;
        const left = 70;
        const right = 32;
        const top = 26;
        const bottom = 58;
        const plotWidth = width - left - right;
        const plotHeight = height - top - bottom;
        const minTimestamp = points[0].timestampMs;
        const maxTimestamp = points[points.length - 1].timestampMs;
        const totalSpan = Math.max(maxTimestamp - minTimestamp, 1);
        const visibleStart = minTimestamp + totalSpan * ctx.thermalChartView.startRatio;
        const visibleEnd = minTimestamp + totalSpan * ctx.thermalChartView.endRatio;
        const visiblePoints = ctx.sliceVisiblePoints(points, visibleStart, visibleEnd);
        const visibleValues = visiblePoints.map((point) => point.value);
        const minValue = Math.min(...visibleValues);
        const maxValue = Math.max(...visibleValues);
        const valueSpan = Math.max(maxValue - minValue, 1);
        const scaleX = (timestampMs) => left + ((timestampMs - visibleStart) / Math.max(visibleEnd - visibleStart, 1)) * plotWidth;
        const scaleY = (value) => top + (1 - (value - minValue) / valueSpan) * plotHeight;
        const tickTimestamps = ctx.buildTimeTicks(visibleStart, visibleEnd, 6, visiblePoints.length <= 8 ? visiblePoints : []);
        const path = ctx.buildPolylinePath(visiblePoints, scaleX, scaleY);

        const interactivePoints = [];
        const circleMarkup = visiblePoints.map((point) => {
            const pointId = interactivePoints.length;
            const key = ctx.buildPointKey("thermal", point.timestampMs);
            interactivePoints.push({
                key,
                title: "熱像資料點",
                seriesLabel: "熱像 G_High",
                rows: [
                    { label: "完整時間", value: ctx.formatFullTimestamp(point.timestampMs) },
                    { label: "毫秒時間", value: `${Math.round(point.timestampMs)} ms` },
                    { label: "G_High", value: ctx.formatNumber(point.value, 2) },
                    { label: "來源檔案", value: thermal.source_file || "-" },
                ],
            });
            const isSelected = ctx.selectedThermalPoint?.key === key;
            return `
                <circle
                    cx="${scaleX(point.timestampMs).toFixed(2)}"
                    cy="${scaleY(point.value).toFixed(2)}"
                    r="${isSelected ? "5.6" : "4.4"}"
                    class="thermal-point chart-point${isSelected ? " chart-point-selected" : ""}"
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

        svg._interactivePoints = interactivePoints;
        svg.dataset.viewWidth = String(width);
        svg.dataset.plotLeft = String(left);
        svg.dataset.plotRight = String(right);
        svg.innerHTML = `
            <rect x="${left}" y="${top}" width="${plotWidth}" height="${plotHeight}" class="chart-hitbox" />
            <line x1="${left}" y1="${top + plotHeight}" x2="${width - right}" y2="${top + plotHeight}" class="grid-line" />
            <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="grid-line" />
            ${tickMarkup}
            <path d="${path}" class="thermal-path" />
            ${circleMarkup}
            <text x="${left}" y="18" class="axis-label">G_High ${ctx.formatNumber(minValue, 2)} ~ ${ctx.formatNumber(maxValue, 2)}</text>
            <text x="${width - right}" y="18" text-anchor="end" class="axis-label">視窗內 ${visiblePoints.length} 點</text>
        `;

        ctx.setText("thermal-window-label", `${ctx.formatFullTimestamp(visibleStart)} -> ${ctx.formatFullTimestamp(visibleEnd)}`);
        ctx.renderPointDetail("thermal-point-detail", ctx.selectedThermalPoint, "點選熱像圖中的資料點後，這裡會顯示完整時間戳與數值。");
    }

    function bindThermalInteractions() {
        ctx.bindInteractiveChart({
            svgId: "thermal-chart",
            resetButtonId: "thermal-reset-view",
            viewState: ctx.thermalChartView,
            onRender: renderThermal,
            onSelectPoint: (point) => {
                ctx.selectedThermalPoint = point;
            },
            onClearSelection: () => {
                ctx.selectedThermalPoint = null;
            },
        });
    }

    return {
        renderThermal,
        bindThermalInteractions,
    };
}
