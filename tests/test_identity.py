"""Utility mapping invariants for the four identity/colour situations."""

from __future__ import annotations

import unittest

from winai_loseai.identity import (
    Identity, black_white_utilities,
    WINNER_BLACK, WINNER_WHITE, WINNER_DRAW,
)


class TestUtilityTable(unittest.TestCase):
    def test_win_identity(self):
        # WIN black wins -> +1; WIN black loses -> -1.
        self.assertEqual(black_white_utilities(WINNER_BLACK, Identity.WIN, Identity.WIN),
                         (1, -1))
        self.assertEqual(black_white_utilities(WINNER_WHITE, Identity.WIN, Identity.WIN),
                         (-1, 1))

    def test_lose_identity(self):
        # LOSE players want their colour to lose.
        self.assertEqual(black_white_utilities(WINNER_BLACK, Identity.LOSE, Identity.LOSE),
                         (-1, 1))
        self.assertEqual(black_white_utilities(WINNER_WHITE, Identity.LOSE, Identity.LOSE),
                         (1, -1))

    def test_mixed_identity_aligned(self):
        # Black WIN vs White LOSE: both prefer black winning.
        self.assertEqual(black_white_utilities(WINNER_BLACK, Identity.WIN, Identity.LOSE),
                         (1, 1))
        self.assertEqual(black_white_utilities(WINNER_WHITE, Identity.WIN, Identity.LOSE),
                         (-1, -1))

    def test_draw_gives_zero(self):
        self.assertEqual(black_white_utilities(WINNER_DRAW, Identity.WIN, Identity.LOSE),
                         (0, 0))
        self.assertEqual(black_white_utilities(WINNER_DRAW, Identity.LOSE, Identity.LOSE),
                         (0, 0))


if __name__ == "__main__":
    unittest.main()
