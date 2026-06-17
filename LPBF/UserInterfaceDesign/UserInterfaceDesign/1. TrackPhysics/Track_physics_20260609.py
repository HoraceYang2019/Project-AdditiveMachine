# -*- coding: utf-8 -*-
"""
Dash NPZ Phase Viewer with Time Slider

版面：
1. 左側：
   - Snapshot Slider
   - 3D NPZ Phase

2. 右側：
   - Melt Pool Dimension Quality / 熔池尺寸品質
   - Solidification Quality / 凝固品質
   - 熔池凝固曲線
   - 熔池長寬深曲線

3. 左側 Navigation Sidebar 可透過 Navbar 三條線按鈕收合。
"""

from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from dash import Dash, dcc, html, Input, Output


# =========================================================
# 1. NPZ 路徑
# =========================================================
NPZ_PREVIEW_PATH = Path(
    r"D:\2026Experiment\2026Experiment0528\thermal_phase_fields_part000.npz"
).resolve()


# =========================================================
# 2. Dash Port
# =========================================================
DASH_PORT = 8074


# =========================================================
# 3. 導覽網址
# =========================================================
APP_URLS = {
    "workspace": "http://127.0.0.1:8071",
    "step1": "http://127.0.0.1:8074",
    "step2": "http://127.0.0.1:8075",
    "step3a": "http://127.0.0.1:8076",
    "step3b": "http://127.0.0.1:8077",
    "step4": "http://127.0.0.1:8078",
}


# =========================================================
# 4. Phase 定義
# =========================================================
PHASE_EMPTY = 0
PHASE_SOLID = 1
PHASE_LIQUID = 2


# =========================================================
# 5. 熔池尺寸品質門檻
# =========================================================
SPOT_SIZE_UM = 50.0

TARGET_LENGTH_UM = 6.0 * SPOT_SIZE_UM
LENGTH_GOOD_TOL = 0.6 * SPOT_SIZE_UM
LENGTH_WARN_TOL = 1.2 * SPOT_SIZE_UM

TARGET_WIDTH_UM = 2.0 * SPOT_SIZE_UM
WIDTH_GOOD_TOL = 0.4 * SPOT_SIZE_UM
WIDTH_WARN_TOL = 0.8 * SPOT_SIZE_UM

DEPTH_GOOD_MIN = 0.8 * SPOT_SIZE_UM
DEPTH_GOOD_MAX = 1.2 * SPOT_SIZE_UM
DEPTH_WARN_MIN = 0.6 * SPOT_SIZE_UM
DEPTH_WARN_MAX = 1.4 * SPOT_SIZE_UM


# =========================================================
# 6. 凝固品質門檻
# =========================================================
SOLIDIFICATION_GOOD_RATIO = 85.0
SOLIDIFICATION_WARN_RATIO = 60.0

LIQUID_GOOD_MAX = 15.0
LIQUID_WARN_MAX = 40.0


# =========================================================
# 7. 顯示設定
# =========================================================
STEP_X = 2
STEP_Y = 1
STEP_Z = 1

SHOW_POWDER_POINTS = True

MAX_POINTS_BY_CLASS = {
    "Powder": 120000,
    "Resolidified Track": 300000,
    "Melt Pool": 300000,
}

GRAPH_CONFIG = {
    "responsive": True,
    "displaylogo": False,
    "scrollZoom": True,
    "doubleClick": "reset",
}


# =========================================================
# 8. 全域快取
# =========================================================
NPZ_INFO = {
    "loaded": False,
    "error": None,
    "num_snapshots": 0,
    "Nx": 0,
    "Ny": 0,
    "Nz": 0,
    "dx_um": 1.0,
    "dy_um": 1.0,
    "dz_um": 1.0,
    "phase_ds": None,
    "meltpool_metrics": None,
    "solidification_metrics": None,
}


# =========================================================
# 9. Sidebar 與主畫面樣式
# =========================================================
SIDEBAR_EXPANDED_STYLE = {
    "width": "240px",
    "top": "56px",
    "left": "0px",
    "height": "calc(100vh - 56px)",
    "position": "fixed",
    "zIndex": 1030,
    "padding": "16px",
    "overflowY": "auto",
    "overflowX": "hidden",
    "backgroundColor": "#222",
    "boxSizing": "border-box",
    "transition": "width 0.25s ease, padding 0.25s ease",
}

SIDEBAR_COLLAPSED_STYLE = {
    "width": "0px",
    "top": "56px",
    "left": "0px",
    "height": "calc(100vh - 56px)",
    "position": "fixed",
    "zIndex": 1030,
    "padding": "0px",
    "overflow": "hidden",
    "backgroundColor": "#222",
    "boxSizing": "border-box",
    "transition": "width 0.25s ease, padding 0.25s ease",
}

MAIN_EXPANDED_STYLE = {
    "marginLeft": "260px",
    "width": "calc(100% - 260px)",
    "minHeight": "calc(100vh - 56px)",
    "padding": "5px 12px 16px 12px",
    "overflowX": "hidden",
    "boxSizing": "border-box",
    "transition": "margin-left 0.25s ease, width 0.25s ease",
}

MAIN_COLLAPSED_STYLE = {
    "marginLeft": "0px",
    "width": "100%",
    "minHeight": "calc(100vh - 56px)",
    "padding": "5px 12px 16px 12px",
    "overflowX": "hidden",
    "boxSizing": "border-box",
    "transition": "margin-left 0.25s ease, width 0.25s ease",
}


# =========================================================
# 10. 基本工具
# =========================================================
def clamp_snapshot_index(snapshot_idx, num_snapshots):
    if num_snapshots <= 0:
        return 0

    if snapshot_idx is None:
        return 0

    snapshot_idx = int(snapshot_idx)

    if snapshot_idx < 0:
        snapshot_idx = num_snapshots + snapshot_idx

    return max(0, min(snapshot_idx, num_snapshots - 1))


def sample_indices(indices, max_points):
    if indices is None or len(indices) == 0:
        return indices

    if len(indices) <= max_points:
        return indices

    pick = np.linspace(
        0,
        len(indices) - 1,
        int(max_points),
        dtype=np.int64,
    )

    return indices[pick]


def mask_to_xyz(mask, dx_um, dy_um, dz_um, max_points):
    indices = np.argwhere(mask)

    if indices.size == 0:
        return [], [], [], 0, 0

    raw_count = int(indices.shape[0])
    indices = sample_indices(indices, max_points)

    x = (indices[:, 0] + 0.5) * dx_um
    y = (indices[:, 1] + 0.5) * dy_um
    z = (indices[:, 2] + 0.5) * dz_um

    return x, y, z, raw_count, int(indices.shape[0])


