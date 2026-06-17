# -*- coding: utf-8 -*-
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

import numpy as np
import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from dash import Dash, html, dcc, Input, Output, State, no_update
from dash.exceptions import PreventUpdate

try:
    from skimage import measure
    SKIMAGE_AVAILABLE = True
    SKIMAGE_IMPORT_ERROR = None
except Exception as e:
    measure = None
    SKIMAGE_AVAILABLE = False
    SKIMAGE_IMPORT_ERROR = e


# =========================================================
# 0. 基本路徑設定
# =========================================================
BASE_DIR = Path(__file__).parent.resolve()
ASSETS_DIR = BASE_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

APP_URLS = {
    "workspace": "http://127.0.0.1:8071",
    "step1": "http://127.0.0.1:8074",
    "step3a": "http://127.0.0.1:8076",
    "step3b": "http://127.0.0.1:8077",
    "step4": "http://127.0.0.1:8078",
}

RUN_SCRIPT_PATH = (BASE_DIR / "train_sg_mpt.py").resolve()

LOCAL_ROOT = BASE_DIR / "step4_local_data"
SUMMARY_DIR = LOCAL_ROOT / "step4_summaries"
LOG_DIR = SUMMARY_DIR / "logs"

for folder in (LOCAL_ROOT, SUMMARY_DIR, LOG_DIR):
    folder.mkdir(parents=True, exist_ok=True)


# =========================================================
# 1. 左側固定讀取 STL 切割 NPZ
# =========================================================
LEFT_NPZ_PATH = Path(
    r"D:\2026Experiment\2026Experiment0528\dash\NIST\3. Simulation\Surface_Profile\Cut_npz\surface_profile_from_stl.npz"
)


# =========================================================
# 2. 右側讀取 NPZ
# =========================================================
# 注意：
# 這裡可以放「資料夾路徑」，也可以直接放「單一 .npz 檔案路徑」。
# 本程式已修正 find_latest_npz()，兩種都支援。
NPZ_DIR = Path(
    r"D:\2026Experiment\2026Experiment0528\dash\NIST\3. Simulation\Surface_Profile\stacked_voxel_count_L0248_to_L0250.npz"
)

NPZ_EXTS = [".npz"]


# =========================================================
# 3. 顯示與色階設定
# =========================================================
MAX_DISPLAY_VOXELS = 8_000_000
MAX_MESH_FACES = 600_000
MAX_SURFACE_POINTS = 800_000

# Z 軸視覺放大倍率
Z_EXAGGERATION = 3.0

# xyz_solid01 是否裁切空白邊界
TRIM_3D_EMPTY_BORDER = True

# xyz_solid01 是否補滿 zmin~zmax，讓模型看起來是實體
FILL_INTERVAL_SOLID = True

# xyz_solid01 優先用 Mesh3d 顯示
PREFER_MESH3D_FOR_XYZ = True

# 是否使用高度差上色
USE_HEIGHT_TEXTURE_COLOR = True

# 色階
TEXTURE_COLORSCALE = "Viridis"

# colorbar 固定 0~120 um
HEIGHT_COLOR_MIN_UM = 0
HEIGHT_COLOR_MAX_UM = 120

# =========================================================
# 3-1. 上表面高低落差分析設定
# =========================================================
# 外圍多少比例算「邊緣」；0.15 = 外圍 15%
EDGE_RATIO = 0.15

# 中間多少比例算「中心」；0.40 = 中間 40%
CENTER_RATIO = 0.40

# 平均高度差提醒門檻，單位 um
WARNING_DIFF_UM = 10.0

# 平均高度差嚴重門檻，單位 um
FAIL_DIFF_UM = 25.0

SURFACE_GRAY_COLOR = "#A9A9A9"


# =========================================================
# 4. Dash Layout Style
# =========================================================
CONTENT_OPEN = {
    "marginLeft": "260px",
    "padding": "10px",
    "paddingTop": "6px",
    "paddingBottom": "12px",
    "transition": "margin-left 0.25s ease",
    "minHeight": "calc(100vh - 56px)",
    "width": "calc(100% - 260px)",
    "maxWidth": "100%",
    "overflowX": "hidden",
    "boxSizing": "border-box",
}

CONTENT_CLOSED = {
    **CONTENT_OPEN,
    "marginLeft": "16px",
    "width": "calc(100% - 16px)",
}

GRAPH_STYLE = {
    "width": "100%",
    "height": "clamp(520px, 78vh, 980px)",
    "minHeight": "520px",
}

CARD_FILL = {
    "width": "100%",
    "height": "100%",
    "minHeight": "0",
    "minWidth": "0",
}


# =========================================================
# 5. 建立 Dash App
# =========================================================
app = Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.DARKLY,
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css",
    ],
    suppress_callback_exceptions=True,
    assets_folder=str(ASSETS_DIR),
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

app.title = "Step 4 — Surface_profile"

template_path = BASE_DIR / "templates" / "surface_profile.html"
app.index_string = (
    template_path.read_text(encoding="utf-8")
    if template_path.exists()
    else "<html><body>{%app_entry%}{%config%}{%scripts%}{%renderer%}</body></html>"
)


# =========================================================
# 6. Run 狀態
# =========================================================
current_proc: Optional[subprocess.Popen] = None
run_start_ts: Optional[float] = None
current_log_path: Optional[Path] = None
log_fh = None


def now_ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def fmt_elapsed(sec: float):
    sec = max(0, int(sec))
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


# =========================================================
# 7. 找最新 NPZ
# =========================================================
def find_latest_npz(path: Path):
    """
    支援兩種用法：

    1. path 是單一 .npz 檔案：
       直接回傳該檔案。

    2. path 是資料夾：
       自動搜尋資料夾內最新的 .npz 檔案。

    修正錯誤：
    NotADirectoryError: [WinError 267] 目錄名稱無效

    原因：
    原本程式把單一 .npz 檔案當成資料夾使用 iterdir()。
    """
    path = Path(path)

    if not path.exists():
        return None

    # 如果 path 本身就是 .npz 檔案，直接回傳
    if path.is_file():
        if path.suffix.lower() in NPZ_EXTS:
            return path
        return None

    # 如果 path 是資料夾，搜尋最新 .npz
    if path.is_dir():
        files = [
            p for p in path.iterdir()
            if p.is_file() and p.suffix.lower() in NPZ_EXTS
        ]

        if not files:
            return None

        return max(files, key=lambda p: p.stat().st_mtime)

    return None


# =========================================================
# 8. 2D 降採樣
# =========================================================
def downsample_2d(arr, max_points=800_000):
    arr = np.asarray(arr)

    if arr.ndim != 2:
        raise ValueError(f"height map 必須是 2D，但目前 shape={arr.shape}")

    h, w = arr.shape
    total = int(h * w)

    if total <= int(max_points):
        return arr, 1

    stride = int(np.ceil(np.sqrt(total / float(max_points))))
    stride = max(1, stride)

    return arr[::stride, ::stride], stride


