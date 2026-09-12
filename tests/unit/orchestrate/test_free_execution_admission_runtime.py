from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from nbadb.orchestrate import free_execution_admission_runtime as runtime
from nbadb.orchestrate.free_execution_admission import (
    ExecutionIntentV1,
    FreeExecutionAdmissionStatus,
    FreeExecutionAdmissionV1,
    FreeExecutionMode,
    ProviderOperationV1,
)
from nbadb.orchestrate.free_execution_admission_runtime import (
    AtomicFileReplayLedgerV1,
    FreeExecutionBoundaryError,
    FreeExecutionBoundaryV1,
    LedgerRootAuthorityV1,
    ProviderRequestAuthorizationV1,
    apply_free_execution_admission,
    authorize_provider_request,
    load_free_execution_admission,
)
from tests.unit.orchestrate import test_free_execution_admission as fixtures

if TYPE_CHECKING:
    from pathlib import Path


def _blocked() -> FreeExecutionAdmissionV1:
    return FreeExecutionAdmissionV1.capacity_blocked(
        manifest_bytes=fixtures._manifest_bytes(),
        repository=fixtures._REPOSITORY,
        source_sha=fixtures._SOURCE_SHA,
        workflow_path=fixtures._WORKFLOW_PATH,
        workflow_sha256=__import__("hashlib").sha256(fixtures._workflow_bytes()).hexdigest(),
        run_id=fixtures._RUN_ID,
        run_attempt=fixtures._RUN_ATTEMPT,
        admission_job_id="free-execution-admission",
        mode=FreeExecutionMode.INITIAL,
        requested_capacity=2,
        admission_nonce="blocked-101-1",
        evaluated_at="2026-08-26T12:01:00Z",
        expires_at="2026-08-26T12:05:00Z",
        blocker_codes=("capacity_unavailable",),
    )


def _ledger_checkpoint_response(root: Path):
    metadata = root.lstat()
    return fixtures._json_response(
        (
            f"https://api.github.com/repos/{fixtures._REPOSITORY}/actions/runs/"
            f"{fixtures._RUN_ID}/attempts/{fixtures._RUN_ATTEMPT}/"
            "free-execution-ledger-root"
        ),
        {
            "schema_version": 1,
            "repository": fixtures._REPOSITORY,
            "source_sha": fixtures._SOURCE_SHA,
            "run_id": fixtures._RUN_ID,
            "run_attempt": fixtures._RUN_ATTEMPT,
            "root_path": str(root),
            "root_device": metadata.st_dev,
            "root_inode": metadata.st_ino,
            "restoration_checkpoint_sha256": "c" * 64,
            "restored": True,
        },
        at="2026-08-26T12:01:00Z",
    )


def _operation(index: int = 0, *, nonce: str | None = None) -> ProviderOperationV1:
    return fixtures._lane_operation(index, nonce=nonce)


def test_caller_manufactured_ledger_checkpoint_is_executable_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    response = _ledger_checkpoint_response(root)
    expected_codes = LedgerRootAuthorityV1.integration_blocker_codes
    with pytest.raises(FreeExecutionBoundaryError) as caught:
        LedgerRootAuthorityV1.from_checkpoint_authority(
            root_path=root,
            repository=fixtures._REPOSITORY,
            source_sha=fixtures._SOURCE_SHA,
            run_id=fixtures._RUN_ID,
            run_attempt=fixtures._RUN_ATTEMPT,
            response=response,
        )
    assert all(code in str(caught.value) for code in expected_codes)
    monkeypatch.setattr(LedgerRootAuthorityV1, "integration_blocker_codes", ())
    with pytest.raises(FreeExecutionBoundaryError) as still_blocked:
        LedgerRootAuthorityV1.from_checkpoint_authority(
            root_path=root,
            repository=fixtures._REPOSITORY,
            source_sha=fixtures._SOURCE_SHA,
            run_id=fixtures._RUN_ID,
            run_attempt=fixtures._RUN_ATTEMPT,
            response=response,
        )
    assert all(code in str(still_blocked.value) for code in expected_codes)
    assert list(root.iterdir()) == []


def test_runtime_apply_blocks_before_projection_or_ledger_claim(tmp_path: Path) -> None:
    root = tmp_path / "untouched"
    root.mkdir()
    with pytest.raises(FreeExecutionBoundaryError) as caught:
        apply_free_execution_admission(
            fixtures._manifest_bytes(),
            _blocked(),
            authority=None,
            ledger=object(),  # type: ignore[arg-type]
            repository=fixtures._REPOSITORY,
            source_sha=fixtures._SOURCE_SHA,
            workflow_path=fixtures._WORKFLOW_PATH,
            workflow_sha256=__import__("hashlib").sha256(fixtures._workflow_bytes()).hexdigest(),
            run_id=fixtures._RUN_ID,
            run_attempt=fixtures._RUN_ATTEMPT,
            admission_job_id="free-execution-admission",
            mode=FreeExecutionMode.INITIAL,
            checked_at="2026-08-26T12:02:00Z",
        )
    assert "integration-blocked" in str(caught.value)
    assert list(root.iterdir()) == []


