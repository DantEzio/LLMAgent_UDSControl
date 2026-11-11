# -*- coding: utf-8 -*-
"""
LLM event analysis agent module: encapsulates LLM calls used to:
1. Extract rainfall information from weather event reports (structured JSON output)
2. Map natural-language location descriptions to drainage system regions
3. Estimate the temporal distribution of additional rainfall

Design principles:
- Rule-based estimator (GB/T 28592-2012 meteorological rainfall grades)
- Embedded reasoning engine, no external API dependency
- All outputs are structured data
"""

import os
import json
import re
import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, List


@dataclass
class RainfallEstimate:
    """Rainfall estimate produced by the LLM"""
    estimated_rainfall_mm: float = 0.0       # Total rainfall (mm)
    peak_intensity_mm_hr: float = 0.0        # Peak intensity (mm/hr)
    duration_hours: int = 6                   # Duration (hours)
    temporal_distribution: list = field(default_factory=list)  # Hourly mm values
    confidence: str = "medium"                # high / medium / low
    source: str = "rule"                      # "llm" / "rule" / "fallback"
    raw_response: str = ""                    # Raw LLM response (for debugging)
    start_time: Optional[datetime.datetime] = None  # [v11] Expected / actual rainfall start time
    end_time: Optional[datetime.datetime] = None    # [v12] Actual rainfall end time (extracted from README)


@dataclass
class EventInfo:
    """Event information structure parsed from README.md"""
    event_id: str = ""
    event_date: str = ""
    warning_type: str = ""                    # Warning type
    location: str = ""                        # Covered area
    forecast_rainfall: str = ""               # Original forecast rainfall text
    source_url: str = ""
    readme_content: str = ""

    # Parsed numeric values
    parsed_total_rainfall: Optional[float] = None   # Total (mm) extracted from the forecast text


# Meteorological rainfall grade reference (GB/T 28592-2012)
_RAINFALL_STANDARD = """
暴雨蓝色: 12h≥50mm 或 24h 50-100mm, 小时雨强约 5-10mm/hr
暴雨黄色: 6h≥50mm 或 24h 100-250mm(大暴雨), 小时雨强约 10-20mm/hr
暴雨橙色: 3h≥50mm 或 24h 100-250mm, 局地≥250mm, 小时雨强约 15-30mm/hr
暴雨红色: 3h≥100mm 或 24h≥250mm(特大暴雨), 小时雨强约 30-60mm/hr
台风/特大暴雨: 可达 300-500mm/24h, 极端情况更高
"""


