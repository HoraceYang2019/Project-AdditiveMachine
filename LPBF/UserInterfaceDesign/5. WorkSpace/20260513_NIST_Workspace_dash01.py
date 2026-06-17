# -*- coding: utf-8 -*-

import dash
from dash import html, dcc, Input, Output, State, ctx, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.io as pio
import requests
import numpy as np


# =========================================================
# 1. 基本參數設定
# =========================================================

PIXEL_SIZE_MM = 0.02

# 工件尺寸：9 mm × 5 mm
X_RANGE_MM = 9.0
Y_RANGE_MM = 5.0


# =========================================================
# 2. API URL 設定
# =========================================================

OTHER_DASH_URL = "http://127.0.0.1:8074/"
SECOND_DASH_URL = "http://127.0.0.1:8072/"

# Layer Path / Animation API
LAYER_PATH_API_URL = "http://127.0.0.1:8001"

# Coverage Heatmap API
HEATMAP_API_URL = "http://127.0.0.1:8002/heatmap/"

# Cooling Time API
COOLINGTIME_API_URL = "http://127.0.0.1:8003/coolingtime/"

# STL API
STL_API_URL = "http://127.0.0.1:8004/stl_layer/"

# Chamber View API
# 注意：如果 8005 已經給 Layer Feature API 使用，
# Chamber View API 建議改到其他 port，避免衝突。
AB_CAMERA_URL = "http://127.0.0.1:8005/ab_camera_view/"

# Layer Feature API
# 8055：熔池寬度 Meltpool Width
LAYER_FEATURE_API_URL_WIDTH = "http://127.0.0.1:8055"

# 8066：熔池面積 Meltpool Area
# 注意：這裡仍然是讀 8066 API。
# 目前 8066 API 回傳 data 欄位仍是 meltpool_width_mm，
# 所以畫圖時會讀 meltpool_width_mm，只把顯示名稱改成熔池面積。
LAYER_FEATURE_API_URL_AREA = "http://127.0.0.1:8066"


# =========================================================
# 3. Dash App 初始化
# =========================================================

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True
)

app.title = "多功能模擬 Dashboard"

pio.templates.default = "plotly_white"
pio.templates["plotly_white"].layout.font.family = "Arial"


# =========================================================
# 4. UI 色彩設定
# =========================================================

BG = "#1f2430"
PANEL_BG = "#2a2f3a"
BORDER = "#3a4150"
TEXT = "#e8eaed"
MUTED = "#9aa0a6"


# =========================================================
# 5. Panel 包裝函式
# =========================================================

def panel(children, title=None, height=None):
    style = {
        "background": PANEL_BG,
        "border": f"1px solid {BORDER}",
        "borderRadius": "12px",
        "padding": "12px",
        "height": height or "100%",
        "display": "flex",
        "flexDirection": "column",
        "width": "100%"
    }

    items = []

    if title is not None:
        items.append(html.H5(title, style={"marginBottom": "8px"}))

    if isinstance(children, (list, tuple)):
        items.extend([c for c in children if c is not None])
    else:
        items.append(children)

    return html.Div(items, style=style)


# =========================================================
# 6. Layer Feature API 工具函式
# =========================================================

def make_error_figure(message, graph_height=390):
    fig = go.Figure()

    fig.update_layout(
        title=message,
        template="plotly_white",
        height=graph_height,
        margin=dict(t=55, b=20, l=20, r=20)
    )

    return fig


def fetch_layer_feature(api_base_url, layer_id, max_points=8000, include_segments=False):
    """
    從指定 Layer Feature API 讀取單一 Layer 資料。

    第一格：8055 熔池寬度
        http://127.0.0.1:8055/layer/{layer_id}

    第二格：8066 熔池面積
        http://127.0.0.1:8066/layer/{layer_id}
    """
    url = f"{api_base_url}/layer/{int(layer_id)}"

    res = requests.get(
        url,
        params={
            "max_points": int(max_points),
            "include_segments": bool(include_segments)
        },
        timeout=20
    )

    res.raise_for_status()

    return res.json()


