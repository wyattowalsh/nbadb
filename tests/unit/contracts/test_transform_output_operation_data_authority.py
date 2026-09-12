from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import fields
from typing import TYPE_CHECKING, cast

import pytest

from nbadb.contracts import transform_output_operation_data_authority as authority
from nbadb.contracts.ordered_sha256_prefix_fold import (
    compute_ordered_sha256_prefix_fold,
)
from nbadb.contracts.transform_output_operation_data_authority import (
    CumulativeConditionalStagingEvidenceInventoryV1,
    CumulativeConditionalStagingEvidenceMemberV1,
    DurableRawTerminalManifestLocatorV1,
    FullExtractionBlockedRawMemberV1,
    FullExtractionExecutableRawMemberV1,
    FullExtractionRawOperationDenominatorV1,
    OperationDataAuthorityError,
    OperationDataEvidenceV1,
    RawAuxiliaryTerminalMemberV1,
    SuccessorRawOperationDenominatorV1,
    VerifiedOperationRawSnapshotV1,
    W2DatabaseAuthorityReceiptV1,
    W2SourceMemberAttributionV1,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _fold(domain: str, leaves: Iterable[str]) -> tuple[int, str]:
    materialized = tuple(leaves)
    result = compute_ordered_sha256_prefix_fold(
        domain=domain,
        count=len(materialized),
        item_sha256s=iter(materialized),
    )
    return result.count, result.root_sha256


def _context(label: str, *, generation: int = 1) -> authority._OperationContextV1:
    return authority._OperationContextV1(
        operation_sha256=_digest(f"operation:{label}"),
        source_sha="1" * 40,
        chain_id="chain-main",
        transaction_generation=generation,
        transaction_generation_identity_sha256=_digest(f"generation:{label}"),
        duckdb_snapshot_sha256=_digest(f"snapshot:{label}"),
    )


def _locator(
    label: str,
    *,
    context: authority._OperationContextV1,
    call_count: int = 1,
    call_root: str | None = None,
    route_count: int = 1,
    route_root: str | None = None,
) -> DurableRawTerminalManifestLocatorV1:
    exact_call_root = call_root or _digest(f"calls:{label}")
    exact_route_root = route_root or _digest(f"routes:{label}")
    return DurableRawTerminalManifestLocatorV1._seal(
        source_sha=context.source_sha,
        run_id=int.from_bytes(hashlib.sha256(label.encode()).digest()[:4], "big") + 1,
        run_attempt=1,
        chain_id=context.chain_id,
        lane_id=f"lane-{label}",
        scope_sha256=_digest(f"scope:{label}"),
        route_authority_sha256=_digest(f"route-authority:{label}"),
        request_closure_authority_sha256=_digest(f"request-closure:{label}"),
        field_authority_sha256=_digest(f"field-authority:{label}"),
        model_authority_sha256=_digest(f"model-authority:{label}"),
        authority_set_sha256=_digest(f"authority-set:{label}"),
        expected_call_count=call_count,
        expected_call_inventory_sha256=exact_call_root,
        route_count=route_count,
        route_inventory_sha256=exact_route_root,
        terminal_generation=0,
        terminal_parent_manifest_sha256=None,
        terminal_manifest_sha256=_digest(f"terminal-manifest:{label}"),
        terminal_operation_sha256=_digest(f"terminal-operation:{label}"),
        terminal_receipt_count=call_count,
        terminal_receipt_inventory_sha256=_digest(f"terminal-receipts:{label}"),
        terminal_manifest_canonical_byte_length=512,
        terminal_manifest_canonical_sha256=_digest(f"terminal-canonical:{label}"),
    )


def _full_raw(
    context: authority._OperationContextV1,
    *,
    normalized_count: int = 2,
    executable_count: int = 1,
) -> VerifiedOperationRawSnapshotV1:
    if not 0 <= executable_count <= normalized_count:
        raise AssertionError("invalid test denominator")
    blocked_count = normalized_count - executable_count
    executable_locator = _locator("executable", context=context)
    executable = FullExtractionExecutableRawMemberV1._seal(
        normalized_lane_sha256=_digest("normalized:executable"),
        terminal_locator=executable_locator,
    )
    blocked = FullExtractionBlockedRawMemberV1._seal(
        normalized_lane_sha256=_digest("normalized:blocked"),
        blocked_evidence_sha256=_digest("blocked:evidence"),
    )
    discovery = RawAuxiliaryTerminalMemberV1._seal(
        auxiliary_role="discovery_seed",
        terminal_locator=_locator("discovery", context=context),
    )
    live = RawAuxiliaryTerminalMemberV1._seal(
        auxiliary_role="live_snapshot",
        terminal_locator=_locator("live", context=context),
    )
    normalized_leaves = tuple(_digest(f"normalized:{index}") for index in range(normalized_count))
    executable_leaves = tuple(
        executable.member_sha256 if index == 0 else _digest(f"executable:{index}")
        for index in range(executable_count)
    )
    blocked_leaves = tuple(
        blocked.member_sha256 if index == 0 else _digest(f"blocked:{index}")
        for index in range(blocked_count)
    )
    terminal_leaves = (
        *(executable_locator.locator_sha256 for _ in range(executable_count)),
        discovery.terminal_locator.locator_sha256,
        live.terminal_locator.locator_sha256,
    )
    _, normalized_root = _fold(authority._FULL_NORMALIZED_DOMAIN, normalized_leaves)
    _, executable_root = _fold(authority._FULL_EXECUTABLE_DOMAIN, executable_leaves)
    _, blocked_root = _fold(authority._FULL_BLOCKED_DOMAIN, blocked_leaves)
    _, terminal_root = _fold(authority._RAW_TERMINAL_DOMAIN, terminal_leaves)
    denominator = FullExtractionRawOperationDenominatorV1._seal(
        operation_context=context,
        normalized_manifest_lane_count=normalized_count,
        normalized_manifest_lane_inventory_sha256=normalized_root,
        executable_lane_count=executable_count,
        executable_lane_inventory_sha256=executable_root,
        blocked_lane_count=blocked_count,
        blocked_lane_inventory_sha256=blocked_root,
        discovery_member=discovery,
        live_member=live,
        raw_terminal_inventory_sha256=terminal_root,
    )
    return VerifiedOperationRawSnapshotV1._seal(
        operation_context=context,
        operation_kind="full_extraction",
        denominator=denominator,
    )


def _successor_raw(
    context: authority._OperationContextV1,
    *,
    prior_evidence_sha256: str,
) -> VerifiedOperationRawSnapshotV1:
    prior_leaves = (_digest("prior-terminal:0"), _digest("prior-terminal:1"))
    prior_count, prior_root = _fold(authority._RAW_TERMINAL_DOMAIN, prior_leaves)
    call_count, call_root = _fold(
        "nbadb:f5:test-successor-call:v1",
        (_digest("successor-call:0"), _digest("successor-call:1")),
    )
    route_count, route_root = _fold(
        "nbadb:f5:test-successor-route:v1",
        (_digest("successor-route:0"),),
    )
    locator = _locator(
        "successor-delta",
        context=context,
        call_count=call_count,
        call_root=call_root,
        route_count=route_count,
        route_root=route_root,
    )
    denominator = SuccessorRawOperationDenominatorV1._seal(
        operation_context=context,
        prior_operation_data_evidence_sha256=prior_evidence_sha256,
        prior_raw_snapshot_sha256=_digest("prior-raw-snapshot"),
        prior_raw_terminal_member_count=prior_count,
        prior_raw_terminal_inventory_sha256=prior_root,
        successor_execution_plan_sha256=_digest("successor-plan"),
        planning_generation_manifest_sha256=_digest("planning-generation-manifest"),
        planned_route_replacement_bindings_sha256=_digest("planned-route-bindings"),
        dispatch_call_count=call_count,
        dispatch_call_inventory_sha256=call_root,
        requested_route_binding_count=route_count,
        requested_route_binding_inventory_sha256=route_root,
        delta_terminal_locator=locator,
    )
    return VerifiedOperationRawSnapshotV1._seal(
        operation_context=context,
        operation_kind="successor",
        denominator=denominator,
    )


def _w2(
    context: authority._OperationContextV1,
    *,
    successor: bool,
    prior_evidence_sha256: str | None,
) -> W2DatabaseAuthorityReceiptV1:
    prior_leaves = (_digest("w2:prior"),) if successor else ()
    added_leaves = (_digest("w2:added"),)
    final_leaves = (*prior_leaves, *added_leaves)
    prior_count, prior_root = _fold(authority._W2_OPERATION_DOMAIN, prior_leaves)
    final_count, final_root = _fold(authority._W2_OPERATION_DOMAIN, final_leaves)
    added_count, added_root = _fold(authority._W2_ADDED_DOMAIN, added_leaves)
    attribution = W2SourceMemberAttributionV1._seal(
        w2_operation_sha256=added_leaves[0],
        source_member_role="successor_delta" if successor else "discovery_seed",
        source_member_sha256=_digest("source-member"),
        source_terminal_locator_sha256=_digest("source-locator"),
    )
    attribution_count, attribution_root = _fold(
        authority._W2_ATTRIBUTION_DOMAIN,
        (attribution.attribution_sha256,),
    )
    return W2DatabaseAuthorityReceiptV1._seal(
        operation_context=context,
        w2_baseline_kind="prior_assured_snapshot" if successor else "initial_full_rebuild",
        prior_operation_data_evidence_sha256=prior_evidence_sha256,
        prior_w2_operation_count=prior_count,
        prior_w2_operation_inventory_sha256=prior_root,
        final_w2_operation_count=final_count,
        final_w2_operation_inventory_sha256=final_root,
        added_w2_operation_count=added_count,
        added_w2_operation_inventory_sha256=added_root,
        source_member_attribution_count=attribution_count,
        source_member_attribution_inventory_sha256=attribution_root,
        public_w2_database_receipt_sha256=_digest("public-w2-receipt"),
        w2_required_logical_call_count=final_count,
        w2_source_call_admission_inventory_sha256=_digest("w2-call-admission"),
        raw_authority_v2_bundle_count=final_count,
        raw_authority_v2_bundle_inventory_sha256=_digest("raw-v2-bundle"),
        raw_authority_v2_persistence_receipt_inventory_sha256=_digest("raw-v2-persistence"),
        w2_publication_receipt_count=final_count,
        w2_publication_receipt_inventory_sha256=_digest("w2-publication"),
        w2_exact_six_schema_inventory_sha256=_digest("w2-six-schema"),
        w2_relation_row_count=17,
        w2_relation_inventory_sha256=_digest("w2-relations"),
        w2_operation_receipt_inventory_sha256=_digest("w2-operation-receipts"),
        w2_operation_persistence_receipt_inventory_sha256=_digest("w2-operation-persistence"),
    )


def _conditional_member(
    label: str,
    *,
    live: bool,
    successor: bool,
) -> CumulativeConditionalStagingEvidenceMemberV1:
    if live:
        staging_key = "stg_nba_api_live_lossless_nodes"
        kind = "live_complete_node_tree"
        role = "successor_delta" if successor else "live_snapshot"
    else:
        staging_key = "stg_nba_api_lossless_result_cells"
        kind = "stats_additive_result_cells"
        role = "successor_delta" if successor else "full_extraction_executable"
    return CumulativeConditionalStagingEvidenceMemberV1._seal(
        staging_key=staging_key,
        conditional_kind=kind,
        source_member_role=role,
        source_member_sha256=_digest(f"conditional-source:{label}"),
        source_terminal_locator_sha256=_digest(f"conditional-locator:{label}"),
        route_id=f"route/{label}",
        route_admission_sha256=_digest(f"route-admission:{label}"),
        provider_authority_sha256=_digest(f"provider:{label}"),
        route_authority_sha256=_digest(f"route-authority:{label}"),
        landing_sha256=_digest(f"landing:{label}"),
        persistence_receipt_sha256=_digest(f"persistence:{label}"),
        staging_schema_sha256=_digest(f"staging-schema:{label}"),
        staging_row_count=3,
        staging_row_inventory_sha256=_digest(f"staging-rows:{label}"),
    )


def _conditional(
    context: authority._OperationContextV1,
    *,
    successor: bool,
    prior_evidence_sha256: str | None,
) -> CumulativeConditionalStagingEvidenceInventoryV1:
    prior_members = (_digest("conditional:prior"),) if successor else ()
    added_members = (
        _conditional_member("stats", live=False, successor=successor).member_sha256,
        _conditional_member("live", live=True, successor=successor).member_sha256,
    )
    current_members = (*prior_members, *added_members)
    baseline_members: tuple[str, ...] = ()
    baseline_count, baseline_root = _fold(authority._CONDITIONAL_MEMBER_DOMAIN, baseline_members)
    prior_count, prior_root = _fold(authority._CONDITIONAL_MEMBER_DOMAIN, prior_members)
    current_count, current_root = _fold(authority._CONDITIONAL_MEMBER_DOMAIN, current_members)
    added_count, added_root = _fold(authority._CONDITIONAL_ADDED_DOMAIN, added_members)
    staging_keys = (_digest("staging-key:stats"), _digest("staging-key:live"))
    staging_count, staging_root = _fold(authority._CONDITIONAL_STAGING_KEY_DOMAIN, staging_keys)
    typed_count, typed_root = _fold(
        authority._CONDITIONAL_TYPED_SOURCE_DOMAIN,
        tuple(_digest(f"typed-source:{index}") for index in range(current_count)),
    )
    return CumulativeConditionalStagingEvidenceInventoryV1._seal(
        operation_context=context,
        baseline_kind="prior_assured_snapshot" if successor else "initial_full_rebuild",
        prior_operation_data_evidence_sha256=prior_evidence_sha256,
        prior_conditional_staging_authority_sha256=(
            _digest("prior-conditional-authority") if successor else None
        ),
        baseline_member_count=baseline_count,
        baseline_member_inventory_sha256=baseline_root,
        prior_member_count=prior_count,
        prior_member_inventory_sha256=prior_root,
        current_member_count=current_count,
        current_member_inventory_sha256=current_root,
        added_member_count=added_count,
        added_member_inventory_sha256=added_root,
        staging_key_count=staging_count,
        staging_key_inventory_sha256=staging_root,
        typed_source_member_count=typed_count,
        typed_source_member_inventory_sha256=typed_root,
    )


def _evidence(operation_kind: str = "full_extraction") -> OperationDataEvidenceV1:
    successor = operation_kind == "successor"
    if operation_kind not in {"full_extraction", "successor"}:
        raise AssertionError("unknown fixture operation kind")
    context = _context(operation_kind, generation=2 if successor else 1)
    prior = _digest("prior-operation-data-evidence") if successor else None
    raw = (
        _successor_raw(context, prior_evidence_sha256=cast("str", prior))
        if successor
        else _full_raw(context)
    )
    return OperationDataEvidenceV1._seal(
        raw_snapshot=raw,
        w2_database_authority=_w2(
            context,
            successor=successor,
            prior_evidence_sha256=prior,
        ),
        conditional_staging_inventory=_conditional(
            context,
            successor=successor,
            prior_evidence_sha256=prior,
        ),
    )


@pytest.mark.parametrize("operation_kind", ["full_extraction", "successor"])
def test_operation_data_evidence_round_trips_exact_canonical_bytes(
    operation_kind: str,
) -> None:
    evidence = _evidence(operation_kind)
    encoded = evidence.canonical_bytes()

    assert OperationDataEvidenceV1.from_canonical_bytes(encoded) == evidence
    assert OperationDataEvidenceV1.from_canonical_bytes(encoded).canonical_bytes() == encoded
    assert not encoded.endswith(b"\n")


def _all_public_dtos() -> tuple[object, ...]:
    full = _evidence()
    successor = _evidence("successor")
    context = full.operation_context
    locator = _locator("standalone", context=context)
    executable = FullExtractionExecutableRawMemberV1._seal(
        normalized_lane_sha256=_digest("standalone-executable"),
        terminal_locator=locator,
    )
    blocked = FullExtractionBlockedRawMemberV1._seal(
        normalized_lane_sha256=_digest("standalone-blocked"),
        blocked_evidence_sha256=_digest("standalone-blocked-evidence"),
    )
    auxiliary = RawAuxiliaryTerminalMemberV1._seal(
        auxiliary_role="discovery_seed",
        terminal_locator=locator,
    )
    attribution = W2SourceMemberAttributionV1._seal(
        w2_operation_sha256=_digest("standalone-w2"),
        source_member_role="discovery_seed",
        source_member_sha256=auxiliary.member_sha256,
        source_terminal_locator_sha256=locator.locator_sha256,
    )
    conditional = _conditional_member("standalone", live=False, successor=False)
    return (
        locator,
        executable,
        blocked,
        auxiliary,
        cast("FullExtractionRawOperationDenominatorV1", full.raw_snapshot.denominator),
        cast("SuccessorRawOperationDenominatorV1", successor.raw_snapshot.denominator),
        full.raw_snapshot,
        attribution,
        full.w2_database_authority,
        conditional,
        full.conditional_staging_inventory,
        full,
    )


def test_every_public_codec_rejects_subclass_parser_and_serializer() -> None:
    for value in _all_public_dtos():
        dto_type = type(value)
        canonical = cast("Any", value).canonical_bytes()
        foreign_type = type(f"Foreign{dto_type.__name__}", (dto_type,), {})

        with pytest.raises(OperationDataAuthorityError, match="exact DTO class"):
            foreign_type.from_canonical_bytes(canonical)

        foreign = object.__new__(foreign_type)
        for field in fields(dto_type):
            object.__setattr__(foreign, field.name, getattr(value, field.name))
        with pytest.raises(OperationDataAuthorityError, match="exact DTO class"):
            foreign.canonical_bytes()


def test_every_direct_constructor_is_private() -> None:
    for value in _all_public_dtos():
        kwargs = {field.name: getattr(value, field.name) for field in fields(type(value))}
        with pytest.raises(OperationDataAuthorityError, match="construction is private"):
            type(value)(**kwargs)


def test_every_private_seal_rejects_a_foreign_subclass() -> None:
    full = _evidence()
    successor = _evidence("successor")
    full_denominator = cast(
        "FullExtractionRawOperationDenominatorV1", full.raw_snapshot.denominator
    )
    successor_denominator = cast(
        "SuccessorRawOperationDenominatorV1", successor.raw_snapshot.denominator
    )
    locator = full_denominator.discovery_member.terminal_locator
    executable = FullExtractionExecutableRawMemberV1._seal(
        normalized_lane_sha256=_digest("seal-executable"), terminal_locator=locator
    )
    blocked = FullExtractionBlockedRawMemberV1._seal(
        normalized_lane_sha256=_digest("seal-blocked"),
        blocked_evidence_sha256=_digest("seal-blocked-evidence"),
    )
    auxiliary = full_denominator.discovery_member
    attribution = W2SourceMemberAttributionV1._seal(
        w2_operation_sha256=_digest("seal-w2"),
        source_member_role="discovery_seed",
        source_member_sha256=auxiliary.member_sha256,
        source_terminal_locator_sha256=locator.locator_sha256,
    )
    conditional_member = _conditional_member("seal", live=False, successor=False)

    calls: tuple[tuple[type[object], dict[str, object]], ...] = (
        (DurableRawTerminalManifestLocatorV1, {}),
        (
            FullExtractionExecutableRawMemberV1,
            {
                "normalized_lane_sha256": executable.normalized_lane_sha256,
                "terminal_locator": locator,
            },
        ),
        (
            FullExtractionBlockedRawMemberV1,
            {
                "normalized_lane_sha256": blocked.normalized_lane_sha256,
                "blocked_evidence_sha256": blocked.blocked_evidence_sha256,
            },
        ),
        (
            RawAuxiliaryTerminalMemberV1,
            {"auxiliary_role": "discovery_seed", "terminal_locator": locator},
        ),
        (
            FullExtractionRawOperationDenominatorV1,
            {
                "operation_context": full.operation_context,
                "normalized_manifest_lane_count": (full_denominator.normalized_manifest_lane_count),
                "normalized_manifest_lane_inventory_sha256": (
                    full_denominator.normalized_manifest_lane_inventory_sha256
                ),
                "executable_lane_count": full_denominator.executable_lane_count,
                "executable_lane_inventory_sha256": (
                    full_denominator.executable_lane_inventory_sha256
                ),
                "blocked_lane_count": full_denominator.blocked_lane_count,
                "blocked_lane_inventory_sha256": (full_denominator.blocked_lane_inventory_sha256),
                "discovery_member": full_denominator.discovery_member,
                "live_member": full_denominator.live_member,
                "raw_terminal_inventory_sha256": (full_denominator.raw_terminal_inventory_sha256),
            },
        ),
        (
            SuccessorRawOperationDenominatorV1,
            {
                "operation_context": successor.operation_context,
                "prior_operation_data_evidence_sha256": (
                    successor_denominator.prior_operation_data_evidence_sha256
                ),
                "prior_raw_snapshot_sha256": (successor_denominator.prior_raw_snapshot_sha256),
                "prior_raw_terminal_member_count": (
                    successor_denominator.prior_raw_terminal_member_count
                ),
                "prior_raw_terminal_inventory_sha256": (
                    successor_denominator.prior_raw_terminal_inventory_sha256
                ),
                "successor_execution_plan_sha256": (
                    successor_denominator.successor_execution_plan_sha256
                ),
                "planning_generation_manifest_sha256": (
                    successor_denominator.planning_generation_manifest_sha256
                ),
                "planned_route_replacement_bindings_sha256": (
                    successor_denominator.planned_route_replacement_bindings_sha256
                ),
                "dispatch_call_count": successor_denominator.dispatch_call_count,
                "dispatch_call_inventory_sha256": (
                    successor_denominator.dispatch_call_inventory_sha256
                ),
                "requested_route_binding_count": (
                    successor_denominator.requested_route_binding_count
                ),
                "requested_route_binding_inventory_sha256": (
                    successor_denominator.requested_route_binding_inventory_sha256
                ),
                "delta_terminal_locator": successor_denominator.delta_terminal_locator,
            },
        ),
        (
            VerifiedOperationRawSnapshotV1,
            {
                "operation_context": full.operation_context,
                "operation_kind": "full_extraction",
                "denominator": full_denominator,
            },
        ),
        (
            W2SourceMemberAttributionV1,
            {
                "w2_operation_sha256": attribution.w2_operation_sha256,
                "source_member_role": attribution.source_member_role,
                "source_member_sha256": attribution.source_member_sha256,
                "source_terminal_locator_sha256": (attribution.source_terminal_locator_sha256),
            },
        ),
        (W2DatabaseAuthorityReceiptV1, {}),
        (CumulativeConditionalStagingEvidenceMemberV1, {}),
        (CumulativeConditionalStagingEvidenceInventoryV1, {}),
        (
            OperationDataEvidenceV1,
            {
                "raw_snapshot": full.raw_snapshot,
                "w2_database_authority": full.w2_database_authority,
                "conditional_staging_inventory": full.conditional_staging_inventory,
            },
        ),
    )
    assert conditional_member.member_sha256
    for dto_type, kwargs in calls:
        foreign_type = type(f"ForeignSeal{dto_type.__name__}", (dto_type,), {})
        with pytest.raises(OperationDataAuthorityError, match="exact DTO class"):
            foreign_type._seal(**kwargs)


def _walk_json(value: object) -> Iterable[object]:
    yield value
    if type(value) is dict:
        for child in cast("dict[str, object]", value).values():
            yield from _walk_json(child)
    elif type(value) is list:
        for child in cast("list[object]", value):
            yield from _walk_json(child)


def test_durable_evidence_has_no_history_arrays_or_forbidden_authority_fields() -> None:
    payload = json.loads(_evidence("successor").canonical_bytes())
    forbidden_array_keys = {
        "normalized_manifest_lane_sha256s",
        "executable_members",
        "blocked_members",
        "dispatch_call_sha256s",
        "requested_route_sha256s",
        "prior_w2_operation_sha256s",
        "final_w2_operation_sha256s",
        "added_w2_operation_sha256s",
        "source_member_attributions",
        "prior_member_sha256s",
        "members",
        "added_member_sha256s",
        "staging_keys",
    }
    all_nodes = tuple(_walk_json(payload))
    all_keys = {
        key for node in all_nodes if type(node) is dict for key in cast("dict[str, object]", node)
    }

    assert forbidden_array_keys.isdisjoint(all_keys)
    assert not any(type(node) is list for node in all_nodes)
    assert not any(
        forbidden in key
        for key in all_keys
        for forbidden in ("hmac", "capability", "physical_table", "caller_map")
    )
    assert "operation_commitment_sha256" not in all_keys


def test_operation_data_evidence_remains_non_admitting_precommit_evidence() -> None:
    assert "Non-admitting" in cast("str", OperationDataEvidenceV1.__doc__)
    public_names = set(authority.__all__)
    assert not any(name.startswith(("admit", "compile", "verify")) for name in public_names)
    source = inspect.getsource(authority)
    assert "orchestrate" not in source
    # The layering guard targets engine usage, not a snapshot-digest field
    # name: the codec carries `duckdb_snapshot_sha256` as opaque metadata.
    assert "import duckdb" not in source
    assert "duckdb." not in source
    assert "operation_commitment" not in source
