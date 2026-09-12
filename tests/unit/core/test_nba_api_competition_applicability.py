from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from nba_api.live.nba.library.http import NBALiveHTTP
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.core.nba_api_competition_applicability import (
    COMPETITION_APPLICABILITY_RESOURCE,
    CompetitionApplicabilityAuthority,
    NbaApiCompetitionApplicabilityError,
    build_competition_applicability_authority,
    build_pinned_competition_applicability_payload,
    load_pinned_competition_applicability_payload,
    pinned_competition_applicability_authority,
    resolve_competition_probe_eligibility,
    write_pinned_competition_applicability,
)

_EXPECTED_LEAGUES = {"00", "01", "10", "15", "20"}
_NON_TEMPORAL = {
    "CommonPlayerInfo",
    "CommonTeamYears",
    "FranchiseHistory",
    "FranchiseLeaders",
    "GameRotation",
    "PlayerCareerStats",
    "PlayerProfileV2",
}
_GL_PERSON1 = "parameter:stats:GLAlumBoxScoreSimilarityScore:0002:person1_league_id"
_GL_PERSON2 = "parameter:stats:GLAlumBoxScoreSimilarityScore:0005:person2_league_id"


def _resource_path() -> Path:
    return (
        Path(__file__).parents[3]
        / "src"
        / "nbadb"
        / "contracts"
        / COMPETITION_APPLICABILITY_RESOURCE
    )


def _authority() -> CompetitionApplicabilityAuthority:
    return build_competition_applicability_authority()


def test_authority_preserves_555_endpoint_560_axis_and_635_role_denominators() -> None:
    authority = pinned_competition_applicability_authority()
    payload = load_pinned_competition_applicability_payload()

    assert len(authority.existence_intervals) == 5
    assert len(authority.endpoint_cells) == 555
    assert len(authority.parameter_axis_cells) == 560
    assert len(authority.alias_role_cells) == 635
    assert len({item.provider_endpoint_id for item in authority.endpoint_cells}) == 111
    assert len({item.provider_occurrence_id for item in authority.parameter_axis_cells}) == 112
    assert (
        len(
            {
                (item.repo_endpoint_name, item.provider_occurrence_id)
                for item in authority.alias_role_cells
            }
        )
        == 127
    )
    assert payload["typed_declared_axis_cell_count"] == 1750
    assert payload == build_pinned_competition_applicability_payload()


def test_authority_partitions_all_112_axes_by_temporal_shape() -> None:
    authority = _authority()
    shapes = {
        item.provider_occurrence_id: item.temporal_shape for item in authority.parameter_axis_cells
    }

    assert Counter(shapes.values()) == {
        "explicit_season": 96,
        "participant_season_axis": 2,
        "season_type_only": 4,
        "date_or_date_range_only": 3,
        "no_temporal_parameter": 7,
    }
    assert len(shapes) == 112


def test_non_temporal_endpoints_are_explicit_and_have_no_synthesized_season_value() -> None:
    authority = _authority()
    observed = {
        item.provider_endpoint_id
        for item in authority.parameter_axis_cells
        if item.temporal_shape == "no_temporal_parameter"
    }

    assert observed == _NON_TEMPORAL
    for endpoint in sorted(observed):
        result = resolve_competition_probe_eligibility(endpoint, "10")
        assert result.native_period is None
        assert result.probe_eligible is True
        assert result.existence_status == "not_applicable_no_effective_period_axis"


def test_existence_intervals_only_gate_probe_eligibility() -> None:
    authority = _authority()
    intervals = {item.league_id: item for item in authority.existence_intervals}

    assert intervals["00"].contains("1946-47")
    assert intervals["00"].contains("2025-26")
    assert not intervals["00"].contains("2026-27")
    assert intervals["10"].contains(1997)
    assert intervals["10"].contains(2026)
    assert intervals["15"].contains(2010)
    assert not intervals["15"].contains(2011)
    assert not intervals["15"].contains(2020)
    assert intervals["20"].contains("2001-02")
    assert all(
        item.endpoint_support_status == "unknown_no_independent_endpoint_specific_source"
        for item in authority.endpoint_cells
    )


def test_provider_availability_remains_probe_required_or_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("applicability authority attempted provider I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", _network_forbidden)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", _network_forbidden)
    authority = pinned_competition_applicability_authority()

    assert {
        item.provider_availability_status
        for item in (
            *authority.endpoint_cells,
            *authority.parameter_axis_cells,
            *authority.alias_role_cells,
        )
    } == {"unknown"}
    assert {
        item.probe_disposition
        for item in (
            *authority.endpoint_cells,
            *authority.parameter_axis_cells,
            *authority.alias_role_cells,
        )
    } == {"probe_required"}


