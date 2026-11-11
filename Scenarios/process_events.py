"""
Process 52 NMC warning events:
1. Parse event definitions from markdown summary
2. Extract 72h rainfall windows from Excel (24h before + 24h rainfall + 24h after)
3. Create individual event folders with full data + SWMM .npy files
"""
import pandas as pd
import numpy as np
import os
import sys

BASE_DIR = r"C:\Users\chong\Desktop\DRL_Agent_UDSRTC\Scenarios"
EXCEL_PATH = os.path.join(BASE_DIR, "Chaohu_Rainfall_2015-2025_OpenMeteo.xlsx")
EVENTS_DIR = os.path.join(BASE_DIR, "NMC_Events_2015_2025")

# ============================================================
# 52 events extracted from 中央气象台_巢湖降雨预警_2015_2025.md
# Format: (seq, year, date_str, warning_type, location, forecast_rain, source, url)
# ============================================================
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
    (8,  2016, "07-02", "暴雨橙色预警(连续第3天)", "安徽巢湖(点名)", "大暴雨100-240mm, 实况巢湖280-500mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xzytq/201607/t20160702_315677.html"),
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
    (34, 2022, "06-23", "暴雨蓝色预警", "苏皖鄂", "大到暴雨50-100mm", "央视", "https://tv.cctv.cn/2022/06/23/VIDENJrDefdd7QehKbieSaQP220623.shtml"),
    (35, 2022, "07-05", "台风暹芭残余低压暴雨", "安徽江北", "大雨到暴雨25-100mm", "百度", "http://baijiahao.baidu.com/s?id=1737473038585473944"),

    # 2023 (2 events)
    (36, 2023, "06-17", "入梅首场强降雨(暴雨预警升级)", "合肥巢湖流域", "局部150-200mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xgzdt/202306/t20230618_5586327.html"),
    (37, 2023, "07-17", "巢湖暴雨红色预警", "巢湖烔炀黄麓", "红色标准3h≥100mm, 实况6h/150mm+", "腾讯新闻", "https://news.qq.com/rain/a/20230717A04EOM00"),

    # 2024 (7 events)
    (38, 2024, "06-19", "安徽入梅强降水预警", "江淮之间(含巢湖方向)", "暴雨50-100mm", "巢湖市政府", "https://www.chaohu.gov.cn/tszf/bmtx/11387127.html"),
    (39, 2024, "06-23", "暴雨橙色预警", "安徽南部(含巢湖)", "大暴雨100-200mm", "央视", "https://news.cctv.com/2024/06/23/ARTIBLTREJOpsfGNtqAAWi60240623.shtml"),
    (40, 2024, "06-28", "巢湖暴雨蓝色预警", "巢湖全市", "暴雨50-100mm", "腾讯新闻", "https://news.qq.com/rain/a/20240628A06N2C00"),
    (41, 2024, "07-07", "暴雨橙色预警", "安徽全省(含巢湖)", "大到暴雨50-100mm, 鲁南特大暴雨250-270mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xtpxw/202407/t20240707_6404151.html"),
    (42, 2024, "07-15", "暴雨橙色预警", "安徽北部", "暴雨到大暴雨100-250mm", "中新网", "https://www.chinanews.com.cn/sh/2024/07-15/10251735.shtml"),
    (43, 2024, "07-16", "暴雨橙色预警(继续)", "安徽北部", "特大暴雨250-300mm", "央视", "https://news.cctv.com/2024/07/16/ARTIeLZOlL2uN027YseSlqjM240716.shtml"),
    (44, 2024, "08-13", "巢湖暴雨橙色预警", "巢湖全市", "3h≥50mm(橙色标准)", "国家应急广播", "http://www.cneb.gov.cn/yjxx/csyj/20240813/t20240813_526850739.html"),

    # 2025 (8 events)
    (45, 2025, "06-07", "天气公报暴雨黄色预警", "安徽中南部(含巢湖)", "局地大暴雨100-150mm", "百度", "https://baijiahao.baidu.com/s?id=1834228217548970636"),
    (46, 2025, "06-07", "巢湖强对流黄色预警", "巢湖庙岗栏杆烔炀中垾", "短时暴雨3h≥30mm", "百度", "https://baijiahao.baidu.com/s?id=1834215224897890540"),
    (47, 2025, "06-14", "巢湖暴雨橙色预警", "巢湖柘皋镇", "3h≥50mm, 实况柘皋1h/75mm", "国家应急广播", "http://www.cneb.gov.cn/yjxx/csyj/20250614/t20250614_527211277.html"),
    (48, 2025, "07-31", "巢湖台风蓝色预警(竹节草)", "巢湖全市", "过程雨量40-80mm", "巢湖市政府", "https://www.chaohu.gov.cn/tszf/mszq/11458047.html"),
    (49, 2025, "07-31", "巢湖暴雨黄色预警", "巢湖中庙槐林坝镇", "6h≥100mm, 皖中南最大200mm", "百度", "https://baijiahao.baidu.com/s?id=1839169646217451263"),
    (50, 2025, "08-11", "巢湖暴雨蓝色预警", "巢湖夏阁庙岗苏湾", "6h≥50mm", "巢湖市政府", "https://www.chaohu.gov.cn/tszf/bmtx/11459463.html"),
    (51, 2025, "09-23", "安徽省暴雨黄色预警(桦加沙)", "合肥六安滁州", "大到暴雨50-100mm", "安徽商报", "https://weibo.com/1806503894/Q5UIHzht9"),
    (52, 2025, "09-24", "台风橙+暴雨橙双预警(桦加沙)", "安徽中部", "大暴雨100-250mm", "CMA", "https://www.cma.gov.cn/2011xwzx/2011xqxxw/2011xzytq/202509/t20250924_7353109.html"),
]

