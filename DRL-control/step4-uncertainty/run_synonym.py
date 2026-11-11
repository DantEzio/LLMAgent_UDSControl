# -*- coding: utf-8 -*-
"""
Synonym perturbation experiment - standalone runner.

Replaces synonyms in the weather warning README to test the stability of LLM outputs when the
wording changes but the meaning is equivalent.

Experiment scale: 4 backends x 11 variants x 10 events = 440 LLM calls.

Usage:
    python run_synonym.py                                # run all 4 backends (variant_0..10)
    python run_synonym.py --backend GLM                  # run only the given backend
    python run_synonym.py --skip-existing                # skip existing results
    python run_synonym.py --start-variant 2 --skip-existing   # run variant_2 to the end
    python run_synonym.py --start-variant 2 --end-variant 6   # run only variant_2..5
"""

import time
import argparse
import sys
import numpy as np

# Import shared modules
from _run_common import (
    load_step3, run_single_event, save_results, results_exist,
    LLM_BACKENDS, get_backend_names, ensure_result_dirs,
    SYNONYM_NUM_VARIANTS, SYNONYM_SEEDS, DEBUG_MAX_EVENTS,
    create_llm_advisor, generate_synonym_variants,
)

ensure_result_dirs()


# ============================================================
# Synonym experiment
# ============================================================
def run_experiment_synonym(step3, backends, skip_existing=False,
                           start_variant=0, end_variant=None):
    """Run the synonym perturbation experiment"""
    if end_variant is None:
        end_variant = SYNONYM_NUM_VARIANTS
    # Boundary checks (project convention: no try-catch)
    if start_variant < 0 or start_variant > SYNONYM_NUM_VARIANTS:
        print(f"ERROR: --start-variant {start_variant} 超出范围 [0, {SYNONYM_NUM_VARIANTS}]")
        sys.exit(1)
    if end_variant < start_variant or end_variant > SYNONYM_NUM_VARIANTS:
        print(f"ERROR: --end-variant {end_variant} 超出范围 [{start_variant}, {SYNONYM_NUM_VARIANTS}]")
        sys.exit(1)

    n_var = end_variant - start_variant
    print("\n" + "=" * 60)
    print(f"[SYNONYM] Experiment: SYNONYM (variants {start_variant}..{end_variant-1}, {n_var} variants)")
    print("=" * 60)

    scenarios = step3.all_scenarios
    max_events = DEBUG_MAX_EVENTS if DEBUG_MAX_EVENTS > 0 else len(scenarios)

    for backend_name in backends:
        print(f"\n--- Backend: {backend_name} ---")
        llm_advisor = create_llm_advisor(backend_name)

        for v_idx in range(start_variant, end_variant):
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


# ============================================================
# Progress summary
# ============================================================
def print_run_summary():
    """Print the expected number of runs"""
    n_backends = len(get_backend_names())
    n_events = DEBUG_MAX_EVENTS if DEBUG_MAX_EVENTS > 0 else 10
    total = n_backends * SYNONYM_NUM_VARIANTS * n_events

    print("\n" + "=" * 60)
    print("SYNONYM EXPERIMENT — RUN SUMMARY")
    print("=" * 60)
    print(f"  Events:          {n_events}")
    print(f"  LLM Backends:    {n_backends} ({', '.join(get_backend_names())})")
    print(f"  Synonym variants: {SYNONYM_NUM_VARIANTS} (seeds={SYNONYM_SEEDS})")
    print(f"  TOTAL runs:      {total}")
    print("=" * 60)
    return total


# ============================================================
# Main function
# ============================================================
def main():
    """CLI entry point: run the "language synonym replacement" uncertainty experiment (re-decide after rewording the prompt).
    """
    parser = argparse.ArgumentParser(description='Synonym Uncertainty Experiment')
    parser.add_argument(
        '--backend', type=str, default=None,
        help='仅运行指定后端 (默认全部)',
    )
    parser.add_argument(
        '--skip-existing', action='store_true',
        help='跳过已存在的结果文件',
    )
    parser.add_argument(
        '--start-variant', type=int, default=0,
        help='起始变体编号 (默认0)',
    )
    parser.add_argument(
        '--end-variant', type=int, default=None,
        help='结束变体编号 (不含, 默认=SYNONYM_NUM_VARIANTS)',
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

    end_variant = args.end_variant if args.end_variant is not None else SYNONYM_NUM_VARIANTS
    print_run_summary()
    print(f"\nSelected backends: {backends}")
    print(f"Skip existing: {args.skip_existing}")
    print(f"Variant range: [{args.start_variant}, {end_variant})  ({end_variant - args.start_variant} variants)")

    # Load step3 lazily (avoid triggering SWMM initialization when idle)
    step3 = load_step3()

    t_start = time.time()
    run_experiment_synonym(step3, backends,
                           skip_existing=args.skip_existing,
                           start_variant=args.start_variant,
                           end_variant=end_variant)
    t_total = time.time() - t_start

    print(f"\n{'=' * 60}")
    print(f"[SYNONYM] ALL DONE! Total time: {t_total/60:.1f} min ({t_total:.0f}s)")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
