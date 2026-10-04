"""Read-only, guarded independent arithmetic check for M5 fixed-480 inference.

This recovery verifier adds canonical raw-row gates before the prior independent
binomial-polynomial arithmetic implementation. It imports no production code.
It does not replace replay, source-lock, manifest, or raw-record validation.
CLI: python recovery_verify_inference_v1.py /path/to/analysis.json
The CLI prints JSON and never writes to the input experiment directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random

import verify_inference_arithmetic as arithmetic

DIRECTIONS = (('WIN', 'WIN'), ('LOSE', 'LOSE'), ('WIN', 'LOSE'), ('LOSE', 'WIN'))
ORIENTATIONS = ((1, 2), (2, 1))
RULES = {0: 'G0', 8: 'G1-pass8'}
SEEDS = (11, 12, 13)
KEYS = ('pass_min_ply', 'batch_seed', 'black_identity', 'white_identity',
        'black_seed', 'white_seed', 'replicate')
INTEGER_FIELDS = ('pass_min_ply', 'batch_seed', 'black_seed', 'white_seed',
                  'replicate', 'budget', 'block_index', 'game_seed', 'move_count')


def seed_for(batch_seed, block_index):
    text = f'game-seed|{batch_seed}|{block_index}'
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:16], 'big')


def expected_rows():
    blocks = [(seed, *direction, *orientation, replicate)
              for seed in SEEDS for direction in DIRECTIONS
              for orientation in ORIENTATIONS for replicate in range(10)]
    rng = random.Random(2026100402)
    rng.shuffle(blocks)
    arm_orders = [[0, 8], [8, 0]] * 120
    rng.shuffle(arm_orders)
    return {(rule, *block): index
            for index, (rule, block) in enumerate(
                (rule, block) for block, order in zip(blocks, arm_orders)
                for rule in order)}


def validate_rows(rows):
    """Return explicit problems, never silently filter, impute, or reweight."""
    problems = []
    if not isinstance(rows, list):
        return ['rows must be a list containing all 480 formal records']
    if len(rows) != 480:
        problems.append(f'exactly 480 rows required; observed {len(rows)}')
    expected = expected_rows()
    observed = Counter()
    strata = Counter()
    pair_arms = {}
    indexes_present = sum(isinstance(r, dict) and 'game_index' in r for r in rows)
    ids_present = sum(isinstance(r, dict) and 'game_id' in r for r in rows)
    if indexes_present not in (0, 480):
        problems.append('game_index metadata must be either absent or complete')
    if ids_present not in (0, 480):
        problems.append('game_id metadata must be either absent or complete')
    for i, row in enumerate(rows):
        try:
            if not isinstance(row, dict) or any(type(row[k]) is not int for k in INTEGER_FIELDS):
                raise ValueError('missing or noninteger design/length field')
            key = tuple(row[k] for k in KEYS)
            if key not in expected:
                raise ValueError('unregistered row key')
            observed[key] += 1
            rule, seed, ib, iw, sb, sw, replicate = key
            block_index = (DIRECTIONS.index((ib, iw)) * 2 + ORIENTATIONS.index((sb, sw))) * 10 + replicate
            if (row['budget'] != 256 or row['block_index'] != block_index
                    or row['block_id'] != f'{seed}:{block_index}'
                    or row['game_seed'] != seed_for(seed, block_index)
                    or row['ruleset'] != RULES[rule]):
                raise ValueError('budget or canonical block/seed/rule mismatch')
            if 'game_index' in row and (type(row['game_index']) is not int or row['game_index'] != expected[key]):
                raise ValueError('game_index does not match frozen schedule')
            if 'game_id' in row and row['game_id'] != f'g1_pass8_estimation_v1-g{expected[key]:06d}':
                raise ValueError('game_id does not match frozen schedule')
            n, actions = row['move_count'], row['actions']
            if (not rule + 2 <= n <= 100 or not isinstance(actions, list)
                    or len(actions) != n or any(type(a) is not int or not 0 <= a <= 25 for a in actions)
                    or 25 in actions[:rule]
                    or any(actions[j:j + 2] == [25, 25] for j in range(n - 2))):
                raise ValueError('invalid bounded length, pass window, or terminal sequence')
            reason = 'double_pass' if actions[-2:] == [25, 25] else 'move_limit'
            if row['termination_reason'] != reason or (reason == 'move_limit' and n != 100):
                raise ValueError('invalid termination reason or precedence')
            if row['winner'] not in ('black', 'white'):
                raise ValueError('winner must be black or white at komi 2.5')
            for color in ('black', 'white'):
                value = row[color + '_utility']
                expected_utility = 1 if ((row['winner'] == color) == (row[color + '_identity'] == 'WIN')) else -1
                if type(value) is not int or value != expected_utility:
                    raise ValueError('utility does not agree with winner and identity')
            if 'extra_length' in row and (type(row['extra_length']) is not int or row['extra_length'] != n - rule - 2):
                raise ValueError('extra length is not the registered translation')
            strata[rule, seed, ib, iw, sb, sw] += 1
            pair_arms.setdefault(key[1:], []).append(rule)
        except (KeyError, TypeError, ValueError) as error:
            problems.append(f'row {i}: {error}')
    if set(observed) != set(expected) or any(n != 1 for n in observed.values()):
        problems.append('rows are not the exact unique canonical fixed-480 key set')
    if len(pair_arms) != 240 or any(sorted(arms) != [0, 8] for arms in pair_arms.values()):
        problems.append('exactly 240 matched blocks with both rule arms required')
    if len(strata) != 48 or any(n != 10 for n in strata.values()):
        problems.append('exactly 48 rule/seed/direction/orientation cells of size 10 required')
    for direction in DIRECTIONS:
        for rule in RULES:
            count = sum(n for (r, s, ib, iw, sb, sw), n in strata.items() if r == rule and (ib, iw) == direction)
            if count != 60:
                problems.append(f'{direction} rule {rule}: expected 60 observations, got {count}')
            for seed in SEEDS:
                count = sum(n for (r, s, ib, iw, sb, sw), n in strata.items()
                            if r == rule and s == seed and (ib, iw) == direction)
                if count != 20:
                    problems.append(f'{direction} seed {seed} rule {rule}: expected 20 observations, got {count}')
    return problems


def verify(rows, saved):
    problems = validate_rows(rows)
    if not isinstance(saved, dict):
        problems.append('saved inference must be an object')
    if problems:
        return {'passed': False, 'problems': problems, 'arithmetic_executed': False,
                'method': 'recovery_fixed480_canonical_gate_v1'}, None
    try:
        checked, expected = arithmetic.verify(rows, saved)
    except (KeyError, TypeError, ValueError, AttributeError, AssertionError) as error:
        return {'passed': False, 'problems': [f'malformed saved inference: {error}'],
                'arithmetic_executed': False, 'method': 'recovery_fixed480_canonical_gate_v1'}, None
    intervals = saved.get('intervals', {})
    for key, value in {'paired_goal_method': arithmetic.METHOD,
                       'raw_length_method': 'Hoeffding_independent_bounded_mean'}.items():
        checked['problems'] += arithmetic.close(value, intervals.get(key), 'inference.intervals.' + key)
    checked.update(passed=not checked['problems'], arithmetic_executed=True,
                   canonical_fixed480_rows_checked=True, unique_paired_blocks=240,
                   pooled_pairs_per_direction=60, pairs_per_seed_direction=20,
                   recovery_verifier_version='recovery_fixed480_canonical_gate_v1')
    checked['limitations'] += ['Requires separately passed raw-record/source/manifest/replay checks. Structural action checks are not a legality proof.',
                               'The fixed stream-independence model remains an assumption; no coverage is claimed conditional on choosing only fault-free runs.']
    return checked, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis', type=Path)
    args = parser.parse_args()
    document = json.loads(args.analysis.read_text(encoding='utf-8'))
    result, _ = verify(document.get('rows'), document.get('inference'))
    print(json.dumps(result, indent=2))
    return int(not result['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
