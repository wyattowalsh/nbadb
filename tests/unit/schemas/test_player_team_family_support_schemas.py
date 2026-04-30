from __future__ import annotations

import pandera.errors as pa_errors
import polars as pl
import pytest

from nbadb.schemas.registry import get_input_schema, get_output_schema
from nbadb.schemas.staging.player_team_family_support import (
    StagingFantasyWidgetSchema,
    StagingFranchiseLeadersSchema,
    StagingLineupSchema,
    StagingPlayerAvailableSeasonsSchema,
    StagingPlayerHeadlineStatsSchema,
    StagingTeamDashGeneralSplitsSchema,
    StagingTeamShootAssistedBySchema,
)
from nbadb.schemas.star.player_team_family_support import (
    FactFantasySchema,
    FactFranchiseDetailSchema,
    FactFranchiseLeadersSchema,
    FactFranchisePlayersSchema,
    FactHustleAvailabilitySchema,
    FactPlayerClutchDetailSchema,
    FactPlayerGameSplitsDetailSchema,
    FactPlayerGeneralSplitsDetailSchema,
    FactPlayerHeadlineStatsSchema,
    FactPlayerTeamPerfDetailSchema,
    FactPlayerYoyDetailSchema,
    FactTeamGeneralSplitsDetailSchema,
    FactTeamShootingSplitsDetailSchema,
)


def test_player_reference_input_schemas_validate_core_rows() -> None:
    available = pl.DataFrame({"season_id": ["22024"]})
    headline = pl.DataFrame(
        {
            "player_id": [2544],
            "player_name": ["LeBron James"],
            "time_frame": ["2024-25"],
            "pts": [27.1],
            "ast": [8.2],
            "reb": [7.5],
            "pie": [0.21],
        }
    )

    assert StagingPlayerAvailableSeasonsSchema.validate(available).shape == (1, 1)
    assert StagingPlayerHeadlineStatsSchema.validate(headline).shape == (1, 7)


def test_fantasy_and_franchise_staging_schemas_validate_rows() -> None:
    fantasy = pl.DataFrame(
        {
            "player_id": [2544],
            "player_name": ["LeBron James"],
            "player_position": ["SF"],
            "team_id": [1610612747],
            "team_abbreviation": ["LAL"],
            "gp": [55],
            "min": [34.8],
            "fan_duel_pts": [46.2],
            "nba_fantasy_pts": [48.0],
            "pts": [27.1],
            "reb": [7.5],
            "ast": [8.2],
            "blk": [0.8],
            "stl": [1.3],
            "tov": [3.4],
            "fg3m": [2.1],
            "fga": [19.2],
            "fg_pct": [0.538],
            "fta": [6.4],
            "ft_pct": [0.741],
            "season_type": ["Regular Season"],
        }
    )
    leaders = pl.DataFrame(
        {
            "team_id": [1610612738],
            "pts": [26395.0],
            "pts_person_id": [78049],
            "pts_player": ["John Havlicek"],
            "ast": [6795.0],
            "ast_person_id": [78049],
            "ast_player": ["John Havlicek"],
            "reb": [8200.0],
            "reb_person_id": [78049],
            "reb_player": ["John Havlicek"],
            "blk": [1333.0],
            "blk_person_id": [77142],
            "blk_player": ["Robert Parish"],
            "stl": [1727.0],
            "stl_person_id": [201142],
            "stl_player": ["Paul Pierce"],
        }
    )

    assert StagingFantasyWidgetSchema.validate(fantasy).shape[0] == 1
    assert StagingFranchiseLeadersSchema.validate(leaders).shape[0] == 1