def make_layer_path_figure(
    api_data,
    graph_height=390,
    source_label="",
    value_key="meltpool_width_mm",
    value_label="Meltpool Width",
    colorbar_title="Width (mm)",
    global_min_key=None,
    global_max_key=None,
    rotate_180=True
):
    """
    將 API 回傳的 x_mm / y_mm 與指定數值欄位畫成 XY 路徑圖。

    8055：value_key="meltpool_width_mm"，顯示熔池寬度。
    8066：仍然讀 8066 API 回傳的 meltpool_width_mm 欄位，
          只把畫面名稱顯示為熔池面積。

    rotate_180=True 時，同時反轉 X 軸與 Y 軸，
    讓 Layer Feature API Display 的顯示方向旋轉 180 度。
    """
    meta = api_data.get("meta", {})
    data = api_data.get("data", {})
    stats = api_data.get("stats", {})
    global_info = api_data.get("global", {})

    x = np.asarray(data.get("x_mm", []), dtype=float)
    y = np.asarray(data.get("y_mm", []), dtype=float)

    # 依照指定欄位讀取顏色值
    # 8055：meltpool_width_mm
    # 8066：目前 API 實際也回傳 meltpool_width_mm，只改顯示名稱為熔池面積
    value_raw = data.get(value_key, [])

    value = np.asarray(value_raw, dtype=float)

    fig = go.Figure()

    if len(x) == 0 or len(y) == 0 or len(value) == 0:
        available_keys = ", ".join(list(data.keys())) if isinstance(data, dict) else "無法取得欄位"
        return make_error_figure(
            f"Layer Feature API 沒有回傳有效資料｜需要欄位：x_mm, y_mm, {value_key}<br>目前 data 欄位：{available_keys}",
            graph_height=graph_height
        )

    # 避免 x/y/value 長度不同造成 Plotly 顯示錯誤
    n = min(len(x), len(y), len(value))
    x = x[:n]
    y = y[:n]
    value = value[:n]

    finite_value = value[np.isfinite(value)]
    if len(finite_value) == 0:
        return make_error_figure(
            f"{value_label} 全部都是 NaN 或非數值，無法顯示",
            graph_height=graph_height
        )

    # 色階範圍：優先使用 API global，沒有才用目前 layer 的 min/max
    cmin = None
    cmax = None

    if global_min_key and global_max_key:
        cmin = global_info.get(global_min_key)
        cmax = global_info.get(global_max_key)

    if cmin is None or cmax is None:
        cmin = global_info.get("w_min", global_info.get("width_min", None))
        cmax = global_info.get("w_max", global_info.get("width_max", None))

    if cmin is None or cmax is None:
        cmin = float(np.nanmin(finite_value))
        cmax = float(np.nanmax(finite_value))

    fig.add_trace(
        go.Scattergl(
            x=x,
            y=y,
            mode="lines+markers",
            line=dict(width=1, color="rgba(80,80,80,0.45)"),
            marker=dict(
                size=4,
                color=value,
                colorscale="Jet",
                cmin=float(cmin),
                cmax=float(cmax),
                colorbar=dict(title=colorbar_title),
            ),
            hovertemplate=(
                "X: %{x:.4f} mm<br>"
                "Y: %{y:.4f} mm<br>"
                f"{value_label}: " + "%{marker.color:.6f}"
                "<extra></extra>"
            ),
            name=value_label
        )
    )

    # 起點標示
    fig.add_trace(
        go.Scattergl(
            x=[x[0]],
            y=[y[0]],
            mode="markers+text",
            marker=dict(size=10, color="red"),
            text=["Start"],
            textposition="top right",
            name="Start",
            hoverinfo="skip"
        )
    )

    csv_name = meta.get("csv_name", "")

    title_text = (
        f"{value_label} {source_label} | CSV: {csv_name} | Rows: {stats.get('rows_original', len(x))}"
    )

    fig.update_layout(
        title=title_text,
        template="plotly_white",
        height=graph_height,
        margin=dict(t=65, b=45, l=55, r=80),
        xaxis_title="Laser position X (mm)",
        yaxis_title="Laser position Y (mm)",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
    )

    fig.update_yaxes(scaleanchor="x", scaleratio=1)

    # 使用 API 給的全域座標範圍，讓 8055 / 8066 顯示比例一致
    if global_info:
        x_min = global_info.get("x_min")
        x_max = global_info.get("x_max")
        y_min = global_info.get("y_min")
        y_max = global_info.get("y_max")

        if all(v is not None for v in [x_min, x_max, y_min, y_max]):
            dx = float(x_max) - float(x_min)
            dy = float(y_max) - float(y_min)

            pad_x = dx * 0.05 if dx > 0 else 1.0
            pad_y = dy * 0.05 if dy > 0 else 1.0

            if rotate_180:
                # 旋轉 180 度 = X 軸反向 + Y 軸反向
                fig.update_xaxes(range=[float(x_max) + pad_x, float(x_min) - pad_x])
                fig.update_yaxes(range=[float(y_max) + pad_y, float(y_min) - pad_y])
            else:
                fig.update_xaxes(range=[float(x_min) - pad_x, float(x_max) + pad_x])
                fig.update_yaxes(range=[float(y_min) - pad_y, float(y_max) + pad_y])

    elif rotate_180:
        # 如果 API 沒有提供 global 座標範圍，也一樣反轉兩個軸
        fig.update_xaxes(autorange="reversed")
        fig.update_yaxes(autorange="reversed")

    return fig


