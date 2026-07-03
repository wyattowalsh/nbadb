from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingCommonPlayoffSeriesSchema(BaseSchema):
    season_id: str | None = pa.Field(nullable=True, metadata={"description": "Season identifier"})
    series_id: str | None = pa.Field(
        nullable=True, metadata={"description": "Playoff series identifier"}
    )
    game_id: str | None = pa.Field(nullable=True, metadata={"description": "Game identifier"})
    game_number: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Series game number"}
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Home team identifier", "fk_ref": "staging_team.team_id"},
    )
    away_team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Away team identifier", "fk_ref": "staging_team.team_id"},
    )
    home_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Home team abbreviation"},
    )
    away_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Away team abbreviation"},
    )
    wins: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Wins in the series"})
    losses: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Losses in the series"},
    )


class StagingIstStandingsSchema(BaseSchema):
    league_id: str | None = pa.Field(nullable=True, metadata={"description": "League identifier"})
    season_year: str | None = pa.Field(nullable=True, metadata={"description": "Season year"})
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_city: str | None = pa.Field(nullable=True, metadata={"description": "Team city"})
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation"}
    )
    team_slug: str | None = pa.Field(nullable=True, metadata={"description": "Team slug"})
    conference: str | None = pa.Field(nullable=True, metadata={"description": "Conference"})
    ist_group: str | None = pa.Field(nullable=True, metadata={"description": "Cup group"})
    group_name: str | None = pa.Field(nullable=True, metadata={"description": "Cup group name"})
    clinch_indicator: str | None = pa.Field(
        nullable=True, metadata={"description": "Cup clinch status indicator"}
    )
    clinched_ist_group: int | None = pa.Field(
        nullable=True, metadata={"description": "Cup group clinch flag"}
    )
    clinched_ist_knockout: int | None = pa.Field(
        nullable=True, metadata={"description": "Cup knockout clinch flag"}
    )
    clinched_ist_wildcard: int | None = pa.Field(
        nullable=True, metadata={"description": "Cup wildcard clinch flag"}
    )
    wins: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Cup wins"})
    losses: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Cup losses"})
    pct: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Cup win pct"})
    win_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Cup win percentage"},
    )
    points_for: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Points scored in cup play"},
    )
    points_against: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Points allowed in cup play"},
    )
    point_diff: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Point differential in cup play"},
    )
    pts: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Points"})
    opp_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Opponent points"}
    )
    diff: float | None = pa.Field(nullable=True, metadata={"description": "Point differential"})
    ist_group_rank: int | None = pa.Field(nullable=True, ge=0)
    ist_group_gb: float | None = pa.Field(nullable=True, ge=0.0)
    ist_wildcard_rank: int | None = pa.Field(nullable=True, ge=0)
    ist_wildcard_gb: float | None = pa.Field(nullable=True, ge=0.0)
    ist_knockout_rank: int | None = pa.Field(nullable=True, ge=0)
    game_id1: str | None = pa.Field(nullable=True)
    game_id2: str | None = pa.Field(nullable=True)
    game_id3: str | None = pa.Field(nullable=True)
    game_id4: str | None = pa.Field(nullable=True)
    game_status1: int | None = pa.Field(nullable=True)
    game_status2: int | None = pa.Field(nullable=True)
    game_status3: int | None = pa.Field(nullable=True)
    game_status4: int | None = pa.Field(nullable=True)
    game_status_text1: str | None = pa.Field(nullable=True)
    game_status_text2: str | None = pa.Field(nullable=True)
    game_status_text3: str | None = pa.Field(nullable=True)
    game_status_text4: str | None = pa.Field(nullable=True)
    location1: str | None = pa.Field(nullable=True)
    location2: str | None = pa.Field(nullable=True)
    location3: str | None = pa.Field(nullable=True)
    location4: str | None = pa.Field(nullable=True)
    opponent_team_abbreviation1: str | None = pa.Field(nullable=True)
    opponent_team_abbreviation2: str | None = pa.Field(nullable=True)
    opponent_team_abbreviation3: str | None = pa.Field(nullable=True)
    opponent_team_abbreviation4: str | None = pa.Field(nullable=True)
    outcome1: str | None = pa.Field(nullable=True)
    outcome2: str | None = pa.Field(nullable=True)
    outcome3: str | None = pa.Field(nullable=True)
    outcome4: str | None = pa.Field(nullable=True)


class StagingLeaguePlayerBioSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Player identifier", "fk_ref": "staging_player.person_id"},
    )
    player_name: str | None = pa.Field(nullable=True, metadata={"description": "Player name"})
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Team abbreviation"},
    )
    season_year: str | None = pa.Field(nullable=True, metadata={"description": "Season year"})
    age: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Player age"})
    height: str | None = pa.Field(nullable=True, metadata={"description": "Listed height"})
    weight: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Listed weight"}
    )
    college: str | None = pa.Field(nullable=True, metadata={"description": "College"})
    country: str | None = pa.Field(nullable=True, metadata={"description": "Country"})
    draft_year: str | None = pa.Field(nullable=True, metadata={"description": "Draft year"})
    draft_round: str | None = pa.Field(nullable=True, metadata={"description": "Draft round"})
    draft_number: str | None = pa.Field(nullable=True, metadata={"description": "Draft number"})
    player_height: str | None = pa.Field(nullable=True, metadata={"description": "Player height"})
    player_height_inches: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Player height in inches"}
    )
    player_weight: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Player weight"}
    )
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    pts: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Points"})
    reb: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Rebounds"})
    ast: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Assists"})
    net_rating: float | None = pa.Field(nullable=True, metadata={"description": "Net rating"})
    oreb_pct: float | None = pa.Field(nullable=True, ge=0.0)
    dreb_pct: float | None = pa.Field(nullable=True, ge=0.0)
    usg_pct: float | None = pa.Field(nullable=True, ge=0.0)
    ts_pct: float | None = pa.Field(nullable=True, ge=0.0)
    ast_pct: float | None = pa.Field(nullable=True, ge=0.0)


class StagingLeagueDashPlayerBioStatsSchema(StagingLeaguePlayerBioSchema):
    pass


class StagingLeaguePlayerClutchSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Player identifier", "fk_ref": "staging_player.person_id"},
    )
    player_name: str | None = pa.Field(nullable=True, metadata={"description": "Player name"})
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Team abbreviation"},
    )
    age: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Player age"})
    group_set: str | None = pa.Field(
        nullable=True, metadata={"description": "Dashboard grouping set"}
    )
    season_year: str = pa.Field(nullable=False, metadata={"description": "Season year"})
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    gp_rank: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Wins"})
    w_rank: int | None = pa.Field(nullable=True, ge=0)
    l: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Losses"})  # noqa: E741
    l_rank: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Win pct"})
    w_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    min: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Minutes"})
    min_rank: int | None = pa.Field(nullable=True, ge=0)
    pts: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Points"})
    pts_rank: int | None = pa.Field(nullable=True, ge=0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fga_rank: int | None = pa.Field(nullable=True, ge=0)
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Field goal percentage"},
    )
    fg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3m_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    ftm_rank: int | None = pa.Field(nullable=True, ge=0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    fta_rank: int | None = pa.Field(nullable=True, ge=0)
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Free throw percentage"},
    )
    ft_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    oreb_rank: int | None = pa.Field(nullable=True, ge=0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb_rank: int | None = pa.Field(nullable=True, ge=0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    reb_rank: int | None = pa.Field(nullable=True, ge=0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    ast_rank: int | None = pa.Field(nullable=True, ge=0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    tov_rank: int | None = pa.Field(nullable=True, ge=0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    stl_rank: int | None = pa.Field(nullable=True, ge=0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blk_rank: int | None = pa.Field(nullable=True, ge=0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    blka_rank: int | None = pa.Field(nullable=True, ge=0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pf_rank: int | None = pa.Field(nullable=True, ge=0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    pfd_rank: int | None = pa.Field(nullable=True, ge=0)
    plus_minus: float | None = pa.Field(nullable=True)
    plus_minus_rank: int | None = pa.Field(nullable=True, ge=0)
    nba_fantasy_pts: float | None = pa.Field(nullable=True, ge=0.0)
    nba_fantasy_pts_rank: int | None = pa.Field(nullable=True, ge=0)
    dd2: float | None = pa.Field(nullable=True, ge=0.0)
    dd2_rank: int | None = pa.Field(nullable=True, ge=0)
    td3: float | None = pa.Field(nullable=True, ge=0.0)
    td3_rank: int | None = pa.Field(nullable=True, ge=0)
    cfid: int | None = pa.Field(nullable=True, ge=0)
    cfparams: str | None = pa.Field(nullable=True)


class StagingShotLocationsSchema(BaseSchema):
    season_year: str = pa.Field(nullable=False, metadata={"description": "Season year"})
    player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Player identifier", "fk_ref": "staging_player.person_id"},
    )
    player_name: str | None = pa.Field(nullable=True, metadata={"description": "Player name"})
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Team abbreviation"},
    )
    age: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.AGE",
            "description": "Player age",
        },
    )
    shot_zone_basic: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Basic shot zone bucket"},
    )
    shot_zone_area: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Shot zone area"},
    )
    shot_zone_range: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Shot zone range"},
    )
    fgm: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Field goals made"}
    )
    fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Field goals attempted"},
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Field goal percentage"},
    )
    restricted_area_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.RESTRICTED_AREA_FGM",
            "description": "Restricted area field goals made",
        },
    )
    restricted_area_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.RESTRICTED_AREA_FGA",
            "description": "Restricted area field goals attempted",
        },
    )
    restricted_area_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.RESTRICTED_AREA_FG_PCT",
            "description": "Restricted area field goal percentage",
        },
    )
    in_the_paint_non_ra_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.IN_THE_PAINT_NON_RA_FGM",
            "description": "Non-restricted paint field goals made",
        },
    )
    in_the_paint_non_ra_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.IN_THE_PAINT_NON_RA_FGA",
            "description": "Non-restricted paint field goals attempted",
        },
    )
    in_the_paint_non_ra_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.IN_THE_PAINT_NON_RA_FG_PCT",
            "description": "Non-restricted paint field goal percentage",
        },
    )
    mid_range_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.MID_RANGE_FGM",
            "description": "Mid-range field goals made",
        },
    )
    mid_range_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.MID_RANGE_FGA",
            "description": "Mid-range field goals attempted",
        },
    )
    mid_range_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.MID_RANGE_FG_PCT",
            "description": "Mid-range field goal percentage",
        },
    )
    left_corner_3_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.LEFT_CORNER_3_FGM",
            "description": "Left-corner three-point field goals made",
        },
    )
    left_corner_3_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.LEFT_CORNER_3_FGA",
            "description": "Left-corner three-point field goals attempted",
        },
    )
    left_corner_3_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.LEFT_CORNER_3_FG_PCT",
            "description": "Left-corner three-point field goal percentage",
        },
    )
    right_corner_3_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.RIGHT_CORNER_3_FGM",
            "description": "Right-corner three-point field goals made",
        },
    )
    right_corner_3_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.RIGHT_CORNER_3_FGA",
            "description": "Right-corner three-point field goals attempted",
        },
    )
    right_corner_3_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.RIGHT_CORNER_3_FG_PCT",
            "description": "Right-corner three-point field goal percentage",
        },
    )
    above_the_break_3_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.ABOVE_THE_BREAK_3_FGM",
            "description": "Above-the-break three-point field goals made",
        },
    )
    above_the_break_3_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.ABOVE_THE_BREAK_3_FGA",
            "description": "Above-the-break three-point field goals attempted",
        },
    )
    above_the_break_3_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.ABOVE_THE_BREAK_3_FG_PCT",
            "description": "Above-the-break three-point field goal percentage",
        },
    )
    backcourt_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.BACKCOURT_FGM",
            "description": "Backcourt field goals made",
        },
    )
    backcourt_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.BACKCOURT_FGA",
            "description": "Backcourt field goals attempted",
        },
    )
    backcourt_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashPlayerShotLocations.ShotLocations.BACKCOURT_FG_PCT",
            "description": "Backcourt field goal percentage",
        },
    )


class StagingTrackingDefenseSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "description": "Defender player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(nullable=True, metadata={"description": "Defender name"})
    age: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Player age"})
    player_position: str | None = pa.Field(
        nullable=True, metadata={"description": "Player position"}
    )
    close_def_person_id: int | None = pa.Field(
        nullable=True, gt=0, metadata={"description": "Closest defender identifier"}
    )
    player_last_team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Player last team identifier", "fk_ref": "staging_team.team_id"},
    )
    player_last_team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Player last team abbreviation"}
    )
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Team abbreviation"},
    )
    defense_category: str = pa.Field(nullable=False, metadata={"description": "Defense category"})
    season_year: str | None = pa.Field(nullable=True, metadata={"description": "Season year"})
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    g: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games"})
    freq: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Frequency"})
    d_fgm: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Defended FGM"})
    d_fga: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Defended FGA"})
    d_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Defended FG percentage"},
    )
    normal_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Baseline FG percentage"},
    )
    pct_plusminus: float | None = pa.Field(
        nullable=True,
        metadata={"description": "FG percentage differential"},
    )


