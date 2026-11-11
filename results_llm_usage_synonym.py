# -*- coding: utf-8 -*-
"""
Aggregate token usage, API call cost, processed text volume and API latency for 4 BCAgent LLM variants.

Variants:
  - step3-BCAgent-control         -> DeepSeek-v4-flash
  - step3-BCAgent-control-GLM     -> GLM-4-flash
  - step3-BCAgent-control-Kimi    -> Moonshot-v1-8k
  - step3-BCAgent-control-MiniMax -> Minimax-M3

Outputs:
  - Results/LLMUsage/llm_usage_summary.csv  (summary per LLM variant)
  - Results/LLMUsage/llm_usage_by_event.csv (detail per event x LLM)
  - Results/LLMUsage/llm_improvement_usage_comparison.png (3x1: improvement / Token / Time violin plots)
  - Results/LLMUsage/llm-api-pricing-table.md (pricing reference table)

Usage:
    python results_llm_usage.py
"""

import sys
import os

_sys_parent = os.path.dirname(os.path.abspath(__file__))
_drl_control_dir = os.path.join(_sys_parent, 'DRL-control')

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import glob
from matplotlib import rcParams

import results_synonym_boxplot as syn_box   # Reuse the synonym experiment data loading and colors (for subplot d)

import matplotlib
config = {
    "font.size": 16,
    "mathtext.fontset": 'stix',
    "font.family": 'sans-serif',
    "font.sans-serif": ['Arial', 'DejaVu Sans', 'Microsoft YaHei', 'SimHei'],
    'axes.unicode_minus': False,
}
rcParams.update(config)

# ============================================================
# LLM variant configuration
# ============================================================
LLM_VARIANTS = {
    'DeepSeek-v4-flash': 'step3-BCAgent-control',
    'GLM-4-flash':       'step3-BCAgent-control-GLM',
    'Moonshot-v1-8k':    'step3-BCAgent-control-Kimi',
    'Minimax-M3':        'step3-BCAgent-control-MiniMax',
}

LLM_COLORS = {
    'DeepSeek-v4-flash': '#2e7d32',      # Dark green (same as AgenticAI-Control in results_varLLM.py / results_FC.py)
    'GLM-4-flash':       '#1f77b4',      # Blue (same as results_varLLM.py)
    'Moonshot-v1-8k':    '#9467bd',      # Purple (same as results_varLLM.py)
    'Minimax-M3':        '#ff7f0e',      # Orange (same as results_varLLM.py)
}

project_root = _sys_parent
scenarios_dir = os.path.join(project_root, 'Scenarios', 'NMC_Events_2015_2025')

# ============================================================
# LLM API pricing (CNY / million tokens)
# ============================================================
PRICING = {
    'DeepSeek-v4-flash': {'input': 1.00, 'output': 2.00},
    'GLM-4-flash':       {'input': 0.00, 'output': 0.00},
    'Moonshot-v1-8k':    {'input': 2.00, 'output': 10.00},
    'Minimax-M3':        {'input': 4.20, 'output': 16.80},
}

# ============================================================
# 1. Discover scenario names (based on BC results)
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
# 2. Load all LLM variant results and extract LLM call traces
# ============================================================
# llm_data[llm_label] = list of flat trace records
llm_data = {}

for llm_label, dir_name in LLM_VARIANTS.items():
    records = []
    for name in scenario_names:
        llm_path = os.path.join(project_root, 'DRL-control', dir_name,
                                'results', f'bc_agent_results_{name}.npy')
        if not os.path.exists(llm_path):
            print(f"  [{llm_label}] 未找到结果: {llm_path}")
            continue

        result = np.load(llm_path, allow_pickle=True).tolist()
        full_trace = result.get('llm_full_trace', [])
        if not full_trace:
            continue

        for trace in full_trace:
            if not isinstance(trace, dict):
                continue
            # Keep only real LLM API call records; filter out housekeeping traces
            if trace.get('trace_type') != 'mode_a_full_analysis':
                continue

            # Extract the text character count
            prompt_chars = len(trace.get('mode_a_prompt', ''))
            response_chars = len(trace.get('mode_a_raw_response', ''))
            prompt_tokens = trace.get('prompt_tokens', 0)
            completion_tokens = trace.get('completion_tokens', 0)
            total_tokens = trace.get('total_tokens', 0)

            # Compute the cost of this call
            price_cfg = PRICING[llm_label]
            cost = (prompt_tokens / 1e6) * price_cfg['input'] + (completion_tokens / 1e6) * price_cfg['output']

            rec = {
                'llm_label': llm_label,
                'scenario': name,
                'step': trace.get('step', 0),
                'prompt_chars': prompt_chars,
                'response_chars': response_chars,
                'total_chars': prompt_chars + response_chars,
                'api_call_time_ms': trace.get('api_call_time_ms', 0.0),
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_tokens': total_tokens,
                'cost': cost,
            }
            records.append(rec)

    llm_data[llm_label] = records
    print(f"  [{llm_label}] 加载 {len(records)} 条 LLM 调用记录")

