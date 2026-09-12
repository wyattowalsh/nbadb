from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.derived.agg_player_bio import AggPlayerBioTransformer
from nbadb.transform.dimensions.dim_team_extended import DimTeamExtendedTransformer
from nbadb.transform.facts.fact_player_game_log import FactPlayerGameLogTransformer
from nbadb.transform.facts.fact_team_game_log import FactTeamGameLogTransformer


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    for key, val in staging.items():
        conn.register(key, val.collect())
    transformer._conn = conn
    result = transformer.transform(staging)
    conn.close()
    return result


# ---------------------------------------------------------------------------
# 1. dim_team_extended — JOINs on team_id
# ---------------------------------------------------------------------------
class TestDimTeamExtended:
    def test_class_attrs(self) -> None:
        assert DimTeamExtendedTransformer.output_table == "dim_team_extended"
        assert set(DimTeamExtendedTransformer.depends_on) == {
            "stg_team_details",
            "stg_team_info_common",
            "stg_team_years",
        }

    def test_join_on_team_id(self) -> None:
        staging = {
            "stg_team_details": pl.DataFrame(
                {"team_id": [1], "city": ["Boston"], "nickname": ["Celtics"]}
            ).lazy(),
            "stg_team_info_common": pl.DataFrame(
                {"team_id": [1], "abbreviation": ["BOS"], "conference": ["East"]}
            ).lazy(),
            "stg_team_years": pl.DataFrame(
                {"team_id": [1], "min_year": [1946], "max_year": [2024]}
            ).lazy(),
        }
        result = _run(DimTeamExtendedTransformer(), staging)
        assert result.shape[0] == 1
        assert "team_id" in result.columns
        assert "city" in result.columns
        assert "abbreviation" in result.columns
        assert "min_year" in result.columns
        # team_id should appear once (EXCLUDE removes duplicates from joined tables)
        assert result.columns.count("team_id") == 1

    def test_left_join_team_years_null(self) -> None:
        staging = {
            "stg_team_details": pl.DataFrame({"team_id": [1], "city": ["Boston"]}).lazy(),
            "stg_team_info_common": pl.DataFrame({"team_id": [1], "abbreviation": ["BOS"]}).lazy(),
            "stg_team_years": pl.DataFrame({"team_id": [999], "min_year": [2000]}).lazy(),
        }
        result = _run(DimTeamExtendedTransformer(), staging)
        assert result.shape[0] == 1
        assert result["min_year"][0] is None

    def test_inner_join_filters_missing_common(self) -> None:
        """stg_team_info_common uses INNER JOIN, so missing rows are excluded."""
        staging = {
            "stg_team_details": pl.DataFrame({"team_id": [1, 2], "city": ["Boston", "LA"]}).lazy(),
            "stg_team_info_common": pl.DataFrame({"team_id": [1], "abbreviation": ["BOS"]}).lazy(),
            "stg_team_years": pl.DataFrame({"team_id": [1, 2], "min_year": [1946, 1960]}).lazy(),
        }
        result = _run(DimTeamExtendedTransformer(), staging)
        # Only team_id=1 survives the INNER JOIN with stg_team_info_common
        assert result.shape[0] == 1
        assert result["team_id"][0] == 1


# ---------------------------------------------------------------------------
# 2. agg_player_bio — pinned player-team-season projection
# ---------------------------------------------------------------------------
_BIO_PUBLIC_COLUMNS = [
    "player_id",
    "player_name",
    "team_id",
    "team_abbreviation",
    "age",
    "player_height",
    "player_height_inches",
    "player_weight",
    "college",
    "country",
    "draft_year",
    "draft_round",
    "draft_number",
    "gp",
    "pts",
    "reb",
    "ast",
    "net_rating",
    "oreb_pct",
    "dreb_pct",
    "usg_pct",
    "ts_pct",
    "ast_pct",
    "season_year",
    "season_type",
]

