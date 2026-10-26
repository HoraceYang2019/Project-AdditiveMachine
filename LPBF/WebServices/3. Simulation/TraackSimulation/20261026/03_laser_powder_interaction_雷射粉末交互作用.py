# -*- coding: utf-8 -*-
"""
==========================================================================
03｜雷射與粉末交互作用（Laser–Powder Interaction）
==========================================================================

【一、程式大綱｜計算順序】
  01. 讀取輸入參數：功率、掃描速度、光斑、吸收率、Voxel 尺寸
  02. 載入粉末及基板：讀取 solid_mask.npy/.npz 的三維金屬分布
  03. 計算雷射位置：根據時間與掃描速度沿 +X 移動，Y 固定於中央
  04. 計算 Gaussian 光強：取得 XY 平面各光柱入射功率
  05. 計算粉末逐層遮蔽：由最高 Z 向下，依金屬填充率決定攔截比例
  06. 計算 Voxel 吸收功率：將攔截功率乘以吸收率，換算成 W/m³
  07. 檢查功率收支：入射＝吸收＋未吸收攔截＋底部透射＋網格外功率
  08. 驗證吸收深度：輸出全域頂面與各光柱首個金屬表面以下 2/4/10/20 µm 吸收比例
  09. 檢查 Z 層入射／攔截／吸收功率與高吸收 Voxel
  10. 輸出模擬結果：儲存 CSV 功率歷程、Z 層 CSV 及 NPZ 的 XY / XYZ 分布

【二、主要函式與職責】
  02.process.parse_command_line()    統一讀取加工命令列設定
  load_metal_mask()                  讀取粉末／基板 3D 金屬遮罩
  calculate_laser_position()         計算雷射當下 X 座標、開關與掃描時間
  calculate_laser_powder_absorption()計算 Gaussian 光強、遮蔽與吸收
  save_snapshot()                    儲存 NPZ 光場快照
  main()                             串接流程並輸出 CSV／NPZ

【三、輸入與輸出】
  輸入：input/solid_mask.npy（或 .npz）、雷射與數值參數
  輸出：laser_power_history.csv、laser_t*.npz、laser_config.json
  單位：長度 m（設定以 µm 輸入）；時間 s（設定以 ns/µs 輸入）
        光強 W/m²；體積吸收功率密度 W/m³；總功率 W

【四、物理假設及限制】
  - 光斑在 XY 平面使用 Gaussian 分布，沿 +X 連續移動。
  - 每個 XY 光柱沿 −Z 傳播，逐層依金屬體積填充率遮蔽。
  - 反射／散射只有功率帳，不做光線追蹤與多次反射。
  - 尚不計算粉末升溫、XYZ 熱傳導、熔化、液態流動或熔深。
   - 獨立測試採 fL=0；正式主程式須逐步傳入液相率以更新吸收率。
  - 這是 Stage A 簡化光學模型，不能視為已驗證的實際光學行為。
  - 材料吸收率與金屬填充率門檻只從 01 材料模組讀取。
==========================================================================
"""

from importlib import import_module  # 支援 01/02 數字開頭的副程式檔名
import csv  # 輸出每個採樣時間點的功率平衡
import json  # 輸出運行設定與模型限制
import math  # Gaussian 公式中的 π 與指數
from pathlib import Path  # 跨平台檔案路徑
import numpy as np  # 基本 CPU 陣列計算，並支援選用 CuPy

# 【跨副程式依賴】使用唯一材料來源與唯一加工設定來源。
material = import_module("01_Material Parameters_材料參數")  # 01：Ti64 材料係數
process = import_module("02_process_parameters_加工參數")  # 02：加工／數值參數

# 與原 Stage A 的最低有效金屬填充率相同；低於此值視作無法攔截雷射。
MINIMUM_ACTIVE_METAL_FILL = material.MINIMUM_ACTIVE_METAL_FILL  # 計算或建立有效金屬最低填充率

ABSORPTIVITY_SOLID = material.SOLID_LASER_ABSORPTIVITY  # 從 01 取得使用者指定的固態吸收率 0.40
ABSORPTIVITY_LIQUID = material.LIQUID_LASER_ABSORPTIVITY  # 從 01 取得使用者指定的液態吸收率 0.25
ABSORPTIVITY_MODEL = 'user-specified solid/liquid absorptivity, linear liquid-fraction interpolation'  # 實際模型為相依指定值，不是 Fresnel 推算


# ============================================================================
# 函式大綱｜calculate_phase_absorptivity() — 依液相率更新吸收率
# 【輸入】液相率陣列；NumPy／CuPy 陣列後端
# 【計算】檢查液相率輸入，將固態與液態吸收率線性混合
# 【輸出】與液相率相同形狀的局部吸收率陣列
# ============================================================================
def calculate_phase_absorptivity(liquid_fraction, array_backend):  # 定義函式：依液相率更新吸收率
    if liquid_fraction is None:  # 判斷本行條件，成立時執行下方處理
        raise ValueError('相依吸收率需要液相率 liquid_fraction；主程式須傳入當前 fL')  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    fL = array_backend.clip(array_backend.asarray(liquid_fraction), 0.0, 1.0)  # 計算或建立液相率 fL
    return material.SOLID_LASER_ABSORPTIVITY * (1.0 - fL) + material.LIQUID_LASER_ABSORPTIVITY * fL  # 計算時直接讀取 01 的兩相吸收率


