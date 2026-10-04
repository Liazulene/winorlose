#!/usr/bin/env python3
"""Read-only G1-pass8 final audit. Standard library only; no engine imports.

This is an independent final-area and arithmetic check with a small actual-path
capture reconstruction. It is NOT another complete Go/search rules engine:
nonpass root legal-set completeness, rollout/tree legality and search values
are not independently proved. Actual nonpass situational repetition and suicide
are checked, and reported root pass membership/budgets/utility symmetry checked.
Run only after the owner declares the fixed 48-game data ready.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import sys

EXPERIMENT = "G1-pass8-pilot-v1"
BATCH = "g1_pass8_pilot_v1"
DIRECTIONS = ("WIN/WIN", "LOSE/LOSE", "WIN/LOSE", "LOSE/WIN")
RULES = {0: "G0", 8: "G1-pass8"}
DELTA_KEYS = ("length_delta", "extra_length_delta", "black_goal_delta",
              "white_goal_delta", "joint_goal_delta", "black_board_win_delta")
PROVENANCE_KEYS = ("code_version", "schema_version", "source_fingerprint", "python_version")
PROTOCOL_SHA = "99b6520c514a931b602cfc99731ac17e81069d82e177dc3cd21b493f00e4591c"
PLAN_SHA = "27ba0d57f1ba8801fb1e70c65f66d04e6732cfb32c7d7bcb373df1be8701147f"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def differences(expected, actual, path="root"):
    """Strict shape/type checks, tolerant only for finite float arithmetic."""
    errors = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object"]
        for key in sorted(expected.keys() - actual.keys()):
            errors.append(f"{path}.{key}: missing")
        for key in sorted(actual.keys() - expected.keys()):
            errors.append(f"{path}.{key}: unexpected")
        for key in sorted(expected.keys() & actual.keys()):
            errors.extend(differences(expected[key], actual[key], f"{path}.{key}"))
    elif isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected array"]
        if len(expected) != len(actual):
            errors.append(f"{path}: length {len(actual)} != {len(expected)}")
        for i, (left, right) in enumerate(zip(expected, actual)):
            errors.extend(differences(left, right, f"{path}[{i}]"))
    elif isinstance(expected, bool) or expected is None:
        if type(expected) is not type(actual) or expected != actual:
            errors.append(f"{path}: {actual!r} != {expected!r}")
    elif isinstance(expected, (int, float)):
        if (not isinstance(actual, (int, float)) or isinstance(actual, bool)
                or not math.isfinite(actual) or not math.isfinite(expected)
                or not math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-9)):
            errors.append(f"{path}: {actual!r} != {expected!r}")
    elif type(expected) is not type(actual) or expected != actual:
        errors.append(f"{path}: {actual!r} != {expected!r}")
    return errors


def neighbors(point):
    row, col = divmod(point, 5)
    return tuple(r * 5 + c for r, c in ((row-1, col), (row+1, col),
                                      (row, col-1), (row, col+1))
                 if 0 <= r < 5 and 0 <= c < 5)


ADJ = tuple(neighbors(point) for point in range(25))


def area(board):
    """Connected-empty-component ownership, implemented with disjoint sets."""
    if len(board) != 25 or any(type(x) is not int or x not in (0, 1, 2) for x in board):
        raise ValueError("invalid 5x5 board")
    parent = list(range(25))
    def root(point):
        while parent[point] != point:
            point = parent[point]
        return point
    for point, value in enumerate(board):
        if value == 0:
            for nb in ADJ[point]:
                if board[nb] == 0:
                    parent[root(nb)] = root(point)
    regions = {}
    for point, value in enumerate(board):
        if value == 0:
            region = regions.setdefault(root(point), [0, set()])
            region[0] += 1
            region[1].update(board[n] for n in ADJ[point] if board[n])
    scores = [float(board.count(1)), float(board.count(2)) + 2.5]
    for size, border in regions.values():
        if len(border) == 1:
            scores[next(iter(border))-1] += size
    margin = scores[0] - scores[1]
    return dict(black_score=scores[0], white_score=scores[1], score_margin=margin,
                winner="black" if margin > 0 else "white" if margin < 0 else "draw")


def utilities(winner, ib, iw):
    result = []
    for color, identity in (("black", ib), ("white", iw)):
        if identity not in ("WIN", "LOSE"):
            raise ValueError("invalid identity")
        board_result = 0 if winner == "draw" else 1 if winner == color else -1
        result.append(board_result if identity == "WIN" else -board_result)
    return result


def component(board, point):
    stones, frontier, liberties = {point}, [point], set()
    while frontier:
        current = frontier.pop()
        for nb in ADJ[current]:
            if board[nb] == 0:
                liberties.add(nb)
            elif board[nb] == board[point] and nb not in stones:
                frontier.append(nb)
                stones.add(nb)
    return stones, liberties


def apply_placement(board, action, color):
    """Only actual placement/capture geometry. No search or root enumeration."""
    if not 0 <= action < 25 or board[action]:
        raise ValueError("invalid or occupied placement")
    result = list(board)
    result[action] = color
    captured = set()
    for nb in ADJ[action]:
        if result[nb] == 3-color:
            group, liberties = component(result, nb)
            if not liberties:
                captured.update(group)
    for point in captured:
        result[point] = 0
    if not component(result, action)[1]:
        raise ValueError("actual suicide")
    return result, len(captured)


def seed_from(parts):
    raw = "|".join(map(str, parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:16], "big")


def design(protocol):
    """Reconstruct schedule from fixed preregistration without production code."""
    blocks = []
    for seed in protocol["batch_seeds"]:
        for index, direction in enumerate(protocol["identity_directions"]):
            for orientation, (bs, ws) in enumerate(protocol["agent_seed_orientations"]):
                block_index = 2 * index + orientation
                blocks.append(dict(budget=256, batch_seed=seed,
                    black_identity=direction[0], white_identity=direction[1],
                    black_seed=bs, white_seed=ws, replicate=0,
                    block_index=block_index, block_id=f"{seed}:{block_index}"))
    rng = random.Random(protocol["schedule_seed"])
    rng.shuffle(blocks)
    orders = [[0, 8], [8, 0]] * 12
    rng.shuffle(orders)
    cells = []
    plan = []
    for block, order in zip(blocks, orders):
        for rule in order:
            cell = dict(block, pass_min_ply=rule, ruleset=RULES[rule])
            cells.append(cell)
            entry = dict(index=len(plan),
                game_seed=seed_from(("game-seed", block["batch_seed"], block["block_index"])),
                pass_min_ply=rule)
            for color in ("black", "white"):
                identity, seed = block[color+"_identity"], block[color+"_seed"]
                entry[color] = dict(agent_id=f"{identity}-medium-s{seed}",
                    identity=identity, algorithm="vector_mcts", compute_level="medium", seed=seed)
            plan.append(entry)
    return cells, plan


def distribution(values):
    seq = sorted(values)
    result = {"n": len(seq), "mean": math.fsum(seq)/len(seq) if seq else None}
    for label, fraction in (("min", 0), ("q1", .25), ("median", .5),
                            ("q3", .75), ("p90", .9), ("p95", .95), ("max", 1)):
        if not seq:
            result[label] = None
            continue
        position = fraction * (len(seq)-1)
        low, high = math.floor(position), math.ceil(position)
        weight = position-low
        result[label] = seq[low] * (1-weight) + seq[high] * weight
    return result


def reconstruct(rec, cell, entry, byte_count, provenance):
    errors = []
    def check(condition, label):
        if not condition:
            errors.append(label)
    def equal(expected, actual, label):
        errors.extend(differences(expected, actual, label))
    expected_header = dict(game_id=f"{BATCH}-g{entry['index']:06d}", batch_id=BATCH,
        game_index=entry["index"], game_seed=entry["game_seed"], board_size=5,
        komi=2.5, pass_min_ply=entry["pass_min_ply"], ruleset=RULES[entry["pass_min_ply"]],
        **provenance)
    for color in ("black", "white"):
        expected_header[color] = entry[color]
        for key in ("agent_id", "identity", "algorithm", "compute_level"):
            expected_header[color+"_"+key] = entry[color][key]
    for key, value in expected_header.items():
        equal(value, rec.get(key), key)
    actions = [move["action"] for move in rec["moves"]]
    rule = entry["pass_min_ply"]
    check(type(rec["move_count"]) is int, "move_count integer")
    equal(len(actions), rec["move_count"], "move_count")
    check(rule+2 <= len(actions) <= 100, "registered length limits")
    counts = {color: dict(passes=0, placements=0, captured_by_opponent=0)
              for color in ("black", "white")}
    proposals = []
    board = [0]*25
    history = {(tuple(board), 1)}
    previous_pass = False
    superko = 0
    for i, move in enumerate(rec["moves"]):
        color, color_code = ("black", 1) if i % 2 == 0 else ("white", 2)
        enemy = "white" if color == "black" else "black"
        label = f"action[{i+1}]"
        action = move["action"]
        check(type(action) is int and 0 <= action <= 25, label+" action range/type")
        equal(i+1, move["index"], label+" index")
        equal(color, move["color"], label+" color")
        equal(action == 25, move["is_pass"], label+" is_pass")
        check(not (previous_pass and i and actions[i-1] == 25 and i > 1 and actions[i-2] == 25), label+" after terminal")
        for key in ("root_visit_count", "simulations_used"):
            check(type(move[key]) is int and move[key] == 256, label+" "+key)
        maps = [move[key] for key in ("action_visit_counts", "action_q_black", "action_q_white")]
        check(all(isinstance(mapping, dict) for mapping in maps), label+" map objects")
        canonical = all(type(key) is str and key in {str(a) for a in range(26)}
                        for mapping in maps for key in mapping)
        check(canonical, label+" canonical map keys")
        check(set(maps[0]) == set(maps[1]) == set(maps[2]), label+" map key equality")
        check(type(move["legal_action_count"]) is int and len(maps[0]) == move["legal_action_count"], label+" legal count")
        check(("25" in maps[0]) == (i >= rule), label+" pass root membership")
        check(all(int(key) == 25 or board[int(key)] == 0 for key in maps[0]), label+" root occupied action")
        visits = maps[0]
        check(all(type(value) is int and value >= 0 for value in visits.values()), label+" nonnegative integer visits")
        equal(256, sum(visits.values()), label+" visit sum")
        check(str(action) in visits and visits[str(action)] == max(visits.values(), default=-1), label+" chosen maximum visits")
        for key in visits:
            qb, qw = maps[1].get(key), maps[2].get(key)
            if visits[key] == 0:
                check(qb is None and qw is None, label+" unvisited Q null")
            else:
                finite = all(isinstance(q, (int, float)) and not isinstance(q, bool)
                             and math.isfinite(q) and abs(q) <= 1+1e-10 for q in (qb, qw))
                check(finite, label+" visited Q bounds")
                if finite:
                    equal(qb, -qw if cell["black_identity"] == cell["white_identity"] else qw,
                          label+" utility-vector Q relation")
        check(type(move["superko_excluded"]) is int and move["superko_excluded"] >= 0, label+" superko count")
        superko += move["superko_excluded"]
        check(isinstance(move["search_time_ms"], (int, float)) and not isinstance(move["search_time_ms"], bool)
              and math.isfinite(move["search_time_ms"]) and move["search_time_ms"] >= 0, label+" search timing")
        if action == 25:
            check(i >= rule, label+" early actual pass")
            counts[color]["passes"] += 1
            if not previous_pass:
                scored = area(board)
                proposals.append(dict(ply=i+1, proposer=color, score_margin=scored["score_margin"],
                    instant_utilities=utilities(scored["winner"], cell["black_identity"], cell["white_identity"]),
                    next_action_available=i+1 < len(actions),
                    accepted=actions[i+1] == 25 if i+1 < len(actions) else None))
            if previous_pass:
                check(i == len(actions)-1, label+" double pass before end")
        else:
            counts[color]["placements"] += 1
            board, captured = apply_placement(board, action, color_code)
            counts[enemy]["captured_by_opponent"] += captured
            check((tuple(board), 3-color_code) not in history, label+" actual situational superko")
        history.add((tuple(board), 3-color_code))
        previous_pass = action == 25
    equal(board, rec["final_board"], "final_board from actual capture geometry")
    scored = area(rec["final_board"])
    for key, value in scored.items():
        equal(value, rec[key], key+" from independent area")
    ub, uw = utilities(scored["winner"], cell["black_identity"], cell["white_identity"])
    equal(ub, rec["black_utility"], "black identity utility")
    equal(uw, rec["white_utility"], "white identity utility")
    check(type(rec["black_utility"]) is int and type(rec["white_utility"]) is int, "identity utility integer types")
    termination = "double_pass" if actions[-2:] == [25, 25] else "move_limit" if len(actions) == 100 else "invalid"
    check(termination != "invalid", "valid terminal condition")
    equal(termination, rec["termination_reason"], "terminal condition including doublepass precedence")
    equal(superko, rec["superko_rejections"], "summed reported superko exclusions")
    check(isinstance(rec["game_wall_ms"], (int, float)) and not isinstance(rec["game_wall_ms"], bool)
          and math.isfinite(rec["game_wall_ms"]) and rec["game_wall_ms"] >= 0, "game timing")
    own = {"black": actions[::2], "white": actions[1::2]}
    row = {key: rec[key] for key in ("game_id", "black_identity", "white_identity", "black_algorithm",
        "white_algorithm", "game_wall_ms")}
    row.update({key: scored[key] for key in ("winner", "black_score", "white_score")})
    row.update(black_utility=ub, white_utility=uw, move_count=len(actions), termination_reason=termination,
        superko_rejections=superko, actions=actions, color_counts=counts, pass_proposals=proposals,
        extra_length=len(actions)-rule-2,
        first_pass_action=next((i+1 for i, action in enumerate(actions) if action == 25), None),
        routes=dict(empty_double_pass=actions == [25, 25],
            black_one_stone_double_pass=len(actions) == 3 and actions[0] < 25 and actions[1:] == [25, 25],
            all_pass_by_color={color: bool(seq) and all(a == 25 for a in seq) for color, seq in own.items()},
            one_stone_then_pass_by_color={color: bool(seq) and seq[0] < 25 and all(a == 25 for a in seq[1:])
                                         for color, seq in own.items()}),
        prefixes={str(size): dict(raw=actions[:size] if len(actions) >= size else None,
            END_padded=[actions[i] if i < len(actions) else -1 for i in range(size)]) for size in (4, 8, 12)},
        game_index=entry["index"], game_seed=entry["game_seed"],
        search_times_ms=[m["search_time_ms"] for m in rec["moves"]], game_bytes=byte_count, **cell)
    return row, errors


def summarize(rows):
    length = [row["move_count"] for row in rows]
    result = dict(n=len(rows), length=distribution(length),
        black_board_wins=sum(r["winner"] == "black" for r in rows),
        white_board_wins=sum(r["winner"] == "white" for r in rows),
        black_goals=sum(r["black_utility"] == 1 for r in rows),
        white_goals=sum(r["white_utility"] == 1 for r in rows),
        joint_goals=sum(r["black_utility"] == 1 and r["white_utility"] == 1 for r in rows),
        length2=length.count(2), length3=length.count(3), length10=length.count(10),
        length_le10=sum(x <= 10 for x in length), length_le8=sum(x <= 8 for x in length),
        length_ge60=sum(x >= 60 for x in length),
        extra_length=distribution([r["extra_length"] for r in rows]),
        first_pass_action=distribution([r["first_pass_action"] for r in rows if r["first_pass_action"] is not None]),
        first_legal_pass_delay=distribution([r["first_pass_action"]-r["pass_min_ply"]-1
                                           for r in rows if r["first_pass_action"] is not None]),
        color_counts={c: {key: sum(r["color_counts"][c][key] for r in rows)
                         for key in ("passes", "placements", "captured_by_opponent")} for c in ("black", "white")},
        empty_double_pass=sum(r["routes"]["empty_double_pass"] for r in rows),
        black_one_stone_double_pass=sum(r["routes"]["black_one_stone_double_pass"] for r in rows),
        literal_d0_one_stone_route=sum(r["actions"] == [0, 25, 25] for r in rows),
        black_realized_all_pass=sum(r["routes"]["all_pass_by_color"]["black"] for r in rows),
        termination=dict(Counter(r["termination_reason"] for r in rows)),
        superko_total=sum(r["superko_rejections"] for r in rows),
        game_wall_seconds=distribution([r["game_wall_ms"]/1000 for r in rows]),
        game_wall_seconds_sum=math.fsum(r["game_wall_ms"]/1000 for r in rows),
        search_ms=distribution([value for r in rows for value in r["search_times_ms"]]),
        output_game_bytes=sum(r["game_bytes"] for r in rows))
    acceptance = {}
    for color, offset in (("black", 0), ("white", 1)):
        for favorable in (True, False):
            opportunities = [e for r in rows for e in r["pass_proposals"]
                if e["proposer"] == color and (e["instant_utilities"][offset] == 1) == favorable
                and e["next_action_available"]]
            acceptance[f"{color}_proposer_favorable_{favorable}"] = dict(
                opportunities=len(opportunities), accepted=sum(e["accepted"] for e in opportunities))
    result["pass_proposal_acceptance"] = acceptance
    result["prefixes"] = {}
    for length in (4, 8, 12):
        result["prefixes"][str(length)] = {}
        for mode in ("raw", "END_padded"):
            seqs = [r["prefixes"][str(length)][mode] for r in rows
                    if r["prefixes"][str(length)][mode] is not None]
            frequency = Counter(tuple(seq) for seq in seqs)
            result["prefixes"][str(length)][mode] = dict(n=len(seqs), unique=len(frequency),
                top1_count=max(frequency.values(), default=0))
    return result


def assemble(rows):
    groups, representatives, supplemental = {}, {}, {}
    select = lambda rule, direction=None, seed=None: [r for r in rows if r["pass_min_ply"] == rule
        and (direction is None or r["black_identity"]+"/"+r["white_identity"] == direction)
        and (seed is None or r["batch_seed"] == seed)]
    for rule, name in RULES.items():
        groups[name] = dict(all=summarize(select(rule)),
            directions={d: summarize(select(rule, d)) for d in DIRECTIONS},
            seeds={str(seed): {d: summarize(select(rule, d, seed)) for d in DIRECTIONS} for seed in (8, 9, 10)})
        supplemental[name] = {}
        for direction in DIRECTIONS:
            ordered = sorted(select(rule, direction), key=lambda r: (r["move_count"], r["game_id"]))
            if ordered:
                representatives[f"{rule}:{direction}"] = [ordered[i]["game_id"]
                    for i in (0, (len(ordered)-1)//2, len(ordered)-1)]
        for seed in (None, 8, 9, 10):
            subsets = {d: select(rule, d, seed) for d in DIRECTIONS}
            means = {d: distribution([r["move_count"] for r in subset])["mean"] for d, subset in subsets.items()}
            s = dict(direction_n={d: len(subset) for d, subset in subsets.items()}, direction_mean=means)
            if all(value is not None for value in means.values()):
                mixed = (means["WIN/LOSE"] + means["LOSE/WIN"])/2
                same = (means["WIN/WIN"] + means["LOSE/LOSE"])/2
                s.update(mixed_mean=mixed, same_mean=same, mixed_minus_same=mixed-same,
                    mixed_minus_WW=mixed-means["WIN/WIN"], mixed_minus_LL=mixed-means["LOSE/LOSE"])
            supplemental[name]["pooled" if seed is None else str(seed)] = s
    pairs = []
    for block in sorted({r["block_id"] for r in rows}):
        matching = {r["pass_min_ply"]: r for r in rows if r["block_id"] == block}
        if set(matching) != {0, 8}:
            continue
        a, b = matching[0], matching[8]
        item = {key: a[key] for key in ("block_id", "batch_seed", "black_identity", "white_identity")}
        item.update(G0_game_id=a["game_id"], G1_game_id=b["game_id"],
            length_delta=b["move_count"]-a["move_count"],
            extra_length_delta=b["move_count"]-a["move_count"]-8,
            black_goal_delta=int(b["black_utility"] == 1)-int(a["black_utility"] == 1),
            white_goal_delta=int(b["white_utility"] == 1)-int(a["white_utility"] == 1),
            black_board_win_delta=int(b["winner"] == "black")-int(a["winner"] == "black"),
            joint_goal_delta=int(b["black_utility"] == b["white_utility"] == 1)-int(a["black_utility"] == a["white_utility"] == 1))
        pairs.append(item)
    deltas = {}
    for seed in (None, 8, 9, 10):
        deltas["pooled" if seed is None else str(seed)] = {}
        for direction in DIRECTIONS:
            subset = [r for r in pairs if r["black_identity"]+"/"+r["white_identity"] == direction
                      and (seed is None or r["batch_seed"] == seed)]
            deltas["pooled" if seed is None else str(seed)][direction] = {
                key: distribution([r[key] for r in subset]) for key in DELTA_KEYS}
    return dict(experiment_id=EXPERIMENT, pilot_descriptive_only=True, n_records=len(rows),
        groups=groups, rows=rows, paired_differences=pairs, paired_summaries=deltas,
        supplemental_equal_direction_means=supplemental, representatives=representatives,
        anomalous_game_ids=[r["game_id"] for r in rows if r["termination_reason"] != "double_pass"
            or r["black_identity"] != r["white_identity"] and r["black_utility"] != 1],
        interpretation="Extra length subtracts a mechanical rule-specific minimum, not a causal adjustment. No inferential intervals; no historical or future data pooled.")


def audit(root, out):
    root, out = Path(root).resolve(), Path(out).resolve()
    exp = root / "experiments/g1_pass8_v1"
    errors = []
    def equal(expected, actual, label):
        errors.extend(differences(expected, actual, label))
    protocol = read(exp/"preregistration.json")
    equal(PROTOCOL_SHA, digest(exp/"preregistration.json"), "frozen preregistration hash")
    equal(PROTOCOL_SHA, digest(out/"preregistration.json"), "saved preregistration hash")
    equal(PLAN_SHA, digest(exp/"frozen_plan.json"), "frozen plan hash")
    cells, plan = design(protocol)
    equal(48, len(plan), "registered game count")
    equal(plan, read(exp/"frozen_plan.json"), "independent schedule versus frozen plan")
    equal(plan, read(out/"plan.json"), "independent schedule versus saved plan")
    equal([dict(index=e["index"], game_seed=e["game_seed"]) for e in plan], read(out/"game_seeds.json"), "saved seeds")
    lock = read(exp/"pre_execution_source_lock.json")
    equal(lock, read(out/"source_lock.json"), "source lock mirror")
    inventory = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
                 for path in [root/"run.py", *sorted((root/"src/winai_loseai").rglob("*.py"))]}
    equal(lock["files"], inventory, "current normalized source files")
    fingerprint = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    equal(lock["source_fingerprint"], fingerprint, "independent source fingerprint")
    prelock = read(exp/"pre_execution_lock.json")
    experiment_lock = read(out/"experiment_lock.json")
    for key in ("experiment_id", *PROVENANCE_KEYS, "preregistration_sha256", "entry_point_sha256",
                "measurement_script_sha256", "scipy_version", "numpy_version"):
        equal(prelock[key], experiment_lock.get(key), "experiment lock "+key)
    for file, key in (("scripts/run_g1_pass8.py", "entry_point_sha256"),
                      ("scripts/measure_g1_pass8_chunk.py", "measurement_script_sha256")):
        equal(prelock[key], digest(root/file), file+" frozen hash")
    for file, sha in prelock["test_files_sha256"].items():
        equal(sha, digest(root/file), file+" frozen hash")
    provenance = {key: lock[key] for key in PROVENANCE_KEYS}
    manifest = read(out/"manifest.json")
    expected_manifest = dict(batch_id=BATCH, kind=EXPERIMENT, status="completed", requested_games=48,
        planned_game_count=48, completed_game_count=48, completed_indexes=list(range(48)),
        board_size=5, komi=2.5, batch_seed=[8, 9, 10], concurrency=1, pass_min_plies=[0, 8],
        budget=256, schedule_seed=2026100401, **provenance)
    agents = {}
    for entry in plan:
        for color in ("black", "white"):
            agents[entry[color]["agent_id"]] = entry[color]
    expected_manifest["agents"] = list(agents.values())
    for key, value in expected_manifest.items():
        equal(value, manifest.get(key), "manifest "+key)
    if (out/"rule_fault.json").exists():
        errors.append("persisted rule_fault.json")
    files = sorted((out/"games").glob("*.json"))
    equal([f"{BATCH}-g{i:06d}.json" for i in range(48)], [file.name for file in files], "raw game filenames/count")
    extras = [file.name for file in (out/"games").iterdir() if not file.is_file() or file.suffix != ".json"]
    equal([], extras, "unexpected game artifacts")
    rows, per_game, metadata = [], {}, []
    for file in files:
        rec = read(file)
        index = rec["game_index"]
        if type(index) is not int or not 0 <= index < 48:
            errors.append(file.name+": invalid game index")
            continue
        row, issues = reconstruct(rec, cells[index], plan[index], file.stat().st_size, provenance)
        rows.append(row)
        errors.extend(file.name+": "+issue for issue in issues)
        per_game[file.stem] = dict(passed=not issues, problems=issues, actions=row["move_count"],
            black_score=row["black_score"], white_score=row["white_score"],
            winner=row["winner"], color_counts=row["color_counts"], pass_proposals=len(row["pass_proposals"]))
        meta = {k: v for k, v in rec.items() if k not in ("black", "white", "moves")}
        meta.update(opening_actions=[m["action"] for m in rec["moves"][:12]], game_file="games/"+file.name)
        metadata.append(meta)
    actual_metadata = [json.loads(line) for line in (out/"games.jsonl").read_text().splitlines() if line.strip()]
    equal(metadata, actual_metadata, "full metadata mirror")
    equal(list(range(48)), [r["game_index"] for r in rows], "raw indexes in order")
    equal(24, len({r["block_id"] for r in rows}), "24 unique paired blocks")
    equal(24, len({e["game_seed"] for e in plan}), "24 unique initial game seeds")
    streams = {seed_from(("agent-stream", e["game_seed"], color, e[color]["seed"]))
               for e in plan for color in ("black", "white")}
    equal(48, len(streams), "48 unique initial color-agent streams")
    for i in range(0, 48, 2):
        a, b = plan[i:i+2]
        equal({k: v for k, v in a.items() if k not in ("index", "pass_min_ply")},
              {k: v for k, v in b.items() if k not in ("index", "pass_min_ply")}, f"paired seeds/agents {i//2}")
        equal([0, 8], sorted([a["pass_min_ply"], b["pass_min_ply"]]), f"paired arms {i//2}")
    equal({"0,8": 12, "8,0": 12}, dict(Counter(f"{plan[i]['pass_min_ply']},{plan[i+1]['pass_min_ply']}" for i in range(0, 48, 2))), "balanced arm orders")
    recomputed = assemble(rows)
    equal(recomputed, read(out/"analysis.json"), "analysis")
    equal(24, len(recomputed["paired_differences"]), "24 complete descriptive pairs")
    for rule in RULES.values():
        for direction in DIRECTIONS:
            equal(6, recomputed["groups"][rule]["directions"][direction]["n"], f"balanced {rule} {direction}")
            for seed in (8, 9, 10):
                equal(2, recomputed["groups"][rule]["seeds"][str(seed)][direction]["n"], f"balanced {rule} {direction} seed{seed}")
    locked_inputs = [exp/"preregistration.json", exp/"frozen_plan.json", exp/"pre_execution_source_lock.json",
                     exp/"pre_execution_lock.json", out/"analysis.json", out/"manifest.json", out/"games.jsonl",
                     out/"source_lock.json", out/"experiment_lock.json", out/"plan.json", out/"game_seeds.json", *files]
    report = dict(audit_id="G1-pass8-independent-final-audit-v1", experiment_id=EXPERIMENT,
        passed=not errors, complete=len(rows) == 48, n_records=len(rows), n_pairs=len(recomputed["paired_differences"]),
        n_actual_actions=sum(r["move_count"] for r in rows), n_pass_proposals=sum(len(r["pass_proposals"]) for r in rows),
        problems=errors, per_game=per_game, source_fingerprint=fingerprint,
        input_sha256={str(file.relative_to(root)): digest(file) for file in locked_inputs},
        coverage=["48 records / 24 adjacent paired blocks / 12 arm orders each / fixed rule-direction-seed balance",
            "independent union-find final area and per-proposal score / identity utility",
            "actual-path capture reconstruction, suicide and situational repetition checks",
            "recorded root pass window, key consistency, visits, chosen maximum and utility-vector Q symmetry",
            "full independent saved-analysis recomputation: rows, four directions, per seed, quantiles, routes, captures, prefixes, event denominators",
            "paired raw/extra length and goal/boardwinner deltas; equal-direction mixed/same summaries; representatives/anomalies",
            "source/protocol/entry/measurement/test frozen hashes and metadata mirrors"],
        limitations=["Not a second full rules/search engine; root nonpass legal-set completeness and superko exclusion counts are not independently enumerated.",
            "Reported search values, rollout and internal tree legality are not regenerated or proved.",
            "Game/search timings and file bytes are checked and aggregated, but child CPU/peakRSS measurement validity is a separate cost audit.",
            "Historical-source preservation, historical-stream disjointness and six deterministic regenerations are separately owned evidence.",
            "Pilot is descriptive only; no inference, causal coordination adjustment, sample expansion or behavioral GO decision."])
    return report, recomputed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--recomputed", type=Path)
    parser.add_argument("--data-ready", action="store_true", help="Owner has declared the complete pilot ready for final audit")
    args = parser.parse_args()
    if not args.data_ready:
        parser.error("final audit requires explicit --data-ready")
    for target in [args.report, *([args.recomputed] if args.recomputed else [])]:
        if target.resolve().is_relative_to(args.out.resolve()):
            parser.error("audit output must not modify pilot inputs")
        if target.exists():
            parser.error("audit output exists; use a new path")
    try:
        report, recomputed = audit(args.root, args.out)
    except Exception as exc:
        report = dict(audit_id="G1-pass8-independent-final-audit-v1", passed=False,
            problems=[f"Audit could not finish: {type(exc).__name__}: {exc}"], complete=False)
        recomputed = None
    report["audit_script_sha256"] = digest(__file__)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if args.recomputed and recomputed is not None:
        args.recomputed.parent.mkdir(parents=True, exist_ok=True)
        args.recomputed.write_text(json.dumps(recomputed, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in ("passed", "complete", "n_records", "n_pairs", "n_actual_actions", "n_pass_proposals", "problems")}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
