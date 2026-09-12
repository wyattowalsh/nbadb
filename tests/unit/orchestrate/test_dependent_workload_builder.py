from __future__ import annotations

from decimal import Decimal

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
    DirectionalMatchupObservation,
    FoundationEvidenceState,
    FoundationScopeEvidence,
    RotationObservation,
    compile_dependent_workload,
)
from nbadb.orchestrate.dependent_workload_contract import (
    DependentScopeDisposition,
    DependentWorkloadContractError,
    DependentWorkloadInconclusiveError,
    DependentWorkloadKind,
    FoundationAuthority,
    FoundationAuthorityKind,
    FoundationInputReceipt,
    SourceRowIdentity,
    WorkloadScope,
)
from nbadb.orchestrate.public_value_authority_store import PUBLIC_VALUE_AUTHORITY_TABLES
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE

_SOURCE_SHA = "a" * 40
_DATABASE_SHA = "b" * 64
_REPORT_SHA = "c" * 64
_PROVIDER_SHA = "9" * 64


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
        generation=1,
        artifact_name="full-extraction-checkpoint-chain-a-iter-1",
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
        generation=1,
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
_RECEIPT_ROUTE_INDEX = {
    "stg_league_game_log": 0,
    "stg_matchup": 0,
    "stg_rotation_away": 0,
    "stg_rotation_home": 1,
}


def _receipt(
    table_name: str,
    marker: str,
    *,
    row_count: int,
    game_id: str = "0022400001",
) -> FoundationInputReceipt:
    endpoint_name = _RECEIPT_ENDPOINTS[table_name]
    parameters: dict[str, int | str] = (
        {
            "season": "2024-25",
            "season_type": "Regular Season",
        }
        if table_name == "stg_league_game_log"
        else {"game_id": game_id}
    )
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
        persisted_content_sha256=(
            marker * 64
            if authority_kind is FoundationAuthorityKind.DISCOVERY_GENERATION
            else str((int(marker, 16) + 1) % 10) * 64
        ),
        persisted_schema_sha256=str((int(marker, 16) + 2) % 10) * 64,
        persisted_row_count=row_count,
    )


def _receipts(
    game_ids: tuple[str, ...] = ("0022400001",),
    *,
    matchup_rows: dict[str, int] | None = None,
    rotation_rows: dict[str, tuple[int, int]] | None = None,
) -> tuple[FoundationInputReceipt, ...]:
    matchup_counts = {game_id: 1 for game_id in game_ids} if matchup_rows is None else matchup_rows
    rotation_counts = (
        {game_id: (5, 5) for game_id in game_ids} if rotation_rows is None else rotation_rows
    )
    receipts = [_receipt("stg_league_game_log", "3", row_count=len(game_ids))]
    marker_index = 4
    for game_id in game_ids:
        if game_id in matchup_counts:
            receipts.append(
                _receipt(
                    "stg_matchup",
                    format(marker_index, "x"),
                    row_count=matchup_counts[game_id],
                    game_id=game_id,
                )
            )
            marker_index += 1
        if game_id in rotation_counts:
            away_count, home_count = rotation_counts[game_id]
            receipts.extend(
                (
                    _receipt(
                        "stg_rotation_away",
                        format(marker_index, "x"),
                        row_count=away_count,
                        game_id=game_id,
                    ),
                    _receipt(
                        "stg_rotation_home",
                        format(marker_index + 1, "x"),
                        row_count=home_count,
                        game_id=game_id,
                    ),
                )
            )
            marker_index += 2
    return tuple(receipts)


