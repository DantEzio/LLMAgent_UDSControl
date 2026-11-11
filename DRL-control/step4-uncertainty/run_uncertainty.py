# -*- coding: utf-8 -*-
"""
Uncertainty analysis main runner (unified entry point).

Runs 3 experiment types:
1. baseline    - undisturbed reference (4 LLM backends x 10 events = 40 runs)
2. synonym     - synonym perturbation (4 backends x 2 variants x 10 events = 80 runs)
3. state_noise - state observation noise (4 backends x 2 seeds x 10 events = 80 runs)

Total: 200 runs (reduced configuration for the build phase).

Usage:
    python run_uncertainty.py                     # run all experiments
    python run_uncertainty.py --experiment baseline  # baseline only
    python run_uncertainty.py --experiment synonym
    python run_uncertainty.py --experiment state_noise
    python run_uncertainty.py --backend GLM       # run only the given backend
    python run_uncertainty.py --skip-existing     # skip existing results

Run a single experiment standalone:
    python run_synonym.py                         # synonym experiment only
    python run_state_noise.py                     # state noise experiment only
"""

import sys
import os
import time
import argparse
import numpy as np

# ============================================================
# Import shared modules (path setup, step3 loading, run_single_event, etc.)
# ============================================================
from _run_common import (
    load_step3, run_single_event, save_results, results_exist,
    LLM_BACKENDS, get_backend_names, get_result_dir, ensure_result_dirs,
    SYNONYM_NUM_VARIANTS, SYNONYM_SEEDS,
    STATE_NOISE_NUM_SEEDS, STATE_NOISE_SEEDS, STATE_NOISE_SCALE,
    RERUN_BASELINE, DEBUG_MAX_EVENTS, RESULTS_ROOT,
    STEP3_RESULT_DIRS, STEP3_RESULT_PREFIX,
    create_llm_advisor, generate_synonym_variants, StatePerturbator,
)

ensure_result_dirs()


# ============================================================
# Experiment runners
# ============================================================
def run_experiment_baseline(step3, backends, skip_existing=False):
    """
    Baseline experiment: reuse the original step3 results directly (zero LLM API calls).

    Implementation: read .npy files from DRL-control/step3-BCAgent-control-*/results/, attach
    _uncertainty_meta metadata, then write them into step4's results_uncertainty/baseline/{backend}/.

    Safety guarantees:
    - step3 source files are only read with np.load(); no write operation is performed on them
    - The destination get_result_dir('baseline', backend, 0) lives under step4 and is physically
      isolated from the step3 source directory, so original results are never affected

    If RERUN_BASELINE=True, fall back to rerunning through the LLM API (to backfill missing files).
    """
    print("\n" + "=" * 60)
    print("[UNC] Experiment: BASELINE")
    print("=" * 60)

    scenarios = step3.all_scenarios
    max_events = DEBUG_MAX_EVENTS if DEBUG_MAX_EVENTS > 0 else len(scenarios)

    # ---- Mode A: read-only copy from original step3 results (recommended, RERUN_BASELINE=False) ----
    if not RERUN_BASELINE:
        print("[UNC] Mode: COPY from step3 original results (zero API calls)")
        print(f"[UNC] Source prefix: '{STEP3_RESULT_PREFIX}*.npy'")
        print(f"[UNC] Dest dir:     results_uncertainty/baseline/<backend>/")
        print("-" * 60)

        for backend_name in backends:
            src_results_dir = STEP3_RESULT_DIRS[backend_name]
            print(f"\n--- Backend: {backend_name} ---")
            print(f"  Source (READ-ONLY): {src_results_dir}")

            if not os.path.isdir(src_results_dir):
                print(f"  WARNING: source directory does not exist, skipping.")
                continue

            for i in range(max_events):
                scenario = scenarios[i]
                scenario_name = scenario['name']

                # step4 destination path (writes here, fully isolated from the step3 source)
                dst_dir = get_result_dir('baseline', backend_name, 0)
                dst_path = os.path.join(dst_dir, f'results_{scenario_name}.npy')

                if skip_existing and os.path.exists(dst_path):
                    print(f"  [{i+1}/{max_events}] {scenario_name} — SKIP (exists)")
                    continue

                # step3 source path (read-only)
                src_path = os.path.join(
                    src_results_dir, f'{STEP3_RESULT_PREFIX}{scenario_name}.npy'
                )

                if not os.path.exists(src_path):
                    print(f"  [{i+1}/{max_events}] {scenario_name} — MISSING in step3!")
                    continue

                # Read-only load -> .item() gives an independent in-memory copy -> modify it -> write to step4
                # np.load does not modify files on disk; the dict from .item() is detached from the source
                t0 = time.time()
                data = np.load(src_path, allow_pickle=True).item()
                data['_uncertainty_meta'] = {
                    'experiment': 'baseline',
                    'backend': backend_name,
                    'variant_id': 0,
                    'scenario_name': scenario_name,
                    'scenario_idx': i,
                    'source': 'step3_original',
                    'source_path': src_path,
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                }

                os.makedirs(dst_dir, exist_ok=True)
                np.save(dst_path, data)

                elapsed = time.time() - t0
                total_f = float(np.sum(data.get('flooding', [0])))
                total_c = float(np.sum(data.get('CSO', [0])))
                print(f"  [{i+1}/{max_events}] {scenario_name} — F={total_f:.1f}, C={total_c:.1f}, {elapsed:.2f}s -> {dst_path}")
        return

    # ---- Mode B: rerun via LLM API (fallback, RERUN_BASELINE=True) ----
    print("[UNC] Mode: RE-RUN baseline via LLM API (RERUN_BASELINE=True)")
    print("-" * 60)

    for backend_name in backends:
        print(f"\n--- Backend: {backend_name} ---")
        llm_advisor = create_llm_advisor(backend_name)

        for i in range(max_events):
            scenario = scenarios[i]
            if skip_existing and results_exist('baseline', backend_name, 0, scenario['name']):
                print(f"  [{i+1}/{max_events}] {scenario['name']} — SKIP (exists)")
                continue

            print(f"  [{i+1}/{max_events}] {scenario['name']}")
            t0 = time.time()
            results = run_single_event(
                step3, backend_name, llm_advisor, i,
                experiment='baseline', variant_id=0,
            )
            save_path = save_results(results, 'baseline', backend_name, 0, scenario['name'])
            elapsed = time.time() - t0
            total_f = float(np.sum(results.get('flooding', [0])))
            total_c = float(np.sum(results.get('CSO', [0])))
            print(f"    F={total_f:.1f}, C={total_c:.1f}, time={elapsed:.0f}s -> {save_path}")


