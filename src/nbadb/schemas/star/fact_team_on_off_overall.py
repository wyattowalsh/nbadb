from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


@derived_output_schema(
    literal_fields={
        "league_id",
        "request_date_from",
        "request_date_to",
        "request_game_segment",
        "request_last_n_games",
        "request_location",
        "request_measure_type",
        "request_month",
        "request_opponent_team_id",
        "request_outcome",
        "request_pace_adjust",
        "request_per_mode",
        "request_period",
        "request_plus_minus",
        "request_rank",
        "request_season_segment",
        "request_vs_conference",
        "request_vs_division",
        "source_detail_result_set",
        "source_summary_result_set",
    },
    audit_fields={
        "detail_source_present",
        "summary_source_present",
        "reconciliation_status",
    },
)
class FactTeamOnOffOverallSchema(BaseSchema):
    """Descriptive team totals from reconciled on/off endpoint baselines.

    This table does not estimate a player's causal effect. It preserves the
    unfiltered team-level overall packet used as the denominator/context for
    player on/off splits.
    """

    __consumer_metadata__ = {
        "grain": "team-competition-season-season_type-provider-group-default-request-scope",
        "natural_key": [
            "league_id",
            "team_id",
            "season_year",
            "season_type",
            "group_set",
            "group_value",
        ],
        "request_discriminators": [
            "request_last_n_games",
            "request_measure_type",
            "request_month",
            "request_opponent_team_id",
            "request_pace_adjust",
            "request_per_mode",
            "request_period",
            "request_plus_minus",
            "request_rank",
            "request_date_from",
            "request_date_to",
            "request_game_segment",
            "request_location",
            "request_outcome",
            "request_season_segment",
            "request_vs_conference",
            "request_vs_division",
        ],
        "row_semantics": (
            "Descriptive provider team totals and denominator context; not a causal "
            "player-effect estimate."
        ),
        "agent_intents": ["team_on_off", "player_impact_context", "team_season"],
        "join_hints": {"dim_team": "team_id"},
    }

    league_id: str = pa.Field(isin=["00"], metadata={"description": "NBA competition identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team natural key"})
    season_year: str = pa.Field(metadata={"description": "Request season"})
    season_type: str = pa.Field(metadata={"description": "Request season type"})
    group_set: str = pa.Field(metadata={"description": "Provider result grouping"})
    group_value: str | None = pa.Field(
        nullable=True, metadata={"description": "Provider result grouping value"}
    )
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)

    request_last_n_games: int = pa.Field(ge=0)
    request_measure_type: str = pa.Field(isin=["Base"])
    request_month: int = pa.Field(ge=0)
    request_opponent_team_id: int = pa.Field(ge=0)
    request_pace_adjust: str = pa.Field(isin=["N"])
    request_per_mode: str = pa.Field(isin=["Totals"])
    request_period: int = pa.Field(ge=0)
    request_plus_minus: str = pa.Field(isin=["N"])
    request_rank: str = pa.Field(isin=["N"])
    request_date_from: str | None = pa.Field(nullable=True)
    request_date_to: str | None = pa.Field(nullable=True)
    request_game_segment: str | None = pa.Field(nullable=True)
    request_location: str | None = pa.Field(nullable=True)
    request_outcome: str | None = pa.Field(nullable=True)
    request_season_segment: str | None = pa.Field(nullable=True)
    request_vs_conference: str | None = pa.Field(nullable=True)
    request_vs_division: str | None = pa.Field(nullable=True)

    gp: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0)
    l: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    provider_w_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    w_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Recomputed W / (W + L)"},
    )
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    provider_fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg_pct: float | None = pa.Field(
        nullable=True, ge=0.0, le=1.0, metadata={"description": "Recomputed FGM / FGA"}
    )
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    provider_fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Recomputed FG3M / FG3A"},
    )
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    provider_ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ft_pct: float | None = pa.Field(
        nullable=True, ge=0.0, le=1.0, metadata={"description": "Recomputed FTM / FTA"}
    )
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    plus_minus: float | None = pa.Field(nullable=True)

    gp_rank: int | None = pa.Field(nullable=True, ge=0)
    w_rank: int | None = pa.Field(nullable=True, ge=0)
    l_rank: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    min_rank: int | None = pa.Field(nullable=True, ge=0)
    fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    fga_rank: int | None = pa.Field(nullable=True, ge=0)
    fg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3m_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3a_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    ftm_rank: int | None = pa.Field(nullable=True, ge=0)
    fta_rank: int | None = pa.Field(nullable=True, ge=0)
    ft_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    oreb_rank: int | None = pa.Field(nullable=True, ge=0)
    dreb_rank: int | None = pa.Field(nullable=True, ge=0)
    reb_rank: int | None = pa.Field(nullable=True, ge=0)
    ast_rank: int | None = pa.Field(nullable=True, ge=0)
    tov_rank: int | None = pa.Field(nullable=True, ge=0)
    stl_rank: int | None = pa.Field(nullable=True, ge=0)
    blk_rank: int | None = pa.Field(nullable=True, ge=0)
    blka_rank: int | None = pa.Field(nullable=True, ge=0)
    pf_rank: int | None = pa.Field(nullable=True, ge=0)
    pfd_rank: int | None = pa.Field(nullable=True, ge=0)
    pts_rank: int | None = pa.Field(nullable=True, ge=0)
    plus_minus_rank: int | None = pa.Field(nullable=True, ge=0)

    efg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "(FGM + 0.5 * FG3M) / FGA from provider totals"},
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "PTS / (2 * (FGA + 0.44 * FTA)) from provider totals"},
    )
    estimated_possessions: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "FGA + 0.44 * FTA - OREB + TOV"},
    )
    pts_per_100_estimated_possessions: float | None = pa.Field(nullable=True, ge=0.0)
    ast_to_ratio: float | None = pa.Field(nullable=True, ge=0.0)

    detail_source_present: bool = pa.Field(
        metadata={"description": "Details endpoint overall packet was present"}
    )
    summary_source_present: bool = pa.Field(
        metadata={"description": "Summary endpoint overall packet was present"}
    )
    reconciliation_status: str = pa.Field(
        isin=["both_exact_match", "details_only", "summary_only"],
        metadata={"description": "Exact source coverage at the natural grain"},
    )
    source_detail_result_set: str | None = pa.Field(nullable=True)
    source_summary_result_set: str | None = pa.Field(nullable=True)
