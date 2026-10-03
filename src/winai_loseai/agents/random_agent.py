"""RandomAgent: uniform random play over all legal actions including pass.

Used as the rules stress-test and as the baseline.  Its moves do not depend on
identity or on its own seed (uniform sampling), so the distribution of board
outcomes is identical across identity conditions and only the *interpretation*
(utilities) changes.
"""

from __future__ import annotations

from ..game.state import GoState


class RandomAgent:
    algorithm = "random"

    def __init__(self, spec, rng):
        self.spec = spec
        self._rng = rng
        self.last_stats = None

    def select_action(self, state: GoState, identity_black, identity_white) -> int:
        legal = state.legal_actions()
        return legal[self._rng.randrange(len(legal))]
