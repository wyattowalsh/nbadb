"""Canonical schema-v7 terminal assurance for recurring successor updates.

The report produced here intentionally reuses ``terminal-assurance-report.json``.
It inventories every byte-bearing public data resource but represents the report
and assured manifest as control-resource contracts only.  That ordering avoids a
self-hash cycle: write this canonical report first, build the assured manifest over
the resulting tree second, then supply that manifest's digest when constructing the
final :class:`SuccessorAssuranceIdentity`.

No value object in this module contains a local filesystem path.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, ClassVar, Self, cast

from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.nba_api_provenance import normalize_nba_api_provider_authority
from nbadb.orchestrate.capture_session import PrivateGenerationIdentity
from nbadb.orchestrate.successor_planning_contract import (
    SuccessorPlanningEvidence,
    SuccessorPlanningPublicIdentity,
    finalize_successor_update_intent,
)
from nbadb.orchestrate.successor_update_contract import (
    BaselineAssuranceIdentity,
    DeltaDisposition,
    SuccessorAssuranceIdentity,
    SuccessorGenerationBuild,
    SuccessorGenerationState,
    SuccessorUpdateIntent,
    SuccessorUpdateTransaction,
    canonical_json_bytes,
    canonical_sha256,
)
from nbadb.orchestrate.w2_database_assurance import (
    W2DatabaseAuthorityError,
    W2DatabaseAuthorityReceiptV1,
)

__all__ = [
    "SUCCESSOR_ASSURANCE_MANIFEST_DIGEST_DOMAIN",
    "SUCCESSOR_ASSURANCE_MANIFEST_KIND",
    "SUCCESSOR_ASSURANCE_MANIFEST_SCHEMA_VERSION",
    "SUCCESSOR_TERMINAL_ASSURANCE_KIND",
    "SUCCESSOR_TERMINAL_ASSURANCE_SCHEMA_VERSION",
    "SuccessorAssuranceContractError",
    "SuccessorAssuranceManifest",
    "SuccessorDatabaseEvidence",
    "SuccessorDeltaCoverage",
    "SuccessorLogicalCallAuthority",
    "SuccessorPublicEvidence",
    "SuccessorPublicResourceAttestation",
    "SuccessorRouteReceiptAttestation",
    "SuccessorScanEvidence",
    "SuccessorTerminalAssuranceReportV7",
    "SuccessorTransformOutputAttestation",
    "emit_successor_assurance_manifest",
    "validate_successor_terminal_assurance_report",
    "verify_successor_assurance_manifest",
]

SUCCESSOR_TERMINAL_ASSURANCE_SCHEMA_VERSION = 7
SUCCESSOR_TERMINAL_ASSURANCE_KIND = "successor_terminal_assurance_report"
SUCCESSOR_ASSURANCE_MANIFEST_SCHEMA_VERSION = 7
SUCCESSOR_ASSURANCE_MANIFEST_KIND = "successor_assurance_manifest"
SUCCESSOR_ASSURANCE_MANIFEST_DIGEST_DOMAIN = "nbadb.successor-assurance-manifest.v7"
_CONTROL_RESOURCES = (
    "assured-artifact-manifest.json",
    "terminal-assurance-report.json",
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}")
_TABLE_RE = re.compile(r"[a-z][a-z0-9_]{0,127}")
_WINDOWS_ABSOLUTE_RE = re.compile(r"[A-Za-z]:[\\/]")
_W2_EXPECTED_CALL_INVENTORY_KIND = "successor_w2_expected_call_inventory"
_W2_EXPECTED_CALL_INVENTORY_SCHEMA_VERSION = 1


class SuccessorAssuranceContractError(ValueError):
    """Raised when successor terminal assurance is incomplete or inconsistent."""


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: set[str] | frozenset[str],
    *,
    label: str,
) -> None:
    actual = set(payload)
    if actual == set(expected):
        return
    missing = sorted(set(expected) - actual)
    unexpected = sorted(actual - set(expected))
    raise SuccessorAssuranceContractError(
        f"{label} fields are invalid: missing={missing}; unexpected={unexpected}"
    )


def _mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SuccessorAssuranceContractError(f"{field_name} must be an object")
    return cast("Mapping[str, object]", value)


def _list(value: object, *, field_name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise SuccessorAssuranceContractError(f"{field_name} must be a list")
    return value


def _sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise SuccessorAssuranceContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _source_sha(value: object, *, field_name: str = "source_sha") -> str:
    if not isinstance(value, str) or _SOURCE_SHA_RE.fullmatch(value) is None:
        raise SuccessorAssuranceContractError(
            f"{field_name} must be a 40-character lowercase commit SHA"
        )
    return value


def _safe_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN_RE.fullmatch(value) is None:
        raise SuccessorAssuranceContractError(f"{field_name} must be an exact safe token")
    return value


def _nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise SuccessorAssuranceContractError(f"{field_name} must be a nonnegative integer")
    return value


def _positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise SuccessorAssuranceContractError(f"{field_name} must be a positive integer")
    return value


def _canonical_copy(value: object) -> Any:
    return json.loads(canonical_json_bytes(value))


def _w2_expected_call_inventory_sha256(
    bindings: Sequence[Mapping[str, object]],
    *,
    w2_source_call_admission_inventory_sha256: str,
) -> str:
    """Join expected public calls to the database-derived admission inventory."""

    return canonical_sha256(
        {
            "schema_version": _W2_EXPECTED_CALL_INVENTORY_SCHEMA_VERSION,
            "kind": _W2_EXPECTED_CALL_INVENTORY_KIND,
            "calls": [_canonical_copy(binding) for binding in bindings],
            "w2_source_call_admission_inventory_sha256": _sha256(
                w2_source_call_admission_inventory_sha256,
                field_name="w2_source_call_admission_inventory_sha256",
            ),
        }
    )


def _replay_w2_database_authority(
    value: object,
    *,
    label: str,
) -> W2DatabaseAuthorityReceiptV1:
    if type(value) is not W2DatabaseAuthorityReceiptV1:
        raise SuccessorAssuranceContractError(f"{label} must be the exact typed W2 receipt")
    receipt = value
    try:
        replayed = W2DatabaseAuthorityReceiptV1.from_canonical_bytes(receipt.canonical_bytes())
    except W2DatabaseAuthorityError as exc:
        raise SuccessorAssuranceContractError(f"{label} failed exact canonical replay") from exc
    if replayed != receipt:
        raise SuccessorAssuranceContractError(f"{label} changed during exact canonical replay")
    return replayed


_PRIVATE_PLANNING_KEYS = frozenset(
    {
        "dispatches",
        "members",
        "parameters",
        "request",
        "requested_planning_scopes",
        "requested_route_scopes",
        "sealed_dispatches",
        "waves",
    }
)


def _reject_private_planning_bytes(value: object, *, field_name: str = "planning_evidence") -> None:
    """Reject private planning inventories and sealed-dispatch parameter bodies."""

    if isinstance(value, Mapping):
        leaked = sorted(key for key in value if key in _PRIVATE_PLANNING_KEYS)
        if leaked:
            raise SuccessorAssuranceContractError(
                f"{field_name} must carry only path-free planning identities; "
                f"private fields present: {', '.join(leaked)}"
            )
        for key, child in value.items():
            _reject_private_planning_bytes(child, field_name=f"{field_name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_private_planning_bytes(child, field_name=f"{field_name}[{index}]")


def _reject_absolute_paths(value: object, *, field_name: str = "report") -> None:
    """Reject local absolute-path material anywhere in a report payload."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            _reject_absolute_paths(child, field_name=f"{field_name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_absolute_paths(child, field_name=f"{field_name}[{index}]")
        return
    if not isinstance(value, str):
        return
    if value.startswith(("/", "\\", "file://")) or _WINDOWS_ABSOLUTE_RE.match(value) is not None:
        raise SuccessorAssuranceContractError(
            f"{field_name} must not contain an absolute filesystem path"
        )


def _resource_id(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SuccessorAssuranceContractError("public resource_id is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise SuccessorAssuranceContractError("public resource_id is invalid")
    return value


@dataclass(frozen=True, slots=True)
class SuccessorTransformOutputAttestation:
    """Deterministic identity of one schema-backed transform output."""

    table_name: str
    row_count: int
    schema_sha256: str
    content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.table_name, str) or _TABLE_RE.fullmatch(self.table_name) is None:
            raise SuccessorAssuranceContractError("transform table_name is invalid")
        _nonnegative_int(self.row_count, field_name="transform row_count")
        _sha256(self.schema_sha256, field_name="transform schema_sha256")
        _sha256(self.content_sha256, field_name="transform content_sha256")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "table_name": self.table_name,
            "row_count": self.row_count,
            "schema_sha256": self.schema_sha256,
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {"table_name", "row_count", "schema_sha256", "content_sha256"},
            label="transform output attestation",
        )
        table_name = payload["table_name"]
        if not isinstance(table_name, str):
            raise SuccessorAssuranceContractError("transform table_name is invalid")
        return cls(
            table_name=table_name,
            row_count=_nonnegative_int(payload["row_count"], field_name="transform row_count"),
            schema_sha256=_sha256(payload["schema_sha256"], field_name="transform schema_sha256"),
            content_sha256=_sha256(
                payload["content_sha256"], field_name="transform content_sha256"
            ),
        )


@dataclass(frozen=True, slots=True)
class SuccessorScanEvidence:
    """Digest-bound proof that the hard full-publication scan passed."""

    report_sha256: str
    status: str
    fail_on: str
    full_publication: bool
    error_count: int

    def __post_init__(self) -> None:
        _sha256(self.report_sha256, field_name="scan report_sha256")
        if self.status != "passed" or self.fail_on != "error":
            raise SuccessorAssuranceContractError(
                "successor scan must be a passed fail-on-error scan"
            )
        if self.full_publication is not True or self.error_count != 0:
            raise SuccessorAssuranceContractError(
                "successor scan must prove zero-error full-publication assurance"
            )

    def to_dict(self) -> dict[str, str | int | bool]:
        return {
            "report_sha256": self.report_sha256,
            "status": self.status,
            "fail_on": self.fail_on,
            "full_publication": self.full_publication,
            "error_count": self.error_count,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {"report_sha256", "status", "fail_on", "full_publication", "error_count"},
            label="scan evidence",
        )
        status = payload["status"]
        fail_on = payload["fail_on"]
        if not isinstance(status, str) or not isinstance(fail_on, str):
            raise SuccessorAssuranceContractError("scan status and fail_on must be strings")
        return cls(
            report_sha256=_sha256(payload["report_sha256"], field_name="scan report_sha256"),
            status=status,
            fail_on=fail_on,
            full_publication=payload["full_publication"] is True,
            error_count=_nonnegative_int(payload["error_count"], field_name="scan error_count"),
        )


@dataclass(frozen=True, slots=True)
class SuccessorDatabaseEvidence:
    """Exact candidate DuckDB and SQLite bytes without local paths."""

    duckdb_sha256: str
    duckdb_bytes: int
    sqlite_sha256: str
    sqlite_bytes: int

    def __post_init__(self) -> None:
        _sha256(self.duckdb_sha256, field_name="duckdb_sha256")
        _positive_int(self.duckdb_bytes, field_name="duckdb_bytes")
        _sha256(self.sqlite_sha256, field_name="sqlite_sha256")
        _positive_int(self.sqlite_bytes, field_name="sqlite_bytes")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "duckdb_sha256": self.duckdb_sha256,
            "duckdb_bytes": self.duckdb_bytes,
            "sqlite_sha256": self.sqlite_sha256,
            "sqlite_bytes": self.sqlite_bytes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {"duckdb_sha256", "duckdb_bytes", "sqlite_sha256", "sqlite_bytes"},
            label="database evidence",
        )
        return cls(
            duckdb_sha256=_sha256(payload["duckdb_sha256"], field_name="duckdb_sha256"),
            duckdb_bytes=_positive_int(payload["duckdb_bytes"], field_name="duckdb_bytes"),
            sqlite_sha256=_sha256(payload["sqlite_sha256"], field_name="sqlite_sha256"),
            sqlite_bytes=_positive_int(payload["sqlite_bytes"], field_name="sqlite_bytes"),
        )