_BIO_DTYPES = {
    "player_id": pl.Int64,
    "player_name": pl.String,
    "team_id": pl.Int64,
    "team_abbreviation": pl.String,
    "age": pl.Float64,
    "player_height": pl.String,
    "player_height_inches": pl.Float64,
    "player_weight": pl.Float64,
    "college": pl.String,
    "country": pl.String,
    "draft_year": pl.String,
    "draft_round": pl.String,
    "draft_number": pl.String,
    "gp": pl.Int64,
    "pts": pl.Float64,
    "reb": pl.Float64,
    "ast": pl.Float64,
    "net_rating": pl.Float64,
    "oreb_pct": pl.Float64,
    "dreb_pct": pl.Float64,
    "usg_pct": pl.Float64,
    "ts_pct": pl.Float64,
    "ast_pct": pl.Float64,
    "season_year": pl.String,
    "season_type": pl.String,
}


def _bio_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "player_id": 101,
        "player_name": "Nikola Jokic",
        "team_id": 1610612743,
        "team_abbreviation": "DEN",
        "age": 29.0,
        "player_height": "6-11",
        "player_height_inches": 83.0,
        "player_weight": 284.0,
        "college": None,
        "country": "Serbia",
        "draft_year": "2014",
        "draft_round": "2",
        "draft_number": "41",
        "gp": 79,
        "pts": 26.4,
        "reb": 12.4,
        "ast": 9.0,
        "net_rating": 10.1,
        "oreb_pct": 0.09,
        "dreb_pct": 0.31,
        "usg_pct": 0.29,
        "ts_pct": 0.65,
        "ast_pct": 0.42,
        "season_year": "2024-25",
        "season_type": "Regular Season",
    }
    row.update(updates)
    return row


def _run_player_bio(rows: list[dict[str, object]]) -> pl.DataFrame:
    frame = pl.DataFrame(rows, schema_overrides=_BIO_DTYPES)
    staging = {"stg_league_player_bio": frame.lazy()}
    transformer = AggPlayerBioTransformer()
    conn = duckdb.connect()
    try:
        conn.register("stg_league_player_bio", frame)
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


