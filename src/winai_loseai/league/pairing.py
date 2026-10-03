"""Pairing logic: builds the deterministic list of games for a batch.

Each job is a plain dict (picklable) with everything needed to play one game:

    {"index", "game_seed", "batch_id", "black": <AgentSpec>, "white": <AgentSpec>}

Ordered pairings (i, j) and (j, i) both appear so that colour is exchanged.
"""

from __future__ import annotations

from ..identity import Identity
from ..spec import AgentSpec, random_spec, mcts_individuals
from .seeds import game_seed_for


def make_job(black: AgentSpec, white: AgentSpec, batch_seed: int,
             batch_id: str, index: int) -> dict:
    return {
        "index": int(index),
        "game_seed": game_seed_for(batch_seed, index),
        "batch_id": batch_id,
        "black": black,
        "white": white,
    }


def expand_pairs(pairs, games_per_pair: int, batch_seed: int, batch_id: str,
                 start_index: int = 0):
    """Repeat each ``(black, white)`` pair ``games_per_pair`` times."""
    jobs = []
    index = start_index
    for black, white in pairs:
        for _ in range(games_per_pair):
            jobs.append(make_job(black, white, batch_seed, batch_id, index))
            index += 1
    return jobs


def ordered_pair_jobs(specs, games_per_pair: int, batch_seed: int,
                      batch_id: str, start_index: int = 0):
    """All ordered pairs (i, j), i != j, each repeated ``games_per_pair`` times.

    Because pairs are ordered, every unordered pairing is played in both
    colours, satisfying "each pair exchanges black/white".
    """
    pairs = [(a, b) for a in specs for b in specs if a is not b]
    return expand_pairs(pairs, games_per_pair, batch_seed, batch_id, start_index)


def random_baseline_jobs(games_per_combo: int, batch_seed: int, batch_id: str,
                         start_index: int = 0):
    """Batch A: RandomAgent vs RandomAgent across all identity combinations.

    Random's moves do not depend on identity, so the four combos only change
    the utility interpretation (a built-in control for the rule engine).
    """
    combos = [
        (random_spec(Identity.WIN), random_spec(Identity.WIN)),
        (random_spec(Identity.LOSE), random_spec(Identity.LOSE)),
        (random_spec(Identity.WIN), random_spec(Identity.LOSE)),
        (random_spec(Identity.LOSE), random_spec(Identity.WIN)),
    ]
    return expand_pairs(combos, games_per_combo, batch_seed, batch_id, start_index)


# Fixed individual pools used by the formal MCTS batches.
def batch_B_specs():
    return (mcts_individuals(Identity.WIN, "shallow")
            + mcts_individuals(Identity.LOSE, "shallow"))


def batch_C_specs():
    return (mcts_individuals(Identity.WIN, "shallow")
            + mcts_individuals(Identity.WIN, "medium")
            + mcts_individuals(Identity.LOSE, "shallow")
            + mcts_individuals(Identity.LOSE, "medium"))


def batch_jobs_for(kind: str, requested_games: int, batch_seed: int,
                   batch_id: str):
    """Deterministic job plan for a formal batch (A / B / C).

    ``requested_games`` is a *target*; the actual planned count is the largest
    multiple the pairing structure allows (per-combo / per-ordered-pair cells
    are always filled completely).
    """
    kind = kind.upper()
    if kind == "A":
        per = max(1, requested_games // 4)
        return random_baseline_jobs(per, batch_seed, batch_id)
    specs = batch_B_specs() if kind == "B" else batch_C_specs()
    n_pairs = len(specs) * (len(specs) - 1)
    per_pair = max(1, requested_games // n_pairs)
    return ordered_pair_jobs(specs, per_pair, batch_seed, batch_id)
