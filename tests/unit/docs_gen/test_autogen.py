from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from nbadb.docs_gen.autogen import (
    OBSOLETE_LEGACY_GENERATED_FILES,
    _resolve_generated_data_dir,
    check_docs_artifacts,
    generate_docs_artifacts,
    generated_artifact_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path


def _expected_paths(docs_root: Path) -> list[Path]:
    return list(generated_artifact_manifest(docs_root).generated_paths)


# Table profile is conditional on the DB file existing, so the base count
# excludes it.  These tests run without a DuckDB file.
_BASE_ARTIFACT_COUNT = 19


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


def test_generated_artifact_manifest_includes_obsolete_legacy_files(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs" / "content" / "docs"
    generated_dir = tmp_path / "docs" / "lib" / "generated"

    manifest = generated_artifact_manifest(docs_root)

    assert manifest.obsolete_paths == tuple(
        generated_dir / filename for filename in OBSOLETE_LEGACY_GENERATED_FILES
    )


def test_generate_docs_artifacts_removes_obsolete_legacy_files(tmp_path: Path) -> None:
    generated_dir = _resolve_generated_data_dir(tmp_path)
    obsolete_path = generated_dir / "raw.json"
    obsolete_path.parent.mkdir(parents=True)
    obsolete_path.write_text("{}\n", encoding="utf-8")

    generate_docs_artifacts(tmp_path)

    assert not obsolete_path.exists()


def test_check_docs_artifacts_reports_no_drift_after_generation(tmp_path: Path) -> None:
    generate_docs_artifacts(tmp_path)

    assert check_docs_artifacts(tmp_path) == []


def test_check_docs_artifacts_reports_stale_file(tmp_path: Path) -> None:
    generate_docs_artifacts(tmp_path)
    stale_path = _resolve_generated_data_dir(tmp_path) / "star-reference.json"
    stale_path.write_text("[]\n", encoding="utf-8")

    stale_paths = check_docs_artifacts(tmp_path)

    assert stale_path in stale_paths


def test_check_docs_artifacts_reports_obsolete_legacy_file(tmp_path: Path) -> None:
    generate_docs_artifacts(tmp_path)
    obsolete_path = _resolve_generated_data_dir(tmp_path) / "star.json"
    obsolete_path.write_text("{}\n", encoding="utf-8")

    stale_paths = check_docs_artifacts(tmp_path)

    assert obsolete_path in stale_paths


def test_docs_gen_module_check_passes_after_generation(tmp_path: Path) -> None:
    generate_docs_artifacts(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nbadb.docs_gen",
            "--docs-root",
            str(tmp_path),
            "--check",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Docs autogen check passed." in result.stdout
