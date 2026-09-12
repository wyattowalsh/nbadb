from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from nba_api.live.nba.library.http import NBALiveHTTP
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.core.nba_api_competition_occurrences import (
    COMPETITION_OCCURRENCE_RESOURCE,
    CompetitionOccurrenceAuthority,
    NbaApiCompetitionOccurrenceError,
    build_competition_occurrence_authority,
    build_pinned_competition_occurrence_payload,
    load_pinned_competition_occurrence_payload,
    pinned_competition_occurrence_authority,
    write_pinned_competition_occurrences,
)
from nbadb.core.nba_api_competition_occurrences_verifier import (
    verify_pinned_competition_occurrence_authority,
)

_PACKAGE_CENSUS_SHA256 = "25fa1eb874799d6f68ead21c78da1232668f29985b0a8cc8e1340c14cabddbb9"
_REPO_ALIAS_CENSUS_SHA256 = "02b0c5df1706529713d13251d8d30804989e622e74b71013da2dbf2fa5684652"
_REPO_SOURCE_CENSUS_SHA256 = "d51d1b9271389314baceec3b965dfa667fc2ce5f5a23b534650e5e3fc6cd09fb"


def _resource_path() -> Path:
    return (
        Path(__file__).parents[3] / "src" / "nbadb" / "contracts" / COMPETITION_OCCURRENCE_RESOURCE
    )


def _clear_caches() -> None:
    build_competition_occurrence_authority.cache_clear()
    pinned_competition_occurrence_authority.cache_clear()
    verify_pinned_competition_occurrence_authority.cache_clear()


@pytest.fixture(autouse=True)
def _isolated_occurrence_caches() -> None:
    _clear_caches()
    yield
    _clear_caches()


def test_occurrence_authority_enumerates_exact_package_denominator() -> None:
    authority = pinned_competition_occurrence_authority()
    payload = load_pinned_competition_occurrence_payload()

    assert len(authority.package_occurrences) == 112
    assert authority.package_endpoint_count == 111
    assert Counter(item.constructor_name for item in authority.package_occurrences) == {
        "league_id": 63,
        "league_id_nullable": 47,
        "person1_league_id": 1,
        "person2_league_id": 1,
    }
    assert Counter(item.wire_name for item in authority.package_occurrences) == {
        "LeagueID": 110,
        "Person1LeagueId": 1,
        "Person2LeagueId": 1,
    }
    assert authority.package_planning_census_sha256 == _PACKAGE_CENSUS_SHA256
    assert payload == build_pinned_competition_occurrence_payload()
    assert payload["package_occurrence_count"] == 112
    assert payload["package_endpoint_count"] == 111


def test_occurrence_authority_enumerates_exact_registered_extractor_alias_denominator() -> None:
    authority = pinned_competition_occurrence_authority()

    assert len(authority.repo_aliases) == 126
    assert len(authority.repo_source_inventory) == 26
    assert authority.repo_alias_planning_census_sha256 == _REPO_ALIAS_CENSUS_SHA256
    assert authority.repo_source_inventory_sha256 == _REPO_SOURCE_CENSUS_SHA256
    assert len({item.repo_endpoint_name for item in authority.repo_aliases}) == 126
    assert (
        sum(len(item.parameter_roles) for item in authority.repo_aliases)
        == authority.projected_role_count
    )


def test_occurrence_authority_classifies_all_spellings_defaults_nullable_forms_and_roles() -> None:
    authority = pinned_competition_occurrence_authority()
    occurrences = authority.package_occurrences

    assert {item.default for item in occurrences} == {"00"}
    assert {item.constructor_name: item.default_expression for item in occurrences} == {
        "league_id": "LeagueID.default",
        "league_id_nullable": "LeagueIDNullable.default",
        "person1_league_id": "LeagueID.default",
        "person2_league_id": "LeagueID.default",
    }
    assert all(
        item.nullable == (item.constructor_name == "league_id_nullable") for item in occurrences
    )
    assert all(item.has_default and item.semantic_role == "scope_axis" for item in occurrences)
    participant_roles = [
        role
        for alias in authority.repo_aliases
        for role in alias.parameter_roles
        if role.constructor_name.startswith("person")
    ]
    assert [role.constructor_name for role in participant_roles] == [
        "person1_league_id",
        "person2_league_id",
    ]
    assert all(
        role.forwarding_behavior == "exact_constructor_name_forwarding"
        and role.output_behavior == "participant_role_only_no_primary_league_id_injection"
        for role in participant_roles
    )