# =========================================================
# 9. xyz_solid01 體素處理
# =========================================================
def build_interval_filled_xyz(zmax_abs, zmin_abs=None):
    """
    將每個 XY 位置的 zmin~zmax 補成實體。
    這樣 marching cubes 才會顯示成實心工件，不會只有薄薄一層。
    """

    zmax_abs = np.asarray(zmax_abs, dtype=np.int32)

    if zmin_abs is None:
        zmin_abs = np.where(zmax_abs >= 0, 0, -1).astype(np.int32, copy=False)
    else:
        zmin_abs = np.asarray(zmin_abs, dtype=np.int32)

    valid_mask = zmax_abs >= 0
    zmin_abs = np.where(valid_mask, zmin_abs, -1).astype(np.int32, copy=False)
    zmin_abs = np.where(
        valid_mask,
        np.minimum(zmin_abs, zmax_abs),
        -1,
    ).astype(np.int32, copy=False)

    max_abs = int(np.max(zmax_abs)) if np.any(valid_mask) else -1

    if max_abs < 0:
        return np.zeros((1, zmax_abs.shape[0], zmax_abs.shape[1]), dtype=np.uint8)

    z_idx = np.arange(max_abs + 1, dtype=np.int32)[:, None, None]

    xyz_solid01 = (
        (z_idx >= zmin_abs[None, :, :])
        & (z_idx <= zmax_abs[None, :, :])
    ).astype(np.uint8)

    return xyz_solid01


def trim_xyz_empty_border(xyz_solid01, x_origin, y_origin, z_origin_idx):
    """
    裁切 xyz_solid01 外圍完全空白區域。
    """

    volume = np.asarray(xyz_solid01, dtype=np.uint8)

    if volume.ndim != 3:
        raise ValueError(f"xyz_solid01 必須是 3D，目前 shape={volume.shape}")

    mask = volume > 0

    if not np.any(mask):
        return volume, int(x_origin), int(y_origin), int(z_origin_idx)

    z_any = np.any(mask, axis=(1, 2))
    y_any = np.any(mask, axis=(0, 2))
    x_any = np.any(mask, axis=(0, 1))

    z0 = int(np.where(z_any)[0][0])
    z1 = int(np.where(z_any)[0][-1]) + 1

    y0 = int(np.where(y_any)[0][0])
    y1 = int(np.where(y_any)[0][-1]) + 1

    x0 = int(np.where(x_any)[0][0])
    x1 = int(np.where(x_any)[0][-1]) + 1

    trimmed = volume[z0:z1, y0:y1, x0:x1]

    return (
        trimmed,
        int(x_origin) + x0,
        int(y_origin) + y0,
        int(z_origin_idx) + z0,
    )


def downsample_xyz_for_display(xyz_solid01, max_voxels=8_000_000):
    """
    3D 體素降採樣，避免資料太大導致 Dash 卡住。
    """

    volume = np.asarray(xyz_solid01, dtype=np.uint8)
    total_voxels = int(volume.size)

    if total_voxels <= int(max_voxels):
        return volume, (1, 1, 1)

    stride = int(np.ceil((total_voxels / float(max_voxels)) ** (1.0 / 3.0)))
    stride = max(1, stride)

    nz, ny, nx = volume.shape

    pad_z = (-nz) % stride
    pad_y = (-ny) % stride
    pad_x = (-nx) % stride

    if pad_z or pad_y or pad_x:
        volume = np.pad(
            volume,
            ((0, pad_z), (0, pad_y), (0, pad_x)),
            mode="constant",
            constant_values=0,
        )

    pz, py, px = volume.shape

    down = volume.reshape(
        pz // stride, stride,
        py // stride, stride,
        px // stride, stride,
    ).max(axis=(1, 3, 5)).astype(np.uint8, copy=False)

    return down, (stride, stride, stride)


def add_empty_halo(xyz_solid01, x_origin, y_origin, z_origin_idx, stride_xyz, halo_voxels=1):
    """
    在體素外圍補一圈空白，讓 marching cubes 能完整抓到外殼。
    """

    halo = max(0, int(halo_voxels))
    volume = np.asarray(xyz_solid01, dtype=np.uint8)

    if halo <= 0:
        return volume, int(x_origin), int(y_origin), int(z_origin_idx)

    padded = np.pad(
        volume,
        ((halo, halo), (halo, halo), (halo, halo)),
        mode="constant",
        constant_values=0,
    )

    stride_z, stride_y, stride_x = [int(v) for v in stride_xyz]

    return (
        padded,
        int(x_origin) - halo * stride_x,
        int(y_origin) - halo * stride_y,
        int(z_origin_idx) - halo * stride_z,
    )


