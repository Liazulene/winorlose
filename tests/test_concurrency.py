"""Concurrency invariance (issue #4).

The sequential and process-pool paths must hand the worker *exactly the same*
``board_size`` / ``komi``; here a non-default 3x3 / komi 0.5 batch is run both
ways and compared move-for-move.
"""

from __future__ import annotations

import unittest

from winai_loseai.identity import Identity
from winai_loseai.spec import random_spec
from winai_loseai.league.runner import run_jobs

SIZE = 3
KOMI = 0.5


def _make_jobs(n=6, batch_seed=0):
    jobs = []
    ids = [Identity.WIN, Identity.LOSE]
    for i in range(n):
        jobs.append({
            "black": random_spec(ids[i % 2], seed=i),
            "white": random_spec(ids[(i + 1) % 2], seed=i + 100),
            "game_seed": batch_seed * 1000 + i,
            "batch_id": "conc",
            "index": i,
        })
    return jobs


def _fingerprint(records):
    out = []
    for r in records:
        out.append({
            "board_size": r["board_size"],
            "komi": r["komi"],
            "winner": r["winner"],
            "black_score": r["black_score"],
            "white_score": r["white_score"],
            "move_count": r["move_count"],
            "termination_reason": r["termination_reason"],
            "seq": [(m["action"], m["color"]) for m in r["moves"]],
        })
    return out


class TestConcurrencyInvariance(unittest.TestCase):
    def test_sequential_equals_pool_on_3x3(self):
        jobs = _make_jobs()
        seq = run_jobs(jobs, concurrency=1, board_size=SIZE, komi=KOMI)
        par = run_jobs(jobs, concurrency=2, board_size=SIZE, komi=KOMI)

        self.assertEqual(len(seq), len(par))
        fp_seq = _fingerprint(seq)
        fp_par = _fingerprint(par)
        self.assertEqual(fp_seq, fp_par)

        # guard against the previous bug where the pool silently used 5x5/2.5
        for r in par:
            self.assertEqual(r["board_size"], SIZE)
            self.assertEqual(r["komi"], KOMI)
            self.assertEqual(r["board_size"], 3)


if __name__ == "__main__":
    unittest.main()
