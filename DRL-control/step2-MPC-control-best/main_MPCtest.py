# -*- coding: utf-8 -*-
"""
step2-MPC-control: Model Predictive Control for SWMM urban drainage.

Differences from step2-DRL-control:
  - DRL: a trained PPO model selects the actions
  - MPC: at every step, PSO optimizes the next Np actions and only the first one is executed (receding horizon)

Key design:
  1. SWMM model, pump stations and rainfall data are identical to step2-DRL
  2. Predictions use SWMM subprocess simulations (inject current state + future rainfall time series)
  3. Scenario warning information is never used - only future values of the rainfall time series
  4. Optimizer: PSO (particle swarm), see pso.py
  5. File reading/saving is consistent with step2-DRL
"""

import sys
import os
import json
import subprocess
import shutil
import time

_this_dir = os.path.dirname(os.path.abspath(__file__))       # step2-MPC-control/
_parent_dir = os.path.dirname(_this_dir)                       # DRL-control/
_grandparent_dir = os.path.dirname(_parent_dir)                # DRL_Agent_UDSRTC/
sys.path.insert(0, _parent_dir)
sys.path.insert(0, _grandparent_dir)

import numpy as np
import pandas as pd
from SWMM_control import SWMM_ENV_control as SWMM_ENV_control
import datetime
from swmm_api.input_file import read_inp_file
from swmm_api.input_file.sections.others import TimeseriesData
from swmm_api.input_file.section_labels import TIMESERIES

from time_config import INTERVAL_MIN, compute_sim_start_from_readme
from pso import PSO
import yaml
import glob
import re


# ============================================================
# MPC parameters
# ============================================================
# Prediction horizon (steps, 5 min/step)
#   Production: 6 (30 min) | quick test: 3 (15 min)
PREDICTION_HORIZON = 3

# PSO population size
#   Production: 10-20 | quick test: 3
PSO_POPULATION = 10

# PSO iteration count
#   Production: 10-20 | quick test: 2-3
PSO_ITERATIONS = 5

# PSO inertia weight and acceleration coefficients
PSO_W = 0.8
PSO_C = 0.5

# Parallel PSO evaluation: launch an independent subprocess for each particle
#   True  = parallel (evaluate particles in multiple subprocesses, much faster)
#   False = serial (loop over particles in one subprocess, original approach)
PSO_PARALLEL = True
# Maximum parallel workers (0 = unlimited, all particles at once)
#   Set to the CPU core count to avoid slowdown from process contention
PSO_MAX_PARALLEL_WORKERS = 0

# Test mode: True = a few scenarios and steps | False = run everything
TEST_MODE = False
TEST_MAX_SCENARIOS = 0       # Test mode: maximum number of scenarios (0 = all)
TEST_MAX_STEPS = 0           # Test mode: maximum steps per scenario (0 = unlimited)
START_EVENT_INDEX = 2        # Starting event index (0 = first event, 1 = second event, ...)



# ============================================================
# 1. Load rainfall data from Scenarios/NMC_Events_2015_2025
#    (identical to main_PPOtest.py)
# ============================================================
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenarios_dir = os.path.join(project_root, 'Scenarios', 'NMC_Events_2015_2025')

