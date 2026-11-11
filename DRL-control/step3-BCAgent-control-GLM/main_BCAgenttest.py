"""AgenticAI-BC main simulation script - step 3 of the workflow (core method).

Purpose
-------
Adds "LLM event-driven adjustment" on top of the rule controller (BC, see step1-BC-control):
BC produces a base action at every control step; when a weather warning (warnings.md) or
the realtime state triggers, an LLM applies a one-way relaxation to the base action
(only switching pumps from off to on) to produce the final command.
If no trigger occurs or validation fails, the code falls back to the pure rule action.

Data flow
---------
Inputs:
    Scenarios/NMC_Events_2015_2025/<event>/<event>_FULL_SWMM.npy   rainfall series
    Scenarios/NMC_Events_2015_2025/<event>/README.md                event start/end times
    Scenarios/NMC_Events_2015_2025/<event>/Event_XX_warnings.md     weather warning records
    DRL-control/SWMM_control/_tem_control/control0/chaohu.inp       drainage network model
Outputs:
    results/bc_agent_results_<event>.npy in this directory (closed-loop results with LLM decision traces)
    reports/*.html in this directory (interactive per-event reports)

Variants
--------
step3-BCAgent-control / -GLM / -Kimi / -MiniMax are the same code with different LLM backends;
only the "LLM configuration" block of this file differs (model / base_url / api_key).
The copies under step4-uncertainty are used for uncertainty experiments
(synonym replacement / state perturbation).

Usage
-----
    python DRL-control/step3-BCAgent-control/main_BCAgenttest.py
"""

import sys
import os
_this_dir = os.path.dirname(os.path.abspath(__file__))       # step3-BCAgent-control/
_parent_dir = os.path.dirname(_this_dir)                       # DRL-control/
_grandparent_dir = os.path.dirname(_parent_dir)                # DRL_Agent_UDSRTC/
sys.path.insert(0, _parent_dir)
sys.path.insert(0, _grandparent_dir)

import numpy as np
import pandas as pd
from SWMM_control import SWMM_ENV_control as SWMM_ENV_control
import datetime
import matplotlib.pyplot as plt
from joblib import Parallel, delayed
from swmm_api import read_out_file
from swmm_api.input_file import read_inp_file
from swmm_api.input_file.sections.others import TimeseriesData
from swmm_api.input_file.section_labels import TIMESERIES

from pyswmm import Nodes, Links, RainGages, Simulation

import json
import yaml
import glob
import re

# [NEW] Import the shared time configuration (DRL-control/time_config.py)
# _parent_dir (DRL-control/) is already added to sys.path at the top of this file
from time_config import PRE_HOURS, POST_HOURS, INTERVAL_MIN, compute_sim_start_from_readme

# ============================================================
# [NEW] Event-driven adjustment module
# ============================================================
from topology_mapper import DrainageTopologyMapper, quick_map
from llm_event_agent import (LLMEventAgent, EventInfo, RainfallEstimate,
                              WarningStatus, WarningLevel, WarningRecord,
                              ParsedWarningsFile, parse_warnings_file)
from llm_action_advisor import LLMActionAdvisor, LLMAdjustmentResult

# === Global switch: enable LLM event-driven adjustment ===
# Set to False to fall back to pure BC rule control (backward compatible)
ENABLE_LLM_ADJUSTMENT = True


# ============================================================
# [v5] LLM analysis cache data structure
# ============================================================
from dataclasses import dataclass, field as dc_field
from typing import List, Optional, Dict, Any

@dataclass
class CachedLLMAnalysis:
    """Cached result of a full LLM analysis (reused across steps) - core data structure of the v5 workflow"""
    # Input information
    event_info: Any = None                        # EventInfo from llm_event_agent
    rainfall_est: Any = None                      # RainfallEstimate from llm_event_agent
    swmm_impact: Any = None                       # [SWMM estimation removed] Always None; field kept for compatibility
    topo_summary: str = ""                        # Topology summary string
    realtime_state_at_analysis: dict = None       # SWMM realtime state at analysis time

    # LLM output
    llm_adjusted_action: List[int] = dc_field(default_factory=list)   # Action vector suggested by the LLM
    llm_reasoning: str = ""                      # LLM reasoning

    # Metadata
    analysis_step: int = 0                        # Simulation step at which the analysis was performed
    expected_rain_time: Any = None                # Expected rainfall start time (datetime or None)
    expected_rain_end_time: Any = None            # [v12] Actual rainfall end time (datetime or None)
    analysis_timestamp: Any = None               # Simulation time at which the analysis was performed (datetime)


def _extract_expected_rain_time(rainfall_est, readme_text):
    """
    [v11] Extract the expected rainfall start time from the rainfall estimate or README text.

    Multi-level fallback (highest priority first):
      1. RainfallEstimate.start_time (parsed by llm_event_agent from the "rainfall period" line)
      2. Actual start time from the README "rainfall period" line
      3. Issue time of the first warning in README
      4. Legacy fallback: event date string (least accurate, day resolution only)
    """
    # Priority 1: RainfallEstimate.start_time (most accurate)
    if rainfall_est is not None and getattr(rainfall_est, 'start_time', None) is not None:
        return rainfall_est.start_time

    # Priority 2 [NEW]: extract the actual rainfall start from the README "rainfall period" line
    #     Match format: "| <rainfall period> | 2015-06-01 18:00 ~ 2015-06-03 04:00 |"
    if readme_text:
        rain_process_match = re.search(
            r'降雨过程.*?(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})\s*[~～]',
            readme_text,
        )
        if rain_process_match:
            return datetime.datetime.strptime(rain_process_match.group(1), '%Y-%m-%d %H:%M')

    # Priority 3 [NEW]: extract the first warning time from the README issue time
    #     Match format: "| **issue time** | 2015-06-01 18:00 |"
    if readme_text:
        pub_time_match = re.search(
            r'发布时间.*?(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})',
            readme_text,
        )
        if pub_time_match:
            year, mon, day, hour, minute = (
                int(pub_time_match.group(i)) for i in range(1, 6)
            )
            return datetime.datetime(year, mon, day, hour, minute)

    # Priority 4 (legacy fallback): event date string -> 00:00 that day (least accurate)
    if readme_text:
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', readme_text)
        if date_match:
            return datetime.datetime.strptime(date_match.group(1), '%Y-%m-%d')

    return None


def _extract_rainfall_end_time(rainfall_est, readme_text):
    """
    [v12] Extract the actual rainfall end time from the rainfall estimate or README text.

    Multi-level fallback (highest priority first):
      1. RainfallEstimate.end_time (llm_event_agent v12 parses the "rainfall period" line)
      2. End time from the README "rainfall period" line (the time after ~)
      3. Fallback: expected_rain_time + duration_hours * 2 (conservative scaling)
      4. Final fallback: None
    """
    # Priority 1: RainfallEstimate.end_time (most accurate)
    if rainfall_est is not None and getattr(rainfall_est, 'end_time', None) is not None:
        return rainfall_est.end_time

    # Priority 2: end time from the README "rainfall period" line
    #     Match format: "| <rainfall period> | 2015-06-01 18:00 ~ 2015-06-03 04:00 |"
    if readme_text:
        end_match = re.search(
            r'[~～]\s*(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})',
            readme_text,
        )
        if end_match:
            return datetime.datetime.strptime(end_match.group(1), '%Y-%m-%d %H:%M')

    # Priority 3: fallback - start_time + duration * 2 (conservative estimate)
    if rainfall_est is not None and getattr(rainfall_est, 'start_time', None) is not None:
        dur = getattr(rainfall_est, 'duration_hours', 12)
        return rainfall_est.start_time + datetime.timedelta(hours=dur * 2)

    return None





def _read_current_rainfall(observation, step, rain_array_2d):
    """Read the current actual rainfall intensity (mm/hr) from the observation vector or rainfall array"""
    # Prefer rain_array_2d (already scaled by 10, must be scaled back)
    if rain_array_2d is not None and step < len(rain_array_2d):
        return float(rain_array_2d[step][1]) / 10.0
    return 0.0


