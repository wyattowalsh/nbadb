from __future__ import annotations

import json
from pathlib import Path

from nbadb.docs_gen.data_dictionary import DataDictionaryGenerator
from nbadb.docs_gen.er_diagram import ERDiagramGenerator
from nbadb.docs_gen.lineage import LineageGenerator
from nbadb.docs_gen.schema_docs import SchemaDocsGenerator
from nbadb.docs_gen.site_metrics import (
    generate_site_metrics_module,
    resolve_site_metrics_output_path,
)
from nbadb.docs_gen.table_profile import generate_table_profile_json

DEFAULT_DOCS_ROOT = Path("docs/content/docs")
DEFAULT_DB_PATH = Path("data/nba.duckdb")
SCHEMA_TIERS = ("raw", "staging", "star")
DATA_DICTIONARY_TIERS = ("raw", "staging", "star")


def _resolve_generated_data_dir(docs_root: Path) -> Path:
    """Resolve the lib/generated directory for JSON data files."""
    docs_root = docs_root.resolve()
    if docs_root.name == "docs" and docs_root.parent.name == "content":
        return docs_root.parent.parent / "lib" / "generated"
    return docs_root / "_generated"


def _normalize_content(content: str) -> str:
    return f"{content.rstrip()}\n"


def _write_deterministic(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_content(content)
    if path.exists() and path.read_text(encoding="utf-8") == normalized:
        return False
    path.write_text(normalized, encoding="utf-8")
    return True


def _write_artifact(
    path: Path,
    content: str,
    updated_paths: list[Path],
    unchanged_paths: list[Path],
) -> None:
    if _write_deterministic(path, content):
        updated_paths.append(path)
    else:
        unchanged_paths.append(path)


def _resolve_table_profile_output_path(docs_root: Path) -> Path:
    docs_root = docs_root.resolve()
    if docs_root.name == "docs" and docs_root.parent.name == "content":
        return docs_root.parent.parent / "table-profile.generated.json"
    return docs_root / "_generated" / "table-profile.generated.json"


def generate_docs_artifacts(
    docs_root: Path = DEFAULT_DOCS_ROOT,
    db_path: Path | None = None,
) -> tuple[list[Path], list[Path]]:
    updated_paths: list[Path] = []
    unchanged_paths: list[Path] = []

    gen_data_dir = _resolve_generated_data_dir(docs_root)
    gen_data_dir.mkdir(parents=True, exist_ok=True)

    schema_gen = SchemaDocsGenerator(output_dir=docs_root / "schema")
    for tier in SCHEMA_TIERS:
        data = schema_gen.generate_tier_json(tier)
        _write_artifact(
            gen_data_dir / f"{tier}-reference.json",
            json.dumps(data, indent=2, sort_keys=False),
            updated_paths,
            unchanged_paths,
        )
        _write_artifact(
            docs_root / "schema" / f"{tier}-reference.mdx",
            schema_gen.generate_tier_stub_mdx(tier, len(data)),
            updated_paths,
            unchanged_paths,
        )

    data_dictionary_gen = DataDictionaryGenerator(output_dir=docs_root / "data-dictionary")
    for tier in DATA_DICTIONARY_TIERS:
        data = data_dictionary_gen.generate_tier_json(tier)
        _write_artifact(
            gen_data_dir / f"{tier}-dictionary.json",
            json.dumps(data, indent=2, sort_keys=False),
            updated_paths,
            unchanged_paths,
        )
        _write_artifact(
            docs_root / "data-dictionary" / f"{tier}.mdx",
            data_dictionary_gen.generate_stub_mdx(tier, len(data)),
            updated_paths,
            unchanged_paths,
        )

    er_gen = ERDiagramGenerator(output_dir=docs_root / "diagrams")
    _write_artifact(
        docs_root / "diagrams" / "er-auto.mdx",
        er_gen.generate_mdx(),
        updated_paths,
        unchanged_paths,
    )
    schema_json = json.dumps(
        er_gen.generate_json(),
        indent=2,
        sort_keys=True,
    )
    _write_artifact(
        docs_root / "schema" / "schema.json",
        schema_json,
        updated_paths,
        unchanged_paths,
    )

    lineage_gen = LineageGenerator(output_dir=docs_root / "lineage")
    _write_artifact(
        docs_root / "lineage" / "lineage-auto.mdx",
        lineage_gen.generate_mdx(),
        updated_paths,
        unchanged_paths,
    )
    lineage_json = json.dumps(
        lineage_gen.generate_dict(),
        indent=2,
        sort_keys=True,
    )
    _write_artifact(
        docs_root / "lineage" / "lineage.json",
        lineage_json,
        updated_paths,
        unchanged_paths,
    )

    _write_artifact(
        resolve_site_metrics_output_path(docs_root),
        generate_site_metrics_module(docs_root),
        updated_paths,
        unchanged_paths,
    )

    resolved_db = db_path or DEFAULT_DB_PATH
    if resolved_db.exists():
        _write_artifact(
            _resolve_table_profile_output_path(docs_root),
            generate_table_profile_json(resolved_db),
            updated_paths,
            unchanged_paths,
        )

    return updated_paths, unchanged_paths
