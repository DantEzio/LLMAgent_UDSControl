# Prompt: Generate `process_events.py` — Batch Rainfall Event Processing Script

## Task Overview

Write a Python script `process_events.py` that reads hourly rainfall data from an Excel file and a list of 52 meteorological warning events (hardcoded), then for each event extracts a 72-hour rainfall window and outputs three files per event (CSV, NPY, Markdown README), plus an overall summary (CSV + Markdown).

---

## Input Data

### Input 1: Excel File — `Chaohu_Rainfall_2015-2025_OpenMeteo.xlsx`

- **Location:** Same directory as the script (`BASE_DIR`).
- **Sheet name:** `Hourly_Rainfall`
- **Total rows:** ~91,536 (hourly records from 2015-01-01 00:00 to 2025-12-31 23:00)
- **Columns (8 columns):**

| Column | Dtype | Description |
|--------|-------|-------------|
| `datetime` | datetime64 | Full timestamp (e.g., `2015-06-27 08:00:00`) |
| `date` | str | Date string `YYYY-MM-DD` |
| `time` | str | Time string `HH:MM:SS` |
| `year` | int64 | Year (2015–2025) |
| `month` | int64 | Month (1–12) |
| `day` | int64 | Day of month |
| `hour` | int64 | Hour (0–23) |
| `precipitation_mm` | int64 | Hourly precipitation in millimeters |

- **Data source:** Open-Meteo ERA5 reanalysis, 0.25° grid, coordinates lat=31.6, lon=117.87 (Chaohu region).
- **Other sheets** (`Yearly_Stats`, `Monthly_Stats`) are NOT used by this script.

### Input 2: 52 Event Definitions — Hardcoded as Python List

The 52 events come from the summary table in `中央气象台_巢湖降雨预警_2015_2025.md`, but they are **NOT read programmatically from the markdown**. Instead, they are hardcoded as a Python list of tuples inside the script.

Each event tuple has **8 fields**:

```python
(seq, year, date_str, warning_type, location, forecast_rain, source, url)
```

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `seq` | int | `1` | Sequential number 1–52 |
| `year` | int | `2015` | Year of the event |
| `date_str` | str | `"06-02"` | Month-day string (MM-DD) |
| `warning_type` | str | `"暴雨蓝色预警"` | Full warning type text (Chinese) |
| `location` | str | `"安徽中南部(含巢湖流域)"` | Coverage area |
| `forecast_rain` | str | `"局地大暴雨100-160mm"` | NMC forecast rainfall description |
| `source` | str | `"CMA"` | Data source abbreviation |
| `url` | str | `"https://www.cma.gov.cn/..."` | Original URL |

**Full 52-event list** (organized by year, 2015–2025):

