# -*- coding: utf-8 -*-
"""
Layer Feature FastAPI Backend

已移除圖片顯示功能版本

功能：
1. 提供 Dash 讀取 Layer CSV 資料
2. 提供 Dash 讀取 XY 路徑資料
3. 提供 Dash 讀取 Meltpoolwidth 資料
4. 提供每層統計資訊
5. 不讀取圖片
6. 不提供圖片 API
7. 不產生 Matplotlib 預覽圖

安裝套件：
    pip install fastapi uvicorn pandas numpy

直接執行方式：
    python layerfeature_visual.py

API 文件：
    http://127.0.0.1:8005/docs

Dash 可讀取：
    http://127.0.0.1:8005/layers
    http://127.0.0.1:8005/layers/meta
    http://127.0.0.1:8005/layer/1
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ============================================================
# 1. 使用者設定
# ============================================================

# 放 1~250 個 csv 的資料夾
CSV_DIR = Path(
    r"D:\2026Experiment\2026Experiment0528\dash\NIST\7. Analysis\layerfeature_visual\part01"
)

# API 設定
API_TITLE = "Layer Feature API"
API_VERSION = "1.0.0"

# Layer 範圍
START_LAYER = 1
END_LAYER = 250

# CSV 欄位設定，0-based index
COL_X = 2       # 第3欄 laser position in X-axis(mm)
COL_Y = 3       # 第4欄 laser position in Y-axis(mm)
COL_W = 11      # 第13欄 Meltpoolwidth(mm)

# 線段顯示資料設定
USE_WIDTH_AS_LINEWIDTH = False
MIN_LINEWIDTH = 0.8
MAX_LINEWIDTH = 3.5
DEFAULT_LINEWIDTH = 3.0
CMAP = "jet"

# 色階範圍是否用百分位，避免極端值拉爆
USE_PERCENTILE_COLOR_LIMIT = True
COLOR_PERCENTILE_LOW = 1
COLOR_PERCENTILE_HIGH = 99

# 固定座標軸範圍設定
FIXED_AXIS_LIMIT = True


# ============================================================
# 2. API 回傳資料模型
# ============================================================

class LayerMeta(BaseModel):
    layer_id: int
    csv_name: str
    csv_path: str
    rows: int


class GlobalInfo(BaseModel):
    csv_dir: str
    start_layer: int
    end_layer: int
    loaded_count: int
    missing_count: int
    missing_layers: List[int]
    layer_ids: List[int]
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    w_min: float
    w_max: float
    cmap: str
    fixed_axis_limit: bool


# ============================================================
# 3. 工具函式
# ============================================================

def find_layer_file(csv_dir: Path, layer_id: int) -> Optional[Path]:
    """
    尋找指定 layer 的 CSV。

    優先找：
        L0001.csv

    若沒有，再找：
        L0001*.csv
    """
    exact_path = csv_dir / f"L{layer_id:04d}.csv"

    if exact_path.exists():
        return exact_path

    candidates = sorted(csv_dir.glob(f"L{layer_id:04d}*.csv"))

    if candidates:
        return candidates[0]

    return None


def read_one_csv(csv_path: Path) -> pd.DataFrame:
    """
    讀取單一 CSV。

    只讀三欄：
        x_mm
        y_mm
        meltpool_width_mm

    若遇到文字或壞行，會轉成 NaN 後移除。
    """
    df = pd.read_csv(
        csv_path,
        header=None,
        usecols=[COL_X, COL_Y, COL_W],
        engine="python",
        on_bad_lines="skip",
    )

    df.columns = ["x_mm", "y_mm", "meltpool_width_mm"]

    df["x_mm"] = pd.to_numeric(df["x_mm"], errors="coerce")
    df["y_mm"] = pd.to_numeric(df["y_mm"], errors="coerce")
    df["meltpool_width_mm"] = pd.to_numeric(
        df["meltpool_width_mm"],
        errors="coerce",
    )

    df = df.dropna(
        subset=["x_mm", "y_mm", "meltpool_width_mm"]
    ).reset_index(drop=True)

    return df


def safe_float(value) -> float:
    """
    避免 JSON 回傳 NaN / inf。
    """
    if value is None:
        return 0.0

    value = float(value)

    if not np.isfinite(value):
        return 0.0

    return value


def downsample_df(df: pd.DataFrame, max_points: int = 0) -> pd.DataFrame:
    """
    給 Dash 讀取時可選擇降採樣，避免資料太大。

    max_points = 0 代表不降採樣。
    """
    if max_points is None or max_points <= 0:
        return df

    if len(df) <= max_points:
        return df

    idx = np.linspace(0, len(df) - 1, max_points).astype(int)

    return df.iloc[idx].reset_index(drop=True)


def width_to_linewidth(
    width_values: np.ndarray,
    w_min: float,
    w_max: float,
) -> np.ndarray:
    """
    將 meltpool width 映射成線寬。

    Dash 如果要畫彩色線段，可以使用回傳的 line_width。
    """
    if w_max <= w_min:
        return np.full_like(
            width_values,
            (MIN_LINEWIDTH + MAX_LINEWIDTH) / 2,
            dtype=float,
        )

    ratio = (width_values - w_min) / (w_max - w_min)
    ratio = np.clip(ratio, 0, 1)

    return MIN_LINEWIDTH + ratio * (MAX_LINEWIDTH - MIN_LINEWIDTH)


def make_segment_payload(
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    w_min: float,
    w_max: float,
) -> List[Dict]:
    """
    將連續點轉成線段資料。

    Dash 可以用這個 segments 畫每一小段雷射路徑。
    每段線的 Meltpoolwidth 使用前後兩點平均。
    """
    if len(x) < 2:
        return []

    w_seg = 0.5 * (w[:-1] + w[1:])

    if USE_WIDTH_AS_LINEWIDTH:
        line_widths = width_to_linewidth(w_seg, w_min, w_max)
    else:
        line_widths = np.full_like(
            w_seg,
            DEFAULT_LINEWIDTH,
            dtype=float,
        )

    segments = []

    for i in range(len(w_seg)):
        segments.append(
            {
                "x": [
                    safe_float(x[i]),
                    safe_float(x[i + 1]),
                ],
                "y": [
                    safe_float(y[i]),
                    safe_float(y[i + 1]),
                ],
                "meltpool_width_mm": safe_float(w_seg[i]),
                "line_width": safe_float(line_widths[i]),
            }
        )

    return segments


# ============================================================
# 4. 全域資料快取
# ============================================================

all_layers: List[Dict] = []
missing_layers: List[int] = []
layer_map: Dict[int, Dict] = {}
global_info: Optional[Dict] = None


def load_all_layers() -> None:
    """
    啟動 API 時讀取所有 layer。
    並計算全域座標範圍與色階範圍。

    這版不讀取圖片。
    """
    global all_layers
    global missing_layers
    global layer_map
    global global_info

    all_layers = []
    missing_layers = []
    layer_map = {}
    global_info = None

    if not CSV_DIR.exists():
        raise RuntimeError(f"CSV_DIR 不存在，請確認路徑：{CSV_DIR}")

    for layer_id in range(START_LAYER, END_LAYER + 1):
        csv_path = find_layer_file(CSV_DIR, layer_id)

        if csv_path is None:
            missing_layers.append(layer_id)
            continue

        try:
            df = read_one_csv(csv_path)
        except Exception as exc:
            print(f"[WARN] CSV 讀取失敗：{csv_path} | {exc}")
            missing_layers.append(layer_id)
            continue

        if len(df) < 2:
            print(f"[WARN] {csv_path.name} 有效資料少於 2 筆，略過")
            missing_layers.append(layer_id)
            continue

        item = {
            "layer_id": layer_id,
            "csv_path": csv_path,
            "df": df,
        }

        all_layers.append(item)
        layer_map[layer_id] = item

    if not all_layers:
        raise RuntimeError(
            "沒有讀到任何有效 CSV，請確認 CSV_DIR 路徑與檔名格式。"
        )

    all_x = np.concatenate(
        [item["df"]["x_mm"].to_numpy() for item in all_layers]
    )

    all_y = np.concatenate(
        [item["df"]["y_mm"].to_numpy() for item in all_layers]
    )

    all_w = np.concatenate(
        [item["df"]["meltpool_width_mm"].to_numpy() for item in all_layers]
    )

    x_min = safe_float(np.nanmin(all_x))
    x_max = safe_float(np.nanmax(all_x))
    y_min = safe_float(np.nanmin(all_y))
    y_max = safe_float(np.nanmax(all_y))

    if USE_PERCENTILE_COLOR_LIMIT:
        w_min = safe_float(
            np.nanpercentile(all_w, COLOR_PERCENTILE_LOW)
        )
        w_max = safe_float(
            np.nanpercentile(all_w, COLOR_PERCENTILE_HIGH)
        )
    else:
        w_min = safe_float(np.nanmin(all_w))
        w_max = safe_float(np.nanmax(all_w))

    if w_max <= w_min:
        w_max = w_min + 1e-6

    global_info = {
        "csv_dir": str(CSV_DIR),
        "start_layer": START_LAYER,
        "end_layer": END_LAYER,
        "loaded_count": len(all_layers),
        "missing_count": len(missing_layers),
        "missing_layers": missing_layers,
        "layer_ids": [item["layer_id"] for item in all_layers],
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "w_min": w_min,
        "w_max": w_max,
        "cmap": CMAP,
        "fixed_axis_limit": FIXED_AXIS_LIMIT,
    }

    print(f"[INFO] 成功讀取 {len(all_layers)} 個 layer")
    print(f"[INFO] CSV_DIR = {CSV_DIR}")

    if missing_layers:
        print(f"[WARN] 找不到或無效 layer 數量：{len(missing_layers)}")
        print(
            f"[WARN] missing layers: "
            f"{missing_layers[:30]}"
            f"{' ...' if len(missing_layers) > 30 else ''}"
        )


def get_layer_or_404(layer_id: int) -> Dict:
    """
    取得指定 layer。
    如果不存在，回傳 404。
    """
    item = layer_map.get(layer_id)

    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Layer {layer_id} 不存在或 CSV 無效",
        )

    return item


def build_layer_meta(item: Dict) -> Dict:
    """
    建立單一 layer 的基本資訊。
    """
    return {
        "layer_id": item["layer_id"],
        "csv_name": item["csv_path"].name,
        "csv_path": str(item["csv_path"]),
        "rows": int(len(item["df"])),
    }


def build_layer_payload(
    layer_id: int,
    max_points: int = 0,
    include_segments: bool = True,
) -> Dict:
    """
    建立 Dash 可直接讀取的 JSON。
    """
    item = get_layer_or_404(layer_id)

    df_original = item["df"]
    df = downsample_df(df_original, max_points=max_points)

    x = df["x_mm"].to_numpy(dtype=float)
    y = df["y_mm"].to_numpy(dtype=float)
    w = df["meltpool_width_mm"].to_numpy(dtype=float)

    payload = {
        "meta": build_layer_meta(item),
        "global": global_info,
        "data": {
            "x_mm": [safe_float(v) for v in x],
            "y_mm": [safe_float(v) for v in y],
            "meltpool_width_mm": [safe_float(v) for v in w],
        },
        "stats": {
            "rows_original": int(len(df_original)),
            "rows_returned": int(len(df)),
            "x_min": safe_float(np.nanmin(x)),
            "x_max": safe_float(np.nanmax(x)),
            "y_min": safe_float(np.nanmin(y)),
            "y_max": safe_float(np.nanmax(y)),
            "meltpool_width_min": safe_float(np.nanmin(w)),
            "meltpool_width_max": safe_float(np.nanmax(w)),
            "meltpool_width_mean": safe_float(np.nanmean(w)),
            "meltpool_width_std": safe_float(np.nanstd(w)),
        },
    }

    if include_segments:
        payload["segments"] = make_segment_payload(
            x=x,
            y=y,
            w=w,
            w_min=global_info["w_min"],
            w_max=global_info["w_max"],
        )
    else:
        payload["segments"] = []

    return payload


# ============================================================
# 5. FastAPI App
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    取代 @app.on_event("startup")，避免 DeprecationWarning。
    API 啟動時自動讀取 CSV。
    """
    load_all_layers()
    yield


