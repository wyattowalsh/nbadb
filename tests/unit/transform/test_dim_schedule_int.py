"""Tests for DimScheduleIntTransformer."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest


@pytest.fixture()
def conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


def _make_stg_schedule_int(**overrides: object) -> pl.DataFrame:
    """Return a minimal stg_schedule_int DataFrame."""
    defaults: dict[str, list[object]] = {
        "game_id": ["0012400001"],
        "game_code": ["20250115/BOSCHI"],
        "league_id": ["00"],
        "season_year": ["2024-25"],
        "game_date": ["2025-01-15"],
        "game_date_est": ["2025-01-15T00:00:00"],
        "game_date_time_est": ["2025-01-15T19:30:00"],
        "game_date_utc": ["2025-01-16"],
        "game_time_utc": ["00:30:00"],
        "game_date_time_utc": ["2025-01-16T00:30:00"],
        "game_status": [3],
        "game_status_text": ["Final"],
        "game_sequence": [1],
        "week_number": [1],
        "week_name": ["Week 1"],
        "day": ["Wednesday"],
        "arena_name": ["United Center"],
        "arena_city": ["Chicago"],
        "arena_state": ["IL"],
        "home_team_team_id": [1610612741],
        "home_team_team_name": ["Bulls"],
        "home_team_team_city": ["Chicago"],
        "home_team_team_tricode": ["CHI"],
        "home_team_wins": [10],
        "home_team_losses": [5],
        "home_team_score": [110],
        "away_team_team_id": [1610612738],
        "away_team_team_name": ["Celtics"],
        "away_team_team_city": ["Boston"],
        "away_team_team_tricode": ["BOS"],
        "away_team_wins": [12],
        "away_team_losses": [3],
        "away_team_score": [105],
        "if_necessary": [False],
        "series_text": [None],
        "game_subtype": [None],
        "is_neutral": [False],
        "postponed_status": [""],
    }
    defaults.update(overrides)
    return pl.DataFrame(defaults)


def _make_stg_schedule_int_weeks(**overrides: object) -> pl.DataFrame:
    """Return a minimal stg_schedule_int_weeks DataFrame."""
    defaults: dict[str, list[object]] = {
        "league_id": ["00"],
        "season_year": ["2024-25"],
        "week_number": [1],
        "week_name": ["Week 1"],
        "start_date": ["2025-01-13"],
        "end_date": ["2025-01-19"],
    }
    defaults.update(overrides)
    return pl.DataFrame(defaults)


def _register_staging(
    conn: duckdb.DuckDBPyConnection,
    schedule_int: pl.DataFrame,
    schedule_int_weeks: pl.DataFrame,
) -> dict[str, pl.LazyFrame]:
    """Register staging tables in DuckDB and return a staging dict."""
    conn.register("stg_schedule_int", schedule_int)
    conn.register("stg_schedule_int_weeks", schedule_int_weeks)
    return {
        "stg_schedule_int": schedule_int.lazy(),
        "stg_schedule_int_weeks": schedule_int_weeks.lazy(),
    }


class TestDimScheduleIntMetadata:
    def test_output_table(self) -> None:
        from nbadb.transform.dimensions.dim_schedule_int import DimScheduleIntTransformer

        assert DimScheduleIntTransformer.output_table == "dim_schedule_int"

    def test_depends_on(self) -> None:
        from nbadb.transform.dimensions.dim_schedule_int import DimScheduleIntTransformer

        assert "stg_schedule_int" in DimScheduleIntTransformer.depends_on
        assert "stg_schedule_int_weeks" in DimScheduleIntTransformer.depends_on

    def test_is_sql_transformer(self) -> None:
        from nbadb.transform.base import SqlTransformer
        from nbadb.transform.dimensions.dim_schedule_int import DimScheduleIntTransformer

        assert issubclass(DimScheduleIntTransformer, SqlTransformer)


class TestDimScheduleIntTransform:
    def test_basic_transform(self, conn: duckdb.DuckDBPyConnection) -> None:
        from nbadb.transform.dimensions.dim_schedule_int import DimScheduleIntTransformer

        staging = _register_staging(conn, _make_stg_schedule_int(), _make_stg_schedule_int_weeks())
        t = DimScheduleIntTransformer()
        t._conn = conn
        result = t.transform(staging)

        assert result.shape[0] == 1
        assert "game_id" in result.columns
        assert "home_team_id" in result.columns
        assert "away_team_id" in result.columns
        assert "arena_name" in result.columns
        assert "week_start_date" in result.columns
        assert "week_end_date" in result.columns

    def test_deduplicates_by_game_id(self, conn: duckdb.DuckDBPyConnection) -> None:
        from nbadb.transform.dimensions.dim_schedule_int import DimScheduleIntTransformer

        schedule_int = _make_stg_schedule_int(
            game_id=["0012400001", "0012400001"],
            game_code=["20250115/BOSCHI", "20250115/BOSCHI"],
            game_status=[1, 3],
            game_status_text=["Scheduled", "Final"],
            home_team_score=[0, 110],
            away_team_score=[0, 105],
            # Duplicate all other columns
            league_id=["00", "00"],
            season_year=["2024-25", "2024-25"],
            game_date=["2025-01-15", "2025-01-15"],
            game_date_est=["2025-01-15T00:00:00", "2025-01-15T00:00:00"],
            game_date_time_est=["2025-01-15T19:30:00", "2025-01-15T19:30:00"],
            game_date_utc=["2025-01-16", "2025-01-16"],
            game_time_utc=["00:30:00", "00:30:00"],
            game_date_time_utc=["2025-01-16T00:30:00", "2025-01-16T00:30:00"],
            game_sequence=[1, 1],
            week_number=[1, 1],
            week_name=["Week 1", "Week 1"],
            day=["Wednesday", "Wednesday"],
            arena_name=["United Center", "United Center"],
            arena_city=["Chicago", "Chicago"],
            arena_state=["IL", "IL"],
            home_team_team_id=[1610612741, 1610612741],
            home_team_team_name=["Bulls", "Bulls"],
            home_team_team_city=["Chicago", "Chicago"],
            home_team_team_tricode=["CHI", "CHI"],
            home_team_wins=[10, 10],
            home_team_losses=[5, 5],
            away_team_team_id=[1610612738, 1610612738],
            away_team_team_name=["Celtics", "Celtics"],
            away_team_team_city=["Boston", "Boston"],
            away_team_team_tricode=["BOS", "BOS"],
            away_team_wins=[12, 12],
            away_team_losses=[3, 3],
            if_necessary=[False, False],
            series_text=[None, None],
            game_subtype=[None, None],
            is_neutral=[False, False],
            postponed_status=["", ""],
        )
        staging = _register_staging(conn, schedule_int, _make_stg_schedule_int_weeks())
        t = DimScheduleIntTransformer()
        t._conn = conn
        result = t.transform(staging)

        assert result.shape[0] == 1
        # Should keep the row with the higher gameStatus (3 = Final)
        assert result["game_status"][0] == 3

    def test_multiple_games(self, conn: duckdb.DuckDBPyConnection) -> None:
        from nbadb.transform.dimensions.dim_schedule_int import DimScheduleIntTransformer

        schedule_int = _make_stg_schedule_int(
            game_id=["0012400001", "0012400002"],
            game_code=["20250115/BOSCHI", "20250116/LALMIA"],
            league_id=["00", "00"],
            season_year=["2024-25", "2024-25"],
            game_date=["2025-01-15", "2025-01-16"],
            game_date_est=["2025-01-15T00:00:00", "2025-01-16T00:00:00"],
            game_date_time_est=["2025-01-15T19:30:00", "2025-01-16T19:00:00"],
            game_date_utc=["2025-01-16", "2025-01-17"],
            game_time_utc=["00:30:00", "00:00:00"],
            game_date_time_utc=["2025-01-16T00:30:00", "2025-01-17T00:00:00"],
            game_status=[3, 3],
            game_status_text=["Final", "Final"],
            game_sequence=[1, 2],
            week_number=[1, 1],
            week_name=["Week 1", "Week 1"],
            day=["Wednesday", "Thursday"],
            arena_name=["United Center", "FTX Arena"],
            arena_city=["Chicago", "Miami"],
            arena_state=["IL", "FL"],
            home_team_team_id=[1610612741, 1610612748],
            home_team_team_name=["Bulls", "Heat"],
            home_team_team_city=["Chicago", "Miami"],
            home_team_team_tricode=["CHI", "MIA"],
            home_team_wins=[10, 8],
            home_team_losses=[5, 7],
            home_team_score=[110, 98],
            away_team_team_id=[1610612738, 1610612747],
            away_team_team_name=["Celtics", "Lakers"],
            away_team_team_city=["Boston", "Los Angeles"],
            away_team_team_tricode=["BOS", "LAL"],
            away_team_wins=[12, 11],
            away_team_losses=[3, 4],
            away_team_score=[105, 102],
            if_necessary=[False, False],
            series_text=[None, None],
            game_subtype=[None, None],
            is_neutral=[False, False],
            postponed_status=["", ""],
        )
        staging = _register_staging(conn, schedule_int, _make_stg_schedule_int_weeks())
        t = DimScheduleIntTransformer()
        t._conn = conn
        result = t.transform(staging)

        assert result.shape[0] == 2
        # Sorted by game_date, game_id
        assert result["game_id"].to_list() == ["0012400001", "0012400002"]

    def test_week_join_populates_dates(self, conn: duckdb.DuckDBPyConnection) -> None:
        from nbadb.transform.dimensions.dim_schedule_int import DimScheduleIntTransformer

        staging = _register_staging(conn, _make_stg_schedule_int(), _make_stg_schedule_int_weeks())
        t = DimScheduleIntTransformer()
        t._conn = conn
        result = t.transform(staging)

        assert result["week_start_date"][0] is not None
        assert result["week_end_date"][0] is not None

    def test_week_join_null_when_no_match(self, conn: duckdb.DuckDBPyConnection) -> None:
        from nbadb.transform.dimensions.dim_schedule_int import DimScheduleIntTransformer

        # Week data for week 2, but game is week 1 — should produce null week dates
        weeks = _make_stg_schedule_int_weeks(week_number=[2], week_name=["Week 2"])
        staging = _register_staging(conn, _make_stg_schedule_int(), weeks)
        t = DimScheduleIntTransformer()
        t._conn = conn
        result = t.transform(staging)

        assert result.shape[0] == 1
        assert result["week_start_date"][0] is None
        assert result["week_end_date"][0] is None

    def test_column_renaming(self, conn: duckdb.DuckDBPyConnection) -> None:
        from nbadb.transform.dimensions.dim_schedule_int import DimScheduleIntTransformer

        staging = _register_staging(conn, _make_stg_schedule_int(), _make_stg_schedule_int_weeks())
        t = DimScheduleIntTransformer()
        t._conn = conn
        result = t.transform(staging)

        # Verify snake_case renaming
        expected_cols = {
            "game_id",
            "game_code",
            "league_id",
            "season_year",
            "game_date",
            "game_status",
            "home_team_id",
            "home_team_name",
            "away_team_id",
            "away_team_name",
            "arena_name",
            "arena_city",
            "week_number",
            "week_start_date",
            "week_end_date",
            "is_neutral",
            "day_of_week",
        }
        assert expected_cols.issubset(set(result.columns))
