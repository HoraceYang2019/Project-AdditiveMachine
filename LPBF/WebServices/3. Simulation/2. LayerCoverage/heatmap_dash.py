# === heatmap_api.py ===
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
import pandas as pd
import numpy as np
import os
import re

app = FastAPI()

# =========================================================
# Layer Coverage Heatmap CSV 資料夾
# =========================================================
DATA_FOLDER = r"D:\2026Experiment\2026Experiment0528\dash\NIST\3. Simulation\Layer_Coverage\heatmap_csv"


# =========================================================
# 低值門檻
# =========================================================
# 原本可能只判斷 0 或直接顯示原始 CSV。
# 現在改成：
#
# 目前層 >= 1000：使用目前層數值
# 目前層 < 1000 ：補前一層殘留值
# 前一層 < 1000 ：不算有效殘留，補 0
LOW_VALUE_THRESHOLD = 1000.0


# =========================================================
# 自動取得可用 Layer 編號
# 檔名格式：
# layer_0_heatmap.csv
# layer_1_heatmap.csv
# layer_2_heatmap.csv
# ...
# =========================================================
def get_available_layers():
    if not os.path.exists(DATA_FOLDER):
        return []

    layers = []
    pattern = re.compile(r"^layer_(\d+)_heatmap\.csv$")

    for f in os.listdir(DATA_FOLDER):
        match = pattern.match(f)

        if match:
            try:
                layer_id = int(match.group(1))
                layers.append(layer_id)
            except Exception:
                pass

    return sorted(layers)


# =========================================================
# 尋找指定 Layer CSV
# =========================================================
def find_layer_file(layer: int):
    filename = f"layer_{layer}_heatmap.csv"
    file_path = os.path.join(DATA_FOLDER, filename)

    if os.path.exists(file_path):
        return file_path

    available_layers = get_available_layers()

    raise HTTPException(
        status_code=404,
        detail={
            "message": f"指定的層數 {layer} 不存在。",
            "expected_filename": filename,
            "data_folder": DATA_FOLDER,
            "available_layers": available_layers,
        },
    )


# =========================================================
# 讀取單一 Heatmap CSV
# =========================================================
def load_single_heatmap_csv(file_path: str):
    """
    讀取單一 Layer Coverage Heatmap CSV。

    處理方式：
    1. header=None，沒有標題列
    2. 全部轉成數值
    3. NaN 補 0
    4. np.fliplr() 左右翻轉 X 軸
    """
    df = pd.read_csv(file_path, header=None)

    data = df.apply(pd.to_numeric, errors="coerce").values
    data = np.nan_to_num(data, nan=0.0)

    # 左右翻轉 X 軸
    data = np.fliplr(data)

    if data.ndim != 2:
        raise ValueError("CSV 不是 2D 陣列")

    if data.size == 0:
        raise ValueError("CSV 沒有有效數值")

    return data


# =========================================================
# 小於 1000 補前一層殘留值
# =========================================================
def fill_below_threshold_with_previous_residual(current_data, previous_data):
    """
    目前層小於 1000 的地方，補前一層殘留值。

    規則：
        current >= LOW_VALUE_THRESHOLD：
            使用 current

        current < LOW_VALUE_THRESHOLD：
            補 previous_residual

        previous_residual：
            previous >= LOW_VALUE_THRESHOLD 才算有效殘留
            previous < LOW_VALUE_THRESHOLD 補 0
    """
    current_data = np.asarray(current_data, dtype=float)
    previous_data = np.asarray(previous_data, dtype=float)

    if current_data.ndim != 2 or previous_data.ndim != 2:
        raise ValueError("目前層與前一層資料都必須是 2D 陣列")

    rows = min(current_data.shape[0], previous_data.shape[0])
    cols = min(current_data.shape[1], previous_data.shape[1])

    if rows <= 0 or cols <= 0:
        raise ValueError("CSV 尺寸無效，無法進行補值")

    current_crop = current_data[:rows, :cols]
    previous_crop = previous_data[:rows, :cols]

    # 前一層有效殘留：只有 >= 1000 才保留
    previous_residual = np.where(
        previous_crop >= LOW_VALUE_THRESHOLD,
        previous_crop,
        0.0,
    )

    # 目前層有效區：只有 >= 1000 才使用目前層
    current_mask = current_crop >= LOW_VALUE_THRESHOLD

    # 目前層 >= 1000 用目前層
    # 目前層 < 1000 補前一層殘留
    display_data = np.where(
        current_mask,
        current_crop,
        previous_residual,
    )

    return display_data


