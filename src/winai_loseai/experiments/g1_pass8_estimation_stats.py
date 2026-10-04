"""Fixed-sample, paired G0 versus G1-pass8 inference.

The pooled family contains exactly eight estimands: four direction-specific
goal-rate changes and four raw mean-length changes. Each uses alpha=.05/8.
Goals use the inherited two-sided Clopper-Pearson discordance rectangle;
lengths use Hoeffding with the a-priori support [-90,98]. No choice between
methods, intersection, tests, significance flags, or optional stopping occurs.

For independent, nonidentical Bernoulli trials, TWO-SIDED equal-tail CP at
confidence >=.5 covers their average probability (Mattner and Tasto 2015,
Theorem 1.3; arXiv:1403.0229v3 Theorem 1.12). This is not a one-sided CP
robustness claim. The two discordance counts can be dependent: the rectangle
projection uses a union bound. Hoeffding also allows heterogeneous means.

The inferential unit is an independent PRNG-stream block, not one arm, move,
or pass proposal. Independence is a simulation model, not a fact proved by
hash uniqueness. Fixed seed outcomes are deterministic. Coverage concerns
hypothetical independent stream replications of this fixed design, not a
population of agents, policies, or new batch seeds. Full replay/integrity
validation belongs to the runner and must precede this analysis.
"""
from __future__ import annotations

import math
import statistics

ANALYSIS_VERSION = "g1-pass8-fixed-paired-cp-hoeffding-v1"

from ..league.seeds import game_seed_for
from .d1_estimation_stats import (
    CI_METHOD, CP_SOURCE, HOEFFDING_SOURCE,
    clopper_pearson, paired_rate_difference, rate_estimate,
)


DIRECTIONS = (('WIN', 'WIN'), ('LOSE', 'LOSE'), ('WIN', 'LOSE'), ('LOSE', 'WIN'))
ORIENTATIONS = ((1, 2), (2, 1))
RULES = {0: 'G0', 8: 'G1-pass8'}
PRIMARY_ENDPOINTS = {
    'WIN/WIN': 'black_goals', 'LOSE/LOSE': 'black_goals',
    'WIN/LOSE': 'joint_goals', 'LOSE/WIN': 'joint_goals',
}
FAMILY_SIZE = 8
FAMILY_ALPHA = .05
INTERVAL_CONFIDENCE = 1 - FAMILY_ALPHA / FAMILY_SIZE
RAW_LENGTH_SUPPORT = (-90, 98)
EXTRA_LENGTH_SHIFT = -8


def _distribution(values):
    values = sorted(values)
    def quantile(q):
        i = (len(values) - 1) * q
        lo = int(i)
        hi = min(lo + 1, len(values) - 1)
        return values[lo] + (values[hi] - values[lo]) * (i - lo)
    return {'n': len(values), 'mean': statistics.mean(values),
            **{name: quantile(q) for name, q in (
                ('min', 0), ('q1', .25), ('median', .5), ('q3', .75),
                ('p90', .9), ('p95', .95), ('max', 1))}}


def bounded_mean_interval(values, lower, upper, confidence=.95):
    """Hoeffding CI for the mean of independent, possibly unequal means."""
    numeric = lambda v: type(v) in (int, float) and math.isfinite(v)
    values = list(values)
    if (not numeric(lower) or not numeric(upper) or lower >= upper
            or not numeric(confidence) or not 0 < confidence < 1
            or not values or any(not numeric(v) or not lower <= v <= upper for v in values)):
        raise ValueError('finite bounded observations, ordered support, and 0 < confidence < 1 required')
    n = len(values)
    estimate = statistics.mean(values)
    radius = (upper - lower) * math.sqrt(math.log(2 / (1 - confidence)) / (2 * n))
    ci = [max(lower, math.nextafter(estimate - radius, -math.inf)),
          min(upper, math.nextafter(estimate + radius, math.inf))]
    return {'n': n, 'estimate': estimate, 'confidence_level': confidence,
            'ci': ci, 'support': [lower, upper], 'unclipped_radius': radius,
            'method': 'Hoeffding_independent_bounded_mean',
            'coverage_scope': 'pointwise_for_this_fixed_estimand'}