# ============================================================
# 2b. Load BC results (to compute improvement rates)
# ============================================================
results_BC = {}
for name in scenario_names:
    bc_path = os.path.join(project_root, 'DRL-control', 'step1-BC-control', 'results', f'bc_results_{name}.npy')
    if os.path.exists(bc_path):
        results_BC[name] = np.load(bc_path, allow_pickle=True).tolist()

# ============================================================
# 2c. Compute F+C improvement over BC for each LLM (one value per event)
# ============================================================
llm_improvement_vs_BC = {}   # {llm_label: [imp1, imp2, ...]}
llm_fc_by_event = {}          # {llm_label: {scenario_name: fc_value}} - absolute F+C values (for hypothesis tests)
for llm_label, dir_name in LLM_VARIANTS.items():
    imp_vs_bc = []
    llm_fc_by_event[llm_label] = {}
    for name in scenario_names:
        llm_path = os.path.join(project_root, 'DRL-control', dir_name,
                                'results', f'bc_agent_results_{name}.npy')
        if name not in results_BC:
            continue
        if not os.path.exists(llm_path):
            continue

        llm_result = np.load(llm_path, allow_pickle=True).tolist()
        bc_fc = results_BC[name]['flooding'][-1] + results_BC[name]['CSO'][-1]
        llm_fc = llm_result['flooding'][-1] + llm_result['CSO'][-1]
        llm_fc_by_event[llm_label][name] = llm_fc  # Save absolute values for the hypothesis tests

        if bc_fc > 0:
            imp_vs_bc.append((bc_fc - llm_fc) / bc_fc * 100)

    llm_improvement_vs_BC[llm_label] = imp_vs_bc
    if imp_vs_bc:
        print(f"  [{llm_label}] vsBC 平均提升: {np.mean(imp_vs_bc):.2f}% ({len(imp_vs_bc)} 事件)")

# ============================================================
# 3. Check data availability
# ============================================================
has_tokens = any(
    any(r.get('total_tokens', 0) > 0 for r in records)
    for records in llm_data.values()
)
has_timing = any(
    any(r.get('api_call_time_ms', 0) > 0 for r in records)
    for records in llm_data.values()
)

print(f"\nToken 数据可用: {'是' if has_tokens else '否 (需重新运行模拟)'}")
print(f"耗时数据可用: {'是' if has_timing else '否 (需重新运行模拟)'}")

# ============================================================
# 4. Aggregate statistics by LLM variant
# ============================================================
print("\n" + "=" * 90)
print("按 LLM 变体汇总 - Token 用量 / 花费 / 文本量 / 调用耗时")
print("=" * 90)

summary_rows = []
for llm_label in LLM_VARIANTS:
    records = llm_data.get(llm_label, [])
    if not records:
        print(f"  [{llm_label}] 无数据")
        continue

    n_calls = len(records)
    total_prompt_c = sum(r['prompt_chars'] for r in records)
    total_response_c = sum(r['response_chars'] for r in records)
    total_c = sum(r['total_chars'] for r in records)
    avg_prompt_c = total_prompt_c / n_calls
    avg_response_c = total_response_c / n_calls
    avg_total_c = total_c / n_calls

    total_pt = sum(r['prompt_tokens'] for r in records)
    total_ct = sum(r['completion_tokens'] for r in records)
    total_tt = sum(r['total_tokens'] for r in records)
    avg_pt = total_pt / n_calls
    avg_ct = total_ct / n_calls
    avg_tt = total_tt / n_calls

    times = [r['api_call_time_ms'] for r in records if r['api_call_time_ms'] > 0]
    avg_time = np.mean(times) if times else 0
    max_time = np.max(times) if times else 0
    min_time = np.min(times) if times else 0

    total_cost = sum(r['cost'] for r in records)
    avg_cost = total_cost / n_calls
    costs_list = [r['cost'] for r in records]
    max_cost = max(costs_list)

    row = {
        'LLM': llm_label,
        '调用次数': n_calls,
        '总Prompt字符': total_prompt_c,
        '总Response字符': total_response_c,
        '总文本字符': total_c,
        '平均Prompt字符': round(avg_prompt_c, 1),
        '平均Response字符': round(avg_response_c, 1),
        '平均文本字符': round(avg_total_c, 1),
        '平均Prompt_Tokens': round(avg_pt, 1),
        '平均Completion_Tokens': round(avg_ct, 1),
        '平均Total_Tokens': round(avg_tt, 1),
        '总Prompt_Tokens': total_pt,
        '总Completion_Tokens': total_ct,
        '总Tokens': total_tt,
        '总花费(¥)': round(total_cost, 6),
        '平均花费(¥)': round(avg_cost, 6),
        '最大花费(¥)': round(max_cost, 6),
        '输入价格(¥/1M)': PRICING[llm_label]['input'],
        '输出价格(¥/1M)': PRICING[llm_label]['output'],
        '平均耗时ms': round(avg_time, 1),
        '最大耗时ms': round(max_time, 1),
        '最小耗时ms': round(min_time, 1),
    }
    summary_rows.append(row)

    print(f"\n  [{llm_label}]")
    print(f"    调用次数: {n_calls}")
    print(f"    文本量:  平均 {avg_total_c:.0f} chars/次 (Prompt {avg_prompt_c:.0f} + Response {avg_response_c:.0f})")
    print(f"            总计 {total_c:,} chars")
    print(f"    Tokens:  平均 {avg_tt:.1f}/次 (Prompt {avg_pt:.1f} + Completion {avg_ct:.1f})")
    print(f"            总计 {total_tt:,} tokens")
    print(f"    花费:    平均 ¥{avg_cost:.6f}/次, 总计 ¥{total_cost:.4f}")
    print(f"            (输入 ¥{PRICING[llm_label]['input']}/1M + 输出 ¥{PRICING[llm_label]['output']}/1M)")
    if avg_time > 0:
        print(f"    耗时:    平均 {avg_time:.0f}ms, 最小 {min_time:.0f}ms, 最大 {max_time:.0f}ms")
    else:
        print(f"    耗时:    N/A (需重新运行模拟获取)")

