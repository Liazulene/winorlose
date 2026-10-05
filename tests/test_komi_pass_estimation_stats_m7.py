"""Synthetic statistical rows only: never produce or modify formal games."""
import copy
import itertools
import json
import math

import pytest
from scipy.stats import t

from winai_loseai.league.seeds import game_seed_for
from winai_loseai.experiments.komi_pass_estimation_stats import (
    ARMS, CONTRASTS, DIRECTIONS, ORIENTATIONS, FAMILY_SIZE, INTERVAL_CONFIDENCE,
    analyze_rows, bounded_mean_interval, planned_precision, stratified_t_sensitivity,
)
from winai_loseai.experiments.d1_estimation_stats import clopper_pearson, paired_rate_difference


def _protocol(small=False):
    p = {'pass_min_plies': [0, 8], 'komis': [2.5, 0.0], 'budget': 256,
         'batch_seeds': [17, 18, 19], 'identity_directions': [list(d) for d in DIRECTIONS],
         'agent_seed_orientations': [list(o) for o in ORIENTATIONS],
         'games_per_cell': 10, 'planned_games': 960, 'board_size': 5}
    if small:
        p.update(budget=1, batch_seeds=[80], games_per_cell=1, planned_games=32)
    return p


def _set_outcome(row, black_goal, draw=False):
    row['winner'] = ('draw' if draw else
                     'black' if black_goal == (row['black_identity'] == 'WIN') else 'white')
    for color in ('black', 'white'):
        row[color + '_utility'] = (0 if draw else
            1 if (row['winner'] == color) == (row[color + '_identity'] == 'WIN') else -1)


def _rows(p):
    # Statistical-row fixtures are not represented as legal/replayed games.
    rows = []
    for rule, komi in ARMS:
        for seed in p['batch_seeds']:
            for di, (ib, iw) in enumerate(DIRECTIONS):
                for oi, (sb, sw) in enumerate(ORIENTATIONS):
                    for rep in range(p['games_per_cell']):
                        index = (di * 2 + oi) * p['games_per_cell'] + rep
                        actions = [0, 25, 25] if rule == 0 else list(range(8)) + [25, 25]
                        row = {'pass_min_ply': rule, 'komi': komi, 'ruleset': ARMS[rule, komi],
                               'budget': p['budget'], 'batch_seed': seed,
                               'black_identity': ib, 'white_identity': iw,
                               'black_seed': sb, 'white_seed': sw, 'replicate': rep,
                               'identity_index': di, 'orientation_index': oi,
                               'block_index': index, 'block_id': f'{seed}:{index}',
                               'game_seed': game_seed_for(seed, index), 'actions': actions,
                               'move_count': len(actions), 'extra_length': len(actions) - rule - 2,
                               'termination_reason': 'double_pass'}
                        success = komi == 2.5 or (sb == 1 if rule == 0 else seed == p['batch_seeds'][0])
                        _set_outcome(row, success, draw=komi == 0 and rule == 0 and not success)
                        rows.append(row)
    return rows


@pytest.fixture(scope='module')
def formal_result():
    p = _protocol()
    rows = _rows(p)
    before = copy.deepcopy(rows), copy.deepcopy(p)
    result = analyze_rows(reversed(rows), p)
    assert (rows, p) == before
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    return result


def test_exact_three_member_family_denominators_and_signs(formal_result):
    r = formal_result
    assert r['n_records'] == 960 and r['n_quartets'] == 240
    assert r['complete_registered_sample'] and r['estimation_only']
    assert r['intervals']['simultaneous_family_size'] == FAMILY_SIZE == 3
    assert list(r['primary_family']) == list(CONTRASTS)
    assert len(r['intervals']['family']) == 3
    expected = (-.5, -2 / 3, -1 / 6)
    for name, value in zip(CONTRASTS, expected):
        endpoint = r['primary_family'][name]
        assert endpoint['n'] == 60 and endpoint['estimate'] == pytest.approx(value)
        assert endpoint['confidence_level'] == INTERVAL_CONFIDENCE
        assert endpoint['simultaneous_family_confidence_level'] == .95
        assert endpoint['simultaneous_family_ci95'] == endpoint['ci']
        assert endpoint['identity_direction'] == 'LOSE/LOSE' and endpoint['endpoint'] == 'black_goals'
    delta0, delta8, interaction = [r['primary_family'][c] for c in CONTRASTS]
    assert (delta0['n00'], delta0['n01'], delta0['n10'], delta0['n11']) == (0, 0, 30, 30)
    assert (delta8['n00'], delta8['n01'], delta8['n10'], delta8['n11']) == (0, 0, 40, 20)
    assert delta0['component_confidence_level'] == pytest.approx(1 - .05 / 6)
    assert interaction['support'] == [-2, 2]
    assert interaction['unclipped_radius'] == pytest.approx(.7989569652809462)
    assert sum(interaction['value_counts'].values()) == 60


