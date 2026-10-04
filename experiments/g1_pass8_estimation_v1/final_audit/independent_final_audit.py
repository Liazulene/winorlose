#!/usr/bin/env python3
"""Read-only M5 fixed480 G1-pass8 final audit. Standard library only; no engine imports.

Independent terminal/proposal area, actual-path capture/legality and full actual
root legal-set enumeration complement the separately reviewed arithmetic guard.
Internal rollout/tree legality and numerical search values are not regenerated.
Run only after the owner declares the fixed 480-game data ready.
Adapted from the independent M4 audit, not from production game/analysis code.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import sys

EXPERIMENT = "G1-pass8-estimation-v1"
BATCH = "g1_pass8_estimation_v1"
DIRECTIONS = ("WIN/WIN", "LOSE/LOSE", "WIN/LOSE", "LOSE/WIN")
RULES = {0: "G0", 8: "G1-pass8"}
DELTA_KEYS = ("length_delta", "extra_length_delta", "black_goal_delta",
              "white_goal_delta", "joint_goal_delta", "black_board_win_delta")
PROVENANCE_KEYS = ("code_version", "schema_version", "source_fingerprint", "python_version")
SEEDS = (11, 12, 13)
GAMES = 480
BLOCKS = 240
AUDIT_ID = "G1-pass8-estimation-independent-final-audit-v1"
EXPERIMENT_PATH = Path("experiments/g1_pass8_estimation_v1")
PROTOCOL_SHA = "cfe65b3f20b6e2cefdf620a27e501333c5798ea0801ee1b8881be2c010ff76fa"
VERIFIER_HASHES = {
    'recovery_verify_inference_v1.py': 'c1880daa7b65edf99473f7d02002a7b541919097c332b0830418d04dcadab331',
    'verify_inference_arithmetic.py': 'd2dd9c7b98712f348da5fcacc4c74761eff666749c8d97b50e2f67b171385932',
}
REVIEW_HASH_PATHS = {
    'independent_review_sha256': 'independent_review/resume20261004_launch_safety_summary.json',
    'independent_statistics_review_sha256': 'independent_review/recovery_statistics_review_v1.json',
    'historical_preservation_sha256': 'pre_execution_preservation.json',
    'G0_regression_sha256': 'G0_regression_3_recovery.json',
    'statistics_precision_final_sha256': 'statistics_method_precision_final.json',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return parse_json(Path(path).read_text(encoding="utf-8"))


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
    elif type(expected) is int:
        if type(actual) is not int or expected != actual:
            errors.append(f"{path}: {actual!r} != exact integer {expected!r}")
    elif isinstance(expected, float):
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
    """Independent placement/capture geometry; no production rules import."""
    if type(action) is not int or not 0 <= action < 25 or board[action]:
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
                for replicate in range(10):
                    block_index = (2 * index + orientation) * 10 + replicate
                    blocks.append(dict(budget=256, batch_seed=seed,
                        black_identity=direction[0], white_identity=direction[1],
                        black_seed=bs, white_seed=ws, replicate=replicate,
                        block_index=block_index, block_id=f"{seed}:{block_index}"))
    rng = random.Random(protocol["schedule_seed"])
    rng.shuffle(blocks)
    orders = [[0, 8], [8, 0]] * 120
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
    validate_record_shape(rec)
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
        legal, excluded = legal_actions(board, color_code, history, i, rule)
        equal(sorted(str(a) for a in legal), sorted(maps[0]), label+" independently enumerated legal root set")
        equal(excluded, move["superko_excluded"], label+" independently enumerated superko exclusions")
        check(action in legal, label+" independently legal selected action")
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
    scored = area(board)
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
            seeds={str(seed): {d: summarize(select(rule, d, seed)) for d in DIRECTIONS} for seed in SEEDS})
        supplemental[name] = {}
        for direction in DIRECTIONS:
            ordered = sorted(select(rule, direction), key=lambda r: (r["move_count"], r["game_id"]))
            if ordered:
                representatives[f"{rule}:{direction}"] = [ordered[i]["game_id"]
                    for i in (0, (len(ordered)-1)//2, len(ordered)-1)]
        for seed in (None, *SEEDS):
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
    for seed in (None, *SEEDS):
        deltas["pooled" if seed is None else str(seed)] = {}
        for direction in DIRECTIONS:
            subset = [r for r in pairs if r["black_identity"]+"/"+r["white_identity"] == direction
                      and (seed is None or r["batch_seed"] == seed)]
            deltas["pooled" if seed is None else str(seed)][direction] = {
                key: distribution([r[key] for r in subset]) for key in DELTA_KEYS}
    return dict(experiment_id=EXPERIMENT, estimation_only=True, n_records=len(rows),
        groups=groups, rows=rows, paired_differences=pairs, paired_summaries=deltas,
        supplemental_equal_direction_means=supplemental, representatives=representatives,
        anomalous_game_ids=[r["game_id"] for r in rows if r["termination_reason"] != "double_pass"
            or r["black_identity"] != r["white_identity"] and r["black_utility"] != 1],
        interpretation="Extra length subtracts a mechanical rule-specific minimum, not a causal adjustment. Complete-sample preregistered intervals only; no historical or pilot data pooled.")



def parse_json(text):
    """Reject duplicate keys, nonfinite constants, and trailing/torn JSON."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f'nonfinite JSON constant: {value}')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_record_shape(rec):
    """Fail closed before indexing malformed data; no coercion or imputation."""
    if not isinstance(rec, dict):
        raise ValueError('record must be an object')
    integer_fields = ('game_index', 'game_seed', 'board_size', 'pass_min_ply',
                      'move_count', 'superko_rejections', 'black_utility', 'white_utility',
                      'schema_version')
    required = set(integer_fields) | {'game_id', 'batch_id', 'black', 'white',
        'black_agent_id', 'white_agent_id', 'black_identity', 'white_identity',
        'black_algorithm', 'white_algorithm', 'black_compute_level', 'white_compute_level',
        'komi', 'ruleset', 'moves', 'final_board', 'winner', 'termination_reason',
        'black_score', 'white_score', 'score_margin', 'game_wall_ms', *PROVENANCE_KEYS}
    if not required <= rec.keys():
        raise ValueError('missing game fields: ' + ', '.join(sorted(required - rec.keys())))
    if any(type(rec[key]) is not int for key in integer_fields):
        raise ValueError('game integer fields must be nonboolean integers')
    if any(not finite(rec[key]) for key in ('komi', 'black_score', 'white_score', 'score_margin', 'game_wall_ms')):
        raise ValueError('game numeric fields must be finite nonboolean numbers')
    area(rec['final_board'])
    for color in ('black', 'white'):
        spec = rec[color]
        if (not isinstance(spec, dict) or set(spec) != {'agent_id', 'identity', 'algorithm', 'compute_level', 'seed'}
                or type(spec['seed']) is not int):
            raise ValueError('malformed agent specification')
    if not isinstance(rec['moves'], list) or not 2 <= len(rec['moves']) <= 100:
        raise ValueError('moves must be a bounded nonempty terminal sequence')
    move_ints = ('index', 'action', 'legal_action_count', 'superko_excluded',
                 'root_visit_count', 'simulations_used')
    required_move = {*move_ints, 'color', 'is_pass', 'search_time_ms',
                     'action_visit_counts', 'action_q_black', 'action_q_white'}
    keys = {str(a) for a in range(26)}
    for move in rec['moves']:
        if not isinstance(move, dict) or not required_move <= move.keys():
            raise ValueError('missing/malformed move fields')
        if any(type(move[k]) is not int for k in move_ints) or not 0 <= move['action'] <= 25:
            raise ValueError('invalid move integer fields/action')
        if type(move['is_pass']) is not bool or not finite(move['search_time_ms']):
            raise ValueError('invalid move boolean/timing')
        for key in ('action_visit_counts', 'action_q_black', 'action_q_white'):
            mapping = move[key]
            if not isinstance(mapping, dict) or not mapping or not set(mapping) <= keys:
                raise ValueError('search maps require canonical action string keys')
        if any(type(v) is not int or v < 0 for v in move['action_visit_counts'].values()):
            raise ValueError('visit counts must be nonnegative nonboolean integers')


