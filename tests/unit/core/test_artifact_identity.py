from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

import nbadb.core.artifact_identity as artifact_identity
from nbadb.core.artifact_identity import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    build_assured_artifact_manifest,
    main,
    verify_assured_artifact_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path

_SOURCE_SHA = "a" * 40
_COVERAGE_FINGERPRINT = "b" * 64


def _write_artifact(root: Path) -> None:
    (root / "parquet" / "dim_player").mkdir(parents=True)
    (root / "nba.duckdb").write_bytes(b"duckdb")
    (root / "parquet" / "dim_player" / "part-0.parquet").write_bytes(b"parquet")


def test_build_and_verify_manifest_round_trip(tmp_path: Path) -> None:
    _write_artifact(tmp_path)

    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    manifest = verify_assured_artifact_manifest(
        tmp_path,
        expected_chain_id="full-20260711",
        expected_source_sha=_SOURCE_SHA,
        expected_coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )

    assert manifest_path == tmp_path / ASSURED_ARTIFACT_MANIFEST_NAME
    assert manifest["file_count"] == 2
    assert manifest["bytes"] == len(b"duckdbparquet")
    assert [entry["path"] for entry in manifest["files"]] == [
        "nba.duckdb",
        "parquet/dim_player/part-0.parquet",
    ]


def test_verify_rejects_tampered_artifact(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    (tmp_path / "nba.duckdb").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="contents do not match"):
        verify_assured_artifact_manifest(tmp_path)


def test_verify_rejects_expected_identity_mismatch(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )

    with pytest.raises(ValueError, match="source_sha mismatch"):
        verify_assured_artifact_manifest(tmp_path, expected_source_sha="c" * 40)


def test_metadata_created_after_manifest_is_not_part_of_data_identity(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    (tmp_path / "dataset-metadata.json").write_text("{}\n", encoding="utf-8")

    manifest = verify_assured_artifact_manifest(tmp_path)

    assert all(entry["path"] != "dataset-metadata.json" for entry in manifest["files"])


def test_verify_rejects_manifest_with_inconsistent_tree_fingerprint(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["data_tree_fingerprint"] = "d" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="tree fingerprint is inconsistent"):
        verify_assured_artifact_manifest(tmp_path)


def test_verify_rejects_detached_manifest_path(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    canonical = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    detached = tmp_path.parent / "detached-assured-artifact-manifest.json"
    detached.write_bytes(canonical.read_bytes())

    with pytest.raises(ValueError, match="canonical path"):
        verify_assured_artifact_manifest(tmp_path, manifest_path=detached)


def test_verify_rejects_boolean_schema_version(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = True
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported schema"):
        verify_assured_artifact_manifest(tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("file_count", True, "file count"),
        ("file_count", 1.0, "file count"),
        ("bytes", True, "byte count"),
        ("bytes", 1.0, "byte count"),
    ],
)
def test_verify_rejects_noninteger_aggregate_fields(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    (tmp_path / "one-byte.bin").write_bytes(b"x")
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload[field] = value
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        verify_assured_artifact_manifest(tmp_path)


def test_build_atomically_replaces_raced_manifest_symlink_without_following_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_artifact(tmp_path)
    victim = tmp_path.parent / "victim.txt"
    victim.write_text("do not overwrite\n", encoding="utf-8")
    manifest_path = tmp_path / ASSURED_ARTIFACT_MANIFEST_NAME
    original_inventory = artifact_identity._inventory_from_root_descriptor

    def inventory_then_swap(root_descriptor: int) -> list[dict[str, object]]:
        inventory = original_inventory(root_descriptor)
        manifest_path.symlink_to(victim)
        return inventory

    monkeypatch.setattr(
        artifact_identity,
        "_inventory_from_root_descriptor",
        inventory_then_swap,
    )

    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )

    assert victim.read_text(encoding="utf-8") == "do not overwrite\n"
    assert manifest_path.is_file()
    assert not manifest_path.is_symlink()


def test_verify_rejects_manifest_symlink_without_following_it(tmp_path: Path) -> None:
    _write_artifact(tmp_path)
    manifest_path = build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    detached = tmp_path.parent / "valid-detached-manifest.json"
    detached.write_bytes(manifest_path.read_bytes())
    manifest_path.unlink()
    manifest_path.symlink_to(detached)

    with pytest.raises(ValueError, match="symlinks"):
        verify_assured_artifact_manifest(tmp_path)


def test_inventory_rejects_nested_directory_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    (outside / "outside.bin").write_bytes(b"outside")
    (tmp_path / "inside.bin").write_bytes(b"inside")
    (tmp_path / "nested").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinks"):
        build_assured_artifact_manifest(
            tmp_path,
            chain_id="full-20260711",
            source_sha=_SOURCE_SHA,
            coverage_fingerprint=_COVERAGE_FINGERPRINT,
        )


def test_nested_inventory_is_globally_sorted_before_manifest_creation(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "child.bin").write_bytes(b"child")
    (tmp_path / "a.txt").write_bytes(b"sibling")

    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )
    manifest = verify_assured_artifact_manifest(tmp_path)

    assert [entry["path"] for entry in manifest["files"]] == ["a.txt", "a/child.bin"]


def test_verify_cli_prints_bounded_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_artifact(tmp_path)
    build_assured_artifact_manifest(
        tmp_path,
        chain_id="full-20260711",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=_COVERAGE_FINGERPRINT,
    )

    assert (
        main(
            [
                "verify",
                "--root",
                str(tmp_path),
                "--chain-id",
                "full-20260711",
                "--source-sha",
                _SOURCE_SHA,
                "--coverage-fingerprint",
                _COVERAGE_FINGERPRINT,
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "verified"
    assert output["file_count"] == 2
    assert "files" not in output
