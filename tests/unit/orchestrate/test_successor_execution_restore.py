from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import polars as pl
import pytest

from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.staging_batches import StagingBatchStore, StagingChunkMetadata
from nbadb.orchestrate.successor_execution_restore import (
    logical_bindings_from_replacement_attestations,
    reopen_same_generation_journal_attestations,
    restore_same_generation_replacements,
    successor_receipts_from_replacement_attestations,
)
from nbadb.orchestrate.successor_update_contract import (
    DeltaDisposition,
    SuccessorUpdateContractError,
)
from tests.unit.orchestrate.test_orchestrator import _successor_replacement_attestations
from tests.unit.orchestrate.test_successor_runtime import _harness, _one_league_game_log_plan


def _seed_generation_journal(
    public_root: Path,
    *,
    generation_identity_sha256: str,
    binding: LogicalCallReceiptBinding,
) -> None:
    duckdb_path = public_root / "nba.duckdb"
    if duckdb_path.exists() or duckdb_path.is_symlink():
        duckdb_path.unlink()
    connection = duckdb.connect(str(duckdb_path))
    try:
        journal = PipelineJournal(
            connection,
            successor_generation_sha256=generation_identity_sha256,
        )
        route_mapping: list[tuple[str, str]] = []
        frames: dict[str, pl.DataFrame] = {}
        for value, route_id in enumerate(binding.result_route_ids, start=1):
            _endpoint, staging_key, _index = route_id.rsplit(":", 2)
            route_mapping.append((staging_key, route_id))
            frames[staging_key] = pl.DataFrame({"value": [value]})
        StagingBatchStore(journal._conn).persist_frames(
            frames,
            metadata=StagingChunkMetadata(
                run_mode="successor_exact",
                lane_id="restore-lane",
                pattern="season",
                chunk_index=0,
                params_digest="params",
                entries_digest="entries",
                source_endpoint_name=binding.endpoint_name,
                source_params_digest=binding.logical_parameters_sha256,
            ),
            expected_staging_keys=[staging_key for staging_key, _route in route_mapping],
            replace_existing_chunk=True,
            receipt_binding=binding,
            result_route_ids_by_staging_key=tuple(route_mapping),
            successor_generation_sha256=generation_identity_sha256,
        )
    finally:
        connection.close()


def test_logical_bindings_group_exact_route_attestations(tmp_path: Path) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    transaction = harness["transaction"]
    dispatch = harness["dispatch"]
    attestations = _successor_replacement_attestations(
        transaction,
        dispatch,
        logical_root="a" * 64,
    )

    bindings = logical_bindings_from_replacement_attestations(attestations)

    assert len(bindings) == 1
    assert bindings[0].logical_call_receipt_sha256 == "a" * 64
    assert bindings[0].endpoint_name == dispatch.endpoint_name
    assert bindings[0].logical_parameters_sha256 == dispatch.parameters_sha256
    assert bindings[0].result_route_ids == dispatch.staging_route_ids


def test_receipts_reconstruct_exact_dispatch_member_progress(tmp_path: Path) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    transaction = harness["transaction"]
    plan = harness["plan"]
    dispatch = harness["dispatch"]
    requested_scope = harness["requested_scope"]
    attestations = _successor_replacement_attestations(
        transaction,
        dispatch,
        logical_root="b" * 64,
    )

    receipts = successor_receipts_from_replacement_attestations(
        transaction=transaction,
        execution_plan=plan,
        attestations=attestations,
    )

    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.requested_scope_sha256 == requested_scope.identity_sha256
    assert receipt.execution_dispatch_identity_sha256 == dispatch.identity_sha256
    assert receipt.logical_call_receipt_sha256 == "b" * 64
    assert receipt.disposition is DeltaDisposition.OBSERVED


