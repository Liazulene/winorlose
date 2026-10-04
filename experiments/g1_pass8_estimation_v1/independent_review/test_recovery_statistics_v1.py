"""Recovery statistical review; synthetic rows only, no game execution/writes."""
from __future__ import annotations

import copy
import itertools
import json
import math
from pathlib import Path
import random
import sys

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / 'src')]

import recovery_verify_inference_v1 as guarded
import verify_inference_arithmetic as reference
from winai_loseai.experiments import g1_pass8_estimation_stats as production
from winai_loseai.experiments.d1_estimation_stats import clopper_pearson, paired_rate_difference


def protocol():
    return json.loads((HERE.parent / 'preregistration.json').read_text())


def rows():
    result = []
    for key, game_index in guarded.expected_rows().items():
        rule, seed, ib, iw, sb, sw, rep = key
        direction = guarded.DIRECTIONS.index((ib, iw))
        orientation = guarded.ORIENTATIONS.index((sb, sw))
        block = (direction * 2 + orientation) * 10 + rep
        # Statistical fixtures, not purported legal/replayed game records.
        black_goal = ((rep + seed + orientation) % 4 < (3 if rule == 8 else 2))
        winner = 'black' if black_goal == (ib == 'WIN') else 'white'
        n = rule + 2 + ((block * 7 + seed) % (99 - rule))
        actions = [i % 25 for i in range(n - 2)] + [25, 25]
        result.append(dict(pass_min_ply=rule, batch_seed=seed, black_identity=ib,
                           white_identity=iw, black_seed=sb, white_seed=sw,
                           replicate=rep, budget=256, block_index=block,
                           block_id=f'{seed}:{block}', game_seed=guarded.seed_for(seed, block),
                           ruleset=guarded.RULES[rule], move_count=n, actions=actions,
                           extra_length=n-rule-2, winner=winner,
                           black_utility=1 if black_goal else -1,
                           white_utility=(1 if black_goal else -1) * (1 if ib != iw else -1),
                           termination_reason='double_pass', game_index=game_index,
                           game_id=f'g1_pass8_estimation_v1-g{game_index:06d}'))
    return result


@pytest.mark.parametrize('n', [20, 60])
@pytest.mark.parametrize('confidence', [.95, .975, .996875])
def test_every_cp_count_against_binomial_polynomial_inversion(n, confidence):
    for k in range(n + 1):
        assert clopper_pearson(k, n, confidence) == pytest.approx(reference.cp(k, n, confidence), abs=2e-13)


@pytest.mark.parametrize('n', [20, 60])
@pytest.mark.parametrize('confidence', [.95, 1-.05/8])
def test_every_feasible_discordance_table_against_independent_arithmetic(n, confidence):
    for positive in range(n + 1):
        for negative in range(n - positive + 1):
            a = [0]*positive + [1]*negative + [0]*(n-positive-negative)
            b = [1]*positive + [0]*negative + [0]*(n-positive-negative)
            actual = paired_rate_difference(a, b, confidence)
            wanted = reference.pair_rate(a, b, confidence)
            assert reference.close(wanted, actual) == []


def test_precision_json_recomputed_without_beta_quantiles():
    document = json.loads((HERE.parent / 'statistics_method_precision.json').read_text())
    for scope, n in [('pooled', 60), ('per_seed', 20)]:
        saved = document['precision'][scope]
        assert saved['n_pairs'] == n
        assert saved['feasible_discordance_count_combinations'] == (n+1)*(n+2)//2
        for label, confidence in [('pointwise95', .95), ('joint_family8_95', 1-.05/8)]:
            if scope == 'per_seed' and label == 'joint_family8_95':
                continue
            component = 1-(1-confidence)/2
            candidates = []
            for positive in range(n+1):
                lp, up = reference.cp(positive, n, component)
                for negative in range(n-positive+1):
                    lm, um = reference.cp(negative, n, component)
                    lo, hi, estimate = lp-um, up-lm, (positive-negative)/n
                    candidates.append((hi-lo, max(estimate-lo, hi-estimate), positive, negative))
            maximum = max(c[0] for c in candidates)
            planned = saved[label]
            assert planned['goal_all_concordant_ci'] == pytest.approx([-reference.cp(0,n,component)[1], reference.cp(0,n,component)[1]])
            assert planned['goal_maximum_full_width'] == pytest.approx(maximum)
            assert planned['goal_maximum_distance_from_estimate'] == pytest.approx(max(c[1] for c in candidates))
            assert planned['goal_full_width_maximizers_nplus_nminus'] == [[c[2],c[3]] for c in candidates if abs(c[0]-maximum)<1e-14]
            assert planned['raw_length_unclipped_radius'] == pytest.approx(188*math.sqrt(math.log(2/(1-confidence))/(2*n)))
        assert saved['marginal_rate_all_success_pointwise95_ci'] == pytest.approx(reference.cp(n,n,.95))


