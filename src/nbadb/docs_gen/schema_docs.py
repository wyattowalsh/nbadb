from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from typing import Any

import pandera.polars as pa
from loguru import logger


class SchemaDocsGenerator:
    """Generate complete schema reference MDX from Pandera models.

    Produces one JSON data file + one lightweight MDX stub per schema tier.
    The MDX stub imports a React component that renders from JSON at runtime,
    avoiding MDX compilation of hundreds of markdown tables.
    """

    SCHEMA_PACKAGES = {
        "raw": "nbadb.schemas.raw",
        "staging": "nbadb.schemas.staging",
        "star": "nbadb.schemas.star",
    }

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("docs/content/docs/schema")

    def _discover_schemas(self, package_name: str) -> list[tuple[str, type[pa.DataFrameModel]]]:
        """Discover schema classes in a package."""
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

    def generate_tier_mdx(self, tier: str) -> str:
        """Generate schema reference MDX for a tier."""
        package = self.SCHEMA_PACKAGES.get(tier)
        if not package:
            return f"# Schema Reference — {tier.title()}\n\nUnknown tier.\n"

        schemas = self._discover_schemas(package)
        lines = [
            "---",
            f"title: Schema Reference — {tier.title()}",
            f"description: Complete schema docs for {tier} tier",
            "---",
            "",
            f"# Schema Reference — {tier.title()}",
            "",
            f"This tier contains {len(schemas)} schema(s).",
            "",
        ]

        for class_name, schema_cls in sorted(schemas, key=lambda x: x[0]):
            table_name = self._table_name_from_class(class_name)
            config = getattr(schema_cls, "Config", None)
            coerce = getattr(config, "coerce", False) if config else False
            strict = getattr(config, "strict", True) if config else True

            lines.append(f"## `{table_name}`")
            lines.append("")
            lines.append(f"**Class**: `{class_name}`")
            lines.append(f"**Coerce**: {coerce} | **Strict**: {strict}")
            lines.append("")

            schema = schema_cls.to_schema()
            lines.append("| Column | Type | Nullable | Constraints | Description |")
            lines.append("|--------|------|----------|-------------|-------------|")

            for col_name, col in schema.columns.items():
                metadata = getattr(col, "metadata", {}) or {}
                nullable = getattr(col, "nullable", False)
                desc = metadata.get("description", "")
                fk = metadata.get("fk_ref", "")
                dtype = getattr(col, "dtype", None)
                type_str = str(dtype) if dtype else "unknown"

                constraints = []
                for check in getattr(col, "checks", []):
                    name = getattr(check, "name", "")
                    stats = getattr(check, "statistics", {})
                    val = None
                    if name == "greater_than" and (val := stats.get("min_value")) is not None:
                        constraints.append(f"gt={val}")
                    elif name == "greater_or_equal" and (val := stats.get("min_value")) is not None:
                        constraints.append(f"ge={val}")
                    elif name == "less_than" and (val := stats.get("max_value")) is not None:
                        constraints.append(f"lt={val}")
                    elif name == "less_or_equal" and (val := stats.get("max_value")) is not None:
                        constraints.append(f"le={val}")
                    elif name == "in_range":
                        lo = stats.get("min_value")
                        hi = stats.get("max_value")
                        if lo is not None and hi is not None:
                            constraints.append(f"range=[{lo}, {hi}]")
                    elif name == "isin" and (val := stats.get("allowed_values")) is not None:
                        constraints.append(f"in={val}")
                    elif name == "unique_values":
                        constraints.append("unique")
                if fk:
                    constraints.append(f"FK→{fk}")
                constraint_str = ", ".join(constraints) if constraints else "—"

                lines.append(
                    f"| `{col_name}` | `{type_str}` | "
                    f"{'Yes' if nullable else 'No'} | "
                    f"{constraint_str} | {desc} |"
                )
            lines.append("")

        return "\n".join(lines)

    def generate_tier_json(self, tier: str) -> list[dict[str, Any]]:
        """Generate JSON schema reference data for a tier."""
        package = self.SCHEMA_PACKAGES.get(tier)
        if not package:
            return []

        schemas = self._discover_schemas(package)
        result: list[dict[str, Any]] = []

        for class_name, schema_cls in sorted(schemas, key=lambda x: x[0]):
            table_name = self._table_name_from_class(class_name)
            config = getattr(schema_cls, "Config", None)
            coerce = getattr(config, "coerce", False) if config else False
            strict = getattr(config, "strict", True) if config else True

            schema = schema_cls.to_schema()
            columns: list[dict[str, Any]] = []

            for col_name, col in schema.columns.items():
                metadata = getattr(col, "metadata", {}) or {}
                nullable = getattr(col, "nullable", False)
                fk = metadata.get("fk_ref", "")
                dtype = getattr(col, "dtype", None)
                type_str = str(dtype) if dtype else "unknown"

                constraints = []
                for check in getattr(col, "checks", []):
                    name = getattr(check, "name", "")
                    stats = getattr(check, "statistics", {})
                    val = None
                    if name == "greater_than" and (val := stats.get("min_value")) is not None:
                        constraints.append(f"gt={val}")
                    elif name == "greater_or_equal" and (val := stats.get("min_value")) is not None:
                        constraints.append(f"ge={val}")
                    elif name == "less_than" and (val := stats.get("max_value")) is not None:
                        constraints.append(f"lt={val}")
                    elif name == "less_or_equal" and (val := stats.get("max_value")) is not None:
                        constraints.append(f"le={val}")
                    elif name == "in_range":
                        lo = stats.get("min_value")
                        hi = stats.get("max_value")
                        if lo is not None and hi is not None:
                            constraints.append(f"range=[{lo}, {hi}]")
                    elif name == "isin" and (val := stats.get("allowed_values")) is not None:
                        constraints.append(f"in={val}")
                    elif name == "unique_values":
                        constraints.append("unique")
                if fk:
                    constraints.append(f"FK→{fk}")

                columns.append(
                    {
                        "name": col_name,
                        "type": type_str,
                        "nullable": nullable,
                        "constraints": ", ".join(constraints) if constraints else "—",
                        "description": metadata.get("description", ""),
                    }
                )

            result.append(
                {
                    "table_name": table_name,
                    "class_name": class_name,
                    "coerce": coerce,
                    "strict": strict,
                    "columns": columns,
                }
            )
        return result

    def generate_tier_stub_mdx(self, tier: str, schema_count: int) -> str:
        """Generate a lightweight MDX stub that renders from JSON."""
        json_path = f"@/lib/generated/{tier}-reference.json"
        return "\n".join(
            [
                "---",
                f"title: Schema Reference — {tier.title()}",
                f"description: Complete schema docs for {tier} tier ({schema_count} schemas)",
                "full: true",
                "---",
                "",
                f"import data from '{json_path}'",
                "import { SchemaReferenceTable } from '@/components/mdx/schema-reference-table'",
                "",
                f"# Schema Reference — {tier.title()}",
                "",
                f"This tier contains **{schema_count}** schemas.",
                "",
                "<SchemaReferenceTable data={data} />",
            ]
        )

    def write(self, tiers: list[str] | None = None) -> list[Path]:
        """Write schema reference JSON + MDX stub for specified tiers."""
        tiers = tiers or ["raw", "staging", "star"]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for tier in tiers:
            # Write JSON data
            data = self.generate_tier_json(tier)
            json_path = self.output_dir / f"{tier}-reference.json"
            json_path.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")
            logger.info(f"Wrote schema JSON: {json_path} ({len(data)} schemas)")
            written.append(json_path)

            # Write MDX stub
            content = self.generate_tier_stub_mdx(tier, len(data))
            mdx_path = self.output_dir / f"{tier}-reference.mdx"
            mdx_path.write_text(content, encoding="utf-8")
            logger.info(f"Wrote schema stub: {mdx_path}")
            written.append(mdx_path)
        return written
