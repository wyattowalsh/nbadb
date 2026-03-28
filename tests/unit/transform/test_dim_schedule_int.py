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
        "gameId": ["0012400001"],
        "gameCode": ["20250115/BOSCHI"],
        "leagueId": ["00"],
        "seasonYear": ["2024-25"],
        "gameDate": ["2025-01-15"],
        "gameDateEst": ["2025-01-15T00:00:00"],
        "gameDateTimeEst": ["2025-01-15T19:30:00"],
        "gameDateUTC": ["2025-01-16"],
        "gameTimeUTC": ["00:30:00"],
        "gameDateTimeUTC": ["2025-01-16T00:30:00"],
        "gameStatus": [3],
        "gameStatusText": ["Final"],
        "gameSequence": [1],
        "weekNumber": [1],
        "weekName": ["Week 1"],
        "day": ["Wednesday"],
        "arenaName": ["United Center"],
        "arenaCity": ["Chicago"],
        "arenaState": ["IL"],
        "homeTeam_teamId": [1610612741],
        "homeTeam_teamName": ["Bulls"],
        "homeTeam_teamCity": ["Chicago"],
        "homeTeam_teamTricode": ["CHI"],
        "homeTeam_wins": [10],
        "homeTeam_losses": [5],
        "homeTeam_score": [110],
        "awayTeam_teamId": [1610612738],
        "awayTeam_teamName": ["Celtics"],
        "awayTeam_teamCity": ["Boston"],
        "awayTeam_teamTricode": ["BOS"],
        "awayTeam_wins": [12],
        "awayTeam_losses": [3],
        "awayTeam_score": [105],
        "ifNecessary": [False],
        "seriesText": [None],
        "gameSubtype": [None],
        "isNeutral": [False],
        "postponedStatus": [""],
    }
    defaults.update(overrides)
    return pl.DataFrame(defaults)


def _make_stg_schedule_int_weeks(**overrides: object) -> pl.DataFrame:
    """Return a minimal stg_schedule_int_weeks DataFrame."""
    defaults: dict[str, list[object]] = {
        "leagueId": ["00"],
        "seasonYear": ["2024-25"],
        "weekNumber": [1],
        "weekName": ["Week 1"],
        "startDate": ["2025-01-13"],
        "endDate": ["2025-01-19"],
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
            gameId=["0012400001", "0012400001"],
            gameCode=["20250115/BOSCHI", "20250115/BOSCHI"],
            gameStatus=[1, 3],
            gameStatusText=["Scheduled", "Final"],
            homeTeam_score=[0, 110],
            awayTeam_score=[0, 105],
            # Duplicate all other columns
            leagueId=["00", "00"],
            seasonYear=["2024-25", "2024-25"],
            gameDate=["2025-01-15", "2025-01-15"],
            gameDateEst=["2025-01-15T00:00:00", "2025-01-15T00:00:00"],
            gameDateTimeEst=["2025-01-15T19:30:00", "2025-01-15T19:30:00"],
            gameDateUTC=["2025-01-16", "2025-01-16"],
            gameTimeUTC=["00:30:00", "00:30:00"],
            gameDateTimeUTC=["2025-01-16T00:30:00", "2025-01-16T00:30:00"],
            gameSequence=[1, 1],
            weekNumber=[1, 1],
            weekName=["Week 1", "Week 1"],
            day=["Wednesday", "Wednesday"],
            arenaName=["United Center", "United Center"],
            arenaCity=["Chicago", "Chicago"],
            arenaState=["IL", "IL"],
            homeTeam_teamId=[1610612741, 1610612741],
            homeTeam_teamName=["Bulls", "Bulls"],
            homeTeam_teamCity=["Chicago", "Chicago"],
            homeTeam_teamTricode=["CHI", "CHI"],
            homeTeam_wins=[10, 10],
            homeTeam_losses=[5, 5],
            awayTeam_teamId=[1610612738, 1610612738],
            awayTeam_teamName=["Celtics", "Celtics"],
            awayTeam_teamCity=["Boston", "Boston"],
            awayTeam_teamTricode=["BOS", "BOS"],
            awayTeam_wins=[12, 12],
            awayTeam_losses=[3, 3],
            ifNecessary=[False, False],
            seriesText=[None, None],
            gameSubtype=[None, None],
            isNeutral=[False, False],
            postponedStatus=["", ""],
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
            gameId=["0012400001", "0012400002"],
            gameCode=["20250115/BOSCHI", "20250116/LALMIA"],
            leagueId=["00", "00"],
            seasonYear=["2024-25", "2024-25"],
            gameDate=["2025-01-15", "2025-01-16"],
            gameDateEst=["2025-01-15T00:00:00", "2025-01-16T00:00:00"],
            gameDateTimeEst=["2025-01-15T19:30:00", "2025-01-16T19:00:00"],
            gameDateUTC=["2025-01-16", "2025-01-17"],
            gameTimeUTC=["00:30:00", "00:00:00"],
            gameDateTimeUTC=["2025-01-16T00:30:00", "2025-01-17T00:00:00"],
            gameStatus=[3, 3],
            gameStatusText=["Final", "Final"],
            gameSequence=[1, 2],
            weekNumber=[1, 1],
            weekName=["Week 1", "Week 1"],
            day=["Wednesday", "Thursday"],
            arenaName=["United Center", "FTX Arena"],
            arenaCity=["Chicago", "Miami"],
            arenaState=["IL", "FL"],
            homeTeam_teamId=[1610612741, 1610612748],
            homeTeam_teamName=["Bulls", "Heat"],
            homeTeam_teamCity=["Chicago", "Miami"],
            homeTeam_teamTricode=["CHI", "MIA"],
            homeTeam_wins=[10, 8],
            homeTeam_losses=[5, 7],
            homeTeam_score=[110, 98],
            awayTeam_teamId=[1610612738, 1610612747],
            awayTeam_teamName=["Celtics", "Lakers"],
            awayTeam_teamCity=["Boston", "Los Angeles"],
            awayTeam_teamTricode=["BOS", "LAL"],
            awayTeam_wins=[12, 11],
            awayTeam_losses=[3, 4],
            awayTeam_score=[105, 102],
            ifNecessary=[False, False],
            seriesText=[None, None],
            gameSubtype=[None, None],
            isNeutral=[False, False],
            postponedStatus=["", ""],
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
        weeks = _make_stg_schedule_int_weeks(weekNumber=[2], weekName=["Week 2"])
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
