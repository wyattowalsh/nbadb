"""Pandera star-schema contracts for all agg_* aggregate output tables."""

from __future__ import annotations

import pandera.polars as pa
import polars as pl

from nbadb.schemas.base import BaseSchema, derived_output_schema


class AggAllTimeLeadersSchema(BaseSchema):
    """All-time career leaders with computed ranking columns."""

    player_id: int = pa.Field(
        gt=0,
        metadata={"description": "Unique player identifier"},
    )
    player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Player display name"}
    )
    pts: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Career total points"})
    ast: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Career total assists"}
    )
    reb: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Career total rebounds"}
    )
    pts_rank: int | None = pa.Field(
        nullable=True, ge=1, metadata={"description": "All-time points rank"}
    )
    ast_rank: int | None = pa.Field(
        nullable=True, ge=1, metadata={"description": "All-time assists rank"}
    )
    reb_rank: int | None = pa.Field(
        nullable=True, ge=1, metadata={"description": "All-time rebounds rank"}
    )


class AggClutchStatsSchema(BaseSchema):
    """Clutch-time statistics merged from dashboard and league clutch sources."""

    __consumer_metadata__ = {
        "grain": "player-season-clutch",
        "agent_intents": ["clutch", "clutch_performance"],
    }

    player_id: int | None = pa.Field(
        nullable=True, gt=0, metadata={"description": "Player identifier"}
    )
    season_year: str | None = pa.Field(
        nullable=True, metadata={"description": "Season year (e.g. 2024-25)"}
    )
    clutch_gp: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Games played in clutch time"}
    )
    clutch_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Minutes played in clutch time"}
    )
    clutch_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Points scored in clutch time"}
    )
    clutch_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Clutch field goal percentage"}
    )
    clutch_ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Clutch free throw percentage"}
    )
    league_clutch_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "League-wide clutch points"}
    )
    league_clutch_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "League-wide clutch FG percentage"}
    )


class AggGameTotalsSchema(BaseSchema):
    """Per-game aggregate with home/away stats side-by-side."""

    game_id: str = pa.Field(
        unique=True,
        metadata={"description": "Unique NBA game identifier"},
    )
    game_date: str = pa.Field(metadata={"description": "Date the game was played"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"},
    )
    home_team_id: int = pa.Field(gt=0, metadata={"description": "Home team identifier"})
    away_team_id: int = pa.Field(gt=0, metadata={"description": "Away team identifier"})
    home_pts: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Home team points"}
    )
    away_pts: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Away team points"}
    )
    total_pts: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Combined game points (home + away)"}
    )
    home_reb: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Home team total rebounds"}
    )
    away_reb: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Away team total rebounds"}
    )
    home_ast: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Home team assists"}
    )
    away_ast: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Away team assists"}
    )
    home_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Home FGM divided by home FGA when FGA is positive"},
    )
    away_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Away FGM divided by away FGA when FGA is positive"},
    )

    @pa.dataframe_check
    @classmethod
    def structural_identity_is_valid(cls, data: pa.PolarsData) -> pl.LazyFrame:
        """Validate identity shape without asserting derived arithmetic equality."""

        del cls
        return data.lazyframe.select(
            (
                pl.col("game_id").str.strip_chars().str.len_chars().gt(0)
                & pl.col("game_date").str.strip_chars().str.len_chars().gt(0)
                & pl.col("season_year").str.strip_chars().str.len_chars().gt(0)
                & (
                    pl.col("season_type").is_null()
                    | pl.col("season_type").str.strip_chars().str.len_chars().gt(0)
                )
                & pl.col("home_team_id").ne(pl.col("away_team_id"))
                & pl.col("game_id").n_unique().eq(pl.len())
            ).alias("structural_identity_is_valid")
        )


