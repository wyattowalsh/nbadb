from __future__ import annotations

from typing import TYPE_CHECKING

from nbadb.core.nba_api_contract import (
    build_endpoint_contract,
    build_nba_api_bronze_contracts_from_bundle,
    build_nba_api_metadata_ledger,
    build_nba_api_upstream_contract_bundle,
    contract_to_json,
    discover_endpoint_analysis_doc_contracts,
    discover_live_endpoint_doc_contracts,
    discover_runtime_live_endpoint_contracts,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_endpoint_doc(
    root: Path,
    layout_parts: tuple[str, ...],
    filename: str,
    markdown: str,
) -> Path:
    docs_dir = root.joinpath(*layout_parts)
    docs_dir.mkdir(parents=True)
    path = docs_dir / filename
    path.write_text(markdown, encoding="utf-8")
    return path


def _minimal_endpoint_markdown(endpoint: str) -> str:
    return f"""# {endpoint}

## JSON
```json
{{
  "data_sets": {{
    "{endpoint}": ["ID"]
  }},
  "endpoint": "{endpoint}",
  "nullable_parameters": [],
  "parameters": [],
  "required_parameters": [],
  "status": "success"
}}
```
"""


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


def test_discover_endpoint_analysis_doc_contracts_reads_json_blocks(tmp_path: Path) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "playerawards.md",
        """# PlayerAwards

## JSON
```json
{
  "data_sets": {
    "PlayerAwards": ["PERSON_ID", "SEASON"]
  },
  "endpoint": "PlayerAwards",
  "nullable_parameters": [],
  "parameters": ["PlayerID"],
  "required_parameters": ["PlayerID"],
  "status": "success"
}
```
""",
    )

    contracts = discover_endpoint_analysis_doc_contracts(tmp_path)

    contract = contracts["PlayerAwards"]
    assert contract.runtime_class_name == "PlayerAwards"
    assert contract.endpoint_slug == "playerawards"
    assert contract.parameters == ("PlayerID",)
    assert contract.required_parameters == ("PlayerID",)
    assert contract.result_sets[0].result_set_name == "PlayerAwards"
    assert contract.result_sets[0].expected_columns == ("PERSON_ID", "SEASON")
    assert contract.result_sets[0].source == "endpoint_analysis_docs"


def test_contract_to_json_preserves_docs_metadata_and_lenient_patterns(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "playerindex.md",
        r"""# PlayerIndex

##### Endpoint URL
>[https://stats.nba.com/stats/playerindex](https://stats.nba.com/stats/playerindex)

##### Valid URL
> https://stats.nba.com/stats/playerindex?LeagueID=00&Season=2024-25

Last validated 2026-06-30

## JSON
```json
{
  "data_sets": {
    "PlayerIndex": ["PERSON_ID", "PLAYER_LAST_NAME"]
  },
  "endpoint": "PlayerIndex",
  "nullable_parameters": ["Season"],
  "parameter_patterns": {
    "LeagueID": null,
    "Season": "^(\d{4}-\d{2})$"
  },
  "parameters": ["LeagueID", "Season"],
  "required_parameters": ["LeagueID"],
  "status": "success"
}
```
""",
    )

    contracts = discover_endpoint_analysis_doc_contracts(tmp_path)
    contract = contracts["PlayerIndex"]

    assert contract.parameter_patterns == (
        ("LeagueID", None),
        ("Season", r"^(\d{4}-\d{2})$"),
    )
    assert contract.endpoint_url == "https://stats.nba.com/stats/playerindex"
    assert (
        contract.valid_url == "https://stats.nba.com/stats/playerindex?LeagueID=00&Season=2024-25"
    )
    assert contract.last_validated_date == "2026-06-30"
    assert contract.source_path == "docs/nba_api/stats/endpoints/playerindex.md"

    payload = contract_to_json(contract)
    assert payload["parameter_patterns"] == {
        "LeagueID": None,
        "Season": r"^(\d{4}-\d{2})$",
    }
    assert payload["endpoint_url"] == "https://stats.nba.com/stats/playerindex"
    assert payload["valid_url"] == (
        "https://stats.nba.com/stats/playerindex?LeagueID=00&Season=2024-25"
    )
    assert payload["last_validated_date"] == "2026-06-30"
    assert payload["source_path"] == "docs/nba_api/stats/endpoints/playerindex.md"
    assert payload["source_family"] == "stats"
    assert payload["status"] == "success"


