# -*- coding: utf-8 -*-
"""
Uncertainty analysis result statistics and visualization.

Features:
1. Load all experiment results (baseline / synonym / state_noise)
2. Compute mean, standard deviation and coefficient of variation of F+C (flooding + CSO)
3. Group comparisons by experiment type x LLM backend
4. Generate comparison figures

Usage:
    python analyze_uncertainty_results.py              # analyze everything
    python analyze_uncertainty_results.py --experiment synonym  # synonym only
"""

import os
import sys
import glob
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

# ============================================================
# Paths
# ============================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_ROOT = os.path.join(_THIS_DIR, 'results_uncertainty')

# Experiment directories
EXPERIMENT_DIRS = {
    'baseline': os.path.join(RESULTS_ROOT, 'baseline'),
    'synonym': os.path.join(RESULTS_ROOT, 'synonym'),
    'state_noise': os.path.join(RESULTS_ROOT, 'state_noise'),
}

# Colors for LLM backends (for plotting)
BACKEND_COLORS = {
    'DeepSeek': '#2196F3',
    'GLM': '#4CAF50',
    'Kimi': '#FF9800',
    'MiniMax': '#9C27B0',
}


# ============================================================
# Data loading
# ============================================================
def load_results_from_dir(dir_path):
    """
    Load all .npy result files from a directory.

    Returns:
        list of dict: [{results, meta, filepath}, ...]
    """
    results_list = []
    npy_files = glob.glob(os.path.join(dir_path, '*.npy'))

    for fpath in npy_files:
        results = np.load(fpath, allow_pickle=True).item()
        meta = results.get('_uncertainty_meta', {})
        results_list.append({
            'results': results,
            'meta': meta,
            'filepath': fpath,
        })

    return results_list


def load_all_results(experiment_name):
    """
    Load all results of one experiment type.

    Directory layout:
        synonym/DeepSeek/variant_0/results_Event01.npy
        state_noise/GLM/seed_42/results_Event01.npy
        baseline/DeepSeek/results_Event01.npy

    Returns:
        list of dict with keys: results, meta, experiment, backend, variant_id, scenario_name
    """
    all_data = []
    exp_dir = EXPERIMENT_DIRS.get(experiment_name)
    if not exp_dir or not os.path.exists(exp_dir):
        print(f"[WARN] Directory not found: {exp_dir}")
        return all_data

    if experiment_name == 'baseline':
        # baseline/Backend/results_EventXX.npy
        for backend_dir in sorted(os.listdir(exp_dir)):
            backend_path = os.path.join(exp_dir, backend_dir)
            if not os.path.isdir(backend_path):
                continue
            for fpath in sorted(glob.glob(os.path.join(backend_path, '*.npy'))):
                results = np.load(fpath, allow_pickle=True).item()
                fname = os.path.basename(fpath)
                scenario_name = fname.replace('results_', '').replace('.npy', '')
                all_data.append({
                    'results': results,
                    'experiment': 'baseline',
                    'backend': backend_dir,
                    'variant_id': 0,
                    'scenario_name': scenario_name,
                })
    else:
        # synonym/Backend/variant_X/results_EventXX.npy
        # state_noise/Backend/seed_XX/results_EventXX.npy
        for backend_dir in sorted(os.listdir(exp_dir)):
            backend_path = os.path.join(exp_dir, backend_dir)
            if not os.path.isdir(backend_path):
                continue
            for sub_dir in sorted(os.listdir(backend_path)):
                sub_path = os.path.join(backend_path, sub_dir)
                if not os.path.isdir(sub_path):
                    continue
                # Parse variant_id / seed
                if sub_dir.startswith('variant_'):
                    variant_id = int(sub_dir.split('_')[1])
                elif sub_dir.startswith('seed_'):
                    variant_id = int(sub_dir.split('_')[1])
                else:
                    variant_id = sub_dir

                for fpath in sorted(glob.glob(os.path.join(sub_path, '*.npy'))):
                    results = np.load(fpath, allow_pickle=True).item()
                    fname = os.path.basename(fpath)
                    scenario_name = fname.replace('results_', '').replace('.npy', '')
                    all_data.append({
                        'results': results,
                        'experiment': experiment_name,
                        'backend': backend_dir,
                        'variant_id': variant_id,
                        'scenario_name': scenario_name,
                    })

    return all_data


# ============================================================
# Statistics
# ============================================================
def compute_flooding_cso(results):
    """Extract total flooding and CSO from the results dict"""
    flooding = float(np.sum(results.get('flooding', [0])))
    cso = float(np.sum(results.get('CSO', [0])))
    return flooding, cso


