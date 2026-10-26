# -*- coding: utf-8 -*-
"""05｜金屬＋保護氣體 Voxel 總焓與固液相變模組。
計算流程：溫度→總體積焓→導熱更新→反算溫度→金屬液相率／相態→熔深。
假設：各 Voxel 內金屬與氣體局部熱平衡、固定密度，這裡不求解氣體流動。
蒸發質量與熱損失由主程式更新；本模組負責溫度、焓、固液相變及相變能量分解。
氣體物性必須在 01 模組宣告；金屬熔化潛熱仍由 01 讀取。
此處氣體專指採用 01 氬氣物性的保護氣體背景，不是獨立的金屬蒸氣場。
金屬蒸發量由主程式累積；本模組不追蹤蒸氣的密度、溫度、輸運與凝結。
"""
from importlib import import_module  # 載入數字開頭的材料模組
import numpy as np  # 支援 NumPy 預設後端與小網格測試
material = import_module('01_Material Parameters_材料參數')  # 物性唯一來源

# ============================================================================
# 函式大綱｜metal_specific_energy_components() — 分解金屬比顯熱與熔化比潛熱
# 【輸入】絕對溫度場（K）；NumPy／CuPy 運算後端 xp
# 【計算】以液相線分段比熱積分顯熱，再以線性液相率求熔化潛熱
# 【輸出】每公斤剩餘金屬的顯熱與潛熱存量，不是累計熔化耗能
# ============================================================================
def metal_specific_energy_components(temperature_K, xp=np):  # 定義函式：分解金屬比顯熱與熔化比潛熱
    """分解金屬比顯熱與熔化比潛熱。
    計算：以液相線分段比熱積分顯熱，再以線性液相率求熔化潛熱。
    輸出：每公斤剩餘金屬的顯熱與潛熱存量，不是累計熔化耗能。
    """
    Ts = material.SOLIDUS_TEMPERATURE_K  # 計算或建立固相線溫度
    Tl = material.LIQUIDUS_TEMPERATURE_K  # 計算或建立液相線溫度
    cs = material.SOLID_SPECIFIC_HEAT_J_KG_K  # 計算或建立固態比熱
    cl = material.LIQUID_SPECIFIC_HEAT_J_KG_K  # 計算或建立液態比熱
    sensible = (cs * (xp.minimum(temperature_K, Tl) - 293.15) +  # 金屬升溫至液相線的比顯熱（J/kg）；不包含氣體
                cl * xp.maximum(temperature_K - Tl, 0.0))  # 加入液相線以上的液態金屬升溫比顯熱（J/kg）
    latent = material.LATENT_HEAT_J_KG * xp.clip(  # 熔化比潛熱乘液相率，得到目前金屬比潛熱存量（J/kg）
        (temperature_K - Ts) / (Tl - Ts), 0.0, 1.0)  # 固相線以下為零、液相線以上為完整熔化比潛熱
    return sensible, latent  # 回傳本行計算結果，交由呼叫端繼續使用


# ============================================================================
# 函式大綱｜specific_enthalpy_from_temperature() — 由金屬溫度求總比焓
# 【輸入】絕對溫度場（K）；NumPy／CuPy 運算後端 xp
# 【計算】將共用來源的比顯熱與熔化比潛熱相加，以 293.15 K 為零點
# 【輸出】金屬比焓，單位 J/kg
# ============================================================================
def specific_enthalpy_from_temperature(temperature_K, xp=np):  # 定義函式：由金屬溫度求總比焓
    """以 293.15 K 為零焓點；與輸出的顯熱、熔化潛熱共用計算來源。"""  # 接續本段欄位名稱、提示訊息或報表文字
    sensible, latent = metal_specific_energy_components(temperature_K, xp)  # 取得金屬比顯熱與熔化比潛熱（均為 J/kg），包含液態升溫
    return sensible + latent  # 回傳本行計算結果，交由呼叫端繼續使用

