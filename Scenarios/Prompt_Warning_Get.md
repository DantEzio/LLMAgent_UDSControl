# NMC Rainfall Warning Data Collection Prompt

> This prompt is used to systematically collect all rainfall-related meteorological warnings issued by the National Meteorological Center (NMC) / China Meteorological Administration (CMA) covering the Chaohu region from 2015 to 2025, and generate a structured Markdown summary file along with individual event directories.

---

## Prompt

```
Please perform a systematic web search to collect all rainfall-related meteorological warnings issued by the National Meteorological Center (NMC) / China Meteorological Administration (CMA) that cover the Chaohu (巢湖) region from 2015 to 2025. Compile the results into a structured Markdown summary file and a folder of individual event directories.

## Target Region

- **Primary target**: Chaohu city (巢湖市), Anhui Province, China
- **Coordinates**: latitude 31.6°N, longitude 117.87°E
- **Coverage criteria**: Any warning whose stated coverage area includes at least one of the following:
  - "巢湖" (directly named)
  - "安徽中部" (central Anhui — Chaohu is in central Anhui)
  - "安徽中南部" (south-central Anhui)
  - "安徽中北部" (north-central Anhui)
  - "江淮" or "江淮之间" (Jianghuai region — Chaohu sits in this area)
  - "苏皖" or "苏皖鄂" (Jiangsu-Anhui or Jiangsu-Anhui-Hubei combined warnings)
  - "长江中下游" (middle and lower Yangtze — Chaohu is in this zone)
  - "安徽全省" or "安徽大部" (all or most of Anhui)
  - "合肥" (Hefei — Chaohu is administratively under Hefei)

## Warning Types to Collect

Collect the following types of warnings:
1. **Rainstorm warnings** (暴雨预警) — all levels: Blue (Ⅳ), Yellow (Ⅲ), Orange (Ⅱ), Red (Ⅰ)
2. **Typhoon warnings** (台风预警) — when the typhoon causes rainfall affecting Chaohu (include only if rainfall is mentioned)
3. **Severe convective weather warnings** (强对流预警) — when short-duration heavy rain is involved
4. **Weather bulletins** (天气公报) — when they mention heavy rain covering the Chaohu area
5. **Emergency responses** (应急响应) — CMA's meteorological disaster emergency response levels related to rainstorms
6. **Season reviews / post-event analyses** (汛期盘点/复盘) — when they include Chaohu as a case study

## Rainfall Amount Standards (GB/T 28592-2012)

Include this reference in the output file header:
- Blue warning (暴雨蓝色): 12h ≥ 50mm / 24h 50–100mm
- Yellow warning (暴雨黄色): 6h ≥ 50mm / 24h 100–250mm (heavy rainstorm)
- Orange warning (暴雨橙色): 3h ≥ 50mm / 24h 100–250mm (heavy rainstorm), locally ≥ 250mm (extraordinary)
- Red warning (暴雨红色): 3h ≥ 100mm / 24h ≥ 250mm (extraordinary rainstorm)

## Search Strategy

Search year by year (2015, 2016, ..., 2025), for each year:

1. **Search query**: Use web search with queries like:
   - `中央气象台 暴雨预警 巢湖 [year]`
   - `中国气象局 暴雨预警 安徽 [year]`
   - `CMA rainstorm warning Anhui Chaohu [year]`
   - `中央气象台 台风预警 安徽 [year]`
   - For each found warning, search for the specific date to find the original CMA page

2. **Primary data sources** (in priority order):
   - CMA official website: `cma.gov.cn` (China Meteorological Administration) — look for URLs matching pattern `cma.gov.cn/2011xwzx/...` or `cma.gov.cn/2011zwxx/...`
   - NMC official website: `nmc.cn` (National Meteorological Center)
   - CCTV news: `tv.cctv.com` or `news.cctv.com`
   - China Weather Net: `weather.com.cn`
   - National Emergency Broadcasting: `cneb.gov.cn`
   - Chaohu city government: `chaohu.gov.cn` (for local-level warnings)
   - Other credible media: The Paper (thepaper.cn), Xinhua, China News, CRI Online, CNR (cnr.cn)

3. **For each warning found, extract**:
   - **Issue date/time** (发布时间 — as precise as possible; if only date is found, note "(assumed)" for the time)
   - **Warning type and level** (预警类型 — e.g., "Rainstorm Orange Warning", "Typhoon Red Warning")
   - **Coverage area** (覆盖区域 — the original text describing which regions are covered)
   - **Predicted rainfall** (预报雨量 — extract the specific numbers from the NMC original text. If exact numbers are not available, infer the range from the warning level standard and mark it as "[Standard]" vs "[NMC Original]" for data traceability)
   - **Source** (来源 — the name of the publishing media, e.g., "CMA", "CCTV", "China Weather Net")
   - **URL** (网址 — the full link to the source page)

4. **Rainfall data labeling convention**:
   - `[NMC Original]` — Exact millimeter values extracted from the CMA/NMC original warning page
   - `[Standard]` — Range inferred from the warning level per GB/T 28592-2012
   - `[Provincial/City Station]` — Values from provincial or city-level meteorological stations
   - `[Continued Warning]` — Inferred from the previous day's NMC values when a warning is continued
   - `[CMA Review]` — Values from CMA post-event analysis reports

## Output File 1: Main Summary

Save as: `中央气象台_巢湖降雨预警_2015_2025.md`

### Structure:

```
# Summary of Rainfall Warnings for Chaohu Region by NMC/CMA (2015—2025)

