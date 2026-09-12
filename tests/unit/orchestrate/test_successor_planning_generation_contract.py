from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_planning_generation_contract import (
    SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION,
    PlanningDataMember,
    PlanningDispatchPhase,
    PlanningGenerationManifest,
    SealedProviderDispatch,
    SuccessorPlanningArtifactIdentity,
    SuccessorPlanningGenerationContractError,
    SuccessorPlanningWave,
    canonical_planning_json_bytes,
    canonical_planning_sha256,
)
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticDescriptor,
    PlanningSemanticKind,
)
from nbadb.orchestrate.successor_update_contract import (
    SUCCESSOR_UPDATE_CONTRACT_SCHEMA_VERSION,
    CallMutability,
    RequestedRouteScope,
    SuccessorUpdateMode,
)


def _scope(
    marker: str,
    *,
    endpoint: str,
    route: str,
    parameters: dict[str, Any],
) -> RequestedRouteScope:
    return RequestedRouteScope.from_parameters(
        endpoint_name=endpoint,
        route_id=route,
        route_contract_sha256=marker * 64,
        parameters=parameters,
        mutability=CallMutability.MUTABLE,
    )


def _semantic(
    marker: str,
    *,
    value_count: int,
    typed_zero_reason_code: str | None = None,
) -> PlanningSemanticDescriptor:
    return PlanningSemanticDescriptor.from_partition(
        semantic_kind=PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA,
        partition={},
        semantic_schema_sha256=canonical_planning_sha256({"semantic_schema": marker}),
        semantic_content_sha256=canonical_planning_sha256({"semantic_content": marker}),
        value_count=value_count,
        typed_zero_reason_code=typed_zero_reason_code,
    )