def compute_extent_um(mask, axis, pitch_um):
    """
    Dimension =
        (max_index - min_index + 1) × pitch_um
    """
    indices = np.argwhere(mask)

    if indices.size == 0:
        return 0.0

    min_idx = int(indices[:, axis].min())
    max_idx = int(indices[:, axis].max())

    return float((max_idx - min_idx + 1) * pitch_um)


# =========================================================
# 11. 熔池長寬深計算
# =========================================================
def compute_all_meltpool_metrics(phase_ds, dx_um, dy_um, dz_um):
    nt = phase_ds.shape[0]

    lengths = np.zeros(nt, dtype=np.float64)
    widths = np.zeros(nt, dtype=np.float64)
    depths = np.zeros(nt, dtype=np.float64)

    for i in range(nt):
        liquid_mask = phase_ds[i] == PHASE_LIQUID

        if not np.any(liquid_mask):
            continue

        lengths[i] = compute_extent_um(
            liquid_mask,
            axis=0,
            pitch_um=dx_um,
        )

        widths[i] = compute_extent_um(
            liquid_mask,
            axis=1,
            pitch_um=dy_um,
        )

        depths[i] = compute_extent_um(
            liquid_mask,
            axis=2,
            pitch_um=dz_um,
        )

    return {
        "length_um": lengths,
        "width_um": widths,
        "depth_um": depths,
    }


# =========================================================
# 12. 熔池凝固指標
# =========================================================
def compute_all_solidification_metrics(phase_ds):
    nt = phase_ds.shape[0]

    solidification_ratio = np.zeros(nt, dtype=np.float64)
    liquid_ratio = np.zeros(nt, dtype=np.float64)

    resolidified_count = np.zeros(nt, dtype=np.int64)
    liquid_count = np.zeros(nt, dtype=np.int64)
    melted_region_count = np.zeros(nt, dtype=np.int64)

    ever_melted_mask = np.zeros(
        phase_ds.shape[1:],
        dtype=bool,
    )

    for i in range(nt):
        phase_now = phase_ds[i]

        liquid_mask = phase_now == PHASE_LIQUID
        ever_melted_mask |= liquid_mask

        solid_mask = phase_now == PHASE_SOLID
        resolidified_mask = solid_mask & ever_melted_mask

        melted_region_mask = resolidified_mask | liquid_mask

        r_count = int(np.count_nonzero(resolidified_mask))
        l_count = int(np.count_nonzero(liquid_mask))
        total_count = int(np.count_nonzero(melted_region_mask))

        resolidified_count[i] = r_count
        liquid_count[i] = l_count
        melted_region_count[i] = total_count

        if total_count > 0:
            solidification_ratio[i] = (
                r_count / total_count * 100.0
            )

            liquid_ratio[i] = (
                l_count / total_count * 100.0
            )

    return {
        "solidification_ratio": solidification_ratio,
        "liquid_ratio": liquid_ratio,
        "resolidified_count": resolidified_count,
        "liquid_count": liquid_count,
        "melted_region_count": melted_region_count,
    }


# =========================================================
# 13. 品質判斷
# =========================================================
def evaluate_range_by_target(value, target, good_tol, warn_tol):
    diff = abs(value - target)

    if diff <= good_tol:
        return "Good", "success", "green"

    if diff <= warn_tol:
        return "Warning", "warning", "yellow"

    return "Bad", "danger", "red"


def evaluate_depth_status(depth_um):
    if DEPTH_GOOD_MIN <= depth_um <= DEPTH_GOOD_MAX:
        return "Good", "success", "green"

    if DEPTH_WARN_MIN <= depth_um <= DEPTH_WARN_MAX:
        return "Warning", "warning", "yellow"

    return "Bad", "danger", "red"


def get_meltpool_status(length_um, width_um, depth_um):
    length_status = evaluate_range_by_target(
        length_um,
        TARGET_LENGTH_UM,
        LENGTH_GOOD_TOL,
        LENGTH_WARN_TOL,
    )

    width_status = evaluate_range_by_target(
        width_um,
        TARGET_WIDTH_UM,
        WIDTH_GOOD_TOL,
        WIDTH_WARN_TOL,
    )

    depth_status = evaluate_depth_status(depth_um)

    return length_status, width_status, depth_status


def evaluate_solidification_status(
    solidification_ratio,
    liquid_ratio,
    melted_region_count,
):
    if melted_region_count <= 0:
        return "No Melted Region", "secondary", "#808080"

    if (
        solidification_ratio >= SOLIDIFICATION_GOOD_RATIO
        and liquid_ratio <= LIQUID_GOOD_MAX
    ):
        return "Stable Solidification", "success", "green"

    if (
        solidification_ratio >= SOLIDIFICATION_WARN_RATIO
        and liquid_ratio <= LIQUID_WARN_MAX
    ):
        return "Partial Solidification", "warning", "yellow"

    return "Unstable / Still Liquid", "danger", "red"


# =========================================================
# 14. NPZ 讀取
# =========================================================
def load_npz_to_cache():
    global NPZ_INFO

    if NPZ_INFO["loaded"]:
        return NPZ_INFO

    if not NPZ_PREVIEW_PATH.exists():
        NPZ_INFO["error"] = f"找不到 NPZ：{NPZ_PREVIEW_PATH}"
        return NPZ_INFO

    try:
        with np.load(NPZ_PREVIEW_PATH) as data:
            if "phase" not in data.files:
                NPZ_INFO["error"] = "NPZ 裡面找不到 phase 欄位"
                return NPZ_INFO

            phase = data["phase"]

            if phase.ndim != 4:
                NPZ_INFO["error"] = (
                    f"phase 不是 4D，現在 shape = {phase.shape}"
                )
                return NPZ_INFO

            nt, nx, ny, nz = phase.shape

            dx_um = (
                float(data["dx"]) * 1e6
                if "dx" in data.files
                else 1.0
            )

            dy_um = (
                float(data["dy"]) * 1e6
                if "dy" in data.files
                else 1.0
            )

            dz_um = (
                float(data["dz"]) * 1e6
                if "dz" in data.files
                else 1.0
            )

            phase_ds = phase[
                :,
                ::STEP_X,
                ::STEP_Y,
                ::STEP_Z,
            ].copy()

            meltpool_metrics = compute_all_meltpool_metrics(
                phase_ds=phase_ds,
                dx_um=dx_um * STEP_X,
                dy_um=dy_um * STEP_Y,
                dz_um=dz_um * STEP_Z,
            )

            solidification_metrics = compute_all_solidification_metrics(
                phase_ds
            )

            NPZ_INFO.update(
                {
                    "loaded": True,
                    "error": None,
                    "num_snapshots": int(nt),
                    "Nx": int(nx),
                    "Ny": int(ny),
                    "Nz": int(nz),
                    "dx_um": dx_um,
                    "dy_um": dy_um,
                    "dz_um": dz_um,
                    "phase_ds": phase_ds,
                    "meltpool_metrics": meltpool_metrics,
                    "solidification_metrics": solidification_metrics,
                }
            )

            print("成功讀取 NPZ")
            print(f"NPZ path：{NPZ_PREVIEW_PATH}")
            print(f"phase shape：{phase.shape}")
            print(f"phase_ds shape：{phase_ds.shape}")
            print(
                f"dx={dx_um:.3f} µm, "
                f"dy={dy_um:.3f} µm, "
                f"dz={dz_um:.3f} µm"
            )

            return NPZ_INFO

    except Exception as error:
        NPZ_INFO["error"] = f"NPZ 讀取失敗：{error}"
        return NPZ_INFO