def legal_actions(board, color, history, ply, pass_min_ply):
    """Independent full actual-root candidate enumeration, including superko.

    The terminal status is checked by reconstruct before reaching subsequent
    actions. This helper operates only on a nonterminal state.
    """
    legal, superko = [], 0
    for action in range(25):
        if board[action]:
            continue
        try:
            candidate, _ = apply_placement(board, action, color)
        except ValueError:  # Suicide, after opponent removal.
            continue
        if (tuple(candidate), 3-color) in history:
            superko += 1
        else:
            legal.append(action)
    if ply >= pass_min_ply:
        legal.append(25)
    if not legal:
        raise ValueError('nonterminal no-legal-action state; forbidden to impute an outcome')
    return legal, superko


def validate_protocol(protocol):
    exact = {'experiment_id': EXPERIMENT, 'batch_id': BATCH,
        'code_version': 'winai_loseai-0.7.0-g1-pass8-estimation', 'schema_version': 2,
        'board_size': 5, 'komi': 2.5, 'budget': 256, 'pass_min_plies': [0, 8],
        'batch_seeds': list(SEEDS), 'identity_directions': [d.split('/') for d in DIRECTIONS],
        'agent_seed_orientations': [[1, 2], [2, 1]], 'games_per_cell': 10,
        'planned_games': GAMES, 'schedule_seed': 2026100402,
        'registered_before_first_formal_game': True}
    errors = []
    for key, value in exact.items():
        errors.extend(differences(value, protocol.get(key), 'protocol.' + key))
    for key in ('board_size', 'schema_version', 'budget', 'games_per_cell', 'planned_games', 'schedule_seed'):
        if type(protocol.get(key)) is not int:
            errors.append('protocol.' + key + ': requires integer')
    if protocol.get('resource_policy', {}).get('concurrency') != 1:
        errors.append('protocol formal concurrency must be 1')
    if protocol.get('statistics', {}).get('analysis_version') != 'g1-pass8-fixed-paired-cp-hoeffding-v1':
        errors.append('protocol statistical version mismatch')
    if errors:
        raise ValueError('; '.join(errors))


