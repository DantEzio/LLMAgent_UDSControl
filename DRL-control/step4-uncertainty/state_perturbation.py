# -*- coding: utf-8 -*-
"""
State observation perturbation module.

Injects Gaussian noise into the observation vectors returned by the SWMM environment,
simulating the effect of sensor measurement errors on BC rule control and LLM decisions.

Design principles:
- Noise is applied only to "read" observations (depth/flow), never to the real SWMM simulation
- Fixed random seeds ensure reproducibility
- Relative noise (scaled by the value) avoids excessive perturbation of near-zero values
"""

import numpy as np


class StatePerturbator:
    """
    State observation perturbator.

    Usage:
        perturbator = StatePerturbator(seed=42, noise_scale=0.05)
        noisy_obs = perturbator.perturb_observation(observation_list)
        noisy_state = perturbator.perturb_realtime_state(realtime_state_dict)
    """

    def __init__(self, seed=42, noise_scale=0.05):
        """
        Args:
            seed: Random seed (different seeds produce different noise sequences).
            noise_scale: Relative standard deviation of the noise (0.05 = 5%).
        """
        self.seed = seed
        self.noise_scale = noise_scale
        self.rng = np.random.RandomState(seed)
        self._call_count = 0

    def perturb_observation(self, observation):
        """
        Add Gaussian noise to an observation vector.

        Args:
            observation: List/array of observations [depth_cc, depth_jk, flow1, ...].

        Returns:
            Noisy observation list (same type as the input).
        """
        self._call_count += 1
        arr = np.array(observation, dtype=float)

        # Relative noise: noise = value * scale * N(0,1)
        # For near-zero values use an absolute noise floor: max(|value| * scale, 0.001) * N(0,1)
        noise_std = np.maximum(np.abs(arr) * self.noise_scale, 0.001)
        noise = self.rng.normal(0, 1, size=arr.shape) * noise_std
        noisy_arr = arr + noise

        # Depths and flows cannot be negative
        noisy_arr = np.maximum(noisy_arr, 0.0)

        # Preserve the input type
        if isinstance(observation, list):
            return noisy_arr.tolist()
        return noisy_arr

    def perturb_realtime_state(self, realtime_state):
        """
        Add Gaussian noise to a realtime state dict.

        Noise is applied to the numeric values in node_depths, link_flows and storage_fill_status.

        Args:
            realtime_state: dict {
                'node_depths': {name: depth, ...},
                'link_flows': {name: flow, ...},
                'storage_fill_status': {name: {'depth':..., 'max_depth':..., 'fill_ratio':...}, ...}
            }

        Returns:
            Noisy state dict (deep copy).
        """
        import copy
        noisy_state = copy.deepcopy(realtime_state)

        # Perturb node_depths
        if 'node_depths' in noisy_state and noisy_state['node_depths']:
            for node_name in noisy_state['node_depths']:
                val = noisy_state['node_depths'][node_name]
                if isinstance(val, (int, float)):
                    noisy_state['node_depths'][node_name] = self._add_noise_to_value(val)

        # Perturb link_flows
        if 'link_flows' in noisy_state and noisy_state['link_flows']:
            for link_name in noisy_state['link_flows']:
                val = noisy_state['link_flows'][link_name]
                if isinstance(val, (int, float)):
                    noisy_state['link_flows'][link_name] = self._add_noise_to_value(val)

        # Perturb storage_fill_status (depth and fill_ratio)
        if 'storage_fill_status' in noisy_state and noisy_state['storage_fill_status']:
            for sname in noisy_state['storage_fill_status']:
                sinfo = noisy_state['storage_fill_status'][sname]
                if not isinstance(sinfo, dict):
                    continue
                if 'depth' in sinfo:
                    noisy_depth = self._add_noise_to_value(sinfo['depth'])
                    noisy_depth = max(noisy_depth, 0.0)
                    sinfo['depth'] = round(noisy_depth, 3)
                    # Recompute fill_ratio
                    max_depth = sinfo.get('max_depth', 1.0)
                    if max_depth > 0:
                        sinfo['fill_ratio'] = round(noisy_depth / max_depth * 100, 1)

        return noisy_state

    def _add_noise_to_value(self, value):
        """Apply relative Gaussian noise to a single value"""
        self._call_count += 1
        noise_std = max(abs(value) * self.noise_scale, 0.001)
        noise = self.rng.normal(0, noise_std)
        return value + noise

    def get_stats(self):
        """Return perturbation statistics"""
        return {
            'seed': self.seed,
            'noise_scale': self.noise_scale,
            'total_calls': self._call_count,
        }


def make_state_noise_fn(seed=42, noise_scale=0.05):
    """
    Create a state noise function (for the state_noise_fn parameter of BC_interact).

    Returns a function that takes an observation list and returns a noisy observation list.

    Args:
        seed: Random seed.
        noise_scale: Relative standard deviation of the noise.

    Returns:
        function: (observation_list) -> noisy_observation_list
    """
    perturbator = StatePerturbator(seed=seed, noise_scale=noise_scale)

    def noise_fn(observation):
        return perturbator.perturb_observation(observation)

    # Attach the perturbator reference for external access
    noise_fn.perturbator = perturbator
    return noise_fn


def make_realtime_state_noise_fn(seed=42, noise_scale=0.05):
    """
    Create a realtime state noise function.

    Returns a function that takes a realtime_state dict and returns a noisy dict.

    Args:
        seed: Random seed.
        noise_scale: Relative standard deviation of the noise.

    Returns:
        function: (realtime_state_dict) -> noisy_dict
    """
    perturbator = StatePerturbator(seed=seed, noise_scale=noise_scale)

    def noise_fn(realtime_state):
        return perturbator.perturb_realtime_state(realtime_state)

    noise_fn.perturbator = perturbator
    return noise_fn


if __name__ == '__main__':
    # Test
    print('=== State Perturbation Test ===')

    obs = [1.5, 4.2, 0.03, 0.05, 0.01, 0.2, 0.15]
    print(f'Original observation: {obs}')

    for seed in [42, 123]:
        fn = make_state_noise_fn(seed=seed, noise_scale=0.05)
        noisy = fn(obs)
        print(f'Seed {seed}: {noisy}')
        diffs = [abs(a - b) for a, b in zip(obs, noisy)]
        print(f'  Diffs: {[f"{d:.4f}" for d in diffs]}')

    # Test realtime_state
    rt_state = {
        'node_depths': {'CC-storage': 2.5, 'JK-storage': 4.8, 'J1': 0.3},
        'link_flows': {'C1': 0.05, 'C2': 0.12},
        'storage_fill_status': {
            'CC-storage': {'depth': 2.5, 'max_depth': 5.0, 'fill_ratio': 50.0},
            'JK-storage': {'depth': 4.8, 'max_depth': 6.0, 'fill_ratio': 80.0},
        },
    }
    print(f'\nOriginal realtime_state storage: {rt_state["storage_fill_status"]}')
    rt_fn = make_realtime_state_noise_fn(seed=42, noise_scale=0.05)
    noisy_rt = rt_fn(rt_state)
    print(f'Noisy realtime_state storage: {noisy_rt["storage_fill_status"]}')
