from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nbadb.schemas.registry import _star_schema_registry

if TYPE_CHECKING:
    from nbadb.schemas.base import BaseSchema


class ERDiagramGenerator:
    """Generate Mermaid ER diagrams from Pandera schema FK metadata.

    Reads fk_ref metadata from star schema fields to build
    relationship edges between tables.
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("docs/content/docs/diagrams")

    def _discover_schemas(
        self,
    ) -> list[tuple[str, type[BaseSchema]]]:
        """Return public star schemas from the registry source of truth."""
        return sorted(_star_schema_registry().items())

    def _table_name_from_class(self, class_name: str) -> str:
        """Convert class name to table name (CamelCase → snake_case)."""
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

    def _extract_relationships(
        self, table_name: str, schema_cls: type[BaseSchema]
    ) -> list[dict[str, str]]:
        """Extract FK relationships from schema metadata."""
        rels: list[dict[str, str]] = []
        schema = schema_cls.to_schema()
        annotations = {}
        for cls in reversed(schema_cls.__mro__):
            annotations.update(getattr(cls, "__annotations__", {}))

        for field_name in annotations:
            if field_name.startswith("_"):
                continue
            effective_name = getattr(schema_cls, field_name, field_name)
            field_obj = schema.columns.get(effective_name)
            if field_obj is None:
                continue
            metadata = field_obj.metadata or {}
            fk_ref = metadata.get("fk_ref", "")
            if fk_ref and "." in fk_ref:
                ref_table, ref_col = fk_ref.split(".", 1)
                rels.append(
                    {
                        "from_table": table_name,
                        "from_col": str(effective_name),
                        "to_table": ref_table,
                        "to_col": ref_col,
                    }
                )
        return rels

    def _extract_columns(self, schema_cls: type[BaseSchema]) -> list[dict[str, str]]:
        """Extract column info for ER entity block."""
        cols: list[dict[str, str]] = []
        annotations = {}
        for cls in reversed(schema_cls.__mro__):
            annotations.update(getattr(cls, "__annotations__", {}))

        schema = schema_cls.to_schema()
        for field_name, field_type in annotations.items():
            # Skip internal fields
            if field_name == "Config" or field_name.startswith("_"):
                continue
            effective_name = getattr(schema_cls, field_name, field_name)
            field_obj = schema.columns.get(effective_name)
            if field_obj is None:
                continue
            type_str = str(field_type)
            if " | None" in type_str:
                type_str = type_str.replace(" | None", "")
            metadata = field_obj.metadata or {}
            pk = "PK" if metadata.get("primary_key") is True else ""
            fk = "FK" if metadata.get("fk_ref") else ""
            key = pk or fk
            cols.append({"name": str(effective_name), "type": type_str, "key": key})
        return cols

    def _family_from_table_name(self, table_name: str) -> str:
        """Derive the schema family from a table name prefix."""
        for prefix in ("analytics_", "bridge_", "agg_", "dim_", "fact_"):
            if table_name.startswith(prefix):
                return prefix.rstrip("_")
        return "other"

    def generate_json(self) -> dict[str, object]:
        """Generate a JSON-serializable dict of all star-schema tables.

        Returns a structure like::

            {
                "tables": {
                    "dim_player": {
                        "family": "dim",
                        "columns": [
                            {"name": "player_id", "type": "int", "key": "PK"},
                            ...
                        ],
                        "relationships": [
                            {"from_col": "team_id", "to_table": "dim_team", "to_col": "team_id"}
                        ]
                    },
                    ...
                }
            }
        """
        schemas = self._discover_schemas()
        tables: dict[str, dict[str, object]] = {}

        for table_name, schema_cls in schemas:
            # Skip internal mixin/base classes
            if table_name.startswith("__") or table_name.startswith("_"):
                continue
            family = self._family_from_table_name(table_name)
            if family == "other":
                continue
            columns = [col for col in self._extract_columns(schema_cls) if col["name"] != "Config"]
            raw_rels = self._extract_relationships(table_name, schema_cls)
            relationships = [
                {
                    "from_col": r["from_col"],
                    "to_table": r["to_table"],
                    "to_col": r["to_col"],
                }
                for r in raw_rels
            ]
            tables[table_name] = {
                "family": family,
                "columns": columns,
                "relationships": relationships,
            }

        return {"tables": tables}

    def generate_mermaid(
        self,
        filter_prefix: str | None = None,
    ) -> str:
        """Generate Mermaid erDiagram syntax."""
        schemas = self._discover_schemas()
        lines = ["erDiagram"]

        all_rels: list[dict[str, str]] = []
        table_cols: dict[str, list[dict[str, str]]] = {}

        for table_name, schema_cls in schemas:
            if filter_prefix and not table_name.startswith(filter_prefix):
                continue
            rels = self._extract_relationships(table_name, schema_cls)
            all_rels.extend(rels)
            table_cols[table_name] = self._extract_columns(schema_cls)

        for table_name, cols in sorted(table_cols.items()):
            lines.append(f"    {table_name} {{")
            for col in cols:
                key_marker = f" {col['key']}" if col["key"] else ""
                lines.append(f"        {col['type']} {col['name']}{key_marker}")
            lines.append("    }")

        seen_rels: set[tuple[str, str, str, str]] = set()
        for rel in all_rels:
            identity = (
                rel["from_table"],
                rel["from_col"],
                rel["to_table"],
                rel["to_col"],
            )
            if identity in seen_rels:
                continue
            seen_rels.add(identity)
            if rel["from_table"] in table_cols and rel["to_table"] in table_cols:
                lines.append(
                    f'    {rel["to_table"]} ||--o{{ {rel["from_table"]} : "{rel["from_col"]}"'
                )

        return "\n".join(lines)

    def _generate_family_mermaid(
        self,
        family_prefixes: list[str],
    ) -> str:
        """Generate a Mermaid erDiagram for tables matching the given prefixes.

        Cross-family relationships are included when the *source* table
        belongs to one of the requested families (e.g. a fact→dim FK
        appears in the facts sub-diagram).
        """
        schemas = self._discover_schemas()
        lines = ["erDiagram"]

        all_rels: list[dict[str, str]] = []
        table_cols: dict[str, list[dict[str, str]]] = {}
        family_tables: set[str] = set()

        for table_name, schema_cls in schemas:
            if not any(table_name.startswith(p) for p in family_prefixes):
                continue
            family_tables.add(table_name)
            rels = self._extract_relationships(table_name, schema_cls)
            all_rels.extend(rels)
            table_cols[table_name] = self._extract_columns(schema_cls)

        # Also discover referenced cross-family tables so the relationship
        # target entities appear in the diagram.
        cross_tables: set[str] = set()
        for rel in all_rels:
            if rel["to_table"] not in family_tables:
                cross_tables.add(rel["to_table"])

        # Add cross-family target entities (columns discovered from schemas)
        for table_name, schema_cls in schemas:
            if table_name in cross_tables and table_name not in table_cols:
                table_cols[table_name] = self._extract_columns(schema_cls)

        for table_name, cols in sorted(table_cols.items()):
            lines.append(f"    {table_name} {{")
            for col in cols:
                key_marker = f" {col['key']}" if col["key"] else ""
                lines.append(f"        {col['type']} {col['name']}{key_marker}")
            lines.append("    }")

        seen_rels: set[tuple[str, str, str, str]] = set()
        for rel in all_rels:
            identity = (
                rel["from_table"],
                rel["from_col"],
                rel["to_table"],
                rel["to_col"],
            )
            if identity in seen_rels:
                continue
            seen_rels.add(identity)
            if rel["from_table"] in table_cols and rel["to_table"] in table_cols:
                lines.append(
                    f'    {rel["to_table"]} ||--o{{ {rel["from_table"]} : "{rel["from_col"]}"'
                )

        return "\n".join(lines)

    def generate_mdx(self) -> str:
        """Generate ER diagram MDX split into per-family sub-diagrams."""
        dim_mermaid = self._generate_family_mermaid(["dim_"])
        fact_mermaid = self._generate_family_mermaid(["fact_"])
        other_mermaid = self._generate_family_mermaid(["bridge_", "agg_", "analytics_"])

        sections = [
            "---\n"
            "title: ER Diagram\n"
            "description: Star schema entity-relationship diagram\n"
            "---\n\n"
            "# Star Schema ER Diagram\n\n"
            "{/* Auto-generated by nbadb docs-gen. Do not edit by hand. */}\n"
            "{/* Regenerate: uv run nbadb docs-autogen --docs-root docs/content/docs */}\n",
            f"## Dimensions\n\n```mermaid\n{dim_mermaid}\n```\n",
            f"## Facts\n\n```mermaid\n{fact_mermaid}\n```\n",
            f"## Bridges, Aggregates & Analytics\n\n```mermaid\n{other_mermaid}\n```\n",
        ]
        return "\n".join(sections)

    def write(self) -> Path:
        """Write ER diagram MDX file."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / "er-auto.mdx"
        path.write_text(self.generate_mdx(), encoding="utf-8")
        logger.info(f"Wrote ER diagram: {path}")
        return path
