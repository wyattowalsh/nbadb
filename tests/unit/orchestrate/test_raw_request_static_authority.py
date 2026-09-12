from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

import pytest

from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.core.nba_api_runtime_contract import pinned_static_dataset_contract
from nbadb.extract.bronze import ParserInputContext
from nbadb.extract.nba_api_adapter import NbaApiCaptureContract
from nbadb.extract.registry import EndpointRegistry
from nbadb.extract.static.players import (
    StaticPlayersExtractor,
    StaticWnbaPlayersExtractor,
)
from nbadb.extract.static.teams import StaticTeamsExtractor, StaticWnbaTeamsExtractor
from nbadb.orchestrate.planning import ExtractionPlanItem
from nbadb.orchestrate.raw_request_context import (
    RawRequestContextCompilationError,
    RawRequestExecutionIdentityV1,
    build_ordinary_raw_request_context_factory,
    compile_static_raw_request_context,
)
from nbadb.orchestrate.request_closure_production import (
    ReceiptOnlyParserInputSink,
    StaticRequestClosureAuthorityV1,
    build_ordinary_request_closure_authority,
)
from nbadb.orchestrate.staging_map import get_by_endpoint

if TYPE_CHECKING:
    from nbadb.extract.base import BaseExtractor

_SUPPORT_DATE = date(2026, 8, 27)
_STATIC_EXTRACTORS = (
    StaticPlayersExtractor,
    StaticTeamsExtractor,
    StaticWnbaPlayersExtractor,
    StaticWnbaTeamsExtractor,
)
_STATIC_ENDPOINTS = tuple(sorted(item.endpoint_name for item in _STATIC_EXTRACTORS))


def _static_registry() -> EndpointRegistry:
    registry = EndpointRegistry()
    for extractor in _STATIC_EXTRACTORS:
        registry.register(extractor)
    return registry


def _static_plan(*endpoint_names: str) -> list[ExtractionPlanItem]:
    plan: list[ExtractionPlanItem] = []
    for endpoint_name in endpoint_names:
        entries = get_by_endpoint(endpoint_name)
        assert entries
        plan.append(
            ExtractionPlanItem(
                label=f"static raw authority: {endpoint_name}",
                pattern=entries[0].param_pattern,
                entries=entries,
                params=[{}],
                priority=0,
            )
        )
    return plan


def _build_all_static() -> tuple[StaticRequestClosureAuthorityV1, ...]:
    build = build_ordinary_request_closure_authority(
        _static_plan(*_STATIC_ENDPOINTS),
        registry=_static_registry(),
        run_mode="init",
        support_date=_SUPPORT_DATE,
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )
    assert build.authority is None
    assert build.scope_gaps == ()
    return build.static_authorities


def _execution(**overrides: object) -> RawRequestExecutionIdentityV1:
    values: dict[str, object] = {
        "source_sha": "1" * 40,
        "run_id": 101,
        "run_attempt": 1,
        "chain_id": "chain-static",
        "lane_id": "lane-static",
    }
    values.update(overrides)
    return RawRequestExecutionIdentityV1(**values)  # type: ignore[arg-type]


def test_all_four_registered_static_extractors_bind_fixed_parameterless_authority() -> None:
    authorities = _build_all_static()

    assert tuple(item.endpoint_name for item in authorities) == _STATIC_ENDPOINTS
    assert {item.competition_id for item in authorities} == {"00", "10"}
    assert len({item.provider_request_sha256 for item in authorities}) == 4
    assert len({item.static_authority_sha256 for item in authorities}) == 4
    for authority in authorities:
        assert authority.logical_parameters_sha256
        assert authority.physical_route_ids == (
            f"{authority.endpoint_name}:stg_{authority.endpoint_name}:0",
        )
        assert authority.qualified_request.request_kind == "static_source"
        assert authority.qualified_request.provider_request_sha256 is None
        assert (
            authority.competition_identity_sha256
            == authority.qualified_request.source_request_sha256
        )
        assert authority.to_dict()["static_authority_sha256"] == (authority.static_authority_sha256)


def test_static_context_compiler_binds_fixed_root_route_and_execution() -> None:
    authorities = _build_all_static()
    factory = build_ordinary_raw_request_context_factory(None, authorities, _execution())

    for authority in authorities:
        context = factory(authority.endpoint_name, {})
        assert context.provider_authority_sha256 == authority.provider_authority_sha256
        assert context.source_sha == "1" * 40
        assert len(context.provider_calls) == 1
        call = context.provider_calls[0]
        assert call.source_family == "static"
        assert call.endpoint_id == authority.endpoint_name
        assert call.provider_call_role == "static_snapshot"
        assert call.provider_request_sha256 == authority.provider_request_sha256
        assert call.endpoint_contract_sha256 == authority.endpoint_contract_sha256
        assert call.competition_id == authority.competition_id
        assert call.competition_identity_sha256 == authority.competition_identity_sha256
        assert call.scope_sha256 == authority.scope_sha256
        assert call.pagination_sha256 is None
        assert call.page_ordinal is None