def test_discover_endpoint_analysis_doc_contracts_reads_indented_json_sections(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "playerawards.md",
        """# PlayerAwards

##### Endpoint URL
> https://stats.nba.com/stats/playerawards

## JSON

    {
      "data_sets": {
        "PlayerAwards": ["PERSON_ID", "SEASON"]
      },
      "endpoint": "PlayerAwards",
      "nullable_parameters": [],
      "parameters": ["PlayerID"],
      "required_parameters": ["PlayerID"],
      "status": "success"
    }

Last validated 2020-08-16
""",
    )

    contracts = discover_endpoint_analysis_doc_contracts(tmp_path)
    contract = contracts["PlayerAwards"]

    assert contract.endpoint_url == "https://stats.nba.com/stats/playerawards"
    assert contract.last_validated_date == "2020-08-16"
    assert contract.result_sets[0].expected_columns == ("PERSON_ID", "SEASON")


def test_discover_endpoint_analysis_doc_contracts_handles_nested_data_sets(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "scheduleleaguev2.md",
        """# ScheduleLeagueV2

## JSON
```json
{
  "data_sets": {
    "ScheduleLeagueV2": ["GAME_ID", "GAME_DATE"],
    "SeasonWeeksNested": {
      "headers": ["SEASON_ID", "WEEK_NUMBER"],
      "rows": []
    },
    "Weeks": ["SEASON_ID", "WEEK_NUMBER"]
  },
  "endpoint": "ScheduleLeagueV2",
  "nullable_parameters": [],
  "parameters": ["LeagueID", "Season"],
  "required_parameters": ["LeagueID", "Season"],
  "status": "success"
}
```
""",
    )

    contracts = discover_endpoint_analysis_doc_contracts(tmp_path)
    contract = contracts["ScheduleLeagueV2"]

    assert [result_set.result_set_name for result_set in contract.result_sets] == [
        "ScheduleLeagueV2",
        "Weeks",
    ]
    assert contract.result_sets[0].expected_columns == ("GAME_ID", "GAME_DATE")
    assert contract.result_sets[1].expected_columns == ("SEASON_ID", "WEEK_NUMBER")
    assert [result_set.result_set_index for result_set in contract.result_sets] == [0, 1]


def test_discover_endpoint_analysis_doc_contracts_expands_grouped_data_sets(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "leaguedashplayershotlocations.md",
        """# LeagueDashPlayerShotLocations

## JSON
```json
{
  "data_sets": {
    "ShotLocations": [
      {
        "columnNames": ["Restricted Area", "Mid-Range"],
        "columnSpan": 3,
        "columnsToSkip": 5,
        "name": "SHOT_CATEGORY"
      },
      {
        "columnNames": [
          "PLAYER_ID",
          "PLAYER_NAME",
          "TEAM_ID",
          "TEAM_ABBREVIATION",
          "AGE",
          "FGM",
          "FGA",
          "FG_PCT",
          "FGM",
          "FGA",
          "FG_PCT"
        ],
        "columnSpan": 1,
        "name": "columns"
      }
    ]
  },
  "endpoint": "LeagueDashPlayerShotLocations",
  "nullable_parameters": [],
  "parameters": [],
  "required_parameters": [],
  "status": "success"
}
```
""",
    )

    contracts = discover_endpoint_analysis_doc_contracts(tmp_path)

    contract = contracts["LeagueDashPlayerShotLocations"]
    assert contract.result_sets[0].expected_columns == (
        "PLAYER_ID",
        "PLAYER_NAME",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "AGE",
        "restricted_area_fgm",
        "restricted_area_fga",
        "restricted_area_fg_pct",
        "mid_range_fgm",
        "mid_range_fga",
        "mid_range_fg_pct",
    )
    assert contract.warnings == ()


def test_discover_endpoint_analysis_doc_contracts_infers_missing_endpoint_from_title(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "scheduleleaguev2.md",
        """# ScheduleLeagueV2

Last validated 2025-01-14

## JSON
```json
{
  "data_sets": {
    "SeasonGames": ["gameId", "gameDate"],
    "SeasonWeeks": ["weekNumber", "weekName"]
  },
  "nullable_parameters": [],
  "parameter_patterns": {
    "LeagueID": null,
    "Season": null
  },
  "parameters": ["LeagueID", "Season"],
  "required_parameters": ["LeagueID", "Season"],
  "status": "success"
}
```
""",
    )

    contracts = discover_endpoint_analysis_doc_contracts(tmp_path)

    contract = contracts["ScheduleLeagueV2"]
    assert contract.endpoint_slug == "scheduleleaguev2"
    assert contract.last_validated_date == "2025-01-14"
    assert [result_set.result_set_name for result_set in contract.result_sets] == [
        "SeasonGames",
        "SeasonWeeks",
    ]


