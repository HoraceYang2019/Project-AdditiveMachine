(async function () {
    const dashboardUrl = window.location.search
        ? `/api/dashboard-data${window.location.search}`
        : "/api/dashboard-data";
    const response = await fetch(dashboardUrl);
    const state = await response.json();
    const byId = (id) => document.getElementById(id);
    const segmentTypeLabels = {
        deposit: "沉積",
        travel: "移動",
        retract: "抬升",
        approach: "接近",
        unknown: "未知",
    };
    const eventActionLabels = {
        set: "設定",
        clear: "清除",
    };
    const noteLabels = {
        Dwell: "停留",
        "Powder supply": "送粉",
        "LASER safety lock on": "雷射安全鎖開啟",
        "WAIT FOR THE POWDER REFILL ALL THE SPACE IN TUBE": "等待粉末填滿整個管路空間",
        "LASER ON": "雷射開啟",
        "LASER OFF": "雷射關閉",
        "Laser on": "雷射開啟",
        "Laser off": "雷射關閉",
    };

    let selectedLayerIndex = state.layers[0]?.layer_index ?? 1;
    const progressSliderMax = 1000;
    const heatAlertThresholds = {
        goodMax: 1300,
        abnormalMin: 1500,
    };
    const heatAlertBands = [
        {
            key: "good",
            label: "優良",
            rangeLabel: "<= 1300 °C",
            description: "目前溫度落在穩定製程區間。",
            badgeClass: "is-good",
        },
        {
            key: "warning",
            label: "警示",
            rangeLabel: "1300 < T < 1500 °C",
            description: "目前溫度接近製程上限，建議留意熱輸入。",
            badgeClass: "is-warning",
        },
        {
            key: "abnormal",
            label: "異常",
            rangeLabel: ">= 1500 °C",
            description: "目前溫度超出警戒上限，建議立即確認製程狀態。",
            badgeClass: "is-abnormal",
        },
    ];
    const playback = {
        isPlaying: false,
        speedMultiplier: 1,
        progressUnits: 0,
        totalUnits: 0,
        layerKey: "",
        geometry: null,
        rafId: 0,
        lastFrameMs: 0,
    };
    const coordinatePlayback = {
        isPlaying: false,
        speedMultiplier: 1,
        progressUnits: 0,
        totalUnits: 0,
        geometryKey: "",
        geometry: null,
        rafId: 0,
        lastFrameMs: 0,
    };
    let editorSourceText = "";
    let editorSourceFileName = "";
    let editorCanEdit = false;
    let editorIsBusy = false;
    let alignmentManualOffsetMs = Number(state.alignment?.manual_offset_default_ms || 0);
    let activeToolpathLineNo = null;
    const thermalChartView = {
        startRatio: 0,
        endRatio: 1,
        pointerId: null,
        dragStartX: 0,
        dragStartStart: 0,
        dragStartEnd: 1,
        dragMoved: false,
    };
    const alignmentChartView = {
        startRatio: 0,
        endRatio: 1,
        pointerId: null,
        dragStartX: 0,
        dragStartStart: 0,
        dragStartEnd: 1,
        dragMoved: false,
    };
    let selectedThermalPoint = null;
    let selectedAlignmentPoint = null;

    function layerRecord() {
        return state.layers.find((item) => item.layer_index === Number(selectedLayerIndex)) || state.layers[0];
    }

    function formatNumber(value, digits = 3) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) {
            return "-";
        }
        return Number(value).toFixed(digits);
    }

    function formatInteger(value) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) {
            return "-";
        }
        return `${Math.round(Number(value))}`;
    }

    function formatSignedMilliseconds(value) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) {
            return "-";
        }
        const rounded = Math.round(Number(value));
        const prefix = rounded > 0 ? "+" : "";
        return `${prefix}${rounded} ms`;
    }

    function heatAlertBand(key) {
        return heatAlertBands.find((item) => item.key === key) || heatAlertBands[0];
    }

    function classifyHeatAlert(value) {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) {
            return {
                key: "unknown",
                label: "未判定",
                rangeLabel: "-",
                description: "尚未取得可用的熱像溫度資料。",
                badgeClass: "is-unknown",
            };
        }
        if (numeric <= heatAlertThresholds.goodMax) {
            return { ...heatAlertBand("good"), value: numeric };
        }
        if (numeric < heatAlertThresholds.abnormalMin) {
            return { ...heatAlertBand("warning"), value: numeric };
        }
        return { ...heatAlertBand("abnormal"), value: numeric };
    }

    function summarizeHeatAlertSamples(points, valueSelector = (point) => point) {
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
            const level = classifyHeatAlert(numeric).key;
            if (level === "good" || level === "warning" || level === "abnormal") {
                summary[level] += 1;
                summary.total += 1;
            }
        }
        return summary;
    }

    function isRelativeTimestamp(timestampMs) {
        return Number.isFinite(Number(timestampMs)) && Math.abs(Number(timestampMs)) < 100000000000;
    }

    function formatRelativeTimestamp(timestampMs) {
        const rounded = Math.round(Number(timestampMs));
        const sign = rounded < 0 ? "-" : "";
        return `T${sign}+${Math.abs(rounded)} ms`;
    }

    function formatChartTime(timestampMs) {
        if (isRelativeTimestamp(timestampMs)) {
            return formatRelativeTimestamp(timestampMs);
        }
        const date = new Date(Number(timestampMs));
        if (Number.isNaN(date.getTime())) {
            return "-";
        }

        const pad = (value, size = 2) => String(value).padStart(size, "0");
        return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
    }

    function formatFullTimestamp(timestampMs) {
        if (isRelativeTimestamp(timestampMs)) {
            return formatRelativeTimestamp(timestampMs);
        }
        const date = new Date(Number(timestampMs));
        if (Number.isNaN(date.getTime())) {
            return "-";
        }

        const pad = (value, size = 2) => String(value).padStart(size, "0");
        return [
            `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
            `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`,
        ].join(" ");
    }

    function clampIndex(value, maxIndex) {
        return Math.min(Math.max(Number(value) || 0, 0), Math.max(Number(maxIndex) || 0, 0));
    }

    function setText(id, text) {
        const node = byId(id);
        if (node) {
            node.textContent = text;
        }
    }

    function setStatus(text, type = "info") {
        const node = byId("upload-status");
        if (!node) {
            return;
        }
        node.textContent = text;
        node.dataset.status = type;
    }

    function setEditorStatus(text, type = "info") {
        const node = byId("mpf-editor-status");
        if (!node) {
            return;
        }
        node.textContent = text;
        node.dataset.status = type;
    }

    function translateSegmentType(value) {
        return segmentTypeLabels[value] || value || "-";
    }

    function translateEventAction(value) {
        return eventActionLabels[value] || value || "-";
    }

    function translateNote(value) {
        return noteLabels[value] || value || "-";
    }

    function clamp(value, min, max) {
        return Math.min(Math.max(value, min), max);
    }

    function normalizeMpfFileName(value, fallbackStem = "edited_output") {
        const trimmed = String(value || "").trim();
        const rawName = trimmed.split(/[\\/]/).pop() || "";
        if (!rawName) {
            return `${fallbackStem}.MPF`;
        }
        const dotIndex = rawName.lastIndexOf(".");
        if (dotIndex <= 0) {
            return `${rawName}.MPF`;
        }
        return `${rawName.slice(0, dotIndex)}.MPF`;
    }

    function countEditorLines(text) {
        if (!text) {
            return 0;
        }
        return String(text).split(/\r?\n/).length;
    }

    function updateEditorLineCount(text) {
        setText("mpf-editor-line-count", `${countEditorLines(text)} 行`);
    }

    function setEditorDownloadLink(url, label, enabled = true) {
        const node = byId("mpf-editor-download");
        if (!node) {
            return;
        }
        node.textContent = label;
        node.href = enabled && url ? url : "#";
        node.setAttribute("aria-disabled", enabled ? "false" : "true");
    }

    function syncEditorControls() {
        const textArea = byId("mpf-editor-text");
        const fileNameInput = byId("mpf-editor-file-name");
        const reloadButton = byId("mpf-editor-reload");
        const previewButton = byId("mpf-editor-preview");
        const exportButton = byId("mpf-editor-export");
        if (textArea) {
            textArea.disabled = editorIsBusy || !editorCanEdit;
        }
        if (fileNameInput) {
            fileNameInput.disabled = editorIsBusy || !editorCanEdit;
        }
        if (reloadButton) {
            reloadButton.disabled = editorIsBusy || !editorCanEdit;
        }
        if (previewButton) {
            previewButton.disabled = editorIsBusy || !editorCanEdit;
        }
        if (exportButton) {
            exportButton.disabled = editorIsBusy || !editorCanEdit;
        }
    }

    function setEditorBusy(isBusy) {
        editorIsBusy = Boolean(isBusy);
        syncEditorControls();
    }

    function setEditorEditable(canEdit) {
        editorCanEdit = Boolean(canEdit);
        syncEditorControls();
    }

    function renderHeader() {
        document.title = state.header.title;
        setText("dashboard-title", state.header.title);
        setText("dashboard-subtitle", state.header.subtitle);
        setText("program-id-chip", `程式 ${state.header.program_id ?? "-"}`);
        setText("output-name-chip", `輸出 ${state.output_name ?? "-"}`);

        const headerCards = byId("header-cards");
        headerCards.replaceChildren(
            ...state.header.header_cards.map((card) => {
                const article = document.createElement("article");
                article.className = "hero-card";
                article.innerHTML = `<span>${card.label}</span><strong>${card.value}</strong>`;
                return article;
            }),
        );
    }

    function buildOutputOptions(selectedValue) {
        const outputs = Array.isArray(state.available_outputs) ? state.available_outputs : [];
        return outputs.map((output) => {
            const option = document.createElement("option");
            option.value = String(output.value ?? "");
            option.textContent = output.label ?? output.value ?? "-";
            if (option.value === String(selectedValue ?? "")) {
                option.selected = true;
            }
            return option;
        });
    }

    function renderOutputSelect() {
        const select = byId("output-select");
        if (!select) {
            return;
        }

        select.replaceChildren(...buildOutputOptions(state.selected_output_name));
        if (!select.dataset.bound) {
            select.addEventListener("change", (event) => {
                const params = new URLSearchParams(window.location.search);
                const outputName = String(event.target.value || "");
                if (outputName) {
                    params.set("output_name", outputName);
                } else {
                    params.delete("output_name");
                }
                const nextSearch = params.toString();
                window.location.search = nextSearch ? `?${nextSearch}` : "";
            });
            select.dataset.bound = "true";
        }
    }

    function renderUploadBindings() {
        const select = byId("upload-target-output");
        if (select) {
            select.replaceChildren(...buildOutputOptions(state.selected_output_name));
        }

        const edgeExampleLink = byId("edge-example-link");
        if (edgeExampleLink && state.upload_help?.edge_example_url) {
            edgeExampleLink.href = state.upload_help.edge_example_url;
        }
    }

    function renderUploadForm() {
        renderUploadBindings();
        const form = byId("upload-form");
        const submitButton = byId("upload-submit");
        if (!form || form.dataset.bound) {
            return;
        }

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const formData = new FormData(form);
            if (!formData.get("target_output_name") && state.selected_output_name) {
                formData.set("target_output_name", state.selected_output_name);
            }

            setStatus("正在上傳並處理資料，請稍候...", "working");
            if (submitButton) {
                submitButton.disabled = true;
            }

            try {
                const uploadResponse = await fetch("/api/upload-data", {
                    method: "POST",
                    body: formData,
                });
                const payload = await uploadResponse.json();
                if (!uploadResponse.ok || !payload.ok) {
                    throw new Error(payload.message || "上傳失敗。");
                }

                setStatus(payload.message || "上傳完成，正在重新整理...", "success");
                const params = new URLSearchParams(window.location.search);
                if (payload.selected_output_name) {
                    params.set("output_name", payload.selected_output_name);
                }
                const nextSearch = params.toString();
                window.location.search = nextSearch ? `?${nextSearch}` : "";
            } catch (error) {
                setStatus(error instanceof Error ? error.message : "上傳失敗。", "error");
            } finally {
                if (submitButton) {
                    submitButton.disabled = false;
                }
            }
        });

        form.dataset.bound = "true";
    }

    async function loadMpfSource() {
        const editorConfig = state.mpf_editor || {};
        const textArea = byId("mpf-editor-text");
        const fileNameInput = byId("mpf-editor-file-name");

        if (!textArea || !fileNameInput) {
            return;
        }

        if (!editorConfig.source_available || !editorConfig.load_url) {
            textArea.value = "";
            textArea.disabled = true;
            fileNameInput.value = normalizeMpfFileName(
                editorConfig.source_file_name || state.nc_file?.file_name || state.output_name,
                state.output_name || "edited_output",
            );
            setEditorEditable(false);
            setText("mpf-editor-source-label", "目前找不到可編輯的 MPF 原始檔。");
            updateEditorLineCount("");
            setEditorDownloadLink("#", "目前沒有可下載版本", false);
            setEditorStatus("請先上傳 MPF，或選擇一個有原始 MPF 的輸出版本。", "error");
            return;
        }

        setEditorBusy(true);
        setEditorStatus("正在載入目前 MPF 原文...", "working");

        try {
            const response = await fetch(editorConfig.load_url);
            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || "MPF 原文載入失敗。");
            }

            editorSourceText = String(payload.text || "");
            editorSourceFileName = normalizeMpfFileName(
                payload.file_name || editorConfig.source_file_name || state.output_name,
                state.output_name || "edited_output",
            );
            textArea.value = editorSourceText;
            fileNameInput.value = editorSourceFileName;
            setEditorEditable(true);
            setText("mpf-editor-source-label", `來源檔案：${editorSourceFileName} / 輸出版本：${payload.output_name || state.output_name}`);
            updateEditorLineCount(editorSourceText);
            setEditorDownloadLink(payload.download_url || editorConfig.download_url, "下載目前版本", true);
            setEditorStatus("MPF 原文已載入，可直接修改後預覽。", "success");
        } catch (error) {
            textArea.value = "";
            setEditorEditable(false);
            updateEditorLineCount("");
            setEditorDownloadLink("#", "目前沒有可下載版本", false);
            setEditorStatus(error instanceof Error ? error.message : "MPF 原文載入失敗。", "error");
        } finally {
            setEditorBusy(false);
        }
    }

    function renderMpfEditor() {
        const textArea = byId("mpf-editor-text");
        const fileNameInput = byId("mpf-editor-file-name");
        const reloadButton = byId("mpf-editor-reload");
        const previewButton = byId("mpf-editor-preview");
        const exportButton = byId("mpf-editor-export");
        if (!textArea || !fileNameInput || !reloadButton || !previewButton || !exportButton) {
            return;
        }

        if (!textArea.dataset.bound) {
            textArea.addEventListener("input", (event) => {
                updateEditorLineCount(event.target.value);
                setEditorStatus("已修改 MPF，尚未建立新的 preview 版本。", "info");
            });
            textArea.dataset.bound = "true";
        }

        if (!reloadButton.dataset.bound) {
            reloadButton.addEventListener("click", async () => {
                await loadMpfSource();
            });
            reloadButton.dataset.bound = "true";
        }

        if (!previewButton.dataset.bound) {
            previewButton.addEventListener("click", async () => {
                const nextFileName = normalizeMpfFileName(
                    fileNameInput.value || editorSourceFileName || state.output_name,
                    state.output_name || "edited_preview",
                );
                setEditorBusy(true);
                setEditorStatus("正在解析新的 preview 版本，請稍候...", "working");
                try {
                    const response = await fetch((state.mpf_editor || {}).preview_url || "/api/preview-mpf", {
                        method: "POST",
                        headers: { "Content-Type": "application/json; charset=utf-8" },
                        body: JSON.stringify({
                            output_name: state.selected_output_name,
                            file_name: nextFileName,
                            mpf_text: textArea.value,
                        }),
                    });
                    const payload = await response.json();
                    if (!response.ok || !payload.ok) {
                        throw new Error(payload.message || "建立 preview 版本失敗。");
                    }

                    setEditorStatus(payload.message || "Preview 版本已建立。", "success");
                    const params = new URLSearchParams(window.location.search);
                    if (payload.selected_output_name) {
                        params.set("output_name", payload.selected_output_name);
                    }
                    const nextSearch = params.toString();
                    window.location.search = nextSearch ? `?${nextSearch}` : "";
                } catch (error) {
                    setEditorStatus(error instanceof Error ? error.message : "建立 preview 版本失敗。", "error");
                    setEditorBusy(false);
                }
            });
            previewButton.dataset.bound = "true";
        }

        if (!exportButton.dataset.bound) {
            exportButton.addEventListener("click", async () => {
                const nextFileName = normalizeMpfFileName(
                    fileNameInput.value || editorSourceFileName || state.output_name,
                    state.output_name || "exported_mpf",
                );
                setEditorBusy(true);
                setEditorStatus("正在輸出新的 MPF 檔案...", "working");
                try {
                    const response = await fetch((state.mpf_editor || {}).export_url || "/api/export-mpf", {
                        method: "POST",
                        headers: { "Content-Type": "application/json; charset=utf-8" },
                        body: JSON.stringify({
                            output_name: state.selected_output_name,
                            file_name: nextFileName,
                            mpf_text: textArea.value,
                        }),
                    });
                    const payload = await response.json();
                    if (!response.ok || !payload.ok) {
                        throw new Error(payload.message || "輸出 MPF 失敗。");
                    }

                    setEditorStatus(
                        payload.saved_path
                            ? `新 MPF 已輸出：${payload.saved_path}`
                            : (payload.message || "新 MPF 已輸出。"),
                        "success",
                    );
                } catch (error) {
                    setEditorStatus(error instanceof Error ? error.message : "輸出 MPF 失敗。", "error");
                } finally {
                    setEditorBusy(false);
                }
            });
            exportButton.dataset.bound = "true";
        }

        loadMpfSource();
    }

    function renderLayerSelect() {
        const select = byId("layer-select");
        select.replaceChildren(
            ...state.layers.map((layer) => {
                const option = document.createElement("option");
                option.value = String(layer.layer_index);
                option.textContent = `第 ${layer.layer_index} 層 / Z ${formatNumber(layer.z_level_mm, 3)} mm`;
                if (layer.layer_index === selectedLayerIndex) {
                    option.selected = true;
                }
                return option;
            }),
        );

        if (!select.dataset.bound) {
            select.addEventListener("change", (event) => {
                selectedLayerIndex = Number(event.target.value);
                coordinatePlayback.geometryKey = "";
                resetCoordinatePlayback();
                renderDynamicSections();
            });
            select.dataset.bound = "true";
        }
    }

    function renderToolbar() {
        const layer = layerRecord();
        setText(
            "layer-summary",
            `${formatInteger(layer?.segment_count)} 個路徑段 / ${formatInteger(layer?.point_count)} 個點位`,
        );
        const thermalWindow = state.thermal?.sample_count
            ? `${state.thermal.start_time} 至 ${state.thermal.end_time}`
            : "尚未上傳熱像資料";
        setText("thermal-window", thermalWindow);
    }

    function renderLayerMetrics() {
        const layer = layerRecord();
        const metrics = [
            { label: "Z 高度", value: `${formatNumber(layer?.z_level_mm, 3)} mm` },
            { label: "行號範圍", value: `${layer?.line_range?.start ?? "-"} 至 ${layer?.line_range?.end ?? "-"}` },
            { label: "沉積段數", value: formatInteger(layer?.deposit_segment_count) },
            { label: "移動段數", value: formatInteger(layer?.travel_segment_count) },
            { label: "X 範圍", value: layer?.bounds ? `${formatNumber(layer.bounds.x_min_mm, 2)} 至 ${formatNumber(layer.bounds.x_max_mm, 2)}` : "-" },
            { label: "Y 範圍", value: layer?.bounds ? `${formatNumber(layer.bounds.y_min_mm, 2)} 至 ${formatNumber(layer.bounds.y_max_mm, 2)}` : "-" },
        ];

        byId("layer-metrics").replaceChildren(
            ...metrics.map((metric) => {
                const article = document.createElement("article");
                article.className = "metric-card";
                article.innerHTML = `<span>${metric.label}</span><strong>${metric.value}</strong>`;
                return article;
            }),
        );
    }

    function renderSegments() {
        const layer = layerRecord();
        const segmentList = byId("segment-list");
        const visibleSegments = (layer?.segments || []).slice(0, 14);

        segmentList.replaceChildren(
            ...visibleSegments.map((segment) => {
                const article = document.createElement("article");
                article.className = "list-card";
                const speed = segment.feed_rate_mm_min ? `${formatNumber(segment.feed_rate_mm_min, 0)} mm/min` : "-";
                const segmentTypeLabel = translateSegmentType(segment.path_type);
                const pillClass = segment.path_type === "deposit" ? "pill-deposit" : "pill-travel";
                article.innerHTML = `
                    <div class="list-head">
                        <strong>${segment.segment_id}</strong>
                        <span class="pill ${pillClass}">${segmentTypeLabel}</span>
                    </div>
                    <div class="list-body">${segment.source_range ?? "-"}</div>
                    <div class="list-body">點數 ${formatInteger(segment.point_count)} / 進給 ${speed}</div>
                `;
                return article;
            }),
        );
    }

    function currentLayerEvents() {
        const layer = layerRecord();
        const eventWindow = layer?.event_line_range || layer?.line_range;
        const start = eventWindow?.start ?? 0;
        const end = eventWindow?.end ?? Number.MAX_SAFE_INTEGER;
        return (state.parameter_events || []).filter((event) => {
            const lineNo = Number(event.line_no ?? 0);
            return lineNo >= start && lineNo <= end;
        });
    }

    function findActiveLayerEvent(events) {
        if (!Number.isFinite(Number(activeToolpathLineNo))) {
            return null;
        }
        let activeEvent = null;
        for (const event of events) {
            const eventLineNo = Number(event.line_no ?? NaN);
            if (!Number.isFinite(eventLineNo)) {
                continue;
            }
            if (eventLineNo <= Number(activeToolpathLineNo)) {
                activeEvent = event;
                continue;
            }
            break;
        }
        return activeEvent;
    }

    function renderEventFocusPanel(events, activeEvent) {
        const panel = byId("event-focus-panel");
        if (!panel) {
            return;
        }
        if (!events.length) {
            panel.innerHTML = `
                <div class="event-focus-empty">
                    <strong>目前圖層沒有雷射事件。</strong>
                    <p>切換到有雷射參數事件的圖層後，這裡會同步顯示目前事件、功率與指令內容。</p>
                </div>
            `;
            return;
        }

        const event = activeEvent || events[0];
        const detailParts = [];
        if (event.laser_power_w !== null && event.laser_power_w !== undefined) {
            detailParts.push(`${formatNumber(event.laser_power_w, 0)} W`);
        }
        if (event.spot_diameter_mm !== null && event.spot_diameter_mm !== undefined) {
            detailParts.push(`光斑 ${formatNumber(event.spot_diameter_mm, 2)} mm`);
        }
        if (event.dwell_s !== null && event.dwell_s !== undefined) {
            detailParts.push(`停留 ${formatNumber(event.dwell_s, 1)} s`);
        }
        const eventLabel = event.laser_on ? "雷射開啟" : "雷射切換";
        const statusLabel = activeEvent ? "同步中" : "待同步";
        const badgeClass = activeEvent ? (event.laser_on ? "is-deposit" : "is-travel") : "is-idle";

        panel.innerHTML = `
            <div class="event-focus-overview">
                <div class="event-focus-copy">
                    <p class="event-focus-kicker">雷射事件同步</p>
                    <p class="event-focus-reading">${event.parameter_event_id || "EVENT"}</p>
                    <p class="event-focus-meta">行號 ${event.line_no ?? "-"} · ${eventLabel} · ${statusLabel}</p>
                    <p class="event-focus-description">${detailParts.join(" / ") || translateNote(event.notes)}</p>
                </div>
                <span class="toolpath-focus-badge ${badgeClass}">${event.laser_on ? "雷射 ON" : "事件"}</span>
            </div>
            <div class="event-focus-command">${event.raw_command || "-"}</div>
        `;
    }

    function renderEvents() {
        const visibleEvents = currentLayerEvents().slice(0, 12);

        const list = byId("event-list");
        const source = visibleEvents.length > 0 ? visibleEvents : (state.parameter_events || []).slice(0, 10);
        const activeEvent = findActiveLayerEvent(source);
        renderEventFocusPanel(source, activeEvent);

        list.replaceChildren(
            ...source.map((event) => {
                const article = document.createElement("article");
                const isActive = activeEvent?.parameter_event_id === event.parameter_event_id;
                article.className = `list-card${isActive ? " list-card-active" : ""}`;
                const detailParts = [];
                if (event.laser_power_w !== null && event.laser_power_w !== undefined) {
                    detailParts.push(`${formatNumber(event.laser_power_w, 0)} W`);
                }
                if (event.spot_diameter_mm !== null && event.spot_diameter_mm !== undefined) {
                    detailParts.push(`光斑 ${formatNumber(event.spot_diameter_mm, 2)} mm`);
                }
                if (event.dwell_s !== null && event.dwell_s !== undefined) {
                    detailParts.push(`停留 ${formatNumber(event.dwell_s, 1)} s`);
                }
                article.innerHTML = `
                    <div class="list-head">
                        <strong>${event.parameter_event_id}</strong>
                        <span class="pill ${event.laser_on ? "pill-deposit" : "pill-neutral"}">${translateEventAction(event.parameter_action)}</span>
                    </div>
                    <div class="list-body">行號 ${event.line_no} / ${event.raw_command}</div>
                    <div class="list-body">${detailParts.join(" / ") || translateNote(event.notes)}</div>
                `;
                return article;
            }),
        );
    }

    function projectPoint(point, bounds, width, height, padding) {
        const plotWidth = width - padding.left - padding.right;
        const plotHeight = height - padding.top - padding.bottom;
        const xSpan = Math.max(bounds.x_max_mm - bounds.x_min_mm, 1);
        const ySpan = Math.max(bounds.y_max_mm - bounds.y_min_mm, 1);
        const x = padding.left + ((point.x_mm - bounds.x_min_mm) / xSpan) * plotWidth;
        const y = padding.top + (1 - (point.y_mm - bounds.y_min_mm) / ySpan) * plotHeight;
        return { x, y };
    }

    function createLineMarkup(start, end, cssClass) {
        return `<line x1="${start.x.toFixed(2)}" y1="${start.y.toFixed(2)}" x2="${end.x.toFixed(2)}" y2="${end.y.toFixed(2)}" class="${cssClass}" />`;
    }

    function interpolatePoint(start, end, ratio) {
        return {
            x: start.x + (end.x - start.x) * ratio,
            y: start.y + (end.y - start.y) * ratio,
        };
    }

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
            state.selected_output_name ?? "",
            layer.layer_index ?? "",
            layer.point_count ?? "",
            layer.line_range?.start ?? "",
            layer.line_range?.end ?? "",
        ].join("|");
    }

    function cancelPlaybackLoop() {
        if (playback.rafId) {
            window.cancelAnimationFrame(playback.rafId);
            playback.rafId = 0;
        }
    }

    function pausePlayback() {
        playback.isPlaying = false;
        playback.lastFrameMs = 0;
        cancelPlaybackLoop();
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

        const projectedPoints = points.map((point) => projectPoint(point, bounds, width, height, padding));
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
                createLineMarkup(
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
            <text x="${padding.left}" y="${height - 32}" class="axis-label">X ${formatNumber(bounds.x_min_mm, 2)} 至 ${formatNumber(bounds.x_max_mm, 2)} mm</text>
            <text x="${width - padding.right}" y="${height - 32}" text-anchor="end" class="axis-label">Y ${formatNumber(bounds.y_min_mm, 2)} 至 ${formatNumber(bounds.y_max_mm, 2)} mm</text>
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
        if (playback.layerKey !== nextKey) {
            pausePlayback();
            playback.layerKey = nextKey;
            playback.geometry = buildToolpathGeometry(layer);
            playback.totalUnits = playback.geometry?.totalUnits ?? 0;
            playback.progressUnits = 0;
        }
        return playback.geometry;
    }

    function buildPlaybackSnapshot(geometry) {
        if (!geometry || !geometry.points.length) {
            return null;
        }

        const totalUnits = playback.totalUnits || geometry.totalUnits || 0;
        const progressUnits = clamp(playback.progressUnits, 0, totalUnits);
        const activeSegments = [];
        let headProjected = geometry.startProjected;
        let headRaw = geometry.points[0];
        let activeType = geometry.segments[0]?.pathType || "travel";
        let traversedSegments = 0;

        for (const segment of geometry.segments) {
            if (progressUnits >= segment.endUnits) {
                activeSegments.push(
                    createLineMarkup(
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
                const ratio = clamp((progressUnits - segment.startUnits) / span, 0, 1);
                const partialProjected = interpolatePoint(segment.startProjected, segment.endProjected, ratio);
                const partialRaw = interpolateRawPoint(segment.startPoint, segment.endPoint, ratio);
                activeSegments.push(
                    createLineMarkup(
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
            progressUnits,
        };
    }

    function updateToolpathControls(geometry, snapshot) {
        const playButton = byId("toolpath-play-button");
        const resetButton = byId("toolpath-reset-button");
        const range = byId("toolpath-progress-range");
        const speedSelect = byId("toolpath-speed-select");
        const progressLabel = byId("toolpath-progress-label");
        const statusLabel = byId("toolpath-status");
        const hasPath = Boolean(geometry && geometry.points.length > 1 && geometry.segments.length);
        const ratio = snapshot?.progressRatio ?? 0;
        const sliderValue = Math.round(ratio * progressSliderMax);

        if (playButton) {
            playButton.disabled = !hasPath;
            playButton.textContent = playback.isPlaying ? "暫停" : "播放";
        }
        if (resetButton) {
            resetButton.disabled = !hasPath;
        }
        if (range) {
            range.disabled = !hasPath;
            range.value = String(sliderValue);
        }
        if (speedSelect) {
            speedSelect.value = String(playback.speedMultiplier);
            speedSelect.disabled = !hasPath;
        }
        if (progressLabel) {
            progressLabel.textContent = `${(ratio * 100).toFixed(1)}%`;
        }
        if (statusLabel) {
            if (!hasPath) {
                statusLabel.textContent = "此層沒有足夠的刀具點位可播放。";
                return;
            }
            const point = snapshot?.headRaw || geometry.points[0];
            const pathLabel = snapshot?.activeType === "deposit" ? "雷射沉積" : "移動";
            const finishedText = ratio >= 1 ? "，已播放完成" : "";
            statusLabel.textContent = `行號 ${point.line_no ?? "-"} / X ${formatNumber(point.x_mm, 2)} / Y ${formatNumber(point.y_mm, 2)} / Z ${formatNumber(point.z_mm, 3)} / ${pathLabel}${finishedText}`;
        }
    }

    function renderToolpathFocusPanel(geometry, snapshot) {
        const panel = byId("toolpath-focus-panel");
        if (!panel) {
            return;
        }
        if (!geometry || !geometry.points.length) {
            panel.innerHTML = `
                <div class="toolpath-focus-empty">
                    <strong>尚未建立路徑播放監看。</strong>
                    <p>請先切換到有工具路徑的圖層，右側才會同步顯示目前行號、座標與沉積狀態。</p>
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
                description: "目前為雷射沉積路徑，建議同步觀察熱像變化與層內位置。",
            }
            : activeType === "travel"
                ? {
                    label: "移動",
                    badgeClass: "is-travel",
                    description: "目前為移動段，適合觀察換道、回程與邊界位置。",
                }
                : {
                    label: "待機",
                    badgeClass: "is-idle",
                    description: "目前尚未進入有效播放路徑。",
                };

        panel.innerHTML = `
            <div class="toolpath-focus-overview">
                <div class="toolpath-focus-copy">
                    <p class="toolpath-focus-kicker">路徑同步監看</p>
                    <p class="toolpath-focus-reading">L${point.line_no ?? "-"}</p>
                    <p class="toolpath-focus-meta">播放進度 ${progressText} · 已通過 ${formatInteger(traversedSegments)} / ${formatInteger(geometry.segments.length)} 段</p>
                    <p class="toolpath-focus-description">${status.description}</p>
                </div>
                <span class="toolpath-focus-badge ${status.badgeClass}">${status.label}</span>
            </div>
            <div class="toolpath-focus-grid">
                <article class="toolpath-focus-card">
                    <span>X</span>
                    <strong>${formatNumber(point.x_mm, 2)} mm</strong>
                </article>
                <article class="toolpath-focus-card">
                    <span>Y</span>
                    <strong>${formatNumber(point.y_mm, 2)} mm</strong>
                </article>
                <article class="toolpath-focus-card">
                    <span>Z</span>
                    <strong>${formatNumber(point.z_mm, 3)} mm</strong>
                </article>
            </div>
            <div class="toolpath-focus-footer">
                <span>圖層 ${formatInteger(layerRecord()?.layer_index)}</span>
                <span>點位 ${formatInteger(geometry.points.length)} 筆</span>
                <span>目前線號 ${point.line_no ?? "-"}</span>
            </div>
        `;
    }

    function renderToolpath() {
        const svg = byId("toolpath-plot");
        const layer = layerRecord();
        const geometry = ensurePlaybackGeometry(layer);

        if (!geometry) {
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">沒有運動點位資料</text>`;
            activeToolpathLineNo = null;
            updateToolpathControls(null, null);
            renderToolpathFocusPanel(null, null);
            renderEvents();
            return;
        }

        const snapshot = buildPlaybackSnapshot(geometry);
        activeToolpathLineNo = Number(snapshot?.headRaw?.line_no ?? geometry.points[0]?.line_no ?? NaN);
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
        renderEvents();
    }

    function renderToolpathFrame(frameTimeMs) {
        if (!playback.isPlaying || !playback.geometry) {
            return;
        }

        if (!playback.lastFrameMs) {
            playback.lastFrameMs = frameTimeMs;
        }
        const elapsedSeconds = Math.max((frameTimeMs - playback.lastFrameMs) / 1000, 0);
        playback.lastFrameMs = frameTimeMs;

        const advance = elapsedSeconds * playback.geometry.baseUnitsPerSecond * playback.speedMultiplier;
        playback.progressUnits = clamp(
            playback.progressUnits + advance,
            0,
            playback.totalUnits || playback.geometry.totalUnits || 0,
        );
        renderToolpath();

        if (playback.progressUnits >= (playback.totalUnits || playback.geometry.totalUnits || 0)) {
            pausePlayback();
            renderToolpath();
            return;
        }

        playback.rafId = window.requestAnimationFrame(renderToolpathFrame);
    }

    function startPlayback() {
        const geometry = ensurePlaybackGeometry(layerRecord());
        if (!geometry || geometry.segments.length === 0) {
            renderToolpath();
            return;
        }

        if (playback.progressUnits >= (playback.totalUnits || geometry.totalUnits)) {
            playback.progressUnits = 0;
        }

        pausePlayback();
        playback.isPlaying = true;
        playback.lastFrameMs = 0;
        renderToolpath();
        playback.rafId = window.requestAnimationFrame(renderToolpathFrame);
    }

    function resetPlayback() {
        pausePlayback();
        playback.progressUnits = 0;
        renderToolpath();
    }

    function bindToolpathControls() {
        const playButton = byId("toolpath-play-button");
        const resetButton = byId("toolpath-reset-button");
        const range = byId("toolpath-progress-range");
        const speedSelect = byId("toolpath-speed-select");

        if (playButton && !playButton.dataset.bound) {
            playButton.addEventListener("click", () => {
                if (playback.isPlaying) {
                    pausePlayback();
                    renderToolpath();
                    return;
                }
                startPlayback();
            });
            playButton.dataset.bound = "true";
        }

        if (resetButton && !resetButton.dataset.bound) {
            resetButton.addEventListener("click", () => {
                resetPlayback();
            });
            resetButton.dataset.bound = "true";
        }

        if (range && !range.dataset.bound) {
            range.addEventListener("input", (event) => {
                pausePlayback();
                const ratio = Number(event.target.value) / progressSliderMax;
                playback.progressUnits = (playback.totalUnits || 0) * clamp(ratio, 0, 1);
                renderToolpath();
            });
            range.dataset.bound = "true";
        }

        if (speedSelect && !speedSelect.dataset.bound) {
            speedSelect.addEventListener("change", (event) => {
                playback.speedMultiplier = Number(event.target.value) || 1;
                renderToolpath();
            });
            speedSelect.dataset.bound = "true";
        }
    }

    function renderThermal() {
        const thermal = state.thermal || {};
        const stats = [
            { label: "取樣數", value: formatInteger(thermal.sample_count) },
            { label: "G_High 最小值", value: formatNumber(thermal.g_high_min, 2) },
            { label: "G_High 平均值", value: formatNumber(thermal.g_high_avg, 2) },
            { label: "G_High 最大值", value: formatNumber(thermal.g_high_max, 2) },
        ];

        byId("thermal-stats").replaceChildren(
            ...stats.map((metric) => {
                const article = document.createElement("article");
                article.className = "metric-card";
                article.innerHTML = `<span>${metric.label}</span><strong>${metric.value}</strong>`;
                return article;
            }),
        );

        const svg = byId("thermal-chart");
        const trace = thermal.thermal_trace || [];
        if (!trace.length) {
            const message = thermal.source_kind === "missing" ? "尚未上傳熱像趨勢資料" : "沒有熱像趨勢資料";
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">${message}</text>`;
            return;
        }

        const width = 900;
        const height = 320;
        const left = 60;
        const right = 24;
        const top = 24;
        const bottom = 50;
        const plotWidth = width - left - right;
        const plotHeight = height - top - bottom;
        const maxValue = Math.max(...trace.map((item) => Number(item.g_high)), 1);
        const minValue = Math.min(...trace.map((item) => Number(item.g_high)), 0);
        const valueSpan = Math.max(maxValue - minValue, 1);
        const step = trace.length > 1 ? plotWidth / (trace.length - 1) : 0;

        const points = trace.map((item, index) => {
            const x = left + step * index;
            const y = top + (1 - (Number(item.g_high) - minValue) / valueSpan) * plotHeight;
            return { x, y, label: item.time, value: item.g_high };
        });

        const path = points
            .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
            .join(" ");

        const firstLabel = points[0]?.label ?? "";
        const lastLabel = points[points.length - 1]?.label ?? "";

        svg.innerHTML = `
            <line x1="${left}" y1="${top + plotHeight}" x2="${width - right}" y2="${top + plotHeight}" class="grid-line" />
            <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="grid-line" />
            <path d="${path}" class="thermal-path" />
            ${points
                .map(
                    (point) =>
                        `<circle cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="4.5" class="thermal-point" />`,
                )
                .join("")}
            <text x="${left}" y="18" class="axis-label">最小值 ${formatNumber(minValue, 2)} / 最大值 ${formatNumber(maxValue, 2)}</text>
            <text x="${left}" y="292" class="axis-label">${firstLabel}</text>
            <text x="${width - right}" y="292" text-anchor="end" class="axis-label">${lastLabel}</text>
        `;
    }

    function renderAlignment() {
        const alignment = state.alignment || {};
        const statsNode = byId("alignment-stats");
        const svg = byId("alignment-chart");
        const edgeLabel = alignment.edge_label || state.edge?.value_label || "Edge 值";

        const stats = alignment.available
            ? [
                { label: "對齊點數", value: formatInteger(alignment.sample_count) },
                { label: "熱像取樣數", value: formatInteger(alignment.thermal_sample_count) },
                { label: "Edge 取樣數", value: formatInteger(alignment.edge_sample_count) },
                { label: "Edge 欄位", value: edgeLabel },
            ]
            : [
                { label: "對齊狀態", value: alignment.message || "尚未完成對齊" },
                { label: "熱像來源", value: state.thermal?.source_file || "-" },
                { label: "Edge 來源", value: state.edge?.source_file || "-" },
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

        const trace = alignment.trace || [];
        if (!alignment.available || !trace.length) {
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">${alignment.message || "尚未完成資料對齊"}</text>`;
            return;
        }

        const width = 900;
        const height = 320;
        const left = 60;
        const right = 60;
        const top = 24;
        const bottom = 50;
        const plotWidth = width - left - right;
        const plotHeight = height - top - bottom;
        const step = trace.length > 1 ? plotWidth / (trace.length - 1) : 0;

        const thermalValues = trace.map((item) => Number(item.thermal_g_high));
        const edgeValues = trace.map((item) => Number(item.edge_value));
        const thermalMin = Math.min(...thermalValues);
        const thermalMax = Math.max(...thermalValues);
        const edgeMin = Math.min(...edgeValues);
        const edgeMax = Math.max(...edgeValues);
        const thermalSpan = Math.max(thermalMax - thermalMin, 1);
        const edgeSpan = Math.max(edgeMax - edgeMin, 1);

        const thermalPoints = trace.map((item, index) => {
            const x = left + step * index;
            const y = top + (1 - (Number(item.thermal_g_high) - thermalMin) / thermalSpan) * plotHeight;
            return { x, y, label: item.time };
        });
        const edgePoints = trace.map((item, index) => {
            const x = left + step * index;
            const y = top + (1 - (Number(item.edge_value) - edgeMin) / edgeSpan) * plotHeight;
            return { x, y, label: item.time };
        });

        const thermalPath = thermalPoints
            .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
            .join(" ");
        const edgePath = edgePoints
            .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
            .join(" ");

        const firstLabel = trace[0]?.time ?? "";
        const lastLabel = trace[trace.length - 1]?.time ?? "";

        svg.innerHTML = `
            <line x1="${left}" y1="${top + plotHeight}" x2="${width - right}" y2="${top + plotHeight}" class="grid-line" />
            <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="grid-line" />
            <line x1="${width - right}" y1="${top}" x2="${width - right}" y2="${top + plotHeight}" class="grid-line" />
            <path d="${thermalPath}" class="thermal-path" />
            <path d="${edgePath}" class="edge-path" />
            ${thermalPoints
                .map(
                    (point) =>
                        `<circle cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="3.8" class="thermal-point" />`,
                )
                .join("")}
            ${edgePoints
                .map(
                    (point) =>
                        `<circle cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="3.4" class="edge-point" />`,
                )
                .join("")}
            <text x="${left}" y="18" class="axis-label">熱像 ${formatNumber(thermalMin, 2)} 至 ${formatNumber(thermalMax, 2)}</text>
            <text x="${width - right}" y="18" text-anchor="end" class="axis-label">${edgeLabel} ${formatNumber(edgeMin, 2)} 至 ${formatNumber(edgeMax, 2)}</text>
            <text x="${left}" y="292" class="axis-label">${firstLabel}</text>
            <text x="${width - right}" y="292" text-anchor="end" class="axis-label">${lastLabel}</text>
        `;
    }

    function syncAlignmentControls(alignment, enabled) {
        const range = byId("alignment-offset-range");
        const numberInput = byId("alignment-offset-number");
        const autoButton = byId("alignment-auto-button");
        const offsetLabel = byId("alignment-offset-label");
        const methodLabel = byId("alignment-method-label");
        const offsetRange = Math.max(Number(alignment?.manual_offset_range_ms || 5000), 0);
        const autoOffsetMs = Number(alignment?.auto_offset_ms || 0);

        alignmentManualOffsetMs = clamp(alignmentManualOffsetMs, -offsetRange, offsetRange);

        if (range) {
            range.min = String(-offsetRange);
            range.max = String(offsetRange);
            range.step = "10";
            range.value = String(alignmentManualOffsetMs);
            range.disabled = !enabled;
        }
        if (numberInput) {
            numberInput.min = String(-offsetRange);
            numberInput.max = String(offsetRange);
            numberInput.step = "10";
            numberInput.value = String(alignmentManualOffsetMs);
            numberInput.disabled = !enabled;
        }
        if (autoButton) {
            autoButton.disabled = !enabled;
        }
        if (offsetLabel) {
            offsetLabel.textContent = `套用 ${formatSignedMilliseconds(autoOffsetMs + alignmentManualOffsetMs)}`;
        }
        if (methodLabel) {
            const pieces = [];
            if (alignment?.method_label) {
                pieces.push(alignment.method_label);
            }
            if (enabled) {
                pieces.push(`自動 ${formatSignedMilliseconds(autoOffsetMs)}`);
                pieces.push(`手動 ${formatSignedMilliseconds(alignmentManualOffsetMs)}`);
            }
            methodLabel.textContent = pieces.join(" / ") || "尚未建立對齊";
        }
    }

    function bindAlignmentControls() {
        const range = byId("alignment-offset-range");
        const numberInput = byId("alignment-offset-number");
        const autoButton = byId("alignment-auto-button");

        if (range && !range.dataset.bound) {
            range.addEventListener("input", (event) => {
                alignmentManualOffsetMs = Number(event.target.value) || 0;
                renderAlignment();
            });
            range.dataset.bound = "true";
        }

        if (numberInput && !numberInput.dataset.bound) {
            numberInput.addEventListener("input", (event) => {
                alignmentManualOffsetMs = Number(event.target.value) || 0;
                renderAlignment();
            });
            numberInput.dataset.bound = "true";
        }

        if (autoButton && !autoButton.dataset.bound) {
            autoButton.addEventListener("click", () => {
                alignmentManualOffsetMs = Number(state.alignment?.manual_offset_default_ms || 0);
                renderAlignment();
            });
            autoButton.dataset.bound = "true";
        }
    }

    function renderAlignment() {
        const alignment = state.alignment || {};
        const statsNode = byId("alignment-stats");
        const svg = byId("alignment-chart");
        const edgeLabel = alignment.edge_label || state.edge?.value_label || "Edge";
        const thermalTrace = Array.isArray(state.thermal?.thermal_trace) ? state.thermal.thermal_trace : [];
        const edgeTrace = Array.isArray(state.edge?.edge_trace) ? state.edge.edge_trace : [];
        const autoOffsetMs = Number(alignment.auto_offset_ms || 0);
        const appliedOffsetMs = autoOffsetMs + alignmentManualOffsetMs;
        const thermalFeature = alignment.thermal_feature || null;
        const machineFeature = alignment.machine_feature || null;

        const stats = alignment.available
            ? [
                { label: "對齊方式", value: alignment.method_label || "-" },
                { label: "自動 Offset", value: formatSignedMilliseconds(autoOffsetMs) },
                { label: "手動微調", value: formatSignedMilliseconds(alignmentManualOffsetMs) },
                { label: "套用 Offset", value: formatSignedMilliseconds(appliedOffsetMs) },
                { label: "熱像特徵", value: thermalFeature?.time || "-" },
                { label: "Edge 特徵", value: machineFeature?.time || "-" },
            ]
            : [
                { label: "對齊狀態", value: alignment.message || "尚未建立對齊" },
                { label: "熱像檔案", value: state.thermal?.source_file || "-" },
                { label: "Edge 檔案", value: state.edge?.source_file || "-" },
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
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">${alignment.message || "尚未建立資料對齊"}</text>`;
            return;
        }

        const rawThermalSeries = thermalTrace
            .map((item) => ({
                timestampMs: Number(item.timestamp_ms),
                value: Number(item.g_high),
            }))
            .filter((item) => Number.isFinite(item.timestampMs) && Number.isFinite(item.value));
        const alignedThermalSeries = thermalTrace
            .map((item) => ({
                timestampMs: Number(item.timestamp_ms) + appliedOffsetMs,
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
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">對齊圖缺少可繪製的時間序列</text>`;
            return;
        }

        const allTimestamps = alignedThermalSeries
            .concat(edgeSeries)
            .map((item) => item.timestampMs);
        const width = 900;
        const height = 320;
        const left = 70;
        const right = 70;
        const top = 28;
        const bottom = 54;
        const plotWidth = width - left - right;
        const plotHeight = height - top - bottom;
        const minTimestamp = Math.min(...allTimestamps);
        const maxTimestamp = Math.max(...allTimestamps);
        const timeSpan = Math.max(maxTimestamp - minTimestamp, 1);

        const thermalValues = rawThermalSeries.concat(alignedThermalSeries).map((item) => item.value);
        const edgeValues = edgeSeries.map((item) => item.value);
        const thermalMin = Math.min(...thermalValues);
        const thermalMax = Math.max(...thermalValues);
        const edgeMin = Math.min(...edgeValues);
        const edgeMax = Math.max(...edgeValues);
        const thermalSpan = Math.max(thermalMax - thermalMin, 1);
        const edgeSpan = Math.max(edgeMax - edgeMin, 1);

        const scaleX = (timestampMs) => left + ((timestampMs - minTimestamp) / timeSpan) * plotWidth;
        const scaleThermalY = (value) => top + (1 - (value - thermalMin) / thermalSpan) * plotHeight;
        const scaleEdgeY = (value) => top + (1 - (value - edgeMin) / edgeSpan) * plotHeight;
        const buildPath = (points, yScale) =>
            points
                .map((point, index) => {
                    const x = scaleX(point.timestampMs).toFixed(2);
                    const y = yScale(point.value).toFixed(2);
                    return `${index === 0 ? "M" : "L"} ${x} ${y}`;
                })
                .join(" ");

        const rawThermalPath = buildPath(rawThermalSeries, scaleThermalY);
        const alignedThermalPath = buildPath(alignedThermalSeries, scaleThermalY);
        const edgePath = buildPath(edgeSeries, scaleEdgeY);

        const markerLines = [];
        const markerLabels = [];
        const addMarker = (timestampMs, label, cssClass, anchor = "start", y = top + 16) => {
            if (!Number.isFinite(timestampMs) || timestampMs < minTimestamp || timestampMs > maxTimestamp) {
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
        addMarker(
            Number(thermalFeature?.timestamp_ms) + appliedOffsetMs,
            "熱像對齊後",
            "feature-line thermal-feature-line",
            "start",
            top + 32,
        );
        addMarker(Number(machineFeature?.timestamp_ms), "LASER ON", "feature-line machine-feature-line", "end", top + 16);

        svg.innerHTML = `
            <line x1="${left}" y1="${top + plotHeight}" x2="${width - right}" y2="${top + plotHeight}" class="grid-line" />
            <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="grid-line" />
            <line x1="${width - right}" y1="${top}" x2="${width - right}" y2="${top + plotHeight}" class="grid-line" />
            ${markerLines.join("")}
            <path d="${rawThermalPath}" class="thermal-path-raw" />
            <path d="${alignedThermalPath}" class="thermal-path" />
            <path d="${edgePath}" class="edge-path" />
            ${markerLabels.join("")}
            <text x="${left}" y="18" class="axis-label">熱像 ${formatNumber(thermalMin, 2)} ~ ${formatNumber(thermalMax, 2)}</text>
            <text x="${width - right}" y="18" text-anchor="end" class="axis-label">${edgeLabel} ${formatNumber(edgeMin, 2)} ~ ${formatNumber(edgeMax, 2)}</text>
            <text x="${left}" y="${height - 18}" class="axis-label">${formatChartTime(minTimestamp)}</text>
            <text x="${width - right}" y="${height - 18}" text-anchor="end" class="axis-label">${formatChartTime(maxTimestamp)}</text>
        `;
    }

    function resetChartView(viewState) {
        viewState.startRatio = 0;
        viewState.endRatio = 1;
        viewState.pointerId = null;
        viewState.dragStartX = 0;
        viewState.dragStartStart = 0;
        viewState.dragStartEnd = 1;
        viewState.dragMoved = false;
    }

    function clampChartView(viewState, minSpan = 0.02) {
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

    function zoomChartView(viewState, factor, anchorRatio = 0.5) {
        const currentSpan = Math.max(viewState.endRatio - viewState.startRatio, 0.0001);
        const nextSpan = clamp(currentSpan / factor, 0.02, 1);
        const clampedAnchor = clamp(anchorRatio, 0, 1);
        const anchorValue = viewState.startRatio + currentSpan * clampedAnchor;

        viewState.startRatio = anchorValue - nextSpan * clampedAnchor;
        viewState.endRatio = anchorValue + nextSpan * (1 - clampedAnchor);
        clampChartView(viewState);
    }

    function buildTimeTicks(startTimestampMs, endTimestampMs, preferredCount = 6, sourcePoints = []) {
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

    function sliceVisiblePoints(points, startTimestampMs, endTimestampMs) {
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

    function buildPolylinePath(points, scaleX, scaleY) {
        return points
            .map((point, index) => {
                const x = scaleX(point.timestampMs).toFixed(2);
                const y = scaleY(point.value).toFixed(2);
                return `${index === 0 ? "M" : "L"} ${x} ${y}`;
            })
            .join(" ");
    }

    function buildPointKey(seriesKey, timestampMs, suffix = "") {
        return suffix
            ? `${seriesKey}|${Math.round(timestampMs)}|${suffix}`
            : `${seriesKey}|${Math.round(timestampMs)}`;
    }

    function renderPointDetail(containerId, selectedPoint, emptyMessage) {
        const container = byId(containerId);
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
                <strong>${selectedPoint.title || "點位資訊"}</strong>
                <span>${selectedPoint.seriesLabel || "-"}</span>
            </div>
            <div class="chart-detail-grid">
                ${rows
                    .map(
                        (row) => `
                            <article class="chart-detail-card">
                                <span>${row.label}</span>
                                <strong>${row.value}</strong>
                            </article>
                        `,
                    )
                    .join("")}
            </div>
        `;
    }

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

    function bindInteractiveChart({ svgId, resetButtonId, viewState, onRender, onSelectPoint, onClearSelection }) {
        const svg = byId(svgId);
        const resetButton = byId(resetButtonId);
        if (!svg) {
            return;
        }

        if (!svg.dataset.interactiveBound) {
            svg.addEventListener(
                "wheel",
                (event) => {
                    const metrics = getSvgPlotMetrics(svg);
                    const rect = svg.getBoundingClientRect();
                    const plotLeftPx = rect.width * (metrics.plotLeft / metrics.viewWidth);
                    const plotWidthPx = rect.width * (metrics.plotWidth / metrics.viewWidth);
                    if (plotWidthPx <= 0) {
                        return;
                    }

                    event.preventDefault();
                    const pointerRatio = clamp((event.clientX - rect.left - plotLeftPx) / plotWidthPx, 0, 1);
                    const zoomFactor = event.deltaY < 0 ? 1.18 : 0.84;
                    zoomChartView(viewState, zoomFactor, pointerRatio);
                    onRender();
                },
                { passive: false },
            );

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

    function bindChartInteractions() {
        bindInteractiveChart({
            svgId: "thermal-chart",
            resetButtonId: "thermal-reset-view",
            viewState: thermalChartView,
            onRender: renderThermal,
            onSelectPoint: (point) => {
                selectedThermalPoint = point;
            },
            onClearSelection: () => {
                selectedThermalPoint = null;
            },
        });
        bindInteractiveChart({
            svgId: "alignment-chart",
            resetButtonId: "alignment-reset-view",
            viewState: alignmentChartView,
            onRender: renderAlignment,
            onSelectPoint: (point) => {
                selectedAlignmentPoint = point;
            },
            onClearSelection: () => {
                selectedAlignmentPoint = null;
            },
        });
    }

    function renderThermal() {
        const thermal = state.thermal || {};
        const stats = [
            { label: "取樣點數", value: formatInteger(thermal.sample_count) },
            { label: "G_High 最小值", value: formatNumber(thermal.g_high_min, 2) },
            { label: "G_High 平均值", value: formatNumber(thermal.g_high_avg, 2) },
            { label: "G_High 最大值", value: formatNumber(thermal.g_high_max, 2) },
        ];

        byId("thermal-stats").replaceChildren(
            ...stats.map((metric) => {
                const article = document.createElement("article");
                article.className = "metric-card";
                article.innerHTML = `<span>${metric.label}</span><strong>${metric.value}</strong>`;
                return article;
            }),
        );

        const svg = byId("thermal-chart");
        const trace = Array.isArray(thermal.thermal_trace) ? thermal.thermal_trace : [];
        const points = trace
            .map((item) => ({
                timestampMs: Number(item.timestamp_ms),
                value: Number(item.g_high),
            }))
            .filter((item) => Number.isFinite(item.timestampMs) && Number.isFinite(item.value));

        if (!points.length) {
            const message = thermal.source_kind === "missing" ? "尚未提供熱像儀資料。" : "熱像儀資料沒有可顯示的點位。";
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">${message}</text>`;
            setText("thermal-window-label", "尚未建立時間視窗");
            renderPointDetail("thermal-point-detail", null, "點一下圖上的熱像點位，就能看到完整時間戳與數值。");
            return;
        }

        clampChartView(thermalChartView);

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
        const visibleStart = minTimestamp + totalSpan * thermalChartView.startRatio;
        const visibleEnd = minTimestamp + totalSpan * thermalChartView.endRatio;
        const visiblePoints = sliceVisiblePoints(points, visibleStart, visibleEnd);
        const visibleValues = visiblePoints.map((point) => point.value);
        const minValue = Math.min(...visibleValues);
        const maxValue = Math.max(...visibleValues);
        const valueSpan = Math.max(maxValue - minValue, 1);
        const scaleX = (timestampMs) => left + ((timestampMs - visibleStart) / Math.max(visibleEnd - visibleStart, 1)) * plotWidth;
        const scaleY = (value) => top + (1 - (value - minValue) / valueSpan) * plotHeight;
        const tickTimestamps = buildTimeTicks(visibleStart, visibleEnd, 6, visiblePoints.length <= 8 ? visiblePoints : []);
        const path = buildPolylinePath(visiblePoints, scaleX, scaleY);

        const interactivePoints = [];
        const circleMarkup = visiblePoints
            .map((point) => {
                const pointId = interactivePoints.length;
                const key = buildPointKey("thermal", point.timestampMs);
                interactivePoints.push({
                    key,
                    title: "熱像儀點位",
                    seriesLabel: "熱像 G_High",
                    rows: [
                        { label: "時間戳", value: formatFullTimestamp(point.timestampMs) },
                        { label: "毫秒時間", value: `${Math.round(point.timestampMs)} ms` },
                        { label: "G_High", value: formatNumber(point.value, 2) },
                        { label: "來源檔案", value: thermal.source_file || "-" },
                    ],
                });
                const isSelected = selectedThermalPoint?.key === key;
                return `
                    <circle
                        cx="${scaleX(point.timestampMs).toFixed(2)}"
                        cy="${scaleY(point.value).toFixed(2)}"
                        r="${isSelected ? "5.6" : "4.4"}"
                        class="thermal-point chart-point${isSelected ? " chart-point-selected" : ""}"
                        data-point-id="${pointId}"
                    />
                `;
            })
            .join("");

        const tickMarkup = tickTimestamps
            .map((timestampMs, index) => {
                const x = scaleX(timestampMs);
                const anchor = index === 0 ? "start" : (index === tickTimestamps.length - 1 ? "end" : "middle");
                return `
                    <line x1="${x.toFixed(2)}" y1="${top}" x2="${x.toFixed(2)}" y2="${(top + plotHeight).toFixed(2)}" class="grid-line" />
                    <text x="${x.toFixed(2)}" y="${height - 18}" text-anchor="${anchor}" class="chart-axis-tick">${formatChartTime(timestampMs)}</text>
                `;
            })
            .join("");

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
            <text x="${left}" y="18" class="axis-label">G_High ${formatNumber(minValue, 2)} ~ ${formatNumber(maxValue, 2)}</text>
            <text x="${width - right}" y="18" text-anchor="end" class="axis-label">顯示 ${visiblePoints.length} 個時間點</text>
        `;

        setText("thermal-window-label", `${formatFullTimestamp(visibleStart)} -> ${formatFullTimestamp(visibleEnd)}`);
        renderPointDetail("thermal-point-detail", selectedThermalPoint, "點一下圖上的熱像點位，就能看到完整時間戳與數值。");
    }

    function syncAlignmentControls(alignment, enabled) {
        const range = byId("alignment-offset-range");
        const numberInput = byId("alignment-offset-number");
        const autoButton = byId("alignment-auto-button");
        const offsetLabel = byId("alignment-offset-label");
        const methodLabel = byId("alignment-method-label");
        const offsetRange = Math.max(Number(alignment?.manual_offset_range_ms || 5000), 0);
        const autoOffsetMs = Number(alignment?.auto_offset_ms || 0);

        alignmentManualOffsetMs = clamp(alignmentManualOffsetMs, -offsetRange, offsetRange);

        if (range) {
            range.min = String(-offsetRange);
            range.max = String(offsetRange);
            range.step = "10";
            range.value = String(alignmentManualOffsetMs);
            range.disabled = !enabled;
        }
        if (numberInput) {
            numberInput.min = String(-offsetRange);
            numberInput.max = String(offsetRange);
            numberInput.step = "10";
            numberInput.value = String(alignmentManualOffsetMs);
            numberInput.disabled = !enabled;
        }
        if (autoButton) {
            autoButton.disabled = !enabled;
        }
        if (offsetLabel) {
            offsetLabel.textContent = `套用 ${formatSignedMilliseconds(autoOffsetMs + alignmentManualOffsetMs)}`;
        }
        if (methodLabel) {
            const pieces = [];
            if (alignment?.method_label) {
                pieces.push(alignment.method_label);
            }
            if (enabled) {
                pieces.push(`自動 ${formatSignedMilliseconds(autoOffsetMs)}`);
                pieces.push(`手動 ${formatSignedMilliseconds(alignmentManualOffsetMs)}`);
            }
            methodLabel.textContent = pieces.join(" / ") || "尚未建立對齊";
        }
    }

    function bindAlignmentControls() {
        const range = byId("alignment-offset-range");
        const numberInput = byId("alignment-offset-number");
        const autoButton = byId("alignment-auto-button");

        if (range && !range.dataset.bound) {
            range.addEventListener("input", (event) => {
                alignmentManualOffsetMs = Number(event.target.value) || 0;
                selectedAlignmentPoint = null;
                renderAlignment();
            });
            range.dataset.bound = "true";
        }

        if (numberInput && !numberInput.dataset.bound) {
            numberInput.addEventListener("input", (event) => {
                alignmentManualOffsetMs = Number(event.target.value) || 0;
                selectedAlignmentPoint = null;
                renderAlignment();
            });
            numberInput.dataset.bound = "true";
        }

        if (autoButton && !autoButton.dataset.bound) {
            autoButton.addEventListener("click", () => {
                alignmentManualOffsetMs = Number(state.alignment?.manual_offset_default_ms || 0);
                selectedAlignmentPoint = null;
                renderAlignment();
            });
            autoButton.dataset.bound = "true";
        }
    }

    function renderAlignment() {
        const alignment = state.alignment || {};
        const statsNode = byId("alignment-stats");
        const svg = byId("alignment-chart");
        const edgeLabel = alignment.edge_label || state.edge?.value_label || "Edge";
        const thermalTrace = Array.isArray(state.thermal?.thermal_trace) ? state.thermal.thermal_trace : [];
        const edgeTrace = Array.isArray(state.edge?.edge_trace) ? state.edge.edge_trace : [];
        const autoOffsetMs = Number(alignment.auto_offset_ms || 0);
        const appliedOffsetMs = autoOffsetMs + alignmentManualOffsetMs;
        const thermalFeature = alignment.thermal_feature || null;
        const machineFeature = alignment.machine_feature || null;

        const stats = alignment.available
            ? [
                { label: "對齊方式", value: alignment.method_label || "-" },
                { label: "自動 Offset", value: formatSignedMilliseconds(autoOffsetMs) },
                { label: "手動微調", value: formatSignedMilliseconds(alignmentManualOffsetMs) },
                { label: "套用 Offset", value: formatSignedMilliseconds(appliedOffsetMs) },
                { label: "熱像特徵", value: thermalFeature?.time || "-" },
                { label: "Edge 特徵", value: machineFeature?.time || "-" },
            ]
            : [
                { label: "對齊狀態", value: alignment.message || "尚未建立對齊" },
                { label: "熱像檔案", value: state.thermal?.source_file || "-" },
                { label: "Edge 檔案", value: state.edge?.source_file || "-" },
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
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">${alignment.message || "尚未建立資料對齊"}</text>`;
            setText("alignment-window-label", "尚未建立時間視窗");
            renderPointDetail("alignment-point-detail", null, "點一下熱像或 Edge 點位，就能看到時間戳、數值與對齊資訊。");
            return;
        }

        clampChartView(alignmentChartView);

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
            svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">對齊圖缺少可繪製的時間序列</text>`;
            setText("alignment-window-label", "尚未建立時間視窗");
            renderPointDetail("alignment-point-detail", null, "點一下熱像或 Edge 點位，就能看到時間戳、數值與對齊資訊。");
            return;
        }

        const allTimestamps = rawThermalSeries
            .concat(alignedThermalSeries, edgeSeries)
            .map((item) => item.timestampMs);
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
        const visibleStart = minTimestamp + totalSpan * alignmentChartView.startRatio;
        const visibleEnd = minTimestamp + totalSpan * alignmentChartView.endRatio;
        const visibleRawThermal = rawThermalSeries.filter(
            (point) => point.timestampMs >= visibleStart && point.timestampMs <= visibleEnd,
        );
        const visibleAlignedThermal = sliceVisiblePoints(alignedThermalSeries, visibleStart, visibleEnd);
        const visibleEdge = sliceVisiblePoints(edgeSeries, visibleStart, visibleEnd);
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
        const visibleTickSource = Array.from(
            new Map(
                visibleAlignedThermal
                    .concat(visibleEdge)
                    .map((point) => [Math.round(point.timestampMs), point]),
            ).values(),
        );
        const tickTimestamps = buildTimeTicks(
            visibleStart,
            visibleEnd,
            6,
            visibleTickSource.length <= 8 ? visibleTickSource : [],
        );
        const rawThermalPath = buildPolylinePath(visibleRawThermal, scaleX, scaleThermalY);
        const alignedThermalPath = buildPolylinePath(visibleAlignedThermal, scaleX, scaleThermalY);
        const edgePath = buildPolylinePath(visibleEdge, scaleX, scaleEdgeY);

        const interactivePoints = [];
        const rawThermalCircles = visibleRawThermal
            .map((point) => {
                const pointId = interactivePoints.length;
                const key = buildPointKey("thermal-raw", point.timestampMs);
                interactivePoints.push({
                    key,
                    title: "熱像原始時間點",
                    seriesLabel: "熱像原始時間",
                    rows: [
                        { label: "顯示時間戳", value: formatFullTimestamp(point.timestampMs) },
                        { label: "原始時間戳", value: formatFullTimestamp(point.originalTimestampMs) },
                        { label: "G_High", value: formatNumber(point.value, 2) },
                        { label: "套用 Offset", value: "0 ms" },
                    ],
                });
                const isSelected = selectedAlignmentPoint?.key === key;
                return `
                    <circle
                        cx="${scaleX(point.timestampMs).toFixed(2)}"
                        cy="${scaleThermalY(point.value).toFixed(2)}"
                        r="${isSelected ? "4.8" : "3.3"}"
                        class="thermal-point-raw chart-point${isSelected ? " chart-point-selected" : ""}"
                        data-point-id="${pointId}"
                    />
                `;
            })
            .join("");

        const alignedThermalCircles = visibleAlignedThermal
            .map((point) => {
                const pointId = interactivePoints.length;
                const key = buildPointKey("thermal-aligned", point.timestampMs, point.originalTimestampMs);
                interactivePoints.push({
                    key,
                    title: "熱像對齊後點位",
                    seriesLabel: "熱像對齊後",
                    rows: [
                        { label: "顯示時間戳", value: formatFullTimestamp(point.timestampMs) },
                        { label: "原始時間戳", value: formatFullTimestamp(point.originalTimestampMs) },
                        { label: "G_High", value: formatNumber(point.value, 2) },
                        { label: "套用 Offset", value: formatSignedMilliseconds(appliedOffsetMs) },
                    ],
                });
                const isSelected = selectedAlignmentPoint?.key === key;
                return `
                    <circle
                        cx="${scaleX(point.timestampMs).toFixed(2)}"
                        cy="${scaleThermalY(point.value).toFixed(2)}"
                        r="${isSelected ? "5.2" : "3.8"}"
                        class="thermal-point chart-point${isSelected ? " chart-point-selected" : ""}"
                        data-point-id="${pointId}"
                    />
                `;
            })
            .join("");

        const edgeCircles = visibleEdge
            .map((point) => {
                const pointId = interactivePoints.length;
                const key = buildPointKey("edge", point.timestampMs);
                interactivePoints.push({
                    key,
                    title: "Edge 點位",
                    seriesLabel: edgeLabel,
                    rows: [
                        { label: "時間戳", value: formatFullTimestamp(point.timestampMs) },
                        { label: edgeLabel, value: formatNumber(point.value, 4) },
                        { label: "資料型別", value: state.edge?.edge_format || "-" },
                        { label: "來源檔案", value: state.edge?.source_file || "-" },
                    ],
                });
                const isSelected = selectedAlignmentPoint?.key === key;
                return `
                    <circle
                        cx="${scaleX(point.timestampMs).toFixed(2)}"
                        cy="${scaleEdgeY(point.value).toFixed(2)}"
                        r="${isSelected ? "4.8" : "3.4"}"
                        class="edge-point chart-point${isSelected ? " chart-point-selected" : ""}"
                        data-point-id="${pointId}"
                    />
                `;
            })
            .join("");

        const tickMarkup = tickTimestamps
            .map((timestampMs, index) => {
                const x = scaleX(timestampMs);
                const anchor = index === 0 ? "start" : (index === tickTimestamps.length - 1 ? "end" : "middle");
                return `
                    <line x1="${x.toFixed(2)}" y1="${top}" x2="${x.toFixed(2)}" y2="${(top + plotHeight).toFixed(2)}" class="grid-line" />
                    <text x="${x.toFixed(2)}" y="${height - 18}" text-anchor="${anchor}" class="chart-axis-tick">${formatChartTime(timestampMs)}</text>
                `;
            })
            .join("");

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
        addMarker(
            Number(thermalFeature?.timestamp_ms) + appliedOffsetMs,
            "熱像對齊後",
            "feature-line thermal-feature-line",
            "start",
            top + 32,
        );
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
            <text x="${left}" y="18" class="axis-label">熱像 ${formatNumber(thermalMin, 2)} ~ ${formatNumber(thermalMax, 2)}</text>
            <text x="${width - right}" y="18" text-anchor="end" class="axis-label">${edgeLabel} ${formatNumber(edgeMin, 2)} ~ ${formatNumber(edgeMax, 2)}</text>
        `;

        setText("alignment-window-label", `${formatFullTimestamp(visibleStart)} -> ${formatFullTimestamp(visibleEnd)}`);
        renderPointDetail("alignment-point-detail", selectedAlignmentPoint, "點一下熱像或 Edge 點位，就能看到時間戳、數值與對齊資訊。");
    }

    function coordinatePlaybackKey(payload, trajectoryId) {
        return [
            state.selected_output_name ?? "",
            trajectoryId ?? "",
            payload?.trajectory_count ?? "",
            payload?.work_trace?.length ?? "",
        ].join("|");
    }

    function cancelCoordinatePlaybackLoop() {
        if (coordinatePlayback.rafId) {
            window.cancelAnimationFrame(coordinatePlayback.rafId);
            coordinatePlayback.rafId = 0;
        }
    }

    function pauseCoordinatePlayback() {
        coordinatePlayback.isPlaying = false;
        coordinatePlayback.lastFrameMs = 0;
        cancelCoordinatePlaybackLoop();
    }

    function ensureSelectedCoordinateTrajectory(payload) {
        const ids = (Array.isArray(payload?.trajectory_summaries) ? payload.trajectory_summaries : [])
            .map((item) => String(item.trajectory_id ?? ""))
            .filter(Boolean);
        if (!ids.length) {
            const fallback = Array.from(
                new Set(
                    (Array.isArray(payload?.work_trace) ? payload.work_trace : [])
                        .map((point) => String(point.trajectory_id ?? ""))
                        .filter(Boolean),
                ),
            );
            if (!fallback.length) {
                selectedCoordinateTrajectoryId = "";
                return "";
            }
            if (!fallback.includes(selectedCoordinateTrajectoryId)) {
                selectedCoordinateTrajectoryId = fallback[0];
            }
            return selectedCoordinateTrajectoryId;
        }

        if (!ids.includes(selectedCoordinateTrajectoryId)) {
            selectedCoordinateTrajectoryId = ids[0];
        }
        return selectedCoordinateTrajectoryId;
    }

    function coordinateHeatColor(value, min, max) {
        const numericValue = Number(value);
        if (!Number.isFinite(numericValue) || !Number.isFinite(Number(min)) || !Number.isFinite(Number(max))) {
            return "hsl(210 68% 44%)";
        }
        const span = Math.max(Number(max) - Number(min), 0.0001);
        const ratio = clamp((numericValue - Number(min)) / span, 0, 1);
        const hue = 220 - ratio * 190;
        const saturation = 72 + ratio * 10;
        const lightness = 42 + ratio * 10;
        return `hsl(${hue.toFixed(1)} ${saturation.toFixed(1)}% ${lightness.toFixed(1)}%)`;
    }

    function interpolateCoordinatePoint(start, end, ratio) {
        const lerp = (a, b) => Number(a) + (Number(b) - Number(a)) * ratio;
        const startTime = Number(start.timestamp_ms ?? start.sample_ms ?? 0);
        const endTime = Number(end.timestamp_ms ?? end.sample_ms ?? startTime);
        const startHeat = Number(start.g_high);
        const endHeat = Number(end.g_high);

        return {
            work_x_mm: lerp(start.work_x_mm, end.work_x_mm),
            work_y_mm: lerp(start.work_y_mm, end.work_y_mm),
            work_z_mm: lerp(
                start.work_z_mm ?? start.machine_z_mm ?? 0,
                end.work_z_mm ?? end.machine_z_mm ?? start.work_z_mm ?? start.machine_z_mm ?? 0,
            ),
            timestamp_ms: lerp(startTime, endTime),
            g_high: Number.isFinite(startHeat) && Number.isFinite(endHeat)
                ? lerp(startHeat, endHeat)
                : (Number.isFinite(endHeat) ? endHeat : startHeat),
            trajectory_id: end.trajectory_id ?? start.trajectory_id,
        };
    }

    function buildCoordinateGeometry(payload, trajectoryId) {
        const filteredPoints = (Array.isArray(payload?.work_trace) ? payload.work_trace : [])
            .filter((point) => {
                if (!Number.isFinite(Number(point.work_x_mm)) || !Number.isFinite(Number(point.work_y_mm))) {
                    return false;
                }
                return !trajectoryId || String(point.trajectory_id ?? "") === String(trajectoryId);
            })
            .slice()
            .sort((left, right) => Number(left.timestamp_ms ?? 0) - Number(right.timestamp_ms ?? 0));

        if (filteredPoints.length < 2) {
            return null;
        }

        const xValues = filteredPoints.map((point) => Number(point.work_x_mm));
        const yValues = filteredPoints.map((point) => Number(point.work_y_mm));
        const heatValues = filteredPoints
            .map((point) => Number(point.g_high))
            .filter((value) => Number.isFinite(value));
        const xMin = Math.min(...xValues);
        const xMax = Math.max(...xValues);
        const yMin = Math.min(...yValues);
        const yMax = Math.max(...yValues);
        const width = 900;
        const height = 420;
        const padding = { left: 70, right: 40, top: 30, bottom: 50 };
        const plotWidth = width - padding.left - padding.right;
        const plotHeight = height - padding.top - padding.bottom;
        const xSpan = Math.max(xMax - xMin, 1);
        const ySpan = Math.max(yMax - yMin, 1);
        const heatMin = heatValues.length ? Math.min(...heatValues) : 0;
        const heatMax = heatValues.length ? Math.max(...heatValues) : 1;

        const project = (point) => ({
            x: padding.left + ((Number(point.work_x_mm) - xMin) / xSpan) * plotWidth,
            y: padding.top + (1 - (Number(point.work_y_mm) - yMin) / ySpan) * plotHeight,
        });

        const pointEntries = filteredPoints.map((point) => ({
            ...point,
            projected: project(point),
        }));
        const gridLines = [];
        for (let index = 0; index <= 4; index += 1) {
            const y = padding.top + (plotHeight / 4) * index;
            gridLines.push(
                `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" class="grid-line" />`,
            );
        }

        const guideDots = [];
        const segments = [];
        let totalUnits = 0;
        const rawLengths = [];

        for (let index = 1; index < pointEntries.length; index += 1) {
            const startPoint = pointEntries[index - 1];
            const endPoint = pointEntries[index];
            const startProjected = startPoint.projected;
            const endProjected = endPoint.projected;
            const rawLength = Math.hypot(
                Number(endPoint.work_x_mm) - Number(startPoint.work_x_mm),
                Number(endPoint.work_y_mm) - Number(startPoint.work_y_mm),
                Number(endPoint.work_z_mm ?? startPoint.work_z_mm ?? 0) - Number(startPoint.work_z_mm ?? 0),
            );
            rawLengths.push(rawLength);
        }

        const sortedLengths = rawLengths.filter((value) => Number.isFinite(value) && value > 0).sort((left, right) => left - right);
        const medianLength = sortedLengths.length
            ? sortedLengths[Math.floor(sortedLengths.length / 2)]
            : 1;
        const jumpThreshold = Math.max(medianLength * 2.8, 2.5);
        const pointStep = Math.max(1, Math.floor(pointEntries.length / 180));

        pointEntries.forEach((point, index) => {
            if (index % pointStep !== 0 && index !== 0 && index !== pointEntries.length - 1) {
                return;
            }
            guideDots.push(
                `<circle cx="${point.projected.x.toFixed(2)}" cy="${point.projected.y.toFixed(2)}" r="2.1" class="coordinate-guide-dot" />`,
            );
        });

        for (let index = 1; index < pointEntries.length; index += 1) {
            const startPoint = pointEntries[index - 1];
            const endPoint = pointEntries[index];
            const startProjected = startPoint.projected;
            const endProjected = endPoint.projected;
            const rawLength = Math.hypot(
                Number(endPoint.work_x_mm) - Number(startPoint.work_x_mm),
                Number(endPoint.work_y_mm) - Number(startPoint.work_y_mm),
                Number(endPoint.work_z_mm ?? startPoint.work_z_mm ?? 0) - Number(startPoint.work_z_mm ?? 0),
            );
            const length = Math.max(
                Math.hypot(
                    Number(endPoint.work_x_mm) - Number(startPoint.work_x_mm),
                    Number(endPoint.work_y_mm) - Number(startPoint.work_y_mm),
                    Number(endPoint.work_z_mm ?? startPoint.work_z_mm ?? 0) - Number(startPoint.work_z_mm ?? 0),
                ),
                0.12,
            );
            const startHeat = Number(startPoint.g_high);
            const endHeat = Number(endPoint.g_high);
            const heatValue = Number.isFinite(startHeat) && Number.isFinite(endHeat)
                ? (startHeat + endHeat) / 2
                : (Number.isFinite(endHeat) ? endHeat : startHeat);
            segments.push({
                startPoint,
                endPoint,
                startProjected,
                endProjected,
                startUnits: totalUnits,
                endUnits: totalUnits + length,
                heatValue,
                isJump: rawLength > jumpThreshold,
                index,
            });
            totalUnits += length;
        }

        const startProjected = pointEntries[0].projected;
        const endProjected = pointEntries[pointEntries.length - 1].projected;
        const staticMarkup = `
            ${gridLines.join("")}
            ${guideDots.join("")}
            <circle cx="${startProjected.x.toFixed(2)}" cy="${startProjected.y.toFixed(2)}" r="7" class="marker-start" />
            <circle cx="${endProjected.x.toFixed(2)}" cy="${endProjected.y.toFixed(2)}" r="7" class="marker-end" />
            <text x="${padding.left}" y="18" class="axis-label">X ${formatNumber(xMin, 2)} ~ ${formatNumber(xMax, 2)} mm</text>
            <text x="${width - padding.right}" y="18" text-anchor="end" class="axis-label">Y ${formatNumber(yMin, 2)} ~ ${formatNumber(yMax, 2)} mm</text>
        `;

        return {
            width,
            height,
            points: pointEntries,
            segments,
            staticMarkup,
            totalUnits,
            startProjected,
            endProjected,
            trajectoryId: String(trajectoryId ?? ""),
            heatMin,
            heatMax,
            baseUnitsPerSecond: Math.max(totalUnits / 10, 10),
            pointStep,
        };
    }

    function ensureCoordinatePlaybackGeometry(payload) {
        const trajectoryId = ensureSelectedCoordinateTrajectory(payload);
        const nextKey = coordinatePlaybackKey(payload, trajectoryId);
        if (coordinatePlayback.geometryKey !== nextKey) {
            pauseCoordinatePlayback();
            coordinatePlayback.geometryKey = nextKey;
            coordinatePlayback.geometry = buildCoordinateGeometry(payload, trajectoryId);
            coordinatePlayback.totalUnits = coordinatePlayback.geometry?.totalUnits ?? 0;
            coordinatePlayback.progressUnits = 0;
        }
        return coordinatePlayback.geometry;
    }

    function buildCoordinatePlaybackSnapshot(geometry) {
        if (!geometry || !geometry.points.length) {
            return null;
        }

        const totalUnits = coordinatePlayback.totalUnits || geometry.totalUnits || 0;
        const progressUnits = clamp(coordinatePlayback.progressUnits, 0, totalUnits);
        const activeDots = [];
        let headProjected = geometry.startProjected;
        let headPoint = geometry.points[0];
        let headHeat = Number(headPoint.g_high);
        let headPointIndex = 0;

        for (const segment of geometry.segments) {
            if (progressUnits >= segment.endUnits) {
                headProjected = segment.endProjected;
                headPoint = segment.endPoint;
                headPointIndex = segment.index;
                headHeat = Number.isFinite(Number(segment.endPoint.g_high)) ? Number(segment.endPoint.g_high) : segment.heatValue;
                continue;
            }

            if (progressUnits > segment.startUnits) {
                const span = Math.max(segment.endUnits - segment.startUnits, 0.0001);
                const ratio = clamp((progressUnits - segment.startUnits) / span, 0, 1);
                const partialProjected = interpolatePoint(segment.startProjected, segment.endProjected, ratio);
                const partialPoint = interpolateCoordinatePoint(segment.startPoint, segment.endPoint, ratio);
                headProjected = partialProjected;
                headPoint = partialPoint;
                headPointIndex = Math.max(0, segment.index - 1);
                headHeat = Number.isFinite(Number(partialPoint.g_high)) ? Number(partialPoint.g_high) : segment.heatValue;
                break;
            }

            break;
        }

        if (progressUnits >= totalUnits) {
            headProjected = geometry.endProjected;
            headPoint = geometry.points[geometry.points.length - 1];
            headPointIndex = geometry.points.length - 1;
            headHeat = Number(headPoint.g_high);
        }

        const trailWindow = 110;
        const renderStep = Math.max(1, geometry.pointStep);
        const trailStartIndex = Math.max(0, headPointIndex - trailWindow);
        for (let index = trailStartIndex; index <= headPointIndex; index += renderStep) {
            const point = geometry.points[index];
            const ageRatio = headPointIndex <= trailStartIndex
                ? 1
                : (index - trailStartIndex) / Math.max(headPointIndex - trailStartIndex, 1);
            const color = coordinateHeatColor(point.g_high, geometry.heatMin, geometry.heatMax);
            const glowRadius = 8 + ageRatio * 10;
            const coreRadius = 2.2 + ageRatio * 2.4;
            const glowOpacity = 0.08 + ageRatio * 0.16;
            const coreOpacity = 0.22 + ageRatio * 0.55;
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

    function renderCoordinateTrajectoryOptions(payload) {
        const select = byId("coordinate-trajectory-select");
        if (!select) {
            return;
        }

        const summaries = Array.isArray(payload?.trajectory_summaries) ? payload.trajectory_summaries : [];
        const options = summaries.length
            ? summaries.map((item) => ({
                value: String(item.trajectory_id ?? ""),
                label: `Trajectory ${item.trajectory_id} (${formatInteger(item.sample_count)} pts)`,
            }))
            : Array.from(
                new Set(
                    (Array.isArray(payload?.work_trace) ? payload.work_trace : [])
                        .map((point) => String(point.trajectory_id ?? ""))
                        .filter(Boolean),
                ),
            ).map((trajectoryId) => ({
                value: trajectoryId,
                label: `Trajectory ${trajectoryId}`,
            }));

        select.replaceChildren(
            ...options.map((optionData) => {
                const option = document.createElement("option");
                option.value = optionData.value;
                option.textContent = optionData.label;
                option.selected = optionData.value === selectedCoordinateTrajectoryId;
                return option;
            }),
        );
        select.disabled = options.length === 0;
    }

    function renderCoordinateTrajectorySummaries(payload) {
        const listNode = byId("trajectory-list");
        const summaries = Array.isArray(payload?.trajectory_summaries) ? payload.trajectory_summaries.slice(0, 12) : [];
        listNode.replaceChildren(
            ...summaries.map((item) => {
                const trajectoryId = String(item.trajectory_id ?? "");
                const article = document.createElement("article");
                article.className = `list-card list-card-selectable${trajectoryId === selectedCoordinateTrajectoryId ? " list-card-selected" : ""}`;
                article.tabIndex = 0;
                article.innerHTML = `
                    <div class="list-head">
                        <strong>Trajectory ${trajectoryId}</strong>
                        <span class="pill ${trajectoryId === selectedCoordinateTrajectoryId ? "pill-deposit" : "pill-neutral"}">${formatInteger(item.sample_count)} samples</span>
                    </div>
                    <div class="list-body">Machine start X ${formatNumber(item.machine_start?.x_mm, 2)} / Y ${formatNumber(item.machine_start?.y_mm, 2)} / Z ${formatNumber(item.machine_start?.z_mm, 2)}</div>
                    <div class="list-body">Work start X ${formatNumber(item.work_start?.x_mm, 2)} / Y ${formatNumber(item.work_start?.y_mm, 2)} / Z ${formatNumber(item.work_start?.z_mm, 2)}</div>
                `;
                article.addEventListener("click", () => {
                    if (trajectoryId === selectedCoordinateTrajectoryId) {
                        return;
                    }
                    selectedCoordinateTrajectoryId = trajectoryId;
                    coordinatePlayback.geometryKey = "";
                    renderCoordinateAlignment();
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

    function updateCoordinateControls(payload, geometry, snapshot) {
        const playButton = byId("coordinate-play-button");
        const resetButton = byId("coordinate-reset-button");
        const range = byId("coordinate-progress-range");
        const speedSelect = byId("coordinate-speed-select");
        const progressLabel = byId("coordinate-progress-label");
        const statusLabel = byId("coordinate-status");
        const toolbarNote = byId("coordinate-toolbar-note");
        const hasPath = Boolean(geometry && geometry.points.length > 1 && geometry.segments.length);
        const ratio = snapshot?.progressRatio ?? 0;
        const sliderValue = Math.round(ratio * progressSliderMax);

        if (playButton) {
            playButton.disabled = !hasPath;
            playButton.textContent = coordinatePlayback.isPlaying ? "暫停" : "播放";
        }
        if (resetButton) {
            resetButton.disabled = !hasPath;
        }
        if (range) {
            range.disabled = !hasPath;
            range.value = String(sliderValue);
        }
        if (speedSelect) {
            speedSelect.value = String(coordinatePlayback.speedMultiplier);
            speedSelect.disabled = !hasPath;
        }
        if (progressLabel) {
            progressLabel.textContent = `${(ratio * 100).toFixed(1)}%`;
        }
        if (toolbarNote) {
            toolbarNote.textContent = hasPath
                ? `顏色越偏紅代表 G_High 越高，目前顯示 trajectory ${selectedCoordinateTrajectoryId}。`
                : "目前沒有可播放的 Edge 熱路徑。";
        }
        if (statusLabel) {
            if (!payload?.available) {
                statusLabel.textContent = payload?.message || "目前沒有座標轉換資料。";
                return;
            }
            if (!hasPath) {
                statusLabel.textContent = "選一條 trajectory 後播放 Edge 熱路徑。";
                return;
            }
            const point = snapshot?.headPoint || geometry.points[0];
            const finishedText = ratio >= 1 ? " / 已完成" : "";
            statusLabel.textContent =
                `Trajectory ${selectedCoordinateTrajectoryId} / ${formatChartTime(point.timestamp_ms)} / `
                + `G_High ${formatNumber(point.g_high, 2)} / `
                + `X ${formatNumber(point.work_x_mm, 2)} / Y ${formatNumber(point.work_y_mm, 2)}${finishedText}`;
        }
    }

    function updateCoordinateControls(geometry, snapshot) {
        const playButton = byId("coordinate-play-button");
        const resetButton = byId("coordinate-reset-button");
        const range = byId("coordinate-progress-range");
        const speedSelect = byId("coordinate-speed-select");
        const progressLabel = byId("coordinate-progress-label");
        const statusLabel = byId("coordinate-status");
        const toolbarNote = byId("coordinate-toolbar-note");
        const hasPath = Boolean(geometry && geometry.points.length > 1 && geometry.segments.length);
        const ratio = snapshot?.progressRatio ?? 0;
        const sliderValue = Math.round(ratio * progressSliderMax);

        if (playButton) {
            playButton.disabled = !hasPath;
            playButton.textContent = coordinatePlayback.isPlaying ? "暫停" : "播放";
        }
        if (resetButton) {
            resetButton.disabled = !hasPath;
            resetButton.textContent = "重播";
        }
        if (range) {
            range.disabled = !hasPath;
            range.value = String(sliderValue);
        }
        if (speedSelect) {
            speedSelect.value = String(coordinatePlayback.speedMultiplier);
            speedSelect.disabled = !hasPath;
        }
        if (progressLabel) {
            progressLabel.textContent = `${(ratio * 100).toFixed(1)}%`;
        }
        if (toolbarNote) {
            toolbarNote.textContent = hasPath
                ? `目前使用第 ${formatInteger(geometry.layerIndex)} 層的 G-code 沉積路徑，並同步播放熱像 G_High。`
                : "請先切換到有熱像資料的 G-code layer。";
        }
        if (statusLabel) {
            if (!hasPath) {
                statusLabel.textContent = "請選擇有熱像資料與沉積路徑的 layer。";
                return;
            }
            const point = snapshot?.headPoint || geometry.points[0];
            const pointTime = point.heat_timestamp_ms ?? point.timestamp_ms ?? null;
            const finishedText = ratio >= 1 ? " / 播放完成" : "";
            const alertLabel = classifyHeatAlert(point.heat_g_high).label;
            statusLabel.textContent = `Layer ${geometry.layerIndex} / ${formatChartTime(pointTime)} / G_High ${formatNumber(point.heat_g_high, 2)} °C / ${alertLabel} / X ${formatNumber(point.x_mm, 2)} / Y ${formatNumber(point.y_mm, 2)}${finishedText}`;
        }
    }

    function renderCoordinatePlaybackFrame(frameTimeMs) {
        if (!coordinatePlayback.isPlaying || !coordinatePlayback.geometry) {
            return;
        }

        if (!coordinatePlayback.lastFrameMs) {
            coordinatePlayback.lastFrameMs = frameTimeMs;
        }
        const elapsedSeconds = Math.max((frameTimeMs - coordinatePlayback.lastFrameMs) / 1000, 0);
        coordinatePlayback.lastFrameMs = frameTimeMs;

        const advance = elapsedSeconds * coordinatePlayback.geometry.baseUnitsPerSecond * coordinatePlayback.speedMultiplier;
        coordinatePlayback.progressUnits = clamp(
            coordinatePlayback.progressUnits + advance,
            0,
            coordinatePlayback.totalUnits || coordinatePlayback.geometry.totalUnits || 0,
        );
        renderCoordinateAlignment();

        if (coordinatePlayback.progressUnits >= (coordinatePlayback.totalUnits || coordinatePlayback.geometry.totalUnits || 0)) {
            pauseCoordinatePlayback();
            renderCoordinateAlignment();
            return;
        }

        coordinatePlayback.rafId = window.requestAnimationFrame(renderCoordinatePlaybackFrame);
    }

    function startCoordinatePlayback() {
        const geometry = ensureCoordinatePlaybackGeometry(state.coordinate_alignment || {});
        if (!geometry || geometry.segments.length === 0) {
            renderCoordinateAlignment();
            return;
        }

        if (coordinatePlayback.progressUnits >= (coordinatePlayback.totalUnits || geometry.totalUnits)) {
            coordinatePlayback.progressUnits = 0;
        }

        pauseCoordinatePlayback();
        coordinatePlayback.isPlaying = true;
        coordinatePlayback.lastFrameMs = 0;
        renderCoordinateAlignment();
        coordinatePlayback.rafId = window.requestAnimationFrame(renderCoordinatePlaybackFrame);
    }

    function resetCoordinatePlayback() {
        pauseCoordinatePlayback();
        coordinatePlayback.progressUnits = 0;
        renderCoordinateAlignment();
    }

    function bindCoordinatePlaybackControls() {
        const playButton = byId("coordinate-play-button");
        const resetButton = byId("coordinate-reset-button");
        const range = byId("coordinate-progress-range");
        const speedSelect = byId("coordinate-speed-select");
        const trajectorySelect = byId("coordinate-trajectory-select");

        if (playButton && !playButton.dataset.bound) {
            playButton.addEventListener("click", () => {
                if (coordinatePlayback.isPlaying) {
                    pauseCoordinatePlayback();
                    renderCoordinateAlignment();
                    return;
                }
                startCoordinatePlayback();
            });
            playButton.dataset.bound = "true";
        }

        if (resetButton && !resetButton.dataset.bound) {
            resetButton.addEventListener("click", () => {
                resetCoordinatePlayback();
            });
            resetButton.dataset.bound = "true";
        }

        if (range && !range.dataset.bound) {
            range.addEventListener("input", (event) => {
                pauseCoordinatePlayback();
                const ratio = Number(event.target.value) / progressSliderMax;
                coordinatePlayback.progressUnits = (coordinatePlayback.totalUnits || 0) * clamp(ratio, 0, 1);
                renderCoordinateAlignment();
            });
            range.dataset.bound = "true";
        }

        if (speedSelect && !speedSelect.dataset.bound) {
            speedSelect.addEventListener("change", (event) => {
                coordinatePlayback.speedMultiplier = Number(event.target.value) || 1;
                renderCoordinateAlignment();
            });
            speedSelect.dataset.bound = "true";
        }

        if (trajectorySelect && !trajectorySelect.dataset.bound) {
            trajectorySelect.addEventListener("change", (event) => {
                selectedCoordinateTrajectoryId = String(event.target.value || "");
                coordinatePlayback.geometryKey = "";
                resetCoordinatePlayback();
            });
            trajectorySelect.dataset.bound = "true";
        }
    }

    function renderCoordinateAlignment() {
        const payload = state.coordinate_alignment || {};
        const statsNode = byId("coordinate-stats");
        const plotNode = byId("coordinate-plot");

        if (!payload.available) {
            statsNode.replaceChildren(
                (() => {
                    const article = document.createElement("article");
                    article.className = "metric-card";
                    article.innerHTML = `<span>Status</span><strong>${payload.message || "No coordinate conversion data."}</strong>`;
                    return article;
                })(),
            );
            plotNode.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">${payload.message || "No coordinate conversion data."}</text>`;
            renderCoordinateTrajectoryOptions(payload);
            renderCoordinateTrajectorySummaries(payload);
            updateCoordinateControls(payload, null, null);
            return;
        }

        const offset = payload.applied_offset_mm || {};
        const stats = [
            { label: "Machine Frame", value: payload.machine_frame_label || "-" },
            { label: "Work Frame", value: payload.work_frame_label || "-" },
            { label: "Offset X", value: `${formatNumber(offset.x_mm, 3)} mm` },
            { label: "Offset Y", value: `${formatNumber(offset.y_mm, 3)} mm` },
            { label: "Offset Z", value: `${formatNumber(offset.z_mm, 3)} mm` },
            { label: "Trajectories", value: formatInteger(payload.trajectory_count) },
        ];

        statsNode.replaceChildren(
            ...stats.map((metric) => {
                const article = document.createElement("article");
                article.className = "metric-card";
                article.innerHTML = `<span>${metric.label}</span><strong>${metric.value}</strong>`;
                return article;
            }),
        );

        renderCoordinateTrajectoryOptions(payload);
        renderCoordinateTrajectorySummaries(payload);

        const geometry = ensureCoordinatePlaybackGeometry(payload);
        if (!geometry) {
            plotNode.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">No transformed edge path.</text>`;
            updateCoordinateControls(payload, null, null);
            return;
        }

        const snapshot = buildCoordinatePlaybackSnapshot(geometry);
        const headColor = coordinateHeatColor(snapshot?.headHeat, geometry.heatMin, geometry.heatMax);
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
        updateCoordinateControls(payload, geometry, snapshot);
    }

    function coordinatePlaybackKey(layer, heatWindow) {
        return [
            state.selected_output_name ?? "",
            layer?.layer_index ?? "",
            layer?.motion_points?.length ?? "",
            heatWindow?.trace?.length ?? "",
            heatWindow?.start_timestamp_ms ?? "",
            heatWindow?.end_timestamp_ms ?? "",
        ].join("|");
    }

    function coordinateHeatTrace() {
        const edgeTrace = Array.isArray(state.edge?.edge_trace) ? state.edge.edge_trace : [];
        if (edgeTrace.length && edgeTrace.some((point) => Number.isFinite(Number(point.g_high)))) {
            return edgeTrace
                .map((point) => ({
                    timestamp_ms: Number(point.timestamp_ms),
                    g_high: Number(point.g_high),
                }))
                .filter((point) => Number.isFinite(point.timestamp_ms) && Number.isFinite(point.g_high))
                .sort((left, right) => left.timestamp_ms - right.timestamp_ms);
        }
        const thermalTrace = Array.isArray(state.thermal?.thermal_trace) ? state.thermal.thermal_trace : [];
        return thermalTrace
            .map((point) => ({
                timestamp_ms: Number(point.timestamp_ms),
                g_high: Number(point.g_high),
            }))
            .filter((point) => Number.isFinite(point.timestamp_ms) && Number.isFinite(point.g_high))
            .sort((left, right) => left.timestamp_ms - right.timestamp_ms);
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
        const heatTrace = coordinateHeatTrace();
        const layers = Array.isArray(state.layers) ? state.layers : [];
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
            const trace = heatTrace.filter((point) => point.timestamp_ms >= windowStartMs && point.timestamp_ms <= windowEndMs);
            return {
                layer_index: item.layer_index,
                z_level_mm: item.z_level_mm,
                deposit_units: item.deposit_units,
                start_timestamp_ms: windowStartMs,
                end_timestamp_ms: windowEndMs,
                sample_count: trace.length,
                trace,
            };
        });
    }

    function currentLayerHeatWindow() {
        const windows = buildLayerHeatWindows();
        return windows.find((item) => Number(item.layer_index) === Number(selectedLayerIndex)) || windows[0] || null;
    }

    function renderCoordinateTrajectoryOptions() {
        const select = byId("coordinate-trajectory-select");
        if (!select) {
            return;
        }
        const options = (Array.isArray(state.layers) ? state.layers : []).map((layer) => ({
            value: String(layer.layer_index),
            label: `Layer ${layer.layer_index} · Z ${formatNumber(layer.z_level_mm, 3)} mm`,
        }));
        select.replaceChildren(
            ...options.map((optionData) => {
                const option = document.createElement("option");
                option.value = optionData.value;
                option.textContent = optionData.label;
                option.selected = Number(optionData.value) === Number(selectedLayerIndex);
                return option;
            }),
        );
        select.disabled = options.length === 0;
    }

    function renderCoordinateTrajectorySummaries() {
        const listNode = byId("trajectory-list");
        const windows = buildLayerHeatWindows().slice(0, 12);
        listNode.replaceChildren(
            ...windows.map((item) => {
                const layerIndex = Number(item.layer_index);
                const article = document.createElement("article");
                article.className = `list-card list-card-selectable${layerIndex === Number(selectedLayerIndex) ? " list-card-selected" : ""}`;
                article.tabIndex = 0;
                article.innerHTML = `
                    <div class="list-head">
                        <strong>Layer ${layerIndex}</strong>
                        <span class="pill ${layerIndex === Number(selectedLayerIndex) ? "pill-deposit" : "pill-neutral"}">${formatInteger(item.sample_count)} heat samples</span>
                    </div>
                    <div class="list-body">Z ${formatNumber(item.z_level_mm, 3)} mm / Deposit length ${formatNumber(item.deposit_units, 2)} mm</div>
                    <div class="list-body">${formatChartTime(item.start_timestamp_ms)} -> ${formatChartTime(item.end_timestamp_ms)}</div>
                `;
                article.addEventListener("click", () => {
                    if (layerIndex === Number(selectedLayerIndex)) {
                        return;
                    }
                    selectedLayerIndex = layerIndex;
                    coordinatePlayback.geometryKey = "";
                    resetCoordinatePlayback();
                    renderDynamicSections();
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

    function buildCoordinateGeometry() {
        const layer = layerRecord();
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

        const mappedPoints = depositPoints.map((point, index) => {
            const heatIndex = clampIndex(Math.round((index / Math.max(depositPoints.length - 1, 1)) * (heatTrace.length - 1)), heatTrace.length - 1);
            const heatPoint = heatTrace[heatIndex];
            return {
                ...point,
                projected: project(point),
                heat_g_high: Number(heatPoint.g_high),
                heat_timestamp_ms: Number(heatPoint.timestamp_ms),
            };
        });

        const heatValues = mappedPoints.map((point) => Number(point.heat_g_high)).filter((value) => Number.isFinite(value));
        const heatMin = heatValues.length ? Math.min(...heatValues) : 0;
        const heatMax = heatValues.length ? Math.max(...heatValues) : 1;
        const heatAverage = heatValues.length
            ? heatValues.reduce((sum, value) => sum + Number(value), 0) / heatValues.length
            : null;
        const heatSummary = summarizeHeatAlertSamples(heatTrace, (point) => point.g_high);

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
            <text x="${padding.left}" y="18" class="axis-label">X ${formatNumber(bounds.x_min_mm, 2)} ~ ${formatNumber(bounds.x_max_mm, 2)} mm</text>
            <text x="${width - padding.right}" y="18" text-anchor="end" class="axis-label">Y ${formatNumber(bounds.y_min_mm, 2)} ~ ${formatNumber(bounds.y_max_mm, 2)} mm</text>
        `;

        const durationSeconds = Math.max((Number(heatWindow.end_timestamp_ms) - Number(heatWindow.start_timestamp_ms)) / 1000, 1);
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
            heatWindow,
            baseUnitsPerSecond: Math.max(totalUnits / durationSeconds, totalUnits / 18, 2.5),
        };
    }

    function ensureCoordinatePlaybackGeometry() {
        const layer = layerRecord();
        const heatWindow = currentLayerHeatWindow();
        const nextKey = coordinatePlaybackKey(layer, heatWindow);
        if (coordinatePlayback.geometryKey !== nextKey) {
            pauseCoordinatePlayback();
            coordinatePlayback.geometryKey = nextKey;
            coordinatePlayback.geometry = buildCoordinateGeometry();
            coordinatePlayback.totalUnits = coordinatePlayback.geometry?.totalUnits ?? 0;
            coordinatePlayback.progressUnits = 0;
        }
        return coordinatePlayback.geometry;
    }

    function buildCoordinatePlaybackSnapshot(geometry) {
        if (!geometry || !geometry.points.length) {
            return null;
        }
        const totalUnits = coordinatePlayback.totalUnits || geometry.totalUnits || 0;
        const progressUnits = clamp(coordinatePlayback.progressUnits, 0, totalUnits);
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
                const ratio = clamp((progressUnits - segment.startUnits) / span, 0, 1);
                const partialProjected = interpolatePoint(segment.startProjected, segment.endProjected, ratio);
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
            const color = coordinateHeatColor(point.heat_g_high, geometry.heatMin, geometry.heatMax);
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
        const panel = byId("coordinate-alert-panel");
        if (!panel) {
            return;
        }
        if (!geometry || !Array.isArray(geometry.points) || !geometry.points.length) {
            panel.innerHTML = `
                <div class="coordinate-alert-empty">
                    <strong>尚未建立熱像同步警示。</strong>
                    <p>請先選擇有熱像資料與沉積路徑的 layer，系統才會根據 G-code Heat Playback 顯示即時警示。</p>
                </div>
            `;
            return;
        }

        const point = snapshot?.headPoint || geometry.points[0];
        const pointTime = point?.heat_timestamp_ms ?? point?.timestamp_ms ?? null;
        const status = classifyHeatAlert(point?.heat_g_high);
        const summary = geometry.heatSummary || summarizeHeatAlertSamples(geometry.heatWindow?.trace, (item) => item.g_high);
        const progressText = `${((snapshot?.progressRatio ?? 0) * 100).toFixed(1)}%`;
        const cardMarkup = heatAlertBands
            .map((band) => {
                const count = Number(summary?.[band.key] || 0);
                const ratioText = summary?.total ? `${((count / summary.total) * 100).toFixed(1)}%` : "0.0%";
                const activeClass = status.key === band.key ? " is-active" : "";
                return `
                    <article class="coordinate-alert-card ${band.badgeClass}${activeClass}">
                        <span class="coordinate-alert-card-label">${band.label}</span>
                        <strong class="coordinate-alert-card-value">${formatInteger(count)} 點</strong>
                        <div class="coordinate-alert-card-meta">
                            <span>${ratioText}</span>
                            <span>${summary?.total ? `${formatInteger(summary.total)} 筆樣本` : "0 筆樣本"}</span>
                        </div>
                        <div class="coordinate-alert-card-range">${band.rangeLabel}</div>
                    </article>
                `;
            })
            .join("");

        panel.innerHTML = `
            <div class="coordinate-alert-overview">
                <div class="coordinate-alert-copy">
                    <p class="coordinate-alert-kicker">熱像同步警示</p>
                    <p class="coordinate-alert-reading">${formatNumber(point?.heat_g_high, 2)} °C</p>
                    <p class="coordinate-alert-meta">Layer ${formatInteger(geometry.layerIndex)} · ${formatChartTime(pointTime)} · 播放進度 ${progressText}</p>
                    <p class="coordinate-alert-description">${status.description}</p>
                </div>
                <span class="coordinate-alert-badge ${status.badgeClass}">${status.label}</span>
            </div>
            <div class="coordinate-alert-grid">${cardMarkup}</div>
            <div class="coordinate-alert-footer">
                <span>本層峰值 ${formatNumber(geometry.heatMax, 2)} °C</span>
                <span>本層平均 ${formatNumber(geometry.heatAverage, 2)} °C</span>
                <span>X ${formatNumber(point?.x_mm, 2)} / Y ${formatNumber(point?.y_mm, 2)} / Z ${formatNumber(point?.z_mm, 2)} mm</span>
            </div>
        `;
    }

    function updateCoordinateControls(geometry, snapshot) {
        const playButton = byId("coordinate-play-button");
        const resetButton = byId("coordinate-reset-button");
        const range = byId("coordinate-progress-range");
        const speedSelect = byId("coordinate-speed-select");
        const progressLabel = byId("coordinate-progress-label");
        const statusLabel = byId("coordinate-status");
        const toolbarNote = byId("coordinate-toolbar-note");
        const hasPath = Boolean(geometry && geometry.points.length > 1 && geometry.segments.length);
        const ratio = snapshot?.progressRatio ?? 0;
        const sliderValue = Math.round(ratio * progressSliderMax);

        if (playButton) {
            playButton.disabled = !hasPath;
            playButton.textContent = coordinatePlayback.isPlaying ? "暫停" : "播放";
        }
        if (resetButton) {
            resetButton.disabled = !hasPath;
        }
        if (range) {
            range.disabled = !hasPath;
            range.value = String(sliderValue);
        }
        if (speedSelect) {
            speedSelect.value = String(coordinatePlayback.speedMultiplier);
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
            statusLabel.textContent = `Layer ${geometry.layerIndex} / ${formatChartTime(pointTime)} / G_High ${formatNumber(point.heat_g_high, 2)} / X ${formatNumber(point.x_mm, 2)} / Y ${formatNumber(point.y_mm, 2)}${finishedText}`;
        }
    }

    function renderCoordinatePlaybackFrame(frameTimeMs) {
        if (!coordinatePlayback.isPlaying || !coordinatePlayback.geometry) {
            return;
        }
        if (!coordinatePlayback.lastFrameMs) {
            coordinatePlayback.lastFrameMs = frameTimeMs;
        }
        const elapsedSeconds = Math.max((frameTimeMs - coordinatePlayback.lastFrameMs) / 1000, 0);
        coordinatePlayback.lastFrameMs = frameTimeMs;
        const advance = elapsedSeconds * coordinatePlayback.geometry.baseUnitsPerSecond * coordinatePlayback.speedMultiplier;
        coordinatePlayback.progressUnits = clamp(
            coordinatePlayback.progressUnits + advance,
            0,
            coordinatePlayback.totalUnits || coordinatePlayback.geometry.totalUnits || 0,
        );
        renderCoordinateAlignment();
        if (coordinatePlayback.progressUnits >= (coordinatePlayback.totalUnits || coordinatePlayback.geometry.totalUnits || 0)) {
            pauseCoordinatePlayback();
            renderCoordinateAlignment();
            return;
        }
        coordinatePlayback.rafId = window.requestAnimationFrame(renderCoordinatePlaybackFrame);
    }

    function startCoordinatePlayback() {
        const geometry = ensureCoordinatePlaybackGeometry();
        if (!geometry || geometry.segments.length === 0) {
            renderCoordinateAlignment();
            return;
        }
        if (coordinatePlayback.progressUnits >= (coordinatePlayback.totalUnits || geometry.totalUnits)) {
            coordinatePlayback.progressUnits = 0;
        }
        pauseCoordinatePlayback();
        coordinatePlayback.isPlaying = true;
        coordinatePlayback.lastFrameMs = 0;
        renderCoordinateAlignment();
        coordinatePlayback.rafId = window.requestAnimationFrame(renderCoordinatePlaybackFrame);
    }

    function resetCoordinatePlayback() {
        pauseCoordinatePlayback();
        coordinatePlayback.progressUnits = 0;
        renderCoordinateAlignment();
    }

    function bindCoordinatePlaybackControls() {
        const playButton = byId("coordinate-play-button");
        const resetButton = byId("coordinate-reset-button");
        const range = byId("coordinate-progress-range");
        const speedSelect = byId("coordinate-speed-select");
        const layerSelect = byId("coordinate-trajectory-select");

        if (playButton && !playButton.dataset.bound) {
            playButton.addEventListener("click", () => {
                if (coordinatePlayback.isPlaying) {
                    pauseCoordinatePlayback();
                    renderCoordinateAlignment();
                    return;
                }
                startCoordinatePlayback();
            });
            playButton.dataset.bound = "true";
        }
        if (resetButton && !resetButton.dataset.bound) {
            resetButton.addEventListener("click", () => {
                resetCoordinatePlayback();
            });
            resetButton.dataset.bound = "true";
        }
        if (range && !range.dataset.bound) {
            range.addEventListener("input", (event) => {
                pauseCoordinatePlayback();
                const ratio = Number(event.target.value) / progressSliderMax;
                coordinatePlayback.progressUnits = (coordinatePlayback.totalUnits || 0) * clamp(ratio, 0, 1);
                renderCoordinateAlignment();
            });
            range.dataset.bound = "true";
        }
        if (speedSelect && !speedSelect.dataset.bound) {
            speedSelect.addEventListener("change", (event) => {
                coordinatePlayback.speedMultiplier = Number(event.target.value) || 1;
                renderCoordinateAlignment();
            });
            speedSelect.dataset.bound = "true";
        }
        if (layerSelect && !layerSelect.dataset.bound) {
            layerSelect.addEventListener("change", (event) => {
                selectedLayerIndex = Number(event.target.value) || selectedLayerIndex;
                coordinatePlayback.geometryKey = "";
                resetCoordinatePlayback();
                renderDynamicSections();
            });
            layerSelect.dataset.bound = "true";
        }
    }

    function renderCoordinateAlignment() {
        const statsNode = byId("coordinate-stats");
        const plotNode = byId("coordinate-plot");
        const layer = layerRecord();
        const heatWindow = currentLayerHeatWindow();
        renderCoordinateTrajectoryOptions();
        renderCoordinateTrajectorySummaries();

        if (!layer || !heatWindow) {
            statsNode.replaceChildren((() => {
                const article = document.createElement("article");
                article.className = "metric-card";
                article.innerHTML = "<span>Status</span><strong>No G-code heat window.</strong>";
                return article;
            })());
            plotNode.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="#6b7280" font-size="20">No G-code heat playback data.</text>`;
            updateCoordinateControls(null, null);
            renderCoordinateAlertPanel(null, null);
            return;
        }

        const mapping = state.accurate_time_mapping || {};
        const stats = [
            { label: "Selected Layer", value: `Layer ${formatInteger(layer.layer_index)}` },
            { label: "Z Level", value: `${formatNumber(layer.z_level_mm, 3)} mm` },
            { label: "Heat Samples", value: formatInteger(heatWindow.sample_count) },
            { label: "Window Start", value: formatChartTime(heatWindow.start_timestamp_ms) },
            { label: "Window End", value: formatChartTime(heatWindow.end_timestamp_ms) },
            { label: "Time Mapping", value: mapping.offset_s !== undefined ? `${formatNumber(mapping.offset_s, 3)} s` : "-" },
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
        const headColor = coordinateHeatColor(snapshot?.headHeat, geometry.heatMin, geometry.heatMax);
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

    function renderDynamicSections() {
        renderToolbar();
        renderLayerMetrics();
        renderSegments();
        renderEvents();
        renderToolpath();
        renderThermal();
        renderAlignment();
        renderCoordinateAlignment();
    }

    renderHeader();
    renderOutputSelect();
    renderUploadForm();
    renderMpfEditor();
    bindToolpathControls();
    bindAlignmentControls();
    bindCoordinatePlaybackControls();
    bindChartInteractions();
    renderLayerSelect();
    renderDynamicSections();
})();