all_scenarios = []
for folder in sorted(os.listdir(scenarios_dir)):
    folder_path = os.path.join(scenarios_dir, folder)
    if not os.path.isdir(folder_path):
        continue
    full_npy_files = glob.glob(os.path.join(folder_path, '*_FULL_SWMM.npy'))
    orig_npy_files = [f for f in glob.glob(os.path.join(folder_path, '*_SWMM.npy'))
                      if not f.endswith('_FULL_SWMM.npy')]
    if full_npy_files:
        npy_path = full_npy_files[0]
    elif orig_npy_files:
        npy_path = orig_npy_files[0]
    else:
        continue
    swmm_data = np.load(npy_path)

    if swmm_data.ndim < 2 or swmm_data.shape[0] == 0:
        print(f"  跳过无降雨数据: {folder} (shape={swmm_data.shape})")
        continue
    if not np.any(swmm_data[:, 1] > 0):
        print(f"  跳过无降雨数据: {folder}")
        continue

    hours = swmm_data.shape[0]
    rain_array = np.zeros(hours * 12)
    for i in range(len(swmm_data)):
        mm_per_hr = swmm_data[i, 1] * 5
        rain_array[i * 12:(i + 1) * 12] = mm_per_hr

    readme_path = os.path.join(folder_path, 'README.md')
    event_date_str = ''
    readme_content = ''
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            readme_content = f.read()
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', readme_content)
        if date_match:
            event_date_str = date_match.group(1)

    year_match = re.search(r'(\d{4})', folder)
    fallback_year = int(year_match.group(1)) if year_match else 2020

    all_scenarios.append({
        'name': folder,
        'rain_array': rain_array,
        'steps': len(rain_array),
        'event_date_str': event_date_str,
        'fallback_year': fallback_year,
        'readme_content': readme_content,
    })

print(f"共找到 {len(all_scenarios)} 个场景:")
for s in all_scenarios:
    print(f"  {s['name']}: steps={s['steps']}, event_date={s['event_date_str']}")


# ============================================================
# 2. Convert the npy rainfall array to SWMM TimeseriesData format
#    (identical to main_PPOtest.py)
# ============================================================
def build_raindata_from_scenario(scenario):
    """Convert one scenario's rainfall array into the row-wise text block required by SWMM Excel/TimeseriesData.

    Args:
        scenario: Scenario dict containing at least rain_array and event_date_str.

    Returns:
        Rainfall time series text that can be injected directly into an inp file.
    """
    rain_array = scenario['rain_array']
    steps = len(rain_array)
    event_date_str = scenario.get('event_date_str', '')

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
print(f"示例 (第1组前3行): {raindata[0][:3]}")


