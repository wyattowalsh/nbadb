from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from typing import Any

import pandera.polars as pa
from loguru import logger


class LineageGenerator:
    """Generate column-level lineage from Pandera schema metadata.

    Traces star schema columns back to source endpoints using
    the 'source' metadata annotation on each field.
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("docs/content/docs/lineage")

    def _discover_schemas(
        self, package_name: str = "nbadb.schemas.star"
    ) -> list[tuple[str, type[pa.DataFrameModel]]]:
        """Discover schema classes."""
        schemas: list[tuple[str, type[pa.DataFrameModel]]] = []
        try:
            pkg = importlib.import_module(package_name)
        except ImportError:
            return schemas

        pkg_path = getattr(pkg, "__path__", None)
        if pkg_path is None:
            return schemas

        for module_path in Path(pkg_path[0]).glob("*.py"):
            if module_path.name.startswith("_"):
                continue
            module_name = f"{package_name}.{module_path.stem}"
            try:
                mod = importlib.import_module(module_name)
            except ImportError:
                continue

            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, pa.DataFrameModel)
                    and obj is not pa.DataFrameModel
                    and obj.__module__ == module_name
                ):
                    schemas.append((name, obj))
        return schemas

    def _table_name_from_class(self, class_name: str) -> str:
        """Convert class name to table name."""
        name = class_name
        for suffix in ("Schema", "Model"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        result = []
        for i, ch in enumerate(name):
            if ch.isupper() and i > 0:
                result.append("_")
            result.append(ch.lower())
        return "".join(result)

    def build_lineage_graph(self) -> dict[str, Any]:
        """Build full lineage graph: star column → source endpoint.field."""
        schemas = self._discover_schemas()
        graph: dict[str, Any] = {}

        for class_name, schema_cls in schemas:
            table_name = self._table_name_from_class(class_name)
            columns: dict[str, dict[str, str]] = {}

            annotations = {}
            for cls in reversed(schema_cls.__mro__):
                annotations.update(getattr(cls, "__annotations__", {}))

            for field_name in annotations:
                if field_name.startswith("_"):
                    continue
                field_obj = getattr(schema_cls, field_name, None)
                if field_obj is None:
                    continue
                metadata = getattr(field_obj, "metadata", {}) or {}
                source = metadata.get("source", "")
                fk_ref = metadata.get("fk_ref", "")

                entry: dict[str, str] = {}
                if source:
                    parts = source.split(".")
                    if len(parts) >= 2:
                        entry["endpoint"] = parts[0]
                        entry["result_set"] = parts[1] if len(parts) > 2 else ""
                        entry["field"] = parts[-1]
                    else:
                        entry["raw_source"] = source
                if fk_ref:
                    entry["fk_ref"] = fk_ref
                if entry:
                    columns[field_name] = entry

            if columns:
                graph[table_name] = {
                    "class": class_name,
                    "columns": columns,
                }

        return graph

    def generate_json(self) -> str:
        """Generate lineage JSON export."""
        graph = self.build_lineage_graph()
        return json.dumps(graph, indent=2)

    def generate_mermaid(self) -> str:
        """Generate table-level lineage Mermaid flowchart."""
        graph = self.build_lineage_graph()

        endpoints: set[str] = set()
        tables: set[str] = set()
        edges: set[tuple[str, str]] = set()

        for table_name, info in graph.items():
            tables.add(table_name)
            for col_info in info["columns"].values():
                ep = col_info.get("endpoint", "")
                if ep and ep != "derived":
                    endpoints.add(ep)
                    edges.add((ep, table_name))

        lines = ["flowchart LR"]
        for ep in sorted(endpoints):
            safe_id = ep.replace("-", "_").replace(" ", "_")
            lines.append(f"    {safe_id}[{ep}]")
        for t in sorted(tables):
            safe_id = t.replace("-", "_")
            lines.append(f"    {safe_id}[({t})]")
        for src, tgt in sorted(edges):
            safe_src = src.replace("-", "_").replace(" ", "_")
            safe_tgt = tgt.replace("-", "_")
            lines.append(f"    {safe_src} --> {safe_tgt}")

        return "\n".join(lines)

    def generate_mdx(self) -> str:
        """Generate lineage MDX with Mermaid diagram."""
        mermaid = self.generate_mermaid()
        return (
            "---\n"
            "title: Data Lineage\n"
            "description: Column-level lineage from star schema to source endpoints\n"
            "---\n\n"
            "# Data Lineage\n\n"
            "## Table-Level Lineage\n\n"
            "```mermaid\n"
            f"{mermaid}\n"
            "```\n\n"
            "## Column-Level Lineage\n\n"
            "See `lineage.json` for machine-readable column-level tracing.\n"
        )

    def write(self) -> list[Path]:
        """Write lineage MDX + JSON files."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        mdx_path = self.output_dir / "lineage-auto.mdx"
        mdx_path.write_text(self.generate_mdx(), encoding="utf-8")
        written.append(mdx_path)

        json_path = self.output_dir / "lineage.json"
        json_path.write_text(self.generate_json(), encoding="utf-8")
        written.append(json_path)

        logger.info(f"Wrote lineage files: {[str(p) for p in written]}")
        return written
