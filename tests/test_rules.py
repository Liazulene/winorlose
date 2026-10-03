"""Rule-engine unit tests (spec section 9.1)."""

from __future__ import annotations

import unittest

from winai_loseai.game.state import (
    GoState, EMPTY, BLACK, WHITE, pass_action, other, board_has_dead_group,
    move_limit, board_after_play,
)
from winai_loseai.game.scoring import area_scores, score_position, empty_regions

from tests._helpers import pt, board_of, state_of

SIZE = 5
PASS = pass_action(SIZE)


class TestGroupCapture(unittest.TestCase):
    """Single- and multi-stone capture; liberties after capture."""

    def test_multi_stone_capture(self):
        # White pair at (2,2),(2,3) with single liberty (2,1); black captures.
        b = board_of(
            black=[(1, 2), (3, 2), (1, 3), (3, 3), (2, 4)],
            white=[(2, 2), (2, 3)],
        )
        s = state_of(b, to_play=BLACK)
        action = pt(2, 1)
        self.assertIn(action, s.legal_actions())
        nxt = s.play(action)
        self.assertEqual(nxt.board[pt(2, 2)], EMPTY)
        self.assertEqual(nxt.board[pt(2, 3)], EMPTY)
        self.assertEqual(nxt.board[pt(2, 1)], BLACK)
        # played stone group must be alive after the capture
        self.assertFalse(board_has_dead_group(nxt.board, SIZE))

    def test_single_stone_capture_creates_liberty(self):
        # White single stone at (2,2) in atari; black captures at (2,1).
        b = board_of(
            black=[(1, 2), (3, 2), (2, 3)],
            white=[(2, 2)],
        )
        s = state_of(b, to_play=BLACK)
        action = pt(2, 1)
        self.assertIn(action, s.legal_actions())
        nxt = s.play(action)
        self.assertEqual(nxt.board[pt(2, 2)], EMPTY)
        self.assertEqual(nxt.board[pt(2, 1)], BLACK)

    def test_group_liberties_removed_only_when_no_liberties(self):
        # A white group with 2 liberties must NOT be captured by filling one.
        b = board_of(
            black=[(1, 2), (2, 3)],
            white=[(2, 2)],
        )
        s = state_of(b, to_play=BLACK)
        action = pt(2, 1)  # (2,2) still has (3,2)? empty -> two liberties remain
        nxt = s.play(action)
        self.assertEqual(nxt.board[pt(2, 2)], WHITE)  # not captured


class TestSuicide(unittest.TestCase):
    def test_suicide_rejected(self):
        # White occupies all four neighbours of (2,2); black cannot self-fill.
        b = board_of(white=[(1, 2), (3, 2), (2, 1), (2, 3)])
        s = state_of(b, to_play=BLACK)
        action = pt(2, 2)
        self.assertNotIn(action, s.legal_actions())
        self.assertIsNone(s.try_play(action))

    def test_capture_not_suicide(self):
        # Black plays into its only liberty, capturing -> gains liberties.
        b = board_of(
            black=[(1, 3), (3, 3), (2, 4)],
            white=[(2, 3)],
        )
        s = state_of(b, to_play=BLACK)
        action = pt(2, 2)  # last liberty of the white stone
        self.assertIn(action, s.legal_actions())
        nxt = s.play(action)
        self.assertFalse(board_has_dead_group(nxt.board, SIZE))
        self.assertEqual(nxt.board[pt(2, 3)], EMPTY)


