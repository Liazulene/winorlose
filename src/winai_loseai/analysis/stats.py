"""Small statistics helpers (pure stdlib; deterministic bootstrap)."""

from __future__ import annotations

import math

from ..rng import make_analysis_rng


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def std(xs):
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def describe(xs):
    xs = sorted(float(x) for x in xs)
    n = len(xs)
    if n == 0:
        return {"n": 0}
    def q(p):
        if n == 1:
            return xs[0]
        k = (n - 1) * p
        lo = int(math.floor(k))
        hi = int(math.ceil(k))
        return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
    return {
        "n": n,
        "mean": sum(xs) / n,
        "sd": std(xs),
        "min": xs[0],
        "q25": q(0.25),
        "median": q(0.5),
        "q75": q(0.75),
        "max": xs[-1],
        "sum": sum(xs),
    }


def normal_ci_95(xs):
    """Normal-approximation 95% CI for the mean."""
    xs = list(xs)
    if len(xs) == 0:
        return None
    m = mean(xs)
    s = std(xs)
    se = s / math.sqrt(len(xs))
    return {"mean": m, "ci95_low": m - 1.959963984540054 * se,
            "ci95_high": m + 1.959963984540054 * se, "n": len(xs)}


def bootstrap_ci_diff_mean(a, b, n_boot=2000, seed=12345, alpha=0.05):
    """Bootstrap percentile CI for ``mean(a) - mean(b)``.

    ``a`` / ``b`` are the raw value lists; the two samples are *not* pooled
    (bootstrap each, subtract).  Deterministic thanks to a fixed seed stream.
    """
    a = list(a)
    b = list(b)
    if not a or not b:
        return None
    rng = make_analysis_rng(seed)
    na, nb = len(a), len(b)
    diffs = []
    for _ in range(n_boot):
        sa = sum(a[rng.randrange(na)] for _ in range(na)) / na
        sb = sum(b[rng.randrange(nb)] for _ in range(nb)) / nb
        diffs.append(sa - sb)
    diffs.sort()
    lo = diffs[int(round(alpha / 2 * n_boot))]
    hi = diffs[int(round((1 - alpha / 2) * n_boot))]
    return {
        "mean_a": mean(a),
        "mean_b": mean(b),
        "diff_mean": mean(a) - mean(b),
        "ci95_low": lo,
        "ci95_high": hi,
        "n_a": na,
        "n_b": nb,
    }
