from __future__ import annotations

import hashlib
import json
from typing import cast

import pytest

from nbadb.contracts.canonical_arrow_value import ArrowLogicalTypeV1
from nbadb.contracts.raw_request_authority import ObservationRouteLandingV2
from nbadb.contracts.route_field_canonical_alias import (
    ROUTE_FIELD_CANONICAL_ALIAS_FIELD_COLUMNS,
    ROUTE_FIELD_CANONICAL_ALIAS_RECEIPT_COLUMNS,
    RouteFieldCanonicalAliasError,
    RouteFieldCanonicalAliasFieldV1,
    RouteFieldCanonicalAliasReceiptV1,
)
from nbadb.contracts.typed_field_value_receipt import (
    LandingFieldAuthorityV2,
    RouteFieldLandingReceiptV2,
    canonical_sha256,
)
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    CommittedStagingChunkReceiptV2,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _landing(
    *,
    label: str,
    observation_sha256: str,
    route_ordinal: int,
    route_id: str,
    staging_key: str,
    semantic: str,
    conditional_lossless: bool,
    alias_target_route_id: str | None,
    row_count: int = 2,
    content_hash: str | None = None,
    persisted_content_sha256: str | None = None,
    persisted_schema_sha256: str | None = None,
) -> ObservationRouteLandingV2:
    content_hash_value = content_hash or _sha("shared-content-hash")
    persisted_content_value = persisted_content_sha256 or _sha("shared-persisted-content")
    persisted_schema_value = persisted_schema_sha256 or _sha("shared-persisted-schema")
    logical_receipt_sha256 = _sha("shared-logical-receipt")
    committed_receipt = CommittedStagingChunkReceiptV2(
        chunk_id=f"chunk:{label}",
        staging_key=staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=content_hash_value,
        persisted_row_count=row_count,
        persisted_content_sha256=persisted_content_value,
        persisted_schema_sha256=persisted_schema_value,
        logical_call_receipt_sha256=logical_receipt_sha256,
        provider_authority_sha256=_sha("provider-authority"),
        logical_parameters_sha256=_sha("logical-parameters"),
        result_route_id=route_id,
    )
    return ObservationRouteLandingV2.build(
        observation_sha256=observation_sha256,
        logical_receipt_sha256=logical_receipt_sha256,
        route_ordinal=route_ordinal,
        route_authority_kind=(
            "conditional_staging_route_admission_v1"
            if conditional_lossless
            else "staging_route_contract_v1"
        ),
        route_authority_sha256=_sha(f"route-authority:{label}"),
        landing_semantic=semantic,
        conditional_lossless=conditional_lossless,
        alias_target_route_id=alias_target_route_id,
        live_snapshot_at=None,
        source_occurrence_sha256s=(),
        committed_receipt=committed_receipt,
    )


def _field(
    *,
    ordinal: int,
    name: str,
    route_id: str = "VideoEventsLossless",
    staging_key: str = "raw_nba_api_stats_lossless_record",
) -> LandingFieldAuthorityV2:
    logical_type = ArrowLogicalTypeV1(type_kind="utf8", offset_width=32)
    payload = {
        "schema_version": 2,
        "kind": LandingFieldAuthorityV2.kind,
        "field_fate_structure_sha256": _sha("field-fate"),
        "route_id": route_id,
        "staging_key": staging_key,
        "storage_ordinal": ordinal,
        "storage_column": name,
        "origin": "storage_only",
        "sink_sha256": _sha(f"sink:{ordinal}:{name}"),
        "route_binding_sha256s": [],
        "source_occurrence_sha256s": [],
        "source_endpoint_ids": [],
        "source_result_set_names": [],
        "source_result_set_ordinals": [],
        "source_header_ordinals": [],
        "source_field_names": [],
        "lossless_binding_sha256s": [],
        "logical_type": logical_type.to_dict(),
        "logical_type_sha256": logical_type.type_sha256,
    }
    return LandingFieldAuthorityV2(
        field_fate_structure_sha256=payload["field_fate_structure_sha256"],
        route_id=route_id,
        staging_key=staging_key,
        storage_ordinal=ordinal,
        storage_column=name,
        origin="storage_only",
        sink_sha256=payload["sink_sha256"],
        route_binding_sha256s=(),
        source_occurrence_sha256s=(),
        source_endpoint_ids=(),
        source_result_set_names=(),
        source_result_set_ordinals=(),
        source_header_ordinals=(),
        source_field_names=(),
        lossless_binding_sha256s=(),
        logical_type=logical_type,
        logical_type_sha256=logical_type.type_sha256,
        authority_sha256=canonical_sha256(payload),
    )


