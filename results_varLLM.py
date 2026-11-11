# -*- coding: utf-8 -*-
"""
对比不同 LLM 后端下 BCAgent 的控制效果 (F+C 曲线 vs 降雨)。

绘制 BC 基准线 与 所有 LLM 变体的 BCAgent 结果：
  - step1-BC-control              → BC
  - step3-BCAgent-control         → DeepSeek-v4
  - step3-BCAgent-control-GLM     → GLM-4-flash
  - step3-BCAgent-control-Kimi    → Moonshot-v1-8k
  - step3-BCAgent-control-MiniMax → MiniMax-M3

用法:
    python results_varLLM.py
"""

import sys
import os

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

# [FIX] 导入 warnings.md 解析函数（用于标记场景中记录的真实预警事件）
try:
    from llm_event_agent import parse_warnings_file
except ImportError:
    parse_warnings_file = None

# [UPDATED] 从统一配置导入时间参数 (DRL-control/time_config.py)
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
# LLM 变体配置
# ============================================================
LLM_VARIANTS = {
    'DeepSeek-v4':   'step3-BCAgent-control',
    'GLM-4-flash':   'step3-BCAgent-control-GLM',
    'Moonshot-v1-8k': 'step3-BCAgent-control-Kimi',
    'MiniMax-M3':    'step3-BCAgent-control-MiniMax',
}

project_root = _sys_parent
scenarios_dir = os.path.join(project_root, 'Scenarios', 'NMC_Events_2015_2025')

# ============================================================
# 1. 发现所有场景
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

print(f"NMC目录下共 {len(nmc_scenario_names)} 个场景文件夹")
print(f"其中 {len(scenario_names)} 个场景有 BC 结果")
print(f"LLM 变体: {list(LLM_VARIANTS.keys())}")

# ============================================================
# 2. 加载场景降雨数据
# ============================================================
scenario_rain = {}
scenario_rain_raw = {}
scenario_sim_start = {}

