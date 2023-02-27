"""data table definitions
"""
# -- Imports --------------------------------------------------------------------------
import pandas as pd
import pandera as pa
from pandera import SchemaModel
from pandera.typing import (
    Bool,
    DataFrame,
    DateTime,
    Float,
    Index,
    Int,
    Object,
    Series,
    String,
)


# -- Data -----------------------------------------------------------------------------
class PlayerSchema(SchemaModel):
    id: Series[String] = pa.Field(nullable=False, coerce=True)
    full_name: Series[String] = pa.Field()
    first_name: Series[String] = pa.Field()
    last_name: Series[String] = pa.Field()
    is_active: Series[Bool] = pa.Field(coerce=True)


class TeamSchema(SchemaModel):
    id: Series[String] = pa.Field(nullable=False, coerce=True)
    full_name: Series[String] = pa.Field(nullable=False)
    abbreviation: Series[String] = pa.Field()
    nickname: Series[String] = pa.Field()
    city: Series[String] = pa.Field()
    state: Series[String] = pa.Field()
    year_founded: Series[Float] = pa.Field(coerce=True)


class LeagueGameLogSchema(SchemaModel):
    season_id: Series[String] = pa.Field(nullable=False)
    team_id_home: Series[String] = pa.Field(nullable=False)
    team_abbreviation_home: Series[String] = pa.Field()
    team_name_home: Series[String] = pa.Field()
    game_id: Series[String] = pa.Field(nullable=False)
    game_date: Series[DateTime] = pa.Field(nullable=False)
    matchup_home: Series[String] = pa.Field()
    wl_home: Series[String] = pa.Field(nullable=True)
    min: Series[Int] = pa.Field()
    fgm_home: Series[Float] = pa.Field(nullable=True)
    fga_home: Series[Float] = pa.Field(nullable=True)
    fg_pct_home: Series[Float] = pa.Field(nullable=True)
    fg3m_home: Series[Float] = pa.Field(nullable=True)
    fg3a_home: Series[Float] = pa.Field(nullable=True)
    fg3_pct_home: Series[Float] = pa.Field(nullable=True)
    ftm_home: Series[Float] = pa.Field(nullable=True)
    fta_home: Series[Float] = pa.Field(nullable=True)
    ft_pct_home: Series[Float] = pa.Field(nullable=True)
    oreb_home: Series[Float] = pa.Field(nullable=True)
    dreb_home: Series[Float] = pa.Field(nullable=True)
    reb_home: Series[Float] = pa.Field(nullable=True)
    ast_home: Series[Float] = pa.Field(nullable=True)
    stl_home: Series[Float] = pa.Field(nullable=True)
    blk_home: Series[Float] = pa.Field(nullable=True)
    tov_home: Series[Float] = pa.Field(nullable=True)
    pf_home: Series[Float] = pa.Field(nullable=True)
    pts_home: Series[Int] = pa.Field()
    plus_minus_home: Series[Int] = pa.Field()
    video_available_home: Series[Bool] = pa.Field()
    team_id_away: Series[String] = pa.Field(nullable=False)
    team_abbreviation_away: Series[String] = pa.Field()
    team_name_away: Series[String] = pa.Field()
    matchup_away: Series[String] = pa.Field()
    wl_away: Series[String] = pa.Field(nullable=True)
    fgm_away: Series[Float] = pa.Field(nullable=True)
    fga_away: Series[Float] = pa.Field(nullable=True)
    fg_pct_away: Series[Float] = pa.Field(nullable=True)
    fg3m_away: Series[Float] = pa.Field(nullable=True)
    fg3a_away: Series[Float] = pa.Field(nullable=True)
    fg3_pct_away: Series[Float] = pa.Field(nullable=True)
    ftm_away: Series[Float] = pa.Field(nullable=True)
    fta_away: Series[Float] = pa.Field(nullable=True)
    ft_pct_away: Series[Float] = pa.Field(nullable=True)
    oreb_away: Series[Float] = pa.Field(nullable=True)
    dreb_away: Series[Float] = pa.Field(nullable=True)
    reb_away: Series[Float] = pa.Field(nullable=True)
    ast_away: Series[Float] = pa.Field(nullable=True)
    stl_away: Series[Float] = pa.Field(nullable=True)
    blk_away: Series[Float] = pa.Field(nullable=True)
    tov_away: Series[Float] = pa.Field(nullable=True)
    pf_away: Series[Float] = pa.Field(nullable=True)
    pts_away: Series[Int] = pa.Field()
    plus_minus_away: Series[Int] = pa.Field()
    video_available_away: Series[Bool] = pa.Field()
 
    class Config:
        coerce = True

