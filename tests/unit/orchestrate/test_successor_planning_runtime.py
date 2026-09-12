from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, cast

import polars as pl
import pytest

import nbadb.orchestrate.successor_planning_runtime as runtime_module
from nbadb.contracts.field_fate_structure import compile_field_fate_structure
from nbadb.contracts.logical_provider_parameter_binding import (
    compile_logical_provider_parameter_binding,
)
from nbadb.contracts.raw_request_authority import canonical_semantic_parameters
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.config import NbaDbSettings
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_runtime_contracts,
)
from nbadb.extract.base import BaseExtractor
from nbadb.extract.bronze import (
    PARSER_INPUT_REPRESENTATION,
    BronzeLimits,
    LogicalCallReceiptBinding,
    canonical_parameters_sha256,
)
from nbadb.extract.nba_api_adapter import rederive_raw_authority_result_sets
from nbadb.extract.raw_request_capture import (
    RawProviderCallContextV2,
    RawRequestCaptureContextV2,
    wrap_raw_request_capture_contract,
)
from nbadb.extract.registry import EndpointRegistry
from nbadb.orchestrate.body_blob_store import BodyBlobStore
from nbadb.orchestrate.declared_bodyless_packet_store import DeclaredBodylessPacketStore
from nbadb.orchestrate.extractor_runner import PatternExtractionResult
from nbadb.orchestrate.public_value_authority_store import PublicValueAuthorityStore
from nbadb.orchestrate.raw_request_store import RawRequestAuthorityStore
from nbadb.orchestrate.successor_planner import deterministic_planning_generation_id
from nbadb.orchestrate.successor_planning_driver import (
    PlanningExactCallRuntimeRequest,
    PlanningWaveSealRuntimeRequest,
    RequestDrivenSuccessorPlanningDriver,
)
from nbadb.orchestrate.successor_planning_request_builder import (
    build_successor_planning_request,
)
from nbadb.orchestrate.successor_planning_runtime import (
    ExactPlanningRuntimeConfig,
    ExactPlanningRuntimeError,
    ExtractorPlanningExactCallRuntime,
    PlanningW2AuthorityResourcesV1,
    _normalize_cume_game_ids,
    _normalize_game_date_index,
    _normalize_live_game_ids,
    _normalize_season_players,
    _normalize_teams_for_year,
)
from nbadb.orchestrate.successor_planning_store import (
    CommittedPlanningCall,
    CommittedPlanningMember,
    PlanningArtifactSource,
    PlanningDatabaseSource,
    PlanningGenerationPhase,
    PlanningWaveAdmission,
)
from nbadb.orchestrate.successor_update_contract import SuccessorUpdateMode
from nbadb.orchestrate.w2_operation_store import W2OperationStore
from nbadb.orchestrate.w2_source_call_preparation import W2SourceCallPreparationRuntime
from tests.unit.orchestrate.test_successor_planning_driver import (
    _BudgetFactory,
    _executor,
    _SemanticRuntime,
)

if TYPE_CHECKING:
    from pathlib import Path


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _limits() -> BronzeLimits:
    return BronzeLimits(
        max_response_bytes=100_000,
        max_generation_stored_bytes=2_000_000,
        minimum_free_bytes=1,
        max_receipt_bytes=100_000,
        max_receipt_count=1_000,
        max_checkpoint_bytes=1_000_000,
        minimum_deadline_headroom_seconds=10.0,
    )


def _settings(tmp_path: Path) -> NbaDbSettings:
    return NbaDbSettings(
        data_dir=tmp_path / "public",
        duckdb_path=tmp_path / "public" / "nba.duckdb",
        sqlite_path=tmp_path / "public" / "nba.sqlite",
        log_dir=tmp_path / "logs",
    )


class _PlanningLeagueGameLogExtractor(BaseExtractor):
    endpoint_name = "league_game_log"
    category = "test"

    async def extract(self, **_params: Any) -> pl.DataFrame:
        return pl.DataFrame()


class _ReplacementPlanningLeagueGameLogExtractor(BaseExtractor):
    endpoint_name = "league_game_log"
    category = "test"

    async def extract(self, **_params: Any) -> pl.DataFrame:
        return pl.DataFrame()


def _wire_parameters(endpoint_id: str, parameters: dict[str, object]) -> dict[str, object]:
    query_names = dict(pinned_runtime_contracts()[endpoint_id].parameter_query_names)
    semantic = dict(parameters)
    if "season_type" in semantic:
        semantic["season_type_all_star"] = semantic.pop("season_type")
    return {query_names[name]: value for name, value in semantic.items()}


