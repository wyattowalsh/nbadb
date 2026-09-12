from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.contracts.temporal_availability_contract import (
    EXPECTED_LEGACY_RULE_COUNT,
    EXPECTED_ROUTE_SCOPE_COUNT,
    TemporalAuthorityBindingsV1,
    TemporalAvailabilityEvidenceV1,
    TemporalAvailabilityLedgerError,
    TemporalAvailabilityStateV1,
    TemporalAvailabilityUnitV1,
    TemporalEvidenceBasisV1,
    TemporalEvidenceStateV1,
    TemporalRevalidationPolicyV1,
    compile_temporal_availability_evidence_ledger_v1,
    temporal_availability_contract_bundle,
    temporal_probe_plan,
    validate_temporal_availability_contract_bundle,
    validate_temporal_availability_evidence_ledger_v1,
    validate_temporal_probe_plan,
)
from nbadb.orchestrate.extraction_contract import FULL_EXTRACTION_SUPPORT_RULES


def test_temporal_contract_has_exact_route_and_legacy_rule_census() -> None:
    bundle = temporal_availability_contract_bundle()
    routes = staging_route_contract_bundle()

    assert len(bundle.scopes) == EXPECTED_ROUTE_SCOPE_COUNT == len(routes.routes) == 438
    assert (
        len(bundle.source_rules)
        == EXPECTED_LEGACY_RULE_COUNT
        == len(FULL_EXTRACTION_SUPPORT_RULES)
        == 149
    )
    assert bundle.projected_interval_count == 340
    assert [scope.route_id for scope in bundle.scopes] == [
        route.route_id for route in routes.routes
    ]
    assert set(bundle.by_route_id) == {route.route_id for route in routes.routes}


def test_temporal_contract_never_promotes_planner_policy_to_availability() -> None:
    bundle = temporal_availability_contract_bundle()

    assert bundle.planner_start_basis_counts == (
        ("fallback_attempt_unverified", EXPECTED_ROUTE_SCOPE_COUNT),
    )
    assert all(scope.planner_start_season == 1946 for scope in bundle.scopes)
    assert all(scope.availability_state == "unknown" for scope in bundle.scopes)
    assert all(scope.sink_ready for scope in bundle.scopes)
    assert all(scope.revalidation_required for scope in bundle.scopes)
    assert bundle.model_green is False


def test_every_legacy_rule_is_bounded_blocked_evidence_not_unavailability() -> None:
    bundle = temporal_availability_contract_bundle()
    referenced = {
        interval.rule_id for scope in bundle.scopes for interval in scope.evidence_intervals
    }

    assert referenced == {rule.rule_id for rule in bundle.source_rules}
    assert bundle.evidence_state_counts == (("contract_blocked", 149),)
    assert all(
        rule.evidence_disposition == "legacy_bounded_rule_not_availability"
        for rule in bundle.source_rules
    )
    assert all(len(rule.evidence_sha256) == 64 for rule in bundle.source_rules)
    assert all(rule.revalidation_command for rule in bundle.source_rules)


def test_noncontiguous_win_probability_gap_remains_noncontiguous() -> None:
    bundle = temporal_availability_contract_bundle()
    scope = bundle.by_route_id["win_probability:stg_win_probability:0"]

    assert [
        (interval.season_start, interval.season_end) for interval in scope.evidence_intervals
    ] == [(1946, 1946), (1949, 1950)]


def test_temporal_scope_binds_exact_provider_result_parameter_and_season_type() -> None:
    bundle = temporal_availability_contract_bundle()
    route = staging_route_contract_bundle().by_route_id["video_details:stg_video_details:0"]
    scope = bundle.by_route_id[route.route_id]

    assert scope.provider_authority_sha256 == route.provider_authority_sha256
    assert scope.provider_endpoint_id == route.provider_endpoint_id
    assert scope.provider_result_set_name == route.provider_result_set_name
    assert scope.provider_result_set_ordinal == route.provider_result_set_ordinal
    assert scope.provider_required_parameters == route.provider_required_parameters
    assert scope.provider_optional_parameters == route.provider_optional_parameters
    assert scope.param_pattern == scope.entity_scope == scope.workload_scope == "player_team_season"
    assert scope.supported_season_types == route.supported_season_types
    assert scope.season_type_capability == route.season_type_capability
    assert [(item.season_start, item.season_end) for item in scope.evidence_intervals] == [
        (1946, 2003)
    ]


