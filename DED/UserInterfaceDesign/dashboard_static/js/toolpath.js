export function initToolpathSection(ctx) {
    function interpolateRawPoint(start, end, ratio) {
        const startLineNo = Number(start.line_no ?? 0);
        const endLineNo = Number(end.line_no ?? startLineNo);
        const startZ = Number(start.z_mm ?? 0);
        const endZ = Number(end.z_mm ?? startZ);
        return {
            x_mm: Number(start.x_mm) + (Number(end.x_mm) - Number(start.x_mm)) * ratio,
            y_mm: Number(start.y_mm) + (Number(end.y_mm) - Number(start.y_mm)) * ratio,
            z_mm: startZ + (endZ - startZ) * ratio,
            line_no: Math.round(startLineNo + (endLineNo - startLineNo) * ratio),
        };
    }

    function layerPlaybackKey(layer) {
        if (!layer) {
            return "";
        }
        return [
            ctx.state.selected_output_name ?? "",
            layer.layer_index ?? "",
            layer.point_count ?? "",
            layer.line_range?.start ?? "",
            layer.line_range?.end ?? "",
        ].join("|");
    }

    function buildToolpathGeometry(layer) {
        const points = layer?.motion_points || [];
        const bounds = layer?.bounds;
        const width = 900;
        const height = 560;
        const padding = { left: 72, right: 40, top: 36, bottom: 56 };
        if (!points.length || !bounds) {
            return null;
        }

        const projectedPoints = points.map((point) => ctx.projectPoint(point, bounds, width, height, padding));
        const gridLines = [];
        for (let index = 0; index <= 4; index += 1) {
            const y = padding.top + ((height - padding.top - padding.bottom) / 4) * index;
            gridLines.push(`<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" class="grid-line" />`);
        }

        const segments = [];
        const backgroundSegments = [];
        let totalUnits = 0;
        for (let index = 1; index < points.length; index += 1) {
            const startPoint = points[index - 1];
            const endPoint = points[index];
            const startProjected = projectedPoints[index - 1];
            const endProjected = projectedPoints[index];
            const actualLength = Math.hypot(
                Number(endPoint.x_mm) - Number(startPoint.x_mm),
                Number(endPoint.y_mm) - Number(startPoint.y_mm),
                Number(endPoint.z_mm ?? startPoint.z_mm ?? 0) - Number(startPoint.z_mm ?? 0),
            );
            const unitLength = Math.max(actualLength, 0.2);
            const pathType = endPoint.laser_on ? "deposit" : "travel";
            segments.push({
                pathType,
                startPoint,
                endPoint,
                startProjected,
                endProjected,
                startUnits: totalUnits,
                endUnits: totalUnits + unitLength,
            });
            backgroundSegments.push(
                ctx.createLineMarkup(
                    startProjected,
                    endProjected,
                    pathType === "deposit" ? "segment-ghost-deposit" : "segment-ghost-travel",
                ),
            );
            totalUnits += unitLength;
        }

        const startProjected = projectedPoints[0];
        const endProjected = projectedPoints[projectedPoints.length - 1];
        const staticMarkup = `
            ${gridLines.join("")}
            ${backgroundSegments.join("")}
            <circle cx="${startProjected.x.toFixed(2)}" cy="${startProjected.y.toFixed(2)}" r="7" class="marker-start" />
            <circle cx="${endProjected.x.toFixed(2)}" cy="${endProjected.y.toFixed(2)}" r="7" class="marker-end" />
            <text x="${padding.left}" y="${height - 32}" class="axis-label">X ${ctx.formatNumber(bounds.x_min_mm, 2)} ~ ${ctx.formatNumber(bounds.x_max_mm, 2)} mm</text>
            <text x="${width - padding.right}" y="${height - 32}" text-anchor="end" class="axis-label">Y ${ctx.formatNumber(bounds.y_min_mm, 2)} ~ ${ctx.formatNumber(bounds.y_max_mm, 2)} mm</text>
        `;

        return {
            width,
            height,
            bounds,
            points,
            segments,
            projectedPoints,
            startProjected,
            endProjected,
            staticMarkup,
            totalUnits,
            baseUnitsPerSecond: Math.max(totalUnits / 12, 8),
        };
    }

    function ensurePlaybackGeometry(layer) {
        const nextKey = layerPlaybackKey(layer);
        if (ctx.playback.layerKey !== nextKey) {
            ctx.pausePlayback();
            ctx.playback.layerKey = nextKey;
            ctx.playback.geometry = buildToolpathGeometry(layer);
            ctx.playback.totalUnits = ctx.playback.geometry?.totalUnits ?? 0;
            ctx.playback.progressUnits = 0;
        }
        return ctx.playback.geometry;
    }

    function buildPlaybackSnapshot(geometry) {
        if (!geometry || !geometry.points.length) {
            return null;
        }
        const totalUnits = ctx.playback.totalUnits || geometry.totalUnits || 0;
        const progressUnits = ctx.clamp(ctx.playback.progressUnits, 0, totalUnits);
        const activeSegments = [];
        let headProjected = geometry.startProjected;
        let headRaw = geometry.points[0];
        let activeType = geometry.segments[0]?.pathType || "travel";
        let traversedSegments = 0;

        for (const segment of geometry.segments) {
            if (progressUnits >= segment.endUnits) {
                activeSegments.push(
                    ctx.createLineMarkup(
                        segment.startProjected,
                        segment.endProjected,
                        segment.pathType === "deposit" ? "segment-active-deposit" : "segment-active-travel",
                    ),
                );
                headProjected = segment.endProjected;
                headRaw = segment.endPoint;
                activeType = segment.pathType;
                traversedSegments += 1;
                continue;
            }
            if (progressUnits > segment.startUnits) {
                const span = Math.max(segment.endUnits - segment.startUnits, 0.0001);
                const ratio = ctx.clamp((progressUnits - segment.startUnits) / span, 0, 1);
                const partialProjected = ctx.interpolatePoint(segment.startProjected, segment.endProjected, ratio);
                const partialRaw = interpolateRawPoint(segment.startPoint, segment.endPoint, ratio);
                activeSegments.push(
                    ctx.createLineMarkup(
                        segment.startProjected,
                        partialProjected,
                        segment.pathType === "deposit" ? "segment-active-deposit" : "segment-active-travel",
                    ),
                );
                headProjected = partialProjected;
                headRaw = partialRaw;
                activeType = segment.pathType;
                break;
            }
            break;
        }

        if (progressUnits >= totalUnits && geometry.points.length) {
            headProjected = geometry.endProjected;
            headRaw = geometry.points[geometry.points.length - 1];
            activeType = geometry.segments[geometry.segments.length - 1]?.pathType || activeType;
            traversedSegments = geometry.segments.length;
        }

        return {
            activeMarkup: activeSegments.join(""),
            headProjected,
            headRaw,
            activeType,
            progressRatio: totalUnits > 0 ? progressUnits / totalUnits : 0,
            traversedSegments,
        };
    }

    function updateToolpathControls(geometry, snapshot) {
        const playButton = ctx.byId("toolpath-play-button");
        const resetButton = ctx.byId("toolpath-reset-button");
        const range = ctx.byId("toolpath-progress-range");
        const speedSelect = ctx.byId("toolpath-speed-select");
        const progressLabel = ctx.byId("toolpath-progress-label");
        const statusLabel = ctx.byId("toolpath-status");
        const hasPath = Boolean(geometry && geometry.points.length > 1 && geometry.segments.length);
        const ratio = snapshot?.progressRatio ?? 0;
        const sliderValue = Math.round(ratio * ctx.progressSliderMax);

        if (playButton) {
            playButton.disabled = !hasPath;
            playButton.textContent = ctx.playback.isPlaying ? "暫停" : "播放";
        }
        if (resetButton) {
            resetButton.disabled = !hasPath;
        }
        if (range) {
            range.disabled = !hasPath;
            range.value = String(sliderValue);
        }
        if (speedSelect) {
            speedSelect.value = String(ctx.playback.speedMultiplier);
            speedSelect.disabled = !hasPath;
        }
        if (progressLabel) {
            progressLabel.textContent = `${(ratio * 100).toFixed(1)}%`;
        }
        if (statusLabel) {
            if (!hasPath) {
                statusLabel.textContent = "請選擇有路徑資料的 layer。";
                return;
            }
            const point = snapshot?.headRaw || geometry.points[0];
            const pathLabel = snapshot?.activeType === "deposit" ? "雷射沉積" : "移動";
            const finishedText = ratio >= 1 ? " / 已完成" : "";
            statusLabel.textContent = `行號 ${point.line_no ?? "-"} / X ${ctx.formatNumber(point.x_mm, 2)} / Y ${ctx.formatNumber(point.y_mm, 2)} / Z ${ctx.formatNumber(point.z_mm, 3)} / ${pathLabel}${finishedText}`;
        }
    }

    function renderToolpathFocusPanel(geometry, snapshot) {
        const panel = ctx.byId("toolpath-focus-panel");
        if (!panel) {
            return;
        }
        if (!geometry || !geometry.points.length) {
            panel.innerHTML = `
                <div class="toolpath-focus-empty">
                    <strong>尚未建立路徑播放資訊。</strong>
                    <p>切換到有沉積點的 layer 後，這裡會同步顯示目前行號與座標。</p>
                </div>
            `;
            return;
        }

        const point = snapshot?.headRaw || geometry.points[0];
        const activeType = snapshot?.activeType || geometry.segments[0]?.pathType || "unknown";
        const progressText = `${((snapshot?.progressRatio ?? 0) * 100).toFixed(1)}%`;
        const traversedSegments = Number(snapshot?.traversedSegments ?? 0);
        const status = activeType === "deposit"
            ? {
                label: "沉積",
                badgeClass: "is-deposit",
                description: "目前播放點位位於雷射沉積路徑。",
            }
            : {
                label: "移動",
                badgeClass: "is-travel",
                description: "目前播放點位位於非沉積移動路徑。",
            };

        panel.innerHTML = `
            <div class="toolpath-focus-overview">
                <div class="toolpath-focus-copy">
                    <p class="toolpath-focus-kicker">路徑同步監看</p>
                    <p class="toolpath-focus-reading">L${point.line_no ?? "-"}</p>
                    <p class="toolpath-focus-meta">播放進度 ${progressText} · 已走過 ${ctx.formatInteger(traversedSegments)} / ${ctx.formatInteger(geometry.segments.length)} 段</p>
                    <p class="toolpath-focus-description">${status.description}</p>
                </div>
                <span class="toolpath-focus-badge ${status.badgeClass}">${status.label}</span>
            </div>
            <div class="toolpath-focus-grid">
                <article class="toolpath-focus-card">
                    <span>X</span>
                    <strong>${ctx.formatNumber(point.x_mm, 2)} mm</strong>
                </article>
                <article class="toolpath-focus-card">
                    <span>Y</span>
                    <strong>${ctx.formatNumber(point.y_mm, 2)} mm</strong>
                </article>
                <article class="toolpath-focus-card">
                    <span>Z</span>
                    <strong>${ctx.formatNumber(point.z_mm, 3)} mm</strong>
                </article>
            </div>
            <div class="toolpath-focus-footer">
                <span>Layer ${ctx.formatInteger(ctx.layerRecord()?.layer_index)}</span>
                <span>點數 ${ctx.formatInteger(geometry.points.length)}</span>
                <span>目前線號 ${point.line_no ?? "-"}</span>
            </div>
        `;
    }

    function renderToolpath() {
        const svg = ctx.byId("toolpath-plot");
        if (!svg) {
            return;
        }
        const geometry = ensurePlaybackGeometry(ctx.layerRecord());
        if (!geometry) {
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">沒有運動點位資料</text>`;
            updateToolpathControls(null, null);
            renderToolpathFocusPanel(null, null);
            return;
        }

        const snapshot = buildPlaybackSnapshot(geometry);
        const headMarkup = snapshot
            ? `
                <circle cx="${snapshot.headProjected.x.toFixed(2)}" cy="${snapshot.headProjected.y.toFixed(2)}" r="9.5" class="marker-head-ring" />
                <circle cx="${snapshot.headProjected.x.toFixed(2)}" cy="${snapshot.headProjected.y.toFixed(2)}" r="4.5" class="marker-head-core" />
            `
            : "";

        svg.innerHTML = `
            ${geometry.staticMarkup}
            ${snapshot?.activeMarkup || ""}
            ${headMarkup}
        `;
        updateToolpathControls(geometry, snapshot);
        renderToolpathFocusPanel(geometry, snapshot);
    }

    function renderToolpathFrame(frameTimeMs) {
        if (!ctx.playback.isPlaying || !ctx.playback.geometry) {
            return;
        }
        if (!ctx.playback.lastFrameMs) {
            ctx.playback.lastFrameMs = frameTimeMs;
        }
        const elapsedSeconds = Math.max((frameTimeMs - ctx.playback.lastFrameMs) / 1000, 0);
        ctx.playback.lastFrameMs = frameTimeMs;
        const advance = elapsedSeconds * ctx.playback.geometry.baseUnitsPerSecond * ctx.playback.speedMultiplier;
        ctx.playback.progressUnits = ctx.clamp(
            ctx.playback.progressUnits + advance,
            0,
            ctx.playback.totalUnits || ctx.playback.geometry.totalUnits || 0,
        );
        renderToolpath();

        if (ctx.playback.progressUnits >= (ctx.playback.totalUnits || ctx.playback.geometry.totalUnits || 0)) {
            ctx.pausePlayback();
            renderToolpath();
            return;
        }
        ctx.playback.rafId = window.requestAnimationFrame(renderToolpathFrame);
    }

    function startPlayback() {
        const geometry = ensurePlaybackGeometry(ctx.layerRecord());
        if (!geometry || geometry.segments.length === 0) {
            renderToolpath();
            return;
        }
        if (ctx.playback.progressUnits >= (ctx.playback.totalUnits || geometry.totalUnits)) {
            ctx.playback.progressUnits = 0;
        }
        ctx.pausePlayback();
        ctx.playback.isPlaying = true;
        ctx.playback.lastFrameMs = 0;
        renderToolpath();
        ctx.playback.rafId = window.requestAnimationFrame(renderToolpathFrame);
    }

    function resetPlayback() {
        ctx.pausePlayback();
        ctx.playback.progressUnits = 0;
        renderToolpath();
    }

    function bindToolpathControls() {
        const playButton = ctx.byId("toolpath-play-button");
        const resetButton = ctx.byId("toolpath-reset-button");
        const range = ctx.byId("toolpath-progress-range");
        const speedSelect = ctx.byId("toolpath-speed-select");

        if (playButton && !playButton.dataset.bound) {
            playButton.addEventListener("click", () => {
                if (ctx.playback.isPlaying) {
                    ctx.pausePlayback();
                    renderToolpath();
                    return;
                }
                startPlayback();
            });
            playButton.dataset.bound = "true";
        }

        if (resetButton && !resetButton.dataset.bound) {
            resetButton.addEventListener("click", resetPlayback);
            resetButton.dataset.bound = "true";
        }

        if (range && !range.dataset.bound) {
            range.addEventListener("input", (event) => {
                ctx.pausePlayback();
                const ratio = Number(event.target.value) / ctx.progressSliderMax;
                ctx.playback.progressUnits = (ctx.playback.totalUnits || 0) * ctx.clamp(ratio, 0, 1);
                renderToolpath();
            });
            range.dataset.bound = "true";
        }

        if (speedSelect && !speedSelect.dataset.bound) {
            speedSelect.addEventListener("change", (event) => {
                ctx.playback.speedMultiplier = Number(event.target.value) || 1;
                renderToolpath();
            });
            speedSelect.dataset.bound = "true";
        }
    }

    return {
        renderToolpath,
        bindToolpathControls,
    };
}
