from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast

import pytest

from nbadb.extract.bronze import canonical_parameters_sha256
from nbadb.orchestrate.successor_update_contract import (
    SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS,
    BaselineAssuranceIdentity,
    CallMutability,
    DeltaDisposition,
    ObservedDeltaReceipt,
    PlannedRouteReplacementBinding,
    RequestedRouteScope,
    SuccessorAssuranceIdentity,
    SuccessorGenerationBuild,
    SuccessorGenerationState,
    SuccessorUpdateContractError,
    SuccessorUpdateIntent,
    SuccessorUpdateMode,
    SuccessorUpdateTransaction,
    SuccessorUpdateTransitionError,
    UpdateScopeClosureEvidenceKind,
    canonical_json_bytes,
    canonical_sha256,
    is_scoreboard_derived_game_scope,
    may_reuse_baseline_completion,
    planned_route_replacement_bindings_sha256,
    require_live_and_scoreboard_update_delta_closure,
    require_update_replacement_delta_closure,
    requires_update_replacement_delta_closure,
)

_SOURCE_SHA = "a" * 40


def _baseline(*, source_sha: str = _SOURCE_SHA, marker: int = 1) -> BaselineAssuranceIdentity:
    digests = [f"{value:x}" * 64 for value in range(marker, marker + 11)]
    return BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=238,
        chain_id="full-initial-20260813",
        source_sha=source_sha,
        coverage_fingerprint=digests[0],
        data_tree_fingerprint=digests[1],
        remote_bundle_fingerprint_sha256=digests[2],
        installed_public_tree_sha256=digests[3],
        installed_public_tree_bytes=12_345,
        assured_manifest_sha256=digests[4],
        terminal_assurance_report_sha256=digests[5],
        private_baseline_receipt_sha256=digests[6],
        checkpoint_database_sha256=digests[7],
        checkpoint_report_sha256=digests[8],
        contract_blocked_evidence_sha256=digests[9],
        provider_authority_sha256=digests[10],
    )


def _scope(
    route_id: str,
    marker: str,
    *,
    mutability: CallMutability = CallMutability.MUTABLE,
) -> RequestedRouteScope:
    return RequestedRouteScope.from_parameters(
        endpoint_name=route_id.split(":", 1)[0],
        route_id=route_id,
        route_contract_sha256=marker * 64,
        parameters={"marker": marker},
        mutability=mutability,
    )


def _intent(
    baseline: BaselineAssuranceIdentity,
    scopes: tuple[RequestedRouteScope, ...],
    *,
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
    source_sha: str | None = None,
) -> SuccessorUpdateIntent:
    return SuccessorUpdateIntent(
        baseline_identity_sha256=baseline.identity_sha256,
        planning_generation_manifest_sha256="0" * 64,
        successor_execution_plan_sha256="1" * 64,
        planned_route_replacement_bindings_sha256=(
            planned_route_replacement_bindings_sha256(
                tuple(_planned_binding(scope) for scope in scopes)
            )
        ),
        mode=mode,
        source_sha=source_sha or baseline.source_sha,
        cutoff_utc="2026-08-06T12:00:00Z",
        as_of_utc="2026-08-13T12:00:00Z",
        requested_scopes=scopes,
    )


def _planned_binding(scope: RequestedRouteScope) -> PlannedRouteReplacementBinding:
    return PlannedRouteReplacementBinding(
        requested_scope_sha256=scope.identity_sha256,
        execution_dispatch_identity_sha256=canonical_sha256(
            {
                "endpoint_name": scope.endpoint_name,
                "parameters_sha256": scope.scope_sha256,
            }
        ),
        planning_dependency_identity_sha256s=(
            canonical_sha256(
                {
                    "planning_dependency": scope.endpoint_name,
                    "parameters_sha256": scope.scope_sha256,
                }
            ),
        ),
    )


def _receipt(
    baseline: BaselineAssuranceIdentity,
    intent: SuccessorUpdateIntent,
    scope: RequestedRouteScope,
    marker: str,
    *,
    disposition: DeltaDisposition = DeltaDisposition.OBSERVED,
) -> ObservedDeltaReceipt:
    binding = _planned_binding(scope)
    return ObservedDeltaReceipt(
        baseline_identity_sha256=baseline.identity_sha256,
        update_intent_sha256=intent.identity_sha256,
        source_sha=intent.source_sha,
        requested_scope_sha256=scope.identity_sha256,
        execution_dispatch_identity_sha256=(binding.execution_dispatch_identity_sha256),
        planning_dependency_identity_sha256s=(binding.planning_dependency_identity_sha256s),
        disposition=disposition,
        logical_call_receipt_sha256=marker * 64,
        prior_persisted_content_sha256="0" * 64,
        source_scope_replacement_sha256="f" * 64,
        persisted_content_sha256=hex((int(marker, 16) + 1) % 16)[2:] * 64,
        persisted_schema_sha256=hex((int(marker, 16) + 2) % 16)[2:] * 64,
        persisted_row_count=0 if disposition is DeltaDisposition.TYPED_ZERO else 12,
        typed_zero_reason_code=(
            "provider_returned_no_rows" if disposition is DeltaDisposition.TYPED_ZERO else None
        ),
    )


def _candidate(
    *,
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
) -> tuple[
    BaselineAssuranceIdentity,
    tuple[RequestedRouteScope, RequestedRouteScope],
    SuccessorUpdateIntent,
    SuccessorUpdateTransaction,
]:
    baseline = _baseline()
    scopes = (
        _scope("scoreboard.live", "a"),
        _scope("league_game_log.default", "b"),
    )
    intent = _intent(baseline, tuple(reversed(scopes)), mode=mode)
    transaction = SuccessorUpdateTransaction.candidate(
        generation=1,
        baseline=baseline,
        intent=intent,
    )
    return baseline, scopes, intent, transaction


