# -*- coding: utf-8 -*-
"""
LPBF 三維網格熱傳與相變主程式。

【執行大綱】
01：材料物性；02：加工與數值設定；03：雷射移動、遮蔽與吸收。
04：XYZ 導熱、對流、輻射、底部邊界散熱及粉末／基板界面傳熱。
05：體積焓、溫度、固液相變、熔深與蒸發質量及能量更新。
06 暫停使用；主程式只載入 01～05，保留 06 檔案供之後另行恢復。

【預設停止與輸出】
預設第 10000 step 輸出並終止；每十步記錄一筆，每千步分檔，不追加冷卻。
結果包含熱歷程 CSV、主能量表、相變及導熱明細、設定 JSON 與 NPZ 快照。
已有結果時自動另建目錄；只有指定允許覆寫時才使用既有資料夾。

【能量帳的定義】
顯熱與熔化潛熱是目前存量；另記熔化吸收、凝固釋放與汽化潛熱的累計量。
汽化潛熱另列為相變吸收，蒸發損失只列攜出焓；求解器仍扣除兩者並減少金屬量。
粉末／基板界面導熱屬內部轉移，不能與底部外流重複扣除。
預設蒸發採顯式速率更新及上方直接暴露液面近似，需檢查時間步收斂。
本程式的能量守恆驗證不代表已完成實驗校正或完整流體與蒸氣輸運驗證。
"""
import csv  # 載入CSV 讀寫所需功能
import io  # 未啟用詳細 CSV 時使用記憶體文字流，避免建立多餘檔案
import json  # 載入JSON 設定檔讀寫所需功能
import math  # 載入數學函式所需功能
import os  # 載入環境變數讀取所需功能
import sys  # 共用已載入的材料與階段模組，避免同一檔案產生兩份物性物件
from datetime import datetime  # 重跑時以時間戳另建輸出目錄，保留先前結果
from pathlib import Path  # 載入檔案與資料夾路徑所需功能
import importlib.util  # 載入依檔名動態載入模組所需功能
import numpy as np  # 載入CPU 陣列計算所需功能

# ============================================================================
# 函式大綱｜load_local_module() — 載入工作目錄內的編號模組
# 【輸入】檔名前綴；動態模組別名
# 【計算】依前綴搜尋唯一 Python 檔，以檔名註冊模組並提供別名；重複引用共用同一物件
# 【輸出】已執行初始化的本地模組物件
# ============================================================================
def load_local_module(prefix, alias):  # 定義函式：載入工作目錄內的編號模組
    candidates = list(Path(__file__).resolve().parent.glob(prefix + "*.py"))  # 計算或建立符合前綴的模組檔清單
    if len(candidates) != 1:  # 判斷本行條件，成立時執行下方處理
        raise ImportError(f"Expected one module matching {prefix!r}, found {len(candidates)}")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    module_name = candidates[0].stem  # 與 02～05 的 import_module 使用相同的正式模組名稱
    if module_name in sys.modules:  # 已由其他階段載入時直接共用
        return sys.modules[module_name]  # 避免主程式與子模組各自持有不同的材料物件
    spec = importlib.util.spec_from_file_location(module_name, candidates[0])  # 以正式檔名建立載入規格
    module = importlib.util.module_from_spec(spec)  # 計算或建立動態載入的模組物件
    sys.modules[module_name] = module  # 初始化前註冊，讓相互引用取得同一物件
    try:  # 初始化失敗時不可保留半載入的材料或計算模組
        spec.loader.exec_module(module)  # 執行載入模組的初始化程式
    except BaseException:  # 包含中斷時也恢復模組登錄狀態
        sys.modules.pop(module_name, None)  # 移除未完成的模組
        raise  # 保留原始錯誤供診斷
    sys.modules[alias] = module  # 舊別名也指向同一個已完成初始化的物件
    return module  # 回傳本行計算結果，交由呼叫端繼續使用

material = load_local_module("01_Material Parameters_", "lpbf_material")  # 計算或建立材料物性模組
process = load_local_module("02_process_parameters_", "lpbf_process")  # 計算或建立加工參數模組
laser = load_local_module("03_laser_powder_interaction_", "lpbf_laser")  # 計算或建立雷射模組
heat = load_local_module("04_heat_transfer_", "lpbf_heat")  # 計算或建立熱傳模組
phase = load_local_module("05_enthalpy_phase_", "lpbf_phase")  # 計算或建立相變模組
MODEL_REVISION = 'stage05_thermal_audit_v4_alpha040_025'  # 本版本修正氣體步長、界面導熱診斷與本步蒸發液相判斷

ENERGY_DETAIL_LABELS = (  # 計算或建立相變與導熱明細欄位及中文標籤
    ('Emelting_cumulative_J', '固→液：熔化潛熱吸收（累計）'),  # 接續相變與導熱明細欄位及中文標籤的數值、運算式或資料項目
    ('Esolidification_released_J', '液→固：凝固潛熱釋放（累計）'),  # 接續相變與導熱明細欄位及中文標籤的數值、運算式或資料項目
    ('Evaporization_latent_J', '液→氣：汽化潛熱吸收（主表潛熱項）'),  # 汽化能量歸入潛熱，不再重複列為蒸發損失
    ('Eevaporated_enthalpy_J', '蒸發攜出焓（主表損失項）'),  # 僅移除金屬原本攜有的焓列為蒸發損失
    ('Econd_into_substrate_J', '粉末→基板導熱（累計）'),  # 接續相變與導熱明細欄位及中文標籤的數值、運算式或資料項目
    ('Econd_from_substrate_J', '基板→粉末導熱（累計）'),  # 接續相變與導熱明細欄位及中文標籤的數值、運算式或資料項目
    ('Eevaporated_fusion_latent_J', '蒸發攜出熔化潛熱（攜出焓內含）'),  # 接續相變與導熱明細欄位及中文標籤的數值、運算式或資料項目
    ('Econd_net_into_substrate_J', '粉末→基板淨導熱'),  # 接續相變與導熱明細欄位及中文標籤的數值、運算式或資料項目
    ('Efusion_balance_residual_J', '固液潛熱收支殘差'),  # 接續相變與導熱明細欄位及中文標籤的數值、運算式或資料項目
)  # 結束本段參數、容器或條件的組合

THERMAL_CSV_COLUMNS = (  # 主要兩份 CSV 共用分類、英文識別字與中文欄位名稱
    ('時間', 'step', '計算步數'),  # 時間步序號
    ('時間', 'time_us', '模擬時間'),  # 單位 µs
    ('雷射', 'laser_x_um', '雷射位置'),  # 單位 µm
    ('溫度－固態', 'Tmax_solid_K', '固態最高溫度'),  # 包含初始固態與已再凝固金屬，無該相時留白
    ('溫度－液態', 'Tmax_liquid_K', '液態最高溫度'),  # 只取液態相碼網格，無該相時留白
    ('溫度－保護氣體', 'Tmax_argon_K', '氬氣最高溫度'),  # 氣體區沿用氬氣物性的局部熱平衡溫度
    ('溫度－金屬蒸氣', 'Tmax_metal_vapor_K', '金屬蒸氣最高溫度（未計算）'),  # 尚無獨立蒸氣溫度場
    ('相變－固態', 'solid_cells', '固態體素數'),  # 不含另列的再凝固體素
    ('相變－固液共存', 'mushy_cells', '固液共存體素數'),  # 相態代碼 2 的網格數
    ('相變－液態', 'liquid_cells', '液態體素數'),  # 相態代碼 3 的網格數
    ('相變－凝固', 'resolidified_cells', '已重新凝固體素數'),  # 相態代碼 4 的網格數
    ('相態－保護氣體', 'argon_cells', '氬氣區體素數'),  # 氣體相碼包含原有空隙及蒸發後空間，均採氬氣物性
    ('相態－金屬蒸氣', 'metal_vapor_cells', '金屬蒸氣體素數（未計算）'),  # 不把蒸發後的空隙直接當作蒸氣體素
    ('質量－金屬蒸氣', 'metal_vapor_generated_kg', '累積汽化金屬質量'),  # 已從金屬移除的質量，不代表域內蒸氣存量
    ('熔深－液態', 'Dsub_liquid_um', '基板當前液態熔深'),  # 單位 µm
    ('熔深－歷史', 'Dsub_ever_um', '基板歷史最大熔深'),  # 曾熔化的最深位置不因後續蒸發回退
    ('功率－雷射', 'Pincident_W', '雷射入射功率（W）'),  # 雷射開啟時維持設定功率，不隨步數累加
    ('能量－雷射', 'Eincident_J', '單步雷射入射能量（J）'),  # 功率乘實際單步時間，不隨記錄步數累加
    ('能量－吸收', 'Eabs_J', '材料吸收能量'),  # 全域實際吸收能量，單位 J
    ('顯熱－固態', 'Esensible_solid_J', '固態顯熱變化'),  # 共存區依固相比例分配
    ('顯熱－液態', 'Esensible_liquid_J', '液態顯熱變化'),  # 共存區依液相比例分配，兩項相加等於金屬顯熱
    ('顯熱－保護氣體', 'Esensible_argon_J', '氬氣顯熱變化'),  # 原氣體熱容量使用 01 的氬氣物性
    ('顯熱－金屬蒸氣', 'Esensible_metal_vapor_J', '域內金屬蒸氣顯熱（未計算）'),  # 不能把累積攜出焓當成域內蒸氣儲能
    ('潛熱－固液', 'Elatent_fusion_J', '熔化／凝固潛熱變化'),  # 域內熔化潛熱存量相對初始的變化
    ('潛熱－液氣', 'Elatent_vaporization_J', '汽化／凝結潛熱變化'),  # 目前只計汽化吸收，尚未建立凝結模型
    ('熱損失－對流', 'Econv_J', '對流損耗'),  # 累積對流外流能量，單位 J
    ('熱損失－輻射', 'Erad_J', '輻射損耗'),  # 累積輻射外流能量，單位 J
    ('熱損失－導熱', 'Ebottom_J', '底部導熱損耗'),  # 不包含粉末與基板間的內部傳熱
    ('熱損失－蒸發', 'Eevap_J', '蒸發帶走的能量'),  # 只含攜出焓；汽化潛熱已另列，不能重複加總
    ('流動－液態', 'Umax_liquid_m_s', '最大液態金屬流速'),  # 目前未求解流動，輸出空白
    ('流動－保護氣體', 'Umax_argon_m_s', '最大氬氣流速（未計算）'),  # 目前未求解保護氣流
    ('流動－金屬蒸氣', 'Umax_metal_vapor_m_s', '最大金屬蒸氣流速（未計算）'),  # 尚未建立蒸氣輸運
    ('守恆', 'energy_error_pct', '能量守恆誤差'),  # 使用求解器完整能量收支計算的相對誤差
)  # 共有 33 個欄位，區分功率與累積能量、保護氣體與金屬蒸氣

DIAGNOSTIC_CSV_LABELS = {  # 選用診斷 CSV 也使用中英對照標頭
    **{name: meaning for _, name, meaning in THERMAL_CSV_COLUMNS},  # 主要欄位沿用相同中文名稱
    'Tmax_gas_K': '氬氣最高溫度', 'gas_cells': '氬氣區體素數',  # 詳細診斷保留舊英文識別字，中文明確標示物種
    'Eincident_cumulative_J': '累積雷射入射能量（J）',  # 累積量另用明確名稱，避免與主表單步量混淆
    'Esensible_gas_J': '氬氣顯熱變化', 'Umax_gas_m_s': '最大氬氣流速（未計算）',  # 舊氣體欄不代表金屬蒸氣
    'laser_on': '雷射開啟狀態', 'laser_y_um': '雷射Y座標', 'Tmax_K': '全域最高溫度',  # 雷射與溫度
    'Tmax_metal_K': '金屬最高溫度', 'Tmin_metal_K': '金屬最低溫度',  # 金屬溫度診斷
    'Esensible_J': '顯熱變化合計', 'Esensible_metal_J': '金屬顯熱變化合計', 'Elatent_J': '熔化潛熱存量變化',  # 完整能量分解
    'Esensible_pct_Eabs': '顯熱占吸收能量百分比', 'Elatent_pct_Eabs': '熔化潛熱占吸收能量百分比',  # 詳細百分比
    'Eevap_total_removed_J': '蒸發總移除能量含汽化潛熱', 'Estored_J': '目前總焓',  # 求解器守恆帳
    'Dsub_mushy_um': '基板固液共存熔深', 'solidification_completed': '是否完成凝固',  # 相變診斷
    'Qlaser_W_m3_max': '雷射熱源最大值', 'Qcond_W_m3_at_Tmax': '最高溫位置導熱項',  # 體積熱源單位見英文欄名
    'Qconv_W_m3_at_Tmax': '最高溫位置對流項', 'Qrad_W_m3_at_Tmax': '最高溫位置輻射項',  # 邊界熱源
    'Qevap_diagnostic_W_m3_at_Tmax': '最高溫位置蒸發項',  # 本步實際蒸發熱源
    'Pconv_W': '對流損失功率', 'Prad_W': '輻射損失功率', 'Pevap_W': '蒸發總移除功率', 'Aconv_rad_m2': '對流輻射暴露面積',  # 功率與面積
    'Eresidual_J': '能量收支殘差', 'Eresidual_pct': '能量收支殘差百分比', 'evaporated_mass_kg': '累積蒸發金屬質量',  # 守恆與質量
    **dict(ENERGY_DETAIL_LABELS),  # 相變與導熱過程量使用既有精確標籤
    'Elatent_accounted_J': '熔化存量加汽化吸收', 'Elatent_accounted_pct_Eabs': '潛熱項合計百分比',  # 報表合計
    'Evaporization_latent_pct_Eabs': '汽化潛熱百分比', 'Eevap_enthalpy_loss_J': '蒸發攜出焓損失',  # 蒸發分項
    'Eevap_enthalpy_loss_pct_Eabs': '蒸發攜出焓百分比',  # 不包含已另列汽化潛熱
    'i': '網格X索引', 'j': '網格Y索引', 'k': '網格Z索引',  # 網格索引
    'x_um': '網格X座標', 'y_um': '網格Y座標', 'z_um': '網格Z座標',  # 網格中心座標
    'laser_distance_xy_um': '網格距雷射平面距離', 'F': '金屬填充率', 'T_K': '網格溫度', 'H_J_m3': '網格體積焓',  # 單格狀態
    'E_laser_J': '單格累積雷射吸收', 'E_conduction_signed_J': '單格累積淨導熱',  # 固定網格累積量
    'E_convection_loss_J': '單格累積對流損失', 'E_radiation_loss_J': '單格累積輻射損失', 'E_bottom_loss_J': '單格累積底部外流',  # 單格損失
    'E_net_J': '單格累積淨能量', 'delta_H_times_volume_J': '單格總焓變化',  # 審計主項
    'closure_residual_J': '單格收支閉合殘差', 'closure_error_pct': '單格收支誤差百分比',  # 閉合檢查
    'Qlaser_last_W_m3': '上一步雷射熱源', 'Qnet_last_W_m3': '上一步淨熱源', 'Qcond_last_W_m3': '上一步導熱項',  # 最近使用的熱源
    'Qconv_last_W_m3': '上一步對流項', 'Qrad_last_W_m3': '上一步輻射項', 'Qevap_diagnostic_last_W_m3': '上一步蒸發項',  # 最近使用的損失
    'Psub_W': '粉末傳入基板淨功率', 'qmean_contact_W_m2': '界面平均熱通量',  # 界面診斷
    'contact_fraction': '金屬接觸比例', 'contact_voxels': '金屬接觸網格數',  # 幾何接觸
    'Tmax_substrate_K': '基板最高溫度', 'Tmax_powder_K': '粉末區最高溫度',  # 分區最高溫
    'hotspot_i': '最高溫X索引', 'hotspot_j': '最高溫Y索引', 'hotspot_k': '最高溫Z索引', 'Tmax_hotspot_K': '最高溫網格溫度',  # 熱點座標
    'F_at_Tmax': '最高溫網格填充率', 'mass_at_Tmax_kg': '最高溫網格金屬質量', 'H_at_Tmax_J_m3': '最高溫網格體積焓',  # 熱點材料
    'Qlaser_at_Tmax_W_m3': '熱點雷射熱源', 'Qcond_at_Tmax_W_m3': '熱點導熱項', 'Qnet_at_Tmax_W_m3': '熱點淨熱源',  # 熱點熱源
    'Qconv_at_Tmax_W_m3': '熱點對流項', 'Qrad_at_Tmax_W_m3': '熱點輻射項', 'Qevap_diagnostic_at_Tmax_W_m3': '熱點蒸發項',  # 熱點損失
    'P_into_substrate_W': '傳入基板正向功率', 'P_out_of_substrate_W': '基板回傳功率',  # 雙向導熱
    'positive_contact_voxels': '正向導熱接觸網格數', 'negative_contact_voxels': '反向導熱接觸網格數',  # 導熱方向
    'P_laser_absorbed_total_W': '總雷射吸收功率', 'P_laser_absorbed_substrate_W': '基板吸收功率', 'P_laser_absorbed_powder_W': '粉末區吸收功率',  # 分區吸收
    'laser_z_peak_index': '最大吸收Z層索引', 'laser_z_peak_center_um': '最大吸收Z層中心', 'laser_z_peak_W': '最大吸收層功率',  # 層吸收峰值
    'recoil_pressure_max_Pa': '最大反衝壓力', 'keyhole_candidate_voxels': '開孔候選網格數',  # 簡化表面壓力診斷
    'z_index': 'Z層索引', 'z_center_um': 'Z層中心', 'absorbed_power_W': '雷射吸收功率', 'fraction_of_absorbed_power': '占總吸收功率比例',  # 逐層功率
    'incident_power_W': '入射功率', 'intercepted_power_W': '金屬攔截功率', 'reflected_power_W': '反射功率',  # 逐層收支
    'scan_distance_um': '從起點前進距離', 'scan_fraction_pct': '完整掃描距離百分比', 'incident_energy_J': '累積雷射入射能量（J）',  # 對照吸收量時須使用同一累積時間範圍
    'solid_reference_absorptivity_pct': '固態參考吸收率百分比', 'theoretical_absorbed_J': '固定固態吸收率參考能量',  # 參考值不是實際有效吸收率
    'actual_absorbed_J': '實際雷射吸收能量', 'actual_minus_theory_J': '實際減參考吸收能量', 'relative_error_pct': '相對參考值差異百分比',  # 吸收對照
    'energy_item': '能量項目', 'energy_J': '能量', 'percent_of_absorbed': '占吸收能量百分比',  # 能量長表
    'incident_power_domain_W': '域內入射功率', 'outside_domain_W': '域外雷射功率',  # 雷射域邊界
    'reflected_or_scattered_W': '反射或散射功率', 'transmitted_below_domain_W': '底部透射功率',  # 未吸收功率
    'power_balance_residual_W': '雷射功率收支殘差', 'incident_energy_cumulative_J': '累積入射能量', 'absorbed_energy_cumulative_J': '累積吸收能量',  # 雷射驗證
}  # 診斷欄位與主要欄位分開管理，主表共 33 欄