def _authority(
    *,
    receipts: tuple[FoundationInputReceipt, ...] | None = None,
    compiler_sha256: str = DEPENDENT_WORKLOAD_COMPILER_SHA256,
) -> FoundationAuthority:
    return FoundationAuthority(
        checkpoint_transaction=_committed_transaction(),
        checkpoint_report_sha256=_REPORT_SHA,
        checkpoint_database_sha256=_DATABASE_SHA,
        discovery_artifact_id=303,
        discovery_artifact_run_id=202,
        discovery_artifact_name="full-extraction-discovery-artifacts-chain-a",
        discovery_artifact_digest="8" * 64,
        provider_authority_sha256=_PROVIDER_SHA,
        source_sha=_SOURCE_SHA,
        compiler_implementation_sha256=compiler_sha256,
        query_plan_sha256=DEPENDENT_WORKLOAD_QUERY_PLAN_SHA256,
        input_receipts=receipts or _receipts(),
    )


def _scope(
    game_id: str = "0022400001",
    *,
    receipts: tuple[FoundationInputReceipt, ...] | None = None,
) -> WorkloadScope:
    receipt_inventory = receipts or _receipts()
    receipt = next(
        receipt for receipt in receipt_inventory if receipt.table_name == "stg_league_game_log"
    )
    return WorkloadScope(
        "2024-25",
        "Regular Season",
        game_id,
        receipt.identity_sha256,
        int(game_id[-1]) - 1,
    )


def _source(
    table_name: str,
    row_ordinal: int,
    *,
    receipts: tuple[FoundationInputReceipt, ...] | None = None,
    game_id: str = "0022400001",
) -> SourceRowIdentity:
    receipt_inventory = receipts or _receipts()
    receipt = next(
        receipt
        for receipt in receipt_inventory
        if receipt.table_name == table_name
        and (
            table_name == "stg_league_game_log"
            or dict(receipt.logical_parameters) == {"game_id": game_id}
        )
    )
    return SourceRowIdentity(receipt.identity_sha256, row_ordinal)


def _evidence(
    scope: WorkloadScope,
    *,
    matchup_state: FoundationEvidenceState = FoundationEvidenceState.COMPLETE,
    rotation_state: FoundationEvidenceState = FoundationEvidenceState.COMPLETE,
    matchup_reason_code: str = "",
    rotation_reason_code: str = "",
) -> FoundationScopeEvidence:
    return FoundationScopeEvidence(
        scope=scope,
        matchup_state=matchup_state,
        rotation_state=rotation_state,
        matchup_reason_code=matchup_reason_code,
        rotation_reason_code=rotation_reason_code,
    )


def _matchup(
    scope: WorkloadScope,
    *,
    ordinal: int = 0,
    off_player_id: int = 11,
    def_player_id: int = 21,
    receipts: tuple[FoundationInputReceipt, ...] | None = None,
) -> DirectionalMatchupObservation:
    return DirectionalMatchupObservation(
        scope=scope,
        off_team_id=101,
        off_player_id=off_player_id,
        def_team_id=202,
        def_player_id=def_player_id,
        source_row=_source(
            "stg_matchup",
            ordinal,
            receipts=receipts,
            game_id=scope.game_id,
        ),
    )


def _rotation_rows(
    scope: WorkloadScope,
    *,
    away_players: tuple[int, ...] = (11, 12, 13, 14, 15),
    home_players: tuple[int, ...] = (21, 22, 23, 24, 25),
    start: str = "0",
    end: str = "10",
    ordinal_offset: int = 0,
    receipts: tuple[FoundationInputReceipt, ...] | None = None,
) -> tuple[RotationObservation, ...]:
    return tuple(
        [
            RotationObservation(
                scope=scope,
                side="away",
                team_id=101,
                player_id=player_id,
                interval_start=Decimal(start),
                interval_end=Decimal(end),
                source_row=_source(
                    "stg_rotation_away",
                    ordinal_offset + index,
                    receipts=receipts,
                    game_id=scope.game_id,
                ),
            )
            for index, player_id in enumerate(away_players)
        ]
        + [
            RotationObservation(
                scope=scope,
                side="home",
                team_id=202,
                player_id=player_id,
                interval_start=Decimal(start),
                interval_end=Decimal(end),
                source_row=_source(
                    "stg_rotation_home",
                    ordinal_offset + index,
                    receipts=receipts,
                    game_id=scope.game_id,
                ),
            )
            for index, player_id in enumerate(home_players)
        ]
    )


