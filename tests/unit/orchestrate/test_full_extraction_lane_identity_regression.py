from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nbadb.contracts.assurance_admission import AssuranceAdmission
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.orchestrate.full_extraction_control import (
    FullExtractionLane,
    _attested_current_lane_artifacts,
    _coverage_fingerprint,
    _coverage_hash_for_lane,
    _create_exact_extraction_journal,
    _file_sha256,
    _metadata_lane_contract_errors,
    _metadata_records_by_lane,
    _schedule_lanes,
    build_checkpoint_database,
    lane_outcome_from_metadata,
    manifest_payload,
)

FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "fixtures"
    / "full-extraction"
    / "run-29568624951-completed-lane-reorder.json"
)
TEST_ARTIFACT_ID = "8479295867"
TEST_ARTIFACT_DIGEST = f"sha256:{'c' * 64}"


def _assurance_admission(source_sha: str) -> AssuranceAdmission:
    authority = expected_nba_api_provider_authority()
    return AssuranceAdmission(
        source_sha=source_sha,
        assurance_manifest_sha256="1" * 64,
        generation_semantic_sha256="2" * 64,
        provider_evidence_sha256=str(authority["provider_evidence_sha256"]),
        provider_authority_sha256=str(authority["authority_sha256"]),
        authority_semantic_diff_sha256="3" * 64,
        authority_update_mode="full",
        first_extraction=True,
        model_status="GREEN",
    )


def _fixture() -> dict[str, Any]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _lane(row: dict[str, Any], *, index_field: str) -> FullExtractionLane:
    return FullExtractionLane(
        lane_id=str(row["lane_id"]),
        lane_index=int(row[index_field]),
        lane_name=str(row["lane_name"]),
        lane_kind=str(row["lane_kind"]),
        season_start=row["season_start"],
        season_end=row["season_end"],
        patterns=tuple(row["patterns"]),
        season_types=tuple(row["season_types"]),
        context_measures=tuple(row["context_measures"]),
        endpoints=tuple(row["endpoints"]),
        resume_only=True,
        timeout_seconds=int(row["timeout_seconds"]),
    )


def _contract_payload(lane: FullExtractionLane, lane_index: object) -> dict[str, Any]:
    return {
        "lane_id": lane.lane_id,
        "lane_index": lane_index,
        "lane_name": lane.lane_name,
        "lane_kind": lane.lane_kind,
        "patterns": list(lane.patterns),
        "season_types": list(lane.season_types),
        "context_measures": list(lane.context_measures),
        "endpoints": list(lane.endpoints),
        "season_start": "" if lane.season_start is None else str(lane.season_start),
        "season_end": "" if lane.season_end is None else str(lane.season_end),
    }


def _write_lane_database(path: Path, endpoint: str, params: str) -> None:
    path.parent.mkdir(parents=True)
    connection = duckdb.connect(str(path))
    try:
        connection.execute("CREATE TABLE stg_fixture (value INTEGER)")
        connection.execute("INSERT INTO stg_fixture VALUES (1)")
        _create_exact_extraction_journal(connection)
        connection.execute(
            """
            INSERT INTO _extraction_journal (
                endpoint,
                params,
                status,
                started_at,
                completed_at,
                rows_extracted,
                error_message,
                retry_count
            )
            VALUES (?, ?, 'done', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, NULL, 0)
            """,
            [endpoint, params],
        )
    finally:
        connection.close()


