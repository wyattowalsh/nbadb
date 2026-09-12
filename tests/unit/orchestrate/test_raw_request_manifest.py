from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nbadb.orchestrate.raw_request_manifest import (
    RawRequestAuthorityManifestError,
    RawRequestAuthorityManifestV2,
    parse_raw_request_authority_manifest,
    recompute_raw_request_authority_manifest,
    validate_raw_request_authority_manifest,
    validate_raw_request_authority_manifest_roll_forward,
)
from nbadb.orchestrate.raw_request_store import (
    RawRequestAuthorityPersistenceReceiptV2,
    RawRequestClosureCallV2,
    RawRequestPersistedAttemptV2,
)


def _sha(label: str) -> str:
    import hashlib

    return hashlib.sha256(label.encode()).hexdigest()


def _sha_payload(value: object) -> str:
    import hashlib

    return hashlib.sha256(_canonical(value)).hexdigest()


_EXPECTED_CALL = RawRequestClosureCallV2.build(
    endpoint_name="fixture_endpoint",
    source_family="stats",
    endpoint_id="FixtureEndpoint",
    logical_parameters_sha256=_sha("logical-parameters"),
    provider_parameters_sha256=_sha("provider-parameters"),
    provider_request_sha256=_sha("provider-request"),
    route_ids=("fixture_endpoint:stg_fixture:0",),
    scope_sha256=_sha("scope"),
)

_SECOND_EXPECTED_CALL = RawRequestClosureCallV2.build(
    endpoint_name="second_fixture_endpoint",
    source_family="stats",
    endpoint_id="SecondFixtureEndpoint",
    logical_parameters_sha256=_sha("second-logical-parameters"),
    provider_parameters_sha256=_sha("second-provider-parameters"),
    provider_request_sha256=_sha("second-provider-request"),
    route_ids=("second_fixture_endpoint:stg_second_fixture:0",),
    scope_sha256=_sha("second-scope"),
)


def _scope_for_calls(calls: tuple[RawRequestClosureCallV2, ...]) -> str:
    ordered = tuple(sorted(calls, key=lambda item: item.logical_request_sha256))
    if len(ordered) == 1:
        return ordered[0].scope_sha256
    return _sha_payload(
        {
            "schema_version": 2,
            "kind": "nbadb_raw_request_composite_scope_v2",
            "logical_requests": [
                {
                    "logical_request_sha256": item.logical_request_sha256,
                    "scope_sha256": item.scope_sha256,
                }
                for item in ordered
            ],
        }
    )


def _receipt(
    marker: int,
    *,
    bundle_sha256: str | None = None,
    replayed: bool = False,
) -> RawRequestAuthorityPersistenceReceiptV2:
    return RawRequestAuthorityPersistenceReceiptV2(
        bundle_sha256=bundle_sha256 or _sha(f"bundle:{marker}"),
        object_count=marker % 3,
        observation_count=0,
        occurrence_count=marker % 7,
        landing_count=marker % 5,
        object_inventory_sha256=_sha(f"objects:{marker}"),
        observation_inventory_sha256=_sha(f"observations:{marker}"),
        occurrence_inventory_sha256=_sha(f"occurrences:{marker}"),
        landing_inventory_sha256=_sha(f"landings:{marker}"),
        object_rows_sha256=_sha(f"object-rows:{marker}"),
        observation_rows_sha256=_sha(f"observation-rows:{marker}"),
        occurrence_rows_sha256=_sha(f"occurrence-rows:{marker}"),
        landing_rows_sha256=_sha(f"landing-rows:{marker}"),
        attempts=(),
        attempt_count=0,
        attempt_inventory_sha256=_sha_payload([]),
        replayed=replayed,
    )