class TestAggPlayerBio:
    def test_exact_pinned_provider_projection_and_dependency(self) -> None:
        import nba_api
        from nba_api.stats.endpoints.leaguedashplayerbiostats import (
            LeagueDashPlayerBioStats,
        )

        from nbadb.extract.base import _inject_request_scope_columns
        from nbadb.schemas.staging.league_support import StagingLeaguePlayerBioSchema
        from nbadb.schemas.star.agg_schemas import AggPlayerBioSchema

        assert nba_api.__version__ == "1.11.4"
        expected_provider_columns = LeagueDashPlayerBioStats.expected_data[
            "LeagueDashPlayerBioStats"
        ]
        assert [column.lower() for column in expected_provider_columns] + [
            "season_year",
            "season_type",
        ] == _BIO_PUBLIC_COLUMNS
        injected = _inject_request_scope_columns(
            pl.DataFrame({"player_id": [101]}),
            {"season": "2024-25", "season_type_all_star": "Playoffs"},
        )
        assert injected.columns == ["player_id", "season_year", "season_type"]
        assert injected.select("season_year", "season_type").row(0) == (
            "2024-25",
            "Playoffs",
        )
        assert AggPlayerBioTransformer.output_table == "agg_player_bio"
        assert AggPlayerBioTransformer.depends_on == ["stg_league_player_bio"]
        normalized_sql = " ".join(AggPlayerBioTransformer._SQL.lower().split())
        assert "select *" not in normalized_sql
        assert normalized_sql.count("from stg_league_player_bio") == 1
        staging_weight = StagingLeaguePlayerBioSchema.to_schema().columns["player_weight"]
        public_weight = AggPlayerBioSchema.to_schema().columns["player_weight"]
        assert str(staging_weight.dtype) == str(public_weight.dtype) == "Float64"

    def test_exact_projection_preserves_team_stints_and_excludes_staging_extras(self) -> None:
        from nbadb.schemas.star.agg_schemas import AggPlayerBioSchema

        first_stint = _bio_row(
            player_id=7,
            player_name="Two Team Player",
            team_id=1610612737,
            team_abbreviation="ATL",
            gp=20,
            height="legacy-height",
            weight=999.0,
            league_id="transport-only",
            transport_extra="discard-me",
        )
        second_stint = _bio_row(
            player_id=7,
            player_name="Two Team Player",
            team_id=1610612738,
            team_abbreviation="BOS",
            gp=30,
            height="legacy-height",
            weight=999.0,
            league_id="transport-only",
            transport_extra="discard-me",
        )
        playoff_same_team = _bio_row(
            player_id=7,
            player_name="Two Team Player",
            team_id=1610612737,
            team_abbreviation="ATL",
            gp=6,
            season_type="Playoffs",
            height="legacy-height",
            weight=999.0,
            transport_extra="discard-me",
        )

        result = _run_player_bio([second_stint, playoff_same_team, first_stint])

        assert result.columns == _BIO_PUBLIC_COLUMNS
        assert result.select("player_id", "team_id", "season_year", "season_type").to_dicts() == [
            {
                "player_id": 7,
                "team_id": 1610612737,
                "season_year": "2024-25",
                "season_type": "Playoffs",
            },
            {
                "player_id": 7,
                "team_id": 1610612737,
                "season_year": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 7,
                "team_id": 1610612738,
                "season_year": "2024-25",
                "season_type": "Regular Season",
            },
        ]
        assert result["player_weight"].dtype == pl.Float64
        assert list(AggPlayerBioSchema.to_schema().columns) == result.columns
        assert AggPlayerBioSchema.validate(result).to_dicts() == result.to_dicts()

    def test_exact_duplicates_collapse_at_player_team_season_type_grain(self) -> None:
        row = _bio_row()
        result = _run_player_bio([row, row.copy(), row.copy()])

        assert result.shape == (1, len(_BIO_PUBLIC_COLUMNS))

    def test_null_player_name_and_unknown_team_identity_are_preserved(self) -> None:
        from nbadb.schemas.star.agg_schemas import AggPlayerBioSchema

        result = _run_player_bio([_bio_row(player_name=None, team_id=None)])

        assert result.select("player_name", "team_id").row(0) == (None, None)
        assert AggPlayerBioSchema.validate(result).to_dicts() == result.to_dicts()

    def test_conflicting_tuple_at_same_key_fails_closed(self) -> None:
        with pytest.raises(duckdb.Error, match="conflicting player bio tuple"):
            _run_player_bio([_bio_row(pts=26.4), _bio_row(pts=27.1)])

    @pytest.mark.parametrize(
        ("updates", "message"),
        [
            ({"player_id": None}, "invalid player_id"),
            ({"player_id": 0}, "invalid player_id"),
            ({"player_id": -1}, "invalid player_id"),
            ({"team_id": 0}, "invalid team_id"),
            ({"team_id": -1}, "invalid team_id"),
            ({"season_year": None}, "invalid season_year"),
            ({"season_year": ""}, "invalid season_year"),
            ({"season_year": "   "}, "invalid season_year"),
            ({"season_type": None}, "invalid season_type"),
            ({"season_type": ""}, "invalid season_type"),
            ({"season_type": "   "}, "invalid season_type"),
        ],
    )
    def test_null_or_invalid_grain_key_fails_closed(
        self,
        updates: dict[str, object],
        message: str,
    ) -> None:
        with pytest.raises(duckdb.Error, match=message):
            _run_player_bio([_bio_row(**updates)])


