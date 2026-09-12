from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from nbadb.core.artifact_identity import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME,
)
from nbadb.orchestrate.successor_generation_store import SuccessorGenerationStore
from nbadb.orchestrate.successor_inventory import measure_installed_public_tree
from nbadb.orchestrate.successor_publication_authority import (
    SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED,
    SUCCESSOR_DURABLE_PUBLICATION_REQUIRED,
    SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED,
    SuccessorPublicationAuthorityError,
    bind_successor_report_to_current_authority,
    open_successor_generation_store,
    require_successor_current_publication_authority,
    require_successor_durable_publication,
    require_successor_publication_authority,
    successor_publication_requested,
)
from nbadb.orchestrate.successor_update_contract import (
    SuccessorGenerationState,
    SuccessorUpdateTransaction,
)
from tests.unit.orchestrate.test_successor_assurance import _report
from tests.unit.orchestrate.test_successor_generation_store import _promoted

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DAILY_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "daily-update.yml"
_MONTHLY_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "monthly-update.yml"
_SCAN_REPORT_ACTION = _REPO_ROOT / ".github" / "actions" / "scan-report" / "action.yml"


def _write_report(data_dir: Path, payload: bytes | str | dict[str, object]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    elif isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def test_require_successor_publication_authority_accepts_canonical_schema_v7(
    tmp_path: Path,
) -> None:
    report = _report()
    _write_report(tmp_path, report.canonical_bytes)

    assert require_successor_publication_authority(tmp_path) == report
    assert successor_publication_requested(tmp_path) is True


def test_require_successor_publication_authority_rejects_missing_report(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match="cannot substitute",
    ):
        require_successor_publication_authority(tmp_path)
    assert successor_publication_requested(tmp_path) is False


def test_require_successor_publication_authority_rejects_schema_v3_terminal_report(
    tmp_path: Path,
) -> None:
    _write_report(
        tmp_path,
        {
            "schema_version": 3,
            "chain_id": "full-baseline-20260801",
            "source_sha": "a" * 40,
        },
    )

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED,
    ):
        require_successor_publication_authority(tmp_path)
    assert successor_publication_requested(tmp_path) is False


def test_successor_publication_requested_is_true_when_store_is_supplied(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "successor-store")
    _write_report(
        tmp_path,
        {
            "schema_version": 3,
            "chain_id": "full-baseline-20260801",
            "source_sha": "a" * 40,
        },
    )

    assert successor_publication_requested(tmp_path) is False
    assert successor_publication_requested(tmp_path, successor_generation_store=store) is True


def test_require_successor_durable_publication_rejects_leftover_v3_when_store_requested(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "successor-store")
    _write_report(
        tmp_path,
        {
            "schema_version": 3,
            "chain_id": "full-baseline-20260801",
            "source_sha": "a" * 40,
        },
    )

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED,
    ):
        require_successor_durable_publication(
            tmp_path,
            full_publication=True,
            verify_remote=True,
            require_durable_intent=True,
            publication_ledger=object(),
            successor_generation_store=store,
        )


def test_require_successor_publication_authority_rejects_invalid_schema_v7_bytes(
    tmp_path: Path,
) -> None:
    _write_report(tmp_path, {"schema_version": 7, "kind": "not-successor"})

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match="schema-v7 successor authority is invalid",
    ):
        require_successor_publication_authority(tmp_path)
    assert successor_publication_requested(tmp_path) is True


def test_require_successor_publication_authority_rejects_symlink_report(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "public"
    data_dir.mkdir()
    target = tmp_path / "elsewhere.json"
    target.write_text("{}\n", encoding="utf-8")
    (data_dir / SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME).symlink_to(target)

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED,
    ):
        require_successor_publication_authority(data_dir)
    assert successor_publication_requested(data_dir) is False


