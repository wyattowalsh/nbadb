from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any, cast

import pytest

from nbadb.orchestrate.recurring_update_plan import (
    EndpointOverlapScopeV1,
    GapRepairRequestV1,
    RecurringUpdateMode,
    RecurringUpdatePlanError,
    RecurringUpdatePlanV1,
    TailGenerationV1,
    canonical_json_bytes,
)

_DATASET_REF = "w4w/nba-database"
_VERSION = 42
_VERSION_REF = f"{_DATASET_REF}/versions/{_VERSION}"


def _sha(character: str) -> str:
    return character * 64


def _overlap(
    *,
    endpoint_name: str = "league_game_log",
    request_key: str = "regular_season",
    request_contract_sha256: str = _sha("1"),
    scope_start_utc: str = "2026-08-20T00:00:00Z",
    scope_end_utc: str = "2026-08-26T00:00:00Z",
    parameters: dict[str, object] | None = None,
) -> EndpointOverlapScopeV1:
    return EndpointOverlapScopeV1.from_parameters(
        endpoint_name=endpoint_name,
        request_key=request_key,
        request_contract_sha256=request_contract_sha256,
        scope_start_utc=scope_start_utc,
        scope_end_utc=scope_end_utc,
        parameters=(
            {
                "league_id": "00",
                "season": "2025-26",
                "season_type": "Regular Season",
            }
            if parameters is None
            else parameters
        ),
    )


def _gap(
    *,
    endpoint_name: str = "box_score_summary_v2",
    request_key: str = "missing_game_0022500001",
    request_contract_sha256: str = _sha("2"),
    gap_start_utc: str = "2026-07-01T00:00:00Z",
    gap_end_utc: str = "2026-07-02T00:00:00Z",
    reason_code: str = "known_missing_game",
    parameters: dict[str, object] | None = None,
) -> GapRepairRequestV1:
    return GapRepairRequestV1.from_parameters(
        endpoint_name=endpoint_name,
        request_key=request_key,
        request_contract_sha256=request_contract_sha256,
        gap_start_utc=gap_start_utc,
        gap_end_utc=gap_end_utc,
        reason_code=reason_code,
        parameters={"game_id": "0022500001"} if parameters is None else parameters,
    )


def _tail(
    *,
    event_cutoff_utc: str = "2026-08-25T23:59:59Z",
    as_of_utc: str = "2026-08-26T01:00:00Z",
    window_start_utc: str = "2026-08-20T00:00:00Z",
    window_end_utc: str = "2026-08-26T00:00:00Z",
    sealed_at_utc: str = "2026-08-26T01:05:00Z",
    overlap_scopes: tuple[EndpointOverlapScopeV1, ...] | None = None,
    gap_repair_requests: tuple[GapRepairRequestV1, ...] | None = None,
) -> TailGenerationV1:
    return TailGenerationV1.build(
        event_cutoff_utc=event_cutoff_utc,
        as_of_utc=as_of_utc,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        sealed_at_utc=sealed_at_utc,
        overlap_scopes=(_overlap(),) if overlap_scopes is None else overlap_scopes,
        gap_repair_requests=(_gap(),) if gap_repair_requests is None else gap_repair_requests,
    )


def _plan(
    *,
    mode: RecurringUpdateMode = RecurringUpdateMode.DAILY,
    dataset_ref: str = _DATASET_REF,
    parent_dataset_version: int = _VERSION,
    parent_dataset_version_ref: str = _VERSION_REF,
    parent_authority_sha256: str = _sha("a"),
    tail_generation: TailGenerationV1 | None = None,
) -> RecurringUpdatePlanV1:
    return RecurringUpdatePlanV1.create_initial(
        mode=mode,
        dataset_ref=dataset_ref,
        parent_dataset_version=parent_dataset_version,
        parent_dataset_version_ref=parent_dataset_version_ref,
        parent_authority_sha256=parent_authority_sha256,
        tail_generation=_tail() if tail_generation is None else tail_generation,
    )


