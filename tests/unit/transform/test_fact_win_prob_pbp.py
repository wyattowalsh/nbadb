from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.facts.fact_win_prob_pbp import FactWinProbPbpTransformer


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _frame(row: dict) -> pl.LazyFrame:
    return pl.DataFrame({k: [v] for k, v in row.items()}).lazy()


SAMPLE_ROW = {
    "game_id": "0022400100",
    "event_num": 1,
    "home_pct": 0.52,
    "visitor_pct": 0.48,
    "home_pts": 0,
    "visitor_pts": 0,
    "home_score_margin": 0,
    "period": 1,
    "seconds_remaining": 720.0,
    "home_poss_ind": 1,
    "home_g": 0,
    "description": "Jump Ball",
    "location": "Home",
    "pctimestring": "12:00",
    "isvisible": 1,
}


class TestFactWinProbPbp:
    def test_output_table(self) -> None:
        t = FactWinProbPbpTransformer()
        assert t.output_table == "fact_win_prob_pbp"

    def test_depends_on(self) -> None:
        t = FactWinProbPbpTransformer()
        assert t.depends_on == ["stg_win_prob_pbp"]

    def test_sql_is_non_empty(self) -> None:
        assert FactWinProbPbpTransformer._SQL.strip()

    def test_basic_transform(self) -> None:
        staging = {"stg_win_prob_pbp": _frame(SAMPLE_ROW)}
        result = _run(FactWinProbPbpTransformer(), staging)
        assert result.shape[0] == 1
        assert result["game_id"][0] == "0022400100"
        assert result["event_num"][0] == 1
        assert result["home_pct"][0] == pytest.approx(0.52)
        assert result["visitor_pct"][0] == pytest.approx(0.48)
        assert result["period"][0] == 1

    def test_preserves_all_columns(self) -> None:
        staging = {"stg_win_prob_pbp": _frame(SAMPLE_ROW)}
        result = _run(FactWinProbPbpTransformer(), staging)
        assert set(SAMPLE_ROW.keys()) == set(result.columns)

    def test_multiple_rows(self) -> None:
        df = pl.DataFrame(
            {
                "game_id": ["0022400100", "0022400100"],
                "event_num": [1, 2],
                "home_pct": [0.52, 0.55],
                "visitor_pct": [0.48, 0.45],
                "home_pts": [0, 2],
                "visitor_pts": [0, 0],
                "home_score_margin": [0, 2],
                "period": [1, 1],
                "seconds_remaining": [720.0, 690.0],
                "home_poss_ind": [1, 0],
                "home_g": [0, 0],
                "description": ["Jump Ball", "Made Shot"],
                "location": ["Home", "Home"],
                "pctimestring": ["12:00", "11:30"],
                "isvisible": [1, 1],
            }
        )
        staging = {"stg_win_prob_pbp": df.lazy()}
        result = _run(FactWinProbPbpTransformer(), staging)
        assert result.shape[0] == 2
        assert result["home_score_margin"].to_list() == [0, 2]