def test_compiler_emits_direct_occurrences_and_deduplicated_executable_units() -> None:
    scope = _scope()

    bundle = compile_dependent_workload(
        authority=_authority(),
        scope_evidence=[_evidence(scope)],
        matchup_observations=[_matchup(scope)],
        rotation_observations=_rotation_rows(scope),
    )

    assert len(bundle.player_matchup_occurrences) == 1
    assert len(bundle.team_player_occurrences) == 1
    assert len(bundle.five_v_five_occurrences) == 2
    assert len(bundle.executable_units) == 4
    assert len(bundle.scope_dispositions) == 3
    player = bundle.player_matchup_occurrences[0]
    assert (player.player_id, player.vs_player_id) == (11, 21)
    assert (player.player_team_id, player.vs_team_id) == (101, 202)
    lineups = {(item.team_side, item.vs_team_side): item for item in bundle.five_v_five_occurrences}
    assert set(lineups) == {("away", "home"), ("home", "away")}
    assert all(item.interval_start == "0" for item in lineups.values())
    assert all(item.interval_end == "10" for item in lineups.values())
    assert lineups[("away", "home")].team_player_ids == (11, 12, 13, 14, 15)
    assert lineups[("away", "home")].vs_player_ids == (21, 22, 23, 24, 25)
    assert lineups[("home", "away")].team_player_ids == (21, 22, 23, 24, 25)
    assert lineups[("home", "away")].vs_player_ids == (11, 12, 13, 14, 15)
    lineup_disposition = next(
        item for item in bundle.scope_dispositions if item.kind is DependentWorkloadKind.FIVE_V_FIVE
    )
    assert (lineup_disposition.occurrence_count, lineup_disposition.executable_unit_count) == (
        2,
        2,
    )
    assert all(
        item.disposition is DependentScopeDisposition.COMPLETE for item in bundle.scope_dispositions
    )


def test_directional_matchup_never_synthesizes_reverse_or_cartesian_pairs() -> None:
    game_id = "0022400001"
    receipts = _receipts(
        matchup_rows={game_id: 2},
        rotation_rows={game_id: (0, 0)},
    )
    scope = _scope(receipts=receipts)
    observations = (
        _matchup(
            scope,
            ordinal=0,
            off_player_id=11,
            def_player_id=21,
            receipts=receipts,
        ),
        _matchup(
            scope,
            ordinal=1,
            off_player_id=12,
            def_player_id=22,
            receipts=receipts,
        ),
    )

    bundle = compile_dependent_workload(
        authority=_authority(receipts=receipts),
        scope_evidence=[_evidence(scope, rotation_state=FoundationEvidenceState.VALID_EMPTY)],
        matchup_observations=observations,
        rotation_observations=(),
    )

    pairs = {(item.player_id, item.vs_player_id) for item in bundle.player_matchup_occurrences}
    assert pairs == {(11, 21), (12, 22)}
    assert (21, 11) not in pairs
    assert (11, 22) not in pairs
    assert (12, 21) not in pairs
    assert {(item.team_id, item.vs_player_id) for item in bundle.team_player_occurrences} == {
        (101, 21),
        (101, 22),
    }


def test_matchup_receipt_requires_every_attested_row_under_reordering() -> None:
    game_id = "0022400001"
    receipts = _receipts(
        matchup_rows={game_id: 2},
        rotation_rows={game_id: (0, 0)},
    )
    scope = _scope(receipts=receipts)
    observations = (
        _matchup(scope, ordinal=0, off_player_id=11, def_player_id=21, receipts=receipts),
        _matchup(scope, ordinal=1, off_player_id=12, def_player_id=22, receipts=receipts),
    )
    evidence = [_evidence(scope, rotation_state=FoundationEvidenceState.VALID_EMPTY)]

    forward = compile_dependent_workload(
        authority=_authority(receipts=receipts),
        scope_evidence=evidence,
        matchup_observations=observations,
        rotation_observations=(),
    )
    reverse = compile_dependent_workload(
        authority=_authority(receipts=tuple(reversed(receipts))),
        scope_evidence=evidence,
        matchup_observations=tuple(reversed(observations)),
        rotation_observations=(),
    )
    assert forward.canonical_bytes == reverse.canonical_bytes

    with pytest.raises(DependentWorkloadContractError, match="not consumed exactly"):
        compile_dependent_workload(
            authority=_authority(receipts=receipts),
            scope_evidence=evidence,
            matchup_observations=observations[:-1],
            rotation_observations=(),
        )