# =========================================================
# 7. Layout
# =========================================================

app.layout = html.Div([
    dcc.Interval(
        id="npz-init-trigger",
        interval=500,
        n_intervals=0,
        max_intervals=1
    ),

    html.Div([
        dcc.Slider(
            id="global-layer-slider",
            min=1,
            max=250,
            step=1,
            value=1,
            marks={i: str(i) for i in range(1, 251, 25)},
            tooltip={"placement": "bottom", "always_visible": False}
        )
    ], style={
        "padding": "10px",
        "borderBottom": f"2px solid {BORDER}"
    }),

    dbc.Row([
        # =================================================
        # 左側：STL + Layer Path + Chamber View
        # =================================================
        dbc.Col(
            panel([
                html.H5("STL and Layer Paths"),

                dcc.Tabs(
                    id="tabs-stl-path",
                    value="tab-stl",
                    children=[
                        dcc.Tab(label="STL Model", value="tab-stl"),
                        dcc.Tab(label="Layer Paths", value="tab-path")
                    ],
                    style={
                        "background": PANEL_BG,
                        "color": TEXT
                    }
                ),

                html.Div(
                    id="tabs-content-stl-path",
                    children=[
                        html.Div([
                            dcc.Dropdown(
                                id="stl-layer-dropdown",
                                options=[
                                    {"label": f"Layer {i}", "value": i}
                                    for i in range(1, 251)
                                ],
                                value=1,
                                style={
                                    "width": "100%",
                                    "marginBottom": "10px"
                                }
                            ),

                            dcc.Graph(
                                id="stl-graph",
                                style={
                                    "height": "400px",
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "8px",
                                    "background": "#ffffff"
                                }
                            ),

                            html.Div(
                                id="stl-error-msg",
                                style={
                                    "color": "#ff6b6b",
                                    "marginTop": "5px"
                                }
                            )
                        ], id="tab-stl-content", style={"display": "block"}),

                        html.Div([
                            dcc.Dropdown(
                                id="path-layer-dropdown",
                                options=[
                                    {"label": f"Layer {i}", "value": i}
                                    for i in range(1, 251)
                                ],
                                value=1,
                                style={
                                    "width": "100%",
                                    "marginBottom": "10px"
                                }
                            ),

                            html.Div([
                                html.Button(
                                    "▶ play",
                                    id="play-btn",
                                    n_clicks=0,
                                    style={"marginRight": "10px"}
                                ),
                                html.Button(
                                    "⏸ stop",
                                    id="pause-btn",
                                    n_clicks=0
                                )
                            ], style={"marginBottom": "10px"}),

                            html.Div(id="animation-container"),

                            dcc.Store(id="played-layer", data=None),
                            dcc.Store(id="animation-ended", data=False)

                        ], id="tab-path-content", style={"display": "none"})
                    ],
                    style={
                        "height": "420px",
                        "border": f"1px solid {BORDER}",
                        "padding": "10px",
                        "overflow": "auto",
                        "borderRadius": "8px"
                    }
                ),

                html.Hr(style={"borderColor": BORDER}),

                html.H5("Chamber View"),

                dcc.Dropdown(
                    id="ab-layer-dropdown",
                    options=[
                        {"label": str(l), "value": l}
                        for l in range(2, 252)
                    ],
                    value=2,
                    clearable=False,
                    style={
                        "width": "100%",
                        "marginBottom": "10px"
                    }
                ),

                html.Img(
                    id="ab-camera-image",
                    style={
                        "width": "100%",
                        "border": f"1px solid {BORDER}",
                        "borderRadius": "8px",
                        "background": "#000"
                    }
                ),

                html.Div(
                    id="ab-camera-error",
                    style={
                        "color": "#ffb74d",
                        "marginTop": "5px"
                    }
                )
            ]),
            width=3,
            style={"display": "flex"}
        ),

        # =================================================
        # 中間：Layer Feature API Display
        # 第一格：8055 熔池寬度，XY Path
        # 第二格：8066 API，畫面名稱顯示熔池面積
        # =================================================
        dbc.Col(
            panel([
                html.H5("Layer Feature API Display"),

                # 保留元件給 callback 使用，但隱藏，不顯示 API 讀取文字
                html.Div(
                    id="layer-feature-api-status",
                    style={"display": "none"}
                ),

                html.Div([
                    dcc.Graph(
                        id="npz-left-graph",
                        style={
                            "height": "390px",
                            "background": "#ffffff",
                            "border": f"1px solid {BORDER}",
                            "borderRadius": "8px"
                        }
                    )
                ],
                    style={
                        "width": "100%",
                        "minWidth": "0",
                        "marginBottom": "10px"
                    }
                ),

                html.Div([
                    dcc.Graph(
                        id="npz-right-graph",
                        style={
                            "height": "390px",
                            "background": "#ffffff",
                            "border": f"1px solid {BORDER}",
                            "borderRadius": "8px"
                        }
                    )
                ],
                    style={
                        "width": "100%",
                        "minWidth": "0"
                    }
                )
            ]),
            width=6,
            style={"display": "flex"}
        ),

        # =================================================
        # 右側：Coverage + Cooling Time
        # =================================================
        dbc.Col(
            panel([
                html.H5("Coverage Layer"),

                dcc.Dropdown(
                    id="heat-layer-dropdown",
                    options=[
                        {"label": f"Layer {i}", "value": i}
                        for i in range(1, 251)
                    ],
                    value=1,
                    clearable=False,
                    style={
                        "width": "100%",
                        "marginBottom": "6px"
                    }
                ),

                dcc.Graph(
                    id="heatmap-graph",
                    style={
                        "height": "350px",
                        "background": "#ffffff",
                        "border": f"1px solid {BORDER}",
                        "borderRadius": "8px"
                    }
                ),

                html.Hr(style={"borderColor": BORDER}),

                html.H5("Cooling Time"),

                dcc.Dropdown(
                    id="ct-layer-dropdown",
                    options=[
                        {"label": f"Layer {i}", "value": i}
                        for i in range(1, 251)
                    ],
                    value=1,
                    clearable=False,
                    style={
                        "width": "100%",
                        "marginBottom": "4px"
                    }
                ),

                html.Div(
                    id="ct-error-message",
                    style={
                        "color": "#ffb74d",
                        "marginTop": "4px",
                        "fontSize": "14px"
                    }
                ),

                html.Img(
                    id="ct-image",
                    style={
                        "display": "none"
                    }
                ),

                html.Div(id="static-ct-image-container")
            ]),
            width=3,
            style={"display": "flex"}
        )
    ],
        className="g-2",
        style={
            "marginBottom": "20px",
            "alignItems": "stretch",
            "marginLeft": "0px",
            "marginRight": "0px"
        }
    )
],
    style={
        "background": BG,
        "color": TEXT,
        "minHeight": "100vh",
        "padding": "8px"
    }
)


