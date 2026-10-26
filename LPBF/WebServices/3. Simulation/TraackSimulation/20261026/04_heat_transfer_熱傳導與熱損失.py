# -*- coding: utf-8 -*-
"""
==============================================================================
04｜XYZ 熱傳導與熱損失（Heat Transfer & Heat Loss）
==============================================================================

【一、計算大綱】
01. 接收主程式的 3D 溫度 T、金屬填充率 F、液相率 fL 與 Voxel 尺寸
02. 從 01_Material Parameters_材料參數.py 取得固／液熱導率、放射率、σ
03. 以相鄰金屬 Voxel 的界面通量計算 XYZ 熱傳導（內部能量轉移）
04. 以金屬與空隙的交界面估算暴露表面積
05. 計算環境對流熱損失
06. 計算表面輻射熱損失
07. 計算模型 Z=0 底部熱損失
08. 回傳四個分項 W/m³、各自總功率 W 與守恆審計量

【二、架構與職責】
- 此檔只有函式，不包含正式 LPBF 時間迴圈、不讀取粉末檔。
- 不自行宣告 Ti64 的物性常數；由 01 模組統一管理。
- h_ambient、h_bottom、T_ambient 由主程式傳入（02 管理邊界條件）。
- 第 03 支的雷射吸收功率密度由主程式另行相加。
- 第 05 支負責焓與溫度、相變；本檔不直接修改 H/T/fL。
- 包含簡化 Hertz-Knudsen 蒸發熱損失估算；不更新蒸發質量，亦不含氣體流動、熔池流動或粉末接觸熱阻。

【三、單位】
T [K]；F、fL [-]；dx [m]；k [W/(m·K)]；h [W/(m²·K)]
各 rate [W/m³]；功率 [W]；體積焓 H [J/m³]；時間 dt [s]

【四、物理提醒】
- 金屬內部相鄰 Voxel 的導熱通量成對加減，總和應為 0。
- 表面對流與輻射屬於真正的外部熱損失，雷射加熱時同樣存在。
- 空 Voxel 代表填充保護氣體，05 必須同步儲存氣體顯熱。
- 這是有限體積簡化模型；不宣稱已經實驗驗證。
==============================================================================
"""
from importlib import import_module  # 依檔名動態載入模組（檔名前面有數字及中文）
import math  # 檢查熱穩定步長所用參數是否為有限值
import numpy as np                    # CPU 測試時使用的陣列後端

MATERIAL_MODULE_NAME = "01_Material Parameters_材料參數"  # 材料參數唯一來源
EVAPORATION_ACCOMMODATION = 0.20  # 簡化 Hertz-Knudsen 蒸發係數；後續需依材料資料校正
EVAPORATION_BACK_PRESSURE_PA = 0.0  # 假設表面附近 Ti64 蒸氣分壓可忽略


# ============================================================================
# 函式大綱｜_material() — 取得統一材料模組
# 【輸入】無外部參數；讀取本檔或相關模組設定
# 【計算】依模組名稱載入 01，避免在熱傳模組重複定義物性
# 【輸出】材料模組物件
# ============================================================================
def _material():  # 定義函式：取得統一材料模組
    """延遲載入 01 材料模組，並供 04 的所有計算函式共用。"""  # 接續本段欄位名稱、提示訊息或報表文字
    return import_module(MATERIAL_MODULE_NAME)  # 回傳本行計算結果，交由呼叫端繼續使用


# ============================================================================
# 函式大綱｜_adjacent_slices() — 建立相鄰網格切片
# 【輸入】陣列軸向
# 【計算】沿指定軸取得左側與右側相鄰儲存格的切片範圍
# 【輸出】兩組可直接索引三維陣列的切片
# ============================================================================
def _adjacent_slices(axis):  # 定義函式：建立相鄰網格切片
    """取得 XYZ 指定方向上，一對相鄰的 Voxel 索引切片。"""  # 接續本段欄位名稱、提示訊息或報表文字
    left = [slice(None)] * 3                 # 先選取三個方向的全部格點
    right = [slice(None)] * 3                # 建立相鄰格點的第二組切片
    left[axis] = slice(None, -1)             # 左側 / 下方 Voxel
    right[axis] = slice(1, None)             # 右側 / 上方 Voxel
    return tuple(left), tuple(right)         # 回傳可以直接用於 NumPy/CuPy 的索引


# ============================================================================
# 函式大綱｜calculate_conductivity() — 計算金屬與氣體的有效導熱率
# 【輸入】絕對溫度場（K）；液相率陣列；金屬填充率陣列；NumPy／CuPy 運算後端 xp；指定氣體導熱率（W/m/K）
# 【計算】以液相率混合固液金屬導熱率，再以金屬填充率混合氣體導熱率
# 【輸出】局部有效導熱率陣列；採平行混合近似，未校正粉末接觸熱阻
# ============================================================================
def calculate_conductivity(temperature_K, liquid_fraction, metal_fill_fraction, xp, gas_k=None):  # 計算氣體與金屬混合導熱率
    """第一階段 Voigt 平行混合近似；實際粉末接觸熱阻尚未校正。"""  # 說明模型限制
    mat = _material()  # 讀取唯一材料資料庫
    if liquid_fraction is None:  # 若主程式尚無液相率
        liquid_fraction = xp.clip((temperature_K - mat.SOLIDUS_TEMPERATURE_K) / (mat.LIQUIDUS_TEMPERATURE_K - mat.SOLIDUS_TEMPERATURE_K), 0.0, 1.0)  # 由溫度估算液相率
    F = xp.clip(metal_fill_fraction, 0.0, 1.0)  # 將 Voxel 填充率限制在合理範圍
    k_metal = mat.SOLID_CONDUCTIVITY_W_M_K + (mat.LIQUID_CONDUCTIVITY_W_M_K - mat.SOLID_CONDUCTIVITY_W_M_K) * xp.clip(liquid_fraction, 0.0, 1.0)  # 金屬固液線性插值
    return F * k_metal + (1.0 - F) * (mat.GAS_CONDUCTIVITY_W_M_K if gas_k is None else gas_k)  # 空 Voxel 仍具有氣體導熱率