class CommonPlayerInfoSchema(SchemaModel):
    person_id: Series[String] = pa.Field(nullable=False)
    first_name: Series[String] = pa.Field()
    last_name: Series[String] = pa.Field()
    display_first_last: Series[String] = pa.Field()
    display_last_comma_first: Series[String] = pa.Field()
    display_fi_last: Series[String] = pa.Field()
    player_slug: Series[String] = pa.Field()
    birthdate: Series[DateTime] = pa.Field()
    school: Series[String] = pa.Field(nullable=True)
    country: Series[String] = pa.Field(nullable=True)
    last_affiliation: Series[String] = pa.Field()
    height: Series[String] = pa.Field()
    weight: Series[String] = pa.Field(nullable=True)
    season_exp: Series[Float] = pa.Field()
    jersey: Series[String] = pa.Field(nullable=True)
    position: Series[String] = pa.Field()
    rosterstatus: Series[String] = pa.Field()
    games_played_current_season_flag: Series[String] = pa.Field()
    team_id: Series[Int] = pa.Field()
    team_name: Series[String] = pa.Field()
    team_abbreviation: Series[String] = pa.Field()
    team_code: Series[String] = pa.Field()
    team_city: Series[String] = pa.Field()
    playercode: Series[String] = pa.Field(nullable=True)
    from_year: Series[Float] = pa.Field(nullable=True)
    to_year: Series[Float] = pa.Field(nullable=True)
    dleague_flag: Series[String] = pa.Field()
    nba_flag: Series[String] = pa.Field()
    games_played_flag: Series[String] = pa.Field()
    draft_year: Series[String] = pa.Field(nullable=True)
    draft_round: Series[String] = pa.Field(nullable=True)
    draft_number: Series[String] = pa.Field(nullable=True)
    greatest_75_flag: Series[String] = pa.Field()

    class Config:
        coerce = True


class TeamDetailsSchema(SchemaModel):
    team_id: Series[String] = pa.Field()
    abbreviation: Series[String] = pa.Field(nullable=True)
    nickname: Series[String] = pa.Field(nullable=True)
    yearfounded: Series[Float] = pa.Field(nullable=True)
    city: Series[String] = pa.Field(nullable=True)
    arena: Series[String] = pa.Field()
    arenacapacity: Series[Float] = pa.Field(nullable=True)
    owner: Series[String] = pa.Field()
    generalmanager: Series[String] = pa.Field()
    headcoach: Series[String] = pa.Field()
    dleagueaffiliation: Series[String] = pa.Field()
    facebook: Series[String] = pa.Field(nullable=True)
    instagram: Series[String] = pa.Field(nullable=True)
    twitter: Series[String] = pa.Field(nullable=True)

    class Config:
        coerce = True


class TeamHistorySchema(SchemaModel):
    team_id: Series[String] = pa.Field()
    city: Series[String] = pa.Field()
    nickname: Series[String] = pa.Field()
    year_founded: Series[Int] = pa.Field()
    year_active_till: Series[Int] = pa.Field()

    class Config:
        coerce = True


class GameSummarySchema(SchemaModel):
    game_date_est: Series[DateTime] = pa.Field()
    game_sequence: Series[Object] = pa.Field(nullable=True)
    game_id: Series[String] = pa.Field()
    game_status_id: Series[Int] = pa.Field()
    game_status_text: Series[String] = pa.Field(nullable=True)
    gamecode: Series[String] = pa.Field()
    home_team_id: Series[String] = pa.Field()
    visitor_team_id: Series[String] = pa.Field()
    season: Series[String] = pa.Field()
    live_period: Series[Int] = pa.Field()
    live_pc_time: Series[String] = pa.Field(nullable=True)
    natl_tv_broadcaster_abbreviation: Series[String] = pa.Field(nullable=True)
    live_period_time_bcast: Series[String] = pa.Field()
    wh_status: Series[Int] = pa.Field()

    class Config:
        coerce = True


class OtherStatsSchema(SchemaModel):
    league_id: Series[String] = pa.Field()
    team_id_home: Series[String] = pa.Field()
    team_abbreviation_home: Series[String] = pa.Field()
    team_city_home: Series[String] = pa.Field()
    pts_paint_home: Series[Int] = pa.Field()
    pts_2nd_chance_home: Series[Int] = pa.Field()
    pts_fb_home: Series[Int] = pa.Field()
    largest_lead_home: Series[Int] = pa.Field()
    lead_changes: Series[Int] = pa.Field()
    times_tied: Series[Int] = pa.Field()
    team_turnovers_home: Series[Object] = pa.Field(nullable=True)
    total_turnovers_home: Series[Object] = pa.Field(nullable=True)
    team_rebounds_home: Series[Object] = pa.Field(nullable=True)
    pts_off_to_home: Series[Object] = pa.Field(nullable=True)
    team_id_away: Series[String] = pa.Field()
    team_abbreviation_away: Series[String] = pa.Field()
    team_city_away: Series[String] = pa.Field()
    pts_paint_away: Series[Int] = pa.Field()
    pts_2nd_chance_away: Series[Int] = pa.Field()
    pts_fb_away: Series[Int] = pa.Field()	
    largest_lead_away: Series[Int] = pa.Field()
    team_turnovers_away: Series[Object] = pa.Field(nullable=True)
    total_turnovers_away: Series[Object] = pa.Field(nullable=True)
    team_rebounds_away: Series[Object] = pa.Field(nullable=True)
    pts_off_to_away: Series[Object] = pa.Field(nullable=True)

    class Config:
        coerce = True


