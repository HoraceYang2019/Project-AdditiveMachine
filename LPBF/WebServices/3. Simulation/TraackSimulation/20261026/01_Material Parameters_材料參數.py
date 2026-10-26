
# -*- coding: utf-8 -*-
"""Ti-6Al-4V 材料係數：目前僅保留 01～05 與主程式實際使用的項目。

功能：
1. 定義 Ti64 固態與液態材料物性
2. 定義固液相變及汽化參數
3. 定義反衝壓診斷所需表面張力與熱輻射參數
4. 統一管理固態與液態雷射吸收率
5. 驗證材料參數是否具有基本物理合理性

注意：
- 雷射吸收率依使用者設定為固態 0.40、液態 0.25。
- 已移除不參與計算的氣體名稱、雷射波長與折射率／消光係數。
- 06 暫停使用，其專用液態密度、黏度、氣體參考溫度與熱膨脹係數已移除。
- 本檔只管理係數，不執行熔池模擬。
- 長度 m、時間 s、溫度 K，其他均使用 SI 單位。
"""

import math  # 載入數學函式所需功能

SOLID_DENSITY_KG_M3 = 4420.0                    # 固態 Ti64 密度，kg/m³
SOLID_SPECIFIC_HEAT_J_KG_K = 650.0              # 固態比熱容，J/(kg·K)
LIQUID_SPECIFIC_HEAT_J_KG_K = 831.0             # 液態比熱容，J/(kg·K)
SOLID_CONDUCTIVITY_W_M_K = 8.0                  # 固態熱傳導係數，W/(m·K)
LIQUID_CONDUCTIVITY_W_M_K = 33.4                # 液態熱傳導係數，W/(m·K)
SOLIDUS_TEMPERATURE_K = 1878.0                  # 固相線溫度，K
LIQUIDUS_TEMPERATURE_K = 1928.0                 # 液相線溫度，K
LATENT_HEAT_J_KG = 360000.0                     # 固液相變潛熱，J/kg
GAS_DENSITY_KG_M3 = 1.63                        # 氬氣參考密度，kg/m³；約室溫常壓
GAS_SPECIFIC_HEAT_J_KG_K = 520.0                # 氬氣定壓比熱容，J/(kg·K)
GAS_CONDUCTIVITY_W_M_K = 0.0177                 # 氬氣熱傳導係數，W/(m·K)
BOILING_TEMPERATURE_K = 3315.0                  # 沸點，K
LATENT_HEAT_VAPORIZATION_J_KG = 9830000         # 汽化潛熱，J/kg
MOLAR_MASS_KG_MOL = 0.04649                     # Ti-6Al-4V（Ti64）合金的平均摩爾質量
SURFACE_TENSION_N_M = 1.525                     # 液態 Ti64 表面張力，N/m
SURFACE_TENSION_TEMP_COEFF_N_M_K = -1.90e-4     # Ti64 表面張力溫度係數，N/(m·K)
EMISSIVITY = 1.0                                # 表面放射率，無因次
STEFAN_BOLTZMANN_CONSTANT = 5.670374419e-08     # Stefan-Boltzmann 常數，W/(m²·K⁴)，表面熱輻射損失。
SOLID_LASER_ABSORPTIVITY = 0.40  # 使用者指定固態雷射吸收率；作為液相率為零時的端點
LIQUID_LASER_ABSORPTIVITY = 0.25  # 使用者指定液態雷射吸收率；作為液相率為一時的端點
UNIVERSAL_GAS_CONSTANT_J_MOL_K = 8.314462618    # 通用氣體常數，J/(mol·K)
MINIMUM_ACTIVE_METAL_FILL = 1e-05               # 最小有效金屬體積填充率

