from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema
from nbadb.schemas.staging.box_score import (
    StagingBoxScoreAdvancedTeamSchema,
    StagingBoxScoreDefensiveTeamSchema,
    StagingBoxScoreFourFactorsTeamSchema,
    StagingBoxScoreHustlePlayerSchema,
    StagingBoxScoreMiscTeamSchema,
    StagingBoxScorePlayerTrackTeamSchema,
    StagingBoxScoreScoringTeamSchema,
    StagingBoxScoreTraditionalStarterBenchSchema,
    StagingBoxScoreTraditionalTeamSchema,
)
from nbadb.schemas.staging.schedule import StagingScoreboardWinProbabilitySchema


class FactBoxScoreTeamSchema(StagingBoxScoreTraditionalTeamSchema):
    __consumer_metadata__ = {
        "grain": "team-game",
        "agent_intents": ["team_box_score", "box_score_team"],
        "join_hints": {"dim_team": "team_id"},
    }


class FactBoxScoreStarterBenchSchema(StagingBoxScoreTraditionalStarterBenchSchema):
    pass


class FactBoxScoreAdvancedTeamSchema(StagingBoxScoreAdvancedTeamSchema):
    pass


class FactBoxScoreMiscTeamSchema(StagingBoxScoreMiscTeamSchema):
    pass


class FactBoxScoreScoringTeamSchema(StagingBoxScoreScoringTeamSchema):
    pass


class FactBoxScoreFourFactorsTeamSchema(StagingBoxScoreFourFactorsTeamSchema):
    pass


class FactBoxScorePlayerTrackTeamSchema(StagingBoxScorePlayerTrackTeamSchema):
    pass


class FactBoxScoreDefensiveTeamSchema(StagingBoxScoreDefensiveTeamSchema):
    pass


class FactBoxScoreHustlePlayerSchema(StagingBoxScoreHustlePlayerSchema):
    pass


class FactScoreboardWinProbabilitySchema(StagingScoreboardWinProbabilitySchema):
    pass


class FactGameContextSchema(BaseSchema):
    game_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "description": "Game identifier across game-context result packets",
            "fk_ref": "dim_game.game_id",
        },
    )
    game_date: str | None = pa.Field(nullable=True, metadata={"description": "Game date"})
    attendance: int | None = pa.Field(
        nullable=True, metadata={"description": "Reported attendance"}
    )
    game_time: str | None = pa.Field(
        nullable=True, metadata={"description": "Game time or duration"}
    )
    game_status_text: str | None = pa.Field(
        nullable=True, metadata={"description": "Game status display text"}
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Home team identifier", "fk_ref": "dim_team.team_id"},
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Visitor team identifier", "fk_ref": "dim_team.team_id"},
    )
    team_id: int | None = pa.Field(
        nullable=True, metadata={"description": "Team identifier", "fk_ref": "dim_team.team_id"}
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    team_city: str | None = pa.Field(nullable=True, metadata={"description": "Team city name"})
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    player_id: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Player identifier", "fk_ref": "dim_player.player_id"},
    )
    first_name: str | None = pa.Field(nullable=True, metadata={"description": "First name"})
    last_name: str | None = pa.Field(nullable=True, metadata={"description": "Last name"})
    jersey_num: str | None = pa.Field(nullable=True, metadata={"description": "Jersey number"})
    pts_paint: int | None = pa.Field(nullable=True, metadata={"description": "Points in the paint"})
    pts_2nd_chance: int | None = pa.Field(
        nullable=True, metadata={"description": "Second chance points"}
    )
    pts_fb: int | None = pa.Field(nullable=True, metadata={"description": "Fast break points"})
    pts_off_to: int | None = pa.Field(
        nullable=True, metadata={"description": "Points off turnovers"}
    )
    largest_lead: int | None = pa.Field(nullable=True, metadata={"description": "Largest lead"})
    lead_changes: int | None = pa.Field(nullable=True, metadata={"description": "Lead changes"})
    times_tied: int | None = pa.Field(nullable=True, metadata={"description": "Times tied"})
    last_game_id: str | None = pa.Field(
        nullable=True, metadata={"description": "Previous meeting game identifier"}
    )
    series_leader: str | None = pa.Field(
        nullable=True, metadata={"description": "Season-series leader label"}
    )
    video_available_flag: int | None = pa.Field(
        nullable=True, metadata={"description": "Video availability flag"}
    )
    pt_available: int | None = pa.Field(
        nullable=True, metadata={"description": "Player tracking availability flag"}
    )
    pt_xyz_available: int | None = pa.Field(
        nullable=True, metadata={"description": "Player tracking XYZ availability flag"}
    )
    wh_status: int | None = pa.Field(
        nullable=True, metadata={"description": "Wagering hub status flag"}
    )
    hustle_status: int | None = pa.Field(
        nullable=True, metadata={"description": "Hustle availability flag"}
    )
    historical_status: int | None = pa.Field(
        nullable=True, metadata={"description": "Historical data availability flag"}
    )
    context_source: str = pa.Field(
        nullable=False, metadata={"description": "Source packet contributing the row"}
    )


