from __future__ import annotations

import polars as pl

from nbadb.schemas.registry import get_input_schema, get_output_schema
from nbadb.schemas.staging.team_heavy_support import (
    StagingOnOffDetailsOffCourtSchema,
    StagingOnOffDetailsOnCourtSchema,
    StagingOnOffDetailsOverallSchema,
    StagingOnOffSchema,
    StagingOnOffSummaryOffCourtSchema,
    StagingOnOffSummaryOnCourtSchema,
    StagingOnOffSummaryOverallSchema,
    StagingTeamAvailableSeasonsSchema,
    StagingTeamAwardsConfSchema,
    StagingTeamAwardsDivSchema,
    StagingTeamBackgroundSchema,
    StagingTeamDashboardEstimatedSchema,
    StagingTeamDashboardOnOffSchema,
    StagingTeamGameLogsV2Schema,
    StagingTeamHistoricalLeadersSchema,
    StagingTeamHistorySchema,
    StagingTeamHofSchema,
    StagingTeamPlayerDashboardSchema,
    StagingTeamPlayerDashOverallSchema,
    StagingTeamPlayerDashPlayersSchema,
    StagingTeamRetiredSchema,
    StagingTeamSeasonRanksSchema,
    StagingTeamSocialSitesSchema,
    StagingTeamYearByYearSchema,
    StagingTeamYearByYearStatsSchema,
)
from nbadb.schemas.star.team_heavy_support import (
    FactOnOffDetailSchema,
    FactTeamAvailableSeasonsSchema,
    FactTeamHistoricalSchema,
    FactTeamHistoryDetailSchema,
)


def test_team_heavy_input_schema_registry_covers_requested_staging_keys() -> None:
    expected = {
        "stg_team_awards_conf": StagingTeamAwardsConfSchema,
        "stg_team_awards_div": StagingTeamAwardsDivSchema,
        "stg_team_background": StagingTeamBackgroundSchema,
        "stg_team_history": StagingTeamHistorySchema,
        "stg_team_hof": StagingTeamHofSchema,
        "stg_team_retired": StagingTeamRetiredSchema,
        "stg_team_social_sites": StagingTeamSocialSitesSchema,
        "stg_team_dashboard_estimated": StagingTeamDashboardEstimatedSchema,
        "stg_team_game_logs_v2": StagingTeamGameLogsV2Schema,
        "stg_team_historical_leaders": StagingTeamHistoricalLeadersSchema,
        "stg_team_available_seasons": StagingTeamAvailableSeasonsSchema,
        "stg_team_season_ranks": StagingTeamSeasonRanksSchema,
        "stg_team_player_dashboard": StagingTeamPlayerDashboardSchema,
        "stg_team_player_dash_players": StagingTeamPlayerDashPlayersSchema,
        "stg_team_player_dash_overall": StagingTeamPlayerDashOverallSchema,
        "stg_team_dashboard_on_off": StagingTeamDashboardOnOffSchema,
        "stg_on_off": StagingOnOffSchema,
        "stg_on_off_details_overall": StagingOnOffDetailsOverallSchema,
        "stg_on_off_details_off_court": StagingOnOffDetailsOffCourtSchema,
        "stg_on_off_details_on_court": StagingOnOffDetailsOnCourtSchema,
        "stg_on_off_summary_overall": StagingOnOffSummaryOverallSchema,
        "stg_on_off_summary_off_court": StagingOnOffSummaryOffCourtSchema,
        "stg_on_off_summary_on_court": StagingOnOffSummaryOnCourtSchema,
        "stg_team_year_by_year": StagingTeamYearByYearSchema,
        "stg_team_year_by_year_stats": StagingTeamYearByYearStatsSchema,
    }

    for table_name, schema_cls in expected.items():
        assert get_input_schema(table_name) is schema_cls, table_name


def test_team_heavy_output_schema_registry_covers_requested_tables() -> None:
    assert get_output_schema("fact_team_available_seasons") is FactTeamAvailableSeasonsSchema
    assert get_output_schema("fact_on_off_detail") is FactOnOffDetailSchema
    assert get_output_schema("fact_team_historical") is FactTeamHistoricalSchema
    assert get_output_schema("fact_team_history_detail") is FactTeamHistoryDetailSchema