def test_incomplete_multi_route_fails_before_capture_restore(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    from tests.unit.orchestrate.test_successor_runtime import _multi_route_harness

    harness = _multi_route_harness(harness)
    transaction = harness["transaction"]
    plan = harness["plan"]
    dispatch = plan.dispatches[0]
    attestations = _successor_replacement_attestations(
        transaction,
        dispatch,
        logical_root="c" * 64,
    )[:1]
    session = MagicMock()

    with pytest.raises(SuccessorUpdateContractError, match="exactly cover"):
        restore_same_generation_replacements(
            transaction=transaction,
            execution_plan=plan,
            capture_session=session,
            attestations=attestations,
        )

    session.restore_completed_bindings.assert_not_called()


def test_reopen_journal_treats_placeholder_bytes_as_no_progress(tmp_path: Path) -> None:
    public_root = tmp_path / "public"
    public_root.mkdir()
    duckdb_path = public_root / "nba.duckdb"
    duckdb_path.write_bytes(b"checkpointed-public-database")

    attestations = reopen_same_generation_journal_attestations(
        duckdb_path,
        generation_identity_sha256="d" * 64,
    )

    assert attestations == ()


def test_reopen_journal_loads_real_generation_attestations(tmp_path: Path) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    public_root = harness["public_root"]
    transaction = harness["transaction"]
    dispatch = harness["dispatch"]
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256="e" * 64,
        endpoint_name=dispatch.endpoint_name,
        logical_parameters_sha256=dispatch.parameters_sha256,
        provider_authority_sha256=transaction.baseline.provider_authority_sha256,
        result_route_ids=dispatch.staging_route_ids,
    )
    _seed_generation_journal(
        public_root,
        generation_identity_sha256=transaction.generation_identity_sha256,
        binding=binding,
    )

    attestations = reopen_same_generation_journal_attestations(
        public_root / "nba.duckdb",
        generation_identity_sha256=transaction.generation_identity_sha256,
    )

    assert tuple(item.logical_call_receipt_sha256 for item in attestations) == ("e" * 64,)
    assert tuple(item.result_route_id for item in attestations) == dispatch.staging_route_ids


def test_reopen_journal_rejects_missing_duckdb(tmp_path: Path) -> None:
    with pytest.raises(SuccessorUpdateContractError, match="runtime journal DuckDB is missing"):
        reopen_same_generation_journal_attestations(
            tmp_path / "missing.duckdb",
            generation_identity_sha256="f" * 64,
        )


def test_restore_rejects_non_attestation_inventory_before_capture(tmp_path: Path) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    session = MagicMock()

    with pytest.raises(SuccessorUpdateContractError, match="do not form exact logical calls"):
        restore_same_generation_replacements(
            transaction=harness["transaction"],
            execution_plan=harness["plan"],
            capture_session=session,
            attestations=(object(),),  # type: ignore[arg-type]
        )

    session.restore_completed_bindings.assert_not_called()


def test_restore_rejects_mixed_logical_authority(tmp_path: Path) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    (first,) = _successor_replacement_attestations(
        harness["transaction"],
        harness["dispatch"],
        logical_root="1" * 64,
    )
    mixed = replace(first, result_route_id="scoreboard:stg_scoreboard:0")

    with pytest.raises(SuccessorUpdateContractError, match="do not form exact logical calls"):
        logical_bindings_from_replacement_attestations((first, mixed))


def test_restore_rejects_replacement_outside_sealed_plan(tmp_path: Path) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    transaction = harness["transaction"]
    plan = harness["plan"]
    dispatch = harness["dispatch"]
    (attestation,) = _successor_replacement_attestations(
        transaction,
        dispatch,
        logical_root="2" * 64,
    )
    foreign = replace(attestation, source_scope_sha256="0" * 64, logical_parameters_sha256="0" * 64)
    session = MagicMock()

    with pytest.raises(
        SuccessorUpdateContractError,
        match="falls outside the sealed execution plan",
    ):
        restore_same_generation_replacements(
            transaction=transaction,
            execution_plan=plan,
            capture_session=session,
            attestations=(foreign,),
        )

    session.restore_completed_bindings.assert_not_called()


