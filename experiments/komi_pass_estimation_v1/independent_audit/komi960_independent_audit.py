#!/usr/bin/env python3
"""M7 fixed960 independent audit, replay uses standard library; optional Student-t quantile uses SciPy only.

Core replay/geometry was copied and adapted from the read-only M5 independent
final audit. This file never imports production engines, production analysis,
or inherited audit modules. It does not regenerate MCTS internals.
"""
import argparse
from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import sys

EXPERIMENT = "komi-pass-estimation-v1"
BATCH = "komi_pass_estimation_v1"
DIRECTIONS = ("WIN/WIN", "LOSE/LOSE", "WIN/LOSE", "LOSE/WIN")
ARMS = ((0, 2.5), (8, 2.5), (0, 0.0), (8, 0.0))
RULES = {(0, 2.5): "G0", (8, 2.5): "G1-pass8", (0, 0.0): "G1-k0", (8, 0.0): "G1-k0-pass8"}
PROVENANCE_KEYS = ("code_version", "schema_version", "source_fingerprint", "python_version")
SEEDS = (17, 18, 19)
GAMES = 960
BLOCKS = 240
AUDIT_ID = "komi-pass-estimation-independent-audit-v1"
EXPERIMENT_PATH = Path("experiments/komi_pass_estimation_v1")

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

def area(board, komi):
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
    scores = [float(board.count(1)), float(board.count(2)) + komi]
    for size, border in regions.values():
        if len(border) == 1:
            scores[next(iter(border))-1] += size
    margin = scores[0] - scores[1]
    return dict(black_score=scores[0], white_score=scores[1], score_margin=margin,
                winner="black" if margin > 0 else "white" if margin < 0 else "draw")


