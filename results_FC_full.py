"""结果可视化 (完整版): 累计 F+C 曲线 + 多指标汇总表 + 预警时点标注。

用途
----
与 ``results_FC.py`` 相比, 本脚本额外输出各方法的 Flooding / CSO / F+C
逐事件指标表, 并在曲线上用竖线标注 warnings.md 中记录的预警等级与取消时刻。

输入
----
Scenarios/NMC_Events_2015_2025/<事件>/*_FULL_SWMM.npy   降雨序列
Scenarios/NMC_Events_2015_2025/<事件>/README.md         事件起始时间
Scenarios/NMC_Events_2015_2025/<事件>/Event_XX_warnings.md  预警记录 (可选)
DRL-control/step1-BC-control/results/bc_results_*.npy
DRL-control/step2-MPC-control-best/results/mpc_results_*.npy
DRL-control/step3-BCAgent-control/results/bc_agent_results_*.npy

输出
----
Results/FigControlperformance/FC_curve_vs_rainfall_full.png   累计 F+C 曲线图
Results/table_FC_NMC_full.csv                                 逐事件指标表

说明
----
- ``parse_warnings_file`` 依赖 ``step3-BCAgent-control/llm_event_agent.py``;
  若该模块不可导入则自动跳过预警竖线, 不影响其余绘图;
- 事件筛选仅要求存在 BC 结果。

运行方式
--------
    python results_FC_full.py
"""

import sys
import os

# 项目根目录
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
# 1. 发现所有场景 (从 Scenarios/NMC_Events_2015_2025)
# ============================================================
project_root = _sys_parent
scenarios_dir = os.path.join(project_root, 'Scenarios', 'NMC_Events_2015_2025')

# 从 Scenarios 目录获取所有场景文件夹名
nmc_scenario_names = sorted([
    d for d in os.listdir(scenarios_dir)
    if os.path.isdir(os.path.join(scenarios_dir, d))
])

# 从 BC results 中获取已有结果的场景名，只保留在 NMC 目录中存在的
bc_results_dir = os.path.join(project_root, 'DRL-control', 'step1-BC-control', 'results')
bc_scenario_files = sorted(glob.glob(os.path.join(bc_results_dir, 'bc_results_*.npy')))
scenario_names = []
for f in bc_scenario_files:
    basename = os.path.basename(f)
    # bc_results_Event_01_2015-06-02_暴雨蓝色.npy -> Event_01_2015-06-02_暴雨蓝色
    name = basename.replace('bc_results_', '').replace('.npy', '')
    # 只保留在 NMC_Events_2015_2025 目录中存在的场景
    if name in nmc_scenario_names:
        scenario_names.append(name)

print(f"NMC目录下共 {len(nmc_scenario_names)} 个场景文件夹")
print(f"其中 {len(scenario_names)} 个场景有 BC 结果:")
for s in scenario_names:
    print(f"  {s}")



