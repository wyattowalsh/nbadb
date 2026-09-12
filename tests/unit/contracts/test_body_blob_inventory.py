from __future__ import annotations

import json
from copy import copy
from dataclasses import replace
from datetime import timedelta

import pytest

from nbadb.contracts import body_blob_inventory
from nbadb.contracts.body_blob_inventory import (
    BODY_BLOB_RESOURCE_PREFIX,
    BodyBlobAuthorityError,
    BodyBlobFileReadbackReceiptV1,
    BodyBlobInventoryReadbackReceiptV1,
    BodyBlobInventoryV1,
    BodyBlobObservationReadbackReceiptV1,
    build_body_blob_inventory,
    replay_body_blob_inventory,
    validate_body_blob_inventory,
)
from nbadb.contracts.raw_request_authority import (
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
)
from tests.unit.contracts.test_raw_request_authority import (
    _STARTED_AT,
    _attempt,
    _sha,
    _video_bundle,
)


class _TextSubclass(str):
    pass


def _unchecked_selection[T](value: T, selection: str) -> T:
    candidate = copy(value)
    object.__setattr__(candidate, "selection", selection)
    return candidate


def _downstream_observation(
    *,
    selected: RequestObservationV2,
    body_object_sha256: str,
    provider_call_ordinal: int = 1,
) -> RequestObservationV2:
    attempt = _attempt(
        source_family="stats",
        endpoint_id="VideoDetails",
        parameters={"team_id": 1, "player_id": 2, "season": "2024-25"},
        provider_authority_sha256=selected.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=selected.attempt.endpoint_contract_sha256,
        provider_call_ordinal=provider_call_ordinal,
    )
    return RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1,
        lifecycle="incomplete",
        outcome="downstream_incomplete",
        failure_class="response_contract",
        root_exception_class="ResponseContractError",
        body_disposition="public_parser_input",
        body_object_sha256=body_object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[],
        route_landing_sha256s=[],
        capture_response_receipt_sha256=_sha(f"capture:{attempt.attempt_sha256}"),
        logical_receipt_sha256=None,
    )


def _shared_body_bundle() -> RawRequestAuthorityBundleV2:
    selected_bundle, selected, occurrences, landings = _video_bundle("VideoDetails", {})
    incomplete = _downstream_observation(
        selected=selected,
        body_object_sha256=selected_bundle.objects[0].object_sha256,
    )
    return RawRequestAuthorityBundleV2.build(
        objects=selected_bundle.objects,
        observations=[incomplete, selected],
        occurrences=occurrences,
        landings=landings,
    )


def _readback_receipt(
    bundle: RawRequestAuthorityBundleV2,
    inventory: BodyBlobInventoryV1,
) -> BodyBlobInventoryReadbackReceiptV1:
    object_by_sha = {item.object_sha256: item for item in bundle.objects}
    files = tuple(
        BodyBlobFileReadbackReceiptV1.build(
            descriptor=descriptor,
            parser_input_object=object_by_sha[descriptor.parser_input_object_sha256],
            readback_bytes=object_by_sha[descriptor.parser_input_object_sha256].stored_payload,
            store_namespace_sha256=_sha("store"),
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_descriptor_sha256=descriptor.descriptor_sha256,
        )
        for descriptor in inventory.descriptors
    )
    file_by_descriptor = {item.descriptor_sha256: item for item in files}
    observation_receipts = tuple(
        BodyBlobObservationReadbackReceiptV1.build(
            reference=reference,
            file_readback=file_by_descriptor[reference.descriptor_sha256],
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_reference_sha256=reference.reference_sha256,
            expected_file_readback_receipt_sha256=file_by_descriptor[
                reference.descriptor_sha256
            ].receipt_sha256,
        )
        for reference in inventory.references
    )
    return BodyBlobInventoryReadbackReceiptV1.build(
        inventory=inventory,
        file_readbacks=files,
        observation_readbacks=observation_receipts,
        store_namespace_sha256=_sha("store"),
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        expected_inventory_sha256=inventory.inventory_sha256,
    )


def test_duplicate_body_is_one_blob_with_two_exact_observation_references() -> None:
    bundle = _shared_body_bundle()
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    assert inventory.descriptor_count == 1
    assert inventory.reference_count == 2
    assert inventory.selected_reference_count == 1
    assert inventory.incomplete_reference_count == 1
    assert [item.selection for item in inventory.references] == [
        "selected_terminal",
        "downstream_incomplete",
    ]
    assert {item.descriptor_sha256 for item in inventory.references} == {
        inventory.descriptors[0].descriptor_sha256
    }
    descriptor = inventory.descriptors[0]
    assert descriptor.blob_sha256 == bundle.objects[0].stored_sha256
    assert descriptor.relative_resource_name == (
        f"{BODY_BLOB_RESOURCE_PREFIX}/{descriptor.blob_sha256[:2]}/"
        f"{descriptor.blob_sha256}.payload.gz"
    )


