from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from nba_api.live.nba.endpoints import PlayByPlay as LivePlayByPlay
from nba_api.stats.endpoints import LeagueGameLog, PlayByPlayV3

from nbadb.core.nba_api_contract import contract_from_json, contract_to_json
from nbadb.core.nba_api_provenance import (
    NBA_API_LIVE_CONTRACT_SHA256,
    NBA_API_RUNTIME_CONTRACT_COUNT,
    NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256,
    NBA_API_RUNTIME_CONTRACT_SHA256,
    NBA_API_STATIC_CONTRACT_SHA256,
    NBA_API_UPSTREAM_COMMIT,
)
from nbadb.core.nba_api_runtime_contract import (
    RUNTIME_CONTRACT_RESOURCE,
    LiveEndpointContract,
    StaticDatasetContract,
    build_pinned_runtime_contract_payload,
    endpoint_contract_sha256,
    load_pinned_runtime_contract_payload,
    owned_contract_sha256,
    pinned_endpoint_contract,
    pinned_live_contracts,
    pinned_live_endpoint_contract,
    pinned_runtime_contracts,
    pinned_static_contracts,
    pinned_static_dataset_contract,
    write_pinned_runtime_contract,
)


def _resource_path() -> Path:
    return Path(__file__).parents[3] / "src" / "nbadb" / "contracts" / RUNTIME_CONTRACT_RESOURCE


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _exact_upstream_root() -> Path:
    raw = os.environ.get("NBADB_NBA_API_UPSTREAM_ROOT")
    if not raw:
        pytest.skip("exact-source no-drift generation requires NBADB_NBA_API_UPSTREAM_ROOT")
    return Path(raw)


def test_generated_runtime_contract_matches_exact_tracked_resource() -> None:
    root = _exact_upstream_root()
    generated = build_pinned_runtime_contract_payload(root)
    loaded = load_pinned_runtime_contract_payload(_resource_path())

    assert generated == loaded
    assert generated["provider"]["commit_sha"] == NBA_API_UPSTREAM_COMMIT
    assert generated["summary"] == {
        "column_contract_count": 9513,
        "endpoint_contract_count": 139,
        "live_column_contract_count": 430,
        "live_endpoint_contract_count": 4,
        "live_parsed_column_contract_count": 431,
        "live_result_set_contract_count": 33,
        "result_set_contract_count": 376,
        "static_dataset_contract_count": 4,
        "static_modeled_dataset_contract_count": 4,
        "static_modeled_field_contract_count": 26,
        "static_out_of_scope_dataset_contract_count": 0,
    }
    assert generated["summary"]["endpoint_contract_count"] == (NBA_API_RUNTIME_CONTRACT_COUNT)
    assert generated["contracts_sha256"] == NBA_API_RUNTIME_CONTRACT_SHA256
    assert generated["live_contracts_sha256"] == NBA_API_LIVE_CONTRACT_SHA256
    assert generated["static_contracts_sha256"] == NBA_API_STATIC_CONTRACT_SHA256
    assert generated["payload_sha256"] == NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256
    assert (
        write_pinned_runtime_contract(
            _resource_path(),
            upstream_root=root,
            check=True,
        )
        is True
    )


