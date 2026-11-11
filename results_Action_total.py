# -*- coding: utf-8 -*-
"""
Compare the total number of pumps on over each rainfall event for three methods:
BC, Agent (DeepSeek) and MPC (perfect).

Layout: 5 rows x 2 columns, one subplot per rainfall event (cf. results_FC_full.py).
Each subplot:
  - Rainfall bars (inverted right axis, alpha=0.4)
  - Stair curves of total pumps on for the three methods (left axis, 0~7)
A single shared legend is placed at the bottom.

Output: Results/FigAction/FigAction.png

Methods:
  - step1-BC-control             -> BC
  - step3-BCAgent-control        -> Agent (DeepSeek)
  - step2-MPC-control-best       -> MPC (perfect rainfall forecast)

Usage:
    python results_Action_total.py
"""

import sys
import os

_sys_parent = os.path.dirname(os.path.abspath(__file__))
_drl_control_dir = os.path.join(_sys_parent, 'DRL-control')

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import glob
import re
import datetime
from matplotlib.gridspec import GridSpec
from matplotlib import rcParams
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# Import time parameters from the shared configuration
_drl_control_root = os.path.join(_sys_parent, 'DRL-control')
if _drl_control_root not in sys.path:
    sys.path.insert(0, _drl_control_root)
from time_config import PRE_HOURS, POST_HOURS, INTERVAL_MIN, compute_sim_start_from_readme

config = {
    "font.size": 16,
    "mathtext.fontset": 'stix',
    "font.family": 'sans-serif',
    "font.sans-serif": ['Arial', 'DejaVu Sans', 'Microsoft YaHei', 'SimHei'],
    'axes.unicode_minus': False
}
rcParams.update(config)

# ============================================================
# Method config: name -> (directory, result file prefix, action field, display label)
# ============================================================
METHODS = {
    'BC':    ('step1-BC-control',       'bc_results_',       'action',           'BC'),
    'Agent': ('step3-BCAgent-control',  'bc_agent_results_', 'adjusted_actions', 'AgenticAI-Control'),
    'MPC':   ('step2-MPC-control-best', 'mpc_results_',      'action',           'MPC'),
}

# Pump count (7 units: CC-S1/S2/R1/R2, JK-S/R1/R2), binary 0/1 -> sum 0~7
NUM_PUMPS = 7

# Color configuration (same style as results_FC_full.py / results_varLLM.py)
COLORS = {
    'BC':    '#8b0000',   # Dark red
    'Agent': '#2e7d32',   # Dark green (AgenticAI-Control, DeepSeek)
    'MPC':   '#b8860b',   # Dark gold (perfect forecast)
}

# Line styles (BC solid, the other two methods dashed)
LINESTYLES = {
    'BC':    '-',
    'Agent': '--',
    'MPC':   '--',
}

# Drawing order (later on top): bottom -> top
PLOT_ORDER = ['MPC', 'BC', 'Agent']

# Legend order (same as results_FC_full.py)
LEGEND_ORDER = ['BC', 'MPC', 'Agent']

project_root = _sys_parent
scenarios_dir = os.path.join(project_root, 'Scenarios', 'NMC_Events_2015_2025')

# ============================================================
# 1. Discover all scenarios (same as results_varLLM.py)
# ============================================================
nmc_scenario_names = sorted([
    d for d in os.listdir(scenarios_dir)
    if os.path.isdir(os.path.join(scenarios_dir, d))
])

bc_results_dir = os.path.join(project_root, 'DRL-control', 'step1-BC-control', 'results')
bc_scenario_files = sorted(glob.glob(os.path.join(bc_results_dir, 'bc_results_*.npy')))
scenario_names = []
for f in bc_scenario_files:
    basename = os.path.basename(f)
    name = basename.replace('bc_results_', '').replace('.npy', '')
    if name in nmc_scenario_names:
        scenario_names.append(name)

print(f"共 {len(scenario_names)} 个场景")
print(f"方法: {list(METHODS.keys())}")

# ============================================================
# 2. Load scenario sim_start and rainfall data (for the time axis and right-axis rainfall bars)
# ============================================================
scenario_sim_start = {}
scenario_rain_raw = {}   # {scenario_name: (times_list, mm_per_hr_array)}