def test_secondary_cells_keep_full_n_and_never_receive_family_ci(formal_result):
    r = formal_result
    for direction in ('WIN/WIN', 'LOSE/LOSE', 'WIN/LOSE', 'LOSE/WIN'):
        assert r['pooled'][direction]['n_quartets'] == 60
        assert r['pooled'][direction]['n_per_arm'] == 60
        for arm in ARMS.values():
            cell = r['pooled'][direction]['arms'][arm]
            assert cell['n'] == 60
            rates = cell['rates']
            assert all(rate['n'] == 60 for rate in rates.values())
            assert all(rate['coverage_scope'] == 'pointwise95_not_family_adjusted' for rate in rates.values())
            assert rates['black_board_wins']['successes'] + rates['white_board_wins']['successes'] + rates['draws']['successes'] == 60
            assert all(sum(counts.values()) == 60 for counts in cell['utility_counts'].values())
        for seed in (17, 18, 19):
            assert r['per_seed'][str(seed)][direction]['n_per_arm'] == 20
            for sb, sw in ORIENTATIONS:
                assert r['per_stratum'][f'{seed}:{sb},{sw}'][direction]['n_per_arm'] == 10
    for panel in ('pooled', 'per_seed', 'per_stratum', 'approximate_sensitivity'):
        assert 'simultaneous_family_ci95' not in json.dumps(r[panel])


def test_draw_goal_and_utility_semantics_not_complements(formal_result):
    for direction in ('WIN/WIN', 'LOSE/LOSE'):
        cell = formal_result['pooled'][direction]['arms']['G1-k0']
        assert cell['rates']['black_goals']['successes'] == 30
        assert cell['rates']['white_goals']['successes'] == 0
        assert cell['rates']['draws']['successes'] == 30
        assert cell['utility_counts']['black'] == {'-1': 0, '0': 30, '1': 30}
        assert cell['utility_counts']['white'] == {'-1': 30, '0': 30, '1': 0}
    for direction in ('WIN/LOSE', 'LOSE/WIN'):
        rates = formal_result['pooled'][direction]['arms']['G1-k0']['rates']
        assert rates['joint_goals']['n'] == rates['black_goals']['n'] == rates['white_goals']['n'] == 60
        assert rates['joint_goals']['successes'] == rates['black_goals']['successes'] == rates['white_goals']['successes'] == 30


def test_small_protocol_and_fixed_stratum_equal_weight():
    p = _protocol(True)
    result = analyze_rows(_rows(p), p)
    assert result['n_records'] == 32 and result['n_quartets'] == 8
    assert result['primary_family'][CONTRASTS[0]]['n'] == 2
    for v in result['approximate_sensitivity'].values():
        assert v['n_fixed_strata'] == 2 and v['ci'] is None
        assert v['status'] == 'unavailable_insufficient_within_stratum_replication'


@pytest.mark.parametrize('sign', (-1, 1))
def test_interaction_preserves_full_plusminus2_support(sign):
    p = _protocol()
    rows = _rows(p)
    for row in rows:
        # sign=+1 gives delta0=-1, delta8=+1; reverse for sign=-1.
        success = ((row['pass_min_ply'] == 0) == (row['komi'] == 2.5)) == (sign == 1)
        _set_outcome(row, success)
    result = analyze_rows(rows, p)['primary_family'][CONTRASTS[2]]
    assert result['estimate'] == 2 * sign
    assert result['value_counts'][str(2 * sign)] == 60
    if sign == 1:
        assert 1 < result['ci'][0] < result['ci'][1] == 2
    else:
        assert -2 == result['ci'][0] < result['ci'][1] < -1


def test_all_concordant_interaction_never_zero_width():
    result = bounded_mean_interval([0] * 60, -2, 2, INTERVAL_CONFIDENCE)
    assert result['ci'] == pytest.approx([-.7989569652809462, .7989569652809462])
    paired = paired_rate_difference([1] * 60, [1] * 60, INTERVAL_CONFIDENCE)
    assert paired['ci'] == pytest.approx([-.08729629680021657, .08729629680021657])