def _write_attested_metadata(
    *,
    path: Path,
    database_path: Path,
    metadata_lane: FullExtractionLane,
    chain_id: str,
    run_id: str,
    source_sha: str,
) -> None:
    artifact_name = f"extraction-lane-{chain_id}-{metadata_lane.lane_id}"
    database_sha256 = _file_sha256(database_path)
    payload = {
        "metadata_schema_version": 3,
        "chain_id": chain_id,
        "source_sha": source_sha,
        "lane_id": metadata_lane.lane_id,
        "lane_index": metadata_lane.lane_index,
        "lane_name": metadata_lane.lane_name,
        "lane_kind": metadata_lane.lane_kind,
        "status": "complete",
        "raw_status": "complete",
        "patterns": list(metadata_lane.patterns),
        "season_types": list(metadata_lane.season_types),
        "context_measures": list(metadata_lane.context_measures),
        "endpoints": list(metadata_lane.endpoints),
        "season_start": (
            "" if metadata_lane.season_start is None else str(metadata_lane.season_start)
        ),
        "season_end": "" if metadata_lane.season_end is None else str(metadata_lane.season_end),
        "coverage_units_hash": _coverage_hash_for_lane(metadata_lane),
        "database_sha256": database_sha256,
        "state_artifact": {
            "run_id": run_id,
            "name": artifact_name,
            "sha256": database_sha256,
            "attested": True,
            "uploaded": True,
            "artifact_id": TEST_ARTIFACT_ID,
            "artifact_digest": TEST_ARTIFACT_DIGEST,
        },
    }
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    artifact_root = next(parent for parent in database_path.parents if parent.name == artifact_name)
    attestation_path = artifact_root / "artifacts/extraction/lane-state-attestation.json"
    attestation_path.parent.mkdir(parents=True)
    attestation_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "chain_id": chain_id,
                "source_sha": source_sha,
                "lane_id": metadata_lane.lane_id,
                "run_id": run_id,
                "artifact_name": artifact_name,
                "coverage_units_hash": _coverage_hash_for_lane(metadata_lane),
                "database_sha256": database_sha256,
                "attested": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_run_29568624951_fixture_freezes_completed_lane_reorder() -> None:
    fixture = _fixture()
    rows = fixture["lanes"]
    original = [_lane(row, index_field="original_lane_index") for row in rows]
    rescheduled = [_lane(row, index_field="rescheduled_lane_index") for row in rows]

    assert len(rows) == 13
    assert [lane.lane_index for lane in original] == fixture["expected_original_indexes"]
    assert [lane.lane_index for lane in rescheduled] == fixture["expected_rescheduled_indexes"]
    assert _coverage_fingerprint(original) == fixture["expected_coverage_fingerprint"]
    assert _coverage_fingerprint(rescheduled) == fixture["expected_coverage_fingerprint"]
    original_hashes = {lane.lane_id: _coverage_hash_for_lane(lane) for lane in original}
    assert original_hashes == fixture["expected_lane_coverage_hashes"]
    assert original_hashes == {lane.lane_id: _coverage_hash_for_lane(lane) for lane in rescheduled}
    assert fixture["incident_baseline"] == {
        "error": (
            "ValueError: Latest checkpoint pointer coverage hash does not match "
            "the built checkpoint"
        ),
        "run_started_at": "2026-07-17T10:28:14Z",
        "updated_at": "2026-07-20T23:49:45Z",
        "run_duration_seconds": 307291,
        "job_span_started_at": "2026-07-17T10:28:20Z",
        "job_span_completed_at": "2026-07-20T23:49:44Z",
        "job_span_duration_seconds": 307284,
        "duration_display": "85h21m",
        "duration_display_precision": "minute",
        "jobs": {
            "total": 79,
            "success": 62,
            "failure": 12,
            "skipped": 5,
        },
        "extract_jobs": {
            "total": 64,
            "complete": 13,
            "needs_resume": 50,
            "pipeline_failure": 1,
        },
        "calls": {"completed": 290006, "failed": 26039},
        "rows": 42135461,
        "canonical_checkpoint_present": False,
    }


@given(st.permutations(tuple(range(13))))
@settings(deadline=None, max_examples=50)
def test_completed_lane_permutations_preserve_durable_coverage_identity(
    permutation: list[int],
) -> None:
    rows = _fixture()["lanes"]
    original = [_lane(row, index_field="original_lane_index") for row in rows]
    permuted = [original[source_index] for source_index in permutation]
    rescheduled = _schedule_lanes(
        permuted,
        chunk_profile="standard",
        max_matrix_lanes=len(permuted),
    )

    assert [lane.lane_index for lane in rescheduled] == list(range(13))
    assert _coverage_fingerprint(rescheduled) == _coverage_fingerprint(original)
    assert {lane.lane_id: _coverage_hash_for_lane(lane) for lane in rescheduled} == {
        lane.lane_id: _coverage_hash_for_lane(lane) for lane in original
    }


