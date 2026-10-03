"""Analysis summary tests (matrix + grouped openings)."""

from __future__ import annotations

import csv
import os
import tempfile
import unittest

from winai_loseai.identity import Identity
from winai_loseai.league.runner import play_one
from winai_loseai.league.storage import write_records
from winai_loseai.analysis.summary import summarize

from tests._helpers import random_spec_

ALL_COMBOS = [
    (Identity.WIN, Identity.WIN),
    (Identity.LOSE, Identity.LOSE),
    (Identity.WIN, Identity.LOSE),
    (Identity.LOSE, Identity.WIN),
]


def _play(bi, wi, seed, index):
    return play_one({
        "black": random_spec_(bi),
        "white": random_spec_(wi),
        "game_seed": seed,
        "batch_id": "sum",
        "index": index,
    })


def _build(combos, per=4):
    records = []
    i = 0
    for bi, wi in combos:
        for _ in range(per):
            records.append(_play(bi, wi, i, i))
            i += 1
    return records


def _read_matrix(tmp):
    path = os.path.join(tmp, "summary", "matchup_matrix.csv")
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    agents = rows[0][1:]
    matrix = {}
    for row in rows[1:]:
        a = row[0]
        matrix[a] = dict(zip(agents, row[1:]))
    return matrix


class TestSummary(unittest.TestCase):
    def test_summarize_produces_files(self):
        records = _build([(Identity.WIN, Identity.WIN), (Identity.WIN, Identity.LOSE)])
        with tempfile.TemporaryDirectory() as tmp:
            write_records(tmp, "sum", records)
            summary = summarize(tmp)
            self.assertEqual(summary["n_games"], 8)
            self.assertEqual(len(summary["identity_pairs"]), 2)
            self.assertEqual(sum(r["n_games"] for r in summary["identity_pairs"]), 8)
            for name in ("summary.json", "identity_pairs.csv", "matchup_matrix.csv",
                         "matchup_counts.csv", "openings.csv", "openings_grouped.csv"):
                self.assertTrue(os.path.exists(os.path.join(tmp, "summary", name)), name)
            # length-difference analysis should exist when both relations present
            self.assertEqual(len(summary["length_diffs_mixed_vs_same"]), 1)

    def test_self_play_diagonal_goal_rate_is_half(self):
        # Random WIN-vs-WIN / LOSE-vs-LOSE use the SAME agent_id for both
        # colours; the per-colour matrix must average both sides -> 0.5.
        records = _build([(Identity.WIN, Identity.WIN), (Identity.LOSE, Identity.LOSE)], per=6)
        with tempfile.TemporaryDirectory() as tmp:
            write_records(tmp, "sum", records)
            summarize(tmp)
            matrix = _read_matrix(tmp)
            self.assertEqual(matrix["TRAND-WIN"]["TRAND-WIN"], "0.5000")
            self.assertEqual(matrix["TRAND-LOSE"]["TRAND-LOSE"], "0.5000")

    def test_opening_groups_cover_conditions(self):
        records = _build(ALL_COMBOS, per=4)
        with tempfile.TemporaryDirectory() as tmp:
            write_records(tmp, "sum", records)
            summary = summarize(tmp)
            groups = {g["group"]: g for g in summary["opening_groups"]}
            # required condition rows
            for name in ("global", "WIN_vs_WIN", "LOSE_vs_LOSE",
                         "WIN_vs_LOSE", "LOSE_vs_WIN", "same_identity",
                         "mixed_identity"):
                self.assertIn(name, groups)
            # identity-combo groups have exactly their own games
            self.assertEqual(groups["WIN_vs_WIN"]["n_games"], 4)
            self.assertEqual(groups["LOSE_vs_WIN"]["n_games"], 4)
            self.assertEqual(groups["same_identity"]["n_games"], 8)
            self.assertEqual(groups["mixed_identity"]["n_games"], 8)
            # each group carries per-length prefix stats
            self.assertEqual([ps["prefix_length"] for ps in groups["global"]["prefix_stats"]],
                             [4, 8, 12])
            # agent-pair granularity is present too
            pair_groups = [g for g in summary["opening_groups"] if g["group"].startswith("pair:")]
            self.assertTrue(pair_groups)
            # grouped CSV exists with headers
            path = os.path.join(tmp, "summary", "openings_grouped.csv")
            with open(path, encoding="utf-8") as fh:
                reader = csv.reader(fh)
                header = next(reader)
            self.assertEqual(header[0], "group")


if __name__ == "__main__":
    unittest.main()
