from __future__ import annotations

import hashlib
import json
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast
from unittest.mock import patch

import duckdb
import polars as pl
import pytest

from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    canonical_json_bytes,
)
from nbadb.contracts.raw_request_finalization import finalize_raw_request_capture
from nbadb.contracts.raw_request_reconstruction import LiveSnapshotPlanAuthorityV2
from nbadb.contracts.staging_route_contract import (
    StagingRouteContract,
    staging_route_contract_bundle,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    owned_contract_sha256,
    pinned_live_contracts,
    pinned_runtime_contracts,
    pinned_static_dataset_contract,
)
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
from nbadb.extract.nba_api_adapter import (
    RawAuthorityStatsResultRows,
    rederive_raw_authority_result_sets,
    rederive_raw_authority_route_frames,
    rederive_raw_authority_stats_rows,
    rows_to_polars,
)
from nbadb.extract.raw_request_capture import (
    PendingRawRequestSuccessV2,
    PendingResultOccurrenceV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.orchestrate import raw_request_store as store_module
from nbadb.orchestrate.raw_request_store import (
    RawRequestAuthorityStore,
    RawRequestClosureCallV2,
    RawRequestManifestAuthorityV2,
    compile_raw_request_manifest_authority,
)
from nbadb.orchestrate.scanner import DataScanner, ScanSeverity
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    CommittedStagingChunkReceiptV2,
    frame_content_hash,
    frame_schema_hash,
)
from nbadb.schemas.registry import get_input_schema

if TYPE_CHECKING:
    from pathlib import Path

_SOURCE_SHA = "a" * 40
_STARTED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _sha(value: str | bytes) -> str:
    encoded = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _attempt(
    source_family: Literal["stats", "live", "static"],
    endpoint_id: str,
    ordinal: int,
    *,
    parameters: dict[str, object] | None = None,
    competition_id: str | None = None,
    competition_identity_sha256: str | None = None,
    scope_sha256: str | None = None,
    lane_id: str = "lane",
) -> RequestAttemptIdentityV2:
    if source_family == "stats":
        contract_sha256 = endpoint_contract_sha256(pinned_runtime_contracts()[endpoint_id])
    elif source_family == "live":
        contract_sha256 = owned_contract_sha256(pinned_live_contracts()[endpoint_id])
    else:
        contract_sha256 = owned_contract_sha256(pinned_static_dataset_contract(endpoint_id))
    return RequestAttemptIdentityV2.build(
        semantic_request_sha256=_sha(f"semantic:{ordinal}"),
        logical_invocation_sha256=_sha(f"logical:{ordinal}"),
        provider_call_role="static_snapshot" if source_family == "static" else "primary",
        provider_call_ordinal=0,
        retry_ordinal=0,
        request_ordinal=0,
        source_family=source_family,
        endpoint_id=endpoint_id,
        parameters=(
            parameters
            if parameters is not None
            else {"season": "2025-26"}
            if source_family == "stats"
            else {}
        ),
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256=contract_sha256,
        competition_id=competition_id,
        competition_identity_sha256=competition_identity_sha256,
        scope_sha256=scope_sha256 or _sha(f"scope:{ordinal}"),
        pagination_sha256=None,
        page_ordinal=None,
        source_sha=_SOURCE_SHA,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id=lane_id,
    )


def _logical_receipt(attempt: RequestAttemptIdentityV2) -> str:
    return _sha(f"logical-receipt:{attempt.attempt_sha256}")


def _stats_frame(
    route: StagingRouteContract,
    result_rows: RawAuthorityStatsResultRows,
    *,
    safe_parameters_json: str,
) -> pl.DataFrame:
    ordered_headers = result_rows.ordered_headers
    rows = result_rows.rows
    values = tuple(tuple(json.loads(cell.canonical_json) for cell in row) for row in rows)
    frame = rows_to_polars(ordered_headers, values)
    canonical_columns = tuple(item.canonical_column for item in route.column_mappings)
    frame = frame.rename(dict(zip(ordered_headers, canonical_columns, strict=True)))
    schema_cls = get_input_schema(route.staging_key)
    assert schema_cls is not None
    schema = schema_cls.to_schema()
    assert tuple(schema.columns) == route.storage_columns
    frame = frame.select(
        [
            (
                pl.col(column)
                if column in frame.columns
                else pl.lit(None).cast(schema.columns[column].dtype.type)
            ).alias(column)
            for column in route.storage_columns
        ]
    )
    frame = schema_cls.validate(frame)
    assert isinstance(frame, pl.DataFrame)
    parameters = cast("dict[str, object]", json.loads(safe_parameters_json))

    def first(*keys: str) -> object | None:
        return next(
            (
                parameters[key]
                for key in keys
                if parameters.get(key) is not None and parameters.get(key) != ""
            ),
            None,
        )

    additions: list[pl.Expr] = []
    for column_name, value in (
        ("season_year", first("season", "season_nullable", "season_year")),
        (
            "season_type",
            first(
                "season_type_all_star",
                "season_type_playoffs",
                "season_type",
                "season_type_nullable",
                "season_type_all_star_nullable",
            ),
        ),
        ("league_id", first("league_id", "league_id_nullable")),
    ):
        if value is not None and column_name not in frame.columns:
            additions.append(pl.lit(value).alias(column_name))
    return frame.with_columns(additions) if additions else frame