@given(
    st.one_of(
        st.integers(min_value=0, max_value=1_000_000),
        st.integers(min_value=0, max_value=1_000_000).map(str),
    )
)
@settings(deadline=None, max_examples=50)
def test_non_negative_attempt_local_lane_index_is_not_durable_identity(
    metadata_lane_index: int | str,
) -> None:
    row = _fixture()["lanes"][2]
    rescheduled_lane = _lane(row, index_field="rescheduled_lane_index")
    payload = _contract_payload(rescheduled_lane, metadata_lane_index)

    assert _metadata_lane_contract_errors(payload, rescheduled_lane, strict=True) == []


@pytest.mark.parametrize("lane_index", [None, True, -1, "-1", "", "not-an-index", [], {}])
def test_malformed_attempt_local_lane_index_is_rejected(lane_index: object) -> None:
    row = _fixture()["lanes"][2]
    rescheduled_lane = _lane(row, index_field="rescheduled_lane_index")
    payload = _contract_payload(rescheduled_lane, lane_index)

    errors = _metadata_lane_contract_errors(payload, rescheduled_lane, strict=True)

    assert any(error.startswith("metadata_lane_index_") for error in errors)


def test_missing_attempt_local_lane_index_is_rejected() -> None:
    row = _fixture()["lanes"][2]
    rescheduled_lane = _lane(row, index_field="rescheduled_lane_index")
    payload = _contract_payload(rescheduled_lane, 24)
    payload.pop("lane_index")

    errors = _metadata_lane_contract_errors(payload, rescheduled_lane, strict=True)

    assert errors == ["metadata_lane_index_missing"]


def test_checkpoint_accepts_original_metadata_index_after_lane_reschedule(tmp_path: Path) -> None:
    fixture = _fixture()
    row = fixture["lanes"][2]
    original_lane = _lane(row, index_field="original_lane_index")
    rescheduled_lane = _lane(row, index_field="rescheduled_lane_index")
    chain_id = str(fixture["chain_id"])
    run_id = str(fixture["source_run_id"])
    source_sha = str(fixture["workflow_source_sha"])
    coverage_fingerprint = _coverage_fingerprint([rescheduled_lane])
    artifact_name = f"full-extraction-checkpoint-{chain_id}-iter-1"

    manifest = manifest_payload(
        [rescheduled_lane],
        assurance_admission=_assurance_admission(source_sha),
        chain_id=chain_id,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    artifacts_dir = tmp_path / "lanes"
    lane_artifact_dir = (
        artifacts_dir / f"run-{run_id}" / f"extraction-lane-{chain_id}-{original_lane.lane_id}"
    )
    database_path = lane_artifact_dir / "data/nbadb/nba.duckdb"
    _write_lane_database(
        database_path,
        original_lane.endpoints[0],
        '{"team_id": 1610612737}',
    )

    metadata_dir = tmp_path / "metadata"
    metadata_path = (
        metadata_dir
        / f"run-{run_id}"
        / f"extraction-lane-metadata-{chain_id}-{original_lane.lane_id}"
        / "lane-metadata.json"
    )
    _write_attested_metadata(
        path=metadata_path,
        database_path=database_path,
        metadata_lane=original_lane,
        chain_id=chain_id,
        run_id=run_id,
        source_sha=source_sha,
    )

    metadata_records = _metadata_records_by_lane(metadata_dir)
    metadata = {lane_id: records[-1][1] for lane_id, records in metadata_records.items()}
    complete_lane_ids = {
        lane_id
        for lane_id, payload in metadata.items()
        if lane_outcome_from_metadata(payload) == "complete"
    }
    _paths, attested_lane_ids, failures, _run_ids = _attested_current_lane_artifacts(
        artifacts_dir=artifacts_dir,
        metadata_dir=metadata_dir,
        complete_lane_ids=complete_lane_ids,
        metadata=metadata,
        metadata_records=metadata_records,
        lanes_by_id={rescheduled_lane.lane_id: rescheduled_lane},
        chain_id=chain_id,
        source_sha=source_sha,
        authorized_run_ids={run_id},
    )
    assert failures == {}
    assert attested_lane_ids == {rescheduled_lane.lane_id}

    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=artifacts_dir,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id=chain_id,
        run_id=run_id,
        source_sha=source_sha,
        checkpoint_generation=1,
        checkpoint_artifact_name=artifact_name,
    )

    assert report["terminal_ready"] is True
    assert report["included_lane_ids"] == [original_lane.lane_id]
    assert report["coverage_fingerprint"] == coverage_fingerprint