def _w2_resources(tmp_path: Path) -> PlanningW2AuthorityResourcesV1:
    provider_authority_sha256 = staging_route_contract_bundle().provider_authority_sha256
    runtimes: dict[str, W2SourceCallPreparationRuntime] = {}

    def raw_request_context_factory(
        scope: Any,
        endpoint_name: str,
        parameters: dict[str, object],
    ) -> RawRequestCaptureContextV2:
        assert endpoint_name == "league_game_log"
        endpoint_id = "LeagueGameLog"
        contract = pinned_runtime_contracts()[endpoint_id]
        semantic_parameters = dict(parameters)
        semantic_parameters["season_type_all_star"] = semantic_parameters.pop("season_type")
        _safe_json, _safe_sha256, provider_request_sha256 = canonical_semantic_parameters(
            "stats",
            endpoint_id,
            semantic_parameters,
        )
        scope_sha256 = canonical_parameters_sha256(parameters)
        return RawRequestCaptureContextV2(
            provider_authority_sha256=provider_authority_sha256,
            source_sha=scope.semantic_source_sha,
            run_id=scope.workflow_run_id,
            run_attempt=scope.workflow_run_attempt,
            chain_id=scope.chain_id,
            lane_id=scope.lane_id,
            provider_calls=(
                RawProviderCallContextV2(
                    request_ordinal=0,
                    semantic_request_sha256=_digest(
                        f"semantic:{scope.identity_sha256}:{provider_request_sha256}"
                    ),
                    logical_invocation_sha256=_digest(
                        f"logical:{scope.identity_sha256}:{scope_sha256}"
                    ),
                    provider_call_role="primary",
                    provider_call_ordinal=0,
                    source_family="stats",
                    endpoint_id=endpoint_id,
                    provider_request_sha256=provider_request_sha256,
                    endpoint_contract_sha256=endpoint_contract_sha256(contract),
                    scope_sha256=scope_sha256,
                ),
            ),
        )

    def preparation_runtime_factory(scope: Any) -> W2SourceCallPreparationRuntime:
        cached = runtimes.get(scope.identity_sha256)
        if cached is not None:
            return cached
        base = tmp_path / "w2" / scope.identity_sha256
        body = base / "body"
        bodyless = base / "bodyless"
        for path in (tmp_path / "w2", base, body, bodyless):
            path.mkdir(mode=0o700, exist_ok=True)
            path.chmod(0o700)
        identity = {
            "source_sha": scope.semantic_source_sha,
            "run_id": scope.workflow_run_id,
            "run_attempt": scope.workflow_run_attempt,
            "chain_id": scope.chain_id,
            "lane_id": scope.lane_id,
        }
        runtime = W2SourceCallPreparationRuntime(
            body_blob_store=BodyBlobStore(body.resolve(), **identity),
            declared_bodyless_packet_store=DeclaredBodylessPacketStore(
                bodyless.resolve(),
                **identity,
            ),
            field_fate=compile_field_fate_structure(),
        )
        runtimes[scope.identity_sha256] = runtime
        return runtime

    def logical_parameter_binding_factory(
        _scope: Any,
        request: PlanningExactCallRuntimeRequest,
        context: RawRequestCaptureContextV2,
    ) -> tuple[Any, str]:
        semantic_parameters = dict(request.dispatch.parameters)
        semantic_parameters["season_type_all_star"] = semantic_parameters.pop("season_type")
        binding = compile_logical_provider_parameter_binding(
            raw_request_context=context,
            logical_endpoint_name=request.dispatch.endpoint_name,
            logical_parameters=request.dispatch.parameters,
            result_route_ids=tuple(sorted(request.dispatch.staging_route_ids)),
            provider_semantic_parameters=(semantic_parameters,),
        )
        return binding, binding.binding_sha256

    return PlanningW2AuthorityResourcesV1(
        raw_request_context_factory=raw_request_context_factory,
        w2_preparation_runtime_factory=preparation_runtime_factory,
        raw_authority_store_factory=RawRequestAuthorityStore,
        public_value_store_factory=PublicValueAuthorityStore,
        w2_operation_store_factory=W2OperationStore,
        live_plan_binding_factory=lambda _scope, _request, _snapshot, _binding: (),
        logical_provider_parameter_binding_factory=(logical_parameter_binding_factory),
    )


def _config(tmp_path: Path) -> ExactPlanningRuntimeConfig:
    public = tmp_path / "public"
    capture = tmp_path / "capture"
    store = tmp_path / "store"
    for path, mode in ((public, 0o755), (capture, 0o700), (store, 0o700)):
        path.mkdir(mode=mode)
        path.chmod(mode)
    planning_registry = EndpointRegistry()
    planning_registry.register(_PlanningLeagueGameLogExtractor)
    return ExactPlanningRuntimeConfig(
        settings=_settings(tmp_path),
        registry=planning_registry,
        registry_authority=planning_registry.capture_authority(("league_game_log",)),
        capture_base=capture.resolve(),
        planning_store_root=store.resolve(),
        public_roots=(public.resolve(),),
        capture_limits=_limits(),
        estimated_checkpoint_bytes=50_000,
        # The exact Raw/W2 authority relations now make the minimal planning
        # database about 12.4 MB on DuckDB 1.5.5.  Keep the test cap bounded
        # while leaving enough headroom for its mandatory checkpoint commit.
        planning_driver_database_max_bytes=16_000_000,
        monotonic_deadline_seconds=200.0,
        minimum_deadline_headroom_seconds=10.0,
        before_planning_effects_authority=lambda: None,
        before_provider_authority=lambda: None,
        w2_authority_resources=_w2_resources(tmp_path),
        monotonic_clock=lambda: 100.0,
    )


def _request():
    return build_successor_planning_request(
        baseline_identity_sha256=_digest("baseline"),
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        workflow_run_id=731,
        workflow_run_attempt=4,
    )


def _league_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "season_id": ["22025"],
            "team_id": [1610612747],
            "team_abbreviation": ["LAL"],
            "team_name": ["Lakers"],
            "game_id": ["0022500001"],
            "game_date": ["2026-08-12"],
            "matchup": ["LAL vs. BOS"],
            "wl": ["W"],
            "w": pl.Series([None], dtype=pl.Int64),
            "l": pl.Series([None], dtype=pl.Int64),
            "w_pct": pl.Series([None], dtype=pl.Float64),
            "min": [240.0],
            "fgm": [40.0],
            "fga": [85.0],
            "fg_pct": [0.471],
            "fg3m": [12.0],
            "fg3a": [35.0],
            "fg3_pct": [0.343],
            "ftm": [20.0],
            "fta": [25.0],
            "ft_pct": [0.8],
            "oreb": [10.0],
            "dreb": [35.0],
            "reb": [45.0],
            "ast": [25.0],
            "stl": [8.0],
            "blk": [5.0],
            "tov": [12.0],
            "pf": [18.0],
            "pts": [112.0],
            "plus_minus": [8.0],
            "video_available": [1],
        }
    )