df_summary = pd.DataFrame(summary_rows)

# ============================================================
# 5. Aggregate by event x LLM variant (detailed table)
# ============================================================
print("\n" + "=" * 90)
print("按事件 × LLM 变体 - 每条记录的详细统计")
print("=" * 90)

detail_rows = []
for llm_label in LLM_VARIANTS:
    records = llm_data.get(llm_label, [])
    for rec in records:
        detail_rows.append(rec)

if detail_rows:
    df_detail = pd.DataFrame(detail_rows)

    # Aggregate by scenario + LLM
    event_summary = df_detail.groupby(['llm_label', 'scenario']).agg(
        调用次数=('total_tokens', 'count'),
        平均Total_Tokens=('total_tokens', 'mean'),
        平均Prompt_Tokens=('prompt_tokens', 'mean'),
        平均Completion_Tokens=('completion_tokens', 'mean'),
        总Tokens=('total_tokens', 'sum'),
        平均Prompt字符=('prompt_chars', 'mean'),
        平均Response字符=('response_chars', 'mean'),
        平均总字符=('total_chars', 'mean'),
        总花费=('cost', 'sum'),
        平均花费=('cost', 'mean'),
        平均耗时ms=('api_call_time_ms', 'mean'),
    ).reset_index()
    event_summary = event_summary.round(1)
    print(event_summary.to_string(index=False))
    df_event_summary = event_summary
else:
    df_event_summary = pd.DataFrame()

# ============================================================
# 6. Save the CSV
# ============================================================
output_dir = os.path.join(project_root, 'Results', 'LLMUsage')
os.makedirs(output_dir, exist_ok=True)

df_summary.to_csv(os.path.join(output_dir, 'llm_usage_summary.csv'), index=False)
if not df_event_summary.empty:
    df_event_summary.to_csv(os.path.join(output_dir, 'llm_usage_by_event.csv'), index=False)

print(f"\n汇总表已保存: {os.path.join(output_dir, 'llm_usage_summary.csv')}")

# ============================================================
# 7. Hypothesis test: consistency of the 4 LLM controllers (Friedman + Nemenyi)
# ============================================================
print("\n" + "=" * 90)
print("假设检验: 4 个 LLM 控制效果一致性 (Friedman 检验)")
print("=" * 90)

import importlib.util
from scipy import stats
from scipy.stats import rankdata
from itertools import combinations

# Detect scikit-posthocs (use find_spec instead of try-except)
has_sp = importlib.util.find_spec('scikit_posthocs') is not None
if has_sp:
    import scikit_posthocs as sp
else:
    print("  [警告] 未安装 scikit-posthocs, Nemenyi 事后检验将被跳过")
    print("         安装: pip install scikit-posthocs")

ALPHA = 0.05

# ---- Build the aligned F+C matrix ----
# Keep only events where all LLMs have results, ensuring complete pairing
test_llms = [l for l in LLM_VARIANTS if l in llm_fc_by_event and len(llm_fc_by_event[l]) > 0]
common_scenarios = set(scenario_names)
for llm_label in test_llms:
    common_scenarios &= set(llm_fc_by_event[llm_label].keys())
common_scenarios = sorted(common_scenarios)

print(f"\n参与检验的 LLM: {test_llms}")
print(f"共同事件数 (区组数 n): {len(common_scenarios)}")
print(f"LLM 数 (处理数 k): {len(test_llms)}")

fc_matrix = np.array([
    [llm_fc_by_event[llm][name] for llm in test_llms]
    for name in common_scenarios
])  # shape (n_events, n_llms)