def _target_receipt(
    *,
    raw_bundle_sha256: str,
    target_landing: ObservationRouteLandingV2,
    fields: tuple[LandingFieldAuthorityV2, ...],
    source_shape: str = "body_node_bound",
    route_id: str | None = None,
    staging_key: str | None = None,
) -> RouteFieldLandingReceiptV2:
    receipt = object.__new__(RouteFieldLandingReceiptV2)
    route_id = route_id or target_landing.route_id
    staging_key = staging_key or target_landing.staging_key
    field_count = len(fields)
    cell_count = target_landing.persisted_row_count * field_count
    values: dict[str, object] = {
        "canonical_frame_format": "arrow_ipc_stream_v1",
        "frame_content_hash_contract": "canonical_arrow_ipc_stream_sha256_v1",
        "frame_schema_hash_contract": "canonical_arrow_schema_sha256_v1",
        "readback_receipt_sha256": _sha("readback"),
        "receipt_root_sha256": target_landing.receipt_root_sha256,
        "raw_bundle_sha256": raw_bundle_sha256,
        "field_fate_structure_sha256": _sha("field-fate"),
        "route_id": route_id,
        "staging_key": staging_key,
        "source_family": "stats",
        "decoder_kind": "conditional_body_node_rows_v2",
        "source_shape": source_shape,
        "endpoint_id": "VideoEvents",
        "conditional_authority_sha256": _sha("conditional-authority"),
        "row_partition_receipt_sha256": _sha("row-partition"),
        "row_count": target_landing.persisted_row_count,
        "occurrence_partition_count": 0,
        "selected_occurrence_count": 0,
        "field_count": field_count,
        "cell_count": cell_count,
        "source_verified_cell_count": 0,
        "storage_readback_only_cell_count": cell_count,
        "field_authorities": fields,
        "selected_occurrence_sha256s": (),
        "row_slice_receipt_sha256s": tuple(
            _sha(f"row-slice:{ordinal}") for ordinal in range(target_landing.persisted_row_count)
        ),
        "value_node_count": 0,
        "value_max_depth": 0,
        "value_utf8_bytes": 0,
        "value_binary_bytes": 0,
        "value_container_items": 0,
        "value_canonical_bytes": 0,
        "fields_sha256": canonical_sha256([field.to_dict() for field in fields]),
        "occurrences_sha256": canonical_sha256([]),
        "selected_occurrences_sha256": canonical_sha256([]),
        "values_sha256": canonical_sha256([]),
        "conditional_rows_sha256": _sha("conditional-rows"),
    }
    for name, value in values.items():
        object.__setattr__(receipt, name, value)
    object.__setattr__(
        receipt,
        "landing_receipt_sha256",
        canonical_sha256(receipt.identity_payload()),
    )
    return receipt


def _case(
    *,
    fields: tuple[LandingFieldAuthorityV2, ...] | None = None,
) -> tuple[
    str,
    ObservationRouteLandingV2,
    ObservationRouteLandingV2,
    RouteFieldLandingReceiptV2,
]:
    bundle_sha256 = _sha("raw-authority-bundle")
    observation_sha256 = _sha("observation")
    alias = _landing(
        label="alias",
        observation_sha256=observation_sha256,
        route_ordinal=0,
        route_id="VideoEventsFixed",
        staging_key="raw_video_events_fixed",
        semantic="response_canonical_alias",
        conditional_lossless=False,
        alias_target_route_id="VideoEventsLossless",
    )
    target = _landing(
        label="target",
        observation_sha256=observation_sha256,
        route_ordinal=1,
        route_id="VideoEventsLossless",
        staging_key="raw_nba_api_stats_lossless_record",
        semantic="conditional_lossless",
        conditional_lossless=True,
        alias_target_route_id=None,
    )
    target_fields = fields
    if target_fields is None:
        target_fields = (
            _field(ordinal=0, name="record_kind"),
            _field(ordinal=1, name="payload_sha256"),
        )
    receipt = _target_receipt(
        raw_bundle_sha256=bundle_sha256,
        target_landing=target,
        fields=target_fields,
    )
    return bundle_sha256, alias, target, receipt


