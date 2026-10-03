"""Output-directory overwrite policy (issue #1)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from winai_loseai.identity import Identity
from winai_loseai.league.runner import play_one
from winai_loseai.league.storage import (
    write_records, prepare_out_dir, has_existing_data,
    OutputDirExists, read_metadata, iter_game_files,
)
from winai_loseai.league.replay import replay_all_in

from tests._helpers import random_spec_


def _records(n=2):
    out = []
    for i in range(n):
        out.append(play_one({
            "black": random_spec_(Identity.WIN),
            "white": random_spec_(Identity.LOSE),
            "game_seed": i,
            "batch_id": "pol",
            "index": i,
        }))
    return out


class TestOverwritePolicy(unittest.TestCase):
    def test_fresh_directory_writes_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            write_records(out, "pol", _records(2))
            self.assertEqual(len(read_metadata(out)), 2)

    def test_second_write_without_overwrite_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            write_records(out, "pol", _records(2))
            with self.assertRaises(OutputDirExists):
                prepare_out_dir(out, overwrite=False)
            with self.assertRaises(OutputDirExists):
                write_records(out, "pol", _records(2))
            # original data intact
            self.assertEqual(len(read_metadata(out)), 2)

    def test_overwrite_clears_only_experiment_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            outside = os.path.join(tmp, "outside.txt")
            with open(outside, "w", encoding="utf-8") as fh:
                fh.write("keep me")
            write_records(out, "pol", _records(2))
            # unrelated file *inside* the dir is not owned -> must survive
            stray = os.path.join(out, "notes.txt")
            with open(stray, "w", encoding="utf-8") as fh:
                fh.write("user notes")

            prepare_out_dir(out, overwrite=True)
            self.assertFalse(has_existing_data(out))
            self.assertTrue(os.path.exists(stray))       # untouched
            self.assertTrue(os.path.exists(outside))     # outside untouched

            # new run writes exactly its own games; no stale files remain
            write_records(out, "pol", _records(3))
            self.assertEqual(sum(1 for _ in iter_game_files(out)), 3)
            total, ok, fails = replay_all_in(out)
            self.assertEqual((total, ok), (3, 3))
            self.assertTrue(os.path.exists(stray))
            self.assertTrue(os.path.exists(outside))

    def test_manifest_schema_version_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            write_records(out, "pol", _records(1), manifest={"note": "x"})
            with open(os.path.join(out, "manifest.json"), encoding="utf-8") as fh:
                manifest = json.load(fh)
            self.assertEqual(manifest["game_count"], 1)
            self.assertIsNotNone(manifest.get("schema_version"))


if __name__ == "__main__":
    unittest.main()
