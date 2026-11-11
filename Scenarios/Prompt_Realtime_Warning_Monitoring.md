# NMC Real-Time Warning Monitoring Prompt (10-Minute Interval)

> This prompt is used to poll the NMC/CMA website every 10 minutes for currently active rainfall-related warnings covering the Chaohu region, with deduplication to avoid saving the same warning repeatedly.

---

## Prompt

```
Please write a Python script that polls the National Meteorological Center (NMC) / China Meteorological Administration (CMA) website every 10 minutes for currently active rainfall-related warnings covering the Chaohu region. When new or updated warnings are found, save them to the `10min_warnings/` folder. This script is designed to be executed every 10 minutes via an external scheduler (e.g., Windows Task Scheduler or cron).

## Target Region

- **Primary target**: Chaohu city (巢湖市), Anhui Province, China
- **Coordinates**: latitude 31.6°N, longitude 117.87°E
- **Coverage criteria**: Any warning whose stated coverage area includes at least one of the following:
  - "巢湖" (directly named)
  - "安徽中部" (central Anhui) / "安徽中南部" (south-central Anhui) / "安徽中北部" (north-central Anhui)
  - "江淮" or "江淮之间" (Jianghuai region — Chaohu sits in this area)
  - "苏皖" or "苏皖鄂" (Jiangsu-Anhui or Jiangsu-Anhui-Hubei combined warnings)
  - "长江中下游" (middle and lower Yangtze — Chaohu is in this zone)
  - "安徽全省" or "安徽大部" (all or most of Anhui)
  - "合肥" (Hefei — Chaohu is administratively under Hefei)

## Warning Types to Monitor

1. **Rainstorm warnings** (暴雨预警) — Blue / Yellow / Orange / Red
2. **Typhoon warnings** (台风预警) — when rainfall is mentioned
3. **Severe convective weather warnings** (强对流预警)
4. **Weather bulletins** (天气公报) — when heavy rain covers the Chaohu area

## Data Sources (Real-Time Warning Pages)

The script should fetch and parse the following pages in priority order:

### Primary: NMC Official Warning Page
- URL: `http://www.nmc.cn/publish/country/warning/index.html`
- This page lists all currently active national-level meteorological warnings
- Parse the HTML to extract warning entries: warning type, level, coverage area, issue time, and any detail link

### Secondary: CMA Warning Release Page
- URL: `https://www.cma.gov.cn/2011xwzx/2011sqyj/`
- CMA's official severe weather warning release page
- Contains the latest warnings issued by CMA headquarters

### Tertiary: China Weather Net Warning Page
- URL: `http://www.weather.com.cn/alarm/index.shtml`
- Alternative real-time warning feed

### Fallback: Anhui Provincial Meteorological Bureau
- URL: `https://www.ahqx.cn/` (Anhui Provincial Meteorological Bureau)
- Provincial-level warnings that may include Chaohu-specific alerts

## Request Parameters

- Use `requests` with a realistic User-Agent header (e.g., `"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"`)
- Set timeout to 15 seconds per request
- Implement retry: 3 retries with 5-second intervals on failure
- If all data sources fail in a single run, still record the attempt with a "FAILED" status (do not crash silently)

## Output Requirements

### Folder Structure

All output files are saved in the `10min_warnings/` directory (create it if it does not exist).

### File Format: Daily JSON Lines + Daily CSV

Each day generates two files plus a persistent state file:

```
10min_warnings/
  chaohu_warnings_2025-07-29.jsonl    # One JSON object per line (full detail)
  chaohu_warnings_2025-07-29.csv      # Flat table for quick inspection
  _dedup_state.json                     # Persistent deduplication state
```

### JSONL Record Structure (one line per warning entry per poll)

```json
{
  "fetch_time": "2025-07-29 14:37:05",
  "source": "NMC",
  "source_url": "http://www.nmc.cn/publish/country/warning/index.html",
  "warning_id": "202507291400-暴雨橙色-安徽中南部",
  "issue_time": "2025-07-29T14:00",
  "warning_type": "暴雨",
  "warning_level": "橙色",
  "coverage_area": "安徽中南部（含巢湖流域）",
  "predicted_rainfall": "3h 50-100mm",
  "detail_url": "http://www.nmc.cn/publish/country/warning/14xxxx.html",
  "chaohu_match_reason": "安徽中南部",
  "status": "ACTIVE",
  "is_new": true,
  "is_updated": false
}
```

### CSV Column Structure

| Column | Description | Example |
|--------|-------------|---------|
| fetch_time | System timestamp when script runs | 2025-07-29 14:37:05 |
| source | Data source name | NMC |
| warning_id | Dedup identifier (issue_time + type + level + area) | 202507291400-暴雨橙色-安徽中南部 |
| issue_time | Warning issue time from source | 2025-07-29T14:00 |
| warning_type | Type of warning | 暴雨 |
| warning_level | Level (Blue/Yellow/Orange/Red) | 橙色 |
| coverage_area | Original coverage text | 安徽中南部（含巢湖流域） |
| predicted_rainfall | Predicted rainfall text | 3h 50-100mm |
| chaohu_match_reason | Which keyword matched | 安徽中南部 |
| detail_url | Link to warning detail page | http://... |
| status | ACTIVE / EXPIRED / FAILED | ACTIVE |
| is_new | First time seeing this warning? | True |
| is_updated | Warning level/content changed since last seen? | False |

If today's files do not exist yet (first run of the day), create them with a header row (CSV). If they already exist, append new rows without rewriting the header.

