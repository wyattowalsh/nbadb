from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_team_awards_conf import FactTeamAwardsConfTransformer
from nbadb.transform.facts.fact_team_awards_div import FactTeamAwardsDivTransformer
from nbadb.transform.facts.fact_team_background import FactTeamBackgroundTransformer
from nbadb.transform.facts.fact_team_hof import FactTeamHofTransformer
from nbadb.transform.facts.fact_team_retired import FactTeamRetiredTransformer
from nbadb.transform.facts.fact_team_season_ranks import FactTeamSeasonRanksTransformer
from nbadb.transform.facts.fact_team_social_sites import FactTeamSocialSitesTransformer
from nbadb.transform.pipeline import _star_schema_map


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _assert_schema_valid(table: str, df: pl.DataFrame) -> None:
    schema_cls = _star_schema_map()[table]
    validated = schema_cls.validate(df)
    assert isinstance(validated, pl.DataFrame)


class TestTeamReferenceStarSchemas:
    def test_team_awards_conf_schema_validates_transform_output(self) -> None:
        staging = {
            "stg_team_awards_conf": pl.DataFrame(
                {
                    "yearawarded": ["2024"],
                    "oppositeteam": ["Pacers"],
                }
            ).lazy()
        }

        result = _run(FactTeamAwardsConfTransformer(), staging)

        assert result.shape == (1, 2)
        _assert_schema_valid("fact_team_awards_conf", result)

    def test_team_awards_div_schema_validates_transform_output(self) -> None:
        staging = {
            "stg_team_awards_div": pl.DataFrame(
                {
                    "yearawarded": ["2024"],
                    "oppositeteam": ["Knicks"],
                }
            ).lazy()
        }

        result = _run(FactTeamAwardsDivTransformer(), staging)

        assert result.shape == (1, 2)
        _assert_schema_valid("fact_team_awards_div", result)

    def test_team_background_schema_validates_transform_output(self) -> None:
        staging = {
            "stg_team_background": pl.DataFrame(
                {
                    "team_id": [1610612738],
                    "abbreviation": ["BOS"],
                    "nickname": ["Celtics"],
                    "yearfounded": [1946],
                    "city": ["Boston"],
                    "arena": ["TD Garden"],
                    "arenacapacity": [19156],
                    "owner": ["Wyc Grousbeck"],
                    "generalmanager": ["Brad Stevens"],
                    "headcoach": ["Joe Mazzulla"],
                    "dleagueaffiliation": ["Maine Celtics"],
                }
            ).lazy()
        }

        result = _run(FactTeamBackgroundTransformer(), staging)

        assert result.shape == (1, 11)
        _assert_schema_valid("fact_team_background", result)

    def test_team_hof_schema_validates_transform_output(self) -> None:
        staging = {
            "stg_team_hof": pl.DataFrame(
                {
                    "playerid": [76003],
                    "player": ["Larry Bird"],
                    "position": ["F"],
                    "jersey": ["33"],
                    "seasonswithteam": ["1979-92"],
                    "year": ["1998"],
                }
            ).lazy()
        }

        result = _run(FactTeamHofTransformer(), staging)

        assert result.shape == (1, 6)
        _assert_schema_valid("fact_team_hof", result)

    def test_team_retired_schema_validates_transform_output(self) -> None:
        staging = {
            "stg_team_retired": pl.DataFrame(
                {
                    "playerid": [76003],
                    "player": ["Larry Bird"],
                    "position": ["F"],
                    "jersey": ["33"],
                    "seasonswithteam": ["1979-92"],
                    "year": ["1993"],
                }
            ).lazy()
        }

        result = _run(FactTeamRetiredTransformer(), staging)

        assert result.shape == (1, 6)
        _assert_schema_valid("fact_team_retired", result)

    def test_team_social_sites_schema_validates_transform_output(self) -> None:
        staging = {
            "stg_team_social_sites": pl.DataFrame(
                {
                    "accounttype": ["Official Website"],
                    "website_link": ["https://www.nba.com/celtics"],
                }
            ).lazy()
        }

        result = _run(FactTeamSocialSitesTransformer(), staging)

        assert result.shape == (1, 2)
        _assert_schema_valid("fact_team_social_sites", result)

    def test_team_season_ranks_schema_validates_transform_output(self) -> None:
        staging = {
            "stg_team_season_ranks": pl.DataFrame(
                {
                    "league_id": ["00"],
                    "season_id": ["22024"],
                    "team_id": [1610612738],
                    "pts_rank": [2],
                    "pts_pg": [118.7],
                    "reb_rank": [6],
                    "reb_pg": [44.4],
                    "ast_rank": [3],
                    "ast_pg": [27.1],
                    "opp_pts_rank": [4],
                    "opp_pts_pg": [110.2],
                    "season_type": ["Regular Season"],
                }
            ).lazy()
        }

        result = _run(FactTeamSeasonRanksTransformer(), staging)

        assert result.shape == (1, 12)
        _assert_schema_valid("fact_team_season_ranks", result)


def test_team_reference_schemas_are_discovered_without_init_exports() -> None:
    assert {
        "fact_team_awards_conf",
        "fact_team_awards_div",
        "fact_team_background",
        "fact_team_hof",
        "fact_team_retired",
        "fact_team_season_ranks",
        "fact_team_social_sites",
    }.issubset(_star_schema_map())