# ============================================================================
# 函式大綱｜parse_arguments() — 轉交獨立雷射測試的命令列參數
# 【輸入】命令列參數
# 【計算】呼叫 02 的統一解析器，避免重複定義製程設定
# 【輸出】加工與數值設定物件
# ============================================================================
def parse_arguments(args=None):  # 定義函式：轉交獨立雷射測試的命令列參數
    """直接使用 02 的命令列解析；雷射不再重複定義任何製程預設值。"""  # 接續本段欄位名稱、提示訊息或報表文字
    return process.parse_command_line(args=args)  # 所有加工參數只定義於 02


# ============================================================================
# 函式大綱｜load_metal_mask() — 載入三維粉末與基板幾何
# 【輸入】輸入幾何檔路徑
# 【計算】讀取 npy 或 npz、選取遮罩並檢查形狀與有效金屬
# 【輸出】三維金屬遮罩與實際輸入路徑
# ============================================================================
def load_metal_mask(input_path):  # 定義函式：載入三維粉末與基板幾何
    """讀取 [Nx,Ny,Nz] 的布林幾何；True 代表該 Voxel 有金屬。"""  # 接續本段欄位名稱、提示訊息或報表文字
    path = Path(input_path)  # 將路徑轉成 Path
    if path.is_dir():  # 輸入若為資料夾，預設讀取其內的 solid_mask.npy
        path = path / 'solid_mask.npy'  # 與原始 Stage A 相容
    if not path.is_file():  # 無法找到原始粉末幾何時停止
        raise FileNotFoundError(f'找不到粉末幾何：{path}')  # 避免默默建立假的粉末床
    if path.suffix.lower() == '.npz':  # 處理壓縮的 NumPy 檔案
        with np.load(path, allow_pickle=False) as archive:  # 安全讀取 NPZ
            name = 'solid_mask' if 'solid_mask' in archive.files else archive.files[0]  # 優先使用固態遮罩鍵
            mask = np.asarray(archive[name], dtype=bool)  # 轉為布林幾何
    else:  # 一般 NPY 格式
        mask = np.asarray(np.load(path, allow_pickle=False), dtype=bool)  # 讀入布林幾何
    if mask.ndim != 3 or min(mask.shape) < 1:  # 確保 XYZ 網格格式正確
        raise ValueError('solid_mask 必須是非空的三維陣列 [Nx,Ny,Nz]')  # 回報輸入格式錯誤
    if not np.any(mask):  # 全空的網格沒有可吸收雷射的金屬
        raise ValueError('solid_mask 完全沒有金屬，無法進行雷射粉末吸收測試')  # 回報空粉末床
    return mask, path  # 回傳金屬幾何與實際檔案路徑


# ============================================================================
# 函式大綱｜calculate_laser_position() — 計算雷射掃描位置
# 【輸入】模擬時間（s）；變數 domain_length_x_m；變數 start_x_m；變數 end_margin_m；掃描速度（scan_speed_m_s）
# 【計算】由起點、速度及時間計算 X 座標，並判斷是否仍在掃描期間
# 【輸出】雷射 X 座標、開關狀態與完整掃描時間
# ============================================================================
def calculate_laser_position(time_s, domain_length_x_m, start_x_m, end_margin_m, scan_speed_m_s):  # 定義函式：計算雷射掃描位置
    """更新雷射位置；超出掃描時間之後雷射關閉，X 停留在終點。"""  # 接續本段欄位名稱、提示訊息或報表文字
    scan_length_m = domain_length_x_m - start_x_m - end_margin_m  # 計算實際掃描距離
    if scan_length_m <= 0.0:  # 掃描起點與終點不可重疊或顛倒
        raise ValueError('X 模型長度不足，請縮小 --start-um / --end-margin-um')  # 回報幾何限制
    scan_duration_s = scan_length_m / scan_speed_m_s  # 以距離 / 速度計算掃描時間
    laser_on = time_s < scan_duration_s  # 原始 Stage A：到達終點時間後立即關閉
    laser_x_m = start_x_m + scan_speed_m_s * min(time_s, scan_duration_s)  # 連續計算光斑 X 位置
    return laser_x_m, laser_on, scan_duration_s  # 回傳雷射中心與狀態