class AggLeagueLeadersSchema(BaseSchema):
    """Per-season player rankings derived from agg_player_season."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    avg_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average points per game"}
    )
    avg_reb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average rebounds per game"}
    )
    avg_ast: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average assists per game"}
    )
    avg_stl: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average steals per game"}
    )
    avg_blk: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average blocks per game"}
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "FGM divided by FGA from season totals"},
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "FG3M divided by FG3A from season totals"},
    )
    ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Free throw percentage"}
    )
    pts_rank: int = pa.Field(ge=1, metadata={"description": "Points per game rank"})
    reb_rank: int = pa.Field(ge=1, metadata={"description": "Rebounds per game rank"})
    ast_rank: int = pa.Field(ge=1, metadata={"description": "Assists per game rank"})
    stl_rank: int = pa.Field(ge=1, metadata={"description": "Steals per game rank"})
    blk_rank: int = pa.Field(ge=1, metadata={"description": "Blocks per game rank"})


class AggLineupEfficiencySchema(BaseSchema):
    """Exposure-correct lineup totals, rates, and coverage evidence."""

    __consumer_metadata__ = {
        "grain": "lineup-team-season-season_type",
        "agent_intents": ["lineups", "lineup_efficiency", "lineup_shooting"],
        "join_hints": {
            "dim_team": "team_id",
            "bridge_lineup_player": "group_id + team_id + season_year",
        },
    }

    group_id: str = pa.Field(metadata={"description": "Provider lineup group identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    lineup_source: str = pa.Field(
        isin=["league", "team"],
        metadata={"description": "Selected league-first canonical source"},
    )
    lineup_source_count: int = pa.Field(
        ge=1,
        le=2,
        metadata={"description": "Number of agreeing lineup endpoints observed"},
    )
    lineup_source_coverage: str = pa.Field(
        isin=["league", "team", "league+team"],
        metadata={"description": "Ordered inventory of agreeing lineup endpoints"},
    )
    canonical_observation_count: int = pa.Field(
        ge=1,
        le=1,
        metadata={"description": "One exact canonical fact after exact deduplication"},
    )
    gp_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact has games played"}
    )
    minutes_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact has lineup minutes"}
    )
    estimated_possessions_covered_observations: int = pa.Field(
        ge=0,
        le=1,
        metadata={"description": "Canonical fact has FGA, FTA, OREB, and TOV"},
    )
    win_pct_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports W divided by GP"}
    )
    fg_pct_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports FGM divided by FGA"}
    )
    fg3_pct_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports FG3M divided by FG3A"}
    )
    ft_pct_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports FTM divided by FTA"}
    )
    efg_pct_covered_observations: int = pa.Field(
        ge=0,
        le=1,
        metadata={"description": "Canonical fact supports derived effective FG percentage"},
    )
    ts_pct_covered_observations: int = pa.Field(
        ge=0,
        le=1,
        metadata={"description": "Canonical fact supports derived true-shooting percentage"},
    )
    fg3a_per_fga_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports FG3A divided by FGA"}
    )
    fta_per_fga_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports FTA divided by FGA"}
    )
    ast_tov_ratio_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports AST divided by TOV"}
    )
    pts_per48_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports points per 48"}
    )
    reb_per48_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports rebounds per 48"}
    )
    ast_per48_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports assists per 48"}
    )
    tov_per48_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports turnovers per 48"}
    )
    stl_per48_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports steals per 48"}
    )
    blk_per48_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports blocks per 48"}
    )
    plus_minus_per48_covered_observations: int = pa.Field(
        ge=0, le=1, metadata={"description": "Canonical fact supports plus-minus per 48"}
    )
    estimated_off_rating_covered_observations: int = pa.Field(
        ge=0,
        le=1,
        metadata={"description": "Canonical fact supports estimated offensive rating"},
    )
    estimated_def_rating_covered_observations: int = pa.Field(
        ge=0,
        le=1,
        metadata={"description": "Canonical fact supports estimated defensive rating"},
    )
    estimated_net_rating_covered_observations: int = pa.Field(
        ge=0,
        le=1,
        metadata={"description": "Canonical fact supports estimated net rating"},
    )
    total_gp: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Reported games played"}
    )
    total_w: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Reported lineup wins"}
    )
    total_l: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Reported lineup losses"}
    )
    total_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Reported lineup minutes"}
    )
    total_fgm: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Field goals made"}
    )
    total_fga: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Field goals attempted"}
    )
    total_fg3m: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Three-point field goals made"}
    )
    total_fg3a: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Three-point field goals attempted"}
    )
    total_ftm: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Free throws made"}
    )
    total_fta: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Free throws attempted"}
    )
    total_oreb: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Offensive rebounds"}
    )
    total_dreb: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Defensive rebounds"}
    )
    total_reb: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Total rebounds"}
    )
    total_ast: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Assists"})
    total_tov: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Turnovers"})
    total_stl: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Steals"})
    total_blk: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Blocks"})
    total_blka: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Field-goal attempts blocked"}
    )
    total_pf: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Personal fouls"})
    total_pfd: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Personal fouls drawn"}
    )
    total_pts: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Points scored"})
    total_plus_minus: float | None = pa.Field(
        nullable=True, metadata={"description": "Point differential while the lineup played"}
    )
    win_pct: float | None = pa.Field(
        nullable=True, ge=0.0, le=1.0, metadata={"description": "Wins divided by decisions"}
    )
    fg_pct: float | None = pa.Field(
        nullable=True, ge=0.0, le=1.0, metadata={"description": "FGM divided by FGA"}
    )
    fg3_pct: float | None = pa.Field(
        nullable=True, ge=0.0, le=1.0, metadata={"description": "FG3M divided by FG3A"}
    )
    ft_pct: float | None = pa.Field(
        nullable=True, ge=0.0, le=1.0, metadata={"description": "FTM divided by FTA"}
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Effective field-goal percentage from summed makes/attempts"},
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "True-shooting percentage using the standard 0.44 FTA factor"},
    )
    fg3a_per_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Three-point attempts divided by field-goal attempts"},
    )
    fta_per_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Free-throw attempts divided by field-goal attempts"},
    )
    ast_tov_ratio: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Assists divided by turnovers"}
    )
    estimated_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "FGA + 0.44*FTA - OREB + TOV possession estimate"},
    )
    pts_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Points per 48 lineup minutes"}
    )
    reb_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Rebounds per 48 lineup minutes"}
    )
    ast_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Assists per 48 lineup minutes"}
    )
    tov_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Turnovers per 48 lineup minutes"}
    )
    stl_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Steals per 48 lineup minutes"}
    )
    blk_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Blocks per 48 lineup minutes"}
    )
    plus_minus_per48: float | None = pa.Field(
        nullable=True, metadata={"description": "Point differential per 48 lineup minutes"}
    )
    estimated_off_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Points scored per 100 estimated possessions"},
    )
    estimated_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Opponent points per 100 estimated possessions"},
    )
    estimated_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Point differential per 100 estimated possessions"},
    )

    @pa.dataframe_check
    @classmethod
    def source_tuple_is_exact(cls, data: pa.PolarsData) -> pl.LazyFrame:
        """Admit only the three exact tuples emitted by fact-lineup reconciliation."""

        del cls
        return data.lazyframe.select(
            (
                (
                    pl.col("lineup_source").eq("league")
                    & pl.col("lineup_source_count").eq(1)
                    & pl.col("lineup_source_coverage").eq("league")
                )
                | (
                    pl.col("lineup_source").eq("team")
                    & pl.col("lineup_source_count").eq(1)
                    & pl.col("lineup_source_coverage").eq("team")
                )
                | (
                    pl.col("lineup_source").eq("league")
                    & pl.col("lineup_source_count").eq(2)
                    & pl.col("lineup_source_coverage").eq("league+team")
                )
            ).alias("source_tuple_is_exact")
        )

    @pa.dataframe_check
    @classmethod
    def structural_keys_are_nonblank_and_unique(
        cls,
        data: pa.PolarsData,
    ) -> pl.LazyFrame:
        """Keep uniqueness a structural contract, not an arithmetic assertion."""

        del cls
        keys = ("group_id", "team_id", "season_year", "season_type")
        return data.lazyframe.select(
            (
                pl.col("group_id").str.strip_chars().str.len_chars().gt(0)
                & pl.col("season_year").str.strip_chars().str.len_chars().gt(0)
                & pl.col("season_type").str.strip_chars().str.len_chars().gt(0)
                & pl.struct(keys).n_unique().eq(pl.len())
            ).alias("structural_keys_are_nonblank_and_unique")
        )

    @pa.dataframe_check
    @classmethod
    def coverage_is_bounded_by_canonical_observation(
        cls,
        data: pa.PolarsData,
    ) -> pl.LazyFrame:
        del cls
        coverage_columns = (
            "gp_covered_observations",
            "minutes_covered_observations",
            "estimated_possessions_covered_observations",
            "win_pct_covered_observations",
            "fg_pct_covered_observations",
            "fg3_pct_covered_observations",
            "ft_pct_covered_observations",
            "efg_pct_covered_observations",
            "ts_pct_covered_observations",
            "fg3a_per_fga_covered_observations",
            "fta_per_fga_covered_observations",
            "ast_tov_ratio_covered_observations",
            "pts_per48_covered_observations",
            "reb_per48_covered_observations",
            "ast_per48_covered_observations",
            "tov_per48_covered_observations",
            "stl_per48_covered_observations",
            "blk_per48_covered_observations",
            "plus_minus_per48_covered_observations",
            "estimated_off_rating_covered_observations",
            "estimated_def_rating_covered_observations",
            "estimated_net_rating_covered_observations",
        )
        return data.lazyframe.select(
            pl.all_horizontal(
                [
                    pl.col(column).le(pl.col("canonical_observation_count"))
                    for column in coverage_columns
                ]
            ).alias("coverage_is_bounded_by_canonical_observation")
        )

    @pa.dataframe_check
    @classmethod
    def metric_nullability_matches_local_coverage(
        cls,
        data: pa.PolarsData,
    ) -> pl.LazyFrame:
        """Bind each output only to its own exact 0/1 coverage witness."""

        del cls
        coverage_metric_pairs = (
            ("gp_covered_observations", "total_gp"),
            ("minutes_covered_observations", "total_min"),
            ("estimated_possessions_covered_observations", "estimated_possessions"),
            ("win_pct_covered_observations", "win_pct"),
            ("fg_pct_covered_observations", "fg_pct"),
            ("fg3_pct_covered_observations", "fg3_pct"),
            ("ft_pct_covered_observations", "ft_pct"),
            ("efg_pct_covered_observations", "efg_pct"),
            ("ts_pct_covered_observations", "ts_pct"),
            ("fg3a_per_fga_covered_observations", "fg3a_per_fga"),
            ("fta_per_fga_covered_observations", "fta_per_fga"),
            ("ast_tov_ratio_covered_observations", "ast_tov_ratio"),
            ("pts_per48_covered_observations", "pts_per48"),
            ("reb_per48_covered_observations", "reb_per48"),
            ("ast_per48_covered_observations", "ast_per48"),
            ("tov_per48_covered_observations", "tov_per48"),
            ("stl_per48_covered_observations", "stl_per48"),
            ("blk_per48_covered_observations", "blk_per48"),
            ("plus_minus_per48_covered_observations", "plus_minus_per48"),
            ("estimated_off_rating_covered_observations", "estimated_off_rating"),
            ("estimated_def_rating_covered_observations", "estimated_def_rating"),
            ("estimated_net_rating_covered_observations", "estimated_net_rating"),
        )
        checks = [
            (
                (pl.col(coverage).eq(0) & pl.col(metric).is_null())
                | (pl.col(coverage).eq(1) & pl.col(metric).is_not_null())
            )
            for coverage, metric in coverage_metric_pairs
        ]
        return data.lazyframe.select(
            pl.all_horizontal(checks).alias("metric_nullability_matches_local_coverage")
        )

    @pa.dataframe_check
    @classmethod
    def nullable_float_outputs_are_finite(
        cls,
        data: pa.PolarsData,
    ) -> pl.LazyFrame:
        del cls
        float_columns = (
            "total_min",
            "total_plus_minus",
            "win_pct",
            "fg_pct",
            "fg3_pct",
            "ft_pct",
            "efg_pct",
            "ts_pct",
            "fg3a_per_fga",
            "fta_per_fga",
            "ast_tov_ratio",
            "estimated_possessions",
            "pts_per48",
            "reb_per48",
            "ast_per48",
            "tov_per48",
            "stl_per48",
            "blk_per48",
            "plus_minus_per48",
            "estimated_off_rating",
            "estimated_def_rating",
            "estimated_net_rating",
        )
        return data.lazyframe.select(
            pl.all_horizontal(
                [pl.col(column).is_null() | pl.col(column).is_finite() for column in float_columns]
            ).alias("nullable_float_outputs_are_finite")
        )


class AggPlayerBioSchema(BaseSchema):
    """Player biographical and physical information from league bio stats."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Player display name"}
    )
    team_id: int | None = pa.Field(nullable=True, gt=0, metadata={"description": "Team identifier"})
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    age: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Player age"})
    player_height: str | None = pa.Field(
        nullable=True, metadata={"description": "Player height as string (e.g. 6-8)"}
    )
    player_height_inches: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Player height in inches"}
    )
    player_weight: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Player weight"}
    )
    college: str | None = pa.Field(nullable=True, metadata={"description": "College attended"})
    country: str | None = pa.Field(nullable=True, metadata={"description": "Country of origin"})
    draft_year: str | None = pa.Field(nullable=True, metadata={"description": "Year drafted"})
    draft_round: str | None = pa.Field(nullable=True, metadata={"description": "Round drafted"})
    draft_number: str | None = pa.Field(
        nullable=True, metadata={"description": "Overall draft pick number"}
    )
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    pts: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Points per game"})
    reb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Rebounds per game"}
    )
    ast: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Assists per game"}
    )
    net_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Net rating (offensive - defensive)"}
    )
    oreb_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Offensive rebound percentage"}
    )
    dreb_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Defensive rebound percentage"}
    )
    usg_pct: float | None = pa.Field(nullable=True, metadata={"description": "Usage percentage"})
    ts_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "True shooting percentage"}
    )
    ast_pct: float | None = pa.Field(nullable=True, metadata={"description": "Assist percentage"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )


class AggPlayerCareerSchema(BaseSchema):
    """Career-aggregated stats per player across regular seasons."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    career_gp: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Career games played"}
    )
    career_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career total minutes"}
    )
    career_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career total points"}
    )
    career_ppg: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career points per game"}
    )
    career_rpg: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career rebounds per game"}
    )
    career_apg: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career assists per game"}
    )
    career_spg: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career steals per game"}
    )
    career_bpg: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career blocks per game"}
    )
    career_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Career field goal percentage"}
    )
    career_fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Career three-point percentage"}
    )
    career_ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Career free throw percentage"}
    )
    first_season: str | None = pa.Field(
        nullable=True, metadata={"description": "First season played"}
    )
    last_season: str | None = pa.Field(
        nullable=True, metadata={"description": "Last season played"}
    )
    seasons_played: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Total seasons played"}
    )


class AggPlayerRollingSchema(BaseSchema):
    """Past-only player averages within one team, season, and season type."""

    game_id: str = pa.Field(metadata={"description": "Unique game identifier"})
    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    game_date: str = pa.Field(metadata={"description": "Game date"})
    pts_roll5: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Mean points over up to 5 strictly prior games"},
    )
    reb_roll5: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Mean rebounds over up to 5 strictly prior games"},
    )
    ast_roll5: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Mean assists over up to 5 strictly prior games"},
    )
    pts_roll10: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Mean points over up to 10 strictly prior games"},
    )
    reb_roll10: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Mean rebounds over up to 10 strictly prior games"},
    )
    ast_roll10: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Mean assists over up to 10 strictly prior games"},
    )
    pts_roll20: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Mean points over up to 20 strictly prior games"},
    )
    reb_roll20: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Mean rebounds over up to 20 strictly prior games"},
    )
    ast_roll20: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Mean assists over up to 20 strictly prior games"},
    )


class AggPlayerSeasonAdvancedSchema(BaseSchema):
    """Possession-weighted provider metrics at player-team-season-type grain."""

    __consumer_metadata__ = {
        "grain": "player-team-season-season_type",
        "agent_intents": ["player_advanced", "player_efficiency", "player_season"],
        "join_hints": {"dim_player": "player_id", "dim_team": "team_id"},
        "metric_provenance": {
            "avg_pace": "provider pace weighted by positive player minutes",
            "avg_*": "provider metric weighted by positive provider possessions",
        },
    }

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    minutes_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games with nonnegative parsed player minutes"}
    )
    total_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Covered player minutes"}
    )
    possession_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games with nonnegative provider possessions"}
    )
    total_possessions: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Provider possessions across games"}
    )
    pace_covered_games: int = pa.Field(
        ge=0,
        metadata={"description": "Games with provider pace and positive minutes"},
    )
    pace_covered_minutes: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Player minutes supporting minute-weighted provider pace"},
    )
    off_rating_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider offensive rating"}
    )
    off_rating_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider offensive rating"},
    )
    avg_off_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider offensive rating"},
    )
    def_rating_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider defensive rating"}
    )
    def_rating_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider defensive rating"},
    )
    avg_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider defensive rating"},
    )
    net_rating_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider net rating"}
    )
    net_rating_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider net rating"},
    )
    avg_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider net rating"},
    )
    ts_pct_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider true-shooting percentage"}
    )
    ts_pct_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider true-shooting percentage"},
    )
    avg_ts_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider true-shooting percentage"},
    )
    usg_pct_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider usage percentage"}
    )
    usg_pct_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider usage percentage"},
    )
    avg_usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider usage percentage"},
    )
    efg_pct_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider effective FG%"}
    )
    efg_pct_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider effective FG%"},
    )
    avg_efg_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider effective FG%"},
    )
    ast_pct_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider assist percentage"}
    )
    ast_pct_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider assist percentage"},
    )
    avg_ast_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider assist percentage"},
    )
    ast_ratio_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider assist ratio"}
    )
    ast_ratio_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider assist ratio"},
    )
    avg_ast_ratio: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider assist ratio"},
    )
    oreb_pct_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider offensive rebound rate"}
    )
    oreb_pct_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider offensive rebound rate"},
    )
    avg_oreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider offensive rebound percentage"},
    )
    dreb_pct_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider defensive rebound rate"}
    )
    dreb_pct_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider defensive rebound rate"},
    )
    avg_dreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider defensive rebound percentage"},
    )
    reb_pct_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider total rebound rate"}
    )
    reb_pct_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider total rebound rate"},
    )
    avg_reb_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider total rebound percentage"},
    )
    tov_pct_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider turnover percentage"}
    )
    tov_pct_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider turnover percentage"},
    )
    avg_tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider turnover percentage"},
    )
    avg_pace: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Minute-weighted provider pace"},
    )
    pie_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider player impact estimate"}
    )
    pie_covered_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider player impact estimate"},
    )
    avg_pie: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider player impact estimate"},
    )
    advanced_metric_source: str = pa.Field(
        isin=["provider_possession_weighted"],
        metadata={"description": "Provenance and aggregation rule for provider metrics"},
    )
    pace_source: str = pa.Field(
        isin=["provider_minute_weighted"],
        metadata={"description": "Provenance and aggregation rule for pace"},
    )


class AggPlayerSeasonSchema(BaseSchema):
    """Player season aggregates joining traditional and advanced game logs."""

    __consumer_metadata__ = {
        "grain": "player-team-season-season_type",
        "agent_intents": ["scoring", "assists", "rebounds", "player_season"],
        "scd2_notes": "Join dim_player with is_current = TRUE for current player names.",
        "join_hints": {"dim_player": "player_id + is_current = TRUE"},
        "metric_provenance": {
            "shooting_efficiency": "derived from summed traditional box-score counts",
            "advanced_metrics": "provider values weighted by positive possessions",
        },
    }

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    minutes_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games with reported player minutes"}
    )
    scoring_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games with reported player points"}
    )
    rebounding_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games with reported player rebounds"}
    )
    playmaking_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games with reported player assists"}
    )
    shooting_covered_games: int = pa.Field(
        ge=0,
        metadata={"description": "Games with complete shooting makes, attempts, and points"},
    )
    advanced_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Traditional games matched to an advanced fact row"}
    )
    advanced_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Positive provider possessions across matched advanced games"},
    )
    total_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total minutes played"}
    )
    avg_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average minutes per game"}
    )
    total_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total points scored"}
    )
    avg_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average points per game"}
    )
    total_reb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total rebounds"}
    )
    avg_reb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average rebounds per game"}
    )
    total_ast: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total assists"}
    )
    avg_ast: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average assists per game"}
    )
    total_stl: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total steals"}
    )
    avg_stl: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average steals per game"}
    )
    total_blk: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total blocks"}
    )
    avg_blk: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average blocks per game"}
    )
    total_tov: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total turnovers"}
    )
    avg_tov: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average turnovers per game"}
    )
    total_oreb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total offensive rebounds"}
    )
    total_dreb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total defensive rebounds"}
    )
    total_pf: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total personal fouls"}
    )
    total_plus_minus: float | None = pa.Field(
        nullable=True, metadata={"description": "Total provider plus-minus"}
    )
    total_fgm: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total field goals made"}
    )
    total_fga: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total field goals attempted"}
    )
    fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Field goal percentage"}
    )
    total_fg3m: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total three-pointers made"}
    )
    total_fg3a: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total three-pointers attempted"}
    )
    fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goal percentage"}
    )
    total_ftm: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total free throws made"}
    )
    total_fta: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total free throws attempted"}
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "FTM divided by FTA from season totals"},
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Effective FG% derived from summed FGM, FG3M, and FGA"},
    )
    three_point_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Summed three-point attempts divided by summed FGA"},
    )
    free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Summed free-throw attempts divided by summed FGA"},
    )
    ast_tov_ratio: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Summed assists divided by summed turnovers"},
    )
    rating_covered_games: int = pa.Field(
        ge=0,
        metadata={"description": "Games with positive possessions and all three ratings"},
    )
    rating_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting the provider rating estimates"},
    )
    avg_off_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider offensive rating"},
    )
    avg_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider defensive rating"},
    )
    avg_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider net rating"},
    )
    avg_ts_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "True-shooting percentage derived from season totals"},
    )
    provider_ts_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider TS% aggregation"}
    )
    provider_ts_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider TS% aggregation"},
    )
    provider_avg_ts_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider TS% retained separately"},
    )
    usage_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider usage aggregation"}
    )
    usage_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider usage aggregation"},
    )
    avg_usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider usage percentage"},
    )
    pie_covered_games: int = pa.Field(
        ge=0, metadata={"description": "Games supporting provider PIE aggregation"}
    )
    pie_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting provider PIE aggregation"},
    )
    avg_pie: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted provider player impact estimate"},
    )
    shooting_efficiency_source: str = pa.Field(
        isin=["derived_traditional_totals"],
        metadata={"description": "Provenance for shooting efficiency outputs"},
    )
    advanced_metric_weight: str = pa.Field(
        isin=["provider_possessions"],
        metadata={"description": "Exposure basis for provider-only advanced outputs"},
    )


class AggPlayerSeasonPer36Schema(BaseSchema):
    """Per-36-minute rates derived from agg_player_season."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    avg_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average minutes per game"}
    )
    pts_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Points per 36 minutes"}
    )
    reb_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Rebounds per 36 minutes"}
    )
    ast_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Assists per 36 minutes"}
    )
    stl_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Steals per 36 minutes"}
    )
    blk_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Blocks per 36 minutes"}
    )
    tov_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Turnovers per 36 minutes"}
    )