# =========================================================
# 8. Callback：同步所有 Layer Dropdown
# =========================================================

@app.callback(
    Output("stl-layer-dropdown", "value"),
    Output("path-layer-dropdown", "value"),
    Output("ct-layer-dropdown", "value"),
    Output("ab-layer-dropdown", "value"),
    Output("heat-layer-dropdown", "value"),
    Input("global-layer-slider", "value"),
    prevent_initial_call=True
)
def sync_all_dropdowns(global_layer):
    display_layer = int(global_layer if global_layer is not None else 1)

    # Chamber View 原本從 2 開始，如果 slider 是 1，就固定顯示 2
    ab_layer = display_layer if 2 <= display_layer <= 251 else 2

    return (
        display_layer,
        display_layer,
        display_layer,
        ab_layer,
        display_layer
    )


# =========================================================
# 9. Callback：切換 STL / Layer Path Tab
# =========================================================

@app.callback(
    Output("tab-stl-content", "style"),
    Output("tab-path-content", "style"),
    Input("tabs-stl-path", "value")
)
def toggle_tabs(selected_tab):
    if selected_tab == "tab-stl":
        return {"display": "block"}, {"display": "none"}

    return {"display": "none"}, {"display": "block"}


# =========================================================
# 10. Callback：更新 STL 3D 圖
# =========================================================