def _synthetic_manifest(
    *,
    baseline_identity_sha256: str,
    mode: SuccessorUpdateMode,
    source_sha: str,
    cutoff_utc: str,
    as_of_utc: str,
    update_scopes: tuple[RequestedRouteScope, ...],
    workflow_run_id: int = 23,
    workflow_run_attempt: int = 2,
) -> PlanningGenerationManifest:
    """Build a compact two-wave manifest for adjacent contract tests."""

    if len(update_scopes) < 2:
        raise ValueError("synthetic planning manifest needs at least two update scopes")
    wave_0_leader, wave_1_leader = update_scopes[:2]
    wave_0_scopes = tuple(
        scope
        for scope in update_scopes
        if (scope.endpoint_name, scope.scope_sha256)
        == (wave_0_leader.endpoint_name, wave_0_leader.scope_sha256)
    )
    wave_1_scopes = tuple(
        scope
        for scope in update_scopes
        if (scope.endpoint_name, scope.scope_sha256)
        == (wave_1_leader.endpoint_name, wave_1_leader.scope_sha256)
    )
    if set(wave_0_scopes) & set(wave_1_scopes):
        raise ValueError("synthetic planning waves require distinct logical calls")
    wave_0_scope = wave_0_scopes[0]
    wave_1_scope = wave_1_scopes[0]
    request = SuccessorPlanningRequest(
        baseline_identity_sha256=baseline_identity_sha256,
        mode=mode,
        source_sha=source_sha,
        cutoff_utc=cutoff_utc,
        as_of_utc=as_of_utc,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        requested_planning_scopes=tuple(
            sorted(wave_0_scopes, key=lambda scope: scope.identity_sha256)
        ),
    )
    wave_0_members = tuple(
        PlanningDataMember(
            member_id=f"synthetic_wave_0_member_{index}",
            wave_index=0,
            producing_scope_sha256=scope.identity_sha256,
            schema_sha256=canonical_planning_sha256({"schema": 0, "result": index}),
            content_sha256=canonical_planning_sha256({"scope": scope.identity_sha256}),
            row_count=1,
            semantic=_semantic(f"synthetic-wave-0-{index}", value_count=1),
        )
        for index, scope in enumerate(wave_0_scopes)
    )
    wave_1_members = tuple(
        PlanningDataMember(
            member_id=f"synthetic_wave_1_member_{index}",
            wave_index=1,
            producing_scope_sha256=scope.identity_sha256,
            schema_sha256=canonical_planning_sha256({"schema": 1, "result": index}),
            content_sha256=canonical_planning_sha256({"scope": scope.identity_sha256}),
            row_count=1,
            semantic=_semantic(f"synthetic-wave-1-{index}", value_count=1),
        )
        for index, scope in enumerate(wave_1_scopes)
    )
    members = tuple(
        sorted((*wave_0_members, *wave_1_members), key=lambda member: member.identity_sha256)
    )
    wave_0_member_ids = tuple(sorted(member.identity_sha256 for member in wave_0_members))
    wave_1_member_ids = tuple(sorted(member.identity_sha256 for member in wave_1_members))
    wave_0 = SuccessorPlanningWave(
        wave_index=0,
        parent_wave_identity_sha256=None,
        requested_scope_identity_sha256s=tuple(
            sorted(scope.identity_sha256 for scope in wave_0_scopes)
        ),
        completed_scope_identity_sha256s=tuple(
            sorted(scope.identity_sha256 for scope in wave_0_scopes)
        ),
        member_identity_sha256s=wave_0_member_ids,
        member_receipt_sha256s=tuple(
            canonical_planning_sha256({"receipt": 0, "member": member_id})
            for member_id in wave_0_member_ids
        ),
        private_generation_identity_sha256=canonical_planning_sha256({"private": 0}),
        completion_receipt_sha256=canonical_planning_sha256({"complete": 0}),
    )
    wave_1 = SuccessorPlanningWave(
        wave_index=1,
        parent_wave_identity_sha256=wave_0.identity_sha256,
        requested_scope_identity_sha256s=tuple(
            sorted(scope.identity_sha256 for scope in wave_1_scopes)
        ),
        completed_scope_identity_sha256s=tuple(
            sorted(scope.identity_sha256 for scope in wave_1_scopes)
        ),
        member_identity_sha256s=wave_1_member_ids,
        member_receipt_sha256s=tuple(
            canonical_planning_sha256({"receipt": 1, "member": member_id})
            for member_id in wave_1_member_ids
        ),
        private_generation_identity_sha256=canonical_planning_sha256({"private": 1}),
        completion_receipt_sha256=canonical_planning_sha256({"complete": 1}),
    )
    update_dispatches: list[SealedProviderDispatch] = []
    grouped_update_scopes: dict[tuple[str, str], list[RequestedRouteScope]] = {}
    for scope in update_scopes:
        grouped_update_scopes.setdefault((scope.endpoint_name, scope.scope_sha256), []).append(
            scope
        )
    for logical_scopes in grouped_update_scopes.values():
        first_scope = logical_scopes[0]
        logical_scope_ids = {scope.identity_sha256 for scope in logical_scopes}
        update_dispatches.append(
            SealedProviderDispatch.from_parameters(
                phase=PlanningDispatchPhase.UPDATE,
                endpoint_name=first_scope.endpoint_name,
                requested_scope_identity_sha256s=tuple(
                    scope.identity_sha256 for scope in logical_scopes
                ),
                parameters=first_scope.parameters,
                pattern=first_scope.endpoint_name,
                staging_route_ids=tuple(scope.route_id for scope in logical_scopes),
                dependency_identity_sha256s=(
                    wave_1_member_ids
                    if wave_1_scope.identity_sha256 in logical_scope_ids
                    else (
                        wave_0_member_ids
                        if wave_0_scope.identity_sha256 in logical_scope_ids
                        else wave_0_member_ids
                    )
                ),
            )
        )
    dispatches = (
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.PLANNING_WAVE_0,
            endpoint_name=wave_0_scope.endpoint_name,
            requested_scope_identity_sha256s=tuple(
                scope.identity_sha256 for scope in wave_0_scopes
            ),
            parameters=wave_0_scope.parameters,
            pattern=wave_0_scope.endpoint_name,
            staging_route_ids=tuple(scope.route_id for scope in wave_0_scopes),
            dependency_identity_sha256s=(),
        ),
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.PLANNING_WAVE_1,
            endpoint_name=wave_1_scope.endpoint_name,
            requested_scope_identity_sha256s=tuple(
                scope.identity_sha256 for scope in wave_1_scopes
            ),
            parameters=wave_1_scope.parameters,
            pattern=wave_1_scope.endpoint_name,
            staging_route_ids=tuple(scope.route_id for scope in wave_1_scopes),
            dependency_identity_sha256s=wave_0_member_ids,
        ),
        *update_dispatches,
    )
    artifact_identity = SuccessorPlanningArtifactIdentity(
        planning_request_sha256=request.identity_sha256,
        planning_generation_id="synthetic-planning-generation",
        planning_database_sha256=canonical_planning_sha256({"database": "bytes"}),
        planning_database_bytes=4096,
        planning_database_schema_sha256=canonical_planning_sha256({"database": "schema"}),
        member_inventory_sha256=canonical_planning_sha256([member.to_dict() for member in members]),
        private_generation_identity_sha256=canonical_planning_sha256(
            [wave.private_generation_identity_sha256 for wave in (wave_0, wave_1)]
        ),
        wave_inventory_sha256=canonical_planning_sha256(
            [wave.to_dict() for wave in (wave_0, wave_1)]
        ),
        planning_manifest_sha256="0" * 64,
        sealed_dispatch_inventory_sha256=canonical_planning_sha256(
            [dispatch.to_dict() for dispatch in dispatches]
        ),
    )
    return PlanningGenerationManifest.seal(
        request=request,
        artifact_identity=artifact_identity,
        waves=(wave_0, wave_1),
        members=members,
        requested_route_scopes=tuple(
            sorted(update_scopes, key=lambda scope: scope.identity_sha256)
        ),
        sealed_dispatches=dispatches,
    )