def test_temporal_compilation_is_deterministic_and_deeply_immutable() -> None:
    first = temporal_availability_contract_bundle()
    second = temporal_availability_contract_bundle()

    assert first is second
    assert first.digest == second.digest
    assert first.to_dict() == second.to_dict()
    with pytest.raises(TypeError):
        first.by_route_id["new"] = first.scopes[0]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        first.scopes[0].availability_state = "supported"  # type: ignore[misc]


def test_temporal_validator_fails_closed_on_source_or_digest_drift() -> None:
    bundle = temporal_availability_contract_bundle()

    with pytest.raises(ValueError, match="digest"):
        validate_temporal_availability_contract_bundle(replace(bundle, digest="0" * 64))
    changed_scope = replace(bundle.scopes[0], planner_start_season=1947)
    changed = replace(bundle, scopes=(changed_scope, *bundle.scopes[1:]))
    with pytest.raises(ValueError):
        validate_temporal_availability_contract_bundle(changed)


def test_probe_plan_is_bounded_no_network_proposal_for_every_route() -> None:
    plan = temporal_probe_plan(target_season_start=2025)

    assert len(plan.units) == EXPECTED_ROUTE_SCOPE_COUNT
    assert plan.execution_authorized is False
    assert max(len(unit.points) for unit in plan.units) <= 20
    assert all(unit.points for unit in plan.units)
    assert "inconclusive_transient" in plan.allowed_observation_states
    assert plan == temporal_probe_plan(target_season_start=2025)


def test_probe_plan_preserves_discontinuities_and_requires_workload_binding() -> None:
    plan = temporal_probe_plan(target_season_start=2025)
    win_probability = next(
        unit for unit in plan.units if unit.route_id == "win_probability:stg_win_probability:0"
    )
    video = next(
        unit for unit in plan.units if unit.route_id == "video_details:stg_video_details:0"
    )

    assert [point.season_start for point in win_probability.points] == [
        1946,
        1947,
        1949,
        1950,
        1951,
        2025,
    ]
    assert video.binding_state == "verified_workload_binding_required"
    assert video.points[-1].season_start == 2025


def test_probe_plan_rejects_parent_or_execution_drift() -> None:
    plan = temporal_probe_plan(target_season_start=2025)

    with pytest.raises(ValueError, match="digest"):
        validate_temporal_probe_plan(replace(plan, digest="0" * 64))
    with pytest.raises(ValueError, match="predates"):
        temporal_probe_plan(target_season_start=1945)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _authority(*, suffix: str = "primary") -> TemporalAuthorityBindingsV1:
    return TemporalAuthorityBindingsV1(
        authority_generation_sha256=_sha(f"authority-generation-{suffix}"),
        request_universe_generation_sha256=_sha(f"request-universe-{suffix}"),
        request_universe_terminal_receipt_sha256=_sha(f"request-universe-terminal-{suffix}"),
        request_universe_independent_proof_sha256=_sha(f"request-universe-proof-{suffix}"),
        checkpoint_transaction_sha256=_sha(f"checkpoint-transaction-{suffix}"),
        checkpoint_database_sha256=_sha(f"checkpoint-database-{suffix}"),
        checkpoint_w2_authority_sha256=_sha(f"checkpoint-w2-{suffix}"),
    )


