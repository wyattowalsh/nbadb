from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.core import model_audit as model_audit_module
from nbadb.core.model_audit import (
    AuditDecision,
    AuditMode,
    AuditRecord,
    AuditStrictness,
    ModelAuditEngine,
    compare_baseline,
)
from nbadb.orchestrate.staging_map import StagingEntry


def _schema_model(columns: dict[str, object]) -> type:
    class FakeSchemaModel:
        @classmethod
        def to_schema(cls) -> object:
            return SimpleNamespace(columns=columns)

    return FakeSchemaModel


class _FakeRegistry:
    def __init__(self, extractor_classes: list[object]) -> None:
        self._extractor_classes = extractor_classes
        self.count = len(extractor_classes)

    def discover(self) -> None:
        return None

    def get_all(self) -> list[object]:
        return list(self._extractor_classes)

    def get(self, endpoint_name: str) -> object:
        for extractor_cls in self._extractor_classes:
            if extractor_cls.endpoint_name == endpoint_name:
                return extractor_cls
        raise KeyError(endpoint_name)


def test_inventory_uses_runtime_class_rows_and_normalizes_stats_source_kind(tmp_path: Path) -> None:
    extractor_classes = [
        SimpleNamespace(endpoint_name="box_score_traditional", category="box_score"),
        SimpleNamespace(endpoint_name="static_players", category="static"),
        SimpleNamespace(endpoint_name="live_score_board", category="live"),
    ]
    fake_registry = _FakeRegistry(extractor_classes)
    staging_entries = [
        StagingEntry("box_score_traditional", "stg_box_score_traditional", "game"),
    ]
    transformers = [
        SimpleNamespace(
            output_table="fact_box_score",
            depends_on=["stg_box_score_traditional"],
        ),
        SimpleNamespace(
            output_table="fact_missing_schema",
            depends_on=["stg_box_score_traditional"],
        ),
    ]
    schema_columns = {
        "game_id": SimpleNamespace(
            nullable=False, metadata={"source": "stg_box_score_traditional.game_id"}
        ),
        "player_sk": SimpleNamespace(nullable=False, metadata={}),
        "loaded_at": SimpleNamespace(nullable=False, metadata={"source": "audit.loaded_at"}),
        "mystery_metric": SimpleNamespace(nullable=True, metadata={}),
    }
    schema_map = {
        "fact_box_score": _schema_model(schema_columns),
    }
    fake_coverage = SimpleNamespace(
        _discover_runtime_endpoint_classes=lambda: (
            ["BoxScoreTraditionalV2", "BoxScoreTraditionalV3"],
            "1.11.4",
        ),
        _discover_runtime_static_surfaces=lambda: {"players"},
        _discover_runtime_live_endpoint_classes=lambda: {"score_board"},
        _extractor_endpoint_map=lambda: {
            "box_score_traditional": {"endpoint": "box_score_traditional"}
        },
        _static_extractor_surfaces=lambda: {"players"},
        _live_extractor_surfaces=lambda: {"score_board"},
        _transform_catalog=lambda: ({}, {"fact_box_score", "fact_missing_schema"}),
    )

    engine = ModelAuditEngine(project_root=tmp_path)
    engine._coverage = fake_coverage

    with (
        patch.object(model_audit_module, "registry", fake_registry),
        patch.object(model_audit_module, "STAGING_MAP", staging_entries),
        patch.object(model_audit_module, "discover_all_transformers", return_value=transformers),
        patch.object(model_audit_module, "_star_schema_registry", return_value=schema_map),
        patch.object(
            model_audit_module,
            "get_output_schema",
            side_effect=lambda table_name: schema_map.get(table_name),
        ),
        patch.object(
            model_audit_module,
            "get_input_schema",
            side_effect=lambda table_name: (
                object() if table_name == "stg_box_score_traditional" else None
            ),
        ),
        patch.object(
            model_audit_module,
            "LineageGenerator",
            return_value=SimpleNamespace(generate_dict=lambda: {"fact_box_score": {}}),
        ),
    ):
        sections = engine._build_inventory_sections()

    runtime_stats_rows = [
        record for record in sections["runtime_surfaces"] if record.source_kind == "stats"
    ]
    assert sections["inventory_meta"]["runtime_stats_surface_count"] == 2
    assert sections["inventory_meta"]["runtime_stats_canonical_surface_count"] == 1
    assert [record.runtime_surface for record in runtime_stats_rows] == [
        "box_score_traditional_v2",
        "box_score_traditional_v3",
    ]
    assert {record.endpoint_name for record in runtime_stats_rows} == {"box_score_traditional"}
    assert {record.decision for record in runtime_stats_rows} == {AuditDecision.MODELED.value}
    assert all(record.details["is_runtime_alias"] is True for record in runtime_stats_rows)

    staging_record = sections["staging_surfaces"][0]
    assert staging_record.source_kind == "stats"
    assert staging_record.details["extractor_category"] == "box_score"
    assert staging_record.details["live_probe_status"] == "not_run"

    model_rows = {record.output_table: record for record in sections["model_surfaces"]}
    assert model_rows["fact_box_score"].decision == AuditDecision.MODELED.value
    assert model_rows["fact_missing_schema"].decision == AuditDecision.SCHEMA_GAP.value

    column_rows = {record.key: record for record in sections["column_contracts"]}
    assert column_rows["fact_box_score.game_id"].origin == "source"
    assert column_rows["fact_box_score.player_sk"].origin == "surrogate"
    assert column_rows["fact_box_score.loaded_at"].origin == "audit"
    assert (
        column_rows["fact_box_score.mystery_metric"].decision == AuditDecision.VALIDATION_GAP.value
    )


