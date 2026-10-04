#!/usr/bin/env python3
"""Post-completion independent audit of D1-G0-estimation-v1.

Prepared from frozen protocol/schema only, before final behavioral analysis.
Never imports the experiment package or SciPy. CP limits are independently
obtained by direct binomial-tail summation and monotone bisection, rather than
the frozen implementation's inverse-beta quantiles. No output is read until
the explicit CLI authorization and the completed/720-file gate both pass.

This checks reported statistics, configuration, raw actions and independent
area scoring. It is not a replacement for the separate all-game legal replay,
search validator, or regeneration checks. It never edits the run or repo.

After explicit permission to read FINAL outcomes:
  python check_final_analysis_independent.py --final-analysis-authorized \
      --repo /path/to/winorlose_d1_estimation_v1 --run /path/to/completed/run \
      --report /outside/repo/independent_final_analysis_audit.json
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys


PREPARED_UTC = '2026-10-04T03:27:00+00:00'
FROZEN_HASHES = {
    'experiments/d1_estimation_v1/preregistration.json':
        '4eb8abc6b7faa538a3380036210023dcbe561494711d4284997a5b0287263b84',
    'experiments/d1_estimation_v1/protocol_clarifications.json':
        '57eb18e0370e877cfb704c68aa29161b14add7a60d4c8a160ee2f801abd367b6',
    'src/winai_loseai/experiments/d1_estimation_stats.py':
        '18881afa7df0068e0883a609285087a58e749ffa98b7484a18635448a74bbe69',
}
BUDGETS = (64, 256, 1024)
SEEDS = (5, 6, 7)
DIRECTIONS = ('WIN/WIN', 'LOSE/LOSE', 'WIN/LOSE', 'LOSE/WIN')
ORIENTATIONS = ((1, 2), (2, 1))
PRIMARY = {'LOSE/LOSE': 'black_realized_all_pass',
           'WIN/LOSE': 'black_one_stone_double_pass',
           'LOSE/WIN': 'empty_double_pass'}
PRIMARY_COMPARISONS = ((256, 64), (1024, 64))
COMPARISONS = (*PRIMARY_COMPARISONS, (1024, 256))
CI_METHOD = 'paired_discordance_two_sided_CP_rectangle_Bonferroni'
ABS_TOL = 2e-10


class Refused(RuntimeError):
    pass


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise Refused(message)


def binomial_tail(n, p, start, stop):
    """Inclusive finite binomial sum; n<=60 here, no special functions."""
    return math.fsum(math.comb(n, j) * p**j * (1 - p)**(n - j)
                     for j in range(start, stop + 1))


def solve_increasing_tail(n, k, tail):
    """Solve P[Bin(n,p)>=k]=tail; n>=1 and 1<=k<=n."""
    lo, hi = 0., 1.
    for _ in range(75):
        mid = (lo + hi) / 2
        if binomial_tail(n, mid, k, n) < tail:
            lo = mid
        else:
            hi = mid
    return lo


@lru_cache(maxsize=None, typed=True)
def cp_tail_inversion(k, n, confidence=.95):
    require(type(n) is int and type(k) is int and n >= 1 and 0 <= k <= n,
            'Invalid CP input')
    require(.5 <= confidence < 1, 'Invalid CP confidence')
    tail = (1 - confidence) / 2
    lower = 0. if k == 0 else solve_increasing_tail(n, k, tail)
    # Symmetry of the lower-tail root; preserves outward endpoint rounding.
    upper = 1. if k == n else 1 - solve_increasing_tail(n, n - k, tail)
    return [lower, upper]


def independent_math_checks():
    """Known boundary solutions and finite-sum residuals, no run inputs."""
    checks = 0
    for n in (10, 20, 60):
        for confidence in (.95, .975, 1 - .05 / 12):
            tail = (1 - confidence) / 2
            lo, hi = cp_tail_inversion(0, n, confidence)
            require(lo == 0 and abs(hi - (1 - tail**(1 / n))) < 5e-14,
                    'Independent CP zero-count self-check failed')
            lo, hi = cp_tail_inversion(n, n, confidence)
            require(hi == 1 and abs(lo - tail**(1 / n)) < 5e-14,
                    'Independent CP all-count self-check failed')
            checks += 2
            for k in range(1, n):
                lo, hi = cp_tail_inversion(k, n, confidence)
                require(abs(binomial_tail(n, lo, k, n) - tail) < 1e-12,
                        'Independent CP lower-tail residual failed')
                require(abs(binomial_tail(n, hi, 0, k) - tail) < 1e-12,
                        'Independent CP upper-tail residual failed')
                checks += 2
    return checks


def rate(values):
    n, k = len(values), sum(values)
    return {'successes': k, 'n': n, 'estimate': k / n, 'confidence_level': .95,
            'ci': cp_tail_inversion(k, n),
            'method': 'two_sided_Clopper_Pearson_average_probability'}


def paired(aa, bb, simultaneous=False):
    require(len(aa) == len(bb) and len(aa) > 0, 'Invalid independent pairing')
    counts = Counter(zip(aa, bb))
    n, positive, negative = len(aa), counts[0, 1], counts[1, 0]
    p_ci, m_ci = cp_tail_inversion(positive, n, .975), cp_tail_inversion(negative, n, .975)
    estimate = (positive - negative) / n
    ci = [p_ci[0] - m_ci[1], p_ci[1] - m_ci[0]]
    radius = math.sqrt(2 * math.log(40) / n)
    audit = [max(-1., estimate - radius), min(1., estimate + radius)]
    result = {'n': n, 'baseline_successes': sum(aa), 'comparison_successes': sum(bb),
              'n00': counts[0, 0], 'n01': positive, 'n10': negative, 'n11': counts[1, 1],
              'discordant_pairs': positive + negative, 'estimate': estimate,
              'confidence_level': .95, 'ci': ci, 'ci95': ci,
              'component_confidence_level': .975, 'positive_probability_ci': p_ci,
              'negative_probability_ci': m_ci, 'method': CI_METHOD,
              'hoeffding_ci': audit, 'ci95_hoeffding': audit, 'hoeffding_radius': radius}
    if simultaneous:
        c = 1 - .05 / 12
        pp, mm = cp_tail_inversion(positive, n, c), cp_tail_inversion(negative, n, c)
        result.update(simultaneous_primary_ci95=[pp[0] - mm[1], pp[1] - mm[0]],
                      simultaneous_family_size=6, simultaneous_component_confidence_level=c)
    return result


class Comparisons:
    def __init__(self):
        self.checks = 0
        self.numeric_checks = 0
        self.max_abs_error = 0.
        self.mismatch_count = 0
        self.mismatches = []

    def mismatch(self, path, expected, actual):
        self.mismatch_count += 1
        if len(self.mismatches) < 100:
            self.mismatches.append({'path': path, 'expected': expected, 'reported': actual})

    def compare(self, actual, expected, path, exact_keys=False):
        self.checks += 1
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                self.mismatch(path, 'object', actual)
                return
            if exact_keys and set(actual) != set(expected):
                self.mismatch(path + '.keys', sorted(expected), sorted(actual))
            for key, value in expected.items():
                if key not in actual:
                    self.mismatch(path + '.' + key, value, '<missing>')
                else:
                    self.compare(actual[key], value, path + '.' + key, exact_keys)
        elif isinstance(expected, list):
            if not isinstance(actual, list) or len(actual) != len(expected):
                self.mismatch(path, expected, actual)
            else:
                for i, value in enumerate(expected):
                    self.compare(actual[i], value, path + f'[{i}]', exact_keys)
        elif type(expected) is float:
            self.numeric_checks += 1
            if type(actual) not in (int, float) or not math.isfinite(actual):
                self.mismatch(path, expected, actual)
            else:
                error = abs(actual - expected)
                self.max_abs_error = max(self.max_abs_error, error)
                if error > ABS_TOL:
                    self.mismatch(path, expected, actual)
        elif type(actual) is not type(expected) or actual != expected:
            self.mismatch(path, expected, actual)


def independently_score(board):
    """Simple 5x5 flood fill, independent of package scoring functions."""
    require(isinstance(board, list) and len(board) == 25
            and all(type(x) is int and x in (0, 1, 2) for x in board), 'Invalid final board')
    points = {1: board.count(1), 2: board.count(2) + 2.5}
    unseen = {i for i, x in enumerate(board) if x == 0}
    while unseen:
        component, boundary, queue = set(), set(), [next(iter(unseen))]
        while queue:
            i = queue.pop()
            if i in component:
                continue
            component.add(i)
            r, c = divmod(i, 5)
            for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if 0 <= rr < 5 and 0 <= cc < 5:
                    j = rr * 5 + cc
                    if board[j] == 0 and j not in component:
                        queue.append(j)
                    elif board[j]:
                        boundary.add(board[j])
        unseen.difference_update(component)
        if len(boundary) == 1:
            points[next(iter(boundary))] += len(component)
    return points[1], points[2]


def design_plan(p):
    """Construct the complete design independently from recorded loop order."""
    plan = []
    for budget in BUDGETS:
        for seed in SEEDS:
            for d, direction in enumerate(DIRECTIONS):
                ib, iw = direction.split('/')
                for o, (sb, sw) in enumerate(ORIENTATIONS):
                    for rep in range(10):
                        block_index = 20 * d + 10 * o + rep
                        game_seed = int.from_bytes(hashlib.sha256(
                            f'game-seed|{seed}|{block_index}'.encode()).digest()[:16], 'big')
                        plan.append({'budget': budget, 'batch_seed': seed,
                                     'black_identity': ib, 'white_identity': iw,
                                     'black_seed': sb, 'white_seed': sw, 'replicate': rep,
                                     'block_index': block_index, 'block_id': f'{seed}:{block_index}',
                                     'game_seed': game_seed, 'game_index': len(plan), 'direction': direction})
    return plan


def raw_row(record, expected, check):
    index = expected['game_index']
    label = f'raw[{index}]'
    gid = f'd1_g0_estimation_v1-g{index:06d}'
    budget = expected['budget']
    level = {64: 'shallow', 256: 'medium', 1024: 'deep'}[budget]
    check.compare(record, {'game_index': index, 'game_id': gid, 'batch_id': 'd1_g0_estimation_v1',
                          'game_seed': expected['game_seed'], 'board_size': 5, 'komi': 2.5,
                          'schema_version': 1, 'code_version': 'winai_loseai-0.5.0-d1-estimation'}, label)
    for color in ('black', 'white'):
        identity, seed = expected[color + '_identity'], expected[color + '_seed']
        spec = {'agent_id': f'{identity}-{level}-s{seed}', 'identity': identity,
                'algorithm': 'vector_mcts', 'compute_level': level, 'seed': seed}
        check.compare(record[color], spec, label + '.' + color, True)
        check.compare(record, {color + '_' + key: spec[key] for key in ('agent_id', 'identity', 'algorithm', 'compute_level')}, label)
    moves = record['moves']
    require(isinstance(moves, list) and 2 <= len(moves) <= 100, label + ': invalid moves')
    actions = []
    for i, move in enumerate(moves):
        action = move['action']
        require(type(action) is int and 0 <= action <= 25, label + ': invalid action')
        actions.append(action)
        check.compare(move, {'index': i + 1, 'color': 'black' if i % 2 == 0 else 'white',
                             'is_pass': action == 25, 'simulations_used': budget,
                             'root_visit_count': budget}, label + f'.moves[{i}]')
    check.compare(record['move_count'], len(actions), label + '.move_count')
    terminal = 'double_pass' if actions[-2:] == [25, 25] else 'move_limit'
    require(terminal == 'double_pass' or len(actions) == 100, label + ': no valid terminal condition')
    require(all(actions[i:i + 2] != [25, 25] for i in range(len(actions) - 2)),
            label + ': actions continue after double pass')
    check.compare(record['termination_reason'], terminal, label + '.termination_reason')
    black, white = independently_score(record['final_board'])
    winner = 'black' if black > white else 'white'
    require(black != white, label + ': impossible G0 draw')
    utilities = {c: 1 if ((winner == c) == (expected[c + '_identity'] == 'WIN')) else -1
                 for c in ('black', 'white')}
    check.compare(record, {'black_score': float(black), 'white_score': float(white),
                          'score_margin': float(black - white), 'winner': winner,
                          'black_utility': utilities['black'], 'white_utility': utilities['white']}, label)
    own_black, own_white = actions[::2], actions[1::2]
    flags = {
        'black_realized_all_pass': int(bool(own_black) and not any(a != 25 for a in own_black)),
        'black_one_stone_double_pass': int(len(actions) == 3 and 0 <= actions[0] < 25 and actions[1:] == [25, 25]),
        'empty_double_pass': int(actions == [25, 25]),
        'literal_one_stone_a0': int(actions == [0, 25, 25]),
        'black_board_wins': int(winner == 'black'), 'white_board_wins': int(winner == 'white'),
        'black_goals': int(utilities['black'] == 1), 'white_goals': int(utilities['white'] == 1),
        'joint_goals': int(utilities['black'] == utilities['white'] == 1),
        'length2': int(len(actions) == 2), 'length3': int(len(actions) == 3),
        'length_le8': int(len(actions) <= 8), 'length_ge60': int(len(actions) >= 60),
        'move_limit': int(terminal == 'move_limit'),
    }
    return {**expected, 'game_id': gid, 'actions': actions, 'move_count': len(actions),
            'winner': winner, 'black_utility': utilities['black'], 'white_utility': utilities['white'],
            'flags': flags, 'white_all_pass': bool(own_white) and all(a == 25 for a in own_white)}


def quantile(values, q):
    values = sorted(values)
    x = (len(values) - 1) * q
    i, fraction = math.floor(x), x % 1
    return values[i] if fraction == 0 else (1 - fraction) * values[i] + fraction * values[i + 1]


def distribution(values):
    return {'n': len(values), 'mean': float(statistics.mean(values)),
            **{name: float(quantile(values, q)) for name, q in
               (('min', 0), ('q1', .25), ('median', .5), ('q3', .75), ('p90', .9), ('p95', .95), ('max', 1))}}


def verify_group(rows, actual, direction, label, check, pooled=False):
    n = len(rows) // 3
    check.compare(actual, {'identity_direction': direction, 'primary_endpoint': PRIMARY.get(direction),
                          'n_per_budget': n}, label)
    endpoint_names = list(rows[0]['flags'])
    by_budget = {b: sorted((r for r in rows if r['budget'] == b), key=lambda r: r['block_id']) for b in BUDGETS}
    evidence = {'primary_endpoint': PRIMARY.get(direction), 'n_per_budget': n, 'rates': {}, 'contrasts': {}}
    for budget in BUDGETS:
        rr = by_budget[budget]
        reported = actual['budgets'][str(budget)]
        check.compare(reported['n'], n, label + f'.budgets.{budget}.n')
        check.compare(sorted(reported['rates']), sorted(endpoint_names), label + f'.budgets.{budget}.rate_names')
        for name in endpoint_names:
            expected = rate([r['flags'][name] for r in rr])
            check.compare(reported['rates'][name], expected, label + f'.budgets.{budget}.rates.{name}', True)
            if name == PRIMARY.get(direction):
                evidence['rates'][str(budget)] = expected
        check.compare(reported['length'], distribution([r['move_count'] for r in rr]), label + f'.budgets.{budget}.length', True)
    for comparison, baseline in COMPARISONS:
        aa, bb = by_budget[baseline], by_budget[comparison]
        require([r['block_id'] for r in aa] == [r['block_id'] for r in bb], 'Independent block mismatch')
        key = f'{comparison}-{baseline}'
        reported = actual['contrasts'][key]
        check.compare(reported, {'baseline_budget': baseline, 'comparison_budget': comparison,
                                'contrast_role': 'primary_budget_contrast' if baseline == 64 else 'secondary_budget_contrast',
                                'length_delta_inference': 'descriptive_only'}, label + '.contrasts.' + key)
        check.compare(sorted(reported['rates']), sorted(endpoint_names), label + '.contrasts.' + key + '.rate_names')
        for name in endpoint_names:
            simultaneous = pooled and baseline == 64 and name == PRIMARY.get(direction)
            expected = paired([r['flags'][name] for r in aa], [r['flags'][name] for r in bb], simultaneous)
            check.compare(reported['rates'][name], expected, label + f'.contrasts.{key}.rates.{name}', True)
            if name == PRIMARY.get(direction):
                evidence['contrasts'][key] = expected
        check.compare(reported['length_delta'], distribution([b['move_count'] - a['move_count'] for a, b in zip(aa, bb)]),
                      label + f'.contrasts.{key}.length_delta', True)
    return evidence


def verify_lengths(rows, actual, label, check):
    evidence = {}
    for budget in BUDGETS:
        available = [r for r in rows if r['budget'] == budget]
        by_direction = {}
        for direction in DIRECTIONS:
            full = [r['move_count'] for r in available if r['direction'] == direction]
            retained = [length for length in full if length > 3]
            by_direction[direction] = {'full_n': len(full), 'full_mean': statistics.mean(full),
                                       'retained_n': len(retained), 'excluded_n': len(full) - len(retained),
                                       'retained_mean': statistics.mean(retained) if retained else None}
        evidence[str(budget)] = {'per_identity_direction': by_direction}
        for mode, selected in (('all_games', available), ('exclude_length2_3', [r for r in available if r['move_count'] > 3])):
            mixed = [r['move_count'] for r in selected if r['black_identity'] != r['white_identity']]
            same = [r['move_count'] for r in selected if r['black_identity'] == r['white_identity']]
            difference = float(statistics.mean(mixed) - statistics.mean(same)) if mixed and same else None
            expected = {'mixed_n': len(mixed), 'same_n': len(same),
                        'mixed': distribution(mixed) if mixed else None,
                        'same': distribution(same) if same else None,
                        'mixed_minus_same_mean': difference,
                        'identity_denominators': {d: sum(r['direction'] == d for r in selected) for d in DIRECTIONS},
                        'inference': 'descriptive_only; no pairing across identity directions'}
            check.compare(actual[str(budget)][mode], expected, label + f'.{budget}.{mode}', True)
            evidence[str(budget)][mode] = {'mixed_n': len(mixed), 'same_n': len(same),
                                         'mixed_minus_same_mean': difference}
    return evidence


def audit(repo, run, report_path):
    require(not report_path.is_relative_to(repo) and not report_path.is_relative_to(run),
            'Audit report must be outside the frozen repo and run')
    for relative, digest in FROZEN_HASHES.items():
        require(sha256_file(repo / relative) == digest, 'Prepared source changed: ' + relative)
    p = read_json(repo / 'experiments/d1_estimation_v1/preregistration.json')
    # Only the manifest and directory entry names may be inspected before this gate.
    manifest_path = run / 'manifest.json'
    manifest_hash = sha256_file(manifest_path)
    manifest = read_json(manifest_path)
    require(manifest.get('status') == 'completed', 'REFUSED: manifest status is not completed')
    require(manifest.get('planned_game_count') == manifest.get('completed_game_count') == 720,
            'REFUSED: manifest does not declare exactly 720 completed games')
    require(manifest.get('completed_indexes') == list(range(720)), 'REFUSED: completion index coverage is not 0..719')
    filenames = sorted(path.name for path in (run / 'games').iterdir())
    expected_names = [f'd1_g0_estimation_v1-g{i:06d}.json' for i in range(720)]
    require(filenames == expected_names, 'REFUSED: games directory is not exactly the 720 registered game files')
    require(all((run / 'games' / name).is_file() and not (run / 'games' / name).is_symlink() for name in filenames),
            'REFUSED: nonregular or symlinked game file')
    require(p['budgets'] == list(BUDGETS) and p['batch_seeds'] == list(SEEDS)
            and p['games_per_cell'] == 10 and p['planned_games'] == 720
            and p['identity_directions'] == [d.split('/') for d in DIRECTIONS]
            and p['agent_seed_orientations'] == [list(o) for o in ORIENTATIONS], 'Unexpected preregistered design')
    require(sha256_file(run / 'preregistration.json') == FROZEN_HASHES['experiments/d1_estimation_v1/preregistration.json'],
            'Saved preregistration mismatch')
    check = Comparisons()
    check.compare(manifest, {'batch_id': p['batch_id'], 'kind': p['experiment_id'], 'requested_games': 720,
                            'batch_seed': list(SEEDS), 'board_size': 5, 'komi': 2.5,
                            'code_version': p['code_version'], 'concurrency': 1}, 'manifest')
    analysis_path = run / 'analysis.json'
    analysis_hash = sha256_file(analysis_path)
    analysis = read_json(analysis_path)
    check.compare(analysis, {'experiment_id': p['experiment_id'], 'estimation_only': True, 'n_records': 720}, 'analysis')
    estimates = analysis['estimates']
    check.compare(estimates, {'analysis_version': 'paired-fixed-strata-cp-v1', 'estimation_only': True,
                             'n_records': 720, 'complete_registered_sample': True}, 'estimates')
    family = [{'direction': d, 'endpoint': e, 'comparison_budget': b, 'baseline_budget': 64}
              for d, e in PRIMARY.items() for b in (256, 1024)]
    check.compare(estimates['intervals'], {'confidence_level': .95, 'paired_primary_method': CI_METHOD,
                                        'simultaneous_primary_family_size': 6, 'family': family}, 'estimates.intervals')
    math_check_count = independent_math_checks()
    plan = design_plan(p)
    rows, raw_hashes = [], {}
    for expected, name in zip(plan, filenames):
        path = run / 'games' / name
        raw_hashes[name] = sha256_file(path)
        rows.append(raw_row(read_json(path), expected, check))
    balance = Counter((r['budget'], r['batch_seed'], r['direction'], r['black_seed'], r['white_seed']) for r in rows)
    require(len(balance) == 72 and set(balance.values()) == {10}, 'Full-sample cell imbalance')
    require(len({r['game_seed'] for r in rows}) == 240, 'Nonunique game seeds across registered blocks')
    require(all(len({r['game_seed'] for r in rows if r['block_id'] == block}) == 1
                for block in {r['block_id'] for r in rows}), 'Game seed changes across paired budgets')
    # Match every reported derived row to its independent raw record.
    require(len(analysis['rows']) == 720, 'Reported derived row count mismatch')
    reported_rows = {r['game_index']: r for r in analysis['rows']}
    require(set(reported_rows) == set(range(720)), 'Reported rows duplicate or missing indexes')
    for row in rows:
        i = row['game_index']
        expected = {k: row[k] for k in (*plan[i].keys(), 'game_id', 'actions', 'move_count',
                                        'winner', 'black_utility', 'white_utility') if k != 'direction'}
        expected['routes'] = {'empty_double_pass': bool(row['flags']['empty_double_pass']),
                              'black_one_stone_double_pass': bool(row['flags']['black_one_stone_double_pass']),
                              'all_pass_by_color': {'black': bool(row['flags']['black_realized_all_pass']),
                                                    'white': row['white_all_pass']}}
        check.compare(reported_rows[i], expected, f'analysis.rows[{i}]')
    primary_evidence = {'pooled': {}, 'per_seed': {str(s): {} for s in SEEDS}}
    raw_counts = {'pooled': {}, 'per_seed': {str(s): {} for s in SEEDS}}
    for direction in DIRECTIONS:
        rr = [r for r in rows if r['direction'] == direction]
        result = verify_group(rr, estimates['pooled'][direction], direction, 'estimates.pooled.' + direction, check, True)
        if direction in PRIMARY:
            primary_evidence['pooled'][direction] = result
        for budget in BUDGETS:
            selected = [r for r in rr if r['budget'] == budget]
            counts = {name: sum(r['flags'][name] for r in selected) for name in selected[0]['flags']}
            raw_counts['pooled'].setdefault(str(budget), {})[direction] = {'n': 60, **counts}
            legacy = {k: v for k, v in counts.items() if k not in ('literal_one_stone_a0', 'move_limit')}
            legacy.update(n=60, literal_d0_one_stone_route=counts['literal_one_stone_a0'])
            check.compare(analysis['groups'][str(budget)]['directions'][direction], legacy, f'analysis.groups.{budget}.directions.{direction}')
        for seed in SEEDS:
            sr = [r for r in rr if r['batch_seed'] == seed]
            require(len(sr) == 60, 'Per-seed total across budgets is not 60')
            result = verify_group(sr, estimates['per_seed'][str(seed)][direction], direction,
                                  f'estimates.per_seed.{seed}.{direction}', check)
            if direction in PRIMARY:
                primary_evidence['per_seed'][str(seed)][direction] = result
            for budget in BUDGETS:
                selected = [r for r in sr if r['budget'] == budget]
                counts = {name: sum(r['flags'][name] for r in selected) for name in selected[0]['flags']}
                raw_counts['per_seed'][str(seed)].setdefault(str(budget), {})[direction] = {'n': 20, **counts}
                legacy = {k: v for k, v in counts.items() if k not in ('literal_one_stone_a0', 'move_limit')}
                legacy.update(n=20, literal_d0_one_stone_route=counts['literal_one_stone_a0'])
                check.compare(analysis['groups'][str(budget)]['seeds'][str(seed)][direction], legacy,
                              f'analysis.groups.{budget}.seeds.{seed}.{direction}')
            for sb, sw in ORIENTATIONS:
                ss = [r for r in sr if (r['black_seed'], r['white_seed']) == (sb, sw)]
                label = f'{seed}:{sb},{sw}'
                verify_group(ss, estimates['per_stratum'][label][direction], direction,
                             f'estimates.per_stratum.{label}.{direction}', check)
    # The legacy per-block paired array must also agree with raw trajectories.
    expected_pairs = []
    by_block = {}
    for row in rows:
        by_block.setdefault(row['block_id'], {})[row['budget']] = row
    for block in sorted(by_block):
        aa = by_block[block][64]
        for budget in (256, 1024):
            bb = by_block[block][budget]
            expected_pairs.append({'block_id': block, 'budget': budget, 'baseline_budget': 64,
                                   'length_delta': bb['move_count'] - aa['move_count'],
                                   'black_goal_delta': bb['flags']['black_goals'] - aa['flags']['black_goals'],
                                   'black_all_pass_delta': bb['flags']['black_realized_all_pass'] - aa['flags']['black_realized_all_pass']})
    check.compare(analysis['paired_differences'], expected_pairs, 'analysis.paired_differences', True)
    length_evidence = {'pooled': verify_lengths(rows, estimates['mixed_same_length']['pooled'],
                                               'estimates.mixed_same_length.pooled', check), 'per_seed': {}}
    for seed in SEEDS:
        length_evidence['per_seed'][str(seed)] = verify_lengths([r for r in rows if r['batch_seed'] == seed],
            estimates['mixed_same_length']['per_seed'][str(seed)], f'estimates.mixed_same_length.per_seed.{seed}', check)
    clarification = read_json(repo / 'experiments/d1_estimation_v1/protocol_clarifications.json')
    weighting_note = next(c for c in clarification['clarifications'] if c['topic'] == 'filtered length weighting')
    # Read-only snapshot stability: do not bless mixed versions of run inputs.
    require(sha256_file(manifest_path) == manifest_hash, 'Manifest changed during audit')
    require(sha256_file(analysis_path) == analysis_hash, 'Analysis changed during audit')
    require(all(sha256_file(run / 'games' / name) == digest for name, digest in raw_hashes.items()),
            'Raw game changed during audit')
    return {'audit': 'D1-G0-estimation-v1-independent-final-analysis',
            'status': 'passed' if check.mismatch_count == 0 else 'failed',
            'prepared_from_schema_utc': PREPARED_UTC, 'completed_utc': datetime.now(timezone.utc).isoformat(),
            'python_version': platform.python_version(), 'checker_sha256': sha256_file(__file__),
            'input_hashes': {**FROZEN_HASHES, 'manifest.json': manifest_hash, 'analysis.json': analysis_hash,
                             'raw_game_hash_map_sha256': hashlib.sha256(json.dumps(raw_hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()},
            'completion_gate': {'manifest_status': 'completed', 'saved_games': 720, 'indexes': '0..719',
                                'registered_cells': 72, 'games_per_cell': 10, 'distinct_matched_blocks': 240,
                                'pooled_n_per_budget_direction': 60, 'per_seed_n_per_budget_direction': 20},
            'independence': 'Standard library only; no import of frozen analysis/game package or SciPy. Direct binomial finite sums and bisection; separate area-scoring flood fill.',
            'coverage': 'All14 binary endpoint rates and all3 within-direction budget contrasts, pooled/per-seed/per-orientation; all6 pooled primary simultaneous bounds; raw-derived rows; legacy counts/pairs; full and filtered lengths.',
            'math_self_checks': math_check_count, 'comparison_checks': check.checks,
            'numeric_checks': check.numeric_checks, 'absolute_tolerance': ABS_TOL,
            'maximum_absolute_numeric_difference': check.max_abs_error,
            'mismatch_count': check.mismatch_count, 'mismatches': check.mismatches,
            'primary_results': primary_evidence, 'raw_route_goal_counts': raw_counts,
            'length_sensitivity': length_evidence, 'protocol_weighting_clarification': weighting_note,
            'limitations': ['Independent-stream conditional inference only; fixed agent seeds are not a sampled agent population.',
                            'Marginal95% intervals are not simultaneous; the separately reported six-primary family bounds are.',
                            'Filtered means use actual retained-game weights, may be undefined for empty groups, and are descriptive rather than causal.',
                            'This is a statistical/record audit, not independent legal-move replay or MCTS correctness proof.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--final-analysis-authorized', action='store_true')
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    # No repo/run file is opened without explicit action-time authorization.
    if not args.final_analysis_authorized:
        print(json.dumps({'status': 'refused', 'reason': 'Explicit final-analysis authorization flag required'}))
        return 2
    repo, run, report = args.repo.resolve(), args.run.resolve(), args.report.resolve()
    if report.is_relative_to(repo) or report.is_relative_to(run):
        print(json.dumps({'status': 'refused', 'reason': 'Report must remain outside the frozen repo and run'}))
        return 2
    try:
        result = audit(repo, run, report)
    except (Refused, OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        result = {'audit': 'D1-G0-estimation-v1-independent-final-analysis', 'status': 'refused',
                  'completed_utc': datetime.now(timezone.utc).isoformat(), 'reason': str(error),
                  'checker_sha256': sha256_file(__file__)}
    report.parent.mkdir(parents=True, exist_ok=True)
    # Never replace an earlier audit result silently.
    with report.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'report': str(report),
                      'mismatch_count': result.get('mismatch_count'), 'reason': result.get('reason')}, ensure_ascii=False))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
