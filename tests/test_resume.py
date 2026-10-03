"""Incremental-save / resumable-batch tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from winai_loseai.league.batch import run_batch, _SimulatedStop, post_validation
from winai_loseai.league import runstore as rs
from winai_loseai.league import storage
from winai_loseai.league import replay as replay_mod

GAMES = 8   # Batch A: 4 identity combos x 2 -> 8 games (small but realistic)
SEED = 7


def _run(out, *, resume=False, concurrency=1, games=GAMES, seed=SEED,
         overwrite=False, stop_after=None):
    return run_batch(out, "A", games, seed, concurrency,
                     overwrite=overwrite, resume=resume, stop_after=stop_after)


def _fp(rec):
    return (rec["game_index"], tuple(m["action"] for m in rec["moves"]),
            rec["winner"], rec["black_score"], tuple(rec["final_board"]),
            rec["termination_reason"])


def _dir_fp(out):
    return {rec["game_index"]: _fp(rec) for rec in storage.iter_game_files(out)}


def _manifest(out):
    return json.load(open(os.path.join(out, "manifest.json"), encoding="utf-8"))


def _jsonl_order(out):
    return [line["game_index"] for line in storage.read_metadata(out)]


class TestIncrementalComplete(unittest.TestCase):
    def test_full_run_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            store = _run(out)
            self.assertEqual(store.manifest_status(), rs.STATUS_COMPLETED)

            m = _manifest(out)
            self.assertEqual(m["planned_game_count"], GAMES)
            self.assertEqual(m["completed_game_count"], GAMES)
            self.assertEqual(m["completed_indexes"], list(range(GAMES)))
            self.assertEqual(m["status"], rs.STATUS_COMPLETED)
            self.assertIsNotNone(m["last_updated"])
            self.assertIn("agents", m)

            # plan, seeds, metadata and game files all agree
            self.assertEqual(len(json.load(open(os.path.join(out, "plan.json"),
                                                 encoding="utf-8"))), GAMES)
            self.assertEqual(len(json.load(open(os.path.join(out, "game_seeds.json"),
                                                 encoding="utf-8"))), GAMES)
            meta = storage.read_metadata(out)
            self.assertEqual(len(meta), GAMES)
            ids = [line["game_id"] for line in meta]
            self.assertEqual(len(ids), len(set(ids)))
            files = list(storage.iter_game_files(out))
            self.assertEqual(len(files), GAMES)
            # no leftover temp files from the atomic writer
            games_dir = os.path.join(out, "games")
            self.assertFalse([f for f in os.listdir(games_dir) if f.endswith(".tmp")])
            self.assertEqual(rs.integrity_problems(out), [])
            total, ok, fails = replay_mod.replay_all_in(out)
            self.assertEqual((total, ok), (GAMES, GAMES))


class TestInterruptedResume(unittest.TestCase):
    def test_interrupt_then_resume_matches_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = os.path.join(tmp, "scratch")
            resumed = os.path.join(tmp, "resumed")

            _run(scratch)  # from-scratch reference

            # simulate a stop after 3 games -> interrupted
            with self.assertRaises(_SimulatedStop):
                _run(resumed, stop_after=3)
            self.assertEqual(_manifest(resumed)["status"], rs.STATUS_INTERRUPTED)
            self.assertEqual(_manifest(resumed)["completed_game_count"], 3)

            # resume finishes the rest; no duplicate JSONL lines
            store = _run(resumed, resume=True)
            self.assertEqual(store.manifest_status(), rs.STATUS_COMPLETED)
            m = _manifest(resumed)
            self.assertEqual(m["completed_game_count"], GAMES)
            self.assertEqual(m["status"], rs.STATUS_COMPLETED)
            meta = storage.read_metadata(resumed)
            self.assertEqual(len(meta), GAMES)
            ids = [line["game_id"] for line in meta]
            self.assertEqual(len(ids), len(set(ids)))

            # resumed final chess is identical to a from-scratch run
            self.assertEqual(_dir_fp(resumed), _dir_fp(scratch))
            self.assertEqual(rs.integrity_problems(resumed), [])
            total, ok, _fails = replay_mod.replay_all_in(resumed)
            self.assertEqual((total, ok), (GAMES, GAMES))


class TestResumeRefusals(unittest.TestCase):
    def test_config_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            with self.assertRaises(_SimulatedStop):
                _run(out, stop_after=2)

            # different total games -> different plan
            with self.assertRaises(rs.ConfigMismatch):
                _run(out, resume=True, games=16)
            # different batch seed -> different plan
            with self.assertRaises(rs.ConfigMismatch):
                _run(out, resume=True, seed=99)
            # different batch kind
            with self.assertRaises(rs.ConfigMismatch):
                run_batch(out, "B", 56, SEED, 1, resume=True)
            # different board size
            with self.assertRaises(rs.ConfigMismatch):
                run_batch(out, "A", GAMES, SEED, 1, resume=True, board_size=3)
            # not a run dir at all
            empty = os.path.join(tmp, "empty")
            with self.assertRaises(rs.NotARunDirectory):
                _run(empty, resume=True)

            # the interrupted run is untouched and still resumable
            self.assertEqual(_manifest(out)["status"], rs.STATUS_INTERRUPTED)
            _run(out, resume=True)
            self.assertEqual(_manifest(out)["status"], rs.STATUS_COMPLETED)

    def test_resume_overwrite_exclusive_at_cli(self):
        # CLI-level guard (not the store) is exercised via run.py separately;
        # here we assert the store refuses overwrite semantics on resume dir.
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            with self.assertRaises(_SimulatedStop):
                _run(out, stop_after=1)
            # plain fresh start into an existing run dir without overwrite fails
            with self.assertRaises(storage.OutputDirExists):
                _run(out, overwrite=False)


class TestCorruptAndTempFiles(unittest.TestCase):
    def test_corrupt_and_temp_files_not_counted_as_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            with self.assertRaises(_SimulatedStop):
                _run(out, stop_after=3)  # indexes 0,1,2 written

            games_dir = os.path.join(out, "games")
            # corrupt one completed game file
            gid1 = rs.expected_game_id("batch_A", 1)
            with open(os.path.join(games_dir, f"{gid1}.json"), "w", encoding="utf-8") as fh:
                fh.write("{ not valid json !!!")
            # drop a leftover temp file for a not-yet-run game
            tmp_path = os.path.join(games_dir, f"{rs.expected_game_id('batch_A', 5)}.json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write('{"partial": true}')

            # resume must NOT treat index 1 as done; it re-runs and repairs it
            store = _run(out, resume=True)
            self.assertEqual(store.manifest_status(), rs.STATUS_COMPLETED)
            self.assertEqual(len(list(storage.iter_game_files(out))), GAMES)
            meta = storage.read_metadata(out)
            self.assertEqual(len(meta), GAMES)
            self.assertEqual(len({line["game_id"] for line in meta}), GAMES)
            # repaired game file parses and replays
            rec1 = json.load(open(os.path.join(games_dir, f"{gid1}.json"),
                                  encoding="utf-8"))
            self.assertEqual(rec1["game_index"], 1)
            self.assertEqual(rs.integrity_problems(out), [])
            total, ok, _fails = replay_mod.replay_all_in(out)
            self.assertEqual((total, ok), (GAMES, GAMES))


class TestConcurrencyAndReRun(unittest.TestCase):
    def test_sequential_scratch_equals_concurrent_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = os.path.join(tmp, "scratch")
            concurrent = os.path.join(tmp, "concurrent")
            _run(scratch, concurrency=1)

            with self.assertRaises(_SimulatedStop):
                _run(concurrent, concurrency=1, stop_after=3)
            _run(concurrent, resume=True, concurrency=2)

            self.assertEqual(_dir_fp(concurrent), _dir_fp(scratch))
            self.assertEqual(rs.integrity_problems(concurrent), [])

    def test_completed_run_resumed_again_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            _run(out)

            def snapshot():
                snap = {}
                for base, _dirs, files in os.walk(out):
                    for f in files:
                        p = os.path.join(base, f)
                        with open(p, "rb") as fh:
                            snap[os.path.relpath(p, out)] = fh.read()
                return snap

            before = snapshot()
            store = _run(out, resume=True)  # nothing left to do
            self.assertEqual(store.manifest_status(), rs.STATUS_COMPLETED)
            self.assertEqual(_manifest(out)["status"], rs.STATUS_COMPLETED)
            after = snapshot()
            self.assertEqual(before, after)  # no file changed at all


class TestJsonlOrderingDeterministic(unittest.TestCase):
    """games.jsonl game_index order is identical whatever the scheduling."""

    def test_order_identical_across_concurrency_and_resume(self):
        expected = list(range(GAMES))
        with tempfile.TemporaryDirectory() as tmp:
            seq = os.path.join(tmp, "seq")
            conc = os.path.join(tmp, "conc")
            resu = os.path.join(tmp, "resu")

            _run(seq, concurrency=1)                    # sequential from scratch
            _run(conc, concurrency=2)                   # parallel from scratch
            with self.assertRaises(_SimulatedStop):
                _run(resu, concurrency=1, stop_after=3)
            _run(resu, resume=True, concurrency=2)      # resume with concurrency

            self.assertEqual(_jsonl_order(seq), expected)
            self.assertEqual(_jsonl_order(conc), expected)
            self.assertEqual(_jsonl_order(resu), expected)
            # and the persisted game content is the same everywhere
            self.assertEqual(_dir_fp(conc), _dir_fp(seq))
            self.assertEqual(_dir_fp(resu), _dir_fp(seq))


class TestMetadataRepair(unittest.TestCase):
    def _full_run(self, tmp):
        out = os.path.join(tmp, "run")
        _run(out)
        return out

    def _meta_path(self, out):
        return os.path.join(out, "games.jsonl")

    def test_trailing_torn_line_auto_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._full_run(tmp)
            with open(self._meta_path(out), "ab") as fh:
                fh.write(b'{"truncated":true')  # crash mid-append, no newline

            _run(out, resume=True)  # auto-repair happens on open
            self.assertEqual(_manifest(out)["status"], rs.STATUS_COMPLETED)
            self.assertEqual(_jsonl_order(out), list(range(GAMES)))
            # the torn tail is gone and the file parses cleanly
            text = open(self._meta_path(out), encoding="utf-8").read()
            self.assertFalse(text.rstrip().endswith('{"truncated":true'))
            self.assertEqual(rs.integrity_problems(out), [])
            total, ok, _fails = replay_mod.replay_all_in(out)
            self.assertEqual((total, ok), (GAMES, GAMES))

    def test_missing_metadata_rebuilt_from_game_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._full_run(tmp)
            gid2 = rs.expected_game_id("batch_A", 2)
            path = self._meta_path(out)
            kept = [ln for ln in open(path, encoding="utf-8").read().splitlines()
                    if f'"{gid2}"' not in ln]
            open(path, "w", encoding="utf-8").write("\n".join(kept) + "\n")

            file_bytes_before = open(os.path.join(out, "games", f"{gid2}.json"),
                                     "rb").read()
            _run(out, resume=True)  # restores the metadata line from the file
            self.assertEqual(_manifest(out)["status"], rs.STATUS_COMPLETED)
            self.assertEqual(_jsonl_order(out), list(range(GAMES)))
            # the game was NOT re-run: its full file is byte-identical
            file_bytes_after = open(os.path.join(out, "games", f"{gid2}.json"),
                                    "rb").read()
            self.assertEqual(file_bytes_before, file_bytes_after)
            self.assertEqual(rs.integrity_problems(out), [])

    def test_combined_missing_line_and_torn_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._full_run(tmp)
            gid1 = rs.expected_game_id("batch_A", 1)
            path = self._meta_path(out)
            kept = [ln for ln in open(path, encoding="utf-8").read().splitlines()
                    if f'"{gid1}"' not in ln]
            open(path, "w", encoding="utf-8").write("\n".join(kept) + "\n")
            with open(path, "ab") as fh:
                fh.write(b'{"tail')

            _run(out, resume=True)
            order = _jsonl_order(out)
            self.assertEqual(order, list(range(GAMES)))  # ascending, no dups
            self.assertEqual(len(order), len(set(order)))
            self.assertEqual(_manifest(out)["status"], rs.STATUS_COMPLETED)
            self.assertEqual(rs.integrity_problems(out), [])

    def test_middle_line_corruption_raises_and_is_not_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._full_run(tmp)
            path = self._meta_path(out)
            lines = open(path, encoding="utf-8").read().splitlines()
            lines[3] = "{ not json"  # a middle line, valid lines still follow
            text_before = "\n".join(lines) + "\n"
            open(path, "w", encoding="utf-8").write(text_before)

            with self.assertRaises(rs.MetadataCorrupt):
                _run(out, resume=True)
            # nothing was auto-repaired
            self.assertEqual(open(path, encoding="utf-8").read(), text_before)


class TestValidationFailedManifest(unittest.TestCase):
    def test_replay_failure_sets_validation_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            _run(out)  # completed + clean

            # tamper with a move's is_pass flag inside a game file so that the
            # game still parses (integrity passes) but full replay flags it.
            gid = rs.expected_game_id("batch_A", 0)
            gpath = os.path.join(out, "games", f"{gid}.json")
            rec = json.load(open(gpath, encoding="utf-8"))
            rec["moves"][0]["is_pass"] = not bool(rec["moves"][0]["is_pass"])
            json.dump(rec, open(gpath, "w", encoding="utf-8"))

            status, info = post_validation(out)
            self.assertEqual(status, rs.STATUS_VALIDATION_FAILED)
            self.assertGreaterEqual(info["replay_fail"], 1)
            m = _manifest(out)
            self.assertEqual(m["status"], rs.STATUS_VALIDATION_FAILED)
            self.assertIsNotNone(m["error"])

    def test_clean_run_reaffirmed_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            _run(out)
            status, info = post_validation(out)
            self.assertEqual(status, rs.STATUS_COMPLETED)
            self.assertEqual(info["replay_fail"], 0)
            self.assertEqual(_manifest(out)["status"], rs.STATUS_COMPLETED)


if __name__ == "__main__":
    unittest.main()