# ============================================================================
# 函式大綱｜bilingual_csv_header() — 建立詳細 CSV 的中英欄名
# 【輸入】英文欄位識別字清單
# 【計算】以固定字典查找中文意思，未知欄位立即回報以免靜默錯標
# 【輸出】英文與中文以直線分隔的單列標頭
# ============================================================================
def bilingual_csv_header(names):  # 供所有選用診斷 CSV 共用
    return [f'{name}｜{DIAGNOSTIC_CSV_LABELS[name]}' for name in names]  # 強制每個輸出欄位都有中英對照


# ============================================================================
# 函式大綱｜thermal_csv_header() — 建立中英對照的主要 CSV 欄名
# 【輸入】無，使用 THERMAL_CSV_COLUMNS 的固定欄位順序
# 【計算】以直線分隔英文識別字與中文意思，維持單列標頭以利試算表讀取
# 【輸出】33 個中英欄位名稱
# ============================================================================
def thermal_csv_header():  # 主要 CSV 採單列中英標頭
    return [f'{name}｜{meaning}' for _, name, meaning in THERMAL_CSV_COLUMNS]  # 英文識別字保留單位資訊，中文提供閱讀意義


# ============================================================================
# 函式大綱｜write_segmented_history() — 每千步分檔保存時間歷程
# 【輸入】輸出目錄、當前步數及中英欄位對應資料列
# 【計算】將步數 1～1000 歸第一檔、1001～2000 歸第二檔，依此類推
# 【輸出】UTF-8 BOM CSV；每筆寫入後關檔，避免中斷時遺失緩衝資料
# ============================================================================
def write_segmented_history(output_dir, step, row):  # 由主迴圈每十步呼叫
    first_step = ((step - 1) // 1000) * 1000 + 1  # 整千步歸屬上一段，避免多出第十一檔
    last_step = first_step + 999  # 檔名顯示所涵蓋的計算步數範圍
    path = output_dir / f'thermal_history_{first_step:05d}_{last_step:05d}.csv'  # 依範圍命名並方便排序
    first_record = step == first_step + 9 or not path.exists()  # 每段首筆重建檔案，避免覆寫模式混入舊資料
    with path.open('w' if first_record else 'a', newline='', encoding='utf-8-sig') as history_stream:  # 每次完成即關閉檔案
        history_writer = csv.writer(history_stream)  # 建立本段資料寫入器
        if first_record:  # 每個檔案只寫一列中英標頭
            history_writer.writerow(thermal_csv_header())  # 每段都能獨立閱讀
        history_writer.writerow(row)  # 儲存當前十步採樣點的完整資料


# ============================================================================
# 函式大綱｜phase_max_temperature() — 取得指定相態的最高溫度
# 【輸入】溫度陣列、相態遮罩、NumPy／CuPy 後端
# 【計算】只對指定相態求最大值，沒有該相態時不虛構零溫度
# 【輸出】最高溫度（K）；無該相態時回傳空字串
# ============================================================================
def phase_max_temperature(temperature, mask, xp):  # 供固態、液態與氣態溫度欄位共用
    if not bool(scalar(xp.any(mask))):  # 檢查當前是否有該相態
        return ''  # 留白表示無此相態，不使用零或 NaN 冒充溫度
    return scalar(xp.max(xp.where(mask, temperature, -xp.inf)))  # 只對選定相態計算最大溫度



# ============================================================================
# 函式大綱｜scalar() — 將運算後端純量轉成 Python 數值
# 【輸入】待轉換數值
# 【計算】GPU 值先傳回 CPU，CPU 值直接轉為浮點數
# 【輸出】Python 浮點數；GPU 傳回可能等待尚未完成的運算
# ============================================================================
def scalar(value):  # 定義函式：將運算後端純量轉成 Python 數值
    """將運算後端純量轉成 Python 數值。
    計算：GPU 值先傳回 CPU，CPU 值直接轉為浮點數。
    輸出：Python 浮點數；GPU 傳回可能等待尚未完成的運算。
    """
    return float(value.get()) if hasattr(value, 'get') else float(value)  # 回傳本行計算結果，交由呼叫端繼續使用


# ============================================================================
# 函式大綱｜prepare_output_directory() — 建立本次獨立輸出目錄
# 【輸入】原指定輸出目錄；允許使用既有目錄的開關
# 【計算】嘗試建立目錄；已有資料時加上時間戳與序號，除非明確允許覆寫
# 【輸出】可寫入的本次輸出路徑，預設保留舊結果
# ============================================================================
def prepare_output_directory(requested_dir, allow_existing=False):  # 定義函式：建立本次獨立輸出目錄
    """建立本次獨立輸出目錄。
    計算：嘗試建立目錄；已有資料時加上時間戳與序號，除非明確允許覆寫。
    輸出：可寫入的本次輸出路徑，預設保留舊結果。
    """
    requested_dir = Path(requested_dir)  # 計算或建立原指定輸出目錄
    output_dir = requested_dir  # 計算或建立本次輸出目錄
    run_stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')  # 計算或建立本次輸出的時間戳
    attempt = 0  # 計算或建立輸出目錄名稱嘗試次數
    while True:  # 只要本行條件仍成立，就持續重試或處理
        try:  # 嘗試執行可能失敗的載入、寫檔或運算
            output_dir.mkdir(parents=True)  # 建立輸出目錄及必要的上層目錄
            return output_dir  # 回傳本行計算結果，交由呼叫端繼續使用
        except FileExistsError:  # 攔截本行指定的例外並採取對應處理
            if output_dir.is_dir() and (allow_existing or not any(output_dir.iterdir())):  # 判斷本行條件，成立時執行下方處理
                return output_dir  # 回傳本行計算結果，交由呼叫端繼續使用
            attempt += 1  # 累加至輸出目錄名稱嘗試次數
            suffix = f'_{attempt}' if attempt > 1 else ''  # 計算或建立避免名稱重複的序號尾碼
            output_dir = requested_dir.with_name(f'{requested_dir.name}_{run_stamp}{suffix}')  # 計算或建立本次輸出目錄


# ============================================================================
# 函式大綱｜write_distance_energy_report() — 輸出指定掃描距離的能量表
# 【輸入】主能量 CSV 寫入器；Markdown 能量表檔案；時間步序號；模擬時間（s）；相對起點的掃描距離（µm）；累積雷射吸收能量（J）
# 【續輸入】金屬顯熱（J）；氣體顯熱（J）；熔化潛熱存量（J）；底部邊界損失；對流熱損失；輻射熱損失
# 【續輸入】蒸發損失（J）；相變及導熱明細字典；明細 CSV 寫入器
# 【計算】以吸收能量為百分比分母，分列儲能、外流及不重複加總的相變與導熱明細
# 【輸出】終端及 Markdown 表格、主能量 CSV 與選用明細 CSV
# ============================================================================
def write_distance_energy_report(csv_writer, markdown_stream, step, time_s,  # 定義函式：輸出指定掃描距離的能量表
                                 distance_um, absorbed, sensible_metal, sensible_gas, latent,  # 接續函式參數：相對起點的掃描距離（µm）、累積雷射吸收能量（J）、金屬顯熱（J）、氣體顯熱（J）、熔化潛熱存量（J）
                                 bottom, convection, radiation, evaporation,  # 接續函式參數：底部邊界損失、對流熱損失、輻射熱損失、蒸發損失（J）
                                 details=None, details_writer=None):  # 接續函式參數：相變及導熱明細字典、明細 CSV 寫入器
    """輸出指定掃描距離的能量表。
    計算：以吸收能量為百分比分母，分列儲能、外流及不重複加總的相變與導熱明細。
    輸出：終端及 Markdown 表格、主能量 CSV 與選用明細 CSV。
    """
    sensible = sensible_metal + sensible_gas  # 計算或建立金屬加氣體的顯熱（J）
    vaporization_latent = details['Evaporization_latent_J'] if details is not None else 0.0  # 取出液轉氣所吸收的汽化潛熱
    carried_enthalpy_loss = evaporation - vaporization_latent  # 從蒸發總移除量扣除汽化潛熱，只留下攜出焓損失
    latent_accounted = latent + vaporization_latent  # 熔化存量加累積汽化吸收，不代表全為域內存量
    residual = absorbed - sensible - latent_accounted - bottom - convection - radiation - carried_enthalpy_loss  # 分類改變後汽化能量仍只計一次
    rows = [  # 計算或建立能量項目與數值資料列
        ("吸收的雷射能量", absorbed),  # 接續能量項目與數值資料列的數值、運算式或資料項目
        ("顯熱增加（金屬，含固液態）", sensible_metal),  # 金屬顯熱包含固態、固液共存與液態的升溫能量
        ("顯熱增加（氣體）", sensible_gas),  # 接續能量項目與數值資料列的數值、運算式或資料項目
        ("熔化潛熱存儲", latent),  # 接續能量項目與數值資料列的數值、運算式或資料項目
        ("汽化潛熱吸收（液→氣）", vaporization_latent),  # 汽化吸收明確列為潛熱，不列為蒸發損失
        ("底部導熱邊界損失（全域外流）", bottom),  # 接續能量項目與數值資料列的數值、運算式或資料項目
        ("對流損失", convection),  # 接續能量項目與數值資料列的數值、運算式或資料項目
        ("輻射損失", radiation),  # 接續能量項目與數值資料列的數值、運算式或資料項目
        ("蒸發攜出焓損失（不含汽化潛熱）", carried_enthalpy_loss),  # 損失只剩移除金屬攜出的原有焓
        ("能量平衡殘差", residual),  # 接續能量項目與數值資料列的數值、運算式或資料項目
    ]  # 結束本段參數、容器或條件的組合
    lines = [f"### 掃描距離 {distance_um:.6f} µm，時間 {time_s * 1e6:.6f} µs",  # 計算或建立準備輸出的 Markdown 文字行
             "", "| 能量項目 | 能量（J） | 占吸收能量 |",  # 接續準備輸出的 Markdown 文字行的數值、運算式或資料項目
             "| :------ | ------: | ------: |"]  # 接續準備輸出的 Markdown 文字行的數值、運算式或資料項目
    for label, energy in rows:  # 依序處理label, energy，逐項套用下方運算
        percentage = 100.0 * energy / absorbed if absorbed > 0.0 else 0.0  # 計算或建立相對雷射吸收能量的百分比
        if csv_writer is not None:  # 主程式改用精簡寬表，僅獨立呼叫時選擇輸出原長表
            csv_writer.writerow([step, time_s * 1e6, distance_um, label, energy, percentage])  # 原長表僅在提供寫入器時輸出
        percent_text = f"{percentage:.3e}%" if 0.0 < abs(percentage) < 0.01 else f"{percentage:.2f}%"  # 計算或建立百分比顯示文字
        lines.append(f"| {label} | {energy:.5e} | {percent_text} |")  # 將本行項目加入清單尾端
    sensible_pct = 100.0 * sensible / absorbed if absorbed > 0.0 else 0.0  # 計算或建立顯熱百分比（sensible_pct）
    latent_accounted_pct = 100.0 * latent_accounted / absorbed if absorbed > 0.0 else 0.0  # 計算兩個潛熱項合計占比
    lines.extend(["", f"顯熱增加合計：{sensible:.5e} J（{sensible_pct:.2f}%）。",  # 把本行各項依序加入清單
                  f"潛熱項合計（熔化存量＋汽化吸收）：{latent_accounted:.5e} J（{latent_accounted_pct:.2f}%）。",  # 合計說明不再重複加入主表能量
                  "金屬顯熱包含固態、固液共存及液態升溫；熔化潛熱另列，避免重複計算。",  # 說明液態金屬顯熱已計入金屬項
                  "汽化潛熱是累積相變吸收，並非域內熔化潛熱存量；物理計算仍扣除此能量。",  # 分清相變吸收與域內存量
                  "蒸發攜出焓損失不再包含汽化潛熱，兩項各列一次，避免重複計算。"])  # 說明新的潛熱與損失分類
    if details is not None:  # 判斷本行條件，成立時執行下方處理
        lines.extend(["", "相變與內部導熱明細（以下不與上表重複加總）：", "",  # 把本行各項依序加入清單
                      "| 項目 | 能量（J） | 相對吸收能量 |", "| :--- | ---: | ---: |"])  # 把本行各項依序加入清單
        for key, label in ENERGY_DETAIL_LABELS:  # 依序處理key, label，逐項套用下方運算
            energy = details[key]  # 計算或建立該項能量（J）
            percentage = 100.0 * energy / absorbed if absorbed > 0 else 0.0  # 計算或建立相對雷射吸收能量的百分比
            percent_text = f'{percentage:.3e}%' if 0 < abs(percentage) < 0.01 else f'{percentage:.2f}%'  # 計算或建立百分比顯示文字
            lines.append(f'| {label} | {energy:.5e} | {percent_text} |')  # 將本行項目加入清單尾端
            if details_writer is not None:  # 判斷本行條件，成立時執行下方處理
                details_writer.writerow([step, time_s * 1e6, distance_um, label, energy, percentage])  # 依既定欄位順序寫入一列 CSV 資料
        lines.extend(["", "熔化吸收與凝固釋放是累計過程量，可能反覆發生；汽化潛熱已列入主表潛熱項。",  # 明細汽化潛熱不再額外加總
                      "傳入基板的導熱仍留在全域模型內，不能再次當作全域損失扣除。"])  # 把本行各項依序加入清單
    table = "\n".join(lines) + "\n\n"  # 計算或建立變數 table
    markdown_stream.write(table)  # 將報表文字寫入檔案
    markdown_stream.flush()  # 將已寫入的緩衝資料送往檔案
    print(table, flush=True)  # 輸出本階段的數值、進度或診斷訊息


# ============================================================================
# 函式大綱｜apply_boiling_plateau_evaporation() — 執行舊版沸點蒸發對照
# 【輸入】體積焓 H（J/m³）；金屬填充率 F；蒸發前淨熱源（W/m³）；時間步長（s）；暴露面積係數；液相率陣列
# 【續輸入】網格邊長（m）；NumPy／CuPy 運算後端 xp；是否附回蒸發前預測溫度
# 【計算】以超過沸點的焓換算移除金屬量，將剩餘材料設回沸點並記錄反衝診斷
# 【輸出】蒸發功率密度、剩餘填充率、開孔候選數、最大反衝壓與選用預測溫度
# ============================================================================
def apply_boiling_plateau_evaporation(H, F, base_power_W_m3, dt_s,  # 定義函式：執行舊版沸點蒸發對照
                                     exposed_area_factor, liquid_fraction,  # 接續函式參數：暴露面積係數、液相率陣列
                                     voxel_size_m, xp, return_temperature=False):  # 接續函式參數：網格邊長（m）、NumPy／CuPy 運算後端 xp、是否附回蒸發前預測溫度
    """執行舊版沸點蒸發對照。
    計算：以超過沸點的焓換算移除金屬量，將剩餘材料設回沸點並記錄反衝診斷。
    輸出：蒸發功率密度、剩餘填充率、開孔候選數、最大反衝壓與選用預測溫度。
    """
    if dt_s <= 0.0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("dt_s must be positive")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    if exposed_area_factor.shape != F.shape:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("exposed_area_factor shape must match metal_fill_fraction")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值

    boiling_K = material.BOILING_TEMPERATURE_K  # 計算或建立標準沸點（K）
    boiling_T = xp.full_like(F, boiling_K, dtype=xp.float64)  # 計算或建立沸點（boiling_T）
    H_before_evaporation = H + base_power_W_m3 * dt_s  # 計算或建立蒸發前預測體積焓
    H_at_boiling = phase.total_enthalpy_from_temperature(boiling_T, F, xp)  # 計算或建立目前金屬量對應的沸點焓
    T_before = phase.temperature_from_enthalpy(H_before_evaporation, F, xp)  # 由加入本步淨熱源後的總體積焓，反算蒸發前預測溫度
    exponent = (material.LATENT_HEAT_VAPORIZATION_J_KG * material.MOLAR_MASS_KG_MOL *  # 計算或建立變數 exponent
                (T_before - boiling_K) /  # 接續變數 exponent的數值、運算式或資料項目
                (material.UNIVERSAL_GAS_CONSTANT_J_MOL_K *  # 接續變數 exponent的數值、運算式或資料項目
                 xp.maximum(T_before, 1.0) * boiling_K))  # 接續變數 exponent的數值、運算式或資料項目
    recoil_pressure_Pa = 0.54 * 101325.0 * xp.exp(xp.clip(exponent, -700.0, 100.0))  # 計算或建立反衝壓力（recoil_pressure_Pa）
    surface_tension = xp.maximum(  # 計算或建立表面（surface_tension）
        material.SURFACE_TENSION_N_M + material.SURFACE_TENSION_TEMP_COEFF_N_M_K *  # 接續表面（surface_tension）的參數：逐項取較大值以限制下界
        (T_before - 293.15), 1e-6)  # 接續表面（surface_tension）的參數：逐項取較大值以限制下界
    capillary_pressure_Pa = 2.0 * surface_tension / voxel_size_m  # 計算或建立毛細壓力（capillary_pressure_Pa）
    opening = recoil_pressure_Pa > (101325.0 + capillary_pressure_Pa)  # 計算或建立反衝壓是否克服環境壓與毛細壓
    exposed_liquid = ((exposed_area_factor > 0.0) &  # 計算或建立暴露且充分液化的金屬遮罩
                      (liquid_fraction >= 0.99) &  # 接續暴露且充分液化的金屬遮罩的數值、運算式或資料項目
                      (F >= material.MINIMUM_ACTIVE_METAL_FILL))  # 接續暴露且充分液化的金屬遮罩的數值、運算式或資料項目
    evaporating = exposed_liquid & (T_before > boiling_K)  # 計算或建立允許蒸發的網格遮罩
    superheat_energy_J_m3 = xp.where(  # 計算或建立超過沸點的體積焓
        evaporating,  # 接續超過沸點的體積焓的參數：依布林遮罩選擇對應分支數值
        xp.maximum(H_before_evaporation - H_at_boiling, 0.0),  # 接續超過沸點的體積焓的參數：依布林遮罩選擇對應分支數值
        0.0)  # 接續超過沸點的體積焓的參數：依布林遮罩選擇對應分支數值
    evaporated_mass_density_kg_m3 = (  # 計算或建立已蒸發質量密度（evaporated_mass_density_kg_m3）
        superheat_energy_J_m3 /  # 接續已蒸發質量密度（evaporated_mass_density_kg_m3）的數值、運算式或資料項目
        max(material.LATENT_HEAT_VAPORIZATION_J_KG, 1e-30))  # 接續已蒸發質量密度（evaporated_mass_density_kg_m3）的數值、運算式或資料項目
    delta_F = evaporated_mass_density_kg_m3 / material.SOLID_DENSITY_KG_M3  # 計算或建立變數 delta_F
    F_next = xp.where(evaporating, xp.maximum(F - delta_F, 0.0), F)  # 扣除蒸發質量對應的金屬填充率，並確保不出現負金屬量
    H_after_evaporation = phase.total_enthalpy_from_temperature(  # 計算或建立舊模型蒸發後的沸點焓
        boiling_T, F_next, xp)  # 接續舊模型蒸發後的沸點焓的參數：由溫度計算混合體積焓
    energy_removed = xp.where(  # 計算或建立蒸發移除的體積能量
        evaporating,  # 接續蒸發移除的體積能量的參數：依布林遮罩選擇對應分支數值
        xp.maximum(H_before_evaporation - H_after_evaporation, 0.0),  # 接續蒸發移除的體積能量的參數：依布林遮罩選擇對應分支數值
        0.0)  # 接續蒸發移除的體積能量的參數：依布林遮罩選擇對應分支數值
    q_evap = energy_removed / dt_s  # 將舊沸點模型本步移除的體積能量除以時間步，換成蒸發功率密度
    candidate_count = xp.count_nonzero(exposed_liquid & opening)  # 計算或建立開孔候選數
    max_recoil_pressure = xp.max(recoil_pressure_Pa)  # 計算或建立最大反衝壓
    result = (q_evap, F_next, candidate_count, max_recoil_pressure)  # 計算或建立變數 result
    return result + (T_before,) if return_temperature else result  # 回傳本行計算結果，交由呼叫端繼續使用


# ============================================================================
# 函式大綱｜apply_rate_limited_evaporation() — 以表面蒸發速率更新質量與能量
# 【輸入】體積焓 H（J/m³）；金屬填充率 F；蒸發前淨熱源（W/m³）；時間步長（s）；暴露面積係數；網格邊長（m）
# 【續輸入】NumPy／CuPy 運算後端 xp；蒸發係數；金屬蒸氣背壓（Pa）；是否附回蒸發前預測溫度
# 【計算】用蒸發前預測溫度計算速率，同步移除汽化潛熱與金屬攜出焓；不強制回到沸點
# 【輸出】蒸發熱源、剩餘金屬量與壓力診斷；顯式更新須檢查時間步收斂
# ============================================================================
def apply_rate_limited_evaporation(H, F, base_power_W_m3, dt_s,  # 定義函式：以表面蒸發速率更新質量與能量
                                   exposed_area_factor, voxel_size_m, xp,  # 接續函式參數：暴露面積係數、網格邊長（m）、NumPy／CuPy 運算後端 xp
                                   accommodation=heat.EVAPORATION_ACCOMMODATION,  # 接續函式參數：蒸發係數
                                   vapor_back_pressure_Pa=heat.EVAPORATION_BACK_PRESSURE_PA,  # 接續函式參數：金屬蒸氣背壓（Pa）
                                   return_temperature=False):  # 回傳蒸發熱源、剩餘金屬量與壓力診斷；顯式更新須檢查時間步收斂
    """以表面蒸發速率更新質量與能量。
    計算：用蒸發前預測溫度計算速率，同步移除汽化潛熱與金屬攜出焓；不強制回到沸點。
    輸出：蒸發熱源、剩餘金屬量與壓力診斷；顯式更新須檢查時間步收斂。
    """
    if dt_s <= 0.0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("dt_s must be positive")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    H_before = H + base_power_W_m3 * dt_s  # 計算或建立蒸發前預測體積焓
    T_before = phase.temperature_from_enthalpy(H_before, F, xp)  # 由加入本步淨熱源後的總體積焓，反算蒸發前預測溫度
    h_metal = xp.maximum(phase.specific_enthalpy_from_temperature(T_before, xp), 0.0)  # 取得蒸發金屬的顯熱加熔化潛熱比焓，用於計算攜出能量
    q_requested = heat.calculate_evaporation_loss(  # 由表面面積、飽和蒸氣壓與蒸發係數求要求的熱損失率
        T_before, F, voxel_size_m, dt_s, xp,  # 接續速率模型要求的蒸發功率密度的參數：估算速率限制的蒸發熱損失
        accommodation=accommodation, vapor_back_pressure_Pa=vapor_back_pressure_Pa,  # 接續速率模型要求的蒸發功率密度的參數：估算速率限制的蒸發熱損失
        evaporation_area_factor=exposed_area_factor,  # 接續速率模型要求的蒸發功率密度的參數：估算速率限制的蒸發熱損失
        metal_specific_enthalpy_J_kg=h_metal)  # 接續速率模型要求的蒸發功率密度的參數：估算速率限制的蒸發熱損失
    q_evap = xp.minimum(q_requested, xp.maximum(H_before, 0.0) / dt_s)  # 限制蒸發能量移除量，避免超出本步可用焓或速率模型所需值
    removed_mass_density = q_evap * dt_s / (material.LATENT_HEAT_VAPORIZATION_J_KG + h_metal)  # 用本步蒸發能量除以汽化潛熱加攜出比焓，換算移除質量密度
    F_next = xp.maximum(F - removed_mass_density / material.SOLID_DENSITY_KG_M3, 0.0)  # 扣除蒸發質量對應的金屬填充率，並確保不出現負金屬量
    exponent = (material.LATENT_HEAT_VAPORIZATION_J_KG * material.MOLAR_MASS_KG_MOL /  # 計算或建立變數 exponent
                material.UNIVERSAL_GAS_CONSTANT_J_MOL_K *  # 接續變數 exponent的數值、運算式或資料項目
                (1.0 / material.BOILING_TEMPERATURE_K - 1.0 / xp.maximum(T_before, 1.0)))  # 接續變數 exponent的數值、運算式或資料項目
    p_sat = 101325.0 * xp.exp(xp.clip(exponent, -80.0, 25.0))  # 計算或建立飽和金屬蒸氣壓
    exposed = ((exposed_area_factor > 0.0) & (T_before >= material.LIQUIDUS_TEMPERATURE_K) &  # 計算或建立變數 exposed
               (F >= material.MINIMUM_ACTIVE_METAL_FILL))  # 接續變數 exposed的數值、運算式或資料項目
    recoil = xp.where(exposed, 0.54 * p_sat, 0.0)  # 計算或建立暴露液面反衝壓
    tension = xp.maximum(material.SURFACE_TENSION_N_M +  # 計算或建立變數 tension
                         material.SURFACE_TENSION_TEMP_COEFF_N_M_K * (T_before - 293.15), 1e-6)  # 接續變數 tension的參數：逐項取較大值以限制下界
    opening = recoil > (101325.0 + 2.0 * tension / voxel_size_m)  # 計算或建立反衝壓是否克服環境壓與毛細壓
    result = (q_evap, F_next, xp.count_nonzero(exposed & opening), xp.max(recoil))  # 計算或建立變數 result
    return result + (T_before,) if return_temperature else result  # 回傳本行計算結果，交由呼叫端繼續使用


# ============================================================================
# 函式大綱｜run_stage03_validation() — 只執行雷射吸收驗證
# 【輸入】加工與數值設定；金屬填充率陣列；NumPy／CuPy 運算後端 xp
# 【計算】保持輸入遮罩及零液相率，以每步中點積分雷射功率
# 【輸出】03 專用設定、吸收能量歷程與逐 Z 層功率檔
# ============================================================================
def run_stage03_validation(settings, metal_fill_fraction, xp):  # 定義函式：只執行雷射吸收驗證
    """只執行雷射吸收驗證。
    計算：保持輸入遮罩及零液相率，以每步中點積分雷射功率。
    輸出：03 專用設定、吸收能量歷程與逐 Z 層功率檔。
    """
    if settings.laser_validation_dt_us <= 0.0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("--laser-validation-dt-us must be positive")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    voxel_size_m = settings.grid_um * 1e-6  # 計算或建立網格邊長（m）
    scan_duration_s = ((metal_fill_fraction.shape[0] * voxel_size_m -  # 計算或建立掃描期間（scan_duration_s）
                        (settings.start_um + settings.end_margin_um) * 1e-6) /  # 接續掃描期間（scan_duration_s）的數值、運算式或資料項目
                       (settings.speed * 1e-3))  # 接續掃描期間（scan_duration_s）的數值、運算式或資料項目
    if scan_duration_s <= 0.0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("laser scan duration must be positive; check scan start/end margin")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    dt_s = settings.laser_validation_dt_us * 1e-6  # 計算或建立時間步長（s）
    n_steps = math.ceil(scan_duration_s / dt_s)  # 計算或建立總時間步數
    liquid_fraction = xp.zeros_like(metal_fill_fraction, dtype=xp.float64)  # 計算或建立液相率陣列

    output_dir = Path(settings.out) / "stage03_laser_validation"  # 計算或建立本次輸出目錄
    output_dir.mkdir(parents=True, exist_ok=True)  # 建立輸出目錄及必要的上層目錄
    history_path = output_dir / "laser_energy_history.csv"  # 計算或建立雷射能量歷程 CSV 路徑
    z_path = output_dir / "laser_energy_by_z.csv"  # 計算或建立逐層雷射功率 CSV 路徑
    config_path = output_dir / "config.json"  # 計算或建立模型設定 JSON 路徑
    if ((history_path.exists() or z_path.exists()) and  # 判斷本行條件，成立時執行下方處理
            not settings.allow_existing_output):  # 接續上一行的邏輯判斷或大小比較條件
        raise FileExistsError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
            f"Stage 03 output already exists in {output_dir}; choose another --out "  # 接續本段欄位名稱、提示訊息或報表文字
            "or pass --allow-existing-output to overwrite the CSV files"  # 接續本段欄位名稱、提示訊息或報表文字
        )  # 結束本段參數、容器或條件的組合
    config_path.write_text(json.dumps({  # 以指定編碼寫入文字檔
        **vars(settings),  # 以指定編碼寫入文字檔
        "stage": "03 laser only",  # 設定變數 stage欄位的值
        "input_mask_shape": list(metal_fill_fraction.shape),  # 設定遮罩（input_mask_shape）欄位的值
        "backend": "cupy" if xp is not np else "numpy",  # 設定CPU／GPU 陣列後端欄位的值
        "laser_validation_dt_us": dt_s * 1e6,  # 設定雷射（laser_validation_dt_us）欄位的值
        "scan_duration_us": scan_duration_s * 1e6,  # 設定掃描期間（scan_duration_us）欄位的值
        "liquid_fraction_used": "zero (solid-state absorptivity; no stage 05 phase update)",  # 設定液態比例（liquid_fraction_used）欄位的值
        "energy_integration": "midpoint sampling of absorbed power per validation step",  # 設定能量（energy_integration）欄位的值
    }, ensure_ascii=False, indent=2), encoding="utf-8")  # 以指定編碼寫入文字檔

    history_header = [  # 計算或建立歷程欄位名稱（history_header）
        "step", "time_us", "laser_on", "laser_x_um", "laser_y_um",  # 接續歷程欄位名稱（history_header）的數值、運算式或資料項目
        "incident_power_domain_W", "absorbed_power_W",  # 接續歷程欄位名稱（history_header）的數值、運算式或資料項目
        "outside_domain_W", "reflected_or_scattered_W", "transmitted_below_domain_W",  # 接續歷程欄位名稱（history_header）的數值、運算式或資料項目
        "power_balance_residual_W", "incident_energy_cumulative_J",  # 接續歷程欄位名稱（history_header）的數值、運算式或資料項目
        "absorbed_energy_cumulative_J",  # 接續歷程欄位名稱（history_header）的數值、運算式或資料項目
    ]  # 結束本段參數、容器或條件的組合
    z_header = ["step", "time_us", "z_index", "z_center_um", "incident_power_W",  # 計算或建立Z方向欄位名稱（z_header）
                "intercepted_power_W", "absorbed_power_W", "reflected_power_W"]  # 接續Z方向欄位名稱（z_header）的數值、運算式或資料項目
    incident_energy_J = 0.0  # 計算或建立入射能量（incident_energy_J）
    absorbed_energy_J = 0.0  # 計算或建立吸收能量（absorbed_energy_J）
    # 開啟本行所列檔案，離開區塊時自動關閉資源
    with history_path.open("w", newline="", encoding="utf-8-sig") as history_stream, \
            z_path.open("w", newline="", encoding="utf-8-sig") as z_stream:  # 接續本段運算：逐層雷射功率 CSV 路徑
        history_writer = csv.writer(history_stream)  # 計算或建立歷程寫入器（history_writer）
        z_writer = csv.writer(z_stream)  # 計算或建立逐層功率 CSV 寫入器
        history_writer.writerow(bilingual_csv_header(history_header))  # 依既定欄位順序寫入一列 CSV 資料
        z_writer.writerow(bilingual_csv_header(z_header))  # 依既定欄位順序寫入一列 CSV 資料
        for step in range(n_steps):  # 依序處理step，逐項套用下方運算
            time_s = step * dt_s  # 計算或建立模擬時間（s）
            step_dt = min(dt_s, scan_duration_s - time_s)  # 計算或建立本步實際時間步長（s）
            sample_time_s = time_s + 0.5 * step_dt  # 計算或建立時間（sample_time_s）
            laser_x_m, laser_y_m, laser_on, _, result = laser.compute_laser_step(  # 計算或建立雷射（laser_x_m）、雷射（laser_y_m）、雷射（laser_on）、變數 _、變數 result
                metal_fill_fraction, xp, settings, sample_time_s,  # 接續雷射（laser_x_m）、雷射（laser_y_m）、雷射（laser_on）、變數 _、變數 result的參數：執行單一步雷射計算
                liquid_fraction=liquid_fraction)  # 接續雷射（laser_x_m）、雷射（laser_y_m）、雷射（laser_on）、變數 _、變數 result的參數：執行單一步雷射計算
            incident_energy_J += (settings.power * step_dt) if laser_on else 0.0  # 累加至入射能量（incident_energy_J）
            absorbed_energy_J += scalar(result["absorbed_power_W"]) * step_dt  # 累加至吸收能量（absorbed_energy_J）
            history_writer.writerow([  # 依既定欄位順序寫入一列 CSV 資料
                step, sample_time_s * 1e6, int(laser_on), laser_x_m * 1e6,  # 依既定欄位順序寫入一列 CSV 資料
                laser_y_m * 1e6, scalar(result["incident_power_domain_W"]),  # 依既定欄位順序寫入一列 CSV 資料
                scalar(result["absorbed_power_W"]),  # 依既定欄位順序寫入一列 CSV 資料
                scalar(result["outside_domain_W"]),  # 依既定欄位順序寫入一列 CSV 資料
                scalar(result["unabsorbed_intercepted_W"]),  # 依既定欄位順序寫入一列 CSV 資料
                scalar(result["transmitted_below_domain_W"]),  # 依既定欄位順序寫入一列 CSV 資料
                scalar(result["power_balance_residual_W"]),  # 依既定欄位順序寫入一列 CSV 資料
                incident_energy_J, absorbed_energy_J,  # 依既定欄位順序寫入一列 CSV 資料
            ])  # 結束本段參數、容器或條件的組合
            if step == 0 or step == n_steps - 1 or step % max(1, round(5e-6 / dt_s)) == 0:  # 依步數間隔或終止條件決定是否執行檢查與輸出
                incident_z = cpu_array(result["incident_power_by_z_W"], xp)  # 計算或建立入射Z方向（incident_z）
                intercepted_z = cpu_array(result["intercepted_power_by_z_W"], xp)  # 計算或建立攔截Z方向（intercepted_z）
                absorbed_z = cpu_array(result["absorbed_power_by_z_W"], xp)  # 計算或建立吸收Z方向（absorbed_z）
                reflected_z = cpu_array(result["reflected_power_by_z_W"], xp)  # 計算或建立反射Z方向（reflected_z）
                for k in range(metal_fill_fraction.shape[2]):  # 依序處理k，逐項套用下方運算
                    z_writer.writerow([  # 依既定欄位順序寫入一列 CSV 資料
                        step, sample_time_s * 1e6, k, (k + 0.5) * settings.grid_um,  # 依既定欄位順序寫入一列 CSV 資料
                        float(incident_z[k]), float(intercepted_z[k]),  # 依既定欄位順序寫入一列 CSV 資料
                        float(absorbed_z[k]), float(reflected_z[k]),  # 依既定欄位順序寫入一列 CSV 資料
                    ])  # 結束本段參數、容器或條件的組合
    print(f"[STAGE 03 COMPLETE] input={getattr(settings, 'powder', '')}; "  # 輸出本階段的數值、進度或診斷訊息
          f"scan_time={scan_duration_s*1e6:.6f} us; dt={dt_s*1e6:.6g} us; "  # 輸出本階段的數值、進度或診斷訊息
          f"incident={incident_energy_J:.9e} J; absorbed={absorbed_energy_J:.9e} J; "  # 輸出本階段的數值、進度或診斷訊息
          f"effective_absorptivity={100*absorbed_energy_J/max(incident_energy_J, 1e-30):.6f}%")  # 輸出本階段的數值、進度或診斷訊息
    print(f"[STAGE 03 OUTPUT] {output_dir.resolve()}")  # 輸出本階段的數值、進度或診斷訊息


