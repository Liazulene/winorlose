"""Synthetic tests only: no formal games and no historical output writes."""
import copy
import math

import pytest

from winai_loseai.league.seeds import game_seed_for
from winai_loseai.experiments.g1_pass8_estimation_stats import (
    DIRECTIONS, ORIENTATIONS, PRIMARY_ENDPOINTS, INTERVAL_CONFIDENCE,
    analyze_rows, bounded_mean_interval, planning_precision,
)
from winai_loseai.experiments.d1_estimation_stats import paired_rate_difference


def _protocol(small=False):
    p = {'pass_min_plies': [0, 8], 'budget': 256, 'batch_seeds': [11, 12, 13],
         'identity_directions': [list(d) for d in DIRECTIONS],
         'agent_seed_orientations': [list(o) for o in ORIENTATIONS],
         'games_per_cell': 10, 'planned_games': 480, 'board_size': 5, 'komi': 2.5}
    if small:
        p.update(budget=1, batch_seeds=[80], games_per_cell=1, planned_games=16)
    return p


def _rows(p):
    # These are statistical rows, not purported legal/replayed full games.
    rows = []
    for rule in p['pass_min_plies']:
        for seed in p['batch_seeds']:
            for d, (ib, iw) in enumerate(DIRECTIONS):
                for o, (sb, sw) in enumerate(ORIENTATIONS):
                    for rep in range(p['games_per_cell']):
                        index = (d * 2 + o) * p['games_per_cell'] + rep
                        goal = rule == 8 and sb == 1
                        winner = 'black' if goal == (ib == 'WIN') else 'white'
                        utility = lambda color, identity: 1 if (winner == color) == (identity == 'WIN') else -1
                        actions = [0, 25, 25] if rule == 0 else list(range(8)) + [25, 25]
                        rows.append({'pass_min_ply': rule, 'ruleset': 'G0' if rule == 0 else 'G1-pass8',
                                     'budget': p['budget'], 'batch_seed': seed,
                                     'black_identity': ib, 'white_identity': iw,
                                     'black_seed': sb, 'white_seed': sw, 'replicate': rep,
                                     'block_index': index, 'block_id': f'{seed}:{index}',
                                     'game_seed': game_seed_for(seed, index),
                                     'actions': actions, 'move_count': len(actions),
                                     'extra_length': len(actions) - rule - 2,
                                     'winner': winner, 'black_utility': utility('black', ib),
                                     'white_utility': utility('white', iw), 'termination_reason': 'double_pass'})
    return rows


def test_complete_formal_analysis_pairing_counts_family_and_no_mutation():
    p = _protocol()
    rows = _rows(p)
    original_rows, original_p = copy.deepcopy(rows), copy.deepcopy(p)
    result = analyze_rows(reversed(rows), p)
    assert rows == original_rows and p == original_p
    assert result['complete_registered_sample']
    assert result['n_records'] == 480 and result['n_paired_blocks'] == 240
    family = result['intervals']['family']
    assert result['intervals']['simultaneous_family_size'] == len(family) == 8
    assert {(f['direction'], f['endpoint']) for f in family} == {
        (d, e) for d, g in PRIMARY_ENDPOINTS.items() for e in (g, 'raw_length')}
    adjusted_count = 0
    for direction, endpoint in PRIMARY_ENDPOINTS.items():
        group = result['pooled'][direction]
        assert group['n_pairs'] == 60
        goals = group['contrast']['rates'][endpoint]
        assert goals['n'] == 60 and goals['estimate'] == .5
        assert goals['n01'] == 30 and goals['n10'] == 0
        assert goals['simultaneous_family_interval_confidence_level'] == INTERVAL_CONFIDENCE
        assert goals['simultaneous_family_component_confidence_level'] == 1 - .05 / 16
        for name, rate in group['contrast']['rates'].items():
            if 'simultaneous_family_ci95' in rate:
                assert name == endpoint
                adjusted_count += 1
        for arm in ('G0', 'G1-pass8'):
            assert group['rules'][arm]['n'] == 60
            assert all('simultaneous_family_ci95' not in rate for rate in group['rules'][arm]['rates'].values())
        raw, extra = group['contrast']['raw_length'], group['contrast']['extra_length']
        assert raw['estimate'] == 7 and extra['estimate'] == -1
        assert raw['unclipped_radius'] == pytest.approx(32.962068531647475)
        assert raw['simultaneous_family_unclipped_radius'] == pytest.approx(41.218476568497685)
        assert extra['ci'] == [v - 8 for v in raw['ci']]
        assert extra['simultaneous_family_ci95'] == [v - 8 for v in raw['simultaneous_family_ci95']]
        assert extra['support'] == [-98, 90] and not extra['is_additional_family_member']
        adjusted_count += 1
        for seed in p['batch_seeds']:
            sr = result['per_seed'][str(seed)][direction]
            assert sr['n_pairs'] == 20
            assert sr['contrast']['rates'][endpoint]['estimate'] == .5
            assert 'simultaneous_family_ci95' not in sr['contrast']['rates'][endpoint]
            assert 'simultaneous_family_ci95' not in sr['contrast']['raw_length']
            assert sr['contrast']['raw_length']['unclipped_radius'] == pytest.approx(57.09197741938069)
    assert adjusted_count == 8