n_events = fc_matrix.shape[0]
k_llms = fc_matrix.shape[1]

# ---- Descriptive statistics ----
print("\n--- 描述统计 (F+C 绝对值, m³) ---")
desc_rows = []
for j, llm in enumerate(test_llms):
    col = fc_matrix[:, j]
    print(f"  {llm:20s}: 均值={np.mean(col):.1f}, 中位数={np.median(col):.1f}, "
          f"标准差={np.std(col, ddof=1):.1f}, 最小={np.min(col):.1f}, 最大={np.max(col):.1f}")
    desc_rows.append({
        'LLM': llm,
        '事件数': n_events,
        '均值': round(np.mean(col), 2),
        '中位数': round(np.median(col), 2),
        '标准差': round(np.std(col, ddof=1), 2),
        '最小值': round(np.min(col), 2),
        '最大值': round(np.max(col), 2),
    })

# ---- Normality test (Shapiro-Wilk on residuals, for reference only) ----
grand_mean = fc_matrix.mean()
row_means = fc_matrix.mean(axis=1, keepdims=True)
col_means = fc_matrix.mean(axis=0, keepdims=True)
residuals = fc_matrix - row_means - col_means + grand_mean
shapiro_stat, shapiro_p = stats.shapiro(residuals.flatten())
normal_ok = shapiro_p > ALPHA
print(f"\n--- 正态性检验 (Shapiro-Wilk, 残差) ---")
print(f"  W = {shapiro_stat:.4f}, p = {shapiro_p:.4f}")
print(f"  残差正态性: {'满足' if normal_ok else '不满足'} (p {'>' if normal_ok else '<='} {ALPHA})")
print(f"  注: 小样本下正态性仅供参考, 主检验使用非参数 Friedman")

# ---- Friedman test (primary test) ----
print(f"\n--- 主检验: Friedman χ² (α = {ALPHA}) ---")
columns_fc = [fc_matrix[:, j] for j in range(k_llms)]
friedman_stat, friedman_p = stats.friedmanchisquare(*columns_fc)
print(f"  Friedman χ² = {friedman_stat:.4f}")
print(f"  p 值 = {friedman_p:.6f}")

# Effect size: Kendall's W
kendall_w = friedman_stat / (n_events * (k_llms - 1))
print(f"  Kendall's W (效应量) = {kendall_w:.4f}")

friedman_significant = friedman_p < ALPHA
if friedman_significant:
    print(f"  结论: 拒绝 H0 — 至少有一对 LLM 控制效果有显著差异")
else:
    print(f"  结论: 不能拒绝 H0 — {k_llms} 个 LLM 控制效果无显著差异")

# ---- Friedman ranks (rank 1 = lowest F+C = best) ----
ranks_matrix = np.zeros_like(fc_matrix)
for i in range(n_events):
    ranks_matrix[i] = rankdata(fc_matrix[i], method='average')
avg_ranks = ranks_matrix.mean(axis=0)
print("\n--- 平均秩 (rank 1 = F+C 最低 = 最优) ---")
for j, llm in enumerate(test_llms):
    print(f"  {llm:20s}: {avg_ranks[j]:.2f}")

# ---- Nemenyi post-hoc test ----
nemenyi_p_matrix = None
CD = None
if has_sp:
    print(f"\n--- 事后检验: Nemenyi (α = {ALPHA}) ---")
    nemenyi_p_matrix = sp.posthoc_nemenyi_friedman(fc_matrix)
    nemenyi_p_matrix.index = test_llms
    nemenyi_p_matrix.columns = test_llms
    print("  Nemenyi 校正后 p 值矩阵:")
    print(nemenyi_p_matrix.round(4).to_string())

    # Critical difference CD (q_alpha from tables: alpha=0.05)
    q_alpha_table = {3: 2.343, 4: 2.569, 5: 2.728, 6: 2.850}
    q_alpha = q_alpha_table.get(k_llms, 2.569)
    CD = q_alpha * np.sqrt(k_llms * (k_llms + 1) / (6 * n_events))
    print(f"\n  临界差异 CD = {CD:.4f} (q_α={q_alpha}, k={k_llms}, n={n_events})")
    print(f"  秩差 < CD 的 LLM 对 → 无显著差异")

    for i in range(k_llms):
        for j in range(i + 1, k_llms):
            p_val = nemenyi_p_matrix.iloc[i, j]
            rank_diff = abs(avg_ranks[i] - avg_ranks[j])
            sig = p_val < ALPHA
            print(f"    {test_llms[i]:20s} vs {test_llms[j]:20s}: p={p_val:.4f}, "
                  f"秩差={rank_diff:.2f}, {'显著' if sig else '不显著'}")