# ============================================================
# BC rule controller (from step1-BC-control/main_BCtest.py)
# Water-level-threshold rule control for 7 pump stations
# ============================================================
def level_rule(level, pre_action, stdlevel):
    """Rule evaluation for a single pump station.

    Args:
        level: Current water level.
        pre_action: Previous action (0=off, 1=on).
        stdlevel: [high threshold, low threshold].
    Returns:
        cc_a: Current action (0=off, 1=on).
    """
    cc_a = pre_action
    if level >= stdlevel[0]:
        cc_a = 1
    else:
        if level >= stdlevel[1]:
            if pre_action == 0:
                cc_a = 0
            else:
                cc_a = 1
        else:
            cc_a = 0
    return cc_a


def BC_rule_control(state, pre_action):
    """Water-level-threshold rule control for 7 pump stations.

    Pumps: cc_r1, cc_r2, cc_s1, cc_s2 (state[0] = Changgeng storage level)
    Pumps: jk_r1, jk_r2, jk_s     (state[1] = JK storage level)

    Args:
        state: [cc_water_level, jk_water_level] or a longer observation vector (first two dims used).
        pre_action: Previous 7-pump action list [int, ...].
    Returns:
        7-pump action list [cc_r1, cc_r2, cc_s1, cc_s2, jk_r1, jk_r2, jk_s].
    """
    # Water level thresholds per pump [high (start), low (maintain)]
    stdlevel = {
        'cc_r1': [1.2, 0.5],
        'cc_r2': [1.4, 0.5],
        'cc_s1': [0.8, 0.5],
        'cc_s2': [1, 0.5],
        'jk_r1': [4.2, 1.2],
        'jk_r2': [4.3, 1.2],
        'jk_s': [4, 1]
    }
    cc_r1 = level_rule(state[0], pre_action[0], stdlevel['cc_r1'])
    cc_r2 = level_rule(state[0], pre_action[1], stdlevel['cc_r2'])
    cc_s1 = level_rule(state[0], pre_action[2], stdlevel['cc_s1'])
    cc_s2 = level_rule(state[0], pre_action[3], stdlevel['cc_s2'])
    jk_r1 = level_rule(state[1], pre_action[4], stdlevel['jk_r1'])
    jk_r2 = level_rule(state[1], pre_action[5], stdlevel['jk_r2'])
    jk_s = level_rule(state[1], pre_action[6], stdlevel['jk_s'])

    return [cc_r1, cc_r2, cc_s1, cc_s2, jk_r1, jk_r2, jk_s]


# ============================================================
# 1. Load rainfall data (_SWMM.npy) from Scenarios/NMC_Events_2015_2025
#    New format: shape=(72,2) -> [elapsed_hours, mm/hr], hourly
#    SWMM RAIN GAGE uses INTENSITY, so mm/hr values are used directly with no unit conversion
# ============================================================
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenarios_dir = os.path.join(project_root, 'Scenarios', 'NMC_Events_2015_2025')

all_scenarios = []
for folder in sorted(os.listdir(scenarios_dir)):
    folder_path = os.path.join(scenarios_dir, folder)
    if not os.path.isdir(folder_path):
        continue
    # [UPDATED] Prefer *_FULL_SWMM.npy (complete pre+rain+post window);
    #           fall back to the original *_SWMM.npy for backward compatibility
    full_npy_files = glob.glob(os.path.join(folder_path, '*_FULL_SWMM.npy'))
    orig_npy_files = [f for f in glob.glob(os.path.join(folder_path, '*_SWMM.npy'))
                      if not f.endswith('_FULL_SWMM.npy')]
    if full_npy_files:
        npy_path = full_npy_files[0]
    elif orig_npy_files:
        npy_path = orig_npy_files[0]
    else:
        continue
    swmm_data = np.load(npy_path)  # shape (N,2): [elapsed_hours, mm/hr]

    # Skip scenarios with no data or empty 1D arrays (Event_47~52)
    if swmm_data.ndim < 2 or swmm_data.shape[0] == 0:
        print(f"  跳过无降雨数据: {folder} (shape={swmm_data.shape})")
        continue
    if not np.any(swmm_data[:, 1] > 0):
        print(f"  跳过无降雨数据: {folder}")
        continue

    # SWMM RAIN GAGE uses INTENSITY (mm/hr), so the raw mm/hr values are used directly
    # Repeat each hourly value 12 times (one record per 5 min, each holding that hour's intensity in mm/hr)
    # [FIX] Compute hours directly from the array row count to match the span of *_FULL_SWMM.npy
    hours = swmm_data.shape[0]
    rain_array = np.zeros(hours * 12)  # 12 five-minute steps per hour
    for i in range(len(swmm_data)):
        mm_per_hr = swmm_data[i, 1] * 5  # Scale rainfall data by a factor of 5
        rain_array[i * 12:(i + 1) * 12] = mm_per_hr

    # Extract the event date from README.md
    readme_path = os.path.join(folder_path, 'README.md')
    event_date_str = ''
    readme_content = ''  # [NEW] Keep the full README content
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            readme_content = f.read()
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', readme_content)
        if date_match:
            event_date_str = date_match.group(1)

    # [NEW] Locate the warnings.md file
    warnings_md_path = ''
    warnings_md_candidates = glob.glob(os.path.join(folder_path, '*_warnings.md'))
    if warnings_md_candidates:
        warnings_md_path = warnings_md_candidates[0]

    # Fall back to the year parsed from the folder name
    year_match = re.search(r'(\d{4})', folder)
    fallback_year = int(year_match.group(1)) if year_match else 2020

    all_scenarios.append({
        'name': folder,
        'rain_array': rain_array,       # shape (hours*12,), unit: mm/hr (INTENSITY)
        'steps': len(rain_array),
        'event_date_str': event_date_str,
        'fallback_year': fallback_year,
        'readme_content': readme_content,  # [NEW] Full README content for LLM analysis
        'warnings_md_path': warnings_md_path,  # [NEW] Path to warnings.md
    })

print(f"共 {len(all_scenarios)} 个场景:")


# ============================================================
# 2. Convert the npy rainfall array to SWMM TimeseriesData format
#    [MM/DD/YYYY HH:MM:SS, value] - same format as the original raindata
#    Determine the simulation start from center_date in _rain_meta.json
# ============================================================
def build_raindata_from_scenario(scenario):
    """
    Convert a scenario rainfall array to [[time_str, value], ...] format.

    [UPDATED] The rainfall data (*_FULL_SWMM.npy) already covers the full simulation window
    (PRE_HOURS zero values + full rainfall period + POST_HOURS zero values), so this
    function no longer prepends or appends zero segments; it generates the time series step by step.
    """
    rain_array = scenario['rain_array']
    steps = len(rain_array)
    event_date_str = scenario.get('event_date_str', '')

    # [FIX] Parse the real data start from the README "data window" line to compute the simulation start.
    # Row 0 of the original *_SWMM.npy is the start of the data window;
    # Row 0 of *_FULL_SWMM.npy is the start of the data window minus PRE_HOURS (zero-padding added).
    # Fallback: event_date 08:00 - PRE_HOURS (legacy logic, less accurate).
    sim_start_dt = compute_sim_start_from_readme(
        scenario.get('readme_content', ''),
        event_date_str,
        scenario.get('fallback_year', 2020),
    )

    raindata_list = []
    for t in range(steps):
        current_dt = sim_start_dt + datetime.timedelta(minutes=INTERVAL_MIN * t)
        time_str = current_dt.strftime('%m/%d/%Y %H:%M:%S')
        value = float(rain_array[t])
        raindata_list.append([time_str, str(value)])

    return raindata_list, sim_start_dt