def test_provider_authorization_blocks_before_point_or_ledger_claim() -> None:
    with pytest.raises(FreeExecutionBoundaryError) as caught:
        authorize_provider_request(
            _blocked(),
            object(),  # type: ignore[arg-type]
            point_authority=object(),  # type: ignore[arg-type]
            predecessor=_blocked(),
            operation=_operation(),
            ledger=object(),  # type: ignore[arg-type]
            checked_at="2026-08-26T12:02:00Z",
        )
    assert "integration-blocked" in str(caught.value)


def test_self_resealed_positive_boundary_is_not_authority() -> None:
    payload = {
        "schema_version": 1,
        "admission_sha256": "a" * 64,
        "intent_sha256": "b" * 64,
        "ledger_root_authority_sha256": "c" * 64,
        "ledger_marker_sha256": "d" * 64,
        "status": FreeExecutionAdmissionStatus.ADMITTED.value,
        "provider_calls_allowed": True,
        "execution_slot_count": 1,
        "matrix_lane_count": 1,
        "deferred_lane_count": 0,
        "boundary_sha256": "",
    }
    with pytest.raises(FreeExecutionBoundaryError, match="integration-blocked"):
        FreeExecutionBoundaryV1.from_dict(payload)


def test_self_resealed_provider_authorization_is_not_authority() -> None:
    payload = {
        "schema_version": 1,
        "admission_sha256": "a" * 64,
        "point_of_use_sha256": "b" * 64,
        "operation_sha256": "c" * 64,
        "ledger_root_authority_sha256": "d" * 64,
        "ledger_marker_sha256": "e" * 64,
        "actual_job_id": 1,
        "logical_job_id": "extract",
        "lane_id": "lane-0",
        "authorized_at": "2026-08-26T12:02:00Z",
        "expires_at": "2026-08-26T12:03:00Z",
        "authorization_sha256": "",
    }
    with pytest.raises(FreeExecutionBoundaryError, match="integration-blocked"):
        ProviderRequestAuthorizationV1.from_dict(payload)


def test_operation_candidate_binds_exact_lane_endpoint_parameters_body_and_nonce() -> None:
    intent = ExecutionIntentV1.from_manifest_bytes(fixtures._manifest_bytes())
    operation = _operation()
    assert (
        runtime._normalize_authorized_operation(
            intent=intent,
            lane_id="lane-0",
            logical_job_id="extract",
            operation=operation,
        )
        == operation
    )
    for hostile in (
        _operation(nonce="lane-0-call-2"),
        replace(operation, endpoint_id="team_years", operation_sha256=""),
        replace(
            operation,
            request_url="https://stats.nba.com/stats/teamyearbyyearstats",
            operation_sha256="",
        ),
        replace(operation, safe_parameters_json='{"Season":"2021-22"}', operation_sha256=""),
    ):
        with pytest.raises(FreeExecutionBoundaryError, match="not exactly issued"):
            runtime._normalize_authorized_operation(
                intent=intent,
                lane_id="lane-0",
                logical_job_id="extract",
                operation=hostile,
            )
    with pytest.raises(FreeExecutionBoundaryError, match="foreign"):
        runtime._normalize_authorized_operation(
            intent=intent,
            lane_id="lane-1",
            logical_job_id="extract",
            operation=operation,
        )
    rebound = replace(operation, operation_kind="plan", operation_sha256="")
    manifest = json.loads(fixtures._manifest_bytes())
    manifest["lanes"][0]["operation_sha256s"] = [rebound.operation_sha256]
    manifest["github_matrix"]["include"][0]["operation_sha256s"] = [rebound.operation_sha256]
    rebound_intent = ExecutionIntentV1.from_manifest_bytes(fixtures.canonical_json_bytes(manifest))
    with pytest.raises(FreeExecutionBoundaryError, match="logical job"):
        runtime._normalize_authorized_operation(
            intent=rebound_intent,
            lane_id="lane-0",
            logical_job_id="extract",
            operation=rebound,
        )


def test_operation_candidate_renormalizes_mutated_frozen_instance() -> None:
    intent = ExecutionIntentV1.from_manifest_bytes(fixtures._manifest_bytes())
    operation = _operation()
    object.__setattr__(operation, "endpoint_id", "team_years")
    with pytest.raises(FreeExecutionBoundaryError, match="invalid"):
        runtime._normalize_authorized_operation(
            intent=intent,
            lane_id="lane-0",
            logical_job_id="extract",
            operation=operation,
        )


def test_load_blocked_admission_uses_no_follow_bounded_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "admission.json"
    blocked = _blocked()
    path.write_bytes(blocked.to_bytes())
    assert load_free_execution_admission(path) == blocked
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(FreeExecutionBoundaryError, match="opened safely"):
        load_free_execution_admission(link)


def test_ledger_constructor_requires_repository_owned_authority_type(tmp_path: Path) -> None:
    path = tmp_path / "ledger"
    path.mkdir()
    with pytest.raises(FreeExecutionBoundaryError, match="exact restored root authority"):
        AtomicFileReplayLedgerV1(path)  # type: ignore[arg-type]