def _build(
    baseline: BaselineAssuranceIdentity,
    scopes: tuple[RequestedRouteScope, RequestedRouteScope],
    intent: SuccessorUpdateIntent,
    transaction: SuccessorUpdateTransaction,
) -> SuccessorUpdateTransaction:
    receipts = (
        _receipt(baseline, intent, scopes[1], "d", disposition=DeltaDisposition.TYPED_ZERO),
        _receipt(baseline, intent, scopes[0], "c"),
    )
    return transaction.mark_built(observed_delta_receipts=receipts)


def _assurance(
    transaction: SuccessorUpdateTransaction,
    **overrides: object,
) -> SuccessorAssuranceIdentity:
    assert transaction.build is not None
    values: dict[str, object] = {
        "baseline_identity_sha256": transaction.baseline.identity_sha256,
        "update_intent_sha256": transaction.intent.identity_sha256,
        "source_sha": transaction.intent.source_sha,
        "generation": transaction.generation,
        "requested_scopes_sha256": transaction.intent.requested_scopes_sha256,
        "observed_delta_receipts_sha256": (transaction.build.observed_delta_receipts_sha256),
        "planned_route_replacement_bindings_sha256": (
            transaction.build.planned_route_replacement_bindings_sha256
        ),
        "transform_inventory_sha256": "4" * 64,
        "scan_report_sha256": "5" * 64,
        "publication_resource_inventory_sha256": "6" * 64,
        "installed_public_tree_sha256": "8" * 64,
        "private_generation_receipt_sha256": "7" * 64,
        "successor_data_tree_fingerprint": "1" * 64,
        "successor_assured_manifest_sha256": "2" * 64,
        "successor_validation_report_sha256": "3" * 64,
    }
    values.update(overrides)
    return SuccessorAssuranceIdentity(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", list(SuccessorUpdateMode))
def test_successor_transaction_reaches_promoted_with_canonical_round_trip(
    mode: SuccessorUpdateMode,
) -> None:
    baseline, scopes, intent, candidate = _candidate(mode=mode)
    assert candidate.state is SuccessorGenerationState.CANDIDATE
    assert tuple(scope.identity_sha256 for scope in intent.requested_scopes) == tuple(
        sorted(scope.identity_sha256 for scope in scopes)
    )

    built = _build(baseline, scopes, intent, candidate)
    assert built.state is SuccessorGenerationState.BUILT
    assert built.build is not None
    assert tuple(
        receipt.requested_scope_sha256 for receipt in built.build.observed_delta_receipts
    ) == tuple(sorted(scope.identity_sha256 for scope in scopes))

    validated = built.mark_validated(_assurance(built))
    promoted = validated.promote()
    assert promoted.state is SuccessorGenerationState.PROMOTED
    assert promoted.promoted_assurance.identity_sha256 == validated.assurance.identity_sha256
    assert candidate.generation_identity_sha256 == promoted.generation_identity_sha256
    assert len(promoted.content_sha256) == 64
    assert json.loads(promoted.canonical_bytes) == promoted.to_dict()
    assert promoted.to_dict()["schema_version"] == 6

    restored = SuccessorUpdateTransaction.from_dict(promoted.to_dict())
    assert restored == promoted
    assert restored.canonical_bytes == promoted.canonical_bytes
    assert restored.content_sha256 == promoted.content_sha256


def test_successor_transaction_rejects_pre_planning_manifest_schema() -> None:
    baseline, scopes, intent, candidate = _candidate()
    built = _build(baseline, scopes, intent, candidate)
    promoted = built.mark_validated(_assurance(built)).promote()
    payload = promoted.to_dict()
    payload["schema_version"] = 5

    with pytest.raises(SuccessorUpdateContractError, match="unsupported schema version"):
        SuccessorUpdateTransaction.from_dict(payload)


def test_canonical_serialization_and_inventory_digests_are_order_independent() -> None:
    baseline, scopes, intent, candidate = _candidate()
    reverse_intent = _intent(baseline, scopes)
    assert intent.to_dict() == reverse_intent.to_dict()
    assert intent.identity_sha256 == reverse_intent.identity_sha256
    assert canonical_sha256(intent.to_dict()) == intent.identity_sha256
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'

    forward_receipts = tuple(
        _receipt(baseline, intent, scope, marker)
        for scope, marker in zip(scopes, ("c", "d"), strict=True)
    )
    reverse_receipts = tuple(reversed(forward_receipts))
    forward = candidate.mark_built(observed_delta_receipts=forward_receipts)
    reverse = candidate.mark_built(observed_delta_receipts=reverse_receipts)
    assert forward.build == reverse.build
    assert forward.content_sha256 == reverse.content_sha256


def test_requested_scope_persists_exact_executable_parameters_and_derived_digest() -> None:
    game_ids = ["0022400001", "0022400002"]
    scope = RequestedRouteScope.from_parameters(
        endpoint_name="cume_stats_player_games",
        route_id="cume_stats_player_games:stg_cume_player_games:0",
        route_contract_sha256="a" * 64,
        parameters={
            "season_type": "Regular Season",
            "game_ids": game_ids,
            "player_id": 2544,
        },
        mutability=CallMutability.MUTABLE,
    )
    game_ids.append("0022400003")

    expected_parameters: dict[str, Any] = {
        "game_ids": ["0022400001", "0022400002"],
        "player_id": 2544,
        "season_type": "Regular Season",
    }
    assert scope.parameter_items == (
        ("game_ids", ("0022400001", "0022400002")),
        ("player_id", 2544),
        ("season_type", "Regular Season"),
    )
    assert scope.parameters == expected_parameters
    assert scope.scope_sha256 == canonical_parameters_sha256(expected_parameters)
    assert scope.uniqueness_key == (
        scope.endpoint_name,
        scope.route_id,
        scope.route_contract_sha256,
        scope.scope_sha256,
    )

    payload = scope.to_dict()
    assert payload["parameters"] == expected_parameters
    assert payload["endpoint_name"] == "cume_stats_player_games"
    assert payload["scope_sha256"] == scope.scope_sha256
    assert RequestedRouteScope.from_dict(payload) == scope

    payload_parameters = cast("dict[str, Any]", payload["parameters"])
    cast("list[str]", payload_parameters["game_ids"]).append("0022400004")
    assert scope.parameters == expected_parameters
    assert (
        RequestedRouteScope.from_parameters(
            endpoint_name=scope.endpoint_name,
            route_id=scope.route_id,
            route_contract_sha256=scope.route_contract_sha256,
            parameters={
                **expected_parameters,
                "game_ids": list(reversed(expected_parameters["game_ids"])),
            },
            mutability=scope.mutability,
        ).scope_sha256
        != scope.scope_sha256
    )


@pytest.mark.parametrize(
    ("parameters", "error"),
    [
        ({"api_key": "redacted"}, "forbidden key"),
        ({"filters": {"season": "2024-25"}}, "unsupported value type"),
        ({"game_ids": [["0022400001"]]}, "unsupported value type"),
        ({"game_ids": {"0022400001"}}, "unsupported value type"),
    ],
)
def test_requested_scope_rejects_secret_or_unsupported_nested_parameters(
    parameters: dict[str, object],
    error: str,
) -> None:
    with pytest.raises(SuccessorUpdateContractError, match=error):
        RequestedRouteScope.from_parameters(
            endpoint_name="league_game_log",
            route_id="league_game_log:stg_league_game_log:0",
            route_contract_sha256="a" * 64,
            parameters=parameters,
            mutability=CallMutability.MUTABLE,
        )


@pytest.mark.parametrize(
    "parameter_items",
    [
        [("season", "2024-25")],
        (("season", "2024-25", "extra"),),
        (("season", "2024-25"), ("season", "2025-26")),
        (("season", "2024-25"), ("game_id", "0022400001")),
        (("game_ids", ["0022400001"]),),
    ],
)
def test_requested_scope_rejects_mutable_duplicate_or_malformed_parameter_inventory(
    parameter_items: object,
) -> None:
    with pytest.raises(SuccessorUpdateContractError, match="parameter"):
        RequestedRouteScope(
            endpoint_name="league_game_log",
            route_id="league_game_log:stg_league_game_log:0",
            route_contract_sha256="a" * 64,
            parameter_items=cast("Any", parameter_items),
            mutability=CallMutability.MUTABLE,
        )


def test_requested_scope_rejects_supplied_or_tampered_scope_digest_without_fallback() -> None:
    scope = _scope("league_game_log:stg_league_game_log:0", "a")
    with pytest.raises(TypeError, match="scope_sha256"):
        cast("Any", RequestedRouteScope)(
            endpoint_name=scope.endpoint_name,
            route_id=scope.route_id,
            route_contract_sha256=scope.route_contract_sha256,
            parameter_items=scope.parameter_items,
            mutability=scope.mutability,
            scope_sha256="f" * 64,
        )

    tampered = scope.to_dict()
    tampered["scope_sha256"] = "0" * 64
    with pytest.raises(SuccessorUpdateContractError, match="does not match"):
        RequestedRouteScope.from_dict(tampered)

    noncanonical = scope.to_dict()
    noncanonical["scope_sha256"] = "A" * 64
    with pytest.raises(SuccessorUpdateContractError, match="lowercase SHA-256"):
        RequestedRouteScope.from_dict(noncanonical)

    digest_only = scope.to_dict()
    del digest_only["parameters"]
    with pytest.raises(SuccessorUpdateContractError, match="fields are invalid"):
        RequestedRouteScope.from_dict(digest_only)


def test_contract_payload_has_no_path_or_message_fields() -> None:
    baseline, scopes, intent, candidate = _candidate()
    built = _build(baseline, scopes, intent, candidate)
    promoted = built.mark_validated(_assurance(built)).promote()

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            payload = value
            return set(payload).union(*(keys(item) for item in payload.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    serialized_keys = keys(promoted.to_dict())
    assert not any(
        key == "path" or key == "message" or key.endswith("_path") or key.endswith("_message")
        for key in serialized_keys
    )


@pytest.mark.parametrize(
    ("field_name", "value", "error"),
    [
        ("remote_dataset", "missing-owner", "owner/dataset"),
        ("remote_dataset", "../escape", "owner/dataset"),
        ("remote_dataset_version", 0, "positive integer"),
        ("remote_dataset_version", True, "positive integer"),
        ("installed_public_tree_sha256", "A" * 64, "lowercase SHA-256"),
        ("installed_public_tree_bytes", True, "signed-63-bit"),
        ("installed_public_tree_bytes", -1, "signed-63-bit"),
        ("installed_public_tree_bytes", 1 << 63, "signed-63-bit"),
        ("private_baseline_receipt_sha256", "0" * 63, "lowercase SHA-256"),
    ],
)
def test_baseline_requires_exact_remote_public_and_private_authority(
    field_name: str,
    value: object,
    error: str,
) -> None:
    with pytest.raises(SuccessorUpdateContractError, match=error):
        replace(_baseline(), **{field_name: value})


def test_baseline_old_shape_and_installed_byte_tamper_fail_closed() -> None:
    baseline = _baseline()
    old_payload = baseline.to_dict()
    old_payload.pop("installed_public_tree_bytes")
    with pytest.raises(SuccessorUpdateContractError, match="fields are invalid"):
        BaselineAssuranceIdentity.from_dict(old_payload)

    scope = _scope("scoreboard.live", "a")
    intent = _intent(baseline, (scope,))
    tampered_payload = baseline.to_dict()
    tampered_payload["installed_public_tree_bytes"] = baseline.installed_public_tree_bytes + 1
    tampered = BaselineAssuranceIdentity.from_dict(tampered_payload)
    assert tampered.identity_sha256 != baseline.identity_sha256
    with pytest.raises(SuccessorUpdateContractError, match="baseline identity"):
        SuccessorUpdateTransaction.candidate(
            generation=1,
            baseline=tampered,
            intent=intent,
        )


def test_mutable_calls_cannot_reuse_baseline_completion() -> None:
    mutable = _scope("scoreboard.live", "a", mutability=CallMutability.MUTABLE)
    immutable = _scope("team_years.default", "b", mutability=CallMutability.IMMUTABLE)
    assert may_reuse_baseline_completion(mutable) is False
    assert may_reuse_baseline_completion(immutable) is True
    with pytest.raises(SuccessorUpdateContractError, match="RequestedRouteScope"):
        may_reuse_baseline_completion("scoreboard.live")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("disposition", "row_count", "reason", "error"),
    [
        (DeltaDisposition.OBSERVED, 0, None, "explicit typed_zero"),
        (DeltaDisposition.OBSERVED, 1, "not_zero", "cannot contain"),
        (DeltaDisposition.TYPED_ZERO, 1, "not_zero", "zero row count"),
        (DeltaDisposition.TYPED_ZERO, 0, None, "stable reason code"),
        (DeltaDisposition.TYPED_ZERO, 0, "Human message", "stable reason code"),
    ],
)
def test_typed_zero_is_explicit_and_structurally_validated(
    disposition: DeltaDisposition,
    row_count: int,
    reason: str | None,
    error: str,
) -> None:
    baseline, scopes, intent, _candidate_transaction = _candidate()
    valid = _receipt(baseline, intent, scopes[0], "c")
    with pytest.raises(SuccessorUpdateContractError, match=error):
        replace(
            valid,
            disposition=disposition,
            persisted_row_count=row_count,
            typed_zero_reason_code=reason,
        )


def test_typed_zero_receipt_round_trips_as_an_explicit_disposition() -> None:
    baseline, scopes, intent, _candidate_transaction = _candidate()
    receipt = _receipt(
        baseline,
        intent,
        scopes[0],
        "c",
        disposition=DeltaDisposition.TYPED_ZERO,
    )
    payload = receipt.to_dict()
    assert payload["disposition"] == "typed_zero"
    assert payload["persisted_row_count"] == 0
    assert payload["typed_zero_reason_code"] == "provider_returned_no_rows"
    assert ObservedDeltaReceipt.from_dict(payload) == receipt
    assert receipt.planned_route_replacement_binding == _planned_binding(scopes[0])


def test_planned_route_replacement_binding_digest_is_canonical_and_domain_separated() -> None:
    scopes = (
        _scope("scoreboard.live", "a"),
        _scope("league_game_log.default", "b"),
    )
    bindings = tuple(_planned_binding(scope) for scope in scopes)

    assert planned_route_replacement_bindings_sha256(bindings) == (
        planned_route_replacement_bindings_sha256(tuple(reversed(bindings)))
    )
    assert planned_route_replacement_bindings_sha256(bindings) != canonical_sha256(
        [binding.to_dict() for binding in bindings]
    )
    assert PlannedRouteReplacementBinding.from_dict(bindings[0].to_dict()) == bindings[0]


@pytest.mark.parametrize(
    "dependencies",
    [
        (),
        ("a" * 64, "a" * 64),
        ("b" * 64, "a" * 64),
        ("A" * 64,),
    ],
)
def test_planned_route_replacement_binding_rejects_noncanonical_dependencies(
    dependencies: tuple[str, ...],
) -> None:
    scope = _scope("scoreboard.live", "a")
    with pytest.raises(SuccessorUpdateContractError, match="planning_dependency"):
        PlannedRouteReplacementBinding(
            requested_scope_sha256=scope.identity_sha256,
            execution_dispatch_identity_sha256="c" * 64,
            planning_dependency_identity_sha256s=dependencies,
        )


def test_observed_delta_receipt_rejects_scalar_or_legacy_dependency_fields() -> None:
    baseline, scopes, intent, _candidate_transaction = _candidate()
    payload = _receipt(baseline, intent, scopes[0], "c").to_dict()
    payload["planning_dependency_identity_sha256s"] = "d" * 64
    with pytest.raises(SuccessorUpdateContractError, match="must be a list"):
        ObservedDeltaReceipt.from_dict(payload)

    payload = _receipt(baseline, intent, scopes[0], "c").to_dict()
    payload["planning_dependency_identity_sha256"] = payload.pop(
        "planning_dependency_identity_sha256s"
    )[0]
    with pytest.raises(SuccessorUpdateContractError, match="fields are invalid"):
        ObservedDeltaReceipt.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("prior_persisted_content_sha256", "A" * 64),
        ("source_scope_replacement_sha256", "0" * 63),
    ],
)
def test_delta_receipt_requires_exact_source_scope_replacement_evidence(
    field_name: str,
    value: str,
) -> None:
    baseline, scopes, intent, _candidate_transaction = _candidate()
    with pytest.raises(SuccessorUpdateContractError, match=field_name):
        replace(_receipt(baseline, intent, scopes[0], "c"), **{field_name: value})


