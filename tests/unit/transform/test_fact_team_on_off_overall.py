from __future__ import annotations

import duckdb
import polars as pl
import pytest
from nba_api.stats.endpoints import TeamPlayerOnOffDetails

from nbadb.schemas.registry import get_output_schema
from nbadb.transform.facts.fact_team_on_off_overall import (
    FactTeamOnOffOverallTransformer,
)

TEAM_ID = 1610612738


def _overall_frame(
    *,
    season_type: str = "Regular Season",
    group_value: str = "Overall",
) -> pl.DataFrame:
    row: dict[str, list[object]] = {}
    for provider_column in TeamPlayerOnOffDetails.expected_data["OverallTeamPlayerOnOffDetails"]:
        column = provider_column.lower()
        if column.endswith("_rank"):
            row[column] = [1]
        else:
            row[column] = [1.0]

    row.update(
        {
            "group_set": ["Overall"],
            "group_value": [group_value],
            "team_id": [TEAM_ID],
            "team_abbreviation": ["BOS"],
            "team_name": ["Boston Celtics"],
            "gp": [80],
            "w": [60],
            "l": [20],
            "w_pct": [0.749],
            "min": [3840.0],
            "fgm": [3200.0],
            "fga": [6400.0],
            "fg_pct": [0.499],
            "fg3m": [1200.0],
            "fg3a": [3200.0],
            "fg3_pct": [0.374],
            "ftm": [1600.0],
            "fta": [2000.0],
            "ft_pct": [0.799],
            "oreb": [800.0],
            "dreb": [2400.0],
            "reb": [3200.0],
            "ast": [2000.0],
            "tov": [1000.0],
            "stl": [600.0],
            "blk": [400.0],
            "blka": [350.0],
            "pf": [1500.0],
            "pfd": [1600.0],
            "pts": [9200.0],
            "plus_minus": [500.0],
            "season_year": ["2024-25"],
            "season_type": [season_type],
        }
    )
    return pl.DataFrame(row)


def _run(
    details: pl.DataFrame | None = None,
    summary: pl.DataFrame | None = None,
) -> pl.DataFrame:
    details = details if details is not None else _overall_frame()
    summary = summary if summary is not None else _overall_frame()
    conn = duckdb.connect()
    try:
        conn.register("stg_team_dashboard_on_off", details)
        conn.register("stg_on_off", summary)
        transformer = FactTeamOnOffOverallTransformer()
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def test_contract_owns_both_exact_overall_landing_routes() -> None:
    assert FactTeamOnOffOverallTransformer.output_table == "fact_team_on_off_overall"
    assert FactTeamOnOffOverallTransformer.depends_on == [
        "stg_team_dashboard_on_off",
        "stg_on_off",
    ]
    schema = get_output_schema("fact_team_on_off_overall")
    assert schema is not None
    assert schema.__consumer_metadata__["natural_key"] == [
        "league_id",
        "team_id",
        "season_year",
        "season_type",
        "group_set",
        "group_value",
    ]
    assert "not a causal" in schema.__consumer_metadata__["row_semantics"]


def test_reconciled_output_is_schema_valid_and_preserves_provider_fields() -> None:
    result = _run()
    schema = get_output_schema("fact_team_on_off_overall")
    assert schema is not None
    schema.validate(result)

    row = result.row(0, named=True)
    assert row["league_id"] == "00"
    assert row["team_id"] == TEAM_ID
    assert row["season_year"] == "2024-25"
    assert row["season_type"] == "Regular Season"
    assert row["request_measure_type"] == "Base"
    assert row["request_per_mode"] == "Totals"
    assert row["reconciliation_status"] == "both_exact_match"
    assert row["detail_source_present"] is True
    assert row["summary_source_present"] is True
    assert row["source_detail_result_set"] == "OverallTeamPlayerOnOffDetails"
    assert row["source_summary_result_set"] == "OverallTeamPlayerOnOffSummary"
    assert row["pts_rank"] == 1
    assert row["plus_minus"] == pytest.approx(500.0)


def test_rates_are_recomputed_from_provider_totals() -> None:
    row = _run().row(0, named=True)
    possessions = 6400 + 0.44 * 2000 - 800 + 1000

    assert row["provider_w_pct"] == pytest.approx(0.749)
    assert row["w_pct"] == pytest.approx(60 / 80)
    assert row["provider_fg_pct"] == pytest.approx(0.499)
    assert row["fg_pct"] == pytest.approx(3200 / 6400)
    assert row["provider_fg3_pct"] == pytest.approx(0.374)
    assert row["fg3_pct"] == pytest.approx(1200 / 3200)
    assert row["provider_ft_pct"] == pytest.approx(0.799)
    assert row["ft_pct"] == pytest.approx(1600 / 2000)
    assert row["efg_pct"] == pytest.approx((3200 + 0.5 * 1200) / 6400)
    assert row["ts_pct"] == pytest.approx(9200 / (2 * (6400 + 0.44 * 2000)))
    assert row["estimated_possessions"] == pytest.approx(possessions)
    assert row["pts_per_100_estimated_possessions"] == pytest.approx(100 * 9200 / possessions)
    assert row["ast_to_ratio"] == pytest.approx(2.0)


def test_exact_duplicates_are_idempotent() -> None:
    frame = _overall_frame()
    result = _run(pl.concat([frame, frame]), pl.concat([frame, frame]))

    assert result.height == 1
    assert result["reconciliation_status"][0] == "both_exact_match"


def test_conflicting_same_source_payload_fails_closed() -> None:
    frame = _overall_frame()
    conflict = frame.with_columns(pl.lit(9201.0).alias("pts"))

    with pytest.raises(duckdb.InvalidInputException, match="conflicting duplicate details"):
        _run(pl.concat([frame, conflict]), frame)


def test_conflicting_detail_and_summary_payload_fails_closed() -> None:
    detail = _overall_frame()
    summary = detail.with_columns(pl.lit(3199.0).alias("fgm"))

    with pytest.raises(duckdb.InvalidInputException, match="packets conflict"):
        _run(detail, summary)


@pytest.mark.parametrize(
    ("missing_source", "expected_status"),
    [("details", "summary_only"), ("summary", "details_only")],
)
def test_single_source_rows_are_retained_with_explicit_coverage(
    missing_source: str,
    expected_status: str,
) -> None:
    frame = _overall_frame()
    empty = frame.head(0)
    details = empty if missing_source == "details" else frame
    summary = empty if missing_source == "summary" else frame

    result = _run(details, summary)
    row = result.row(0, named=True)
    assert row["reconciliation_status"] == expected_status
    assert row["detail_source_present"] is (missing_source != "details")
    assert row["summary_source_present"] is (missing_source != "summary")


def test_season_type_and_provider_group_are_part_of_the_natural_grain() -> None:
    frames = pl.concat(
        [
            _overall_frame(),
            _overall_frame(season_type="Playoffs"),
            _overall_frame(group_value="Alternate"),
        ]
    )

    result = _run(frames, frames)
    assert result.height == 3
    assert set(result["season_type"].to_list()) == {"Regular Season", "Playoffs"}
    assert set(result["group_value"].to_list()) == {"Overall", "Alternate"}
