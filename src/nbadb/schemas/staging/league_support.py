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
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    group_name: str | None = pa.Field(nullable=True, metadata={"description": "Cup group name"})
    wins: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Cup wins"})
    losses: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Cup losses"})
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
    season_year: str = pa.Field(nullable=False, metadata={"description": "Season year"})
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    min: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Minutes"})
    pts: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Points"})
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Field goal percentage"},
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Free throw percentage"},
    )


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
    pass


class StagingLeaguePtTeamDefendSchema(LeaguePtShotsBaseSchema):
    pass


class StagingLeagueTeamPtShotSchema(LeaguePtShotsBaseSchema):
    pass


class StagingLeagueOppPtShotSchema(LeaguePtShotsBaseSchema):
    pass


class StagingLeaguePlayerPtShotSchema(LeaguePtShotsBaseSchema):
    pass


class StagingLeagueTeamClutchSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    season_year: str = pa.Field(nullable=False, metadata={"description": "Season year"})
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    w: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Wins"})
    l: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Losses"})  # noqa: E741
    min: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Minutes"})
    pts: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Points"})
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Field goal percentage"},
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Free throw percentage"},
    )
    plus_minus: float | None = pa.Field(nullable=True, metadata={"description": "Plus-minus"})


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


class StagingLeagueHustlePlayerSchema(BaseSchema):
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
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    min: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Minutes"})
    deflections: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Deflections"},
    )


class StagingLeagueHustleTeamSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={"description": "Team identifier", "fk_ref": "staging_team.team_id"},
    )
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    deflections: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Deflections"},
    )


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