for folder_name in scenario_names:
    folder_path = os.path.join(scenarios_dir, folder_name)
    readme_path = os.path.join(folder_path, 'README.md')
    sim_start_val = None
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            readme_content = f.read()
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', readme_content)
        event_date_str = date_match.group(1) if date_match else ''
        sim_start_val = compute_sim_start_from_readme(readme_content, event_date_str)
        scenario_sim_start[folder_name] = sim_start_val

    # Load rainfall data (prefer *_FULL_SWMM.npy, same as results_FC_full.py)
    full_npy_files = glob.glob(os.path.join(folder_path, '*_FULL_SWMM.npy'))
    orig_npy_files = [f for f in glob.glob(os.path.join(folder_path, '*_SWMM.npy'))
                      if not f.endswith('_FULL_SWMM.npy')]
    npy_files = full_npy_files if full_npy_files else orig_npy_files
    if npy_files and sim_start_val is not None:
        swmm_data = np.load(npy_files[0])
        if swmm_data.ndim >= 2 and swmm_data.shape[0] > 0:
            elapsed_hours = swmm_data[:, 0]
            mm_per_hr = swmm_data[:, 1]
            times_raw = [sim_start_val + datetime.timedelta(hours=float(h))
                         for h in elapsed_hours]
            scenario_rain_raw[folder_name] = (times_raw, mm_per_hr)
            continue
    scenario_rain_raw[folder_name] = ([], np.array([]))

# ============================================================
# 3. Load results for all methods
# ============================================================
results_methods = {}   # {method_label: {scenario_name: result_dict}}

for method_label, (dir_name, file_prefix, _action_key, _display_label) in METHODS.items():
    results_methods[method_label] = {}
    for name in scenario_names:
        m_path = os.path.join(project_root, 'DRL-control', dir_name,
                              'results', f'{file_prefix}{name}.npy')
        if os.path.exists(m_path):
            results_methods[method_label][name] = np.load(m_path, allow_pickle=True).tolist()
        else:
            print(f"  警告: 未找到 {method_label} 结果: {m_path}")

# ============================================================
# 4. Plot: 5 rows x 2 columns, one subplot per rainfall event (cf. results_FC_full.py)
#    Each subplot: rainfall bars (inverted right axis) + stair curves of total pumps on (left axis)
#    A single shared legend is placed at the bottom of the figure
# ============================================================
print("\n生成 [BC vs Agent(DeepSeek) vs MPC(perfect)] 开启泵总数量曲线 (5行2列)...")

