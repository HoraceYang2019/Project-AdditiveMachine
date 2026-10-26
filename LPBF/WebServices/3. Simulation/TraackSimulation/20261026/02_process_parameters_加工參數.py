# -*- coding: utf-8 -*-
# 【02｜加工與數值參數】本檔不存放 Ti64 材料物性，所有材料物性由 01 提供。
"""LPBF 製程、邊界條件、數值設定（第一階段）。

保留加工／數值參數的命令列名稱（settings.power 等）。
此模組只負責設定，不包含材料係數，也不執行雷射或 CFD 計算。
材料吸收率與放射率只由 01_Material Parameters_材料參數.py 定義；06 目前停用。
03 模組由主程式傳入製程設定並讀取統一的材料係數。
"""
import argparse  # 使用 Python 標準命令列參數解析器
from importlib import import_module  # 讀取以數字及中文命名的唯一材料模組

# 各項設定依用途分類：第一個值為原本 CLI 名稱，第二個值為預設值。
LASER_PROCESS_OPTIONS = [  # A. 雷射與掃描設定
    ("power", 300.0, "雷射名目功率（W）"),  # 雷射輸入功率；尚須經吸收率與遮蔽模型計算實際吸收量
    ("speed", 1200.0, "雷射掃描速度（mm/s）"),  # 雷射中心沿正 X 方向移動的速度
    ("spot-diameter", 80.0, "Gaussian 光斑直徑（µm）"),  # 影響 X/Y 光強分布；不直接指定熔池深度
    ("start-um", 60.0, "X 方向掃描起點（µm）"),  # 雷射開始掃描的 X 座標
    ("end-margin-um", 690.0, "末端保留距離（µm）"),  # 避免掃描位置超出右側邊界
]  # 結束本段參數、容器或條件的組合
GEOMETRY_OPTIONS = [  # B. 幾何與網格設定
    ("grid-um", 2.0, "各方向 Voxel 網格尺寸（µm）"),  # 程式使用等距 dx=dy=dz
    ("substrate-um", 30.0, "基板頂面高度（µm）"),  # 自 z=0 向上計算基板所佔層數
]  # 結束本段參數、容器或條件的組合
THERMAL_BOUNDARY_OPTIONS = [  # C. 初始條件與散熱邊界
    ("ambient-h", 20.0, "環境對流換熱係數（W/m²/K）"),  # 表面對流熱損失模型
    ("bottom-h", 20000.0, "底部換熱係數（W/m²/K）"),  # 模型最底層對環境的散熱
    ("gas-k", None, "氣體熱傳導率（W/m/K）；未指定時使用 01 材料參數"),  # 僅在明確指定時覆寫材料值
]  # 結束本段參數、容器或條件的組合
NUMERICAL_OPTIONS = [  # E. 時間步、求解器、收斂及輸出頻率
    ("dt-ns", 0.5, "使用者指定時間步長上限（ns）"),  # 原始程式仍可能縮小至熱穩定步長
    ("save-us", 20.0, "NPZ 快照輸出間隔（µs）"),  # 溫度、焓、填充率與相態場的儲存週期
    ("log-us", 5.0, "CSV 診斷記錄間隔（µs）"),  # 診斷資訊輸出週期
    ("energy-report-distance-um", 10.0, "雷射前進此距離後輸出累積能量表並終止，不再冷卻（µm，相對掃描起點，預設 10）"),  # 接續變數 NUMERICAL_OPTIONS的數值、運算式或資料項目
    ("solidification-tol", 0.01, "凝固完成所允許的液相率"),  # 低於門檻視為凝固完成，必須搭配溫度和雷射關閉狀態判斷
]  # 結束本段參數、容器或條件的組合


