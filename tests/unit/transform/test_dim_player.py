from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.dimensions.dim_player import DimPlayerTransformer


def _run_transform(t: DimPlayerTransformer, staging: dict) -> pl.DataFrame:
    """Inject a shared DuckDB connection and run the transformer."""
    conn = duckdb.connect()
    for key, val in staging.items():
        conn.register(key, val.collect())
    t._conn = conn
    result = t.transform(staging)
    conn.close()
    return result


def _make_player_info(**overrides: list) -> pl.DataFrame:
    """Helper to build stg_player_info with sensible defaults."""
    defaults = {
        "player_id": [1, 1, 2],
        "full_name": ["Player A", "Player A", "Player B"],
        "first_name": ["Player", "Player", "Player"],
        "last_name": ["A", "A", "B"],
        "roster_status": ["Active", "Active", "Inactive"],
        "team_id": [10, 20, 30],
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
        "season": ["2023-24", "2024-25", "2024-25"],
    }
    defaults.update(overrides)
    return pl.DataFrame(defaults)


class TestDimPlayerTransformer:
    def test_class_attributes(self) -> None:
        assert DimPlayerTransformer.output_table == "dim_player"
        assert "stg_player_info" in DimPlayerTransformer.depends_on

    def test_scd2_produces_rows(self) -> None:
        stg = _make_player_info()
        t = DimPlayerTransformer()
        result = _run_transform(t, {"stg_player_info": stg.lazy()})
        assert result.shape[0] >= 2
        assert "player_sk" in result.columns
        assert "is_current" in result.columns
        assert "valid_from" in result.columns

    def test_scd2_detects_team_change(self) -> None:
        stg = _make_player_info(
            player_id=[1, 1],
            full_name=["Player A", "Player A"],
            first_name=["Player", "Player"],
            last_name=["A", "A"],
            roster_status=["Active", "Active"],
            team_id=[10, 20],
            position=["G", "G"],
            jersey_number=["1", "1"],
            height=["6-3", "6-3"],
            weight=[190, 190],
            birth_date=["1990-01-01", "1990-01-01"],
            country=["USA", "USA"],
            draft_year=[2012, 2012],
            draft_round=[1, 1],
            draft_number=[4, 4],
            college_id=[None, None],
            from_year=["2012", "2012"],
            to_year=["2025", "2025"],
            season=["2023-24", "2024-25"],
        )
        t = DimPlayerTransformer()
        result = _run_transform(t, {"stg_player_info": stg.lazy()})
        player_rows = result.filter(pl.col("player_id") == 1)
        assert player_rows.shape[0] == 2
        current = player_rows.filter(pl.col("is_current"))
        assert current.shape[0] == 1
        assert current["team_id"][0] == 20

    def test_surrogate_keys_are_sequential(self) -> None:
        """player_sk should be sequential integers starting from 1."""
        stg = _make_player_info()
        t = DimPlayerTransformer()
        result = _run_transform(t, {"stg_player_info": stg.lazy()})
        sks = result["player_sk"].to_list()
        assert sks == list(range(1, len(sks) + 1))

    def test_single_team_player_has_one_row(self) -> None:
        """A player who never changed teams should have exactly 1 row with is_current=True."""
        stg = _make_player_info(
            player_id=[99, 99, 99],
            full_name=["Stable Player", "Stable Player", "Stable Player"],
            first_name=["Stable", "Stable", "Stable"],
            last_name=["Player", "Player", "Player"],
            roster_status=["Active", "Active", "Active"],
            team_id=[50, 50, 50],
            position=["C", "C", "C"],
            jersey_number=["7", "7", "7"],
            height=["7-0", "7-0", "7-0"],
            weight=[260, 260, 260],
            birth_date=["1995-03-15", "1995-03-15", "1995-03-15"],
            country=["USA", "USA", "USA"],
            draft_year=[2017, 2017, 2017],
            draft_round=[1, 1, 1],
            draft_number=[3, 3, 3],
            college_id=[None, None, None],
            from_year=["2017", "2017", "2017"],
            to_year=["2025", "2025", "2025"],
            season=["2022-23", "2023-24", "2024-25"],
        )
        t = DimPlayerTransformer()
        result = _run_transform(t, {"stg_player_info": stg.lazy()})
        assert result.shape[0] == 1
        assert result["is_current"][0] is True
        assert result["valid_to"][0] is None

    def test_valid_from_valid_to_non_overlapping(self) -> None:
        """For a player with multiple versions, valid_to of row N == valid_from of row N+1."""
        stg = _make_player_info(
            player_id=[1, 1, 1],
            full_name=["Player A", "Player A", "Player A"],
            first_name=["Player", "Player", "Player"],
            last_name=["A", "A", "A"],
            roster_status=["Active", "Active", "Active"],
            team_id=[10, 20, 30],
            position=["G", "G", "F"],
            jersey_number=["1", "1", "1"],
            height=["6-3", "6-3", "6-3"],
            weight=[190, 190, 190],
            birth_date=["1990-01-01", "1990-01-01", "1990-01-01"],
            country=["USA", "USA", "USA"],
            draft_year=[2012, 2012, 2012],
            draft_round=[1, 1, 1],
            draft_number=[4, 4, 4],
            college_id=[None, None, None],
            from_year=["2012", "2012", "2012"],
            to_year=["2025", "2025", "2025"],
            season=["2022-23", "2023-24", "2024-25"],
        )
        t = DimPlayerTransformer()
        result = _run_transform(t, {"stg_player_info": stg.lazy()})
        rows = result.sort("player_sk")
        assert rows.shape[0] == 3
        # valid_to of row 0 == valid_from of row 1
        assert rows["valid_to"][0] == rows["valid_from"][1]
        # valid_to of row 1 == valid_from of row 2
        assert rows["valid_to"][1] == rows["valid_from"][2]
        # last row has null valid_to
        assert rows["valid_to"][2] is None

    def test_new_columns_present(self) -> None:
        """first_name, last_name, is_active, from_year, to_year must appear."""
        stg = _make_player_info()
        t = DimPlayerTransformer()
        result = _run_transform(t, {"stg_player_info": stg.lazy()})
        for col in ("first_name", "last_name", "is_active", "from_year", "to_year"):
            assert col in result.columns, f"missing column: {col}"
        # is_active should be boolean
        current = result.filter(pl.col("is_current"))
        assert current["is_active"].dtype == pl.Boolean
        # from_year / to_year should be integers
        assert result["from_year"].dtype in (pl.Int32, pl.Int64)
        assert result["to_year"].dtype in (pl.Int32, pl.Int64)

    def test_is_current_only_on_latest(self) -> None:
        """Only the last version of each player should have is_current=True."""
        stg = _make_player_info()
        t = DimPlayerTransformer()
        result = _run_transform(t, {"stg_player_info": stg.lazy()})
        for pid in result["player_id"].unique().to_list():
            player_rows = result.filter(pl.col("player_id") == pid).sort("valid_from")
            current_rows = player_rows.filter(pl.col("is_current"))
            assert current_rows.shape[0] == 1
            # The current row should be the last one
            assert current_rows["valid_from"][0] == player_rows["valid_from"][-1]