def test_fact_franchise_passthrough_schemas_validate_rows() -> None:
    leaders = pl.DataFrame(
        {
            "team_id": [1610612738],
            "pts": [26395.0],
            "pts_person_id": [78049],
            "pts_player": ["John Havlicek"],
        }
    )
    players = pl.DataFrame(
        {
            "team_id": [1610612738],
            "person_id": [2544],
            "player": ["LeBron James"],
            "season_type": ["Regular Season"],
        }
    )

    assert FactFranchiseLeadersSchema.validate(leaders).shape == (1, 4)
    assert FactFranchisePlayersSchema.validate(players).shape == (1, 4)


def test_lineup_and_team_dashboard_staging_schemas_validate_rows() -> None:
    lineup = pl.DataFrame(
        {
            "group_set": ["Lineups"],
            "group_id": ["1627759-1628369-1628400-1629057-203954"],
            "group_name": ["Starter Group"],
            "team_id": [1610612738],
            "team_abbreviation": ["BOS"],
            "gp": [34],
            "w": [22],
            "l": [12],
            "w_pct": [0.647],
            "min": [315.4],
            "fgm": [128],
            "fga": [250],
            "fg_pct": [0.512],
            "fg3m": [51],
            "fg3a": [130],
            "fg3_pct": [0.392],
            "ftm": [44],
            "fta": [56],
            "ft_pct": [0.786],
            "oreb": [31],
            "dreb": [92],
            "reb": [123],
            "ast": [78],
            "tov": [29],
            "stl": [18],
            "blk": [11],
            "blka": [9],
            "pf": [52],
            "pfd": [47],
            "pts": [351],
            "plus_minus": [42.0],
            "gp_rank": [7],
            "w_rank": [5],
            "l_rank": [18],
            "w_pct_rank": [6],
            "min_rank": [4],
            "fgm_rank": [3],
            "fga_rank": [5],
            "fg_pct_rank": [2],
            "fg3m_rank": [2],
            "fg3a_rank": [4],
            "fg3_pct_rank": [3],
            "ftm_rank": [8],
            "fta_rank": [10],
            "ft_pct_rank": [12],
            "oreb_rank": [16],
            "dreb_rank": [5],
            "reb_rank": [7],
            "ast_rank": [4],
            "tov_rank": [20],
            "stl_rank": [14],
            "blk_rank": [12],
            "blka_rank": [11],
            "pf_rank": [19],
            "pfd_rank": [13],
            "pts_rank": [3],
            "plus_minus_rank": [2],
            "season_year": ["2024-25"],
        }
    )
    general = pl.DataFrame(
        {
            "season_type": ["Regular Season"],
            "group_set": ["Overall"],
            "group_value": ["2024-25"],
            "season_year": ["2024-25"],
            "gp": [82],
            "w": [57],
            "l": [25],
            "w_pct": [0.695],
            "min": [48.0],
            "fgm": [43.1],
            "fga": [88.9],
            "fg_pct": [0.485],
            "fg3m": [14.3],
            "fg3a": [38.2],
            "fg3_pct": [0.374],
            "ftm": [18.2],
            "fta": [23.4],
            "ft_pct": [0.778],
            "oreb": [10.8],
            "dreb": [33.6],
            "reb": [44.4],
            "ast": [27.1],
            "tov": [12.8],
            "stl": [7.9],
            "blk": [5.3],
            "blka": [4.1],
            "pf": [18.1],
            "pfd": [19.7],
            "pts": [118.7],
            "plus_minus": [7.8],
            "gp_rank": [3],
            "w_rank": [2],
            "l_rank": [29],
            "w_pct_rank": [2],
            "min_rank": [11],
            "fgm_rank": [5],
            "fga_rank": [8],
            "fg_pct_rank": [4],
            "fg3m_rank": [1],
            "fg3a_rank": [1],
            "fg3_pct_rank": [6],
            "ftm_rank": [9],
            "fta_rank": [12],
            "ft_pct_rank": [7],
            "oreb_rank": [10],
            "dreb_rank": [4],
            "reb_rank": [6],
            "ast_rank": [3],
            "tov_rank": [12],
            "stl_rank": [9],
            "blk_rank": [11],
            "blka_rank": [8],
            "pf_rank": [17],
            "pfd_rank": [13],
            "pts_rank": [2],
            "plus_minus_rank": [1],
            "cfid": [7],
            "cfparams": ["TEAM_ID=1610612738&SEASON=2024-25"],
        }
    )
    assisted_by = pl.DataFrame(
        {
            "season_type": ["Regular Season"],
            "group_set": ["AssistedBy"],
            "player_id": [1628369],
            "player_name": ["Jayson Tatum"],
            "fgm": [10.4],
            "fga": [20.1],
            "fg_pct": [0.517],
            "fg3m": [3.1],
            "fg3a": [8.2],
            "fg3_pct": [0.378],
            "efg_pct": [0.594],
            "blka": [0.7],
            "pct_ast_2pm": [0.62],
            "pct_uast_2pm": [0.38],
            "pct_ast_3pm": [0.89],
            "pct_uast_3pm": [0.11],
            "pct_ast_fgm": [0.73],
            "pct_uast_fgm": [0.27],
            "fgm_rank": [5],
            "fga_rank": [6],
            "fg_pct_rank": [7],
            "fg3m_rank": [3],
            "fg3a_rank": [4],
            "fg3_pct_rank": [12],
            "efg_pct_rank": [5],
            "blka_rank": [20],
            "pct_ast_2pm_rank": [6],
            "pct_uast_2pm_rank": [25],
            "pct_ast_3pm_rank": [2],
            "pct_uast_3pm_rank": [27],
            "pct_ast_fgm_rank": [4],
            "pct_uast_fgm_rank": [29],
            "cfid": [7],
            "cfparams": ["TEAM_ID=1610612738&SEASON=2024-25"],
        }
    )

    assert StagingLineupSchema.validate(lineup).shape[0] == 1
    assert StagingTeamDashGeneralSplitsSchema.validate(general).shape[0] == 1
    assert StagingTeamShootAssistedBySchema.validate(assisted_by).shape[0] == 1