@app.callback(
    Output("stl-graph", "figure"),
    Output("stl-error-msg", "children"),
    Input("stl-layer-dropdown", "value"),
    Input("tabs-stl-path", "value")
)
def update_stl_graph(target_layer, tab_value):
    if tab_value != "tab-stl":
        return no_update, ""

    try:
        res = requests.get(
            STL_API_URL,
            params={"target_layer": target_layer},
            timeout=10
        )

        if res.status_code != 200:
            return go.Figure(), f"❌ Request error：{res.status_code}"

        data = res.json()

        vertices = np.array(data["vertices"])
        faces = np.array(data["faces"])
        box = np.array(data["layer_box"])
        z_range = data["z_range"]

        mesh = go.Mesh3d(
            x=vertices[:, 0],
            y=vertices[:, 1],
            z=vertices[:, 2],
            i=faces[:, 0],
            j=faces[:, 1],
            k=faces[:, 2],
            opacity=0.3,
            color="gray",
            name="STL Mesh"
        )

        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7)
        ]

        box_lines = go.Scatter3d(
            x=sum([[box[i][0], box[j][0], None] for i, j in edges], []),
            y=sum([[box[i][1], box[j][1], None] for i, j in edges], []),
            z=sum([[box[i][2], box[j][2], None] for i, j in edges], []),
            mode="lines",
            line=dict(color="red", width=3),
            name=f"Layer {target_layer} Box"
        )

        fig = go.Figure(data=[mesh, box_lines])

        fig.update_layout(
            scene=dict(aspectmode="data"),
            margin=dict(l=0, r=0, t=40, b=0),
            title=f"STL {target_layer} layer（Z: {z_range[0]:.2f} ~ {z_range[1]:.2f}）"
        )

        return fig, ""

    except requests.exceptions.ConnectionError:
        return go.Figure(), "❌ STL FastAPI 連線失敗，請確認 port 8004 是否已啟動"

    except Exception as e:
        return go.Figure(), f"❌ error：{str(e)}"


# =========================================================
# 11. Callback：Layer Path 動畫控制
# =========================================================