def _recover(
    previous: RecurringUpdatePlanV1,
    **changes: object,
) -> RecurringUpdatePlanV1:
    values: dict[str, object] = {
        "mode": previous.mode,
        "dataset_ref": previous.dataset_ref,
        "parent_dataset_version": previous.parent_dataset_version,
        "parent_dataset_version_ref": previous.parent_dataset_version_ref,
        "parent_authority_sha256": previous.parent_authority_sha256,
        "tail_generation": previous.tail_generation,
    }
    values.update(changes)
    return RecurringUpdatePlanV1.recover_from(
        previous,
        mode=cast("RecurringUpdateMode", values["mode"]),
        dataset_ref=cast("str", values["dataset_ref"]),
        parent_dataset_version=cast("int", values["parent_dataset_version"]),
        parent_dataset_version_ref=cast("str", values["parent_dataset_version_ref"]),
        parent_authority_sha256=cast("str", values["parent_authority_sha256"]),
        tail_generation=cast("TailGenerationV1", values["tail_generation"]),
    )


def test_plan_is_canonical_digest_bound_and_round_trips_exactly() -> None:
    plan = _plan()

    assert TailGenerationV1.from_bytes(plan.tail_generation.to_bytes()) == plan.tail_generation
    assert RecurringUpdatePlanV1.from_dict(plan.to_dict()) == plan
    assert RecurringUpdatePlanV1.from_bytes(plan.canonical_bytes) == plan
    assert RecurringUpdatePlanV1.from_bytes(plan.to_bytes()) == plan
    assert plan.content_sha256 == hashlib.sha256(plan.canonical_bytes).hexdigest()
    assert plan.update_transaction_id == plan.expected_update_transaction_id
    assert plan.tail_generation.request_identities == tuple(
        sorted(
            (
                plan.tail_generation.overlap_scopes[0].request_identity_sha256,
                plan.tail_generation.gap_repair_requests[0].request_identity_sha256,
            )
        )
    )


def test_parameter_order_is_canonical_and_external_mutation_cannot_change_request() -> None:
    parameters: dict[str, object] = {
        "season_type": "Regular Season",
        "season": "2025-26",
        "league_id": "00",
        "player_ids": [3, 1, 2],
    }
    request = _overlap(parameters=parameters)
    before = request.request_identity_sha256
    parameters["season"] = "2024-25"
    cast("list[int]", parameters["player_ids"]).append(4)

    same_request = _overlap(
        parameters={
            "league_id": "00",
            "player_ids": [3, 1, 2],
            "season": "2025-26",
            "season_type": "Regular Season",
        }
    )
    assert request.parameter_items == same_request.parameter_items
    assert request.request_identity_sha256 == same_request.request_identity_sha256 == before
    assert request.parameters["season"] == "2025-26"
    assert request.parameters["player_ids"] == [3, 1, 2]


def test_direct_mutable_or_noncanonical_parameter_inventory_is_rejected() -> None:
    with pytest.raises(RecurringUpdatePlanError, match="immutable canonical tuple"):
        EndpointOverlapScopeV1(
            endpoint_name="league_game_log",
            request_key="regular_season",
            request_contract_sha256=_sha("1"),
            scope_start_utc="2026-08-20T00:00:00Z",
            scope_end_utc="2026-08-26T00:00:00Z",
            parameter_items=cast("Any", {"season": "2025-26"}),
        )

    with pytest.raises(RecurringUpdatePlanError, match="immutable canonical sorted"):
        EndpointOverlapScopeV1(
            endpoint_name="league_game_log",
            request_key="regular_season",
            request_contract_sha256=_sha("1"),
            scope_start_utc="2026-08-20T00:00:00Z",
            scope_end_utc="2026-08-26T00:00:00Z",
            parameter_items=(("z", "last"), ("a", "first")),
        )


def test_tail_builder_canonicalizes_request_order_without_losing_exact_identities() -> None:
    first = _overlap(endpoint_name="box_score_summary_v2", request_key="summary")
    second = _overlap(endpoint_name="league_game_log", request_key="regular_season")
    gap_one = _gap(endpoint_name="box_score_summary_v2", request_key="missing_b")
    gap_two = _gap(
        endpoint_name="box_score_summary_v2",
        request_key="missing_a",
        gap_start_utc="2026-06-01T00:00:00Z",
        gap_end_utc="2026-06-02T00:00:00Z",
        parameters={"game_id": "0022500002"},
    )

    tail = _tail(
        overlap_scopes=(second, first),
        gap_repair_requests=(gap_one, gap_two),
    )
    assert tail.overlap_scopes == (first, second)
    assert tail.gap_repair_requests == (gap_two, gap_one)
    assert tail.request_identities == tuple(sorted(tail.request_identities))
    assert len(tail.request_identities) == 4


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        (
            {"window_start_utc": "2026-08-26T00:00:00Z"},
            "time order",
        ),
        (
            {"event_cutoff_utc": "2026-08-26T00:00:01Z"},
            "time order",
        ),
        (
            {"window_end_utc": "2026-08-26T01:00:01Z"},
            "time order",
        ),
        (
            {"as_of_utc": "2026-08-26T01:05:01Z"},
            "time order",
        ),
        (
            {"sealed_at_utc": "2026-08-26T00:59:59Z"},
            "time order",
        ),
    ],
)
def test_tail_rejects_time_order_violations(changes: dict[str, str], error: str) -> None:
    with pytest.raises(RecurringUpdatePlanError, match=error):
        _tail(**changes)


