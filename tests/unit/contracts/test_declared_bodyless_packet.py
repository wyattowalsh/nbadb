from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, cast

import pytest

import nbadb.contracts.declared_bodyless_packet as packet_module
import nbadb.contracts.declared_bodyless_packet_types as packet_types_module
from nbadb.contracts.declared_bodyless_packet import (
    build_declared_bodyless_packet,
    validate_declared_bodyless_packet,
)
from nbadb.contracts.declared_bodyless_packet_types import (
    DECLARED_BODYLESS_PACKET_CODEC_CONTRACT_SHA256,
    DECLARED_BODYLESS_PACKET_CODEC_ID,
    DECLARED_BODYLESS_PACKET_REPRESENTATION_ID,
    DeclaredBodylessPacketError,
    DeclaredBodylessPacketReadbackReceiptV1,
    DeclaredBodylessPacketV1,
    decode_public_canonical_packet,
    rederive_declared_bodyless_packet_projection,
    validate_declared_bodyless_packet_bytes,
    validate_declared_bodyless_packet_identity,
)
from nbadb.contracts.raw_request_authority import RequestAttemptIdentityV2, RequestObservationV2
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.nba_api_runtime_contract import pinned_static_dataset_contract


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sha_json(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _static_authority(
    *,
    endpoint_id: str = "static_teams",
    provider_authority_sha256: str | None = None,
) -> tuple[RequestObservationV2, bytes]:
    contract = pinned_static_dataset_contract(endpoint_id)
    provider_root = (
        staging_route_contract_bundle().provider_authority_sha256
        if provider_authority_sha256 is None
        else provider_authority_sha256
    )
    attempt = RequestAttemptIdentityV2.build(
        semantic_request_sha256=_sha("semantic-request"),
        logical_invocation_sha256=_sha("logical-invocation"),
        provider_call_role="primary",
        provider_call_ordinal=0,
        retry_ordinal=0,
        request_ordinal=0,
        source_family="static",
        endpoint_id=endpoint_id,
        parameters={},
        provider_authority_sha256=provider_root,
        endpoint_contract_sha256=contract.contract_sha256,
        competition_id=None,
        competition_identity_sha256=None,
        scope_sha256=_sha("scope"),
        pagination_sha256=None,
        page_ordinal=None,
        source_sha="a" * 40,
        run_id=701,
        run_attempt=1,
        chain_id="chain-static",
        lane_id="lane-static",
    )
    started = datetime(2026, 8, 28, tzinfo=UTC)
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={"transport_kind": "static_snapshot"},
        started_at=started,
        finished_at=started + timedelta(microseconds=1),
        elapsed_ns=1_000,
        lifecycle="selected_terminal",
        outcome="static_snapshot_success",
        failure_class=None,
        root_exception_class=None,
        body_disposition="declared_bodyless",
        body_object_sha256=None,
        bodyless_evidence_sha256=_sha("opaque-bodyless-evidence-not-packet-bytes"),
        result_occurrence_sha256s=[_sha("result-occurrence")],
        route_landing_sha256s=[_sha("route-landing")],
        capture_response_receipt_sha256=_sha("capture-response"),
        logical_receipt_sha256=_sha("logical-receipt"),
    )
    rows = getattr(importlib.import_module("nba_api.stats.library.data"), contract.source_symbol)
    packet_bytes = json.dumps(
        rows,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return observation, packet_bytes


@pytest.fixture(scope="module")
def admitted_packet() -> tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1]:
    observation, packet_bytes = _static_authority()
    packet = build_declared_bodyless_packet(
        observation=observation,
        expected_observation_sha256=observation.attempt.observation_sha256,
        expected_observation_record_sha256=observation.observation_record_sha256,
        packet_bytes=packet_bytes,
    )
    return observation, packet_bytes, packet


