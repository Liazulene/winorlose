"""Shared helpers for tests."""

from __future__ import annotations

import os

from winai_loseai.game.state import GoState, EMPTY, BLACK, WHITE
from winai_loseai.identity import Identity
from winai_loseai.spec import AgentSpec

SLOW = os.environ.get("WIN_OR_LOSE_RUN_SLOW", "1") != "0"


def pt(r: int, c: int, size: int = 5) -> int:
    """Row-major board action index."""
    return r * size + c


def board_of(size: int = 5, black=(), white=()):
    """Board tuple from iterables of ``(row, col)`` coordinates."""
    b = [EMPTY] * (size * size)
    for r, c in black:
        b[pt(r, c, size)] = BLACK
    for r, c in white:
        b[pt(r, c, size)] = WHITE
    return tuple(b)


def state_of(board, size=5, to_play=BLACK, **kwargs):
    return GoState.from_board(board, size=size, to_play=to_play, **kwargs)


def mcts_spec(identity, seed=1, level="shallow"):
    return AgentSpec(
        agent_id=f"T-{identity.value}-{level}-s{seed}",
        identity=identity,
        algorithm="vector_mcts",
        compute_level=level,
        seed=seed,
    )


def random_spec_(identity, seed=0):
    return AgentSpec(
        agent_id=f"TRAND-{identity.value}",
        identity=identity,
        algorithm="random",
        compute_level="none",
        seed=seed,
    )