def test_tail_rejects_overlap_that_does_not_cover_cutoff_or_escapes_window() -> None:
    before_cutoff = _overlap(scope_end_utc="2026-08-25T00:00:00Z")
    with pytest.raises(RecurringUpdatePlanError, match="cover the cutoff"):
        _tail(overlap_scopes=(before_cutoff,))

    starts_too_early = _overlap(scope_start_utc="2026-08-19T23:59:59Z")
    with pytest.raises(RecurringUpdatePlanError, match="inside the tail window"):
        _tail(overlap_scopes=(starts_too_early,))


def test_tail_requires_gap_repairs_to_be_explicit_and_strictly_older() -> None:
    touches_window = _gap(gap_end_utc="2026-08-20T00:00:00Z")
    with pytest.raises(RecurringUpdatePlanError, match="strictly before"):
        _tail(gap_repair_requests=(touches_window,))

    no_repairs = _tail(gap_repair_requests=())
    assert no_repairs.gap_repair_requests == ()
    assert len(no_repairs.request_identities) == 1


def test_duplicate_and_conflicting_request_scopes_are_rejected() -> None:
    scope = _overlap()
    with pytest.raises(RecurringUpdatePlanError, match="duplicate or conflicting"):
        _tail(overlap_scopes=(scope, scope))

    conflicting = _overlap(parameters={"season": "2024-25"})
    with pytest.raises(RecurringUpdatePlanError, match="duplicate or conflicting"):
        _tail(overlap_scopes=(scope, conflicting))

    gap = _gap()
    conflicting_gap = _gap(reason_code="manual_audit_gap")
    with pytest.raises(RecurringUpdatePlanError, match="duplicate or conflicting"):
        _tail(gap_repair_requests=(gap, conflicting_gap))


def test_descriptive_labels_cannot_disguise_duplicate_executable_requests() -> None:
    overlap = _overlap(request_key="label_a")
    relabeled_overlap = _overlap(request_key="label_b")
    assert overlap.request_identity_sha256 == relabeled_overlap.request_identity_sha256
    with pytest.raises(RecurringUpdatePlanError, match="derived request identities"):
        _tail(overlap_scopes=(overlap, relabeled_overlap))

    gap = _gap(request_key="gap_a", reason_code="known_missing_game")
    relabeled_gap = _gap(
        request_key="gap_b",
        reason_code="manual_audit_gap",
    )
    assert gap.request_identity_sha256 == relabeled_gap.request_identity_sha256
    with pytest.raises(RecurringUpdatePlanError, match="derived request identities"):
        _tail(gap_repair_requests=(gap, relabeled_gap))


def test_disjoint_gap_scopes_are_distinct_even_with_the_same_executable_parameters() -> None:
    first = _gap(
        request_key="gap_a",
        gap_start_utc="2026-06-01T00:00:00Z",
        gap_end_utc="2026-06-02T00:00:00Z",
    )
    second = _gap(
        request_key="gap_b",
        gap_start_utc="2026-07-01T00:00:00Z",
        gap_end_utc="2026-07-02T00:00:00Z",
    )
    assert first.request_identity_sha256 != second.request_identity_sha256
    tail = _tail(gap_repair_requests=(second, first))
    assert tail.gap_repair_requests == (first, second)
    assert len(tail.request_identities) == 3


def test_request_identity_inventory_must_be_exact_sorted_and_deduplicated() -> None:
    tail = _tail()
    with pytest.raises(RecurringUpdatePlanError, match="exactly equal"):
        replace(tail, request_identities=tail.request_identities[:-1])
    with pytest.raises(RecurringUpdatePlanError, match="exactly equal"):
        replace(
            tail,
            request_identities=(tail.request_identities[0], tail.request_identities[0]),
        )
    with pytest.raises(RecurringUpdatePlanError, match="exactly equal"):
        replace(tail, request_identities=tuple(reversed(tail.request_identities)))


