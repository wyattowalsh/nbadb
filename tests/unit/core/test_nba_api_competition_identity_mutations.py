from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from nbadb.core.nba_api_competition_identity import (
    CompetitionIdentityRequirement,
    CompetitionQualifiedRequest,
    NbaApiCompetitionIdentityError,
    bind_explicit_competition_request,
    bind_static_competition_source,
    compile_competition_identity_requirements,
    qualify_entity_identity,
)
from nbadb.core.nba_api_competition_identity_verifier import (
    verify_pinned_competition_identity_authority,
)
from nbadb.core.nba_api_request_surface import (
    CanonicalProviderRequest,
    materialize_provider_request,
    pinned_request_surface_authority,
)

_RESOURCE = Path("src/nbadb/contracts/nba_api_competition_identity_v1_11_4.json")
_COMPETITION_DOMAIN = "nbadb.nba-api.competition-scope.v1"
_ENTITY_DOMAIN = "nbadb.nba-api.entity.v1"
_SOURCE_REQUEST_DOMAIN = "nbadb.nba-api.source-request.v1"
_LEAGUES = ("00", "01", "10", "15", "20")
_NON_NBA_LEAGUES = ("01", "10", "15", "20")
_ENTITY_VECTORS: tuple[tuple[str, str, str | int], ...] = (
    ("game", "provider_string", "0022400001"),
    ("team", "provider_integer", 1610612737),
    ("player", "provider_integer", 2544),
    ("season", "provider_string", "2024-25"),
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _requirements() -> tuple[CompetitionIdentityRequirement, ...]:
    return compile_competition_identity_requirements()


def _requirement(
    repo_endpoint_name: str,
    league_id: str,
    *,
    strategy: str | None = None,
    constructor_name: str | None = None,
) -> CompetitionIdentityRequirement:
    matches = [
        item
        for item in _requirements()
        if item.repo_endpoint_name == repo_endpoint_name
        and item.league_id == league_id
        and (strategy is None or item.role_binding.binding_strategy == strategy)
        and (constructor_name is None or item.role_binding.constructor_name == constructor_name)
    ]
    assert len(matches) == 1
    return matches[0]


def _materialize_league_game_log(
    requirement: CompetitionIdentityRequirement,
    *,
    omit_league_id: bool,
) -> CanonicalProviderRequest:
    authority = pinned_request_surface_authority()
    endpoint = authority.endpoint(
        requirement.source_family,  # type: ignore[arg-type]
        requirement.provider_endpoint_id,
    )
    parameters: dict[str, object] = {
        "season": "2024-25",
        "season_type_all_star": "Regular Season",
        "counter": 0,
    }
    constructor_name = requirement.role_binding.constructor_name
    assert constructor_name == "league_id"
    if not omit_league_id:
        parameters[constructor_name] = requirement.league_id
    return materialize_provider_request(
        endpoint,
        parameters,
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )


def _request_body(
    request: CompetitionQualifiedRequest,
    request_kind: str,
) -> dict[str, object]:
    return {
        "domain_separator": _SOURCE_REQUEST_DOMAIN,
        "competition_scope_sha256": request.competition_scope_sha256,
        "requirement_sha256": request.requirement_sha256,
        "role_binding_sha256": request.role_binding_sha256,
        "request_kind": request_kind,
        "source_evidence_sha256": request.source_evidence_sha256,
        "provider_request_sha256": request.provider_request_sha256,
    }


def _payload() -> dict[str, object]:
    return cast("dict[str, object]", json.loads(_RESOURCE.read_text(encoding="utf-8")))


def _mapping(payload: dict[str, object], name: str) -> dict[str, object]:
    return cast("dict[str, object]", payload[name])


def _rows(payload: dict[str, object], name: str) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", payload[name])


def _surface(payload: dict[str, object], name: str) -> dict[str, object]:
    matches = [
        row for row in _rows(payload, "qualified_surface_contracts") if row["surface_name"] == name
    ]
    assert len(matches) == 1
    return matches[0]


def _requirement_row(
    payload: dict[str, object],
    repo_endpoint_name: str,
    league_id: str,
    *,
    strategy: str | None = None,
    constructor_name: str | None = None,
) -> dict[str, object]:
    matches = []
    for row in _rows(payload, "identity_requirements"):
        role = cast("dict[str, object]", row["role_binding"])
        if (
            row["repo_endpoint_name"] == repo_endpoint_name
            and row["league_id"] == league_id
            and (strategy is None or role["binding_strategy"] == strategy)
            and (constructor_name is None or role["constructor_name"] == constructor_name)
        ):
            matches.append(row)
    assert len(matches) == 1
    return matches[0]


def _role(row: dict[str, object]) -> dict[str, object]:
    return cast("dict[str, object]", row["role_binding"])


def _reseal(payload: dict[str, object]) -> bytes:
    for requirement in _rows(payload, "identity_requirements"):
        role = _role(requirement)
        role_body = dict(role)
        role_body.pop("role_binding_sha256", None)
        role["role_binding_sha256"] = _digest(role_body)
        requirement_body = dict(requirement)
        requirement_body.pop("requirement_sha256", None)
        requirement["requirement_sha256"] = _digest(
            {
                "domain_separator": _COMPETITION_DOMAIN,
                "requirement": requirement_body,
            }
        )
    payload["identity_requirements_sha256"] = _digest(payload["identity_requirements"])
    for surface in _rows(payload, "qualified_surface_contracts"):
        surface_body = dict(surface)
        surface_body.pop("surface_contract_sha256", None)
        surface["surface_contract_sha256"] = _digest(surface_body)
    payload["qualified_surface_contracts_sha256"] = _digest(payload["qualified_surface_contracts"])
    authority_body = dict(payload)
    authority_body.pop("authority_sha256", None)
    authority_body.pop("payload_sha256", None)
    payload["authority_sha256"] = _digest(authority_body)
    payload_body = dict(payload)
    payload_body.pop("payload_sha256", None)
    payload["payload_sha256"] = _digest(payload_body)
    return _pretty_bytes(payload)


def _assert_digest_closure(payload: dict[str, object]) -> None:
    for requirement in _rows(payload, "identity_requirements"):
        role = _role(requirement)
        role_body = dict(role)
        role_sha256 = role_body.pop("role_binding_sha256")
        assert role_sha256 == _digest(role_body)
        requirement_body = dict(requirement)
        requirement_sha256 = requirement_body.pop("requirement_sha256")
        assert requirement_sha256 == _digest(
            {
                "domain_separator": _COMPETITION_DOMAIN,
                "requirement": requirement_body,
            }
        )
    assert payload["identity_requirements_sha256"] == _digest(payload["identity_requirements"])
    for surface in _rows(payload, "qualified_surface_contracts"):
        surface_body = dict(surface)
        surface_sha256 = surface_body.pop("surface_contract_sha256")
        assert surface_sha256 == _digest(surface_body)
    assert payload["qualified_surface_contracts_sha256"] == _digest(
        payload["qualified_surface_contracts"]
    )
    authority_body = dict(payload)
    payload_sha256 = authority_body.pop("payload_sha256")
    authority_sha256 = authority_body.pop("authority_sha256")
    assert authority_sha256 == _digest(authority_body)
    payload_body = dict(payload)
    payload_body.pop("payload_sha256")
    assert payload_sha256 == _digest(payload_body)


def _candidate(tmp_path: Path, payload: dict[str, object], name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(_reseal(payload))
    reread = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    _assert_digest_closure(reread)
    assert path.read_bytes() == _pretty_bytes(reread)
    return path


def _assert_rejected(path: Path) -> None:
    candidate = cast(
        "dict[str, object]",
        json.loads(path.read_text(encoding="utf-8")),
    )
    _assert_digest_closure(candidate)
    with pytest.raises(ValueError, match="differs from independent sources"):
        verify_pinned_competition_identity_authority(path)


def _assert_pristine_reseal_is_accepted(tmp_path: Path) -> None:
    path = _candidate(tmp_path, deepcopy(_payload()), "pristine-resealed.json")
    proof = verify_pinned_competition_identity_authority(path)
    assert proof.finding_count == 0
    assert proof.findings == ()


def test_nba_provider_default_cannot_bind_any_non_nba_explicit_requirement() -> None:
    requirements = [
        _requirement(
            "league_game_log",
            league_id,
            strategy="explicit_applicability_cell",
            constructor_name="league_id",
        )
        for league_id in _LEAGUES
    ]
    nba = requirements[0]
    non_nba = requirements[1:]
    defaulted_request = _materialize_league_game_log(nba, omit_league_id=True)

    assert tuple(requirement.league_id for requirement in requirements) == _LEAGUES
    assert {requirement.league_id for requirement in non_nba} == set(_NON_NBA_LEAGUES)
    assert len(non_nba) == 4
    assert {requirement.provider_endpoint_id for requirement in requirements} == {"LeagueGameLog"}
    assert {requirement.role_binding.constructor_name for requirement in requirements} == {
        "league_id"
    }
    assert {requirement.role_binding.wire_name for requirement in requirements} == {"LeagueID"}
    assert {requirement.role_binding.provider_occurrence_id for requirement in requirements} == {
        "parameter:stats:LeagueGameLog:0002:league_id"
    }
    assert {requirement.role_binding.participant_axis_binding for requirement in requirements} == {
        "not_applicable"
    }
    assert dict(defaulted_request.materialized_parameters)["league_id"] == "00"
    assert "LeagueID=00" in defaulted_request.query_string

    positive = bind_explicit_competition_request(nba, defaulted_request)
    assert positive.competition_scope_sha256 == nba.competition_scope_sha256
    assert positive.provider_request_sha256 == defaulted_request.provider_request_sha256
    assert positive.to_dict()["request_kind"] == "provider_request"

    for requirement in non_nba:
        with pytest.raises(
            NbaApiCompetitionIdentityError,
            match="provider request competition role differs from requirement",
        ):
            bind_explicit_competition_request(requirement, defaulted_request)


def test_resealed_competition_scope_substitution_fails_for_every_shared_identifier_kind() -> (  # noqa: E501
    None
):
    nba = _requirement("league_game_log", "00")
    non_nba = [_requirement("league_game_log", league_id) for league_id in _NON_NBA_LEAGUES]
    rejection_count = 0

    for entity_kind, provider_encoding, entity_value in _ENTITY_VECTORS:
        for non_nba_requirement in non_nba:
            assert non_nba_requirement.competition_scope_sha256 != nba.competition_scope_sha256

            entity = qualify_entity_identity(
                non_nba_requirement,
                entity_kind,
                provider_encoding,
                entity_value,
            )
            original_identity_sha256 = entity.entity_identity_sha256
            mutated_body = {
                "domain_separator": _ENTITY_DOMAIN,
                "competition_scope_sha256": nba.competition_scope_sha256,
                "entity_kind": entity_kind,
                "provider_encoding": provider_encoding,
                "entity_value": entity_value,
            }
            object.__setattr__(
                entity,
                "competition_scope_sha256",
                nba.competition_scope_sha256,
            )
            object.__setattr__(entity, "entity_identity_sha256", _digest(mutated_body))

            assert entity.entity_identity_sha256 == _digest(mutated_body)
            assert entity.entity_identity_sha256 != original_identity_sha256
            assert entity.competition_scope_sha256 == nba.competition_scope_sha256
            with pytest.raises(NbaApiCompetitionIdentityError, match="entity identity drifted"):
                entity.to_dict()
            rejection_count += 1

            nba_entity = qualify_entity_identity(
                nba,
                entity_kind,
                provider_encoding,
                entity_value,
            )
            nba_public_body = nba_entity.to_dict()
            object.__setattr__(
                nba_entity,
                "_requirement_evidence",
                non_nba_requirement,
            )
            assert nba_entity.competition_scope_sha256 == nba.competition_scope_sha256
            assert nba_entity.entity_identity_sha256 == nba_public_body["entity_identity_sha256"]
            with pytest.raises(NbaApiCompetitionIdentityError, match="entity identity drifted"):
                nba_entity.to_dict()
            rejection_count += 1

    assert rejection_count == 32


def test_resealed_source_request_kind_substitution_fails_at_consumption() -> None:
    explicit_requirement = _requirement(
        "league_game_log",
        "00",
        strategy="explicit_applicability_cell",
        constructor_name="league_id",
    )
    provider = _materialize_league_game_log(
        explicit_requirement,
        omit_league_id=False,
    )
    explicit = bind_explicit_competition_request(explicit_requirement, provider)
    original_explicit_sha256 = explicit.source_request_sha256
    object.__setattr__(explicit, "request_kind", "static_source")
    object.__setattr__(
        explicit,
        "source_request_sha256",
        _digest(_request_body(explicit, "static_source")),
    )
    assert explicit.source_request_sha256 == _digest(_request_body(explicit, "static_source"))
    assert explicit.source_request_sha256 != original_explicit_sha256
    with pytest.raises(
        NbaApiCompetitionIdentityError,
        match="competition-qualified request identity drifted",
    ):
        explicit.to_dict()

    static_requirement = next(
        requirement
        for requirement in _requirements()
        if requirement.role_binding.binding_strategy == "fixed_static_root"
    )
    static = bind_static_competition_source(static_requirement)
    original_static_sha256 = static.source_request_sha256
    object.__setattr__(static, "request_kind", "provider_request")
    object.__setattr__(
        static,
        "source_request_sha256",
        _digest(_request_body(static, "provider_request")),
    )
    assert static.source_request_sha256 == _digest(_request_body(static, "provider_request"))
    assert static.source_request_sha256 != original_static_sha256
    with pytest.raises(
        NbaApiCompetitionIdentityError,
        match="competition-qualified request identity drifted",
    ):
        static.to_dict()


def test_independent_verifier_rejects_every_non_nba_scope_collapsed_to_nba_default(
    tmp_path: Path,
) -> None:
    _assert_pristine_reseal_is_accepted(tmp_path)
    for league_id in _NON_NBA_LEAGUES:
        payload = deepcopy(_payload())
        nba = _requirement_row(
            payload,
            "league_game_log",
            "00",
            strategy="explicit_applicability_cell",
            constructor_name="league_id",
        )
        target = _requirement_row(
            payload,
            "league_game_log",
            league_id,
            strategy="explicit_applicability_cell",
            constructor_name="league_id",
        )
        assert target["league_id"] == league_id
        assert target["symbol"] != nba["symbol"]
        assert target["competition_scope_sha256"] != nba["competition_scope_sha256"]
        target["league_id"] = nba["league_id"]
        target["symbol"] = nba["symbol"]
        target["competition_scope_sha256"] = nba["competition_scope_sha256"]
        assert (
            target["league_id"],
            target["symbol"],
            target["competition_scope_sha256"],
        ) == (
            nba["league_id"],
            nba["symbol"],
            nba["competition_scope_sha256"],
        )
        _assert_rejected(_candidate(tmp_path, payload, f"collapse-{league_id}-to-nba.json"))


def test_independent_verifier_rejects_entity_and_request_discriminator_removal(
    tmp_path: Path,
) -> None:
    removals = {
        "entity": (
            "competition_scope_sha256",
            "entity_kind",
            "provider_encoding",
        ),
        "source_request": (
            "competition_scope_sha256",
            "requirement_sha256",
            "role_binding_sha256",
            "request_kind",
        ),
    }
    candidate_count = 0
    for surface_name, fields_to_remove in removals.items():
        for field_name in fields_to_remove:
            payload = deepcopy(_payload())
            surface = _surface(payload, surface_name)
            identity_fields = cast("list[object]", surface["identity_fields"])
            field_types = cast("dict[str, object]", surface["identity_field_types"])
            assert field_name in identity_fields
            assert field_name in field_types
            identity_fields.remove(field_name)
            field_types.pop(field_name)
            assert field_name not in identity_fields
            assert field_name not in field_types
            _assert_rejected(
                _candidate(
                    tmp_path,
                    payload,
                    f"{surface_name}-remove-{field_name}.json",
                )
            )
            candidate_count += 1

    payload = deepcopy(_payload())
    source_request = _surface(payload, "source_request")
    field_types = cast("dict[str, object]", source_request["identity_field_types"])
    assert field_types["request_kind"] == "literal:provider_request|static_source"
    field_types["request_kind"] = "str"
    assert field_types["request_kind"] == "str"
    _assert_rejected(_candidate(tmp_path, payload, "source-request-weaken-request-kind.json"))
    candidate_count += 1

    assert candidate_count == 8


def test_independent_verifier_rejects_role_binding_strategy_root_kind_mode_state_and_occurrence_rebinding(  # noqa: E501
    tmp_path: Path,
) -> None:
    explicit = "explicit_applicability_cell"
    dynamic = "receipt_bound_dynamic_root"
    cases: tuple[
        tuple[
            str,
            str,
            tuple[str, str, str | None, str],
            tuple[str, str, str | None, str],
        ],
        ...,
    ] = (
        (
            "binding-strategy",
            "binding_strategy",
            ("live_box_score", "00", None, dynamic),
            ("static_players", "01", None, "root_not_exposed"),
        ),
        (
            "constructor-name",
            "constructor_name",
            ("league_game_log", "00", "league_id", explicit),
            (
                "gl_alum_box_score_similarity_score",
                "00",
                "person1_league_id",
                explicit,
            ),
        ),
        (
            "provider-occurrence",
            "provider_occurrence_id",
            ("league_game_log", "00", "league_id", explicit),
            (
                "gl_alum_box_score_similarity_score",
                "00",
                "person1_league_id",
                explicit,
            ),
        ),
        (
            "wire-name",
            "wire_name",
            ("league_game_log", "00", "league_id", explicit),
            (
                "gl_alum_box_score_similarity_score",
                "00",
                "person1_league_id",
                explicit,
            ),
        ),
        (
            "temporal-companion-occurrences",
            "temporal_companion_occurrence_ids",
            (
                "gl_alum_box_score_similarity_score",
                "00",
                "person1_league_id",
                explicit,
            ),
            (
                "gl_alum_box_score_similarity_score",
                "00",
                "person2_league_id",
                explicit,
            ),
        ),
        (
            "participant-axis",
            "participant_axis_binding",
            ("league_game_log", "00", "league_id", explicit),
            (
                "gl_alum_box_score_similarity_score",
                "00",
                "person1_league_id",
                explicit,
            ),
        ),
        (
            "root-kind",
            "root_kind",
            ("live_box_score", "00", None, dynamic),
            ("team_details", "00", None, dynamic),
        ),
        (
            "root-mode",
            "root_mode",
            ("live_box_score", "00", None, dynamic),
            ("live_odds", "00", None, dynamic),
        ),
        (
            "root-state",
            "root_state",
            ("live_box_score", "00", None, dynamic),
            ("static_players", "00", None, "fixed_static_root"),
        ),
        (
            "root-binding",
            "root_binding_sha256",
            ("live_box_score", "00", None, dynamic),
            ("live_play_by_play", "00", None, dynamic),
        ),
    )

    for name, field_name, source_spec, alternate_spec in cases:
        payload = deepcopy(_payload())
        source = _requirement_row(
            payload,
            source_spec[0],
            source_spec[1],
            constructor_name=source_spec[2],
            strategy=source_spec[3],
        )
        alternate = _requirement_row(
            payload,
            alternate_spec[0],
            alternate_spec[1],
            constructor_name=alternate_spec[2],
            strategy=alternate_spec[3],
        )
        source_role = _role(source)
        alternate_role = _role(alternate)
        assert field_name in source_role
        assert field_name in alternate_role
        original = deepcopy(source_role[field_name])
        replacement = deepcopy(alternate_role[field_name])
        assert replacement != original
        source_role[field_name] = replacement
        assert source_role[field_name] == alternate_role[field_name]
        _assert_rejected(_candidate(tmp_path, payload, f"role-{name}.json"))

    assert len(cases) == 10