def _fixture() -> PlanningGenerationManifest:
    wave_0_scope = _scope(
        "1",
        endpoint="scoreboard_v3",
        route="scoreboard_v3:stg_scoreboard_games",
        parameters={"game_date": "2026-08-01", "league_id": "00"},
    )
    wave_1_scope = _scope(
        "2",
        endpoint="cume_stats_player_games",
        route="cume_stats_player_games:stg_cume_player_games",
        parameters={
            "player_id": 2544,
            "season": "2025-26",
            "season_type": "Regular Season",
        },
    )
    dependent_update_scope = _scope(
        "3",
        endpoint="cume_stats_player",
        route="cume_stats_player:stg_cume_player_game_by_game",
        parameters={
            "game_ids": ["0022600001"],
            "player_id": 2544,
            "season": "2025-26",
            "season_type": "Regular Season",
        },
    )
    ordinary_update_scope = _scope(
        "a",
        endpoint="league_game_log",
        route="league_game_log:stg_league_game_log",
        parameters={"season": "2025-26", "season_type": "Regular Season"},
    )
    request = SuccessorPlanningRequest(
        baseline_identity_sha256="a" * 64,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-01T00:00:00Z",
        as_of_utc="2026-08-02T00:00:00Z",
        workflow_run_id=23,
        workflow_run_attempt=2,
        requested_planning_scopes=(wave_0_scope,),
    )
    wave_0_member = PlanningDataMember(
        member_id="live_game_ids",
        wave_index=0,
        producing_scope_sha256=wave_0_scope.identity_sha256,
        schema_sha256="4" * 64,
        content_sha256="5" * 64,
        row_count=0,
        semantic=_semantic(
            "live-game-ids",
            value_count=0,
            typed_zero_reason_code="scoreboard_complete_empty",
        ),
        typed_zero_reason_code="scoreboard_complete_empty",
    )
    wave_1_member = PlanningDataMember(
        member_id="player_cume_foundation",
        wave_index=1,
        producing_scope_sha256=wave_1_scope.identity_sha256,
        schema_sha256="6" * 64,
        content_sha256="7" * 64,
        row_count=1,
        semantic=_semantic("player-cume-foundation", value_count=1),
    )
    members = tuple(
        sorted((wave_0_member, wave_1_member), key=lambda member: member.identity_sha256)
    )
    wave_0 = SuccessorPlanningWave(
        wave_index=0,
        parent_wave_identity_sha256=None,
        requested_scope_identity_sha256s=(wave_0_scope.identity_sha256,),
        completed_scope_identity_sha256s=(wave_0_scope.identity_sha256,),
        member_identity_sha256s=(wave_0_member.identity_sha256,),
        member_receipt_sha256s=("8" * 64,),
        private_generation_identity_sha256="9" * 64,
        completion_receipt_sha256="c" * 64,
    )
    wave_1 = SuccessorPlanningWave(
        wave_index=1,
        parent_wave_identity_sha256=wave_0.identity_sha256,
        requested_scope_identity_sha256s=(wave_1_scope.identity_sha256,),
        completed_scope_identity_sha256s=(wave_1_scope.identity_sha256,),
        member_identity_sha256s=(wave_1_member.identity_sha256,),
        member_receipt_sha256s=("d" * 64,),
        private_generation_identity_sha256="e" * 64,
        completion_receipt_sha256="f" * 64,
    )
    dispatches = (
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.PLANNING_WAVE_0,
            endpoint_name=wave_0_scope.endpoint_name,
            requested_scope_identity_sha256s=(wave_0_scope.identity_sha256,),
            parameters=wave_0_scope.parameters,
            pattern="scoreboard_v3",
            staging_route_ids=(wave_0_scope.route_id,),
            dependency_identity_sha256s=(),
        ),
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.PLANNING_WAVE_1,
            endpoint_name=wave_1_scope.endpoint_name,
            requested_scope_identity_sha256s=(wave_1_scope.identity_sha256,),
            parameters=wave_1_scope.parameters,
            pattern="cume_stats_player",
            staging_route_ids=(wave_1_scope.route_id,),
            dependency_identity_sha256s=(wave_0_member.identity_sha256,),
        ),
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name=wave_0_scope.endpoint_name,
            requested_scope_identity_sha256s=(wave_0_scope.identity_sha256,),
            parameters=wave_0_scope.parameters,
            pattern="scoreboard_v3",
            staging_route_ids=(wave_0_scope.route_id,),
            dependency_identity_sha256s=(wave_0_member.identity_sha256,),
        ),
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name=wave_1_scope.endpoint_name,
            requested_scope_identity_sha256s=(wave_1_scope.identity_sha256,),
            parameters=wave_1_scope.parameters,
            pattern="cume_stats_player_games",
            staging_route_ids=(wave_1_scope.route_id,),
            dependency_identity_sha256s=(wave_1_member.identity_sha256,),
        ),
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name=dependent_update_scope.endpoint_name,
            requested_scope_identity_sha256s=(dependent_update_scope.identity_sha256,),
            parameters=dependent_update_scope.parameters,
            pattern="cume_stats_player",
            staging_route_ids=(dependent_update_scope.route_id,),
            dependency_identity_sha256s=(wave_1_member.identity_sha256,),
        ),
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name=ordinary_update_scope.endpoint_name,
            requested_scope_identity_sha256s=(ordinary_update_scope.identity_sha256,),
            parameters=ordinary_update_scope.parameters,
            pattern="league_game_log",
            staging_route_ids=(ordinary_update_scope.route_id,),
            dependency_identity_sha256s=(wave_0_member.identity_sha256,),
        ),
    )
    scopes = tuple(
        sorted(
            (
                wave_0_scope,
                wave_1_scope,
                dependent_update_scope,
                ordinary_update_scope,
            ),
            key=lambda scope: scope.identity_sha256,
        )
    )
    artifact_identity = SuccessorPlanningArtifactIdentity(
        planning_request_sha256=request.identity_sha256,
        planning_generation_id="planning-generation-0001",
        planning_database_sha256="0" * 64,
        planning_database_bytes=4096,
        planning_database_schema_sha256="1" * 64,
        member_inventory_sha256=canonical_planning_sha256([member.to_dict() for member in members]),
        private_generation_identity_sha256=canonical_planning_sha256(
            [wave.private_generation_identity_sha256 for wave in (wave_0, wave_1)]
        ),
        wave_inventory_sha256=canonical_planning_sha256(
            [wave.to_dict() for wave in (wave_0, wave_1)]
        ),
        planning_manifest_sha256="2" * 64,
        sealed_dispatch_inventory_sha256=canonical_planning_sha256(
            [dispatch.to_dict() for dispatch in dispatches]
        ),
    )
    return PlanningGenerationManifest.seal(
        request=request,
        artifact_identity=artifact_identity,
        waves=(wave_0, wave_1),
        members=members,
        requested_route_scopes=scopes,
        sealed_dispatches=dispatches,
    )


