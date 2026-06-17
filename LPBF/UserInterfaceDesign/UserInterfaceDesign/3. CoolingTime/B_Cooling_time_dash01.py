# -*- coding: utf-8 -*-

import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from dash import Dash, html, dcc, Input, Output
from waitress import serve


# =========================================================
# 1. 固定讀取 Cooling Time CSV 資料夾
# =========================================================
FIXED_CSV_DIR = Path(
    r"D:\2026Experiment\2026Experiment0612\dash\NIST\3. Simulation\Cooling_Time\cooling_layer_csv"
)


# =========================================================
# 2. Dash 導覽網址
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
# 3. Layer 範圍
# =========================================================
LAYER_MIN_UI = 1
LAYER_MAX_UI = 250


# =========================================================
# 4. Heatmap 顯示座標
# =========================================================
DISPLAY_X_START_MM = -5.4
DISPLAY_X_END_MM = 5.4

DISPLAY_Y_START_MM = -5.4
DISPLAY_Y_END_MM = 5.4


# =========================================================
# 5. 品質分析範圍
# =========================================================
QUALITY_X_START_MM = -4.5
QUALITY_X_END_MM = 4.5

QUALITY_Y_START_MM = -2.5
QUALITY_Y_END_MM = 2.5


# =========================================================
# 6. 有效 Cooling Time 門檻
# =========================================================
# Cooling Time < 200 視為空白／不足區域。
LOW_VALUE_THRESHOLD = 200.0


# =========================================================
# 7. 品質分析設定
# =========================================================
# True：品質分析只計算 >= LOW_VALUE_THRESHOLD 的有效區域
# False：品質分析計算全部數值
EXCLUDE_BELOW_THRESHOLD_FOR_QUALITY = True

COOLING_CV_PASS = 0.10
COOLING_CV_WARN = 0.20

COOLING_RANGE_PASS = 0.25
COOLING_RANGE_WARN = 0.45


# =========================================================
# 8. Heatmap 色階
# =========================================================
COOLING_ZMIN = 0.0
COOLING_ZMAX = 1600.0
COOLING_COLORSCALE = "Blues"


# =========================================================
# 9. n 層主圖設定
# =========================================================
# 主圖直接使用 Layer n 的原始 Cooling Time。
# 不乘倍率、不補 n-1，也不改變 n 層的數值。
USE_RAW_N_LAYER_AS_BASE = True


# =========================================================
# 10. n+1 對 n 的「顏色深淺」影響設定
# =========================================================
# 重要：
# n+1 不會取代 Layer n 的 Cooling Time。
# n+1 只用來產生一層透明深色遮罩：
#
#     Time increase = max(
#         CoolingTime(n+1) - CoolingTime(n),
#         0
#     )
#
# 只有 n+1 時間比 n 長時，該位置顏色才會變深。
# n+1 時間小於或等於 n 時，該位置顏色保持不變。
#
# Heatmap 的基本形狀與 Cooling Time 數值仍由 Layer n 決定。

# 是否啟用 n+1 梯度深淺疊加
ENABLE_NEXT_LAYER_GRADIENT_SHADING = True

# n+1 比 n 增加的時間，使用最大百分位數做顏色正規化。
# 例如 95：正向時間增加量達到 P95 時視為最深，
# 避免少數極端值支配整張圖。
GRADIENT_NORMALIZE_PERCENTILE = 95.0

# n+1 比 n 增加量小於或等於此值時，不加深。
GRADIENT_MIN_DIFFERENCE = 0.0

# 最深遮罩透明度，數值越大，梯度大的地方越深。
# 建議範圍 0.20～0.70。
GRADIENT_MAX_OPACITY = 0.55

# 梯度遮罩色階：
# 0 為完全透明；1 為深藍半透明。
GRADIENT_OVERLAY_COLORSCALE = [
    [0.00, "rgba(0, 0, 80, 0.00)"],
    [0.20, "rgba(0, 0, 80, 0.03)"],
    [0.40, "rgba(0, 0, 90, 0.10)"],
    [0.60, "rgba(0, 0, 100, 0.22)"],
    [0.80, "rgba(0, 0, 90, 0.38)"],
    [1.00, f"rgba(0, 0, 60, {GRADIENT_MAX_OPACITY:.2f})"],
]


# =========================================================
# 11. Layer 對應工具
# =========================================================
def ui_layer_to_current_csv_index(ui_layer: int) -> int:
    return int(ui_layer) - 1


def ui_layer_to_next_csv_index(ui_layer: int) -> int:
    """
    Display Layer n 對應 CSV index = n-1。
    下一層 n+1 對應 CSV index = n。
    """
    return int(ui_layer)


def csv_index_to_ui_layer(csv_index: int) -> int:
    return int(csv_index) + 1


# =========================================================
# 12. 自動計算 Graph 高度
# =========================================================
def get_graph_height_css():
    x_range = abs(DISPLAY_X_END_MM - DISPLAY_X_START_MM)
    y_range = abs(DISPLAY_Y_END_MM - DISPLAY_Y_START_MM)

    if x_range <= 0 or y_range <= 0:
        return "700px"

    ratio = y_range / x_range

    return (
        f"clamp("
        f"700px, "
        f"calc((100vw - 360px) * {ratio:.6f}), "
        f"1200px"
        f")"
    )


GRAPH_HEIGHT_CSS = get_graph_height_css()

GRAPH_CONFIG = {
    "responsive": True,
    "displaylogo": False,
    "scrollZoom": True,
    "doubleClick": "reset",
}

HEATMAP_STYLE = {
    "width": "100%",
    "height": GRAPH_HEIGHT_CSS,
    "minHeight": "700px",
    "margin": "0 auto",
    "marginTop": "12px",
}


# =========================================================
# 13. Dash 初始化
# =========================================================
app = Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.DARKLY,
        (
            "https://cdn.jsdelivr.net/npm/"
            "bootstrap-icons@1.11.3/font/bootstrap-icons.css"
        ),
    ],
    suppress_callback_exceptions=True,
    meta_tags=[
        {
            "name": "viewport",
            "content": "width=device-width, initial-scale=1",
        },
    ],
)

app.title = "Cooling Time - n+1 Longer Means Darker"