def _attempt_receipt(
    marker: str,
    *,
    call: RawRequestClosureCallV2 = _EXPECTED_CALL,
    retry_ordinal: int = 0,
    lifecycle: str = "selected_terminal",
    outcome: str = "success_nonempty",
    provider_call_sha256: str | None = None,
    provider_call_role: str = "primary",
    provider_call_ordinal: int = 0,
    request_ordinal: int = 0,
    logical_parameters_sha256: str | None = None,
    safe_parameters_sha256: str | None = None,
) -> RawRequestAuthorityPersistenceReceiptV2:
    attempt = RawRequestPersistedAttemptV2(
        observation_sha256=_sha(f"observation:{marker}"),
        observation_record_sha256=_sha(f"observation-record:{marker}"),
        semantic_request_sha256=_sha("semantic-request"),
        logical_invocation_sha256=_sha("logical-invocation"),
        provider_call_sha256=provider_call_sha256 or _sha("provider-call"),
        provider_call_role=provider_call_role,
        provider_call_ordinal=provider_call_ordinal,
        retry_ordinal=retry_ordinal,
        request_ordinal=request_ordinal,
        source_family=call.source_family,
        endpoint_id=call.endpoint_id,
        provider_request_sha256=call.provider_request_sha256,
        logical_parameters_sha256=(logical_parameters_sha256 or call.logical_parameters_sha256),
        safe_parameters_sha256=(
            safe_parameters_sha256
            or call.provider_parameters_sha256
            or call.logical_parameters_sha256
        ),
        scope_sha256=call.scope_sha256,
        lifecycle=lifecycle,
        outcome=outcome,
        route_ids=call.route_ids if lifecycle == "selected_terminal" else (),
    )
    return RawRequestAuthorityPersistenceReceiptV2(
        bundle_sha256=_sha(f"bundle:{marker}"),
        object_count=0,
        observation_count=1,
        occurrence_count=len(attempt.route_ids),
        landing_count=len(attempt.route_ids),
        object_inventory_sha256=_sha(f"objects:{marker}"),
        observation_inventory_sha256=_sha(f"observations:{marker}"),
        occurrence_inventory_sha256=_sha(f"occurrences:{marker}"),
        landing_inventory_sha256=_sha(f"landings:{marker}"),
        object_rows_sha256=_sha(f"object-rows:{marker}"),
        observation_rows_sha256=_sha(f"observation-rows:{marker}"),
        occurrence_rows_sha256=_sha(f"occurrence-rows:{marker}"),
        landing_rows_sha256=_sha(f"landing-rows:{marker}"),
        attempts=(attempt,),
        attempt_count=1,
        attempt_inventory_sha256=_sha_payload([attempt.to_dict()]),
        replayed=False,
    )


def _manifest(
    receipts: tuple[RawRequestAuthorityPersistenceReceiptV2, ...] = (),
    **overrides: object,
) -> RawRequestAuthorityManifestV2:
    values: dict[str, object] = {
        "source_sha": "a" * 40,
        "run_id": 101,
        "run_attempt": 1,
        "chain_id": "chain.public",
        "lane_id": "lane.stats.0001",
        "scope_sha256": _sha("scope"),
        "route_authority_sha256": _sha("routes"),
        "request_closure_authority_sha256": _sha("request-closure"),
        "field_authority_sha256": _sha("fields"),
        "model_authority_sha256": _sha("models"),
        "expected_calls": (_EXPECTED_CALL,),
        "receipts": receipts,
    }
    values.update(overrides)
    return RawRequestAuthorityManifestV2.seal(**values)  # type: ignore[arg-type]


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def test_root_manifest_round_trips_and_independently_recomputes() -> None:
    manifest = _manifest((_receipt(3), _receipt(1), _receipt(2, replayed=True)))

    assert tuple(item.bundle_sha256 for item in manifest.receipts) == tuple(
        item.bundle_sha256
        for item in sorted(manifest.receipts, key=lambda item: item.receipt_sha256)
    )
    assert manifest.receipt_count == 3
    assert all(not receipt.replayed for receipt in manifest.receipts)
    assert manifest.delta_receipt_count == 3
    assert manifest.delta_receipt_sha256s == tuple(
        item.receipt_sha256 for item in manifest.receipts
    )
    assert parse_raw_request_authority_manifest(manifest.canonical_bytes) == manifest
    assert recompute_raw_request_authority_manifest(manifest) == manifest
    assert validate_raw_request_authority_manifest(manifest) == manifest
    assert manifest.manifest_sha256 == _sha256_semantic(manifest)


