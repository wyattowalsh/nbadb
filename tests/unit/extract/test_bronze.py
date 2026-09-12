from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

import nbadb.extract.bronze as bronze_module
from nbadb.core.errors import ExtractionError
from nbadb.extract.bronze import (
    PARSER_INPUT_REPRESENTATION,
    STATIC_INPUT_REPRESENTATION,
    BronzeCaptureStore,
    BronzeLimits,
    LogicalCallReceiptBinding,
    ParserInputCapacityError,
    ParserInputContext,
    ResultSetReceipt,
    canonical_parameters_payload,
    canonical_parameters_sha256,
    parent_occurrence_states_digest,
)

if TYPE_CHECKING:
    from pathlib import Path

_WORKFLOW_RUN_ID = 123456789
_WORKFLOW_RUN_ATTEMPT = 1


def _store(
    tmp_path: Path,
    *,
    max_response_bytes: int = 100_000,
    max_generation_stored_bytes: int = 1_000_000,
    max_receipt_count: int = 1_000_000,
    max_checkpoint_bytes: int | None = None,
    minimum_deadline_headroom_seconds: float | None = None,
) -> BronzeCaptureStore:
    return BronzeCaptureStore(
        tmp_path / "private" / "bronze-inputs",
        public_roots=(tmp_path / "data" / "nbadb",),
        limits=BronzeLimits(
            max_response_bytes=max_response_bytes,
            max_generation_stored_bytes=max_generation_stored_bytes,
            minimum_free_bytes=1,
            max_receipt_count=max_receipt_count,
            max_checkpoint_bytes=max_checkpoint_bytes,
            minimum_deadline_headroom_seconds=minimum_deadline_headroom_seconds,
        ),
    )


def _descriptor_store(tmp_path: Path) -> tuple[BronzeCaptureStore, Path, Path]:
    base = (tmp_path / "authorized-private").resolve()
    base.mkdir(mode=0o700, parents=True)
    observed = base.stat()
    generation = base / "generation"
    store = BronzeCaptureStore.create_under_authorized_parent(
        base,
        generation.name,
        expected_parent_identity=(observed.st_dev, observed.st_ino),
        public_roots=((tmp_path / "data" / "nbadb").resolve(),),
        limits=BronzeLimits(
            max_response_bytes=100_000,
            max_generation_stored_bytes=1_000_000,
            minimum_free_bytes=1,
            max_receipt_count=1_000_000,
        ),
    )
    return store, base, generation


def test_descriptor_writer_rejects_foreign_base_before_generation_creation(
    tmp_path: Path,
) -> None:
    base = (tmp_path / "authorized-private").resolve()
    base.mkdir(mode=0o700, parents=True)
    observed = base.stat()

    with pytest.raises(ExtractionError, match="parent root authority"):
        BronzeCaptureStore.create_under_authorized_parent(
            base,
            "generation",
            expected_parent_identity=(observed.st_dev, observed.st_ino + 1),
            public_roots=((tmp_path / "data" / "nbadb").resolve(),),
            limits=BronzeLimits(
                max_response_bytes=100_000,
                max_generation_stored_bytes=1_000_000,
                minimum_free_bytes=1,
            ),
        )

    assert list(base.iterdir()) == []


def test_descriptor_writer_rejects_base_substitution_without_writing_replacement(
    tmp_path: Path,
) -> None:
    base = (tmp_path / "authorized-private").resolve()
    base.mkdir(mode=0o700, parents=True)
    observed = base.stat()
    retained = base.with_name("authorized-private-retained")
    base.rename(retained)
    base.mkdir(mode=0o700)

    with pytest.raises(ExtractionError, match="parent root authority"):
        BronzeCaptureStore.create_under_authorized_parent(
            base,
            "generation",
            expected_parent_identity=(observed.st_dev, observed.st_ino),
            public_roots=((tmp_path / "data" / "nbadb").resolve(),),
            limits=BronzeLimits(
                max_response_bytes=100_000,
                max_generation_stored_bytes=1_000_000,
                minimum_free_bytes=1,
            ),
        )

    assert list(base.iterdir()) == []
    assert list(retained.iterdir()) == []


def test_descriptor_writer_pins_generation_after_path_substitution(tmp_path: Path) -> None:
    store, _base, generation = _descriptor_store(tmp_path)
    retained = generation.with_name("generation-retained")
    generation.rename(retained)
    generation.mkdir(mode=0o700)
    try:
        captured = store.store_parser_input(
            '{"resultSets":[]}',
            representation=PARSER_INPUT_REPRESENTATION,
        )
        assert captured.stored_bytes > 0
    finally:
        store.close()

    assert list(generation.iterdir()) == []
    assert (retained / ".capture.lock").is_file()
    assert any(path.is_file() for path in (retained / "blobs").rglob("*"))


def test_descriptor_writer_path_substitution_during_publication_never_writes_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _base, generation = _descriptor_store(tmp_path)
    retained = generation.with_name("generation-retained")
    original_link = bronze_module.os.link
    substituted = False

    def substitute_link(*args: object, **kwargs: object) -> None:
        nonlocal substituted
        if not substituted:
            generation.rename(retained)
            generation.mkdir(mode=0o700)
            substituted = True
        original_link(*args, **kwargs)

    monkeypatch.setattr(bronze_module.os, "link", substitute_link)
    try:
        captured = store.store_parser_input(
            '{"resultSets":[]}',
            representation=PARSER_INPUT_REPRESENTATION,
        )
        assert captured.stored_bytes > 0
    finally:
        store.close()

    assert substituted is True
    assert list(generation.iterdir()) == []
    assert any(path.is_file() for path in (retained / "blobs").rglob("*"))


def _response_receipt(
    store: BronzeCaptureStore,
    payload: str,
    *,
    context: ParserInputContext | None = None,
) -> tuple[str, bytes]:
    response_context = context or ParserInputContext(attempt_id="attempt-1")
    captured = store.store_parser_input(
        payload,
        representation=PARSER_INPUT_REPRESENTATION,
    )
    receipt = store.record_response_attempt(
        context=response_context,
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="LeagueGameLog",
        endpoint_slug="leaguegamelog",
        parameters={"LeagueID": "00", "Season": "2024-25"},
        provider_authority_sha256="a" * 64,
        contract_sha256="b" * 64,
        status_code=200,
        captured=captured,
        outcome="success_nonempty",
        failure_class=None,
        root_exception_class=None,
        result_sets=(
            ResultSetReceipt(
                name="LeagueGameLog",
                provider_index=0,
                canonical_index=0,
                headers_sha256="c" * 64,
                row_count=1,
                json_path=None,
                container_kind="nba_api_result_set",
                container_count=1,
                missing_count=0,
                null_count=0,
                parent_observation_count=1,
                parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
                observed_field_orders_sha256="d" * 64,
                normalized_output_sha256="e" * 64,
            ),
        ),
    )
    return receipt, payload.encode()