def test_discover_endpoint_analysis_doc_contracts_ignores_malformed_parameter_patterns(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "playerindex.md",
        """# PlayerIndex

## JSON
```json
{
  "data_sets": {
    "PlayerIndex": ["PERSON_ID"]
  },
  "endpoint": "PlayerIndex",
  "nullable_parameters": [],
  "parameter_patterns": ["not", "a", "mapping"],
  "parameters": ["LeagueID"],
  "required_parameters": ["LeagueID"],
  "status": "success"
}
```
""",
    )

    contracts = discover_endpoint_analysis_doc_contracts(tmp_path)

    assert contracts["PlayerIndex"].parameter_patterns == ()


def test_discover_live_endpoint_doc_contracts_reads_live_docs(tmp_path: Path) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "live", "endpoints"),
        "scoreboard.md",
        """# ScoreBoard

##### Endpoint URL
>[https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json]

## JSON
```json
{
  "scoreboard": {
    "gameDate": "2026-06-30",
    "games": []
  }
}
```

Last validated 2020-08-16
""",
    )

    contracts = discover_live_endpoint_doc_contracts(tmp_path)

    contract = contracts["ScoreBoard"]
    assert contract.source_family == "live"
    assert contract.endpoint_slug == "scoreboard"
    assert contract.endpoint_url == (
        "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    )
    assert contract.last_validated_date == "2020-08-16"
    assert contract.source_path == "docs/nba_api/live/endpoints/scoreboard.md"


def test_build_nba_api_upstream_contract_bundle_counts_docs_tools_and_fixtures(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "playerawards.md",
        """# PlayerAwards

##### Endpoint URL
> https://stats.nba.com/stats/playerawards

## Parameters
API Parameter Name | Python Parameter Variable | Pattern | Required | Nullable
------------ | ------------ | :-----------: | :---: | :---:
[_**PlayerID**_](parameters.md#PlayerID) | player_id | `^\\d+$` | `Y` |

## Data Sets
#### PlayerAwards `player_awards`
```text
["PERSON_ID", "SEASON"]
```

## JSON
```json
{
  "data_sets": {
    "PlayerAwards": ["PERSON_ID", "SEASON"]
  },
  "endpoint": "PlayerAwards",
  "nullable_parameters": [],
  "parameters": ["PlayerID"],
  "required_parameters": ["PlayerID"],
  "status": "success"
}
```
""",
    )
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "live", "endpoints"),
        "scoreboard.md",
        """# ScoreBoard

## JSON
```json
{"scoreboard": {"games": []}}
```

## Data Sets
#### Games `games`
```text
["gameId", "gameStatusText"]
```

## About `Games` Data Set
Key | Class | Sample | Description | AlwaysPresent |
------------ | ------------ | :-----------: | :------------------: | :---------:
`gameId`|`<class 'str'>`| `0022400001` | `NBA game id` | `Yes` |
`gameStatusText`|`<class 'str'>`| `Final` | `Status label` | `No` |
""",
    )
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "static"),
        "players.md",
        """# players.py

## `_get_player_dict`(_`player_row`_)
```python
player = {
    'id': player_id,
    'full_name': full_name,
    'is_active': True,
}
```
Returns a player dictionary.
""",
    )
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "library"),
        "parameters.md",
        """# Endpoint Parameters

## _PlayerID_

#### Class `PlayerID`
##### Patterns
 - `^\\d+$`

Variable Name | Value
------------ | -------------
_**player_id**_ `default` | `0`
""",
    )
    output_dir = tmp_path / "docs" / "nba_api" / "stats" / "endpoints_output"
    output_dir.mkdir(parents=True)
    (output_dir / "playerawards_output.md").write_text(
        "PlayerAwards:\n\n| ID | SEASON |\n| --- | --- |\n| 1 | 2024-25 |\n",
        encoding="utf-8",
    )
    responses_dir = tmp_path / "docs" / "nba_api" / "stats" / "endpoints" / "responses"
    responses_dir.mkdir(parents=True)
    (responses_dir / "playerawards.json").write_text("{}\n", encoding="utf-8")
    tools_dir = tmp_path / "tools" / "stats"
    tools_dir.mkdir(parents=True)
    (tools_dir / "mapping.py").write_text(
        "endpoint_list = ['PlayerAwards']\n"
        "parameter_variations = {'PlayerID': {'default_py_value': None}}\n"
        "parameter_map = {'PlayerID': PlayerID}\n",
        encoding="utf-8",
    )

    bundle = build_nba_api_upstream_contract_bundle(tmp_path)

    assert bundle["enabled"] is True
    assert len(bundle["bundle_digest"]) == 64
    inventory = bundle["source_inventory"]
    assert inventory["stats_endpoint_doc_count"] == 1
    assert inventory["parsed_stats_contract_count"] == 1
    assert inventory["live_endpoint_doc_count"] == 1
    assert inventory["parsed_live_contract_count"] >= 4
    assert inventory["static_doc_count"] == 1
    assert inventory["parameter_library_doc_count"] == 1
    assert inventory["endpoint_output_doc_count"] == 1
    assert inventory["response_fixture_count"] == 1
    assert inventory["tools_python_file_count"] == 1
    assert inventory["stats_endpoint_metadata_count"] == 1
    assert inventory["stats_result_set_metadata_count"] == 1
    assert inventory["stats_column_metadata_count"] == 2
    assert inventory["live_endpoint_metadata_count"] >= 4
    assert inventory["live_field_metadata_count"] > 0
    assert inventory["static_function_doc_count"] == 1
    assert inventory["parameter_library_entry_count"] == 1
    assert inventory["endpoint_output_sample_column_count"] == 2
    assert inventory["tools_endpoint_list_count"] == 1
    assert inventory["tools_endpoint_missing_docs_count"] == 0
    assert inventory["docs_endpoint_missing_tools_count"] == 0
    assert bundle["stats_contracts"][0]["source_path"] == (
        "docs/nba_api/stats/endpoints/playerawards.md"
    )
    live_contracts_by_name = {
        contract["runtime_class_name"]: contract for contract in bundle["live_contracts"]
    }
    assert {"BoxScore", "Odds", "PlayByPlay", "ScoreBoard"} <= set(live_contracts_by_name)
    assert live_contracts_by_name["ScoreBoard"]["source_family"] == "live"
    assert live_contracts_by_name["ScoreBoard"]["endpoint_url"].endswith("todaysScoreboard_00.json")
    assert live_contracts_by_name["ScoreBoard"]["source_path"] == (
        "nba_api.live.nba.endpoints.scoreboard.ScoreBoard"
    )
    assert bundle["source_files"]["stats_endpoint_docs"] == [
        "docs/nba_api/stats/endpoints/playerawards.md"
    ]
    assert bundle["source_files"]["live_endpoint_docs"] == [
        "docs/nba_api/live/endpoints/scoreboard.md"
    ]
    assert (
        len(
            bundle["source_file_digests"]["endpoint_output_docs"][
                "docs/nba_api/stats/endpoints_output/playerawards_output.md"
            ]
        )
        == 64
    )
    assert (
        len(
            bundle["source_file_digests"]["response_fixtures"][
                "docs/nba_api/stats/endpoints/responses/playerawards.json"
            ]
        )
        == 64
    )
    assert len(bundle["source_file_digests"]["tools"]["tools/stats/mapping.py"]) == 64
    assert bundle["metadata_ledger"]["summary"]["metadata_ingestion_warning_count"] == 0
    assert (
        bundle["metadata_ledger"]["stats_endpoint_metadata"][0]["parameters"][0][
            "api_parameter_name"
        ]
        == "PlayerID"
    )
    live_metadata_by_endpoint = {
        endpoint["endpoint"]: endpoint
        for endpoint in bundle["metadata_ledger"]["live_endpoint_metadata"]
    }
    assert live_metadata_by_endpoint["ScoreBoard"]["data_sets"]
    assert all(
        data_set["field_count"] > 0
        for endpoint in live_metadata_by_endpoint.values()
        for data_set in endpoint["data_sets"]
    )
    assert bundle["metadata_ledger"]["static_doc_metadata"][0]["dictionary_shapes"][0]["keys"] == [
        "id",
        "full_name",
        "is_active",
    ]
    assert bundle["metadata_ledger"]["parameter_library"]["parameters"][0]["classes"] == [
        "PlayerID"
    ]
    bronze_contracts = build_nba_api_bronze_contracts_from_bundle(bundle)
    assert bronze_contracts["summary"]["stats_table_count"] == 1
    assert bronze_contracts["summary"]["live_table_count"] > 0
    assert bronze_contracts["summary"]["static_table_count"] == 1
    assert bronze_contracts["summary"]["zero_column_table_count"] == 0
    assert bronze_contracts["summary"]["missing_description_count"] == 0
    assert (
        bronze_contracts["summary"]["described_column_count"]
        == (bronze_contracts["summary"]["column_count"])
    )
    assert bronze_contracts["summary"]["description_source_counts"]["generated"] > 0
    assert bronze_contracts["summary"]["table_count"] == (
        bronze_contracts["summary"]["stats_table_count"]
        + bronze_contracts["summary"]["live_table_count"]
        + bronze_contracts["summary"]["static_table_count"]
    )
    bronze_tables_by_name = {table["bronze_table"]: table for table in bronze_contracts["tables"]}
    assert "bronze_static_players_shape_1" in bronze_tables_by_name
    assert "bronze_stats_playerawards_playerawards" in bronze_tables_by_name
    player_awards_columns = {
        column["name"]: column
        for column in bronze_tables_by_name["bronze_stats_playerawards_playerawards"]["columns"]
    }
    assert player_awards_columns["PERSON_ID"]["description"]
    assert player_awards_columns["PERSON_ID"]["description_source"] == "generated"
    live_tables = [
        table for table in bronze_contracts["tables"] if table["source_family"] == "live"
    ]
    assert live_tables
    assert all(table["column_count"] > 0 for table in live_tables)
    assert all(
        column["source"] == "nba_api_live_expected_data"
        for table in live_tables
        for column in table["columns"]
    )
    assert "0022400001" not in {
        column["name"] for table in live_tables for column in table["columns"]
    }
    playbyplay_actions = bronze_tables_by_name["bronze_live_playbyplay_game_actions"]
    playbyplay_action_columns = {column["name"]: column for column in playbyplay_actions["columns"]}
    assert playbyplay_action_columns["qualifiers"]["sample_type"] == "array"
    assert playbyplay_action_columns["qualifiers"]["json_path"] == "$.game.actions.qualifiers"
    assert playbyplay_action_columns["qualifiers"]["description"]
    assert playbyplay_action_columns["qualifiers"]["description_source"] == "generated"