def test_replayed_relabel_is_non_authoritative_across_root_and_delta() -> None:
    initial = _receipt(1)
    delta = _receipt(2)

    ordinary_root = _manifest((initial,))
    relabelled_root = _manifest((replace(initial, replayed=True),))
    ordinary_child = ordinary_root.roll_forward((delta,))
    relabelled_child = relabelled_root.roll_forward((replace(delta, replayed=True),))

    assert ordinary_root == relabelled_root
    assert ordinary_root.canonical_bytes == relabelled_root.canonical_bytes
    assert ordinary_child == relabelled_child
    assert ordinary_child.manifest_sha256 == relabelled_child.manifest_sha256
    assert ordinary_child.receipt_inventory_sha256 == relabelled_child.receipt_inventory_sha256
    assert (
        ordinary_child.delta_receipt_inventory_sha256
        == relabelled_child.delta_receipt_inventory_sha256
    )
    assert all(not receipt.replayed for receipt in relabelled_child.receipts)


def test_parser_rejects_fully_resealed_replayed_manifest_receipt() -> None:
    payload = _manifest((_receipt(1),)).to_dict()
    receipt = payload["receipts"][0]  # type: ignore[index]
    receipt["replayed"] = True  # type: ignore[index]
    payload["receipt_inventory_sha256"] = _sha_payload(payload["receipts"])
    payload["delta_receipt_inventory_sha256"] = _sha_payload(payload["receipts"])
    semantic = dict(payload)
    semantic.pop("manifest_sha256")
    payload["manifest_sha256"] = _sha_payload(semantic)

    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="replay-independent authority projection",
    ):
        parse_raw_request_authority_manifest(_canonical(payload))


def _sha256_semantic(manifest: RawRequestAuthorityManifestV2) -> str:
    import hashlib

    payload = manifest.to_dict()
    payload.pop("manifest_sha256")
    return hashlib.sha256(_canonical(payload)).hexdigest()


def test_copy_plus_delta_conserves_parent_and_exposes_only_added_receipts() -> None:
    first = _receipt(1)
    second = _receipt(2)
    parent = _manifest((first,))

    child = parent.roll_forward((second,))

    assert child.generation == 1
    assert child.parent_manifest_sha256 == parent.manifest_sha256
    assert child.receipt_count == 2
    assert child.delta_receipt_sha256s == (second.receipt_sha256,)
    assert child.delta_object_reference_count == second.object_count
    assert child.delta_observation_reference_count == second.observation_count
    assert child.delta_occurrence_reference_count == second.occurrence_count
    assert child.delta_landing_reference_count == second.landing_count
    assert child.delta_landing_inventory_sha256 != child.landing_inventory_sha256
    assert child.delta_landing_rows_sha256 != child.landing_rows_sha256
    assert validate_raw_request_authority_manifest_roll_forward(parent, child) == child


def test_zero_delta_generations_remain_distinct_and_conserve_receipts() -> None:
    root = _manifest((_receipt(1),))

    zero_one = root.roll_forward(())
    zero_two = zero_one.roll_forward(())

    assert zero_one.receipts == root.receipts
    assert zero_one.delta_receipt_sha256s == ()
    assert zero_one.delta_receipt_count == 0
    assert zero_one.manifest_sha256 != root.manifest_sha256
    assert zero_two.generation == 2
    assert zero_two.parent_manifest_sha256 == zero_one.manifest_sha256
    assert len({root.manifest_sha256, zero_one.manifest_sha256, zero_two.manifest_sha256}) == 3
    assert parse_raw_request_authority_manifest(zero_two.canonical_bytes) == zero_two


@pytest.mark.parametrize("terminal_argument", [False, True])
def test_terminal_roll_forward_is_monotonic_and_zero_delta_idempotent(
    terminal_argument: bool,
) -> None:
    parent = _manifest((_attempt_receipt("terminal-parent"),), terminal=True)

    child = parent.roll_forward((), terminal=terminal_argument)

    assert child.generation == parent.generation + 1
    assert child.parent_manifest_sha256 == parent.manifest_sha256
    assert child.receipts == parent.receipts
    assert child.delta_receipt_sha256s == ()
    assert child.coverage_complete is child.terminal_sealed is child.is_complete is True
    assert validate_raw_request_authority_manifest_roll_forward(parent, child) == child