# ============================================================================
# 函式大綱｜cpu_array() — 將輸出陣列轉成 NumPy
# 【輸入】待轉換數值；NumPy／CuPy 運算後端 xp
# 【計算】GPU 後端使用一次陣列傳輸，CPU 後端直接取得 NumPy 表示
# 【輸出】可由 CSV、NPZ 或檢查程式使用的 CPU 陣列
# ============================================================================
def cpu_array(value, xp):  # 定義函式：將輸出陣列轉成 NumPy
    """將輸出陣列轉成 NumPy。
    計算：GPU 後端使用一次陣列傳輸，CPU 後端直接取得 NumPy 表示。
    輸出：可由 CSV、NPZ 或檢查程式使用的 CPU 陣列。
    """
    return xp.asnumpy(value) if xp is not np else np.asarray(value)  # 回傳本行計算結果，交由呼叫端繼續使用


# ============================================================================
# 函式大綱｜save_voxel_state() — 儲存完整三維網格狀態
# 【輸入】本次輸出目錄；時間步序號；模擬時間（s）；金屬填充率 F；初始金屬填充率；體積焓 H（J/m³）
# 【續輸入】溫度 T（K）；液相率 fL；氣體、固態、共存、液態及再凝固相態代碼；CPU 基板遮罩；CPU 金屬幾何遮罩；曾經熔化的網格標記
# 【續輸入】雷射（laser_on）；雷射（laser_x_m）；雷射（laser_y_m）；網格邊長（µm）；基板（substrate_height_um）；基板各定義的熔深字典
# 【續輸入】NumPy／CuPy 運算後端 xp；診斷（thermal_diagnostic）；能量殘差（energy_residual_J）
# 【計算】轉回 CPU 後壓縮寫入暫存 NPZ，檢查形狀與有限值，再替換正式檔
# 【輸出】含溫度、焓、填充率、液相率及診斷的快照路徑
# ============================================================================
def save_voxel_state(output_dir, step, time_s, F, initial_F, H, T, fL, phase_codes,  # 定義函式：儲存完整三維網格狀態
                     substrate_mask_cpu, mask_cpu, ever_melted, laser_on, laser_x_m,  # 接續函式參數：CPU 基板遮罩、CPU 金屬幾何遮罩、曾經熔化的網格標記、雷射（laser_on）、雷射（laser_x_m）
                     laser_y_m, voxel_size_um, substrate_height_um, depths, xp, thermal_diagnostic=None, energy_residual_J=0.):  # 接續函式參數：雷射（laser_y_m）、網格邊長（µm）、基板（substrate_height_um）、基板各定義的熔深字典、NumPy／CuPy 運算後端 xp、診斷（thermal_diagnostic）、能量殘差（energy_residual_J）
    """儲存完整三維網格狀態。
    計算：轉回 CPU 後壓縮寫入暫存 NPZ，檢查形狀與有限值，再替換正式檔。
    輸出：含溫度、焓、填充率、液相率及診斷的快照路徑。
    """
    target = output_dir / f'state_t{time_s*1e6:010.3f}us_step{step:08d}.npz'  # 計算或建立正式輸出檔路徑
    density = dict(  # 計算或建立準備寫入 NPZ 的場量字典
        F=cpu_array(F, xp).astype(np.float32),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        F_initial=cpu_array(initial_F, xp).astype(np.float32),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        H=cpu_array(H, xp).astype(np.float32),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        T=cpu_array(T, xp).astype(np.float32),  # 皞怠漲 K
        fL=cpu_array(fL, xp).astype(np.float32),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        phase=cpu_array(phase_codes, xp).astype(np.uint8),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        ever_melted=cpu_array(ever_melted, xp).astype(np.uint8),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        substrate_mask=substrate_mask_cpu,  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        powder_mask=mask_cpu & ~substrate_mask_cpu,  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        dx_um=np.float64(voxel_size_um), dy_um=np.float64(voxel_size_um), dz_um=np.float64(voxel_size_um),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        substrate_top_um=np.float64(substrate_height_um),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        powder_top_um=np.float64(F.shape[2] * voxel_size_um),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        Dsub_mushy_um=np.float64(depths['Dsub_mushy_um']),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        Dsub_liquid_um=np.float64(depths['Dsub_liquid_um']),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        Dsub_ever_um=np.float64(depths['Dsub_ever_um']),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        time_us=np.float64(time_s * 1e6), time_s=np.float64(time_s),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        step=np.int64(step), laser_on=np.bool_(laser_on),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        laser_x_um=np.float64(laser_x_m * 1e6), laser_y_um=np.float64(laser_y_m * 1e6),  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
        phase_encoding=np.array('0_gas_void_1_solid_2_mushy_3_liquid_4_resolidified'))  # 接續準備寫入 NPZ 的場量字典的參數：執行 dict 呼叫並完成該步處理
    if thermal_diagnostic is not None:  # 判斷本行條件，成立時執行下方處理
        for key, value in thermal_diagnostic.items():  # 依序處理key, value，逐項套用下方運算
            density[key] = cpu_array(value, xp).astype(np.float32)  # 計算或建立準備寫入 NPZ 的場量字典的指定網格或切片
    density['Eresidual_J'] = np.float64(energy_residual_J)  # 計算或建立準備寫入 NPZ 的場量字典的變數 Eresidual_J欄位
    if thermal_diagnostic is None:  # 判斷本行條件，成立時執行下方處理
        for name in ('Qlaser_W_m3','Qcond_W_m3','Qconv_W_m3','Qrad_W_m3','Qevap_diagnostic_W_m3'):  # 依序處理name，逐項套用下方運算
            density[name] = np.zeros(F.shape,dtype=np.float32)  # 計算或建立準備寫入 NPZ 的場量字典的指定網格或切片
    density['F_difference'] = density['F'] - density['F_initial']  # 計算或建立準備寫入 NPZ 的場量字典的變數 F_difference欄位
    if not np.all(np.isfinite(density['T'])) or not np.all(np.isfinite(density['H'])):  # 判斷本行條件，成立時執行下方處理
        raise FloatingPointError('NPZ ?脣???暹澈摨行??? NaN/Inf')  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    temporary = target.with_suffix('.writing.npz')  # 計算或建立暫存輸出檔路徑
    try:  # 嘗試執行可能失敗的載入、寫檔或運算
        np.savez_compressed(temporary, **density)  # 將各場量壓縮儲存成 NPZ 檔
        with np.load(temporary, allow_pickle=False) as check:  # 開啟本行所列檔案，離開區塊時自動關閉資源
            assert check['T'].shape == F.shape and check['phase'].shape == F.shape  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
        temporary.replace(target)  # 以完成的暫存檔替換正式檔
    finally:  # 無論成功或失敗，最後都執行資源清理
        temporary.unlink(missing_ok=True)  # 清除殘留的暫存檔
    return target  # 回傳本行計算結果，交由呼叫端繼續使用


