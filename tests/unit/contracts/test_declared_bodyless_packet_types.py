from __future__ import annotations

import ast
import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, cast

import pytest

import nbadb.contracts.declared_bodyless_packet_types as packet_types
from nbadb.contracts.declared_bodyless_packet_types import (
    DECLARED_BODYLESS_PACKET_CODEC_CONTRACT_SHA256,
    DECLARED_BODYLESS_PACKET_CODEC_ID,
    DECLARED_BODYLESS_PACKET_ENCODING_ID,
    DECLARED_BODYLESS_PACKET_REPRESENTATION_ID,
    DeclaredBodylessPacketError,
    DeclaredBodylessPacketProjectionV1,
    DeclaredBodylessPacketReadbackReceiptV1,
    DeclaredBodylessPacketV1,
    decode_public_canonical_packet,
    rederive_declared_bodyless_packet_projection,
    validate_declared_bodyless_packet_bytes,
    validate_declared_bodyless_packet_identity,
    validate_declared_bodyless_packet_readback_receipt,
)

_FROZEN_SCHEMA_JSON = (
    '[{"name":"id","ordinal":0,"projected":true,"sample_type":"int"},'
    '{"name":"nickname","ordinal":1,"projected":false,"sample_type":"str"}]'
)
_PACKET_BYTES = b'[[7,"Alpha"],[8,""]]'