def test_roll_forward_verifier_rejects_parsed_forged_terminal_downgrade() -> None:
    parent = _manifest((_attempt_receipt("terminal-parent"),), terminal=True)
    forged = RawRequestAuthorityManifestV2._from_parts(
        source_sha=parent.source_sha,
        run_id=parent.run_id,
        run_attempt=parent.run_attempt,
        chain_id=parent.chain_id,
        lane_id=parent.lane_id,
        scope_sha256=parent.scope_sha256,
        generation=parent.generation + 1,
        parent_manifest_sha256=parent.manifest_sha256,
        route_authority_sha256=parent.route_authority_sha256,
        request_closure_authority_sha256=parent.request_closure_authority_sha256,
        field_authority_sha256=parent.field_authority_sha256,
        model_authority_sha256=parent.model_authority_sha256,
        expected_calls=parent.expected_calls,
        receipts=parent.receipts,
        delta_receipt_sha256s=(),
        terminal_sealed=False,
    )
    parsed = parse_raw_request_authority_manifest(forged.canonical_bytes)

    assert parsed.terminal_sealed is parsed.is_complete is False
    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="downgraded terminal completeness",
    ):
        validate_raw_request_authority_manifest_roll_forward(parent, parsed)


@pytest.mark.parametrize(
    ("lifecycle", "outcome"),
    [
        ("incomplete", "transport_failure_no_response"),
        ("selected_terminal", "success_nonempty"),
    ],
)
def test_terminal_manifest_rejects_any_genuinely_new_retry_delta(
    lifecycle: str,
    outcome: str,
) -> None:
    parent = _manifest((_attempt_receipt("terminal-parent"),), terminal=True)
    delta = _attempt_receipt(
        f"new-{lifecycle}",
        retry_ordinal=1,
        lifecycle=lifecycle,
        outcome=outcome,
    )

    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="terminal manifest cannot accept a new receipt delta",
    ):
        parent.roll_forward((delta,), terminal=False)


def test_partial_manifest_exposes_exact_missing_inventory_and_terminal_rejects_it() -> None:
    calls = tuple(
        sorted(
            (_EXPECTED_CALL, _SECOND_EXPECTED_CALL),
            key=lambda item: item.logical_request_sha256,
        )
    )
    first = _attempt_receipt("first", call=_EXPECTED_CALL)

    partial = _manifest(
        (first,),
        expected_calls=calls,
        scope_sha256=_scope_for_calls(calls),
    )

    assert partial.expected_request_sha256s == tuple(item.logical_request_sha256 for item in calls)
    assert partial.completed_request_sha256s == (_EXPECTED_CALL.logical_request_sha256,)
    assert partial.unresolved_request_sha256s == (_SECOND_EXPECTED_CALL.logical_request_sha256,)
    assert partial.coverage_complete is False
    assert partial.terminal_sealed is False
    assert partial.is_complete is False
    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="terminal sealing rejects unresolved closure calls",
    ):
        _manifest(
            (first,),
            expected_calls=calls,
            scope_sha256=_scope_for_calls(calls),
            terminal=True,
        )

    complete = _manifest(
        (first, _attempt_receipt("second", call=_SECOND_EXPECTED_CALL)),
        expected_calls=calls,
        scope_sha256=_scope_for_calls(calls),
        terminal=True,
    )
    assert complete.unresolved_request_sha256s == ()
    assert complete.coverage_complete is complete.terminal_sealed is complete.is_complete is True


def test_unplanned_2023_24_request_always_rejects() -> None:
    unplanned = RawRequestClosureCallV2.build(
        endpoint_name=_EXPECTED_CALL.endpoint_name,
        source_family=_EXPECTED_CALL.source_family,
        endpoint_id=_EXPECTED_CALL.endpoint_id,
        logical_parameters_sha256=_sha("season:2023-24"),
        provider_parameters_sha256=_sha("provider-season:2023-24"),
        provider_request_sha256=_sha("provider-request:2023-24"),
        route_ids=_EXPECTED_CALL.route_ids,
        scope_sha256=_EXPECTED_CALL.scope_sha256,
    )

    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="outside the exact closure denominator",
    ):
        _manifest((_attempt_receipt("2023-24", call=unplanned),))


