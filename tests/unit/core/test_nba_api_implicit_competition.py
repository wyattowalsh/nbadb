from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import copy, deepcopy
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from nba_api.live.nba.library.http import NBALiveHTTP
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.core import nba_api_implicit_competition as implicit_subject
from nbadb.core.nba_api_competition_applicability import (
    pinned_competition_applicability_authority,
)
from nbadb.core.nba_api_competition_occurrences import (
    pinned_competition_occurrence_authority,
)
from nbadb.core.nba_api_implicit_competition import (
    CompetitionRootRequirement,
    ImplicitCompetitionAliasBinding,
    ImplicitCompetitionAuthority,
    ImplicitCompetitionCell,
    ImplicitCompetitionEndpointBinding,
    NbaApiImplicitCompetitionError,
    ReceiptBoundCompetitionRoot,
    build_implicit_competition_authority,
    build_pinned_implicit_competition_payload,
    load_pinned_implicit_competition_payload,
    resolve_implicit_competition,
    write_pinned_implicit_competition,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


_RESOURCE_NAME = "nba_api_implicit_competition_v1_11_4.json"
_LIVE_RAW_ROOT_EVIDENCE_SHA256 = "f45dd10412bbd8a45f846b0ebb8f046848d997f0162c4d040baab61fd17ef13f"


class _StringSubclass(str):
    pass


class _IntegerSubclass(int):
    pass


class _TupleSubclass(tuple[object, ...]):
    pass


class _DictSubclass(dict[str, object]):
    pass


class _RequirementSubclass(CompetitionRootRequirement):
    pass


class _EndpointBindingSubclass(ImplicitCompetitionEndpointBinding):
    pass


class _AliasBindingSubclass(ImplicitCompetitionAliasBinding):
    pass


class _CellSubclass(ImplicitCompetitionCell):
    pass


class _ReceiptSubclass(ReceiptBoundCompetitionRoot):
    pass


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


def _resource_path() -> Path:
    return Path(__file__).parents[3] / "src" / "nbadb" / "contracts" / _RESOURCE_NAME


def _authority() -> ImplicitCompetitionAuthority:
    return build_implicit_competition_authority()


def _binding(
    *, root_kind: str | None = None, root_mode: str | None = None
) -> ImplicitCompetitionEndpointBinding:
    matches = [
        item
        for item in _authority().endpoint_bindings
        if (root_kind is None or item.root_requirement.root_kind == root_kind)
        and (root_mode is None or item.root_requirement.root_mode == root_mode)
    ]
    assert matches
    return matches[0]


def _receipt(
    binding: ImplicitCompetitionEndpointBinding,
    league_id: str,
    root_value: int | str,
    *,
    row_ordinal: int = 0,
    common_updates: Mapping[str, object] | None = None,
    variant_updates: Mapping[str, object] | None = None,
    receipt_updates: Mapping[str, object] | None = None,
    producer_receipt_override: Mapping[str, object] | None = None,
    variant_as_subclass: bool = False,
    producer_as_subclass: bool = False,
    receipt_subclass_field: str | None = None,
    variant_subclass_key: str | None = None,
    producer_subclass_key: str | None = None,
    receipt_type: type[ReceiptBoundCompetitionRoot] = ReceiptBoundCompetitionRoot,
) -> ReceiptBoundCompetitionRoot:
    requirement = binding.root_requirement
    source_scope_sha256 = _digest(
        {
            "league_id": league_id,
            "physical_endpoint_key": binding.physical_endpoint_key,
            "scope": "test-only-offline-receipt",
        }
    )
    source_request_identity_sha256 = _digest(
        {
            "league_id": league_id,
            "root_kind": requirement.root_kind,
            "root_value": root_value,
            "source_endpoint_id": binding.provider_endpoint_id,
        }
    )
    producer_artifact_sha256 = _digest(
        {"artifact": binding.physical_endpoint_key, "league_id": league_id}
    )
    producer_payload_sha256 = _digest(
        {"payload": source_request_identity_sha256, "root_value": root_value}
    )
    producer_body: dict[str, object] = {
        "artifact_sha256": producer_artifact_sha256,
        "payload_sha256": producer_payload_sha256,
        "schema": "OfflineProducerReceiptV1",
        "source_request_identity_sha256": source_request_identity_sha256,
        "source_scope_sha256": source_scope_sha256,
        "task_id": "test-offline-producer",
    }
    source_request_receipt_sha256 = _digest(producer_body)
    default_producer_receipt: dict[str, object] = {
        **producer_body,
        "receipt_sha256": source_request_receipt_sha256,
    }
    producer_receipt = (
        default_producer_receipt if producer_receipt_override is None else producer_receipt_override
    )
    source_request_receipt_sha256 = producer_receipt["receipt_sha256"]
    competition_authority_sha256 = _authority().competition_authority_sha256
    common: dict[str, object] = {
        "competition_authority_sha256": competition_authority_sha256,
        "league_id": league_id,
        "root_binding_sha256": binding.binding_sha256,
        "root_generation_sha256": source_scope_sha256,
        "root_kind": requirement.root_kind,
        "root_mode": requirement.root_mode,
        "root_value": root_value,
        "source_endpoint_id": binding.provider_endpoint_id,
        "source_request_identity_sha256": source_request_identity_sha256,
        "source_request_receipt_sha256": source_request_receipt_sha256,
    }
    if common_updates:
        common.update(common_updates)
    variant: dict[str, object] = {
        **common,
        "producer_artifact_sha256": producer_artifact_sha256,
        "producer_payload_sha256": producer_payload_sha256,
        "producer_receipt_sha256": source_request_receipt_sha256,
        "producer_schema": "OfflineProducerReceiptV1",
        "producer_task_id": "test-offline-producer",
        "source_scope_sha256": source_scope_sha256,
    }
    root_value_type = "int" if type(root_value) is int else "str"
    if requirement.root_mode == "request_parameter":
        variant.update(
            {
                "provider_occurrence_id": requirement.provider_occurrence_id,
                "root_value_type": root_value_type,
                "source_signature_sha256": requirement.source_signature_sha256,
                "typed_domain_sha256": requirement.typed_domain_sha256,
            }
        )
    elif requirement.root_mode == "response_game_join":
        variant.update(
            {
                "captured_body_sha256": _digest(
                    {
                        "games": [{"gameId": common["root_value"]}],
                        "league_id": common["league_id"],
                    }
                ),
                "captured_game_id": common["root_value"],
                "game_id_json_path": "$.games.gameId",
                "live_raw_root_evidence_sha256": _LIVE_RAW_ROOT_EVIDENCE_SHA256,
                "result_occurrence_sha256": _digest(
                    {"endpoint": "Odds", "row_ordinal": row_ordinal}
                ),
                "root_value_type": root_value_type,
                "row_ordinal": row_ordinal,
            }
        )
    elif requirement.root_mode == "response_game_collection":
        variant.update(
            {
                "captured_body_sha256": _digest(
                    {
                        "scoreboard": {
                            "games": [{"gameId": common["root_value"]}],
                            "leagueId": common["league_id"],
                        }
                    }
                ),
                "captured_game_id": common["root_value"],
                "captured_league_id": common["league_id"],
                "game_id_json_path": "$.scoreboard.games.gameId",
                "league_id_json_path": "$.scoreboard.leagueId",
                "live_raw_root_evidence_sha256": _LIVE_RAW_ROOT_EVIDENCE_SHA256,
                "result_occurrence_sha256": _digest(
                    {"endpoint": "ScoreBoard", "row_ordinal": row_ordinal}
                ),
                "root_value_type": root_value_type,
                "row_ordinal": row_ordinal,
            }
        )
    else:
        raise AssertionError("Static roots cannot receive dynamic test receipts")
    if variant_updates:
        variant.update(variant_updates)
    if variant_subclass_key is not None:
        variant[_StringSubclass(variant_subclass_key)] = variant.pop(variant_subclass_key)
    variant_evidence_sha256 = _digest(variant)
    observation = {
        **common,
        "schema": "ReceiptBoundCompetitionRootV1",
        "variant_evidence_sha256": variant_evidence_sha256,
    }
    root_observation_sha256 = _digest(observation)
    receipt_body: dict[str, object] = {
        **observation,
        "root_observation_sha256": root_observation_sha256,
    }
    receipt_payload = {**receipt_body, "receipt_sha256": _digest(receipt_body)}
    if receipt_updates:
        receipt_payload.update(receipt_updates)
    if receipt_subclass_field is not None:
        receipt_value = receipt_payload[receipt_subclass_field]
        assert type(receipt_value) is str
        receipt_payload[receipt_subclass_field] = _StringSubclass(receipt_value)
    if producer_subclass_key is not None:
        producer_receipt = dict(producer_receipt)
        producer_receipt[_StringSubclass(producer_subclass_key)] = producer_receipt.pop(
            producer_subclass_key
        )
    return receipt_type(
        **receipt_payload,
        variant_evidence=_DictSubclass(variant) if variant_as_subclass else variant,
        producer_receipt=(
            _DictSubclass(producer_receipt) if producer_as_subclass else producer_receipt
        ),
    )


def _exact_type_mutations(value: object) -> tuple[object, ...]:
    if type(value) is str:
        return (_StringSubclass(value),)
    if type(value) is int:
        return (_IntegerSubclass(value), bool(value))
    if type(value) is bool:
        return (int(value),)
    if type(value) is tuple:
        mutations: list[object] = [_TupleSubclass(value)]
        exact_tuple = tuple(value)
        for index, item in enumerate(exact_tuple):
            if type(item) is str:
                mutated = list(exact_tuple)
                mutated[index] = _StringSubclass(item)
                mutations.append(tuple(mutated))
                break
        return tuple(mutations)
    return ()


def _stale_receipt_field_value(
    receipt: ReceiptBoundCompetitionRoot,
    field_name: str,
) -> object:
    value = getattr(receipt, field_name)
    if field_name == "_variant_evidence_items":
        return tuple(
            (
                key,
                "0" * 64 if key == "source_request_identity_sha256" else item,
            )
            for key, item in value
        )
    if field_name == "_producer_receipt_items":
        return tuple((key, "0" * 64 if key == "artifact_sha256" else item) for key, item in value)
    replacements: dict[str, object] = {
        "schema": "ReceiptBoundCompetitionRootV2",
        "root_kind": "team",
        "root_value": "0022500002",
        "league_id": "10",
        "root_mode": "response_game_join",
        "source_endpoint_id": "ForeignEndpoint",
    }
    return replacements.get(field_name, "0" * 64)


def _assert_exact_type_mutations_rejected(
    value: object,
    *,
    replace_extras: Mapping[str, object] | None = None,
) -> None:
    for field in fields(value):
        for mutation in _exact_type_mutations(getattr(value, field.name)):
            updates = {field.name: mutation}
            if replace_extras:
                updates.update(replace_extras)
            with pytest.raises(NbaApiImplicitCompetitionError):
                replace(value, **updates)


def _clone_as_subclass(value: object, subclass: type[object]) -> object:
    return subclass(
        **{field.name: getattr(value, field.name) for field in fields(value) if field.init}
    )


def _sealed_checked_payload(payload: Mapping[str, object]) -> bytes:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"authority_sha256", "payload_sha256"}
    }
    body["authority_sha256"] = _digest(body)
    body["payload_sha256"] = _digest(body)
    return (
        json.dumps(
            body,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def test_authority_partitions_147_physical_sources_into_111_explicit_and_36_implicit() -> None:
    explicit = {
        item.provider_endpoint_id
        for item in pinned_competition_occurrence_authority().package_occurrences
    }
    implicit = _authority().endpoint_bindings

    assert len(explicit) == 111
    assert len(implicit) == 36
    assert len({item.physical_endpoint_key for item in implicit}) == 36
    assert explicit.isdisjoint(item.provider_endpoint_id for item in implicit)
    assert len(explicit) + len(implicit) == 147


def test_authority_partitions_162_repo_aliases_into_126_explicit_and_36_implicit() -> None:
    explicit = {
        item.repo_endpoint_name for item in pinned_competition_occurrence_authority().repo_aliases
    }
    implicit = {item.repo_endpoint_name for item in _authority().alias_bindings}

    assert len(explicit) == 126
    assert len(implicit) == 36
    assert explicit.isdisjoint(implicit)
    assert len(explicit | implicit) == 162


def test_authority_preserves_180_physical_and_180_alias_competition_cells() -> None:
    authority = _authority()

    assert len(authority.physical_competition_cells) == 180
    assert len(authority.alias_competition_cells) == 180
    assert len({item.cell_id for item in authority.physical_competition_cells}) == 180
    assert len({item.cell_id for item in authority.alias_competition_cells}) == 180
    assert {item.provider_availability_status for item in authority.physical_competition_cells} == {
        "unknown"
    }


def test_root_kind_and_binding_mode_counts_are_exact() -> None:
    requirements = [item.root_requirement for item in _authority().endpoint_bindings]

    assert Counter(item.root_kind for item in requirements) == {
        "game": 30,
        "player": 1,
        "team": 1,
        "static": 4,
    }
    assert Counter(item.root_mode for item in requirements) == {
        "request_parameter": 30,
        "response_game_collection": 1,
        "response_game_join": 1,
        "embedded_static_dataset": 4,
    }


def test_static_roots_bind_only_exact_nba_and_wnba_dataset_sources() -> None:
    static = [
        item
        for item in _authority().endpoint_bindings
        if item.root_requirement.root_kind == "static"
    ]

    assert {
        (
            item.physical_endpoint_key,
            item.root_requirement.fixed_league_id,
            item.root_requirement.fixed_symbol,
        )
        for item in static
    } == {
        ("static:static_players", "00", "nba"),
        ("static:static_teams", "00", "nba"),
        ("static:static_wnba_players", "10", "wnba"),
        ("static:static_wnba_teams", "10", "wnba"),
    }
    assert all(item.root_requirement.static_chain_sha256 for item in static)


def test_full_denominators_are_735_physical_740_axis_and_815_role_cells() -> None:
    explicit = pinned_competition_applicability_authority()
    implicit = _authority()

    assert len(explicit.endpoint_cells) + len(implicit.physical_competition_cells) == 735
    assert len(explicit.parameter_axis_cells) + len(implicit.physical_competition_cells) == 740
    assert len(explicit.alias_role_cells) + len(implicit.alias_competition_cells) == 815


def test_implicit_competition_resource_is_generated_without_drift(tmp_path: Path) -> None:
    candidate = tmp_path / _RESOURCE_NAME

    assert write_pinned_implicit_competition(candidate) is False
    assert write_pinned_implicit_competition(candidate) is True
    assert write_pinned_implicit_competition(candidate, check=True) is True
    assert candidate.read_bytes() == _resource_path().read_bytes()
    assert load_pinned_implicit_competition_payload(candidate) == (
        build_pinned_implicit_competition_payload()
    )


def test_primary_rejects_current_source_authority_load_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_current_source_load() -> None:
        raise implicit_subject.ImplicitCompetitionSourceAuthorityLoadError("test failure")

    implicit_subject._root_source_payload.cache_clear()
    build_implicit_competition_authority.cache_clear()
    monkeypatch.setattr(
        implicit_subject,
        "load_implicit_competition_current_source_authority",
        fail_current_source_load,
    )
    try:
        with pytest.raises(
            NbaApiImplicitCompetitionError,
            match="current implicit-competition source authority is invalid",
        ):
            build_implicit_competition_authority()
    finally:
        implicit_subject._root_source_payload.cache_clear()
        build_implicit_competition_authority.cache_clear()


def test_primary_rejects_historical_current_source_path_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = implicit_subject.load_implicit_competition_current_source_authority()
    foreign_bindings = tuple(
        SimpleNamespace(
            path=("src/nbadb/foreign/current-source.py" if index == 0 else binding.path)
        )
        for index, binding in enumerate(current.candidate.source_bindings)
    )
    foreign_authority = SimpleNamespace(candidate=SimpleNamespace(source_bindings=foreign_bindings))

    implicit_subject._root_source_payload.cache_clear()
    build_implicit_competition_authority.cache_clear()
    monkeypatch.setattr(
        implicit_subject,
        "load_implicit_competition_current_source_authority",
        lambda: foreign_authority,
    )
    try:
        with pytest.raises(
            NbaApiImplicitCompetitionError,
            match="historical and current implicit source path inventories differ",
        ):
            build_implicit_competition_authority()
    finally:
        implicit_subject._root_source_payload.cache_clear()
        build_implicit_competition_authority.cache_clear()


def test_authority_rejects_missing_extra_or_duplicate_physical_alias_or_cell() -> None:
    authority = _authority()
    groups = (
        "endpoint_bindings",
        "alias_bindings",
        "physical_competition_cells",
        "alias_competition_cells",
    )

    for field in groups:
        values = getattr(authority, field)
        mutations = (
            values[:-1],
            (*values, values[0]),
            (*values[:-1], values[0]),
        )
        for mutation in mutations:
            with pytest.raises(NbaApiImplicitCompetitionError):
                replace(authority, **{field: mutation})

    endpoint = authority.endpoint_bindings[0]
    alias = authority.alias_bindings[0]
    physical_cell = authority.physical_competition_cells[0]
    alias_cell = authority.alias_competition_cells[0]
    for value in (authority, endpoint, alias, physical_cell, alias_cell):
        _assert_exact_type_mutations_rejected(value)

    requirement_subclass = _clone_as_subclass(
        endpoint.root_requirement,
        _RequirementSubclass,
    )
    endpoint_subclass = _clone_as_subclass(endpoint, _EndpointBindingSubclass)
    alias_subclass = _clone_as_subclass(alias, _AliasBindingSubclass)
    physical_cell_subclass = _clone_as_subclass(physical_cell, _CellSubclass)
    alias_cell_subclass = _clone_as_subclass(alias_cell, _CellSubclass)
    assert type(requirement_subclass) is _RequirementSubclass
    assert type(endpoint_subclass) is _EndpointBindingSubclass
    assert type(alias_subclass) is _AliasBindingSubclass
    assert type(physical_cell_subclass) is _CellSubclass
    assert type(alias_cell_subclass) is _CellSubclass

    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(endpoint, root_requirement=requirement_subclass)
    for field, child in (
        ("endpoint_bindings", endpoint_subclass),
        ("alias_bindings", alias_subclass),
        ("physical_competition_cells", physical_cell_subclass),
        ("alias_competition_cells", alias_cell_subclass),
    ):
        children = getattr(authority, field)
        with pytest.raises(NbaApiImplicitCompetitionError):
            replace(authority, **{field: (child, *children[1:])})


def test_authority_rejects_explicit_and_implicit_endpoint_or_alias_overlap() -> None:
    authority = _authority()
    occurrence = pinned_competition_occurrence_authority()

    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(
            authority.endpoint_bindings[0],
            provider_endpoint_id=occurrence.package_occurrences[0].provider_endpoint_id,
        )
    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(
            authority.alias_bindings[0],
            repo_endpoint_name=occurrence.repo_aliases[0].repo_endpoint_name,
        )


def test_authority_rejects_unclassified_no_league_source() -> None:
    binding = _authority().endpoint_bindings[0]

    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(binding, source_family="unclassified_no_league_source")


def test_authority_rejects_static_helper_promoted_to_physical_endpoint() -> None:
    static = _binding(root_kind="static")

    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(
            static,
            physical_endpoint_key="static:find_players_by_full_name",
            provider_endpoint_id="find_players_by_full_name",
        )


def test_authority_rejects_raw_id_default_history_url_or_id_shape_as_competition_evidence() -> None:
    for root_kind, root_value in (("game", "0022500001"), ("team", 1610612737), ("player", 2544)):
        binding = _binding(root_kind=root_kind, root_mode="request_parameter")
        for league_id in ("00", "10"):
            resolution = resolve_implicit_competition(
                binding.physical_endpoint_key,
                league_id,
            )
            assert resolution.resolution_state == "root_receipt_required"
            assert resolution.root_value is None
            assert resolution.receipt_sha256 is None
        assert root_value is not None


def test_authority_rejects_missing_or_unbound_root_receipt() -> None:
    binding = _binding(root_kind="game", root_mode="request_parameter")
    missing = resolve_implicit_competition(binding.physical_endpoint_key, "00")
    nba_receipt = _receipt(binding, "00", "0022500001")
    unbound = resolve_implicit_competition(
        binding.physical_endpoint_key,
        "10",
        receipt=nba_receipt,
    )

    assert missing.resolution_state == "root_receipt_required"
    assert unbound.resolution_state == "root_receipt_required"
    with pytest.raises(NbaApiImplicitCompetitionError):
        _receipt(
            binding,
            "00",
            "0022500001",
            variant_updates={"producer_receipt_sha256": "0" * 64},
        )

    foreign_sha256 = _digest({"foreign": "producer-commitment"})
    self_resealed_foreign_edges = (
        ({}, {"producer_artifact_sha256": foreign_sha256}),
        ({}, {"producer_payload_sha256": foreign_sha256}),
        ({}, {"producer_schema": "ForeignProducerReceiptV1"}),
        ({}, {"producer_task_id": "foreign-producer"}),
        ({"source_request_identity_sha256": foreign_sha256}, {}),
        (
            {"root_generation_sha256": foreign_sha256},
            {"source_scope_sha256": foreign_sha256},
        ),
    )
    for common_updates, variant_updates in self_resealed_foreign_edges:
        with pytest.raises(NbaApiImplicitCompetitionError):
            _receipt(
                binding,
                "00",
                "0022500001",
                common_updates=common_updates,
                variant_updates=variant_updates,
            )

    empty_producer_receipt = {"receipt_sha256": _digest({})}
    with pytest.raises(NbaApiImplicitCompetitionError):
        _receipt(
            binding,
            "00",
            "0022500001",
            producer_receipt_override=empty_producer_receipt,
        )

    valid = _receipt(binding, "00", "0022500001")
    assert len(valid.to_dict()) == 14
    valid_resolution = resolve_implicit_competition(
        binding.physical_endpoint_key,
        "00",
        receipt=valid,
    )
    assert valid_resolution.resolution_state == "competition_resolved"
    with pytest.raises(ValueError):
        replace(valid)
    replaced_valid = replace(
        valid,
        variant_evidence=dict(valid._variant_evidence_items),
        producer_receipt=dict(valid._producer_receipt_items),
    )
    assert replaced_valid == valid
    replaced_valid._revalidate()

    receipt_fields = {field.name for field in fields(valid)}
    assert receipt_fields == {
        "schema",
        "root_kind",
        "root_value",
        "league_id",
        "competition_authority_sha256",
        "root_binding_sha256",
        "root_mode",
        "root_generation_sha256",
        "source_endpoint_id",
        "source_request_identity_sha256",
        "source_request_receipt_sha256",
        "variant_evidence_sha256",
        "root_observation_sha256",
        "receipt_sha256",
        "_variant_evidence_items",
        "_producer_receipt_items",
    }
    for copier in (copy, deepcopy):
        for receipt_field in fields(valid):
            tampered = copier(valid)
            object.__setattr__(
                tampered,
                receipt_field.name,
                _stale_receipt_field_value(tampered, receipt_field.name),
            )
            with pytest.raises(NbaApiImplicitCompetitionError):
                resolve_implicit_competition(
                    binding.physical_endpoint_key,
                    "00",
                    receipt=tampered,
                )
            with pytest.raises(NbaApiImplicitCompetitionError):
                replace(valid_resolution, receipt=tampered)


def test_authority_rejects_root_kind_locator_or_request_value_mismatch() -> None:
    binding = _binding(root_kind="game", root_mode="request_parameter")
    requirement = binding.root_requirement

    for exact_requirement in (
        requirement,
        _binding(root_mode="response_game_join").root_requirement,
        _binding(root_kind="static").root_requirement,
    ):
        _assert_exact_type_mutations_rejected(exact_requirement)

    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(requirement, root_kind="team")
    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(requirement, parameter_location="body")
    with pytest.raises(NbaApiImplicitCompetitionError):
        _receipt(
            binding,
            "00",
            "0022500001",
            variant_updates={"provider_occurrence_id": "parameter:foreign"},
        )
    with pytest.raises(NbaApiImplicitCompetitionError):
        _receipt(
            binding,
            "00",
            22500001,
        )

    valid_receipt = _receipt(binding, "00", "0022500001")
    for field, value in valid_receipt.to_dict().items():
        if type(value) is str:
            with pytest.raises(NbaApiImplicitCompetitionError):
                _receipt(
                    binding,
                    "00",
                    "0022500001",
                    receipt_subclass_field=field,
                )
    for options in (
        {"variant_as_subclass": True},
        {"producer_as_subclass": True},
        {"variant_subclass_key": "root_kind"},
        {"producer_subclass_key": "schema"},
    ):
        with pytest.raises(NbaApiImplicitCompetitionError):
            _receipt(binding, "00", "0022500001", **options)
    with pytest.raises(NbaApiImplicitCompetitionError):
        _receipt(
            _binding(root_kind="team", root_mode="request_parameter"),
            "00",
            _IntegerSubclass(1610612737),
        )


def test_authority_rejects_ambiguous_live_response_root() -> None:
    odds = _binding(root_mode="response_game_join")
    scoreboard = _binding(root_mode="response_game_collection")

    assert (
        resolve_implicit_competition(odds.physical_endpoint_key, "00").resolution_state
        == "root_receipt_required"
    )
    with pytest.raises(NbaApiImplicitCompetitionError):
        _receipt(
            odds,
            "00",
            "0022500001",
            variant_updates={"captured_game_id": "0022500002"},
        )
    with pytest.raises(NbaApiImplicitCompetitionError):
        _receipt(
            scoreboard,
            "00",
            "0022500001",
            variant_updates={"captured_league_id": "10"},
        )


def test_authority_rejects_static_mapping_or_source_digest_drift() -> None:
    static = _binding(root_kind="static")
    requirement = static.root_requirement

    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(requirement, fixed_league_id="10")
    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(requirement, static_chain_sha256="0" * 64)
    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(static, provider_source_sha256="0" * 64)


def test_authority_rejects_provider_availability_or_terminal_claims() -> None:
    authority = _authority()
    cell = authority.physical_competition_cells[0]
    resolution = resolve_implicit_competition(cell.physical_endpoint_key, cell.league_id)

    for field, value in (
        ("endpoint_support_status", "supported"),
        ("provider_availability_status", "available"),
        ("request_terminal_state", "captured_nonempty"),
    ):
        with pytest.raises(NbaApiImplicitCompetitionError):
            replace(cell, **{field: value})
        with pytest.raises(NbaApiImplicitCompetitionError):
            replace(resolution, **{field: value})

    alias_cell = authority.alias_competition_cells[0]
    alias_resolution = resolve_implicit_competition(
        alias_cell.physical_endpoint_key,
        alias_cell.league_id,
        repo_endpoint_name=alias_cell.repo_endpoint_name,
    )
    static_cell = next(
        item
        for item in authority.physical_competition_cells
        if item.root_state == "fixed_static_root"
    )
    static_resolution = resolve_implicit_competition(
        static_cell.physical_endpoint_key,
        static_cell.league_id,
    )
    dynamic_binding = _binding(root_kind="game", root_mode="request_parameter")
    receipt = _receipt(dynamic_binding, "00", "0022500001")
    resolved = resolve_implicit_competition(
        dynamic_binding.physical_endpoint_key,
        "00",
        receipt=receipt,
    )
    for exact_resolution, extras in (
        (resolution, None),
        (alias_resolution, None),
        (static_resolution, None),
        (resolved, {"receipt": receipt}),
    ):
        _assert_exact_type_mutations_rejected(
            exact_resolution,
            replace_extras=extras,
        )

    receipt_subclass = _receipt(
        dynamic_binding,
        "00",
        "0022500001",
        receipt_type=_ReceiptSubclass,
    )
    assert type(receipt_subclass) is _ReceiptSubclass
    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(resolved, receipt=receipt_subclass)
    with pytest.raises(NbaApiImplicitCompetitionError):
        resolve_implicit_competition(
            _StringSubclass(dynamic_binding.physical_endpoint_key),
            "00",
        )
    with pytest.raises(NbaApiImplicitCompetitionError):
        resolve_implicit_competition(
            dynamic_binding.physical_endpoint_key,
            _StringSubclass("00"),
        )


def test_authority_rejects_root_not_exposed_relabelled_upstream_unavailable() -> None:
    cell = next(
        item
        for item in _authority().physical_competition_cells
        if item.root_state == "root_not_exposed"
    )
    resolution = resolve_implicit_competition(cell.physical_endpoint_key, cell.league_id)

    assert resolution.resolution_state == "root_not_exposed"
    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(cell, root_state="upstream_unavailable")
    with pytest.raises(NbaApiImplicitCompetitionError):
        replace(resolution, resolution_state="upstream_unavailable")


def test_authority_rejects_noncanonical_or_unknown_checked_resource_fields(
    tmp_path: Path,
) -> None:
    payload = build_pinned_implicit_competition_payload()
    unknown = dict(payload)
    unknown["unexpected"] = "forbidden"
    unknown_path = tmp_path / "unknown.json"
    unknown_path.write_bytes(_sealed_checked_payload(unknown))
    noncanonical_path = tmp_path / "noncanonical.json"
    noncanonical_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(NbaApiImplicitCompetitionError):
        load_pinned_implicit_competition_payload(unknown_path)
    with pytest.raises(NbaApiImplicitCompetitionError):
        load_pinned_implicit_competition_payload(noncanonical_path)


def test_dynamic_request_root_requires_receipt_before_competition_resolution() -> None:
    binding = _binding(root_kind="game", root_mode="request_parameter")

    unresolved = resolve_implicit_competition(binding.physical_endpoint_key, "00")
    receipt = _receipt(binding, "00", "0022500001")
    resolved = resolve_implicit_competition(
        binding.physical_endpoint_key,
        "00",
        receipt=receipt,
    )

    assert unresolved.resolution_state == "root_receipt_required"
    assert unresolved.root_value is None
    assert resolved.resolution_state == "competition_resolved"
    assert resolved.root_value == "0022500001"
    assert resolved.receipt_sha256 == receipt.receipt_sha256


def test_same_game_id_under_two_competitions_remains_distinct() -> None:
    binding = _binding(root_kind="game", root_mode="request_parameter")
    root_value = "0022500001"
    nba = _receipt(binding, "00", root_value)
    wnba = _receipt(binding, "10", root_value)

    nba_resolution = resolve_implicit_competition(
        binding.physical_endpoint_key,
        "00",
        receipt=nba,
    )
    wnba_resolution = resolve_implicit_competition(
        binding.physical_endpoint_key,
        "10",
        receipt=wnba,
    )

    assert nba_resolution.root_value == wnba_resolution.root_value == root_value
    assert nba_resolution.league_id == "00"
    assert wnba_resolution.league_id == "10"
    assert nba_resolution.cell_id != wnba_resolution.cell_id
    assert nba_resolution.receipt_sha256 != wnba_resolution.receipt_sha256


def test_same_team_or_player_id_under_two_competitions_remains_distinct() -> None:
    for root_kind, root_value in (("team", 1610612737), ("player", 2544)):
        binding = _binding(root_kind=root_kind, root_mode="request_parameter")
        nba = _receipt(binding, "00", root_value)
        wnba = _receipt(binding, "10", root_value)
        nba_resolution = resolve_implicit_competition(
            binding.physical_endpoint_key,
            "00",
            receipt=nba,
        )
        wnba_resolution = resolve_implicit_competition(
            binding.physical_endpoint_key,
            "10",
            receipt=wnba,
        )

        assert nba_resolution.root_value == wnba_resolution.root_value == root_value
        assert nba_resolution.cell_id != wnba_resolution.cell_id
        assert nba_resolution.receipt_sha256 != wnba_resolution.receipt_sha256


def test_live_odds_classifies_each_result_by_receipted_game() -> None:
    binding = _binding(root_mode="response_game_join")
    first = _receipt(binding, "00", "0022500001", row_ordinal=0)
    second = _receipt(binding, "10", "1022500001", row_ordinal=1)

    first_resolution = resolve_implicit_competition(
        binding.physical_endpoint_key,
        "00",
        receipt=first,
    )
    second_resolution = resolve_implicit_competition(
        binding.physical_endpoint_key,
        "10",
        receipt=second,
    )

    assert first_resolution.root_value == "0022500001"
    assert second_resolution.root_value == "1022500001"
    assert first_resolution.receipt_sha256 != second_resolution.receipt_sha256


def test_live_scoreboard_requires_observed_league_and_game_root_agreement() -> None:
    binding = _binding(root_mode="response_game_collection")
    receipt = _receipt(binding, "10", "1022500001")
    resolution = resolve_implicit_competition(
        binding.physical_endpoint_key,
        "10",
        receipt=receipt,
    )

    assert resolution.resolution_state == "competition_resolved"
    assert resolution.league_id == "10"
    with pytest.raises(NbaApiImplicitCompetitionError):
        _receipt(
            binding,
            "10",
            "1022500001",
            variant_updates={"captured_league_id": "00"},
        )


def test_static_root_resolves_only_its_exact_bound_competition() -> None:
    binding = next(
        item
        for item in _authority().endpoint_bindings
        if item.physical_endpoint_key == "static:static_players"
    )
    exact = resolve_implicit_competition(binding.physical_endpoint_key, "00")
    foreign = resolve_implicit_competition(binding.physical_endpoint_key, "10")

    assert exact.resolution_state == "competition_resolved"
    assert exact.static_chain_sha256 == binding.root_requirement.static_chain_sha256
    assert foreign.resolution_state == "root_not_exposed"
    assert foreign.provider_availability_status == "unknown"
    with pytest.raises(NbaApiImplicitCompetitionError):
        resolve_implicit_competition(
            binding.physical_endpoint_key,
            "00",
            receipt=_receipt(
                _binding(root_kind="game", root_mode="request_parameter"),
                "00",
                "0022500001",
            ),
        )


def test_every_resolution_keeps_provider_availability_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("implicit competition authority attempted provider I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", _network_forbidden)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", _network_forbidden)
    authority = _authority()
    resolutions = [
        resolve_implicit_competition(item.physical_endpoint_key, item.league_id)
        for item in authority.physical_competition_cells
    ]

    assert {item.provider_availability_status for item in resolutions} == {"unknown"}
    assert {item.endpoint_support_status for item in resolutions} == {"unknown"}
    assert {item.request_terminal_state for item in resolutions} == {"not_asserted"}