for folder_name in scenario_names:
    folder_path = os.path.join(scenarios_dir, folder_name)
    full_npy_files = glob.glob(os.path.join(folder_path, '*_FULL_SWMM.npy'))
    orig_npy_files = [f for f in glob.glob(os.path.join(folder_path, '*_SWMM.npy'))
                      if not f.endswith('_FULL_SWMM.npy')]
    npy_files = full_npy_files if full_npy_files else orig_npy_files

    readme_path = os.path.join(folder_path, 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            readme_content = f.read()
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', readme_content)
        event_date_str = date_match.group(1) if date_match else ''
        scenario_sim_start[folder_name] = compute_sim_start_from_readme(
            readme_content, event_date_str)

    if npy_files:
        swmm_data = np.load(npy_files[0])
        if swmm_data.ndim < 2 or swmm_data.shape[0] == 0:
            scenario_rain[folder_name] = np.array([])
            scenario_rain_raw[folder_name] = ([], np.array([]))
            continue
        hours = swmm_data.shape[0]
        rain_array = np.zeros(hours * 12)
        for j in range(len(swmm_data)):
            mm_per_5min = swmm_data[j, 1] / 12.0
            rain_array[j * 12:(j + 1) * 12] = mm_per_5min
        scenario_rain[folder_name] = rain_array

        elapsed_hours = swmm_data[:, 0]
        mm_per_hr = swmm_data[:, 1]
        times_raw = [scenario_sim_start.get(folder_name, datetime.datetime(2020, 1, 1, 2, 0, 0))
                      + datetime.timedelta(hours=float(h)) for h in elapsed_hours]
        scenario_rain_raw[folder_name] = (times_raw, mm_per_hr)
    else:
        scenario_rain[folder_name] = np.array([])
        scenario_rain_raw[folder_name] = ([], np.array([]))

# ============================================================
# 3. 加载 BC 与所有 LLM BCAgent 结果
# ============================================================
results_BC = {}
results_LLM = {}   # {llm_label: {scenario_name: result_dict}}

for name in scenario_names:
    bc_path = os.path.join(project_root, 'DRL-control', 'step1-BC-control',
                           'results', f'bc_results_{name}.npy')
    if os.path.exists(bc_path):
        results_BC[name] = np.load(bc_path, allow_pickle=True).tolist()
    else:
        print(f"  警告: 未找到 BC 结果: {bc_path}")

for llm_label, dir_name in LLM_VARIANTS.items():
    results_LLM[llm_label] = {}
    for name in scenario_names:
        llm_path = os.path.join(project_root, 'DRL-control', dir_name,
                                'results', f'bc_agent_results_{name}.npy')
        if os.path.exists(llm_path):
            results_LLM[llm_label][name] = np.load(llm_path, allow_pickle=True).tolist()
        else:
            print(f"  警告: 未找到 {llm_label} 结果: {llm_path}")

# ============================================================
# 4. 输出 Flooding + CSO 汇总表
# ============================================================
print("\n" + "=" * 80)
print("表: Flooding + CSO 结果汇总 (BC + 各 LLM BCAgent)")
print("=" * 80)

table_data = {
    'Scenario': [],
    'BC_Flooding': [], 'BC_CSO': [], 'BC_F+C': [],
}
for llm_label in LLM_VARIANTS:
    table_data[f'{llm_label}_Flooding'] = []
    table_data[f'{llm_label}_CSO'] = []
    table_data[f'{llm_label}_F+C'] = []
    table_data[f'{llm_label}_vBC_Impr'] = []

for name in scenario_names:
    if name not in results_BC:
        continue

    bc_flood = results_BC[name]['flooding'][-1]
    bc_cso = results_BC[name]['CSO'][-1]
    bc_fc = bc_flood + bc_cso

    table_data['Scenario'].append(name)
    table_data['BC_Flooding'].append(bc_flood)
    table_data['BC_CSO'].append(bc_cso)
    table_data['BC_F+C'].append(bc_fc)

    for llm_label in LLM_VARIANTS:
        if name in results_LLM[llm_label]:
            llm_flood = results_LLM[llm_label][name]['flooding'][-1]
            llm_cso = results_LLM[llm_label][name]['CSO'][-1]
            llm_fc = llm_flood + llm_cso
            imp_bc = (bc_fc - llm_fc) / bc_fc * 100 if bc_fc > 0 and not np.isnan(bc_fc) else float('nan')
        else:
            llm_flood, llm_cso, llm_fc, imp_bc = float('nan'), float('nan'), float('nan'), float('nan')
        table_data[f'{llm_label}_Flooding'].append(llm_flood)
        table_data[f'{llm_label}_CSO'].append(llm_cso)
        table_data[f'{llm_label}_F+C'].append(llm_fc)
        table_data[f'{llm_label}_vBC_Impr'].append(imp_bc)

df_table = pd.DataFrame(table_data)
print(df_table.to_string(index=False, float_format=lambda x: f'{x:.2f}'))

# 输出平均值
print("\n--- 平均值 ---")
bc_f_vals_avg = [v for v in table_data['BC_Flooding'] if not np.isnan(v)]
bc_c_vals_avg = [v for v in table_data['BC_CSO'] if not np.isnan(v)]
bc_fc_vals_avg = [v for v in table_data['BC_F+C'] if not np.isnan(v)]
print(f"BC          Flooding: {np.mean(bc_f_vals_avg):.2f}, CSO: {np.mean(bc_c_vals_avg):.2f}, F+C: {np.mean(bc_fc_vals_avg):.2f}")

for llm_label in LLM_VARIANTS:
    f_vals = [v for v in table_data[f'{llm_label}_Flooding'] if not np.isnan(v)]
    c_vals = [v for v in table_data[f'{llm_label}_CSO'] if not np.isnan(v)]
    fc_vals = [v for v in table_data[f'{llm_label}_F+C'] if not np.isnan(v)]
    imp_bc_vals = [v for v in table_data[f'{llm_label}_vBC_Impr'] if not np.isnan(v)]
    if fc_vals:
        print(f"{llm_label:<13s} Flooding: {np.mean(f_vals):.2f}, CSO: {np.mean(c_vals):.2f}, F+C: {np.mean(fc_vals):.2f}, vsBC: {np.mean(imp_bc_vals):.2f}%")

# 保存 CSV
results_dir = os.path.join(project_root, 'Results')
os.makedirs(results_dir, exist_ok=True)
df_table.to_csv(os.path.join(results_dir, 'table_FC_varLLM.csv'), index=False)
print(f"\n表格已保存: {os.path.join(results_dir, 'table_FC_varLLM.csv')}")

# ============================================================
# 5. F+C 曲线 vs 降雨 (每个场景) — BC + 所有 LLM BCAgent
# ============================================================
print("\n生成 F+C 曲线 vs 降雨 (varLLM)...")

# 颜色配置: BC + 4 个 LLM (与 results_FC.py 一致)
COLORS = {
    'BC': '#8b0000',               # 深红色 (与 results_FC.py ccf['BC'] 一致)
    'DeepSeek-v4': '#2e7d32',      # 深绿色 (与 results_FC.py AgenticAI-Control 一致)
    'GLM-4-flash': '#1f77b4',      # 蓝色
    'Moonshot-v1-8k': '#9467bd',     # 紫色
    'MiniMax-M3': '#ff7f0e',       # 橙色
}

# 线型配置
LINESTYLES = {
    'BC': '-',
    'DeepSeek-v4': '--',
    'GLM-4-flash': '-.',
    'Moonshot-v1-8k': ':',
    'MiniMax-M3': '--',
}

# Warning level colors
WARNING_COLORS = {
    '蓝色': '#1f77b4',
    '黄色': '#ff8c00',
    '橙色': '#ff4500',
    '红色': '#d62728',
    '应急响应': '#9467bd',
    '解除': '#999999',
    '未知': '#333333',
}

# 只取有 BC 结果的场景 (最多10个)
valid_scenario_names = [n for n in scenario_names if n in results_BC][:10]

n_cols = 2
n_rows = max(1, (len(valid_scenario_names) + n_cols - 1) // n_cols)
n_rows = min(5, n_rows)

fig = plt.figure(dpi=150, figsize=(12, 2.8 * n_rows))
gs = GridSpec(n_rows, n_cols, figure=fig, hspace=0.4, wspace=0.5)

pre_steps = PRE_HOURS * 60 // 5
post_steps = POST_HOURS * 60 // 5

for idx, name in enumerate(valid_scenario_names):
    row = idx // n_cols
    col = idx % n_cols
    ax = fig.add_subplot(gs[row, col])

    rain = scenario_rain.get(name, np.array([]))
    sim_start = scenario_sim_start.get(name)
    if sim_start is None:
        sim_start = datetime.datetime(2020, 1, 1, 2, 0, 0)

    # F+C 曲线 (以 BC 数据长度作为统一基准)
    bc_fc_raw = np.array(results_BC[name]['flooding'][1:]) + np.array(results_BC[name]['CSO'][1:])
    fc_data_len = len(bc_fc_raw)

    # 降雨数据对齐到 FC 长度
    if len(rain) > 0:
        rain_aligned = rain[:fc_data_len] if len(rain) >= fc_data_len else \
            np.pad(rain, (0, fc_data_len - len(rain)))
    else:
        rain_aligned = np.zeros(fc_data_len)

    # 构建时间轴 (每5步聚合一次)
    fc_plot_idx = np.arange(0, fc_data_len, 5)
    n_agg = len(fc_plot_idx)
    dt_agg = [sim_start + datetime.timedelta(minutes=5 * 5 * i) for i in range(n_agg)]

    # BC 曲线
    bc_fc = bc_fc_raw[fc_plot_idx] / 1000

    # ---- 降雨柱状图 (右轴) ----
    ax_rain = ax.twinx()
    ax_rain.set_zorder(0)
    ax.set_zorder(1)
    ax.patch.set_visible(False)
    rain_raw = scenario_rain_raw.get(name, ([], np.array([])))
    times_raw, mm_per_hr = rain_raw
    if len(mm_per_hr) > 0:
        bar_width = 1 / 24
        ax_rain.bar(times_raw, mm_per_hr, width=bar_width, color='steelblue',
                   edgecolor='navy', linewidth=0.3, alpha=0.4, zorder=1)
        ax_rain.set_ylabel('Rainfall\nintensity (mm/h)', fontsize=14, color='black')
        ax_rain.tick_params(axis='y', labelcolor='black', labelsize=13)
        ax_rain.invert_yaxis()
        y_max_rain = mm_per_hr.max() if mm_per_hr.max() > 0 else 10
        ax_rain.set_ylim(y_max_rain * 1.45, 0)

    ax.set_xlim(dt_agg[0] - datetime.timedelta(hours=1),
                dt_agg[-1] + datetime.timedelta(hours=1))

    # 只显示最初、中间、结束三个时间节点
    n_ticks = len(dt_agg)
    tick_positions = [0, n_ticks // 2, n_ticks - 1]
    ax.set_xticks([dt_agg[i] for i in tick_positions])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))

    ax.set_ylabel('Flooding and CSO\n(10³ m³)', fontsize=15)
    ax.tick_params(axis='both', labelsize=14)

    # ---- 绘制 F+C 曲线 ----
    # BC 曲线
    ax.plot(dt_agg, bc_fc, color=COLORS['BC'], alpha=0.35, linewidth=2.0,
            linestyle=LINESTYLES['BC'], zorder=5)

    # 各 LLM BCAgent 曲线
    llm_labels_ordered = list(LLM_VARIANTS.keys())
    for llm_label in llm_labels_ordered:
        if name in results_LLM[llm_label]:
            llm_fc_raw = np.array(results_LLM[llm_label][name]['flooding'][1:]) \
                         + np.array(results_LLM[llm_label][name]['CSO'][1:])
            # 对齐到统一长度
            min_len = min(len(llm_fc_raw), fc_data_len)
            fc_idx = np.arange(0, min_len, 5)
            llm_fc = llm_fc_raw[fc_idx] / 1000
            # 补齐时间轴
            llm_dt = dt_agg[:len(fc_idx)]
            ax.plot(llm_dt, llm_fc, color=COLORS[llm_label], alpha=0.55, linewidth=2.0,
                    linestyle=LINESTYLES[llm_label], zorder=5)

    # ---- LLM Event 垂直线 ----
    if parse_warnings_file is not None:
        warnings_md_candidates = glob.glob(os.path.join(scenarios_dir, name, '*_warnings.md'))
        if warnings_md_candidates:
            parsed_warnings = parse_warnings_file(warnings_md_candidates[0])
            if parsed_warnings and parsed_warnings.records:
                for rec in parsed_warnings.records:
                    level_str = rec.level.value if hasattr(rec.level, 'value') else '未知'
                    color = WARNING_COLORS.get(level_str, '#333333')
                    is_cancelled = rec.is_cancelled
                    linestyle = ':' if is_cancelled else '--'
                    ax.axvline(x=rec.publish_time, color=color,
                              linestyle=linestyle, linewidth=1.5, alpha=0.8)

    short_title = f'Event{idx + 1}'
    ax.set_title(short_title, fontsize=16)

# ---- 统一图例 ----
from matplotlib.lines import Line2D
unified_handles = [
    Line2D([0], [0], color=COLORS['BC'], linewidth=2.0,
           linestyle=LINESTYLES['BC'], label='BC'),
]

for llm_label in LLM_VARIANTS:
    unified_handles.append(
        Line2D([0], [0], color=COLORS[llm_label], linewidth=2.5,
               linestyle=LINESTYLES[llm_label], label=f'AgenticAI-Control-{llm_label}')
    )

fig.legend(handles=unified_handles, fontsize=14, loc='lower center',
            ncol=2, frameon=True, fancybox=True, framealpha=0.95,
            bbox_to_anchor=(0.5, 0.0))

fig.subplots_adjust(bottom=0.12)

# 保存图片到 Results/FigControlperformance 文件夹
fig_dir = os.path.join(project_root, 'Results', 'FigControlperformance')
os.makedirs(fig_dir, exist_ok=True)
out_fig_path = os.path.join(fig_dir, 'varLLM_FC_curve_vs_rainfall.png')
plt.savefig(out_fig_path, dpi=200, bbox_inches='tight')
print(f"F+C 曲线图已保存: {out_fig_path}")
plt.close()

print("\n所有分析和图表生成完成！")
