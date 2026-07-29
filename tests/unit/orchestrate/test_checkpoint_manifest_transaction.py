from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from nbadb.orchestrate.full_extraction_control import (
    FullExtractionChainState,
    _checkpoint_pointer,
    build_checkpoint_database,
    build_checkpoint_transaction,
    build_resume_manifest,
    commit_checkpoint_manifest,
    manifest_payload,
    normalize_manifest,
    validate_checkpoint_artifact,
)

if TYPE_CHECKING:
    from pathlib import Path

_CHAIN_ID = "transaction-chain"
_RUN_ID = "12345"
_SOURCE_SHA = "a" * 40
_ARTIFACT_DIGEST = "sha256:" + "b" * 64


def _write_candidate_manifest(
    path: Path,
    *,
    chain_state: FullExtractionChainState,
) -> None:
    payload = manifest_payload([], chain_state=chain_state)
    payload.update(
        {
            "chain_id": _CHAIN_ID,
            "workflow_source_sha": _SOURCE_SHA,
        }
    )
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _build_generation(
    tmp_path: Path,
    *,
    manifest_path: Path,
    generation: int,
    previous_checkpoint_dir: Path | None = None,
    previous_checkpoint_report_path: Path | None = None,
) -> tuple[Path, Path, Path]:
    metadata_dir = tmp_path / f"metadata-{generation}"
    artifacts_dir = tmp_path / f"lanes-{generation}"
    checkpoint_dir = tmp_path / f"checkpoint-{generation}"
    report_path = tmp_path / f"checkpoint-report-{generation}.json"
    transaction_path = tmp_path / f"checkpoint-transaction-{generation}.json"
    metadata_dir.mkdir()
    artifacts_dir.mkdir()
    artifact_name = f"full-extraction-checkpoint-{_CHAIN_ID}-iter-{generation}"
    build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=artifacts_dir,
        output_dir=checkpoint_dir,
        report_path=report_path,
        previous_checkpoint_dir=previous_checkpoint_dir,
        previous_checkpoint_report_path=previous_checkpoint_report_path,
        chain_id=_CHAIN_ID,
        run_id=_RUN_ID,
        source_sha=_SOURCE_SHA,
        checkpoint_generation=generation,
        checkpoint_artifact_name=artifact_name,
    )
    database_path = checkpoint_dir / "nba.duckdb"
    build_checkpoint_transaction(
        manifest_path=manifest_path,
        checkpoint_report_path=report_path,
        checkpoint_database_path=database_path,
        output_path=transaction_path,
        chain_id=_CHAIN_ID,
        run_id=_RUN_ID,
        source_sha=_SOURCE_SHA,
        checkpoint_generation=generation,
        checkpoint_artifact_name=artifact_name,
    )
    return checkpoint_dir, report_path, transaction_path


def _commit_generation(
    tmp_path: Path,
    *,
    manifest_path: Path,
    checkpoint_dir: Path,
    report_path: Path,
    transaction_path: Path,
    generation: int,
    run_id: str = _RUN_ID,
) -> Path:
    output_path = tmp_path / f"committed-manifest-{generation}.json"
    commit_checkpoint_manifest(
        manifest_path=manifest_path,
        checkpoint_transaction_path=transaction_path,
        checkpoint_report_path=report_path,
        checkpoint_database_path=checkpoint_dir / "nba.duckdb",
        output_path=output_path,
        chain_id=_CHAIN_ID,
        run_id=run_id,
        source_sha=_SOURCE_SHA,
        artifact_id=1000 + generation,
        artifact_digest=_ARTIFACT_DIGEST,
        artifact_size_bytes=4096 + generation,
    )
    return output_path