# ============================================================
# 2. 加载场景降雨数据 (从 Scenarios/NMC_Events_2015_2025 目录)
#    新格式: _SWMM.npy, shape=(72,2) → [elapsed_hours, mm/hr]
#    转换为 mm/5min (mm/hr / 12)
# ============================================================
scenario_rain = {}  # {scenario_name: rain_array (hours*12,), 单位: mm/5min} (保留用于FC对齐)
scenario_rain_raw = {}  # {scenario_name: (times_list, mm_per_hr_array)} 原始降雨数据(用于绘图,与rainfall event一致)
scenario_sim_start = {}  # {scenario_name: datetime} 模拟起始时间
for folder_name in scenario_names:
    folder_path = os.path.join(scenarios_dir, folder_name)
    # [UPDATED] 优先读取 *_FULL_SWMM.npy (含完整 pre+rain+post 窗口)
    full_npy_files = glob.glob(os.path.join(folder_path, '*_FULL_SWMM.npy'))
    orig_npy_files = [f for f in glob.glob(os.path.join(folder_path, '*_SWMM.npy'))
                      if not f.endswith('_FULL_SWMM.npy')]
    npy_files = full_npy_files if full_npy_files else orig_npy_files

    # [FIX] 从 README.md "数据窗口" 解析真实数据起点计算模拟起始时间
    # (原始数据第0行=数据窗口起点; FULL数据第0行=数据窗口起点-PRE_HOURS)
    # 回退: event_date 08:00 - PRE_HOURS (旧逻辑)
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
        # 将 mm/hr 转换为 mm/5min: 每小时均匀分配到12个5分钟步
        # [FIX] 直接用数组行数计算 hours，与三个 main 文件保持一致
        hours = swmm_data.shape[0]
        rain_array = np.zeros(hours * 12)
        for j in range(len(swmm_data)):
            mm_per_5min = swmm_data[j, 1] / 12.0
            rain_array[j * 12:(j + 1) * 12] = mm_per_5min
        scenario_rain[folder_name] = rain_array
        
        # [NEW] 保存原始 mm/hr 数据 (与 results_rainfall_event.py 完全一致)
        elapsed_hours = swmm_data[:, 0]
        mm_per_hr = swmm_data[:, 1]
        times_raw = [scenario_sim_start.get(folder_name, datetime.datetime(2020, 1, 1, 2, 0, 0)) + datetime.timedelta(hours=float(h)) for h in elapsed_hours]
        scenario_rain_raw[folder_name] = (times_raw, mm_per_hr)
    else:
        print(f"  警告: 未找到 {folder_name} 的降雨数据 (_SWMM.npy)")
        scenario_rain[folder_name] = np.array([])
        scenario_rain_raw[folder_name] = ([], np.array([]))

# ============================================================
# 3. 加载 BC、MPC、AgenticAI-BC (规则控制 + LLM事件驱动调整) 结果
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
# 4. 输出 Flooding + CSO 汇总表
# ============================================================
print("\n" + "=" * 80)
print("表: Flooding + CSO 结果汇总")
print("=" * 80)