@dataclass(frozen=True, slots=True)
class SuccessorPublicResourceAttestation:
    """One cycle-free public data resource identity."""

    resource_id: str
    kind: str
    bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _resource_id(self.resource_id)
        if self.kind not in {"file", "directory"}:
            raise SuccessorAssuranceContractError("public resource kind is invalid")
        _nonnegative_int(self.bytes, field_name="public resource bytes")
        _sha256(self.sha256, field_name="public resource sha256")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "resource_id": self.resource_id,
            "kind": self.kind,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {"resource_id", "kind", "bytes", "sha256"},
            label="public resource attestation",
        )
        kind = payload["kind"]
        if not isinstance(kind, str):
            raise SuccessorAssuranceContractError("public resource kind is invalid")
        return cls(
            resource_id=_resource_id(payload["resource_id"]),
            kind=kind,
            bytes=_nonnegative_int(payload["bytes"], field_name="public resource bytes"),
            sha256=_sha256(payload["sha256"], field_name="public resource sha256"),
        )


@dataclass(frozen=True, slots=True)
class SuccessorPublicEvidence:
    """Complete static publication contract plus any observed conditional route."""

    resources: tuple[SuccessorPublicResourceAttestation, ...]
    resource_count: int = field(init=False)
    data_resource_count: int = field(init=False)
    control_resources: tuple[str, ...] = field(init=False)
    publication_resource_inventory_sha256: str = field(init=False)
    successor_data_tree_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
        from nbadb.kaggle.metadata import expected_full_publication_resource_contract
        from nbadb.orchestrate.staging_map import LOSSLESS_FALLBACK_STAGING_KEY

        resources = tuple(self.resources)
        if any(not isinstance(item, SuccessorPublicResourceAttestation) for item in resources):
            raise SuccessorAssuranceContractError(
                "public resources must be SuccessorPublicResourceAttestation values"
            )
        ordered = tuple(sorted(resources, key=lambda item: item.resource_id))
        if ordered != resources:
            raise SuccessorAssuranceContractError("public resources must be sorted by resource_id")
        ids = [item.resource_id for item in resources]
        if len(ids) != len(set(ids)):
            raise SuccessorAssuranceContractError("public resources contain duplicate IDs")
        fallback_resource_ids = {
            f"csv/{LOSSLESS_FALLBACK_STAGING_KEY}.csv",
            (f"parquet/{LOSSLESS_FALLBACK_STAGING_KEY}/{LOSSLESS_FALLBACK_STAGING_KEY}.parquet"),
        }
        include_lossless_fallback = bool(set(ids) & fallback_resource_ids)
        live_lossless_resource_ids = {
            f"csv/{LIVE_LOSSLESS_STAGING_KEY}.csv",
            f"parquet/{LIVE_LOSSLESS_STAGING_KEY}/{LIVE_LOSSLESS_STAGING_KEY}.parquet",
        }
        include_live_lossless = bool(set(ids) & live_lossless_resource_ids)
        expected_contract = expected_full_publication_resource_contract(
            include_lossless_fallback=include_lossless_fallback,
            include_live_lossless=include_live_lossless,
        )
        if any(control not in expected_contract for control in _CONTROL_RESOURCES):
            raise SuccessorAssuranceContractError("public control-resource contract is incomplete")

        expected_data_contract = {
            resource_id: kind
            for resource_id, kind in expected_contract.items()
            if resource_id not in _CONTROL_RESOURCES
        }
        observed_data_contract = {item.resource_id: item.kind for item in resources}
        if observed_data_contract != expected_data_contract:
            missing = sorted(set(expected_data_contract) - set(observed_data_contract))
            unexpected = sorted(set(observed_data_contract) - set(expected_data_contract))
            wrong_kind = sorted(
                resource_id
                for resource_id in set(expected_data_contract) & set(observed_data_contract)
                if expected_data_contract[resource_id] != observed_data_contract[resource_id]
            )
            raise SuccessorAssuranceContractError(
                "public data resource inventory does not match conditional authority: "
                f"missing={missing}; unexpected={unexpected}; wrong_kind={wrong_kind}"
            )

        control_resources = tuple(sorted(_CONTROL_RESOURCES))
        contract_inventory = [
            {"resource_id": resource_id, "kind": expected_contract[resource_id]}
            for resource_id in sorted(expected_contract)
        ]
        data_inventory = [item.to_dict() for item in resources]
        publication_resource_inventory_sha256 = canonical_sha256(
            {
                "resource_contract": contract_inventory,
                "data_resources": data_inventory,
            }
        )
        data_tree_fingerprint = canonical_sha256(
            [
                {
                    "resource_id": item.resource_id,
                    "bytes": item.bytes,
                    "sha256": item.sha256,
                }
                for item in resources
            ]
        )
        object.__setattr__(self, "resource_count", len(expected_contract))
        object.__setattr__(self, "data_resource_count", len(resources))
        object.__setattr__(self, "control_resources", control_resources)
        object.__setattr__(
            self,
            "publication_resource_inventory_sha256",
            publication_resource_inventory_sha256,
        )
        object.__setattr__(
            self,
            "successor_data_tree_fingerprint",
            data_tree_fingerprint,
        )

    def resource(self, resource_id: str) -> SuccessorPublicResourceAttestation:
        matches = [item for item in self.resources if item.resource_id == resource_id]
        if len(matches) != 1:
            raise SuccessorAssuranceContractError(
                f"public resource inventory has no unique {resource_id}"
            )
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_count": self.resource_count,
            "data_resource_count": self.data_resource_count,
            "control_resources": list(self.control_resources),
            "resources": [item.to_dict() for item in self.resources],
            "publication_resource_inventory_sha256": (self.publication_resource_inventory_sha256),
            "successor_data_tree_fingerprint": self.successor_data_tree_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "resource_count",
                "data_resource_count",
                "control_resources",
                "resources",
                "publication_resource_inventory_sha256",
                "successor_data_tree_fingerprint",
            },
            label="public evidence",
        )
        raw_resources = _list(payload["resources"], field_name="public resources")
        result = cls(
            resources=tuple(
                SuccessorPublicResourceAttestation.from_dict(
                    _mapping(raw, field_name=f"public resources[{index}]")
                )
                for index, raw in enumerate(raw_resources)
            )
        )
        raw_controls = _list(payload["control_resources"], field_name="control_resources")
        if list(result.control_resources) != list(raw_controls):
            raise SuccessorAssuranceContractError("public control resources differ")
        comparisons = (
            ("resource_count", result.resource_count, payload["resource_count"]),
            ("data_resource_count", result.data_resource_count, payload["data_resource_count"]),
            (
                "publication_resource_inventory_sha256",
                result.publication_resource_inventory_sha256,
                payload["publication_resource_inventory_sha256"],
            ),
            (
                "successor_data_tree_fingerprint",
                result.successor_data_tree_fingerprint,
                payload["successor_data_tree_fingerprint"],
            ),
        )
        mismatches = [name for name, expected, actual in comparisons if expected != actual]
        if mismatches:
            raise SuccessorAssuranceContractError(
                "public evidence derived fields differ: " + ", ".join(mismatches)
            )
        return result


@dataclass(frozen=True, slots=True)
class SuccessorDeltaCoverage:
    """Disjoint changed/no-change/typed-zero closure over requested scopes."""

    changed_scope_sha256s: tuple[str, ...]
    no_change_scope_sha256s: tuple[str, ...]
    typed_zero_scope_sha256s: tuple[str, ...]
    requested_scope_count: int = field(init=False)
    changed_scope_count: int = field(init=False)
    no_change_scope_count: int = field(init=False)
    typed_zero_scope_count: int = field(init=False)
    coverage_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        inventories = (
            self.changed_scope_sha256s,
            self.no_change_scope_sha256s,
            self.typed_zero_scope_sha256s,
        )
        for inventory in inventories:
            if tuple(sorted(inventory)) != inventory or len(inventory) != len(set(inventory)):
                raise SuccessorAssuranceContractError(
                    "delta coverage inventories must be sorted and unique"
                )
            for digest in inventory:
                _sha256(digest, field_name="delta requested_scope_sha256")
        combined = [digest for inventory in inventories for digest in inventory]
        if len(combined) != len(set(combined)):
            raise SuccessorAssuranceContractError("delta coverage classifications must be disjoint")
        body = {
            "requested_scope_count": len(combined),
            "changed_scope_count": len(self.changed_scope_sha256s),
            "no_change_scope_count": len(self.no_change_scope_sha256s),
            "typed_zero_scope_count": len(self.typed_zero_scope_sha256s),
            "changed_scope_sha256s": list(self.changed_scope_sha256s),
            "no_change_scope_sha256s": list(self.no_change_scope_sha256s),
            "typed_zero_scope_sha256s": list(self.typed_zero_scope_sha256s),
        }
        object.__setattr__(self, "requested_scope_count", len(combined))
        object.__setattr__(self, "changed_scope_count", len(self.changed_scope_sha256s))
        object.__setattr__(self, "no_change_scope_count", len(self.no_change_scope_sha256s))
        object.__setattr__(self, "typed_zero_scope_count", len(self.typed_zero_scope_sha256s))
        object.__setattr__(self, "coverage_sha256", canonical_sha256(body))

    @classmethod
    def from_build(cls, build: SuccessorGenerationBuild) -> Self:
        changed: list[str] = []
        no_change: list[str] = []
        typed_zero: list[str] = []
        for receipt in build.observed_delta_receipts:
            if receipt.disposition is DeltaDisposition.TYPED_ZERO:
                typed_zero.append(receipt.requested_scope_sha256)
            elif (
                receipt.prior_persisted_content_sha256 is not None
                and receipt.prior_persisted_content_sha256 == receipt.persisted_content_sha256
            ):
                no_change.append(receipt.requested_scope_sha256)
            else:
                changed.append(receipt.requested_scope_sha256)
        return cls(
            changed_scope_sha256s=tuple(sorted(changed)),
            no_change_scope_sha256s=tuple(sorted(no_change)),
            typed_zero_scope_sha256s=tuple(sorted(typed_zero)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_scope_count": self.requested_scope_count,
            "changed_scope_count": self.changed_scope_count,
            "no_change_scope_count": self.no_change_scope_count,
            "typed_zero_scope_count": self.typed_zero_scope_count,
            "changed_scope_sha256s": list(self.changed_scope_sha256s),
            "no_change_scope_sha256s": list(self.no_change_scope_sha256s),
            "typed_zero_scope_sha256s": list(self.typed_zero_scope_sha256s),
            "coverage_sha256": self.coverage_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "requested_scope_count",
                "changed_scope_count",
                "no_change_scope_count",
                "typed_zero_scope_count",
                "changed_scope_sha256s",
                "no_change_scope_sha256s",
                "typed_zero_scope_sha256s",
                "coverage_sha256",
            },
            label="delta coverage",
        )

        def inventory(field_name: str) -> tuple[str, ...]:
            raw = _list(payload[field_name], field_name=field_name)
            return tuple(_sha256(item, field_name=field_name) for item in raw)

        result = cls(
            changed_scope_sha256s=inventory("changed_scope_sha256s"),
            no_change_scope_sha256s=inventory("no_change_scope_sha256s"),
            typed_zero_scope_sha256s=inventory("typed_zero_scope_sha256s"),
        )
        comparisons = (
            ("requested_scope_count", result.requested_scope_count),
            ("changed_scope_count", result.changed_scope_count),
            ("no_change_scope_count", result.no_change_scope_count),
            ("typed_zero_scope_count", result.typed_zero_scope_count),
            ("coverage_sha256", result.coverage_sha256),
        )
        mismatches = [name for name, expected in comparisons if payload[name] != expected]
        if mismatches:
            raise SuccessorAssuranceContractError(
                "delta coverage derived fields differ: " + ", ".join(mismatches)
            )
        return result