class FactBoxScoreSummaryV3Schema(BaseSchema):
    game_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "description": "Game identifier across BoxScoreSummaryV3 result packets",
            "fk_ref": "dim_game.game_id",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True, metadata={"description": "Game status display text"}
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Home team identifier", "fk_ref": "dim_team.team_id"},
    )
    away_team_id: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Away team identifier", "fk_ref": "dim_team.team_id"},
    )
    team_id: int | None = pa.Field(
        nullable=True, metadata={"description": "Team identifier", "fk_ref": "dim_team.team_id"}
    )
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    team_tricode: str | None = pa.Field(nullable=True, metadata={"description": "Team tricode"})
    person_id: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Person identifier", "fk_ref": "dim_player.player_id"},
    )
    name: str | None = pa.Field(nullable=True, metadata={"description": "Display name"})
    arena_id: int | None = pa.Field(
        nullable=True, metadata={"description": "Arena identifier", "fk_ref": "dim_arena.arena_id"}
    )
    arena_name: str | None = pa.Field(nullable=True, metadata={"description": "Arena name"})
    attendance: int | None = pa.Field(
        nullable=True, metadata={"description": "Reported attendance"}
    )
    score: int | None = pa.Field(nullable=True, metadata={"description": "Team score"})
    points: int | None = pa.Field(
        nullable=True, metadata={"description": "Points from the OtherStats packet"}
    )
    rebounds_total: int | None = pa.Field(nullable=True, metadata={"description": "Total rebounds"})
    assists: int | None = pa.Field(nullable=True, metadata={"description": "Assists"})
    lead_changes: int | None = pa.Field(nullable=True, metadata={"description": "Lead changes"})
    times_tied: int | None = pa.Field(nullable=True, metadata={"description": "Times tied"})
    biggest_lead: int | None = pa.Field(nullable=True, metadata={"description": "Biggest lead"})
    bench_points: int | None = pa.Field(nullable=True, metadata={"description": "Bench points"})
    video_available_flag: int | None = pa.Field(
        nullable=True, metadata={"description": "Video availability flag"}
    )
    summary_type: str = pa.Field(
        nullable=False, metadata={"description": "Source packet contributing the row"}
    )