# =========================================================
# 14. Slider Marks
# =========================================================
def make_slider_marks(min_ui: int, max_ui: int):
    step = max((max_ui - min_ui) // 10, 1)

    marks = list(
        range(
            min_ui,
            max_ui + 1,
            step,
        )
    )

    if max_ui not in marks:
        marks.append(max_ui)

    return {
        int(value): {
            "label": str(value),
            "style": {
                "color": "#FFFFFF",
                "fontSize": "12px",
                "fontWeight": "600",
                "marginTop": "8px",
            },
        }
        for value in sorted(set(marks))
    }


# =========================================================
# 15. 掃描 CSV
# =========================================================
def scan_cooling_csvs_by_index() -> Dict[int, Path]:
    mapping: Dict[int, Path] = {}

    if (
        not FIXED_CSV_DIR.exists()
        or not FIXED_CSV_DIR.is_dir()
    ):
        return mapping

    pattern = re.compile(
        r"^cooling_layer_1_(\d+)\.csv$",
        flags=re.IGNORECASE,
    )

    for csv_path in FIXED_CSV_DIR.glob("*.csv"):
        match = pattern.match(csv_path.name)

        if not match:
            continue

        csv_index = int(match.group(1))

        if 0 <= csv_index <= 249:
            mapping[csv_index] = csv_path

    return dict(sorted(mapping.items()))


def scan_display_layers() -> Dict[int, Path]:
    csv_mapping = scan_cooling_csvs_by_index()
    display_mapping: Dict[int, Path] = {}

    for csv_index, csv_path in csv_mapping.items():
        ui_layer = csv_index_to_ui_layer(csv_index)

        if LAYER_MIN_UI <= ui_layer <= LAYER_MAX_UI:
            display_mapping[ui_layer] = csv_path

    return dict(sorted(display_mapping.items()))


# =========================================================
# 16. 讀取 CSV
# =========================================================
def load_single_cooling_csv_as_z(csv_path: Path):
    df = pd.read_csv(
        csv_path,
        header=None,
    )

    z = (
        df.apply(
            pd.to_numeric,
            errors="coerce",
        )
        .to_numpy(dtype=float)
    )

    z = np.nan_to_num(
        z,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    if z.ndim != 2:
        raise ValueError(
            f"{csv_path.name} 不是 2D 陣列"
        )

    if z.size == 0:
        raise ValueError(
            f"{csv_path.name} 沒有有效數值"
        )

    # 與原本程式一致，左右翻轉
    z = np.fliplr(z)

    return z


# =========================================================
# 17. 將陣列裁切為共同尺寸
# =========================================================
def crop_arrays_to_common_shape(*arrays):
    valid_arrays = [
        np.asarray(array, dtype=float)
        for array in arrays
        if array is not None
    ]

    if not valid_arrays:
        raise ValueError(
            "沒有可用的 Cooling Time 陣列"
        )

    for array in valid_arrays:
        if array.ndim != 2:
            raise ValueError(
                "Cooling Time CSV 必須為 2D 陣列"
            )

    rows = min(
        array.shape[0]
        for array in valid_arrays
    )

    cols = min(
        array.shape[1]
        for array in valid_arrays
    )

    if rows <= 0 or cols <= 0:
        raise ValueError(
            "Cooling Time CSV 尺寸無效"
        )

    result = []

    for array in arrays:
        if array is None:
            result.append(None)
        else:
            result.append(
                np.asarray(
                    array,
                    dtype=float,
                )[:rows, :cols]
            )

    return result


# =========================================================
# 18. 讀取 Layer n 原始 Cooling Time
# =========================================================
def load_display_layer_z(
    ui_layer: int,
):
    """
    主圖只使用 Layer n 的原始 Cooling Time。

    不使用 n-1 補值。
    不對 n 層乘倍率。
    n+1 只在後續步驟中改變局部顏色深淺。
    """
    ui_layer = int(ui_layer)
    csv_mapping = scan_cooling_csvs_by_index()

    current_index = (
        ui_layer_to_current_csv_index(
            ui_layer
        )
    )

    if current_index not in csv_mapping:
        raise FileNotFoundError(
            f"找不到 Layer n CSV："
            f"cooling_layer_1_{current_index}.csv"
        )

    current_path = csv_mapping[
        current_index
    ]

    z_current = (
        load_single_cooling_csv_as_z(
            current_path
        )
    )

    return z_current, {
        "mode": "raw_n_layer",
        "ui_layer": ui_layer,
        "current_index": current_index,
        "current_file": current_path.name,
        "rule": (
            f"Display Layer {ui_layer} 只使用 "
            f"{current_path.name} 的原始 Cooling Time；"
            "不使用 n-1 補值，也不對 n 層乘倍率。"
        ),
    }


# =========================================================
# 19. 讀取 Layer n+1 原始 Cooling Time
# =========================================================
def load_next_layer_z(
    ui_layer: int,
):
    """
    當 Slider 選擇 Layer n 時，讀取下一層 Layer n+1。

    例如：
        Slider = Layer 4
        n CSV   = cooling_layer_1_3.csv
        n+1 CSV = cooling_layer_1_4.csv
    """
    ui_layer = int(ui_layer)
    csv_mapping = scan_cooling_csvs_by_index()

    next_index = ui_layer_to_next_csv_index(
        ui_layer
    )

    if next_index not in csv_mapping:
        raise FileNotFoundError(
            f"Layer {ui_layer} 沒有下一層 "
            f"Layer {ui_layer + 1} CSV："
            f"cooling_layer_1_{next_index}.csv"
        )

    next_path = csv_mapping[
        next_index
    ]

    z_next = load_single_cooling_csv_as_z(
        next_path
    )

    return z_next, {
        "mode": "raw_n_plus_1_layer",
        "base_ui_layer": ui_layer,
        "display_ui_layer": ui_layer + 1,
        "next_index": next_index,
        "next_file": next_path.name,
        "rule": (
            f"顯示 Layer n+1 = Layer {ui_layer + 1}；"
            f"使用 {next_path.name} 原始 Cooling Time。"
        ),
    }


# =========================================================
# 20. 計算 n+1 對 n 的局部梯度深淺遮罩
# =========================================================
def calculate_next_layer_gradient_shading(
    ui_layer: int,
    z_base,
):
    """
    n+1 只改變顏色深淺，不改變 Layer n 的基本圖形。

    步驟：
    1. 讀取原始 Layer n 與 Layer n+1。
    2. 計算 n+1 比 n 多出的時間：
           time_increase = max(n+1 - n, 0)

       只有 n+1 > n 的位置才加深。
       n+1 <= n 的位置維持原本 Layer n 顏色。

    3. 將正向時間增加量正規化到 0～1。
    4. 以透明深藍遮罩疊加到原本 Layer n Heatmap。

    回傳：
        base_crop       原本 Layer n 顯示值
        gradient_value  n+1 比 n 多出的時間
        gradient_norm   0～1 顏色加深比例
        info            梯度資訊
    """
    ui_layer = int(ui_layer)
    csv_mapping = scan_cooling_csvs_by_index()

    current_index = (
        ui_layer_to_current_csv_index(
            ui_layer
        )
    )

    next_index = (
        ui_layer_to_next_csv_index(
            ui_layer
        )
    )

    # 沒有 n+1 時，不加深
    if next_index not in csv_mapping:
        z_base = np.asarray(
            z_base,
            dtype=float,
        )

        empty_gradient = np.full(
            z_base.shape,
            np.nan,
            dtype=float,
        )

        empty_norm = np.zeros(
            z_base.shape,
            dtype=float,
        )

        return (
            z_base,
            empty_gradient,
            empty_norm,
            {
                "has_next_layer": False,
                "current_index": current_index,
                "next_index": next_index,
                "current_file": (
                    csv_mapping[current_index].name
                    if current_index in csv_mapping
                    else None
                ),
                "next_file": None,
                "gradient_max_reference": None,
                "valid_count": 0,
                "affected_count": 0,
                "affected_ratio": 0.0,
                "n_contribution": 0.0,
                "next_contribution": 0.0,
                "n_influence_ratio": 100.0,
                "next_influence_ratio": 0.0,
                "rule": (
                    f"Layer {ui_layer} 沒有 Layer "
                    f"{ui_layer + 1} CSV，"
                    "因此不套用 n+1 深淺影響。"
                ),
            },
        )

    current_path = csv_mapping[
        current_index
    ]

    next_path = csv_mapping[
        next_index
    ]

    z_current_raw = (
        load_single_cooling_csv_as_z(
            current_path
        )
    )

    z_next_raw = (
        load_single_cooling_csv_as_z(
            next_path
        )
    )

    (
        z_base_crop,
        z_current_crop,
        z_next_crop,
    ) = crop_arrays_to_common_shape(
        z_base,
        z_current_raw,
        z_next_raw,
    )

    valid_mask = (
        (z_current_crop >= LOW_VALUE_THRESHOLD)
        & (z_next_crop >= LOW_VALUE_THRESHOLD)
    )

    # 只保留 n+1 比 n 時間更長的部分。
    # n+1 <= n 時，增加量為 0，因此顏色不變。
    gradient_value = np.maximum(
        z_next_crop - z_current_crop,
        0.0,
    )

    gradient_value = np.where(
        valid_mask,
        gradient_value,
        np.nan,
    )

    finite_gradient = gradient_value[
        np.isfinite(gradient_value)
    ]

    positive_gradient = finite_gradient[
        finite_gradient > GRADIENT_MIN_DIFFERENCE
    ]

    if positive_gradient.size == 0:
        gradient_norm = np.zeros(
            z_base_crop.shape,
            dtype=float,
        )

        max_reference = None

    else:
        max_reference = float(
            np.percentile(
                positive_gradient,
                GRADIENT_NORMALIZE_PERCENTILE,
            )
        )

        if max_reference <= GRADIENT_MIN_DIFFERENCE:
            gradient_norm = np.zeros(
                z_base_crop.shape,
                dtype=float,
            )
        else:
            gradient_norm = (
                gradient_value
                - GRADIENT_MIN_DIFFERENCE
            ) / (
                max_reference
                - GRADIENT_MIN_DIFFERENCE
            )

            gradient_norm = np.clip(
                gradient_norm,
                0.0,
                1.0,
            )

            gradient_norm = np.where(
                np.isfinite(gradient_norm),
                gradient_norm,
                0.0,
            )

    # -----------------------------------------------------
    # 計算 Layer n 與 Layer n+1 的實際顏色影響比例
    #
    # Layer n 貢獻：
    #     Σ CoolingTime(n)
    #
    # Layer n+1 貢獻：
    #     Σ max(CoolingTime(n+1) - CoolingTime(n), 0)
    #
    # 因為 n+1 只負責「額外加深」，所以只計算正向增加量。
    # -----------------------------------------------------
    valid_count = int(
        np.count_nonzero(valid_mask)
    )

    affected_mask = (
        valid_mask
        & (z_next_crop > z_current_crop)
    )

    affected_count = int(
        np.count_nonzero(affected_mask)
    )

    affected_ratio = (
        affected_count / valid_count * 100.0
        if valid_count > 0
        else 0.0
    )

    n_contribution = float(
        np.sum(
            np.where(
                valid_mask,
                z_current_crop,
                0.0,
            )
        )
    )

    next_contribution = float(
        np.sum(
            np.where(
                np.isfinite(gradient_value),
                gradient_value,
                0.0,
            )
        )
    )

    total_contribution = (
        n_contribution
        + next_contribution
    )

    if total_contribution > 1e-12:
        n_influence_ratio = (
            n_contribution
            / total_contribution
            * 100.0
        )

        next_influence_ratio = (
            next_contribution
            / total_contribution
            * 100.0
        )

    else:
        n_influence_ratio = 100.0
        next_influence_ratio = 0.0

    return (
        z_base_crop,
        gradient_value,
        gradient_norm,
        {
            "has_next_layer": True,
            "current_index": current_index,
            "next_index": next_index,
            "current_file": current_path.name,
            "next_file": next_path.name,
            "gradient_max_reference": max_reference,
            "valid_count": valid_count,
            "affected_count": affected_count,
            "affected_ratio": affected_ratio,
            "n_contribution": n_contribution,
            "next_contribution": next_contribution,
            "n_influence_ratio": n_influence_ratio,
            "next_influence_ratio": next_influence_ratio,
            "rule": (
                f"Layer {ui_layer + 1} 不取代 "
                f"Layer {ui_layer}；"
                "只有當 n+1 Cooling Time 大於 n 時，"
                "才依 n+1-n 在相同位置增加深色遮罩。"
            ),
        },
    )


# =========================================================
# 21. 建立 X/Y 座標
# =========================================================
def build_display_xy(z):
    n_rows, n_cols = z.shape

    x_mm = (
        np.linspace(
            DISPLAY_X_START_MM,
            DISPLAY_X_END_MM,
            n_cols,
        )
        if n_cols > 1
        else np.array(
            [DISPLAY_X_START_MM],
            dtype=float,
        )
    )

    y_mm = (
        np.linspace(
            DISPLAY_Y_START_MM,
            DISPLAY_Y_END_MM,
            n_rows,
        )
        if n_rows > 1
        else np.array(
            [DISPLAY_Y_START_MM],
            dtype=float,
        )
    )

    return x_mm, y_mm


# =========================================================
# 22. 裁切品質分析範圍
# =========================================================
def crop_z_by_quality_xy_range(
    z,
    x_mm,
    y_mm,
):
    x_min = min(
        QUALITY_X_START_MM,
        QUALITY_X_END_MM,
    )

    x_max = max(
        QUALITY_X_START_MM,
        QUALITY_X_END_MM,
    )

    y_min = min(
        QUALITY_Y_START_MM,
        QUALITY_Y_END_MM,
    )

    y_max = max(
        QUALITY_Y_START_MM,
        QUALITY_Y_END_MM,
    )

    x_mask = (
        (x_mm >= x_min)
        & (x_mm <= x_max)
    )

    y_mask = (
        (y_mm >= y_min)
        & (y_mm <= y_max)
    )

    if (
        not np.any(x_mask)
        or not np.any(y_mask)
    ):
        raise ValueError(
            "品質分析範圍沒有資料點"
        )

    z_crop = z[
        np.ix_(
            y_mask,
            x_mask,
        )
    ]

    return (
        z_crop,
        int(np.sum(x_mask)),
        int(np.sum(y_mask)),
    )


# =========================================================
# 23. Cooling Time 品質分析
# =========================================================
def calc_cooling_quality(z):
    arr = pd.Series(
        np.asarray(z).ravel()
    )

    arr = pd.to_numeric(
        arr,
        errors="coerce",
    ).to_numpy(dtype=float)

    arr = arr[
        np.isfinite(arr)
    ]

    if EXCLUDE_BELOW_THRESHOLD_FOR_QUALITY:
        arr = arr[
            arr >= LOW_VALUE_THRESHOLD
        ]

    if arr.size == 0:
        return {
            "status": "INFO",
            "color": "secondary",
            "title": (
                "無有效 Cooling Time 數值"
            ),
            "reason": (
                "目前 CSV 沒有 "
                f">= {LOW_VALUE_THRESHOLD:g} "
                "的可計算數值"
            ),
            "mean": None,
            "std": None,
            "cv": None,
            "min": None,
            "max": None,
            "p5": None,
            "p95": None,
            "range_ratio": None,
            "count": 0,
        }

    mean_v = float(
        np.mean(arr)
    )

    std_v = float(
        np.std(arr)
    )

    min_v = float(
        np.min(arr)
    )

    max_v = float(
        np.max(arr)
    )

    p5_v = float(
        np.percentile(
            arr,
            5,
        )
    )

    p95_v = float(
        np.percentile(
            arr,
            95,
        )
    )

    robust_range_v = float(
        p95_v - p5_v
    )

    denominator = abs(
        mean_v
    )

    if denominator < 1e-12:
        cv_v = float("inf")
        range_ratio_v = float("inf")
    else:
        cv_v = (
            std_v
            / denominator
        )

        range_ratio_v = (
            robust_range_v
            / denominator
        )

    if (
        cv_v <= COOLING_CV_PASS
        and range_ratio_v
        <= COOLING_RANGE_PASS
    ):
        status = "PASS"
        color = "success"
        title = (
            "良好：Cooling Time 分布均勻"
        )

    elif (
        cv_v <= COOLING_CV_WARN
        and range_ratio_v
        <= COOLING_RANGE_WARN
    ):
        status = "WARN"
        color = "warning"
        title = (
            "注意：Cooling Time 有些微不均勻"
        )

    else:
        status = "FAIL"
        color = "danger"
        title = (
            "不良：Cooling Time 分布不均勻"
        )

    return {
        "status": status,
        "color": color,
        "title": title,
        "reason": (
            f"CV = {cv_v:.3f}，"
            f"P95-P5/平均 = "
            f"{range_ratio_v:.3f}"
        ),
        "mean": mean_v,
        "std": std_v,
        "cv": cv_v,
        "min": min_v,
        "max": max_v,
        "p5": p5_v,
        "p95": p95_v,
        "range_ratio": range_ratio_v,
        "count": int(arr.size),
    }


def fmt_metric(
    value,
    digits=3,
):
    if value is None:
        return "--"

    if not np.isfinite(value):
        return "∞"

    return f"{value:.{digits}f}"


# =========================================================
# 24. Navbar
# =========================================================
navbar = dbc.Navbar(
    dbc.Container(
        [
            html.Div(
                [
                    html.I(
                        className=(
                            "bi bi-hourglass-split me-2"
                        )
                    ),
                    "Cooling Time Viewer - n+1 Longer Means Darker",
                ],
                className="fw-bold",
            ),
        ],
        fluid=True,
    ),
    color="primary",
    dark=True,
    sticky="top",
)


# =========================================================
# 25. Sidebar
# =========================================================
def navlink(
    label: str,
    key: str,
    icon: str,
):
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
        active=(key == "step3b"),
    )


sidebar = html.Div(
    [
        html.H5(
            "Navigation",
            className="text-white-50",
        ),

        html.Hr(
            className="my-2",
        ),

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
    className="bg-dark p-3 h-100",
    style={
        "width": "240px",
        "position": "fixed",
        "top": "56px",
        "left": 0,
        "overflowY": "auto",
        "height": "100%",
        "zIndex": 1030,
    },
)


# =========================================================
# 26. Main UI
# =========================================================
main_card = dbc.Card(
    [
        dbc.CardHeader(
            html.Div(
                [
                    html.I(
                        className="bi bi-image me-2"
                    ),
                    "Cooling Time",
                ],
                className="fw-bold",
            )
        ),

        dbc.CardBody(
            [
                html.Div(
                    id="media-status",
                    className="mb-3",
                ),

                dbc.Alert(
                    [
                        html.Div(
                            (
                                "主圖只使用 Layer n 的原始 Cooling Time；"
                                "Layer n+1 只改變局部顏色深淺。"
                            ),
                            className="fw-bold",
                        ),

                        html.Div(
                            (
                                "顏色越深："
                                "代表 CoolingTime(n+1) "
                                "比 CoolingTime(n) 更長。"
                            ),
                            className="small mt-1",
                        ),

                        html.Div(
                            (
                                "當 n+1 ≤ n 時顏色不變；"
                                "n+1 不會取代 n，也不改變 n 的數值。"
                            ),
                            className=(
                                "small text-muted mt-1"
                            ),
                        ),
                    ],
                    color="secondary",
                    className="mb-3",
                ),

                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Label(
                                    "Display Mode / 顯示模式",
                                    className="fw-bold mb-2",
                                ),

                                dcc.Dropdown(
                                    id="cooling-display-mode",
                                    options=[
                                        {
                                            "label": (
                                                "Layer n / "
                                                "顯示目前 n 層"
                                            ),
                                            "value": "n",
                                        },
                                        {
                                            "label": (
                                                "Layer n+1 / "
                                                "顯示下一層"
                                            ),
                                            "value": "n_plus_1",
                                        },
                                        {
                                            "label": (
                                                "n+1 → n Influence / "
                                                "n+1 對 n 的影響"
                                            ),
                                            "value": "influence",
                                        },
                                    ],
                                    value="n",
                                    clearable=False,
                                    searchable=False,
                                    style={
                                        "color": "#111111",
                                    },
                                ),
                            ],
                            xs=12,
                            md=6,
                        ),
                    ],
                    className="mb-3",
                ),

                dcc.Slider(
                    id="cooling-layer-slider",
                    min=LAYER_MIN_UI,
                    max=LAYER_MAX_UI,
                    step=1,
                    value=LAYER_MIN_UI,
                    included=False,
                    marks=make_slider_marks(
                        LAYER_MIN_UI,
                        LAYER_MAX_UI,
                    ),
                    tooltip={
                        "placement": "bottom",
                        "always_visible": True,
                    },
                ),

                html.Div(
                    id="cooling-layer-info",
                    className="mt-3",
                ),

                dcc.Loading(
                    type="circle",
                    children=dcc.Graph(
                        id="cooling-heatmap",
                        style=HEATMAP_STYLE,
                        config=GRAPH_CONFIG,
                        figure=go.Figure(),
                    ),
                ),

                html.Div(
                    id="cooling-influence-panel",
                    className="mt-3",
                ),

                html.Div(
                    id="cooling-quality-panel",
                    className="mt-4",
                    style={
                        "paddingBottom": "80px",
                    },
                ),
            ],
        ),
    ]
)


