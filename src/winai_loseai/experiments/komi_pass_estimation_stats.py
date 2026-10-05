"""Fixed-sample four-arm komi/pass inference, separate from all pilot data.

The primary family is exactly three pooled LOSE/LOSE black-goal estimands:
komi0 minus komi2.5 at pass0, the same contrast at pass8, and pass8 minus
pass0 of those contrasts. The first two use the two-sided CP discordance
rectangle; the quartet interaction uses Hoeffding with support [-2, 2].
Each interval has alpha=.05/3. No data-dependent method selection occurs.

Mattner--Tasto (2015), published Theorem1.3 / arXiv v3 Theorem1.12, makes
TWO-SIDED equal-tail CP (confidence >=.5) valid for average probabilities
of independent, potentially nonidentical Bernoulli variables. Applying two
such component intervals at alpha/2 and projecting their rectangle gives
the paired-difference guarantee by a union bound, without assuming the
positive and negative discordance counts independent. Hoeffding allows
nonidentical independent bounded variables. A second union bound gives
the three-member family coverage. One-sided CP is not claimed robust.

Independent quartet streams are a simulation model, not proved by hashes.
Within-quartet arms may be arbitrarily dependent. The estimand is the
average expectation for this fixed seed/orientation design, not a new-agent
or batch-seed population. Fixed saved trajectories are deterministic.
The separately named stratified Student-t/Satterthwaite sensitivity is
approximate, not part of the finite-sample coverage claim or a replacement
for the prespecified intervals. Full replay/integrity must precede analysis.
"""
from __future__ import annotations

import math
import statistics

from scipy.stats import t

from ..league.seeds import game_seed_for
from .d1_estimation_stats import (
    CI_METHOD, CP_SOURCE, HOEFFDING_SOURCE, clopper_pearson,
    paired_rate_difference, rate_estimate,
)
from .g1_pass8_estimation_stats import bounded_mean_interval


ANALYSIS_VERSION = 'komi-pass-fixed-quartet-cp-hoeffding-v1'
DIRECTIONS = (('WIN', 'WIN'), ('LOSE', 'LOSE'), ('WIN', 'LOSE'), ('LOSE', 'WIN'))
ORIENTATIONS = ((1, 2), (2, 1))
ARMS = {(0, 2.5): 'G0', (8, 2.5): 'G1-pass8',
        (0, 0.0): 'G1-k0', (8, 0.0): 'G1-k0-pass8'}
CONTRASTS = ('komi0_minus2.5_at_pass0', 'komi0_minus2.5_at_pass8',
             'komi_effect_pass8_minus_pass0')
FAMILY_SIZE = 3
FAMILY_ALPHA = .05
INTERVAL_CONFIDENCE = 1 - FAMILY_ALPHA / FAMILY_SIZE
INTERACTION_SUPPORT = (-2, 2)
SATTERTHWAITE_SOURCE = 'https://doi.org/10.2307/3002019'


def _distribution(values):
    values = sorted(values)
    if not values:
        raise ValueError('nonempty observations required')
    def quantile(q):
        index = (len(values) - 1) * q
        lo, hi = int(index), min(int(index) + 1, len(values) - 1)
        return values[lo] + (values[hi] - values[lo]) * (index - lo)
    return {'n': len(values), 'mean': statistics.mean(values),
            **{name: quantile(q) for name, q in (
                ('min', 0), ('q1', .25), ('median', .5), ('q3', .75),
                ('p90', .9), ('p95', .95), ('max', 1))}}


