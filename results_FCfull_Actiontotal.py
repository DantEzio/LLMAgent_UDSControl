# -*- coding: utf-8 -*-
"""
组合图: 3 行 2 列, 仅取 Event 1-3

  左列  (col 0): 降雨柱状图 + FC (Flooding+CSO) 曲线  —— 复刻 results_FC_full.py 子图
  右列  (col 1): 降雨柱状图 + 开启泵总数量阶梯曲线     —— 复刻 results_Action_total.py 子图

  行对齐: 同一行 = 同一场降雨 (左 FC, 右 控制曲线)

颜色 / 图例 / 图例名字与两个源代码保持一致:
  - BC              #8b0000
  - MPC-Control     #b8860b   (MPC, step2-MPC-control-best, perfect 预测)
  - AgenticAI-Control #2e7d32  (Agent, step3-BCAgent-control, DeepSeek)
  - Rainfall         steelblue/navy (alpha 0.4)

  全图单一图例 (底部): BC(实线), MPC-Control(虚线), AgenticAI-Control(虚线), Rainfall
  两列均: BC 实线, MPC/Agent 虚线 (颜色区分)

输出: Results/FCfull_Actiontotal.png

用法:
    python results_FCfull_Actiontotal.py
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
    'MPC':   ('step2-MPC-control-best', 'mpc_results_',      'action'),
}

# 显示标签 (与图例一致)
DISPLAY_LABELS = {
    'BC':    'BC',
    'MPC':   'MPC',
    'Agent': 'AgenticAI-Control',
}

# ============================================================
# 各控制策略每步平均响应时间: 从结果文件中的 compute_time 数组实时计算
# (在右列 Action 子图 textbox 中按事件显示, 无需手动填值)
# ============================================================

# ============================================================
# 1. 发现场景 (仅取 Event 1-3)
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

# 仅取前 3 场 (Event 1-3)
N_EVENTS = 3
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
# 4. 绘制 3 行 2 列组合图
#    col 0: FC (复刻 results_FC_full.py)
#    col 1: 控制曲线 (复刻 results_Action_total.py)
# ============================================================
print("\n生成 3 行 2 列组合图 (左 FC + 右 控制曲线)...")

dt_delta = datetime.timedelta(minutes=INTERVAL_MIN)  # 5 分钟
n_rows = N_EVENTS
n_cols = 2

fig = plt.figure(dpi=150, figsize=(14, 3.2 * n_rows))
gs = GridSpec(n_rows, n_cols, figure=fig, hspace=0.38, wspace=0.25)
gs.update(top=0.93, bottom=0.12)


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
        ax_rain.set_ylabel('Rainfall intensity (mm/h)', fontsize=13, color='black')
        ax_rain.tick_params(axis='y', labelcolor='black', labelsize=11)
        ax_rain.invert_yaxis()
        y_max_rain = rain_vals.max() if rain_vals.max() > 0 else 10
        ax_rain.set_ylim(y_max_rain * 1.45, 0)
        ax_rain.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5, integer=True))
    return ax_rain


for idx, name in enumerate(scenario_names):
    # ---------- 左列: FC 子图 (复刻 results_FC_full.py) ----------
    ax_fc = fig.add_subplot(gs[idx, 0])

    sim_start = scenario_sim_start.get(name, datetime.datetime(2020, 1, 1, 2, 0, 0))
    rain_times, rain_vals = scenario_rain_raw.get(name, ([], np.array([])))

    # FC 曲线 (flooding[1:] + CSO[1:]) —— 以 BC 数据长度为基准
    has_bc = name in results['BC']
    if not has_bc:
        ax_fc.set_title(f'Event{idx + 1}: Flooding & CSO', fontsize=16)
    else:
        bc_fc_raw = (np.array(results['BC'][name]['flooding'][1:])
                     + np.array(results['BC'][name]['CSO'][1:]))
        fc_data_len = len(bc_fc_raw)

        # 每 5 步聚合一次 (与 results_FC_full.py 一致)
        fc_plot_idx = np.arange(0, fc_data_len, 5)
        n_agg = len(fc_plot_idx)
        dt_agg = [sim_start + datetime.timedelta(minutes=5 * 5 * i) for i in range(n_agg)]

        bc_fc = bc_fc_raw[fc_plot_idx] / 1000  # 10^3 m^3

        # 降雨柱
        ax_rain = _draw_rain(ax_fc, rain_times, rain_vals)
        ax_fc.set_xlim(dt_agg[0] - datetime.timedelta(hours=1),
                       dt_agg[-1] + datetime.timedelta(hours=1))
        if len(rain_vals) > 0:
            ax_rain.set_xlim(dt_agg[0] - datetime.timedelta(hours=1),
                             dt_agg[-1] + datetime.timedelta(hours=1))

        # 3 个 x 刻度
        n_ticks = len(dt_agg)
        tick_pos = [0, n_ticks // 2, n_ticks - 1]
        ax_fc.set_xticks([dt_agg[i] for i in tick_pos])
        ax_fc.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))

        ax_fc.set_ylabel('Flooding and CSO\n(10³ m³)', fontsize=13)
        ax_fc.tick_params(axis='both', labelsize=11)

        # FC 曲线 (与 results_FC_full.py 颜色/线型/alpha 一致)
        ax_fc.plot(dt_agg, bc_fc, color=ccf['BC'], alpha=FC_ALPHA['BC'],
                   linewidth=2.0, zorder=5)

        # MPC (perfect) FC 曲线
        if name in results['MPC']:
            mpc_fc_raw = (np.array(results['MPC'][name]['flooding'][1:])
                          + np.array(results['MPC'][name]['CSO'][1:]))
            mpc_fc = mpc_fc_raw[fc_plot_idx] / 1000
            ax_fc.plot(dt_agg, mpc_fc, color=ccf['MPC'], alpha=FC_ALPHA['MPC'],
                       linewidth=2.0, linestyle=FC_LINESTYLES['MPC'], zorder=5)

        # Agent (DeepSeek) FC 曲线
        if name in results['Agent']:
            ag_fc_raw = (np.array(results['Agent'][name]['flooding'][1:])
                         + np.array(results['Agent'][name]['CSO'][1:]))
            ag_fc = ag_fc_raw[fc_plot_idx] / 1000
            ax_fc.plot(dt_agg, ag_fc, color=ccf['Agent'], alpha=FC_ALPHA['Agent'],
                       linewidth=2.0, linestyle=FC_LINESTYLES['Agent'], zorder=5)

        # ---- textbox: 各控制策略最终 FC 值 (10³ m³) ----
        fc_text_lines = []
        for _m in ('BC', 'MPC', 'Agent'):
            if name in results[_m]:
                _final_fc = (results[_m][name]['flooding'][-1]
                             + results[_m][name]['CSO'][-1]) / 1000  # 10³ m³
                fc_text_lines.append(f'{DISPLAY_LABELS[_m]}: {_final_fc:.1f}')
            else:
                fc_text_lines.append(f'{DISPLAY_LABELS[_m]}: N/A')
        fc_text = 'Flooding and CSO '+f'(10³ m³)'+ '\n' + '\n'.join(fc_text_lines)
        ax_fc.text(0.95, 0.68, fc_text, transform=ax_fc.transAxes,
                   fontsize=12, ha='right', va='center',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                             edgecolor='gray', alpha=0.85, linewidth=0.6),
                   zorder=10)

        ax_fc.set_title(f'Event{idx + 1}: Flooding & CSO', fontsize=16)

    # 左列 (a) 标签: 仅第一行, 图外左上角
    if idx == 0:
        ax_fc.text(-0.02, 1.08, '(a)', transform=ax_fc.transAxes,
                   fontsize=20, fontweight='bold', ha='left', va='bottom',
                   clip_on=False)

    # ---------- 右列: 控制曲线子图 (复刻 results_Action_total.py) ----------
    ax_act = fig.add_subplot(gs[idx, 1])

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

    # 降雨柱 (与左列同一函数, 保持降雨视觉一致)
    ax_rain2 = _draw_rain(ax_act, rain_times, rain_vals)

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
            ax_act.step(t_count, pump_count, where='post',
                        color=ccf[method_label], linestyle=ACT_LINESTYLES[method_label],
                        linewidth=1.8, alpha=0.9, zorder=3)

        ax_act.set_ylim(-0.5, NUM_PUMPS + 0.5)
        ax_act.set_yticks(range(0, NUM_PUMPS + 1))
        ax_act.set_ylabel('Pumps ON', fontsize=13)
        ax_act.tick_params(axis='both', labelsize=11)
        ax_act.set_xlim(x_lo, x_hi)
        ax_act.set_xticks(tick_times)
        ax_act.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        ax_act.grid(True, axis='y', alpha=0.3, linestyle='--', zorder=0)

    ax_act.set_title(f'Event{idx + 1}: Control actions', fontsize=16)

    # ---- textbox: 各控制策略每步平均响应时间 (从结果 compute_time 实时计算, 本事件) ----
    rt_text_lines = []
    for _m in ('BC', 'MPC', 'Agent'):
        _res = results.get(_m, {}).get(name, {})
        _ct = _res.get('compute_time')
        if _ct is None or len(_ct) == 0:
            rt_text_lines.append(f'{DISPLAY_LABELS[_m]}: N/A')
        else:
            _avg = float(np.mean(_ct))
            # 自适应单位 (按记录原值, 秒为基准)
            if _avg >= 0.1:
                _rt_str = f'{_avg:.2f}s'
            elif _avg >= 0.001:
                _rt_str = f'{_avg * 1000:.2f}ms'
            else:
                _rt_str = f'{_avg * 1e6:.2f}us'
            rt_text_lines.append(f'{DISPLAY_LABELS[_m]}: {_rt_str}')
    rt_text = 'Avg response time:\n' + '\n'.join(rt_text_lines)
    ax_act.text(0.93, 0.70, rt_text, transform=ax_act.transAxes,
               fontsize=12, ha='right', va='center',
               bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                         edgecolor='gray', alpha=0.85, linewidth=0.6),
               zorder=10)

    # 右列 (b) 标签: 仅第一行, 图外左上角
    if idx == 0:
        ax_act.text(-0.02, 1.08, '(b)', transform=ax_act.transAxes,
                    fontsize=20, fontweight='bold', ha='left', va='bottom',
                    clip_on=False)

# ============================================================
# 5. 单一图例 (全图共用): BC 实线, MPC/Agent 虚线, Rainfall
# ============================================================
unified_handles = [
    Line2D([0], [0], color=ccf['BC'],    linewidth=2.5, linestyle='-',  label='BC'),
    Line2D([0], [0], color=ccf['MPC'],   linewidth=2.5, linestyle='--', label='MPC'),
    Line2D([0], [0], color=ccf['Agent'], linewidth=2.5, linestyle='--', label='AgenticAI-Control'),
    Patch(facecolor='steelblue', edgecolor='navy', linewidth=0.3, alpha=0.4, label='Rainfall'),
]
fig.legend(handles=unified_handles, fontsize=14, loc='lower center',
           ncol=len(unified_handles), frameon=True, fancybox=True,
           framealpha=0.95, bbox_to_anchor=(0.5, 0.015))

# ============================================================
# 6. 保存到 Results/FigPerformanceAction/
# ============================================================
fig_dir = os.path.join(project_root, 'Results', 'FigPerformanceAction')
os.makedirs(fig_dir, exist_ok=True)
out_path = os.path.join(fig_dir, 'FCfull_Actiontotal.png')
plt.savefig(out_path, dpi=200, bbox_inches='tight')
plt.close(fig)
print(f"已保存: {out_path}")

print("\n组合图生成完成！")