def test_compare_baseline_detects_new_problem_keys() -> None:
    current_summary = {
        "problem_keys": ["RuntimeSurface:stats:foo:source_gap"],
        "decision_breakdown": {"modeled": 1, "source_gap": 1},
    }
    baseline_summary = {
        "generated_at": "2026-03-28T00:00:00+00:00",
        "problem_keys": [],
        "decision_breakdown": {"modeled": 1},
    }

    comparison = compare_baseline(current_summary, baseline_summary)

    assert comparison["regression_detected"] is True
    assert comparison["new_problem_keys"] == ["RuntimeSurface:stats:foo:source_gap"]
    assert comparison["increased_problem_counts"] == {"source_gap": 1}


def test_write_emits_inventory_matrix_report_and_baseline_comparison(tmp_path: Path) -> None:
    engine = ModelAuditEngine(project_root=tmp_path)
    record = AuditRecord(
        layer="RuntimeSurface",
        key="stats:foo",
        decision=AuditDecision.MODELED.value,
        decision_reason="Modeled surface.",
        source_kind="stats",
        endpoint_name="foo",
        runtime_surface="foo",
    )
    inventory_meta = {
        "project_root": str(tmp_path),
        "runtime_version": "1.11.4",
        "runtime_stats_surface_count": 1,
        "runtime_stats_canonical_surface_count": 1,
        "runtime_static_surface_count": 0,
        "runtime_live_surface_count": 0,
        "extractor_count": 1,
        "extractor_category_breakdown": {"box_score": 1},
        "staging_entry_count": 0,
        "runtime_transform_output_count": 0,
        "legacy_transform_output_count": 0,
        "star_schema_count": 0,
        "legacy_runtime_only_outputs": [],
    }
    summary = {
        "generated_at": "2026-03-28T00:00:00+00:00",
        "inventory": inventory_meta,
        "discovery_issue_count": 0,
        "discovery_issues": [],
        "record_count": 1,
        "decision_breakdown": {"modeled": 1},
        "layer_breakdown": {"RuntimeSurface": {"modeled": 1}},
        "issue_breakdown": {},
        "problem_count": 0,
        "problem_keys": [],
    }
    sections = {
        "runtime_surfaces": [record],
        "staging_surfaces": [],
        "model_surfaces": [],
        "column_contracts": [],
        "records": [record],
        "inventory_meta": inventory_meta,
        "discovery_issues": [],
        "summary": summary,
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"summary": summary}) + "\n", encoding="utf-8")

    with patch.object(engine, "_build_inventory_sections", return_value=sections):
        written = engine.write(
            mode=AuditMode.INVENTORY,
            strictness=AuditStrictness.NO_REGRESSIONS,
            output_dir=tmp_path / "artifacts",
            baseline_path=baseline_path,
        )

    assert set(written) == {
        "inventory",
        "matrix",
        "report",
        "baseline_comparison",
    }
    inventory_payload = json.loads((tmp_path / "artifacts" / "inventory.json").read_text())
    matrix_payload = json.loads((tmp_path / "artifacts" / "matrix.json").read_text())
    baseline_payload = json.loads((tmp_path / "artifacts" / "baseline-comparison.json").read_text())

    assert inventory_payload["summary"]["problem_count"] == 0
    assert matrix_payload["matrix"][0]["key"] == "stats:foo"
    assert baseline_payload["comparison"]["regression_detected"] is False