@app.callback(
    Output("animation-container", "children"),
    Output("played-layer", "data"),
    Output("animation-ended", "data"),
    Input("play-btn", "n_clicks"),
    Input("pause-btn", "n_clicks"),
    Input("path-layer-dropdown", "value"),
    State("played-layer", "data"),
    State("animation-ended", "data"),
    State("animation-container", "children"),
    prevent_initial_call=True
)
def control_animation(
    play_clicks,
    pause_clicks,
    layer,
    played_layer,
    animation_done,
    current_content
):
    triggered = ctx.triggered_id

    if triggered == "pause-btn":
        try:
            res = requests.get(
                f"{LAYER_PATH_API_URL}/get_layer_plot/",
                params={"layer": layer},
                timeout=10
            )

            if res.status_code == 200:
                img_data = res.json()["image_base64"]

                return (
                    html.Img(
                        src=f"data:image/png;base64,{img_data}",
                        style={"maxWidth": "100%"}
                    ),
                    played_layer,
                    animation_done
                )

            return (
                html.Div(f"⚠️ Failed to load static image：{res.status_code}"),
                played_layer,
                animation_done
            )

        except Exception as e:
            return (
                html.Div(f"❌ error：{str(e)}"),
                played_layer,
                animation_done
            )

    if triggered == "path-layer-dropdown":
        return current_content, None, False

    if triggered == "play-btn":
        if played_layer == layer and animation_done:
            return current_content, played_layer, animation_done

        try:
            res = requests.get(
                f"{LAYER_PATH_API_URL}/get_animation/",
                params={"layer": layer},
                timeout=10
            )

            if res.status_code == 200:
                gif_data = res.json()["gif_base64"]

                return (
                    html.Img(
                        src=f"data:image/gif;base64,{gif_data}",
                        style={"maxWidth": "100%"}
                    ),
                    layer,
                    True
                )

            return (
                html.Div(f"⚠️ Unable to load animation：{res.status_code}"),
                played_layer,
                animation_done
            )

        except Exception as e:
            return (
                html.Div(f"❌ Request error: {str(e)}"),
                played_layer,
                animation_done
            )

    return current_content, played_layer, animation_done


# =========================================================
# 12. Callback：Coverage Heatmap
# =========================================================

@app.callback(
    Output("heatmap-graph", "figure"),
    Input("heat-layer-dropdown", "value")
)
def update_heatmap(layer):
    try:
        res = requests.get(
            HEATMAP_API_URL,
            params={"layer": layer},
            timeout=10
        )

        res.raise_for_status()

        json_data = res.json()
        z_data = np.array(json_data["heatmap"], dtype=float)

        h, w = z_data.shape

        x_mm = np.linspace(0, X_RANGE_MM, w)
        y_mm = np.linspace(0, Y_RANGE_MM, h)

        fig = go.Figure(
            data=go.Heatmap(
                z=z_data,
                x=x_mm,
                y=y_mm,
                zmin=0,
                zmax=2500,
                colorscale="Jet",
                colorbar=dict(title="Temp (°C)")
            )
        )

        fig.update_layout(
            title=f"Coverage - Layer {layer}",
            xaxis_title="X (mm)",
            yaxis_title="Y (mm)",
            xaxis=dict(range=[0, X_RANGE_MM]),
            yaxis=dict(range=[0, Y_RANGE_MM]),
            template="plotly_white",
            margin=dict(t=40, b=40, l=50, r=60)
        )

        return fig

    except requests.exceptions.ConnectionError:
        fig = go.Figure()

        fig.update_layout(
            title="❌ Coverage Heatmap API 連線失敗，請確認 port 8002 是否已啟動",
            margin=dict(t=40),
            template="plotly_white"
        )

        return fig

    except Exception as e:
        fig = go.Figure()

        fig.update_layout(
            title=f"⚠️ Coverage loading failed：{str(e)}",
            margin=dict(t=40),
            template="plotly_white"
        )

        return fig


