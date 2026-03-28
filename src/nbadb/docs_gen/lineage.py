from __future__ import annotations

import importlib
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandera.polars as pa
from loguru import logger


def _safe_mermaid_id(name: str) -> str:
    """Sanitise a table/endpoint name for use as a Mermaid node ID."""
    return name.replace("-", "_").replace(" ", "_").replace(".", "_")


class SqlLineageAnalyzer:
    """Parse SqlTransformer._SQL with SQLGlot to extract table-level lineage."""

    def analyze(self) -> dict[str, dict[str, Any]]:
        """Return ``{output_table: {source_tables: [...], columns: [...]}}``.

        Discovers all :class:`SqlTransformer` subclasses and parses their
        ``_SQL`` ClassVar using SQLGlot with the DuckDB dialect.
        """
        try:
            import sqlglot
            from sqlglot import exp
        except ImportError:
            logger.warning("sqlglot not installed — skipping SQL lineage analysis")
            return {}

        from nbadb.orchestrate.transformers import discover_all_transformers
        from nbadb.transform.base import SqlTransformer

        transformers = discover_all_transformers()
        result: dict[str, dict[str, Any]] = {}

        for t in transformers:
            if not isinstance(t, SqlTransformer) or not t._SQL.strip():
                continue

            try:
                parsed = sqlglot.parse(t._SQL, read="duckdb")
            except sqlglot.errors.ErrorLevel:
                logger.debug(f"sqlglot could not parse SQL for {t.output_table}")
                continue

            source_tables: set[str] = set()
            output_columns: list[str] = []

            for stmt in parsed:
                if stmt is None:
                    continue
                # Collect CTE aliases so they are excluded from source tables
                cte_names = {c.alias for c in stmt.find_all(exp.CTE)}
                for tbl in stmt.find_all(exp.Table):
                    name = tbl.name
                    if name and name not in cte_names:
                        source_tables.add(name)

                # Extract output column names from the outermost SELECT
                select = stmt.find(exp.Select)
                if select:
                    for col_expr in select.expressions:
                        alias = col_expr.alias_or_name
                        if alias == "*":
                            output_columns.append("*")
                        elif alias:
                            output_columns.append(alias)

            if source_tables:
                result[t.output_table] = {
                    "source_tables": sorted(source_tables),
                    "columns": output_columns,
                    "class_name": type(t).__name__,
                }

        logger.info(f"SQLGlot analyzed {len(result)} SQL transforms")
        return result