def _reseal(
    manifest: PlanningGenerationManifest,
    *,
    request: SuccessorPlanningRequest | None = None,
    waves: tuple[SuccessorPlanningWave, SuccessorPlanningWave] | None = None,
    members: tuple[PlanningDataMember, ...] | None = None,
    requested_route_scopes: tuple[RequestedRouteScope, ...] | None = None,
    sealed_dispatches: tuple[SealedProviderDispatch, ...] | None = None,
) -> PlanningGenerationManifest:
    request = manifest.request if request is None else request
    waves = manifest.waves if waves is None else waves
    members = manifest.members if members is None else members
    requested_route_scopes = (
        manifest.requested_route_scopes
        if requested_route_scopes is None
        else requested_route_scopes
    )
    sealed_dispatches = (
        manifest.sealed_dispatches if sealed_dispatches is None else sealed_dispatches
    )
    identity = replace(
        manifest.artifact_identity,
        planning_request_sha256=request.identity_sha256,
        member_inventory_sha256=canonical_planning_sha256([member.to_dict() for member in members]),
        private_generation_identity_sha256=canonical_planning_sha256(
            [wave.private_generation_identity_sha256 for wave in waves]
        ),
        wave_inventory_sha256=canonical_planning_sha256([wave.to_dict() for wave in waves]),
        planning_manifest_sha256="0" * 64,
        sealed_dispatch_inventory_sha256=canonical_planning_sha256(
            [dispatch.to_dict() for dispatch in sealed_dispatches]
        ),
    )
    return PlanningGenerationManifest.seal(
        request=request,
        artifact_identity=identity,
        waves=waves,
        members=members,
        requested_route_scopes=requested_route_scopes,
        sealed_dispatches=sealed_dispatches,
    )