def test_duplicate_matchup_row_cannot_replace_an_attested_ordinal() -> None:
    game_id = "0022400001"
    receipts = _receipts(
        matchup_rows={game_id: 2},
        rotation_rows={game_id: (0, 0)},
    )
    scope = _scope(receipts=receipts)
    observations = (
        _matchup(scope, ordinal=0, off_player_id=11, def_player_id=21, receipts=receipts),
        _matchup(scope, ordinal=0, off_player_id=12, def_player_id=22, receipts=receipts),
    )

    with pytest.raises(DependentWorkloadContractError, match="source rows must be unique"):
        compile_dependent_workload(
            authority=_authority(receipts=receipts),
            scope_evidence=[_evidence(scope, rotation_state=FoundationEvidenceState.VALID_EMPTY)],
            matchup_observations=observations,
            rotation_observations=(),
        )


def test_receipt_from_another_game_cannot_replace_a_matchup_row() -> None:
    game_ids = ("0022400001", "0022400002")
    receipts = _receipts(
        game_ids,
        matchup_rows={game_id: 1 for game_id in game_ids},
        rotation_rows={game_id: (0, 0) for game_id in game_ids},
    )
    first_scope = _scope(game_ids[0], receipts=receipts)
    second_scope = _scope(game_ids[1], receipts=receipts)
    rebound = DirectionalMatchupObservation(
        scope=first_scope,
        off_team_id=101,
        off_player_id=11,
        def_team_id=202,
        def_player_id=21,
        source_row=_source(
            "stg_matchup",
            0,
            receipts=receipts,
            game_id=second_scope.game_id,
        ),
    )

    with pytest.raises(DependentWorkloadContractError, match="receipt game scope"):
        compile_dependent_workload(
            authority=_authority(receipts=receipts),
            scope_evidence=[
                _evidence(
                    first_scope,
                    rotation_state=FoundationEvidenceState.VALID_EMPTY,
                ),
                _evidence(
                    second_scope,
                    matchup_state=FoundationEvidenceState.BLOCKED,
                    rotation_state=FoundationEvidenceState.VALID_EMPTY,
                    matchup_reason_code="matchup_contract_blocked",
                ),
            ],
            matchup_observations=[rebound],
            rotation_observations=(),
        )


def test_repeated_observed_occurrences_deduplicate_only_the_provider_unit() -> None:
    game_ids = ("0022400001", "0022400002")
    receipts = _receipts(
        game_ids,
        matchup_rows={game_id: 1 for game_id in game_ids},
        rotation_rows={game_id: (0, 0) for game_id in game_ids},
    )
    first_scope = _scope(game_ids[0], receipts=receipts)
    second_scope = _scope(game_ids[1], receipts=receipts)

    bundle = compile_dependent_workload(
        authority=_authority(receipts=receipts),
        scope_evidence=[
            _evidence(first_scope, rotation_state=FoundationEvidenceState.VALID_EMPTY),
            _evidence(second_scope, rotation_state=FoundationEvidenceState.VALID_EMPTY),
        ],
        matchup_observations=[
            _matchup(first_scope, receipts=receipts),
            _matchup(second_scope, receipts=receipts),
        ],
        rotation_observations=(),
    )

    assert len(bundle.player_matchup_occurrences) == 2
    assert len(bundle.team_player_occurrences) == 2
    player_units = [
        item
        for item in bundle.executable_units
        if item.kind is DependentWorkloadKind.PLAYER_MATCHUP
    ]
    team_units = [
        item for item in bundle.executable_units if item.kind is DependentWorkloadKind.TEAM_PLAYER
    ]
    assert len(player_units) == 1
    assert len(player_units[0].occurrence_sha256s) == 2
    assert len(team_units) == 1
    assert len(team_units[0].occurrence_sha256s) == 2