# ============================================================================
# 函式大綱｜energy_components_from_temperature() — 分解金屬與氣體儲存能量
# 【輸入】絕對溫度場（K）；金屬填充率陣列；NumPy／CuPy 運算後端 xp
# 【計算】以填充率換算金屬及氣體質量密度，分列顯熱與熔化潛熱
# 【輸出】金屬顯熱、金屬潛熱、氣體顯熱的體積密度字典
# ============================================================================
def energy_components_from_temperature(temperature_K, metal_fill_fraction, xp=np, split_sensible_phases=False):  # 可選擇分列固態與液態金屬顯熱
    """分解金屬與氣體儲存能量。
    計算：以填充率換算金屬及氣體質量密度，分列顯熱與熔化潛熱。
    輸出：金屬顯熱、金屬潛熱、氣體顯熱的體積密度字典。
    """
    T = temperature_K  # 計算或建立溫度 T（K）
    F = xp.clip(metal_fill_fraction, 0.0, 1.0)  # 計算或建立金屬填充率 F
    Tref = 293.15  # 計算或建立零焓參考溫度
    metal_sensible_specific, metal_latent_specific = metal_specific_energy_components(T, xp)  # 計算或建立金屬比顯熱、金屬比熔化潛熱
    metal_mass_density = F * material.SOLID_DENSITY_KG_M3  # 以金屬填充率乘固態參考密度，得到每單位網格體積的金屬質量
    metal_sensible = metal_mass_density * metal_sensible_specific  # 金屬質量密度乘比顯熱，換成金屬體積顯熱（J/m³）
    metal_latent = metal_mass_density * metal_latent_specific  # 金屬質量密度乘比潛熱，換成金屬體積熔化潛熱（J/m³）
    gas_sensible = ((1.0 - F) * material.GAS_DENSITY_KG_M3  # 以剩餘氣體體積、氣體密度、比熱與溫差求氣體體積顯熱
                    * material.GAS_SPECIFIC_HEAT_J_KG_K * (T - Tref))  # 接續氣體體積顯熱的數值、運算式或資料項目
    components = dict(metal_sensible_J_m3=metal_sensible,  # 金屬總顯熱仍保留供總焓檢查使用
                metal_latent_J_m3=metal_latent,  # 接續本段運算：金屬體積熔化潛熱
                gas_sensible_J_m3=gas_sensible)  # 接續本段運算：氣體體積顯熱
    if split_sensible_phases:  # 只在輸出需要分相顯熱時建立額外欄位
        fraction = liquid_fraction_from_temperature(T, xp)  # 固液共存網格依連續液相率分配目前金屬顯熱
        components['metal_solid_sensible_J_m3'] = metal_sensible * (1.0 - fraction)  # 固態份額含共存區的固相部分
        components['metal_liquid_sensible_J_m3'] = metal_sensible * fraction  # 液態份額含共存區的液相部分
    return components  # 預設仍回傳原三項；分相輸出時另外提供兩項可加總的顯熱


# ============================================================================
# 函式大綱｜total_enthalpy_from_temperature() — 由溫度計算混合體積焓
# 【輸入】絕對溫度場（K）；金屬填充率陣列；NumPy／CuPy 運算後端 xp
# 【計算】將金屬總比焓與氣體顯熱各自乘質量密度後相加
# 【輸出】三維金屬加氣體的總體積焓，單位 J/m³
# ============================================================================
def total_enthalpy_from_temperature(temperature_K, metal_fill_fraction, xp=np):  # 新增相容的混合焓工具
    """由溫度計算混合體積焓。
    計算：將金屬總比焓與氣體顯熱各自乘質量密度後相加。
    輸出：三維金屬加氣體的總體積焓，單位 J/m³。
    """
    F = xp.clip(metal_fill_fraction, 0.0, 1.0)  # 限制填充率範圍
    components = energy_components_from_temperature(temperature_K, F, xp)  # 總焓與報表共用材料密度、比熱及潛熱計算來源
    return components['metal_sensible_J_m3'] + components['metal_latent_J_m3'] + components['gas_sensible_J_m3']  # 三個互斥能量分項加總為體積焓

