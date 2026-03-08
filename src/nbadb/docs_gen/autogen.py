from __future__ import annotations

import json
from pathlib import Path

from nbadb.docs_gen.data_dictionary import DataDictionaryGenerator
from nbadb.docs_gen.er_diagram import ERDiagramGenerator
from nbadb.docs_gen.lineage import LineageGenerator
from nbadb.docs_gen.schema_docs import SchemaDocsGenerator

DEFAULT_DOCS_ROOT = Path("docs/content/docs")
SCHEMA_TIERS = ("raw", "staging", "star")
DATA_DICTIONARY_TIERS = ("raw", "staging", "star")


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


def generate_docs_artifacts(docs_root: Path = DEFAULT_DOCS_ROOT) -> tuple[list[Path], list[Path]]:
    updated_paths: list[Path] = []
    unchanged_paths: list[Path] = []

    schema_gen = SchemaDocsGenerator(output_dir=docs_root / "schema")
    for tier in SCHEMA_TIERS:
        _write_artifact(
            docs_root / "schema" / f"{tier}-reference.mdx",
            schema_gen.generate_tier_mdx(tier),
            updated_paths,
            unchanged_paths,
        )

    data_dictionary_gen = DataDictionaryGenerator(output_dir=docs_root / "data-dictionary")
    for tier in DATA_DICTIONARY_TIERS:
        _write_artifact(
            docs_root / "data-dictionary" / f"{tier}.mdx",
            data_dictionary_gen.generate_mdx(tier),
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

    lineage_gen = LineageGenerator(output_dir=docs_root / "lineage")
    _write_artifact(
        docs_root / "lineage" / "lineage-auto.mdx",
        lineage_gen.generate_mdx(),
        updated_paths,
        unchanged_paths,
    )
    lineage_json = json.dumps(
        json.loads(lineage_gen.generate_json()),
        indent=2,
        sort_keys=True,
    )
    _write_artifact(
        docs_root / "lineage" / "lineage.json",
        lineage_json,
        updated_paths,
        unchanged_paths,
    )

    return updated_paths, unchanged_paths
