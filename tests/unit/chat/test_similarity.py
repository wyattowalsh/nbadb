"""Tests for player similarity engine."""

from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Load similarity module dynamically since it's a skill script, not a package.
_PATH = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "chat"
    / "skills"
    / "nba-data-analytics"
    / "scripts"
    / "similarity.py"
)
_spec = importlib.util.spec_from_file_location("similarity", _PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

normalize_stats = _mod.normalize_stats
find_similar = _mod.find_similar
cluster_players = _mod.cluster_players
career_similarity = _mod.career_similarity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

METRICS = ["pts", "reb", "ast", "stl", "blk"]


@pytest.fixture()
def player_df() -> pd.DataFrame:
    """Synthetic single-season DataFrame with 30 players."""
    rng = np.random.default_rng(42)
    n = 30
    return pd.DataFrame(
        {
            "full_name": [f"Player_{i}" for i in range(n)],
            "player_id": range(n),
            "team_id": rng.integers(1, 6, size=n),
            "pts": rng.uniform(5, 30, size=n),
            "reb": rng.uniform(1, 12, size=n),
            "ast": rng.uniform(0.5, 10, size=n),
            "stl": rng.uniform(0.3, 2.5, size=n),
            "blk": rng.uniform(0.1, 3.0, size=n),
        }
    )


@pytest.fixture()
def career_df() -> pd.DataFrame:
    """Multi-season DataFrame: 20 players x 5 ages (22-26)."""
    rng = np.random.default_rng(99)
    rows = []
    for i in range(20):
        for age in range(22, 27):
            rows.append(
                {
                    "full_name": f"Player_{i}",
                    "age": age,
                    "pts": rng.uniform(8, 28) + (age - 22) * 1.5,
                    "reb": rng.uniform(2, 10),
                    "ast": rng.uniform(1, 8),
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# TestNormalizeStats
# ---------------------------------------------------------------------------


class TestNormalizeStats:
    def test_zero_mean_unit_var(self, player_df: pd.DataFrame) -> None:
        normed = normalize_stats(player_df, METRICS)
        for col in METRICS:
            assert normed[col].mean() == pytest.approx(0.0, abs=1e-10)
            assert normed[col].std() == pytest.approx(1.0, abs=1e-10)

    def test_constant_column(self) -> None:
        df = pd.DataFrame(
            {
                "full_name": [f"P{i}" for i in range(20)],
                "pts": [10.0] * 20,
                "reb": np.linspace(1, 10, 20),
            }
        )
        normed = normalize_stats(df, ["pts", "reb"])
        assert (normed["pts"] == 0.0).all()

    def test_preserves_non_metric_cols(self, player_df: pd.DataFrame) -> None:
        normed = normalize_stats(player_df, METRICS)
        pd.testing.assert_series_equal(normed["full_name"], player_df["full_name"])


# ---------------------------------------------------------------------------
# TestFindSimilar
# ---------------------------------------------------------------------------


class TestFindSimilar:
    def test_identical_player(self, player_df: pd.DataFrame) -> None:
        # Duplicate a player with a new name — should be similarity ~1.0
        clone = player_df[player_df["full_name"] == "Player_0"].copy()
        clone["full_name"] = "Player_0_clone"
        df = pd.concat([player_df, clone], ignore_index=True)
        result = find_similar(df, "Player_0", metrics=METRICS, n=5)
        top_match = result.iloc[0]
        assert top_match["full_name"] == "Player_0_clone"
        assert top_match["similarity"] == pytest.approx(1.0, abs=1e-6)

    def test_opposite_player(self) -> None:
        # Two players with inversely correlated stats
        df = pd.DataFrame(
            {
                "full_name": ["Target", "Opposite", "Neutral"],
                "pts": [30.0, 5.0, 17.0],
                "reb": [12.0, 1.0, 6.0],
                "ast": [10.0, 0.5, 5.0],
            }
        )
        result = find_similar(df, "Target", metrics=["pts", "reb", "ast"], n=5)
        # Neutral should be more similar than Opposite
        sims = dict(zip(result["full_name"], result["similarity"], strict=False))
        assert sims["Neutral"] > sims["Opposite"]

    def test_player_not_found(self, player_df: pd.DataFrame) -> None:
        result = find_similar(player_df, "Nobody", metrics=METRICS)
        assert "error" in result.columns
        assert "not found" in result["error"].iloc[0]

    def test_returns_n_results(self, player_df: pd.DataFrame) -> None:
        result = find_similar(player_df, "Player_0", metrics=METRICS, n=5)
        assert len(result) <= 5

    def test_euclidean_method(self, player_df: pd.DataFrame) -> None:
        result = find_similar(player_df, "Player_0", metrics=METRICS, n=5, method="euclidean")
        assert len(result) > 0
        assert "similarity" in result.columns
        # All Euclidean similarities should be in (0, 1]
        assert (result["similarity"] > 0).all()
        assert (result["similarity"] <= 1.0).all()


# ---------------------------------------------------------------------------
# TestClusterPlayers
# ---------------------------------------------------------------------------


class TestClusterPlayers:
    def test_correct_cluster_count(self, player_df: pd.DataFrame) -> None:
        result = cluster_players(player_df, metrics=METRICS, n_clusters=3)
        assert result["cluster"].nunique() <= 3

    def test_cluster_column_added(self, player_df: pd.DataFrame) -> None:
        result = cluster_players(player_df, metrics=METRICS, n_clusters=4)
        assert "cluster" in result.columns
        assert len(result) == len(player_df)

    def test_cluster_count_capped_by_player_count(self) -> None:
        df = pd.DataFrame(
            {
                "full_name": ["Player_A", "Player_B", "Player_C"],
                "pts": [10.0, 20.0, 30.0],
                "reb": [4.0, 6.0, 8.0],
                "ast": [2.0, 3.0, 4.0],
            }
        )
        result = cluster_players(df, metrics=["pts", "reb", "ast"], n_clusters=10)
        assert len(result) == len(df)
        assert result["cluster"].nunique() == len(df)

    def test_import_error_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        df = pd.DataFrame(
            {
                "full_name": ["Player_A", "Player_B", "Player_C", "Player_D"],
                "pts": [10.0, 12.0, 25.0, 27.0],
                "reb": [5.0, 5.5, 8.0, 8.5],
            }
        )
        original_import = builtins.__import__

        def _import_with_missing_scipy(
            name,
            globalns=None,
            localns=None,
            fromlist=(),
            level=0,
        ):
            if name == "scipy.cluster.vq":
                raise ImportError("scipy unavailable for test")
            return original_import(name, globalns, localns, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", _import_with_missing_scipy)

        result = cluster_players(df, metrics=["pts", "reb"], n_clusters=2)
        clusters = result.set_index("full_name")["cluster"]

        assert "cluster" in result.columns
        assert len(result) == len(df)
        assert clusters["Player_A"] == clusters["Player_B"]
        assert clusters["Player_C"] == clusters["Player_D"]
        assert clusters["Player_A"] != clusters["Player_C"]


# ---------------------------------------------------------------------------
# TestCareerSimilarity
# ---------------------------------------------------------------------------


class TestCareerSimilarity:
    def test_identical_career(self, career_df: pd.DataFrame) -> None:
        # Clone Player_0 with a new name
        clone = career_df[career_df["full_name"] == "Player_0"].copy()
        clone["full_name"] = "Player_0_clone"
        df = pd.concat([career_df, clone], ignore_index=True)
        result = career_similarity(df, "Player_0", metrics=["pts", "reb", "ast"], n=5)
        top = result.iloc[0]
        assert top["full_name"] == "Player_0_clone"
        assert top["similarity"] == pytest.approx(1.0, abs=1e-6)
        assert top["seasons_compared"] == 5

    def test_player_not_found(self, career_df: pd.DataFrame) -> None:
        result = career_similarity(career_df, "Ghost")
        assert "error" in result.columns
        assert "not found" in result["error"].iloc[0]

    def test_no_overlapping_ages(self) -> None:
        # Target has ages 22-24, others have 30-32 — no overlap
        rows = []
        for age in [22, 23, 24]:
            rows.append({"full_name": "Target", "age": age, "pts": 20.0, "reb": 5.0})
        for i in range(5):
            for age in [30, 31, 32]:
                rows.append({"full_name": f"Other_{i}", "age": age, "pts": 15.0, "reb": 6.0})
        df = pd.DataFrame(rows)
        result = career_similarity(df, "Target", metrics=["pts", "reb"], n=5)
        assert len(result) == 0