def test_game_date_normalizer_is_partition_local_and_canonical() -> None:
    frame = pl.DataFrame(
        {
            "game_id": ["0022500002", "0022500001", "0022500001"],
            "game_date": ["2025-10-22", "2025-10-21", "2025-10-21"],
        }
    )

    assert _normalize_game_date_index(frame) == (
        {"game_date": "2025-10-21", "game_id": "0022500001"},
        {"game_date": "2025-10-22", "game_id": "0022500002"},
    )


def test_game_date_normalizer_rejects_conflicting_dates() -> None:
    frame = pl.DataFrame(
        {
            "game_id": ["0022500001", "0022500001"],
            "game_date": ["2025-10-21", "2025-10-22"],
        }
    )

    with pytest.raises(ExactPlanningRuntimeError, match="multiple game dates"):
        _normalize_game_date_index(frame)


def test_live_normalizer_uses_only_fixed_status_two() -> None:
    snapshot = datetime(2026, 8, 13, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "snapshot_at": [snapshot, snapshot, snapshot],
            "snapshot_date": [date(2026, 8, 13)] * 3,
            "source_endpoint": ["live_score_board"] * 3,
            "game_id": ["0022500001", "0022500002", "0022500003"],
            "game_status": [1, 2, 3],
        }
    )

    assert _normalize_live_game_ids(
        frame,
        as_of_utc="2026-08-13T00:00:00Z",
    ) == ({"game_id": "0022500002"},)


def test_live_normalizer_rejects_missing_status_instead_of_widening() -> None:
    snapshot = datetime(2026, 8, 13, tzinfo=UTC)
    frame = pl.DataFrame(
        {
            "snapshot_at": [snapshot],
            "snapshot_date": [date(2026, 8, 13)],
            "source_endpoint": ["live_score_board"],
            "game_id": ["0022500001"],
            "game_status": [None],
        }
    )

    with pytest.raises(ExactPlanningRuntimeError, match="game_status"):
        _normalize_live_game_ids(frame, as_of_utc="2026-08-13T00:00:00Z")


def test_cume_normalizer_preserves_order_and_enforces_subset() -> None:
    frame = pl.DataFrame({"game_id": ["0022500002", "0022500001"]})

    assert _normalize_cume_game_ids(
        frame,
        game_date_ids=frozenset({"0022500001", "0022500002"}),
    ) == ({"game_id": "0022500002"}, {"game_id": "0022500001"})

    with pytest.raises(ExactPlanningRuntimeError, match="outside"):
        _normalize_cume_game_ids(
            frame,
            game_date_ids=frozenset({"0022500001"}),
        )


def test_team_and_player_windows_are_inclusive_without_wall_clock() -> None:
    teams = pl.DataFrame(
        {
            "league_id": ["00", "00", "10"],
            "team_id": [1, 2, 3],
            "min_year": [2000, 2026, 1990],
            "max_year": [2025, 2030, 2030],
        }
    )
    players = pl.DataFrame(
        {
            "person_id": [7, 8],
            "roster_status": [0, 1],
            "from_year": [2025, 2026],
            "to_year": [2026, 2027],
        }
    )

    assert _normalize_teams_for_year(teams, season_year=2025) == ({"team_id": 1},)
    assert _normalize_season_players(
        players,
        season="2026-27",
        current_only=False,
    ) == ({"player_id": 7}, {"player_id": 8})
    assert _normalize_season_players(
        players,
        season="2026-27",
        current_only=True,
    ) == ({"player_id": 8},)


