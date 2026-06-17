# -*- coding: utf-8 -*-

import re
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import dash_bootstrap_components as dbc

from dash import Dash, html, dcc, Input, Output
from waitress import serve


# =========================================================
# 1. Coverage CSV 資料夾
# =========================================================
COVERAGE_CSV_DIR = Path(
    r"D:\2026Experiment\2026Experiment0612\dash\NIST\3. Simulation\Layer_Coverage\heatmap_csv"
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
# 4. Coverage 三層影響設定
# =========================================================
# 當前層符合門檻時，顯示值放大倍率
CURRENT_LAYER_BOOST = 1.5

# 當前層低於此值時，改用前後相鄰層補值
CURRENT_FILL_THRESHOLD = 1000.0

# 前一層影響權重
PREVIOUS_LAYER_WEIGHT = 1.0

# 下一層影響權重
NEXT_LAYER_WEIGHT = 1.0


# =========================================================
# 5. 下拉選單模式及顏色
# =========================================================
VIEW_MODE_CONFIG = {
    "combined": {
        "label": "Combined：n-1、n、n+1 合併",
        "short_label": "三層合併",
        "colorscale": "Jet",
        "color_description": "Jet 彩色",
    },
    "previous": {
        "label": "Previous Layer：n-1 前一層",
        "short_label": "前一層 n-1",
        "colorscale": "Blues",
        "color_description": "藍色",
    },
    "current": {
        "label": "Current Layer：n 當前層",
        "short_label": "當前層 n",
        "colorscale": "Reds",
        "color_description": "紅色",
    },
    "next": {
        "label": "Next Layer：n+1 下一層",
        "short_label": "下一層 n+1",
        "colorscale": "Greens",
        "color_description": "綠色",
    },
}

DEFAULT_VIEW_MODE = "combined"


# =========================================================
# 6. Heatmap 顯示座標範圍
# =========================================================
DISPLAY_X_START_MM = -5.4
DISPLAY_X_END_MM = 5.4

DISPLAY_Y_START_MM = -5.4
DISPLAY_Y_END_MM = 5.4


# =========================================================
# 7. Coverage 均勻度判斷設定
# =========================================================

# 均勻度判斷使用的中央加工區域
UNIFORMITY_X_START_MM = -4.5
UNIFORMITY_X_END_MM = 4.5

UNIFORMITY_Y_START_MM = -2.5
UNIFORMITY_Y_END_MM = 2.5

# PASS 門檻
UNIFORMITY_CV_PASS = 0.10
UNIFORMITY_RANGE_PASS = 0.25

# WARN 門檻
UNIFORMITY_CV_WARN = 0.20
UNIFORMITY_RANGE_WARN = 0.45

# 相對低值與高值區域判斷
LOW_COVERAGE_FACTOR = 0.60
HIGH_COVERAGE_FACTOR = 1.40

# 邊緣熱累積判斷：
# 邊緣平均值 > 中央平均值 × 此倍率
EDGE_ACCUMULATION_RATIO = 1.20

# 最外圍多少比例視為邊緣
EDGE_BAND_RATIO = 0.10

# False：將 0 納入均勻度計算
# True：排除 0，只分析有 Coverage 的位置
EXCLUDE_ZERO_FOR_UNIFORMITY = False


# =========================================================
# 8. 圖表樣式
# =========================================================
def get_graph_height_css():
    x_range = abs(DISPLAY_X_END_MM - DISPLAY_X_START_MM)
    y_range = abs(DISPLAY_Y_END_MM - DISPLAY_Y_START_MM)

    if x_range <= 0 or y_range <= 0:
        return "clamp(460px,76vh,920px)"

    ratio = y_range / x_range

    return (
        f"clamp("
        f"420px, "
        f"calc((100vw - 360px) * {ratio:.6f}), "
        f"820px"
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
    "minHeight": "420px",
    "margin": "0 auto",
    "marginTop": "8px",
}

INFLUENCE_CHART_STYLE = {
    "width": "100%",
    "height": "410px",
    "minHeight": "360px",
    "margin": "0 auto",
    "marginTop": "4px",
}


# =========================================================
# 8. Dash 初始化
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
            "content": "width=device-width, initial-scale=1",
        }
    ],
)

app.title = "Layer Coverage"