class TestSuperko(unittest.TestCase):
    """Situational superko: non-pass moves may not recreate (board,next)."""

    def _make_ko(self):
        # X=(2,2) white in atari; black captures at (2,1); white's recapture
        # at (2,2) would restore the initial (board, BLACK) position.
        b = board_of(
            black=[(1, 2), (3, 2), (2, 3)],
            white=[(2, 2), (1, 1), (3, 1), (2, 0)],
        )
        s = state_of(b, to_play=BLACK)
        return s, pt(2, 1), pt(2, 2)

    def test_direct_ko_recapture_rejected(self):
        s, capture, recapture = self._make_ko()
        self.assertIn(capture, s.legal_actions())
        after_capture = s.play(capture)
        # The recapture is board-legal (it would capture and restore the board)
        # but must be forbidden because it recreates the initial position.
        restored = board_after_play(after_capture.board, SIZE, recapture, after_capture.to_play)
        self.assertEqual(restored, s.board)
        self.assertNotIn(recapture, after_capture.legal_actions())
        self.assertIsNone(after_capture.try_play(recapture))

    def test_pass_exempt_from_superko(self):
        s, capture, recapture = self._make_ko()
        after_capture = s.play(capture)
        # pass is always legal even though it leaves the same board
        self.assertIn(PASS, after_capture.legal_actions())
        after_pass = after_capture.play(PASS)
        self.assertFalse(after_pass.is_terminal())  # single pass only
        self.assertEqual(after_pass.to_play, BLACK)

    def test_non_ko_capture_does_not_false_trigger(self):
        # Different position -> recapture elsewhere is legal.
        b = board_of(black=[(1, 2)], white=[(2, 2)])
        s = state_of(b, to_play=BLACK)
        action = pt(3, 2)
        nxt = s.play(action)  # captures nothing, ordinary move
        self.assertIsNotNone(nxt)


class TestPassAndTermination(unittest.TestCase):
    def test_pass_legal_and_double_pass_terminates(self):
        s = GoState.initial(SIZE)
        self.assertFalse(s.is_terminal())
        s1 = s.play(PASS)
        self.assertFalse(s1.is_terminal())   # one pass only
        s2 = s1.play(PASS)
        self.assertTrue(s2.is_terminal())
        self.assertEqual(s2.terminal_reason(), "double_pass")
        self.assertEqual(s2.move_count, 2)

    def test_100_move_safety_limit(self):
        # White-box: force the counter near the cap, one more action trips it.
        empty = board_of()
        s = state_of(empty, to_play=BLACK, move_count=move_limit(SIZE) - 1)
        self.assertFalse(s.is_terminal())
        nxt = s.play(pt(0, 0))
        self.assertTrue(nxt.is_terminal())
        self.assertEqual(nxt.terminal_reason(), "move_limit")
        self.assertEqual(nxt.move_count, move_limit(SIZE))

    def test_all_games_end_by_double_pass_or_limit(self):
        reasons = {"double_pass", "move_limit"}
        # rule-level helper: a terminal state must report one of the two
        s = GoState.initial(SIZE)
        s1 = s.play(PASS)
        s2 = s1.play(PASS)
        self.assertIn(s2.terminal_reason(), reasons)


class TestNoMovesAfterTerminal(unittest.TestCase):
    """Once the game is over no further action may be taken (issue #5)."""

    def _assert_blocked(self, terminal_state):
        from winai_loseai.game.state import IllegalMove
        self.assertTrue(terminal_state.is_terminal())
        self.assertEqual(terminal_state.legal_actions(), ())
        legal, _counts = terminal_state.legal_report()
        self.assertEqual(legal, ())
        # every action id (board points + pass) is refused
        for a in range(SIZE * SIZE + 1):
            self.assertIsNone(terminal_state.try_play(a),
                              f"action {a} should be refused after terminal")
        with self.assertRaises(IllegalMove) as ctx:
            terminal_state.play(pt(0, 0))
        self.assertIn("game already over", str(ctx.exception))

    def test_no_moves_after_double_pass(self):
        s = GoState.initial(SIZE).play(PASS).play(PASS)
        self.assertEqual(s.terminal_reason(), "double_pass")
        self._assert_blocked(s)

    def test_no_moves_after_move_limit(self):
        s = state_of(board_of(), to_play=BLACK, move_count=move_limit(SIZE) - 1)
        ended = s.play(pt(0, 0))
        self.assertEqual(ended.terminal_reason(), "move_limit")
        self._assert_blocked(ended)


