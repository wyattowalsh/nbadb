from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.derived.agg_clutch_stats import AggClutchStatsTransformer
from nbadb.transform.facts.fact_player_dashboard_clutch_overall import (
    FactPlayerDashboardClutchOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_game_splits_overall import (
    FactPlayerDashboardGameSplitsOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_general_splits_overall import (
    FactPlayerDashboardGeneralSplitsOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_last_n_overall import (
    FactPlayerDashboardLastNOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_shooting_overall import (
    FactPlayerDashboardShootingOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_team_perf_overall import (
    FactPlayerDashboardTeamPerfOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_yoy_overall import (
    FactPlayerDashboardYoyOverallTransformer,
)


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("transformer_cls", "output_table", "staging_key"),
    [
        (
            FactPlayerDashboardClutchOverallTransformer,
            "fact_player_dashboard_clutch_overall",
            "stg_player_dashboard_clutch",
        ),
        (
            FactPlayerDashboardGameSplitsOverallTransformer,
            "fact_player_dashboard_game_splits_overall",
            "stg_player_dashboard_game_splits",
        ),
        (
            FactPlayerDashboardGeneralSplitsOverallTransformer,
            "fact_player_dashboard_general_splits_overall",
            "stg_player_dashboard_general_splits",
        ),
        (
            FactPlayerDashboardLastNOverallTransformer,
            "fact_player_dashboard_last_n_overall",
            "stg_player_dashboard_last_n_games",
        ),
        (
            FactPlayerDashboardShootingOverallTransformer,
            "fact_player_dashboard_shooting_overall",
            "stg_player_dashboard_shooting_splits",
        ),
        (
            FactPlayerDashboardTeamPerfOverallTransformer,
            "fact_player_dashboard_team_perf_overall",
            "stg_player_dashboard_team_performance",
        ),
        (
            FactPlayerDashboardYoyOverallTransformer,
            "fact_player_dashboard_yoy_overall",
            "stg_player_dashboard_year_over_year",
        ),
    ],
)
def test_player_dashboard_fact_transformers_passthrough(
    transformer_cls: type,
    output_table: str,
    staging_key: str,
) -> None:
    transformer = transformer_cls()
    assert transformer.output_table == output_table
    assert transformer.depends_on == [staging_key]

    staging = {
        staging_key: pl.DataFrame(
            {
                "player_id": [2544],
                "season_year": ["2024-25"],
                "season_type": ["Regular Season"],
                "group_set": ["Overall"],
                "group_value": ["Overall"],
                "metric": [1.0],
            }
        ).lazy()
    }

    result = _run(transformer, staging)
    assert result.to_dict(as_series=False) == staging[staging_key].collect().to_dict(
        as_series=False
    )


def test_agg_clutch_stats_joins_player_dashboard_overall_rows() -> None:
    staging = {
        "stg_player_dashboard_clutch": pl.DataFrame(
            {
                "player_id": [2544],
                "season_year": ["2024-25"],
                "group_set": ["Overall"],
                "group_value": ["Overall"],
                "gp": [12],
                "min": [24.5],
                "pts": [36.0],
                "fg_pct": [0.55],
                "ft_pct": [0.88],
            }
        ).lazy(),
        "stg_league_player_clutch": pl.DataFrame(
            {
                "player_id": [2544],
                "season_year": ["2024-25"],
                "group_set": ["Overall"],
                "pts": [22.0],
                "fg_pct": [0.48],
            }
        ).lazy(),
    }

    result = _run(AggClutchStatsTransformer(), staging)

    assert result.shape == (1, 9)
    assert result["player_id"].to_list() == [2544]
    assert result["clutch_pts"].to_list() == [36.0]
    assert result["league_clutch_fg_pct"].to_list() == [0.48]


def _clutch_staging() -> dict[str, pl.LazyFrame]:
    return {
        "stg_player_dashboard_clutch": pl.DataFrame(
            {
                "player_id": [2544],
                "season_year": ["2024-25"],
                "group_set": ["Overall"],
                "group_value": ["Overall"],
                "gp": [12],
                "min": [24.5],
                "pts": [36.0],
                "fg_pct": [0.55],
                "ft_pct": [0.88],
            }
        ).lazy(),
        "stg_league_player_clutch": pl.DataFrame(
            {
                "player_id": [2544],
                "season_year": ["2024-25"],
                "group_set": ["Overall"],
                "pts": [22.0],
                "fg_pct": [0.48],
            }
        ).lazy(),
    }


def test_agg_clutch_stats_collapses_exact_projected_duplicates() -> None:
    staging = _clutch_staging()
    dashboard = staging["stg_player_dashboard_clutch"].collect()
    league = staging["stg_league_player_clutch"].collect()
    staging["stg_player_dashboard_clutch"] = pl.concat([dashboard, dashboard]).lazy()
    staging["stg_league_player_clutch"] = pl.concat([league, league]).lazy()

    result = _run(AggClutchStatsTransformer(), staging)

    assert result.shape == (1, 9)
    assert result["clutch_ft_pct"].to_list() == [0.88]
    assert result["league_clutch_fg_pct"].to_list() == [0.48]


@pytest.mark.parametrize(
    ("source", "column", "replacement", "message"),
    [
        (
            "stg_player_dashboard_clutch",
            "gp",
            13,
            "conflicting dashboard projected rows",
        ),
        (
            "stg_player_dashboard_clutch",
            "min",
            25.5,
            "conflicting dashboard projected rows",
        ),
        (
            "stg_player_dashboard_clutch",
            "pts",
            37.0,
            "conflicting dashboard projected rows",
        ),
        (
            "stg_player_dashboard_clutch",
            "fg_pct",
            0.56,
            "conflicting dashboard projected rows",
        ),
        (
            "stg_player_dashboard_clutch",
            "ft_pct",
            0.89,
            "conflicting dashboard projected rows",
        ),
        ("stg_league_player_clutch", "pts", 23.0, "conflicting league projected rows"),
        (
            "stg_league_player_clutch",
            "fg_pct",
            0.49,
            "conflicting league projected rows",
        ),
    ],
)
def test_agg_clutch_stats_rejects_conflicting_rows(
    source: str,
    column: str,
    replacement: int | float,
    message: str,
) -> None:
    staging = _clutch_staging()
    original = staging[source].collect()
    conflict = original.with_columns(
        pl.lit(replacement).cast(original.schema[column]).alias(column)
    )
    staging[source] = pl.concat([original, conflict]).lazy()

    with pytest.raises(duckdb.InvalidInputException, match=message):
        _run(AggClutchStatsTransformer(), staging)


def test_agg_clutch_stats_filters_nonoverall_dashboard_rows() -> None:
    staging = _clutch_staging()
    dashboard = staging["stg_player_dashboard_clutch"].collect()
    nonoverall = dashboard.with_columns(
        pl.lit("Last 5 Minutes").alias("group_set"),
        pl.lit("Under 5").alias("group_value"),
        pl.lit(999.0).alias("pts"),
    )
    staging["stg_player_dashboard_clutch"] = pl.concat([dashboard, nonoverall]).lazy()

    result = _run(AggClutchStatsTransformer(), staging)

    assert result["clutch_pts"].to_list() == [36.0]


def test_agg_clutch_stats_does_not_promote_null_grouping_labels() -> None:
    staging = _clutch_staging()
    dashboard = staging["stg_player_dashboard_clutch"].collect()
    league = staging["stg_league_player_clutch"].collect()
    unknown_dashboard = dashboard.with_columns(
        pl.lit(None).cast(pl.String).alias("group_set"),
        pl.lit(None).cast(pl.String).alias("group_value"),
        pl.lit(999.0).alias("pts"),
    )
    nonoverall_league = league.with_columns(
        pl.lit("Last 5 Minutes").alias("group_set"),
        pl.lit(999.0).alias("pts"),
    )
    staging["stg_player_dashboard_clutch"] = pl.concat([dashboard, unknown_dashboard]).lazy()
    staging["stg_league_player_clutch"] = pl.concat([league, nonoverall_league]).lazy()

    result = _run(AggClutchStatsTransformer(), staging)

    assert result["clutch_pts"].to_list() == [36.0]
    assert result["league_clutch_pts"].to_list() == [22.0]


def test_agg_clutch_stats_rejects_complementary_partial_rows() -> None:
    staging = _clutch_staging()
    dashboard = staging["stg_player_dashboard_clutch"].collect()
    partial = dashboard.with_columns(
        pl.lit(None).cast(dashboard.schema["gp"]).alias("gp"),
        pl.lit(None).cast(dashboard.schema["min"]).alias("min"),
    )
    staging["stg_player_dashboard_clutch"] = pl.concat([dashboard, partial]).lazy()

    with pytest.raises(duckdb.InvalidInputException, match="conflicting dashboard projected"):
        _run(AggClutchStatsTransformer(), staging)


def test_agg_clutch_stats_preserves_all_null_metrics() -> None:
    staging = _clutch_staging()
    for source, fields in (
        ("stg_player_dashboard_clutch", ("gp", "min", "pts", "fg_pct", "ft_pct")),
        ("stg_league_player_clutch", ("pts", "fg_pct")),
    ):
        frame = staging[source].collect()
        staging[source] = frame.with_columns(
            *(pl.lit(None).cast(frame.schema[field]).alias(field) for field in fields)
        ).lazy()

    row = _run(AggClutchStatsTransformer(), staging).row(0, named=True)

    assert all(
        row[field] is None
        for field in (
            "clutch_gp",
            "clutch_min",
            "clutch_pts",
            "clutch_fg_pct",
            "clutch_ft_pct",
            "league_clutch_pts",
            "league_clutch_fg_pct",
        )
    )


@pytest.mark.parametrize("missing_source", ["dashboard", "league"])
def test_agg_clutch_stats_preserves_one_sided_rows(missing_source: str) -> None:
    staging = _clutch_staging()
    source = (
        "stg_player_dashboard_clutch"
        if missing_source == "dashboard"
        else "stg_league_player_clutch"
    )
    staging[source] = staging[source].collect().head(0).lazy()

    row = _run(AggClutchStatsTransformer(), staging).row(0, named=True)

    assert row["player_id"] == 2544
    if missing_source == "dashboard":
        assert row["clutch_pts"] is None and row["league_clutch_pts"] == 22.0
    else:
        assert row["clutch_pts"] == 36.0 and row["league_clutch_pts"] is None


@pytest.mark.parametrize("source", ["stg_player_dashboard_clutch", "stg_league_player_clutch"])
def test_agg_clutch_stats_rejects_null_player_identity(source: str) -> None:
    staging = _clutch_staging()
    frame = staging[source].collect()
    staging[source] = frame.with_columns(
        pl.lit(None).cast(frame.schema["player_id"]).alias("player_id")
    ).lazy()

    with pytest.raises(duckdb.InvalidInputException, match="player_id is null"):
        _run(AggClutchStatsTransformer(), staging)