# =========================================================
# 9. Slider Marks
# =========================================================
def make_slider_marks(min_ui: int, max_ui: int):
    step = max((max_ui - min_ui) // 10, 1)

    marks = list(range(min_ui, max_ui + 1, step))

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
# 10. 掃描 Coverage CSV
# =========================================================
def scan_coverage_csvs() -> Dict[int, Path]:
    mapping: Dict[int, Path] = {}

    if not COVERAGE_CSV_DIR.exists():
        print(f"⚠️ Coverage 資料夾不存在：{COVERAGE_CSV_DIR}")
        return mapping

    if not COVERAGE_CSV_DIR.is_dir():
        print(f"⚠️ Coverage 路徑不是資料夾：{COVERAGE_CSV_DIR}")
        return mapping

    csv_files = sorted(COVERAGE_CSV_DIR.glob("*.csv"))

    for csv_path in csv_files:
        stem = csv_path.stem

        # 優先辨識 layer_001、layer001、Layer-001、Layer 001
        layer_match = re.search(
            r"layer[\s_-]*(\d+)",
            stem,
            flags=re.IGNORECASE,
        )

        if layer_match:
            layer_index = int(layer_match.group(1))
        else:
            numbers = re.findall(r"\d+", stem)

            if not numbers:
                continue

            # 找不到 Layer 關鍵字時，使用最後一組數字
            layer_index = int(numbers[-1])

        if LAYER_MIN_UI <= layer_index <= LAYER_MAX_UI:
            mapping[layer_index] = csv_path

    return dict(sorted(mapping.items()))


# =========================================================
# 11. 安全讀取 Coverage CSV
# =========================================================
def load_coverage_csv_as_z(csv_path: Path):
    df_raw = pd.read_csv(
        csv_path,
        header=None,
        dtype=str,
    )

    def clean_value(value):
        if pd.isna(value):
            return np.nan

        text = str(value).strip()

        if text == "":
            return np.nan

        return text

    # 相容不同 pandas 版本
    if hasattr(df_raw, "map"):
        df_raw = df_raw.map(clean_value)
    else:
        df_raw = df_raw.applymap(clean_value)

    df_num = df_raw.apply(
        pd.to_numeric,
        errors="coerce",
    )

    df_num = df_num.dropna(axis=0, how="all")
    df_num = df_num.dropna(axis=1, how="all")

    if df_num.empty:
        raise ValueError("CSV 沒有可用的數值資料")

    # -----------------------------------------------------
    # 移除可能的 Y 座標欄
    # -----------------------------------------------------
    if df_num.shape[1] >= 3:
        first_col = (
            df_num.iloc[:, 0]
            .dropna()
            .to_numpy(dtype=float)
        )

        if len(first_col) >= 3:
            difference = np.diff(first_col)

            is_monotonic = (
                np.all(difference >= 0)
                or np.all(difference <= 0)
            )

            if is_monotonic:
                df_num = df_num.iloc[:, 1:]

    # -----------------------------------------------------
    # 移除可能的 X 座標列
    # -----------------------------------------------------
    if df_num.shape[0] >= 3:
        first_row = (
            df_num.iloc[0, :]
            .dropna()
            .to_numpy(dtype=float)
        )

        if len(first_row) >= 3:
            difference = np.diff(first_row)

            is_monotonic = (
                np.all(difference >= 0)
                or np.all(difference <= 0)
            )

            if is_monotonic:
                df_num = df_num.iloc[1:, :]

    df_num = df_num.dropna(axis=0, how="all")
    df_num = df_num.dropna(axis=1, how="all")

    if df_num.empty:
        raise ValueError(
            "移除座標列或座標欄後，CSV 沒有可用數值"
        )

    z = df_num.to_numpy(dtype=float)

    if not np.isfinite(z).any():
        raise ValueError("CSV 數值全部為 NaN 或無效值")

    z = np.where(
        np.isfinite(z),
        z,
        0.0,
    )

    return z


# =========================================================
# 12. 將陣列裁切為相同尺寸
# =========================================================
def crop_arrays_to_common_shape(*arrays):
    valid_arrays = [
        np.asarray(array, dtype=float)
        for array in arrays
        if array is not None
    ]

    if not valid_arrays:
        raise ValueError("沒有可用的 Coverage 陣列")

    for array in valid_arrays:
        if array.ndim != 2:
            raise ValueError("Coverage CSV 必須為 2D 陣列")

    rows = min(array.shape[0] for array in valid_arrays)
    cols = min(array.shape[1] for array in valid_arrays)

    if rows <= 0 or cols <= 0:
        raise ValueError("Coverage CSV 尺寸無效")

    result = []

    for array in arrays:
        if array is None:
            result.append(None)
        else:
            cropped = np.asarray(
                array,
                dtype=float,
            )[:rows, :cols]

            cropped = np.where(
                np.isfinite(cropped),
                cropped,
                0.0,
            )

            result.append(cropped)

    return result


# =========================================================
# 13. 合併 n-1、n、n+1 Coverage
# =========================================================
def fill_current_low_value_area_with_neighbor_layers(
    z_curr,
    z_prev: Optional[np.ndarray] = None,
    z_next: Optional[np.ndarray] = None,
):
    """
    合併規則：

    當前層 >= CURRENT_FILL_THRESHOLD：
        display = current × CURRENT_LAYER_BOOST

    當前層 < CURRENT_FILL_THRESHOLD：
        display = max(
            previous × PREVIOUS_LAYER_WEIGHT,
            next × NEXT_LAYER_WEIGHT
        )
    """

    z_prev, z_curr, z_next = crop_arrays_to_common_shape(
        z_prev,
        z_curr,
        z_next,
    )

    rows, cols = z_curr.shape

    if z_prev is None:
        z_prev = np.zeros((rows, cols), dtype=float)

    if z_next is None:
        z_next = np.zeros((rows, cols), dtype=float)

    previous_influence = np.where(
        z_prev > 0,
        z_prev * PREVIOUS_LAYER_WEIGHT,
        0.0,
    )

    next_influence = np.where(
        z_next > 0,
        z_next * NEXT_LAYER_WEIGHT,
        0.0,
    )

    neighbor_influence = np.maximum(
        previous_influence,
        next_influence,
    )

    current_mask = z_curr >= CURRENT_FILL_THRESHOLD
    current_enhanced = z_curr * CURRENT_LAYER_BOOST

    z_display = np.where(
        current_mask,
        current_enhanced,
        neighbor_influence,
    )

    return z_display


# =========================================================
# 14. 讀取三層合併資料
# =========================================================
def load_combined_coverage_z(layer_value: int):
    layer_value = int(layer_value)
    mapping = scan_coverage_csvs()

    if layer_value not in mapping:
        raise FileNotFoundError(
            f"找不到當前層 Coverage CSV：Layer {layer_value}"
        )

    previous_layer = layer_value - 1
    next_layer = layer_value + 1
    current_path = mapping[layer_value]

    z_curr = load_coverage_csv_as_z(current_path)

    if previous_layer in mapping:
        previous_path = mapping[previous_layer]
        z_prev = load_coverage_csv_as_z(previous_path)
        previous_file = previous_path.name
    else:
        z_prev = None
        previous_file = None

    if next_layer in mapping:
        next_path = mapping[next_layer]
        z_next = load_coverage_csv_as_z(next_path)
        next_file = next_path.name
    else:
        z_next = None
        next_file = None

    z_display = fill_current_low_value_area_with_neighbor_layers(
        z_curr=z_curr,
        z_prev=z_prev,
        z_next=z_next,
    )

    used_layers = []

    if previous_file is not None:
        used_layers.append(previous_layer)

    used_layers.append(layer_value)

    if next_file is not None:
        used_layers.append(next_layer)

    return z_display, {
        "mode": "combined",
        "display_layer": layer_value,
        "current_layer": layer_value,
        "previous_layer": (
            previous_layer
            if previous_file is not None
            else None
        ),
        "next_layer": (
            next_layer
            if next_file is not None
            else None
        ),
        "current_file": current_path.name,
        "previous_file": previous_file,
        "next_file": next_file,
        "used_layers": used_layers,
        "rule": (
            f"Layer {layer_value} 為主；"
            f"當前層 ≥ {CURRENT_FILL_THRESHOLD:g} 時使用 "
            f"n × {CURRENT_LAYER_BOOST:g}；"
            f"當前層低於門檻時，使用 "
            f"max(n-1 × {PREVIOUS_LAYER_WEIGHT:g}, "
            f"n+1 × {NEXT_LAYER_WEIGHT:g})。"
        ),
    }


# =========================================================
# 15. 根據下拉選單讀取 Coverage
# =========================================================
def load_selected_coverage_z(
    layer_value: int,
    view_mode: str,
):
    """
    combined：顯示 n-1、n、n+1 合併結果
    previous：顯示 n-1 原始 CSV
    current：顯示 n 原始 CSV
    next：顯示 n+1 原始 CSV
    """

    layer_value = int(layer_value)

    if view_mode not in VIEW_MODE_CONFIG:
        view_mode = DEFAULT_VIEW_MODE

    mapping = scan_coverage_csvs()

    if layer_value not in mapping:
        raise FileNotFoundError(
            f"找不到當前層 Coverage CSV：Layer {layer_value}"
        )

    if view_mode == "combined":
        return load_combined_coverage_z(layer_value)

    if view_mode == "previous":
        target_layer = layer_value - 1
        relation_text = "前一層 n-1"
    elif view_mode == "next":
        target_layer = layer_value + 1
        relation_text = "下一層 n+1"
    else:
        target_layer = layer_value
        relation_text = "當前層 n"

    if target_layer not in mapping:
        raise FileNotFoundError(
            f"Layer {layer_value} 的{relation_text} "
            f"Layer {target_layer} 沒有 CSV"
        )

    target_path = mapping[target_layer]
    z = load_coverage_csv_as_z(target_path)

    return z, {
        "mode": view_mode,
        "display_layer": target_layer,
        "current_layer": layer_value,
        "previous_layer": (
            target_layer
            if view_mode == "previous"
            else None
        ),
        "next_layer": (
            target_layer
            if view_mode == "next"
            else None
        ),
        "current_file": (
            target_path.name
            if view_mode == "current"
            else mapping[layer_value].name
        ),
        "previous_file": (
            target_path.name
            if view_mode == "previous"
            else None
        ),
        "next_file": (
            target_path.name
            if view_mode == "next"
            else None
        ),
        "used_layers": [target_layer],
        "rule": (
            f"目前顯示 {relation_text}："
            f"Layer {target_layer}，"
            f"檔案 {target_path.name}。"
            "單層模式顯示原始 CSV 數值，"
            "不套用當前層倍率或相鄰層補值。"
        ),
    }


# =========================================================
# 16. 計算 n-1、n、n+1 Coverage 影響率
# =========================================================
def calc_coverage_influence_rates(
    layer_value: int,
    view_mode: str,
):
    """
    影響率：

        該層實際貢獻的 Coverage 總和
        -------------------------------- × 100%
        所有層實際貢獻的 Coverage 總和

    combined：依照實際合併規則計算三層貢獻。
    previous/current/next：被選擇的單層為 100%。
    """

    layer_value = int(layer_value)

    if view_mode not in VIEW_MODE_CONFIG:
        view_mode = DEFAULT_VIEW_MODE

    mapping = scan_coverage_csvs()

    if layer_value not in mapping:
        raise FileNotFoundError(
            f"找不到當前層 Coverage CSV：Layer {layer_value}"
        )

    result = {
        "previous": {
            "layer": layer_value - 1,
            "label": f"n-1 前一層<br>Layer {layer_value - 1}",
            "rate": 0.0,
            "contribution": 0.0,
            "active_points": 0,
        },
        "current": {
            "layer": layer_value,
            "label": f"n 當前層<br>Layer {layer_value}",
            "rate": 0.0,
            "contribution": 0.0,
            "active_points": 0,
        },
        "next": {
            "layer": layer_value + 1,
            "label": f"n+1 下一層<br>Layer {layer_value + 1}",
            "rate": 0.0,
            "contribution": 0.0,
            "active_points": 0,
        },
    }

    # -----------------------------------------------------
    # 單層模式
    # -----------------------------------------------------
    if view_mode != "combined":
        if view_mode == "previous":
            selected_key = "previous"
            target_layer = layer_value - 1
        elif view_mode == "next":
            selected_key = "next"
            target_layer = layer_value + 1
        else:
            selected_key = "current"
            target_layer = layer_value

        if target_layer not in mapping:
            raise FileNotFoundError(
                f"Layer {target_layer} 沒有 Coverage CSV"
            )

        z_selected = load_coverage_csv_as_z(mapping[target_layer])

        z_selected = np.where(
            np.isfinite(z_selected),
            np.maximum(z_selected, 0.0),
            0.0,
        )

        result[selected_key]["rate"] = 100.0
        result[selected_key]["contribution"] = float(
            np.sum(z_selected)
        )
        result[selected_key]["active_points"] = int(
            np.count_nonzero(z_selected > 0)
        )

        return result

    # -----------------------------------------------------
    # Combined 三層合併模式
    # -----------------------------------------------------
    previous_layer = layer_value - 1
    next_layer = layer_value + 1

    z_curr = load_coverage_csv_as_z(mapping[layer_value])

    if previous_layer in mapping:
        z_prev = load_coverage_csv_as_z(mapping[previous_layer])
    else:
        z_prev = None

    if next_layer in mapping:
        z_next = load_coverage_csv_as_z(mapping[next_layer])
    else:
        z_next = None

    z_prev, z_curr, z_next = crop_arrays_to_common_shape(
        z_prev,
        z_curr,
        z_next,
    )

    rows, cols = z_curr.shape

    if z_prev is None:
        z_prev = np.zeros((rows, cols), dtype=float)

    if z_next is None:
        z_next = np.zeros((rows, cols), dtype=float)

    # 移除無效值與負值
    z_prev = np.where(
        np.isfinite(z_prev),
        np.maximum(z_prev, 0.0),
        0.0,
    )

    z_curr = np.where(
        np.isfinite(z_curr),
        np.maximum(z_curr, 0.0),
        0.0,
    )

    z_next = np.where(
        np.isfinite(z_next),
        np.maximum(z_next, 0.0),
        0.0,
    )

    previous_influence = z_prev * PREVIOUS_LAYER_WEIGHT
    current_influence = z_curr * CURRENT_LAYER_BOOST
    next_influence = z_next * NEXT_LAYER_WEIGHT

    current_mask = z_curr >= CURRENT_FILL_THRESHOLD
    neighbor_mask = ~current_mask

    previous_win_mask = (
        neighbor_mask
        & (previous_influence > next_influence)
        & (previous_influence > 0)
    )

    next_win_mask = (
        neighbor_mask
        & (next_influence > previous_influence)
        & (next_influence > 0)
    )

    tie_mask = (
        neighbor_mask
        & np.isclose(
            previous_influence,
            next_influence,
            rtol=1e-9,
            atol=1e-12,
        )
        & (previous_influence > 0)
    )

    current_contribution_map = np.where(
        current_mask,
        current_influence,
        0.0,
    )

    previous_contribution_map = np.where(
        previous_win_mask,
        previous_influence,
        0.0,
    )

    next_contribution_map = np.where(
        next_win_mask,
        next_influence,
        0.0,
    )

    # 前後層相同時，各分配一半
    previous_contribution_map += np.where(
        tie_mask,
        previous_influence * 0.5,
        0.0,
    )

    next_contribution_map += np.where(
        tie_mask,
        next_influence * 0.5,
        0.0,
    )

    previous_sum = float(np.sum(previous_contribution_map))
    current_sum = float(np.sum(current_contribution_map))
    next_sum = float(np.sum(next_contribution_map))

    total_sum = previous_sum + current_sum + next_sum

    if total_sum > 1e-12:
        previous_rate = previous_sum / total_sum * 100.0
        current_rate = current_sum / total_sum * 100.0
        next_rate = next_sum / total_sum * 100.0
    else:
        previous_rate = 0.0
        current_rate = 0.0
        next_rate = 0.0

    result["previous"]["rate"] = previous_rate
    result["previous"]["contribution"] = previous_sum
    result["previous"]["active_points"] = int(
        np.count_nonzero(previous_contribution_map > 0)
    )

    result["current"]["rate"] = current_rate
    result["current"]["contribution"] = current_sum
    result["current"]["active_points"] = int(
        np.count_nonzero(current_contribution_map > 0)
    )

    result["next"]["rate"] = next_rate
    result["next"]["contribution"] = next_sum
    result["next"]["active_points"] = int(
        np.count_nonzero(next_contribution_map > 0)
    )

    return result


# =========================================================
# 17. 建立 X/Y 座標
# =========================================================
def build_display_xy(z):
    n_rows, n_cols = z.shape

    if n_cols > 1:
        x_mm = np.linspace(
            DISPLAY_X_START_MM,
            DISPLAY_X_END_MM,
            n_cols,
        )
    else:
        x_mm = np.array([DISPLAY_X_START_MM], dtype=float)

    if n_rows > 1:
        y_mm = np.linspace(
            DISPLAY_Y_START_MM,
            DISPLAY_Y_END_MM,
            n_rows,
        )
    else:
        y_mm = np.array([DISPLAY_Y_START_MM], dtype=float)

    return x_mm, y_mm


# =========================================================
# 18. 裁切均勻度分析範圍
# =========================================================
def crop_z_by_uniformity_range(
    z,
    x_mm,
    y_mm,
):
    x_min = min(
        UNIFORMITY_X_START_MM,
        UNIFORMITY_X_END_MM,
    )
    x_max = max(
        UNIFORMITY_X_START_MM,
        UNIFORMITY_X_END_MM,
    )

    y_min = min(
        UNIFORMITY_Y_START_MM,
        UNIFORMITY_Y_END_MM,
    )
    y_max = max(
        UNIFORMITY_Y_START_MM,
        UNIFORMITY_Y_END_MM,
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
            "均勻度分析範圍沒有對應到 Coverage 資料點"
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
# 19. 計算 Coverage 均勻度
# =========================================================
def calc_coverage_uniformity(z):
    z_array = np.asarray(
        z,
        dtype=float,
    )

    if z_array.ndim != 2:
        raise ValueError(
            "Coverage 均勻度資料必須為 2D 陣列"
        )

    z_array = np.where(
        np.isfinite(z_array),
        z_array,
        np.nan,
    )

    values = z_array.ravel()
    values = values[np.isfinite(values)]

    if EXCLUDE_ZERO_FOR_UNIFORMITY:
        values = values[values > 0]

    if values.size == 0:
        return {
            "status": "INFO",
            "color": "secondary",
            "condition": "No valid coverage data",
            "condition_zh": "沒有有效 Coverage 資料",
            "reason": "目前分析範圍內沒有可用的 Coverage 數值。",
            "effect": "無法判斷均勻度。",
            "suggestion": "請確認 CSV、Layer 與分析範圍設定。",
            "mean": None,
            "std": None,
            "cv": None,
            "p5": None,
            "p95": None,
            "range_ratio": None,
            "low_ratio": None,
            "high_ratio": None,
            "edge_mean": None,
            "center_mean": None,
            "edge_center_ratio": None,
            "count": 0,
        }

    mean_v = float(np.mean(values))
    std_v = float(np.std(values))
    p5_v = float(np.percentile(values, 5))
    p95_v = float(np.percentile(values, 95))

    robust_range = float(
        p95_v - p5_v
    )

    denominator = abs(mean_v)

    if denominator < 1e-12:
        cv_v = (
            0.0
            if std_v < 1e-12
            else float("inf")
        )
        range_ratio_v = (
            0.0
            if robust_range < 1e-12
            else float("inf")
        )
        low_ratio_v = 0.0
        high_ratio_v = 0.0
    else:
        cv_v = std_v / denominator
        range_ratio_v = robust_range / denominator

        low_threshold = (
            mean_v * LOW_COVERAGE_FACTOR
        )
        high_threshold = (
            mean_v * HIGH_COVERAGE_FACTOR
        )

        low_ratio_v = float(
            np.mean(values < low_threshold)
        )
        high_ratio_v = float(
            np.mean(values > high_threshold)
        )

    # -----------------------------------------------------
    # 邊緣與中央區域比較
    # -----------------------------------------------------
    rows, cols = z_array.shape
    edge_width = max(
        1,
        int(
            round(
                min(rows, cols)
                * EDGE_BAND_RATIO
            )
        ),
    )

    edge_mask = np.zeros(
        (rows, cols),
        dtype=bool,
    )

    edge_mask[:edge_width, :] = True
    edge_mask[-edge_width:, :] = True
    edge_mask[:, :edge_width] = True
    edge_mask[:, -edge_width:] = True

    valid_mask = np.isfinite(z_array)

    if EXCLUDE_ZERO_FOR_UNIFORMITY:
        valid_mask &= z_array > 0

    center_mask = (
        valid_mask
        & (~edge_mask)
    )
    valid_edge_mask = (
        valid_mask
        & edge_mask
    )

    edge_values = z_array[valid_edge_mask]
    center_values = z_array[center_mask]

    edge_mean_v = (
        float(np.mean(edge_values))
        if edge_values.size > 0
        else None
    )

    center_mean_v = (
        float(np.mean(center_values))
        if center_values.size > 0
        else None
    )

    if (
        edge_mean_v is not None
        and center_mean_v is not None
        and abs(center_mean_v) > 1e-12
    ):
        edge_center_ratio_v = (
            edge_mean_v
            / abs(center_mean_v)
        )
    else:
        edge_center_ratio_v = None

    # -----------------------------------------------------
    # 均勻度狀況判斷
    # -----------------------------------------------------
    pass_uniformity = (
        cv_v <= UNIFORMITY_CV_PASS
        and range_ratio_v
        <= UNIFORMITY_RANGE_PASS
    )

    warn_uniformity = (
        cv_v <= UNIFORMITY_CV_WARN
        and range_ratio_v
        <= UNIFORMITY_RANGE_WARN
    )

    edge_accumulation = (
        edge_center_ratio_v is not None
        and edge_center_ratio_v
        >= EDGE_ACCUMULATION_RATIO
    )

    if pass_uniformity:
        status = "PASS"
        color = "success"
        condition = "Uniform thermal coverage"
        condition_zh = "熱覆蓋均勻"

        reason = (
            f"CV = {cv_v:.3f}，"
            f"P95-P5/平均 = "
            f"{range_ratio_v:.3f}；"
            "分布變動在 PASS 門檻內。"
        )

        effect = (
            "熔化較穩定、層間結合較一致，"
            "Coverage 不均所造成的缺陷風險較低。"
        )

        suggestion = (
            "維持目前雷射功率 P、掃描速度 v、"
            "hatch spacing h 與層厚設定。"
        )

    elif edge_accumulation:
        status = (
            "WARN"
            if warn_uniformity
            else "FAIL"
        )
        color = (
            "warning"
            if status == "WARN"
            else "danger"
        )
        condition = "Edge heat accumulation"
        condition_zh = "邊緣熱累積"

        reason = (
            f"邊緣平均值 / 中央平均值 = "
            f"{edge_center_ratio_v:.3f}，"
            f"已達 {EDGE_ACCUMULATION_RATIO:.2f} "
            "以上。"
        )

        effect = (
            "可能造成邊緣凸起、變形、"
            "粗糙度增加或影響後續鋪粉。"
        )

        suggestion = (
            "邊界區可降低雷射功率 P、提高掃描速度 v，"
            "或增加邊界掃描間隔與冷卻時間。"
        )

    elif warn_uniformity:
        status = "WARN"
        color = "warning"
        condition = "Slightly uneven thermal coverage"
        condition_zh = "熱覆蓋輕微不均"

        reason = (
            f"CV = {cv_v:.3f}，"
            f"P95-P5/平均 = "
            f"{range_ratio_v:.3f}；"
            "已超過 PASS，但仍在 WARN 門檻內。"
        )

        effect = (
            "可能出現局部溫差、冷卻差異、"
            "層間結合波動或表面粗糙度上升。"
        )

        suggestion = (
            "穩定雷射功率 P 與掃描速度 v；"
            "可小幅調整 hatch spacing h 或掃描順序。"
        )

    else:
        status = "FAIL"
        color = "danger"

        if (
            low_ratio_v >= 0.10
            and low_ratio_v > high_ratio_v
        ):
            condition = (
                "Insufficient thermal coverage"
            )
            condition_zh = "熱覆蓋不足"

            reason = (
                f"低於平均值 × "
                f"{LOW_COVERAGE_FACTOR:.2f} 的區域占 "
                f"{low_ratio_v * 100:.2f}%，"
                "低值區域較明顯。"
            )

            effect = (
                "容易造成未熔合、孔洞、"
                "熔道不連續或層間結合不足。"
            )

            suggestion = (
                "提高雷射功率 P、降低掃描速度 v，"
                "或減少 hatch spacing h。"
            )

        elif (
            high_ratio_v >= 0.10
            and high_ratio_v > low_ratio_v
        ):
            condition = (
                "Excessive thermal coverage"
            )
            condition_zh = "熱覆蓋過高"

            reason = (
                f"高於平均值 × "
                f"{HIGH_COVERAGE_FACTOR:.2f} 的區域占 "
                f"{high_ratio_v * 100:.2f}%，"
                "高值區域較明顯。"
            )

            effect = (
                "熱影響區可能擴大，增加變形、"
                "過燒、匙孔或孔洞風險。"
            )

            suggestion = (
                "降低雷射功率 P、提高掃描速度 v，"
                "或增加 hatch spacing h。"
            )

        else:
            condition = "Uneven thermal coverage"
            condition_zh = "熱覆蓋不均"

            reason = (
                f"CV = {cv_v:.3f}，"
                f"P95-P5/平均 = "
                f"{range_ratio_v:.3f}；"
                "均超出允許門檻，且高低值區域混合。"
            )

            effect = (
                "可能造成殘留應力、翹曲、"
                "粗糙度增加與層間結合不穩定。"
            )

            suggestion = (
                "穩定雷射功率 P 與掃描速度 v，"
                "並微調 hatch spacing h、掃描順序"
                "或局部功率。"
            )

    return {
        "status": status,
        "color": color,
        "condition": condition,
        "condition_zh": condition_zh,
        "reason": reason,
        "effect": effect,
        "suggestion": suggestion,
        "mean": mean_v,
        "std": std_v,
        "cv": cv_v,
        "p5": p5_v,
        "p95": p95_v,
        "range_ratio": range_ratio_v,
        "low_ratio": low_ratio_v,
        "high_ratio": high_ratio_v,
        "edge_mean": edge_mean_v,
        "center_mean": center_mean_v,
        "edge_center_ratio": edge_center_ratio_v,
        "count": int(values.size),
    }


# =========================================================
# 20. 均勻度數值格式
# =========================================================
def fmt_uniformity_metric(
    value,
    digits=3,
    suffix="",
):
    if value is None:
        return "--"

    try:
        if not np.isfinite(value):
            return "∞"

        return (
            f"{value:.{digits}f}"
            f"{suffix}"
        )

    except Exception:
        return "--"


# =========================================================
# 21. 均勻度數值卡
# =========================================================
def make_uniformity_metric_card(
    title,
    value,
    color="dark",
):
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        title,
                        className=(
                            "small text-muted"
                        ),
                    ),
                    html.H5(
                        value,
                        className="mb-0 mt-1",
                    ),
                ],
                className="p-2 text-center",
            ),
            color=color,
            outline=True,
            className="h-100",
        ),
        xs=6,
        md=4,
        xl=2,
    )