def _unit(
    authority: TemporalAuthorityBindingsV1,
    *,
    season_start: int,
    season_end: int | None = None,
    field_occurrence_id: str = "field:league_game_log:0:GAME_ID:0",
) -> TemporalAvailabilityUnitV1:
    return TemporalAvailabilityUnitV1.build(
        authority=authority,
        route_id="league_game_log:stg_league_game_log:0",
        provider_endpoint_id="stats:leaguegamelog.LeagueGameLog",
        provider_result_set_name="LeagueGameLog",
        provider_result_set_ordinal=0,
        request_scope_sha256=_sha("request-scope"),
        competition_identity_sha256=_sha("competition:nba"),
        season_type_identity_sha256=_sha("season-type:regular-season"),
        season_type="Regular Season",
        field_occurrence_id=field_occurrence_id,
        provider_field="GAME_ID",
        field_occurrence_ordinal=0,
        season_start=season_start,
        season_end=season_start if season_end is None else season_end,
    )


def _policy(
    *,
    as_of_date: date = date(2026, 8, 31),
    historical_max_age_days: int = 30,
    current_max_age_days: int = 2,
    unavailable_max_age_days: int = 30,
) -> TemporalRevalidationPolicyV1:
    return TemporalRevalidationPolicyV1(
        policy_id="daily-current-historical-monthly-v1",
        as_of_date=as_of_date,
        current_window_start_season=2025,
        historical_max_age_days=historical_max_age_days,
        current_max_age_days=current_max_age_days,
        unavailable_max_age_days=unavailable_max_age_days,
    )


def _evidence(
    unit: TemporalAvailabilityUnitV1,
    *,
    state: TemporalEvidenceStateV1,
    basis: TemporalEvidenceBasisV1,
    observed_on: date = date(2026, 8, 30),
) -> TemporalAvailabilityEvidenceV1:
    return TemporalAvailabilityEvidenceV1.build(
        unit=unit,
        state=state,
        basis=basis,
        observed_on=observed_on,
        evidence_authority_sha256=_sha(f"evidence:{unit.unit_id}:{state.value}"),
    )


def test_final_temporal_ledger_preserves_no_evidence_as_explicit_red() -> None:
    authority = _authority()
    units = (_unit(authority, season_start=2000), _unit(authority, season_start=2001))

    ledger = compile_temporal_availability_evidence_ledger_v1(
        authority=authority,
        required_units=units,
        revalidation_policy=_policy(),
    )

    assert ledger.model_green is False
    assert [interval.state for interval in ledger.intervals] == [
        TemporalAvailabilityStateV1.EVIDENCE_INSUFFICIENT,
        TemporalAvailabilityStateV1.EVIDENCE_INSUFFICIENT,
    ]
    assert dict(ledger.blocker_counts) == {
        "evidence_insufficient": 2,
        "required_unit_evidence_missing": 2,
        "revalidation_required": 2,
    }
    assert ledger.internal_gaps == ()
    assert ledger == compile_temporal_availability_evidence_ledger_v1(
        authority=authority,
        required_units=tuple(reversed(units)),
        revalidation_policy=_policy(),
    )


def test_final_temporal_ledger_distinguishes_every_terminal_state() -> None:
    authority = _authority()
    units = tuple(_unit(authority, season_start=2000 + index) for index in range(7))
    state_and_basis = (
        (
            TemporalEvidenceStateV1.UPSTREAM_UNAVAILABLE,
            TemporalEvidenceBasisV1.EXACT_UPSTREAM_UNAVAILABLE_AUTHORITY,
        ),
        (
            TemporalEvidenceStateV1.NONAPPLICABLE,
            TemporalEvidenceBasisV1.EXACT_NONAPPLICABILITY_AUTHORITY,
        ),
        (
            TemporalEvidenceStateV1.RESULT_MISSING,
            TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
        ),
        (
            TemporalEvidenceStateV1.FIELD_MISSING,
            TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
        ),
        (
            TemporalEvidenceStateV1.NULL,
            TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
        ),
        (
            TemporalEvidenceStateV1.PRESENT_EMPTY,
            TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
        ),
        (
            TemporalEvidenceStateV1.POPULATED,
            TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
        ),
    )
    evidence = tuple(
        _evidence(unit, state=state, basis=basis)
        for unit, (state, basis) in zip(units, state_and_basis, strict=True)
    )

    ledger = compile_temporal_availability_evidence_ledger_v1(
        authority=authority,
        required_units=units,
        evidence=tuple(reversed(evidence)),
        revalidation_policy=_policy(),
    )

    assert ledger.model_green is True
    assert ledger.blocker_counts == ()
    assert [interval.state.value for interval in ledger.intervals] == [
        "nonexistent",
        "nonapplicable",
        "result_missing",
        "field_missing",
        "null",
        "present_empty",
        "populated",
    ]
    assert all(not interval.revalidation_required for interval in ledger.intervals)
    assert len(ledger.digest) == 64


