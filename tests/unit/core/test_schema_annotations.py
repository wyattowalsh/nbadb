from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandera.polars as pa
import pytest

from nbadb.core import schema_annotations as annotations
from nbadb.core.field_docs import generated_field_description, humanize_field_name
from nbadb.core.schema_annotations import (
    ARTIFACT_FILENAMES,
    build_schema_annotation_artifacts,
    schema_annotation_strict_issues,
)
from nbadb.orchestrate.staging_map import STAGING_MAP
from nbadb.schemas.base import BaseSchema
from nbadb.schemas.registry import (
    _raw_schema_registry,
    _staging_schema_registry,
    _star_schema_registry,
)

if TYPE_CHECKING:
    from pathlib import Path


def _patch_schema_annotation_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raw: dict[str, type[BaseSchema]],
    staging: dict[str, type[BaseSchema]],
    star: dict[str, type[BaseSchema]] | None = None,
) -> None:
    monkeypatch.setattr(annotations, "_raw_schema_registry", lambda: raw)
    monkeypatch.setattr(annotations, "_staging_schema_registry", lambda: staging)
    monkeypatch.setattr(annotations, "_star_schema_registry", lambda: star or {})
    monkeypatch.setattr(annotations, "_staging_route_rows", lambda: [])
    monkeypatch.setattr(
        annotations,
        "_schema_helper_reconciliation",
        lambda: {
            "summary": {
                "inspected_schema_class_count": 0,
                "classification_counts": {},
                "public_helper_leak_count": 0,
                "public_table_counts": {
                    "raw": len(raw),
                    "staging": len(staging),
                    "star": len(star or {}),
                },
            },
            "public_helper_leaks": [],
            "classes": [],
        },
    )
    monkeypatch.setattr(
        annotations,
        "_transform_schema_parity",
        lambda: {
            "schema_table_count": len(star or {}),
            "transform_output_count": len(star or {}),
            "schema_without_transform": [],
            "transform_without_schema": [],
            "schema_without_transform_count": 0,
            "transform_without_schema_count": 0,
        },
    )


@pytest.fixture(scope="module")
def annotation_payload() -> dict[str, Any]:
    return build_schema_annotation_artifacts()


def test_schema_annotation_audit_reports_live_registry_gates(
    annotation_payload: dict[str, Any],
) -> None:
    payload = annotation_payload
    summary = payload["schema_annotation_audit"]["summary"]
    blocking_counts = summary["blocking_issue_counts"]

    assert summary["strict_pass"] is all(value == 0 for value in blocking_counts.values())
    if blocking_counts["raw_bronze_unresolved_useful_field_count"]:
        assert summary["sample_raw_bronze_unresolved_useful_fields"]
    assert summary["public_table_counts"] == {
        "raw": len(_raw_schema_registry()),
        "staging": len(_staging_schema_registry()),
        "star": len(_star_schema_registry()),
    }
    assert payload["staging_route_inventory"]["summary"]["route_count"] == len(STAGING_MAP)
    assert payload["staging_route_inventory"]["summary"]["unresolved_route_count"] == 0
    assert payload["raw_silver_gold_field_fate"]["summary"]["field_count"] > 0
    assert payload["silver_gold_feature_inventory"]["summary"]["column_count"] > 0


def test_schema_annotation_artifacts_include_requested_files(
    annotation_payload: dict[str, Any],
) -> None:
    payload = annotation_payload
    assert set(payload["schema_annotation_audit"]["artifact_files"]) == set(ARTIFACT_FILENAMES)
    assert set(payload) == set(ARTIFACT_FILENAMES)


def test_raw_fate_uses_raw_input_schema_routes(annotation_payload: dict[str, Any]) -> None:
    rows = annotation_payload["raw_silver_gold_field_fate"]["fields"]
    points_total = next(
        row
        for row in rows
        if row["source_table"] == "raw_live_play_by_play" and row["source_column"] == "points_total"
    )

    assert points_total["fate"] == "staged_same_name"
    assert points_total["lineage_match_status"] == "verified"
    assert points_total["lineage_match_basis"] == "raw_input_schema_route"
    assert points_total["verified_staging_tables"] == ["stg_live_play_by_play"]
    assert points_total["requires_followup"] is False