def test_nested_request_identity_and_inventory_digest_tampering_fail_readback() -> None:
    tail_payload = _tail().to_dict()
    overlaps = cast("list[dict[str, object]]", tail_payload["overlap_scopes"])
    overlaps[0]["request_identity_sha256"] = _sha("f")
    with pytest.raises(RecurringUpdatePlanError, match="request identity differs"):
        TailGenerationV1.from_dict(tail_payload)

    tail_payload = _tail().to_dict()
    tail_payload["request_identities_sha256"] = _sha("e")
    with pytest.raises(RecurringUpdatePlanError, match="inventory digest differs"):
        TailGenerationV1.from_dict(tail_payload)


@pytest.mark.parametrize(
    ("version", "version_ref", "error"),
    [
        (0, f"{_DATASET_REF}/versions/0", "positive"),
        (-1, f"{_DATASET_REF}/versions/-1", "positive"),
        (cast("Any", True), f"{_DATASET_REF}/versions/1", "positive"),
        (cast("Any", "42"), _VERSION_REF, "positive"),
        (_VERSION, _DATASET_REF, "unversioned and latest"),
        (_VERSION, f"{_DATASET_REF}/versions/latest", "unversioned and latest"),
        (_VERSION, f"{_DATASET_REF}/versions/43", "unversioned and latest"),
    ],
)
def test_plan_rejects_nonpositive_unversioned_and_latest_parent_aliases(
    version: int,
    version_ref: str,
    error: str,
) -> None:
    with pytest.raises(RecurringUpdatePlanError, match=error):
        _plan(parent_dataset_version=version, parent_dataset_version_ref=version_ref)


def test_plan_requires_immutable_parent_authority_and_exact_dataset_reference() -> None:
    with pytest.raises(RecurringUpdatePlanError, match="owner/dataset"):
        _plan(dataset_ref="latest", parent_dataset_version_ref="latest/versions/42")
    with pytest.raises(RecurringUpdatePlanError, match="lowercase SHA-256"):
        _plan(parent_authority_sha256="A" * 64)
    with pytest.raises(RecurringUpdatePlanError, match="lowercase SHA-256"):
        _plan(parent_authority_sha256="")


def test_initial_plan_rejects_forged_transaction_id_or_recovery_coordinates() -> None:
    plan = _plan()
    with pytest.raises(RecurringUpdatePlanError, match="update_transaction_id differs"):
        replace(plan, update_transaction_id=_sha("f"))
    with pytest.raises(RecurringUpdatePlanError, match="cannot claim a recovery parent"):
        replace(plan, recovery_parent_plan_sha256=_sha("d"))
    with pytest.raises(RecurringUpdatePlanError, match="requires the exact prior"):
        replace(plan, recovery_generation=1)