def compute_llm_stats(results):
    """Extract LLM call statistics"""
    trace = results.get('llm_full_trace', [])
    n_calls = len([t for t in trace if t.get('trace_type', '').startswith('mode_a')])
    n_timing = len([t for t in trace if 'timing_validation' in t.get('trace_type', '')])

    # Token statistics
    total_tokens = 0
    total_time_ms = 0
    for t in trace:
        if t.get('trace_type') == 'mode_a_full_analysis':
            total_tokens += t.get('total_tokens', 0)
            total_time_ms += t.get('api_call_time_ms', 0)

    return {
        'n_llm_calls': n_calls,
        'n_timing_validations': n_timing,
        'total_tokens': total_tokens,
        'total_api_time_s': total_time_ms / 1000.0,
    }


def build_summary_table(all_data, experiment_name):
    """
    Build the summary statistics table.

    Returns:
        DataFrame
    """
    rows = []
    for item in all_data:
        results = item['results']
        flooding, cso = compute_flooding_cso(results)
        llm_stats = compute_llm_stats(results)

        # Count action adjustments
        adj_log = results.get('adjustment_log', [])
        n_llm_used = len([a for a in adj_log if a.get('used_action') == 'llm'])
        n_bc_used = len([a for a in adj_log if a.get('used_action') == 'bc'])

        rows.append({
            'experiment': item['experiment'],
            'backend': item['backend'],
            'variant_id': item['variant_id'],
            'scenario': item['scenario_name'],
            'flooding': flooding,
            'cso': cso,
            'F_plus_C': flooding + cso,
            'n_llm_calls': llm_stats['n_llm_calls'],
            'n_timing_validations': llm_stats['n_timing_validations'],
            'n_llm_used': n_llm_used,
            'n_bc_used': n_bc_used,
            'total_tokens': llm_stats['total_tokens'],
            'total_api_time_s': llm_stats['total_api_time_s'],
        })

    return pd.DataFrame(rows)


def compute_uncertainty_stats(df, experiment_name):
    """
    Compute uncertainty statistics (grouped by backend x scenario).

    Returns:
        DataFrame with columns: backend, scenario, mean_F, std_F, mean_C, std_C, cv_F, cv_C, n
    """
    if df.empty:
        return pd.DataFrame()

    group_cols = ['backend', 'scenario']
    if experiment_name == 'baseline':
        # baseline has a single run, so no variation
        stats = df.groupby(group_cols).agg(
            mean_F=('flooding', 'mean'),
            std_F=('flooding', 'std'),
            mean_C=('cso', 'mean'),
            std_C=('cso', 'std'),
            mean_FC=('F_plus_C', 'mean'),
            std_FC=('F_plus_C', 'std'),
            n=('flooding', 'count'),
        ).reset_index()
    else:
        # Multiple variants/seeds: compute the coefficient of variation
        stats = df.groupby(group_cols).agg(
            mean_F=('flooding', 'mean'),
            std_F=('flooding', 'std'),
            mean_C=('cso', 'mean'),
            std_C=('cso', 'std'),
            mean_FC=('F_plus_C', 'mean'),
            std_FC=('F_plus_C', 'std'),
            n=('flooding', 'count'),
        ).reset_index()
        # Coefficient of variation CV = std / mean
        stats['cv_F'] = stats.apply(
            lambda r: r['std_F'] / r['mean_F'] if r['mean_F'] > 0 else 0, axis=1
        )
        stats['cv_C'] = stats.apply(
            lambda r: r['std_C'] / r['mean_C'] if r['mean_C'] > 0 else 0, axis=1
        )
        stats['cv_FC'] = stats.apply(
            lambda r: r['std_FC'] / r['mean_FC'] if r['mean_FC'] > 0 else 0, axis=1
        )

    return stats


