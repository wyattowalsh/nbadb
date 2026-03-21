from __future__ import annotations

import json
from typing import ClassVar

import polars as pl

from nbadb.core.transform_dependency_graph import TransformDependencyGraphGenerator
from nbadb.transform.base import BaseTransformer


class _DimSeason(BaseTransformer):
    output_table: ClassVar[str] = "dim_season"
    depends_on: ClassVar[list[str]] = ["stg_season"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame()


class _FactGame(BaseTransformer):
    output_table: ClassVar[str] = "fact_game"
    depends_on: ClassVar[list[str]] = ["dim_season", "stg_games", "ghost_dep"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame()


class _AggGame(BaseTransformer):
    output_table: ClassVar[str] = "agg_game"
    depends_on: ClassVar[list[str]] = ["fact_game"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame()


class _CycleA(BaseTransformer):
    output_table: ClassVar[str] = "fact_cycle_a"
    depends_on: ClassVar[list[str]] = ["fact_cycle_b"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame()


class _CycleB(BaseTransformer):
    output_table: ClassVar[str] = "fact_cycle_b"
    depends_on: ClassVar[list[str]] = ["fact_cycle_a"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame()


def test_build_graph_classifies_dependencies_and_consumers(tmp_path) -> None:
    generator = TransformDependencyGraphGenerator(
        project_root=tmp_path,
        transformers=[_AggGame(), _FactGame(), _DimSeason()],
    )

    graph = generator.build_graph()

    assert graph["summary"]["transformer_count"] == 3
    assert graph["summary"]["transform_dependency_count"] == 2
    assert graph["summary"]["staging_dependency_count"] == 2
    assert graph["summary"]["unresolved_dependency_count"] == 1
    assert graph["summary"]["cycle_count"] == 0
    assert graph["roots"] == ["dim_season"]
    assert graph["leaves"] == ["agg_game"]
    assert graph["execution_order"] == ["dim_season", "fact_game", "agg_game"]

    nodes = {node["output_table"]: node for node in graph["transformers"]}
    assert nodes["dim_season"]["staging_dependencies"] == ["stg_season"]
    assert nodes["dim_season"]["consumers"] == ["fact_game"]
    assert nodes["fact_game"]["transform_dependencies"] == ["dim_season"]
    assert nodes["fact_game"]["staging_dependencies"] == ["stg_games"]
    assert nodes["fact_game"]["unresolved_dependencies"] == ["ghost_dep"]
    assert nodes["fact_game"]["consumers"] == ["agg_game"]
    assert nodes["agg_game"]["transform_dependencies"] == ["fact_game"]

    edges = {
        (edge["from"], edge["to"], edge["dependency_kind"]) for edge in graph["edges"]
    }
    assert ("dim_season", "fact_game", "transform_output") in edges
    assert ("stg_games", "fact_game", "staging") in edges
    assert ("ghost_dep", "fact_game", "unresolved") in edges


def test_build_graph_detects_cycles_and_suppresses_execution_order(tmp_path) -> None:
    generator = TransformDependencyGraphGenerator(
        project_root=tmp_path,
        transformers=[_CycleA(), _CycleB()],
    )

    graph = generator.build_graph()

    assert graph["summary"]["cycle_count"] == 1
    assert graph["cycles"] == [["fact_cycle_a", "fact_cycle_b", "fact_cycle_a"]]
    assert graph["execution_order"] == []


def test_write_creates_json_artifact(tmp_path) -> None:
    output_path = tmp_path / "artifacts" / "transform-dependencies" / "graph.json"
    generator = TransformDependencyGraphGenerator(
        project_root=tmp_path,
        output_path=output_path,
        transformers=[_AggGame(), _FactGame(), _DimSeason()],
    )

    written = generator.write()

    assert written == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"]["transformer_count"] == 3
    assert any(
        node["output_table"] == "fact_game" for node in payload["transformers"]
    )