# ============================================================================
# 函式大綱｜calculate_xyz_conduction() — 計算三方向內部導熱
# 【輸入】絕對溫度場（K）；金屬填充率陣列；網格邊長（m）；NumPy／CuPy 運算後端 xp；液相率陣列；指定氣體導熱率（W/m/K）
# 【計算】使用調和平均面導熱率計算相鄰通量，對兩側網格成對加減
# 【輸出】各網格淨導熱功率密度；封閉域內總和應接近零
# ============================================================================
def calculate_xyz_conduction(temperature_K, metal_fill_fraction, voxel_size_m, xp=np, liquid_fraction=None, gas_k=None):  # 計算全域多相三維導熱
    """金屬、氣體皆導熱；內部界面熱通量成對更新，守恆總體積焓。"""  # 模型說明
    if voxel_size_m <= 0:  # 驗證網格尺寸
        raise ValueError("voxel_size_m 必須大於零")  # 阻止無效網格
    k = calculate_conductivity(temperature_K, liquid_fraction, metal_fill_fraction, xp, gas_k)  # 計算各格等效導熱率
    q_cond = xp.zeros_like(temperature_K, dtype=xp.float64)  # 建立每格體積導熱功率密度 W/m³
    for axis in range(3):  # X、Y、Z 依次傳熱
        a, b = _adjacent_slices(axis)  # 取得共用面的左右相鄰格
        k_face = 2.0 * k[a] * k[b] / xp.maximum(k[a] + k[b], 1e-30)  # 調和平均面導熱率
        face_q = k_face * (temperature_K[b] - temperature_K[a]) / voxel_size_m**2  # 左格流入功率密度
        q_cond[a] += face_q  # 左格獲取熱量
        q_cond[b] -= face_q  # 右格失去相同熱量，確保守恆
    return q_cond  # 回傳全域三維導熱源項


# ============================================================================
# 函式大綱｜calculate_thermal_stable_dt() — 估算金屬、氣體與邊界共同的安全顯式步長
# 【輸入】網格邊長、氣體導熱率、對流與底部係數、溫度診斷上限
# 【計算】以最小熱容量與調和平均面係數上界估計六面導熱，再加入邊界散熱斜率
# 【輸出】含 0.8 安全係數的時間步上限（s），適用於不同填充率及固液狀態
# ============================================================================
def calculate_thermal_stable_dt(voxel_size_m, gas_k=None, ambient_h_W_m2_K=0.0,  # 定義熱傳顯式更新的安全步長
                                 bottom_h_W_m2_K=0.0, max_temperature_K=10000.0):  # 用診斷溫度上限限制輻射項斜率
    """面調和平均係數不超過本格導熱率兩倍，六面流出率以 12*k/C/dx² 為上界。
    混合物 k/C 不超過金屬、氣體端點最大值；固液共存的潛熱只會增加熱容量。
    邊界面積係數不超過 6F，混合熱容量不小於 F*rho*min(cp)。
    此界限處理導熱與邊界散熱，不取代顯式蒸發的時間步收斂驗證。
    """
    mat = _material()  # 所有物性仍統一由 01 管理
    gas_k = mat.GAS_CONDUCTIVITY_W_M_K if gas_k is None else gas_k  # 使用實際氣體導熱率
    parameters = (voxel_size_m, gas_k, ambient_h_W_m2_K, bottom_h_W_m2_K, max_temperature_K)  # 收集步長估計參數
    if not all(math.isfinite(value) for value in parameters):  # 非有限值無法估計安全步長
        raise ValueError('Thermal stability parameters must be finite')  # 提早指出無效參數
    if voxel_size_m <= 0 or max_temperature_K <= 0 or min(parameters[1:4]) < 0:  # 檢查長度、溫度及非負導熱／換熱係數
        raise ValueError('Invalid grid size, temperature or thermal coefficient')  # 拒絕不合法的熱傳設定
    metal_capacity = mat.SOLID_DENSITY_KG_M3 * min(mat.SOLID_SPECIFIC_HEAT_J_KG_K, mat.LIQUID_SPECIFIC_HEAT_J_KG_K)  # 固液兩相較小的體積熱容量
    gas_capacity = mat.GAS_DENSITY_KG_M3 * mat.GAS_SPECIFIC_HEAT_J_KG_K  # 低熱容量氣體也須納入限制
    diffusivity_bound = max(max(mat.SOLID_CONDUCTIVITY_W_M_K, mat.LIQUID_CONDUCTIVITY_W_M_K) / metal_capacity,  # 金屬擴散率上界
                            gas_k / gas_capacity)  # 與氣體擴散率比較取較大值
    conduction_rate = 12.0 * diffusivity_bound / voxel_size_m**2  # 六面導熱流出率上界
    radiation_slope = 4.0 * mat.EMISSIVITY * mat.STEFAN_BOLTZMANN_CONSTANT * max_temperature_K**3  # 診斷溫度範圍內的最大輻射斜率
    boundary_rate = (6.0 * (ambient_h_W_m2_K + radiation_slope) + bottom_h_W_m2_K) / (metal_capacity * voxel_size_m)  # 對流、輻射及底部散熱的附加限制
    return 0.8 / (conduction_rate + boundary_rate)  # 加入安全係數並回傳秒為單位的上限


