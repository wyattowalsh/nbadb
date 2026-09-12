from __future__ import annotations

import copy
import errno
import hashlib
import importlib
import json
import os
import stat
import threading
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import nbadb.contracts.declared_bodyless_packet as producer_module
import nbadb.contracts.declared_bodyless_packet_types as packet_module
import nbadb.orchestrate.declared_bodyless_packet_store as store_module
from nbadb.contracts.declared_bodyless_packet import (
    build_declared_bodyless_packet,
)
from nbadb.contracts.declared_bodyless_packet_types import (
    DeclaredBodylessPacketError,
    DeclaredBodylessPacketReadbackReceiptV1,
    DeclaredBodylessPacketV1,
    validate_declared_bodyless_packet_readback_receipt,
)
from nbadb.contracts.raw_request_authority import RequestAttemptIdentityV2, RequestObservationV2
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.nba_api_runtime_contract import pinned_static_dataset_contract
from nbadb.orchestrate.declared_bodyless_packet_store import (
    DeclaredBodylessPacketStore,
    DeclaredBodylessPacketStoreError,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sha_json(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")
    return hashlib.sha256(encoded).hexdigest()


def _authority() -> tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1]:
    contract = pinned_static_dataset_contract("static_teams")
    attempt = RequestAttemptIdentityV2.build(
        semantic_request_sha256=_sha("semantic-request"),
        logical_invocation_sha256=_sha("logical-invocation"),
        provider_call_role="primary",
        provider_call_ordinal=0,
        retry_ordinal=0,
        request_ordinal=0,
        source_family="static",
        endpoint_id="static_teams",
        parameters={},
        provider_authority_sha256=staging_route_contract_bundle().provider_authority_sha256,
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
        bodyless_evidence_sha256=_sha("opaque-bodyless-evidence"),
        result_occurrence_sha256s=[_sha("occurrence")],
        route_landing_sha256s=[_sha("landing")],
        capture_response_receipt_sha256=_sha("capture"),
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
    packet = build_declared_bodyless_packet(
        observation=observation,
        expected_observation_sha256=observation.attempt.observation_sha256,
        expected_observation_record_sha256=observation.observation_record_sha256,
        packet_bytes=packet_bytes,
    )
    return observation, packet_bytes, packet


def _store(root: Path) -> DeclaredBodylessPacketStore:
    return DeclaredBodylessPacketStore(
        root,
        source_sha="a" * 40,
        run_id=701,
        run_attempt=1,
        chain_id="chain-static",
        lane_id="lane-static",
    )


def _run_root(tmp_path: Path) -> Path:
    root = tmp_path / "declared-bodyless-run"
    root.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    return root


def _persist(
    store: DeclaredBodylessPacketStore,
    authority: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
    *,
    known_secrets: tuple[str | bytes, ...] = (),
) -> DeclaredBodylessPacketReadbackReceiptV1:
    observation, packet_bytes, packet = authority
    return store.persist(
        packet=packet,
        packet_bytes=packet_bytes,
        expected_observation_sha256=observation.attempt.observation_sha256,
        expected_observation_record_sha256=observation.observation_record_sha256,
        expected_packet_authority_sha256=packet.packet_authority_sha256,
        known_secrets=known_secrets,
    )


def _readback(
    store: DeclaredBodylessPacketStore,
    authority: tuple[RequestObservationV2, bytes, DeclaredBodylessPacketV1],
    receipt: DeclaredBodylessPacketReadbackReceiptV1,
    *,
    known_secrets: tuple[str | bytes, ...] = (),
) -> bytes:
    observation, packet_bytes, packet = authority
    return store.readback(
        receipt=receipt,
        packet=packet,
        packet_bytes=packet_bytes,
        expected_observation_sha256=observation.attempt.observation_sha256,
        expected_observation_record_sha256=observation.observation_record_sha256,
        expected_packet_authority_sha256=packet.packet_authority_sha256,
        expected_receipt_sha256=receipt.receipt_sha256,
        known_secrets=known_secrets,
    )


def _assert_sanitized_store_error(
    caught: pytest.ExceptionInfo[DeclaredBodylessPacketStoreError],
    *,
    message: str,
    sentinel: str,
) -> None:
    assert type(caught.value) is DeclaredBodylessPacketStoreError
    assert str(caught.value) == message
    assert caught.value.__cause__ is None
    assert sentinel not in "".join(traceback.format_exception(caught.value))


def test_atomic_persist_and_exact_path_free_readback(tmp_path: Path) -> None:
    authority = _authority()
    observation, packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)

    receipt = _persist(store, authority)
    assert receipt.observation_sha256 == observation.attempt.observation_sha256
    assert receipt.packet_authority_sha256 == packet.packet_authority_sha256
    assert receipt.public_resource_name == packet.public_resource_name
    assert receipt.readback_payload_sha256 == hashlib.sha256(packet_bytes).hexdigest()
    assert receipt.readback_payload_length == len(packet_bytes)
    assert receipt.field_count == packet.field_count
    assert receipt.schema_root_sha256 == packet.schema_root_sha256
    assert receipt.content_root_sha256 == packet.content_root_sha256
    assert receipt.row_root_sha256 == packet.row_root_sha256
    assert receipt.cell_root_sha256 == packet.cell_root_sha256
    assert _readback(store, authority, receipt) == packet_bytes
    assert (root / receipt.public_resource_name).read_bytes() == packet_bytes

    public = receipt.to_row()
    assert not any("path" in key for key in public)
    assert str(root) not in receipt.to_canonical_bytes().decode()
    assert receipt.public_resource_name.count("/") == 0


def test_known_secret_inventory_reaches_every_leaf_readback_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    store = _store(_run_root(tmp_path))
    known_secrets = ("known-but-absent-public-secret", b"known-absent-bytes-secret")

    original_build = DeclaredBodylessPacketReadbackReceiptV1.build
    observed_build_secrets: list[tuple[str | bytes, ...]] = []

    def recording_build(
        *,
        packet: DeclaredBodylessPacketV1,
        readback_bytes: bytes,
        store_namespace_sha256: str,
        expected_packet_authority_sha256: str,
        known_secrets: tuple[str | bytes, ...] = (),
    ) -> DeclaredBodylessPacketReadbackReceiptV1:
        observed_build_secrets.append(known_secrets)
        return original_build(
            packet=packet,
            readback_bytes=readback_bytes,
            store_namespace_sha256=store_namespace_sha256,
            expected_packet_authority_sha256=expected_packet_authority_sha256,
            known_secrets=known_secrets,
        )

    monkeypatch.setattr(DeclaredBodylessPacketReadbackReceiptV1, "build", recording_build)
    receipt = _persist(store, authority, known_secrets=known_secrets)
    assert _persist(store, authority, known_secrets=known_secrets) == receipt
    assert observed_build_secrets == [known_secrets, known_secrets]
    monkeypatch.undo()

    original_validate = validate_declared_bodyless_packet_readback_receipt
    observed_validation_secrets: list[tuple[str | bytes, ...]] = []

    def recording_validate(
        value: object,
        *,
        packet: DeclaredBodylessPacketV1,
        readback_bytes: bytes,
        store_namespace_sha256: str,
        expected_packet_authority_sha256: str,
        expected_receipt_sha256: str,
        known_secrets: tuple[str | bytes, ...] = (),
    ) -> DeclaredBodylessPacketReadbackReceiptV1:
        observed_validation_secrets.append(known_secrets)
        return original_validate(
            value,
            packet=packet,
            readback_bytes=readback_bytes,
            store_namespace_sha256=store_namespace_sha256,
            expected_packet_authority_sha256=expected_packet_authority_sha256,
            expected_receipt_sha256=expected_receipt_sha256,
            known_secrets=known_secrets,
        )

    monkeypatch.setattr(
        store_module,
        "validate_declared_bodyless_packet_readback_receipt",
        recording_validate,
    )
    assert _readback(store, authority, receipt, known_secrets=known_secrets) == authority[1]
    assert observed_validation_secrets == [known_secrets, known_secrets]


def test_receipt_canonical_roundtrip_uses_exact_resource_bytes(tmp_path: Path) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    store = _store(_run_root(tmp_path))
    receipt = _persist(store, authority)
    rebuilt = DeclaredBodylessPacketReadbackReceiptV1.from_canonical_bytes(
        receipt.to_canonical_bytes(),
        packet=packet,
        readback_bytes=packet_bytes,
        store_namespace_sha256=store.namespace_sha256,
        expected_packet_authority_sha256=packet.packet_authority_sha256,
        expected_receipt_sha256=receipt.receipt_sha256,
    )
    assert rebuilt.to_canonical_bytes() == receipt.to_canonical_bytes()


def test_receipt_canonical_decode_sanitizes_unexpected_field_cause(tmp_path: Path) -> None:
    _observation, packet_bytes, packet = authority = _authority()
    store = _store(_run_root(tmp_path))
    receipt = _persist(store, authority)
    payload = receipt.to_row()
    payload["attacker_controlled_field"] = "do-not-echo-unexpected-field"
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    with pytest.raises(DeclaredBodylessPacketError) as caught:
        DeclaredBodylessPacketReadbackReceiptV1.from_canonical_bytes(
            encoded,
            packet=packet,
            readback_bytes=packet_bytes,
            store_namespace_sha256=store.namespace_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
    assert "do-not-echo-unexpected-field" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_receipt_build_rejects_cheap_inputs_before_packet_reconstruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _observation, packet_bytes, packet = _authority()
    store = _store(_run_root(tmp_path))

    class ForeignBytes(bytes):
        pass

    def forbidden_replace(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("packet reconstruction preceded cheap receipt admission")

    monkeypatch.setattr(packet_module, "replace", forbidden_replace)
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketReadbackReceiptV1.build(
            packet=packet,
            readback_bytes=packet_bytes,
            store_namespace_sha256="not-a-sha",
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketReadbackReceiptV1.build(
            packet=packet,
            readback_bytes=ForeignBytes(packet_bytes),
            store_namespace_sha256=store.namespace_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )


def test_receipt_validation_rejects_external_pins_before_reconstruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    store = _store(_run_root(tmp_path))
    receipt = _persist(store, authority)

    def forbidden_replace(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("receipt reconstruction preceded external-pin admission")

    monkeypatch.setattr(packet_module, "replace", forbidden_replace)
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_readback_receipt(
            receipt,
            packet=packet,
            readback_bytes=packet_bytes,
            store_namespace_sha256="not-a-sha",
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )


def test_receipt_decode_rejects_store_pin_before_json_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    store = _store(_run_root(tmp_path))
    receipt = _persist(store, authority)

    def forbidden_decode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("JSON allocation preceded store-pin admission")

    monkeypatch.setattr(packet_module, "decode_public_canonical_packet", forbidden_decode)
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketReadbackReceiptV1.from_canonical_bytes(
            receipt.to_canonical_bytes(),
            packet=packet,
            readback_bytes=packet_bytes,
            store_namespace_sha256="not-a-sha",
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_readback_receipt(
            receipt,
            packet=packet,
            readback_bytes=packet_bytes,
            store_namespace_sha256=store.namespace_sha256,
            expected_packet_authority_sha256="not-a-sha",
            expected_receipt_sha256=receipt.receipt_sha256,
        )


def test_zero_row_packet_persists_without_synthesizing_cells(tmp_path: Path) -> None:
    observation, _packet_bytes, packet = _authority()
    empty_bytes = b"[]"
    empty_sha = hashlib.sha256(empty_bytes).hexdigest()
    projection = packet_module.rederive_declared_bodyless_packet_projection(
        packet_bytes=empty_bytes,
        frozen_static_schema_json=packet.frozen_static_schema_json,
    )
    payload = packet.to_row()
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
    store = _store(_run_root(tmp_path))
    receipt = store.persist(
        packet=empty_packet,
        packet_bytes=empty_bytes,
        expected_observation_sha256=observation.attempt.observation_sha256,
        expected_observation_record_sha256=observation.observation_record_sha256,
        expected_packet_authority_sha256=empty_packet.packet_authority_sha256,
    )
    assert receipt.row_count == 0
    assert receipt.cell_count == 0
    assert receipt.readback_payload_length == 2


def test_same_key_same_content_is_verified_noop_without_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    store = _store(_run_root(tmp_path))
    first = _persist(store, authority)

    def forbidden_link(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("verified replay must not republish immutable content")

    monkeypatch.setattr(store_module.os, "link", forbidden_link)
    second = _persist(store, authority)
    assert second.to_canonical_bytes() == first.to_canonical_bytes()


@pytest.mark.parametrize("mutation", ["truncated", "extra", "same-size-different"])
def test_corruption_and_same_key_different_content_fail_without_overwrite(
    tmp_path: Path,
    mutation: str,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    path = root / packet.public_resource_name
    changed = {
        "truncated": packet_bytes[:-1],
        "extra": packet_bytes + b"x",
        "same-size-different": b"x" + packet_bytes[1:],
    }[mutation]
    path.write_bytes(changed)
    path.chmod(0o600)
    with pytest.raises(DeclaredBodylessPacketStoreError):
        _persist(store, authority)
    assert path.read_bytes() == changed


def test_existing_packet_with_foreign_mode_fails_closed(tmp_path: Path) -> None:
    authority = _authority()
    _observation, _packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    _persist(store, authority)
    path = root / packet.public_resource_name
    path.chmod(0o644)

    with pytest.raises(DeclaredBodylessPacketStoreError):
        _persist(store, authority)

    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_symlink_and_fifo_packet_members_fail_closed(tmp_path: Path) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority

    symlink_root = _run_root(tmp_path / "symlink-case")
    target = symlink_root / "target.json"
    target.write_bytes(packet_bytes)
    (symlink_root / packet.public_resource_name).symlink_to(target)
    with pytest.raises(DeclaredBodylessPacketStoreError):
        _persist(_store(symlink_root), authority)
    assert target.read_bytes() == packet_bytes

    fifo_root = _run_root(tmp_path / "fifo-case")
    os.mkfifo(fifo_root / packet.public_resource_name, 0o600)
    with pytest.raises(DeclaredBodylessPacketStoreError):
        _persist(_store(fifo_root), authority)


def test_symlink_relative_world_readable_and_traversal_roots_fail_closed(tmp_path: Path) -> None:
    real = _run_root(tmp_path / "real-case")
    link = tmp_path / "root-link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(DeclaredBodylessPacketStoreError):
        _store(link)
    with pytest.raises(DeclaredBodylessPacketStoreError):
        _store(Path("relative-run-root"))

    open_root = _run_root(tmp_path / "mode-case")
    open_root.chmod(0o755)
    with pytest.raises(DeclaredBodylessPacketStoreError):
        _store(open_root)


def test_foreign_observation_and_run_namespace_fail_before_io(tmp_path: Path) -> None:
    authority = _authority()
    observation, packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    with pytest.raises(DeclaredBodylessPacketStoreError):
        store.persist(
            packet=packet,
            packet_bytes=packet_bytes,
            expected_observation_sha256=_sha("foreign-observation"),
            expected_observation_record_sha256=observation.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
        )
    assert not (root / packet.public_resource_name).exists()

    foreign_store = DeclaredBodylessPacketStore(
        root,
        source_sha="a" * 40,
        run_id=702,
        run_attempt=1,
        chain_id="chain-static",
        lane_id="lane-static",
    )
    with pytest.raises(DeclaredBodylessPacketStoreError):
        _persist(foreign_store, authority)


def test_frozen_packet_store_and_readback_do_not_reopen_runtime_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    store = _store(_run_root(tmp_path))

    def drifted_registry(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("frozen storage must not reopen runtime registry")

    monkeypatch.setattr(producer_module, "pinned_static_dataset_contract", drifted_registry)
    monkeypatch.setattr(producer_module, "pinned_request_surface_authority", drifted_registry)
    monkeypatch.setattr(producer_module, "staging_route_contract_bundle", drifted_registry)
    receipt = _persist(store, authority)
    assert _readback(store, authority, receipt) == authority[1]


@pytest.mark.parametrize(
    ("operation", "message"),
    (
        ("open", "declared bodyless store root cannot be opened safely"),
        ("stat", "declared bodyless store root cannot be opened safely"),
        ("fsync", "declared bodyless store lock cannot be initialized safely"),
    ),
)
def test_constructor_os_failures_have_fixed_cause_free_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    message: str,
) -> None:
    authority = _authority()
    _observation, _packet_bytes, packet = authority
    root = _run_root(tmp_path)
    sentinel = f"audit-private-{operation}-sentinel"

    def fail_operation(*_args: object, **_kwargs: object) -> object:
        raise OSError(errno.EIO, sentinel)

    monkeypatch.setattr(store_module, "_require_platform", lambda: None)
    monkeypatch.setattr(store_module.os, operation, fail_operation)
    with pytest.raises(DeclaredBodylessPacketStoreError) as caught:
        _store(root)
    _assert_sanitized_store_error(caught, message=message, sentinel=sentinel)
    monkeypatch.undo()
    assert not (root / packet.public_resource_name).exists()
    assert not list(root.glob("*.tmp"))


def test_lock_bootstrap_failure_has_no_os_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _run_root(tmp_path)
    original_open = store_module.os.open
    sentinel = "audit-private-lock-bootstrap-sentinel"

    def fail_lock_open(path: object, *args: object, **kwargs: object) -> int:
        if path == store_module._LOCK_NAME:
            raise FileNotFoundError(errno.ENOENT, sentinel, sentinel)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(store_module, "_require_platform", lambda: None)
    monkeypatch.setattr(store_module.os, "open", fail_lock_open)
    with pytest.raises(DeclaredBodylessPacketStoreError) as caught:
        _store(root)
    _assert_sanitized_store_error(
        caught,
        message="declared bodyless store lock bootstrap did not converge",
        sentinel=sentinel,
    )


def test_read_failure_has_fixed_cause_free_error_and_preserves_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    receipt = _persist(store, authority)
    sentinel = "audit-private-read-sentinel"

    def fail_read(*_args: object, **_kwargs: object) -> bytes:
        raise OSError(errno.EIO, sentinel)

    monkeypatch.setattr(store_module.os, "read", fail_read)
    with pytest.raises(DeclaredBodylessPacketStoreError) as caught:
        _readback(store, authority, receipt)
    _assert_sanitized_store_error(
        caught,
        message="declared bodyless packet cannot be read safely",
        sentinel=sentinel,
    )
    assert (root / packet.public_resource_name).read_bytes() == packet_bytes
    assert not list(root.glob("*.tmp"))


def test_close_failure_has_fixed_cause_free_error_and_preserves_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    receipt = _persist(store, authority)
    original_close = store_module.os.close
    sentinel = "audit-private-close-sentinel"

    def close_then_fail(descriptor: int) -> None:
        original_close(descriptor)
        raise OSError(errno.EIO, sentinel)

    monkeypatch.setattr(store_module.os, "close", close_then_fail)
    with pytest.raises(DeclaredBodylessPacketStoreError) as caught:
        _readback(store, authority, receipt)
    _assert_sanitized_store_error(
        caught,
        message="declared bodyless store root cannot be released safely",
        sentinel=sentinel,
    )
    assert (root / packet.public_resource_name).read_bytes() == packet_bytes
    assert not list(root.glob("*.tmp"))


def test_leaf_failure_translation_has_no_private_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    root = _run_root(tmp_path)
    store = _store(root)
    sentinel = "audit-private-leaf-sentinel"

    def fail_leaf(*_args: object, **_kwargs: object) -> object:
        raise DeclaredBodylessPacketError(sentinel)

    monkeypatch.setattr(store_module, "validate_declared_bodyless_packet_bytes", fail_leaf)
    with pytest.raises(DeclaredBodylessPacketStoreError) as caught:
        _persist(store, authority)
    _assert_sanitized_store_error(
        caught,
        message="declared bodyless packet failed exact authority validation",
        sentinel=sentinel,
    )


def test_write_enospc_and_baseexception_cleanup_leave_no_partial_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, _packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    original_write = store_module.os.write
    sentinel = "audit-private-write-sentinel"

    def no_space(_descriptor: int, _value: object) -> int:
        raise OSError(errno.ENOSPC, sentinel)

    monkeypatch.setattr(store_module.os, "write", no_space)
    with pytest.raises(DeclaredBodylessPacketStoreError) as caught:
        _persist(store, authority)
    _assert_sanitized_store_error(
        caught,
        message="declared bodyless packet cannot be installed durably",
        sentinel=sentinel,
    )
    assert not (root / packet.public_resource_name).exists()
    assert not list(root.glob("*.tmp"))

    def interrupted(_descriptor: int, _value: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(store_module.os, "write", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _persist(store, authority)
    assert not (root / packet.public_resource_name).exists()
    assert not list(root.glob("*.tmp"))

    monkeypatch.setattr(store_module.os, "write", original_write)
    assert _persist(store, authority).readback_payload_sha256 == packet.stored_payload_sha256


@pytest.mark.parametrize("failure_type", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_cleanup_close_fault_never_masks_active_baseexception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    authority = _authority()
    _observation, _packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    original_close = store_module.os.close
    signal_raised = False

    def interrupted(_descriptor: int, _value: object) -> int:
        nonlocal signal_raised
        signal_raised = True
        raise failure_type

    def close_then_fail(descriptor: int) -> None:
        original_close(descriptor)
        if signal_raised:
            raise OSError(errno.EIO, "audit-private-cleanup-sentinel")

    monkeypatch.setattr(store_module.os, "write", interrupted)
    monkeypatch.setattr(store_module.os, "close", close_then_fail)
    with pytest.raises(failure_type) as caught:
        _persist(store, authority)
    assert type(caught.value) is failure_type
    assert not (root / packet.public_resource_name).exists()
    assert not list(root.glob("*.tmp"))


def test_link_interruption_before_effect_preserves_absence_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, _packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    sentinel = "audit-private-link-sentinel"

    def interrupted_link(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOSPC, sentinel)

    monkeypatch.setattr(store_module.os, "link", interrupted_link)
    with pytest.raises(DeclaredBodylessPacketStoreError) as caught:
        _persist(store, authority)
    _assert_sanitized_store_error(
        caught,
        message="declared bodyless packet cannot be installed durably",
        sentinel=sentinel,
    )
    assert not (root / packet.public_resource_name).exists()
    assert not list(root.glob("*.tmp"))


def test_atomic_no_clobber_promotion_preserves_racing_foreign_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    original_link = store_module.os.link
    foreign_bytes = bytes([packet_bytes[0] ^ 1]) + packet_bytes[1:]

    def racing_link(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=dst_dir_fd,
        )
        try:
            os.write(descriptor, foreign_bytes)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(store_module.os, "link", racing_link)
    with pytest.raises(DeclaredBodylessPacketStoreError):
        _persist(store, authority)
    assert (root / packet.public_resource_name).read_bytes() == foreign_bytes
    assert not list(root.glob("*.tmp"))


def test_effect_before_raise_is_recoverable_as_verified_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    original_link = store_module.os.link

    def effect_then_raise(*args: object, **kwargs: object) -> None:
        original_link(*args, **kwargs)
        raise OSError(errno.EIO, "post-link interruption")

    monkeypatch.setattr(store_module.os, "link", effect_then_raise)
    with pytest.raises(DeclaredBodylessPacketStoreError):
        _persist(store, authority)
    assert (root / packet.public_resource_name).read_bytes() == packet_bytes
    assert not list(root.glob("*.tmp"))

    monkeypatch.setattr(store_module.os, "link", original_link)
    assert _persist(store, authority).stored_payload_sha256 == packet.stored_payload_sha256


def test_crash_between_link_and_temp_unlink_recovers_exact_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    original_unlink = store_module.os.unlink

    def fail_temporary_unlink(
        name: str,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if name.endswith(".tmp"):
            raise OSError(errno.EIO, "simulated process death before temporary unlink")
        original_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(store_module.os, "unlink", fail_temporary_unlink)
    with pytest.raises(DeclaredBodylessPacketStoreError):
        _persist(store, authority)
    temporary_members = list(root.glob("*.tmp"))
    installed = root / packet.public_resource_name
    assert len(temporary_members) == 1
    assert installed.read_bytes() == packet_bytes
    assert installed.stat().st_nlink == 2
    assert temporary_members[0].stat().st_nlink == 2

    monkeypatch.setattr(store_module.os, "unlink", original_unlink)
    original_fsync = store_module.os.fsync
    recovery_fsync_kinds: list[str] = []

    def record_recovery_fsync(descriptor: int) -> None:
        recovery_fsync_kinds.append(
            "directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file"
        )
        original_fsync(descriptor)

    monkeypatch.setattr(store_module.os, "fsync", record_recovery_fsync)
    receipt = _persist(store, authority)
    assert receipt.stored_payload_sha256 == packet.stored_payload_sha256
    assert "file" in recovery_fsync_kinds
    assert "directory" in recovery_fsync_kinds
    assert recovery_fsync_kinds.index("file") < recovery_fsync_kinds.index("directory")
    assert installed.stat().st_nlink == 1
    assert not list(root.glob("*.tmp"))


def test_directory_fsync_failure_after_link_preserves_recoverable_exact_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    root = _run_root(tmp_path)
    store = _store(root)
    original_fsync = store_module.os.fsync
    sentinel = "audit-private-fsync-sentinel"

    def fail_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(errno.ENOSPC, sentinel)
        original_fsync(descriptor)

    monkeypatch.setattr(store_module.os, "fsync", fail_directory_fsync)
    with pytest.raises(DeclaredBodylessPacketStoreError) as caught:
        _persist(store, authority)
    _assert_sanitized_store_error(
        caught,
        message="declared bodyless packet cannot be installed durably",
        sentinel=sentinel,
    )
    assert (root / packet.public_resource_name).read_bytes() == packet_bytes
    assert not list(root.glob("*.tmp"))

    recovery_fsync_kinds: list[str] = []

    def record_recovery_fsync(descriptor: int) -> None:
        recovery_fsync_kinds.append(
            "directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file"
        )
        original_fsync(descriptor)

    monkeypatch.setattr(store_module.os, "fsync", record_recovery_fsync)
    assert _persist(store, authority).stored_payload_sha256 == packet.stored_payload_sha256
    assert {"file", "directory"}.issubset(recovery_fsync_kinds)


def test_configured_root_rebind_before_promotion_fails_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    root = _run_root(tmp_path)
    displaced = root.with_name(f"{root.name}-displaced")
    store = _store(root)
    original_link = store_module.os.link

    def rebind_then_link(*args: object, **kwargs: object) -> None:
        root.rename(displaced)
        root.mkdir(mode=0o700)
        root.chmod(0o700)
        original_link(*args, **kwargs)

    monkeypatch.setattr(store_module.os, "link", rebind_then_link)
    with pytest.raises(DeclaredBodylessPacketStoreError, match="rebound"):
        _persist(store, authority)
    assert not (root / packet.public_resource_name).exists()
    assert (displaced / packet.public_resource_name).read_bytes() == packet_bytes


def test_receipt_tampering_wrong_pin_and_object_setattr_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _observation, packet_bytes, packet = authority
    store = _store(_run_root(tmp_path))
    receipt = _persist(store, authority)

    tampered = copy.copy(receipt)
    object.__setattr__(tampered, "row_count", receipt.row_count + 1)
    with pytest.raises(DeclaredBodylessPacketError):
        validate_declared_bodyless_packet_readback_receipt(
            tampered,
            packet=packet,
            readback_bytes=packet_bytes,
            store_namespace_sha256=store.namespace_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )

    def forbidden_tampered_read(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("file IO preceded complete receipt admission")

    monkeypatch.setattr(
        store_module.DeclaredBodylessPacketStore,
        "_read_bound_file",
        staticmethod(forbidden_tampered_read),
    )
    with pytest.raises(DeclaredBodylessPacketStoreError):
        store.readback(
            receipt=tampered,
            packet=packet,
            packet_bytes=packet_bytes,
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
    monkeypatch.undo()

    payload = receipt.to_row()
    payload.pop("receipt_sha256")
    payload["row_count"] = 0
    payload["cell_count"] = 1
    with pytest.raises(DeclaredBodylessPacketError):
        DeclaredBodylessPacketReadbackReceiptV1(
            **payload,
            receipt_sha256=_sha_json(payload),
        )

    def forbidden_read(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("file IO preceded receipt-root admission")

    monkeypatch.setattr(
        store_module.DeclaredBodylessPacketStore,
        "_read_bound_file",
        staticmethod(forbidden_read),
    )
    with pytest.raises(DeclaredBodylessPacketStoreError):
        store.readback(
            receipt=receipt,
            packet=packet,
            packet_bytes=packet_bytes,
            expected_observation_sha256=packet.observation_sha256,
            expected_observation_record_sha256=packet.observation_record_sha256,
            expected_packet_authority_sha256=packet.packet_authority_sha256,
            expected_receipt_sha256=_sha("foreign-receipt"),
        )


def test_two_store_instances_converge_on_one_immutable_resource(tmp_path: Path) -> None:
    authority = _authority()
    root = _run_root(tmp_path)
    stores = (_store(root), _store(root))
    receipts: list[DeclaredBodylessPacketReadbackReceiptV1] = []
    failures: list[BaseException] = []

    def run(store: DeclaredBodylessPacketStore) -> None:
        try:
            receipts.append(_persist(store, authority))
        except BaseException as exc:  # pragma: no cover - assertion reports exact failure
            failures.append(exc)

    for _round in range(20):
        threads = [threading.Thread(target=run, args=(store,)) for store in stores]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
    assert not failures
    assert len(receipts) == 40
    assert len({receipt.to_canonical_bytes() for receipt in receipts}) == 1
    assert len(list(root.glob("declared-static-packet-*.json"))) == 1