def test_build_nba_api_metadata_ledger_reconciles_tools_endpoint_list(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "playerawards.md",
        _minimal_endpoint_markdown("PlayerAwards"),
    )
    tools_dir = tmp_path / "tools" / "stats"
    tools_dir.mkdir(parents=True)
    (tools_dir / "mapping.py").write_text(
        "endpoint_list = ['MissingEndpoint']\n",
        encoding="utf-8",
    )

    ledger = build_nba_api_metadata_ledger(tmp_path)

    assert ledger["tools_reconciliation"] == {
        "tools_endpoint_missing_docs": ["MissingEndpoint"],
        "docs_endpoint_missing_tools": ["PlayerAwards"],
        "rows": [
            {
                "endpoint": "MissingEndpoint",
                "status": "tools_endpoint_missing_docs",
                "source": "tools_endpoint_list",
                "classification": "tools_inventory_endpoint_without_parsed_doc",
                "classification_reason": (
                    "tools/stats/library/mapping.py is an upstream endpoint inventory, "
                    "but the current docs tree does not expose a parsed endpoint contract for this "
                    "key."
                ),
                "blocking": False,
                "matched_docs_endpoint": None,
                "matched_tools_endpoint": "MissingEndpoint",
            },
            {
                "endpoint": "PlayerAwards",
                "status": "docs_endpoint_missing_tools",
                "source": "stats_endpoint_docs",
                "classification": "docs_contract_without_tools_inventory_key",
                "classification_reason": (
                    "The upstream docs tree exposes this endpoint contract, but the tools endpoint "
                    "inventory does not list the same normalized key."
                ),
                "blocking": False,
                "matched_docs_endpoint": "PlayerAwards",
                "matched_tools_endpoint": None,
            },
        ],
        "tools_endpoint_missing_docs_count": 1,
        "docs_endpoint_missing_tools_count": 1,
        "classified_mismatch_count": 2,
        "blocking_mismatch_count": 0,
        "blocking_tools_endpoint_missing_docs_count": 0,
        "blocking_docs_endpoint_missing_tools_count": 0,
    }
    assert ledger["summary"]["tools_endpoint_missing_docs_count"] == 1
    assert ledger["summary"]["docs_endpoint_missing_tools_count"] == 1
    assert ledger["summary"]["blocking_tools_docs_mismatch_count"] == 0