# =========================================================
# 載入顯示用 Heatmap Layer
# =========================================================
def load_display_heatmap_layer(layer: int):
    """
    載入顯示用 Layer Coverage Heatmap。

    Layer 0：
        直接讀 layer_0_heatmap.csv

    Layer 1 以上：
        目前層為主
        目前層小於 1000 的區域補前一層殘留值
    """
    current_file_path = find_layer_file(layer)
    current_data = load_single_heatmap_csv(current_file_path)

    if layer <= 0:
        return current_data, {
            "mode": "single_layer",
            "layer": layer,
            "current_file": os.path.basename(current_file_path),
            "previous_layer": None,
            "previous_file": None,
            "rule": "Layer 0 直接顯示 layer_0_heatmap.csv",
        }

    previous_layer = layer - 1
    previous_file_path = find_layer_file(previous_layer)
    previous_data = load_single_heatmap_csv(previous_file_path)

    display_data = fill_below_threshold_with_previous_residual(
        current_data=current_data,
        previous_data=previous_data,
    )

    return display_data, {
        "mode": "fill_below_1000_with_previous_residual",
        "layer": layer,
        "current_file": os.path.basename(current_file_path),
        "previous_layer": previous_layer,
        "previous_file": os.path.basename(previous_file_path),
        "rule": (
            f"目前層 {os.path.basename(current_file_path)} 為主，"
            f"小於 {LOW_VALUE_THRESHOLD:g} 的區域補前一層 "
            f"{os.path.basename(previous_file_path)} 的殘留值"
        ),
    }


# =========================================================
# Heatmap API
#
# Dash 前端可以打：
# http://127.0.0.1:8002/heatmap/?layer=0
# http://127.0.0.1:8002/heatmap/?layer=1
# =========================================================
@app.get("/heatmap/")
@app.get("/heatmap")
def get_heatmap(layer: int = Query(..., description="層數，例如 0 ~ 250")):
    if not os.path.exists(DATA_FOLDER):
        raise HTTPException(
            status_code=404,
            detail=f"找不到資料夾：{DATA_FOLDER}",
        )

    available_layers = get_available_layers()

    if layer not in available_layers:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"指定的層數 {layer} 不存在，請確認是否有對應的 CSV 檔案。",
                "data_folder": DATA_FOLDER,
                "available_layers": available_layers,
            },
        )

    try:
        data, layer_info = load_display_heatmap_layer(layer)

        return JSONResponse(
            content={
                "layer": layer,
                "heatmap": data.tolist(),
                "shape": list(data.shape),
                "low_value_threshold": LOW_VALUE_THRESHOLD,
                "mode": layer_info["mode"],
                "current_file": layer_info["current_file"],
                "previous_layer": layer_info["previous_layer"],
                "previous_file": layer_info["previous_file"],
                "rule": layer_info["rule"],
            }
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"處理熱圖發生錯誤：{str(e)}",
        )


# =========================================================
# 可用 Layer 清單
#
# http://127.0.0.1:8002/heatmap_layers/
# =========================================================
@app.get("/heatmap_layers/")
@app.get("/heatmap_layers")
def heatmap_layers():
    return JSONResponse(
        content={
            "data_folder": DATA_FOLDER,
            "folder_exists": os.path.exists(DATA_FOLDER),
            "file_pattern": "layer_{layer}_heatmap.csv",
            "available_layers": get_available_layers(),
            "low_value_threshold": LOW_VALUE_THRESHOLD,
            "rule": (
                f"Layer 1 以上會將目前層小於 {LOW_VALUE_THRESHOLD:g} 的區域，"
                "補成前一層有效殘留值"
            ),
        }
    )


# =========================================================
# 健康檢查
#
# http://127.0.0.1:8002/health/
# =========================================================
@app.get("/health/")
@app.get("/health")
def health():
    return JSONResponse(
        content={
            "status": "ok",
            "message": "Layer Coverage Heatmap API is running",
            "data_folder": DATA_FOLDER,
            "folder_exists": os.path.exists(DATA_FOLDER),
            "file_pattern": "layer_{layer}_heatmap.csv",
            "available_layers": get_available_layers(),
            "low_value_threshold": LOW_VALUE_THRESHOLD,
            "rule": (
                f"目前層 >= {LOW_VALUE_THRESHOLD:g} 使用目前層；"
                f"目前層 < {LOW_VALUE_THRESHOLD:g} 補前一層殘留值"
            ),
        }
    )


# =========================================================
# 啟動伺服器
# =========================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8002,
    )