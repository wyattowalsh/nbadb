from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest
from nba_api.stats import endpoints as stats_endpoints
from nba_api.stats.endpoints import (
    DefenseHub,
    ScoreboardV2,
    VideoDetails,
    VideoDetailsAsset,
    VideoEvents,
)
from nba_api.stats.endpoints.videoeventsasset import VideoEventsAsset

from nbadb.core.nba_api_contract import (
    NbaApiEndpointContract,
    NbaApiResultSetContract,
    build_endpoint_contract,
    contract_from_json,
    contract_to_json,
    discover_endpoint_analysis_doc_contracts,
    endpoint_response_mode_contract,
)
from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts

_UNKNOWN_RUNTIME_CLASSES = (
    VideoDetails,
    VideoDetailsAsset,
    VideoEvents,
    VideoEventsAsset,
)
_EXACT_UNKNOWN_AUTHORITY = {
    "VideoDetails": {
        "module_name": "nba_api.stats.endpoints.videodetails",
        "endpoint_slug": "videodetails",
        "endpoint_contract_sha256": (
            "b50a6fdc8978b112fff011711af4ce944411c02be4840c2c1ad0c2f3d2065db0"
        ),
        "authority_sha256": ("e3293deb99dc63fe7c197c4383e18c8b77be63c403d5d63f8993a3d836075c1e"),
        "endpoint_doc_status": "documented_empty_result_inventory",
        "package_export_status": "package_exported",
    },
    "VideoDetailsAsset": {
        "module_name": "nba_api.stats.endpoints.videodetailsasset",
        "endpoint_slug": "videodetailsasset",
        "endpoint_contract_sha256": (
            "e211f645130087ed25bc93454a8d75a3ac48ae7d85981f15b2fd1a52bbcde609"
        ),
        "authority_sha256": ("9efc8cd99c90dd155038038ffd09662565c1392f52c02bff7b578bca099671f4"),
        "endpoint_doc_status": "documented_empty_result_inventory",
        "package_export_status": "package_exported",
    },
    "VideoEvents": {
        "module_name": "nba_api.stats.endpoints.videoevents",
        "endpoint_slug": "videoevents",
        "endpoint_contract_sha256": (
            "6635877fbe55e7e3d1ac42628299bd090cbfc0a3fa70d035c7fdab17785aab87"
        ),
        "authority_sha256": ("fae7ed13164fb5da586ca596d8931d0034d0f880462f05cad22686943c12476d"),
        "endpoint_doc_status": "documented_empty_result_inventory",
        "package_export_status": "package_exported",
    },
    "VideoEventsAsset": {
        "module_name": "nba_api.stats.endpoints.videoeventsasset",
        "endpoint_slug": "videoeventsasset",
        "endpoint_contract_sha256": (
            "983ff8abdba00ec041a13fac6da9b93ffac695693224e46f5c5152df3f0760d3"
        ),
        "authority_sha256": ("704f72be399bcbd3c3612ea7449460a5b11b29c5f8fc7f341e143c1440fc5107"),
        "endpoint_doc_status": "endpoint_doc_absent",
        "package_export_status": "direct_import_only",
    },
}


def _pinned_video_contract(name: str = "VideoDetails") -> NbaApiEndpointContract:
    return pinned_runtime_contracts()[name]


def test_exact_four_empty_endpoint_inventories_compile_as_unknown_dynamic() -> None:
    pinned = pinned_runtime_contracts()

    for runtime_cls in _UNKNOWN_RUNTIME_CLASSES:
        generated = build_endpoint_contract(runtime_cls)
        expected = _EXACT_UNKNOWN_AUTHORITY[runtime_cls.__name__]
        response = generated.response_contract

        assert contract_to_json(generated) == contract_to_json(pinned[runtime_cls.__name__])
        assert generated.result_sets == ()
        assert generated.parser_kind == "legacy_result_sets"
        assert generated.response_mode == "unknown_dynamic_response"
        assert response == endpoint_response_mode_contract(generated)
        assert response.module_name == expected["module_name"]
        assert response.endpoint_slug == expected["endpoint_slug"]
        assert response.provider_result_inventory == ("endpoint_expected_data_empty_unknown")
        assert response.observed_packet_mode == ("fail_closed_json_object_or_legacy_result_sets")
        assert response.endpoint_doc_status == expected["endpoint_doc_status"]
        assert response.package_export_status == expected["package_export_status"]
        assert response.endpoint_contract_sha256 == expected["endpoint_contract_sha256"]
        assert response.authority_sha256 == expected["authority_sha256"]


