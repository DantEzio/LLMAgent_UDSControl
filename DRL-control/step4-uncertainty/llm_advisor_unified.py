# -*- coding: utf-8 -*-
"""
Unified LLM Action Advisor.

Supports 4 LLM backends (DeepSeek / GLM / Kimi / MiniMax) and selects the correct API call
style automatically from the backend configuration.

DeepSeek uses reasoning_effort + thinking parameters; the other backends use the standard
OpenAI-compatible interface.
"""

import os
import sys
import time
import importlib.util

# ============================================================
# Import the base class and constants from step3-BCAgent-control
# ============================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STEP3_DIR = os.path.join(_THIS_DIR, 'step3-BCAgent-control')
_ADVISOR_PATH = os.path.join(_STEP3_DIR, 'llm_action_advisor.py')

# Dynamically import step3's llm_action_advisor module (avoids name conflicts)
_spec = importlib.util.spec_from_file_location(
    'llm_action_advisor_base', _ADVISOR_PATH
)
_base_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base_module)

# Export the base class and constants
BaseLLMActionAdvisor = _base_module.LLMActionAdvisor
LLMAdjustmentResult = _base_module.LLMAdjustmentResult
TimingValidationResult = _base_module.TimingValidationResult
SYSTEM_PROMPT = _base_module.SYSTEM_PROMPT
TIMING_VALIDATION_SYSTEM_PROMPT = _base_module.TIMING_VALIDATION_SYSTEM_PROMPT
PUMP_NAMES = _base_module.PUMP_NAMES


class SimpleLLMActionAdvisor(BaseLLMActionAdvisor):
    """
    LLM Advisor for standard OpenAI-compatible endpoints (GLM / Kimi / MiniMax).

    Difference from the base class: _call_llm does not use reasoning_effort / extra_body arguments.
    """

    def _call_llm(self, prompt: str):
        """Call the LLM API (standard OpenAI-compatible interface), return (response text, latency ms, token info dict)"""
        t1 = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        t2 = time.perf_counter()
        elapsed_ms = (t2 - t1)

        usage = response.usage
        token_info = {
            'prompt_tokens': usage.prompt_tokens if usage else 0,
            'completion_tokens': usage.completion_tokens if usage else 0,
            'total_tokens': usage.total_tokens if usage else 0,
        }

        return response.choices[0].message.content.strip(), elapsed_ms, token_info


def create_llm_advisor(backend_name, config=None):
    """
    Create the LLMActionAdvisor instance matching an LLM backend name.

    Args:
        backend_name: LLM backend name ('DeepSeek' / 'GLM' / 'Kimi' / 'MiniMax').
        config: Optional configuration dict that overrides the defaults.

    Returns:
        An LLMActionAdvisor or SimpleLLMActionAdvisor instance.
    """
    # Import config lazily to avoid circular imports
    if config is None:
        from config_uncertainty import LLM_BACKENDS
        config = LLM_BACKENDS[backend_name]

    use_reasoning = config.get('use_reasoning', False)

    advisor_kwargs = {
        'api_key': config['api_key'],
        'base_url': config['base_url'],
        'model': config['model'],
    }

    if use_reasoning:
        # DeepSeek: use the base class (with reasoning parameters)
        return BaseLLMActionAdvisor(**advisor_kwargs)
    else:
        # GLM / Kimi / MiniMax: use the simplified subclass
        return SimpleLLMActionAdvisor(**advisor_kwargs)


if __name__ == '__main__':
    # Test: create an advisor for each backend
    from config_uncertainty import LLM_BACKENDS, get_backend_names

    print('=== Unified LLM Advisor Test ===')
    for name in get_backend_names():
        advisor = create_llm_advisor(name)
        cfg = LLM_BACKENDS[name]
        advisor_type = type(advisor).__name__
        print(f'{name:10s} -> {advisor_type:30s} model={cfg["model"]:20s} '
              f'reasoning={cfg["use_reasoning"]}')