def test_quartet_covariance_used_for_interaction_and_no_arm_independence():
    p = _protocol()
    rows = _rows(p)
    # Both komi effects fluctuate identically, making every interaction zero.
    for row in rows:
        _set_outcome(row, row['komi'] == 2.5 or row['replicate'] % 2 == 0)
    result = analyze_rows(rows, p)
    primary = result['primary_family']
    assert primary[CONTRASTS[0]]['estimate'] == primary[CONTRASTS[1]]['estimate'] == -.5
    assert primary[CONTRASTS[2]]['value_counts']['0'] == 60
    sensitivity = result['approximate_sensitivity']
    assert sensitivity[CONTRASTS[0]]['standard_error'] > 0
    assert sensitivity[CONTRASTS[2]]['status'] == 'unavailable_zero_estimated_variance'
    assert sensitivity[CONTRASTS[2]]['ci'] is None


def test_satterthwaite_sensitivity_formula_fixed_strata_and_zero_handling():
    strata = {f's{i}': [-1, 1] * 5 for i in range(6)}
    result = stratified_t_sensitivity(strata, -1, 1)
    assert result['status'] == 'approximation_only'
    assert result['exact_coverage_claim'] is False
    assert result['n_fixed_strata'] == 6 and result['n'] == 60
    assert result['degrees_of_freedom'] == pytest.approx(54)
    assert result['standard_error'] == pytest.approx(math.sqrt(1 / 54))
    radius = t.ppf(1 - .05 / 6, 54) / math.sqrt(54)
    assert result['ci'] == pytest.approx([-radius, radius])
    unequal = stratified_t_sensitivity({'a': [-1, 1], 'b': [1] * 20}, -1, 1)
    assert unequal['estimate'] == .5  # Equal strata, not equal records.
    assert unequal['degrees_of_freedom'] == pytest.approx(1)
    constant = stratified_t_sensitivity({'a': [1] * 10, 'b': [-1] * 10}, -1, 1)
    assert constant['estimate'] == 0 and constant['ci'] is None
    assert constant['status'] == 'unavailable_zero_estimated_variance'


@pytest.mark.parametrize('strata,lower,upper,confidence', [
    ({}, -1, 1, .95), ({'a': []}, -1, 1, .95), ({'a': [True, False]}, -1, 1, .95),
    ({'a': [float('nan')]}, -1, 1, .95), ({'a': [2]}, -1, 1, .95),
    ({'a': [0]}, 1, 1, .95), ({'a': [0]}, -1, 1, True), ({'a': [0]}, -1, 1, 1),
])
def test_invalid_approximate_sensitivity_rejected(strata, lower, upper, confidence):
    with pytest.raises(ValueError):
        stratified_t_sensitivity(strata, lower, upper, confidence)


@pytest.mark.parametrize('damage', [
    'missing', 'duplicate', 'seed', 'all_four_seeds', 'block_id', 'block_index',
    'identity_index', 'orientation_index', 'replicate', 'boolean_rule', 'boolean_komi',
    'budget', 'ruleset', 'early_pass', 'length', 'utility_bool', 'utility_float',
    'utility_wrong', 'draw_komi2p5', 'draw_utility', 'extra', 'termination',
    'early_doublepass', 'missing_field', 'unknown_identity', 'nan_komi',
])
def test_complete_registered_design_fails_closed(damage):
    p = _protocol(True)
    rows = _rows(p)
    r = rows[-1]
    if damage == 'missing': rows.pop()
    elif damage == 'duplicate': rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'seed': r['game_seed'] += 1
    elif damage == 'all_four_seeds':
        for rr in rows:
            if rr['block_id'] == r['block_id']: rr['game_seed'] += 1
    elif damage in ('block_index', 'identity_index', 'orientation_index', 'replicate'): r[damage] += 1
    elif damage == 'block_id': r['block_id'] += 'x'
    elif damage == 'boolean_rule': r['pass_min_ply'] = False
    elif damage == 'boolean_komi': r['komi'] = False
    elif damage == 'budget': r['budget'] += 1
    elif damage == 'ruleset': r['ruleset'] = 'G0'
    elif damage == 'early_pass': r['actions'][7] = 25
    elif damage == 'length': r['move_count'] += 1
    elif damage == 'utility_bool': r['black_utility'] = True
    elif damage == 'utility_float': r['black_utility'] = float(r['black_utility'])
    elif damage == 'utility_wrong': r['black_utility'] *= -1
    elif damage == 'draw_komi2p5': _set_outcome(rows[0], False, draw=True)
    elif damage == 'draw_utility':
        _set_outcome(r, False, draw=True)
        r['black_utility'] = 1
    elif damage == 'extra': r['extra_length'] += 1
    elif damage == 'termination': r['termination_reason'] = 'move_limit'
    elif damage == 'early_doublepass':
        r['actions'].append(0)
        r['move_count'] += 1
        r['extra_length'] += 1
    elif damage == 'missing_field': del r['game_seed']
    elif damage == 'unknown_identity': r['black_identity'] = 'OTHER'
    else: r['komi'] = float('nan')
    with pytest.raises(ValueError):
        analyze_rows(rows, p)


