from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from nbadb.extract.bronze import canonical_parameters_sha256
from nbadb.orchestrate.checkpoint_contract import (
    CheckpointArtifactReceipt,
    CheckpointTransaction,
    CheckpointW2AuthorityIdentity,
)
from nbadb.orchestrate.dependent_workload_builder import (
    DEPENDENT_WORKLOAD_COMPILER_SHA256,
    DEPENDENT_WORKLOAD_QUERY_PLAN_SHA256,
)
from nbadb.orchestrate.dependent_workload_contract import (
    DEPENDENT_WORKLOAD_INTEGRATION_STATE,
    DependentExecutableUnit,
    DependentScopeDisposition,
    DependentWorkloadBundle,
    DependentWorkloadContractError,
    DependentWorkloadKind,
    FiveVsFiveOccurrence,
    FoundationAuthority,
    FoundationAuthorityKind,
    FoundationInputReceipt,
    PlayerMatchupOccurrence,
    ScopeDispositionRecord,
    SourceRowIdentity,
    TeamPlayerOccurrence,
    WorkloadScope,
)
from nbadb.orchestrate.public_value_authority_store import PUBLIC_VALUE_AUTHORITY_TABLES
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE

_SOURCE_SHA = "a" * 40
_DATABASE_SHA = "b" * 64
_REPORT_SHA = "c" * 64
_PROVIDER_SHA = "d" * 64


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


def _committed_transaction() -> CheckpointTransaction:
    candidate = CheckpointTransaction.candidate(
        chain_id="chain-a",
        source_sha=_SOURCE_SHA,
        generation=2,
        artifact_name="full-extraction-checkpoint-chain-a-iter-2",
        lane_contracts=[{"lane_id": "foundation", "coverage_units_hash": "1" * 64}],
        coverage_fingerprint="2" * 64,
    )
    built = candidate.mark_built(
        database_sha256=_DATABASE_SHA,
        report_sha256=_REPORT_SHA,
        w2_authority=_checkpoint_w2_authority(),
    )
    assert built.build is not None
    receipt = CheckpointArtifactReceipt(
        artifact_id=101,
        artifact_run_id=202,
        artifact_run_attempt=1,
        artifact_name=built.artifact_name,
        artifact_digest="sha256:" + "3" * 64,
        artifact_size_bytes=4096,
        database_sha256=_DATABASE_SHA,
        report_sha256=_REPORT_SHA,
        chain_id="chain-a",
        source_sha=_SOURCE_SHA,
        generation=2,
        coverage_fingerprint="2" * 64,
        lane_inventory_sha256=built.identity.coverage.lane_inventory_sha256,
        w2_authority_identity_sha256=built.build.w2_authority.identity_sha256,
    )
    return built.mark_uploaded_verified(receipt).commit()


_RECEIPT_ENDPOINTS = {
    "stg_league_game_log": "league_game_log",
    "stg_matchup": "box_score_matchups",
    "stg_rotation_away": "game_rotation",
    "stg_rotation_home": "game_rotation",
}
_RECEIPT_PARAMS: dict[str, dict[str, int | str]] = {
    "stg_league_game_log": {
        "season": "2024-25",
        "season_type": "Regular Season",
    },
    "stg_matchup": {"game_id": "0022400001"},
    "stg_rotation_away": {"game_id": "0022400001"},
    "stg_rotation_home": {"game_id": "0022400001"},
}
_RECEIPT_ROUTE_INDEX = {
    "stg_league_game_log": 0,
    "stg_matchup": 0,
    "stg_rotation_away": 0,
    "stg_rotation_home": 1,
}


def _receipt(table_name: str, *, row_count: int, marker: str) -> FoundationInputReceipt:
    endpoint_name = _RECEIPT_ENDPOINTS[table_name]
    parameters = _RECEIPT_PARAMS[table_name]
    authority_kind = (
        FoundationAuthorityKind.DISCOVERY_GENERATION
        if table_name == "stg_league_game_log"
        else FoundationAuthorityKind.STAGING_CHUNK
    )
    return FoundationInputReceipt(
        authority_kind=authority_kind,
        table_name=table_name,
        chunk_id=marker * 64,
        endpoint_name=endpoint_name,
        logical_call_receipt_sha256=(
            None if authority_kind is FoundationAuthorityKind.DISCOVERY_GENERATION else marker * 64
        ),
        discovery_manifest_sha256=(
            marker * 64 if authority_kind is FoundationAuthorityKind.DISCOVERY_GENERATION else None
        ),
        logical_parameters=tuple(parameters.items()),
        logical_parameters_sha256=canonical_parameters_sha256(parameters),
        provider_authority_sha256=_PROVIDER_SHA,
        result_route_id=f"{endpoint_name}:{table_name}:{_RECEIPT_ROUTE_INDEX[table_name]}",
        persisted_content_sha256=marker.lower() * 64,
        persisted_schema_sha256=str((int(marker, 16) + 1) % 10) * 64,
        persisted_row_count=row_count,
    )