# ============================================================================
# 函式大綱｜temperature_from_enthalpy() — 由總體積焓反算溫度
# 【輸入】體積焓場（J/m³）；金屬填充率陣列；NumPy／CuPy 運算後端 xp
# 【計算】建立固態、固液共存與液態的焓界限，逐段解析反算
# 【輸出】局部熱平衡溫度；純氣體也保留熱容量並參與升溫
# ============================================================================
def temperature_from_enthalpy(enthalpy_J_m3, metal_fill_fraction, xp=np):  # 保留主程式原本呼叫格式
    """分段線性混合焓解析反算；所有 Voxel 均有正熱容量。"""  # 說明逆變換
    F = xp.clip(metal_fill_fraction, 0.0, 1.0)  # 金屬佔有體積比例
    mg = (1.0 - F) * material.GAS_DENSITY_KG_M3  # 氣體質量每單位總體積
    mm = F * material.SOLID_DENSITY_KG_M3  # 金屬質量每單位總體積
    Cgas = mg * material.GAS_SPECIFIC_HEAT_J_KG_K  # 氣體體積熱容量
    Cs = mm * material.SOLID_SPECIFIC_HEAT_J_KG_K + Cgas  # 固態金屬＋氣體體積熱容量
    Cm = Cs + mm * material.LATENT_HEAT_J_KG / (material.LIQUIDUS_TEMPERATURE_K - material.SOLIDUS_TEMPERATURE_K)  # 共存區熱容
    Cl = mm * material.LIQUID_SPECIFIC_HEAT_J_KG_K + Cgas  # 液態金屬＋氣體體積熱容量
    Hs = Cs * (material.SOLIDUS_TEMPERATURE_K - 293.15)  # 固相線混合焓
    Hl = Hs + Cm * (material.LIQUIDUS_TEMPERATURE_K - material.SOLIDUS_TEMPERATURE_K)  # 液相線混合焓
    Tsolid = 293.15 + enthalpy_J_m3 / Cs  # 固態區或純氣體升溫
    Tmushy = material.SOLIDUS_TEMPERATURE_K + (enthalpy_J_m3 - Hs) / Cm  # 相變共存區升溫
    Tliquid = material.LIQUIDUS_TEMPERATURE_K + (enthalpy_J_m3 - Hl) / Cl  # 完全熔化後升溫
    return xp.where(enthalpy_J_m3 <= Hs, Tsolid, xp.where(enthalpy_J_m3 < Hl, Tmushy, Tliquid))  # 返回所有 Voxel 的溫度

# ============================================================================
# 函式大綱｜liquid_fraction_from_temperature() — 由溫度計算液相率
# 【輸入】絕對溫度場（K）；NumPy／CuPy 運算後端 xp
# 【計算】在固相線與液相線之間線性插值，並限制於零到一
# 【輸出】無因次液相率陣列
# ============================================================================
def liquid_fraction_from_temperature(temperature_K, xp=np):  # 維持原始介面
    return xp.clip((temperature_K - material.SOLIDUS_TEMPERATURE_K) / (material.LIQUIDUS_TEMPERATURE_K - material.SOLIDUS_TEMPERATURE_K), 0.0, 1.0)  # 線性液相率


# ============================================================================
# 函式大綱｜phase_change_energy_increments() — 分列單步相變能量
# 【輸入】原金屬填充率；熱更新前液相率；蒸發前預測液相率；剩餘金屬填充率；蒸發後液相率；單一網格體積（m³）
# 【續輸入】NumPy／CuPy 運算後端 xp
# 【計算】依加熱、移除金屬及剩餘材料降溫的分步路徑計算吸收與釋放
# 【輸出】熔化吸收、凝固釋放、汽化潛熱及蒸發攜出熔化潛熱；不含冷凝
# ============================================================================
def phase_change_energy_increments(F_before, fraction_before, fraction_predicted,  # 定義函式：分列單步相變能量
                                    F_after, fraction_after, voxel_volume_m3, xp=np):  # 接續函式參數：剩餘金屬填充率、蒸發後液相率、單一網格體積（m³）、NumPy／CuPy 運算後端 xp
    """分列單步相變能量。
    計算：依加熱、移除金屬及剩餘材料降溫的分步路徑計算吸收與釋放。
    輸出：熔化吸收、凝固釋放、汽化潛熱及蒸發攜出熔化潛熱；不含冷凝。
    """
    if voxel_volume_m3 <= 0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError('voxel_volume_m3 must be positive')  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    scale = material.SOLID_DENSITY_KG_M3 * material.LATENT_HEAT_J_KG * voxel_volume_m3  # 計算或建立變數 scale
    before_delta = fraction_predicted - fraction_before  # 計算原金屬加熱到蒸發前預測狀態時的液相率變化
    after_delta = fraction_after - fraction_predicted  # 計算蒸發移除質量後，剩餘金屬的液相率變化
    melting = xp.sum(F_before * xp.maximum(before_delta, 0.0) +  # 分別累計蒸發前及蒸發後液相率的增加量，換算熔化吸收能量
                     F_after * xp.maximum(after_delta, 0.0)) * scale  # 接續變數 melting的數值、運算式或資料項目
    freezing = xp.sum(F_before * xp.maximum(-before_delta, 0.0) +  # 分別累計蒸發前及蒸發後液相率的下降量，換算凝固釋放能量
                      F_after * xp.maximum(-after_delta, 0.0)) * scale  # 接續變數 freezing的數值、運算式或資料項目
    removed_fill = xp.maximum(F_before - F_after, 0.0)  # 只取金屬填充率減少的部分，作為蒸發移除量
    vaporization = xp.sum(removed_fill) * (material.SOLID_DENSITY_KG_M3 *  # 移除金屬質量乘汽化潛熱，得到液轉氣的潛熱吸收（J）
                                          material.LATENT_HEAT_VAPORIZATION_J_KG * voxel_volume_m3)  # 接續變數 vaporization的數值、運算式或資料項目
    carried_fusion = xp.sum(removed_fill * fraction_predicted) * scale  # 移除的金屬量乘蒸發前液相率與熔化潛熱，避免把蒸發誤算為凝固
    return melting, freezing, vaporization, carried_fusion  # 回傳本行計算結果，交由呼叫端繼續使用