# =========================================================
# 10. 讀取 NPZ
# =========================================================
def load_npz_3d_payload(npz_path: Path):
    """
    支援三種 NPZ 格式：

    A. X / Y / Z
       通常是 STL 切割後的 surface npz

    B. xyz_solid01
       體素資料，會轉成 Mesh3d

    C. cumulative_top_z_map / cumulative_height_map
       高度圖資料，會轉成 Surface
    """

    npz_path = Path(npz_path)
    arr = np.load(npz_path)

    # =========================================================
    # 格式 A：STL 切割後 NPZ，X/Y/Z
    # =========================================================
    if "X" in arr and "Y" in arr and "Z" in arr:
        X = np.asarray(arr["X"], dtype=np.float32)
        Y = np.asarray(arr["Y"], dtype=np.float32)
        Z = np.asarray(arr["Z"], dtype=np.float32)

        if X.shape != Y.shape or X.shape != Z.shape:
            raise ValueError(
                f"X/Y/Z shape 不一致：X={X.shape}, Y={Y.shape}, Z={Z.shape}"
            )

        Z_ds, stride = downsample_2d(Z, MAX_SURFACE_POINTS)
        X_ds = X[::stride, ::stride]
        Y_ds = Y[::stride, ::stride]

        return {
            "kind": "surface",
            "format": "X_Y_Z_from_STL_cut",
            "npz_path": str(npz_path),
            "x": X_ds[0, :],
            "y": Y_ds[:, 0],
            "z": Z_ds * float(Z_EXAGGERATION),
            "stride": int(stride),
            "shape_original": tuple(int(v) for v in Z.shape),
            "shape_display": tuple(int(v) for v in Z_ds.shape),
            "pixel_size_um": 1.0,
            "pixel_size_mm": 0.001,
            "valid_count": int(np.count_nonzero(np.isfinite(Z))),
            "x_origin": 0,
            "y_origin": 0,
            "z_exaggeration": float(Z_EXAGGERATION),
        }

    x_origin = int(arr["x_origin"]) if "x_origin" in arr else 0
    y_origin = int(arr["y_origin"]) if "y_origin" in arr else 0
    z_start = int(arr["z_start"]) if "z_start" in arr else 0

    pixel_size_um = float(arr["pixel_size_um"]) if "pixel_size_um" in arr else 1.0
    pixel_size_mm = pixel_size_um / 1000.0

    # =========================================================
    # 格式 B：xyz_solid01 體素
    # =========================================================
    if "xyz_solid01" in arr:
        xyz_raw = np.asarray(arr["xyz_solid01"], dtype=np.uint8)

        if xyz_raw.ndim != 3:
            raise ValueError(f"xyz_solid01 必須是 3D，但目前 shape={xyz_raw.shape}")

        z_idx = np.arange(xyz_raw.shape[0], dtype=np.int32)[:, None, None]
        zmax_abs = np.where(xyz_raw > 0, z_idx, -1).max(axis=0).astype(np.int32)

        if "zmin_surface_idx" in arr:
            zmin_abs = np.asarray(arr["zmin_surface_idx"], dtype=np.int32)
        else:
            zmin_abs = None

        if FILL_INTERVAL_SOLID:
            xyz_solid01 = build_interval_filled_xyz(zmax_abs, zmin_abs=zmin_abs)
            used_interval_fill = True
        else:
            xyz_solid01 = xyz_raw
            used_interval_fill = False

        original_shape = tuple(int(v) for v in xyz_solid01.shape)
        occupied_voxels = int(np.count_nonzero(xyz_solid01))

        if TRIM_3D_EMPTY_BORDER:
            xyz_solid01, x_origin, y_origin, z_start = trim_xyz_empty_border(
                xyz_solid01,
                x_origin=x_origin,
                y_origin=y_origin,
                z_origin_idx=z_start,
            )

        xyz_display, stride_xyz = downsample_xyz_for_display(
            xyz_solid01,
            max_voxels=MAX_DISPLAY_VOXELS,
        )

        xyz_display, x_origin, y_origin, z_start = add_empty_halo(
            xyz_display,
            x_origin=x_origin,
            y_origin=y_origin,
            z_origin_idx=z_start,
            stride_xyz=stride_xyz,
            halo_voxels=1,
        )

        return {
            "kind": "mesh",
            "format": "xyz_solid01",
            "npz_path": str(npz_path),
            "xyz": xyz_display,
            "x_origin": int(x_origin),
            "y_origin": int(y_origin),
            "z_start": int(z_start),
            "pixel_size_um": float(pixel_size_um),
            "pixel_size_mm": float(pixel_size_mm),
            "stride_xyz": tuple(int(v) for v in stride_xyz),
            "shape_original": original_shape,
            "shape_display": tuple(int(v) for v in xyz_display.shape),
            "occupied_voxels": occupied_voxels,
            "valid_count": occupied_voxels,
            "used_interval_fill": used_interval_fill,
            "z_exaggeration": float(Z_EXAGGERATION),
        }

    # =========================================================
    # 格式 C：cumulative height map
    # =========================================================
    valid_mask = np.asarray(arr["valid_mask"], dtype=bool) if "valid_mask" in arr else None

    if "cumulative_top_z_map" in arr:
        z_map = np.asarray(arr["cumulative_top_z_map"], dtype=np.float32)
        fmt = "cumulative_top_z_map"
    elif "cumulative_height_map" in arr:
        z_map = np.asarray(arr["cumulative_height_map"], dtype=np.float32)
        fmt = "cumulative_height_map"
    else:
        raise KeyError(
            "NPZ 格式不支援，找不到 X/Y/Z、xyz_solid01、"
            "cumulative_top_z_map 或 cumulative_height_map。"
            f"目前 keys = {list(arr.keys())}"
        )

    z_map = np.asarray(z_map, dtype=np.float32)

    if valid_mask is not None:
        if valid_mask.shape != z_map.shape:
            raise ValueError(
                f"valid_mask shape={valid_mask.shape} 與 z_map shape={z_map.shape} 不一致"
            )
        z_map = np.where(valid_mask & np.isfinite(z_map), z_map, np.nan)
    else:
        z_map = np.where(np.isfinite(z_map), z_map, np.nan)

    z_map_ds, stride = downsample_2d(z_map, MAX_SURFACE_POINTS)

    ny, nx = z_map_ds.shape

    x = (np.arange(nx, dtype=np.float32) * stride + x_origin) * pixel_size_mm
    y = (np.arange(ny, dtype=np.float32) * stride + y_origin) * pixel_size_mm
    z = z_map_ds * pixel_size_mm * float(Z_EXAGGERATION)

    return {
        "kind": "surface",
        "format": fmt,
        "npz_path": str(npz_path),
        "x": x,
        "y": y,
        "z": z,
        "stride": int(stride),
        "shape_original": tuple(int(v) for v in z_map.shape),
        "shape_display": tuple(int(v) for v in z_map_ds.shape),
        "pixel_size_um": float(pixel_size_um),
        "pixel_size_mm": float(pixel_size_mm),
        "valid_count": int(np.count_nonzero(np.isfinite(z_map))),
        "x_origin": int(x_origin),
        "y_origin": int(y_origin),
        "z_exaggeration": float(Z_EXAGGERATION),
    }


# =========================================================
# 11. 高度差顏色計算
# =========================================================
def get_height_color_um(z_mm, mean_source_z_mm=None):
    """
    顏色計算方式：

    1. 還原真實 Z 高度
    2. 用整體平均高度作為 0 基準
    3. 計算 |Z - Mean|
    4. 轉成 um
    5. 限制 colorbar 為 0~120 um
    """

    z_mm = np.asarray(z_mm, dtype=np.float32)

    # 還原真實高度，因為顯示用 z 有乘上 Z_EXAGGERATION
    real_z_mm = z_mm / float(Z_EXAGGERATION)

    valid = np.isfinite(real_z_mm)
    if not np.any(valid):
        return np.zeros_like(real_z_mm, dtype=np.float32)

    # 如果有指定平均高度來源，例如右側只用上表面算平均
    if mean_source_z_mm is not None:
        mean_source_z_mm = np.asarray(mean_source_z_mm, dtype=np.float32)
        mean_source_real_z_mm = mean_source_z_mm / float(Z_EXAGGERATION)

        source_valid = np.isfinite(mean_source_real_z_mm)

        if np.any(source_valid):
            z_mean_mm = np.nanmean(mean_source_real_z_mm[source_valid])
        else:
            z_mean_mm = np.nanmean(real_z_mm[valid])
    else:
        z_mean_mm = np.nanmean(real_z_mm[valid])

    # 推回平均高度 = 0，取絕對高度差
    height_um = np.abs(real_z_mm - z_mean_mm) * 1000.0

    # colorbar 固定 0~120 um
    height_um = np.clip(
        height_um,
        HEIGHT_COLOR_MIN_UM,
        HEIGHT_COLOR_MAX_UM,
    )

    return height_um.astype(np.float32)


def get_top_surface_z_mm_from_xyz_payload(data):
    """
    從 xyz_solid01 體素資料中，只抓每個 X-Y 位置的最高 Z，
    用這些上表面高度來計算整體平均高度。
    """

    xyz = np.asarray(data["xyz"], dtype=np.uint8)

    if xyz.ndim != 3:
        raise ValueError(f"xyz 必須是 3D，目前 shape={xyz.shape}")

    if not np.any(xyz > 0):
        return None

    stride_z, stride_y, stride_x = [int(v) for v in data["stride_xyz"]]
    pixel_size_mm = float(data["pixel_size_mm"])
    z_start = int(data["z_start"])

    z_idx = np.arange(xyz.shape[0], dtype=np.float32)[:, None, None]

    # 每個 Y-X 位置只取最高 Z
    top_z_idx = np.where(xyz > 0, z_idx, np.nan)
    top_z_idx = np.nanmax(top_z_idx, axis=0)

    # 轉成顯示用 Z mm，包含 Z 軸倍率
    top_z_mm = (
        top_z_idx * stride_z + z_start
    ) * pixel_size_mm * float(Z_EXAGGERATION)

    top_z_mm = np.where(np.isfinite(top_z_mm), top_z_mm, np.nan)

    return top_z_mm.astype(np.float32)


def make_colorbar_config():
    return dict(
        title=dict(
            text="|Height - Mean| (um)",
            side="right",
        ),
        thickness=18,
        len=0.75,
        tickmode="array",
        tickvals=[0, 20, 40, 60, 80, 100, 120],
        ticktext=["0", "20", "40", "60", "80", "100", "120"],
    )


