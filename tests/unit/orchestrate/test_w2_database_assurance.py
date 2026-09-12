"""Focused database-derived closure tests for exact-six W2 authority."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError, fields, replace
from datetime import timedelta
from functools import cache
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.contracts.raw_request_authority import ParserInputObjectV2
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.db import DBManager
from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
from nbadb.extract.bronze import LogicalCallReceiptBinding, canonical_parameters_sha256
from nbadb.extract.nba_api_adapter import (
    rederive_raw_authority_result_sets,
    rederive_raw_authority_stats_rows,
)
from nbadb.extract.raw_request_capture import (
    PendingRawRequestSuccessV2,
    PendingResultOccurrenceV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.orchestrate import w2_database_assurance as assurance_module
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.public_value_authority_store import PUBLIC_VALUE_AUTHORITY_TABLES
from nbadb.orchestrate.staging_batches import CommittedStagingFrameReadbackV2
from nbadb.orchestrate.w2_database_assurance import (
    W2_ON_OFF_SELECTOR_KIND,
    W2DatabaseAuthorityError,
    W2DatabaseAuthorityReceiptV1,
    W2OnOffDatabaseSnapshotV1,
    W2OnOffPairSnapshotV1,
    W2OnOffResultOwnershipV1,
    W2OnOffSourceCallSnapshotV1,
    verify_w2_database_authority,
    verify_w2_on_off_database_snapshot,
)
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE
from tests.unit.contracts.test_raw_request_finalization import (
    _STARTED_AT,
    _attempt,
    _committed_frame_receipt,
    _stats_frame,
    finalize_raw_request_capture,
)
from tests.unit.contracts.test_w2_operation_builder import _source_values
from tests.unit.orchestrate.test_journal import _persist_receipt_binding, _persist_w2_admission
from tests.unit.orchestrate.test_w2_operation_coordinator import _candidate, _coordinate

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl

    from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallAdmissionV1


_ON_OFF_ENDPOINTS = (
    "team_player_on_off_details",
    "team_player_on_off_summary",
)
_ON_OFF_RUNTIME_PARAMETER_DOMAIN = (
    "team_id",
    "last_n_games",
    "measure_type_detailed_defense",
    "month",
    "opponent_team_id",
    "pace_adjust",
    "per_mode_detailed",
    "period",
    "plus_minus",
    "rank",
    "season",
    "season_type_all_star",
    "date_from_nullable",
    "date_to_nullable",
    "game_segment_nullable",
    "league_id_nullable",
    "location_nullable",
    "outcome_nullable",
    "season_segment_nullable",
    "vs_conference_nullable",
    "vs_division_nullable",
)
_ON_OFF_SHARED_SCOPE_FIELDS = tuple(sorted(_ON_OFF_RUNTIME_PARAMETER_DOMAIN))
_ON_OFF_ROUTE_POLICY = {
    "team_player_on_off_details": (
        (
            0,
            "team_player_on_off_details:stg_on_off_details_overall:0",
            ("team_player_on_off_details:stg_team_dashboard_on_off:0",),
        ),
        (1, "team_player_on_off_details:stg_on_off_details_off_court:1", ()),
        (2, "team_player_on_off_details:stg_on_off_details_on_court:2", ()),
    ),
    "team_player_on_off_summary": (
        (
            0,
            "team_player_on_off_summary:stg_on_off_summary_overall:0",
            ("team_player_on_off_summary:stg_on_off:0",),
        ),
        (1, "team_player_on_off_summary:stg_on_off_summary_off_court:1", ()),
        (2, "team_player_on_off_summary:stg_on_off_summary_on_court:2", ()),
    ),
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _reseal_result_ownership(
    ownership: W2OnOffResultOwnershipV1,
    **changes: object,
) -> W2OnOffResultOwnershipV1:
    values = {
        item.name: getattr(ownership, item.name)
        for item in fields(ownership)
        if item.name != "ownership_sha256"
    }
    values.update(changes)
    identity = assurance_module._result_ownership_identity_payload(**values)
    return W2OnOffResultOwnershipV1(
        ownership_sha256=assurance_module._canonical_sha256(identity),
        **values,
    )


def _reseal_source_call(
    source_call: W2OnOffSourceCallSnapshotV1,
    **changes: object,
) -> W2OnOffSourceCallSnapshotV1:
    values = {
        item.name: getattr(source_call, item.name)
        for item in fields(source_call)
        if item.name != "source_call_sha256"
    }
    values.update(changes)
    if "result_ownerships" in changes:
        ownerships = values["result_ownerships"]
        declared_ids = tuple(
            sorted(route_id for item in ownerships for route_id in item.declared_route_ids)
        )
        owner_ids = tuple(sorted(item.canonical_owner_route_id for item in ownerships))
        alias_ids = tuple(
            sorted(route_id for item in ownerships for route_id in item.non_owning_alias_route_ids)
        )
        values.update(
            {
                "declared_result_route_ids": declared_ids,
                "declared_result_route_count": len(declared_ids),
                "canonical_owner_route_ids": owner_ids,
                "canonical_owner_route_count": len(owner_ids),
                "non_owning_alias_route_ids": alias_ids,
                "non_owning_alias_route_count": len(alias_ids),
                "declared_result_route_inventory_sha256": (
                    assurance_module._route_inventory_sha256(
                        ownerships,
                        role="declared",
                    )
                ),
                "canonical_owner_route_inventory_sha256": (
                    assurance_module._route_inventory_sha256(
                        ownerships,
                        role="canonical_owner",
                    )
                ),
                "non_owning_alias_route_inventory_sha256": (
                    assurance_module._route_inventory_sha256(
                        ownerships,
                        role="non_owning_alias",
                    )
                ),
            }
        )
    identity = assurance_module._source_call_identity_payload(
        journal_table_name=values["journal_table_name"],
        successor_generation_sha256=values["successor_generation_sha256"],
        logical_endpoint_name=values["logical_endpoint_name"],
        logical_parameters_json=values["logical_parameters_json"],
        logical_parameters_sha256=values["logical_parameters_sha256"],
        shared_pair_scope_json=values["shared_pair_scope_json"],
        shared_pair_scope_sha256=values["shared_pair_scope_sha256"],
        provider_authority_sha256=values["provider_authority_sha256"],
        declared_result_route_ids=values["declared_result_route_ids"],
        declared_result_route_count=values["declared_result_route_count"],
        declared_result_route_inventory_sha256=(values["declared_result_route_inventory_sha256"]),
        canonical_owner_route_ids=values["canonical_owner_route_ids"],
        canonical_owner_route_count=values["canonical_owner_route_count"],
        canonical_owner_route_inventory_sha256=(values["canonical_owner_route_inventory_sha256"]),
        non_owning_alias_route_ids=values["non_owning_alias_route_ids"],
        non_owning_alias_route_count=values["non_owning_alias_route_count"],
        non_owning_alias_route_inventory_sha256=(values["non_owning_alias_route_inventory_sha256"]),
        result_ownerships=values["result_ownerships"],
        logical_call_receipt_sha256=values["logical_call_receipt_sha256"],
        admission_sha256=values["admission"].admission_sha256,
        raw_authority_bundle_sha256=values["raw_authority_bundle"].bundle_sha256,
        result_cell_count=values["result_cell_count"],
        result_cell_inventory_sha256=values["result_cell_inventory_sha256"],
    )
    return W2OnOffSourceCallSnapshotV1(
        source_call_sha256=assurance_module._canonical_sha256(identity),
        **values,
    )


def _reseal_pair(
    pair: W2OnOffPairSnapshotV1,
    **changes: object,
) -> W2OnOffPairSnapshotV1:
    values = {
        item.name: getattr(pair, item.name) for item in fields(pair) if item.name != "pair_sha256"
    }
    values.update(changes)
    identity = {
        "schema_version": W2OnOffPairSnapshotV1.schema_version,
        "kind": W2OnOffPairSnapshotV1.kind,
        **values,
    }
    return W2OnOffPairSnapshotV1(
        pair_sha256=assurance_module._canonical_sha256(identity),
        **values,
    )


def _reseal_snapshot(
    snapshot: W2OnOffDatabaseSnapshotV1,
    **changes: object,
) -> W2OnOffDatabaseSnapshotV1:
    values = {
        item.name: getattr(snapshot, item.name)
        for item in fields(snapshot)
        if item.name != "snapshot_sha256"
    }
    values.update(changes)
    identity = {
        "schema_version": W2OnOffDatabaseSnapshotV1.schema_version,
        "kind": W2OnOffDatabaseSnapshotV1.kind,
        "database_authority_receipt_sha256": values["database_authority"].receipt_sha256,
        **{
            key: (
                [item.pair_sha256 for item in value]
                if key == "pairs"
                else [item.source_call_sha256 for item in value]
                if key == "source_calls"
                else value
            )
            for key, value in values.items()
            if key != "database_authority"
        },
    }
    identity["pair_sha256s"] = identity.pop("pairs")
    identity["source_call_sha256s"] = identity.pop("source_calls")
    return W2OnOffDatabaseSnapshotV1(
        snapshot_sha256=assurance_module._canonical_sha256(identity),
        **values,
    )


@cache
def _on_off_w2_values(
    endpoint_name: str,
) -> tuple[dict[str, object], str, dict[str, pl.DataFrame]]:
    declared_routes = tuple(
        route
        for route in staging_route_contract_bundle().routes
        if route.endpoint_name == endpoint_name
    )
    routes_by_id = {route.route_id: route for route in declared_routes}
    policy = _ON_OFF_ROUTE_POLICY[endpoint_name]
    declared_ids = {
        route_id
        for _ordinal, owner_route_id, alias_route_ids in policy
        for route_id in (owner_route_id, *alias_route_ids)
    }
    owner_ids = tuple(owner_route_id for _ordinal, owner_route_id, _aliases in policy)
    assert len(declared_routes) == 4
    assert len(routes_by_id) == 4
    assert set(routes_by_id) == declared_ids
    assert len(owner_ids) == 3
    routes = tuple(routes_by_id[route_id] for route_id in owner_ids)
    route = routes[0]
    parameters: dict[str, object] = {
        "date_from_nullable": "",
        "date_to_nullable": "",
        "game_segment_nullable": "",
        "last_n_games": "0",
        "league_id_nullable": "00",
        "location_nullable": "",
        "measure_type_detailed_defense": "Base",
        "month": "0",
        "opponent_team_id": 0,
        "outcome_nullable": "",
        "pace_adjust": "N",
        "per_mode_detailed": "Totals",
        "period": "0",
        "plus_minus": "N",
        "rank": "N",
        "season": "2024-25",
        "season_segment_nullable": "",
        "season_type_all_star": "Regular Season",
        "team_id": 1_610_612_747,
        "vs_conference_nullable": "",
        "vs_division_nullable": "",
    }
    assert tuple(parameters) == _ON_OFF_SHARED_SCOPE_FIELDS
    attempt = _attempt(route, parameters=parameters)
    logical_receipt = _sha(f"w2-on-off:{endpoint_name}")
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=logical_receipt,
        endpoint_name=endpoint_name,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        provider_authority_sha256=staging_route_contract_bundle().provider_authority_sha256,
        result_route_ids=tuple(sorted(item.route_id for item in routes)),
    )
    contract = pinned_runtime_contracts()[route.provider_endpoint_id]
    parser_input = json.dumps(
        {
            "resultSets": [
                {
                    "name": item.result_set_name,
                    "headers": list(item.expected_columns),
                    "rowSet": [],
                }
                for item in contract.result_sets
            ]
        },
        separators=(",", ":"),
    ).encode()
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=route.provider_endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=binding.provider_authority_sha256,
        endpoint_contract_sha256_value=route.endpoint_contract_sha256,
    )
    body = ParserInputObjectV2.from_parser_input(parser_input.decode())
    pending = PendingRawRequestSuccessV2(
        private_receipt_sha256=_sha(f"w2-on-off-capture:{endpoint_name}"),
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        outcome="success_empty",
        body_disposition="public_parser_input",
        body_object=body,
        results=tuple(
            PendingResultOccurrenceV2(
                result_set=item.result_set,
                duplicate_name_ordinal=item.duplicate_name_ordinal,
                ordered_headers=item.ordered_headers,
            )
            for item in derivations
        ),
        logical_receipt_sha256=logical_receipt,
        aggregate_route_ids=binding.result_route_ids,
    )
    safe_rows = rederive_raw_authority_stats_rows(
        endpoint_id=route.provider_endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=binding.provider_authority_sha256,
        endpoint_contract_sha256_value=route.endpoint_contract_sha256,
    )
    receipts = []
    readbacks = []
    frames: dict[str, pl.DataFrame] = {}
    for fixed_route in routes:
        candidates = tuple(
            item
            for item in safe_rows
            if item.result_set.canonical_index == fixed_route.canonical_result_set_ordinal
            and item.ordered_headers == fixed_route.provider_columns
        )
        assert len(candidates) == 1
        frame = _stats_frame(
            fixed_route,
            candidates[0],
            safe_parameters_json=attempt.safe_parameters_json,
        )
        receipt = _committed_frame_receipt(
            binding,
            route_id=fixed_route.route_id,
            staging_key=fixed_route.staging_key,
            frame=frame,
        )
        frames[fixed_route.staging_key] = frame
        receipts.append(receipt)
        readbacks.append(
            CommittedStagingFrameReadbackV2.build(
                committed_receipt=receipt,
                frame=frame,
            )
        )
    bundle = finalize_raw_request_capture(
        RawRequestCaptureSnapshotV2(
            objects=(body,),
            observations=(),
            pending_successes=(pending,),
            issues=(),
        ),
        binding,
        tuple(receipts),
    )
    values = _source_values(bundle)
    values.update(
        {
            "committed_staging_readbacks": tuple(readbacks),
            "expected_committed_staging_readback_sha256s": tuple(
                item.readback_receipt_sha256 for item in readbacks
            ),
        }
    )
    return values, attempt.safe_parameters_json, frames


def _complete_on_off_call(
    connection: duckdb.DuckDBPyConnection,
    endpoint_name: str,
    *,
    successor_generation_sha256: str | None = None,
) -> W2SourceCallAdmissionV1:
    values, params, frames = _on_off_w2_values(endpoint_name)
    candidate, public_store, operation_store = _candidate(
        connection,
        input_changes=dict(values),
    )
    admission = _coordinate(candidate, public_store, operation_store)
    journal = PipelineJournal(
        connection,
        successor_generation_sha256=successor_generation_sha256,
    )
    binding = candidate.logical_call_binding
    assert binding.endpoint_name == endpoint_name
    journal.record_start(
        endpoint_name,
        params,
        require_receipt=True,
        require_w2_operation=True,
    )
    _persist_receipt_binding(journal, binding, frames=frames)
    journal.record_success(
        endpoint_name,
        params,
        0,
        receipt_binding=binding,
        w2_admission=admission,
    )
    return admission


def _complete_on_off_pair(
    connection: duckdb.DuckDBPyConnection,
    *,
    successor_generation_sha256: str | None = None,
) -> tuple[W2SourceCallAdmissionV1, W2SourceCallAdmissionV1]:
    return (
        _complete_on_off_call(
            connection,
            _ON_OFF_ENDPOINTS[0],
            successor_generation_sha256=successor_generation_sha256,
        ),
        _complete_on_off_call(
            connection,
            _ON_OFF_ENDPOINTS[1],
            successor_generation_sha256=successor_generation_sha256,
        ),
    )


def _complete_one_call(
    connection: duckdb.DuckDBPyConnection,
) -> W2SourceCallAdmissionV1:
    journal = PipelineJournal(connection)
    binding, params, admission = _persist_w2_admission(journal)
    journal.record_start(
        binding.endpoint_name,
        params,
        require_receipt=True,
        require_w2_operation=True,
    )
    journal.record_success(
        binding.endpoint_name,
        params,
        1,
        receipt_binding=binding,
        w2_admission=admission,
    )
    return admission


def _complete_one_successor_call(
    connection: duckdb.DuckDBPyConnection,
) -> W2SourceCallAdmissionV1:
    journal = PipelineJournal(
        connection,
        successor_generation_sha256="a" * 64,
    )
    binding, params, admission = _persist_w2_admission(journal)
    journal.record_start(
        binding.endpoint_name,
        params,
        require_receipt=True,
        require_w2_operation=True,
    )
    journal.record_success(
        binding.endpoint_name,
        params,
        1,
        receipt_binding=binding,
        w2_admission=admission,
    )
    return admission


def _relation_counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    names = (*PUBLIC_VALUE_AUTHORITY_TABLES, RAW_NBA_API_W2_OPERATION_TABLE)
    return {
        table_name: int(connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0])
        for table_name in names
    }


def test_database_assurance_reconstructs_all_boundaries_and_is_replay_stable(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    admission = _complete_one_call(connection)
    before = _relation_counts(connection)

    first = verify_w2_database_authority(connection, require_w2=True)
    second = verify_w2_database_authority(
        connection,
        require_w2=True,
        expected_receipt_sha256=first.receipt_sha256,
    )

    assert type(first) is W2DatabaseAuthorityReceiptV1
    assert second == first
    assert second is not first
    assert W2DatabaseAuthorityReceiptV1.from_canonical_bytes(first.canonical_bytes()) == first
    assert first.w2_required_logical_call_count == 1
    assert first.raw_authority_v2_bundle_count == 1
    assert first.w2_publication_receipt_count == 1
    assert dict(first.w2_relation_row_counts) == before
    assert dict(first.w2_relation_row_counts)[RAW_NBA_API_W2_OPERATION_TABLE] == 1
    assert first.raw_authority_v2_bundle_inventory_sha256 != (first.w2_relation_inventory_sha256)
    assert admission.raw_authority_bundle_sha256
    assert _relation_counts(connection) == before


def test_database_assurance_reconstructs_successor_journal_authority(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    admission = _complete_one_successor_call(connection)

    receipt = verify_w2_database_authority(connection, require_w2=True)

    assert receipt.w2_required_logical_call_count == 1
    assert receipt.raw_authority_v2_bundle_count == 1
    assert receipt.w2_publication_receipt_count == 1
    assert admission.admission_sha256


def test_database_assurance_has_one_deterministic_empty_nonrequired_receipt(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    PipelineJournal(connection)

    first = verify_w2_database_authority(connection, require_w2=False)
    second = verify_w2_database_authority(connection, require_w2=False)

    assert first == second
    assert first.w2_required_logical_call_count == 0
    assert first.w2_relation_row_count == 0
    assert all(count == 0 for _table_name, count in first.w2_relation_row_counts)
    with pytest.raises(W2DatabaseAuthorityError, match="at least one closed logical call"):
        verify_w2_database_authority(connection, require_w2=True)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("w2_source_call_admission_sha256", "f" * 64),
        ("w2_source_call_admission_bytes", b"{}"),
        ("logical_call_receipt_sha256", "f" * 64),
        ("raw_authority_bundle_sha256", "f" * 64),
        ("raw_authority_persistence_receipt_sha256", "f" * 64),
        ("committed_staging_readback_count", 2),
        ("committed_staging_readback_root_sha256", "f" * 64),
        ("w2_operation_key_sha256", "f" * 64),
        ("w2_operation_receipt_sha256", "f" * 64),
        ("w2_operation_persistence_receipt_sha256", "f" * 64),
    ],
)
def test_database_assurance_rejects_corrupt_or_cross_call_journal_pins(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
    column: str,
    value: object,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    _complete_one_call(connection)
    connection.execute(f'UPDATE _extraction_journal SET "{column}" = ?', [value])

    with pytest.raises(W2DatabaseAuthorityError, match="admission failed exact durable replay"):
        verify_w2_database_authority(connection, require_w2=True)


def test_database_assurance_rejects_running_w2_and_evidence_without_marker(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    journal = PipelineJournal(connection)
    candidate, public_store, operation_store = _candidate(connection)
    admission = _coordinate(candidate, public_store, operation_store)
    binding = candidate.logical_call_binding
    journal.record_start(binding.endpoint_name, "{}", require_w2_operation=True)

    with pytest.raises(W2DatabaseAuthorityError, match="not durably successful"):
        verify_w2_database_authority(connection, require_w2=True)

    connection.execute(
        """
        UPDATE _extraction_journal
        SET w2_required = FALSE,
            w2_source_call_admission_sha256 = ?
        """,
        [admission.admission_sha256],
    )
    with pytest.raises(W2DatabaseAuthorityError, match="evidence without an exact required marker"):
        verify_w2_database_authority(connection, require_w2=False)


def test_database_assurance_rejects_public_five_and_operation_orphans(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    PipelineJournal(connection)
    candidate, public_store, operation_store = _candidate(connection)
    _coordinate(candidate, public_store, operation_store)

    with pytest.raises(W2DatabaseAuthorityError, match="orphan W2 bundles"):
        verify_w2_database_authority(connection, require_w2=False)

    connection.execute(f'DELETE FROM "{RAW_NBA_API_W2_OPERATION_TABLE}"')
    with pytest.raises(W2DatabaseAuthorityError, match="orphan W2 bundles"):
        verify_w2_database_authority(connection, require_w2=False)


def test_database_assurance_rejects_missing_public_or_operation_rows(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    admission = _complete_one_call(connection)
    nonempty = next(
        table_name
        for table_name, count in _relation_counts(connection).items()
        if table_name in PUBLIC_VALUE_AUTHORITY_TABLES and count > 0
    )
    connection.execute(f'DELETE FROM "{nonempty}"')

    with pytest.raises(W2DatabaseAuthorityError, match="missing or extra|exact-six publication"):
        verify_w2_database_authority(connection, require_w2=True)

    # Rebuild in a fresh fixture is intentionally unnecessary: operation absence
    # is an independent scalar closure failure on the already durable admission.
    connection.execute(
        f'DELETE FROM "{RAW_NBA_API_W2_OPERATION_TABLE}" WHERE operation_key_sha256 = ?',
        [admission.operation_key_sha256],
    )
    with pytest.raises(W2DatabaseAuthorityError, match="admission failed exact durable replay"):
        verify_w2_database_authority(connection, require_w2=True)


def test_database_assurance_rejects_raw_v2_mutation_before_publication(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    _complete_one_call(connection)
    connection.execute(
        """
        UPDATE raw_nba_api_request_observation
        SET observation_record_sha256 = ?
        """,
        ["f" * 64],
    )

    with pytest.raises(W2DatabaseAuthorityError, match="Raw Authority V2 receipt"):
        verify_w2_database_authority(connection, require_w2=True)


def test_database_assurance_refuses_caller_transaction_without_mutation(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    _complete_one_call(connection)
    before = connection.execute("SELECT * FROM _extraction_journal").fetchall()
    connection.execute("BEGIN TRANSACTION")

    with pytest.raises(W2DatabaseAuthorityError, match="sanitized dependency replay"):
        verify_w2_database_authority(connection, require_w2=True)

    assert connection.execute("SELECT * FROM _extraction_journal").fetchall() == before
    connection.execute("ROLLBACK")


def test_database_assurance_external_pin_preflight_and_schema_drift_fail_closed(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    receipt = verify_w2_database_authority(connection, require_w2=False)

    with pytest.raises(W2DatabaseAuthorityError, match="expected W2 database receipt"):
        verify_w2_database_authority(
            connection,
            require_w2=False,
            expected_receipt_sha256="not-a-digest",
        )
    with pytest.raises(W2DatabaseAuthorityError, match="differs from its expected receipt"):
        verify_w2_database_authority(
            connection,
            require_w2=False,
            expected_receipt_sha256="f" * 64,
        )
    assert (
        verify_w2_database_authority(
            connection,
            require_w2=False,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
        == receipt
    )

    _complete_one_call(connection)
    connection.execute(
        "ALTER TABLE raw_nba_api_value_representation ADD COLUMN foreign_value VARCHAR"
    )
    with pytest.raises(W2DatabaseAuthorityError, match="schema or primary key"):
        verify_w2_database_authority(connection, require_w2=True)


def test_database_assurance_receipt_replay_rejects_noncanonical_or_additive_bytes(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    receipt = verify_w2_database_authority(
        duckdb_memory_with_pipeline_tables,
        require_w2=False,
    )
    canonical = receipt.canonical_bytes()

    with pytest.raises(W2DatabaseAuthorityError, match="not canonical JSON"):
        W2DatabaseAuthorityReceiptV1.from_canonical_bytes(canonical + b"\n")
    with pytest.raises(W2DatabaseAuthorityError, match="foreign ordered field shape"):
        W2DatabaseAuthorityReceiptV1.from_canonical_bytes(
            json.dumps(
                {**receipt.to_dict(), "unexpected": True},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )


def test_on_off_snapshot_replays_fixed_selector_and_typed_records_deterministically(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    admissions = _complete_on_off_pair(connection)

    first = verify_w2_on_off_database_snapshot(connection)
    second = verify_w2_on_off_database_snapshot(
        connection,
        expected_database_receipt_sha256=first.database_authority.receipt_sha256,
    )

    assert type(first) is W2OnOffDatabaseSnapshotV1
    assert first == second
    assert first is not second
    assert first.selector_kind == W2_ON_OFF_SELECTOR_KIND
    assert first.selected_pair_count == 1
    assert len(first.pairs) == 1
    assert first.selected_logical_call_count == 2
    assert first.selected_observation_count == 2
    assert first.selected_occurrence_count == 6
    assert first.selected_result_cell_count == 0
    assert {item.logical_endpoint_name for item in first.source_calls} == set(_ON_OFF_ENDPOINTS)
    assert {item.admission.admission_sha256 for item in first.source_calls} == {
        item.admission_sha256 for item in admissions
    }
    assert {item.journal_table_name for item in first.source_calls} == {"_extraction_journal"}
    pair = first.pairs[0]
    assert pair.journal_table_name == "_extraction_journal"
    assert pair.successor_generation_sha256 is None
    assert pair.declared_result_route_count == 8
    assert pair.canonical_owner_route_count == 6
    assert pair.non_owning_alias_route_count == 2
    assert pair.shared_pair_scope_sha256 == first.source_calls[0].shared_pair_scope_sha256
    assert pair.shared_pair_scope_sha256 == first.source_calls[1].shared_pair_scope_sha256
    for source_call in first.source_calls:
        assert source_call.declared_result_route_count == 4
        assert source_call.canonical_owner_route_count == 3
        assert source_call.non_owning_alias_route_count == 1
        assert tuple(item.result_set_ordinal for item in source_call.result_ownerships) == (
            0,
            1,
            2,
        )
        expected_policy = _ON_OFF_ROUTE_POLICY[source_call.logical_endpoint_name]
        assert source_call.canonical_owner_route_ids == tuple(
            sorted(owner for _ordinal, owner, _aliases in expected_policy)
        )
        assert source_call.non_owning_alias_route_ids == tuple(
            alias for _ordinal, _owner, aliases in expected_policy for alias in aliases
        )
        assert (
            tuple(sorted(landing.route_id for landing in source_call.raw_authority_bundle.landings))
            == source_call.canonical_owner_route_ids
        )
    assert all(item.raw_authority_bundle.bundle_sha256 for item in first.source_calls)
    by_endpoint = {item.logical_endpoint_name: item for item in first.source_calls}
    details_call = by_endpoint[_ON_OFF_ENDPOINTS[0]]
    summary_call = by_endpoint[_ON_OFF_ENDPOINTS[1]]
    successor_generation = "a" * 64

    with pytest.raises(W2DatabaseAuthorityError, match="successor generation"):
        _reseal_source_call(
            details_call,
            journal_table_name="_successor_extraction_journal",
            successor_generation_sha256=None,
        )
    with pytest.raises(W2DatabaseAuthorityError, match="baseline.*successor generation"):
        _reseal_source_call(
            details_call,
            successor_generation_sha256=successor_generation,
        )

    successor_details = _reseal_source_call(
        details_call,
        journal_table_name="_successor_extraction_journal",
        successor_generation_sha256=successor_generation,
    )
    successor_summary = _reseal_source_call(
        summary_call,
        journal_table_name="_successor_extraction_journal",
        successor_generation_sha256=successor_generation,
    )
    successor_pairs = assurance_module._build_on_off_pairs((successor_details, successor_summary))
    assert len(successor_pairs) == 1
    assert successor_pairs[0].successor_generation_sha256 == successor_generation
    for calls in (
        (successor_details, summary_call),
        (details_call, successor_summary),
        (
            successor_details,
            _reseal_source_call(
                successor_summary,
                successor_generation_sha256="b" * 64,
            ),
        ),
    ):
        with pytest.raises(W2DatabaseAuthorityError, match="current-generation denominator"):
            assurance_module._build_on_off_pairs(calls)

    with pytest.raises(W2DatabaseAuthorityError, match="admission or Raw bundle"):
        _reseal_source_call(details_call, admission=summary_call.admission)
    with pytest.raises(W2DatabaseAuthorityError, match="admission or Raw bundle"):
        _reseal_source_call(
            details_call,
            raw_authority_bundle=summary_call.raw_authority_bundle,
        )
    with pytest.raises(W2DatabaseAuthorityError, match="parameter digest"):
        _reseal_source_call(details_call, logical_parameters_sha256="f" * 64)
    with pytest.raises(W2DatabaseAuthorityError, match="result-cell inventory root"):
        _reseal_source_call(details_call, result_cell_inventory_sha256="f" * 64)

    ownerships = details_call.result_ownerships
    overall = ownerships[0]
    alias_route_id = overall.non_owning_alias_route_ids[0]
    route_by_id = assurance_module._fixed_on_off_route_contracts(details_call.logical_endpoint_name)
    alias_as_owner = _reseal_result_ownership(
        overall,
        canonical_owner_route_id=alias_route_id,
        canonical_owner_route_contract_sha256=route_by_id[alias_route_id].contract_sha256,
        non_owning_alias_route_ids=(overall.canonical_owner_route_id,),
        non_owning_alias_route_contract_sha256s=(overall.canonical_owner_route_contract_sha256,),
    )
    with pytest.raises(
        W2DatabaseAuthorityError,
        match="selected Raw observations|ownerships differ",
    ):
        _reseal_source_call(
            details_call,
            result_ownerships=(alias_as_owner, *ownerships[1:]),
        )

    omitted_alias = _reseal_result_ownership(
        overall,
        declared_route_ids=(overall.canonical_owner_route_id,),
        declared_route_contract_sha256s=(overall.canonical_owner_route_contract_sha256,),
        non_owning_alias_route_ids=(),
        non_owning_alias_route_contract_sha256s=(),
    )
    with pytest.raises(
        W2DatabaseAuthorityError,
        match="non-owning aliases|exact 4/3/1 route algebra",
    ):
        _reseal_source_call(
            details_call,
            result_ownerships=(omitted_alias, *ownerships[1:]),
        )

    foreign_landing = _reseal_result_ownership(
        overall,
        canonical_owner_landing_sha256=(
            summary_call.result_ownerships[0].canonical_owner_landing_sha256
        ),
    )
    with pytest.raises(W2DatabaseAuthorityError, match="ownerships differ"):
        _reseal_source_call(
            details_call,
            result_ownerships=(foreign_landing, *ownerships[1:]),
        )

    swapped_occurrence = _reseal_result_ownership(
        overall,
        occurrence_sha256=ownerships[1].occurrence_sha256,
    )
    with pytest.raises(W2DatabaseAuthorityError, match="ownerships differ"):
        _reseal_source_call(
            details_call,
            result_ownerships=(swapped_occurrence, *ownerships[1:]),
        )
    with pytest.raises(W2DatabaseAuthorityError, match="crosses endpoint wrappers"):
        _reseal_source_call(
            details_call,
            result_ownerships=summary_call.result_ownerships,
        )

    swapped_pair = _reseal_pair(
        pair,
        details_source_call_sha256=pair.summary_source_call_sha256,
        summary_source_call_sha256=pair.details_source_call_sha256,
    )
    with pytest.raises(W2DatabaseAuthorityError, match="pairs differ"):
        _reseal_snapshot(first, pairs=(swapped_pair,))
    with pytest.raises(
        W2DatabaseAuthorityError,
        match="source-call snapshot route inventory crosses endpoint wrappers",
    ):
        replace(
            first.source_calls[0],
            logical_endpoint_name=_ON_OFF_ENDPOINTS[1],
        )
    with pytest.raises(FrozenInstanceError):
        first.selector_kind = "caller-selector"  # type: ignore[misc]


def test_on_off_selector_policy_matches_exact_runtime_and_route_registries() -> None:
    runtime_contracts = pinned_runtime_contracts()
    details = runtime_contracts["TeamPlayerOnOffDetails"]
    summary = runtime_contracts["TeamPlayerOnOffSummary"]

    assert details.parameters == _ON_OFF_RUNTIME_PARAMETER_DOMAIN
    assert summary.parameters == _ON_OFF_RUNTIME_PARAMETER_DOMAIN
    assert details.required_parameters == summary.required_parameters == ("team_id",)
    assert details.nullable_parameters == summary.nullable_parameters
    assert details.parameter_defaults == summary.parameter_defaults
    assert details.parameter_query_names == summary.parameter_query_names

    bundle = staging_route_contract_bundle()
    for endpoint_name in _ON_OFF_ENDPOINTS:
        routes = tuple(route for route in bundle.routes if route.endpoint_name == endpoint_name)
        policy = _ON_OFF_ROUTE_POLICY[endpoint_name]
        declared_ids = {
            route_id for _ordinal, owner, aliases in policy for route_id in (owner, *aliases)
        }
        owner_ids = {owner for _ordinal, owner, _aliases in policy}
        alias_ids = {alias for _ordinal, _owner, aliases in policy for alias in aliases}
        assert len(routes) == 4
        assert {route.route_id for route in routes} == declared_ids
        assert len(owner_ids) == 3
        assert len(alias_ids) == 1
        assert owner_ids.isdisjoint(alias_ids)
        assert set(assurance_module._fixed_on_off_route_contracts(endpoint_name)) == (declared_ids)


@pytest.mark.parametrize(
    ("endpoint_name", "provider_id"),
    [
        ("team_player_on_off_details", "TeamPlayerOnOffDetails"),
        ("team_player_on_off_summary", "TeamPlayerOnOffSummary"),
    ],
)
@pytest.mark.parametrize("missing_parameter", _ON_OFF_RUNTIME_PARAMETER_DOMAIN)
def test_on_off_selector_rejects_each_endpoint_runtime_parameter_domain_mutation(
    endpoint_name: str,
    provider_id: str,
    missing_parameter: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = dict(pinned_runtime_contracts())
    contract = contracts[provider_id]
    contracts[provider_id] = replace(
        contract,
        parameters=tuple(name for name in contract.parameters if name != missing_parameter),
    )
    monkeypatch.setattr(
        assurance_module,
        "pinned_runtime_contracts",
        lambda: contracts,
    )

    with pytest.raises(W2DatabaseAuthorityError, match="exact shared 21-field domain"):
        assurance_module._fixed_on_off_route_contracts(endpoint_name)


@pytest.mark.parametrize(
    ("endpoint_name", "provider_id"),
    [
        ("team_player_on_off_details", "TeamPlayerOnOffDetails"),
        ("team_player_on_off_summary", "TeamPlayerOnOffSummary"),
    ],
)
@pytest.mark.parametrize(
    "contract_field",
    [
        "required_parameters",
        "nullable_parameters",
        "parameter_defaults",
        "parameter_query_names",
    ],
)
def test_on_off_selector_rejects_each_endpoint_runtime_metadata_mutation(
    endpoint_name: str,
    provider_id: str,
    contract_field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = dict(pinned_runtime_contracts())
    contract = contracts[provider_id]
    current = getattr(contract, contract_field)
    contracts[provider_id] = replace(contract, **{contract_field: current[:-1]})
    monkeypatch.setattr(
        assurance_module,
        "pinned_runtime_contracts",
        lambda: contracts,
    )

    with pytest.raises(W2DatabaseAuthorityError, match="exact shared 21-field domain"):
        assurance_module._fixed_on_off_route_contracts(endpoint_name)


def test_on_off_snapshot_rejects_empty_fixed_selector(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    with pytest.raises(W2DatabaseAuthorityError, match="matched no logical calls"):
        verify_w2_on_off_database_snapshot(duckdb_memory_with_pipeline_tables)


@pytest.mark.parametrize(
    ("statements", "expected_value"),
    [
        (("UPDATE generation_probe SET value = 2",), 2),
        (
            (
                "UPDATE generation_probe SET value = 2",
                "UPDATE generation_probe SET value = 1",
            ),
            1,
        ),
    ],
    ids=("external-drift", "external-mutate-restore-aba"),
)
def test_on_off_snapshot_tripwire_rejects_external_connection_generation_activity(
    tmp_path: Path,
    statements: tuple[str, ...],
    expected_value: int,
) -> None:
    database_path = tmp_path / "w2-snapshot-tripwire.duckdb"
    primary = duckdb.connect(str(database_path))
    secondary = duckdb.connect(str(database_path))
    try:
        primary.execute("CREATE TABLE generation_probe (value INTEGER NOT NULL)")
        primary.execute("INSERT INTO generation_probe VALUES (1)")
        previous_transaction_id = assurance_module._current_transaction_id(primary)
        with assurance_module._verifier_owned_read_snapshot(
            primary,
            previous_transaction_id=previous_transaction_id,
        ) as snapshot_transaction_id:
            assert primary.execute("SELECT value FROM generation_probe").fetchone() == (1,)
        previous_transaction_id = assurance_module._close_snapshot_concurrency_tripwire(
            primary,
            snapshot_transaction_id=snapshot_transaction_id,
        )

        for statement in statements:
            secondary.execute(statement)

        with (
            pytest.raises(
                assurance_module._InternalAuthorityError,
                match="transaction activity changed before verifier snapshot admission",
            ),
            assurance_module._verifier_owned_read_snapshot(
                primary,
                previous_transaction_id=previous_transaction_id,
            ),
        ):
            pass
        assert primary.execute("SELECT value FROM generation_probe").fetchone() == (expected_value,)
    finally:
        secondary.close()
        primary.close()


def test_on_off_snapshot_public_api_rejects_external_mutate_restore_aba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "w2-public-snapshot.duckdb"
    manager = DBManager(
        sqlite_path=tmp_path / "w2-public-snapshot.sqlite",
        duckdb_path=database_path,
    )
    manager.init()
    primary = manager.duckdb
    secondary = duckdb.connect(str(database_path))
    try:
        _complete_on_off_pair(primary)
        original_close = assurance_module._close_snapshot_concurrency_tripwire
        close_calls = 0

        def mutate_restore_after_first_snapshot(
            target: duckdb.DuckDBPyConnection,
            *,
            snapshot_transaction_id: int,
        ) -> int:
            nonlocal close_calls
            next_transaction_id = original_close(
                target,
                snapshot_transaction_id=snapshot_transaction_id,
            )
            close_calls += 1
            if close_calls == 1:
                secondary.execute(
                    "UPDATE _extraction_journal "
                    "SET endpoint = 'franchise_history' WHERE endpoint = ?",
                    [_ON_OFF_ENDPOINTS[0]],
                )
                secondary.execute(
                    "UPDATE _extraction_journal SET endpoint = ? "
                    "WHERE endpoint = 'franchise_history'",
                    [_ON_OFF_ENDPOINTS[0]],
                )
            return next_transaction_id

        monkeypatch.setattr(
            assurance_module,
            "_close_snapshot_concurrency_tripwire",
            mutate_restore_after_first_snapshot,
        )
        with pytest.raises(
            W2DatabaseAuthorityError,
            match="transaction activity changed before verifier snapshot admission",
        ):
            verify_w2_on_off_database_snapshot(primary)

        assert close_calls == 1
        assert primary.execute(
            "SELECT endpoint FROM _extraction_journal WHERE endpoint IN (?, ?) ORDER BY endpoint",
            list(_ON_OFF_ENDPOINTS),
        ).fetchall() == [(name,) for name in _ON_OFF_ENDPOINTS]
        assert not assurance_module.raw_store_module._WRITE_LOCK._is_owned()
        assert not assurance_module.public_store_module._WRITE_LOCK._is_owned()
        assert not assurance_module.operation_store_module._WRITE_LOCK._is_owned()
        primary.execute("BEGIN TRANSACTION")
        primary.execute("ROLLBACK")
    finally:
        secondary.close()
        manager.close()


@pytest.mark.parametrize(
    "failure_stage",
    [
        "first_verification",
        "first_materialization",
        "second_verification",
        "second_materialization",
        "final_snapshot_construction",
    ],
)
def test_on_off_snapshot_injected_failures_close_transactions_and_release_all_locks(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    baseline = verify_w2_database_authority(connection, require_w2=False)
    verification_calls = 0
    materialization_calls = 0

    def staged_verification(*_args: object, **_kwargs: object) -> W2DatabaseAuthorityReceiptV1:
        nonlocal verification_calls
        assert assurance_module.raw_store_module._WRITE_LOCK._is_owned()
        assert assurance_module.public_store_module._WRITE_LOCK._is_owned()
        assert assurance_module.operation_store_module._WRITE_LOCK._is_owned()
        verification_calls += 1
        if failure_stage == "first_verification" and verification_calls == 1:
            assurance_module._fail("injected first verification failure")
        if failure_stage == "second_verification" and verification_calls == 2:
            assurance_module._fail("injected second verification failure")
        return W2DatabaseAuthorityReceiptV1.from_canonical_bytes(baseline.canonical_bytes())

    def staged_materialization(
        *_args: object,
        **_kwargs: object,
    ) -> tuple[W2OnOffSourceCallSnapshotV1, ...]:
        nonlocal materialization_calls
        assert assurance_module.raw_store_module._WRITE_LOCK._is_owned()
        assert assurance_module.public_store_module._WRITE_LOCK._is_owned()
        assert assurance_module.operation_store_module._WRITE_LOCK._is_owned()
        materialization_calls += 1
        if failure_stage == "first_materialization" and materialization_calls == 1:
            assurance_module._fail("injected first materialization failure")
        if failure_stage == "second_materialization" and materialization_calls == 2:
            assurance_module._fail("injected second materialization failure")
        return ()

    def staged_snapshot_construction(*_args: object, **_kwargs: object) -> None:
        assurance_module._fail("injected final snapshot construction failure")

    with monkeypatch.context() as isolated:
        isolated.setattr(assurance_module, "_verify_database", staged_verification)
        isolated.setattr(
            assurance_module,
            "_materialize_on_off_source_calls",
            staged_materialization,
        )
        if failure_stage == "final_snapshot_construction":
            isolated.setattr(
                assurance_module,
                "_build_on_off_database_snapshot",
                staged_snapshot_construction,
            )
        with pytest.raises(
            W2DatabaseAuthorityError,
            match="injected .* failure",
        ):
            verify_w2_on_off_database_snapshot(connection)

    assert not assurance_module.raw_store_module._WRITE_LOCK._is_owned()
    assert not assurance_module.public_store_module._WRITE_LOCK._is_owned()
    assert not assurance_module.operation_store_module._WRITE_LOCK._is_owned()
    connection.execute("BEGIN TRANSACTION")
    connection.execute("ROLLBACK")
    assert verify_w2_database_authority(connection, require_w2=False) == baseline


def test_on_off_snapshot_acquires_and_releases_persistence_locks_in_fixed_order(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str]] = []

    class OrderedLockProbe:
        def __init__(self, name: str) -> None:
            self.name = name
            self.owned = False

        def __enter__(self) -> OrderedLockProbe:
            assert not self.owned
            self.owned = True
            events.append(("enter", self.name))
            return self

        def __exit__(self, *_args: object) -> None:
            assert self.owned
            events.append(("exit", self.name))
            self.owned = False

        def _is_owned(self) -> bool:
            return self.owned

    raw_lock = OrderedLockProbe("raw")
    public_lock = OrderedLockProbe("public")
    operation_lock = OrderedLockProbe("operation")

    def fail_after_lock_acquisition(*_args: object, **_kwargs: object) -> None:
        assert raw_lock._is_owned()
        assert public_lock._is_owned()
        assert operation_lock._is_owned()
        assurance_module._fail("injected ordered-lock probe failure")

    monkeypatch.setattr(assurance_module.raw_store_module, "_WRITE_LOCK", raw_lock)
    monkeypatch.setattr(assurance_module.public_store_module, "_WRITE_LOCK", public_lock)
    monkeypatch.setattr(assurance_module.operation_store_module, "_WRITE_LOCK", operation_lock)
    monkeypatch.setattr(
        assurance_module,
        "_verify_database",
        fail_after_lock_acquisition,
    )

    with pytest.raises(W2DatabaseAuthorityError, match="ordered-lock probe failure"):
        verify_w2_on_off_database_snapshot(duckdb_memory_with_pipeline_tables)

    assert events == [
        ("enter", "raw"),
        ("enter", "public"),
        ("enter", "operation"),
        ("exit", "operation"),
        ("exit", "public"),
        ("exit", "raw"),
    ]


def test_on_off_snapshot_rejects_subset_metadata_partial_and_cross_journal_mutations(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    _complete_on_off_pair(connection)
    baseline = verify_w2_on_off_database_snapshot(connection)

    with pytest.raises(W2DatabaseAuthorityError, match="differs from its expected receipt"):
        verify_w2_on_off_database_snapshot(
            connection,
            expected_database_receipt_sha256="f" * 64,
        )

    connection.execute(
        "UPDATE _extraction_journal SET endpoint = 'franchise_history' WHERE endpoint = ?",
        [_ON_OFF_ENDPOINTS[0]],
    )
    with pytest.raises(W2DatabaseAuthorityError, match="denominators differ"):
        verify_w2_on_off_database_snapshot(connection)
    connection.execute(
        "UPDATE _extraction_journal SET endpoint = ? WHERE endpoint = 'franchise_history'",
        [_ON_OFF_ENDPOINTS[0]],
    )

    route_json = connection.execute(
        "SELECT result_route_ids_json FROM _extraction_journal WHERE endpoint = ?",
        [_ON_OFF_ENDPOINTS[0]],
    ).fetchone()[0]
    connection.execute(
        "UPDATE _extraction_journal SET result_route_ids_json = ? WHERE endpoint = ?",
        [f'["{_ON_OFF_ENDPOINTS[0]}:foreign:99"]', _ON_OFF_ENDPOINTS[0]],
    )
    with pytest.raises(
        W2DatabaseAuthorityError,
        match="on/off journal routes differ from the fixed canonical owners",
    ):
        verify_w2_on_off_database_snapshot(connection)
    connection.execute(
        "UPDATE _extraction_journal SET result_route_ids_json = ? WHERE endpoint = ?",
        [route_json, _ON_OFF_ENDPOINTS[0]],
    )

    admission_bytes = connection.execute(
        "SELECT w2_source_call_admission_bytes FROM _extraction_journal WHERE endpoint = ?",
        [_ON_OFF_ENDPOINTS[0]],
    ).fetchone()[0]
    connection.execute(
        "UPDATE _extraction_journal SET w2_source_call_admission_bytes = NULL WHERE endpoint = ?",
        [_ON_OFF_ENDPOINTS[0]],
    )
    with pytest.raises(W2DatabaseAuthorityError, match="lacks exact admission bytes"):
        verify_w2_on_off_database_snapshot(connection)
    connection.execute(
        "UPDATE _extraction_journal SET w2_source_call_admission_bytes = ? WHERE endpoint = ?",
        [admission_bytes, _ON_OFF_ENDPOINTS[0]],
    )

    PipelineJournal(connection, successor_generation_sha256="b" * 64)
    baseline_columns = tuple(
        str(row[1])
        for row in connection.execute("PRAGMA table_info('_extraction_journal')").fetchall()
    )
    quoted_columns = ", ".join(f'"{name}"' for name in baseline_columns)
    connection.execute(
        f"INSERT INTO _successor_extraction_journal "
        f"(successor_generation_sha256, {quoted_columns}) "
        f"SELECT ?, {quoted_columns} FROM _extraction_journal WHERE endpoint = ?",
        ["b" * 64, _ON_OFF_ENDPOINTS[0]],
    )
    with pytest.raises(W2DatabaseAuthorityError, match="duplicate or cross-call"):
        verify_w2_on_off_database_snapshot(connection)
    connection.execute(
        "DELETE FROM _successor_extraction_journal WHERE successor_generation_sha256 = ?",
        ["b" * 64],
    )

    original_materialize = assurance_module._materialize_on_off_source_calls
    materialize_calls = 0

    def mutate_inside_locked_snapshot(
        target: duckdb.DuckDBPyConnection,
        *,
        snapshot_transaction_id: int | None = None,
    ) -> tuple[object, ...]:
        nonlocal materialize_calls
        assert assurance_module.raw_store_module._WRITE_LOCK._is_owned()
        assert assurance_module.public_store_module._WRITE_LOCK._is_owned()
        assert assurance_module.operation_store_module._WRITE_LOCK._is_owned()
        materialize_calls += 1
        result = original_materialize(
            target,
            snapshot_transaction_id=snapshot_transaction_id,
        )
        return () if materialize_calls == 2 else result

    monkeypatch.setattr(
        assurance_module,
        "_materialize_on_off_source_calls",
        mutate_inside_locked_snapshot,
    )
    with pytest.raises(W2DatabaseAuthorityError, match="denominators differ|changed"):
        verify_w2_on_off_database_snapshot(
            connection,
            expected_database_receipt_sha256=baseline.database_authority.receipt_sha256,
        )
    assert materialize_calls == 2


def test_on_off_snapshot_rejects_legacy_unreceipted_matching_call(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    connection = duckdb_memory_with_pipeline_tables
    PipelineJournal(connection)
    parameters: dict[str, object] = {
        "date_from_nullable": "",
        "date_to_nullable": "",
        "game_segment_nullable": "",
        "last_n_games": "0",
        "league_id_nullable": "00",
        "location_nullable": "",
        "measure_type_detailed_defense": "Base",
        "month": "0",
        "opponent_team_id": 0,
        "outcome_nullable": "",
        "pace_adjust": "N",
        "per_mode_detailed": "Totals",
        "period": "0",
        "plus_minus": "N",
        "rank": "N",
        "season": "2024-25",
        "season_segment_nullable": "",
        "season_type_all_star": "Regular Season",
        "team_id": 1610612747,
        "vs_conference_nullable": "",
        "vs_division_nullable": "",
    }
    canonical_parameters = json.dumps(
        parameters,
        sort_keys=True,
        separators=(",", ":"),
    )
    canonical_routes = json.dumps(
        sorted(owner for _ordinal, owner, _aliases in _ON_OFF_ROUTE_POLICY[_ON_OFF_ENDPOINTS[0]]),
        separators=(",", ":"),
    )
    connection.execute(
        """
        INSERT INTO _extraction_journal
            (
                endpoint,
                params,
                logical_parameters_sha256,
                provider_authority_sha256,
                result_route_ids_json,
                logical_call_receipt_sha256,
                status,
                w2_required
            )
        VALUES (?, ?, ?, ?, ?, ?, 'done', FALSE)
        """,
        [
            _ON_OFF_ENDPOINTS[0],
            canonical_parameters,
            canonical_parameters_sha256(parameters),
            staging_route_contract_bundle().provider_authority_sha256,
            canonical_routes,
            _sha("legacy-unreceipted-matching-call"),
        ],
    )

    with pytest.raises(
        W2DatabaseAuthorityError,
        match="on/off journal call is legacy, partial, or not durably W2-complete",
    ):
        verify_w2_on_off_database_snapshot(connection)


def test_on_off_snapshot_api_has_no_caller_selector_or_sql_surface() -> None:
    assert assurance_module.__all__ == [
        "W2_ON_OFF_SELECTOR_KIND",
        "W2DatabaseAuthorityError",
        "W2DatabaseAuthorityReceiptV1",
        "W2OnOffDatabaseSnapshotV1",
        "W2OnOffPairSnapshotV1",
        "W2OnOffResultOwnershipV1",
        "W2OnOffSourceCallSnapshotV1",
        "verify_w2_database_authority",
        "verify_w2_on_off_database_snapshot",
    ]
    database_signature = inspect.signature(verify_w2_database_authority)
    snapshot_signature = inspect.signature(verify_w2_on_off_database_snapshot)

    assert tuple(database_signature.parameters) == (
        "connection",
        "require_w2",
        "expected_receipt_sha256",
    )
    assert database_signature.parameters["require_w2"].kind is (inspect.Parameter.KEYWORD_ONLY)
    assert database_signature.parameters["require_w2"].default is inspect.Parameter.empty
    assert database_signature.parameters["expected_receipt_sha256"].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )
    assert database_signature.parameters["expected_receipt_sha256"].default is None
    assert tuple(snapshot_signature.parameters) == (
        "connection",
        "expected_database_receipt_sha256",
    )
    assert snapshot_signature.parameters["expected_database_receipt_sha256"].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )
    assert snapshot_signature.parameters["expected_database_receipt_sha256"].default is None
    forbidden = {
        "endpoint",
        "logical_call",
        "predicate",
        "resolver",
        "route",
        "selector",
        "sql",
    }
    assert not any(
        token in name
        for name in (*database_signature.parameters, *snapshot_signature.parameters)
        for token in forbidden
    )


def test_on_off_snapshot_dtos_are_structurally_frozen() -> None:
    expected_fields = {
        W2DatabaseAuthorityReceiptV1: (
            "receipt_sha256",
            "w2_required_logical_call_count",
            "w2_source_call_admission_inventory_sha256",
            "raw_authority_v2_bundle_count",
            "raw_authority_v2_bundle_inventory_sha256",
            "raw_authority_v2_persistence_receipt_inventory_sha256",
            "w2_publication_receipt_count",
            "w2_publication_receipt_inventory_sha256",
            "w2_exact_six_schema_inventory_sha256",
            "w2_relation_row_counts",
            "w2_relation_row_count",
            "w2_relation_inventory_sha256",
        ),
        W2OnOffResultOwnershipV1: (
            "ownership_sha256",
            "result_set_ordinal",
            "result_set_name",
            "occurrence_sha256",
            "declared_route_ids",
            "declared_route_contract_sha256s",
            "canonical_owner_route_id",
            "canonical_owner_route_contract_sha256",
            "canonical_owner_landing_sha256",
            "non_owning_alias_route_ids",
            "non_owning_alias_route_contract_sha256s",
        ),
        W2OnOffSourceCallSnapshotV1: (
            "source_call_sha256",
            "journal_table_name",
            "successor_generation_sha256",
            "logical_endpoint_name",
            "logical_parameters_json",
            "logical_parameters_sha256",
            "shared_pair_scope_json",
            "shared_pair_scope_sha256",
            "provider_authority_sha256",
            "declared_result_route_ids",
            "declared_result_route_count",
            "declared_result_route_inventory_sha256",
            "canonical_owner_route_ids",
            "canonical_owner_route_count",
            "canonical_owner_route_inventory_sha256",
            "non_owning_alias_route_ids",
            "non_owning_alias_route_count",
            "non_owning_alias_route_inventory_sha256",
            "result_ownerships",
            "logical_call_receipt_sha256",
            "admission",
            "raw_authority_bundle",
            "result_cells",
            "result_cell_count",
            "result_cell_inventory_sha256",
        ),
        W2OnOffPairSnapshotV1: (
            "pair_sha256",
            "shared_pair_scope_json",
            "shared_pair_scope_sha256",
            "journal_table_name",
            "successor_generation_sha256",
            "provider_authority_sha256",
            "details_source_call_sha256",
            "summary_source_call_sha256",
            "declared_result_route_count",
            "declared_result_route_inventory_sha256",
            "canonical_owner_route_count",
            "canonical_owner_route_inventory_sha256",
            "non_owning_alias_route_count",
            "non_owning_alias_route_inventory_sha256",
        ),
        W2OnOffDatabaseSnapshotV1: (
            "snapshot_sha256",
            "selector_kind",
            "database_authority",
            "database_generation_sha256",
            "selected_pair_count",
            "selected_pair_inventory_sha256",
            "selected_logical_call_count",
            "selected_logical_call_inventory_sha256",
            "selected_observation_count",
            "selected_observation_inventory_sha256",
            "selected_occurrence_count",
            "selected_occurrence_inventory_sha256",
            "selected_result_cell_count",
            "selected_result_cell_inventory_sha256",
            "pairs",
            "source_calls",
        ),
    }

    for dto, field_names in expected_fields.items():
        assert dto.__dataclass_params__.frozen
        assert tuple(item.name for item in fields(dto)) == field_names
        assert all("transaction" not in name for name in field_names)
