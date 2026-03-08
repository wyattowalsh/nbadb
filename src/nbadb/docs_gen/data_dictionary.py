from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from typing import Any

import pandera.polars as pa
from loguru import logger


class DataDictionaryGenerator:
    """Generate data dictionary MDX from Pandera schema metadata.

    Scans all schema modules under nbadb.schemas.star and extracts
    field-level metadata (description, source, fk_ref, nullable, type).
    """

    SCHEMA_PACKAGES = [
        "nbadb.schemas.star",
        "nbadb.schemas.staging",
        "nbadb.schemas.raw",
    ]

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("docs/content/docs/data-dictionary")

    def _discover_schemas(self, package_name: str) -> list[tuple[str, type[pa.DataFrameModel]]]:
        """Discover all DataFrameModel subclasses in a package."""
        schemas: list[tuple[str, type[pa.DataFrameModel]]] = []
        try:
            pkg = importlib.import_module(package_name)
        except ImportError:
            logger.warning(f"Could not import {package_name}")
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
                logger.warning(f"Could not import {module_name}")
                continue

            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, pa.DataFrameModel)
                    and obj is not pa.DataFrameModel
                    and obj.__module__ == module_name
                ):
                    schemas.append((name, obj))
        return schemas

    def _extract_fields(self, schema_cls: type[pa.DataFrameModel]) -> list[dict[str, Any]]:
        """Extract field metadata from a schema class."""
        fields: list[dict[str, Any]] = []
        schema = schema_cls.to_schema()
        for col_name, col in schema.columns.items():
            metadata = getattr(col, "metadata", {}) or {}
            nullable = getattr(col, "nullable", False)
            dtype = getattr(col, "dtype", None)
            type_str = str(dtype) if dtype else "unknown"

            fields.append(
                {
                    "name": col_name,
                    "type": type_str,
                    "nullable": nullable,
                    "description": metadata.get("description", ""),
                    "source": metadata.get("source", ""),
                    "fk_ref": metadata.get("fk_ref", ""),
                }
            )
        return fields

    def _table_name_from_class(self, class_name: str) -> str:
        """Convert schema class name to table name."""
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

    def generate_mdx(self, tier: str = "star") -> str:
        """Generate MDX content for a schema tier."""
        package = f"nbadb.schemas.{tier}"
        schemas = self._discover_schemas(package)
        if not schemas:
            return f"# Data Dictionary — {tier.title()}\n\nNo schemas found.\n"

        lines = [
            "---",
            f"title: Data Dictionary — {tier.title()}",
            f"description: Field-level documentation for all {tier} schema tables",
            "---",
            "",
            f"# Data Dictionary — {tier.title()}",
            "",
        ]

        for class_name, schema_cls in sorted(schemas, key=lambda x: x[0]):
            table_name = self._table_name_from_class(class_name)
            fields = self._extract_fields(schema_cls)
            lines.append(f"## {table_name}")
            lines.append("")
            lines.append("| Column | Type | Nullable | Description | Source |")
            lines.append("|--------|------|----------|-------------|--------|")
            for f in fields:
                fk = f" (FK → {f['fk_ref']})" if f["fk_ref"] else ""
                lines.append(
                    f"| `{f['name']}` | `{f['type']}` | "
                    f"{'Yes' if f['nullable'] else 'No'} | "
                    f"{f['description']}{fk} | "
                    f"`{f['source']}` |"
                )
            lines.append("")

        return "\n".join(lines)

    def generate_json(self, tier: str = "star") -> str:
        """Generate JSON data dictionary for programmatic use."""
        package = f"nbadb.schemas.{tier}"
        schemas = self._discover_schemas(package)
        result: dict[str, Any] = {}
        for class_name, schema_cls in schemas:
            table_name = self._table_name_from_class(class_name)
            result[table_name] = self._extract_fields(schema_cls)
        return json.dumps(result, indent=2)

    def write(self, tiers: list[str] | None = None) -> list[Path]:
        """Write MDX files for specified tiers."""
        tiers = tiers or ["star", "staging", "raw"]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for tier in tiers:
            content = self.generate_mdx(tier)
            path = self.output_dir / f"{tier}.mdx"
            path.write_text(content, encoding="utf-8")
            logger.info(f"Wrote data dictionary: {path}")
            written.append(path)
        return written