def test_build_nba_api_bronze_contracts_blocks_unclassified_zero_column_stats_tables() -> None:
    bundle = {
        "enabled": True,
        "bundle_digest": "digest",
        "metadata_ledger": {"metadata_digest": "metadata", "stats_endpoint_metadata": []},
        "stats_contracts": [
            {
                "runtime_class_name": "EmptyEndpoint",
                "endpoint_slug": "emptyendpoint",
                "parameters": [],
                "result_sets": [{"result_set_name": "EmptySet", "expected_columns": []}],
            }
        ],
    }

    bronze_contracts = build_nba_api_bronze_contracts_from_bundle(bundle)

    assert bronze_contracts["tables"] == []
    assert bronze_contracts["summary"]["stats_table_count"] == 0
    assert bronze_contracts["summary"]["zero_column_table_count"] == 1
    assert bronze_contracts["summary"]["classified_zero_column_table_count"] == 0
    assert bronze_contracts["summary"]["blocking_zero_column_table_count"] == 1
    assert bronze_contracts["skipped_zero_column_tables"] == [
        {
            "source_family": "stats",
            "endpoint": "EmptyEndpoint",
            "endpoint_slug": "emptyendpoint",
            "result_set_name": "EmptySet",
            "source_path": None,
            "reason": "zero_column_result_set_suppressed",
            "classification": "unclassified_zero_column_result_set",
            "classification_reason": (
                "No local evidence classifies this upstream zero-column result set."
            ),
            "blocking": True,
        }
    ]