def test_runtime_config_rejects_casefold_and_same_inode_root_aliases(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    left_stat = left.stat()
    right_stat = right.stat()

    assert runtime_module._paths_overlap(  # noqa: SLF001
        type(left)("/Authority"),
        type(right)("/authority"),
        left_stat=left_stat,
        right_stat=right_stat,
    )
    assert runtime_module._paths_overlap(  # noqa: SLF001
        left,
        right,
        left_stat=left_stat,
        right_stat=left_stat,
    )


def test_runtime_config_rejects_root_substitution_after_construction(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    original = config.capture_base.with_name("capture-original")
    config.capture_base.rename(original)
    config.capture_base.mkdir(mode=0o700)
    config.capture_base.chmod(0o700)

    with pytest.raises(ExactPlanningRuntimeError, match="capture_base changed identity"):
        config.require_current_roots()


def test_runtime_config_rejects_registry_authority_mismatch(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    replacement_registry = EndpointRegistry()
    replacement_registry.register(_ReplacementPlanningLeagueGameLogExtractor)

    with pytest.raises(ExactPlanningRuntimeError, match="registry authority differs"):
        replace(config, registry=replacement_registry)


@pytest.mark.parametrize(
    "value",
    [True, 0.0, -1.0, float("inf"), float("nan"), "10"],
)
def test_runtime_config_rejects_invalid_deadline_headroom_authority(
    tmp_path: Path,
    value: object,
) -> None:
    with pytest.raises(ExactPlanningRuntimeError, match="admission authority is invalid"):
        replace(_config(tmp_path), minimum_deadline_headroom_seconds=value)


def test_runtime_config_rejects_deadline_headroom_authority_drift(
    tmp_path: Path,
) -> None:
    with pytest.raises(ExactPlanningRuntimeError, match="authorities differ"):
        replace(_config(tmp_path), minimum_deadline_headroom_seconds=9.0)


@pytest.mark.parametrize("value", [True, 0, -1, 1 << 63])
def test_runtime_config_requires_positive_signed63_driver_database_cap(
    tmp_path: Path,
    value: object,
) -> None:
    with pytest.raises(ExactPlanningRuntimeError, match="signed-63-bit"):
        replace(
            _config(tmp_path),
            planning_driver_database_max_bytes=value,  # type: ignore[arg-type]
        )


def test_runtime_config_requires_before_provider_authority(tmp_path: Path) -> None:
    with pytest.raises(ExactPlanningRuntimeError, match="before_provider_authority"):
        replace(_config(tmp_path), before_provider_authority=None)  # type: ignore[arg-type]


def test_runtime_config_requires_exact_explicit_w2_authority_resources(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    with pytest.raises(ExactPlanningRuntimeError, match="exact planning W2 authority"):
        replace(  # type: ignore[arg-type]
            config,
            w2_authority_resources=None,
        )

    with pytest.raises(ExactPlanningRuntimeError, match="must be callable"):
        replace(
            config.w2_authority_resources,
            live_plan_binding_factory=None,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("clock_value", [True, 0.0, float("inf"), float("nan")])
def test_runtime_deadline_guard_rejects_invalid_clock_reading(
    tmp_path: Path,
    clock_value: object,
) -> None:
    config = replace(_config(tmp_path), monotonic_clock=lambda: clock_value)

    with pytest.raises(ExactPlanningRuntimeError, match="clock reading is invalid"):
        config.require_deadline_headroom(stage="test")


def test_planning_member_write_handles_short_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "member.json"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    real_write = os.write

    def short_write(fd: int, value: bytes | memoryview) -> int:
        return real_write(fd, value[:3])

    monkeypatch.setattr(runtime_module.os, "write", short_write)
    try:
        runtime_module._write_all(  # noqa: SLF001
            descriptor,
            b'{"complete":true}',
            label="test member",
        )
    finally:
        os.close(descriptor)

    assert target.read_bytes() == b'{"complete":true}'


def test_artifact_measurement_rejects_named_inode_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "artifact.bin"
    displaced = tmp_path / "artifact-original.bin"
    payload = b"a" * (1024 * 1024 + 1)
    target.write_bytes(payload)
    target.chmod(0o600)
    real_read = os.read
    swapped = False

    def swapping_read(fd: int, byte_count: int) -> bytes:
        nonlocal swapped
        chunk = real_read(fd, byte_count)
        if chunk and not swapped:
            target.rename(displaced)
            target.write_bytes(b"b" * len(payload))
            target.chmod(0o600)
            swapped = True
        return chunk

    monkeypatch.setattr(runtime_module.os, "read", swapping_read)
    with pytest.raises(ExactPlanningRuntimeError, match="changed while measured"):
        runtime_module._artifact_source(target)  # noqa: SLF001


def test_database_copy_rejects_zero_write_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.duckdb"
    destination = tmp_path / "destination.duckdb"
    source.write_bytes(b"database bytes")
    source.chmod(0o600)
    artifact = PlanningArtifactSource(
        path=source.resolve(),
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        byte_count=source.stat().st_size,
    )
    database = PlanningDatabaseSource(
        artifact=artifact,
        schema_sha256=_digest("schema"),
    )
    monkeypatch.setattr(runtime_module.os, "write", lambda _fd, _value: 0)

    with pytest.raises(ExactPlanningRuntimeError, match="copy write made no progress"):
        runtime_module._copy_database_source(database, destination)  # noqa: SLF001


def _install_fake_league_provider(
    monkeypatch: pytest.MonkeyPatch,
    dispatch: Any,
    *,
    provider_calls: list[str] | None = None,
) -> None:
    async def fake_run_pattern_result(
        runner: Any,
        _pattern: str,
        param_sets: list[dict[str, object]],
        _entries: list[object],
        **kwargs: object,
    ) -> PatternExtractionResult:
        if provider_calls is not None:
            provider_calls.append(dispatch.identity_sha256)
        parameters = param_sets[0]
        params_json = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
        runner._journal.record_start(  # noqa: SLF001
            dispatch.endpoint_name,
            params_json,
            require_receipt=True,
            require_w2_operation=True,
        )
        private_contract = runner._capture_contract_factory(  # noqa: SLF001
            dispatch.endpoint_name,
            parameters,
        )
        public_context = runner._raw_request_capture_context_factory(  # noqa: SLF001
            dispatch.endpoint_name,
            parameters,
        )
        endpoint_contract = pinned_runtime_contracts()["LeagueGameLog"]
        contract = wrap_raw_request_capture_contract(
            private_contract.for_endpoint_contract(endpoint_contract_sha256(endpoint_contract)),
            public_context,
        )
        frame = _league_frame()
        headers = list(endpoint_contract.result_sets[0].expected_columns)
        provider_frame = frame.with_columns(
            pl.lit(parameters["season"]).alias("season_year"),
            pl.lit(parameters["season_type"]).alias("season_type"),
            pl.lit("00").alias("league_id"),
        )
        provider_row = [provider_frame[column.lower()][0] for column in headers]
        parser_input = json.dumps(
            {
                "resultSets": [
                    {
                        "name": "LeagueGameLog",
                        "headers": headers,
                        "rowSet": [provider_row],
                    }
                ]
            },
            separators=(",", ":"),
        )
        derivations = rederive_raw_authority_result_sets(
            source_family="stats",
            endpoint_id="LeagueGameLog",
            parser_input=parser_input.encode(),
            provider_authority_sha256=contract.provider_authority_sha256,
            endpoint_contract_sha256_value=contract.endpoint_contract_sha256,
        )
        request_context = contract.begin_request()
        captured = contract.sink.store_parser_input(
            parser_input,
            representation=PARSER_INPUT_REPRESENTATION,
        )
        attempt = contract.sink.record_response_attempt(
            context=request_context,
            transport_kind="http_response",
            source_family="stats",
            endpoint_id="LeagueGameLog",
            endpoint_slug="leaguegamelog",
            parameters=_wire_parameters("LeagueGameLog", parameters),
            provider_authority_sha256=contract.provider_authority_sha256,
            contract_sha256=contract.endpoint_contract_sha256,
            status_code=200,
            captured=captured,
            outcome="success_nonempty",
            failure_class=None,
            root_exception_class=None,
            result_sets=tuple(item.result_set for item in derivations),
        )
        contract.record_receipt(request_context, attempt, successful=True)
        snapshot = contract.receipt_snapshot()
        root = contract.sink.record_logical_call(
            context=contract.context,
            logical_endpoint_id=dispatch.endpoint_name,
            logical_parameters=parameters,
            provider_authority_sha256=contract.provider_authority_sha256,
            response_receipt_sha256s=snapshot.receipt_sha256s,
            successful_response_ordinals=snapshot.successful_response_ordinals,
            result_route_ids=dispatch.staging_route_ids,
        )
        binding = LogicalCallReceiptBinding(
            logical_call_receipt_sha256=root,
            endpoint_name=dispatch.endpoint_name,
            logical_parameters_sha256=canonical_parameters_sha256(parameters),
            provider_authority_sha256=contract.provider_authority_sha256,
            result_route_ids=tuple(sorted(dispatch.staging_route_ids)),
        )
        callback = cast("Any", kwargs["persist_chunk_results"])
        admissions = callback(
            {"stg_league_game_log": provider_frame},
            source_results=[
                {
                    "frames": {"stg_league_game_log": provider_frame},
                    "source_endpoint_name": dispatch.endpoint_name,
                    "source_params_json": params_json,
                    "expected_staging_keys": ("stg_league_game_log",),
                    "receipt_binding": binding,
                    "raw_request_capture_snapshot": contract.sink.snapshot(),
                    "recorded_static_attempts": (),
                    "plan_live_snapshot_at": None,
                    "result_route_ids_by_staging_key": (
                        ("stg_league_game_log", dispatch.staging_route_ids[0]),
                    ),
                }
            ],
        )
        runner._journal.record_success(  # noqa: SLF001
            dispatch.endpoint_name,
            params_json,
            1,
            receipt_binding=binding,
            w2_admission=admissions[0],
        )
        return PatternExtractionResult(
            frames={"stg_league_game_log": provider_frame},
            eligible_calls=1,
            scheduled_calls=1,
            success_count=1,
            row_count=1,
        )

    monkeypatch.setattr(
        runtime_module.ExtractorRunner,
        "run_pattern_result",
        fake_run_pattern_result,
    )


def _league_exact_call(
    tmp_path: Path,
    runtime: ExtractorPlanningExactCallRuntime,
    *,
    planning_generation_id: str,
) -> PlanningExactCallRuntimeRequest:
    request = _request()
    driver = RequestDrivenSuccessorPlanningDriver(runtime)
    scope = next(
        item
        for item in request.requested_planning_scopes
        if item.endpoint_name == "league_game_log"
        and item.parameters["season_type"] == "Regular Season"
    )
    scopes = request.requested_planning_scopes
    admission = PlanningWaveAdmission(
        wave_index=0,
        parent_wave_identity_sha256=None,
        requested_route_scopes=scopes,
        sealed_dispatches=driver._build_wave_0_dispatches(scopes),  # noqa: SLF001
    )
    dispatch = next(
        item
        for item in admission.sealed_dispatches
        if item.requested_scope_identity_sha256s == (scope.identity_sha256,)
    )
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    work.chmod(0o700)
    return PlanningExactCallRuntimeRequest(
        request=request,
        planning_generation_id=planning_generation_id,
        wave_index=0,
        admission=admission,
        dispatch=dispatch,
        requested_route_scopes=(scope,),
        provider_authority_sha256=(staging_route_contract_bundle().provider_authority_sha256),
        cutoff_utc=request.cutoff_utc,
        as_of_utc=request.as_of_utc,
        workflow_run_id=request.workflow_run_id,
        workflow_run_attempt=request.workflow_run_attempt,
        input_planning_database=None,
        private_work_root=work.resolve(),
    )


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, str], ...]:
    snapshot: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot.append((relative, "directory", ""))
        else:
            snapshot.append((relative, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(snapshot)


async def test_oversized_input_database_fails_before_capture_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(_config(tmp_path), planning_driver_database_max_bytes=4)
    runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        runtime,
        planning_generation_id="successor-planning-v2-input-cap",
    )
    input_path = tmp_path / "input.duckdb"
    input_path.write_bytes(b"12345")
    input_path.chmod(0o600)
    input_database = PlanningDatabaseSource(
        artifact=PlanningArtifactSource(
            path=input_path.resolve(),
            sha256=hashlib.sha256(b"12345").hexdigest(),
            byte_count=5,
        ),
        schema_sha256=_digest("input-schema"),
    )
    exact = replace(exact, input_planning_database=input_database)
    provider_calls: list[str] = []
    _install_fake_league_provider(
        monkeypatch,
        exact.dispatch,
        provider_calls=provider_calls,
    )
    capture_before = _tree_snapshot(config.capture_base)
    work_before = _tree_snapshot(exact.private_work_root)

    with pytest.raises(ExactPlanningRuntimeError, match="input database exceeds"):
        await runtime.execute_planning_call(exact)

    assert provider_calls == []
    assert _tree_snapshot(config.capture_base) == capture_before
    assert _tree_snapshot(exact.private_work_root) == work_before


async def test_minimum_output_database_cap_fails_before_capture_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(_config(tmp_path), planning_driver_database_max_bytes=1)
    runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        runtime,
        planning_generation_id="successor-planning-v2-output-cap",
    )
    provider_calls: list[str] = []
    _install_fake_league_provider(
        monkeypatch,
        exact.dispatch,
        provider_calls=provider_calls,
    )
    capture_before = _tree_snapshot(config.capture_base)

    with pytest.raises((ExactPlanningRuntimeError, runtime_module.duckdb.IOException)) as exc_info:
        await runtime.execute_planning_call(exact)

    assert provider_calls == []
    assert _tree_snapshot(config.capture_base) == capture_before
    message = str(exc_info.value)
    database_paths = tuple(exact.private_work_root.glob("call-*/planning.duckdb"))
    if "before provider execution" in message:
        assert len(database_paths) == 1
        assert database_paths[0].stat().st_size > config.planning_driver_database_max_bytes
    else:
        assert "File too large" in message


async def test_reused_wave_rechecks_deadline_before_any_later_call_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = iter((100.0, 100.0, 191.0))
    config = replace(_config(tmp_path), monotonic_clock=lambda: next(readings))
    runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        runtime,
        planning_generation_id="successor-planning-v2-deadline-reuse",
    )
    provider_calls: list[str] = []
    _install_fake_league_provider(
        monkeypatch,
        exact.dispatch,
        provider_calls=provider_calls,
    )

    await runtime.execute_planning_call(exact)
    capture_before = _tree_snapshot(config.capture_base)
    work_before = _tree_snapshot(exact.private_work_root)

    with pytest.raises(ExactPlanningRuntimeError, match="call entry"):
        await runtime.execute_planning_call(exact)

    assert provider_calls == [exact.dispatch.identity_sha256]
    assert _tree_snapshot(config.capture_base) == capture_before
    assert _tree_snapshot(exact.private_work_root) == work_before


async def test_reused_session_rechecks_before_provider_authority_without_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_calls = 0

    def before_provider_authority() -> None:
        nonlocal authority_calls
        authority_calls += 1
        if authority_calls == 2:
            raise RuntimeError("capacity rejected")

    config = replace(
        _config(tmp_path),
        before_provider_authority=before_provider_authority,
    )
    runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        runtime,
        planning_generation_id="successor-planning-v2-provider-authority-reuse",
    )
    provider_calls: list[str] = []
    _install_fake_league_provider(
        monkeypatch,
        exact.dispatch,
        provider_calls=provider_calls,
    )

    await runtime.execute_planning_call(exact)
    capture_before = _tree_snapshot(config.capture_base)
    database_paths_before = set(exact.private_work_root.glob("call-*/planning.duckdb"))

    with pytest.raises(ExactPlanningRuntimeError, match="authority rejected"):
        await runtime.execute_planning_call(exact)

    assert authority_calls == 2
    assert provider_calls == [exact.dispatch.identity_sha256]
    assert _tree_snapshot(config.capture_base) == capture_before
    new_database_paths = (
        set(exact.private_work_root.glob("call-*/planning.duckdb")) - database_paths_before
    )
    assert len(new_database_paths) == 1
    connection = runtime_module.duckdb.connect(
        str(new_database_paths.pop()),
        read_only=True,
    )
    try:
        assert connection.execute(
            "SELECT count(*) FROM _successor_extraction_journal"
        ).fetchone() == (0,)
    finally:
        connection.close()


async def test_registry_drift_fails_before_provider_capture_or_journal_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        runtime,
        planning_generation_id="successor-planning-v2-registry-drift",
    )
    provider_calls: list[str] = []
    _install_fake_league_provider(
        monkeypatch,
        exact.dispatch,
        provider_calls=provider_calls,
    )
    capture_before = _tree_snapshot(config.capture_base)
    work_before = _tree_snapshot(exact.private_work_root)
    config.registry.register(_ReplacementPlanningLeagueGameLogExtractor)

    with pytest.raises(ExactPlanningRuntimeError, match="registry authority differs"):
        await runtime.execute_planning_call(exact)

    assert provider_calls == []
    assert _tree_snapshot(config.capture_base) == capture_before
    assert _tree_snapshot(exact.private_work_root) == work_before


