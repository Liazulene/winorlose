"""Full-game properties: invariants, determinism, utility structure (spec 9.2)."""

from __future__ import annotations

import unittest

from winai_loseai.game.state import (
    GoState, EMPTY, BLACK, WHITE, move_limit, board_has_dead_group,
)
from winai_loseai.identity import Identity
from winai_loseai.league.runner import play_one
from winai_loseai.spec import random_spec, mcts_individuals, AgentSpec

from tests._helpers import SLOW

SIZE = 5


def _job(bi, wi, gs, bseed=0, wseed=0, index=0, batch="prop"):
    return {
        "black": random_spec(bi, seed=bseed),
        "white": random_spec(wi, seed=wseed),
        "game_seed": int(gs),
        "batch_id": batch,
        "index": int(index),
    }


def _replay_with_checks(record):
    """Apply the record's moves and validate invariants at every ply."""
    state = GoState.initial(SIZE)
    for m in record["moves"]:
        state = state.play(m["action"])
        assert all(v in (EMPTY, BLACK, WHITE) for v in state.board)
        assert not board_has_dead_group(state.board, SIZE)  # no dead group
    assert state.move_count <= move_limit(SIZE)
    return state


class TestRandomGameInvariants(unittest.TestCase):
    ID_COMBOS = [
        (Identity.WIN, Identity.WIN),
        (Identity.LOSE, Identity.LOSE),
        (Identity.WIN, Identity.LOSE),
        (Identity.LOSE, Identity.WIN),
    ]

    def test_termination_and_board_invariants(self):
        for gs in range(24):
            bi, wi = self.ID_COMBOS[gs % 4]
            rec = play_one(_job(bi, wi, gs, bseed=gs % 5, wseed=gs % 7, index=gs))
            self.assertIn(rec["termination_reason"], ("double_pass", "move_limit"))
            self.assertLessEqual(rec["move_count"], move_limit(SIZE))
            _replay_with_checks(rec)

    def test_identity_does_not_change_board_outcome(self):
        # Same seeds, same game seed, only identities swapped -> same moves.
        rec_a = play_one(_job(Identity.WIN, Identity.WIN, 9, bseed=3, wseed=3))
        rec_b = play_one(_job(Identity.LOSE, Identity.LOSE, 9, bseed=3, wseed=3))
        self.assertEqual([m["action"] for m in rec_a["moves"]],
                         [m["action"] for m in rec_b["moves"]])
        self.assertEqual(rec_a["winner"], rec_b["winner"])

    def test_utility_invariants(self):
        for gs in range(16):
            bi, wi = self.ID_COMBOS[gs % 4]
            rec = play_one(_job(bi, wi, gs, index=gs))
            ub, uw = rec["black_utility"], rec["white_utility"]
            self.assertIn(ub, (-1, 0, 1))
            self.assertIn(uw, (-1, 0, 1))
            if rec["winner"] == "draw":
                self.assertEqual((ub, uw), (0, 0))
            elif bi == wi:
                self.assertEqual(ub + uw, 0)      # zero-sum within same identity
            else:
                self.assertEqual(ub, uw)          # aligned across identities

    def test_reproducible_per_move_given_seed(self):
        rec1 = play_one(_job(Identity.WIN, Identity.LOSE, 123, bseed=2, wseed=4, index=0))
        rec2 = play_one(_job(Identity.WIN, Identity.LOSE, 123, bseed=2, wseed=4, index=0))
        self.assertEqual([(m["action"], m["color"]) for m in rec1["moves"]],
                         [(m["action"], m["color"]) for m in rec2["moves"]])
        self.assertEqual(rec1["winner"], rec2["winner"])
        self.assertEqual(rec1["black_score"], rec2["black_score"])


@unittest.skipUnless(SLOW, "slow MCTS game tests disabled (WIN_OR_LOSE_RUN_SLOW=0)")
class TestMctsGameProperties(unittest.TestCase):
    def test_deterministic_and_non_zero_sum(self):
        win = mcts_individuals(Identity.WIN, "shallow", n_seeds=1)[0]
        lose = mcts_individuals(Identity.LOSE, "shallow", n_seeds=1)[0]
        gs = 55
        job = {"black": win, "white": lose, "game_seed": gs,
               "batch_id": "mcts_prop", "index": 0}
        rec1 = play_one(job)
        rec2 = play_one(job)
        seq1 = [(m["action"], m["color"]) for m in rec1["moves"]]
        seq2 = [(m["action"], m["color"]) for m in rec2["moves"]]
        self.assertEqual(seq1, seq2)
        self.assertLessEqual(rec1["move_count"], move_limit(SIZE))
        # WIN vs LOSE: same-sign utilities when a colour wins (no draw here).
        if rec1["winner"] != "draw":
            self.assertEqual(rec1["black_utility"], rec1["white_utility"])


if __name__ == "__main__":
    unittest.main()
