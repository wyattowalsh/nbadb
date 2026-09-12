"""Provider-field conservation tests for ``fact_shot_chart``."""

from __future__ import annotations

import duckdb
import polars as pl

from nbadb.schemas.star.fact_shot_chart import FactShotChartSchema
from nbadb.transform.facts.fact_shot_chart import FactShotChartTransformer


def _shot_rows() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "grid_type": ["Shot Chart Detail", "Shot Chart Detail"],
            "game_id": ["0022400001", "0022400002"],
            "game_event_id": [17, 33],
            "player_id": [203999, 1629029],
            "player_name": ["Nikola Jokic", "Luka Doncic"],
            "team_id": [1610612743, 1610612747],
            "team_name": ["Denver Nuggets", "Los Angeles Lakers"],
            "league_id": ["00", "00"],
            "season_year": ["2024-25", "2024-25"],
            "season_type": ["Regular Season", "Regular Season"],
            "period": [1, 4],
            "minutes_remaining": [8, 0],
            "seconds_remaining": [31, 4],
            "event_type": ["Made Shot", "Missed Shot"],
            "action_type": ["Driving Layup Shot", "Step Back Jump shot"],
            "shot_type": ["2PT Field Goal", "3PT Field Goal"],
            "shot_zone_basic": ["Restricted Area", "Above the Break 3"],
            "shot_zone_area": ["Center(C)", "Left Side Center(LC)"],
            "shot_zone_range": ["Less Than 8 ft.", "24+ ft."],
            "shot_distance": [1, 27],
            "loc_x": [2, -118],
            "loc_y": [8, 241],
            "shot_attempted_flag": [1, 1],
            "shot_made_flag": [1, 0],
            "game_date": ["20241022", None],
            "htm": ["DEN", "LAL"],
            "vtm": ["OKC", "DAL"],
        }
    )


def _dim_games() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["0022400001", "0022400002"],
            "game_date": ["2024-10-22", "2024-10-23"],
            "season_year": ["2024-25", "2024-25"],
            "season_type": ["Regular Season", "Regular Season"],
        }
    )


def _run(
    shots: pl.DataFrame | None = None,
    games: pl.DataFrame | None = None,
) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        conn.register("stg_shot_chart", shots if shots is not None else _shot_rows())
        conn.register("dim_game", games if games is not None else _dim_games())
        transformer = FactShotChartTransformer()
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def test_every_staged_shot_field_survives_gold_projection() -> None:
    result = _run()

    assert result.columns == [
        "grid_type",
        "game_id",
        "game_event_id",
        "player_id",
        "player_name",
        "team_id",
        "team_name",
        "league_id",
        "season_year",
        "season_type",
        "period",
        "minutes_remaining",
        "seconds_remaining",
        "event_type",
        "action_type",
        "shot_type",
        "shot_zone_basic",
        "shot_zone_area",
        "shot_zone_range",
        "shot_distance",
        "loc_x",
        "loc_y",
        "shot_attempted_flag",
        "shot_made_flag",
        "game_date",
        "htm",
        "vtm",
    ]
    assert result["game_event_id"].to_list() == [17, 33]
    assert result["event_type"].to_list() == ["Made Shot", "Missed Shot"]
    assert result["shot_attempted_flag"].to_list() == [1, 1]
    FactShotChartSchema.validate(result)


def test_provider_game_date_wins_and_dimension_date_fills_missing_value() -> None:
    result = _run().sort("game_id")

    assert result["game_date"].to_list() == ["20241022", "2024-10-23"]


def test_missing_game_dimension_preserves_shot_and_request_scope() -> None:
    result = _run(games=_dim_games().clear())

    assert result.height == 2
    assert result["season_year"].to_list() == ["2024-25", "2024-25"]
    assert result["season_type"].to_list() == ["Regular Season", "Regular Season"]
    assert result["league_id"].to_list() == ["00", "00"]
    assert result["game_event_id"].to_list() == [17, 33]