def _receipts() -> tuple[FoundationInputReceipt, ...]:
    return (
        _receipt("stg_league_game_log", row_count=1, marker="3"),
        _receipt("stg_matchup", row_count=1, marker="4"),
        _receipt("stg_rotation_away", row_count=5, marker="5"),
        _receipt("stg_rotation_home", row_count=5, marker="6"),
    )


def _authority(
    *,
    transaction: CheckpointTransaction | None = None,
    receipts: tuple[FoundationInputReceipt, ...] | None = None,
    compiler_sha256: str = DEPENDENT_WORKLOAD_COMPILER_SHA256,
) -> FoundationAuthority:
    return FoundationAuthority(
        checkpoint_transaction=transaction or _committed_transaction(),
        checkpoint_report_sha256=_REPORT_SHA,
        checkpoint_database_sha256=_DATABASE_SHA,
        discovery_artifact_id=303,
        discovery_artifact_run_id=202,
        discovery_artifact_name="full-extraction-discovery-artifacts-chain-a",
        discovery_artifact_digest="e" * 64,
        provider_authority_sha256=_PROVIDER_SHA,
        source_sha=_SOURCE_SHA,
        compiler_implementation_sha256=compiler_sha256,
        query_plan_sha256=DEPENDENT_WORKLOAD_QUERY_PLAN_SHA256,
        input_receipts=receipts or _receipts(),
    )


def _receipt_source(table_name: str, row_ordinal: int = 0) -> SourceRowIdentity:
    receipt = next(item for item in _receipts() if item.table_name == table_name)
    return SourceRowIdentity(receipt.identity_sha256, row_ordinal)


def _bundle(*, authority: FoundationAuthority | None = None) -> DependentWorkloadBundle:
    league_receipt = next(item for item in _receipts() if item.table_name == "stg_league_game_log")
    scope = WorkloadScope(
        "2024-25",
        "Regular Season",
        "0022400001",
        league_receipt.identity_sha256,
        0,
    )
    matchup_source = _receipt_source("stg_matchup")
    player = PlayerMatchupOccurrence(scope, 11, 101, 21, 202, matchup_source)
    team = TeamPlayerOccurrence(scope, 101, 21, 202, matchup_source)
    lineup_sources = tuple(
        [_receipt_source("stg_rotation_away", index) for index in range(5)]
        + [_receipt_source("stg_rotation_home", index) for index in range(5)]
    )
    lineup = FiveVsFiveOccurrence(
        scope=scope,
        interval_start="0",
        interval_end="10",
        team_id=101,
        team_player_ids=(11, 12, 13, 14, 15),
        team_side="away",
        vs_team_id=202,
        vs_player_ids=(21, 22, 23, 24, 25),
        vs_team_side="home",
        source_rows=lineup_sources,
    )
    reverse_lineup = FiveVsFiveOccurrence(
        scope=scope,
        interval_start="0",
        interval_end="10",
        team_id=202,
        team_player_ids=(21, 22, 23, 24, 25),
        team_side="home",
        vs_team_id=101,
        vs_player_ids=(11, 12, 13, 14, 15),
        vs_team_side="away",
        source_rows=lineup_sources,
    )
    units = (
        DependentExecutableUnit(
            DependentWorkloadKind.PLAYER_MATCHUP,
            (
                ("season", scope.season),
                ("season_type", scope.season_type),
                ("player_id", 11),
                ("vs_player_id", 21),
            ),
            (player.identity_sha256,),
        ),
        DependentExecutableUnit(
            DependentWorkloadKind.TEAM_PLAYER,
            (
                ("season", scope.season),
                ("season_type", scope.season_type),
                ("team_id", 101),
                ("vs_player_id", 21),
            ),
            (team.identity_sha256,),
        ),
        DependentExecutableUnit(
            DependentWorkloadKind.FIVE_V_FIVE,
            (
                ("season", scope.season),
                ("season_type", scope.season_type),
                ("team_id", 101),
                ("vs_team_id", 202),
                ("player_id1", 11),
                ("player_id2", 12),
                ("player_id3", 13),
                ("player_id4", 14),
                ("player_id5", 15),
                ("vs_player_id1", 21),
                ("vs_player_id2", 22),
                ("vs_player_id3", 23),
                ("vs_player_id4", 24),
                ("vs_player_id5", 25),
            ),
            (lineup.identity_sha256,),
        ),
        DependentExecutableUnit(
            DependentWorkloadKind.FIVE_V_FIVE,
            (
                ("season", scope.season),
                ("season_type", scope.season_type),
                ("team_id", 202),
                ("vs_team_id", 101),
                ("player_id1", 21),
                ("player_id2", 22),
                ("player_id3", 23),
                ("player_id4", 24),
                ("player_id5", 25),
                ("vs_player_id1", 11),
                ("vs_player_id2", 12),
                ("vs_player_id3", 13),
                ("vs_player_id4", 14),
                ("vs_player_id5", 15),
            ),
            (reverse_lineup.identity_sha256,),
        ),
    )
    dispositions = tuple(
        ScopeDispositionRecord(
            scope=scope,
            kind=kind,
            disposition=DependentScopeDisposition.COMPLETE,
            reason_code="observed",
            occurrence_count=(2 if kind is DependentWorkloadKind.FIVE_V_FIVE else 1),
            executable_unit_count=(2 if kind is DependentWorkloadKind.FIVE_V_FIVE else 1),
        )
        for kind in DependentWorkloadKind
    )
    return DependentWorkloadBundle(
        authority=authority or _authority(),
        player_matchup_occurrences=(player,),
        team_player_occurrences=(team,),
        five_v_five_occurrences=(lineup, reverse_lineup),
        executable_units=units,
        scope_dispositions=dispositions,
    )