# =========================================================
# 27. Layout
# =========================================================
app.layout = html.Div(
    [
        navbar,
        sidebar,

        html.Div(
            [
                main_card,
            ],
            style={
                "marginLeft": "260px",
                "padding": "12px",
                "paddingTop": "5px",
                "paddingBottom": "200px",
                "width": "calc(100% - 260px)",
                "overflowX": "hidden",
            },
        ),
    ],
    style={
        "minHeight": "100vh",
    },
)


# =========================================================
# 28. Slider init
# =========================================================
@app.callback(
    [
        Output(
            "cooling-layer-slider",
            "min",
        ),
        Output(
            "cooling-layer-slider",
            "max",
        ),
        Output(
            "cooling-layer-slider",
            "marks",
        ),
        Output(
            "cooling-layer-slider",
            "value",
        ),
        Output(
            "media-status",
            "children",
        ),
    ],
    Input(
        "cooling-layer-slider",
        "id",
    ),
    prevent_initial_call=False,
)
def init_slider(_):
    mapping = scan_display_layers()

    if not mapping:
        return (
            LAYER_MIN_UI,
            LAYER_MAX_UI,
            make_slider_marks(
                LAYER_MIN_UI,
                LAYER_MAX_UI,
            ),
            LAYER_MIN_UI,
            dbc.Alert(
                (
                    f"⚠️ 找不到 CSV："
                    f"{FIXED_CSV_DIR}"
                ),
                color="warning",
            ),
        )

    layers = sorted(
        mapping.keys()
    )

    min_layer = layers[0]
    max_layer = layers[-1]

    return (
        min_layer,
        max_layer,
        make_slider_marks(
            min_layer,
            max_layer,
        ),
        min_layer,
        "",
    )