# ============================================================
# Visualization
# ============================================================
def plot_uncertainty_comparison(df, stats, experiment_name, save_dir):
    """
    Generate uncertainty comparison figures.

    Figure 1: mean +/- std of F+C per backend x event (bar chart)
    Figure 2: coefficient of variation (CV) heatmap
    Figure 3: F+C distribution box plots per backend
    """
    if df.empty:
        print(f"[WARN] No data for {experiment_name}")
        return

    backends = sorted(df['backend'].unique())
    scenarios = sorted(df['scenario'].unique())

    # --- Figure 1: grouped bar chart of mean +/- std of F+C ---
    fig, ax = plt.subplots(figsize=(max(14, len(scenarios) * 1.5), 6))
    x = np.arange(len(scenarios))
    width = 0.8 / max(len(backends), 1)

    for b_idx, backend in enumerate(backends):
        means = []
        stds = []
        for sc in scenarios:
            subset = stats[(stats['backend'] == backend) & (stats['scenario'] == sc)]
            if not subset.empty:
                means.append(subset['mean_FC'].values[0])
                stds.append(subset['std_FC'].values[0] if 'std_FC' in subset else 0)
            else:
                means.append(0)
                stds.append(0)

        color = BACKEND_COLORS.get(backend, '#666666')
        ax.bar(x + b_idx * width, means, width, yerr=stds,
               label=backend, color=color, alpha=0.8, capsize=3)

    ax.set_xlabel('Rainfall Event')
    ax.set_ylabel('Flooding + CSO')
    ax.set_title(f'{experiment_name} — F+C Mean +/- Std by Backend')
    ax.set_xticks(x + width * (len(backends) - 1) / 2)
    ax.set_xticklabels(scenarios, rotation=45, ha='right', fontsize=8)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    fpath = os.path.join(save_dir, f'{experiment_name}_fc_comparison.png')
    plt.savefig(fpath, dpi=150)
    plt.close()
    print(f"  Saved: {fpath}")

    # --- Figure 2: CV heatmap (non-baseline only) ---
    if experiment_name != 'baseline' and 'cv_FC' in stats.columns:
        fig, ax = plt.subplots(figsize=(max(10, len(scenarios) * 0.8), max(4, len(backends) * 0.8)))
        cv_pivot = stats.pivot(index='backend', columns='scenario', values='cv_FC')
        im = ax.imshow(cv_pivot.values, aspect='auto', cmap='YlOrRd', vmin=0, vmax=1)
        ax.set_xticks(range(len(cv_pivot.columns)))
        ax.set_xticklabels(cv_pivot.columns, rotation=45, ha='right', fontsize=8)
        ax.set_yticks(range(len(cv_pivot.index)))
        ax.set_yticklabels(cv_pivot.index)
        # Annotate the values
        for i in range(len(cv_pivot.index)):
            for j in range(len(cv_pivot.columns)):
                val = cv_pivot.values[i, j]
                if np.isnan(val):
                    val = 0
                ax.text(j, i, f'{val:.2f}', ha='center', va='center', fontsize=7)
        plt.colorbar(im, label='CV (F+C)')
        ax.set_title(f'{experiment_name} — Coefficient of Variation (F+C)')
        plt.tight_layout()
        fpath = os.path.join(save_dir, f'{experiment_name}_cv_heatmap.png')
        plt.savefig(fpath, dpi=150)
        plt.close()
        print(f"  Saved: {fpath}")

    # --- Figure 3: box plots of F+C distribution per backend ---
    fig, ax = plt.subplots(figsize=(10, 6))
    box_data = []
    box_labels = []
    for backend in backends:
        subset = df[df['backend'] == backend]
        box_data.append(subset['F_plus_C'].values)
        box_labels.append(backend)

    bp = ax.boxplot(box_data, labels=box_labels, patch_artist=True)
    for patch, backend in zip(bp['boxes'], backends):
        patch.set_facecolor(BACKEND_COLORS.get(backend, '#666666'))
        patch.set_alpha(0.6)

    ax.set_ylabel('Flooding + CSO')
    ax.set_title(f'{experiment_name} — F+C Distribution by Backend')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    fpath = os.path.join(save_dir, f'{experiment_name}_fc_boxplot.png')
    plt.savefig(fpath, dpi=150)
    plt.close()
    print(f"  Saved: {fpath}")