# Build raindata for all scenarios (list of lists, same structure as new_training_raindata)
raindata = []
scenario_start_times = []
for scenario in all_scenarios:
    rd, start_dt = build_raindata_from_scenario(scenario)
    raindata.append(rd)
    scenario_start_times.append(start_dt)


# ============================================================
# 3. Adjust SWMM simulation times: set the inp start/end times from the rainfall data
# ============================================================
def modify_inp_simulation_time(inp_path, start_dt, steps, interval_min=INTERVAL_MIN):
    """
    Update the simulation start/end times in the inp file.

    [UPDATED] The rainfall data (*_FULL_SWMM.npy) already covers the full window (pre+rain+post),
    so the total simulation time = steps * interval_min, with no extra pre/post padding.
    The simulation span therefore matches the time span plotted by results.py exactly.
    """
    inp = read_inp_file(inp_path)

    total_minutes = steps * interval_min
    end_dt = start_dt + datetime.timedelta(minutes=total_minutes)

    inp.OPTIONS['START_DATE'] = start_dt.strftime('%m/%d/%Y')
    inp.OPTIONS['START_TIME'] = start_dt.strftime('%H:%M:%S')
    inp.OPTIONS['REPORT_START_DATE'] = start_dt.strftime('%m/%d/%Y')
    inp.OPTIONS['REPORT_START_TIME'] = start_dt.strftime('%H:%M:%S')
    inp.OPTIONS['END_DATE'] = end_dt.strftime('%m/%d/%Y')
    inp.OPTIONS['END_TIME'] = end_dt.strftime('%H:%M:%S')

    return inp


# SWMM environment parameters
# _parent_dir is defined at the top of the file as the absolute path to DRL-control/
_control_dir = os.path.join(_parent_dir, 'SWMM_control', '_tem_control', 'control0')
folder_path = _control_dir
last_slash_idx = folder_path.rfind('/')
name = folder_path[last_slash_idx + 1:]

env_param = {
    'orf': os.path.join(_control_dir, 'chaohu'),
    'orf_save': 'chaohu_RTC',
    'parm': os.path.join(_control_dir, 'chaohu - 20%-control'),
    'advance_seconds': 300,
    'ksys': 0.5,
    'kconb': 0.5,
    'reward_type': '1',
    'istest': True,
}
env = SWMM_ENV_control.SWMM_ENV(env_param)
print(f"\nSWMM 环境: {name}")


