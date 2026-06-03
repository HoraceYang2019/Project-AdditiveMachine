export function initInfoSection(ctx) {
    function renderLayerMetrics() {
        const layer = ctx.layerRecord();
        const metrics = [
            { label: "Z 高度", value: `${ctx.formatNumber(layer?.z_level_mm, 3)} mm` },
            { label: "行號範圍", value: `${layer?.line_range?.start ?? "-"} 至 ${layer?.line_range?.end ?? "-"}` },
            { label: "沉積段數", value: ctx.formatInteger(layer?.deposit_segment_count) },
            { label: "移動段數", value: ctx.formatInteger(layer?.travel_segment_count) },
            {
                label: "X 範圍",
                value: layer?.bounds
                    ? `${ctx.formatNumber(layer.bounds.x_min_mm, 2)} 至 ${ctx.formatNumber(layer.bounds.x_max_mm, 2)}`
                    : "-",
            },
            {
                label: "Y 範圍",
                value: layer?.bounds
                    ? `${ctx.formatNumber(layer.bounds.y_min_mm, 2)} 至 ${ctx.formatNumber(layer.bounds.y_max_mm, 2)}`
                    : "-",
            },
        ];

        const node = ctx.byId("layer-metrics");
        if (!node) {
            return;
        }
        node.replaceChildren(
            ...metrics.map((metric) => {
                const article = document.createElement("article");
                article.className = "metric-card";
                article.innerHTML = `<span>${metric.label}</span><strong>${metric.value}</strong>`;
                return article;
            }),
        );
    }

    function renderSegments() {
        const layer = ctx.layerRecord();
        const segmentList = ctx.byId("segment-list");
        if (!segmentList) {
            return;
        }
        const visibleSegments = (layer?.segments || []).slice(0, 14);
        segmentList.replaceChildren(
            ...visibleSegments.map((segment) => {
                const article = document.createElement("article");
                article.className = "list-card";
                const speed = segment.feed_rate_mm_min ? `${ctx.formatNumber(segment.feed_rate_mm_min, 0)} mm/min` : "-";
                const segmentTypeLabel = ctx.translateSegmentType(segment.path_type);
                const pillClass = segment.path_type === "deposit" ? "pill-deposit" : "pill-travel";
                article.innerHTML = `
                    <div class="list-head">
                        <strong>${segment.segment_id}</strong>
                        <span class="pill ${pillClass}">${segmentTypeLabel}</span>
                    </div>
                    <div class="list-body">${segment.source_range ?? "-"}</div>
                    <div class="list-body">點數 ${ctx.formatInteger(segment.point_count)} / 進給 ${speed}</div>
                `;
                return article;
            }),
        );
    }

    return {
        renderLayerMetrics,
        renderSegments,
    };
}
