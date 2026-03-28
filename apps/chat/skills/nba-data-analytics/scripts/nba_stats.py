"""Statistical testing helpers for NBA analytics.

Provides significance testing, confidence intervals, and streak analysis
using scipy.stats. All functions return JSON-serializable dicts.
"""

from __future__ import annotations

import math


def _to_list(data) -> list[float]:
    """Convert input to list of floats, handling pandas Series and arrays."""
    if hasattr(data, "tolist"):
        return [float(x) for x in data.tolist()]
    return [float(x) for x in data]


def is_significant(
    group_a,
    group_b,
    test: str = "auto",
    alpha: float = 0.05,
) -> dict:
    """Test whether two groups differ significantly.

    Parameters
    ----------
    group_a, group_b : array-like of numeric values
    test : 'auto', 'ttest', or 'mannwhitney'
    alpha : significance level (default 0.05)

    Returns
    -------
    dict with keys: significant, p_value, test_used, effect_size, summary
    """
    try:
        from scipy.stats import mannwhitneyu, shapiro, ttest_ind
    except ImportError:
        return {"error": "scipy not available", "significant": None}

    a = _to_list(group_a)
    b = _to_list(group_b)

    if len(a) < 3 or len(b) < 3:
        return {"error": "Need at least 3 observations per group", "significant": None}

    # Auto-select test based on normality
    if test == "auto":
        try:
            _, p_a = shapiro(a)
            _, p_b = shapiro(b)
            test = "ttest" if (p_a > 0.05 and p_b > 0.05) else "mannwhitney"
        except Exception:
            test = "mannwhitney"

    if test == "ttest":
        stat, p_value = ttest_ind(a, b, equal_var=False)
        test_name = "Welch's t-test"
    else:
        stat, p_value = mannwhitneyu(a, b, alternative="two-sided")
        test_name = "Mann-Whitney U"

    # Cohen's d effect size
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    var_a = sum((x - mean_a) ** 2 for x in a) / max(len(a) - 1, 1)
    var_b = sum((x - mean_b) ** 2 for x in b) / max(len(b) - 1, 1)
    pooled_df = (len(a) - 1) + (len(b) - 1)
    pooled_variance = (
        ((len(a) - 1) * var_a + (len(b) - 1) * var_b) / pooled_df if pooled_df > 0 else 0.0
    )
    pooled_std = math.sqrt(pooled_variance) if pooled_variance > 0 else 0.0
    effect_size = abs(mean_a - mean_b) / pooled_std if pooled_std > 0 else 0.0

    if effect_size < 0.2:
        effect_label = "negligible"
    elif effect_size < 0.5:
        effect_label = "small"
    elif effect_size < 0.8:
        effect_label = "medium"
    else:
        effect_label = "large"

    p_value = float(p_value)
    significant = bool(p_value < alpha)
    summary = (
        f"{'Significant' if significant else 'Not significant'} difference "
        f"(p={p_value:.4f}, {test_name}). "
        f"Effect size: {effect_size:.2f} ({effect_label}). "
        f"Group means: {mean_a:.2f} vs {mean_b:.2f}."
    )

    return {
        "significant": significant,
        "p_value": round(p_value, 6),
        "test_used": test_name,
        "effect_size": round(effect_size, 3),
        "effect_label": effect_label,
        "mean_a": round(mean_a, 3),
        "mean_b": round(mean_b, 3),
        "n_a": len(a),
        "n_b": len(b),
        "summary": summary,
    }