def _promoted_current_authority(
    tmp_path: Path,
) -> tuple[SuccessorGenerationStore, Path, SuccessorUpdateTransaction]:
    report = _report()
    report_bytes = report.canonical_bytes
    data_bytes = b"promoted-current-public-duckdb"
    store = SuccessorGenerationStore(tmp_path / "successor-store")
    candidate = SuccessorUpdateTransaction.candidate(
        generation=1,
        baseline=report.baseline,
        intent=report.intent,
    )
    built = candidate.mark_built(observed_delta_receipts=report.build.observed_delta_receipts)
    candidate_root = store.candidate_path(candidate)
    public_root = candidate_root / "public"
    public_root.mkdir(parents=True)
    assured_manifest = {
        "chain_id": report.chain_id,
        "source_sha": report.source_sha,
        "coverage_fingerprint": report.coverage_fingerprint,
        "data_tree_fingerprint": report.public_evidence.successor_data_tree_fingerprint,
        "files": [
            {
                "path": "nba.duckdb",
                "bytes": len(data_bytes),
                "sha256": hashlib.sha256(data_bytes).hexdigest(),
            },
            {
                "path": SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME,
                "bytes": len(report_bytes),
                "sha256": hashlib.sha256(report_bytes).hexdigest(),
            },
        ],
    }
    manifest_bytes = (
        json.dumps(assured_manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    (public_root / "nba.duckdb").write_bytes(data_bytes)
    (public_root / SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME).write_bytes(report_bytes)
    (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).write_bytes(manifest_bytes)
    installed = measure_installed_public_tree(public_root)
    identity = report.to_successor_assurance_identity(
        successor_assured_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        installed_public_tree_sha256=installed.installed_public_tree_sha256,
    )
    validated = built.mark_validated(identity)
    promoted = validated.promote()
    store.record_transaction(candidate_root, candidate)
    store.record_transaction(candidate_root, built)
    store.record_transaction(candidate_root, validated)
    store.record_promoted_candidate(candidate_root, promoted)
    with patch.object(store, "_gate_publication_before_promote"):
        store.promote(candidate_root, promoted)
    return store, public_root, promoted


def test_require_successor_durable_publication_accepts_verified_durable_path(
    tmp_path: Path,
) -> None:
    store, public_root, _promoted = _promoted_current_authority(tmp_path)
    report = _report()

    assert (
        require_successor_durable_publication(
            public_root,
            full_publication=True,
            verify_remote=True,
            require_durable_intent=True,
            publication_ledger=object(),
            successor_generation_store=store,
        )
        == report
    )


@pytest.mark.parametrize(
    ("full_publication", "verify_remote", "require_durable_intent", "has_ledger"),
    [
        (False, True, True, True),
        (True, False, True, True),
        (True, True, False, True),
        (True, True, True, False),
    ],
)
def test_require_successor_durable_publication_rejects_generic_upload(
    tmp_path: Path,
    full_publication: bool,
    verify_remote: bool,
    require_durable_intent: bool,
    has_ledger: bool,
) -> None:
    _write_report(tmp_path, _report().canonical_bytes)

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_DURABLE_PUBLICATION_REQUIRED,
    ):
        require_successor_durable_publication(
            tmp_path,
            full_publication=full_publication,
            verify_remote=verify_remote,
            require_durable_intent=require_durable_intent,
            publication_ledger=object() if has_ledger else None,
        )


@pytest.mark.parametrize("workflow_path", [_DAILY_WORKFLOW, _MONTHLY_WORKFLOW])
def test_scheduled_update_workflows_use_public_recurring_publication(
    workflow_path: Path,
) -> None:
    workflow = workflow_path.read_text(encoding="utf-8")
    scan_start = workflow.index("name: Scan data quality")
    upload_start = workflow.index("name: Upload to Kaggle")
    scan = workflow[scan_start:upload_start]
    upload = workflow[upload_start:]

    assert "full-publication: true" not in scan
    assert "data-dir: data/nbadb" in scan
    assert "successor-generation-store" not in scan
    assert "checkpoint-report:" not in scan
    assert "checkpoint-manifest:" not in scan
    assert "--full-publication" not in upload
    assert "--verify-remote" in upload
    assert "--successor-generation-store" not in upload
    assert "--publication-ledger github-deployment" in upload
    assert "--require-durable-intent" in upload
    assert "group: nbadb-kaggle-publish" in workflow
    assert "queue: max" in workflow
    assert "cancel-in-progress: false" in workflow


def test_scan_report_action_uses_successor_full_publication_without_checkpoints() -> None:
    action = _SCAN_REPORT_ACTION.read_text(encoding="utf-8")

    assert "args+=(--full-publication)" in action
    assert "args+=(--successor-generation-store" in action
    assert "full-publication scan requires all canonical checkpoint inputs" in action
    checkpoint_error = action.index(
        "full-publication scan requires all canonical checkpoint inputs"
    )
    successor_args = action.index("args+=(--full-publication)")
    store_args = action.index("args+=(--successor-generation-store")
    assert checkpoint_error < successor_args < store_args
    assert 'if [ -n "$CHECKPOINT_REPORT" ]' in action
    assert 'if [ -n "$SUCCESSOR_GENERATION_STORE" ]' in action


def test_open_successor_generation_store_rejects_missing_or_symlink_root(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-store"
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked-store"
    linked.symlink_to(target)

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED,
    ):
        open_successor_generation_store(missing)
    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED,
    ):
        open_successor_generation_store(linked)