def test_repeated_exact_lineups_deduplicate_only_canonical_directional_keys() -> None:
    game_ids = ("0022400001", "0022400002")
    receipts = _receipts(
        game_ids,
        matchup_rows={game_id: 0 for game_id in game_ids},
    )
    first_scope = _scope(game_ids[0], receipts=receipts)
    second_scope = _scope(game_ids[1], receipts=receipts)

    bundle = compile_dependent_workload(
        authority=_authority(receipts=receipts),
        scope_evidence=[
            _evidence(first_scope, matchup_state=FoundationEvidenceState.VALID_EMPTY),
            _evidence(second_scope, matchup_state=FoundationEvidenceState.VALID_EMPTY),
        ],
        matchup_observations=(),
        rotation_observations=(
            *_rotation_rows(first_scope, receipts=receipts),
            *_rotation_rows(second_scope, receipts=receipts),
        ),
    )

    lineup_units = [
        item for item in bundle.executable_units if item.kind is DependentWorkloadKind.FIVE_V_FIVE
    ]
    assert len(bundle.five_v_five_occurrences) == 4
    assert len(lineup_units) == 2
    assert {len(item.occurrence_sha256s) for item in lineup_units} == {2}
    assert {
        (dict(item.parameters)["team_id"], dict(item.parameters)["vs_team_id"])
        for item in lineup_units
    } == {(101, 202), (202, 101)}


def test_rotation_boundaries_compile_two_exact_stints_without_widening() -> None:
    game_id = "0022400001"
    receipts = _receipts(
        matchup_rows={game_id: 0},
        rotation_rows={game_id: (6, 5)},
    )
    scope = _scope(receipts=receipts)
    rows = list(_rotation_rows(scope, end="10", receipts=receipts))
    rows[4] = RotationObservation(
        scope=scope,
        side="away",
        team_id=101,
        player_id=15,
        interval_start=Decimal("0"),
        interval_end=Decimal("5"),
        source_row=_source("stg_rotation_away", 4, receipts=receipts),
    )
    rows.append(
        RotationObservation(
            scope=scope,
            side="away",
            team_id=101,
            player_id=16,
            interval_start=Decimal("5"),
            interval_end=Decimal("10"),
            source_row=_source("stg_rotation_away", 5, receipts=receipts),
        )
    )

    bundle = compile_dependent_workload(
        authority=_authority(receipts=receipts),
        scope_evidence=[_evidence(scope, matchup_state=FoundationEvidenceState.VALID_EMPTY)],
        matchup_observations=(),
        rotation_observations=rows,
    )

    assert sorted(
        (
            item.interval_start,
            item.interval_end,
            item.team_side,
            item.team_player_ids,
        )
        for item in bundle.five_v_five_occurrences
    ) == [
        ("0", "5", "away", (11, 12, 13, 14, 15)),
        ("0", "5", "home", (21, 22, 23, 24, 25)),
        ("5", "10", "away", (11, 12, 13, 14, 16)),
        ("5", "10", "home", (21, 22, 23, 24, 25)),
    ]
    assert (
        len(
            [
                unit
                for unit in bundle.executable_units
                if unit.kind is DependentWorkloadKind.FIVE_V_FIVE
            ]
        )
        == 4
    )


def test_rotation_receipt_rejects_one_omitted_attested_row() -> None:
    game_id = "0022400001"
    receipts = _receipts(
        matchup_rows={game_id: 0},
        rotation_rows={game_id: (5, 5)},
    )
    scope = _scope(receipts=receipts)
    rows = _rotation_rows(scope, receipts=receipts)

    with pytest.raises(DependentWorkloadContractError, match="not consumed exactly"):
        compile_dependent_workload(
            authority=_authority(receipts=receipts),
            scope_evidence=[_evidence(scope, matchup_state=FoundationEvidenceState.VALID_EMPTY)],
            matchup_observations=(),
            rotation_observations=rows[:-1],
        )


