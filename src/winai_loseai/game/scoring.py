"""Programmatic area scoring (Tromp-Taylor style), no dead-stone judgement.

Per spec section 3.3:

* black score   = black stones + empty regions adjacent only to black;
* white score   = white stones + empty regions adjacent only to white + komi;
* empty regions touching both colours score for nobody (neutral "dame");
* ``score_margin = black_score - white_score``; ``> 0`` -> black wins.

The default komi of ``2.5`` (white) makes draws impossible in practice, but the
data model keeps a ``draw`` case for future rule changes.
"""

from __future__ import annotations

import math

from .state import EMPTY, BLACK, WHITE, neighbors, index_to_row_col

WINNER_BLACK = "black"
WINNER_WHITE = "white"
WINNER_DRAW = "draw"


def validate_komi(komi):
    """Reject ambiguous/non-finite komi without changing a valid value."""
    if type(komi) not in (int, float) or not math.isfinite(komi):
        raise ValueError("komi must be a finite non-boolean number")
    return komi


def ruleset_name(pass_min_ply: int, komi: float = 2.5) -> str:
    """Name the complete scoring/pass variant; the historical G0 is k2.5.

    GoState only needs the pass rule to generate legal moves. Persisted
    records also distinguish komi, so k0 can never be labelled as G0.
    """
    validate_komi(komi)
    if type(pass_min_ply) is not int or pass_min_ply < 0:
        raise ValueError("pass_min_ply must be a non-negative non-boolean integer")
    suffix = f"-pass{pass_min_ply}" if pass_min_ply else ""
    if komi == 2.5:
        return f"G1{suffix}" if suffix else "G0"
    label = "0" if komi == 0 else str(float(komi)).removesuffix(".0")
    return f"G1-k{label}{suffix}"


def empty_regions(board, size: int):
    """Yield ``(region, neighbour_colours)`` for each maximal empty area."""
    visited = set()
    for start, val in enumerate(board):
        if val != EMPTY or start in visited:
            continue
        region = set()
        colours = set()
        stack = [start]
        while stack:
            i = stack.pop()
            if i in region:
                continue
            region.add(i)
            for nb in neighbors(i, size):
                v = board[nb]
                if v == EMPTY:
                    if nb not in region:
                        stack.append(nb)
                else:
                    colours.add(v)
        visited |= region
        yield region, colours


def area_scores(board, size: int, komi: float = 2.5):
    """Return ``(black_score, white_score)`` including komi."""
    validate_komi(komi)
    black_stones = sum(1 for v in board if v == BLACK)
    white_stones = sum(1 for v in board if v == WHITE)
    black_territory = 0
    white_territory = 0
    for _region, colours in empty_regions(board, size):
        if colours == {BLACK}:
            black_territory += len(_region)
        elif colours == {WHITE}:
            white_territory += len(_region)
        # else: touches both (or, on an empty board, neither) -> neutral
    black_score = float(black_stones + black_territory)
    white_score = float(white_stones + white_territory + komi)
    return black_score, white_score


def winner_from_margin(margin: float) -> str:
    if margin > 0:
        return WINNER_BLACK
    if margin < 0:
        return WINNER_WHITE
    return WINNER_DRAW


def score_position(board, size: int, komi: float = 2.5):
    """Full scoring result dict for a terminal board."""
    black_score, white_score = area_scores(board, size, komi)
    margin = black_score - white_score
    winner = winner_from_margin(margin)
    return {
        "black_score": black_score,
        "white_score": white_score,
        "score_margin": margin,
        "winner": winner,
    }