def test_require_successor_durable_publication_requires_explicit_store(
    tmp_path: Path,
) -> None:
    _write_report(tmp_path, _report().canonical_bytes)

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED,
    ):
        require_successor_durable_publication(
            tmp_path,
            full_publication=True,
            verify_remote=True,
            require_durable_intent=True,
            publication_ledger=object(),
        )


def test_require_successor_publication_authority_binds_current_when_required(
    tmp_path: Path,
) -> None:
    store, public_root, promoted = _promoted_current_authority(tmp_path)

    report = require_successor_publication_authority(
        public_root,
        successor_generation_store=store,
        require_current_authority=True,
    )

    assert report == _report()
    assert (
        report.to_successor_assurance_identity(
            successor_assured_manifest_sha256=(
                promoted.promoted_assurance.successor_assured_manifest_sha256
            ),
            installed_public_tree_sha256=promoted.promoted_assurance.installed_public_tree_sha256,
        )
        == promoted.promoted_assurance
    )


def test_require_successor_publication_authority_rejects_missing_store_when_required(
    tmp_path: Path,
) -> None:
    _write_report(tmp_path, _report().canonical_bytes)
    (tmp_path / ASSURED_ARTIFACT_MANIFEST_NAME).write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED,
    ):
        require_successor_publication_authority(
            tmp_path,
            require_current_authority=True,
        )


def test_bind_successor_report_rejects_rewritten_noncurrent_public(
    tmp_path: Path,
) -> None:
    store, public_root, _promoted = _promoted_current_authority(tmp_path)
    rewritten = tmp_path / "rewritten-public"
    shutil.copytree(public_root, rewritten)
    for path in (rewritten, *rewritten.rglob("*")):
        path.chmod(0o700 if path.is_dir() else 0o600)

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match="not the exact current candidate public directory",
    ):
        bind_successor_report_to_current_authority(
            rewritten,
            _report(),
            successor_generation_store=store,
        )


def test_require_successor_current_publication_authority_rereads_pointer(
    tmp_path: Path,
) -> None:
    store, public_root, promoted = _promoted_current_authority(tmp_path)
    assurance = promoted.promoted_assurance

    require_successor_current_publication_authority(
        data_root=public_root,
        generation_store=store,
        assurance_identity=assurance,
        installed_public_tree_sha256=assurance.installed_public_tree_sha256,
    )


def test_publication_rejects_missing_current_pointer(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "empty-store")
    report = _report()
    _write_report(tmp_path, report.canonical_bytes)
    (tmp_path / ASSURED_ARTIFACT_MANIFEST_NAME).write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match="no current generation authority",
    ):
        require_successor_publication_authority(
            tmp_path,
            successor_generation_store=store,
            require_current_authority=True,
        )


def test_publication_rejects_remeasurement_failure_after_topology_injection(
    tmp_path: Path,
) -> None:
    store, public_root, _promoted_tx = _promoted_current_authority(tmp_path)
    public_root.chmod(0o700)
    (public_root / "injected-empty").mkdir()
    public_root.chmod(0o500)

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match="current generation authority is invalid",
    ):
        bind_successor_report_to_current_authority(
            public_root,
            _report(),
            successor_generation_store=store,
        )


def test_publication_rejects_non_promoted_loaded_transaction(tmp_path: Path) -> None:
    store, public_root, promoted = _promoted_current_authority(tmp_path)
    real_load = store.load_transaction
    seen_current_read = {"done": False}

    def after_current_read(candidate: Path) -> SuccessorUpdateTransaction:
        transaction = real_load(candidate)
        if not seen_current_read["done"]:
            seen_current_read["done"] = True
            return transaction
        return replace(transaction, state=SuccessorGenerationState.VALIDATED)

    with (
        patch.object(store, "load_transaction", side_effect=after_current_read),
        pytest.raises(SuccessorPublicationAuthorityError, match="is not PROMOTED"),
    ):
        require_successor_current_publication_authority(
            data_root=public_root,
            generation_store=store,
            assurance_identity=promoted.promoted_assurance,
            installed_public_tree_sha256=(promoted.promoted_assurance.installed_public_tree_sha256),
        )