_PROJECTION_VECTOR = {
    "field_count": 2,
    "row_count": 2,
    "cell_count": 4,
    "schema_root_sha256": "8c2a760dc9aae25c276f0a25e7ee61bb79c5a23b8270458e8ea3d9c8e0e0c2bb",
    "content_root_sha256": "23ef509d9d54c735532bae5549221d68aae216a50b61c4a788529eb4987d86d8",
    "row_root_sha256": "a3a6d838484cdb85fdfbbc80af2973adfb5ad2b228d2318f3f3b4465f99427e6",
    "cell_root_sha256": "93c9bb8c2d5c3a94484659489d4650ee7aae00eda6f050b0d76bf5b118d05d2c",
}
_PACKET_ROW_FIELDS = (
    "schema_version",
    "kind",
    "observation_sha256",
    "observation_record_sha256",
    "attempt_sha256",
    "logical_receipt_sha256",
    "endpoint_id",
    "endpoint_contract_sha256",
    "provider_authority_sha256",
    "public_resource_name",
    "frozen_static_schema_json",
    "frozen_static_schema_sha256",
    "source_sha",
    "run_id",
    "run_attempt",
    "chain_id",
    "lane_id",
    "representation_id",
    "media_type",
    "encoding_id",
    "codec_contract_id",
    "codec_contract_sha256",
    "uncompressed_packet_sha256",
    "uncompressed_packet_length",
    "stored_payload_sha256",
    "stored_payload_length",
    "field_count",
    "row_count",
    "cell_count",
    "schema_root_sha256",
    "content_root_sha256",
    "row_root_sha256",
    "cell_root_sha256",
    "packet_authority_sha256",
)
_READBACK_ROW_FIELDS = (
    "schema_version",
    "kind",
    "observation_sha256",
    "observation_record_sha256",
    "packet_authority_sha256",
    "public_resource_name",
    "frozen_static_schema_sha256",
    "store_namespace_sha256",
    "stored_payload_sha256",
    "stored_payload_length",
    "readback_payload_sha256",
    "readback_payload_length",
    "field_count",
    "row_count",
    "cell_count",
    "schema_root_sha256",
    "content_root_sha256",
    "row_root_sha256",
    "cell_root_sha256",
    "receipt_sha256",
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _build_packet(
    *,
    packet_bytes: bytes = _PACKET_BYTES,
    frozen_schema_json: str = _FROZEN_SCHEMA_JSON,
    endpoint_id: str = "static_fixture",
    known_secrets: tuple[str | bytes, ...] = (),
) -> DeclaredBodylessPacketV1:
    return DeclaredBodylessPacketV1.build(
        observation_sha256=_sha("observation"),
        observation_record_sha256=_sha("observation-record"),
        attempt_sha256=_sha("observation"),
        logical_receipt_sha256=_sha("logical-receipt"),
        endpoint_id=endpoint_id,
        endpoint_contract_sha256=_sha("endpoint-contract"),
        provider_authority_sha256=_sha("provider-authority"),
        frozen_static_schema_json=frozen_schema_json,
        source_sha="a" * 40,
        run_id=7,
        run_attempt=1,
        chain_id="chain-static",
        lane_id="lane-static",
        packet_bytes=packet_bytes,
        expected_observation_sha256=_sha("observation"),
        expected_observation_record_sha256=_sha("observation-record"),
        known_secrets=known_secrets,
    )


@pytest.fixture(scope="module")
def packet() -> DeclaredBodylessPacketV1:
    return _build_packet()


@pytest.fixture(scope="module")
def receipt(packet: DeclaredBodylessPacketV1) -> DeclaredBodylessPacketReadbackReceiptV1:
    return DeclaredBodylessPacketReadbackReceiptV1.build(
        packet=packet,
        readback_bytes=_PACKET_BYTES,
        store_namespace_sha256=_sha("store-namespace"),
        expected_packet_authority_sha256=packet.packet_authority_sha256,
    )


def test_frozen_projection_and_codec_vectors_are_byte_exact() -> None:
    projection = rederive_declared_bodyless_packet_projection(
        packet_bytes=_PACKET_BYTES,
        frozen_static_schema_json=_FROZEN_SCHEMA_JSON,
    )
    assert projection.to_row() == _PROJECTION_VECTOR
    assert (
        DECLARED_BODYLESS_PACKET_CODEC_CONTRACT_SHA256
        == "d3869d82419903bb090f0ea0002fac7a0bdfcaffbabc21e4b040532f8ce6fc27"
    )
    assert DECLARED_BODYLESS_PACKET_CODEC_ID == "identity-bytes-v1"
    assert DECLARED_BODYLESS_PACKET_ENCODING_ID == "utf-8-strict-v1"
    assert (
        DECLARED_BODYLESS_PACKET_REPRESENTATION_ID == "nbadb_static_source_rows_canonical_json_v1"
    )


def test_projection_strict_row_and_canonical_byte_replay() -> None:
    projection = rederive_declared_bodyless_packet_projection(
        packet_bytes=_PACKET_BYTES,
        frozen_static_schema_json=_FROZEN_SCHEMA_JSON,
    )
    assert DeclaredBodylessPacketProjectionV1.from_row(projection.to_row()) == projection
    assert (
        DeclaredBodylessPacketProjectionV1.from_canonical_bytes(projection.to_canonical_bytes())
        == projection
    )
    reordered = dict(reversed(tuple(projection.to_row().items())))
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketProjectionV1.from_row(reordered)
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketProjectionV1.from_row(dict(projection.to_row(), extra=1))


def test_packet_build_is_exact_value_authority(packet: DeclaredBodylessPacketV1) -> None:
    assert tuple(packet.to_row()) == _PACKET_ROW_FIELDS
    assert packet.observation_sha256 == packet.attempt_sha256 == _sha("observation")
    assert packet.stored_payload_sha256 == hashlib.sha256(_PACKET_BYTES).hexdigest()
    assert packet.stored_payload_sha256 == packet.uncompressed_packet_sha256
    assert packet.stored_payload_length == packet.uncompressed_packet_length == len(_PACKET_BYTES)
    assert packet.field_count == 2
    assert packet.row_count == 2
    assert packet.cell_count == 4
    assert packet.packet_authority_sha256 == (
        "488355d20eed062d85d0011a12a8fa9c97ce133437de4b9180a4ff164f237e10"
    )
    assert hashlib.sha256(packet.to_canonical_bytes()).hexdigest() == (
        "288cfc79970e475e3bd58f21ff69f99086447cab123d4d1630fe2537a31ba5b8"
    )
    public_text = packet.to_canonical_bytes().decode()
    assert "bodyless_evidence" not in public_text
    assert "/Users/" not in public_text
    assert "nba_api" not in public_text


def test_packet_strict_row_and_canonical_byte_replay(packet: DeclaredBodylessPacketV1) -> None:
    rebuilt_row = DeclaredBodylessPacketV1.from_row(
        packet.to_row(),
        packet_bytes=_PACKET_BYTES,
        expected_observation_sha256=packet.observation_sha256,
        expected_observation_record_sha256=packet.observation_record_sha256,
        expected_packet_authority_sha256=packet.packet_authority_sha256,
    )
    rebuilt_bytes = DeclaredBodylessPacketV1.from_canonical_bytes(
        packet.to_canonical_bytes(),
        packet_bytes=_PACKET_BYTES,
        expected_observation_sha256=packet.observation_sha256,
        expected_observation_record_sha256=packet.observation_record_sha256,
        expected_packet_authority_sha256=packet.packet_authority_sha256,
    )
    assert rebuilt_row == rebuilt_bytes == packet
    assert rebuilt_bytes.to_canonical_bytes() == packet.to_canonical_bytes()

    reordered = dict(reversed(tuple(packet.to_row().items())))
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketV1.from_row(
            reordered,
            packet_bytes=_PACKET_BYTES,
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )


def test_noncanonical_packet_identity_bytes_fail(packet: DeclaredBodylessPacketV1) -> None:
    noncanonical = json.dumps(packet.to_row(), sort_keys=True, separators=(", ", ": ")).encode()
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketV1.from_canonical_bytes(
            noncanonical,
            packet_bytes=_PACKET_BYTES,
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )


def test_readback_build_and_strict_replay(
    packet: DeclaredBodylessPacketV1,
    receipt: DeclaredBodylessPacketReadbackReceiptV1,
) -> None:
    assert tuple(receipt.to_row()) == _READBACK_ROW_FIELDS
    assert receipt.readback_payload_sha256 == packet.stored_payload_sha256
    assert receipt.readback_payload_length == packet.stored_payload_length
    assert receipt.receipt_sha256 == (
        "f0874057023cc303b0ca48eda2ce0ad22725bfdf88a1041369c661083d7688fb"
    )
    assert hashlib.sha256(receipt.to_canonical_bytes()).hexdigest() == (
        "f97d2bb53f4a735f3e608f49c8b9805e482eb9cde895a0147fc38563915a6d58"
    )
    assert (
        DeclaredBodylessPacketReadbackReceiptV1.from_row(
            receipt.to_row(),
            packet=packet,
            readback_bytes=_PACKET_BYTES,
            store_namespace_sha256=_sha("store-namespace"),
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
        == receipt
    )
    assert (
        DeclaredBodylessPacketReadbackReceiptV1.from_canonical_bytes(
            receipt.to_canonical_bytes(),
            packet=packet,
            readback_bytes=_PACKET_BYTES,
            store_namespace_sha256=_sha("store-namespace"),
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
        == receipt
    )


@pytest.mark.parametrize(
    "encoded",
    [
        b'{"safe":1,"safe":2}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e9999}',
        b'{"value":01}',
        b'{ "value":1}',
        b'[{"b":1,"a":2}]',
        b'["\\ud800"]',
        b"\xff",
    ],
)
def test_duplicate_nonfinite_invalid_and_noncanonical_json_fail(encoded: bytes) -> None:
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        decode_public_canonical_packet(encoded)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_json_recursion_is_suppressed_but_base_exception_signals_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def recursive_loads(*_args: object, **_kwargs: object) -> object:
        raise RecursionError("private recursion detail")

    monkeypatch.setattr(packet_types.json, "loads", recursive_loads)
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        decode_public_canonical_packet(b"[]")
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True

    def interrupted_loads(*_args: object, **_kwargs: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(packet_types.json, "loads", interrupted_loads)
    with pytest.raises(KeyboardInterrupt):
        decode_public_canonical_packet(b"[]")


def test_deep_and_huge_number_preflight_precedes_json_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_loads(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("json.loads ran before lexical preflight")

    monkeypatch.setattr(packet_types.json, "loads", forbidden_loads)
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(b"[" * 10_000 + b"0" + b"]" * 10_000)
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(b"[" + b"9" * 50_000 + b"]")


def test_packet_string_node_and_byte_bounds_are_preflighted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(packet_types, "MAX_DECLARED_BODYLESS_STRING_BYTES", 3)
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(b'["four"]')
    monkeypatch.setattr(packet_types, "MAX_DECLARED_BODYLESS_STRING_BYTES", 1024)
    monkeypatch.setattr(packet_types, "MAX_DECLARED_BODYLESS_JSON_NODES", 3)
    assert decode_public_canonical_packet(b"[0,0]") == [0, 0]
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(b"[0,0,0]")
    monkeypatch.setattr(packet_types, "MAX_DECLARED_BODYLESS_PACKET_BYTES", 5)
    assert decode_public_canonical_packet(b"[0,0]") == [0, 0]
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(b"[0,0] ")


@pytest.mark.parametrize(
    ("value", "sentinel"),
    [
        ({"apiKey": "redacted"}, "redacted"),
        ({"outer": {"accessToken": "redacted"}}, "redacted"),
        ({"sessionKey": "redacted"}, "redacted"),
        (["Authorization: Bearer abcdefghijklmnop1234"], "abcdefghijklmnop1234"),
        (["Basic YWJjZGVmZ2hpamts"], "YWJjZGVmZ2hpamts"),
        (["ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"], "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        (["AKIAABCDEFGHIJKLMNOP"], "ABCDEFGHIJKLMNOP"),
        (
            ["eyJabcdefghij.abcdefghijk.abcdefghijk"],
            "abcdefghijk",
        ),
        (["/Users/private-name/secret.txt"], "private-name"),
        (["/home/private-name/secret.txt"], "private-name"),
        (["/private/var/tmp/private-name"], "private-name"),
        (["https://user:do-not-echo@example.test/x"], "do-not-echo"),
    ],
)
def test_secret_key_and_value_matrix_fails_without_echo(value: object, sentinel: str) -> None:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        decode_public_canonical_packet(encoded)
    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None


def test_known_secret_inventory_is_exact_and_checked_before_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "one-off-private-sentinel"
    encoded = json.dumps([[7, sentinel]], separators=(",", ":")).encode()
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        decode_public_canonical_packet(encoded, known_secrets=(sentinel,))
    assert sentinel not in str(caught.value)

    class ForeignSecrets(tuple):
        pass

    def forbidden_loads(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("json.loads ran before secret admission")

    monkeypatch.setattr(packet_types.json, "loads", forbidden_loads)
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(b"[]", known_secrets=ForeignSecrets())


def test_known_secrets_cover_frozen_schema_metadata_and_all_packet_replays() -> None:
    sentinel = "one-off-private-sentinel"
    hostile_schema = (
        '[{"name":"one-off-private-sentinel","ordinal":0,"projected":true,"sample_type":"int"}]'
    )
    hostile_schema_bytes = b"[[7]]"

    with pytest.raises(DeclaredBodylessPacketError):
        rederive_declared_bodyless_packet_projection(
            packet_bytes=hostile_schema_bytes,
            frozen_static_schema_json=hostile_schema,
            known_secrets=(sentinel,),
        )
    with pytest.raises(DeclaredBodylessPacketError):
        _build_packet(
            packet_bytes=hostile_schema_bytes,
            frozen_schema_json=hostile_schema,
            known_secrets=(sentinel,),
        )

    schema_packet = _build_packet(
        packet_bytes=hostile_schema_bytes,
        frozen_schema_json=hostile_schema,
    )
    metadata_packet = _build_packet(endpoint_id=sentinel)
    with pytest.raises(DeclaredBodylessPacketError):
        _build_packet(endpoint_id=sentinel, known_secrets=(sentinel,))

    for candidate, packet_bytes in (
        (schema_packet, hostile_schema_bytes),
        (metadata_packet, _PACKET_BYTES),
    ):
        with pytest.raises(DeclaredBodylessPacketError):
            DeclaredBodylessPacketV1.from_row(
                candidate.to_row(),
                packet_bytes=packet_bytes,
                expected_observation_sha256=candidate.observation_sha256,
                expected_observation_record_sha256=candidate.observation_record_sha256,
                expected_packet_authority_sha256=candidate.packet_authority_sha256,
                known_secrets=(sentinel,),
            )
        with pytest.raises(DeclaredBodylessPacketError):
            DeclaredBodylessPacketV1.from_canonical_bytes(
                candidate.to_canonical_bytes(),
                packet_bytes=packet_bytes,
                expected_observation_sha256=candidate.observation_sha256,
                expected_observation_record_sha256=candidate.observation_record_sha256,
                expected_packet_authority_sha256=candidate.packet_authority_sha256,
                known_secrets=(sentinel,),
            )

    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketReadbackReceiptV1.build(
            packet=metadata_packet,
            readback_bytes=_PACKET_BYTES,
            store_namespace_sha256=_sha("store-namespace"),
            expected_packet_authority_sha256=metadata_packet.packet_authority_sha256,
            known_secrets=(sentinel,),
        )


def test_benign_unicode_and_auth_words_remain_public() -> None:
    value = [[7, "Magic Johnson — Bearer of the scoring load"]]
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    assert decode_public_canonical_packet(encoded) == value


@pytest.mark.parametrize(
    "schema",
    [
        "[]",
        '[{"name":"id","ordinal":false,"projected":true,"sample_type":"int"}]',
        '[{"name":"id","ordinal":0,"projected":1,"sample_type":"int"}]',
        '[{"name":"id","ordinal":0,"projected":true,"sample_type":"integer"}]',
        (
            '[{"name":"id","ordinal":0,"projected":true,"sample_type":"int"},'
            '{"name":"id","ordinal":1,"projected":false,"sample_type":"str"}]'
        ),
        '[{"name":"authToken","ordinal":0,"projected":true,"sample_type":"int"}]',
        '[{"ordinal":0,"name":"id","projected":true,"sample_type":"int"}]',
    ],
)
def test_frozen_schema_shape_type_order_and_secret_defenses(schema: str) -> None:
    with pytest.raises(DeclaredBodylessPacketError):
        rederive_declared_bodyless_packet_projection(
            packet_bytes=b"[]",
            frozen_static_schema_json=schema,
        )


@pytest.mark.parametrize(
    "packet_bytes",
    [
        b'[[7,"Alpha",1]]',
        b'[[true,"Alpha"]]',
        b'[[0,"Alpha"]]',
        b"[[7,1]]",
        b'{"id":7}',
    ],
)
def test_packet_rows_must_match_frozen_width_types_and_identifier(packet_bytes: bytes) -> None:
    with pytest.raises(DeclaredBodylessPacketError):
        rederive_declared_bodyless_packet_projection(
            packet_bytes=packet_bytes,
            frozen_static_schema_json=_FROZEN_SCHEMA_JSON,
        )


def test_zero_row_packet_has_explicit_zero_denominators() -> None:
    projection = rederive_declared_bodyless_packet_projection(
        packet_bytes=b"[]",
        frozen_static_schema_json=_FROZEN_SCHEMA_JSON,
    )
    packet = _build_packet(packet_bytes=b"[]")
    assert projection.row_count == packet.row_count == 0
    assert projection.cell_count == packet.cell_count == 0
    assert packet.stored_payload_sha256 == hashlib.sha256(b"[]").hexdigest()
    assert (
        validate_declared_bodyless_packet_bytes(
            packet,
            packet_bytes=b"[]",
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
        == packet
    )


def test_exact_builtin_types_and_dto_subclasses_are_rejected(
    packet: DeclaredBodylessPacketV1,
) -> None:
    class ForeignBytes(bytes):
        pass

    class ForeignString(str):
        pass

    class ForeignPacket(DeclaredBodylessPacketV1):
        pass

    class ForeignProjection(DeclaredBodylessPacketProjectionV1):
        pass

    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(ForeignBytes(_PACKET_BYTES))
    with pytest.raises(DeclaredBodylessPacketError):
        replace(packet, row_count=True)
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketV1.build(
            observation_sha256=ForeignString(packet.observation_sha256),
            observation_record_sha256=packet.observation_record_sha256,
            attempt_sha256=packet.attempt_sha256,
            logical_receipt_sha256=packet.logical_receipt_sha256,
            endpoint_id=packet.endpoint_id,
            endpoint_contract_sha256=packet.endpoint_contract_sha256,
            provider_authority_sha256=packet.provider_authority_sha256,
            frozen_static_schema_json=packet.frozen_static_schema_json,
            source_sha=packet.source_sha,
            run_id=packet.run_id,
            run_attempt=packet.run_attempt,
            chain_id=packet.chain_id,
            lane_id=packet.lane_id,
            packet_bytes=_PACKET_BYTES,
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        ForeignPacket.from_row(
            packet.to_row(),
            packet_bytes=_PACKET_BYTES,
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        ForeignProjection.from_row(_PROJECTION_VECTOR)


def test_dtos_are_immutable(
    packet: DeclaredBodylessPacketV1,
    receipt: DeclaredBodylessPacketReadbackReceiptV1,
) -> None:
    with pytest.raises(FrozenInstanceError):
        packet.row_count = 99  # type: ignore
    with pytest.raises(FrozenInstanceError):
        receipt.row_count = 99  # type: ignore


def test_external_pins_and_bytes_fail_before_projection(
    packet: DeclaredBodylessPacketV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_projection(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("projection ran before cheap authority checks")

    monkeypatch.setattr(
        packet_types,
        "rederive_declared_bodyless_packet_projection",
        forbidden_projection,
    )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_bytes(
            packet,
            packet_bytes=b"[]",
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_bytes(
            packet,
            packet_bytes=_PACKET_BYTES,
            expected_observation_sha256=_sha("foreign-observation"),
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )


def test_corruption_and_coordinated_projection_reseal_fail(
    packet: DeclaredBodylessPacketV1,
) -> None:
    corrupted = copy.copy(packet)
    object.__setattr__(corrupted, "row_count", packet.row_count + 1)
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_identity(
            corrupted,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )

    resealed_row = cast("dict[str, Any]", packet.to_row())
    resealed_row["content_root_sha256"] = _sha("fabricated-content-root")
    resealed_payload = {
        key: value for key, value in resealed_row.items() if key != "packet_authority_sha256"
    }
    resealed_row["packet_authority_sha256"] = _canonical_sha(resealed_payload)
    resealed = DeclaredBodylessPacketV1(**resealed_row)
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_bytes(
            resealed,
            packet_bytes=_PACKET_BYTES,
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=resealed.packet_authority_sha256,
        )


def test_deleted_slot_corruption_is_normalized(packet: DeclaredBodylessPacketV1) -> None:
    corrupted = copy.copy(packet)
    object.__delattr__(corrupted, "stored_payload_sha256")
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        validate_declared_bodyless_packet_bytes(
            corrupted,
            packet_bytes=_PACKET_BYTES,
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
    assert caught.value.__cause__ is None


def test_readback_rejects_wrong_bytes_namespace_and_reseal(
    packet: DeclaredBodylessPacketV1,
    receipt: DeclaredBodylessPacketReadbackReceiptV1,
) -> None:
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketReadbackReceiptV1.build(
            packet=packet,
            readback_bytes=b"[]",
            store_namespace_sha256=_sha("store-namespace"),
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_readback_receipt(
            receipt,
            packet=packet,
            readback_bytes=_PACKET_BYTES,
            store_namespace_sha256=_sha("foreign-store"),
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )

    resealed_row = cast("dict[str, Any]", receipt.to_row())
    resealed_row["content_root_sha256"] = _sha("fabricated-content-root")
    resealed_payload = {
        key: value for key, value in resealed_row.items() if key != "receipt_sha256"
    }
    resealed_row["receipt_sha256"] = _canonical_sha(resealed_payload)
    resealed = DeclaredBodylessPacketReadbackReceiptV1(**resealed_row)
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_readback_receipt(
            resealed,
            packet=packet,
            readback_bytes=_PACKET_BYTES,
            store_namespace_sha256=_sha("store-namespace"),
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=resealed.receipt_sha256,
        )


@pytest.mark.parametrize("root_field", ["content_root_sha256", "row_root_sha256"])
def test_readback_rederives_packet_roots_before_build_and_every_replay(
    packet: DeclaredBodylessPacketV1,
    receipt: DeclaredBodylessPacketReadbackReceiptV1,
    root_field: str,
) -> None:
    fabricated_root = _sha(f"fabricated-{root_field}")
    packet_row = cast("dict[str, Any]", packet.to_row())
    packet_row[root_field] = fabricated_root
    packet_payload = {
        key: value for key, value in packet_row.items() if key != "packet_authority_sha256"
    }
    packet_row["packet_authority_sha256"] = _canonical_sha(packet_payload)
    forged_packet = DeclaredBodylessPacketV1(**packet_row)

    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketReadbackReceiptV1.build(
            packet=forged_packet,
            readback_bytes=_PACKET_BYTES,
            store_namespace_sha256=_sha("store-namespace"),
            expected_packet_authority_sha256=forged_packet.packet_authority_sha256,
        )

    receipt_row = cast("dict[str, Any]", receipt.to_row())
    receipt_row["packet_authority_sha256"] = forged_packet.packet_authority_sha256
    receipt_row[root_field] = fabricated_root
    receipt_payload = {key: value for key, value in receipt_row.items() if key != "receipt_sha256"}
    receipt_row["receipt_sha256"] = _canonical_sha(receipt_payload)
    forged_receipt = DeclaredBodylessPacketReadbackReceiptV1(**receipt_row)

    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_readback_receipt(
            forged_receipt,
            packet=forged_packet,
            readback_bytes=_PACKET_BYTES,
            store_namespace_sha256=_sha("store-namespace"),
            expected_packet_authority_sha256=forged_packet.packet_authority_sha256,
            expected_receipt_sha256=forged_receipt.receipt_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketReadbackReceiptV1.from_row(
            forged_receipt.to_row(),
            packet=forged_packet,
            readback_bytes=_PACKET_BYTES,
            store_namespace_sha256=_sha("store-namespace"),
            expected_packet_authority_sha256=forged_packet.packet_authority_sha256,
            expected_receipt_sha256=forged_receipt.receipt_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketReadbackReceiptV1.from_canonical_bytes(
            forged_receipt.to_canonical_bytes(),
            packet=forged_packet,
            readback_bytes=_PACKET_BYTES,
            store_namespace_sha256=_sha("store-namespace"),
            expected_packet_authority_sha256=forged_packet.packet_authority_sha256,
            expected_receipt_sha256=forged_receipt.receipt_sha256,
        )


def test_strict_rows_reject_hostile_mapping_subclasses(
    packet: DeclaredBodylessPacketV1,
    receipt: DeclaredBodylessPacketReadbackReceiptV1,
) -> None:
    class ForeignRow(dict[str, object]):
        pass

    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketV1.from_row(
            ForeignRow(packet.to_row()),
            packet_bytes=_PACKET_BYTES,
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketReadbackReceiptV1.from_row(
            ForeignRow(receipt.to_row()),
            packet=packet,
            readback_bytes=_PACKET_BYTES,
            store_namespace_sha256=_sha("store-namespace"),
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )


def test_production_module_has_stdlib_only_dependency_boundary() -> None:
    source_path = Path(packet_types.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots <= {
        "__future__",
        "collections",
        "dataclasses",
        "hashlib",
        "json",
        "math",
        "re",
        "typing",
    }
    assert "nbadb" not in imported_roots
    for forbidden in (
        "raw_request_authority",
        "raw_transport_contract",
        "staging_route_contract",
        "independent_static_value_decoder",
        "nba_api",
        "polars",
        "pandera",
    ):
        assert forbidden not in source