# ============================================================================
# 函式大綱｜run_simulation() — 執行主模擬與指定距離能量統計
# 【輸入】加工與數值設定
# 【計算】僅載入 01～05、逐步更新雷射與熱相變，分列相變及導熱帳，不求解熔池流動
# 【輸出】預設前進 10 µm 後的 CSV、Markdown、設定及 NPZ，輸出完成後停止
# ============================================================================
def run_simulation(settings=None):  # 定義函式：執行主模擬與指定距離能量統計
    """執行主模擬與指定距離能量統計。
    計算：僅載入 01～05、逐步更新雷射與熱相變，分列相變及導熱帳，不求解熔池流動。
    輸出：預設前進 10 µm 後的 CSV、Markdown、設定及 NPZ，輸出完成後停止。
    """
    if settings is None:  # 判斷本行條件，成立時執行下方處理
        settings = process.parse_command_line()  # 計算或建立加工與數值設定
    material.validate_material_properties()  # 檢查材料物性
    process.validate_process_parameters(settings)  # 檢查加工及蒸發參數
    if settings.verify:  # 判斷本行條件，成立時執行下方處理
        phase.verify_phase_module()  # 驗證混合焓與固液相變
        heat.verify_heat_transfer_module()  # 驗證導熱與熱損失模組
        return  # 回傳本行計算結果，交由呼叫端繼續使用
    print(f'[MODEL REVISION] {MODEL_REVISION}', flush=True)  # 啟動時立即顯示實際載入版本，避免誤認舊程序使用了新程式
    xp = np  # 計算或建立NumPy／CuPy 運算後端 xp
    if not settings.cpu:  # 判斷本行條件，成立時執行下方處理
        try:  # 嘗試執行可能失敗的載入、寫檔或運算
            import cupy as cp  # 載入CUDA GPU 陣列計算所需功能
            cp.zeros(1).sum().get()  # 將 GPU 計算結果傳回 CPU
            xp = cp  # 計算或建立NumPy／CuPy 運算後端 xp
        except Exception as error:  # 攔截本行指定的例外並採取對應處理
            print(f"[INFO] GPU unavailable; falling back to CPU: {error}")  # 輸出本階段的數值、進度或診斷訊息
    mask_cpu, input_path = laser.load_metal_mask(settings.powder)  # 計算或建立CPU 金屬幾何遮罩、輸入幾何檔路徑
    F = xp.asarray(mask_cpu, dtype=xp.float64)  # 計算或建立金屬填充率 F
    if settings.through_stage == "03":  # 判斷本行條件，成立時執行下方處理
        run_stage03_validation(settings, F, xp)  # 只執行雷射吸收驗證
        return  # 回傳本行計算結果，交由呼叫端繼續使用
    stage04_validation = settings.through_stage == "04"  # 計算或建立04 熱傳驗證模式開關
    F0 = F.copy()  # 計算或建立初始金屬填充率 F0
    dx_m = settings.grid_um * 1e-6  # 計算或建立等距網格邊長（m）
    ambient_area_factor = heat.calculate_gas_facing_face_area(F, xp)  # 計算或建立對流及輻射暴露面積係數
    ambient_area_m2 = scalar(xp.sum(ambient_area_factor)) * dx_m**2  # 計算或建立對流及輻射總暴露面積（m²）
    nz = F.shape[2]  # 計算或建立變數 nz
    substrate_top_index = int(round(settings.substrate_um / settings.grid_um))  # 計算或建立基板頂面 Z 索引
    if not 0 < substrate_top_index < nz:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("substrate top index must lie inside the Z dimension")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    substrate_mask_cpu = np.zeros_like(mask_cpu, dtype=bool)  # 計算或建立CPU 基板遮罩
    substrate_mask_cpu[:, :, :substrate_top_index] = mask_cpu[:, :, :substrate_top_index]  # 計算或建立CPU 基板遮罩的指定網格或切片
    H = xp.zeros_like(F)  # 計算或建立體積焓 H（J/m³）
    T = phase.temperature_from_enthalpy(H, F, xp)  # 計算或建立溫度 T（K）
    fL = phase.liquid_fraction_from_temperature(T, xp)  # 計算或建立液相率 fL
    evaporation_area_factor = heat.calculate_evaporation_surface_area(F, None, xp, settings.evaporation_surface)  # 只建立幾何面積，液態資格由本步預測溫度判斷
    z_occupancy = np.count_nonzero(mask_cpu >= material.MINIMUM_ACTIVE_METAL_FILL, axis=(0, 1))  # 計算或建立Z方向（z_occupancy）
    substrate_planes_full = bool(np.all(z_occupancy[:substrate_top_index] == F.shape[0] * F.shape[1]))  # 計算或建立基板（substrate_planes_full）
    occupied_z = np.flatnonzero(z_occupancy)  # 計算或建立Z方向（occupied_z）
    first_powder_z = next((int(k) for k in occupied_z if k >= substrate_top_index), None)  # 計算或建立粉末Z方向（first_powder_z）
    last_occupied_z = int(occupied_z[-1]) if occupied_z.size else None  # 計算或建立最近記錄Z方向（last_occupied_z）
    print(f'[GEOMETRY] array axes=(x,y,z); k=0 is build-plate bottom; laser enters from high z; '  # 輸出本階段的數值、進度或診斷訊息
          f'substrate k=[0,{substrate_top_index}) => 0-{substrate_top_index*settings.grid_um:.1f} um; '  # 輸出本階段的數值、進度或診斷訊息
          f'full_substrate_planes={substrate_planes_full}; first_occupied_powder_k={first_powder_z}; '  # 輸出本階段的數值、進度或診斷訊息
          f'last_occupied_k={last_occupied_z}', flush=True)  # 輸出本階段的數值、進度或診斷訊息
    if not substrate_planes_full:  # 判斷本行條件，成立時執行下方處理
        print('[GEOMETRY WARNING] Some voxels inside the configured substrate depth are empty; '  # 輸出本階段的數值、進度或診斷訊息
              'check mask orientation and --substrate-um.', flush=True)  # 輸出本階段的數值、進度或診斷訊息
    initial_energy_components = phase.energy_components_from_temperature(T, F, xp, split_sensible_phases=True)  # 初始狀態同樣分列固態與液態顯熱
    initial_solid_sensible_J = scalar(xp.sum(initial_energy_components['metal_solid_sensible_J_m3'])) * dx_m**3  # 固態顯熱變化的初始基準
    initial_liquid_sensible_J = scalar(xp.sum(initial_energy_components['metal_liquid_sensible_J_m3'])) * dx_m**3  # 液態顯熱變化的初始基準
    initial_metal_sensible_J = scalar(xp.sum(initial_energy_components['metal_sensible_J_m3'])) * dx_m**3  # 計算或建立初始金屬顯熱（initial_metal_sensible_J）
    initial_metal_latent_J = scalar(xp.sum(initial_energy_components['metal_latent_J_m3'])) * dx_m**3  # 計算或建立初始金屬潛熱（initial_metal_latent_J）
    initial_gas_sensible_J = scalar(xp.sum(initial_energy_components['gas_sensible_J_m3'])) * dx_m**3  # 計算或建立初始氣體顯熱（initial_gas_sensible_J）
    ever_melted = xp.zeros_like(F, dtype=xp.bool_)  # 計算或建立曾經熔化的網格標記
    phase_codes = xp.where(F >= material.MINIMUM_ACTIVE_METAL_FILL, 1, 0).astype(xp.uint8)  # 計算或建立氣體、固態、共存、液態及再凝固相態代碼
    stable_dt = heat.calculate_thermal_stable_dt(  # 同時保護金屬、氣體及各種邊界散熱的顯式更新
        dx_m, gas_k=settings.gas_k, ambient_h_W_m2_K=settings.ambient_h,  # 使用與主求解器相同的氣體及環境參數
        bottom_h_W_m2_K=settings.bottom_h, max_temperature_K=settings.max_diagnostic_T)  # 以設定的溫度上限評估輻射穩定性
    dt = min(settings.dt_ns * 1e-9, stable_dt)  # 同時遵守使用者時間步上限與熱穩定限制
    report_period_s = settings.max_steps * dt if settings.max_steps else settings.energy_report_distance_um * 1e-6 / (settings.speed * 1e-3)  # 預設按指定步數停止；零才改用距離
    report_every = settings.max_steps or max(1, math.ceil(report_period_s / dt))  # 步數模式不改變安全時間步
    dt = report_period_s / report_every  # 距離模式對齊終止位置，步數模式維持安全步長
    stop_distance_um = report_period_s * settings.speed * 1e-3 * 1e6  # 計算本次實際終止距離
    scan_duration = ((F.shape[0] * dx_m) - (settings.start_um + settings.end_margin_um) * 1e-6) / (settings.speed * 1e-3)  # 計算或建立完整掃描所需時間（s）
    if scan_duration <= 0:  # 判斷本行條件，成立時執行下方處理
        raise ValueError("laser scan duration must be positive; check scan start, end margin, and speed")  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    if report_period_s > scan_duration + 1e-15:  # 判斷本行條件，成立時執行下方處理
        raise ValueError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
            f"Scan path is shorter than the requested stopping distance "  # 接續本段欄位名稱、提示訊息或報表文字
            f"({stop_distance_um:g} um); check scan start/end margin")  # 接續本段欄位名稱、提示訊息或報表文字
    max_time = report_period_s  # 計算或建立本次終止時間（s）
    n_steps = report_every  # 計算或建立總時間步數
    save_every = max(1, round(settings.save_us * 1e-6 / dt))  # 計算或建立NPZ 快照輸出步數間隔
    log_every = 10  # 主要歷程固定每十步一筆
    output_dir = (Path(settings.out) / "stage04_phase_validation" if stage04_validation else  # 計算或建立本次輸出目錄
                  (Path(settings.out)))  # 接續本次輸出目錄的數值、運算式或資料項目
    requested_output_dir = output_dir  # 計算或建立原指定輸出目錄
    output_dir = prepare_output_directory(output_dir, settings.allow_existing_output)  # 計算或建立本次輸出目錄
    if output_dir != requested_output_dir:  # 判斷本行條件，成立時執行下方處理
        print(f'[INFO] 原輸出目錄已有資料，本次改存至：{output_dir.resolve()}', flush=True)  # 輸出本階段的數值、進度或診斷訊息
    print(f'[OUTPUT DIRECTORY] {output_dir.resolve()}', flush=True)  # 輸出本階段的數值、進度或診斷訊息
    (output_dir / 'config.json').write_text(json.dumps({**vars(settings), 'actual_dt_ns': dt*1e9,  # 以指定編碼寫入文字檔
        'model_revision': MODEL_REVISION,  # 隨結果保存本次實際執行的模型版本
        'thermal_stable_dt_ns': stable_dt * 1e9,  # 記錄包含氣體與邊界的熱穩定時間步上限
        'energy_report_schema': 'fusion_storage_plus_vaporization_absorption; evaporation_loss_excludes_vaporization_latent',  # 汽化改列潛熱，蒸發損失只含攜出焓
        'thermal_csv_schema': 'bilingual_single_step_incident_energy_v4',  # 入射能量欄改為固定時間步的能量
        'Pincident_W_definition': 'configured laser power while laser is on; zero when off',  # 明確區分瓦特與焦耳
        'Eincident_J_definition': 'configured incident power times actual_dt; per solver step, not per CSV interval or cumulative',  # 每列皆代表一個計算步的輸入
        'diagnostic_Eincident_cumulative_J_definition': 'incident power integrated over illumination time; cumulative audit only',  # 累積量只保留供內部與詳細診斷使用
        'Eevap_J_definition': 'carried enthalpy only; excludes separately reported Elatent_vaporization_J',  # 主表蒸發能量不重複包含汽化潛熱
        'diagnostic_Eevap_total_removed_J_definition': 'vaporization latent + carried enthalpy; solver energy audit',  # 蒸發總移除量只保留在詳細診斷
        'uncomputed_csv_fields': ['Umax_liquid_m_s', 'Umax_argon_m_s', 'Umax_metal_vapor_m_s', 'Tmax_metal_vapor_K', 'metal_vapor_cells', 'Esensible_metal_vapor_J'],  # 留白代表未求解
        'gas_species_models': {'argon': 'thermal background; local thermal equilibrium; no flow', 'Ti-6Al-4V_metal_vapor': 'cumulative evaporation source only; no independent density, temperature, transport or condensation field'},  # 記錄兩類氣體的實際模型範圍
        'backend': 'cupy' if xp is not np else 'numpy', 'scan_time_us': scan_duration*1e6,  # 設定CPU／GPU 陣列後端欄位的值
        'stop_distance_um': stop_distance_um, 'stop_step': n_steps,  # 保存實際停止距離與步數
        'history_every_steps': 10, 'history_file_steps': 1000,  # 記錄主要歷程的採樣與分檔規則
        'simulation_end_time_us': max_time * 1e6,  # 設定時間（simulation_end_time_us）欄位的值
        'cooling_after_stop': False,  # 設定之後（cooling_after_stop）欄位的值
        'stage': ('04 heat-transfer validation; solid-liquid phase change enabled; evaporation disabled'  # 設定變數 stage欄位的值
                  if stage04_validation else ('05 full simulation')),  # 依熱傳驗證或停用蒸發設定選擇對應計算分支
        'stage04_temperature_model': 'enthalpy method with solid-liquid latent heat and liquid-fraction update enabled' if stage04_validation else 'not applicable',  # 設定溫度（stage04_temperature_model）欄位的值
        'physical_model': ('laser + XYZ conduction + dynamic gas-facing convection/radiation + bottom loss; '  # 設定變數 physical_model欄位的值
                           'solid-liquid phase change enabled; evaporation disabled'  # 以指定編碼寫入文字檔
                           if stage04_validation else  # 依熱傳驗證或停用蒸發設定選擇對應計算分支
                           ('laser + XYZ conduction + dynamic gas-facing convection/radiation + '  # 以指定編碼寫入文字檔
                            'surface mass-loss evaporation; no melt flow')),  # 以指定編碼寫入文字檔
        'reference_density_kg_m3': material.SOLID_DENSITY_KG_M3,  # 設定密度（reference_density_kg_m3）欄位的值
        'latent_heat_J_kg': material.LATENT_HEAT_J_KG,  # 設定潛熱（latent_heat_J_kg）欄位的值
        'absorptivity_solid': laser.ABSORPTIVITY_SOLID,  # 實際固態雷射吸收率為使用者指定值 0.40
        'absorptivity_liquid': laser.ABSORPTIVITY_LIQUID,  # 實際液態雷射吸收率為使用者指定值 0.25
        'absorptivity_model': laser.ABSORPTIVITY_MODEL,  # 模型說明與 03 真正採用的吸收率計算保持一致
        'evaporation_model': ('disabled' if stage04_validation or settings.evaporation_model == 'off' else  # 設定蒸發（evaporation_model）欄位的值
                              ('explicit Hertz-Knudsen rate with Clausius-Clapeyron vapor pressure; mass and total-enthalpy bounds; no boiling-temperature reset'  # 以指定編碼寫入文字檔
                               if settings.evaporation_model == 'rate' else 'legacy boiling-plateau mass loss')),  # 判斷本行條件，成立時執行下方處理
        'evaporation_surface_model': ('liquid faces weighted by vertical open fraction; consistent with laser coverage; lateral connectivity not resolved'  # 蒸發面積與雷射的逐層填充率遮蔽保持一致
                                     if settings.evaporation_surface == 'top' else 'all fully liquid metal/gas faces, including internal pores'),  # 判斷本行條件，成立時執行下方處理
        'evaporation_rate_sampling': 'predicted temperature before evaporation; explicit time integration',  # 設定蒸發（evaporation_rate_sampling）欄位的值
        'recoil_pressure_model': 'disabled during stage-04 validation' if stage04_validation else '0.54*P_atm*exp(Lv*M*(T-Tb)/(R*T*Tb)); keyhole-opening voxel proxy, not CFD or a calibrated Ti64 free-surface model',  # 設定反衝壓力（recoil_pressure_model）欄位的值
        'heat_loss_area_model': 'all current XYZ metal/gas faces, recomputed after each voxel-depletion update; includes internal pores',  # 設定損失面積（heat_loss_area_model）欄位的值
        'geometry_axis_convention': 'array axes=(x,y,z); k=0 is build-plate bottom; laser enters from high z',  # 設定變數 geometry_axis_convention欄位的值
        'geometry_full_substrate_planes': substrate_planes_full,  # 設定基板（geometry_full_substrate_planes）欄位的值
        'geometry_first_occupied_powder_k': first_powder_z,  # 設定粉末（geometry_first_occupied_powder_k）欄位的值
        'geometry_last_occupied_k': last_occupied_z,  # 設定最近記錄（geometry_last_occupied_k）欄位的值
        'energy_balance_warning_pct': 5.0,  # 設定能量收支百分比（energy_balance_warning_pct）欄位的值
        'temperature_diagnostic_limit_K': settings.max_diagnostic_T,  # 設定溫度診斷（temperature_diagnostic_limit_K）欄位的值
        'gas_k_effective_W_m_K': settings.gas_k,  # 設定氣體有效（gas_k_effective_W_m_K）欄位的值
        'boundary_surface_model': 'all XYZ metal-gas interfaces including internal pores; powder contact uses conduction; z=0 uses bottom boundary'},  # 設定表面（boundary_surface_model）欄位的值
        ensure_ascii=False, indent=2), encoding='utf-8')  # 以指定編碼寫入文字檔
    diagnostic_dir = output_dir / 'diagnostics'  # 詳細診斷集中於子目錄
    if settings.diagnostic_csv:  # 使用者明確指定才建立診斷目錄
        diagnostic_dir.mkdir(exist_ok=True)  # 預設避免建立多餘 CSV
    absorption_comparison_path = diagnostic_dir / 'absorption_energy_equal_distance.csv'  # 選用吸收能量對照
    diagnostic_csv_path = diagnostic_dir / 'thermal_diagnostics.csv'  # 選用熱源與界面診斷
    header = ['step', 'time_us', 'laser_on', 'laser_x_um', 'Tmax_K', 'Tmax_metal_K', 'Tmax_gas_K', 'Tmin_metal_K',  # 計算或建立熱歷程 CSV 欄位名稱
              'solid_cells', 'mushy_cells', 'liquid_cells', 'resolidified_cells',  # 接續熱歷程 CSV 欄位名稱的數值、運算式或資料項目
              'Eabs_J', 'Eincident_cumulative_J',  # 詳細診斷累積入射量明確使用不同名稱
              'Esensible_J', 'Esensible_metal_J', 'Esensible_gas_J', 'Elatent_J',  # 接續熱歷程 CSV 欄位名稱的數值、運算式或資料項目
              'Esensible_pct_Eabs', 'Elatent_pct_Eabs',  # 接續熱歷程 CSV 欄位名稱的數值、運算式或資料項目
              'Econv_J', 'Erad_J', 'Ebottom_J', 'Eevap_total_removed_J', 'Estored_J', 'energy_error_pct',  # 診斷專用欄位明確表示完整蒸發移除量
              'Dsub_mushy_um', 'Dsub_liquid_um', 'Dsub_ever_um', 'solidification_completed',  # 接續熱歷程 CSV 欄位名稱的數值、運算式或資料項目
              'Qlaser_W_m3_max', 'Qcond_W_m3_at_Tmax', 'Qconv_W_m3_at_Tmax',  # 接續熱歷程 CSV 欄位名稱的數值、運算式或資料項目
              'Qrad_W_m3_at_Tmax', 'Qevap_diagnostic_W_m3_at_Tmax',  # 接續熱歷程 CSV 欄位名稱的數值、運算式或資料項目
              'Pconv_W', 'Prad_W', 'Pevap_W', 'Aconv_rad_m2',  # 接續熱歷程 CSV 欄位名稱的數值、運算式或資料項目
              'Eresidual_J', 'Eresidual_pct', 'evaporated_mass_kg']  # 接續熱歷程 CSV 欄位名稱的數值、運算式或資料項目
    header.extend(key for key, _ in ENERGY_DETAIL_LABELS)  # 把本行各項依序加入清單
    header.extend(['Elatent_accounted_J', 'Elatent_accounted_pct_Eabs',  # 增加潛熱合計能量與百分比
                   'Evaporization_latent_pct_Eabs', 'Eevap_enthalpy_loss_J',  # 分列汽化潛熱占比與攜出焓損失
                   'Eevap_enthalpy_loss_pct_Eabs'])  # 記錄扣除汽化潛熱後的蒸發損失百分比
    phase_transfer_acc = xp.zeros(7, dtype=xp.float64)  # 計算或建立相變與界面導熱累積能量向量
    energy_acc = xp.zeros(5, dtype=xp.float64)  # 計算或建立累積雷射、對流、輻射、底部及蒸發能量向量
    Eincident_cumulative_J = 0.0  # 累積入射量明確命名，與主要 CSV 的單步 Eincident_J 分開
    last_q_fields = None  # 計算或建立最近輸出的各種體積熱源場
    last_powers = dict(Pconv_W=0., Prad_W=0., Pevap_diagnostic_W=0.,  # 計算或建立最近記錄的熱損失功率與面積
                       Aconv_rad_m2=ambient_area_m2)  # 接續最近記錄的熱損失功率與面積的參數：執行 dict 呼叫並完成該步處理
    print(f'[START] Voxel={F.shape} backend={"cupy" if xp is not np else "numpy"} dt={dt*1e9:.5f} ns')  # 輸出本階段的數值、進度或診斷訊息
    print(  # 輸出本階段的數值、進度或診斷訊息
        f"[MODEL] laser absorptivity: solid={laser.ABSORPTIVITY_SOLID:.4f}, "  # 輸出本階段的數值、進度或診斷訊息
        f"liquid={laser.ABSORPTIVITY_LIQUID:.4f}; latent heat={material.LATENT_HEAT_J_KG} J/kg"  # 輸出本階段的數值、進度或診斷訊息
    )  # 結束本段參數、容器或條件的組合
    audit_index = tuple(int(os.getenv(name, str(default))) for name, default in  # 計算或建立固定審計網格的三維索引
                        [('LPBF_AUDIT_I', 36), ('LPBF_AUDIT_J', 51), ('LPBF_AUDIT_K', 28)])  # 接續固定審計網格的三維索引的參數：執行 tuple 呼叫並完成該步處理
    if any(axis < 0 or axis >= size for axis, size in zip(audit_index, F.shape)):  # 判斷本行條件，成立時執行下方處理
        audit_index = tuple(min(max(axis, 0), size-1) for axis, size in zip(audit_index, F.shape)); print(f'[AUDIT] 蝝Ｗ?撌脤??嗅蝬脫?改?{audit_index}')  # 輸出本階段的數值、進度或診斷訊息
    audit_volume_m3 = dx_m ** 3  # 計算或建立審計網格體積（m³）
    audit_initial_H = xp.asarray(H[audit_index], dtype=xp.float64).copy()  # 計算或建立固定網格初始體積焓
    audit_components = ['laser', 'conduction', 'convection', 'radiation', 'bottom', 'net']  # 計算或建立固定網格審計能量項目名稱
    audit_acc = {name: xp.asarray(0.0, dtype=xp.float64) for name in audit_components}  # 計算或建立固定網格各能量項的累積量
    audit_csv_path = diagnostic_dir / 'fixed_voxel_energy_audit.csv'  # 選用固定網格審計
    audit_header = ['step', 'time_us', 'i', 'j', 'k', 'x_um', 'y_um', 'z_um',  # 計算或建立固定網格審計欄位名稱（audit_header）
                    'laser_x_um', 'laser_distance_xy_um', 'F', 'T_K', 'H_J_m3',  # 接續固定網格審計欄位名稱（audit_header）的數值、運算式或資料項目
                    'E_laser_J', 'E_conduction_signed_J', 'E_convection_loss_J',  # 接續固定網格審計欄位名稱（audit_header）的數值、運算式或資料項目
                    'E_radiation_loss_J', 'E_bottom_loss_J', 'E_net_J',  # 接續固定網格審計欄位名稱（audit_header）的數值、運算式或資料項目
                    'delta_H_times_volume_J', 'closure_residual_J', 'closure_error_pct',  # 接續固定網格審計欄位名稱（audit_header）的數值、運算式或資料項目
                    'Qlaser_last_W_m3', 'Qnet_last_W_m3', 'Qcond_last_W_m3', 'Qconv_last_W_m3', 'Qrad_last_W_m3', 'Qevap_diagnostic_last_W_m3']  # 接續固定網格審計欄位名稱（audit_header）的數值、運算式或資料項目
    audit_last_qlaser = xp.asarray(0.0, dtype=xp.float64)  # 計算或建立固定網格審計最近記錄雷射熱源（audit_last_qlaser）
    audit_last_qnet = xp.asarray(0.0, dtype=xp.float64)  # 計算或建立固定網格審計最近記錄淨熱源（audit_last_qnet）
    audit_last_components = {key:xp.asarray(0.,dtype=xp.float64) for key in ('Qcond','Qconv','Qrad','Qevap')}  # 計算或建立固定網格審計最近記錄分項（audit_last_components）
    audit_every = max(1, int(os.getenv('LPBF_AUDIT_EVERY', '1000')))  # 計算或建立固定網格審計步數間隔
    print(f'[VOXEL AUDIT CONFIG] index={audit_index} every={audit_every} steps '  # 輸出本階段的數值、進度或診斷訊息
          f'xyz_um={tuple((v+0.5)*settings.grid_um for v in audit_index)}', flush=True)  # 輸出本階段的數值、進度或診斷訊息
    # ============================================================================
    # 雷射表面吸收深度診斷：獨立 CSV，不增加 thermal_history 的 33 個欄位
    # 診斷使用「本步熱更新前」的 F、fL 與雷射吸收場。
    # ============================================================================
    laser_depth_csv_path = output_dir / 'laser_absorption_depth_history.csv'
    laser_depth_every = max(1, int(os.getenv('LPBF_LASER_DEPTH_EVERY', '100')))
    laser_depth_columns = [
        'step', 'time_us', 'laser_x_um', 'laser_on',
        'incident_power_domain_W', 'absorbed_power_W',
        'local_top2um_absorbed_pct', 'local_top4um_absorbed_pct',
        'local_top10um_absorbed_pct', 'local_top20um_absorbed_pct',
        'max_voxel_absorbed_power_W', 'max_voxel_source_W_m3',
        'maximum_Z_layer_absorbed_pct',
    ]
    with laser_depth_csv_path.open('w', newline='', encoding='utf-8-sig') as depth_file:
        csv.writer(depth_file).writerow(laser_depth_columns)
    print(f'[LASER DEPTH CSV] {laser_depth_csv_path.resolve()} '
          f'every={laser_depth_every} steps', flush=True)
    z_csv_path = diagnostic_dir / 'laser_z_absorption_history.csv'  # 選用逐層雷射診斷
    diagnostic_header = ['step', 'time_us', 'laser_x_um', 'Psub_W', 'qmean_contact_W_m2',  # 計算或建立診斷欄位名稱（diagnostic_header）
                         'contact_fraction', 'contact_voxels', 'Tmax_substrate_K', 'Tmax_powder_K',  # 接續診斷欄位名稱（diagnostic_header）的數值、運算式或資料項目
                         'hotspot_i', 'hotspot_j', 'hotspot_k', 'Tmax_hotspot_K',  # 接續診斷欄位名稱（diagnostic_header）的數值、運算式或資料項目
                         'F_at_Tmax', 'mass_at_Tmax_kg', 'H_at_Tmax_J_m3',  # 接續診斷欄位名稱（diagnostic_header）的數值、運算式或資料項目
                         'Qlaser_at_Tmax_W_m3', 'Qcond_at_Tmax_W_m3', 'Qnet_at_Tmax_W_m3',  # 接續診斷欄位名稱（diagnostic_header）的數值、運算式或資料項目
                         'Qconv_at_Tmax_W_m3', 'Qrad_at_Tmax_W_m3', 'Qevap_diagnostic_at_Tmax_W_m3',  # 接續診斷欄位名稱（diagnostic_header）的數值、運算式或資料項目
                         'P_into_substrate_W', 'P_out_of_substrate_W', 'positive_contact_voxels', 'negative_contact_voxels',  # 接續診斷欄位名稱（diagnostic_header）的數值、運算式或資料項目
                          'P_laser_absorbed_total_W', 'P_laser_absorbed_substrate_W', 'P_laser_absorbed_powder_W', 'laser_z_peak_index', 'laser_z_peak_center_um', 'laser_z_peak_W',  # 接續診斷欄位名稱（diagnostic_header）的數值、運算式或資料項目
                          'recoil_pressure_max_Pa', 'keyhole_candidate_voxels']  # 接續診斷欄位名稱（diagnostic_header）的數值、運算式或資料項目
    if not hasattr(heat, 'diagnose_substrate_heat_flux'):  # 判斷本行條件，成立時執行下方處理
        raise AttributeError('蝚?04 ?舐撩撠?diagnose_substrate_heat_flux()嚗?雿輻撌脣??亥那?瑞? 04 璅∠?')  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    # 開啟本行所列檔案，離開區塊時自動關閉資源
    # 【續行第 1 列】開啟本行指定的輸出檔案，離開區塊後自動關閉
    # 【續行第 2 列】開啟本行指定的輸出檔案，離開區塊後自動關閉
    # 【續行第 3 列】開啟本行指定的輸出檔案，離開區塊後自動關閉
    # 【續行第 4 列】開啟本次輸出目錄、主能量 CSV 檔案，離開區塊後自動關閉
    # 【續行第 5 列】開啟本次輸出目錄、相變與導熱明細 CSV 檔案，離開區塊後自動關閉
    # 【續行第 6 列】開啟本次輸出目錄、Markdown 能量報表，離開區塊後自動關閉
    with (absorption_comparison_path.open('w', newline='', encoding='utf-8-sig') if settings.diagnostic_csv else io.StringIO()) as absorption_stream, \
         (diagnostic_csv_path.open('w', newline='', encoding='utf-8-sig') if settings.diagnostic_csv else io.StringIO()) as diagnostic_stream, \
         (z_csv_path.open('w', newline='', encoding='utf-8-sig') if settings.diagnostic_csv else io.StringIO()) as z_stream, \
         (output_dir / 'energy_budget_by_distance.csv').open('w', newline='', encoding='utf-8-sig') as energy_stream, \
         ((diagnostic_dir / 'phase_change_and_conduction_by_distance.csv').open('w', newline='', encoding='utf-8-sig') if settings.diagnostic_csv else io.StringIO()) as detail_stream, \
         (output_dir / 'energy_budget_by_distance.md').open('w', encoding='utf-8') as energy_markdown, \
         ((diagnostic_dir / 'thermal_history_diagnostics.csv').open('w', newline='', encoding='utf-8-sig') if settings.diagnostic_csv else io.StringIO()) as raw_stream, \
         (audit_csv_path.open('w', newline='', encoding='utf-8-sig') if settings.diagnostic_csv else io.StringIO()) as audit_stream:  # 診斷停用時只使用記憶體，不建立多餘 CSV
        energy_writer = csv.writer(energy_stream)  # 計算或建立主能量 CSV 寫入器
        energy_writer.writerow(thermal_csv_header())  # 最終距離結果改用精簡中英寬表
        energy_stream.flush()  # 尚未完成時仍立即寫出標頭
        detail_writer = csv.writer(detail_stream)  # 計算或建立明細 CSV 寫入器
        detail_writer.writerow(bilingual_csv_header(['step', 'time_us', 'scan_distance_um', 'energy_item', 'energy_J', 'percent_of_absorbed']))  # 依既定欄位順序寫入一列 CSV 資料
        energy_markdown.write(  # 將報表文字寫入檔案
            '# 雷射掃描累積能量表\n\n'  # 將報表文字寫入檔案
            '距離相對於掃描起點；各項為從初始狀態到該距離的全域累積量，單位 J。\n'  # 將報表文字寫入檔案
            '顯熱分列金屬與氣體；熔化潛熱為剩餘金屬目前保留的存量，不是累計熔化耗能。\n'  # 將報表文字寫入檔案
            '導電邊界損耗使用底部邊界散熱，內部導熱不計為全域損失。\n'  # 將報表文字寫入檔案
            '汽化潛熱另列為相變吸收；蒸發損失僅含移除金屬攜出的焓。\n'  # 說明報表已將汽化潛熱與蒸發損失拆開
            '汽化仍消耗能量，並與攜出焓分開列帳，總能量收支不變。\n\n')  # 保留物理守恆與明確統計定義
        audit_writer = csv.writer(audit_stream)  # 計算或建立固定網格審計 CSV 寫入器
        audit_writer.writerow(bilingual_csv_header(audit_header))  # 依既定欄位順序寫入一列 CSV 資料
        writer = csv.writer(raw_stream)  # 原詳細歷程只寫入選用診斷
        absorption_writer = csv.writer(absorption_stream)  # 計算或建立寫入器（absorption_writer）
        diagnostic_writer = csv.writer(diagnostic_stream)  # 計算或建立診斷寫入器（diagnostic_writer）
        z_writer = csv.writer(z_stream)  # 計算或建立逐層功率 CSV 寫入器
        z_writer.writerow(bilingual_csv_header(['step', 'time_us', 'laser_x_um', 'z_index', 'z_center_um', 'absorbed_power_W', 'fraction_of_absorbed_power']))  # 依既定欄位順序寫入一列 CSV 資料
        writer.writerow(bilingual_csv_header(header))  # 依既定欄位順序寫入一列 CSV 資料
        absorption_writer.writerow(bilingual_csv_header(['step', 'time_us', 'scan_distance_um', 'scan_fraction_pct', 'incident_energy_J', 'solid_reference_absorptivity_pct', 'theoretical_absorbed_J', 'actual_absorbed_J', 'actual_minus_theory_J', 'relative_error_pct']))  # 固態參考值改用指定吸收率，避免誤標為 Fresnel 計算
        diagnostic_writer.writerow(bilingual_csv_header(diagnostic_header))  # 依既定欄位順序寫入一列 CSV 資料
        for step in range(n_steps + 1):  # 依序處理step，逐項套用下方運算
            time_s = min(step * dt, max_time)  # 計算或建立模擬時間（s）
            lx, ly, on, _, laser_result = laser.compute_laser_step(  # 計算或建立雷射 X 座標（m）、雷射 Y 座標（m）、雷射是否開啟、變數 _、雷射位置對應的吸收與功率審計結果
                F, xp, settings, time_s, liquid_fraction=fL,  # 接續雷射 X 座標（m）、雷射 Y 座標（m）、雷射是否開啟、變數 _、雷射位置對應的吸收與功率審計結果的參數：執行單一步雷射計算
            )  # 結束本段參數、容器或條件的組合
            # 以實際使用的本步吸收功率與當前金屬幾何計算，並輸出至獨立 CSV。
            if step > 0 and (step % laser_depth_every == 0 or step == n_steps):
                depth_metrics = laser.diagnose_laser_absorption_depth(
                    laser_result, F, dx_m, xp
                )
                depth_values = [
                    step, time_s * 1e6, float(lx) * 1e6, int(on),
                    scalar(laser_result['incident_power_domain_W']),
                    scalar(laser_result['absorbed_power_W']),
                    *[scalar(depth_metrics[key]) for key in laser_depth_columns[6:]],
                ]
                with laser_depth_csv_path.open('a', newline='', encoding='utf-8-sig') as depth_file:
                    csv.writer(depth_file).writerow(depth_values)
            if step == 0:  # 判斷本行條件，成立時執行下方處理
                laser_initial_x_m = float(lx)  # 計算或建立雷射初始（laser_initial_x_m）
                laser_previous_check_x_m = float(lx)  # 計算或建立雷射（laser_previous_check_x_m）
                laser_previous_check_time_s = float(time_s)  # 計算或建立雷射時間（laser_previous_check_time_s）
                print(f'[LASER CONFIG] speed={settings.speed:.6f} mm/s '  # 輸出本階段的數值、進度或診斷訊息
                      f'dt={dt*1e9:.6f} ns start_x={laser_initial_x_m*1e6:.6f} um '  # 輸出本階段的數值、進度或診斷訊息
                      f'scan_duration={scan_duration*1e6:.3f} us', flush=True)  # 輸出本階段的數值、進度或診斷訊息
            if step % 1000 == 0:  # 依步數間隔或終止條件決定是否執行檢查與輸出
                expected_distance_um = settings.speed * 1e-3 * min(time_s, scan_duration) * 1e6  # 計算或建立距離（expected_distance_um）
                actual_signed_distance_um = (float(lx) - laser_initial_x_m) * 1e6  # 計算或建立距離（actual_signed_distance_um）
                actual_distance_um = abs(actual_signed_distance_um)  # 計算或建立距離（actual_distance_um）
                position_error_um = actual_distance_um - expected_distance_um  # 計算或建立位置誤差（position_error_um）
                expected_interval_um = settings.speed * 1e-3 * (float(time_s) - laser_previous_check_time_s) * 1e6 if on else 0.0  # 計算或建立變數 expected_interval_um
                actual_interval_um = abs(float(lx) - laser_previous_check_x_m) * 1e6  # 計算或建立變數 actual_interval_um
                print(f'[LASER MOVE] STEP={step} t={time_s*1e6:.3f} us '  # 輸出本階段的數值、進度或診斷訊息
                      f'speed={settings.speed:.1f} mm/s expected={expected_distance_um:.6f} um '  # 輸出本階段的數值、進度或診斷訊息
                      f'actual={actual_distance_um:.6f} um error={position_error_um:+.6e} um '  # 輸出本階段的數值、進度或診斷訊息
                      f'x_now={float(lx)*1e6:.6f} um '  # 輸出本階段的數值、進度或診斷訊息
                      f'interval_expected={expected_interval_um:.6f} um '  # 輸出本階段的數值、進度或診斷訊息
                      f'interval_actual={actual_interval_um:.6f} um laser_on={int(on)}', flush=True)  # 輸出本階段的數值、進度或診斷訊息
                laser_previous_check_x_m = float(lx)  # 計算或建立雷射（laser_previous_check_x_m）
                laser_previous_check_time_s = float(time_s)  # 計算或建立雷射時間（laser_previous_check_time_s）
            completed = False  # 計算或建立是否已達再凝固完成條件
            completion_check_every = max(1, settings.check_every)  # 計算或建立變數 completion_check_every
            if not on and (step % completion_check_every == 0 or step == n_steps):  # 依步數間隔或終止條件決定是否執行檢查與輸出
                completed = (bool(scalar(xp.any(ever_melted))) and  # 計算或建立是否已達再凝固完成條件
                             not bool(scalar(xp.any((F >= material.MINIMUM_ACTIVE_METAL_FILL) &  # 接續是否已達再凝固完成條件的數值、運算式或資料項目
                                                    (fL > settings.solidification_tol)))))  # 接續是否已達再凝固完成條件的數值、運算式或資料項目
            distance_report = (step > 0 and step % report_every == 0 and  # 只有到達設定距離且仍在掃描路徑內時，才輸出距離能量表
                               step * dt <= scan_duration + 1e-15)  # 接續是否已到達能量表輸出距離的數值、運算式或資料項目
            record = (step % log_every == 0 or step % save_every == 0 or step == n_steps or completed or distance_report)  # 計算或建立本步是否需要記錄狀態
            if record:  # 判斷本行條件，成立時執行下方處理
                depths = phase.calculate_substrate_melt_depths(F, fL, ever_melted,  # 計算或建立基板各定義的熔深字典
                                   substrate_top_index, settings.grid_um, xp)  # 接續基板各定義的熔深字典的參數：計算基板內的熔化深度
                counts = [int(scalar(xp.sum(phase_codes == code))) for code in (1, 2, 3, 4)]  # 計算或建立各相態有效網格數
                stored = scalar(xp.sum(H)) * dx_m**3  # 計算或建立目前全域總焓（J）
                energy_components = phase.energy_components_from_temperature(T, F, xp, split_sensible_phases=True)  # 分相只影響輸出分類，不改變焓求解器
                E_sensible_solid = scalar(xp.sum(energy_components['metal_solid_sensible_J_m3'])) * dx_m**3 - initial_solid_sensible_J  # 固態份額顯熱相對初始的變化
                E_sensible_liquid = scalar(xp.sum(energy_components['metal_liquid_sensible_J_m3'])) * dx_m**3 - initial_liquid_sensible_J  # 液態份額顯熱相對初始的變化
                E_sensible_metal = (scalar(xp.sum(energy_components['metal_sensible_J_m3'])) * dx_m**3  # 計算或建立金屬顯熱增加（J）
                                    - initial_metal_sensible_J)  # 接續金屬顯熱增加（J）的數值、運算式或資料項目
                E_latent = (scalar(xp.sum(energy_components['metal_latent_J_m3'])) * dx_m**3  # 計算或建立目前熔化潛熱存量增加（J）
                            - initial_metal_latent_J)  # 接續目前熔化潛熱存量增加（J）的數值、運算式或資料項目
                E_sensible_gas = (scalar(xp.sum(energy_components['gas_sensible_J_m3'])) * dx_m**3  # 計算或建立氣體顯熱增加（J）
                                  - initial_gas_sensible_J)  # 接續氣體顯熱增加（J）的數值、運算式或資料項目
                E_sensible = E_sensible_metal + E_sensible_gas  # 金屬顯熱增加與氣體顯熱增加相加，得到全域顯熱存量增加
                initial_stored = (initial_metal_sensible_J + initial_metal_latent_J +  # 計算或建立初始（initial_stored）
                                  initial_gas_sensible_J)  # 接續初始（initial_stored）的數值、運算式或資料項目
                stored_change = stored - initial_stored  # 目前總焓扣除初始總焓，得到相同參考點的儲存能量增加
                decomposition_error = E_sensible + E_latent - stored_change  # 檢查顯熱增加加熔化潛熱增加是否等於總焓增加
                if abs(decomposition_error) > 1e-8 * max(abs(stored_change), 1e-12):  # 判斷本行條件，成立時執行下方處理
                    raise FloatingPointError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
                        f'Sensible/latent decomposition disagrees with enthalpy at step={step}: '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'error={decomposition_error:.6e} J')  # 接續本段欄位名稱、提示訊息或報表文字
                Eabs, Econv, Erad, Ebottom, Eevap = cpu_array(energy_acc, xp).tolist()  # 計算或建立累積吸收雷射能量（J）、累積對流損失（J）、累積輻射損失（J）、累積底部外流能量（J）、累積蒸發損失（J）
                details = dict(zip((key for key, _ in ENERGY_DETAIL_LABELS[:7]),  # 計算或建立相變及導熱明細字典
                                   cpu_array(phase_transfer_acc, xp).tolist()))  # 接續相變及導熱明細字典的參數：執行 dict 呼叫並完成該步處理
                details['Econd_net_into_substrate_J'] = details['Econd_into_substrate_J'] - details['Econd_from_substrate_J']  # 計算或建立相變及導熱明細字典的傳入基板（Econd_net_into_substrate_J）欄位
                details['Efusion_balance_residual_J'] = (details['Emelting_cumulative_J'] -  # 計算或建立相變及導熱明細字典的收支殘差（Efusion_balance_residual_J）欄位
                    details['Esolidification_released_J'] - details['Eevaporated_fusion_latent_J'] - E_latent)  # 接續相變及導熱明細字典的收支殘差（Efusion_balance_residual_J）欄位的數值、運算式或資料項目
                if abs(details['Efusion_balance_residual_J']) > 1e-8 * max(  # 目前沒有物質搬運，必須檢查固液潛熱完整收支
                        details['Emelting_cumulative_J'], abs(E_latent), 1e-12):  # 接續本段運算：相變及導熱明細字典、目前熔化潛熱存量增加（J）
                    raise FloatingPointError(f'Fusion latent balance mismatch at step={step}: {details["Efusion_balance_residual_J"]:.6e} J')  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
                if distance_report:  # 到達指定掃描距離時輸出累積能量及相變明細
                    write_distance_energy_report(  # 輸出指定掃描距離的能量表
                        None, energy_markdown, step, time_s,  # Markdown 保留分類表，CSV 改在下方寫入寬表
                        stop_distance_um,  # 輸出實際終止時的掃描距離
                        Eabs, E_sensible_metal, E_sensible_gas, E_latent,  # 輸出指定掃描距離的能量表
                        Ebottom, Econv, Erad, Eevap, details=details, details_writer=detail_writer)  # 輸出指定掃描距離的能量表
                    energy_stream.flush()  # 將已寫入的緩衝資料送往檔案
                    detail_stream.flush()  # 將已寫入的緩衝資料送往檔案
                sensible_pct_Eabs = 100.0 * E_sensible / Eabs if Eabs > 0.0 else 0.0  # 計算或建立顯熱百分比（sensible_pct_Eabs）
                latent_pct_Eabs = 100.0 * E_latent / Eabs if Eabs > 0.0 else 0.0  # 計算或建立潛熱百分比（latent_pct_Eabs）
                residual_J = Eabs-Econv-Erad-Ebottom-Eevap-stored  # 雷射吸收能量扣除各項外流與目前儲能，計算全域能量平衡殘差
                err = 100 * residual_J / max(abs(Eabs), abs(stored), 1e-20)  # 計算或建立全域能量平衡相對誤差（%）
                if abs(err) > 5.0:  # 判斷本行條件，成立時執行下方處理
                    print(f'[ENERGY BALANCE WARNING] step={step} t={time_s*1e6:.3f}us '  # 輸出本階段的數值、進度或診斷訊息
                          f'residual={residual_J:+.6e}J error={err:+.3f}% '  # 輸出本階段的數值、進度或診斷訊息
                          f'(configured diagnostic threshold=5%)', flush=True)  # 輸出本階段的數值、進度或診斷訊息
                min_metal_T = scalar(xp.min(xp.where(F >= material.MINIMUM_ACTIVE_METAL_FILL, T, xp.inf)))  # 計算或建立最小金屬（min_metal_T）
                max_metal_T = scalar(xp.max(xp.where(F >= material.MINIMUM_ACTIVE_METAL_FILL, T, -xp.inf)))  # 計算或建立最大金屬（max_metal_T）
                max_gas_T = scalar(xp.max(xp.where(F < material.MINIMUM_ACTIVE_METAL_FILL, T, -xp.inf))) if bool(scalar(xp.any(F < material.MINIMUM_ACTIVE_METAL_FILL))) else float('nan')  # 計算或建立最大氣體（max_gas_T）
                row = [step, time_s*1e6, int(on), lx*1e6, scalar(xp.max(T)), max_metal_T, max_gas_T, min_metal_T,  # 計算或建立本步熱歷程 CSV 資料列
                        *counts, Eabs, Eincident_cumulative_J,  # 詳細診斷記錄累積量，主表則記錄單步量
                        E_sensible, E_sensible_metal, E_sensible_gas, E_latent,  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                        sensible_pct_Eabs, latent_pct_Eabs,  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                        Econv, Erad, Ebottom, Eevap, stored, err,  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                       depths['Dsub_mushy_um'], depths['Dsub_liquid_um'], depths['Dsub_ever_um'], int(completed),  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                       scalar(xp.max(last_q_fields['Qlaser_W_m3'])) if last_q_fields is not None else 0.,  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                       scalar(last_q_fields['Qcond_W_m3'][xp.unravel_index(xp.argmax(xp.where(F>=material.MINIMUM_ACTIVE_METAL_FILL,T,-xp.inf)),T.shape)]) if last_q_fields is not None else 0.,  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                       scalar(last_q_fields['Qconv_W_m3'][xp.unravel_index(xp.argmax(xp.where(F>=material.MINIMUM_ACTIVE_METAL_FILL,T,-xp.inf)),T.shape)]) if last_q_fields is not None else 0.,  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                       scalar(last_q_fields['Qrad_W_m3'][xp.unravel_index(xp.argmax(xp.where(F>=material.MINIMUM_ACTIVE_METAL_FILL,T,-xp.inf)),T.shape)]) if last_q_fields is not None else 0.,  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                       scalar(last_q_fields['Qevap_diagnostic_W_m3'][xp.unravel_index(xp.argmax(xp.where(F>=material.MINIMUM_ACTIVE_METAL_FILL,T,-xp.inf)),T.shape)]) if last_q_fields is not None else 0.,  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                       last_powers['Pconv_W'],last_powers['Prad_W'],last_powers['Pevap_diagnostic_W'],  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                       last_powers['Aconv_rad_m2'], residual_J, err,  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                       scalar(xp.sum(F0 - F)) * material.SOLID_DENSITY_KG_M3 * dx_m**3]  # 接續本步熱歷程 CSV 資料列的數值、運算式或資料項目
                row.extend(details[key] for key, _ in ENERGY_DETAIL_LABELS)  # 把本行各項依序加入清單
                latent_accounted_J = E_latent + details['Evaporization_latent_J']  # 報表潛熱合計為熔化存量加累積汽化吸收
                evaporation_enthalpy_loss_J = Eevap - details['Evaporization_latent_J']  # 蒸發攜出焓損失不含汽化潛熱
                report_pct_scale = 100.0 / Eabs if Eabs > 0.0 else 0.0  # 無雷射吸收時避免除以零
                row.extend([latent_accounted_J, latent_accounted_J * report_pct_scale,  # 附加潛熱合計的能量與百分比
                            details['Evaporization_latent_J'] * report_pct_scale,  # 附加汽化潛熱百分比
                            evaporation_enthalpy_loss_J, evaporation_enthalpy_loss_J * report_pct_scale])  # 附加蒸發攜出焓損失能量與百分比
                summary = {  # 主要 CSV 用字典組裝，避免欄位順序與數值錯位
                    'step': step, 'time_us': time_s * 1e6, 'laser_x_um': lx * 1e6,  # 時間與雷射位置
                    'Tmax_solid_K': phase_max_temperature(T, (phase_codes == 1) | (phase_codes == 4), xp),  # 包含再凝固金屬
                    'Tmax_liquid_K': phase_max_temperature(T, phase_codes == 3, xp),  # 無液態時留白
                    'Tmax_argon_K': phase_max_temperature(T, phase_codes == 0, xp),  # 使用氬氣物性的氣體區溫度
                    'Tmax_metal_vapor_K': '',  # 沒有獨立金屬蒸氣溫度場
                    'solid_cells': counts[0], 'mushy_cells': counts[1],  # 固態與共存網格數
                    'liquid_cells': counts[2], 'resolidified_cells': counts[3],  # 液態與再凝固網格數
                    'argon_cells': int(scalar(xp.count_nonzero(phase_codes == 0))),  # 氣體區網格數，不是純物種體積分率
                    'metal_vapor_cells': '',  # 未追蹤蒸氣空間分布，不能輸出零冒充結果
                    'metal_vapor_generated_kg': details['Evaporization_latent_J'] / material.LATENT_HEAT_VAPORIZATION_J_KG,  # 由累積汽化潛熱換算已汽化質量
                    'Dsub_liquid_um': depths['Dsub_liquid_um'], 'Dsub_ever_um': depths['Dsub_ever_um'],  # 當前與歷史基板熔深
                    'Pincident_W': settings.power if on else 0.0,  # 雷射開啟期間固定顯示設定瓦數
                    'Eincident_J': settings.power * dt if on else 0.0,  # 使用者指定輸出單步能量，固定步長下每列相同
                    'Eabs_J': Eabs,  # 吸收與後續熱量欄仍是累積或存量變化，維持原能量收支
                    'Esensible_solid_J': E_sensible_solid, 'Esensible_liquid_J': E_sensible_liquid,  # 共存區按相比例分配顯熱
                    'Esensible_argon_J': E_sensible_gas, 'Elatent_fusion_J': E_latent,  # 氬氣背景顯熱與熔化潛熱存量變化
                    'Esensible_metal_vapor_J': '',  # 尚未計算域內金屬蒸氣儲能
                    'Elatent_vaporization_J': details['Evaporization_latent_J'],  # 目前僅計汽化吸收，未計凝結
                    'Econv_J': Econv, 'Erad_J': Erad, 'Ebottom_J': Ebottom,  # 三項對外熱損失
                    'Eevap_J': evaporation_enthalpy_loss_J,  # 蒸發攜出焓，不重複包含汽化潛熱
                    'Umax_liquid_m_s': '', 'Umax_argon_m_s': '', 'Umax_metal_vapor_m_s': '',  # 未求解流動，三類流速分開留白
                    'energy_error_pct': err,  # 完整物理能量收支誤差
                }  # 結束主要欄位字典
                summary_row = [summary[name] for _, name, _ in THERMAL_CSV_COLUMNS]  # 依固定分類順序產生一列資料
                if distance_report:  # 到達目標距離時最終 CSV 僅輸出一列
                    energy_writer.writerow(summary_row)  # 使用與主要歷程相同的中英寬表
                    energy_stream.flush()  # 最終結果立即落盤
                if step % log_every == 0 or step == n_steps or completed:  # 依步數間隔或終止條件決定是否執行檢查與輸出
                    if step > 0:  # 初始零步不占用每段一百筆資料的配額
                        write_segmented_history(output_dir, step, summary_row)  # 每千步分檔並立即保存
                    writer.writerow(row)  # 詳細診斷僅在啟用時另存
                    raw_stream.flush()  # 即時寫出選用診斷
                    total_scan_distance_um = scan_duration * settings.speed * 1e-3 * 1e6  # 計算或建立總計掃描距離（total_scan_distance_um）
                    scan_distance_um = min(abs(float(lx) - laser_initial_x_m) * 1e6, total_scan_distance_um)  # 計算或建立掃描距離（scan_distance_um）
                    scan_fraction = min(max(scan_distance_um / total_scan_distance_um, 0.0), 1.0)  # 計算或建立掃描比例（scan_fraction）
                    theoretical_absorptivity = laser.ABSORPTIVITY_SOLID  # 計算或建立變數 theoretical_absorptivity
                    theoretical_absorbed_J = Eincident_cumulative_J * theoretical_absorptivity  # 累積理論吸收必須使用累積入射量
                    absorption_difference_J = Eabs - theoretical_absorbed_J  # 計算或建立變數 absorption_difference_J
                    absorption_relative_error_pct = (  # 計算或建立誤差百分比（absorption_relative_error_pct）
                        100.0 * absorption_difference_J / theoretical_absorbed_J  # 接續誤差百分比（absorption_relative_error_pct）的數值、運算式或資料項目
                        if theoretical_absorbed_J > 0.0 else 0.0  # 判斷本行條件，成立時執行下方處理
                    )  # 結束本段參數、容器或條件的組合
                    absorption_writer.writerow([  # 依既定欄位順序寫入一列 CSV 資料
                        step, time_s * 1e6, scan_distance_um, scan_fraction * 100.0,  # 依既定欄位順序寫入一列 CSV 資料
                        Eincident_cumulative_J, theoretical_absorptivity * 100.0, theoretical_absorbed_J,  # 累積能量比較不使用單步輸入值
                        Eabs, absorption_difference_J, absorption_relative_error_pct,  # 依既定欄位順序寫入一列 CSV 資料
                    ])  # 結束本段參數、容器或條件的組合
                    absorption_stream.flush()  # 將已寫入的緩衝資料送往檔案
                    print(f'[STEP] {step} t={time_s*1e6:.3f}us laser={int(on)} '  # 輸出本階段的數值、進度或診斷訊息
                          f'Tmax_metal={max_metal_T:.1f}K Tmax_gas={max_gas_T:.1f}K S/M/L/RS={counts} '  # 輸出本階段的數值、進度或診斷訊息
                          f'Dsub={depths["Dsub_liquid_um"]:.1f}um Eerr={err:.4g}% '  # 輸出本階段的數值、進度或診斷訊息
                          f'Pconv={last_powers["Pconv_W"]:.4e}W Prad={last_powers["Prad_W"]:.4e}W '  # 輸出本階段的數值、進度或診斷訊息
                      f'Pevap={last_powers["Pevap_diagnostic_W"]:.4e}W')  # 輸出本階段的數值、進度或診斷訊息
                if step % save_every == 0 or step == n_steps or completed:  # 依步數間隔或終止條件決定是否執行檢查與輸出
                    saved = save_voxel_state(output_dir, step, time_s, F, F0, H, T, fL, phase_codes,  # 計算或建立變數 saved
                           substrate_mask_cpu, mask_cpu, ever_melted, on, lx, ly,  # 接續變數 saved的參數：儲存完整三維網格狀態
                           settings.grid_um, settings.substrate_um, depths, xp, last_q_fields, residual_J)  # 接續變數 saved的參數：儲存完整三維網格狀態
                    print(f'[NPZ] {saved.name}  shape={F.shape}')  # 輸出本階段的數值、進度或診斷訊息
            if step % audit_every == 0 or completed or step == n_steps:  # 依步數間隔或終止條件決定是否執行檢查與輸出
                audit_q_keys = ('Qcond', 'Qconv', 'Qrad', 'Qevap')  # 計算或建立固定網格審計（audit_q_keys）
                audit_values = cpu_array(xp.stack([  # 計算或建立一次傳回 CPU 的審計純量向量
                    *[audit_acc[name] for name in audit_components],  # 接續一次傳回 CPU 的審計純量向量的參數：執行 tolist 呼叫並完成該步處理
                    H[audit_index], T[audit_index], F[audit_index], audit_initial_H,  # 接續一次傳回 CPU 的審計純量向量的參數：執行 tolist 呼叫並完成該步處理
                    audit_last_qlaser, audit_last_qnet,  # 接續一次傳回 CPU 的審計純量向量的參數：執行 tolist 呼叫並完成該步處理
                    *[audit_last_components[key] for key in audit_q_keys],  # 接續一次傳回 CPU 的審計純量向量的參數：執行 tolist 呼叫並完成該步處理
                ]), xp).tolist()  # 接續一次傳回 CPU 的審計純量向量的參數：執行 tolist 呼叫並完成該步處理
                audit_E = dict(zip(audit_components, audit_values[:len(audit_components)]))  # 計算或建立傳回 CPU 的審計能量字典
                (audit_H_now, audit_T_now, audit_F_now, audit_H_initial,  # 計算或建立固定網格審計（audit_H_now）、固定網格審計（audit_T_now）、固定網格審計（audit_F_now）、固定網格審計初始（audit_H_initial）、固定網格審計雷射熱源（audit_qlaser_now）、固定網格審計淨熱源（audit_qnet_now）、*audit_q_values
                 audit_qlaser_now, audit_qnet_now, *audit_q_values) = audit_values[len(audit_components):]  # 接續固定網格審計（audit_H_now）、固定網格審計（audit_T_now）、固定網格審計（audit_F_now）、固定網格審計初始（audit_H_initial）、固定網格審計雷射熱源（audit_qlaser_now）、固定網格審計淨熱源（audit_qnet_now）、*audit_q_values的數值、運算式或資料項目
                audit_delta_H_J = (audit_H_now - audit_H_initial) * audit_volume_m3  # 計算或建立固定網格總焓變化（J）
                audit_residual_J = audit_delta_H_J - audit_E['net']  # 計算或建立固定網格能量收支殘差（J）
                audit_scale_J = max(abs(audit_delta_H_J), abs(audit_E['net']), abs(audit_E['laser']), 1e-20)  # 計算或建立固定網格誤差正規化尺度
                audit_error_pct = 100.0 * audit_residual_J / audit_scale_J  # 計算或建立固定網格能量相對誤差（%）
                audit_x_um = (audit_index[0] + 0.5) * settings.grid_um  # 計算或建立固定網格審計（audit_x_um）
                audit_y_um = (audit_index[1] + 0.5) * settings.grid_um  # 計算或建立固定網格審計（audit_y_um）
                audit_z_um = (audit_index[2] + 0.5) * settings.grid_um  # 計算或建立固定網格審計Z方向（audit_z_um）
                audit_distance_um = math.hypot(audit_x_um - lx * 1e6, audit_y_um - ly * 1e6)  # 計算或建立固定網格審計距離（audit_distance_um）
                audit_writer.writerow([step, time_s*1e6, *audit_index, audit_x_um, audit_y_um, audit_z_um,  # 依既定欄位順序寫入一列 CSV 資料
                                       lx*1e6, audit_distance_um, audit_F_now, audit_T_now, audit_H_now,  # 依既定欄位順序寫入一列 CSV 資料
                                       audit_E['laser'], audit_E['conduction'], audit_E['convection'],  # 依既定欄位順序寫入一列 CSV 資料
                                       audit_E['radiation'], audit_E['bottom'], audit_E['net'],  # 依既定欄位順序寫入一列 CSV 資料
                                       audit_delta_H_J, audit_residual_J, audit_error_pct,  # 依既定欄位順序寫入一列 CSV 資料
                                       audit_qlaser_now, audit_qnet_now, *audit_q_values])  # 依既定欄位順序寫入一列 CSV 資料
                audit_stream.flush()  # 將已寫入的緩衝資料送往檔案
                print(f'[VOXEL ENERGY] step={step} t={time_s*1e6:.3f}us xyz={audit_index} '  # 輸出本階段的數值、進度或診斷訊息
                      f'T={audit_T_now:.1f}K Elaser={audit_E["laser"]:.6e}J '  # 輸出本階段的數值、進度或診斷訊息
                      f'Econd={audit_E["conduction"]:.6e}J Eloss='  # 輸出本階段的數值、進度或診斷訊息
                      f'{audit_E["convection"]+audit_E["radiation"]+audit_E["bottom"]:.6e}J '  # 輸出本階段的數值、進度或診斷訊息
                      f'dH={audit_delta_H_J:.6e}J residual={audit_residual_J:+.6e}J '  # 輸出本階段的數值、進度或診斷訊息
                      f'error={audit_error_pct:+.4e}% distance={audit_distance_um:.2f}um', flush=True)  # 輸出本階段的數值、進度或診斷訊息
            if completed or step == n_steps:  # 判斷本行條件，成立時執行下方處理
                print(f'[DONE] step={step}; laser travelled {stop_distance_um:g} um; '  # 輸出實際終止步數與距離
                      'energy report saved; simulation stopped without cooling.'  # 輸出本階段的數值、進度或診斷訊息
                      if step == n_steps else '[DONE] Solidification completed.')  # 判斷本行條件，成立時執行下方處理
                break  # 結束目前迴圈，不再進行下一步計算
            step_dt = min(dt, max_time-time_s)  # 計算或建立本步實際時間步長（s）
            ambient_area_factor = heat.calculate_gas_facing_face_area(F, xp)  # 計算或建立對流及輻射暴露面積係數
            ambient_area_m2 = xp.sum(ambient_area_factor) * dx_m**2  # 計算或建立對流及輻射總暴露面積（m²）
            heat_terms = heat.calculate_heat_transfer_and_loss(  # 計算或建立導熱與各種邊界熱損失結果
                temperature_K=T, metal_fill_fraction=F, voxel_size_m=dx_m,  # 接續導熱與各種邊界熱損失結果的參數：整合導熱與邊界熱損失
                ambient_temperature_K=293.15, ambient_h_W_m2_K=settings.ambient_h,  # 接續導熱與各種邊界熱損失結果的參數：整合導熱與邊界熱損失
                bottom_h_W_m2_K=settings.bottom_h, xp=xp, liquid_fraction=fL, gas_k=settings.gas_k,  # 接續導熱與各種邊界熱損失結果的參數：整合導熱與邊界熱損失
                exposed_area_factor=ambient_area_factor, exposed_surface_area_m2=ambient_area_m2)  # 接續導熱與各種邊界熱損失結果的參數：整合導熱與邊界熱損失
            interface_into, interface_out = heat.calculate_substrate_interface_power(  # 計算或建立粉末傳入基板的功率（W）、基板回傳粉末的功率（W）
                T, F, substrate_top_index, dx_m, xp, liquid_fraction=fL, gas_k=settings.gas_k)  # 接續粉末傳入基板的功率（W）、基板回傳粉末的功率（W）的參數：計算粉末與基板的界面導熱
            base_power = (laser_result['absorption_W_m3'] +  # 雷射吸收加內部導熱與邊界散熱，尚未扣除蒸發
                          heat_terms['net_without_laser_W_m3'])  # 接續扣除蒸發前的總淨熱源的數值、運算式或資料項目
            F_before_evaporation = F  # 保留移除質量前的金屬量，讓相變分解不把蒸發誤判為凝固
            applied_evaporation_area = evaporation_area_factor  # 保留本步實際使用的蒸發面積，避免錯誤診斷讀到更新後下一步的面積
            fraction_before = phase.liquid_fraction_from_temperature(T, xp)  # 保留熱更新前的液相率，用來分辨後續熔化與凝固
            if stage04_validation or settings.evaporation_model == 'off':  # 依熱傳驗證或停用蒸發設定選擇對應計算分支
                qevap = xp.zeros_like(F, dtype=xp.float64)  # 計算或建立蒸發損失功率密度（W/m³）
                F_after_evaporation = F  # 計算或建立蒸發後金屬填充率
                keyhole_candidate_count = xp.asarray(0, dtype=xp.int64)  # 計算或建立可能開孔的表面網格數
                recoil_pressure_max = xp.asarray(0.0, dtype=xp.float64)  # 計算或建立最大反衝壓（Pa）
                T_before_evaporation = phase.temperature_from_enthalpy(H + base_power * step_dt, F, xp)  # 計算或建立蒸發前預測溫度
            elif settings.evaporation_model == 'boiling':  # 判斷本行條件，成立時執行下方處理
                qevap, F_after_evaporation, keyhole_candidate_count, recoil_pressure_max, T_before_evaporation = apply_boiling_plateau_evaporation(  # 計算或建立蒸發損失功率密度（W/m³）、蒸發後金屬填充率、可能開孔的表面網格數、最大反衝壓（Pa）、蒸發前預測溫度
                    H, F, base_power, step_dt, evaporation_area_factor, fL, dx_m, xp, return_temperature=True)  # 接續蒸發損失功率密度（W/m³）、蒸發後金屬填充率、可能開孔的表面網格數、最大反衝壓（Pa）、蒸發前預測溫度的參數：執行舊版沸點蒸發對照
            else:  # 前述條件不成立時，改採以下處理方式
                qevap, F_after_evaporation, keyhole_candidate_count, recoil_pressure_max, T_before_evaporation = apply_rate_limited_evaporation(  # 計算或建立蒸發損失功率密度（W/m³）、蒸發後金屬填充率、可能開孔的表面網格數、最大反衝壓（Pa）、蒸發前預測溫度
                    H, F, base_power, step_dt, evaporation_area_factor, dx_m, xp,  # 接續蒸發損失功率密度（W/m³）、蒸發後金屬填充率、可能開孔的表面網格數、最大反衝壓（Pa）、蒸發前預測溫度的參數：以表面蒸發速率更新質量與能量
                    accommodation=settings.evaporation_coefficient,  # 接續蒸發損失功率密度（W/m³）、蒸發後金屬填充率、可能開孔的表面網格數、最大反衝壓（Pa）、蒸發前預測溫度的參數：以表面蒸發速率更新質量與能量
                    vapor_back_pressure_Pa=settings.vapor_back_pressure, return_temperature=True)  # 接續蒸發損失功率密度（W/m³）、蒸發後金屬填充率、可能開孔的表面網格數、最大反衝壓（Pa）、蒸發前預測溫度的參數：以表面蒸發速率更新質量與能量
            if step % log_every == 0:  # 依步數間隔或終止條件決定是否執行檢查與輸出
                interface = heat.diagnose_substrate_heat_flux(  # 計算或建立變數 interface
                    temperature_K=T, metal_fill_fraction=F,  # 接續變數 interface的參數：診斷粉末與基板間的熱通量
                    substrate_top_index=substrate_top_index, voxel_size_m=dx_m,  # 接續變數 interface的參數：診斷粉末與基板間的熱通量
                    xp=xp, liquid_fraction=fL, gas_k=settings.gas_k)  # 與主計算使用相同氣體導熱率
                psub = scalar(interface['P_powder_to_substrate_W'])  # 計算或建立變數 psub
                qmean = scalar(interface['mean_interface_flux_W_m2'])  # 計算或建立變數 qmean
                p_into = scalar(interface['P_into_substrate_W'])  # 計算或建立傳入（p_into）
                p_out = scalar(interface['P_out_of_substrate_W'])  # 計算或建立流出（p_out）
                contacts_into = int(scalar(interface['positive_contact_voxels']))  # 計算或建立傳入（contacts_into）
                contacts_out = int(scalar(interface['negative_contact_voxels']))  # 計算或建立流出（contacts_out）
                assert abs(psub - (p_into - p_out)) <= 1e-8 * max(1.0, abs(psub), p_into, p_out), "substrate heat flux balance failed"  # 驗證本行守恆、形狀、符號或數值條件；不符合時立即指出錯誤
                contact = scalar(interface['contact_fraction'])  # 計算或建立接觸（contact）
                contact_voxels = int(scalar(interface['contact_voxels']))  # 計算或建立接觸（contact_voxels）
                tsub_max = scalar(interface['Tmax_substrate_K'])  # 計算或建立最大（tsub_max）
                tpow_max = scalar(interface['Tmax_powder_K'])  # 計算或建立最大（tpow_max）
                active = F >= material.MINIMUM_ACTIVE_METAL_FILL  # 計算或建立有效金屬網格遮罩
                flat_index = int(scalar(xp.argmax(xp.where(active, T, -xp.inf))))  # 計算或建立索引（flat_index）
                i, j, k = np.unravel_index(flat_index, T.shape)  # 計算或建立變數 i、變數 j、局部有效導熱率或 Z 索引
                index = (int(i), int(j), int(k))  # 計算或建立索引（index）
                hotspot_T = scalar(T[index])  # 計算或建立變數 hotspot_T
                hotspot_F = scalar(F[index])  # 計算或建立變數 hotspot_F
                hotspot_mass = material.SOLID_DENSITY_KG_M3 * hotspot_F * dx_m**3  # 計算或建立質量（hotspot_mass）
                hotspot_H = scalar(H[index])  # 計算或建立變數 hotspot_H
                hotspot_Qlaser = scalar(laser_result['absorption_W_m3'][index])  # 計算或建立雷射熱源（hotspot_Qlaser）
                hotspot_Qcond = scalar(heat_terms['conduction_W_m3'][index])  # 計算或建立變數 hotspot_Qcond
                hotspot_Qconv = scalar(heat_terms['convection_loss_W_m3'][index])  # 計算或建立變數 hotspot_Qconv
                hotspot_Qrad = scalar(heat_terms['radiation_loss_W_m3'][index])  # 計算或建立變數 hotspot_Qrad
                hotspot_Qevap = scalar(qevap[index])  # 計算或建立變數 hotspot_Qevap
                hotspot_Qnet = scalar(laser_result['absorption_W_m3'][index] +  # 計算或建立淨熱源（hotspot_Qnet）
                                      heat_terms['net_without_laser_W_m3'][index] - qevap[index])  # 接續淨熱源（hotspot_Qnet）的參數：將運算後端純量轉成 Python 數值
                z_powers = cpu_array(laser_result['absorbed_power_by_z_W'], xp).astype(np.float64)  # 計算或建立Z方向（z_powers）
                z_abs_total = float(np.sum(z_powers))  # 計算或建立Z方向總計（z_abs_total）
                z_peak_index = int(np.argmax(z_powers))  # 計算或建立Z方向索引（z_peak_index）
                z_peak_center_um = (z_peak_index + 0.5) * settings.grid_um  # 計算或建立Z方向中心（z_peak_center_um）
                z_peak_power = float(z_powers[z_peak_index])  # 計算或建立Z方向功率（z_peak_power）
                z_sub_power = float(np.sum(z_powers[:substrate_top_index]))  # 計算或建立Z方向功率（z_sub_power）
                z_powder_power = float(np.sum(z_powers[substrate_top_index:]))  # 計算或建立Z方向粉末功率（z_powder_power）
                for z_idx, z_power in enumerate(z_powers):  # 依序處理z_idx, z_power，逐項套用下方運算
                    z_ratio = float(z_power / z_abs_total) if z_abs_total > 0.0 else 0.0  # 計算或建立Z方向（z_ratio）
                    z_writer.writerow([step, time_s*1e6, lx*1e6, z_idx, (z_idx + 0.5) * settings.grid_um, float(z_power), z_ratio])  # 依既定欄位順序寫入一列 CSV 資料
                z_stream.flush()  # 將已寫入的緩衝資料送往檔案
                print(f'[LASER_Z] step={step} t={time_s*1e6:.3f}us '  # 輸出本階段的數值、進度或診斷訊息
                      f'Pabs={z_abs_total:.6e}W Psub_abs={z_sub_power:.6e}W Ppow_abs={z_powder_power:.6e}W '  # 輸出本階段的數值、進度或診斷訊息
                      f'peak_z={z_peak_center_um:.1f}um peak_W={z_peak_power:.6e}W', flush=True)  # 輸出本階段的數值、進度或診斷訊息
                print(f'[INTERFACE] step={step} t={time_s*1e6:.3f}us '  # 輸出本階段的數值、進度或診斷訊息
                      f'Psub={psub:.6e}W qmean={qmean:.6e}W/m2 '  # 輸出本階段的數值、進度或診斷訊息
                      f'Pin={p_into:.6e}W Pout={p_out:.6e}W '  # 輸出本階段的數值、進度或診斷訊息
                      f'contact={contact*100:.2f}% cells={contact_voxels} '  # 輸出本階段的數值、進度或診斷訊息
                      f'Tsub={tsub_max:.1f}K Tpow={tpow_max:.1f}K', flush=True)  # 輸出本階段的數值、進度或診斷訊息
                print(f'[HOTSPOT] step={step} xyz={index} T={hotspot_T:.1f}K '  # 輸出本階段的數值、進度或診斷訊息
                      f'F={hotspot_F:.6f} mass={hotspot_mass:.6e}kg '  # 輸出本階段的數值、進度或診斷訊息
                      f'H={hotspot_H:.6e}J/m3 Qlaser={hotspot_Qlaser:.6e}W/m3 '  # 輸出本階段的數值、進度或診斷訊息
                      f'Qcond={hotspot_Qcond:.6e} Qconv={hotspot_Qconv:.6e} Qrad={hotspot_Qrad:.6e} Qevap_diag={hotspot_Qevap:.6e} Qnet={hotspot_Qnet:.6e} W/m3', flush=True)  # 輸出本階段的數值、進度或診斷訊息
                diagnostic_writer.writerow([step, time_s*1e6, lx*1e6, psub, qmean,  # 依既定欄位順序寫入一列 CSV 資料
                    contact, contact_voxels, tsub_max, tpow_max, *index, hotspot_T,  # 依既定欄位順序寫入一列 CSV 資料
                    hotspot_F, hotspot_mass, hotspot_H, hotspot_Qlaser, hotspot_Qcond, hotspot_Qnet, hotspot_Qconv, hotspot_Qrad, hotspot_Qevap,  # 依既定欄位順序寫入一列 CSV 資料
                    p_into, p_out, contacts_into, contacts_out, z_abs_total, z_sub_power, z_powder_power,  # 依既定欄位順序寫入一列 CSV 資料
                    z_peak_index, z_peak_center_um, z_peak_power,  # 依既定欄位順序寫入一列 CSV 資料
                    scalar(recoil_pressure_max), scalar(keyhole_candidate_count)])  # 依既定欄位順序寫入一列 CSV 資料
                diagnostic_stream.flush()  # 將已寫入的緩衝資料送往檔案
            if step % log_every == 0 or step % save_every == 0 or step % audit_every == 0:  # 依步數間隔或終止條件決定是否執行檢查與輸出
                last_q_fields = {  # 計算或建立最近輸出的各種體積熱源場
                    'Qlaser_W_m3':laser_result['absorption_W_m3'].copy(),  # 設定雷射熱源（Qlaser_W_m3）欄位的值
                    'Qcond_W_m3':heat_terms['conduction_W_m3'].copy(),  # 設定變數 Qcond_W_m3欄位的值
                    'Qconv_W_m3':heat_terms['convection_loss_W_m3'].copy(),  # 設定變數 Qconv_W_m3欄位的值
                    'Qrad_W_m3':heat_terms['radiation_loss_W_m3'].copy(),  # 設定變數 Qrad_W_m3欄位的值
                    'Qevap_diagnostic_W_m3':qevap.copy(),  # 設定診斷（Qevap_diagnostic_W_m3）欄位的值
                }  # 結束本段參數、容器或條件的組合
                last_powers = dict(Pconv_W=scalar(heat_terms['power_convection_loss_W']),  # 計算或建立最近記錄的熱損失功率與面積
                    Prad_W=scalar(heat_terms['power_radiation_loss_W']),  # 接續最近記錄的熱損失功率與面積的參數：執行 dict 呼叫並完成該步處理
                    Pevap_diagnostic_W=scalar(xp.sum(qevap))*dx_m**3,  # 接續最近記錄的熱損失功率與面積的參數：執行 dict 呼叫並完成該步處理
                    Aconv_rad_m2=scalar(heat_terms['exposed_surface_area_m2']))  # 接續最近記錄的熱損失功率與面積的參數：執行 dict 呼叫並完成該步處理
            audit_last_components['Qcond'] = heat_terms['conduction_W_m3'][audit_index]  # 計算或建立固定網格審計最近記錄分項（audit_last_components）的變數 Qcond欄位
            audit_last_components['Qconv'] = heat_terms['convection_loss_W_m3'][audit_index]  # 計算或建立固定網格審計最近記錄分項（audit_last_components）的變數 Qconv欄位
            audit_last_components['Qrad'] = heat_terms['radiation_loss_W_m3'][audit_index]  # 計算或建立固定網格審計最近記錄分項（audit_last_components）的變數 Qrad欄位
            audit_last_components['Qevap'] = qevap[audit_index]  # 計算或建立固定網格審計最近記錄分項（audit_last_components）的變數 Qevap欄位
            net_power = base_power - qevap  # 從淨熱源扣除蒸發損失，供體積焓積分使用
            audit_factor = audit_volume_m3 * step_dt  # 計算或建立固定網格審計（audit_factor）
            audit_acc['laser'] += laser_result['absorption_W_m3'][audit_index] * audit_factor  # 累加至固定網格各能量項的累積量的雷射模組欄位
            audit_acc['conduction'] += heat_terms['conduction_W_m3'][audit_index] * audit_factor  # 累加至固定網格各能量項的累積量的導熱（conduction）欄位
            audit_acc['convection'] += heat_terms['convection_loss_W_m3'][audit_index] * audit_factor  # 累加至固定網格各能量項的累積量的對流熱損失欄位
            audit_acc['radiation'] += heat_terms['radiation_loss_W_m3'][audit_index] * audit_factor  # 累加至固定網格各能量項的累積量的輻射熱損失欄位
            audit_acc['bottom'] += heat_terms['bottom_loss_W_m3'][audit_index] * audit_factor  # 累加至固定網格各能量項的累積量的底部邊界損失欄位
            audit_acc['net'] += net_power[audit_index] * audit_factor  # 累加至固定網格各能量項的累積量的變數 net欄位
            audit_last_qlaser = laser_result['absorption_W_m3'][audit_index]  # 計算或建立固定網格審計最近記錄雷射熱源（audit_last_qlaser）
            audit_last_qnet = net_power[audit_index]  # 計算或建立固定網格審計最近記錄淨熱源（audit_last_qnet）
            F = F_after_evaporation  # 計算或建立金屬填充率 F
            updated = phase.update_enthalpy_phase(  # 計算或建立本步焓與相態更新結果
                H, F, net_power, step_dt, ever_melted, xp)  # 接續本步焓與相態更新結果的參數：更新體積焓、溫度與相態
            H, T = updated['enthalpy_J_m3'], updated['temperature_K']  # 計算或建立體積焓 H（J/m³）、溫度 T（K）
            fL, phase_codes = updated['liquid_fraction'], updated['phase']  # 計算或建立液相率 fL、氣體、固態、共存、液態及再凝固相態代碼
            ever_melted = updated['ever_melted_mask']  # 計算或建立曾經熔化的網格標記
            melting_J, freezing_J, vaporization_J, carried_fusion_J = phase.phase_change_energy_increments(  # 計算或建立本步熔化吸收潛熱（J）、本步凝固釋放潛熱（J）、本步汽化潛熱（J）、蒸發帶出的熔化潛熱（J）
                F_before_evaporation, fraction_before,  # 接續本步熔化吸收潛熱（J）、本步凝固釋放潛熱（J）、本步汽化潛熱（J）、蒸發帶出的熔化潛熱（J）的參數：分列單步相變能量
                phase.liquid_fraction_from_temperature(T_before_evaporation, xp),  # 接續本步熔化吸收潛熱（J）、本步凝固釋放潛熱（J）、本步汽化潛熱（J）、蒸發帶出的熔化潛熱（J）的參數：分列單步相變能量
                F, phase.liquid_fraction_from_temperature(T, xp), dx_m**3, xp)  # 接續本步熔化吸收潛熱（J）、本步凝固釋放潛熱（J）、本步汽化潛熱（J）、蒸發帶出的熔化潛熱（J）的參數：分列單步相變能量
            evaporation_J = xp.sum(qevap) * dx_m**3 * step_dt  # 蒸發功率密度積分網格體積與本步時間，得到本步蒸發總損失
            phase_transfer_acc += xp.stack((  # 累加至相變與界面導熱累積能量向量
                melting_J, freezing_J, vaporization_J, evaporation_J - vaporization_J,  # 接續相變與界面導熱累積能量向量的參數：將各項合併成同一個陣列
                interface_into * step_dt, interface_out * step_dt, carried_fusion_J))  # 接續相變與界面導熱累積能量向量的參數：將各項合併成同一個陣列
            evaporation_area_factor = heat.calculate_evaporation_surface_area(F, None, xp, settings.evaporation_surface)  # 快取新幾何暴露面積，下一步依預測溫度判斷液態
            step_energy = xp.stack((  # 將雷射與各損失功率乘本步時間，建立全域能量累積增量
                laser_result['absorbed_power_W'],  # 接續本步各項能量增量的數值、運算式或資料項目
                heat_terms['power_convection_loss_W'],  # 接續本步各項能量增量的數值、運算式或資料項目
                heat_terms['power_radiation_loss_W'],  # 接續本步各項能量增量的數值、運算式或資料項目
                heat_terms['power_bottom_loss_W'],  # 接續本步各項能量增量的數值、運算式或資料項目
                xp.sum(qevap) * dx_m**3)) * step_dt  # 接續本步各項能量增量的數值、運算式或資料項目
            energy_acc += step_energy  # 累加至累積雷射、對流、輻射、底部及蒸發能量向量
            if on:  # 判斷本行條件，成立時執行下方處理
                Eincident_cumulative_J += settings.power * step_dt  # 實際積分每個時間步，保持累積吸收對照正確
            if step % max(1, settings.check_every) == 0:  # 依步數間隔或終止條件決定是否執行檢查與輸出
                finite_fields = {  # 計算或建立變數 finite_fields
                    'Qlaser': laser_result['absorption_W_m3'],  # 設定雷射熱源（Qlaser）欄位的值
                    'Qcond': heat_terms['conduction_W_m3'],  # 設定變數 Qcond欄位的值
                    'Qconv': heat_terms['convection_loss_W_m3'],  # 設定變數 Qconv欄位的值
                    'Qrad': heat_terms['radiation_loss_W_m3'],  # 設定變數 Qrad欄位的值
                    'Qevap': qevap,  # 設定變數 Qevap欄位的值
                    'base_power': base_power,  # 設定扣除蒸發前的總淨熱源欄位的值
                    'net_power': net_power,  # 設定扣除蒸發後的總淨熱源欄位的值
                    'enthalpy': H,  # 設定焓（enthalpy）欄位的值
                    'temperature': T,  # 設定溫度（temperature）欄位的值
                }  # 結束本段參數、容器或條件的組合
                for field_name, field in finite_fields.items():  # 依序處理field_name, field，逐項套用下方運算
                    bad = xp.argwhere(~xp.isfinite(field))  # 計算或建立變數 bad
                    if int(bad.shape[0]) > 0:  # 判斷本行條件，成立時執行下方處理
                        bad_index = tuple(int(v) for v in cpu_array(bad[0], xp))  # 計算或建立索引（bad_index）
                        neighborhood = tuple(  # 計算或建立變數 neighborhood
                            slice(max(0, coordinate - 1), min(size, coordinate + 2))  # 接續變數 neighborhood的參數：執行 tuple 呼叫並完成該步處理
                            for coordinate, size in zip(bad_index, H.shape)  # 依序處理coordinate, size，逐項套用下方運算
                        )  # 結束本段參數、容器或條件的組合
                        neighborhood_lines = []  # 計算或建立變數 neighborhood_lines
                        for name, values in {  # 依序處理name, values，逐項套用下方運算
                            'F': F,  # 設定金屬填充率 F欄位的值
                            'T_K': T,  # 設定變數 T_K欄位的值
                            'H_J_m3': H,  # 設定變數 H_J_m3欄位的值
                            'Qlaser_W_m3': laser_result['absorption_W_m3'],  # 設定雷射熱源（Qlaser_W_m3）欄位的值
                            'Qcond_W_m3': heat_terms['conduction_W_m3'],  # 設定變數 Qcond_W_m3欄位的值
                            'Qconv_W_m3': heat_terms['convection_loss_W_m3'],  # 設定變數 Qconv_W_m3欄位的值
                            'Qrad_W_m3': heat_terms['radiation_loss_W_m3'],  # 設定變數 Qrad_W_m3欄位的值
                            'Qevap_W_m3': qevap,  # 設定變數 Qevap_W_m3欄位的值
                            'net_power_W_m3': net_power,  # 設定淨熱源（W/m³）欄位的值
                        }.items():  # 接續本段參數、索引或數值運算
                            local_values = cpu_array(values[neighborhood], xp)  # 計算或建立變數 local_values
                            neighborhood_lines.append(  # 將本行項目加入清單尾端
                                f'{name} neighborhood={np.array2string(local_values, precision=5, suppress_small=False)}'  # 將本行項目加入清單尾端
                            )  # 結束本段參數、容器或條件的組合
                        raise FloatingPointError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
                            f'Non-finite {field_name} at step={step}, voxel={bad_index}, '  # 接續本段欄位名稱、提示訊息或報表文字
                            f'value={scalar(field[bad_index])}\n' + '\n'.join(neighborhood_lines)  # 接續本段欄位名稱、提示訊息或報表文字
                        )  # 結束本段參數、容器或條件的組合
                min_flat_index = int(scalar(xp.argmin(H)))  # 計算或建立最小索引（min_flat_index）
                min_index = tuple(int(v) for v in np.unravel_index(min_flat_index, H.shape))  # 計算或建立最小索引（min_index）
                min_enthalpy = scalar(H[min_index])  # 計算或建立最小焓（min_enthalpy）
                if min_enthalpy < -1e-3:  # 判斷本行條件，成立時執行下方處理
                    raise FloatingPointError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
                        f'Negative enthalpy at step={step}: min_H={min_enthalpy:.9e} J/m^3, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'voxel={min_index}, F={scalar(F[min_index]):.9e}, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'T={scalar(T[min_index]):.9e} K, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Qlaser={scalar(laser_result["absorption_W_m3"][min_index]):.9e} W/m^3, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Qcond={scalar(heat_terms["conduction_W_m3"][min_index]):.9e} W/m^3, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Qconv={scalar(heat_terms["convection_loss_W_m3"][min_index]):.9e} W/m^3, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Qrad={scalar(heat_terms["radiation_loss_W_m3"][min_index]):.9e} W/m^3, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Qevap={scalar(qevap[min_index]):.9e} W/m^3'  # 接續本段欄位名稱、提示訊息或報表文字
                    )  # 結束本段參數、容器或條件的組合
                max_temperature = scalar(xp.max(T))  # 計算或建立最大溫度（max_temperature）
                if max_temperature > settings.max_diagnostic_T:  # 判斷本行條件，成立時執行下方處理
                    hot_flat = int(scalar(xp.argmax(T)))  # 計算或建立變數 hot_flat
                    hot_index = tuple(int(v) for v in np.unravel_index(hot_flat, T.shape))  # 計算或建立索引（hot_index）
                    raise FloatingPointError(  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
                        f'Temperature diagnostic limit exceeded at step={step}: '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Tmax={max_temperature:.6g} K > --max-diagnostic-T={settings.max_diagnostic_T:g} K; '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'voxel={hot_index}, F={scalar(F[hot_index]):.6g}, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'H={scalar(H[hot_index]):.6e} J/m^3, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Qlaser={scalar(laser_result["absorption_W_m3"][hot_index]):.6e} W/m^3, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Qcond={scalar(heat_terms["conduction_W_m3"][hot_index]):.6e}, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Qconv={scalar(heat_terms["convection_loss_W_m3"][hot_index]):.6e}, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Qrad={scalar(heat_terms["radiation_loss_W_m3"][hot_index]):.6e}, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'Qevap={scalar(qevap[hot_index]):.6e} W/m^3, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'applied_evap_area_factor={scalar(applied_evaporation_area[hot_index]):.6e}, '  # 顯示出錯網格本步是否具有可蒸發面積
                        f'model_revision={MODEL_REVISION}, '  # 同時指出此例外來自哪個模型版本
                        f'recoil_max={scalar(recoil_pressure_max):.6e} Pa, '  # 接續本段欄位名稱、提示訊息或報表文字
                        f'keyhole_candidates={scalar(keyhole_candidate_count)}'  # 接續本段欄位名稱、提示訊息或報表文字
                    )  # 結束本段參數、容器或條件的組合
    print(f'[OUTPUT] {output_dir.resolve()}')  # 輸出本階段的數值、進度或診斷訊息


if __name__ == '__main__':  # 只有直接執行本檔時才啟動以下流程
    try:  # 嘗試執行可能失敗的載入、寫檔或運算
        run_simulation()  # 執行主模擬與指定距離能量統計
    except KeyboardInterrupt:  # 攔截本行指定的例外並採取對應處理
        print('\n[INTERRUPTED] 執行收到中斷訊號，模擬已停止。'  # 輸出本階段的數值、進度或診斷訊息
              '請以輸出目錄中已寫入的紀錄為準；這不代表已完成 10 µm 計算。', flush=True)  # 輸出本階段的數值、進度或診斷訊息
        raise SystemExit(130)  # 拋出例外並保留錯誤原因，停止使用無效設定或異常數值
    
    