def test_canonical_round_trip_binds_current_schema_and_all_inventories() -> None:
    manifest = _fixture()

    restored = PlanningGenerationManifest.from_canonical_bytes(manifest.canonical_bytes)

    assert restored == manifest
    assert PlanningGenerationManifest.from_dict(manifest.to_dict()) == manifest
    public = manifest.to_public_dict()
    assert "members" not in public
    assert "waves" not in public
    assert "sealed_dispatches" not in public
    assert "request" not in public
    assert "requested_route_scopes" not in public
    assert public["identity_sha256"] == manifest.identity_sha256
    assert public["artifact_identity"] == manifest.artifact_identity.to_dict()
    assert manifest.canonical_bytes == canonical_planning_json_bytes(manifest.to_dict())
    assert manifest.artifact_identity.planning_manifest_sha256 == (
        manifest.computed_planning_manifest_sha256
    )
    assert manifest.to_dict()["schema_version"] == (SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION)
    assert manifest.to_dict()["requested_route_scope_schema_version"] == (
        SUCCESSOR_UPDATE_CONTRACT_SCHEMA_VERSION
    )
    assert b"/" not in manifest.canonical_bytes


def test_decoding_rejects_unknown_noncanonical_duplicate_and_tampered_fields() -> None:
    manifest = _fixture()
    unknown = manifest.to_dict()
    unknown["path"] = "/tmp/private.duckdb"
    with pytest.raises(SuccessorPlanningGenerationContractError, match="unexpected=path"):
        PlanningGenerationManifest.from_dict(unknown)

    pretty = json.dumps(manifest.to_dict(), indent=2).encode()
    with pytest.raises(SuccessorPlanningGenerationContractError, match="not canonical"):
        PlanningGenerationManifest.from_canonical_bytes(pretty)

    duplicate = b'{"kind":"planning_generation_manifest","kind":"other"}'
    with pytest.raises(SuccessorPlanningGenerationContractError, match="duplicate key"):
        PlanningGenerationManifest.from_canonical_bytes(duplicate)

    tampered = manifest.to_dict()
    tampered["artifact_identity"]["planning_database_bytes"] = 4097
    encoded = canonical_planning_json_bytes(tampered)
    with pytest.raises(SuccessorPlanningGenerationContractError, match="manifest body"):
        PlanningGenerationManifest.from_canonical_bytes(encoded)

    wrong_schema_type = manifest.to_dict()
    wrong_schema_type["schema_version"] = True
    with pytest.raises(SuccessorPlanningGenerationContractError, match="schema is invalid"):
        PlanningGenerationManifest.from_dict(wrong_schema_type)

    nested_schema_type = manifest.to_dict()
    nested_schema_type["request"]["schema_version"] = True
    with pytest.raises(SuccessorPlanningGenerationContractError, match="schema is invalid"):
        PlanningGenerationManifest.from_canonical_bytes(
            canonical_planning_json_bytes(nested_schema_type)
        )


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"output_path": "/tmp/private"}, "path-bearing"),
        ({"endpoint": "file:///tmp/private"}, "path or URI"),
        ({"api_token": "redacted"}, "forbidden key"),
    ],
)
def test_dispatch_parameters_are_path_and_secret_free(
    parameters: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(SuccessorPlanningGenerationContractError, match=message):
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name="league_game_log",
            requested_scope_identity_sha256s=("1" * 64,),
            parameters=parameters,
            pattern="league_game_log",
            staging_route_ids=("league_game_log:stg_league_game_log",),
            dependency_identity_sha256s=("1" * 64,),
        )

    with pytest.raises(SuccessorPlanningGenerationContractError, match="path-free"):
        replace(_fixture().artifact_identity, planning_generation_id="../escape")


