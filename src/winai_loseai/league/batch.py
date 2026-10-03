"""High-level orchestrator for long, resumable formal batches.

Streams finished games straight to disk through a :class:`RunStore` (never
buffering a whole batch), marks the manifest ``running`` before the first game
and ``completed`` only after the last one, and supports ``--resume`` to carry
on from whatever was already persisted.
"""

from __future__ import annotations

import time
import traceback

from .. import CODE_VERSION
from ..spec import DEFAULT_BOARD_SIZE, DEFAULT_KOMI
from .pairing import batch_jobs_for
from .runner import stream_jobs
from .runstore import RunStore, STATUS_RUNNING, STATUS_COMPLETED, \
    STATUS_INTERRUPTED, STATUS_FAILED

PROGRESS_EVERY = 64


class _SimulatedStop(Exception):
    """Internal test hook that mimics an interruption after N games."""


def run_batch(out_dir, kind: str, requested_games: int, batch_seed: int,
              concurrency: int, board_size: int = DEFAULT_BOARD_SIZE,
              komi: float = DEFAULT_KOMI, overwrite: bool = False,
              resume: bool = False, stop_after: int | None = None,
              progress_every: int = PROGRESS_EVERY) -> RunStore:
    """Run a formal batch, writing games incrementally.

    Returns the finished :class:`RunStore`.  Raises on configuration
    mismatch / inability to resume; marks the run ``interrupted`` (Ctrl-C /
    test stop) or ``failed`` (unexpected error) before re-raising.
    """
    kind = kind.upper()
    batch_id = f"batch_{kind}"
    jobs = batch_jobs_for(kind, requested_games, batch_seed, batch_id)
    cfg = {
        "batch_id": batch_id,
        "kind": kind,
        "requested_games": int(requested_games),
        "batch_seed": int(batch_seed),
        "concurrency": int(concurrency),
        "board_size": int(board_size),
        "komi": float(komi),
        "code_version": CODE_VERSION,
    }

    store = RunStore(out_dir)
    if resume:
        store.open_for_resume(jobs, cfg)
    else:
        store.start(jobs, cfg, overwrite=overwrite)

    pending = [j for j in jobs if j["index"] not in store.completed]
    planned = len(jobs)
    if not pending:
        # Nothing left to run.  Auto-finish only crash-state runs (running /
        # interrupted); a completed or validation-failed run is left untouched
        # for the caller to inspect / re-validate.
        st = store.manifest_status()
        if st in (STATUS_RUNNING, STATUS_INTERRUPTED):
            store.finish()
        return store
    store.update(STATUS_RUNNING)

    print(f"[batch-{kind}] resuming/starting from {len(store.completed)}/"
          f"{planned}; running {len(pending)} pending games "
          f"(concurrency={concurrency}, stop_after={stop_after})")
    t0 = time.perf_counter()
    done_here = 0
    try:
        for rec in stream_jobs(pending, concurrency=concurrency,
                               board_size=board_size, komi=komi):
            store.write_game(rec)
            done_here += 1
            if stop_after is not None and done_here >= stop_after:
                raise _SimulatedStop()
            if done_here % progress_every == 0:
                store.update(STATUS_RUNNING)
                el = time.perf_counter() - t0
                per = el / done_here if done_here else float("nan")
                print(f"[batch-{kind}] {len(store.completed)}/{planned} games "
                      f"({done_here} this session, {el:.1f}s, {per:.3f}s/game)")
        store.finish()
    except _SimulatedStop:
        store.update(STATUS_INTERRUPTED)
        print(f"[batch-{kind}] interrupted after {len(store.completed)}/{planned} "
              f"games (test stop); use --resume to continue.")
        raise
    except KeyboardInterrupt:
        store.update(STATUS_INTERRUPTED)
        print(f"[batch-{kind}] interrupted after {len(store.completed)}/{planned} "
              f"games; use --resume to continue.")
        raise
    except Exception as exc:  # noqa: BLE001 - we must record failure state
        store.update(STATUS_FAILED, error=traceback.format_exc(limit=5))
        print(f"[batch-{kind}] FAILED after {len(store.completed)}/{planned} "
              f"games: {exc!r}")
        raise
    return store


def post_validation(out_dir: str):
    """Integrity check + full replay of a finished run; update the manifest.

    Returns ``(status, info)`` where ``info`` carries problems / replay counts.
    A finished run is never left ``completed`` when integrity or replay finds a
    problem: it becomes ``failed`` (integrity) or ``validation_failed``
    (replay).  A clean run is re-affirmed as ``completed``.
    """
    from . import runstore as rs
    from .replay import replay_all_in

    problems = rs.integrity_problems(out_dir)
    if problems:
        rs.update_status(out_dir, rs.STATUS_FAILED,
                         error="integrity: " + "; ".join(problems))
        return rs.STATUS_FAILED, {
            "problems": problems, "replay_total": 0,
            "replay_ok": 0, "replay_fail": 0, "failures": [],
        }

    total, ok, fails = replay_all_in(out_dir)
    if fails:
        rs.update_status(
            out_dir, rs.STATUS_VALIDATION_FAILED,
            error=f"{len(fails)} of {total} game(s) failed replay validation")
        return rs.STATUS_VALIDATION_FAILED, {
            "problems": [], "replay_total": total, "replay_ok": ok,
            "replay_fail": len(fails),
            "failures": [gid for gid, _problems in fails[:20]],
        }

    rs.update_status(out_dir, rs.STATUS_COMPLETED)
    return rs.STATUS_COMPLETED, {
        "problems": [], "replay_total": total, "replay_ok": ok,
        "replay_fail": 0, "failures": [],
    }