# ============================================================================
# 函式大綱｜update_enthalpy_phase() — 更新體積焓、溫度與相態
# 【輸入】體積焓場（J/m³）；金屬填充率陣列；淨熱源（W/m³）；時間（time_step_s）；歷史熔化遮罩；NumPy／CuPy 運算後端 xp
# 【計算】積分淨熱源、反算溫度、更新有效金屬液相率與歷史熔化標記
# 【輸出】焓、溫度、液相率、相態及曾熔化遮罩的字典
# ============================================================================
def update_enthalpy_phase(enthalpy_J_m3, metal_fill_fraction, net_power_W_m3, time_step_s, ever_melted_mask=None, xp=np):  # 主程式呼叫介面不變
    """氣體不再丟棄導熱能量；僅金屬發生熔化及再凝固。"""  # 定義守恆與相變範圍
    if enthalpy_J_m3.shape != metal_fill_fraction.shape or enthalpy_J_m3.shape != net_power_W_m3.shape:  # 檢查陣列形狀
        raise ValueError('H、F、net_power 形狀必須相同')  # 中止錯誤資料
    if time_step_s <= 0:  # 檢查時間步長
        raise ValueError('時間步長必須大於零')  # 中止無效設定
    active = metal_fill_fraction >= material.MINIMUM_ACTIVE_METAL_FILL  # 定義有效金屬範圍
    new_H = enthalpy_J_m3 + time_step_s * net_power_W_m3  # 金屬與氣體都儲存熱量，保持導熱守恆
    T = temperature_from_enthalpy(new_H, metal_fill_fraction, xp)  # 混合總焓反算溫度
    fL = xp.where(active, liquid_fraction_from_temperature(T, xp), 0.0)  # 氣體相態不熔化
    ever = xp.zeros_like(active) if ever_melted_mask is None else ever_melted_mask.copy()  # 保存歷史熔化
    ever |= active & (fL > 0.0)  # 任一相變即標記歷史
    codes = xp.where(~active, 0, xp.where(fL >= 0.99, 3, xp.where(fL > 0.0, 2, xp.where(ever, 4, 1)))).astype(xp.uint8)  # 原相態 0～4
    return dict(enthalpy_J_m3=new_H, temperature_K=T, liquid_fraction=fL, phase=codes, ever_melted_mask=ever)  # 回傳主程式需要的欄位

