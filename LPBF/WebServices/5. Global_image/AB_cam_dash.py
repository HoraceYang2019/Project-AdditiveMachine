from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import matplotlib.pyplot as plt
from PIL import Image
import numpy as np
import base64
import os
import io
import uvicorn

app = FastAPI()

# 圖片資料夾
A_FOLDER = r"D:\2026Experiment\2026Experiment0528\dash\NIST\5. Global_image\before powder recoating"
B_FOLDER = r"D:\2026Experiment\2026Experiment0528\dash\NIST\5. Global_image\after laser exposure"
plt.rcParams['font.family'] = 'Microsoft JhengHei'

# 快取圖片
cache_ab_image = {}

# === 輔助讀圖函數 ===
def load_image(folder, source, layer_str, group):
    filename = f"{source}{layer_str}{group}.PNG"
    path = os.path.join(folder, filename)
    if os.path.exists(path):
        return np.array(Image.open(path))
    return None

# === API: 只顯示 Ac 與 Bc 的圖 ===
@app.get("/ab_camera_view/")
def get_ab_camera_view(layer: int):
    if not (2 <= layer <= 251):
        raise HTTPException(status_code=400, detail="層數需在 2 ~ 251 範圍內")

    layer_str = f"{layer:04d}"

    # 回傳快取圖片
    if layer in cache_ab_image:
        return JSONResponse(content={"image_base64": cache_ab_image[layer]})

    # 讀取 Ac 與 Bc 圖片
    img_a = load_image(A_FOLDER, 'A', layer_str, 'c')
    img_b = load_image(B_FOLDER, 'B', layer_str, 'c')

    fig, axs = plt.subplots(1, 2, figsize=(10, 6))

    # 顯示 Ac
    if img_a is not None:
        axs[0].imshow(img_a, cmap='gray')
        axs[0].set_title(f"A{layer_str}c")
    else:
        axs[0].text(0.5, 0.5, "Not Found", ha='center', va='center')
    axs[0].axis('off')

    # 顯示 Bc
    if img_b is not None:
        axs[1].imshow(img_b, cmap='gray')
        axs[1].set_title(f"B{layer_str}c")
    else:
        axs[1].text(0.5, 0.5, "Not Found", ha='center', va='center')
    axs[1].axis('off')

    plt.tight_layout()

    # 圖轉 base64
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches='tight')
    plt.close(fig)

    buf.seek(0)
    image_base64 = base64.b64encode(buf.read()).decode("utf-8")
    cache_ab_image[layer] = image_base64

    return JSONResponse(content={"image_base64": image_base64})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8005)
