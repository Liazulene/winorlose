"""Deterministic per-game seed assignment.

A game seed depends only on the batch seed and the game index, so a batch is
fully reproducible and independent of the number of games requested, the
concurrency level and the execution order.
"""

from __future__ import annotations

from ..rng import seed_from_key


def game_seed_for(batch_seed: int, index: int) -> int:
    return seed_from_key("game-seed", batch_seed, index)