def test_checkpoint_pointer_commits_only_after_verified_receipt(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    _write_candidate_manifest(
        candidate_path,
        chain_state=FullExtractionChainState(artifact_run_ids=(_RUN_ID,)),
    )
    checkpoint_dir, report_path, transaction_path = _build_generation(
        tmp_path,
        manifest_path=candidate_path,
        generation=1,
    )

    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert candidate["chain_state"]["latest_checkpoint_generation"] == 0

    committed_path = _commit_generation(
        tmp_path,
        manifest_path=candidate_path,
        checkpoint_dir=checkpoint_dir,
        report_path=report_path,
        transaction_path=transaction_path,
        generation=1,
    )
    committed = json.loads(committed_path.read_text(encoding="utf-8"))
    state = committed["chain_state"]
    assert state["latest_checkpoint_generation"] == 1
    assert state["latest_checkpoint_transaction"]["state"] == "committed"
    assert state["latest_checkpoint_transaction"]["receipt"]["artifact_id"] == 1001

    verified = validate_checkpoint_artifact(
        manifest_path=committed_path,
        checkpoint_dir=checkpoint_dir,
        checkpoint_report_path=report_path,
        chain_id=_CHAIN_ID,
        source_sha=_SOURCE_SHA,
    )
    assert verified["checkpoint_generation"] == 1
    assert verified["artifact_receipt"]["artifact_id"] == 1001


def test_checkpoint_commit_rolls_transaction_forward_copy_plus_delta(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    _write_candidate_manifest(
        candidate_path,
        chain_state=FullExtractionChainState(artifact_run_ids=(_RUN_ID,)),
    )
    checkpoint_one, report_one, transaction_one = _build_generation(
        tmp_path,
        manifest_path=candidate_path,
        generation=1,
    )
    committed_one = _commit_generation(
        tmp_path,
        manifest_path=candidate_path,
        checkpoint_dir=checkpoint_one,
        report_path=report_one,
        transaction_path=transaction_one,
        generation=1,
    )

    committed_one_manifest = normalize_manifest(
        json.loads(committed_one.read_text(encoding="utf-8"))
    )
    resume_metadata = tmp_path / "resume-metadata"
    resume_metadata.mkdir()
    _next_lanes, resumed_chain_state, _summary = build_resume_manifest(
        list(committed_one_manifest.lanes),
        resume_metadata,
        chain_state=committed_one_manifest.chain_state,
        current_iteration=2,
    )
    assert resumed_chain_state.latest_checkpoint_transaction is not None
    resumed_candidate = tmp_path / "resumed-candidate.json"
    _write_candidate_manifest(
        resumed_candidate,
        chain_state=resumed_chain_state,
    )

    checkpoint_two, report_two, transaction_two = _build_generation(
        tmp_path,
        manifest_path=resumed_candidate,
        generation=2,
        previous_checkpoint_dir=checkpoint_one,
        previous_checkpoint_report_path=report_one,
    )
    committed_two = _commit_generation(
        tmp_path,
        manifest_path=resumed_candidate,
        checkpoint_dir=checkpoint_two,
        report_path=report_two,
        transaction_path=transaction_two,
        generation=2,
    )
    state = json.loads(committed_two.read_text(encoding="utf-8"))["chain_state"]
    assert state["latest_checkpoint_generation"] == 2
    assert state["previous_checkpoint_generation"] == 1
    assert state["latest_checkpoint_transaction"]["state"] == "committed"
    assert state["previous_checkpoint_transaction"]["state"] == "committed"
    assert (
        checkpoint_one.joinpath("nba.duckdb").read_bytes()
        == checkpoint_two.joinpath("nba.duckdb").read_bytes()
    )


def test_checkpoint_pointer_rejects_transaction_without_flat_identity(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    _write_candidate_manifest(
        candidate_path,
        chain_state=FullExtractionChainState(artifact_run_ids=(_RUN_ID,)),
    )
    checkpoint_dir, report_path, transaction_path = _build_generation(
        tmp_path,
        manifest_path=candidate_path,
        generation=1,
    )
    committed_path = _commit_generation(
        tmp_path,
        manifest_path=candidate_path,
        checkpoint_dir=checkpoint_dir,
        report_path=report_path,
        transaction_path=transaction_path,
        generation=1,
    )
    committed_state = json.loads(committed_path.read_text(encoding="utf-8"))["chain_state"]

    with pytest.raises(ValueError, match="transaction together"):
        _checkpoint_pointer(
            FullExtractionChainState(
                latest_checkpoint_transaction=committed_state["latest_checkpoint_transaction"]
            ),
            prefix="latest",
            chain_id=_CHAIN_ID,
        )


def test_checkpoint_pointer_accepts_complete_legacy_flat_identity() -> None:
    pointer = _checkpoint_pointer(
        FullExtractionChainState(
            latest_checkpoint_run_id=_RUN_ID,
            latest_checkpoint_artifact_name=(f"full-extraction-checkpoint-{_CHAIN_ID}-iter-1"),
            latest_checkpoint_generation=1,
            latest_checkpoint_coverage_hash="c" * 64,
        ),
        prefix="latest",
        chain_id=_CHAIN_ID,
    )

    assert pointer is not None
    assert pointer.transaction is None


@pytest.mark.parametrize("prefix", ["latest", "previous"])
@pytest.mark.parametrize("malformed_transaction", [None, "", []])
def test_manifest_rejects_present_malformed_transaction_instead_of_legacy_fallback(
    prefix: str,
    malformed_transaction: object,
) -> None:
    state = FullExtractionChainState(
        **{
            f"{prefix}_checkpoint_run_id": _RUN_ID,
            f"{prefix}_checkpoint_artifact_name": (
                f"full-extraction-checkpoint-{_CHAIN_ID}-iter-1"
            ),
            f"{prefix}_checkpoint_generation": 1,
            f"{prefix}_checkpoint_coverage_hash": "c" * 64,
        }
    )
    payload = manifest_payload([], chain_state=state)
    payload["chain_state"][f"{prefix}_checkpoint_transaction"] = malformed_transaction

    with pytest.raises(ValueError, match="transaction must be an object"):
        normalize_manifest(payload)


def test_manifest_accepts_transaction_absent_legacy_pointer() -> None:
    state = FullExtractionChainState(
        latest_checkpoint_run_id=_RUN_ID,
        latest_checkpoint_artifact_name=(f"full-extraction-checkpoint-{_CHAIN_ID}-iter-1"),
        latest_checkpoint_generation=1,
        latest_checkpoint_coverage_hash="c" * 64,
    )
    payload = manifest_payload([], chain_state=state)

    assert "latest_checkpoint_transaction" not in payload["chain_state"]
    assert normalize_manifest(payload).chain_state == state


def test_checkpoint_restore_rejects_transaction_inventory_not_in_report(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    _write_candidate_manifest(
        candidate_path,
        chain_state=FullExtractionChainState(artifact_run_ids=(_RUN_ID,)),
    )
    checkpoint_dir, report_path, transaction_path = _build_generation(
        tmp_path,
        manifest_path=candidate_path,
        generation=1,
    )
    committed_path = _commit_generation(
        tmp_path,
        manifest_path=candidate_path,
        checkpoint_dir=checkpoint_dir,
        report_path=report_path,
        transaction_path=transaction_path,
        generation=1,
    )
    committed = json.loads(committed_path.read_text(encoding="utf-8"))
    transaction = committed["chain_state"]["latest_checkpoint_transaction"]
    forged_lanes = [
        {
            "lane_id": "forged-lane",
            "coverage_units_hash": "c" * 64,
        }
    ]
    forged_inventory_sha256 = hashlib.sha256(
        json.dumps(
            forged_lanes,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    transaction["identity"]["coverage"]["lanes"] = forged_lanes
    transaction["identity"]["coverage"]["lane_inventory_sha256"] = forged_inventory_sha256
    transaction["receipt"]["lane_inventory_sha256"] = forged_inventory_sha256
    committed_path.write_text(
        json.dumps(committed, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="lane inventory does not match its transaction"):
        validate_checkpoint_artifact(
            manifest_path=committed_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=report_path,
            chain_id=_CHAIN_ID,
            source_sha=_SOURCE_SHA,
        )


def test_checkpoint_commit_rejects_post_build_report_mutation(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    _write_candidate_manifest(
        candidate_path,
        chain_state=FullExtractionChainState(artifact_run_ids=(_RUN_ID,)),
    )
    checkpoint_dir, report_path, transaction_path = _build_generation(
        tmp_path,
        manifest_path=candidate_path,
        generation=1,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["active_lane_count"] = 99
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="report changed"):
        _commit_generation(
            tmp_path,
            manifest_path=candidate_path,
            checkpoint_dir=checkpoint_dir,
            report_path=report_path,
            transaction_path=transaction_path,
            generation=1,
        )


def test_checkpoint_commit_rejects_post_build_database_mutation(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    _write_candidate_manifest(
        candidate_path,
        chain_state=FullExtractionChainState(artifact_run_ids=(_RUN_ID,)),
    )
    checkpoint_dir, report_path, transaction_path = _build_generation(
        tmp_path,
        manifest_path=candidate_path,
        generation=1,
    )
    database_path = checkpoint_dir / "nba.duckdb"
    with database_path.open("ab") as database:
        database.write(b"post-build mutation")

    with pytest.raises(ValueError, match="database changed"):
        _commit_generation(
            tmp_path,
            manifest_path=candidate_path,
            checkpoint_dir=checkpoint_dir,
            report_path=report_path,
            transaction_path=transaction_path,
            generation=1,
        )


def test_checkpoint_commit_rejects_report_from_different_run(
    tmp_path: Path,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    _write_candidate_manifest(
        candidate_path,
        chain_state=FullExtractionChainState(artifact_run_ids=(_RUN_ID,)),
    )
    checkpoint_dir, report_path, transaction_path = _build_generation(
        tmp_path,
        manifest_path=candidate_path,
        generation=1,
    )

    with pytest.raises(ValueError, match="report run_id does not match"):
        _commit_generation(
            tmp_path,
            manifest_path=candidate_path,
            checkpoint_dir=checkpoint_dir,
            report_path=report_path,
            transaction_path=transaction_path,
            generation=1,
            run_id="54321",
        )


@pytest.mark.parametrize(
    ("report_updates", "error_match"),
    [
        (
            {"coverage_fingerprint": "c" * 64},
            "coverage fingerprint does not match",
        ),
        (
            {
                "included_lane_ids": ["fabricated-lane"],
                "included_lane_coverage_hashes": {"fabricated-lane": "d" * 64},
            },
            "lane inventory is absent from the manifest",
        ),
    ],
)
def test_checkpoint_transaction_recomputes_manifest_coverage_identity(
    tmp_path: Path,
    report_updates: dict[str, object],
    error_match: str,
) -> None:
    candidate_path = tmp_path / "candidate.json"
    _write_candidate_manifest(
        candidate_path,
        chain_state=FullExtractionChainState(artifact_run_ids=(_RUN_ID,)),
    )
    checkpoint_dir, report_path, _transaction_path = _build_generation(
        tmp_path,
        manifest_path=candidate_path,
        generation=1,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.update(report_updates)
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error_match):
        build_checkpoint_transaction(
            manifest_path=candidate_path,
            checkpoint_report_path=report_path,
            checkpoint_database_path=checkpoint_dir / "nba.duckdb",
            output_path=tmp_path / "tampered-transaction.json",
            chain_id=_CHAIN_ID,
            run_id=_RUN_ID,
            source_sha=_SOURCE_SHA,
            checkpoint_generation=1,
            checkpoint_artifact_name=(f"full-extraction-checkpoint-{_CHAIN_ID}-iter-1"),
        )
