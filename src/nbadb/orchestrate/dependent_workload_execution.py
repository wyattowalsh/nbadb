"""Execute one exact shard from a receipt-bound dependent workload plan."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import polars as pl

from nbadb.contracts.logical_provider_parameter_binding import (
    LogicalProviderParameterBindingV1,
    compile_logical_provider_parameter_binding,
    verify_logical_provider_parameter_binding,
)
from nbadb.core.config import NbaDbSettings, get_settings
from nbadb.extract.bronze import canonical_parameters_sha256
from nbadb.orchestrate.dependent_workload_contract import (
    DependentWorkloadContractError,
    canonical_json_bytes,
)
from nbadb.orchestrate.dependent_workload_planning import (
    DEPENDENT_LANE_KIND,
    DependentExecutionLane,
    DependentExecutionPlan,
    DependentPhysicalCall,
)
from nbadb.orchestrate.orchestrator import ExtractionOutcome, Orchestrator
from nbadb.orchestrate.raw_request_environment import (
    raw_request_assurance_authority_from_env,
    raw_request_execution_identity_from_env,
)
from nbadb.orchestrate.w2_runtime_environment import (
    w2_source_call_preparation_runtime_from_env,
)

if TYPE_CHECKING:
    from nbadb.core.db import DBManager
    from nbadb.orchestrate.extractor_runner import ExtractorRunner
    from nbadb.orchestrate.journal import PipelineJournal
    from nbadb.orchestrate.planning import ExtractionPlanItem
    from nbadb.orchestrate.raw_request_assurance import RawRequestAssuranceAuthorityV2
    from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1
    from nbadb.orchestrate.request_closure_production import ProductionRequestClosureBuild
    from nbadb.orchestrate.w2_source_call_preparation import (
        W2SourceCallPreparationRuntime,
    )


def _append_github_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def _require_exact(value: str, expected: str, *, field_name: str) -> None:
    if value != expected:
        raise DependentWorkloadContractError(
            f"dependent {field_name} differs from the manifest authority"
        )


def load_authorized_dependent_lane(
    *,
    plan_path: Path,
    lane_id: str,
    expected_plan_sha256: str,
    expected_bundle_sha256: str,
    expected_lane_sha256: str,
    expected_foundation_transaction_sha256: str,
    expected_source_sha: str,
    expected_provider_authority_sha256: str,
) -> tuple[DependentExecutionPlan, DependentExecutionLane]:
    """Load one lane only after every manifest-bound content authority matches."""

    plan = DependentExecutionPlan.read(plan_path)
    lane = plan.lane(lane_id)
    for actual, expected, field_name in (
        (plan.content_sha256, expected_plan_sha256, "execution plan digest"),
        (plan.bundle_content_sha256, expected_bundle_sha256, "bundle digest"),
        (lane.content_sha256, expected_lane_sha256, "lane digest"),
        (
            plan.checkpoint_transaction_sha256,
            expected_foundation_transaction_sha256,
            "foundation checkpoint transaction",
        ),
        (plan.source_sha, expected_source_sha, "semantic source"),
        (
            plan.provider_authority_sha256,
            expected_provider_authority_sha256,
            "provider authority",
        ),
    ):
        _require_exact(actual, expected, field_name=field_name)
    return plan, lane


def _load_dependent_raw_request_authorities(
    plan: DependentExecutionPlan,
    lane: DependentExecutionLane,
) -> tuple[RawRequestExecutionIdentityV1, RawRequestAssuranceAuthorityV2]:
    """Fail closed before construction of any call-capable runtime object."""

    if not lane.calls:
        raise DependentWorkloadContractError(
            "provider-free dependent lane cannot request raw-request authorities"
        )
    try:
        raw_execution = raw_request_execution_identity_from_env()
    except Exception:
        raise DependentWorkloadContractError(
            "dependent provider lane raw-request execution authority is invalid"
        ) from None
    if raw_execution is None:
        raise DependentWorkloadContractError(
            "dependent provider lane requires raw-request execution authority"
        )
    from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1

    if type(raw_execution) is not RawRequestExecutionIdentityV1:
        raise DependentWorkloadContractError(
            "dependent provider lane raw-request execution authority is invalid"
        )
    try:
        execution = RawRequestExecutionIdentityV1(
            source_sha=raw_execution.source_sha,
            run_id=raw_execution.run_id,
            run_attempt=raw_execution.run_attempt,
            chain_id=raw_execution.chain_id,
            lane_id=raw_execution.lane_id,
        )
    except Exception:
        raise DependentWorkloadContractError(
            "dependent provider lane raw-request execution authority is invalid"
        ) from None
    if execution is raw_execution or execution != raw_execution:
        raise DependentWorkloadContractError(
            "dependent provider lane raw-request execution authority is invalid"
        )
    if execution.source_sha != plan.source_sha:
        raise DependentWorkloadContractError(
            "dependent raw-request execution source differs from the execution plan"
        )
    if execution.lane_id != lane.lane_id:
        raise DependentWorkloadContractError(
            "dependent raw-request execution lane differs from the authorized lane"
        )
    try:
        raw_assurance = raw_request_assurance_authority_from_env(execution)
    except Exception:
        raise DependentWorkloadContractError(
            "dependent provider lane raw-request assurance authority is invalid"
        ) from None
    if raw_assurance is None:
        raise DependentWorkloadContractError(
            "dependent provider lane requires independently validated raw-request assurance"
        )
    from nbadb.orchestrate.raw_request_assurance import (
        RawRequestAssuranceAuthorityV2,
        validate_raw_request_assurance_authority,
    )

    if type(raw_assurance) is not RawRequestAssuranceAuthorityV2:
        raise DependentWorkloadContractError(
            "dependent provider lane raw-request assurance authority is invalid"
        )
    try:
        validated = validate_raw_request_assurance_authority(raw_assurance)
        if type(validated) is not RawRequestAssuranceAuthorityV2 or validated is not raw_assurance:
            raise TypeError
        assurance = RawRequestAssuranceAuthorityV2(
            source_sha=raw_assurance.source_sha,
            assurance_admission_sha256=raw_assurance.assurance_admission_sha256,
            assurance_manifest_sha256=raw_assurance.assurance_manifest_sha256,
            generation_semantic_sha256=raw_assurance.generation_semantic_sha256,
            generation_index_sha256=raw_assurance.generation_index_sha256,
            provider_evidence_sha256=raw_assurance.provider_evidence_sha256,
            provider_authority_sha256=raw_assurance.provider_authority_sha256,
            field_children=raw_assurance.field_children,
            model_children=raw_assurance.model_children,
            field_authority_sha256=raw_assurance.field_authority_sha256,
            model_authority_sha256=raw_assurance.model_authority_sha256,
            validation_provenance_sha256=raw_assurance.validation_provenance_sha256,
        )
        replayed = validate_raw_request_assurance_authority(assurance)
    except Exception:
        raise DependentWorkloadContractError(
            "dependent provider lane raw-request assurance authority is invalid"
        ) from None
    if (
        assurance is raw_assurance
        or assurance != raw_assurance
        or type(replayed) is not RawRequestAssuranceAuthorityV2
        or replayed is not assurance
    ):
        raise DependentWorkloadContractError(
            "dependent provider lane raw-request assurance authority is invalid"
        )
    if assurance.source_sha != plan.source_sha:
        raise DependentWorkloadContractError(
            "dependent raw-request assurance source differs from the execution plan"
        )
    if assurance.provider_authority_sha256 != plan.provider_authority_sha256:
        raise DependentWorkloadContractError(
            "dependent raw-request assurance differs from the provider authority"
        )
    return execution, assurance


def _build_dependent_w2_runtime(
    execution: RawRequestExecutionIdentityV1,
    assurance: RawRequestAssuranceAuthorityV2,
) -> W2SourceCallPreparationRuntime:
    """Admit one exact run-owned W2 runtime before provider construction."""

    try:
        runtime = w2_source_call_preparation_runtime_from_env(execution, assurance)
    except Exception:
        raise DependentWorkloadContractError(
            "dependent provider lane W2 preparation runtime is invalid"
        ) from None
    from nbadb.orchestrate.w2_source_call_preparation import (
        W2SourceCallPreparationRuntime,
    )

    if type(runtime) is not W2SourceCallPreparationRuntime:
        raise DependentWorkloadContractError(
            "dependent provider lane W2 preparation runtime is invalid"
        )
    try:
        expected_execution = (
            execution.source_sha,
            execution.run_id,
            execution.run_attempt,
            execution.chain_id,
            execution.lane_id,
        )
        for store in (
            runtime.body_blob_store,
            runtime.declared_bodyless_packet_store,
        ):
            store_execution = (
                store._source_sha,  # noqa: SLF001
                store._run_id,  # noqa: SLF001
                store._run_attempt,  # noqa: SLF001
                store._chain_id,  # noqa: SLF001
                store._lane_id,  # noqa: SLF001
            )
            if store_execution != expected_execution:
                raise TypeError
        exact = W2SourceCallPreparationRuntime(
            body_blob_store=runtime.body_blob_store,
            declared_bodyless_packet_store=runtime.declared_bodyless_packet_store,
            field_fate=runtime.field_fate,
            known_secrets=runtime.known_secrets,
        )
    except Exception:
        raise DependentWorkloadContractError(
            "dependent provider lane W2 preparation runtime is invalid"
        ) from None
    if exact is runtime or exact != runtime or exact.known_secrets:
        raise DependentWorkloadContractError(
            "dependent provider lane W2 preparation runtime is invalid"
        )
    return exact


def _build_dependent_request_closure(
    *,
    orchestrator: Orchestrator,
    runner: ExtractorRunner,
    lane: DependentExecutionLane,
    extraction_plan: list[ExtractionPlanItem],
) -> ProductionRequestClosureBuild:
    """Compile and reconcile one lane's complete provider-call denominator."""

    if not lane.calls or not extraction_plan:
        raise DependentWorkloadContractError(
            "dependent provider lane lacks its exact extraction plan"
        )
    closure = orchestrator._build_ordinary_request_closure(
        runner,
        extraction_plan,
        run_mode="backfill",
        support_date=date.today(),
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )
    if closure.authority is None or closure.static_authorities or closure.scope_gaps:
        raise DependentWorkloadContractError(
            "dependent provider lane request closure is incomplete"
        )
    expected_calls = {(call.endpoint_name, call.parameters_sha256) for call in lane.calls}
    actual_calls = {
        (call.endpoint_name, call.logical_parameters_sha256)
        for call in closure.authority.logical_calls
    }
    if len(closure.authority.logical_calls) != len(lane.calls) or actual_calls != expected_calls:
        raise DependentWorkloadContractError(
            "dependent provider lane request closure differs from its physical calls"
        )
    expected_routes = {route_id for call in lane.calls for route_id in call.result_route_ids}
    actual_routes = {alias.staging_route_id for alias in closure.authority.staging_route_aliases}
    if actual_routes != expected_routes:
        raise DependentWorkloadContractError(
            "dependent provider lane request closure differs from its staging routes"
        )
    return closure