def test_authority_binds_exact_committed_checkpoint_and_receipt_inventory() -> None:
    authority = _authority(receipts=tuple(reversed(_receipts())))

    assert [item.table_name for item in authority.input_receipts] == [
        "stg_league_game_log",
        "stg_matchup",
        "stg_rotation_away",
        "stg_rotation_home",
    ]
    payload = authority.to_dict()
    assert payload["checkpoint_transaction"]["state"] == "committed"
    assert payload["checkpoint_artifact_id"] == 101
    assert payload["checkpoint_artifact_run_id"] == 202
    assert payload["checkpoint_report_sha256"] == _REPORT_SHA
    assert payload["checkpoint_database_sha256"] == _DATABASE_SHA
    assert "private_cas_manifest_sha256" not in payload
    assert "private_cas_artifact_set_sha256" not in payload
    assert payload["provider_authority_sha256"] == _PROVIDER_SHA
    assert len(authority.checkpoint_transaction_sha256) == 64
    assert len(authority.input_receipts_sha256) == 64


def test_authority_rejects_uncommitted_or_digest_drifted_checkpoint() -> None:
    committed = _committed_transaction()
    assert committed.build is not None
    candidate = CheckpointTransaction.candidate(
        chain_id="chain-a",
        source_sha=_SOURCE_SHA,
        generation=2,
        artifact_name="full-extraction-checkpoint-chain-a-iter-2",
        lane_contracts=[{"lane_id": "foundation", "coverage_units_hash": "1" * 64}],
        coverage_fingerprint="2" * 64,
    )

    with pytest.raises(DependentWorkloadContractError, match="must be committed"):
        _authority(transaction=candidate)
    with pytest.raises(DependentWorkloadContractError, match="report digest differs"):
        FoundationAuthority(
            checkpoint_transaction=committed,
            checkpoint_report_sha256="0" * 64,
            checkpoint_database_sha256=_DATABASE_SHA,
            discovery_artifact_id=303,
            discovery_artifact_run_id=202,
            discovery_artifact_name="full-extraction-discovery-artifacts-chain-a",
            discovery_artifact_digest="e" * 64,
            provider_authority_sha256=_PROVIDER_SHA,
            source_sha=_SOURCE_SHA,
            compiler_implementation_sha256=DEPENDENT_WORKLOAD_COMPILER_SHA256,
            query_plan_sha256=DEPENDENT_WORKLOAD_QUERY_PLAN_SHA256,
            input_receipts=_receipts(),
        )


def test_bundle_has_deterministic_content_address_and_post_foundation_state() -> None:
    first = _bundle()
    second = _bundle(authority=_authority(receipts=tuple(reversed(_receipts()))))

    assert first.canonical_bytes == second.canonical_bytes
    assert first.content_sha256 == second.content_sha256
    assert first.generation_basename == f"dependent-workload.{first.content_sha256}.json"
    assert first.to_payload()["integration_state"] == DEPENDENT_WORKLOAD_INTEGRATION_STATE
    assert first.to_payload()["integration_state"] == "post_foundation_ready"
    assert first.to_payload()["inventory"] == second.to_payload()["inventory"]


