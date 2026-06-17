import { clamp } from "./shared-format.js";

function getSvgPlotMetrics(svg) {
    const viewWidth = Number(svg.dataset.viewWidth || 900);
    const plotLeft = Number(svg.dataset.plotLeft || 0);
    const plotRight = Number(svg.dataset.plotRight || 0);
    return {
        viewWidth,
        plotLeft,
        plotRight,
        plotWidth: Math.max(viewWidth - plotLeft - plotRight, 1),
    };
}

export function bindInteractiveChart(ctx, {
    svgId,
    resetButtonId,
    viewState,
    onRender,
    onSelectPoint,
    onClearSelection,
}) {
    const svg = ctx.byId(svgId);
    const resetButton = ctx.byId(resetButtonId);
    if (!svg) {
        return;
    }

    if (!svg.dataset.interactiveBound) {
        svg.addEventListener("wheel", (event) => {
            const metrics = getSvgPlotMetrics(svg);
            const rect = svg.getBoundingClientRect();
            const plotLeftPx = rect.width * (metrics.plotLeft / metrics.viewWidth);
            const plotWidthPx = rect.width * (metrics.plotWidth / metrics.viewWidth);
            if (plotWidthPx <= 0) {
                return;
            }
            event.preventDefault();
            const pointerRatio = clamp((event.clientX - rect.left - plotLeftPx) / plotWidthPx, 0, 1);
            zoomChartView(viewState, event.deltaY < 0 ? 1.18 : 0.84, pointerRatio);
            onRender();
        }, { passive: false });

        svg.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) {
                return;
            }
            viewState.pointerId = event.pointerId;
            viewState.dragStartX = event.clientX;
            viewState.dragStartStart = viewState.startRatio;
            viewState.dragStartEnd = viewState.endRatio;
            viewState.dragMoved = false;
            if (typeof svg.setPointerCapture === "function") {
                svg.setPointerCapture(event.pointerId);
            }
            svg.classList.add("chart-dragging");
        });

        svg.addEventListener("pointermove", (event) => {
            if (viewState.pointerId !== event.pointerId) {
                return;
            }
            const metrics = getSvgPlotMetrics(svg);
            const rect = svg.getBoundingClientRect();
            const plotWidthPx = rect.width * (metrics.plotWidth / metrics.viewWidth);
            if (plotWidthPx <= 0) {
                return;
            }
            const span = viewState.dragStartEnd - viewState.dragStartStart;
            const deltaRatio = ((event.clientX - viewState.dragStartX) / plotWidthPx) * span;
            viewState.startRatio = viewState.dragStartStart - deltaRatio;
            viewState.endRatio = viewState.dragStartEnd - deltaRatio;
            clampChartView(viewState);
            if (Math.abs(event.clientX - viewState.dragStartX) > 3) {
                viewState.dragMoved = true;
            }
            onRender();
        });

        const finishPointer = (event) => {
            if (viewState.pointerId !== event.pointerId) {
                return;
            }
            if (typeof svg.releasePointerCapture === "function" && svg.hasPointerCapture?.(event.pointerId)) {
                svg.releasePointerCapture(event.pointerId);
            }
            svg.classList.remove("chart-dragging");
            const didMove = viewState.dragMoved;
            viewState.pointerId = null;
            viewState.dragMoved = false;
            if (didMove) {
                return;
            }
            const pointId = event.target?.dataset?.pointId;
            if (pointId !== undefined && Array.isArray(svg._interactivePoints) && svg._interactivePoints[pointId]) {
                onSelectPoint(svg._interactivePoints[pointId]);
            } else if (typeof onClearSelection === "function") {
                onClearSelection();
            }
            onRender();
        };

        svg.addEventListener("pointerup", finishPointer);
        svg.addEventListener("pointercancel", (event) => {
            if (viewState.pointerId !== event.pointerId) {
                return;
            }
            viewState.pointerId = null;
            viewState.dragMoved = false;
            svg.classList.remove("chart-dragging");
        });

        svg.dataset.interactiveBound = "true";
    }

    if (resetButton && !resetButton.dataset.bound) {
        resetButton.addEventListener("click", () => {
            resetChartView(viewState);
            onRender();
        });
        resetButton.dataset.bound = "true";
    }
}

export function resetChartView(viewState) {
    viewState.startRatio = 0;
    viewState.endRatio = 1;
    viewState.pointerId = null;
    viewState.dragStartX = 0;
    viewState.dragStartStart = 0;
    viewState.dragStartEnd = 1;
    viewState.dragMoved = false;
}

export function clampChartView(viewState, minSpan = 0.02) {
    const clampedMinSpan = clamp(minSpan, 0.001, 1);
    const span = clamp(viewState.endRatio - viewState.startRatio, clampedMinSpan, 1);
    let start = viewState.startRatio;
    let end = viewState.endRatio;
    if (span >= 1) {
        start = 0;
        end = 1;
    } else {
        if (start < 0) {
            end -= start;
            start = 0;
        }
        if (end > 1) {
            start -= end - 1;
            end = 1;
        }
        start = clamp(start, 0, 1 - span);
        end = start + span;
    }
    viewState.startRatio = start;
    viewState.endRatio = end;
}