def test_small_balanced_protocol_accepted_and_pooling_is_equal_seed_weight():
    p = _protocol(True)
    result = analyze_rows(_rows(p), p)
    assert result['n_records'] == 16
    assert result['pooled']['WIN/WIN']['n_pairs'] == 2
    p = _protocol()
    rows = _rows(p)
    # G1 goal success only in seed11. Every direction must pool to1/3.
    for r in rows:
        if r['pass_min_ply'] == 8:
            success = r['batch_seed'] == 11
            r['winner'] = 'black' if success == (r['black_identity'] == 'WIN') else 'white'
            for c in ('black', 'white'):
                r[c + '_utility'] = 1 if (r['winner'] == c) == (r[c + '_identity'] == 'WIN') else -1
    result = analyze_rows(rows, p)
    for d, e in PRIMARY_ENDPOINTS.items():
        assert result['pooled'][d]['contrast']['rates'][e]['estimate'] == pytest.approx(1 / 3)


def test_goal_complements_and_mixed_goals_are_not_independent_trials():
    result = analyze_rows(_rows(_protocol()), _protocol())
    for direction in ('WIN/WIN', 'LOSE/LOSE'):
        rates = result['pooled'][direction]['contrast']['rates']
        black, white = rates['black_goals'], rates['white_goals']
        assert black['estimate'] == -white['estimate']
        assert black['ci'] == pytest.approx([-white['ci'][1], -white['ci'][0]])
        assert 'joint_goals' not in rates
    for direction in ('WIN/LOSE', 'LOSE/WIN'):
        rates = result['pooled'][direction]['contrast']['rates']
        for endpoint in ('black_goals', 'white_goals'):
            assert rates[endpoint]['n'] == rates['joint_goals']['n'] == 60
            assert rates[endpoint]['ci'] == rates['joint_goals']['ci']


@pytest.mark.parametrize('values,lo,hi,confidence', [([], 0, 1, .95), ([True], 0, 1, .95),
    ([float('nan')], 0, 1, .95), ([2], 0, 1, .95), ([0], 1, 1, .95),
    ([0], 0, 1, True), ([0], 0, 1, 1), ([0], 0, float('inf'), .95)])
def test_bounded_mean_rejects_invalid_data(values, lo, hi, confidence):
    with pytest.raises(ValueError):
        bounded_mean_interval(values, lo, hi, confidence)


def test_hoeffding_formula_clipping_and_constant_nonzero_uncertainty():
    for confidence in (.95, INTERVAL_CONFIDENCE):
        radius = 188 * math.sqrt(math.log(2 / (1 - confidence)) / 120)
        zero = bounded_mean_interval([0] * 60, -90, 98, confidence)
        assert zero['ci'] == pytest.approx([-radius, radius])
        assert bounded_mean_interval([-90] * 60, -90, 98, confidence)['ci'] == pytest.approx([-90, -90 + radius])
        assert bounded_mean_interval([98] * 60, -90, 98, confidence)['ci'] == pytest.approx([98 - radius, 98])


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'seed', 'both_pair_seeds', 'block_id',
    'block_index', 'cross_direction_seed', 'replicate', 'boolean_key', 'budget', 'rule_name',
    'early_pass', 'length', 'utility_bool', 'utility_wrong', 'draw', 'extra', 'termination',
    'early_doublepass', 'missing_field'])
