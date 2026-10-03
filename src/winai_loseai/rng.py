"""Reproducible, per-game / per-agent random number streams.

Every random draw inside a single game is taken from a stream that is derived
deterministically from the *game seed* (plus agent identity).  This guarantees:

* two runs with the same config + same game seed produce bit-identical games,
  regardless of how many games are run in parallel or in what order;
* two different individuals (different ``agent_seed``) inside the same game use
  different streams, so the agent seed is allowed to shape rollout / tie-break
  noise (as stated by the spec);
* no global RNG state, so concurrency can never change results.
"""

from __future__ import annotations

import hashlib
import random


def seed_from_key(*parts) -> int:
    """Derive a large deterministic integer seed from an arbitrary key."""
    text = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:16], "big")


def make_game_rng(game_seed: int, role: str, agent_seed: int) -> random.Random:
    """RNG stream for one agent inside one game.

    Parameters
    ----------
    game_seed : int
        Seed of the individual game.
    role : {"black", "white"}
        Colour this agent plays in this game.
    agent_seed : int
        The agent's own seed (part of its identity in the MVP).
    """
    return random.Random(seed_from_key("agent-stream", game_seed, role, agent_seed))


def make_analysis_rng(seed: int = 12345) -> random.Random:
    """Fixed-seed RNG used only for analysis (e.g. bootstrap)."""
    return random.Random(seed_from_key("analysis", seed))