# ============================================================================
# 函式大綱｜calculate_substrate_melt_depths() — 計算基板內的熔化深度
# 【輸入】金屬填充率陣列；液相率陣列；歷史熔化遮罩；基板頂面 Z 索引；網格邊長（µm）；NumPy／CuPy 運算後端 xp
# 【計算】在基板範圍分別搜尋固液共存、完全液態與歷史熔化的最低高度
# 【輸出】各種定義的基板熔深，單位 µm
# ============================================================================
def calculate_substrate_melt_depths(metal_fill_fraction, liquid_fraction, ever_melted_mask, substrate_top_index, voxel_size_um, xp=np):  # 主程式原本介面
    """尋找基板內最低發生固液相變的 Z 索引；不指定固定熔深。"""  # 熔深定義
    metal = metal_fill_fraction >= material.MINIMUM_ACTIVE_METAL_FILL  # 金屬有效遮罩
    substrate = xp.arange(metal_fill_fraction.shape[2])[None, None, :] < substrate_top_index  # 辨識基板 Z 區域
    # ============================================================================
    # 函式大綱｜depth() — 將基板相態遮罩換算為熔深
    # 【輸入】有效網格遮罩
    # 【計算】搜尋遮罩中最低 Z 索引，與基板頂面相減並乘網格尺寸
    # 【輸出】熔深；沒有符合的金屬網格時回傳零
    # ============================================================================
    def depth(mask):  # 尋找滿足條件的最低 Z 位置
        z = xp.nonzero(mask)[2]  # 取得符合條件的 Z 索引
        if z.size == 0:  # 若完全沒有熔化
            return 0.0  # 熔深為零
        zmin = z.min()  # 基板內最深的 Z
        zmin = int(zmin.item())  # NumPy 或 CuPy scalar 轉為 Python 整數
        return (substrate_top_index - zmin) * voxel_size_um  # 換算為 Voxel 尺度的深度 µm
    return dict(Dsub_mushy_um=depth(substrate & metal & (liquid_fraction > 0)), Dsub_liquid_um=depth(substrate & metal & (liquid_fraction >= 0.99)), Dsub_ever_um=depth(substrate & ever_melted_mask))  # 歷史熔深保留曾熔化位置，即使該位置之後蒸發也不回退

# ============================================================================
# 函式大綱｜verify_phase_module() — 驗證混合焓與固液相變
# 【輸入】無外部參數；讀取本檔或相關模組設定
# 【計算】檢查焓溫正反算、氣體升溫、液態分類與再凝固歷史
# 【輸出】通過訊息及 True；失敗時拋出斷言例外
# ============================================================================
def verify_phase_module():  # 獨立單元測試入口
    material.validate_material_properties()  # 驗證金屬物性
    F = np.array([0.0, 0.3, 1.0], dtype=float).reshape(3, 1, 1)  # 三種填充狀態
    T = np.array([800.0, (material.SOLIDUS_TEMPERATURE_K + material.LIQUIDUS_TEMPERATURE_K) / 2.0, material.LIQUIDUS_TEMPERATURE_K + 300.0], dtype=float).reshape(3, 1, 1)  # 測試溫度跟隨材料相變區間
    H = total_enthalpy_from_temperature(T, F)  # 將三種溫度轉為總體積焓
    assert np.allclose(temperature_from_enthalpy(H, F), T, atol=1e-8), '混合焓正反算不一致'  # 驗證焓模型
    H0 = np.zeros((1, 1, 1))  # 純氣體初始零焓
    F0 = np.zeros_like(H0)  # 純氣體佔有率
    Q = np.full_like(H0, 1e10)  # 氣體加熱功率密度
    state = update_enthalpy_phase(H0, F0, Q, 1e-9)  # 積分氣體焓變化
    assert np.isclose(state['enthalpy_J_m3'][0, 0, 0], 10.0), '氣體熱量丟失'  # 確認能量積分
    assert state['temperature_K'][0, 0, 0] > 293.15, '純氣體沒有升溫'  # 驗證氣體熱容量
    assert state['phase'][0, 0, 0] == 0, '氣體相態編碼改變'  # Viewer 仍將氣體標為 0
    solid_F = np.ones((2, 2, 2))  # 全金屬相變測試網格
    hot_H = total_enthalpy_from_temperature(np.full_like(solid_F, material.LIQUIDUS_TEMPERATURE_K + 100.0), solid_F)  # 使用高於當前液相線的溫度測試熔化
    hot = update_enthalpy_phase(hot_H, solid_F, np.zeros_like(solid_F), 1e-9)  # 檢查完全液態
    assert np.all(hot['phase'] == 3), '液態分類錯誤'  # 高於液相線皆為液態
    cool_H = total_enthalpy_from_temperature(np.full_like(solid_F, 800.0), solid_F)  # 冷卻後比焓
    cool = update_enthalpy_phase(cool_H, solid_F, np.zeros_like(solid_F), 1e-9, hot['ever_melted_mask'])  # 測試再凝固
    assert np.all(cool['phase'] == 4), '凝固歷史分類錯誤'  # 確認再凝固標記
    print('[PASS] 05 金屬＋氣體混合焓、液相率、再凝固、熱量守恆')  # 顯示檢查通過
    return True  # 測試結束

if __name__ == '__main__':  # 單獨執行時進行單元測試
    verify_phase_module()  # 不啟動正式 LPBF 模擬
