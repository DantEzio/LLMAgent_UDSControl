# -*- coding: utf-8 -*-
"""
两张 5行2列 合并图 (Event 1-10):

  图1: 全部 Flooding and CSO 结果 (每子图一场降雨, FC 曲线 + 降雨柱)
  图2: 全部控制曲线结果 (每子图一场降雨, 开启泵总数量阶梯曲线 + 降雨柱)

数据源 / 图例 (不变):
  - BC              #8b0000   (step1-BC-control)
  - Limited MPC     #b8860b   (MPC, step2-MPC-control-usefull)
  - AgenticAI-Control #2e7d32  (Agent, step3-BCAgent-control, DeepSeek)
  - Rainfall         steelblue/navy (alpha 0.4)

输出:
  - Results/FigPerformanceAction/FC_E1-10.png     (图1)
  - Results/FigPerformanceAction/Action_E1-10.png (图2)

用法:
    python results_FC_Action_per_event_S11.py
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

# 从统一配置导入时间参数
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
# 颜色 (与 results_FC_full.py ccf / results_Action_total.py COLORS 一致)
# ============================================================
ccf = {
    'BC':         "#8b0000",   # 深红
    'MPC':        "#b8860b",   # 暗金 (perfect 预测)
    'Agent':      "#2e7d32",   # 深绿 (AgenticAI-Control, DeepSeek)
}

# 线型 (BC 实线, 其余两个控制方法虚线) —— 两列统一, 全图单图例
FC_LINESTYLES  = {'BC': '-', 'MPC': '--', 'Agent': '--'}
FC_ALPHA        = {'BC': 0.4, 'MPC': 0.7, 'Agent': 0.6}

ACT_LINESTYLES = {'BC': '-', 'MPC': '--', 'Agent': '--'}

# 泵数量 (7台, 二进制 0/1 -> 总和 0~7)
NUM_PUMPS = 7

# 方法结果路径配置: 标签 -> (目录, 结果前缀, action 字段名)
METHOD_PATHS = {
    'BC':    ('step1-BC-control',       'bc_results_',       'action'),
    'Agent': ('step3-BCAgent-control',  'bc_agent_results_', 'adjusted_actions'),
    'MPC':   ('step2-MPC-control-usefull', 'mpc_results_',      'action'),
}

# ============================================================
# 1. 发现场景 (取 Event 1-10)
# ============================================================
project_root = _sys_parent
scenarios_dir = os.path.join(project_root, 'Scenarios', 'NMC_Events_2015_2025')

nmc_scenario_names = sorted([
    d for d in os.listdir(scenarios_dir)
    if os.path.isdir(os.path.join(scenarios_dir, d))
])

bc_results_dir = os.path.join(project_root, 'DRL-control', 'step1-BC-control', 'results')
bc_scenario_files = sorted(glob.glob(os.path.join(bc_results_dir, 'bc_results_*.npy')))
scenario_names_all = []
for f in bc_scenario_files:
    basename = os.path.basename(f)
    name = basename.replace('bc_results_', '').replace('.npy', '')
    if name in nmc_scenario_names:
        scenario_names_all.append(name)

# 取前 10 场 (Event 1-10)
N_EVENTS = 10
scenario_names = scenario_names_all[:N_EVENTS]
print(f"共选取 {len(scenario_names)} 场降雨 (Event 1-{N_EVENTS}):")
for s in scenario_names:
    print(f"  {s}")

# ============================================================
# 2. 加载 sim_start 与降雨数据 (与 results_FC_full.py 一致)
# ============================================================
scenario_sim_start = {}
scenario_rain_raw = {}   # {name: (times_list, mm_per_hr_array)}

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
# 3. 加载 BC / Agent / MPC 结果 (含 flooding/CSO 与 action)
# ============================================================
results = {}   # {method_label: {scenario_name: result_dict}}
for method_label, (dir_name, file_prefix, _action_key) in METHOD_PATHS.items():
    results[method_label] = {}
    for name in scenario_names:
        m_path = os.path.join(project_root, 'DRL-control', dir_name,
                              'results', f'{file_prefix}{name}.npy')
        if os.path.exists(m_path):
            results[method_label][name] = np.load(m_path, allow_pickle=True).tolist()
        else:
            print(f"  警告: 未找到 {method_label} 结果: {m_path}")

# ============================================================
# 4. 绘制两张 5行2列 组合图 (Event 1-10):
#    图1: 全部 Flooding and CSO 结果;  图2: 全部控制曲线结果
#    数据源与图例不变
# ============================================================
print("\n生成两张 5x2 组合图 (图1: Flooding & CSO, 图2: 控制曲线), Event 1-10...")

dt_delta = datetime.timedelta(minutes=INTERVAL_MIN)  # 5 分钟


def _draw_rain(ax, rain_times, rain_vals):
    """降雨柱状图 (右轴倒置), 与 results_FC_full.py 一致 (max*1.45)。"""
    ax_rain = ax.twinx()
    ax_rain.set_zorder(0)
    ax.set_zorder(1)
    ax.patch.set_visible(False)
    if len(rain_vals) > 0:
        bar_width = 1 / 24  # 1 小时 (以天为单位)
        ax_rain.bar(rain_times, rain_vals, width=bar_width, color='steelblue',
                    edgecolor='navy', linewidth=0.3, alpha=0.4, zorder=1)
        ax_rain.set_ylabel('Rainfall intensity (mm/h)', fontsize=12, color='black')
        ax_rain.tick_params(axis='y', labelcolor='black', labelsize=11)
        ax_rain.invert_yaxis()
        y_max_rain = rain_vals.max() if rain_vals.max() > 0 else 10
        ax_rain.set_ylim(y_max_rain * 1.45, 0)
        ax_rain.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5, integer=True))
    return ax_rain


# 输出目录
fig_dir = os.path.join(project_root, 'Results', 'FigPerformanceAction')
os.makedirs(fig_dir, exist_ok=True)

# 仅选取 Event 1-10 (scenario_names_all 第 1~10 个, 1-indexed)
event_start = 1
event_end = 10
selected_names = scenario_names_all[event_start - 1:event_end]
n_events = len(selected_names)
n_rows = (n_events + 1) // 2   # 5 行
n_cols = 2


def _draw_fc_subplot(ax, name, event_no):
    """在一个子图上绘制某事件的 FC (Flooding+CSO) 曲线 + 降雨柱 (复刻 results_FC_full.py)。"""
    sim_start = scenario_sim_start.get(name, datetime.datetime(2020, 1, 1, 2, 0, 0))
    rain_times, rain_vals = scenario_rain_raw.get(name, ([], np.array([])))

    # FC 曲线 (flooding[1:] + CSO[1:]) —— 以 BC 数据长度为基准
    if name not in results['BC']:
        ax.set_title(f'Event{event_no}', fontsize=16)
        return

    bc_fc_raw = (np.array(results['BC'][name]['flooding'][1:])
                 + np.array(results['BC'][name]['CSO'][1:]))
    fc_data_len = len(bc_fc_raw)

    # 每 5 步聚合一次 (与 results_FC_full.py 一致)
    fc_plot_idx = np.arange(0, fc_data_len, 5)
    n_agg = len(fc_plot_idx)
    dt_agg = [sim_start + datetime.timedelta(minutes=5 * 5 * i) for i in range(n_agg)]

    bc_fc = bc_fc_raw[fc_plot_idx] / 1000  # 10^3 m^3

    # 降雨柱
    ax_rain = _draw_rain(ax, rain_times, rain_vals)
    ax.set_xlim(dt_agg[0] - datetime.timedelta(hours=1),
                dt_agg[-1] + datetime.timedelta(hours=1))
    if len(rain_vals) > 0:
        ax_rain.set_xlim(dt_agg[0] - datetime.timedelta(hours=1),
                         dt_agg[-1] + datetime.timedelta(hours=1))

    # 3 个 x 刻度
    n_ticks = len(dt_agg)
    tick_pos = [0, n_ticks // 2, n_ticks - 1]
    ax.set_xticks([dt_agg[i] for i in tick_pos])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))

    ax.set_ylabel('Flooding and CSO\n(10³ m³)', fontsize=13)
    ax.tick_params(axis='both', labelsize=11)

    # FC 曲线 (与 results_FC_full.py 颜色/线型/alpha 一致)
    ax.plot(dt_agg, bc_fc, color=ccf['BC'], alpha=FC_ALPHA['BC'],
            linewidth=2.0, zorder=5)

    # MPC FC 曲线
    if name in results['MPC']:
        mpc_fc_raw = (np.array(results['MPC'][name]['flooding'][1:])
                      + np.array(results['MPC'][name]['CSO'][1:]))
        mpc_fc = mpc_fc_raw[fc_plot_idx] / 1000
        ax.plot(dt_agg, mpc_fc, color=ccf['MPC'], alpha=FC_ALPHA['MPC'],
                linewidth=2.0, linestyle=FC_LINESTYLES['MPC'], zorder=5)

    # Agent (DeepSeek) FC 曲线
    if name in results['Agent']:
        ag_fc_raw = (np.array(results['Agent'][name]['flooding'][1:])
                     + np.array(results['Agent'][name]['CSO'][1:]))
        ag_fc = ag_fc_raw[fc_plot_idx] / 1000
        ax.plot(dt_agg, ag_fc, color=ccf['Agent'], alpha=FC_ALPHA['Agent'],
                linewidth=2.0, linestyle=FC_LINESTYLES['Agent'], zorder=5)

    ax.set_title(f'Event{event_no}', fontsize=16)


def _draw_action_subplot(ax, name, event_no):
    """在一个子图上绘制某事件的控制曲线 (开启泵总数量) + 降雨柱 (复刻 results_Action_total.py)。"""
    sim_start = scenario_sim_start.get(name, datetime.datetime(2020, 1, 1, 2, 0, 0))
    rain_times, rain_vals = scenario_rain_raw.get(name, ([], np.array([])))

    # 收集各方法 action -> 开启泵总数量 (7台二进制泵求和)
    method_data = {}
    max_len = 0
    for method_label in ('BC', 'Agent', 'MPC'):
        if name not in results[method_label]:
            continue
        res = results[method_label][name]
        action_key = METHOD_PATHS[method_label][2]
        actions = res.get(action_key, [])
        if not actions:
            continue
        action_arr = np.array(actions)  # shape (T, 7)
        if action_arr.ndim != 2 or action_arr.shape[1] == 0:
            continue
        pump_count = action_arr.sum(axis=1).astype(int)
        method_data[method_label] = {
            'pump_count': pump_count,
            'n_steps': action_arr.shape[0],
        }
        if action_arr.shape[0] > max_len:
            max_len = action_arr.shape[0]

    # 降雨柱
    ax_rain2 = _draw_rain(ax, rain_times, rain_vals)

    if max_len > 0:
        time_axis = [sim_start + dt_delta * i for i in range(max_len)]
        tick_idx = [0, max_len // 2, max_len - 1]
        tick_times = [time_axis[i] for i in tick_idx]
        x_lo = time_axis[0] - datetime.timedelta(minutes=10)
        x_hi = time_axis[-1] + datetime.timedelta(minutes=10)
        ax_rain2.set_xlim(x_lo, x_hi)

        # 各方法开启泵总数量阶梯曲线 (与 results_Action_total.py 颜色/线型一致)
        for method_label in ('MPC', 'BC', 'Agent'):  # 绘制层叠顺序 (底->顶)
            md = method_data.get(method_label)
            if md is None:
                continue
            pump_count = md['pump_count']
            n = md['n_steps']
            t_count = time_axis[:n]
            ax.step(t_count, pump_count, where='post',
                    color=ccf[method_label], linestyle=ACT_LINESTYLES[method_label],
                    linewidth=1.8, alpha=0.9, zorder=3)

        ax.set_ylim(-0.5, NUM_PUMPS + 0.5)
        ax.set_yticks(range(0, NUM_PUMPS + 1))
        ax.set_ylabel('Pumps ON', fontsize=13)
        ax.tick_params(axis='both', labelsize=11)
        ax.set_xlim(x_lo, x_hi)
        ax.set_xticks(tick_times)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        ax.grid(True, axis='y', alpha=0.3, linestyle='--', zorder=0)

    ax.set_title(f'Event{event_no}', fontsize=16)


# ============================================================
# 5. 单一图例 (两张图共用, 数据源与图例不变): BC 实线, MPC/Agent 虚线, Rainfall
# ============================================================
unified_handles = [
    Line2D([0], [0], color=ccf['BC'],    linewidth=2.5, linestyle='-',  label='BC'),
    Line2D([0], [0], color=ccf['MPC'],   linewidth=2.5, linestyle='--', label='Limited MPC'),
    Line2D([0], [0], color=ccf['Agent'], linewidth=2.5, linestyle='--', label='AgenticAI-Control'),
    Patch(facecolor='steelblue', edgecolor='navy', linewidth=0.3, alpha=0.4, label='Rainfall'),
]

# ============================================================
# 6. 图1: 全部 Flooding and CSO 结果 (5行2列)
# ============================================================
fig1 = plt.figure(dpi=150, figsize=(14, 3.2 * n_rows))
gs1 = GridSpec(n_rows, n_cols, figure=fig1, hspace=0.38, wspace=0.25)
gs1.update(top=0.95, bottom=0.07)

for idx, name in enumerate(selected_names):
    event_no = event_start + idx   # 实际事件编号 (1..10)
    ax_fc = fig1.add_subplot(gs1[idx // n_cols, idx % n_cols])
    _draw_fc_subplot(ax_fc, name, event_no)

fig1.legend(handles=unified_handles, fontsize=14, loc='lower center',
            ncol=len(unified_handles), frameon=True, fancybox=True,
            framealpha=0.95, bbox_to_anchor=(0.5, 0.035))

out_path1 = os.path.join(fig_dir, 'FC_E1-10.png')
plt.savefig(out_path1, dpi=200, bbox_inches='tight')
plt.close(fig1)
print(f"已保存: {out_path1}")

# ============================================================
# 7. 图2: 全部控制曲线结果 (5行2列)
# ============================================================
fig2 = plt.figure(dpi=150, figsize=(14, 3.2 * n_rows))
gs2 = GridSpec(n_rows, n_cols, figure=fig2, hspace=0.38, wspace=0.25)
gs2.update(top=0.95, bottom=0.07)

for idx, name in enumerate(selected_names):
    event_no = event_start + idx   # 实际事件编号 (1..10)
    ax_act = fig2.add_subplot(gs2[idx // n_cols, idx % n_cols])
    _draw_action_subplot(ax_act, name, event_no)

fig2.legend(handles=unified_handles, fontsize=14, loc='lower center',
            ncol=len(unified_handles), frameon=True, fancybox=True,
            framealpha=0.95, bbox_to_anchor=(0.5, 0.035))

out_path2 = os.path.join(fig_dir, 'Action_E1-10.png')
plt.savefig(out_path2, dpi=200, bbox_inches='tight')
plt.close(fig2)
print(f"已保存: {out_path2}")

print("\n两张组合图生成完成！")
