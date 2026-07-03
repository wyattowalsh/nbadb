from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from nbadb.docs_gen.data_dictionary import DataDictionaryGenerator
from nbadb.docs_gen.er_diagram import ERDiagramGenerator
from nbadb.docs_gen.lineage import LineageGenerator
from nbadb.docs_gen.schema_agent_export import export_schema_agent_metadata
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
OBSOLETE_LEGACY_GENERATED_FILES = ("raw.json", "staging.json", "star.json")


@dataclass(frozen=True)
class GeneratedArtifactManifest:
    generated_paths: tuple[Path, ...]
    obsolete_paths: tuple[Path, ...]


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


def generated_artifact_manifest(
    docs_root: Path = DEFAULT_DOCS_ROOT,
    db_path: Path | None = None,
) -> GeneratedArtifactManifest:
    generated_dir = _resolve_generated_data_dir(docs_root)
    generated_paths = [
        *(generated_dir / f"{tier}-reference.json" for tier in SCHEMA_TIERS),
        *(docs_root / "schema" / f"{tier}-reference.mdx" for tier in SCHEMA_TIERS),
        *(generated_dir / f"{tier}-dictionary.json" for tier in DATA_DICTIONARY_TIERS),
        *(docs_root / "data-dictionary" / f"{tier}.mdx" for tier in DATA_DICTIONARY_TIERS),
        docs_root / "diagrams" / "er-auto.mdx",
        generated_dir / "schema.json",
        docs_root / "lineage" / "lineage-auto.mdx",
        generated_dir / "lineage.json",
        generated_dir / "schema-coverage.json",
        generated_dir / "agent-catalog.json",
        resolve_site_metrics_output_path(docs_root),
    ]

    resolved_db = db_path or DEFAULT_DB_PATH
    if resolved_db.exists():
        generated_paths.append(_resolve_table_profile_output_path(docs_root))

    return GeneratedArtifactManifest(
        generated_paths=tuple(generated_paths),
        obsolete_paths=tuple(
            generated_dir / filename for filename in OBSOLETE_LEGACY_GENERATED_FILES
        ),
    )


def _remove_obsolete_generated_artifacts(docs_root: Path) -> list[Path]:
    removed_paths: list[Path] = []
    for path in generated_artifact_manifest(docs_root).obsolete_paths:
        if path.exists() or path.is_symlink():
            path.unlink()
            removed_paths.append(path)
    return removed_paths


def _generation_base_for_docs_root(docs_root: Path) -> Path:
    docs_root = docs_root.resolve()
    if docs_root.name == "docs" and docs_root.parent.name == "content":
        return docs_root.parent.parent
    return docs_root


