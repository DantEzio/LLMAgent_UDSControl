# -*- coding: utf-8 -*-
"""
State observation noise experiment - standalone runner.

Adds relative Gaussian noise (5%) to SWMM node depths / flows to test the robustness of LLM
control under inaccurate observations.

Experiment scale: 4 backends x 2 seeds x 10 events = 80 LLM calls.

Usage:
    python run_state_noise.py                        # run all 4 backends
    python run_state_noise.py --backend GLM          # run only the given backend
    python run_state_noise.py --skip-existing        # skip existing results
"""

import time
import argparse
import sys
import numpy as np

# Import shared modules
from _run_common import (
    load_step3, run_single_event, save_results, results_exist,
    LLM_BACKENDS, get_backend_names, ensure_result_dirs,
    STATE_NOISE_NUM_SEEDS, STATE_NOISE_SEEDS, STATE_NOISE_SCALE, DEBUG_MAX_EVENTS,
    create_llm_advisor, StatePerturbator,
)

ensure_result_dirs()


# ============================================================
# State noise experiment
# ============================================================
def run_experiment_state_noise(step3, backends, skip_existing=False):
    """Run the state observation noise experiment"""
    print("\n" + "=" * 60)
    print(f"[STATE_NOISE] Experiment: STATE_NOISE ({STATE_NOISE_NUM_SEEDS} seeds, scale={STATE_NOISE_SCALE})")
    print("=" * 60)

    scenarios = step3.all_scenarios
    max_events = DEBUG_MAX_EVENTS if DEBUG_MAX_EVENTS > 0 else len(scenarios)

    for backend_name in backends:
        print(f"\n--- Backend: {backend_name} ---")
        llm_advisor = create_llm_advisor(backend_name)

        for s_idx in range(STATE_NOISE_NUM_SEEDS):
            seed = STATE_NOISE_SEEDS[s_idx]
            print(f"\n  Seed {s_idx} (seed={seed}, scale={STATE_NOISE_SCALE})")

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
# Progress summary
# ============================================================
def print_run_summary():
    """Print the expected number of runs"""
    n_backends = len(get_backend_names())
    n_events = DEBUG_MAX_EVENTS if DEBUG_MAX_EVENTS > 0 else 10
    total = n_backends * STATE_NOISE_NUM_SEEDS * n_events

    print("\n" + "=" * 60)
    print("STATE NOISE EXPERIMENT — RUN SUMMARY")
    print("=" * 60)
    print(f"  Events:            {n_events}")
    print(f"  LLM Backends:      {n_backends} ({', '.join(get_backend_names())})")
    print(f"  Noise seeds:       {STATE_NOISE_NUM_SEEDS} (seeds={STATE_NOISE_SEEDS}, scale={STATE_NOISE_SCALE})")
    print(f"  TOTAL runs:        {total}")
    print("=" * 60)
    return total


# ============================================================
# Main function
# ============================================================
def main():
    """CLI entry point: run the "state observation perturbation" uncertainty experiment (re-decide after adding noise to observations).
    """
    parser = argparse.ArgumentParser(description='State Noise Uncertainty Experiment')
    parser.add_argument(
        '--backend', type=str, default=None,
        help='仅运行指定后端 (默认全部)',
    )
    parser.add_argument(
        '--skip-existing', action='store_true',
        help='跳过已存在的结果文件',
    )
    args = parser.parse_args()

    # Backend selection
    if args.backend:
        if args.backend not in LLM_BACKENDS:
            print(f"ERROR: Unknown backend '{args.backend}'. Available: {get_backend_names()}")
            sys.exit(1)
        backends = [args.backend]
    else:
        backends = get_backend_names()

    print_run_summary()
    print(f"\nSelected backends: {backends}")
    print(f"Skip existing: {args.skip_existing}")

    # Load step3 lazily (avoid triggering SWMM initialization when idle)
    step3 = load_step3()

    t_start = time.time()
    run_experiment_state_noise(step3, backends, skip_existing=args.skip_existing)
    t_total = time.time() - t_start

    print(f"\n{'=' * 60}")
    print(f"[STATE_NOISE] ALL DONE! Total time: {t_total/60:.1f} min ({t_total:.0f}s)")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