def _private_generation_from_dict(
    payload: Mapping[str, object],
    *,
    expected_logical_call_roots: tuple[str, ...],
    expected_logical_call_bindings_sha256: str,
) -> PrivateGenerationIdentity:
    expected = {
        "schema_version",
        "kind",
        "manifest_sha256",
        "provider_authority_sha256",
        "semantic_source_sha",
        "chain_id",
        "lane_id",
        "workflow_run_id",
        "workflow_run_attempt",
        "artifact_count",
        "done_call_count",
        "done_call_receipt_sha256s",
        "done_call_receipts_sha256",
        "done_call_bindings_sha256",
        "done_attempt_count",
        "done_blob_count",
        "orphan_call_count",
        "orphan_attempt_count",
        "orphan_blob_count",
        "stored_bytes",
    }
    _require_exact_keys(payload, expected, label="update private generation")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != PrivateGenerationIdentity.schema_version
        or payload["kind"] != PrivateGenerationIdentity.kind
    ):
        raise SuccessorAssuranceContractError("update private generation schema is invalid")
    raw_roots = _list(
        payload["done_call_receipt_sha256s"],
        field_name="done_call_receipt_sha256s",
    )
    result = PrivateGenerationIdentity(
        manifest_sha256=_sha256(payload["manifest_sha256"], field_name="manifest_sha256"),
        provider_authority_sha256=_sha256(
            payload["provider_authority_sha256"], field_name="provider_authority_sha256"
        ),
        semantic_source_sha=_source_sha(
            payload["semantic_source_sha"], field_name="semantic_source_sha"
        ),
        chain_id=_safe_token(payload["chain_id"], field_name="chain_id"),
        lane_id=_safe_token(payload["lane_id"], field_name="lane_id"),
        workflow_run_id=_positive_int(payload["workflow_run_id"], field_name="workflow_run_id"),
        workflow_run_attempt=_positive_int(
            payload["workflow_run_attempt"], field_name="workflow_run_attempt"
        ),
        artifact_count=_nonnegative_int(payload["artifact_count"], field_name="artifact_count"),
        done_call_count=_nonnegative_int(payload["done_call_count"], field_name="done_call_count"),
        done_call_receipt_sha256s=tuple(
            _sha256(root, field_name="done_call_receipt_sha256") for root in raw_roots
        ),
        done_call_bindings_sha256=_sha256(
            payload["done_call_bindings_sha256"],
            field_name="done_call_bindings_sha256",
        ),
        done_attempt_count=_nonnegative_int(
            payload["done_attempt_count"], field_name="done_attempt_count"
        ),
        done_blob_count=_nonnegative_int(payload["done_blob_count"], field_name="done_blob_count"),
        orphan_call_count=_nonnegative_int(
            payload["orphan_call_count"], field_name="orphan_call_count"
        ),
        orphan_attempt_count=_nonnegative_int(
            payload["orphan_attempt_count"], field_name="orphan_attempt_count"
        ),
        orphan_blob_count=_nonnegative_int(
            payload["orphan_blob_count"], field_name="orphan_blob_count"
        ),
        stored_bytes=_nonnegative_int(payload["stored_bytes"], field_name="stored_bytes"),
    )
    if result.done_call_receipts_sha256 != _sha256(
        payload["done_call_receipts_sha256"],
        field_name="done_call_receipts_sha256",
    ):
        raise SuccessorAssuranceContractError(
            "update private generation logical-call root digest differs"
        )
    if result.done_call_receipt_sha256s != expected_logical_call_roots:
        raise SuccessorAssuranceContractError(
            "update private generation logical-call roots differ from observed delta receipts"
        )
    if result.done_call_bindings_sha256 != expected_logical_call_bindings_sha256:
        raise SuccessorAssuranceContractError(
            "update private generation logical-call binding digest differs from "
            "baseline, intent, and build"
        )
    return result


def _expected_logical_call_binding_payloads(
    *,
    baseline: BaselineAssuranceIdentity,
    intent: SuccessorUpdateIntent,
    build: SuccessorGenerationBuild,
) -> tuple[dict[str, object], ...]:
    """Derive the exact public-safe capture bindings required by the build.

    One provider invocation may produce several requested result routes.  The
    logical-call receipt is therefore a root, not a route receipt.  Every route
    attached to a root must retain one endpoint and one canonical parameter
    identity, while the result-route inventory remains exact, sorted, and unique.
    """

    scopes_by_identity = {scope.identity_sha256: scope for scope in intent.requested_scopes}
    route_contracts = staging_route_contract_bundle().by_route_id
    grouped: dict[str, tuple[str, str, set[str]]] = {}
    for receipt in build.observed_delta_receipts:
        scope = scopes_by_identity.get(receipt.requested_scope_sha256)
        if scope is None:
            raise SuccessorAssuranceContractError(
                "logical-call binding references a scope outside the successor intent"
            )

        registered_route = route_contracts.get(scope.route_id)
        if registered_route is None:
            raise SuccessorAssuranceContractError(
                "requested scope is absent from the registered staging route contract bundle"
            )
        if registered_route.endpoint_name != scope.endpoint_name:
            raise SuccessorAssuranceContractError(
                "requested scope endpoint differs from the registered staging route contract"
            )
        if registered_route.contract_sha256 != scope.route_contract_sha256:
            raise SuccessorAssuranceContractError(
                "requested scope digest differs from the registered staging route contract"
            )
        if registered_route.provider_authority_sha256 != baseline.provider_authority_sha256:
            raise SuccessorAssuranceContractError(
                "requested staging route provider authority differs from the baseline"
            )
        route_endpoint_name = registered_route.endpoint_name

        root = receipt.logical_call_receipt_sha256
        current = grouped.get(root)
        if current is None:
            grouped[root] = (
                route_endpoint_name,
                scope.scope_sha256,
                {scope.route_id},
            )
            continue

        endpoint_name, logical_parameters_sha256, result_route_ids = current
        if route_endpoint_name != endpoint_name:
            raise SuccessorAssuranceContractError(
                "logical-call root spans multiple endpoint authorities"
            )
        if logical_parameters_sha256 != scope.scope_sha256:
            raise SuccessorAssuranceContractError(
                "logical-call root spans multiple logical parameter authorities"
            )
        if scope.route_id in result_route_ids:
            raise SuccessorAssuranceContractError(
                "logical-call root contains duplicate exact result routes"
            )
        result_route_ids.add(scope.route_id)

    return tuple(
        {
            "endpoint_name": endpoint_name,
            "logical_call_receipt_sha256": root,
            "logical_parameters_sha256": logical_parameters_sha256,
            "provider_authority_sha256": baseline.provider_authority_sha256,
            "result_route_ids": sorted(result_route_ids),
        }
        for root, (endpoint_name, logical_parameters_sha256, result_route_ids) in sorted(
            grouped.items()
        )
    )


def _five_key_binding_payloads(
    calls: Sequence[SuccessorLogicalCallAuthority],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "endpoint_name": call.endpoint_name,
            "logical_call_receipt_sha256": call.logical_call_receipt_sha256,
            "logical_parameters_sha256": call.logical_parameters_sha256,
            "provider_authority_sha256": call.provider_authority_sha256,
            "result_route_ids": list(call.result_route_ids),
        }
        for call in calls
    )


@dataclass(frozen=True, slots=True)
class SuccessorRouteReceiptAttestation:
    """One route/staging receipt owned by a single logical call root."""

    requested_scope_sha256: str
    route_id: str
    execution_dispatch_identity_sha256: str
    source_scope_replacement_sha256: str
    persisted_content_sha256: str
    disposition: str

    def __post_init__(self) -> None:
        _sha256(self.requested_scope_sha256, field_name="requested_scope_sha256")
        _safe_token(self.route_id, field_name="route_id")
        _sha256(
            self.execution_dispatch_identity_sha256,
            field_name="execution_dispatch_identity_sha256",
        )
        _sha256(
            self.source_scope_replacement_sha256,
            field_name="source_scope_replacement_sha256",
        )
        _sha256(self.persisted_content_sha256, field_name="persisted_content_sha256")
        if self.disposition not in {
            DeltaDisposition.OBSERVED.value,
            DeltaDisposition.TYPED_ZERO.value,
        }:
            raise SuccessorAssuranceContractError("route receipt disposition is invalid")

    def to_dict(self) -> dict[str, str]:
        return {
            "requested_scope_sha256": self.requested_scope_sha256,
            "route_id": self.route_id,
            "execution_dispatch_identity_sha256": self.execution_dispatch_identity_sha256,
            "source_scope_replacement_sha256": self.source_scope_replacement_sha256,
            "persisted_content_sha256": self.persisted_content_sha256,
            "disposition": self.disposition,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "requested_scope_sha256",
                "route_id",
                "execution_dispatch_identity_sha256",
                "source_scope_replacement_sha256",
                "persisted_content_sha256",
                "disposition",
            },
            label="route receipt attestation",
        )
        route_id = payload["route_id"]
        disposition = payload["disposition"]
        if not isinstance(route_id, str) or not isinstance(disposition, str):
            raise SuccessorAssuranceContractError("route receipt attestation fields are invalid")
        return cls(
            requested_scope_sha256=_sha256(
                payload["requested_scope_sha256"],
                field_name="requested_scope_sha256",
            ),
            route_id=route_id,
            execution_dispatch_identity_sha256=_sha256(
                payload["execution_dispatch_identity_sha256"],
                field_name="execution_dispatch_identity_sha256",
            ),
            source_scope_replacement_sha256=_sha256(
                payload["source_scope_replacement_sha256"],
                field_name="source_scope_replacement_sha256",
            ),
            persisted_content_sha256=_sha256(
                payload["persisted_content_sha256"],
                field_name="persisted_content_sha256",
            ),
            disposition=disposition,
        )