def test_bundle_and_nested_contracts_are_immutable() -> None:
    bundle = _bundle()

    with pytest.raises(FrozenInstanceError):
        bundle.authority.source_sha = "0" * 40  # type: ignore[misc]
    with pytest.raises(TypeError):
        bundle.executable_units[0].parameters[0] = ("season", "2023-24")  # type: ignore[index]


def test_executable_and_lineup_contracts_reject_zero_duplicate_or_overlap_ids() -> None:
    league_receipt = next(item for item in _receipts() if item.table_name == "stg_league_game_log")
    scope = WorkloadScope(
        "2024-25",
        "Regular Season",
        "0022400001",
        league_receipt.identity_sha256,
        0,
    )
    source = _receipt_source("stg_matchup")
    occurrence = PlayerMatchupOccurrence(scope, 11, 101, 21, 202, source)

    with pytest.raises(DependentWorkloadContractError, match="positive integer"):
        DependentExecutableUnit(
            DependentWorkloadKind.PLAYER_MATCHUP,
            (
                ("season", scope.season),
                ("season_type", scope.season_type),
                ("player_id", 0),
                ("vs_player_id", 21),
            ),
            (occurrence.identity_sha256,),
        )
    with pytest.raises(DependentWorkloadContractError, match="must not overlap"):
        FiveVsFiveOccurrence(
            scope=scope,
            interval_start="0",
            interval_end="1",
            team_id=101,
            team_player_ids=(11, 12, 13, 14, 15),
            team_side="away",
            vs_team_id=202,
            vs_player_ids=(15, 22, 23, 24, 25),
            vs_team_side="home",
            source_rows=tuple(SourceRowIdentity(f"{index + 1:064x}", 0) for index in range(10)),
        )


def test_bundle_rejects_unbound_occurrence_reference() -> None:
    bundle = _bundle()
    first_unit = bundle.executable_units[0]
    tampered = DependentExecutableUnit(
        kind=first_unit.kind,
        parameters=first_unit.parameters,
        occurrence_sha256s=("9" * 64,),
    )

    with pytest.raises(DependentWorkloadContractError, match="wrong kind"):
        DependentWorkloadBundle(
            authority=bundle.authority,
            player_matchup_occurrences=bundle.player_matchup_occurrences,
            team_player_occurrences=bundle.team_player_occurrences,
            five_v_five_occurrences=bundle.five_v_five_occurrences,
            executable_units=(tampered, *bundle.executable_units[1:]),
            scope_dispositions=bundle.scope_dispositions,
        )


def test_bundle_requires_both_exact_five_v_five_directions() -> None:
    bundle = _bundle()
    away_occurrence = next(
        item for item in bundle.five_v_five_occurrences if item.team_side == "away"
    )
    away_unit = next(
        item
        for item in bundle.executable_units
        if item.kind is DependentWorkloadKind.FIVE_V_FIVE
        and dict(item.parameters)["team_id"] == away_occurrence.team_id
    )
    dispositions = tuple(
        replace(item, occurrence_count=1, executable_unit_count=1)
        if item.kind is DependentWorkloadKind.FIVE_V_FIVE
        else item
        for item in bundle.scope_dispositions
    )

    with pytest.raises(DependentWorkloadContractError, match="missing its exact reverse"):
        DependentWorkloadBundle(
            authority=bundle.authority,
            player_matchup_occurrences=bundle.player_matchup_occurrences,
            team_player_occurrences=bundle.team_player_occurrences,
            five_v_five_occurrences=(away_occurrence,),
            executable_units=tuple(
                item
                for item in bundle.executable_units
                if item.kind is not DependentWorkloadKind.FIVE_V_FIVE
            )
            + (away_unit,),
            scope_dispositions=dispositions,
        )


def test_compiler_identity_is_content_bound_in_bundle() -> None:
    baseline = _bundle()
    changed = _bundle(authority=_authority(compiler_sha256="0" * 64))

    assert baseline.authority.compiler_implementation_sha256 != (
        changed.authority.compiler_implementation_sha256
    )
    assert baseline.content_sha256 != changed.content_sha256


def test_executable_units_conserve_every_physical_alias() -> None:
    endpoints = {unit.kind: unit.endpoint_names for unit in _bundle().executable_units}

    assert endpoints[DependentWorkloadKind.PLAYER_MATCHUP] == ("player_vs_player",)
    assert endpoints[DependentWorkloadKind.TEAM_PLAYER] == ("team_vs_player",)
    assert endpoints[DependentWorkloadKind.FIVE_V_FIVE] == (
        "team_and_players_vs",
        "team_and_players_vs_players",
    )
