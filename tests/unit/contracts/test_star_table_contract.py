from __future__ import annotations

import importlib
import json
from collections import Counter
from dataclasses import FrozenInstanceError

import pytest

from nbadb.contracts.star_table_contract import (
    EXPECTED_STAR_TABLE_COUNTS,
    EXPECTED_STAR_TABLE_TOTAL,
    StarTableContractCompilationError,
    compile_star_table_contracts,
    schema_contract_sha256,
)
from nbadb.orchestrate.transformers import discover_all_transformers
from nbadb.schemas.registry import _star_schema_registry
from nbadb.transform.base import SqlTransformer


@pytest.fixture(scope="module")
def inventory():
    return compile_star_table_contracts()


def test_compiler_covers_exact_runtime_universe_without_drops(inventory) -> None:
    registry = _star_schema_registry()
    transformers = discover_all_transformers(include_live=True)
    contract_names = tuple(contract.output_name for contract in inventory.tables)

    assert len(inventory.tables) == EXPECTED_STAR_TABLE_TOTAL == len(registry)
    assert contract_names == tuple(sorted(registry))
    assert set(contract_names) == {transformer.output_table for transformer in transformers}
    assert inventory.family_counts == EXPECTED_STAR_TABLE_COUNTS
    expected_family_counts = Counter(name.partition("_")[0] for name in registry)
    assert inventory.family_counts.fact == expected_family_counts["fact"]
    assert inventory.family_counts.dim == expected_family_counts["dim"]
    assert inventory.family_counts.bridge == expected_family_counts["bridge"]
    assert inventory.family_counts.agg == expected_family_counts["agg"]
    assert inventory.family_counts.analytics == expected_family_counts["analytics"]
    assert inventory.family_counts.total == len(registry)


def test_compiled_pandera_schemas_preserve_exact_order_and_metadata(inventory) -> None:
    registry = _star_schema_registry()

    assert sum(len(contract.columns) for contract in inventory.tables) == sum(
        len(schema_cls.to_schema().columns) for schema_cls in registry.values()
    )

    for contract in inventory.tables:
        schema_cls = registry[contract.output_name]
        schema = schema_cls.to_schema()
        assert contract.schema_class == schema_cls.__name__
        assert contract.schema_module == schema_cls.__module__
        assert tuple(column.name for column in contract.columns) == tuple(schema.columns)
        assert tuple(column.ordinal for column in contract.columns) == tuple(
            range(len(schema.columns))
        )
        for compiled, runtime in zip(
            contract.columns,
            schema.columns.values(),
            strict=True,
        ):
            metadata = dict(runtime.metadata or {})
            assert compiled.data_type == str(runtime.dtype)
            assert compiled.nullable is bool(runtime.nullable)
            assert compiled.unique is bool(runtime.unique)
            assert compiled.required is bool(runtime.required)
            assert compiled.source == metadata.get("source")
            assert compiled.fk_ref == metadata.get("fk_ref")
            assert json.loads(compiled.metadata_json) == metadata
        assert contract.schema_sha256 == schema_contract_sha256(contract.columns)

    empty = {contract.output_name for contract in inventory.tables if not contract.columns}
    assert empty == set()
    assert all("schema_empty" not in contract.blockers for contract in inventory.tables)


def test_schema_digest_is_order_sensitive(inventory) -> None:
    contract = inventory.table("fact_shot_chart")

    assert len(contract.columns) > 1
    assert schema_contract_sha256(contract.columns) == contract.schema_sha256
    assert schema_contract_sha256(tuple(reversed(contract.columns))) != contract.schema_sha256


def test_transform_contracts_bind_exact_identity_kind_and_dependencies(inventory) -> None:
    runtime_by_name = {
        transformer.output_table: transformer
        for transformer in discover_all_transformers(include_live=True)
    }

    for contract in inventory.tables:
        runtime = runtime_by_name[contract.output_name]
        runtime_cls = type(runtime)
        transform = contract.transform
        binding_module = importlib.import_module(transform.binding_module)

        assert transform.class_name == runtime_cls.__name__
        assert transform.qualname == runtime_cls.__qualname__
        assert transform.runtime_module == runtime_cls.__module__
        assert getattr(binding_module, transform.class_name) is runtime_cls
        assert transform.dependencies == tuple(runtime.depends_on)
        assert transform.kind == ("sql" if isinstance(runtime, SqlTransformer) else "python")
        assert len(transform.implementation_sha256) == 64
        int(transform.implementation_sha256, 16)

    expected_kind_counts = Counter(
        "sql" if isinstance(runtime, SqlTransformer) else "python"
        for runtime in runtime_by_name.values()
    )
    assert Counter(table.transform.kind for table in inventory.tables) == expected_kind_counts
    factory_contract = inventory.table("fact_video_details")
    assert factory_contract.transform.runtime_module == "abc"
    assert factory_contract.transform.binding_module == ("nbadb.transform.facts.fact_video_support")


def test_compilation_is_deterministic(inventory) -> None:
    repeated = compile_star_table_contracts()

    assert repeated == inventory
    assert repeated.contract_sha256 == inventory.contract_sha256
    assert tuple(table.contract_sha256 for table in repeated.tables) == tuple(
        table.contract_sha256 for table in inventory.tables
    )