def _build(
    *,
    fields: tuple[LandingFieldAuthorityV2, ...] | None = None,
) -> tuple[
    RouteFieldCanonicalAliasReceiptV1,
    ObservationRouteLandingV2,
    ObservationRouteLandingV2,
    RouteFieldLandingReceiptV2,
]:
    bundle_sha256, alias, target, target_receipt = _case(fields=fields)
    receipt = RouteFieldCanonicalAliasReceiptV1.build(
        raw_authority_bundle_sha256=bundle_sha256,
        alias_landing=alias,
        target_landings=(target,),
        target_route_receipts=(target_receipt,),
    )
    return receipt, alias, target, target_receipt


def test_canonical_alias_receipt_round_trips_without_value_payloads() -> None:
    receipt, alias, target, target_receipt = _build()

    assert (
        receipt.validate_against(
            alias_landing=alias,
            target_landings=(target,),
            target_route_receipts=(target_receipt,),
        )
        is receipt
    )
    assert RouteFieldCanonicalAliasReceiptV1.from_row(receipt.to_row()) == receipt
    assert (
        RouteFieldCanonicalAliasReceiptV1.from_canonical_bytes(receipt.canonical_bytes()) == receipt
    )
    assert tuple(receipt.to_row()) == ROUTE_FIELD_CANONICAL_ALIAS_RECEIPT_COLUMNS
    assert receipt.field_count == 2
    assert tuple(field.field_ordinal for field in receipt.fields) == (0, 1)
    assert all(
        RouteFieldCanonicalAliasFieldV1.from_canonical_bytes(field.canonical_bytes()) == field
        for field in receipt.fields
    )
    assert all(
        tuple(field.to_row()) == ROUTE_FIELD_CANONICAL_ALIAS_FIELD_COLUMNS
        for field in receipt.fields
    )

    encoded = receipt.canonical_bytes()
    for prohibited in (
        b"value_receipts",
        b"conditional_row_receipts",
        b"canonical_json",
        b"provider_value",
    ):
        assert prohibited not in encoded
    assert not hasattr(target_receipt, "value_receipts")
    assert not hasattr(target_receipt, "conditional_row_receipts")


def test_zero_field_alias_has_one_canonical_empty_inventory() -> None:
    receipt, alias, target, target_receipt = _build(fields=())

    assert receipt.field_count == 0
    assert receipt.fields == ()
    assert receipt.to_row()["fields_json"] == "[]"
    assert (
        receipt.validate_against(
            alias_landing=alias,
            target_landings=(target,),
            target_route_receipts=(target_receipt,),
        )
        is receipt
    )


@pytest.mark.parametrize("ambiguous_kind", ["landing", "receipt"])
def test_ambiguous_target_fails_closed(ambiguous_kind: str) -> None:
    bundle_sha256, alias, target, target_receipt = _case()
    target_landings = (target, target) if ambiguous_kind == "landing" else (target,)
    target_receipts = (
        (target_receipt, target_receipt) if ambiguous_kind == "receipt" else (target_receipt,)
    )

    with pytest.raises(RouteFieldCanonicalAliasError, match="ambiguous"):
        RouteFieldCanonicalAliasReceiptV1.build(
            raw_authority_bundle_sha256=bundle_sha256,
            alias_landing=alias,
            target_landings=target_landings,
            target_route_receipts=target_receipts,
        )


def test_cross_observation_target_fails_closed() -> None:
    bundle_sha256, alias, target, target_receipt = _case()
    foreign = target.model_copy(update={"observation_sha256": _sha("foreign-observation")})

    with pytest.raises(RouteFieldCanonicalAliasError, match="different observations"):
        RouteFieldCanonicalAliasReceiptV1.build(
            raw_authority_bundle_sha256=bundle_sha256,
            alias_landing=alias,
            target_landings=(foreign,),
            target_route_receipts=(target_receipt,),
        )


@pytest.mark.parametrize(
    ("attribute", "replacement"),
    [
        ("content_hash", _sha("different-content-hash")),
        ("persisted_row_count", 3),
        ("persisted_content_sha256", _sha("different-persisted-content")),
        ("persisted_schema_sha256", _sha("different-persisted-schema")),
    ],
)
def test_content_schema_and_count_drift_fail_closed(attribute: str, replacement: object) -> None:
    bundle_sha256, alias, target, target_receipt = _case()
    drifted = _landing(
        label=f"drifted-{attribute}",
        observation_sha256=target.observation_sha256,
        route_ordinal=target.route_ordinal,
        route_id=target.route_id,
        staging_key=target.staging_key,
        semantic="conditional_lossless",
        conditional_lossless=True,
        alias_target_route_id=None,
        row_count=(
            cast("int", replacement)
            if attribute == "persisted_row_count"
            else target.persisted_row_count
        ),
        content_hash=(
            cast("str", replacement) if attribute == "content_hash" else target.content_hash
        ),
        persisted_content_sha256=(
            cast("str", replacement)
            if attribute == "persisted_content_sha256"
            else target.persisted_content_sha256
        ),
        persisted_schema_sha256=(
            cast("str", replacement)
            if attribute == "persisted_schema_sha256"
            else target.persisted_schema_sha256
        ),
    )

    with pytest.raises(RouteFieldCanonicalAliasError, match="persisted content, schema, or row"):
        RouteFieldCanonicalAliasReceiptV1.build(
            raw_authority_bundle_sha256=bundle_sha256,
            alias_landing=alias,
            target_landings=(drifted,),
            target_route_receipts=(target_receipt,),
        )


