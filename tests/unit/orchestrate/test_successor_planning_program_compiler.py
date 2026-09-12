from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import duckdb
import pytest

from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.orchestrate.planning import executable_entries_by_pattern
from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDataMember,
    PlanningDispatchPhase,
)
from nbadb.orchestrate.successor_planning_program_compiler import (
    SUCCESSOR_PLANNING_PROGRAM_COMPILER_SCHEMA_VERSION,
    SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE,
    SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE,
    CompiledSuccessorPlanningProgram,
    PlanningSemanticMemberAuthority,
    PlanningSemanticPartitionValues,
    SuccessorPlanningProgramCompilerError,
    compile_successor_planning_program,
    install_successor_planning_semantic_schema,
    read_successor_planning_semantic_registry,
    successor_planning_database_schema_sha256,
    successor_planning_semantic_write_transaction,
    write_successor_planning_semantic_partition,
)
from nbadb.orchestrate.successor_planning_request_builder import (
    build_successor_planning_request,
)
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticDescriptor,
    PlanningSemanticKind,
)
from nbadb.orchestrate.successor_update_contract import (
    CallMutability,
    RequestedRouteScope,
    SuccessorUpdateMode,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    result = duckdb.connect(str(tmp_path / "planning.duckdb"))
    try:
        install_successor_planning_semantic_schema(result)
        yield result
    finally:
        result.close()


def _scope(endpoint_name: str = "league_game_log") -> RequestedRouteScope:
    route = next(
        route
        for route in staging_route_contract_bundle().routes
        if route.endpoint_name == endpoint_name
    )
    if route.param_pattern in {"season", "player_season", "team_season"}:
        parameters: dict[str, object] = {
            "season": "2025-26",
            "season_type": "Regular Season",
        }
    else:
        parameters = {}
    return RequestedRouteScope.from_parameters(
        endpoint_name=route.endpoint_name,
        route_id=route.route_id,
        route_contract_sha256=route.contract_sha256,
        parameters=parameters,
        mutability=CallMutability.MUTABLE,
    )


def _authority(
    *,
    scope: RequestedRouteScope,
    descriptor: object,
    wave_index: int = 0,
    logical_call_receipt_sha256: str = "3" * 64,
    provider_authority_sha256: str | None = None,
) -> PlanningSemanticMemberAuthority:
    assert isinstance(descriptor, PlanningSemanticDescriptor)
    member = PlanningDataMember(
        member_id=f"member-{descriptor.identity_sha256}",
        wave_index=wave_index,
        producing_scope_sha256=scope.identity_sha256,
        schema_sha256="1" * 64,
        content_sha256="2" * 64,
        row_count=descriptor.value_count,
        semantic=descriptor,
        typed_zero_reason_code=descriptor.typed_zero_reason_code,
    )
    return PlanningSemanticMemberAuthority(
        member=member,
        producing_scope=scope,
        logical_call_receipt_sha256=logical_call_receipt_sha256,
        provider_authority_sha256=(
            staging_route_contract_bundle().by_route_id[scope.route_id].provider_authority_sha256
            if provider_authority_sha256 is None
            else provider_authority_sha256
        ),
    )


def _write(
    connection: duckdb.DuckDBPyConnection,
    **kwargs: Any,
) -> PlanningSemanticDescriptor:
    with successor_planning_semantic_write_transaction(connection) as transaction:
        return write_successor_planning_semantic_partition(transaction, **kwargs)


def test_installs_exact_two_table_schema_v2(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    assert SUCCESSOR_PLANNING_PROGRAM_COMPILER_SCHEMA_VERSION == 2
    assert connection.execute(
        f"PRAGMA table_info('{SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE}')"
    ).fetchall() == [
        (0, "descriptor_identity_sha256", "VARCHAR", True, None, True),
        (1, "producing_scope_identity_sha256", "VARCHAR", True, None, False),
        (2, "semantic_kind", "VARCHAR", True, None, False),
        (3, "partition_json", "VARCHAR", True, None, False),
        (4, "semantic_schema_sha256", "VARCHAR", True, None, False),
        (5, "semantic_content_sha256", "VARCHAR", True, None, False),
        (6, "value_count", "UBIGINT", True, None, False),
        (7, "typed_zero_reason_code", "VARCHAR", False, None, False),
    ]
    assert connection.execute(
        f"PRAGMA table_info('{SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE}')"
    ).fetchall() == [
        (0, "descriptor_identity_sha256", "VARCHAR", True, None, True),
        (1, "ordinal", "UBIGINT", True, None, True),
        (2, "value_json", "VARCHAR", True, None, False),
    ]


@pytest.mark.parametrize(
    ("semantic_kind", "endpoint_name", "partition", "values"),
    [
        (
            PlanningSemanticKind.GAME_DATE_INDEX,
            "league_game_log",
            {"season": "2025-26", "season_type": "Regular Season"},
            [
                {"game_id": "0022500002", "game_date": "2025-10-22"},
                {"game_date": "2025-10-21", "game_id": "0022500001"},
            ],
        ),
        (
            PlanningSemanticKind.SEASON_PLAYER_UNIVERSE,
            "common_all_players",
            {"season": "2025-26", "current_only": True},
            [{"player_id": 2544}, {"player_id": 201939}],
        ),
        (
            PlanningSemanticKind.SEASON_TEAM_UNIVERSE,
            "common_team_years",
            {"season": "2025-26"},
            [{"team_id": 1610612747}],
        ),
        (
            PlanningSemanticKind.CURRENT_TEAM_UNIVERSE,
            "common_team_years",
            {"as_of_utc": "2026-08-13T12:30:00Z"},
            [{"team_id": 1610612747}],
        ),
        (
            PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION,
            "player_game_logs",
            {"season": "2025-26", "season_type": "Regular Season"},
            [{"player_id": 2544, "team_id": 1610612747}],
        ),
        (
            PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
            "live_score_board",
            {"as_of_utc": "2026-08-13T12:30:00Z"},
            [{"game_id": "0022500001"}],
        ),
        (
            PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
            "cume_stats_player_games",
            {
                "player_id": 2544,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
            [{"game_id": "0022500002"}, {"game_id": "0022500001"}],
        ),
        (
            PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
            "cume_stats_team_games",
            {
                "team_id": 1610612747,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
            [{"game_id": "0022500001"}],
        ),
    ],
)
def test_write_and_read_recompute_every_nonempty_semantic_kind(
    connection: duckdb.DuckDBPyConnection,
    semantic_kind: PlanningSemanticKind,
    endpoint_name: str,
    partition: dict[str, object],
    values: list[dict[str, object]],
) -> None:
    scope = _scope(endpoint_name)
    descriptor = _write(
        connection,
        producing_scope=scope,
        semantic_kind=semantic_kind,
        partition=partition,
        values=values,
        typed_zero_reason_code=None,
    )
    authority = _authority(scope=scope, descriptor=descriptor)

    registry = read_successor_planning_semantic_registry(
        connection,
        authorities=(authority,),
    )

    assert len(registry) == 1
    assert registry[0].authority == authority
    if semantic_kind in {
        PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
        PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
    }:
        assert tuple(registry[0].values) == tuple(values)
    else:
        assert tuple(registry[0].values) == tuple(
            sorted(values, key=lambda value: tuple(value[key] for key in sorted(value)))
        )
    assert descriptor.semantic_schema_sha256 not in {"0" * 64, "1" * 64}
    assert descriptor.semantic_content_sha256 not in {"0" * 64, "1" * 64}


def test_non_cume_values_are_canonical_deduped_but_cume_order_is_authority(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    players = _scope("common_all_players")
    player_descriptor = _write(
        connection,
        producing_scope=players,
        semantic_kind=PlanningSemanticKind.SEASON_PLAYER_UNIVERSE,
        partition={"season": "2025-26", "current_only": True},
        values=[{"player_id": 2544}, {"player_id": 1}, {"player_id": 2544}],
        typed_zero_reason_code=None,
    )
    assert player_descriptor.value_count == 2

    cume = _scope("cume_stats_player_games")
    with pytest.raises(SuccessorPlanningProgramCompilerError, match="duplicate game IDs"):
        _write(
            connection,
            producing_scope=cume,
            semantic_kind=PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
            partition={
                "player_id": 2544,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
            values=[{"game_id": "0022500001"}, {"game_id": "0022500001"}],
            typed_zero_reason_code=None,
        )


def test_typed_zero_registry_includes_auxiliary_and_provider_empty(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    auxiliary_scope = _scope("common_team_years")
    auxiliary = _write(
        connection,
        producing_scope=auxiliary_scope,
        semantic_kind=PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA,
        partition={},
        values=[],
        typed_zero_reason_code="no_derived_semantic_values",
    )
    live_scope = _scope("live_score_board")
    live = _write(
        connection,
        producing_scope=live_scope,
        semantic_kind=PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
        partition={"as_of_utc": "2026-08-13T12:30:00Z"},
        values=[],
        typed_zero_reason_code="provider_success_empty",
    )
    authorities = (
        _authority(scope=auxiliary_scope, descriptor=auxiliary),
        _authority(scope=live_scope, descriptor=live),
    )

    registry = read_successor_planning_semantic_registry(
        connection,
        authorities=tuple(sorted(authorities, key=lambda item: item.descriptor_identity_sha256)),
    )

    assert len(registry) == 2
    assert all(not item.values for item in registry)
    with pytest.raises(SuccessorPlanningProgramCompilerError, match="exact typed-zero"):
        _write(
            connection,
            producing_scope=auxiliary_scope,
            semantic_kind=PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA,
            partition={},
            values=[],
            typed_zero_reason_code="provider_success_empty",
        )


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ([{"game_id": "225000001", "game_date": "2025-10-21"}], "ten-digit"),
        ([{"game_id": "0022500001", "game_date": "2025-02-30"}], "YYYY-MM-DD"),
        ([{"game_id": "0022500001", "game_date": "2025-10-21", "x": 1}], "fields"),
        ([{"game_id": "0022500001", "game_date": float("nan")}], "YYYY-MM-DD"),
    ],
)
def test_writer_rejects_malformed_unknown_or_nonfinite_values_before_database_write(
    connection: duckdb.DuckDBPyConnection,
    values: list[dict[str, object]],
    match: str,
) -> None:
    with pytest.raises(SuccessorPlanningProgramCompilerError, match=match):
        _write(
            connection,
            producing_scope=_scope(),
            semantic_kind=PlanningSemanticKind.GAME_DATE_INDEX,
            partition={"season": "2025-26", "season_type": "Regular Season"},
            values=values,
            typed_zero_reason_code=None,
        )
    assert connection.execute(
        f"SELECT count(*) FROM {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE}"
    ).fetchone() == (0,)


def _one_game_registry(
    connection: duckdb.DuckDBPyConnection,
) -> PlanningSemanticMemberAuthority:
    scope = _scope()
    descriptor = _write(
        connection,
        producing_scope=scope,
        semantic_kind=PlanningSemanticKind.GAME_DATE_INDEX,
        partition={"season": "2025-26", "season_type": "Regular Season"},
        values=[{"game_date": "2025-10-21", "game_id": "0022500001"}],
        typed_zero_reason_code=None,
    )
    return _authority(scope=scope, descriptor=descriptor)


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign_partition",
        "orphan_value",
        "ordinal_gap",
        "noncanonical_json",
        "content_digest",
        "partition_scope",
    ],
)
def test_reader_fails_closed_on_registry_or_value_drift(
    connection: duckdb.DuckDBPyConnection,
    mutation: str,
) -> None:
    authority = _one_game_registry(connection)
    descriptor = authority.descriptor_identity_sha256
    if mutation == "foreign_partition":
        row = list(
            connection.execute(
                f"SELECT * FROM {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE}"
            ).fetchone()
        )
        row[0] = "f" * 64
        connection.execute(
            f"INSERT INTO {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE} "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
    elif mutation == "orphan_value":
        connection.execute(
            f"INSERT INTO {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE} VALUES (?, ?, ?)",
            ["f" * 64, 0, '{"game_date":"2025-10-21","game_id":"0022500002"}'],
        )
    elif mutation == "ordinal_gap":
        connection.execute(f"UPDATE {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE} SET ordinal=2")
    elif mutation == "noncanonical_json":
        connection.execute(
            f"UPDATE {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE} SET value_json=?",
            [json.dumps({"game_date": "2025-10-21", "game_id": "0022500001"}, indent=2)],
        )
    elif mutation == "content_digest":
        connection.execute(
            f"UPDATE {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE} SET semantic_content_sha256=?",
            ["f" * 64],
        )
    else:
        connection.execute(
            f"UPDATE {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE} "
            "SET producing_scope_identity_sha256=?",
            ["f" * 64],
        )

    with pytest.raises(SuccessorPlanningProgramCompilerError):
        read_successor_planning_semantic_registry(connection, authorities=(authority,))
    assert descriptor == authority.member.semantic.identity_sha256


def test_reader_rejects_missing_authority_and_exact_table_schema_drift(tmp_path: Path) -> None:
    connection = duckdb.connect(str(tmp_path / "bad.duckdb"))
    try:
        connection.execute(
            f"CREATE TABLE {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE} (x VARCHAR)"
        )
        connection.execute(f"CREATE TABLE {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE} (x VARCHAR)")
        with pytest.raises(SuccessorPlanningProgramCompilerError, match="exact schema v2"):
            install_successor_planning_semantic_schema(connection)
    finally:
        connection.close()


def test_complete_database_schema_digest_is_copy_stable_and_binds_opaque_tables(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.duckdb"
    connection = duckdb.connect(str(source_path))
    try:
        install_successor_planning_semantic_schema(connection)
        connection.execute(
            "CREATE TABLE _opaque_runtime_journal (call_id VARCHAR PRIMARY KEY, done BOOLEAN)"
        )
        expected = successor_planning_database_schema_sha256(connection)
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    copy_path = tmp_path / "descriptor-safe-copy.duckdb"
    copy_path.write_bytes(source_path.read_bytes())
    copied = duckdb.connect(str(copy_path), read_only=True)
    try:
        assert successor_planning_database_schema_sha256(copied) == expected
    finally:
        copied.close()

    changed = duckdb.connect(str(source_path))
    try:
        changed.execute("ALTER TABLE _opaque_runtime_journal ADD COLUMN ordinal UBIGINT")
        assert successor_planning_database_schema_sha256(changed) != expected
    finally:
        changed.close()


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE VIEW unsealed_view AS SELECT 1 AS value",
        "ATTACH ':memory:' AS foreign_database",
    ],
)
def test_complete_database_schema_digest_rejects_external_authority(
    connection: duckdb.DuckDBPyConnection,
    statement: str,
) -> None:
    connection.execute(statement)
    with pytest.raises(SuccessorPlanningProgramCompilerError):
        successor_planning_database_schema_sha256(connection)


def test_authority_rejects_member_scope_mismatch(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    authority = _one_game_registry(connection)
    with pytest.raises(SuccessorPlanningProgramCompilerError, match="producing scope"):
        PlanningSemanticMemberAuthority(
            member=authority.member,
            producing_scope=_scope("common_team_years"),
            logical_call_receipt_sha256="3" * 64,
            provider_authority_sha256="4" * 64,
        )


def test_authority_rejects_forged_current_route_provider(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    authority = _one_game_registry(connection)
    with pytest.raises(SuccessorPlanningProgramCompilerError, match="provider authority"):
        PlanningSemanticMemberAuthority(
            member=authority.member,
            producing_scope=authority.producing_scope,
            logical_call_receipt_sha256="3" * 64,
            provider_authority_sha256="f" * 64,
        )


def test_value_insert_failure_rolls_back_partition_and_values(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    class _FailingConnection:
        def __init__(self, delegate: duckdb.DuckDBPyConnection) -> None:
            self.delegate = delegate

        def execute(
            self,
            query: str,
            parameters: object = None,
        ) -> duckdb.DuckDBPyConnection:
            if (
                f"INSERT INTO {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE}" in query
                and parameters is not None
            ):
                raise RuntimeError("injected value insert failure")
            if parameters is None:
                return self.delegate.execute(query)
            return self.delegate.execute(query, parameters)

    failing = _FailingConnection(connection)
    with (
        pytest.raises(SuccessorPlanningProgramCompilerError, match="append"),
        successor_planning_semantic_write_transaction(failing) as transaction,  # type: ignore[arg-type]
    ):
        write_successor_planning_semantic_partition(
            transaction,
            producing_scope=_scope(),
            semantic_kind=PlanningSemanticKind.GAME_DATE_INDEX,
            partition={"season": "2025-26", "season_type": "Regular Season"},
            values=[{"game_date": "2025-10-21", "game_id": "0022500001"}],
            typed_zero_reason_code=None,
        )

    assert connection.execute(
        f"SELECT count(*) FROM {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE}"
    ).fetchone() == (0,)
    assert connection.execute(
        f"SELECT count(*) FROM {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE}"
    ).fetchone() == (0,)


def _request(
    mode: SuccessorUpdateMode,
    *,
    cutoff_utc: str = "2026-08-12T00:00:00Z",
    as_of_utc: str = "2026-08-13T00:00:00Z",
) -> SuccessorPlanningRequest:
    return build_successor_planning_request(
        baseline_identity_sha256="a" * 64,
        mode=mode,
        source_sha="b" * 40,
        cutoff_utc=cutoff_utc,
        as_of_utc=as_of_utc,
        workflow_run_id=123,
        workflow_run_attempt=1,
    )


def _planning_scope(
    request: SuccessorPlanningRequest,
    endpoint_name: str,
    *,
    season: str | None = None,
    season_type: str | None = None,
) -> RequestedRouteScope:
    for scope in request.requested_planning_scopes:
        if scope.endpoint_name != endpoint_name:
            continue
        if season is not None and scope.parameters.get("season") != season:
            continue
        if season_type is not None and scope.parameters.get("season_type") != season_type:
            continue
        return scope
    raise AssertionError((endpoint_name, season, season_type))


def _semantic_registry_for_mode(
    connection: duckdb.DuckDBPyConnection,
    mode: SuccessorUpdateMode,
    *,
    game_values: list[dict[str, object]] | None = None,
    request: SuccessorPlanningRequest | None = None,
) -> tuple[
    SuccessorPlanningRequest,
    tuple[PlanningSemanticMemberAuthority, ...],
    tuple[PlanningSemanticPartitionValues, ...],
]:
    request = _request(mode) if request is None else request
    assert isinstance(request, SuccessorPlanningRequest)
    authorities: list[PlanningSemanticMemberAuthority] = []
    seasons = sorted(
        {
            str(scope.parameters["season"])
            for scope in request.requested_planning_scopes
            if scope.endpoint_name == "league_game_log"
        }
    )
    season_types_by_season = {
        season: sorted(
            {
                str(scope.parameters["season_type"])
                for scope in request.requested_planning_scopes
                if scope.endpoint_name == "league_game_log" and scope.parameters["season"] == season
            }
        )
        for season in seasons
    }
    with successor_planning_semantic_write_transaction(connection) as transaction:
        for season in seasons:
            for pair_index, season_type in enumerate(season_types_by_season[season]):
                league = _planning_scope(
                    request,
                    "league_game_log",
                    season=season,
                    season_type=season_type,
                )
                values = game_values
                if values is None:
                    year = int(season[:4])
                    values = [
                        {
                            "game_date": f"{year + 1:04d}-08-12",
                            "game_id": f"002{year % 100:02d}{pair_index:05d}",
                        }
                    ]
                game_descriptor = write_successor_planning_semantic_partition(
                    transaction,
                    producing_scope=league,
                    semantic_kind=PlanningSemanticKind.GAME_DATE_INDEX,
                    partition={"season": season, "season_type": season_type},
                    values=values,
                    typed_zero_reason_code=(None if values else "provider_success_empty"),
                )
                authorities.append(_authority(scope=league, descriptor=game_descriptor))

                logs = _planning_scope(
                    request,
                    "player_game_logs",
                    season=season,
                    season_type=season_type,
                )
                affiliation = write_successor_planning_semantic_partition(
                    transaction,
                    producing_scope=logs,
                    semantic_kind=PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION,
                    partition={"season": season, "season_type": season_type},
                    values=[{"player_id": 2544, "team_id": 1610612747}],
                    typed_zero_reason_code=None,
                )
                authorities.append(_authority(scope=logs, descriptor=affiliation))

            players = _planning_scope(request, "common_all_players", season=season)
            player_descriptor = write_successor_planning_semantic_partition(
                transaction,
                producing_scope=players,
                semantic_kind=PlanningSemanticKind.SEASON_PLAYER_UNIVERSE,
                partition={
                    "season": season,
                    "current_only": mode is SuccessorUpdateMode.DAILY,
                },
                values=[{"player_id": 2544}],
                typed_zero_reason_code=None,
            )
            authorities.append(_authority(scope=players, descriptor=player_descriptor))

        teams = _planning_scope(request, "common_team_years")
        for season in seasons:
            team_descriptor = write_successor_planning_semantic_partition(
                transaction,
                producing_scope=teams,
                semantic_kind=PlanningSemanticKind.SEASON_TEAM_UNIVERSE,
                partition={"season": season},
                values=[{"team_id": 1610612747}],
                typed_zero_reason_code=None,
            )
            authorities.append(_authority(scope=teams, descriptor=team_descriptor))
        current_descriptor = write_successor_planning_semantic_partition(
            transaction,
            producing_scope=teams,
            semantic_kind=PlanningSemanticKind.CURRENT_TEAM_UNIVERSE,
            partition={"as_of_utc": request.as_of_utc},
            values=[{"team_id": 1610612747}],
            typed_zero_reason_code=None,
        )
        authorities.append(_authority(scope=teams, descriptor=current_descriptor))
        auxiliary = write_successor_planning_semantic_partition(
            transaction,
            producing_scope=teams,
            semantic_kind=PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA,
            partition={},
            values=[],
            typed_zero_reason_code="no_derived_semantic_values",
        )
        authorities.append(_authority(scope=teams, descriptor=auxiliary))

        scoreboard = _planning_scope(request, "live_score_board")
        live_descriptor = write_successor_planning_semantic_partition(
            transaction,
            producing_scope=scoreboard,
            semantic_kind=PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
            partition={"as_of_utc": request.as_of_utc},
            values=[{"game_id": "0022500001"}],
            typed_zero_reason_code=None,
        )
        authorities.append(_authority(scope=scoreboard, descriptor=live_descriptor))

    ordered = tuple(sorted(authorities, key=lambda item: item.descriptor_identity_sha256))
    registry = read_successor_planning_semantic_registry(
        connection,
        authorities=ordered,
    )
    return request, ordered, registry


def test_typed_zero_game_index_still_derives_cume_foundation_calls(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    request, _authorities, registry = _semantic_registry_for_mode(
        connection,
        SuccessorUpdateMode.DAILY,
        game_values=[],
    )

    program = compile_successor_planning_program(
        request=request,
        semantic_registry=registry,
        phase=PlanningDispatchPhase.PLANNING_WAVE_1,
    )

    assert {dispatch.endpoint_name for dispatch in program.sealed_dispatches} == {
        "cume_stats_player_games",
        "cume_stats_team_games",
    }
    assert all(
        len(dispatch.dependency_identity_sha256s) == 2 for dispatch in program.sealed_dispatches
    )


def _add_foundation_semantics(
    connection: duckdb.DuckDBPyConnection,
    authorities: tuple[PlanningSemanticMemberAuthority, ...],
    wave_1: CompiledSuccessorPlanningProgram,
) -> tuple[PlanningSemanticMemberAuthority, ...]:
    additions: list[PlanningSemanticMemberAuthority] = []
    with successor_planning_semantic_write_transaction(connection) as transaction:
        for scope in wave_1.requested_route_scopes:
            if scope.endpoint_name == "cume_stats_player_games":
                kind = PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS
                partition = {
                    "player_id": scope.parameters["player_id"],
                    "season": scope.parameters["season"],
                    "season_type": scope.parameters["season_type"],
                }
            else:
                assert scope.endpoint_name == "cume_stats_team_games"
                kind = PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS
                partition = {
                    "team_id": scope.parameters["team_id"],
                    "season": scope.parameters["season"],
                    "season_type": scope.parameters["season_type"],
                }
            descriptor = write_successor_planning_semantic_partition(
                transaction,
                producing_scope=scope,
                semantic_kind=kind,
                partition=partition,
                values=[{"game_id": "0022500001"}],
                typed_zero_reason_code=None,
            )
            route = staging_route_contract_bundle().by_route_id[scope.route_id]
            additions.append(
                _authority(
                    scope=scope,
                    descriptor=descriptor,
                    wave_index=1,
                    logical_call_receipt_sha256="5" * 64,
                    provider_authority_sha256=route.provider_authority_sha256,
                )
            )
    return tuple(
        sorted(
            (*authorities, *additions),
            key=lambda item: item.descriptor_identity_sha256,
        )
    )


@pytest.mark.parametrize("mode", [SuccessorUpdateMode.DAILY, SuccessorUpdateMode.MONTHLY])
def test_compiles_full_route_surface_with_plural_dependency_and_mirror_authority(
    connection: duckdb.DuckDBPyConnection,
    mode: SuccessorUpdateMode,
) -> None:
    request, authorities, registry = _semantic_registry_for_mode(connection, mode)
    wave_1 = compile_successor_planning_program(
        request=request,
        semantic_registry=registry,
        phase=PlanningDispatchPhase.PLANNING_WAVE_1,
    )
    assert {dispatch.endpoint_name for dispatch in wave_1.sealed_dispatches} == {
        "cume_stats_player_games",
        "cume_stats_team_games",
    }
    assert all(
        len(dispatch.dependency_identity_sha256s) == 2 for dispatch in wave_1.sealed_dispatches
    )

    authorities = _add_foundation_semantics(connection, authorities, wave_1)
    registry = read_successor_planning_semantic_registry(
        connection,
        authorities=authorities,
    )

    update = compile_successor_planning_program(
        request=request,
        semantic_registry=registry,
        phase=PlanningDispatchPhase.UPDATE,
    )
    endpoints = {dispatch.endpoint_name for dispatch in update.sealed_dispatches}
    assert {
        "league_game_log",
        "player_game_logs",
        "common_all_players",
        "common_team_years",
        "live_score_board",
        "live_odds",
        "live_play_by_play",
        "live_box_score",
        "video_details",
        "video_details_asset",
        "cume_stats_player",
        "cume_stats_team",
    } <= endpoints
    assert (
        sum(
            len(dispatch.staging_route_ids)
            for dispatch in update.sealed_dispatches
            if dispatch.endpoint_name == "live_box_score"
        )
        == 7
    )
    assert all(dispatch.dependency_identity_sha256s for dispatch in update.sealed_dispatches)

    members_by_scope: dict[str, set[str]] = {}
    for authority in authorities:
        members_by_scope.setdefault(authority.producing_scope.identity_sha256, set()).add(
            authority.member_identity_sha256
        )
    for planning_scope in request.requested_planning_scopes:
        mirror = next(
            dispatch
            for dispatch in update.sealed_dispatches
            if planning_scope.identity_sha256 in dispatch.requested_scope_identity_sha256s
        )
        expected = tuple(
            sorted(
                member
                for scope_id in mirror.requested_scope_identity_sha256s
                for member in members_by_scope[scope_id]
            )
        )
        assert mirror.dependency_identity_sha256s == expected

    for wave_1_scope in wave_1.requested_route_scopes:
        mirror = next(
            dispatch
            for dispatch in update.sealed_dispatches
            if wave_1_scope.identity_sha256 in dispatch.requested_scope_identity_sha256s
        )
        expected = tuple(sorted(members_by_scope[wave_1_scope.identity_sha256]))
        assert mirror.dependency_identity_sha256s == expected

    update_route_ids = {
        route_id for dispatch in update.sealed_dispatches for route_id in dispatch.staging_route_ids
    }
    expected_count = 370 if mode is SuccessorUpdateMode.DAILY else 403
    assert len(update_route_ids) == expected_count

    if mode is SuccessorUpdateMode.DAILY:
        assert not any(
            dispatch.endpoint_name == "static_players" for dispatch in update.sealed_dispatches
        )
    else:
        assert any(
            dispatch.endpoint_name == "static_players" for dispatch in update.sealed_dispatches
        )


def test_historical_game_and_date_routes_use_partition_local_support_authority(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    request = _request(
        SuccessorUpdateMode.MONTHLY,
        cutoff_utc="2017-08-12T00:00:00Z",
        as_of_utc="2017-08-13T00:00:00Z",
    )
    request, authorities, registry = _semantic_registry_for_mode(
        connection,
        SuccessorUpdateMode.MONTHLY,
        request=request,
    )
    wave_1 = compile_successor_planning_program(
        request=request,
        semantic_registry=registry,
        phase=PlanningDispatchPhase.PLANNING_WAVE_1,
    )
    authorities = _add_foundation_semantics(connection, authorities, wave_1)
    registry = read_successor_planning_semantic_registry(
        connection,
        authorities=authorities,
    )

    update = compile_successor_planning_program(
        request=request,
        semantic_registry=registry,
        phase=PlanningDispatchPhase.UPDATE,
    )

    assert not any(
        dispatch.endpoint_name == "box_score_defensive" for dispatch in update.sealed_dispatches
    )
    authority_route_ids = {
        f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
        for entries in executable_entries_by_pattern().values()
        for entry in entries
    }
    emitted = {
        route_id for dispatch in update.sealed_dispatches for route_id in dispatch.staging_route_ids
    }
    assert "box_score_defensive:stg_box_score_defensive:0" in authority_route_ids
    assert "box_score_defensive:stg_box_score_defensive:0" not in emitted


def test_update_rejects_foundation_descriptor_partition_relabel(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    request, authorities, registry = _semantic_registry_for_mode(
        connection,
        SuccessorUpdateMode.DAILY,
    )
    wave_1 = compile_successor_planning_program(
        request=request,
        semantic_registry=registry,
        phase=PlanningDispatchPhase.PLANNING_WAVE_1,
    )
    authorities = _add_foundation_semantics(connection, authorities, wave_1)
    original = next(
        authority
        for authority in authorities
        if authority.member.wave_index == 1
        and authority.producing_scope.endpoint_name == "cume_stats_player_games"
    )
    connection.execute(
        f"DELETE FROM {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE} "
        "WHERE descriptor_identity_sha256=?",
        [original.descriptor_identity_sha256],
    )
    connection.execute(
        f"DELETE FROM {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE} "
        "WHERE descriptor_identity_sha256=?",
        [original.descriptor_identity_sha256],
    )
    scope = original.producing_scope
    forged = _write(
        connection,
        producing_scope=scope,
        semantic_kind=PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
        partition={
            "player_id": 999,
            "season": scope.parameters["season"],
            "season_type": scope.parameters["season_type"],
        },
        values=[{"game_id": "0022500001"}],
        typed_zero_reason_code=None,
    )
    forged_authority = _authority(
        scope=scope,
        descriptor=forged,
        wave_index=1,
        logical_call_receipt_sha256=original.logical_call_receipt_sha256,
        provider_authority_sha256=original.provider_authority_sha256,
    )
    authorities = tuple(
        sorted(
            (forged_authority if authority is original else authority for authority in authorities),
            key=lambda authority: authority.descriptor_identity_sha256,
        )
    )
    registry = read_successor_planning_semantic_registry(
        connection,
        authorities=authorities,
    )

    with pytest.raises(
        SuccessorPlanningProgramCompilerError,
        match="foundation topology",
    ):
        compile_successor_planning_program(
            request=request,
            semantic_registry=registry,
            phase=PlanningDispatchPhase.UPDATE,
        )