export function zoomChartView(viewState, factor, anchorRatio = 0.5) {
    const currentSpan = Math.max(viewState.endRatio - viewState.startRatio, 0.0001);
    const nextSpan = clamp(currentSpan / factor, 0.02, 1);
    const clampedAnchor = clamp(anchorRatio, 0, 1);
    const anchorValue = viewState.startRatio + currentSpan * clampedAnchor;
    viewState.startRatio = anchorValue - nextSpan * clampedAnchor;
    viewState.endRatio = anchorValue + nextSpan * (1 - clampedAnchor);
    clampChartView(viewState);
}

export function buildTimeTicks(startTimestampMs, endTimestampMs, preferredCount = 6, sourcePoints = []) {
    const availablePoints = Array.isArray(sourcePoints) ? sourcePoints : [];
    if (availablePoints.length > 0 && availablePoints.length <= preferredCount) {
        return availablePoints.map((point) => Number(point.timestampMs));
    }
    if (!Number.isFinite(startTimestampMs) || !Number.isFinite(endTimestampMs)) {
        return [];
    }
    if (startTimestampMs === endTimestampMs) {
        return [startTimestampMs];
    }
    const tickCount = Math.max(2, preferredCount);
    const span = endTimestampMs - startTimestampMs;
    return Array.from({ length: tickCount }, (_, index) => (
        startTimestampMs + (span * index) / (tickCount - 1)
    ));
}

export function sliceVisiblePoints(points, startTimestampMs, endTimestampMs) {
    if (!Array.isArray(points) || points.length === 0) {
        return [];
    }
    let firstVisibleIndex = -1;
    let lastVisibleIndex = -1;
    for (let index = 0; index < points.length; index += 1) {
        const timestampMs = Number(points[index].timestampMs);
        if (timestampMs >= startTimestampMs && timestampMs <= endTimestampMs) {
            if (firstVisibleIndex === -1) {
                firstVisibleIndex = index;
            }
            lastVisibleIndex = index;
        }
    }
    if (firstVisibleIndex === -1) {
        let nearestIndex = 0;
        let smallestDistance = Number.POSITIVE_INFINITY;
        for (let index = 0; index < points.length; index += 1) {
            const distance = Math.abs(Number(points[index].timestampMs) - startTimestampMs);
            if (distance < smallestDistance) {
                smallestDistance = distance;
                nearestIndex = index;
            }
        }
        return [points[nearestIndex]];
    }
    const startIndex = Math.max(0, firstVisibleIndex - 1);
    const endIndex = Math.min(points.length - 1, lastVisibleIndex + 1);
    return points.slice(startIndex, endIndex + 1);
}

export function buildPolylinePath(points, scaleX, scaleY) {
    return points
        .map((point, index) => {
            const x = scaleX(point.timestampMs).toFixed(2);
            const y = scaleY(point.value).toFixed(2);
            return `${index === 0 ? "M" : "L"} ${x} ${y}`;
        })
        .join(" ");
}

export function buildPointKey(seriesKey, timestampMs, suffix = "") {
    return suffix
        ? `${seriesKey}|${Math.round(timestampMs)}|${suffix}`
        : `${seriesKey}|${Math.round(timestampMs)}`;
}

export function projectPoint(point, bounds, width, height, padding) {
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const xSpan = Math.max(Number(bounds.x_max_mm) - Number(bounds.x_min_mm), 1);
    const ySpan = Math.max(Number(bounds.y_max_mm) - Number(bounds.y_min_mm), 1);
    const x = padding.left + ((Number(point.x_mm) - Number(bounds.x_min_mm)) / xSpan) * plotWidth;
    const y = padding.top + (1 - (Number(point.y_mm) - Number(bounds.y_min_mm)) / ySpan) * plotHeight;
    return { x, y };
}

export function createLineMarkup(start, end, cssClass) {
    return `<line x1="${start.x.toFixed(2)}" y1="${start.y.toFixed(2)}" x2="${end.x.toFixed(2)}" y2="${end.y.toFixed(2)}" class="${cssClass}" />`;
}

export function interpolatePoint(start, end, ratio) {
    return {
        x: start.x + (end.x - start.x) * ratio,
        y: start.y + (end.y - start.y) * ratio,
    };
}

export function coordinateHeatColor(value, min, max) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return "rgba(36, 68, 107, 0.45)";
    }
    const minValue = Number.isFinite(Number(min)) ? Number(min) : numeric;
    const maxValue = Number.isFinite(Number(max)) ? Number(max) : numeric;
    const span = Math.max(maxValue - minValue, 1);
    const ratio = clamp((numeric - minValue) / span, 0, 1);
    const hue = 210 - ratio * 170;
    const saturation = 74 + ratio * 16;
    const lightness = 42 + ratio * 14;
    return `hsl(${hue.toFixed(1)} ${saturation.toFixed(1)}% ${lightness.toFixed(1)}%)`;
}

export function cancelAnimationFrameLoop(controller) {
    if (controller.rafId) {
        window.cancelAnimationFrame(controller.rafId);
        controller.rafId = 0;
    }
}

export function pauseAnimationPlayback(controller) {
    controller.isPlaying = false;
    controller.lastFrameMs = 0;
    cancelAnimationFrameLoop(controller);
}
