from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawLeagueStandingsV3Schema(BaseSchema):
    league_id: str = pa.Field(
        metadata={
            "source": ("LeagueStandingsV3.Standings.LeagueID"),
            "description": "League identifier",
        },
    )
    season_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.SeasonID"),
            "description": "Season identifier",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TeamID"),
            "description": "Unique team identifier",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TeamCity"),
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TeamName"),
            "description": "Team name",
        },
    )
    team_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TeamSlug"),
            "description": "URL-friendly team slug",
        },
    )
    conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.Conference"),
            "description": "Conference name",
        },
    )
    conference_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ConferenceRecord"),
            "description": "Win-loss record in conference",
        },
    )
    playoff_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.PlayoffRank"),
            "description": "Playoff seeding rank",
        },
    )
    clinch_indicator: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ClinchIndicator"),
            "description": "Clinch status indicator",
        },
    )
    division: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.Division"),
            "description": "Division name",
        },
    )
    division_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.DivisionRecord"),
            "description": "Win-loss record in division",
        },
    )
    division_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.DivisionRank"),
            "description": "Rank within division",
        },
    )
    wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.WINS"),
            "description": "Total wins",
        },
    )
    losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.LOSSES"),
            "description": "Total losses",
        },
    )
    win_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.WinPCT"),
            "description": "Winning percentage",
        },
    )
    league_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.LeagueRank"),
            "description": "Overall league rank",
        },
    )
    record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.Record"),
            "description": "Overall win-loss record",
        },
    )
    home: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.HOME"),
            "description": "Home win-loss record",
        },
    )
    road: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ROAD"),
            "description": "Road win-loss record",
        },
    )
    l10: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.L10"),
            "description": "Record in last 10 games",
        },
    )
    long_win_streak: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.LongWinStreak"),
            "description": "Longest winning streak",
        },
    )
    long_loss_streak: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.LongLossStreak"),
            "description": "Longest losing streak",
        },
    )
    current_streak: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.CurrentStreak"),
            "description": "Current win or loss streak",
        },
    )
    ot_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.OT_Record"),
            "description": "Overtime win-loss record",
        },
    )
    three_pts_or_less: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ThreePTSOrLess"),
            "description": ("Record in games decided by 3 points or less"),
        },
    )
    ten_pts_or_more: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TenPTSOrMore"),
            "description": ("Record in games decided by 10 points or more"),
        },
    )
    conference_games_back: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ConferenceGamesBack"),
            "description": ("Games behind conference leader"),
        },
    )
    division_games_back: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.DivisionGamesBack"),
            "description": ("Games behind division leader"),
        },
    )
    clinched_conference_title: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ClinchedConferenceTitle"),
            "description": ("Whether team clinched conference"),
        },
    )
    clinched_division_title: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ClinchedDivisionTitle"),
            "description": ("Whether team clinched division"),
        },
    )
    clinched_playoff_birth: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ClinchedPlayoffBirth"),
            "description": ("Whether team clinched playoff berth"),
        },
    )
    eliminated_conference: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.EliminatedConference"),
            "description": ("Whether team eliminated from conference playoff contention"),
        },
    )
    pts_pg: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.PointsPG"),
            "description": "Points per game",
        },
    )
    opp_pts_pg: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.OppPointsPG"),
            "description": "Opponent points per game",
        },
    )
    diff_pts_pg: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.DiffPointsPG"),
            "description": ("Point differential per game"),
        },
    )


class RawPlayoffPictureSchema(BaseSchema):
    conference: str = pa.Field(
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.CONFERENCE"),
            "description": "Conference name",
        },
    )
    high_seed_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.HIGH_SEED_RANK"),
            "description": "Higher seed rank",
        },
    )
    high_seed_team: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.HIGH_SEED_TEAM"),
            "description": "Higher seed team name",
        },
    )
    high_seed_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.HIGH_SEED_TEAM_ID"),
            "description": ("Higher seed team identifier"),
        },
    )
    low_seed_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.LOW_SEED_RANK"),
            "description": "Lower seed rank",
        },
    )
    low_seed_team: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.LOW_SEED_TEAM"),
            "description": "Lower seed team name",
        },
    )
    low_seed_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.LOW_SEED_TEAM_ID"),
            "description": ("Lower seed team identifier"),
        },
    )
    high_seed_series_w: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.HIGH_SEED_SERIES_W"),
            "description": ("Higher seed series wins"),
        },
    )
    high_seed_series_l: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.HIGH_SEED_SERIES_L"),
            "description": ("Higher seed series losses"),
        },
    )
    high_seed_series_remaining_g: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.HIGH_SEED_SERIES_REMAINING_G"),
            "description": ("Remaining games in series"),
        },
    )
    high_seed_series_remaining_home_g: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.HIGH_SEED_SERIES_REMAINING_HOME_G"),
            "description": ("Remaining home games in series"),
        },
    )
    high_seed_series_remaining_away_g: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("PlayoffPicture.EastConfPlayoffPicture.HIGH_SEED_SERIES_REMAINING_AWAY_G"),
            "description": ("Remaining away games in series"),
        },
    )