def shooting_confidence(
    makes: int,
    attempts: int,
    confidence: float = 0.95,
    method: str = "wilson",
) -> dict:
    """Confidence interval for a shooting percentage.

    Uses Wilson score interval (better than normal approximation for small samples).
    """
    if attempts <= 0:
        return {"pct": 0.0, "lower": 0.0, "upper": 0.0, "confidence": confidence}

    pct = makes / attempts

    if method == "wilson":
        try:
            from scipy.stats import norm

            z = norm.ppf(1 - (1 - confidence) / 2)
        except ImportError:
            z = 1.96  # fallback for 95%

        denom = 1 + z**2 / attempts
        center = (pct + z**2 / (2 * attempts)) / denom
        margin = z * math.sqrt((pct * (1 - pct) + z**2 / (4 * attempts)) / attempts) / denom
        lower = max(0.0, center - margin)
        upper = min(1.0, center + margin)
    else:
        # Normal approximation fallback
        se = math.sqrt(pct * (1 - pct) / attempts) if pct > 0 and pct < 1 else 0
        lower = max(0.0, pct - 1.96 * se)
        upper = min(1.0, pct + 1.96 * se)

    return {
        "pct": round(pct, 4),
        "lower": round(lower, 4),
        "upper": round(upper, 4),
        "confidence": confidence,
        "makes": makes,
        "attempts": attempts,
    }


def breakout_threshold(series, sigma: float = 2.0) -> dict:
    """Identify outlier performances N standard deviations above the mean.

    For DataFrame or game-log workflows, use trends.find_breakouts().

    Parameters
    ----------
    series : array-like of numeric values (e.g., points per game)
    sigma : number of standard deviations above mean to qualify as breakout

    Returns
    -------
    dict with threshold, breakout indices, mean, std
    """
    values = _to_list(series)
    if len(values) < 5:
        return {"error": "Need at least 5 observations", "breakout_indices": []}

    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    threshold = mean + sigma * std

    breakout_indices = [i for i, v in enumerate(values) if v >= threshold]

    return {
        "mean": round(mean, 2),
        "std": round(std, 2),
        "threshold": round(threshold, 2),
        "sigma": sigma,
        "breakout_count": len(breakout_indices),
        "breakout_indices": breakout_indices,
        "total_games": len(values),
    }


def streak_significance(outcomes, direction: str = "hot") -> dict:
    """Test whether observed streaks differ from random expectation.

    Parameters
    ----------
    outcomes : array-like of binary values (1=success, 0=failure)
    direction : 'hot' (test for clustering) or 'cold'

    Returns
    -------
    dict with longest streak, expected streak length, p-value (if scipy available).

    Note
    ----
    The runs-test p-value is omnibus/two-sided regardless of direction. The
    direction only changes which outcome is counted for the longest and expected
    streak metrics.
    """
    vals = [int(x) for x in _to_list(outcomes)]
    n = len(vals)
    if n < 10:
        return {"error": "Need at least 10 observations", "significant": None}

    # Count longest streak
    target = 1 if direction == "hot" else 0
    longest = 0
    current = 0
    for v in vals:
        if v == target:
            current += 1
            longest = max(longest, current)
        else:
            current = 0

    # Count runs (alternating sequences)
    runs = 1
    for i in range(1, n):
        if vals[i] != vals[i - 1]:
            runs += 1

    n_success = sum(vals)
    n_fail = n - n_success
    p = n_success / n if n > 0 else 0.5

    # Expected longest streak (geometric distribution approximation)
    if 0 < p < 1:
        log_base = math.log(p) if direction == "hot" else math.log(1 - p)
        expected_longest = math.log(n) / abs(log_base)
    elif (p == 1 and direction == "hot") or (p == 0 and direction == "cold"):
        expected_longest = n
    else:
        expected_longest = 0

    # Runs test for significance
    p_value = None
    try:
        if n_success > 0 and n_fail > 0:
            expected_runs = 1 + (2 * n_success * n_fail) / n
            var_runs = (2 * n_success * n_fail * (2 * n_success * n_fail - n)) / (n**2 * (n - 1))
            if var_runs > 0:
                z = (runs - expected_runs) / math.sqrt(var_runs)
                try:
                    from scipy.stats import norm

                    p_value = round(2 * norm.sf(abs(z)), 6)
                except ImportError:
                    pass
    except (ZeroDivisionError, ValueError):
        pass

    return {
        "longest_streak": longest,
        "expected_longest": (
            round(expected_longest, 1) if isinstance(expected_longest, float) else expected_longest
        ),
        "total_observations": n,
        "success_rate": round(p, 4),
        "num_runs": runs,
        "p_value": p_value,
        "direction": direction,
        "significant": p_value < 0.05 if p_value is not None else None,
    }