def test_gl_alum_participant_axes_and_temporal_companions_remain_distinct() -> None:
    authority = _authority()
    axes = {
        item.provider_occurrence_id: item
        for item in authority.parameter_axis_cells
        if item.provider_endpoint_id == "GLAlumBoxScoreSimilarityScore" and item.league_id == "00"
    }

    assert set(axes) == {_GL_PERSON1, _GL_PERSON2}
    assert axes[_GL_PERSON1].constructor_name == "person1_league_id"
    assert axes[_GL_PERSON1].wire_name == "Person1LeagueId"
    assert axes[_GL_PERSON1].temporal_companion_occurrence_ids == (
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0003:person1_season_year",
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0004:person1_season_type",
    )
    assert axes[_GL_PERSON2].constructor_name == "person2_league_id"
    assert axes[_GL_PERSON2].wire_name == "Person2LeagueId"
    assert axes[_GL_PERSON2].temporal_companion_occurrence_ids == (
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0006:person2_season_year",
        "parameter:stats:GLAlumBoxScoreSimilarityScore:0007:person2_season_type",
    )
    assert all(
        item.participant_axis_binding == "same_person_temporal_companions"
        and item.joint_cartesian_authority is False
        for item in axes.values()
    )


def test_alias_projection_preserves_127_roles_and_635_cells() -> None:
    authority = _authority()
    roles = {
        (item.repo_endpoint_name, item.provider_occurrence_id)
        for item in authority.alias_role_cells
    }

    assert len(roles) == 127
    assert len(authority.alias_role_cells) == 635
    assert all(
        {item.league_id for item in authority.alias_role_cells if item.repo_endpoint_name == alias}
        == _EXPECTED_LEAGUES
        for alias in {item.repo_endpoint_name for item in authority.alias_role_cells}
    )