def test_build_nba_api_bronze_contracts_classifies_known_zero_column_stats_tables() -> None:
    bundle = {
        "enabled": True,
        "bundle_digest": "digest",
        "metadata_ledger": {"metadata_digest": "metadata", "stats_endpoint_metadata": []},
        "stats_contracts": [
            {
                "runtime_class_name": "ScoreboardV2",
                "endpoint_slug": "scoreboardv2",
                "parameters": [],
                "result_sets": [{"result_set_name": "WinProbability", "expected_columns": []}],
            }
        ],
    }

    bronze_contracts = build_nba_api_bronze_contracts_from_bundle(bundle)

    assert bronze_contracts["summary"]["zero_column_table_count"] == 1
    assert bronze_contracts["summary"]["classified_zero_column_table_count"] == 1
    assert bronze_contracts["summary"]["blocking_zero_column_table_count"] == 0
    assert bronze_contracts["skipped_zero_column_tables"][0]["blocking"] is False
    assert (
        bronze_contracts["skipped_zero_column_tables"][0]["classification"]
        == "deprecated_upstream_empty_result_set"
    )


def test_build_nba_api_metadata_ledger_reports_disabled_without_docs_root() -> None:
    ledger = build_nba_api_metadata_ledger(None)

    assert ledger["enabled"] is False
    assert ledger["warnings"] == ["endpoint_analysis_docs_root_not_configured"]
    assert len(ledger["metadata_digest"]) == 64


def test_build_nba_api_upstream_contract_bundle_digest_ignores_absolute_root(
    tmp_path: Path,
) -> None:
    roots = (tmp_path / "first" / "nba_api", tmp_path / "second" / "nba_api")
    for root in roots:
        _write_endpoint_doc(
            root,
            ("docs", "nba_api", "stats", "endpoints"),
            "playerawards.md",
            _minimal_endpoint_markdown("PlayerAwards"),
        )

    first_bundle = build_nba_api_upstream_contract_bundle(roots[0])
    second_bundle = build_nba_api_upstream_contract_bundle(roots[1])

    assert first_bundle["docs_root"] != second_bundle["docs_root"]
    assert first_bundle["bundle_digest"] == second_bundle["bundle_digest"]