# =========================================================
# 22. 建立空白圖
# =========================================================
def make_empty_figure(message):
    fig = go.Figure()

    fig.update_layout(
        template="plotly_dark",
        autosize=True,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=message,
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=16),
            )
        ],
        margin=dict(l=20, r=20, t=40, b=20),
    )

    return fig


# =========================================================
# 19. 建立 Coverage 影響率圖
# =========================================================
def make_influence_rate_figure(
    layer_value: int,
    view_mode: str,
):
    influence = calc_coverage_influence_rates(
        layer_value=layer_value,
        view_mode=view_mode,
    )

    categories = [
        influence["previous"]["label"],
        influence["current"]["label"],
        influence["next"]["label"],
    ]

    rates = [
        influence["previous"]["rate"],
        influence["current"]["rate"],
        influence["next"]["rate"],
    ]

    contributions = [
        influence["previous"]["contribution"],
        influence["current"]["contribution"],
        influence["next"]["contribution"],
    ]

    active_points = [
        influence["previous"]["active_points"],
        influence["current"]["active_points"],
        influence["next"]["active_points"],
    ]

    custom_data = np.column_stack(
        [contributions, active_points]
    )

    bar_colors = [
        "#3498DB",  # n-1 藍色
        "#E74C3C",  # n 紅色
        "#2ECC71",  # n+1 綠色
    ]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=categories,
            y=rates,
            marker=dict(
                color=bar_colors,
                line=dict(
                    color="rgba(255,255,255,0.65)",
                    width=1,
                ),
            ),
            text=[f"{rate:.2f}%" for rate in rates],
            textposition="auto",
            textfont=dict(size=16),
            customdata=custom_data,
            hovertemplate=(
                "%{x}<br>"
                "影響率 = %{y:.2f}%<br>"
                "Coverage 貢獻總和 = %{customdata[0]:,.3f}<br>"
                "實際貢獻資料點 = %{customdata[1]:,.0f}"
                "<extra></extra>"
            ),
        )
    )

    view_name = VIEW_MODE_CONFIG[view_mode]["short_label"]
    total_rate = float(np.sum(rates))

    fig.update_layout(
        template="plotly_dark",
        autosize=True,
        title=dict(
            text=(
                "Coverage Layer Influence Rate / 層影響率"
                "<br>"
                f"基準 Layer {layer_value}｜"
                f"模式：{view_name}｜"
                f"影響率總和：{total_rate:.2f}%"
            ),
            x=0.5,
            xanchor="center",
        ),
        xaxis=dict(
            title="Layer / 層",
            automargin=True,
            tickfont=dict(size=13),
        ),
        yaxis=dict(
            title="Influence Rate / 影響率 (%)",
            range=[0, 105],
            ticksuffix="%",
            gridcolor="rgba(255,255,255,0.15)",
            zeroline=True,
            zerolinecolor="rgba(255,255,255,0.4)",
        ),
        margin=dict(l=75, r=30, t=95, b=80),
        showlegend=False,
        height=410,
        uirevision="coverage-influence",
        bargap=0.28,
    )

    return fig