# =========================================================
# 15. Phase 分類
# =========================================================
def compute_class_masks(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return None, None, None, None, snapshot_idx

    phase_ds = info["phase_ds"]
    nt = phase_ds.shape[0]

    snapshot_idx = clamp_snapshot_index(snapshot_idx, nt)

    phase_now = phase_ds[snapshot_idx]
    phase_history = phase_ds[: snapshot_idx + 1]

    solid_mask = phase_now == PHASE_SOLID
    liquid_mask = phase_now == PHASE_LIQUID

    ever_melted_mask = np.any(
        phase_history == PHASE_LIQUID,
        axis=0,
    )

    mask_powder = solid_mask & (~ever_melted_mask)
    mask_resolidified = solid_mask & ever_melted_mask
    mask_liquid = liquid_mask.copy()

    return (
        phase_now,
        mask_powder,
        mask_resolidified,
        mask_liquid,
        snapshot_idx,
    )


# =========================================================
# 16. UI 工具
# =========================================================
def make_empty_figure(message, height=650):
    fig = go.Figure()

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111",
        plot_bgcolor="#111",
        height=height,
        margin=dict(l=2, r=2, t=45, b=2),
    )

    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=18),
    )

    return fig


def make_quality_card(
    title,
    value,
    subtitle,
    color,
    icon="bi-activity",
):
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        [
                            html.I(
                                className=f"bi {icon} me-2"
                            ),
                            html.Span(
                                title,
                                className="fw-bold",
                            ),
                        ],
                        className="d-flex align-items-center mb-2",
                        style={"fontSize": "14px"},
                    ),

                    html.Div(
                        value,
                        className="fw-bold",
                        style={
                            "fontSize": "26px",
                            "lineHeight": "1.15",
                            "letterSpacing": "0.5px",
                        },
                    ),

                    html.Div(
                        subtitle,
                        className="mt-2",
                        style={
                            "fontSize": "12px",
                            "opacity": "0.9",
                            "lineHeight": "1.4",
                        },
                    ),
                ]
            ),
            color=color,
            inverse=True,
            className="shadow-sm border-0",
            style={
                "borderRadius": "14px",
                "minHeight": "145px",
            },
        ),
        xl=4,
        lg=12,
        md=4,
        sm=12,
        className="mb-2",
    )


