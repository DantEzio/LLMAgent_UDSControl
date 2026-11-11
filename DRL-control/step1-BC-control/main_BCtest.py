"""Rule controller (BC) main simulation script - step 1 of the workflow.

Purpose
-------
For every rainstorm event under ``Scenarios/NMC_Events_2015_2025``, run one closed-loop
simulation of the SWMM model with fixed water-level threshold rules and output CSO discharge
and flooding at each time step. This is the reference baseline for the later
MPC / DRL / AgenticAI-BC methods.

Data flow
---------
Inputs:
    Scenarios/NMC_Events_2015_2025/<event>/<event>_FULL_SWMM.npy   (rainfall series)
    Scenarios/NMC_Events_2015_2025/<event>/README.md               (event start/end times)
    DRL-control/SWMM_control/_tem_control/control0/chaohu.inp      (SWMM network model)
Outputs:
    DRL-control/step1-BC-control/results/bc_results_<event>.npy
    plus SWMM .out files (used by generate_html_report.py to plot water levels)

Key conventions
---------------
- The control step and simulation window come from ``DRL-control/time_config.py``
  (PRE_HOURS / POST_HOURS / INTERVAL_MIN);
- Each event must close the SWMM simulation object explicitly, otherwise the next run reports
  ``MultiSimulationError`` because of leftover DLL state;
- Action vector order: [cc_r1, cc_r2, cc_s1, cc_s2, jk_r1, jk_r2, jk_s].

Usage
-----
    python DRL-control/step1-BC-control/main_BCtest.py
"""

import sys
import os
_this_dir = os.path.dirname(os.path.abspath(__file__))       # step1-BC-conopt/
_parent_dir = os.path.dirname(_this_dir)                       # DRL-control/
_grandparent_dir = os.path.dirname(_parent_dir)                # DRL_Agent_UDSRTC/
sys.path.insert(0, _parent_dir)
sys.path.insert(0, _grandparent_dir)

import numpy as np
import pandas as pd
from SWMM_control import SWMM_ENV_control as SWMM_ENV_control
import datetime
import time
import matplotlib.pyplot as plt
from swmm_api import read_out_file
import json
import yaml
import glob
import re

from swmm_api.input_file import read_inp_file
from pyswmm import Simulation,Links,Nodes,RainGages,SystemStats
from swmm_api.input_file.sections.others import TimeseriesData
from swmm_api.input_file.section_labels import TIMESERIES,PUMPS,CONDUITS,OUTFALLS,COORDINATES

# [NEW] Import the shared time configuration (DRL-control/time_config.py)
# _parent_dir (DRL-control/) is already added to sys.path at the top of this file
from time_config import PRE_HOURS, POST_HOURS, INTERVAL_MIN, compute_sim_start_from_readme


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
    swmm_data = np.load(npy_path)  # shape (72,2): [elapsed_hours, mm/hr]

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
    readme_content = ''  # [NEW] Keep the full README content for parsing the data window start
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            readme_content = f.read()
        # Extract the date in "2015-06-02" format (from the title or data window)
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', readme_content)
        if date_match:
            event_date_str = date_match.group(1)

    # Fall back to the year parsed from the folder name
    year_match = re.search(r'(\d{4})', folder)
    fallback_year = int(year_match.group(1)) if year_match else 2020

    all_scenarios.append({
        'name': folder,
        'rain_array': rain_array,       # shape (hours*12,), unit: mm/hr (INTENSITY)
        'steps': len(rain_array),
        'event_date_str': event_date_str,
        'fallback_year': fallback_year,
        'readme_content': readme_content,  # [NEW] Full README content
    })

print(f"共找到 {len(all_scenarios)} 个场景:")
for s in all_scenarios:
    print(f"  {s['name']}: steps={s['steps']}, event_date={s['event_date_str']}")


# ============================================================
# 2. Convert the npy rainfall array to SWMM TimeseriesData format
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


raindata = []
scenario_start_times = []
for scenario in all_scenarios:
    rd, start_dt = build_raindata_from_scenario(scenario)
    raindata.append(rd)
    scenario_start_times.append(start_dt)

print(f"\n降雨数据转换完成，共 {len(raindata)} 组")


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


# ============================================================
# 4. SWMM environment initialization
# ============================================================
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
# 5. BC rule controller (same as the original code)
# ============================================================
def BC_rule_control(state, pre_action):
    """Rule controller entry point: basin levels and the previous action determine the 7 pump states.

    Parameters
    ----------
    state : sequence[float]
        ``state[0]`` = CC storage depth, ``state[1]`` = JK storage depth (m).
    pre_action : sequence[int]
        Previous action, in the order [cc_r1, cc_r2, cc_s1, cc_s2, jk_r1, jk_r2, jk_s].

    Returns
    -------
    list[int]
        Current action in the same order as ``pre_action``. Thresholds are fixed and do not
        scale with basin design depths.
    """
    # state[0]:cc-storage depth; state[1]:jk-storage depth
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


