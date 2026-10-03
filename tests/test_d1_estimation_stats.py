"""Finite-sample boundary, heterogeneity, pairing, and fixed-design tests."""
import copy
import itertools
import math

import pytest
from scipy.stats import binomtest

from winai_loseai.experiments.d1_estimation_stats import (
    PRIMARY_ENDPOINTS, analyze_rows, clopper_pearson, paired_rate_difference,
)


@pytest.mark.parametrize('n', [1, 2, 10, 20, 60])
@pytest.mark.parametrize('confidence', [.5, .95, .975, 1 - .05 / 12])
def test_cp_matches_official_scipy_exact(n, confidence):
    for k in range(n + 1):
        expected = binomtest(k, n, alternative='two-sided').proportion_ci(confidence, method='exact')
        observed = clopper_pearson(k, n, confidence)
        assert observed == pytest.approx(expected, abs=2e-12)
        assert 0 <= observed[0] <= k / n <= observed[1] <= 1


@pytest.mark.parametrize('n', [20, 60])
@pytest.mark.parametrize('kind', ['zero', 'one', 'mixed'])
def test_all_concordant_is_nonzero_width(n, kind):
    values = {'zero': [0] * n, 'one': [1] * n, 'mixed': [0, 1] * (n // 2)}[kind]
    result = paired_rate_difference(values, values)
    bound = 1 - .0125 ** (1 / n)
    assert result['estimate'] == 0
    assert result['discordant_pairs'] == 0
    assert result['ci95'] == pytest.approx([-bound, bound])
    assert result['ci95'][0] < 0 < result['ci95'][1]
    assert result['hoeffding_radius'] == pytest.approx(math.sqrt(2 * math.log(40) / n))


@pytest.mark.parametrize('n', [1, 20, 60])
def test_all_positive_negative_and_complement_symmetry(n):
    positive = paired_rate_difference([0] * n, [1] * n)
    negative = paired_rate_difference([1] * n, [0] * n)
    bound = 2 * .0125 ** (1 / n) - 1
    assert positive['estimate'] == 1
    assert positive['ci95'] == pytest.approx([bound, 1])
    assert negative['estimate'] == -1
    assert negative['ci95'] == pytest.approx([-1, -bound])


def test_pairing_matters_even_with_identical_marginal_counts():
    concordant = paired_rate_difference([0] * 30 + [1] * 30, [0] * 30 + [1] * 30)
    discordant = paired_rate_difference([0] * 30 + [1] * 30, [1] * 30 + [0] * 30)
    assert concordant['estimate'] == discordant['estimate'] == 0
    assert concordant['ci95'][1] < discordant['ci95'][1]
    assert discordant['n01'] == discordant['n10'] == 30


def test_asymmetric_reversal_and_simultaneous_interval_nesting():
    aa, bb = [0] * 40 + [1] * 20, [1] * 15 + [0] * 35 + [1] * 10
    ab = paired_rate_difference(aa, bb)
    ba = paired_rate_difference(bb, aa)
    assert ba['estimate'] == -ab['estimate']
    assert ba['ci95'] == pytest.approx([-ab['ci95'][1], -ab['ci95'][0]])
    adjusted = paired_rate_difference(aa, bb, 1 - .05 / 6)
    assert adjusted['ci'][0] <= ab['ci95'][0] <= ab['ci95'][1] <= adjusted['ci'][1]


@pytest.mark.parametrize('k,n,c', [(-1, 10, .95), (11, 10, .95), (0, 0, .95),
                                   (True, 2, .95), (1, 2.0, .95), (1, 2, .49),
                                   (1, 2, 1), (1, 2, float('nan'))])
def test_cp_rejects_invalid_inputs(k, n, c):
    with pytest.raises(ValueError):
        clopper_pearson(k, n, c)


def test_warm_cache_does_not_bypass_strict_types():
    clopper_pearson(1, 1)
    for k, n in [(True, 1), (1, True), (1.0, 1), (1, 1.0)]:
        with pytest.raises(ValueError):
            clopper_pearson(k, n)


@pytest.mark.parametrize('aa,bb', [([], []), ([0], []), ([0], [0, 1]),
                                  ([2], [0]), ([None], [0]), ([.0], [0])])
def test_pair_input_validation(aa, bb):
    with pytest.raises(ValueError):
        paired_rate_difference(aa, bb)


def _poisson_binomial(probabilities):
    pmf = [1.]
    for p in probabilities:
        updated = [0.] * (len(pmf) + 1)
        for k, value in enumerate(pmf):
            updated[k] += value * (1 - p)
            updated[k + 1] += value * p
        pmf = updated
    return pmf


def test_cp_average_probability_coverage_nonidentical_exact_enumeration():
    # Exact finite-state evaluation, not Monte Carlo or an iid-only test.
    # Include heterogeneity concentrated in one nearly-boundary trial.
    for probabilities in itertools.product([0, .001, .0249, .2, .5, .9, .999, 1], repeat=4):
        mean = sum(probabilities) / 4
        for confidence in (.5, .95, .975):
            coverage = sum(mass for k, mass in enumerate(_poisson_binomial(probabilities))
                           if clopper_pearson(k, 4, confidence)[0] - 1e-14 <= mean
                           <= clopper_pearson(k, 4, confidence)[1] + 1e-14)
            assert coverage >= confidence - 1e-12


def _discordance_pmf(probabilities):
    pmf = {(0, 0): 1.}
    for positive, negative in probabilities:
        updated = {}
        for (b, c), mass in pmf.items():
            for key, chance in (((b + 1, c), positive), ((b, c + 1), negative),
                                ((b, c), 1 - positive - negative)):
                updated[key] = updated.get(key, 0) + mass * chance
        pmf = updated
    return pmf


def test_paired_ci_coverage_nonidentical_exact_enumeration():
    choices = [(0, 0), (1, 0), (0, 1), (.006, .012), (.1, .8), (.4, .4)]
    intervals = {}
    for b in range(5):
        for c in range(5 - b):
            aa = [0] * b + [1] * c + [0] * (4 - b - c)
            bb = [1] * b + [0] * c + [0] * (4 - b - c)
            intervals[b, c] = paired_rate_difference(aa, bb)['ci95']
    for probabilities in itertools.product(choices, repeat=4):
        delta = sum(b - c for b, c in probabilities) / 4
        coverage = sum(mass for key, mass in _discordance_pmf(probabilities).items()
                       if intervals[key][0] - 1e-14 <= delta <= intervals[key][1] + 1e-14)
        assert coverage >= .95 - 1e-12


def _protocol(small=False):
    p = {'budgets': [64, 256, 1024], 'batch_seeds': [5, 6, 7],
         'identity_directions': [['WIN', 'WIN'], ['LOSE', 'LOSE'], ['WIN', 'LOSE'], ['LOSE', 'WIN']],
         'agent_seed_orientations': [[1, 2], [2, 1]], 'games_per_cell': 10,
         'planned_games': 720}
    if small:
        p.update(budgets=[1, 3], batch_seeds=[5], games_per_cell=1, planned_games=16)
    return p


def _rows(p):
    rows = []
    for budget in p['budgets']:
        for seed in p['batch_seeds']:
            for d, (ib, iw) in enumerate(p['identity_directions']):
                for o, (sb, sw) in enumerate(p['agent_seed_orientations']):
                    for rep in range(p['games_per_cell']):
                        success = budget != p['budgets'][0] and (budget == p['budgets'][-1] or sb == 1)
                        actions = [0, 1, 25, 25]
                        if success:
                            actions = [7, 25, 25] if (ib, iw) == ('WIN', 'LOSE') else [25, 25]
                        index = (d * 2 + o) * p['games_per_cell'] + rep
                        winner = 'black' if actions == [7, 25, 25] else 'white'
                        utility = lambda color, identity: 1 if (winner == color) == (identity == 'WIN') else -1
                        rows.append({'budget': budget, 'batch_seed': seed, 'black_identity': ib,
                                     'white_identity': iw, 'black_seed': sb, 'white_seed': sw,
                                     'replicate': rep, 'block_id': f'{seed}:{index}',
                                     'game_seed': seed * 10000 + index,
                                     'actions': actions, 'move_count': len(actions), 'winner': winner,
                                     'black_utility': utility('black', ib), 'white_utility': utility('white', iw),
                                     'termination_reason': 'double_pass'})
    return rows


def test_formal_balanced_analysis_counts_pairing_weights_and_no_mutation():
    p = _protocol()
    rows = _rows(p)
    original = copy.deepcopy(rows)
    result = analyze_rows(reversed(rows), p)
    assert rows == original
    assert result['n_records'] == 720
    assert result['intervals']['simultaneous_primary_family_size'] == 6
    assert len(result['intervals']['family']) == 6
    assert len(result['per_stratum']) == 6
    for direction, endpoint in PRIMARY_ENDPOINTS.items():
        pooled = result['pooled'][direction]
        assert pooled['n_per_budget'] == 60
        medium = pooled['contrasts']['256-64']['rates'][endpoint]
        deep = pooled['contrasts']['1024-64']['rates'][endpoint]
        assert medium['n'] == 60 and medium['estimate'] == .5 and medium['n01'] == 30
        assert deep['estimate'] == 1 and deep['n01'] == 60
        secondary = pooled['contrasts']['1024-256']['rates'][endpoint]
        assert secondary['estimate'] == .5
        assert 'simultaneous_primary_ci95' not in secondary
        assert medium['simultaneous_primary_ci95'][0] <= medium['ci95'][0]
        assert medium['simultaneous_primary_ci95'][1] >= medium['ci95'][1]
        for seed in p['batch_seeds']:
            single = result['per_seed'][str(seed)][direction]
            assert single['n_per_budget'] == 20
            assert single['contrasts']['256-64']['rates'][endpoint]['estimate'] == .5
            assert 'simultaneous_primary_ci95' not in single['contrasts']['256-64']['rates'][endpoint]
        for group in result['per_stratum'].values():
            assert group[direction]['n_per_budget'] == 10
    ww = result['pooled']['WIN/WIN']
    assert ww['primary_endpoint'] is None
    assert all('simultaneous_primary_ci95' not in rate
               for contrast in ww['contrasts'].values() for rate in contrast['rates'].values())
    lengths = result['mixed_same_length']['pooled']
    assert lengths['64']['all_games']['mixed_n'] == lengths['64']['all_games']['same_n'] == 120
    assert lengths['1024']['exclude_length2_3']['mixed_n'] == 0
    assert lengths['1024']['exclude_length2_3']['same_n'] == 0
    assert lengths['1024']['exclude_length2_3']['mixed_minus_same_mean'] is None


def test_reduced_protocol_has_derived_comparisons():
    p = _protocol(True)
    p['primary_contrasts'] = [[256, 64], [1024, 64]]
    result = analyze_rows(_rows(p), p)
    assert result['n_records'] == 16
    assert result['intervals']['simultaneous_primary_family_size'] == 3
    assert set(result['pooled']['LOSE/LOSE']['contrasts']) == {'3-1'}


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'wrong_seed', 'wrong_block',
                                   'cross_direction', 'replicate', 'bool_key', 'actions', 'move_count', 'bool_utility'])
