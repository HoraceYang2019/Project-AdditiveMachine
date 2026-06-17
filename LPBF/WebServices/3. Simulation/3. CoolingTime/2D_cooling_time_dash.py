# === coolingtime_api.py ===
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
import pandas as pd
import numpy as np
import os
import re
import uvicorn

app = FastAPI()

# =========================================================
# CoolingTime CSV 資料夾
# =========================================================
DATA_FOLDER = r"D:\2026Experiment\2026Experiment0528\dash\NIST\3. Simulation\Cooling_Time\cooling_layer_csv"


# =========================================================
# 低值門檻
# =========================================================
# 原本是用 0 判斷空白區域
# 現在改成：低於 200 視為空白／不足區域
#
# 目前層 >= 200：使用目前層數值
# 目前層 < 200 ：補前一層殘留值
# 前一層 < 200 ：不算有效殘留，補 0
LOW_VALUE_THRESHOLD = 200.0


# =========================================================
# Heatmap 色階設定
# =========================================================
COOLING_ZMIN = 0
COOLING_ZMAX = 1600


# =========================================================
# 自動取得可用 Layer / Frame 編號
# 檔名格式：
# cooling_layer_1_0.csv
# cooling_layer_1_1.csv
# ...
# cooling_layer_1_250.csv
# =========================================================
def get_available_layers():
    if not os.path.exists(DATA_FOLDER):
        return []

    layers = []
    pattern = re.compile(r"^cooling_layer_1_(\d+)\.csv$")

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
# 尋找指定 Layer / Frame 檔案
# =========================================================
def find_layer_file(layer: int):
    filename = f"cooling_layer_1_{layer}.csv"
    file_path = os.path.join(DATA_FOLDER, filename)

    if os.path.exists(file_path):
        return file_path

    available_layers = get_available_layers()

    raise HTTPException(
        status_code=404,
        detail={
            "message": f"指定的 layer/frame {layer} 不存在。",
            "expected_filename": filename,
            "data_folder": DATA_FOLDER,
            "available_layers": available_layers,
        },
    )


# =========================================================
# 讀取單一 CoolingTime CSV
# =========================================================
def load_single_cooling_csv(file_path: str):
    """
    讀取單一 CoolingTime CSV，轉成 2D numpy array。

    處理方式：
    1. header=None，沒有標題列
    2. 轉成數值
    3. NaN 補 0
    4. np.fliplr() 左右翻轉
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
# 低於 200 補前一層殘留值
# =========================================================
def fill_below_threshold_with_previous_residual(current_data, previous_data):
    """
    目前層低於 200 的地方，補前一層殘留值。

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

    # 前一層有效殘留：只有 >= 200 才保留
    previous_residual = np.where(
        previous_crop >= LOW_VALUE_THRESHOLD,
        previous_crop,
        0.0,
    )

    # 目前層有效區：只有 >= 200 才使用目前層
    current_mask = current_crop >= LOW_VALUE_THRESHOLD

    # 目前層 >= 200 用目前層
    # 目前層 < 200 補前一層殘留
    display_data = np.where(
        current_mask,
        current_crop,
        previous_residual,
    )

    return display_data


# =========================================================
# 載入顯示用 CoolingTime Layer
# =========================================================
def load_display_cooling_layer(layer: int):
    """
    載入顯示用 CoolingTime。

    Layer 0：
        直接讀 cooling_layer_1_0.csv

    Layer 1 以上：
        目前層為主
        目前層低於 200 的區域補前一層殘留值
    """
    current_file_path = find_layer_file(layer)
    current_data = load_single_cooling_csv(current_file_path)

    if layer <= 0:
        return current_data, {
            "mode": "single_layer",
            "layer": layer,
            "current_file": os.path.basename(current_file_path),
            "previous_layer": None,
            "previous_file": None,
            "rule": "Layer 0 直接顯示 cooling_layer_1_0.csv",
        }

    previous_layer = layer - 1
    previous_file_path = find_layer_file(previous_layer)
    previous_data = load_single_cooling_csv(previous_file_path)

    display_data = fill_below_threshold_with_previous_residual(
        current_data=current_data,
        previous_data=previous_data,
    )

    return display_data, {
        "mode": "fill_below_200_with_previous_residual",
        "layer": layer,
        "current_file": os.path.basename(current_file_path),
        "previous_layer": previous_layer,
        "previous_file": os.path.basename(previous_file_path),
        "rule": (
            f"目前層 {os.path.basename(current_file_path)} 為主，"
            f"低於 {LOW_VALUE_THRESHOLD:g} 的區域補前一層 "
            f"{os.path.basename(previous_file_path)} 的殘留值"
        ),
    }


# =========================================================
# CoolingTime API
#
# Dash 前端可以打這個：
# http://127.0.0.1:8003/coolingtime/?layer=0
# http://127.0.0.1:8003/coolingtime/?layer=250
# =========================================================
@app.get("/coolingtime/")
@app.get("/coolingtime")
def get_coolingtime(layer: int = Query(..., description="層數/Frame，例如 0 ~ 250")):
    if not os.path.exists(DATA_FOLDER):
        raise HTTPException(
            status_code=404,
            detail=f"找不到資料夾：{DATA_FOLDER}",
        )

    try:
        data, layer_info = load_display_cooling_layer(layer)

        return JSONResponse(
            content={
                "layer": layer,
                "file_name": layer_info["current_file"],
                "data_folder": DATA_FOLDER,
                "heatmap": data.tolist(),
                "shape": list(data.shape),
                "zmin": COOLING_ZMIN,
                "zmax": COOLING_ZMAX,
                "unit": "us",
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
            detail=f"處理 CoolingTime CSV 發生錯誤：{str(e)}",
        )


# =========================================================
# 可用 Layer / Frame 清單
#
# http://127.0.0.1:8003/coolingtime_layers/
# =========================================================
@app.get("/coolingtime_layers/")
@app.get("/coolingtime_layers")
def coolingtime_layers():
    return JSONResponse(
        content={
            "data_folder": DATA_FOLDER,
            "folder_exists": os.path.exists(DATA_FOLDER),
            "file_pattern": "cooling_layer_1_{layer}.csv",
            "available_layers": get_available_layers(),
            "low_value_threshold": LOW_VALUE_THRESHOLD,
            "rule": (
                f"Layer 1 以上會將目前層低於 {LOW_VALUE_THRESHOLD:g} 的區域，"
                "補成前一層有效殘留值"
            ),
        }
    )


# =========================================================
# 健康檢查
#
# http://127.0.0.1:8003/health/
# =========================================================
@app.get("/health/")
@app.get("/health")
def health():
    return JSONResponse(
        content={
            "status": "ok",
            "message": "CoolingTime API is running",
            "data_folder": DATA_FOLDER,
            "folder_exists": os.path.exists(DATA_FOLDER),
            "file_pattern": "cooling_layer_1_{layer}.csv",
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
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8003,
    )