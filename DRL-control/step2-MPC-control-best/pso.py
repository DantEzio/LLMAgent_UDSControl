# -*- coding: utf-8 -*-
"""
PSO (Particle Swarm Optimization) for MPC control.

Fixed version:
  1. Removed erroneous 0.01 factor in position update
  2. Added bounds clamping after position update
  3. Generic fitness function interface with **kwargs
  4. Configurable inertia weight and acceleration constants
  5. No try-except (per project convention)
"""

import numpy as np


class PSO(object):
    """
    Particle Swarm Optimization.

    Usage:
        pso = PSO(
            population_size=10,
            max_steps=20,
            dim=6,               # prediction horizon length
            x_bound=[0, 1],      # action space bounds (continuous)
            calculate_fitness=my_fitness_func,
            fitness_args={'inp_path': '...', 'action_table': ...},
            w=0.8, c=1.5,
        )
        best_pos, best_fit = pso.evolve()

    The calculate_fitness function should accept:
        x: np.array of shape (population_size, dim), values in x_bound
        **fitness_args
    and return:
        np.array of shape (population_size,) with fitness values (higher = better)
    """

    def __init__(self, population_size, max_steps, dim,
                 x_bound, calculate_fitness, fitness_args=None,
                 w=0.8, c=1.5, init_seed=None):
        """Initialize a standard particle swarm optimizer (PSO).

        Args:
            population_size: Number of particles.
            max_steps: Maximum number of iterations.
            dim: Search space dimension.
            x_bound: Position bounds, as (low_array, high_array).
            calculate_fitness: Fitness callback receiving the position matrix and returning fitness values.
            fitness_args: Extra arguments passed to the callback.
            w: Inertia weight.
            c: Cognitive / social learning factor (c1 = c2 = c).
            init_seed: Random seed for reproducibility.
        """
        self.w = w                         # inertia weight
        self.c1 = c                        # cognitive acceleration
        self.c2 = c                        # social acceleration
        self.population_size = population_size
        self.max_steps = max_steps
        self.dim = dim
        self.x_bound = x_bound
        self.calculate_fitness = calculate_fitness
        self.fitness_args = fitness_args if fitness_args is not None else {}

        # Initialize particle positions and velocities
        self.x = np.random.uniform(
            self.x_bound[0], self.x_bound[1],
            (self.population_size, self.dim)
        )
        self.v = np.zeros((self.population_size, self.dim))

        # Warm start: inject seed position(s) into the first particle(s)
        if init_seed is not None:
            init_seed = np.asarray(init_seed, dtype=float)
            if init_seed.ndim == 1:
                init_seed = init_seed.reshape(1, -1)
            k = min(init_seed.shape[0], self.population_size)
            d = min(init_seed.shape[1], self.dim)
            self.x[:k, :d] = init_seed[:k, :d]
            self.x = np.clip(self.x, self.x_bound[0], self.x_bound[1])

        # Evaluate initial fitness
        fitness = self.calculate_fitness(self.x, **self.fitness_args)

        # Personal best
        self.p = self.x.copy()
        self.individual_best_fitness = fitness.copy()

        # Global best
        best_idx = int(np.argmax(fitness))
        self.pg = self.x[best_idx].copy()
        self.global_best_fitness = fitness[best_idx]

        # Convergence curve
        self.best_fit_curve = []

    def evolve(self):
        """Run PSO evolution. Returns (best_position, best_fitness)."""
        self.best_fit_curve = []

        for step in range(self.max_steps):
            r1 = np.random.rand(self.population_size, self.dim)
            r2 = np.random.rand(self.population_size, self.dim)

            # Update velocity
            self.v = (self.w * self.v
                      + self.c1 * r1 * (self.p - self.x)
                      + self.c2 * r2 * (self.pg - self.x))

            # Update position (no erroneous 0.01 factor)
            self.x = self.x + self.v

            # Clamp to bounds
            self.x = np.clip(self.x, self.x_bound[0], self.x_bound[1])

            # Evaluate fitness
            fitness = self.calculate_fitness(self.x, **self.fitness_args)

            # Update personal best
            update_id = np.greater(fitness, self.individual_best_fitness)
            self.p[update_id] = self.x[update_id]
            self.individual_best_fitness[update_id] = fitness[update_id]

            # Update global best
            max_fit = np.max(fitness)
            if max_fit > self.global_best_fitness:
                best_idx = int(np.argmax(fitness))
                self.pg = self.x[best_idx].copy()
                self.global_best_fitness = max_fit

            self.best_fit_curve.append(self.global_best_fitness)

            # Early termination: convergence check
            if step > 20:
                recent = np.sum(self.best_fit_curve[-10:])
                previous = np.sum(self.best_fit_curve[-20:-10])
                if abs(recent - previous) < 1e-6:
                    break

        return self.pg, self.global_best_fitness
