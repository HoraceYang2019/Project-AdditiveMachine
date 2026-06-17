# -*- coding: utf-8 -*-
"""
Dash NPZ Phase Viewer with Time Slider

功能：
1. 讀取 NPZ 檔案中的 phase 4D 資料：phase[time, x, y, z]
2. 顯示 3D NPZ Phase：
   - 藍色：Powder / never melted solid
   - 綠色：Resolidified / melted then solid
   - 橘色：Liquid / current melt pool
3. 在 3D 圖下方加入：
   - 熔池長度 Length
   - 熔池寬度 Width
   - 熔池深度 Depth
   - 熔池尺寸品質判斷
   - 熔池凝固判別
   - 熔池凝固曲線
   - 熔池長寬深曲線
4. 綠 / 黃 / 紅代表目前拉霸 Snapshot 的品質狀態：
   - Green  = Good / Stable
   - Yellow = Warning / Partial
   - Red    = Bad / Unstable
5. 曲線顏色不使用綠黃紅：
   - Length = 藍青色
   - Width  = 紫色
   - Depth  = 橘色
"""

from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from dash import Dash, dcc, html, Input, Output


# =========================================================
# 1. NPZ 路徑設定
# =========================================================
NPZ_PREVIEW_PATH = Path(
    r"D:\2026Experiment\2026Experiment0528\thermal_phase_fields_part000.npz"
).resolve()


# =========================================================
# 2. Dash Port
# =========================================================
DASH_PORT = 8074