@pytest.mark.parametrize("drift_kind", ["route", "staging", "root"])
def test_target_receipt_route_identity_drift_fails_closed(drift_kind: str) -> None:
    bundle_sha256, alias, target, target_receipt = _case()
    if drift_kind == "route":
        target_receipt = _target_receipt(
            raw_bundle_sha256=bundle_sha256,
            target_landing=target,
            fields=target_receipt.field_authorities,
            route_id="ForeignRoute",
        )
    elif drift_kind == "staging":
        target_receipt = _target_receipt(
            raw_bundle_sha256=bundle_sha256,
            target_landing=target,
            fields=target_receipt.field_authorities,
            staging_key="foreign_staging",
        )
    else:
        object.__setattr__(target_receipt, "receipt_root_sha256", _sha("foreign-root"))

    with pytest.raises(RouteFieldCanonicalAliasError, match="absent or ambiguous"):
        RouteFieldCanonicalAliasReceiptV1.build(
            raw_authority_bundle_sha256=bundle_sha256,
            alias_landing=alias,
            target_landings=(target,),
            target_route_receipts=(target_receipt,),
        )


def test_target_field_drift_is_rejected_by_independent_replay() -> None:
    receipt, alias, target, _target_receipt_original = _build()
    drifted_fields = (
        _field(ordinal=0, name="renamed_record_kind"),
        _field(ordinal=1, name="payload_sha256"),
    )
    drifted_target_receipt = _target_receipt(
        raw_bundle_sha256=receipt.raw_authority_bundle_sha256,
        target_landing=target,
        fields=drifted_fields,
    )

    with pytest.raises(RouteFieldCanonicalAliasError, match="independent authority replay"):
        receipt.validate_against(
            alias_landing=alias,
            target_landings=(target,),
            target_route_receipts=(drifted_target_receipt,),
        )


@pytest.mark.parametrize("inventory_kind", ["reordered", "duplicate"])
def test_target_field_reorder_and_duplicate_fail_closed(inventory_kind: str) -> None:
    bundle_sha256, alias, target, target_receipt = _case()
    first, second = target_receipt.field_authorities
    fields = (second, first) if inventory_kind == "reordered" else (first, first)
    malformed = _target_receipt(
        raw_bundle_sha256=bundle_sha256,
        target_landing=target,
        fields=fields,
    )

    with pytest.raises(RouteFieldCanonicalAliasError, match="reordered or relabeled"):
        RouteFieldCanonicalAliasReceiptV1.build(
            raw_authority_bundle_sha256=bundle_sha256,
            alias_landing=alias,
            target_landings=(target,),
            target_route_receipts=(malformed,),
        )


def test_independently_resealed_alias_drift_fails_external_replay() -> None:
    original, alias, target, target_receipt = _build()
    resealed_alias = alias.model_copy(
        update={
            "landing_sha256": _sha("resealed-alias-landing"),
            "staging_key": "resealed_alias_staging",
        }
    )
    with pytest.raises(RouteFieldCanonicalAliasError, match="exact Raw V2 replay"):
        RouteFieldCanonicalAliasReceiptV1.build(
            raw_authority_bundle_sha256=original.raw_authority_bundle_sha256,
            alias_landing=resealed_alias,
            target_landings=(target,),
            target_route_receipts=(target_receipt,),
        )