def test_raw_fate_classifies_known_legacy_alias(annotation_payload: dict[str, Any]) -> None:
    rows = annotation_payload["raw_silver_gold_field_fate"]["fields"]
    turnover_pct = next(
        row
        for row in rows
        if row["source_table"] == "raw_box_score_advanced_player"
        and row["source_column"] == "tm_tov_pct"
    )

    assert turnover_pct["fate"] == "staged_renamed"
    assert turnover_pct["lineage_match_status"] == "classified"
    assert turnover_pct["lineage_match_basis"] == "known_legacy_alias"
    assert turnover_pct["classified_staging_columns"] == [
        {"table_name": "stg_box_score_advanced_player", "column_name": "tov_pct"}
    ]
    assert turnover_pct["requires_followup"] is False


def test_raw_fate_classifies_player_career_regular_mirror(
    annotation_payload: dict[str, Any],
) -> None:
    rows = annotation_payload["raw_silver_gold_field_fate"]["fields"]
    points = next(
        row
        for row in rows
        if row["source_table"] == "raw_player_career_stats" and row["source_column"] == "pts"
    )

    assert points["fate"] == "staged_same_name"
    assert points["lineage_match_status"] == "classified"
    assert points["lineage_match_basis"] == "known_player_career_regular_route"
    assert points["verified_staging_tables"] == ["stg_player_career_regular"]
    assert points["requires_followup"] is False


def test_schema_annotation_classifies_effective_fg_pct_as_box_score_measure(
    annotation_payload: dict[str, Any],
) -> None:
    columns = annotation_payload["silver_gold_feature_inventory"]["columns"]
    efg_rows = [
        row
        for row in columns
        if row["table_name"] == "fact_box_score_four_factors"
        and row["column_name"] == "effective_field_goal_percentage"
    ]

    assert efg_rows
    assert efg_rows[0]["semantic_primary"] == "box_score_measures"


def test_schema_annotation_audit_blocks_when_required_bronze_contracts_missing() -> None:
    payload = build_schema_annotation_artifacts(require_bronze_contracts=True)
    summary = payload["schema_annotation_audit"]["summary"]

    assert summary["blocking_issue_counts"]["bronze_contract_missing_count"] == 1
    assert summary["strict_pass"] is False
    assert "bronze_contract_missing_count=1" in schema_annotation_strict_issues(payload)


