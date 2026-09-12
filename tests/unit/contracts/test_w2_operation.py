from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import fields, replace
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

import nbadb.contracts.w2_operation as w2
from nbadb.contracts.raw_request_authority import (
    RequestAttemptIdentityV2,
    RequestObservationV2,
)
from nbadb.contracts.w2_operation import (
    W2OperationError,
    W2OperationKeyV1,
    W2OperationPersistenceReceiptV1,
    W2OperationReceiptV1,
)
from tests.unit.contracts.test_raw_request_authority import (
    _STARTED_AT,
    _attempt,
    _sha,
    _video_bundle,
)


class _IntSubclass(int):
    pass


class _TextSubclass(str):
    pass


def _observation(
    attempt: RequestAttemptIdentityV2,
    *,
    response_marker: str = "body",
    elapsed_ns: int = 1,
) -> RequestObservationV2:
    transport_kind = "live_http" if attempt.source_family == "live" else "stats_http"
    return RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": transport_kind,
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=elapsed_ns,
        lifecycle="incomplete",
        outcome="downstream_incomplete",
        failure_class="response_contract",
        root_exception_class="ResponseContractError",
        body_disposition="public_parser_input",
        body_object_sha256=_sha(response_marker),
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[],
        route_landing_sha256s=[],
        capture_response_receipt_sha256=_sha(f"capture:{response_marker}"),
        logical_receipt_sha256=None,
    )


def _failure_observation(attempt: RequestAttemptIdentityV2) -> RequestObservationV2:
    transport_kind = "live_http" if attempt.source_family == "live" else "stats_http"
    return RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": transport_kind,
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=2),
        elapsed_ns=2,
        lifecycle="incomplete",
        outcome="parser_failure",
        failure_class="response_contract",
        root_exception_class="ResponseContractError",
        body_disposition="excluded_failure_body",
        body_object_sha256=None,
        bodyless_evidence_sha256=_sha("excluded-failure-body"),
        result_occurrence_sha256s=[],
        route_landing_sha256s=[],
        capture_response_receipt_sha256=None,
        logical_receipt_sha256=None,
    )


def _attempt_variant(
    base: RequestAttemptIdentityV2,
    *,
    provider_call_ordinal: int | None = None,
    retry_ordinal: int | None = None,
    request_ordinal: int | None = None,
    pagination_sha256: str | None | object = ...,  # type: ignore[assignment]
    page_ordinal: int | None | object = ...,  # type: ignore[assignment]
) -> RequestAttemptIdentityV2:
    raw_parameters = json.loads(base.safe_parameters_json)
    assert type(raw_parameters) is dict
    return RequestAttemptIdentityV2.build(
        semantic_request_sha256=base.semantic_request_sha256,
        logical_invocation_sha256=base.logical_invocation_sha256,
        provider_call_role=base.provider_call_role,
        provider_call_ordinal=(
            base.provider_call_ordinal if provider_call_ordinal is None else provider_call_ordinal
        ),
        retry_ordinal=base.retry_ordinal if retry_ordinal is None else retry_ordinal,
        request_ordinal=base.request_ordinal if request_ordinal is None else request_ordinal,
        source_family=base.source_family,
        endpoint_id=base.endpoint_id,
        parameters=cast("dict[str, object]", raw_parameters),
        provider_authority_sha256=base.provider_authority_sha256,
        endpoint_contract_sha256=base.endpoint_contract_sha256,
        competition_id=base.competition_id,
        competition_identity_sha256=base.competition_identity_sha256,
        scope_sha256=base.scope_sha256,
        pagination_sha256=(
            base.pagination_sha256
            if pagination_sha256 is ...
            else cast("str | None", pagination_sha256)
        ),
        page_ordinal=(
            base.page_ordinal if page_ordinal is ... else cast("int | None", page_ordinal)
        ),
        source_sha=base.source_sha,
        run_id=base.run_id,
        run_attempt=base.run_attempt,
        chain_id=base.chain_id,
        lane_id=base.lane_id,
    )


def _operation_key() -> tuple[W2OperationKeyV1, str]:
    bundle, selected, _occurrences, _landings = _video_bundle("VideoDetails", {})
    return W2OperationKeyV1.build((selected,)), bundle.bundle_sha256


