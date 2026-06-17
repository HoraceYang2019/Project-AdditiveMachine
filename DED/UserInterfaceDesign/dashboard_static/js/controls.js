export function initControlsSection(ctx) {
    let topBandHeightRaf = 0;

    function normalizeHeroUploadPanel() {
        const hero = document.querySelector(".hero");
        const heroCopy = hero?.querySelector(".hero-copy");
        const heroTitleRow = heroCopy?.querySelector(".hero-title-row");
        const uploadPanel = hero?.querySelector(".upload-panel");
        if (!hero || !heroCopy || !heroTitleRow || !uploadPanel) {
            return;
        }
        let heroMain = hero.querySelector(".hero-main");

        if (uploadPanel.parentElement !== heroTitleRow) {
            heroTitleRow.appendChild(uploadPanel);
        }

        if (heroMain) {
            if (heroCopy.parentElement === heroMain) {
                hero.insertBefore(heroCopy, heroMain);
            }
            heroMain.remove();
        }
    }

    function clearTopBandHeightSync() {
        const topBand = document.querySelector(".top-band");
        const heroCopy = document.querySelector(".hero-copy");
        const heroCards = document.querySelector("#header-cards");
        const commandPanel = document.querySelector(".top-command-panel");
        const targets = [heroCopy, heroCards, commandPanel].filter(Boolean);

        topBand?.style.removeProperty("--top-band-equal-height");
        for (const element of targets) {
            element.style.removeProperty("min-height");
            element.style.removeProperty("height");
            element.style.removeProperty("align-self");
        }
    }

    function syncTopBandHeights() {
        clearTopBandHeightSync();
    }

    function scheduleTopBandHeightSync() {
        if (topBandHeightRaf) {
            cancelAnimationFrame(topBandHeightRaf);
        }
        topBandHeightRaf = requestAnimationFrame(() => {
            topBandHeightRaf = 0;
            syncTopBandHeights();
        });
    }

    function floatingPanels() {
        return Array.from(document.querySelectorAll(".upload-panel"));
    }

    function syncFloatingPanelState() {
        const hasOpenPanel = floatingPanels().some((panel) => panel.open);
        document.body.classList.toggle("floating-panel-open", hasOpenPanel);
    }

    function closeFloatingPanels(exceptPanel = null) {
        for (const panel of floatingPanels()) {
            if (panel !== exceptPanel) {
                panel.open = false;
            }
        }
        syncFloatingPanelState();
    }

    function resetFloatingPanelPosition(panel) {
        panel.style.setProperty("--floating-panel-left", `${Math.round(window.innerWidth / 2)}px`);
        panel.style.setProperty("--floating-panel-top", `${Math.round(window.innerHeight / 2)}px`);
    }

    function ensureFloatingPanelCloseButton(panel) {
        const summary = panel.querySelector(".panel-summary");
        if (!summary || summary.querySelector(".panel-floating-close")) {
            return;
        }

        const button = document.createElement("button");
        button.type = "button";
        button.className = "panel-floating-close";
        button.setAttribute("aria-label", "關閉彈窗");
        button.textContent = "×";
        button.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            panel.open = false;
            syncFloatingPanelState();
        });
        summary.appendChild(button);
    }

    function bindFloatingPanelDrag(panel) {
        const summary = panel.querySelector(".panel-summary");
        if (!summary || summary.dataset.dragBound) {
            return;
        }

        summary.addEventListener("click", (event) => {
            if (panel.open && !event.target.closest(".panel-floating-close")) {
                event.preventDefault();
            }
        });

        summary.addEventListener("pointerdown", (event) => {
            if (!panel.open || event.target.closest(".panel-floating-close")) {
                return;
            }
            if (event.button !== undefined && event.button !== 0) {
                return;
            }

            event.preventDefault();
            const rect = panel.getBoundingClientRect();
            const startX = event.clientX;
            const startY = event.clientY;
            const startCenterX = rect.left + rect.width / 2;
            const startCenterY = rect.top + rect.height / 2;

            function movePanel(moveEvent) {
                const nextCenterX = ctx.clamp(
                    startCenterX + moveEvent.clientX - startX,
                    rect.width / 2 + 12,
                    window.innerWidth - rect.width / 2 - 12,
                );
                const nextCenterY = ctx.clamp(
                    startCenterY + moveEvent.clientY - startY,
                    rect.height / 2 + 12,
                    window.innerHeight - rect.height / 2 - 12,
                );
                panel.style.setProperty("--floating-panel-left", `${nextCenterX}px`);
                panel.style.setProperty("--floating-panel-top", `${nextCenterY}px`);
            }

            function stopDrag() {
                document.removeEventListener("pointermove", movePanel);
                document.removeEventListener("pointerup", stopDrag);
                document.removeEventListener("pointercancel", stopDrag);
            }

            document.addEventListener("pointermove", movePanel);
            document.addEventListener("pointerup", stopDrag);
            document.addEventListener("pointercancel", stopDrag);
        });

        summary.dataset.dragBound = "true";
    }

    function bindFloatingPanelDismiss() {
        if (document.body.dataset.floatingPanelsBound) {
            return;
        }

        normalizeHeroUploadPanel();
        if (!document.body.dataset.heroUploadResponsiveBound) {
            window.addEventListener("resize", () => {
                normalizeHeroUploadPanel();
                scheduleTopBandHeightSync();
            });
            document.body.dataset.heroUploadResponsiveBound = "true";
        }

        for (const panel of floatingPanels()) {
            ensureFloatingPanelCloseButton(panel);
            bindFloatingPanelDrag(panel);
        }

        document.addEventListener("click", (event) => {
            const openPanels = floatingPanels().filter((panel) => panel.open);
            if (!openPanels.length) {
                return;
            }
            const clickedInside = openPanels.some((panel) => (
                panel.querySelector(".panel-summary")?.contains(event.target)
                || panel.querySelector(".collapsible-panel-body")?.contains(event.target)
            ));
            if (!clickedInside) {
                closeFloatingPanels();
            }
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeFloatingPanels();
            }
        });

        for (const panel of floatingPanels()) {
            panel.addEventListener("toggle", () => {
                if (panel.open) {
                    resetFloatingPanelPosition(panel);
                    closeFloatingPanels(panel);
                }
                syncFloatingPanelState();
            });
        }

        const initiallyOpenPanels = floatingPanels().filter((panel) => panel.open);
        if (initiallyOpenPanels.length) {
            const primaryPanel = initiallyOpenPanels[0];
            resetFloatingPanelPosition(primaryPanel);
            closeFloatingPanels(primaryPanel);
        } else {
            syncFloatingPanelState();
        }

        document.body.dataset.floatingPanelsBound = "true";
    }

    function renderHeader() {
        document.title = ctx.state.header?.title || "DED Dashboard";
        ctx.setText("dashboard-title", ctx.state.header?.title || "DED Dashboard");
        ctx.setText("dashboard-subtitle", ctx.state.header?.subtitle || "");
        ctx.setText("program-id-chip", `程式 ${ctx.state.header?.program_id ?? "-"}`);
        ctx.setText("output-name-chip", `輸出 ${ctx.state.output_name ?? "-"}`);

        const headerCards = ctx.byId("header-cards");
        const hero = document.querySelector(".hero");
        if (!headerCards) {
            return;
        }
        const cards = (ctx.state.header?.header_cards || []).map((card) => {
                const article = document.createElement("article");
                article.className = "hero-card";
                article.innerHTML = `<span>${card.label}</span><strong>${card.value}</strong>`;
                return article;
            });
        headerCards.replaceChildren(...cards);
        const hasCards = cards.length > 0;
        headerCards.hidden = !hasCards;
        hero?.classList.toggle("hero-single", !hasCards);
        scheduleTopBandHeightSync();
    }

    function buildOutputOptions(selectedValue) {
        const outputs = Array.isArray(ctx.state.available_outputs) ? ctx.state.available_outputs : [];
        return outputs.map((output) => {
            const option = document.createElement("option");
            option.value = String(output.value ?? "");
            option.textContent = output.label ?? output.value ?? "-";
            option.selected = option.value === String(selectedValue ?? "");
            return option;
        });
    }

    function renderOutputSelect() {
        const select = ctx.byId("output-select");
        if (!select) {
            return;
        }
        select.replaceChildren(...buildOutputOptions(ctx.state.selected_output_name));
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
        const select = ctx.byId("upload-target-output");
        if (select) {
            select.replaceChildren(...buildOutputOptions(ctx.state.selected_output_name));
        }
        const edgeExampleLink = ctx.byId("edge-example-link");
        if (edgeExampleLink && ctx.state.upload_help?.edge_example_url) {
            edgeExampleLink.href = ctx.state.upload_help.edge_example_url;
        }
    }

    function renderUploadForm() {
        renderUploadBindings();
        const form = ctx.byId("upload-form");
        const submitButton = ctx.byId("upload-submit");
        if (!form || form.dataset.bound) {
            return;
        }

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const formData = new FormData(form);
            if (!formData.get("target_output_name") && ctx.state.selected_output_name) {
                formData.set("target_output_name", ctx.state.selected_output_name);
            }

            ctx.setStatus("正在上傳資料並更新 dashboard...", "working");
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
                    throw new Error(payload.message || "上傳失敗");
                }
                ctx.setStatus(payload.message || "上傳完成，正在切換資料集...", "success");
                const params = new URLSearchParams(window.location.search);
                if (payload.selected_output_name) {
                    params.set("output_name", payload.selected_output_name);
                }
                const nextSearch = params.toString();
                window.location.search = nextSearch ? `?${nextSearch}` : "";
            } catch (error) {
                ctx.setStatus(error instanceof Error ? error.message : "上傳失敗", "error");
            } finally {
                if (submitButton) {
                    submitButton.disabled = false;
                }
            }
        });

        form.dataset.bound = "true";
    }

    async function loadMpfSource() {
        const editorConfig = ctx.state.mpf_editor || {};
        const textArea = ctx.byId("mpf-editor-text");
        const fileNameInput = ctx.byId("mpf-editor-file-name");
        if (!textArea || !fileNameInput) {
            return;
        }

        if (!editorConfig.source_available || !editorConfig.load_url) {
            textArea.value = "";
            fileNameInput.value = ctx.normalizeMpfFileName(
                editorConfig.source_file_name || ctx.state.nc_file?.file_name || ctx.state.output_name,
                ctx.state.output_name || "edited_output",
            );
            ctx.setEditorEditable(false);
            ctx.setText("mpf-editor-source-label", "目前沒有可編輯的 MPF 來源。");
            ctx.updateEditorLineCount("");
            ctx.setEditorDownloadLink("#", "沒有可下載的原始檔", false);
            ctx.setEditorStatus("請先上傳 MPF，或切換到帶有原始 MPF 的 output。", "error");
            return;
        }

        ctx.setEditorBusy(true);
        ctx.setEditorStatus("正在讀取 MPF 內容...", "working");

        try {
            const response = await fetch(editorConfig.load_url);
            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || "讀取 MPF 失敗");
            }

            ctx.editor.sourceText = String(payload.text || "");
            ctx.editor.sourceFileName = ctx.normalizeMpfFileName(
                payload.file_name || editorConfig.source_file_name || ctx.state.output_name,
                ctx.state.output_name || "edited_output",
            );
            textArea.value = ctx.editor.sourceText;
            fileNameInput.value = ctx.editor.sourceFileName;
            ctx.setEditorEditable(true);
            ctx.setText("mpf-editor-source-label", `來源檔案：${ctx.editor.sourceFileName}`);
            ctx.updateEditorLineCount(ctx.editor.sourceText);
            ctx.setEditorDownloadLink(payload.download_url || editorConfig.download_url, "下載原始 MPF", true);
            ctx.setEditorStatus("MPF 已載入，可以直接編輯或另存。", "success");
        } catch (error) {
            textArea.value = "";
            ctx.setEditorEditable(false);
            ctx.updateEditorLineCount("");
            ctx.setEditorDownloadLink("#", "沒有可下載的原始檔", false);
            ctx.setEditorStatus(error instanceof Error ? error.message : "讀取 MPF 失敗", "error");
        } finally {
            ctx.setEditorBusy(false);
        }
    }

    function renderMpfEditor() {
        const textArea = ctx.byId("mpf-editor-text");
        const fileNameInput = ctx.byId("mpf-editor-file-name");
        const reloadButton = ctx.byId("mpf-editor-reload");
        const previewButton = ctx.byId("mpf-editor-preview");
        const exportButton = ctx.byId("mpf-editor-export");
        if (!textArea || !fileNameInput || !reloadButton || !previewButton || !exportButton) {
            return;
        }

        if (!textArea.dataset.bound) {
            textArea.addEventListener("input", (event) => {
                ctx.updateEditorLineCount(event.target.value);
                ctx.setEditorStatus("內容已更新，可以即時預覽或匯出新 MPF。", "info");
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
                const nextFileName = ctx.normalizeMpfFileName(
                    fileNameInput.value || ctx.editor.sourceFileName || ctx.state.output_name,
                    ctx.state.output_name || "edited_preview",
                );
                ctx.setEditorBusy(true);
                ctx.setEditorStatus("正在建立 preview output...", "working");
                try {
                    const response = await fetch((ctx.state.mpf_editor || {}).preview_url || "/api/preview-mpf", {
                        method: "POST",
                        headers: { "Content-Type": "application/json; charset=utf-8" },
                        body: JSON.stringify({
                            output_name: ctx.state.selected_output_name,
                            file_name: nextFileName,
                            mpf_text: textArea.value,
                        }),
                    });
                    const payload = await response.json();
                    if (!response.ok || !payload.ok) {
                        throw new Error(payload.message || "建立 preview 失敗");
                    }
                    ctx.setEditorStatus(payload.message || "Preview 已建立，正在切換。", "success");
                    const params = new URLSearchParams(window.location.search);
                    if (payload.selected_output_name) {
                        params.set("output_name", payload.selected_output_name);
                    }
                    const nextSearch = params.toString();
                    window.location.search = nextSearch ? `?${nextSearch}` : "";
                } catch (error) {
                    ctx.setEditorStatus(error instanceof Error ? error.message : "建立 preview 失敗", "error");
                    ctx.setEditorBusy(false);
                }
            });
            previewButton.dataset.bound = "true";
        }

        if (!exportButton.dataset.bound) {
            exportButton.addEventListener("click", async () => {
                const nextFileName = ctx.normalizeMpfFileName(
                    fileNameInput.value || ctx.editor.sourceFileName || ctx.state.output_name,
                    ctx.state.output_name || "exported_mpf",
                );
                ctx.setEditorBusy(true);
                ctx.setEditorStatus("正在輸出新 MPF 檔案...", "working");
                try {
                    const response = await fetch((ctx.state.mpf_editor || {}).export_url || "/api/export-mpf", {
                        method: "POST",
                        headers: { "Content-Type": "application/json; charset=utf-8" },
                        body: JSON.stringify({
                            output_name: ctx.state.selected_output_name,
                            file_name: nextFileName,
                            mpf_text: textArea.value,
                        }),
                    });
                    const payload = await response.json();
                    if (!response.ok || !payload.ok) {
                        throw new Error(payload.message || "輸出 MPF 失敗");
                    }
                    ctx.setEditorStatus(
                        payload.saved_path
                            ? `新 MPF 已輸出：${payload.saved_path}`
                            : (payload.message || "新 MPF 已輸出"),
                        "success",
                    );
                } catch (error) {
                    ctx.setEditorStatus(error instanceof Error ? error.message : "輸出 MPF 失敗", "error");
                } finally {
                    ctx.setEditorBusy(false);
                }
            });
            exportButton.dataset.bound = "true";
        }

        loadMpfSource();
    }

    function renderLayerSelect() {
        const select = ctx.byId("layer-select");
        if (!select) {
            return;
        }
        select.replaceChildren(
            ...((ctx.state.layers || []).map((layer) => {
                const option = document.createElement("option");
                option.value = String(layer.layer_index);
                option.textContent = `Layer ${layer.layer_index} · Z ${ctx.formatNumber(layer.z_level_mm, 3)} mm`;
                option.selected = Number(layer.layer_index) === Number(ctx.selectedLayerIndex);
                return option;
            })),
        );

        if (!select.dataset.bound) {
            select.addEventListener("change", (event) => {
                ctx.selectedLayerIndex = Number(event.target.value);
                ctx.coordinatePlayback.geometryKey = "";
                if (typeof ctx.resetCoordinatePlayback === "function") {
                    ctx.resetCoordinatePlayback();
                }
                if (typeof ctx.renderDynamicSections === "function") {
                    ctx.renderDynamicSections();
                }
            });
            select.dataset.bound = "true";
        }
    }

    function renderToolbar() {
        const layer = ctx.layerRecord();
        ctx.setText(
            "layer-summary",
            `${ctx.formatInteger(layer?.segment_count)} 段 / ${ctx.formatInteger(layer?.point_count)} 點`,
        );
        const thermalWindow = ctx.state.thermal?.sample_count
            ? `${ctx.state.thermal.start_time} -> ${ctx.state.thermal.end_time}`
            : "尚未上傳熱像資料";
        ctx.setText("thermal-window", thermalWindow);
        scheduleTopBandHeightSync();
    }

    function renderToolbar() {
        const layer = ctx.layerRecord();
        ctx.setText(
            "layer-summary",
            `${ctx.formatInteger(layer?.segment_count)} 段 / ${ctx.formatInteger(layer?.point_count)} 點`,
        );
        const activeWindow = ctx.state.alignment?.thermal_active_window || null;
        const thermalWindow = activeWindow
            ? `${activeWindow.aligned_start_time || activeWindow.start_time || "-"} -> ${activeWindow.aligned_end_time || activeWindow.end_time || "-"}`
            : ctx.state.thermal?.sample_count
                ? `${ctx.state.thermal.start_time} -> ${ctx.state.thermal.end_time}`
                : "目前沒有熱像資料";
        ctx.setText("thermal-window", thermalWindow);
        scheduleTopBandHeightSync();
    }

    return {
        bindFloatingPanelDismiss,
        renderHeader,
        renderOutputSelect,
        renderUploadForm,
        renderMpfEditor,
        renderLayerSelect,
        renderToolbar,
        syncTopBandHeights: scheduleTopBandHeightSync,
    };
}