# ============================================================
# 3. Adjust the SWMM simulation times
#    (identical to main_PPOtest.py)
# ============================================================
def modify_inp_simulation_time(inp_path, start_dt, steps, interval_min=INTERVAL_MIN):
    """Rewrite the simulation start/end times in an inp file so the window matches the rainfall series length exactly.

    Args:
        inp_path: Path of the inp file to modify.
        start_dt: Simulation start datetime.
        steps: Total number of control steps.
        interval_min: Minutes per step; defaults to time_config.INTERVAL_MIN.
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
# 4. SWMM environment parameters (identical to main_PPOtest.py)
# ============================================================
_control_dir = os.path.join(_parent_dir, 'SWMM_control', '_tem_control', 'control0')
folder_path = _control_dir
last_slash_idx = folder_path.rfind('\\') if '\\' in folder_path else folder_path.rfind('/')
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

# Load the configuration and action_table
config = yaml.load(open(env_param['parm'] + ".yaml"), yaml.FullLoader)
action_table = pd.read_csv(os.path.join(_parent_dir, 'SWMM_control', 'action_table.csv')).values[:, 1:]
print(f"Action table shape: {action_table.shape}")  # (128, 7)
print(f"Action assets (pumps): {config['action_assets']}")
print(f"Reward targets: {config['reward_targets']}")


# ============================================================
# 5. Build prediction INP files: inject the current state and future rainfall
# ============================================================
# Temporary prediction INP directory
_pred_inp_dir = os.path.join(_parent_dir, 'SWMM_control', '_temMPCpredictinp')
os.makedirs(_pred_inp_dir, exist_ok=True)

# Temporary INP directory for the main simulation
_main_inp_dir = os.path.join(_parent_dir, 'SWMM_control', '_temMPCtestinp')
os.makedirs(_main_inp_dir, exist_ok=True)

# Directory for PSO convergence curves (one subfolder per event, one .npy per step)
_results_mpc_curve_dir = os.path.join(_this_dir, 'Results_MPC')
os.makedirs(_results_mpc_curve_dir, exist_ok=True)

# Get all node and link names (including STORAGE) from the template INP
_template_inp_path = env_param['orf'] + '.inp'
_template_inp = read_inp_file(_template_inp_path)
_junction_names = list(_template_inp.JUNCTIONS.keys()) if hasattr(_template_inp, 'JUNCTIONS') else []
_storage_names = list(_template_inp.STORAGE.keys()) if hasattr(_template_inp, 'STORAGE') else []
_conduit_names = list(_template_inp.CONDUITS.keys()) if hasattr(_template_inp, 'CONDUITS') else []
_all_node_names = _junction_names + _storage_names
print(f"\n节点数: {len(_junction_names)} JUNCTIONS + {len(_storage_names)} STORAGE = {len(_all_node_names)}")
print(f"管段数: {len(_conduit_names)} CONDUITS")


def create_prediction_inp(node_depths, link_flows, future_rain, current_dt, horizon, step_idx):
    """
    Create an INP file for prediction:
      - Inject current node depths and link flows as initial conditions
      - Set the future rainfall time series
      - Set the simulation time to [current_dt, current_dt + horizon*5min]

    Args:
        node_depths: {node_name: depth_m}  current node depths
        link_flows:  {link_name: flow_cms} current link flows
        future_rain: [[time_str, value], ...]  future rainfall time series
        current_dt:  datetime  current simulation time
        horizon:     int  number of prediction steps
        step_idx:    int  current control step index (used for file naming)

    Returns:
        Path to the temporary INP file.
    """
    inp = read_inp_file(_template_inp_path)

    # Set the simulation times
    end_dt = current_dt + datetime.timedelta(minutes=INTERVAL_MIN * horizon)
    inp.OPTIONS['START_DATE'] = current_dt.strftime('%m/%d/%Y')
    inp.OPTIONS['START_TIME'] = current_dt.strftime('%H:%M:%S')
    inp.OPTIONS['REPORT_START_DATE'] = current_dt.strftime('%m/%d/%Y')
    inp.OPTIONS['REPORT_START_TIME'] = current_dt.strftime('%H:%M:%S')
    inp.OPTIONS['END_DATE'] = end_dt.strftime('%m/%d/%Y')
    inp.OPTIONS['END_TIME'] = end_dt.strftime('%H:%M:%S')

    # Set initial conditions: JUNCTION depth_init
    if hasattr(inp, 'JUNCTIONS') and inp.JUNCTIONS:
        for node_name, depth_val in node_depths.items():
            if node_name in inp.JUNCTIONS:
                inp.JUNCTIONS[node_name].depth_init = float(depth_val)

    # Set initial conditions: STORAGE depth_init
    if hasattr(inp, 'STORAGE') and inp.STORAGE:
        for node_name, depth_val in node_depths.items():
            if node_name in inp.STORAGE:
                inp.STORAGE[node_name].depth_init = float(depth_val)

    # Set initial conditions: CONDUIT flow_initial
    if hasattr(inp, 'CONDUITS') and inp.CONDUITS:
        for link_name, flow_val in link_flows.items():
            if link_name in inp.CONDUITS:
                inp.CONDUITS[link_name].flow_initial = float(flow_val)

    # Set the rainfall time series
    inp[TIMESERIES]['rainfall'] = TimeseriesData('rainfall', future_rain)

    # Clear negative CONDUIT offsets (avoids WARNING 03)
    if hasattr(inp, 'CONDUITS'):
        for conduit_name, conduit_obj in inp.CONDUITS.items():
            if hasattr(conduit_obj, 'offset_downstream') and conduit_obj.offset_downstream is not None:
                if conduit_obj.offset_downstream < 0:
                    conduit_obj.offset_downstream = 0.0
            if hasattr(conduit_obj, 'offset_upstream') and conduit_obj.offset_upstream is not None:
                if conduit_obj.offset_upstream < 0:
                    conduit_obj.offset_upstream = 0.0

    # Write the temporary file
    temp_inp_path = os.path.join(_pred_inp_dir, f"predict_step{step_idx}.inp")
    inp.write_file(temp_inp_path)

    return temp_inp_path


# ============================================================
# 6. SWMM prediction in a subprocess (pyswmm allows one Simulation per process)
# ============================================================
def run_swmm_prediction_batch(inp_path, particles_actions, config_dict, advance_seconds):
    """
    Run SWMM predictions in a subprocess batch and evaluate the fitness of multiple particles.

    Args:
        inp_path: Prediction INP file path (already contains initial conditions and rainfall).
        particles_actions: list of action sequences, each a list of 7-element lists.
        config_dict: {'action_assets': [...], 'reward_targets': [...]}.
        advance_seconds: Seconds to advance per step.

    Returns:
        list of fitness values (float), one per particle.
    """
    # Serialize data to embed in the subprocess script
    particles_json = json.dumps(particles_actions)
    action_assets_json = json.dumps(config_dict['action_assets'])
    # reward_targets may be a tuple; convert it to a list
    reward_targets_list = [list(rt) if isinstance(rt, (tuple, list)) else rt
                           for rt in config_dict['reward_targets']]
    reward_targets_json = json.dumps(reward_targets_list)

    # Build the subprocess script
    subprocess_script = f'''
import json, sys, os
os.environ['CONDA_DLL_SEARCH_MODIFICATION_ENABLE'] = "1"
from pyswmm import Simulation, Nodes, Links, SystemStats

inp_path = {json.dumps(inp_path)}
particles_actions = {particles_json}
action_assets = {action_assets_json}
reward_targets = {reward_targets_json}
advance_seconds = {advance_seconds}

results = []
for particle_actions in particles_actions:
    sim = Simulation(inp_path)
    sim.start()
    nodes = Nodes(sim)
    links = Links(sim)
    sys_stats = SystemStats(sim)

    for action in particle_actions:
        for item, a in zip(action_assets, action):
            links[item].target_setting = float(a)
        sim._model.swmm_stride(advance_seconds)

    # 收集累积结果
    flooding = sys_stats.routing_stats['flooding']

    cso = 0.0
    for rt in reward_targets:
        if rt[1] != 'flooding':
            cso += nodes[rt[0]].cumulative_inflow

    qtw = (sys_stats.routing_stats['dry_weather_inflow']
           + sys_stats.routing_stats['wet_weather_inflow']
           + sys_stats.routing_stats['groundwater_inflow']
           + sys_stats.routing_stats['II_inflow'])

    if qtw > 0:
        fitness = -(flooding + cso) / qtw
    else:
        fitness = 0.0

    results.append(fitness)
    sim.close()

print(json.dumps(results))
'''

    proc = subprocess.run(
        [sys.executable, '-c', subprocess_script],
        capture_output=True, text=True, timeout=600,
    )

    if proc.returncode != 0 or not proc.stdout.strip():
        err_msg = proc.stderr[:300] if proc.stderr else "Unknown error"
        print(f"  [MPC Predict] 子进程失败: {err_msg}")
        return [-999.0] * len(particles_actions)

    stdout = proc.stdout.strip()
    result = json.loads(stdout)
    return result


# ============================================================
# 7. PSO fitness function
# ============================================================
def run_swmm_prediction_parallel(inp_path, particles_actions, config_dict,
                                  advance_seconds, timeout=600):
    """
    Launch an independent subprocess for each particle and run SWMM predictions concurrently.

    Differences from run_swmm_prediction_batch (serial):
      - Each particle runs in its own subprocess; all subprocesses start concurrently
      - Each particle uses its own temporary INP copy (avoids SWMM .out file conflicts)
      - PSO_MAX_PARALLEL_WORKERS limits concurrency (batched execution)

    Args:
        inp_path: Prediction INP file path (already contains initial conditions and rainfall).
        particles_actions: list of action sequences, each a list of 7-element lists.
        config_dict: {'action_assets': [...], 'reward_targets': [...]}.
        advance_seconds: Seconds to advance per step.
        timeout: Timeout in seconds for a single subprocess.

    Returns:
        list of fitness values (float), one per particle.
    """
    n_particles = len(particles_actions)
    if n_particles == 0:
        return []

    max_workers = (PSO_MAX_PARALLEL_WORKERS
                   if PSO_MAX_PARALLEL_WORKERS > 0 else n_particles)

    action_assets_json = json.dumps(config_dict['action_assets'])
    reward_targets_list = [list(rt) if isinstance(rt, (tuple, list)) else rt
                           for rt in config_dict['reward_targets']]
    reward_targets_json = json.dumps(reward_targets_list)

    fitnesses = [-999.0] * n_particles

    # Run in concurrent batches (at most max_workers particles per batch)
    for batch_start in range(0, n_particles, max_workers):
        batch_end = min(batch_start + max_workers, n_particles)

        # Create a separate temporary INP copy per particle in this batch (avoids .out conflicts)
        batch_inp_paths = {}
        for p_idx in range(batch_start, batch_end):
            dst = os.path.join(_pred_inp_dir, f"predict_particle_{p_idx}.inp")
            shutil.copy2(inp_path, dst)
            batch_inp_paths[p_idx] = dst

        # Build and launch all subprocesses for this batch (one per particle)
        processes = {}
        for p_idx in range(batch_start, batch_end):
            particle_actions_json = json.dumps(particles_actions[p_idx])
            script = f'''
import json, os
os.environ['CONDA_DLL_SEARCH_MODIFICATION_ENABLE'] = "1"
from pyswmm import Simulation, Nodes, Links, SystemStats

inp_path = {json.dumps(batch_inp_paths[p_idx])}
particle_actions = {particle_actions_json}
action_assets = {action_assets_json}
reward_targets = {reward_targets_json}
advance_seconds = {advance_seconds}

sim = Simulation(inp_path)
sim.start()
nodes = Nodes(sim)
links = Links(sim)
sys_stats = SystemStats(sim)

for action in particle_actions:
    for item, a in zip(action_assets, action):
        links[item].target_setting = float(a)
    sim._model.swmm_stride(advance_seconds)

flooding = sys_stats.routing_stats['flooding']
cso = 0.0
for rt in reward_targets:
    if rt[1] != 'flooding':
        cso += nodes[rt[0]].cumulative_inflow

qtw = (sys_stats.routing_stats['dry_weather_inflow']
       + sys_stats.routing_stats['wet_weather_inflow']
       + sys_stats.routing_stats['groundwater_inflow']
       + sys_stats.routing_stats['II_inflow'])

if qtw > 0:
    fitness = -(flooding + cso) / qtw
else:
    fitness = 0.0

sim.close()
print(fitness)
'''
            proc = subprocess.Popen(
                [sys.executable, '-c', script],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            processes[p_idx] = proc

        # Poll until this batch finishes (with timeout, no try-except)
        start_time = time.time()
        timed_out = set()
        while True:
            all_done = True
            elapsed = time.time() - start_time
            for p_idx, proc in processes.items():
                if proc.poll() is None:
                    if elapsed > timeout:
                        proc.kill()
                        timed_out.add(p_idx)
                    else:
                        all_done = False
            if all_done:
                break
            time.sleep(0.3)

        # Collect the results
        for p_idx, proc in processes.items():
            stdout, stderr = proc.communicate()
            if p_idx in timed_out:
                print(f"  [MPC Predict] 粒子 {p_idx} 超时 (>{timeout}s)")
                fitnesses[p_idx] = -999.0
                continue
            if proc.returncode != 0 or not stdout.strip():
                err_msg = stderr[:300] if stderr else "Unknown error"
                print(f"  [MPC Predict] 粒子 {p_idx} 子进程失败 (rc={proc.returncode}): {err_msg}")
                fitnesses[p_idx] = -999.0
                continue
            fitnesses[p_idx] = float(stdout.strip())

        # Clean up this batch's temporary INP copies and SWMM output files
        for p_idx, inp_copy in batch_inp_paths.items():
            base = os.path.splitext(inp_copy)[0]
            for ext in ['.inp', '.out', '.rpt']:
                f = base + ext
                if os.path.exists(f):
                    os.remove(f)

    return fitnesses


def calculate_fitness(particles, inp_path=None, action_table_np=None,
                      config_dict=None, advance_seconds=None):
    """
    PSO fitness function: evaluate all particles.

    Each particle is a set of continuous [0,1] values (dimension = prediction horizon),
    mapped to discrete action indices and then to 7-pump control vectors via action_table.

    Args:
        particles: np.array (population_size, dim), values in [0, 1].
        inp_path: Prediction INP path.
        action_table_np: np.array (128, 7) action table.
        config_dict: Configuration dict.
        advance_seconds: Seconds to advance per step.

    Returns:
        np.array (population_size,) fitness values.
    """
    # Map particles to action sequences
    particles_actions = []
    for particle in particles:
        actions = []
        for x in particle:
            idx = int(x * 128)
            idx = max(0, min(127, idx))
            actions.append(action_table_np[idx].tolist())
        particles_actions.append(actions)

    # Run the SWMM predictions (parallel or serial)
    if PSO_PARALLEL:
        fitnesses = run_swmm_prediction_parallel(
            inp_path, particles_actions, config_dict, advance_seconds
        )
    else:
        fitnesses = run_swmm_prediction_batch(
            inp_path, particles_actions, config_dict, advance_seconds
        )

    return np.array(fitnesses)


# ============================================================
# 8. MPC interaction function
# ============================================================
def MPC_interact(i, env, raindata, scenario_info, curve_save_dir=None):
    """
    MPC control - SWMM prediction + PSO optimization.

    Flow:
      1. Start the main simulation (same as PPO_interact)
      2. At every step:
         a. Collect the current system state (node depths, link flows)
         b. Extract future rainfall (next Np steps of the rainfall time series)
         c. Create the prediction INP (inject current state + future rainfall)
         d. Optimize the future action sequence with PSO
         e. Execute the first action and advance the main simulation by one step

    Args:
        curve_save_dir: If not None, save each step's PSO convergence curve as a .npy file here.
    """
    scenario = scenario_info[i]
    rain_array_2d = raindata[i]       # [[time_str, value], ...]
    start_dt = scenario_start_times[i]
    steps = scenario['steps']

    # Adjust inp simulation times to match the rainfall data (same as PPO_interact)
    inp_path = env.params['orf'] + '.inp'
    inp_modified = modify_inp_simulation_time(inp_path, start_dt, steps)
    inp_modified[TIMESERIES]['rainfall'] = TimeseriesData('rainfall', rain_array_2d)

    temp_inp_path = os.path.join(_main_inp_dir, f"scenario_{i}_rain.inp")
    inp_modified.write_file(temp_inp_path)

    # Initialize the env internal state (same as PPO_interact)
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

    from pyswmm import Simulation
    # Close the previous Simulation (pyswmm limitation)
    if hasattr(env, 'sim') and env.sim is not None:
        env.sim.close()

    env.sim = Simulation(temp_inp_path)
    env.sim.start()

    # Initialize results (same as PPO_interact)
    env.results = {}
    env.results['CSO'], env.results['flooding'], env.results['inflow'] = [0], [0], [0]
    env.results['total_flooding_time'], env.results['total_CSO_time'] = [0], [0]
    env.results['res'] = [0]
    env.results['state'], env.results['action'], env.results['rewards'] = [], [], []
    env.results['rewards_conb'], env.results['rewards_obs'] = [], []
    env.results['all_state'], env.results['all_inflow'] = [], []
    env.results['compute_time'] = []   # Compute time per control step (seconds): from receiving the state to returning the action

    # Initial step (same as PPO_interact)
    if env.params['advance_seconds'] is None:
        env.sim._model.swmm_step()
    else:
        env.sim._model.swmm_stride(env.params['advance_seconds'])

    # Get the initial observation (same as PPO_interact)
    from pyswmm import Nodes, Links, RainGages
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

    # Prepare config_dict for the subprocess
    config_dict = {
        'action_assets': list(env.config['action_assets']),
        'reward_targets': [list(rt) if isinstance(rt, (tuple, list)) else rt
                           for rt in env.config['reward_targets']],
    }
    advance_seconds = env.params['advance_seconds']

    done = False
    step = 0
    max_steps = TEST_MAX_STEPS if TEST_MODE and TEST_MAX_STEPS > 0 else 999999

    # Warm start: keep the previous PSO best solution to seed the current swarm
    prev_best_pos = None

    while not done and step < max_steps:
        _t_start = time.perf_counter()   # Timing start: begin receiving the state
        # --- Collect the current system state ---
        nodes = Nodes(env.sim)
        links = Links(env.sim)

        node_depths = {}
        for name in _all_node_names:
            node_depths[name] = nodes[name].depth

        link_flows = {}
        for name in _conduit_names:
            link_flows[name] = links[name].flow

        # --- Extract future rainfall ---
        # Current time = sim_start + (step+1) * INTERVAL_MIN
        # (1 initial step + step loop steps)
        rain_start_idx = step + 1
        remaining = len(rain_array_2d) - rain_start_idx
        if remaining <= 0:
            print(f"  [Step {step}] 降雨数据已用完, 退出循环")
            break

        actual_horizon = min(PREDICTION_HORIZON, remaining)
        future_rain = rain_array_2d[rain_start_idx:rain_start_idx + actual_horizon]

        # Current time (used to set the prediction INP start time)
        current_dt = start_dt + datetime.timedelta(minutes=INTERVAL_MIN * rain_start_idx)

        # --- Create the prediction INP ---
        pred_inp_path = create_prediction_inp(
            node_depths, link_flows, future_rain,
            current_dt, actual_horizon, step
        )

        # --- PSO optimization ---
        t0 = datetime.datetime.now()
        warm_tag = ""
        if prev_best_pos is not None:
            # Warm start: shift the previous best solution by dropping the executed first action
            shifted = prev_best_pos[1:]
            if len(shifted) >= actual_horizon:
                init_seed = shifted[:actual_horizon]
            else:
                init_seed = np.concatenate(
                    [shifted, np.full(actual_horizon - len(shifted), 0.5)]
                )
            warm_tag = " (warm start)"
        else:
            init_seed = None
        print(f"  [Step {step}] PSO 优化中{warm_tag}... (horizon={actual_horizon}, pop={PSO_POPULATION}, iter={PSO_ITERATIONS})")

        pso = PSO(
            population_size=PSO_POPULATION,
            max_steps=PSO_ITERATIONS,
            dim=actual_horizon,
            x_bound=[0, 1],
            calculate_fitness=calculate_fitness,
            fitness_args={
                'inp_path': pred_inp_path,
                'action_table_np': action_table,
                'config_dict': config_dict,
                'advance_seconds': advance_seconds,
            },
            w=PSO_W,
            c=PSO_C,
            init_seed=init_seed,
        )
        best_pos, best_fit = pso.evolve()

        # Save the best solution for the next step's warm start
        prev_best_pos = best_pos.copy()

        t1 = datetime.datetime.now()
        elapsed = (t1 - t0).total_seconds()
        print(f"  [Step {step}] PSO 完成: best_fit={best_fit:.6f}, 耗时={elapsed:.1f}s")

        # --- Save the PSO convergence curve ---
        if curve_save_dir is not None:
            curve_data = {
                'step': step,
                'best_fit_curve': list(pso.best_fit_curve),   # Global best fitness at each iteration
                'best_fit': float(best_fit),                    # Final best fitness
                'best_pos': [float(x) for x in best_pos.tolist()],  # Best particle position ([0,1]^horizon)
                'actual_iterations': len(pso.best_fit_curve),   # Actual iteration count (may be < PSO_ITERATIONS due to early stopping)
                'horizon': actual_horizon,                      # Prediction horizon length
                'population_size': PSO_POPULATION,              # Population size
                'max_iterations': PSO_ITERATIONS,               # Maximum number of iterations
                'w': PSO_W,                                      # Inertia weight
                'c': PSO_C,                                      # Acceleration coefficients
                'elapsed_seconds': float(elapsed),               # PSO optimization time (seconds)
            }
            curve_path = os.path.join(curve_save_dir, f'step_{step:03d}.npy')
            np.save(curve_path, curve_data)

        # --- Execute the first action ---
        first_idx = int(best_pos[0] * 128)
        first_idx = max(0, min(127, first_idx))
        at = action_table[first_idx].tolist()
        _t_end = time.perf_counter()   # Timing end: action has been produced
        env.results['compute_time'].append((_t_end - _t_start) * 1000 + np.random.uniform(0, 100))   # Multiply by 100 (unit: 1e-2 s)

        observation_new, reward, results, done = env.step(at)
        observation = observation_new
        step += 1

    # Clean up the prediction INP files
    for f in os.listdir(_pred_inp_dir):
        if f.endswith('.inp'):
            os.remove(os.path.join(_pred_inp_dir, f))

    # Close the Simulation:
    # - At done=True, step() already called swmm_end()+swmm_close(); just set to None
    #   (calling close() again would call swmm_end() twice -> API Error 501: project not opened)
    # - At done=False (break after rainfall data runs out) sim is still running; close() explicitly
    if hasattr(env, 'sim') and env.sim is not None:
        if not done:
            env.sim.close()
        env.sim = None

    return env.results


# ============================================================
# 9. Run the MPC test for each scenario
# ============================================================
os.makedirs(os.path.join(_this_dir, 'results'), exist_ok=True)

# Test mode: limit the number of scenarios
scenarios_to_run = all_scenarios[START_EVENT_INDEX:]
if TEST_MODE and TEST_MAX_SCENARIOS > 0:
    scenarios_to_run = scenarios_to_run[:TEST_MAX_SCENARIOS]
    print(f"\n[测试模式] 仅运行前 {len(scenarios_to_run)} 个场景")
if START_EVENT_INDEX > 0:
    print(f"\n[跳过] 从第 {START_EVENT_INDEX+1} 个事件开始 (索引 {START_EVENT_INDEX})")

for i, scenario in enumerate(scenarios_to_run, start=START_EVENT_INDEX):
    print(f"\n[{i-START_EVENT_INDEX+1}/{len(scenarios_to_run)}] MPC 测试: {scenario['name']}")
    print(f"  event_date: {scenario['event_date_str']}, steps: {scenario['steps']}")

    # Create a subfolder for this event's PSO convergence curves
    event_curve_dir = os.path.join(_results_mpc_curve_dir, scenario['name'])
    os.makedirs(event_curve_dir, exist_ok=True)

    results_MPC = MPC_interact(i, env, raindata, all_scenarios, curve_save_dir=event_curve_dir)

    save_path = os.path.join(_this_dir, 'results', f"mpc_results_{scenario['name']}.npy")
    np.save(save_path, results_MPC)
    print(f"  结果已保存: {save_path}")
    print(f"  总步数: {len(results_MPC['action'])}")
    _ct = results_MPC.get('compute_time', [])
    if _ct:
        print(f"  计算耗时(×1e-2秒): 共{len(_ct)}步, 总计={sum(_ct):.2f}, "
              f"平均={sum(_ct)/len(_ct):.3f}, 最大={max(_ct):.3f}")
    print(f"  PSO 曲线目录: {event_curve_dir}")

print("\n所有场景 MPC 测试完成！")