def test_wave_order_parent_and_exact_completion_are_fail_closed() -> None:
    manifest = _fixture()
    wave_0, wave_1 = manifest.waves

    with pytest.raises(SuccessorPlanningGenerationContractError, match="ordered wave 0"):
        replace(manifest, waves=(wave_1, wave_0))
    with pytest.raises(SuccessorPlanningGenerationContractError, match="parent"):
        replace(
            manifest,
            waves=(wave_0, replace(wave_1, parent_wave_identity_sha256="0" * 64)),
        )
    with pytest.raises(SuccessorPlanningGenerationContractError, match="exactly equal"):
        replace(wave_0, completed_scope_identity_sha256s=("f" * 64,))


def test_typed_zero_requires_complete_member_and_exact_receipt() -> None:
    manifest = _fixture()
    zero_member = next(member for member in manifest.members if member.row_count == 0)
    nonempty_member = next(member for member in manifest.members if member.row_count > 0)

    with pytest.raises(SuccessorPlanningGenerationContractError, match="require a typed-zero"):
        replace(zero_member, typed_zero_reason_code=None)
    with pytest.raises(SuccessorPlanningGenerationContractError, match="cannot claim"):
        replace(nonempty_member, typed_zero_reason_code="provider_success_empty")
    with pytest.raises(SuccessorPlanningGenerationContractError, match="nonempty"):
        replace(manifest.waves[0], member_receipt_sha256s=())


def test_manifest_rejects_dispatch_widening_duplicate_and_missing_scope() -> None:
    manifest = _fixture()
    update = manifest.sealed_dispatches[-1]

    widened = replace(
        update,
        requested_scope_identity_sha256s=("f" * 64,),
    )
    with pytest.raises(SuccessorPlanningGenerationContractError, match="widens"):
        replace(manifest, sealed_dispatches=(*manifest.sealed_dispatches[:-1], widened))

    duplicate = replace(update, pattern="league_game_log_duplicate")
    with pytest.raises(
        SuccessorPlanningGenerationContractError,
        match="logical call more than once",
    ):
        replace(manifest, sealed_dispatches=(*manifest.sealed_dispatches, duplicate))

    extra_scope = _scope(
        "a",
        endpoint="box_score_summary_v3",
        route="box_score_summary_v3:stg_box_score_summary",
        parameters={"game_id": "0022600002"},
    )
    scopes = tuple(
        sorted(
            (*manifest.requested_route_scopes, extra_scope), key=lambda item: item.identity_sha256
        )
    )
    with pytest.raises(SuccessorPlanningGenerationContractError, match="exactly cover"):
        replace(manifest, requested_route_scopes=scopes)


