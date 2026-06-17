from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import io
import base64
import os
import tempfile
import uvicorn

app = FastAPI()

CSV_PATH = r"D:\2026Experiment\2026Experiment0528\dash\NIST\2. Slicing\laser_paths.csv"
plt.rcParams['font.family'] = 'Microsoft JhengHei'

# 🔁 全域快取
cache_gif = {}
cache_img = {}

@app.get("/get_animation/")
def get_animation(layer: int = 1):
    if layer in cache_gif:
        return JSONResponse(content={"gif_base64": cache_gif[layer]})

    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV 讀取錯誤：{str(e)}")

    if 'layer' not in df.columns:
        raise HTTPException(status_code=400, detail="CSV 缺少 'layer' 欄位")

    df_layer = df[df['layer'] == layer].reset_index(drop=True)
    if df_layer.empty:
        raise HTTPException(status_code=404, detail=f"第 {layer} 層沒有資料")

    # ✅ X 左右翻轉 & Y 上下翻轉
    df_layer['x1'], df_layer['x2'] = -df_layer['x1'], -df_layer['x2']
    df_layer['y1'], df_layer['y2'] = -df_layer['y1'], -df_layer['y2']

    # 準備動畫
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.set_title(f"第 {layer} 層雷射路徑（逐條顯示）")
    ax.set_xlim(df_layer[['x1', 'x2']].min().min() - 1, df_layer[['x1', 'x2']].max().max() + 1)
    ax.set_ylim(df_layer[['y1', 'y2']].min().min() - 1, df_layer[['y1', 'y2']].max().max() + 1)
    ax.set_aspect('equal')
    ax.grid(True)

    lines = []

    def update(i):
        row = df_layer.iloc[i]
        line, = ax.plot([row['x1'], row['x2']], [row['y1'], row['y2']], color='red', linewidth=1)
        lines.append(line)
        return lines

    ani = animation.FuncAnimation(
        fig, update, frames=len(df_layer), interval=50, blit=False, repeat=False
    )

    # 儲存為 GIF
    with tempfile.NamedTemporaryFile(suffix='.gif', delete=False) as tmpfile:
        tmp_path = tmpfile.name

    ani.save(tmp_path, writer='pillow')
    plt.close(fig)

    with open(tmp_path, 'rb') as f:
        gif_bytes = f.read()
    os.remove(tmp_path)

    base64_data = base64.b64encode(gif_bytes).decode("utf-8")
    cache_gif[layer] = base64_data

    return JSONResponse(content={"gif_base64": base64_data})


@app.get("/get_layer_plot/")
def get_layer_plot(layer: int = 1):
    if layer in cache_img:
        return JSONResponse(content={"image_base64": cache_img[layer]})

    try:
        df = pd.read_csv(CSV_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV 讀取錯誤：{str(e)}")

    df_layer = df[df["layer"] == layer]
    if df_layer.empty:
        raise HTTPException(status_code=404, detail=f"第 {layer} 層沒有資料")

    # ✅ X 左右翻轉 & Y 上下翻轉
    df_layer['x1'], df_layer['x2'] = -df_layer['x1'], -df_layer['x2']
    df_layer['y1'], df_layer['y2'] = -df_layer['y1'], -df_layer['y2']

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.set_xlim(df_layer[['x1', 'x2']].min().min() - 1, df_layer[['x1', 'x2']].max().max() + 1)
    ax.set_ylim(df_layer[['y1', 'y2']].min().min() - 1, df_layer[['y1', 'y2']].max().max() + 1)
    ax.set_aspect('equal')
    ax.axis("off")

    for _, row in df_layer.iterrows():
        ax.plot([row["x1"], row["x2"]], [row["y1"], row["y2"]], color='red', linewidth=1)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)

    buf.seek(0)
    image_base64 = base64.b64encode(buf.read()).decode("utf-8")
    cache_img[layer] = image_base64

    return JSONResponse(content={"image_base64": image_base64})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
