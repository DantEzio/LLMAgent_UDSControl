"""Result visualization (full version): cumulative F+C curves + multi-metric summary table + warning time markers.

Purpose
-------
Compared with ``results_FC.py``, this script also outputs a per-event table of Flooding / CSO /
F+C for each method, and marks the warning levels and cancellation times recorded in warnings.md
with vertical lines on the curves.

Inputs
------
Scenarios/NMC_Events_2015_2025/<event>/*_FULL_SWMM.npy       rainfall series
Scenarios/NMC_Events_2015_2025/<event>/README.md              event start time
Scenarios/NMC_Events_2015_2025/<event>/Event_XX_warnings.md  warning records (optional)
DRL-control/step1-BC-control/results/bc_results_*.npy
DRL-control/step2-MPC-control-best/results/mpc_results_*.npy
DRL-control/step3-BCAgent-control/results/bc_agent_results_*.npy

Outputs
-------
Results/FigControlperformance/FC_curve_vs_rainfall_full.png   cumulative F+C curves
Results/table_FC_NMC_full.csv                                 per-event metrics table

Notes
-----
- ``parse_warnings_file`` depends on ``step3-BCAgent-control/llm_event_agent.py``;
  if that module cannot be imported, warning markers are skipped without affecting the rest of the plot;
- Event selection only requires a BC result to exist.

Usage
-----
    python results_FC_full.py
"""

import sys
import os

# Project root directory
_sys_parent = os.path.dirname(os.path.abspath(__file__))
_drl_control_dir = os.path.join(_sys_parent, 'DRL-control')

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import glob
import re
import datetime
from matplotlib.gridspec import GridSpec
from matplotlib import rcParams

# [FIX] Import the warnings.md parser (to mark real warning events recorded in scenarios)
try:
    from llm_event_agent import parse_warnings_file
except ImportError:
    parse_warnings_file = None

# [UPDATED] Import time parameters from the shared configuration (DRL-control/time_config.py)
_drl_control_root = os.path.join(_sys_parent, 'DRL-control')
if _drl_control_root not in sys.path:
    sys.path.insert(0, _drl_control_root)
from time_config import PRE_HOURS, POST_HOURS, INTERVAL_MIN, compute_sim_start_from_readme

import matplotlib
config = {
    "font.size": 16,
    "mathtext.fontset": 'stix',
    "font.family": 'sans-serif',
    "font.sans-serif": ['Arial', 'DejaVu Sans'],
    'axes.unicode_minus': False
}
rcParams.update(config)

# ============================================================
# 1. Discover all scenarios (from Scenarios/NMC_Events_2015_2025)
# ============================================================
project_root = _sys_parent
scenarios_dir = os.path.join(project_root, 'Scenarios', 'NMC_Events_2015_2025')

# Get scenario folder names from the Scenarios directory
nmc_scenario_names = sorted([
    d for d in os.listdir(scenarios_dir)
    if os.path.isdir(os.path.join(scenarios_dir, d))
])

# Get scenario names from BC results and keep only those present in the NMC directory
bc_results_dir = os.path.join(project_root, 'DRL-control', 'step1-BC-control', 'results')
bc_scenario_files = sorted(glob.glob(os.path.join(bc_results_dir, 'bc_results_*.npy')))
scenario_names = []
for f in bc_scenario_files:
    basename = os.path.basename(f)
    # bc_results_<event>.npy -> <event>
    name = basename.replace('bc_results_', '').replace('.npy', '')
    # Keep only scenarios present in the NMC_Events_2015_2025 directory
    if name in nmc_scenario_names:
        scenario_names.append(name)

print(f"NMC目录下共 {len(nmc_scenario_names)} 个场景文件夹")
print(f"其中 {len(scenario_names)} 个场景有 BC 结果:")
for s in scenario_names:
    print(f"  {s}")