def _endpoints(row):
    rule = row['pass_min_ply']
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
    if row['winner'] not in ('black', 'white'):
        raise ValueError('half-point komi requires a non-draw winner')
    for color in ('black', 'white'):
        value = row[color + '_utility']
        expected = 1 if ((row['winner'] == color) == (row[color + '_identity'] == 'WIN')) else -1
        if type(value) not in (int, float) or value != expected:
            raise ValueError('winner and identity utility disagree')
    if ('extra_length' in row and (type(row['extra_length']) is not int
                                   or row['extra_length'] != length - rule - 2)):
        raise ValueError('extra length disagrees with mechanical minimum')
    result = {
        'black_board_wins': row['winner'] == 'black',
        'white_board_wins': row['winner'] == 'white',
        'black_goals': row['black_utility'] == 1,
        'white_goals': row['white_utility'] == 1,
        'length_ge60': length >= 60,
        'move_limit': reason == 'move_limit',
    }
    if row['black_identity'] != row['white_identity']:
        result['joint_goals'] = row['black_utility'] == row['white_utility'] == 1
    return result


def _validate_rows(rows, p):
    try:
        seeds, repetitions = p['batch_seeds'], p['games_per_cell']
        if (p['pass_min_plies'] != [0, 8] or any(type(r) is not int for r in p['pass_min_plies'])
                or type(p['budget']) is not int or p['budget'] < 1
                or not isinstance(seeds, list) or not seeds
                or any(type(s) is not int or s < 0 for s in seeds)
                or len(set(seeds)) != len(seeds)
                or p['identity_directions'] != [list(d) for d in DIRECTIONS]
                or p['agent_seed_orientations'] != [list(o) for o in ORIENTATIONS]
                or type(repetitions) is not int or repetitions < 1
                or type(p['board_size']) is not int or p['board_size'] != 5
                or type(p['komi']) not in (int, float) or p['komi'] != 2.5):
            raise ValueError('invalid balanced pass8 design')
        expected = {(rule, seed, *direction, *orientation, replicate)
                    for rule in RULES for seed in seeds for direction in DIRECTIONS
                    for orientation in ORIENTATIONS for replicate in range(repetitions)}
        if type(p['planned_games']) is not int or p['planned_games'] != len(expected) or len(rows) != len(expected):
            raise ValueError('complete registered sample required; no partial inference or reweighting')
        indexed, used_seeds = {}, {}
        keys = ('pass_min_ply', 'batch_seed', 'black_identity', 'white_identity',
                'black_seed', 'white_seed', 'replicate')
        for row in rows:
            if any(type(row[k]) is not int for k in
                   ('pass_min_ply', 'batch_seed', 'black_seed', 'white_seed', 'replicate', 'budget')):
                raise ValueError('noninteger design key')
            key = tuple(row[k] for k in keys)
            if key not in expected or key in indexed or row['budget'] != p['budget']:
                raise ValueError('duplicate or unregistered design cell')
            rule, seed, ib, iw, sb, sw, replicate = key
            index = (DIRECTIONS.index((ib, iw)) * 2 + ORIENTATIONS.index((sb, sw))) * repetitions + replicate
            canonical_seed = game_seed_for(seed, index)
            if (row['block_id'] != f'{seed}:{index}' or type(row['game_seed']) is not int
                    or row['game_seed'] != canonical_seed
                    or ('block_index' in row and (type(row['block_index']) is not int or row['block_index'] != index))
                    or ('ruleset' in row and row['ruleset'] != RULES[rule])):
                raise ValueError('canonical block ID, index, seed, or rule mismatch')
            block = key[1:]
            if canonical_seed in used_seeds and used_seeds[canonical_seed] != block:
                raise ValueError('game seed reused across distinct matched blocks')
            used_seeds[canonical_seed] = block
            indexed[key] = dict(row, _endpoint_values=_endpoints(row))
        if set(indexed) != expected:
            raise ValueError('incomplete registered sample')
        return list(indexed.values())
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('malformed registered design or analysis row') from error


def _add_family(result, adjusted, endpoint):
    result['simultaneous_family_ci95'] = adjusted['ci']
    result['simultaneous_family_interval_confidence_level'] = INTERVAL_CONFIDENCE
    result['simultaneous_family_size'] = FAMILY_SIZE
    result['simultaneous_family_endpoint'] = endpoint
    if 'component_confidence_level' in adjusted:
        result['simultaneous_family_component_confidence_level'] = adjusted['component_confidence_level']
        result['simultaneous_family_positive_probability_ci'] = adjusted['positive_probability_ci']
        result['simultaneous_family_negative_probability_ci'] = adjusted['negative_probability_ci']
        result['simultaneous_family_hoeffding_audit_ci'] = adjusted['hoeffding_ci']
    else:
        result['simultaneous_family_unclipped_radius'] = adjusted['unclipped_radius']