# =========================================================
# 17. 熔池尺寸品質
# =========================================================
def make_meltpool_summary_cards(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return dbc.Alert(
            info["error"],
            color="danger",
            className="mt-2",
        )

    nt = info["phase_ds"].shape[0]
    snapshot_idx = clamp_snapshot_index(snapshot_idx, nt)

    metrics = info["meltpool_metrics"]

    length_um = float(metrics["length_um"][snapshot_idx])
    width_um = float(metrics["width_um"][snapshot_idx])
    depth_um = float(metrics["depth_um"][snapshot_idx])

    has_liquid = (
        length_um > 0
        and width_um > 0
        and depth_um > 0
    )

    abnormal_notes = []
    correction_notes = []

    if not has_liquid:
        length_value = "N/A"
        width_value = "N/A"
        depth_value = "N/A"

        length_card_color = "secondary"
        width_card_color = "secondary"
        depth_card_color = "secondary"

        length_subtitle = "No Liquid｜目前沒有液態熔池"
        width_subtitle = "No Liquid｜目前沒有液態熔池"
        depth_subtitle = "No Liquid｜目前沒有液態熔池"

        abnormal_color = "secondary"

        abnormal_notes.append(
            "目前 Snapshot 沒有明顯液態熔池，因此無法判斷"
            "熔池長度、寬度與深度是否符合目標。"
        )

        abnormal_notes.append(
            "可能原因包含：雷射尚未作用、目前時間點已完成凝固，"
            "或 phase 資料中沒有 Liquid = 2 的區域。"
        )

        correction_notes.append(
            "確認目前 Snapshot 是否位於雷射作用時間內，"
            "並檢查 3D 圖中是否存在橘色 Liquid 熔池。"
        )

        correction_notes.append(
            "若整段製程皆無液態熔池，可提高雷射功率 P，"
            "或降低掃描速度 v。"
        )

        correction_notes.append(
            "若這是掃描結束後的 Snapshot，沒有液態熔池可能代表"
            "熔池已完成凝固，屬於合理現象。"
        )

    else:
        length_value = f"{length_um:.2f} µm"
        width_value = f"{width_um:.2f} µm"
        depth_value = f"{depth_um:.2f} µm"

        (
            length_status,
            width_status,
            depth_status,
        ) = get_meltpool_status(
            length_um,
            width_um,
            depth_um,
        )

        length_text, length_card_color, _ = length_status
        width_text, width_card_color, _ = width_status
        depth_text, depth_card_color, _ = depth_status

        length_subtitle = (
            f"{length_text}｜Target "
            f"{TARGET_LENGTH_UM:.0f} ± "
            f"{LENGTH_GOOD_TOL:.0f} µm"
        )

        width_subtitle = (
            f"{width_text}｜Target "
            f"{TARGET_WIDTH_UM:.0f} ± "
            f"{WIDTH_GOOD_TOL:.0f} µm"
        )

        depth_subtitle = (
            f"{depth_text}｜Good "
            f"{DEPTH_GOOD_MIN:.0f}–"
            f"{DEPTH_GOOD_MAX:.0f} µm"
        )

        # Length
        if length_text == "Bad":
            if length_um < TARGET_LENGTH_UM - LENGTH_WARN_TOL:
                abnormal_notes.append(
                    f"熔池長度過短：Length = {length_um:.2f} µm。"
                    "可能是雷射功率不足、掃描速度過快或熱輸入不足。"
                )

                abnormal_notes.append(
                    "長度過短可能造成熔道不連續，增加熔合不足風險。"
                )

                correction_notes.append(
                    "提高雷射功率 P，或降低掃描速度 v。"
                )

            elif length_um > TARGET_LENGTH_UM + LENGTH_WARN_TOL:
                abnormal_notes.append(
                    f"熔池長度過長：Length = {length_um:.2f} µm。"
                    "可能是雷射功率偏高、掃描速度過慢或熱累積過高。"
                )

                correction_notes.append(
                    "降低雷射功率 P，或提高掃描速度 v。"
                )

        elif length_text == "Warning":
            abnormal_notes.append(
                f"熔池長度進入警告範圍："
                f"Length = {length_um:.2f} µm。"
            )

            correction_notes.append(
                "先觀察後續 Snapshot，若持續偏離，再小幅調整 P 或 v。"
            )

        # Width
        if width_text == "Bad":
            if width_um < TARGET_WIDTH_UM - WIDTH_WARN_TOL:
                abnormal_notes.append(
                    f"熔池寬度過窄：Width = {width_um:.2f} µm。"
                    "相鄰熔道可能出現重疊不足。"
                )

                correction_notes.append(
                    "提高 P、降低 v，或小幅降低掃描間距 h。"
                )

            elif width_um > TARGET_WIDTH_UM + WIDTH_WARN_TOL:
                abnormal_notes.append(
                    f"熔池寬度過寬：Width = {width_um:.2f} µm。"
                    "可能有橫向熱擴散過強或熱累積問題。"
                )

                correction_notes.append(
                    "降低 P、提高 v，或小幅增加掃描間距 h。"
                )

        elif width_text == "Warning":
            abnormal_notes.append(
                f"熔池寬度進入警告範圍："
                f"Width = {width_um:.2f} µm。"
            )

            correction_notes.append(
                "先小幅調整掃描速度 v，避免一次大幅修改 P。"
            )

        # Depth
        if depth_text == "Bad":
            if depth_um < DEPTH_WARN_MIN:
                abnormal_notes.append(
                    f"熔池深度過淺：Depth = {depth_um:.2f} µm。"
                    "可能造成層間熔合不足。"
                )

                correction_notes.append(
                    "提高 P、降低 v，或降低層厚 t。"
                )

            elif depth_um > DEPTH_WARN_MAX:
                abnormal_notes.append(
                    f"熔池深度過深：Depth = {depth_um:.2f} µm。"
                    "可能有 Keyhole 深熔風險。"
                )

                correction_notes.append(
                    "降低 P 或提高 v，避免能量過度集中。"
                )

        elif depth_text == "Warning":
            abnormal_notes.append(
                f"熔池深度進入警告範圍："
                f"Depth = {depth_um:.2f} µm。"
            )

            correction_notes.append(
                "小幅調整 P 或 v，並觀察後續深度變化。"
            )

        if not abnormal_notes:
            abnormal_notes.append(
                "目前熔池長度、寬度與深度皆在可接受範圍內。"
            )

        if not correction_notes:
            correction_notes.append(
                "目前尺寸狀態正常，建議維持 P、v、h、t。"
            )

        abnormal_color = "success"

        if (
            length_text == "Bad"
            or width_text == "Bad"
            or depth_text == "Bad"
        ):
            abnormal_color = "danger"

        elif (
            length_text == "Warning"
            or width_text == "Warning"
            or depth_text == "Warning"
        ):
            abnormal_color = "warning"

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.I(
                                className="bi bi-rulers me-2"
                            ),
                            html.Span(
                                "Melt Pool Dimension Quality / 熔池尺寸品質"
                            ),
                        ],
                        className="fw-bold",
                        style={"fontSize": "20px"},
                    ),

                    html.Div(
                        f"Snapshot：{snapshot_idx}",
                        className="text-white-50",
                        style={"fontSize": "13px"},
                    ),
                ],
                className=(
                    "d-flex justify-content-between "
                    "align-items-end mb-2"
                ),
            ),

            dbc.Row(
                [
                    make_quality_card(
                        title="Length / 長度",
                        value=length_value,
                        subtitle=length_subtitle,
                        color=length_card_color,
                        icon="bi-arrows-expand",
                    ),

                    make_quality_card(
                        title="Width / 寬度",
                        value=width_value,
                        subtitle=width_subtitle,
                        color=width_card_color,
                        icon="bi-arrows",
                    ),

                    make_quality_card(
                        title="Depth / 深度",
                        value=depth_value,
                        subtitle=depth_subtitle,
                        color=depth_card_color,
                        icon="bi-arrow-down-up",
                    ),
                ],
                className="g-2",
            ),

            dbc.Alert(
                [
                    html.Div(
                        [
                            html.I(
                                className=(
                                    "bi bi-exclamation-triangle me-2"
                                )
                            ),
                            html.Span(
                                "異常說明"
                            ),
                        ],
                        className="fw-bold mb-2",
                    ),

                    html.Ul(
                        [
                            html.Li(note)
                            for note in abnormal_notes
                        ],
                        className="mb-0",
                        style={
                            "fontSize": "13px",
                            "lineHeight": "1.65",
                            "paddingLeft": "20px",
                        },
                    ),

                    html.Hr(),

                    html.Div(
                        [
                            html.I(
                                className="bi bi-tools me-2"
                            ),
                            html.Span(
                                "修改方案"
                            ),
                        ],
                        className="fw-bold mb-2",
                    ),

                    html.Ul(
                        [
                            html.Li(note)
                            for note in correction_notes
                        ],
                        className="mb-0",
                        style={
                            "fontSize": "13px",
                            "lineHeight": "1.65",
                            "paddingLeft": "20px",
                        },
                    ),
                ],
                color=abnormal_color,
                className="mt-1 mb-1",
                style={
                    "borderRadius": "12px",
                },
            ),
        ],
        style={
            "width": "96%",
            "margin": "8px auto 0 auto",
            "padding": "12px",
            "backgroundColor": "#1b1b1b",
            "borderRadius": "14px",
            "border": (
                "1px solid rgba(255,255,255,0.08)"
            ),
        },
    )