# ============================================================================
# 函式大綱｜calculate_substrate_interface_power() — 計算粉末與基板的界面導熱
# 【輸入】絕對溫度場（K）；金屬填充率陣列；基板頂面 Z 索引；網格邊長（m）；NumPy／CuPy 運算後端 xp；液相率陣列
# 【續輸入】指定氣體導熱率（W/m/K）
# 【計算】只取界面兩層，以與 XYZ 求解器一致的面導熱率計算雙向傳熱
# 【輸出】傳入基板與回傳粉末的功率；屬內部轉移，不是全域損失
# ============================================================================
def calculate_substrate_interface_power(temperature_K, metal_fill_fraction,  # 定義函式：計算粉末與基板的界面導熱
                                         substrate_top_index, voxel_size_m, xp=np,  # 接續函式參數：基板頂面 Z 索引、網格邊長（m）、NumPy／CuPy 運算後端 xp
                                         liquid_fraction=None, gas_k=None):  # 接續函式參數：液相率陣列、指定氣體導熱率（W/m/K）
    """計算粉末與基板的界面導熱。
    計算：只取界面兩層，以與 XYZ 求解器一致的面導熱率計算雙向傳熱。
    輸出：傳入基板與回傳粉末的功率；屬內部轉移，不是全域損失。
    """
    if not 0 < substrate_top_index < temperature_K.shape[2] or voxel_size_m <= 0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError('Invalid substrate interface index or voxel size')  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    slab = slice(substrate_top_index - 1, substrate_top_index + 1)  # 計算或建立界面相鄰兩層的切片範圍
    temp = temperature_K[:, :, slab]  # 計算或建立變數 temp
    fill = metal_fill_fraction[:, :, slab]  # 計算或建立填充（fill）
    liquid = None if liquid_fraction is None else liquid_fraction[:, :, slab]  # 計算或建立液態（liquid）
    k = calculate_conductivity(temp, liquid, fill, xp, gas_k)  # 計算或建立局部有效導熱率或 Z 索引
    k_face = 2.0 * k[:, :, 0] * k[:, :, 1] / xp.maximum(k[:, :, 0] + k[:, :, 1], 1e-30)  # 計算或建立相鄰面調和平均導熱率
    face_power = k_face * (temp[:, :, 1] - temp[:, :, 0]) * voxel_size_m  # 面導熱率乘上下層溫差及網格邊長，得到各界面的傳熱功率
    into = xp.sum(xp.maximum(face_power, 0.0))  # 累計粉末較熱時傳入基板的正向面功率
    out = xp.sum(xp.maximum(-face_power, 0.0))  # 累計基板較熱時回傳粉末的反向面功率，數值以正值表示
    return into, out  # 回傳本行計算結果，交由呼叫端繼續使用

# ============================================================================
# 函式大綱｜calculate_gas_facing_face_area() — 計算所有金屬與氣體接觸面
# 【輸入】金屬填充率陣列；NumPy／CuPy 運算後端 xp
# 【計算】累計三方向相鄰填充率形成的暴露面並排除底部外邊界
# 【輸出】包含內部孔隙的面積係數，供對流與輻射近似使用
# ============================================================================
def calculate_gas_facing_face_area(metal_fill_fraction, xp=np):  # 定義函式：計算所有金屬與氣體接觸面
    """計算所有金屬與氣體接觸面。
    計算：累計三方向相鄰填充率形成的暴露面並排除底部外邊界。
    輸出：包含內部孔隙的面積係數，供對流與輻射近似使用。
    """
    f = xp.clip(metal_fill_fraction, 0.0, 1.0)  # 計算或建立限制在零到一的金屬填充率
    area = xp.zeros_like(f, dtype=xp.float64)  # 計算或建立暴露面積或面積係數
    for axis in range(3):  # 依序處理axis，逐項套用下方運算
        left = [slice(None)] * 3  # 計算或建立變數 left
        right = [slice(None)] * 3  # 計算或建立變數 right
        left[axis] = slice(None, -1)  # 計算或建立變數 left的指定網格或切片
        right[axis] = slice(1, None)  # 計算或建立變數 right的指定網格或切片
        a, b = tuple(left), tuple(right)  # 計算或建立變數 a、變數 b
        area[a] += f[a] * (1.0 - f[b])  # 累加至暴露面積或面積係數的指定網格或切片
        area[b] += f[b] * (1.0 - f[a])  # 累加至暴露面積或面積係數的指定網格或切片
        low = [slice(None)] * 3  # 計算或建立變數 low
        high = [slice(None)] * 3  # 計算或建立變數 high
        low[axis] = 0  # 計算或建立變數 low的指定網格或切片
        high[axis] = -1  # 計算或建立變數 high的指定網格或切片
        if axis != 2:  # 判斷本行條件，成立時執行下方處理
            area[tuple(low)] += f[tuple(low)]  # 累加至暴露面積或面積係數的指定網格或切片
        area[tuple(high)] += f[tuple(high)]  # 累加至暴露面積或面積係數的指定網格或切片
    return area  # 回傳本行計算結果，交由呼叫端繼續使用


# ============================================================================
# 函式大綱｜calculate_top_surface_face_area() — 計算與光學遮蔽一致的垂直暴露面
# 【輸入】金屬填充率陣列；NumPy／CuPy 運算後端 xp
# 【計算】逐層累乘上方氣體開放比例，將部分填充上層未遮蔽的面積傳給下層
# 【輸出】各層直接朝上暴露面積／dx²；每柱合計不超過一，不解析側向連通
# ============================================================================
def calculate_top_surface_face_area(metal_fill_fraction, xp=np):  # 定義函式：計算光學可見的垂直暴露面
    """沿用雷射模型的填充率遮蔽近似，分配各層朝上開放面積。
    完整金屬層會遮住下層；部分蒸發後，未覆蓋的比例同時允許雷射與蒸氣通過。
    這是垂直開放面近似，不代表已解析實際孔道或側向氣體輸運。
    """
    mat = _material()  # 計算或建立變數 mat
    f = xp.where(metal_fill_fraction >= mat.MINIMUM_ACTIVE_METAL_FILL,  # 與雷射使用同一有效金屬門檻
                 xp.clip(metal_fill_fraction, 0.0, 1.0), 0.0)  # 無效微量金屬視為開放氣體
    open_fraction = 1.0 - f  # 單層未被金屬遮蔽的面積比例
    open_including_layer = xp.cumprod(open_fraction[:, :, ::-1], axis=2)[:, :, ::-1]  # 從最高 Z 向下累乘開放比例
    open_above = xp.concatenate((open_including_layer[:, :, 1:],  # 下層只取自身上方所有層的開放比例
                                 xp.ones_like(f[:, :, :1])), axis=2)  # 頂部上方完全開放，比例為一
    return f * open_above  # 本層金屬面乘上方開放比例，避免光能進入卻禁止該處蒸發


