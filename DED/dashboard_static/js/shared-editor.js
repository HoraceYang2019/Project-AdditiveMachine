export function setText(byId, id, text) {
    const node = byId(id);
    if (node) {
        node.textContent = text;
    }
}

export function setStatus(byId, text, type = "info") {
    const node = byId("upload-status");
    if (!node) {
        return;
    }
    node.textContent = text;
    node.dataset.status = type;
}

export function setEditorStatus(byId, text, type = "info") {
    const node = byId("mpf-editor-status");
    if (!node) {
        return;
    }
    node.textContent = text;
    node.dataset.status = type;
}

export function normalizeMpfFileName(value, fallbackStem = "edited_output") {
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

export function countEditorLines(text) {
    if (!text) {
        return 0;
    }
    return String(text).split(/\r?\n/).length;
}

export function updateEditorLineCount(ctx, text) {
    ctx.setText("mpf-editor-line-count", `${countEditorLines(text)} 行`);
}

export function setEditorDownloadLink(ctx, url, label, enabled = true) {
    const node = ctx.byId("mpf-editor-download");
    if (!node) {
        return;
    }
    node.textContent = label;
    node.href = enabled && url ? url : "#";
    node.setAttribute("aria-disabled", enabled ? "false" : "true");
}

export function syncEditorControls(ctx) {
    const textArea = ctx.byId("mpf-editor-text");
    const fileNameInput = ctx.byId("mpf-editor-file-name");
    const reloadButton = ctx.byId("mpf-editor-reload");
    const previewButton = ctx.byId("mpf-editor-preview");
    const exportButton = ctx.byId("mpf-editor-export");
    const isBusy = ctx.editor.isBusy;
    const canEdit = ctx.editor.canEdit;

    if (textArea) {
        textArea.disabled = isBusy || !canEdit;
    }
    if (fileNameInput) {
        fileNameInput.disabled = isBusy || !canEdit;
    }
    if (reloadButton) {
        reloadButton.disabled = isBusy || !canEdit;
    }
    if (previewButton) {
        previewButton.disabled = isBusy || !canEdit;
    }
    if (exportButton) {
        exportButton.disabled = isBusy || !canEdit;
    }
}

export function setEditorBusy(ctx, isBusy) {
    ctx.editor.isBusy = Boolean(isBusy);
    syncEditorControls(ctx);
}

export function setEditorEditable(ctx, canEdit) {
    ctx.editor.canEdit = Boolean(canEdit);
    syncEditorControls(ctx);
}