def _committed_frame_receipt(
    binding: LogicalCallReceiptBinding,
    *,
    route_id: str,
    staging_key: str,
    frame: pl.DataFrame,
) -> CommittedStagingChunkReceiptV2:
    content_sha256 = frame_content_hash(frame)
    return CommittedStagingChunkReceiptV2(
        chunk_id=f"chunk:{_sha(route_id)[:16]}",
        staging_key=staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=content_sha256,
        persisted_row_count=frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(frame),
        logical_call_receipt_sha256=binding.logical_call_receipt_sha256,
        provider_authority_sha256=binding.provider_authority_sha256,
        logical_parameters_sha256=binding.logical_parameters_sha256,
        result_route_id=route_id,
    )


def _exact_case_bundle(
    *,
    source_family: Literal["stats", "live", "static"],
    endpoint_name: str,
    endpoint_id: str,
    ordinal: int,
    parser_input: bytes | None,
    parameters: dict[str, object] | None = None,
    competition_id: str | None = None,
    competition_identity_sha256: str | None = None,
    scope_sha256: str | None = None,
    lane_id: str = "lane",
) -> RawRequestAuthorityBundleV2:
    attempt = _attempt(
        source_family,
        endpoint_id,
        ordinal,
        parameters=parameters,
        competition_id=competition_id,
        competition_identity_sha256=competition_identity_sha256,
        scope_sha256=scope_sha256,
        lane_id=lane_id,
    )
    fixed_routes = tuple(
        sorted(
            (
                route
                for route in staging_route_contract_bundle().routes
                if route.endpoint_name == endpoint_name
                and route.source_family == source_family
                and route.provider_endpoint_id == endpoint_id
            ),
            key=lambda item: item.ordinal,
        )
    )
    assert fixed_routes
    conditional_route_ids: tuple[str, ...] = ()
    if source_family == "live":
        conditional_route_ids = (
            f"{endpoint_name}:{LIVE_LOSSLESS_STAGING_KEY}:"
            f"{len(pinned_live_contracts()[endpoint_id].result_sets)}",
        )
    route_ids = tuple(sorted((*[route.route_id for route in fixed_routes], *conditional_route_ids)))
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=_logical_receipt(attempt),
        endpoint_name=endpoint_name,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        result_route_ids=route_ids,
    )
    derivations = rederive_raw_authority_result_sets(
        source_family=source_family,
        endpoint_id=endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    body = (
        None
        if parser_input is None
        else ParserInputObjectV2.from_parser_input(parser_input.decode("utf-8"))
    )
    pending = PendingRawRequestSuccessV2(
        private_receipt_sha256=_sha(f"capture-response:{attempt.attempt_sha256}"),
        attempt=attempt,
        transport=(
            {"transport_kind": "static_snapshot"}
            if source_family == "static"
            else {
                "transport_kind": f"{source_family}_http",
                "status_code": 200,
                "effective_status_code": 200,
            }
        ),
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        outcome=(
            "static_snapshot_success"
            if source_family == "static"
            else "success_nonempty"
            if any(item.result_set.row_count for item in derivations)
            else "success_empty"
        ),
        body_disposition=(
            "declared_bodyless" if source_family == "static" else "public_parser_input"
        ),
        body_object=body,
        results=tuple(
            PendingResultOccurrenceV2(
                result_set=item.result_set,
                duplicate_name_ordinal=item.duplicate_name_ordinal,
                ordered_headers=item.ordered_headers,
            )
            for item in derivations
        ),
        logical_receipt_sha256=binding.logical_call_receipt_sha256,
        aggregate_route_ids=binding.result_route_ids,
    )
    receipts: list[CommittedStagingChunkReceiptV2] = []
    if source_family in {"static", "live"}:
        frame_derivations = rederive_raw_authority_route_frames(
            source_family=source_family,
            endpoint_name=endpoint_name,
            endpoint_id=endpoint_id,
            selected_route_ids=route_ids,
            parser_input=parser_input,
            safe_parameters_json=attempt.safe_parameters_json,
            provider_authority_sha256=attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
            capture_response_receipt_sha256=pending.private_receipt_sha256,
            live_snapshot_at=_STARTED_AT if source_family == "live" else None,
        )
        receipts.extend(
            _committed_frame_receipt(
                binding,
                route_id=item.route_id,
                staging_key=item.staging_key,
                frame=item.frame,
            )
            for item in frame_derivations
        )
    else:
        assert parser_input is not None
        safe_rows = rederive_raw_authority_stats_rows(
            endpoint_id=endpoint_id,
            parser_input=parser_input,
            provider_authority_sha256=attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
        )
        for route in fixed_routes:
            candidates = tuple(
                item
                for item in safe_rows
                if item.result_set.canonical_index == route.canonical_result_set_ordinal
                and item.ordered_headers == route.provider_columns
            )
            assert len(candidates) == 1
            receipts.append(
                _committed_frame_receipt(
                    binding,
                    route_id=route.route_id,
                    staging_key=route.staging_key,
                    frame=_stats_frame(
                        route,
                        candidates[0],
                        safe_parameters_json=attempt.safe_parameters_json,
                    ),
                )
            )
    snapshot = RawRequestCaptureSnapshotV2(
        objects=() if body is None else (body,),
        observations=(),
        pending_successes=(pending,),
        issues=(),
    )
    live_plan_authority = (
        LiveSnapshotPlanAuthorityV2.build(
            sealed_plan_bytes=b'{"kind":"scanner_test_live_sealed_plan_v2"}',
            attempt=attempt,
            route_ids=tuple((*[route.route_id for route in fixed_routes], *conditional_route_ids)),
            live_snapshot_at=_STARTED_AT,
        )
        if source_family == "live"
        else None
    )
    return finalize_raw_request_capture(
        snapshot,
        binding,
        tuple(sorted(receipts, key=lambda item: item.result_route_id)),
        live_plan_authority=live_plan_authority,
        expected_live_plan_authority_sha256=(
            live_plan_authority.authority_sha256 if live_plan_authority is not None else None
        ),
    )


def _stats_case(
    ordinal: int = 0,
) -> tuple[
    ParserInputObjectV2,
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    expected = pinned_runtime_contracts()["LeagueGameLog"].result_sets[0]
    assert expected.result_set_name is not None
    parser_input = json.dumps(
        {
            "resultSets": [
                {
                    "name": expected.result_set_name,
                    "headers": list(expected.expected_columns),
                    "rowSet": [],
                }
            ]
        },
        separators=(",", ":"),
    )
    bundle = _exact_case_bundle(
        source_family="stats",
        endpoint_name="league_game_log",
        endpoint_id="LeagueGameLog",
        ordinal=ordinal,
        parser_input=parser_input.encode("utf-8"),
    )
    return bundle.objects[0], bundle.observations[0], bundle.occurrences, bundle.landings


def _static_case(
    ordinal: int = 1,
    *,
    endpoint_id: str = "static_players",
) -> tuple[
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    bundle = _exact_case_bundle(
        source_family="static",
        endpoint_name=endpoint_id,
        endpoint_id=endpoint_id,
        ordinal=ordinal,
        parser_input=None,
    )
    return bundle.observations[0], bundle.occurrences, bundle.landings


def _live_parent_empty_case(
    ordinal: int = 2,
) -> tuple[
    ParserInputObjectV2,
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    parser_input = '{"meta":{"version":1},"scoreboard":{"games":[]}}'
    bundle = _exact_case_bundle(
        source_family="live",
        endpoint_name="live_score_board",
        endpoint_id="ScoreBoard",
        ordinal=ordinal,
        parser_input=parser_input.encode("utf-8"),
    )
    return bundle.objects[0], bundle.observations[0], bundle.occurrences, bundle.landings


def _bundle(kind: Literal["combined", "stats", "static", "live"]) -> RawRequestAuthorityBundleV2:
    objects: list[ParserInputObjectV2] = []
    observations: list[RequestObservationV2] = []
    occurrences: list[ResultOccurrenceV2] = []
    landings: list[ObservationRouteLandingV2] = []
    if kind in {"combined", "stats"}:
        body, observation, rows, route_landings = _stats_case()
        objects.append(body)
        observations.append(observation)
        occurrences.extend(rows)
        landings.extend(route_landings)
    if kind in {"combined", "static"}:
        observation, rows, route_landings = _static_case()
        observations.append(observation)
        occurrences.extend(rows)
        landings.extend(route_landings)
    if kind == "live":
        body, observation, rows, route_landings = _live_parent_empty_case()
        objects.append(body)
        observations.append(observation)
        occurrences.extend(rows)
        landings.extend(route_landings)
    return RawRequestAuthorityBundleV2.build(
        objects=objects,
        observations=observations,
        occurrences=occurrences,
        landings=tuple(
            sorted(landings, key=lambda item: (item.observation_sha256, item.route_ordinal))
        ),
    )


def _persist(
    connection: duckdb.DuckDBPyConnection,
    kind: Literal["combined", "stats", "static", "live"] = "combined",
) -> RawRequestAuthorityBundleV2:
    bundle = _bundle(kind)
    RawRequestAuthorityStore(connection).persist_bundle(bundle)
    return bundle


def _scan_only_private_raw(
    connection: duckdb.DuckDBPyConnection,
):
    scanner = DataScanner(connection)
    with ExitStack() as stack:
        stack.enter_context(patch.object(scanner, "_check_request_closure_inventory"))
        stack.enter_context(patch.object(scanner, "_check_full_publication_request_authority_join"))
        return scanner.scan_private_capture()


def _raw_errors(report) -> list[object]:
    return [
        finding
        for finding in report.filter(severity=ScanSeverity.ERROR)
        if finding.table in {"raw_request_authority", "raw_request_authority_private"}
    ]


def _verified_evidence(report) -> dict[str, object]:
    evidence = report.evidence["raw_request_authority"]
    assert evidence["evidence_code"] == "raw_authority_reconstruction_verified"
    return evidence


def test_private_capture_scanner_reconstructs_exact_fixed_raw_inventory() -> None:
    connection = duckdb.connect(":memory:")
    try:
        bundle = _persist(connection)

        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    assert _raw_errors(report) == []
    evidence = _verified_evidence(report)
    assert evidence["bundle_sha256"] == bundle.bundle_sha256
    assert evidence["object_count"] == 1
    assert evidence["observation_count"] == 2
    assert evidence["occurrence_count"] == 2
    assert evidence["landing_count"] == 2
    assert evidence["parsed_body_count"] == 1
    assert evidence["bodyless_observation_count"] == 1
    assert evidence["parent_empty_packet_count"] == 0
    assert len(cast("str", evidence["route_landing_inventory_sha256"])) == 64
    assert len(cast("str", evidence["assurance_sha256"])) == 64
    assert report.to_dict()["evidence"]["raw_request_authority"] == evidence


def test_private_capture_scanner_preserves_declared_bodyless_authority() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist(connection, "static")

        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    assert _raw_errors(report) == []
    details = _verified_evidence(report)
    assert details["parsed_body_count"] == 0
    assert details["bodyless_observation_count"] == 1
    assert details["result_packet_count"] == 1


def test_private_capture_scanner_rejects_live_without_persisted_sealed_plan() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist(connection, "live")

        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    errors = _raw_errors(report)
    assert len(errors) == 1
    assert errors[0].check == "raw_authority_reconstruction_failed"
    assert errors[0].details["verification_stage"] == "reconstruction"
    assert errors[0].details["verified_observation_count"] == 0
    assert "raw_request_authority" not in report.evidence


def test_private_capture_scanner_fails_closed_on_public_row_corruption() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist(connection, "stats")
        connection.execute(
            "UPDATE raw_nba_api_result_occurrence SET route_receipt_sha256 = ?",
            ["0" * 64],
        )

        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    errors = _raw_errors(report)
    assert len(errors) == 1
    assert errors[0].check == "raw_authority_rows_malformed"
    assert errors[0].details["verified_observation_count"] == 0
    assert "input_value" not in errors[0].message


def test_private_capture_scanner_rejects_stats_occurrence_not_derived_from_body() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist(connection, "stats")
        connection.execute(
            "UPDATE raw_nba_api_request_observation SET body_object_sha256 = ?",
            ["f" * 64],
        )
        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    errors = _raw_errors(report)
    assert len(errors) == 1
    assert errors[0].check == "raw_authority_bundle_invalid"
    assert errors[0].details["verified_observation_count"] == 0


def test_private_capture_scanner_rejects_live_occurrence_not_derived_from_body() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist(connection, "live")
        connection.execute(
            "UPDATE raw_nba_api_request_observation SET body_object_sha256 = ?",
            ["f" * 64],
        )
        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    errors = _raw_errors(report)
    assert len(errors) == 1
    assert errors[0].check == "raw_authority_bundle_invalid"
    assert errors[0].details["verified_observation_count"] == 0


def test_private_capture_scanner_rejects_static_occurrence_not_derived_from_pin() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist(connection, "static")
        connection.execute(
            "UPDATE raw_nba_api_result_occurrence SET output_sha256 = ?",
            ["f" * 64],
        )
        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    errors = _raw_errors(report)
    assert len(errors) == 1
    assert errors[0].check == "raw_authority_rows_malformed"
    assert errors[0].details["verified_observation_count"] == 0


def test_private_capture_scanner_rejects_foreign_endpoint_contract() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist(connection, "stats")
        connection.execute(
            "UPDATE raw_nba_api_request_observation SET endpoint_contract_sha256 = ?",
            ["f" * 64],
        )
        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    errors = _raw_errors(report)
    assert len(errors) == 1
    assert errors[0].check == "raw_authority_rows_malformed"
    assert errors[0].details["verified_observation_count"] == 0


def test_private_capture_scanner_pages_observations_and_preserves_bundle_identity() -> None:
    connection = duckdb.connect(":memory:")
    try:
        bundle = _persist(connection, "combined")
        with patch.object(DataScanner, "_RAW_AUTHORITY_PAGE_SIZE", 1):
            report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    assert _raw_errors(report) == []
    evidence = _verified_evidence(report)
    assert evidence["bundle_sha256"] == bundle.bundle_sha256
    assert evidence["observation_count"] == 2


def test_private_capture_scanner_reconstructs_global_v2_bundle_identity() -> None:
    connection = duckdb.connect(":memory:")
    try:
        bundle = _persist(connection, "combined")
        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    assert _raw_errors(report) == []
    evidence = _verified_evidence(report)
    assert evidence["bundle_sha256"] == bundle.bundle_sha256
    assert evidence["observation_count"] == 2
    assert evidence["landing_count"] == len(bundle.landings)


@pytest.mark.parametrize(
    "table_name",
    (
        "raw_nba_api_parser_input_object",
        "raw_nba_api_request_observation",
        "raw_nba_api_result_occurrence",
        "raw_nba_api_observation_route_landing",
    ),
)
def test_private_capture_scanner_requires_every_fixed_raw_table(table_name: str) -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist(connection, "stats")
        connection.execute(f'DROP TABLE "{table_name}"')

        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    errors = _raw_errors(report)
    assert len(errors) == 1
    assert errors[0].check == "missing_private_raw_authority_tables"
    assert errors[0].details["missing_tables"] == [table_name]


def test_private_capture_scanner_accepts_unrelated_shadow_raw_table() -> None:
    """Unexpected extra raw tables are a public-admission concern, not private."""

    connection = duckdb.connect(":memory:")
    try:
        _persist(connection, "stats")
        connection.execute('CREATE TABLE "raw_nba_api_shadow" (marker INTEGER)')

        report = _scan_only_private_raw(connection)
    finally:
        connection.close()

    assert _raw_errors(report) == []


def test_public_full_scan_rejects_private_raw_authority_tables() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist(connection, "stats")
        with ExitStack() as stack:
            scanner = DataScanner(connection)
            stack.enter_context(patch.object(scanner, "_assure_transformer_discovery"))
            stack.enter_context(
                patch.object(scanner, "_check_full_publication_w2_database_authority")
            )
            stack.enter_context(patch.object(scanner, "_check_request_closure_inventory"))
            stack.enter_context(patch.object(scanner, "_check_full_publication_anchors"))
            stack.enter_context(patch.object(scanner, "_check_full_publication_cardinality"))
            report = scanner.scan(
                categories=["raw_authority_inventory_only"], full_publication=True
            )
    finally:
        connection.close()

    errors = [
        finding
        for finding in report.filter(severity=ScanSeverity.ERROR)
        if finding.table == "raw_request_authority_private"
    ]
    assert len(errors) == 1
    assert errors[0].check == "private_raw_authority_publication_leak"
    assert sorted(errors[0].details["leaked_tables"]) == sorted(
        (
            "raw_nba_api_parser_input_object",
            "raw_nba_api_request_observation",
            "raw_nba_api_result_occurrence",
            "raw_nba_api_observation_route_landing",
        )
    )


def test_public_full_scan_admits_tree_without_private_raw_tables() -> None:
    connection = duckdb.connect(":memory:")
    try:
        with ExitStack() as stack:
            scanner = DataScanner(connection)
            stack.enter_context(patch.object(scanner, "_assure_transformer_discovery"))
            stack.enter_context(
                patch.object(scanner, "_check_full_publication_w2_database_authority")
            )
            stack.enter_context(patch.object(scanner, "_check_request_closure_inventory"))
            stack.enter_context(patch.object(scanner, "_check_full_publication_anchors"))
            stack.enter_context(patch.object(scanner, "_check_full_publication_cardinality"))
            report = scanner.scan(
                categories=["raw_authority_inventory_only"], full_publication=True
            )
    finally:
        connection.close()

    assert not [
        finding
        for finding in report.filter(severity=ScanSeverity.ERROR)
        if finding.table == "raw_request_authority_private"
    ]
    exclusion = report.evidence["private_raw_authority_exclusion"]
    assert exclusion["evidence_code"] == "private_raw_authority_absent"


def test_private_capture_raw_reconstruction_never_writes_database(tmp_path: Path) -> None:
    database_path = tmp_path / "raw-authority.duckdb"
    writer = duckdb.connect(str(database_path))
    try:
        _persist(writer, "combined")
        writer.execute("CHECKPOINT")
    finally:
        writer.close()
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()

    reader = duckdb.connect(str(database_path), read_only=True)
    try:
        report = _scan_only_private_raw(reader)
    finally:
        reader.close()

    after = hashlib.sha256(database_path.read_bytes()).hexdigest()
    assert _raw_errors(report) == []
    assert before == after


def test_non_full_scan_does_not_require_or_read_raw_authority_tables() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute('CREATE TABLE "raw_foreign_shape" (marker INTEGER)')

        scanner = DataScanner(connection)
        with patch.object(scanner, "_assure_transformer_discovery"):
            report = scanner.scan(categories=["missing_table"])
    finally:
        connection.close()

    assert _raw_errors(report) == []
    assert "raw_request_authority" not in report.evidence
    assert "raw_request_authority_private" not in report.evidence


_FOUR_STATIC_ENDPOINTS = (
    "static_players",
    "static_teams",
    "static_wnba_players",
    "static_wnba_teams",
)


def _four_static_bundle() -> RawRequestAuthorityBundleV2:
    observations: list[RequestObservationV2] = []
    occurrences: list[ResultOccurrenceV2] = []
    landings: list[ObservationRouteLandingV2] = []
    for ordinal, endpoint_id in enumerate(_FOUR_STATIC_ENDPOINTS, start=10):
        observation, rows, route_landings = _static_case(
            ordinal,
            endpoint_id=endpoint_id,
        )
        observations.append(observation)
        occurrences.extend(rows)
        landings.extend(route_landings)
    return RawRequestAuthorityBundleV2.build(
        objects=(),
        observations=observations,
        occurrences=occurrences,
        landings=tuple(
            sorted(landings, key=lambda item: (item.observation_sha256, item.route_ordinal))
        ),
    )


def _issue_test_manifest_authority(
    unsigned: RawRequestManifestAuthorityV2,
) -> RawRequestManifestAuthorityV2:
    with patch.object(
        store_module,
        "_compile_raw_request_manifest_authority_impl",
        return_value=unsigned,
    ):
        return compile_raw_request_manifest_authority(
            None,  # type: ignore[arg-type]
            None,
            assurance_authority=None,  # type: ignore[arg-type]
        )


def _manifest_authority(bundle: RawRequestAuthorityBundleV2) -> RawRequestManifestAuthorityV2:
    routes_by_observation: dict[str, set[str]] = {
        item.attempt.observation_sha256: set() for item in bundle.observations
    }
    for landing in bundle.landings:
        routes_by_observation[landing.observation_sha256].add(landing.route_id)
    endpoint_names = {
        observation.attempt.observation_sha256: next(
            landing.route_id.split(":", 1)[0]
            for landing in bundle.landings
            if landing.observation_sha256 == observation.attempt.observation_sha256
        )
        for observation in bundle.observations
    }
    calls = tuple(
        sorted(
            (
                RawRequestClosureCallV2.build(
                    endpoint_name=endpoint_names[observation.attempt.observation_sha256],
                    source_family=observation.attempt.source_family,
                    endpoint_id=observation.attempt.endpoint_id,
                    logical_parameters_sha256=(observation.attempt.safe_parameters_sha256),
                    provider_parameters_sha256=(observation.attempt.safe_parameters_sha256),
                    provider_request_sha256=(observation.attempt.provider_request_sha256),
                    route_ids=tuple(
                        sorted(routes_by_observation[observation.attempt.observation_sha256])
                    ),
                    scope_sha256=observation.attempt.scope_sha256,
                )
                for observation in bundle.observations
            ),
            key=lambda item: item.logical_request_sha256,
        )
    )
    scope_sha256 = (
        calls[0].scope_sha256
        if len(calls) == 1
        else _sha(
            canonical_json_bytes(
                {
                    "schema_version": 2,
                    "kind": "nbadb_raw_request_composite_scope_v2",
                    "logical_requests": [
                        {
                            "logical_request_sha256": item.logical_request_sha256,
                            "scope_sha256": item.scope_sha256,
                        }
                        for item in calls
                    ],
                }
            )
        )
    )
    first = bundle.observations[0].attempt
    return _issue_test_manifest_authority(
        RawRequestManifestAuthorityV2(
            source_sha=first.source_sha,
            run_id=first.run_id,
            run_attempt=first.run_attempt,
            chain_id=first.chain_id,
            lane_id=first.lane_id,
            scope_sha256=scope_sha256,
            route_authority_sha256=_sha("route-authority"),
            request_closure_authority_sha256=_sha("closure-authority"),
            field_authority_sha256=_sha("field-authority"),
            model_authority_sha256=_sha("model-authority"),
            expected_calls=calls,
            compiler_provenance_sha256="0" * 64,
        )
    )


def _persist_manifest(
    connection: duckdb.DuckDBPyConnection,
    *,
    expected_bundle: RawRequestAuthorityBundleV2,
    persisted_bundle: RawRequestAuthorityBundleV2 | None = None,
    terminal: bool,
) -> None:
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(persisted_bundle or expected_bundle)
    store.advance_manifest(
        _manifest_authority(expected_bundle),
        (receipt,),
        terminal=terminal,
    )


def _stats_manifest_and_closure(
    *,
    season: str,
) -> tuple[
    RawRequestAuthorityBundleV2,
    RawRequestManifestAuthorityV2,
    object,
]:
    from nbadb.core.nba_api_request_surface import (
        RequestScopeDimension,
        RequestScopeManifest,
        materialize_provider_request,
        pinned_request_surface_authority,
    )
    from nbadb.core.nba_api_terminal_state import build_terminal_request_binding
    from nbadb.extract.bronze import canonical_parameters_sha256
    from nbadb.orchestrate.request_closure_runtime import (
        PersistedStagingReceipt,
        RequestClosureAdapterInput,
        RequestObservation,
        ResultSetReceipt,
        RouteRequestSpecInput,
        build_authoritative_route_manifest,
        build_request_closure_runtime_receipt,
    )

    params: dict[str, object] = {
        "is_only_current_season": 0,
        "league_id": "00",
        "season": season,
    }
    endpoint_id = "CommonAllPlayers"
    endpoint_name = "common_all_players"
    route_id = f"{endpoint_name}:stg_common_all_players:0"
    pinned = pinned_request_surface_authority()
    route_manifest = build_authoritative_route_manifest(
        (
            RouteRequestSpecInput(
                route_id=route_id,
                source_family="stats",
                endpoint_id=endpoint_id,
                parameters=tuple(sorted(params.items())),
            ),
        )
    )
    endpoint = pinned.endpoint("stats", endpoint_id)
    request = materialize_provider_request(
        endpoint,
        params,
        request_surface_sha256=pinned.surface_sha256,
        runtime_contract_payload_sha256=pinned.runtime_contract_payload_sha256,
    )
    materialized = dict(request.materialized_parameters)
    dimensions = []
    dependency_ids = sorted(
        {dependency for parameter in endpoint.parameters for dependency in parameter.dependencies}
    )
    for dependency_id in dependency_ids:
        values = {
            materialized[parameter.name]
            for parameter in endpoint.parameters
            if dependency_id in parameter.dependencies
        }
        dimensions.append(
            RequestScopeDimension(
                dependency_id=dependency_id,
                source_kind="raw_publication_scanner_test",
                source_authority_sha256="a" * 64,
                values=tuple(sorted(values, key=canonical_json_bytes)),
            )
        )
    scope = RequestScopeManifest(
        request_surface_sha256=pinned.surface_sha256,
        scope_id=f"raw_publication_scanner_{season.replace('-', '_')}",
        seed_route_ids=(route_id,),
        dimensions=tuple(sorted(dimensions, key=lambda item: item.dimension_sha256)),
    )
    source_request_sha256 = _sha(f"stats-source-request:{season}")
    request_binding = build_terminal_request_binding(
        request_surface_sha256=pinned.surface_sha256,
        runtime_contract_payload_sha256=pinned.runtime_contract_payload_sha256,
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        route_manifest_sha256=route_manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        provider_request_sha256=request.provider_request_sha256,
        source_request_sha256=source_request_sha256,
        competition_authority_sha256=_sha("competition-authority"),
        competition_scope_sha256=_sha(f"competition-scope:{season}"),
        competition_requirement_sha256=_sha("competition-requirement"),
        role_binding_sha256=_sha("competition-role-binding"),
        source_evidence_sha256=_sha(f"competition-source-evidence:{season}"),
        source_family="stats",
        endpoint_id=endpoint_id,
        route_ids=(route_id,),
    )

    expected_result = pinned_runtime_contracts()[endpoint_id].result_sets[0]
    assert expected_result.result_set_name is not None
    parser_input = json.dumps(
        {
            "resultSets": [
                {
                    "name": expected_result.result_set_name,
                    "headers": list(expected_result.expected_columns),
                    "rowSet": [],
                }
            ]
        },
        separators=(",", ":"),
    )
    raw_bundle = _exact_case_bundle(
        source_family="stats",
        endpoint_name=endpoint_name,
        endpoint_id=endpoint_id,
        ordinal=20,
        parser_input=parser_input.encode("utf-8"),
        parameters=params,
        competition_id="00",
        competition_identity_sha256=source_request_sha256,
        scope_sha256=scope.scope_sha256,
        lane_id="stats-lane",
    )
    body = raw_bundle.objects[0]
    attempt = raw_bundle.observations[0].attempt
    raw_result = raw_bundle.occurrences[0]
    raw_landing = raw_bundle.landings[0]
    result = ResultSetReceipt(
        ordinal=0,
        result_set_name=raw_result.result_name,
        occurrence_state="present_empty",
        row_count=raw_result.row_count,
        ordered_columns_sha256=raw_result.ordered_headers_sha256,
        result_set_payload_sha256=raw_result.output_sha256,
    )
    staging = PersistedStagingReceipt(
        result_set_ordinal=0,
        result_set_name=raw_result.result_name,
        staging_key="stg_common_all_players",
        row_count=raw_result.row_count,
        result_set_payload_sha256=raw_result.output_sha256,
        staging_receipt_root_sha256=raw_landing.receipt_root_sha256,
    )
    closure_observation = RequestObservation(
        request_surface_sha256=pinned.surface_sha256,
        route_manifest_sha256=route_manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        provider_request_sha256=request.provider_request_sha256,
        source_family="stats",
        endpoint_id=endpoint_id,
        route_ids=(route_id,),
        request_binding=request_binding,
        state="success_empty",
        attempt_count=1,
        http_status=200,
        response_body_sha256=body.response_sha256,
        response_body_bytes=body.uncompressed_bytes,
        parser_input_sha256=body.response_sha256,
        result_sets=(result,),
        staging_receipts=(staging,),
    )
    closure_receipt = build_request_closure_runtime_receipt(
        RequestClosureAdapterInput(
            route_manifest=route_manifest,
            scope=scope,
            observations=(closure_observation,),
        )
    )
    call = RawRequestClosureCallV2.build(
        endpoint_name=endpoint_name,
        source_family="stats",
        endpoint_id=endpoint_id,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        provider_parameters_sha256=canonical_parameters_sha256(materialized),
        provider_request_sha256=attempt.provider_request_sha256,
        route_ids=(route_id,),
        scope_sha256=scope.scope_sha256,
    )
    raw_manifest_authority = _issue_test_manifest_authority(
        RawRequestManifestAuthorityV2(
            source_sha=_SOURCE_SHA,
            run_id=101,
            run_attempt=1,
            chain_id="chain",
            lane_id="stats-lane",
            scope_sha256=scope.scope_sha256,
            route_authority_sha256=_sha(f"stats-route-authority:{season}"),
            request_closure_authority_sha256=_sha(f"stats-closure-authority:{season}"),
            field_authority_sha256=_sha("field-authority"),
            model_authority_sha256=_sha("model-authority"),
            expected_calls=(call,),
            compiler_provenance_sha256="0" * 64,
        )
    )
    return raw_bundle, raw_manifest_authority, closure_receipt


def _scan_manifest_join_only(
    connection: duckdb.DuckDBPyConnection,
    *,
    closure_receipt: object | None = None,
):
    scanner = DataScanner(connection)
    with (
        patch.object(scanner, "_assure_transformer_discovery"),
        patch.object(scanner, "_check_private_raw_authority_reconstruction"),
        patch.object(
            scanner,
            "_check_request_closure_inventory",
            return_value=closure_receipt,
        ),
        patch.object(scanner, "_check_full_publication_anchors"),
        patch.object(scanner, "_check_full_publication_cardinality"),
    ):
        return scanner.scan(
            categories=["raw_manifest_join_only"],
            full_publication=True,
        )


def _manifest_join_errors(report) -> list[object]:
    return [
        finding
        for finding in report.filter(severity=ScanSeverity.ERROR)
        if finding.check == "raw_authority_manifest_join_failed"
    ]


def test_full_publication_manifest_join_accepts_exact_four_static_roots_read_only(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "four-static-authorities.duckdb"
    writer = duckdb.connect(str(database_path))
    try:
        _persist_manifest(
            writer,
            expected_bundle=_four_static_bundle(),
            terminal=True,
        )
        writer.execute("CHECKPOINT")
    finally:
        writer.close()
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()

    reader = duckdb.connect(str(database_path), read_only=True)
    try:
        report = _scan_manifest_join_only(reader)
    finally:
        reader.close()

    assert _manifest_join_errors(report) == []
    evidence = report.evidence["raw_request_manifest_join"]
    assert evidence["expected_call_count"] == 4
    assert evidence["selected_attempt_count"] == 4
    assert evidence["static_endpoint_counts"] == {
        endpoint_id: 1 for endpoint_id in _FOUR_STATIC_ENDPOINTS
    }
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before


def test_full_publication_manifest_join_exactly_binds_stats_and_four_static() -> None:
    stats_bundle, stats_authority, closure_receipt = _stats_manifest_and_closure(season="2025-26")
    connection = duckdb.connect(":memory:")
    try:
        _persist_manifest(
            connection,
            expected_bundle=_four_static_bundle(),
            terminal=True,
        )
        store = RawRequestAuthorityStore(connection)
        stats_receipt = store.persist_bundle(stats_bundle)
        store.advance_manifest(stats_authority, (stats_receipt,), terminal=True)
        report = _scan_manifest_join_only(
            connection,
            closure_receipt=closure_receipt,
        )
    finally:
        connection.close()

    assert _manifest_join_errors(report) == []
    evidence = report.evidence["raw_request_manifest_join"]
    assert evidence["expected_call_count"] == 5
    assert evidence["request_closure_observation_count"] == 1


def test_full_publication_manifest_join_rejects_unrelated_green_closure() -> None:
    stats_bundle, stats_authority, _ = _stats_manifest_and_closure(season="2025-26")
    _, _, unrelated_closure = _stats_manifest_and_closure(season="2024-25")
    connection = duckdb.connect(":memory:")
    try:
        _persist_manifest(
            connection,
            expected_bundle=_four_static_bundle(),
            terminal=True,
        )
        store = RawRequestAuthorityStore(connection)
        stats_receipt = store.persist_bundle(stats_bundle)
        store.advance_manifest(stats_authority, (stats_receipt,), terminal=True)
        report = _scan_manifest_join_only(
            connection,
            closure_receipt=unrelated_closure,
        )
    finally:
        connection.close()

    errors = _manifest_join_errors(report)
    assert len(errors) == 1
    assert errors[0].details["verification_stage"] == "manifest_chain"
    assert "absent from request closure" in errors[0].message


def test_full_publication_manifest_join_rejects_unrelated_raw_receipt() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist_manifest(
            connection,
            expected_bundle=_four_static_bundle(),
            terminal=True,
        )
        RawRequestAuthorityStore(connection).persist_bundle(_bundle("live"))
        report = _scan_manifest_join_only(connection)
    finally:
        connection.close()

    errors = _manifest_join_errors(report)
    assert len(errors) == 1
    assert errors[0].details["verification_stage"] == "global_relations"
    assert "outside terminal manifests" in errors[0].message


def test_full_publication_manifest_join_rejects_subset_raw_receipt() -> None:
    full = _four_static_bundle()
    selected_observations = full.observations[:2]
    selected_ids = {item.attempt.observation_sha256 for item in selected_observations}
    subset = RawRequestAuthorityBundleV2.build(
        objects=(),
        observations=selected_observations,
        occurrences=tuple(
            item for item in full.occurrences if item.observation_sha256 in selected_ids
        ),
        landings=tuple(item for item in full.landings if item.observation_sha256 in selected_ids),
    )
    connection = duckdb.connect(":memory:")
    try:
        _persist_manifest(
            connection,
            expected_bundle=full,
            persisted_bundle=subset,
            terminal=False,
        )
        report = _scan_manifest_join_only(connection)
    finally:
        connection.close()

    errors = _manifest_join_errors(report)
    assert len(errors) == 1
    assert errors[0].details["verification_stage"] == "manifest_chain"
    assert "not terminal-sealed and complete" in errors[0].message


@pytest.mark.parametrize("extra_kind", ["static", "stats"])
def test_full_publication_manifest_join_rejects_extra_static_or_stats_request(
    extra_kind: Literal["static", "stats"],
) -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist_manifest(
            connection,
            expected_bundle=_four_static_bundle(),
            terminal=True,
        )
        RawRequestAuthorityStore(connection).persist_bundle(_bundle(extra_kind))
        report = _scan_manifest_join_only(connection)
    finally:
        connection.close()

    errors = _manifest_join_errors(report)
    assert len(errors) == 1
    assert errors[0].details["verification_stage"] == "global_relations"


def test_full_publication_manifest_join_rejects_manifest_digest_tamper() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist_manifest(
            connection,
            expected_bundle=_four_static_bundle(),
            terminal=True,
        )
        connection.execute(
            "UPDATE _raw_request_authority_manifest_journal SET manifest_sha256 = ?",
            ["f" * 64],
        )
        report = _scan_manifest_join_only(connection)
    finally:
        connection.close()

    errors = _manifest_join_errors(report)
    assert len(errors) == 1
    assert errors[0].details["verification_stage"] == "manifest_chain"
    assert "columns differ" in errors[0].message


def test_full_publication_manifest_join_rejects_nonterminal_complete_generation() -> None:
    connection = duckdb.connect(":memory:")
    try:
        _persist_manifest(
            connection,
            expected_bundle=_four_static_bundle(),
            terminal=False,
        )
        report = _scan_manifest_join_only(connection)
    finally:
        connection.close()

    errors = _manifest_join_errors(report)
    assert len(errors) == 1
    assert errors[0].details["verification_stage"] == "manifest_chain"
    assert "not terminal-sealed and complete" in errors[0].message