# ============================================================================
# 函式大綱｜calculate_evaporation_surface_area() — 計算可蒸發的液態表面
# 【輸入】金屬填充率陣列；液相率陣列；NumPy／CuPy 運算後端 xp；蒸發表面近似模型
# 【計算】依選定模型取得垂直開放面或全部氣體接觸面，再篩選有效液態金屬
# 【輸出】液態表面面積係數；頂面模式保守排除被覆蓋孔隙
# ============================================================================
def calculate_evaporation_surface_area(metal_fill_fraction, liquid_fraction=None, xp=np,  # 省略液相率時只回傳幾何暴露面積
                                       surface_model="top"):  # 接續函式參數：蒸發表面近似模型
    """計算可蒸發的液態表面。
    計算：取得垂直開放面或全部氣體接觸面；提供液相率時才篩選液態金屬。
    輸出：面積係數；省略液相率時，呼叫端用同一步預測溫度決定蒸發資格。
    """
    mat = _material()  # 計算或建立變數 mat
    if surface_model == "top":  # 判斷本行條件，成立時執行下方處理
        gas_facing = calculate_top_surface_face_area(metal_fill_fraction, xp)  # 計算或建立氣體（gas_facing）
    elif surface_model == "all-gas-faces":  # 判斷本行條件，成立時執行下方處理
        gas_facing = calculate_gas_facing_face_area(metal_fill_fraction, xp)  # 計算或建立氣體（gas_facing）
    else:  # 前述條件不成立時，改採以下處理方式
        raise ValueError(f"Unknown evaporation surface model: {surface_model}")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    fully_liquid = True if liquid_fraction is None else liquid_fraction >= 0.99  # 幾何模式避免使用前一步液相率遮蔽本步新熔化網格
    active_metal = metal_fill_fraction >= mat.MINIMUM_ACTIVE_METAL_FILL  # 計算或建立金屬（active_metal）
    return xp.where(fully_liquid & active_metal, gas_facing, 0.0)  # 回傳本行計算結果，交由呼叫端繼續使用


# ============================================================================
# 函式大綱｜calculate_heat_transfer_and_loss() — 整合導熱與邊界熱損失
# 【輸入】絕對溫度場（K）；金屬填充率陣列；網格邊長（m）；溫度（ambient_temperature_K）；變數 ambient_h_W_m2_K；底部（bottom_h_W_m2_K）
# 【續輸入】NumPy／CuPy 運算後端 xp；液相率陣列；指定氣體導熱率（W/m/K）；暴露面積係數；表面面積（exposed_surface_area_m2）
# 【計算】計算 XYZ 導熱、對流、輻射與底部散熱，將場量積分為功率
# 【輸出】各熱源／損失場及全域功率；正損失在主程式中扣除
# ============================================================================
def calculate_heat_transfer_and_loss(  # 定義函式：整合導熱與邊界熱損失
        temperature_K, metal_fill_fraction, voxel_size_m, ambient_temperature_K,  # 接續函式參數：絕對溫度場（K）、金屬填充率陣列、網格邊長（m）、溫度（ambient_temperature_K）
        ambient_h_W_m2_K, bottom_h_W_m2_K, xp=np, liquid_fraction=None, gas_k=None,  # 接續函式參數：變數 ambient_h_W_m2_K、底部（bottom_h_W_m2_K）、NumPy／CuPy 運算後端 xp、液相率陣列、指定氣體導熱率（W/m/K）
        exposed_area_factor=None, exposed_surface_area_m2=None):  # 接續函式參數：暴露面積係數、表面面積（exposed_surface_area_m2）
    """
    供未來主程式「每個時間步」呼叫一次。

    回傳 dict：
      conduction_W_m3      XYZ 導熱淨功率密度，可正可負
      convection_loss_W_m3 表面對流散熱，正值表示向外散失
      radiation_loss_W_m3  表面輻射散熱，正值表示向外散失
      bottom_loss_W_m3     Z=0 的底部散熱，正值表示向外散失
      total_loss_W_m3      三項邊界散熱總和
      net_without_laser_W_m3 導熱 - 熱損失（尚未包含雷射熱源）
      power_*_W            將各項 W/m³ 對整個網格積分所得 W

    注意：外界高於金屬溫度時，對流與輻射可為負值（表示環境加熱）。
    """
    mat = _material()                                                   # 固態／液態熱導率及輻射常數統一來自 01
    if temperature_K.ndim != 3 or temperature_K.shape != metal_fill_fraction.shape:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("T 與 F 必須具有相同的 [Nx,Ny,Nz] 三維形狀")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    if voxel_size_m <= 0 or ambient_temperature_K <= 0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("Voxel 尺寸與環境溫度必須為正值")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    if ambient_h_W_m2_K < 0 or bottom_h_W_m2_K < 0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("對流與底部換熱係數不能為負")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    q_cond = calculate_xyz_conduction(temperature_K, metal_fill_fraction,  # 計算或建立各網格淨導熱功率密度
                                    voxel_size_m, xp, liquid_fraction, gas_k)  # X、Y、Z 內部導熱
    area_factor = (calculate_gas_facing_face_area(metal_fill_fraction, xp)  # 計算或建立暴露面積係數
                   if exposed_area_factor is None else exposed_area_factor)  # 所有金屬-氣體界面；目前作為對流／輻射近似面積
    if area_factor.shape != metal_fill_fraction.shape:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("exposed_area_factor shape must match metal_fill_fraction")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    delta_T = temperature_K - ambient_temperature_K                    # 金屬溫度與環境溫差 [K]
    convection = ambient_h_W_m2_K * delta_T * area_factor / voxel_size_m  # 計算或建立對流熱損失
    radiation = (mat.EMISSIVITY * mat.STEFAN_BOLTZMANN_CONSTANT *  # 計算或建立輻射熱損失
                 (temperature_K**4 - ambient_temperature_K**4) *  # 接續輻射熱損失的數值、運算式或資料項目
                 area_factor / voxel_size_m)  # 接續輻射熱損失的數值、運算式或資料項目
    bottom = xp.zeros_like(temperature_K, dtype=xp.float64)           # 只在最低 Z 層加入底部散熱
    f_bottom = xp.where(metal_fill_fraction[:, :, 0] >= mat.MINIMUM_ACTIVE_METAL_FILL,  # 計算或建立底部（f_bottom）
                        xp.clip(metal_fill_fraction[:, :, 0], 0.0, 1.0), 0.0)  # 接續底部（f_bottom）的參數：依布林遮罩選擇對應分支數值
    bottom[:, :, 0] = (bottom_h_W_m2_K *  # 計算或建立底部邊界損失的指定網格或切片
                       (temperature_K[:, :, 0] - ambient_temperature_K) *  # 接續底部邊界損失的指定網格或切片的數值、運算式或資料項目
                       f_bottom / voxel_size_m)                        # 底部 q = h_bottom × ΔT / Δz
    total_loss = convection + radiation + bottom                       # 對外熱損失總和
    volume = voxel_size_m**3                                          # 每個 Voxel 體積 m³
    if exposed_surface_area_m2 is None:  # 判斷本行條件，成立時執行下方處理
        exposed_surface_area_m2 = xp.sum(area_factor) * voxel_size_m**2  # 計算或建立表面面積（exposed_surface_area_m2）
    return {                                                           # 回傳詳細分項，不在此函式更改焓／相態
        "conduction_W_m3": q_cond,  # 設定導熱（conduction_W_m3）欄位的值
        "convection_loss_W_m3": convection,  # 設定對流損失（convection_loss_W_m3）欄位的值
        "radiation_loss_W_m3": radiation,  # 設定輻射損失（radiation_loss_W_m3）欄位的值
        "bottom_loss_W_m3": bottom,  # 設定底部損失（bottom_loss_W_m3）欄位的值
        "total_loss_W_m3": total_loss,  # 設定總計損失（total_loss_W_m3）欄位的值
        "net_without_laser_W_m3": q_cond - total_loss,  # 主程式可直接加上 Qlaser，不可再次扣損失
        "convection_sink_W_m3": -convection,  # 已帶負號的對流源項
        "radiation_sink_W_m3": -radiation,    # 已帶負號的輻射源項
        "bottom_sink_W_m3": -bottom,          # 已帶負號的底部源項
        "power_conduction_sum_W": xp.sum(q_cond) * volume,             # 內部守恆下應接近 0
        "power_convection_loss_W": xp.sum(convection) * volume,         # 整個模型對流失熱功率
        "power_radiation_loss_W": xp.sum(radiation) * volume,           # 整個模型輻射失熱功率
        "power_bottom_loss_W": xp.sum(bottom) * volume,                 # 整個模型底部散熱功率
        "power_total_loss_W": xp.sum(total_loss) * volume,              # 外界熱損失功率
        "exposed_area_factor": area_factor,  # 設定暴露面積係數欄位的值
        "exposed_surface_area_m2": exposed_surface_area_m2,  # 設定表面面積（exposed_surface_area_m2）欄位的值
    }  # 結束本段參數、容器或條件的組合