def run_experiment_synonym(step3, backends, skip_existing=False):
    """Run the synonym perturbation experiment"""
    print("\n" + "=" * 60)
    print(f"[UNC] Experiment: SYNONYM ({SYNONYM_NUM_VARIANTS} variants)")
    print("=" * 60)

    scenarios = step3.all_scenarios
    max_events = DEBUG_MAX_EVENTS if DEBUG_MAX_EVENTS > 0 else len(scenarios)

    for backend_name in backends:
        print(f"\n--- Backend: {backend_name} ---")
        llm_advisor = create_llm_advisor(backend_name)

        for v_idx in range(SYNONYM_NUM_VARIANTS):
            seed = SYNONYM_SEEDS[v_idx]
            print(f"\n  Variant {v_idx} (seed={seed})")

            for i in range(max_events):
                scenario = scenarios[i]
                if skip_existing and results_exist('synonym', backend_name, v_idx, scenario['name']):
                    print(f"    [{i+1}/{max_events}] {scenario['name']} — SKIP (exists)")
                    continue

                # Generate synonym variants
                original_readme = scenario['readme_content']
                variants = generate_synonym_variants(
                    original_readme, num_variants=v_idx + 1, seed=seed
                )
                variant_text = variants[v_idx]

                print(f"    [{i+1}/{max_events}] {scenario['name']}")
                t0 = time.time()
                results = run_single_event(
                    step3, backend_name, llm_advisor, i,
                    experiment='synonym', variant_id=v_idx,
                    readme_override=variant_text,
                )
                save_path = save_results(
                    results, 'synonym', backend_name, v_idx, scenario['name']
                )
                elapsed = time.time() - t0
                total_f = float(np.sum(results.get('flooding', [0])))
                total_c = float(np.sum(results.get('CSO', [0])))
                print(f"      F={total_f:.1f}, C={total_c:.1f}, time={elapsed:.0f}s -> {save_path}")


