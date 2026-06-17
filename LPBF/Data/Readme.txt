NAS Data

完整資料下載位置：

開啟 NAS Data

http://163.18.48.141:8080/share.cgi?ssid=5a0ae56e4ac64e3b9478b6fbea83d3cf

Folder Structure
LPBF_Project/
├── 1. Design/
├── 2. Slicing/
├── 3. Simulation/
├── 4. Coaxial_image/
├── 5. Global_image/
└── 6. Measured_data/

Folder Description
資料夾	中文名稱	存放內容	常見格式
1. Design	工件設計	原始工件幾何、CAD 模型及尺寸資料	.stl、.step、.stp、.iges
2. Slicing	切層與掃描路徑	雷射掃描路徑、雷射功率、掃描速度及切層設定	.cli、.slc、.csv、.gcode
3. Simulation	數值模擬	熔池、溫度場、相位、冷卻時間、熱覆蓋及表面輪廓模擬結果	.npz、.npy、.csv
4. Coaxial_image	同軸影像	與雷射光路同方向拍攝的熔池、飛濺及製程影像	.png、.jpg、.tif、.avi、.mp4
5. Global_image	全域影像	從上方或側面拍攝整個粉床，包括鋪粉後與雷射掃描後的影像	.png、.jpg、.tif、.avi、.mp4
6. Measured_data	實際量測資料	表面粗糙度、XCT、工件尺寸及其他實驗量測結果	.csv、.stl、.pdf