class LeaguePtShotsBaseSchema(BaseSchema):
    id: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Generic row identifier"}
    )
    player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Player identifier", "fk_ref": "staging_player.person_id"},
    )
    player_name: str | None = pa.Field(nullable=True, metadata={"description": "Player name"})
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Team abbreviation"},
    )
    season_year: str | None = pa.Field(nullable=True, metadata={"description": "Season year"})
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    g: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games"})
    sort_order: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Sort order"})
    close_def_dist_range: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Closest defender distance range"},
    )
    fga_frequency: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Shot-attempt frequency"},
    )
    fg2a_frequency: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a_frequency: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Field goals made"})
    fga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Field goals attempted"},
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Field goal percentage"},
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Effective field goal percentage"},
    )
    fg2m: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Two-point makes"})
    fg2a: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Two-point attempts"},
    )
    fg2_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Two-point percentage"},
    )
    fg3m: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Three-point makes"},
    )
    fg3a: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Three-point attempts"},
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Three-point percentage"},
    )
    dfgm: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Defended FGM"})
    dfga: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Defended FGA"})
    dfg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Defended FG percentage"},
    )


class StagingLeaguePtStatsSchema(LeaguePtShotsBaseSchema):
    w: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Wins"})
    l: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Losses"})  # noqa: E741
    w_pct: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Win pct"})
    min: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Minutes"})
    dist_feet: float | None = pa.Field(nullable=True, ge=0.0)
    dist_miles: float | None = pa.Field(nullable=True, ge=0.0)
    dist_miles_off: float | None = pa.Field(nullable=True, ge=0.0)
    dist_miles_def: float | None = pa.Field(nullable=True, ge=0.0)
    avg_speed: float | None = pa.Field(nullable=True, ge=0.0)
    avg_speed_off: float | None = pa.Field(nullable=True, ge=0.0)
    avg_speed_def: float | None = pa.Field(nullable=True, ge=0.0)


class StagingLeaguePtTeamDefendSchema(LeaguePtShotsBaseSchema):
    freq: float | None = pa.Field(nullable=True, ge=0.0)
    d_fgm: float | None = pa.Field(nullable=True, ge=0.0)
    d_fga: float | None = pa.Field(nullable=True, ge=0.0)
    d_fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    normal_fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    pct_plusminus: float | None = pa.Field(nullable=True)


class StagingLeagueTeamPtShotSchema(LeaguePtShotsBaseSchema):
    pass


class StagingLeagueOppPtShotSchema(LeaguePtShotsBaseSchema):
    pass


class StagingLeaguePlayerPtShotSchema(LeaguePtShotsBaseSchema):
    age: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Player age"})
    player_last_team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Player last team identifier", "fk_ref": "staging_team.team_id"},
    )
    player_last_team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Player last team abbreviation"}
    )


class StagingLeagueTeamClutchSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    season_year: str = pa.Field(nullable=False, metadata={"description": "Season year"})
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    gp_rank: int | None = pa.Field(nullable=True, ge=0)
    w_rank: int | None = pa.Field(nullable=True, ge=0)
    l_rank: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Wins"})
    l: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Losses"})  # noqa: E741
    w_pct: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Win pct"})
    min: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Minutes"})
    min_rank: int | None = pa.Field(nullable=True, ge=0)
    pts: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Points"})
    pts_rank: int | None = pa.Field(nullable=True, ge=0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fga_rank: int | None = pa.Field(nullable=True, ge=0)
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Field goal percentage"},
    )
    fg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3m_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    ftm_rank: int | None = pa.Field(nullable=True, ge=0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    fta_rank: int | None = pa.Field(nullable=True, ge=0)
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Free throw percentage"},
    )
    ft_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    oreb_rank: int | None = pa.Field(nullable=True, ge=0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb_rank: int | None = pa.Field(nullable=True, ge=0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    reb_rank: int | None = pa.Field(nullable=True, ge=0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    ast_rank: int | None = pa.Field(nullable=True, ge=0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    tov_rank: int | None = pa.Field(nullable=True, ge=0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    stl_rank: int | None = pa.Field(nullable=True, ge=0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blk_rank: int | None = pa.Field(nullable=True, ge=0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    blka_rank: int | None = pa.Field(nullable=True, ge=0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pf_rank: int | None = pa.Field(nullable=True, ge=0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    pfd_rank: int | None = pa.Field(nullable=True, ge=0)
    plus_minus: float | None = pa.Field(nullable=True, metadata={"description": "Plus-minus"})
    plus_minus_rank: int | None = pa.Field(nullable=True, ge=0)
    cfid: int | None = pa.Field(nullable=True, ge=0)
    cfparams: str | None = pa.Field(nullable=True)


class StagingLeagueTeamShotLocationsSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    season_year: str = pa.Field(nullable=False, metadata={"description": "Season year"})
    shot_zone_basic: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Basic shot zone bucket"},
    )
    shot_zone_area: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Shot zone area"},
    )
    shot_zone_range: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Shot zone range"},
    )
    fgm: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Field goals made"}
    )
    fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Field goals attempted"},
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Field goal percentage"},
    )
    restricted_area_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.RESTRICTED_AREA_FGM",
            "description": "Restricted area field goals made",
        },
    )
    restricted_area_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.RESTRICTED_AREA_FGA",
            "description": "Restricted area field goals attempted",
        },
    )
    restricted_area_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.RESTRICTED_AREA_FG_PCT",
            "description": "Restricted area field goal percentage",
        },
    )
    in_the_paint_non_ra_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.IN_THE_PAINT_NON_RA_FGM",
            "description": "Non-restricted paint field goals made",
        },
    )
    in_the_paint_non_ra_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.IN_THE_PAINT_NON_RA_FGA",
            "description": "Non-restricted paint field goals attempted",
        },
    )
    in_the_paint_non_ra_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.IN_THE_PAINT_NON_RA_FG_PCT",
            "description": "Non-restricted paint field goal percentage",
        },
    )
    mid_range_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.MID_RANGE_FGM",
            "description": "Mid-range field goals made",
        },
    )
    mid_range_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.MID_RANGE_FGA",
            "description": "Mid-range field goals attempted",
        },
    )
    mid_range_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.MID_RANGE_FG_PCT",
            "description": "Mid-range field goal percentage",
        },
    )
    left_corner_3_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.LEFT_CORNER_3_FGM",
            "description": "Left-corner three-point field goals made",
        },
    )
    left_corner_3_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.LEFT_CORNER_3_FGA",
            "description": "Left-corner three-point field goals attempted",
        },
    )
    left_corner_3_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.LEFT_CORNER_3_FG_PCT",
            "description": "Left-corner three-point field goal percentage",
        },
    )
    right_corner_3_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.RIGHT_CORNER_3_FGM",
            "description": "Right-corner three-point field goals made",
        },
    )
    right_corner_3_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.RIGHT_CORNER_3_FGA",
            "description": "Right-corner three-point field goals attempted",
        },
    )
    right_corner_3_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.RIGHT_CORNER_3_FG_PCT",
            "description": "Right-corner three-point field goal percentage",
        },
    )
    above_the_break_3_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.ABOVE_THE_BREAK_3_FGM",
            "description": "Above-the-break three-point field goals made",
        },
    )
    above_the_break_3_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.ABOVE_THE_BREAK_3_FGA",
            "description": "Above-the-break three-point field goals attempted",
        },
    )
    above_the_break_3_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.ABOVE_THE_BREAK_3_FG_PCT",
            "description": "Above-the-break three-point field goal percentage",
        },
    )
    backcourt_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.BACKCOURT_FGM",
            "description": "Backcourt field goals made",
        },
    )
    backcourt_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.BACKCOURT_FGA",
            "description": "Backcourt field goals attempted",
        },
    )
    backcourt_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashTeamShotLocations.ShotLocations.BACKCOURT_FG_PCT",
            "description": "Backcourt field goal percentage",
        },
    )


class StagingLeagueHustlePlayerSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Player identifier", "fk_ref": "staging_player.person_id"},
    )
    player_name: str | None = pa.Field(nullable=True, metadata={"description": "Player name"})
    age: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Player age"})
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Team abbreviation"},
    )
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    g: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games"})
    min: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Minutes"})
    contested_shots: float | None = pa.Field(nullable=True, ge=0.0)
    contested_shots_2pt: float | None = pa.Field(nullable=True, ge=0.0)
    contested_shots_3pt: float | None = pa.Field(nullable=True, ge=0.0)
    deflections: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Deflections"},
    )
    charges_drawn: float | None = pa.Field(nullable=True, ge=0.0)
    screen_assists: float | None = pa.Field(nullable=True, ge=0.0)
    screen_ast_pts: float | None = pa.Field(nullable=True, ge=0.0)
    off_loose_balls_recovered: float | None = pa.Field(nullable=True, ge=0.0)
    def_loose_balls_recovered: float | None = pa.Field(nullable=True, ge=0.0)
    loose_balls_recovered: float | None = pa.Field(nullable=True, ge=0.0)
    pct_loose_balls_recovered_off: float | None = pa.Field(nullable=True, ge=0.0)
    pct_loose_balls_recovered_def: float | None = pa.Field(nullable=True, ge=0.0)
    off_boxouts: float | None = pa.Field(nullable=True, ge=0.0)
    def_boxouts: float | None = pa.Field(nullable=True, ge=0.0)
    box_out_player_team_rebs: float | None = pa.Field(nullable=True, ge=0.0)
    box_out_player_rebs: float | None = pa.Field(nullable=True, ge=0.0)
    box_outs: float | None = pa.Field(nullable=True, ge=0.0)
    pct_box_outs_off: float | None = pa.Field(nullable=True, ge=0.0)
    pct_box_outs_def: float | None = pa.Field(nullable=True, ge=0.0)
    pct_box_outs_team_reb: float | None = pa.Field(nullable=True, ge=0.0)
    pct_box_outs_reb: float | None = pa.Field(nullable=True, ge=0.0)


class StagingLeagueHustleTeamSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    min: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Minutes"})
    contested_shots: float | None = pa.Field(nullable=True, ge=0.0)
    contested_shots_2pt: float | None = pa.Field(nullable=True, ge=0.0)
    contested_shots_3pt: float | None = pa.Field(nullable=True, ge=0.0)
    deflections: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Deflections"},
    )
    charges_drawn: float | None = pa.Field(nullable=True, ge=0.0)
    screen_assists: float | None = pa.Field(nullable=True, ge=0.0)
    screen_ast_pts: float | None = pa.Field(nullable=True, ge=0.0)
    off_loose_balls_recovered: float | None = pa.Field(nullable=True, ge=0.0)
    def_loose_balls_recovered: float | None = pa.Field(nullable=True, ge=0.0)
    loose_balls_recovered: float | None = pa.Field(nullable=True, ge=0.0)
    pct_loose_balls_recovered_off: float | None = pa.Field(nullable=True, ge=0.0)
    pct_loose_balls_recovered_def: float | None = pa.Field(nullable=True, ge=0.0)
    off_boxouts: float | None = pa.Field(nullable=True, ge=0.0)
    def_boxouts: float | None = pa.Field(nullable=True, ge=0.0)
    box_outs: float | None = pa.Field(nullable=True, ge=0.0)
    pct_box_outs_off: float | None = pa.Field(nullable=True, ge=0.0)
    pct_box_outs_def: float | None = pa.Field(nullable=True, ge=0.0)


class StagingBoxScoreUsageTeamSchema(BaseSchema):
    game_id: str = pa.Field(nullable=False, metadata={"description": "Game identifier"})
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Team abbreviation"},
    )
    team_city: str | None = pa.Field(nullable=True, metadata={"description": "Team city"})
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    team_slug: str | None = pa.Field(nullable=True, metadata={"description": "Team slug"})
    min: str | None = pa.Field(nullable=True, metadata={"description": "Minutes played"})
    usg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Usage percentage"},
    )
    pct_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team field goals made"},
    )
    pct_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team field goals attempted"},
    )
    pct_fg3m: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team threes made"},
    )
    pct_fg3a: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team threes attempted"},
    )
    pct_ftm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team free throws made"},
    )
    pct_fta: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team free throws attempted"},
    )
    pct_oreb: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team offensive rebounds"},
    )
    pct_dreb: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team defensive rebounds"},
    )
    pct_reb: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team rebounds"},
    )
    pct_ast: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team assists"},
    )
    pct_tov: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team turnovers"},
    )
    pct_stl: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team steals"},
    )
    pct_blk: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team blocks"},
    )
    pct_blka: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team blocked attempts"},
    )
    pct_pf: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team personal fouls"},
    )
    pct_pfd: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team fouls drawn"},
    )
    pct_pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Share of team points"},
    )