def test_live_and_static_contracts_are_exact_source_owned() -> None:
    live = pinned_live_endpoint_contract(LivePlayByPlay)
    actions = next(result for result in live.result_sets if result.name == "game_actions")
    person_ids = next(
        result for result in live.result_sets if result.name == "game_actions_personidsfilter"
    )
    fields = [field.name for field in actions.fields]
    person_ids_field = next(field for field in actions.fields if field.name == "personIdsFilter")
    teams = pinned_static_dataset_contract("static_teams")
    wnba_players = pinned_static_dataset_contract("static_wnba_players")
    wnba_teams = pinned_static_dataset_contract("static_wnba_teams")
    odds = load_pinned_runtime_contract_payload()["live_contracts"]["Odds"]
    outcomes = next(
        result for result in odds["result_sets"] if result["name"] == "games_markets_books_outcomes"
    )
    outcome_fields = {field["name"]: field for field in outcomes["fields"]}

    assert len(fields) == 54
    assert fields[-1] == "value"
    assert (
        sum(
            1
            for contract in load_pinned_runtime_contract_payload()["live_contracts"].values()
            for result_set in contract["result_sets"]
            for field in result_set["fields"]
            if field["source_field"]
        )
        == 430
    )
    assert person_ids_field.runtime_sample_type == "array"
    assert person_ids_field.documented_types == ("array",)
    assert person_ids_field.drift_status == "runtime_and_docs"
    assert person_ids_field.nested_result_set_name == person_ids.name
    assert person_ids.traversal_path == (
        "game",
        "actions",
        "*",
        "personIdsFilter",
    )
    assert person_ids.parent_result_set_name == "game_actions"
    assert person_ids.fields[0].source_field is False
    assert person_ids.fields[0].documented_types is None
    assert person_ids.fields[0].runtime_sample_type == "integer"
    assert live.full_url_template.startswith("https://cdn.nba.com/")
    assert live.documented_url_drift == "docs_relative_runtime_canonicalized"
    assert live.parameters[0].pattern == r"^\d{10}$"
    assert outcome_fields["spread"]["documented_type"] == ["string", "null"]
    assert outcome_fields["opening_spread"]["documented_type"] == ["number", "null"]
    assert len(owned_contract_sha256(live)) == 64
    assert [field.name for field in teams.raw_fields][-1] == "championship_year"
    assert "championship_year" not in teams.projected_fields
    assert teams.raw_fields[-1].provider_projection_disposition == (
        "omitted_by_provider_projection"
    )
    assert teams.raw_fields[-1].model_disposition == "defined_and_implemented"
    assert teams.raw_fields[-1].extraction_coverage_effect == "none"
    assert teams.implementation_status == "complete"
    assert [field.name for field in wnba_players.raw_fields] == [
        "id",
        "last_name",
        "first_name",
        "full_name",
        "is_active",
    ]
    assert [field.name for field in wnba_teams.raw_fields] == [
        "id",
        "abbreviation",
        "nickname",
        "year_founded",
        "city",
        "full_name",
        "state",
        "championship_year",
    ]
    assert wnba_teams.raw_fields[-1].provider_projection_disposition == (
        "omitted_by_provider_projection"
    )
    assert all(
        contract.model_disposition == "defined_and_implemented"
        and contract.implementation_status == "complete"
        and {field.model_disposition for field in contract.raw_fields}
        == {"defined_and_implemented"}
        for contract in pinned_static_contracts().values()
    )


def test_custom_parser_inventory_is_generated_from_exact_provider_registry() -> None:
    payload = load_pinned_runtime_contract_payload()
    custom = {
        contract["endpoint_slug"]
        for contract in payload["contracts"].values()
        if contract["parser_kind"] == "custom_nested"
    }

    assert custom == {
        "boxscoreadvancedv3",
        "boxscoredefensivev2",
        "boxscorefourfactorsv3",
        "boxscorehustlev2",
        "boxscorematchupsv3",
        "boxscoremiscv3",
        "boxscoreplayertrackv3",
        "boxscorescoringv3",
        "boxscoresummaryv3",
        "boxscoretraditionalv3",
        "boxscoreusagev3",
        "gravityleaders",
        "iststandings",
        "playbyplayv3",
        "scheduleleaguev2",
        "scheduleleaguev2int",
        "scoreboardv3",
    }
    assert all(
        contract["parser_kind"] in {"legacy_result_sets", "custom_nested"}
        for contract in payload["contracts"].values()
    )