@pytest.mark.parametrize(
    ("away_players", "home_players", "reason_code"),
    [
        ((11, 12, 13, 14), (21, 22, 23, 24, 25), "rotation_interval_not_exact_five"),
        ((11, 12, 13, 14, 14), (21, 22, 23, 24, 25), "rotation_interval_duplicate_player"),
        ((11, 12, 13, 14, 15), (15, 22, 23, 24, 25), "rotation_interval_player_overlap"),
    ],
)
def test_incomplete_or_invalid_lineup_is_blocked_without_request(
    away_players: tuple[int, ...],
    home_players: tuple[int, ...],
    reason_code: str,
) -> None:
    game_id = "0022400001"
    receipts = _receipts(
        matchup_rows={game_id: 0},
        rotation_rows={game_id: (len(away_players), len(home_players))},
    )
    scope = _scope(receipts=receipts)

    bundle = compile_dependent_workload(
        authority=_authority(receipts=receipts),
        scope_evidence=[_evidence(scope, matchup_state=FoundationEvidenceState.VALID_EMPTY)],
        matchup_observations=(),
        rotation_observations=_rotation_rows(
            scope,
            away_players=away_players,
            home_players=home_players,
            receipts=receipts,
        ),
    )

    assert bundle.five_v_five_occurrences == ()
    assert all(
        unit.kind is not DependentWorkloadKind.FIVE_V_FIVE for unit in bundle.executable_units
    )
    disposition = next(
        item for item in bundle.scope_dispositions if item.kind is DependentWorkloadKind.FIVE_V_FIVE
    )
    assert disposition.disposition is DependentScopeDisposition.BLOCKED
    assert disposition.reason_code == reason_code


def test_valid_empty_and_explicit_blocked_are_distinct_terminal_dispositions() -> None:
    game_ids = ("0022400001", "0022400002")
    receipts = _receipts(
        game_ids,
        matchup_rows={game_ids[0]: 0},
        rotation_rows={game_ids[0]: (0, 0)},
    )
    empty_scope = _scope(game_ids[0], receipts=receipts)
    blocked_scope = _scope(game_ids[1], receipts=receipts)

    bundle = compile_dependent_workload(
        authority=_authority(receipts=receipts),
        scope_evidence=[
            _evidence(
                empty_scope,
                matchup_state=FoundationEvidenceState.VALID_EMPTY,
                rotation_state=FoundationEvidenceState.VALID_EMPTY,
            ),
            _evidence(
                blocked_scope,
                matchup_state=FoundationEvidenceState.BLOCKED,
                rotation_state=FoundationEvidenceState.BLOCKED,
                matchup_reason_code="matchup_contract_blocked",
                rotation_reason_code="rotation_contract_blocked",
            ),
        ],
        matchup_observations=(),
        rotation_observations=(),
    )

    assert bundle.executable_units == ()
    empty_dispositions = {
        item.disposition for item in bundle.scope_dispositions if item.scope == empty_scope
    }
    blocked_dispositions = {
        item.disposition for item in bundle.scope_dispositions if item.scope == blocked_scope
    }
    assert empty_dispositions == {DependentScopeDisposition.TYPED_ZERO}
    assert blocked_dispositions == {DependentScopeDisposition.BLOCKED}