@dataclass(frozen=True, slots=True)
class SuccessorLogicalCallAuthority:
    """One logical receipt root closed across its exact ordered result routes."""

    endpoint_name: str
    logical_call_receipt_sha256: str
    logical_parameters_sha256: str
    provider_authority_sha256: str
    result_route_ids: tuple[str, ...]
    route_receipts: tuple[SuccessorRouteReceiptAttestation, ...]

    def __post_init__(self) -> None:
        _safe_token(self.endpoint_name, field_name="endpoint_name")
        _sha256(self.logical_call_receipt_sha256, field_name="logical_call_receipt_sha256")
        _sha256(self.logical_parameters_sha256, field_name="logical_parameters_sha256")
        _sha256(self.provider_authority_sha256, field_name="provider_authority_sha256")
        routes = tuple(self.result_route_ids)
        if (
            not routes
            or any(not isinstance(route_id, str) for route_id in routes)
            or tuple(sorted(set(routes))) != routes
        ):
            raise SuccessorAssuranceContractError(
                "logical-call result routes must be a sorted unique nonempty inventory"
            )
        for route_id in routes:
            _safe_token(route_id, field_name="result_route_id")
        receipts = tuple(self.route_receipts)
        if not receipts or any(
            not isinstance(item, SuccessorRouteReceiptAttestation) for item in receipts
        ):
            raise SuccessorAssuranceContractError(
                "logical-call route receipts must be SuccessorRouteReceiptAttestation values"
            )
        ordered = tuple(sorted(receipts, key=lambda item: item.requested_scope_sha256))
        if ordered != receipts:
            raise SuccessorAssuranceContractError(
                "logical-call route receipts must be sorted by requested_scope_sha256"
            )
        scope_ids = [item.requested_scope_sha256 for item in receipts]
        if len(scope_ids) != len(set(scope_ids)):
            raise SuccessorAssuranceContractError(
                "logical-call route receipts contain duplicate requested scopes"
            )
        receipt_routes = tuple(item.route_id for item in receipts)
        if len(receipt_routes) != len(set(receipt_routes)):
            raise SuccessorAssuranceContractError(
                "logical-call route receipts contain duplicate result routes"
            )
        if set(receipt_routes) != set(routes):
            missing = sorted(set(routes) - set(receipt_routes))
            unexpected = sorted(set(receipt_routes) - set(routes))
            raise SuccessorAssuranceContractError(
                "logical-call route receipts do not exactly cover result routes: "
                f"missing={missing}; unexpected={unexpected}"
            )
        object.__setattr__(self, "result_route_ids", routes)
        object.__setattr__(self, "route_receipts", receipts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "logical_parameters_sha256": self.logical_parameters_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "result_route_ids": list(self.result_route_ids),
            "route_receipts": [item.to_dict() for item in self.route_receipts],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "endpoint_name",
                "logical_call_receipt_sha256",
                "logical_parameters_sha256",
                "provider_authority_sha256",
                "result_route_ids",
                "route_receipts",
            },
            label="logical-call authority",
        )
        endpoint_name = payload["endpoint_name"]
        if not isinstance(endpoint_name, str):
            raise SuccessorAssuranceContractError("logical-call endpoint_name must be a string")
        raw_routes = _list(payload["result_route_ids"], field_name="result_route_ids")
        raw_receipts = _list(payload["route_receipts"], field_name="route_receipts")
        return cls(
            endpoint_name=endpoint_name,
            logical_call_receipt_sha256=_sha256(
                payload["logical_call_receipt_sha256"],
                field_name="logical_call_receipt_sha256",
            ),
            logical_parameters_sha256=_sha256(
                payload["logical_parameters_sha256"],
                field_name="logical_parameters_sha256",
            ),
            provider_authority_sha256=_sha256(
                payload["provider_authority_sha256"],
                field_name="provider_authority_sha256",
            ),
            result_route_ids=tuple(
                _safe_token(route_id, field_name="result_route_id") for route_id in raw_routes
            ),
            route_receipts=tuple(
                SuccessorRouteReceiptAttestation.from_dict(
                    _mapping(raw, field_name=f"route_receipts[{index}]")
                )
                for index, raw in enumerate(raw_receipts)
            ),
        )


def _logical_calls_from_report(
    report: SuccessorTerminalAssuranceReportV7,
) -> tuple[SuccessorLogicalCallAuthority, ...]:
    bindings = _expected_logical_call_binding_payloads(
        baseline=report.baseline,
        intent=report.intent,
        build=report.build,
    )
    scopes_by_id = {scope.identity_sha256: scope for scope in report.intent.requested_scopes}
    receipts_by_root: dict[str, list[Any]] = {}
    for receipt in report.build.observed_delta_receipts:
        receipts_by_root.setdefault(receipt.logical_call_receipt_sha256, []).append(receipt)

    calls: list[SuccessorLogicalCallAuthority] = []
    for binding in bindings:
        root = cast("str", binding["logical_call_receipt_sha256"])
        grouped = receipts_by_root.get(root, [])
        if not grouped:
            raise SuccessorAssuranceContractError(
                "logical-call authority is missing every route receipt for a sealed root"
            )
        route_receipts = tuple(
            SuccessorRouteReceiptAttestation(
                requested_scope_sha256=receipt.requested_scope_sha256,
                route_id=scopes_by_id[receipt.requested_scope_sha256].route_id,
                execution_dispatch_identity_sha256=receipt.execution_dispatch_identity_sha256,
                source_scope_replacement_sha256=receipt.source_scope_replacement_sha256,
                persisted_content_sha256=receipt.persisted_content_sha256,
                disposition=receipt.disposition.value,
            )
            for receipt in sorted(
                grouped,
                key=lambda item: item.requested_scope_sha256,
            )
        )
        calls.append(
            SuccessorLogicalCallAuthority(
                endpoint_name=cast("str", binding["endpoint_name"]),
                logical_call_receipt_sha256=root,
                logical_parameters_sha256=cast("str", binding["logical_parameters_sha256"]),
                provider_authority_sha256=cast("str", binding["provider_authority_sha256"]),
                result_route_ids=tuple(cast("list[str]", binding["result_route_ids"])),
                route_receipts=route_receipts,
            )
        )
    return tuple(calls)


