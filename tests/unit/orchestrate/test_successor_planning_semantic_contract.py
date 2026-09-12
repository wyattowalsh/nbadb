from __future__ import annotations

import json
from dataclasses import replace

import pytest

from nbadb.orchestrate.successor_planning_semantic_contract import (
    SUCCESSOR_PLANNING_SEMANTIC_SCHEMA_VERSION,
    PlanningSemanticDescriptor,
    PlanningSemanticKind,
    SuccessorPlanningSemanticContractError,
)


def _descriptor(
    semantic_kind: PlanningSemanticKind = PlanningSemanticKind.GAME_DATE_INDEX,
    *,
    partition: dict[str, object] | None = None,
    value_count: int = 2,
    typed_zero_reason_code: str | None = None,
) -> PlanningSemanticDescriptor:
    if partition is None:
        partition = {"season": "2025-26", "season_type": "Regular Season"}
    return PlanningSemanticDescriptor.from_partition(
        semantic_kind=semantic_kind,
        partition=partition,
        semantic_schema_sha256="a" * 64,
        semantic_content_sha256="b" * 64,
        value_count=value_count,
        typed_zero_reason_code=typed_zero_reason_code,
    )


@pytest.mark.parametrize(
    ("semantic_kind", "partition"),
    [
        (
            PlanningSemanticKind.GAME_DATE_INDEX,
            {"season": "2025-26", "season_type": "Regular Season"},
        ),
        (
            PlanningSemanticKind.SEASON_PLAYER_UNIVERSE,
            {"current_only": True, "season": "2025-26"},
        ),
        (PlanningSemanticKind.SEASON_TEAM_UNIVERSE, {"season": "2025-26"}),
        (
            PlanningSemanticKind.CURRENT_TEAM_UNIVERSE,
            {"as_of_utc": "2026-08-13T12:30:00Z"},
        ),
        (
            PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION,
            {"season": "2025-26", "season_type": "Playoffs"},
        ),
        (
            PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
            {"as_of_utc": "2026-08-13T12:30:00Z"},
        ),
        (
            PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
            {
                "player_id": 2544,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
        ),
        (
            PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
            {
                "season": "2025-26",
                "season_type": "Regular Season",
                "team_id": 1610612747,
            },
        ),
        (PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA, {}),
    ],
)
def test_closed_semantic_kinds_round_trip_exact_partition_authority(
    semantic_kind: PlanningSemanticKind,
    partition: dict[str, object],
) -> None:
    descriptor = _descriptor(semantic_kind, partition=partition)

    assert PlanningSemanticDescriptor.from_dict(descriptor.to_dict()) == descriptor
    assert PlanningSemanticDescriptor.from_canonical_bytes(descriptor.canonical_bytes) == descriptor
    assert descriptor.partition == dict(sorted(partition.items()))
    assert descriptor.to_dict()["schema_version"] == SUCCESSOR_PLANNING_SEMANTIC_SCHEMA_VERSION
    assert set(descriptor.to_dict()) == {
        "schema_version",
        "kind",
        "semantic_kind",
        "partition",
        "semantic_schema_sha256",
        "semantic_content_sha256",
        "value_count",
        "typed_zero_reason_code",
    }
    assert "values" not in descriptor.to_dict()
    assert b"/" not in descriptor.canonical_bytes


def test_partition_keys_types_and_values_are_exact_and_path_free() -> None:
    with pytest.raises(SuccessorPlanningSemanticContractError, match="missing=season_type"):
        _descriptor(partition={"season": "2025-26"})
    with pytest.raises(SuccessorPlanningSemanticContractError, match="unexpected=game_ids"):
        _descriptor(
            partition={
                "game_ids": "0022500001",
                "season": "2025-26",
                "season_type": "Regular Season",
            }
        )
    with pytest.raises(SuccessorPlanningSemanticContractError, match="consecutive"):
        _descriptor(partition={"season": "2025-27", "season_type": "Regular Season"})
    with pytest.raises(SuccessorPlanningSemanticContractError, match="canonical label"):
        _descriptor(partition={"season": "2025-26", "season_type": "/tmp/private"})
    with pytest.raises(SuccessorPlanningSemanticContractError, match="positive integer"):
        _descriptor(
            PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
            partition={
                "player_id": True,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
        )
    with pytest.raises(SuccessorPlanningSemanticContractError, match="boolean"):
        _descriptor(
            PlanningSemanticKind.SEASON_PLAYER_UNIVERSE,
            partition={"current_only": 1, "season": "2025-26"},
        )
    with pytest.raises(SuccessorPlanningSemanticContractError, match="canonical UTC"):
        _descriptor(
            PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
            partition={"as_of_utc": "2026-02-30T00:00:00Z"},
        )


def test_partition_inventory_is_immutable_canonical_and_detached() -> None:
    source = {"season_type": "Regular Season", "season": "2025-26"}
    descriptor = _descriptor(partition=source)
    source["season"] = "2024-25"
    detached = descriptor.partition
    detached["season"] = "2023-24"

    assert descriptor.partition_items == (
        ("season", "2025-26"),
        ("season_type", "Regular Season"),
    )
    assert descriptor.partition["season"] == "2025-26"
    with pytest.raises(SuccessorPlanningSemanticContractError, match="canonical sorted order"):
        replace(descriptor, partition_items=tuple(reversed(descriptor.partition_items)))
    with pytest.raises(SuccessorPlanningSemanticContractError, match="duplicate keys"):
        replace(
            descriptor,
            partition_items=(
                ("season", "2025-26"),
                ("season", "2025-26"),
                ("season_type", "Regular Season"),
            ),
        )


def test_typed_zero_is_required_only_for_exact_empty_partition_values() -> None:
    zero = _descriptor(
        value_count=0,
        typed_zero_reason_code="provider_success_empty",
    )

    assert PlanningSemanticDescriptor.from_canonical_bytes(zero.canonical_bytes) == zero
    with pytest.raises(SuccessorPlanningSemanticContractError, match="require a typed-zero"):
        replace(zero, typed_zero_reason_code=None)
    with pytest.raises(SuccessorPlanningSemanticContractError, match="cannot claim"):
        _descriptor(value_count=1, typed_zero_reason_code="provider_success_empty")
    with pytest.raises(SuccessorPlanningSemanticContractError, match="nonnegative"):
        _descriptor(value_count=-1)


def test_decode_rejects_unknown_schema_kind_duplicate_nonfinite_and_noncanonical() -> None:
    descriptor = _descriptor()
    unknown = descriptor.to_dict()
    unknown["global_player_ids"] = []
    with pytest.raises(
        SuccessorPlanningSemanticContractError,
        match="unexpected=global_player_ids",
    ):
        PlanningSemanticDescriptor.from_dict(unknown)

    old_schema = descriptor.to_dict()
    old_schema["schema_version"] = 0
    with pytest.raises(SuccessorPlanningSemanticContractError, match="schema is invalid"):
        PlanningSemanticDescriptor.from_dict(old_schema)

    invalid_kind = descriptor.to_dict()
    invalid_kind["semantic_kind"] = "inferred_affiliations"
    with pytest.raises(SuccessorPlanningSemanticContractError, match="kind is invalid"):
        PlanningSemanticDescriptor.from_dict(invalid_kind)

    pretty = json.dumps(descriptor.to_dict(), indent=2).encode()
    with pytest.raises(SuccessorPlanningSemanticContractError, match="not canonical"):
        PlanningSemanticDescriptor.from_canonical_bytes(pretty)

    duplicate = b'{"kind":"planning_semantic_descriptor","kind":"other"}'
    with pytest.raises(SuccessorPlanningSemanticContractError, match="duplicate key"):
        PlanningSemanticDescriptor.from_canonical_bytes(duplicate)

    nonfinite = descriptor.to_dict()
    nonfinite["value_count"] = float("nan")
    encoded = json.dumps(nonfinite, separators=(",", ":")).encode()
    with pytest.raises(SuccessorPlanningSemanticContractError, match="non-finite"):
        PlanningSemanticDescriptor.from_canonical_bytes(encoded)


def test_schema_and_content_identities_are_independent_semantic_authorities() -> None:
    descriptor = _descriptor()

    assert descriptor.semantic_schema_sha256 == "a" * 64
    assert descriptor.semantic_content_sha256 == "b" * 64
    assert descriptor.identity_sha256 not in {
        descriptor.semantic_schema_sha256,
        descriptor.semantic_content_sha256,
    }
    with pytest.raises(SuccessorPlanningSemanticContractError, match="lowercase SHA-256"):
        replace(descriptor, semantic_content_sha256="B" * 64)