# ============================================================================
# 函式大綱｜calculate_laser_powder_absorption() — 計算雷射與粉末的能量交互作用
# 【輸入】金屬填充率陣列；NumPy／CuPy 陣列後端；網格邊長（m）；雷射中心（laser_center_x_m）；雷射中心（laser_center_y_m）；雷射功率（laser_power_W）
# 【續輸入】變數 absorptivity；變數 spot_radius_m
# 【計算】建立高斯光強，以由上至下的累積透射率計算攔截、吸收、反射及透射功率
# 【輸出】三維吸收功率密度與全域、逐層功率收支；不追蹤多次反射
# ============================================================================
def calculate_laser_powder_absorption(metal_fill_fraction, array_backend, voxel_size_m,  # 定義函式：計算雷射與粉末的能量交互作用
                                      laser_center_x_m, laser_center_y_m,  # 接續函式參數：雷射中心（laser_center_x_m）、雷射中心（laser_center_y_m）
                                      laser_power_W, absorptivity, spot_radius_m):  # 接續函式參數：雷射功率（laser_power_W）、變數 absorptivity、變數 spot_radius_m
    """計算 XYZ 吸收功率密度與封閉功率帳；不修改粉末或溫度。"""  # 接續本段欄位名稱、提示訊息或報表文字
    nx, ny, nz = metal_fill_fraction.shape  # 取得 XYZ Voxel 數量
    # absorptivity 可為純量或與 F 同形狀的 3D 局部吸收率；逐 Z 層使用，不複製到 CPU。
    if getattr(absorptivity, 'ndim', 0) == 3 and absorptivity.shape != metal_fill_fraction.shape:  # 判斷本行條件，成立時執行下方處理
        raise ValueError('吸收率 3D 陣列必須與 metal_fill_fraction 形狀相同')  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    x_centers_m = (array_backend.arange(nx) + 0.5) * voxel_size_m  # 計算 X 方向各 Voxel 中心
    y_centers_m = (array_backend.arange(ny) + 0.5) * voxel_size_m  # 計算 Y 方向各 Voxel 中心
    radius_squared_m2 = (x_centers_m[:, None] - laser_center_x_m) ** 2 + (y_centers_m[None, :] - laser_center_y_m) ** 2  # 計算 XY 距光斑中心距離平方
    gaussian_intensity_W_m2 = (2.0 * laser_power_W / (math.pi * spot_radius_m**2)) * array_backend.exp(-2.0 * radius_squared_m2 / spot_radius_m**2)  # Gaussian 表面光強
    incident_power_xy_W = gaussian_intensity_W_m2 * voxel_size_m**2  # 各 XY 光柱的入射雷射功率
    coverage = array_backend.where(  # 計算或建立遮蔽率（coverage）
        metal_fill_fraction >= material.MINIMUM_ACTIVE_METAL_FILL,  # 計算時使用與熱傳及相變一致的材料填充率門檻
        array_backend.clip(metal_fill_fraction, 0.0, 1.0), 0.0)  # 接續遮蔽率（coverage）的參數：依布林遮罩選擇對應分支數值
    layer_transmission = 1.0 - coverage  # 計算或建立透射率（layer_transmission）
    transmission_including_layer = array_backend.cumprod(  # 計算或建立透射率（transmission_including_layer）
        layer_transmission[:, :, ::-1], axis=2)[:, :, ::-1]  # 接續透射率（transmission_including_layer）的數值、運算式或資料項目
    transmission_before_layer = array_backend.concatenate(  # 計算或建立透射率之前（transmission_before_layer）
        (transmission_including_layer[:, :, 1:],  # 接續透射率之前（transmission_before_layer）的參數：執行 concatenate 呼叫並完成該步處理
         array_backend.ones((nx, ny, 1), dtype=array_backend.float64)), axis=2)  # 接續透射率之前（transmission_before_layer）的參數：執行 concatenate 呼叫並完成該步處理
    incident_by_voxel_W = incident_power_xy_W[:, :, None] * transmission_before_layer  # 計算或建立入射網格（incident_by_voxel_W）
    intercepted_power_by_voxel_W = incident_by_voxel_W * coverage  # 計算或建立攔截功率網格（intercepted_power_by_voxel_W）
    alpha = (absorptivity if getattr(absorptivity, 'ndim', 0) == 3  # 計算或建立變數 alpha
             else array_backend.asarray(absorptivity))  # 接續變數 alpha的數值、運算式或資料項目
    absorbed_power_by_voxel_W = intercepted_power_by_voxel_W * alpha  # 計算或建立吸收功率網格（absorbed_power_by_voxel_W）
    absorbed_power_density_W_m3 = absorbed_power_by_voxel_W / voxel_size_m**3  # 計算或建立吸收功率密度（absorbed_power_density_W_m3）
    incident_power_by_z_W = array_backend.sum(incident_by_voxel_W, axis=(0, 1))  # 計算或建立入射功率Z方向（incident_power_by_z_W）
    intercepted_power_by_z_W = array_backend.sum(intercepted_power_by_voxel_W, axis=(0, 1))  # 計算或建立攔截功率Z方向（intercepted_power_by_z_W）
    absorbed_power_by_z_W = array_backend.sum(absorbed_power_by_voxel_W, axis=(0, 1))  # 計算或建立吸收功率Z方向（absorbed_power_by_z_W）
    reflected_power_by_z_W = array_backend.sum(  # 計算或建立反射功率Z方向（reflected_power_by_z_W）
        intercepted_power_by_voxel_W * (1.0 - alpha), axis=(0, 1))  # 接續反射功率Z方向（reflected_power_by_z_W）的參數：沿指定軸加總陣列數值
    coverage_by_z = array_backend.mean(coverage, axis=(0, 1))  # 計算或建立遮蔽率Z方向（coverage_by_z）
    z_indices = array_backend.arange(nz, dtype=array_backend.int32)[None, None, :]  # 計算或建立Z方向索引（z_indices）
    first_hit_index_xy = array_backend.max(  # 計算或建立索引XY平面（first_hit_index_xy）
        array_backend.where(coverage > 0.0, z_indices, -1), axis=2)  # 接續索引XY平面（first_hit_index_xy）的參數：執行 max 呼叫並完成該步處理
    remaining_transmission = array_backend.prod(layer_transmission, axis=2)  # 計算或建立剩餘透射率（remaining_transmission）
    reflected_or_scattered_power_W = array_backend.sum(reflected_power_by_z_W)  # 計算或建立反射功率（reflected_or_scattered_power_W）
    incident_power_in_domain_W = array_backend.sum(incident_power_xy_W)  # 積分有限 XY 網格內的雷射入射功率
    absorbed_power_W = array_backend.sum(absorbed_power_by_z_W)  # 累加所有 Z 層金屬吸收的功率
    transmitted_power_below_domain_W = array_backend.sum(incident_power_xy_W * remaining_transmission)  # 計算穿透至整個網格底部的功率
    outside_domain_power_W = laser_power_W - incident_power_in_domain_W  # 有限網格未涵蓋的 Gaussian 光斑尾部功率
    power_balance_residual_W = (laser_power_W - outside_domain_power_W - absorbed_power_W  # 計算或建立功率收支殘差（power_balance_residual_W）
                                - reflected_or_scattered_power_W - transmitted_power_below_domain_W)  # 雷射全域功率收支差
    return {  # 同時回傳三維熱源與吸收功率審計資訊
        'gaussian_intensity_W_m2': gaussian_intensity_W_m2,  # XY 光強
        'absorption_W_m3': absorbed_power_density_W_m3,  # XYZ 金屬吸收功率密度
        'remaining_transmission_xy': remaining_transmission,  # 穿過全高度的殘餘透射比例
        'absorbed_power_by_z_W': absorbed_power_by_z_W,  # 各 Z 層吸收功率
        'incident_power_by_z_W': incident_power_by_z_W,  # 新增：各 Z 層入射功率
        'intercepted_power_by_z_W': intercepted_power_by_z_W,  # 新增：各 Z 層攔截功率
        'reflected_power_by_z_W': reflected_power_by_z_W,  # 新增：各 Z 層未吸收功率
        'coverage_by_z': coverage_by_z,  # 新增：各 Z 層平均遮蔽率
        'first_hit_index_xy': first_hit_index_xy,  # 新增：各光柱首次碰到金屬高度
        'incident_power_domain_W': incident_power_in_domain_W,  # 網格內入射功率
        'absorbed_power_W': absorbed_power_W,  # 所有金屬吸收功率
        'effective_absorptivity': absorbed_power_W / laser_power_W if laser_power_W > 0.0 else 0.0,  # 設定有效（effective_absorptivity）欄位的值
        'absorptivity_model': ABSORPTIVITY_MODEL,  # 記錄實際使用的相依吸收率模型
        'unabsorbed_intercepted_W': reflected_or_scattered_power_W,  # 簡化反射／散射功率
        'transmitted_below_domain_W': transmitted_power_below_domain_W,  # 穿過底部的功率
        'outside_domain_W': outside_domain_power_W,  # 網格外的 Gaussian 尾部
        'power_balance_residual_W': power_balance_residual_W,  # 守恆殘差
    }  # 結束光學能量計算