@pytest.mark.parametrize(
    "basis",
    [
        TemporalEvidenceBasisV1.HTTP_404,
        TemporalEvidenceBasisV1.HTTP_429,
        TemporalEvidenceBasisV1.HTTP_5XX,
        TemporalEvidenceBasisV1.TIMEOUT,
        TemporalEvidenceBasisV1.MALFORMED_RESPONSE,
        TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
    ],
)
def test_upstream_unavailable_rejects_nonauthoritative_bases(
    basis: TemporalEvidenceBasisV1,
) -> None:
    unit = _unit(_authority(), season_start=2000)

    with pytest.raises(TemporalAvailabilityLedgerError, match="incompatible"):
        _evidence(
            unit,
            state=TemporalEvidenceStateV1.UPSTREAM_UNAVAILABLE,
            basis=basis,
        )


def test_exact_upstream_unavailable_identity_cannot_be_tampered() -> None:
    unit = _unit(_authority(), season_start=2000)
    evidence = _evidence(
        unit,
        state=TemporalEvidenceStateV1.UPSTREAM_UNAVAILABLE,
        basis=TemporalEvidenceBasisV1.EXACT_UPSTREAM_UNAVAILABLE_AUTHORITY,
    )

    with pytest.raises(TemporalAvailabilityLedgerError, match="exact evidence identity"):
        replace(evidence, upstream_unavailable_identity_sha256=_sha("foreign"))


def test_transport_and_present_empty_evidence_remain_distinct() -> None:
    authority = _authority()
    first = _unit(authority, season_start=2000)
    second = _unit(authority, season_start=2001)
    timeout = _evidence(
        first,
        state=TemporalEvidenceStateV1.EVIDENCE_INSUFFICIENT,
        basis=TemporalEvidenceBasisV1.TIMEOUT,
    )
    present_empty = _evidence(
        second,
        state=TemporalEvidenceStateV1.PRESENT_EMPTY,
        basis=TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
    )

    ledger = compile_temporal_availability_evidence_ledger_v1(
        authority=authority,
        required_units=(first, second),
        evidence=(timeout, present_empty),
        revalidation_policy=_policy(),
    )

    assert ledger.model_green is False
    assert (
        ledger.by_unit_id[first.unit_id].state is TemporalAvailabilityStateV1.EVIDENCE_INSUFFICIENT
    )
    assert ledger.by_unit_id[second.unit_id].state is TemporalAvailabilityStateV1.PRESENT_EMPTY
    assert dict(ledger.blocker_counts)["nonauthoritative_timeout"] == 1