print(f"Total events: {len(events)}")

# Load rainfall data
print("\nLoading rainfall data...")
df = pd.read_excel(EXCEL_PATH, sheet_name='Hourly_Rainfall')
df['datetime'] = pd.to_datetime(df['datetime'])
print(f"Loaded {len(df)} hourly records from {df.datetime.min()} to {df.datetime.max()}")

# Create events root directory
os.makedirs(EVENTS_DIR, exist_ok=True)

# ============================================================
# Process each event
# ============================================================
success_count = 0
error_count = 0
event_summary = []

for seq, year, date_str, wtype, location, frain, source, url in events:
    try:
        # Parse date
        month = int(date_str.split('-')[0])
        day = int(date_str.split('-')[1])

        # Warning time: assume 08:00 AM on the event date
        warning_dt = pd.Timestamp(year=year, month=month, day=day, hour=8, minute=0)

        # 72h window: 24h before warning -> 24h rainfall -> 24h after
        start_dt = warning_dt - pd.Timedelta(hours=24)
        end_dt = warning_dt + pd.Timedelta(hours=48)  # exclusive

        # Extract data
        mask = (df['datetime'] >= start_dt) & (df['datetime'] < end_dt)
        event_df = df[mask].copy().reset_index(drop=True)

        if len(event_df) == 0:
            print(f"  [{seq:02d}] {year}-{date_str}: NO DATA in range {start_dt} to {end_dt}")
            error_count += 1
            continue

        # Create folder name
        # Clean type name for path
        wtype_short = wtype.replace("预警", "").replace("(", "_").replace(")", "").replace(" ", "_")
        if len(wtype_short) > 30:
            wtype_short = wtype_short[:30]
        loc_short = location.split("(")[0].split("（")[0].strip()
        if len(loc_short) > 20:
            loc_short = loc_short[:20]

        folder_name = f"Event_{seq:02d}_{year}-{date_str}_{wtype_short}"
        folder_path = os.path.join(EVENTS_DIR, folder_name)
        os.makedirs(folder_path, exist_ok=True)

        # ==== Save 1: Rainfall data CSV (all original columns) ====
        csv_path = os.path.join(folder_path, f"{folder_name}_rainfall.csv")
        event_df.to_csv(csv_path, index=False, encoding='utf-8-sig')

        # ==== Save 2: SWMM rainfall time series as .npy ====
        # SWMM format: [elapsed_hours, intensity_mm_per_hour]
        # Time starts from 0 at beginning of the 72h window
        elapsed_hours = np.arange(len(event_df), dtype=np.float64)
        precipitation = event_df['precipitation_mm'].values.astype(np.float64)

        # Stack into 2D array: shape (N, 2)
        swmm_ts = np.column_stack([elapsed_hours, precipitation])

        npy_path = os.path.join(folder_path, f"{folder_name}_SWMM.npy")
        np.save(npy_path, swmm_ts)

        # ==== Save 3: Event metadata markdown ====
        md_path = os.path.join(folder_path, f"README.md")
        total_rain = event_df['precipitation_mm'].sum()
        max_rain = event_df['precipitation_mm'].max()
        max_hour = event_df.loc[event_df['precipitation_mm'].idxmax(), 'datetime'] if max_rain > 0 else "N/A"
        rain_hours = (event_df['precipitation_mm'] > 0).sum()

        # Split into three 24h segments
        before_df = event_df[event_df['datetime'] < warning_dt]
        during_df = event_df[(event_df['datetime'] >= warning_dt) & (event_df['datetime'] < warning_dt + pd.Timedelta(hours=24))]
        after_df = event_df[event_df['datetime'] >= warning_dt + pd.Timedelta(hours=24)]

        md_content = f"""# Event {seq:02d}: {year}-{date_str} {wtype}

## 事件信息
| 项目 | 内容 |
|:---|------|
| **事件序号** | {seq:02d} |
| **预警发布时间** | {year}-{date_str} 08:00 (假定) |
| **预警类型** | {wtype} |
| **覆盖区域** | {location} |
| **预报雨量** | {frain} |
| **数据来源** | {source} |
| **原始网址** | {url} |

## 降雨数据摘要
| 指标 | 数值 |
|:---|:---|
| **数据窗口** | {start_dt.strftime('%Y-%m-%d %H:%M')} ~ {end_dt.strftime('%Y-%m-%d %H:%M')} (72小时) |
| **总降雨量** | {total_rain:.1f} mm |
| **最大小时雨强** | {max_rain:.1f} mm/hr (at {max_hour}) |
| **降雨小时数** | {rain_hours} / {len(event_df)} |

## 分时段统计
| 时段 | 时间范围 | 累计降雨量 | 最大雨强 |
|:---|------|:---:|:---:|
| 预警前24h | {start_dt.strftime('%m-%d %H:%M')} ~ {warning_dt.strftime('%m-%d %H:%M')} | {before_df['precipitation_mm'].sum():.1f} mm | {before_df['precipitation_mm'].max():.1f} mm/hr |
| 降雨过程24h | {warning_dt.strftime('%m-%d %H:%M')} ~ {(warning_dt + pd.Timedelta(hours=24)).strftime('%m-%d %H:%M')} | {during_df['precipitation_mm'].sum():.1f} mm | {during_df['precipitation_mm'].max():.1f} mm/hr |
| 预警后24h | {(warning_dt + pd.Timedelta(hours=24)).strftime('%m-%d %H:%M')} ~ {end_dt.strftime('%m-%d %H:%M')} | {after_df['precipitation_mm'].sum():.1f} mm | {after_df['precipitation_mm'].max():.1f} mm/hr |

## 文件列表
- `{folder_name}_rainfall.csv` — 完整降雨数据(含所有原始列)
- `{folder_name}_SWMM.npy` — SWMM格式降雨时间序列(72h, shape=[72,2]: [elapsed_hours, mm/hr])
"""
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        event_summary.append({
            'seq': seq,
            'date': f"{year}-{date_str}",
            'warning_type': wtype,
            'location': location,
            'total_rainfall_mm': round(total_rain, 1),
            'max_intensity_mmh': round(max_rain, 1),
            'rain_hours': rain_hours,
            'folder': folder_name,
            'n_records': len(event_df)
        })

        print(f"  [{seq:02d}] {year}-{date_str} {wtype}: {len(event_df)} records, "
              f"total={total_rain:.1f}mm, max={max_rain:.1f}mm/h → {folder_name}")
        success_count += 1

    except Exception as e:
        print(f"  [{seq:02d}] {year}-{date_str}: ERROR - {e}")
        error_count += 1

