"""Storage round-trip + replay equivalence tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from winai_loseai.identity import Identity
from winai_loseai.league.runner import play_one
from winai_loseai.league.replay import replay_record, replay_all_in
from winai_loseai.league.storage import write_records, read_metadata, read_game

from tests._helpers import random_spec_


def _random_record(game_seed=11, bi=Identity.WIN, wi=Identity.LOSE, index=0):
    return play_one({
        "black": random_spec_(bi),
        "white": random_spec_(wi),
        "game_seed": game_seed,
        "batch_id": "replay_t",
        "index": index,
    })


class TestReplayEquivalence(unittest.TestCase):
    def test_replay_matches_record(self):
        rec = _random_record()
        res = replay_record(rec)
        self.assertTrue(res["ok"], res["problems"])

    def test_replay_detects_tampering(self):
        rec = _random_record()
        rec["black_score"] = rec["black_score"] + 5
        res = replay_record(rec)
        self.assertFalse(res["ok"])
        self.assertTrue(any("score field" in p for p in res["problems"]))

    def test_replay_detects_bad_utility(self):
        rec = _random_record()
        rec["black_utility"] = -rec["black_utility"]
        res = replay_record(rec)
        self.assertFalse(res["ok"])

    def test_replay_detects_final_board_tamper(self):
        rec = _random_record()
        rec["final_board"] = list(rec["final_board"])
        rec["final_board"][0] = (rec["final_board"][0] + 1) % 3
        res = replay_record(rec)
        self.assertFalse(res["ok"])
        self.assertTrue(any("final_board" in p for p in res["problems"]))

    def test_replay_detects_move_color_tamper(self):
        rec = _random_record()
        self.assertEqual(rec["moves"][0]["color"], "black")  # black moves first
        rec["moves"][0]["color"] = "white"
        res = replay_record(rec)
        self.assertFalse(res["ok"])
        self.assertTrue(any("color mismatch" in p for p in res["problems"]))

    def test_replay_detects_is_pass_tamper(self):
        rec = _random_record()
        last = rec["moves"][-1]
        last["is_pass"] = not bool(last["is_pass"])
        res = replay_record(rec)
        self.assertFalse(res["ok"])
        self.assertTrue(any("is_pass mismatch" in p for p in res["problems"]))

    def test_replay_detects_legal_count_tamper(self):
        rec = _random_record()
        rec["moves"][0]["legal_action_count"] += 5
        res = replay_record(rec)
        self.assertFalse(res["ok"])
        self.assertTrue(any("legal_action_count mismatch" in p
                            for p in res["problems"]))

    def test_record_has_final_board(self):
        rec = _random_record()
        self.assertEqual(len(rec["final_board"]), 25)
        self.assertTrue(rec["final_board"])


class TestStorageRoundTrip(unittest.TestCase):
    def test_write_read_replay_round_trip(self):
        records = [_random_record(gs, index=gs) for gs in (1, 2, 3)]
        with tempfile.TemporaryDirectory() as tmp:
            write_records(tmp, "rt", records, manifest={"note": "x"})
            meta = read_metadata(tmp)
            self.assertEqual(len(meta), 3)
            self.assertEqual(len(records), 3)
            # metadata opening prefix matches the full record
            self.assertEqual(meta[0]["opening_actions"],
                             [m["action"] for m in records[0]["moves"][:12]])
            # every metadata points to an existing full file
            for line in meta:
                self.assertTrue(os.path.exists(os.path.join(tmp, line["game_file"])))
            total, ok, fails = replay_all_in(tmp)
            self.assertEqual(total, 3)
            self.assertEqual(ok, 3, fails)
            # manifest written
            with open(os.path.join(tmp, "manifest.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["game_count"], 3)
            # read_game equals written record
            gid = records[0]["game_id"]
            self.assertEqual(read_game(tmp, gid)["moves"], records[0]["moves"])


if __name__ == "__main__":
    unittest.main()
