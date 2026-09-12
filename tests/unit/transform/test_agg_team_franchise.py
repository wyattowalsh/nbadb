from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.schemas.star.agg_schemas import AggTeamFranchiseSchema
from nbadb.transform.derived.agg_team_franchise import AggTeamFranchiseTransformer


def _run(frame: pl.DataFrame) -> pl.DataFrame:
    connection = duckdb.connect()
    try:
        connection.register("stg_franchise", frame)
        transformer = AggTeamFranchiseTransformer()
        transformer._conn = connection
        return transformer.transform({"stg_franchise": frame.lazy()})
    finally:
        connection.close()


def _franchises() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "league_id": ["00", "00"],
            "team_id": [2, 1],
            "team_city": ["Second", "First"],
            "team_name": ["Twos", "Ones"],
            "start_year": ["2000", "1946"],
            "end_year": ["2025", "2025"],
            "years": [26, 80],
            "games": [0, 100],
            "wins": [0, 60],
            "losses": [0, 40],
            "win_pct": [None, 0.6],
            "po_appearances": [0, 50],
            "div_titles": [0, 25],
            "conf_titles": [0, 20],
            "league_titles": [0, 18],
            "transport_only_extra": ["ignored", "ignored"],
        }
    )


def test_team_franchise_projects_exact_public_columns_and_formulas() -> None:
    result = _run(_franchises())

    assert result.columns == list(AggTeamFranchiseSchema.to_schema().columns)
    assert result["team_id"].to_list() == [1, 2]
    assert result["start_year"].dtype == pl.Int32
    assert result["end_year"].dtype == pl.Int32
    assert result["franchise_age_years"].to_list() == [80, 26]
    assert result["computed_win_pct"].to_list() == [0.6, None]
    assert "league_id" not in result.columns
    assert "transport_only_extra" not in result.columns
    assert AggTeamFranchiseSchema.validate(result).to_dicts() == result.to_dicts()


def test_team_franchise_preserves_null_years_without_fabricating_age() -> None:
    frame = (
        _franchises()
        .head(1)
        .with_columns(
            pl.lit(None).cast(pl.String).alias("start_year"),
            pl.lit(None).cast(pl.String).alias("end_year"),
        )
    )

    row = _run(frame).row(0, named=True)

    assert row["start_year"] is None
    assert row["end_year"] is None
    assert row["franchise_age_years"] is None
    assert row["computed_win_pct"] is None


def test_team_franchise_rejects_malformed_nonnull_years() -> None:
    frame = _franchises().head(1).with_columns(pl.lit("not-a-year").alias("start_year"))

    with pytest.raises(duckdb.ConversionException):
        _run(frame)


def test_team_franchise_collapses_exact_projected_duplicates() -> None:
    row = _franchises().head(1)
    frame = pl.concat(
        [
            row,
            row.with_columns(pl.lit("different transport value").alias("transport_only_extra")),
        ]
    )

    result = _run(frame)

    assert result.height == 1
    assert result["team_id"].to_list() == [2]


def test_team_franchise_rejects_conflicting_rows_for_one_team() -> None:
    row = _franchises().head(1)
    frame = pl.concat([row, row.with_columns(pl.lit(1).cast(pl.Int64).alias("wins"))])

    with pytest.raises(duckdb.InvalidInputException, match="conflicting projected rows"):
        _run(frame)


def test_team_franchise_rejects_null_team_id() -> None:
    frame = _franchises().head(1).with_columns(pl.lit(None).cast(pl.Int64).alias("team_id"))

    with pytest.raises(duckdb.InvalidInputException, match="invalid team_id"):
        _run(frame)


def test_team_franchise_retains_distinct_teams_with_same_name() -> None:
    frame = _franchises().with_columns(pl.lit("Shared").alias("team_name"))

    result = _run(frame)

    assert result["team_id"].to_list() == [1, 2]
    assert result["team_name"].to_list() == ["Shared", "Shared"]


def test_team_franchise_preserves_unknown_wins_with_positive_games() -> None:
    frame = (
        _franchises()
        .head(1)
        .with_columns(
            pl.lit(10).alias("games"),
            pl.lit(None).cast(pl.Int64).alias("wins"),
        )
    )

    row = _run(frame).row(0, named=True)

    assert row["wins"] is None
    assert row["computed_win_pct"] is None


def test_team_franchise_equal_years_have_inclusive_age_one() -> None:
    frame = (
        _franchises()
        .head(1)
        .with_columns(
            pl.lit("2000").alias("start_year"),
            pl.lit("2000").alias("end_year"),
        )
    )

    assert _run(frame)["franchise_age_years"].to_list() == [1]


def test_team_franchise_rejects_reversed_years() -> None:
    frame = (
        _franchises()
        .head(1)
        .with_columns(
            pl.lit("2001").alias("start_year"),
            pl.lit("2000").alias("end_year"),
        )
    )

    with pytest.raises(duckdb.InvalidInputException, match="end_year precedes start_year"):
        _run(frame)


def test_team_franchise_rejects_out_of_range_integer_year() -> None:
    frame = _franchises().head(1).with_columns(pl.lit("2147483648").alias("start_year"))

    with pytest.raises(duckdb.ConversionException):
        _run(frame)