# ============================================================
# 4. BC+Agentic interaction: BC rule control + LLM event-driven adjustment
#    [NEW] Integrate event-time detection + LLM analysis + action correction
# ============================================================
def BC_interact(i, env, raindata, scenario_info,
                 enable_adjustment=True,
                 topology_mapper=None, llm_agent=None,
                 llm_advisor=None,
                 llm_refresh_interval=6,        # [v14] Step interval for periodic refresh
                 llm_state_deviation_threshold=0.15,  # [v14] State deviation threshold (15%)
                 llm_rainfall_excess_ratio=1.5):       # [v14] Rainfall excess ratio (150%)
    """
    BC+Agentic interaction - BC rule control as the base strategy + LLM event-driven dynamic adjustment.
    Uses actual scenario rainfall data and matches the SWMM simulation times automatically.

    When enable_adjustment=True, every control step checks for event times;
    on a match, an LLM analyzes the situation and corrects the pump control actions.

    [v14] Supports periodic refresh: at fixed step intervals or when state deviation exceeds a
          threshold, the LLM is called again to update the strategy (instead of once at the first event).

    Args:
        i: Scenario index.
        env: SWMM environment.
        raindata: Rainfall data list.
        scenario_info: Scenario information list.
        enable_adjustment: [NEW] Whether to enable event-driven adjustment.
        topology_mapper: [NEW] DrainageTopologyMapper instance.
        llm_agent: [NEW] LLMEventAgent instance.
        llm_advisor: [NEW] LLMActionAdvisor instance (prompt + LLM call).
        llm_refresh_interval: [v14] Step interval for periodic refresh (default 6 steps).
        llm_state_deviation_threshold: [v14] State deviation trigger threshold (default 0.15 = 15%).
        llm_rainfall_excess_ratio: [v14] Rainfall excess trigger ratio (default 1.5 = 150%).
    """
    scenario = scenario_info[i]
    rain_array_2d = raindata[i]       # [[time_str, value], ...]
    start_dt = scenario_start_times[i]
    steps = scenario['steps']

    # Update the inp simulation times to match the rainfall data
    inp_path = env.params['orf'] + '.inp'
    inp_modified = modify_inp_simulation_time(inp_path, start_dt, steps)

    # Set the rainfall time series
    inp_modified[TIMESERIES]['rainfall'] = TimeseriesData('rainfall', rain_array_2d)

    # Write a temporary inp file
    temp_inp_dir = os.path.join(project_root, 'DRL-control', 'SWMM_control', '_temBCAgenttestinp')
    os.makedirs(temp_inp_dir, exist_ok=True)
    # The SWMM DLL does not support non-ASCII paths, so temporary files are named by index
    temp_inp_path = os.path.join(temp_inp_dir, f"scenario_{i}_rain.inp")
    inp_modified.write_file(temp_inp_path)

    # Initialize env internal state (same logic as env.reset, but with our custom inp)
    env.config = yaml.load(open(env.params['parm'] + ".yaml"), yaml.FullLoader)

    inp_orig = read_inp_file(env.params['orf'] + '.inp')
    env.pipe_idname = {}
    pid = 1
    for k in inp_orig.CONDUITS.keys():
        env.pipe_idname[k] = pid
        pid += 1

    env.node_idname = {}
    nid = 1
    for k in inp_orig.JUNCTIONS.keys():
        env.node_idname[k] = nid
        nid += 1

    # Close the previous Simulation (pyswmm allows only one active Simulation per process)
    if hasattr(env, 'sim') and env.sim is not None:
        try:
            env.sim.close()
        except Exception:
            pass  # Ignore when the model is closed or its state is inconsistent
        env.sim = None
    env.sim = Simulation(temp_inp_path)
    env.sim.start()

    # Initialize results (added adjustment_log, warning_log and original_action)
    env.results = {}
    env.results['CSO'], env.results['flooding'], env.results['inflow'] = [0], [0], [0]
    env.results['total_flooding_time'], env.results['total_CSO_time'] = [0], [0]
    env.results['res'] = [0]
    env.results['state'], env.results['action'], env.results['rewards'] = [], [], []
    env.results['rewards_conb'], env.results['rewards_obs'] = [], []
    env.results['all_state'], env.results['all_inflow'] = [], []
    # [NEW] Adjustment log
    env.results['adjustment_log'] = []       # Detailed record of each adjustment
    env.results['original_actions'] = []     # Raw BC action record (rule-control baseline)
    env.results['adjusted_actions'] = []     # Corrected action actually executed
    env.results['warning_log'] = []          # [NEW] Warning detection + LLM call log
    env.results['llm_full_trace'] = []        # [v6] Full LLM call trace (prompt / response / decision)

    if env.params['advance_seconds'] is None:
        env.sim._model.swmm_step()
    else:
        env.sim._model.swmm_stride(env.params['advance_seconds'])

    # Get the initial observation (same logic as env.reset)
    nodes = Nodes(env.sim)
    links = Links(env.sim)
    rgs = RainGages(env.sim)

    observation = []
    for _temp in env.config["states"]:
        if _temp[1] == 'depthN':
            observation.append(nodes[_temp[0]].depth)
        elif _temp[1] == 'flow':
            observation.append(links[_temp[0]].flow)
        elif _temp[1] == 'inflow':
            observation.append(nodes[_temp[0]].total_inflow)
        else:
            observation.append(rgs[_temp[0]].rainfall)

    # ============================================================
    # [NEW] Multiple event-driven adjustments based on warnings.md
    # ============================================================
    # Parse the warnings.md file
    parsed_warnings = None
    warnings_md_path = scenario.get('warnings_md_path', '')
    if enable_adjustment and warnings_md_path:
        parsed_warnings = parse_warnings_file(warnings_md_path)
        if parsed_warnings and parsed_warnings.records:
            print(f"  [ADJ] Warnings file loaded: {warnings_md_path}")
            print(f"  [ADJ]   Records: {len(parsed_warnings.records)}, "
                  f"time window: {parsed_warnings.time_window_start} ~ {parsed_warnings.time_window_end}")
            for idx, rec in enumerate(parsed_warnings.records):
                print(f"  [ADJ]   #{idx+1}: {rec.publish_time} | {rec.level.value} | {rec.status.value}")
        else:
            print(f"  [ADJ] Warnings file found but no valid records ({warnings_md_path})")
            parsed_warnings = None

    if enable_adjustment and parsed_warnings is None:
        # No warnings.md -> degrade to the original single trigger (backward compatible)
        # In this case the "event trigger step" exists only for compatibility; no LLM call is made
        print(f"  [ADJ] No warnings file available → pure BC mode (no LLM calls)")

    # ============================================================
    # State variables - fully aligned with the new workflow framework
    # ============================================================
    cached_llm_analysis: Optional[CachedLLMAnalysis] = None  # Cache of LLM analysis results (reused across steps)
    warning_trigger_count = 0        # Cumulative trigger count
    llm_action_first_used_step: Optional[int] = None  # Step at which the LLM strategy was first adopted
    llm_action_total_uses: int = 0                    # Cumulative number of LLM strategy adoptions

    # [v14] State variables for periodic refresh
    steps_since_last_llm_call: int = 0       # Steps since the last LLM call (full analysis)
    llm_total_refresh_calls: int = 0         # [v14] Cumulative periodic refresh count (excluding the first event)
    last_llm_realtime_state: dict = {}       # [v14] Realtime state snapshot at the last LLM call (for deviation detection)
    llm_refresh_sequence: list = []          # [v14] Refresh sequence log (for auditing)

    # ============================================================
    # ============================================================
    # Nested function: Step 12 unified timing validation (aligned with the new workflow)
    #
    # Workflow design: every step performs an independent timing check via a second LLM API call;
    #              and no longer uses v8 cache locking / v11 override / Mode B short-circuit optimizations
    # ============================================================
    def _run_timing_validation(
        pending_analysis,
        current_time,
        observation_local,
        t_local,
        at_original_local,
        path_source='A_or_B',  # 'A_or_B' | 'C_no_event_cache'
    ):
        """
        Execute Step 12 timing validation (fully aligned with the new workflow).

        Core design principles:
        - Call the LLM validate_timing API at every step for an independent timing decision
        - No locking / reuse / short-circuit mechanisms
        - Inputs include 5 signal groups: expected rainfall time, current rainfall, storage level trend, LLM analysis cache, current state

        Returns (final_action, updated_cached).
        - The v10 hard cutoff clears cached_llm_analysis.
        """
        nonlocal cached_llm_analysis, llm_action_total_uses, llm_action_first_used_step
        at_local = list(at_original_local)

        if pending_analysis is None or llm_advisor is None:
            return at_local, cached_llm_analysis

        # ============================================================
        # [v10] Hard cutoff: once the current time passes the expected rainfall end time,
        #        discard all LLM strategies and revert to pure BC rule control (safety fallback)
        # ============================================================
        _expected_end = getattr(pending_analysis, 'expected_rain_end_time', None)
        _expected = pending_analysis.expected_rain_time

        # Precompute _dur so it can be referenced in both if/elif branches
        _dur = getattr(
            pending_analysis.rainfall_est, 'duration_hours', 12
        ) if (
            hasattr(pending_analysis, 'rainfall_est')
            and pending_analysis.rainfall_est is not None
        ) else 12

        if _expected_end is not None:
            _hard_deadline = _expected_end
        elif _expected is not None:
            _hard_deadline = _expected + datetime.timedelta(hours=_dur)
        else:
            _hard_deadline = None

        if _hard_deadline is not None and current_time > _hard_deadline:
            print(f"  [STEP-12-{path_source}] => HARD EXPIRED: "
                  f"now={current_time.strftime('%H:%M')} > "
                  f"deadline={_hard_deadline.strftime('%H:%M')} "
                  f"-> 🗑️ Clear ALL LLM cache permanently")

            # Enhanced clearing: reset all LLM-related state variables (nonlocal declared at function start)
            _pre_clear_snapshot = {
                'analysis_origin_step': pending_analysis.analysis_step if pending_analysis else None,
                'total_uses_before_clear': llm_action_total_uses,
                'first_use_step': llm_action_first_used_step,
                'pending_llm_action': list(pending_analysis.llm_adjusted_action) if pending_analysis else None,
            }
            cached_llm_analysis = None      # Clear the LLM analysis cache
            llm_action_total_uses = 0       # Reset the cumulative usage counter
            llm_action_first_used_step = None  # Reset the first-use flag

            env.results['llm_full_trace'].append({
                'step': t_local,
                'sim_time': current_time.strftime('%Y-%m-%d %H:%M'),
                'trace_type': 'mode_v10_hard_expiry',
                'current_rainfall_mm_hr': _read_current_rainfall(
                    observation_local, t_local, rain_array_2d),
                'expected_rain_time': (_expected.strftime('%Y-%m-%d %H:%M') if _expected else None),
                'hard_deadline': _hard_deadline.strftime('%Y-%m-%d %H:%M'),
                'analysis_origin_step': pending_analysis.analysis_step if pending_analysis else None,
                'expiry_reason': f'current_time > deadline ({_dur}h after rain)',
                'final_action_used': 'bc',
                'final_action': list(at_original_local),
                'pending_llm_action': list(pending_analysis.llm_adjusted_action) if pending_analysis else None,
            })
            env.results['adjustment_log'].append({
                'step': t_local,
                'sim_time': current_time.strftime('%Y-%m-%d %H:%M'),
                'trigger_count': warning_trigger_count,
                'path': path_source,
                'event': 'hard_expired_with_full_cache_clear',
                'clear_scope': {
                    'cached_llm_analysis': True,
                    'llm_action_total_uses': True,
                    'llm_action_first_used_step': True,
                },
                'pre_clear_snapshot': _pre_clear_snapshot,
                'used_action': 'bc',
                'final_action': list(at_original_local),
                'reason': f'Safety: exceeded hard deadline ({_hard_deadline}), all LLM state cleared',
            })

            return at_original_local, cached_llm_analysis

        # ============================================================
        # Read the current state signals
        # ============================================================
        current_rainfall = _read_current_rainfall(observation_local, t_local, rain_array_2d)

        # Compute the sustained storage level rise (input condition of workflow Step 12)
        _storage_trend = _compute_storage_trend_signal()

        print(f"  [STEP-12-{path_source}] Timing validation: time={current_time.strftime('%H:%M')}, "
              f"rainfall={current_rainfall:.4f}mm/hr, "
              f"storage_trend={_storage_trend}, "
              f"expected_rain={pending_analysis.expected_rain_time}")

        # ============================================================
        # Core: call validate_timing for an independent timing decision via a second LLM API call
        # (workflow Step 12: independent decision at every step, no cache / lock / short-circuit)
        # ============================================================
        timing_result = llm_advisor.validate_timing(
            pending_or_cached_result=pending_analysis,
            current_sim_time=current_time,
            current_rainfall_value=current_rainfall,
            expected_rain_time=pending_analysis.expected_rain_time,
            realtime_state={'node_depths': current_node_depths}
                           if 'current_node_depths' in dir() else None,
            storage_trend=_storage_trend,   # [Added] Sustained storage level rise
        )

        # Choose the final action based on the LLM timing validation result
        if timing_result.suitable:
            # Adopt the LLM action directly (the duration-limit check has been removed)
            at_local = list(timing_result.action_to_use)
            llm_action_total_uses += 1
            if llm_action_first_used_step is None:
                llm_action_first_used_step = t_local

            print(f"  [STEP-12-{path_source}] => TIMING SUITABLE -> Using LLM action")
            print(f"             Reason: {timing_result.reason}")
        else:
            # 13) Too early / unsuitable -> output the BC rule strategy
            at_local = list(at_original_local)
            print(f"  [STEP-12-{path_source}] => TIMING NOT SUITABLE -> Falling back to BC")
            print(f"             Reason: {timing_result.reason}")

        # Save the LLM analysis to the cache for validation in later steps
        if cached_llm_analysis is None and pending_analysis is not None:
            cached_llm_analysis = pending_analysis
            llm_action_total_uses = 0          # New Event: refresh the counters automatically
            llm_action_first_used_step = None  # Reset the first-use flag
            print(f"  [CACHE] LLM analysis saved for future steps (counters reset)")

        # Logging
        env.results['adjustment_log'].append({
            'step': t_local, 'sim_time': current_time.strftime('%Y-%m-%d %H:%M'),
            'trigger_count': warning_trigger_count,
            'path': path_source,
            'event': 'timing_validation',
            'used_action': 'llm' if timing_result.suitable else 'bc',
            'final_action': list(at_local),
        })
        env.results['warning_log'].append({
            'step': t_local, 'sim_time': current_time.strftime('%Y-%m-%d %H:%M'),
            'event': 'timing_validated',
            'suitable': timing_result.suitable,
            'action_used': 'llm' if timing_result.suitable else 'bc',
        })

        # Full LLM call trace
        env.results['llm_full_trace'].append({
            'step': t_local,
            'sim_time': current_time.strftime('%Y-%m-%d %H:%M'),
            'trace_type': f'step12_timing_validation_{path_source}',
            'current_rainfall_mm_hr': current_rainfall,
            'storage_trend': _storage_trend,
            'expected_rain_time': (
                pending_analysis.expected_rain_time.strftime('%Y-%m-%d %H:%M')
                if hasattr(pending_analysis, 'expected_rain_time')
                   and pending_analysis.expected_rain_time else None
            ),
            'analysis_origin_step': pending_analysis.analysis_step,
            'mode_12_prompt': getattr(timing_result, 'raw_prompt', ''),
            'mode_12_raw_response': getattr(timing_result, 'raw_response', ''),
            'timing_suitable': timing_result.suitable,
            'timing_reason': getattr(timing_result, 'reason', ''),
            'final_action_used': 'llm' if timing_result.suitable else 'bc',
            'final_action': list(at_local),
            'pending_llm_action': list(pending_analysis.llm_adjusted_action),
        })

        return at_local, cached_llm_analysis

    # ============================================================
    # Helper: compute the sustained storage level rise signal
    # (an input condition for workflow Step 12)
    # ============================================================
    def _compute_storage_trend_signal():
        """
        Compute the sustained storage water level rise.

        Return format:
        {
            'trend': 'rising' | 'stable' | 'falling' | 'unknown',
            'rate_m_per_min': float,       # change rate (m/min, positive = rising)
            'storage_nodes': dict,         # current level of each storage node
            'description': str,            # human-readable description
        }
        """
        # Identify storage nodes (names usually contain 'storage' or the local word for reservoir)
        _storage_nodes = {}
        if hasattr(env, 'node_idname'):
            for node_name in env.node_idname:
                if 'storage' in node_name.lower() or '蓄' in node_name:
                    depth = float(nodes[node_name].depth)
                    _storage_nodes[node_name] = depth

        if not _storage_nodes:
            return {'trend': 'unknown', 'rate_m_per_min': 0.0,
                    'storage_nodes': {}, 'description': 'No storage nodes found'}

        # Compute the average water level change rate (requires historical data)
        _avg_depth = sum(_storage_nodes.values()) / len(_storage_nodes)

        # Try to get the previous step's storage levels from the environment results
        _prev_avg = None
        if hasattr(env, 'results') and 'storage_depth_history' in env.results:
            _history = env.results['storage_depth_history']
            if len(_history) >= 2:
                _prev_avg = _history[-2].get('avg_depth')

        if _prev_avg is not None:
            _rate = (_avg_depth - _prev_avg) / 5.0  # One step every 5 minutes
            if _rate > 0.001:
                _trend = 'rising'
                _desc = f'Storage rising (+{_rate:.4f}m/5min, avg={_avg_depth:.3f}m)'
            elif _rate < -0.001:
                _trend = 'falling'
                _desc = f'Storage falling ({_rate:.4f}m/5min, avg={_avg_depth:.3f}m)'
            else:
                _trend = 'stable'
                _desc = f'Storage stable (rate≈0, avg={_avg_depth:.3f}m)'
        else:
            _rate = 0.0
            _trend = 'unknown'
            _desc = f'Storage snapshot (avg={_avg_depth:.3f}m, no history)'

        # Save the current snapshot to history
        if hasattr(env, 'results'):
            if 'storage_depth_history' not in env.results:
                env.results['storage_depth_history'] = []
            env.results['storage_depth_history'].append({
                'step': t,  # Captured from the outer scope
                'avg_depth': _avg_depth,
                'node_depths': dict(_storage_nodes),
            })

        return {
            'trend': _trend,
            'rate_m_per_min': _rate,
            'storage_nodes': _storage_nodes,
            'description': _desc,
        }

    # ============================================================
    # [v14] Helper: state-deviation trigger check
    # ============================================================
    def _check_state_deviation_trigger(
        current_state_snapshot,
        last_snapshot,
        deviation_threshold=llm_state_deviation_threshold,
        rainfall_excess_ratio=llm_rainfall_excess_ratio,
    ):
        """
        Compare the current state with the state at the last LLM call and decide whether to refresh early.

        Trigger conditions (either one is enough):
        1. Storage node level change rate > deviation_threshold (default 15%)
        2. Current rainfall intensity > rainfall_excess_ratio times the last estimated peak (default 150%)

        Args:
            current_state_snapshot: Current realtime state {'node_depths':{}, 'storage_fill_status':{}}.
            last_snapshot: State snapshot taken at the last LLM call.
            deviation_threshold: State deviation threshold (0.15 = 15%).
            rainfall_excess_ratio: Rainfall excess ratio (1.5 = 150%).

        Returns:
            (should_trigger, trigger_reason, details_dict)
        """
        nonlocal cached_llm_analysis

        if not last_snapshot or not current_state_snapshot:
            return False, "no_baseline", {}

        trigger_reasons = []
        details = {}

        # Condition 1: storage level change detection
        current_storage = current_state_snapshot.get('storage_fill_status', {})
        last_storage = last_snapshot.get('storage_fill_status', {})

        max_deviation = 0.0
        deviated_nodes = []
        for node_name, cur_info in current_storage.items():
            if node_name in last_storage:
                cur_ratio = cur_info.get('fill_ratio', 0) / 100.0  # Convert to a fraction
                last_ratio = last_storage[node_name].get('fill_ratio', 0) / 100.0
                if last_ratio > 0.05:  # Avoid dividing by values close to zero
                    deviation = abs(cur_ratio - last_ratio) / last_ratio
                    max_deviation = max(max_deviation, deviation)
                    if deviation > deviation_threshold:
                        deviated_nodes.append({
                            'node': node_name,
                            'last_fill': round(last_ratio * 100, 1),
                            'current_fill': round(cur_ratio * 100, 1),
                            'deviation_pct': round(deviation * 100, 1),
                        })

        if deviated_nodes:
            trigger_reasons.append(f"storage_deviation({max_deviation*100:.1f}%)")
            details['storage_deviated_nodes'] = deviated_nodes
            details['max_storage_deviation'] = round(max_deviation * 100, 1)

        # Condition 2: rainfall excess detection
        try:
            current_rainfall_val = _read_current_rainfall(
                observation, t, rain_array_2d
            )
        except Exception:
            current_rainfall_val = 0.0

        if cached_llm_analysis and hasattr(cached_llm_analysis, 'rainfall_est'):
            est_peak = getattr(cached_llm_analysis.rainfall_est, 'peak_intensity_mm_hr', None)
            if est_peak and est_peak > 0:
                excess_ratio = current_rainfall_val / est_peak
                if excess_ratio > rainfall_excess_ratio:
                    trigger_reasons.append(f"rainfall_excess({excess_ratio:.1f}x)")
                    details['current_rainfall'] = round(current_rainfall_val, 2)
                    details['estimated_peak'] = round(est_peak, 2)
                    details['excess_ratio'] = round(excess_ratio, 2)

        should_trigger = len(trigger_reasons) > 0
        return should_trigger, "; ".join(trigger_reasons) if trigger_reasons else "ok", details

    def _record_state_for_comparison(state_snapshot):
        """
        Record the current state snapshot into last_llm_realtime_state for later deviation comparisons.

        [v14] Called after every full LLM analysis to save the baseline state.
        """
        nonlocal last_llm_realtime_state
        if state_snapshot:
            last_llm_realtime_state = {
                'node_depths': dict(state_snapshot.get('node_depths', {})),
                'storage_fill_status': {
                    k: dict(v) for k, v in state_snapshot.get('storage_fill_status', {}).items()
                },
                'recorded_step': t,
                'recorded_time': (start_dt + datetime.timedelta(minutes=5 * t)).strftime('%Y-%m-%d %H:%M'),
            }





    done, t = False, 0
    pre_action_bc = [0] * 7   # Previous action of the BC controller (all pumps off initially)
    while not done:
        # ===== Step: BC rule control output =====
        at = BC_rule_control(observation, pre_action_bc)
        pre_action_bc = list(at)       # Update the action memory
        at_original = list(at)         # Record the raw BC action (baseline for LLM adjustments)
        observation = np.array(observation).reshape(1, -1)   # Keep the format compatible with the downstream SWMM/LLM modules

        # ===== Step 3: Query Event =====
        new_warning = None
        if enable_adjustment and parsed_warnings is not None:
            new_warning = parsed_warnings.get_warning_at_step(t, start_dt)

        if new_warning is None or getattr(new_warning, 'is_cancelled', False) or not enable_adjustment:
            # ===== [No Event] branch =====
            if new_warning is not None and getattr(new_warning, 'is_cancelled', False):
                # --- Path 1: warning cancelled -> keep state, do not clear the cache ---
                current_time_cancel = start_dt + datetime.timedelta(minutes=5 * t)
                env.results['warning_log'].append({
                    'step': t, 'sim_time': current_time_cancel.strftime('%Y-%m-%d %H:%M'),
                    'event': 'warning_cancelled', 'level': new_warning.level.value,
                    'status': new_warning.status.value, 'action': 'keep_cache_continue',
                })
                print(f"  [ADJ] Warning cancelled at t={t}, keeping cache, using BC action")

            elif new_warning is None and enable_adjustment:
                # --- Path 2: no warning at all -> check for a reusable LLM cache ---
                current_time_ne = start_dt + datetime.timedelta(minutes=5 * t)
                if cached_llm_analysis is not None:
                    # LLM cache present -> timing validation (independent LLM API call at every step)
                    print(f"  [NO-EVENT-CACHE] t={t}: Has LLM cache, entering timing validation "
                          f"(cached from step={cached_llm_analysis.analysis_step})")
                    at, cached_llm_analysis = \
                        _run_timing_validation(
                            pending_analysis=cached_llm_analysis,
                            current_time=current_time_ne,
                            observation_local=observation,
                            t_local=t,
                            at_original_local=at_original,
                            path_source='C_no_event_cache',
                        )
                    # [v14] Also increment the step counter when there is no event (for periodic refresh intervals)
                    steps_since_last_llm_call += 1
                else:
                    # No cache -> use the BC rules directly
                    print(f"  [NO-EVENT] t={t}: No LLM cache available, using pure BC rule control")

            else:
                # --- Path 3: LLM adjustment globally disabled ---
                pass  # Do nothing, keep the current state

        else:
            # ===== [Event present] branch (workflow Steps 3->4) =====
            warning_trigger_count += 1
            current_time = start_dt + datetime.timedelta(minutes=5 * t)

            # [v14] ============================================================
            # Periodic refresh: hybrid trigger (fixed interval + state deviation)
            #
            # Design goals:
            # - First event: follow Path A normally (cached_llm_analysis is None)
            # - Every N steps afterwards, or on a large state change: clear the cache and re-enter Path A
            # - Cost control: about 10-12 calls for a 72-step scenario (instead of only 1)
            # ============================================================
            force_refresh = False
            refresh_trigger_reason = ""
            refresh_details = {}

            if cached_llm_analysis is not None:
                # Cache present -> check whether a periodic refresh is needed
                steps_since_last_llm_call += 1

                # Trigger 1: fixed step interval check
                interval_triggered = steps_since_last_llm_call >= llm_refresh_interval

                # Trigger 2: state deviation detection (collect the current state first)
                deviation_triggered = False
                deviation_reason = ""
                deviation_detail = {}

                # Collect the current state snapshot (same logic as in Path A)
                _current_state_for_deviation_check = {}
                if hasattr(env, 'node_idname'):
                    _current_node_depths_dev = {}
                    _current_storage_fill_dev = {}
                    for node_name in env.node_idname:
                        try:
                            cur_depth = float(nodes[node_name].depth)
                            _current_node_depths_dev[node_name] = cur_depth
                            if 'storage' in node_name.lower() or '蓄' in node_name:
                                max_depth = float(nodes[node_name].full_depth)
                                fill_ratio = (cur_depth / max_depth * 100) if max_depth > 0 else 0.0
                                _current_storage_fill_dev[node_name] = {
                                    'depth': round(cur_depth, 3),
                                    'max_depth': round(max_depth, 3),
                                    'fill_ratio': round(fill_ratio, 1),
                                }
                        except Exception:
                            pass
                    _current_state_for_deviation_check = {
                        'node_depths': _current_node_depths_dev,
                        'storage_fill_status': _current_storage_fill_dev,
                    }

                if _current_state_for_deviation_check:
                    deviation_triggered, deviation_reason, deviation_detail = \
                        _check_state_deviation_trigger(
                            current_state_snapshot=_current_state_for_deviation_check,
                            last_snapshot=last_llm_realtime_state,
                            deviation_threshold=llm_state_deviation_threshold,
                            rainfall_excess_ratio=llm_rainfall_excess_ratio,
                        )

                # Hybrid trigger decision
                force_refresh = interval_triggered or deviation_triggered

                if interval_triggered:
                    refresh_trigger_reason = f"interval(steps={steps_since_last_llm_call}>={llm_refresh_interval})"
                if deviation_triggered:
                    refresh_trigger_reason = (f"{refresh_trigger_reason}; " if refresh_trigger_reason else "") + \
                                             f"deviation({deviation_reason})"
                refresh_details = {
                    'steps_since_last_call': steps_since_last_llm_call,
                    'interval_threshold': llm_refresh_interval,
                    'interval_triggered': interval_triggered,
                    'deviation_triggered': deviation_triggered,
                    'deviation_detail': deviation_detail,
                }

                if force_refresh:
                    llm_total_refresh_calls += 1
                    print(f"  [v14-REFRESH] Triggered at t={t} ({current_time.strftime('%H:%M')})")
                    print(f"              Reason: {refresh_trigger_reason}")
                    print(f"              Details: steps_since={steps_since_last_llm_call}, "
                          f"interval_trig={interval_triggered}, dev_trig={deviation_triggered}")
                    print(f"              Refresh #{llm_total_refresh_calls}: clearing cache → will re-enter Path A")

                    # Record the refresh event in the trace log
                    env.results['llm_full_trace'].append({
                        'step': t,
                        'sim_time': current_time.strftime('%Y-%m-%d %H:%M'),
                        'trace_type': 'v14_periodic_refresh_trigger',
                        'refresh_sequence': llm_total_refresh_calls,
                        'refresh_trigger': refresh_trigger_reason,
                        'steps_since_last_refresh': steps_since_last_llm_call,
                        'is_periodic_refresh': True,
                        **refresh_details,
                    })

                    # Key operation: force-clear the cache so the flow re-enters Path A
                    cached_llm_analysis = None
                    steps_since_last_llm_call = 0  # Reset the counters

            # ===== Original Path A/B branch logic =====
            if cached_llm_analysis is None:
                    # ========================================
                    # Path A: full first-analysis chain (Steps 5-12)
                    # ========================================
                    readme_text = scenario.get('readme_content', '')

                    if llm_agent and readme_text:
                        # Steps 5-6: parse the event text + estimate rainfall amount and duration
                        event_info = llm_agent.parse_readme(readme_text)
                        rainfall_est = llm_agent.analyze_rainfall(event_info)
                        #print(f"\n{'='*60}")
                        #print(f"  *** [PATH-A] Full analysis at step t={t} ***")
                        #print(f"       Sim time: {current_time.strftime('%Y-%m-%d %H:%M')}")
                        #print(f"       Level: {new_warning.level.value} | Status: {new_warning.status.value}")
                        #print(f"       Rainfall est: {rainfall_est.estimated_rainfall_mm}mm, "f"{rainfall_est.duration_hours}h")
                        #print(f"{'='*60}")

                        # Step 8': get all node depths and link flows from the main SWMM run (as initial values)
                        current_node_depths = {}
                        if hasattr(env, 'node_idname'):
                            for node_name in env.node_idname:
                                current_node_depths[node_name] = float(nodes[node_name].depth)

                        # === [v6] Extract relative storage levels (for water-level evaluation in the LLM prompt) ===
                        storage_fill_status = {}
                        if hasattr(env, 'node_idname'):
                            for node_name in env.node_idname:
                                if 'storage' in node_name.lower() or '蓄' in node_name:
                                    try:
                                        cur_depth = float(nodes[node_name].depth)
                                        max_depth = float(nodes[node_name].full_depth)
                                        fill_ratio = cur_depth / max_depth if max_depth > 0 else 0.0
                                        storage_fill_status[node_name] = {
                                            'depth': round(cur_depth, 3),
                                            'max_depth': round(max_depth, 3),
                                            'fill_ratio': round(fill_ratio * 100, 1),
                                        }
                                    except Exception as e:
                                        print(f"  [WARN] Failed to read storage fill for {node_name}: {e}")

                        current_link_flows = {}
                        if hasattr(env, 'pipe_idname'):
                            for link_name in env.pipe_idname:
                                current_link_flows[link_name] = float(links[link_name].flow)
                        realtime_state = {
                            'node_depths': current_node_depths,
                            'link_flows': current_link_flows,
                            'storage_fill_status': storage_fill_status,
                        }
                        print(f"  [A-8'] SWMM state collected: "
                              f"{len(current_node_depths)} nodes, {len(current_link_flows)} links")

                        # Steps 7-9: [removed] the former fast SWMM estimation; use realtime state + LLM analysis directly
                        topo_result = topology_mapper.get_affected_pumps(
                            event_info.location or readme_text
                        )
                        affected_pumps = topo_result.area.affected_pumps
                        affected_nodes = topo_result.area.affected_nodes
                        print(f"  [A-C] Topology: zones={topo_result.area.matched_zones}, "
                              f"pumps={affected_pumps}, nodes={len(affected_nodes)}")

                        # Steps 11-12: fuse information, build the prompt, call the LLM -> LLM-adjusted control strategy
                        topo_summary = ""
                        if topology_mapper:
                            topo_summary = (
                                f"Affected area: {topo_result.area.matched_zones} ({topo_result.area.description})\n"
                                f"Affected pumps: {affected_pumps}\n"
                                f"Affected nodes: {len(affected_nodes)}\n"
                            )

                        llm_result = llm_advisor.get_adjustment(
                            readme_text=readme_text, event_info=event_info,
                            rainfall_est=rainfall_est, cached_impact=None,
                            topo_summary=topo_summary, at_original=at_original,
                            realtime_state=realtime_state,
                            current_sim_time=current_time,
                            warning_record=new_warning,
                        )

                        if llm_result.success and llm_result.source == "llm_agent":
                            at_llm = llm_result.adjusted_action
                            llm_reasoning = llm_result.reasoning
                            print(f"  [A-E] LLM Action adjusted:")
                            print(f"       Original: {llm_result.original_action}")
                            print(f"       Adjusted: {at_llm} (LLM)")
                            print(f"       Changed:  {llm_result.pumps_changed}")
                            print(f"       Reason:   {llm_reasoning}")
                            env.results['adjustment_log'].append({
                                'step': t, 'trigger_count': warning_trigger_count,
                                'path': 'A_full_analysis', 'source': 'llm_agent',
                                'warning_level': new_warning.level.value,
                                'original_action': llm_result.original_action,
                                'adjusted_action': at_llm,
                                'pumps_changed': llm_result.pumps_changed,
                                'urgency': llm_result.urgency,
                                'reason': llm_reasoning,
                                'log': llm_result.log_message,
                            })
                        else:
                            # LLM failure -> keep the raw BC action (the SWMM rule_fallback estimation was removed)
                            at_llm = list(at_original)
                            llm_reasoning = "LLM failed, keeping BC original action"
                            print(f"  [A-E] LLM failed, keeping BC original")

                        # [v6] === Full LLM call trace (Mode A) ===
                        _trace_mode_a = {
                            'step': t,
                            'sim_time': current_time.strftime('%Y-%m-%d %H:%M'),
                            'trace_type': 'mode_a_full_analysis',
                            # --- Input ---
                            'event_info': {
                                'warning_type': getattr(event_info, 'warning_type', None),
                                'location': getattr(event_info, 'location', None),
                                'event_id': getattr(event_info, 'event_id', None),
                            } if event_info else None,
                            'rainfall_est': {
                                'total_mm': getattr(rainfall_est, 'estimated_rainfall_mm', None),
                                'peak_mm_hr': getattr(rainfall_est, 'peak_intensity_mm_hr', None),
                                'duration_hrs': getattr(rainfall_est, 'duration_hours', None),
                                'confidence': getattr(rainfall_est, 'confidence', None),
                            } if rainfall_est else None,
                            'realtime_state': realtime_state,
                            'topo_summary': topo_summary,
                            # --- Mode A LLM call ---
                            'mode_a_prompt': getattr(llm_result, 'raw_prompt', ''),
                            'mode_a_raw_response': getattr(llm_result, 'raw_response', ''),
                            'mode_a_adjusted_action': list(at_llm),
                            'mode_a_reasoning': llm_reasoning,
                            'mode_a_source': getattr(llm_result, 'source', 'unknown'),
                            # [v15] LLM call latency and token usage
                            'api_call_time_ms': getattr(llm_result, 'api_call_time_ms', 0.0),
                            'prompt_tokens': getattr(llm_result, 'prompt_tokens', 0),
                            'completion_tokens': getattr(llm_result, 'completion_tokens', 0),
                            'total_tokens': getattr(llm_result, 'total_tokens', 0),
                            # --- [v14] Periodic refresh marker ---
                            'refresh_sequence': llm_total_refresh_calls + 1,  # Sequence number of this call in the refresh sequence (1 = first event)
                            'refresh_trigger': refresh_trigger_reason if force_refresh else 'first_event',  # Trigger reason
                            'steps_since_last_refresh': steps_since_last_llm_call,  # Steps since the last refresh
                            'is_periodic_refresh': force_refresh,  # Whether this is a periodic refresh (True = not the first event)
                        }
                        env.results['llm_full_trace'].append(_trace_mode_a)

                        # Build CachedLLMAnalysis (used only after timing validation confirms it)
                        pending_analysis = CachedLLMAnalysis(
                            event_info=event_info,
                            rainfall_est=rainfall_est,
                            swmm_impact=None,
                            topo_summary=topo_summary,
                            realtime_state_at_analysis=realtime_state,
                            llm_adjusted_action=list(at_llm),
                            llm_reasoning=llm_reasoning,
                            analysis_step=t,
                            expected_rain_time=_extract_expected_rain_time(rainfall_est, readme_text),
                            expected_rain_end_time=_extract_rainfall_end_time(rainfall_est, readme_text),
                            analysis_timestamp=current_time,
                        )

                        # [v14] Record the current state snapshot as the baseline for deviation detection
                        _record_state_for_comparison(realtime_state)
                        steps_since_last_llm_call = 0  # Reset the step counter

                        env.results['warning_log'].append({
                            'step': t, 'sim_time': current_time.strftime('%Y-%m-%d %H:%M'),
                            'event': 'full_analysis_complete', 'path': 'A',
                            'trigger_count': warning_trigger_count,
                            'level': new_warning.level.value,
                            'status': new_warning.status.value,
                        })
                    else:
                        pending_analysis = None
                        print(f"  [WARN] No llm_agent/readme at t={t}, skipping Path A")
            else:
                # ========================================
                # Path B: cached-analysis reuse chain (Step 13)
                # ========================================
                pending_analysis = cached_llm_analysis
                print(f"  [PATH-B] Using cached LLM analysis "
                      f"(originally from step={pending_analysis.analysis_step})")

            # ================================================
            # Step 12: unified timing validation (convergence point of Path A/B)
            # Fully aligned with the new workflow: every step calls the LLM API independently
            # ================================================
            if pending_analysis is not None:
                at, cached_llm_analysis = \
                    _run_timing_validation(
                        pending_analysis=pending_analysis,
                        current_time=current_time,
                        observation_local=observation,
                        t_local=t,
                        at_original_local=at_original,
                        path_source='A_or_B',
                    )
            elif pending_analysis is not None and llm_advisor is None:
                    # Pending analysis but no advisor -> use BC directly
                    at = list(at_original)
                    if cached_llm_analysis is None:
                        cached_llm_analysis = pending_analysis

        # ===== Final: record original and executed actions in results =====
        env.results['original_actions'].append(at_original)
        env.results['adjusted_actions'].append(list(at))

        observation_new, reward, results, done = env.step(at)
        observation = observation_new
        t += 1

    # Per-scenario summary
    if enable_adjustment and parsed_warnings is not None:
        print(f"\n  [ADJ] Scenario summary: {warning_trigger_count} LLM calls, "
              f"{len(parsed_warnings.records)} warnings total")
        env.results['warning_summary'] = {
            'total_warnings': len(parsed_warnings.records),
            'total_triggers': warning_trigger_count,
            'warnings_file': warnings_md_path,
        }
        # === [v5] Event-driven adjustment summary ===
        # Distribution of timing validation results
        timing_stats = {'suitable': 0, 'too_early': 0, 'total': 0}
        for adj_entry in env.results.get('adjustment_log', []):
            if adj_entry.get('event') == 'timing_validation':
                timing_stats['total'] += 1
                if adj_entry.get('timing_suitable'):
                    timing_stats['suitable'] += 1
                else:
                    timing_stats['too_early'] += 1
        print(f"  [ADJ] Timing validation summary: "
              f"{timing_stats['suitable']}/{timing_stats['total']} suitable, "
              f"{timing_stats['too_early']}/{timing_stats['total']} too_early")
        env.results['timing_summary'] = timing_stats

        # === [v14] Periodic refresh summary ===
        refresh_summary = {
            'total_llm_refresh_calls': llm_total_refresh_calls,
            'refresh_interval_setting': llm_refresh_interval,
            'state_deviation_threshold': llm_state_deviation_threshold,
            'rainfall_excess_ratio': llm_rainfall_excess_ratio,
            'final_steps_since_last_call': steps_since_last_llm_call,
            'has_baseline_state': bool(last_llm_realtime_state),
        }
        # Distribution of refresh trigger reasons
        refresh_trigger_types = {'interval': 0, 'deviation': 0, 'first_event': 0, 'unknown': 0}
        for trace_entry in env.results.get('llm_full_trace', []):
            if trace_entry.get('trace_type') == 'v14_periodic_refresh_trigger':
                if trace_entry.get('interval_triggered'):
                    refresh_trigger_types['interval'] += 1
                if trace_entry.get('deviation_triggered'):
                    refresh_trigger_types['deviation'] += 1
            elif trace_entry.get('trace_type') == 'mode_a_full_analysis':
                if not trace_entry.get('is_periodic_refresh', False):
                    refresh_trigger_types['first_event'] += 1
        refresh_summary['trigger_distribution'] = refresh_trigger_types

        env.results['v14_refresh_summary'] = refresh_summary
        print(f"  [v14-REFRESH] Summary: {llm_total_refresh_calls + 1} total LLM analyses "
              f"(1 initial + {llm_total_refresh_calls} periodic refreshes)")
        print(f"                Trigger distribution: {refresh_trigger_types}")
        print(f"                Config: interval={llm_refresh_interval}steps, "
              f"deviation>{llm_state_deviation_threshold*100}%, "
              f"rainfall>{llm_rainfall_excess_ratio}x peak")

    return env.results