def test_build_nba_api_upstream_contract_bundle_digest_tracks_source_file_content(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "playerawards.md",
        _minimal_endpoint_markdown("PlayerAwards"),
    )
    output_dir = tmp_path / "docs" / "nba_api" / "stats" / "endpoints_output"
    output_dir.mkdir(parents=True)
    output_path = output_dir / "playerawards_output.md"
    output_path.write_text("PlayerAwards:\n\n| ID |\n", encoding="utf-8")
    responses_dir = tmp_path / "docs" / "nba_api" / "stats" / "endpoints" / "responses"
    responses_dir.mkdir(parents=True)
    response_path = responses_dir / "playerawards.json"
    response_path.write_text("{}\n", encoding="utf-8")
    tools_dir = tmp_path / "tools" / "stats"
    tools_dir.mkdir(parents=True)
    tool_path = tools_dir / "mapping.py"
    tool_path.write_text("endpoint_list = []\n", encoding="utf-8")

    base_digest = build_nba_api_upstream_contract_bundle(tmp_path)["bundle_digest"]
    output_path.write_text("PlayerAwards:\n\n| ID | SEASON |\n", encoding="utf-8")
    output_digest = build_nba_api_upstream_contract_bundle(tmp_path)["bundle_digest"]
    response_path.write_text('{"changed": true}\n', encoding="utf-8")
    response_digest = build_nba_api_upstream_contract_bundle(tmp_path)["bundle_digest"]
    tool_path.write_text("endpoint_list = ['PlayerAwards']\n", encoding="utf-8")
    tool_digest = build_nba_api_upstream_contract_bundle(tmp_path)["bundle_digest"]

    assert output_digest != base_digest
    assert response_digest != output_digest
    assert tool_digest != response_digest


def test_build_nba_api_upstream_contract_bundle_reports_malformed_stats_docs(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "stats", "endpoints"),
        "broken.md",
        """# Broken

## JSON
```json
{"data_sets":
```
""",
    )

    bundle = build_nba_api_upstream_contract_bundle(tmp_path)

    assert bundle["source_inventory"]["stats_endpoint_doc_count"] == 1
    assert bundle["source_inventory"]["parsed_stats_contract_count"] == 0
    assert bundle["malformed_stats_docs"] == [
        {
            "source_path": "docs/nba_api/stats/endpoints/broken.md",
            "reason": "json_payload_missing_or_invalid",
        }
    ]
    assert bundle["warnings"] == ["malformed_stats_docs_detected"]


def test_build_nba_api_metadata_ledger_warns_for_invalid_live_json(tmp_path: Path) -> None:
    (tmp_path / "tools").mkdir()
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "live", "endpoints"),
        "scoreboard.md",
        """# ScoreBoard

## JSON
```json
{"scoreboard":
```
""",
    )

    ledger = build_nba_api_metadata_ledger(tmp_path)

    assert ledger["summary"]["metadata_ingestion_warning_count"] == 1
    assert ledger["warnings"] == [
        {
            "source_path": "docs/nba_api/live/endpoints/scoreboard.md",
            "reason": "live_doc_json_payload_invalid",
        }
    ]


def test_live_bronze_contracts_use_runtime_expected_data_not_markdown_samples(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "live", "endpoints"),
        "boxscore.md",
        """# BoxScore

## Data Sets
#### Officials `officials`
```text
["personId", "name"]
```

## JSON
```json
{
  "game": {
    "arenaName": "TD Garden",
    "ticketsUrl": "https://example.invalid/tickets",
    "officials": [{"personId": 1, "name": "Sample Official"}]
  }
}
```
""",
    )

    bundle = build_nba_api_upstream_contract_bundle(tmp_path)
    bronze_contracts = build_nba_api_bronze_contracts_from_bundle(bundle)

    live_tables = [
        table for table in bronze_contracts["tables"] if table["source_family"] == "live"
    ]
    live_column_names = {column["name"] for table in live_tables for column in table["columns"]}
    assert live_tables
    assert all(table["column_count"] > 0 for table in live_tables)
    assert "TD Garden" not in live_column_names
    assert "https://example.invalid/tickets" not in live_column_names
    assert "Sample Official" not in live_column_names
    assert all(
        column["source"] == "nba_api_live_expected_data" and column["json_path"].startswith("$")
        for table in live_tables
        for column in table["columns"]
    )


