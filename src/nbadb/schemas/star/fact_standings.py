from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactStandingsSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TeamID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.Conference"),
            "description": ("Conference (East or West)"),
        },
    )
    division: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.Division"),
            "description": "Division name",
        },
    )
    conf_rank: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ConferenceRank"),
            "description": "Conference rank",
        },
    )
    div_rank: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.DivisionRank"),
            "description": "Division rank",
        },
    )
    wins: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.WINS"),
            "description": "Total wins",
        },
    )
    losses: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.LOSSES"),
            "description": "Total losses",
        },
    )
    win_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.WinPCT"),
            "description": "Win percentage",
        },
    )
    home_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.HOME"),
            "description": ("Home record (e.g. 30-11)"),
        },
    )
    road_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ROAD"),
            "description": ("Road record (e.g. 25-16)"),
        },
    )
    last_ten: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.L10"),
            "description": "Last 10 games record",
        },
    )
    current_streak: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.CurrentStreak"),
            "description": ("Current streak (e.g. W3, L2)"),
        },
    )
    games_back: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ConferenceGamesBack"),
            "description": ("Games behind conference leader"),
        },
    )
    clinch_indicator: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ClinchedPostSeason"),
            "description": ("Clinch indicator (e.g. p, x, z)"),
        },
    )
    pts_pg: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.PointsPG"),
            "description": ("Average points per game"),
        },
    )
    opp_pts_pg: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.OppPointsPG"),
            "description": ("Opponent points per game"),
        },
    )
    diff_pts_pg: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.DiffPointsPG"),
            "description": ("Point differential per game"),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.season_type",
            "description": ("Season type (Regular, Playoff)"),
        },
    )