def plot_baseline_vs_perturbed(baseline_df, perturbed_df, experiment_name, save_dir):
    """
    Compare F+C between the baseline and perturbation experiments.

    Figure: baseline vs perturbed scatter plot per backend x event.
    """
    if baseline_df.empty or perturbed_df.empty:
        return

    backends = sorted(baseline_df['backend'].unique())
    scenarios = sorted(baseline_df['scenario'].unique())

    fig, axes = plt.subplots(1, len(backends), figsize=(6 * len(backends), 6),
                              squeeze=False)
    for b_idx, backend in enumerate(backends):
        ax = axes[0][b_idx]
        bl = baseline_df[baseline_df['backend'] == backend]
        pt = perturbed_df[perturbed_df['backend'] == backend]

        # Match by scenario
        bl_fc = bl.set_index('scenario')['F_plus_C'].to_dict()
        pt_fc = pt.groupby('scenario')['F_plus_C'].agg(['mean', 'std']).reset_index()

        x_vals = [bl_fc.get(s, 0) for s in pt_fc['scenario']]
        y_means = pt_fc['mean'].values
        y_stds = pt_fc['std'].values if 'std' in pt_fc.columns else np.zeros(len(pt_fc))

        color = BACKEND_COLORS.get(backend, '#666666')
        ax.errorbar(x_vals, y_means, yerr=y_stds, fmt='o', color=color,
                     capsize=3, markersize=6, alpha=0.7, label=experiment_name)

        # Diagonal reference line
        max_val = max(max(x_vals), max(y_means)) * 1.1 if len(x_vals) > 0 else 1
        ax.plot([0, max_val], [0, max_val], 'k--', alpha=0.3, label='baseline')

        ax.set_xlabel('Baseline F+C')
        ax.set_ylabel(f'{experiment_name} F+C (mean +/- std)')
        ax.set_title(backend)
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

    plt.suptitle(f'Baseline vs {experiment_name} — F+C Comparison', fontsize=14)
    plt.tight_layout()
    fpath = os.path.join(save_dir, f'baseline_vs_{experiment_name}.png')
    plt.savefig(fpath, dpi=150)
    plt.close()
    print(f"  Saved: {fpath}")


# ============================================================
# Main analysis function
# ============================================================
def analyze_experiment(experiment_name, baseline_df=None):
    """Analyze a single experiment"""
    print(f"\n{'=' * 60}")
    print(f"Analyzing: {experiment_name}")
    print(f"{'=' * 60}")

    all_data = load_all_results(experiment_name)
    if not all_data:
        print(f"  No data found for {experiment_name}")
        return None, None

    print(f"  Loaded {len(all_data)} result files")

    df = build_summary_table(all_data, experiment_name)
    stats = compute_uncertainty_stats(df, experiment_name)

    # Print the summary
    print(f"\n  Summary ({experiment_name}):")
    print(f"  Backends: {sorted(df['backend'].unique())}")
    print(f"  Scenarios: {len(df['scenario'].unique())}")
    print(f"  Total runs: {len(df)}")

    if experiment_name != 'baseline':
        print(f"\n  Uncertainty stats (by backend):")
        for backend in sorted(df['backend'].unique()):
            sub = df[df['backend'] == backend]
            print(f"    {backend:10s}: F+C mean={sub['F_plus_C'].mean():.2f}, "
                  f"std={sub['F_plus_C'].std():.2f}, "
                  f"CV={sub['F_plus_C'].std()/sub['F_plus_C'].mean():.3f}"
                  if sub['F_plus_C'].mean() > 0 else
                  f"    {backend:10s}: F+C mean=0.00")

    # Save the tables
    save_dir = RESULTS_ROOT
    csv_path = os.path.join(save_dir, f'{experiment_name}_summary.csv')
    df.to_csv(csv_path, index=False)
    print(f"\n  Saved: {csv_path}")

    stats_csv = os.path.join(save_dir, f'{experiment_name}_stats.csv')
    stats.to_csv(stats_csv, index=False)
    print(f"  Saved: {stats_csv}")

    # Generate the figures
    plot_uncertainty_comparison(df, stats, experiment_name, save_dir)

    # Compare with the baseline
    if baseline_df is not None and not baseline_df.empty:
        plot_baseline_vs_perturbed(baseline_df, df, experiment_name, save_dir)

    return df, stats


def main():
    """CLI entry point: aggregate uncertainty experiment results into statistics tables and grouped box plots.
    """
    parser = argparse.ArgumentParser(description='Uncertainty Analysis Results')
    parser.add_argument(
        '--experiment', type=str, default='all',
        choices=['all', 'baseline', 'synonym', 'state_noise'],
        help='分析哪个实验 (default: all)',
    )
    args = parser.parse_args()

    os.makedirs(RESULTS_ROOT, exist_ok=True)

    # Load the baseline first (for comparison)
    baseline_df = None
    if args.experiment in ('all', 'baseline'):
        baseline_df, _ = analyze_experiment('baseline')
    elif args.experiment in ('all', 'synonym', 'state_noise'):
        # Also load the baseline for comparison
        all_data = load_all_results('baseline')
        if all_data:
            baseline_df = build_summary_table(all_data, 'baseline')

    # Analyze the other experiments
    if args.experiment in ('all', 'synonym'):
        analyze_experiment('synonym', baseline_df=baseline_df)

    if args.experiment in ('all', 'state_noise'):
        analyze_experiment('state_noise', baseline_df=baseline_df)

    print(f"\n{'=' * 60}")
    print("Analysis complete!")
    print(f"Results saved to: {RESULTS_ROOT}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