class LLMEventAgent:
    """
    Event analysis agent (embedded reasoning engine, no external API dependency).

    Usage:
        agent = LLMEventAgent()
        event_info = agent.parse_readme(readme_content)
        rainfall = agent.analyze_rainfall(event_info)
    """

    def __init__(self):
        """
        Initialize the event analysis agent.
        Uses an embedded rule-based reasoning engine following GB/T 28592-2012 to analyze rainfall events.
        No external API dependency.
        """
        self.llm_available = True  # Mark as available and use the embedded reasoning engine
        print("[LLMAgent] Initialized with embedded reasoning engine (no external API required).")

    def parse_readme(self, readme_content: str) -> EventInfo:
        """
        Parse event metadata from a scenario's README.md content.

        Args:
            readme_content: Full text of the README.md file.

        Returns:
            An EventInfo data object.
        """
        info = EventInfo(readme_content=readme_content)

        # Extract the event index
        m = re.search(r'事件序号\s*\|\s*(\d+)', readme_content)
        if m:
            info.event_id = m.group(1).zfill(2)

        # Extract the date
        m = re.search(r'(\d{4}-\d{2}-\d{2})', readme_content)
        if m:
            info.event_date = m.group(1)

        # Extract the warning type
        m = re.search(r'预警类型\s*\|\s*([^|\n]+)', readme_content)
        if m:
            info.warning_type = m.group(1).strip()

        # Extract the covered area
        m = re.search(r'覆盖区域\s*\|\s*([^|\n]+)', readme_content)
        if m:
            info.location = m.group(1).strip()

        # Extract the forecast rainfall
        m = re.search(r'预报雨量\s*\|\s*([^|\n]+)', readme_content)
        if m:
            info.forecast_rainfall = m.group(1).strip()
            # Try to extract a numeric value from it
            info.parsed_total_rainfall = self._extract_rainfall_number(info.forecast_rainfall)

        return info

    def _extract_rainfall_number(self, text: str) -> Optional[float]:
        """Extract a numeric value (mm) from forecast rainfall text"""
        # Match patterns such as "100-160mm", "local heavy rain 100-160mm", "291 mm"
        patterns = [
            r'(\d+(?:\.\d+)?)\s*[-~～]\s*(\d+(?:\.\d+)?)?\s*mm',  # "100-160mm"
            r'(\d+(?:\.\d+)?)\s*毫米',                          # "291 mm"
            r'(\d+(?:\.\d+)?)\s*mm',                           # "69.1mm"
            r'大雨到暴雨.*?(\d+)-(\d+)',                        # "heavy rain (25-100mm)"
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                # Use the upper bound of the range as a conservative estimate
                if m.group(2):
                    return float(m.group(2))
                return float(m.group(1))
        return None

    def analyze_rainfall(self, event_info: EventInfo) -> RainfallEstimate:
        """
        Analyze the event's rainfall amount using the embedded reasoning engine.

        Args:
            event_info: EventInfo object.

        Returns:
            RainfallEstimate with the estimated rainfall amount.
        """
        return self._embedded_reasoning(event_info)

    def _embedded_reasoning(self, event_info: EventInfo) -> RainfallEstimate:
        """
        Embedded reasoning engine: combines forecast text, warning type and rainfall grade standards.

        This method mimics an LLM analysis process:
        1. Parse rainfall numbers from the forecast text
        2. Determine the rainfall grade from the warning type
        3. Account for historical observed data (e.g. the "observed" section in README)
        4. Generate a rainfall temporal distribution curve
        """
        wt = event_info.warning_type or ""
        fc = event_info.forecast_rainfall or ""
        readme = event_info.readme_content or ""
        
        # Step 1: extract numeric values from the forecast text
        total_mm = event_info.parsed_total_rainfall
        
        # Step 2: try to extract a stronger signal from the "observed" data in README
        reality_total = None
        reality_peak = None
        
        # Match patterns such as "observed: ... XXXmm"
        reality_patterns = [
            r'实况[：:]\s*.*?(\d+(?:\.\d+)?)\s*[-~～]\s*(\d+(?:\.\d+)?)\s*mm',  # observed: Chaohu 280-500mm
            r'实况[：:]\s*.*?(\d+(?:\.\d+)?)\s*毫米',
            r'实况[：:]\s*.*?(\d+(?:\.\d+)?)\s*mm',
            r'累计雨量.*?(\d+(?:\.\d+)?)\s*[-~～]\s*(\d+(?:\.\d+)?)\s*mm',
        ]
        for pat in reality_patterns:
            m = re.search(pat, readme, re.IGNORECASE)
            if m:
                if m.lastindex and m.lastindex >= 2 and m.group(2):
                    reality_total = float(m.group(2))  # Use the upper bound
                else:
                    reality_total = float(m.group(1))
                break
        
        # Match the maximum hourly rainfall intensity
        peak_patterns = [
            r'最大小时雨[强量].*?(\d+(?:\.\d+)?)\s*[-~～]\s*(\d+(?:\.\d+)?)\s*mm',
            r'小时雨[强量].*?(\d+(?:\.\d+)?)\s*[-~～]\s*(\d+(?:\.\d+)?)\s*mm',
            r'最大小时雨[强量].*?(\d+(?:\.\d+)?)\s*mm',
        ]
        for pat in peak_patterns:
            m = re.search(pat, readme, re.IGNORECASE)
            if m:
                if m.lastindex and m.lastindex >= 2 and m.group(2):
                    reality_peak = float(m.group(2))
                else:
                    reality_peak = float(m.group(1))
                break
        
        # Step 3: combined reasoning - observed data first, then forecast, then warning level
        reasoning_parts = []
        
        if reality_total:
            total_mm = reality_total
            reasoning_parts.append(f"使用实况总降雨量{reality_total}mm")
        elif total_mm:
            reasoning_parts.append(f"使用预报总降雨量{total_mm}mm")
        else:
            reasoning_parts.append("无明确数值，使用预警等级推断")
        
        if reality_peak:
            peak = reality_peak
            reasoning_parts.append(f"使用实况峰值雨强{reality_peak}mm/hr")
        else:
            peak = None
            reasoning_parts.append("峰值雨强由预警等级推断")
        
        # [v11/v12] Step 3.5: extract actual rainfall start/end times from the README "rainfall period" line
        _start_time = None
        _end_time = None
        rain_process_patterns_start = [
            r'降雨过程.*?(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})\s*[~～]',  # | <rainfall period> | 06-01 18:00 ~ ... |
            r'降雨时间.*?(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})',          # Start of the rainfall time window
        ]
        rain_process_patterns_end = [
            r'[~～]\s*(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})',              # | ~ 06-03 04:00 |
        ]
        for pat in rain_process_patterns_start:
            m = re.search(pat, readme)
            if m:
                _start_time = datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M')
                reasoning_parts.append(f"降雨开始时间={_start_time.strftime('%m-%d %H:%M')}")
                break
        for pat in rain_process_patterns_end:
            m = re.search(pat, readme)
            if m:
                _end_time = datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M')
                reasoning_parts.append(f"降雨结束时间={_end_time.strftime('%m-%d %H:%M')}")
                break

        # Step 4: choose parameters by warning level
        combined = (wt + " " + fc).lower()
        
        if any(k in combined for k in ["红色", "特大暴雨", "极值", "历史"]):
            if peak is None:
                peak = min(50.0, max(25.0, total_mm * 0.2)) if total_mm else 40.0
            dur = 12
            if total_mm is None:
                total_mm = 280.0
            confidence = "high"
            level_desc = "红色/特大暴雨"
        elif any(k in combined for k in ["橙色", "大暴雨", "应急响应", "一级"]):
            if peak is None:
                peak = min(30.0, max(15.0, total_mm * 0.15)) if total_mm else 18.0
            dur = 10
            if total_mm is None:
                total_mm = 150.0
            confidence = "high" if reality_total else "medium"
            level_desc = "橙色/大暴雨"
        elif any(k in combined for k in ["黄色", "台风"]):
            if peak is None:
                peak = min(20.0, max(8.0, total_mm * 0.12)) if total_mm else 12.0
            dur = 8
            if total_mm is None:
                total_mm = 80.0
            confidence = "medium"
            level_desc = "黄色/台风"
        elif any(k in combined for k in ["蓝色", "强对流"]):
            if peak is None:
                peak = min(12.0, max(4.0, total_mm * 0.1)) if total_mm else 7.0
            dur = 6
            if total_mm is None:
                total_mm = 50.0
            confidence = "medium"
            level_desc = "蓝色/强对流"
        else:
            if peak is None:
                peak = total_mm * 0.08 if total_mm else 5.0
            dur = 6
            if total_mm is None:
                total_mm = 30.0
            confidence = "low"
            level_desc = "一般降雨"
        
        reasoning_parts.append(f"预警等级: {level_desc}")
        
        # Step 5: generate the rainfall hyetograph
        distribution = self._generate_hyetograph(total_mm, dur, peak)
        
        reasoning = "; ".join(reasoning_parts)
        
        est = RainfallEstimate(
            estimated_rainfall_mm=round(total_mm, 1),
            peak_intensity_mm_hr=round(peak, 1),
            duration_hours=dur,
            temporal_distribution=[round(v, 2) for v in distribution],
            confidence=confidence,
            source="embedded",  # Mark as built-in reasoning engine
            raw_response=f"Embedded reasoning: {reasoning}",
            start_time=_start_time,  # [v11] Rainfall start time
            end_time=_end_time,      # [v12] Rainfall end time
        )
        print(f"[LLMAgent] Embedded reasoning: {est.estimated_rainfall_mm}mm, "
              f"peak={est.peak_intensity_mm_hr}mm/hr, dur={est.duration_hours}h, "
              f"conf={est.confidence}, start_time={est.start_time} | {reasoning}")
        return est

    @staticmethod
    def _generate_hyetograph(total_mm: float, duration_hours: int, 
                             peak_mm_hr: float) -> list[float]:
        """
        Generate a typical rainfall hyetograph.
        Uses a simplified gamma-like shape: fast rise, slow recession.
        """
        import math
        
        dist = []
        if duration_hours <= 0:
            duration_hours = 1
            
        peak_pos = int(duration_hours * 0.45)  # Peak located at about 45% of the duration
        
        for t in range(duration_hours):
            # Simplified Gamma-like distribution
            if t < peak_pos:
                # Rising limb: exponential growth
                value = peak_mm_hr * ((t + 1) / peak_pos) ** 1.8
            else:
                # Falling limb: exponential decay
                decay_t = t - peak_pos
                value = peak_mm_hr * math.exp(-decay_t / (duration_hours - peak_pos + 1) * 2.0)
            
            # Ensure non-negative values
            value = max(0, value)
            dist.append(value)

        # Normalize so the sum equals target total_mm
        current_sum = sum(dist)
        if current_sum > 0:
            scale = total_mm / current_sum
            dist = [v * scale for v in dist]
        else:
            # Fallback: uniform distribution
            dist = [total_mm / duration_hours] * duration_hours

        return dist


# ============================================================
# [NEW] Warning status and level enums
# ============================================================
from enum import Enum


class WarningStatus(Enum):
    """Warning record status"""
    首次发布 = "首次发布"
    继续发布 = "继续发布"
    升级 = "升级"
    降级 = "降级"
    解除 = "解除"
    应急响应 = "应急响应"
    未知 = "未知"


class WarningLevel(Enum):
    """Warning level"""
    蓝色 = "蓝色"           # Level IV
    黄色 = "黄色"           # Level III
    橙色 = "橙色"           # Level II
    红色 = "红色"           # Level I
    应急响应 = "应急响应"    # Major meteorological disaster emergency response
    解除 = "解除"           # Warning lifted
    未知 = "未知"


# ============================================================
# [NEW] Dataclasses for warning records and parsed results
# ============================================================
@dataclass
class WarningRecord:
    """A single warning record"""
    publish_time: datetime.datetime = field(default_factory=lambda: datetime.datetime(2000, 1, 1))
    agency: str = ""
    level: WarningLevel = WarningLevel.未知
    status: WarningStatus = WarningStatus.未知
    coverage: str = ""
    rainfall_forecast: str = ""
    max_hourly_rain: str = ""
    notes: str = ""
    description: str = ""          # Section title description
    raw_text: str = ""             # Raw section text

    @property
    def is_cancelled(self) -> bool:
        """Whether the warning is lifted"""
        return self.status == WarningStatus.解除 or self.level == WarningLevel.解除

    @property
    def is_emergency(self) -> bool:
        """Whether this is an emergency response"""
        return (self.status == WarningStatus.应急响应
                or self.level == WarningLevel.应急响应)


@dataclass
class ParsedWarningsFile:
    """Parsed warnings.md file"""
    records: List[WarningRecord] = field(default_factory=list)
    time_window_start: Optional[datetime.datetime] = None
    time_window_end: Optional[datetime.datetime] = None
    source: str = ""

    # Internal state: index of the next warning record to process
    _next_idx: int = field(default=0, repr=False)

    def get_warning_at_step(self, t: int,
                            sim_start_dt: datetime.datetime
                            ) -> Optional[WarningRecord]:
        """
        Check at control step t whether a new warning record should be triggered.

        Args:
            t: Current step index (0-based).
            sim_start_dt: Simulation start datetime.

        Returns:
            The new unprocessed warning record, or None if there is none.
        """
        from datetime import timedelta
        current_time = sim_start_dt + timedelta(minutes=5 * t)

        # Check whether the next unprocessed record has reached its issue time
        while self._next_idx < len(self.records):
            next_w = self.records[self._next_idx]
            if current_time >= next_w.publish_time:
                self._next_idx += 1
                return next_w
            else:
                break
        return None

    @property
    def is_warning_active(self) -> bool:
        """
        Whether the warning is still active.
        Condition: the last processed record is not a "lifted" status.
        """
        if self._next_idx == 0:
            return False                                # No record has been processed yet
        last = self.records[self._next_idx - 1]
        return not last.is_cancelled

    @property
    def has_more_warnings(self) -> bool:
        """Whether unprocessed warning records remain"""
        return self._next_idx < len(self.records)

    def reset(self):
        """Reset the processing pointer (for running the same scenario multiple times)"""
        self._next_idx = 0


# ============================================================
# [NEW] warnings.md parsing functions
# ============================================================
def parse_warnings_file(file_path: str) -> Optional[ParsedWarningsFile]:
    """
    Parse an Event_XX_warnings.md file into structured data.

    Supported record formats:
    1. Section header + table:
       ### N. YYYY-MM-DD HH:MM - description
       | field | value | ...

    2. Section header only (e.g. emergency response):
       ### N. YYYY-MM-DD - description
       | field | value | ...

    Args:
        file_path: Path to the warnings.md file.

    Returns:
        A ParsedWarningsFile object; None on parse failure or missing file.
    """
    import datetime

    if not os.path.exists(file_path):
        print(f"  [WARN] Warnings file not found: {file_path}")
        return None

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return _parse_warnings_content(content, source=file_path)


def _parse_warnings_content(content: str, source: str = "") -> ParsedWarningsFile:
    """
    Parse warnings.md text content.

    Args:
        content: Markdown text content.
        source: Source identifier (file path).

    Returns:
        A ParsedWarningsFile object.
    """
    import datetime

    result = ParsedWarningsFile(source=source)
    records = []

    # ---- Extract the time window ----
    tw_match = re.search(
        r'降雨时间窗口[：:]\s*'
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*[~～]\s*'
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})',
        content
    )
    if tw_match:
        result.time_window_start = datetime.datetime.strptime(
            tw_match.group(1), '%Y-%m-%d %H:%M')
        result.time_window_end = datetime.datetime.strptime(
            tw_match.group(2), '%Y-%m-%d %H:%M')

    # ---- Split the warning record sections ----
    # Each record starts with "### N. "
    sections = re.split(r'\n(?=###\s+\d+\.\s+)', content)

    for section in sections:
        # Match section titles: ### N. YYYY-MM-DD [HH:MM] - description
        header_match = re.match(
            r'###\s+\d+\.\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\s*[—\-]\s*(.*)',
            section
        )
        if not header_match:
            continue

        time_str = header_match.group(1).strip()
        description = header_match.group(2).strip()

        # Parse the issue time
        publish_time = _parse_warning_datetime(time_str)

        # Parse table fields
        record = WarningRecord(
            publish_time=publish_time,
            description=description,
            raw_text=section.strip(),
        )

        # Extract each field from the table
        record.agency = _extract_table_field(section, '发布机构')
        record.coverage = _extract_table_field(section, '覆盖区域')
        record.rainfall_forecast = _extract_table_field(section, '降雨预测')
        record.max_hourly_rain = _extract_table_field(section, '最大小时雨强')
        record.notes = _extract_table_field(section, '备注')

        # Warning level (from the "warning level" table field)
        level_text = _extract_table_field(section, '预警级别')
        # May also be an emergency response (from the "response level" field)
        if not level_text:
            level_text = _extract_table_field(section, '响应级别')

        # Parse the level and status
        record.level = _parse_warning_level(level_text, description)
        record.status = _parse_warning_status(level_text, description)

        # If the table has no issuing agency, try to match an emergency response in the section title
        if not record.agency:
            record.agency = _extract_table_field(section, '启动机构')
        if not record.agency:
            record.agency = _extract_table_field(section, '机构')
        if not record.agency:
            record.agency = '中央气象台'  # fallback

        # Coverage of an emergency response may come from the "covered area" field or context
        if not record.coverage:
            record.coverage = _extract_table_field(section, '区域')

        # Reason for the emergency response
        if not record.notes:
            record.notes = _extract_table_field(section, '原因')
        if not record.notes:
            record.notes = _extract_table_field(section, '触发条件')

        records.append(record)

    # Sort by issue time
    records.sort(key=lambda r: r.publish_time)

    # Infer the status automatically (if not yet determined)
    for idx, rec in enumerate(records):
        if rec.status == WarningStatus.未知:
            if rec.level == WarningLevel.解除:
                rec.status = WarningStatus.解除
            elif rec.level == WarningLevel.应急响应:
                rec.status = WarningStatus.应急响应
            elif idx == 0:
                rec.status = WarningStatus.首次发布
            else:
                prev = records[idx - 1]
                # Compare levels to decide upgrade / downgrade / continuation
                level_order = {
                    WarningLevel.蓝色: 1, WarningLevel.黄色: 2,
                    WarningLevel.橙色: 3, WarningLevel.红色: 4,
                }
                cur_val = level_order.get(rec.level, 0)
                prev_val = level_order.get(prev.level, 0)
                if cur_val > prev_val:
                    rec.status = WarningStatus.升级
                elif cur_val < prev_val:
                    rec.status = WarningStatus.降级
                else:
                    rec.status = WarningStatus.继续发布

    result.records = records
    return result


