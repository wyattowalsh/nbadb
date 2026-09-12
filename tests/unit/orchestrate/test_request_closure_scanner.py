from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import duckdb

from nbadb.core.nba_api_competition_identity import (
    bind_explicit_competition_request,
    build_competition_terminal_request_binding,
    compile_competition_identity_requirements,
)
from nbadb.core.nba_api_request_surface import (
    RequestScopeDimension,
    RequestScopeManifest,
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.orchestrate.extractor_runner import (
    RequestClosureCompetitionAuthority,
    RequestClosureExecutionAuthority,
)
from nbadb.orchestrate.request_closure_runtime import (
    PersistedStagingReceipt,
    RequestObservation,
    ResultSetReceipt,
    RouteRequestSpecInput,
    build_authoritative_route_manifest,
)
from nbadb.orchestrate.request_closure_staging import (
    RequestClosureObservationInventory,
    RequestClosureScopeGap,
)
from nbadb.orchestrate.scanner import DataScanner, ScanSeverity

if TYPE_CHECKING:
    from pathlib import Path


_COMMON_ALL_PLAYERS_SCOPE: dict[str, object] = {
    "is_only_current_season": 0,
    "league_id": "00",
    "season": "2025-26",
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _green_inventory() -> RequestClosureObservationInventory:
    pinned = pinned_request_surface_authority()
    route_id = "common_all_players:stg_common_all_players:0"
    manifest = build_authoritative_route_manifest(
        (
            RouteRequestSpecInput(
                route_id=route_id,
                source_family="stats",
                endpoint_id="CommonAllPlayers",
                parameters=tuple(sorted(_COMMON_ALL_PLAYERS_SCOPE.items())),
            ),
        )
    )
    endpoint = pinned.endpoint("stats", "CommonAllPlayers")
    request = materialize_provider_request(
        endpoint,
        _COMMON_ALL_PLAYERS_SCOPE,
        request_surface_sha256=pinned.surface_sha256,
        runtime_contract_payload_sha256=pinned.runtime_contract_payload_sha256,
    )
    materialized = dict(request.materialized_parameters)
    dimensions = []
    for dependency_id in sorted(
        {dependency for parameter in endpoint.parameters for dependency in parameter.dependencies}
    ):
        values = {
            materialized[parameter.name]
            for parameter in endpoint.parameters
            if dependency_id in parameter.dependencies
        }
        dimensions.append(
            RequestScopeDimension(
                dependency_id=dependency_id,
                source_kind="request_closure_scanner_test",
                source_authority_sha256="a" * 64,
                values=tuple(sorted(values, key=_canonical_bytes)),
            )
        )
    scope = RequestScopeManifest(
        request_surface_sha256=pinned.surface_sha256,
        scope_id="request_closure_scanner_test",
        seed_route_ids=(route_id,),
        dimensions=tuple(sorted(dimensions, key=lambda item: item.dimension_sha256)),
    )
    requirement = next(
        item
        for item in compile_competition_identity_requirements()
        if item.repo_endpoint_name == "common_all_players"
        and item.provider_endpoint_id == "CommonAllPlayers"
        and item.league_id == _COMMON_ALL_PLAYERS_SCOPE["league_id"]
        and item.role_binding.binding_strategy == "explicit_applicability_cell"
    )
    qualified = bind_explicit_competition_request(requirement, request)
    request_binding = build_competition_terminal_request_binding(
        qualified,
        route_manifest_sha256=manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        route_ids=(route_id,),
    )
    authority = RequestClosureExecutionAuthority(
        manifest,
        scope,
        competition_authorities=(RequestClosureCompetitionAuthority(qualified, request_binding),),
    )
    result = ResultSetReceipt(
        ordinal=0,
        result_set_name="CommonAllPlayers",
        occurrence_state="present_nonempty",
        row_count=1,
        ordered_columns_sha256="b" * 64,
        result_set_payload_sha256="c" * 64,
    )
    staging = PersistedStagingReceipt(
        result_set_ordinal=0,
        result_set_name="CommonAllPlayers",
        staging_key="stg_common_all_players",
        row_count=1,
        result_set_payload_sha256="c" * 64,
        staging_receipt_root_sha256="d" * 64,
    )
    observation = RequestObservation(
        request_surface_sha256=pinned.surface_sha256,
        route_manifest_sha256=manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        provider_request_sha256=request.provider_request_sha256,
        source_family="stats",
        endpoint_id="CommonAllPlayers",
        route_ids=(route_id,),
        request_binding=request_binding,
        state="success_nonempty",
        attempt_count=1,
        http_status=200,
        response_body_sha256="e" * 64,
        response_body_bytes=2,
        parser_input_sha256="f" * 64,
        result_sets=(result,),
        staging_receipts=(staging,),
    )
    inventory = RequestClosureObservationInventory(authority, (observation,))
    assert inventory.green
    return inventory


def _request_closure_findings(scanner: DataScanner, path: Path) -> list[object]:
    with (
        patch.object(scanner, "_assure_transformer_discovery"),
        patch.object(scanner, "_check_full_publication_anchors"),
        patch.object(scanner, "_check_full_publication_cardinality"),
    ):
        report = scanner.scan(
            categories=["request_closure_test"],
            full_publication=True,
            request_closure_inventory_path=path,
        )
    return [finding for finding in report.findings if finding.table == "request_closure"]


def test_scanner_accepts_only_independently_reproduced_green_inventory(tmp_path) -> None:
    path = tmp_path / "request-closure-observation-inventory.json"
    path.write_bytes(_green_inventory().canonical_bytes)
    conn = duckdb.connect(":memory:")
    try:
        scanner = DataScanner(conn)
        assert _request_closure_findings(scanner, path) == []
        assert scanner._report.checks_run >= 1
    finally:
        conn.close()


def test_scanner_fails_closed_for_missing_tampered_and_typed_gap_inventory(tmp_path) -> None:
    conn = duckdb.connect(":memory:")
    try:
        missing = DataScanner(conn)
        missing_findings = _request_closure_findings(missing, tmp_path / "missing.json")
        assert len(missing_findings) == 1
        assert missing_findings[0].severity is ScanSeverity.ERROR
        assert missing_findings[0].check == "request_closure_inventory_missing"

        tampered_path = tmp_path / "tampered.json"
        tampered_path.write_bytes(_green_inventory().canonical_bytes + b"\n")
        tampered = DataScanner(conn)
        tampered_findings = _request_closure_findings(tampered, tampered_path)
        assert len(tampered_findings) == 1
        assert tampered_findings[0].check == "request_closure_inventory_invalid"

        gap = RequestClosureScopeGap(
            reason_code="dependent_scope_unmaterialized",
            endpoint_names=("cume_stats_player",),
            physical_route_ids=("cume_stats_player:stg_cume_player:0",),
            logical_call_count=1,
            scope_evidence_sha256="9" * 64,
        )
        gap_inventory = RequestClosureObservationInventory(None, (), scope_gaps=(gap,))
        gap_path = tmp_path / "gap.json"
        gap_path.write_bytes(gap_inventory.canonical_bytes)
        incomplete = DataScanner(conn)
        incomplete_findings = _request_closure_findings(incomplete, gap_path)
        assert len(incomplete_findings) == 1
        assert incomplete_findings[0].check == "request_closure_inventory_invalid"
        assert "dependent_scope_unmaterialized" in incomplete_findings[0].message
    finally:
        conn.close()