# =========================================================
# 29. Layer info
# =========================================================
@app.callback(
    Output(
        "cooling-layer-info",
        "children",
    ),
    [
        Input(
            "cooling-layer-slider",
            "value",
        ),
        Input(
            "cooling-display-mode",
            "value",
        ),
    ],
    prevent_initial_call=False,
)
def update_layer_info(
    layer_value,
    display_mode,
):
    if layer_value is None:
        layer_value = LAYER_MIN_UI

    if display_mode is None:
        display_mode = "n"

    layer_value = int(layer_value)

    csv_mapping = scan_cooling_csvs_by_index()

    current_index = (
        ui_layer_to_current_csv_index(
            layer_value
        )
    )

    next_index = (
        ui_layer_to_next_csv_index(
            layer_value
        )
    )

    current_name = (
        csv_mapping[current_index].name
        if current_index in csv_mapping
        else "找不到 n 層 CSV"
    )

    next_name = (
        csv_mapping[next_index].name
        if next_index in csv_mapping
        else "無下一層 CSV"
    )

    if display_mode == "n":
        title = (
            f"目前顯示：Layer n = "
            f"Layer {layer_value}"
        )

        detail = (
            f"檔案：{current_name}"
        )

        explanation = (
            "只顯示 Layer n 原始 Cooling Time，"
            "不加入 n+1 顏色影響。"
        )

        color = "primary"

    elif display_mode == "n_plus_1":
        title = (
            f"目前顯示：Layer n+1 = "
            f"Layer {layer_value + 1}"
        )

        detail = (
            f"檔案：{next_name}"
        )

        explanation = (
            "Slider 數值仍代表基準 Layer n；"
            "畫面顯示它的下一層 n+1 原始 Cooling Time。"
        )

        color = "info"

    else:
        title = (
            f"目前顯示：Layer {layer_value + 1} "
            f"對 Layer {layer_value} 的影響"
        )

        detail = (
            f"Layer n：{current_name}｜"
            f"Layer n+1：{next_name}"
        )

        explanation = (
            "以 Layer n 原始圖為主；"
            "只有 n+1 Cooling Time 大於 n 的位置，"
            "才依 n+1-n 增加深色。"
        )

        color = "secondary"

    return dbc.Alert(
        [
            html.Div(
                [
                    html.I(
                        className=(
                            "bi bi-layers me-2"
                        )
                    ),
                    title,
                ],
                className="fw-bold",
            ),

            html.Div(
                detail,
                className="small mt-1",
            ),

            html.Div(
                explanation,
                className=(
                    "small text-muted mt-1"
                ),
            ),
        ],
        color=color,
        className="mb-0",
    )