# ============================================================================
# 函式大綱｜update_volumetric_enthalpy() — 以熱傳結果更新體積焓
# 【輸入】體積焓場（J/m³）；雷射（laser_W_m3）；變數 heat_result；時間步長（s）
# 【計算】將雷射熱源與不含雷射的淨熱源相加，再乘時間步長
# 【輸出】更新後的體積焓陣列，不在此處反算相態
# ============================================================================
def update_volumetric_enthalpy(enthalpy_J_m3, laser_W_m3, heat_result, dt_s):  # 定義函式：以熱傳結果更新體積焓
    """將對流、輻射、底部熱損失真正扣除；使用體積焓 J/m³。"""  # 接續本段欄位名稱、提示訊息或報表文字
    if dt_s <= 0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("dt_s 必須大於 0")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    if enthalpy_J_m3.shape != laser_W_m3.shape:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("H 與雷射熱源的 3D shape 必須一致")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    net_source_W_m3 = laser_W_m3 + heat_result["net_without_laser_W_m3"]  # 計算或建立變數 net_source_W_m3
    return enthalpy_J_m3 + dt_s * net_source_W_m3  # 回傳本行計算結果，交由呼叫端繼續使用


# ============================================================================
# 函式大綱｜verify_heat_transfer_module() — 驗證導熱與熱損失模組
# 【輸入】無外部參數；讀取本檔或相關模組設定
# 【計算】用小網格檢查內部傳熱守恆、邊界損失符號及氣體導熱
# 【輸出】通過訊息；驗證失敗時拋出斷言例外
# ============================================================================
def verify_heat_transfer_module():  # 定義函式：驗證導熱與熱損失模組
    """純 CPU 三項單元驗證；不等同物理模型或實際粉末床實驗驗證。"""  # 接續本段欄位名稱、提示訊息或報表文字
    mat = _material()                                                    # 讀取測試需要的 Ti64 材料資訊
    mat.validate_material_properties()                                   # 先驗證輸入物性範圍
    f = np.ones((5, 5, 5), dtype=np.float64)                              # 測試一塊均質連續金屬
    t = np.full(f.shape, 600.0)                                          # 設定金屬溫度高於環境
    t[2, 2, 2] = 1500.0                                                  # 在中心建立局部熱點
    result = calculate_heat_transfer_and_loss(t, f, 2e-6, 293.15, 20.0, 20000.0)  # 計算或建立變數 result
    assert abs(float(result["power_conduction_sum_W"])) < 1e-9, "內部導熱不守恆"  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
    assert float(result["power_convection_loss_W"]) > 0, "對流熱損失應為正"  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
    assert float(result["power_radiation_loss_W"]) > 0, "輻射熱損失應為正"  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
    assert float(result["power_bottom_loss_W"]) > 0, "底部熱損失應為正"  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
    H0 = np.full_like(f, 1.0e9)  # 計算或建立變數 H0
    H1 = update_volumetric_enthalpy(H0, np.zeros_like(f), result, 1e-9)  # 計算或建立變數 H1
    expected_delta = 1e-9 * result["net_without_laser_W_m3"]  # 計算或建立變數 expected_delta
    assert np.allclose(H1-H0, expected_delta, atol=5e-7), "體積焓未正確扣除散熱"  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
    assert np.sum(H1-H0) < 0, "無雷射時外部熱損失應造成總焓下降"  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤

    f0 = np.zeros_like(f)                                                 # 測試全空 Voxel 不應有熱流或散熱
    r0 = calculate_heat_transfer_and_loss(t, f0, 2e-6, 293.15, 20.0, 20000.0)  # 計算或建立變數 r0
    assert abs(float(np.sum(r0["net_without_laser_W_m3"]))) < 1e-6, "全氣體內部導熱須守恆"  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
    bridge_F = np.array([1.0, 0.0, 1.0], dtype=float).reshape(3, 1, 1)  # 金屬－氣體－金屬測試體
    bridge_T = np.array([1000.0, 300.0, 300.0], dtype=float).reshape(3, 1, 1)  # 給定左端高溫
    bridge_q = calculate_xyz_conduction(bridge_T, bridge_F, 2e-6)  # 取得所有相鄰界面熱通量
    assert float(bridge_q[1, 0, 0]) > 0, "氣體 Voxel 必須能從金屬吸熱"  # 驗證氣體具有熱通量
    assert abs(float(np.sum(bridge_q))) < 1e-6, "氣體橋接必須全域守恆"  # 檢查內部通量成對抵銷
    print("[PASS] 金屬－氣體－金屬橋接傳熱與守恆")  # 顯示橋接測試結果
    print("[PASS] XYZ 內部導熱淨和 = 0")                                 # 完成內部能量守恆測試
    print("[PASS] 對流／輻射／底部散熱皆為正")                            # 完成表面熱損失測試
    print("[PASS] 全氣體熱傳守恆且沒有金屬表面熱損失")                       # 完成空間遮罩測試
    return True  # 回傳本行計算結果，交由呼叫端繼續使用