# ============================================================================
# 函式大綱｜validate_material_properties() — 檢查材料物性
# 【輸入】無外部參數；讀取本檔或相關模組設定
# 【計算】檢查有限正值、相變溫度順序、放射率與填充率範圍；不等同實驗校正
# 【輸出】通過時回傳 True，無效物性則拋出例外
# ============================================================================
def validate_material_properties():  # 定義函式：檢查材料物性
    """驗證已設定係數的基本數值合理性。

    注意：
    此函式不代表已通過實驗、CFD 或能量守恆驗證。
    """

    positive_parameters = {  # 計算或建立必須為有限正數的材料係數集合
        "固態密度": SOLID_DENSITY_KG_M3,  # 設定變數 固態密度欄位的值
        "固態比熱": SOLID_SPECIFIC_HEAT_J_KG_K,  # 設定變數 固態比熱欄位的值
        "液態比熱": LIQUID_SPECIFIC_HEAT_J_KG_K,  # 設定變數 液態比熱欄位的值
        "固態熱傳導率": SOLID_CONDUCTIVITY_W_M_K,  # 設定變數 固態熱傳導率欄位的值
        "液態熱傳導率": LIQUID_CONDUCTIVITY_W_M_K,  # 設定變數 液態熱傳導率欄位的值
        "氣體密度": GAS_DENSITY_KG_M3,  # 驗證氬氣密度
        "氣體比熱": GAS_SPECIFIC_HEAT_J_KG_K,  # 驗證氬氣比熱
        "氣體熱傳導率": GAS_CONDUCTIVITY_W_M_K,  # 驗證氬氣導熱係數
        "熔化潛熱": LATENT_HEAT_J_KG,  # 設定變數 熔化潛熱欄位的值
        "汽化潛熱": LATENT_HEAT_VAPORIZATION_J_KG,  # 設定變數 汽化潛熱欄位的值
        "表面張力": SURFACE_TENSION_N_M,  # 設定變數 表面張力欄位的值
        "莫耳質量": MOLAR_MASS_KG_MOL,  # 設定變數 莫耳質量欄位的值
        "氣體常數": UNIVERSAL_GAS_CONSTANT_J_MOL_K,  # 設定變數 氣體常數欄位的值
        "Stefan-Boltzmann 常數":  # 設定變數 Stefan-Boltzmann 常數欄位的值
            STEFAN_BOLTZMANN_CONSTANT,  # 接續必須為有限正數的材料係數集合的數值、運算式或資料項目
    }  # 結束本段參數、容器或條件的組合

    for parameter_name, parameter_value in positive_parameters.items():  # 依序處理parameter_name, parameter_value，逐項套用下方運算

        if (  # 判斷本行條件，成立時執行下方處理
            not math.isfinite(parameter_value)  # 接續上一行的邏輯判斷或大小比較條件
            or parameter_value <= 0  # 接續上一行的邏輯判斷或大小比較條件
        ):  # 結束本段參數、容器或條件的組合
            raise ValueError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
                f"{parameter_name}必須為有限正數："  # 接續本段欄位名稱、提示訊息或報表文字
                f"{parameter_value}"  # 接續本段欄位名稱、提示訊息或報表文字
            )  # 結束本段參數、容器或條件的組合

    # 檢查相變溫度
    if not (  # 判斷本行條件，成立時執行下方處理
        0 < SOLIDUS_TEMPERATURE_K  # 接續本段參數、索引或數值運算
        < LIQUIDUS_TEMPERATURE_K  # 接續上一行的邏輯判斷或大小比較條件
        < BOILING_TEMPERATURE_K  # 接續上一行的邏輯判斷或大小比較條件
    ):  # 結束本段參數、容器或條件的組合
        raise ValueError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
            "溫度必須符合 固相線 < 液相線 < 沸點"  # 接續本段欄位名稱、提示訊息或報表文字
        )  # 結束本段參數、容器或條件的組合

    # 檢查放射率
    if not 0 <= EMISSIVITY <= 1:  # 判斷本行條件，成立時執行下方處理
        raise ValueError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
            "放射率必須介於 0 至 1"  # 接續本段欄位名稱、提示訊息或報表文字
        )  # 結束本段參數、容器或條件的組合

    # 檢查使用者指定的固態與液態雷射吸收率
    for name, alpha in (("固態吸收率", SOLID_LASER_ABSORPTIVITY),  # 檢查使用者指定的固態吸收率
                        ("液態吸收率", LIQUID_LASER_ABSORPTIVITY)):  # 同樣檢查液態吸收率
        if not math.isfinite(alpha) or not 0.0 <= alpha <= 1.0:  # 吸收率須為有限值且介於零至一
            raise ValueError(f"{name}必須為 0 至 1 的有限值")  # 避免無效吸收率造成熱源能量異常
    # 檢查金屬填充率門檻
    if not 0 < MINIMUM_ACTIVE_METAL_FILL <= 1:  # 判斷本行條件，成立時執行下方處理
        raise ValueError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
            "金屬填充率門檻必須介於 0 至 1"  # 接續本段欄位名稱、提示訊息或報表文字
        )  # 結束本段參數、容器或條件的組合


    # 若表面張力溫度係數已設定，檢查其有限性
    if SURFACE_TENSION_TEMP_COEFF_N_M_K is not None:  # 判斷本行條件，成立時執行下方處理
        dsigma = SURFACE_TENSION_TEMP_COEFF_N_M_K  # 計算或建立變數 dsigma
        if not math.isfinite(dsigma):  # 判斷本行條件，成立時執行下方處理
            raise ValueError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
                "表面張力溫度係數必須為有限數值"  # 接續本段欄位名稱、提示訊息或報表文字
            )  # 結束本段參數、容器或條件的組合

    return True  # 回傳本行計算結果，交由呼叫端繼續使用