# =========================================================
# 13. Callback：Cooling Time Heatmap
# =========================================================

@app.callback(
    Output("ct-image", "style"),
    Output("static-ct-image-container", "children"),
    Output("ct-error-message", "children"),
    Input("ct-layer-dropdown", "value")
)
def display_ct_heatmap_api_mode(ct_layer_value):
    try:
        display_layer = int(ct_layer_value if ct_layer_value is not None else 1)
        api_layer = display_layer - 1

        res = requests.get(
            COOLINGTIME_API_URL,
            params={"layer": api_layer},
            timeout=10
        )

        res.raise_for_status()

        json_data = res.json()
        data = np.array(json_data["heatmap"], dtype=float)

        if data.ndim != 2:
            return (
                {"display": "none"},
                html.Div(),
                f"❌ CoolingTime 資料維度錯誤，目前維度：{data.shape}"
            )

        h, w = data.shape

        x_mm = np.linspace(0, X_RANGE_MM, w)
        y_mm = np.linspace(0, Y_RANGE_MM, h)

        zmin = json_data.get("zmin", 0)
        zmax = json_data.get("zmax", 1600)
        unit = json_data.get("unit", "us")

        fig = go.Figure(
            data=go.Heatmap(
                z=data,
                x=x_mm,
                y=y_mm,
                colorscale="Blues",
                zmin=zmin,
                zmax=zmax,
                colorbar=dict(title=f"Time ({unit})")
            )
        )

        fig.update_layout(
            title=f"Cooling Time Map — Layer {display_layer}",
            xaxis_title="X (mm)",
            yaxis_title="Y (mm)",
            xaxis=dict(range=[0, X_RANGE_MM]),
            yaxis=dict(range=[0, Y_RANGE_MM]),
            template="plotly_white",
            height=400,
            margin=dict(t=50, b=40, l=50, r=70)
        )

        graph = dcc.Graph(
            figure=fig,
            style={
                "border": "1px solid #e5e7eb",
                "borderRadius": "10px",
                "background": "#ffffff"
            }
        )

        return (
            {"display": "none"},
            graph,
            ""
        )

    except requests.exceptions.ConnectionError:
        return (
            {"display": "none"},
            html.Div(),
            "❌ CoolingTime FastAPI 連線失敗，請確認 port 8003 是否已啟動"
        )

    except requests.exceptions.Timeout:
        return (
            {"display": "none"},
            html.Div(),
            "❌ CoolingTime API 連線逾時，請確認 port 8003 是否正常運作"
        )

    except requests.exceptions.HTTPError as e:
        try:
            detail = res.json().get("detail", res.text)
        except Exception:
            detail = str(e)

        return (
            {"display": "none"},
            html.Div(),
            f"❌ CoolingTime API 回傳錯誤：{detail}"
        )

    except Exception as e:
        return (
            {"display": "none"},
            html.Div(),
            f"❌ CoolingTime 顯示錯誤：{str(e)}"
        )


# =========================================================
# 14. Callback：Chamber View
# =========================================================

@app.callback(
    Output("ab-camera-image", "src"),
    Output("ab-camera-error", "children"),
    Input("ab-layer-dropdown", "value")
)
def update_ab_camera_image(layer):
    try:
        res = requests.get(
            AB_CAMERA_URL,
            params={"layer": layer},
            timeout=10
        )

        if res.status_code == 200:
            img_base64 = res.json()["image_base64"]
            return f"data:image/png;base64,{img_base64}", ""

        try:
            detail = res.json().get("detail", res.text)
        except Exception:
            detail = res.text

        return None, f"⚠️ Loading failed：{detail}"

    except requests.exceptions.ConnectionError:
        return None, "❌ Chamber View API 連線失敗，請確認 Chamber API port 是否已啟動"

    except Exception as e:
        return None, f"❌ error：{str(e)}"


# =========================================================
# 15. Callback：Layer Feature API Display
# 第一格讀 8055，顯示熔池寬度 XY Path
# 第二格讀 8066，畫面名稱顯示熔池面積 XY Path
# 已移除畫面上的 API 讀取狀態文字
# =========================================================