async def test_deadline_is_rechecked_immediately_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = iter((100.0, 191.0))
    config = replace(_config(tmp_path), monotonic_clock=lambda: next(readings))
    runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        runtime,
        planning_generation_id="successor-planning-v2-deadline-provider",
    )
    provider_calls: list[str] = []
    _install_fake_league_provider(
        monkeypatch,
        exact.dispatch,
        provider_calls=provider_calls,
    )

    with pytest.raises(ExactPlanningRuntimeError, match="provider call"):
        await runtime.execute_planning_call(exact)

    assert provider_calls == []
    database_paths = tuple(exact.private_work_root.glob("call-*/planning.duckdb"))
    assert len(database_paths) == 1
    connection = runtime_module.duckdb.connect(str(database_paths[0]), read_only=True)
    try:
        assert connection.execute(
            "SELECT count(*) FROM _successor_extraction_journal"
        ).fetchone() == (0,)
    finally:
        connection.close()


async def test_w2_authority_failure_leaves_committed_staging_nonterminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    resources = replace(
        config.w2_authority_resources,
        live_plan_binding_factory=lambda *_args: (_ for _ in ()).throw(
            RuntimeError("hostile live-plan factory detail")
        ),
    )
    config = replace(config, w2_authority_resources=resources)
    planning_runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        planning_runtime,
        planning_generation_id="successor-planning-v2-w2-failure",
    )
    _install_fake_league_provider(monkeypatch, exact.dispatch)

    with pytest.raises(
        ExactPlanningRuntimeError,
        match="planning live-plan authority factory failed",
    ) as exc_info:
        await planning_runtime.execute_planning_call(exact)

    assert "hostile live-plan factory detail" not in str(exc_info.value)
    database_paths = tuple(exact.private_work_root.glob("call-*/planning.duckdb"))
    assert len(database_paths) == 1
    connection = runtime_module.duckdb.connect(str(database_paths[0]), read_only=True)
    try:
        row = connection.execute(
            """
            SELECT status, w2_required, w2_source_call_admission_bytes,
                   w2_operation_receipt_sha256
            FROM _successor_extraction_journal
            """
        ).fetchone()
        assert row == ("running", True, None, None)
        assert connection.execute("SELECT count(*) FROM _staging_chunk_journal").fetchone() == (1,)
    finally:
        connection.close()
    assert tuple(exact.private_work_root.glob("call-*/member-*.json")) == ()