```python
events = [
    # 2015 (5 events)
    (1,  2015, "06-02", "暴雨蓝色预警", "安徽中南部(含巢湖流域)", "局地大暴雨100-160mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xzytq/201506/t20150602_284084.html"),
    (2,  2015, "06-26", "暴雨蓝色预警", "安徽中部(含巢湖)", "局地大暴雨100-130mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xqxyw/201506/t20150626_286094.html"),
    (3,  2015, "06-27", "暴雨蓝色预警", "苏皖", "大到暴雨50-100mm", "央视", "https://tv.cctv.com/2015/06/27/VIDE1435409005858673.shtml"),
    (4,  2015, "06-28", "暴雨蓝色预警", "苏皖豫", "大到暴雨50-100mm", "央视", "https://tv.cctv.com/2015/06/28/VIDE1435440623080744.shtml"),
    (5,  2015, "08-19", "暴雨蓝色预警", "安徽东部(巢湖流域东部)", "大到暴雨50-100mm", "央广网", "http://m.cnr.cn/news/20150819/t20150819_519586058.html"),
    # 2016 (6 events)
    (6,  2016, "06-30", "暴雨橙色预警(2016年首个)", "鄂皖苏含巢湖", "累计200-400mm, 特大暴雨250-280mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xqxyw/201606/t20160630_315475.html"),
    (7,  2016, "07-01", "暴雨橙色预警(继续)", "苏皖鄂", "累计200-400mm, 大暴雨100-200mm", "央视", "https://tv.cctv.com/2016/07/01/VIDEWlaTTHxxQwIijyrAvAX1160701.shtml"),
    (8,  2016, "07-02", "暴雨橙色预警(连续第3天)", "安徽巢湖(点名)", "大暴雨100-240mm, 实况巢湖280-500mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xqxyw/201607/t20160702_315677.html"),
    (9,  2016, "07-03", "暴雨橙色预警(继续)", "安徽中南部", "大暴雨100-200mm", "国际在线", "https://news.cri.cn/uc-eco/20160704/6f489cea-95d7-15be-6066-3095627ef8e8.html"),
    (10, 2016, "07-04", "重大气象灾害二级应急响应", "长江中下游(巢湖大闸湖决堤)", "暴雨到大暴雨", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xqxyw/201607/t20160704_315791.html"),
    (11, 2016, "07-04", "暴雨降为蓝色预警", "江淮地区", "大雨到暴雨25-100mm", "CMA", "https://www.cma.gov.cn/2011zwxx/2011zyjgl/2011zyjxy/2011zqxyj/201607/t20160704_315863.html"),
    # 2017 (2 events)
    (12, 2017, "06-10", "暴雨黄色+强对流预警", "江苏安徽湖南", "大到暴雨50-100mm, 局地大暴雨", "看看新闻", "https://m.kankanews.com/detail/lm2XNoAmPQr"),
    (13, 2017, "06-11", "应急响应(强降雨服务)", "长江中下游(含巢湖流域)", "大到暴雨50-100mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xqxyw/201706/t20170611_421877.html"),
    # 2018 (5 events)
    (14, 2018, "07-10", "台风红色预警(玛莉亚)", "浙沪皖等9省(含巢湖方向)", "浙江特大暴雨250-350mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xqxyw/201807/t20180710_472956.html"),
    (15, 2018, "07-20", "台风+暴雨预警(安比)", "安徽大别山区", "累计250-350mm, 安徽东部大到暴雨", "CMA", "https://www.cma.gov.cn/2011xwzx/spxw/201807/t20180720_474106.html"),
    (16, 2018, "08-17", "台风蓝+暴雨黄(温比亚)", "安徽北部和大别山区", "暴雨到大暴雨100-250mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xzytq/201808/t20180817_476088.html"),
    (17, 2018, "08-18", "台风暴雨(温比亚)", "巢湖苏湾102mm(实况)", "安徽大部暴雨到大暴雨100-200mm", "中国天气网", "https://www.weather.com.cn/anhui/tqyw/08/2916271.shtml"),
    (18, 2018, "08-22", "台风应急响应(温比亚复盘)", "安徽全境", "安徽全境累计50-200mm", "CMA", "https://www.cma.gov.cn/2011xzt/2018zt/20180420/2018042011/202111/t20211103_4140717.html"),
    # 2019 (3 events)
    (19, 2019, "08-08", "台风红色预警(利奇马)", "华东沿海皖东", "浙东特大暴雨250-320mm", "CMA", "https://www.cma.gov.cn/2011xzt/2019zt/2019tf/20190808/2018070906/201908/t20190808_532246.html"),
    (20, 2019, "08-10", "台风蓝色预警(利奇马)", "安徽全省(江淮东部暴雨)", "暴雨50-100mm, 局地大暴雨100-200mm", "国家应急广播", "http://www.cneb.gov.cn/2019/08/10/ARTI1565409978917184.shtml"),
    (21, 2019, "08-14", "台风复盘(利奇马)", "安徽5.22万人受灾", "安徽平均50-100mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xzytq/201908/t20190814_533010.html"),
    # 2020 (8 events)
    (22, 2020, "06-02", "暴雨预警(连续发布第1天)", "江淮江南", "大到暴雨50-100mm, 连续40天首发", "综合", ""),
    (23, 2020, "06-10", "暴雨黄色预警", "安徽江淮之间", "大到暴雨50-100mm, 入梅后首轮", "央视", "http://ysxw.cctv.cn/article.html?item_id=3153704339766237127"),
    (24, 2020, "06-28", "暴雨预警(连续第27天)", "安徽合肥巢湖", "暴雨到大暴雨100-200mm, 第5轮强降雨", "央视", "https://tv.cctv.com/2020/06/28/VIDEY6sA93YLVawdYQUR1mOl200628.shtml"),
    (25, 2020, "07-12", "暴雨预警(连续第40天)", "长江中下游(含巢湖)", "大到暴雨50-100mm", "CMA", "http://cq.cma.gov.cn/sqxj/xwdt/sjdt/202007/t20200713_1865252.html"),
    (26, 2020, "07-17", "暴雨黄色预警", "安徽中北部", "局地大暴雨100-200mm", "中国天气网", "http://news.weather.com.cn/2020/07/3358576.shtml"),
    (27, 2020, "07-23", "暴雨预警(巢湖水位超保)", "巢湖流域", "7.24-26新一轮大到暴雨", "人民网", "https://unn.people.com.cn/n1/2020/0723/c14717-31794841.html"),
    (28, 2020, "07-26", "CMA巢湖专题(防汛解读)", "巢湖流域", "巢湖南部面雨量较大, 流域累计851mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xqxyw/202007/t20200726_559270.html"),
    (29, 2020, "09-01", "2020年汛期盘点", "全国(巢湖案例)", "巢湖流域梅雨931mm历史第一", "CMA", "http://www.scio.gov.cn/xwfb/bwxwfb/gbwfbh/qxj/202307/t20230703_721924.html"),
    # 2021 (4 events)
    (30, 2021, "07-24", "台风橙色预警(烟花)", "合肥巢湖烔炀雷雨大风", "暴雨到大暴雨100-250mm", "百度", "http://baijiahao.baidu.com/s?id=1706155583467781646"),
    (31, 2021, "07-25", "台风蓝色预警(烟花)", "安徽江淮", "江淮东部暴雨50-100mm", "国家应急广播", "http://www.cneb.gov.cn/2021/07/25/ARTI1627175843883615.shtml"),
    (32, 2021, "07-27", "台风蓝+暴雨黄(烟花双预警)", "安徽全省", "暴雨50-100mm, 局地大暴雨100-200mm", "澎湃新闻", "https://m.thepaper.cn/newsDetail_forward_13773511"),
    (33, 2021, "07-28", "暴雨黄色预警(烟花入皖)", "安徽北部", "大暴雨100-230mm", "澎湃新闻", "https://m.thepaper.cn/newsDetail_forward_13777902"),
    # 2022 (2 events)
    (34, 2022, "06-23", "暴雨蓝色预警", "苏皖鄂", "大到暴雨50-100mm", "央视", "https://tv.cctv.com/2022/06/23/VIDENJrDefdd7QehKbieSaQP220623.shtml"),
    (35, 2022, "07-05", "台风暹芭残余低压暴雨", "安徽江北", "大雨到暴雨25-100mm", "百度", "http://baijiahao.baidu.com/s?id=1737473038585473944"),
    # 2023 (2 events)
    (36, 2023, "06-17", "入梅首场强降雨(暴雨预警升级)", "合肥巢湖流域", "局部150-200mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xgzdt/202306/t20230618_5586327.html"),
    (37, 2023, "07-17", "巢湖暴雨红色预警", "巢湖烔炀黄麓", "红色标准3h>=100mm, 实况6h/150mm+", "腾讯新闻", "https://news.qq.com/rain/a/20230717A04EOM00"),
    # 2024 (7 events)
    (38, 2024, "06-19", "安徽入梅强降水预警", "江淮之间(含巢湖方向)", "暴雨50-100mm", "巢湖市政府", "https://www.chaohu.gov.cn/tszf/bmtx/11387127.html"),
    (39, 2024, "06-23", "暴雨橙色预警", "安徽南部(含巢湖)", "大暴雨100-200mm", "央视", "https://news.cctv.com/2024/06/23/ARTIBLTREJOpsfGNtqAAWi60240623.shtml"),
    (40, 2024, "06-28", "巢湖暴雨蓝色预警", "巢湖全市", "暴雨50-100mm", "腾讯新闻", "https://news.qq.com/rain/a/20240628A06N2C00"),
    (41, 2024, "07-07", "暴雨橙色预警", "安徽全省(含巢湖)", "大到暴雨50-100mm, 鲁南特大暴雨250-270mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xtpxw/202407/t20240707_6404151.html"),
    (42, 2024, "07-15", "暴雨橙色预警", "安徽北部", "暴雨到大暴雨100-250mm", "中新网", "https://www.chinanews.com.cn/sh/2024/07-15/10251735.shtml"),
    (43, 2024, "07-16", "暴雨橙色预警(继续)", "安徽北部", "特大暴雨250-300mm", "央视", "https://news.cctv.com/2024/07/16/ARTIeLZOlL2uN027YseSlqjM240716.shtml"),
    (44, 2024, "08-13", "巢湖暴雨橙色预警", "巢湖全市", "3h>=50mm(橙色标准)", "国家应急广播", "http://www.cneb.gov.cn/yjxx/csyj/20240813/t20240813_526850739.html"),
    # 2025 (8 events)
    (45, 2025, "06-07", "天气公报暴雨黄色预警", "安徽中南部(含巢湖)", "局地大暴雨100-150mm", "百度", "https://baijiahao.baidu.com/s?id=1834228217548970636"),
    (46, 2025, "06-07", "巢湖强对流黄色预警", "巢湖庙岗栏杆烔炀中垾", "短时暴雨3h>=30mm", "百度", "https://baijiahao.baidu.com/s?id=1834215224897890540"),
    (47, 2025, "06-14", "巢湖暴雨橙色预警", "巢湖柘皋镇", "3h>=50mm, 实况柘皋1h/75mm", "国家应急广播", "http://www.cneb.gov.cn/yjxx/csyj/20250614/t20250614_527211277.html"),
    (48, 2025, "07-31", "巢湖台风蓝色预警(竹节草)", "巢湖全市", "过程雨量40-80mm", "巢湖市政府", "https://www.chaohu.gov.cn/tszf/mszq/11458047.html"),
    (49, 2025, "07-31", "巢湖暴雨黄色预警", "巢湖中庙槐林坝镇", "6h>=100mm, 皖中南最大200mm", "百度", "https://baijiahao.baidu.com/s?id=1839169646217451263"),
    (50, 2025, "08-11", "巢湖暴雨蓝色预警", "巢湖夏阁庙岗苏湾", "6h>=50mm", "巢湖市政府", "https://www.chaohu.gov.cn/tszf/bmtx/11459463.html"),
    (51, 2025, "09-23", "安徽省暴雨黄色预警(桦加沙)", "合肥六安滁州", "大到暴雨50-100mm", "安徽商报", "https://weibo.com/1806503894/Q5UIHzht9"),
    (52, 2025, "09-24", "台风橙+暴雨橙双预警(桦加沙)", "安徽中部", "大暴雨100-250mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xqxyw/202509/t20250924_7353109.html"),
]
```

