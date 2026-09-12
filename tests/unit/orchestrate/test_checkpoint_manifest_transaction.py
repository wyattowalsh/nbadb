from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from nbadb.contracts.assurance_admission import AssuranceAdmission
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.orchestrate.checkpoint_contract import (
    CheckpointContractError,
    CheckpointTransaction,
    CheckpointTransitionError,
    CheckpointW2AuthorityIdentity,
)
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
    from typing import Any

_CHAIN_ID = "transaction-chain"
_RUN_ID = "12345"
_SOURCE_SHA = "a" * 40
_ARTIFACT_DIGEST = "sha256:" + "b" * 64


def _assurance_admission() -> AssuranceAdmission:
    authority = expected_nba_api_provider_authority()
    return AssuranceAdmission(
        source_sha=_SOURCE_SHA,
        assurance_manifest_sha256="1" * 64,
        generation_semantic_sha256="2" * 64,
        provider_evidence_sha256=str(authority["provider_evidence_sha256"]),
        provider_authority_sha256=str(authority["authority_sha256"]),
        authority_semantic_diff_sha256="3" * 64,
        authority_update_mode="full",
        first_extraction=True,
        model_status="GREEN",
    )


def _write_candidate_manifest(
    path: Path,
    *,
    chain_state: FullExtractionChainState,
) -> None:
    payload = manifest_payload(
        [],
        assurance_admission=_assurance_admission(),
        chain_id=_CHAIN_ID,
        chain_state=chain_state,
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
    run_attempt: str = "1",
    artifact_id: int | None = None,
    artifact_digest: str = _ARTIFACT_DIGEST,
    artifact_size_bytes: int | None = None,
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
        run_attempt=run_attempt,
        source_sha=_SOURCE_SHA,
        artifact_id=artifact_id if artifact_id is not None else 1000 + generation,
        artifact_digest=artifact_digest,
        artifact_size_bytes=(
            artifact_size_bytes if artifact_size_bytes is not None else 4096 + generation
        ),
    )
    return output_path


def _prepare_roll_forward(
    tmp_path: Path,
) -> tuple[Path, bytes, Path, Path, Path, Path]:
    initial_candidate = tmp_path / "initial-candidate.json"
    _write_candidate_manifest(
        initial_candidate,
        chain_state=FullExtractionChainState(artifact_run_ids=(_RUN_ID,)),
    )
    checkpoint_one, report_one, transaction_one = _build_generation(
        tmp_path,
        manifest_path=initial_candidate,
        generation=1,
    )
    committed_one = _commit_generation(
        tmp_path,
        manifest_path=initial_candidate,
        checkpoint_dir=checkpoint_one,
        report_path=report_one,
        transaction_path=transaction_one,
        generation=1,
    )
    committed_one_bytes = committed_one.read_bytes()
    committed_manifest = normalize_manifest(json.loads(committed_one.read_text(encoding="utf-8")))
    next_candidate = tmp_path / "next-candidate.json"
    _write_candidate_manifest(
        next_candidate,
        chain_state=committed_manifest.chain_state,
    )
    checkpoint_two, report_two, transaction_two = _build_generation(
        tmp_path,
        manifest_path=next_candidate,
        generation=2,
        previous_checkpoint_dir=checkpoint_one,
        previous_checkpoint_report_path=report_one,
    )
    return (
        committed_one,
        committed_one_bytes,
        next_candidate,
        checkpoint_two,
        report_two,
        transaction_two,
    )


def _assert_prior_pointer_is_authoritative(
    *,
    committed_manifest_path: Path,
    committed_manifest_bytes: bytes,
    candidate_manifest_path: Path,
) -> None:
    assert committed_manifest_path.read_bytes() == committed_manifest_bytes
    for manifest_path in (committed_manifest_path, candidate_manifest_path):
        manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
        pointer = _checkpoint_pointer(
            manifest.chain_state,
            prefix="latest",
            chain_id=_CHAIN_ID,
        )
        assert pointer is not None
        assert pointer.generation == 1
        assert pointer.transaction is not None
        assert pointer.transaction.committed_receipt.artifact_id == 1001


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