def test_restore_rejects_one_logical_receipt_spanning_multiple_dispatches(
    tmp_path: Path,
) -> None:
    from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
    from nbadb.orchestrate.successor_execution_plan import SealedUpdateExecutionDispatch
    from nbadb.orchestrate.successor_planning_generation_contract import (
        PlanningDispatchPhase,
        SealedProviderDispatch,
    )
    from nbadb.orchestrate.successor_update_contract import (
        CallMutability,
        RequestedRouteScope,
        SuccessorUpdateIntent,
        SuccessorUpdateTransaction,
    )

    first = _one_league_game_log_plan(_harness(tmp_path))
    first_dispatch = first["dispatch"]
    first_scope = first["requested_scope"]
    first_transaction = first["transaction"]
    bundle = staging_route_contract_bundle()
    route_id = "league_game_log:stg_league_game_log:0"
    second_parameters = {"season": "2024-25", "season_type": "Regular Season"}
    second_scope = RequestedRouteScope.from_parameters(
        endpoint_name="league_game_log",
        route_id=route_id,
        route_contract_sha256=bundle.by_route_id[route_id].contract_sha256,
        parameters=second_parameters,
        mutability=CallMutability.MUTABLE,
    )
    second_dispatch = SealedUpdateExecutionDispatch(
        order=1,
        sealed_dispatch=SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name="league_game_log",
            requested_scope_identity_sha256s=(second_scope.identity_sha256,),
            parameters=second_parameters,
            pattern="season",
            staging_route_ids=(route_id,),
            dependency_identity_sha256s=first_dispatch.dependency_identity_sha256s,
        ),
        requested_scopes=(second_scope,),
    )
    combined_plan = replace(first["plan"], dispatches=(first_dispatch, second_dispatch))
    combined_intent = SuccessorUpdateIntent(
        baseline_identity_sha256=first_transaction.baseline.identity_sha256,
        planning_generation_manifest_sha256=(
            first_transaction.intent.planning_generation_manifest_sha256
        ),
        successor_execution_plan_sha256=combined_plan.identity_sha256,
        planned_route_replacement_bindings_sha256=(
            combined_plan.planned_route_replacement_bindings_sha256
        ),
        mode=first_transaction.intent.mode,
        source_sha=first_transaction.intent.source_sha,
        cutoff_utc=first_transaction.intent.cutoff_utc,
        as_of_utc=first_transaction.intent.as_of_utc,
        requested_scopes=(first_scope, second_scope),
    )
    combined_transaction = SuccessorUpdateTransaction.candidate(
        generation=first_transaction.generation,
        baseline=first_transaction.baseline,
        intent=combined_intent,
    )
    (first_attestation,) = _successor_replacement_attestations(
        combined_transaction,
        first_dispatch,
        logical_root="3" * 64,
    )
    (second_attestation,) = _successor_replacement_attestations(
        combined_transaction,
        second_dispatch,
        logical_root="3" * 64,
    )
    session = MagicMock()

    with pytest.raises(
        SuccessorUpdateContractError,
        match="spans multiple execution dispatches",
    ):
        restore_same_generation_replacements(
            transaction=combined_transaction,
            execution_plan=combined_plan,
            capture_session=session,
            attestations=(first_attestation, second_attestation),
        )

    session.restore_completed_bindings.assert_not_called()


def test_restore_rejects_dispatch_split_across_logical_receipts(tmp_path: Path) -> None:
    from tests.unit.orchestrate.test_successor_runtime import _multi_route_harness

    harness = _multi_route_harness(_harness(tmp_path))
    transaction = harness["transaction"]
    plan = harness["plan"]
    dispatch = plan.dispatches[0]
    first_complete = _successor_replacement_attestations(
        transaction,
        dispatch,
        logical_root="4" * 64,
    )
    second_complete = _successor_replacement_attestations(
        transaction,
        dispatch,
        logical_root="5" * 64,
    )
    session = MagicMock()

    with pytest.raises(
        SuccessorUpdateContractError,
        match="split across logical replacement receipts",
    ):
        restore_same_generation_replacements(
            transaction=transaction,
            execution_plan=plan,
            capture_session=session,
            attestations=(*first_complete, *second_complete),
        )

    session.restore_completed_bindings.assert_not_called()


