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

from .state import EMPTY, BLACK, WHITE, neighbors, index_to_row_col

WINNER_BLACK = "black"
WINNER_WHITE = "white"
WINNER_DRAW = "draw"


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