def _dependent_provider_semantic_parameters(
    call: DependentPhysicalCall,
) -> tuple[dict[str, int | str], ...]:
    """Project one exact dependent logical call to its pinned provider names."""

    if call.endpoint_name not in {
        "player_vs_player",
        "team_vs_player",
        "team_and_players_vs",
        "team_and_players_vs_players",
    }:
        raise DependentWorkloadContractError(
            "dependent provider parameter projection received a foreign endpoint"
        )
    parameters = dict(call.parameters)
    season_type = parameters.pop("season_type", None)
    if type(season_type) is not str or not season_type:
        raise DependentWorkloadContractError(
            "dependent provider parameter projection lacks exact season type"
        )
    return ({**parameters, "season_type_playoffs": season_type},)


def _compile_dependent_parameter_bindings(
    *,
    orchestrator: Orchestrator,
    lane: DependentExecutionLane,
    request_closure: ProductionRequestClosureBuild,
) -> dict[tuple[str, str], tuple[LogicalProviderParameterBindingV1, str]]:
    """Compile and externally pin every logical/provider join before transport."""

    authority = request_closure.authority
    execution = orchestrator._raw_request_execution_identity  # noqa: SLF001
    if authority is None or execution is None or request_closure.static_authorities:
        raise DependentWorkloadContractError(
            "dependent provider parameter binding lacks exact Raw context authority"
        )
    try:
        from nbadb.orchestrate.raw_request_context import (
            build_ordinary_raw_request_context_factory,
        )

        context_factory = build_ordinary_raw_request_context_factory(
            authority,
            (),
            execution,
        )
        bindings: dict[
            tuple[str, str],
            tuple[LogicalProviderParameterBindingV1, str],
        ] = {}
        for call in lane.calls:
            logical_parameters: dict[str, object] = dict(call.parameters)
            context = context_factory(call.endpoint_name, logical_parameters)
            compiled = compile_logical_provider_parameter_binding(
                raw_request_context=context,
                logical_endpoint_name=call.endpoint_name,
                logical_parameters=logical_parameters,
                result_route_ids=tuple(sorted(call.result_route_ids)),
                provider_semantic_parameters=(_dependent_provider_semantic_parameters(call)),
            )
            binding_sha256 = compiled.binding_sha256
            replayed = verify_logical_provider_parameter_binding(
                compiled,
                expected_binding_sha256=binding_sha256,
            )
            key = (call.endpoint_name, call.parameters_sha256)
            if key in bindings:
                raise DependentWorkloadContractError(
                    "dependent provider parameter binding repeats a physical call"
                )
            bindings[key] = (replayed, binding_sha256)
    except DependentWorkloadContractError:
        raise
    except Exception:
        raise DependentWorkloadContractError(
            "dependent logical/provider parameter binding compilation failed"
        ) from None
    if len(bindings) != len(lane.calls):
        raise DependentWorkloadContractError(
            "dependent logical/provider parameter binding inventory is incomplete"
        )
    return bindings