def test_intent_rejects_duplicate_or_unsafe_route_scopes() -> None:
    baseline = _baseline()
    scope = _scope("scoreboard.live", "a")
    with pytest.raises(SuccessorUpdateContractError, match="duplicate scopes"):
        _intent(baseline, (scope, scope))

    conflicting_mutability = replace(scope, mutability=CallMutability.IMMUTABLE)
    with pytest.raises(SuccessorUpdateContractError, match="duplicate"):
        _intent(baseline, (scope, conflicting_mutability))

    with pytest.raises(SuccessorUpdateContractError, match="safe token"):
        replace(scope, route_id="../../scoreboard")


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-13T12:00:00+00:00",
        "2026-08-13T12:00:00.000000Z",
        "2026-02-30T12:00:00Z",
        "2026-8-13T12:00:00Z",
    ],
)
def test_intent_requires_canonical_utc_instants(value: str) -> None:
    baseline = _baseline()
    with pytest.raises(SuccessorUpdateContractError, match="canonical UTC form"):
        replace(_intent(baseline, (_scope("scoreboard.live", "a"),)), as_of_utc=value)


def test_intent_rejects_cutoff_after_as_of() -> None:
    baseline = _baseline()
    with pytest.raises(SuccessorUpdateContractError, match="must not be after"):
        replace(
            _intent(baseline, (_scope("scoreboard.live", "a"),)),
            cutoff_utc="2026-08-14T00:00:00Z",
        )