def _translate_length(raw):
    result = dict(raw)
    for key in ('estimate',):
        result[key] += EXTRA_LENGTH_SHIFT
    for key in ('ci', 'support', 'simultaneous_family_ci95'):
        if key in result:
            result[key] = [x + EXTRA_LENGTH_SHIFT for x in result[key]]
    result['distribution'] = {key: (value if key == 'n' else value + EXTRA_LENGTH_SHIFT)
                              for key, value in raw['distribution'].items()}
    result['derived_from'] = 'raw_length_delta_minus_8'
    result['is_additional_family_member'] = False
    result['interpretation'] = 'Mechanical translation only; not a causal adjustment or coordination estimate.'
    return result


def _group(rows, direction, simultaneous=False):
    order = lambda row: (row['batch_seed'], row['black_seed'], row['white_seed'], row['replicate'])
    arms = {rule: sorted((r for r in rows if r['pass_min_ply'] == rule), key=order) for rule in RULES}
    baseline, comparison = arms[0], arms[8]
    if [order(r) for r in baseline] != [order(r) for r in comparison]:
        raise ValueError('paired block order mismatch')
    primary = PRIMARY_ENDPOINTS[direction]
    rules = {}
    for rule, arm in arms.items():
        rates = {name: dict(rate_estimate(r['_endpoint_values'][name] for r in arm),
                            coverage_scope='pointwise_95_not_family_adjusted')
                 for name in arm[0]['_endpoint_values']}
        rules[RULES[rule]] = {'n': len(arm), 'rates': rates,
                             'length': _distribution([r['move_count'] for r in arm]),
                             'extra_length': _distribution([r['move_count'] - rule - 2 for r in arm])}
    rates = {}
    for name in baseline[0]['_endpoint_values']:
        a = [r['_endpoint_values'][name] for r in baseline]
        b = [r['_endpoint_values'][name] for r in comparison]
        value = paired_rate_difference(a, b)
        value['coverage_scope'] = 'pointwise_95_not_family_adjusted'
        if simultaneous and name == primary:
            _add_family(value, paired_rate_difference(a, b, INTERVAL_CONFIDENCE), f'{direction}:{name}')
        rates[name] = value
    lengths = [b['move_count'] - a['move_count'] for a, b in zip(baseline, comparison)]
    raw = bounded_mean_interval(lengths, *RAW_LENGTH_SUPPORT)
    raw['distribution'] = _distribution(lengths)
    if simultaneous:
        _add_family(raw, bounded_mean_interval(lengths, *RAW_LENGTH_SUPPORT, INTERVAL_CONFIDENCE),
                    f'{direction}:raw_length')
    return {'identity_direction': direction, 'primary_goal_endpoint': primary,
            'n_pairs': len(baseline), 'rules': rules,
            'contrast': {'comparison': 'G1-pass8', 'baseline': 'G0',
                         'direction': 'G1-pass8_minus_G0', 'rates': rates,
                         'raw_length': raw, 'extra_length': _translate_length(raw)}}