# ============================================================================
# 函式大綱｜parse_command_line() — 建立加工與數值設定
# 【輸入】命令列參數
# 【計算】依雷射、幾何、熱邊界及輸出分類建立命令列選項並解析
# 【輸出】含預設值及使用者覆寫值的設定物件
# ============================================================================
def parse_command_line(args=None):  # 解析外部輸入；args=None 表示讀取終端命令列
    """傳回 01～05 的加工／數值設定；不包含材料吸收率或放射率。"""  # 材料係數只由 01 管理
    argument_parser = argparse.ArgumentParser(description=__doc__)  # 建立命令列解析器
    groups = [  # 指定參數在 --help 中的分類
        ("雷射製程", LASER_PROCESS_OPTIONS),  # 雷射功率、速度與光斑
        ("模型幾何", GEOMETRY_OPTIONS),  # Voxel 尺寸與基板高度
        ("熱邊界條件", THERMAL_BOUNDARY_OPTIONS),  # 對流與輻射
        ("數值及輸出", NUMERICAL_OPTIONS),  # 熱時間步、凝固判斷與資料輸出
    ]  # 結束本段參數、容器或條件的組合
    for group_name, options in groups:  # 為每類參數建立獨立 help 群組
        group = argument_parser.add_argument_group(group_name)  # 設定命令列顯示分類
        for option_name, default_value, explanation in options:  # 對群組內的參數逐項建立選項
            group.add_argument("--" + option_name, type=float, default=default_value, help=explanation)  # 保留原始名稱與預設值
    argument_parser.add_argument("--allow-existing-output", action="store_true", help="允許覆寫既有輸出；省略時熱模擬重跑會自動建立新目錄")  # 新增命令列選項及預設值與中文說明
    argument_parser.add_argument("--max-diagnostic-T", type=float, default=10000.0, help="溫度異常停止上限（K）")  # 非物理夾限，僅用於診斷
    argument_parser.add_argument("--check-every", type=int, default=100, help="每多少步進行數值檢查")  # 守恆檢查週期
    argument_parser.add_argument("--powder", default="input/solid_mask.npy", help="輸入 3D 粉末／基板遮罩路徑")  # 讀取 .npy 或 .npz
    argument_parser.add_argument("--through-stage", choices=("03", "04", "05"), default="05",  # 現階段僅提供雷射、熱傳與熱相變模式
                                 help="03 只驗證雷射；04 熱傳與固液相變、停用蒸發；05 熱傳與相變含蒸發（預設）；06 暫停使用")  # 清楚標示目前不執行流動模型
    argument_parser.add_argument("--laser-validation-dt-us", type=float, default=1.0,  # 新增命令列選項及預設值與中文說明
                                 help="03 單獨驗證時的雷射積分時間步長（us）")  # 新增命令列選項及預設值與中文說明
    argument_parser.add_argument("--out", default="output_stageA_voxel_250um_recoil_pressure_proxy", help="模擬輸出目錄")  # 新增命令列選項及預設值與中文說明
    argument_parser.add_argument("--cpu", action="store_true", help="強制 CPU NumPy 模式")  # 不使用 CuPy GPU
    argument_parser.add_argument("--evaporation-model", choices=("rate", "boiling", "off"), default="rate",  # 新增命令列選項及預設值與中文說明
                                 help="蒸發模型：rate 為 Hertz-Knudsen 速率模型（預設）；boiling 為舊沸點處理；off 停用")  # 新增命令列選項及預設值與中文說明
    argument_parser.add_argument("--evaporation-surface", choices=("top", "all-gas-faces"), default="top",  # 新增命令列選項及預設值與中文說明
                                 help="蒸發面積：top 依上方各層開放比例計算暴露面（預設）；all-gas-faces 包含內孔表面")  # 部分蒸發上層的開放比例會傳至下層
    argument_parser.add_argument("--evaporation-coefficient", type=float, default=0.20,  # 新增命令列選項及預設值與中文說明
                                 help="Hertz-Knudsen 蒸發係數（0~1，暫用值，需校正）")  # 新增命令列選項及預設值與中文說明
    argument_parser.add_argument("--vapor-back-pressure", type=float, default=0.0,  # 新增命令列選項及預設值與中文說明
                                 help="金屬蒸氣背壓／分壓（Pa），不是保護氣體總壓")  # 新增命令列選項及預設值與中文說明
    argument_parser.add_argument("--verify", action="store_true", help="執行原有內建測試後結束")  # 數值功能檢查
    argument_parser.add_argument("--diagnostic-csv", action="store_true", help="另外輸出詳細診斷 CSV 至 diagnostics 子目錄")  # 預設只輸出精簡時間歷程與距離結果 CSV
    argument_parser.add_argument("--max-steps", type=int, default=10000, help="模擬終止步數（預設 10000；設為 0 才使用距離終止）")  # 步數模式優先於原本的距離終止設定
    settings = argument_parser.parse_args(args=args)  # 先解析使用者指定的製程與邊界條件
    if settings.gas_k is None:  # 不以舊的寫死數值蓋過材料設定
        settings.gas_k = import_module('01_Material Parameters_材料參數').GAS_CONDUCTIVITY_W_M_K  # 使用 01 當前的氣體導熱率
    return settings  # 回傳已解析材料預設值的設定


# ============================================================================
# 函式大綱｜validate_process_parameters() — 檢查加工及蒸發參數
# 【輸入】加工與數值設定
# 【計算】檢查必要正值、蒸發係數範圍及金屬蒸氣背壓
# 【輸出】通過時回傳 True，設定無效則拋出例外
# ============================================================================
def validate_process_parameters(settings):  # 獨立執行時才檢查；不改動原模擬原有判斷
    """基本輸入範圍檢查；不會改寫使用者參數。"""  # 接續本段欄位名稱、提示訊息或報表文字
    if settings.through_stage not in ('03', '04', '05'):  # 防止外部建立設定物件時繞過命令列限制
        raise ValueError('現階段僅支援 03、04、05，06 暫停使用')  # 在載入幾何與開始運算前說明不支援的模式
    positive_names = ("power", "speed", "grid_um", "substrate_um", "spot_diameter", "dt_ns", "energy_report_distance_um", "gas_k")  # 氣體導熱率也須為有限正數
    if settings.max_steps < 0:  # 零保留為距離終止模式
        raise ValueError('max_steps 不得小於零')  # 避免無效的終止步數
    for name in positive_names:  # 依序檢查正值參數
        if not 0 < getattr(settings, name) < float("inf"):  # 檢查是否違反下限或非有限值
            raise ValueError(f"{name} 必須大於零")  # 顯示哪個參數有錯
    if not 0.0 <= settings.evaporation_coefficient <= 1.0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("evaporation_coefficient 必須介於 0 與 1")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    if not 0.0 <= settings.vapor_back_pressure < float("inf"):  # 判斷本行條件，成立時執行下方處理
        raise ValueError("vapor_back_pressure 必須是有限非負值")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    return True  # 通過檢查


if __name__ == "__main__":  # 獨立執行本檔時，印出當前製程參數
    settings = parse_command_line()  # 讀取命令列，允許外部覆寫預設值
    validate_process_parameters(settings)  # 檢查基本輸入範圍
    for parameter_name, parameter_value in vars(settings).items():  # 逐項讀出最終參數
        print(f"{parameter_name} = {parameter_value}")  # 顯示解析後的參數
