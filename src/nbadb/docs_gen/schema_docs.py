from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pandera.polars as pa
from loguru import logger


class SchemaDocsGenerator:
    """Generate complete schema reference MDX from Pandera models.

    Produces one MDX file per schema tier with full table/column docs.
    """

    SCHEMA_PACKAGES = {
        "raw": "nbadb.schemas.raw",
        "staging": "nbadb.schemas.staging",
        "star": "nbadb.schemas.star",
    }

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("docs/content/docs/schema")

    def _discover_schemas(
        self, package_name: str
    ) -> list[tuple[str, type[pa.DataFrameModel]]]:
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

            annotations = {}
            for cls in reversed(schema_cls.__mro__):
                annotations.update(getattr(cls, "__annotations__", {}))

            lines.append("| Column | Type | Nullable | Constraints | Description |")
            lines.append("|--------|------|----------|-------------|-------------|")

            for field_name, field_type in annotations.items():
                if field_name.startswith("_"):
                    continue
                field_obj = getattr(schema_cls, field_name, None)
                if field_obj is None:
                    continue
                metadata = getattr(field_obj, "metadata", {}) or {}
                nullable = getattr(field_obj, "nullable", False)
                desc = metadata.get("description", "")
                fk = metadata.get("fk_ref", "")

                constraints = []
                for attr in ("gt", "ge", "lt", "le"):
                    val = getattr(field_obj, attr, None)
                    if val is not None:
                        constraints.append(f"{attr}={val}")
                if fk:
                    constraints.append(f"FK→{fk}")
                constraint_str = ", ".join(constraints) if constraints else "—"

                type_str = str(field_type)
                if " | None" in type_str:
                    type_str = type_str.replace(" | None", "")

                lines.append(
                    f"| `{field_name}` | `{type_str}` | "
                    f"{'Yes' if nullable else 'No'} | "
                    f"{constraint_str} | {desc} |"
                )
            lines.append("")

        return "\n".join(lines)

    def write(self, tiers: list[str] | None = None) -> list[Path]:
        """Write schema reference MDX for specified tiers."""
        tiers = tiers or ["raw", "staging", "star"]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for tier in tiers:
            content = self.generate_tier_mdx(tier)
            path = self.output_dir / f"{tier}-reference.mdx"
            path.write_text(content, encoding="utf-8")
            logger.info(f"Wrote schema docs: {path}")
            written.append(path)
        return written