async def test_real_execute_and_seal_with_private_bronze_and_duckdb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    runtime = ExtractorPlanningExactCallRuntime(_config(tmp_path))
    driver = RequestDrivenSuccessorPlanningDriver(runtime)
    scope = next(
        item
        for item in request.requested_planning_scopes
        if item.endpoint_name == "league_game_log"
        and item.parameters["season_type"] == "Regular Season"
    )
    scopes = request.requested_planning_scopes
    admission = PlanningWaveAdmission(
        wave_index=0,
        parent_wave_identity_sha256=None,
        requested_route_scopes=scopes,
        sealed_dispatches=driver._build_wave_0_dispatches(scopes),  # noqa: SLF001
    )
    dispatch = next(
        item
        for item in admission.sealed_dispatches
        if item.requested_scope_identity_sha256s == (scope.identity_sha256,)
    )
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    work.chmod(0o700)
    _install_fake_league_provider(monkeypatch, dispatch)
    exact = PlanningExactCallRuntimeRequest(
        request=request,
        planning_generation_id="successor-planning-v2-test",
        wave_index=0,
        admission=admission,
        dispatch=dispatch,
        requested_route_scopes=(scope,),
        provider_authority_sha256=(staging_route_contract_bundle().provider_authority_sha256),
        cutoff_utc=request.cutoff_utc,
        as_of_utc=request.as_of_utc,
        workflow_run_id=request.workflow_run_id,
        workflow_run_attempt=request.workflow_run_attempt,
        input_planning_database=None,
        private_work_root=work.resolve(),
    )

    # Treat the first successful runtime result as uncommitted, mirroring a
    # store commit failure.  Reissuing on the same runtime creates another
    # Bronze root, of which only the second is admitted to the seal below.
    uncommitted = await runtime.execute_planning_call(exact)
    execution = await runtime.execute_planning_call(exact)

    assert len(execution.members) == 1
    assert uncommitted.members[0].receipt_sha256 != execution.members[0].receipt_sha256
    assert execution.members[0].member.semantic.semantic_kind.value == "game_date_index"
    assert execution.planning_database.artifact.path.stat().st_mode & 0o777 == 0o600
    assert (
        execution.planning_database.artifact.byte_count
        <= runtime.config.planning_driver_database_max_bytes
    )
    committed_member = CommittedPlanningMember(
        member=execution.members[0].member,
        receipt_sha256=execution.members[0].receipt_sha256,
        artifact_sha256=execution.members[0].artifact.sha256,
        artifact_bytes=execution.members[0].artifact.byte_count,
        object_domain_sha256=_digest("member-object"),
    )
    committed_call = CommittedPlanningCall(
        ordinal=0,
        wave_index=0,
        sealed_dispatch=dispatch,
        requested_route_scopes=(scope,),
        members=(committed_member,),
        planning_database_sha256=execution.planning_database.artifact.sha256,
        planning_database_bytes=execution.planning_database.artifact.byte_count,
        planning_database_schema_sha256=execution.planning_database.schema_sha256,
        identity_sha256=_digest("committed-call"),
    )
    envelope = runtime_module.PlanningMemberEnvelope.from_canonical_bytes(
        execution.members[0].artifact.path.read_bytes()
    )
    seal_request = PlanningWaveSealRuntimeRequest(
        request=request,
        planning_generation_id=exact.planning_generation_id,
        admission=PlanningWaveAdmission(
            wave_index=0,
            parent_wave_identity_sha256=None,
            requested_route_scopes=(scope,),
            sealed_dispatches=(dispatch,),
        ),
        committed_calls=(committed_call,),
        member_envelopes=(envelope,),
        planning_database=execution.planning_database,
        private_work_root=work.resolve(),
    )

    seal = await runtime.seal_planning_wave(seal_request)
    reentered = await runtime.seal_planning_wave(seal_request)

    assert seal.wave.identity_sha256 == reentered.wave.identity_sha256
    assert seal.private_generation_identity.done_call_count == 1
    assert seal.private_generation_identity.orphan_call_count == 1
    assert seal.private_generation_identity == reentered.private_generation_identity
    assert seal.completion_receipt.capture_scope.workflow_run_id == request.workflow_run_id