def test_positive_receipt_cannot_be_typed_zero_but_can_be_explicitly_blocked() -> None:
    game_id = "0022400001"
    receipts = _receipts(
        matchup_rows={game_id: 2},
        rotation_rows={game_id: (0, 0)},
    )
    scope = _scope(receipts=receipts)

    with pytest.raises(DependentWorkloadContractError, match="not consumed exactly"):
        compile_dependent_workload(
            authority=_authority(receipts=receipts),
            scope_evidence=[
                _evidence(
                    scope,
                    matchup_state=FoundationEvidenceState.VALID_EMPTY,
                    rotation_state=FoundationEvidenceState.VALID_EMPTY,
                )
            ],
            matchup_observations=(),
            rotation_observations=(),
        )

    bundle = compile_dependent_workload(
        authority=_authority(receipts=receipts),
        scope_evidence=[
            _evidence(
                scope,
                matchup_state=FoundationEvidenceState.BLOCKED,
                rotation_state=FoundationEvidenceState.VALID_EMPTY,
                matchup_reason_code="matchup_foundation_rows_invalid",
            )
        ],
        matchup_observations=(),
        rotation_observations=(),
    )
    matchup_dispositions = [
        item
        for item in bundle.scope_dispositions
        if item.kind
        in {
            DependentWorkloadKind.PLAYER_MATCHUP,
            DependentWorkloadKind.TEAM_PLAYER,
        }
    ]
    assert {item.disposition for item in matchup_dispositions} == {
        DependentScopeDisposition.BLOCKED
    }


@pytest.mark.parametrize("inconclusive_surface", ["matchup", "rotation"])
def test_inconclusive_foundation_aborts_atomic_compilation(
    inconclusive_surface: str,
) -> None:
    game_id = "0022400001"
    receipts = _receipts(
        matchup_rows={game_id: 0},
        rotation_rows={game_id: (0, 0)},
    )
    scope = _scope(receipts=receipts)
    evidence = _evidence(
        scope,
        matchup_state=(
            FoundationEvidenceState.INCONCLUSIVE
            if inconclusive_surface == "matchup"
            else FoundationEvidenceState.VALID_EMPTY
        ),
        rotation_state=(
            FoundationEvidenceState.INCONCLUSIVE
            if inconclusive_surface == "rotation"
            else FoundationEvidenceState.VALID_EMPTY
        ),
        matchup_reason_code=(
            "matchup_receipt_missing" if inconclusive_surface == "matchup" else ""
        ),
        rotation_reason_code=(
            "rotation_receipt_missing" if inconclusive_surface == "rotation" else ""
        ),
    )

    with pytest.raises(DependentWorkloadInconclusiveError, match="inconclusive"):
        compile_dependent_workload(
            authority=_authority(receipts=receipts),
            scope_evidence=[evidence],
            matchup_observations=(),
            rotation_observations=(),
        )


def test_complete_scope_without_rows_is_inconclusive_not_typed_zero() -> None:
    game_id = "0022400001"
    receipts = _receipts(
        matchup_rows={game_id: 0},
        rotation_rows={game_id: (0, 0)},
    )
    scope = _scope(receipts=receipts)

    with pytest.raises(DependentWorkloadInconclusiveError, match="has no observed rows"):
        compile_dependent_workload(
            authority=_authority(receipts=receipts),
            scope_evidence=[_evidence(scope, rotation_state=FoundationEvidenceState.VALID_EMPTY)],
            matchup_observations=(),
            rotation_observations=(),
        )


def test_source_receipt_table_and_row_ordinal_are_fail_closed() -> None:
    receipts = _receipts()
    scope = _scope(receipts=receipts)
    wrong_table_observation = DirectionalMatchupObservation(
        scope=scope,
        off_team_id=101,
        off_player_id=11,
        def_team_id=202,
        def_player_id=21,
        source_row=_source("stg_rotation_away", 0, receipts=receipts),
    )

    with pytest.raises(DependentWorkloadContractError, match="wrong source table"):
        compile_dependent_workload(
            authority=_authority(receipts=receipts),
            scope_evidence=[_evidence(scope, rotation_state=FoundationEvidenceState.VALID_EMPTY)],
            matchup_observations=[wrong_table_observation],
            rotation_observations=(),
        )

    tiny_scope = scope
    tiny_matchup_receipt = next(item for item in receipts if item.table_name == "stg_matchup")
    out_of_range = DirectionalMatchupObservation(
        scope=tiny_scope,
        off_team_id=101,
        off_player_id=11,
        def_team_id=202,
        def_player_id=21,
        source_row=SourceRowIdentity(tiny_matchup_receipt.identity_sha256, 1),
    )
    with pytest.raises(DependentWorkloadContractError, match="outside its persisted receipt"):
        compile_dependent_workload(
            authority=_authority(receipts=receipts),
            scope_evidence=[
                _evidence(tiny_scope, rotation_state=FoundationEvidenceState.VALID_EMPTY)
            ],
            matchup_observations=[out_of_range],
            rotation_observations=(),
        )


