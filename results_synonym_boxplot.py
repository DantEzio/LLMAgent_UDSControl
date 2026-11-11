# -*- coding: utf-8 -*-
"""
Uncertainty analysis - box plots for the synonym perturbation experiment.

Shows the Flooding+CSO distribution of 4 LLM backends under synonym prompt perturbation for
different rainfall events. Each subplot corresponds to one rainfall event and contains box
plots for the 4 LLMs (aggregated across variants).

Usage:
    python results_synonym_boxplot.py
"""

import sys
import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import rcParams
import glob

# -- Path settings --------------------------------------------
_sys_parent = os.path.dirname(os.path.abspath(__file__))
_drl_control_dir = os.path.join(_sys_parent, 'DRL-control')

# -- CJK font & styling ----------------------------------------
config = {
    "font.size": 14,
    "mathtext.fontset": 'stix',
    "font.family": 'sans-serif',
    "font.sans-serif": ['Arial', 'DejaVu Sans'],
    'axes.unicode_minus': False,
}
rcParams.update(config)

# -- LLM configuration (same as results_varLLM.py) ----------------
LLM_NAMES = ['DeepSeek-v4-flash', 'GLM-4-flash', 'Moonshot-v1-8k', 'Minimax-M3']
LLM_DIR_MAP = {
    'DeepSeek-v4-flash': 'DeepSeek',
    'GLM-4-flash':       'GLM',
    'Moonshot-v1-8k':    'Kimi',
    'Minimax-M3':        'MiniMax',
}

COLORS = {
    'DeepSeek-v4-flash': '#2e7d32',   # Dark green
    'GLM-4-flash':       '#1f77b4',   # Blue
    'Moonshot-v1-8k':    '#9467bd',   # Purple
    'Minimax-M3':        '#ff7f0e',    # Orange
}

# -- Data paths ----------------------------------------------
SYNONYM_BASE = os.path.join(_drl_control_dir, 'step4-uncertainty',
                            'results_uncertainty', 'synonym')
BASELINE_BASE = os.path.join(_drl_control_dir, 'step4-uncertainty',
                             'results_uncertainty', 'baseline')

# -- Load data ------------------------------------------------
def load_synonym_data():
    """
    Return dict[event_short_name][llm_label] -> list[float] (F+C of each variant).
    """
    # Discover all event names (from one LLM's variant_0 directory)
    first_llm_dir = os.path.join(SYNONYM_BASE, 'DeepSeek', 'variant_0')
    event_files = sorted(glob.glob(os.path.join(first_llm_dir, '*.npy')))
    event_names = []
    for f in event_files:
        basename = os.path.basename(f)
        # results_Event_XX_<date>_<warning>.npy -> Event_XX
        name = basename.replace('results_', '').replace('.npy', '')
        # Extract the short name Event_XX
        parts = name.split('_')
        short = '_'.join(parts[:2]) if len(parts) >= 2 else name
        event_names.append((short, f))  # (short name, full file path template)

    # Organize data: {event_short: {llm: [fc_values_per_variant]}}
    data = {}
    for short_name, _ in event_names:
        data[short_name] = {}

    for llm_label, llm_dir in LLM_DIR_MAP.items():
        llm_base = os.path.join(SYNONYM_BASE, llm_dir)
        if not os.path.isdir(llm_base):
            print(f"  警告: 目录不存在 {llm_base}")
            continue

        # Discover all variants
        variant_dirs = sorted(
            [d for d in os.listdir(llm_base)
             if os.path.isdir(os.path.join(llm_base, d)) and d.startswith('variant_')]
        )

        for short_name, template_path in event_names:
            fc_list = []
            for vdir in variant_dirs:
                # Find matching files in that variant directory
                vpath = os.path.join(llm_base, vdir)
                pattern = os.path.basename(template_path)  # Filename pattern
                candidates = glob.glob(os.path.join(vpath, pattern))
                if not candidates:
                    # Try fuzzy matching: filename contains Event_XX
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
                        fc = flooding[-1] + cso[-1]  # Cumulative F+C
                        fc_list.append(fc)

            data[short_name][llm_label] = fc_list

    return data, [sn for sn, _ in event_names]


def load_baseline_data(event_names):
    """
    Load the raw F+C values (m^3) of the baseline (undisturbed) run.
    Returns dict[event_short_name][llm_label] -> float (F+C, raw m^3).
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
                    fc = flooding[-1] + cso[-1]  # Raw m^3
                    baseline[short_name][llm_label] = fc

    return baseline


def main():
    """CLI entry point: load synonym-replacement and baseline experiment data and draw the grouped CoV bar chart.
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

    # -- Compute the Coefficient of Variation (CoV) per (event, LLM) --
    # Per event: CoV_event = std(F+C across variants, ddof=1) / mean(F+C across variants) x 100 (%)
    # Overall: CoV_llm = mean(CoV_event over events)
    # Average per-event values so differences in F+C magnitude between events do not dominate CoV
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

    # -- Single figure: x=LLM, 10 bars per LLM (one per event), bar height=CoV(%) for that (event, LLM) --
    n_llm = len(LLM_NAMES)
    n_evt = len(event_names)
    bar_w = 0.75
    group_gap = 1.5   # Extra spacing between groups

    # Compute bar x positions and group centers
    bar_x = []           # [(xpos, llm, event_name), ...]
    group_centers = []
    x_cursor = 0.0
    for li, llm in enumerate(LLM_NAMES):
        for ei, en in enumerate(event_names):
            bar_x.append((x_cursor + ei * bar_w, llm, en))
        group_centers.append(x_cursor + (n_evt - 1) * bar_w / 2.0)
        x_cursor += (n_evt - 1) * bar_w + bar_w + group_gap   # Start of the next group

    fig, ax = plt.subplots(dpi=150, figsize=(14, 7))

    # -- Draw bars (one bar = CoV of that (event, LLM)) --
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

    # -- Within each LLM group: mean horizontal line + annotation --
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

    # -- x axis: major ticks = LLM names, minor ticks = event numbers --
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

    # -- Legend: colors for 4 LLMs + their mean CoV --
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

    # -- Save -----------------------------------------------------
    out_dir = os.path.join(_sys_parent, 'Results', 'LLMUsage', 'FigUncertainty')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'synonym_cov_bar.png')
    plt.savefig(out_path, dpi=200, bbox_inches='tight')
    print(f"\nCoV 柱状图已保存: {out_path}")
    plt.close()


if __name__ == '__main__':
    main()