# =========================================================
# 11-1. 上表面高低落差統計
# =========================================================
def extract_top_surface_um_for_stats(data):
    """
    取得真正的上表面高度，單位 um。

    注意：
    - data["z"] 或 top_surface_z_mm 都是顯示用高度，已乘上 Z_EXAGGERATION
    - 所以統計前要除回 Z_EXAGGERATION
    """

    if data["kind"] == "mesh":
        top_z_display_mm = get_top_surface_z_mm_from_xyz_payload(data)

        if top_z_display_mm is None:
            return None

        top_z_real_mm = top_z_display_mm / float(Z_EXAGGERATION)
        top_z_um = top_z_real_mm * 1000.0

        return top_z_um.astype(np.float32)

    else:
        z_display_mm = np.asarray(data["z"], dtype=np.float32)
        z_real_mm = z_display_mm / float(Z_EXAGGERATION)
        z_um = z_real_mm * 1000.0

        return z_um.astype(np.float32)


def calc_one_region_stats(values_um):
    """
    計算單一區域的高度統計。
    使用 P95 - P5 當主要高低落差，避免極端雜訊影響。
    """

    values_um = np.asarray(values_um, dtype=np.float32)
    values_um = values_um[np.isfinite(values_um)]

    if values_um.size == 0:
        return {
            "count": 0,
            "mean": np.nan,
            "std": np.nan,
            "min": np.nan,
            "max": np.nan,
            "range": np.nan,
            "p5": np.nan,
            "p50": np.nan,
            "p95": np.nan,
            "robust_drop": np.nan,
        }

    p5 = float(np.percentile(values_um, 5))
    p50 = float(np.percentile(values_um, 50))
    p95 = float(np.percentile(values_um, 95))

    return {
        "count": int(values_um.size),
        "mean": float(np.mean(values_um)),
        "std": float(np.std(values_um)),
        "min": float(np.min(values_um)),
        "max": float(np.max(values_um)),
        "range": float(np.max(values_um) - np.min(values_um)),
        "p5": p5,
        "p50": p50,
        "p95": p95,
        "robust_drop": float(p95 - p5),
    }