def test_consumer_grain_evidence_never_claims_review(inventory) -> None:
    explicit = [table for table in inventory.tables if table.consumer_metadata is not None]
    inferred = [
        table
        for table in inventory.tables
        if table.grain.evidence_kind == "inferred_consumer_metadata_unreviewed"
    ]

    assert explicit
    assert inferred
    assert len(inferred) == len(inventory.tables) - len(explicit)
    assert all(table.grain.reviewed is False for table in inventory.tables)
    assert all(table.grain.columns == () for table in inventory.tables)
    assert inventory.table("dim_player").grain.evidence_kind == (
        "explicit_consumer_metadata_unreviewed"
    )
    assert inventory.table("dim_player").grain.label == "player-current-identity-snapshot"
    assert all("grain_inferred_unreviewed" in table.blockers for table in inferred)
    assert "grain_columns_unreviewed" in inventory.table("dim_player").blockers


def test_uniqueness_constraints_do_not_become_invented_keys(inventory) -> None:
    tables_with_unique_columns = [
        table for table in inventory.tables if any(column.unique for column in table.columns)
    ]

    assert len(tables_with_unique_columns) == 13
    assert sum(column.unique for table in inventory.tables for column in table.columns) == 14
    assert all(table.key_policy.kind == "unreviewed_bag" for table in inventory.tables)
    assert all(table.key_policy.columns == () for table in inventory.tables)
    assert all(table.key_policy.reviewed is False for table in inventory.tables)
    assert all("key_policy_unreviewed_bag" in table.blockers for table in inventory.tables)


def test_foreign_keys_require_explicit_current_or_as_of_semantics(inventory) -> None:
    foreign_keys = [relation for table in inventory.tables for relation in table.foreign_keys]

    assert foreign_keys
    assert all(relation.current_or_as_of is None for relation in foreign_keys)
    assert all(relation.reviewed is False for relation in foreign_keys)
    assert all(
        relation.blockers == ("fk_relationship_semantics_unreviewed",) for relation in foreign_keys
    )
    player_fk = next(
        relation
        for relation in inventory.table("fact_player_game_traditional").foreign_keys
        if relation.column == "player_id"
    )
    assert player_fk.reference == "dim_player.player_id"
    assert player_fk.target_column_unique is False
    assert (
        "fk_relationship_semantics_unreviewed:player_id"
        in inventory.table("fact_player_game_traditional").blockers
    )


def test_scd_and_row_operation_semantics_remain_blockers(inventory) -> None:
    expected_policy_names = {
        "row",
        "filter",
        "dedup",
        "union",
        "aggregate",
        "temporal",
        "scd",
    }

    for table in inventory.tables:
        assert {policy.name for policy in table.semantic_policies} == expected_policy_names
        assert all(policy.reviewed is False for policy in table.semantic_policies)
        assert all(policy.value is None for policy in table.semantic_policies)
        assert all(
            f"{policy_name}_semantics_unreviewed" in table.blockers
            for policy_name in expected_policy_names
        )
        assert table.model_green is False

    dim_player = inventory.table("dim_player")
    assert dim_player.consumer_metadata is not None
    assert "scd2_notes" in json.loads(dim_player.consumer_metadata.canonical_json)
    assert "scd_semantics_unreviewed" in dim_player.blockers


def test_global_model_green_is_false_and_blockers_are_aggregated(inventory) -> None:
    summary = {blocker.code: blocker for blocker in inventory.blocker_summary}

    assert inventory.model_green is False
    assert inventory.model_green is False
    assert summary["grain_columns_unreviewed"].table_count == len(inventory.tables)
    assert summary["key_policy_unreviewed_bag"].table_count == len(inventory.tables)
    assert summary["row_semantics_unreviewed"].table_count == len(inventory.tables)
    tables_with_foreign_keys = sum(bool(table.foreign_keys) for table in inventory.tables)
    foreign_key_count = sum(len(table.foreign_keys) for table in inventory.tables)
    assert summary["fk_relationship_semantics_unreviewed"].table_count == tables_with_foreign_keys
    assert summary["fk_relationship_semantics_unreviewed"].occurrence_count == foreign_key_count
    assert "schema_empty" not in summary


def test_inventory_is_deeply_immutable(inventory) -> None:
    with pytest.raises(FrozenInstanceError):
        inventory.model_green = True
    with pytest.raises(TypeError):
        inventory.tables[0] = inventory.tables[0]
    with pytest.raises(FrozenInstanceError):
        inventory.tables[0].grain.reviewed = True


def test_registry_gap_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import nbadb.schemas.registry as schema_registry_module

    original = schema_registry_module._star_schema_registry
    incomplete = dict(original())
    incomplete.pop("fact_shot_chart")
    monkeypatch.setattr(
        schema_registry_module,
        "_star_schema_registry",
        lambda: incomplete,
    )

    with pytest.raises(
        StarTableContractCompilationError,
        match="cannot load the runtime star-table universe",
    ):
        compile_star_table_contracts()