def test_competition_applicability_resource_is_generated_without_drift(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / COMPETITION_APPLICABILITY_RESOURCE
    assert write_pinned_competition_applicability(candidate) is False
    assert write_pinned_competition_applicability(candidate) is True
    assert write_pinned_competition_applicability(candidate, check=True) is True
    assert candidate.read_bytes() == _resource_path().read_bytes()
    assert (
        hashlib.sha256(candidate.read_bytes()).hexdigest()
        == hashlib.sha256(_resource_path().read_bytes()).hexdigest()
    )


@pytest.mark.parametrize("denominator", ["endpoint", "axis", "alias"])
@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_applicability_rejects_missing_extra_or_duplicate_endpoint_axis_or_role_cell(
    denominator: str,
    mutation: str,
) -> None:
    authority = _authority()
    field = {
        "endpoint": "endpoint_cells",
        "axis": "parameter_axis_cells",
        "alias": "alias_role_cells",
    }[denominator]
    rows = list(getattr(authority, field))
    if mutation == "missing":
        rows.pop()
    elif mutation == "extra":
        rows.append(rows[-1])
        rows.append(rows[-1])
    else:
        rows[-1] = rows[0]

    with pytest.raises(
        NbaApiCompetitionApplicabilityError,
        match="denominator|duplicate",
    ):
        replace(authority, **{field: tuple(rows)})


def test_applicability_rejects_unclassified_or_evidence_free_unsupported_cell() -> None:
    cell = _authority().endpoint_cells[0]
    with pytest.raises(NbaApiCompetitionApplicabilityError, match="unsupported/supported"):
        replace(cell, endpoint_support_status="unsupported")


def test_applicability_rejects_history_evidence_as_endpoint_support() -> None:
    cell = _authority().parameter_axis_cells[0]
    with pytest.raises(NbaApiCompetitionApplicabilityError, match="history"):
        replace(cell, endpoint_support_evidence_kind="competition_existence_history")


def test_applicability_rejects_endpoint_support_as_existence_evidence() -> None:
    interval = _authority().existence_intervals[0]
    with pytest.raises(NbaApiCompetitionApplicabilityError, match="existence evidence"):
        replace(interval, evidence_scope="endpoint_support")


def test_applicability_rejects_provider_available_or_upstream_unavailable_claim() -> None:
    cell = _authority().alias_role_cells[0]
    for field, value, match in (
        ("provider_availability_status", "available", "provider availability"),
        ("probe_disposition", "upstream_unavailable", "probe disposition"),
    ):
        with pytest.raises(NbaApiCompetitionApplicabilityError, match=match):
            replace(cell, **{field: value})

    league_game_log_occurrence = "parameter:stats:LeagueGameLog:0002:league_id"
    gl_person1 = resolve_competition_probe_eligibility(
        "GLAlumBoxScoreSimilarityScore",
        "00",
        "2025-26",
        provider_occurrence_id=_GL_PERSON1,
        repo_endpoint_name="gl_alum_box_score_similarity_score",
    )
    valid_controls = (
        resolve_competition_probe_eligibility("LeagueGameLog", "00", "2025-26"),
        resolve_competition_probe_eligibility("LeagueGameLog", "00", "2026-27"),
        resolve_competition_probe_eligibility("LeagueGameLog", "00"),
        resolve_competition_probe_eligibility("CommonPlayerInfo", "10"),
        resolve_competition_probe_eligibility("AllTimeLeadersGrids", "20"),
        resolve_competition_probe_eligibility("LeagueGameLog", "10", 2026),
        resolve_competition_probe_eligibility("LeagueGameLog", "15", 2010),
        resolve_competition_probe_eligibility("LeagueGameLog", "15", 2020),
        gl_person1,
        resolve_competition_probe_eligibility(
            "GLAlumBoxScoreSimilarityScore",
            "00",
            "2025-26",
            provider_occurrence_id=_GL_PERSON2,
            repo_endpoint_name="gl_alum_box_score_similarity_score",
        ),
    )
    assert all(replace(result) == result for result in valid_controls)

    confirmed = valid_controls[0]
    planned = valid_controls[1]
    missing = valid_controls[2]
    non_temporal = valid_controls[3]
    season_type_only = valid_controls[4]
    wnba = valid_controls[5]
    summer_gap = valid_controls[7]
    mutations = (
        (confirmed, {"endpoint_support_status": "supported"}, "endpoint support"),
        (confirmed, {"endpoint_support_status": "unsupported"}, "endpoint support"),
        (confirmed, {"provider_availability_status": "available"}, "provider availability"),
        (
            confirmed,
            {"provider_availability_status": "upstream_unavailable"},
            "provider availability",
        ),
        (confirmed, {"provider_availability_status": "terminal"}, "provider availability"),
        (confirmed, {"probe_disposition": "upstream_unavailable"}, "inconsistent"),
        (confirmed, {"probe_disposition": "terminal"}, "inconsistent"),
        (confirmed, {"existence_status": "terminal"}, "inconsistent"),
        (confirmed, {"probe_eligible": 1}, "exact boolean"),
        (confirmed, {"probe_eligible": False}, "inconsistent"),
        (confirmed, {"probe_disposition": "unknown"}, "inconsistent"),
        (planned, {"probe_eligible": True}, "inconsistent"),
        (missing, {"probe_disposition": "probe_required"}, "inconsistent"),
        (non_temporal, {"probe_eligible": False}, "inconsistent"),
        (confirmed, {"provider_endpoint_id": "NotAnEndpoint"}, "exact endpoint"),
        (
            gl_person1,
            {"provider_occurrence_id": league_game_log_occurrence},
            "exact endpoint",
        ),
        (confirmed, {"league_id": "99"}, "exact endpoint"),
        (confirmed, {"symbol": "wnba"}, "identity differs"),
        (confirmed, {"temporal_shape": "season_type_only"}, "identity differs"),
        (confirmed, {"native_period_type": "calendar_year"}, "identity differs"),
        (confirmed, {"repo_endpoint_name": "common_player_info"}, "repo alias"),
        (confirmed, {"native_period": 2025}, "season-label"),
        (confirmed, {"native_period": None}, "inconsistent"),
        (wnba, {"native_period": "2025-26"}, "native integer year"),
        (wnba, {"native_period": True}, "native integer year"),
        (non_temporal, {"native_period": 2026}, "inconsistent"),
        (season_type_only, {"native_period": "2025-26"}, "inconsistent"),
        (summer_gap, {"probe_eligible": True}, "inconsistent"),
        (summer_gap, {"existence_status": "confirmed_eligibility"}, "inconsistent"),
    )
    for result, changes, match in mutations:
        with pytest.raises(NbaApiCompetitionApplicabilityError, match=match):
            replace(result, **changes)


@pytest.mark.parametrize("mutation", ["overlapping", "reversed", "unconfirmed"])
def test_applicability_rejects_overlapping_reversed_or_unconfirmed_existence_interval(
    mutation: str,
) -> None:
    authority = _authority()
    first = authority.existence_intervals[0]
    if mutation == "reversed":
        with pytest.raises(NbaApiCompetitionApplicabilityError, match="reversed"):
            replace(first, start="2025-26", end="1946-47")
    elif mutation == "unconfirmed":
        with pytest.raises(NbaApiCompetitionApplicabilityError, match="confirmed"):
            replace(first, status="planned_future_not_confirmed_eligibility")
    else:
        duplicate = replace(authority.existence_intervals[1], league_id="00", symbol="nba")
        rows = tuple(
            sorted((*authority.existence_intervals[:-1], duplicate), key=lambda x: x.league_id)
        )
        with pytest.raises(NbaApiCompetitionApplicabilityError, match="missing or duplicate"):
            replace(authority, existence_intervals=rows)


def test_applicability_rejects_missing_revalidation_metadata() -> None:
    authority = _authority()
    with pytest.raises(NbaApiCompetitionApplicabilityError, match="revalidation"):
        replace(authority, revalidation_policy_id="")


def test_applicability_rejects_nba_season_string_for_non_nba_competition() -> None:
    with pytest.raises(NbaApiCompetitionApplicabilityError, match="native integer year"):
        resolve_competition_probe_eligibility("LeagueGameLog", "10", "2025-26")
    with pytest.raises(NbaApiCompetitionApplicabilityError, match="native integer year"):
        resolve_competition_probe_eligibility("LeagueGameLog", "15", "2025-26")


@pytest.mark.parametrize("mutation", ["axis_collapse", "joint_cartesian"])
def test_applicability_rejects_gl_alum_axis_collapse_or_joint_cartesian_authority(
    mutation: str,
) -> None:
    cell = next(
        item
        for item in _authority().parameter_axis_cells
        if item.provider_occurrence_id == _GL_PERSON2 and item.league_id == "00"
    )
    with pytest.raises(
        NbaApiCompetitionApplicabilityError,
        match="GLAlum|Cartesian|constructor/wire|axis/role",
    ):
        if mutation == "axis_collapse":
            replace(cell, constructor_name="person1_league_id")
        else:
            replace(cell, joint_cartesian_authority=True)


def test_authority_changes_when_existence_boundary_or_source_digest_changes() -> None:
    authority = _authority()
    nba = authority.existence_intervals[0]
    changed_interval = replace(
        nba,
        end="2024-25",
        planned_future_periods=("2025-26", "2026-27"),
    )
    changed_intervals = (changed_interval, *authority.existence_intervals[1:])
    boundary_changed = replace(authority, existence_intervals=changed_intervals)
    source_changed = replace(authority, competition_existence_resource_sha256="0" * 64)

    assert boundary_changed.authority_sha256 != authority.authority_sha256
    assert source_changed.authority_sha256 != authority.authority_sha256


def test_resolver_returns_probe_eligible_only_inside_source_backed_existence() -> None:
    inside = resolve_competition_probe_eligibility(
        "LeagueGameLog",
        "00",
        "2025-26",
    )
    planned = resolve_competition_probe_eligibility(
        "LeagueGameLog",
        "00",
        "2026-27",
    )
    summer_gap = resolve_competition_probe_eligibility("LeagueGameLog", "15", 2020)

    assert (inside.probe_eligible, inside.probe_disposition) == (True, "probe_required")
    assert (planned.probe_eligible, planned.probe_disposition) == (False, "unknown")
    assert (summer_gap.probe_eligible, summer_gap.probe_disposition) == (False, "unknown")


def test_resolver_keeps_provider_availability_unknown() -> None:
    result = resolve_competition_probe_eligibility("LeagueGameLog", "20", "2025-26")

    assert result.probe_eligible is True
    assert result.endpoint_support_status == "unknown_no_independent_endpoint_specific_source"
    assert result.provider_availability_status == "unknown"


def test_resolver_returns_non_temporal_scope_without_season_value() -> None:
    result = resolve_competition_probe_eligibility("CommonPlayerInfo", "10")

    assert result.temporal_shape == "no_temporal_parameter"
    assert result.native_period is None
    assert result.probe_eligible is True
    with pytest.raises(NbaApiCompetitionApplicabilityError, match="no explicit"):
        resolve_competition_probe_eligibility("CommonPlayerInfo", "10", 2026)
