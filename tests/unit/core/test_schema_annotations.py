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
