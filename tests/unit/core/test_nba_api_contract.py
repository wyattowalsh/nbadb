from __future__ import annotations

from nbadb.core.nba_api_contract import build_endpoint_contract, contract_to_json


class SyntheticRuntimeEndpoint:
    endpoint = "syntheticruntimeendpoint"
    expected_data = {
        "PrimarySet": ["PLAYER_ID", "TEAM_ID"],
        "EmptyConditionalSet": [],
    }

    def __init__(
        self,
        season: str,
        player_id: int | None = None,
        location_nullable: str = "",
        proxy: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
        get_request: bool = True,
    ) -> None:
        self.season = season
        self.player_id = player_id

    def load_response(self) -> None:
        data_sets = {"PrimarySet": [], "MissingLoadResponseSet": []}
        self.primary = data_sets["PrimarySet"]
        self.missing = data_sets["MissingLoadResponseSet"]


def test_build_endpoint_contract_reads_runtime_metadata_and_source_warnings() -> None:
    contract = build_endpoint_contract(SyntheticRuntimeEndpoint)

    assert contract.runtime_class_name == "SyntheticRuntimeEndpoint"
    assert contract.endpoint_slug == "syntheticruntimeendpoint"
    assert contract.parameters == ("season", "player_id", "location_nullable")
    assert contract.required_parameters == ("season",)
    assert contract.nullable_parameters == ("player_id", "location_nullable")
    assert contract.warnings == (
        "load_response_result_sets_missing_expected_data:MissingLoadResponseSet",
    )
    assert [result_set.result_set_name for result_set in contract.result_sets] == [
        "PrimarySet",
        "EmptyConditionalSet",
    ]
    assert contract.result_sets[0].expected_columns == ("PLAYER_ID", "TEAM_ID")
    assert contract.result_sets[1].expected_columns == ()


def test_contract_to_json_preserves_result_set_order_and_columns() -> None:
    payload = contract_to_json(build_endpoint_contract(SyntheticRuntimeEndpoint))

    assert payload["runtime_class_name"] == "SyntheticRuntimeEndpoint"
    assert payload["parameters"] == ["season", "player_id", "location_nullable"]
    assert payload["result_sets"] == [
        {
            "runtime_class_name": "SyntheticRuntimeEndpoint",
            "result_set_index": 0,
            "result_set_name": "PrimarySet",
            "expected_columns": ["PLAYER_ID", "TEAM_ID"],
            "source": "expected_data",
            "confidence": "high",
        },
        {
            "runtime_class_name": "SyntheticRuntimeEndpoint",
            "result_set_index": 1,
            "result_set_name": "EmptyConditionalSet",
            "expected_columns": [],
            "source": "expected_data",
            "confidence": "high",
        },
    ]
