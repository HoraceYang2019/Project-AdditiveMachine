export function initCoordinateSection(ctx) {
    function percentile(values, ratio) {
        if (!Array.isArray(values) || !values.length) {
            return 0;
        }
        const sorted = values
            .map((value) => Number(value))
            .filter((value) => Number.isFinite(value))
            .sort((left, right) => left - right);
        if (!sorted.length) {
            return 0;
        }
        if (sorted.length === 1) {
            return sorted[0];
        }
        const position = Math.max(0, Math.min(1, ratio)) * (sorted.length - 1);
        const lower = Math.floor(position);
        const upper = Math.min(lower + 1, sorted.length - 1);
        const blend = position - lower;
        return sorted[lower] * (1 - blend) + sorted[upper] * blend;
    }

    function playbackCoordinateOffset() {
        const offset = ctx.state.coordinate_alignment?.applied_offset_mm || {};
        return {
            x_mm: Number(offset.x_mm || 0),
            y_mm: Number(offset.y_mm || 0),
            z_mm: Number(offset.z_mm || 0),
        };
    }

    function normalizeEdgePlaybackSamples() {
        const edgeTrace = Array.isArray(ctx.state.edge?.playback_trace) ? ctx.state.edge.playback_trace : (
            Array.isArray(ctx.state.edge?.edge_trace) ? ctx.state.edge.edge_trace : []
        );
        const offset = playbackCoordinateOffset();
        return edgeTrace
            .map((point) => {
                const machineX = Number(point.machine_x_mm);
                const machineY = Number(point.machine_y_mm);
                const machineZ = Number(point.machine_z_mm);
                const workX = Number.isFinite(Number(point.work_x_mm)) ? Number(point.work_x_mm) : machineX + offset.x_mm;
                const workY = Number.isFinite(Number(point.work_y_mm)) ? Number(point.work_y_mm) : machineY + offset.y_mm;
                const workZ = Number.isFinite(Number(point.work_z_mm)) ? Number(point.work_z_mm) : machineZ + offset.z_mm;
                return {
                    timestamp_ms: Number(point.timestamp_ms),
                    g_high: Number(point.g_high),
                    machine_x_mm: machineX,
                    machine_y_mm: machineY,
                    machine_z_mm: machineZ,
                    work_x_mm: workX,
                    work_y_mm: workY,
                    work_z_mm: workZ,
                    trajectory_id: point.trajectory_id ?? null,
                    heat_source: "edge",
                };
            })
            .filter((point) => (
                Number.isFinite(point.timestamp_ms)
                && Number.isFinite(point.machine_x_mm)
                && Number.isFinite(point.machine_y_mm)
                && Number.isFinite(point.machine_z_mm)
                && Number.isFinite(point.work_x_mm)
                && Number.isFinite(point.work_y_mm)
                && Number.isFinite(point.work_z_mm)
            ))
            .sort((left, right) => left.timestamp_ms - right.timestamp_ms);
    }

    function normalizeThermalPlaybackSamples() {
        const appliedOffsetMs = Number(ctx.state.alignment?.auto_offset_ms || 0) + Number(ctx.alignmentManualOffsetMs || 0);
        const thermalTrace = Array.isArray(ctx.state.thermal?.playback_trace) ? ctx.state.thermal.playback_trace : (
            Array.isArray(ctx.state.thermal?.thermal_trace) ? ctx.state.thermal.thermal_trace : []
        );
        return thermalTrace
            .map((point) => ({
                timestamp_ms: Number(point.timestamp_ms) + appliedOffsetMs,
                g_high: Number(point.g_high),
                heat_source: "thermal",
            }))
            .filter((point) => Number.isFinite(point.timestamp_ms) && Number.isFinite(point.g_high))
            .sort((left, right) => left.timestamp_ms - right.timestamp_ms);
    }

    function shouldUseEdgeHeatTrace(edgeTrace) {
        if (!edgeTrace.length || !edgeTrace.some((point) => Number.isFinite(Number(point.g_high)))) {
            return false;
        }
        const mapping = ctx.state.edge?.accurate_time_mapping || {};
        const mappingError = Number(mapping.mean_absolute_g_high_error);
        if (Number.isFinite(mappingError) && mappingError > 180) {
            return false;
        }
        return true;
    }

    function coordinateHeatTrace() {
        const edgeSamples = normalizeEdgePlaybackSamples();
        if (!edgeSamples.length) {
            return [];
        }
        if (shouldUseEdgeHeatTrace(edgeSamples)) {
            return edgeSamples
                .filter((point) => Number.isFinite(point.g_high))
                .sort((left, right) => left.timestamp_ms - right.timestamp_ms);
        }

        const thermalSamples = normalizeThermalPlaybackSamples();
        if (!thermalSamples.length) {
            return edgeSamples
                .filter((point) => Number.isFinite(point.g_high))
                .sort((left, right) => left.timestamp_ms - right.timestamp_ms);
        }

        const overlapStart = Math.max(edgeSamples[0].timestamp_ms, thermalSamples[0].timestamp_ms);
        const overlapEnd = Math.min(
            edgeSamples[edgeSamples.length - 1].timestamp_ms,
            thermalSamples[thermalSamples.length - 1].timestamp_ms,
        );
        const mergedSamples = [];
        let thermalIndex = 0;
        for (const edgePoint of edgeSamples) {
            const timestampMs = Number(edgePoint.timestamp_ms);
            if (timestampMs < overlapStart || timestampMs > overlapEnd) {
                continue;
            }
            while (
                thermalIndex + 1 < thermalSamples.length
                && Math.abs(thermalSamples[thermalIndex + 1].timestamp_ms - timestampMs)
                    <= Math.abs(thermalSamples[thermalIndex].timestamp_ms - timestampMs)
            ) {
                thermalIndex += 1;
            }
            const thermalPoint = thermalSamples[thermalIndex];
            mergedSamples.push({
                ...edgePoint,
                g_high: Number(thermalPoint.g_high),
                heat_source: "thermal",
                heat_timestamp_ms: Number(thermalPoint.timestamp_ms),
            });
        }
        return mergedSamples;
    }

    function trimActiveHeatTrace(trace) {
        if (!Array.isArray(trace) || trace.length < 6) {
            return trace;
        }
        const values = trace
            .map((point) => Number(point.g_high))
            .filter((value) => Number.isFinite(value));
        if (values.length < 6) {
            return trace;
        }
        const baselineCandidates = trace
            .slice(0, Math.min(3, trace.length))
            .concat(trace.slice(Math.max(trace.length - 3, 0)))
            .map((point) => Number(point.g_high))
            .filter((value) => Number.isFinite(value));
        const baseline = baselineCandidates.length ? Math.min(...baselineCandidates) : percentile(values, 0.1);
        const peak = percentile(values, 0.95);
        const threshold = baseline + Math.max((peak - baseline) * 0.12, 35);

        let startIndex = trace.findIndex((point) => Number(point.g_high) >= threshold);
        let endIndex = -1;
        for (let index = trace.length - 1; index >= 0; index -= 1) {
            if (Number(trace[index].g_high) >= threshold) {
                endIndex = index;
                break;
            }
        }

        if (startIndex < 0 || endIndex < startIndex) {
            return trace;
        }
        startIndex = Math.max(0, startIndex - 1);
        endIndex = Math.min(trace.length - 1, endIndex + 1);
        const trimmed = trace.slice(startIndex, endIndex + 1);
        return trimmed.length >= Math.max(4, Math.floor(trace.length * 0.35)) ? trimmed : trace;
    }

    function processStartTimestampMs(heatTrace) {
        const processTimestamp = Number(ctx.state.alignment?.machine_feature?.timestamp_ms);
        if (!Number.isFinite(processTimestamp) || !Array.isArray(heatTrace) || !heatTrace.length) {
            return null;
        }
        const minTimestamp = Number(heatTrace[0].timestamp_ms);
        const maxTimestamp = Number(heatTrace[heatTrace.length - 1].timestamp_ms);
        if (!Number.isFinite(minTimestamp) || !Number.isFinite(maxTimestamp)) {
            return null;
        }
        if (processTimestamp < minTimestamp || processTimestamp > maxTimestamp) {
            return null;
        }
        return processTimestamp;
    }

    function buildRatioFallbackWindows(heatTrace, layers) {
        if (!heatTrace.length || !layers.length) {
            return [];
        }
        const startTimestampMs = Number(heatTrace[0].timestamp_ms);
        const endTimestampMs = Number(heatTrace[heatTrace.length - 1].timestamp_ms);
        const totalDurationMs = Math.max(endTimestampMs - startTimestampMs, 1);
        const layerUnits = layers.map((layer) => ({
            layer_index: layer.layer_index,
            z_level_mm: layer.z_level_mm,
            deposit_units: calculateLayerDepositUnits(layer),
        }));
        const totalUnits = Math.max(layerUnits.reduce((sum, item) => sum + item.deposit_units, 0), layerUnits.length || 1);

        let cumulativeUnits = 0;
        return layerUnits.map((item, index) => {
            const startRatio = cumulativeUnits / totalUnits;
            cumulativeUnits += item.deposit_units;
            const endRatio = index === layerUnits.length - 1 ? 1 : cumulativeUnits / totalUnits;
            const windowStartMs = Math.round(startTimestampMs + totalDurationMs * startRatio);
            const windowEndMs = Math.round(startTimestampMs + totalDurationMs * endRatio);
            const trace = trimActiveHeatTrace(
                heatTrace.filter((point) => point.timestamp_ms >= windowStartMs && point.timestamp_ms <= windowEndMs),
            );
            return {
                layer_index: item.layer_index,
                z_level_mm: item.z_level_mm,
                deposit_units: item.deposit_units,
                start_timestamp_ms: trace[0]?.timestamp_ms ?? windowStartMs,
                end_timestamp_ms: trace[trace.length - 1]?.timestamp_ms ?? windowEndMs,
                sample_count: trace.length,
                trace,
                heat_source: trace[0]?.heat_source || null,
                source_mode: "ratio-fallback",
            };
        });
    }

    function layerZTolerance(layers, layerIndex) {
        const ordered = (Array.isArray(layers) ? layers : [])
            .map((layer) => ({
                layer_index: Number(layer.layer_index),
                z_level_mm: Number(layer.z_level_mm),
            }))
            .filter((layer) => Number.isFinite(layer.layer_index) && Number.isFinite(layer.z_level_mm))
            .sort((left, right) => left.layer_index - right.layer_index);
        const currentIndex = ordered.findIndex((layer) => layer.layer_index === Number(layerIndex));
        if (currentIndex < 0) {
            return 0.18;
        }
        const gaps = [];
        if (currentIndex > 0) {
            gaps.push(Math.abs(ordered[currentIndex].z_level_mm - ordered[currentIndex - 1].z_level_mm));
        }
        if (currentIndex + 1 < ordered.length) {
            gaps.push(Math.abs(ordered[currentIndex + 1].z_level_mm - ordered[currentIndex].z_level_mm));
        }
        const gap = gaps.length ? Math.min(...gaps.filter((value) => value > 0)) : 0.2;
        return ctx.clamp((gap || 0.2) * 0.7, 0.12, 0.4);
    }

    function layerBoundsMargin(bounds) {
        if (!bounds) {
            return 1.5;
        }
        const xSpan = Math.max(Number(bounds.x_max_mm) - Number(bounds.x_min_mm), 0);
        const ySpan = Math.max(Number(bounds.y_max_mm) - Number(bounds.y_min_mm), 0);
        return ctx.clamp(Math.max(xSpan, ySpan) * 0.03, 0.8, 2.0);
    }

    function calculateLayerDepositUnits(layer) {
        const points = Array.isArray(layer?.motion_points) ? layer.motion_points : [];
        let totalUnits = 0;
        for (let index = 1; index < points.length; index += 1) {
            const startPoint = points[index - 1];
            const endPoint = points[index];
            if (!startPoint?.laser_on || !endPoint?.laser_on) {
                continue;
            }
            const lineGap = Math.abs(Number(endPoint.line_no ?? index) - Number(startPoint.line_no ?? (index - 1)));
            if (lineGap > 6) {
                continue;
            }
            totalUnits += Math.max(
                Math.hypot(
                    Number(endPoint.x_mm) - Number(startPoint.x_mm),
                    Number(endPoint.y_mm) - Number(startPoint.y_mm),
                    Number(endPoint.z_mm ?? startPoint.z_mm ?? 0) - Number(startPoint.z_mm ?? 0),
                ),
                0.08,
            );
        }
        return totalUnits;
    }

    function buildLayerHeatWindows() {
        const fullHeatTrace = coordinateHeatTrace();
        const layers = Array.isArray(ctx.state.layers) ? ctx.state.layers : [];
        if (!fullHeatTrace.length || !layers.length) {
            return [];
        }
        const processStartMs = processStartTimestampMs(fullHeatTrace);
        const heatTrace = processStartMs === null
            ? fullHeatTrace
            : fullHeatTrace.filter((point) => Number(point.timestamp_ms) >= processStartMs);
        if (!heatTrace.length) {
            return [];
        }

        const fallbackWindows = buildRatioFallbackWindows(heatTrace, layers);
        const windows = layers.map((layer, index) => {
            const bounds = layer?.bounds || null;
            const zTolerance = layerZTolerance(layers, layer?.layer_index);
            const margin = layerBoundsMargin(bounds);
            let trace = heatTrace.filter((point) => {
                if (!Number.isFinite(Number(point.work_z_mm)) || !Number.isFinite(Number(point.work_x_mm)) || !Number.isFinite(Number(point.work_y_mm))) {
                    return false;
                }
                if (Math.abs(Number(point.work_z_mm) - Number(layer?.z_level_mm)) > zTolerance) {
                    return false;
                }
                if (!bounds) {
                    return true;
                }
                return (
                    Number(point.work_x_mm) >= Number(bounds.x_min_mm) - margin
                    && Number(point.work_x_mm) <= Number(bounds.x_max_mm) + margin
                    && Number(point.work_y_mm) >= Number(bounds.y_min_mm) - margin
                    && Number(point.work_y_mm) <= Number(bounds.y_max_mm) + margin
                );
            });
            trace = trimActiveHeatTrace(trace);

            const minimumSamples = Math.max(10, Math.floor((Array.isArray(layer?.motion_points) ? layer.motion_points.length : 0) * 0.08));
            const fallback = fallbackWindows[index] || null;
            if (trace.length < minimumSamples && fallback?.trace?.length) {
                trace = fallback.trace;
            }

            return {
                layer_index: Number(layer?.layer_index || 0),
                z_level_mm: Number(layer?.z_level_mm || 0),
                deposit_units: calculateLayerDepositUnits(layer),
                start_timestamp_ms: trace[0]?.timestamp_ms ?? fallback?.start_timestamp_ms ?? null,
                end_timestamp_ms: trace[trace.length - 1]?.timestamp_ms ?? fallback?.end_timestamp_ms ?? null,
                sample_count: trace.length,
                trace,
                heat_source: trace[0]?.heat_source || fallback?.heat_source || null,
                source_mode: trace === fallback?.trace ? "ratio-fallback" : "spatial-layer-match",
            };
        });
        return windows.some((item) => Array.isArray(item.trace) && item.trace.length)
            ? windows
            : fallbackWindows;
    }

    function buildEmergencyHeatWindow(layer) {
        const fullHeatTrace = coordinateHeatTrace();
        const processStartMs = processStartTimestampMs(fullHeatTrace);
        const baseTrace = processStartMs === null
            ? fullHeatTrace
            : fullHeatTrace.filter((point) => Number(point.timestamp_ms) >= processStartMs);
        const trace = trimActiveHeatTrace(baseTrace);
        if (!trace.length) {
            return null;
        }
        trace.sort((left, right) => left.timestamp_ms - right.timestamp_ms);
        return {
            layer_index: Number(layer?.layer_index || ctx.selectedLayerIndex || 0),
            z_level_mm: Number(layer?.z_level_mm || 0),
            deposit_units: calculateLayerDepositUnits(layer),
            start_timestamp_ms: trace[0].timestamp_ms,
            end_timestamp_ms: trace[trace.length - 1].timestamp_ms,
            sample_count: trace.length,
            trace,
            heat_source: trace[0]?.heat_source || "thermal",
            source_mode: "emergency-fallback",
        };
    }

    function currentLayerHeatWindow() {
        const windows = buildLayerHeatWindows();
        const selectedWindow = windows.find((item) => Number(item.layer_index) === Number(ctx.selectedLayerIndex));
        if (selectedWindow && Array.isArray(selectedWindow.trace) && selectedWindow.trace.length) {
            return selectedWindow;
        }
        const firstUsableWindow = windows.find((item) => Array.isArray(item.trace) && item.trace.length);
        if (firstUsableWindow) {
            return firstUsableWindow;
        }
        return buildEmergencyHeatWindow(ctx.layerRecord()) || selectedWindow || windows[0] || null;
    }

    function renderCoordinateTrajectoryOptions() {
        const select = ctx.byId("coordinate-trajectory-select");
        if (!select) {
            return;
        }
        const options = (Array.isArray(ctx.state.layers) ? ctx.state.layers : []).map((layer) => ({
            value: String(layer.layer_index),
            label: `Layer ${layer.layer_index} · Z ${ctx.formatNumber(layer.z_level_mm, 3)} mm`,
        }));
        select.replaceChildren(
            ...options.map((optionData) => {
                const option = document.createElement("option");
                option.value = optionData.value;
                option.textContent = optionData.label;
                option.selected = Number(optionData.value) === Number(ctx.selectedLayerIndex);
                return option;
            }),
        );
        select.disabled = options.length === 0;
    }

    function renderCoordinateTrajectorySummaries() {
        const listNode = ctx.byId("trajectory-list");
        if (!listNode) {
            return;
        }
        const windows = buildLayerHeatWindows().slice(0, 12);
        listNode.replaceChildren(
            ...windows.map((item) => {
                const layerIndex = Number(item.layer_index);
                const article = document.createElement("article");
                article.className = `list-card list-card-selectable${layerIndex === Number(ctx.selectedLayerIndex) ? " list-card-selected" : ""}`;
                article.tabIndex = 0;
                article.innerHTML = `
                    <div class="list-head">
                        <strong>Layer ${layerIndex}</strong>
                        <span class="pill ${layerIndex === Number(ctx.selectedLayerIndex) ? "pill-deposit" : "pill-neutral"}">${ctx.formatInteger(item.sample_count)} heat samples</span>
                    </div>
                    <div class="list-body">Z ${ctx.formatNumber(item.z_level_mm, 3)} mm / Deposit length ${ctx.formatNumber(item.deposit_units, 2)} mm</div>
                    <div class="list-body">${ctx.formatChartTime(item.start_timestamp_ms)} -> ${ctx.formatChartTime(item.end_timestamp_ms)}</div>
                `;
                article.addEventListener("click", () => {
                    if (layerIndex === Number(ctx.selectedLayerIndex)) {
                        return;
                    }
                    ctx.selectedLayerIndex = layerIndex;
                    ctx.coordinatePlayback.geometryKey = "";
                    resetCoordinatePlayback();
                    ctx.renderDynamicSections();
                });
                article.addEventListener("keydown", (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        article.click();
                    }
                });
                return article;
            }),
        );
    }

    function interpolateCoordinatePoint(start, end, ratio) {
        const lerp = (a, b) => Number(a) + (Number(b) - Number(a)) * ratio;
        const startTime = Number(start.heat_timestamp_ms ?? start.timestamp_ms ?? 0);
        const endTime = Number(end.heat_timestamp_ms ?? end.timestamp_ms ?? startTime);
        const startHeat = Number(start.heat_g_high ?? start.g_high);
        const endHeat = Number(end.heat_g_high ?? end.g_high);
        return {
            x_mm: lerp(start.x_mm, end.x_mm),
            y_mm: lerp(start.y_mm, end.y_mm),
            z_mm: lerp(start.z_mm ?? 0, end.z_mm ?? start.z_mm ?? 0),
            heat_timestamp_ms: lerp(startTime, endTime),
            heat_g_high: Number.isFinite(startHeat) && Number.isFinite(endHeat)
                ? lerp(startHeat, endHeat)
                : (Number.isFinite(endHeat) ? endHeat : startHeat),
        };
    }

    function clipCoolingTailNearEndpoint(heatTrace, depositPoints) {
        if (!Array.isArray(heatTrace) || heatTrace.length < 24 || !Array.isArray(depositPoints) || depositPoints.length < 4) {
            return heatTrace;
        }
        const lastPoint = depositPoints[depositPoints.length - 1];
        const previousPoint = depositPoints[depositPoints.length - 2] || lastPoint;
        const lastSegmentLength = Math.hypot(
            Number(lastPoint.x_mm) - Number(previousPoint.x_mm),
            Number(lastPoint.y_mm) - Number(previousPoint.y_mm),
            Number(lastPoint.z_mm ?? previousPoint.z_mm ?? 0) - Number(previousPoint.z_mm ?? 0),
        );
        const endpointRadius = ctx.clamp(lastSegmentLength * 1.1, 0.9, 1.8);
        const requiredHoldCount = Math.max(12, Math.min(28, Math.round(heatTrace.length * 0.025)));
        let candidateStart = null;
        let streakCount = 0;

        for (let index = 0; index < heatTrace.length; index += 1) {
            const sample = heatTrace[index];
            const dx = Number(sample.work_x_mm) - Number(lastPoint.x_mm);
            const dy = Number(sample.work_y_mm) - Number(lastPoint.y_mm);
            const dz = Number(sample.work_z_mm ?? lastPoint.z_mm ?? 0) - Number(lastPoint.z_mm ?? 0);
            const distanceToEnd = Math.hypot(dx, dy, dz * 1.5);
            if (distanceToEnd <= endpointRadius) {
                if (candidateStart === null) {
                    candidateStart = index;
                }
                streakCount += 1;
                if (streakCount >= requiredHoldCount && candidateStart > Math.floor(heatTrace.length * 0.45)) {
                    return heatTrace.slice(0, candidateStart + 1);
                }
            } else {
                candidateStart = null;
                streakCount = 0;
            }
        }

        return heatTrace;
    }

    function matchHeatSamplesToDepositPoints(depositPoints, heatTrace, project) {
        if (!depositPoints.length || !heatTrace.length) {
            return [];
        }
        const hasSpatialSamples = heatTrace.some((sample) => (
            Number.isFinite(Number(sample.work_x_mm))
            && Number.isFinite(Number(sample.work_y_mm))
            && Number.isFinite(Number(sample.work_z_mm))
        ));
        if (!hasSpatialSamples) {
            return depositPoints.map((point, index) => {
                const heatIndex = ctx.clampIndex(
                    Math.round((index / Math.max(depositPoints.length - 1, 1)) * (heatTrace.length - 1)),
                    heatTrace.length - 1,
                );
                const heatPoint = heatTrace[heatIndex];
                return {
                    ...point,
                    projected: project(point),
                    heat_g_high: Number(heatPoint.g_high),
                    heat_timestamp_ms: Number(heatPoint.heat_timestamp_ms ?? heatPoint.timestamp_ms),
                    heat_source: heatPoint.heat_source || "edge",
                    matched_work_x_mm: null,
                    matched_work_y_mm: null,
                    matched_work_z_mm: null,
                };
            });
        }
        let cursor = 0;
        const lastHeatIndex = Math.max(heatTrace.length - 1, 1);
        const searchWindow = Math.max(24, Math.min(80, Math.round(heatTrace.length / 14)));
        return depositPoints.map((point, index) => {
            const targetRatio = depositPoints.length > 1 ? index / (depositPoints.length - 1) : 0;
            const expectedIndex = Math.round(targetRatio * lastHeatIndex);
            const searchStart = Math.max(cursor, expectedIndex - searchWindow);
            const searchEnd = Math.max(searchStart, Math.min(lastHeatIndex, expectedIndex + searchWindow));
            let bestIndex = searchStart;
            let bestScore = Number.POSITIVE_INFINITY;
            for (let sampleIndex = searchStart; sampleIndex <= searchEnd; sampleIndex += 1) {
                const sample = heatTrace[sampleIndex];
                const dx = Number(sample.work_x_mm) - Number(point.x_mm);
                const dy = Number(sample.work_y_mm) - Number(point.y_mm);
                const dz = Number(sample.work_z_mm ?? point.z_mm ?? 0) - Number(point.z_mm ?? 0);
                const distanceScore = Math.hypot(dx, dy, dz * 1.5);
                const ratioScore = (Math.abs(sampleIndex - expectedIndex) / Math.max(searchWindow, 1)) * 10.0;
                const stallPenalty = sampleIndex === cursor && index > 0 && expectedIndex > cursor ? 0.75 : 0;
                const score = distanceScore + ratioScore + stallPenalty;
                if (score < bestScore) {
                    bestScore = score;
                    bestIndex = sampleIndex;
                }
            }
            if (bestIndex === cursor && index > 0 && expectedIndex > cursor + 1) {
                bestIndex = Math.min(searchEnd, cursor + 1);
            }
            cursor = bestIndex;
            const heatPoint = heatTrace[bestIndex];
            return {
                ...point,
                projected: project(point),
                heat_g_high: Number(heatPoint.g_high),
                heat_timestamp_ms: Number(heatPoint.heat_timestamp_ms ?? heatPoint.timestamp_ms),
                heat_source: heatPoint.heat_source || "edge",
                matched_work_x_mm: Number(heatPoint.work_x_mm),
                matched_work_y_mm: Number(heatPoint.work_y_mm),
                matched_work_z_mm: Number(heatPoint.work_z_mm),
            };
        });
    }

    function buildCoordinateGeometry() {
        const layer = ctx.layerRecord();
        const heatWindow = currentLayerHeatWindow();
        const points = Array.isArray(layer?.motion_points) ? layer.motion_points : [];
        const bounds = layer?.bounds;
        const heatTrace = Array.isArray(heatWindow?.trace) ? heatWindow.trace : [];
        if (!points.length || !bounds || heatTrace.length < 2) {
            return null;
        }

        const depositPoints = points.filter((point) => point?.laser_on && Number.isFinite(Number(point.x_mm)) && Number.isFinite(Number(point.y_mm)));
        if (depositPoints.length < 2) {
            return null;
        }
        const effectiveHeatTrace = clipCoolingTailNearEndpoint(heatTrace, depositPoints);
        if (effectiveHeatTrace.length < 2) {
            return null;
        }

        const width = 900;
        const height = 420;
        const padding = { left: 70, right: 40, top: 30, bottom: 50 };
        const plotWidth = width - padding.left - padding.right;
        const plotHeight = height - padding.top - padding.bottom;
        const xSpan = Math.max(Number(bounds.x_max_mm) - Number(bounds.x_min_mm), 1);
        const ySpan = Math.max(Number(bounds.y_max_mm) - Number(bounds.y_min_mm), 1);

        const project = (point) => ({
            x: padding.left + ((Number(point.x_mm) - Number(bounds.x_min_mm)) / xSpan) * plotWidth,
            y: padding.top + (1 - (Number(point.y_mm) - Number(bounds.y_min_mm)) / ySpan) * plotHeight,
        });

        const mappedPoints = matchHeatSamplesToDepositPoints(depositPoints, effectiveHeatTrace, project);

        const heatValues = mappedPoints.map((point) => Number(point.heat_g_high)).filter((value) => Number.isFinite(value));
        const heatMin = heatValues.length ? Math.min(...heatValues) : 0;
        const heatMax = heatValues.length ? Math.max(...heatValues) : 1;
        const heatAverage = heatValues.length
            ? heatValues.reduce((sum, value) => sum + Number(value), 0) / heatValues.length
            : null;
        const heatSummary = ctx.summarizeHeatAlertSamples(effectiveHeatTrace, (point) => point.g_high);

        const gridLines = [];
        for (let index = 0; index <= 4; index += 1) {
            const y = padding.top + (plotHeight / 4) * index;
            gridLines.push(`<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" class="grid-line" />`);
        }

        const guideDots = [];
        const pointStep = Math.max(1, Math.floor(mappedPoints.length / 180));
        mappedPoints.forEach((point, index) => {
            if (index % pointStep !== 0 && index !== 0 && index !== mappedPoints.length - 1) {
                return;
            }
            guideDots.push(`<circle cx="${point.projected.x.toFixed(2)}" cy="${point.projected.y.toFixed(2)}" r="2" class="coordinate-guide-dot" />`);
        });

        const segments = [];
        const backgroundSegments = [];
        let totalUnits = 0;
        for (let index = 1; index < mappedPoints.length; index += 1) {
            const startPoint = mappedPoints[index - 1];
            const endPoint = mappedPoints[index];
            const lineGap = Math.abs(Number(endPoint.line_no ?? index) - Number(startPoint.line_no ?? (index - 1)));
            const actualLength = Math.hypot(
                Number(endPoint.x_mm) - Number(startPoint.x_mm),
                Number(endPoint.y_mm) - Number(startPoint.y_mm),
                Number(endPoint.z_mm ?? startPoint.z_mm ?? 0) - Number(startPoint.z_mm ?? 0),
            );
            if (lineGap > 6 || actualLength > 12) {
                continue;
            }
            const unitLength = Math.max(actualLength, 0.08);
            const heatValue = (Number(startPoint.heat_g_high) + Number(endPoint.heat_g_high)) / 2;
            backgroundSegments.push(`<line x1="${startPoint.projected.x.toFixed(2)}" y1="${startPoint.projected.y.toFixed(2)}" x2="${endPoint.projected.x.toFixed(2)}" y2="${endPoint.projected.y.toFixed(2)}" class="coordinate-heat-ghost" />`);
            segments.push({
                startPoint,
                endPoint,
                startProjected: startPoint.projected,
                endProjected: endPoint.projected,
                startUnits: totalUnits,
                endUnits: totalUnits + unitLength,
                heatValue,
                index,
            });
            totalUnits += unitLength;
        }

        if (!segments.length) {
            return null;
        }

        const firstPoint = segments[0].startPoint;
        const lastPoint = segments[segments.length - 1].endPoint;
        const staticMarkup = `
            ${gridLines.join("")}
            ${backgroundSegments.join("")}
            ${guideDots.join("")}
            <circle cx="${firstPoint.projected.x.toFixed(2)}" cy="${firstPoint.projected.y.toFixed(2)}" r="7" class="marker-start" />
            <circle cx="${lastPoint.projected.x.toFixed(2)}" cy="${lastPoint.projected.y.toFixed(2)}" r="7" class="marker-end" />
            <text x="${padding.left}" y="18" class="axis-label">X ${ctx.formatNumber(bounds.x_min_mm, 2)} ~ ${ctx.formatNumber(bounds.x_max_mm, 2)} mm</text>
            <text x="${width - padding.right}" y="18" text-anchor="end" class="axis-label">Y ${ctx.formatNumber(bounds.y_min_mm, 2)} ~ ${ctx.formatNumber(bounds.y_max_mm, 2)} mm</text>
        `;

        const durationSeconds = Math.max(
            (Number(effectiveHeatTrace[effectiveHeatTrace.length - 1]?.heat_timestamp_ms ?? effectiveHeatTrace[effectiveHeatTrace.length - 1]?.timestamp_ms)
                - Number(effectiveHeatTrace[0]?.heat_timestamp_ms ?? effectiveHeatTrace[0]?.timestamp_ms)) / 1000,
            1,
        );
        return {
            width,
            height,
            points: mappedPoints,
            segments,
            staticMarkup,
            totalUnits,
            startProjected: firstPoint.projected,
            endProjected: lastPoint.projected,
            heatMin,
            heatMax,
            heatAverage,
            heatSummary,
            pointStep,
            layerIndex: layer.layer_index,
            zLevelMm: layer.z_level_mm,
            heatWindow: {
                ...heatWindow,
                trace: effectiveHeatTrace,
                sample_count: effectiveHeatTrace.length,
                start_timestamp_ms: Number(effectiveHeatTrace[0]?.heat_timestamp_ms ?? effectiveHeatTrace[0]?.timestamp_ms ?? heatWindow.start_timestamp_ms),
                end_timestamp_ms: Number(effectiveHeatTrace[effectiveHeatTrace.length - 1]?.heat_timestamp_ms ?? effectiveHeatTrace[effectiveHeatTrace.length - 1]?.timestamp_ms ?? heatWindow.end_timestamp_ms),
            },
            heatSource: heatWindow.heat_source || "edge",
            sourceMode: heatWindow.source_mode || "ratio-fallback",
            baseUnitsPerSecond: Math.max(totalUnits / durationSeconds, totalUnits / 18, 2.5),
        };
    }

    function coordinatePlaybackKey(layer, heatWindow) {
        return [
            ctx.state.selected_output_name ?? "",
            layer?.layer_index ?? "",
            layer?.motion_points?.length ?? "",
            heatWindow?.trace?.length ?? "",
            heatWindow?.start_timestamp_ms ?? "",
            heatWindow?.end_timestamp_ms ?? "",
            heatWindow?.heat_source ?? "",
            heatWindow?.source_mode ?? "",
        ].join("|");
    }

    function ensureCoordinatePlaybackGeometry() {
        const layer = ctx.layerRecord();
        const heatWindow = currentLayerHeatWindow();
        const nextKey = coordinatePlaybackKey(layer, heatWindow);
        if (ctx.coordinatePlayback.geometryKey !== nextKey) {
            ctx.pauseCoordinatePlayback();
            ctx.coordinatePlayback.geometryKey = nextKey;
            ctx.coordinatePlayback.geometry = buildCoordinateGeometry();
            ctx.coordinatePlayback.totalUnits = ctx.coordinatePlayback.geometry?.totalUnits ?? 0;
            ctx.coordinatePlayback.progressUnits = 0;
        }
        return ctx.coordinatePlayback.geometry;
    }

    function buildCoordinatePlaybackSnapshot(geometry) {
        if (!geometry || !geometry.points.length) {
            return null;
        }
        const totalUnits = ctx.coordinatePlayback.totalUnits || geometry.totalUnits || 0;
        const progressUnits = ctx.clamp(ctx.coordinatePlayback.progressUnits, 0, totalUnits);
        const activeDots = [];
        let headProjected = geometry.startProjected;
        let headPoint = geometry.points[0];
        let headHeat = Number(headPoint.heat_g_high);
        let headPointIndex = 0;

        for (const segment of geometry.segments) {
            if (progressUnits >= segment.endUnits) {
                headProjected = segment.endProjected;
                headPoint = segment.endPoint;
                headPointIndex = segment.index;
                headHeat = Number.isFinite(Number(segment.endPoint.heat_g_high)) ? Number(segment.endPoint.heat_g_high) : segment.heatValue;
                continue;
            }
            if (progressUnits > segment.startUnits) {
                const span = Math.max(segment.endUnits - segment.startUnits, 0.0001);
                const ratio = ctx.clamp((progressUnits - segment.startUnits) / span, 0, 1);
                const partialProjected = ctx.interpolatePoint(segment.startProjected, segment.endProjected, ratio);
                const partialPoint = interpolateCoordinatePoint(segment.startPoint, segment.endPoint, ratio);
                headProjected = partialProjected;
                headPoint = partialPoint;
                headPointIndex = Math.max(0, segment.index - 1);
                headHeat = Number.isFinite(Number(partialPoint.heat_g_high)) ? Number(partialPoint.heat_g_high) : segment.heatValue;
                break;
            }
            break;
        }

        if (progressUnits >= totalUnits) {
            headProjected = geometry.endProjected;
            headPoint = geometry.points[geometry.points.length - 1];
            headPointIndex = geometry.points.length - 1;
            headHeat = Number(headPoint.heat_g_high);
        }

        const trailWindow = 120;
        const renderStep = Math.max(1, geometry.pointStep);
        const trailStartIndex = Math.max(0, headPointIndex - trailWindow);
        for (let index = trailStartIndex; index <= headPointIndex; index += renderStep) {
            const point = geometry.points[index];
            const ageRatio = headPointIndex <= trailStartIndex ? 1 : (index - trailStartIndex) / Math.max(headPointIndex - trailStartIndex, 1);
            const color = ctx.coordinateHeatColor(point.heat_g_high, geometry.heatMin, geometry.heatMax);
            const glowRadius = 8 + ageRatio * 10;
            const coreRadius = 2.2 + ageRatio * 2.6;
            const glowOpacity = 0.08 + ageRatio * 0.18;
            const coreOpacity = 0.24 + ageRatio * 0.58;
            activeDots.push(
                `<circle cx="${point.projected.x.toFixed(2)}" cy="${point.projected.y.toFixed(2)}" r="${glowRadius.toFixed(2)}" class="coordinate-heat-spot-glow" style="fill:${color};opacity:${glowOpacity.toFixed(3)}" />`,
                `<circle cx="${point.projected.x.toFixed(2)}" cy="${point.projected.y.toFixed(2)}" r="${coreRadius.toFixed(2)}" class="coordinate-heat-spot-core" style="fill:${color};opacity:${coreOpacity.toFixed(3)}" />`,
            );
        }

        return {
            activeMarkup: activeDots.join(""),
            headProjected,
            headPoint,
            headHeat,
            progressRatio: totalUnits > 0 ? progressUnits / totalUnits : 0,
        };
    }

    function renderCoordinateAlertPanel(geometry, snapshot) {
        const panel = ctx.byId("coordinate-alert-panel");
        if (!panel) {
            return;
        }
        if (!geometry || !Array.isArray(geometry.points) || !geometry.points.length) {
            panel.innerHTML = `
                <div class="coordinate-alert-empty">
                    <strong>尚未建立熱像同步警示。</strong>
                    <p>請先選擇有熱資料與沉積路徑的 layer，系統才會根據 G-code Heat Playback 顯示即時警示。</p>
                </div>
            `;
            return;
        }

        const point = snapshot?.headPoint || geometry.points[0];
        const pointTime = point?.heat_timestamp_ms ?? point?.timestamp_ms ?? null;
        const status = ctx.classifyHeatAlert(point?.heat_g_high);
        const summary = geometry.heatSummary || ctx.summarizeHeatAlertSamples(geometry.heatWindow?.trace, (item) => item.g_high);
        const progressText = `${((snapshot?.progressRatio ?? 0) * 100).toFixed(1)}%`;
        const cardMarkup = ctx.heatAlertBands.map((band) => {
            const count = Number(summary?.[band.key] || 0);
            const ratioText = summary?.total ? `${((count / summary.total) * 100).toFixed(1)}%` : "0.0%";
            const activeClass = status.key === band.key ? " is-active" : "";
            return `
                <article class="coordinate-alert-card ${band.badgeClass}${activeClass}">
                    <span class="coordinate-alert-card-label">${band.label}</span>
                    <strong class="coordinate-alert-card-value">${ctx.formatInteger(count)} 點</strong>
                    <div class="coordinate-alert-card-meta">
                        <span>${ratioText}</span>
                        <span>${summary?.total ? `${ctx.formatInteger(summary.total)} 筆樣本` : "0 筆樣本"}</span>
                    </div>
                    <div class="coordinate-alert-card-range">${band.rangeLabel}</div>
                </article>
            `;
        }).join("");

        panel.innerHTML = `
            <div class="coordinate-alert-overview">
                <div class="coordinate-alert-copy">
                    <p class="coordinate-alert-kicker">熱像同步警示</p>
                    <p class="coordinate-alert-reading">${ctx.formatNumber(point?.heat_g_high, 2)} °C</p>
                    <p class="coordinate-alert-meta">Layer ${ctx.formatInteger(geometry.layerIndex)} · ${ctx.formatChartTime(pointTime)} · 播放進度 ${progressText}</p>
                    <p class="coordinate-alert-description">${status.description}</p>
                </div>
                <span class="coordinate-alert-badge ${status.badgeClass}">${status.label}</span>
            </div>
            <div class="coordinate-alert-grid">${cardMarkup}</div>
            <div class="coordinate-alert-footer">
                <span>本層峰值 ${ctx.formatNumber(geometry.heatMax, 2)} °C</span>
                <span>本層平均 ${ctx.formatNumber(geometry.heatAverage, 2)} °C</span>
                <span>X ${ctx.formatNumber(point?.x_mm, 2)} / Y ${ctx.formatNumber(point?.y_mm, 2)} / Z ${ctx.formatNumber(point?.z_mm, 2)} mm</span>
            </div>
        `;
    }

    function updateCoordinateControls(geometry, snapshot) {
        const playButton = ctx.byId("coordinate-play-button");
        const resetButton = ctx.byId("coordinate-reset-button");
        const range = ctx.byId("coordinate-progress-range");
        const speedSelect = ctx.byId("coordinate-speed-select");
        const progressLabel = ctx.byId("coordinate-progress-label");
        const statusLabel = ctx.byId("coordinate-status");
        const toolbarNote = ctx.byId("coordinate-toolbar-note");
        const hasPath = Boolean(geometry && geometry.points.length > 1 && geometry.segments.length);
        const ratio = snapshot?.progressRatio ?? 0;
        const sliderValue = Math.round(ratio * ctx.progressSliderMax);

        if (playButton) {
            playButton.disabled = !hasPath;
            playButton.textContent = ctx.coordinatePlayback.isPlaying ? "暫停" : "播放";
        }
        if (resetButton) {
            resetButton.disabled = !hasPath;
        }
        if (range) {
            range.disabled = !hasPath;
            range.value = String(sliderValue);
        }
        if (speedSelect) {
            speedSelect.value = String(ctx.coordinatePlayback.speedMultiplier);
            speedSelect.disabled = !hasPath;
        }
        if (progressLabel) {
            progressLabel.textContent = `${(ratio * 100).toFixed(1)}%`;
        }
        if (toolbarNote) {
            toolbarNote.textContent = hasPath
                ? `目前使用 Layer ${geometry.layerIndex} 的 G-code 沉積路徑作為骨架，並將對齊後的 G_High 熱值沿路徑播放。`
                : "目前沒有可用的 G-code 熱路徑資料。";
        }
        if (statusLabel) {
            if (!hasPath) {
                statusLabel.textContent = "請切換到有沉積路徑與熱資料的 layer。";
                return;
            }
            const point = snapshot?.headPoint || geometry.points[0];
            const pointTime = point.heat_timestamp_ms ?? point.timestamp_ms ?? null;
            const finishedText = ratio >= 1 ? " / 已完成" : "";
            statusLabel.textContent = `Layer ${geometry.layerIndex} / ${ctx.formatChartTime(pointTime)} / G_High ${ctx.formatNumber(point.heat_g_high, 2)} / X ${ctx.formatNumber(point.x_mm, 2)} / Y ${ctx.formatNumber(point.y_mm, 2)}${finishedText}`;
        }
    }

    function renderCoordinatePlaybackFrame(frameTimeMs) {
        if (!ctx.coordinatePlayback.isPlaying || !ctx.coordinatePlayback.geometry) {
            return;
        }
        if (!ctx.coordinatePlayback.lastFrameMs) {
            ctx.coordinatePlayback.lastFrameMs = frameTimeMs;
        }
        const elapsedSeconds = Math.max((frameTimeMs - ctx.coordinatePlayback.lastFrameMs) / 1000, 0);
        ctx.coordinatePlayback.lastFrameMs = frameTimeMs;
        const advance = elapsedSeconds * ctx.coordinatePlayback.geometry.baseUnitsPerSecond * ctx.coordinatePlayback.speedMultiplier;
        ctx.coordinatePlayback.progressUnits = ctx.clamp(
            ctx.coordinatePlayback.progressUnits + advance,
            0,
            ctx.coordinatePlayback.totalUnits || ctx.coordinatePlayback.geometry.totalUnits || 0,
        );
        renderCoordinateAlignment();
        if (ctx.coordinatePlayback.progressUnits >= (ctx.coordinatePlayback.totalUnits || ctx.coordinatePlayback.geometry.totalUnits || 0)) {
            ctx.pauseCoordinatePlayback();
            renderCoordinateAlignment();
            return;
        }
        ctx.coordinatePlayback.rafId = window.requestAnimationFrame(renderCoordinatePlaybackFrame);
    }

    function startCoordinatePlayback() {
        const geometry = ensureCoordinatePlaybackGeometry();
        if (!geometry || geometry.segments.length === 0) {
            renderCoordinateAlignment();
            return;
        }
        if (ctx.coordinatePlayback.progressUnits >= (ctx.coordinatePlayback.totalUnits || geometry.totalUnits)) {
            ctx.coordinatePlayback.progressUnits = 0;
        }
        ctx.pauseCoordinatePlayback();
        ctx.coordinatePlayback.isPlaying = true;
        ctx.coordinatePlayback.lastFrameMs = 0;
        renderCoordinateAlignment();
        ctx.coordinatePlayback.rafId = window.requestAnimationFrame(renderCoordinatePlaybackFrame);
    }

    function resetCoordinatePlayback() {
        ctx.pauseCoordinatePlayback();
        ctx.coordinatePlayback.progressUnits = 0;
        renderCoordinateAlignment();
    }

    function bindCoordinatePlaybackControls() {
        const playButton = ctx.byId("coordinate-play-button");
        const resetButton = ctx.byId("coordinate-reset-button");
        const range = ctx.byId("coordinate-progress-range");
        const speedSelect = ctx.byId("coordinate-speed-select");
        const layerSelect = ctx.byId("coordinate-trajectory-select");

        if (playButton && !playButton.dataset.bound) {
            playButton.addEventListener("click", () => {
                if (ctx.coordinatePlayback.isPlaying) {
                    ctx.pauseCoordinatePlayback();
                    renderCoordinateAlignment();
                    return;
                }
                startCoordinatePlayback();
            });
            playButton.dataset.bound = "true";
        }
        if (resetButton && !resetButton.dataset.bound) {
            resetButton.addEventListener("click", resetCoordinatePlayback);
            resetButton.dataset.bound = "true";
        }
        if (range && !range.dataset.bound) {
            range.addEventListener("input", (event) => {
                ctx.pauseCoordinatePlayback();
                const ratio = Number(event.target.value) / ctx.progressSliderMax;
                ctx.coordinatePlayback.progressUnits = (ctx.coordinatePlayback.totalUnits || 0) * ctx.clamp(ratio, 0, 1);
                renderCoordinateAlignment();
            });
            range.dataset.bound = "true";
        }
        if (speedSelect && !speedSelect.dataset.bound) {
            speedSelect.addEventListener("change", (event) => {
                ctx.coordinatePlayback.speedMultiplier = Number(event.target.value) || 1;
                renderCoordinateAlignment();
            });
            speedSelect.dataset.bound = "true";
        }
        if (layerSelect && !layerSelect.dataset.bound) {
            layerSelect.addEventListener("change", (event) => {
                ctx.selectedLayerIndex = Number(event.target.value) || ctx.selectedLayerIndex;
                ctx.coordinatePlayback.geometryKey = "";
                resetCoordinatePlayback();
                ctx.renderDynamicSections();
            });
            layerSelect.dataset.bound = "true";
        }
    }

    function renderCoordinateAlignment() {
        const statsNode = ctx.byId("coordinate-stats");
        const plotNode = ctx.byId("coordinate-plot");
        if (!statsNode || !plotNode) {
            return;
        }
        const layer = ctx.layerRecord();
        const heatWindow = currentLayerHeatWindow();
        renderCoordinateTrajectoryOptions();
        renderCoordinateTrajectorySummaries();

        if (!layer || !heatWindow) {
            const article = document.createElement("article");
            article.className = "metric-card";
            article.innerHTML = "<span>Status</span><strong>No G-code heat window.</strong>";
            statsNode.replaceChildren(article);
            plotNode.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">No G-code heat playback data.</text>`;
            updateCoordinateControls(null, null);
            renderCoordinateAlertPanel(null, null);
            return;
        }

        const mapping = ctx.state.accurate_time_mapping || {};
        const stats = [
            { label: "Selected Layer", value: `Layer ${ctx.formatInteger(layer.layer_index)}` },
            { label: "Z Level", value: `${ctx.formatNumber(layer.z_level_mm, 3)} mm` },
            { label: "Heat Samples", value: ctx.formatInteger(heatWindow.sample_count) },
            { label: "Window Start", value: ctx.formatChartTime(heatWindow.start_timestamp_ms) },
            { label: "Window End", value: ctx.formatChartTime(heatWindow.end_timestamp_ms) },
            { label: "Time Mapping", value: mapping.offset_s !== undefined ? `${ctx.formatNumber(mapping.offset_s, 3)} s` : "-" },
        ];
        statsNode.replaceChildren(
            ...stats.map((metric) => {
                const article = document.createElement("article");
                article.className = "metric-card";
                article.innerHTML = `<span>${metric.label}</span><strong>${metric.value}</strong>`;
                return article;
            }),
        );

        const geometry = ensureCoordinatePlaybackGeometry();
        if (!geometry) {
            plotNode.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">No deposit toolpath for this layer.</text>`;
            updateCoordinateControls(null, null);
            renderCoordinateAlertPanel(null, null);
            return;
        }

        const snapshot = buildCoordinatePlaybackSnapshot(geometry);
        const headColor = ctx.coordinateHeatColor(snapshot?.headHeat, geometry.heatMin, geometry.heatMax);
        const headMarkup = snapshot
            ? `
                <circle cx="${snapshot.headProjected.x.toFixed(2)}" cy="${snapshot.headProjected.y.toFixed(2)}" r="13" class="coordinate-head-halo" style="fill:${headColor}" />
                <circle cx="${snapshot.headProjected.x.toFixed(2)}" cy="${snapshot.headProjected.y.toFixed(2)}" r="6.5" class="coordinate-head-core" style="fill:${headColor}" />
            `
            : "";

        plotNode.innerHTML = `
            ${geometry.staticMarkup}
            ${snapshot?.activeMarkup || ""}
            ${headMarkup}
        `;
        updateCoordinateControls(geometry, snapshot);
        renderCoordinateAlertPanel(geometry, snapshot);
    }

    ctx.resetCoordinatePlayback = resetCoordinatePlayback;

    return {
        renderCoordinateAlignment,
        bindCoordinatePlaybackControls,
        resetCoordinatePlayback,
    };
}