# ============================================================================
# 函式大綱｜diagnose_laser_absorption_depth() — 檢查雷射吸收深度
# 【輸入】變數 result；金屬填充率陣列；網格邊長（m）；NumPy／CuPy 陣列後端
# 【計算】比較固定頂面及各光柱首次金屬表面以下的吸收分布
# 【輸出】吸收深度、層位置與能量占比等診斷欄位
# ============================================================================
def diagnose_laser_absorption_depth(result, metal_fill_fraction, voxel_size_m, array_backend):  # 定義函式：檢查雷射吸收深度
    """驗證能量沉積是否集中；兩種深度基準都以已吸收功率為分母。"""  # 避免誤將入射功率當成吸收比例分母
    xp = array_backend  # 支援 NumPy 和 CuPy
    absorb = result['absorption_W_m3'] * voxel_size_m**3  # 將每格 W/m³ 換算為 W
    nz = absorb.shape[2]  # 取得 Z 層數
    total = xp.sum(absorb)  # 計算域內所有吸收功率 W
    denom = xp.maximum(total, 1.0e-30)  # 防止雷射關閉後除以零
    first_index = result['first_hit_index_xy']  # 取得每個 XY 光柱首次遭遇金屬的高度
    index_z = xp.arange(nz, dtype=xp.int32)[None, None, :]  # 建立供三維遮罩使用的 Z 索引
    first_index_3d = first_index[:, :, None]  # 將首遇高度擴展至 Z 軸
    result_metrics = {}  # 建立診斷結果字典
    for depth_um in (2, 4, 10, 20):  # 固定比較四個深度範圍
        cells = max(1, int(math.ceil(depth_um * 1e-6 / voxel_size_m - 1e-12)))  # 深度換算成整數 Voxel 層數
        global_power = xp.sum(absorb[:, :, max(0, nz - cells):])  # 全域幾何頂面以下深度的吸收功率
        local_mask = (first_index_3d >= 0) & (index_z <= first_index_3d) & (index_z > first_index_3d - cells)  # 每光柱首遇金屬之下指定格數
        local_power = xp.sum(xp.where(local_mask, absorb, 0.0))  # 加總粉床局部表面下方吸收功率
        result_metrics[f'global_top{depth_um}um_absorbed_pct'] = 100.0 * global_power / denom  # 全域頂面比例 %
        result_metrics[f'local_top{depth_um}um_absorbed_pct'] = 100.0 * local_power / denom  # 局部首遇金屬表面比例 %
    result_metrics['effective_absorptivity_domain'] = total / xp.maximum(result['incident_power_domain_W'], 1.0e-30)  # 域內有效吸收率
    result_metrics['max_voxel_absorbed_power_W'] = xp.max(absorb)  # 單格最大吸收功率 W
    result_metrics['max_voxel_source_W_m3'] = xp.max(result['absorption_W_m3'])  # 單格最大體積熱源 W/m³
    result_metrics['maximum_Z_layer_absorbed_pct'] = 100.0 * xp.max(result['absorbed_power_by_z_W']) / denom  # 單一 Z 層吸收占比
    return result_metrics  # 提供給 CSV、終端與 NPZ 的驗證資訊