def safe_relative(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('lock path must be relative')
    path = root / relative
    if '..' in Path(relative).parts or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('lock path escapes experiment root')
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlinked evidence is forbidden')
    return path


def inference_verifier(root):
    """Load only the separately reviewed stdlib arithmetic guard, never src/."""
    import importlib.util
    directory = root / EXPERIMENT_PATH / 'independent_review'
    path = directory / 'recovery_verify_inference_v1.py'
    for name, sha in VERIFIER_HASHES.items():
        if digest(directory/name) != sha:
            raise ValueError('independent arithmetic verifier hash changed: '+name)
    # This is the reviewed sibling module path, rather than a caller-supplied import.
    sys.path.insert(0, str(directory))
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    old_arithmetic = sys.modules.get('verify_inference_arithmetic')
    try:
        arithmetic_spec = importlib.util.spec_from_file_location('verify_inference_arithmetic', directory/'verify_inference_arithmetic.py')
        arithmetic_module = importlib.util.module_from_spec(arithmetic_spec)
        arithmetic_spec.loader.exec_module(arithmetic_module)
        sys.modules['verify_inference_arithmetic'] = arithmetic_module
        spec = importlib.util.spec_from_file_location('m5_independent_guard', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old_bytecode
        if old_arithmetic is None:
            sys.modules.pop('verify_inference_arithmetic', None)
        else:
            sys.modules['verify_inference_arithmetic'] = old_arithmetic
        sys.path.pop(0)
    return module, [path, directory/'verify_inference_arithmetic.py']


def _audit(root, out):
    root, out = Path(root).resolve(), Path(out).resolve()
    exp = root / EXPERIMENT_PATH
    errors, input_files, snapshots = [], set(), {}
    def equal(expected, actual, label):
        errors.extend(differences(expected, actual, label))
    def rd(path):
        path = Path(path)
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('symlinked evidence is forbidden: ' + str(path))
        raw = path.read_bytes()
        snapshots[path] = hashlib.sha256(raw).hexdigest()
        value = parse_json(raw.decode('utf-8'))
        input_files.add(path)
        return value
    def hash_file(path):
        input_files.add(Path(path))
        sha = digest(path)
        if Path(path) in snapshots and snapshots[Path(path)] != sha:
            errors.append('input changed during audit: '+str(path))
        snapshots[Path(path)] = sha
        return sha
    protocol = rd(exp/'preregistration.json')
    validate_protocol(protocol)
    equal(PROTOCOL_SHA, hash_file(exp/'preregistration.json'), 'independently pinned M5 preregistration')
    cells, plan = design(protocol)
    equal(GAMES, len(plan), 'registered game count')
    equal(plan, rd(exp/'frozen_plan.json'), 'independent frozen schedule')
    equal(plan, rd(out/'plan.json'), 'saved schedule')
    equal([dict(index=e['index'], game_seed=e['game_seed']) for e in plan], rd(out/'game_seeds.json'), 'saved seed mirror')
    lock = rd(exp/'pre_execution_source_lock.json')
    prelock = rd(exp/'pre_execution_lock.json')
    equal(lock, rd(out/'source_lock.json'), 'source lock mirror')
    for key in PROVENANCE_KEYS:
        equal(lock[key], prelock.get(key), 'prelock provenance ' + key)
    equal(protocol['code_version'], lock['code_version'], 'source code version')
    equal(protocol['schema_version'], lock['schema_version'], 'source schema version')
    equal('sha256-utf8-lf-path-map-v1', lock.get('algorithm'), 'source hash algorithm')
    inventory = {}
    for path in [root/'run.py', *sorted((root/'src/winai_loseai').rglob('*.py'))]:
        safe_relative(root, path.relative_to(root).as_posix())
        input_files.add(path)
        raw = path.read_bytes()
        snapshots[path] = hashlib.sha256(raw).hexdigest()
        normalized = raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        inventory[path.relative_to(root).as_posix()] = hashlib.sha256(normalized.encode()).hexdigest()
    equal(lock['files'], inventory, 'current normalized source inventory')
    fingerprint = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    equal(lock['source_fingerprint'], fingerprint, 'independent source fingerprint')
    equal(prelock['preregistration_sha256'], hash_file(exp/'preregistration.json'), 'frozen preregistration SHA256')
    equal(prelock['preregistration_sha256'], hash_file(out/'preregistration.json'), 'saved preregistration SHA256')
    experiment_lock = rd(out/'experiment_lock.json')
    expected_lock = {key: prelock[key] for key in ('experiment_id', *PROVENANCE_KEYS,
        'preregistration_sha256', 'entry_point_sha256', 'measurement_script_sha256', 'scipy_version', 'numpy_version')}
    equal(expected_lock, experiment_lock, 'experiment lock')
    for file, key in (('scripts/run_g1_pass8_estimation.py', 'entry_point_sha256'),
                      ('scripts/measure_g1_pass8_estimation_chunk.py', 'measurement_script_sha256')):
        equal(prelock[key], hash_file(root/file), file+' frozen hash')
    test_hashes = prelock.get('test_files_sha256')
    if not isinstance(test_hashes, dict) or not test_hashes:
        errors.append('pre-execution test hash inventory missing/empty')
    else:
        equal(sorted(p.relative_to(root).as_posix() for p in (root/'tests').rglob('*.py')),
              sorted(test_hashes), 'complete frozen test source inventory')
        for relative, sha in test_hashes.items():
            equal(sha, hash_file(safe_relative(root, relative)), relative+' frozen hash')
    # Additional independently frozen input inventories are verified when present.
    for inventory_key in ('input_files_sha256', 'independent_review_files_sha256', 'audit_files_sha256'):
        for relative, sha in prelock.get(inventory_key, {}).items():
            equal(sha, hash_file(safe_relative(root, relative)), inventory_key+': '+relative)
    equal(prelock['frozen_plan_sha256'], hash_file(exp/'frozen_plan.json'), 'frozen plan SHA256')
    for key, relative in REVIEW_HASH_PATHS.items():
        equal(prelock[key], hash_file(exp/relative), key+' frozen review evidence')
    equal(prelock['full_suite']['log_sha256'], hash_file(exp/'full_tests_final_prelaunch.txt'), 'frozen full-suite log')
    equal(0, prelock.get('formal_games_before_freeze'), 'formal games before freeze')
    equal(False, prelock.get('scientific_plan_change'), 'scientific plan unchanged')
    equal(3, prelock.get('G0_regression_games'), 'frozen G0 regression count')
    provenance = {key: lock[key] for key in PROVENANCE_KEYS}
    manifest = rd(out/'manifest.json')
    expected_manifest = dict(batch_id=BATCH, kind=EXPERIMENT, status='completed', requested_games=GAMES,
        planned_game_count=GAMES, completed_game_count=GAMES, completed_indexes=list(range(GAMES)),
        board_size=5, komi=2.5, batch_seed=list(SEEDS), concurrency=1, pass_min_plies=[0, 8],
        budget=256, schedule_seed=2026100402, **provenance)
    agents = {e[c]['agent_id']: e[c] for e in plan for c in ('black', 'white')}
    expected_manifest['agents'] = list(agents.values())
    for key, value in expected_manifest.items():
        equal(value, manifest.get(key), 'manifest.'+key)
    for key in ('requested_games', 'planned_game_count', 'completed_game_count', 'concurrency'):
        if type(manifest.get(key)) is not int:
            errors.append('manifest.'+key+': must be an integer')
    if (out/'rule_fault.json').exists():
        errors.append('persisted rule_fault.json, no completed experiment is admissible')
    files = sorted((out/'games').glob('*.json'))
    equal([f'{BATCH}-g{i:06d}.json' for i in range(GAMES)], [p.name for p in files], 'raw filenames/count')
    extras = [p.name for p in (out/'games').iterdir() if not p.is_file() or p.suffix != '.json']
    equal([], extras, 'unexpected game artifacts, including unfinished tmp files')
    rows, per_game, metadata = [], {}, []
    for index, entry in enumerate(plan):
        file = out/'games'/f'{BATCH}-g{index:06d}.json'
        if not file.is_file():
            continue
        try:
            rec = rd(file)
            row, issues = reconstruct(rec, cells[index], entry, file.stat().st_size, provenance)
            rows.append(row)
            metadata.append({k: v for k, v in rec.items() if k not in ('black', 'white', 'moves')} |
                dict(opening_actions=[m['action'] for m in rec['moves'][:12]], game_file='games/'+file.name))
            per_game[file.stem] = dict(passed=not issues, problems=issues, actions=row['move_count'],
                black_score=row['black_score'], white_score=row['white_score'], winner=row['winner'],
                color_counts=row['color_counts'], pass_proposals=len(row['pass_proposals']))
            errors.extend(file.name+': '+issue for issue in issues)
        except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
            issue = f'malformed/illegal record: {type(exc).__name__}: {exc}'
            errors.append(file.name+': '+issue)
            per_game[file.stem] = dict(passed=False, problems=[issue])
    jsonl = out/'games.jsonl'
    input_files.add(jsonl)
    jsonl_bytes = jsonl.read_bytes()
    snapshots[jsonl] = hashlib.sha256(jsonl_bytes).hexdigest()
    lines = jsonl_bytes.decode('utf-8').splitlines()
    if any(not line.strip() for line in lines):
        errors.append('blank JSONL records forbidden')
    actual_metadata = [parse_json(line) for line in lines]
    equal(metadata, actual_metadata, 'full ordered JSONL metadata mirror')
    equal(list(range(GAMES)), [r['game_index'] for r in rows], 'canonical raw indexes')
    equal(BLOCKS, len({r['block_id'] for r in rows}), '240 unique paired blocks')
    equal(BLOCKS, len({e['game_seed'] for e in plan}), '240 distinct initial game seeds')
    streams = {seed_from(('agent-stream', e['game_seed'], color, e[color]['seed']))
               for e in plan for color in ('black', 'white')}
    equal(GAMES, len(streams), '480 distinct initial color-agent streams')
    for i in range(0, GAMES, 2):
        a, b = plan[i:i+2]
        equal({k: v for k, v in a.items() if k not in ('index', 'pass_min_ply')},
              {k: v for k, v in b.items() if k not in ('index', 'pass_min_ply')}, f'paired seeds/agents {i//2}')
        equal([0, 8], sorted([a['pass_min_ply'], b['pass_min_ply']]), f'paired arms {i//2}')
    equal({'0,8': 120, '8,0': 120}, dict(Counter(f"{plan[i]['pass_min_ply']},{plan[i+1]['pass_min_ply']}"
              for i in range(0, GAMES, 2))), 'balanced arm orders')
    counts = Counter((r['pass_min_ply'], r['batch_seed'], r['black_identity'], r['white_identity'],
                      r['black_seed'], r['white_seed']) for r in rows)
    expected_counts = {(rule, seed, *direction.split('/'), *orientation): 10
        for rule in RULES for seed in SEEDS for direction in DIRECTIONS for orientation in ((1,2), (2,1))}
    equal(expected_counts, counts, '48 fixed cells of exactly 10 games')
    raw_hashes = {p.name: hash_file(p) for p in files}
    saved_validation = rd(out/'validation.json')
    expected_validation = dict(experiment_id=EXPERIMENT, planned=GAMES, game_count=GAMES,
        replay_and_search_ok=GAMES, complete=True, problems=[], manifest_status='completed',
        rule_fault_present=False, source_fingerprint=fingerprint, raw_game_sha256=raw_hashes)
    equal(expected_validation, saved_validation, 'completed saved validation snapshot')
    saved_analysis = rd(out/'analysis.json')
    recomputed = None
    inference_report = dict(passed=False, arithmetic_executed=False,
        problems=['Inference suppressed until all fixed480 raw/design/source/manifest checks pass'])
    if not errors:
        recomputed = assemble(rows)
        expected_descriptive = {k: v for k, v in saved_analysis.items() if k != 'inference'}
        equal(recomputed, expected_descriptive, 'independent descriptive analysis')
        # Do not compute intervals from partial, corrupt, or noncanonical data.
        if not errors:
            verifier, verifier_files = inference_verifier(root)
            for path in verifier_files:
                hash_file(path)
            inference_report, expected_inference = verifier.verify(rows, saved_analysis.get('inference'))
            if not inference_report['passed']:
                errors.extend('inference: '+str(p) for p in inference_report['problems'])
            recomputed['inference'] = expected_inference
    for path, original in snapshots.items():
        if digest(path) != original:
            errors.append('input changed during audit: '+str(path))
    report = dict(audit_id=AUDIT_ID, experiment_id=EXPERIMENT, passed=not errors,
        complete=len(rows)==GAMES and set(counts)==set(expected_counts) and counts==expected_counts,
        n_records=len(rows), n_pairs=sum(Counter(r['pass_min_ply'] for r in rows if r['block_id']==b)=={0:1,8:1} for b in {r['block_id'] for r in rows}),
        n_actual_actions=sum(r['move_count'] for r in rows),
        n_pass_proposals=sum(len(r['pass_proposals']) for r in rows), problems=errors,
        per_game=per_game, source_fingerprint=fingerprint, statistical_audit=inference_report,
        input_sha256={str(p.relative_to(root)) if p.is_relative_to(root) else str(p): digest(p)
                      for p in sorted(input_files)},
        recomputed_inference_scope='The recomputed artifact contains independently reconstructed pooled/per_seed numerical groups; explanatory saved metadata is not copied.',
        coverage=[
            '480 canonical games, 240 adjacent paired blocks, 120 arm orders each; full six-stratum fixed design',
            'Independent union-find terminal/proposal area scoring and identity utilities',
            'Actual-path capture, suicide, situational superko, all actual-root legal candidates, pass window and terminal precedence',
            'Root search key sets, visit totals/maximum choice, finite Q/utility symmetry; superko exclusion counts',
            'Independent rows, descriptive aggregates, paired deltas, event denominators, quantiles, captures, raw/END prefixes and representatives',
            'Strict duplicate-key/nonfinite-free JSON/JSONL; complete manifest/validation and all saved source stamps',
            'Frozen source/protocol/entry/measurement/test/input hashes; independent guarded inference comparison'],
        limitations=[
            'Not a proof of internal tree or rollout legality, UCT implementation, RNG execution, or numerical search Q correctness.',
            'Observed search/game timings and byte counts checked and aggregated; child CPU/peakRSS and historical preservation are separately audited.',
            'Historical seed noncollision and six deterministic regenerations remain separately required evidence.',
            'Source locks establish byte consistency, not independent external timestamp attestation or malicious multi-file tamper resistance.',
            'Statistical coverage requires the preregistered hypothetical independent-stream model; fixed deterministic seeds themselves have no sampling uncertainty.',
            'No optional stopping, rare-failure certificate, equivalence conclusion, pure coordination causal effect, or 7x7 GO claim.'])
    return report, recomputed


def audit(root, out):
    """Never repair input or continue inference after malformed/missing evidence."""
    try:
        return _audit(root, out)
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError, AttributeError) as exc:
        return dict(audit_id=AUDIT_ID, experiment_id=EXPERIMENT, passed=False, complete=False,
            problems=[f'Audit could not finish: {type(exc).__name__}: {exc}'],
            statistical_audit={'passed': False, 'arithmetic_executed': False}), None


def check_output_targets(root, out, targets):
    allowed = Path(root).resolve()/EXPERIMENT_PATH/'final_audit'
    resolved = []
    for target in targets:
        target = Path(target).absolute()
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('symlinked audit output forbidden')
        dest = target.resolve()
        if set(dest.parts) & {'winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1','winorlose_g1_pass8_v1'}:
            raise ValueError('historical worktrees are forbidden audit output targets')
        if not dest.is_relative_to(allowed) or dest == allowed:
            raise ValueError('audit output must be a new path under this M5 final_audit directory')
        if dest.is_relative_to(Path(out).resolve()) or target.exists():
            raise ValueError('audit output must not exist or modify input data')
        if dest in resolved:
            raise ValueError('audit output paths must be distinct')
        resolved.append(dest)
    return resolved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--recomputed', type=Path)
    parser.add_argument('--data-ready', action='store_true', help='Owner declares full 480-game formal sample ready')
    args = parser.parse_args(argv)
    if not args.data_ready:
        parser.error('final audit requires explicit --data-ready; never audit partial formal data')
    try:
        targets = check_output_targets(args.root, args.out, [args.report]+([args.recomputed] if args.recomputed else []))
    except ValueError as exc:
        parser.error(str(exc))
    report, recomputed = audit(args.root, args.out)
    report['audit_script_sha256'] = digest(__file__)
    report['execution_role'] = 'read-only completed-sample final verification'
    for target, document in zip(targets, [report, recomputed]):
        if document is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation also prevents accidental overwrite after the precheck.
            with target.open('x', encoding='utf-8') as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write('\n')
    print(json.dumps({k: report.get(k) for k in ('passed', 'complete', 'n_records', 'n_pairs', 'problems')}, indent=2))
    return int(not report['passed'])


if __name__ == '__main__':
    sys.exit(main())
