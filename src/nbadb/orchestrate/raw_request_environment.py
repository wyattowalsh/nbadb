"""Fail-closed GitHub Actions admission for public raw-request capture."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nbadb.orchestrate.raw_request_assurance import RawRequestAssuranceAuthorityV2
    from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1

_AUTHORITY_OPT_IN_ENV = "NBADB_ENABLE_RAW_REQUEST_AUTHORITY"
_ASSURANCE_GENERATION_ENV = "NBADB_RAW_REQUEST_ASSURANCE_GENERATION"
_UPSTREAM_ROOT_ENV = "ENDPOINT_ANALYSIS_DOCS_ROOT"
_TRUE_VALUES = frozenset({"1", "true"})
_FALSE_VALUES = frozenset({"0", "false"})
_EXECUTION_ENV_NAMES = (
    "WORKFLOW_SOURCE_SHA",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "ACTIVE_CHAIN_ID",
    "LANE_ID",
)


class RawRequestExecutionEnvironmentError(ValueError):
    """Raised when an opted-in Actions execution identity is not exact."""


def raw_request_execution_identity_from_env(
    environ: Mapping[str, str] | None = None,
) -> RawRequestExecutionIdentityV1 | None:
    """Build one public execution identity from exact Actions provenance."""

    source = os.environ if environ is None else environ
    opt_in = source.get(_AUTHORITY_OPT_IN_ENV)
    if opt_in is None or opt_in in _FALSE_VALUES:
        return None
    if opt_in not in _TRUE_VALUES:
        raise RawRequestExecutionEnvironmentError(
            "raw-request authority opt-in must be an exact boolean lexical value"
        )
    if source.get("GITHUB_ACTIONS") != "true":
        raise RawRequestExecutionEnvironmentError(
            "raw-request authority requires an exact GitHub Actions execution"
        )
    raw_values = tuple(source.get(name) for name in _EXECUTION_ENV_NAMES)
    if any(type(value) is not str or not value for value in raw_values):
        raise RawRequestExecutionEnvironmentError(
            "raw-request authority execution provenance is incomplete"
        )
    source_sha, run_id_raw, run_attempt_raw, chain_id, lane_id = cast(
        "tuple[str, str, str, str, str]",
        raw_values,
    )
    if not run_id_raw.isascii() or not run_id_raw.isdecimal() or run_id_raw.startswith("0"):
        raise RawRequestExecutionEnvironmentError(
            "raw-request authority run ID must be a canonical positive integer"
        )
    if (
        not run_attempt_raw.isascii()
        or not run_attempt_raw.isdecimal()
        or run_attempt_raw.startswith("0")
    ):
        raise RawRequestExecutionEnvironmentError(
            "raw-request authority run attempt must be a canonical positive integer"
        )

    from nbadb.orchestrate.raw_request_context import (
        RawRequestContextCompilationError,
        RawRequestExecutionIdentityV1,
    )

    try:
        return RawRequestExecutionIdentityV1(
            source_sha=source_sha,
            run_id=int(run_id_raw),
            run_attempt=int(run_attempt_raw),
            chain_id=chain_id,
            lane_id=lane_id,
        )
    except RawRequestContextCompilationError as exc:
        raise RawRequestExecutionEnvironmentError(
            "raw-request authority execution provenance is invalid"
        ) from exc


def raw_request_assurance_authority_from_env(
    execution_identity: RawRequestExecutionIdentityV1 | None,
    environ: Mapping[str, str] | None = None,
    *,
    project_root: Path | None = None,
) -> RawRequestAssuranceAuthorityV2 | None:
    """Revalidate field/model authority from the exact downloaded generation."""

    if execution_identity is None:
        return None
    source = os.environ if environ is None else environ
    generation_raw = source.get(_ASSURANCE_GENERATION_ENV)
    upstream_raw = source.get(_UPSTREAM_ROOT_ENV)
    if (
        type(generation_raw) is not str
        or not generation_raw
        or type(upstream_raw) is not str
        or not upstream_raw
    ):
        raise RawRequestExecutionEnvironmentError(
            "raw-request authority assurance provenance is incomplete"
        )
    generation_path = Path(generation_raw)
    upstream_path = Path(upstream_raw)
    if (
        not generation_path.is_absolute()
        or not upstream_path.is_absolute()
        or generation_path.is_symlink()
        or upstream_path.is_symlink()
        or not generation_path.is_dir()
        or not upstream_path.is_dir()
    ):
        raise RawRequestExecutionEnvironmentError(
            "raw-request authority assurance roots are invalid"
        )

    from nbadb.orchestrate.raw_request_assurance import (
        RawRequestAssuranceError,
        load_raw_request_assurance_authority,
    )

    try:
        authority = load_raw_request_assurance_authority(
            generation_path,
            project_root=project_root or Path.cwd(),
            endpoint_analysis_docs_root=upstream_path,
        )
    except RawRequestAssuranceError as exc:
        raise RawRequestExecutionEnvironmentError(
            "raw-request authority assurance generation is invalid"
        ) from exc
    if authority.source_sha != execution_identity.source_sha:
        raise RawRequestExecutionEnvironmentError(
            "raw-request authority assurance source differs from execution"
        )
    return authority


__all__ = [
    "RawRequestExecutionEnvironmentError",
    "raw_request_assurance_authority_from_env",
    "raw_request_execution_identity_from_env",
]
