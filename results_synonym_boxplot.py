# -*- coding: utf-8 -*-
"""
不确定性分析 — 同义词干扰实验箱型图。

展示不同降雨事件下，4个LLM后端在同义词prompt扰动下的 Flooding+CSO 分布。
每个子图对应一个降雨事件，内含4个LLM的箱型图（跨variant聚合）。

用法:
    python results_synonym_boxplot.py
"""

import sys
import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import rcParams
import glob

# ── 路径设置 ──────────────────────────────────────────────
_sys_parent = os.path.dirname(os.path.abspath(__file__))
_drl_control_dir = os.path.join(_sys_parent, 'DRL-control')

# ── 中文字体 & 样式 ───────────────────────────────────────
config = {
    "font.size": 14,
    "mathtext.fontset": 'stix',
    "font.family": 'sans-serif',
    "font.sans-serif": ['Arial', 'DejaVu Sans'],
    'axes.unicode_minus': False,
}
rcParams.update(config)

# ── LLM 配置 (与 results_varLLM.py 一致) ──────────────────
LLM_NAMES = ['DeepSeek-v4-flash', 'GLM-4-flash', 'Moonshot-v1-8k', 'Minimax-M3']
LLM_DIR_MAP = {
    'DeepSeek-v4-flash': 'DeepSeek',
    'GLM-4-flash':       'GLM',
    'Moonshot-v1-8k':    'Kimi',
    'Minimax-M3':        'MiniMax',
}

COLORS = {
    'DeepSeek-v4-flash': '#2e7d32',   # 深绿
    'GLM-4-flash':       '#1f77b4',   # 蓝
    'Moonshot-v1-8k':    '#9467bd',   # 紫
    'Minimax-M3':        '#ff7f0e',    # 橙
}

# ── 数据路径 ──────────────────────────────────────────────
SYNONYM_BASE = os.path.join(_drl_control_dir, 'step4-uncertainty',
                            'results_uncertainty', 'synonym')
BASELINE_BASE = os.path.join(_drl_control_dir, 'step4-uncertainty',
                             'results_uncertainty', 'baseline')

# ── 加载数据 ──────────────────────────────────────────────
def load_synonym_data():
    """
    返回 dict[event_short_name][llm_label] -> list[float] (各 variant 的 F+C)
    """
    # 发现所有事件名（从任意一个LLM的 variant_0 目录获取）
    first_llm_dir = os.path.join(SYNONYM_BASE, 'DeepSeek', 'variant_0')
    event_files = sorted(glob.glob(os.path.join(first_llm_dir, '*.npy')))
    event_names = []
    for f in event_files:
        basename = os.path.basename(f)
        # results_Event_XX_日期_预警.npy -> Event_XX
        name = basename.replace('results_', '').replace('.npy', '')
        # 提取短名称 Event_XX
        parts = name.split('_')
        short = '_'.join(parts[:2]) if len(parts) >= 2 else name
        event_names.append((short, f))  # (短名, 完整文件路径模板)

    # 组织数据: {event_short: {llm: [fc_values_per_variant]}}
    data = {}
    for short_name, _ in event_names:
        data[short_name] = {}

    for llm_label, llm_dir in LLM_DIR_MAP.items():
        llm_base = os.path.join(SYNONYM_BASE, llm_dir)
        if not os.path.isdir(llm_base):
            print(f"  警告: 目录不存在 {llm_base}")
            continue

        # 发现所有 variant
        variant_dirs = sorted(
            [d for d in os.listdir(llm_base)
             if os.path.isdir(os.path.join(llm_base, d)) and d.startswith('variant_')]
        )

        for short_name, template_path in event_names:
            fc_list = []
            for vdir in variant_dirs:
                # 在该 variant 目录下查找匹配的文件
                vpath = os.path.join(llm_base, vdir)
                pattern = os.path.basename(template_path)  # 文件名模式
                candidates = glob.glob(os.path.join(vpath, pattern))
                if not candidates:
                    # 尝试模糊匹配: 包含 Event_XX
                    event_key = short_name.split('_')[1] if '_' in short_name else ''
                    cands = [f for f in os.listdir(vpath)
                             if f.endswith('.npy') and f'Event_{event_key}_' in f]
                    if cands:
                        candidates = [os.path.join(vpath, cands[0])]

                if candidates:
                    result = np.load(candidates[0], allow_pickle=True).tolist()
                    flooding = result.get('flooding', [])
                    cso = result.get('CSO', [])
                    if flooding and cso:
                        fc = flooding[-1] + cso[-1]  # 累积 F+C
                        fc_list.append(fc)

            data[short_name][llm_label] = fc_list

    return data, [sn for sn, _ in event_names]


