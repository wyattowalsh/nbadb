from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from nbadb.contracts.fixture_manifest import (
    NbaApiFixtureManifestError,
    fixture_manifest_bytes,
    write_fixture_manifest,
)


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture
def upstream_root() -> Path:
    raw = os.environ.get("NBADB_NBA_API_UPSTREAM_ROOT")
    if not raw:
        pytest.skip("exact-source fixture generation requires NBADB_NBA_API_UPSTREAM_ROOT")
    return Path(raw)


def test_checked_fixture_manifest_matches_two_distinct_generations(
    project_root: Path,
    upstream_root: Path,
    tmp_path: Path,
) -> None:
    checked = project_root / "tests/fixtures/nba_api_contract/manifest.json"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert (
        write_fixture_manifest(
            first,
            project_root=project_root,
            upstream_root=upstream_root,
        )
        is False
    )
    assert (
        write_fixture_manifest(
            second,
            project_root=project_root,
            upstream_root=upstream_root,
        )
        is False
    )
    assert first.read_bytes() == second.read_bytes() == checked.read_bytes()
    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        == hashlib.sha256(checked.read_bytes()).hexdigest()
    )


def test_fixture_manifest_writer_is_idempotent_and_check_fails_closed(
    project_root: Path,
    upstream_root: Path,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "manifest.json"

    assert (
        write_fixture_manifest(
            candidate,
            project_root=project_root,
            upstream_root=upstream_root,
        )
        is False
    )
    assert (
        write_fixture_manifest(
            candidate,
            project_root=project_root,
            upstream_root=upstream_root,
        )
        is True
    )
    assert (
        write_fixture_manifest(
            candidate,
            project_root=project_root,
            upstream_root=upstream_root,
            check=True,
        )
        is True
    )
    candidate.write_text("{}\n", encoding="utf-8")
    with pytest.raises(NbaApiFixtureManifestError, match="generated drift"):
        write_fixture_manifest(
            candidate,
            project_root=project_root,
            upstream_root=upstream_root,
            check=True,
        )


def test_fixture_manifest_bytes_are_stable(
    project_root: Path,
    upstream_root: Path,
) -> None:
    first = fixture_manifest_bytes(
        project_root=project_root,
        upstream_root=upstream_root,
    )
    second = fixture_manifest_bytes(
        project_root=project_root,
        upstream_root=upstream_root,
    )

    assert first == second