# =========================================================
# 30. Heatmap
# =========================================================
@app.callback(
    Output(
        "cooling-heatmap",
        "figure",
    ),
    [
        Input(
            "cooling-layer-slider",
            "value",
        ),
        Input(
            "cooling-display-mode",
            "value",
        ),
    ],
    prevent_initial_call=False,
)
def update_heatmap(
    layer_value,
    display_mode,
):
    if layer_value is None:
        layer_value = LAYER_MIN_UI

    if display_mode is None:
        display_mode = "n"

    layer_value = int(layer_value)
    mapping = scan_display_layers()

    if (
        not mapping
        or layer_value not in mapping
    ):
        return go.Figure()

    try:
        # -------------------------------------------------
        # 模式 1：只顯示 Layer n 原始 Cooling Time
        # -------------------------------------------------
        if display_mode == "n":
            z_display, _ = load_display_layer_z(
                layer_value
            )

            x_mm, y_mm = build_display_xy(
                z_display
            )

            fig = go.Figure(
                go.Heatmap(
                    z=z_display,
                    x=x_mm,
                    y=y_mm,
                    colorscale=COOLING_COLORSCALE,
                    zmin=COOLING_ZMIN,
                    zmax=COOLING_ZMAX,
                    zsmooth=False,
                    colorbar=dict(
                        title=dict(
                            text="Time (μs)",
                            side="right",
                        ),
                        thickness=18,
                        len=0.9,
                    ),
                    hovertemplate=(
                        "X = %{x:.3f} mm<br>"
                        "Y = %{y:.3f} mm<br>"
                        "Layer n Cooling Time = "
                        "%{z:.3f} μs"
                        "<extra></extra>"
                    ),
                    name="Layer n",
                )
            )

            title_text = (
                "Cooling Time"
                "<br>"
                f"Layer n = Layer {layer_value}"
            )

        # -------------------------------------------------
        # 模式 2：只顯示 Layer n+1 原始 Cooling Time
        # -------------------------------------------------
        elif display_mode == "n_plus_1":
            z_display, _ = load_next_layer_z(
                layer_value
            )

            x_mm, y_mm = build_display_xy(
                z_display
            )

            fig = go.Figure(
                go.Heatmap(
                    z=z_display,
                    x=x_mm,
                    y=y_mm,
                    colorscale=COOLING_COLORSCALE,
                    zmin=COOLING_ZMIN,
                    zmax=COOLING_ZMAX,
                    zsmooth=False,
                    colorbar=dict(
                        title=dict(
                            text="Time (μs)",
                            side="right",
                        ),
                        thickness=18,
                        len=0.9,
                    ),
                    hovertemplate=(
                        "X = %{x:.3f} mm<br>"
                        "Y = %{y:.3f} mm<br>"
                        "Layer n+1 Cooling Time = "
                        "%{z:.3f} μs"
                        "<extra></extra>"
                    ),
                    name="Layer n+1",
                )
            )

            title_text = (
                "Cooling Time"
                "<br>"
                f"Layer n+1 = Layer "
                f"{layer_value + 1}"
            )

        # -------------------------------------------------
        # 模式 3：以 n 為主，顯示 n+1 對 n 的影響
        # -------------------------------------------------
        else:
            z_base, _ = load_display_layer_z(
                layer_value
            )

            (
                z_base,
                gradient_value,
                gradient_norm,
                gradient_info,
            ) = calculate_next_layer_gradient_shading(
                layer_value,
                z_base,
            )

            x_mm, y_mm = build_display_xy(
                z_base
            )

            custom_data = np.dstack(
                (
                    z_base,
                    np.where(
                        np.isfinite(
                            gradient_value
                        ),
                        gradient_value,
                        np.nan,
                    ),
                    gradient_norm,
                )
            )

            fig = go.Figure()

            # Layer n 原始主圖
            fig.add_trace(
                go.Heatmap(
                    z=z_base,
                    x=x_mm,
                    y=y_mm,
                    colorscale=COOLING_COLORSCALE,
                    zmin=COOLING_ZMIN,
                    zmax=COOLING_ZMAX,
                    zsmooth=False,
                    colorbar=dict(
                        title=dict(
                            text="Time (μs)",
                            side="right",
                        ),
                        thickness=18,
                        len=0.9,
                    ),
                    hovertemplate=(
                        "X = %{x:.3f} mm<br>"
                        "Y = %{y:.3f} mm<br>"
                        "Layer n Cooling Time = "
                        "%{z:.3f} μs"
                        "<extra></extra>"
                    ),
                    name="Layer n Cooling Time",
                )
            )

            # n+1 時間較長處才加深
            if gradient_info[
                "has_next_layer"
            ]:
                fig.add_trace(
                    go.Heatmap(
                        z=gradient_norm,
                        x=x_mm,
                        y=y_mm,
                        customdata=custom_data,
                        colorscale=(
                            GRADIENT_OVERLAY_COLORSCALE
                        ),
                        zmin=0.0,
                        zmax=1.0,
                        zsmooth=False,
                        showscale=False,
                        hovertemplate=(
                            "X = %{x:.3f} mm<br>"
                            "Y = %{y:.3f} mm<br>"
                            "Layer n Cooling Time = "
                            "%{customdata[0]:.3f} μs<br>"
                            "n+1 比 n 多 = "
                            "%{customdata[1]:.3f} μs<br>"
                            "顏色加深比例 = "
                            "%{customdata[2]:.3f}"
                            "<extra></extra>"
                        ),
                        name=(
                            "n+1 對 n 的顏色影響"
                        ),
                    )
                )

            title_text = (
                "Cooling Time Influence"
                "<br>"
                f"Layer {layer_value} 為主｜"
                f"Layer {layer_value + 1} "
                "時間較長處加深"
            )

    except Exception as error:
        fig = go.Figure()

        fig.update_layout(
            template="plotly_dark",
            title=(
                f"Cooling Time 載入失敗："
                f"{error}"
            ),
            annotations=[
                dict(
                    text=str(error),
                    x=0.5,
                    y=0.5,
                    xref="paper",
                    yref="paper",
                    showarrow=False,
                )
            ],
        )

        return fig

    fig.update_layout(
        template="plotly_dark",
        title=dict(
            text=title_text,
            x=0.5,
            xanchor="center",
        ),
        margin=dict(
            l=60,
            r=70,
            t=82,
            b=60,
        ),
        xaxis=dict(
            title="X (mm)",
            range=[
                DISPLAY_X_START_MM,
                DISPLAY_X_END_MM,
            ],
            automargin=True,
        ),
        yaxis=dict(
            title="Y (mm)",
            range=[
                DISPLAY_Y_START_MM,
                DISPLAY_Y_END_MM,
            ],
            scaleanchor="x",
            scaleratio=1,
            automargin=True,
        ),
        uirevision=(
            f"cooling-time-{display_mode}"
        ),
        showlegend=False,
    )

    return fig