---

## Output Data

### Output Directory Structure

```
NMC_Events_2015_2025/
├── 00_Event_Summary.csv          ← Overall summary (CSV)
├── 00_Event_Summary.md           ← Overall summary (Markdown)
├── Event_01_2015-06-02_暴雨蓝色/
│   ├── README.md                 ← Event metadata + rainfall statistics
│   ├── Event_01_2015-06-02_暴雨蓝色_rainfall.csv   ← Full hourly rainfall data
│   └── Event_01_2015-06-02_暴雨蓝色_SWMM.npy       ← SWMM format time series
├── Event_02_.../
│   └── ...
└── ... (52 event folders total)
```

### Output File 1: `{folder_name}_rainfall.csv` (per event)

- Contains all original columns from the Excel sheet (`datetime`, `date`, `time`, `year`, `month`, `day`, `hour`, `precipitation_mm`) filtered to the 72-hour window.
- Encoding: `utf-8-sig` (for Excel compatibility).
- No index column.

### Output File 2: `{folder_name}_SWMM.npy` (per event)

- **Format:** NumPy 2D array, `np.float64`.
- **Shape:** `(N, 2)` where N = number of hourly records in the window (typically 72).
- **Column 0:** Elapsed hours from window start (0, 1, 2, ..., N-1).
- **Column 1:** Precipitation intensity in mm/hour (from `precipitation_mm` column).
- **Usage:** Direct input to SWMM (Storm Water Management Model) rainfall time series.

