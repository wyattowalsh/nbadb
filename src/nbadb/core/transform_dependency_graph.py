from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nbadb.orchestrate.transformers import discover_all_transformers

if TYPE_CHECKING:
    from nbadb.transform.base import BaseTransformer


class TransformDependencyGraphGenerator:
    def __init__(
        self,
        project_root: Path | None = None,
        output_path: Path | None = None,
        transformers: list[BaseTransformer] | None = None,
    ) -> None:
        self.project_root = Path(project_root) if project_root is not None else Path.cwd()
        self.output_path = output_path or (
            self.project_root
            / "artifacts"
            / "transform-dependencies"
            / "transform-dependency-graph.json"
        )
        self._transformers_override = transformers

    @staticmethod
    def _table_family(table_name: str) -> str:
        if table_name.startswith("dim_"):
            return "dimension"
        if table_name.startswith("fact_"):
            return "fact"
        if table_name.startswith("bridge_"):
            return "bridge"
        if table_name.startswith("agg_"):
            return "aggregate"
        if table_name.startswith("analytics_"):
            return "analytics"
        return "other"

    @staticmethod
    def _dependency_kind(dependency: str, output_tables: set[str]) -> str:
        if dependency in output_tables:
            return "transform_output"
        if dependency.startswith("stg_"):
            return "staging"
        if dependency.startswith("raw_"):
            return "raw"
        return "unresolved"

    def _load_transformers(self) -> list[BaseTransformer]:
        if self._transformers_override is not None:
            return list(self._transformers_override)
        return discover_all_transformers()

    @staticmethod
    def _normalize_cycle(nodes: list[str]) -> tuple[str, ...]:
        if len(nodes) <= 1:
            return tuple(nodes)

        cycle_nodes = nodes[:-1]
        if not cycle_nodes:
            return tuple(nodes)

        rotations = [
            tuple(cycle_nodes[index:] + cycle_nodes[:index]) for index in range(len(cycle_nodes))
        ]
        canonical = min(rotations)
        return canonical + (canonical[0],)

    def _find_cycles(self, adjacency: dict[str, list[str]]) -> list[list[str]]:
        visited: set[str] = set()
        in_stack: set[str] = set()
        stack: list[str] = []
        cycles: set[tuple[str, ...]] = set()

        def visit(node: str) -> None:
            visited.add(node)
            in_stack.add(node)
            stack.append(node)

            for dependency in adjacency.get(node, []):
                if dependency not in adjacency:
                    continue
                if dependency not in visited:
                    visit(dependency)
                    continue
                if dependency in in_stack:
                    start = stack.index(dependency)
                    cycle = stack[start:] + [dependency]
                    cycles.add(self._normalize_cycle(cycle))

            stack.pop()
            in_stack.remove(node)

        for node in sorted(adjacency):
            if node not in visited:
                visit(node)

        return [list(cycle) for cycle in sorted(cycles)]

    def _topological_order(
        self,
        adjacency: dict[str, list[str]],
        consumers_map: dict[str, set[str]],
    ) -> list[str]:
        indegree = {name: len(adjacency.get(name, [])) for name in adjacency}
        queue = deque(sorted(name for name, degree in indegree.items() if degree == 0))
        ordered: list[str] = []

        while queue:
            node = queue.popleft()
            ordered.append(node)
            for consumer in sorted(consumers_map.get(node, set())):
                indegree[consumer] -= 1
                if indegree[consumer] == 0:
                    queue.append(consumer)

        if len(ordered) != len(adjacency):
            return []
        return ordered

    def build_graph(self) -> dict[str, Any]:
        transformers = sorted(self._load_transformers(), key=lambda item: item.output_table)
        output_tables = {transformer.output_table for transformer in transformers}

        transformer_nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        consumers_map: dict[str, set[str]] = defaultdict(set)
        transform_adjacency: dict[str, list[str]] = {}
        dependency_kind_counts: Counter[str] = Counter()

        for transformer in transformers:
            depends_on = sorted(transformer.depends_on)
            grouped: dict[str, list[str]] = defaultdict(list)
            transform_dependencies: list[str] = []
            for dependency in depends_on:
                kind = self._dependency_kind(dependency, output_tables)
                grouped[kind].append(dependency)
                dependency_kind_counts[kind] += 1
                edges.append(
                    {
                        "from": dependency,
                        "to": transformer.output_table,
                        "dependency_kind": kind,
                    }
                )
                consumers_map[dependency].add(transformer.output_table)
                if kind == "transform_output":
                    transform_dependencies.append(dependency)

            transform_dependencies.sort()
            transform_adjacency[transformer.output_table] = transform_dependencies
            transformer_nodes.append(
                {
                    "output_table": transformer.output_table,
                    "table_family": self._table_family(transformer.output_table),
                    "class_name": type(transformer).__name__,
                    "module": type(transformer).__module__,
                    "depends_on": depends_on,
                    "transform_dependencies": transform_dependencies,
                    "staging_dependencies": sorted(grouped.get("staging", [])),
                    "raw_dependencies": sorted(grouped.get("raw", [])),
                    "unresolved_dependencies": sorted(grouped.get("unresolved", [])),
                }
            )

        for node in transformer_nodes:
            node["consumers"] = sorted(consumers_map.get(node["output_table"], set()))

        family_counts = Counter(node["table_family"] for node in transformer_nodes)
        roots = sorted(
            node["output_table"]
            for node in transformer_nodes
            if not node["transform_dependencies"]
        )
        leaves = sorted(
            node["output_table"]
            for node in transformer_nodes
            if not node["consumers"]
        )
        cycles = self._find_cycles(transform_adjacency)
        execution_order = (
            []
            if cycles
            else self._topological_order(transform_adjacency, consumers_map)
        )

        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "project": {
                "root": str(self.project_root),
            },
            "summary": {
                "transformer_count": len(transformer_nodes),
                "edge_count": len(edges),
                "transform_dependency_count": dependency_kind_counts["transform_output"],
                "staging_dependency_count": dependency_kind_counts["staging"],
                "raw_dependency_count": dependency_kind_counts["raw"],
                "unresolved_dependency_count": dependency_kind_counts["unresolved"],
                "root_transformer_count": len(roots),
                "leaf_transformer_count": len(leaves),
                "cycle_count": len(cycles),
                "family_breakdown": dict(sorted(family_counts.items())),
            },
            "transformers": transformer_nodes,
            "edges": sorted(
                edges,
                key=lambda item: (
                    item["to"],
                    item["dependency_kind"],
                    item["from"],
                ),
            ),
            "roots": roots,
            "leaves": leaves,
            "cycles": cycles,
            "execution_order": execution_order,
        }

    def generate_json(self) -> str:
        return json.dumps(self.build_graph(), indent=2)

    def write(self, output_path: Path | None = None) -> Path:
        destination = output_path or self.output_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.generate_json() + "\n", encoding="utf-8")
        return destination


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate transform dependency graph artifact JSON."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (defaults to cwd).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Output JSON path "
            "(defaults to <project-root>/artifacts/transform-dependencies/"
            "transform-dependency-graph.json)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    generator = TransformDependencyGraphGenerator(
        project_root=args.project_root,
        output_path=args.output,
    )
    written = generator.write()
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
