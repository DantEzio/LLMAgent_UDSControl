# -*- coding: utf-8 -*-
"""
Uncertainty analysis shared configuration file.

Contains:
- LLM backend configuration (DeepSeek / GLM / Kimi / MiniMax)
- Experiment parameters (variant count, random seeds, noise scale)
- Path configuration
"""

import os

# ============================================================
# Path configuration
# ============================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STEP3_DIR = os.path.join(_THIS_DIR, 'step3-BCAgent-control')
_PARENT_DIR = os.path.dirname(_THIS_DIR)          # DRL-control/
_PROJECT_ROOT = os.path.dirname(_PARENT_DIR)       # DRL_Agent_UDSRTC/

# Root directory for results
RESULTS_ROOT = os.path.join(_THIS_DIR, 'results_uncertainty')

# Subdirectories for each experiment
BASELINE_DIR = os.path.join(RESULTS_ROOT, 'baseline')
SYNONYM_DIR = os.path.join(RESULTS_ROOT, 'synonym')
STATE_NOISE_DIR = os.path.join(RESULTS_ROOT, 'state_noise')

# ============================================================
# Map of original step3 result paths (reused as baseline source, read-only)
# ============================================================
# step3 directory names under DRL-control/ for each LLM backend
STEP3_DIR_NAMES = {
    'DeepSeek': 'step3-BCAgent-control',
    'GLM':      'step3-BCAgent-control-GLM',
    'Kimi':     'step3-BCAgent-control-Kimi',
    'MiniMax':  'step3-BCAgent-control-MiniMax',
}

# Absolute paths to each backend's original step3 results/ directory (read-only)
STEP3_RESULT_DIRS = {
    name: os.path.join(_PARENT_DIR, dir_name, 'results')
    for name, dir_name in STEP3_DIR_NAMES.items()
}

# Prefix of original step3 result files (distinct from the step4 'results_' prefix)
STEP3_RESULT_PREFIX = 'bc_agent_results_'

# ============================================================
# LLM backend configuration
# ============================================================
LLM_BACKENDS = {
    'DeepSeek': {
        'api_key': '[Your LLM API]',
        'base_url': 'https://api.deepseek.com',
        'model': 'deepseek-v4-flash',
        'use_reasoning': True,   # DeepSeek uses reasoning_effort + thinking
    },
    'GLM': {
        'api_key': '[Your LLM API]',
        'base_url': 'https://open.bigmodel.cn/api/paas/v4/',
        'model': 'glm-4-flash',
        'use_reasoning': False,
    },
    'Kimi': {
        'api_key': '[Your LLM API]',
        'base_url': 'https://api.moonshot.cn/v1',
        'model': 'moonshot-v1-8k',
        'use_reasoning': False,
    },
    'MiniMax': {
        'api_key': '[Your LLM API]',
        'base_url': 'https://api.minimaxi.com/v1',
        'model': 'MiniMax-M3',
        'use_reasoning': False,
    },
}

# ============================================================
# Experiment parameters (build phase: reduced to 2 variants/seeds)
# ============================================================

# --- Experiment 1: synonym perturbation ---
SYNONYM_NUM_VARIANTS = 11         # Number of synonym variants (variant_0 ~ variant_10)
SYNONYM_SEEDS = [42, 123, 456, 789, 1024, 2048, 3030, 4040, 5050, 6060, 7070]

# --- Experiment 2: state observation noise ---
STATE_NOISE_NUM_SEEDS = 2         # Number of random seeds
STATE_NOISE_SEEDS = [42, 123]     # List of random seeds
STATE_NOISE_SCALE = 0.05          # Noise scale (relative standard deviation 5%)

# --- Baseline ---
# baseline reuses the original step3 results (zero API calls, read-only copy)
# A manual rerun is only needed if source files in STEP3_RESULT_DIRS are missing

# ============================================================
# Run control
# ============================================================
# Whether to rerun the baseline (False = read-only copy from step3 results/, recommended)
RERUN_BASELINE = False

# Debug mode: run only the first N events (0 = all)
DEBUG_MAX_EVENTS = 0

# LLM call retry parameters
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY_SEC = 5


def get_backend_names():
    """Return the list of all LLM backend names"""
    return list(LLM_BACKENDS.keys())


def get_result_dir(experiment, backend, variant_id):
    """
    Build the result save directory path.

    Args:
        experiment: 'baseline' | 'synonym' | 'state_noise'.
        backend: LLM backend name.
        variant_id: Variant number (int) or seed value.

    Returns:
        Absolute path to the result directory.
    """
    if experiment == 'baseline':
        base = BASELINE_DIR
        # baseline uses the backend name as subfolder (4 separate folders to avoid overwriting)
        sub = backend
    elif experiment == 'synonym':
        base = SYNONYM_DIR
        sub = os.path.join(backend, f'variant_{variant_id}')
    elif experiment == 'state_noise':
        base = STATE_NOISE_DIR
        sub = os.path.join(backend, f'seed_{variant_id}')
    else:
        raise ValueError(f'Unknown experiment type: {experiment}')
    return os.path.join(base, sub)


def ensure_result_dirs():
    """Create all result directories"""
    dirs = [RESULTS_ROOT, BASELINE_DIR, SYNONYM_DIR, STATE_NOISE_DIR]
    for d in dirs:
        os.makedirs(d, exist_ok=True)


if __name__ == '__main__':
    print('=== Uncertainty Analysis Configuration ===')
    print(f'LLM Backends: {get_backend_names()}')
    print(f'Synonym variants: {SYNONYM_NUM_VARIANTS} (seeds={SYNONYM_SEEDS})')
    print(f'State noise seeds: {STATE_NOISE_NUM_SEEDS} (seeds={STATE_NOISE_SEEDS}, scale={STATE_NOISE_SCALE})')
    print(f'Results root: {RESULTS_ROOT}')
    print(f'Debug max events: {DEBUG_MAX_EVENTS}')