# ---- Wilcoxon signed-rank test + Holm correction (robustness check) ----
print(f"\n--- 稳健性补充: Wilcoxon 符号秩 + Holm 校正 (α = {ALPHA}) ---")
pair_indices = list(combinations(range(k_llms), 2))
raw_p_values = []
for i, j in pair_indices:
    diff = fc_matrix[:, i] - fc_matrix[:, j]
    if np.all(diff == 0):
        stat_w, p_w = np.nan, 1.0
    else:
        stat_w, p_w = stats.wilcoxon(fc_matrix[:, i], fc_matrix[:, j])
    raw_p_values.append(p_w)
    print(f"  {test_llms[i]:20s} vs {test_llms[j]:20s}: W={stat_w:.1f}, p={p_w:.4f}")

# Holm correction (step-down procedure)
m_tests = len(raw_p_values)
sorted_order = np.argsort(raw_p_values)
holm_adjusted = np.array(raw_p_values, dtype=float)
running_max = 0.0
for pos, orig_idx in enumerate(sorted_order):
    adj = raw_p_values[orig_idx] * (m_tests - pos)
    if adj > running_max:
        running_max = adj
    holm_adjusted[orig_idx] = min(running_max, 1.0)

print("\n  Holm 校正后:")
for pos, (i, j) in enumerate(pair_indices):
    p_adj = holm_adjusted[pos]
    sig = p_adj < ALPHA
    print(f"    {test_llms[i]:20s} vs {test_llms[j]:20s}: p_adj={p_adj:.4f}, "
          f"{'显著' if sig else '不显著'}")