@pytest.mark.parametrize('key,value', [
    ('pass_min_plies', [False, 8]), ('pass_min_plies', [0., 8]), ('komis', [2.5, False]),
    ('komis', [0.0, 2.5]), ('budget', True), ('batch_seeds', [80, 80]),
    ('batch_seeds', [True]), ('games_per_cell', True), ('board_size', 5.),
    ('planned_games', 32.), ('agent_seed_orientations', [[True, 2], [2, True]]),
])
def test_protocol_type_and_design_mutations_rejected(key, value):
    p = _protocol(True)
    rows = _rows(p)
    p[key] = value
    with pytest.raises(ValueError):
        analyze_rows(rows, p)


def test_terminal_precedence_and_cheap_endpoints_are_recomputed():
    p = _protocol(True)
    rows = _rows(p)
    for r in rows:
        r['actions'] = [i % 25 for i in range(98)] + [25, 25]
        r['move_count'] = 100
        r['extra_length'] = 98 - r['pass_min_ply']
        r['routes'] = {'empty_double_pass': True}  # Deliberately stale unused cached field.
    result = analyze_rows(rows, p)
    for arm in result['pooled']['LOSE/LOSE']['arms'].values():
        assert arm['rates']['empty_double_pass']['successes'] == 0
        assert arm['rates']['move_limit']['successes'] == 0
        assert arm['rates']['length_ge60']['successes'] == arm['n']
    rows[-1]['termination_reason'] = 'move_limit'
    with pytest.raises(ValueError):
        analyze_rows(rows, p)


@pytest.mark.parametrize('n,halfwidth,distance,radius', [
    (48, .14774836944665626, .15149423935322404, .8932610427325676),
    (54, .13919003161499266, .14232335979001537, .8421745875812865),
    (60, .13193796805756308, .1345945626885724, .7989569652809462),
    (66, .12569283054844502, .12797252735050263, .7617755768125718),
])
def test_effect_independent_precision_numbers(n, halfwidth, distance, radius):
    result = planned_precision(n)
    assert result['marginal_rate_pointwise95']['maximum_half_full_width'] == pytest.approx(halfwidth)
    assert result['marginal_rate_pointwise95']['maximum_distance_from_estimate'] == pytest.approx(distance)
    assert result['joint_family3_95']['interaction_unclipped_radius'] == pytest.approx(radius)
    assert result['feasible_discordance_count_combinations'] == (n + 1) * (n + 2) // 2


def test_family_precision_exhaustive_discordance_and_boundary_limits():
    result = planned_precision(60)
    primary = result['joint_family3_95']
    assert primary['goal_maximum_full_width'] == pytest.approx(.68988516564197)
    assert primary['goal_maximum_distance_from_estimate'] == pytest.approx(.3560441111835191)
    assert primary['goal_width_maximizers_nplus_nminus'] == [[30, 30]]
    assert primary['goal_all_concordant_ci'] == pytest.approx([-.08729629680021657, .08729629680021657])
    assert result['marginal_rate_pointwise95']['all_success_ci'] == pytest.approx([.9403705077138331, 1])
    assert result['pointwise95']['goal_maximum_full_width'] == pytest.approx(.595823972588579)


@pytest.mark.parametrize('n', (0, -1, True, 60., '60'))
def test_precision_invalid_n_rejected(n):
    with pytest.raises(ValueError): planned_precision(n)


def test_two_sided_cp_heterogeneous_average_finite_enumeration():
    # Exact Poisson-binomial mass convolution, no stochastic coverage simulation.
    # This check is illustrative numerical verification, not the theorem's proof.
    for probabilities in itertools.product((0., .05, .5, .95, 1.), repeat=4):
        mass = [1.]
        for probability in probabilities:
            nxt = [0.] * (len(mass) + 1)
            for k, value in enumerate(mass):
                nxt[k] += value * (1 - probability)
                nxt[k + 1] += value * probability
            mass = nxt
        mean = sum(probabilities) / len(probabilities)
        for confidence in (.5, .95, 1 - .05 / 6):
            coverage = sum(prob for k, prob in enumerate(mass)
                           if clopper_pearson(k, 4, confidence)[0] <= mean <= clopper_pearson(k, 4, confidence)[1])
            assert coverage + 1e-12 >= confidence