def test_live_metadata_prefers_runtime_parameters_over_docs_supplement(
    tmp_path: Path,
) -> None:
    _write_endpoint_doc(
        tmp_path,
        ("docs", "nba_api", "live", "endpoints"),
        "playbyplay.md",
        """# PlayByPlay

## Parameters
API Parameter Name | Python Parameter Variable | Pattern | Required | Nullable
------------ | ------------ | :-----------: | :---: | :---:
BogusParam | bogus_param |  | `Y` |

## JSON
```json
{
  "game": {
    "actions": []
  }
}
```
""",
    )

    bundle = build_nba_api_upstream_contract_bundle(tmp_path)
    live_metadata_by_endpoint = {
        endpoint["endpoint"]: endpoint
        for endpoint in bundle["metadata_ledger"]["live_endpoint_metadata"]
    }
    playbyplay = live_metadata_by_endpoint["PlayByPlay"]

    runtime_parameter_names = {
        parameter["python_parameter_variable"] for parameter in playbyplay["parameters"]
    }
    supplement_parameter_names = {
        parameter["python_parameter_variable"]
        for parameter in playbyplay["docs_supplement"]["parameters"]
    }
    assert "game_id" in runtime_parameter_names
    assert "bogus_param" not in runtime_parameter_names
    assert supplement_parameter_names == {"bogus_param"}


def test_discover_runtime_live_endpoint_contracts_reads_expected_data() -> None:
    contracts = discover_runtime_live_endpoint_contracts()

    assert {"BoxScore", "Odds", "PlayByPlay", "ScoreBoard"} <= set(contracts)
    assert all(contract.source_family == "live" for contract in contracts.values())
    assert all(contract.result_sets for contract in contracts.values())
    assert all(
        result_set.source == "expected_data"
        for contract in contracts.values()
        for result_set in contract.result_sets
    )


def test_build_nba_api_upstream_contract_bundle_accepts_nested_docs_root_with_tools(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "nba_api"
    docs_root = repo_root / "docs"
    _write_endpoint_doc(
        docs_root,
        ("nba_api", "stats", "endpoints"),
        "playerawards.md",
        _minimal_endpoint_markdown("PlayerAwards"),
    )
    tools_dir = repo_root / "tools" / "stats"
    tools_dir.mkdir(parents=True)
    (tools_dir / "mapping.py").write_text("endpoint_list = []\n", encoding="utf-8")

    bundle = build_nba_api_upstream_contract_bundle(docs_root)

    assert bundle["source_inventory"]["parsed_stats_contract_count"] == 1
    assert bundle["source_inventory"]["tools_python_file_count"] == 1
    assert bundle["source_files"]["tools"] == ["../tools/stats/mapping.py"]


def test_build_nba_api_upstream_contract_bundle_does_not_treat_flat_stats_as_live_docs(
    tmp_path: Path,
) -> None:
    stats_root = tmp_path / "stats-endpoints"
    _write_endpoint_doc(
        stats_root,
        (),
        "playerawards.md",
        _minimal_endpoint_markdown("PlayerAwards"),
    )

    bundle = build_nba_api_upstream_contract_bundle(stats_root)

    assert bundle["source_inventory"]["parsed_stats_contract_count"] == 1
    assert bundle["source_inventory"]["live_endpoint_doc_count"] == 0
    assert bundle["source_inventory"]["parsed_live_contract_count"] >= 4
    assert all(contract["source_family"] == "live" for contract in bundle["live_contracts"])
    assert all(
        contract["source_path"].startswith("nba_api.live.nba.endpoints.")
        for contract in bundle["live_contracts"]
    )


def test_discover_endpoint_analysis_doc_contracts_accepts_supported_root_layouts(
    tmp_path: Path,
) -> None:
    layouts = (
        (
            tmp_path / "repo-layout",
            ("docs", "nba_api", "stats", "endpoints"),
            "RepoLayoutEndpoint",
        ),
        (
            tmp_path / "package-layout",
            ("nba_api", "stats", "endpoints"),
            "PackageLayoutEndpoint",
        ),
        (
            tmp_path / "flat-layout",
            (),
            "FlatLayoutEndpoint",
        ),
    )

    for root, layout_parts, endpoint in layouts:
        _write_endpoint_doc(
            root,
            layout_parts,
            f"{endpoint.lower()}.md",
            _minimal_endpoint_markdown(endpoint),
        )

        contracts = discover_endpoint_analysis_doc_contracts(root)

        assert set(contracts) == {endpoint}
        assert contracts[endpoint].endpoint_slug == endpoint.lower()