def test_manifest_rejects_endpoint_parameters_staging_and_dependency_drift() -> None:
    manifest = _fixture()
    wave_1_dispatch = manifest.sealed_dispatches[1]

    with pytest.raises(SuccessorPlanningGenerationContractError, match="endpoint differs"):
        replace(
            manifest,
            sealed_dispatches=(
                manifest.sealed_dispatches[0],
                replace(wave_1_dispatch, endpoint_name="cume_stats_team"),
                *manifest.sealed_dispatches[2:],
            ),
        )

    parameter_drift = SealedProviderDispatch.from_parameters(
        phase=wave_1_dispatch.phase,
        endpoint_name=wave_1_dispatch.endpoint_name,
        requested_scope_identity_sha256s=wave_1_dispatch.requested_scope_identity_sha256s,
        parameters={**wave_1_dispatch.parameters, "player_id": 201939},
        pattern=wave_1_dispatch.pattern,
        staging_route_ids=wave_1_dispatch.staging_route_ids,
        dependency_identity_sha256s=wave_1_dispatch.dependency_identity_sha256s,
    )
    with pytest.raises(SuccessorPlanningGenerationContractError, match="parameters differ"):
        replace(
            manifest,
            sealed_dispatches=(
                manifest.sealed_dispatches[0],
                parameter_drift,
                *manifest.sealed_dispatches[2:],
            ),
        )

    with pytest.raises(SuccessorPlanningGenerationContractError, match="staging route"):
        replace(
            manifest,
            sealed_dispatches=(
                manifest.sealed_dispatches[0],
                replace(
                    wave_1_dispatch,
                    staging_route_ids=("cume_stats_player:stg_wrong",),
                ),
                *manifest.sealed_dispatches[2:],
            ),
        )

    with pytest.raises(SuccessorPlanningGenerationContractError, match="non-wave-0 member"):
        replace(
            manifest,
            sealed_dispatches=(
                manifest.sealed_dispatches[0],
                replace(wave_1_dispatch, dependency_identity_sha256s=("0" * 64,)),
                *manifest.sealed_dispatches[2:],
            ),
        )
    with pytest.raises(SuccessorPlanningGenerationContractError, match="requires"):
        replace(wave_1_dispatch, dependency_identity_sha256s=())


def test_mutable_planning_scopes_must_be_recalled_once_during_update() -> None:
    manifest = _fixture()
    wave_0_scope_id = manifest.waves[0].requested_scope_identity_sha256s[0]
    update_without_scoreboard = tuple(
        dispatch
        for dispatch in manifest.sealed_dispatches
        if not (
            dispatch.phase is PlanningDispatchPhase.UPDATE
            and wave_0_scope_id in dispatch.requested_scope_identity_sha256s
        )
    )

    with pytest.raises(
        SuccessorPlanningGenerationContractError,
        match="mutable planning logical calls must be re-dispatched",
    ):
        replace(manifest, sealed_dispatches=update_without_scoreboard)


def test_nested_digest_tampering_and_unknown_leaf_fields_are_rejected() -> None:
    manifest = _fixture()
    payload = manifest.to_dict()
    payload["waves"][0]["member_receipts_sha256"] = "0" * 64
    with pytest.raises(SuccessorPlanningGenerationContractError, match="exact inventory"):
        PlanningGenerationManifest.from_dict(payload)

    dispatch_payload = manifest.sealed_dispatches[0].to_dict()
    dispatch_payload["fallback"] = True
    with pytest.raises(SuccessorPlanningGenerationContractError, match="unexpected=fallback"):
        SealedProviderDispatch.from_dict(dispatch_payload)


def test_dispatch_dependency_inventory_is_plural_canonical_and_phase_strict() -> None:
    manifest = _fixture()
    wave_0_dispatch, wave_1_dispatch = manifest.sealed_dispatches[:2]

    assert wave_0_dispatch.to_dict()["dependency_identity_sha256s"] == []
    assert "dependency_identity_sha256" not in wave_0_dispatch.to_dict()
    with pytest.raises(SuccessorPlanningGenerationContractError, match="empty dependency"):
        replace(wave_0_dispatch, dependency_identity_sha256s=("1" * 64,))
    with pytest.raises(SuccessorPlanningGenerationContractError, match="nonempty sealed"):
        replace(wave_1_dispatch, dependency_identity_sha256s=())
    with pytest.raises(SuccessorPlanningGenerationContractError, match="duplicates"):
        replace(wave_1_dispatch, dependency_identity_sha256s=("1" * 64, "1" * 64))
    with pytest.raises(SuccessorPlanningGenerationContractError, match="canonical sorted"):
        replace(wave_1_dispatch, dependency_identity_sha256s=("2" * 64, "1" * 64))

    old_scalar = wave_1_dispatch.to_dict()
    old_scalar["dependency_identity_sha256"] = old_scalar.pop("dependency_identity_sha256s")[0]
    with pytest.raises(
        SuccessorPlanningGenerationContractError,
        match="missing=dependency_identity_sha256s",
    ):
        SealedProviderDispatch.from_dict(old_scalar)