# 04 新增：粉末與基板界面熱傳導診斷

# ============================================================================
# 函式大綱｜diagnose_substrate_heat_flux() — 診斷粉末與基板間的熱通量
# 【輸入】絕對溫度場（K）；金屬填充率陣列；基板頂面 Z 索引；網格邊長（m）；NumPy／CuPy 運算後端 xp；液相率陣列
# 【計算】計算界面淨通量、雙向功率、接觸數及兩區最高溫度
# 【輸出】界面熱傳診斷字典；不把內部傳熱當作全域外流
# ============================================================================
def diagnose_substrate_heat_flux(  # 定義函式：診斷粉末與基板間的熱通量
    temperature_K,  # 接續函式參數：絕對溫度場（K）
    metal_fill_fraction,  # 接續函式參數：金屬填充率陣列
    substrate_top_index,  # 接續函式參數：基板頂面 Z 索引
    voxel_size_m,  # 接續函式參數：網格邊長（m）
    xp=np,  # 接續函式參數：NumPy／CuPy 運算後端 xp
    liquid_fraction=None,  # 接續函式參數：液相率陣列
    gas_k=None  # 與主求解器使用同一指定氣體導熱率
):  # 結束本段參數、容器或條件的組合
    """
    診斷粉末與基板交界面的熱傳導。

    輸入：
        temperature_K       : 3D 溫度場 K
        metal_fill_fraction : 3D 金屬填充率 F
        substrate_top_index : 基板頂面 Z 索引
        voxel_size_m        : Voxel 尺寸 m
        xp                  : numpy 或 cupy
        liquid_fraction     : 液相率，可為 None

    輸出：
        P_powder_to_substrate_W
        mean_interface_flux_W_m2
        contact_fraction
        contact_voxels
        Tmax_substrate_K
        Tmax_powder_K
    """

    mat = _material()  # 計算或建立變數 mat

    nz = temperature_K.shape[2]  # 計算或建立變數 nz
    if not 0 < substrate_top_index < nz:  # 判斷本行條件，成立時執行下方處理
        raise ValueError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
            "substrate_top_index 必須位於網格內部"  # 接續本段欄位名稱、提示訊息或報表文字
        )  # 結束本段參數、容器或條件的組合

    if voxel_size_m <= 0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("voxel_size_m 必須大於零")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值

    # 基板最後一層、粉末第一層
    ks = substrate_top_index - 1  # 計算或建立變數 ks
    kp = substrate_top_index  # 計算或建立變數 kp

    Tsub = temperature_K[:, :, ks]  # 計算或建立變數 Tsub
    Tpow = temperature_K[:, :, kp]  # 計算或建立變數 Tpow

    Fsub = metal_fill_fraction[:, :, ks]  # 計算或建立變數 Fsub
    Fpow = metal_fill_fraction[:, :, kp]  # 計算或建立變數 Fpow

    # 沿用 04 現有的有效導熱模型
    k_eff = calculate_conductivity(  # 計算或建立變數 k_eff
        temperature_K,  # 接續變數 k_eff的參數：計算金屬與氣體的有效導熱率
        liquid_fraction,  # 接續變數 k_eff的參數：計算金屬與氣體的有效導熱率
        metal_fill_fraction,  # 接續變數 k_eff的參數：計算金屬與氣體的有效導熱率
        xp, gas_k=gas_k  # 確保界面診斷與主計算的混合導熱率一致
    )  # 結束本段參數、容器或條件的組合

    Ksub = k_eff[:, :, ks]  # 計算或建立變數 Ksub
    Kpow = k_eff[:, :, kp]  # 計算或建立變數 Kpow

    # 有效金屬接觸判定
    contact = (  # 計算或建立接觸（contact）
        (Fsub >= mat.MINIMUM_ACTIVE_METAL_FILL)  # 接續接觸（contact）的數值、運算式或資料項目
        &  # 接續接觸（contact）的數值、運算式或資料項目
        (Fpow >= mat.MINIMUM_ACTIVE_METAL_FILL)  # 接續接觸（contact）的數值、運算式或資料項目
    )  # 結束本段參數、容器或條件的組合

    # 調和平均界面導熱係數
    k_face = (  # 計算或建立相鄰面調和平均導熱率
        2.0 * Ksub * Kpow  # 接續相鄰面調和平均導熱率的數值、運算式或資料項目
        / xp.maximum(Ksub + Kpow, 1e-30)  # 接續相鄰面調和平均導熱率的數值、運算式或資料項目
    )  # 結束本段參數、容器或條件的組合

    # 正值：粉末 -> 基板
    flux = k_face * (Tpow - Tsub) / voxel_size_m  # 氣體與金屬間亦可傳熱，不使用接觸遮罩截斷

    area = voxel_size_m ** 2  # 計算或建立暴露面積或面積係數

    # 界面總功率
    power_W = xp.sum(flux) * area  # 計算或建立功率（power_W）

    # 有效接觸數量
    contact_count = xp.sum(contact)  # 計算或建立接觸數量（contact_count）

    # 接觸比例
    contact_fraction = xp.mean(  # 計算或建立接觸比例（contact_fraction）
        contact.astype(xp.float64)  # 接續接觸比例（contact_fraction）的參數：執行 mean 呼叫並完成該步處理
    )  # 結束本段參數、容器或條件的組合

    # 對實際被判定接觸的面積求平均
    mean_flux = power_W / (flux.size * area)  # 對整個界面積求平均，包含氣體傳熱

    # 基板與粉末各自的最高溫度
    active = (  # 計算或建立有效金屬網格遮罩
        metal_fill_fraction  # 接續有效金屬網格遮罩的數值、運算式或資料項目
        >= mat.MINIMUM_ACTIVE_METAL_FILL  # 接續有效金屬網格遮罩的數值、運算式或資料項目
    )  # 結束本段參數、容器或條件的組合

    sub_active = active[:, :, :substrate_top_index]  # 計算或建立變數 sub_active
    pow_active = active[:, :, substrate_top_index:]  # 計算或建立變數 pow_active

    Tmax_sub = xp.max(  # 計算或建立變數 Tmax_sub
        xp.where(  # 接續變數 Tmax_sub的參數：執行 max 呼叫並完成該步處理
            sub_active,  # 接續變數 Tmax_sub的參數：執行 max 呼叫並完成該步處理
            temperature_K[:, :, :substrate_top_index],  # 接續變數 Tmax_sub的參數：執行 max 呼叫並完成該步處理
            -xp.inf  # 接續變數 Tmax_sub的參數：執行 max 呼叫並完成該步處理
        )  # 結束本段參數、容器或條件的組合
    )  # 結束本段參數、容器或條件的組合

    Tmax_pow = xp.max(  # 計算或建立變數 Tmax_pow
        xp.where(  # 接續變數 Tmax_pow的參數：執行 max 呼叫並完成該步處理
            pow_active,  # 接續變數 Tmax_pow的參數：執行 max 呼叫並完成該步處理
            temperature_K[:, :, substrate_top_index:],  # 接續變數 Tmax_pow的參數：執行 max 呼叫並完成該步處理
            -xp.inf  # 接續變數 Tmax_pow的參數：執行 max 呼叫並完成該步處理
        )  # 結束本段參數、容器或條件的組合
    )  # 結束本段參數、容器或條件的組合

    return {  # 回傳本行計算結果，交由呼叫端繼續使用
        "P_powder_to_substrate_W": power_W,  # 向下與向上熱流抵銷後的淨功率 W
        "P_into_substrate_W": xp.sum(xp.maximum(flux, 0.0)) * area,  # 所有粉末向基板傳熱的正向功率 W
        "P_out_of_substrate_W": xp.sum(xp.maximum(-flux, 0.0)) * area,  # 所有基板向粉末傳熱的反向功率絕對值 W
        "positive_contact_voxels": xp.sum(contact & (flux > 0.0)),  # 熱量流向基板的接觸面數量
        "negative_contact_voxels": xp.sum(contact & (flux < 0.0)),  # 熱量流出基板的接觸面數量
        "mean_interface_flux_W_m2": mean_flux,  # 設定平均通量（mean_interface_flux_W_m2）欄位的值
        "contact_fraction": contact_fraction,  # 設定接觸比例（contact_fraction）欄位的值
        "contact_voxels": contact_count,  # 只記錄金屬與金屬相鄰的面數，不代表熱流僅經此處
        "Tmax_substrate_K": Tmax_sub,  # 設定基板（Tmax_substrate_K）欄位的值
        "Tmax_powder_K": Tmax_pow,  # 設定粉末（Tmax_powder_K）欄位的值
        "interface_flux_W_m2": flux,  # 界面各位置正負熱通量
        "thermal_interface_cells": flux.size,  # 總計所有界面傳熱面
    }  # 結束本段參數、容器或條件的組合


