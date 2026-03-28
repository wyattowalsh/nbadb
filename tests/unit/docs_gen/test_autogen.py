from __future__ import annotations

from typing import TYPE_CHECKING

from nbadb.docs_gen.autogen import generate_docs_artifacts

if TYPE_CHECKING:
    from pathlib import Path


def _expected_paths(docs_root: Path) -> list[Path]:
    return [
        docs_root / "schema" / "raw-reference.mdx",
        docs_root / "schema" / "staging-reference.mdx",
        docs_root / "schema" / "star-reference.mdx",
        docs_root / "data-dictionary" / "raw.mdx",
        docs_root / "data-dictionary" / "staging.mdx",
        docs_root / "data-dictionary" / "star.mdx",
        docs_root / "diagrams" / "er-auto.mdx",
        docs_root / "schema" / "schema.json",
        docs_root / "lineage" / "lineage-auto.mdx",
        docs_root / "lineage" / "lineage.json",
        docs_root / "_generated" / "site-metrics.generated.ts",
    ]


# Table profile is conditional on the DB file existing, so the base count
# excludes it.  These tests run without a DuckDB file.
_BASE_ARTIFACT_COUNT = 11


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
