"""Forecast evaluation and hedge-effectiveness tools (standard library only).

The rule these functions enforce: a model "wins" only if the confidence
interval on its loss improvement over a baseline excludes zero. Anything else
is reported as no detected difference.

Contents
- scoring: mae, rmse, pinball, brier, reliability, interval_coverage
- uncertainty: block_bootstrap_ci (moving-block, respects autocorrelation), compare
- modelling: fit_ridge / predict (small linear models, no numpy)
- hedging: hedge_effectiveness, min_variance_ratio, out_of_sample_hedge
"""

import math
import random

MIN_N_FOR_VERDICT = 30


# ------------------------------------------------------------------ scoring
def mae(y, p):
    return sum(abs(a - b) for a, b in zip(y, p)) / len(y)


def rmse(y, p):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(y, p)) / len(y))


def pinball(y, q, tau):
    """Pinball (quantile) loss for one observation. tau in (0,1)."""
    d = y - q
    return tau * d if d >= 0 else (tau - 1) * d


def brier(probs, outcomes):
    """Mean squared error of probabilities against 0/1 outcomes. 0 is perfect; 0.25 is always-50%."""
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs)


def reliability(probs, outcomes, bins=10):
    """Calibration table. Each row: bin range, count, mean forecast, observed frequency."""
    rows = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(probs) if (lo <= p < hi) or (b == bins - 1 and p == 1.0)]
        if not idx:
            rows.append({"lo": lo, "hi": hi, "n": 0, "mean_p": None, "freq": None})
            continue
        rows.append({
            "lo": lo, "hi": hi, "n": len(idx),
            "mean_p": sum(probs[i] for i in idx) / len(idx),
            "freq": sum(outcomes[i] for i in idx) / len(idx),
        })
    return rows


def interval_coverage(lo, hi, y):
    """Share of observations inside [lo, hi]. For a stated 80% interval this should be near 0.80."""
    pairs = [(a, b, c) for a, b, c in zip(lo, hi, y) if a is not None and b is not None]
    if not pairs:
        return None
    return sum(1 for a, b, c in pairs if a <= c <= b) / len(pairs)


# -------------------------------------------------------------- uncertainty
def block_bootstrap_ci(values, block=7, n_boot=2000, alpha=0.05, seed=0):
    """Moving-block bootstrap CI for the mean. Returns (mean, lo, hi)."""
    n = len(values)
    if n == 0:
        raise ValueError("no values")
    m = sum(values) / n
    block = max(1, min(block, n))
    rnd = random.Random(seed)
    n_blocks = math.ceil(n / block)
    means = []
    for _ in range(n_boot):
        s = 0.0
        cnt = 0
        for _b in range(n_blocks):
            start = rnd.randint(0, n - block)
            seg = values[start:start + block]
            s += sum(seg)
            cnt += len(seg)
        means.append(s / cnt)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return m, lo, hi


def compare(loss_model, loss_baseline, block=7, n_boot=2000, seed=0):
    """Paired comparison of per-step losses (lower is better).

    diff = loss_model - loss_baseline, so a negative mean means the model is better.
    Verdict is 'model_better' only if the whole CI is below zero.
    """
    if len(loss_model) != len(loss_baseline):
        raise ValueError("loss series must be the same length")
    n = len(loss_model)
    if n < MIN_N_FOR_VERDICT:
        return {"n": n, "verdict": "insufficient_data", "mean_diff": None, "ci_lo": None, "ci_hi": None}
    diffs = [a - b for a, b in zip(loss_model, loss_baseline)]
    m, lo, hi = block_bootstrap_ci(diffs, block=block, n_boot=n_boot, seed=seed)
    verdict = "model_better" if hi < 0 else ("baseline_better" if lo > 0 else "no_difference_detected")
    return {
        "n": n, "mean_diff": m, "ci_lo": lo, "ci_hi": hi, "verdict": verdict,
        "mean_loss_model": sum(loss_model) / n, "mean_loss_baseline": sum(loss_baseline) / n,
    }


# ---------------------------------------------------------------- modelling
def _solve(A, b):
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            raise ValueError("singular system")
        M[c], M[piv] = M[piv], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            if f:
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x


def fit_ridge(X, y, lam=1e-6):
    """Least squares with a tiny ridge term. X rows must include an intercept column of 1s at index 0."""
    k = len(X[0])
    A = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for row, t in zip(X, y):
        for i in range(k):
            b[i] += row[i] * t
            for j in range(k):
                A[i][j] += row[i] * row[j]
    for i in range(1, k):  # do not shrink the intercept
        A[i][i] += lam
    return _solve(A, b)


def predict(coef, row):
    return sum(c * x for c, x in zip(coef, row))


# ------------------------------------------------------------------ hedging
def _var(v):
    m = sum(v) / len(v)
    return sum((x - m) ** 2 for x in v) / (len(v) - 1)


def hedge_effectiveness(exposure_pnl, hedge_pnl, ratio=1.0, tail=0.05):
    """Compare unhedged vs hedged profit and loss. Both series are signed P&L per period.

    effectiveness = 1 - Var(hedged) / Var(unhedged). 1 is a perfect hedge, 0 is no
    effect, negative means the hedge added risk. Tail loss is the mean of the worst
    `tail` share of periods.
    """
    if len(exposure_pnl) != len(hedge_pnl) or len(exposure_pnl) < 3:
        raise ValueError("need equal-length series of at least 3 periods")
    hedged = [e + ratio * h for e, h in zip(exposure_pnl, hedge_pnl)]
    k = max(1, int(len(hedged) * tail))
    tail_loss = lambda s: sum(sorted(s)[:k]) / k
    vu, vh = _var(exposure_pnl), _var(hedged)
    return {
        "n": len(hedged), "ratio": ratio,
        "var_unhedged": vu, "var_hedged": vh,
        "effectiveness": 1 - vh / vu if vu > 0 else None,
        "worst_unhedged": min(exposure_pnl), "worst_hedged": min(hedged),
        "tail_mean_unhedged": tail_loss(exposure_pnl), "tail_mean_hedged": tail_loss(hedged),
        "mean_unhedged": sum(exposure_pnl) / len(exposure_pnl), "mean_hedged": sum(hedged) / len(hedged),
    }


def min_variance_ratio(exposure_pnl, hedge_pnl):
    """Ratio h minimising Var(exposure + h * hedge): -Cov(E, H) / Var(H)."""
    n = len(exposure_pnl)
    me, mh = sum(exposure_pnl) / n, sum(hedge_pnl) / n
    cov = sum((e - me) * (h - mh) for e, h in zip(exposure_pnl, hedge_pnl)) / (n - 1)
    vh = _var(hedge_pnl)
    return -cov / vh if vh > 0 else 0.0


def out_of_sample_hedge(exposure_pnl, hedge_pnl, split):
    """Fit the hedge ratio on periods [:split], report effectiveness on periods [split:]."""
    ratio = min_variance_ratio(exposure_pnl[:split], hedge_pnl[:split])
    res = hedge_effectiveness(exposure_pnl[split:], hedge_pnl[split:], ratio=ratio)
    res["fitted_on"] = split
    return res