### File Encoding

CSV: UTF-8 with BOM (utf-8-sig) for Excel compatibility on Windows.
JSONL: UTF-8 (no BOM).

## Deduplication Mechanism

This is the most critical component — the script runs every 10 minutes, so the same warning will appear in multiple polls. To avoid saving duplicates:

### State File: `_dedup_state.json`

Stored in the `10min_warnings/` folder. Structure:

```json
{
  "active_warnings": {
    "202507291400-暴雨橙色-安徽中南部": {
      "warning_id": "202507291400-暴雨橙色-安徽中南部",
      "first_seen": "2025-07-29 14:07:05",
      "last_seen": "2025-07-29 14:37:05",
      "warning_level": "橙色",
      "coverage_area": "安徽中南部（含巢湖流域）",
      "predicted_rainfall": "3h 50-100mm",
      "poll_count": 4
    }
  },
  "expired_warnings": {},
  "last_cleanup": "2025-07-29 14:37:05"
}
```

### Dedup Logic

1. **Build warning_id**: Combine `issue_time + warning_type + warning_level + coverage_area` into a unique identifier string
2. **On each poll**, compare fetched warnings against `active_warnings` in the state file:
   - **New warning** (`is_new: true`): warning_id not in active_warnings → save to JSONL/CSV, add to state
   - **Existing warning, no change** (`is_new: false, is_updated: false`): warning_id exists, content unchanged → update `last_seen` and `poll_count` in state, do NOT write to JSONL/CSV (or optionally write a lightweight "still active" heartbeat row)
   - **Updated warning** (`is_updated: true`): warning_id exists but level/coverage/rainfall changed → save to JSONL/CSV with `is_updated: true`, update state
3. **Expiry detection**: Warnings in `active_warnings` that are NOT found in the current poll → move to `expired_warnings` with `expired_at` timestamp, do NOT write to JSONL/CSV
4. **State cleanup**: Every 24 hours (or when `expired_warnings` exceeds 200 entries), remove entries older than 7 days from `expired_warnings`

### Warning ID Construction

```python
def build_warning_id(issue_time, warning_type, warning_level, coverage_area):
    # Normalize: remove spaces, punctuation, lowercase
    import hashlib
    raw = f"{issue_time}|{warning_type}|{warning_level}|{coverage_area}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()[:16]
```

Alternatively, use the human-readable format: `{issue_time}_{warning_type}{warning_level}_{coverage_area_truncated}`.

## Technical Requirements

1. Use `requests` with `BeautifulSoup` (bs4) for HTML parsing
2. Use the `csv` module for CSV appending (standard library, lightweight)
3. Use `json` module for JSONL writing and state file management
4. Use `datetime` module for timestamps and daily filenames
5. Implement request retry: 3 retries, 5-second intervals
6. If all data sources fail, append a row with `status: "FAILED"` and `warning_id: ""` — this makes data gaps visible
7. Print a concise log line to stdout after each run:
   ```
   [2025-07-29 14:37:05] Source: NMC | Active warnings: 3 | New: 1 | Updated: 0 | Expired: 0 | Saved to 10min_warnings/chaohu_warnings_2025-07-29.csv
   ```
8. The script should be a single-run script (fetch once, process, save, then exit). Do NOT include a `while True` loop or `time.sleep()` — the 10-minute interval is handled by the external scheduler
9. Handle HTML encoding properly (NMC pages may use GB2312/GBK or UTF-8 — detect from response headers or content)
10. Be respectful to the server: do not send requests more frequently than the 10-minute interval allows

## HTML Parsing Notes

NMC warning pages may use JavaScript rendering. If `requests` + BeautifulSoup cannot extract warning data (empty results), consider:
- Using the `agent-browser` skill (Playwright headless browser) to render JavaScript first, then extract DOM
- Checking if NMC provides a JSON API behind the warning page (inspect network requests in browser DevTools)
- As a fallback, search for the warning RSS/Atom feed if available

## Scheduling Instructions (include as comments at the top of the script)

### Windows Task Scheduler
1. Open Task Scheduler → Create Basic Task
2. Set trigger: Daily, repeat every 10 minutes for 1 day
3. Set action: "Start a program" → point to Python executable with script path as argument

### Linux / macOS crontab
```
*/10 * * * * /path/to/python /path/to/fetch_warnings_10min.py >> /path/to/10min_warnings/cron.log 2>&1
```

## Rainfall Amount Standards (GB/T 28592-2012)

For reference when parsing predicted rainfall from warning text:
- Blue: 12h ≥ 50mm / 24h 50–100mm
- Yellow: 6h ≥ 50mm / 24h 100–250mm
- Orange: 3h ≥ 50mm / 24h 100–250mm
- Red: 3h ≥ 100mm / 24h ≥ 250mm

## Notes

- NMC warning pages are primarily in Chinese — parsing logic should handle Chinese text
- Some warnings may be issued at the national level (covering multiple provinces) while others are provincial — both should be checked for Chaohu keywords
- Warning level upgrades/downgrades (e.g., Blue → Yellow → Orange) are common during active weather events — the dedup mechanism handles this via `is_updated: true`
- The `active_warnings` state file should be backed up daily (copy to `10min_warnings/_archive/dedup_state_YYYY-MM-DD.json`)
- If the NMC website changes its HTML structure, the parsing selectors will need updating — include a clear comment block identifying all CSS selectors used for easy maintenance
```