def test_exact_static_packet_binds_selected_observation_and_public_roots(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, packet_bytes, packet = admitted_packet
    assert packet.observation_sha256 == observation.attempt.observation_sha256
    assert packet.observation_record_sha256 == observation.observation_record_sha256
    assert packet.endpoint_id == "static_teams"
    assert packet.endpoint_contract_sha256 == observation.attempt.endpoint_contract_sha256
    assert packet.provider_authority_sha256 == observation.attempt.provider_authority_sha256
    assert packet.representation_id == DECLARED_BODYLESS_PACKET_REPRESENTATION_ID
    assert packet.codec_contract_id == DECLARED_BODYLESS_PACKET_CODEC_ID
    assert packet.codec_contract_sha256 == DECLARED_BODYLESS_PACKET_CODEC_CONTRACT_SHA256
    assert packet.uncompressed_packet_sha256 == hashlib.sha256(packet_bytes).hexdigest()
    assert packet.stored_payload_sha256 == packet.uncompressed_packet_sha256
    assert packet.stored_payload_length == len(packet_bytes)
    assert packet.row_count == 30
    assert packet.field_count == 8
    assert packet.cell_count == 240
    assert packet.public_resource_name.endswith(f"{packet.stored_payload_sha256}.json")

    public = packet.to_row()
    assert "bodyless_evidence_sha256" not in public
    assert all("/Users/" not in str(value) for value in public.values())
    assert all("nba_api.stats.library.data" not in str(value) for value in public.values())


def test_migration_preserves_packet_projection_and_readback_identity_bytes(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    _observation, packet_bytes, packet = admitted_packet
    projection = rederive_declared_bodyless_packet_projection(
        packet_bytes=packet_bytes,
        frozen_static_schema_json=packet.frozen_static_schema_json,
    )
    receipt = DeclaredBodylessPacketReadbackReceiptV1.build(
        packet=packet,
        readback_bytes=packet_bytes,
        store_namespace_sha256="0" * 64,
        expected_packet_authority_sha256=packet.packet_authority_sha256,
    )

    assert packet.packet_authority_sha256 == (
        "fc6548a693673fd9634e335f54dfa97308c804ae240db8c7f0929f11fa965a89"
    )
    assert hashlib.sha256(packet.to_canonical_bytes()).hexdigest() == (
        "d3b7b312f43f18d9d82e8f9bdfaaac8becf5e4fad5d4b2c58a1369795c4d51b2"
    )
    assert receipt.receipt_sha256 == (
        "6f2673298345ca6a2db1408e471648f47806c0866d1384b77b7ac1e3487dd4c0"
    )
    assert hashlib.sha256(receipt.to_canonical_bytes()).hexdigest() == (
        "c6e86560d2baa034ca9565c52e56316b8c3fd01b2b049e63cf7fc6dd03771b55"
    )
    assert (
        projection.schema_root_sha256,
        projection.content_root_sha256,
        projection.row_root_sha256,
        projection.cell_root_sha256,
    ) == (
        "b7ac27e94f1adc6dbfcc3cec4deaa67e335cbc5f4a94493dfa081f5d8a2ae59e",
        "3cc806c0393c0a815d8ab5a17701b598bbb8dbf4618b85cbc551bdfd10f1b23d",
        "602b262d73187d8a5b8efa4dcc1d1a0ed494dd2d64e5ab3407cccfe5d46ba639",
        "86b8ab388428cde9996226cabb03bcbd99cafd9da4edcc8675299895169618be",
    )


def test_producer_has_only_provider_functions_and_private_leaf_imports() -> None:
    source_path = Path(packet_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden_duplicates = {
        "DeclaredBodylessPacketProjectionV1",
        "DeclaredBodylessPacketReadbackReceiptV1",
        "DeclaredBodylessPacketV1",
        "decode_public_canonical_packet",
        "rederive_declared_bodyless_packet_projection",
        "validate_declared_bodyless_packet_bytes",
        "validate_declared_bodyless_packet_identity",
        "validate_declared_bodyless_packet_readback_receipt",
    }
    assert forbidden_duplicates.isdisjoint(definitions)
    assert packet_module.__all__ == [
        "build_declared_bodyless_packet",
        "validate_declared_bodyless_packet",
    ]
    leaf_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "nbadb.contracts.declared_bodyless_packet_types"
    ]
    assert leaf_imports
    leaf_aliases = [alias for node in leaf_imports for alias in node.names]
    assert all(alias.asname is not None and alias.asname.startswith("_") for alias in leaf_aliases)


def test_packet_identity_roundtrips_from_frozen_dto_and_exact_bytes(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, packet_bytes, packet = admitted_packet
    rebuilt = DeclaredBodylessPacketV1.from_canonical_bytes(
        packet.to_canonical_bytes(),
        packet_bytes=packet_bytes,
        expected_observation_sha256=observation.attempt.observation_sha256,
        expected_observation_record_sha256=observation.observation_record_sha256,
        expected_packet_authority_sha256=packet.packet_authority_sha256,
    )
    assert rebuilt.to_canonical_bytes() == packet.to_canonical_bytes()
    assert (
        validate_declared_bodyless_packet_bytes(
            rebuilt,
            packet_bytes=packet_bytes,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
        == packet
    )


def test_packet_canonical_decode_sanitizes_unexpected_field_cause(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, packet_bytes, packet = admitted_packet
    payload = packet.to_row()
    payload["attacker_controlled_field"] = "do-not-echo-unexpected-field"
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    with pytest.raises(DeclaredBodylessPacketError) as caught:
        DeclaredBodylessPacketV1.from_canonical_bytes(
            encoded,
            packet_bytes=packet_bytes,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
    assert "do-not-echo-unexpected-field" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_opaque_bodyless_digest_is_never_accepted_as_packet_bytes(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, _packet_bytes, _packet = admitted_packet
    assert observation.bodyless_evidence_sha256 is not None
    with pytest.raises(DeclaredBodylessPacketError):
        build_declared_bodyless_packet(
            observation=observation,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            packet_bytes=observation.bodyless_evidence_sha256.encode(),
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
        b"\xff",
    ],
)
def test_malformed_duplicate_nonfinite_and_noncanonical_json_fail_closed(encoded: bytes) -> None:
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(encoded)


@pytest.mark.parametrize(
    ("encoded", "sentinel"),
    [
        (b'{"apiKey":"do-not-echo-key"}', "do-not-echo-key"),
        (b'{"outer":{"accessToken":"do-not-echo-token"}}', "do-not-echo-token"),
        (b'{"clientSecret":"do-not-echo-secret"}', "do-not-echo-secret"),
        (b'["Bearer do-not-echo-bearer"]', "do-not-echo-bearer"),
        (
            b'["prefix Authorization: Bearer abcdefghijklmnop1234 suffix"]',
            "abcdefghijklmnop1234",
        ),
        (b'["prefix Bearer abcdefghijklmnop1234 suffix"]', "abcdefghijklmnop1234"),
        (b'["/Users/private-name/secret.txt"]', "private-name"),
        (b'["/Users/private-name"]', "private-name"),
        (b'["/home/private-name"]', "private-name"),
        (b'["/private/var"]', "private/var"),
        (b'["prefix /Users/private-name suffix"]', "private-name"),
        (b'["prefix /home/private-name suffix"]', "private-name"),
        (b'["prefix /private/var suffix"]', "private/var"),
        (b'["prefix /private/var: suffix"]', "private/var"),
        (b'["prefix /private/var, suffix"]', "private/var"),
        (b'["prefix /private/var. suffix"]', "private/var"),
        (b'["prefix /private/var) suffix"]', "private/var"),
        (b'["https://user:do-not-echo@example.test/x"]', "do-not-echo"),
        (b'["ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"]', "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    ],
)
def test_secret_shaped_nested_keys_and_values_fail_without_echo(
    encoded: bytes,
    sentinel: str,
) -> None:
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        decode_public_canonical_packet(encoded)
    assert sentinel not in str(caught.value)


@pytest.mark.parametrize(
    "key",
    [
        "githubToken",
        "privateKey",
        "secretKey",
        "token",
        "secret",
        "auth",
        "authentication",
        "authToken",
        "session",
        "sessionKey",
        "api-token",
    ],
)
def test_additional_secret_shaped_keys_fail_without_echo(key: str) -> None:
    encoded = json.dumps({key: "opaque-value"}, separators=(",", ":")).encode()
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        decode_public_canonical_packet(encoded)
    assert key not in str(caught.value)


def test_malformed_secret_has_no_untrusted_exception_cause() -> None:
    secret = "do-not-echo-malformed-secret"
    encoded = f'{{"password":"{secret}",}}'.encode()
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        decode_public_canonical_packet(encoded)
    assert secret not in str(caught.value)
    assert caught.value.__cause__ is None


def test_known_secret_inventory_rejects_exact_nested_value_without_echo() -> None:
    sentinel = "one-off-secret-sentinel"
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        decode_public_canonical_packet(
            json.dumps([[1, sentinel]], separators=(",", ":")).encode(),
            known_secrets=(sentinel,),
        )
    assert sentinel not in str(caught.value)


@pytest.mark.parametrize(
    "key",
    [
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "/Users/private-name/secret.txt",
        "https://user:do-not-echo@example.test/x",
    ],
)
def test_secret_shaped_generic_key_text_fails_without_echo(key: str) -> None:
    encoded = json.dumps({key: 1}, separators=(",", ":")).encode()
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        decode_public_canonical_packet(encoded)
    assert key not in str(caught.value)


def test_known_secret_inventory_rejects_exact_key_without_echo() -> None:
    sentinel = "one-off-secret-key-sentinel"
    encoded = json.dumps({sentinel: 1}, separators=(",", ":")).encode()
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        decode_public_canonical_packet(encoded, known_secrets=(sentinel,))
    assert sentinel not in str(caught.value)


def test_secret_inventory_is_admitted_before_json_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ForeignSecrets(tuple):
        pass

    def forbidden_loads(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("JSON allocation preceded secret-inventory admission")

    monkeypatch.setattr(packet_types_module.json, "loads", forbidden_loads)
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(b"[]", known_secrets=ForeignSecrets())


def test_benign_nba_unicode_text_is_public_safe() -> None:
    value = [[1610612747, "Los Angeles Lakers", "Magic Johnson — NBA legend"]]
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    assert decode_public_canonical_packet(encoded) == value


@pytest.mark.parametrize(
    "value",
    [
        "Basic Basketball",
        "Bearer of the scoring load",
        "Authorization is required for League Pass",
    ],
)
def test_auth_filter_preserves_benign_nba_text(value: str) -> None:
    encoded = json.dumps([[1, value]], ensure_ascii=False, separators=(",", ":")).encode()
    assert decode_public_canonical_packet(encoded) == [[1, value]]


def test_embedded_authorization_cannot_form_packet_or_receipt_authority() -> None:
    observation, packet_bytes = _static_authority()
    rows = json.loads(packet_bytes)
    sentinel = "prefix Authorization: Bearer abcdefghijklmnop1234 suffix"
    rows[0][1] = sentinel
    hostile_bytes = json.dumps(
        rows,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    with pytest.raises(DeclaredBodylessPacketError) as projection:
        rederive_declared_bodyless_packet_projection(
            packet_bytes=hostile_bytes,
            frozen_static_schema_json=build_declared_bodyless_packet(
                observation=observation,
                expected_observation_sha256=observation.attempt.observation_sha256,
                expected_observation_record_sha256=observation.observation_record_sha256,
                packet_bytes=packet_bytes,
            ).frozen_static_schema_json,
        )
    assert sentinel not in str(projection.value)

    with pytest.raises(DeclaredBodylessPacketError) as caught:
        build_declared_bodyless_packet(
            observation=observation,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            packet_bytes=hostile_bytes,
        )
    assert sentinel not in str(caught.value)


def test_provider_build_rejects_known_secret_before_static_decoding_without_echo() -> None:
    observation, packet_bytes = _static_authority()
    sentinel = "Atlanta Hawks"
    assert sentinel.encode() in packet_bytes
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        build_declared_bodyless_packet(
            observation=observation,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            packet_bytes=packet_bytes,
            known_secrets=(sentinel,),
        )
    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None


def test_provider_decoder_exception_is_sanitized_without_context(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation, packet_bytes, _packet = admitted_packet

    def hostile_decoder(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("private-provider-decoder-detail")

    monkeypatch.setattr(packet_module, "decode_static_value_response", hostile_decoder)
    with pytest.raises(DeclaredBodylessPacketError) as caught:
        build_declared_bodyless_packet(
            observation=observation,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            packet_bytes=packet_bytes,
        )
    assert "private-provider-decoder-detail" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit])
def test_provider_decoder_base_exception_signals_propagate(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    observation, packet_bytes, _packet = admitted_packet

    def interrupted_decoder(*_args: object, **_kwargs: object) -> object:
        raise failure_type()

    monkeypatch.setattr(packet_module, "decode_static_value_response", interrupted_decoder)
    with pytest.raises(failure_type):
        build_declared_bodyless_packet(
            observation=observation,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            packet_bytes=packet_bytes,
        )


def test_preflight_enforces_exact_byte_and_structure_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = b"[0,0,0]"
    monkeypatch.setattr(packet_types_module, "MAX_DECLARED_BODYLESS_PACKET_BYTES", len(exact))
    assert decode_public_canonical_packet(exact) == [0, 0, 0]
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(exact + b" ")

    monkeypatch.setattr(packet_types_module, "MAX_DECLARED_BODYLESS_PACKET_BYTES", 1024)
    monkeypatch.setattr(packet_types_module, "MAX_DECLARED_BODYLESS_JSON_NODES", 3)
    assert decode_public_canonical_packet(b"[0,0]") == [0, 0]
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(b"[0,0,0]")


def test_depth_and_number_token_bounds_fail_before_unbounded_decode() -> None:
    too_deep = b"[" * 65 + b"0" + b"]" * 65
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(too_deep)
    huge_integer = b"[" + b"9" * 129 + b"]"
    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(huge_integer)


def test_exact_builtin_bytes_and_integer_types_are_required(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, packet_bytes, packet = admitted_packet

    class ForeignBytes(bytes):
        pass

    with pytest.raises(DeclaredBodylessPacketError):
        decode_public_canonical_packet(ForeignBytes(packet_bytes))
    with pytest.raises(DeclaredBodylessPacketError):
        replace(packet, row_count=True)
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_bytes(
            packet,
            packet_bytes=ForeignBytes(packet_bytes),
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )


def test_foreign_provider_observation_and_external_pins_fail_closed(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, packet_bytes, packet = admitted_packet
    foreign_observation, _ = _static_authority(provider_authority_sha256=_sha("foreign-provider"))
    with pytest.raises(DeclaredBodylessPacketError):
        build_declared_bodyless_packet(
            observation=foreign_observation,
            expected_observation_sha256=foreign_observation.attempt.observation_sha256,
            expected_observation_record_sha256=foreign_observation.observation_record_sha256,
            packet_bytes=packet_bytes,
        )


def test_external_pin_and_packet_bytes_fail_before_expensive_reconstruction(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation, packet_bytes, packet = admitted_packet

    def forbidden_replace(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("DTO reconstruction preceded external-root admission")

    monkeypatch.setattr(packet_types_module, "replace", forbidden_replace)
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_identity(
            packet,
            expected_packet_authority_sha256=_sha("foreign-packet-authority"),
        )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_bytes(
            packet,
            packet_bytes=b"[]",
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )

    class ForeignSecrets(tuple):
        pass

    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_bytes(
            packet,
            packet_bytes=packet_bytes,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            known_secrets=ForeignSecrets(),
        )
    monkeypatch.undo()

    def forbidden_projection(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("projection preceded cheap packet-byte admission")

    monkeypatch.setattr(
        packet_types_module,
        "rederive_declared_bodyless_packet_projection",
        forbidden_projection,
    )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_bytes(
            packet,
            packet_bytes=b"[]",
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_identity(
            packet,
            expected_packet_authority_sha256=_sha("foreign-packet-authority"),
        )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_bytes(
            packet,
            packet_bytes=packet_bytes,
            expected_observation_sha256=_sha("foreign-observation"),
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )


def test_fully_resealed_endpoint_relabel_cannot_cross_external_authority(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, packet_bytes, packet = admitted_packet
    payload = cast("dict[str, Any]", packet.to_row())
    payload.pop("packet_authority_sha256")
    payload["endpoint_id"] = "static_players"
    resealed = DeclaredBodylessPacketV1(
        **payload,
        packet_authority_sha256=_sha_json(payload),
    )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_bytes(
            resealed,
            packet_bytes=packet_bytes,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet(
            resealed,
            observation=observation,
            packet_bytes=packet_bytes,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=resealed.packet_authority_sha256,
        )


def test_object_setattr_tampering_and_foreign_type_fail_closed(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    _observation, _packet_bytes, packet = admitted_packet
    tampered = copy.copy(packet)
    object.__setattr__(tampered, "row_count", packet.row_count + 1)
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_identity(
            tampered,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )

    class EqualForeign:
        def __eq__(self, _other: object) -> bool:
            return True

    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_identity(
            EqualForeign(),
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )


def test_hostile_nested_attempt_is_rejected_before_method_execution(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, packet_bytes, _packet = admitted_packet

    class PoisonAttempt:
        def to_dict(self) -> object:
            raise AssertionError("hostile nested attempt executed")

    poisoned = observation.model_copy(update={"attempt": PoisonAttempt()})
    with pytest.raises(DeclaredBodylessPacketError):
        build_declared_bodyless_packet(
            observation=poisoned,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            packet_bytes=packet_bytes,
        )


def test_hostile_timestamp_timezone_is_rejected_before_method_execution(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, packet_bytes, _packet = admitted_packet

    class PoisonTimezone(tzinfo):
        def utcoffset(self, _value: datetime | None) -> timedelta:
            raise AssertionError("hostile timezone executed")

        def dst(self, _value: datetime | None) -> timedelta:
            return timedelta(0)

    hostile = datetime(2026, 8, 28, tzinfo=PoisonTimezone())
    for field_name in ("started_at", "finished_at"):
        poisoned = observation.model_copy(update={field_name: hostile})
        with pytest.raises(DeclaredBodylessPacketError):
            build_declared_bodyless_packet(
                observation=poisoned,
                expected_observation_sha256=observation.attempt.observation_sha256,
                expected_observation_record_sha256=observation.observation_record_sha256,
                packet_bytes=packet_bytes,
            )


def test_coordinated_root_reseal_cannot_bypass_byte_reconstruction(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, packet_bytes, packet = admitted_packet
    payload = cast("dict[str, Any]", packet.to_row())
    payload.pop("packet_authority_sha256")
    payload["content_root_sha256"] = _sha("fabricated-content-root")
    resealed = DeclaredBodylessPacketV1(
        **payload,
        packet_authority_sha256=_sha_json(payload),
    )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_bytes(
            resealed,
            packet_bytes=packet_bytes,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=resealed.packet_authority_sha256,
        )


def test_zero_row_packet_denominators_are_structurally_lossless(
    admitted_packet: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
) -> None:
    observation, _packet_bytes, packet = admitted_packet
    empty_bytes = b"[]"
    empty_sha = hashlib.sha256(empty_bytes).hexdigest()
    projection = rederive_declared_bodyless_packet_projection(
        packet_bytes=empty_bytes,
        frozen_static_schema_json=packet.frozen_static_schema_json,
    )
    payload = cast("dict[str, Any]", packet.to_row())
    payload.pop("packet_authority_sha256")
    payload.update(
        {
            "cell_count": 0,
            "cell_root_sha256": projection.cell_root_sha256,
            "content_root_sha256": projection.content_root_sha256,
            "public_resource_name": f"declared-static-packet-sha256-{empty_sha}.json",
            "row_count": 0,
            "row_root_sha256": projection.row_root_sha256,
            "stored_payload_length": len(empty_bytes),
            "stored_payload_sha256": empty_sha,
            "uncompressed_packet_length": len(empty_bytes),
            "uncompressed_packet_sha256": empty_sha,
        }
    )
    empty_packet = DeclaredBodylessPacketV1(
        **payload,
        packet_authority_sha256=_sha_json(payload),
    )
    assert (
        validate_declared_bodyless_packet_bytes(
            empty_packet,
            packet_bytes=empty_bytes,
            expected_observation_sha256=observation.attempt.observation_sha256,
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=empty_packet.packet_authority_sha256,
        ).row_count
        == 0
    )
