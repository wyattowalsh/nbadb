from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from nbadb.core.errors import ResponseContractError
from nbadb.core.errors import ValidationError as NbaDbValidationError
from nbadb.extract.landing_projection import (
    apply_live_snapshot_contract,
    live_payload_to_frame,
    project_static_landing_frame,
)

_SNAPSHOT_AT = datetime(2026, 4, 17, 12, 30, tzinfo=UTC)


def _players() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "id": [1],
            "last_name": ["Doe"],
            "first_name": ["Jane"],
            "full_name": ["Jane Doe"],
            "is_active": [True],
        }
    )


def _teams() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "id": [2, 3],
            "abbreviation": ["AAA", "BBB"],
            "nickname": ["A", "B"],
            "year_founded": [1949, 2000],
            "city": ["Alpha", "Beta"],
            "full_name": ["Alpha A", "Beta B"],
            "state": ["East", "West"],
            "championship_year": [[1949, 1950], []],
        }
    )


@pytest.mark.parametrize(
    ("dataset_id", "source", "columns"),
    [
        (
            "static_players",
            _players,
            ["id", "full_name", "first_name", "last_name", "is_active"],
        ),
        (
            "static_wnba_players",
            _players,
            ["id", "last_name", "first_name", "full_name", "is_active", "league"],
        ),
        (
            "static_teams",
            _teams,
            [
                "id",
                "full_name",
                "abbreviation",
                "nickname",
                "city",
                "state",
                "year_founded",
                "championship_years_json",
            ],
        ),
        (
            "static_wnba_teams",
            _teams,
            [
                "id",
                "abbreviation",
                "nickname",
                "year_founded",
                "city",
                "full_name",
                "state",
                "championship_years_json",
                "league",
            ],
        ),
    ],
)
def test_static_projection_has_exact_fixed_shape(
    dataset_id: str,
    source: object,
    columns: list[str],
) -> None:
    source_frame = source()
    original = source_frame.clone()

    projected = project_static_landing_frame(dataset_id, source_frame)

    assert projected.columns == columns
    assert source_frame.equals(original)
    if dataset_id.endswith("teams"):
        assert projected["championship_years_json"].to_list() == ["[1949,1950]", "[]"]
    if "wnba" in dataset_id:
        assert projected["league"].unique().to_list() == ["WNBA"]


def test_static_projection_rejects_unknown_dataset_and_non_frame() -> None:
    with pytest.raises(ResponseContractError, match="lacks a pinned dataset"):
        project_static_landing_frame("static_unknown", _players())
    with pytest.raises(ResponseContractError, match="requires a Polars frame"):
        project_static_landing_frame("static_players", object())  # type: ignore[arg-type]


def test_live_payload_projection_preserves_canonical_json_and_nested_field() -> None:
    payload = [
        {"gameId": "001", "statistics": {"points": 17}},
        {"gameId": "002", "statistics": {"points": 23}},
    ]

    frame = live_payload_to_frame(
        payload,
        field_projections={"statistics.points": "points"},
    )

    assert frame.columns == ["game_id", "statistics", "points", "payload_json"]
    assert frame["game_id"].to_list() == ["001", "002"]
    assert frame["points"].to_list() == [17, 23]
    assert frame["payload_json"].to_list() == [
        json.dumps(record, sort_keys=True) for record in payload
    ]


@pytest.mark.parametrize("payload", [None, []])
def test_live_payload_projection_preserves_empty_zero_width(payload: object) -> None:
    frame = live_payload_to_frame(payload)
    assert frame.shape == (0, 0)


def test_live_payload_projection_preserves_scalar_shapes() -> None:
    assert live_payload_to_frame([1, 2]).to_dicts() == [{"value": 1}, {"value": 2}]
    assert live_payload_to_frame("value").to_dicts() == [{"value": "value"}]


def test_live_snapshot_contract_injects_param_key_and_metadata() -> None:
    frame = live_payload_to_frame([{"actionNumber": 1}])

    projected = apply_live_snapshot_contract(
        frame,
        source_endpoint="live_play_by_play",
        natural_keys=("game_id", "action_number"),
        snapshot_at=_SNAPSHOT_AT,
        params={"game_id": "001"},
    )

    assert projected.columns == [
        "action_number",
        "payload_json",
        "game_id",
        "snapshot_at",
        "snapshot_date",
        "source_endpoint",
    ]
    assert projected.row(0, named=True) == {
        "action_number": 1,
        "payload_json": '{"actionNumber": 1}',
        "game_id": "001",
        "snapshot_at": _SNAPSHOT_AT,
        "snapshot_date": _SNAPSHOT_AT.date(),
        "source_endpoint": "live_play_by_play",
    }


def test_live_snapshot_contract_preserves_exact_typed_empty_shape() -> None:
    frame = apply_live_snapshot_contract(
        pl.DataFrame(),
        source_endpoint="live_play_by_play",
        natural_keys=("game_id", "action_number"),
        snapshot_at=_SNAPSHOT_AT,
        params={"game_id": "001"},
    )

    assert frame.shape == (0, 6)
    assert frame.columns == [
        "game_id",
        "action_number",
        "snapshot_at",
        "snapshot_date",
        "source_endpoint",
        "payload_json",
    ]
    assert frame.schema["game_id"] == pl.String
    assert frame.schema["action_number"] == pl.Null
    assert frame.schema["payload_json"] == pl.String


def test_live_snapshot_contract_rejects_missing_nonempty_natural_key() -> None:
    with pytest.raises(NbaDbValidationError, match="missing required natural keys: game_id"):
        apply_live_snapshot_contract(
            pl.DataFrame({"action_number": [1]}),
            source_endpoint="live_play_by_play",
            natural_keys=("game_id", "action_number"),
            snapshot_at=_SNAPSHOT_AT,
            params={},
        )


def test_base_wrappers_are_exact_shared_projection_delegates() -> None:
    from nbadb.extract.base import BaseExtractor

    payload = [{"actionNumber": 1}]
    direct = live_payload_to_frame(payload)
    assert BaseExtractor._live_payload_to_frame(payload).equals(direct)
    assert BaseExtractor._apply_live_snapshot_contract(
        direct,
        source_endpoint="live_play_by_play",
        natural_keys=("game_id", "action_number"),
        snapshot_at=_SNAPSHOT_AT,
        params={"game_id": "001"},
    ).equals(
        apply_live_snapshot_contract(
            direct,
            source_endpoint="live_play_by_play",
            natural_keys=("game_id", "action_number"),
            snapshot_at=_SNAPSHOT_AT,
            params={"game_id": "001"},
        )
    )


def test_projection_module_keeps_forbidden_dependencies_out() -> None:
    source_path = Path(__file__).parents[3] / "src/nbadb/extract/landing_projection.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    forbidden = (
        "nbadb.extract.base",
        "nbadb.extract.live",
        "nbadb.extract.nba_api_adapter",
        "nbadb.contracts.staging_route_contract",
        "nbadb.orchestrate.staging_batches",
        "nbadb.orchestrate.raw_request",
    )
    assert not any(module.startswith(forbidden) for module in imported)