def _endpoints(row):
    """Recompute outcomes from rows; no white-goal complement shortcuts."""
    rule, komi = row['pass_min_ply'], row['komi']
    actions, length = row['actions'], row['move_count']
    if (type(length) is not int or not rule + 2 <= length <= 100
            or not isinstance(actions, list) or len(actions) != length
            or any(type(a) is not int or not 0 <= a <= 25 for a in actions)
            or 25 in actions[:rule]):
        raise ValueError('invalid action sequence, pass window, or length')
    if any(actions[i:i + 2] == [25, 25] for i in range(length - 2)):
        raise ValueError('actions occur after double-pass termination')
    reason = 'double_pass' if actions[-2:] == [25, 25] else 'move_limit'
    if row['termination_reason'] != reason or (reason == 'move_limit' and length != 100):
        raise ValueError('invalid terminal reason or precedence')
    winner = row['winner']
    if winner not in ('black', 'white', 'draw') or (komi == 2.5 and winner == 'draw'):
        raise ValueError('invalid winner; half-point komi cannot draw')
    for color in ('black', 'white'):
        expected = (0 if winner == 'draw' else
                    1 if ((winner == color) == (row[color + '_identity'] == 'WIN')) else -1)
        if type(row[color + '_utility']) is not int or row[color + '_utility'] != expected:
            raise ValueError('winner and identity utility disagree; draws require utility0')
    if ('extra_length' in row and (type(row['extra_length']) is not int
                                   or row['extra_length'] != length - rule - 2)):
        raise ValueError('extra length disagrees with mechanical minimum')
    return {
        'black_board_wins': winner == 'black', 'white_board_wins': winner == 'white',
        'draws': winner == 'draw', 'black_goals': row['black_utility'] == 1,
        'white_goals': row['white_utility'] == 1,
        'joint_goals': row['black_utility'] == row['white_utility'] == 1,
        'length2': length == 2, 'length3': length == 3, 'length10': length == 10,
        'length_le8': length <= 8, 'length_le10': length <= 10,
        'length_ge60': length >= 60, 'move_limit': reason == 'move_limit',
        'empty_double_pass': actions == [25, 25],
        'black_one_stone_double_pass': length == 3 and actions[0] < 25 and actions[1:] == [25, 25],
        'black_realized_all_pass': all(a == 25 for a in actions[::2]),
        'at_rule_minimum': length == rule + 2,
    }


def _validate_rows(rows, p):
    try:
        seeds, repetitions = p['batch_seeds'], p['games_per_cell']
        if (p['pass_min_plies'] != [0, 8] or any(type(r) is not int for r in p['pass_min_plies'])
                or p['komis'] != [2.5, 0.0] or any(type(k) not in (int, float) for k in p['komis'])
                or type(p['budget']) is not int or p['budget'] < 1
                or not isinstance(seeds, list) or not seeds
                or any(type(s) is not int or s < 0 for s in seeds) or len(set(seeds)) != len(seeds)
                or p['identity_directions'] != [list(d) for d in DIRECTIONS]
                or p['agent_seed_orientations'] != [list(o) for o in ORIENTATIONS]
                or any(type(s) is not int for o in p['agent_seed_orientations'] for s in o)
                or type(repetitions) is not int or repetitions < 1
                or type(p['board_size']) is not int or p['board_size'] != 5):
            raise ValueError('invalid balanced four-arm design')
        expected = {(rule, komi, seed, *direction, *orientation, replicate)
                    for rule, komi in ARMS for seed in seeds for direction in DIRECTIONS
                    for orientation in ORIENTATIONS for replicate in range(repetitions)}
        if type(p['planned_games']) is not int or p['planned_games'] != len(expected) or len(rows) != len(expected):
            raise ValueError('complete registered sample required; no partial inference or reweighting')
        indexed, used_seeds = {}, {}
        keys = ('pass_min_ply', 'komi', 'batch_seed', 'black_identity', 'white_identity',
                'black_seed', 'white_seed', 'replicate')
        for row in rows:
            if any(type(row[k]) is not int for k in
                   ('pass_min_ply', 'batch_seed', 'black_seed', 'white_seed', 'replicate', 'budget')):
                raise ValueError('noninteger design key')
            if type(row['komi']) not in (int, float) or not math.isfinite(row['komi']):
                raise ValueError('invalid komi')
            key = tuple(row[k] for k in keys)
            if key not in expected or key in indexed or row['budget'] != p['budget']:
                raise ValueError('duplicate or unregistered design cell')
            rule, komi, seed, ib, iw, sb, sw, replicate = key
            di, oi = DIRECTIONS.index((ib, iw)), ORIENTATIONS.index((sb, sw))
            index = (di * 2 + oi) * repetitions + replicate
            canonical_seed = game_seed_for(seed, index)
            if (row['block_id'] != f'{seed}:{index}' or type(row['game_seed']) is not int
                    or row['game_seed'] != canonical_seed
                    or ('ruleset' in row and row['ruleset'] != ARMS[rule, komi])):
                raise ValueError('canonical block ID, seed, or rule mismatch')
            for name, value in (('block_index', index), ('identity_index', di), ('orientation_index', oi)):
                if name in row and (type(row[name]) is not int or row[name] != value):
                    raise ValueError('canonical design index mismatch')
            block = key[2:]
            if canonical_seed in used_seeds and used_seeds[canonical_seed] != block:
                raise ValueError('game seed reused across distinct quartets')
            used_seeds[canonical_seed] = block
            indexed[key] = dict(row, _endpoint_values=_endpoints(row))
        if set(indexed) != expected:
            raise ValueError('incomplete registered sample')
        return list(indexed.values())
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('malformed registered design or analysis row') from error


