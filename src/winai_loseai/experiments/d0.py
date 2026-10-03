"""Locked deterministic D0 experiment. Run via scripts/run_d0.py.

Only this new experiment entry point can mutate its own new output. Historical
G0 rules/search and records remain unchanged. Analysis is descriptive: the
four identity labels do not supply independent deterministic replicates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time
import traceback

from .. import CODE_VERSION
from ..identity import Identity, black_white_utilities
from ..spec import AgentSpec
from ..game.state import GoState, BLACK, WHITE, board_has_dead_group
from ..game.scoring import score_position
from ..provenance import current_provenance, source_lock
from ..league.pairing import make_job
from ..league.runner import stream_jobs, play_one
from ..league.runstore import (RunStore, ConfigMismatch, integrity_problems,
                              STATUS_RUNNING, STATUS_INTERRUPTED, STATUS_FAILED,
                              STATUS_COMPLETED, STATUS_VALIDATION_FAILED)
from ..league.storage import read_metadata, _metadata_line
from ..league.replay import replay_record

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = ROOT / "experiments/d0_v1/preregistration.json"
ENTRY_POINT = ROOT / "scripts/run_d0.py"
PREREGISTRATION_SHA256 = "6ad743a6af29b274680c99ca279042c3fc209e6133c8410145c517a78daf74e2"
BATCH_ID = "d0_g0_v1"
POLICIES = ("always_pass", "one_stone_then_pass", "greedy_area")
IDENTITIES = ((Identity.WIN, Identity.WIN), (Identity.LOSE, Identity.LOSE),
              (Identity.WIN, Identity.LOSE), (Identity.LOSE, Identity.WIN))
PROTECTED_NAMES = {"batch_A_seed0", "batch_B_shallow_seed0", "batch_B_shallow_seed1"}


class D0Interrupted(Exception):
    """Requested deterministic checkpoint; not an experimental failure."""


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def experiment_lock():
    if sha256(PROTOCOL) != PREREGISTRATION_SHA256:
        raise ConfigMismatch("D0 preregistration changed; create a new version")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["code_version"] != CODE_VERSION or protocol["experiment_id"] != "D0-G0-v1":
        raise ConfigMismatch("D0 protocol/version mismatch")
    return {"experiment_id": "D0-G0-v1", **current_provenance(),
            "preregistration_sha256": sha256(PROTOCOL),
            "entry_point_sha256": sha256(ENTRY_POINT)}


def assert_output_allowed(out):
    path = Path(out).resolve()
    if PROTECTED_NAMES.intersection(path.parts):
        raise ValueError("historical G0 output is read-only")
    if path == ROOT or path in ROOT.parents or path == ROOT / "outputs":
        raise ValueError("output must be a dedicated new experiment directory")
    if path.is_relative_to(ROOT / "reports"):
        raise ValueError("historical report tree is read-only")
    if (path / "manifest.json").exists():
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("batch_id") != BATCH_ID:
            raise ValueError("cannot modify a different experiment")
    # Refuse symlinked children too: no writes outside the dedicated run tree.
    if path.exists() and any(p.is_symlink() for p in path.rglob("*")):
        raise ValueError("output contains symlinks")
    return path


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def jobs():
    result = []
    for ib, iw in IDENTITIES:
        for ab in POLICIES:
            for aw in POLICIES:
                black = AgentSpec(f"{ab}-{ib.value}", ib, ab, "none", 0)
                white = AgentSpec(f"{aw}-{iw.value}", iw, aw, "none", 0)
                result.append(make_job(black, white, 0, BATCH_ID, len(result)))
    return result


def strip_timing(record):
    return {key: value for key, value in record.items() if key != "game_wall_ms"}


def config(concurrency):
    return {"batch_id": BATCH_ID, "kind": "D0-G0-v1", "requested_games": 36,
            "batch_seed": 0, "concurrency": concurrency,
            "board_size": 5, "komi": 2.5, "code_version": CODE_VERSION}


def run(out, concurrency=1, resume=False, stop_after=None):
    if concurrency not in (1, 2):
        raise ValueError("D0 concurrency must be 1 or 2")
    if stop_after is not None and stop_after < 1:
        raise ValueError("stop_after must be positive")
    out = assert_output_allowed(out)
    locked = experiment_lock()
    store = RunStore(str(out))
    if resume:
        lock_path = out / "experiment_lock.json"
        if not lock_path.exists() or json.loads(lock_path.read_text()) != locked:
            raise ConfigMismatch("D0 experiment lock differs or is missing")
        saved_protocol = out / "preregistration.json"
        if not saved_protocol.exists() or sha256(saved_protocol) != locked["preregistration_sha256"]:
            raise ConfigMismatch("D0 saved preregistration differs or is missing")
        store.open_for_resume(jobs(), config(concurrency))
        if store.manifest_status() == STATUS_COMPLETED and not store.pending_indexes():
            # Read-only verification of completed runs; no timestamp rewrites.
            checked = validate(out)
            if checked["problems"]:
                raise ValueError(checked["problems"])
            return checked
    else:
        # A new run must have an entirely empty dedicated directory.
        if out.exists() and any(out.iterdir()):
            raise FileExistsError("D0 output must be empty; use --resume")
        store.start(jobs(), config(concurrency), overwrite=False)
        atomic_json(out / "experiment_lock.json", locked)
        (out / "preregistration.json").write_bytes(PROTOCOL.read_bytes())
    pending = [job for job in jobs() if job["index"] not in store.completed]
    store.update(STATUS_RUNNING)
    count = 0
    try:
        for record in stream_jobs(pending, concurrency=concurrency, board_size=5, komi=2.5):
            if experiment_lock() != locked:
                raise ConfigMismatch("D0 experimental inputs changed during run")
            store.write_game(record)
            count += 1
            if count % 5 == 0:
                store.update(STATUS_RUNNING)
                print(f"[D0] checkpoint {len(store.completed)}/36", flush=True)
            if stop_after is not None and count >= stop_after:
                raise D0Interrupted(f"checkpoint after {count} new games")
        # Validate while still running; completion is contingent on all checks.
        store.update(STATUS_RUNNING)
        checked = validate(out)
        if checked["problems"]:
            store.update(STATUS_VALIDATION_FAILED, error="; ".join(checked["problems"]))
            atomic_json(out / "validation.json", checked)
            raise ValueError("D0 validation failed")
        atomic_json(out / "validation.json", checked)
        atomic_json(out / "analysis.json", analyze(out))
        store.finish()
        return checked
    except (D0Interrupted, KeyboardInterrupt):
        store.update(STATUS_INTERRUPTED)
        raise
    except Exception:
        if store.manifest_status() != STATUS_VALIDATION_FAILED:
            store.update(STATUS_FAILED, error=traceback.format_exc(limit=5))
        raise


def records(out):
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((Path(out) / "games").glob("*.json"))]


def validate(out):
    """Read-only full replay, policy reproduction, exact metadata and G0 checks."""
    out = Path(out)
    problems = integrity_problems(str(out))
    locked = json.loads((out / "experiment_lock.json").read_text())
    if locked != experiment_lock():
        problems.append("experiment lock mismatch")
    if sha256(out / "preregistration.json") != locked["preregistration_sha256"]:
        problems.append("saved preregistration mismatch")
    if json.loads((out / "source_lock.json").read_text()) != source_lock():
        problems.append("current source lock mismatch")
    plan = jobs()
    manifest = json.loads((out / "manifest.json").read_text())
    for key, value in config(manifest.get("concurrency")).items():
        if manifest.get(key) != value:
            problems.append(f"D0 manifest mismatch: {key}")
    if manifest.get("completed_indexes") != list(range(36)):
        problems.append("D0 completed indexes mismatch")
    if manifest.get("completed_game_count") != 36:
        problems.append("D0 completed count mismatch")
    if manifest.get("concurrency") not in (1, 2):
        problems.append("D0 invalid concurrency")
    saved_plan = json.loads((out / "plan.json").read_text())
    from ..league.runstore import job_to_entry
    if saved_plan != [job_to_entry(j) for j in plan]:
        problems.append("D0 plan mismatch")
    expected_seeds = [{"index": j["index"], "game_seed": j["game_seed"]} for j in plan]
    if json.loads((out / "game_seeds.json").read_text()) != expected_seeds:
        problems.append("D0 seed plan mismatch")
    saved = records(out)
    meta = read_metadata(str(out))
    if len(saved) != 36 or len(meta) != 36:
        problems.append("D0 expected exactly 36 complete games")
    by_id = {r["game_id"]: r for r in meta}
    replay_ok = reproduced_ok = 0
    for rec in saved:
        gid = rec["game_id"]
        result = replay_record(rec)
        replay_ok += result["ok"]
        problems.extend(f"{gid}: {p}" for p in result["problems"])
        if by_id.get(gid) != _metadata_line(rec):
            problems.append(f"{gid}: full metadata differs")
        idx = rec["game_index"]
        if idx < 0 or idx >= len(plan):
            problems.append(f"{gid}: bad index")
            continue
        fresh = play_one(plan[idx])
        if strip_timing(fresh) != strip_timing(rec):
            problems.append(f"{gid}: deterministic policy reproduction mismatch")
        else:
            reproduced_ok += 1
        state = GoState.initial(5)
        superko = 0
        for move in rec["moves"]:
            _, counts = state.legal_report()
            if move["superko_excluded"] != counts["superko"]:
                problems.append(f"{gid}: per-move superko mismatch")
            superko += counts["superko"]
            state = state.play(move["action"])
            if board_has_dead_group(state.board, 5):
                problems.append(f"{gid}: dead group")
        if rec["superko_rejections"] != superko:
            problems.append(f"{gid}: total superko mismatch")
        if not 2 <= rec["move_count"] <= 100:
            problems.append(f"{gid}: invalid length")
    if len(saved) == 36 and not problems:
        analysis_path = out / "analysis.json"
        if analysis_path.exists():
            if json.loads(analysis_path.read_text()) != analyze(out):
                problems.append("D0 saved analysis mismatch")
        elif manifest.get("status") == STATUS_COMPLETED:
            problems.append("D0 completed run missing analysis")
    checks = analytical_checks(saved)
    problems.extend(key for key, passed in checks.items() if not passed)
    return {"experiment_id": "D0-G0-v1", "problems": problems,
            "game_count": len(saved), "replay_ok": replay_ok,
            "policy_reproduction_ok": reproduced_ok, "exact_checks": checks,
            "source_fingerprint": current_provenance()["source_fingerprint"]}


def analytical_checks(saved):
    checks = {}
    for rec in saved:
        ab, aw = rec["black_algorithm"], rec["white_algorithm"]
        prefix = rec["game_id"]
        if ab == aw == "always_pass":
            checks[prefix + "-H1"] = ([m["action"] for m in rec["moves"]] == [25, 25]
                                     and rec["black_score"] == 0 and rec["white_score"] == 2.5)
        if ab == "one_stone_then_pass" and aw == "always_pass":
            checks[prefix + "-H2"] = (rec["move_count"] == 3 and rec["black_score"] == 25
                                     and rec["white_score"] == 2.5)
        if ab == "always_pass":
            checks[prefix + "-H3"] = (rec["black_score"] == 0 and rec["winner"] == "white")
    for ab in POLICIES:
        for aw in POLICIES:
            group = [r for r in saved if r["black_algorithm"] == ab and r["white_algorithm"] == aw]
            keys = ("moves", "winner", "black_score", "white_score", "final_board", "move_count", "termination_reason")
            checks[f"{ab}/{aw}-H4"] = len(group) == 4 and all(
                all(r[k] == group[0][k] for k in keys) for r in group)
    return checks


def describe_game(rec):
    state = GoState.initial(5)
    actions = [m["action"] for m in rec["moves"]]
    pass_events = []
    counts = {c: {"passes": 0, "placements": 0, "captured_by_opponent": 0} for c in ("black", "white")}
    for i, move in enumerate(rec["moves"]):
        color = move["color"]
        if move["is_pass"]:
            counts[color]["passes"] += 1
            if state.consecutive_passes == 0:
                scored = score_position(state.board, 5, 2.5)
                utilities = black_white_utilities(scored["winner"], Identity(rec["black_identity"]), Identity(rec["white_identity"]))
                pass_events.append({"ply": i + 1, "proposer": color,
                    "score_margin": scored["score_margin"], "instant_utilities": list(utilities),
                    "next_action_available": i + 1 < len(actions),
                    "accepted": actions[i + 1] == 25 if i + 1 < len(actions) else None})
        else:
            counts[color]["placements"] += 1
        child = state.play(move["action"])
        enemy, enemy_code = ("white", WHITE) if state.to_play == BLACK else ("black", BLACK)
        counts[enemy]["captured_by_opponent"] += state.board.count(enemy_code) - child.board.count(enemy_code)
        state = child
    own = {color: actions[offset::2] for color, offset in (("black", 0), ("white", 1))}
    return {key: rec[key] for key in ("game_id", "black_identity", "white_identity", "black_algorithm",
            "white_algorithm", "winner", "black_score", "white_score", "black_utility", "white_utility",
            "move_count", "termination_reason", "superko_rejections", "game_wall_ms")} | {
        "actions": actions, "color_counts": counts, "pass_proposals": pass_events,
        "routes": {"empty_double_pass": actions == [25, 25],
            "black_one_stone_double_pass": len(actions) == 3 and actions[0] < 25 and actions[1:] == [25, 25],
            "all_pass_by_color": {c: all(a == 25 for a in seq) for c, seq in own.items()},
            "one_stone_then_pass_by_color": {c: bool(seq) and seq[0] < 25 and all(a == 25 for a in seq[1:]) for c, seq in own.items()}},
        "prefixes": {str(length): {"raw": actions[:length] if len(actions) >= length else None,
                     "END_padded": (actions + [-1] * length)[:length]} for length in (4, 8, 12)}}


def analyze(out):
    saved = records(out)
    rows = [describe_game(rec) for rec in saved]
    lengths = [r["move_count"] for r in rows]
    groups = {}
    for ib, iw in IDENTITIES:
        subset = [r for r in rows if r["black_identity"] == ib.value and r["white_identity"] == iw.value]
        lens = [r["move_count"] for r in subset]
        groups[f"{ib.value}/{iw.value}"] = {
            "n_conditions": len(subset), "lengths": lens, "mean_length": statistics.mean(lens),
            "median_length": statistics.median(lens), "min": min(lens), "max": max(lens),
            "black_goal_count": sum(r["black_utility"] == 1 for r in subset),
            "white_goal_count": sum(r["white_utility"] == 1 for r in subset),
            "length2": lens.count(2), "length3": lens.count(3),
            "length_le8": sum(n <= 8 for n in lens), "length_ge60": sum(n >= 60 for n in lens)}
    trajectory_count = len({tuple(r["actions"]) for r in rows})
    return {"experiment_id": "D0-G0-v1", "descriptive_only": True,
            "n_records": len(rows), "n_ordered_policy_conditions": 9,
            "n_unique_trajectories": trajectory_count,
            "identity_groups": groups, "rows": rows,
            "lengths_all": lengths, "superko_total": sum(r["superko_rejections"] for r in rows),
            "termination_counts": {reason: sum(r["termination_reason"] == reason for r in rows) for reason in ("double_pass", "move_limit")},
            "game_wall_ms_sum": sum(r["game_wall_ms"] for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "validate"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=1, choices=(1, 2))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", type=int)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        result = (run(args.out, args.concurrency, args.resume, args.stop_after)
                  if args.command == "run" else validate(args.out))
    except D0Interrupted as error:
        print(str(error), flush=True)
        return 75
    print(json.dumps(result, indent=2))
    print(f"wall_seconds={time.perf_counter() - started:.6f}")
    return int(bool(result["problems"]))
