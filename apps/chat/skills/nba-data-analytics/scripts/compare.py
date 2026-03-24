"""Player comparison framework for NBA analytics.

Provides side-by-side comparisons, percentile rankings, radar charts,
and per-minute normalization.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import matplotlib.figure


def compare_players(
    df: pd.DataFrame,
    player_col: str = "full_name",
    metrics: list[str] | None = None,
) -> pd.DataFrame:
    """Side-by-side comparison table with league average row.

    Parameters
    ----------
    df : DataFrame with one row per player
    player_col : column containing player names
    metrics : columns to compare (auto-detects numeric if None)
    """
    if metrics is None:
        metrics = [c for c in df.select_dtypes(include="number").columns if c != "player_id"]

    result = df.set_index(player_col)[metrics].copy()
    result.loc["League Avg"] = result.mean()
    return result.round(2)


def percentile_rank(
    df: pd.DataFrame,
    player_col: str = "full_name",
    metrics: list[str] | None = None,
    ascending_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Compute percentile rankings (0-100) for each metric.

    Parameters
    ----------
    ascending_cols : metrics where lower is better (e.g., 'tov', 'pf')
    """
    if metrics is None:
        metrics = [c for c in df.select_dtypes(include="number").columns if c != "player_id"]
    ascending_cols = ascending_cols or []

    result = df[[player_col]].copy()
    for col in metrics:
        if col not in df.columns:
            continue
        if col in ascending_cols:
            result[col + "_pctile"] = df[col].rank(ascending=True, pct=True).mul(100).round(1)
        else:
            result[col + "_pctile"] = df[col].rank(ascending=True, pct=True).mul(100).round(1)
    return result


def radar_chart(
    player_stats: dict | pd.DataFrame,
    categories: list[str] | None = None,
    title: str = "",
    max_values: dict | None = None,
) -> matplotlib.figure.Figure:
    """Create a radar/spider chart comparing players across metrics.

    Parameters
    ----------
    player_stats : dict of {player_name: {metric: value}} or DataFrame
        If DataFrame, rows are players, columns are metrics.
    categories : metric names to display (auto-detected if None)
    max_values : outer ring values per category (defaults to data max)
    """
    import matplotlib.pyplot as plt

    # Normalize input to dict
    if isinstance(player_stats, pd.DataFrame):
        stats_dict = {idx: row.to_dict() for idx, row in player_stats.iterrows()}
    else:
        stats_dict = player_stats

    if not stats_dict:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        plt.show()
        return fig

    if categories is None:
        first_player = next(iter(stats_dict.values()))
        categories = list(first_player.keys())

    n = len(categories)
    if n < 3:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "Need at least 3 categories", ha="center", va="center")
        plt.show()
        return fig

    angles = [i / n * 2 * math.pi for i in range(n)]
    angles += angles[:1]  # close the polygon

    # Compute max values for normalization
    if max_values is None:
        max_values = {}
        for cat in categories:
            vals = [stats_dict[p].get(cat, 0) for p in stats_dict]
            max_values[cat] = max(vals) if vals and max(vals) > 0 else 1

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={"projection": "polar"})
    fig.patch.set_facecolor("#141a2e")
    ax.set_facecolor("#141a2e")

    # Try to use team colors
    try:
        from team_colors import get_team_color  # noqa: F401

        _has_colors = True
    except ImportError:
        _has_colors = False

    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]

    for idx, (player, stats) in enumerate(stats_dict.items()):
        values = [stats.get(cat, 0) / max_values.get(cat, 1) for cat in categories]
        values += values[:1]
        color = colors[idx % len(colors)]
        ax.plot(angles, values, "o-", linewidth=2, label=player, color=color)
        ax.fill(angles, values, alpha=0.15, color=color)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, color="white", size=10)
    ax.set_yticklabels([])
    ax.tick_params(colors="white")
    ax.spines["polar"].set_color("#444")
    ax.set_title(title or "Player Comparison", color="white", size=14, pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), framealpha=0.3)

    plt.show()
    return fig


def per36(
    df: pd.DataFrame,
    min_col: str = "avg_min",
    stat_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Per-36-minute normalization.

    Adds {stat}_per36 columns for each stat.
    """
    result = df.copy()
    if stat_cols is None:
        stat_cols = [
            c
            for c in df.select_dtypes(include="number").columns
            if c not in (min_col, "player_id", "team_id", "gp")
        ]

    for col in stat_cols:
        if col in result.columns and min_col in result.columns:
            result[col + "_per36"] = np.where(
                result[min_col] > 0,
                (result[col] * 36 / result[min_col]).round(2),
                0.0,
            )
    return result


def per100(
    df: pd.DataFrame,
    pace_col: str = "pace",
    stat_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Per-100-possession normalization.

    Adds {stat}_per100 columns. Requires a pace column.
    """
    result = df.copy()
    if stat_cols is None:
        stat_cols = [
            c
            for c in df.select_dtypes(include="number").columns
            if c not in (pace_col, "player_id", "team_id", "gp")
        ]

    for col in stat_cols:
        if col in result.columns and pace_col in result.columns:
            result[col + "_per100"] = np.where(
                result[pace_col] > 0,
                (result[col] * 100 / result[pace_col]).round(2),
                0.0,
            )
    return result