app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    lifespan=lifespan,
)

# 讓 Dash 從不同 port 讀取 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> Dict:
    """
    API 首頁。
    """
    return {
        "message": "Layer Feature API is running",
        "docs": "/docs",
        "layers": "/layers",
        "layers_meta": "/layers/meta",
        "example_layer": f"/layer/{START_LAYER}",
        "csv_dir": str(CSV_DIR),
        "note": "圖片顯示功能已移除，只提供 CSV 數值資料給 Dash 讀取。",
    }


@app.get("/health")
def health() -> Dict:
    """
    檢查 API 是否正常運作。
    """
    return {
        "status": "ok",
        "csv_dir": str(CSV_DIR),
        "csv_dir_exists": CSV_DIR.exists(),
        "loaded_count": len(all_layers),
        "missing_count": len(missing_layers),
    }


@app.post("/reload")
def reload_data() -> Dict:
    """
    重新讀取 CSV。
    修改 CSV 資料後可以呼叫，不用重開 API。
    """
    load_all_layers()

    return {
        "status": "reloaded",
        "loaded_count": len(all_layers),
        "missing_count": len(missing_layers),
    }


@app.get("/layers", response_model=GlobalInfo)
def get_layers() -> Dict:
    """
    取得所有可用 layer 與全域顯示資訊。
    """
    return global_info