def test_intent_requires_exact_planning_authority_digests() -> None:
    baseline = _baseline()
    intent = _intent(baseline, (_scope("scoreboard.live", "a"),))

    assert intent.to_dict()["planning_generation_manifest_sha256"] == "0" * 64
    assert intent.to_dict()["successor_execution_plan_sha256"] == "1" * 64
    with pytest.raises(
        SuccessorUpdateContractError,
        match="planning_generation_manifest_sha256",
    ):
        replace(intent, planning_generation_manifest_sha256="A" * 64)
    with pytest.raises(
        SuccessorUpdateContractError,
        match="successor_execution_plan_sha256",
    ):
        replace(intent, successor_execution_plan_sha256="A" * 64)


def test_candidate_rejects_baseline_identity_mismatch_and_allows_newer_update_source() -> None:
    baseline = _baseline()
    scope = _scope("scoreboard.live", "a")
    intent = _intent(baseline, (scope,))
    other_baseline = _baseline(marker=2)
    with pytest.raises(SuccessorUpdateContractError, match="baseline identity"):
        SuccessorUpdateTransaction.candidate(
            generation=1,
            baseline=other_baseline,
            intent=intent,
        )

    newer_source_intent = _intent(
        baseline,
        (scope,),
        source_sha="b" * 40,
    )
    transaction = SuccessorUpdateTransaction.candidate(
        generation=1,
        baseline=baseline,
        intent=newer_source_intent,
    )
    assert transaction.baseline.source_sha == _SOURCE_SHA
    assert transaction.intent.source_sha == "b" * 40


