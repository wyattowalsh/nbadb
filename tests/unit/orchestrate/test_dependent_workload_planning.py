from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pytest

from nbadb.extract.bronze import LogicalCallReceiptBinding, canonical_parameters_sha256
from nbadb.orchestrate.checkpoint_contract import (
    CheckpointArtifactReceipt,
    CheckpointTransaction,
    CheckpointW2AuthorityIdentity,
)
from nbadb.orchestrate.dependent_workload_contract import (
    DependentWorkloadContractError,
    DependentWorkloadKind,
    canonical_sha256,
)
from nbadb.orchestrate.dependent_workload_planning import (
    DEPENDENT_ENDPOINTS,
    DependentExecutionPlan,
    build_dependent_execution_plan,
    compile_post_foundation_bundle,
)
from nbadb.orchestrate.discovery_artifacts import (
    DiscoveryArtifactScope,
    DiscoveryArtifactStore,
)
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.public_value_authority_store import PUBLIC_VALUE_AUTHORITY_TABLES
from nbadb.orchestrate.staging_batches import StagingBatchStore, StagingChunkMetadata
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE

if TYPE_CHECKING:
    from pathlib import Path

_CHAIN_ID = "dependent-fixture"
_SOURCE_SHA = "a" * 40
_PROVIDER_SHA = "b" * 64
_RUN_ID = 404
_DISCOVERY_NAME = f"full-extraction-discovery-artifacts-{_CHAIN_ID}"
_DISCOVERY_DIGEST = "c" * 64
_GAME_ID = "0022400001"


def _checkpoint_w2_authority() -> CheckpointW2AuthorityIdentity:
    relation_counts = tuple(
        sorted(
            (table_name, 0)
            for table_name in (*PUBLIC_VALUE_AUTHORITY_TABLES, RAW_NBA_API_W2_OPERATION_TABLE)
        )
    )
    database_authority = W2DatabaseAuthorityReceiptV1.build(
        w2_required_logical_call_count=0,
        w2_source_call_admission_inventory_sha256="4" * 64,
        raw_authority_v2_bundle_count=0,
        raw_authority_v2_bundle_inventory_sha256="5" * 64,
        raw_authority_v2_persistence_receipt_inventory_sha256="6" * 64,
        w2_publication_receipt_count=0,
        w2_publication_receipt_inventory_sha256="7" * 64,
        w2_exact_six_schema_inventory_sha256="8" * 64,
        w2_relation_row_counts=relation_counts,
        w2_relation_row_count=0,
        w2_relation_inventory_sha256="9" * 64,
    )
    return CheckpointW2AuthorityIdentity(
        database_authority=database_authority,
        database_authority_sha256=database_authority.receipt_sha256,
        expected_call_count=0,
        expected_call_inventory_sha256="0" * 64,
        database_authority_closed=True,
    )


@dataclass(frozen=True)
class _Fixture:
    manifest_path: Path
    report_path: Path
    database_path: Path
    discovery_root: Path


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_params(parameters: dict[str, int | str]) -> str:
    return json.dumps(parameters, sort_keys=True, separators=(",", ":"))


def _persist_call(
    conn: duckdb.DuckDBPyConnection,
    *,
    endpoint_name: str,
    parameters: dict[str, int | str],
    frames: dict[str, pl.DataFrame],
    routes: tuple[tuple[str, int], ...],
) -> None:
    parameters_sha256 = canonical_parameters_sha256(parameters)
    route_mapping = tuple(
        (staging_key, f"{endpoint_name}:{staging_key}:{result_index}")
        for staging_key, result_index in routes
    )
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=canonical_sha256(
            {
                "endpoint_name": endpoint_name,
                "logical_parameters_sha256": parameters_sha256,
                "provider_authority_sha256": _PROVIDER_SHA,
                "result_route_ids": [route_id for _key, route_id in route_mapping],
            }
        ),
        endpoint_name=endpoint_name,
        logical_parameters_sha256=parameters_sha256,
        provider_authority_sha256=_PROVIDER_SHA,
        result_route_ids=tuple(route_id for _key, route_id in route_mapping),
    )
    serialized = _canonical_params(parameters)
    journal = PipelineJournal(conn)
    journal.record_start(endpoint_name, serialized)
    StagingBatchStore(conn).persist_frames(
        frames,
        metadata=StagingChunkMetadata(
            run_mode="foundation",
            lane_id=f"foundation-{endpoint_name}",
            pattern="game",
            chunk_index=0,
            params_digest=parameters_sha256[:16],
            entries_digest=canonical_sha256([endpoint_name])[:16],
            source_endpoint_name=endpoint_name,
            source_params_digest=parameters_sha256,
        ),
        expected_staging_keys=tuple(staging_key for staging_key, _index in routes),
        materialize=True,
        receipt_binding=binding,
        result_route_ids_by_staging_key=route_mapping,
    )
    journal.record_success(
        endpoint_name,
        serialized,
        sum(frame.height for frame in frames.values()),
        receipt_binding=binding,
    )