# ============================================================================
# 函式大綱｜save_absorption_z_profile() — 儲存逐層雷射吸收分布
# 【輸入】本次輸出目錄；時間步序號；模擬時間（s）；變數 result；網格邊長（m）；CPU／GPU 陣列後端
# 【計算】把各 Z 層的入射、攔截、吸收及反射資料轉回 CPU 並寫入 CSV
# 【輸出】逐層功率資料檔，供檢查雷射穿透與遮蔽
# ============================================================================
def save_absorption_z_profile(output_dir, step, time_s, result, voxel_size_m, backend):  # 定義函式：儲存逐層雷射吸收分布
    """每個儲存時間輸出一份逐 Z 層能量收支診斷。"""  # 保留原 Stage A 光學模型
    fields = ('incident_power_by_z_W', 'intercepted_power_by_z_W', 'absorbed_power_by_z_W', 'reflected_power_by_z_W', 'coverage_by_z')  # 指定需要的光學欄位
    arrays = [backend.asnumpy(result[key]) if backend is not np else np.asarray(result[key]) for key in fields]  # GPU 只在儲存時轉 CPU
    nz = len(arrays[0])  # 取得 Z 層數
    path = output_dir / f'laser_z_profile_t{time_s*1e6:010.3f}us_step{step:08d}.csv'  # 為每一個快照建立獨立檔名
    with path.open('w', newline='', encoding='utf-8-sig') as file:  # 使用 Excel 可讀的 UTF-8 BOM
        writer = csv.writer(file)  # 建立 CSV 寫入器
        writer.writerow(['z_index', 'depth_from_domain_top_um', *fields, 'z_layer_absorption_fraction'])  # 寫入每個欄位名稱
        for k in range(nz - 1, -1, -1):  # 由頂往底輸出資料
            vals = [float(a[k]) for a in arrays]  # 取得當層功率與遮蔽率
            fraction = vals[2] / vals[0] if vals[0] > 0 else 0.0  # 吸收比例為該層吸收/該層入射
            writer.writerow([k, (nz - 1 - k) * voxel_size_m * 1e6, *vals, fraction])  # 寫入 Z 層資料
    return path  # 回傳完成的 CSV 路徑