def test_inventory_validate_and_canonical_replay_rederive_raw_bundle() -> None:
    bundle = _shared_body_bundle()
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    assert (
        validate_body_blob_inventory(
            inventory,
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
        == inventory
    )
    assert (
        replay_body_blob_inventory(
            inventory.to_canonical_bytes(),
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
        == inventory
    )
    assert (
        BodyBlobInventoryV1.from_canonical_bytes(
            inventory.to_canonical_bytes(),
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
        == inventory
    )


def test_scoped_empty_inventory_and_readback_have_exact_zero_roots() -> None:
    bundle = RawRequestAuthorityBundleV2.build(
        objects=[],
        observations=[],
        occurrences=[],
        landings=[],
    )
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    assert inventory.descriptors == ()
    assert inventory.references == ()
    assert inventory.total_stored_bytes == 0
    receipt = BodyBlobInventoryReadbackReceiptV1.build(
        inventory=inventory,
        file_readbacks=(),
        observation_readbacks=(),
        store_namespace_sha256=_sha("empty-store"),
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        expected_inventory_sha256=inventory.inventory_sha256,
    )
    assert receipt.file_readback_count == 0
    assert receipt.observation_readback_count == 0
    assert receipt.total_readback_bytes == 0
    assert receipt.raw_authority_bundle_sha256 == bundle.bundle_sha256


def test_three_readback_layers_bind_exact_object_reference_and_inventory() -> None:
    bundle = _shared_body_bundle()
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    receipt = _readback_receipt(bundle, inventory)
    assert receipt.file_readback_count == inventory.descriptor_count
    assert receipt.observation_readback_count == inventory.reference_count
    assert receipt.selected_observation_readback_count == 1
    assert receipt.incomplete_observation_readback_count == 1
    assert receipt.total_readback_bytes == bundle.objects[0].stored_bytes
    first_file = receipt.file_readbacks[0]
    assert (
        BodyBlobFileReadbackReceiptV1.from_canonical_bytes(
            first_file.to_canonical_bytes(),
            descriptor=inventory.descriptors[0],
            parser_input_object=bundle.objects[0],
            readback_bytes=bundle.objects[0].stored_payload,
            store_namespace_sha256=_sha("store"),
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_descriptor_sha256=inventory.descriptors[0].descriptor_sha256,
            expected_receipt_sha256=first_file.receipt_sha256,
        )
        == first_file
    )
    first_observation = receipt.observation_readbacks[0]
    reference = inventory.references[0]
    assert (
        BodyBlobObservationReadbackReceiptV1.from_canonical_bytes(
            first_observation.to_canonical_bytes(),
            reference=reference,
            file_readback=first_file,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_reference_sha256=reference.reference_sha256,
            expected_file_readback_receipt_sha256=first_file.receipt_sha256,
            expected_receipt_sha256=first_observation.receipt_sha256,
        )
        == first_observation
    )
    assert (
        BodyBlobInventoryReadbackReceiptV1.from_canonical_bytes(
            receipt.to_canonical_bytes(),
            inventory=inventory,
            file_readbacks=receipt.file_readbacks,
            observation_readbacks=receipt.observation_readbacks,
            store_namespace_sha256=_sha("store"),
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
        == receipt
    )
    with pytest.raises(BodyBlobAuthorityError, match="observation readback selection"):
        replace(
            first_observation,
            selection=_TextSubclass("selected_terminal"),
        )
    hostile_observation = _unchecked_selection(
        first_observation,
        _TextSubclass("selected_terminal"),
    )
    hostile_observations = (hostile_observation, *receipt.observation_readbacks[1:])
    with pytest.raises(BodyBlobAuthorityError, match="observation readback selection"):
        BodyBlobInventoryReadbackReceiptV1.build(
            inventory=inventory,
            file_readbacks=receipt.file_readbacks,
            observation_readbacks=hostile_observations,
            store_namespace_sha256=_sha("store"),
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
    with pytest.raises(BodyBlobAuthorityError, match="observation readback selection"):
        BodyBlobInventoryReadbackReceiptV1.from_canonical_bytes(
            receipt.to_canonical_bytes(),
            inventory=inventory,
            file_readbacks=receipt.file_readbacks,
            observation_readbacks=hostile_observations,
            store_namespace_sha256=_sha("store"),
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )


def test_foreign_bundle_or_coordinated_reseal_cannot_enter_inventory() -> None:
    bundle = _shared_body_bundle()
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    with pytest.raises(BodyBlobAuthorityError, match="external pins"):
        validate_body_blob_inventory(
            inventory,
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=_sha("foreign-inventory"),
        )
    with pytest.raises(BodyBlobAuthorityError, match="root|identity"):
        replace(
            inventory,
            descriptor_root_sha256=_sha("resealed-root"),
            inventory_sha256=_sha("resealed-inventory"),
        )
    first_reference = inventory.references[0]
    with pytest.raises(BodyBlobAuthorityError, match="reference selection"):
        replace(
            first_reference,
            selection=_TextSubclass("selected_terminal"),
        )
    hostile_reference = _unchecked_selection(
        first_reference,
        _TextSubclass("selected_terminal"),
    )
    hostile_inventory = copy(inventory)
    object.__setattr__(
        hostile_inventory,
        "references",
        (hostile_reference, *inventory.references[1:]),
    )
    with pytest.raises(BodyBlobAuthorityError, match="reference selection"):
        validate_body_blob_inventory(
            hostile_inventory,
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )


def test_orphan_duplicate_and_reordered_members_are_rejected() -> None:
    bundle = _shared_body_bundle()
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    with pytest.raises(BodyBlobAuthorityError, match="duplicate|orphan"):
        replace(
            inventory,
            descriptors=(*inventory.descriptors, inventory.descriptors[0]),
            descriptor_count=2,
            inventory_sha256=_sha("duplicate-inventory"),
        )
    with pytest.raises(BodyBlobAuthorityError, match="order"):
        replace(
            inventory,
            references=tuple(reversed(inventory.references)),
            inventory_sha256=_sha("reordered-inventory"),
        )
    receipt = _readback_receipt(bundle, inventory)
    with pytest.raises(BodyBlobAuthorityError, match="order|binding"):
        BodyBlobInventoryReadbackReceiptV1.build(
            inventory=inventory,
            file_readbacks=receipt.file_readbacks,
            observation_readbacks=tuple(reversed(receipt.observation_readbacks)),
            store_namespace_sha256=_sha("store"),
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )


def test_canonical_decoder_rejects_depth_duplicate_keys_and_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _shared_body_bundle()
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    deep = b"[" * 65 + b"0" + b"]" * 65
    with pytest.raises(BodyBlobAuthorityError, match="structural"):
        replay_body_blob_inventory(
            deep,
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
    duplicate = (
        b'{"inventory_sha256":"'
        + inventory.inventory_sha256.encode("ascii")
        + b'","inventory_sha256":"'
        + inventory.inventory_sha256.encode("ascii")
        + b'"}'
    )
    with pytest.raises(BodyBlobAuthorityError, match="duplicate"):
        replay_body_blob_inventory(
            duplicate,
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
    oversized_number = b'{"value":' + b"9" * 129 + b"}"
    with pytest.raises(BodyBlobAuthorityError, match="oversized number"):
        replay_body_blob_inventory(
            oversized_number,
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
    monkeypatch.setattr(body_blob_inventory, "MAX_BODY_BLOB_CANONICAL_BYTES", 32)
    with pytest.raises(BodyBlobAuthorityError, match="byte bound"):
        replay_body_blob_inventory(
            b" " * 33,
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )


def test_recursion_error_is_normalized_and_dto_subclasses_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _shared_body_bundle()
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )

    def explode(*_args: object, **_kwargs: object) -> object:
        raise RecursionError

    monkeypatch.setattr(body_blob_inventory.json, "loads", explode)
    with pytest.raises(BodyBlobAuthorityError, match="cannot be decoded"):
        replay_body_blob_inventory(
            inventory.to_canonical_bytes(),
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )

    class ForeignInventory(BodyBlobInventoryV1):
        pass

    foreign = object.__new__(ForeignInventory)
    with pytest.raises(BodyBlobAuthorityError, match="foreign structured type"):
        validate_body_blob_inventory(
            foreign,
            bundle=bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )


def test_known_secret_and_embedded_authorization_are_rejected() -> None:
    selected_bundle, selected, _occurrences, _landings = _video_bundle("VideoDetails", {})
    body = ParserInputObjectV2.from_parser_input('{"note":"private-value-123"}')
    incomplete = _downstream_observation(
        selected=selected,
        body_object_sha256=body.object_sha256,
        provider_call_ordinal=3,
    )
    bundle = RawRequestAuthorityBundleV2.build(
        objects=[body],
        observations=[incomplete],
        occurrences=[],
        landings=[],
    )
    with pytest.raises(BodyBlobAuthorityError, match="secret"):
        build_body_blob_inventory(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            known_secrets=("private-value-123",),
        )
    inventory = build_body_blob_inventory(
        selected_bundle,
        expected_raw_authority_bundle_sha256=selected_bundle.bundle_sha256,
    )
    malicious = json.dumps(
        {
            "inventory_sha256": inventory.inventory_sha256,
            "note": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            "raw_authority_bundle_sha256": selected_bundle.bundle_sha256,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    with pytest.raises(BodyBlobAuthorityError, match="secret"):
        replay_body_blob_inventory(
            malicious,
            bundle=selected_bundle,
            expected_raw_authority_bundle_sha256=selected_bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