# ---- Save the text report ----
report_lines = []
report_lines.append("=" * 80)
report_lines.append("LLM 控制效果一致性假设检验报告")
report_lines.append(f"生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
report_lines.append("=" * 80)
report_lines.append("")
report_lines.append("一、实验设计")
report_lines.append(f"  设计类型: 随机化完全区组设计 (RCBD) / 重复测量")
report_lines.append(f"  处理因子 (k): {k_llms} 个 LLM — {', '.join(test_llms)}")
report_lines.append(f"  区组因子 (n): {n_events} 场降雨事件")
report_lines.append(f"  响应变量: 绝对 F+C 值 (flooding[-1] + CSO[-1], m³)")
report_lines.append(f"  显著性水平 α: {ALPHA}")
report_lines.append("")
report_lines.append("二、描述统计")
for row in desc_rows:
    report_lines.append(f"  {row['LLM']}: 均值={row['均值']}, 中位数={row['中位数']}, "
                        f"标准差={row['标准差']}, 范围=[{row['最小值']}, {row['最大值']}]")
report_lines.append("")
report_lines.append("三、正态性检验 (Shapiro-Wilk, 残差)")
report_lines.append(f"  W = {shapiro_stat:.4f}, p = {shapiro_p:.4f}")
report_lines.append(f"  残差正态性: {'满足' if normal_ok else '不满足'}")
report_lines.append(f"  注: 小样本下正态性仅供参考, 主检验使用非参数 Friedman")
report_lines.append("")
report_lines.append("四、主检验: Friedman χ²")
report_lines.append(f"  H0: {k_llms} 个 LLM 的控制效果分布相同")
report_lines.append(f"  χ² = {friedman_stat:.4f}")
report_lines.append(f"  p 值 = {friedman_p:.6f}")
report_lines.append(f"  Kendall's W (效应量) = {kendall_w:.4f}")
if friedman_significant:
    report_lines.append(f"  结论: 拒绝 H0 — 至少有一对 LLM 控制效果有显著差异")
else:
    report_lines.append(f"  结论: 不能拒绝 H0 — {k_llms} 个 LLM 控制效果无显著差异")
report_lines.append("")
report_lines.append("五、平均秩 (rank 1 = F+C 最低 = 最优)")
for j, llm in enumerate(test_llms):
    report_lines.append(f"  {llm}: {avg_ranks[j]:.2f}")
report_lines.append("")

if has_sp:
    report_lines.append("六、事后检验: Nemenyi")
    report_lines.append(f"  临界差异 CD = {CD:.4f}")
    report_lines.append("  校正后 p 值矩阵:")
    for i in range(k_llms):
        for j in range(i + 1, k_llms):
            p_val = nemenyi_p_matrix.iloc[i, j]
            rank_diff = abs(avg_ranks[i] - avg_ranks[j])
            report_lines.append(f"    {test_llms[i]} vs {test_llms[j]}: p={p_val:.4f}, "
                                f"秩差={rank_diff:.2f}, {'显著' if p_val < ALPHA else '不显著'}")
    report_lines.append("")

report_lines.append("七、稳健性补充: Wilcoxon 符号秩 + Holm 校正")
for pos, (i, j) in enumerate(pair_indices):
    p_adj = holm_adjusted[pos]
    report_lines.append(f"  {test_llms[i]} vs {test_llms[j]}: p_adj={p_adj:.4f}, "
                        f"{'显著' if p_adj < ALPHA else '不显著'}")
report_lines.append("")
report_lines.append("=" * 80)

report_path = os.path.join(output_dir, 'hypothesis_test_report.txt')
with open(report_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(report_lines))
print(f"\n报告已保存: {report_path}")

# ---- Save the CSV summary table ----
summary_rows_ht = []
summary_rows_ht.append({
    '检验类型': 'Friedman',
    '对比': '全局',
    '统计量': round(friedman_stat, 4),
    'p值': round(friedman_p, 6),
    '效应量(Kendall_W)': round(kendall_w, 4),
    '显著性': '是' if friedman_significant else '否',
    '结论': '拒绝H0' if friedman_significant else '不拒绝H0',
})
for pos, (i, j) in enumerate(pair_indices):
    summary_rows_ht.append({
        '检验类型': 'Nemenyi',
        '对比': f"{test_llms[i]} vs {test_llms[j]}",
        '统计量': '',
        'p值': round(nemenyi_p_matrix.iloc[i, j], 4) if has_sp else '',
        '效应量(Kendall_W)': round(abs(avg_ranks[i] - avg_ranks[j]), 2) if has_sp else '',
        '显著性': '是' if (has_sp and nemenyi_p_matrix.iloc[i, j] < ALPHA) else '否',
        '结论': '',
    })
    summary_rows_ht.append({
        '检验类型': 'Wilcoxon+Holm',
        '对比': f"{test_llms[i]} vs {test_llms[j]}",
        '统计量': '',
        'p值': round(holm_adjusted[pos], 4),
        '效应量(Kendall_W)': '',
        '显著性': '是' if holm_adjusted[pos] < ALPHA else '否',
        '结论': '',
    })

df_ht = pd.DataFrame(summary_rows_ht)
csv_path = os.path.join(output_dir, 'hypothesis_test_summary.csv')
df_ht.to_csv(csv_path, index=False)
print(f"汇总表已保存: {csv_path}")

# ---- Nemenyi CD diagram ----
if has_sp:
    fig_cd, ax_cd = plt.subplots(dpi=150, figsize=(14, 3.2))

    sorted_idx = np.argsort(avg_ranks)
    sorted_llms = [test_llms[i] for i in sorted_idx]
    sorted_ranks = avg_ranks[sorted_idx]
    sorted_colors = [LLM_COLORS[llm] for llm in sorted_llms]

    n_plot = len(sorted_llms)

    # All points are drawn on the horizontal line y=0
    for i in range(n_plot):
        ax_cd.scatter(sorted_ranks[i], 0, color=sorted_colors[i],
                      s=280, zorder=5, edgecolors='black', linewidths=1.2)
        # Labels below the points
        ax_cd.text(sorted_ranks[i], -0.12, sorted_llms[i],
                   va='top', ha='center', fontsize=12, fontweight='bold', rotation=15)
        # Rank annotations
        ax_cd.text(sorted_ranks[i], 0.08, f'{sorted_ranks[i]:.2f}',
                   va='bottom', ha='center', fontsize=10, color='gray')

    # Connect LLM pairs with no significant difference (rank difference < CD) - line above
    level = 0.22
    for i in range(n_plot):
        for j in range(i + 1, n_plot):
            if sorted_ranks[j] - sorted_ranks[i] < CD:
                ax_cd.plot([sorted_ranks[i], sorted_ranks[j]], [level, level],
                           'k-', linewidth=2.5, zorder=3, solid_capstyle='round')
                level += 0.13

    ax_cd.axhline(y=0, color='gray', linewidth=0.5, alpha=0.5)
    ax_cd.set_xlabel('Average Rank (lower = better F+C)', fontsize=14)
    ax_cd.set_title(f'Nemenyi CD Diagram (CD={CD:.3f}, α={ALPHA}, n={n_events})',
                    fontsize=14)
    ax_cd.set_yticks([])
    ax_cd.set_xlim(left=0.5, right=k_llms + 0.5)
    ax_cd.set_ylim(bottom=-0.55, top=level + 0.15)
    ax_cd.grid(axis='x', alpha=0.3)

    plt.tight_layout()
    cd_fig_path = os.path.join(output_dir, 'nemenyi_cd_diagram.png')
    plt.savefig(cd_fig_path, dpi=200, bbox_inches='tight')
    print(f"Nemenyi CD 图已保存: {cd_fig_path}")
    plt.close()

print("\n假设检验完成！")

# ============================================================
# 8. Generate a 3x1 figure: (1) improvement violin (2) token usage (3) call latency
# ============================================================
print("\n生成 LLM 用量与提升率对比图...")

# Filter LLM variants that have data
available_llms = [l for l in LLM_VARIANTS if llm_data.get(l)]
n_available = len(available_llms)
llm_colors_list = [LLM_COLORS[l] for l in available_llms]

# ---- Data preparation ----
# Token / time data (one row per call)
token_data = []
time_data = []
for llm_label in available_llms:
    records = llm_data[llm_label]
    token_data.append([r['total_tokens'] for r in records])
    time_data.append([r['api_call_time_ms'] for r in records if r['api_call_time_ms'] > 0])

# Improvement data (one value per event, vs BC only)
imp_bc_data = []
for llm_label in available_llms:
    imp_bc_data.append(llm_improvement_vs_BC.get(llm_label, []))

positions = np.arange(1, n_available + 1)

fig, axes = plt.subplots(4, 1, dpi=150, figsize=(12, 10.8))

# ---- Subplot 1: F+C improvement over BC by LLM (violin plot) ----
ax1 = axes[0]

vp_bc = ax1.violinplot(imp_bc_data, positions=positions,
                        showmeans=True, showmedians=True, widths=0.7)
for i, body in enumerate(vp_bc['bodies']):
    body.set_facecolor(llm_colors_list[i])
    body.set_alpha(0.55)
    body.set_edgecolor('none')
for part in ('cmeans', 'cmedians', 'cbars'):
    if part in vp_bc:
        vp_bc[part].set_color('black')
        vp_bc[part].set_linewidth(1.0)

# Overlay jittered scatter points
for i in range(n_available):
    if imp_bc_data[i]:
        jitter = np.random.normal(positions[i], 0.06, size=len(imp_bc_data[i]))
        ax1.scatter(jitter, imp_bc_data[i], color=llm_colors_list[i], alpha=0.5,
                    s=25, edgecolors='none')

ax1.set_xticks(positions)
ax1.set_xticklabels(available_llms, fontsize=14)
ax1.set_ylabel('Improvement rate'+'\n'+'vs. BC (%)', fontsize=15)
# No fixed ylim: vs-BC improvement is about 40~49%; the old set_ylim(50,100) clipped all data, so let it auto-scale
ax1.axhline(y=0, color='gray', linestyle='--', linewidth=1.0, alpha=0.6)
ax1.grid(axis='y', alpha=0.3)

# Subplot label
ax1.text(-0.08, 1.03, '(a)', transform=ax1.transAxes,
         fontsize=18, fontweight='bold', va='bottom', ha='left')

# Hypothesis test result annotation (Friedman, placed at the bottom of the subplot)
ht_conclusion = 'No significant difference' if not friedman_significant else 'Significant difference'
ht_text = (f"Friedman: $\\chi^2$={friedman_stat:.2f}, p={friedman_p:.4f}, "
           f"{ht_conclusion} ($\\alpha$=0.05)")
ax1.text(0.5, 0.15, ht_text, transform=ax1.transAxes, fontsize=14,
         va='bottom', ha='center', bbox=dict(boxstyle='round,pad=0.4',
         facecolor='white', edgecolor='gray', alpha=0.9))

# ---- Subplot 2: total tokens per call (violin plot) ----
ax2 = axes[1]
vp2 = ax2.violinplot(token_data, positions=positions, showmeans=True,
                      showmedians=True, widths=0.7)
for i, body in enumerate(vp2['bodies']):
    body.set_facecolor(llm_colors_list[i])
    body.set_alpha(0.55)
    body.set_edgecolor('none')
for part in ('cmeans', 'cmedians', 'cbars'):
    if part in vp2:
        vp2[part].set_color('black')
        vp2[part].set_linewidth(1.0)

for i, data in enumerate(token_data):
    jitter = np.random.normal(positions[i], 0.06, size=len(data))
    ax2.scatter(jitter, data, color=llm_colors_list[i], alpha=0.5, s=25,
                edgecolors='none')

ax2.set_xticks(positions)
ax2.set_xticklabels(available_llms, fontsize=14)
ax2.set_ylabel('Tokens usage'+'\n'+'per call', fontsize=15)
ax2.grid(axis='y', alpha=0.3)

ax2.text(-0.08, 1.03, '(b)', transform=ax2.transAxes,
         fontsize=18, fontweight='bold', va='bottom', ha='left')

# ---- Subplot 3: API call time per call (violin plot) ----
ax3 = axes[2]
vp3 = ax3.violinplot(time_data, positions=positions, showmeans=True,
                      showmedians=True, widths=0.7)
for i, body in enumerate(vp3['bodies']):
    body.set_facecolor(llm_colors_list[i])
    body.set_alpha(0.55)
    body.set_edgecolor('none')
for part in ('cmeans', 'cmedians', 'cbars'):
    if part in vp3:
        vp3[part].set_color('black')
        vp3[part].set_linewidth(1.0)

for i, data in enumerate(time_data):
    jitter = np.random.normal(positions[i], 0.06, size=len(data))
    ax3.scatter(jitter, data, color=llm_colors_list[i], alpha=0.5, s=25,
                edgecolors='none')

ax3.set_xticks(positions)
ax3.set_xticklabels(available_llms, fontsize=14)
ax3.set_ylabel('API call time (ms)', fontsize=15)
ax3.grid(axis='y', alpha=0.3)

ax3.text(-0.08, 1.03, '(c)', transform=ax3.transAxes,
         fontsize=18, fontweight='bold', va='bottom', ha='left')

# ---- Subplot 4 (d): per-event deviation from baseline under synonym perturbation by LLM (violin, same style as (a)) ----
# Data: mean relative deviation from baseline (%) per (event, LLM) (signed, one value per event)
# Top annotation: a single CoV per LLM (std/mean x100, averaged over events); see results_synonym_boxplot for the computation
ax4 = axes[3]

_syn_data, _syn_events = syn_box.load_synonym_data()
_syn_baseline = syn_box.load_baseline_data(_syn_events)

# Mean relative deviation (%) per (event, LLM) = mean([(v-base)/base*100 for v in variants])
_rel_dev = {}      # {event: {llm: mean_rel_dev%}}
_cov_per_llm = {}  # {llm: single CoV %}
for _llm in syn_box.LLM_NAMES:
    _covs = []
    for _en in _syn_events:
        _rel_dev.setdefault(_en, {})
        _fv = _syn_data.get(_en, {}).get(_llm, [])
        _bv = _syn_baseline.get(_en, {}).get(_llm)
        if _fv and _bv and _bv > 0:
            _rd = float(np.mean([(v - _bv) / _bv * 100 for v in _fv]))
            _rel_dev[_en][_llm] = _rd
        else:
            _rel_dev[_en][_llm] = float('nan')
        # CoV uses raw F+C across variants (std/mean x100), averaged over events -> one value per LLM
        if len(_fv) >= 2:
            _mv = float(np.mean(_fv))
            if _mv > 0:
                _covs.append(float(np.std(_fv, ddof=1)) / _mv * 100)
    _cov_per_llm[_llm] = float(np.mean(_covs)) if _covs else float('nan')

# Per-event deviation list per LLM (violin data, one value per event)
_rd_data = []
for _llm in syn_box.LLM_NAMES:
    _vals = [_rel_dev.get(_en, {}).get(_llm, float('nan')) for _en in _syn_events]
    _rd_data.append([v for v in _vals if not np.isnan(v)])

positions_d = np.arange(1, len(syn_box.LLM_NAMES) + 1)

# Violin plot (same style as (a))
vp4 = ax4.violinplot(_rd_data, positions=positions_d, showmeans=True,
                     showmedians=True, widths=0.7)
for i, body in enumerate(vp4['bodies']):
    body.set_facecolor(LLM_COLORS[syn_box.LLM_NAMES[i]])
    body.set_alpha(0.55)
    body.set_edgecolor('none')
for part in ('cmeans', 'cmedians', 'cbars'):
    if part in vp4:
        vp4[part].set_color('black')
        vp4[part].set_linewidth(1.0)

# Overlay jittered scatter points, same as (a)
for i in range(len(syn_box.LLM_NAMES)):
    if _rd_data[i]:
        jitter = np.random.normal(positions_d[i], 0.06, size=len(_rd_data[i]))
        ax4.scatter(jitter, _rd_data[i], color=LLM_COLORS[syn_box.LLM_NAMES[i]],
                    alpha=0.5, s=25, edgecolors='none')

# Place each LLM's single CoV directly above its violin (top aligned)
_ylo, _yhi = ax4.get_ylim()
ax4.set_ylim(_ylo, _yhi + (_yhi - _ylo) * 0.16)   # Leave space at the top for the CoV labels
for i, _llm in enumerate(syn_box.LLM_NAMES):
    _cv = _cov_per_llm[_llm]
    if np.isnan(_cv):
        continue
    ax4.text(positions_d[i], _yhi + (_yhi - _ylo) * 0.03,
             f'CoV={_cv:.2f}%', ha='center', va='bottom',
             fontsize=14, fontweight='bold', color=LLM_COLORS[_llm])

ax4.set_xticks(positions_d)
ax4.set_xticklabels(syn_box.LLM_NAMES, fontsize=14)
ax4.set_ylabel('Relative deviation\nfrom baseline (%)', fontsize=15)
ax4.axhline(0, color='gray', linewidth=1.0, linestyle='--', alpha=0.6)
ax4.grid(axis='y', alpha=0.3)

ax4.text(-0.08, 1.03, '(d)', transform=ax4.transAxes,
         fontsize=18, fontweight='bold', va='bottom', ha='left')

plt.tight_layout()

# Save to the Results/LLMUsage folder
fig_dir = os.path.join(project_root, 'Results', 'LLMUsage')
os.makedirs(fig_dir, exist_ok=True)
out_fig_path = os.path.join(fig_dir, 'llm_improvement_usage_comparison.png')
plt.savefig(out_fig_path, dpi=200, bbox_inches='tight')
print(f"提升率与用量对比图已保存: {out_fig_path}")
plt.close()

print("\n所有统计和图表生成完成！")