# =========================================================
# 18. 凝固品質
# =========================================================
def make_solidification_summary_cards(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return dbc.Alert(
            info["error"],
            color="danger",
            className="mt-2",
        )

    nt = info["phase_ds"].shape[0]
    snapshot_idx = clamp_snapshot_index(snapshot_idx, nt)

    metrics = info["solidification_metrics"]

    solidification_ratio = float(
        metrics["solidification_ratio"][snapshot_idx]
    )

    liquid_ratio = float(
        metrics["liquid_ratio"][snapshot_idx]
    )

    resolidified_count = int(
        metrics["resolidified_count"][snapshot_idx]
    )

    liquid_count = int(
        metrics["liquid_count"][snapshot_idx]
    )

    melted_region_count = int(
        metrics["melted_region_count"][snapshot_idx]
    )

    status_text, status_color, _ = evaluate_solidification_status(
        solidification_ratio,
        liquid_ratio,
        melted_region_count,
    )

    abnormal_notes = []
    correction_notes = []

    if melted_region_count <= 0:
        ratio_value = "N/A"
        liquid_value = "N/A"

        abnormal_notes.append(
            "目前沒有偵測到曾經熔化的區域，因此無法判斷凝固品質。"
        )

        correction_notes.append(
            "確認目前 Snapshot 是否位於雷射作用期間。"
        )

        correction_notes.append(
            "若整段製程皆無熔化區域，可提高 P 或降低 v。"
        )

    else:
        ratio_value = f"{solidification_ratio:.2f}%"
        liquid_value = f"{liquid_ratio:.2f}%"

        if status_text == "Stable Solidification":
            abnormal_notes.append(
                "目前大部分熔化區域已重新凝固，凝固狀態良好。"
            )

            correction_notes.append(
                "建議維持目前 P、v、h、t。"
            )

        elif status_text == "Partial Solidification":
            abnormal_notes.append(
                f"目前為部分凝固：凝固比例 "
                f"{solidification_ratio:.2f}%，液態比例 "
                f"{liquid_ratio:.2f}%。"
            )

            abnormal_notes.append(
                "熔池仍有部分液態區域，建議觀察後續 Snapshot。"
            )

            correction_notes.append(
                "若液態比例持續偏高，可小幅降低 P 或提高 v。"
            )

            correction_notes.append(
                "亦可延長冷卻時間或提高散熱能力。"
            )

        else:
            abnormal_notes.append(
                f"凝固狀態不佳：凝固比例 "
                f"{solidification_ratio:.2f}%，液態比例 "
                f"{liquid_ratio:.2f}%。"
            )

            correction_notes.append(
                "降低 P 或提高 v，避免熔池長時間維持液態。"
            )

            if liquid_count > resolidified_count:
                abnormal_notes.append(
                    "目前液態區域數量大於重新凝固區域。"
                )

                correction_notes.append(
                    "檢查局部熱累積與掃描路徑是否過度集中。"
                )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.I(
                                className="bi bi-snow2 me-2"
                            ),
                            html.Span(
                                "Solidification Quality / 凝固品質"
                            ),
                        ],
                        className="fw-bold",
                        style={"fontSize": "20px"},
                    ),

                    html.Div(
                        f"Snapshot：{snapshot_idx}",
                        className="text-white-50",
                        style={"fontSize": "13px"},
                    ),
                ],
                className=(
                    "d-flex justify-content-between "
                    "align-items-end mb-2"
                ),
            ),

            dbc.Row(
                [
                    make_quality_card(
                        title="Solidification Ratio / 凝固比例",
                        value=ratio_value,
                        subtitle=(
                            "Resolidified / "
                            "(Resolidified + Liquid)"
                        ),
                        color=status_color,
                        icon="bi-check-circle",
                    ),

                    make_quality_card(
                        title="Liquid Ratio / 液態比例",
                        value=liquid_value,
                        subtitle=(
                            f"Liquid Count = {liquid_count:,}"
                        ),
                        color=status_color,
                        icon="bi-droplet",
                    ),

                    make_quality_card(
                        title="Status / 凝固狀態",
                        value=status_text,
                        subtitle=(
                            f"Resolidified = "
                            f"{resolidified_count:,}"
                        ),
                        color=status_color,
                        icon="bi-clipboard-data",
                    ),
                ],
                className="g-2",
            ),

            dbc.Alert(
                [
                    html.Div(
                        [
                            html.I(
                                className=(
                                    "bi bi-exclamation-triangle me-2"
                                )
                            ),
                            html.Span("異常說明"),
                        ],
                        className="fw-bold mb-2",
                    ),

                    html.Ul(
                        [
                            html.Li(note)
                            for note in abnormal_notes
                        ],
                        className="mb-0",
                        style={
                            "fontSize": "13px",
                            "lineHeight": "1.65",
                            "paddingLeft": "20px",
                        },
                    ),

                    html.Hr(),

                    html.Div(
                        [
                            html.I(
                                className="bi bi-tools me-2"
                            ),
                            html.Span("修改方案"),
                        ],
                        className="fw-bold mb-2",
                    ),

                    html.Ul(
                        [
                            html.Li(note)
                            for note in correction_notes
                        ],
                        className="mb-0",
                        style={
                            "fontSize": "13px",
                            "lineHeight": "1.65",
                            "paddingLeft": "20px",
                        },
                    ),
                ],
                color=status_color,
                className="mt-1 mb-1",
                style={
                    "borderRadius": "12px",
                },
            ),
        ],
        style={
            "width": "96%",
            "margin": "10px auto 0 auto",
            "padding": "12px",
            "backgroundColor": "#1b1b1b",
            "borderRadius": "14px",
            "border": (
                "1px solid rgba(255,255,255,0.08)"
            ),
        },
    )


# =========================================================
# 19. 凝固曲線
# =========================================================
def make_solidification_curve_figure(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return make_empty_figure(
            f"⚠️ {info['error']}",
            height=350,
        )

    nt = info["phase_ds"].shape[0]
    snapshot_idx = clamp_snapshot_index(snapshot_idx, nt)

    metrics = info["solidification_metrics"]

    x = np.arange(nt)

    solidification_ratio = metrics["solidification_ratio"]
    liquid_ratio = metrics["liquid_ratio"]

    current_solidification = float(
        solidification_ratio[snapshot_idx]
    )

    current_total = int(
        metrics["melted_region_count"][snapshot_idx]
    )

    status_text, _, quality_color = evaluate_solidification_status(
        current_solidification,
        float(liquid_ratio[snapshot_idx]),
        current_total,
    )

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=x,
            y=solidification_ratio,
            mode="lines",
            name="Solidification Ratio",
            line=dict(
                color="#00CED1",
                width=3,
            ),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=liquid_ratio,
            mode="lines",
            name="Liquid Ratio",
            line=dict(
                color="#DA70D6",
                width=3,
                dash="dash",
            ),
        )
    )

    fig.add_vline(
        x=snapshot_idx,
        line_width=2,
        line_dash="dash",
        line_color="white",
    )

    if current_total > 0:
        fig.add_trace(
            go.Scatter(
                x=[snapshot_idx],
                y=[current_solidification],
                mode="markers+text",
                name=status_text,
                marker=dict(
                    color=quality_color,
                    size=13,
                    symbol="diamond",
                    line=dict(
                        color="white",
                        width=1,
                    ),
                ),
                text=[status_text],
                textposition="top center",
            )
        )

    fig.add_hline(
        y=SOLIDIFICATION_GOOD_RATIO,
        line_width=1,
        line_dash="dash",
        line_color="#888888",
        annotation_text="Stable ≥ 85%",
        annotation_position="top left",
    )

    fig.add_hline(
        y=SOLIDIFICATION_WARN_RATIO,
        line_width=1,
        line_dash="dot",
        line_color="#888888",
        annotation_text="Partial ≥ 60%",
        annotation_position="bottom left",
    )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111",
        plot_bgcolor="#111",
        height=350,
        margin=dict(
            l=45,
            r=15,
            t=55,
            b=45,
        ),
        title=(
            f"Melt Pool Solidification Curve - "
            f"Snapshot {snapshot_idx}"
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1.0,
        ),
        xaxis=dict(
            title="Snapshot / Time",
            gridcolor="#333",
        ),
        yaxis=dict(
            title="Ratio (%)",
            range=[0, 105],
            gridcolor="#333",
        ),
        hovermode="x unified",
    )

    return fig