def level_rule(level, pre_action, stdlevel):
    """Hysteresis water-level rule for a single pump.

    Parameters
    ----------
    level : float
        Current water depth (m).
    pre_action : int
        Previous action of this pump (0=off, 1=on).
    stdlevel : sequence[float]
        ``[high threshold, low threshold]``; above the high threshold the pump is forced on,
        below the low threshold it is forced off, and in between the previous state is kept
        (hysteresis, avoids frequent switching).

    Returns
    -------
    int
        Current action of this pump (0=off, 1=on).
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


# ============================================================
# 6. BC interaction: use actual scenario rainfall data and matching simulation times
# ============================================================
def BC_interact(i, env, raindata, scenario_info):
    """BC rule control interaction - uses actual scenario rainfall data and matches SWMM simulation times automatically"""
    scenario = scenario_info[i]
    rain_array_2d = raindata[i]
    start_dt = scenario_start_times[i]
    steps = scenario['steps']

    # Update the inp simulation times to match the rainfall data
    inp_path = env.params['orf'] + '.inp'
    inp_modified = modify_inp_simulation_time(inp_path, start_dt, steps)

    # Set the rainfall time series
    inp_modified[TIMESERIES]['rainfall'] = TimeseriesData('rainfall', rain_array_2d)

    # Write a temporary inp file
    temp_inp_dir = os.path.join(project_root, 'DRL-control', 'SWMM_control', '_temBCtestinp')
    os.makedirs(temp_inp_dir, exist_ok=True)
    # The SWMM DLL does not support non-ASCII paths, so temporary files are named by index
    temp_inp_path = os.path.join(temp_inp_dir, f"scenario_{i}_rain.inp")
    inp_modified.write_file(temp_inp_path)

    # Initialize the env internal state
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
            pass
    # Guard: pyswmm close() sometimes fails to fully reset global state
    try:
        from pyswmm.simulation import _sim_state_instance
        if _sim_state_instance.sim_is_instantiated:
            _sim_state_instance.sim_is_instantiated = False
    except ImportError:
        pass
    env.sim = Simulation(temp_inp_path)
    env.sim.start()

    # Initialize results
    env.results = {}
    env.results['CSO'], env.results['flooding'], env.results['inflow'] = [0], [0], [0]
    env.results['total_flooding_time'], env.results['total_CSO_time'] = [0], [0]
    env.results['res'] = [0]
    env.results['state'], env.results['action'], env.results['rewards'] = [], [], []
    env.results['rewards_conb'], env.results['rewards_obs'] = [], []
    env.results['all_state'], env.results['all_inflow'] = [], []
    env.results['compute_time'] = []   # Compute time per control step (seconds): from receiving the state to returning the action

    if env.params['advance_seconds'] is None:
        env.sim._model.swmm_step()
    else:
        env.sim._model.swmm_stride(env.params['advance_seconds'])

    # Get the initial observation
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

    done, t = False, 0
    pre_action = [0 for _ in range(len(env.config['action_assets']))]
    while not done:
        _t_start = time.perf_counter()                       # Timing start: state has been received
        action = BC_rule_control(observation, pre_action)   # state -> action computation
        _t_end = time.perf_counter()                         # Timing end: action has been produced
        env.results['compute_time'].append(_t_end - _t_start)
        pre_action = action
        observation_new, reward, results, done = env.step(action)
        observation = observation_new
    return env.results


# ============================================================
# 7. Run the BC rule control test for each scenario and save results by scenario name
# ============================================================
os.makedirs(os.path.join(_this_dir, 'results'), exist_ok=True)

for i, scenario in enumerate(all_scenarios):
    print(f"\n[{i+1}/{len(all_scenarios)}] 测试: {scenario['name']}")
    print(f"  event_date: {scenario['event_date_str']}, steps: {scenario['steps']}")
    results = BC_interact(i, env, raindata, all_scenarios)
    save_path = os.path.join(_this_dir, 'results', f"bc_results_{scenario['name']}.npy")
    np.save(save_path, results)
    print(f"  结果已保存: {save_path}")
    _ct = results.get('compute_time', [])
    if _ct:
        print(f"  计算耗时(秒): 共{len(_ct)}步, 总计={sum(_ct):.4f}s, "
              f"平均={sum(_ct)/len(_ct):.6f}s, 最大={max(_ct):.6f}s")

print("\n所有场景 BC 规则控制测试完成！")