# 此函式由 main.py 的時間迴圈呼叫；04 獨立執行時只執行單元測試。

# ============================================================================
# 函式大綱｜verify_substrate_interface_diagnostic() — 驗證界面導熱診斷
# 【輸入】無外部參數；讀取本檔或相關模組設定
# 【計算】設定已知界面溫差，檢查功率方向、接觸面與面積換算
# 【輸出】通過訊息；方向或單位不一致時拋出斷言例外
# ============================================================================
def verify_substrate_interface_diagnostic():  # 定義函式：驗證界面導熱診斷
    """檢查界面熱流正負方向、接觸面積及功率單位。"""  # 接續本段欄位名稱、提示訊息或報表文字
    F = np.ones((4, 3, 4), dtype=np.float64)  # 計算或建立金屬填充率 F
    T = np.full_like(F, 300.0)  # 計算或建立溫度 T（K）
    T[:, :, 2:] = 1000.0  # 計算或建立溫度 T（K）的指定網格或切片
    out = diagnose_substrate_heat_flux(T, F, 2, 2e-6, xp=np)  # 累計基板較熱時回傳粉末的反向面功率，數值以正值表示
    assert float(out["P_powder_to_substrate_W"]) > 0.0, "熱應自粉末流向基板"  # 驗證淨功率方向
    assert np.isclose(float(out["P_into_substrate_W"]) - float(out["P_out_of_substrate_W"]), float(out["P_powder_to_substrate_W"])), "界面正負功率不守恆"  # 驗證功率分項加總
    assert int(out["contact_voxels"]) == 12, "接觸面數錯誤"  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
    assert np.isclose(float(out["contact_fraction"]), 1.0), "接觸率錯誤"  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
    assert np.isclose(  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
        float(out["P_powder_to_substrate_W"]),  # 接續本段運算：回傳粉末的反向功率
        float(out["mean_interface_flux_W_m2"]) * 12 * (2e-6)**2  # 接續本段運算：回傳粉末的反向功率
    ), "界面功率與通量單位不一致"  # 接續本段參數、索引或數值運算
    print("[PASS] 04 基板界面熱通量診斷測試")  # 輸出本階段的數值、進度或診斷訊息


