from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.schemas.star.dim_player import DimPlayerSchema
from nbadb.transform.dimensions.dim_player import DimPlayerTransformer


def _run_transform(t: DimPlayerTransformer, staging: dict) -> pl.DataFrame:
    """Inject a shared DuckDB connection and run the transformer."""
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        t._conn = conn
        return t.transform(staging)
    finally:
        conn.close()


def _make_player_info(**overrides: list) -> pl.DataFrame:
    """Build current CommonPlayerInfo observations, including an exact replay."""
    defaults = {
        "player_id": [1, 1, 2],
        "full_name": ["Player A", "Player A", "Player B"],
        "first_name": ["Player", "Player", "Player"],
        "last_name": ["A", "A", "B"],
        "roster_status": ["Active", "Active", "Inactive"],
        "team_id": [10, 10, 30],
        "position": ["G", "G", "F"],
        "jersey_number": ["1", "1", "5"],
        "height": ["6-3", "6-3", "6-8"],
        "weight": [190, 190, 240],
        "birth_date": ["1990-01-01", "1990-01-01", "1992-05-15"],
        "country": ["USA", "USA", "Greece"],
        "draft_year": [2012, 2012, 2013],
        "draft_round": [1, 1, 1],
        "draft_number": [4, 4, 15],
        "college_id": [None, None, None],
        "from_year": ["2012", "2012", "2013"],
        "to_year": ["2025", "2025", "2020"],
    }
    defaults.update(overrides)
    return pl.DataFrame(defaults)


class TestDimPlayerTransformer:
    def test_class_attributes(self) -> None:
        assert DimPlayerTransformer.output_table == "dim_player"
        assert DimPlayerTransformer.depends_on == ["stg_player_info"]

    def test_current_snapshot_has_one_row_per_player(self) -> None:
        result = _run_transform(
            DimPlayerTransformer(), {"stg_player_info": _make_player_info().lazy()}
        )

        assert result.shape[0] == 2
        assert result["player_id"].to_list() == [1, 2]
        assert result["is_current"].to_list() == [True, True]
        assert result["valid_to"].null_count() == 2

    def test_exact_replay_is_idempotent(self) -> None:
        result = _run_transform(
            DimPlayerTransformer(), {"stg_player_info": _make_player_info().lazy()}
        )

        player = result.filter(pl.col("player_id") == 1)
        assert player.shape[0] == 1
        assert player["team_id"].item() == 10

    def test_conflicting_current_observations_fail_closed(self) -> None:
        stg = _make_player_info(team_id=[10, 20, 30])

        with pytest.raises(
            duckdb.InvalidInputException,
            match="conflicting current player identity observations",
        ):
            _run_transform(DimPlayerTransformer(), {"stg_player_info": stg.lazy()})

    def test_surrogate_keys_are_sequential(self) -> None:
        result = _run_transform(
            DimPlayerTransformer(), {"stg_player_info": _make_player_info().lazy()}
        )

        assert result["player_sk"].to_list() == [1, 2]

    def test_current_identity_fields_and_types_are_preserved(self) -> None:
        result = _run_transform(
            DimPlayerTransformer(), {"stg_player_info": _make_player_info().lazy()}
        )
        player = result.filter(pl.col("player_id") == 1)

        assert player["full_name"].item() == "Player A"
        assert player["team_id"].item() == 10
        assert player["is_active"].item() is True
        assert player["from_year"].dtype in (pl.Int32, pl.Int64)
        assert player["to_year"].dtype in (pl.Int32, pl.Int64)
        assert player["valid_from"].item() == "2012"

    def test_null_career_start_gets_explicit_unknown_compatibility_value(self) -> None:
        stg = _make_player_info(
            player_id=[99],
            full_name=["Unknown Start"],
            first_name=["Unknown"],
            last_name=["Start"],
            roster_status=[None],
            team_id=[None],
            position=[None],
            jersey_number=[None],
            height=[None],
            weight=[None],
            birth_date=[None],
            country=[None],
            draft_year=[None],
            draft_round=[None],
            draft_number=[None],
            college_id=[None],
            from_year=[None],
            to_year=[None],
        )

        result = _run_transform(DimPlayerTransformer(), {"stg_player_info": stg.lazy()})

        assert result["valid_from"].item() == "unknown"
        assert result["valid_to"].item() is None
        assert result["is_current"].item() is True

    def test_provider_unattached_team_sentinel_becomes_nullable_identity(self) -> None:
        staging = _make_player_info(
            player_id=[99],
            full_name=["Free Agent"],
            first_name=["Free"],
            last_name=["Agent"],
            roster_status=["Inactive"],
            team_id=[0],
            position=[None],
            jersey_number=[None],
            height=[None],
            weight=[None],
            birth_date=[None],
            country=[None],
            draft_year=[None],
            draft_round=[None],
            draft_number=[None],
            college_id=[None],
            from_year=["2020"],
            to_year=["2025"],
        )

        result = _run_transform(DimPlayerTransformer(), {"stg_player_info": staging.lazy()})

        assert result["team_id"].item() is None
        DimPlayerSchema.validate(result)