# =========================================================
# 31. Layer n / Layer n+1 影響比例
# =========================================================
@app.callback(
    Output(
        "cooling-influence-panel",
        "children",
    ),
    [
        Input(
            "cooling-layer-slider",
            "value",
        ),
        Input(
            "cooling-display-mode",
            "value",
        ),
    ],
    prevent_initial_call=False,
)
def update_influence_panel(
    layer_value,
    display_mode,
):
    if display_mode != "influence":
        return ""

    if layer_value is None:
        layer_value = LAYER_MIN_UI

    layer_value = int(layer_value)

    mapping = scan_display_layers()

    if (
        not mapping
        or layer_value not in mapping
    ):
        return dbc.Alert(
            "目前 Layer 沒有 CSV",
            color="warning",
        )

    try:
        z_base, _ = load_display_layer_z(
            layer_value
        )

        (
            _,
            _,
            _,
            influence,
        ) = calculate_next_layer_gradient_shading(
            layer_value,
            z_base,
        )

    except Exception as error:
        return dbc.Alert(
            f"影響比例計算失敗：{error}",
            color="danger",
        )

    n_ratio = float(
        np.clip(
            influence.get(
                "n_influence_ratio",
                100.0,
            ),
            0.0,
            100.0,
        )
    )

    next_ratio = float(
        np.clip(
            influence.get(
                "next_influence_ratio",
                0.0,
            ),
            0.0,
            100.0,
        )
    )

    affected_ratio = float(
        influence.get(
            "affected_ratio",
            0.0,
        )
    )

    valid_count = int(
        influence.get(
            "valid_count",
            0,
        )
    )

    affected_count = int(
        influence.get(
            "affected_count",
            0,
        )
    )

    return dbc.Card(
        [
            dbc.CardHeader(
                html.Div(
                    [
                        html.I(
                            className=(
                                "bi bi-percent me-2"
                            )
                        ),
                        (
                            "Layer n / Layer n+1 "
                            "Color Influence Ratio / "
                            "顏色影響比例"
                        ),
                    ],
                    className="fw-bold",
                )
            ),

            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody(
                                        [
                                            html.Div(
                                                (
                                                    "Layer n "
                                                    "基礎影響"
                                                ),
                                                className=(
                                                    "small text-muted"
                                                ),
                                            ),

                                            html.H4(
                                                f"{n_ratio:.2f}%",
                                                className="mb-0",
                                            ),
                                        ],
                                        className=(
                                            "text-center p-2"
                                        ),
                                    ),
                                    outline=True,
                                    color="primary",
                                    className="h-100",
                                ),
                                xs=12,
                                md=4,
                            ),

                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody(
                                        [
                                            html.Div(
                                                (
                                                    "Layer n+1 "
                                                    "加深影響"
                                                ),
                                                className=(
                                                    "small text-muted"
                                                ),
                                            ),

                                            html.H4(
                                                f"{next_ratio:.2f}%",
                                                className="mb-0",
                                            ),
                                        ],
                                        className=(
                                            "text-center p-2"
                                        ),
                                    ),
                                    outline=True,
                                    color="info",
                                    className="h-100",
                                ),
                                xs=12,
                                md=4,
                            ),

                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody(
                                        [
                                            html.Div(
                                                (
                                                    "n+1 造成加深的 "
                                                    "面積比例"
                                                ),
                                                className=(
                                                    "small text-muted"
                                                ),
                                            ),

                                            html.H4(
                                                (
                                                    f"{affected_ratio:.2f}%"
                                                ),
                                                className="mb-0",
                                            ),
                                        ],
                                        className=(
                                            "text-center p-2"
                                        ),
                                    ),
                                    outline=True,
                                    color="secondary",
                                    className="h-100",
                                ),
                                xs=12,
                                md=4,
                            ),
                        ],
                        className="g-2",
                    ),

                    html.Div(
                        [
                            html.Div(
                                (
                                    f"Layer n "
                                    f"{n_ratio:.2f}%"
                                ),
                                style={
                                    "width": (
                                        f"{n_ratio:.6f}%"
                                    ),
                                    "background": "#0d6efd",
                                    "color": "white",
                                    "textAlign": "center",
                                    "whiteSpace": "nowrap",
                                    "overflow": "hidden",
                                    "minHeight": "30px",
                                    "lineHeight": "30px",
                                },
                            ),

                            html.Div(
                                (
                                    f"Layer n+1 "
                                    f"{next_ratio:.2f}%"
                                ),
                                style={
                                    "width": (
                                        f"{next_ratio:.6f}%"
                                    ),
                                    "background": "#0dcaf0",
                                    "color": "#111111",
                                    "textAlign": "center",
                                    "whiteSpace": "nowrap",
                                    "overflow": "hidden",
                                    "minHeight": "30px",
                                    "lineHeight": "30px",
                                },
                            ),
                        ],
                        style={
                            "display": "flex",
                            "width": "100%",
                            "borderRadius": "6px",
                            "overflow": "hidden",
                            "background": "#343a40",
                        },
                        className="mt-3",
                    ),

                    dbc.Alert(
                        [
                            html.Div(
                                (
                                    "比例計算："
                                    "Layer n 貢獻 = "
                                    "Σ CoolingTime(n)；"
                                    "Layer n+1 貢獻 = "
                                    "Σ max(n+1-n, 0)。"
                                ),
                                className="fw-bold",
                            ),

                            html.Div(
                                (
                                    f"有效比較點："
                                    f"{valid_count:,}；"
                                    f"其中 n+1 > n："
                                    f"{affected_count:,} 點。"
                                ),
                                className="small mt-1",
                            ),
                        ],
                        color="secondary",
                        className="mt-3 mb-0",
                    ),
                ]
            ),
        ]
    )