def _attach_dependent_parameter_bindings(
    *,
    source_results: object,
    bindings: dict[
        tuple[str, str],
        tuple[LogicalProviderParameterBindingV1, str],
    ],
) -> None:
    """Attach only the precompiled pair selected by exact logical call identity."""

    if type(source_results) is not list or not source_results:
        raise DependentWorkloadContractError(
            "dependent provider persistence lacks exact source-call evidence"
        )
    for source_result in source_results:
        if type(source_result) is not dict:
            raise DependentWorkloadContractError(
                "dependent provider persistence has a foreign source-call DTO"
            )
        exact_source_result = cast("dict[str, object]", source_result)
        if (
            "logical_provider_parameter_binding" in exact_source_result
            or "expected_logical_provider_parameter_binding_sha256" in exact_source_result
        ):
            raise DependentWorkloadContractError(
                "dependent provider persistence received a pre-populated parameter binding"
            )
        endpoint_name = exact_source_result.get("source_endpoint_name")
        source_params_json = exact_source_result.get("source_params_json")
        if type(endpoint_name) is not str or type(source_params_json) is not str:
            raise DependentWorkloadContractError(
                "dependent provider persistence lacks exact logical call identity"
            )
        try:
            logical_parameters = json.loads(source_params_json)
            if type(logical_parameters) is not dict:
                raise TypeError
            logical_parameters_sha256 = canonical_parameters_sha256(logical_parameters)
        except Exception:
            raise DependentWorkloadContractError(
                "dependent provider persistence has invalid logical parameters"
            ) from None
        selected = bindings.get((endpoint_name, logical_parameters_sha256))
        if selected is None:
            raise DependentWorkloadContractError(
                "dependent provider persistence lacks its precompiled parameter binding"
            )
        binding, binding_sha256 = selected
        exact_source_result["logical_provider_parameter_binding"] = binding
        exact_source_result["expected_logical_provider_parameter_binding_sha256"] = binding_sha256


