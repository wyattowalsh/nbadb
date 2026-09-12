from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from nbadb.core.nba_api_competition_identity import (
    CompetitionIdentityRequirement,
    bind_receipt_root_competition_request,
    compile_competition_identity_requirements,
    qualify_entity_identity,
)
from nbadb.core.nba_api_implicit_competition import (
    ReceiptBoundCompetitionRoot,
    pinned_implicit_competition_authority,
)
from nbadb.core.nba_api_request_surface import (
    CanonicalProviderRequest,
    materialize_provider_request,
    pinned_request_surface_authority,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


_LEAGUES = ("00", "01", "10", "15", "20")
_ENTITY_VECTORS: tuple[tuple[str, str, str | int], ...] = (
    ("game", "provider_string", "0022400001"),
    ("team", "provider_integer", 1610612737),
    ("player", "provider_integer", 2544),
    ("season", "provider_string", "2024-25"),
)
_DYNAMIC_ROOT_VECTORS: tuple[tuple[str, str, str | int], ...] = (
    ("live_box_score", "game", "0022400001"),
    ("team_details", "team", 1610612737),
    ("player_awards", "player", 2544),
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _requirements() -> tuple[CompetitionIdentityRequirement, ...]:
    return compile_competition_identity_requirements()


def _requirement(
    repo_endpoint_name: str,
    league_id: str,
) -> CompetitionIdentityRequirement:
    matches = [
        item
        for item in _requirements()
        if item.repo_endpoint_name == repo_endpoint_name and item.league_id == league_id
    ]
    assert len(matches) == 1
    return matches[0]


def _provider_request(
    requirement: CompetitionIdentityRequirement,
    parameters: Mapping[str, object],
) -> CanonicalProviderRequest:
    authority = pinned_request_surface_authority()
    endpoint = authority.endpoint(
        requirement.source_family,  # type: ignore[arg-type]
        requirement.provider_endpoint_id,
    )
    return materialize_provider_request(
        endpoint,
        parameters,
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )


def _dynamic_provider_request(
    requirement: CompetitionIdentityRequirement,
    root_value: str | int,
) -> CanonicalProviderRequest:
    root_parameter_name = _dynamic_root_parameter_name(requirement)
    return _provider_request(requirement, {root_parameter_name: root_value})


def _dynamic_root_parameter_name(
    requirement: CompetitionIdentityRequirement,
) -> str:
    implicit = pinned_implicit_competition_authority()
    binding = next(
        item
        for item in implicit.endpoint_bindings
        if item.binding_sha256 == requirement.role_binding.root_binding_sha256
    )
    root = binding.root_requirement
    assert root.root_mode == "request_parameter"
    assert root.provider_occurrence_id is not None
    request_surface = pinned_request_surface_authority()
    endpoint = request_surface.endpoint(
        requirement.source_family,  # type: ignore[arg-type]
        requirement.provider_endpoint_id,
    )
    occurrence = next(
        item for item in endpoint.parameters if item.occurrence_id == root.provider_occurrence_id
    )
    return occurrence.name


def _dynamic_receipt(
    requirement: CompetitionIdentityRequirement,
    provider: CanonicalProviderRequest,
) -> ReceiptBoundCompetitionRoot:
    authority = pinned_implicit_competition_authority()
    binding = next(
        item
        for item in authority.endpoint_bindings
        if item.binding_sha256 == requirement.role_binding.root_binding_sha256
    )
    root = binding.root_requirement
    assert root.root_mode == "request_parameter"
    occurrence = next(
        item
        for item in pinned_request_surface_authority()
        .endpoint(provider.source_family, provider.endpoint_id)
        .parameters
        if item.occurrence_id == root.provider_occurrence_id
    )
    root_value = dict(provider.materialized_parameters)[occurrence.name]
    source_scope_sha256 = _digest(
        {
            "league_id": requirement.league_id,
            "physical_endpoint_key": requirement.physical_endpoint_key,
            "scope": "competition-identity-collision-offline-test",
        }
    )
    producer_artifact_sha256 = _digest(
        {
            "artifact": requirement.physical_endpoint_key,
            "league_id": requirement.league_id,
        }
    )
    producer_payload_sha256 = _digest(
        {"payload": provider.provider_request_sha256, "root_value": root_value}
    )
    producer_body: dict[str, object] = {
        "artifact_sha256": producer_artifact_sha256,
        "payload_sha256": producer_payload_sha256,
        "schema": "OfflineProducerReceiptV1",
        "source_request_identity_sha256": provider.provider_request_sha256,
        "source_scope_sha256": source_scope_sha256,
        "task_id": "competition-identity-collision-offline-test",
    }
    source_request_receipt_sha256 = _digest(producer_body)
    producer_receipt = {
        **producer_body,
        "receipt_sha256": source_request_receipt_sha256,
    }
    common: dict[str, object] = {
        "competition_authority_sha256": authority.competition_authority_sha256,
        "league_id": requirement.league_id,
        "root_binding_sha256": binding.binding_sha256,
        "root_generation_sha256": source_scope_sha256,
        "root_kind": root.root_kind,
        "root_mode": root.root_mode,
        "root_value": root_value,
        "source_endpoint_id": binding.provider_endpoint_id,
        "source_request_identity_sha256": provider.provider_request_sha256,
        "source_request_receipt_sha256": source_request_receipt_sha256,
    }
    variant = {
        **common,
        "producer_artifact_sha256": producer_artifact_sha256,
        "producer_payload_sha256": producer_payload_sha256,
        "producer_receipt_sha256": source_request_receipt_sha256,
        "producer_schema": "OfflineProducerReceiptV1",
        "producer_task_id": "competition-identity-collision-offline-test",
        "source_scope_sha256": source_scope_sha256,
        "provider_occurrence_id": root.provider_occurrence_id,
        "root_value_type": "int" if type(root_value) is int else "str",
        "source_signature_sha256": root.source_signature_sha256,
        "typed_domain_sha256": root.typed_domain_sha256,
    }
    observation = {
        **common,
        "schema": "ReceiptBoundCompetitionRootV1",
        "variant_evidence_sha256": _digest(variant),
    }
    body = {**observation, "root_observation_sha256": _digest(observation)}
    return ReceiptBoundCompetitionRoot(
        **body,
        receipt_sha256=_digest(body),
        variant_evidence=variant,
        producer_receipt=producer_receipt,
    )


def test_shared_game_team_player_and_season_identifiers_are_distinct_across_all_five_competitions() -> (  # noqa: E501
    None
):
    identities = []
    for entity_kind, provider_encoding, entity_value in _ENTITY_VECTORS:
        kind_identities = [
            qualify_entity_identity(
                _requirement("league_game_log", league_id),
                entity_kind,
                provider_encoding,
                entity_value,
            )
            for league_id in _LEAGUES
        ]
        projections = [item.to_dict() for item in kind_identities]

        assert [item.entity_kind for item in kind_identities] == [entity_kind] * 5
        assert [item.provider_encoding for item in kind_identities] == [provider_encoding] * 5
        assert [item.entity_value for item in kind_identities] == [entity_value] * 5
        assert {item.competition_scope_sha256 for item in kind_identities} == {
            _requirement("league_game_log", league_id).competition_scope_sha256
            for league_id in _LEAGUES
        }
        assert len({item.entity_identity_sha256 for item in kind_identities}) == 5
        assert all(
            projection["entity_kind"] == entity_kind
            and projection["provider_encoding"] == provider_encoding
            and projection["entity_value"] == entity_value
            for projection in projections
        )
        identities.extend(kind_identities)

    assert len(identities) == 20
    assert len({item.entity_identity_sha256 for item in identities}) == 20


def test_shared_dynamic_game_team_and_player_provider_requests_get_distinct_competition_source_identities() -> (  # noqa: E501
    None
):
    for repo_endpoint_name, root_kind, root_value in _DYNAMIC_ROOT_VECTORS:
        requirements = [_requirement(repo_endpoint_name, league_id) for league_id in _LEAGUES]
        providers = [
            _dynamic_provider_request(requirement, root_value) for requirement in requirements
        ]
        receipts = [
            _dynamic_receipt(requirement, provider)
            for requirement, provider in zip(requirements, providers, strict=True)
        ]
        requests = [
            bind_receipt_root_competition_request(requirement, receipt, provider)
            for requirement, receipt, provider in zip(
                requirements,
                receipts,
                providers,
                strict=True,
            )
        ]

        assert tuple(requirement.league_id for requirement in requirements) == _LEAGUES
        assert {requirement.role_binding.binding_strategy for requirement in requirements} == {
            "receipt_bound_dynamic_root"
        }
        assert {requirement.role_binding.root_kind for requirement in requirements} == {root_kind}
        root_parameter_names = {
            _dynamic_root_parameter_name(requirement) for requirement in requirements
        }
        assert len(root_parameter_names) == 1
        root_parameter_name = next(iter(root_parameter_names))
        assert len({provider.provider_request_sha256 for provider in providers}) == 1
        assert all(
            provider.materialized_parameters == providers[0].materialized_parameters
            for provider in providers
        )
        assert all(
            type(dict(provider.materialized_parameters)[root_parameter_name]) is type(root_value)
            and dict(provider.materialized_parameters)[root_parameter_name] == root_value
            for provider in providers
        )
        assert tuple(receipt.league_id for receipt in receipts) == _LEAGUES
        assert all(receipt.root_value == root_value for receipt in receipts)
        assert all(
            receipt.source_request_identity_sha256 == provider.provider_request_sha256
            for receipt, provider in zip(receipts, providers, strict=True)
        )
        assert len({receipt.receipt_sha256 for receipt in receipts}) == 5
        assert len({request.competition_scope_sha256 for request in requests}) == 5
        assert len({request.requirement_sha256 for request in requests}) == 5
        assert len({request.role_binding_sha256 for request in requests}) == 5
        assert len({request.source_evidence_sha256 for request in requests}) == 5
        assert len({request.source_request_sha256 for request in requests}) == 5
        assert {request.provider_request_sha256 for request in requests} == {
            providers[0].provider_request_sha256
        }
        assert all(request.to_dict()["request_kind"] == "provider_request" for request in requests)


def test_entity_kind_and_provider_encoding_discriminators_prevent_same_value_collisions() -> (  # noqa: E501
    None
):
    requirement = _requirement("league_game_log", "00")
    shared_value = 2544
    kinds = ("game", "team", "player", "season")
    kind_identities = [
        qualify_entity_identity(requirement, kind, "provider_integer", shared_value)
        for kind in kinds
    ]
    kind_projections = [item.to_dict() for item in kind_identities]
    kind_baselines = [
        {
            key: value
            for key, value in projection.items()
            if key not in {"entity_kind", "entity_identity_sha256"}
        }
        for projection in kind_projections
    ]

    assert len({json.dumps(item, sort_keys=True) for item in kind_baselines}) == 1
    assert [item.entity_kind for item in kind_identities] == list(kinds)
    assert len({item.entity_identity_sha256 for item in kind_identities}) == len(kinds)

    encodings = ("provider_integer", "provider_string")
    encoding_identities = [
        qualify_entity_identity(requirement, "player", encoding, shared_value)
        for encoding in encodings
    ]
    encoding_projections = [item.to_dict() for item in encoding_identities]
    encoding_baselines = [
        {
            key: value
            for key, value in projection.items()
            if key not in {"provider_encoding", "entity_identity_sha256"}
        }
        for projection in encoding_projections
    ]

    assert len({json.dumps(item, sort_keys=True) for item in encoding_baselines}) == 1
    assert [item.provider_encoding for item in encoding_identities] == list(encodings)
    assert all(item.entity_value == shared_value for item in encoding_identities)
    assert len({item.entity_identity_sha256 for item in encoding_identities}) == len(encodings)