# =========================================================
# 3. Dash 導覽網址
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
# 根據 spot_size = 50 µm 建議：
# Width  ≈ 2 × spot_size = 100 µm
# Length ≈ 6 × spot_size = 300 µm
# Depth  ≈ 0.8 ~ 1.2 × spot_size = 40 ~ 60 µm
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
# 6. 熔池凝固判斷門檻
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
# 9. 基本工具函式
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

    pick = np.linspace(0, len(indices) - 1, int(max_points), dtype=np.int64)
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
    計算熔池在某一方向的實際尺寸。

    公式：
        Dimension = (max_index - min_index + 1) × pitch_um

    +1 原因：
        如果熔池只有 1 個格點，不加 +1 會變成 0。
    """
    indices = np.argwhere(mask)

    if indices.size == 0:
        return 0.0

    min_idx = int(indices[:, axis].min())
    max_idx = int(indices[:, axis].max())

    return float((max_idx - min_idx + 1) * pitch_um)


# =========================================================
# 10. 熔池長寬深計算
# =========================================================
def compute_all_meltpool_metrics(phase_ds, dx_um, dy_um, dz_um):
    """
    對所有 snapshot 計算：
    - Length：X 方向
    - Width ：Y 方向
    - Depth ：Z 方向
    """
    nt = phase_ds.shape[0]

    lengths = np.zeros(nt, dtype=np.float64)
    widths = np.zeros(nt, dtype=np.float64)
    depths = np.zeros(nt, dtype=np.float64)

    for i in range(nt):
        liquid_mask = phase_ds[i] == PHASE_LIQUID

        if not np.any(liquid_mask):
            continue

        lengths[i] = compute_extent_um(liquid_mask, axis=0, pitch_um=dx_um)
        widths[i] = compute_extent_um(liquid_mask, axis=1, pitch_um=dy_um)
        depths[i] = compute_extent_um(liquid_mask, axis=2, pitch_um=dz_um)

    return {
        "length_um": lengths,
        "width_um": widths,
        "depth_um": depths,
    }


# =========================================================
# 11. 熔池凝固指標計算
# =========================================================
def compute_all_solidification_metrics(phase_ds):
    """
    熔池凝固判別指標。

    Liquid：
        目前 snapshot 還是液態的熔池區域。

    Resolidified：
        目前是 Solid，而且歷史上曾經是 Liquid 的區域。
        也就是已經熔化過，現在重新凝固的區域。

    Solidification Ratio：
        Resolidified / (Resolidified + Liquid) × 100%

    Liquid Ratio：
        Liquid / (Resolidified + Liquid) × 100%
    """
    nt = phase_ds.shape[0]

    solidification_ratio = np.zeros(nt, dtype=np.float64)
    liquid_ratio = np.zeros(nt, dtype=np.float64)
    resolidified_count = np.zeros(nt, dtype=np.int64)
    liquid_count = np.zeros(nt, dtype=np.int64)
    melted_region_count = np.zeros(nt, dtype=np.int64)

    ever_melted_mask = np.zeros(phase_ds.shape[1:], dtype=bool)

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
            solidification_ratio[i] = r_count / total_count * 100.0
            liquid_ratio[i] = l_count / total_count * 100.0

    return {
        "solidification_ratio": solidification_ratio,
        "liquid_ratio": liquid_ratio,
        "resolidified_count": resolidified_count,
        "liquid_count": liquid_count,
        "melted_region_count": melted_region_count,
    }


# =========================================================
# 12. 品質判斷函式
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
    """
    熔池凝固品質判斷。

    Green / Stable：
        Solidification Ratio >= 85%，且 Liquid Ratio <= 15%。

    Yellow / Partial：
        Solidification Ratio >= 60%，且 Liquid Ratio <= 40%。

    Red / Unstable：
        低於上述條件。
    """
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
# 13. NPZ 讀取與快取
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
                NPZ_INFO["error"] = f"phase 不是 4D，現在 shape = {phase.shape}"
                return NPZ_INFO

            nt, nx, ny, nz = phase.shape

            dx_um = float(data["dx"]) * 1e6 if "dx" in data.files else 1.0
            dy_um = float(data["dy"]) * 1e6 if "dy" in data.files else 1.0
            dz_um = float(data["dz"]) * 1e6 if "dz" in data.files else 1.0

            phase_ds = phase[:, ::STEP_X, ::STEP_Y, ::STEP_Z].copy()

            meltpool_metrics = compute_all_meltpool_metrics(
                phase_ds=phase_ds,
                dx_um=dx_um * STEP_X,
                dy_um=dy_um * STEP_Y,
                dz_um=dz_um * STEP_Z,
            )

            solidification_metrics = compute_all_solidification_metrics(
                phase_ds=phase_ds
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
            print(f"dx={dx_um:.3f} um, dy={dy_um:.3f} um, dz={dz_um:.3f} um")

            return NPZ_INFO

    except Exception as e:
        NPZ_INFO["error"] = f"NPZ 讀取失敗：{e}"
        return NPZ_INFO


# =========================================================
# 14. Phase 分類
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

    ever_melted_mask = np.any(phase_history == PHASE_LIQUID, axis=0)

    mask_powder = solid_mask & (~ever_melted_mask)
    mask_resolidified = solid_mask & ever_melted_mask
    mask_liquid = liquid_mask.copy()

    return phase_now, mask_powder, mask_resolidified, mask_liquid, snapshot_idx


# =========================================================
# 15. UI 卡片與空白圖
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


def make_quality_card(title, value, subtitle, color, icon="bi-activity"):
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        [
                            html.I(className=f"bi {icon} me-2"),
                            html.Span(title, className="fw-bold"),
                        ],
                        className="d-flex align-items-center mb-2",
                        style={"fontSize": "15px"},
                    ),
                    html.Div(
                        value,
                        className="fw-bold",
                        style={
                            "fontSize": "30px",
                            "lineHeight": "1.15",
                            "letterSpacing": "0.5px",
                        },
                    ),
                    html.Div(
                        subtitle,
                        className="mt-2",
                        style={
                            "fontSize": "13px",
                            "opacity": "0.9",
                            "lineHeight": "1.4",
                        },
                    ),
                ],
            ),
            color=color,
            inverse=True,
            className="shadow-sm border-0",
            style={
                "borderRadius": "16px",
                "minHeight": "150px",
            },
        ),
        md=4,
        sm=12,
        className="mb-3",
    )


def make_meltpool_summary_cards(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return dbc.Alert(info["error"], color="danger", className="mt-2")

    nt = info["phase_ds"].shape[0]
    snapshot_idx = clamp_snapshot_index(snapshot_idx, nt)

    metrics = info["meltpool_metrics"]

    length_um = float(metrics["length_um"][snapshot_idx])
    width_um = float(metrics["width_um"][snapshot_idx])
    depth_um = float(metrics["depth_um"][snapshot_idx])

    length_status, width_status, depth_status = get_meltpool_status(
        length_um,
        width_um,
        depth_um,
    )

    length_text, length_card_color, _ = length_status
    width_text, width_card_color, _ = width_status
    depth_text, depth_card_color, _ = depth_status

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className="bi bi-rulers me-2"),
                            html.Span(
                                "Melt Pool Dimension Quality / 熔池尺寸品質判斷"
                            ),
                        ],
                        className="fw-bold",
                        style={"fontSize": "22px"},
                    ),
                    html.Div(
                        f"Current Snapshot：{snapshot_idx}",
                        className="text-white-50",
                        style={"fontSize": "14px"},
                    ),
                ],
                className="d-flex justify-content-between align-items-end mt-3 mb-2",
            ),

            dbc.Row(
                [
                    make_quality_card(
                        title="Melt Pool Length",
                        value=f"{length_um:.2f} µm",
                        subtitle=(
                            f"{length_text}｜Target "
                            f"{TARGET_LENGTH_UM:.0f} ± {LENGTH_GOOD_TOL:.0f} µm"
                        ),
                        color=length_card_color,
                        icon="bi-arrows-expand",
                    ),
                    make_quality_card(
                        title="Melt Pool Width",
                        value=f"{width_um:.2f} µm",
                        subtitle=(
                            f"{width_text}｜Target "
                            f"{TARGET_WIDTH_UM:.0f} ± {WIDTH_GOOD_TOL:.0f} µm"
                        ),
                        color=width_card_color,
                        icon="bi-arrows",
                    ),
                    make_quality_card(
                        title="Melt Pool Depth",
                        value=f"{depth_um:.2f} µm",
                        subtitle=(
                            f"{depth_text}｜Good "
                            f"{DEPTH_GOOD_MIN:.0f} ~ {DEPTH_GOOD_MAX:.0f} µm"
                        ),
                        color=depth_card_color,
                        icon="bi-arrow-down-up",
                    ),
                ],
                className="g-3",
            ),

            dbc.Alert(
                [
                    html.Div(
                        [
                            html.Span("Green", className="fw-bold text-success"),
                            html.Span(" = Good / 正常　"),
                            html.Span("Yellow", className="fw-bold text-warning"),
                            html.Span(" = Warning / 警告　"),
                            html.Span("Red", className="fw-bold text-danger"),
                            html.Span(" = Bad / 異常"),
                        ]
                    ),
                    html.Div(
                        "顏色代表目前拉霸 Snapshot 的品質判斷，不是固定代表 Length / Width / Depth。",
                        className="mt-1 text-white-50",
                    ),
                ],
                color="dark",
                className="mt-1 mb-2 py-2 small",
                style={"borderRadius": "12px"},
            ),
        ],
        style={
            "width": "96%",
            "margin": "0 auto",
            "backgroundColor": "#1b1b1b",
            "padding": "14px",
            "borderRadius": "18px",
            "border": "1px solid rgba(255,255,255,0.08)",
        },
    )


def make_solidification_summary_cards(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return dbc.Alert(info["error"], color="danger", className="mt-2")

    nt = info["phase_ds"].shape[0]
    snapshot_idx = clamp_snapshot_index(snapshot_idx, nt)

    metrics = info["solidification_metrics"]

    solidification_ratio = float(metrics["solidification_ratio"][snapshot_idx])
    liquid_ratio = float(metrics["liquid_ratio"][snapshot_idx])
    resolidified_count = int(metrics["resolidified_count"][snapshot_idx])
    liquid_count = int(metrics["liquid_count"][snapshot_idx])
    melted_region_count = int(metrics["melted_region_count"][snapshot_idx])

    status_text, status_color, _ = evaluate_solidification_status(
        solidification_ratio,
        liquid_ratio,
        melted_region_count,
    )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className="bi bi-droplet-half me-2"),
                            html.Span(
                                "Melt Pool Solidification Judgment / 熔池凝固判別"
                            ),
                        ],
                        className="fw-bold",
                        style={"fontSize": "22px"},
                    ),
                    html.Div(
                        f"Current Snapshot：{snapshot_idx}",
                        className="text-white-50",
                        style={"fontSize": "14px"},
                    ),
                ],
                className="d-flex justify-content-between align-items-end mt-3 mb-2",
            ),

            dbc.Row(
                [
                    make_quality_card(
                        title="Solidification Ratio",
                        value=f"{solidification_ratio:.2f}%",
                        subtitle="Resolidified / (Resolidified + Liquid)",
                        color=status_color,
                        icon="bi-check-circle",
                    ),
                    make_quality_card(
                        title="Liquid Ratio",
                        value=f"{liquid_ratio:.2f}%",
                        subtitle=f"Liquid Count = {liquid_count:,}",
                        color=status_color,
                        icon="bi-droplet",
                    ),
                    make_quality_card(
                        title="Solidification Status",
                        value=status_text,
                        subtitle=f"Resolidified Count = {resolidified_count:,}",
                        color=status_color,
                        icon="bi-clipboard-data",
                    ),
                ],
                className="g-3",
            ),

            dbc.Alert(
                [
                    html.Div(
                        [
                            html.Span("公式：", className="fw-bold"),
                            html.Span(
                                "Solidification Ratio = Resolidified / "
                                "(Resolidified + Liquid) × 100%"
                            ),
                        ]
                    ),
                    html.Div(
                        "比例越高代表熔池越接近穩定凝固；Liquid Ratio 越高代表目前仍有較多液態熔池。",
                        className="mt-1 text-white-50",
                    ),
                ],
                color="dark",
                className="mt-1 mb-2 py-2 small",
                style={"borderRadius": "12px"},
            ),
        ],
        style={
            "width": "96%",
            "margin": "12px auto 0 auto",
            "backgroundColor": "#1b1b1b",
            "padding": "14px",
            "borderRadius": "18px",
            "border": "1px solid rgba(255,255,255,0.08)",
        },
    )


# =========================================================
# 16. 曲線圖
# =========================================================
def make_solidification_curve_figure(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return make_empty_figure(f"⚠️ {info['error']}", height=360)

    nt = info["phase_ds"].shape[0]
    snapshot_idx = clamp_snapshot_index(snapshot_idx, nt)

    metrics = info["solidification_metrics"]

    x = np.arange(nt)
    solidification_ratio = metrics["solidification_ratio"]
    liquid_ratio = metrics["liquid_ratio"]

    current_solidification = float(solidification_ratio[snapshot_idx])
    current_liquid = float(liquid_ratio[snapshot_idx])
    current_total = int(metrics["melted_region_count"][snapshot_idx])

    status_text, _, quality_color = evaluate_solidification_status(
        current_solidification,
        current_liquid,
        current_total,
    )

    fig = go.Figure()

    SOLIDIFICATION_CURVE_COLOR = "#00CED1"
    LIQUID_CURVE_COLOR = "#DA70D6"

    fig.add_trace(
        go.Scatter(
            x=x,
            y=solidification_ratio,
            mode="lines",
            name="Solidification Ratio",
            line=dict(color=SOLIDIFICATION_CURVE_COLOR, width=3),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=liquid_ratio,
            mode="lines",
            name="Liquid Ratio",
            line=dict(color=LIQUID_CURVE_COLOR, width=3, dash="dash"),
        )
    )

    fig.add_vline(
        x=snapshot_idx,
        line_width=2,
        line_dash="dash",
        line_color="white",
        opacity=0.85,
    )

    fig.add_trace(
        go.Scatter(
            x=[snapshot_idx],
            y=[current_solidification],
            mode="markers+text",
            name=f"Current Solidification - {status_text}",
            marker=dict(
                color=quality_color,
                size=15,
                symbol="diamond",
                line=dict(color="white", width=1),
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
        height=360,
        margin=dict(l=45, r=15, t=50, b=45),
        title=(
            f"Melt Pool Solidification Curve at Snapshot {snapshot_idx} "
            f"| Quality Point: Green=Stable, Yellow=Partial, Red=Unstable"
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1.0,
            bgcolor="rgba(0,0,0,0.25)",
        ),
        xaxis=dict(
            title="Snapshot / Time",
            gridcolor="#333",
            zerolinecolor="#777",
        ),
        yaxis=dict(
            title="Ratio (%)",
            range=[0, 105],
            gridcolor="#333",
            zerolinecolor="#777",
        ),
        hovermode="x unified",
    )

    return fig


def make_meltpool_curve_figure(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return make_empty_figure(f"⚠️ {info['error']}", height=420)

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

    length_status, width_status, depth_status = get_meltpool_status(
        current_length,
        current_width,
        current_depth,
    )

    length_text, _, length_quality_color = length_status
    width_text, _, width_quality_color = width_status
    depth_text, _, depth_quality_color = depth_status

    fig = go.Figure()

    LENGTH_CURVE_COLOR = "#00BFFF"
    WIDTH_CURVE_COLOR = "#A020F0"
    DEPTH_CURVE_COLOR = "#FF8C00"

    fig.add_trace(
        go.Scatter(
            x=x,
            y=lengths,
            mode="lines",
            name="Length",
            line=dict(color=LENGTH_CURVE_COLOR, width=3),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=widths,
            mode="lines",
            name="Width",
            line=dict(color=WIDTH_CURVE_COLOR, width=3, dash="dash"),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=depths,
            mode="lines",
            name="Depth",
            line=dict(color=DEPTH_CURVE_COLOR, width=3, dash="dot"),
        )
    )

    fig.add_vline(
        x=snapshot_idx,
        line_width=2,
        line_dash="dash",
        line_color="white",
        opacity=0.85,
    )

    fig.add_trace(
        go.Scatter(
            x=[snapshot_idx],
            y=[current_length],
            mode="markers+text",
            name=f"Current Length - {length_text}",
            marker=dict(
                color=length_quality_color,
                size=15,
                symbol="diamond",
                line=dict(color="white", width=1),
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
            name=f"Current Width - {width_text}",
            marker=dict(
                color=width_quality_color,
                size=15,
                symbol="diamond",
                line=dict(color="white", width=1),
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
            name=f"Current Depth - {depth_text}",
            marker=dict(
                color=depth_quality_color,
                size=15,
                symbol="diamond",
                line=dict(color="white", width=1),
            ),
            text=[f"Depth {depth_text}"],
            textposition="top center",
        )
    )

    fig.add_hline(
        y=TARGET_LENGTH_UM,
        line_width=1,
        line_dash="dash",
        line_color=LENGTH_CURVE_COLOR,
        annotation_text="Length Target",
        annotation_position="top left",
    )

    fig.add_hline(
        y=TARGET_WIDTH_UM,
        line_width=1,
        line_dash="dash",
        line_color=WIDTH_CURVE_COLOR,
        annotation_text="Width Target",
        annotation_position="bottom left",
    )

    fig.add_hrect(
        y0=DEPTH_GOOD_MIN,
        y1=DEPTH_GOOD_MAX,
        fillcolor=DEPTH_CURVE_COLOR,
        opacity=0.10,
        line_width=0,
        annotation_text="Depth Good Range",
        annotation_position="top right",
    )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111",
        plot_bgcolor="#111",
        height=420,
        margin=dict(l=45, r=15, t=50, b=45),
        title=(
            f"Melt Pool Dimension Quality at Snapshot {snapshot_idx} "
            f"| Quality Point: Green=Good, Yellow=Warning, Red=Bad"
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1.0,
            bgcolor="rgba(0,0,0,0.25)",
        ),
        xaxis=dict(
            title="Snapshot / Time",
            gridcolor="#333",
            zerolinecolor="#777",
        ),
        yaxis=dict(
            title="Dimension (µm)",
            gridcolor="#333",
            zerolinecolor="#777",
        ),
        hovermode="x unified",
    )

    return fig


# =========================================================
# 17. 3D NPZ 圖
# =========================================================
def make_npz_3d_figure(snapshot_idx):
    info = load_npz_to_cache()

    if info["error"]:
        return make_empty_figure(f"⚠️ {info['error']}")

    nt = info["phase_ds"].shape[0]

    phase_now, mask_powder, mask_resolidified, mask_liquid, snapshot_idx = compute_class_masks(
        snapshot_idx
    )

    if phase_now is None:
        return make_empty_figure("⚠️ 無法產生 phase mask")

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
        max_points = MAX_POINTS_BY_CLASS.get(name, 100000)

        x, y, z, raw_count, shown_count = mask_to_xyz(
            mask,
            dx_um,
            dy_um,
            dz_um,
            max_points=max_points,
        )

        display_summary.append(f"{name}: {shown_count:,}/{raw_count:,}")

        if len(x) > 0:
            style = styles[name]

            fig.add_trace(
                go.Scatter3d(
                    x=x,
                    y=y,
                    z=z,
                    mode="markers",
                    name=f"{name} ({shown_count:,}/{raw_count:,})",
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
        margin=dict(l=2, r=2, t=45, b=2),
        height=650,
        title=(
            f"3D NPZ Phase Preview - Snapshot {snapshot_idx} / {nt - 1} | "
            f"dx={info['dx_um']:.2f}, dy={info['dy_um']:.2f}, dz={info['dz_um']:.2f} µm | "
            f"Displayed: {' | '.join(display_summary)}"
        ),
        legend=dict(
            x=0.02,
            y=0.98,
            bgcolor="rgba(0,0,0,.35)",
        ),
        uirevision="keep-camera",
        scene=dict(
            camera=dict(
                eye=dict(x=2.0, y=2.0, z=1.4)
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
# 18. Dash Layout
# =========================================================
app = Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.DARKLY,
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css",
    ],
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

app.title = "Track Physics NPZ Dash"


navbar = dbc.Navbar(
    dbc.Container(
        [
            html.Div(
                [
                    html.I(className="bi bi-cpu me-2"),
                    html.Span("Track Physics - NPZ Phase Viewer", className="h5 mb-0"),
                ],
                className="d-flex align-items-center",
            ),
        ],
        fluid=True,
    ),
    color="primary",
    dark=True,
    sticky="top",
)


def navlink(label, key, icon):
    return dbc.NavLink(
        [html.I(className=f"bi {icon} me-2"), label],
        href=APP_URLS[key],
        target="_self",
        external_link=True,
        active=(key == "step1"),
    )


sidebar = html.Div(
    [
        html.H5("Navigation", className="text-white-50"),
        html.Hr(className="my-2"),
        dbc.Nav(
            [
                navlink("Workspace", "workspace", "bi-house"),
                navlink("Track Physics", "step1", "bi-1-circle"),
                navlink("Layer Coverage", "step3a", "bi-2-circle"),
                navlink("Cooling Time", "step3b", "bi-3-circle"),
                navlink("Surface_profile", "step4", "bi-4-circle"),
            ],
            vertical=True,
            pills=True,
        ),
        html.Div("© 2026", className="text-white-50 small mt-2"),
    ],
    className="bg-dark p-3 h-100",
    style={
        "width": "240px",
        "top": "56px",
        "left": 0,
        "overflowY": "auto",
        "height": "calc(100vh - 56px)",
        "zIndex": 1030,
        "position": "fixed",
    },
)


def get_initial_snapshot_count():
    info = load_npz_to_cache()

    if info["error"]:
        return 1

    return max(info["num_snapshots"], 1)


INITIAL_N = get_initial_snapshot_count()
INITIAL_VALUE = max(INITIAL_N - 1, 0)


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
                                    html.I(className="bi bi-boxes me-2"),
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
                                html.Div(
                                    [
                                        html.Div(
                                            "Snapshot / Time",
                                            className="small text-muted mb-1",
                                        ),
                                        dcc.Slider(
                                            id="npz-snapshot-slider",
                                            min=0,
                                            max=max(INITIAL_N - 1, 0),
                                            step=1,
                                            value=INITIAL_VALUE,
                                            marks=None,
                                            updatemode="drag",
                                            tooltip={
                                                "placement": "bottom",
                                                "always_visible": True,
                                                "style": {
                                                    "color": "#000000",
                                                    "backgroundColor": "#FFFFFF",
                                                    "fontSize": "15px",
                                                    "fontWeight": "700",
                                                },
                                            },
                                        ),
                                    ],
                                    style={
                                        "width": "96%",
                                        "margin": "12px auto 18px auto",
                                    },
                                ),

                                dcc.Loading(
                                    type="circle",
                                    children=[
                                        dcc.Graph(
                                            id="image-zoom-graph",
                                            config=GRAPH_CONFIG,
                                            responsive=True,
                                            style={
                                                "width": "96%",
                                                "height": "68vh",
                                                "minHeight": "560px",
                                                "margin": "0 auto",
                                            },
                                        ),

                                        html.Div(id="meltpool-metric-cards"),

                                        html.Div(id="solidification-metric-cards"),

                                        dcc.Graph(
                                            id="solidification-curve-graph",
                                            config=GRAPH_CONFIG,
                                            responsive=True,
                                            style={
                                                "width": "96%",
                                                "height": "370px",
                                                "margin": "8px auto 0 auto",
                                            },
                                        ),

                                        dcc.Graph(
                                            id="meltpool-dimension-graph",
                                            config=GRAPH_CONFIG,
                                            responsive=True,
                                            style={
                                                "width": "96%",
                                                "height": "430px",
                                                "margin": "8px auto 0 auto",
                                            },
                                        ),
                                    ],
                                ),
                            ],
                            className="p-2",
                        ),
                    ],
                    className="shadow-sm",
                    style={
                        "width": "100%",
                        "marginTop": "10px",
                    },
                ),
            ],
            style={
                "marginLeft": "260px",
                "padding": "12px",
                "paddingTop": "5px",
                "paddingBottom": "16px",
                "minHeight": "calc(100vh - 56px)",
                "width": "calc(100% - 260px)",
                "maxWidth": "100%",
                "overflowX": "hidden",
                "overflowY": "auto",
            },
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
# 19. Callbacks
# =========================================================
@app.callback(
    [
        Output("image-zoom-graph", "figure"),
        Output("meltpool-metric-cards", "children"),
        Output("solidification-metric-cards", "children"),
        Output("solidification-curve-graph", "figure"),
        Output("meltpool-dimension-graph", "figure"),
    ],
    Input("npz-snapshot-slider", "value"),
)
def update_npz_graph(snapshot_idx):
    fig_3d = make_npz_3d_figure(snapshot_idx)
    meltpool_cards = make_meltpool_summary_cards(snapshot_idx)
    solidification_cards = make_solidification_summary_cards(snapshot_idx)
    solidification_curve_fig = make_solidification_curve_figure(snapshot_idx)
    meltpool_curve_fig = make_meltpool_curve_figure(snapshot_idx)

    return (
        fig_3d,
        meltpool_cards,
        solidification_cards,
        solidification_curve_fig,
        meltpool_curve_fig,
    )


# =========================================================
# 20. 主程式
# =========================================================
if __name__ == "__main__":
    print("=" * 70)
    print("Dash NPZ Phase Viewer")
    print(f"NPZ Path: {NPZ_PREVIEW_PATH}")
    print(f"Dash URL: http://127.0.0.1:{DASH_PORT}")
    print("=" * 70)

    app.run(
        host="127.0.0.1",
        port=DASH_PORT,
        debug=False,
    )