def test_support_family_output_schemas_validate_union_rows() -> None:
    fantasy = pl.DataFrame(
        {
            "player_id": [2544],
            "player_name": ["LeBron James"],
            "team_id": [1610612747],
            "team_name": ["Lakers"],
            "team_abbreviation": ["LAL"],
            "jersey_num": ["23"],
            "player_position": ["SF"],
            "location": ["Home"],
            "gp": [55],
            "min": [34.8],
            "fan_duel_pts": [46.2],
            "nba_fantasy_pts": [48.0],
            "usg_pct": [0.312],
            "fgm": [9.8],
            "fga": [19.2],
            "fg_pct": [0.538],
            "fg3m": [2.1],
            "fg3a": [6.0],
            "fg3_pct": [0.350],
            "ftm": [5.4],
            "fta": [6.4],
            "ft_pct": [0.741],
            "oreb": [1.1],
            "dreb": [6.4],
            "reb": [7.5],
            "ast": [8.2],
            "tov": [3.4],
            "stl": [1.3],
            "blk": [0.8],
            "blka": [0.5],
            "pf": [1.7],
            "pfd": [5.8],
            "pts": [27.1],
            "plus_minus": [6.2],
            "season_type": ["Regular Season"],
            "fantasy_source": ["infographic_fanduel_player"],
        }
    )
    franchise = pl.DataFrame(
        {
            "team_id": [1610612738],
            "league_id": [None],
            "team": [None],
            "person_id": [None],
            "player": [None],
            "season_type": [None],
            "active_with_team": [None],
            "gp": [None],
            "fgm": [None],
            "fga": [None],
            "fg_pct": [None],
            "fg3m": [None],
            "fg3a": [None],
            "fg3_pct": [None],
            "ftm": [None],
            "fta": [None],
            "ft_pct": [None],
            "oreb": [None],
            "dreb": [None],
            "reb": [8200.0],
            "ast": [6795.0],
            "pf": [None],
            "stl": [1727.0],
            "tov": [None],
            "blk": [1333.0],
            "pts": [26395.0],
            "pts_person_id": [78049],
            "pts_player": ["John Havlicek"],
            "ast_person_id": [78049],
            "ast_player": ["John Havlicek"],
            "reb_person_id": [78049],
            "reb_player": ["John Havlicek"],
            "blk_person_id": [77142],
            "blk_player": ["Robert Parish"],
            "stl_person_id": [201142],
            "stl_player": ["Paul Pierce"],
            "detail_type": ["leaders"],
        }
    )
    hustle = pl.DataFrame(
        {
            "game_id": ["0022400001"],
            "hustle_status": ["Available"],
            "team_id": [None],
            "team_abbreviation": [None],
            "team_city": [None],
            "player_id": [None],
            "player_name": [None],
            "start_position": [None],
            "comment": [None],
            "minutes": [None],
            "pts": [None],
            "contested_shots": [None],
            "contested_shots_2pt": [None],
            "contested_shots_3pt": [None],
            "deflections": [None],
            "charges_drawn": [None],
            "screen_assists": [None],
            "screen_ast_pts": [None],
            "off_loose_balls_recovered": [None],
            "def_loose_balls_recovered": [None],
            "loose_balls_recovered": [None],
            "off_boxouts": [None],
            "def_boxouts": [None],
            "box_out_player_team_rebs": [None],
            "box_out_player_rebs": [None],
            "box_outs": [None],
            "hustle_type": ["availability"],
        }
    )
    clutch = pl.DataFrame(
        {
            "player_id": [2544],
            "season_year": ["2024-25"],
            "season_type": ["Regular Season"],
            "group_set": ["Overall"],
            "group_value": ["Overall"],
            "gp": [12],
            "w": [8],
            "l": [4],
            "w_pct": [0.667],
            "min": [35.2],
            "fgm": [10.0],
            "fga": [19.0],
            "fg_pct": [0.526],
            "fg3m": [2.5],
            "fg3a": [6.0],
            "fg3_pct": [0.417],
            "ftm": [5.0],
            "fta": [6.0],
            "ft_pct": [0.833],
            "oreb": [1.2],
            "dreb": [7.1],
            "reb": [8.3],
            "ast": [7.4],
            "tov": [3.1],
            "stl": [1.4],
            "blk": [0.8],
            "blka": [0.5],
            "pf": [1.9],
            "pfd": [5.3],
            "pts": [27.5],
            "plus_minus": [5.4],
            "gp_rank": [1],
            "w_rank": [2],
            "l_rank": [3],
            "w_pct_rank": [4],
            "min_rank": [5],
            "fgm_rank": [6],
            "fga_rank": [7],
            "fg_pct_rank": [8],
            "fg3m_rank": [9],
            "fg3a_rank": [10],
            "fg3_pct_rank": [11],
            "ftm_rank": [12],
            "fta_rank": [13],
            "ft_pct_rank": [14],
            "oreb_rank": [15],
            "dreb_rank": [16],
            "reb_rank": [17],
            "ast_rank": [18],
            "tov_rank": [19],
            "stl_rank": [20],
            "blk_rank": [21],
            "blka_rank": [22],
            "pf_rank": [23],
            "pfd_rank": [24],
            "pts_rank": [25],
            "plus_minus_rank": [26],
            "nba_fantasy_pts": [49.8],
            "dd2": [3.0],
            "td3": [1.0],
            "cfid": [7],
            "cfparams": ["PLAYER_ID=2544&SEASON=2024-25"],
            "clutch_window": ["overall"],
        }
    )
    team_detail = pl.DataFrame(
        {
            "season_type": ["Regular Season"],
            "group_set": ["DaysRest"],
            "group_value": ["0 Days"],
            "season_year": [None],
            "team_days_rest_range": ["0 Days"],
            "team_game_location": [None],
            "season_month_name": [None],
            "season_segment": [None],
            "game_result": [None],
            "gp": [12],
            "w": [8],
            "l": [4],
            "w_pct": [0.667],
            "min": [48.0],
            "fgm": [39.0],
            "fga": [84.0],
            "fg_pct": [0.464],
            "fg3m": [13.0],
            "fg3a": [36.0],
            "fg3_pct": [0.361],
            "ftm": [17.0],
            "fta": [22.0],
            "ft_pct": [0.773],
            "oreb": [10.0],
            "dreb": [34.0],
            "reb": [44.0],
            "ast": [26.0],
            "tov": [13.0],
            "stl": [7.0],
            "blk": [5.0],
            "blka": [4.0],
            "pf": [18.0],
            "pfd": [19.0],
            "pts": [108.0],
            "plus_minus": [6.0],
            "gp_rank": [5],
            "w_rank": [4],
            "l_rank": [12],
            "w_pct_rank": [6],
            "min_rank": [9],
            "fgm_rank": [8],
            "fga_rank": [7],
            "fg_pct_rank": [11],
            "fg3m_rank": [3],
            "fg3a_rank": [4],
            "fg3_pct_rank": [10],
            "ftm_rank": [12],
            "fta_rank": [13],
            "ft_pct_rank": [9],
            "oreb_rank": [7],
            "dreb_rank": [8],
            "reb_rank": [6],
            "ast_rank": [5],
            "tov_rank": [19],
            "stl_rank": [14],
            "blk_rank": [16],
            "blka_rank": [15],
            "pf_rank": [18],
            "pfd_rank": [20],
            "pts_rank": [9],
            "plus_minus_rank": [4],
            "cfid": [7],
            "cfparams": ["TEAM_ID=1610612738&SEASON=2024-25"],
            "split_type": ["days_rest"],
        }
    )
    shooting_detail = pl.DataFrame(
        {
            "season_type": ["Regular Season"],
            "group_set": ["AssistedBy"],
            "group_value": [None],
            "player_id": [1628369],
            "player_name": ["Jayson Tatum"],
            "fgm": [10.4],
            "fga": [20.1],
            "fg_pct": [0.517],
            "fg3m": [3.1],
            "fg3a": [8.2],
            "fg3_pct": [0.378],
            "efg_pct": [0.594],
            "blka": [0.7],
            "pct_ast_2pm": [0.62],
            "pct_uast_2pm": [0.38],
            "pct_ast_3pm": [0.89],
            "pct_uast_3pm": [0.11],
            "pct_ast_fgm": [0.73],
            "pct_uast_fgm": [0.27],
            "fgm_rank": [5],
            "fga_rank": [6],
            "fg_pct_rank": [7],
            "fg3m_rank": [3],
            "fg3a_rank": [4],
            "fg3_pct_rank": [12],
            "efg_pct_rank": [5],
            "blka_rank": [20],
            "pct_ast_2pm_rank": [6],
            "pct_uast_2pm_rank": [25],
            "pct_ast_3pm_rank": [2],
            "pct_uast_3pm_rank": [27],
            "pct_ast_fgm_rank": [4],
            "pct_uast_fgm_rank": [29],
            "cfid": [7],
            "cfparams": ["TEAM_ID=1610612738&SEASON=2024-25"],
            "shooting_split": ["assisted_by"],
        }
    )

    assert FactFantasySchema.validate(fantasy).shape[0] == 1
    assert FactFranchiseDetailSchema.validate(franchise).shape[0] == 1
    assert FactHustleAvailabilitySchema.validate(hustle).shape[0] == 1
    assert (
        FactPlayerHeadlineStatsSchema.validate(
            pl.DataFrame(
                {
                    "player_id": [2544],
                    "player_name": ["LeBron James"],
                    "time_frame": ["2024-25"],
                    "pts": [27.1],
                    "ast": [8.2],
                    "reb": [7.5],
                    "pie": [0.21],
                }
            )
        ).shape[0]
        == 1
    )
    assert FactPlayerClutchDetailSchema.validate(clutch).shape[0] == 1
    assert (
        FactPlayerGameSplitsDetailSchema.validate(
            clutch.drop("clutch_window").with_columns(pl.lit("game_overall").alias("split_type"))
        ).shape[0]
        == 1
    )
    assert (
        FactPlayerGeneralSplitsDetailSchema.validate(
            clutch.drop("clutch_window").with_columns(pl.lit("month").alias("split_type"))
        ).shape[0]
        == 1
    )
    assert (
        FactPlayerTeamPerfDetailSchema.validate(
            clutch.drop("clutch_window").with_columns(
                pl.lit(1).alias("group_value_order"),
                pl.lit("Home").alias("group_value_2"),
                pl.lit("overall").alias("perf_context"),
            )
        ).shape[0]
        == 1
    )
    assert (
        FactPlayerYoyDetailSchema.validate(
            clutch.drop("clutch_window").with_columns(
                pl.lit(1610612747).alias("team_id"),
                pl.lit("LAL").alias("team_abbreviation"),
                pl.lit("2025-04-10").alias("max_game_date"),
                pl.lit("overall").alias("yoy_type"),
            )
        ).shape[0]
        == 1
    )
    assert FactTeamGeneralSplitsDetailSchema.validate(team_detail).shape[0] == 1
    assert FactTeamShootingSplitsDetailSchema.validate(shooting_detail).shape[0] == 1