# =========================================================
# 20. 導覽列連結
# =========================================================
def navlink(
    label: str,
    key: str,
    icon: str,
):
    return dbc.NavLink(
        [
            html.I(className=f"bi {icon} me-2"),
            label,
        ],
        href=APP_URLS[key],
        target="_self",
        external_link=True,
        active=(key == "step3a"),
    )


# =========================================================
# 21. Navbar
# =========================================================
navbar = dbc.Navbar(
    dbc.Container(
        [
            html.Div(
                [
                    html.I(
                        className="bi bi-grid-3x3-gap-fill me-2"
                    ),
                    "Layer Coverage Viewer",
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
# 22. Sidebar
# =========================================================
sidebar = html.Div(
    [
        html.H5(
            "Navigation",
            className="text-white-50",
        ),
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
        html.Div(
            "© 2026",
            className="text-white-50 small mt-2",
        ),
    ],
    className="bg-dark p-3 h-100",
    style={
        "width": "240px",
        "top": "56px",
        "left": 0,
        "overflowY": "auto",
        "height": "100%",
        "zIndex": 1030,
        "position": "fixed",
    },
)


# =========================================================
# 23. 下拉選單
# =========================================================
coverage_view_dropdown = html.Div(
    [
        html.Div(
            [
                html.I(className="bi bi-layers me-2"),
                "Coverage View / 顯示模式",
            ],
            className="fw-bold mb-1",
        ),
        dcc.Dropdown(
            id="coverage-view-dropdown",
            options=[
                {
                    "label": config["label"],
                    "value": mode,
                }
                for mode, config in VIEW_MODE_CONFIG.items()
            ],
            value=DEFAULT_VIEW_MODE,
            clearable=False,
            searchable=False,
            style={
                "color": "#000000",
                "backgroundColor": "#FFFFFF",
            },
        ),
        html.Div(
            [
                dbc.Badge(
                    "n-1 前一層：藍色",
                    color="primary",
                    className="me-2 mt-2",
                ),
                dbc.Badge(
                    "n 當前層：紅色",
                    color="danger",
                    className="me-2 mt-2",
                ),
                dbc.Badge(
                    "n+1 下一層：綠色",
                    color="success",
                    className="me-2 mt-2",
                ),
                dbc.Badge(
                    "合併：Jet 彩色",
                    color="info",
                    className="me-2 mt-2",
                ),
            ],
            className="d-flex flex-wrap",
        ),
    ],
    style={
        "width": "100%",
        "maxWidth": "480px",
    },
)


# =========================================================
# 24. 主畫面
# =========================================================
main_card = dbc.Card(
    [
        dbc.CardHeader(
            html.Div(
                [
                    html.Div(
                        [
                            html.I(className="bi bi-image me-2"),
                            "Layer Coverage",
                        ],
                        className="me-auto fw-bold",
                    ),
                ],
                className="d-flex align-items-center",
            )
        ),
        dbc.CardBody(
            [
                html.Div(
                    id="media-status",
                    className="mb-2",
                ),
                dbc.Row(
                    [
                        dbc.Col(
                            coverage_view_dropdown,
                            xs=12,
                            lg=4,
                            className="mb-3",
                        ),
                        dbc.Col(
                            html.Div(
                                id="coverage-layer-info",
                                className="mt-1",
                            ),
                            xs=12,
                            lg=8,
                            className="mb-3",
                        ),
                    ],
                    className="align-items-end",
                ),
                dcc.Loading(
                    type="circle",
                    children=html.Div(
                        [
                            html.Div(
                                "Layer / 層數",
                                className="fw-bold mb-2",
                            ),
                            dcc.Slider(
                                id="coverage-layer-slider",
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
                                    "style": {
                                        "color": "#000000",
                                        "backgroundColor": "#FFFFFF",
                                        "fontSize": "15px",
                                        "fontWeight": "700",
                                    },
                                },
                            ),
                            dcc.Graph(
                                id="coverage-heatmap",
                                style=HEATMAP_STYLE,
                                config=GRAPH_CONFIG,
                                responsive=True,
                                figure=go.Figure(),
                            ),
                            dbc.Card(
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
                                                    "Layer Influence Rate / "
                                                    "層影響率"
                                                ),
                                            ],
                                            className="fw-bold",
                                        )
                                    ),
                                    dbc.CardBody(
                                        [
                                            dcc.Graph(
                                                id=(
                                                    "coverage-influence-chart"
                                                ),
                                                style=(
                                                    INFLUENCE_CHART_STYLE
                                                ),
                                                config={
                                                    "responsive": True,
                                                    "displaylogo": False,
                                                    "scrollZoom": False,
                                                    "doubleClick": "reset",
                                                },
                                                responsive=True,
                                                figure=go.Figure(),
                                            ),
                                            html.Div(
                                                (
                                                    "影響率代表各層對目前顯示 "
                                                    "Coverage 數值的實際貢獻比例。"
                                                    "Combined 模式依照門檻、倍率與 "
                                                    "max(n-1, n+1) 規則計算。"
                                                ),
                                                className=(
                                                    "small text-muted "
                                                    "text-center mt-1"
                                                ),
                                            ),
                                        ],
                                        className="p-2",
                                    ),
                                ],
                                className="shadow-sm mt-3",
                            ),

                            html.Div(
                                id="coverage-uniformity-panel",
                                className="mt-3",
                                style={
                                    "width": "100%",
                                    "margin": "0 auto",
                                },
                            ),
                        ],
                        style={
                            "width": "100%",
                            "maxWidth": "100%",
                            "minWidth": "760px",
                            "margin": "0 auto",
                        },
                    ),
                ),
            ],
            className="p-3",
        ),
    ],
    className="shadow-sm h-100",
    style={
        "width": "100%",
        "maxWidth": "100%",
        "margin": "0 auto",
    },
)


