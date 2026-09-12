from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactLineupStatsSchema(BaseSchema):
    """Canonical lineup totals reconciled across the two lineup endpoints."""

    __consumer_metadata__ = {
        "grain": "lineup-team-season-season_type",
        "agent_intents": ["lineups", "lineup_stats", "lineup_efficiency"],
        "join_hints": {
            "dim_team": "team_id",
            "bridge_lineup_player": "group_id + team_id + season_year",
        },
    }

    group_set: str = pa.Field(
        metadata={
            "source": ("LeagueDashLineups.Lineups.GROUP_SET"),
            "description": ("Lineup group set label"),
        },
    )
    group_id: str = pa.Field(
        metadata={
            "source": ("LeagueDashLineups.Lineups.GROUP_ID"),
            "description": ("Lineup group identifier"),
        },
    )
    group_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashLineups.Lineups.GROUP_NAME"),
            "description": ("Lineup player names"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.GP"),
            "description": "Games played",
        },
    )
    w: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.W"),
            "description": "Wins",
        },
    )
    l: int | None = pa.Field(  # noqa: E741
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.L"),
            "description": "Losses",
        },
    )
    w_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueDashLineups.Lineups.W_PCT",
            "description": "Provider lineup win percentage",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.MIN"),
            "description": "Minutes played",
        },
    )
    fgm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.FGM"),
            "description": "Field goals made",
        },
    )
    fga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.FGA"),
            "description": ("Field goals attempted"),
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashLineups.Lineups.FG_PCT"),
            "description": ("Field goal percentage"),
        },
    )
    fg3m: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.FG3M"),
            "description": ("Three-pointers made"),
        },
    )
    fg3a: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.FG3A"),
            "description": ("Three-pointers attempted"),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashLineups.Lineups.FG3_PCT"),
            "description": ("Three-point percentage"),
        },
    )
    ftm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.FTM"),
            "description": "Free throws made",
        },
    )
    fta: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.FTA"),
            "description": ("Free throws attempted"),
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashLineups.Lineups.FT_PCT"),
            "description": ("Free throw percentage"),
        },
    )
    oreb: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.OREB"),
            "description": ("Offensive rebounds"),
        },
    )
    dreb: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.DREB"),
            "description": ("Defensive rebounds"),
        },
    )
    reb: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.REB"),
            "description": "Total rebounds",
        },
    )
    ast: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.AST"),
            "description": "Assists",
        },
    )
    tov: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.TOV"),
            "description": "Turnovers",
        },
    )
    stl: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.STL"),
            "description": "Steals",
        },
    )
    blk: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.BLK"),
            "description": "Blocks",
        },
    )
    blka: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "LeagueDashLineups.Lineups.BLKA",
            "description": "Lineup field-goal attempts blocked",
        },
    )
    pf: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "LeagueDashLineups.Lineups.PF",
            "description": "Lineup personal fouls",
        },
    )
    pfd: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "LeagueDashLineups.Lineups.PFD",
            "description": "Lineup personal fouls drawn",
        },
    )
    pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueDashLineups.Lineups.PTS"),
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueDashLineups.Lineups.PLUS_MINUS"),
            "description": "Plus-minus",
        },
    )
    net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueDashLineups.Lineups.NET_RATING",
            "description": (
                "Provider advanced net rating; null until the Advanced measure request "
                "surface is captured"
            ),
        },
    )
    season_type: str = pa.Field(
        metadata={
            "source": "request.season_type",
            "description": "Season type (Regular Season, Playoffs, etc.)",
        },
    )
    lineup_source: str = pa.Field(
        isin=["league", "team"],
        metadata={
            "source": "derived.lineup_source",
            "description": "Selected source after league-first exact reconciliation",
        },
    )
    lineup_source_count: int = pa.Field(
        ge=1,
        le=2,
        metadata={
            "source": "derived.lineup_source_count",
            "description": "Number of agreeing lineup endpoints observed",
        },
    )
    lineup_source_coverage: str = pa.Field(
        isin=["league", "team", "league+team"],
        metadata={
            "source": "derived.lineup_source_coverage",
            "description": "Ordered inventory of agreeing lineup endpoints",
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "request.season",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