class TestScoring(unittest.TestCase):
    def test_komi_makes_white_favourite_on_empty_board(self):
        s = GoState.initial(SIZE)
        # two passes => score empty board
        res = score_position(s.board, SIZE, komi=2.5)
        self.assertEqual(res["black_score"], 0.0)
        self.assertEqual(res["white_score"], 2.5)
        self.assertEqual(res["winner"], "white")
        self.assertLess(res["score_margin"], 0)  # margin = black - white < 0

    def test_single_color_region(self):
        # Board with only a black stone: the whole empty region touches black.
        black_score, white_score = area_scores(board_of(black=[(2, 1)]), SIZE, 2.5)
        self.assertEqual(black_score, 25.0)   # 1 stone + 24 territory
        self.assertEqual(white_score, 2.5)    # 0 stones + 0 territory + komi

    def test_white_region(self):
        black_score, white_score = area_scores(board_of(white=[(4, 4)]), SIZE, 2.5)
        self.assertEqual(black_score, 0.0)
        self.assertEqual(white_score, 25.0 + 2.5)

    def test_neutral_dame_touching_both_colours(self):
        # One big empty region between black and white -> neutral.
        black_score, white_score = area_scores(
            board_of(black=[(2, 1)], white=[(4, 4)]), SIZE, 2.5)
        self.assertEqual(black_score, 1.0)
        self.assertEqual(white_score, 1.0 + 2.5)

    def test_closed_eye_scores_for_owner(self):
        # Black ring around the (2,2)-(3,3) interior; that 2x2 empty region
        # touches black only, so it scores for black.
        b = board_of(black=[
            (1, 2), (1, 3),
            (2, 1), (3, 1),
            (4, 2), (4, 3),
            (2, 4), (3, 4),
        ])
        s = state_of(b, to_play=WHITE)
        # interior (2,2),(2,3),(3,2),(3,3) is empty & enclosed
        regions = list(empty_regions(b, SIZE))
        sizes = {len(reg) for reg, _ in regions}
        self.assertIn(4, sizes)  # the enclosed 2x2 region exists
        black_score, white_score = area_scores(b, SIZE, 2.5)
        self.assertGreaterEqual(black_score, 4.0)  # at least the 4 interior pts
        self.assertGreater(black_score, white_score)  # black encloses territory

    def test_winner_by_margin_half_point_never_draw(self):
        from winai_loseai.game.scoring import winner_from_margin
        self.assertEqual(winner_from_margin(0.5), "black")
        self.assertEqual(winner_from_margin(-0.5), "white")


class TestLegalActionsConsistency(unittest.TestCase):
    def test_legal_equals_applicable(self):
        # For several random positions: an action is legal iff try_play succeeds.
        rng = __import__("random").Random(7)
        positions = []
        s = GoState.initial(SIZE)
        positions.append(s)
        while len(positions) <= 41 and not s.is_terminal():
            s = s.play(rng.choice(s.legal_actions()))
            positions.append(s)
        for s in positions:
            legal = set(s.legal_actions())
            for a in range(SIZE * SIZE + 1):
                ok = s.try_play(a) is not None
                self.assertEqual(ok, a in legal,
                                 f"mismatch at {s.move_count} action {a}")
                if ok:
                    self.assertEqual(s.try_play(a).to_play, other(s.to_play))

    def test_occupied_points_never_legal(self):
        b = board_of(black=[(0, 0)], white=[(0, 1)])
        s = state_of(b, to_play=BLACK)
        self.assertNotIn(pt(0, 0), s.legal_actions())
        self.assertNotIn(pt(0, 1), s.legal_actions())


if __name__ == "__main__":
    unittest.main()