def test_fail_closed_on_incomplete_invalid_or_mispaired_sample(damage):
    p = _protocol(True)
    rows = _rows(p)
    r = rows[-1]
    if damage == 'missing': rows.pop()
    elif damage == 'duplicate': rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'seed': r['game_seed'] += 1
    elif damage == 'both_pair_seeds':
        for rr in rows:
            if rr['block_id'] == r['block_id']: rr['game_seed'] += 1
    elif damage == 'block_id': r['block_id'] += 'x'
    elif damage == 'block_index': r['block_index'] += 1
    elif damage == 'cross_direction_seed': r['game_seed'] = rows[-3]['game_seed']
    elif damage == 'replicate': r['replicate'] = 1
    elif damage == 'boolean_key': r['pass_min_ply'] = True
    elif damage == 'budget': r['budget'] += 1
    elif damage == 'rule_name': r['ruleset'] = 'G0'
    elif damage == 'early_pass': r['actions'][7] = 25
    elif damage == 'length': r['move_count'] += 1
    elif damage == 'utility_bool': r['black_utility'] = True
    elif damage == 'utility_wrong': r['black_utility'] *= -1
    elif damage == 'draw': r['winner'] = 'draw'
    elif damage == 'extra': r['extra_length'] += 1
    elif damage == 'termination': r['termination_reason'] = 'move_limit'
    elif damage == 'early_doublepass':
        r['actions'] += [0]
        r['move_count'] += 1
        r['extra_length'] += 1
    else: del r['block_id']
    with pytest.raises(ValueError): analyze_rows(rows, p)


def test_terminal_precedence_at100_and_correct_length_support():
    p = _protocol(True)
    rows = _rows(p)
    for r in rows:
        r['actions'] = [i % 25 for i in range(98)] + [25, 25]
        r['move_count'] = 100
        r['extra_length'] = 98 - r['pass_min_ply']
    result = analyze_rows(rows, p)
    assert result['pooled']['WIN/WIN']['contrast']['raw_length']['estimate'] == 0
    rows[-1]['termination_reason'] = 'move_limit'
    with pytest.raises(ValueError): analyze_rows(rows, p)


def test_precision_enumeration_and_nonzero_boundary_intervals():
    result = planning_precision(60)
    assert result['feasible_discordance_count_combinations'] == 1891
    adjusted = result['joint_family8_95']
    assert adjusted['goal_all_concordant_ci'] == pytest.approx([-.10209511614447087, .10209511614447087])
    assert adjusted['goal_maximum_full_width'] == pytest.approx(.7631904840310405)
    assert adjusted['goal_full_width_maximizers_nplus_nminus'] == [[30, 30]]
    assert result['pointwise95']['goal_maximum_full_width'] == pytest.approx(.5958239725885787)
    assert result['marginal_rate_all_success_pointwise95_ci'] == pytest.approx([.9403705077138331, 1])
    for n in (20, 60):
        bound = 1 - (.05 / 4) ** (1 / n)
        actual = paired_rate_difference([1] * n, [1] * n)
        assert actual['ci'] == pytest.approx([-bound, bound])
        assert planning_precision(n)['pointwise95']['goal_all_concordant_ci'] == pytest.approx(actual['ci'])


@pytest.mark.parametrize('bad', [0, -1, True, 20.0])
def test_precision_rejects_invalid_n(bad):
    with pytest.raises(ValueError): planning_precision(bad)


@pytest.mark.parametrize('key,value', [('pass_min_plies', [False, 8]), ('pass_min_plies', [0., 8]),
    ('budget', True), ('batch_seeds', [True]), ('batch_seeds', [80, 80]),
    ('board_size', 5.), ('planned_games', 16.), ('games_per_cell', True)])
def test_protocol_types_and_balance_are_strict(key, value):
    p = _protocol(True)
    rows = _rows(p)
    p[key] = value
    with pytest.raises(ValueError): analyze_rows(rows, p)