```python
# Construction:
elapsed_hours = np.arange(len(event_df), dtype=np.float64)
precipitation = event_df['precipitation_mm'].values.astype(np.float64)
swmm_ts = np.column_stack([elapsed_hours, precipitation])
np.save(npy_path, swmm_ts)
```

### Output File 3: `README.md` (per event)

Markdown document with three sections:

1. **事件信息 (Event Info)** — Table with: 事件序号, 预警发布时间, 预警类型, 覆盖区域, 预报雨量, 数据来源, 原始网址
2. **降雨数据摘要 (Rainfall Summary)** — Table with: 数据窗口 (72h range), 总降雨量, 最大小时雨强 (with timestamp), 降雨小时数 (count/total)
3. **分时段统计 (Segment Statistics)** — Table splitting the 72h window into three 24h segments: 预警前24h, 降雨过程24h, 预警后24h, each with 累计降雨量 and 最大雨强
4. **文件列表** — Lists the two data files with descriptions

### Output File 4: `00_Event_Summary.csv` (overall)

Columns: `seq`, `date`, `warning_type`, `location`, `total_rainfall_mm`, `max_intensity_mmh`, `rain_hours`, `folder`, `n_records`

### Output File 5: `00_Event_Summary.md` (overall)

Markdown document with:
- Total events processed count + error count
- Summary table (all 52 events in one table)
- SWMM Time Series Format explanation
- File Structure tree diagram