class LineageGenerator:
    """Generate column-level lineage from Pandera schema metadata.

    Traces star schema columns back to source endpoints using
    the 'source' metadata annotation on each field.  Optionally
    enriched with SQLGlot-based SQL analysis of SqlTransformer queries.
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("docs/content/docs/lineage")
        self._lineage_graph: dict[str, Any] | None = None
        self._sql_lineage: dict[str, dict[str, Any]] | None = None

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
                    and not name.startswith("_")  # Skip mixin classes
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
        if self._lineage_graph is not None:
            return self._lineage_graph
        schemas = self._discover_schemas()
        graph: dict[str, Any] = {}

        for class_name, schema_cls in schemas:
            table_name = self._table_name_from_class(class_name)
            columns: dict[str, dict[str, str]] = {}
            schema = schema_cls.to_schema()

            for field_name, field_obj in schema.columns.items():
                metadata = field_obj.metadata or {}
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

        self._lineage_graph = graph
        return graph

    def build_sql_lineage(self) -> dict[str, dict[str, Any]]:
        """Build SQL-level lineage via SQLGlot parsing."""
        if self._sql_lineage is not None:
            return self._sql_lineage
        self._sql_lineage = SqlLineageAnalyzer().analyze()
        return self._sql_lineage

    def generate_dict(self) -> dict[str, Any]:
        """Return combined lineage data as a dict (no serialization)."""
        schema_graph = self.build_lineage_graph()
        sql_graph = self.build_sql_lineage()

        combined: dict[str, Any] = {}
        all_tables = sorted(set(schema_graph) | set(sql_graph))

        for table in all_tables:
            entry: dict[str, Any] = {}
            if table in schema_graph:
                entry["schema_lineage"] = schema_graph[table]
            if table in sql_graph:
                entry["sql_lineage"] = sql_graph[table]
            combined[table] = entry

        return combined

    def generate_json(self) -> str:
        """Generate lineage JSON with both schema metadata and SQL analysis."""
        return json.dumps(self.generate_dict(), indent=2)

    def generate_mermaid(self) -> str:
        """Generate table-level lineage Mermaid flowchart.

        Combines Pandera schema metadata (endpoint → star table) with
        SQLGlot SQL analysis (staging/dim/fact → output table).
        """
        schema_graph = self.build_lineage_graph()
        sql_graph = self.build_sql_lineage()

        endpoints: set[str] = set()
        staging_tables: set[str] = set()
        output_tables: set[str] = set()
        edges: set[tuple[str, str]] = set()

        # Schema metadata edges: endpoint → star table
        for table_name, info in schema_graph.items():
            output_tables.add(table_name)
            for col_info in info["columns"].values():
                ep = col_info.get("endpoint", "")
                if ep and ep != "derived":
                    endpoints.add(ep)
                    edges.add((ep, table_name))

        # SQL-parsed edges: source_table → output table
        for output_table, info in sql_graph.items():
            output_tables.add(output_table)
            for src in info["source_tables"]:
                edges.add((src, output_table))
                if src.startswith("stg_") or not src.startswith(
                    ("dim_", "fact_", "bridge_", "agg_", "analytics_")
                ):
                    staging_tables.add(src)

        lines = ["flowchart LR"]

        # Style classes
        lines.append("    classDef endpoint fill:#e1f5fe,stroke:#0277bd")
        lines.append("    classDef staging fill:#fff3e0,stroke:#ef6c00")
        lines.append("    classDef dim fill:#e8f5e9,stroke:#2e7d32")
        lines.append("    classDef fact fill:#fce4ec,stroke:#c62828")
        lines.append("    classDef other fill:#f3e5f5,stroke:#6a1b9a")

        # Endpoint nodes
        for ep in sorted(endpoints):
            sid = _safe_mermaid_id(ep)
            lines.append(f"    {sid}[{ep}]:::endpoint")

        # Staging nodes (from SQL analysis, not already shown as endpoints)
        for st in sorted(staging_tables - endpoints):
            sid = _safe_mermaid_id(st)
            lines.append(f"    {sid}[{st}]:::staging")

        # Output table nodes
        for t in sorted(output_tables):
            sid = _safe_mermaid_id(t)
            if t.startswith("dim_"):
                lines.append(f"    {sid}[({t})]:::dim")
            elif t.startswith("fact_"):
                lines.append(f"    {sid}[({t})]:::fact")
            else:
                lines.append(f"    {sid}[({t})]:::other")

        # Edges
        for src, tgt in sorted(edges):
            lines.append(f"    {_safe_mermaid_id(src)} --> {_safe_mermaid_id(tgt)}")

        return "\n".join(lines)

    def generate_mdx(self) -> str:
        """Generate lineage MDX with Mermaid diagram."""
        mermaid = self.generate_mermaid()
        sql_graph = self.build_sql_lineage()
        sql_count = len(sql_graph)
        generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        return (
            "---\n"
            "title: Data Lineage\n"
            "description: Column-level lineage from star schema to source endpoints\n"
            "---\n\n"
            "# Data Lineage\n\n"
            "{/* Auto-generated by nbadb docs-gen. Do not edit by hand. */}\n"
            f"{{/* Generated: {generated_at} */}}\n"
            "{/* Regenerate: uv run nbadb docs-autogen --docs-root docs/content/docs */}\n\n"
            "## Table-Level Lineage\n\n"
            f"Generated from Pandera schema metadata and SQLGlot analysis"
            f" of {sql_count} SQL transforms.\n\n"
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