def test_occurrence_authority_projects_126_aliases_to_127_roles_without_loss() -> None:
    authority = pinned_competition_occurrence_authority()
    occurrences = {item.occurrence_id for item in authority.package_occurrences}
    roles = [role for alias in authority.repo_aliases for role in alias.parameter_roles]
    gl_alum = next(
        alias
        for alias in authority.repo_aliases
        if alias.repo_endpoint_name == "gl_alum_box_score_similarity_score"
    )

    assert authority.projected_role_count == 127
    assert Counter(role.constructor_name for role in roles) == {
        "league_id": 69,
        "league_id_nullable": 56,
        "person1_league_id": 1,
        "person2_league_id": 1,
    }
    assert all(role.provider_occurrence_id in occurrences for role in roles)
    assert [role.constructor_name for role in gl_alum.parameter_roles] == [
        "person1_league_id",
        "person2_league_id",
    ]


def test_independent_occurrence_authority_matches_primary() -> None:
    authority = pinned_competition_occurrence_authority()
    proof = verify_pinned_competition_occurrence_authority()
    payload = load_pinned_competition_occurrence_payload()

    assert proof.authority_sha256 == authority.authority_sha256
    assert proof.package_occurrences_sha256 == authority.package_occurrences_sha256
    assert proof.repo_aliases_sha256 == authority.repo_aliases_sha256
    assert proof.package_planning_census_sha256 == _PACKAGE_CENSUS_SHA256
    assert proof.repo_alias_planning_census_sha256 == _REPO_ALIAS_CENSUS_SHA256
    assert proof.repo_source_inventory_sha256 == _REPO_SOURCE_CENSUS_SHA256
    assert proof.checked_payload_sha256 == payload["payload_sha256"]
    assert (proof.package_occurrence_count, proof.repo_alias_count) == (112, 126)
    assert proof.projected_role_count == 127


def test_occurrence_authority_changes_when_package_occurrence_changes() -> None:
    authority = build_competition_occurrence_authority()
    first = authority.package_occurrences[0]
    changed_occurrences = tuple(
        sorted(
            (replace(first, default="10"), *authority.package_occurrences[1:]),
            key=lambda item: item.occurrence_id,
        )
    )
    changed = replace(authority, package_occurrences=changed_occurrences)

    assert changed.package_occurrences_sha256 != authority.package_occurrences_sha256
    assert changed.authority_sha256 != authority.authority_sha256


def test_occurrence_authority_rejects_unregistered_or_unmapped_extractor_alias() -> None:
    authority = build_competition_occurrence_authority()
    first_alias = authority.repo_aliases[0]
    unregistered = replace(first_alias, repo_endpoint_name="unregistered_competition_alias")
    with pytest.raises(NbaApiCompetitionOccurrenceError, match="not registered"):
        CompetitionOccurrenceAuthority(
            distribution_record_authority_sha256=(authority.distribution_record_authority_sha256),
            request_surface_resource_sha256=authority.request_surface_resource_sha256,
            request_surface_payload_sha256=authority.request_surface_payload_sha256,
            request_surface_sha256=authority.request_surface_sha256,
            package_planning_census_sha256=authority.package_planning_census_sha256,
            package_occurrences=authority.package_occurrences,
            repo_alias_planning_census_sha256=(authority.repo_alias_planning_census_sha256),
            repo_aliases=tuple(
                sorted(
                    (unregistered, *authority.repo_aliases[1:]),
                    key=lambda item: item.repo_endpoint_name,
                )
            ),
            repo_source_inventory=authority.repo_source_inventory,
        )

    first_role = first_alias.parameter_roles[0]
    unmapped_id = "parameter:stats:ForeignEndpoint:0000:league_id"
    unmapped = replace(
        first_alias,
        provider_occurrence_ids=(unmapped_id,),
        parameter_roles=(replace(first_role, provider_occurrence_id=unmapped_id),),
    )
    with pytest.raises(NbaApiCompetitionOccurrenceError, match="unmapped"):
        replace(
            authority,
            repo_aliases=tuple(
                sorted(
                    (unmapped, *authority.repo_aliases[1:]),
                    key=lambda item: item.repo_endpoint_name,
                )
            ),
        )


def test_competition_occurrence_resource_is_generated_without_drift(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / COMPETITION_OCCURRENCE_RESOURCE
    assert write_pinned_competition_occurrences(candidate) is False
    assert write_pinned_competition_occurrences(candidate) is True
    assert write_pinned_competition_occurrences(candidate, check=True) is True
    assert candidate.read_bytes() == _resource_path().read_bytes()
    assert (
        hashlib.sha256(candidate.read_bytes()).hexdigest()
        == hashlib.sha256(_resource_path().read_bytes()).hexdigest()
    )


def test_occurrence_authorities_never_send_provider_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("competition occurrence authority attempted provider I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", _network_forbidden)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", _network_forbidden)
    assert pinned_competition_occurrence_authority().package_endpoint_count == 111


def test_competition_occurrence_resource_is_canonical_json() -> None:
    raw = _resource_path().read_bytes()
    payload = json.loads(raw)
    assert raw == (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        + b"\n"
    )
