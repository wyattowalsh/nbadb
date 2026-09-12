"""Tests for the body/bodyless-only W2 value projection authority."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import re
import subprocess
import sys
from dataclasses import fields as dataclass_fields
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

import nbadb.contracts.independent_body_value_projection_builder as builder_module
from nbadb.contracts.body_blob_inventory import build_body_blob_inventory
from nbadb.contracts.independent_body_value_projection_builder import (
    INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256,
    DeclaredBodylessProjectionAuthorityV1,
    IndependentBodyValueProjectionBuilderError,
    IndependentBodyValueProjectionV1,
    build_declared_bodyless_projection_authority,
    build_independent_body_value_projection,
)
from nbadb.contracts.independent_stats_lossless_authority_builder import (
    build_independent_stats_lossless_authorities,
)
from nbadb.contracts.live_lossless_value_authority import (
    build_live_lossless_value_authority,
)
from nbadb.contracts.value_projection_plan_builder import build_value_projection_plan
from nbadb.core.nba_api_runtime_contract import pinned_static_dataset_contract
from tests.unit.contracts.test_public_table_value_projection import _project
from tests.unit.contracts.test_public_value_authority_adapter import _live_bundle
from tests.unit.contracts.test_raw_request_authority import _stats_fallback_bundle, _video_bundle
from tests.unit.contracts.test_raw_result_cell_authority import (
    _static_case,
    _stats_case,
)
from tests.unit.contracts.test_value_projection_plan_builder import (
    _fixture as _plan_fixture,
)
from tests.unit.contracts.test_value_projection_plan_builder import _packet_source

if TYPE_CHECKING:
    from nbadb.contracts.value_projection_plan import ValueProjectionPlanV1


_SOURCE_PATH = Path("src/nbadb/contracts/independent_body_value_projection_builder.py")


def _unsafe_clone_with(value: object, **changes: object) -> object:
    """Construct hostile exact-type test evidence without running its seal checks."""

    value_type = cast("type[Any]", type(value))
    clone = object.__new__(value_type)
    for item in dataclass_fields(cast("Any", value)):
        object.__setattr__(
            clone,
            item.name,
            changes.get(item.name, getattr(value, item.name)),
        )
    return clone


def _static_packet_bytes(endpoint_id: str) -> bytes:
    contract = pinned_static_dataset_contract(endpoint_id)
    rows = getattr(importlib.import_module("nba_api.stats.library.data"), contract.source_symbol)
    return json.dumps(
        rows,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _builder_fixture(
    *,
    bundle: object,
    cells: tuple[object, ...],
    stats: tuple[object, ...] = (),
    live: object | None = None,
    packets: tuple[object, ...] = (),
    bodyless_readbacks: tuple[object, ...] = (),
    packet_bytes: tuple[bytes, ...] = (),
) -> tuple[ValueProjectionPlanV1, dict[str, object]]:
    fixture = _plan_fixture(
        bundle=cast("Any", bundle),
        cells=cast("Any", cells),
        stats=cast("Any", stats),
        live=cast("Any", live),
        packets=cast("Any", packets),
        bodyless_readbacks=cast("Any", bodyless_readbacks),
    )
    plan = build_value_projection_plan(**fixture)
    inventory = build_body_blob_inventory(
        cast("Any", bundle),
        expected_raw_authority_bundle_sha256=cast("Any", bundle).bundle_sha256,
    )
    values = {
        "expected_raw_authority_bundle_sha256": cast("Any", bundle).bundle_sha256,
        "ownership_authority": fixture["ownership_authority"],
        "expected_ownership_receipt_sha256": fixture["expected_ownership_receipt_sha256"],
        "plan": plan,
        "expected_plan_sha256": plan.plan_sha256,
        "body_blob_inventory": inventory,
        "expected_body_blob_inventory_sha256": inventory.inventory_sha256,
        "body_blob_inventory_readback_receipt": fixture["body_blob_inventory_readback_receipt"],
        "expected_body_blob_inventory_readback_receipt_sha256": fixture[
            "expected_body_blob_inventory_readback_receipt_sha256"
        ],
        "declared_bodyless_packets": packets,
        "expected_declared_bodyless_packet_authority_sha256s": tuple(
            cast("Any", item).packet_authority_sha256 for item in packets
        ),
        "declared_bodyless_readback_receipts": bodyless_readbacks,
        "expected_declared_bodyless_readback_receipt_sha256s": tuple(
            cast("Any", item).receipt_sha256 for item in bodyless_readbacks
        ),
        "declared_bodyless_packet_bytes": packet_bytes,
    }
    return plan, values


def _build(bundle: object, values: dict[str, object]) -> IndependentBodyValueProjectionV1:
    return build_independent_body_value_projection(cast("Any", bundle), **values)


@cache
def _static_context() -> tuple[
    object, tuple[object, ...], object, object, bytes, object, dict[str, object]
]:
    bundle, cells = _static_case()
    observation = bundle.observations[0]
    packet, readback = _packet_source(observation)
    payload = _static_packet_bytes(observation.attempt.endpoint_id)
    plan, values = _builder_fixture(
        bundle=bundle,
        cells=cast("Any", cells),
        packets=(packet,),
        bodyless_readbacks=(readback,),
        packet_bytes=(payload,),
    )
    return bundle, cast("Any", cells), packet, readback, payload, plan, values


def test_code_owned_policy_is_stable_and_not_caller_selectable() -> None:
    assert INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256 == (
        "0a9b11ff038cac92c068bf65843961d9c0e8cbddcc286172add5b5c190c6b7e2"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256)
    signature = ast.parse(_SOURCE_PATH.read_text(encoding="utf-8"))
    builder = next(
        node
        for node in signature.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_independent_body_value_projection"
    )
    assert "body_projection_policy_sha256" not in {
        argument.arg for argument in (*builder.args.args, *builder.args.kwonlyargs)
    }


def test_rectangular_stats_bytes_equal_the_public_projection_oracle() -> None:
    bundle, cells = _stats_case()
    plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    authority = _build(bundle, values)
    public = _project(plan, cells=tuple(item.to_row() for item in cells))

    assert authority.projection == public.projection
    assert authority.partitions == public.partitions
    assert authority.items == public.items
    assert authority.receipt.body_projection_policy_sha256 == (
        INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256
    )
    assert (
        authority.receipt.body_blob_inventory_sha256
        == cast("Any", values["body_blob_inventory_readback_receipt"]).inventory_sha256
    )
    assert authority.receipt.body_blob_byte_count == sum(
        item.payload_byte_count
        for item in plan.observation_sources
        if item.source_input_kind == "parser_input_body"
    )
    assert authority.declared_bodyless_authority.packet_count == 0


def test_unknown_stats_bytes_preserve_duplicate_results_unicode_and_large_integer() -> None:
    payload = {
        "resultSets": [
            {
                "name": "Extra",
                "headers": ["VALUE"],
                "rowSet": [["caf\u00e9"], [(1 << 63) - 1]],
            },
            {
                "name": "Extra",
                "headers": ["VALUE"],
                "rowSet": [[True]],
            },
        ]
    }
    bundle, _observation, _occurrences, _landings = _video_bundle("VideoEvents", payload)
    stats = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    plan, values = _builder_fixture(bundle=bundle, cells=(), stats=cast("Any", stats))
    authority = _build(bundle, values)
    public = _project(plan, stats_rows=tuple(item.to_row() for item in stats[0].records))

    assert authority.projection == public.projection
    assert authority.partitions == public.partitions
    assert authority.items == public.items
    canonical_values = tuple(
        item.canonical_json for item in authority.items if item.canonical_json is not None
    )
    assert '"caf\u00e9"' in canonical_values
    assert str((1 << 63) - 1) in canonical_values
    assert [item.result_duplicate_ordinal for item in authority.partitions[:2]] == [0, 1]


@pytest.mark.parametrize(
    "variant",
    ("header_drift", "heterogeneous", "duplicate_name", "additive_result"),
)
def test_stats_lossless_drift_bytes_equal_the_public_projection_oracle(variant: str) -> None:
    bundle, _observation, _occurrences, _landings = _stats_fallback_bundle(variant)
    stats = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    plan, values = _builder_fixture(bundle=bundle, cells=(), stats=cast("Any", stats))
    authority = _build(bundle, values)
    public = _project(plan, stats_rows=tuple(item.to_row() for item in stats[0].records))

    assert authority.projection == public.projection
    assert authority.partitions == public.partitions
    assert authority.items == public.items


def test_missing_stats_result_uses_the_exact_expected_result_path() -> None:
    bundle, _observation, _occurrences, _landings = _stats_fallback_bundle("missing_result")
    stats = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    plan, values = _builder_fixture(bundle=bundle, cells=(), stats=cast("Any", stats))
    missing = next(item for item in plan.occurrence_plans if item.result_presence == "missing")

    assert missing.result_path is None
    assert missing.provider_result_ordinal is None
    assert missing.canonical_result_ordinal is None
    authority = _build(bundle, values)
    public = _project(plan, stats_rows=tuple(item.to_row() for item in stats[0].records))

    assert authority.projection == public.projection
    assert authority.partitions == public.partitions
    assert authority.items == public.items
    missing_partition = next(
        item for item in authority.partitions if item.occurrence_sha256 == missing.occurrence_sha256
    )
    assert missing_partition.result_path == f"$.expectedResults[{missing.expected_result_ordinal}]"


def test_static_packet_bytes_equal_the_public_projection_oracle() -> None:
    bundle, cells, _packet, _readback, payload, plan, base_values = _static_context()
    authority = _build(bundle, dict(base_values))
    public = _project(cast("Any", plan), cells=tuple(cast("Any", item).to_row() for item in cells))

    assert authority.projection == public.projection
    assert authority.partitions == public.partitions
    assert authority.items == public.items
    assert authority.receipt.bodyless_packet_byte_count == len(payload)
    assert authority.receipt.declared_bodyless_authority_sha256 == (
        authority.declared_bodyless_authority.authority_sha256
    )
    assert (
        authority.declared_bodyless_authority.payload_root_sha256
        != hashlib.sha256(payload).hexdigest()
    )


def test_live_bytes_equal_public_projection_and_preserve_value_states() -> None:
    bundle = _live_bundle()
    live = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    plan, values = _builder_fixture(bundle=bundle, cells=(), live=live)
    authority = _build(bundle, values)
    public = _project(plan, live_rows=tuple(item.to_row() for item in live.records))

    assert authority.projection == public.projection
    assert authority.partitions == public.partitions
    assert authority.items == public.items
    decoded_values = [
        item.value()
        for item in authority.items
        if item.value_state == "canonical" and item.canonical_json is not None
    ]
    assert None in decoded_values
    assert {
        item.value_kind for item in authority.items if item.value_state == "structural_container"
    } >= {"array", "object"}


@pytest.mark.parametrize(
    "value",
    (None, "", "\u2603", 9_007_199_254_740_991, -9_007_199_254_740_991),
)
def test_independent_canonical_value_replay_preserves_hostile_scalars(value: object) -> None:
    canonical = builder_module._canonical_bytes(value).decode("utf-8")
    assert builder_module._decode_canonical_value(canonical) == value


def test_independent_live_shapes_preserve_missing_and_empty_containers() -> None:
    assert builder_module._node_value_shape(
        presence_kind="missing",
        value_kind="missing",
        canonical_json=None,
    ) == {"value_state": "missing", "missing_presence_kind": "missing"}
    assert builder_module._node_value_shape(
        presence_kind="present",
        value_kind="array",
        canonical_json=None,
    ) == {"value_state": "structural_container", "structural_value_kind": "array"}
    assert builder_module._node_value_shape(
        presence_kind="present",
        value_kind="object",
        canonical_json=None,
    ) == {"value_state": "structural_container", "structural_value_kind": "object"}


def test_declared_bodyless_aggregate_is_deterministic_and_exactly_ordered() -> None:
    bundle, _cells, packet, readback, payload, _plan, _values = _static_context()
    observation = cast("Any", bundle).observations[0]
    args = {
        "raw_authority_bundle_sha256": bundle.bundle_sha256,
        "packets": (packet,),
        "expected_packet_authority_sha256s": (packet.packet_authority_sha256,),
        "readbacks": (readback,),
        "expected_readback_receipt_sha256s": (readback.receipt_sha256,),
        "packet_bytes": (payload,),
        "expected_observation_sha256s": (observation.attempt.observation_sha256,),
        "expected_observation_record_sha256s": (observation.observation_record_sha256,),
    }
    first = build_declared_bodyless_projection_authority(**args)
    second = build_declared_bodyless_projection_authority(**args)

    assert first == second
    assert type(first) is DeclaredBodylessProjectionAuthorityV1
    assert first.packet_count == first.readback_count == first.payload_count == 1
    assert first.payload_byte_count == len(payload)
    with pytest.raises(
        IndependentBodyValueProjectionBuilderError,
        match="duplicate authority identities",
    ):
        build_declared_bodyless_projection_authority(
            **{
                **args,
                "packets": (packet, packet),
                "expected_packet_authority_sha256s": (
                    packet.packet_authority_sha256,
                    packet.packet_authority_sha256,
                ),
                "readbacks": (readback, readback),
                "expected_readback_receipt_sha256s": (
                    readback.receipt_sha256,
                    readback.receipt_sha256,
                ),
                "packet_bytes": (payload, payload),
                "expected_observation_sha256s": (
                    observation.attempt.observation_sha256,
                    observation.attempt.observation_sha256,
                ),
                "expected_observation_record_sha256s": (
                    observation.observation_record_sha256,
                    observation.observation_record_sha256,
                ),
            }
        )


@pytest.mark.parametrize("mode", ("missing", "extra", "changed"))
def test_bodyless_packet_inventory_must_match_exact_bytes(mode: str) -> None:
    bundle, _cells, _packet, _readback, payload, _plan, base_values = _static_context()
    values = dict(base_values)
    if mode == "missing":
        values["declared_bodyless_packet_bytes"] = ()
    elif mode == "extra":
        values["declared_bodyless_packet_bytes"] = (payload, payload)
    else:
        values["declared_bodyless_packet_bytes"] = (payload + b" ",)

    with pytest.raises(IndependentBodyValueProjectionBuilderError):
        _build(bundle, values)


def test_external_identity_pins_are_checked_before_authority_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))

    def traversal_bomb(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("authority traversal occurred before pinning")

    monkeypatch.setattr(builder_module, "validate_raw_request_authority_bundle", traversal_bomb)
    values["expected_plan_sha256"] = "f" * 64
    with pytest.raises(IndependentBodyValueProjectionBuilderError, match="external pin"):
        _build(bundle, values)


def test_foreign_ownership_is_rejected_before_raw_authority_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))

    def traversal_bomb(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Raw authority traversal occurred")

    monkeypatch.setattr(builder_module, "validate_raw_request_authority_bundle", traversal_bomb)
    values["ownership_authority"] = object()
    with pytest.raises(
        IndependentBodyValueProjectionBuilderError,
        match="ownership has a foreign exact DTO",
    ):
        _build(bundle, values)


def test_hostile_child_error_is_collapsed_at_the_authority_replay_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    marker = "hostile-sensitive-child-message"

    def hostile_child(*_args: object, **_kwargs: object) -> object:
        raise IndependentBodyValueProjectionBuilderError(marker)

    monkeypatch.setattr(builder_module, "validate_raw_request_authority_bundle", hostile_child)
    with pytest.raises(IndependentBodyValueProjectionBuilderError) as captured:
        _build(bundle, values)

    assert str(captured.value) == "independent body projection authority replay failed"
    assert marker not in str(captured.value)


def test_foreign_body_readback_builder_return_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    monkeypatch.setattr(
        builder_module.BodyBlobInventoryReadbackReceiptV1,
        "build",
        classmethod(lambda _cls, **_kwargs: object()),
    )

    with pytest.raises(
        IndependentBodyValueProjectionBuilderError,
        match="authority replay failed",
    ):
        _build(bundle, values)


def test_foreign_ownership_builder_return_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    valid = values["ownership_authority"]

    class DelegatingProxy:
        def __getattr__(self, name: str) -> object:
            return getattr(valid, name)

        def __eq__(self, _other: object) -> bool:
            return True

    monkeypatch.setattr(
        builder_module,
        "build_lossless_ownership_authority",
        lambda **_kwargs: DelegatingProxy(),
    )
    with pytest.raises(
        IndependentBodyValueProjectionBuilderError,
        match="authority replay failed",
    ):
        _build(bundle, values)


def test_corrupted_internal_declared_authority_return_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells, _packet, _readback, _payload, _plan, base_values = _static_context()
    valid = _build(bundle, dict(base_values)).declared_bodyless_authority
    corrupted = _unsafe_clone_with(
        valid,
        payload_byte_count=valid.payload_byte_count + 1,
    )
    monkeypatch.setattr(
        builder_module,
        "_build_declared_bodyless_projection_authority",
        lambda **_kwargs: corrupted,
    )

    with pytest.raises(
        IndependentBodyValueProjectionBuilderError,
        match="failed exact DTO replay",
    ):
        _build(bundle, dict(base_values))


def test_live_decoder_output_is_bound_to_the_exact_raw_parser_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _live_bundle()
    live = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    _plan, values = _builder_fixture(bundle=bundle, cells=(), live=live)
    decode = builder_module.decode_live_value_response

    def alternate_bytes(
        parser_input: bytes,
        *,
        endpoint_id: str,
        endpoint_contract_sha256: str,
    ) -> object:
        return decode(
            parser_input + b" ",
            endpoint_id=endpoint_id,
            endpoint_contract_sha256=endpoint_contract_sha256,
        )

    monkeypatch.setattr(builder_module, "decode_live_value_response", alternate_bytes)
    with pytest.raises(
        IndependentBodyValueProjectionBuilderError,
        match="independent live body decoding failed",
    ):
        _build(bundle, values)


def test_static_validator_output_is_bound_to_the_exact_packet_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells, _packet, _readback, _payload, _plan, base_values = _static_context()
    validate = builder_module.validate_decoded_static_response

    def poisoned_validator(value: object) -> object:
        exact = validate(value)
        return _unsafe_clone_with(
            exact,
            parser_input_sha256="0" * 64,
            parser_input_length=1,
        )

    monkeypatch.setattr(builder_module, "validate_decoded_static_response", poisoned_validator)
    with pytest.raises(
        IndependentBodyValueProjectionBuilderError,
        match="independent static packet decoding failed",
    ):
        _build(bundle, dict(base_values))


def test_hostile_stats_decoder_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    marker = "HOSTILE_DECODER_SENTINEL"

    def hostile_decoder(*_args: object, **_kwargs: object) -> object:
        raise IndependentBodyValueProjectionBuilderError(marker)

    monkeypatch.setattr(builder_module, "decode_stats_projection_response", hostile_decoder)
    with pytest.raises(IndependentBodyValueProjectionBuilderError) as captured:
        _build(bundle, values)

    assert str(captured.value) == "independent stats body decoding failed"
    assert marker not in str(captured.value)


def test_foreign_raw_parser_replay_return_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    monkeypatch.setattr(
        builder_module,
        "decode_parser_input_object",
        lambda _value: object(),
    )

    with pytest.raises(
        IndependentBodyValueProjectionBuilderError,
        match="parser source failed exact replay",
    ):
        _build(bundle, values)


def test_foreign_stats_validator_return_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    validate = builder_module.validate_decoded_stats_projection_response

    class DelegatingProxy:
        def __init__(self, target: object) -> None:
            self._target = target

        def __getattr__(self, name: str) -> object:
            return getattr(self._target, name)

        def __eq__(self, _other: object) -> bool:
            return True

    def foreign_validator(value: object, *, parser_input_bytes: bytes) -> object:
        return DelegatingProxy(validate(value, parser_input_bytes=parser_input_bytes))

    monkeypatch.setattr(
        builder_module,
        "validate_decoded_stats_projection_response",
        foreign_validator,
    )
    with pytest.raises(
        IndependentBodyValueProjectionBuilderError,
        match="independent stats body decoding failed",
    ):
        _build(bundle, values)


def test_hostile_projection_item_builder_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    marker = "HOSTILE_ITEM_SENTINEL"

    def hostile_builder(_cls: object, **_kwargs: object) -> object:
        raise RuntimeError(marker)

    monkeypatch.setattr(
        builder_module.ValueProjectionItemV1,
        "build",
        classmethod(hostile_builder),
    )
    with pytest.raises(IndependentBodyValueProjectionBuilderError) as captured:
        _build(bundle, values)

    assert str(captured.value) == ("independent body source cannot form its exact projection item")
    assert marker not in str(captured.value)


@pytest.mark.parametrize(
    ("target_name", "expected_message"),
    (
        (
            "ValueProjectionPartitionV1",
            "independent body source cannot form its exact projection partition",
        ),
        (
            "ValueProjectionReceiptV1",
            "independent body projection aggregate construction failed",
        ),
        (
            "BodyValueProjectionReceiptV1",
            "independent body projection aggregate construction failed",
        ),
    ),
)
def test_foreign_projection_child_builder_returns_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
    expected_message: str,
) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    target = getattr(builder_module, target_name)
    monkeypatch.setattr(
        target,
        "build",
        classmethod(lambda _cls, **_kwargs: object()),
    )

    with pytest.raises(IndependentBodyValueProjectionBuilderError) as captured:
        _build(bundle, values)

    assert str(captured.value) == expected_message


def test_hostile_known_secret_sequence_is_rejected_without_traversal() -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))

    class HostileSequence:
        def __len__(self) -> int:
            raise ValueError("HOSTILE_SECRET_SEQUENCE")

        def __getitem__(self, _index: int) -> object:
            raise ValueError("HOSTILE_SECRET_SEQUENCE")

    values["known_secrets"] = HostileSequence()
    with pytest.raises(IndependentBodyValueProjectionBuilderError) as captured:
        _build(bundle, values)

    assert str(captured.value) == "known-secret inventory must be one bounded exact sequence"
    assert "HOSTILE_SECRET_SEQUENCE" not in str(captured.value)


def test_bodyless_denominator_is_checked_before_member_scan() -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    values["declared_bodyless_packets"] = (object(),)

    with pytest.raises(
        IndependentBodyValueProjectionBuilderError,
        match="bodyless denominators differ",
    ):
        _build(bundle, values)


def test_occurrence_lookup_uses_prebuilt_indexes() -> None:
    tree = ast.parse(_SOURCE_PATH.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_occurrence_for_stats_result", "_live_occurrence"}
    }
    assert set(functions) == {"_occurrence_for_stats_result", "_live_occurrence"}
    for function in functions.values():
        attributes = {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)}
        assert "occurrence_plans" not in attributes
        assert any(
            isinstance(node, ast.Name) and node.id == "occurrence_index"
            for node in ast.walk(function)
        )


def test_known_secret_failures_are_sanitized() -> None:
    bundle, _cells, _packet, _readback, payload, _plan, base_values = _static_context()
    secret = payload[1:17]
    values = dict(base_values)
    values["known_secrets"] = (secret,)
    with pytest.raises(IndependentBodyValueProjectionBuilderError) as captured:
        _build(bundle, values)

    assert "known-secret material" in str(captured.value)
    assert secret.decode("utf-8", errors="ignore") not in str(captured.value)


@pytest.mark.parametrize(
    ("name", "foreign"),
    (
        ("declared_bodyless_packets", []),
        ("declared_bodyless_readback_receipts", []),
        ("declared_bodyless_packet_bytes", []),
    ),
)
def test_foreign_bodyless_container_types_fail_closed(name: str, foreign: object) -> None:
    bundle, cells = _stats_case()
    _plan, values = _builder_fixture(bundle=bundle, cells=cast("Any", cells))
    values[name] = foreign
    with pytest.raises(IndependentBodyValueProjectionBuilderError, match="exact tuples"):
        _build(bundle, values)


def test_source_has_no_public_staging_or_production_parser_dependency() -> None:
    tree = ast.parse(_SOURCE_PATH.read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden = (
        "nbadb.extract",
        "nbadb.orchestrate",
        "nbadb.schemas",
        "nbadb.contracts.public_table_value_projection",
        "nbadb.contracts.public_value_authority_adapter",
        "nbadb.contracts.raw_result_cell_authority",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.") for name in imports for prefix in forbidden
    )

    script = """
import sys
import nbadb.contracts.independent_body_value_projection_builder
forbidden = (
    'nbadb.contracts.public_table_value_projection',
    'nbadb.contracts.public_value_authority_adapter',
    'nbadb.contracts.raw_result_cell_authority',
)
loaded = tuple(name for name in sys.modules if any(
    name == prefix or name.startswith(prefix + '.') for prefix in forbidden
))
if loaded:
    raise SystemExit(repr(loaded))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