# ============================================================================
# 函式大綱｜compute_laser_step() — 執行單一步雷射計算
# 【輸入】金屬填充率陣列；NumPy／CuPy 陣列後端；加工與數值設定；時間（simulation_time_s）；液相率陣列
# 【計算】更新掃描位置與開關，依當前液相率選用吸收率，再計算三維熱源
# 【輸出】雷射座標、開關、掃描時間與吸收結果
# ============================================================================
def compute_laser_step(metal_fill_fraction, array_backend, settings, simulation_time_s,  # 定義函式：執行單一步雷射計算
                       liquid_fraction=None):  # 接續函式參數：液相率陣列
    """給未來 main.py 每個時間步呼叫：輸入當前粉末分布，回傳位置與三維雷射吸收結果。"""  # 接續本段欄位名稱、提示訊息或報表文字
    voxel_size_m = settings.grid_um * 1e-6  # 使用 02 網格參數換算公尺
    length_x_m = metal_fill_fraction.shape[0] * voxel_size_m  # X 方向實際模型長度
    laser_x_m, laser_on, scan_duration_s = calculate_laser_position(  # 利用 02 掃描速度計算移動
        simulation_time_s, length_x_m, settings.start_um * 1e-6,  # 接續雷射（laser_x_m）、雷射（laser_on）、掃描期間（scan_duration_s）的參數：計算雷射掃描位置
        settings.end_margin_um * 1e-6, settings.speed * 1e-3)  # 接續雷射（laser_x_m）、雷射（laser_on）、掃描期間（scan_duration_s）的參數：計算雷射掃描位置
    laser_y_m = metal_fill_fraction.shape[1] * voxel_size_m / 2  # 雷射 Y 中心位置
    active_power_W = settings.power if laser_on else 0.0  # 雷射結束後關閉功率
    if liquid_fraction is None:  # 判斷本行條件，成立時執行下方處理
        raise ValueError('compute_laser_step 必須傳入當前 3D liquid_fraction，避免熔化後仍固定使用固態吸收率')  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    if liquid_fraction.shape != metal_fill_fraction.shape:  # 判斷本行條件，成立時執行下方處理
        raise ValueError('liquid_fraction 與 metal_fill_fraction 尺寸不一致')  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    local_alpha = calculate_phase_absorptivity(liquid_fraction, array_backend)  # 計算或建立變數 local_alpha
    result = calculate_laser_powder_absorption(  # 計算 Gaussian 光強與粉末遮蔽
        metal_fill_fraction, array_backend, voxel_size_m, laser_x_m,  # 接續變數 result的參數：計算雷射與粉末的能量交互作用
        laser_y_m, active_power_W, local_alpha,  # 接續變數 result的參數：計算雷射與粉末的能量交互作用
        0.5 * settings.spot_diameter * 1e-6,  # 接續變數 result的參數：計算雷射與粉末的能量交互作用
        )  # 結束本段參數、容器或條件的組合
    return laser_x_m, laser_y_m, laser_on, scan_duration_s, result  # 供熱傳模組取用 absorption_W_m3


# ============================================================================
# 函式大綱｜save_snapshot() — 儲存獨立雷射光場快照
# 【輸入】本次輸出目錄；時間步序號；模擬時間（s）；雷射（laser_x_m）；雷射（laser_y_m）；雷射（laser_on）
# 【續輸入】變數 result；CPU／GPU 陣列後端；診斷（diagnostics）
# 【計算】把 GPU 陣列轉成 CPU，將光強、熱源及診斷寫成壓縮 NPZ
# 【輸出】光場快照路徑及選用的深度診斷檔
# ============================================================================
def save_snapshot(output_dir, step, time_s, laser_x_m, laser_y_m, laser_on, result, backend, diagnostics=None):  # 定義函式：儲存獨立雷射光場快照
    """儲存可繪製 XY/XZ/YZ 光強剖面的 NPZ；保留完整 XYZ 吸收陣列。"""  # 接續本段欄位名稱、提示訊息或報表文字
    as_numpy = (lambda a: backend.asnumpy(a) if backend is not np else np.asarray(a))  # GPU 資料先轉回 CPU
    target = output_dir / f'laser_t{time_s*1e6:010.3f}us_step{step:08d}.npz'  # 依時刻命名輸出檔
    np.savez_compressed(target,  # 壓縮儲存雷射光場
                        intensity_XY_W_m2=as_numpy(result['gaussian_intensity_W_m2']).astype(np.float32),  # XY 光強圖
                        absorption_XYZ_W_m3=as_numpy(result['absorption_W_m3']).astype(np.float32),  # 三維雷射吸收圖
                        transmission_XY=as_numpy(result['remaining_transmission_xy']).astype(np.float32),  # XY 透射分布
                        absorbed_power_by_Z_W=as_numpy(result['absorbed_power_by_z_W']).astype(np.float64),  # 各 Z 層功率
                        laser_x_um=np.float64(laser_x_m*1e6),  # 光斑 X 位置
                        laser_y_um=np.float64(laser_y_m*1e6),  # 光斑 Y 位置
                        laser_on=np.bool_(laser_on),  # 光斑開關狀態
                        time_us=np.float64(time_s*1e6))  # 模擬時間
    if diagnostics is not None:  # 有深度診斷時一併輸出可直接繪圖的 NPZ 指標
        metric_path = output_dir / f'laser_depth_metrics_t{time_s*1e6:010.3f}us_step{step:08d}.npz'  # 診斷 NPZ 與光場 NPZ 分開以保持舊欄位相容
        np.savez_compressed(metric_path, **{key: np.float64(float(value.get()) if hasattr(value, 'get') else float(value)) for key, value in diagnostics.items()})  # 儲存各吸收深度比例
    return target  # 回傳已寫入的快照路徑