def test_build_requires_one_bound_receipt_for_every_requested_scope() -> None:
    baseline, scopes, intent, candidate = _candidate()
    receipt = _receipt(baseline, intent, scopes[0], "c")
    with pytest.raises(SuccessorUpdateContractError, match="missing="):
        candidate.mark_built(observed_delta_receipts=(receipt,))

    unknown_scope_receipt = replace(receipt, requested_scope_sha256="f" * 64)
    with pytest.raises(SuccessorUpdateContractError, match="unexpected="):
        candidate.mark_built(
            observed_delta_receipts=(
                receipt,
                _receipt(baseline, intent, scopes[1], "d"),
                unknown_scope_receipt,
            )
        )

    with pytest.raises(SuccessorUpdateContractError, match="duplicate scopes"):
        SuccessorGenerationBuild(
            baseline_identity_sha256=baseline.identity_sha256,
            update_intent_sha256=intent.identity_sha256,
            source_sha=intent.source_sha,
            observed_delta_receipts=(receipt, receipt),
        )


def test_build_rejects_route_dispatch_or_dependency_relabel_against_sealed_intent() -> None:
    baseline, scopes, intent, candidate = _candidate()
    receipts = (
        _receipt(baseline, intent, scopes[0], "c"),
        _receipt(baseline, intent, scopes[1], "d"),
    )

    relabelled_dispatch = replace(
        receipts[0],
        execution_dispatch_identity_sha256="e" * 64,
    )
    with pytest.raises(SuccessorUpdateContractError, match="differ from the sealed plan"):
        candidate.mark_built(observed_delta_receipts=(relabelled_dispatch, receipts[1]))

    relabelled_dependencies = replace(
        receipts[0],
        planning_dependency_identity_sha256s=("e" * 64,),
    )
    with pytest.raises(SuccessorUpdateContractError, match="differ from the sealed plan"):
        candidate.mark_built(observed_delta_receipts=(relabelled_dependencies, receipts[1]))


def _multi_route_candidate() -> tuple[
    BaselineAssuranceIdentity,
    tuple[RequestedRouteScope, RequestedRouteScope],
    SuccessorUpdateIntent,
    SuccessorUpdateTransaction,
]:
    baseline = _baseline()
    parameters = {"season": "2025-26"}
    scopes = tuple(
        RequestedRouteScope.from_parameters(
            endpoint_name="fixture_endpoint",
            route_id=route_id,
            route_contract_sha256=marker * 64,
            parameters=parameters,
            mutability=CallMutability.MUTABLE,
        )
        for route_id, marker in (
            ("fixture_endpoint:stg_a:0", "a"),
            ("fixture_endpoint:stg_b:1", "b"),
        )
    )
    intent = _intent(baseline, scopes)
    return (
        baseline,
        scopes,
        intent,
        SuccessorUpdateTransaction.candidate(
            generation=1,
            baseline=baseline,
            intent=intent,
        ),
    )