def test_denominator_rejects_foreign_provider_parameter_digest() -> None:
    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="differs from its exact closure call",
    ):
        _manifest(
            (
                _attempt_receipt(
                    "foreign-safe-parameters",
                    safe_parameters_sha256=_sha("foreign-provider-parameters"),
                ),
            ),
            terminal=True,
        )


def test_denominator_rejects_foreign_logical_parameter_digest() -> None:
    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="differs from its exact closure call",
    ):
        _manifest(
            (
                _attempt_receipt(
                    "foreign-logical-parameters",
                    logical_parameters_sha256=_sha("foreign-logical-parameters"),
                ),
            ),
            terminal=True,
        )


def test_denominator_rejects_cross_bound_logical_and_provider_digests() -> None:
    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="differs from its exact closure call",
    ):
        _manifest(
            (
                _attempt_receipt(
                    "cross-bound-parameters",
                    logical_parameters_sha256=cast(
                        "str", _EXPECTED_CALL.provider_parameters_sha256
                    ),
                    safe_parameters_sha256=_EXPECTED_CALL.logical_parameters_sha256,
                ),
            ),
            terminal=True,
        )


def test_denominator_rejects_missing_provider_parameter_authority() -> None:
    missing_provider = RawRequestClosureCallV2.build(
        endpoint_name=_EXPECTED_CALL.endpoint_name,
        source_family=_EXPECTED_CALL.source_family,
        endpoint_id=_EXPECTED_CALL.endpoint_id,
        logical_parameters_sha256=_EXPECTED_CALL.logical_parameters_sha256,
        provider_parameters_sha256=None,
        provider_request_sha256=_EXPECTED_CALL.provider_request_sha256,
        route_ids=_EXPECTED_CALL.route_ids,
        scope_sha256=_EXPECTED_CALL.scope_sha256,
    )

    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="lacks provider parameter authority",
    ):
        _manifest(
            (_attempt_receipt("missing-provider", call=missing_provider),),
            expected_calls=(missing_provider,),
            terminal=True,
        )


def test_parser_rejects_legacy_attempt_without_distinct_logical_digest() -> None:
    payload = _manifest(
        (_attempt_receipt("legacy-attempt"),),
        terminal=True,
    ).to_dict()
    attempts = payload["receipts"][0]["attempts"]  # type: ignore[index]
    attempts[0].pop("logical_parameters_sha256")

    with pytest.raises(RawRequestAuthorityManifestError):
        parse_raw_request_authority_manifest(_canonical(payload))


def test_retry_inventory_requires_zero_based_contiguous_prefix() -> None:
    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="exact retry prefix",
    ):
        _manifest((_attempt_receipt("retry-one", retry_ordinal=1),))


def test_unplanned_provider_call_shape_rejects_without_widening_scope() -> None:
    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="unplanned provider-call shape",
    ):
        _manifest(
            (
                _attempt_receipt(
                    "extra-call",
                    provider_call_ordinal=1,
                    request_ordinal=1,
                ),
            )
        )


@pytest.mark.parametrize(
    "override",
    [
        {"source_sha": "b" * 40},
        {"run_id": 102},
        {"run_attempt": 2},
        {"chain_id": "another.chain"},
        {"lane_id": "another.lane"},
        {"scope_sha256": _sha("other-scope")},
        {"route_authority_sha256": _sha("other-routes")},
        {"request_closure_authority_sha256": _sha("other-closure")},
        {"field_authority_sha256": _sha("other-fields")},
        {"model_authority_sha256": _sha("other-models")},
    ],
)
def test_copy_plus_delta_rejects_foreign_lineage_or_authority(
    override: dict[str, object],
) -> None:
    parent = _manifest((_receipt(1),))

    with pytest.raises(RawRequestAuthorityManifestError, match="foreign lineage|authority"):
        parent.roll_forward((_receipt(2),), **override)  # type: ignore[arg-type]


