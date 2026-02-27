from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawLeagueGameLogSchema(BaseSchema):
    season_id: str = pa.Field(
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.SEASON_ID"
            ),
            "description": "Season identifier",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.TEAM_ID"
            ),
            "description": "Unique team identifier",
        },
    )
    team_abbreviation: str = pa.Field(
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog"
                ".TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_name: str = pa.Field(
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.TEAM_NAME"
            ),
            "description": "Team name",
        },
    )
    game_id: str = pa.Field(
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    game_date: str = pa.Field(
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.GAME_DATE"
            ),
            "description": "Date of the game",
        },
    )
    matchup: str = pa.Field(
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.MATCHUP"
            ),
            "description": "Matchup string (e.g. LAL vs. BOS)",
        },
    )
    wl: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.WL",
            "description": "Win or loss indicator",
        },
    )
    w: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.W",
            "description": "Wins",
        },
    )
    l: int | None = pa.Field(  # noqa: E741
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.L",
            "description": "Losses",
        },
    )
    w_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.W_PCT"
            ),
            "description": "Win percentage",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.MIN",
            "description": "Minutes played",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.FGM",
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.FGA",
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.FG_PCT"
            ),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.FG3M"
            ),
            "description": "Three-point field goals made",
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.FG3A"
            ),
            "description": "Three-point field goals attempted",
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.FG3_PCT"
            ),
            "description": "Three-point field goal percentage",
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.FTM",
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.FTA",
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.FT_PCT"
            ),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.OREB"
            ),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.DREB"
            ),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.REB",
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.AST",
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.STL",
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.BLK",
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.TOV",
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.PF",
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameLog.LeagueGameLog.PTS",
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog.PLUS_MINUS"
            ),
            "description": "Plus-minus differential",
        },
    )
    video_available: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "LeagueGameLog.LeagueGameLog"
                ".VIDEO_AVAILABLE"
            ),
            "description": "Video availability flag",
        },
    )


class RawPlayerGameLogSchema(BaseSchema):
    season_id: str = pa.Field(
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.SEASON_ID"
            ),
            "description": "Season identifier",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    game_id: str = pa.Field(
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    game_date: str = pa.Field(
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.GAME_DATE"
            ),
            "description": "Date of the game",
        },
    )
    matchup: str = pa.Field(
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.MATCHUP"
            ),
            "description": "Matchup string (e.g. LAL vs. BOS)",
        },
    )
    wl: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.WL"
            ),
            "description": "Win or loss indicator",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.MIN"
            ),
            "description": "Minutes played",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.FGM"
            ),
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.FGA"
            ),
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.FG_PCT"
            ),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.FG3M"
            ),
            "description": "Three-point field goals made",
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.FG3A"
            ),
            "description": (
                "Three-point field goals attempted"
            ),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.FG3_PCT"
            ),
            "description": (
                "Three-point field goal percentage"
            ),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.FTM"
            ),
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.FTA"
            ),
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.FT_PCT"
            ),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.OREB"
            ),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.DREB"
            ),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.REB"
            ),
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.AST"
            ),
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.STL"
            ),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.BLK"
            ),
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.TOV"
            ),
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.PF"
            ),
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog.PTS"
            ),
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerGameLog.PlayerGameLog"
                ".PLUS_MINUS"
            ),
            "description": "Plus-minus differential",
        },
    )


class RawTeamGameLogSchema(BaseSchema):
    season_id: str = pa.Field(
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.SEASON_ID"
            ),
            "description": "Season identifier",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.TEAM_ID"
            ),
            "description": "Unique team identifier",
        },
    )
    team_abbreviation: str = pa.Field(
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog"
                ".TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_name: str = pa.Field(
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.TEAM_NAME"
            ),
            "description": "Team name",
        },
    )
    game_id: str = pa.Field(
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    game_date: str = pa.Field(
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.GAME_DATE"
            ),
            "description": "Date of the game",
        },
    )
    matchup: str = pa.Field(
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.MATCHUP"
            ),
            "description": "Matchup string (e.g. LAL vs. BOS)",
        },
    )
    wl: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.WL",
            "description": "Win or loss indicator",
        },
    )
    w: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.W",
            "description": "Wins",
        },
    )
    l: int | None = pa.Field(  # noqa: E741
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.L",
            "description": "Losses",
        },
    )
    w_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.W_PCT"
            ),
            "description": "Win percentage",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.MIN",
            "description": "Minutes played",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.FGM",
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.FGA",
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.FG_PCT"
            ),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.FG3M",
            "description": "Three-point field goals made",
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.FG3A",
            "description": (
                "Three-point field goals attempted"
            ),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.FG3_PCT"
            ),
            "description": (
                "Three-point field goal percentage"
            ),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.FTM",
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.FTA",
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.FT_PCT"
            ),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.OREB",
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.DREB",
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.REB",
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.AST",
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.STL",
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.BLK",
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.TOV",
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.PF",
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameLog.TeamGameLog.PTS",
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog.PLUS_MINUS"
            ),
            "description": "Plus-minus differential",
        },
    )
    video_available: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamGameLog.TeamGameLog"
                ".VIDEO_AVAILABLE"
            ),
            "description": "Video availability flag",
        },
    )