table_data = {
    'Scenario': [],
    'BC_Flooding': [],
    'BC_CSO': [],
    'BC_F+C': [],
    'MPC_Flooding': [],      # MPC (PSO + SWMM 预测滚动时域控制)
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

    # MPC (PSO + SWMM 预测滚动时域控制)
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

    # BC + AgenticAI (AgenticAI-BC: 规则控制 + LLM事件驱动调整)
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

# 输出平均值
print("\n--- 平均值 ---")
bc_f_avg = np.mean(table_data['BC_Flooding'])
bc_c_avg = np.mean(table_data['BC_CSO'])
bc_fc_avg = np.mean(table_data['BC_F+C'])

print(f"BC         Flooding: {bc_f_avg:.2f}, CSO: {bc_c_avg:.2f}, F+C: {bc_fc_avg:.2f}")

# MPC 平均
mpc_f_vals = [v for v in table_data['MPC_Flooding'] if not np.isnan(v)]
mpc_c_vals = [v for v in table_data['MPC_CSO'] if not np.isnan(v)]
mpc_fc_vals = [v for v in table_data['MPC_F+C'] if not np.isnan(v)]
mpc_vs_bc_vals = [v for v in table_data['MPCvBC_Improve'] if not np.isnan(v)]

if mpc_fc_vals:
    print(f"MPC          Flooding: {np.mean(mpc_f_vals):.2f}, CSO: {np.mean(mpc_c_vals):.2f}, F+C: {np.mean(mpc_fc_vals):.2f}")
    print(f"MPC vs BC  改善率: {np.mean(mpc_vs_bc_vals):.2f}%")

# AgenticAI-BC 平均
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

# 保存 CSV 到 Results 文件夹
results_dir = os.path.join(project_root, 'Results')
os.makedirs(results_dir, exist_ok=True)
df_table.to_csv(os.path.join(results_dir, 'table_FC_NMC_full.csv'), index=False)
print(f"\n表格已保存: {os.path.join(results_dir, 'table_FC_NMC_full.csv')}")



# ============================================================
# 6. F+C 曲线 vs 降雨 (每个场景)
#    布局: 5行2列, 降雨数据画在顶部
# ============================================================
print("\n生成 F+C 曲线 vs 降雨...")

ccf = {
    'BC': "#8b0000",      # 深红色 (BC)
    'MPC': "#b8860b",     # 暗金黄色 (PSO + SWMM 预测滚动时域控制)
    'AgenticAI-BC': "#2e7d32",  # 深绿色 (BC规则控制+LLM事件驱动, DeepSeek)
}

# Warning level colors (与 results_rainfall_event.py 完全一致)
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

# 只取有 BC 结果的场景 (最多10个用于绘图)
valid_scenario_names = [n for n in scenario_names if n in results_BC][:10]

# Track which warning levels appear (for global legend)
all_warning_levels_seen = set()

n_cols = 2
n_rows = max(1, (len(valid_scenario_names) + n_cols - 1) // n_cols)
# 确保最多5行
n_rows = min(5, n_rows)

fig = plt.figure(dpi=150, figsize=(12, 2.8 * n_rows))
gs = GridSpec(n_rows, n_cols, figure=fig, hspace=0.4, wspace=0.5)

pre_steps = PRE_HOURS * 60 // 5   # 72 步
post_steps = POST_HOURS * 60 // 5  # 216 步

for idx, name in enumerate(valid_scenario_names):
    row = idx // n_cols
    col = idx % n_cols
    ax = fig.add_subplot(gs[row, col])

    rain = scenario_rain.get(name, np.array([]))
    sim_start = scenario_sim_start.get(name)
    if sim_start is None:
        sim_start = datetime.datetime(2020, 1, 1, 2, 0, 0)

    # F+C 曲线 (先计算)
    bc_fc_raw = np.array(results_BC[name]['flooding'][1:]) + np.array(results_BC[name]['CSO'][1:])

    # 以 FC 数据实际长度为统一基准
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

    bc_fc = bc_fc_raw[fc_plot_idx] / 1000  # 转换为 10^3 m^3

    # 计算最终 F+C 值
    bc_final = bc_fc[-1]

    # ---- 降雨柱状图 (右轴, 与results_rainfall_event.py完全一致: mm/hr) ----
    ax_rain = ax.twinx()
    # 轴层级控制：确保主轴元素(曲线/legend)能覆盖双轴上的降雨bar
    ax_rain.set_zorder(0)
    ax.set_zorder(1)
    ax.patch.set_visible(False)  # 隐藏主轴背景，否则会挡住降雨bar
    rain_raw = scenario_rain_raw.get(name, ([], np.array([])))
    times_raw, mm_per_hr = rain_raw
    if len(mm_per_hr) > 0:
        bar_width = 1 / 24  # 1小时宽度(与rainfall event一致,以天为单位)
        ax_rain.bar(times_raw, mm_per_hr, width=bar_width, color='steelblue',
                   edgecolor='navy', linewidth=0.3, alpha=0.4, zorder=1)
        ax_rain.set_ylabel('Rainfall\nintensity (mm/h)', fontsize=14, color='black')
        ax_rain.tick_params(axis='y', labelcolor='black', labelsize=13)
        # 倒置Y轴：上方为0，往下越大
        ax_rain.invert_yaxis()
        # Y轴范围 (与rainfall event一致: max*1.45, 但倒置)
        y_max_rain = mm_per_hr.max() if mm_per_hr.max() > 0 else 10
        ax_rain.set_ylim(y_max_rain * 1.45, 0)  # 上方为0，下方是1.45倍最大值

    ax.set_xlim(dt_agg[0] - datetime.timedelta(hours=1),
                dt_agg[-1] + datetime.timedelta(hours=1))

    # 只显示最初、中间、结束三个时间节点
    n_ticks = len(dt_agg)
    tick_positions = [0, n_ticks // 2, n_ticks - 1]
    ax.set_xticks([dt_agg[i] for i in tick_positions])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))

    # Y轴标签 (左轴: F+C)
    ax.set_ylabel('Flooding and CSO\n(10³ m³)', fontsize=15)
    ax.tick_params(axis='both', labelsize=14)

    # ---- 绘制 F+C 曲线 ----
    # BC 曲线
    ax.plot(dt_agg, bc_fc, color=ccf['BC'], alpha=0.4, linewidth=2.0, zorder=5)

    # MPC 曲线 (如果存在)
    has_mpc = name in results_MPC
    if has_mpc:
        mpc_fc_raw = np.array(results_MPC[name]['flooding'][1:]) + np.array(results_MPC[name]['CSO'][1:])
        mpc_fc = mpc_fc_raw[fc_plot_idx] / 1000
        ax.plot(dt_agg, mpc_fc, color=ccf['MPC'], alpha=0.7, linewidth=2.0, linestyle=':', zorder=5)

    # AgenticAI-BC 曲线 (如果存在)
    has_bcagent = name in results_BCAgent_Agentic
    if has_bcagent:
        bcag_fc_raw = np.array(results_BCAgent_Agentic[name]['flooding'][1:]) + np.array(results_BCAgent_Agentic[name]['CSO'][1:])
        bcag_fc = bcag_fc_raw[fc_plot_idx] / 1000
        ax.plot(dt_agg, bcag_fc, color=ccf['AgenticAI-BC'], alpha=0.6, linewidth=2.0, linestyle='--', zorder=5)

    # ---- LLM Event 垂直线 (按results_rainfall_event.py方式: 追踪等级+区分取消) ----
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

    # (legend 已移至图外统一绘制，见下方 fig.legend)

    # 标题 (Event1, Event2, ...)
    short_title = f'Event{idx + 1}'
    ax.set_title(short_title, fontsize=16)

# ---- 统一图例放在整个图的下方 (曲线 + 风险等级) ----
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
unified_handles = [
    Line2D([0], [0], color=ccf['BC'], linewidth=2.5, label='BC'),
]

# 检查是否有任意子图包含 MPC 数据
any_mpc = any(name in results_MPC for name in valid_scenario_names)
if any_mpc:
    unified_handles.append(
        Line2D([0], [0], color=ccf['MPC'], linewidth=2.5,
               linestyle=':', label='MPC')
    )

# 检查是否有任意子图包含 AgenticAI-BC 数据
any_bcagent = any(name in results_BCAgent_Agentic for name in valid_scenario_names)
if any_bcagent:
    unified_handles.append(
        Line2D([0], [0], color=ccf['AgenticAI-BC'], linewidth=2.5,
               linestyle='--', label='AgenticAI-Control')
    )

# 降雨柱状图图例 (放在最后)
unified_handles.append(
    Patch(facecolor='steelblue', edgecolor='navy', linewidth=0.3, alpha=0.4, label='Rainfall')
)

fig.legend(handles=unified_handles, fontsize=18, loc='lower center',
            ncol=len(unified_handles), frameon=True, fancybox=True, framealpha=0.95,
            bbox_to_anchor=(0.5, 0.0))

# 收紧底部边距，让legend更靠近图主体
fig.subplots_adjust(bottom=0.07)

# 保存图片到 Results/FigControlperformance 文件夹
fig_dir = os.path.join(project_root, 'Results', 'FigControlperformance')
os.makedirs(fig_dir, exist_ok=True)
out_fig_path = os.path.join(fig_dir, 'FC_curve_vs_rainfall_full.png')
plt.savefig(out_fig_path, dpi=200, bbox_inches='tight')
print(f"F+C 曲线图已保存: {out_fig_path}")
plt.close()



print("\n所有分析和图表生成完成！")