def test_build_rejects_multi_route_logical_call_split_or_dispatch_relabel() -> None:
    baseline, scopes, intent, candidate = _multi_route_candidate()
    first = _receipt(baseline, intent, scopes[0], "c")
    second = _receipt(baseline, intent, scopes[1], "d")
    assert first.execution_dispatch_identity_sha256 == second.execution_dispatch_identity_sha256

    with pytest.raises(SuccessorUpdateContractError, match="missing="):
        candidate.mark_built(observed_delta_receipts=(first,))

    with pytest.raises(SuccessorUpdateContractError, match="split across logical"):
        candidate.mark_built(observed_delta_receipts=(first, second))

    same_call = replace(
        second,
        logical_call_receipt_sha256=first.logical_call_receipt_sha256,
    )
    built = candidate.mark_built(observed_delta_receipts=(first, same_call))
    assert built.build is not None
    assert len(built.build.planned_route_replacement_bindings) == 2

    relabelled = replace(
        same_call,
        execution_dispatch_identity_sha256="e" * 64,
    )
    with pytest.raises(SuccessorUpdateContractError, match="relabelled across"):
        candidate.mark_built(observed_delta_receipts=(first, relabelled))


def test_build_parser_rejects_self_consistent_fabricated_binding_digest() -> None:
    baseline, scopes, intent, candidate = _candidate()
    built = _build(baseline, scopes, intent, candidate)
    assert built.build is not None
    payload = built.build.to_dict()
    raw_bindings = cast("list[dict[str, object]]", payload["planned_route_replacement_bindings"])
    raw_bindings[0]["execution_dispatch_identity_sha256"] = "e" * 64
    fabricated = tuple(
        PlannedRouteReplacementBinding.from_dict(binding) for binding in raw_bindings
    )
    payload["planned_route_replacement_bindings_sha256"] = (
        planned_route_replacement_bindings_sha256(fabricated)
    )

    with pytest.raises(SuccessorUpdateContractError, match="does not match receipts"):
        SuccessorGenerationBuild.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "value", "error"),
    [
        ("baseline_identity_sha256", "e" * 64, "baseline_identity_sha256"),
        ("update_intent_sha256", "e" * 64, "update_intent_sha256"),
        ("source_sha", "b" * 40, "source_sha"),
    ],
)
def test_build_rejects_receipt_authority_mismatch(
    field_name: str,
    value: str,
    error: str,
) -> None:
    baseline, scopes, intent, candidate = _candidate()
    receipts = [
        _receipt(baseline, intent, scopes[0], "c"),
        _receipt(baseline, intent, scopes[1], "d"),
    ]
    receipts[0] = replace(receipts[0], **{field_name: value})
    with pytest.raises(SuccessorUpdateContractError, match=error):
        candidate.mark_built(observed_delta_receipts=receipts)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("baseline_identity_sha256", "f" * 64),
        ("update_intent_sha256", "f" * 64),
        ("source_sha", "b" * 40),
        ("generation", 2),
        ("requested_scopes_sha256", "f" * 64),
        ("observed_delta_receipts_sha256", "f" * 64),
        ("planned_route_replacement_bindings_sha256", "f" * 64),
    ],
)
def test_validation_rejects_assurance_mismatch(field_name: str, value: str | int) -> None:
    baseline, scopes, intent, candidate = _candidate()
    built = _build(baseline, scopes, intent, candidate)
    assurance = _assurance(built, **{field_name: value})
    with pytest.raises(SuccessorUpdateContractError, match=field_name):
        built.mark_validated(assurance)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing", "missing=planned_route_replacement_bindings_sha256"),
        ("bool", "must be a lowercase SHA-256"),
    ],
)
def test_assurance_identity_parser_requires_exact_planned_route_binding_digest(
    mutation: str,
    error: str,
) -> None:
    baseline, scopes, intent, candidate = _candidate()
    built = _build(baseline, scopes, intent, candidate)
    payload = _assurance(built).to_dict()
    if mutation == "missing":
        payload.pop("planned_route_replacement_bindings_sha256")
    else:
        payload["planned_route_replacement_bindings_sha256"] = True

    with pytest.raises(SuccessorUpdateContractError, match=error):
        SuccessorAssuranceIdentity.from_dict(payload)


def test_state_transitions_are_strict_and_state_shapes_fail_closed() -> None:
    baseline, scopes, intent, candidate = _candidate()
    with pytest.raises(SuccessorUpdateTransitionError, match="expected built"):
        candidate.mark_validated(
            SuccessorAssuranceIdentity(
                baseline_identity_sha256=baseline.identity_sha256,
                update_intent_sha256=intent.identity_sha256,
                source_sha=intent.source_sha,
                generation=1,
                requested_scopes_sha256=intent.requested_scopes_sha256,
                observed_delta_receipts_sha256="1" * 64,
                planned_route_replacement_bindings_sha256=(
                    intent.planned_route_replacement_bindings_sha256
                ),
                transform_inventory_sha256="5" * 64,
                scan_report_sha256="6" * 64,
                publication_resource_inventory_sha256="7" * 64,
                installed_public_tree_sha256="9" * 64,
                private_generation_receipt_sha256="8" * 64,
                successor_data_tree_fingerprint="2" * 64,
                successor_assured_manifest_sha256="3" * 64,
                successor_validation_report_sha256="4" * 64,
            )
        )
    with pytest.raises(SuccessorUpdateTransitionError, match="expected validated"):
        candidate.promote()
    with pytest.raises(SuccessorUpdateTransitionError, match="expected promoted"):
        _ = candidate.promoted_assurance

    built = _build(baseline, scopes, intent, candidate)
    with pytest.raises(SuccessorUpdateTransitionError, match="expected candidate"):
        built.mark_built(observed_delta_receipts=built.build.observed_delta_receipts)
    validated = built.mark_validated(_assurance(built))
    with pytest.raises(SuccessorUpdateTransitionError, match="expected built"):
        validated.mark_validated(validated.assurance)
    promoted = validated.promote()
    with pytest.raises(SuccessorUpdateTransitionError, match="expected validated"):
        promoted.promote()

    with pytest.raises(SuccessorUpdateContractError, match="invalid build contract"):
        SuccessorUpdateTransaction(
            state=SuccessorGenerationState.BUILT,
            generation=1,
            baseline=baseline,
            intent=intent,
        )


