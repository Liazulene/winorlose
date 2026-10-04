"""Read-only pilot design and historical RNG inventory audit; runs no games."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from winai_loseai.experiments import g1_pass8 as experiment
from winai_loseai.league.runstore import job_to_entry


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_hash(*parts):
    # Independent transcription of the unchanged frozen RNG key format.
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:16], "big")


def main():
    protocol = experiment.protocol()
    actual = experiment.jobs()
    blocks = [(batch_seed, identity_index, orientation_index)
              for batch_seed in protocol["batch_seeds"]
              for identity_index in range(4) for orientation_index in range(2)]
    scheduler = random.Random(protocol["schedule_seed"])
    scheduler.shuffle(blocks)
    orders = [[0, 8], [8, 0]] * 12
    scheduler.shuffle(orders)
    expected = [(block, arm) for block, order in zip(blocks, orders) for arm in order]
    problems = []
    strata = Counter()
    for index, ((batch_seed, identity_index, orientation_index), arm) in enumerate(expected):
        job = actual[index]
        black_identity, white_identity = protocol["identity_directions"][identity_index]
        black_seed, white_seed = protocol["agent_seed_orientations"][orientation_index]
        wanted = (index, seed_hash("game-seed", batch_seed, identity_index * 2 + orientation_index),
                  arm, black_identity, white_identity, black_seed, white_seed, 256, 256)
        found = (job["index"], job["game_seed"], job["pass_min_ply"],
                 job["black"].identity.value, job["white"].identity.value,
                 job["black"].seed, job["white"].seed,
                 job["black"].simulations(), job["white"].simulations())
        if found != wanted:
            problems.append(f"job {index} differs from independently constructed schedule")
        strata[(arm, batch_seed, black_identity, white_identity)] += 1
    current_seeds = {job["game_seed"] for job in actual}
    current_streams = {seed_hash("agent-stream", job["game_seed"], color, job[color].seed)
                       for job in actual for color in ("black", "white")}
    if len(actual) != 48 or len(current_seeds) != 24 or len(current_streams) != 48:
        problems.append("wrong game/paired-seed/derived-stream count")
    if set(strata.values()) != {2} or len(strata) != 24:
        problems.append("unbalanced rule x seed x direction strata")
    arm_orders = Counter(tuple(actual[i + j]["pass_min_ply"] for j in (0, 1))
                         for i in range(0, len(actual), 2))
    if arm_orders != {(0, 8): 12, (8, 0): 12}:
        problems.append("arm order not balanced 12:12")

    required_inherited = {
        "batch_A_seed0", "batch_B_shallow_seed0", "batch_B_shallow_seed1",
        "d1_g0_cost_v1", "d1_g0_estimation_v1", "smoke_mcts", "smoke_random",
    }
    # Exclude only this pilot's exact output-directory name: rerunning the
    # audit after execution must not label deliberate self-reuse a collision.
    directories = [path.parent for path in sorted((ROOT / "outputs").glob("*/game_seeds.json"))
                   if path.parent.name != protocol["batch_id"]]
    found_inherited = {directory.name for directory in directories}
    for missing in sorted(required_inherited - found_inherited):
        problems.append(f"missing required historical inventory: {missing}")
    directories.append(ROOT.parent / "winorlose_d0_v1/outputs/d0_g0_v1_seed0")
    comparisons = []
    for directory in directories:
        source_files = {}
        seed_path = directory / "game_seeds.json"
        old_seed_rows = json.loads(seed_path.read_text())
        old_seeds = {row["game_seed"] for row in old_seed_rows}
        source_files[str(seed_path)] = digest(seed_path)
        plan_path = directory / "plan.json"
        if plan_path.exists():
            old_jobs = json.loads(plan_path.read_text())
            source_files[str(plan_path)] = digest(plan_path)
            origin = "plan.json"
        else:
            paths = sorted((directory / "games").glob("*.json"))
            old_jobs = [json.loads(path.read_text()) for path in paths]
            source_files.update({str(path): digest(path) for path in paths})
            origin = "complete game JSONs (no plan.json exists)"
        if len(old_jobs) != len(old_seed_rows) or {row["game_seed"] for row in old_jobs} != old_seeds:
            problems.append(f"historical inventory count/seed mismatch: {directory.name}")
        old_streams = {seed_hash("agent-stream", job["game_seed"], color, job[color]["seed"])
                       for job in old_jobs for color in ("black", "white")}
        seed_overlap = sorted(current_seeds & old_seeds)
        stream_overlap = sorted(current_streams & old_streams)
        if seed_overlap or stream_overlap:
            problems.append(f"historical RNG overlap: {directory.name}")
        comparisons.append({
            "inventory": directory.name, "directory": str(directory),
            "source": origin, "records": len(old_jobs),
            "distinct_game_seeds": len(old_seeds), "distinct_derived_streams": len(old_streams),
            "game_seed_overlap": seed_overlap, "derived_stream_overlap": stream_overlap,
            "source_file_sha256": source_files,
        })
    result = {
        "purpose": "Independent prelaunch schedule/seed review. No pilot or synthetic games executed; this is not a full-code acceptance report.",
        "experiment_id": protocol["experiment_id"],
        "preregistration_sha256_at_check": digest(experiment.PROTOCOL),
        "script_sha256": digest(Path(__file__)),
        "new_games": len(actual), "paired_blocks": len(current_seeds),
        "new_distinct_agent_streams": len(current_streams),
        "required_historical_inventories": sorted(required_inherited | {"d0_g0_v1_seed0"}),
        "excluded_current_pilot_directory": str(ROOT / "outputs" / protocol["batch_id"]),
        "arm_order_counts": {str(key): value for key, value in sorted(arm_orders.items())},
        "rule_seed_direction_counts": [{"pass_min_ply": key[0], "batch_seed": key[1],
                                       "black_identity": key[2], "white_identity": key[3], "count": value}
                                      for key, value in sorted(strata.items())],
        "plan_sha256": hashlib.sha256(json.dumps([job_to_entry(job) for job in actual], sort_keys=True).encode()).hexdigest(),
        "derived_stream_inventory_sha256": hashlib.sha256(json.dumps(sorted(current_streams)).encode()).hexdigest(),
        "comparisons": comparisons,
        "limitations": ["Zero hash/seed overlap is not a proof of PRNG statistical independence.",
                        "Historical inventory overlap with itself is allowed; only new-versus-historical isolation is tested.",
                        "The D0 inventory is read from the sibling winorlose_d0_v1 worktree; that directory is required to rerun this check.",
                        "Paired arms deliberately reuse initial game and agent seeds; their random-number consumption may diverge."],
        "problems": problems,
    }
    print(json.dumps(result, sort_keys=True, indent=2))
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
