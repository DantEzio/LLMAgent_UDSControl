# -*- coding: utf-8 -*-
"""
Uncertainty analysis - shared runtime module.

Reused by run_synonym.py / run_state_noise.py / run_uncertainty.py. Contains:
- Path setup + step3 module loading (lazy import, called explicitly by each runner)
- Common functions run_single_event() / save_results() / results_exist()
"""

import sys
import os
import time
import numpy as np

# ============================================================
# Paths (module-level constants resolved at import time)
# ============================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STEP3_DIR = os.path.join(_THIS_DIR, 'step3-BCAgent-control')
_PARENT_DIR = os.path.dirname(_THIS_DIR)           # DRL-control/
_PROJECT_ROOT = os.path.dirname(_PARENT_DIR)        # DRL_Agent_UDSRTC/

_step3_loaded = False

from config_uncertainty import (
    LLM_BACKENDS, get_backend_names, get_result_dir, ensure_result_dirs,
    SYNONYM_NUM_VARIANTS, SYNONYM_SEEDS,
    STATE_NOISE_NUM_SEEDS, STATE_NOISE_SEEDS, STATE_NOISE_SCALE,
    RERUN_BASELINE, DEBUG_MAX_EVENTS, RESULTS_ROOT,
    STEP3_RESULT_DIRS, STEP3_RESULT_PREFIX,
)
from llm_advisor_unified import create_llm_advisor
from synonym_generator import generate_synonym_variants
from state_perturbation import StatePerturbator

ensure_result_dirs()


# ============================================================
# Load step3 lazily (avoid SWMM initialization when only config is imported)
# ============================================================
def load_step3():
    """Load the step3 BCAgent module (only when a run is needed)"""
    global _step3_loaded
    if _step3_loaded:
        import main_BCAgenttest as step3_mod
        return step3_mod

    if _STEP3_DIR not in sys.path:
        sys.path.insert(0, _STEP3_DIR)
    if _PARENT_DIR not in sys.path:
        sys.path.insert(0, _PARENT_DIR)
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

    print("=" * 60)
    print("[UNC] Loading step3 BCAgent module...")
    print("=" * 60)
    import main_BCAgenttest as step3_mod
    print(f"[UNC] step3 loaded: {len(step3_mod.all_scenarios)} scenarios, env ready")
    _step3_loaded = True
    return step3_mod


# ============================================================
# Common functions
# ============================================================
def run_single_event(step3, backend_name, llm_advisor, scenario_idx,
                     experiment='baseline', variant_id=0,
                     readme_override=None, state_perturbator=None):
    """
    Run a single test for one event.

    Args:
        step3: Loaded step3 module.
        backend_name: LLM backend name.
        llm_advisor: LLMActionAdvisor instance.
        scenario_idx: Scenario index.
        experiment: Experiment type ('baseline' / 'synonym' / 'state_noise').
        variant_id: Variant number or seed value.
        readme_override: Overriding README text (used by the synonym experiment).
        state_perturbator: State perturbator (used by the state noise experiment).

    Returns:
        env.results dict.
    """
    scenario = step3.all_scenarios[scenario_idx]

    # Synonym experiment: temporarily replace readme_content
    original_readme = None
    if readme_override is not None:
        original_readme = scenario['readme_content']
        scenario['readme_content'] = readme_override

    # Call BC_interact
    results = step3.BC_interact(
        scenario_idx, step3.env, step3.raindata, step3.all_scenarios,
        enable_adjustment=True,
        topology_mapper=step3._topology_mapper,
        llm_agent=step3._llm_agent,
        llm_advisor=llm_advisor,
        llm_refresh_interval=6,
        llm_state_deviation_threshold=0.15,
        llm_rainfall_excess_ratio=1.5,
        state_perturbator=state_perturbator,
        variant_id=variant_id,
    )

    # Restore the original readme
    if original_readme is not None:
        scenario['readme_content'] = original_readme

    # Attach experiment metadata
    results['_uncertainty_meta'] = {
        'experiment': experiment,
        'backend': backend_name,
        'variant_id': variant_id,
        'scenario_name': scenario['name'],
        'scenario_idx': scenario_idx,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
    }

    return results


def save_results(results, experiment, backend, variant_id, scenario_name):
    """Save the results to the corresponding directory and return the saved path"""
    save_dir = get_result_dir(experiment, backend, variant_id)
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f'results_{scenario_name}.npy')
    np.save(save_path, results)
    return save_path


def results_exist(experiment, backend, variant_id, scenario_name):
    """Check whether the result file already exists"""
    save_dir = get_result_dir(experiment, backend, variant_id)
    save_path = os.path.join(save_dir, f'results_{scenario_name}.npy')
    return os.path.exists(save_path)