class OfficialsSchema(SchemaModel):
    game_id: Series[String] = pa.Field()
    official_id: Series[String] = pa.Field()
    first_name: Series[String] = pa.Field()
    last_name: Series[String] = pa.Field()
    jersey_num: Series[String] = pa.Field()

    class Config:
        coerce = True


class InactivePlayersSchema(SchemaModel):
    game_id: Series[String] = pa.Field()
    player_id: Series[String] = pa.Field()
    first_name: Series[String] = pa.Field()
    last_name: Series[String] = pa.Field()
    jersey_num: Series[String] = pa.Field()
    team_id: Series[String] = pa.Field()
    team_city: Series[String] = pa.Field()
    team_name: Series[String] = pa.Field()
    team_abbreviation: Series[String] = pa.Field()

    class Config:
        coerce = True


class GameInfoSchema(SchemaModel):
    game_id: Series[String] = pa.Field()
    game_date: Series[DateTime] = pa.Field()
    attendance: Series[Object] = pa.Field(nullable=True)
    game_time: Series[String] = pa.Field()

    class Config:
        coerce = True


class LineScoreSchema(SchemaModel):
    game_date_est: Series[DateTime] = pa.Field()
    game_sequence: Series[Object] = pa.Field(nullable=True)
    game_id: Series[String] = pa.Field()
    team_id_home: Series[String] = pa.Field()
    team_abbreviation_home: Series[String] = pa.Field()
    team_city_name_home: Series[String] = pa.Field()
    team_nickname_home: Series[String] = pa.Field()
    team_wins_losses_home: Series[String] = pa.Field()
    pts_qtr1_home: Series[Object] = pa.Field(nullable=True)
    pts_qtr2_home: Series[Object] = pa.Field(nullable=True)
    pts_qtr3_home: Series[Object] = pa.Field(nullable=True)
    pts_qtr4_home: Series[Object] = pa.Field(nullable=True)
    pts_ot1_home: Series[Object] = pa.Field(nullable=True)
    pts_ot2_home: Series[Object] = pa.Field(nullable=True)
    pts_ot3_home: Series[Object] = pa.Field(nullable=True)
    pts_ot4_home: Series[Object] = pa.Field(nullable=True)
    pts_ot5_home: Series[Object] = pa.Field(nullable=True)
    pts_ot6_home: Series[Object] = pa.Field(nullable=True)
    pts_ot7_home: Series[Object] = pa.Field(nullable=True)
    pts_ot8_home: Series[Object] = pa.Field(nullable=True)
    pts_ot9_home: Series[Object] = pa.Field(nullable=True)
    pts_ot10_home: Series[Object] = pa.Field(nullable=True)
    pts_home: Series[Object] = pa.Field()
    team_id_away: Series[String] = pa.Field()
    team_abbreviation_away: Series[String] = pa.Field()
    team_city_name_away: Series[String] = pa.Field()
    team_nickname_away: Series[String] = pa.Field()
    team_wins_losses_away: Series[String] = pa.Field()
    pts_qtr1_away: Series[Object] = pa.Field(nullable=True)
    pts_qtr2_away: Series[Object] = pa.Field(nullable=True)
    pts_qtr3_away: Series[Object] = pa.Field(nullable=True)
    pts_qtr4_away: Series[Object] = pa.Field(nullable=True)
    pts_ot1_away: Series[Object] = pa.Field(nullable=True)
    pts_ot2_away: Series[Object] = pa.Field(nullable=True)
    pts_ot3_away: Series[Object] = pa.Field(nullable=True)
    pts_ot4_away: Series[Object] = pa.Field(nullable=True)
    pts_ot5_away: Series[Object] = pa.Field(nullable=True)
    pts_ot6_away: Series[Object] = pa.Field(nullable=True)
    pts_ot7_away: Series[Object] = pa.Field(nullable=True)
    pts_ot8_away: Series[Object] = pa.Field(nullable=True)
    pts_ot9_away: Series[Object] = pa.Field(nullable=True)
    pts_ot10_away: Series[Object] = pa.Field(nullable=True)
    pts_away: Series[Int] = pa.Field()

    class Config:
        coerce = True