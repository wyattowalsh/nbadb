from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.derived.agg_on_off_splits import AggOnOffSplitsTransformer


def _run(staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        t = AggOnOffSplitsTransformer()
        t._conn = conn
        return t.transform(staging)
    finally:
        conn.close()


def _stg_on_off(
    season_type: str = "Regular Season",
    player_id: int = 201566,
    team_id: int = 1610612738,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "player_id": [player_id],
            "team_id": [team_id],
            "season_year": ["2024-25"],
            "season_type": [season_type],
            "on_off": ["On"],
            "gp": [65],
            "min": [35.0],
            "pts": [25.0],
            "reb": [6.0],
            "ast": [7.0],
            "off_rating": [115.0],
            "def_rating": [107.0],
            "net_rating": [8.0],
        }
    ).lazy()


def _stg_team_dashboard_on_off(
    season_type: str = "Regular Season",
    team_id: int = 1610612738,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "team_id": [team_id],
            "season_year": ["2024-25"],
            "season_type": [season_type],
            "on_off": ["overall"],
            "gp": [82],
            "min": [48.0],
            "pts": [118.0],
            "reb": [44.0],
            "ast": [27.0],
            "off_rating": [121.0],
            "def_rating": [110.0],
            "net_rating": [11.0],
        }
    ).lazy()


def _stg_player_on_details(
    season_type: str = "Regular Season",
    player_id: int = 201566,
    team_id: int = 1610612738,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "player_id": [player_id],
            "team_id": [team_id],
            "season_year": ["2024-25"],
            "season_type": [season_type],
            "on_off": ["Off"],
            "gp": [60],
            "min": [16.0],
            "pts": [18.0],
            "reb": [5.0],
            "ast": [5.0],
            "off_rating": [108.0],
            "def_rating": [111.0],
            "net_rating": [-3.0],
        }
    ).lazy()


def _staging(**overrides: pl.LazyFrame) -> dict[str, pl.LazyFrame]:
    defaults: dict[str, pl.LazyFrame] = {
        "stg_on_off": _stg_on_off(),
        "stg_team_dashboard_on_off": _stg_team_dashboard_on_off(),
        "stg_player_on_details": _stg_player_on_details(),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_output_table(self) -> None:
        assert AggOnOffSplitsTransformer.output_table == "agg_on_off_splits"

    def test_depends_on(self) -> None:
        assert set(AggOnOffSplitsTransformer.depends_on) == {
            "stg_team_dashboard_on_off",
            "stg_on_off",
            "stg_player_on_details",
        }


# ---------------------------------------------------------------------------
# Entity type routing
# ---------------------------------------------------------------------------


class TestEntityTypes:
    def test_three_entity_types_produced(self) -> None:
        result = _run(_staging())
        assert set(result["entity_type"].to_list()) == {"player", "team", "player_detail"}

    def test_player_entity_from_stg_on_off(self) -> None:
        result = _run(_staging())
        player_rows = result.filter(pl.col("entity_type") == "player")
        assert player_rows.shape[0] == 1
        assert player_rows["entity_id"][0] == 201566

    def test_team_entity_from_stg_team_dashboard(self) -> None:
        result = _run(_staging())
        team_rows = result.filter(pl.col("entity_type") == "team")
        assert team_rows.shape[0] == 1
        assert team_rows["entity_id"][0] == 1610612738

    def test_player_detail_entity_from_stg_player_on_details(self) -> None:
        result = _run(_staging())
        detail_rows = result.filter(pl.col("entity_type") == "player_detail")
        assert detail_rows.shape[0] == 1
        assert detail_rows["entity_id"][0] == 201566


# ---------------------------------------------------------------------------
# season_type propagation (regression)
# ---------------------------------------------------------------------------


class TestSeasonTypePropagation:
    """Ensure season_type is present and correct in every output row."""

    def test_season_type_column_present(self) -> None:
        result = _run(_staging())
        assert "season_type" in result.columns

    def test_season_type_values_match_inputs(self) -> None:
        result = _run(_staging())
        assert set(result["season_type"].to_list()) == {"Regular Season"}

    def test_multiple_season_types_preserved(self) -> None:
        """Both Regular Season and Playoffs rows should survive the UNION."""
        rs = _stg_on_off(season_type="Regular Season")
        po = _stg_on_off(season_type="Playoffs")
        combined = pl.concat([rs.collect(), po.collect()]).lazy()

        staging = _staging(stg_on_off=combined)
        result = _run(staging)

        player_rows = result.filter(pl.col("entity_type") == "player")
        assert set(player_rows["season_type"].to_list()) == {"Regular Season", "Playoffs"}

    def test_season_type_per_entity_type(self) -> None:
        """Each staging source carries its own season_type through."""
        staging = _staging(
            stg_on_off=_stg_on_off(season_type="Playoffs"),
            stg_team_dashboard_on_off=_stg_team_dashboard_on_off(season_type="Playoffs"),
            stg_player_on_details=_stg_player_on_details(season_type="Regular Season"),
        )
        result = _run(staging)

        player_row = result.filter(pl.col("entity_type") == "player")
        team_row = result.filter(pl.col("entity_type") == "team")
        detail_row = result.filter(pl.col("entity_type") == "player_detail")

        assert player_row["season_type"][0] == "Playoffs"
        assert team_row["season_type"][0] == "Playoffs"
        assert detail_row["season_type"][0] == "Regular Season"


# ---------------------------------------------------------------------------
# Column forwarding
# ---------------------------------------------------------------------------


class TestColumnForwarding:
    def test_rating_columns_forwarded(self) -> None:
        result = _run(_staging())
        player_row = result.filter(pl.col("entity_type") == "player")
        assert player_row["off_rating"][0] == pytest.approx(115.0)
        assert player_row["def_rating"][0] == pytest.approx(107.0)
        assert player_row["net_rating"][0] == pytest.approx(8.0)

    def test_stat_columns_forwarded(self) -> None:
        result = _run(_staging())
        player_row = result.filter(pl.col("entity_type") == "player")
        assert player_row["pts"][0] == pytest.approx(25.0)
        assert player_row["reb"][0] == pytest.approx(6.0)
        assert player_row["ast"][0] == pytest.approx(7.0)
