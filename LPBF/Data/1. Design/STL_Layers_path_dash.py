# === stl_layer_api.py ===
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
import trimesh
import numpy as np
import os

app = FastAPI()

# === STL 設定 ===
STL_PATH = r"D:\2026Experiment\2026Experiment0528\dash\NIST\1. Design\OverhangPart_9x5x5mm.STL"
LAYER_COUNT = 251
Z_MIN, Z_MAX = 0, 500
LAYER_HEIGHT = (Z_MAX - Z_MIN) / LAYER_COUNT

@app.get("/stl_layer/")
def get_stl_layer(target_layer: int = Query(..., ge=0, le=LAYER_COUNT - 1)):
    if not os.path.exists(STL_PATH):
        raise HTTPException(status_code=404, detail="STL 檔案不存在")

    try:
        # 讀取 STL 並縮放
        mesh = trimesh.load_mesh(STL_PATH)
        mesh.apply_scale([100, 100, 100])

        # 取得 STL 邊界
        bounds = mesh.bounds  # [[xmin, ymin, zmin], [xmax, ymax, zmax]]
        xmin, ymin, _ = bounds[0]
        xmax, ymax, _ = bounds[1]

        # 計算該層 Z 範圍
        z_start = Z_MIN + target_layer * LAYER_HEIGHT
        z_end = z_start + LAYER_HEIGHT

        # 產生紅框 8 個點
        box_vertices = np.array([
            [xmin, ymin, z_start],
            [xmax, ymin, z_start],
            [xmax, ymax, z_start],
            [xmin, ymax, z_start],
            [xmin, ymin, z_end],
            [xmax, ymin, z_end],
            [xmax, ymax, z_end],
            [xmin, ymax, z_end],
        ]).tolist()

        # 回傳 mesh + box
        return JSONResponse(content={
            "vertices": mesh.vertices.tolist(),
            "faces": mesh.faces.tolist(),
            "layer_box": box_vertices,
            "z_range": [z_start, z_end],
            "layer": target_layer
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"處理 STL 發生錯誤：{str(e)}")

# 若直接執行，啟動伺服器
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8004)