# =========================================================
# 20. 熔池尺寸曲線
# =========================================================
def make_meltpool_curve_figure(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return make_empty_figure(
            f"⚠️ {info['error']}",
            height=400,
        )

    nt = info["phase_ds"].shape[0]
    snapshot_idx = clamp_snapshot_index(snapshot_idx, nt)

    metrics = info["meltpool_metrics"]

    x = np.arange(nt)

    lengths = metrics["length_um"]
    widths = metrics["width_um"]
    depths = metrics["depth_um"]

    current_length = float(lengths[snapshot_idx])
    current_width = float(widths[snapshot_idx])
    current_depth = float(depths[snapshot_idx])

    has_liquid = (
        current_length > 0
        and current_width > 0
        and current_depth > 0
    )

    if has_liquid:
        (
            length_status,
            width_status,
            depth_status,
        ) = get_meltpool_status(
            current_length,
            current_width,
            current_depth,
        )

        length_text, _, length_color = length_status
        width_text, _, width_color = width_status
        depth_text, _, depth_color = depth_status

    else:
        length_text = "No Liquid"
        width_text = "No Liquid"
        depth_text = "No Liquid"

        length_color = "#808080"
        width_color = "#808080"
        depth_color = "#808080"

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=x,
            y=lengths,
            mode="lines",
            name="Length",
            line=dict(
                color="#00BFFF",
                width=3,
            ),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=widths,
            mode="lines",
            name="Width",
            line=dict(
                color="#A020F0",
                width=3,
                dash="dash",
            ),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=depths,
            mode="lines",
            name="Depth",
            line=dict(
                color="#FF8C00",
                width=3,
                dash="dot",
            ),
        )
    )

    fig.add_vline(
        x=snapshot_idx,
        line_width=2,
        line_dash="dash",
        line_color="white",
    )

    if has_liquid:
        fig.add_trace(
            go.Scatter(
                x=[snapshot_idx],
                y=[current_length],
                mode="markers+text",
                name=f"Length {length_text}",
                marker=dict(
                    color=length_color,
                    size=12,
                    symbol="diamond",
                ),
                text=[f"Length {length_text}"],
                textposition="top center",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=[snapshot_idx],
                y=[current_width],
                mode="markers+text",
                name=f"Width {width_text}",
                marker=dict(
                    color=width_color,
                    size=12,
                    symbol="diamond",
                ),
                text=[f"Width {width_text}"],
                textposition="top center",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=[snapshot_idx],
                y=[current_depth],
                mode="markers+text",
                name=f"Depth {depth_text}",
                marker=dict(
                    color=depth_color,
                    size=12,
                    symbol="diamond",
                ),
                text=[f"Depth {depth_text}"],
                textposition="top center",
            )
        )

    fig.add_hline(
        y=TARGET_LENGTH_UM,
        line_width=1,
        line_dash="dash",
        line_color="#00BFFF",
        annotation_text="Length Target",
        annotation_position="top left",
    )

    fig.add_hline(
        y=TARGET_WIDTH_UM,
        line_width=1,
        line_dash="dash",
        line_color="#A020F0",
        annotation_text="Width Target",
        annotation_position="bottom left",
    )

    fig.add_hrect(
        y0=DEPTH_GOOD_MIN,
        y1=DEPTH_GOOD_MAX,
        fillcolor="#FF8C00",
        opacity=0.10,
        line_width=0,
        annotation_text="Depth Good Range",
        annotation_position="top right",
    )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111",
        plot_bgcolor="#111",
        height=400,
        margin=dict(
            l=45,
            r=15,
            t=55,
            b=45,
        ),
        title=(
            f"Melt Pool Dimension Curve - "
            f"Snapshot {snapshot_idx}"
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1.0,
        ),
        xaxis=dict(
            title="Snapshot / Time",
            gridcolor="#333",
        ),
        yaxis=dict(
            title="Dimension (µm)",
            gridcolor="#333",
        ),
        hovermode="x unified",
    )

    return fig


