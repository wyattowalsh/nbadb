"""Load the accepted current-source authority from authenticated package resources."""

from __future__ import annotations

import ast
import hashlib
from importlib import resources

from nbadb.contracts.implicit_competition_source_authority import (
    SOURCE_PATHS,
    ImplicitCompetitionCurrentSourceAuthorityV1,
    ImplicitCompetitionSourceAuthorityError,
)
from nbadb.contracts.implicit_competition_source_authority_pin import (
    IMPLICIT_COMPETITION_SOURCE_AUTHORITY_CURRENT_BINDING_COUNT,
    IMPLICIT_COMPETITION_SOURCE_AUTHORITY_PROVENANCE_BINDING_COUNT,
    IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RAW_SHA256,
    IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RESOURCE,
    IMPLICIT_COMPETITION_SOURCE_AUTHORITY_SEMANTIC_SHA256,
)

_SOURCE_PREFIX = "src/nbadb/"


class ImplicitCompetitionSourceAuthorityLoadError(ValueError):
    """The packaged implicit-competition source authority cannot be authenticated."""


def _fail(message: str) -> None:
    raise ImplicitCompetitionSourceAuthorityLoadError(message)


def _source_semantic_sha256(raw: bytes, *, path: str) -> str:
    """Apply the authority generator's exact Python AST semantic projection."""

    try:
        tree = ast.parse(raw, filename=path)
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise ImplicitCompetitionSourceAuthorityLoadError(
            f"packaged current source is not valid Python: {path}"
        ) from exc
    return hashlib.sha256(
        ast.dump(tree, annotate_fields=True, include_attributes=False).encode("utf-8")
    ).hexdigest()


def _read_packaged_authority() -> bytes:
    try:
        return (
            resources.files("nbadb.contracts")
            .joinpath(IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RESOURCE)
            .read_bytes()
        )
    except (AttributeError, OSError, TypeError) as exc:
        raise ImplicitCompetitionSourceAuthorityLoadError(
            "packaged implicit-competition source authority cannot be read"
        ) from exc


def _read_packaged_source(path: str) -> bytes:
    if not path.startswith(_SOURCE_PREFIX):
        _fail("current source binding is outside the packaged nbadb source root")
    relative = path.removeprefix(_SOURCE_PREFIX)
    parts = tuple(relative.split("/"))
    if not parts or any(not part or part in {".", ".."} for part in parts):
        _fail("current source binding has an unsafe package-relative path")
    try:
        return resources.files("nbadb").joinpath(*parts).read_bytes()
    except (AttributeError, OSError, TypeError) as exc:
        raise ImplicitCompetitionSourceAuthorityLoadError(
            f"packaged current source cannot be read: {path}"
        ) from exc


def _authenticate_current_sources(
    authority: ImplicitCompetitionCurrentSourceAuthorityV1,
) -> None:
    bindings = authority.candidate.source_bindings
    frozen_bindings = authority.candidate.frozen_bindings
    if (
        len(bindings) != IMPLICIT_COMPETITION_SOURCE_AUTHORITY_CURRENT_BINDING_COUNT
        or tuple(binding.path for binding in bindings) != SOURCE_PATHS
        or len(bindings) + len(frozen_bindings)
        != IMPLICIT_COMPETITION_SOURCE_AUTHORITY_PROVENANCE_BINDING_COUNT
    ):
        _fail("packaged current-source authority binding inventory drifted")

    for binding in bindings:
        raw = _read_packaged_source(binding.path)
        if len(raw) != binding.byte_count or hashlib.sha256(raw).hexdigest() != binding.sha256:
            _fail(f"packaged current source byte identity drifted: {binding.path}")
        if _source_semantic_sha256(raw, path=binding.path) != binding.semantic_sha256:
            _fail(f"packaged current source semantic identity drifted: {binding.path}")


def load_implicit_competition_current_source_authority() -> (
    ImplicitCompetitionCurrentSourceAuthorityV1
):
    """Return a fresh authority authenticated against this installed package."""

    raw = _read_packaged_authority()
    if hashlib.sha256(raw).hexdigest() != IMPLICIT_COMPETITION_SOURCE_AUTHORITY_RAW_SHA256:
        _fail("packaged implicit-competition source authority raw SHA-256 drifted")
    try:
        authority = ImplicitCompetitionCurrentSourceAuthorityV1.from_canonical_bytes(raw)
    except ImplicitCompetitionSourceAuthorityError as exc:
        raise ImplicitCompetitionSourceAuthorityLoadError(
            "packaged implicit-competition source authority is invalid"
        ) from exc
    if authority.authority_sha256 != IMPLICIT_COMPETITION_SOURCE_AUTHORITY_SEMANTIC_SHA256:
        _fail("packaged implicit-competition source authority semantic SHA-256 drifted")
    _authenticate_current_sources(authority)
    return authority


__all__ = [
    "ImplicitCompetitionSourceAuthorityLoadError",
    "load_implicit_competition_current_source_authority",
]