@dataclass(frozen=True, slots=True)
class SuccessorAssuranceManifest:
    """Canonical successor-assurance manifest for one emitted candidate."""

    planning_generation_manifest_sha256: str
    planning_generation_id: str
    planning_artifact_identity_sha256: str
    planning_manifest_sha256: str
    sealed_dispatch_inventory_sha256: str
    execution_plan_sha256: str
    logical_calls: tuple[SuccessorLogicalCallAuthority, ...]
    w2_database_authority: W2DatabaseAuthorityReceiptV1
    w2_database_authority_sha256: str
    w2_expected_call_count: int
    w2_expected_call_inventory_sha256: str
    w2_database_authority_closed: bool
    baseline_identity_sha256: str
    update_intent_sha256: str
    source_sha: str
    generation: int
    requested_scopes_sha256: str
    observed_delta_receipts_sha256: str
    planned_route_replacement_bindings_sha256: str
    transform_inventory_sha256: str
    scan_report_sha256: str
    publication_resource_inventory_sha256: str
    installed_public_tree_sha256: str
    private_generation_receipt_sha256: str
    successor_data_tree_fingerprint: str
    successor_assured_manifest_sha256: str
    successor_validation_report_sha256: str
    logical_call_count: int = field(init=False)
    route_receipt_count: int = field(init=False)
    logical_call_bindings_sha256: str = field(init=False)
    identity_sha256: str = field(init=False)

    schema_version: ClassVar[int] = SUCCESSOR_ASSURANCE_MANIFEST_SCHEMA_VERSION
    kind: ClassVar[str] = SUCCESSOR_ASSURANCE_MANIFEST_KIND
    digest_domain: ClassVar[str] = SUCCESSOR_ASSURANCE_MANIFEST_DIGEST_DOMAIN

    def __post_init__(self) -> None:
        for field_name in (
            "planning_generation_manifest_sha256",
            "planning_artifact_identity_sha256",
            "planning_manifest_sha256",
            "sealed_dispatch_inventory_sha256",
            "execution_plan_sha256",
            "w2_database_authority_sha256",
            "w2_expected_call_inventory_sha256",
            "baseline_identity_sha256",
            "update_intent_sha256",
            "requested_scopes_sha256",
            "observed_delta_receipts_sha256",
            "planned_route_replacement_bindings_sha256",
            "transform_inventory_sha256",
            "scan_report_sha256",
            "publication_resource_inventory_sha256",
            "installed_public_tree_sha256",
            "private_generation_receipt_sha256",
            "successor_data_tree_fingerprint",
            "successor_assured_manifest_sha256",
            "successor_validation_report_sha256",
        ):
            _sha256(getattr(self, field_name), field_name=field_name)
        _safe_token(self.planning_generation_id, field_name="planning_generation_id")
        _source_sha(self.source_sha)
        _positive_int(self.generation, field_name="generation")
        calls = tuple(self.logical_calls)
        if not calls or any(not isinstance(item, SuccessorLogicalCallAuthority) for item in calls):
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest logical calls must be nonempty authorities"
            )
        ordered = tuple(sorted(calls, key=lambda item: item.logical_call_receipt_sha256))
        if ordered != calls:
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest logical calls must be sorted by receipt root"
            )
        roots = [item.logical_call_receipt_sha256 for item in calls]
        if len(roots) != len(set(roots)):
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest contains duplicate logical-call roots"
            )
        route_count = sum(len(item.route_receipts) for item in calls)
        if route_count < len(calls):
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest dropped a required route receipt"
            )
        bindings_sha256 = canonical_sha256(_five_key_binding_payloads(calls))
        w2_receipt = _replay_w2_database_authority(
            self.w2_database_authority,
            label="successor-assurance manifest W2 database authority",
        )
        expected_w2_inventory_sha256 = _w2_expected_call_inventory_sha256(
            _five_key_binding_payloads(calls),
            w2_source_call_admission_inventory_sha256=(
                w2_receipt.w2_source_call_admission_inventory_sha256
            ),
        )
        if (
            self.w2_database_authority_sha256 != w2_receipt.receipt_sha256
            or type(self.w2_expected_call_count) is not int
            or self.w2_expected_call_count != len(calls)
            or self.w2_expected_call_count != w2_receipt.w2_required_logical_call_count
            or self.w2_expected_call_inventory_sha256 != expected_w2_inventory_sha256
            or self.w2_database_authority_closed is not True
        ):
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest W2 database authority is not exact and closed"
            )
        object.__setattr__(self, "w2_database_authority", w2_receipt)
        object.__setattr__(self, "logical_calls", calls)
        object.__setattr__(self, "logical_call_count", len(calls))
        object.__setattr__(self, "route_receipt_count", route_count)
        object.__setattr__(self, "logical_call_bindings_sha256", bindings_sha256)
        object.__setattr__(
            self,
            "identity_sha256",
            canonical_sha256(
                {
                    "digest_domain": self.digest_domain,
                    "manifest": self._identity_payload(),
                }
            ),
        )
        _reject_absolute_paths(self.to_dict())

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "digest_domain": self.digest_domain,
            "planning_generation_manifest_sha256": (self.planning_generation_manifest_sha256),
            "planning_generation_id": self.planning_generation_id,
            "planning_artifact_identity_sha256": self.planning_artifact_identity_sha256,
            "planning_manifest_sha256": self.planning_manifest_sha256,
            "sealed_dispatch_inventory_sha256": self.sealed_dispatch_inventory_sha256,
            "execution_plan_sha256": self.execution_plan_sha256,
            "logical_call_count": self.logical_call_count,
            "logical_calls": [item.to_dict() for item in self.logical_calls],
            "logical_call_bindings_sha256": self.logical_call_bindings_sha256,
            "route_receipt_count": self.route_receipt_count,
            "w2_database_authority": self.w2_database_authority.to_dict(),
            "w2_database_authority_sha256": self.w2_database_authority_sha256,
            "w2_expected_call_count": self.w2_expected_call_count,
            "w2_expected_call_inventory_sha256": self.w2_expected_call_inventory_sha256,
            "w2_database_authority_closed": self.w2_database_authority_closed,
            "baseline_identity_sha256": self.baseline_identity_sha256,
            "update_intent_sha256": self.update_intent_sha256,
            "source_sha": self.source_sha,
            "generation": self.generation,
            "requested_scopes_sha256": self.requested_scopes_sha256,
            "observed_delta_receipts_sha256": self.observed_delta_receipts_sha256,
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
            "transform_inventory_sha256": self.transform_inventory_sha256,
            "scan_report_sha256": self.scan_report_sha256,
            "publication_resource_inventory_sha256": (self.publication_resource_inventory_sha256),
            "installed_public_tree_sha256": self.installed_public_tree_sha256,
            "private_generation_receipt_sha256": self.private_generation_receipt_sha256,
            "successor_data_tree_fingerprint": self.successor_data_tree_fingerprint,
            "successor_assured_manifest_sha256": self.successor_assured_manifest_sha256,
            "successor_validation_report_sha256": self.successor_validation_report_sha256,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict()) + b"\n"

    def to_successor_assurance_identity(self) -> SuccessorAssuranceIdentity:
        return SuccessorAssuranceIdentity(
            baseline_identity_sha256=self.baseline_identity_sha256,
            update_intent_sha256=self.update_intent_sha256,
            source_sha=self.source_sha,
            generation=self.generation,
            requested_scopes_sha256=self.requested_scopes_sha256,
            observed_delta_receipts_sha256=self.observed_delta_receipts_sha256,
            planned_route_replacement_bindings_sha256=(
                self.planned_route_replacement_bindings_sha256
            ),
            transform_inventory_sha256=self.transform_inventory_sha256,
            scan_report_sha256=self.scan_report_sha256,
            publication_resource_inventory_sha256=self.publication_resource_inventory_sha256,
            installed_public_tree_sha256=self.installed_public_tree_sha256,
            private_generation_receipt_sha256=self.private_generation_receipt_sha256,
            successor_data_tree_fingerprint=self.successor_data_tree_fingerprint,
            successor_assured_manifest_sha256=self.successor_assured_manifest_sha256,
            successor_validation_report_sha256=self.successor_validation_report_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["identity_sha256"] = self.identity_sha256
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = {
            "schema_version",
            "kind",
            "digest_domain",
            "planning_generation_manifest_sha256",
            "planning_generation_id",
            "planning_artifact_identity_sha256",
            "planning_manifest_sha256",
            "sealed_dispatch_inventory_sha256",
            "execution_plan_sha256",
            "logical_call_count",
            "logical_calls",
            "logical_call_bindings_sha256",
            "route_receipt_count",
            "w2_database_authority",
            "w2_database_authority_sha256",
            "w2_expected_call_count",
            "w2_expected_call_inventory_sha256",
            "w2_database_authority_closed",
            "baseline_identity_sha256",
            "update_intent_sha256",
            "source_sha",
            "generation",
            "requested_scopes_sha256",
            "observed_delta_receipts_sha256",
            "planned_route_replacement_bindings_sha256",
            "transform_inventory_sha256",
            "scan_report_sha256",
            "publication_resource_inventory_sha256",
            "installed_public_tree_sha256",
            "private_generation_receipt_sha256",
            "successor_data_tree_fingerprint",
            "successor_assured_manifest_sha256",
            "successor_validation_report_sha256",
            "identity_sha256",
        }
        _require_exact_keys(payload, expected, label="successor-assurance manifest")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or payload["digest_domain"] != cls.digest_domain
        ):
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest schema or digest domain is invalid"
            )
        _reject_absolute_paths(payload)
        planning_generation_id = payload["planning_generation_id"]
        if not isinstance(planning_generation_id, str):
            raise SuccessorAssuranceContractError("planning_generation_id must be a string")
        raw_calls = _list(payload["logical_calls"], field_name="logical_calls")
        try:
            w2_database_authority = W2DatabaseAuthorityReceiptV1.from_dict(
                payload["w2_database_authority"]
            )
        except W2DatabaseAuthorityError as exc:
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest W2 database authority is invalid"
            ) from exc
        result = cls(
            planning_generation_manifest_sha256=_sha256(
                payload["planning_generation_manifest_sha256"],
                field_name="planning_generation_manifest_sha256",
            ),
            planning_generation_id=planning_generation_id,
            planning_artifact_identity_sha256=_sha256(
                payload["planning_artifact_identity_sha256"],
                field_name="planning_artifact_identity_sha256",
            ),
            planning_manifest_sha256=_sha256(
                payload["planning_manifest_sha256"],
                field_name="planning_manifest_sha256",
            ),
            sealed_dispatch_inventory_sha256=_sha256(
                payload["sealed_dispatch_inventory_sha256"],
                field_name="sealed_dispatch_inventory_sha256",
            ),
            execution_plan_sha256=_sha256(
                payload["execution_plan_sha256"],
                field_name="execution_plan_sha256",
            ),
            logical_calls=tuple(
                SuccessorLogicalCallAuthority.from_dict(
                    _mapping(raw, field_name=f"logical_calls[{index}]")
                )
                for index, raw in enumerate(raw_calls)
            ),
            w2_database_authority=w2_database_authority,
            w2_database_authority_sha256=_sha256(
                payload["w2_database_authority_sha256"],
                field_name="w2_database_authority_sha256",
            ),
            w2_expected_call_count=_nonnegative_int(
                payload["w2_expected_call_count"], field_name="w2_expected_call_count"
            ),
            w2_expected_call_inventory_sha256=_sha256(
                payload["w2_expected_call_inventory_sha256"],
                field_name="w2_expected_call_inventory_sha256",
            ),
            w2_database_authority_closed=payload["w2_database_authority_closed"] is True,
            baseline_identity_sha256=_sha256(
                payload["baseline_identity_sha256"],
                field_name="baseline_identity_sha256",
            ),
            update_intent_sha256=_sha256(
                payload["update_intent_sha256"],
                field_name="update_intent_sha256",
            ),
            source_sha=_source_sha(payload["source_sha"]),
            generation=_positive_int(payload["generation"], field_name="generation"),
            requested_scopes_sha256=_sha256(
                payload["requested_scopes_sha256"],
                field_name="requested_scopes_sha256",
            ),
            observed_delta_receipts_sha256=_sha256(
                payload["observed_delta_receipts_sha256"],
                field_name="observed_delta_receipts_sha256",
            ),
            planned_route_replacement_bindings_sha256=_sha256(
                payload["planned_route_replacement_bindings_sha256"],
                field_name="planned_route_replacement_bindings_sha256",
            ),
            transform_inventory_sha256=_sha256(
                payload["transform_inventory_sha256"],
                field_name="transform_inventory_sha256",
            ),
            scan_report_sha256=_sha256(
                payload["scan_report_sha256"],
                field_name="scan_report_sha256",
            ),
            publication_resource_inventory_sha256=_sha256(
                payload["publication_resource_inventory_sha256"],
                field_name="publication_resource_inventory_sha256",
            ),
            installed_public_tree_sha256=_sha256(
                payload["installed_public_tree_sha256"],
                field_name="installed_public_tree_sha256",
            ),
            private_generation_receipt_sha256=_sha256(
                payload["private_generation_receipt_sha256"],
                field_name="private_generation_receipt_sha256",
            ),
            successor_data_tree_fingerprint=_sha256(
                payload["successor_data_tree_fingerprint"],
                field_name="successor_data_tree_fingerprint",
            ),
            successor_assured_manifest_sha256=_sha256(
                payload["successor_assured_manifest_sha256"],
                field_name="successor_assured_manifest_sha256",
            ),
            successor_validation_report_sha256=_sha256(
                payload["successor_validation_report_sha256"],
                field_name="successor_validation_report_sha256",
            ),
        )
        derived = result.to_dict()
        mismatches = [
            field_name for field_name in expected if derived[field_name] != payload[field_name]
        ]
        if mismatches:
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest derived fields differ: "
                + ", ".join(sorted(mismatches))
            )
        return result


