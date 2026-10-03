"""Fixed-sample estimation for balanced, paired G0 budget comparisons.

Primary CI: let D_i = Y_comparison,i - Y_baseline,i, and let N+ and N-
count D_i=1 and D_i=-1. Construct TWO-SIDED equal-tail Clopper-Pearson
intervals [L+, U+] and [L-, U-], each at confidence 1-alpha/2. Return
[L+ - U-, U+ - L-]. The union bound gives coverage at least 1-alpha;
independence between N+ and N- is neither assumed nor needed.

For independent nonidentical Bernoulli trials, two-sided CP at confidence
beta >= 1/2 covers the average success probability: Mattner & Tasto (2015),
Probability and Mathematical Statistics 35(2), 301-312, Theorem 1.3
(Theorem 1.12 in arXiv:1403.0229v3, https://arxiv.org/pdf/1403.0229).
Their condition beta >= 2*beta_n-1 is satisfied by beta >= 1/2 (n=1 is
also allowed). This result DOES NOT generally hold for one-sided CP.
The difference construction above is a union-bound projection of that
result, not a named optimal paired-proportions interval.

Each matched block is an independent pseudorandom-stream replicate under
the simulation model; budget outcomes within a block may be arbitrarily
dependent. Fixed seed/orientation strata may have different probabilities.
Equal cell counts make the pooled mean the equal-weight mean of those fixed
strata. CIs do not generalize to a population of agent seeds, policies, or
unrun batch seeds. Deterministic fixed seed results themselves have no
sampling uncertainty; the CIs describe hypothetical independent stream
replications under the stated model.

All intervals are fixed-sample. Marginal 95% intervals are not simultaneous
across endpoints, budgets, or seeds. The separately labelled family interval
uses alpha/6 for the six formal pooled primary comparisons. No tests,
p-values, significance flags, interim efficacy looks, or stopping decisions.
Hoeffding audit: D in [-1,1] gives radius sqrt(2*log(2/alpha)/n).
Source: Hoeffding (1963), Probability inequalities for sums of bounded random
variables, JASA 58, 13-30, https://doi.org/10.1080/01621459.1963.10500830.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import math
import statistics

from scipy.stats import beta


PRIMARY_ENDPOINTS = {
    'LOSE/LOSE': 'black_realized_all_pass',
    'WIN/LOSE': 'black_one_stone_double_pass',
    'LOSE/WIN': 'empty_double_pass',
}
CI_METHOD = 'paired_discordance_two_sided_CP_rectangle_Bonferroni'
CP_SOURCE = 'https://arxiv.org/pdf/1403.0229'
HOEFFDING_SOURCE = 'https://doi.org/10.1080/01621459.1963.10500830'


def _confidence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
        raise ValueError('confidence must be a finite number strictly between 0 and 1')


@lru_cache(maxsize=4096, typed=True)
def clopper_pearson(k, n, confidence=.95):
    """Equal-tail CP limits; heterogeneous-average validity requires >=.5."""
    if type(n) is not int or type(k) is not int or not 0 <= k <= n or n < 1:
        raise ValueError('require integer n >= 1 and 0 <= k <= n')
    _confidence(confidence)
    if confidence < .5:
        raise ValueError('heterogeneous-average CP confidence must be at least .5')
    tail = (1 - confidence) / 2
    lower = 0.0 if k == 0 else float(beta.ppf(tail, k, n - k + 1))
    upper = 1.0 if k == n else float(beta.ppf(1 - tail, k + 1, n - k))
    # Outward rounding avoids accidentally tightening reported boundaries.
    return (max(0.0, math.nextafter(lower, -math.inf)),
            min(1.0, math.nextafter(upper, math.inf)))


def _binary(values):
    values = list(values)
    if not values or any(type(v) not in (bool, int) or v not in (0, 1) for v in values):
        raise ValueError('nonempty binary observations required')
    return [int(v) for v in values]


def paired_rate_difference(baseline_values, comparison_values, confidence=.95):
    """Paired rate difference; the tuple counts use (baseline, comparison)."""
    _confidence(confidence)
    baseline, comparison = _binary(baseline_values), _binary(comparison_values)
    if len(baseline) != len(comparison):
        raise ValueError('paired vectors must have equal lengths')
    n = len(baseline)
    counts = Counter(zip(baseline, comparison))
    positive, negative = counts[0, 1], counts[1, 0]
    component_confidence = 1 - (1 - confidence) / 2
    lp, up = clopper_pearson(positive, n, component_confidence)
    lm, um = clopper_pearson(negative, n, component_confidence)
    estimate = (positive - negative) / n
    interval = [max(-1.0, lp - um), min(1.0, up - lm)]
    radius = math.sqrt(2 * math.log(2 / (1 - confidence)) / n)
    audit = [max(-1.0, estimate - radius), min(1.0, estimate + radius)]
    result = {'n': n, 'baseline_successes': sum(baseline),
              'comparison_successes': sum(comparison),
              'n00': counts[0, 0], 'n01': positive, 'n10': negative, 'n11': counts[1, 1],
              'discordant_pairs': positive + negative, 'estimate': estimate,
              'confidence_level': confidence, 'ci': interval,
              'component_confidence_level': component_confidence,
              'positive_probability_ci': [lp, up], 'negative_probability_ci': [lm, um],
              'method': CI_METHOD, 'hoeffding_ci': audit,
              'hoeffding_radius': radius}
    if confidence == .95:
        result.update(ci95=interval, ci95_hoeffding=audit)
    return result


def rate_estimate(values, confidence=.95):
    """Rate of the fixed mixture of independent stream replicates."""
    values = _binary(values)
    k, n = sum(values), len(values)
    return {'successes': k, 'n': n, 'estimate': k / n,
            'confidence_level': confidence, 'ci': list(clopper_pearson(k, n, confidence)),
            'method': 'two_sided_Clopper_Pearson_average_probability'}


def _distribution(values):
    values = sorted(values)
    if not values:
        raise ValueError('nonempty observations required')
    def quantile(q):
        index = (len(values) - 1) * q
        low = int(index)
        high = min(low + 1, len(values) - 1)
        return values[low] + (values[high] - values[low]) * (index - low)
    return {'n': len(values), 'mean': statistics.mean(values),
            **{name: quantile(q) for name, q in
               [('min', 0), ('q1', .25), ('median', .5), ('q3', .75),
                ('p90', .9), ('p95', .95), ('max', 1)]}}


def _endpoints(row):
    """Endpoints are recomputed from the realized full action sequence."""
    actions = row['actions']
    if (not isinstance(actions, list) or not 2 <= len(actions) <= 100
            or any(type(a) is not int or not 0 <= a <= 25 for a in actions)
            or type(row['move_count']) is not int or row['move_count'] != len(actions)):
        raise ValueError('invalid realized action sequence or move count')
    if row['winner'] not in ('black', 'white'):
        raise ValueError('G0 has no draws')
    if any(type(row[c + '_utility']) not in (int, float)
           or row[c + '_utility'] not in (-1, 1) for c in ('black', 'white')):
        raise ValueError('invalid G0 utility')
    if row['termination_reason'] not in ('double_pass', 'move_limit'):
        raise ValueError('invalid G0 termination reason')
    return {
        'black_realized_all_pass': all(a == 25 for a in actions[::2]),
        'black_one_stone_double_pass': len(actions) == 3 and actions[0] < 25 and actions[1:] == [25, 25],
        'empty_double_pass': actions == [25, 25],
        'literal_one_stone_a0': actions == [0, 25, 25],
        'black_board_wins': row['winner'] == 'black',
        'white_board_wins': row['winner'] == 'white',
        'black_goals': row['black_utility'] == 1,
        'white_goals': row['white_utility'] == 1,
        'joint_goals': row['black_utility'] == row['white_utility'] == 1,
        'length2': len(actions) == 2, 'length3': len(actions) == 3,
        'length_le8': len(actions) <= 8, 'length_ge60': len(actions) >= 60,
        'move_limit': row['termination_reason'] == 'move_limit',
    }


def _validate_rows(rows, p):
    budgets, seeds = p['budgets'], p['batch_seeds']
    directions = [tuple(x) for x in p['identity_directions']]
    orientations = [tuple(x) for x in p['agent_seed_orientations']]
    n = p['games_per_cell']
    if (not budgets or len(budgets) < 2 or len(set(budgets)) != len(budgets)
            or any(type(b) is not int or b <= 0 for b in budgets)
            or budgets != sorted(budgets) or not seeds or len(set(seeds)) != len(seeds)
            or any(type(s) is not int or s < 0 for s in seeds)
            or directions != [('WIN', 'WIN'), ('LOSE', 'LOSE'), ('WIN', 'LOSE'), ('LOSE', 'WIN')]
            or orientations != [(1, 2), (2, 1)] or type(n) is not int or n < 1):
        raise ValueError('invalid balanced G0 design')
    expected = {(b, s, *d, *o, r) for b in budgets for s in seeds
                for d in directions for o in orientations for r in range(n)}
    if p['planned_games'] != len(expected) or len(rows) != len(expected):
        raise ValueError('complete registered sample required; no silent reweighting')
    indexed, block_ids, game_seeds = {}, {}, {}
    for row in rows:
        keys = ('budget', 'batch_seed', 'black_identity', 'white_identity',
                'black_seed', 'white_seed', 'replicate')
        if any(type(row[k]) is not int for k in ('budget', 'batch_seed', 'black_seed', 'white_seed', 'replicate')):
            raise ValueError('noninteger design key')
        key = tuple(row[k] for k in keys)
        if key not in expected or key in indexed:
            raise ValueError('duplicate or unregistered design cell')
        block = key[1:]
        block_id, game_seed = row['block_id'], row['game_seed']
        if not isinstance(block_id, str) or not block_id or type(game_seed) is not int or game_seed < 0:
            raise ValueError('invalid block or game seed')
        for value, seen in ((block_id, block_ids), (game_seed, game_seeds)):
            if value in seen and seen[value] != block:
                raise ValueError('block ID or game seed reused across distinct design blocks')
            seen[value] = block
        indexed[key] = dict(row, _endpoint_values=_endpoints(row))
    if set(indexed) != expected:
        raise ValueError('incomplete registered sample')
    for key, row in indexed.items():
        base = indexed[(budgets[0],) + key[1:]]
        if row['block_id'] != base['block_id'] or row['game_seed'] != base['game_seed']:
            raise ValueError('budget pairing disagrees on block ID or game seed')
    return list(indexed.values())


def _group(rows, budgets, direction, family_size=None):
    result = {'identity_direction': direction, 'primary_endpoint': PRIMARY_ENDPOINTS.get(direction),
              'n_per_budget': len(rows) // len(budgets), 'budgets': {}, 'contrasts': {}}
    by_budget = {}
    key = lambda row: (row['batch_seed'], row['black_seed'], row['white_seed'], row['replicate'])
    for budget in budgets:
        group = sorted((r for r in rows if r['budget'] == budget), key=key)
        by_budget[budget] = group
        result['budgets'][str(budget)] = {
            'n': len(group),
            'rates': {name: rate_estimate(r['_endpoint_values'][name] for r in group)
                      for name in group[0]['_endpoint_values']},
            'length': _distribution([r['move_count'] for r in group]),
        }
    comparisons = [(budget, baseline) for i, baseline in enumerate(budgets)
                   for budget in budgets[i + 1:]]
    for budget, baseline in comparisons:
        base = by_budget[baseline]
        comparison = by_budget[budget]
        if [key(r) for r in base] != [key(r) for r in comparison]:
            raise ValueError('paired block order mismatch')
        rates = {}
        for name in base[0]['_endpoint_values']:
            aa = [r['_endpoint_values'][name] for r in base]
            bb = [r['_endpoint_values'][name] for r in comparison]
            rates[name] = paired_rate_difference(aa, bb)
            if family_size and baseline == budgets[0] and name == PRIMARY_ENDPOINTS.get(direction):
                adjusted = paired_rate_difference(aa, bb, 1 - .05 / family_size)
                rates[name]['simultaneous_primary_ci95'] = adjusted['ci']
                rates[name]['simultaneous_family_size'] = family_size
                rates[name]['simultaneous_component_confidence_level'] = adjusted['component_confidence_level']
        result['contrasts'][f'{budget}-{baseline}'] = {
            'comparison_budget': budget, 'baseline_budget': baseline,
            'contrast_role': 'primary_budget_contrast' if baseline == budgets[0] else 'secondary_budget_contrast',
            'rates': rates,
            'length_delta': _distribution([b['move_count'] - a['move_count'] for a, b in zip(base, comparison)]),
            'length_delta_inference': 'descriptive_only',
        }
    return result


def _mixed_same_lengths(rows, budgets):
    """Descriptive across-direction comparisons, with no cross-direction pairs."""
    result = {}
    for budget in budgets:
        available = [r for r in rows if r['budget'] == budget]
        versions = {}
        for label, selected in [('all_games', available),
                                ('exclude_length2_3', [r for r in available if r['move_count'] > 3])]:
            mixed = [r['move_count'] for r in selected if r['black_identity'] != r['white_identity']]
            same = [r['move_count'] for r in selected if r['black_identity'] == r['white_identity']]
            versions[label] = {
                'mixed_n': len(mixed), 'same_n': len(same),
                'mixed': _distribution(mixed) if mixed else None,
                'same': _distribution(same) if same else None,
                'mixed_minus_same_mean': statistics.mean(mixed) - statistics.mean(same) if mixed and same else None,
                'identity_denominators': {f'{ib}/{iw}': sum((r['black_identity'], r['white_identity']) == (ib, iw)
                                                         for r in selected)
                                          for ib, iw in [('WIN', 'WIN'), ('LOSE', 'LOSE'), ('WIN', 'LOSE'), ('LOSE', 'WIN')]},
                'inference': 'descriptive_only; no pairing across identity directions',
            }
        versions['sensitivity_limit'] = ('Excluding realized 2-3 ply games is post-outcome selection; retained-cell '
                                         'weights may differ. This is a descriptive sensitivity, not a causal adjustment.')
        result[str(budget)] = versions
    return result


def analyze_rows(rows, p):
    """Analyze ONLY a complete balanced registered sample; never mutate rows.

    Rows contain d1.describe_game fields plus all d1.cells fields and game_seed.
    The first listed (smallest) budget is baseline. This also supports reduced
    protocols used in runner tests; their simultaneous family has 3*(B-1) CIs.
    """
    rows = _validate_rows(list(rows), p)
    budgets, seeds = p['budgets'], p['batch_seeds']
    family_size = 3 * (len(budgets) - 1)
    result = {
        'analysis_version': 'paired-fixed-strata-cp-v1', 'estimation_only': True,
        'n_records': len(rows), 'complete_registered_sample': True,
        'intervals': {
            'confidence_level': .95, 'paired_primary_method': CI_METHOD,
            'coverage': 'at least nominal under independent matched-block stream replications',
            'source': CP_SOURCE, 'source_theorem': 'published 1.3; arXiv v3 1.12',
            'audit_method': 'Hoeffding independent bounded differences', 'audit_source': HOEFFDING_SOURCE,
            'multiplicity': 'Marginal 95% CIs are not simultaneous. Only simultaneous_primary_ci95 covers the pooled primary family.',
            'simultaneous_primary_family_size': family_size,
            'family': [{'direction': d, 'endpoint': e, 'comparison_budget': b, 'baseline_budget': budgets[0]}
                       for d, e in PRIMARY_ENDPOINTS.items() for b in budgets[1:]],
        },
        'estimand': {
            'pooled': 'Equal-weight average of the fixed batch-seed by agent-orientation strata in each identity direction.',
            'per_seed': 'Equal-weight average of the two fixed agent-seed orientations within the named batch seed.',
            'replication_unit': 'Matched game block across budgets; identity directions are never paired.',
            'assumptions': 'Independent pseudorandom streams across distinct game blocks; arbitrary within-block budget dependence and stratum heterogeneity.',
            'boundaries': 'Conditional on the two fixed agent seeds and tested batch-seed/orientation design; no population-of-agent-seeds, learning, convergence, or off-path-policy claim.',
            'pilot': 'Prior 72-game cost pilot excluded.',
        },
        'pooled': {}, 'per_seed': {}, 'per_stratum': {},
        'mixed_same_length': {
            'pooled': _mixed_same_lengths(rows, budgets),
            'per_seed': {str(seed): _mixed_same_lengths([r for r in rows if r['batch_seed'] == seed], budgets)
                         for seed in seeds},
        },
    }
    for ib, iw in p['identity_directions']:
        direction = f'{ib}/{iw}'
        selected = [r for r in rows if (r['black_identity'], r['white_identity']) == (ib, iw)]
        result['pooled'][direction] = _group(selected, budgets, direction, family_size)
        for seed in seeds:
            sr = [r for r in selected if r['batch_seed'] == seed]
            result['per_seed'].setdefault(str(seed), {})[direction] = _group(sr, budgets, direction)
            for sb, sw in p['agent_seed_orientations']:
                rr = [r for r in sr if (r['black_seed'], r['white_seed']) == (sb, sw)]
                label = f'{seed}:{sb},{sw}'
                result['per_stratum'].setdefault(label, {})[direction] = _group(rr, budgets, direction)
    return result
