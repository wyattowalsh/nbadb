from __future__ import annotations

import shutil
from collections import Counter
from dataclasses import replace
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

from nbadb.core import nba_api_request_surface_verifier as verifier
from nbadb.core.nba_api_surface_inventory import (
    NBA_API_RECORD_AUTHORITY_SHA256,
    NBA_API_RECORD_ENTRIES_SHA256,
    NBA_API_RECORD_ENTRY_COUNT,
    NBA_API_RECORD_HASHED_ENTRY_COUNT,
    NbaApiSurfaceInventoryError,
    build_distribution_record_authority,
    build_nba_api_surface_inventory,
)


class _CopiedDistribution:
    def __init__(self, root: Path, source: metadata.Distribution) -> None:
        self._root = root
        self.version = source.version
        self.files = source.files

    def locate_file(self, path: Any) -> Path:
        return self._root / str(path)


def _copy_distribution(tmp_path: Path) -> _CopiedDistribution:
    installed = metadata.distribution("nba-api")
    assert installed.files is not None
    for package_path in installed.files:
        source = Path(str(installed.locate_file(package_path)))
        destination = tmp_path / str(package_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return _CopiedDistribution(tmp_path, installed)


def test_complete_record_and_source_atom_inventory_is_exact_and_deterministic() -> None:
    record = build_distribution_record_authority()
    first = build_nba_api_surface_inventory()
    verifier._authority.cache_clear()
    second = build_nba_api_surface_inventory()

    assert record.entry_count == NBA_API_RECORD_ENTRY_COUNT == 195
    assert record.hashed_entry_count == NBA_API_RECORD_HASHED_ENTRY_COUNT == 194
    assert record.entries_sha256 == NBA_API_RECORD_ENTRIES_SHA256
    assert record.authority_sha256 == NBA_API_RECORD_AUTHORITY_SHA256
    assert first == second
    assert first["source_atom_count"] == 12072
    source_atoms = first["source_atoms"]
    assert isinstance(source_atoms, list)
    dynamic_defaults = [
        atom
        for atom in source_atoms
        if isinstance(atom, dict)
        and atom.get("default_authority") == "provider_dynamic_default_expression_v1"
    ]
    assert len(dynamic_defaults) == 90
    assert Counter(atom.get("default_expression") for atom in dynamic_defaults) == {
        "GameDate.default": 2,
        "Season.default": 77,
        "SeasonAll.default": 1,
        "SeasonAll_Time.default": 1,
        "SeasonID.default": 2,
        "SeasonYear.default": 7,
    }
    assert (
        first["independent_package_inventory"]["independently_derived_extended_header_count"] == 47
    )
    assert first["reserved_authorities"] == {
        "league_finite_values": "pending_A1.2a",
        "release_terminal_state": "pending_A1.3a",
    }


def test_inventory_rejects_record_file_or_hash_drift(tmp_path: Path) -> None:
    copied = _copy_distribution(tmp_path)
    target = tmp_path / "nba_api/__init__.py"
    target.write_bytes(target.read_bytes() + b"# count-preserving authority drift\n")

    with pytest.raises(
        NbaApiSurfaceInventoryError,
        match="RECORD file or hash differs",
    ):
        build_distribution_record_authority(copied)  # type: ignore[arg-type]


def test_count_preserving_surface_atom_replacement_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = verifier.build_request_surface_authority
    authority = original()
    endpoint = authority.endpoints[0]
    drifted_endpoint = replace(endpoint, endpoint_slug="count_preserving_replacement")
    drifted = replace(authority, endpoints=(drifted_endpoint, *authority.endpoints[1:]))
    monkeypatch.setattr(verifier, "build_request_surface_authority", lambda: drifted)
    verifier._authority.cache_clear()

    with pytest.raises(
        verifier.NbaApiRequestSurfaceError,
        match="rebuilt exact authority",
    ):
        verifier.build_independent_package_inventory()