async def test_real_extractor_runtime_wave0_crash_then_resume_seal_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    first_runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        first_runtime,
        planning_generation_id="successor-planning-v2-wave0-crash-resume",
    )
    provider_calls: list[str] = []
    _install_fake_league_provider(
        monkeypatch,
        exact.dispatch,
        provider_calls=provider_calls,
    )

    first_execution = await first_runtime.execute_planning_call(exact)
    assert provider_calls == [exact.dispatch.identity_sha256]
    assert len(first_execution.members) == 1
    crash_sessions = tuple(first_runtime._sessions.values())  # noqa: SLF001
    assert crash_sessions
    for session in crash_sessions:
        session.close()

    resume_runtime = ExtractorPlanningExactCallRuntime(config)
    assert resume_runtime.config.capture_base == config.capture_base
    assert resume_runtime.config.planning_store_root == config.planning_store_root
    # execute_planning_call never consults the planning store. An uncommitted
    # success is not skippable, so a new instance re-enters the provider.
    execution = await resume_runtime.execute_planning_call(exact)
    assert provider_calls == [
        exact.dispatch.identity_sha256,
        exact.dispatch.identity_sha256,
    ]
    assert first_execution.members[0].receipt_sha256 != execution.members[0].receipt_sha256
    assert execution.members[0].member.semantic.semantic_kind.value == "game_date_index"
    scope = exact.requested_route_scopes[0]
    committed_member = CommittedPlanningMember(
        member=execution.members[0].member,
        receipt_sha256=execution.members[0].receipt_sha256,
        artifact_sha256=execution.members[0].artifact.sha256,
        artifact_bytes=execution.members[0].artifact.byte_count,
        object_domain_sha256=_digest("member-object"),
    )
    committed_call = CommittedPlanningCall(
        ordinal=0,
        wave_index=0,
        sealed_dispatch=exact.dispatch,
        requested_route_scopes=(scope,),
        members=(committed_member,),
        planning_database_sha256=execution.planning_database.artifact.sha256,
        planning_database_bytes=execution.planning_database.artifact.byte_count,
        planning_database_schema_sha256=execution.planning_database.schema_sha256,
        identity_sha256=_digest("committed-call"),
    )
    envelope = runtime_module.PlanningMemberEnvelope.from_canonical_bytes(
        execution.members[0].artifact.path.read_bytes()
    )
    seal_request = PlanningWaveSealRuntimeRequest(
        request=exact.request,
        planning_generation_id=exact.planning_generation_id,
        admission=PlanningWaveAdmission(
            wave_index=0,
            parent_wave_identity_sha256=None,
            requested_route_scopes=(scope,),
            sealed_dispatches=(exact.dispatch,),
        ),
        committed_calls=(committed_call,),
        member_envelopes=(envelope,),
        planning_database=execution.planning_database,
        private_work_root=exact.private_work_root,
    )

    seal = await resume_runtime.seal_planning_wave(seal_request)
    reentered = await resume_runtime.seal_planning_wave(seal_request)

    assert seal.wave.identity_sha256 == reentered.wave.identity_sha256
    assert seal.private_generation_identity.done_call_count == 1
    assert seal.private_generation_identity.orphan_call_count == 1
    assert seal.private_generation_identity == reentered.private_generation_identity
    assert seal.completion_receipt.capture_scope.workflow_run_id == exact.request.workflow_run_id


