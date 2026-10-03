"""Fixed public identities and the reward mapping they induce.

The reward a colour gets depends only on the *game winner* (a colour) and that
colour's identity.  WIN rewards winning; LOSE rewards losing.  This makes
WIN-vs-WIN and LOSE-vs-LOSE zero-sum while WIN-vs-LOSE is *non-zero-sum*: both
players prefer the same terminal outcome.
"""

from __future__ import annotations

from enum import Enum


class Identity(str, Enum):
    WIN = "WIN"
    LOSE = "LOSE"


# Winner labels used across the code base (strings, independent of board codes).
WINNER_BLACK = "black"
WINNER_WHITE = "white"
WINNER_DRAW = "draw"


def player_utility(identity, winner: str, own_color: str) -> int:
    """Utility in {-1, 0, +1} of a single player.

    Parameters
    ----------
    identity : Identity
        The player's fixed identity.
    winner : str
        One of WINNER_BLACK / WINNER_WHITE / WINNER_DRAW.
    own_color : str
        The player's colour: "black" or "white".
    """
    if winner == WINNER_DRAW:
        return 0
    own_won = winner == own_color
    if identity == Identity.WIN:
        return 1 if own_won else -1
    return -1 if own_won else 1


def black_white_utilities(winner: str, black_identity, white_identity):
    """Return the terminal utility vector ``(u_black, u_white)``.

    Parameters
    ----------
    winner : str
        WINNER_BLACK / WINNER_WHITE / WINNER_DRAW.
    black_identity, white_identity : Identity
        Identities of the black / white players.
    """
    u_black = player_utility(black_identity, winner, "black")
    u_white = player_utility(white_identity, winner, "white")
    return u_black, u_white


def coerce_identity(value):
    """Accept an Identity or its string name and return an Identity."""
    if isinstance(value, Identity):
        return value
    return Identity(str(value).upper())


def identity_goal_reached(utility: int) -> bool:
    """Whether a player's own-identity goal was reached (utility == +1)."""
    return utility == 1