# =========================================================
# 25. App Layout
# =========================================================
app.layout = html.Div(
    [
        navbar,
        sidebar,
        html.Div(
            [main_card],
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
    ]
)


# =========================================================
# 26. Callback：初始化 Slider
# =========================================================
@app.callback(
    [
        Output("coverage-layer-slider", "min"),
        Output("coverage-layer-slider", "max"),
        Output("coverage-layer-slider", "marks"),
        Output("coverage-layer-slider", "value"),
        Output("media-status", "children"),
    ],
    Input("coverage-layer-slider", "id"),
    prevent_initial_call=False,
)
def init_slider(_):
    mapping = scan_coverage_csvs()

    if not mapping:
        return (
            LAYER_MIN_UI,
            LAYER_MAX_UI,
            make_slider_marks(LAYER_MIN_UI, LAYER_MAX_UI),
            LAYER_MIN_UI,
            dbc.Alert(
                [
                    html.Div(
                        "⚠️ 找不到 Coverage CSV",
                        className="fw-bold",
                    ),
                    html.Div(
                        f"請確認資料夾：{COVERAGE_CSV_DIR}",
                        className="small",
                    ),
                ],
                color="warning",
                className="mb-2",
            ),
        )

    layers = sorted(mapping.keys())
    actual_min = layers[0]
    actual_max = layers[-1]

    return (
        actual_min,
        actual_max,
        make_slider_marks(actual_min, actual_max),
        actual_min,
        "",
    )


# =========================================================
# 27. Callback：顯示目前模式資訊
# =========================================================
@app.callback(
    Output("coverage-layer-info", "children"),
    [
        Input("coverage-layer-slider", "value"),
        Input("coverage-view-dropdown", "value"),
    ],
    prevent_initial_call=False,
)
def update_layer_information(
    layer_value,
    view_mode,
):
    if layer_value is None:
        layer_value = LAYER_MIN_UI

    layer_value = int(layer_value)

    if view_mode not in VIEW_MODE_CONFIG:
        view_mode = DEFAULT_VIEW_MODE

    config = VIEW_MODE_CONFIG[view_mode]

    if view_mode == "previous":
        display_layer = layer_value - 1
    elif view_mode == "next":
        display_layer = layer_value + 1
    else:
        display_layer = layer_value

    return dbc.Alert(
        [
            html.Div(
                [
                    html.I(className="bi bi-eye me-2"),
                    f"目前模式：{config['short_label']}",
                ],
                className="fw-bold",
            ),
            html.Div(
                (
                    f"拉霸基準層：Layer {layer_value}｜"
                    f"實際顯示層："
                    f"{'合併結果' if view_mode == 'combined' else f'Layer {display_layer}'}｜"
                    f"色階：{config['color_description']}"
                ),
                className="small mt-1",
            ),
        ],
        color="secondary",
        className="mb-0",
    )


# =========================================================
# 28. Callback：更新 Heatmap
# =========================================================
@app.callback(
    Output("coverage-heatmap", "figure"),
    [
        Input("coverage-layer-slider", "value"),
        Input("coverage-view-dropdown", "value"),
    ],
    prevent_initial_call=False,
)
def update_coverage_heatmap(
    layer_value,
    view_mode,
):
    if layer_value is None:
        layer_value = LAYER_MIN_UI

    layer_value = int(layer_value)

    if view_mode not in VIEW_MODE_CONFIG:
        view_mode = DEFAULT_VIEW_MODE

    mapping = scan_coverage_csvs()

    if not mapping or layer_value not in mapping:
        return make_empty_figure(
            f"No CSV for Layer {layer_value}"
        )

    try:
        z, layer_info = load_selected_coverage_z(
            layer_value=layer_value,
            view_mode=view_mode,
        )

        # 保留原本左右翻轉
        z = z[:, ::-1]

    except Exception as error:
        return make_empty_figure(
            f"讀取失敗<br>{error}"
        )

    x_mm, y_mm = build_display_xy(z)
    view_config = VIEW_MODE_CONFIG[view_mode]

    used_layers_text = ", ".join(
        str(layer)
        for layer in layer_info["used_layers"]
    )

    finite_values = z[np.isfinite(z)]

    if finite_values.size > 0:
        z_min = float(np.min(finite_values))
        z_max = float(np.max(finite_values))

        if abs(z_max - z_min) < 1e-12:
            z_max = z_min + 1.0
    else:
        z_min = 0.0
        z_max = 1.0

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=x_mm,
            y=y_mm,
            colorscale=view_config["colorscale"],
            zmin=z_min,
            zmax=z_max,
            zsmooth=False,
            xgap=0,
            ygap=0,
            colorbar=dict(
                title=dict(
                    text=(
                        f"Coverage<br>"
                        f"{view_config['short_label']}"
                    ),
                    side="right",
                ),
                thickness=18,
                len=0.9,
            ),
            hovertemplate=(
                "X = %{x:.3f} mm<br>"
                "Y = %{y:.3f} mm<br>"
                "Coverage = %{z:.3f}<br>"
                f"Mode = {view_config['short_label']}"
                "<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        template="plotly_dark",
        autosize=True,
        title=(
            f"Layer Coverage - 基準 Layer {layer_value}"
            f"<br>"
            f"顯示：{view_config['short_label']}｜"
            f"使用 Layer：{used_layers_text}｜"
            f"色階：{view_config['color_description']}"
        ),
        margin=dict(l=60, r=70, t=82, b=60),
        uirevision="keep",
        xaxis=dict(
            title="X (mm)",
            range=[DISPLAY_X_START_MM, DISPLAY_X_END_MM],
            constrain="domain",
            automargin=True,
            zeroline=True,
            zerolinecolor="white",
            zerolinewidth=2,
            showgrid=True,
        ),
        yaxis=dict(
            title="Y (mm)",
            range=[DISPLAY_Y_START_MM, DISPLAY_Y_END_MM],
            constrain="domain",
            automargin=True,
            zeroline=True,
            zerolinecolor="white",
            zerolinewidth=2,
            showgrid=True,
            scaleanchor="x",
            scaleratio=1,
        ),
    )

    return fig


# =========================================================
# 29. Callback：更新 Layer 影響率圖
# =========================================================
@app.callback(
    Output("coverage-influence-chart", "figure"),
    [
        Input("coverage-layer-slider", "value"),
        Input("coverage-view-dropdown", "value"),
    ],
    prevent_initial_call=False,
)
def update_coverage_influence_chart(
    layer_value,
    view_mode,
):
    if layer_value is None:
        layer_value = LAYER_MIN_UI

    layer_value = int(layer_value)

    if view_mode not in VIEW_MODE_CONFIG:
        view_mode = DEFAULT_VIEW_MODE

    mapping = scan_coverage_csvs()

    if not mapping or layer_value not in mapping:
        return make_empty_figure(
            f"Layer {layer_value} 沒有 Coverage CSV"
        )

    try:
        return make_influence_rate_figure(
            layer_value=layer_value,
            view_mode=view_mode,
        )

    except Exception as error:
        return make_empty_figure(
            f"影響率計算失敗<br>{error}"
        )


# =========================================================
# 30. Callback：更新 Coverage 均勻度判斷
# =========================================================
@app.callback(
    Output(
        "coverage-uniformity-panel",
        "children",
    ),
    [
        Input(
            "coverage-layer-slider",
            "value",
        ),
        Input(
            "coverage-view-dropdown",
            "value",
        ),
    ],
    prevent_initial_call=False,
)
def update_coverage_uniformity_panel(
    layer_value,
    view_mode,
):
    if layer_value is None:
        layer_value = LAYER_MIN_UI

    layer_value = int(layer_value)

    if view_mode not in VIEW_MODE_CONFIG:
        view_mode = DEFAULT_VIEW_MODE

    mapping = scan_coverage_csvs()

    if (
        not mapping
        or layer_value not in mapping
    ):
        return dbc.Alert(
            (
                f"⚠️ Layer {layer_value} 沒有 CSV，"
                "無法判斷 Coverage 均勻度。"
            ),
            color="warning",
            className="mb-0",
        )

    try:
        z, layer_info = load_selected_coverage_z(
            layer_value=layer_value,
            view_mode=view_mode,
        )

        # 與 Heatmap 顯示方向一致
        z = z[:, ::-1]

        x_mm, y_mm = build_display_xy(z)

        (
            z_uniformity,
            used_cols,
            used_rows,
        ) = crop_z_by_uniformity_range(
            z,
            x_mm,
            y_mm,
        )

        result = calc_coverage_uniformity(
            z_uniformity
        )

    except Exception as error:
        return dbc.Alert(
            (
                "⚠️ Coverage 均勻度判斷失敗："
                f"Layer {layer_value}｜{error}"
            ),
            color="danger",
            className="mb-0",
        )

    view_config = VIEW_MODE_CONFIG[
        view_mode
    ]

    status_badge = dbc.Badge(
        result["status"],
        color=result["color"],
        className="ms-2",
        style={
            "fontSize": "15px",
            "padding": "8px 12px",
            "borderRadius": "12px",
        },
    )

    return dbc.Card(
        [
            dbc.CardHeader(
                html.Div(
                    [
                        html.Span(
                            [
                                html.I(
                                    className=(
                                        "bi bi-grid-3x3-gap me-2"
                                    )
                                ),
                                (
                                    "Coverage Uniformity Judgment / "
                                    "Coverage 均勻度判斷"
                                ),
                            ],
                            className="me-auto fw-bold",
                        ),
                        status_badge,
                    ],
                    className=(
                        "d-flex align-items-center"
                    ),
                )
            ),

            dbc.CardBody(
                [
                    dbc.Alert(
                        [
                            html.H5(
                                (
                                    f"{result['condition_zh']} / "
                                    f"{result['condition']}"
                                ),
                                className="mb-2",
                            ),

                            html.Div(
                                [
                                    html.Strong(
                                        "判斷原因："
                                    ),
                                    result["reason"],
                                ],
                                className="mb-1",
                            ),

                            html.Div(
                                [
                                    html.Strong(
                                        "可能影響："
                                    ),
                                    result["effect"],
                                ],
                                className="mb-1",
                            ),

                            html.Div(
                                [
                                    html.Strong(
                                        "建議調整："
                                    ),
                                    result["suggestion"],
                                ],
                                className="mb-1",
                            ),

                            html.Hr(
                                className="my-2"
                            ),

                            html.Div(
                                (
                                    f"目前模式："
                                    f"{view_config['short_label']}｜"
                                    f"分析範圍 X = "
                                    f"{UNIFORMITY_X_START_MM:g} ～ "
                                    f"{UNIFORMITY_X_END_MM:g} mm，"
                                    f"Y = "
                                    f"{UNIFORMITY_Y_START_MM:g} ～ "
                                    f"{UNIFORMITY_Y_END_MM:g} mm｜"
                                    f"資料點："
                                    f"{used_cols} 欄 × "
                                    f"{used_rows} 列。"
                                ),
                                className="small",
                            ),

                            html.Div(
                                (
                                    "PASS："
                                    f"CV ≤ {UNIFORMITY_CV_PASS:.2f} "
                                    "且 "
                                    f"P95-P5/平均 ≤ "
                                    f"{UNIFORMITY_RANGE_PASS:.2f}；"
                                    "WARN："
                                    f"CV ≤ {UNIFORMITY_CV_WARN:.2f} "
                                    "且 "
                                    f"P95-P5/平均 ≤ "
                                    f"{UNIFORMITY_RANGE_WARN:.2f}；"
                                    "超過則 FAIL。"
                                ),
                                className=(
                                    "small text-muted mt-1"
                                ),
                            ),

                            html.Div(
                                (
                                    "此處判斷的是 Coverage 的相對均勻度；"
                                    "只有當 CSV 數值本身代表熱覆蓋或溫度時，"
                                    "才可直接解讀為熱場均勻度。"
                                ),
                                className=(
                                    "small text-muted mt-1"
                                ),
                            ),

                            html.Div(
                                layer_info["rule"],
                                className=(
                                    "small text-muted mt-1"
                                ),
                            ),
                        ],
                        color=result["color"],
                        className="mt-2 mb-0",
                    ),
                ],
                className="p-2",
            ),
        ],
        className="shadow-sm",
    )


# =========================================================
# 31. 主程式
# =========================================================
if __name__ == "__main__":
    mapping = scan_coverage_csvs()

    print("=" * 75)
    print("🚀 Layer Coverage Dash")
    print("🌐 URL：http://127.0.0.1:8076")
    print(f"📁 Coverage CSV：{COVERAGE_CSV_DIR}")
    print(f"📁 資料夾存在：{COVERAGE_CSV_DIR.exists()}")
    print(f"📄 找到 Layer 數量：{len(mapping)}")

    if mapping:
        layers = sorted(mapping.keys())

        print(
            f"📚 Layer 範圍："
            f"{layers[0]} ～ {layers[-1]}"
        )

        print(
            f"📚 前 20 個 Layer："
            f"{layers[:20]}"
        )

    print(
        "📌 三層合併規則："
        f"n ≥ {CURRENT_FILL_THRESHOLD:g} 時，"
        f"使用 n × {CURRENT_LAYER_BOOST:g}；"
        f"否則使用 max("
        f"n-1 × {PREVIOUS_LAYER_WEIGHT:g}, "
        f"n+1 × {NEXT_LAYER_WEIGHT:g})"
    )

    print(
        "📊 影響率規則："
        "各層實際貢獻 Coverage 總和 ÷ "
        "全部實際貢獻 Coverage 總和 × 100%"
    )

    print(
        "🎨 顏色："
        "n-1 藍色｜"
        "n 紅色｜"
        "n+1 綠色｜"
        "三層合併 Jet"
    )

    print(
        "📐 均勻度門檻："
        f"PASS CV ≤ {UNIFORMITY_CV_PASS:.2f} 且 "
        f"P95-P5/平均 ≤ {UNIFORMITY_RANGE_PASS:.2f}｜"
        f"WARN CV ≤ {UNIFORMITY_CV_WARN:.2f} 且 "
        f"P95-P5/平均 ≤ {UNIFORMITY_RANGE_WARN:.2f}"
    )

    print("=" * 75)

    serve(
        app.server,
        host="0.0.0.0",
        port=8076,
    )