@app.callback(
    Output("npz-left-graph", "figure"),
    Output("npz-right-graph", "figure"),
    Output("layer-feature-api-status", "children"),
    Input("npz-init-trigger", "n_intervals"),
    Input("global-layer-slider", "value")
)
def update_npz_area_with_layer_feature_api(_, layer_value):
    display_layer = int(layer_value if layer_value is not None else 1)

    try:
        # 第一格：讀 8055 API，顯示熔池寬度
        api_data_width = fetch_layer_feature(
            api_base_url=LAYER_FEATURE_API_URL_WIDTH,
            layer_id=display_layer,
            max_points=8000,
            include_segments=False
        )

        # 第二格：讀 8066 API，畫面名稱顯示熔池面積
        api_data_area = fetch_layer_feature(
            api_base_url=LAYER_FEATURE_API_URL_AREA,
            layer_id=display_layer,
            max_points=8000,
            include_segments=False
        )

        # 第一格：8055 熔池寬度，旋轉 180 度
        width_fig = make_layer_path_figure(
            api_data_width,
            graph_height=390,
            source_label="| 8055",
            value_key="meltpool_width_mm",
            value_label="Meltpool Width / 熔池寬度",
            colorbar_title="Width (mm)",
            global_min_key="w_min",
            global_max_key="w_max",
            rotate_180=True
        )

        # 第二格：8066 API，畫面名稱顯示熔池面積
        # 注意：8066 實際回傳欄位目前是 meltpool_width_mm，
        # 所以這裡維持讀 meltpool_width_mm，只改顯示名稱。
        area_fig = make_layer_path_figure(
            api_data_area,
            graph_height=390,
            source_label="| 8066",
            value_key="meltpool_width_mm",
            value_label="Meltpool Area / 熔池面積",
            colorbar_title="Area",
            global_min_key="w_min",
            global_max_key="w_max",
            rotate_180=True
        )

        return width_fig, area_fig, ""

    except requests.exceptions.ConnectionError:
        err = (
            "❌ Layer Feature API 連線失敗，請確認 8055 與 8066 都已啟動。"
            " 8055 = 熔池寬度，8066 = 熔池面積。"
        )
        return make_error_figure(err), make_error_figure(err), ""

    except requests.exceptions.Timeout:
        err = "❌ Layer Feature API 連線逾時，請確認 8055 / 8066 API 是否正常運作。"
        return make_error_figure(err), make_error_figure(err), ""

    except requests.exceptions.HTTPError as e:
        err = f"❌ Layer Feature API 回傳錯誤：{str(e)}"
        return make_error_figure(err), make_error_figure(err), ""

    except Exception as e:
        err = f"❌ Layer Feature API 顯示錯誤：{str(e)}"
        return make_error_figure(err), make_error_figure(err), ""


# =========================================================
# 16. 主程式入口
# =========================================================

if __name__ == "__main__":
    print("====================================================")
    print("Dash URL: http://127.0.0.1:8071")
    print("Coverage Heatmap API URL:", HEATMAP_API_URL)
    print("CoolingTime API URL:", COOLINGTIME_API_URL)
    print("STL API URL:", STL_API_URL)
    print("Layer Feature API WIDTH URL:", LAYER_FEATURE_API_URL_WIDTH)
    print("Layer Feature API AREA URL:", LAYER_FEATURE_API_URL_AREA)
    print("注意：Layer Feature API Display 第一格讀 8055 熔池寬度，第二格讀 8066 熔池面積")
    print("第二格仍讀 8066 API，但實際欄位使用 meltpool_width_mm，只改顯示名稱")
    print("兩格都顯示 XY Path，並且已旋轉 180 度")
    print("畫面不顯示 API 讀取狀態文字")
    print("版面：左側 STL，中間 Layer Feature，右側 Coverage + Cooling Time")
    print("====================================================")

    app.run(debug=True, port=8071)