def test_mutable_multi_route_call_update_depends_on_every_emitted_member() -> None:
    manifest = _fixture()
    original_scope = next(
        scope
        for scope in manifest.requested_route_scopes
        if scope.identity_sha256 in manifest.waves[0].requested_scope_identity_sha256s
    )
    extra_scope = _scope(
        "0",
        endpoint=original_scope.endpoint_name,
        route="scoreboard_v3:stg_scoreboard_extra",
        parameters=original_scope.parameters,
    )
    original_member = next(member for member in manifest.members if member.wave_index == 0)
    extra_member = PlanningDataMember(
        member_id="live_game_ids_extra_route",
        wave_index=0,
        producing_scope_sha256=extra_scope.identity_sha256,
        schema_sha256="a" * 64,
        content_sha256="b" * 64,
        row_count=1,
        semantic=_semantic("live-game-ids-extra-route", value_count=1),
    )
    members = tuple(
        sorted((*manifest.members, extra_member), key=lambda member: member.identity_sha256)
    )
    wave_0 = replace(
        manifest.waves[0],
        requested_scope_identity_sha256s=tuple(
            sorted((original_scope.identity_sha256, extra_scope.identity_sha256))
        ),
        completed_scope_identity_sha256s=tuple(
            sorted((original_scope.identity_sha256, extra_scope.identity_sha256))
        ),
        member_identity_sha256s=tuple(
            member.identity_sha256 for member in members if member.wave_index == 0
        ),
        member_receipt_sha256s=("8" * 64, "9" * 64),
    )
    wave_1 = replace(
        manifest.waves[1],
        parent_wave_identity_sha256=wave_0.identity_sha256,
    )
    planning_dispatch = replace(
        manifest.sealed_dispatches[0],
        requested_scope_identity_sha256s=(
            original_scope.identity_sha256,
            extra_scope.identity_sha256,
        ),
        staging_route_ids=(original_scope.route_id, extra_scope.route_id),
    )
    all_dependencies = tuple(
        sorted((original_member.identity_sha256, extra_member.identity_sha256))
    )
    update_dispatch = replace(
        manifest.sealed_dispatches[2],
        requested_scope_identity_sha256s=(
            original_scope.identity_sha256,
            extra_scope.identity_sha256,
        ),
        staging_route_ids=(original_scope.route_id, extra_scope.route_id),
        dependency_identity_sha256s=all_dependencies,
    )
    dispatches = (
        planning_dispatch,
        manifest.sealed_dispatches[1],
        update_dispatch,
        *manifest.sealed_dispatches[3:],
    )
    request = replace(
        manifest.request,
        requested_planning_scopes=tuple(
            sorted((original_scope, extra_scope), key=lambda scope: scope.identity_sha256)
        ),
    )
    scopes = tuple(
        sorted(
            (*manifest.requested_route_scopes, extra_scope),
            key=lambda scope: scope.identity_sha256,
        )
    )
    expanded = _reseal(
        manifest,
        request=request,
        waves=(wave_0, wave_1),
        members=members,
        requested_route_scopes=scopes,
        sealed_dispatches=dispatches,
    )

    assert expanded.sealed_dispatches[2].dependency_identity_sha256s == all_dependencies
    with pytest.raises(SuccessorPlanningGenerationContractError, match="all emitted members"):
        replace(
            expanded,
            sealed_dispatches=(
                *expanded.sealed_dispatches[:2],
                replace(
                    update_dispatch,
                    dependency_identity_sha256s=(original_member.identity_sha256,),
                ),
                *expanded.sealed_dispatches[3:],
            ),
        )


def test_member_binds_store_and_nested_semantic_authority_independently() -> None:
    manifest = _fixture()
    member = manifest.members[0]

    assert member.content_sha256 != member.semantic.semantic_content_sha256
    assert PlanningDataMember.from_dict(member.to_dict()) == member
    with pytest.raises(SuccessorPlanningGenerationContractError, match="differs from semantic"):
        replace(member, row_count=member.row_count + 1, typed_zero_reason_code=None)

    payload = member.to_dict()
    payload["semantic"]["global_player_ids"] = []
    with pytest.raises(SuccessorPlanningGenerationContractError, match="semantic authority"):
        PlanningDataMember.from_dict(payload)