class AggPlayerSeasonPer48Schema(BaseSchema):
    """Per-48-minute rates derived from agg_player_season."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    avg_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average minutes per game"}
    )
    pts_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Points per 48 minutes"}
    )
    reb_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Rebounds per 48 minutes"}
    )
    ast_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Assists per 48 minutes"}
    )
    stl_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Steals per 48 minutes"}
    )
    blk_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Blocks per 48 minutes"}
    )
    tov_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Turnovers per 48 minutes"}
    )


class AggShotLocationSeasonSchema(BaseSchema):
    """Shot-location season stats with per-season FGM ranking."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    fgm: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Field goals made"})
    season_fgm_rank: int = pa.Field(ge=1, metadata={"description": "Season FGM rank"})


class AggShotZonesSchema(BaseSchema):
    """Event-identity-backed player shot-zone observations by season scope."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    shot_zone_basic: str = pa.Field(metadata={"description": "Provider basic shot-zone value"})
    shot_zone_area: str = pa.Field(metadata={"description": "Provider directional shot-zone value"})
    shot_zone_range: str = pa.Field(metadata={"description": "Provider shot-zone range value"})
    shot_event_count: int = pa.Field(
        ge=1,
        metadata={"description": "Canonical events admitted by provider event identity"},
    )
    outcome_observed_attempt_count: int = pa.Field(
        ge=0,
        metadata={"description": "Admitted events with a reported made-or-missed outcome"},
    )
    made_shot_count_of_observed_outcomes: int = pa.Field(
        ge=0,
        metadata={"description": "Reported made shots among outcome-observed events"},
    )
    fg_pct_of_observed_outcomes: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Made-shot share among outcome-observed events"},
    )
    distance_observed_attempt_count: int = pa.Field(
        ge=0,
        metadata={"description": "Admitted events with a reported shot distance"},
    )
    mean_observed_shot_distance: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Mean provider distance over distance-observed events"},
    )

    @pa.dataframe_check
    @classmethod
    def structural_keys_are_nonblank_and_unique(
        cls,
        data: pa.PolarsData,
    ) -> pl.LazyFrame:
        del cls
        keys = (
            "player_id",
            "season_year",
            "season_type",
            "shot_zone_basic",
            "shot_zone_area",
            "shot_zone_range",
        )
        return data.lazyframe.select(
            (
                pl.all_horizontal(
                    [pl.col(column).str.strip_chars().str.len_chars().gt(0) for column in keys[1:]]
                )
                & pl.struct(keys).n_unique().eq(pl.len())
            ).alias("structural_keys_are_nonblank_and_unique")
        )

    @pa.dataframe_check
    @classmethod
    def coverage_counts_are_coherent(cls, data: pa.PolarsData) -> pl.LazyFrame:
        del cls
        return data.lazyframe.select(
            (
                pl.col("outcome_observed_attempt_count").le(pl.col("shot_event_count"))
                & pl.col("made_shot_count_of_observed_outcomes").le(
                    pl.col("outcome_observed_attempt_count")
                )
                & pl.col("distance_observed_attempt_count").le(pl.col("shot_event_count"))
            ).alias("coverage_counts_are_coherent")
        )

    @pa.dataframe_check
    @classmethod
    def metric_nullability_matches_coverage(
        cls,
        data: pa.PolarsData,
    ) -> pl.LazyFrame:
        del cls
        return data.lazyframe.select(
            (
                (
                    (
                        pl.col("outcome_observed_attempt_count").eq(0)
                        & pl.col("fg_pct_of_observed_outcomes").is_null()
                    )
                    | (
                        pl.col("outcome_observed_attempt_count").gt(0)
                        & pl.col("fg_pct_of_observed_outcomes").is_not_null()
                    )
                )
                & (
                    (
                        pl.col("distance_observed_attempt_count").eq(0)
                        & pl.col("mean_observed_shot_distance").is_null()
                    )
                    | (
                        pl.col("distance_observed_attempt_count").gt(0)
                        & pl.col("mean_observed_shot_distance").is_not_null()
                    )
                )
            ).alias("metric_nullability_matches_coverage")
        )

    @pa.dataframe_check
    @classmethod
    def nullable_metrics_are_finite(cls, data: pa.PolarsData) -> pl.LazyFrame:
        del cls
        return data.lazyframe.select(
            (
                (
                    pl.col("fg_pct_of_observed_outcomes").is_null()
                    | pl.col("fg_pct_of_observed_outcomes").is_finite()
                )
                & (
                    pl.col("mean_observed_shot_distance").is_null()
                    | pl.col("mean_observed_shot_distance").is_finite()
                )
            ).alias("nullable_metrics_are_finite")
        )


class AggTeamDefenseSchema(BaseSchema):
    """Observed-game team defense coverage, totals, and unweighted means."""

    team_id: int = pa.Field(gt=0, metadata={"description": "Unique team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    observed_game_count: int = pa.Field(
        ge=0, metadata={"description": "Advanced-source game-team observations"}
    )
    def_rating_coverage_game_count: int = pa.Field(
        ge=0, metadata={"description": "Observed games with defensive rating"}
    )
    mean_observed_game_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Unweighted mean defensive rating over covered games"},
    )
    net_rating_coverage_game_count: int = pa.Field(
        ge=0, metadata={"description": "Observed games with net rating"}
    )
    mean_observed_game_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Unweighted mean net rating over covered games"},
    )
    four_factors_observed_game_count: int = pa.Field(
        ge=0, metadata={"description": "Observed games with a four-factors source row"}
    )
    opp_effective_field_goal_percentage_coverage_game_count: int = pa.Field(
        ge=0,
        metadata={"description": "Four-factors games with opponent effective field goal rate"},
    )
    mean_observed_game_opp_effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Unweighted observed-game opponent effective field goal rate"},
    )
    opp_free_throw_attempt_rate_coverage_game_count: int = pa.Field(
        ge=0,
        metadata={"description": "Four-factors games with opponent free throw attempt rate"},
    )
    mean_observed_game_opp_free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Unweighted observed-game opponent free throw attempt rate"},
    )
    opp_team_turnover_percentage_coverage_game_count: int = pa.Field(
        ge=0,
        metadata={"description": "Four-factors games with opponent turnover rate"},
    )
    mean_observed_game_opp_team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Unweighted observed-game opponent turnover rate"},
    )
    opp_offensive_rebound_percentage_coverage_game_count: int = pa.Field(
        ge=0,
        metadata={"description": "Four-factors games with opponent offensive rebound rate"},
    )
    mean_observed_game_opp_offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Unweighted observed-game opponent offensive rebound rate"},
    )
    hustle_observed_game_count: int = pa.Field(
        ge=0, metadata={"description": "Observed games with a hustle source row"}
    )
    contested_shots_coverage_game_count: int = pa.Field(
        ge=0, metadata={"description": "Hustle games with contested shots"}
    )
    total_observed_game_contested_shots: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total covered-game contested shots"}
    )
    mean_observed_game_contested_shots: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Unweighted mean covered-game contested shots"},
    )
    deflections_coverage_game_count: int = pa.Field(
        ge=0, metadata={"description": "Hustle games with deflections"}
    )
    total_observed_game_deflections: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total covered-game deflections"}
    )
    mean_observed_game_deflections: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Unweighted mean covered-game deflections"},
    )
    loose_balls_recovered_coverage_game_count: int = pa.Field(
        ge=0, metadata={"description": "Hustle games with loose balls recovered"}
    )
    total_observed_game_loose_balls_recovered: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Total covered-game loose balls recovered"},
    )
    mean_observed_game_loose_balls_recovered: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Unweighted mean covered-game loose balls recovered"},
    )
    charges_drawn_coverage_game_count: int = pa.Field(
        ge=0, metadata={"description": "Hustle games with charges drawn"}
    )
    total_observed_game_charges_drawn: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total covered-game charges drawn"}
    )
    mean_observed_game_charges_drawn: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Unweighted mean covered-game charges drawn"},
    )
    screen_assists_coverage_game_count: int = pa.Field(
        ge=0, metadata={"description": "Hustle games with screen assists"}
    )
    total_observed_game_screen_assists: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total covered-game screen assists"}
    )
    mean_observed_game_screen_assists: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Unweighted mean covered-game screen assists"},
    )

    @pa.dataframe_check
    @classmethod
    def coverage_counts_do_not_exceed_denominators(
        cls,
        data: pa.PolarsData,
    ) -> pl.LazyFrame:
        del cls
        return data.lazyframe.select(
            (
                (pl.col("def_rating_coverage_game_count") <= pl.col("observed_game_count"))
                & (pl.col("net_rating_coverage_game_count") <= pl.col("observed_game_count"))
                & (pl.col("four_factors_observed_game_count") <= pl.col("observed_game_count"))
                & (
                    pl.col("opp_effective_field_goal_percentage_coverage_game_count")
                    <= pl.col("four_factors_observed_game_count")
                )
                & (
                    pl.col("opp_free_throw_attempt_rate_coverage_game_count")
                    <= pl.col("four_factors_observed_game_count")
                )
                & (
                    pl.col("opp_team_turnover_percentage_coverage_game_count")
                    <= pl.col("four_factors_observed_game_count")
                )
                & (
                    pl.col("opp_offensive_rebound_percentage_coverage_game_count")
                    <= pl.col("four_factors_observed_game_count")
                )
                & (pl.col("hustle_observed_game_count") <= pl.col("observed_game_count"))
                & (
                    pl.col("contested_shots_coverage_game_count")
                    <= pl.col("hustle_observed_game_count")
                )
                & (
                    pl.col("deflections_coverage_game_count")
                    <= pl.col("hustle_observed_game_count")
                )
                & (
                    pl.col("loose_balls_recovered_coverage_game_count")
                    <= pl.col("hustle_observed_game_count")
                )
                & (
                    pl.col("charges_drawn_coverage_game_count")
                    <= pl.col("hustle_observed_game_count")
                )
                & (
                    pl.col("screen_assists_coverage_game_count")
                    <= pl.col("hustle_observed_game_count")
                )
            ).alias("coverage_counts_within_denominators")
        )

    @pa.dataframe_check
    @classmethod
    def aggregate_nullability_matches_coverage(
        cls,
        data: pa.PolarsData,
    ) -> pl.LazyFrame:
        """Bind every nullable aggregate to its exact metric coverage count."""

        del cls
        mean_bindings = (
            ("def_rating_coverage_game_count", "mean_observed_game_def_rating"),
            ("net_rating_coverage_game_count", "mean_observed_game_net_rating"),
            (
                "opp_effective_field_goal_percentage_coverage_game_count",
                "mean_observed_game_opp_effective_field_goal_percentage",
            ),
            (
                "opp_free_throw_attempt_rate_coverage_game_count",
                "mean_observed_game_opp_free_throw_attempt_rate",
            ),
            (
                "opp_team_turnover_percentage_coverage_game_count",
                "mean_observed_game_opp_team_turnover_percentage",
            ),
            (
                "opp_offensive_rebound_percentage_coverage_game_count",
                "mean_observed_game_opp_offensive_rebound_percentage",
            ),
        )
        hustle_bindings = (
            (
                "contested_shots_coverage_game_count",
                "total_observed_game_contested_shots",
                "mean_observed_game_contested_shots",
            ),
            (
                "deflections_coverage_game_count",
                "total_observed_game_deflections",
                "mean_observed_game_deflections",
            ),
            (
                "loose_balls_recovered_coverage_game_count",
                "total_observed_game_loose_balls_recovered",
                "mean_observed_game_loose_balls_recovered",
            ),
            (
                "charges_drawn_coverage_game_count",
                "total_observed_game_charges_drawn",
                "mean_observed_game_charges_drawn",
            ),
            (
                "screen_assists_coverage_game_count",
                "total_observed_game_screen_assists",
                "mean_observed_game_screen_assists",
            ),
        )
        mean_checks = [
            (
                (pl.col(coverage_column).eq(0) & pl.col(mean_column).is_null())
                | (pl.col(coverage_column).gt(0) & pl.col(mean_column).is_not_null())
            )
            for coverage_column, mean_column in mean_bindings
        ]
        hustle_checks = [
            (
                (
                    pl.col(coverage_column).eq(0)
                    & pl.col(total_column).is_null()
                    & pl.col(mean_column).is_null()
                )
                | (
                    pl.col(coverage_column).gt(0)
                    & pl.col(total_column).is_not_null()
                    & pl.col(mean_column).is_not_null()
                )
            )
            for coverage_column, total_column, mean_column in hustle_bindings
        ]
        return data.lazyframe.select(
            pl.all_horizontal([*mean_checks, *hustle_checks]).alias(
                "aggregate_nullability_matches_coverage"
            )
        )


class AggTeamFranchiseSchema(BaseSchema):
    """Franchise history with derived age and win-percentage columns."""

    __consumer_metadata__ = {
        "grain": "franchise",
        "agent_intents": ["franchise_history", "championships"],
    }

    team_id: int = pa.Field(gt=0, metadata={"description": "Unique team identifier"})
    team_city: str | None = pa.Field(nullable=True, metadata={"description": "Franchise city"})
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Franchise name"})
    start_year: int | None = pa.Field(
        nullable=True, metadata={"description": "Franchise start year"}
    )
    end_year: int | None = pa.Field(nullable=True, metadata={"description": "Franchise end year"})
    years: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Total years in league"}
    )
    games: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Total games played"}
    )
    wins: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Total wins"})
    losses: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Total losses"})
    win_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Historical win percentage"}
    )
    po_appearances: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Playoff appearances"}
    )
    div_titles: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Division titles won"}
    )
    conf_titles: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Conference titles won"}
    )
    league_titles: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "League championships won"}
    )
    franchise_age_years: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Franchise age in years"}
    )
    computed_win_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Computed win percentage (wins/games)"}
    )


class AggTeamPaceAndEfficiencySchema(BaseSchema):
    """Exposure-correct team-season pace and ratings from advanced box scores."""

    __consumer_metadata__ = {
        "grain": "team-season",
        "agent_intents": ["pace", "team_pace", "efficiency"],
        "join_hints": {"dim_team": "team_id"},
    }

    team_id: int = pa.Field(gt=0, metadata={"description": "Unique team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    total_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Provider possessions reported across canonical games"},
    )
    rating_covered_games: int = pa.Field(
        ge=0,
        metadata={
            "description": (
                "Games with positive possessions and both offensive and defensive ratings"
            )
        },
    )
    rating_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Possessions supporting both weighted rating estimates"},
    )
    pace_covered_games: int = pa.Field(
        ge=0,
        metadata={"description": "Games contributing possession and minute exposure to pace"},
    )
    pace_actual_minutes_games: int = pa.Field(
        ge=0,
        metadata={"description": "Pace games using parsed provider team player-minutes"},
    )
    pace_inferred_minutes_games: int = pa.Field(
        ge=0,
        metadata={"description": "Pace games using minute exposure inferred from provider pace"},
    )
    pace_covered_minutes: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "description": "Elapsed team minutes supporting pace, including explicit fallbacks"
        },
    )
    avg_pace: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Exposure-weighted pace in possessions per 48 team minutes"},
    )
    avg_ortg: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted offensive rating per 100 possessions"},
    )
    avg_drtg: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Possession-weighted defensive rating per 100 possessions"},
    )
    avg_net_rtg: float | None = pa.Field(
        nullable=True,
        metadata={"description": "Weighted offensive rating minus weighted defensive rating"},
    )


class AggTeamSeasonSchema(BaseSchema):
    """Team season aggregates from fact_team_game joined with dim_game."""

    __consumer_metadata__ = {
        "grain": "team-season",
        "agent_intents": ["team_season", "team_stats", "team_averages"],
        "join_hints": {"dim_team": "team_id"},
    }

    team_id: int = pa.Field(gt=0, metadata={"description": "Unique team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    avg_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average points per game"}
    )
    avg_reb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average rebounds per game"}
    )
    avg_ast: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average assists per game"}
    )
    avg_stl: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average steals per game"}
    )
    avg_blk: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average blocks per game"}
    )
    avg_tov: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average turnovers per game"}
    )
    fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Field goal percentage"}
    )
    fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goal percentage"}
    )
    ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Free throw percentage"}
    )


derived_output_schema()(AggAllTimeLeadersSchema)
derived_output_schema()(AggClutchStatsSchema)
derived_output_schema()(AggGameTotalsSchema)
derived_output_schema()(AggLeagueLeadersSchema)
derived_output_schema()(AggLineupEfficiencySchema)
derived_output_schema()(AggPlayerBioSchema)
derived_output_schema()(AggPlayerCareerSchema)
derived_output_schema()(AggPlayerRollingSchema)
derived_output_schema()(AggPlayerSeasonAdvancedSchema)
derived_output_schema()(AggPlayerSeasonSchema)
derived_output_schema()(AggPlayerSeasonPer36Schema)
derived_output_schema()(AggPlayerSeasonPer48Schema)
derived_output_schema()(AggShotLocationSeasonSchema)
derived_output_schema()(AggShotZonesSchema)
derived_output_schema()(AggTeamDefenseSchema)
derived_output_schema()(AggTeamFranchiseSchema)
derived_output_schema()(AggTeamPaceAndEfficiencySchema)
derived_output_schema()(AggTeamSeasonSchema)
