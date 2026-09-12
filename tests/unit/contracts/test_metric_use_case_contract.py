from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from nbadb.contracts import metric_use_case_contract as metric_module
from nbadb.contracts.metric_use_case_contract import (
    EXPECTED_COMPUTED_NUMERIC_ALIAS_COUNT,
    EXPECTED_EXPLICIT_STRUCTURAL_NONMETRIC_COUNT,
    EXPECTED_PUBLIC_NUMERIC_COLUMN_COUNT,
    MetricUseCaseContractCompilationError,
    metric_use_case_registry,
    validate_metric_use_case_registry,
)
from nbadb.contracts.star_table_contract import compile_star_table_contracts


def test_metric_registry_covers_exact_public_numeric_universe() -> None:
    registry = metric_use_case_registry()
    star = compile_star_table_contracts()
    expected = [
        (table.output_name, column.name, column.ordinal)
        for table in star.tables
        for column in table.columns
        if column.data_type in {"Float64", "Int64"}
    ]

    assert len(expected) == EXPECTED_PUBLIC_NUMERIC_COLUMN_COUNT == 4_651
    assert len(registry.metrics) == len(expected)
    assert [(m.table_name, m.column_name, m.column_ordinal) for m in registry.metrics] == expected
    assert registry.kind_counts == (
        (
            "explicit_structural_nonmetric",
            EXPECTED_EXPLICIT_STRUCTURAL_NONMETRIC_COUNT,
        ),
        ("unreviewed_numeric_candidate", 4_305),
    )
    assert registry.expression_counts == (
        ("computed_numeric_alias", EXPECTED_COMPUTED_NUMERIC_ALIAS_COUNT),
        ("no_computed_expression_evidence", 4_461),
    )


def test_registry_finds_exact_computed_aliases_across_nested_sql() -> None:
    registry = metric_use_case_registry()
    computed = [
        metric for metric in registry.metrics if metric.expression_kind == "computed_numeric_alias"
    ]

    assert len(computed) == EXPECTED_COMPUTED_NUMERIC_ALIAS_COUNT == 190
    metric = registry.by_metric_id["agg_team_franchise.computed_win_pct"]
    assert metric.metric_kind == "unreviewed_numeric_candidate"
    assert metric.expression_kind == "computed_numeric_alias"
    assert metric.expression_sql
    assert len(metric.expression_sha256) == 64
    formula = metric.semantic_fields[0]
    assert formula.name == "formula"
    assert formula.value == metric.expression_sql
    assert formula.reviewed is True
    assert all(not field.reviewed for field in metric.semantic_fields[1:])


def test_explicit_numeric_keys_are_nonsemantic_and_not_invented_as_measures() -> None:
    registry = metric_use_case_registry()
    player_id = registry.by_metric_id["fact_player_game_traditional.player_id"]

    assert player_id.metric_kind == "explicit_structural_nonmetric"
    assert player_id.status == "explicit_nonsemantic_disposition"
    assert player_id.expression_sql is None
    assert player_id.blockers == ("nonsemantic_numeric_column_excluded_from_metric_consumers",)
    assert all(not field.reviewed for field in player_id.semantic_fields)


def test_unclassified_numeric_columns_remain_blocked_without_name_inference() -> None:
    registry = metric_use_case_registry()
    candidate = registry.by_metric_id["fact_player_game_traditional.pts"]

    assert candidate.metric_kind == "unreviewed_numeric_candidate"
    assert candidate.status == "blocked_pending_measure_classification"
    assert "numeric_column_measure_classification_unreviewed" in candidate.blockers


def test_every_metric_semantic_gap_is_explicit_and_consumer_quarantined() -> None:
    registry = metric_use_case_registry()

    assert registry.model_green is False
    assert registry.release_gate_green is False
    assert registry.experimental_semantics_green is False
    assert registry.blocker_counts == registry.semantic_gap_counts
    assert all(metric.consumer_admission == "quarantined" for metric in registry.metrics)
    assert all(len(metric.semantic_fields) == 14 for metric in registry.metrics)
    assert all(metric.blockers for metric in registry.metrics)
    assert dict(registry.semantic_gap_counts)["metric_semantics_unreviewed:use_cases"] == 4_305


def test_computed_alias_compiler_rejects_conflicting_formulas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    star = compile_star_table_contracts()
    runtimes = metric_module.discover_all_transformers(include_live=True)
    target = next(runtime for runtime in runtimes if runtime.output_table == "agg_team_franchise")
    ambiguous = SimpleNamespace(
        output_table=target.output_table,
        _SQL=(
            "SELECT 1.0 + 1.0 AS computed_win_pct UNION ALL SELECT 2.0 + 2.0 AS computed_win_pct"
        ),
    )
    monkeypatch.setattr(
        metric_module,
        "discover_all_transformers",
        lambda *, include_live: [
            ambiguous if runtime.output_table == target.output_table else runtime
            for runtime in runtimes
        ],
    )

    with pytest.raises(
        MetricUseCaseContractCompilationError,
        match="ambiguous computed SQL expressions",
    ):
        metric_module._computed_alias_expressions(star)


def test_metric_registry_is_deterministic_and_deeply_immutable() -> None:
    first = metric_use_case_registry()
    second = metric_use_case_registry()

    assert first is second
    assert first.digest == second.digest
    assert first.to_dict() == second.to_dict()
    with pytest.raises(TypeError):
        first.by_metric_id["new"] = first.metrics[0]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        first.metrics[0].consumer_admission = "allowed"  # type: ignore[misc]


def test_metric_registry_validator_fails_closed_on_nested_or_bundle_drift() -> None:
    registry = metric_use_case_registry()

    with pytest.raises(ValueError, match="digest"):
        validate_metric_use_case_registry(replace(registry, digest="0" * 64))
    changed_metric = replace(registry.metrics[0], data_type="String")
    with pytest.raises(ValueError, match="metric contract digest"):
        validate_metric_use_case_registry(
            replace(registry, metrics=(changed_metric, *registry.metrics[1:]))
        )
    changed_expression = replace(registry.metrics[0], expression_sha256="0" * 64)
    with pytest.raises(ValueError, match="expression digest"):
        validate_metric_use_case_registry(
            replace(registry, metrics=(changed_expression, *registry.metrics[1:]))
        )
    with pytest.raises(ValueError, match="kind counts"):
        validate_metric_use_case_registry(replace(registry, kind_counts=()))
    with pytest.raises(ValueError, match="semantic-gap counts"):
        validate_metric_use_case_registry(replace(registry, semantic_gap_counts=()))


def test_registry_constructor_copies_mutable_index_input() -> None:
    registry = metric_use_case_registry()
    mutable_index = dict(registry.by_metric_id)
    rebuilt = replace(registry, _by_metric_id=mutable_index)

    mutable_index.clear()
    assert len(rebuilt.by_metric_id) == EXPECTED_PUBLIC_NUMERIC_COLUMN_COUNT
    with pytest.raises(TypeError):
        rebuilt.by_metric_id["new"] = rebuilt.metrics[0]  # type: ignore[index]