def _assure_dependent_w2_completion(
    *,
    orchestrator: Orchestrator,
    db: DBManager,
    journal: PipelineJournal,
    lane: DependentExecutionLane,
    outcome: ExtractionOutcome,
) -> None:
    """Prove one provider lane is terminal before materialization/checkpoint.

    The runner defers each journal success until the persistence callback has
    committed staging, Raw Authority V2, and the exact-six W2 operation.  This
    postcondition independently replays those durable admissions and the
    terminal request denominator before this executor exposes a checkpoint.
    """

    if not lane.calls or outcome.pattern_failures or outcome.failed_calls or outcome.errors:
        raise DependentWorkloadContractError(
            "dependent provider lane extraction closure is incomplete"
        )

    inventory = orchestrator.request_closure_inventory
    if (
        inventory is None
        or inventory.authority is None
        or inventory.incomplete
        or inventory.scope_gaps
        or inventory.green is not True
        or len(inventory.observations) != len(lane.calls)
    ):
        raise DependentWorkloadContractError(
            "dependent provider lane request closure did not reach terminal green"
        )

    manifest = orchestrator.raw_request_authority_manifest
    if (
        manifest is None
        or manifest.is_complete is not True
        or manifest.coverage_complete is not True
        or manifest.terminal_sealed is not True
        or manifest.expected_request_count != len(lane.calls)
        or manifest.completed_request_count != len(lane.calls)
        or manifest.unresolved_request_count != 0
        or manifest.receipt_count != len(lane.calls)
    ):
        raise DependentWorkloadContractError(
            "dependent provider lane Raw Authority V2 closure is incomplete"
        )

    journal_keys = [
        (
            call.endpoint_name,
            json.dumps(dict(call.parameters), sort_keys=True),
        )
        for call in lane.calls
    ]
    if len(journal_keys) != len(set(journal_keys)):
        raise DependentWorkloadContractError(
            "dependent provider lane repeats one physical journal identity"
        )
    try:
        completed = journal.was_extracted_batch(
            journal_keys,
            require_receipt=True,
            require_w2_operation=True,
        )
    except Exception:
        raise DependentWorkloadContractError(
            "dependent provider lane journal W2 replay failed"
        ) from None
    if type(completed) is not set or completed != set(journal_keys):
        raise DependentWorkloadContractError(
            "dependent provider lane lacks one durable W2 journal admission per call"
        )

    try:
        receipt = _verify_dependent_w2_database(db)
    except Exception:
        raise DependentWorkloadContractError(
            "dependent provider lane W2 database authority is incomplete"
        ) from None
    if (
        receipt.w2_required_logical_call_count != len(lane.calls)
        or receipt.raw_authority_v2_bundle_count != len(lane.calls)
        or receipt.w2_publication_receipt_count != len(lane.calls)
    ):
        raise DependentWorkloadContractError(
            "dependent provider lane W2 database call inventory differs from its plan"
        )