def test_analysis_refuses_broken_design_or_pairing(damage):
    p = _protocol(True)
    rows = _rows(p)
    if damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'wrong_seed':
        rows[-1]['game_seed'] += 5000
    elif damage == 'wrong_block':
        rows[-1]['block_id'] += 'wrong'
    elif damage == 'cross_direction':
        rows[-1]['game_seed'] = rows[-3]['game_seed']
    elif damage == 'replicate':
        rows[-1]['replicate'] = 1
    elif damage == 'bool_key':
        rows[-1]['replicate'] = False
    elif damage == 'actions':
        rows[-1]['actions'][0] = 26
    elif damage == 'bool_utility':
        rows[-1]['black_utility'] = True
    else:
        rows[-1]['move_count'] += 1
    with pytest.raises(ValueError):
        analyze_rows(rows, p)


def test_realized_all_pass_is_not_only_empty_double_pass():
    p = _protocol(True)
    rows = _rows(p)
    for row in rows:
        if row['black_identity'] == row['white_identity'] == 'LOSE':
            row['actions'] = [25, 0, 25, 25]
            row['move_count'] = 4
    group = analyze_rows(rows, p)['pooled']['LOSE/LOSE']['budgets']['1']['rates']
    assert group['black_realized_all_pass']['estimate'] == 1
    assert group['empty_double_pass']['estimate'] == 0


def test_exact_wl_any_first_point_excludes_longer_prefix_routes():
    p = _protocol(True)
    rows = _rows(p)
    for row in rows:
        if (row['black_identity'], row['white_identity']) == ('WIN', 'LOSE'):
            row['actions'] = [24, 25, 25] if row['black_seed'] == 1 else [24, 1, 25, 25]
            row['move_count'] = len(row['actions'])
    group = analyze_rows(rows, p)['pooled']['WIN/LOSE']['budgets']['1']['rates']
    assert group['black_one_stone_double_pass']['estimate'] == .5
    assert group['literal_one_stone_a0']['estimate'] == 0