dt_delta = datetime.timedelta(minutes=INTERVAL_MIN)
n_cols = 2
# At most 5 rows x 2 columns -> at most 10 subplots
n_rows = min(5, max(1, (len(scenario_names) + n_cols - 1) // n_cols))

fig = plt.figure(dpi=150, figsize=(13, 2.9 * n_rows))
gs = GridSpec(n_rows, n_cols, figure=fig, hspace=0.45, wspace=0.45)
gs.update(top=0.95, bottom=0.075)

# Take scenarios with data, up to n_rows*n_cols
valid_scenarios = [n for n in scenario_names
                   if any(n in results_methods[m] for m in METHODS)][:n_rows * n_cols]

for idx, name in enumerate(valid_scenarios):
    row = idx // n_cols
    col = idx % n_cols
    ax = fig.add_subplot(gs[row, col])

    sim_start = scenario_sim_start.get(name, datetime.datetime(2020, 1, 1, 2, 0, 0))

    # Collect each method's action -> total pumps on (sum of 7 binary pumps)
    method_data = {}
    max_len = 0
    for method_label in METHODS:
        if name not in results_methods[method_label]:
            continue
        res = results_methods[method_label][name]
        action_key = METHODS[method_label][2]
        actions = res.get(action_key, [])
        if not actions:
            continue
        action_arr = np.array(actions)  # shape (T, 7)
        if action_arr.ndim != 2 or action_arr.shape[1] == 0:
            continue
        # Sum the 7 pump states at each step -> total pumps on (0~7)
        pump_count = action_arr.sum(axis=1).astype(int)  # shape (T,)
        method_data[method_label] = {
            'pump_count': pump_count,
            'n_steps': action_arr.shape[0],
        }
        if action_arr.shape[0] > max_len:
            max_len = action_arr.shape[0]

    if max_len == 0:
        ax.set_title(f'Event{idx + 1}', fontsize=16)
        print(f"  跳过 {name}: action 数据为空")
        continue

    # Time axis (5 minutes per step)
    time_axis = [sim_start + dt_delta * i for i in range(max_len)]
    _rain_times, _rain_vals = scenario_rain_raw.get(name, ([], np.array([])))
    tick_idx = [0, max_len // 2, max_len - 1]
    tick_times = [time_axis[i] for i in tick_idx]
    x_lo = time_axis[0] - datetime.timedelta(minutes=10)
    x_hi = time_axis[-1] + datetime.timedelta(minutes=10)

    # ---- Rainfall bars (right axis, inverted, cf. results_FC_full.py) ----
    ax_rain = ax.twinx()
    ax_rain.set_zorder(0)
    ax.set_zorder(1)
    ax.patch.set_visible(False)  # Hide the main axis background so the rainfall bars show through
    if len(_rain_vals) > 0:
        bar_width = 1 / 24  # 1-hour width (in days)
        ax_rain.bar(_rain_times, _rain_vals, width=bar_width, color='steelblue',
                    edgecolor='navy', linewidth=0.3, alpha=0.4, zorder=1)
        ax_rain.set_ylabel('Rainfall intensity (mm/h)', fontsize=12, color='black')
        ax_rain.tick_params(axis='y', labelcolor='black', labelsize=11)
        ax_rain.invert_yaxis()
        _y_max_rain = _rain_vals.max() if _rain_vals.max() > 0 else 10
        ax_rain.set_ylim(_y_max_rain * 2.0, 0)
        # Set right-axis ticks explicitly (avoid confusion with the left 0~7 pump-count axis)
        ax_rain.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5, integer=True))
    ax_rain.set_xlim(x_lo, x_hi)

    # ---- Stair curves of total pumps on per method (left axis) ----
    for method_label in PLOT_ORDER:
        md = method_data.get(method_label)
        if md is None:
            continue
        pump_count = md['pump_count']
        n = md['n_steps']
        t_count = time_axis[:n]
        display_label = METHODS[method_label][3]
        ax.step(t_count, pump_count, where='post',
                color=COLORS[method_label], linestyle=LINESTYLES[method_label],
                linewidth=1.8, alpha=0.9, zorder=3, label=display_label)

    ax.set_ylim(-0.5, NUM_PUMPS + 0.5)
    ax.set_yticks(range(0, NUM_PUMPS + 1))
    ax.set_ylabel('Pumps ON', fontsize=13)
    ax.tick_params(axis='both', labelsize=11)
    ax.set_xlim(x_lo, x_hi)
    ax.set_xticks(tick_times)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    ax.grid(True, axis='y', alpha=0.3, linestyle='--', zorder=0)
    ax.set_title(f'Event{idx + 1}', fontsize=16)

# ---- Shared legend at the bottom (curves + rainfall), order: BC, MPC, Agent, Rainfall ----
unified_handles = []
for method_label in LEGEND_ORDER:
    unified_handles.append(
        Line2D([0], [0], color=COLORS[method_label],
               linestyle=LINESTYLES[method_label],
               linewidth=2.5, label=METHODS[method_label][3])
    )
unified_handles.append(
    Patch(facecolor='steelblue', edgecolor='navy', linewidth=0.3,
          alpha=0.4, label='Rainfall')
)

fig.legend(handles=unified_handles, fontsize=16, loc='lower center',
           ncol=len(unified_handles), frameon=True, fancybox=True,
           framealpha=0.95, bbox_to_anchor=(0.5, 0.015))

# Tighten the bottom margin to bring the legend closer to the plots
fig.subplots_adjust(bottom=0.075)

# Save to Results/FigPerformanceAction/FigAction/FigAction.png
fig_dir = os.path.join(project_root, 'Results', 'FigPerformanceAction', 'FigAction')
os.makedirs(fig_dir, exist_ok=True)
out_path = os.path.join(fig_dir, 'FigAction.png')
plt.savefig(out_path, dpi=200, bbox_inches='tight')
plt.close(fig)
print(f"已保存: {out_path}")

print("\n所有开启泵总数量曲线生成完成！")
print(f"输出根目录: {fig_dir}")
