from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.bridge_play_player import BridgePlayPlayerTransformer
from nbadb.transform.facts.fact_play_by_play import FactPlayByPlayTransformer


def _run(transformer: object, frame: pl.DataFrame) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        conn.register("stg_play_by_play", frame)
        transformer._conn = conn  # type: ignore[attr-defined]
        return transformer.transform({})  # type: ignore[attr-defined,no-any-return]
    finally:
        conn.close()


def test_canonical_fact_preserves_v3_fields_and_shot_value() -> None:
    source = pl.DataFrame(
        {
            "game_id": ["0022400001"],
            "action_number": [7],
            "action_type": ["2pt"],
            "shot_value": [2],
            "action_id": [70],
        }
    )

    result = _run(FactPlayByPlayTransformer(), source)

    assert result.to_dicts() == [
        {
            "game_id": "0022400001",
            "action_number": 7,
            "action_type": "2pt",
            "shot_value": 2,
            "action_id": 70,
            "event_type_name": "2pt",
        }
    ]


def test_bridge_projects_the_single_v3_person_without_v2_slots() -> None:
    source = pl.DataFrame(
        {
            "game_id": ["0022400001", "0022400001"],
            "action_number": [7, 8],
            "person_id": [201939, None],
            "team_id": [1610612744, None],
        }
    )

    result = _run(BridgePlayPlayerTransformer(), source)

    assert result.to_dicts() == [
        {
            "game_id": "0022400001",
            "event_num": 7,
            "player_id": 201939,
            "team_id": 1610612744,
            "player_role": "primary",
        }
    ]