# ============================================================
# 2. Load scenario rainfall data (from Scenarios/NMC_Events_2015_2025)
#    New format: _SWMM.npy, shape=(72,2) -> [elapsed_hours, mm/hr]
#    Convert to mm/5min (mm/hr / 12)
# ============================================================
scenario_rain = {}  # {scenario_name: rain_array (hours*12,), unit: mm/5min} (kept for FC alignment)
scenario_rain_raw = {}  # {scenario_name: (times_list, mm_per_hr_array)} raw rainfall data (for plotting, same as rainfall event)
scenario_sim_start = {}  # {scenario_name: datetime} simulation start time
for folder_name in scenario_names:
    folder_path = os.path.join(scenarios_dir, folder_name)
    # [UPDATED] Prefer *_FULL_SWMM.npy (complete pre+rain+post window)
    full_npy_files = glob.glob(os.path.join(folder_path, '*_FULL_SWMM.npy'))
    orig_npy_files = [f for f in glob.glob(os.path.join(folder_path, '*_SWMM.npy'))
                      if not f.endswith('_FULL_SWMM.npy')]
    npy_files = full_npy_files if full_npy_files else orig_npy_files

    # [FIX] Parse the real data start from the README "data window" to compute the simulation start
    # (row 0 of the raw data = data window start; row 0 of FULL data = data window start - PRE_HOURS)
    # Fallback: event_date 08:00 - PRE_HOURS (legacy logic)
    readme_path = os.path.join(folder_path, 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            readme_content = f.read()
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', readme_content)
        event_date_str = date_match.group(1) if date_match else ''
        scenario_sim_start[folder_name] = compute_sim_start_from_readme(
            readme_content, event_date_str)

    if npy_files:
        swmm_data = np.load(npy_files[0])  # shape (N,2): [elapsed_hours, mm/hr]
        if swmm_data.ndim < 2 or swmm_data.shape[0] == 0:
            print(f"  警告: {folder_name} 降雨数据为空")
            scenario_rain[folder_name] = np.array([])
            scenario_rain_raw[folder_name] = ([], np.array([]))
            continue
        # Convert mm/hr to mm/5min: distribute each hour evenly over 12 five-minute steps
        # [FIX] Compute hours directly from the array row count, consistent with the three main files
        hours = swmm_data.shape[0]
        rain_array = np.zeros(hours * 12)
        for j in range(len(swmm_data)):
            mm_per_5min = swmm_data[j, 1] / 12.0
            rain_array[j * 12:(j + 1) * 12] = mm_per_5min
        scenario_rain[folder_name] = rain_array
        
        # [NEW] Keep the raw mm/hr data (identical to results_rainfall_event.py)
        elapsed_hours = swmm_data[:, 0]
        mm_per_hr = swmm_data[:, 1]
        times_raw = [scenario_sim_start.get(folder_name, datetime.datetime(2020, 1, 1, 2, 0, 0)) + datetime.timedelta(hours=float(h)) for h in elapsed_hours]
        scenario_rain_raw[folder_name] = (times_raw, mm_per_hr)
    else:
        print(f"  警告: 未找到 {folder_name} 的降雨数据 (_SWMM.npy)")
        scenario_rain[folder_name] = np.array([])
        scenario_rain_raw[folder_name] = ([], np.array([]))

# ============================================================
# 3. Load BC, MPC and AgenticAI-BC (rule control + LLM event-driven adjustment) results
# ============================================================
results_BC = {}
results_MPC = {}
results_BCAgent_Agentic = {}

for name in scenario_names:
    bc_path = os.path.join(project_root, 'DRL-control', 'step1-BC-control', 'results', f'bc_results_{name}.npy')
    mpc_path = os.path.join(project_root, 'DRL-control', 'step2-MPC-control-best', 'results', f'mpc_results_{name}.npy')
    bcagent_agentic_path = os.path.join(project_root, 'DRL-control', 'step3-BCAgent-control', 'results', f'bc_agent_results_{name}.npy')

    if os.path.exists(bc_path):
        results_BC[name] = np.load(bc_path, allow_pickle=True).tolist()
    else:
        print(f"  警告: 未找到 BC 结果: {bc_path}")

    if os.path.exists(mpc_path):
        results_MPC[name] = np.load(mpc_path, allow_pickle=True).tolist()
    else:
        print(f"  警告: 未找到 MPC 结果: {mpc_path}")

    if os.path.exists(bcagent_agentic_path):
        results_BCAgent_Agentic[name] = np.load(bcagent_agentic_path, allow_pickle=True).tolist()
    else:
        print(f"  警告: 未找到 AgenticAI-BC 结果: {bcagent_agentic_path}")

# ============================================================
# 4. Output the Flooding + CSO summary table
# ============================================================
print("\n" + "=" * 80)
print("表: Flooding + CSO 结果汇总")
print("=" * 80)

table_data = {
    'Scenario': [],
    'BC_Flooding': [],
    'BC_CSO': [],
    'BC_F+C': [],
    'MPC_Flooding': [],      # MPC (PSO + SWMM predictive receding-horizon control)
    'MPC_CSO': [],
    'MPC_F+C': [],
    'MPCvBC_Improve': [],
    'BCAg_Flooding': [],     # AgenticAI-BC
    'BCAg_CSO': [],
    'BCAg_F+C': [],
    'BCAgvBC_Improve': [],
    'BCAgvMPC_Improve': [],
}

for name in scenario_names:
    if name not in results_BC:
        continue

    bc_flood = results_BC[name]['flooding'][-1]
    bc_cso = results_BC[name]['CSO'][-1]
    bc_fc = bc_flood + bc_cso

    # MPC (PSO + SWMM predictive receding-horizon control)
    has_mpc = name in results_MPC
    if has_mpc:
        mpc_flood = results_MPC[name]['flooding'][-1]
        mpc_cso = results_MPC[name]['CSO'][-1]
        mpc_fc = mpc_flood + mpc_cso
        imp_mpc_vs_bc = (bc_fc - mpc_fc) / bc_fc * 100 if bc_fc > 0 else 0
    else:
        mpc_flood = float('nan')
        mpc_cso = float('nan')
        mpc_fc = float('nan')
        imp_mpc_vs_bc = float('nan')

    # BC + AgenticAI (AgenticAI-BC: rule control + LLM event-driven adjustment)
    has_bcagent = name in results_BCAgent_Agentic
    if has_bcagent:
        bcag_flood = results_BCAgent_Agentic[name]['flooding'][-1]
        bcag_cso = results_BCAgent_Agentic[name]['CSO'][-1]
        bcag_fc = bcag_flood + bcag_cso
        imp_bcag_vs_bc = (bc_fc - bcag_fc) / bc_fc * 100 if bc_fc > 0 else 0
        imp_bcag_vs_mpc = (mpc_fc - bcag_fc) / mpc_fc * 100 if (not np.isnan(mpc_fc) and mpc_fc > 0) else float('nan')
    else:
        bcag_flood = float('nan')
        bcag_cso = float('nan')
        bcag_fc = float('nan')
        imp_bcag_vs_bc = float('nan')
        imp_bcag_vs_mpc = float('nan')

    table_data['Scenario'].append(name)
    table_data['BC_Flooding'].append(bc_flood)
    table_data['BC_CSO'].append(bc_cso)
    table_data['BC_F+C'].append(bc_fc)
    table_data['MPC_Flooding'].append(mpc_flood)
    table_data['MPC_CSO'].append(mpc_cso)
    table_data['MPC_F+C'].append(mpc_fc)
    table_data['MPCvBC_Improve'].append(imp_mpc_vs_bc)
    table_data['BCAg_Flooding'].append(bcag_flood)
    table_data['BCAg_CSO'].append(bcag_cso)
    table_data['BCAg_F+C'].append(bcag_fc)
    table_data['BCAgvBC_Improve'].append(imp_bcag_vs_bc)
    table_data['BCAgvMPC_Improve'].append(imp_bcag_vs_mpc)

df_table = pd.DataFrame(table_data)
print(df_table.to_string(index=False, float_format=lambda x: f'{x:.2f}'))

# Output the averages
print("\n--- 平均值 ---")
bc_f_avg = np.mean(table_data['BC_Flooding'])
bc_c_avg = np.mean(table_data['BC_CSO'])
bc_fc_avg = np.mean(table_data['BC_F+C'])

print(f"BC         Flooding: {bc_f_avg:.2f}, CSO: {bc_c_avg:.2f}, F+C: {bc_fc_avg:.2f}")

# MPC average
mpc_f_vals = [v for v in table_data['MPC_Flooding'] if not np.isnan(v)]
mpc_c_vals = [v for v in table_data['MPC_CSO'] if not np.isnan(v)]
mpc_fc_vals = [v for v in table_data['MPC_F+C'] if not np.isnan(v)]
mpc_vs_bc_vals = [v for v in table_data['MPCvBC_Improve'] if not np.isnan(v)]

if mpc_fc_vals:
    print(f"MPC          Flooding: {np.mean(mpc_f_vals):.2f}, CSO: {np.mean(mpc_c_vals):.2f}, F+C: {np.mean(mpc_fc_vals):.2f}")
    print(f"MPC vs BC  改善率: {np.mean(mpc_vs_bc_vals):.2f}%")

# AgenticAI-BC average
bcag_f_vals = [v for v in table_data['BCAg_Flooding'] if not np.isnan(v)]
bcag_c_vals = [v for v in table_data['BCAg_CSO'] if not np.isnan(v)]
bcag_fc_vals = [v for v in table_data['BCAg_F+C'] if not np.isnan(v)]
bcag_vs_bc_vals = [v for v in table_data['BCAgvBC_Improve'] if not np.isnan(v)]
bcag_vs_mpc_vals = [v for v in table_data['BCAgvMPC_Improve'] if not np.isnan(v)]

if bcag_fc_vals:
    print(f"AgenticAI-BC  Flooding: {np.mean(bcag_f_vals):.2f}, CSO: {np.mean(bcag_c_vals):.2f}, F+C: {np.mean(bcag_fc_vals):.2f}")
    print(f"AgenticAI-BC vs BC  改善率: {np.mean(bcag_vs_bc_vals):.2f}%")
    if bcag_vs_mpc_vals:
        print(f"AgenticAI-BC vs MPC 改善率: {np.mean(bcag_vs_mpc_vals):.2f}%")

# Save the CSV to the Results folder
results_dir = os.path.join(project_root, 'Results')
os.makedirs(results_dir, exist_ok=True)
df_table.to_csv(os.path.join(results_dir, 'table_FC_NMC_full.csv'), index=False)
print(f"\n表格已保存: {os.path.join(results_dir, 'table_FC_NMC_full.csv')}")



# ============================================================
# 6. F+C curve vs rainfall (per scenario)
#    Layout: 5 rows x 2 columns, rainfall data drawn at the top
# ============================================================
print("\n生成 F+C 曲线 vs 降雨...")

ccf = {
    'BC': "#8b0000",      # Dark red (BC)
    'MPC': "#b8860b",     # Dark gold (PSO + SWMM predictive receding-horizon control)
    'AgenticAI-BC': "#2e7d32",  # Dark green (BC rule control + LLM event-driven, DeepSeek)
}

# Warning level colors (identical to results_rainfall_event.py)
WARNING_COLORS = {
    '蓝色': '#1f77b4',
    '黄色': '#ff8c00',
    '橙色': '#ff4500',
    '红色': '#d62728',
    '应急响应': '#9467bd',
    '解除': '#999999',
    '未知': '#333333',
}

WARNING_LEVEL_LABELS = {
    '蓝色': 'Blue',
    '黄色': 'Yellow',
    '橙色': 'Orange',
    '红色': 'Red',
    '应急响应': 'Emergency',
    '解除': 'Cancelled',
    '未知': 'Unknown',
}

# Keep only scenarios with BC results (at most 10 for plotting)
valid_scenario_names = [n for n in scenario_names if n in results_BC][:10]

# Track which warning levels appear (for global legend)
all_warning_levels_seen = set()

n_cols = 2
n_rows = max(1, (len(valid_scenario_names) + n_cols - 1) // n_cols)
# Use at most 5 rows
n_rows = min(5, n_rows)

fig = plt.figure(dpi=150, figsize=(12, 2.8 * n_rows))
gs = GridSpec(n_rows, n_cols, figure=fig, hspace=0.4, wspace=0.5)

pre_steps = PRE_HOURS * 60 // 5   # 72 steps
post_steps = POST_HOURS * 60 // 5  # 216 steps

for idx, name in enumerate(valid_scenario_names):
    row = idx // n_cols
    col = idx % n_cols
    ax = fig.add_subplot(gs[row, col])

    rain = scenario_rain.get(name, np.array([]))
    sim_start = scenario_sim_start.get(name)
    if sim_start is None:
        sim_start = datetime.datetime(2020, 1, 1, 2, 0, 0)

    # F+C curve (compute first)
    bc_fc_raw = np.array(results_BC[name]['flooding'][1:]) + np.array(results_BC[name]['CSO'][1:])

    # Use the actual FC data length as the common reference
    fc_data_len = len(bc_fc_raw)

    # Align rainfall data to the FC length
    if len(rain) > 0:
        rain_aligned = rain[:fc_data_len] if len(rain) >= fc_data_len else \
            np.pad(rain, (0, fc_data_len - len(rain)))
    else:
        rain_aligned = np.zeros(fc_data_len)

    # Build the time axis (aggregate every 5 steps)
    fc_plot_idx = np.arange(0, fc_data_len, 5)
    n_agg = len(fc_plot_idx)
    dt_agg = [sim_start + datetime.timedelta(minutes=5 * 5 * i) for i in range(n_agg)]

    bc_fc = bc_fc_raw[fc_plot_idx] / 1000  # Convert to 10^3 m^3

    # Compute the final F+C values
    bc_final = bc_fc[-1]

    # ---- Rainfall bars (right axis, same as results_rainfall_event.py: mm/hr) ----
    ax_rain = ax.twinx()
    # Axis z-order: keep main-axis elements (curves/legend) above the rainfall bars on the twin axis
    ax_rain.set_zorder(0)
    ax.set_zorder(1)
    ax.patch.set_visible(False)  # Hide the main axis background, otherwise it covers the rainfall bars
    rain_raw = scenario_rain_raw.get(name, ([], np.array([])))
    times_raw, mm_per_hr = rain_raw
    if len(mm_per_hr) > 0:
        bar_width = 1 / 24  # 1-hour bar width (in days, same as rainfall event)
        ax_rain.bar(times_raw, mm_per_hr, width=bar_width, color='steelblue',
                   edgecolor='navy', linewidth=0.3, alpha=0.4, zorder=1)
        ax_rain.set_ylabel('Rainfall\nintensity (mm/h)', fontsize=14, color='black')
        ax_rain.tick_params(axis='y', labelcolor='black', labelsize=13)
        # Invert the Y axis: 0 at the top, larger values downward
        ax_rain.invert_yaxis()
        # Y range (same as rainfall event: max*1.45, but inverted)
        y_max_rain = mm_per_hr.max() if mm_per_hr.max() > 0 else 10
        ax_rain.set_ylim(y_max_rain * 1.45, 0)  # 0 at the top, 1.45 times the maximum at the bottom

    ax.set_xlim(dt_agg[0] - datetime.timedelta(hours=1),
                dt_agg[-1] + datetime.timedelta(hours=1))

    # Show only the first, middle and last time ticks
    n_ticks = len(dt_agg)
    tick_positions = [0, n_ticks // 2, n_ticks - 1]
    ax.set_xticks([dt_agg[i] for i in tick_positions])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))

    # Y axis labels (left axis: F+C)
    ax.set_ylabel('Flooding and CSO\n(10³ m³)', fontsize=15)
    ax.tick_params(axis='both', labelsize=14)

    # ---- Plot the F+C curves ----
    # BC curve
    ax.plot(dt_agg, bc_fc, color=ccf['BC'], alpha=0.4, linewidth=2.0, zorder=5)

    # MPC curve (if available)
    has_mpc = name in results_MPC
    if has_mpc:
        mpc_fc_raw = np.array(results_MPC[name]['flooding'][1:]) + np.array(results_MPC[name]['CSO'][1:])
        mpc_fc = mpc_fc_raw[fc_plot_idx] / 1000
        ax.plot(dt_agg, mpc_fc, color=ccf['MPC'], alpha=0.7, linewidth=2.0, linestyle=':', zorder=5)

    # AgenticAI-BC curve (if available)
    has_bcagent = name in results_BCAgent_Agentic
    if has_bcagent:
        bcag_fc_raw = np.array(results_BCAgent_Agentic[name]['flooding'][1:]) + np.array(results_BCAgent_Agentic[name]['CSO'][1:])
        bcag_fc = bcag_fc_raw[fc_plot_idx] / 1000
        ax.plot(dt_agg, bcag_fc, color=ccf['AgenticAI-BC'], alpha=0.6, linewidth=2.0, linestyle='--', zorder=5)

    # ---- LLM Event vertical lines (as in results_rainfall_event.py: track level + mark cancellations) ----
    if parse_warnings_file is not None:
        warnings_md_candidates = glob.glob(os.path.join(scenarios_dir, name, '*_warnings.md'))
        if warnings_md_candidates:
            parsed_warnings = parse_warnings_file(warnings_md_candidates[0])
            if parsed_warnings and parsed_warnings.records:
                for rec in parsed_warnings.records:
                    level_str = rec.level.value if hasattr(rec.level, 'value') else '未知'
                    color = WARNING_COLORS.get(level_str, '#333333')
                    all_warning_levels_seen.add(level_str)
                    is_cancelled = rec.is_cancelled
                    linestyle = ':' if is_cancelled else '--'
                    ax.axvline(x=rec.publish_time, color=color,
                              linestyle=linestyle, linewidth=1.5, alpha=0.8)

    # (legend moved outside the axes and drawn uniformly with fig.legend below)

    # Title (Event1, Event2, ...)
    short_title = f'Event{idx + 1}'
    ax.set_title(short_title, fontsize=16)

# ---- Uniform legend below the whole figure (curves + risk levels) ----
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
unified_handles = [
    Line2D([0], [0], color=ccf['BC'], linewidth=2.5, label='BC'),
]

# Check whether any subplot contains MPC data
any_mpc = any(name in results_MPC for name in valid_scenario_names)
if any_mpc:
    unified_handles.append(
        Line2D([0], [0], color=ccf['MPC'], linewidth=2.5,
               linestyle=':', label='MPC')
    )

# Check whether any subplot contains AgenticAI-BC data
any_bcagent = any(name in results_BCAgent_Agentic for name in valid_scenario_names)
if any_bcagent:
    unified_handles.append(
        Line2D([0], [0], color=ccf['AgenticAI-BC'], linewidth=2.5,
               linestyle='--', label='AgenticAI-Control')
    )

# Rainfall bar legend (added last)
unified_handles.append(
    Patch(facecolor='steelblue', edgecolor='navy', linewidth=0.3, alpha=0.4, label='Rainfall')
)

fig.legend(handles=unified_handles, fontsize=18, loc='lower center',
            ncol=len(unified_handles), frameon=True, fancybox=True, framealpha=0.95,
            bbox_to_anchor=(0.5, 0.0))

# Tighten the bottom margin to bring the legend closer to the plots
fig.subplots_adjust(bottom=0.07)

# Save the figure to Results/FigControlperformance
fig_dir = os.path.join(project_root, 'Results', 'FigControlperformance')
os.makedirs(fig_dir, exist_ok=True)
out_fig_path = os.path.join(fig_dir, 'FC_curve_vs_rainfall_full.png')
plt.savefig(out_fig_path, dpi=200, bbox_inches='tight')
print(f"F+C 曲线图已保存: {out_fig_path}")
plt.close()



print("\n所有分析和图表生成完成！")