def run_experiment_state_noise(step3, backends, skip_existing=False):
    """Run the state observation noise experiment"""
    print("\n" + "=" * 60)
    print(f"[UNC] Experiment: STATE_NOISE ({STATE_NOISE_NUM_SEEDS} seeds, scale={STATE_NOISE_SCALE})")
    print("=" * 60)

    scenarios = step3.all_scenarios
    max_events = DEBUG_MAX_EVENTS if DEBUG_MAX_EVENTS > 0 else len(scenarios)

    for backend_name in backends:
        print(f"\n--- Backend: {backend_name} ---")
        llm_advisor = create_llm_advisor(backend_name)

        for s_idx in range(STATE_NOISE_NUM_SEEDS):
            seed = STATE_NOISE_SEEDS[s_idx]
            print(f"\n  Seed {s_idx} (seed={seed}, scale={STATE_NOISE_SCALE})")

            # Create an independent perturbator per event (same initial state for every event)
            for i in range(max_events):
                scenario = scenarios[i]
                if skip_existing and results_exist('state_noise', backend_name, seed, scenario['name']):
                    print(f"    [{i+1}/{max_events}] {scenario['name']} — SKIP (exists)")
                    continue

                # Create a new StatePerturbator per event (ensures identical noise sequences)
                perturbator = StatePerturbator(seed=seed, noise_scale=STATE_NOISE_SCALE)

                print(f"    [{i+1}/{max_events}] {scenario['name']}")
                t0 = time.time()
                results = run_single_event(
                    step3, backend_name, llm_advisor, i,
                    experiment='state_noise', variant_id=seed,
                    state_perturbator=perturbator,
                )
                save_path = save_results(
                    results, 'state_noise', backend_name, seed, scenario['name']
                )
                elapsed = time.time() - t0
                total_f = float(np.sum(results.get('flooding', [0])))
                total_c = float(np.sum(results.get('CSO', [0])))
                print(f"      F={total_f:.1f}, C={total_c:.1f}, time={elapsed:.0f}s -> {save_path}")


# ============================================================
# Progress statistics
# ============================================================
def print_run_summary(step3):
    """Print the expected run count statistics"""
    n_events = DEBUG_MAX_EVENTS if DEBUG_MAX_EVENTS > 0 else len(step3.all_scenarios)
    n_backends = len(get_backend_names())

    baseline_runs = n_backends * n_events
    synonym_runs = n_backends * SYNONYM_NUM_VARIANTS * n_events
    state_noise_runs = n_backends * STATE_NOISE_NUM_SEEDS * n_events
    total = baseline_runs + synonym_runs + state_noise_runs

    print("\n" + "=" * 60)
    print("UNCERTAINTY ANALYSIS — RUN SUMMARY")
    print("=" * 60)
    print(f"  Events:         {n_events}")
    print(f"  LLM Backends:   {n_backends} ({', '.join(get_backend_names())})")
    print(f"  Synonym variants: {SYNONYM_NUM_VARIANTS} (seeds={SYNONYM_SEEDS})")
    print(f"  State noise seeds: {STATE_NOISE_NUM_SEEDS} (seeds={STATE_NOISE_SEEDS}, scale={STATE_NOISE_SCALE})")
    print(f"  ---")
    print(f"  Baseline runs:    {baseline_runs}")
    print(f"  Synonym runs:     {synonym_runs}")
    print(f"  State noise runs: {state_noise_runs}")
    print(f"  TOTAL:            {total}")
    print(f"  Results root:     {RESULTS_ROOT}")
    print("=" * 60)

    return total


# ============================================================
# Main function
# ============================================================
def main():
    """CLI entry point: dispatch multiple uncertainty experiments and save to results_uncertainty/.
    """
    parser = argparse.ArgumentParser(description='Uncertainty Analysis Runner')
    parser.add_argument(
        '--experiment', type=str, default='all',
        choices=['all', 'baseline', 'synonym', 'state_noise'],
        help='实验类型 (default: all)',
    )
    parser.add_argument(
        '--backend', type=str, default=None,
        help='仅运行指定后端 (默认全部)',
    )
    parser.add_argument(
        '--skip-existing', action='store_true',
        help='跳过已存在的结果文件',
    )
    args = parser.parse_args()

    # Determine which backends to run
    if args.backend:
        if args.backend not in LLM_BACKENDS:
            print(f"ERROR: Unknown backend '{args.backend}'. Available: {get_backend_names()}")
            sys.exit(1)
        backends = [args.backend]
    else:
        backends = get_backend_names()

    # Print the run summary
    step3 = load_step3()
    total = print_run_summary(step3)
    print(f"\nSelected backends: {backends}")
    print(f"Selected experiments: {args.experiment}")
    print(f"Skip existing: {args.skip_existing}")

    t_start = time.time()

    # Run the experiments
    if args.experiment in ('all', 'baseline'):
        run_experiment_baseline(step3, backends, skip_existing=args.skip_existing)

    if args.experiment in ('all', 'synonym'):
        run_experiment_synonym(step3, backends, skip_existing=args.skip_existing)

    if args.experiment in ('all', 'state_noise'):
        run_experiment_state_noise(step3, backends, skip_existing=args.skip_existing)

    t_total = time.time() - t_start
    print(f"\n{'=' * 60}")
    print(f"[UNC] ALL DONE! Total time: {t_total/60:.1f} min ({t_total:.0f}s)")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