def test_full_synthetic480_against_both_independent_verifiers_and_shuffled_input():
    data = rows()
    original = copy.deepcopy(data)
    saved = production.analyze_rows(data, protocol())
    assert guarded.validate_rows(data) == []
    assert reference.verify(data, saved)[0]['passed']
    assert guarded.verify(data, saved)[0]['passed']
    assert data == original
    random.Random(731).shuffle(data)
    assert production.analyze_rows(data, protocol()) == saved
    assert guarded.verify(data, saved)[0]['passed']
    for direction, goal in production.PRIMARY_ENDPOINTS.items():
        group = saved['pooled'][direction]
        assert group['n_pairs'] == 60
        raw, extra = group['contrast']['raw_length'], group['contrast']['extra_length']
        assert extra['estimate'] == raw['estimate']-8
        assert extra['simultaneous_family_ci95'] == [x-8 for x in raw['simultaneous_family_ci95']]
        assert group['contrast']['rates'][goal]['simultaneous_family_size'] == 8
        if direction == 'LOSE/LOSE':
            assert group['rules']['G0']['rates']['black_goals']['successes'] == group['rules']['G0']['rates']['white_board_wins']['successes']
        if direction in ('WIN/LOSE', 'LOSE/WIN'):
            rate = group['contrast']['rates']
            for endpoint in ('black_goals', 'white_goals'):
                assert rate[endpoint]['ci'] == rate['joint_goals']['ci']
                assert rate[endpoint]['n'] == 60


@pytest.mark.parametrize('success', [False, True])
def test_all_success_or_all_failure_remains_uncertain(success):
    data = rows()
    for row in data:
        row['winner'] = 'black' if success == (row['black_identity']=='WIN') else 'white'
        for color in ('black','white'):
            row[color+'_utility'] = 1 if ((row['winner']==color)==(row[color+'_identity']=='WIN')) else -1
    saved = production.analyze_rows(data, protocol())
    assert guarded.verify(data, saved)[0]['passed']
    boundary = 1-(.05/32)**(1/60)
    for direction, endpoint in production.PRIMARY_ENDPOINTS.items():
        rate = saved['pooled'][direction]['contrast']['rates'][endpoint]
        assert rate['discordant_pairs'] == 0
        assert rate['simultaneous_family_ci95'] == pytest.approx([-boundary,boundary])
        assert rate['baseline_successes'] == rate['comparison_successes'] == int(success)*60


def forged_reference_result(data):
    saved = production.analyze_rows(rows(), protocol())
    # Deliberately demonstrate that the old arithmetic module is not a design gate.
    _, expected = reference.verify(data, saved)
    saved.update(expected)
    assert reference.verify(data, saved)[0]['passed']
    return saved