def test_checkpoint_transaction_retains_exact_w2_authority_through_commit(
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
    expected_w2 = CheckpointW2AuthorityIdentity.from_report(report)
    built = CheckpointTransaction.from_dict(
        json.loads(transaction_path.read_text(encoding="utf-8"))
    )

    assert built.build is not None
    assert built.build.w2_authority == expected_w2
    assert built.to_dict()["schema_version"] == 3

    committed_path = _commit_generation(
        tmp_path,
        manifest_path=candidate_path,
        checkpoint_dir=checkpoint_dir,
        report_path=report_path,
        transaction_path=transaction_path,
        generation=1,
    )
    committed_payload = json.loads(committed_path.read_text(encoding="utf-8"))
    committed = CheckpointTransaction.from_dict(
        committed_payload["chain_state"]["latest_checkpoint_transaction"]
    )

    assert committed.build is not None
    assert committed.build.w2_authority == expected_w2
    assert committed.committed_receipt.w2_authority_identity_sha256 == expected_w2.identity_sha256


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "partial",
        "altered",
        "foreign",
        "legacy",
    ],
)
def test_checkpoint_commit_rejects_invalid_w2_transaction_identity(
    tmp_path: Path,
    mutation: str,
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
    transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
    w2_payload = transaction["build"]["w2_authority"]
    if mutation == "missing":
        transaction["build"].pop("w2_authority")
    elif mutation == "partial":
        w2_payload.pop("w2_expected_call_inventory_sha256")
    elif mutation == "altered":
        w2_payload["w2_authority_identity_sha256"] = "0" * 64
    elif mutation == "foreign":
        current = CheckpointW2AuthorityIdentity.from_dict(w2_payload)
        foreign = replace(
            current,
            expected_call_inventory_sha256="0" * 64,
            identity_sha256="",
        )
        transaction["build"]["w2_authority"] = foreign.to_dict()
    else:
        transaction["schema_version"] = 1
    transaction_path.write_text(json.dumps(transaction) + "\n", encoding="utf-8")

    with pytest.raises((CheckpointContractError, ValueError), match="W2|w2|schema version"):
        _commit_generation(
            tmp_path,
            manifest_path=candidate_path,
            checkpoint_dir=checkpoint_dir,
            report_path=report_path,
            transaction_path=transaction_path,
            generation=1,
        )


def test_checkpoint_restore_rejects_receipt_with_foreign_w2_identity(
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
    receipt = committed["chain_state"]["latest_checkpoint_transaction"]["receipt"]
    receipt["w2_authority_identity_sha256"] = "0" * 64
    committed_path.write_text(json.dumps(committed) + "\n", encoding="utf-8")

    with pytest.raises(CheckpointContractError, match="w2_authority_identity_sha256"):
        validate_checkpoint_artifact(
            manifest_path=committed_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=report_path,
            chain_id=_CHAIN_ID,
            source_sha=_SOURCE_SHA,
        )


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
    state_kwargs: dict[str, Any] = {
        f"{prefix}_checkpoint_run_id": _RUN_ID,
        f"{prefix}_checkpoint_artifact_name": (f"full-extraction-checkpoint-{_CHAIN_ID}-iter-1"),
        f"{prefix}_checkpoint_generation": 1,
        f"{prefix}_checkpoint_coverage_hash": "c" * 64,
    }
    state = FullExtractionChainState(**state_kwargs)
    payload = manifest_payload(
        [],
        assurance_admission=_assurance_admission(),
        chain_id=_CHAIN_ID,
        chain_state=state,
    )
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
    payload = manifest_payload(
        [],
        assurance_admission=_assurance_admission(),
        chain_id=_CHAIN_ID,
        chain_state=state,
    )

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


def test_candidate_and_built_transaction_keep_prior_pointer_authoritative(
    tmp_path: Path,
) -> None:
    (
        committed_one,
        committed_one_bytes,
        next_candidate,
        _checkpoint_two,
        _report_two,
        transaction_two,
    ) = _prepare_roll_forward(tmp_path)
    transaction = CheckpointTransaction.from_dict(
        json.loads(transaction_two.read_text(encoding="utf-8"))
    )

    with pytest.raises(CheckpointTransitionError, match="expected uploaded_verified"):
        transaction.commit()

    assert not tmp_path.joinpath("committed-manifest-2.json").exists()
    _assert_prior_pointer_is_authoritative(
        committed_manifest_path=committed_one,
        committed_manifest_bytes=committed_one_bytes,
        candidate_manifest_path=next_candidate,
    )


def test_invalid_candidate_generation_does_not_advance_prior_pointer(
    tmp_path: Path,
) -> None:
    (
        committed_one,
        committed_one_bytes,
        next_candidate,
        checkpoint_two,
        report_two,
        _transaction_two,
    ) = _prepare_roll_forward(tmp_path)
    invalid_transaction_path = tmp_path / "invalid-candidate-transaction.json"

    with pytest.raises(ValueError, match="immediately follow"):
        build_checkpoint_transaction(
            manifest_path=next_candidate,
            checkpoint_report_path=report_two,
            checkpoint_database_path=checkpoint_two / "nba.duckdb",
            output_path=invalid_transaction_path,
            chain_id=_CHAIN_ID,
            run_id=_RUN_ID,
            source_sha=_SOURCE_SHA,
            checkpoint_generation=3,
            checkpoint_artifact_name=(f"full-extraction-checkpoint-{_CHAIN_ID}-iter-3"),
        )

    assert not invalid_transaction_path.exists()
    assert not tmp_path.joinpath("committed-manifest-2.json").exists()
    _assert_prior_pointer_is_authoritative(
        committed_manifest_path=committed_one,
        committed_manifest_bytes=committed_one_bytes,
        candidate_manifest_path=next_candidate,
    )


@pytest.mark.parametrize(
    ("mutated_member", "error_match"),
    [
        ("database", "database changed"),
        ("report", "report changed"),
    ],
)
def test_post_build_content_failure_preserves_prior_pointer(
    tmp_path: Path,
    mutated_member: str,
    error_match: str,
) -> None:
    (
        committed_one,
        committed_one_bytes,
        next_candidate,
        checkpoint_two,
        report_two,
        transaction_two,
    ) = _prepare_roll_forward(tmp_path)
    if mutated_member == "database":
        with checkpoint_two.joinpath("nba.duckdb").open("ab") as database:
            database.write(b"post-build mutation")
    else:
        report = json.loads(report_two.read_text(encoding="utf-8"))
        report["active_lane_count"] = 999
        report_two.write_text(json.dumps(report) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error_match):
        _commit_generation(
            tmp_path,
            manifest_path=next_candidate,
            checkpoint_dir=checkpoint_two,
            report_path=report_two,
            transaction_path=transaction_two,
            generation=2,
        )

    assert not tmp_path.joinpath("committed-manifest-2.json").exists()
    _assert_prior_pointer_is_authoritative(
        committed_manifest_path=committed_one,
        committed_manifest_bytes=committed_one_bytes,
        candidate_manifest_path=next_candidate,
    )


@pytest.mark.parametrize(
    ("artifact_id", "artifact_digest", "artifact_size_bytes", "error_match"),
    [
        (0, _ARTIFACT_DIGEST, 4098, "artifact_id"),
        (1002, "sha256:" + "B" * 64, 4098, "artifact_digest"),
        (1002, _ARTIFACT_DIGEST, 0, "artifact_size_bytes"),
    ],
)
def test_invalid_receipt_cannot_advance_prior_pointer(
    tmp_path: Path,
    artifact_id: int,
    artifact_digest: str,
    artifact_size_bytes: int,
    error_match: str,
) -> None:
    (
        committed_one,
        committed_one_bytes,
        next_candidate,
        checkpoint_two,
        report_two,
        transaction_two,
    ) = _prepare_roll_forward(tmp_path)

    with pytest.raises(ValueError, match=error_match):
        _commit_generation(
            tmp_path,
            manifest_path=next_candidate,
            checkpoint_dir=checkpoint_two,
            report_path=report_two,
            transaction_path=transaction_two,
            generation=2,
            artifact_id=artifact_id,
            artifact_digest=artifact_digest,
            artifact_size_bytes=artifact_size_bytes,
        )

    assert not tmp_path.joinpath("committed-manifest-2.json").exists()
    _assert_prior_pointer_is_authoritative(
        committed_manifest_path=committed_one,
        committed_manifest_bytes=committed_one_bytes,
        candidate_manifest_path=next_candidate,
    )


def test_commit_rejects_built_transaction_from_wrong_source_without_advancing(
    tmp_path: Path,
) -> None:
    (
        committed_one,
        committed_one_bytes,
        next_candidate,
        checkpoint_two,
        report_two,
        transaction_two,
    ) = _prepare_roll_forward(tmp_path)
    transaction = json.loads(transaction_two.read_text(encoding="utf-8"))
    transaction["identity"]["source_sha"] = "0" * 40
    transaction_two.write_text(json.dumps(transaction) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="transaction source SHA does not match"):
        _commit_generation(
            tmp_path,
            manifest_path=next_candidate,
            checkpoint_dir=checkpoint_two,
            report_path=report_two,
            transaction_path=transaction_two,
            generation=2,
        )

    assert not tmp_path.joinpath("committed-manifest-2.json").exists()
    _assert_prior_pointer_is_authoritative(
        committed_manifest_path=committed_one,
        committed_manifest_bytes=committed_one_bytes,
        candidate_manifest_path=next_candidate,
    )


def test_committed_manifest_materialization_failure_preserves_prior_pointer(
    tmp_path: Path,
) -> None:
    (
        committed_one,
        committed_one_bytes,
        next_candidate,
        checkpoint_two,
        report_two,
        transaction_two,
    ) = _prepare_roll_forward(tmp_path)
    blocked_parent = tmp_path / "blocked-output-parent"
    blocked_parent.write_text("not a directory\n", encoding="utf-8")
    blocked_output = blocked_parent / "committed-manifest.json"

    with pytest.raises(OSError):
        commit_checkpoint_manifest(
            manifest_path=next_candidate,
            checkpoint_transaction_path=transaction_two,
            checkpoint_report_path=report_two,
            checkpoint_database_path=checkpoint_two / "nba.duckdb",
            output_path=blocked_output,
            chain_id=_CHAIN_ID,
            run_id=_RUN_ID,
            run_attempt="1",
            source_sha=_SOURCE_SHA,
            artifact_id=1002,
            artifact_digest=_ARTIFACT_DIGEST,
            artifact_size_bytes=4098,
        )

    assert not blocked_output.exists()
    _assert_prior_pointer_is_authoritative(
        committed_manifest_path=committed_one,
        committed_manifest_bytes=committed_one_bytes,
        candidate_manifest_path=next_candidate,
    )


def test_restore_rejects_committed_receipt_workflow_run_mismatch(
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
    committed["chain_state"]["latest_checkpoint_transaction"]["receipt"]["artifact_run_id"] = 54321
    committed_path.write_text(json.dumps(committed) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="disagrees with its pointer: run ID"):
        validate_checkpoint_artifact(
            manifest_path=committed_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=report_path,
            chain_id=_CHAIN_ID,
            source_sha=_SOURCE_SHA,
        )


def test_restore_rejects_transaction_source_mismatch_with_trusted_manifest(
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
    transaction["identity"]["source_sha"] = "0" * 40
    transaction["receipt"]["source_sha"] = "0" * 40
    committed_path.write_text(json.dumps(committed) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="transaction source SHA does not match"):
        validate_checkpoint_artifact(
            manifest_path=committed_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=report_path,
            chain_id=_CHAIN_ID,
            source_sha=_SOURCE_SHA,
        )


@pytest.mark.parametrize(
    ("mutated_member", "error_match"),
    [
        ("database", "database digest does not match its report"),
        ("report", "report digest does not match its transaction"),
    ],
)
def test_restore_revalidates_committed_database_and_report_bytes(
    tmp_path: Path,
    mutated_member: str,
    error_match: str,
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
    if mutated_member == "database":
        with checkpoint_dir.joinpath("nba.duckdb").open("ab") as database:
            database.write(b"post-commit mutation")
    else:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["active_lane_count"] = 999
        report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=error_match):
        validate_checkpoint_artifact(
            manifest_path=committed_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=report_path,
            chain_id=_CHAIN_ID,
            source_sha=_SOURCE_SHA,
        )