def test_required_receipts_and_compiler_identity_are_pinned() -> None:
    scope = _scope()
    without_home = tuple(
        receipt for receipt in _receipts() if receipt.table_name != "stg_rotation_home"
    )

    with pytest.raises(DependentWorkloadContractError, match="missing required tables"):
        compile_dependent_workload(
            authority=_authority(receipts=without_home),
            scope_evidence=[
                _evidence(
                    scope,
                    matchup_state=FoundationEvidenceState.VALID_EMPTY,
                    rotation_state=FoundationEvidenceState.VALID_EMPTY,
                )
            ],
            matchup_observations=(),
            rotation_observations=(),
        )
    with pytest.raises(DependentWorkloadContractError, match="implementation authority"):
        compile_dependent_workload(
            authority=_authority(compiler_sha256="0" * 64),
            scope_evidence=[
                _evidence(
                    scope,
                    matchup_state=FoundationEvidenceState.VALID_EMPTY,
                    rotation_state=FoundationEvidenceState.VALID_EMPTY,
                )
            ],
            matchup_observations=(),
            rotation_observations=(),
        )


def test_zero_ids_are_rejected_before_an_executable_unit_can_exist() -> None:
    scope = _scope()

    with pytest.raises(DependentWorkloadContractError, match="positive integer"):
        DirectionalMatchupObservation(
            scope=scope,
            off_team_id=101,
            off_player_id=0,
            def_team_id=202,
            def_player_id=21,
            source_row=_source("stg_matchup", 0),
        )
    with pytest.raises(DependentWorkloadContractError, match="positive integer"):
        RotationObservation(
            scope=scope,
            side="away",
            team_id=101,
            player_id=0,
            interval_start=Decimal("0"),
            interval_end=Decimal("1"),
            source_row=_source("stg_rotation_away", 0),
        )


def test_compilation_is_deterministic_under_input_order_changes() -> None:
    game_ids = ("0022400001", "0022400002")
    receipts = _receipts(
        game_ids,
        matchup_rows={game_id: 1 for game_id in game_ids},
        rotation_rows={game_id: (0, 0) for game_id in game_ids},
    )
    first_scope = _scope(game_ids[0], receipts=receipts)
    second_scope = _scope(game_ids[1], receipts=receipts)
    evidence = (
        _evidence(first_scope, rotation_state=FoundationEvidenceState.VALID_EMPTY),
        _evidence(second_scope, rotation_state=FoundationEvidenceState.VALID_EMPTY),
    )
    observations = (
        _matchup(
            first_scope,
            off_player_id=11,
            def_player_id=21,
            receipts=receipts,
        ),
        _matchup(
            second_scope,
            off_player_id=12,
            def_player_id=22,
            receipts=receipts,
        ),
    )

    forward = compile_dependent_workload(
        authority=_authority(receipts=receipts),
        scope_evidence=evidence,
        matchup_observations=observations,
        rotation_observations=(),
    )
    reverse = compile_dependent_workload(
        authority=_authority(receipts=tuple(reversed(receipts))),
        scope_evidence=tuple(reversed(evidence)),
        matchup_observations=tuple(reversed(observations)),
        rotation_observations=(),
    )

    assert forward.canonical_bytes == reverse.canonical_bytes
    assert forward.content_sha256 == reverse.content_sha256
