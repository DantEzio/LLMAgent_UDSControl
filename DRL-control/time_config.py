"""
Shared time parameter configuration (DRL-control/time_config.py).

All simulation-time constants are defined here to avoid inconsistencies from hardcoding them
in multiple files. Referenced by:
  - step3-BCAgent-control/main_BCAgenttest.py  (control simulation)
  - results.py                                  (result plotting)
  - prepare_full_rainfall_data.py               (data preprocessing)

Time window structure (example: PRE_HOURS=6, POST_HOURS=18):
  |--- PRE (6h, no rain) ---|--- full rainfall (N h) ---|--- POST (18h, no rain) ---|
  sim_start (02:00)         rain_start (08:00)            rain_end              sim_end
"""

# Zero-rainfall lead time (hours): transition from simulation start to rainfall onset
PRE_HOURS = 6

# Zero-rainfall tail time (hours): recession from rainfall end to simulation end
# Note: this must match POST_HOURS used by results.py for plotting
POST_HOURS = 18

# Rainfall window start (24h clock) - rainfall begins at 08:00 on the event day
RAIN_START_HOUR = 8

# Simulation step (minutes) - SWMM control step
INTERVAL_MIN = 5

# Steps per hour (derived)
STEPS_PER_HOUR = 60 // INTERVAL_MIN  # 12

# Derived: number of steps in the pre / post segments
PRE_STEPS = PRE_HOURS * STEPS_PER_HOUR    # 72 steps
POST_STEPS = POST_HOURS * STEPS_PER_HOUR  # 216 steps


def compute_sim_start(event_date):
    """
    [DEPRECATED] Compute the simulation start time (datetime) from an event date.
    This function assumes "rainfall starts at 08:00 on the event day", while the real data window
    usually starts earlier (possibly 1~2 days before). New code should use
    compute_sim_start_from_readme() to parse the real data window start from README.

    Kept only for backward compatibility.

    Args:
        event_date: datetime.date or datetime.datetime, the event date.

    Returns:
        datetime.datetime: Simulation start time (event day 08:00 - PRE_HOURS).
    """
    import datetime
    rain_start = event_date.replace(hour=RAIN_START_HOUR, minute=0, second=0) \
        if hasattr(event_date, 'replace') else event_date
    # Support datetime.date (which has no hour/minute attributes)
    if not hasattr(rain_start, 'hour'):
        rain_start = datetime.datetime.combine(event_date,
                                               datetime.time(RAIN_START_HOUR, 0, 0))
    return rain_start - datetime.timedelta(hours=PRE_HOURS)


def parse_data_window_start(readme_content):
    """
    Parse the "data window" start time from README.md content.

    Format in README:
        | **data window** | 2015-06-01 12:00 ~ 2015-06-05 11:00 (96 hours) |

    Row 0 (elapsed=0) of the original *_SWMM.npy corresponds to this data window start.
    *_FULL_SWMM.npy prepends PRE_HOURS hours of zeros, so row 0 of the FULL data
    corresponds to (data window start - PRE_HOURS).

    Args:
        readme_content: Full text of the README.md file.

    Returns:
        datetime.datetime: Data window start time; None if parsing fails.
    """
    import re
    import datetime
    if not readme_content:
        return None
    # Match "data window ... YYYY-MM-DD HH:MM ~ ..."
    match = re.search(r'数据窗口.*?(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})', readme_content)
    if match:
        try:
            return datetime.datetime.strptime(match.group(1), '%Y-%m-%d %H:%M')
        except ValueError:
            return None
    return None


def compute_sim_start_from_readme(readme_content, event_date_str='', fallback_year=2020):
    """
    Compute the simulation start time from README content (the actual time of row 0 in *_FULL_SWMM.npy).

    Preferred strategy (accurate): parse the real start from the README "data window" line,
        sim_start = data window start - PRE_HOURS
        (because FULL data = PRE zeros + raw data + POST zeros, so row 0 is the PRE segment start)

    Fallback strategy (legacy, less accurate): if README has no data window information,
        sim_start = event_date 08:00 - PRE_HOURS

    Args:
        readme_content: Full README.md text (may be an empty string).
        event_date_str: Event date string 'YYYY-MM-DD' (for fallback).
        fallback_year: Default year when no date information is available.

    Returns:
        datetime.datetime: Simulation start time.
    """
    import datetime
    data_window_start = parse_data_window_start(readme_content)
    if data_window_start is not None:
        return data_window_start - datetime.timedelta(hours=PRE_HOURS)

    # Fallback: legacy logic (event_date 08:00 - PRE_HOURS)
    if event_date_str:
        try:
            center_dt = datetime.datetime.strptime(event_date_str, '%Y-%m-%d')
        except ValueError:
            center_dt = datetime.datetime(fallback_year, 7, 1)
    else:
        center_dt = datetime.datetime(fallback_year, 7, 1)
    rain_start_dt = center_dt.replace(hour=RAIN_START_HOUR, minute=0, second=0)
    return rain_start_dt - datetime.timedelta(hours=PRE_HOURS)