@app.get("/layers/meta", response_model=List[LayerMeta])
def get_layers_meta() -> List[Dict]:
    """
    取得每一層的 CSV 基本資訊。
    """
    return [build_layer_meta(item) for item in all_layers]


@app.get("/layer/{layer_id}")
def get_layer_data(
    layer_id: int,
    max_points: int = Query(
        0,
        ge=0,
        description="0=不降採樣；例如 3000 可降低 Dash 傳輸量",
    ),
    include_segments: bool = Query(
        True,
        description="是否回傳線段資料，Dash 畫彩色線段時使用",
    ),
) -> Dict:
    """
    取得單一 layer 的 XY 與 Meltpoolwidth 資料。
    """
    return build_layer_payload(
        layer_id=layer_id,
        max_points=max_points,
        include_segments=include_segments,
    )


# ============================================================
# 6. 直接 python layerfeature_visual.py 執行
# ============================================================

if __name__ == "__main__":
    import uvicorn

    print("====================================================")
    print("Layer Feature API")
    print("API URL: http://127.0.0.1:8055")
    print("Docs: http://127.0.0.1:8055/docs")
    print("CSV_DIR:", CSV_DIR)
    print("注意：這版使用 uvicorn.run(app)，不會再 import layer_feature_api")
    print("====================================================")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8055,
        reload=False,
    )

