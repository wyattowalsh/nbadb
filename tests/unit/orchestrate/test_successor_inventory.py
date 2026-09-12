from __future__ import annotations

import hashlib
import os
import stat
from typing import TYPE_CHECKING, cast

import pytest

import nbadb.orchestrate.successor_inventory as inventory_module
from nbadb.core.artifact_identity import inventory_regular_tree
from nbadb.orchestrate.successor_inventory import (
    InstalledPublicTreeInventory,
    measure_installed_public_tree,
)

if TYPE_CHECKING:
    from pathlib import Path

_SHA = "a" * 64


def test_installed_public_tree_uses_exact_descriptor_inventory_domain(tmp_path: Path) -> None:
    public = tmp_path / "public"
    (public / "csv").mkdir(parents=True)
    (public / "parquet" / "empty-partition").mkdir(parents=True)
    (public / "nba.duckdb").write_bytes(b"duckdb")
    (public / "csv" / "dim_team.csv").write_bytes(b"team_id\n1\n")

    measurement = measure_installed_public_tree(public)
    inventory = inventory_regular_tree(public)

    assert measurement.to_inventory() == inventory
    assert measurement.directories == ("csv", "parquet", "parquet/empty-partition")
    assert measurement.file_count == 2
    assert measurement.directory_count == 3
    assert measurement.byte_count == 16
    assert measurement.to_digest_payload() == {
        "digest_domain": "nbadb.installed-public-tree.v2",
        "directories": [
            {"path": "csv"},
            {"path": "parquet"},
            {"path": "parquet/empty-partition"},
        ],
        "files": inventory,
    }

    without_empty_topology = tmp_path / "without-empty-topology"
    (without_empty_topology / "csv").mkdir(parents=True)
    (without_empty_topology / "nba.duckdb").write_bytes(b"duckdb")
    (without_empty_topology / "csv" / "dim_team.csv").write_bytes(b"team_id\n1\n")
    assert inventory_regular_tree(without_empty_topology) == inventory
    assert (
        measure_installed_public_tree(without_empty_topology).installed_public_tree_sha256
        != measurement.installed_public_tree_sha256
    )


