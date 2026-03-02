from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingPlayByPlayV3Schema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    action_number: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.ACTION_NUMBER"),
            "description": ("Sequential action number within game"),
        },
    )
    clock: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.CLOCK"),
            "description": "Game clock time string",
        },
    )
    period: int = pa.Field(
        nullable=False,
        in_range={"min_value": 1, "max_value": 10},
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.PERIOD"),
            "description": "Game period number",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.TEAM_TRICODE"),
            "description": ("Three-letter team abbreviation code"),
        },
    )
    person_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.PERSON_ID"),
            "description": "Person identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.PLAYER_NAME"),
            "description": "Full player name",
        },
    )
    player_name_i: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.PLAYER_NAME_I"),
            "description": ("Player name in initial format"),
        },
    )
    x_legacy: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.X_LEGACY"),
            "description": ("Legacy x-coordinate of action"),
        },
    )
    y_legacy: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.Y_LEGACY"),
            "description": ("Legacy y-coordinate of action"),
        },
    )
    shot_distance: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.SHOT_DISTANCE"),
            "description": ("Distance of shot in feet"),
        },
    )
    shot_result: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.SHOT_RESULT"),
            "description": ("Result of shot attempt"),
        },
    )
    is_field_goal: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.IS_FIELD_GOAL"),
            "description": ("Flag indicating if action is a field goal attempt"),
        },
    )
    score_home: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.SCORE_HOME"),
            "description": "Home team score",
        },
    )
    score_away: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.SCORE_AWAY"),
            "description": "Away team score",
        },
    )
    points_total: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.POINTS_TOTAL"),
            "description": ("Total points scored on the play"),
        },
    )
    location: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.LOCATION"),
            "description": ("Home or away location indicator"),
        },
    )
    description: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.DESCRIPTION"),
            "description": ("Text description of the play"),
        },
    )
    action_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.ACTION_TYPE"),
            "description": ("Type of action performed"),
        },
    )
    sub_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.SUB_TYPE"),
            "description": ("Sub-type of action performed"),
        },
    )
    video_available: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.VIDEO_AVAILABLE"),
            "description": "Video availability flag",
        },
    )
    action_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV3.PlayByPlay.ACTION_ID"),
            "description": ("Unique action identifier"),
        },
    )


class StagingPlayByPlayV2Schema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    eventnum: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.EVENTNUM"),
            "description": "Event sequence number",
        },
    )
    eventmsgtype: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.EVENTMSGTYPE"),
            "description": ("Event message type code"),
        },
    )
    eventmsgactiontype: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.EVENTMSGACTIONTYPE"),
            "description": ("Event message action type code"),
        },
    )
    period: int = pa.Field(
        nullable=False,
        in_range={"min_value": 1, "max_value": 10},
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PERIOD"),
            "description": "Game period number",
        },
    )
    wctimestring: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.WCTIMESTRING"),
            "description": "Wall clock time string",
        },
    )
    pctimestring: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PCTIMESTRING"),
            "description": ("Period clock time string"),
        },
    )
    homedescription: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.HOMEDESCRIPTION"),
            "description": ("Play description for home team"),
        },
    )
    neutraldescription: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.NEUTRALDESCRIPTION"),
            "description": ("Neutral play description"),
        },
    )
    visitordescription: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.VISITORDESCRIPTION"),
            "description": ("Play description for visitor team"),
        },
    )
    score: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.SCORE"),
            "description": "Current game score",
        },
    )
    scoremargin: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.SCOREMARGIN"),
            "description": "Score margin value",
        },
    )
    person1type: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PERSON1TYPE"),
            "description": ("Person 1 type identifier"),
        },
    )
    player1_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER1_ID"),
            "description": ("Player 1 unique identifier"),
            "fk_ref": "staging_player.person_id",
        },
    )
    player1_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER1_NAME"),
            "description": "Player 1 full name",
        },
    )
    player1_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER1_TEAM_ID"),
            "description": ("Player 1 team identifier"),
            "fk_ref": "staging_team.team_id",
        },
    )
    player1_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER1_TEAM_CITY"),
            "description": "Player 1 team city",
        },
    )
    player1_team_nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER1_TEAM_NICKNAME"),
            "description": ("Player 1 team nickname"),
        },
    )
    player1_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER1_TEAM_ABBREVIATION"),
            "description": ("Player 1 team abbreviation"),
        },
    )
    person2type: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PERSON2TYPE"),
            "description": ("Person 2 type identifier"),
        },
    )
    player2_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER2_ID"),
            "description": ("Player 2 unique identifier"),
            "fk_ref": "staging_player.person_id",
        },
    )
    player2_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER2_NAME"),
            "description": "Player 2 full name",
        },
    )
    player2_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER2_TEAM_ID"),
            "description": ("Player 2 team identifier"),
            "fk_ref": "staging_team.team_id",
        },
    )
    player2_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER2_TEAM_CITY"),
            "description": "Player 2 team city",
        },
    )
    player2_team_nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER2_TEAM_NICKNAME"),
            "description": ("Player 2 team nickname"),
        },
    )
    player2_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER2_TEAM_ABBREVIATION"),
            "description": ("Player 2 team abbreviation"),
        },
    )
    person3type: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PERSON3TYPE"),
            "description": ("Person 3 type identifier"),
        },
    )
    player3_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER3_ID"),
            "description": ("Player 3 unique identifier"),
            "fk_ref": "staging_player.person_id",
        },
    )
    player3_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER3_NAME"),
            "description": "Player 3 full name",
        },
    )
    player3_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER3_TEAM_ID"),
            "description": ("Player 3 team identifier"),
            "fk_ref": "staging_team.team_id",
        },
    )
    player3_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER3_TEAM_CITY"),
            "description": "Player 3 team city",
        },
    )
    player3_team_nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER3_TEAM_NICKNAME"),
            "description": ("Player 3 team nickname"),
        },
    )
    player3_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.PLAYER3_TEAM_ABBREVIATION"),
            "description": ("Player 3 team abbreviation"),
        },
    )
    video_available_flag: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayByPlayV2.PlayByPlay.VIDEO_AVAILABLE_FLAG"),
            "description": "Video availability flag",
        },
    )
