"""Tests for the packaged implicit-competition current-source authority loader."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError
from importlib import resources
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nbadb.contracts import implicit_competition_source_authority_loader as subject
from nbadb.contracts.implicit_competition_source_authority import SOURCE_PATHS
from nbadb.contracts.implicit_competition_source_authority_loader import (
    ImplicitCompetitionSourceAuthorityLoadError,
    load_implicit_competition_current_source_authority,
)
from nbadb.contracts.implicit_competition_source_authority_pin import (
    IMPLICIT_COMPETITION_SOURCE_AUTHORITY_CURRENT_BINDING_COUNT,
    IMPLICIT_COMPETITION_SOURCE_AUTHORITY_PROVENANCE_BINDING_COUNT,
    IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RAW_SHA256,
    IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RESOURCE,
    IMPLICIT_COMPETITION_SOURCE_AUTHORITY_SEMANTIC_SHA256,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest import MonkeyPatch


class _BytesResource:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def read_bytes(self) -> bytes:
        return self._raw


class _ResourceRoot:
    def __init__(
        self,
        base: object,
        *,
        package: str,
        replacements: dict[tuple[str, tuple[str, ...]], bytes],
        accesses: list[tuple[str, tuple[str, ...]]],
    ) -> None:
        self._base = base
        self._package = package
        self._replacements = replacements
        self._accesses = accesses

    def joinpath(self, *parts: str):
        normalized = tuple(parts)
        self._accesses.append((self._package, normalized))
        replacement = self._replacements.get((self._package, normalized))
        if replacement is not None:
            return _BytesResource(replacement)
        return self._base.joinpath(*parts)


def _patch_resources(
    monkeypatch: MonkeyPatch,
    *,
    replacements: dict[tuple[str, tuple[str, ...]], bytes] | None = None,
) -> list[tuple[str, tuple[str, ...]]]:
    real_files = subject.resources.files
    accesses: list[tuple[str, tuple[str, ...]]] = []
    replacement_map = replacements or {}

    def wrapped_files(package: str):
        return _ResourceRoot(
            real_files(package),
            package=package,
            replacements=replacement_map,
            accesses=accesses,
        )

    monkeypatch.setattr(subject.resources, "files", wrapped_files)
    return accesses


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            *(str(key) for key in value),
            *(nested for item in value.values() for nested in _walk_keys(item)),
        }
    if isinstance(value, list):
        return {nested for item in value for nested in _walk_keys(item)}
    return set()


def test_loader_pins_exact_canonical_resource_and_returns_fresh_objects(
    monkeypatch: MonkeyPatch,
) -> None:
    raw = (
        resources.files("nbadb.contracts")
        .joinpath(IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RESOURCE)
        .read_bytes()
    )
    accesses = _patch_resources(monkeypatch)

    first = load_implicit_competition_current_source_authority()
    second = load_implicit_competition_current_source_authority()

    assert inspect.signature(load_implicit_competition_current_source_authority).parameters == {}
    assert len(raw) == 10_022
    assert raw[-1:] == b"}"
    assert not raw.endswith(b"\n")
    assert hashlib.sha256(raw).hexdigest() == IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RAW_SHA256
    assert first.canonical_bytes == raw
    assert first.authority_sha256 == IMPLICIT_COMPETITION_SOURCE_AUTHORITY_SEMANTIC_SHA256
    assert first == second
    assert first is not second
    assert first.generation_proof is not second.generation_proof
    assert first.candidate is not second.candidate
    assert first.review is not second.review
    assert first.candidate.source_bindings[0] is not second.candidate.source_bindings[0]
    assert tuple(binding.path for binding in first.candidate.source_bindings) == SOURCE_PATHS
    assert len(first.candidate.source_bindings) == (
        IMPLICIT_COMPETITION_SOURCE_AUTHORITY_CURRENT_BINDING_COUNT
    )
    assert len(first.candidate.source_bindings) + len(first.candidate.frozen_bindings) == (
        IMPLICIT_COMPETITION_SOURCE_AUTHORITY_PROVENANCE_BINDING_COUNT
    )
    assert "source_sha" not in _walk_keys(json.loads(raw))

    expected_accesses = [
        ("nbadb.contracts", (IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RESOURCE,)),
        *[("nbadb", tuple(path.removeprefix("src/nbadb/").split("/"))) for path in SOURCE_PATHS],
    ]
    assert accesses == expected_accesses * 2

    with pytest.raises(FrozenInstanceError):
        first.authority_sha256 = "0" * 64  # type: ignore[misc]


def test_loader_rejects_packaged_authority_tamper_before_parse(
    monkeypatch: MonkeyPatch,
) -> None:
    raw = (
        resources.files("nbadb.contracts")
        .joinpath(IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RESOURCE)
        .read_bytes()
    )
    _patch_resources(
        monkeypatch,
        replacements={
            (
                "nbadb.contracts",
                (IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RESOURCE,),
            ): raw + b"\n"
        },
    )
    parser = MagicMock(side_effect=AssertionError("parser must not see unauthenticated bytes"))
    monkeypatch.setattr(
        subject.ImplicitCompetitionCurrentSourceAuthorityV1,
        "from_canonical_bytes",
        parser,
    )

    with pytest.raises(ImplicitCompetitionSourceAuthorityLoadError, match="raw SHA-256"):
        load_implicit_competition_current_source_authority()

    parser.assert_not_called()


def test_loader_rejects_current_source_byte_drift(monkeypatch: MonkeyPatch) -> None:
    source_path = SOURCE_PATHS[0]
    source_parts = tuple(source_path.removeprefix("src/nbadb/").split("/"))
    source_raw = resources.files("nbadb").joinpath(*source_parts).read_bytes()
    _patch_resources(
        monkeypatch,
        replacements={
            ("nbadb", source_parts): source_raw + b"\n# packaged byte drift\n",
        },
    )

    with pytest.raises(ImplicitCompetitionSourceAuthorityLoadError, match="byte identity drifted"):
        load_implicit_competition_current_source_authority()


def test_loader_rejects_current_source_semantic_drift(monkeypatch: MonkeyPatch) -> None:
    source_path = SOURCE_PATHS[0]
    semantic_projector: Callable[..., str] = subject._source_semantic_sha256

    def drifted_semantic(raw: bytes, *, path: str) -> str:
        if path == source_path:
            return "0" * 64
        return semantic_projector(raw, path=path)

    monkeypatch.setattr(subject, "_source_semantic_sha256", drifted_semantic)

    with pytest.raises(
        ImplicitCompetitionSourceAuthorityLoadError,
        match="semantic identity drifted",
    ):
        load_implicit_competition_current_source_authority()
