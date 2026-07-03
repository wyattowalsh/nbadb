from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nbadb.core.field_docs import resolved_field_description
from nbadb.schemas.registry import (
    _raw_schema_registry,
    _staging_schema_registry,
    _star_schema_registry,
)

if TYPE_CHECKING:
    from nbadb.schemas.base import BaseSchema


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
    SCHEMA_REGISTRIES = {
        "raw": _raw_schema_registry,
        "staging": _staging_schema_registry,
        "star": _star_schema_registry,
    }

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("docs/content/docs/data-dictionary")

    def _discover_schemas(self, tier: str) -> list[tuple[str, type[BaseSchema]]]:
        """Return public schemas for a tier using the registry source of truth."""
        registry_factory = self.SCHEMA_REGISTRIES.get(tier)
        if registry_factory is None:
            logger.warning(f"Unknown schema tier {tier}")
            return []
        return sorted(registry_factory().items())

    def _extract_fields(
        self,
        schema_cls: type[BaseSchema],
        *,
        table_name: str,
        tier: str,
    ) -> list[dict[str, Any]]:
        """Extract field metadata from a schema class."""
        fields: list[dict[str, Any]] = []
        schema = schema_cls.to_schema()
        for col_name, col in schema.columns.items():
            metadata = getattr(col, "metadata", {}) or {}
            nullable = getattr(col, "nullable", False)
            dtype = getattr(col, "dtype", None)
            type_str = str(dtype) if dtype else "unknown"
            description, description_source = resolved_field_description(
                metadata.get("description", ""),
                col_name,
                table_name=table_name,
                tier=tier,
            )

            fields.append(
                {
                    "name": col_name,
                    "type": type_str,
                    "nullable": nullable,
                    "description": description,
                    "description_source": description_source,
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
        schemas = self._discover_schemas(tier)
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

        for table_name, schema_cls in schemas:
            fields = self._extract_fields(schema_cls, table_name=table_name, tier=tier)
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
        schemas = self._discover_schemas(tier)
        result: dict[str, Any] = {}
        for table_name, schema_cls in schemas:
            result[table_name] = self._extract_fields(
                schema_cls,
                table_name=table_name,
                tier=tier,
            )
        return json.dumps(result, indent=2)

    def generate_tier_json(self, tier: str = "star") -> list[dict[str, Any]]:
        """Generate JSON data dictionary for a tier."""
        schemas = self._discover_schemas(tier)
        result: list[dict[str, Any]] = []
        for table_name, schema_cls in schemas:
            fields = self._extract_fields(schema_cls, table_name=table_name, tier=tier)
            result.append({"table_name": table_name, "fields": fields})
        return result

    def generate_stub_mdx(self, tier: str, table_count: int) -> str:
        """Generate a lightweight MDX stub that renders from JSON."""
        json_path = f"@/lib/generated/{tier}-dictionary.json"
        return "\n".join(
            [
                "---",
                f"title: Data Dictionary — {tier.title()}",
                f"description: Field-level docs for {tier} tables ({table_count} total)",
                "full: true",
                "---",
                "",
                f"import data from '{json_path}'",
                "import { DataDictionaryTable } from '@/components/mdx/schema-reference-table'",
                "",
                f"# Data Dictionary — {tier.title()}",
                "",
                f"This tier contains **{table_count}** tables.",
                "",
                "<DataDictionaryTable data={data} />",
            ]
        )

    def write(self, tiers: list[str] | None = None) -> list[Path]:
        """Write data dictionary JSON + MDX stub for specified tiers."""
        tiers = tiers or ["star", "staging", "raw"]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for tier in tiers:
            # Write JSON data
            data = self.generate_tier_json(tier)
            json_path = self.output_dir / f"{tier}.json"
            json_path.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")
            logger.info(f"Wrote data dictionary JSON: {json_path} ({len(data)} tables)")
            written.append(json_path)

            # Write MDX stub
            content = self.generate_stub_mdx(tier, len(data))
            mdx_path = self.output_dir / f"{tier}.mdx"
            mdx_path.write_text(content, encoding="utf-8")
            logger.info(f"Wrote data dictionary stub: {mdx_path}")
            written.append(mdx_path)
        return written