@dataclass(frozen=True, slots=True)
class SuccessorTerminalAssuranceReportV7:
    """Validated DATA-GREEN publication authority for one successor candidate."""

    chain_id: str
    source_sha: str
    coverage_fingerprint: str
    generation: int
    baseline: BaselineAssuranceIdentity
    planning_evidence: SuccessorPlanningEvidence | SuccessorPlanningPublicIdentity
    intent: SuccessorUpdateIntent
    build: SuccessorGenerationBuild
    update_private_generation: PrivateGenerationIdentity
    delta_coverage: SuccessorDeltaCoverage
    transform_outputs: tuple[SuccessorTransformOutputAttestation, ...]
    scan_evidence: SuccessorScanEvidence
    public_evidence: SuccessorPublicEvidence
    database_evidence: SuccessorDatabaseEvidence
    w2_database_authority: W2DatabaseAuthorityReceiptV1
    contract_blocked_evidence: dict[str, Any]
    provider_authority: dict[str, Any]
    model_green: bool = True
    data_green: bool = True
    baseline_identity_sha256: str = field(init=False)
    planning_generation_manifest_sha256: str = field(init=False)
    execution_plan_sha256: str = field(init=False)
    planned_route_replacement_bindings_sha256: str = field(init=False)
    update_intent_sha256: str = field(init=False)
    build_sha256: str = field(init=False)
    private_generation_receipt_sha256: str = field(init=False)
    delta_coverage_sha256: str = field(init=False)
    transform_output_count: int = field(init=False)
    transform_inventory_sha256: str = field(init=False)
    w2_database_authority_sha256: str = field(init=False)
    w2_expected_call_count: int = field(init=False)
    w2_expected_call_inventory_sha256: str = field(init=False)
    w2_database_authority_closed: bool = field(init=False)
    contract_blocked_lane_count: int = field(init=False)
    contract_blocked_evidence_sha256: str = field(init=False)
    provider_authority_sha256: str = field(init=False)

    schema_version: ClassVar[int] = SUCCESSOR_TERMINAL_ASSURANCE_SCHEMA_VERSION
    kind: ClassVar[str] = SUCCESSOR_TERMINAL_ASSURANCE_KIND

    def __post_init__(self) -> None:
        from nbadb.orchestrate.full_extraction_control import (
            _validated_checkpoint_contract_blocked_evidence,
        )
        from nbadb.orchestrate.transformers import expected_transform_output_tables

        _safe_token(self.chain_id, field_name="chain_id")
        _source_sha(self.source_sha)
        _sha256(self.coverage_fingerprint, field_name="coverage_fingerprint")
        _positive_int(self.generation, field_name="generation")
        if self.model_green is not True or self.data_green is not True:
            raise SuccessorAssuranceContractError(
                "successor terminal assurance requires MODEL-GREEN and DATA-GREEN truth"
            )
        if not isinstance(self.baseline, BaselineAssuranceIdentity):
            raise SuccessorAssuranceContractError("baseline must be fully validated")
        if isinstance(self.planning_evidence, SuccessorPlanningEvidence):
            try:
                finalized_intent = finalize_successor_update_intent(self.planning_evidence)
            except ValueError as exc:
                raise SuccessorAssuranceContractError(
                    "successor baseline, planning evidence, intent, and build do not close"
                ) from exc
            if finalized_intent.to_dict() != self.intent.to_dict():
                raise SuccessorAssuranceContractError(
                    "successor intent is not the exact result of sealed planning evidence"
                )
            public_planning = SuccessorPlanningPublicIdentity.from_evidence(self.planning_evidence)
            object.__setattr__(self, "planning_evidence", public_planning)
        elif isinstance(self.planning_evidence, SuccessorPlanningPublicIdentity):
            public_planning = self.planning_evidence
        else:
            raise SuccessorAssuranceContractError("planning_evidence must be fully validated")
        if not isinstance(self.intent, SuccessorUpdateIntent):
            raise SuccessorAssuranceContractError("intent must be fully validated")
        if not isinstance(self.build, SuccessorGenerationBuild):
            raise SuccessorAssuranceContractError("build must be fully validated")
        if not isinstance(self.update_private_generation, PrivateGenerationIdentity):
            raise SuccessorAssuranceContractError(
                "update_private_generation must be a sealed private generation"
            )
        if not isinstance(self.delta_coverage, SuccessorDeltaCoverage):
            raise SuccessorAssuranceContractError("delta_coverage must be fully validated")
        if not isinstance(self.scan_evidence, SuccessorScanEvidence):
            raise SuccessorAssuranceContractError("scan_evidence must be fully validated")
        if not isinstance(self.public_evidence, SuccessorPublicEvidence):
            raise SuccessorAssuranceContractError("public_evidence must be fully validated")
        if not isinstance(self.database_evidence, SuccessorDatabaseEvidence):
            raise SuccessorAssuranceContractError("database_evidence must be fully validated")

        try:
            _ = SuccessorUpdateTransaction(
                state=SuccessorGenerationState.BUILT,
                generation=self.generation,
                baseline=self.baseline,
                intent=self.intent,
                build=self.build,
            )
        except ValueError as exc:
            raise SuccessorAssuranceContractError(
                "successor baseline, planning evidence, intent, and build do not close"
            ) from exc
        planned_route_bindings_sha256 = public_planning.planned_route_replacement_bindings_sha256
        if any(
            authority != planned_route_bindings_sha256
            for authority in (
                public_planning.execution_plan.planned_route_replacement_bindings_sha256,
                self.intent.planned_route_replacement_bindings_sha256,
                self.build.planned_route_replacement_bindings_sha256,
            )
        ):
            raise SuccessorAssuranceContractError(
                "successor planned route replacement binding authority does not close"
            )
        if (
            public_planning.planning_generation_manifest_sha256
            != self.intent.planning_generation_manifest_sha256
            or public_planning.execution_plan_sha256 != self.intent.successor_execution_plan_sha256
        ):
            raise SuccessorAssuranceContractError(
                "public planning identities do not match the sealed successor intent"
            )

        authority_mismatches = []
        if self.source_sha != self.intent.source_sha:
            authority_mismatches.append("source_sha")
        if self.coverage_fingerprint != self.baseline.coverage_fingerprint:
            authority_mismatches.append("coverage_fingerprint")
        if self.chain_id != self.update_private_generation.chain_id:
            authority_mismatches.append("chain_id")
        if self.source_sha != self.update_private_generation.semantic_source_sha:
            authority_mismatches.append("private_generation.semantic_source_sha")
        if authority_mismatches:
            raise SuccessorAssuranceContractError(
                "successor report authority differs: " + ", ".join(authority_mismatches)
            )

        expected_delta = SuccessorDeltaCoverage.from_build(self.build)
        if self.delta_coverage.to_dict() != expected_delta.to_dict():
            raise SuccessorAssuranceContractError(
                "delta coverage does not exactly classify every built requested scope"
            )
        expected_scope_ids = {scope.identity_sha256 for scope in self.intent.requested_scopes}
        classified_scope_ids = {
            *self.delta_coverage.changed_scope_sha256s,
            *self.delta_coverage.no_change_scope_sha256s,
            *self.delta_coverage.typed_zero_scope_sha256s,
        }
        if expected_scope_ids != classified_scope_ids:
            raise SuccessorAssuranceContractError(
                "delta coverage does not exactly close the requested scope inventory"
            )

        transforms = tuple(self.transform_outputs)
        if any(not isinstance(item, SuccessorTransformOutputAttestation) for item in transforms):
            raise SuccessorAssuranceContractError("transform output inventory is invalid")
        if tuple(sorted(transforms, key=lambda item: item.table_name)) != transforms:
            raise SuccessorAssuranceContractError("transform outputs must be sorted by table_name")
        transform_names = [item.table_name for item in transforms]
        if len(transform_names) != len(set(transform_names)):
            raise SuccessorAssuranceContractError("transform output inventory has duplicates")
        expected_transforms = tuple(sorted(expected_transform_output_tables(include_live=True)))
        if (
            not expected_transforms
            or len(expected_transforms) != len(set(expected_transforms))
            or tuple(transform_names) != expected_transforms
        ):
            raise SuccessorAssuranceContractError(
                "transform output inventory does not exactly cover the current "
                "convention-discovered schema-backed tables"
            )

        expected_logical_call_bindings = _expected_logical_call_binding_payloads(
            baseline=self.baseline,
            intent=self.intent,
            build=self.build,
        )
        logical_call_roots = tuple(
            cast("str", binding["logical_call_receipt_sha256"])
            for binding in expected_logical_call_bindings
        )
        expected_logical_call_bindings_sha256 = canonical_sha256(expected_logical_call_bindings)
        w2_receipt = _replay_w2_database_authority(
            self.w2_database_authority,
            label="successor terminal assurance W2 database authority",
        )
        expected_w2_inventory_sha256 = _w2_expected_call_inventory_sha256(
            expected_logical_call_bindings,
            w2_source_call_admission_inventory_sha256=(
                w2_receipt.w2_source_call_admission_inventory_sha256
            ),
        )
        if w2_receipt.w2_required_logical_call_count != len(logical_call_roots):
            raise SuccessorAssuranceContractError(
                "successor W2 database authority call count differs from sealed logical calls"
            )
        private = self.update_private_generation
        if (
            private.done_call_count != len(logical_call_roots)
            or private.done_call_receipt_sha256s != logical_call_roots
            or private.done_call_bindings_sha256 != expected_logical_call_bindings_sha256
            or private.done_attempt_count < private.done_call_count
            or private.artifact_count
            != (
                private.done_call_count
                + private.done_attempt_count
                + private.done_blob_count
                + private.orphan_call_count
                + private.orphan_attempt_count
                + private.orphan_blob_count
            )
            or private.stored_bytes <= 0
        ):
            raise SuccessorAssuranceContractError(
                "sealed update private generation does not reconcile with completed logical calls"
            )

        try:
            normalized_authority = normalize_nba_api_provider_authority(self.provider_authority)
        except ValueError as exc:
            raise SuccessorAssuranceContractError("provider authority is invalid") from exc
        provider_digest = _sha256(
            normalized_authority.get("authority_sha256"),
            field_name="provider_authority_sha256",
        )
        if (
            provider_digest != self.baseline.provider_authority_sha256
            or provider_digest != private.provider_authority_sha256
        ):
            raise SuccessorAssuranceContractError(
                "provider authority does not match baseline and update capture"
            )

        blocked = _canonical_copy(self.contract_blocked_evidence)
        try:
            blocked_rows, blocked_digest = _validated_checkpoint_contract_blocked_evidence(
                {
                    "contract_blocked_lane_count": len(blocked.get("contract_blocked_lanes", [])),
                    "contract_blocked_evidence": blocked,
                    "contract_blocked_evidence_sha256": canonical_sha256(blocked),
                }
            )
        except (AttributeError, ValueError) as exc:
            raise SuccessorAssuranceContractError(
                "inherited contract-blocked evidence is invalid"
            ) from exc
        if blocked_digest != self.baseline.contract_blocked_evidence_sha256:
            raise SuccessorAssuranceContractError(
                "inherited contract-blocked evidence does not match the baseline"
            )

        duckdb_resource = self.public_evidence.resource("nba.duckdb")
        sqlite_resource = self.public_evidence.resource("nba.sqlite")
        database_pairs = (
            (duckdb_resource.sha256, self.database_evidence.duckdb_sha256),
            (duckdb_resource.bytes, self.database_evidence.duckdb_bytes),
            (sqlite_resource.sha256, self.database_evidence.sqlite_sha256),
            (sqlite_resource.bytes, self.database_evidence.sqlite_bytes),
        )
        if any(public != explicit for public, explicit in database_pairs):
            raise SuccessorAssuranceContractError(
                "candidate database evidence does not match the public inventory"
            )

        transform_digest = canonical_sha256([item.to_dict() for item in transforms])
        object.__setattr__(self, "transform_outputs", transforms)
        object.__setattr__(self, "contract_blocked_evidence", blocked)
        object.__setattr__(self, "provider_authority", _canonical_copy(normalized_authority))
        object.__setattr__(self, "baseline_identity_sha256", self.baseline.identity_sha256)
        object.__setattr__(
            self,
            "planning_generation_manifest_sha256",
            public_planning.planning_generation_manifest_sha256,
        )
        object.__setattr__(
            self,
            "execution_plan_sha256",
            public_planning.execution_plan_sha256,
        )
        object.__setattr__(
            self,
            "planned_route_replacement_bindings_sha256",
            planned_route_bindings_sha256,
        )
        object.__setattr__(self, "update_intent_sha256", self.intent.identity_sha256)
        object.__setattr__(self, "build_sha256", self.build.identity_sha256)
        object.__setattr__(
            self,
            "private_generation_receipt_sha256",
            self.update_private_generation.identity_sha256,
        )
        object.__setattr__(
            self,
            "delta_coverage_sha256",
            self.delta_coverage.coverage_sha256,
        )
        object.__setattr__(self, "transform_output_count", len(transforms))
        object.__setattr__(self, "transform_inventory_sha256", transform_digest)
        object.__setattr__(self, "w2_database_authority", w2_receipt)
        object.__setattr__(
            self,
            "w2_database_authority_sha256",
            w2_receipt.receipt_sha256,
        )
        object.__setattr__(self, "w2_expected_call_count", len(logical_call_roots))
        object.__setattr__(
            self,
            "w2_expected_call_inventory_sha256",
            expected_w2_inventory_sha256,
        )
        object.__setattr__(self, "w2_database_authority_closed", True)
        object.__setattr__(self, "contract_blocked_lane_count", len(blocked_rows))
        object.__setattr__(self, "contract_blocked_evidence_sha256", blocked_digest)
        object.__setattr__(self, "provider_authority_sha256", provider_digest)
        public_payload = self.to_dict()
        _reject_private_planning_bytes(public_payload["planning_evidence"])
        _reject_absolute_paths(public_payload)

    @classmethod
    def create(
        cls,
        *,
        chain_id: str,
        source_sha: str,
        coverage_fingerprint: str,
        generation: int,
        baseline: BaselineAssuranceIdentity,
        planning_evidence: SuccessorPlanningEvidence,
        intent: SuccessorUpdateIntent,
        build: SuccessorGenerationBuild,
        update_private_generation: PrivateGenerationIdentity,
        transform_outputs: Sequence[SuccessorTransformOutputAttestation],
        scan_evidence: SuccessorScanEvidence,
        public_evidence: SuccessorPublicEvidence,
        database_evidence: SuccessorDatabaseEvidence,
        w2_database_authority: W2DatabaseAuthorityReceiptV1,
        contract_blocked_evidence: Mapping[str, Any],
        provider_authority: Mapping[str, Any],
    ) -> Self:
        return cls(
            chain_id=chain_id,
            source_sha=source_sha,
            coverage_fingerprint=coverage_fingerprint,
            generation=generation,
            baseline=baseline,
            planning_evidence=planning_evidence,
            intent=intent,
            build=build,
            update_private_generation=update_private_generation,
            delta_coverage=SuccessorDeltaCoverage.from_build(build),
            transform_outputs=tuple(transform_outputs),
            scan_evidence=scan_evidence,
            public_evidence=public_evidence,
            database_evidence=database_evidence,
            w2_database_authority=w2_database_authority,
            contract_blocked_evidence=_canonical_copy(contract_blocked_evidence),
            provider_authority=_canonical_copy(provider_authority),
        )

    @property
    def canonical_bytes(self) -> bytes:
        """Exact bytes that must be written to ``terminal-assurance-report.json``."""

        return canonical_json_bytes(self.to_dict()) + b"\n"

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def to_successor_assurance_identity(
        self,
        *,
        successor_assured_manifest_sha256: str,
        installed_public_tree_sha256: str,
    ) -> SuccessorAssuranceIdentity:
        """Finalize the existing assurance identity after the manifest is built."""

        return SuccessorAssuranceIdentity(
            baseline_identity_sha256=self.baseline_identity_sha256,
            update_intent_sha256=self.update_intent_sha256,
            source_sha=self.source_sha,
            generation=self.generation,
            requested_scopes_sha256=self.intent.requested_scopes_sha256,
            observed_delta_receipts_sha256=self.build.observed_delta_receipts_sha256,
            planned_route_replacement_bindings_sha256=(
                self.planned_route_replacement_bindings_sha256
            ),
            transform_inventory_sha256=self.transform_inventory_sha256,
            scan_report_sha256=self.scan_evidence.report_sha256,
            publication_resource_inventory_sha256=(
                self.public_evidence.publication_resource_inventory_sha256
            ),
            installed_public_tree_sha256=_sha256(
                installed_public_tree_sha256,
                field_name="installed_public_tree_sha256",
            ),
            private_generation_receipt_sha256=self.private_generation_receipt_sha256,
            successor_data_tree_fingerprint=(self.public_evidence.successor_data_tree_fingerprint),
            successor_assured_manifest_sha256=_sha256(
                successor_assured_manifest_sha256,
                field_name="successor_assured_manifest_sha256",
            ),
            successor_validation_report_sha256=self.content_sha256,
        )

    def to_successor_assurance_manifest(
        self,
        *,
        successor_assured_manifest_sha256: str,
        installed_public_tree_sha256: str,
    ) -> SuccessorAssuranceManifest:
        """Project the canonical successor-assurance manifest after controls exist."""

        return emit_successor_assurance_manifest(
            self,
            successor_assured_manifest_sha256=successor_assured_manifest_sha256,
            installed_public_tree_sha256=installed_public_tree_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "model_green": self.model_green,
            "data_green": self.data_green,
            "chain_id": self.chain_id,
            "source_sha": self.source_sha,
            "coverage_fingerprint": self.coverage_fingerprint,
            "generation": self.generation,
            "baseline": self.baseline.to_dict(),
            "baseline_identity_sha256": self.baseline_identity_sha256,
            "planning_evidence": (
                self.planning_evidence.to_public_dict()
                if isinstance(self.planning_evidence, SuccessorPlanningEvidence)
                else self.planning_evidence.to_dict()
            ),
            "planning_generation_manifest_sha256": (self.planning_generation_manifest_sha256),
            "execution_plan_sha256": self.execution_plan_sha256,
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
            "intent": self.intent.to_dict(),
            "update_intent_sha256": self.update_intent_sha256,
            "build": self.build.to_dict(),
            "build_sha256": self.build_sha256,
            "update_private_generation": self.update_private_generation.to_dict(),
            "private_generation_receipt_sha256": self.private_generation_receipt_sha256,
            "delta_coverage": self.delta_coverage.to_dict(),
            "delta_coverage_sha256": self.delta_coverage_sha256,
            "transform_output_count": self.transform_output_count,
            "transform_outputs": [item.to_dict() for item in self.transform_outputs],
            "transform_inventory_sha256": self.transform_inventory_sha256,
            "scan_evidence": self.scan_evidence.to_dict(),
            "public_evidence": self.public_evidence.to_dict(),
            "database_evidence": self.database_evidence.to_dict(),
            "w2_database_authority": self.w2_database_authority.to_dict(),
            "w2_database_authority_sha256": self.w2_database_authority_sha256,
            "w2_expected_call_count": self.w2_expected_call_count,
            "w2_expected_call_inventory_sha256": self.w2_expected_call_inventory_sha256,
            "w2_database_authority_closed": self.w2_database_authority_closed,
            "contract_blocked_lane_count": self.contract_blocked_lane_count,
            "contract_blocked_evidence": _canonical_copy(self.contract_blocked_evidence),
            "contract_blocked_evidence_sha256": self.contract_blocked_evidence_sha256,
            "provider_authority": _canonical_copy(self.provider_authority),
            "provider_authority_sha256": self.provider_authority_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = {
            "schema_version",
            "kind",
            "model_green",
            "data_green",
            "chain_id",
            "source_sha",
            "coverage_fingerprint",
            "generation",
            "baseline",
            "baseline_identity_sha256",
            "planning_evidence",
            "planning_generation_manifest_sha256",
            "execution_plan_sha256",
            "planned_route_replacement_bindings_sha256",
            "intent",
            "update_intent_sha256",
            "build",
            "build_sha256",
            "update_private_generation",
            "private_generation_receipt_sha256",
            "delta_coverage",
            "delta_coverage_sha256",
            "transform_output_count",
            "transform_outputs",
            "transform_inventory_sha256",
            "scan_evidence",
            "public_evidence",
            "database_evidence",
            "w2_database_authority",
            "w2_database_authority_sha256",
            "w2_expected_call_count",
            "w2_expected_call_inventory_sha256",
            "w2_database_authority_closed",
            "contract_blocked_lane_count",
            "contract_blocked_evidence",
            "contract_blocked_evidence_sha256",
            "provider_authority",
            "provider_authority_sha256",
        }
        _require_exact_keys(payload, expected, label="successor terminal assurance report")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or payload["model_green"] is not True
            or payload["data_green"] is not True
        ):
            raise SuccessorAssuranceContractError(
                "successor terminal assurance schema or truth state is invalid"
            )
        _reject_absolute_paths(payload)
        planning_payload = _mapping(payload["planning_evidence"], field_name="planning_evidence")
        _reject_private_planning_bytes(planning_payload)
        try:
            baseline = BaselineAssuranceIdentity.from_dict(
                _mapping(payload["baseline"], field_name="baseline")
            )
            planning = SuccessorPlanningPublicIdentity.from_dict(planning_payload)
            intent = SuccessorUpdateIntent.from_dict(
                _mapping(payload["intent"], field_name="intent")
            )
            build = SuccessorGenerationBuild.from_dict(
                _mapping(payload["build"], field_name="build")
            )
        except ValueError as exc:
            raise SuccessorAssuranceContractError("successor contract member is invalid") from exc
        try:
            expected_logical_call_bindings = _expected_logical_call_binding_payloads(
                baseline=baseline,
                intent=intent,
                build=build,
            )
            private_generation = _private_generation_from_dict(
                _mapping(
                    payload["update_private_generation"],
                    field_name="update_private_generation",
                ),
                expected_logical_call_roots=tuple(
                    cast("str", binding["logical_call_receipt_sha256"])
                    for binding in expected_logical_call_bindings
                ),
                expected_logical_call_bindings_sha256=canonical_sha256(
                    expected_logical_call_bindings
                ),
            )
        except SuccessorAssuranceContractError:
            raise
        except ValueError as exc:
            raise SuccessorAssuranceContractError(
                "update private generation does not reconcile"
            ) from exc
        raw_transforms = _list(payload["transform_outputs"], field_name="transform_outputs")
        try:
            w2_database_authority = W2DatabaseAuthorityReceiptV1.from_dict(
                payload["w2_database_authority"]
            )
        except W2DatabaseAuthorityError as exc:
            raise SuccessorAssuranceContractError(
                "successor terminal assurance W2 database authority is invalid"
            ) from exc
        result = cls(
            chain_id=_safe_token(payload["chain_id"], field_name="chain_id"),
            source_sha=_source_sha(payload["source_sha"]),
            coverage_fingerprint=_sha256(
                payload["coverage_fingerprint"], field_name="coverage_fingerprint"
            ),
            generation=_positive_int(payload["generation"], field_name="generation"),
            baseline=baseline,
            planning_evidence=planning,
            intent=intent,
            build=build,
            update_private_generation=private_generation,
            delta_coverage=SuccessorDeltaCoverage.from_dict(
                _mapping(payload["delta_coverage"], field_name="delta_coverage")
            ),
            transform_outputs=tuple(
                SuccessorTransformOutputAttestation.from_dict(
                    _mapping(raw, field_name=f"transform_outputs[{index}]")
                )
                for index, raw in enumerate(raw_transforms)
            ),
            scan_evidence=SuccessorScanEvidence.from_dict(
                _mapping(payload["scan_evidence"], field_name="scan_evidence")
            ),
            public_evidence=SuccessorPublicEvidence.from_dict(
                _mapping(payload["public_evidence"], field_name="public_evidence")
            ),
            database_evidence=SuccessorDatabaseEvidence.from_dict(
                _mapping(payload["database_evidence"], field_name="database_evidence")
            ),
            w2_database_authority=w2_database_authority,
            contract_blocked_evidence=cast(
                "dict[str, Any]",
                _canonical_copy(
                    _mapping(
                        payload["contract_blocked_evidence"],
                        field_name="contract_blocked_evidence",
                    )
                ),
            ),
            provider_authority=cast(
                "dict[str, Any]",
                _canonical_copy(
                    _mapping(payload["provider_authority"], field_name="provider_authority")
                ),
            ),
        )
        derived = result.to_dict()
        mismatches = [
            field_name for field_name in expected if derived[field_name] != payload[field_name]
        ]
        if mismatches:
            raise SuccessorAssuranceContractError(
                "successor terminal assurance derived fields differ: "
                + ", ".join(sorted(mismatches))
            )
        return result