@pytest.mark.parametrize('damage', ['48_rows', '960_rows', 'duplicated_keys', 'wrong_seed', 'wrong_winner', 'bad_length', 'wrong_schedule'])
def test_guard_rejects_mutations_which_old_arithmetic_verifier_does_not(damage):
    data = rows()
    if damage == '48_rows':
        data = [r for r in data if r['replicate']==0]
    elif damage == '960_rows':
        data = data+copy.deepcopy(data)
    elif damage == 'duplicated_keys':
        for rule in (0,8):
            candidates = [i for i,r in enumerate(data) if r['pass_min_ply']==rule and r['batch_seed']==11 and r['black_identity']==r['white_identity']=='WIN' and r['black_seed']==1]
            data[candidates[1]] = copy.deepcopy(data[candidates[0]])
    elif damage == 'wrong_seed':
        data[0]['game_seed'] += 1
    elif damage == 'wrong_winner':
        data[0]['winner'] = 'white' if data[0]['winner']=='black' else 'black'
    elif damage == 'bad_length':
        data[0]['move_count'] = 101
    elif damage == 'wrong_schedule':
        data[0]['game_index'] = 479-data[0]['game_index']
    forged = forged_reference_result(data)
    result, expected = guarded.verify(data, forged)
    assert not result['passed'] and result['problems'] and expected is None
    assert not result['arithmetic_executed']


@pytest.mark.parametrize('damage', ['missing_arm','boolean_seed','early_pass','after_terminal','float_utility','wrong_extra','missing_field'])
def test_guard_fail_closed_on_other_malformed_rows(damage):
    data = rows()
    saved = production.analyze_rows(data, protocol())
    if damage == 'missing_arm':
        data.pop()
    elif damage == 'boolean_seed':
        data[0]['black_seed'] = True
    elif damage == 'early_pass':
        r = next(r for r in data if r['pass_min_ply']==8)
        r['actions'][0] = 25
    elif damage == 'after_terminal':
        data[0]['actions'][-3:] = [25,25,0]
    elif damage == 'float_utility':
        data[0]['black_utility'] = float(data[0]['black_utility'])
    elif damage == 'wrong_extra':
        data[0]['extra_length'] += 1
    else:
        del data[0]['block_index']
    assert not guarded.verify(data, saved)[0]['passed']


def discordance_pmf(probabilities):
    law = {(0,0):1.0}
    for plus, minus in probabilities:
        updated = {}
        for (p,m), mass in law.items():
            for key, probability in [((p+1,m),plus),((p,m+1),minus),((p,m),1-plus-minus)]:
                if probability:
                    updated[key] = updated.get(key,0.0)+mass*probability
        law = updated
    return law


@pytest.mark.parametrize('n', [20,60])
def test_exact_law_coverage_for_heterogeneous_fixed_strata(n):
    # Exact probability propagation, not random outcome simulation or a proof.
    rng = random.Random(993+n)
    choices = [(0,0),(.001,0),(0,.001),(.01,.98),(.3,.6),(.49,.49),(1,0),(0,1),(.3,0),(0,.3)]
    models = [list(itertools.islice(itertools.cycle(choices), n))]
    for _ in range(12):
        # Two or six unequal stratum distributions, ten independent blocks each.
        model = [pair for pair in rng.choices(choices,k=n//10) for _ in range(10)]
        models.append(model)
    for model in models:
        delta = math.fsum(a-b for a,b in model)/n
        law = discordance_pmf(model)
        assert math.fsum(law.values()) == pytest.approx(1.0, abs=2e-13)
        for confidence in (.95,1-.05/8):
            c = 1-(1-confidence)/2
            coverage = math.fsum(mass for (p,m),mass in law.items()
                                if reference.cp(p,n,c)[0]-reference.cp(m,n,c)[1]-1e-14 <= delta
                                <= reference.cp(p,n,c)[1]-reference.cp(m,n,c)[0]+1e-14)
            assert coverage >= confidence-2e-13


def test_shared_latent_dependence_counterexample_documents_scope():
    # If all 60 differences are one shared +/-1 coin, true mean is zero.
    # Both observed endpoints miss zero: model-based coverage is zero, not 95%.
    positive = reference.pair_rate([0]*60,[1]*60,1-.05/8)['ci']
    negative = reference.pair_rate([1]*60,[0]*60,1-.05/8)['ci']
    assert positive[0]>0 and negative[1]<0


@pytest.mark.parametrize('value', [-90,0,98])
def test_hoeffding_constant_data_uses_registered_support(value):
    for n in (20,60):
        for confidence in (.95,1-.05/8):
            expected = reference.mean_length([value]*n,confidence)
            actual = production.bounded_mean_interval([value]*n,-90,98,confidence)
            assert reference.close(expected, actual) == []
            assert actual['ci'][0] < actual['ci'][1]