def stratified_t_sensitivity(strata, lower, upper, confidence=INTERVAL_CONFIDENCE):
    """Approximate equal-fixed-stratum t interval; never a coverage guarantee.

    With H strata: V=sum(s_h^2/n_h)/H^2 and
    df=V^2/sum((s_h^2/(H^2*n_h))^2/(n_h-1)). At zero estimated variance
    or fewer than2 observations in any stratum, return no interval instead
    of falsely certifying zero uncertainty. Fixed strata are never resampled.
    """
    if not isinstance(strata, dict) or not strata:
        raise ValueError('nonempty fixed strata required')
    strata = {key: list(values) for key, values in strata.items()}
    # Validate support, values and confidence using the finite-bound helper.
    for values in strata.values():
        bounded_mean_interval(values, lower, upper, confidence)
    h = len(strata)
    detail = {key: {'n': len(v), 'mean': statistics.mean(v),
                    'sample_variance': statistics.variance(v) if len(v) >= 2 else None}
              for key, v in strata.items()}
    result = {'method': 'approximate_equal_fixed_stratum_t_Satterthwaite',
              'source': SATTERTHWAITE_SOURCE, 'exact_coverage_claim': False,
              'coverage_scope': 'nonconfirmatory_approximate_sensitivity_not_primary_family',
              'nominal_confidence_level': confidence, 'nominal_bonferroni_family_size': FAMILY_SIZE,
              'n': sum(len(v) for v in strata.values()), 'n_fixed_strata': h,
              'estimate': statistics.mean(d['mean'] for d in detail.values()),
              'support': [lower, upper], 'strata': detail,
              'ci': None, 'standard_error': None, 'degrees_of_freedom': None,
              'limitation': 'Discrete bounded outcomes and only10 replicates per fixed stratum can make this approximation unreliable; it cannot establish the primary conclusion.'}
    if any(d['n'] < 2 for d in detail.values()):
        return dict(result, status='unavailable_insufficient_within_stratum_replication')
    components = [d['sample_variance'] / d['n'] / h ** 2 for d in detail.values()]
    variance = sum(components)
    if variance == 0:
        return dict(result, status='unavailable_zero_estimated_variance', standard_error=0.0)
    df = variance ** 2 / sum(v ** 2 / (d['n'] - 1) for v, d in zip(components, detail.values()))
    se = math.sqrt(variance)
    radius = float(t.ppf((1 + confidence) / 2, df)) * se
    ci = [max(lower, result['estimate'] - radius), min(upper, result['estimate'] + radius)]
    return dict(result, status='approximation_only', ci=ci, standard_error=se,
                degrees_of_freedom=df, unclipped_radius=radius)