def test_private_bronze_is_deterministic_deduplicated_and_replayable(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    payload = '{"resultSets":[{"name":"LeagueGameLog","headers":["ID"],"rowSet":[[1]]}]}'

    first_receipt, expected = _response_receipt(store, payload)
    second_receipt, _ = _response_receipt(store, payload)

    assert first_receipt == second_receipt
    assert store.replay_parser_input(first_receipt) == expected
    assert len(list((store.root / "blobs").rglob("*.payload.gz"))) == 1
    assert len(list((store.root / "receipts" / "attempts").rglob("*.json"))) == 1

    first_manifest = store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    second_manifest = store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    assert first_manifest == second_manifest
    assert first_manifest["artifact_count"] == 2
    assert first_manifest["workflow_run_id"] == _WORKFLOW_RUN_ID
    assert first_manifest["workflow_run_attempt"] == _WORKFLOW_RUN_ATTEMPT

    root = store.root
    store.close()
    reopened = BronzeCaptureStore(
        root,
        public_roots=(tmp_path / "data" / "nbadb",),
        limits=BronzeLimits(100_000, 1_000_000, 1),
    )
    assert (
        reopened.write_manifest(
            provider_authority_sha256="a" * 64,
            semantic_source_sha=None,
            chain_id=None,
            lane_id=None,
            workflow_run_id=_WORKFLOW_RUN_ID,
            workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
            done_call_receipt_sha256s=(),
        )
        == first_manifest
    )


def test_load_sealed_manifest_returns_none_then_fresh_detached_mapping(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    assert store.load_sealed_manifest() is None
    _response_receipt(store, "{}")
    manifest = store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )

    loaded = store.load_sealed_manifest()
    assert loaded == manifest
    assert loaded is not manifest
    assert loaded is not None
    loaded["artifacts"].clear()
    loaded["done_attempt_receipt_sha256s"].clear()

    assert store.load_sealed_manifest() == manifest
    store.close()


def test_open_existing_pins_manifest_receipt_blob_and_inventory_across_root_swap(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    receipt, expected_parser_input = _response_receipt(store, '{"stable":true}')
    manifest = store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    root = store.root
    store.close()
    expected_root_identity = (root.stat().st_dev, root.stat().st_ino)
    sibling = tmp_path / "valid-path-sibling"
    shutil.copytree(root, sibling)
    (sibling / "manifest.json").write_bytes((sibling / "manifest.json").read_bytes() + b"\n")

    opened = BronzeCaptureStore.open_existing(
        root,
        limits=BronzeLimits(100_000, 1_000_000, 1),
        public_roots=(tmp_path / "data" / "nbadb",),
        expected_root_identity=expected_root_identity,
    )
    retained = tmp_path / "retained-authorized-root"
    root.rename(retained)
    sibling.rename(root)
    try:
        assert opened.load_sealed_manifest() == manifest
        assert opened.load_recorded_attempt(receipt).parser_input == expected_parser_input
        assert opened.load_generation_contexts() == (ParserInputContext(attempt_id="attempt-1"),)
    finally:
        opened.close()
        root.rename(sibling)
        retained.rename(root)


def test_open_existing_rejects_preopen_sibling_swap_even_when_swapped_back(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _response_receipt(store, "{}")
    store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    root = store.root
    store.close()
    expected_root_identity = (root.stat().st_dev, root.stat().st_ino)
    sibling = tmp_path / "valid-preopen-sibling"
    shutil.copytree(root, sibling)
    retained = tmp_path / "preopen-authorized-root"
    root.rename(retained)
    sibling.rename(root)
    try:
        with pytest.raises(ExtractionError, match="changed identity before open"):
            BronzeCaptureStore.open_existing(
                root,
                limits=BronzeLimits(100_000, 1_000_000, 1),
                public_roots=(tmp_path / "data" / "nbadb",),
                expected_root_identity=expected_root_identity,
            )
    finally:
        root.rename(sibling)
        retained.rename(root)


def test_open_existing_never_creates_a_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "missing-retained-root"
    with pytest.raises(ExtractionError, match="root is unavailable"):
        BronzeCaptureStore.open_existing(
            missing,
            limits=BronzeLimits(100_000, 1_000_000, 1),
            public_roots=(tmp_path / "data" / "nbadb",),
            expected_root_identity=(1, 1),
        )
    assert not missing.exists()


@pytest.mark.parametrize(
    "expected_root_identity",
    [
        (True, 1),
        (1, True),
        (-1, 1),
        (1, -1),
        (1, 0),
    ],
)
def test_open_existing_rejects_invalid_root_identity(
    tmp_path: Path,
    expected_root_identity: tuple[int, int],
) -> None:
    with pytest.raises(ValueError, match="expected_root_identity"):
        BronzeCaptureStore.open_existing(
            tmp_path / "irrelevant",
            limits=BronzeLimits(100_000, 1_000_000, 1),
            public_roots=(tmp_path / "data" / "nbadb",),
            expected_root_identity=expected_root_identity,
        )


@pytest.mark.parametrize("aliased_control", [".capture.lock", "manifest.json"])
def test_open_existing_rejects_aliased_sealed_controls(
    tmp_path: Path,
    aliased_control: str,
) -> None:
    store = _store(tmp_path)
    store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    root = store.root
    store.close()
    os.link(root / aliased_control, tmp_path / f"alias-{aliased_control.lstrip('.')}")
    expected_root_identity = (root.stat().st_dev, root.stat().st_ino)
    with pytest.raises(ExtractionError, match="aliased"):
        BronzeCaptureStore.open_existing(
            root,
            limits=BronzeLimits(100_000, 1_000_000, 1),
            public_roots=(tmp_path / "data" / "nbadb",),
            expected_root_identity=expected_root_identity,
        )


@pytest.mark.parametrize("missing_control", [".capture.lock", "manifest.json"])
def test_open_existing_does_not_recreate_missing_sealed_controls(
    tmp_path: Path,
    missing_control: str,
) -> None:
    store = _store(tmp_path)
    store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    root = store.root
    store.close()
    control = root / missing_control
    control.unlink()
    expected_root_identity = (root.stat().st_dev, root.stat().st_ino)
    with pytest.raises(ExtractionError):
        BronzeCaptureStore.open_existing(
            root,
            limits=BronzeLimits(100_000, 1_000_000, 1),
            public_roots=(tmp_path / "data" / "nbadb",),
            expected_root_identity=expected_root_identity,
        )
    assert not control.exists()


def test_open_existing_rejects_nested_directory_swap_and_swap_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _response_receipt(store, "{}")
    store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    root = store.root
    store.close()
    expected_root_identity = (root.stat().st_dev, root.stat().st_ino)
    attempts = root / "receipts" / "attempts"
    alternate = tmp_path / "alternate-attempts"
    retained = tmp_path / "retained-attempts"
    shutil.copytree(attempts, alternate)
    original_hash = bronze_module._hash_regular_descriptor
    raced = False

    def swap_during_hash(descriptor: int, *, display_path: str) -> tuple[int, str]:
        nonlocal raced
        observed = original_hash(descriptor, display_path=display_path)
        if not raced and display_path.startswith("receipts/attempts/"):
            raced = True
            attempts.rename(retained)
            alternate.rename(attempts)
            attempts.rename(alternate)
            retained.rename(attempts)
            os.chmod(attempts, 0o755)
            os.chmod(attempts, 0o700)
        return observed

    monkeypatch.setattr(bronze_module, "_hash_regular_descriptor", swap_during_hash)
    with pytest.raises(ExtractionError, match="directory changed while inventorying"):
        BronzeCaptureStore.open_existing(
            root,
            limits=BronzeLimits(100_000, 1_000_000, 1),
            public_roots=(tmp_path / "data" / "nbadb",),
            expected_root_identity=expected_root_identity,
        )
    assert raced is True


@pytest.mark.parametrize("target", ["manifest", "receipt"])
def test_load_sealed_manifest_freshly_rejects_post_open_tampering(
    tmp_path: Path,
    target: str,
) -> None:
    store = _store(tmp_path)
    _response_receipt(store, "{}")
    store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    path = (
        store.root / "manifest.json"
        if target == "manifest"
        else next((store.root / "receipts" / "attempts").rglob("*.json"))
    )
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ExtractionError):
        store.load_sealed_manifest()
    store.close()


def test_manifest_rejects_foreign_provider_orphan_attempt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    captured = store.store_parser_input(
        "{}",
        representation=PARSER_INPUT_REPRESENTATION,
    )
    store.record_response_attempt(
        context=ParserInputContext(attempt_id="attempt-1"),
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="LeagueGameLog",
        endpoint_slug="leaguegamelog",
        parameters={"season": "2025-26"},
        provider_authority_sha256="f" * 64,
        contract_sha256="b" * 64,
        status_code=200,
        captured=captured,
        outcome="success_empty",
        failure_class=None,
        root_exception_class=None,
        result_sets=(
            ResultSetReceipt(
                name="LeagueGameLog",
                provider_index=0,
                canonical_index=0,
                headers_sha256="c" * 64,
                row_count=0,
                json_path=None,
                container_kind="nba_api_result_set",
                container_count=1,
                missing_count=0,
                null_count=0,
                parent_observation_count=1,
                parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
                observed_field_orders_sha256="d" * 64,
                normalized_output_sha256="e" * 64,
            ),
        ),
    )

    with pytest.raises(ExtractionError, match="provider-authority drift"):
        store.write_manifest(
            provider_authority_sha256="a" * 64,
            semantic_source_sha=None,
            chain_id=None,
            lane_id=None,
            workflow_run_id=_WORKFLOW_RUN_ID,
            workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
            done_call_receipt_sha256s=(),
        )
    assert not (store.root / "manifest.json").exists()
    store.close()


def test_recorded_attempt_loads_verified_receipt_and_blob_metadata(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt, expected = _response_receipt(store, "{}")

    recorded = store.load_recorded_attempt(receipt)

    assert recorded.receipt_sha256 == receipt
    assert recorded.source_family == "stats"
    assert recorded.endpoint_id == "LeagueGameLog"
    assert recorded.endpoint_slug == "leaguegamelog"
    assert recorded.provider_authority_sha256 == "a" * 64
    assert recorded.endpoint_contract_sha256 == "b" * 64
    assert recorded.parser_input == expected
    assert recorded.result_sets[0].name == "LeagueGameLog"


def test_stats_fallback_receipt_preserves_duplicate_occurrences_and_missing_sets(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    captured = store.store_parser_input(
        '{"resultSets":[{"name":"Stats"},{"name":"Stats"}]}',
        representation=PARSER_INPUT_REPRESENTATION,
    )

    def _present(provider_index: int, digest: str) -> ResultSetReceipt:
        return ResultSetReceipt(
            name="Stats",
            provider_index=provider_index,
            canonical_index=None,
            headers_sha256="c" * 64,
            row_count=1,
            json_path=None,
            container_kind="nba_api_result_set",
            container_count=1,
            missing_count=0,
            null_count=0,
            parent_observation_count=1,
            parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
            observed_field_orders_sha256="d" * 64,
            normalized_output_sha256=digest,
        )

    missing = ResultSetReceipt(
        name="Removed",
        provider_index=None,
        canonical_index=None,
        headers_sha256="c" * 64,
        row_count=0,
        json_path=None,
        container_kind="nba_api_result_set",
        container_count=0,
        missing_count=1,
        null_count=0,
        parent_observation_count=1,
        parent_occurrence_states_sha256=parent_occurrence_states_digest(("missing",)),
        observed_field_orders_sha256="d" * 64,
        normalized_output_sha256="e" * 64,
    )
    result_sets = (_present(0, "e" * 64), _present(1, "f" * 64), missing)
    receipt = store.record_response_attempt(
        context=ParserInputContext(attempt_id="fallback-1"),
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="FixtureEndpoint",
        endpoint_slug="fixtureendpoint",
        parameters={"ItemID": 1},
        provider_authority_sha256="a" * 64,
        contract_sha256="b" * 64,
        status_code=200,
        captured=captured,
        outcome="success_nonempty",
        failure_class=None,
        root_exception_class=None,
        result_sets=result_sets,
    )

    recorded = store.load_recorded_attempt(receipt)
    assert recorded.result_sets == result_sets
    assert [item.name for item in recorded.result_sets] == ["Stats", "Stats", "Removed"]
    assert [item.provider_index for item in recorded.result_sets] == [0, 1, None]

    with pytest.raises(ValueError, match="provider occurrences before missing"):
        store.record_response_attempt(
            context=ParserInputContext(attempt_id="fallback-2"),
            transport_kind="http_response",
            source_family="stats",
            endpoint_id="FixtureEndpoint",
            endpoint_slug="fixtureendpoint",
            parameters={"ItemID": 2},
            provider_authority_sha256="a" * 64,
            contract_sha256="b" * 64,
            status_code=200,
            captured=captured,
            outcome="success_nonempty",
            failure_class=None,
            root_exception_class=None,
            result_sets=(missing, _present(0, "e" * 64)),
        )


def test_recorded_attempt_rejects_noncanonical_receipt_bytes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt, _expected = _response_receipt(store, "{}")
    receipt_path = next((store.root / "receipts" / "attempts").rglob(f"{receipt}.json"))
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    noncanonical = json.dumps(payload, indent=2).encode()
    tampered_digest = hashlib.sha256(noncanonical).hexdigest()
    tampered_path = (
        store.root / "receipts" / "attempts" / tampered_digest[:2] / f"{tampered_digest}.json"
    )
    tampered_path.parent.mkdir(parents=True)
    tampered_path.write_bytes(noncanonical)

    with pytest.raises(ExtractionError, match="not canonical JSON"):
        store.load_recorded_attempt(tampered_digest)


def test_capture_admission_accepts_exact_checkpoint_and_headroom_boundaries(
    tmp_path: Path,
) -> None:
    store = _store(
        tmp_path,
        max_checkpoint_bytes=1_024,
        minimum_deadline_headroom_seconds=30.0,
    )

    store.admit_capture(
        estimated_checkpoint_bytes=1_024,
        monotonic_now_seconds=100.0,
        monotonic_deadline_seconds=130.0,
    )


@pytest.mark.parametrize(
    ("checkpoint_bytes", "deadline", "match"),
    [
        (1_025, 130.0, "checkpoint byte limit"),
        (1_024, 129.999, "deadline headroom"),
    ],
)
def test_capture_admission_rejects_just_over_capacity_or_under_headroom(
    tmp_path: Path,
    checkpoint_bytes: int,
    deadline: float,
    match: str,
) -> None:
    store = _store(
        tmp_path,
        max_checkpoint_bytes=1_024,
        minimum_deadline_headroom_seconds=30.0,
    )

    with pytest.raises(ParserInputCapacityError, match=match):
        store.admit_capture(
            estimated_checkpoint_bytes=checkpoint_bytes,
            monotonic_now_seconds=100.0,
            monotonic_deadline_seconds=deadline,
        )


def test_capture_admission_requires_explicit_limits_and_positive_measurements(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must be configured together"):
        BronzeLimits(
            max_response_bytes=1,
            max_generation_stored_bytes=1,
            minimum_free_bytes=1,
            max_checkpoint_bytes=1,
        )

    store = _store(tmp_path)
    with pytest.raises(ParserInputCapacityError, match="not configured"):
        store.admit_capture(
            estimated_checkpoint_bytes=1,
            monotonic_now_seconds=1.0,
            monotonic_deadline_seconds=2.0,
        )

    configured = _store(
        tmp_path / "configured",
        max_checkpoint_bytes=1,
        minimum_deadline_headroom_seconds=1.0,
    )
    with pytest.raises(ValueError, match="estimated_checkpoint_bytes"):
        configured.admit_capture(
            estimated_checkpoint_bytes=0,
            monotonic_now_seconds=1.0,
            monotonic_deadline_seconds=2.0,
        )
    with pytest.raises(ValueError, match="monotonic_now_seconds"):
        configured.admit_capture(
            estimated_checkpoint_bytes=1,
            monotonic_now_seconds=float("nan"),
            monotonic_deadline_seconds=2.0,
        )


def test_capture_admission_reserves_checkpoint_bytes_before_free_space_floor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = _store(
        tmp_path,
        max_checkpoint_bytes=1_024,
        minimum_deadline_headroom_seconds=1.0,
    )
    monkeypatch.setattr(
        "nbadb.extract.bronze.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=1_024),
    )

    with pytest.raises(ParserInputCapacityError, match="checkpoint free-space reserve"):
        store.admit_capture(
            estimated_checkpoint_bytes=1_024,
            monotonic_now_seconds=1.0,
            monotonic_deadline_seconds=2.0,
        )


def test_attempt_receipt_persists_only_parameter_digest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt, _expected = _response_receipt(store, "{}")
    path = next((store.root / "receipts" / "attempts").rglob(f"{receipt}.json"))
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)

    assert "2024-25" not in raw
    assert "LeagueID" not in raw
    assert parsed["parameters_sha256"] == canonical_parameters_sha256(
        {"LeagueID": "00", "Season": "2024-25"}
    )
    assert "message" not in raw.lower()
    assert "header" in raw.lower()  # only the bounded result header digest key


def test_secret_like_parameter_keys_fail_before_receipt_write(tmp_path: Path) -> None:
    store = _store(tmp_path)
    captured = store.store_parser_input("{}", representation=PARSER_INPUT_REPRESENTATION)

    with pytest.raises(ValueError, match="forbidden key"):
        store.record_response_attempt(
            context=ParserInputContext(attempt_id="attempt-1"),
            transport_kind="http_response",
            source_family="stats",
            endpoint_id="Fixture",
            endpoint_slug="fixture",
            parameters={"authorization_token": "do-not-store"},
            provider_authority_sha256="a" * 64,
            contract_sha256="b" * 64,
            status_code=403,
            captured=captured,
            outcome="http_application_error",
            failure_class="application",
            root_exception_class="UpstreamHttpError",
            result_sets=(),
        )

    assert not list((store.root / "receipts").rglob("*.json"))
    manifest = store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    assert manifest["orphan_blob_object_sha256s"] == [captured.object_sha256]


def test_no_response_attempt_has_no_parser_input(tmp_path: Path) -> None:
    store = _store(tmp_path)
    digest = store.record_no_response_attempt(
        context=ParserInputContext(attempt_id="attempt-2", retry_ordinal=1),
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="Fixture",
        endpoint_slug="fixture",
        parameters={"Season": "2024-25"},
        provider_authority_sha256="a" * 64,
        contract_sha256="b" * 64,
        outcome="transport_failure_no_response",
        failure_class="transport_transient",
        root_exception_class="Timeout",
    )
    path = next((store.root / "receipts" / "attempts").rglob(f"{digest}.json"))
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert receipt["status_code"] is None
    assert receipt["parser_input"] is None
    with pytest.raises(ExtractionError, match="no replayable"):
        store.replay_parser_input(digest)


def test_response_limit_fails_without_truncation(tmp_path: Path) -> None:
    store = _store(tmp_path, max_response_bytes=4)

    with pytest.raises(ParserInputCapacityError, match="per-response"):
        store.store_parser_input("12345", representation=PARSER_INPUT_REPRESENTATION)

    assert not list((store.root / "blobs").rglob("*payload*"))


def test_replay_rejects_corrupt_stored_object(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt, _expected = _response_receipt(store, "{}")
    blob = next((store.root / "blobs").rglob("*.payload.gz"))
    blob.write_bytes(b"corrupt")

    with pytest.raises(ExtractionError, match="stored parser-input digest"):
        store.replay_parser_input(receipt)


def test_private_root_below_public_data_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be disjoint"):
        BronzeCaptureStore(
            tmp_path / "data" / "nbadb" / "private" / "bronze-inputs",
            public_roots=(tmp_path / "data" / "nbadb",),
            limits=BronzeLimits(
                max_response_bytes=1,
                max_generation_stored_bytes=1,
                minimum_free_bytes=1,
            ),
        )


def test_public_data_root_below_private_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be disjoint"):
        BronzeCaptureStore(
            tmp_path / "private",
            public_roots=(tmp_path / "private" / "data" / "nbadb",),
            limits=BronzeLimits(
                max_response_bytes=1,
                max_generation_stored_bytes=1,
                minimum_free_bytes=1,
            ),
        )


def test_similarly_named_private_sibling_is_not_rejected(tmp_path: Path) -> None:
    store = BronzeCaptureStore(
        tmp_path / "private" / "data" / "nbadb",
        public_roots=(tmp_path / "data" / "nbadb",),
        limits=BronzeLimits(
            max_response_bytes=1,
            max_generation_stored_bytes=10_000,
            minimum_free_bytes=1,
        ),
    )

    assert store.root == (tmp_path / "private" / "data" / "nbadb").resolve()


def test_context_accepts_real_shaped_git_source_sha() -> None:
    context = ParserInputContext(
        attempt_id="attempt-1",
        semantic_source_sha="6f871119f969000a42932f6a03848ab7f6d7b061",
    )

    assert context.semantic_source_sha == "6f871119f969000a42932f6a03848ab7f6d7b061"


def test_logical_call_dereferences_attempts_and_seals_done_graph(tmp_path: Path) -> None:
    store = _store(tmp_path)
    context = ParserInputContext(
        attempt_id="attempt-1",
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
    )
    response_receipt, _expected = _response_receipt(store, "{}", context=context)
    call_receipt = store.record_logical_call(
        context=context,
        logical_endpoint_id="league_game_log",
        logical_parameters={"league_id": "00", "season": "2024-25"},
        provider_authority_sha256="a" * 64,
        response_receipt_sha256s=(response_receipt,),
        successful_response_ordinals=(0,),
        result_route_ids=("stg_league_game_log",),
    )

    with pytest.raises(ExtractionError, match="generation-execution drift"):
        store.build_manifest(
            provider_authority_sha256="a" * 64,
            semantic_source_sha=None,
            chain_id=None,
            lane_id=None,
            workflow_run_id=_WORKFLOW_RUN_ID,
            workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT + 1,
            done_call_receipt_sha256s=(call_receipt,),
        )

    manifest = store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(call_receipt,),
    )

    assert manifest["done_call_receipt_sha256s"] == [call_receipt]
    expected_binding_payloads = [
        {
            "endpoint_name": "league_game_log",
            "logical_call_receipt_sha256": call_receipt,
            "logical_parameters_sha256": canonical_parameters_sha256(
                {"league_id": "00", "season": "2024-25"}
            ),
            "provider_authority_sha256": "a" * 64,
            "result_route_ids": ["stg_league_game_log"],
        }
    ]
    assert manifest["done_call_bindings"] == expected_binding_payloads
    assert (
        manifest["done_call_bindings_sha256"]
        == hashlib.sha256(
            json.dumps(
                expected_binding_payloads,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )
    assert manifest["done_attempt_receipt_sha256s"] == [response_receipt]
    assert manifest["orphan_attempt_receipt_sha256s"] == []
    assert manifest["workflow_run_id"] == _WORKFLOW_RUN_ID
    assert manifest["workflow_run_attempt"] == _WORKFLOW_RUN_ATTEMPT
    with pytest.raises(ExtractionError, match="sealed"):
        store.store_parser_input("{}", representation=PARSER_INPUT_REPRESENTATION)


def test_sealed_manifest_rederives_done_call_bindings_on_reopen(tmp_path: Path) -> None:
    store = _store(tmp_path)
    context = ParserInputContext(
        attempt_id="attempt-1",
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
    )
    response_receipt, _expected = _response_receipt(store, "{}", context=context)
    call_receipt = store.record_logical_call(
        context=context,
        logical_endpoint_id="league_game_log",
        logical_parameters={"season": "2024-25"},
        provider_authority_sha256="a" * 64,
        response_receipt_sha256s=(response_receipt,),
        successful_response_ordinals=(0,),
        result_route_ids=("stg_league_game_log",),
    )
    store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(call_receipt,),
    )
    root = store.root
    store.close()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["done_call_bindings"][0]["endpoint_name"] = "box_score_summary"
    manifest["done_call_bindings_sha256"] = hashlib.sha256(
        json.dumps(
            manifest["done_call_bindings"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    body = dict(manifest)
    body.pop("manifest_sha256")
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ExtractionError, match="contents disagree with the manifest"):
        BronzeCaptureStore(
            root,
            public_roots=(tmp_path / "data" / "nbadb",),
            limits=BronzeLimits(100_000, 1_000_000, 1),
        )


def test_logical_call_rejects_dangling_attempt_receipt(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ExtractionError, match="unavailable or unsafe"):
        store.record_logical_call(
            context=ParserInputContext(attempt_id="attempt-1"),
            logical_endpoint_id="league_game_log",
            logical_parameters={"season": "2024-25"},
            provider_authority_sha256="a" * 64,
            response_receipt_sha256s=("d" * 64,),
            successful_response_ordinals=(0,),
            result_route_ids=("stg_league_game_log",),
        )


def test_logical_call_allows_owned_heterogeneous_fallback_contracts(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    context = ParserInputContext(attempt_id="attempt-1")
    primary = store.store_parser_input("{}", representation=PARSER_INPUT_REPRESENTATION)
    primary_receipt = store.record_response_attempt(
        context=context,
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="PrimaryEndpoint",
        endpoint_slug="primary",
        parameters={"PrimaryID": 1},
        provider_authority_sha256="a" * 64,
        contract_sha256="b" * 64,
        status_code=200,
        captured=primary,
        outcome="contract_mismatch",
        failure_class="response_contract",
        root_exception_class="ResponseContractError",
        result_sets=(),
    )
    fallback_context = replace(context, request_ordinal=1)
    fallback = store.store_parser_input("{}", representation=PARSER_INPUT_REPRESENTATION)
    fallback_receipt = store.record_response_attempt(
        context=fallback_context,
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="FallbackEndpoint",
        endpoint_slug="fallback",
        parameters={"FallbackID": 2},
        provider_authority_sha256="a" * 64,
        contract_sha256="c" * 64,
        status_code=200,
        captured=fallback,
        outcome="success_empty",
        failure_class=None,
        root_exception_class=None,
        result_sets=(),
    )

    call = store.record_logical_call(
        context=context,
        logical_endpoint_id="logical_endpoint",
        logical_parameters={"entity_id": 1},
        provider_authority_sha256="a" * 64,
        response_receipt_sha256s=(primary_receipt, fallback_receipt),
        successful_response_ordinals=(1,),
        result_route_ids=("stg_logical",),
    )

    assert len(call) == 64


def test_logical_call_rejects_reordered_or_empty_routes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    context = ParserInputContext(attempt_id="attempt-1")
    first_receipt, _expected = _response_receipt(store, "{}")
    second = store.store_parser_input("{}", representation=PARSER_INPUT_REPRESENTATION)
    second_receipt = store.record_response_attempt(
        context=replace(context, request_ordinal=1),
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="LeagueGameLog",
        endpoint_slug="leaguegamelog",
        parameters={"LeagueID": "00", "Season": "2024-25"},
        provider_authority_sha256="a" * 64,
        contract_sha256="b" * 64,
        status_code=200,
        captured=second,
        outcome="success_empty",
        failure_class=None,
        root_exception_class=None,
        result_sets=(),
    )

    with pytest.raises(ExtractionError, match="contiguous and ordered"):
        store.record_logical_call(
            context=context,
            logical_endpoint_id="league_game_log",
            logical_parameters={"season": "2024-25"},
            provider_authority_sha256="a" * 64,
            response_receipt_sha256s=(second_receipt, first_receipt),
            successful_response_ordinals=(0, 1),
            result_route_ids=("stg_league_game_log",),
        )
    with pytest.raises(ValueError, match="nonempty"):
        store.record_logical_call(
            context=context,
            logical_endpoint_id="league_game_log",
            logical_parameters={"season": "2024-25"},
            provider_authority_sha256="a" * 64,
            response_receipt_sha256s=(first_receipt,),
            successful_response_ordinals=(0,),
            result_route_ids=(),
        )


def test_logical_call_canonicalizes_exact_multi_route_ids(tmp_path: Path) -> None:
    store = _store(tmp_path)
    response_receipt, _expected = _response_receipt(store, "{}")
    routes = (
        "schedule:stg_schedule_weeks:1",
        "schedule:stg_schedule:0",
    )

    call_receipt = store.record_logical_call(
        context=ParserInputContext(attempt_id="attempt-1"),
        logical_endpoint_id="schedule",
        logical_parameters={"season": "2024-25"},
        provider_authority_sha256="a" * 64,
        response_receipt_sha256s=(response_receipt,),
        successful_response_ordinals=(0,),
        result_route_ids=routes,
    )
    receipt_path = store.root / "receipts" / "calls" / call_receipt[:2] / f"{call_receipt}.json"
    payload = json.loads(receipt_path.read_text())

    assert payload["result_route_ids"] == sorted(routes)


def test_completed_logical_call_binding_roundtrips_under_exact_authority(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    response_receipt, _expected = _response_receipt(store, "{}")
    logical_parameters = {"season": "2024-25"}
    parameter_digest = canonical_parameters_sha256(logical_parameters)
    routes = (
        "schedule:stg_schedule:0",
        "schedule:stg_schedule_weeks:1",
    )
    call_receipt = store.record_logical_call(
        context=ParserInputContext(attempt_id="attempt-1"),
        logical_endpoint_id="schedule",
        logical_parameters=logical_parameters,
        provider_authority_sha256="a" * 64,
        response_receipt_sha256s=(response_receipt,),
        successful_response_ordinals=(0,),
        result_route_ids=routes,
    )

    binding = store.load_completed_logical_call_binding(
        call_receipt,
        expected_endpoint_name="schedule",
        expected_provider_authority_sha256="a" * 64,
        expected_logical_parameters_sha256=parameter_digest,
        expected_result_route_ids=routes,
    )

    assert binding == LogicalCallReceiptBinding(
        logical_call_receipt_sha256=call_receipt,
        endpoint_name="schedule",
        logical_parameters_sha256=parameter_digest,
        provider_authority_sha256="a" * 64,
        result_route_ids=routes,
    )


@pytest.mark.parametrize(
    ("endpoint_name", "provider_digest", "parameter_digest", "routes"),
    [
        ("schedule", "f" * 64, None, None),
        ("schedule", None, "f" * 64, None),
        ("schedule", None, None, ("schedule:stg_other:0",)),
        ("box_score_summary", None, None, None),
    ],
)
def test_completed_logical_call_binding_rejects_expected_authority_drift(
    tmp_path: Path,
    endpoint_name: str,
    provider_digest: str | None,
    parameter_digest: str | None,
    routes: tuple[str, ...] | None,
) -> None:
    store = _store(tmp_path)
    response_receipt, _expected = _response_receipt(store, "{}")
    logical_parameters = {"season": "2024-25"}
    expected_parameter_digest = canonical_parameters_sha256(logical_parameters)
    expected_routes = ("stg_league_game_log",)
    call_receipt = store.record_logical_call(
        context=ParserInputContext(attempt_id="attempt-1"),
        logical_endpoint_id="league_game_log",
        logical_parameters=logical_parameters,
        provider_authority_sha256="a" * 64,
        response_receipt_sha256s=(response_receipt,),
        successful_response_ordinals=(0,),
        result_route_ids=expected_routes,
    )

    with pytest.raises(ExtractionError, match="expected-authority drift"):
        store.load_completed_logical_call_binding(
            call_receipt,
            expected_endpoint_name=endpoint_name,
            expected_provider_authority_sha256=provider_digest or "a" * 64,
            expected_logical_parameters_sha256=(parameter_digest or expected_parameter_digest),
            expected_result_route_ids=routes or expected_routes,
        )


@pytest.mark.parametrize(
    ("field_name", "field_value", "match"),
    [
        ("result_route_ids", ["route_b", "route_a"], "route inventory"),
        ("successful_response_ordinals", [], "success ordinals"),
    ],
)
def test_completed_logical_call_binding_rejects_canonical_semantic_corruption(
    tmp_path: Path,
    field_name: str,
    field_value: list[str] | list[int],
    match: str,
) -> None:
    store = _store(tmp_path)
    response_receipt, _expected = _response_receipt(store, "{}")
    logical_parameters = {"season": "2024-25"}
    parameter_digest = canonical_parameters_sha256(logical_parameters)
    routes = ("route_a", "route_b")
    call_receipt = store.record_logical_call(
        context=ParserInputContext(attempt_id="attempt-1"),
        logical_endpoint_id="league_game_log",
        logical_parameters=logical_parameters,
        provider_authority_sha256="a" * 64,
        response_receipt_sha256s=(response_receipt,),
        successful_response_ordinals=(0,),
        result_route_ids=routes,
    )
    receipt_path = store.root / "receipts" / "calls" / call_receipt[:2] / f"{call_receipt}.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload[field_name] = field_value
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    forged_digest = hashlib.sha256(encoded).hexdigest()
    forged_path = store.root / "receipts" / "calls" / forged_digest[:2] / f"{forged_digest}.json"
    forged_path.parent.mkdir(parents=True, exist_ok=True)
    forged_path.write_bytes(encoded)

    with pytest.raises(ExtractionError, match=match):
        store.load_completed_logical_call_binding(
            forged_digest,
            expected_endpoint_name="league_game_log",
            expected_provider_authority_sha256="a" * 64,
            expected_logical_parameters_sha256=parameter_digest,
            expected_result_route_ids=routes,
        )


def test_completed_logical_call_binding_rejects_endpoint_tamper(tmp_path: Path) -> None:
    store = _store(tmp_path)
    response_receipt, _expected = _response_receipt(store, "{}")
    logical_parameters = {"season": "2024-25"}
    parameter_digest = canonical_parameters_sha256(logical_parameters)
    routes = ("stg_league_game_log",)
    call_receipt = store.record_logical_call(
        context=ParserInputContext(attempt_id="attempt-1"),
        logical_endpoint_id="league_game_log",
        logical_parameters=logical_parameters,
        provider_authority_sha256="a" * 64,
        response_receipt_sha256s=(response_receipt,),
        successful_response_ordinals=(0,),
        result_route_ids=routes,
    )
    receipt_path = store.root / "receipts" / "calls" / call_receipt[:2] / f"{call_receipt}.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["logical_endpoint_id"] = "box_score_summary"
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    forged_digest = hashlib.sha256(encoded).hexdigest()
    forged_path = store.root / "receipts" / "calls" / forged_digest[:2] / f"{forged_digest}.json"
    forged_path.parent.mkdir(parents=True, exist_ok=True)
    forged_path.write_bytes(encoded)

    with pytest.raises(ExtractionError, match="expected-authority drift"):
        store.load_completed_logical_call_binding(
            forged_digest,
            expected_endpoint_name="league_game_log",
            expected_provider_authority_sha256="a" * 64,
            expected_logical_parameters_sha256=parameter_digest,
            expected_result_route_ids=routes,
        )


def test_logical_call_receipt_binding_requires_canonical_nonempty_routes() -> None:
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256="a" * 64,
        endpoint_name="schedule",
        logical_parameters_sha256="b" * 64,
        provider_authority_sha256="c" * 64,
        result_route_ids=("ep:stg_a:0", "ep:stg_b:1"),
    )

    assert binding.result_route_ids == ("ep:stg_a:0", "ep:stg_b:1")
    with pytest.raises(ValueError, match="sorted unique nonempty"):
        LogicalCallReceiptBinding(
            logical_call_receipt_sha256="a" * 64,
            endpoint_name="schedule",
            logical_parameters_sha256="b" * 64,
            provider_authority_sha256="c" * 64,
            result_route_ids=("ep:stg_b:1", "ep:stg_a:0"),
        )
    with pytest.raises(ValueError, match="safe bounded identifier"):
        LogicalCallReceiptBinding(
            logical_call_receipt_sha256="a" * 64,
            endpoint_name="../schedule",
            logical_parameters_sha256="b" * 64,
            provider_authority_sha256="c" * 64,
            result_route_ids=("ep:stg_a:0",),
        )


def test_non_utf8_provider_input_cannot_be_forged_with_bytes(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(TypeError, match="decoded string"):
        store.store_parser_input(  # type: ignore[arg-type]
            b"\xff",
            representation=PARSER_INPUT_REPRESENTATION,
        )


def test_concurrent_same_input_is_one_immutable_object(tmp_path: Path) -> None:
    store = _store(tmp_path)
    barrier = Barrier(8)

    def store_once() -> str:
        barrier.wait()
        return store.store_parser_input(
            "same parser input",
            representation=PARSER_INPUT_REPRESENTATION,
        ).object_sha256

    with ThreadPoolExecutor(max_workers=8) as executor:
        digests = list(executor.map(lambda _index: store_once(), range(8)))

    assert len(set(digests)) == 1
    assert len(list((store.root / "blobs").rglob("*.payload.gz"))) == 1


def test_concurrent_distinct_inputs_cannot_overrun_generation_limit(tmp_path: Path) -> None:
    probe = gzip.compress(b"a" * 200, compresslevel=6, mtime=0)
    store = _store(
        tmp_path,
        max_generation_stored_bytes=len(probe) + 4,
    )
    barrier = Barrier(2)

    def store_once(payload: str) -> str:
        barrier.wait()
        try:
            return store.store_parser_input(
                payload,
                representation=PARSER_INPUT_REPRESENTATION,
            ).object_sha256
        except ParserInputCapacityError:
            return "capacity"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(store_once, ("a" * 200, "b" * 200)))

    assert outcomes.count("capacity") == 1
    assert len(list((store.root / "blobs").rglob("*.payload.gz"))) == 1


def test_manifest_seal_race_is_serialized_without_unattested_write(tmp_path: Path) -> None:
    store = _store(tmp_path)
    barrier = Barrier(2)

    def write_blob() -> str:
        barrier.wait()
        try:
            return store.store_parser_input(
                "raced",
                representation=PARSER_INPUT_REPRESENTATION,
            ).object_sha256
        except ExtractionError:
            return "sealed"

    def seal() -> dict[str, object]:
        barrier.wait()
        return store.write_manifest(
            provider_authority_sha256="a" * 64,
            semantic_source_sha=None,
            chain_id=None,
            lane_id=None,
            workflow_run_id=_WORKFLOW_RUN_ID,
            workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
            done_call_receipt_sha256s=(),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        blob_future = executor.submit(write_blob)
        manifest_future = executor.submit(seal)
        blob_result = blob_future.result()
        manifest = manifest_future.result()

    blob_artifacts = [item for item in manifest["artifacts"] if item["path"].startswith("blobs/")]
    assert (blob_result == "sealed" and blob_artifacts == []) or (
        blob_result != "sealed" and len(blob_artifacts) == 1
    )


def test_receipt_count_limit_fails_before_second_receipt(tmp_path: Path) -> None:
    store = _store(tmp_path, max_receipt_count=1)
    _response_receipt(store, "{}")
    captured = store.store_parser_input("[]", representation=PARSER_INPUT_REPRESENTATION)

    with pytest.raises(ParserInputCapacityError, match="receipt-count"):
        store.record_response_attempt(
            context=ParserInputContext(attempt_id="attempt-2"),
            transport_kind="http_response",
            source_family="stats",
            endpoint_id="LeagueGameLog",
            endpoint_slug="leaguegamelog",
            parameters={"LeagueID": "00", "Season": "2024-25"},
            provider_authority_sha256="a" * 64,
            contract_sha256="b" * 64,
            status_code=200,
            captured=captured,
            outcome="success_nonempty",
            failure_class=None,
            root_exception_class=None,
            result_sets=(),
        )

    assert len(list((store.root / "receipts" / "attempts").rglob("*.json"))) == 1


def test_capture_from_another_store_cannot_forge_attempt_receipt(tmp_path: Path) -> None:
    first = BronzeCaptureStore(
        tmp_path / "first",
        public_roots=(tmp_path / "data",),
        limits=BronzeLimits(1000, 100_000, 1),
    )
    second = BronzeCaptureStore(
        tmp_path / "second",
        public_roots=(tmp_path / "data",),
        limits=BronzeLimits(1000, 100_000, 1),
    )
    captured = first.store_parser_input("{}", representation=PARSER_INPUT_REPRESENTATION)

    with pytest.raises(ExtractionError, match="stored parser-input digest"):
        second.record_response_attempt(
            context=ParserInputContext(attempt_id="attempt-1"),
            transport_kind="http_response",
            source_family="stats",
            endpoint_id="Fixture",
            endpoint_slug="fixture",
            parameters={},
            provider_authority_sha256="a" * 64,
            contract_sha256="b" * 64,
            status_code=200,
            captured=captured,
            outcome="success_nonempty",
            failure_class=None,
            root_exception_class=None,
            result_sets=(),
        )


def test_unknown_file_blocks_manifest_seal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    (store.root / "unexpected.txt").write_text("not a contract artifact", encoding="utf-8")

    with pytest.raises(ExtractionError, match="unknown artifact"):
        store.write_manifest(
            provider_authority_sha256="a" * 64,
            semantic_source_sha=None,
            chain_id=None,
            lane_id=None,
            workflow_run_id=_WORKFLOW_RUN_ID,
            workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
            done_call_receipt_sha256s=(),
        )


def test_symlinked_root_parent_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink = tmp_path / "private-link"
    symlink.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot traverse a symlink"):
        BronzeCaptureStore(
            symlink / "bronze",
            public_roots=(tmp_path / "data",),
            limits=BronzeLimits(1000, 100_000, 1),
        )


def test_private_directories_and_files_use_private_modes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt, _expected = _response_receipt(store, "{}")
    receipt_path = next((store.root / "receipts").rglob(f"{receipt}.json"))
    blob_path = next((store.root / "blobs").rglob("*.payload.gz"))

    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(blob_path.stat().st_mode) == 0o600


def test_replay_enforces_current_uncompressed_limit(tmp_path: Path) -> None:
    first = _store(tmp_path, max_response_bytes=1000)
    receipt, _expected = _response_receipt(first, "x" * 500)
    root = first.root
    first.close()
    second = BronzeCaptureStore(
        root,
        public_roots=(tmp_path / "data" / "nbadb",),
        limits=BronzeLimits(
            max_response_bytes=100,
            max_generation_stored_bytes=1_000_000,
            minimum_free_bytes=1,
        ),
    )

    with pytest.raises(ParserInputCapacityError, match="decoded parser input"):
        second.replay_parser_input(receipt)


def test_sealed_manifest_is_reverified_on_reopen(tmp_path: Path) -> None:
    first = _store(tmp_path)
    _response_receipt(first, "{}")
    first.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    root = first.root
    first.close()
    blob_path = next((root / "blobs").rglob("*.payload.gz"))
    blob_path.write_bytes(b"tampered")

    with pytest.raises(ExtractionError, match="inventoried safely|digest mismatch"):
        BronzeCaptureStore(
            root,
            public_roots=(tmp_path / "data" / "nbadb",),
            limits=BronzeLimits(100_000, 1_000_000, 1),
        )


@pytest.mark.parametrize(
    ("workflow_run_id", "workflow_run_attempt"),
    [
        (0, _WORKFLOW_RUN_ATTEMPT),
        (True, _WORKFLOW_RUN_ATTEMPT),
        (_WORKFLOW_RUN_ID, 0),
        (_WORKFLOW_RUN_ID, False),
    ],
)
def test_manifest_rejects_nonpositive_execution_identity(
    tmp_path: Path,
    workflow_run_id: int,
    workflow_run_attempt: int,
) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="must be a positive integer"):
        store.build_manifest(
            provider_authority_sha256="a" * 64,
            semantic_source_sha=None,
            chain_id=None,
            lane_id=None,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
            done_call_receipt_sha256s=(),
        )


def test_sealed_manifest_load_rejects_invalid_execution_identity(tmp_path: Path) -> None:
    first = _store(tmp_path)
    first.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )
    root = first.root
    first.close()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["workflow_run_attempt"] = 0
    body = dict(manifest)
    body.pop("manifest_sha256")
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ExtractionError, match="execution identity is invalid"):
        BronzeCaptureStore(
            root,
            public_roots=(tmp_path / "data" / "nbadb",),
            limits=BronzeLimits(100_000, 1_000_000, 1),
        )


def test_static_snapshot_is_canonicalized_by_the_store(tmp_path: Path) -> None:
    store = _store(tmp_path)

    first = store.store_static_records([{"name": "A", "id": 1}])
    second = store.store_static_records([{"id": 1, "name": "A"}])

    assert first.object_sha256 == second.object_sha256
    assert gzip.decompress(store.root.joinpath(first.relative_path).read_bytes()) == (
        b'[{"id":1,"name":"A"}]'
    )


def test_static_snapshot_receipt_is_truthful_and_replayable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    captured = store.store_static_records([{"id": 1, "name": "A"}])

    receipt = store.record_static_snapshot_attempt(
        context=ParserInputContext(attempt_id="static-1"),
        endpoint_id="static_players",
        endpoint_slug="players",
        provider_authority_sha256="a" * 64,
        contract_sha256="b" * 64,
        captured=captured,
        result_set=ResultSetReceipt(
            name="players_shape_1",
            provider_index=0,
            canonical_index=0,
            headers_sha256="c" * 64,
            row_count=1,
            json_path=None,
            container_kind="nba_api_static_records",
            container_count=1,
            missing_count=0,
            null_count=0,
            parent_observation_count=1,
            parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
            observed_field_orders_sha256="d" * 64,
            normalized_output_sha256="e" * 64,
        ),
    )
    path = next((store.root / "receipts" / "attempts").rglob(f"{receipt}.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["transport_kind"] == "static_provider_snapshot"
    assert payload["source_family"] == "static"
    assert payload["status_code"] is None
    assert payload["effective_status_code"] is None
    assert payload["parser_input"]["representation"] == STATIC_INPUT_REPRESENTATION
    assert store.replay_parser_input(receipt) == b'[{"id":1,"name":"A"}]'


def test_static_snapshot_rejects_http_status_or_http_representation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    captured_static = store.store_static_records([])
    captured_http = store.store_parser_input("[]", representation=PARSER_INPUT_REPRESENTATION)

    with pytest.raises(ValueError, match="cannot carry HTTP status"):
        store.record_response_attempt(
            context=ParserInputContext(attempt_id="static-1"),
            transport_kind="static_provider_snapshot",
            source_family="static",
            endpoint_id="static_players",
            endpoint_slug="players",
            parameters={},
            provider_authority_sha256="a" * 64,
            contract_sha256="b" * 64,
            status_code=200,
            captured=captured_static,
            outcome="success_empty",
            failure_class=None,
            root_exception_class=None,
            result_sets=(),
        )
    with pytest.raises(ValueError, match="canonical static input"):
        store.record_response_attempt(
            context=ParserInputContext(attempt_id="static-2"),
            transport_kind="static_provider_snapshot",
            source_family="static",
            endpoint_id="static_players",
            endpoint_slug="players",
            parameters={},
            provider_authority_sha256="a" * 64,
            contract_sha256="b" * 64,
            status_code=None,
            captured=captured_http,
            outcome="success_empty",
            failure_class=None,
            root_exception_class=None,
            result_sets=(),
        )


def test_static_snapshot_helper_rejects_noncanonical_result_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    captured = store.store_static_records([])

    with pytest.raises(ValueError, match="result-set identity"):
        store.record_static_snapshot_attempt(
            context=ParserInputContext(attempt_id="static-1"),
            endpoint_id="static_players",
            endpoint_slug="players",
            provider_authority_sha256="a" * 64,
            contract_sha256="b" * 64,
            captured=captured,
            result_set=ResultSetReceipt(
                name="wrong_shape_1",
                provider_index=0,
                canonical_index=0,
                headers_sha256="c" * 64,
                row_count=0,
                json_path=None,
                container_kind="nba_api_static_records",
                container_count=1,
                missing_count=0,
                null_count=0,
                parent_observation_count=1,
                parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
                observed_field_orders_sha256="d" * 64,
                normalized_output_sha256="e" * 64,
            ),
        )


def test_static_pre_snapshot_contract_failure_has_no_fabricated_response(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    receipt = store.record_no_response_attempt(
        context=ParserInputContext(attempt_id="static-1"),
        transport_kind="static_provider_snapshot",
        source_family="static",
        endpoint_id="static_teams",
        endpoint_slug="teams",
        parameters={},
        provider_authority_sha256="a" * 64,
        contract_sha256="b" * 64,
        outcome="contract_mismatch",
        failure_class="response_contract",
        root_exception_class="ResponseContractError",
    )
    path = next((store.root / "receipts" / "attempts").rglob(f"{receipt}.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["transport_kind"] == "static_provider_snapshot"
    assert payload["status_code"] is None
    assert payload["parser_input"] is None


def test_static_snapshot_rejects_noncanonical_endpoint_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="endpoint identity"):
        store.record_no_response_attempt(
            context=ParserInputContext(attempt_id="static-1"),
            transport_kind="static_provider_snapshot",
            source_family="static",
            endpoint_id="static_teams",
            endpoint_slug="unrelated",
            parameters={},
            provider_authority_sha256="a" * 64,
            contract_sha256="b" * 64,
            outcome="contract_mismatch",
            failure_class="response_contract",
            root_exception_class="ResponseContractError",
        )


def test_parser_input_does_not_require_valid_json(tmp_path: Path) -> None:
    store = _store(tmp_path)

    captured = store.store_parser_input(
        "<html>access denied</html>",
        representation=PARSER_INPUT_REPRESENTATION,
    )

    assert gzip.decompress(store.root.joinpath(captured.relative_path).read_bytes()) == (
        b"<html>access denied</html>"
    )


def test_sealed_manifest_rejects_different_idempotent_scope(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )

    with pytest.raises(ExtractionError, match="scope is immutable"):
        store.write_manifest(
            provider_authority_sha256="a" * 64,
            semantic_source_sha=None,
            chain_id=None,
            lane_id=None,
            workflow_run_id=_WORKFLOW_RUN_ID,
            workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT + 1,
            done_call_receipt_sha256s=(),
        )


def test_parameter_digest_rejects_nonfinite_and_mixed_keys() -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_parameters_sha256({"value": float("nan")})
    with pytest.raises(ValueError, match="keys must be strings"):
        canonical_parameters_sha256({"value": 1, 2: "two"})  # type: ignore[dict-item]


def test_parameter_payload_is_canonical_detached_and_digest_equivalent() -> None:
    game_ids = ["0022400001", "0022400002"]
    parameters = {
        "season_type": "Regular Season",
        "game_ids": game_ids,
        "nullable": None,
    }

    payload = canonical_parameters_payload(parameters)
    game_ids.append("0022400003")

    assert payload == {
        "game_ids": ["0022400001", "0022400002"],
        "nullable": None,
        "season_type": "Regular Season",
    }
    assert (
        canonical_parameters_sha256(payload)
        == hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    )


@pytest.mark.parametrize(
    "parameters",
    [
        {"access_token": "redacted"},
        {"filters": {"season": "2024-25"}},
        {"game_ids": [["0022400001"]]},
        {"game_ids": {"0022400001"}},
    ],
)
def test_parameter_payload_rejects_secret_or_nested_mutable_values(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="forbidden key|unsupported value type"):
        canonical_parameters_payload(parameters)


def test_failure_receipt_rejects_unclassified_metadata(tmp_path: Path) -> None:
    store = _store(tmp_path)
    captured = store.store_parser_input("{}", representation=PARSER_INPUT_REPRESENTATION)

    with pytest.raises(ValueError, match="safe allowlist"):
        store.record_response_attempt(
            context=ParserInputContext(attempt_id="attempt-1"),
            transport_kind="http_response",
            source_family="stats",
            endpoint_id="Fixture",
            endpoint_slug="fixture",
            parameters={},
            provider_authority_sha256="a" * 64,
            contract_sha256="b" * 64,
            status_code=200,
            captured=captured,
            outcome="contract_mismatch",
            failure_class="response_contract",
            root_exception_class="secret_from_exception_class",
            result_sets=(),
        )


def test_manifest_is_never_world_readable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_manifest(
        provider_authority_sha256="a" * 64,
        semantic_source_sha=None,
        chain_id=None,
        lane_id=None,
        workflow_run_id=_WORKFLOW_RUN_ID,
        workflow_run_attempt=_WORKFLOW_RUN_ATTEMPT,
        done_call_receipt_sha256s=(),
    )

    assert stat.S_IMODE(os.stat(store.root / "manifest.json").st_mode) == 0o600