def test_publication_rejects_pointer_that_differs_from_promoted_transaction(
    tmp_path: Path,
) -> None:
    store, public_root, promoted = _promoted_current_authority(tmp_path)
    real_load = store.load_transaction
    other = _promoted(1, "other")
    seen_current_read = {"done": False}

    def after_current_read(candidate: Path) -> SuccessorUpdateTransaction:
        if not seen_current_read["done"]:
            seen_current_read["done"] = True
            return real_load(candidate)
        return other

    with (
        patch.object(store, "load_transaction", side_effect=after_current_read),
        pytest.raises(
            SuccessorPublicationAuthorityError,
            match="current pointer differs from its PROMOTED transaction",
        ),
    ):
        require_successor_current_publication_authority(
            data_root=public_root,
            generation_store=store,
            assurance_identity=promoted.promoted_assurance,
            installed_public_tree_sha256=(promoted.promoted_assurance.installed_public_tree_sha256),
        )


def test_publication_rejects_report_assurance_identity_drift(tmp_path: Path) -> None:
    store, public_root, promoted = _promoted_current_authority(tmp_path)
    drifted = replace(
        promoted.promoted_assurance,
        scan_report_sha256="0" * 64,
    )

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match="report assurance identity differs from the exact PROMOTED transaction",
    ):
        require_successor_current_publication_authority(
            data_root=public_root,
            generation_store=store,
            assurance_identity=drifted,
            installed_public_tree_sha256=(promoted.promoted_assurance.installed_public_tree_sha256),
        )


def test_publication_rejects_installed_tree_digest_drift(tmp_path: Path) -> None:
    store, public_root, promoted = _promoted_current_authority(tmp_path)

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match="installed public tree differs from current promotion authority",
    ):
        require_successor_current_publication_authority(
            data_root=public_root,
            generation_store=store,
            assurance_identity=promoted.promoted_assurance,
            installed_public_tree_sha256="0" * 64,
        )


def test_publication_rejects_pointer_change_during_validation(tmp_path: Path) -> None:
    store, public_root, promoted = _promoted_current_authority(tmp_path)
    pointer = store.read_current()
    assert pointer is not None
    altered = json.loads(json.dumps(pointer))
    altered["current"]["transaction_sha256"] = "f" * 64
    reads = [pointer, altered]

    with (
        patch.object(store, "read_current", side_effect=reads),
        pytest.raises(
            SuccessorPublicationAuthorityError,
            match="current generation changed during validation",
        ),
    ):
        require_successor_current_publication_authority(
            data_root=public_root,
            generation_store=store,
            assurance_identity=promoted.promoted_assurance,
            installed_public_tree_sha256=(promoted.promoted_assurance.installed_public_tree_sha256),
        )


def test_publication_rejects_symlink_manifest_and_invalid_store_type(tmp_path: Path) -> None:
    store, public_root, promoted = _promoted_current_authority(tmp_path)
    public_root.chmod(0o700)
    manifest = public_root / ASSURED_ARTIFACT_MANIFEST_NAME
    target = tmp_path / "elsewhere-manifest.json"
    target.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(target)
    public_root.chmod(0o500)

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED,
    ):
        bind_successor_report_to_current_authority(
            public_root,
            _report(),
            successor_generation_store=store,
        )

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match="generation store is invalid",
    ):
        require_successor_current_publication_authority(
            data_root=public_root,
            generation_store=object(),  # type: ignore[arg-type]
            assurance_identity=promoted.promoted_assurance,
            installed_public_tree_sha256=(promoted.promoted_assurance.installed_public_tree_sha256),
        )


def test_publication_rejects_symlink_data_dir_and_invalid_json_report(tmp_path: Path) -> None:
    real = tmp_path / "public"
    real.mkdir()
    _write_report(real, _report().canonical_bytes)
    linked = tmp_path / "linked-public"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED,
    ):
        require_successor_publication_authority(linked)

    _write_report(tmp_path, b"{not-json\n")
    with pytest.raises(
        SuccessorPublicationAuthorityError,
        match=SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED,
    ):
        require_successor_publication_authority(tmp_path)