# =========================================================
# 32. Quality
# =========================================================
@app.callback(
    Output(
        "cooling-quality-panel",
        "children",
    ),
    [
        Input(
            "cooling-layer-slider",
            "value",
        ),
        Input(
            "cooling-display-mode",
            "value",
        ),
    ],
    prevent_initial_call=False,
)
def update_quality(
    layer_value,
    display_mode,
):
    if layer_value is None:
        layer_value = LAYER_MIN_UI

    if display_mode is None:
        display_mode = "n"

    layer_value = int(layer_value)
    mapping = scan_display_layers()

    if (
        not mapping
        or layer_value not in mapping
    ):
        return dbc.Alert(
            "目前 Layer 沒有 CSV",
            color="warning",
        )

    try:
        if display_mode == "n_plus_1":
            z, _ = load_next_layer_z(
                layer_value
            )

            quality_title = (
                "Cooling Time 品質分析 - "
                f"Layer n+1 = "
                f"Layer {layer_value + 1}"
            )

            quality_note = (
                "目前品質分析使用 Layer n+1 "
                "原始 Cooling Time。"
            )

        else:
            z, _ = load_display_layer_z(
                layer_value
            )

            quality_title = (
                "Cooling Time 品質分析 - "
                f"Layer n = Layer "
                f"{layer_value}"
            )

            if display_mode == "influence":
                quality_note = (
                    "影響模式的品質分析仍使用 "
                    "Layer n 原始 Cooling Time；"
                    "n+1 深色遮罩不改變 Mean、Std 或 CV。"
                )
            else:
                quality_note = (
                    "目前品質分析使用 Layer n "
                    "原始 Cooling Time。"
                )

    except Exception as error:
        return dbc.Alert(
            f"Layer 載入失敗：{error}",
            color="danger",
        )

    x_mm, y_mm = build_display_xy(
        z
    )

    (
        z_quality,
        q_cols,
        q_rows,
    ) = crop_z_by_quality_xy_range(
        z,
        x_mm,
        y_mm,
    )

    quality = calc_cooling_quality(
        z_quality
    )

    return dbc.Card(
        [
            dbc.CardHeader(
                quality_title
            ),

            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody(
                                        [
                                            html.Div(
                                                "Mean"
                                            ),

                                            html.H4(
                                                fmt_metric(
                                                    quality[
                                                        "mean"
                                                    ]
                                                )
                                            ),
                                        ]
                                    )
                                )
                            ),

                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody(
                                        [
                                            html.Div(
                                                "Std"
                                            ),

                                            html.H4(
                                                fmt_metric(
                                                    quality[
                                                        "std"
                                                    ]
                                                )
                                            ),
                                        ]
                                    )
                                )
                            ),

                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody(
                                        [
                                            html.Div(
                                                "CV"
                                            ),

                                            html.H4(
                                                fmt_metric(
                                                    quality[
                                                        "cv"
                                                    ]
                                                )
                                            ),
                                        ]
                                    )
                                )
                            ),
                        ]
                    ),

                    dbc.Alert(
                        [
                            html.Div(
                                quality["title"],
                                style={
                                    "fontWeight": "700",
                                },
                            ),

                            html.Div(
                                quality["reason"],
                            ),

                            html.Div(
                                (
                                    f"範圍："
                                    f"X={QUALITY_X_START_MM}"
                                    f"~{QUALITY_X_END_MM}, "
                                    f"Y={QUALITY_Y_START_MM}"
                                    f"~{QUALITY_Y_END_MM}"
                                )
                            ),

                            html.Div(
                                (
                                    f"{q_cols} cols × "
                                    f"{q_rows} rows"
                                )
                            ),

                            html.Div(
                                (
                                    "品質分析有效門檻："
                                    f">= "
                                    f"{LOW_VALUE_THRESHOLD:g}"
                                )
                            ),

                            html.Div(
                                quality_note,
                                className=(
                                    "small text-muted mt-1"
                                ),
                            ),
                        ],
                        color=quality["color"],
                        className="mt-3",
                    ),
                ]
            ),
        ]
    )