# ---------------------------------------------------------------------------
# 3. fact_player_game_log — UNION ALL BY NAME + QUALIFY dedup
# ---------------------------------------------------------------------------
class TestFactPlayerGameLog:
    def test_class_attrs(self) -> None:
        assert FactPlayerGameLogTransformer.output_table == "fact_player_game_log"
        assert set(FactPlayerGameLogTransformer.depends_on) == {
            "stg_player_game_logs",
            "stg_player_game_log",
            "stg_player_game_logs_v2",
        }

    def test_union_and_dedup(self) -> None:
        """Duplicate player_id+game_id rows across sources should be deduplicated."""
        staging = {
            "stg_player_game_logs": pl.DataFrame(
                {
                    "player_id": [1, 2],
                    "game_id": ["G1", "G2"],
                    "season_year": ["2024-25", "2024-25"],
                    "pts": [20, 30],
                }
            ).lazy(),
            "stg_player_game_log": pl.DataFrame(
                {"player_id": [1], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [20]}
            ).lazy(),
            "stg_player_game_logs_v2": pl.DataFrame(
                {"player_id": [1], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [20]}
            ).lazy(),
        }
        result = _run(FactPlayerGameLogTransformer(), staging)
        # player_id=1, game_id=G1 appears in all 3 sources but should be deduplicated
        assert result.shape[0] == 2
        assert "player_id" in result.columns
        assert "game_id" in result.columns

    def test_unique_rows_preserved(self) -> None:
        """Rows that are unique across sources should all be preserved."""
        staging = {
            "stg_player_game_logs": pl.DataFrame(
                {"player_id": [1], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [20]}
            ).lazy(),
            "stg_player_game_log": pl.DataFrame(
                {"player_id": [2], "game_id": ["G2"], "season_year": ["2024-25"], "pts": [25]}
            ).lazy(),
            "stg_player_game_logs_v2": pl.DataFrame(
                {"player_id": [3], "game_id": ["G3"], "season_year": ["2024-25"], "pts": [30]}
            ).lazy(),
        }
        result = _run(FactPlayerGameLogTransformer(), staging)
        assert result.shape[0] == 3

    def test_mismatched_columns_filled_null(self) -> None:
        """UNION ALL BY NAME fills missing columns with NULL."""
        staging = {
            "stg_player_game_logs": pl.DataFrame(
                {"player_id": [1], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [20]}
            ).lazy(),
            "stg_player_game_log": pl.DataFrame(
                {"player_id": [2], "game_id": ["G2"], "season_year": ["2024-25"], "reb": [10]}
            ).lazy(),
            "stg_player_game_logs_v2": pl.DataFrame(
                {"player_id": [3], "game_id": ["G3"], "season_year": ["2024-25"], "ast": [8]}
            ).lazy(),
        }
        result = _run(FactPlayerGameLogTransformer(), staging)
        assert result.shape[0] == 3
        assert "pts" in result.columns
        assert "reb" in result.columns
        assert "ast" in result.columns


# ---------------------------------------------------------------------------
# 4. fact_team_game_log — UNION ALL BY NAME + QUALIFY dedup
# ---------------------------------------------------------------------------
class TestFactTeamGameLog:
    def test_class_attrs(self) -> None:
        assert FactTeamGameLogTransformer.output_table == "fact_team_game_log"
        assert set(FactTeamGameLogTransformer.depends_on) == {
            "stg_team_game_logs_v2",
            "stg_team_game_log",
        }

    def test_union_and_dedup(self) -> None:
        """Duplicate team_id+game_id rows across sources should be deduplicated."""
        staging = {
            "stg_team_game_logs_v2": pl.DataFrame(
                {
                    "team_id": [10, 20],
                    "game_id": ["G1", "G2"],
                    "season_year": ["2024-25", "2024-25"],
                    "pts": [100, 110],
                }
            ).lazy(),
            "stg_team_game_log": pl.DataFrame(
                {"team_id": [10], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [100]}
            ).lazy(),
        }
        result = _run(FactTeamGameLogTransformer(), staging)
        # team_id=10, game_id=G1 appears in both sources but should be deduplicated
        assert result.shape[0] == 2
        assert "team_id" in result.columns
        assert "game_id" in result.columns

    def test_unique_rows_preserved(self) -> None:
        staging = {
            "stg_team_game_logs_v2": pl.DataFrame(
                {"team_id": [10], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [100]}
            ).lazy(),
            "stg_team_game_log": pl.DataFrame(
                {"team_id": [20], "game_id": ["G2"], "season_year": ["2024-25"], "pts": [95]}
            ).lazy(),
        }
        result = _run(FactTeamGameLogTransformer(), staging)
        assert result.shape[0] == 2

    def test_mismatched_columns_filled_null(self) -> None:
        """UNION ALL BY NAME fills missing columns with NULL."""
        staging = {
            "stg_team_game_logs_v2": pl.DataFrame(
                {"team_id": [10], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [100]}
            ).lazy(),
            "stg_team_game_log": pl.DataFrame(
                {"team_id": [20], "game_id": ["G2"], "season_year": ["2024-25"], "fg_pct": [0.48]}
            ).lazy(),
        }
        result = _run(FactTeamGameLogTransformer(), staging)
        assert result.shape[0] == 2
        assert "pts" in result.columns
        assert "fg_pct" in result.columns