# =========================================================
# 21. 3D NPZ 圖
# =========================================================
def make_npz_3d_figure(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return make_empty_figure(
            f"⚠️ {info['error']}"
        )

    nt = info["phase_ds"].shape[0]

    (
        phase_now,
        mask_powder,
        mask_resolidified,
        mask_liquid,
        snapshot_idx,
    ) = compute_class_masks(snapshot_idx)

    if phase_now is None:
        return make_empty_figure(
            "⚠️ 無法產生 phase mask"
        )

    dx_um = info["dx_um"] * STEP_X
    dy_um = info["dy_um"] * STEP_Y
    dz_um = info["dz_um"] * STEP_Z

    nx, ny, nz = phase_now.shape

    fig = go.Figure()

    masks = {
        "Powder": mask_powder,
        "Resolidified Track": mask_resolidified,
        "Melt Pool": mask_liquid,
    }

    if not SHOW_POWDER_POINTS:
        masks.pop("Powder", None)

    styles = {
        "Powder": {
            "color": "royalblue",
            "opacity": 0.08,
            "size": 1.4,
        },

        "Resolidified Track": {
            "color": "limegreen",
            "opacity": 0.80,
            "size": 3.0,
        },

        "Melt Pool": {
            "color": "orangered",
            "opacity": 1.0,
            "size": 4.5,
        },
    }

    display_summary = []

    for name, mask in masks.items():
        max_points = MAX_POINTS_BY_CLASS.get(
            name,
            100000,
        )

        (
            x,
            y,
            z,
            raw_count,
            shown_count,
        ) = mask_to_xyz(
            mask,
            dx_um,
            dy_um,
            dz_um,
            max_points,
        )

        display_summary.append(
            f"{name}: {shown_count:,}/{raw_count:,}"
        )

        if len(x) == 0:
            continue

        style = styles[name]

        fig.add_trace(
            go.Scatter3d(
                x=x,
                y=y,
                z=z,
                mode="markers",
                name=(
                    f"{name} "
                    f"({shown_count:,}/{raw_count:,})"
                ),
                marker=dict(
                    size=style["size"],
                    color=style["color"],
                    opacity=style["opacity"],
                ),
            )
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111",
        plot_bgcolor="#111",
        height=720,
        margin=dict(
            l=2,
            r=2,
            t=60,
            b=2,
        ),
        title=(
            f"3D NPZ Phase Preview - "
            f"Snapshot {snapshot_idx} / {nt - 1}<br>"
            f"dx={info['dx_um']:.2f}, "
            f"dy={info['dy_um']:.2f}, "
            f"dz={info['dz_um']:.2f} µm | "
            f"{' | '.join(display_summary)}"
        ),
        legend=dict(
            x=0.02,
            y=0.98,
            bgcolor="rgba(0,0,0,0.35)",
        ),
        uirevision="keep-camera",
        scene=dict(
            camera=dict(
                eye=dict(
                    x=2.0,
                    y=2.0,
                    z=1.4,
                )
            ),

            xaxis=dict(
                title="X (µm)",
                range=[0, nx * dx_um],
                backgroundcolor="black",
                gridcolor="#444",
                zerolinecolor="#777",
            ),

            yaxis=dict(
                title="Y (µm)",
                range=[0, ny * dy_um],
                backgroundcolor="black",
                gridcolor="#444",
                zerolinecolor="#777",
            ),

            zaxis=dict(
                title="Z (µm)",
                range=[0, nz * dz_um],
                backgroundcolor="black",
                gridcolor="#444",
                zerolinecolor="#777",
            ),

            aspectmode="data",
        ),
    )

    return fig


# =========================================================
# 22. Dash App
# =========================================================
app = Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.DARKLY,
        (
            "https://cdn.jsdelivr.net/npm/"
            "bootstrap-icons@1.11.3/"
            "font/bootstrap-icons.css"
        ),
    ],
    suppress_callback_exceptions=True,
    meta_tags=[
        {
            "name": "viewport",
            "content": (
                "width=device-width, initial-scale=1"
            ),
        }
    ],
)

app.title = "Track Physics NPZ Dash"


# =========================================================
# 23. Navbar
# =========================================================
navbar = dbc.Navbar(
    dbc.Container(
        [
            html.Div(
                [
                    dbc.Button(
                        html.I(
                            className="bi bi-list",
                            style={
                                "fontSize": "30px",
                                "lineHeight": "1",
                            },
                        ),
                        id="sidebar-toggle",
                        n_clicks=0,
                        color="link",
                        title="展開／收合側欄",
                        style={
                            "width": "42px",
                            "height": "40px",
                            "padding": "0px",
                            "marginRight": "10px",
                            "border": "none",
                            "borderRadius": "8px",
                            "boxShadow": "none",
                            "color": "#FFFFFF",
                            "textDecoration": "none",
                            "display": "flex",
                            "alignItems": "center",
                            "justifyContent": "center",
                        },
                    ),

                    html.I(
                        className="bi bi-cpu me-2",
                        style={
                            "fontSize": "20px",
                        },
                    ),

                    html.Span(
                        "Track Physics - NPZ Phase Viewer",
                        className="h5 mb-0",
                    ),
                ],
                className="d-flex align-items-center",
            ),
        ],
        fluid=True,
        className=(
            "d-flex justify-content-start "
            "align-items-center"
        ),
    ),
    color="primary",
    dark=True,
    sticky="top",
)


# =========================================================
# 24. Sidebar
# =========================================================
def navlink(label, key, icon):
    return dbc.NavLink(
        [
            html.I(
                className=f"bi {icon} me-2"
            ),
            label,
        ],
        href=APP_URLS[key],
        target="_self",
        external_link=True,
        active=(key == "step1"),
    )


sidebar = html.Div(
    [
        html.H5(
            "Navigation",
            className="text-white-50",
        ),

        html.Hr(className="my-2"),

        dbc.Nav(
            [
                navlink(
                    "Workspace",
                    "workspace",
                    "bi-house",
                ),

                navlink(
                    "Track Physics",
                    "step1",
                    "bi-1-circle",
                ),

                navlink(
                    "Layer Coverage",
                    "step3a",
                    "bi-2-circle",
                ),

                navlink(
                    "Cooling Time",
                    "step3b",
                    "bi-3-circle",
                ),

                navlink(
                    "Surface_profile",
                    "step4",
                    "bi-4-circle",
                ),
            ],
            vertical=True,
            pills=True,
        ),

        html.Div(
            "© 2026",
            className="text-white-50 small mt-2",
        ),
    ],
    id="sidebar",
    className="bg-dark h-100",
    style=SIDEBAR_EXPANDED_STYLE,
)


# =========================================================
# 25. 初始 Snapshot
# =========================================================
def get_initial_snapshot_count():
    info = load_npz_to_cache()

    if info["error"]:
        return 1

    return max(
        info["num_snapshots"],
        1,
    )


INITIAL_N = get_initial_snapshot_count()
INITIAL_VALUE = max(INITIAL_N - 1, 0)