> **Data sources:** National Meteorological Center (NMC) / China Meteorological Administration (CMA) official websites, CCTV news relay
> **Coverage area:** Chaohu city (including Chaohu basin, Hefei, Anhui Jianghuai region and extended coverage)
> **Warning types:** Rainstorm warnings (Blue/Yellow/Orange/Red), typhoon-rainfall warnings, severe convective weather warnings, weather bulletins
> **Compiled date:** [today's date]
> **Rainfall standard reference:** [include the GB/T 28592-2012 standards listed above]

---

## Table of Contents
1. [2015](#2015)
...
11. [2025](#2025)
12. [Summary Table](#summary-table)
13. [Statistical Overview](#statistical-overview)

---

## [Year]

[Brief paragraph: 1-3 sentences summarizing the year's rainfall pattern and major events for Chaohu]

| # | Issue Date/Time | Warning Type | Coverage Area | **Predicted Rainfall (NMC)** | Source | URL |
|:---:|------|------|------|------|------|------|
| 1 | 2015-06-02 | Rainstorm Blue | Central and southern Anhui (incl. Chaohu basin) | Heavy rain to rainstorm 25-100mm; **local heavy rainstorm 100-160mm** [NMC Original] | CMA | [link](URL) |
| ... | ... | ... | ... | ... | ... | ... |

> **[Year] summary:** [Summary: count, dominant warning level, key events, notable rainfall amounts]

---

[Repeat for each year 2015-2025]

---

## Summary Table

### All entries (sorted by year + date, with predicted rainfall)

| # | Year | Date | Warning Type | Chaohu Association | **Predicted Rainfall (core values)** | Source | URL |
|:---:|:---:|------|------|------|------|------|------|
| 1 | 2015 | 06-02 | Rainstorm Blue | Southern Anhui | Local **heavy rainstorm 100-160mm** | CMA | [link](URL) |
| ... | ... | ... | ... | ... | ... | ... | ... |

---

## Statistical Overview

### Statistics by Year

| Year | Count | Highest Warning Level | Main Causative Factor | Typical Chaohu Event | **Strongest Predicted Rainfall** |
|:---:|:---:|:---:|------|------|------|
| 2015 | 5 | Rainstorm Blue | Meiyu-front rainstorm | Late Jun sustained rain in Jiangsu-Anhui | **Heavy rainstorm 100-160mm** |
| ... | ... | ... | ... | ... | ... |

### Statistics by Predicted Rainfall Level

| Rainfall Level | Occurrences | Typical Events (Year) |
|:---|:---:|------|
| Heavy rain to rainstorm (25-100mm) | XX | ... |
| Rainstorm to heavy rainstorm (50-200mm) | XX | ... |
| Heavy rainstorm (100-250mm) | XX | ... |
| Extraordinary rainstorm (≥250mm) | XX | ... |

### Statistics by Source

| Source | Count | Percentage |
|:---|---:|---:|
| CMA/NMC official | XX | XX% |
| CCTV/Xinhua | XX | XX% |
| ... | ... | ... |

### Predicted Rainfall Data Source Legend

| Label | Meaning | Count |
|:---|------|:---:|
| [NMC Original] | Exact values from CMA/NMC original warning page | XX |
| [Standard] | Range inferred from warning level per GB/T 28592-2012 | XX |
| [Provincial/City Station] | Values from provincial/city meteorological stations | XX |
| [Continued Warning] | Inferred from previous day's NMC values | XX |
| [CMA Review] | Values from CMA post-event analysis | XX |

### Key Findings

[5-6 bullet points summarizing key findings: extreme years, top rainfall forecasts, direct Chaohu mentions, typhoon contributions, warning frequency trends, data traceability rate]
```

## Output File 2: Event Summary Files

In the `NMC_Events_2015_2025/` folder, create:

### 2a. `00_Event_Summary.md`

A markdown summary table of all events with rainfall data statistics:

```
# NMC Warning Events Summary (2015-2025)

**Total events:** XX
**Events with rainfall data:** XX (XX%)
**Time window per event:** 72 hours = 24h before + 24h rainfall + 24h after warning
**Warning time assumption:** 08:00 on event date

## All Events
| # | Date | Warning Type | Location | Total Rain (mm) | Max Intensity (mm/h) | Rain Hours | Records | Data |
|:---:|------|------|------|:---:|:---:|:---:|:---:|:---:|
| 01 | 2015-06-02 | Rainstorm Blue | Southern Anhui (incl. Chaohu basin) | 69.1 | 7.2 | 31 | 72 | ✅ |
| ... | ... | ... | ... | ... | ... | ... | ... | ... |
```

### 2b. `00_Event_Summary.csv`

Same data as above in CSV format with columns:
`seq, date, warning_type, location, total_rainfall_mm, max_intensity_mmh, rain_hours, folder, n_records`

### 2c. Individual Event Folders

For each event, create a folder named:
```
Event_[XX]_[YYYY-MM-DD]_[Warning_Type_Abbreviation]
```
Examples: `Event_01_2015-06-02_暴雨蓝色`, `Event_06_2016-06-30_暴雨橙色_2016年首个`

Each event folder contains the following files:

#### README.md
```
# Event [XX]: [YYYY-MM-DD] [Warning Type]

## Event Information
| Item | Content |
|:---|------|
| **Event number** | XX |
| **Warning issue time** | YYYY-MM-DD HH:MM |
| **Warning type** | [full warning type] |
| **Coverage area** | [coverage area text] |
| **Predicted rainfall** | [predicted rainfall] |
| **Data source** | CMA / CCTV / ... |
| **Original URL** | [source URL if available] |

## Rainfall Data Summary
| Metric | Value |
|:---|:---:|
| **Data window** | [start] ~ [end] (72 hours) |
| **Total rainfall** | XX.X mm |
| **Max hourly intensity** | XX.X mm/hr |
| **Rain hours** | XX / 72 |

## Time-Period Statistics
| Period | Time Range | Cumulative Rainfall | Max Intensity |
|:---|------|:---:|:---:|
| Pre-warning 24h | [range] | XX.X mm | XX.X mm/hr |
| Rainfall process 24h | [range] | XX.X mm | XX.X mm/hr |
| Post-warning 24h | [range] | XX.X mm | XX.X mm/hr |

## File List
- `Event_XX_..._rainfall.csv` — Hourly rainfall data
- `Event_XX_..._SWMM.npy` — SWMM format rainfall series (72h, shape=[72,2])
- `Event_XX_warnings.md` — Detailed warning records (if available)
```

#### [EventName]_rainfall.csv
72-hour hourly rainfall data extracted from the Open-Meteo ERA5 Excel file. CSV with header:
```
datetime,date,time,year,month,day,hour,precipitation_mm
```
Time window: 24h before warning time + 24h of rainfall process + 24h after = 72 rows total.
Warning time assumed as 08:00 on the event date if exact time is unknown.

#### [EventName]_SWMM.npy
NumPy array, shape=[72, 2], columns: [elapsed_hours, rainfall_intensity_mmh]. This is the SWMM (Storm Water Management Model) format rainfall input time series.

#### [EventName]_warnings.md (for early events 2015-2016, if CMA archive pages are accessible)
Detailed warning records within the rainfall time window, including:
- Time window definition: rain-before-6h + rainfall-duration + rain-after-48h
- Each warning record as a table with: issue time, issuing agency, warning level, coverage area, rainfall prediction, max hourly intensity, remarks
- Warning evolution timeline (text diagram showing level changes over time)
- Local warning supplements (provincial/city-level warnings)

## Notes

- Some early warnings (2015-2017) may have their original CMA pages archived or removed. Use CCTV/Xinhua relay reports and infer rainfall amounts from the warning level standard, marking them with the appropriate data label tag
- The "predicted rainfall" is the **forecast** value from NMC's original warning (not observed/actual rainfall). Actual observed values may be mentioned in parentheses for comparison when available
- Events beyond the rainfall data coverage period (after 2025-06-10) will have no rainfall CSV/npy files, only the README.md — mark them with "N/A" and "❌" in the summary
- Folder naming: replace spaces with underscores, keep Chinese characters for warning type abbreviations
- Each event should have a sequential number (01, 02, ..., 52) assigned in chronological order
- When a single date has multiple warnings (e.g., typhoon orange + rainstorm orange), create separate event folders for each
```