def test_final_temporal_ledger_rejects_extra_duplicate_and_foreign_evidence() -> None:
    authority = _authority()
    unit = _unit(authority, season_start=2000)
    evidence = _evidence(
        unit,
        state=TemporalEvidenceStateV1.POPULATED,
        basis=TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
    )
    foreign_unit = _unit(_authority(suffix="foreign"), season_start=2000)
    foreign_evidence = _evidence(
        foreign_unit,
        state=TemporalEvidenceStateV1.POPULATED,
        basis=TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
    )

    with pytest.raises(TemporalAvailabilityLedgerError, match="duplicate evidence"):
        compile_temporal_availability_evidence_ledger_v1(
            authority=authority,
            required_units=(unit,),
            evidence=(evidence, evidence),
            revalidation_policy=_policy(),
        )
    with pytest.raises(TemporalAvailabilityLedgerError, match="extra or foreign"):
        compile_temporal_availability_evidence_ledger_v1(
            authority=authority,
            required_units=(unit,),
            evidence=(foreign_evidence,),
            revalidation_policy=_policy(),
        )
    with pytest.raises(TemporalAvailabilityLedgerError, match="foreign authority"):
        compile_temporal_availability_evidence_ledger_v1(
            authority=authority,
            required_units=(foreign_unit,),
            revalidation_policy=_policy(),
        )


def test_temporal_denominator_rejects_overlap_and_exposes_internal_gaps() -> None:
    authority = _authority()
    overlapping = (
        _unit(authority, season_start=2000, season_end=2001),
        _unit(authority, season_start=2001, season_end=2002),
    )
    with pytest.raises(TemporalAvailabilityLedgerError, match="overlap"):
        compile_temporal_availability_evidence_ledger_v1(
            authority=authority,
            required_units=overlapping,
            revalidation_policy=_policy(),
        )

    first = _unit(authority, season_start=2000)
    third = _unit(authority, season_start=2002)
    evidence = tuple(
        _evidence(
            unit,
            state=TemporalEvidenceStateV1.POPULATED,
            basis=TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
        )
        for unit in (first, third)
    )
    ledger = compile_temporal_availability_evidence_ledger_v1(
        authority=authority,
        required_units=(first, third),
        evidence=evidence,
        revalidation_policy=_policy(),
    )

    assert ledger.model_green is False
    assert [(gap.season_start, gap.season_end) for gap in ledger.internal_gaps] == [(2001, 2001)]
    assert dict(ledger.blocker_counts)["denominator_internal_gap"] == 1


def test_revalidation_policy_blocks_stale_and_future_evidence() -> None:
    authority = _authority()
    unit = _unit(authority, season_start=2025)
    stale = _evidence(
        unit,
        state=TemporalEvidenceStateV1.POPULATED,
        basis=TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
        observed_on=date(2026, 8, 1),
    )
    ledger = compile_temporal_availability_evidence_ledger_v1(
        authority=authority,
        required_units=(unit,),
        evidence=(stale,),
        revalidation_policy=_policy(current_max_age_days=2),
    )
    assert ledger.model_green is False
    assert dict(ledger.blocker_counts) == {"revalidation_required": 1}

    future = _evidence(
        unit,
        state=TemporalEvidenceStateV1.POPULATED,
        basis=TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT,
        observed_on=date(2026, 9, 1),
    )
    with pytest.raises(TemporalAvailabilityLedgerError, match="after the policy"):
        compile_temporal_availability_evidence_ledger_v1(
            authority=authority,
            required_units=(unit,),
            evidence=(future,),
            revalidation_policy=_policy(),
        )


def test_final_temporal_ledger_rejects_empty_denominator_and_digest_drift() -> None:
    authority = _authority()
    with pytest.raises(TemporalAvailabilityLedgerError, match="cannot be empty"):
        compile_temporal_availability_evidence_ledger_v1(
            authority=authority,
            required_units=(),
            revalidation_policy=_policy(),
        )

    unit = _unit(authority, season_start=2000)
    ledger = compile_temporal_availability_evidence_ledger_v1(
        authority=authority,
        required_units=(unit,),
        revalidation_policy=_policy(),
    )
    with pytest.raises(TemporalAvailabilityLedgerError, match="differs"):
        validate_temporal_availability_evidence_ledger_v1(replace(ledger, digest="0" * 64))
    with pytest.raises(TypeError):
        ledger.by_unit_id["foreign"] = ledger.intervals[0]  # type: ignore[index]