def _verify_dependent_w2_database(db: DBManager) -> Any:
    """Return one exact database-derived W2 receipt through a narrow test seam."""

    from nbadb.orchestrate.w2_database_assurance import (
        W2DatabaseAuthorityReceiptV1,
        verify_w2_database_authority,
    )

    receipt = verify_w2_database_authority(db.duckdb, require_w2=True)
    if type(receipt) is not W2DatabaseAuthorityReceiptV1:
        raise DependentWorkloadContractError(
            "dependent provider lane W2 database verifier returned a foreign receipt"
        )
    return receipt


async def _execute_lane_with_runner(
    *,
    orchestrator: Orchestrator,
    db: DBManager,
    journal: PipelineJournal,
    runner: ExtractorRunner,
    lane: DependentExecutionLane,
) -> ExtractionOutcome:
    """Use the normal runner and committed staging store without discovery fan-out."""

    if not lane.calls:
        db.duckdb.execute("CHECKPOINT")
        return ExtractionOutcome(raw={})
    extraction_plan = lane.to_extraction_plan_items()
    request_closure = _build_dependent_request_closure(
        orchestrator=orchestrator,
        runner=runner,
        lane=lane,
        extraction_plan=extraction_plan,
    )
    parameter_bindings = _compile_dependent_parameter_bindings(
        orchestrator=orchestrator,
        lane=lane,
        request_closure=request_closure,
    )

    def persist_dependent_results(
        frames: dict[str, pl.DataFrame],
        **metadata: object,
    ) -> Any:
        source_results = metadata.get("source_results")
        if source_results is not None:
            _attach_dependent_parameter_bindings(
                source_results=source_results,
                bindings=parameter_bindings,
            )
        persistence = cast("Any", orchestrator._persist_staging_to_duckdb)
        return persistence(
            db,
            frames,
            **metadata,
        )

    outcome = await orchestrator._extract_all_patterns(
        runner,
        plan=extraction_plan,
        seasons=[],
        game_ids=[],
        player_ids=[],
        team_ids=[],
        current_team_ids=[],
        game_dates=[],
        player_team_season_params=[],
        game_log_df=pl.DataFrame(),
        include_static=False,
        run_mode=DEPENDENT_LANE_KIND,
        journal=journal,
        persist_results=persist_dependent_results,
        retain_in_memory=False,
        request_closure_build=request_closure,
    )
    _assure_dependent_w2_completion(
        orchestrator=orchestrator,
        db=db,
        journal=journal,
        lane=lane,
        outcome=outcome,
    )
    orchestrator._materialize_staging_batches(
        db,
        endpoints=[lane.endpoint_name],
    )
    db.duckdb.execute("CHECKPOINT")
    return outcome


