import { createDashboardContext } from "./shared.js";
import { initControlsSection } from "./controls.js";
import { initInfoSection } from "./info.js";
import { initToolpathSection } from "./toolpath.js";
import { initThermalSection } from "./thermal.js";
import { initAlignmentSection } from "./alignment.js";
import { initCoordinateSection } from "./coordinate.js";

export async function startDashboard() {
    const ctx = await createDashboardContext();

    Object.assign(ctx, initControlsSection(ctx));
    Object.assign(ctx, initInfoSection(ctx));
    Object.assign(ctx, initToolpathSection(ctx));
    Object.assign(ctx, initThermalSection(ctx));
    Object.assign(ctx, initAlignmentSection(ctx));
    Object.assign(ctx, initCoordinateSection(ctx));

    ctx.renderDynamicSections = () => {
        ctx.renderToolbar();
        ctx.renderLayerMetrics();
        ctx.renderSegments();
        ctx.renderToolpath();
        ctx.renderThermal();
        ctx.renderAlignment();
        ctx.renderCoordinateAlignment();
    };

    ctx.renderHeader();
    ctx.renderOutputSelect();
    ctx.renderUploadForm();
    ctx.renderMpfEditor();
    ctx.bindToolpathControls();
    ctx.bindAlignmentControls();
    ctx.bindCoordinatePlaybackControls();
    ctx.bindThermalInteractions();
    ctx.bindAlignmentInteractions();
    ctx.renderLayerSelect();
    ctx.renderDynamicSections();
}