def load_baseline_data(event_names):
    """
    加载 baseline (无扰动) 的 F+C 原始值 (m³)。
    返回 dict[event_short_name][llm_label] -> float (F+C, 原始 m³)
    """
    baseline = {}
    for short_name in event_names:
        baseline[short_name] = {}
        event_key = short_name.split('_')[1] if '_' in short_name else ''

        for llm_label, llm_dir in LLM_DIR_MAP.items():
            bpath = os.path.join(BASELINE_BASE, llm_dir)
            if not os.path.isdir(bpath):
                continue
            cands = [f for f in os.listdir(bpath)
                     if f.endswith('.npy') and f'Event_{event_key}_' in f]
            if cands:
                result = np.load(os.path.join(bpath, cands[0]), allow_pickle=True).tolist()
                flooding = result.get('flooding', [])
                cso = result.get('CSO', [])
                if flooding and cso:
                    fc = flooding[-1] + cso[-1]  # 原始 m³
                    baseline[short_name][llm_label] = fc

    return baseline


def main():
    """命令行入口: 加载同义替换与 baseline 实验数据, 绘制覆盖率分组柱状图。
    """
    print("加载同义词干扰实验数据...")
    data, event_names = load_synonym_data()
    print("加载 baseline (无扰动) 数据...")
    baseline = load_baseline_data(event_names)

    n_events = len(event_names)
    print(f"  共 {n_events} 个降雨事件")
    for en in event_names:
        llms_ok = [llm for llm in LLM_NAMES if data.get(en, {}).get(llm)]
        print(f"  {en}: {dict((llm, len(data[en][llm])) for llm in llms_ok)}")

    # ── 计算每个 (事件, LLM) 的 Coefficient of Variation (CoV) ──
    # 逐事件: CoV_event = std(F+C across variants, ddof=1) / mean(F+C across variants) × 100 (%)
    # 整体:   CoV_llm = mean(CoV_event over events)
    # 采用逐事件再平均，避免事件间 F+C 量级差异主导 CoV
    cv_per_event = {}   # {event_short: {llm: cov%}}
    cv_per_llm = {}     # {llm: mean cov%}
    for llm_label in LLM_NAMES:
        cv_events = []
        for en in event_names:
            cv_per_event.setdefault(en, {})
            fc_values = data.get(en, {}).get(llm_label, [])
            if len(fc_values) >= 2:
                mean_v = float(np.mean(fc_values))
                if mean_v > 0:
                    std_v = float(np.std(fc_values, ddof=1))
                    cv = std_v / mean_v * 100
                    cv_per_event[en][llm_label] = cv
                    cv_events.append(cv)
                    continue
            cv_per_event[en][llm_label] = float('nan')
        cv_per_llm[llm_label] = float(np.mean(cv_events)) if cv_events else float('nan')

    print("  各 LLM 平均 CoV (std/mean):")
    for llm_label in LLM_NAMES:
        cv_val = cv_per_llm[llm_label]
        print(f"    {llm_label}: {cv_val:.2f}%" if not np.isnan(cv_val)
              else f"    {llm_label}: N/A")

    # ── 单图: x=LLM, 每个 LLM 10 个柱 (每事件一个), 柱高=该(事件,LLM)的 CoV(%) ──
    n_llm = len(LLM_NAMES)
    n_evt = len(event_names)
    bar_w = 0.75
    group_gap = 1.5   # 组间额外间隔

    # 计算 bar 的 x 位置 + 每组中心
    bar_x = []           # [(xpos, llm, event_name), ...]
    group_centers = []
    x_cursor = 0.0
    for li, llm in enumerate(LLM_NAMES):
        for ei, en in enumerate(event_names):
            bar_x.append((x_cursor + ei * bar_w, llm, en))
        group_centers.append(x_cursor + (n_evt - 1) * bar_w / 2.0)
        x_cursor += (n_evt - 1) * bar_w + bar_w + group_gap   # 下一组起点

    fig, ax = plt.subplots(dpi=150, figsize=(14, 7))

    # ── 绘制柱子 (每柱=该(事件,LLM)的 CoV) ──
    for (xpos, llm, en) in bar_x:
        cv = cv_per_event.get(en, {}).get(llm, float('nan'))
        color = COLORS[llm]
        if np.isnan(cv):
            ax.bar(xpos, 0, width=bar_w * 0.9, color=color, alpha=0.2,
                   edgecolor=color, linewidth=0.8)
            ax.text(xpos, 0.2, 'N/A', ha='center', va='bottom',
                    fontsize=8, color='gray', rotation=90)
        else:
            ax.bar(xpos, cv, width=bar_w * 0.9, color=color, alpha=0.7,
                   edgecolor=color, linewidth=0.8)
            ax.text(xpos, cv, f'{cv:.2f}', ha='center', va='bottom',
                    fontsize=7, color=color)

    # ── 每个 LLM 组内: 均值水平线 + 标注 ──
    for li, llm in enumerate(LLM_NAMES):
        cv_vals = [cv_per_event.get(en, {}).get(llm, float('nan')) for en in event_names]
        valid = [v for v in cv_vals if not np.isnan(v)]
        if not valid:
            continue
        mean_v = float(np.mean(valid))
        xs = [x for (x, l, e) in bar_x if l == llm]
        xmin, xmax = min(xs) - bar_w * 0.5, max(xs) + bar_w * 0.5
        ax.hlines(mean_v, xmin, xmax, colors=COLORS[llm], linestyles='--',
                  linewidth=2.2, zorder=5)
        ax.text(xmax + 0.15, mean_v, f'mean={mean_v:.2f}%', va='center', ha='left',
                fontsize=10, color=COLORS[llm], fontweight='bold')

    # ── x 轴: 主刻度=LLM 名, 次刻度=事件编号 ──
    ax.set_xticks(group_centers)
    ax.set_xticklabels(LLM_NAMES, fontsize=12, fontweight='bold')
    ax.set_xticks([x for (x, l, e) in bar_x], minor=True)
    ax.set_xticklabels(
        [e.split('_')[1] if '_' in e else e for (x, l, e) in bar_x],
        minor=True, fontsize=8)
    ax.tick_params(axis='x', which='major', pad=22, length=8)
    ax.tick_params(axis='x', which='minor', length=3, pad=2)

    ax.set_ylabel('Coefficient of Variation, CoV (%)', fontsize=13)
    ax.set_xlabel('LLM  (minor ticks = event No.)', fontsize=13, labelpad=18)
    ax.set_title('Synonym-prompt uncertainty: per-event CoV of F+C across variants',
                 fontsize=14, fontweight='bold')
    ax.grid(axis='y', linestyle='--', alpha=0.35)
    ax.set_xlim(bar_x[0][0] - bar_w, bar_x[-1][0] + bar_w + group_gap)
    ax.set_ylim(bottom=0)

    # ── 图例: 4 LLM 颜色 + 各自 mean CoV ──
    from matplotlib.patches import Patch
    handles = [
        Patch(facecolor=COLORS[lbl], edgecolor=COLORS[lbl], alpha=0.7,
              label=f"{lbl}: mean CoV={cv_per_llm[lbl]:.2f}%"
              if not np.isnan(cv_per_llm[lbl]) else lbl)
        for lbl in LLM_NAMES
    ]
    ax.legend(handles=handles, loc='upper right', fontsize=11, frameon=True,
              fancybox=True, framealpha=0.95)

    fig.tight_layout()

    # ── 保存 ───────────────────────────────────────────────
    out_dir = os.path.join(_sys_parent, 'Results', 'LLMUsage', 'FigUncertainty')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'synonym_cov_bar.png')
    plt.savefig(out_path, dpi=200, bbox_inches='tight')
    print(f"\nCoV 柱状图已保存: {out_path}")
    plt.close()


if __name__ == '__main__':
    main()