---

## Processing Logic

### Step 1: Load Excel Data

```python
df = pd.read_excel(EXCEL_PATH, sheet_name='Hourly_Rainfall')
df['datetime'] = pd.to_datetime(df['datetime'])
```

### Step 2: For Each Event, Extract 72-Hour Window

```
Warning time: assumed as 08:00 AM on the event date
  warning_dt = Timestamp(year=year, month=month, day=day, hour=8, minute=0)

Window definition (72 hours total):
  start_dt = warning_dt - 24 hours  (24h before warning)
  end_dt   = warning_dt + 48 hours  (24h rainfall + 24h after)  [exclusive]

Filter: df[(df['datetime'] >= start_dt) & (df['datetime'] < end_dt)]
```

### Step 3: Folder Naming Convention

```
wtype_short = warning_type with "预警" removed, parentheses replaced by "_", spaces replaced by "_"
              truncated to 30 chars max
loc_short   = location text before first "(" or "（", stripped
              truncated to 20 chars max

folder_name = "Event_{seq:02d}_{year}-{date_str}_{wtype_short}"
```

Example: `Event_03_2015-06-27_暴雨蓝色`

### Step 4: Generate Three Output Files

For each event:
1. Save CSV with `to_csv(encoding='utf-8-sig', index=False)`
2. Build and save NPY with `np.save()`
3. Build and save README.md with event metadata + rainfall statistics

### Step 5: Segment Statistics (for README.md)

Split the 72-hour window into three segments:
- `before_df`: `datetime < warning_dt` (24h before warning)
- `during_df`: `warning_dt <= datetime < warning_dt + 24h` (24h during rainfall)
- `after_df`: `datetime >= warning_dt + 24h` (24h after)

Each segment reports: `sum(precipitation_mm)` and `max(precipitation_mm)`.

### Step 6: Overall Summary

After all events, create:
- `00_Event_Summary.csv` from a list of per-event summary dicts
- `00_Event_Summary.md` with table + SWMM format explanation + file structure tree

### Error Handling

- If no data in the 72h window (e.g., date out of Excel range), print error and skip that event.
- Wrap each event processing in try/except, count successes and failures.

---

## Technical Requirements

- **Language:** Python 3.x
- **Libraries:** `pandas`, `numpy`, `os`, `sys`
- **Path handling:** Use `os.path.join()` for cross-platform compatibility
- **Encoding:** All CSV files use `utf-8-sig`; all Markdown files use `utf-8`
- **Constants:**
  ```python
  BASE_DIR = r"C:\Users\chong\Desktop\DRL_Agent_UDSRTC\Scenarios"
  EXCEL_PATH = os.path.join(BASE_DIR, "Chaohu_Rainfall_2015-2025_OpenMeteo.xlsx")
  EVENTS_DIR = os.path.join(BASE_DIR, "NMC_Events_2015_2025")
  ```
- **Progress output:** Print progress for each event with `[seq] date type: N records, total=Xmm, max=Ymm/h → folder_name`
- **Final output:** Print total success/error count and output directory path

---

## Context

This script is part of a DRL (Deep Reinforcement Learning) agent project for urban drainage system real-time control (UDSRTC). The 52 meteorological warning events cover 2015–2025 for the Chaohu (巢湖) region in Anhui Province, China. The extracted 72-hour rainfall windows serve as simulation scenarios for training the DRL agent in SWMM-based drainage control.

The warning events include: torrential rain warnings (blue/yellow/orange/red levels per GB/T 28592-2012), typhoon-related rainfall warnings, and emergency response activations issued by the National Meteorological Center (NMC) / China Meteorological Administration (CMA) that cover the Chaohu watershed.