def test_installed_public_tree_accepts_exact_expected_root_identity(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    (public / "data.bin").write_bytes(b"exact")
    observed = public.stat()

    measurement = measure_installed_public_tree(
        public,
        expected_root_identity=(observed.st_dev, observed.st_ino),
    )

    assert measurement.file_count == 1
    assert measurement.to_inventory()[0]["path"] == "data.bin"


@pytest.mark.parametrize("invalid_identity", [True, 1.5, [1, 2], (-1, 2)])
def test_installed_public_tree_rejects_invalid_expected_root_identity(
    tmp_path: Path,
    invalid_identity: object,
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    (public / "data.bin").write_bytes(b"exact")

    with pytest.raises(ValueError, match="expected root identity is invalid"):
        measure_installed_public_tree(
            public,
            expected_root_identity=cast("tuple[int, int]", invalid_identity),
        )


def test_installed_public_tree_rejects_foreign_root_before_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    (public / "data.bin").write_bytes(b"exact")
    observed = public.stat()

    def unexpected_inventory(*args: object, **kwargs: object) -> object:
        raise AssertionError("inventory must not run for foreign root authority")

    monkeypatch.setattr(
        inventory_module,
        "_inventory_directory_descriptor",
        unexpected_inventory,
    )

    with pytest.raises(ValueError, match="root differs from expected authority"):
        measure_installed_public_tree(
            public,
            expected_root_identity=(observed.st_dev, observed.st_ino + 1),
        )


def test_installed_public_tree_rejects_nested_directory_mutation_during_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    nested = public / "csv" / "teams"
    nested.mkdir(parents=True)
    (nested / "part.csv").write_bytes(b"team_id\n1\n")
    original_fstat = inventory_module.os.fstat
    nested_identity = (nested.stat().st_dev, nested.stat().st_ino)
    nested_observations = 0

    def mutating_fstat(descriptor: int) -> os.stat_result:
        nonlocal nested_observations
        observed = original_fstat(descriptor)
        if stat.S_ISDIR(observed.st_mode) and (observed.st_dev, observed.st_ino) == nested_identity:
            nested_observations += 1
            if nested_observations == 2:
                (nested / "injected").write_bytes(b"late")
                observed = original_fstat(descriptor)
        return observed

    monkeypatch.setattr(inventory_module.os, "fstat", mutating_fstat)

    with pytest.raises(ValueError, match="directory changed while inventorying: csv/teams"):
        measure_installed_public_tree(public)


def test_installed_public_tree_rejects_regular_file_mutation_after_first_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    first = public / "a.bin"
    first.write_bytes(b"before")
    (public / "b.bin").write_bytes(b"stable")
    original_inventory = inventory_module._inventory_directory_descriptor
    mutated = False

    def mutate_after_first_pass(*args: object, **kwargs: object) -> object:
        nonlocal mutated
        result = original_inventory(*args, **kwargs)
        if not mutated:
            mutated = True
            first.write_bytes(b"after!!")
        return result

    monkeypatch.setattr(
        inventory_module,
        "_inventory_directory_descriptor",
        mutate_after_first_pass,
    )

    with pytest.raises(ValueError, match="file changed before final reproof: a.bin"):
        measure_installed_public_tree(public)

    assert mutated is True


def test_installed_public_tree_rejects_empty_symlink_and_special_file_roots(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="must not be empty"):
        measure_installed_public_tree(empty)

    real = tmp_path / "real"
    real.mkdir()
    (real / "data").write_bytes(b"bytes")
    symlink = tmp_path / "symlink"
    symlink.symlink_to(real, target_is_directory=True)
    with pytest.raises(NotADirectoryError, match="regular directory"):
        measure_installed_public_tree(symlink)

    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        with pytest.raises(NotADirectoryError, match="regular directory"):
            measure_installed_public_tree(fifo)


def test_installed_public_tree_digest_rejects_foreign_domains(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    (public / "nba.duckdb").write_bytes(b"duckdb")
    measurement = measure_installed_public_tree(public)
    payload = measurement.to_digest_payload()

    assert payload["digest_domain"] == "nbadb.installed-public-tree.v2"
    foreign_payloads = (
        {**payload, "digest_domain": "nbadb.remote-bundle.v1"},
        {**payload, "digest_domain": "nbadb.publication-resource.v1"},
        {**payload, "digest_domain": "nbadb.assurance-bound.v1"},
        {key: value for key, value in payload.items() if key != "digest_domain"},
    )
    for foreign in foreign_payloads:
        digest = hashlib.sha256(inventory_module._canonical_json_bytes(foreign)).hexdigest()
        assert digest != measurement.installed_public_tree_sha256


@pytest.mark.parametrize(
    ("files", "directories", "match"),
    [
        ((), (), "must not be empty"),
        ((("b.bin", 1, _SHA), ("a.bin", 1, _SHA)), (), "file inventory must be path-sorted"),
        (
            (("csv/a.bin", 1, _SHA), ("z/b.bin", 1, _SHA)),
            ("z", "csv"),
            "directory inventory must be path-sorted",
        ),
        ((("a.bin", 1, _SHA), ("a.bin", 2, "b" * 64)), (), "duplicate paths"),
        ((("csv/teams/a.bin", 1, _SHA),), ("csv/teams",), "missing parent"),
        ((("csv/a.bin", 1, _SHA),), (), "missing parent"),
        ((("csv", 1, _SHA),), ("csv",), "both a file and a directory"),
        ((("../escape", 1, _SHA),), (), "unsafe"),
        ((("nba.duckdb", 1, "A" * 64),), (), "SHA-256 is invalid"),
        ((("nba.duckdb", -1, _SHA),), (), "byte count is invalid"),
    ],
)
def test_installed_public_tree_inventory_rejects_invalid_topology(
    files: tuple[tuple[str, int, str], ...],
    directories: tuple[str, ...],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        InstalledPublicTreeInventory(files=files, directories=directories)


def test_installed_public_tree_rejects_nested_symlink_and_special_file(
    tmp_path: Path,
) -> None:
    public = tmp_path / "public"
    (public / "csv").mkdir(parents=True)
    (public / "nba.duckdb").write_bytes(b"duckdb")
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    (public / "csv" / "escape").symlink_to(outside)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        measure_installed_public_tree(public)

    (public / "csv" / "escape").unlink()
    if hasattr(os, "mkfifo"):
        os.mkfifo(public / "csv" / "blocked")
        with pytest.raises(ValueError, match="non-regular entry"):
            measure_installed_public_tree(public)


def test_installed_public_tree_rejects_directory_change_after_complete_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    empty = public / "csv" / "empty"
    empty.mkdir(parents=True)
    (public / "nba.duckdb").write_bytes(b"duckdb")
    original_verify_files = inventory_module._verify_regular_file_observations

    def inject_after_complete_scan(*args: object, **kwargs: object) -> None:
        original_verify_files(*args, **kwargs)
        (empty / "late").mkdir()

    monkeypatch.setattr(
        inventory_module,
        "_verify_regular_file_observations",
        inject_after_complete_scan,
    )

    with pytest.raises(ValueError, match="directory changed after inventory: csv/empty"):
        measure_installed_public_tree(public)


def test_installed_public_tree_rejects_root_change_after_complete_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    (public / "nba.duckdb").write_bytes(b"duckdb")
    original_verify_files = inventory_module._verify_regular_file_observations

    def inject_after_complete_scan(*args: object, **kwargs: object) -> None:
        original_verify_files(*args, **kwargs)
        (public / "injected-empty").mkdir()

    monkeypatch.setattr(
        inventory_module,
        "_verify_regular_file_observations",
        inject_after_complete_scan,
    )

    with pytest.raises(ValueError, match="directory changed after inventory: \\."):
        measure_installed_public_tree(public)