class FactScoreboardDetailSchema(BaseSchema):
    game_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "description": "Game identifier across scoreboard detail result packets",
            "fk_ref": "dim_game.game_id",
        },
    )
    game_date_est: str | None = pa.Field(
        nullable=True, metadata={"description": "Game date in Eastern time"}
    )
    team_id: int | None = pa.Field(
        nullable=True, metadata={"description": "Team identifier", "fk_ref": "dim_team.team_id"}
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    team_city: str | None = pa.Field(nullable=True, metadata={"description": "Team city name"})
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Home team identifier", "fk_ref": "dim_team.team_id"},
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Visitor team identifier", "fk_ref": "dim_team.team_id"},
    )
    conference: str | None = pa.Field(nullable=True, metadata={"description": "Conference name"})
    standings_date: str | None = pa.Field(nullable=True, metadata={"description": "Standings date"})
    team: str | None = pa.Field(nullable=True, metadata={"description": "Standings team label"})
    wins: int | None = pa.Field(nullable=True, alias="w", metadata={"description": "Wins"})
    losses: int | None = pa.Field(nullable=True, alias="l", metadata={"description": "Losses"})
    w_pct: float | None = pa.Field(nullable=True, metadata={"description": "Winning percentage"})
    pts: int | None = pa.Field(nullable=True, metadata={"description": "Points"})
    fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Field goal percentage"}
    )
    ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Free throw percentage"}
    )
    fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point percentage"}
    )
    ast: int | None = pa.Field(nullable=True, metadata={"description": "Assists"})
    reb: int | None = pa.Field(nullable=True, metadata={"description": "Rebounds"})
    tov: int | None = pa.Field(nullable=True, metadata={"description": "Turnovers"})
    series_leader: str | None = pa.Field(
        nullable=True, metadata={"description": "Series leader label"}
    )
    pts_player_id: int | None = pa.Field(
        nullable=True, metadata={"description": "Points leader player identifier"}
    )
    reb_player_id: int | None = pa.Field(
        nullable=True, metadata={"description": "Rebounds leader player identifier"}
    )
    ast_player_id: int | None = pa.Field(
        nullable=True, metadata={"description": "Assists leader player identifier"}
    )
    home_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Home team win probability"}
    )
    visitor_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Visitor team win probability"}
    )
    detail_type: str = pa.Field(
        nullable=False, metadata={"description": "Source packet contributing the row"}
    )


class FactScoreboardV3Schema(BaseSchema):
    game_date: str | None = pa.Field(nullable=True, metadata={"description": "Game date"})
    league_id: str | None = pa.Field(nullable=True, metadata={"description": "League identifier"})
    league_name: str | None = pa.Field(nullable=True, metadata={"description": "League name"})
    game_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "description": "Game identifier across ScoreboardV3 result packets",
            "fk_ref": "dim_game.game_id",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True, metadata={"description": "Game status display text"}
    )
    team_id: int | None = pa.Field(
        nullable=True, metadata={"description": "Team identifier", "fk_ref": "dim_team.team_id"}
    )
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    team_tricode: str | None = pa.Field(nullable=True, metadata={"description": "Team tricode"})
    score: int | None = pa.Field(nullable=True, metadata={"description": "Current score"})
    leader_type: str | None = pa.Field(
        nullable=True, metadata={"description": "Leader statistic type"}
    )
    person_id: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Person identifier", "fk_ref": "dim_player.player_id"},
    )
    name: str | None = pa.Field(nullable=True, metadata={"description": "Display name"})
    broadcaster_type: str | None = pa.Field(
        nullable=True, metadata={"description": "Broadcaster type"}
    )
    broadcast_display: str | None = pa.Field(
        nullable=True, metadata={"description": "Broadcast display string"}
    )
    scoreboard_type: str = pa.Field(
        nullable=False, metadata={"description": "Source packet contributing the row"}
    )


derived_output_schema()(FactBoxScoreTeamSchema)
derived_output_schema()(FactBoxScoreStarterBenchSchema)
derived_output_schema()(FactBoxScoreAdvancedTeamSchema)
derived_output_schema()(FactBoxScoreMiscTeamSchema)
derived_output_schema()(FactBoxScoreScoringTeamSchema)
derived_output_schema()(FactBoxScoreFourFactorsTeamSchema)
derived_output_schema()(FactBoxScorePlayerTrackTeamSchema)
derived_output_schema()(FactBoxScoreDefensiveTeamSchema)
derived_output_schema()(FactBoxScoreHustlePlayerSchema)
derived_output_schema()(FactScoreboardWinProbabilitySchema)
derived_output_schema(literal_fields={"context_source"})(FactGameContextSchema)
derived_output_schema(literal_fields={"summary_type"})(FactBoxScoreSummaryV3Schema)
derived_output_schema(literal_fields={"detail_type"})(FactScoreboardDetailSchema)
derived_output_schema(literal_fields={"scoreboard_type"})(FactScoreboardV3Schema)