@pytest.mark.parametrize(
    ("endpoint_name", "result_set_name", "result_set_ordinal"),
    [
        ("DefenseHub", "DefenseHubStat10", 1),
        ("ScoreboardV2", "WinProbability", 9),
    ],
)
def test_named_zero_column_results_remain_declared_result_contracts(
    endpoint_name: str,
    result_set_name: str,
    result_set_ordinal: int,
) -> None:
    runtime_cls = DefenseHub if endpoint_name == "DefenseHub" else ScoreboardV2
    contract = build_endpoint_contract(runtime_cls)
    zero_result = contract.result_sets[result_set_ordinal]
    response = contract.response_contract

    assert zero_result.result_set_name == result_set_name
    assert zero_result.expected_columns == ()
    assert response.response_mode == "declared_result_sets"
    assert response.provider_result_inventory == "named_result_sets"
    assert response.observed_packet_mode == "declared_result_sets_only"
    assert response.endpoint_doc_status is None
    assert response.package_export_status is None


def test_unknown_dynamic_response_rejects_identity_and_shape_mutations() -> None:
    contract = _pinned_video_contract()
    fake_result = NbaApiResultSetContract(
        runtime_class_name="VideoDetails",
        result_set_index=0,
        result_set_name="Invented",
        expected_columns=(),
        source="manual_override",
        confidence="low",
    )
    mutations = (
        replace(contract, runtime_class_name="VideoEvents"),
        replace(contract, module_name="nba_api.stats.endpoints.videoevents"),
        replace(contract, endpoint_slug="videoevents"),
        replace(contract, parser_kind="custom_nested"),
        replace(contract, result_sets=(fake_result,)),
        replace(
            contract,
            runtime_class_name="GenericUnknown",
            module_name="nba_api.stats.endpoints.genericunknown",
            endpoint_slug="genericunknown",
        ),
    )

    for mutated in mutations:
        with pytest.raises(ValueError, match="unknown dynamic response"):
            endpoint_response_mode_contract(mutated)


def test_unknown_dynamic_authority_round_trip_and_digest_are_exact() -> None:
    for endpoint_name, expected in _EXACT_UNKNOWN_AUTHORITY.items():
        contract = _pinned_video_contract(endpoint_name)
        round_tripped = contract_from_json(contract_to_json(contract))

        assert round_tripped == contract
        assert round_tripped.response_contract == contract.response_contract
        assert (
            round_tripped.response_contract.endpoint_contract_sha256
            == (expected["endpoint_contract_sha256"])
        )
        assert round_tripped.response_contract.authority_sha256 == (
            contract.response_contract.authority_sha256
        )


def test_exact_package_export_status_preserves_direct_import_only_asset() -> None:
    declared = set(stats_endpoints.__all__)

    for runtime_cls in _UNKNOWN_RUNTIME_CLASSES:
        module_leaf = runtime_cls.__module__.rsplit(".", 1)[-1]
        expected = _EXACT_UNKNOWN_AUTHORITY[runtime_cls.__name__]
        exported = expected["package_export_status"] == "package_exported"

        assert (module_leaf in declared) is exported
        assert (getattr(stats_endpoints, runtime_cls.__name__, None) is runtime_cls) is exported
    assert getattr(stats_endpoints, "VideoEventsAsset", None) is None


def test_exact_source_docs_bind_three_empty_inventories_and_one_absence() -> None:
    raw_root = os.environ.get("NBADB_NBA_API_UPSTREAM_ROOT")
    if not raw_root:
        pytest.skip("exact-source docs validation requires NBADB_NBA_API_UPSTREAM_ROOT")
    root = Path(raw_root)
    docs = discover_endpoint_analysis_doc_contracts(root)

    for endpoint_name in ("VideoDetails", "VideoDetailsAsset", "VideoEvents"):
        assert docs[endpoint_name].result_sets == ()
        assert docs[endpoint_name].status == "success"
    assert "VideoEventsAsset" not in docs


def test_unrelated_declared_result_endpoint_cannot_be_rebound_as_unknown() -> None:
    declared = build_endpoint_contract(DefenseHub)
    rebound = replace(
        declared,
        runtime_class_name="VideoDetails",
        module_name="nba_api.stats.endpoints.videodetails",
        endpoint_slug="videodetails",
        result_sets=(),
    )

    with pytest.raises(ValueError, match="unknown dynamic response contract drifted"):
        endpoint_response_mode_contract(rebound)