def test_strict_parser_rejects_extra_fields_and_inventory_digest_tampering() -> None:
    baseline, scopes, intent, candidate = _candidate()
    built = _build(baseline, scopes, intent, candidate)
    promoted = built.mark_validated(_assurance(built)).promote()
    payload = promoted.to_dict()
    payload["unexpected"] = True
    with pytest.raises(SuccessorUpdateContractError, match="unexpected=unexpected"):
        SuccessorUpdateTransaction.from_dict(payload)

    payload = promoted.to_dict()
    intent_payload = payload["intent"]
    assert isinstance(intent_payload, dict)
    intent_payload["requested_scopes_sha256"] = "f" * 64
    with pytest.raises(SuccessorUpdateContractError, match="digest does not match"):
        SuccessorUpdateTransaction.from_dict(payload)

    payload = promoted.to_dict()
    build_payload = payload["build"]
    assert isinstance(build_payload, dict)
    build_payload["observed_delta_receipts_sha256"] = "f" * 64
    with pytest.raises(SuccessorUpdateContractError, match="digest does not match"):
        SuccessorUpdateTransaction.from_dict(payload)


@pytest.mark.parametrize("generation", [0, -1, True])
def test_generation_must_be_a_positive_integer(generation: Any) -> None:
    baseline, _scopes, intent, _candidate_transaction = _candidate()
    with pytest.raises(SuccessorUpdateContractError, match="positive integer"):
        SuccessorUpdateTransaction.candidate(
            generation=generation,
            baseline=baseline,
            intent=intent,
        )


_SEALED_LIVE_GAME_ID = "0024090123"


def _live_scope(
    endpoint_name: str,
    route_id: str,
    parameters: dict[str, object],
    *,
    mutability: CallMutability = CallMutability.MUTABLE,
) -> RequestedRouteScope:
    return RequestedRouteScope.from_parameters(
        endpoint_name=endpoint_name,
        route_id=route_id,
        route_contract_sha256=canonical_sha256(route_id),
        parameters=parameters,
        mutability=mutability,
    )


def _live_roots_and_derived_scopes() -> tuple[RequestedRouteScope, ...]:
    return (
        _live_scope(
            "live_score_board",
            "live_score_board:stg_live_score_board:0",
            {},
        ),
        _live_scope("live_odds", "live_odds:stg_live_odds:0", {}),
        _live_scope(
            "live_play_by_play",
            "live_play_by_play:stg_live_play_by_play:0",
            {"game_id": _SEALED_LIVE_GAME_ID},
        ),
        _live_scope(
            "live_box_score",
            "live_box_score:stg_live_box_score_game_details:0",
            {"game_id": _SEALED_LIVE_GAME_ID},
        ),
    )


def test_live_roots_and_scoreboard_derived_scopes_require_delta_closure() -> None:
    ordinary = _scope("scoreboard_v3", "a")
    live_without_game = _live_scope(
        "live_play_by_play",
        "live_play_by_play:stg_live_play_by_play:0",
        {},
    )
    derived_scopes = _live_roots_and_derived_scopes()

    assert {
        "live_score_board",
        "live_odds",
        "live_play_by_play",
        "live_box_score",
    } == SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS
    assert requires_update_replacement_delta_closure(ordinary) is False
    assert is_scoreboard_derived_game_scope(ordinary) is False
    assert is_scoreboard_derived_game_scope(derived_scopes[0]) is False
    assert is_scoreboard_derived_game_scope(derived_scopes[2]) is True
    assert is_scoreboard_derived_game_scope(derived_scopes[3]) is True
    assert is_scoreboard_derived_game_scope(live_without_game) is False
    assert requires_update_replacement_delta_closure(live_without_game) is True
    assert all(requires_update_replacement_delta_closure(scope) for scope in derived_scopes)
    with pytest.raises(SuccessorUpdateContractError, match="RequestedRouteScope"):
        requires_update_replacement_delta_closure("live_score_board")  # type: ignore[arg-type]


def test_live_roots_cannot_reuse_baseline_completion_even_if_marked_immutable() -> None:
    immutable_live = _live_scope(
        "live_score_board",
        "live_score_board:stg_live_score_board:0",
        {},
        mutability=CallMutability.IMMUTABLE,
    )
    assert may_reuse_baseline_completion(immutable_live) is False


@pytest.mark.parametrize(
    "evidence_kind",
    [
        UpdateScopeClosureEvidenceKind.PLANNING_WAVE_CAPTURE,
        UpdateScopeClosureEvidenceKind.RETAINED_BRONZE_SEAL,
        UpdateScopeClosureEvidenceKind.JOURNAL_COMPLETION,
        UpdateScopeClosureEvidenceKind.CAPTURE_COMPLETION,
    ],
)
def test_live_and_scoreboard_scopes_reject_capture_or_bronze_completion(
    evidence_kind: UpdateScopeClosureEvidenceKind,
) -> None:
    baseline = _baseline()
    scopes = _live_roots_and_derived_scopes()
    intent = _intent(baseline, scopes)
    receipts = tuple(
        _receipt(baseline, intent, scope, marker)
        for scope, marker in zip(scopes, ("1", "2", "3", "4"), strict=True)
    )

    with pytest.raises(SuccessorUpdateContractError, match=f"{evidence_kind.value} cannot close"):
        require_update_replacement_delta_closure(
            scopes[0],
            receipt=receipts[0],
            evidence_kind=evidence_kind,
        )
    with pytest.raises(SuccessorUpdateContractError, match=f"{evidence_kind.value} cannot close"):
        require_live_and_scoreboard_update_delta_closure(
            scopes,
            observed_delta_receipts=receipts,
            evidence_kind=evidence_kind,
            sealed_live_game_ids=(_SEALED_LIVE_GAME_ID,),
        )


