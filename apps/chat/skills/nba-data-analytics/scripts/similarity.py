"""Player similarity engine for NBA analytics.

Find statistically similar players using cosine distance, Euclidean distance,
or k-means clustering on normalized stat vectors.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def normalize_stats(
    df: pd.DataFrame,
    metrics: list[str],
) -> pd.DataFrame:
    """Z-score normalization across specified metric columns.

    Returns a copy with normalized values. Original columns are replaced.
    """
    result = df.copy()
    for col in metrics:
        if col in result.columns:
            mean = result[col].mean()
            std = result[col].std()
            if std > 0:
                result[col] = (result[col] - mean) / std
            else:
                result[col] = 0.0
    return result


def find_similar(
    df: pd.DataFrame,
    target_name: str,
    player_col: str = "full_name",
    metrics: list[str] | None = None,
    n: int = 10,
    method: str = "cosine",
) -> pd.DataFrame:
    """Find the N most similar players by statistical profile.

    Parameters
    ----------
    df : DataFrame with one row per player
    target_name : name of the target player to match against
    player_col : column with player names
    metrics : columns to use for comparison (auto-detects numeric if None)
    n : number of similar players to return
    method : 'cosine' or 'euclidean'
    """
    if metrics is None:
        metrics = [
            c
            for c in df.select_dtypes(include="number").columns
            if c not in ("player_id", "team_id")
        ]

    # Filter to valid rows
    valid = df.dropna(subset=metrics).copy()
    if target_name not in valid[player_col].values:
        return pd.DataFrame({"error": [f"Player '{target_name}' not found"]})

    # Z-score normalize
    normed = normalize_stats(valid, metrics)

    target_idx = normed[normed[player_col] == target_name].index[0]
    target_vec = normed.loc[target_idx, metrics].values.astype(float)

    scores = []
    for idx, row in normed.iterrows():
        if idx == target_idx:
            continue
        vec = row[metrics].values.astype(float)
        if method == "cosine":
            dot = np.dot(target_vec, vec)
            norm_t = np.linalg.norm(target_vec)
            norm_v = np.linalg.norm(vec)
            sim = dot / (norm_t * norm_v) if norm_t > 0 and norm_v > 0 else 0.0
        else:  # euclidean
            dist = np.linalg.norm(target_vec - vec)
            sim = 1.0 / (1.0 + dist)  # convert distance to similarity
        scores.append((valid.loc[idx, player_col], float(sim)))

    scores.sort(key=lambda x: x[1], reverse=True)
    top = scores[:n]

    result = pd.DataFrame(top, columns=[player_col, "similarity"])
    # Merge back original stats
    result = result.merge(df[[player_col] + metrics], on=player_col, how="left")
    return result


def cluster_players(
    df: pd.DataFrame,
    player_col: str = "full_name",
    metrics: list[str] | None = None,
    n_clusters: int = 5,
) -> pd.DataFrame:
    """K-means clustering of players by statistical profile.

    Uses scipy.cluster.vq for clustering. Falls back to simple
    quantile-based grouping if scipy is unavailable.
    """
    if metrics is None:
        metrics = [
            c
            for c in df.select_dtypes(include="number").columns
            if c not in ("player_id", "team_id")
        ]

    valid = df.dropna(subset=metrics).copy()
    normed = normalize_stats(valid, metrics)
    data = normed[metrics].values.astype(float)

    try:
        from scipy.cluster.vq import kmeans2, whiten

        whitened = whiten(data)
        # Handle edge case where all values are zero (whiten returns nan)
        if np.any(np.isnan(whitened)):
            whitened = data
        centroids, labels = kmeans2(whitened, n_clusters, minit="points")
        valid = valid.copy()
        valid["cluster"] = labels
    except ImportError:
        # Fallback: simple quantile-based grouping on first metric
        valid = valid.copy()
        valid["cluster"] = pd.qcut(
            valid[metrics[0]], q=min(n_clusters, len(valid)), labels=False, duplicates="drop"
        )

    return valid


def career_similarity(
    df_seasons: pd.DataFrame,
    target_name: str,
    player_col: str = "full_name",
    age_col: str = "age",
    metrics: list[str] | None = None,
    n: int = 10,
) -> pd.DataFrame:
    """Career trajectory similarity — compare stat arcs aligned by age.

    Parameters
    ----------
    df_seasons : multi-season DataFrame (multiple rows per player)
    target_name : player to compare against
    age_col : column for alignment (age or season number)
    """
    if metrics is None:
        metrics = [
            c
            for c in df_seasons.select_dtypes(include="number").columns
            if c not in ("player_id", "team_id", age_col)
        ]

    target = df_seasons[df_seasons[player_col] == target_name]
    if target.empty:
        return pd.DataFrame({"error": [f"Player '{target_name}' not found"]})

    target_ages = set(target[age_col].values)
    scores = []

    for name, group in df_seasons.groupby(player_col):
        if name == target_name:
            continue
        # Find overlapping ages
        common_ages = sorted(target_ages & set(group[age_col].values))
        if len(common_ages) < 2:
            continue

        t_data = target[target[age_col].isin(common_ages)].sort_values(age_col)
        p_data = group[group[age_col].isin(common_ages)].sort_values(age_col)

        # Compute mean absolute difference across all metrics and ages
        diffs = []
        for metric in metrics:
            if metric in t_data.columns and metric in p_data.columns:
                t_vals = t_data[metric].values.astype(float)
                p_vals = p_data[metric].values.astype(float)
                if len(t_vals) == len(p_vals):
                    diff = np.mean(np.abs(t_vals - p_vals))
                    diffs.append(diff)

        if diffs:
            avg_diff = np.mean(diffs)
            sim = 1.0 / (1.0 + avg_diff)
            scores.append((name, float(sim), len(common_ages)))

    scores.sort(key=lambda x: x[1], reverse=True)
    top = scores[:n]

    return pd.DataFrame(top, columns=[player_col, "similarity", "seasons_compared"])