def test_copy_plus_delta_rejects_parent_receipt_or_bundle_duplicates() -> None:
    parent_receipt = _receipt(1)
    parent = _manifest((parent_receipt,))
    same_bundle_different_receipt = _receipt(2, bundle_sha256=parent_receipt.bundle_sha256)

    with pytest.raises(RawRequestAuthorityManifestError, match="parent receipt"):
        parent.roll_forward((replace(parent_receipt, replayed=True),))
    with pytest.raises(RawRequestAuthorityManifestError, match="parent bundle"):
        parent.roll_forward((same_bundle_different_receipt,))


def test_manifest_rejects_duplicates_within_root_and_delta() -> None:
    receipt = _receipt(1)

    with pytest.raises(RawRequestAuthorityManifestError, match="duplicate receipt"):
        _manifest((receipt, receipt))

    parent = _manifest((receipt,))
    delta = _receipt(2)
    with pytest.raises(RawRequestAuthorityManifestError, match="duplicate receipt"):
        parent.roll_forward((delta, delta))


def test_manifest_rejects_duplicate_bundle_with_different_receipt() -> None:
    first = _receipt(1)
    second = _receipt(2, bundle_sha256=first.bundle_sha256)

    with pytest.raises(RawRequestAuthorityManifestError, match="duplicate bundle"):
        _manifest((first, second))


def test_roll_forward_verifier_normalizes_replayed_parent_receipt_relabel() -> None:
    original = _receipt(1)
    parent = _manifest((original,))
    changed = replace(original, replayed=True)
    child = RawRequestAuthorityManifestV2._from_parts(
        source_sha=parent.source_sha,
        run_id=parent.run_id,
        run_attempt=parent.run_attempt,
        chain_id=parent.chain_id,
        lane_id=parent.lane_id,
        scope_sha256=parent.scope_sha256,
        generation=1,
        parent_manifest_sha256=parent.manifest_sha256,
        route_authority_sha256=parent.route_authority_sha256,
        request_closure_authority_sha256=parent.request_closure_authority_sha256,
        field_authority_sha256=parent.field_authority_sha256,
        model_authority_sha256=parent.model_authority_sha256,
        expected_calls=parent.expected_calls,
        receipts=(changed,),
        delta_receipt_sha256s=(),
        terminal_sealed=False,
    )

    assert child.receipts == parent.receipts
    assert validate_raw_request_authority_manifest_roll_forward(parent, child) == child


@pytest.mark.parametrize(
    "field_name,replacement",
    [
        ("receipt_count", 99),
        ("object_reference_count", 99),
        ("observation_reference_count", 99),
        ("occurrence_reference_count", 99),
        ("landing_reference_count", 99),
        ("receipt_inventory_sha256", "0" * 64),
        ("bundle_inventory_sha256", "0" * 64),
        ("object_inventory_sha256", "0" * 64),
        ("observation_inventory_sha256", "0" * 64),
        ("occurrence_inventory_sha256", "0" * 64),
        ("landing_inventory_sha256", "0" * 64),
        ("object_rows_sha256", "0" * 64),
        ("observation_rows_sha256", "0" * 64),
        ("occurrence_rows_sha256", "0" * 64),
        ("landing_rows_sha256", "0" * 64),
        ("delta_receipt_count", 99),
        ("delta_object_reference_count", 99),
        ("delta_observation_reference_count", 99),
        ("delta_occurrence_reference_count", 99),
        ("delta_landing_reference_count", 99),
        ("delta_landing_inventory_sha256", "0" * 64),
        ("delta_object_rows_sha256", "0" * 64),
        ("delta_observation_rows_sha256", "0" * 64),
        ("delta_occurrence_rows_sha256", "0" * 64),
        ("delta_landing_rows_sha256", "0" * 64),
        ("delta_receipt_inventory_sha256", "0" * 64),
        ("authority_set_sha256", "0" * 64),
        ("manifest_sha256", "0" * 64),
    ],
)
def test_parser_rejects_counter_inventory_and_digest_mutations(
    field_name: str,
    replacement: object,
) -> None:
    payload = _manifest((_receipt(1), _receipt(2))).to_dict()
    payload[field_name] = replacement

    with pytest.raises(RawRequestAuthorityManifestError):
        parse_raw_request_authority_manifest(_canonical(payload))