def _ordered_arms(rows):
    order = lambda r: (r['batch_seed'], r['black_seed'], r['white_seed'], r['replicate'])
    arms = {arm: sorted((r for r in rows if (r['pass_min_ply'], r['komi']) == arm), key=order)
            for arm in ARMS}
    reference = [order(r) for r in arms[0, 2.5]]
    if any([order(r) for r in arm] != reference for arm in arms.values()):
        raise ValueError('quartet ordering mismatch')
    return arms


def _interaction_values(arms, endpoint):
    yy = {arm: [int(r['_endpoint_values'][endpoint]) for r in rows] for arm, rows in arms.items()}
    return [d - c - b + a for a, b, c, d in
            zip(yy[0, 2.5], yy[0, 0.0], yy[8, 2.5], yy[8, 0.0])]


def _group(rows, direction):
    arms = _ordered_arms(rows)
    result = {'identity_direction': direction, 'n_quartets': len(rows) // 4,
              'n_per_arm': len(rows) // 4, 'arms': {}, 'contrasts': {}}
    for (rule, komi), arm in arms.items():
        result['arms'][ARMS[rule, komi]] = {
            'n': len(arm), 'pass_min_ply': rule, 'komi': komi,
            'rates': {name: dict(rate_estimate(r['_endpoint_values'][name] for r in arm),
                                 coverage_scope='pointwise95_not_family_adjusted')
                      for name in arm[0]['_endpoint_values']},
            'utility_counts': {color: {str(u): sum(r[color + '_utility'] == u for r in arm)
                                       for u in (-1, 0, 1)} for color in ('black', 'white')},
            'length': _distribution([r['move_count'] for r in arm]),
            'extra_length': _distribution([r['move_count'] - rule - 2 for r in arm]),
        }
    for rule, contrast in zip((0, 8), CONTRASTS[:2]):
        baseline, comparison = arms[rule, 2.5], arms[rule, 0.0]
        rates = {name: dict(paired_rate_difference(
                    [r['_endpoint_values'][name] for r in baseline],
                    [r['_endpoint_values'][name] for r in comparison]),
                    coverage_scope='pointwise95_not_family_adjusted')
                 for name in baseline[0]['_endpoint_values']}
        lengths = [b['move_count'] - a['move_count'] for a, b in zip(baseline, comparison)]
        result['contrasts'][contrast] = {
            'comparison': ARMS[rule, 0.0], 'baseline': ARMS[rule, 2.5], 'rates': rates,
            'raw_length_delta': _distribution(lengths), 'length_inference': 'descriptive_only',
            'extra_length_delta': _distribution(lengths),
            'extra_length_note': 'Same pass threshold cancels; numerically identical to raw komi length difference. No causal adjustment.'}
    interaction = {}
    for name in arms[0, 2.5][0]['_endpoint_values']:
        values = _interaction_values(arms, name)
        interaction[name] = dict(bounded_mean_interval(values, *INTERACTION_SUPPORT),
                                 coverage_scope='pointwise95_not_family_adjusted',
                                 value_counts={str(v): values.count(v) for v in range(-2, 3)})
    length_values = [d['move_count'] - c['move_count'] - b['move_count'] + a['move_count']
                     for a, b, c, d in zip(arms[0, 2.5], arms[0, 0.0], arms[8, 2.5], arms[8, 0.0])]
    result['contrasts'][CONTRASTS[2]] = {'rates': interaction,
        'raw_length_delta': _distribution(length_values), 'length_inference': 'descriptive_only',
        'extra_length_delta': _distribution(length_values),
        'extra_length_note': 'Mechanical shifts cancel in this interaction; not a causal adjustment.'}
    return result


def _primary_family(rows):
    arms = _ordered_arms(rows)
    result = {}
    for rule, contrast in zip((0, 8), CONTRASTS[:2]):
        result[contrast] = paired_rate_difference(
            [r['_endpoint_values']['black_goals'] for r in arms[rule, 2.5]],
            [r['_endpoint_values']['black_goals'] for r in arms[rule, 0.0]], INTERVAL_CONFIDENCE)
    values = _interaction_values(arms, 'black_goals')
    result[CONTRASTS[2]] = dict(bounded_mean_interval(values, *INTERACTION_SUPPORT, INTERVAL_CONFIDENCE),
        value_counts={str(v): values.count(v) for v in range(-2, 3)})
    for contrast, value in result.items():
        value.update(identity_direction='LOSE/LOSE', endpoint='black_goals',
            contrast=contrast, simultaneous_family_size=FAMILY_SIZE,
            simultaneous_family_confidence_level=1 - FAMILY_ALPHA,
            simultaneous_family_ci95=list(value['ci']),
            coverage_scope='pooled_three_member_simultaneous_family_at_least95')
    return result


def _sensitivity(rows):
    arms = _ordered_arms(rows)
    sequences = {CONTRASTS[i]: [int(b['_endpoint_values']['black_goals']) -
                               int(a['_endpoint_values']['black_goals'])
                               for a, b in zip(arms[rule, 2.5], arms[rule, 0.0])]
                 for i, rule in enumerate((0, 8))}
    sequences[CONTRASTS[2]] = _interaction_values(arms, 'black_goals')
    result = {}
    for contrast, sequence in sequences.items():
        strata = {}
        for row, value in zip(arms[0, 2.5], sequence):
            label = f"{row['batch_seed']}:{row['black_seed']},{row['white_seed']}"
            strata.setdefault(label, []).append(value)
        support = INTERACTION_SUPPORT if contrast == CONTRASTS[2] else (-1, 1)
        result[contrast] = stratified_t_sensitivity(strata, *support)
    return result


def analyze_rows(rows, p):
    """Complete sample only; balanced small synthetic designs are supported."""
    rows = _validate_rows(list(rows), p)
    ll = [r for r in rows if (r['black_identity'], r['white_identity']) == ('LOSE', 'LOSE')]
    result = {
        'analysis_version': ANALYSIS_VERSION, 'estimation_only': True,
        'complete_registered_sample': True, 'n_records': len(rows), 'n_quartets': len(rows) // 4,
        'intervals': {
            'paired_komi_method': CI_METHOD, 'paired_komi_source': CP_SOURCE,
            'paired_komi_theorem': 'Mattner-Tasto published1.3/arXivv3-1.12 plus union-bound projection',
            'interaction_method': 'Hoeffding_independent_bounded_mean',
            'interaction_source': HOEFFDING_SOURCE, 'interaction_support': list(INTERACTION_SUPPORT),
            'simultaneous_family_confidence_level': .95, 'simultaneous_family_size': FAMILY_SIZE,
            'per_family_interval_confidence_level': INTERVAL_CONFIDENCE,
            'family': [{'direction': 'LOSE/LOSE', 'endpoint': 'black_goals', 'contrast': c} for c in CONTRASTS],
            'multiplicity': 'Only primary_family covers the three-member pooled joint family. All arm rates, per-seed/per-stratum results and other endpoints are pointwise or descriptive, not joint across panels.',
            'audit': 'Paired CP retains its separately labelled Hoeffding audit; never substitute, intersect or choose the narrower interval.',
            'approximation': 'Stratified-t sensitivity uses nominal Bonferroni3 but carries no exact or finite-sample family coverage guarantee and is nonconfirmatory.',
        },
        'estimand': {
            'pooled': 'Equal weight to each fixed batch-seed by agent-orientation stratum; six strata with ten repetitions in the formal design.',
            'per_seed': 'Equal weight to the two fixed agent orientations within the named batch seed.',
            'replication_unit': 'Matched four-arm quartet, never four independent trials; never pair across identity directions.',
            'assumptions': 'Independent potentially nonidentical quartet PRNG streams; arbitrary within-quartet arm dependence. Hash uniqueness supports provenance isolation, not statistical independence.',
            'scope': 'Hypothetical independent stream replication of this fixed design, not uncertainty in deterministic saved outcomes or inference to new agents, policies or a population of batch seeds.',
            'intervention': 'Whole rule intervention including changes in search, rollout RNG consumption and trajectories; not isolated terminal-channel or coordination attribution.',
            'draws': 'Utility0 and neither goal achieved; full registered denominators. White goals are computed directly and are not black-goal complements.',
            'pilot': 'M6 and all historical observations excluded from the formal sample.',
        },
        'limits': [
            'Fixed sample; no partial-sample inference, outcome-driven expansion, seed replacement, imputation or exclusion of short games.',
            'No p-values, significance flags, equivalence, noninferiority, rare-failure certification or automatic7x7 gate.',
            'Safety/integrity interruptions retain incomplete status; conditioning on an uneventful completed run is not itself a coverage guarantee.',
            'Three seed labels describe fixed-stratum heterogeneity, not random population-of-seeds replication.',
            'Replay and integrity validation must precede analysis; statistical row checks are not an independent rules proof.',
        ],
        'primary_family': _primary_family(ll),
        'approximate_sensitivity': _sensitivity(ll),
        'pooled': {}, 'per_seed': {}, 'per_stratum': {},
    }
    for ib, iw in DIRECTIONS:
        direction = f'{ib}/{iw}'
        selected = [r for r in rows if (r['black_identity'], r['white_identity']) == (ib, iw)]
        result['pooled'][direction] = _group(selected, direction)
        for seed in p['batch_seeds']:
            sr = [r for r in selected if r['batch_seed'] == seed]
            result['per_seed'].setdefault(str(seed), {})[direction] = _group(sr, direction)
            for sb, sw in ORIENTATIONS:
                rr = [r for r in sr if (r['black_seed'], r['white_seed']) == (sb, sw)]
                result['per_stratum'].setdefault(f'{seed}:{sb},{sw}', {})[direction] = _group(rr, direction)
    return result


def planned_precision(n=60):
    """Outcome-free exhaustive count precision; resource choice, never power.

    Maximum half full width and maximum distance from the point estimate
    differ for asymmetric intervals. Neither marginal rate quantity promises
    equal precision for a paired contrast or interaction.
    """
    if type(n) is not int or n < 1:
        raise ValueError('positive integer n required')
    marginal = [clopper_pearson(k, n) for k in range(n + 1)]
    result = {'n_quartets_per_direction': n,
              'feasible_discordance_count_combinations': (n + 1) * (n + 2) // 2,
              'marginal_rate_pointwise95': {
                  'maximum_half_full_width': max((hi - lo) / 2 for lo, hi in marginal),
                  'maximum_distance_from_estimate': max(max(k / n - lo, hi - k / n)
                                                        for k, (lo, hi) in enumerate(marginal)),
                  'all_success_ci': list(marginal[-1]), 'all_failure_ci': list(marginal[0])}}
    for label, confidence in (('pointwise95', .95), ('joint_family3_95', INTERVAL_CONFIDENCE)):
        component = 1 - (1 - confidence) / 2
        limits = [clopper_pearson(k, n, component) for k in range(n + 1)]
        candidates = []
        for plus in range(n + 1):
            lp, up = limits[plus]
            for minus in range(n - plus + 1):
                lm, um = limits[minus]
                lo, hi, estimate = lp - um, up - lm, (plus - minus) / n
                candidates.append((hi - lo, max(hi - estimate, estimate - lo), plus, minus))
        maximum = max(v[0] for v in candidates)
        result[label] = {
            'interval_confidence_level': confidence, 'goal_component_confidence_level': component,
            'goal_maximum_full_width': maximum,
            'goal_maximum_distance_from_estimate': max(v[1] for v in candidates),
            'goal_width_maximizers_nplus_nminus': [[v[2], v[3]] for v in candidates if abs(v[0] - maximum) < 1e-14],
            'goal_all_concordant_ci': [-limits[0][1], limits[0][1]],
            'interaction_unclipped_radius': 4 * math.sqrt(math.log(2 / (1 - confidence)) / (2 * n)),
        }
    result['interpretation'] = ('Resource-fixed coarse estimation, not pilot-effect power. '
        'The marginal-rate bound is not a contrast or interaction precision promise; '
        'the primary interaction can remain inconclusive. No data-dependent extension.')
    return result