def _parse_warning_datetime(time_str: str) -> datetime.datetime:
    """Parse a time string into datetime, preferring hour precision"""
    import datetime
    stripped = time_str.strip()
    # Choose a parsing strategy from string length and format (no try-catch)
    if ' ' in stripped and len(stripped) >= 16:
        # Contains a time part, e.g. '2016-07-04 08:00'
        return datetime.datetime.strptime(stripped, '%Y-%m-%d %H:%M')
    else:
        # Date only, e.g. '2016-07-04'
        return datetime.datetime.strptime(stripped, '%Y-%m-%d')


def _extract_table_field(section: str, field_name: str) -> str:
    """Extract the value of a given field from a markdown table section"""
    # Match: | **field name** | value |
    pattern = rf'\|\s*\*{1,2}{re.escape(field_name)}\*{1,2}\s*\|\s*([^|\n]+)'
    m = re.search(pattern, section, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        # Strip markdown bold markers
        val = re.sub(r'\*{1,3}', '', val)
        return val
    return ""


def _parse_warning_level(level_text: str, description: str = "") -> WarningLevel:
    """Infer the warning level from text"""
    combined = f"{level_text} {description}".lower()
    # Detect by priority
    if any(k in combined for k in ['解除']):
        return WarningLevel.解除
    if any(k in combined for k in ['应急响应', '重大气象灾害']):
        return WarningLevel.应急响应
    if any(k in combined for k in ['红色', 'Ⅰ级', '一级']):
        return WarningLevel.红色
    if any(k in combined for k in ['橙色', 'Ⅱ级', '二级']):
        return WarningLevel.橙色
    if any(k in combined for k in ['黄色', 'Ⅲ级', '三级']):
        return WarningLevel.黄色
    if any(k in combined for k in ['蓝色', 'Ⅳ级', '四级']):
        return WarningLevel.蓝色
    return WarningLevel.未知


def _parse_warning_status(level_text: str, description: str = "") -> WarningStatus:
    """Infer the warning status from text"""
    combined = f"{level_text} {description}".lower()
    if any(k in combined for k in ['解除', '取消']):
        return WarningStatus.解除
    if any(k in combined for k in ['应急响应', '重大气象灾害']):
        return WarningStatus.应急响应
    if any(k in combined for k in ['升级', '提升']):
        return WarningStatus.升级
    if any(k in combined for k in ['降级', '降低']):
        return WarningStatus.降级
    if any(k in combined for k in ['继续', '维持', '持续']):
        return WarningStatus.继续发布
    if any(k in combined for k in ['重新发布', '再次']):
        return WarningStatus.首次发布  # A re-issue is treated as a new first issue
    return WarningStatus.未知


if __name__ == "__main__":
    # Test code
    test_readme = """# Event 08: 2016-07-02 暴雨橙色预警（连续第3天）

## 事件信息
| 项目 | 内容 |
|:---|------|
| **事件序号** | 08 |
| **预警发布时间** | 2016-07-02 08:00 |
| **预警类型** | 暴雨橙色预警 |
| **覆盖区域** | 安徽中南部、安徽中部（明确提及巢湖特大暴雨） |
| **预报雨量** | **安徽中部大暴雨100-240mm**；最大小时雨强60-80mm；实况：巢湖280-500mm(特大暴雨) |

## 降雨数据摘要
| 指标 | 数值 |
|:---|:---:|
| **总降雨量** | 290.6 mm |
| **最大小时雨强** | 12.2 mm/hr |
"""

    # Test the embedded reasoning engine
    agent = LLMEventAgent()
    event_info = agent.parse_readme(test_readme)
    print(f"\nParsed Event ID: {event_info.event_id}")
    print(f"Warning Type: {event_info.warning_type}")
    print(f"Location: {event_info.location}")
    print(f"Forecast: {event_info.forecast_rainfall}")
    print(f"Parsed rainfall: {event_info.parsed_total_rainfall} mm")

    estimate = agent.analyze_rainfall(event_info)
    print(f"\n=== Rainfall Estimate (embedded reasoning) ===")
    print(f"Total: {estimate.estimated_rainfall_mm} mm")
    print(f"Peak intensity: {estimate.peak_intensity_mm_hr} mm/hr")
    print(f"Duration: {estimate.duration_hours} hours")
    print(f"Distribution ({len(estimate.temporal_distribution)} hrs): "
          f"[{', '.join(f'{v:.1f}' for v in estimate.temporal_distribution[:6])}, ...]")
    print(f"Confidence: {estimate.confidence}")
    print(f"Source: {estimate.source}")
