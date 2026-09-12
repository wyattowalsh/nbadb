from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nbadb.cli.app import app
from nbadb.orchestrate.recurring_evidence import (
    FreshnessDecision,
    RecurringRunPhase,
    RecurringRunStatusReason,
    RecurringRunStatusV1,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNNER = CliRunner()
_SOURCE_SHA = hashlib.sha1(b"recurring status source", usedforsecurity=False).hexdigest()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _proof_path(output_path: Path) -> Path:
    return output_path.with_name("pre-extraction-no-mutation-proof.json")


def _required_args(output_path: Path) -> list[str]:
    return [
        "recurring-status",
        "--output-path",
        str(output_path),
        "--source-sha",
        _SOURCE_SHA,
        "--actions-run-id",
        "9001",
        "--actions-run-attempt",
        "1",
        "--expected-prior-nba-date",
        "2026-08-25",
        "--timezone",
        "America/New_York",
        "--provider-availability-cutoff",
        "2026-08-26T10:00:00Z",
        "--scheduled-deadline",
        "2026-08-26T13:00:00Z",
        "--actual-completion",
        "2026-08-26T10:02:00Z",
        "--dataset-ref",
        "trusted-owner/nbadb",
        "--workflow-result",
        "failure",
        "--checkout-outcome",
        "success",
        "--pre-extraction-no-mutation-proof-path",
        str(_proof_path(output_path)),
    ]


def _read_status(path: Path) -> RecurringRunStatusV1:
    return RecurringRunStatusV1.from_bytes(path.read_bytes())


def test_parent_version_absence_emits_truthful_pre_extraction_status(tmp_path: Path) -> None:
    output = tmp_path / "recurring-run-status.json"

    result = _RUNNER.invoke(app, _required_args(output))

    assert result.exit_code == 0, result.output
    status = _read_status(output)
    assert status.freshness is FreshnessDecision.NOT_FRESH
    assert status.phase is RecurringRunPhase.PRE_EXTRACTION
    assert status.reason is RecurringRunStatusReason.PARENT_ADMISSION_FAILED
    assert status.parent_dataset_version is None
    assert status.latest_assured_remote_version is None
    assert status.no_mutation_proven is True
    proof_bytes = _proof_path(output).read_bytes()
    assert status.no_mutation_proof_sha256 == hashlib.sha256(proof_bytes).hexdigest()
    proof = json.loads(proof_bytes)
    assert proof["kind"] == "recurring_pre_extraction_no_mutation_proof"
    assert proof["proof_basis"] == "workflow_control_flow_and_exact_step_outcomes"
    assert proof["outcomes"]["parent"] == "unknown"
    assert proof["outcomes"]["extraction"] == "unknown"
    assert status.provider_mutation_count == 0
    assert status.kaggle_mutation_count == 0


def test_pre_extraction_failure_requires_no_mutation_proof(tmp_path: Path) -> None:
    output = tmp_path / "recurring-run-status.json"
    args = _required_args(output)
    proof_index = args.index("--pre-extraction-no-mutation-proof-path")
    del args[proof_index : proof_index + 2]

    result = _RUNNER.invoke(app, args)

    assert result.exit_code == 1
    assert "requires a no-mutation proof output path" in result.output
    assert not output.exists()


def test_pre_extraction_proof_rejects_reached_downstream_step(tmp_path: Path) -> None:
    output = tmp_path / "recurring-run-status.json"
    args = _required_args(output)
    args.extend(["--extraction-outcome", "success"])

    result = _RUNNER.invoke(app, args)

    assert result.exit_code == 1
    assert "conflicts with reached downstream steps: extraction" in result.output
    assert not output.exists()
    assert not _proof_path(output).exists()


def test_unknown_capacity_does_not_invent_capacity_block(tmp_path: Path) -> None:
    output = tmp_path / "recurring-run-status.json"
    args = _required_args(output)
    args.extend(
        [
            "--parent-outcome",
            "success",
            "--parent-dataset-version",
            "41",
        ]
    )

    result = _RUNNER.invoke(app, args)

    assert result.exit_code == 0, result.output
    status = _read_status(output)
    assert status.reason is RecurringRunStatusReason.EXTRACTION_INCOMPLETE
    assert status.phase is RecurringRunPhase.EXTRACTION
    assert status.no_mutation_proven is False
    assert not _proof_path(output).exists()


def test_successful_steps_without_terminal_receipts_never_imply_fresh(tmp_path: Path) -> None:
    output = tmp_path / "recurring-run-status.json"
    args = _required_args(output)
    workflow_index = args.index("failure")
    args[workflow_index] = "success"
    args.extend(
        [
            "--parent-outcome",
            "success",
            "--capacity-outcome",
            "success",
            "--extraction-outcome",
            "success",
            "--assurance-outcome",
            "success",
            "--publication-outcome",
            "success",
            "--readback-outcome",
            "success",
            "--parent-dataset-version",
            "41",
        ]
    )

    result = _RUNNER.invoke(app, args)

    assert result.exit_code == 0, result.output
    status = _read_status(output)
    assert status.freshness is FreshnessDecision.NOT_FRESH
    assert status.phase is RecurringRunPhase.PUBLICATION
    assert status.reason is RecurringRunStatusReason.READBACK_FAILED
    assert status.parent_dataset_version == 41
    assert status.finalizer_always_ran is True


def test_complete_exact_terminal_evidence_can_emit_fresh(tmp_path: Path) -> None:
    output = tmp_path / "recurring-run-status.json"
    args = _required_args(output)
    workflow_index = args.index("failure")
    args[workflow_index] = "success"
    args.extend(
        [
            "--parent-outcome",
            "success",
            "--capacity-outcome",
            "success",
            "--extraction-outcome",
            "success",
            "--assurance-outcome",
            "success",
            "--publication-outcome",
            "success",
            "--readback-outcome",
            "success",
            "--parent-dataset-version",
            "41",
            "--parent-cutoff",
            "2026-08-25T09:00:00Z",
            "--parent-fingerprint-sha256",
            _sha("parent"),
            "--latest-assured-remote-version",
            "42",
            "--latest-assured-remote-cutoff",
            "2026-08-26T09:00:00Z",
            "--update-transaction-id",
            _sha("transaction"),
            "--coordinator-identity-sha256",
            _sha("coordinator"),
            "--candidate-identity-sha256",
            _sha("candidate"),
            "--request-closure-sha256",
            _sha("closure"),
            "--publication-readback-sha256",
            _sha("readback"),
            "--provider-mutation-count",
            "12",
            "--kaggle-mutation-count",
            "1",
            "--fresh-reason",
            "update_published_and_read_back",
        ]
    )

    result = _RUNNER.invoke(app, args)

    assert result.exit_code == 0, result.output
    status = _read_status(output)
    assert status.freshness is FreshnessDecision.FRESH
    assert status.phase is RecurringRunPhase.COMPLETE
    assert status.reason is RecurringRunStatusReason.UPDATE_PUBLISHED_AND_READ_BACK
    assert status.parent_dataset_version == 41
    assert status.latest_assured_remote_version == 42
    assert status.kaggle_mutation_count == 1


def test_recurring_status_rejects_symlink_output(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("unchanged\n", encoding="utf-8")
    output = tmp_path / "recurring-run-status.json"
    output.symlink_to(target)

    result = _RUNNER.invoke(app, _required_args(output))

    assert result.exit_code == 1
    assert "must not be a symlink" in result.output
    assert target.read_text(encoding="utf-8") == "unchanged\n"


def test_recurring_status_rejects_symlink_proof_output(tmp_path: Path) -> None:
    target = tmp_path / "proof-target.json"
    target.write_text("unchanged\n", encoding="utf-8")
    proof = tmp_path / "pre-extraction-no-mutation-proof.json"
    proof.symlink_to(target)
    output = tmp_path / "recurring-run-status.json"

    result = _RUNNER.invoke(app, _required_args(output))

    assert result.exit_code == 1
    assert "proof path must not be a symlink" in result.output
    assert target.read_text(encoding="utf-8") == "unchanged\n"
    assert not output.exists()


@pytest.mark.parametrize("workflow_name", ["daily-update.yml", "monthly-update.yml"])
def test_recurring_workflow_has_always_run_status_finalizer(workflow_name: str) -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")

    assert "recurring_status:" in workflow
    finalizer = workflow.split("  recurring_status:\n", 1)[1]
    assert "    if: always()" in finalizer
    assert "uv run nbadb recurring-status" in finalizer
    assert "--workflow-result" in finalizer
    assert "--parent-dataset-version" in finalizer
    assert "--capacity-outcome unknown" in finalizer
    assert "--pre-extraction-no-mutation-proof-path" in finalizer
    assert "--fresh-reason" not in finalizer
    assert 'if [[ -z "$EXPECTED_PRIOR_NBA_DATE" ]]' in finalizer
    assert 'if [[ -z "$PROVIDER_AVAILABILITY_CUTOFF" ]]' in finalizer
    assert 'if [[ -z "$SCHEDULED_DEADLINE" ]]' in finalizer
    assert "Upload recurring run status" in finalizer
    assert "if: always()" in finalizer.split("Upload recurring run status", 1)[1]
    assert "if-no-files-found: error" in finalizer
    assert "Upload pre-extraction no-mutation proof" in finalizer


@pytest.mark.parametrize("workflow_name", ["daily-update.yml", "monthly-update.yml"])
def test_recurring_workflow_requires_explicit_exact_parent_version(workflow_name: str) -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")

    assert "NBADB_KAGGLE_PARENT_DATASET_VERSION" in workflow
    assert "NBADB_KAGGLE_DATASET: ${{ vars.NBADB_KAGGLE_DATASET" in workflow
    assert "NBADB_KAGGLE_PARENT_CUTOFF" not in workflow
    assert "NBADB_KAGGLE_PARENT_FINGERPRINT_SHA256" not in workflow
    assert "capacity_outcome: ${{ steps.vpn.outcome }}" not in workflow
    assert '--dataset-version "$EXACT_PARENT_DATASET_VERSION"' in workflow
    assert "Download latest from Kaggle" not in workflow
    assert "_pipeline_watermarks" not in workflow