@pytest.mark.asyncio
@pytest.mark.parametrize("extractor_cls", _STATIC_EXTRACTORS)
async def test_registered_static_extractor_emits_bodyless_pending_success(
    extractor_cls: type[BaseExtractor],
) -> None:
    authorities = _build_all_static()
    authority = next(
        item for item in authorities if item.endpoint_name == extractor_cls.endpoint_name
    )
    public_context = compile_static_raw_request_context(
        authority,
        _execution(),
        authority.endpoint_name,
        {},
    )
    sink = ReceiptOnlyParserInputSink()
    extractor = extractor_cls()
    extractor.begin_extraction_attempt()
    extractor.set_raw_request_capture_context(public_context)
    extractor.set_capture_contract(
        NbaApiCaptureContract(
            sink=sink,
            context=ParserInputContext(
                attempt_id=f"static-{authority.endpoint_name}",
                workflow_run_id=101,
                workflow_run_attempt=1,
                chain_id="chain-static",
                lane_id="lane-static",
                semantic_source_sha="1" * 40,
            ),
            provider_authority_sha256=authority.provider_authority_sha256,
            endpoint_contract_sha256="0" * 64,
        )
    )

    frame = await extractor.extract()
    snapshot = extractor.raw_request_capture_snapshot()

    assert frame.height == pinned_static_dataset_contract(authority.endpoint_name).row_count
    assert snapshot is not None
    assert snapshot.objects == snapshot.observations == snapshot.issues == ()
    assert len(snapshot.pending_successes) == 1
    pending = snapshot.pending_successes[0]
    assert pending.attempt.source_family == "static"
    assert pending.attempt.competition_identity_sha256 == (authority.competition_identity_sha256)
    assert pending.outcome == "static_snapshot_success"
    assert pending.body_disposition == "declared_bodyless"
    assert pending.body_object is None
    assert pending.transport.transport_kind == "static_snapshot"


def test_static_semantic_identity_is_execution_stable_and_invocation_is_not() -> None:
    authority = _build_all_static()[0]
    first = compile_static_raw_request_context(
        authority,
        _execution(),
        authority.endpoint_name,
        {},
    ).provider_calls[0]
    second = compile_static_raw_request_context(
        authority,
        _execution(source_sha="2" * 40, run_id=202, lane_id="lane-static-2"),
        authority.endpoint_name,
        {},
    ).provider_calls[0]

    assert first.semantic_request_sha256 == second.semantic_request_sha256
    assert first.logical_invocation_sha256 != second.logical_invocation_sha256


def test_static_closure_keeps_gap_when_registered_extractor_evidence_is_missing() -> None:
    build = build_ordinary_request_closure_authority(
        _static_plan("static_players"),
        registry=EndpointRegistry(),
        run_mode="init",
        support_date=_SUPPORT_DATE,
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )

    assert build.authority is None
    assert build.static_authorities == ()
    assert tuple(item.reason_code for item in build.scope_gaps) == ("static_receipt_not_bound",)


def test_static_closure_keeps_gap_when_fixed_competition_root_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.orchestrate.request_closure_production as production

    requirements = production.compile_competition_identity_requirements()
    monkeypatch.setattr(
        production,
        "compile_competition_identity_requirements",
        lambda: tuple(item for item in requirements if item.repo_endpoint_name != "static_players"),
    )

    build = build_ordinary_request_closure_authority(
        _static_plan("static_players"),
        registry=_static_registry(),
        run_mode="init",
        support_date=_SUPPORT_DATE,
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )

    assert build.static_authorities == ()
    assert tuple(item.reason_code for item in build.scope_gaps) == ("static_receipt_not_bound",)


@pytest.mark.parametrize(
    "mutation",
    [
        {"physical_route_ids": ("static_players:stg_foreign:0",)},
        {"competition_identity_sha256": "0" * 64},
        {"provider_request_sha256": "0" * 64},
        {"scope_sha256": "0" * 64},
    ],
)
def test_static_authority_rejects_foreign_route_root_or_digest(
    mutation: dict[str, object],
) -> None:
    authority = next(item for item in _build_all_static() if item.endpoint_name == "static_players")

    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="failed exact revalidation",
    ):
        replace(authority, **mutation)


@pytest.mark.parametrize(
    ("endpoint_name", "params"),
    [
        ("static_players", {"league_id": "00"}),
        ("static_unknown", {}),
    ],
)
def test_static_context_factory_rejects_parameters_or_uncovered_endpoint(
    endpoint_name: str,
    params: dict[str, object],
) -> None:
    authorities = _build_all_static()
    factory = build_ordinary_raw_request_context_factory(None, authorities, _execution())

    with pytest.raises(RawRequestContextCompilationError):
        factory(endpoint_name, params)


def test_static_context_factory_rejects_reordered_authority_inventory() -> None:
    authorities = _build_all_static()

    with pytest.raises(
        RawRequestContextCompilationError,
        match="static authorities are invalid",
    ):
        build_ordinary_raw_request_context_factory(
            None,
            tuple(reversed(authorities)),
            _execution(),
        )