if __name__ == "__main__":  # 只有直接執行本檔時才啟動以下流程
    verify_heat_transfer_module()  # 驗證導熱與熱損失模組
    verify_substrate_interface_diagnostic()  # 驗證界面導熱診斷


# 簡化版｜表面蒸發熱損失，不更新金屬質量或幾何
# ============================================================================
# 函式大綱｜calculate_evaporation_loss() — 估算速率限制的蒸發熱損失
# 【輸入】絕對溫度場（K）；金屬填充率陣列；網格邊長（m）；時間步長（s）；NumPy／CuPy 運算後端 xp；蒸發係數
# 【續輸入】金屬蒸氣背壓（Pa）；可蒸發液態表面積係數；金屬焓（metal_specific_enthalpy_J_kg）
# 【計算】以飽和蒸氣壓及 Hertz–Knudsen 通量計算汽化與攜出焓，並受金屬存量限制
# 【輸出】蒸發功率密度；呼叫端須同步移除金屬量並限制總可用焓
# ============================================================================
def calculate_evaporation_loss(temperature_K, metal_fill_fraction, voxel_size_m,  # 定義函式：估算速率限制的蒸發熱損失
                               dt_s, xp=np,  # 接續函式參數：時間步長（s）、NumPy／CuPy 運算後端 xp
                               accommodation=EVAPORATION_ACCOMMODATION,  # 接續函式參數：蒸發係數
                               vapor_back_pressure_Pa=EVAPORATION_BACK_PRESSURE_PA,  # 接續函式參數：金屬蒸氣背壓（Pa）
                               evaporation_area_factor=None,  # 接續函式參數：可蒸發液態表面積係數
                               metal_specific_enthalpy_J_kg=None):  # 接續函式參數：金屬焓（metal_specific_enthalpy_J_kg）
    """估算速率限制的蒸發熱損失。
    計算：以飽和蒸氣壓及 Hertz–Knudsen 通量計算汽化與攜出焓，並受金屬存量限制。
    輸出：蒸發功率密度；呼叫端須同步移除金屬量並限制總可用焓。
    """
    mat = _material()  # 計算或建立變數 mat
    if voxel_size_m <= 0.0 or dt_s <= 0.0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("voxel_size_m and dt_s must be positive")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    if not 0.0 <= accommodation <= 1.0 or vapor_back_pressure_Pa < 0.0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("invalid evaporation coefficient or vapor back-pressure")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    F = xp.clip(metal_fill_fraction, 0., 1.)  # 計算或建立金屬填充率 F
    area = (calculate_top_surface_face_area(F, xp) if evaporation_area_factor is None  # 計算或建立暴露面積或面積係數
            else evaporation_area_factor)  # 接續暴露面積或面積係數的數值、運算式或資料項目
    if area.shape != F.shape:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("evaporation_area_factor shape must match metal_fill_fraction")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    T = xp.maximum(temperature_K, 300.)  # 計算或建立溫度 T（K）
    R = mat.UNIVERSAL_GAS_CONSTANT_J_MOL_K  # 計算或建立變數 R
    M = mat.MOLAR_MASS_KG_MOL  # 計算或建立變數 M
    Tb = mat.BOILING_TEMPERATURE_K  # 計算或建立標準沸點
    Lv = mat.LATENT_HEAT_VAPORIZATION_J_KG  # 計算或建立汽化潛熱（J/kg）
    p_sat = 101325.0 * xp.exp(xp.clip(-Lv * M / R * (1.0 / T - 1.0 / Tb), -80.0, 25.0))  # 計算或建立飽和金屬蒸氣壓
    net_pressure = xp.maximum(p_sat - vapor_back_pressure_Pa, 0.0)  # 飽和蒸氣壓減金屬蒸氣背壓，只保留向外蒸發的正壓差
    mass_flux = accommodation * net_pressure * xp.sqrt(M / (2.0 * np.pi * R * T))  # 以 Hertz–Knudsen 公式計算每單位表面、每秒蒸發的質量
    if metal_specific_enthalpy_J_kg is None:  # 獨立呼叫也要使用完整材料焓，避免只計汽化潛熱
        metal_specific_enthalpy_J_kg = import_module('05_enthalpy_phase_焓法相變').specific_enthalpy_from_temperature(temperature_K, xp)  # 與主程式共用 05 的材料比焓公式
    h_metal = xp.maximum(metal_specific_enthalpy_J_kg, 0.0)  # 蒸發攜出金屬原有顯熱與熔化潛熱
    energy_per_kg = Lv + h_metal  # 計算或建立能量（energy_per_kg）
    q_raw = mass_flux * energy_per_kg * area / voxel_size_m  # 將面質量通量乘每公斤移除能量，再以面積／體積比換成熱源密度
    q_raw = xp.where((temperature_K >= mat.LIQUIDUS_TEMPERATURE_K) & (F > 0.0), q_raw, 0.0)  # 只在液相線以上且仍有金屬時保留蒸發率，排除非液態網格

    q_inventory_limit = F * mat.SOLID_DENSITY_KG_M3 * energy_per_kg / dt_s  # 以當地全部金屬存量求蒸發上限，避免單步移除超過現有質量
    return xp.minimum(q_raw, q_inventory_limit)  # 回傳本行計算結果，交由呼叫端繼續使用