def test_parser_rejects_receipt_mutation_even_if_manifest_digest_is_unchanged() -> None:
    payload = _manifest((_receipt(1),)).to_dict()
    receipt = payload["receipts"][0]  # type: ignore[index]
    receipt["observation_count"] = 88  # type: ignore[index]

    with pytest.raises(
        RawRequestAuthorityManifestError,
        match="persistence receipt is invalid|receipt digest",
    ):
        parse_raw_request_authority_manifest(_canonical(payload))


@pytest.mark.parametrize(
    "identity",
    [
        {"chain_id": "contains_token_value"},
        {"lane_id": "runner.path.private"},
        {"lane_id": "vpn-lane"},
        {"chain_id": "/tmp/not-path-free"},
    ],
)
def test_manifest_rejects_secret_or_path_bearing_identities(identity: dict[str, object]) -> None:
    with pytest.raises(RawRequestAuthorityManifestError, match="public-safe"):
        _manifest((_receipt(1),), **identity)


def test_manifest_rejects_caller_known_secret_bytes_on_seal_and_parse() -> None:
    manifest = _manifest((_receipt(1),))

    with pytest.raises(RawRequestAuthorityManifestError, match="known secret"):
        _manifest((_receipt(1),), known_secrets=(manifest.source_sha,))
    with pytest.raises(RawRequestAuthorityManifestError, match="known secret"):
        parse_raw_request_authority_manifest(
            manifest.canonical_bytes,
            known_secrets=(manifest.chain_id,),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw + b"\n",
        lambda raw: b"\xef\xbb\xbf" + raw,
        lambda raw: raw.replace(b'"run_id":101', b'"run_id":true'),
        lambda raw: raw.replace(b'"schema_version":2', b'"schema_version":1', 1),
    ],
)
def test_parser_rejects_noncanonical_or_wrongly_typed_bytes(mutation: object) -> None:
    raw = _manifest((_receipt(1),)).canonical_bytes

    with pytest.raises(RawRequestAuthorityManifestError):
        parse_raw_request_authority_manifest(mutation(raw))  # type: ignore[operator]


def test_aggregate_counter_overflow_fails_closed() -> None:
    first = replace(_receipt(1), object_count=2**63 - 1)
    second = replace(_receipt(2), object_count=2**63 - 1)

    with pytest.raises(RawRequestAuthorityManifestError, match="bounded counter"):
        _manifest((first, second))


def test_seal_and_parse_share_one_bounded_byte_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    import nbadb.orchestrate.raw_request_manifest as contract

    manifest = _manifest((_receipt(1),))
    monkeypatch.setattr(contract, "_MAX_MANIFEST_BYTES", len(manifest.canonical_bytes) - 1)

    with pytest.raises(RawRequestAuthorityManifestError, match="byte limit"):
        _manifest((_receipt(1),))
    with pytest.raises(RawRequestAuthorityManifestError, match="byte envelope"):
        parse_raw_request_authority_manifest(manifest.canonical_bytes)


@settings(max_examples=50, deadline=None)
@given(
    st.lists(
        st.integers(min_value=0, max_value=10_000),
        unique=True,
        min_size=1,
        max_size=20,
    )
)
def test_receipt_permutations_have_one_canonical_manifest(markers: list[int]) -> None:
    receipts = tuple(_receipt(marker) for marker in markers)

    forward = _manifest(receipts)
    reverse = _manifest(tuple(reversed(receipts)))

    assert forward == reverse
    assert forward.canonical_bytes == reverse.canonical_bytes
    assert parse_raw_request_authority_manifest(forward.canonical_bytes) == forward


@settings(max_examples=40, deadline=None)
@given(
    st.lists(st.integers(min_value=0, max_value=10_000), unique=True, min_size=1, max_size=15),
    st.sampled_from(
        [
            "receipt_count",
            "object_reference_count",
            "observation_reference_count",
            "occurrence_reference_count",
            "landing_reference_count",
            "delta_receipt_count",
            "delta_landing_reference_count",
        ]
    ),
)
def test_property_counter_mutations_never_parse(markers: list[int], field_name: str) -> None:
    payload = _manifest(tuple(_receipt(marker) for marker in markers)).to_dict()
    payload[field_name] = int(payload[field_name]) + 1

    with pytest.raises(RawRequestAuthorityManifestError):
        parse_raw_request_authority_manifest(_canonical(payload))