# =========================================================
# 26. Layout
#
# 左側：
#   Slider + 3D NPZ
#
# 右側：
#   尺寸品質 + 凝固品質 + 曲線
# =========================================================
app.layout = html.Div(
    [
        navbar,
        sidebar,

        html.Div(
            [
                dbc.Card(
                    [
                        dbc.CardHeader(
                            html.Div(
                                [
                                    html.I(
                                        className="bi bi-boxes me-2"
                                    ),

                                    html.Span(
                                        "Preview Image - 3D NPZ",
                                        className="fw-bold",
                                    ),
                                ],
                                className="d-flex align-items-center",
                            )
                        ),

                        dbc.CardBody(
                            [
                                dbc.Row(
                                    [
                                        # =============================
                                        # 左側：Slider + 3D NPZ
                                        # =============================
                                        dbc.Col(
                                            [
                                                html.Div(
                                                    [
                                                        html.Div(
                                                            "Snapshot / Time",
                                                            className=(
                                                                "small "
                                                                "text-muted "
                                                                "mb-1"
                                                            ),
                                                        ),

                                                        dcc.Slider(
                                                            id=(
                                                                "npz-"
                                                                "snapshot-"
                                                                "slider"
                                                            ),
                                                            min=0,
                                                            max=max(
                                                                INITIAL_N - 1,
                                                                0,
                                                            ),
                                                            step=1,
                                                            value=INITIAL_VALUE,
                                                            marks=None,
                                                            updatemode="drag",
                                                            tooltip={
                                                                "placement": (
                                                                    "bottom"
                                                                ),
                                                                "always_visible": (
                                                                    True
                                                                ),
                                                                "style": {
                                                                    "color": (
                                                                        "#000000"
                                                                    ),
                                                                    "backgroundColor": (
                                                                        "#FFFFFF"
                                                                    ),
                                                                    "fontSize": (
                                                                        "15px"
                                                                    ),
                                                                    "fontWeight": (
                                                                        "700"
                                                                    ),
                                                                },
                                                            },
                                                        ),
                                                    ],
                                                    style={
                                                        "width": "96%",
                                                        "margin": (
                                                            "10px auto "
                                                            "18px auto"
                                                        ),
                                                        "paddingBottom": (
                                                            "8px"
                                                        ),
                                                    },
                                                ),

                                                dcc.Loading(
                                                    type="circle",
                                                    children=[
                                                        dcc.Graph(
                                                            id=(
                                                                "image-"
                                                                "zoom-graph"
                                                            ),
                                                            config=GRAPH_CONFIG,
                                                            responsive=True,
                                                            style={
                                                                "width": "100%",
                                                                "height": (
                                                                    "calc("
                                                                    "100vh - "
                                                                    "175px)"
                                                                ),
                                                                "minHeight": (
                                                                    "680px"
                                                                ),
                                                                "margin": (
                                                                    "0 auto"
                                                                ),
                                                            },
                                                        ),
                                                    ],
                                                ),
                                            ],
                                            xl=7,
                                            lg=7,
                                            md=12,
                                            sm=12,
                                            className="mb-2",
                                            style={
                                                "padding": "8px",
                                                "backgroundColor": "#111",
                                                "borderRadius": "14px",
                                                "border": (
                                                    "1px solid "
                                                    "rgba(255,255,255,"
                                                    "0.08)"
                                                ),
                                            },
                                        ),

                                        # =============================
                                        # 右側：品質資訊與曲線
                                        # =============================
                                        dbc.Col(
                                            [
                                                dcc.Loading(
                                                    type="circle",
                                                    children=[
                                                        html.Div(
                                                            id=(
                                                                "meltpool-"
                                                                "metric-cards"
                                                            )
                                                        ),

                                                        html.Div(
                                                            id=(
                                                                "solidification-"
                                                                "metric-cards"
                                                            )
                                                        ),

                                                        dcc.Graph(
                                                            id=(
                                                                "solidification-"
                                                                "curve-graph"
                                                            ),
                                                            config=GRAPH_CONFIG,
                                                            responsive=True,
                                                            style={
                                                                "width": "96%",
                                                                "height": (
                                                                    "350px"
                                                                ),
                                                                "margin": (
                                                                    "10px auto "
                                                                    "0 auto"
                                                                ),
                                                            },
                                                        ),

                                                        dcc.Graph(
                                                            id=(
                                                                "meltpool-"
                                                                "dimension-"
                                                                "graph"
                                                            ),
                                                            config=GRAPH_CONFIG,
                                                            responsive=True,
                                                            style={
                                                                "width": "96%",
                                                                "height": (
                                                                    "400px"
                                                                ),
                                                                "margin": (
                                                                    "10px auto "
                                                                    "12px auto"
                                                                ),
                                                            },
                                                        ),
                                                    ],
                                                ),
                                            ],
                                            xl=5,
                                            lg=5,
                                            md=12,
                                            sm=12,
                                            className="mb-2",
                                            style={
                                                "height": (
                                                    "calc("
                                                    "100vh - 100px)"
                                                ),
                                                "minHeight": "680px",
                                                "padding": (
                                                    "4px 2px "
                                                    "14px 2px"
                                                ),
                                                "overflowY": "auto",
                                                "overflowX": "hidden",
                                                "backgroundColor": "#151515",
                                                "borderRadius": "14px",
                                                "border": (
                                                    "1px solid "
                                                    "rgba(255,255,255,"
                                                    "0.08)"
                                                ),
                                            },
                                        ),
                                    ],
                                    className=(
                                        "g-3 align-items-start"
                                    ),
                                    style={
                                        "width": "100%",
                                        "margin": "0px",
                                    },
                                ),
                            ],
                            className="p-2",
                        ),
                    ],
                    className="shadow-sm",
                    style={
                        "width": "100%",
                        "marginTop": "10px",
                        "backgroundColor": "#111",
                    },
                ),
            ],
            id="main-content",
            style=MAIN_EXPANDED_STYLE,
        ),
    ],
    style={
        "width": "100vw",
        "minHeight": "100vh",
        "overflowX": "hidden",
        "backgroundColor": "#111",
    },
)


# =========================================================
# 27. Snapshot Callback
# =========================================================
@app.callback(
    [
        Output(
            "image-zoom-graph",
            "figure",
        ),

        Output(
            "meltpool-metric-cards",
            "children",
        ),

        Output(
            "solidification-metric-cards",
            "children",
        ),

        Output(
            "solidification-curve-graph",
            "figure",
        ),

        Output(
            "meltpool-dimension-graph",
            "figure",
        ),
    ],
    Input(
        "npz-snapshot-slider",
        "value",
    ),
)
def update_npz_graph(snapshot_idx):
    fig_3d = make_npz_3d_figure(snapshot_idx)

    meltpool_cards = make_meltpool_summary_cards(
        snapshot_idx
    )

    solidification_cards = (
        make_solidification_summary_cards(
            snapshot_idx
        )
    )

    solidification_curve_fig = (
        make_solidification_curve_figure(
            snapshot_idx
        )
    )

    meltpool_curve_fig = (
        make_meltpool_curve_figure(
            snapshot_idx
        )
    )

    return (
        fig_3d,
        meltpool_cards,
        solidification_cards,
        solidification_curve_fig,
        meltpool_curve_fig,
    )


# =========================================================
# 28. Sidebar Callback
# =========================================================
@app.callback(
    [
        Output(
            "sidebar",
            "style",
        ),

        Output(
            "main-content",
            "style",
        ),
    ],
    Input(
        "sidebar-toggle",
        "n_clicks",
    ),
)
def toggle_sidebar(n_clicks):
    if n_clicks is None:
        n_clicks = 0

    is_collapsed = n_clicks % 2 == 1

    if is_collapsed:
        return (
            SIDEBAR_COLLAPSED_STYLE,
            MAIN_COLLAPSED_STYLE,
        )

    return (
        SIDEBAR_EXPANDED_STYLE,
        MAIN_EXPANDED_STYLE,
    )


# =========================================================
# 29. 主程式
# =========================================================
if __name__ == "__main__":
    print("=" * 70)
    print("Dash NPZ Phase Viewer")
    print(f"NPZ Path: {NPZ_PREVIEW_PATH}")
    print(
        f"Dash URL: "
        f"http://127.0.0.1:{DASH_PORT}"
    )
    print("=" * 70)

    app.run(
        host="127.0.0.1",
        port=DASH_PORT,
        debug=False,
    )