"""Tests for dim_team_history SCD2 transformer."""

from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.dimensions.dim_team_history import DimTeamHistoryTransformer


class TestDimTeamHistory:
    def test_class_attributes(self) -> None:
        assert DimTeamHistoryTransformer.output_table == "dim_team_history"
        assert "stg_team_info" in DimTeamHistoryTransformer.depends_on
        assert "stg_franchise" in DimTeamHistoryTransformer.depends_on

    def test_scd2_detects_city_change(self) -> None:
        """When a team relocates, SCD2 creates a new version."""
        conn = duckdb.connect()
        team_info = pl.DataFrame(
            {
                "team_id": [1, 1],
                "city": ["Seattle", "Oklahoma City"],
                "full_name": ["SuperSonics", "Thunder"],
                "abbreviation": ["SEA", "OKC"],
                "season_year": ["2007-08", "2008-09"],
            }
        )
        franchise = pl.DataFrame(
            {
                "team_id": [1],
                "team_name": ["Thunder"],
                "league_id": ["00"],
            }
        )
        conn.register("stg_team_info", team_info)
        conn.register("stg_franchise", franchise)

        t = DimTeamHistoryTransformer()
        t._conn = conn
        result = t.transform({})

        assert result.shape[0] == 2  # Two versions
        seattle = result.filter(pl.col("city") == "Seattle")
        okc = result.filter(pl.col("city") == "Oklahoma City")
        assert seattle["is_current"][0] is False
        assert seattle["valid_to"][0] == "2008-09"
        assert okc["is_current"][0] is True
        assert okc["valid_to"][0] is None
        conn.close()

    def test_scd2_no_change_single_version(self) -> None:
        """Team with no changes across seasons produces one row."""
        conn = duckdb.connect()
        team_info = pl.DataFrame(
            {
                "team_id": [1, 1, 1],
                "city": ["Boston", "Boston", "Boston"],
                "full_name": ["Celtics", "Celtics", "Celtics"],
                "abbreviation": ["BOS", "BOS", "BOS"],
                "season_year": ["2022-23", "2023-24", "2024-25"],
            }
        )
        franchise = pl.DataFrame(
            {
                "team_id": [1],
                "team_name": ["Celtics"],
                "league_id": ["00"],
            }
        )
        conn.register("stg_team_info", team_info)
        conn.register("stg_franchise", franchise)

        t = DimTeamHistoryTransformer()
        t._conn = conn
        result = t.transform({})

        assert result.shape[0] == 1  # Only one version (no changes)
        assert result["is_current"][0] is True
        assert result["valid_from"][0] == "2022-23"
        conn.close()

    def test_scd2_surrogate_key(self) -> None:
        """Each version gets a unique surrogate key."""
        conn = duckdb.connect()
        team_info = pl.DataFrame(
            {
                "team_id": [1, 1, 2],
                "city": ["New Jersey", "Brooklyn", "Los Angeles"],
                "full_name": ["Nets", "Nets", "Lakers"],
                "abbreviation": ["NJN", "BKN", "LAL"],
                "season_year": ["2011-12", "2012-13", "2012-13"],
            }
        )
        franchise = pl.DataFrame(
            {
                "team_id": [1, 2],
                "team_name": ["Nets", "Lakers"],
                "league_id": ["00", "00"],
            }
        )
        conn.register("stg_team_info", team_info)
        conn.register("stg_franchise", franchise)

        t = DimTeamHistoryTransformer()
        t._conn = conn
        result = t.transform({})

        # 2 versions for Nets + 1 for Lakers = 3
        assert result.shape[0] == 3
        sks = result["team_history_sk"].to_list()
        assert len(set(sks)) == 3  # All unique
        assert sks == sorted(sks)  # Sequential
        conn.close()

    def test_scd2_detects_nickname_change(self) -> None:
        """When only the nickname changes, SCD2 creates a new version."""
        conn = duckdb.connect()
        team_info = pl.DataFrame(
            {
                "team_id": [1, 1],
                "city": ["Washington", "Washington"],
                "full_name": ["Bullets", "Wizards"],
                "abbreviation": ["WAS", "WAS"],
                "season_year": ["1996-97", "1997-98"],
            }
        )
        franchise = pl.DataFrame(
            {
                "team_id": [1],
                "team_name": ["Wizards"],
                "league_id": ["00"],
            }
        )
        conn.register("stg_team_info", team_info)
        conn.register("stg_franchise", franchise)

        t = DimTeamHistoryTransformer()
        t._conn = conn
        result = t.transform({})

        assert result.shape[0] == 2
        bullets = result.filter(pl.col("nickname") == "Bullets")
        wizards = result.filter(pl.col("nickname") == "Wizards")
        assert bullets["is_current"][0] is False
        assert wizards["is_current"][0] is True
        conn.close()

    def test_scd2_detects_abbreviation_change(self) -> None:
        """When only the abbreviation changes, SCD2 creates a new version."""
        conn = duckdb.connect()
        team_info = pl.DataFrame(
            {
                "team_id": [1, 1],
                "city": ["Charlotte", "Charlotte"],
                "full_name": ["Hornets", "Hornets"],
                "abbreviation": ["CHA", "CHH"],
                "season_year": ["2013-14", "2014-15"],
            }
        )
        franchise = pl.DataFrame(
            {
                "team_id": [1],
                "team_name": ["Hornets"],
                "league_id": ["00"],
            }
        )
        conn.register("stg_team_info", team_info)
        conn.register("stg_franchise", franchise)

        t = DimTeamHistoryTransformer()
        t._conn = conn
        result = t.transform({})

        assert result.shape[0] == 2
        conn.close()

    def test_valid_from_valid_to_non_overlapping(self) -> None:
        """valid_to of row N == valid_from of row N+1 for the same team."""
        conn = duckdb.connect()
        team_info = pl.DataFrame(
            {
                "team_id": [1, 1, 1],
                "city": ["Seattle", "Oklahoma City", "Oklahoma City"],
                "full_name": ["SuperSonics", "Thunder", "Sonics Revival"],
                "abbreviation": ["SEA", "OKC", "OKC"],
                "season_year": ["2006-07", "2008-09", "2030-31"],
            }
        )
        franchise = pl.DataFrame(
            {
                "team_id": [1],
                "team_name": ["Thunder"],
                "league_id": ["00"],
            }
        )
        conn.register("stg_team_info", team_info)
        conn.register("stg_franchise", franchise)

        t = DimTeamHistoryTransformer()
        t._conn = conn
        result = t.transform({})

        rows = result.filter(pl.col("team_id") == 1).sort("valid_from")
        assert rows.shape[0] == 3
        # valid_to of row 0 == valid_from of row 1
        assert rows["valid_to"][0] == rows["valid_from"][1]
        # valid_to of row 1 == valid_from of row 2
        assert rows["valid_to"][1] == rows["valid_from"][2]
        # last row has null valid_to
        assert rows["valid_to"][2] is None
        conn.close()

    def test_is_current_only_on_latest(self) -> None:
        """Only the last version of each team should have is_current=True."""
        conn = duckdb.connect()
        team_info = pl.DataFrame(
            {
                "team_id": [1, 1, 2, 2],
                "city": ["Seattle", "Oklahoma City", "Vancouver", "Memphis"],
                "full_name": ["SuperSonics", "Thunder", "Grizzlies", "Grizzlies"],
                "abbreviation": ["SEA", "OKC", "VAN", "MEM"],
                "season_year": ["2007-08", "2008-09", "2000-01", "2001-02"],
            }
        )
        franchise = pl.DataFrame(
            {
                "team_id": [1, 2],
                "team_name": ["Thunder", "Grizzlies"],
                "league_id": ["00", "00"],
            }
        )
        conn.register("stg_team_info", team_info)
        conn.register("stg_franchise", franchise)

        t = DimTeamHistoryTransformer()
        t._conn = conn
        result = t.transform({})

        for tid in result["team_id"].unique().to_list():
            team_rows = result.filter(pl.col("team_id") == tid).sort("valid_from")
            current_rows = team_rows.filter(pl.col("is_current"))
            assert current_rows.shape[0] == 1
            assert current_rows["valid_from"][0] == team_rows["valid_from"][-1]
        conn.close()

    def test_franchise_columns_populated(self) -> None:
        """franchise_name and league_id come from stg_franchise join."""
        conn = duckdb.connect()
        team_info = pl.DataFrame(
            {
                "team_id": [1],
                "city": ["Los Angeles"],
                "full_name": ["Lakers"],
                "abbreviation": ["LAL"],
                "season_year": ["2024-25"],
            }
        )
        franchise = pl.DataFrame(
            {
                "team_id": [1],
                "team_name": ["Lakers"],
                "league_id": ["00"],
            }
        )
        conn.register("stg_team_info", team_info)
        conn.register("stg_franchise", franchise)

        t = DimTeamHistoryTransformer()
        t._conn = conn
        result = t.transform({})

        assert result.shape[0] == 1
        assert result["franchise_name"][0] == "Lakers"
        assert result["league_id"][0] == "00"
        conn.close()

    def test_missing_franchise_produces_nulls(self) -> None:
        """If stg_franchise has no matching row, franchise_name/league_id are NULL."""
        conn = duckdb.connect()
        team_info = pl.DataFrame(
            {
                "team_id": [999],
                "city": ["Atlantis"],
                "full_name": ["Dolphins"],
                "abbreviation": ["ATL"],
                "season_year": ["2024-25"],
            }
        )
        franchise = pl.DataFrame(
            {
                "team_id": [1],
                "team_name": ["Lakers"],
                "league_id": ["00"],
            }
        )
        conn.register("stg_team_info", team_info)
        conn.register("stg_franchise", franchise)

        t = DimTeamHistoryTransformer()
        t._conn = conn
        result = t.transform({})

        assert result.shape[0] == 1
        assert result["franchise_name"][0] is None
        assert result["league_id"][0] is None
        conn.close()