# ============================================================
# Generate overall summary
# ============================================================
summary_df = pd.DataFrame(event_summary)
summary_csv = os.path.join(EVENTS_DIR, "00_Event_Summary.csv")
summary_df.to_csv(summary_csv, index=False, encoding='utf-8-sig')

# Overall markdown summary
md_lines = ["# NMC Warning Events Summary (2015-2025)", ""]
md_lines.append(f"**Total events processed:** {success_count} / {len(events)}")
md_lines.append(f"**Errors:** {error_count}")
md_lines.append("")
md_lines.append("| # | Date | Warning Type | Location | Total Rain (mm) | Max Intensity (mm/h) | Rain Hours | Records |")
md_lines.append("|:---:|------|------|------|:---:|:---:|:---:|:---:|")
for s in event_summary:
    md_lines.append(f"| {s['seq']:02d} | {s['date']} | {s['warning_type']} | {s['location']} | {s['total_rainfall_mm']} | {s['max_intensity_mmh']} | {s['rain_hours']} | {s['n_records']} |")
md_lines.append("")
md_lines.append("## SWMM Time Series Format")
md_lines.append("- Each `.npy` file contains a 2D numpy array with shape `(N, 2)`")
md_lines.append("- Column 0: elapsed time in hours from window start")
md_lines.append("- Column 1: precipitation intensity in mm/hour")
md_lines.append("- Time window: 72 hours = 24h before warning + 24h rainfall + 24h after")
md_lines.append("- Warning time assumed as 08:00 on the event date unless otherwise specified")
md_lines.append("")
md_lines.append("## File Structure")
md_lines.append("```")
md_lines.append("NMC_Events_2015_2025/")
md_lines.append("├── 00_Event_Summary.csv")
md_lines.append("├── 00_Event_Summary.md")
for s in event_summary:
    md_lines.append(f"├── {s['folder']}/")
    md_lines.append(f"│   ├── README.md")
    md_lines.append(f"│   ├── {s['folder']}_rainfall.csv")
    md_lines.append(f"│   └── {s['folder']}_SWMM.npy")
md_lines.append("```")

summary_md = os.path.join(EVENTS_DIR, "00_Event_Summary.md")
with open(summary_md, 'w', encoding='utf-8') as f:
    f.write('\n'.join(md_lines))

print(f"\n{'='*60}")
print(f"DONE! {success_count} events processed, {error_count} errors")
print(f"Output directory: {EVENTS_DIR}")
print(f"Summary: {summary_csv}")