def test_restore_rejects_active_dispatch_mismatch(tmp_path: Path) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    transaction = harness["transaction"]
    plan = harness["plan"]
    dispatch = harness["dispatch"]
    attestations = _successor_replacement_attestations(
        transaction,
        dispatch,
        logical_root="6" * 64,
    )

    with pytest.raises(
        SuccessorUpdateContractError,
        match="differs from the active execution dispatch",
    ):
        successor_receipts_from_replacement_attestations(
            transaction=transaction,
            execution_plan=plan,
            attestations=attestations,
            active_dispatch_identity_sha256="0" * 64,
        )


def test_restore_rejects_foreign_generation_or_provider_authority(tmp_path: Path) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    transaction = harness["transaction"]
    plan = harness["plan"]
    dispatch = harness["dispatch"]
    (attestation,) = _successor_replacement_attestations(
        transaction,
        dispatch,
        logical_root="7" * 64,
    )
    foreign = replace(attestation, successor_generation_sha256="0" * 64)

    with pytest.raises(
        SuccessorUpdateContractError,
        match="does not match route/provider authority",
    ):
        successor_receipts_from_replacement_attestations(
            transaction=transaction,
            execution_plan=plan,
            attestations=(foreign,),
        )


def test_restore_rejects_non_transaction_or_plan_authority(tmp_path: Path) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    attestations = _successor_replacement_attestations(
        harness["transaction"],
        harness["dispatch"],
        logical_root="8" * 64,
    )

    with pytest.raises(
        SuccessorUpdateContractError,
        match="exact candidate transaction",
    ):
        successor_receipts_from_replacement_attestations(
            transaction=object(),  # type: ignore[arg-type]
            execution_plan=harness["plan"],
            attestations=attestations,
        )
    with pytest.raises(SuccessorUpdateContractError, match="validated execution plan"):
        successor_receipts_from_replacement_attestations(
            transaction=harness["transaction"],
            execution_plan=object(),  # type: ignore[arg-type]
            attestations=attestations,
        )


@pytest.mark.parametrize(
    ("generation", "match"),
    [
        ("F" * 64, "lowercase SHA-256"),
        ("abc", "lowercase SHA-256"),
        (123, "lowercase SHA-256"),
    ],
)
def test_reopen_journal_rejects_invalid_generation_identity(
    tmp_path: Path,
    generation: object,
    match: str,
) -> None:
    with pytest.raises(SuccessorUpdateContractError, match=match):
        reopen_same_generation_journal_attestations(
            tmp_path / "nba.duckdb",
            generation_identity_sha256=generation,  # type: ignore[arg-type]
        )


def test_reopen_journal_rejects_relative_path_and_nonregular_duckdb(tmp_path: Path) -> None:
    with pytest.raises(SuccessorUpdateContractError, match="absolute Path"):
        reopen_same_generation_journal_attestations(
            Path("nba.duckdb"),
            generation_identity_sha256="9" * 64,
        )

    directory = tmp_path / "nba.duckdb"
    directory.mkdir()
    with pytest.raises(SuccessorUpdateContractError, match="unreadable"):
        reopen_same_generation_journal_attestations(
            directory,
            generation_identity_sha256="9" * 64,
        )

    target = tmp_path / "real.duckdb"
    target.write_bytes(b"DUCK" + b"\x00" * 16)
    linked = tmp_path / "linked.duckdb"
    linked.symlink_to(target)
    with pytest.raises(SuccessorUpdateContractError, match="unreadable"):
        reopen_same_generation_journal_attestations(
            linked,
            generation_identity_sha256="9" * 64,
        )


def test_reopen_journal_rejects_duck_magic_that_cannot_be_opened(tmp_path: Path) -> None:
    duckdb_path = tmp_path / "nba.duckdb"
    duckdb_path.write_bytes(b"DUCK" + b"\x00" * 16)

    with pytest.raises(
        SuccessorUpdateContractError,
        match="could not be reopened",
    ):
        reopen_same_generation_journal_attestations(
            duckdb_path,
            generation_identity_sha256="a" * 64,
        )