if __name__ == "__main__":  # 只有直接執行本檔時才啟動以下流程

    validate_material_properties()  # 檢查材料物性

    print("[PASS] Ti64 材料係數基本檢查通過")  # 輸出本階段的數值、進度或診斷訊息

    print("\n[A] 密度")  # 輸出本階段的數值、進度或診斷訊息
    print("固態密度 =", SOLID_DENSITY_KG_M3, "kg/m³")  # 輸出本階段的數值、進度或診斷訊息

    print("\n[B] 比熱容")  # 輸出本階段的數值、進度或診斷訊息
    print("固態比熱 =", SOLID_SPECIFIC_HEAT_J_KG_K)  # 輸出本階段的數值、進度或診斷訊息
    print("液態比熱 =", LIQUID_SPECIFIC_HEAT_J_KG_K)  # 輸出本階段的數值、進度或診斷訊息

    print("\n[C] 熱傳導")  # 輸出本階段的數值、進度或診斷訊息
    print("固態導熱 =", SOLID_CONDUCTIVITY_W_M_K)  # 輸出本階段的數值、進度或診斷訊息
    print("液態導熱 =", LIQUID_CONDUCTIVITY_W_M_K)  # 輸出本階段的數值、進度或診斷訊息

    print("\n[D] 相變")  # 輸出本階段的數值、進度或診斷訊息
    print("固相線 =", SOLIDUS_TEMPERATURE_K, "K")  # 輸出本階段的數值、進度或診斷訊息
    print("液相線 =", LIQUIDUS_TEMPERATURE_K, "K")  # 輸出本階段的數值、進度或診斷訊息
    print("熔化潛熱 =", LATENT_HEAT_J_KG, "J/kg")  # 輸出本階段的數值、進度或診斷訊息

    print("\n[E] 汽化")  # 輸出本階段的數值、進度或診斷訊息
    print("沸點 =", BOILING_TEMPERATURE_K, "K")  # 輸出本階段的數值、進度或診斷訊息
    print("汽化潛熱 =",  # 輸出本階段的數值、進度或診斷訊息
          LATENT_HEAT_VAPORIZATION_J_KG, "J/kg")  # 輸出本階段的數值、進度或診斷訊息
    print("莫耳質量 =", MOLAR_MASS_KG_MOL, "kg/mol")  # 輸出本階段的數值、進度或診斷訊息

    print("\n[F] 表面性質")  # 輸出本階段的數值、進度或診斷訊息
    print("表面張力 =", SURFACE_TENSION_N_M, "N/m")  # 輸出本階段的數值、進度或診斷訊息
    print("表面張力溫度係數 =",  # 輸出本階段的數值、進度或診斷訊息
          SURFACE_TENSION_TEMP_COEFF_N_M_K)  # 輸出本階段的數值、進度或診斷訊息
    