def calc_surface_region_stats(z_um):
    """
    將上表面分成：
    - overall：整體
    - edge：外圍邊緣
    - center：中心
    - left / right：左右半邊
    - front / back：前後半邊

    回傳每區的平均、高低落差、P95-P5 等。
    """

    z_um = np.asarray(z_um, dtype=np.float32)

    if z_um.ndim != 2:
        raise ValueError(f"上表面高度圖必須是 2D，目前 shape={z_um.shape}")

    h, w = z_um.shape
    valid = np.isfinite(z_um)

    if not np.any(valid):
        raise ValueError("上表面沒有有效高度資料")

    yy, xx = np.indices((h, w))

    edge_x = max(1, int(w * EDGE_RATIO))
    edge_y = max(1, int(h * EDGE_RATIO))

    edge_mask = (
        (xx < edge_x)
        | (xx >= w - edge_x)
        | (yy < edge_y)
        | (yy >= h - edge_y)
    )

    center_w = max(1, int(w * CENTER_RATIO))
    center_h = max(1, int(h * CENTER_RATIO))

    cx0 = max(0, (w - center_w) // 2)
    cx1 = min(w, cx0 + center_w)

    cy0 = max(0, (h - center_h) // 2)
    cy1 = min(h, cy0 + center_h)

    center_mask = np.zeros_like(valid, dtype=bool)
    center_mask[cy0:cy1, cx0:cx1] = True

    left_mask = xx < (w // 2)
    right_mask = xx >= (w // 2)

    front_mask = yy < (h // 2)
    back_mask = yy >= (h // 2)

    masks = {
        "overall": valid,
        "edge": valid & edge_mask,
        "center": valid & center_mask,
        "left": valid & left_mask,
        "right": valid & right_mask,
        "front": valid & front_mask,
        "back": valid & back_mask,
    }

    stats = {}

    for name, mask in masks.items():
        stats[name] = calc_one_region_stats(z_um[mask])

    return stats


def judge_surface_height_problem(stats):
    """
    根據分區統計判斷：
    - 邊緣是否落差大
    - 中心是否落差大
    - 左右是否不平衡
    - 前後是否不平衡
    並給出可能參數調整建議。
    """

    edge = stats["edge"]
    center = stats["center"]
    left = stats["left"]
    right = stats["right"]
    front = stats["front"]
    back = stats["back"]

    edge_drop = edge["robust_drop"]
    center_drop = center["robust_drop"]

    edge_mean = edge["mean"]
    center_mean = center["mean"]

    left_mean = left["mean"]
    right_mean = right["mean"]

    front_mean = front["mean"]
    back_mean = back["mean"]

    lr_diff = right_mean - left_mean
    fb_diff = back_mean - front_mean
    edge_center_diff = edge_mean - center_mean

    region_drops = {
        "邊緣 Edge": edge_drop,
        "中心 Center": center_drop,
        "左半 Left": left["robust_drop"],
        "右半 Right": right["robust_drop"],
        "前側 Front": front["robust_drop"],
        "後側 Back": back["robust_drop"],
    }

    worst_region = max(
        region_drops,
        key=lambda k: -np.inf if not np.isfinite(region_drops[k]) else region_drops[k],
    )

    worst_drop = region_drops[worst_region]

    messages = []

    messages.append(
        f"最大高低落差區域：{worst_region}，P95-P5 = {worst_drop:.2f} um"
    )

    # 邊緣 vs 中心
    if np.isfinite(edge_drop) and np.isfinite(center_drop):
        if edge_drop > center_drop * 1.2:
            messages.append("判斷：邊緣區域的高低落差比中心更明顯。")
        elif center_drop > edge_drop * 1.2:
            messages.append("判斷：中心區域的高低落差比邊緣更明顯。")
        else:
            messages.append("判斷：邊緣與中心的落差接近，沒有明顯集中在單一區域。")

    # 邊緣平均高度與中心平均高度
    if np.isfinite(edge_center_diff):
        if edge_center_diff < -FAIL_DIFF_UM:
            messages.append(
                "邊緣平均高度明顯低於中心，可能有邊緣熔合不足、邊界塌陷或輪廓能量不足。"
            )
            messages.append(
                "建議：可提高 contour power、降低 contour speed、增加 contour/hatch overlap，或增加邊界補償。"
            )

        elif edge_center_diff < -WARNING_DIFF_UM:
            messages.append(
                "邊緣平均高度略低於中心，邊界可能開始偏低。"
            )
            messages.append(
                "建議：小幅提高輪廓道能量，或減少掃描間距 hatch spacing。"
            )

        elif edge_center_diff > FAIL_DIFF_UM:
            messages.append(
                "邊緣平均高度明顯高於中心，可能有邊緣堆積、重熔過強或 contour 能量過高。"
            )
            messages.append(
                "建議：可降低 contour power、提高 contour speed，或減少 contour/hatch overlap。"
            )

        elif edge_center_diff > WARNING_DIFF_UM:
            messages.append(
                "邊緣平均高度略高於中心，邊界可能有輕微堆積。"
            )
            messages.append(
                "建議：小幅降低輪廓道能量，或檢查邊界掃描策略。"
            )

    # 中心問題
    if np.isfinite(center_drop) and np.isfinite(edge_drop):
        if center_drop > edge_drop * 1.2:
            if center_mean < edge_mean:
                messages.append(
                    "中心區域偏低且落差較大，可能是 hatch 區域能量不足或掃描間距過大。"
                )
                messages.append(
                    "建議：提高 hatch power、降低 hatch speed、縮小 hatch spacing。"
                )
            elif center_mean > edge_mean:
                messages.append(
                    "中心區域偏高且落差較大，可能是 hatch 區域熱累積過強。"
                )
                messages.append(
                    "建議：降低 hatch power、提高 hatch speed、增加 hatch spacing，或改變掃描方向降低熱累積。"
                )

    # 左右不平衡
    if np.isfinite(lr_diff):
        if abs(lr_diff) > FAIL_DIFF_UM:
            if lr_diff > 0:
                messages.append(
                    "右側平均高度明顯高於左側，可能有平台水平、刮刀/鋪粉、氣流方向或掃描方向造成的不均。"
                )
            else:
                messages.append(
                    "左側平均高度明顯高於右側，可能有平台水平、刮刀/鋪粉、氣流方向或掃描方向造成的不均。"
                )
            messages.append(
                "建議：檢查基板 leveling、recoater 平整度、粉層厚度、氣流方向，以及是否需要旋轉掃描方向。"
            )

        elif abs(lr_diff) > WARNING_DIFF_UM:
            messages.append(
                "左右平均高度有輕微差異，建議檢查鋪粉均勻性與掃描方向。"
            )

    # 前後不平衡
    if np.isfinite(fb_diff):
        if abs(fb_diff) > FAIL_DIFF_UM:
            if fb_diff > 0:
                messages.append(
                    "後側平均高度明顯高於前側，可能與鋪粉方向、氣流或掃描順序有關。"
                )
            else:
                messages.append(
                    "前側平均高度明顯高於後側，可能與鋪粉方向、氣流或掃描順序有關。"
                )
            messages.append(
                "建議：檢查 recoater movement direction、粉末供給量、氣流方向與掃描路徑排序。"
            )

        elif abs(fb_diff) > WARNING_DIFF_UM:
            messages.append(
                "前後平均高度有輕微差異，建議檢查鋪粉方向與掃描順序。"
            )

    if len(messages) <= 1:
        messages.append(
            "整體高度分布相對均勻，目前沒有明顯邊緣、中心或左右不平衡問題。"
        )

    return messages


def make_surface_height_report(data, title="上表面高低落差分析"):
    """
    產生 Dash 顯示用的簡化版高度落差分析報告。

    顯示重點：
    1. 哪一區落差最大
    2. 邊緣 vs 中心誰比較不平
    3. 左右 / 前後是否有明顯高度差
    4. 直接給參數調整建議
    """

    try:
        z_um = extract_top_surface_um_for_stats(data)

        if z_um is None:
            return [
                html.Div(
                    f"{title}：無法取得上表面高度資料",
                    className="text-warning small",
                )
            ]

        stats = calc_surface_region_stats(z_um)

        edge = stats["edge"]
        center = stats["center"]
        left = stats["left"]
        right = stats["right"]
        front = stats["front"]
        back = stats["back"]
        overall = stats["overall"]

        region_drops = {
            "邊緣 Edge": edge["robust_drop"],
            "中心 Center": center["robust_drop"],
            "左半 Left": left["robust_drop"],
            "右半 Right": right["robust_drop"],
            "前側 Front": front["robust_drop"],
            "後側 Back": back["robust_drop"],
        }

        worst_region = max(
            region_drops,
            key=lambda k: -np.inf if not np.isfinite(region_drops[k]) else region_drops[k],
        )
        worst_drop = region_drops[worst_region]

        edge_drop = edge["robust_drop"]
        center_drop = center["robust_drop"]
        edge_mean = edge["mean"]
        center_mean = center["mean"]

        lr_diff = right["mean"] - left["mean"]
        fb_diff = back["mean"] - front["mean"]
        edge_center_diff = edge_mean - center_mean

        def fmt(v):
            if v is None or not np.isfinite(v):
                return "N/A"
            return f"{v:.2f}"

        # =====================================================
        # 1. 快速判斷：邊緣 / 中心
        # =====================================================
        if np.isfinite(edge_drop) and np.isfinite(center_drop):
            if edge_drop > center_drop * 1.2:
                main_judge = "邊緣落差最大，外圍比中心更不平。"
            elif center_drop > edge_drop * 1.2:
                main_judge = "中心落差最大，中間區域比邊緣更不平。"
            else:
                main_judge = "邊緣與中心落差接近，整體不平程度較平均。"
        else:
            main_judge = "資料不足，無法判斷邊緣與中心差異。"

        # =====================================================
        # 2. 高度偏高 / 偏低判斷
        # =====================================================
        if np.isfinite(edge_center_diff):
            if edge_center_diff > FAIL_DIFF_UM:
                height_judge = "邊緣平均高度明顯高於中心，可能有邊緣堆積或 contour 能量過高。"
                advice = "降低 contour power、提高 contour speed，或減少 contour/hatch overlap。"
                badge_color = "danger"
            elif edge_center_diff > WARNING_DIFF_UM:
                height_judge = "邊緣平均高度略高於中心，邊界可能有輕微堆積。"
                advice = "小幅降低輪廓道能量，並檢查邊界掃描策略。"
                badge_color = "warning"
            elif edge_center_diff < -FAIL_DIFF_UM:
                height_judge = "邊緣平均高度明顯低於中心，可能有邊緣熔合不足或邊界塌陷。"
                advice = "提高 contour power、降低 contour speed，或增加 contour/hatch overlap。"
                badge_color = "danger"
            elif edge_center_diff < -WARNING_DIFF_UM:
                height_judge = "邊緣平均高度略低於中心，邊界可能有輕微下陷。"
                advice = "小幅提高輪廓道能量，或減少 hatch spacing。"
                badge_color = "warning"
            else:
                height_judge = "邊緣與中心平均高度差不大。"
                advice = "目前不需大幅調整 contour 參數，可優先觀察整體均勻性。"
                badge_color = "success"
        else:
            height_judge = "無法判斷邊緣與中心平均高度差。"
            advice = "確認 NPZ 上表面資料是否完整。"
            badge_color = "warning"

        # =====================================================
        # 3. 左右 / 前後判斷
        # =====================================================
        side_notes = []

        if np.isfinite(lr_diff):
            if abs(lr_diff) > FAIL_DIFF_UM:
                if lr_diff > 0:
                    side_notes.append(f"右側比左側平均高 {fmt(abs(lr_diff))} um，左右不平衡明顯")
                else:
                    side_notes.append(f"左側比右側平均高 {fmt(abs(lr_diff))} um，左右不平衡明顯")
            elif abs(lr_diff) > WARNING_DIFF_UM:
                side_notes.append(f"左右平均高度差 {fmt(abs(lr_diff))} um，有輕微不平衡")
            else:
                side_notes.append(f"左右平均高度差 {fmt(abs(lr_diff))} um，左右差異不大")

        if np.isfinite(fb_diff):
            if abs(fb_diff) > FAIL_DIFF_UM:
                if fb_diff > 0:
                    side_notes.append(f"後側比前側平均高 {fmt(abs(fb_diff))} um，前後不平衡明顯")
                else:
                    side_notes.append(f"前側比後側平均高 {fmt(abs(fb_diff))} um，前後不平衡明顯")
            elif abs(fb_diff) > WARNING_DIFF_UM:
                side_notes.append(f"前後平均高度差 {fmt(abs(fb_diff))} um，有輕微不平衡")
            else:
                side_notes.append(f"前後平均高度差 {fmt(abs(fb_diff))} um，前後差異不大")

        # =====================================================
        # 4. 簡化卡片輸出
        # =====================================================
        return [
            html.Hr(className="my-2"),
            dbc.Card(
                dbc.CardBody(
                    [
                        html.Div(
                            [
                                html.Span(title, className="fw-bold me-2"),
                                dbc.Badge(
                                    "快速判斷",
                                    color=badge_color,
                                    className="ms-1",
                                ),
                            ],
                            className="text-success small mb-2",
                        ),

                        html.Div(
                            [
                                html.Span("落差最大位置：", className="fw-bold text-warning"),
                                html.Span(f"{worst_region}，P95-P5 = {fmt(worst_drop)} um"),
                            ],
                            className="small mb-1",
                        ),

                        html.Div(
                            [
                                html.Span("整體落差：", className="fw-bold text-warning"),
                                html.Span(
                                    f"P95-P5 = {fmt(overall['robust_drop'])} um，"
                                    f"Max-Min = {fmt(overall['range'])} um，"
                                    f"Std = {fmt(overall['std'])} um"
                                ),
                            ],
                            className="small mb-1",
                        ),

                        html.Div(
                            [
                                html.Span("邊緣 vs 中心：", className="fw-bold text-warning"),
                                html.Span(
                                    f"邊緣 {fmt(edge_drop)} um，中心 {fmt(center_drop)} um。{main_judge}"
                                ),
                            ],
                            className="small mb-1",
                        ),

                        html.Div(
                            [
                                html.Span("高度判斷：", className="fw-bold text-warning"),
                                html.Span(height_judge),
                            ],
                            className="small mb-1",
                        ),

                        html.Div(
                            [
                                html.Span("方向差異：", className="fw-bold text-warning"),
                                html.Span("；".join(side_notes) + "。"),
                            ],
                            className="small mb-1",
                        ),

                        html.Div(
                            [
                                html.Span("參數建議：", className="fw-bold text-warning"),
                                html.Span(advice),
                            ],
                            className="small",
                        ),
                    ]
                ),
                color="dark",
                outline=True,
                className="mb-2",
            ),
        ]

    except Exception as e:
        return [
            html.Div(
                f"{title} 計算失敗：{e}",
                className="text-warning small",
            )
        ]


# =========================================================
# 12. 建立 Mesh3d
# =========================================================
def make_mesh3d_from_xyz_payload(data, show_colorbar=True):
    """
    xyz_solid01 → marching cubes → Mesh3d

    右側 Latest NPZ 如果是 xyz_solid01 會走這裡。
    顏色平均值只用上表面高度計算，不用側邊/底部。
    """

    if not SKIMAGE_AVAILABLE:
        raise RuntimeError(
            f"尚未安裝 scikit-image，無法建立 Mesh3d。錯誤：{SKIMAGE_IMPORT_ERROR}"
        )

    volume = np.asarray(data["xyz"], dtype=np.float32)

    if volume.ndim != 3:
        raise ValueError(f"xyz 必須是 3D，目前 shape={volume.shape}")

    if not np.any(volume > 0):
        raise ValueError("xyz_solid01 沒有任何實體體素，無法建立 Mesh3d")

    stride_z, stride_y, stride_x = [int(v) for v in data["stride_xyz"]]
    pixel_size_mm = float(data["pixel_size_mm"])

    spacing = (
        pixel_size_mm * float(stride_z) * float(Z_EXAGGERATION),
        pixel_size_mm * float(stride_y),
        pixel_size_mm * float(stride_x),
    )

    verts, faces, normals, values = measure.marching_cubes(
        volume,
        level=0.5,
        spacing=spacing,
    )

    if faces.shape[0] > MAX_MESH_FACES:
        step = int(np.ceil(faces.shape[0] / float(MAX_MESH_FACES)))
        faces = faces[::step]

    z_mm = verts[:, 0] + float(data["z_start"]) * pixel_size_mm * float(Z_EXAGGERATION)
    y_mm = verts[:, 1] + float(data["y_origin"]) * pixel_size_mm
    x_mm = verts[:, 2] + float(data["x_origin"]) * pixel_size_mm

    if USE_HEIGHT_TEXTURE_COLOR:
        top_surface_z_mm = get_top_surface_z_mm_from_xyz_payload(data)

        height_um = get_height_color_um(
            z_mm,
            mean_source_z_mm=top_surface_z_mm,
        )

        return go.Mesh3d(
            x=x_mm,
            y=y_mm,
            z=z_mm,
            i=faces[:, 0],
            j=faces[:, 1],
            k=faces[:, 2],
            intensity=height_um,
            colorscale=TEXTURE_COLORSCALE,
            cmin=HEIGHT_COLOR_MIN_UM,
            cmax=HEIGHT_COLOR_MAX_UM,
            showscale=show_colorbar,
            colorbar=make_colorbar_config(),
            opacity=1.0,
            flatshading=False,
            lighting=dict(
                ambient=0.18,
                diffuse=0.80,
                specular=0.18,
                roughness=0.45,
                fresnel=0.12,
            ),
            lightposition=dict(x=100, y=200, z=300),
            hovertemplate=(
                "X: %{x:.4f} mm<br>"
                "Y: %{y:.4f} mm<br>"
                "Z: %{z:.4f} mm<br>"
                "|Height-Mean|: %{intensity:.2f} um"
                "<extra></extra>"
            ),
            name="",
        )

    return go.Mesh3d(
        x=x_mm,
        y=y_mm,
        z=z_mm,
        i=faces[:, 0],
        j=faces[:, 1],
        k=faces[:, 2],
        color=SURFACE_GRAY_COLOR,
        opacity=1.0,
        flatshading=False,
        hoverinfo="skip",
        name="",
    )


# =========================================================
# 13. 建立 Surface
# =========================================================
def make_surface_trace_from_payload(data, show_colorbar=True):
    """
    X/Y/Z 或 cumulative height map → Surface

    Surface 本身就是上表面資料，
    所以直接用自己的 Z 算整體平均高度。
    """

    z = np.asarray(data["z"], dtype=np.float32)

    height_um = get_height_color_um(z)

    return go.Surface(
        x=data["x"],
        y=data["y"],
        z=z,
        surfacecolor=height_um,
        colorscale=TEXTURE_COLORSCALE,
        cmin=HEIGHT_COLOR_MIN_UM,
        cmax=HEIGHT_COLOR_MAX_UM,
        showscale=show_colorbar,
        colorbar=make_colorbar_config(),
        hovertemplate=(
            "X: %{x:.4f} mm<br>"
            "Y: %{y:.4f} mm<br>"
            "Z: %{z:.4f} mm<br>"
            "|Height-Mean|: %{surfacecolor:.2f} um"
            "<extra></extra>"
        ),
        name="",
    )


# =========================================================
# 14. 建立單張 NPZ 3D Card
# =========================================================
def make_npz_3d_card(npz_path: Optional[Path], graph_id: str, show_colorbar=True):
    frame_style = {
        "width": "100%",
        "height": GRAPH_STYLE["height"],
        "border": "1px solid #444",
        "borderRadius": "8px",
        "backgroundColor": "#111",
        "overflow": "hidden",
        "minWidth": "0",
    }

    if not npz_path or not npz_path.exists():
        return dbc.Card(
            dbc.CardBody(
                html.Div(
                    f"目前找不到 NPZ 檔案：{npz_path}",
                    className="d-flex align-items-center justify-content-center text-warning small",
                    style=frame_style,
                ),
                style={"padding": "0"},
            ),
            className="shadow-sm h-100",
            style=CARD_FILL,
        )

    try:
        data = load_npz_3d_payload(npz_path)
        fig = go.Figure()

        # =====================================================
        # xyz_solid01 → Mesh3d
        # =====================================================
        if data["kind"] == "mesh" and PREFER_MESH3D_FOR_XYZ:
            try:
                fig.add_trace(
                    make_mesh3d_from_xyz_payload(
                        data,
                        show_colorbar=show_colorbar,
                    )
                )
            except Exception:
                # 如果 Mesh3d 失敗，就 fallback 成上表面 Surface
                xyz = np.asarray(data["xyz"], dtype=np.uint8)
                z_idx = np.arange(xyz.shape[0], dtype=np.float32)[:, None, None]
                z_map = np.where(xyz > 0, z_idx, np.nan).max(axis=0)

                z_map_ds, stride = downsample_2d(z_map, MAX_SURFACE_POINTS)

                ny, nx = z_map_ds.shape
                pixel_size_mm = float(data["pixel_size_mm"])

                x = (
                    np.arange(nx, dtype=np.float32) * stride * int(data["stride_xyz"][2])
                    + int(data["x_origin"])
                ) * pixel_size_mm

                y = (
                    np.arange(ny, dtype=np.float32) * stride * int(data["stride_xyz"][1])
                    + int(data["y_origin"])
                ) * pixel_size_mm

                z = (
                    z_map_ds * int(data["stride_xyz"][0])
                    + int(data["z_start"])
                ) * pixel_size_mm * float(Z_EXAGGERATION)

                fig.add_trace(
                    make_surface_trace_from_payload(
                        {
                            "x": x,
                            "y": y,
                            "z": z,
                        },
                        show_colorbar=show_colorbar,
                    )
                )

        # =====================================================
        # X/Y/Z 或 cumulative map → Surface
        # =====================================================
        else:
            fig.add_trace(
                make_surface_trace_from_payload(
                    data,
                    show_colorbar=show_colorbar,
                )
            )

        fig.update_layout(
            autosize=True,
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="#111",
            plot_bgcolor="#111",
            title=None,
            showlegend=False,
            scene=dict(
                bgcolor="#111",
                xaxis=dict(visible=False, showbackground=False),
                yaxis=dict(visible=False, showbackground=False),
                zaxis=dict(visible=False, showbackground=False),
                aspectmode="data",
                camera=dict(
                    eye=dict(x=1.45, y=1.45, z=1.0),
                    up=dict(x=0, y=0, z=1),
                ),
            ),
            uirevision="keep",
        )

        graph = dcc.Graph(
            id=graph_id,
            figure=fig,
            config={
                "responsive": True,
                "displaylogo": False,
                "scrollZoom": True,
                "doubleClick": "reset",
                "displayModeBar": False,
            },
            responsive=True,
            style=GRAPH_STYLE,
        )

        return dbc.Card(
            dbc.CardBody(graph, style={"padding": "0"}),
            className="shadow-sm h-100",
            style={"backgroundColor": "#111", **CARD_FILL},
        )

    except Exception as e:
        return dbc.Card(
            dbc.CardBody(
                html.Div(
                    f"NPZ 3D 讀取失敗：{e}",
                    className="d-flex align-items-center justify-content-center text-warning small",
                    style=frame_style,
                ),
                style={"padding": "0"},
            ),
            className="shadow-sm h-100",
            style=CARD_FILL,
        )


# =========================================================
# 15. Navbar / Sidebar
# =========================================================
def navlink(label: str, key: str, icon: str):
    return dbc.NavLink(
        [html.I(className=f"bi {icon} me-2"), label],
        href=APP_URLS[key],
        target="_self",
        external_link=True,
        active=(key == "step4"),
    )


navbar = dbc.Navbar(
    dbc.Container(
        html.Div(
            [
                dbc.Button(
                    html.I(className="bi bi-list"),
                    id="sidebar-toggle",
                    color="light",
                    className="me-2",
                ),
                html.Div(
                    [html.I(className="bi bi-cube")],
                    className="d-flex align-items-center",
                ),
            ],
            className="d-flex align-items-center",
        ),
        fluid=True,
    ),
    color="primary",
    dark=True,
    sticky="top",
)

sidebar = dbc.Collapse(
    html.Div(
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
            html.Div("© 2025", className="text-white-50 small mt-2"),
        ],
        className="bg-dark p-3 h-100",
    ),
    id="sidebar",
    is_open=True,
    className="position-fixed",
    style={
        "width": "240px",
        "top": "56px",
        "left": 0,
        "overflowY": "auto",
        "height": "100%",
    },
)


# =========================================================
# 16. 主畫面 Card
# =========================================================
right_card = dbc.Card(
    [
        dbc.CardHeader(
            [
                html.I(className="bi bi-boxes me-2"),
                "Surface_profile — NPZ 3D Viewer",
            ]
        ),
        dbc.CardBody(
            [
                dbc.Button(
                    [html.I(className="bi bi-play-fill me-1"), "Run"],
                    id="run-btn",
                    size="sm",
                    color="success",
                    className="mb-3",
                ),
                dbc.Button(
                    [html.I(className="bi bi-arrow-repeat me-1"), "Refresh"],
                    id="gif-refresh-btn",
                    size="sm",
                    color="secondary",
                    className="mb-3 ms-2",
                ),
                html.Div(id="run-status", className="small mb-1"),
                html.Div(id="run-timer", className="small text-success mb-2"),
                html.Div(id="image-index-label", className="text-muted my-2"),
                html.Div(id="gif-4-preview", style={"width": "100%", "minWidth": "0"}),
                html.Div(id="gif-4-meta", className="text-muted small mt-2"),
            ]
        ),
    ],
    className="shadow-sm h-100",
    style=CARD_FILL,
)

body = html.Div(
    [
        dbc.Row(
            [
                dbc.Col(
                    right_card,
                    xs=12,
                    lg=12,
                    className="d-flex",
                    style={"minWidth": "0"},
                ),
            ],
            className="g-3",
            style={"marginTop": "0"},
        ),
    ],
    style={"marginTop": "0", "paddingTop": "0"},
)

content = html.Div(
    id="page-content",
    children=[
        dcc.Markdown(
            """
<style>
#tab-content { margin-top: 0 !important; padding-top: 0 !important; }
#tab-content > *:first-child { margin-top: 0 !important; }
.js-plotly-plot, .plot-container, .svg-container {
    width: 100% !important;
    max-width: 100% !important;
}
</style>
            """.strip(),
            dangerously_allow_html=True,
        ),
        html.Div(
            id="tab-content",
            children=body,
            style={"marginTop": "0", "paddingTop": "0"},
        ),
        dcc.Interval(
            id="run-timer-interval",
            interval=500,
            n_intervals=0,
            disabled=True,
        ),
        dcc.Interval(
            id="gif-scan-interval",
            interval=2000,
            n_intervals=0,
            disabled=True,
        ),
    ],
    style=CONTENT_OPEN,
)

app.layout = html.Div(
    [
        navbar,
        sidebar,
        content,
        dcc.Store(id="sidebar-state", data=True),
    ]
)


# =========================================================
# 17. Sidebar callback
# =========================================================
@app.callback(
    [
        Output("sidebar", "is_open"),
        Output("page-content", "style"),
        Output("sidebar-state", "data"),
    ],
    Input("sidebar-toggle", "n_clicks"),
    State("sidebar", "is_open"),
    prevent_initial_call=False,
)
def toggle_sidebar(n, is_open):
    if n is None:
        return is_open, (CONTENT_OPEN if is_open else CONTENT_CLOSED), is_open

    new_state = not is_open
    return new_state, (CONTENT_OPEN if new_state else CONTENT_CLOSED), new_state


# =========================================================
# 18. Run callback
# =========================================================
@app.callback(
    [
        Output("run-status", "children"),
        Output("run-status", "className"),
        Output("run-timer-interval", "disabled"),
        Output("run-timer", "children"),
    ],
    Input("run-btn", "n_clicks"),
    prevent_initial_call=True,
)
def on_click_run(n_run):
    global current_proc, run_start_ts, current_log_path, log_fh

    if not n_run:
        raise PreventUpdate

    if current_proc is not None and current_proc.poll() is None:
        return (
            f"已在執行中（PID {current_proc.pid}）",
            "text-warning small mb-1",
            False,
            f"⏱ {fmt_elapsed(time.time() - (run_start_ts or time.time()))}",
        )

    if not RUN_SCRIPT_PATH.exists():
        return (
            f"⚠️ 找不到腳本：{RUN_SCRIPT_PATH}",
            "text-danger small mb-1",
            True,
            "",
        )

    ts = now_ts()
    log_path = LOG_DIR / f"run_4_{ts}.txt"

    try:
        log_path.write_text(
            f"# Command: {sys.executable} {RUN_SCRIPT_PATH}\n"
            f"# Start: {datetime.now().isoformat()}\n\n",
            encoding="utf-8",
        )

        log_fh = open(log_path, "a", encoding="utf-8", buffering=1)

        current_proc = subprocess.Popen(
            [sys.executable, str(RUN_SCRIPT_PATH)],
            cwd=str(RUN_SCRIPT_PATH.parent),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )

        run_start_ts = time.time()
        current_log_path = log_path

        return (
            f"✅ 已啟動（Surface_profile，PID {current_proc.pid}）",
            "text-success small mb-1",
            False,
            "⏱ 00:00:00",
        )

    except Exception as e:
        current_proc = None
        run_start_ts = None
        current_log_path = None

        try:
            if log_fh:
                log_fh.close()
        except Exception:
            pass

        log_fh = None

        return (
            f"⚠️ 執行失敗：{e}",
            "text-danger small mb-1",
            True,
            "",
        )


# =========================================================
# 19. Timer callback
# =========================================================
@app.callback(
    [
        Output("run-timer", "children", allow_duplicate=True),
        Output("run-status", "children", allow_duplicate=True),
        Output("run-status", "className", allow_duplicate=True),
        Output("run-timer-interval", "disabled", allow_duplicate=True),
    ],
    Input("run-timer-interval", "n_intervals"),
    prevent_initial_call=True,
)
def on_tick_update_timer(_n):
    global current_proc, run_start_ts, log_fh

    if current_proc is None or run_start_ts is None:
        return "", no_update, no_update, True

    if current_proc.poll() is None:
        return (
            f"⏱ {fmt_elapsed(time.time() - run_start_ts)}",
            no_update,
            no_update,
            False,
        )

    code = current_proc.returncode
    elapsed = fmt_elapsed(time.time() - run_start_ts)
    pid = current_proc.pid

    current_proc = None
    run_start_ts = None

    try:
        if log_fh:
            log_fh.close()
    except Exception:
        pass

    log_fh = None

    return (
        f"⏱ {elapsed}",
        f"🏁 執行完成（PID {pid}，退出碼 {code}）",
        "text-success small mb-1" if code == 0 else "text-danger small mb-1",
        True,
    )


# =========================================================
# 20. 顯示左右 NPZ
# =========================================================
@app.callback(
    [
        Output("gif-4-preview", "children"),
        Output("gif-4-meta", "children"),
        Output("image-index-label", "children"),
    ],
    [
        Input("gif-refresh-btn", "n_clicks"),
    ],
    prevent_initial_call=False,
)
def show_latest_image(_refresh_clicks):
    right_npz = find_latest_npz(NPZ_DIR)

    # =====================================================
    # 上方只保留左右 3D 圖，不顯示目前檔名、路徑與格式資訊
    # =====================================================
    preview = dbc.Row(
        [
            dbc.Col(
                [
                    make_npz_3d_card(
                        LEFT_NPZ_PATH,
                        "graph-left-cut-npz-3d",
                        show_colorbar=False,
                    ),
                ],
                xs=12,
                lg=6,
                className="d-flex flex-column",
                style={"minWidth": "0"},
            ),
            dbc.Col(
                [
                    make_npz_3d_card(
                        right_npz,
                        "graph-right-latest-npz-3d",
                        show_colorbar=True,
                    ),
                ],
                xs=12,
                lg=6,
                className="d-flex flex-column",
                style={"minWidth": "0"},
            ),
        ],
        className="g-3 align-items-stretch",
        style={
            "width": "100%",
            "margin": "0",
            "minWidth": "0",
        },
    )

    # =====================================================
    # 下方分析改成左右並排顯示
    # =====================================================
    left_report = []
    right_report = []

    # =====================================================
    # 左側 NPZ 高低落差分析
    # =====================================================
    if LEFT_NPZ_PATH.exists():
        try:
            left_info = load_npz_3d_payload(LEFT_NPZ_PATH)
            left_report = make_surface_height_report(
                left_info,
                title="左側 Cut STL NPZ 上表面高低落差分析",
            )
        except Exception as e:
            left_report = [
                html.Div(
                    f"左側上表面高低落差分析失敗：{e}",
                    className="text-warning small",
                )
            ]
    else:
        left_report = [
            html.Div(
                "⚠️ 左側固定 NPZ 不存在，無法計算左側上表面高低落差。",
                className="text-warning small",
            )
        ]

    # =====================================================
    # 右側 Latest NPZ 高低落差分析
    # =====================================================
    if right_npz:
        try:
            right_info = load_npz_3d_payload(right_npz)
            right_report = make_surface_height_report(
                right_info,
                title="右側 Latest NPZ 上表面高低落差分析",
            )
        except Exception as e:
            right_report = [
                html.Div(
                    f"右側上表面高低落差分析失敗：{e}",
                    className="text-warning small",
                )
            ]
    else:
        right_report = [
            html.Div(
                "⚠️ 右側找不到 NPZ 資料夾，或資料夾內沒有 .npz 檔，無法計算右側上表面高低落差。",
                className="text-warning small",
            )
        ]

    meta = dbc.Row(
        [
            dbc.Col(
                left_report,
                xs=12,
                lg=6,
                style={"minWidth": "0"},
            ),
            dbc.Col(
                right_report,
                xs=12,
                lg=6,
                style={"minWidth": "0"},
            ),
        ],
        className="g-3 align-items-stretch",
        style={
            "width": "100%",
            "margin": "0",
            "minWidth": "0",
        },
    )

    # 清空 image-index-label，避免顯示「目前顯示：左側...右側...」
    label = ""

    return preview, meta, label


# =========================================================
# 21. 啟動 Dash
# =========================================================
if __name__ == "__main__":
    app.run(port=8078, debug=False, use_reloader=False)