def test_reopen_journal_rejects_invalid_replacement_inventory(tmp_path: Path) -> None:
    duckdb_path = tmp_path / "nba.duckdb"
    connection = duckdb.connect(str(duckdb_path))
    try:
        connection.execute(
            """
            CREATE TABLE _successor_staging_replacement_journal (
                successor_generation_sha256 VARCHAR NOT NULL,
                source_scope_sha256 VARCHAR NOT NULL,
                staging_key VARCHAR NOT NULL,
                canonical_frame_format VARCHAR NOT NULL,
                frame_content_hash_contract VARCHAR NOT NULL,
                frame_schema_hash_contract VARCHAR NOT NULL,
                prior_persisted_content_sha256 VARCHAR,
                persisted_content_sha256 VARCHAR NOT NULL,
                persisted_schema_sha256 VARCHAR NOT NULL,
                persisted_row_count BIGINT NOT NULL,
                logical_call_receipt_sha256 VARCHAR NOT NULL,
                provider_authority_sha256 VARCHAR NOT NULL,
                logical_parameters_sha256 VARCHAR NOT NULL,
                result_route_id VARCHAR NOT NULL,
                replacement_sha256 VARCHAR NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO _successor_staging_replacement_journal VALUES (
                ?, ?, 'stg_league_game_log',
                'arrow_ipc_stream_v2_pyarrow_v5', ?, ?, ?, ?, ?, 1, ?, ?, ?,
                'league_game_log:stg_league_game_log:0', ?
            )
            """,
            [
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "e" * 64,
                "f" * 64,
                "NOT-A-SHA",
                "1" * 64,
                "2" * 64,
                "3" * 64,
                "4" * 64,
                "5" * 64,
            ],
        )
    finally:
        connection.close()

    with pytest.raises(
        SuccessorUpdateContractError,
        match="restoration inventory is invalid",
    ):
        reopen_same_generation_journal_attestations(
            duckdb_path,
            generation_identity_sha256="b" * 64,
        )


def test_reopen_journal_rejects_canonical_digest_mismatch(tmp_path: Path) -> None:
    duckdb_path = tmp_path / "nba.duckdb"
    connection = duckdb.connect(str(duckdb_path))
    try:
        connection.execute(
            """
            CREATE TABLE _successor_staging_replacement_journal (
                successor_generation_sha256 VARCHAR NOT NULL,
                source_scope_sha256 VARCHAR NOT NULL,
                staging_key VARCHAR NOT NULL,
                canonical_frame_format VARCHAR NOT NULL,
                frame_content_hash_contract VARCHAR NOT NULL,
                frame_schema_hash_contract VARCHAR NOT NULL,
                prior_persisted_content_sha256 VARCHAR,
                persisted_content_sha256 VARCHAR NOT NULL,
                persisted_schema_sha256 VARCHAR NOT NULL,
                persisted_row_count BIGINT NOT NULL,
                logical_call_receipt_sha256 VARCHAR NOT NULL,
                provider_authority_sha256 VARCHAR NOT NULL,
                logical_parameters_sha256 VARCHAR NOT NULL,
                result_route_id VARCHAR NOT NULL,
                replacement_sha256 VARCHAR NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO _successor_staging_replacement_journal VALUES (
                ?, ?, 'stg_league_game_log',
                'arrow_ipc_stream_v2_pyarrow_v5', ?, ?, ?, ?, ?, 1, ?, ?, ?,
                'league_game_log:stg_league_game_log:0', ?
            )
            """,
            [
                "c" * 64,
                "d" * 64,
                "e" * 64,
                "f" * 64,
                "1" * 64,
                "2" * 64,
                "3" * 64,
                "4" * 64,
                "5" * 64,
                "6" * 64,
                "7" * 64,
            ],
        )
    finally:
        connection.close()

    with pytest.raises(
        SuccessorUpdateContractError,
        match="restoration inventory is invalid",
    ):
        reopen_same_generation_journal_attestations(
            duckdb_path,
            generation_identity_sha256="c" * 64,
        )