def analyze_rows(rows, p):
    """Analyze a complete registered design; do not mutate rows or protocol.

    Reduced balanced protocols are accepted for synthetic tests. The formal
    frozen protocol supplies three new seeds, ten repetitions, and budget256.
    """
    rows = _validate_rows(list(rows), p)
    result = {
        'analysis_version': ANALYSIS_VERSION,
        'estimation_only': True, 'complete_registered_sample': True, 'n_records': len(rows),
        'n_paired_blocks': len(rows) // 2,
        'intervals': {
            'paired_goal_method': CI_METHOD, 'paired_goal_source': CP_SOURCE,
            'paired_goal_theorem': 'Mattner-Tasto published1.3/arXivv3-1.12 plus union-bound projection',
            'raw_length_method': 'Hoeffding_independent_bounded_mean',
            'raw_length_source': HOEFFDING_SOURCE, 'raw_length_support': list(RAW_LENGTH_SUPPORT),
            'simultaneous_family_confidence_level': .95, 'simultaneous_family_size': FAMILY_SIZE,
            'per_family_interval_confidence_level': INTERVAL_CONFIDENCE,
            'family': [{'direction': direction, 'endpoint': endpoint}
                       for direction, goal in PRIMARY_ENDPOINTS.items() for endpoint in (goal, 'raw_length')],
            'multiplicity': 'Only pooled simultaneous_family_ci95 covers the eight-member joint family; all other intervals are pointwise, not joint across seeds, endpoints, or arms.',
            'goal_hoeffding_audit': 'Shown separately; never selected in place of CP or intersected with it. Audit CIs are not additional family decisions.',
            'extra_length': 'Raw-length point and interval translated by minus8; identical information, no additional family member.',
        },
        'estimand': {
            'pooled': 'Equal weight to the six fixed batch-seed by agent-orientation strata in the formal design.',
            'per_seed': 'Equal weight to the two agent-seed orientations within the named seed.',
            'replication_unit': 'Matched G0/G1 block; the two arms and mixed black/white goals are not independent samples.',
            'assumptions': 'Independent pseudorandom-stream block replication, arbitrary within-block dependence, heterogeneous fixed-stratum probabilities.',
            'scope': 'Hypothetical independent stream replication of this fixed design, not uncertainty in deterministic saved outcomes or a population of new seeds, agents, or policies.',
            'intervention': 'Entire early-pass rule intervention, including changed search, rollout choices, and trajectories; no isolated terminal-channel causal claim.',
            'pilot': 'All historical and pilot observations excluded; canonical new registered blocks only.',
        },
        'limits': [
            'Fixed sample only; no inference on partial outcomes, no data-dependent extension or replacement seeds.',
            'No p-values, significance flags, equivalence, noninferiority, rare-failure certification, or seven-by-seven gate from these intervals.',
            'Per-seed sign agreement is descriptive; three labels do not establish a population-of-seeds effect.',
            'Full integrity and replay validation must precede analysis; row validation is not an independent rules proof.',
            'Counts and denominators accompany all rates; all-success observations retain nonzero uncertainty.',
        ],
        'pooled': {}, 'per_seed': {},
    }
    for ib, iw in DIRECTIONS:
        direction = f'{ib}/{iw}'
        selected = [r for r in rows if (r['black_identity'], r['white_identity']) == (ib, iw)]
        result['pooled'][direction] = _group(selected, direction, simultaneous=True)
        for seed in p['batch_seeds']:
            subset = [r for r in selected if r['batch_seed'] == seed]
            result['per_seed'].setdefault(str(seed), {})[direction] = _group(subset, direction)
    return result


def planning_precision(n):
    """Outcome-free precision calculations, enumerating every feasible count.

    Maximum full width is not a symmetric radius around every point estimate.
    The concordant-cell split has no effect on the rectangle endpoints.
    """
    if type(n) is not int or n < 1:
        raise ValueError('positive integer n required')
    result = {'n_pairs': n, 'feasible_discordance_count_combinations': (n + 1) * (n + 2) // 2}
    for name, confidence in [('pointwise95', .95), ('joint_family8_95', INTERVAL_CONFIDENCE)]:
        component_confidence = 1 - (1 - confidence) / 2
        candidates = []
        for plus in range(n + 1):
            lp, up = clopper_pearson(plus, n, component_confidence)
            for minus in range(n - plus + 1):
                lm, um = clopper_pearson(minus, n, component_confidence)
                lo, hi, estimate = lp - um, up - lm, (plus - minus) / n
                candidates.append((hi - lo, max(hi - estimate, estimate - lo), plus, minus))
        maximum = max(v[0] for v in candidates)
        zero_upper = clopper_pearson(0, n, component_confidence)[1]
        result[name] = {
            'interval_confidence_level': confidence,
            'goal_component_two_sided_confidence_level': component_confidence,
            'goal_all_concordant_ci': [-zero_upper, zero_upper],
            'goal_maximum_full_width': maximum,
            'goal_maximum_distance_from_estimate': max(v[1] for v in candidates),
            'goal_full_width_maximizers_nplus_nminus': [[v[2], v[3]] for v in candidates if abs(v[0] - maximum) < 1e-14],
            'raw_length_unclipped_radius': bounded_mean_interval([0] * n, *RAW_LENGTH_SUPPORT, confidence)['unclipped_radius'],
            'goal_hoeffding_audit_radius': 2 * math.sqrt(math.log(2 / (1 - confidence)) / (2 * n)),
        }
    result['marginal_rate_all_success_pointwise95_ci'] = list(clopper_pearson(n, n))
    result['interpretation'] = 'Resource-bounded coarse fixed-sample estimation; no small-effect, equivalence, or rare-failure assurance; no automatic expansion.'
    return result