def utilities(winner, ib, iw):
    if winner not in ("black", "white", "draw"):
        raise ValueError("invalid board winner")
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
        komi=entry["komi"], pass_min_ply=entry["pass_min_ply"], ruleset=RULES[(entry["pass_min_ply"], entry["komi"]) ],
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
                scored = area(board, entry["komi"])
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
    scored = area(board, entry["komi"])
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
        draws=sum(r["winner"] == "draw" for r in rows),
        utility_counts={color: {str(u):sum(r[color+"_utility"] == u for r in rows) for u in (-1,0,1)} for color in ("black","white")},
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
        for utility,label in ((1,"favorable"),(0,"neutral"),(-1,"unfavorable")):
            opportunities = [e for r in rows for e in r["pass_proposals"]
                if e["proposer"] == color and e["instant_utilities"][offset] == utility
                and e["next_action_available"]]
            acceptance[f"{color}_proposer_{label}"] = dict(
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
    area(rec['final_board'], rec['komi'])
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


def safe_relative(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('lock path must be relative')
    path = root / relative
    if '..' in Path(relative).parts or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('lock path escapes experiment root')
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlinked evidence is forbidden')
    return path



def validate_protocol(protocol):
    """Check the fixed formal design, independently of the production generator."""
    exact = dict(experiment_id=EXPERIMENT, batch_id=BATCH,
        code_version='winai_loseai-0.9.0-komi-pass-estimation', schema_version=2,
        board_size=5, budget=256, pass_min_plies=[0,8], komis=[2.5,0.0],
        batch_seeds=list(SEEDS), identity_directions=[d.split('/') for d in DIRECTIONS],
        agent_seed_orientations=[[1,2],[2,1]], games_per_cell=10, planned_games=GAMES,
        schedule_seed=2026100501, registered_before_first_game=True)
    errors=[]
    for key,value in exact.items():errors.extend(differences(value,protocol.get(key),'protocol.'+key))
    errors.extend(differences(1,protocol.get('resource_policy',{}).get('concurrency'),'protocol.concurrency'))
    errors.extend(differences({name:dict(pass_min_ply=p,komi=k) for (p,k),name in RULES.items()},
        protocol.get('rule_semantics',{}).get('arms'),'protocol.arms'))
    if errors:raise ValueError('; '.join(errors))


def design(protocol):
    """Independent schedule: 240 quartets, ten copies of every arm permutation."""
    validate_protocol(protocol)
    blocks=[]
    for seed in SEEDS:
        for identity_index,direction in enumerate(DIRECTIONS):
            ib,iw=direction.split('/')
            for orientation,(bs,ws) in enumerate(((1,2),(2,1))):
                for replicate in range(10):
                    index=(2*identity_index+orientation)*10+replicate
                    blocks.append(dict(budget=256,batch_seed=seed,black_identity=ib,white_identity=iw,
                        black_seed=bs,white_seed=ws,replicate=replicate,identity_index=identity_index,
                        orientation_index=orientation,block_index=index,block_id=f'{seed}:{index}'))
    rng=random.Random(2026100501);rng.shuffle(blocks)
    orders=list(itertools.permutations(ARMS))*10;rng.shuffle(orders)
    cells=[];plan=[]
    for block,order in zip(blocks,orders):
        for p,k in order:
            cell=dict(block,pass_min_ply=p,komi=k,ruleset=RULES[(p,k)])
            entry=dict(index=len(plan),game_seed=seed_from(('game-seed',block['batch_seed'],block['block_index'])),pass_min_ply=p,komi=k)
            for color in ('black','white'):
                ident=block[color+'_identity']; seed=block[color+'_seed']
                entry[color]=dict(agent_id=f'{ident}-medium-s{seed}',identity=ident,algorithm='vector_mcts',compute_level='medium',seed=seed)
            cells.append(cell);plan.append(entry)
    return cells,plan


METRICS=('length','extra_length','black_goal','white_goal','joint_goal','draw','black_board_win')
CONTRASTS=('komi_at_p0','komi_at_p8','pass_at_k2p5','pass_at_k0','interaction')
# Contrast weights reference ARMS in the fixed order G0, G1-pass8, G1-k0, G1-k0-pass8.
CONTRAST_WEIGHTS={
    'komi_at_p0':(-1,0,1,0), 'komi_at_p8':(0,-1,0,1),
    'pass_at_k2p5':(-1,1,0,0), 'pass_at_k0':(0,0,-1,1),
    'interaction':(1,-1,-1,1)}


def endpoint(row,metric):
    if metric=='length':return row['move_count']
    if metric=='extra_length':return row['move_count']-row['pass_min_ply']-2
    if metric=='black_goal':return int(row['black_utility']==1)
    if metric=='white_goal':return int(row['white_utility']==1)
    if metric=='joint_goal':return int(row['black_utility']==row['white_utility']==1)
    if metric=='draw':return int(row['winner']=='draw')
    if metric=='black_board_win':return int(row['winner']=='black')
    raise ValueError('unknown endpoint')


def assemble(rows):
    """Independently reconstruct full descriptive output; inference added separately."""
    groups={};representatives={};supplemental={}
    def select(arm,direction=None,seed=None):
        return [r for r in rows if (r['pass_min_ply'],r['komi'])==arm
            and (direction is None or r['black_identity']+'/'+r['white_identity']==direction)
            and (seed is None or r['batch_seed']==seed)]
    for arm,name in RULES.items():
        groups[name]=dict(all=summarize(select(arm)),
            directions={d:summarize(select(arm,d)) for d in DIRECTIONS},
            seeds={str(seed):{d:summarize(select(arm,d,seed)) for d in DIRECTIONS} for seed in SEEDS})
        supplemental[name]={}
        for direction in DIRECTIONS:
            ordered=sorted(select(arm,direction),key=lambda r:(r['move_count'],r['game_id']))
            if ordered:representatives[name+':'+direction]=[ordered[i]['game_id'] for i in (0,(len(ordered)-1)//2,len(ordered)-1)]
        for seed in (None,*SEEDS):
            subsets={d:select(arm,d,seed) for d in DIRECTIONS}
            means={d:distribution([r['move_count'] for r in subset])['mean'] for d,subset in subsets.items()}
            result=dict(direction_n={d:len(subset) for d,subset in subsets.items()},direction_mean=means)
            if all(value is not None for value in means.values()):
                mixed=(means['WIN/LOSE']+means['LOSE/WIN'])/2
                same=(means['WIN/WIN']+means['LOSE/LOSE'])/2
                result.update(mixed_mean=mixed,same_mean=same,mixed_minus_same=mixed-same,
                    mixed_minus_WW=mixed-means['WIN/WIN'],mixed_minus_LL=mixed-means['LOSE/LOSE'])
            supplemental[name]['pooled' if seed is None else str(seed)]=result
    pairs=[]
    for block_id in sorted({r['block_id'] for r in rows}):
        subset=[r for r in rows if r['block_id']==block_id]
        by_arm={(r['pass_min_ply'],r['komi']):r for r in subset}
        if len(subset)!=4 or set(by_arm)!=set(ARMS):
            raise ValueError('incomplete or duplicate four-arm block: '+block_id)
        ordered=[by_arm[arm] for arm in ARMS]
        first=ordered[0]
        invariant=('batch_seed','black_identity','white_identity','black_seed','white_seed','game_seed')
        if any(any(r[key]!=first[key] for key in invariant) for r in ordered):
            raise ValueError('four-arm block agent/seed mismatch: '+block_id)
        pairs.append({key:first[key] for key in ('block_id','batch_seed','identity_index','orientation_index','replicate','block_index','black_identity','white_identity')} |
            dict(game_ids={RULES[arm]:by_arm[arm]['game_id'] for arm in ARMS},
                contrasts={contrast:{metric:sum(w*endpoint(r,metric) for w,r in zip(weights,ordered))
                    for metric in METRICS} for contrast,weights in CONTRAST_WEIGHTS.items()}))
    deltas={}
    for seed in (None,*SEEDS):
        deltas['pooled' if seed is None else str(seed)]={}
        for direction in DIRECTIONS:
            subset=[pair for pair in pairs if pair['black_identity']+'/'+pair['white_identity']==direction
                    and (seed is None or pair['batch_seed']==seed)]
            deltas['pooled' if seed is None else str(seed)][direction]={contrast:{metric:
                distribution([r['contrasts'][contrast][metric] for r in subset]) for metric in METRICS} for contrast in CONTRASTS}
    return dict(experiment_id=EXPERIMENT,formal_estimation=True,n_records=len(rows),
        groups=groups,rows=rows,paired_differences=pairs,paired_summaries=deltas,
        supplemental_equal_direction_means=supplemental,representatives=representatives,
        anomalous_game_ids=[r['game_id'] for r in rows if r['termination_reason']!='double_pass'
            or r['black_identity']!=r['white_identity'] and r['black_utility']!=1],
        interpretation='Komi contrasts are 0 minus 2.5; pass contrasts are 8 minus 0; interaction is the komi contrast at pass8 minus pass0. A draw has utility 0 and never counts as identity-goal success. Extra length is a mechanical reference, not causal adjustment. Intervals are in inference; descriptive event counts are not independent game trials. No historical/future pooling.')

# Independent numerical inference: finite binomial sums and bisection, no beta
# quantile or production analysis calls. Student-t uses SciPy only for ppf.
from functools import lru_cache

@lru_cache(maxsize=None)
def independent_cp(k,n,confidence=.95):
    if type(k) is not int or type(n) is not int or not 0<=k<=n or n<1 or not .5<=confidence<1:
        raise ValueError('invalid CP count/confidence')
    tail=(1-confidence)/2
    def lower_root(successes):
        low,high=0.0,1.0
        for _ in range(64):
            mid=(low+high)/2
            prob=math.fsum(math.comb(n,j)*mid**j*(1-mid)**(n-j) for j in range(successes,n+1))
            if prob<tail:low=mid
            else:high=mid
        return (low+high)/2
    return [0.0 if k==0 else lower_root(k),1.0 if k==n else 1-lower_root(n-k)]

def independent_rate(values,confidence=.95):
    n=len(values);k=sum(values)
    return dict(successes=k,n=n,estimate=k/n,confidence_level=confidence,ci=independent_cp(k,n,confidence))

def independent_pair(a,b,confidence=.95):
    n=len(a); counts=Counter(zip(a,b));plus=counts[0,1];minus=counts[1,0]
    component=1-(1-confidence)/2
    lp,up=independent_cp(plus,n,component);lm,um=independent_cp(minus,n,component)
    estimate=(plus-minus)/n;ci=[lp-um,up-lm]
    radius=math.sqrt(2*math.log(2/(1-confidence))/n)
    result=dict(n=n,baseline_successes=sum(a),comparison_successes=sum(b),n00=counts[0,0],n01=plus,n10=minus,n11=counts[1,1],discordant_pairs=plus+minus,estimate=estimate,confidence_level=confidence,ci=ci,component_confidence_level=component,positive_probability_ci=[lp,up],negative_probability_ci=[lm,um],hoeffding_radius=radius,hoeffding_ci=[max(-1.0,estimate-radius),min(1.0,estimate+radius)])
    if confidence==.95:result.update(ci95=ci,ci95_hoeffding=result['hoeffding_ci'])
    return result

def independent_bounded(values,confidence=.95):
    n=len(values);mean=math.fsum(values)/n;radius=4*math.sqrt(math.log(2/(1-confidence))/(2*n))
    return dict(n=n,estimate=mean,confidence_level=confidence,ci=[max(-2,mean-radius),min(2,mean+radius)],support=[-2,2],unclipped_radius=radius,value_counts={str(x):values.count(x) for x in range(-2,3)})

def inference_endpoints(r):
    a=r['actions'];n=len(a)
    return dict(black_board_wins=int(r['winner']=='black'),white_board_wins=int(r['winner']=='white'),draws=int(r['winner']=='draw'),black_goals=int(r['black_utility']==1),white_goals=int(r['white_utility']==1),joint_goals=int(r['black_utility']==r['white_utility']==1),length2=int(n==2),length3=int(n==3),length10=int(n==10),length_le8=int(n<=8),length_le10=int(n<=10),length_ge60=int(n>=60),move_limit=int(r['termination_reason']=='move_limit'),empty_double_pass=int(a==[25,25]),black_one_stone_double_pass=int(n==3 and a[0]<25 and a[1:]==[25,25]),black_realized_all_pass=int(all(x==25 for x in a[::2])),at_rule_minimum=int(n==r['pass_min_ply']+2))

FORMAL_CONTRASTS=('komi0_minus2.5_at_pass0','komi0_minus2.5_at_pass8','komi_effect_pass8_minus_pass0')

def verify_inference(rows,saved):
    errors=[];checks=0
    def subset(expected,actual,path):
        nonlocal checks
        if not isinstance(actual,dict):errors.append(path+': missing object');return
        for k,v in expected.items():
            checks+=1;errors.extend(differences(v,actual.get(k),path+'.'+k))
    def ordered(sub):
        key=lambda r:(r['batch_seed'],r['black_seed'],r['white_seed'],r['replicate'])
        return [sorted([r for r in sub if (r['pass_min_ply'],r['komi'])==arm],key=key) for arm in ARMS]
    def vectors(arm,metric):return [inference_endpoints(r)[metric] for r in arm]
    def interaction(arms,metric):
        return [a-b-c+d for a,b,c,d in zip(*(vectors(arm,metric) for arm in arms))]
    def group(sub,actual,path):
        arms=ordered(sub);n=len(sub)//4
        subset(dict(identity_direction=sub[0]['black_identity']+'/'+sub[0]['white_identity'],n_quartets=n,n_per_arm=n),actual,path)
        errors.extend(differences(sorted(RULES.values()),sorted(actual['arms']),path+'.armkeys'))
        metrics=set(inference_endpoints(sub[0]))
        for arm,records in zip(ARMS,arms):
            target=actual['arms'][RULES[arm]];key=path+'.arms.'+RULES[arm]
            subset(dict(n=n,pass_min_ply=arm[0],komi=arm[1],length=distribution([r['move_count'] for r in records]),extra_length=distribution([r['extra_length'] for r in records]),utility_counts={c:{str(u):sum(r[c+'_utility']==u for r in records) for u in (-1,0,1)} for c in ('black','white')}),target,key)
            errors.extend(differences(sorted(metrics),sorted(target['rates']),key+'.ratekeys'))
            for metric in metrics:
                subset(independent_rate(vectors(records,metric))|dict(coverage_scope='pointwise95_not_family_adjusted'),target['rates'][metric],key+'.'+metric)
        errors.extend(differences(sorted(FORMAL_CONTRASTS),sorted(actual['contrasts']),path+'.contrastkeys'))
        for ci,(base,comp) in enumerate(((arms[0],arms[2]),(arms[1],arms[3]))):
            target=actual['contrasts'][FORMAL_CONTRASTS[ci]];key=path+'.'+FORMAL_CONTRASTS[ci]
            delta=[b['move_count']-a['move_count'] for a,b in zip(base,comp)]
            subset(dict(raw_length_delta=distribution(delta),extra_length_delta=distribution(delta),length_inference='descriptive_only'),target,key)
            for metric in metrics:
                subset(independent_pair(vectors(base,metric),vectors(comp,metric))|dict(coverage_scope='pointwise95_not_family_adjusted'),target['rates'][metric],key+'.'+metric)
        target=actual['contrasts'][FORMAL_CONTRASTS[2]];key=path+'.'+FORMAL_CONTRASTS[2]
        delta=[a['move_count']-b['move_count']-c['move_count']+d['move_count'] for a,b,c,d in zip(*arms)]
        subset(dict(raw_length_delta=distribution(delta),extra_length_delta=distribution(delta),length_inference='descriptive_only'),target,key)
        for metric in metrics:subset(independent_bounded(interaction(arms,metric))|dict(coverage_scope='pointwise95_not_family_adjusted'),target['rates'][metric],key+'.'+metric)
    subset(dict(analysis_version='komi-pass-fixed-quartet-cp-hoeffding-v1',estimation_only=True,complete_registered_sample=True,n_records=960,n_quartets=240),saved,'inference')
    subset(dict(simultaneous_family_size=3,simultaneous_family_confidence_level=.95,per_family_interval_confidence_level=1-.05/3,interaction_support=[-2,2],family=[dict(direction='LOSE/LOSE',endpoint='black_goals',contrast=c) for c in FORMAL_CONTRASTS]),saved['intervals'],'inference.intervals')
    errors.extend(differences(sorted(FORMAL_CONTRASTS),sorted(saved['primary_family']),'primary family keys'))
    ll=[r for r in rows if r['black_identity']==r['white_identity']=='LOSE']; arms=ordered(ll)
    sequences={FORMAL_CONTRASTS[0]:[b-a for a,b in zip(vectors(arms[0],'black_goals'),vectors(arms[2],'black_goals'))],FORMAL_CONTRASTS[1]:[b-a for a,b in zip(vectors(arms[1],'black_goals'),vectors(arms[3],'black_goals'))],FORMAL_CONTRASTS[2]:interaction(arms,'black_goals')}
    for i,name in enumerate(FORMAL_CONTRASTS):
        expected=independent_pair(vectors(arms[i],'black_goals'),vectors(arms[i+2],'black_goals'),1-.05/3) if i<2 else independent_bounded(sequences[name],1-.05/3)
        expected.update(simultaneous_family_ci95=expected['ci'],identity_direction='LOSE/LOSE',endpoint='black_goals',contrast=name,simultaneous_family_size=3,simultaneous_family_confidence_level=.95,coverage_scope='pooled_three_member_simultaneous_family_at_least95')
        subset(expected,saved['primary_family'][name],'primary.'+name)
        strata={}
        for r,v in zip(arms[0],sequences[name]):strata.setdefault(f"{r['batch_seed']}:{r['black_seed']},{r['white_seed']}",[]).append(v)
        means={k:math.fsum(v)/len(v) for k,v in strata.items()}
        variances={k:math.fsum((x-means[k])**2 for x in v)/(len(v)-1) for k,v in strata.items()}
        detail={k:dict(n=len(v),mean=means[k],sample_variance=variances[k]) for k,v in strata.items()}
        vari=math.fsum(variances[k]/len(v)/36 for k,v in strata.items());mean=math.fsum(means.values())/6
        support=[-2,2] if i==2 else [-1,1]
        sensitivity=dict(estimate=mean,n=60,n_fixed_strata=6,strata=detail,support=support,exact_coverage_claim=False,nominal_confidence_level=1-.05/3,nominal_bonferroni_family_size=3,coverage_scope='nonconfirmatory_approximate_sensitivity_not_primary_family')
        if vari==0:sensitivity.update(status='unavailable_zero_estimated_variance',ci=None,standard_error=0.0,degrees_of_freedom=None)
        else:
            from scipy.stats import t
            df=vari**2/math.fsum((variances[k]/len(v)/36)**2/(len(v)-1) for k,v in strata.items())
            se=math.sqrt(vari);radius=float(t.ppf(1-.05/6,df))*se
            sensitivity.update(status='approximation_only',standard_error=se,degrees_of_freedom=df,unclipped_radius=radius,ci=[max(support[0],mean-radius),min(support[1],mean+radius)])
        subset(sensitivity,saved['approximate_sensitivity'][name],'sensitivity.'+name)
    for direction in DIRECTIONS:
        sub=[r for r in rows if r['black_identity']+'/'+r['white_identity']==direction]
        group(sub,saved['pooled'][direction],'pooled.'+direction)
        for seed in SEEDS:
            sr=[r for r in sub if r['batch_seed']==seed]
            group(sr,saved['per_seed'][str(seed)][direction],f'seed.{seed}.{direction}')
            for b,w in ((1,2),(2,1)):
                group([r for r in sr if (r['black_seed'],r['white_seed'])==(b,w)],saved['per_stratum'][f'{seed}:{b},{w}'][direction],f'stratum.{seed}:{b},{w}.{direction}')
    return {'passed':not errors,'problems':errors,'numeric_or_semantic_fields_compared':checks,'method':'Independent binomial-tail bisection CP, union-bound paired rectangles, bounded-quartet Hoeffding, and separately recomputed fixed-stratum variance/Satterthwaite arithmetic. SciPy Student-t ppf shared only for approximate quantile; no production imports.'}


# Independently pinned pre-data protocol; changes require an explicit new audit version.
PROTOCOL_SHA='f4077bf78bec9cde0d9765886fd2af55aea0e3c104537bd9744cbc0abc6f3dbb'


def _audit(root,out):
    root,out=Path(root).resolve(),Path(out).resolve()
    exp=root/EXPERIMENT_PATH
    errors=[];snapshots={};input_files=set()
    def equal(expected,actual,label):errors.extend(differences(expected,actual,label))
    def raw(path):
        path=Path(path)
        if any(p.is_symlink() for p in (path,*path.parents)):
            raise ValueError('symlinked evidence forbidden: '+str(path))
        data=path.read_bytes();sha=hashlib.sha256(data).hexdigest()
        if path in snapshots and snapshots[path]!=sha:errors.append('input changed during audit: '+str(path))
        snapshots[path]=sha;input_files.add(path)
        return data
    def rd(path):return parse_json(raw(path).decode('utf-8'))
    def sha(path):raw(path);return snapshots[Path(path)]
    protocol=rd(exp/'preregistration.json')
    validate_protocol(protocol)
    equal(PROTOCOL_SHA,sha(exp/'preregistration.json'),'independently pinned preregistration')
    cells,plan=design(protocol)
    equal(GAMES,len(plan),'registered game count')
    equal(plan,rd(exp/'frozen_plan.json'),'frozen independent schedule')
    equal(plan,rd(out/'plan.json'),'saved independent schedule')
    equal([dict(index=e['index'],game_seed=e['game_seed']) for e in plan],rd(out/'game_seeds.json'),'seed mirror')
    lock=rd(exp/'pre_execution_source_lock.json')
    prelock=rd(exp/'pre_execution_lock.json')
    equal(lock,rd(out/'source_lock.json'),'source lock mirror')
    equal(prelock['source_lock_sha256'],sha(exp/'pre_execution_source_lock.json'),'frozen source lock SHA256')
    equal(True,prelock.get('registered_before_first_game'),'prelock preregistered')
    for key in PROVENANCE_KEYS:equal(lock[key],prelock.get(key),'prelock provenance '+key)
    equal(protocol['code_version'],lock['code_version'],'code version')
    equal(protocol['schema_version'],lock['schema_version'],'schema version')
    equal('sha256-utf8-lf-path-map-v1',lock.get('algorithm'),'source hash algorithm')
    inventory={}
    for path in [root/'run.py',*sorted((root/'src/winai_loseai').rglob('*.py'))]:
        safe_relative(root,path.relative_to(root).as_posix())
        normalized=raw(path).decode('utf-8').replace('\r\n','\n').replace('\r','\n')
        inventory[path.relative_to(root).as_posix()]=hashlib.sha256(normalized.encode()).hexdigest()
    equal(lock['files'],inventory,'complete normalized source inventory')
    fingerprint=hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    equal(lock['source_fingerprint'],fingerprint,'independent source fingerprint')
    for target,label in ((exp/'preregistration.json','frozen'),(out/'preregistration.json','saved')):
        equal(prelock['preregistration_sha256'],sha(target),label+' preregistration SHA256')
    equal(prelock['frozen_plan_sha256'],sha(exp/'frozen_plan.json'),'frozen plan SHA256')
    saved_lock=rd(out/'experiment_lock.json')
    lock_keys=('experiment_id',*PROVENANCE_KEYS,'preregistration_sha256','entry_point_sha256',
               'measurement_script_sha256','checkpoint_validation_script_sha256','reproduction_script_sha256','scipy_version','numpy_version')
    equal({key:prelock[key] for key in lock_keys},saved_lock,'experiment lock')
    equal(EXPERIMENT,saved_lock['experiment_id'],'experiment lock ID')
    for relative,key in (('scripts/run_komi_pass_estimation.py','entry_point_sha256'),
                         ('scripts/measure_komi_pass_estimation_chunk.py','measurement_script_sha256'),
                         ('scripts/validate_komi_estimation_checkpoint.py','checkpoint_validation_script_sha256'),
                         ('scripts/verify_komi_pass_estimation_reproduction.py','reproduction_script_sha256')):
        equal(prelock[key],sha(root/relative),relative+' frozen SHA256')
    # Pre-execution lock inventories are independent of production source locks.
    # Every supplied inventory is checked, including independent audit/test files.
    test_hashes=prelock.get('test_file_sha256')
    if not isinstance(test_hashes,dict) or not test_hashes:
        errors.append('nonempty pre-execution test source inventory is required')
    else:
        equal(sorted(p.relative_to(root).as_posix() for p in (root/'tests').rglob('*.py')),
              sorted(k for k in test_hashes if k.startswith('tests/')),'complete frozen test source inventory')
    for key,value in prelock.items():
        if (key.endswith('_files_sha256') or key=='test_file_sha256') and isinstance(value,dict):
            for relative,expected_sha in value.items():
                equal(expected_sha,sha(safe_relative(root,relative)),key+': '+relative)
    if 'full_suite' in prelock:
        info=prelock['full_suite']
        logfile=info.get('log_path','experiments/komi_pass_estimation_v1/full_tests_final_prelaunch.txt')
        expected_log_sha=info.get('log_sha256',prelock.get('review_files_sha256',{}).get(logfile))
        equal(expected_log_sha,sha(safe_relative(root,logfile)),'frozen full-suite log')
    if 'production_games_before_freeze' in prelock:
        equal(0,prelock['production_games_before_freeze'],'production games before freeze')
    elif 'formal_games_before_freeze' in prelock:
        equal(0,prelock['formal_games_before_freeze'],'formal games before freeze')
    else:errors.append('pre-execution zero formal-game declaration missing')
    provenance={key:lock[key] for key in PROVENANCE_KEYS}
    manifest=rd(out/'manifest.json')
    expected_manifest=dict(batch_id=BATCH,kind=EXPERIMENT,status='completed',requested_games=GAMES,
        planned_game_count=GAMES,completed_game_count=GAMES,completed_indexes=list(range(GAMES)),
        board_size=5,komi=None,komis=[2.5,0.0],batch_seed=list(SEEDS),concurrency=1,
        pass_min_plies=[0,8],budget=256,schedule_seed=2026100501,games_per_cell=10,checkpoint_games=48,**provenance)
    agents={e[c]['agent_id']:e[c] for e in plan for c in ('black','white')}
    expected_manifest['agents']=list(agents.values())
    for key,value in expected_manifest.items():equal(value,manifest.get(key),'manifest.'+key)
    if (out/'rule_fault.json').exists():errors.append('persisted rule_fault.json prohibits completed audit')
    files=sorted((out/'games').glob('*.json'))
    equal([f'{BATCH}-g{i:06d}.json' for i in range(GAMES)],[p.name for p in files],'raw filenames/count')
    extras=[p.name for p in (out/'games').iterdir() if not p.is_file() or p.suffix!='.json']
    equal([],extras,'unexpected game artifacts including unfinished tmp files')
    rows=[];metadata=[];per_game={}
    for index,entry in enumerate(plan):
        file=out/'games'/f'{BATCH}-g{index:06d}.json'
        if not file.is_file():continue
        try:
            rec=rd(file)
            row,issues=reconstruct(rec,cells[index],entry,file.stat().st_size,provenance)
            rows.append(row)
            metadata.append({k:v for k,v in rec.items() if k not in ('black','white','moves')} |
                dict(opening_actions=[m['action'] for m in rec['moves'][:12]],game_file='games/'+file.name))
            per_game[file.stem]=dict(passed=not issues,problems=issues,actions=row['move_count'],
                black_score=row['black_score'],white_score=row['white_score'],winner=row['winner'],
                black_utility=row['black_utility'],white_utility=row['white_utility'],
                color_counts=row['color_counts'],pass_proposals=len(row['pass_proposals']))
            errors.extend(file.name+': '+issue for issue in issues)
        except (OSError,ValueError,TypeError,KeyError,IndexError,OverflowError) as exc:
            issue=f'malformed/illegal record: {type(exc).__name__}: {exc}'
            errors.append(file.name+': '+issue);per_game[file.stem]=dict(passed=False,problems=[issue])
    lines=raw(out/'games.jsonl').decode('utf-8').splitlines()
    if any(not line.strip() for line in lines):errors.append('blank JSONL record forbidden')
    equal(metadata,[parse_json(line) for line in lines],'complete ordered metadata mirror')
    equal(list(range(GAMES)),[r['game_index'] for r in rows],'canonical game indexes')
    equal(BLOCKS,len({r['block_id'] for r in rows}),'240 unique four-arm blocks')
    equal(BLOCKS,len({e['game_seed'] for e in plan}),'240 distinct initial game seeds')
    streams={seed_from(('agent-stream',e['game_seed'],color,e[color]['seed'])) for e in plan for color in ('black','white')}
    equal(480,len(streams),'480 distinct initial color-agent streams')
    orders=[]
    for i in range(0,GAMES,4):
        block=plan[i:i+4]
        order=tuple((e['pass_min_ply'],e['komi']) for e in block);orders.append(order)
        equal(set(ARMS),set(order),f'four-arm set {i//4}')
        expected={k:v for k,v in block[0].items() if k not in ('index','pass_min_ply','komi')}
        for entry in block[1:]:
            equal(expected,{k:v for k,v in entry.items() if k not in ('index','pass_min_ply','komi')},f'paired agents and seed {i//4}')
    equal(Counter({order:10 for order in itertools.permutations(ARMS)}),Counter(orders),'all24 arm permutations repeated10 times')
    for position in range(4):equal(Counter({arm:60 for arm in ARMS}),Counter(order[position] for order in orders),f'sixty arms at position{position}')
    counts=Counter((r['pass_min_ply'],r['komi'],r['batch_seed'],r['black_identity'],r['white_identity'],r['black_seed'],r['white_seed']) for r in rows)
    expected_counts={(p,k,seed,*d.split('/'),*orientation):10 for p,k in ARMS for seed in SEEDS for d in DIRECTIONS for orientation in ((1,2),(2,1))}
    equal(expected_counts,counts,'96 fixed cells with ten games each')
    raw_hashes={p.name:sha(p) for p in files}
    expected_validation=dict(experiment_id=EXPERIMENT,planned=GAMES,game_count=GAMES,
        replay_and_search_ok=GAMES,complete=True,problems=[],manifest_status='completed',
        rule_fault_present=False,source_fingerprint=fingerprint,raw_game_sha256=raw_hashes)
    equal(expected_validation,rd(out/'validation.json'),'saved completed validation snapshot')
    saved_analysis=rd(out/'analysis.json');recomputed=None;statistical_check=None
    if not errors:
        recomputed=assemble(rows)
        equal(recomputed,{k:v for k,v in saved_analysis.items() if k!='inference'},'independent descriptive analysis')
        statistical_check=verify_inference(rows,saved_analysis['inference'])
        errors.extend(statistical_check['problems'])
        recomputed['independent_inference_verification']=statistical_check
    for path,original in snapshots.items():
        if digest(path)!=original:errors.append('input changed during audit: '+str(path))
    complete=len(rows)==GAMES and counts==expected_counts
    report=dict(audit_id=AUDIT_ID,experiment_id=EXPERIMENT,passed=not errors,complete=complete,
        n_records=len(rows),n_four_arm_blocks=len({r['block_id'] for r in rows}),
        n_actual_actions=sum(r['move_count'] for r in rows),n_pass_proposals=sum(len(r['pass_proposals']) for r in rows),
        n_draws=sum(r['winner']=='draw' for r in rows),problems=errors,per_game=per_game,
        source_fingerprint=fingerprint,descriptive_comparison_executed=recomputed is not None,statistical_crosscheck=statistical_check,
        input_sha256={str(p.relative_to(root)) if p.is_relative_to(root) else str(p):snapshots[p] for p in sorted(input_files)},
        coverage=[
            '960 canonical games,240 matched four-arm blocks,all24 order permutations repeated10times;three seeds and four identity directions',
            'Independent union-find area scoring with actual per-game komi;exactly zero margin draw;both draw utilities zero;no draw goals',
            'Independent actual captures,suicide,situational superko,full actual-root legal sets,pass window,and terminal precedence',
            'Search budget,root visits,maximum-visit choice,Q bounds/nulls/identity-vector symmetry,and superko counts',
            'Full descriptive schema including draws,utility counts,neutral proposal events,prefixes,representatives,and five factorial simple contrasts',
            'Strict JSON/JSONL shape and metadata mirrors;source,protocol,plan,entry,measurement,and supplied test/evidence inventories',
            'Descriptives and all primary/secondary numerical inference independently recomputed from actual trajectories; no historical/future sample pooling'],
        limitations=[
            'Does not prove internal tree/rollout legality,UCT or RNG execution,or numerical Q correctness;deterministic regenerations are separate.',
            'Read-only production-source inspection was used for schema compatibility. Geometry and replay derive from copied/adapted independent M5 code;aggregate math is separately written.',
            'Observed timings and byte counts are validated and aggregated;resource process metrics and historical preservation are separate evidence.',
            'Source locks establish byte consistency,not external timestamp attestation or resistance to coordinated malicious multi-file tampering.',
            'Finite-sample intervals condition on the registered independent-quartet model and fixed allocation; they do not establish policy optimality, pure coordination effects, or7x7 readiness.'])
    return report,recomputed


def audit(root,out):
    """Read-only, fail-closed, complete formal sample only. Never repair evidence."""
    try:return _audit(root,out)
    except (OSError,ValueError,TypeError,KeyError,IndexError,OverflowError,AttributeError) as exc:
        return dict(audit_id=AUDIT_ID,experiment_id=EXPERIMENT,passed=False,complete=False,
            descriptive_comparison_executed=False,problems=[f'Audit could not finish: {type(exc).__name__}: {exc}']),None


def check_output_targets(root,out,targets):
    allowed=Path(root).resolve()/EXPERIMENT_PATH/'independent_audit'
    resolved=[]
    for target in targets:
        path=Path(target).absolute()
        if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('symlinked audit output forbidden')
        dest=path.resolve()
        if set(dest.parts)&{'winorlose','winorlose_d0_v1','winorlose_d1_v1','winorlose_d1_estimation_v1','winorlose_g1_pass8_v1','winorlose_g1_pass8_estimation_v1','winorlose_komi_pass_pilot_v1'}:
            raise ValueError('historical worktrees are forbidden audit output targets')
        if not dest.is_relative_to(allowed) or dest==allowed:raise ValueError('audit output must be under this M7 independent_audit directory')
        if dest.is_relative_to(Path(out).resolve()) or path.exists():raise ValueError('audit output must not exist or modify input evidence')
        if dest in resolved:raise ValueError('audit output targets must be distinct')
        resolved.append(dest)
    return resolved


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--recomputed',type=Path)
    parser.add_argument('--data-ready',action='store_true',help='Owner declares all960 formal games ready')
    args=parser.parse_args(argv)
    if not args.data_ready:parser.error('requires explicit --data-ready; never audit partial formal data')
    try:targets=check_output_targets(args.root,args.out,[args.report]+([args.recomputed] if args.recomputed else []))
    except ValueError as exc:parser.error(str(exc))
    report,recomputed=audit(args.root,args.out)
    report['audit_script_sha256']=digest(__file__)
    report['execution_role']='read-only complete960 formal verification'
    for target,document in zip(targets,[report,recomputed]):
        if document is not None:
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('x',encoding='utf-8') as handle:
                json.dump(document,handle,ensure_ascii=False,indent=2,allow_nan=False);handle.write('\n')
    print(json.dumps({k:report.get(k) for k in ('passed','complete','n_records','n_four_arm_blocks','problems')},indent=2))
    return int(not report['passed'])


if __name__=='__main__':sys.exit(main())