def test_recovery_keeps_transaction_id_stable_and_chains_exact_plan_digests() -> None:
    initial = _plan()
    recovery_one = _recover(initial)
    recovery_two = _recover(recovery_one)

    assert recovery_one.update_transaction_id == initial.update_transaction_id
    assert recovery_two.update_transaction_id == initial.update_transaction_id
    assert recovery_one.recovery_generation == 1
    assert recovery_two.recovery_generation == 2
    assert recovery_one.recovery_parent_plan_sha256 == initial.content_sha256
    assert recovery_two.recovery_parent_plan_sha256 == recovery_one.content_sha256
    assert recovery_one.content_sha256 != initial.content_sha256
    assert RecurringUpdatePlanV1.from_bytes(recovery_two.to_bytes()) == recovery_two


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"mode": RecurringUpdateMode.MONTHLY}, "mode"),
        ({"dataset_ref": "other/dataset"}, "dataset_ref"),
        ({"parent_dataset_version": 43}, "parent_dataset_version"),
        (
            {"parent_dataset_version_ref": f"{_DATASET_REF}/versions/43"},
            "parent_dataset_version_ref",
        ),
        ({"parent_authority_sha256": _sha("b")}, "parent_authority_sha256"),
        (
            {"tail_generation": replace(_tail(), sealed_at_utc="2026-08-26T01:06:00Z")},
            "tail_generation",
        ),
    ],
)
def test_recovery_rejects_parent_or_semantic_drift(
    changes: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(RecurringUpdatePlanError, match=field):
        _recover(_plan(), **changes)


def test_parent_handoff_assertion_rejects_every_kind_of_parent_drift() -> None:
    plan = _plan()
    plan.assert_parent_authority(
        dataset_ref=_DATASET_REF,
        parent_dataset_version=_VERSION,
        parent_dataset_version_ref=_VERSION_REF,
        parent_authority_sha256=_sha("a"),
    )
    with pytest.raises(RecurringUpdatePlanError, match="parent_authority_sha256"):
        plan.assert_parent_authority(
            dataset_ref=_DATASET_REF,
            parent_dataset_version=_VERSION,
            parent_dataset_version_ref=_VERSION_REF,
            parent_authority_sha256=_sha("b"),
        )


def test_plan_readback_rejects_parent_tail_and_transaction_digest_drift() -> None:
    plan = _plan()
    payload = plan.to_dict()
    payload["parent_identity_sha256"] = _sha("f")
    with pytest.raises(RecurringUpdatePlanError, match="authority digest differs"):
        RecurringUpdatePlanV1.from_dict(payload)

    payload = plan.to_dict()
    payload["tail_generation_sha256"] = _sha("e")
    with pytest.raises(RecurringUpdatePlanError, match="authority digest differs"):
        RecurringUpdatePlanV1.from_dict(payload)

    payload = plan.to_dict()
    payload["update_transaction_id"] = _sha("d")
    with pytest.raises(RecurringUpdatePlanError, match="transaction_id differs"):
        RecurringUpdatePlanV1.from_dict(payload)


def test_plan_readback_rejects_extra_fields_noncanonical_bytes_and_duplicate_keys() -> None:
    plan = _plan()
    payload = plan.to_dict()
    payload["ambient_latest_version"] = 43
    with pytest.raises(RecurringUpdatePlanError, match="unexpected"):
        RecurringUpdatePlanV1.from_dict(payload)

    with pytest.raises(RecurringUpdatePlanError, match="canonically encoded"):
        RecurringUpdatePlanV1.from_bytes(plan.to_bytes() + b"\n")
    with pytest.raises(RecurringUpdatePlanError, match="duplicate JSON key"):
        RecurringUpdatePlanV1.from_bytes(b'{"schema_version":1,"schema_version":1}')
    with pytest.raises(RecurringUpdatePlanError, match="bounded contract size"):
        RecurringUpdatePlanV1.from_bytes(b" " * (2 * 1024 * 1024 + 1))


def test_tail_and_plan_builders_have_no_time_or_parent_defaults() -> None:
    with pytest.raises(TypeError):
        TailGenerationV1.build(  # type: ignore[call-arg]
            event_cutoff_utc="2026-08-25T23:59:59Z",
            window_start_utc="2026-08-20T00:00:00Z",
            window_end_utc="2026-08-26T00:00:00Z",
            sealed_at_utc="2026-08-26T01:05:00Z",
            overlap_scopes=(_overlap(),),
            gap_repair_requests=(),
        )
    with pytest.raises(TypeError):
        RecurringUpdatePlanV1.create_initial(  # type: ignore[call-arg]
            mode=RecurringUpdateMode.DAILY,
            dataset_ref=_DATASET_REF,
            parent_dataset_version=_VERSION,
            parent_dataset_version_ref=_VERSION_REF,
            tail_generation=_tail(),
        )


def test_overlap_scope_count_is_bounded() -> None:
    scopes = tuple(_overlap(request_key=f"scope_{index}") for index in range(513))
    with pytest.raises(RecurringUpdatePlanError, match="bounded request count"):
        _tail(overlap_scopes=scopes, gap_repair_requests=())


def test_constructed_request_bytes_are_bounded_before_they_enter_a_plan() -> None:
    with pytest.raises(RecurringUpdatePlanError, match="overlap request.*bounded"):
        _overlap(parameters={"payload": ["x" * 1024] * 257})


def test_canonical_json_rejects_nonfinite_and_nonserializable_values() -> None:
    with pytest.raises(RecurringUpdatePlanError, match="canonical JSON"):
        canonical_json_bytes({"value": float("nan")})
    with pytest.raises(RecurringUpdatePlanError, match="canonical JSON"):
        canonical_json_bytes({"value": object()})