@pytest.mark.parametrize(
    ("zero_column_summary", "expected_strict_pass"),
    [
        (
            {
                "zero_column_table_count": 2,
                "classified_zero_column_table_count": 2,
                "blocking_zero_column_table_count": 0,
            },
            True,
        ),
        (
            {
                "zero_column_table_count": 1,
                "classified_zero_column_table_count": 0,
                "blocking_zero_column_table_count": 1,
            },
            False,
        ),
        ({"zero_column_table_count": 1}, False),
    ],
)
def test_schema_annotation_strict_uses_only_blocking_zero_column_contracts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    zero_column_summary: dict[str, int],
    expected_strict_pass: bool,
) -> None:
    bronze_path = tmp_path / "bronze.json"
    bronze_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "summary": {"table_count": 1, **zero_column_summary},
                "tables": [
                    {
                        "bronze_table": "bronze_static_reference",
                        "source_family": "static",
                        "endpoint": "players",
                        "result_set_name": "shape_1",
                        "columns": [{"name": "record_id"}],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _patch_schema_annotation_sources(monkeypatch, raw={}, staging={}, star={})

    payload = build_schema_annotation_artifacts(bronze_contracts_path=bronze_path)
    summary = payload["schema_annotation_audit"]["summary"]
    classified_count = zero_column_summary.get("classified_zero_column_table_count", 0)
    blocking_count = max(
        zero_column_summary.get("blocking_zero_column_table_count", 0),
        zero_column_summary["zero_column_table_count"] - classified_count,
    )

    assert (
        summary["bronze_contract_zero_column_table_count"]
        == zero_column_summary["zero_column_table_count"]
    )
    assert summary["bronze_contract_classified_zero_column_table_count"] == classified_count
    assert summary["bronze_contract_blocking_zero_column_table_count"] == blocking_count
    assert (
        summary["blocking_issue_counts"]["bronze_contract_blocking_zero_column_table_count"]
        == blocking_count
    )
    assert "bronze_contract_zero_column_table_count" not in summary["blocking_issue_counts"]
    assert summary["strict_pass"] is expected_strict_pass
    assert (
        f"bronze_contract_blocking_zero_column_table_count={blocking_count}"
        in schema_annotation_strict_issues(payload)
    ) is bool(blocking_count)


def test_stats_bronze_fates_use_authoritative_route_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class StagingScheduleSchema(BaseSchema):
        game_date: str | None = pa.Field(nullable=True)

    class StagingSynergySchema(BaseSchema):
        to_pct: float | None = pa.Field(nullable=True)

    class StagingOpenLeadersSchema(BaseSchema):
        player_id: int | None = pa.Field(nullable=True)

    bronze_path = tmp_path / "bronze.json"
    bronze_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "summary": {"table_count": 4},
                "tables": [
                    {
                        "bronze_table": "bronze_schedule",
                        "source_family": "stats",
                        "endpoint": "ScheduleLeagueV2",
                        "result_set_name": "Schedule",
                        "columns": [{"name": "gameDate"}],
                    },
                    {
                        "bronze_table": "bronze_synergy",
                        "source_family": "stats",
                        "endpoint": "SynergyPlayTypes",
                        "result_set_name": "Synergy",
                        "columns": [{"name": "TOV_POSS_PCT"}],
                    },
                    {
                        "bronze_table": "bronze_open_leaders",
                        "source_family": "stats",
                        "endpoint": "LeagueLeaders",
                        "result_set_name": "LeagueLeaders",
                        "columns": [{"name": "PTS"}],
                    },
                    {
                        "bronze_table": "bronze_superseded",
                        "source_family": "stats",
                        "endpoint": "BoxScoreMiscV2",
                        "result_set_name": "PlayerStats",
                        "columns": [{"name": "points"}],
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    provenance = {
        "routes": [
            {
                "endpoint_name": "schedule",
                "runtime_class_name": "ScheduleLeagueV2",
                "source_result_set_name": "Schedule",
                "source_result_set_index": 1,
                "declared_result_set_index": 0,
                "staging_key": "stg_schedule",
                "source_column": "gameDate",
                "normalized_column": "game_date",
                "schema_behavior": "closed",
                "route_status": "declared",
            },
            {
                "endpoint_name": "synergy_play_types",
                "runtime_class_name": "SynergyPlayTypes",
                "source_result_set_name": "Synergy",
                "source_result_set_index": 0,
                "declared_result_set_index": 0,
                "staging_key": "stg_synergy",
                "source_column": "TOV_POSS_PCT",
                "normalized_column": "to_pct",
                "schema_behavior": "closed",
                "route_status": "declared",
            },
            {
                "endpoint_name": "league_leaders",
                "runtime_class_name": "LeagueLeaders",
                "source_result_set_name": "LeagueLeaders",
                "source_result_set_index": 0,
                "declared_result_set_index": 0,
                "staging_key": "stg_open_leaders",
                "source_column": "PTS",
                "normalized_column": "pts",
                "schema_behavior": "passthrough",
                "route_status": "open_passthrough",
            },
        ],
        "superseded_runtime_classes": {"BoxScoreMiscV2": "BoxScoreMiscV3"},
        "summary": {
            "route_field_count": 3,
            "route_status_counts": {"declared": 2, "open_passthrough": 1},
            "blocking_route_field_count": 0,
        },
    }

    class FakeEndpointCoverageGenerator:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def build_schema_annotation_route_provenance(self) -> dict[str, Any]:
            return provenance

    _patch_schema_annotation_sources(
        monkeypatch,
        raw={},
        staging={
            "stg_schedule": StagingScheduleSchema,
            "stg_synergy": StagingSynergySchema,
            "stg_open_leaders": StagingOpenLeadersSchema,
        },
        star={},
    )
    monkeypatch.setattr(annotations, "EndpointCoverageGenerator", FakeEndpointCoverageGenerator)

    rows, _ = annotations._bronze_fate_rows(
        ("staging", "star"),
        tmp_path / "endpoint-analysis",
        bronze_path,
    )
    rows_by_endpoint = {row["endpoint"]: row for row in rows}

    schedule = rows_by_endpoint["ScheduleLeagueV2"]
    assert schedule["fate"] == "staged_normalized"
    assert schedule["verified_staging_tables"] == ["stg_schedule"]
    assert schedule["contract_route_endpoint_names"] == ["schedule"]
    assert schedule["contract_route_result_set_names"] == ["Schedule"]
    assert schedule["contract_route_result_set_indices"] == [1]
    assert schedule["contract_route_declared_result_set_indices"] == [0]
    assert schedule["lineage_match_basis"] == "runtime_contract_declared_route"

    synergy = rows_by_endpoint["SynergyPlayTypes"]
    assert synergy["fate"] == "staged_renamed"
    assert synergy["classified_staging_columns"] == [
        {"table_name": "stg_synergy", "column_name": "to_pct"}
    ]

    open_field = rows_by_endpoint["LeagueLeaders"]
    assert open_field["fate"] == "staged_normalized"
    assert open_field["contract_route_statuses"] == ["open_passthrough"]
    assert open_field["lineage_match_basis"] == "runtime_contract_open_schema_route"

    superseded = rows_by_endpoint["BoxScoreMiscV2"]
    assert superseded["fate"] == "excluded_deprecated_or_superseded"
    assert superseded["superseded_by_runtime_class"] == "BoxScoreMiscV3"
    assert superseded["verified_staging_tables"] == []
    assert all(row["requires_followup"] is False for row in rows)


def test_live_bronze_fates_require_exact_packet_json_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class StagingLivePlayerSchema(BaseSchema):
        points: int | None = pa.Field(nullable=True)
        payload_json: str | None = pa.Field(nullable=True)

    class FactLivePlayerSchema(BaseSchema):
        points: int | None = pa.Field(nullable=True)
        payload_json: str | None = pa.Field(nullable=True)

    bronze_path = tmp_path / "bronze.json"
    bronze_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "summary": {"table_count": 3},
                "tables": [
                    {
                        "bronze_table": "bronze_live_players",
                        "source_family": "live",
                        "endpoint": "BoxScore",
                        "result_set_name": "game_hometeam_players_statistics",
                        "columns": [
                            {
                                "name": "points",
                                "json_path": "$.game.homeTeam.players.statistics.points",
                            },
                            {
                                "name": "assists",
                                "json_path": "$.game.homeTeam.players.statistics.assists",
                            },
                            {"name": "request", "json_path": "$.meta.request"},
                        ],
                    },
                    {
                        "bronze_table": "bronze_live_scoreboard_envelope",
                        "source_family": "live",
                        "endpoint": "ScoreBoard",
                        "result_set_name": "scoreboard",
                        "columns": [
                            {"name": "gameDate", "json_path": "$.scoreboard.gameDate"},
                            {
                                "name": "points",
                                "json_path": "$.scoreboard.gamesExtra.points",
                            },
                        ],
                    },
                    {
                        "bronze_table": "bronze_live_missing_path",
                        "source_family": "live",
                        "endpoint": "Odds",
                        "result_set_name": "games",
                        "columns": [{"name": "wins", "json_path": None}],
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _patch_schema_annotation_sources(
        monkeypatch,
        raw={},
        staging={
            "stg_live_box_score_player_stats_home": StagingLivePlayerSchema,
        },
        star={"fact_live_box_score_player": FactLivePlayerSchema},
    )

    rows, _ = annotations._bronze_fate_rows(("staging", "star"), None, bronze_path)
    rows_by_path = {row["json_path"]: row for row in rows}

    points = rows_by_path["$.game.homeTeam.players.statistics.points"]
    assert points["fate"] == "staged_same_name"
    assert points["lineage_match_basis"] == "live_packet_typed_projection"
    assert points["packet_json_root"] == "$.game.homeTeam.players"
    assert points["representation_column"] == "points"
    assert points["verified_staging_tables"] == ["stg_live_box_score_player_stats_home"]
    assert points["verified_star_tables"] == ["fact_live_box_score_player"]

    assists = rows_by_path["$.game.homeTeam.players.statistics.assists"]
    assert assists["fate"] == "staged_json_payload"
    assert assists["lineage_match_basis"] == "live_packet_json_path"
    assert assists["packet_json_root"] == "$.game.homeTeam.players"
    assert assists["representation_column"] == "payload_json"
    assert assists["requires_followup"] is False

    meta = rows_by_path["$.meta.request"]
    assert meta["fate"] == "excluded_non_analytic_payload"
    assert meta["requires_followup"] is False

    envelope = rows_by_path["$.scoreboard.gameDate"]
    assert envelope["fate"] == "raw_only_reference"
    assert envelope["lineage_match_status"] == "classified"
    assert envelope["requires_followup"] is False

    prefix_collision = rows_by_path["$.scoreboard.gamesExtra.points"]
    assert prefix_collision["fate"] == "blocked_needs_contract_work"
    assert prefix_collision["lineage_match_basis"] == "live_json_path_outside_packet_contract"
    assert prefix_collision["requires_followup"] is True

    missing_path = rows_by_path[None]
    assert missing_path["fate"] == "blocked_needs_contract_work"
    assert missing_path["lineage_match_basis"] == "live_json_path_missing"
    assert missing_path["requires_followup"] is True


def test_schema_annotation_strict_blocks_unmatched_raw_and_bronze_useful_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class RawUnmatchedStatsSchema(BaseSchema):
        points: int | None = pa.Field(nullable=True)

    bronze_path = tmp_path / "bronze.json"
    bronze_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "summary": {"table_count": 1},
                "tables": [
                    {
                        "bronze_table": "bronze_player_stats",
                        "endpoint": "BoxScore",
                        "result_set_name": "PlayerStats",
                        "columns": [{"name": "assists"}],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _patch_schema_annotation_sources(
        monkeypatch,
        raw={"raw_unmatched_stats": RawUnmatchedStatsSchema},
        staging={},
        star={},
    )

    payload = build_schema_annotation_artifacts(bronze_contracts_path=bronze_path)
    summary = payload["schema_annotation_audit"]["summary"]
    unresolved_rows = summary["sample_raw_bronze_unresolved_useful_fields"]

    assert summary["blocking_issue_counts"]["raw_bronze_unresolved_useful_field_count"] == 2
    assert summary["strict_pass"] is False
    assert "raw_bronze_unresolved_useful_field_count=2" in schema_annotation_strict_issues(payload)
    assert {row["source_layer"] for row in unresolved_rows} == {"raw_schema", "bronze_contract"}
    assert {row["lineage_match_status"] for row in unresolved_rows} == {"unresolved"}


def test_global_same_name_raw_match_is_candidate_not_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RawGenericStatsSchema(BaseSchema):
        points: int | None = pa.Field(nullable=True)

    class StagingUnrelatedStatsSchema(BaseSchema):
        points: int | None = pa.Field(nullable=True)

    _patch_schema_annotation_sources(
        monkeypatch,
        raw={"raw_generic_stats": RawGenericStatsSchema},
        staging={"stg_unrelated_stats": StagingUnrelatedStatsSchema},
        star={},
    )

    payload = build_schema_annotation_artifacts()
    field_row = payload["raw_silver_gold_field_fate"]["fields"][0]
    summary = payload["schema_annotation_audit"]["summary"]

    assert field_row["fate"] == "staged_same_name"
    assert field_row["candidate_staging_tables"] == ["stg_unrelated_stats"]
    assert field_row["verified_staging_tables"] == []
    assert field_row["lineage_match_status"] == "candidate_unverified"
    assert field_row["lineage_match_basis"] == "global_same_name"
    assert field_row["requires_followup"] is True
    assert summary["blocking_issue_counts"]["raw_bronze_unresolved_useful_field_count"] == 1
    assert summary["strict_pass"] is False


def test_schema_annotation_classifies_plural_stat_columns() -> None:
    expected_primary = {
        "points": "box_score_measures",
        "assists": "box_score_measures",
        "rebounds": "box_score_measures",
        "steals": "box_score_measures",
        "blocks": "box_score_measures",
        "turnovers": "box_score_measures",
        "wins": "schedule_standings_playoff_features",
        "losses": "schedule_standings_playoff_features",
    }

    for column_name, expected in expected_primary.items():
        semantic_primary, _ = annotations._semantic_category(
            tier="star",
            table_name="fact_plural_stats",
            column_name=column_name,
            metadata={},
        )

        assert semantic_primary == expected


def test_generated_field_labels_preserve_acronym_casing() -> None:
    assert humanize_field_name("nba_api_url") == "NBA API URL"
    assert generated_field_description("nba_api_url") == "NBA API URL value."


def test_star_fk_aliases_normalize_in_inherited_schema() -> None:
    schema = _star_schema_registry()["fact_play_by_play_v2"].to_schema()

    assert schema.columns["player1_id"].metadata["fk_ref"] == "dim_player.player_id"
    assert schema.columns["player1_team_id"].metadata["fk_ref"] == "dim_team.team_id"
    assert schema.columns["player2_id"].metadata["fk_ref"] == "dim_player.player_id"
    assert schema.columns["player2_team_id"].metadata["fk_ref"] == "dim_team.team_id"
    assert schema.columns["player3_id"].metadata["fk_ref"] == "dim_player.player_id"
    assert schema.columns["player3_team_id"].metadata["fk_ref"] == "dim_team.team_id"
