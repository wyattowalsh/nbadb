from __future__ import annotations

from typing import TYPE_CHECKING

from nbadb.docs_gen.autogen import _resolve_generated_data_dir, generate_docs_artifacts
from nbadb.docs_gen.site_metrics import resolve_site_metrics_output_path

if TYPE_CHECKING:
    from pathlib import Path


def _expected_paths(docs_root: Path) -> list[Path]:
    generated_dir = _resolve_generated_data_dir(docs_root)
    return [
        generated_dir / "raw-reference.json",
        generated_dir / "staging-reference.json",
        generated_dir / "star-reference.json",
        docs_root / "schema" / "raw-reference.mdx",
        docs_root / "schema" / "staging-reference.mdx",
        docs_root / "schema" / "star-reference.mdx",
        generated_dir / "raw-dictionary.json",
        generated_dir / "staging-dictionary.json",
        generated_dir / "star-dictionary.json",
        docs_root / "data-dictionary" / "raw.mdx",
        docs_root / "data-dictionary" / "staging.mdx",
        docs_root / "data-dictionary" / "star.mdx",
        docs_root / "diagrams" / "er-auto.mdx",
        generated_dir / "schema.json",
        docs_root / "lineage" / "lineage-auto.mdx",
        generated_dir / "lineage.json",
        generated_dir / "schema-coverage.json",
        resolve_site_metrics_output_path(docs_root),
    ]


# Table profile is conditional on the DB file existing, so the base count
# excludes it.  These tests run without a DuckDB file.
_BASE_ARTIFACT_COUNT = 18


def test_generate_docs_artifacts_creates_expected_files(tmp_path: Path) -> None:
    updated, unchanged = generate_docs_artifacts(tmp_path)

    assert len(updated) == _BASE_ARTIFACT_COUNT
    assert len(unchanged) == 0
    for expected_path in _expected_paths(tmp_path):
        assert expected_path.exists()


def test_generate_docs_artifacts_is_deterministic(tmp_path: Path) -> None:
    generate_docs_artifacts(tmp_path)
    updated, unchanged = generate_docs_artifacts(tmp_path)

    assert len(updated) == 0
    assert len(unchanged) == _BASE_ARTIFACT_COUNT