def validate_successor_terminal_assurance_report(
    value: Mapping[str, object] | bytes | bytearray | str,
) -> SuccessorTerminalAssuranceReportV7:
    """Validate a semantic payload or require exact canonical serialized bytes."""

    encoded: bytes | None = None
    if isinstance(value, str):
        encoded = value.encode("utf-8")
    elif isinstance(value, (bytes, bytearray)):
        encoded = bytes(value)
    if encoded is not None:
        try:
            raw = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorAssuranceContractError(
                "successor terminal assurance report is not valid JSON"
            ) from exc
        payload = _mapping(raw, field_name="successor terminal assurance report")
    else:
        payload = _mapping(value, field_name="successor terminal assurance report")
    result = SuccessorTerminalAssuranceReportV7.from_dict(payload)
    if encoded is not None and encoded != result.canonical_bytes:
        raise SuccessorAssuranceContractError(
            "successor terminal assurance report bytes are not canonical"
        )
    return result


def emit_successor_assurance_manifest(
    report: SuccessorTerminalAssuranceReportV7,
    *,
    successor_assured_manifest_sha256: str,
    installed_public_tree_sha256: str,
) -> SuccessorAssuranceManifest:
    """Emit the canonical successor-assurance manifest from a validated report."""

    if not isinstance(report, SuccessorTerminalAssuranceReportV7):
        raise SuccessorAssuranceContractError(
            "successor-assurance manifest requires a validated terminal report"
        )
    planning = (
        SuccessorPlanningPublicIdentity.from_evidence(report.planning_evidence)
        if isinstance(report.planning_evidence, SuccessorPlanningEvidence)
        else report.planning_evidence
    )
    artifact = planning.planning_generation_manifest.artifact_identity
    execution_plan = planning.execution_plan
    if (
        artifact.planning_manifest_sha256 != execution_plan.planning_manifest_sha256
        or artifact.sealed_dispatch_inventory_sha256
        != execution_plan.sealed_dispatch_inventory_sha256
        or planning.planning_generation_manifest_sha256
        != report.planning_generation_manifest_sha256
        or planning.execution_plan_sha256 != report.execution_plan_sha256
    ):
        raise SuccessorAssuranceContractError(
            "successor-assurance manifest planning-generation and dispatch-manifest "
            "authorities do not close"
        )
    identity = report.to_successor_assurance_identity(
        successor_assured_manifest_sha256=successor_assured_manifest_sha256,
        installed_public_tree_sha256=installed_public_tree_sha256,
    )
    logical_calls = _logical_calls_from_report(report)
    bindings_sha256 = canonical_sha256(_five_key_binding_payloads(logical_calls))
    if bindings_sha256 != report.update_private_generation.done_call_bindings_sha256:
        raise SuccessorAssuranceContractError(
            "successor-assurance manifest logical/route bindings differ from the "
            "sealed private generation"
        )
    return SuccessorAssuranceManifest(
        planning_generation_manifest_sha256=report.planning_generation_manifest_sha256,
        planning_generation_id=execution_plan.planning_generation_id,
        planning_artifact_identity_sha256=execution_plan.planning_artifact_identity_sha256,
        planning_manifest_sha256=execution_plan.planning_manifest_sha256,
        sealed_dispatch_inventory_sha256=execution_plan.sealed_dispatch_inventory_sha256,
        execution_plan_sha256=report.execution_plan_sha256,
        logical_calls=logical_calls,
        w2_database_authority=report.w2_database_authority,
        w2_database_authority_sha256=report.w2_database_authority_sha256,
        w2_expected_call_count=report.w2_expected_call_count,
        w2_expected_call_inventory_sha256=report.w2_expected_call_inventory_sha256,
        w2_database_authority_closed=report.w2_database_authority_closed,
        baseline_identity_sha256=identity.baseline_identity_sha256,
        update_intent_sha256=identity.update_intent_sha256,
        source_sha=identity.source_sha,
        generation=identity.generation,
        requested_scopes_sha256=identity.requested_scopes_sha256,
        observed_delta_receipts_sha256=identity.observed_delta_receipts_sha256,
        planned_route_replacement_bindings_sha256=(
            identity.planned_route_replacement_bindings_sha256
        ),
        transform_inventory_sha256=identity.transform_inventory_sha256,
        scan_report_sha256=identity.scan_report_sha256,
        publication_resource_inventory_sha256=identity.publication_resource_inventory_sha256,
        installed_public_tree_sha256=identity.installed_public_tree_sha256,
        private_generation_receipt_sha256=identity.private_generation_receipt_sha256,
        successor_data_tree_fingerprint=identity.successor_data_tree_fingerprint,
        successor_assured_manifest_sha256=identity.successor_assured_manifest_sha256,
        successor_validation_report_sha256=identity.successor_validation_report_sha256,
    )