def _fixture(
    tmp_path: Path,
    *,
    discovery_frame: pl.DataFrame | None = None,
    checkpoint_frame: pl.DataFrame | None = None,
    include_rotation: bool = True,
) -> _Fixture:
    discovery_root = tmp_path / "discovery"
    discovery_frame = (
        discovery_frame
        if discovery_frame is not None
        else pl.DataFrame({"game_id": [_GAME_ID], "game_date": ["2024-10-22"]})
    )
    checkpoint_frame = checkpoint_frame if checkpoint_frame is not None else discovery_frame.clone()
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    DiscoveryArtifactStore(discovery_root).upsert_frame(
        scope,
        discovery_frame,
        provenance="receipt-bound integration fixture",
    )

    database_path = tmp_path / "foundation.duckdb"
    conn = duckdb.connect(str(database_path))
    try:
        conn.execute(
            """
            CREATE TABLE _extraction_journal (
                endpoint VARCHAR NOT NULL,
                params VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                retry_count INTEGER DEFAULT 0,
                PRIMARY KEY (endpoint, params)
            )
            """
        )
        conn.register("checkpoint_game_log", checkpoint_frame.to_arrow())
        conn.execute("CREATE TABLE stg_league_game_log AS SELECT * FROM checkpoint_game_log")
        conn.unregister("checkpoint_game_log")
        _persist_call(
            conn,
            endpoint_name="box_score_matchups",
            parameters={"game_id": _GAME_ID},
            frames={
                "stg_matchup": pl.DataFrame(
                    {
                        "game_id": [_GAME_ID],
                        "off_team_id": [101],
                        "off_player_id": [11],
                        "def_team_id": [202],
                        "def_player_id": [21],
                    }
                )
            },
            routes=(("stg_matchup", 0),),
        )
        if include_rotation:
            _persist_call(
                conn,
                endpoint_name="game_rotation",
                parameters={"game_id": _GAME_ID},
                frames={
                    "stg_rotation_away": pl.DataFrame(
                        {
                            "game_id": [_GAME_ID] * 5,
                            "team_id": [101] * 5,
                            "person_id": [11, 12, 13, 14, 15],
                            "in_time_real": [0] * 5,
                            "out_time_real": [10] * 5,
                        }
                    ),
                    "stg_rotation_home": pl.DataFrame(
                        {
                            "game_id": [_GAME_ID] * 5,
                            "team_id": [202] * 5,
                            "person_id": [21, 22, 23, 24, 25],
                            "in_time_real": [0] * 5,
                            "out_time_real": [10] * 5,
                        }
                    ),
                },
                routes=(("stg_rotation_away", 0), ("stg_rotation_home", 1)),
            )
        conn.execute("CHECKPOINT")
    finally:
        conn.close()

    database_sha256 = _sha256_path(database_path)
    report_path = tmp_path / "checkpoint-report.json"
    report_path.write_text(
        json.dumps(
            {
                "chain_id": _CHAIN_ID,
                "source_sha": _SOURCE_SHA,
                "checkpoint_generation": 2,
                "database_sha256": database_sha256,
                "provider_authority_sha256": _PROVIDER_SHA,
                "terminal_ready": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    report_sha256 = _sha256_path(report_path)
    candidate = CheckpointTransaction.candidate(
        chain_id=_CHAIN_ID,
        source_sha=_SOURCE_SHA,
        generation=2,
        artifact_name=f"full-extraction-checkpoint-{_CHAIN_ID}-iter-2",
        lane_contracts=[{"lane_id": "foundation", "coverage_units_hash": "d" * 64}],
        coverage_fingerprint="e" * 64,
    )
    built = candidate.mark_built(
        database_sha256=database_sha256,
        report_sha256=report_sha256,
        w2_authority=_checkpoint_w2_authority(),
    )
    assert built.build is not None
    receipt = CheckpointArtifactReceipt(
        artifact_id=303,
        artifact_run_id=_RUN_ID,
        artifact_run_attempt=1,
        artifact_name=built.artifact_name,
        artifact_digest="sha256:" + "f" * 64,
        artifact_size_bytes=database_path.stat().st_size + report_path.stat().st_size,
        database_sha256=database_sha256,
        report_sha256=report_sha256,
        chain_id=_CHAIN_ID,
        source_sha=_SOURCE_SHA,
        generation=2,
        coverage_fingerprint="e" * 64,
        lane_inventory_sha256=built.identity.coverage.lane_inventory_sha256,
        w2_authority_identity_sha256=built.build.w2_authority.identity_sha256,
    )
    transaction = built.mark_uploaded_verified(receipt).commit()
    manifest_path = tmp_path / "committed-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"chain_state": {"latest_checkpoint_transaction": transaction.to_dict()}},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return _Fixture(manifest_path, report_path, database_path, discovery_root)


def _compile(fixture: _Fixture):
    return compile_post_foundation_bundle(
        committed_manifest_path=fixture.manifest_path,
        checkpoint_report_path=fixture.report_path,
        checkpoint_database_path=fixture.database_path,
        discovery_root=fixture.discovery_root,
        discovery_artifact_id=909,
        discovery_artifact_run_id=_RUN_ID,
        discovery_artifact_name=_DISCOVERY_NAME,
        discovery_artifact_digest=_DISCOVERY_DIGEST,
    )


def test_real_receipts_compile_deterministic_alias_conserving_plan(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    bundle = _compile(fixture)
    plan = build_dependent_execution_plan(bundle)
    output = tmp_path / "dependent-plan.json"
    plan.write(output)
    reloaded = DependentExecutionPlan.read(output)

    assert reloaded.content_sha256 == plan.content_sha256
    assert _compile(fixture).content_sha256 == bundle.content_sha256
    assert {call.endpoint_name for call in plan.calls} == set(DEPENDENT_ENDPOINTS)
    lineup_calls = [call for call in plan.calls if call.kind is DependentWorkloadKind.FIVE_V_FIVE]
    assert {call.endpoint_name for call in lineup_calls} == {
        "team_and_players_vs",
        "team_and_players_vs_players",
    }
    assert len(lineup_calls) == 4
    assert len({call.unit_sha256 for call in lineup_calls}) == 2
    assert {
        (dict(call.parameters)["team_id"], dict(call.parameters)["vs_team_id"])
        for call in lineup_calls
    } == {(101, 202), (202, 101)}
    assert {
        endpoint_name: sum(call.endpoint_name == endpoint_name for call in lineup_calls)
        for endpoint_name in ("team_and_players_vs", "team_and_players_vs_players")
    } == {"team_and_players_vs": 2, "team_and_players_vs_players": 2}
    assert len(plan.calls) == 6
    inventory = plan.to_payload()["inventory"]
    assert inventory["semantic_unit_count"] == 4
    assert inventory["physical_call_count"] == 6
    assert inventory["endpoint_counts"] == {
        "player_vs_player": 1,
        "team_and_players_vs": 2,
        "team_and_players_vs_players": 2,
        "team_vs_player": 1,
    }
    assert len(plan.to_extraction_plan_items()) == 4
    serialized = output.read_text(encoding="utf-8")
    assert "private" not in serialized.lower()
    assert "pointer_blob_sha" not in serialized
    assert "expected_previous_blob_sha" not in serialized


def test_missing_rotation_authority_fails_before_cartesian_work(tmp_path: Path) -> None:
    with pytest.raises(
        DependentWorkloadContractError,
        match="missing required tables.*stg_rotation_away.*stg_rotation_home",
    ):
        _compile(_fixture(tmp_path, include_rotation=False))


def test_missing_or_ambiguous_discovery_authority_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    for manifest_path in fixture.discovery_root.glob("league_game_log.*.json"):
        manifest_path.rename(manifest_path.with_suffix(".missing"))

    with pytest.raises(DependentWorkloadContractError, match="manifests are missing"):
        _compile(fixture)


@pytest.mark.parametrize("mode", ["legacy", "aggregate", "conflicting_scope"])
def test_legacy_aggregate_and_conflicting_discovery_authorities_fail_closed(
    tmp_path: Path,
    mode: str,
) -> None:
    fixture = _fixture(tmp_path)
    manifest_path = next(fixture.discovery_root.glob("league_game_log.*.json"))
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mode == "legacy":
        payload["artifact_version"] = 1
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        expected = "singleton v2 generation"
    elif mode == "aggregate":
        payload["scope"]["seasons"].append("2023-24")
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        expected = "singleton v2 generation"
    else:
        conflicting_scope = DiscoveryArtifactScope(
            kind="league_game_log",
            seasons=("2023-24",),
            season_types=("Regular Season",),
        )
        content_sha256 = payload["content"]["sha256"]
        source_generation = fixture.discovery_root / payload["content"]["path"]
        conflicting_generation_name = (
            f"league_game_log.{conflicting_scope.digest()}.{content_sha256}.parquet"
        )
        (fixture.discovery_root / conflicting_generation_name).write_bytes(
            source_generation.read_bytes()
        )
        payload["scope"]["seasons"] = ["2023-24"]
        payload["content"]["path"] = conflicting_generation_name
        (fixture.discovery_root / f"league_game_log.{conflicting_scope.digest()}.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        expected = "conflicting discovery singleton scopes"

    with pytest.raises(DependentWorkloadContractError, match=expected):
        _compile(fixture)


@pytest.mark.parametrize(
    ("discovery_frame", "checkpoint_frame", "expected"),
    [
        (
            pl.DataFrame(
                {"game_id": [], "game_date": []},
                schema={"game_id": pl.String, "game_date": pl.String},
            ),
            pl.DataFrame(
                {"game_id": [], "game_date": []},
                schema={"game_id": pl.String, "game_date": pl.String},
            ),
            "contains no games",
        ),
        (
            pl.DataFrame({"game_id": [_GAME_ID], "game_date": ["2024-10-22"]}),
            pl.DataFrame(
                {
                    "game_id": [_GAME_ID, "0022400002"],
                    "game_date": ["2024-10-22", "2024-10-23"],
                }
            ),
            "row multiset differs",
        ),
    ],
)
def test_zero_and_mismatched_discovery_scopes_fail_closed(
    tmp_path: Path,
    discovery_frame: pl.DataFrame,
    checkpoint_frame: pl.DataFrame,
    expected: str,
) -> None:
    fixture = _fixture(
        tmp_path,
        discovery_frame=discovery_frame,
        checkpoint_frame=checkpoint_frame,
    )

    with pytest.raises(DependentWorkloadContractError, match=expected):
        _compile(fixture)


def test_legitimate_two_team_game_rows_produce_one_deterministic_scope(
    tmp_path: Path,
) -> None:
    game_rows = pl.DataFrame(
        {
            "game_id": [_GAME_ID, _GAME_ID],
            "game_date": ["2024-10-22", "2024-10-22"],
            "team_id": [101, 202],
        }
    )
    bundle = _compile(
        _fixture(
            tmp_path,
            discovery_frame=game_rows,
            checkpoint_frame=game_rows.clone(),
        )
    )

    assert {item.scope for item in bundle.scope_dispositions} == {
        bundle.scope_dispositions[0].scope
    }
    assert bundle.scope_dispositions[0].scope.foundation_row_ordinal == 0
