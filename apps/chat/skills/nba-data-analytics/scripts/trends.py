"""Trend and streak detection helpers for NBA analytics.

Rolling averages, streak detection, breakout identification,
and season projections.
"""

from __future__ import annotations

import math

import pandas as pd


def rolling_stats(
    df: pd.DataFrame,
    stat_cols: list[str],
    window: int = 10,
    date_col: str = "game_date",
) -> pd.DataFrame:
    """Add rolling average columns for specified stats.

    Parameters
    ----------
    df : game-log DataFrame (one row per game)
    stat_cols : columns to compute rolling averages for
    window : rolling window size
    date_col : date column for sorting
    """
    result = df.sort_values(date_col).copy()
    for col in stat_cols:
        if col in result.columns:
            result[f"{col}_rolling_{window}"] = (
                result[col].rolling(window=window, min_periods=1).mean().round(2)
            )
    return result


def detect_streaks(
    df: pd.DataFrame,
    stat_col: str,
    threshold: float,
    direction: str = "above",
    date_col: str = "game_date",
) -> pd.DataFrame:
    """Find consecutive-game streaks where a stat exceeds/falls below a threshold.

    Returns DataFrame with streak_id, start/end dates, length, and avg value.
    """
    sorted_df = df.sort_values(date_col).copy()

    if direction == "above":
        mask = sorted_df[stat_col] >= threshold
    else:
        mask = sorted_df[stat_col] <= threshold

    # Assign streak IDs
    sorted_df["_qualifies"] = mask
    sorted_df["_streak_break"] = sorted_df["_qualifies"] != sorted_df["_qualifies"].shift(1)
    sorted_df["_streak_id"] = sorted_df["_streak_break"].cumsum()

    # Filter to qualifying streaks
    qualifying = sorted_df[sorted_df["_qualifies"]]
    if qualifying.empty:
        return pd.DataFrame(columns=["streak_id", "start_date", "end_date", "length", "avg_value"])

    streaks = (
        qualifying.groupby("_streak_id")
        .agg(
            start_date=(date_col, "first"),
            end_date=(date_col, "last"),
            length=(stat_col, "count"),
            avg_value=(stat_col, "mean"),
            max_value=(stat_col, "max"),
        )
        .reset_index(drop=True)
    )
    streaks["avg_value"] = streaks["avg_value"].round(2)
    streaks["max_value"] = streaks["max_value"].round(2)
    streaks = streaks.sort_values("length", ascending=False).reset_index(drop=True)
    streaks.index.name = "streak_id"
    return streaks.reset_index()


def find_breakouts(
    df: pd.DataFrame,
    stat_col: str,
    sigma: float = 2.0,
    min_games: int = 20,
    date_col: str = "game_date",
) -> pd.DataFrame:
    """Identify outlier games N standard deviations above the season mean.

    Requires at least min_games for a stable baseline.
    """
    if len(df) < min_games:
        return pd.DataFrame({"error": [f"Need at least {min_games} games, got {len(df)}"]})

    values = df[stat_col].dropna()
    mean = float(values.mean())
    std = float(values.std())
    threshold = mean + sigma * std

    result = df[df[stat_col] >= threshold].copy()
    if date_col in result.columns:
        result = result.sort_values(date_col, ascending=False)

    result["_mean"] = round(mean, 2)
    result["_std"] = round(std, 2)
    result["_threshold"] = round(threshold, 2)
    result["_sigma_above"] = ((result[stat_col] - mean) / std).round(2) if std > 0 else 0

    return result


def season_projection(
    current_stats: dict | pd.Series,
    games_played: int,
    total_games: int = 82,
) -> dict:
    """Pace-based 82-game projection with confidence intervals.

    Parameters
    ----------
    current_stats : dict of {stat_name: total_value} (season totals)
    games_played : games played so far
    total_games : games to project to (default 82)

    Returns
    -------
    dict with projected totals and per-game averages
    """
    if games_played <= 0:
        return {"error": "No games played"}

    if isinstance(current_stats, pd.Series):
        current_stats = current_stats.to_dict()

    result = {"games_played": games_played, "total_games": total_games}
    projections = {}

    for stat, total in current_stats.items():
        total = float(total)
        per_game = total / games_played
        projected_total = per_game * total_games
        remaining = total_games - games_played

        # Simple confidence interval based on binomial-like variance
        # Wider CI with fewer games played
        games_factor = math.sqrt(remaining / games_played) if games_played > 0 else 1
        margin = per_game * games_factor * 1.96  # ~95% CI approximation

        projections[stat] = {
            "current_total": round(total, 1),
            "per_game": round(per_game, 2),
            "projected_total": round(projected_total, 1),
            "projected_low": round(projected_total - margin * remaining, 1),
            "projected_high": round(projected_total + margin * remaining, 1),
        }

    result["projections"] = projections
    return result