# ============================================================================
# 函式大綱｜main() — 執行獨立雷射驗證流程
# 【輸入】無外部參數；讀取本檔或相關模組設定
# 【計算】解析參數、載入金屬幾何、選擇運算後端並逐步記錄光學功率
# 【輸出】雷射驗證的設定、CSV 歷程與 NPZ 快照
# ============================================================================
def main():  # 定義函式：執行獨立雷射驗證流程
    """執行獨立光學測試，產生 CSV 功率收支與 NPZ 空間能量分布。"""  # 接續本段欄位名稱、提示訊息或報表文字
    args = parse_arguments()  # 由 02 取得全部加工／數值參數
    material.validate_material_properties()  # 由 01 驗證唯一的材料係數
    process.validate_process_parameters(args)  # 由 02 驗證加工參數
    if min(args.power, args.speed, args.spot_diameter, args.grid_um, args.dt_ns, args.save_us) <= 0.0:  # 物理量須為正
        raise ValueError('功率、速度、光斑、網格、時間步長、儲存間隔必須大於 0')  # 阻止不合法運行
    if min(args.start_um, args.end_margin_um) < 0.0:  # 雷射位置不可為負邊界距離
        raise ValueError('起點與終點邊距必須非負')  # 防止負邊距
    metal_mask_cpu, actual_input_path = load_metal_mask(args.powder)  # 讀取原本生成的粉末床與基板
    backend = np  # 預設在 CPU 上使用 NumPy
    if not args.cpu:  # 未強制 CPU 時優先使用 GPU
        try:  # 嘗試使用 CuPy
            import cupy as cp  # GPU 陣列計算
            cp.zeros(1).sum().get()  # 測試 CUDA 是否可用
            backend = cp  # GPU 啟動成功，改由 CuPy 計算
        except Exception as exc:  # GPU 無法使用不阻止計算
            print(f'[INFO] CuPy 不可用，改為 NumPy：{exc}')  # 提示後端降級
    fill_fraction = backend.asarray(metal_mask_cpu, dtype=backend.float64)  # 建立 0/1 初始金屬填充率
    # 獨立 Stage A 沒有溫度與相變求解，故 fL=0；僅驗證初始固態雷射吸收。
    initial_liquid_fraction = backend.zeros_like(fill_fraction)  # 計算或建立初始液態比例（initial_liquid_fraction）
    initial_absorptivity = calculate_phase_absorptivity(initial_liquid_fraction, backend)  # 計算或建立初始（initial_absorptivity）
    voxel_size_m = args.grid_um * 1.0e-6  # 將 µm 轉成 m
    length_x_m = fill_fraction.shape[0] * voxel_size_m  # 模型 X 方向長度
    length_y_m = fill_fraction.shape[1] * voxel_size_m  # 模型 Y 方向長度
    laser_y_m = 0.5 * length_y_m  # 令雷射沿 Y 中央掃描
    scan_speed_m_s = args.speed * 1.0e-3  # 掃描速度由 mm/s 轉為 m/s
    start_x_m = args.start_um * 1.0e-6  # 雷射起點由 µm 轉為 m
    end_margin_m = args.end_margin_um * 1.0e-6  # 終點邊界由 µm 轉為 m
    spot_radius_m = 0.5 * args.spot_diameter * 1.0e-6  # 光斑直徑轉為半徑，單位 m
    _, _, scan_duration_s = calculate_laser_position(0.0, length_x_m, start_x_m, end_margin_m, scan_speed_m_s)  # 計算掃描總時間
    total_steps = math.ceil(scan_duration_s / (args.dt_ns * 1e-9))  # 使用原始時間步長計算位置更新次數
    save_every_steps = max(1, round(args.save_us * 1e-6 / (args.dt_ns * 1e-9)))  # 儲存頻率轉成迭代步數
    output_dir = Path(args.out)  # 指定輸出資料夾
    output_dir.mkdir(parents=True, exist_ok=True)  # 若資料夾不存在就建立
    config = vars(args).copy()  # 複製統一的加工設定
    config["material_absorptivity_solid"] = ABSORPTIVITY_SOLID  # 計算或建立設定（config）的固態（material_absorptivity_solid）欄位
    config["material_absorptivity_liquid"] = ABSORPTIVITY_LIQUID  # 計算或建立設定（config）的液態（material_absorptivity_liquid）欄位
    config["absorptivity_model"] = ABSORPTIVITY_MODEL  # 記錄吸收率為使用者指定值並依液相率插值
    config["standalone_initial_liquid_fraction"] = 0.0  # 光學單測不求熱與相變，全部先視作未熔
    config["minimum_active_metal_fill"] = material.MINIMUM_ACTIVE_METAL_FILL  # 記錄 01 的金屬門檻
    config.update(input_file=str(actual_input_path.resolve()), backend='cupy' if backend is not np else 'numpy',  # 執行 update 呼叫並完成該步處理
                  shape_xyz=list(metal_mask_cpu.shape), scan_duration_us=scan_duration_s*1e6,  # 執行 update 呼叫並完成該步處理
                  model='原 Stage A Gaussian 垂直遮蔽模型；不含反射追跡、多次散射、升溫或相變')  # 紀錄模型條件
    (output_dir / 'laser_config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')  # 寫出中文設定檔
    csv_columns = ['step', 'time_us', 'laser_on', 'laser_x_um', 'laser_y_um', 'laser_power_W',  # 計算或建立CSV檔（csv_columns）
                   'incident_power_domain_W', 'absorbed_power_W', 'unabsorbed_intercepted_W',  # 接續CSV檔（csv_columns）的數值、運算式或資料項目
                   'transmitted_below_domain_W', 'outside_domain_W', 'power_balance_residual_W']  # 定義功率稽核 CSV 欄位
    diagnostic_columns = ['effective_absorptivity_domain', 'global_top2um_absorbed_pct', 'global_top4um_absorbed_pct',  # 新增：有效吸收率與全域頂面診斷
                          'global_top10um_absorbed_pct', 'global_top20um_absorbed_pct',  # 新增：全域深層吸收比例
                          'local_top2um_absorbed_pct', 'local_top4um_absorbed_pct',  # 新增：局部首遇金屬表面診斷
                          'local_top10um_absorbed_pct', 'local_top20um_absorbed_pct',  # 新增：局部深層吸收比例
                          'max_voxel_absorbed_power_W', 'max_voxel_source_W_m3', 'maximum_Z_layer_absorbed_pct']  # 新增：最高單格熱源與集中程度
    csv_path = output_dir / 'laser_power_history.csv'  # CSV 輸出路徑
    print(f'[START] 金屬網格={metal_mask_cpu.shape} backend={config["backend"]} 掃描={scan_duration_s*1e6:.3f} µs')  # 顯示初始條件
    with csv_path.open('w', newline='', encoding='utf-8-sig') as file:  # 使用 Excel 友善的 UTF-8 BOM
        writer = csv.writer(file)  # 建立 CSV 寫入器
        writer.writerow(csv_columns + diagnostic_columns)  # 原功率欄位後面接上新增診斷欄位
        for step in range(total_steps + 1):  # 每個時間步都更新雷射位置
            time_s = min(step * args.dt_ns * 1e-9, scan_duration_s)  # 當前時間不得超過掃描終點
            laser_x_m, laser_on, _ = calculate_laser_position(time_s, length_x_m, start_x_m,  # 計算或建立雷射（laser_x_m）、雷射（laser_on）、變數 _
                                                               end_margin_m, scan_speed_m_s)  # 取得當前光斑位置
            if step % save_every_steps != 0 and step != total_steps:  # 沒到儲存時刻時只更新位置
                continue  # 跳過光場快照的重複計算；粉末不變且本階段不求熱
            active_power_W = args.power if laser_on else 0.0  # 雷射關閉後輸入功率為零
            result = calculate_laser_powder_absorption(fill_fraction, backend, voxel_size_m,  # 計算或建立變數 result
                        laser_x_m, laser_y_m, active_power_W, initial_absorptivity, spot_radius_m)  # 計算本時刻 3D 光學吸收
            as_float = lambda key: float(result[key].get()) if hasattr(result[key], 'get') else float(result[key])  # 取得單一功率數值
            diagnostics = diagnose_laser_absorption_depth(result, fill_fraction, voxel_size_m, backend)  # 新增：計算全域及局部表面吸收率
            scalar = lambda v: float(v.get()) if hasattr(v, 'get') else float(v)  # 將 CPU/GPU scalar 轉成 CSV 數值
            writer.writerow([step, time_s*1e6, int(laser_on), laser_x_m*1e6, laser_y_m*1e6,  # 寫入原本功率資料及深度診斷
                             active_power_W, *[as_float(name) for name in csv_columns[6:]],  # 維持原始功率收支欄位順序
                             *[scalar(diagnostics[name]) for name in diagnostic_columns]])  # 新增：寫入診斷欄位
            file.flush()  # 即時保留目前時間點的紀錄
            snapshot_path = save_snapshot(output_dir, step, time_s, laser_x_m, laser_y_m,  # 計算或建立檔案路徑（snapshot_path）
                                          laser_on, result, backend, diagnostics)  # 儲存 XYZ NPZ 光強及深度診斷
            profile_path = save_absorption_z_profile(output_dir, step, time_s, result, voxel_size_m, backend)  # 新增：輸出每層吸收 CSV
            print(f'[LASER] t={time_s*1e6:.3f} µs x={laser_x_m*1e6:.2f} µm '  # 輸出本階段的數值、進度或診斷訊息
                  f'Pabs={as_float("absorbed_power_W"):.5f} W '  # 輸出本階段的數值、進度或診斷訊息
                  f'Presidual={as_float("power_balance_residual_W"):.3e} W '  # 顯示功率平衡
                  f'Top2_local={scalar(diagnostics["local_top2um_absorbed_pct"]):.2f}% '  # 新增：局部最表面吸收比例
                  f'Top10_local={scalar(diagnostics["local_top10um_absorbed_pct"]):.2f}% → {snapshot_path.name}')  # 新增：深度診斷摘要
    print(f'[DONE] 功率歷程與深度診斷：{csv_path.resolve()}')  # 提示已完成主要診斷 CSV
    print(f'[DONE] 輸出資料夾：{output_dir.resolve()}')  # 程式結束訊息


if __name__ == '__main__':  # 直接執行本 Python 檔案時進入主程序
    main()  # 執行獨立雷射與粉末光學交互作用測試