def test_live_and_scoreboard_scopes_close_only_with_distinct_replacement_delta() -> None:
    baseline = _baseline()
    scopes = _live_roots_and_derived_scopes()
    ordinary = _scope("league_game_log.default", "b")
    intent = _intent(baseline, (*scopes, ordinary))
    receipts = tuple(
        _receipt(baseline, intent, scope, marker)
        for scope, marker in zip(
            (*scopes, ordinary),
            ("1", "2", "3", "4", "5"),
            strict=True,
        )
    )

    closed = require_live_and_scoreboard_update_delta_closure(
        (*scopes, ordinary),
        observed_delta_receipts=receipts,
        evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
        sealed_live_game_ids=(_SEALED_LIVE_GAME_ID,),
    )
    assert closed == receipts[:4]
    assert (
        require_update_replacement_delta_closure(
            scopes[2],
            receipt=receipts[2],
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
            sealed_live_game_ids=(_SEALED_LIVE_GAME_ID,),
        )
        is receipts[2]
    )

    capture_only = replace(
        receipts[2],
        source_scope_replacement_sha256=receipts[2].logical_call_receipt_sha256,
    )
    with pytest.raises(
        SuccessorUpdateContractError,
        match="capture completion cannot substitute",
    ):
        require_update_replacement_delta_closure(
            scopes[2],
            receipt=capture_only,
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
            sealed_live_game_ids=(_SEALED_LIVE_GAME_ID,),
        )
    with pytest.raises(SuccessorUpdateContractError, match="ObservedDeltaReceipt"):
        require_update_replacement_delta_closure(
            scopes[0],
            receipt=None,
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
        )
    with pytest.raises(SuccessorUpdateContractError, match="does not match"):
        require_update_replacement_delta_closure(
            scopes[0],
            receipt=receipts[1],
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
        )
    with pytest.raises(SuccessorUpdateContractError, match="not a live root"):
        require_update_replacement_delta_closure(
            ordinary,
            receipt=receipts[4],
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
        )


def test_scoreboard_derived_game_scopes_must_match_sealed_live_inventory() -> None:
    baseline = _baseline()
    scopes = _live_roots_and_derived_scopes()
    intent = _intent(baseline, scopes)
    receipts = tuple(
        _receipt(baseline, intent, scope, marker)
        for scope, marker in zip(scopes, ("1", "2", "3", "4"), strict=True)
    )

    with pytest.raises(SuccessorUpdateContractError, match="typed-zero sealed live game"):
        require_live_and_scoreboard_update_delta_closure(
            scopes,
            observed_delta_receipts=receipts,
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
            sealed_live_game_ids=(),
        )
    with pytest.raises(SuccessorUpdateContractError, match="not bound to the sealed live"):
        require_live_and_scoreboard_update_delta_closure(
            scopes,
            observed_delta_receipts=receipts,
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
            sealed_live_game_ids=("0024090999",),
        )
    with pytest.raises(SuccessorUpdateContractError, match="exact ten-digit"):
        require_live_and_scoreboard_update_delta_closure(
            scopes,
            observed_delta_receipts=receipts,
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
            sealed_live_game_ids=("game",),
        )
    with pytest.raises(SuccessorUpdateContractError, match="duplicates"):
        require_live_and_scoreboard_update_delta_closure(
            scopes,
            observed_delta_receipts=receipts,
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
            sealed_live_game_ids=(_SEALED_LIVE_GAME_ID, _SEALED_LIVE_GAME_ID),
        )

    roots_only = require_live_and_scoreboard_update_delta_closure(
        scopes[:2],
        observed_delta_receipts=receipts[:2],
        evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
        sealed_live_game_ids=(),
    )
    assert roots_only == receipts[:2]


def test_mark_built_binds_live_and_scoreboard_scopes_to_replacement_delta() -> None:
    baseline = _baseline()
    scopes = _live_roots_and_derived_scopes()
    intent = _intent(baseline, scopes)
    candidate = SuccessorUpdateTransaction.candidate(
        generation=1,
        baseline=baseline,
        intent=intent,
    )
    receipts = tuple(
        _receipt(baseline, intent, scope, marker)
        for scope, marker in zip(scopes, ("1", "2", "3", "4"), strict=True)
    )
    built = candidate.mark_built(observed_delta_receipts=receipts)
    assert built.build is not None
    assert len(built.build.observed_delta_receipts) == 4

    capture_only = replace(
        receipts[0],
        source_scope_replacement_sha256=receipts[0].logical_call_receipt_sha256,
    )
    with pytest.raises(
        SuccessorUpdateContractError,
        match="capture completion cannot substitute",
    ):
        candidate.mark_built(observed_delta_receipts=(capture_only, *receipts[1:]))


def test_ordinary_scopes_do_not_require_live_delta_closure_inventory() -> None:
    baseline, scopes, intent, _transaction = _candidate()
    receipts = (
        _receipt(baseline, intent, scopes[0], "c"),
        _receipt(baseline, intent, scopes[1], "d", disposition=DeltaDisposition.TYPED_ZERO),
    )
    assert (
        require_live_and_scoreboard_update_delta_closure(
            scopes,
            observed_delta_receipts=receipts,
            evidence_kind=UpdateScopeClosureEvidenceKind.RETAINED_BRONZE_SEAL,
        )
        == ()
    )