def _empty_values(bundle: str) -> dict[str, object]:
    values: dict[str, object] = {
        "raw_authority_bundle_sha256": bundle,
        "committed_staging_readback_count": 0,
        "committed_staging_readback_root_sha256": (
            w2.w2_committed_staging_readback_root(
                raw_authority_bundle_sha256=bundle,
                readback_receipt_sha256s=(),
            )
        ),
        "body_value_projection_receipt_sha256": _sha("body-receipt"),
        "body_projection_policy_sha256": _sha("body-policy"),
        "body_blob_inventory_sha256": _sha("body-inventory"),
        "body_blob_count": 0,
        "body_blob_root_sha256": w2._body_projection_root(
            kind=w2._BODY_EMPTY_ROOT_KINDS["body_blob_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "body_blob_readback_count": 0,
        "body_blob_readback_root_sha256": w2._body_projection_root(
            kind=w2._BODY_EMPTY_ROOT_KINDS["body_blob_readback_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "body_blob_byte_count": 0,
        "parser_input_object_count": 0,
        "parser_input_object_root_sha256": w2._body_projection_root(
            kind=w2._BODY_EMPTY_ROOT_KINDS["parser_input_object_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "declared_bodyless_authority_sha256": _sha("bodyless-authority"),
        "bodyless_packet_count": 0,
        "bodyless_packet_root_sha256": w2._body_projection_root(
            kind=w2._BODY_EMPTY_ROOT_KINDS["bodyless_packet_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "bodyless_readback_count": 0,
        "bodyless_readback_root_sha256": w2._body_projection_root(
            kind=w2._BODY_EMPTY_ROOT_KINDS["bodyless_readback_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "bodyless_packet_byte_count": 0,
        "observation_source_count": 0,
        "observation_source_root_sha256": w2._body_projection_root(
            kind=w2._BODY_EMPTY_ROOT_KINDS["observation_source_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "lossless_ownership_receipt_sha256": _sha("ownership-receipt"),
        "ownership_observation_count": 0,
        "ownership_observation_root_sha256": w2._legacy_root(
            kind=w2._OWNERSHIP_EMPTY_ROOT_KINDS["ownership_observation_root_sha256"],
            item_sha256s=(),
        ),
        "ownership_partition_count": 0,
        "ownership_partition_root_sha256": w2._legacy_root(
            kind=w2._OWNERSHIP_EMPTY_ROOT_KINDS["ownership_partition_root_sha256"],
            item_sha256s=(),
        ),
        "ownership_fixed_zero_landing_root_sha256": w2._legacy_root(
            kind="nbadb_lossless_fixed_zero_landings_v1",
            item_sha256s=(),
        ),
        "ownership_binding_count": 0,
        "ownership_binding_root_sha256": w2._legacy_root(
            kind=w2._OWNERSHIP_EMPTY_ROOT_KINDS["ownership_binding_root_sha256"],
            item_sha256s=(),
        ),
        "ownership_source_record_count": 0,
        "ownership_source_record_root_sha256": w2._legacy_root(
            kind=w2._OWNERSHIP_EMPTY_ROOT_KINDS["ownership_source_record_root_sha256"],
            item_sha256s=(),
        ),
        "expected_unit_inventory_sha256": _sha("expected-unit-inventory"),
        "expected_unit_count": 0,
        "expected_unit_root_sha256": w2._public_expected_unit_root(
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "representation_assignment_count": 0,
        "representation_assignment_root_sha256": w2._legacy_root(
            kind=w2._OWNERSHIP_EMPTY_ROOT_KINDS["representation_assignment_root_sha256"],
            item_sha256s=(),
        ),
        "route_field_landing_receipt_sha256": _sha("route-receipt"),
        "route_field_landing_count": 0,
        "route_field_landing_root_sha256": w2._route_landing_root(
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "value_projection_plan_sha256": _sha("projection-plan"),
        "public_table_value_projection_receipt_sha256": _sha("public-projection-receipt"),
        "value_projection_equality_receipt_sha256": _sha("projection-equality-receipt"),
        "projection_sha256": _sha("projection"),
        "projection_partition_count": 0,
        "projection_partition_root_sha256": w2._value_projection_root(
            kind=w2._PROJECTION_EMPTY_ROOT_KINDS["projection_partition_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "projection_item_count": 0,
        "projection_item_root_sha256": w2._value_projection_root(
            kind=w2._PROJECTION_EMPTY_ROOT_KINDS["projection_item_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "partition_equality_count": 0,
        "partition_equality_root_sha256": w2._value_projection_root(
            kind=w2._PROJECTION_EMPTY_ROOT_KINDS["partition_equality_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "item_equality_count": 0,
        "item_equality_root_sha256": w2._value_projection_root(
            kind=w2._PROJECTION_EMPTY_ROOT_KINDS["item_equality_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        ),
        "equality_root_sha256": _sha("equality-root"),
    }
    for prefix in (
        "result_cell",
        "stats_lossless",
        "live_lossless",
        "value_representation",
        "route_field_landing",
    ):
        values[f"{prefix}_schema_sha256"] = _sha(f"{prefix}-schema")
        values[f"{prefix}_row_count"] = 0
        values[f"{prefix}_row_root_sha256"] = w2._public_relation_root(
            kind=w2._PUBLIC_RELATION_EMPTY_ROOT_KINDS[f"{prefix}_row_root_sha256"],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(),
        )
    values["w2_operation_schema_sha256"] = _sha("w2-operation-schema")
    return values


def _operation() -> W2OperationReceiptV1:
    key, bundle = _operation_key()
    return W2OperationReceiptV1.build(operation_key=key, **_empty_values(bundle))


def _replay_operation(operation: W2OperationReceiptV1) -> W2OperationReceiptV1:
    return W2OperationReceiptV1.from_row(
        operation.to_row(),
        expected_operation_receipt_sha256=operation.operation_receipt_sha256,
        expected_operation_key_sha256=operation.operation_key_sha256,
        expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
        expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
    )


def _reseal_operation_row(row: dict[str, object]) -> dict[str, object]:
    payload = {
        "schema_version": 1,
        "kind": W2OperationReceiptV1.kind,
        **{
            item.name: row[item.name]
            for item in fields(W2OperationReceiptV1)
            if item.name != "operation_receipt_sha256"
        },
    }
    row["operation_receipt_sha256"] = w2._canonical_sha256(payload)
    return row


def _replay_persistence(
    receipt: W2OperationPersistenceReceiptV1,
) -> W2OperationPersistenceReceiptV1:
    return W2OperationPersistenceReceiptV1.from_row(
        receipt.to_row(),
        expected_persistence_receipt_sha256=receipt.persistence_receipt_sha256,
        expected_operation_key_sha256=receipt.operation_key_sha256,
        expected_operation_receipt_sha256=receipt.operation_receipt_sha256,
        expected_w2_operation_schema_sha256=receipt.w2_operation_schema_sha256,
        expected_operation_row_sha256=receipt.operation_row_sha256,
    )


def test_operation_key_excludes_response_body_outcome_and_bundle_content() -> None:
    _bundle, selected, _occurrences, _landings = _video_bundle("VideoDetails", {})
    left = _observation(selected.attempt, response_marker="left", elapsed_ns=1)
    right = _observation(selected.attempt, response_marker="right", elapsed_ns=999)
    left_key = W2OperationKeyV1.build((left,))
    right_key = W2OperationKeyV1.build((right,))
    failure_key = W2OperationKeyV1.build((_failure_observation(selected.attempt),))
    assert left_key == right_key
    assert left_key == failure_key
    assert left.body_object_sha256 != right.body_object_sha256
    assert left.capture_response_receipt_sha256 != right.capture_response_receipt_sha256


def test_operation_and_persistence_field_contracts_are_exact_and_acyclic() -> None:
    assert tuple(item.name for item in fields(W2OperationKeyV1)) == (
        "operation_key_sha256",
        "operation_attempt_count",
        "operation_attempt_root_sha256",
    )
    expected_operation_fields = tuple(
        """
        operation_receipt_sha256 operation_key_sha256 operation_attempt_count
        operation_attempt_root_sha256 raw_authority_bundle_sha256
        committed_staging_readback_count committed_staging_readback_root_sha256
        body_value_projection_receipt_sha256 body_projection_policy_sha256
        body_blob_inventory_sha256 body_blob_count body_blob_root_sha256
        body_blob_readback_count body_blob_readback_root_sha256 body_blob_byte_count
        parser_input_object_count parser_input_object_root_sha256
        declared_bodyless_authority_sha256 bodyless_packet_count bodyless_packet_root_sha256
        bodyless_readback_count bodyless_readback_root_sha256 bodyless_packet_byte_count
        observation_source_count observation_source_root_sha256
        lossless_ownership_receipt_sha256 ownership_observation_count
        ownership_observation_root_sha256 ownership_partition_count
        ownership_partition_root_sha256 ownership_fixed_zero_landing_root_sha256
        ownership_binding_count ownership_binding_root_sha256
        ownership_source_record_count ownership_source_record_root_sha256
        expected_unit_inventory_sha256 expected_unit_count expected_unit_root_sha256
        representation_assignment_count representation_assignment_root_sha256
        route_field_landing_receipt_sha256 route_field_landing_count
        route_field_landing_root_sha256 value_projection_plan_sha256
        public_table_value_projection_receipt_sha256
        value_projection_equality_receipt_sha256 projection_sha256
        projection_partition_count projection_partition_root_sha256
        projection_item_count projection_item_root_sha256 partition_equality_count
        partition_equality_root_sha256 item_equality_count item_equality_root_sha256
        equality_root_sha256 result_cell_schema_sha256 result_cell_row_count
        result_cell_row_root_sha256 stats_lossless_schema_sha256
        stats_lossless_row_count stats_lossless_row_root_sha256
        live_lossless_schema_sha256 live_lossless_row_count
        live_lossless_row_root_sha256 value_representation_schema_sha256
        value_representation_row_count value_representation_row_root_sha256
        route_field_landing_schema_sha256 route_field_landing_row_count
        route_field_landing_row_root_sha256 w2_operation_schema_sha256
        """.split()  # noqa: SIM905 - compact exact field-order specification
    )
    assert tuple(item.name for item in fields(W2OperationReceiptV1)) == expected_operation_fields
    assert tuple(item.name for item in fields(W2OperationPersistenceReceiptV1)) == (
        "persistence_receipt_sha256",
        "operation_key_sha256",
        "operation_receipt_sha256",
        "w2_operation_schema_sha256",
        "operation_row_sha256",
        "post_commit_readback_row_count",
        "post_commit_readback_row_sha256",
        "post_commit_readback_root_sha256",
        "replayed",
    )
    assert not (
        {"operation_row_sha256", "persistence_receipt_sha256"} & set(expected_operation_fields)
    )


def test_operation_key_binds_retry_request_page_and_semantic_order() -> None:
    _bundle, selected, _occurrences, _landings = _video_bundle("VideoDetails", {})
    base = selected.attempt
    variants = (
        _attempt_variant(base, retry_ordinal=base.retry_ordinal + 1),
        _attempt_variant(base, request_ordinal=base.request_ordinal + 1),
        _attempt_variant(
            base,
            pagination_sha256=_sha("pagination"),
            page_ordinal=1,
        ),
        _attempt_variant(base, provider_call_ordinal=base.provider_call_ordinal + 1),
    )
    baseline = W2OperationKeyV1.build((_observation(base),))
    keys = {W2OperationKeyV1.build((_observation(item),)).operation_key_sha256 for item in variants}
    assert baseline.operation_key_sha256 not in keys
    assert len(keys) == len(variants)


def test_operation_key_canonicalizes_multi_observation_input_once() -> None:
    first = _observation(_attempt(provider_call_ordinal=0), response_marker="first")
    second = _observation(_attempt(provider_call_ordinal=1), response_marker="second")
    forward = W2OperationKeyV1.build((first, second))
    reverse = W2OperationKeyV1.build((second, first))
    assert forward == reverse
    assert forward.operation_attempt_count == 2


@pytest.mark.parametrize("bad", [(object(),), (True,), (1,), ("observation",)])
def test_operation_key_rejects_foreign_observations(bad: tuple[object, ...]) -> None:
    with pytest.raises(W2OperationError, match="canonical authority"):
        W2OperationKeyV1.build(bad)  # type: ignore[arg-type]


def test_operation_key_rejects_duplicate_observations_and_non_tuple() -> None:
    observation = _observation(_attempt())
    with pytest.raises(W2OperationError, match="canonical authority"):
        W2OperationKeyV1.build((observation, observation))
    with pytest.raises(W2OperationError, match="tuple"):
        W2OperationKeyV1.build([observation])  # type: ignore[arg-type]


def test_operation_key_row_and_canonical_replay_require_external_pin() -> None:
    key, _bundle = _operation_key()
    assert (
        W2OperationKeyV1.from_row(
            key.to_row(), expected_operation_key_sha256=key.operation_key_sha256
        )
        == key
    )
    assert (
        W2OperationKeyV1.from_canonical_bytes(
            key.canonical_bytes(),
            expected_operation_key_sha256=key.operation_key_sha256,
        )
        == key
    )
    with pytest.raises(W2OperationError, match="external"):
        W2OperationKeyV1.from_row(key.to_row(), expected_operation_key_sha256=_sha("foreign-key"))


def test_operation_receipt_round_trips_exact_scalar_row_and_bytes() -> None:
    operation = _operation()
    assert _replay_operation(operation) == operation
    assert (
        W2OperationReceiptV1.from_canonical_bytes(
            operation.canonical_bytes(),
            expected_operation_receipt_sha256=operation.operation_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        )
        == operation
    )
    assert "operation_row_sha256" not in operation.to_row()
    assert "persistence_receipt_sha256" not in operation.to_row()


def _independent_framed_empty_root(
    *, prefix: bytes, kind: str, scopes: tuple[str, ...], include_schema_version: bool
) -> str:
    digest = hashlib.sha256()
    digest.update(prefix)

    def feed(raw: bytes) -> None:
        digest.update(len(raw).to_bytes(8, "big", signed=False))
        digest.update(raw)

    if include_schema_version:
        feed(b"1")
    feed(kind.encode("utf-8"))
    for scope in scopes:
        feed(scope.encode("ascii"))
    feed(b"0")
    return digest.hexdigest()


def test_empty_roots_match_independent_frozen_child_algorithms() -> None:
    operation = _operation()
    bundle = operation.raw_authority_bundle_sha256
    for root_field, kind in w2._BODY_EMPTY_ROOT_KINDS.items():
        expected = _independent_framed_empty_root(
            prefix=b"nbadb-value-projection-length-framed-root-v1\x00",
            kind=kind,
            scopes=(bundle,),
            include_schema_version=True,
        )
        assert getattr(operation, root_field) == expected
    for root_field, kind in w2._OWNERSHIP_EMPTY_ROOT_KINDS.items():
        expected = hashlib.sha256(
            json.dumps(
                {"count": 0, "items": [], "kind": kind, "schema_version": 1},
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        assert getattr(operation, root_field) == expected
    expected_units = hashlib.sha256(
        (
            '{"count":0,"items":[],"kind":"nbadb_expected_value_unit_ordered_root_v1",'
            f'"raw_authority_bundle_sha256":"{bundle}","schema_version":1}}'
        ).encode()
    ).hexdigest()
    assert operation.expected_unit_root_sha256 == expected_units
    expected_route = hashlib.sha256(
        json.dumps(
            {
                "count": 0,
                "items": [],
                "kind": "raw_nba_api_route_field_rows_v1",
                "raw_authority_bundle_sha256": bundle,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert operation.route_field_landing_root_sha256 == expected_route
    for root_field, kind in w2._PROJECTION_EMPTY_ROOT_KINDS.items():
        expected = _independent_framed_empty_root(
            prefix=b"nbadb-value-projection-length-framed-root-v1\x00",
            kind=kind,
            scopes=(bundle,),
            include_schema_version=True,
        )
        assert getattr(operation, root_field) == expected
    for root_field, kind in w2._PUBLIC_RELATION_EMPTY_ROOT_KINDS.items():
        expected = _independent_framed_empty_root(
            prefix=b"nbadb-public-table-value-projection-root-v1\x00",
            kind=kind,
            scopes=(bundle,),
            include_schema_version=False,
        )
        assert getattr(operation, root_field) == expected


@pytest.mark.parametrize(("count_field", "root_field"), w2._COUNT_ROOT_FIELDS)
def test_operation_receipt_enforces_every_empty_root_pair(
    count_field: str, root_field: str
) -> None:
    operation = _operation()
    with pytest.raises(W2OperationError, match="zero-root"):
        replace(operation, **{root_field: _sha(f"foreign:{root_field}")})
    with pytest.raises(W2OperationError):
        replace(operation, **{count_field: 1})


def test_operation_receipt_rejects_cross_child_count_and_byte_reseals() -> None:
    operation = _operation()
    for changes in (
        {"body_blob_byte_count": 1},
        {"bodyless_packet_byte_count": 1},
        {"body_blob_count": 1, "body_blob_readback_count": 2},
        {"expected_unit_count": 1, "representation_assignment_count": 2},
        {"ownership_binding_count": 1, "ownership_source_record_count": 2},
        {"route_field_landing_count": 1, "route_field_landing_row_count": 2},
        {"projection_partition_count": 1, "partition_equality_count": 2},
        {"projection_item_count": 1, "item_equality_count": 2},
    ):
        with pytest.raises(W2OperationError):
            replace(operation, **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {
                "body_blob_count": 2,
                "body_blob_readback_count": 2,
                "body_blob_byte_count": 1,
                "parser_input_object_count": 2,
                "observation_source_count": 2,
                "ownership_observation_count": 2,
                "committed_staging_readback_count": 2,
                "ownership_partition_count": 2,
                "projection_partition_count": 2,
                "partition_equality_count": 2,
            },
            "attempt count cannot be below owned observations",
        ),
        (
            {
                "body_blob_count": 1,
                "body_blob_readback_count": 1,
                "body_blob_byte_count": 1,
                "parser_input_object_count": 1,
                "observation_source_count": 1,
                "ownership_observation_count": 1,
            },
            "staging readbacks cannot be below owned observations",
        ),
        (
            {
                "body_blob_count": 1,
                "body_blob_readback_count": 1,
                "body_blob_byte_count": 1,
                "parser_input_object_count": 1,
                "observation_source_count": 1,
                "ownership_observation_count": 1,
                "committed_staging_readback_count": 1,
            },
            "ownership partitions cannot be below owned observations",
        ),
        (
            {
                "expected_unit_count": 1,
                "representation_assignment_count": 1,
                "value_representation_row_count": 1,
            },
            "ownership partitions cannot be below expected units",
        ),
        (
            {
                "ownership_partition_count": 1,
                "projection_partition_count": 1,
                "partition_equality_count": 1,
                "expected_unit_count": 1,
                "representation_assignment_count": 1,
                "value_representation_row_count": 1,
            },
            "route-field rows cannot be below expected units",
        ),
    ],
)
def test_operation_receipt_rejects_universal_scalar_lower_bound_violations(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(W2OperationError, match=message):
        replace(_operation(), **changes)


def test_operation_receipt_rejects_fully_resealed_observation_ownership_mismatch() -> None:
    operation = _operation()
    bundle = operation.raw_authority_bundle_sha256
    row = operation.to_row()
    item_sha256 = _sha("coordinated-observation-source")
    for count_field, root_field in (
        ("body_blob_count", "body_blob_root_sha256"),
        ("body_blob_readback_count", "body_blob_readback_root_sha256"),
        ("parser_input_object_count", "parser_input_object_root_sha256"),
        ("observation_source_count", "observation_source_root_sha256"),
    ):
        row[count_field] = 1
        row[root_field] = w2._body_projection_root(
            kind=w2._BODY_EMPTY_ROOT_KINDS[root_field],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(item_sha256,),
        )
    row["body_blob_byte_count"] = 1
    _reseal_operation_row(row)
    new_receipt_sha256 = cast("str", row["operation_receipt_sha256"])

    with pytest.raises(W2OperationError, match="ownership/source observation"):
        W2OperationReceiptV1.from_row(
            row,
            expected_operation_receipt_sha256=new_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=bundle,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        )


def test_operation_receipt_rejects_fully_resealed_ownership_projection_partition_mismatch() -> None:
    operation = _operation()
    row = operation.to_row()
    row["ownership_partition_count"] = 1
    row["ownership_partition_root_sha256"] = w2._legacy_root(
        kind=w2._OWNERSHIP_EMPTY_ROOT_KINDS["ownership_partition_root_sha256"],
        item_sha256s=(_sha("coordinated-ownership-partition"),),
    )
    _reseal_operation_row(row)
    new_receipt_sha256 = cast("str", row["operation_receipt_sha256"])

    with pytest.raises(W2OperationError, match="ownership/projection partition"):
        W2OperationReceiptV1.from_row(
            row,
            expected_operation_receipt_sha256=new_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        )


def test_operation_receipt_rejects_fully_resealed_ownership_projection_item_mismatch() -> None:
    operation = _operation()
    row = operation.to_row()
    item_sha256 = _sha("coordinated-ownership-item")
    for count_field, root_field in (
        ("ownership_binding_count", "ownership_binding_root_sha256"),
        ("ownership_source_record_count", "ownership_source_record_root_sha256"),
    ):
        row[count_field] = 1
        row[root_field] = w2._legacy_root(
            kind=w2._OWNERSHIP_EMPTY_ROOT_KINDS[root_field],
            item_sha256s=(item_sha256,),
        )
    _reseal_operation_row(row)
    new_receipt_sha256 = cast("str", row["operation_receipt_sha256"])

    with pytest.raises(W2OperationError, match="projection-item"):
        W2OperationReceiptV1.from_row(
            row,
            expected_operation_receipt_sha256=new_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        )


def test_operation_receipt_rejects_fully_resealed_public_data_row_union_mismatch() -> None:
    operation = _operation()
    bundle = operation.raw_authority_bundle_sha256
    row = operation.to_row()
    item_sha256 = _sha("coordinated-public-data-item")
    for count_field, root_field in (
        ("ownership_binding_count", "ownership_binding_root_sha256"),
        ("ownership_source_record_count", "ownership_source_record_root_sha256"),
    ):
        row[count_field] = 1
        row[root_field] = w2._legacy_root(
            kind=w2._OWNERSHIP_EMPTY_ROOT_KINDS[root_field],
            item_sha256s=(item_sha256,),
        )
    for count_field, root_field in (
        ("projection_item_count", "projection_item_root_sha256"),
        ("item_equality_count", "item_equality_root_sha256"),
    ):
        row[count_field] = 1
        row[root_field] = w2._value_projection_root(
            kind=w2._PROJECTION_EMPTY_ROOT_KINDS[root_field],
            raw_authority_bundle_sha256=bundle,
            item_sha256s=(item_sha256,),
        )
    _reseal_operation_row(row)
    new_receipt_sha256 = cast("str", row["operation_receipt_sha256"])

    with pytest.raises(W2OperationError, match="public data-row/source-record"):
        W2OperationReceiptV1.from_row(
            row,
            expected_operation_receipt_sha256=new_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=bundle,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        )


def test_operation_receipt_external_pins_defeat_fully_coordinated_reseal() -> None:
    operation = _operation()
    row = operation.to_row()
    row["equality_root_sha256"] = _sha("coordinated-equality")
    _reseal_operation_row(row)
    with pytest.raises(W2OperationError, match="external"):
        W2OperationReceiptV1.from_row(
            row,
            expected_operation_receipt_sha256=operation.operation_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        )


def test_operation_receipt_rejects_extra_self_cycle_and_order_drift() -> None:
    operation = _operation()
    extra = operation.to_row()
    extra["operation_row_sha256"] = _sha("self-cycle")
    with pytest.raises(W2OperationError, match="field shape"):
        _replay_operation_row(extra, operation)
    reordered = dict(reversed(tuple(operation.to_row().items())))
    with pytest.raises(W2OperationError, match="field shape"):
        _replay_operation_row(reordered, operation)


def _replay_operation_row(
    row: dict[str, object], operation: W2OperationReceiptV1
) -> W2OperationReceiptV1:
    return W2OperationReceiptV1.from_row(
        row,
        expected_operation_receipt_sha256=operation.operation_receipt_sha256,
        expected_operation_key_sha256=operation.operation_key_sha256,
        expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
        expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"result_cell_row_count": False},
        {"result_cell_row_count": _IntSubclass(0)},
        {"result_cell_schema_sha256": _TextSubclass(_sha("result_cell-schema"))},
    ],
)
def test_operation_receipt_rejects_bool_and_scalar_subclasses(
    changes: dict[str, object],
) -> None:
    operation = _operation()
    with pytest.raises(W2OperationError):
        replace(operation, **changes)


def test_operation_receipt_rejects_over_bound_counts_before_root_semantics() -> None:
    operation = _operation()
    with pytest.raises(W2OperationError, match="bounded"):
        replace(operation, result_cell_row_count=w2._MAX_OPERATION_ROWS + 1)


def test_operation_receipt_builder_rejects_missing_and_foreign_fields() -> None:
    key, bundle = _operation_key()
    values = _empty_values(bundle)
    values.pop("equality_root_sha256")
    with pytest.raises(W2OperationError, match="missing or foreign"):
        W2OperationReceiptV1.build(operation_key=key, **values)
    values["equality_root_sha256"] = _sha("equality")
    values["operation_row_sha256"] = _sha("self-cycle")
    with pytest.raises(W2OperationError, match="missing or foreign"):
        W2OperationReceiptV1.build(operation_key=key, **values)


def test_canonical_decoder_rejects_duplicate_deep_huge_and_noncanonical_inputs() -> None:
    key, _bundle = _operation_key()
    duplicate = (
        b'{"operation_attempt_count":1,"operation_attempt_root_sha256":"'
        + key.operation_attempt_root_sha256.encode("ascii")
        + b'","operation_key_sha256":"'
        + key.operation_key_sha256.encode("ascii")
        + b'","operation_key_sha256":"'
        + key.operation_key_sha256.encode("ascii")
        + b'","schema_version":1}'
    )
    hostile = (
        duplicate,
        (b"[" * 64) + b"0" + (b"]" * 64),
        b'"' + (b"x" * (w2._MAX_CANONICAL_BYTES + 1)) + b'"',
        key.canonical_bytes().replace(b":", b": ", 1),
    )
    for raw in hostile:
        with pytest.raises(W2OperationError):
            W2OperationKeyV1.from_canonical_bytes(
                raw,
                expected_operation_key_sha256=key.operation_key_sha256,
            )


@pytest.mark.parametrize("raw", [b"\xff", b"{", b'{"x":NaN}'])
def test_canonical_failures_do_not_leak_cause_or_context(raw: bytes) -> None:
    key, _bundle = _operation_key()
    with pytest.raises(W2OperationError) as caught:
        W2OperationKeyV1.from_canonical_bytes(
            raw,
            expected_operation_key_sha256=key.operation_key_sha256,
        )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_persistence_receipt_binds_exact_row_and_excludes_replay_from_identity() -> None:
    operation = _operation()
    inserted = W2OperationPersistenceReceiptV1.build(
        operation=operation,
        post_commit_readback_row=operation.to_row(),
        replayed=False,
    )
    replayed = W2OperationPersistenceReceiptV1.build(
        operation=operation,
        post_commit_readback_row=operation.to_row(),
        replayed=True,
    )
    assert inserted.persistence_receipt_sha256 == replayed.persistence_receipt_sha256
    assert inserted.canonical_bytes() != replayed.canonical_bytes()
    assert inserted.operation_row_sha256 == hashlib.sha256(operation.canonical_bytes()).hexdigest()
    assert _replay_persistence(inserted) == inserted


def test_persistence_rejects_different_operation_as_post_commit_collision() -> None:
    operation = _operation()
    key, bundle = _operation_key()
    values = _empty_values(bundle)
    values["equality_root_sha256"] = _sha("different-operation")
    different = W2OperationReceiptV1.build(operation_key=key, **values)
    with pytest.raises(W2OperationError, match="external"):
        W2OperationPersistenceReceiptV1.build(
            operation=operation,
            post_commit_readback_row=different.to_row(),
            replayed=False,
        )


def test_persistence_rejects_count_hash_root_bool_and_external_pin_drift() -> None:
    operation = _operation()
    receipt = W2OperationPersistenceReceiptV1.build(
        operation=operation,
        post_commit_readback_row=operation.to_row(),
        replayed=False,
    )
    for changes in (
        {"post_commit_readback_row_count": 0},
        {"post_commit_readback_row_count": True},
        {"post_commit_readback_row_count": _IntSubclass(1)},
        {"post_commit_readback_row_sha256": _sha("other-row")},
        {"post_commit_readback_root_sha256": _sha("other-root")},
        {"replayed": 1},
    ):
        with pytest.raises(W2OperationError):
            replace(receipt, **changes)
    with pytest.raises(W2OperationError, match="external"):
        W2OperationPersistenceReceiptV1.from_row(
            receipt.to_row(),
            expected_persistence_receipt_sha256=receipt.persistence_receipt_sha256,
            expected_operation_key_sha256=receipt.operation_key_sha256,
            expected_operation_receipt_sha256=receipt.operation_receipt_sha256,
            expected_w2_operation_schema_sha256=receipt.w2_operation_schema_sha256,
            expected_operation_row_sha256=_sha("foreign-row"),
        )


def test_persistence_external_row_pin_defeats_coordinated_scalar_reseal() -> None:
    operation = _operation()
    receipt = W2OperationPersistenceReceiptV1.build(
        operation=operation,
        post_commit_readback_row=operation.to_row(),
        replayed=False,
    )
    row = receipt.to_row()
    forged_row_sha256 = _sha("forged-operation-row")
    row["operation_row_sha256"] = forged_row_sha256
    row["post_commit_readback_row_sha256"] = forged_row_sha256
    row["post_commit_readback_root_sha256"] = w2._post_commit_readback_root(
        operation_key_sha256=receipt.operation_key_sha256,
        w2_operation_schema_sha256=receipt.w2_operation_schema_sha256,
        row_sha256s=(forged_row_sha256,),
    )
    identity = {
        "schema_version": 1,
        "kind": W2OperationPersistenceReceiptV1.kind,
        **{
            item.name: row[item.name]
            for item in fields(W2OperationPersistenceReceiptV1)
            if item.name not in {"persistence_receipt_sha256", "replayed"}
        },
    }
    forged_receipt_sha256 = w2._canonical_sha256(identity)
    row["persistence_receipt_sha256"] = forged_receipt_sha256
    with pytest.raises(W2OperationError, match="external"):
        W2OperationPersistenceReceiptV1.from_row(
            row,
            expected_persistence_receipt_sha256=forged_receipt_sha256,
            expected_operation_key_sha256=receipt.operation_key_sha256,
            expected_operation_receipt_sha256=receipt.operation_receipt_sha256,
            expected_w2_operation_schema_sha256=receipt.w2_operation_schema_sha256,
            expected_operation_row_sha256=receipt.operation_row_sha256,
        )


def test_persistence_rejects_extra_and_reordered_rows() -> None:
    operation = _operation()
    receipt = W2OperationPersistenceReceiptV1.build(
        operation=operation,
        post_commit_readback_row=operation.to_row(),
        replayed=False,
    )
    extra = receipt.to_row()
    extra["table_row_count"] = 1
    reordered = dict(reversed(tuple(receipt.to_row().items())))
    for row in (extra, reordered):
        with pytest.raises(W2OperationError, match="field shape"):
            W2OperationPersistenceReceiptV1.from_row(
                row,
                expected_persistence_receipt_sha256=receipt.persistence_receipt_sha256,
                expected_operation_key_sha256=receipt.operation_key_sha256,
                expected_operation_receipt_sha256=receipt.operation_receipt_sha256,
                expected_w2_operation_schema_sha256=receipt.w2_operation_schema_sha256,
                expected_operation_row_sha256=receipt.operation_row_sha256,
            )


def test_persistence_canonical_replay_requires_all_external_pins() -> None:
    operation = _operation()
    receipt = W2OperationPersistenceReceiptV1.build(
        operation=operation,
        post_commit_readback_row=operation.to_row(),
        replayed=True,
    )
    assert (
        W2OperationPersistenceReceiptV1.from_canonical_bytes(
            receipt.canonical_bytes(),
            expected_persistence_receipt_sha256=receipt.persistence_receipt_sha256,
            expected_operation_key_sha256=receipt.operation_key_sha256,
            expected_operation_receipt_sha256=receipt.operation_receipt_sha256,
            expected_w2_operation_schema_sha256=receipt.w2_operation_schema_sha256,
            expected_operation_row_sha256=receipt.operation_row_sha256,
        )
        == receipt
    )


def test_contract_dependency_and_operation_key_complexity_boundaries() -> None:
    source_path = Path(w2.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    allowed_project_imports = {
        "nbadb.contracts.raw_request_authority",
        "nbadb.contracts.raw_request_observation_order",
    }
    assert {name for name in imports if name.startswith("nbadb.")} == allowed_project_imports
    forbidden_imports = (
        "value_projection",
        "public_table_value_projection",
        "lossless_ownership",
        "orchestrate",
        "schemas",
        "polars",
        "pandera",
        "duckdb",
    )
    assert not any(
        fragment in module_name for module_name in imports for fragment in forbidden_imports
    )

    key_builder = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "W2OperationKeyV1"
    )
    build_method = next(
        node
        for node in key_builder.body
        if isinstance(node, ast.FunctionDef) and node.name == "build"
    )
    calls = [
        node
        for node in ast.walk(build_method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert sum(node.func.id == "canonical_raw_request_observations" for node in calls) == 1
    assert not any(node.func.id == "sorted" for node in calls)