def test_live_and_static_owned_dtos_are_immutable_and_round_trip() -> None:
    stats_inventory = pinned_runtime_contracts()
    live_inventory = pinned_live_contracts()
    static_inventory = pinned_static_contracts()
    stats = stats_inventory["PlayByPlayV3"]
    live = live_inventory["PlayByPlay"]
    static = static_inventory["static_teams"]

    assert stats.runtime_class_name == "PlayByPlayV3"
    assert isinstance(live, LiveEndpointContract)
    assert isinstance(static, StaticDatasetContract)
    assert isinstance(live.result_sets, tuple)
    assert isinstance(static.raw_fields, tuple)
    assert LiveEndpointContract.from_json(live.to_json()) == live
    assert StaticDatasetContract.from_json(static.to_json()) == static
    with pytest.raises(TypeError):
        stats_inventory["PlayByPlayV3"] = stats  # type: ignore[index]
    with pytest.raises(TypeError):
        live_inventory["PlayByPlay"] = live  # type: ignore[index]
    with pytest.raises(TypeError):
        static_inventory["static_teams"] = static  # type: ignore[index]


def test_owned_dto_rejects_self_consistent_nested_type_drift() -> None:
    raw = pinned_live_endpoint_contract(LivePlayByPlay).to_json()
    field = next(
        item
        for result_set in raw["result_sets"]
        if result_set["name"] == "game_actions"
        for item in result_set["fields"]
        if item["name"] == "side"
    )
    field["documented_type"] = "stringnull"
    result_set = next(item for item in raw["result_sets"] if item["name"] == "game_actions")
    result_set["fields_sha256"] = _digest(result_set["fields"])
    body = dict(raw)
    body.pop("contract_sha256")
    raw["contract_sha256"] = _digest(body)

    with pytest.raises(ValueError, match="invalid JSON value type"):
        LiveEndpointContract.from_json(raw)


def test_loaded_endpoint_contract_is_owned_dto_with_stable_digest() -> None:
    contract = pinned_endpoint_contract(PlayByPlayV3)

    assert contract.runtime_class_name == "PlayByPlayV3"
    assert [result_set.result_set_name for result_set in contract.result_sets] == [
        "AvailableVideo",
        "PlayByPlay",
    ]
    assert contract.result_sets[1].expected_columns[-2:] == ("shotValue", "actionId")
    assert len(endpoint_contract_sha256(contract)) == 64
    assert contract_from_json(contract_to_json(contract)) == contract


def test_runtime_class_identity_drift_is_rejected() -> None:
    original_module = LeagueGameLog.__module__
    LeagueGameLog.__module__ = "nba_api.stats.endpoints.drifted"
    try:
        with pytest.raises(ValueError, match="identity drifted"):
            pinned_endpoint_contract(LeagueGameLog)
    finally:
        LeagueGameLog.__module__ = original_module


def test_payload_digest_and_contract_mutation_fail_closed(tmp_path: Path) -> None:
    payload = load_pinned_runtime_contract_payload(_resource_path())
    payload["contracts"]["LeagueGameLog"]["endpoint_slug"] = "drifted"
    path = tmp_path / "drifted.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="payload digest"):
        load_pinned_runtime_contract_payload(path)


@pytest.mark.parametrize("section", ["live_contracts", "static_contracts"])
def test_self_consistent_owned_contract_drift_is_rejected(
    tmp_path: Path,
    section: str,
) -> None:
    payload = load_pinned_runtime_contract_payload(_resource_path())
    identity = "BoxScore" if section == "live_contracts" else "static_teams"
    contract = payload[section][identity]
    contract["disposition_reason"] = "coordinated drift"
    body = dict(contract)
    body.pop("contract_sha256")
    contract["contract_sha256"] = _digest(body)
    payload[f"{section}_sha256"] = _digest(payload[section])
    payload_body = dict(payload)
    payload_body.pop("payload_sha256")
    payload["payload_sha256"] = _digest(payload_body)
    path = tmp_path / f"{section}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="payload disagrees with authority"):
        load_pinned_runtime_contract_payload(path)