async def test_both_planning_waves_crash_resume_then_no_change_sealed_identity(
    tmp_path: Path,
) -> None:
    wave_0_runtime = _SemanticRuntime(fail_seal_wave_once=0)
    request, store, _runtime, wave_0 = _executor(tmp_path, runtime=wave_0_runtime)
    with pytest.raises(RuntimeError, match="seal-wave-0"):
        await wave_0(request)
    assert wave_0_runtime.call_requests
    assert all(call.wave_index == 0 for call in wave_0_runtime.call_requests)

    wave_1_runtime = _SemanticRuntime(fail_seal_wave_once=1)
    _request_again, _store_again, _runtime_again, wave_1 = _executor(
        tmp_path,
        runtime=wave_1_runtime,
        store=store,
    )
    with pytest.raises(RuntimeError, match="seal-wave-1"):
        await wave_1(request)
    assert wave_1_runtime.call_requests
    assert all(call.wave_index == 1 for call in wave_1_runtime.call_requests)

    completing_runtime = _SemanticRuntime()
    _request_complete, _store_complete, _runtime_complete, completing = _executor(
        tmp_path,
        runtime=completing_runtime,
        store=store,
    )
    evidence = await completing(request)
    assert completing_runtime.call_requests == []
    snapshot = store.load_and_verify(
        request,
        deterministic_planning_generation_id(request),
        budget=_BudgetFactory()(),
    )
    assert snapshot.phase is PlanningGenerationPhase.SEALED

    replay_runtime = _SemanticRuntime()
    _request_replay, _store_replay, _runtime_replay, replay = _executor(
        tmp_path,
        runtime=replay_runtime,
        store=store,
    )
    replayed = await replay(request)
    verified = replay.verify(request, evidence)

    assert replay_runtime.call_requests == []
    assert replay_runtime.seal_requests == []
    assert replayed.identity_sha256 == evidence.identity_sha256
    assert replayed.planning_generation_manifest.identity_sha256 == (
        evidence.planning_generation_manifest.identity_sha256
    )
    assert replayed.execution_plan.identity_sha256 == evidence.execution_plan.identity_sha256
    assert replayed.to_dict() == evidence.to_dict()
    assert verified.to_dict() == evidence.to_dict()
    assert tuple(wave.identity_sha256 for wave in replayed.planning_generation_manifest.waves) == (
        tuple(wave.identity_sha256 for wave in evidence.planning_generation_manifest.waves)
    )
