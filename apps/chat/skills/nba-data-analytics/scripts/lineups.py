"""Lineup and on/off analysis helpers for NBA analytics.

Provides on/off impact computation, two-man combination analysis,
and lineup visualization.
"""

from __future__ import annotations

import pandas as pd


def on_off_impact(
    df: pd.DataFrame,
    entity_col: str = "entity_id",
    on_off_col: str = "on_off",
    rating_cols: list[str] | None = None,
    name_col: str | None = None,
) -> pd.DataFrame:
    """Compute the delta between on-court and off-court ratings.

    Parameters
    ----------
    df : DataFrame from agg_on_off_splits (has 'On' and 'Off' rows per player)
    entity_col : player identifier column
    on_off_col : column containing 'On' / 'Off' values
    rating_cols : columns to compute deltas for (auto-detects numeric if None)
    name_col : optional player name column to include in output
    """
    if rating_cols is None:
        rating_cols = [
            c for c in df.select_dtypes(include="number").columns if c not in (entity_col,)
        ]

    on = df[df[on_off_col].str.strip().str.lower() == "on"].set_index(entity_col)
    off = df[df[on_off_col].str.strip().str.lower() == "off"].set_index(entity_col)

    common = on.index.intersection(off.index)
    if common.empty:
        return pd.DataFrame()

    result = pd.DataFrame(index=common)
    for col in rating_cols:
        if col in on.columns and col in off.columns:
            result[col + "_on"] = on.loc[common, col].values
            result[col + "_off"] = off.loc[common, col].values
            result[col + "_delta"] = on.loc[common, col].values - off.loc[common, col].values

    if name_col and name_col in on.columns:
        result[name_col] = on.loc[common, name_col].values

    result = result.reset_index()
    return result


def two_man_combos(
    df: pd.DataFrame,
    player_cols: list[str] | None = None,
    net_rating_col: str = "avg_net_rating",
    min_col: str = "min",
) -> pd.DataFrame:
    """Aggregate two-player combination stats from lineup data.

    Parameters
    ----------
    df : DataFrame with lineup/player columns and efficiency metrics
    player_cols : columns identifying players in each lineup
        If None, looks for columns matching 'player*' pattern
    net_rating_col : net rating column
    min_col : minutes column for weighting
    """
    if player_cols is None:
        player_cols = [c for c in df.columns if c.lower().startswith("player")]
        if not player_cols:
            return pd.DataFrame({"error": ["No player columns found"]})

    from itertools import combinations

    combos: dict[tuple, list] = {}
    for _, row in df.iterrows():
        players = sorted([str(row[c]) for c in player_cols if pd.notna(row.get(c))])
        rating = float(row.get(net_rating_col, 0) or 0)
        minutes = float(row.get(min_col, 0) or 0)
        for pair in combinations(players, 2):
            if pair not in combos:
                combos[pair] = []
            combos[pair].append({"rating": rating, "minutes": minutes})

    rows = []
    for (p1, p2), games in combos.items():
        total_min = sum(g["minutes"] for g in games)
        if total_min > 0:
            weighted_rating = sum(g["rating"] * g["minutes"] for g in games) / total_min
        else:
            weighted_rating = sum(g["rating"] for g in games) / len(games) if games else 0
        rows.append(
            {
                "player_1": p1,
                "player_2": p2,
                "weighted_net_rating": round(weighted_rating, 2),
                "total_minutes": round(total_min, 1),
                "lineup_count": len(games),
            }
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("weighted_net_rating", ascending=False)
    return result


def lineup_chart(
    df: pd.DataFrame,
    lineup_col: str = "group_id",
    metric_col: str = "avg_net_rating",
    n: int = 10,
    title: str = "",
) -> object:
    """Horizontal bar chart of top and bottom lineups by a metric.

    Shows top N and bottom N lineups.
    """
    import plotly.graph_objects as go

    sorted_df = df.sort_values(metric_col, ascending=False)
    top = sorted_df.head(n)
    bottom = sorted_df.tail(n)
    combined = pd.concat([top, bottom]).drop_duplicates()
    combined = combined.sort_values(metric_col, ascending=True)

    labels = combined[lineup_col].astype(str).tolist()
    values = combined[metric_col].tolist()
    colors = ["#2ca02c" if v >= 0 else "#d62728" for v in values]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker_color=colors,
        )
    )
    fig.update_layout(
        title=title or f"Top/Bottom {n} Lineups by {metric_col}",
        xaxis_title=metric_col,
        yaxis_title="Lineup",
        template="plotly_dark",
        height=max(400, len(combined) * 30),
    )
    return fig