def test_hostile_subclass_and_mutable_candidates_fail_before_field_access() -> None:
    bundle_sha256, alias, target, target_receipt = _case()

    class HostileLanding(ObservationRouteLandingV2):
        pass

    hostile = HostileLanding.model_construct(**alias.model_dump())
    with pytest.raises(RouteFieldCanonicalAliasError, match="foreign alias landing"):
        RouteFieldCanonicalAliasReceiptV1.build(
            raw_authority_bundle_sha256=bundle_sha256,
            alias_landing=hostile,
            target_landings=(target,),
            target_route_receipts=(target_receipt,),
        )
    with pytest.raises(RouteFieldCanonicalAliasError, match="exact tuple"):
        RouteFieldCanonicalAliasReceiptV1.build(
            raw_authority_bundle_sha256=bundle_sha256,
            alias_landing=alias,
            target_landings=cast("tuple[ObservationRouteLandingV2, ...]", [target]),
            target_route_receipts=(target_receipt,),
        )


def test_strict_rows_reject_order_types_secrets_and_count_root_drift() -> None:
    receipt, _alias, _target, _target_receipt_value = _build()
    receipt_row = receipt.to_row()
    reordered_receipt_row = {
        name: receipt_row[name] for name in reversed(ROUTE_FIELD_CANONICAL_ALIAS_RECEIPT_COLUMNS)
    }
    with pytest.raises(RouteFieldCanonicalAliasError, match="exact ordered columns"):
        RouteFieldCanonicalAliasReceiptV1.from_row(reordered_receipt_row)

    bool_count = dict(receipt_row)
    bool_count["field_count"] = True
    with pytest.raises(RouteFieldCanonicalAliasError, match="exact integer"):
        RouteFieldCanonicalAliasReceiptV1.from_row(bool_count)

    wrong_root = dict(receipt_row)
    wrong_root["field_root_sha256"] = _sha("wrong-field-root")
    with pytest.raises(RouteFieldCanonicalAliasError, match="field root"):
        RouteFieldCanonicalAliasReceiptV1.from_row(wrong_root)

    field_row = receipt.fields[0].to_row()
    secret_field = dict(field_row)
    secret_field["field_name"] = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345"
    secret_payload = {
        "schema_version": 1,
        "kind": RouteFieldCanonicalAliasFieldV1.kind,
        **{
            name: secret_field[name]
            for name in ROUTE_FIELD_CANONICAL_ALIAS_FIELD_COLUMNS
            if name not in {"schema_version", "field_sha256"}
        },
    }
    secret_field["field_sha256"] = _canonical_sha256(secret_payload)
    with pytest.raises(RouteFieldCanonicalAliasError, match="public-safe"):
        RouteFieldCanonicalAliasFieldV1.from_row(secret_field)


def test_resealed_field_relabel_cannot_claim_the_original_target() -> None:
    receipt, alias, target, target_receipt = _build()
    field = receipt.fields[0]
    payload = field.identity_payload() | {"field_name": "relabelled_field"}
    forged = RouteFieldCanonicalAliasFieldV1(
        field_sha256=_canonical_sha256(payload),
        field_ordinal=field.field_ordinal,
        field_name="relabelled_field",
        alias_raw_route_landing_sha256=field.alias_raw_route_landing_sha256,
        alias_route_id=field.alias_route_id,
        alias_staging_key=field.alias_staging_key,
        target_raw_route_landing_sha256=field.target_raw_route_landing_sha256,
        target_route_id=field.target_route_id,
        target_staging_key=field.target_staging_key,
        target_route_landing_receipt_sha256=field.target_route_landing_receipt_sha256,
        target_field_authority_sha256=field.target_field_authority_sha256,
        field_origin=field.field_origin,
        logical_type_sha256=field.logical_type_sha256,
    )

    assert forged.field_sha256 != field.field_sha256
    assert forged.target_field_authority_sha256 == field.target_field_authority_sha256
    assert RouteFieldCanonicalAliasFieldV1.from_row(forged.to_row()) == forged

    forged_fields = (forged, receipt.fields[1])
    forged_root = _canonical_sha256(
        {
            "schema_version": 1,
            "kind": "route_field_canonical_alias_fields_v1",
            "count": len(forged_fields),
            "items": [item.field_sha256 for item in forged_fields],
        }
    )
    forged_row = receipt.to_row()
    forged_row["field_root_sha256"] = forged_root
    forged_row["fields_json"] = json.dumps(
        [item.to_row() for item in forged_fields],
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    forged_row["receipt_sha256"] = _canonical_sha256(
        receipt.identity_payload() | {"field_root_sha256": forged_root}
    )
    independently_resealed = RouteFieldCanonicalAliasReceiptV1.from_row(forged_row)

    with pytest.raises(RouteFieldCanonicalAliasError, match="independent authority replay"):
        independently_resealed.validate_against(
            alias_landing=alias,
            target_landings=(target,),
            target_route_receipts=(target_receipt,),
        )