# =========================================================
# 33. MAIN
# =========================================================
if __name__ == "__main__":
    mapping = scan_display_layers()

    print("=" * 78)
    print(
        "🚀 Dash running on "
        "http://127.0.0.1:8077"
    )
    print(
        f"📁 Cooling CSV："
        f"{FIXED_CSV_DIR}"
    )
    print(
        f"📁 資料夾存在："
        f"{FIXED_CSV_DIR.exists()}"
    )
    print(
        f"📄 可顯示 Layer 數量："
        f"{len(mapping)}"
    )

    print(
        "📌 Layer n 顯示規則："
        "只使用 n 層原始 Cooling Time；"
        "不乘倍率、不補 n-1"
    )

    print(
        "📋 顯示模式："
        "Layer n／Layer n+1／"
        "n+1 對 n 的影響"
    )

    print(
        "🎨 影響模式規則："
        "以 n 為主；只有當 "
        "CoolingTime(n+1) > CoolingTime(n) 時，"
        "才依 n+1-n 增加局部深色遮罩"
    )

    print(
        "🌑 最大遮罩透明度："
        f"{GRADIENT_MAX_OPACITY:.2f}"
    )

    print(
        "📐 梯度正規化百分位："
        f"P{GRADIENT_NORMALIZE_PERCENTILE:g}"
    )

    print("=" * 78)

    serve(
        app.server,
        host="0.0.0.0",
        port=8077,
    )
