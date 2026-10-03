"""Read-only full validation; evidence is written outside the raw run.

Usage: python scripts/validate_run.py outputs/batch_B_shallow_seed0
"""
import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from winai_loseai.league.runstore import integrity_problems
from winai_loseai.league.storage import read_metadata, _metadata_line
from winai_loseai.league.replay import replay_record
from winai_loseai.game.state import GoState, board_has_dead_group
from winai_loseai.provenance import fingerprint


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(out):
    out = Path(out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    rows = read_metadata(str(out))
    planned = manifest["planned_game_count"]
    problems = integrity_problems(str(out))
    indexes = [r["game_index"] for r in rows]
    ascending = indexes == list(range(planned))
    legacy = "source_fingerprint" not in manifest
    if sorted(indexes) != list(range(planned)):
        problems.append("index set not complete/unique")
    if not legacy and not ascending:
        problems.append("locked formal run is not in ascending index order")
    if manifest["status"] != "completed" or manifest["completed_game_count"] != planned:
        problems.append("manifest not complete")
    if manifest["completed_indexes"] != list(range(planned)):
        problems.append("manifest completed indexes mismatch")
    meta = {r["game_id"]: r for r in rows}
    pairs = Counter((r["black_agent_id"], r["white_agent_id"]) for r in rows)
    if manifest["kind"] == "B":
        if planned != 2800 or len(pairs) != 56 or set(pairs.values()) != {50}:
            problems.append("formal Batch B pairing balance mismatch")
    seeds = json.loads((out / "game_seeds.json").read_text(encoding="utf-8"))
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    if seeds != [{"index": e["index"], "game_seed": e["game_seed"]} for e in plan]:
        problems.append("seed file differs from plan")
    replay_ok = 0
    hashes = {}
    for p in sorted((out / "games").glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        gid = rec["game_id"]
        hashes[p.name] = sha(p)
        check = replay_record(rec)
        if check["ok"]:
            replay_ok += 1
        else:
            problems.append([gid, check["problems"]])
        if meta.get(gid) != _metadata_line(rec):
            problems.append([gid, "metadata does not equal full record"])
        state = GoState.initial(rec["board_size"])
        ko = 0
        for m in rec["moves"]:
            legal, counts = state.legal_report()
            ko += counts["superko"]
            if m["superko_excluded"] != counts["superko"]:
                problems.append([gid, m["index"], "superko count mismatch"])
            if rec[f"{m['color']}_algorithm"] == "vector_mcts":
                visits = {int(k): v for k, v in m["action_visit_counts"].items()}
                if (m["simulations_used"] != 64 or m["root_visit_count"] != 64
                        or sum(visits.values()) != 64 or set(visits) != set(legal)
                        or visits[m["action"]] != max(visits.values())):
                    problems.append([gid, m["index"], "search budget/choice mismatch"])
                for key in ("action_q_black", "action_q_white"):
                    for v in m[key].values():
                        if v is not None and (not math.isfinite(v) or abs(v) > 1.00000001):
                            problems.append([gid, m["index"], "invalid Q"])
            state = state.play(m["action"])
            if board_has_dead_group(state.board, state.size):
                problems.append([gid, m["index"], "dead group"])
        if ko != rec["superko_rejections"]:
            problems.append([gid, "total superko mismatch"])
    if replay_ok != planned:
        problems.append("full replay count differs from planned")
    summary = json.loads((out / "summary/summary.json").read_text(encoding="utf-8"))
    if summary["n_games"] != planned:
        problems.append("summary count mismatch")
    for cell in summary["identity_pairs"]:
        rr = [r for r in rows if (r["black_identity"], r["white_identity"])
              == (cell["black_identity"], cell["white_identity"])]
        for key, value in {
            "n_games": len(rr),
            "black_win_rate": sum(r["winner"] == "black" for r in rr) / len(rr),
            "black_goal_rate": sum(r["black_utility"] == 1 for r in rr) / len(rr),
            "white_goal_rate": sum(r["white_utility"] == 1 for r in rr) / len(rr),
            "length_mean": sum(r["move_count"] for r in rr) / len(rr),
        }.items():
            if cell[key] != value:
                problems.append(["summary", key, "recomputation mismatch"])
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "run": out.as_posix(), "manifest_status": manifest["status"],
        "planned": planned, "completed": len(rows), "replay_ok": replay_ok,
        "strict_ascending": ascending, "legacy": legacy,
        "problems": problems, "code_version": manifest["code_version"],
        "source_fingerprint": manifest.get("source_fingerprint"),
        "raw_game_hashes_sha256": fingerprint(hashes),
        "metadata_sha256": sha(out / "games.jsonl"),
        "manifest_sha256": sha(out / "manifest.json"),
        "checks": ["plan/seeds/pairs", "full metadata equality", "full replay",
                   "every-ply liberties and superko", "64 simulations and max-visit choice",
                   "summary count/win/goal/mean recomputation"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("out"); args = parser.parse_args()
    result = validate(args.out)
    dest = ROOT / "reports/validation"; dest.mkdir(parents=True, exist_ok=True)
    (dest / (Path(args.out).name + ".json")).write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(bool(result["problems"]))