def test_team_heavy_schemas_validate_representative_rows() -> None:
    awards = pl.DataFrame({"yearawarded": ["2024"], "oppositeteam": ["Pacers"]})
    background = pl.DataFrame(
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
    )
    history = pl.DataFrame(
        {
            "team_id": [1610612738],
            "city": ["Boston"],
            "nickname": ["Celtics"],
            "yearfounded": [1946],
            "yearactivetill": [2025],
        }
    )
    estimated = pl.DataFrame(
        {
            "team_name": ["Boston Celtics"],
            "team_id": [1610612738],
            "gp": [82],
            "w": [61],
            "l": [21],
            "w_pct": [0.744],
            "min": [48.0],
            "e_off_rating": [121.8],
            "e_def_rating": [110.5],
            "e_net_rating": [11.3],
            "e_pace": [99.1],
            "e_ast_ratio": [18.7],
            "e_oreb_pct": [29.2],
            "e_dreb_pct": [71.4],
            "e_reb_pct": [51.7],
            "e_tm_tov_pct": [12.7],
            "gp_rank": [1],
            "w_rank": [1],
            "l_rank": [30],
            "w_pct_rank": [1],
            "min_rank": [12],
            "e_off_rating_rank": [1],
            "e_def_rating_rank": [3],
            "e_net_rating_rank": [1],
            "e_ast_ratio_rank": [4],
            "e_oreb_pct_rank": [6],
            "e_dreb_pct_rank": [2],
            "e_reb_pct_rank": [2],
            "e_tm_tov_pct_rank": [8],
            "e_pace_rank": [15],
            "season_year": ["2024-25"],
        }
    )
    game_logs = pl.DataFrame(
        {
            "season_year": ["2024-25"],
            "season_id": ["22024"],
            "team_id": [1610612738],
            "team_abbreviation": ["BOS"],
            "team_name": ["Boston Celtics"],
            "game_id": ["0022400001"],
            "game_date": ["2024-10-22"],
            "matchup": ["BOS vs. NYK"],
            "wl": ["W"],
            "min": [240.0],
            "fgm": [42.0],
            "fga": [88.0],
            "fg_pct": [0.477],
            "fg3m": [17.0],
            "fg3a": [39.0],
            "fg3_pct": [0.436],
            "ftm": [19.0],
            "fta": [22.0],
            "ft_pct": [0.864],
            "oreb": [11.0],
            "dreb": [36.0],
            "reb": [47.0],
            "ast": [28.0],
            "tov": [10.0],
            "stl": [7.0],
            "blk": [5.0],
            "blka": [3.0],
            "pf": [16.0],
            "pfd": [18.0],
            "pts": [120.0],
            "plus_minus": [9.0],
            "gp_rank": [1],
            "w_rank": [1],
            "l_rank": [30],
            "w_pct_rank": [1],
            "min_rank": [1],
            "fgm_rank": [3],
            "fga_rank": [8],
            "fg_pct_rank": [7],
            "fg3m_rank": [1],
            "fg3a_rank": [2],
            "fg3_pct_rank": [2],
            "ftm_rank": [11],
            "fta_rank": [14],
            "ft_pct_rank": [4],
            "oreb_rank": [9],
            "dreb_rank": [6],
            "reb_rank": [5],
            "ast_rank": [3],
            "tov_rank": [24],
            "stl_rank": [12],
            "blk_rank": [10],
            "blka_rank": [20],
            "pf_rank": [25],
            "pfd_rank": [13],
            "pts_rank": [2],
            "plus_minus_rank": [1],
        }
    )
    leaders = pl.DataFrame(
        {
            "team_id": [1610612738],
            "pts": [26717.0],
            "pts_person_id": [76003],
            "pts_player": ["Larry Bird"],
            "ast": [5695.0],
            "ast_person_id": [76003],
            "ast_player": ["Larry Bird"],
            "reb": [8974.0],
            "reb_person_id": [76003],
            "reb_player": ["Larry Bird"],
            "blk": [703.0],
            "blk_person_id": [76003],
            "blk_player": ["Larry Bird"],
            "stl": [1556.0],
            "stl_person_id": [76003],
            "stl_player": ["Larry Bird"],
            "season_year": ["1985-86"],
        }
    )
    available_seasons = pl.DataFrame({"season_id": ["22024"]})
    ranks = pl.DataFrame(
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
    )
    player_dashboard = pl.DataFrame(
        {
            "group_set": ["PlayersSeasonTotals"],
            "player_id": [1627759],
            "player_name": ["Jaylen Brown"],
            "gp": [70],
            "w": [49],
            "l": [21],
            "w_pct": [0.7],
            "min": [33.5],
            "fgm": [8.6],
            "fga": [18.2],
            "fg_pct": [0.472],
            "fg3m": [2.4],
            "fg3a": [6.7],
            "fg3_pct": [0.358],
            "ftm": [4.4],
            "fta": [5.8],
            "ft_pct": [0.758],
            "oreb": [1.2],
            "dreb": [4.4],
            "reb": [5.6],
            "ast": [3.7],
            "tov": [2.4],
            "stl": [1.0],
            "blk": [0.4],
            "blka": [1.1],
            "pf": [2.2],
            "pfd": [4.8],
            "pts": [23.0],
            "plus_minus": [5.9],
            "nba_fantasy_pts": [38.7],
            "dd2": [6.0],
            "td3": [1.0],
            "gp_rank": [37],
            "w_rank": [19],
            "l_rank": [402],
            "w_pct_rank": [22],
            "min_rank": [31],
            "fgm_rank": [20],
            "fga_rank": [18],
            "fg_pct_rank": [74],
            "fg3m_rank": [34],
            "fg3a_rank": [55],
            "fg3_pct_rank": [117],
            "ftm_rank": [41],
            "fta_rank": [39],
            "ft_pct_rank": [151],
            "oreb_rank": [128],
            "dreb_rank": [94],
            "reb_rank": [97],
            "ast_rank": [110],
            "tov_rank": [89],
            "stl_rank": [128],
            "blk_rank": [245],
            "blka_rank": [151],
            "pf_rank": [165],
            "pfd_rank": [58],
            "pts_rank": [29],
            "plus_minus_rank": [40],
            "nba_fantasy_pts_rank": [36],
            "dd2_rank": [59],
            "td3_rank": [27],
            "season_type": ["Regular Season"],
        }
    )
    team_overall = pl.DataFrame(
        {
            "group_set": ["Overall"],
            "team_id": [1610612738],
            "team_name": ["Boston Celtics"],
            "group_value": ["2024-25"],
            "gp": [82],
            "w": [61],
            "l": [21],
            "w_pct": [0.744],
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
        }
    )
    on_off_team = pl.DataFrame(
        {
            "team_id": [1610612738],
            "season_year": ["2024-25"],
            "season_type": ["Regular Season"],
            "on_off": ["overall"],
            "gp": [82],
            "min": [48.0],
            "pts": [118.7],
            "reb": [44.4],
            "ast": [27.1],
            "off_rating": [121.8],
            "def_rating": [110.5],
            "net_rating": [11.3],
        }
    )
    on_off_player = pl.DataFrame(
        {
            "player_id": [1628369],
            "team_id": [1610612738],
            "season_year": ["2024-25"],
            "season_type": ["Regular Season"],
            "on_off": ["on"],
            "gp": [65],
            "min": [35.1],
            "pts": [117.2],
            "reb": [43.0],
            "ast": [26.0],
            "off_rating": [120.3],
            "def_rating": [111.4],
            "net_rating": [8.9],
        }
    )
    on_off_detail = pl.DataFrame(
        {
            "group_set": ["OnOffCourt"],
            "group_value": ["Overall"],
            "team_id": [1610612738],
            "team_abbreviation": ["BOS"],
            "team_name": ["Boston Celtics"],
            "gp": [82],
            "w": [61],
            "l": [21],
            "w_pct": [0.744],
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
        }
    )
    on_off_summary = pl.DataFrame(
        {
            "group_set": ["PlayersOnCourt"],
            "team_id": [1610612738],
            "team_abbreviation": ["BOS"],
            "team_name": ["Boston Celtics"],
            "vs_player_id": [1627759],
            "vs_player_name": ["Jaylen Brown"],
            "court_status": ["On"],
            "gp": [70],
            "min": [33.5],
            "plus_minus": [5.9],
            "off_rating": [119.2],
            "def_rating": [111.1],
            "net_rating": [8.1],
        }
    )
    year_by_year = pl.DataFrame(
        {
            "team_id": [1610612738],
            "team_city": ["Boston"],
            "team_name": ["Celtics"],
            "year": ["2024-25"],
            "gp": [82],
            "wins": [61],
            "losses": [21],
            "win_pct": [0.744],
            "conf_rank": [2],
            "div_rank": [1],
            "po_wins": [16],
            "po_losses": [4],
            "conf_count": [24],
            "div_count": [35],
            "nba_finals_appearance": ["CHAMPION"],
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
            "pf": [18.1],
            "stl": [7.9],
            "tov": [12.8],
            "blk": [5.3],
            "pts": [118.7],
            "pts_rank": [2],
        }
    )

    assert StagingTeamAwardsConfSchema.validate(awards).shape == (1, 2)
    assert StagingTeamAwardsDivSchema.validate(awards).shape == (1, 2)
    assert StagingTeamBackgroundSchema.validate(background).shape == (1, 11)
    assert StagingTeamHistorySchema.validate(history).shape == (1, 5)
    assert StagingTeamHofSchema.validate(
        pl.DataFrame(
            {
                "playerid": [76003],
                "player": ["Larry Bird"],
                "position": ["F"],
                "jersey": ["33"],
                "seasonswithteam": ["1979-92"],
                "year": ["1998"],
            }
        )
    ).shape == (1, 6)
    assert StagingTeamRetiredSchema.validate(
        pl.DataFrame(
            {
                "playerid": [76003],
                "player": ["Larry Bird"],
                "position": ["F"],
                "jersey": ["33"],
                "seasonswithteam": ["1979-92"],
                "year": ["1993"],
            }
        )
    ).shape == (1, 6)
    assert StagingTeamSocialSitesSchema.validate(
        pl.DataFrame(
            {
                "accounttype": ["Official Website"],
                "website_link": ["https://www.nba.com/celtics"],
            }
        )
    ).shape == (1, 2)
    assert StagingTeamDashboardEstimatedSchema.validate(estimated).shape == (1, estimated.width)
    assert StagingTeamGameLogsV2Schema.validate(game_logs).shape == (1, game_logs.width)
    assert StagingTeamHistoricalLeadersSchema.validate(leaders).shape == (1, leaders.width)
    assert StagingTeamAvailableSeasonsSchema.validate(available_seasons).shape == (1, 1)
    assert StagingTeamSeasonRanksSchema.validate(ranks).shape == (1, ranks.width)
    assert StagingTeamPlayerDashboardSchema.validate(player_dashboard).shape == (
        1,
        player_dashboard.width,
    )
    assert StagingTeamPlayerDashPlayersSchema.validate(player_dashboard).shape == (
        1,
        player_dashboard.width,
    )
    assert StagingTeamPlayerDashOverallSchema.validate(team_overall).shape == (
        1,
        team_overall.width,
    )
    assert StagingTeamDashboardOnOffSchema.validate(on_off_team).shape == (1, on_off_team.width)
    assert StagingOnOffSchema.validate(on_off_player).shape == (1, on_off_player.width)
    assert StagingOnOffDetailsOverallSchema.validate(on_off_detail).shape == (
        1,
        on_off_detail.width,
    )
    assert StagingOnOffDetailsOffCourtSchema.validate(on_off_detail).shape == (
        1,
        on_off_detail.width,
    )
    assert StagingOnOffDetailsOnCourtSchema.validate(on_off_detail).shape == (
        1,
        on_off_detail.width,
    )
    assert StagingOnOffSummaryOverallSchema.validate(on_off_detail).shape == (
        1,
        on_off_detail.width,
    )
    assert StagingOnOffSummaryOffCourtSchema.validate(on_off_summary).shape == (
        1,
        on_off_summary.width,
    )
    assert StagingOnOffSummaryOnCourtSchema.validate(on_off_summary).shape == (
        1,
        on_off_summary.width,
    )
    assert StagingTeamYearByYearSchema.validate(year_by_year).shape == (1, year_by_year.width)
    assert StagingTeamYearByYearStatsSchema.validate(year_by_year).shape == (
        1,
        year_by_year.width,
    )
    assert FactTeamAvailableSeasonsSchema.validate(available_seasons).shape == (1, 1)
    assert FactOnOffDetailSchema.validate(
        pl.DataFrame(
            {
                "court_status": ["summary_on_court"],
                "group_set": ["PlayersOnCourt"],
                "team_id": [1610612738],
                "team_abbreviation": ["BOS"],
                "team_name": ["Boston Celtics"],
                "vs_player_id": [1627759],
                "vs_player_name": ["Jaylen Brown"],
                "gp": [70],
                "min": [33.5],
                "plus_minus": [5.9],
                "off_rating": [119.2],
                "def_rating": [111.1],
                "net_rating": [8.1],
            }
        )
    ).shape == (1, 13)
    assert FactTeamHistoricalSchema.validate(
        pl.DataFrame({"history_type": ["leaders"], "team_id": [1610612738]})
    ).shape == (1, 2)
    assert FactTeamHistoryDetailSchema.validate(history).shape == (1, 5)
