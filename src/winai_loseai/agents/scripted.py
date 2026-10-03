"""D0 deterministic G0 controls, intentionally independent of identity.

Tie-breaking is part of the algorithm definition. Instances are game-local;
OneStoneThenPass remembers a placement even if the placed stone is captured.
"""
from ..game.state import BLACK, pass_action
from ..game.scoring import score_position


class AlwaysPassAgent:
    algorithm = "always_pass"

    def __init__(self, spec, rng=None, komi=2.5):
        self.spec = spec
        self.komi = komi
        self.last_stats = None

    def select_action(self, state, identity_black, identity_white):
        if state.is_terminal():
            raise ValueError("cannot select an action in a terminal state")
        return pass_action(state.size)


class OneStoneThenPassAgent(AlwaysPassAgent):
    algorithm = "one_stone_then_pass"

    def __init__(self, spec, rng=None, komi=2.5):
        super().__init__(spec, rng, komi)
        self.has_placed = False

    def select_action(self, state, identity_black, identity_white):
        passed = super().select_action(state, identity_black, identity_white)
        if not self.has_placed:
            placements = [a for a in state.legal_actions() if a != passed]
            if placements:
                self.has_placed = True
                return min(placements)
        return passed


class GreedyAreaAgent(AlwaysPassAgent):
    algorithm = "greedy_area"

    def select_action(self, state, identity_black, identity_white):
        passed = super().select_action(state, identity_black, identity_white)
        sign = 1 if state.to_play == BLACK else -1
        def rank(action):
            child = state.play(action)
            margin = score_position(child.board, child.size, self.komi)["score_margin"]
            # Larger is better: first own margin, then pass, then lowest point.
            return sign * margin, action == passed, -action
        return max(state.legal_actions(), key=rank)


SCRIPTED_AGENTS = {
    cls.algorithm: cls
    for cls in (AlwaysPassAgent, OneStoneThenPassAgent, GreedyAreaAgent)
}