# ============================================================
# 5. [BC+LLM mode] pure rule control + LLM event-driven adjustment
# ============================================================




# ============================================================
# 6. [NEW] Initialize the event-driven adjustment module
# ============================================================
if ENABLE_LLM_ADJUSTMENT:
    _inp_path_for_mapper = os.path.join(_control_dir, 'chaohu.inp')
    _topology_mapper = DrainageTopologyMapper(_inp_path_for_mapper)
    _llm_agent = LLMEventAgent()   # Use the embedded reasoning engine; no external API dependency
    

    
    # LLM Action Advisor (prompt + GLM API call)
    _llm_advisor = LLMActionAdvisor(
        api_key="83a60473a10c488d947d2d0a8e2505bd.OvMFuALVenv6aAFw",
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        model="glm-4-flash",
    )
    
    print(f"\n[INIT] Event-driven adjustment modules loaded:")
    print(f"  TopologyMapper: {_inp_path_for_mapper}")
    print(f"  LLMAgent: available={_llm_agent.llm_available}")
    print(f"  LLMAdvisor: model={_llm_advisor.model}")
else:
    _topology_mapper = None
    _llm_agent = None
    _llm_advisor = None
    print("\n[INIT] LLM adjustment DISABLED — running pure BC rule control mode")


# ============================================================
# 7. Run BC+Agentic tests for each scenario and save results under the scenario name
# ============================================================
os.makedirs('./results', exist_ok=True)

for i, scenario in enumerate(all_scenarios):  # DEBUG: test only the first event
    print(f"\n[{i+1}/{len(all_scenarios)}] 测试: {scenario['name']}")
    print(f"  event_date: {scenario['event_date_str']}, steps: {scenario['steps']}")
    results_BC = BC_interact(  # BC+LLM hybrid control
        i, env, raindata, all_scenarios,
        enable_adjustment=ENABLE_LLM_ADJUSTMENT,
        topology_mapper=_topology_mapper,
        llm_agent=_llm_agent,
        llm_advisor=_llm_advisor,
        # [v14] Periodic refresh parameters (tune per scenario characteristics)
        llm_refresh_interval=6,           # Check every 6 steps whether the LLM strategy needs refreshing
        llm_state_deviation_threshold=0.15,  # Trigger early when storage changes by more than 15%
        llm_rainfall_excess_ratio=1.5,    # Trigger early when actual rainfall exceeds 150% of the estimated peak
    )
    save_path = os.path.join(_this_dir, 'results', f"bc_agent_results_{scenario['name']}.npy")
    np.save(save_path, results_BC)  # BCAgent + LLM event-driven adjustment results
    print(f"  结果已保存: {save_path}")

print("\n所有场景测试完成！")