def test_support_family_registry_entries_are_discoverable() -> None:
    input_expectations = {
        "stg_player_available_seasons": StagingPlayerAvailableSeasonsSchema,
        "stg_player_headline_stats": StagingPlayerHeadlineStatsSchema,
        "stg_fantasy_widget": StagingFantasyWidgetSchema,
        "stg_franchise_leaders": StagingFranchiseLeadersSchema,
        "stg_lineup": StagingLineupSchema,
        "stg_team_dash_general_splits": StagingTeamDashGeneralSplitsSchema,
        "stg_team_shoot_assisted_by": StagingTeamShootAssistedBySchema,
    }
    output_expectations = {
        "fact_fantasy": FactFantasySchema,
        "fact_franchise_detail": FactFranchiseDetailSchema,
        "fact_hustle_availability": FactHustleAvailabilitySchema,
        "fact_player_clutch_detail": FactPlayerClutchDetailSchema,
        "fact_player_game_splits_detail": FactPlayerGameSplitsDetailSchema,
        "fact_player_general_splits_detail": FactPlayerGeneralSplitsDetailSchema,
        "fact_player_headline_stats": FactPlayerHeadlineStatsSchema,
        "fact_player_team_perf_detail": FactPlayerTeamPerfDetailSchema,
        "fact_player_yoy_detail": FactPlayerYoyDetailSchema,
        "fact_team_general_splits_detail": FactTeamGeneralSplitsDetailSchema,
        "fact_team_shooting_splits_detail": FactTeamShootingSplitsDetailSchema,
    }

    for table_name, schema_cls in input_expectations.items():
        assert get_input_schema(table_name) is schema_cls
    for table_name, schema_cls in output_expectations.items():
        assert get_output_schema(table_name) is schema_cls


def test_staging_lineup_requires_positive_team_id() -> None:
    with pytest.raises(pa_errors.SchemaError):
        StagingLineupSchema.validate(
            pl.DataFrame(
                {
                    "group_set": ["Lineups"],
                    "group_id": ["1-2-3-4-5"],
                    "group_name": ["Bad"],
                    "team_id": [-1],
                    "season_year": ["2024-25"],
                }
            )
        )