def verify_successor_assurance_manifest(
    value: Mapping[str, object] | bytes | bytearray | str | SuccessorAssuranceManifest,
    *,
    report: SuccessorTerminalAssuranceReportV7 | None = None,
    successor_assured_manifest_sha256: str | None = None,
    installed_public_tree_sha256: str | None = None,
    expected_planning_generation_manifest_sha256: str | None = None,
    expected_sealed_dispatch_inventory_sha256: str | None = None,
    expected_logical_call_bindings_sha256: str | None = None,
) -> SuccessorAssuranceManifest:
    """Verify a successor-assurance manifest and its planning/dispatch/receipt authority."""

    encoded: bytes | None = None
    if isinstance(value, SuccessorAssuranceManifest):
        payload = value.to_dict()
    elif isinstance(value, str):
        encoded = value.encode("utf-8")
        payload = None
    elif isinstance(value, (bytes, bytearray)):
        encoded = bytes(value)
        payload = None
    else:
        payload = _mapping(value, field_name="successor-assurance manifest")
    if encoded is not None:
        try:
            raw = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest is not valid JSON"
            ) from exc
        payload = _mapping(raw, field_name="successor-assurance manifest")
    assert payload is not None
    result = SuccessorAssuranceManifest.from_dict(payload)
    if encoded is not None and encoded != result.canonical_bytes:
        raise SuccessorAssuranceContractError(
            "successor-assurance manifest bytes are not canonical"
        )
    if report is not None:
        if not isinstance(report, SuccessorTerminalAssuranceReportV7):
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest verification requires a validated report"
            )
        expected = emit_successor_assurance_manifest(
            report,
            successor_assured_manifest_sha256=(
                successor_assured_manifest_sha256 or result.successor_assured_manifest_sha256
            ),
            installed_public_tree_sha256=(
                installed_public_tree_sha256 or result.installed_public_tree_sha256
            ),
        )
        if expected.to_dict() != result.to_dict():
            raise SuccessorAssuranceContractError(
                "successor-assurance manifest does not match the emitted report authority"
            )
    expectations = (
        (
            "planning_generation_manifest_sha256",
            result.planning_generation_manifest_sha256,
            expected_planning_generation_manifest_sha256,
        ),
        (
            "sealed_dispatch_inventory_sha256",
            result.sealed_dispatch_inventory_sha256,
            expected_sealed_dispatch_inventory_sha256,
        ),
        (
            "logical_call_bindings_sha256",
            result.logical_call_bindings_sha256,
            expected_logical_call_bindings_sha256,
        ),
        (
            "successor_assured_manifest_sha256",
            result.successor_assured_manifest_sha256,
            successor_assured_manifest_sha256,
        ),
        (
            "installed_public_tree_sha256",
            result.installed_public_tree_sha256,
            installed_public_tree_sha256,
        ),
    )
    mismatches = [
        field_name
        for field_name, actual, expected_value in expectations
        if expected_value is not None and actual != expected_value
    ]
    if mismatches:
        raise SuccessorAssuranceContractError(
            "successor-assurance manifest authority differs: " + ", ".join(mismatches)
        )
    return result