def _format_temp_generated_artifacts(
    *,
    actual_base: Path,
    generated_paths: list[Path],
) -> None:
    """Format temporary generated docs exactly as the docs site does."""
    if not (actual_base / "package.json").is_file():
        return

    candidates = [
        path for path in generated_paths if path.suffix in {".json", ".mdx", ".ts", ".tsx"}
    ]
    if not candidates:
        return

    subprocess.run(
        ["pnpm", "exec", "prettier", "--write", *[str(path.resolve()) for path in candidates]],
        cwd=actual_base,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def generate_docs_artifacts(
    docs_root: Path = DEFAULT_DOCS_ROOT,
    db_path: Path | None = None,
) -> tuple[list[Path], list[Path]]:
    updated_paths: list[Path] = []
    unchanged_paths: list[Path] = []

    gen_data_dir = _resolve_generated_data_dir(docs_root)
    gen_data_dir.mkdir(parents=True, exist_ok=True)
    _remove_obsolete_generated_artifacts(docs_root)

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
    schema_data = er_gen.generate_json()
    tables_data = schema_data.get("tables")
    if not isinstance(tables_data, dict):
        msg = "ER diagram generator returned invalid schema data"
        raise TypeError(msg)
    schema_tables = set(tables_data)
    _write_artifact(
        docs_root / "diagrams" / "er-auto.mdx",
        er_gen.generate_mdx(),
        updated_paths,
        unchanged_paths,
    )
    schema_json = json.dumps(
        schema_data,
        indent=2,
        sort_keys=True,
    )
    _write_artifact(
        gen_data_dir / "schema.json",
        schema_json,
        updated_paths,
        unchanged_paths,
    )

    lineage_gen = LineageGenerator(output_dir=docs_root / "lineage")
    lineage_data = lineage_gen.generate_dict()
    lineage_outputs = set(lineage_data.keys())
    missing_schema_outputs = sorted(lineage_outputs - schema_tables)
    schema_coverage = {
        "schema_table_count": len(schema_tables),
        "lineage_output_count": len(lineage_outputs),
        "missing_schema_output_count": len(missing_schema_outputs),
        "missing_schema_outputs": missing_schema_outputs,
    }
    if missing_schema_outputs:
        coverage_note = (
            "## Coverage Notes\n\n"
            "- `schema.json` documents "
            f"**{len(schema_tables)}** schema-backed tables/views.\n"
            f"- `lineage.json` traces **{len(lineage_outputs)}** outputs.\n"
            "- "
            f"**{len(missing_schema_outputs)}** lineage outputs currently have "
            "no schema reference entry. "
            "See `schema-coverage.json` for the machine-readable list.\n"
        )
    else:
        coverage_note = (
            "## Coverage Notes\n\n"
            "`schema.json` and `lineage.json` are aligned across "
            f"**{len(lineage_outputs)}** outputs.\n"
        )
    _write_artifact(
        docs_root / "lineage" / "lineage-auto.mdx",
        f"{lineage_gen.generate_mdx().rstrip()}\n\n{coverage_note}",
        updated_paths,
        unchanged_paths,
    )
    lineage_json = json.dumps(
        lineage_data,
        indent=2,
        sort_keys=True,
    )
    _write_artifact(
        gen_data_dir / "lineage.json",
        lineage_json,
        updated_paths,
        unchanged_paths,
    )
    _write_artifact(
        gen_data_dir / "schema-coverage.json",
        json.dumps(schema_coverage, indent=2, sort_keys=True),
        updated_paths,
        unchanged_paths,
    )
    _write_artifact(
        gen_data_dir / "agent-catalog.json",
        json.dumps(export_schema_agent_metadata(), indent=2, sort_keys=True),
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

    _format_temp_generated_artifacts(
        actual_base=_generation_base_for_docs_root(docs_root),
        generated_paths=[*updated_paths, *unchanged_paths],
    )

    return updated_paths, unchanged_paths


def check_docs_artifacts(
    docs_root: Path = DEFAULT_DOCS_ROOT,
    db_path: Path | None = None,
) -> list[Path]:
    """Return generated artifact paths whose committed content is stale.

    The check mirrors the docs tree into a temporary location before generation
    so homepage metrics that count MDX pages remain comparable while the real
    repository files are left untouched.
    """
    actual_docs_root = docs_root.resolve()
    actual_base = _generation_base_for_docs_root(actual_docs_root)
    stale_paths = [
        path
        for path in generated_artifact_manifest(actual_docs_root, db_path=db_path).obsolete_paths
        if path.exists() or path.is_symlink()
    ]

    with tempfile.TemporaryDirectory(prefix="nbadb-docs-autogen-") as tmp:
        tmp_base = Path(tmp) / "docs-site"
        if actual_docs_root.name == "docs" and actual_docs_root.parent.name == "content":
            tmp_docs_root = tmp_base / "content" / "docs"
        else:
            tmp_docs_root = tmp_base

        shutil.copytree(actual_docs_root, tmp_docs_root, dirs_exist_ok=True)
        updated_paths, unchanged_paths = generate_docs_artifacts(tmp_docs_root, db_path=db_path)
        generated_paths = [*updated_paths, *unchanged_paths]
        _format_temp_generated_artifacts(
            actual_base=actual_base,
            generated_paths=generated_paths,
        )

        for generated_path in generated_paths:
            relative_path = generated_path.resolve().relative_to(tmp_base.resolve())
            actual_path = actual_base / relative_path
            if not actual_path.exists():
                stale_paths.append(actual_path)
                continue
            actual_text = actual_path.read_text(encoding="utf-8")
            generated_text = generated_path.read_text(encoding="utf-8")
            if actual_text != generated_text:
                stale_paths.append(actual_path)

    return sorted(set(stale_paths))