async def execute_dependent_lane(
    *,
    plan_path: Path,
    lane_id: str,
    expected_plan_sha256: str,
    expected_bundle_sha256: str,
    expected_lane_sha256: str,
    expected_foundation_transaction_sha256: str,
    expected_source_sha: str,
    expected_provider_authority_sha256: str,
    data_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise DependentWorkloadContractError("dependent lane timeout must be positive")
    plan, lane = load_authorized_dependent_lane(
        plan_path=plan_path,
        lane_id=lane_id,
        expected_plan_sha256=expected_plan_sha256,
        expected_bundle_sha256=expected_bundle_sha256,
        expected_lane_sha256=expected_lane_sha256,
        expected_foundation_transaction_sha256=expected_foundation_transaction_sha256,
        expected_source_sha=expected_source_sha,
        expected_provider_authority_sha256=expected_provider_authority_sha256,
    )
    execution_identity = None
    assurance_authority = None
    w2_preparation_runtime = None
    if lane.calls:
        execution_identity, assurance_authority = _load_dependent_raw_request_authorities(
            plan,
            lane,
        )
        w2_preparation_runtime = _build_dependent_w2_runtime(
            execution_identity,
            assurance_authority,
        )
    base_settings = get_settings()
    settings_payload = {
        **base_settings.model_dump(),
        "data_dir": data_dir,
        "duckdb_path": data_dir / "nba.duckdb",
        "sqlite_path": data_dir / "nba.sqlite",
    }
    settings = NbaDbSettings.model_validate(settings_payload)
    orchestrator = Orchestrator(
        settings=settings,
        raw_request_execution_identity=execution_identity,
        raw_request_assurance_authority=assurance_authority,
        w2_preparation_runtime=w2_preparation_runtime,
    )
    if lane.calls:
        orchestrator._enable_ordinary_request_closure_capture()
    started_at = datetime.now(UTC)
    try:
        db, journal = orchestrator._init_db()

        async def run() -> ExtractionOutcome:
            async with orchestrator._build_runner(journal) as runner:
                return await _execute_lane_with_runner(
                    orchestrator=orchestrator,
                    db=db,
                    journal=journal,
                    runner=runner,
                    lane=lane,
                )

        async with asyncio.timeout(timeout_seconds):
            outcome = await run()
        status = (
            "complete" if not outcome.pattern_failures and not outcome.failed_calls else "failed"
        )
        return {
            "schema_version": 1,
            "kind": "dependent_lane_execution_summary",
            "status": status,
            "lane_id": lane.lane_id,
            "lane_role": lane.role,
            "lane_content_sha256": lane.content_sha256,
            "execution_plan_content_sha256": plan.content_sha256,
            "bundle_content_sha256": plan.bundle_content_sha256,
            "result": {
                "rows_total": 0,
                "failed_extractions": outcome.failed_calls,
                "pattern_failures": outcome.pattern_failures,
                "errors": [],
            },
            "progress": {
                "planned_physical_calls": len(lane.calls),
                "planned_semantic_units": lane.semantic_unit_count,
            },
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
        }
    finally:
        orchestrator.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-path", type=Path, required=True)
    parser.add_argument("--lane-id", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    parser.add_argument("--expected-lane-sha256", required=True)
    parser.add_argument("--expected-foundation-transaction-sha256", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-provider-authority-sha256", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    parser.add_argument("--summary-path", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _append_github_output("started-at", started_at)
    _append_github_output("effective-timeout-seconds", str(args.timeout_seconds))
    try:
        summary = asyncio.run(
            execute_dependent_lane(
                plan_path=args.plan_path,
                lane_id=args.lane_id,
                expected_plan_sha256=args.expected_plan_sha256,
                expected_bundle_sha256=args.expected_bundle_sha256,
                expected_lane_sha256=args.expected_lane_sha256,
                expected_foundation_transaction_sha256=(
                    args.expected_foundation_transaction_sha256
                ),
                expected_source_sha=args.expected_source_sha,
                expected_provider_authority_sha256=(args.expected_provider_authority_sha256),
                data_dir=args.data_dir,
                timeout_seconds=args.timeout_seconds,
            )
        )
        exit_code = 0 if summary["status"] == "complete" else 1
        status = "complete" if exit_code == 0 else "extract-error"
    except TimeoutError:
        summary = {
            "schema_version": 1,
            "kind": "dependent_lane_execution_summary",
            "status": "timeout",
            "result": {"rows_total": 0, "failed_extractions": 1, "errors": []},
        }
        exit_code = 124
        status = "extract-timeout"
    except Exception as exc:
        summary = {
            "schema_version": 1,
            "kind": "dependent_lane_execution_summary",
            "status": "failed",
            "result": {
                "rows_total": 0,
                "failed_extractions": 1,
                "errors": [{"exception_class": type(exc).__name__}],
            },
        }
        exit_code = 1
        status = "extract-error"
    args.summary_path.parent.mkdir(parents=True, exist_ok=True)
    args.summary_path.write_bytes(canonical_json_bytes(summary) + b"\n")
    _append_github_output("status", status)
    _append_github_output("exit-code", str(exit_code))
    _append_github_output("finished-at", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
