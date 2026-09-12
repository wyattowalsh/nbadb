"""Production-composable lifecycle for one private parser-input generation.

The caller owns configuration and admission measurements.  This module supplies
only lifecycle coordination around :class:`BronzeCaptureStore`; it does not choose
capacity values, enable capture implicitly, or expose private filesystem paths in
its identities.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Self, cast

from nbadb.core.errors import ExtractionError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.extract.bronze import (
    BRONZE_SCHEMA_VERSION,
    BronzeCaptureStore,
    BronzeLimits,
    LogicalCallReceiptBinding,
    ParserInputContext,
    canonical_parameters_sha256,
)
from nbadb.extract.nba_api_adapter import NbaApiCaptureContract

__all__ = [
    "CAPTURE_SESSION_PLACEHOLDER_ENDPOINT_CONTRACT_SHA256",
    "CAPTURE_SESSION_SCHEMA_VERSION",
    "CaptureRunScope",
    "CaptureSessionContractError",
    "CaptureSessionState",
    "CaptureSessionTransitionError",
    "IncompleteCaptureIdentity",
    "PrivateCaptureSession",
    "PrivateGenerationIdentity",
    "planning_wave_lane_id",
    "require_planning_wave_ownership",
]

CAPTURE_SESSION_SCHEMA_VERSION = 2
CAPTURE_SESSION_PLACEHOLDER_ENDPOINT_CONTRACT_SHA256 = hashlib.sha256(
    b"nbadb.capture-session.base-extractor-must-rebind-before-transport.v1"
).hexdigest()

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}")
_SESSION_ATTEMPT_ID_RE = re.compile(
    r"call-([0-9a-f]{12})-([0-9a-f]{8})-([0-9a-f]{12})-([0-9a-f]{16})"
)


class CaptureSessionContractError(ValueError):
    """Raised when capture-session authority is incomplete or inconsistent."""


class CaptureSessionTransitionError(CaptureSessionContractError):
    """Raised when an operation is attempted outside its allowed lifecycle state."""


class CaptureSessionState(StrEnum):
    CREATED = "created"
    ADMITTED = "admitted"
    SEALED = "sealed"
    INCOMPLETE = "incomplete"


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _logical_call_binding_payload(
    binding: LogicalCallReceiptBinding,
) -> dict[str, object]:
    return {
        "endpoint_name": binding.endpoint_name,
        "logical_call_receipt_sha256": binding.logical_call_receipt_sha256,
        "logical_parameters_sha256": binding.logical_parameters_sha256,
        "provider_authority_sha256": binding.provider_authority_sha256,
        "result_route_ids": list(binding.result_route_ids),
    }


def _logical_call_bindings_sha256(
    bindings: Sequence[LogicalCallReceiptBinding],
) -> str:
    ordered = tuple(sorted(bindings, key=lambda item: item.logical_call_receipt_sha256))
    roots = tuple(item.logical_call_receipt_sha256 for item in ordered)
    if len(roots) != len(set(roots)):
        raise CaptureSessionContractError(
            "sealed logical-call binding inventory contains duplicate roots"
        )
    return _canonical_sha256([_logical_call_binding_payload(item) for item in ordered])


def _logical_call_bindings_from_manifest(
    manifest: Mapping[str, object],
) -> tuple[LogicalCallReceiptBinding, ...]:
    raw_bindings = manifest.get("done_call_bindings")
    if not isinstance(raw_bindings, list):
        raise CaptureSessionContractError(
            "sealed private generation done_call_bindings must be a list"
        )
    expected_keys = {
        "endpoint_name",
        "logical_call_receipt_sha256",
        "logical_parameters_sha256",
        "provider_authority_sha256",
        "result_route_ids",
    }
    bindings: list[LogicalCallReceiptBinding] = []
    try:
        for raw_binding in raw_bindings:
            if not isinstance(raw_binding, Mapping) or set(raw_binding) != expected_keys:
                raise ValueError("binding fields are invalid")
            binding_payload = cast("Mapping[str, object]", raw_binding)
            raw_routes = binding_payload["result_route_ids"]
            if not isinstance(raw_routes, list) or any(
                not isinstance(route, str) for route in raw_routes
            ):
                raise ValueError("binding routes are invalid")
            endpoint_name = _require_safe_token(
                binding_payload["endpoint_name"], field_name="endpoint_name"
            )
            root = _require_sha256(
                binding_payload["logical_call_receipt_sha256"],
                field_name="logical_call_receipt_sha256",
            )
            parameters_digest = _require_sha256(
                binding_payload["logical_parameters_sha256"],
                field_name="logical_parameters_sha256",
            )
            provider_digest = _require_sha256(
                binding_payload["provider_authority_sha256"],
                field_name="provider_authority_sha256",
            )
            routes = tuple(
                _require_safe_token(route, field_name="result_route_id") for route in raw_routes
            )
            bindings.append(
                LogicalCallReceiptBinding(
                    endpoint_name=endpoint_name,
                    logical_call_receipt_sha256=root,
                    logical_parameters_sha256=parameters_digest,
                    provider_authority_sha256=provider_digest,
                    result_route_ids=routes,
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise CaptureSessionContractError(
            "sealed private generation logical-call bindings are invalid"
        ) from exc
    canonical_payload = [_logical_call_binding_payload(binding) for binding in bindings]
    if raw_bindings != canonical_payload:
        raise CaptureSessionContractError(
            "sealed private generation logical-call bindings are not canonical"
        )
    expected_digest = _require_sha256(
        manifest.get("done_call_bindings_sha256"),
        field_name="done_call_bindings_sha256",
    )
    if _logical_call_bindings_sha256(bindings) != expected_digest:
        raise CaptureSessionContractError(
            "sealed private generation logical-call binding digest differs"
        )
    return tuple(bindings)


def _require_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise CaptureSessionContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_source_sha(value: object) -> str:
    if not isinstance(value, str) or _SOURCE_SHA_RE.fullmatch(value) is None:
        raise CaptureSessionContractError(
            "semantic_source_sha must be a 40-character lowercase commit SHA"
        )
    return value


def _require_safe_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN_RE.fullmatch(value) is None:
        raise CaptureSessionContractError(f"{field_name} must be an exact safe token")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise CaptureSessionContractError(f"{field_name} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise CaptureSessionContractError(f"{field_name} must be a nonnegative integer")
    return value


def _optional_nonnegative_int(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_nonnegative_int(value, field_name=field_name)


def planning_wave_lane_id(wave_index: int) -> str:
    """Return the exclusive lane token for one planning-wave capture generation."""

    if type(wave_index) is not int or wave_index not in {0, 1}:
        raise CaptureSessionContractError("planning wave index must be exactly 0 or 1")
    return f"planning-wave-{wave_index}"


def require_planning_wave_ownership(
    *,
    planning_generation_id: str,
    wave_index: int,
    chain_id: str,
    lane_id: str,
) -> None:
    """Reject update-execution or otherwise foreign capture identity for a wave."""

    expected_chain = _require_safe_token(
        planning_generation_id,
        field_name="planning_generation_id",
    )
    expected_lane = planning_wave_lane_id(wave_index)
    observed_chain = _require_safe_token(chain_id, field_name="chain_id")
    observed_lane = _require_safe_token(lane_id, field_name="lane_id")
    if observed_chain != expected_chain or observed_lane != expected_lane:
        raise CaptureSessionContractError(
            "capture identity is not exclusively owned by this planning wave"
        )


@dataclass(frozen=True, slots=True)
class CaptureRunScope:
    """Path-free execution scope copied into every parser-input receipt."""

    semantic_source_sha: str
    chain_id: str
    lane_id: str
    workflow_run_id: int
    workflow_run_attempt: int

    def __post_init__(self) -> None:
        _require_source_sha(self.semantic_source_sha)
        _require_safe_token(self.chain_id, field_name="chain_id")
        _require_safe_token(self.lane_id, field_name="lane_id")
        _require_positive_int(self.workflow_run_id, field_name="workflow_run_id")
        _require_positive_int(
            self.workflow_run_attempt,
            field_name="workflow_run_attempt",
        )

    def to_dict(self) -> dict[str, str | int]:
        return {
            "semantic_source_sha": self.semantic_source_sha,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "workflow_run_id": self.workflow_run_id,
            "workflow_run_attempt": self.workflow_run_attempt,
        }

    @property
    def identity_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class PrivateGenerationIdentity:
    """Path-free identity returned only after the bronze manifest is sealed."""

    manifest_sha256: str
    provider_authority_sha256: str
    semantic_source_sha: str
    chain_id: str
    lane_id: str
    workflow_run_id: int
    workflow_run_attempt: int
    artifact_count: int
    done_call_count: int
    done_call_receipt_sha256s: tuple[str, ...]
    done_call_bindings_sha256: str
    done_attempt_count: int
    done_blob_count: int
    orphan_call_count: int
    orphan_attempt_count: int
    orphan_blob_count: int
    stored_bytes: int
    done_call_receipts_sha256: str = field(init=False)

    schema_version: ClassVar[int] = BRONZE_SCHEMA_VERSION
    kind: ClassVar[str] = "private_parser_input_generation"

    def __post_init__(self) -> None:
        _require_sha256(self.manifest_sha256, field_name="manifest_sha256")
        _require_sha256(
            self.provider_authority_sha256,
            field_name="provider_authority_sha256",
        )
        _require_source_sha(self.semantic_source_sha)
        _require_safe_token(self.chain_id, field_name="chain_id")
        _require_safe_token(self.lane_id, field_name="lane_id")
        _require_positive_int(self.workflow_run_id, field_name="workflow_run_id")
        _require_positive_int(
            self.workflow_run_attempt,
            field_name="workflow_run_attempt",
        )
        for field_name in (
            "artifact_count",
            "done_call_count",
            "done_attempt_count",
            "done_blob_count",
            "orphan_call_count",
            "orphan_attempt_count",
            "orphan_blob_count",
            "stored_bytes",
        ):
            _require_nonnegative_int(getattr(self, field_name), field_name=field_name)
        roots = tuple(sorted(self.done_call_receipt_sha256s))
        if len(roots) != len(set(roots)):
            raise CaptureSessionContractError(
                "sealed logical-call root inventory contains duplicates"
            )
        for root in roots:
            _require_sha256(root, field_name="done_call_receipt_sha256")
        if self.done_call_count != len(roots):
            raise CaptureSessionContractError(
                "sealed done_call_count does not reconcile with logical-call roots"
            )
        object.__setattr__(self, "done_call_receipt_sha256s", roots)
        object.__setattr__(
            self,
            "done_call_receipts_sha256",
            _canonical_sha256(list(roots)),
        )
        _require_sha256(
            self.done_call_bindings_sha256,
            field_name="done_call_bindings_sha256",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "manifest_sha256": self.manifest_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "semantic_source_sha": self.semantic_source_sha,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "workflow_run_id": self.workflow_run_id,
            "workflow_run_attempt": self.workflow_run_attempt,
            "artifact_count": self.artifact_count,
            "done_call_count": self.done_call_count,
            "done_call_receipt_sha256s": list(self.done_call_receipt_sha256s),
            "done_call_receipts_sha256": self.done_call_receipts_sha256,
            "done_call_bindings_sha256": self.done_call_bindings_sha256,
            "done_attempt_count": self.done_attempt_count,
            "done_blob_count": self.done_blob_count,
            "orphan_call_count": self.orphan_call_count,
            "orphan_attempt_count": self.orphan_attempt_count,
            "orphan_blob_count": self.orphan_blob_count,
            "stored_bytes": self.stored_bytes,
        }

    @property
    def canonical_bytes(self) -> bytes:
        """Return the exact canonical JSON encoding of this path-free identity."""

        return _canonical_json_bytes(self.to_dict())

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        """Validate and decode the exact current private-generation identity schema."""

        expected_fields = {
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
        if set(payload) != expected_fields:
            raise CaptureSessionContractError("private generation identity fields are invalid")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise CaptureSessionContractError("private generation identity schema is invalid")

        raw_roots = payload["done_call_receipt_sha256s"]
        if not isinstance(raw_roots, list):
            raise CaptureSessionContractError("done_call_receipt_sha256s must be a list")
        roots = tuple(
            _require_sha256(root, field_name="done_call_receipt_sha256") for root in raw_roots
        )
        if list(roots) != sorted(roots) or len(roots) != len(set(roots)):
            raise CaptureSessionContractError(
                "done_call_receipt_sha256s must be a canonical sorted unique inventory"
            )

        result = cls(
            manifest_sha256=_require_sha256(
                payload["manifest_sha256"], field_name="manifest_sha256"
            ),
            provider_authority_sha256=_require_sha256(
                payload["provider_authority_sha256"],
                field_name="provider_authority_sha256",
            ),
            semantic_source_sha=_require_source_sha(payload["semantic_source_sha"]),
            chain_id=_require_safe_token(payload["chain_id"], field_name="chain_id"),
            lane_id=_require_safe_token(payload["lane_id"], field_name="lane_id"),
            workflow_run_id=_require_positive_int(
                payload["workflow_run_id"], field_name="workflow_run_id"
            ),
            workflow_run_attempt=_require_positive_int(
                payload["workflow_run_attempt"],
                field_name="workflow_run_attempt",
            ),
            artifact_count=_require_nonnegative_int(
                payload["artifact_count"], field_name="artifact_count"
            ),
            done_call_count=_require_nonnegative_int(
                payload["done_call_count"], field_name="done_call_count"
            ),
            done_call_receipt_sha256s=roots,
            done_call_bindings_sha256=_require_sha256(
                payload["done_call_bindings_sha256"],
                field_name="done_call_bindings_sha256",
            ),
            done_attempt_count=_require_nonnegative_int(
                payload["done_attempt_count"], field_name="done_attempt_count"
            ),
            done_blob_count=_require_nonnegative_int(
                payload["done_blob_count"], field_name="done_blob_count"
            ),
            orphan_call_count=_require_nonnegative_int(
                payload["orphan_call_count"], field_name="orphan_call_count"
            ),
            orphan_attempt_count=_require_nonnegative_int(
                payload["orphan_attempt_count"], field_name="orphan_attempt_count"
            ),
            orphan_blob_count=_require_nonnegative_int(
                payload["orphan_blob_count"], field_name="orphan_blob_count"
            ),
            stored_bytes=_require_nonnegative_int(
                payload["stored_bytes"], field_name="stored_bytes"
            ),
        )
        expected_roots_digest = _require_sha256(
            payload["done_call_receipts_sha256"],
            field_name="done_call_receipts_sha256",
        )
        if result.done_call_receipts_sha256 != expected_roots_digest:
            raise CaptureSessionContractError(
                "done_call_receipts_sha256 differs from the canonical root inventory"
            )
        if result.to_dict() != dict(payload):
            raise CaptureSessionContractError("private generation identity is not canonical")
        return result

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        """Decode only exact canonical UTF-8 JSON bytes for the current schema."""

        if not isinstance(encoded, bytes):
            raise CaptureSessionContractError("private generation identity encoding must be bytes")

        def reject_duplicate_pairs(
            pairs: list[tuple[str, object]],
        ) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise CaptureSessionContractError(
                        f"private generation identity contains duplicate key {key!r}"
                    )
                result[key] = value
            return result

        def reject_constant(value: str) -> object:
            raise CaptureSessionContractError(
                f"private generation identity contains non-finite JSON value {value}"
            )

        try:
            decoded = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=reject_duplicate_pairs,
                parse_constant=reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaptureSessionContractError(
                "private generation identity is not strict UTF-8 JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise CaptureSessionContractError("private generation identity bytes are not canonical")
        try:
            canonical_decoded = _canonical_json_bytes(decoded)
        except (TypeError, ValueError) as exc:
            raise CaptureSessionContractError(
                "private generation identity contains invalid JSON values"
            ) from exc
        if canonical_decoded != encoded:
            raise CaptureSessionContractError("private generation identity bytes are not canonical")
        result = cls.from_dict(decoded)
        if result.canonical_bytes != encoded:
            raise CaptureSessionContractError(
                "private generation identity bytes differ from validated authority"
            )
        return result

    @classmethod
    def from_manifest(
        cls,
        manifest: Mapping[str, object],
        *,
        scope: CaptureRunScope,
        provider_authority_sha256: str,
    ) -> Self:
        if manifest.get("schema_version") != BRONZE_SCHEMA_VERSION:
            raise CaptureSessionContractError("sealed private generation has an unsupported schema")
        if manifest.get("kind") != cls.kind or manifest.get("sealed") is not True:
            raise CaptureSessionContractError("sealed private generation identity is invalid")
        manifest_sha256 = _require_sha256(
            manifest.get("manifest_sha256"), field_name="manifest_sha256"
        )
        manifest_body = dict(manifest)
        manifest_body.pop("manifest_sha256", None)
        if _canonical_sha256(manifest_body) != manifest_sha256:
            raise CaptureSessionContractError(
                "sealed private generation manifest digest does not match"
            )
        expected_scope = {
            "semantic_source_sha": scope.semantic_source_sha,
            "chain_id": scope.chain_id,
            "lane_id": scope.lane_id,
            "workflow_run_id": scope.workflow_run_id,
            "workflow_run_attempt": scope.workflow_run_attempt,
            "provider_authority_sha256": provider_authority_sha256,
        }
        mismatches = [
            field_name
            for field_name, expected in expected_scope.items()
            if manifest.get(field_name) != expected
        ]
        if mismatches:
            raise CaptureSessionContractError(
                "sealed private generation scope does not match: " + ", ".join(mismatches)
            )

        def inventory_values(
            field_name: str,
            *,
            expected_count_field: str | None,
        ) -> tuple[str, ...]:
            value = manifest.get(field_name)
            if not isinstance(value, list):
                raise CaptureSessionContractError(
                    f"sealed private generation {field_name} must be a list"
                )
            if any(
                not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None for item in value
            ):
                raise CaptureSessionContractError(
                    f"sealed private generation {field_name} is invalid"
                )
            string_values = tuple(item for item in value if isinstance(item, str))
            if len(string_values) != len(set(string_values)):
                raise CaptureSessionContractError(
                    f"sealed private generation {field_name} is invalid"
                )
            if expected_count_field is not None and manifest.get(expected_count_field) != len(
                value
            ):
                raise CaptureSessionContractError(
                    f"sealed private generation {expected_count_field} does not reconcile"
                )
            if list(string_values) != sorted(string_values):
                raise CaptureSessionContractError(
                    f"sealed private generation {field_name} is not canonical"
                )
            return string_values

        done_call_receipt_sha256s = inventory_values(
            "done_call_receipt_sha256s",
            expected_count_field="done_call_count",
        )
        done_attempt_receipt_sha256s = inventory_values(
            "done_attempt_receipt_sha256s",
            expected_count_field="done_attempt_count",
        )
        done_blob_object_sha256s = inventory_values(
            "done_blob_object_sha256s",
            expected_count_field="done_blob_count",
        )
        orphan_call_receipt_sha256s = inventory_values(
            "orphan_call_receipt_sha256s",
            expected_count_field=None,
        )
        orphan_attempt_receipt_sha256s = inventory_values(
            "orphan_attempt_receipt_sha256s",
            expected_count_field=None,
        )
        orphan_blob_object_sha256s = inventory_values(
            "orphan_blob_object_sha256s",
            expected_count_field=None,
        )
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise CaptureSessionContractError("sealed private generation artifacts must be a list")
        artifact_count = _require_nonnegative_int(
            manifest.get("artifact_count"), field_name="artifact_count"
        )
        if artifact_count != len(artifacts):
            raise CaptureSessionContractError(
                "sealed private generation artifact_count does not reconcile"
            )
        artifact_bytes = 0
        for artifact in artifacts:
            if not isinstance(artifact, Mapping):
                raise CaptureSessionContractError(
                    "sealed private generation artifact inventory is invalid"
                )
            artifact_bytes += _require_nonnegative_int(
                artifact.get("size_bytes"), field_name="artifact size_bytes"
            )
        stored_bytes = _require_nonnegative_int(
            manifest.get("stored_bytes"), field_name="stored_bytes"
        )
        if stored_bytes != artifact_bytes:
            raise CaptureSessionContractError(
                "sealed private generation stored_bytes does not reconcile"
            )

        bindings = _logical_call_bindings_from_manifest(manifest)
        binding_roots = tuple(item.logical_call_receipt_sha256 for item in bindings)
        if binding_roots != done_call_receipt_sha256s:
            raise CaptureSessionContractError(
                "sealed logical-call bindings do not reconcile with manifest roots"
            )
        if any(
            binding.provider_authority_sha256 != provider_authority_sha256 for binding in bindings
        ):
            raise CaptureSessionContractError(
                "sealed logical-call bindings differ from generation provider authority"
            )

        return cls(
            manifest_sha256=manifest_sha256,
            provider_authority_sha256=_require_sha256(
                manifest.get("provider_authority_sha256"),
                field_name="provider_authority_sha256",
            ),
            semantic_source_sha=_require_source_sha(manifest.get("semantic_source_sha")),
            chain_id=_require_safe_token(manifest.get("chain_id"), field_name="chain_id"),
            lane_id=_require_safe_token(manifest.get("lane_id"), field_name="lane_id"),
            workflow_run_id=_require_positive_int(
                manifest.get("workflow_run_id"),
                field_name="workflow_run_id",
            ),
            workflow_run_attempt=_require_positive_int(
                manifest.get("workflow_run_attempt"),
                field_name="workflow_run_attempt",
            ),
            artifact_count=artifact_count,
            done_call_count=len(done_call_receipt_sha256s),
            done_call_receipt_sha256s=done_call_receipt_sha256s,
            done_call_bindings_sha256=_require_sha256(
                manifest.get("done_call_bindings_sha256"),
                field_name="done_call_bindings_sha256",
            ),
            done_attempt_count=len(done_attempt_receipt_sha256s),
            done_blob_count=len(done_blob_object_sha256s),
            orphan_call_count=len(orphan_call_receipt_sha256s),
            orphan_attempt_count=len(orphan_attempt_receipt_sha256s),
            orphan_blob_count=len(orphan_blob_object_sha256s),
            stored_bytes=stored_bytes,
        )


@dataclass(frozen=True, slots=True)
class IncompleteCaptureIdentity:
    """Recoverable, path-free evidence returned when an unsealed session closes."""

    provider_authority_sha256: str
    semantic_source_sha: str
    chain_id: str
    lane_id: str
    workflow_run_id: int
    workflow_run_attempt: int
    closed_from_state: str
    issued_call_count: int
    done_call_receipt_sha256s: tuple[str, ...]
    artifact_set_sha256: str | None
    artifact_count: int | None
    stored_bytes: int | None
    inventory_validated: bool
    done_call_receipts_sha256: str = field(init=False)

    schema_version: ClassVar[int] = CAPTURE_SESSION_SCHEMA_VERSION
    kind: ClassVar[str] = "incomplete_private_capture_session"

    def __post_init__(self) -> None:
        _require_sha256(
            self.provider_authority_sha256,
            field_name="provider_authority_sha256",
        )
        _require_source_sha(self.semantic_source_sha)
        _require_safe_token(self.chain_id, field_name="chain_id")
        _require_safe_token(self.lane_id, field_name="lane_id")
        _require_positive_int(self.workflow_run_id, field_name="workflow_run_id")
        _require_positive_int(
            self.workflow_run_attempt,
            field_name="workflow_run_attempt",
        )
        if self.closed_from_state not in {
            CaptureSessionState.CREATED.value,
            CaptureSessionState.ADMITTED.value,
        }:
            raise CaptureSessionContractError("incomplete close state is invalid")
        _require_nonnegative_int(self.issued_call_count, field_name="issued_call_count")
        roots = tuple(sorted(self.done_call_receipt_sha256s))
        if len(roots) != len(set(roots)):
            raise CaptureSessionContractError(
                "incomplete logical-call root inventory contains duplicates"
            )
        for root in roots:
            _require_sha256(root, field_name="done_call_receipt_sha256")
        object.__setattr__(self, "done_call_receipt_sha256s", roots)
        object.__setattr__(
            self,
            "done_call_receipts_sha256",
            _canonical_sha256(list(roots)),
        )
        if self.artifact_set_sha256 is not None:
            _require_sha256(self.artifact_set_sha256, field_name="artifact_set_sha256")
        _optional_nonnegative_int(self.artifact_count, field_name="artifact_count")
        _optional_nonnegative_int(self.stored_bytes, field_name="stored_bytes")
        if type(self.inventory_validated) is not bool:
            raise CaptureSessionContractError("inventory_validated must be a boolean")
        inventory_fields_present = (
            self.artifact_set_sha256 is not None
            and self.artifact_count is not None
            and self.stored_bytes is not None
        )
        if self.inventory_validated != inventory_fields_present:
            raise CaptureSessionContractError(
                "incomplete inventory fields do not match validation state"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "provider_authority_sha256": self.provider_authority_sha256,
            "semantic_source_sha": self.semantic_source_sha,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "workflow_run_id": self.workflow_run_id,
            "workflow_run_attempt": self.workflow_run_attempt,
            "closed_from_state": self.closed_from_state,
            "issued_call_count": self.issued_call_count,
            "done_call_receipt_sha256s": list(self.done_call_receipt_sha256s),
            "done_call_receipts_sha256": self.done_call_receipts_sha256,
            "artifact_set_sha256": self.artifact_set_sha256,
            "artifact_count": self.artifact_count,
            "stored_bytes": self.stored_bytes,
            "inventory_validated": self.inventory_validated,
        }

    @property
    def identity_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())


class PrivateCaptureSession:
    """Explicitly admitted writer for one private bronze generation."""

    @staticmethod
    def _validated_inputs(
        root: Path | str,
        *,
        limits: BronzeLimits,
        public_roots: Sequence[Path | str],
        scope: CaptureRunScope,
    ) -> tuple[Path | str, tuple[Path | str, ...]]:
        if not isinstance(limits, BronzeLimits):
            raise CaptureSessionContractError("limits must be a BronzeLimits value")
        if limits.max_checkpoint_bytes is None or limits.minimum_deadline_headroom_seconds is None:
            raise CaptureSessionContractError("capture admission limits are not configured")
        if not isinstance(scope, CaptureRunScope):
            raise CaptureSessionContractError("scope must be a CaptureRunScope")
        if not isinstance(root, Path | str) or (isinstance(root, str) and not root):
            raise CaptureSessionContractError("root must be an explicitly supplied path")
        roots = tuple(public_roots)
        if not roots:
            raise CaptureSessionContractError(
                "public_roots must contain at least one public data root"
            )
        return root, roots

    def __init__(
        self,
        root: Path | str,
        *,
        limits: BronzeLimits,
        public_roots: Sequence[Path | str],
        scope: CaptureRunScope,
    ) -> None:
        root, roots = self._validated_inputs(
            root,
            limits=limits,
            public_roots=public_roots,
            scope=scope,
        )

        authority = expected_nba_api_provider_authority()
        provider_digest = authority.get("authority_sha256")
        provider_authority_sha256 = _require_sha256(
            provider_digest,
            field_name="provider_authority_sha256",
        )
        store = BronzeCaptureStore(
            root,
            limits=limits,
            public_roots=roots,
        )
        self._initialize(
            store=store,
            scope=scope,
            provider_authority_sha256=provider_authority_sha256,
        )

    @classmethod
    def create_under_authorized_base(
        cls,
        capture_base_root: Path,
        generation_name: str,
        *,
        expected_base_identity: tuple[int, int],
        limits: BronzeLimits,
        public_roots: Sequence[Path | str],
        scope: CaptureRunScope,
    ) -> PrivateCaptureSession:
        """Create or resume one writer below an exact private-base inode."""

        if not isinstance(capture_base_root, Path) or not capture_base_root.is_absolute():
            raise CaptureSessionContractError(
                "capture_base_root must be an explicitly supplied absolute Path"
            )
        if not isinstance(generation_name, str) or not generation_name:
            raise CaptureSessionContractError("generation_name must be a nonempty string")
        root, roots = cls._validated_inputs(
            capture_base_root / generation_name,
            limits=limits,
            public_roots=public_roots,
            scope=scope,
        )
        del root
        authority = expected_nba_api_provider_authority()
        provider_authority_sha256 = _require_sha256(
            authority.get("authority_sha256"),
            field_name="provider_authority_sha256",
        )
        store = BronzeCaptureStore.create_under_authorized_parent(
            capture_base_root,
            generation_name,
            expected_parent_identity=expected_base_identity,
            limits=limits,
            public_roots=roots,
        )
        session = cls.__new__(cls)
        session._initialize(
            store=store,
            scope=scope,
            provider_authority_sha256=provider_authority_sha256,
        )
        return session

    @classmethod
    def open_existing(
        cls,
        root: Path | str,
        *,
        limits: BronzeLimits,
        public_roots: Sequence[Path | str],
        scope: CaptureRunScope,
        expected_root_identity: tuple[int, int],
    ) -> PrivateCaptureSession:
        """Open a retained sealed generation through its pre-authorized inode."""

        root, roots = cls._validated_inputs(
            root,
            limits=limits,
            public_roots=public_roots,
            scope=scope,
        )
        authority = expected_nba_api_provider_authority()
        provider_authority_sha256 = _require_sha256(
            authority.get("authority_sha256"),
            field_name="provider_authority_sha256",
        )
        store = BronzeCaptureStore.open_existing(
            root,
            limits=limits,
            public_roots=roots,
            expected_root_identity=expected_root_identity,
        )
        session = cls.__new__(cls)
        session._initialize(
            store=store,
            scope=scope,
            provider_authority_sha256=provider_authority_sha256,
        )
        return session

    def _initialize(
        self,
        *,
        store: BronzeCaptureStore,
        scope: CaptureRunScope,
        provider_authority_sha256: str,
    ) -> None:
        self._provider_authority_sha256 = provider_authority_sha256
        self._scope = scope
        self._store = store
        try:
            sealed_manifest = self._store.load_sealed_manifest()
            self._contract_count = (
                0
                if sealed_manifest is not None
                else self._next_contract_ordinal(self._store.load_generation_contexts())
            )
        except Exception:
            self._store.close()
            raise
        self._state = CaptureSessionState.CREATED
        self._closed = False
        self._issued_parameter_counts: Counter[tuple[str, str]] = Counter()
        self._completed_bindings: dict[str, LogicalCallReceiptBinding] = {}
        self._generation_identity: PrivateGenerationIdentity | None = None
        self._incomplete_identity: IncompleteCaptureIdentity | None = None
        self._lock = threading.RLock()

    def _next_contract_ordinal(
        self,
        contexts: Sequence[ParserInputContext],
    ) -> int:
        """Validate prior contexts and return a collision-free next ordinal."""

        expected_scope = {
            "workflow_run_id": self._scope.workflow_run_id,
            "workflow_run_attempt": self._scope.workflow_run_attempt,
            "chain_id": self._scope.chain_id,
            "lane_id": self._scope.lane_id,
            "semantic_source_sha": self._scope.semantic_source_sha,
        }
        ordinals: list[int] = []
        expected_prefix = self._scope.identity_sha256[:12]
        for context in contexts:
            mismatches = [
                field_name
                for field_name, expected in expected_scope.items()
                if getattr(context, field_name) != expected
            ]
            if mismatches:
                raise CaptureSessionContractError(
                    "private capture resume context differs from run scope: "
                    + ", ".join(mismatches)
                )
            match = _SESSION_ATTEMPT_ID_RE.fullmatch(context.attempt_id)
            if match is None or match.group(1) != expected_prefix:
                raise CaptureSessionContractError(
                    "private capture resume context has an invalid logical-call identity"
                )
            ordinals.append(int(match.group(2), 16))
        return max(ordinals, default=-1) + 1

    @property
    def scope(self) -> CaptureRunScope:
        return self._scope

    @property
    def state(self) -> CaptureSessionState:
        return self._state

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def generation_identity(self) -> PrivateGenerationIdentity | None:
        return self._generation_identity

    @property
    def incomplete_identity(self) -> IncompleteCaptureIdentity | None:
        return self._incomplete_identity

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _require_live_state(
        self,
        expected: CaptureSessionState,
        *,
        operation: str,
    ) -> None:
        if self._closed:
            raise CaptureSessionTransitionError(f"cannot {operation} a closed capture session")
        if self._state is not expected:
            raise CaptureSessionTransitionError(
                f"cannot {operation} capture session from {self._state.value}; "
                f"expected {expected.value}"
            )

    def admit(
        self,
        *,
        estimated_checkpoint_bytes: int,
        monotonic_now_seconds: float,
        monotonic_deadline_seconds: float,
    ) -> None:
        """Run caller-measured capacity admission before creating any call contract."""

        with self._lock:
            self._require_live_state(CaptureSessionState.CREATED, operation="admit")
            self._store.admit_capture(
                estimated_checkpoint_bytes=estimated_checkpoint_bytes,
                monotonic_now_seconds=monotonic_now_seconds,
                monotonic_deadline_seconds=monotonic_deadline_seconds,
            )
            self._state = CaptureSessionState.ADMITTED

    def inventory_unsealed_contexts(self) -> tuple[ParserInputContext, ...]:
        """Inventory exact unsealed Bronze contexts without changing session state."""

        with self._lock:
            if self._closed:
                raise CaptureSessionTransitionError("cannot inventory a closed capture session")
            if self._state not in {
                CaptureSessionState.CREATED,
                CaptureSessionState.ADMITTED,
            }:
                raise CaptureSessionTransitionError(
                    "cannot inventory unsealed Bronze contexts from "
                    f"{self._state.value}; expected created or admitted"
                )
            try:
                return self._store.load_generation_contexts()
            except (ExtractionError, OSError, TypeError, ValueError) as exc:
                raise CaptureSessionContractError(
                    "unsealed Bronze generation contexts are invalid"
                ) from exc

    def adopt_unsealed_same_generation_writer(self) -> None:
        """Reopen a factory CREATED writer as admitted without capacity re-admit.

        Sealed generations stay on ``restore_sealed_identity_if_present``.
        Bindings stay empty until the caller restores them from the terminal
        or the generation journal.
        """

        with self._lock:
            self._require_live_state(
                CaptureSessionState.CREATED,
                operation="adopt an unsealed same-generation writer",
            )
            try:
                sealed_manifest = self._store.load_sealed_manifest()
            except (ExtractionError, OSError, TypeError, ValueError) as exc:
                raise CaptureSessionContractError(
                    "unsealed same-generation writer cannot load its sealed-manifest probe"
                ) from exc
            if sealed_manifest is not None:
                raise CaptureSessionContractError(
                    "cannot adopt an unsealed writer while a sealed manifest is present"
                )
            self._state = CaptureSessionState.ADMITTED

    def restore_sealed_identity_if_present(self) -> PrivateGenerationIdentity | None:
        """Restore an exact sealed identity after crash reentry, without mutation."""

        with self._lock:
            self._require_live_state(
                CaptureSessionState.CREATED,
                operation="restore a sealed identity",
            )
            try:
                manifest = self._store.load_sealed_manifest()
                if manifest is None:
                    return None

                identity = PrivateGenerationIdentity.from_manifest(
                    manifest,
                    scope=self._scope,
                    provider_authority_sha256=self._provider_authority_sha256,
                )
                next_contract_ordinal = self._next_contract_ordinal(
                    self._store.load_generation_contexts()
                )
                bindings = _logical_call_bindings_from_manifest(manifest)
                restored_bindings = {
                    binding.logical_call_receipt_sha256: binding for binding in bindings
                }
                if tuple(sorted(restored_bindings)) != identity.done_call_receipt_sha256s:
                    raise CaptureSessionContractError(
                        "sealed logical-call binding inventory does not match its identity"
                    )
            except CaptureSessionContractError:
                self._close_failed_sealed_restore()
                raise
            except (ExtractionError, OSError, TypeError, ValueError) as exc:
                self._close_failed_sealed_restore()
                raise CaptureSessionContractError(
                    "sealed private capture generation is invalid"
                ) from exc

            self._contract_count = next_contract_ordinal
            self._completed_bindings = restored_bindings
            self._generation_identity = identity
            self._state = CaptureSessionState.SEALED
            return identity

    def _close_failed_sealed_restore(self) -> None:
        """Fail closed and release generation ownership after rejected reentry."""

        self._incomplete_identity = IncompleteCaptureIdentity(
            provider_authority_sha256=self._provider_authority_sha256,
            semantic_source_sha=self._scope.semantic_source_sha,
            chain_id=self._scope.chain_id,
            lane_id=self._scope.lane_id,
            workflow_run_id=self._scope.workflow_run_id,
            workflow_run_attempt=self._scope.workflow_run_attempt,
            closed_from_state=CaptureSessionState.CREATED.value,
            issued_call_count=self._contract_count,
            done_call_receipt_sha256s=(),
            artifact_set_sha256=None,
            artifact_count=None,
            stored_bytes=None,
            inventory_validated=False,
        )
        self._state = CaptureSessionState.INCOMPLETE
        self._store.close()
        self._closed = True

    def contract_for(
        self,
        endpoint_name: str,
        params: Mapping[str, Any],
    ) -> NbaApiCaptureContract:
        """Return an isolated zero-ordinal contract without retaining raw parameters."""

        with self._lock:
            self._require_live_state(
                CaptureSessionState.ADMITTED,
                operation="create a capture contract",
            )
            endpoint = _require_safe_token(endpoint_name, field_name="endpoint_name")
            if not isinstance(params, Mapping):
                raise CaptureSessionContractError("params must be a mapping")
            try:
                parameter_digest = canonical_parameters_sha256(params)
            except (TypeError, ValueError) as exc:
                raise CaptureSessionContractError(
                    "capture contract parameters are invalid"
                ) from exc

            call_ordinal = self._contract_count
            attempt_id = self._attempt_id(
                call_ordinal=call_ordinal,
                endpoint_name=endpoint,
                parameter_digest=parameter_digest,
            )
            context = ParserInputContext(
                attempt_id=attempt_id,
                retry_ordinal=0,
                request_ordinal=0,
                workflow_run_id=self._scope.workflow_run_id,
                workflow_run_attempt=self._scope.workflow_run_attempt,
                chain_id=self._scope.chain_id,
                lane_id=self._scope.lane_id,
                semantic_source_sha=self._scope.semantic_source_sha,
            )
            self._contract_count += 1
            self._issued_parameter_counts[(endpoint, parameter_digest)] += 1
            return NbaApiCaptureContract(
                sink=self._store,
                context=context,
                provider_authority_sha256=self._provider_authority_sha256,
                endpoint_contract_sha256=(CAPTURE_SESSION_PLACEHOLDER_ENDPOINT_CONTRACT_SHA256),
            )

    def _attempt_id(
        self,
        *,
        call_ordinal: int,
        endpoint_name: str,
        parameter_digest: str,
    ) -> str:
        endpoint_digest = hashlib.sha256(endpoint_name.encode("ascii")).hexdigest()
        return (
            f"call-{self._scope.identity_sha256[:12]}-{call_ordinal:08x}-"
            f"{endpoint_digest[:12]}-{parameter_digest[:16]}"
        )

    def record_completed(self, binding: LogicalCallReceiptBinding) -> None:
        """Validate and retain one durable logical-call root for the final manifest."""

        with self._lock:
            self._require_live_state(
                CaptureSessionState.ADMITTED,
                operation="record a completed logical call",
            )
            if not isinstance(binding, LogicalCallReceiptBinding):
                raise CaptureSessionContractError(
                    "completed root must be a LogicalCallReceiptBinding"
                )
            if binding.provider_authority_sha256 != self._provider_authority_sha256:
                raise CaptureSessionContractError(
                    "completed logical call has provider-authority drift"
                )
            root = binding.logical_call_receipt_sha256
            existing = self._completed_bindings.get(root)
            issued_key = (binding.endpoint_name, binding.logical_parameters_sha256)
            if existing is None and self._issued_parameter_counts[issued_key] < 1:
                raise CaptureSessionContractError(
                    "completed logical call has no issued parameter authority"
                )

            try:
                verified = self._store.load_completed_logical_call_binding(
                    root,
                    expected_endpoint_name=binding.endpoint_name,
                    expected_provider_authority_sha256=(binding.provider_authority_sha256),
                    expected_logical_parameters_sha256=(binding.logical_parameters_sha256),
                    expected_result_route_ids=binding.result_route_ids,
                )
            except (ExtractionError, TypeError, ValueError) as exc:
                raise CaptureSessionContractError(
                    "completed logical-call binding does not match canonical stored authority"
                ) from exc

            if existing is not None:
                if existing != verified or verified != binding:
                    raise CaptureSessionContractError(
                        "completed logical-call root has conflicting binding authority"
                    )
                return

            self._completed_bindings[root] = verified
            self._issued_parameter_counts[
                (verified.endpoint_name, verified.logical_parameters_sha256)
            ] -= 1

    def restore_completed_bindings(
        self,
        bindings: Sequence[LogicalCallReceiptBinding],
    ) -> None:
        """Restore staging-attested roots from the same unsealed generation.

        The owning orchestrator supplies only bindings reconstructed from its
        generation-scoped replacement journal.  Every root is reloaded from
        canonical Bronze bytes and the prospective complete manifest is built
        once to prove provider, semantic source, chain, lane, run, and attempt
        scope before any restored root becomes session state.
        """

        with self._lock:
            self._require_live_state(
                CaptureSessionState.ADMITTED,
                operation="restore completed logical calls",
            )
            if isinstance(bindings, (str, bytes)):
                raise CaptureSessionContractError(
                    "restored logical-call bindings must be a sequence of bindings"
                )
            prospective = dict(self._completed_bindings)
            try:
                for binding in bindings:
                    if not isinstance(binding, LogicalCallReceiptBinding):
                        raise TypeError("restored binding has an invalid type")
                    if binding.provider_authority_sha256 != self._provider_authority_sha256:
                        raise ValueError("restored binding has provider-authority drift")
                    verified = self._store.load_completed_logical_call_binding(
                        binding.logical_call_receipt_sha256,
                        expected_endpoint_name=binding.endpoint_name,
                        expected_provider_authority_sha256=(binding.provider_authority_sha256),
                        expected_logical_parameters_sha256=(binding.logical_parameters_sha256),
                        expected_result_route_ids=binding.result_route_ids,
                    )
                    existing = prospective.get(verified.logical_call_receipt_sha256)
                    if existing is not None and existing != verified:
                        raise ValueError("restored root has conflicting binding authority")
                    prospective[verified.logical_call_receipt_sha256] = verified
                manifest = self._store.build_manifest(
                    provider_authority_sha256=self._provider_authority_sha256,
                    semantic_source_sha=self._scope.semantic_source_sha,
                    chain_id=self._scope.chain_id,
                    lane_id=self._scope.lane_id,
                    workflow_run_id=self._scope.workflow_run_id,
                    workflow_run_attempt=self._scope.workflow_run_attempt,
                    done_call_receipt_sha256s=tuple(sorted(prospective)),
                )
                PrivateGenerationIdentity.from_manifest(
                    manifest,
                    scope=self._scope,
                    provider_authority_sha256=self._provider_authority_sha256,
                )
            except (ExtractionError, TypeError, ValueError) as exc:
                raise CaptureSessionContractError(
                    "restored logical-call bindings do not match the unsealed generation"
                ) from exc
            self._completed_bindings = prospective

    def seal(self) -> PrivateGenerationIdentity:
        """Write the exact bronze manifest and return its path-free identity."""

        with self._lock:
            if self._state is CaptureSessionState.SEALED:
                assert self._generation_identity is not None
                return self._generation_identity
            self._require_live_state(CaptureSessionState.ADMITTED, operation="seal")
            try:
                manifest = self._store.write_manifest(
                    provider_authority_sha256=self._provider_authority_sha256,
                    semantic_source_sha=self._scope.semantic_source_sha,
                    chain_id=self._scope.chain_id,
                    lane_id=self._scope.lane_id,
                    workflow_run_id=self._scope.workflow_run_id,
                    workflow_run_attempt=self._scope.workflow_run_attempt,
                    done_call_receipt_sha256s=tuple(sorted(self._completed_bindings)),
                )
            except (ExtractionError, TypeError, ValueError) as exc:
                raise CaptureSessionContractError(
                    "private capture generation contains a foreign, scope-mismatched, "
                    "or otherwise invalid root"
                ) from exc
            identity = PrivateGenerationIdentity.from_manifest(
                manifest,
                scope=self._scope,
                provider_authority_sha256=self._provider_authority_sha256,
            )
            self._generation_identity = identity
            self._state = CaptureSessionState.SEALED
            return identity

    def _build_incomplete_identity(
        self,
        *,
        closed_from_state: CaptureSessionState,
    ) -> IncompleteCaptureIdentity:
        roots = tuple(sorted(self._completed_bindings))
        artifact_set_sha256: str | None = None
        artifact_count: int | None = None
        stored_bytes: int | None = None
        inventory_validated = False
        try:
            manifest = self._store.build_manifest(
                provider_authority_sha256=self._provider_authority_sha256,
                semantic_source_sha=self._scope.semantic_source_sha,
                chain_id=self._scope.chain_id,
                lane_id=self._scope.lane_id,
                workflow_run_id=self._scope.workflow_run_id,
                workflow_run_attempt=self._scope.workflow_run_attempt,
                done_call_receipt_sha256s=roots,
            )
            if (
                manifest.get("workflow_run_id") != self._scope.workflow_run_id
                or manifest.get("workflow_run_attempt") != self._scope.workflow_run_attempt
            ):
                raise CaptureSessionContractError(
                    "incomplete private generation execution identity does not match"
                )
            artifact_set_sha256 = _require_sha256(
                manifest.get("artifact_set_sha256"),
                field_name="artifact_set_sha256",
            )
            artifact_count = _require_nonnegative_int(
                manifest.get("artifact_count"), field_name="artifact_count"
            )
            stored_bytes = _require_nonnegative_int(
                manifest.get("stored_bytes"), field_name="stored_bytes"
            )
            inventory_validated = True
        except (CaptureSessionContractError, ExtractionError, OSError, TypeError, ValueError):
            pass
        return IncompleteCaptureIdentity(
            provider_authority_sha256=self._provider_authority_sha256,
            semantic_source_sha=self._scope.semantic_source_sha,
            chain_id=self._scope.chain_id,
            lane_id=self._scope.lane_id,
            workflow_run_id=self._scope.workflow_run_id,
            workflow_run_attempt=self._scope.workflow_run_attempt,
            closed_from_state=closed_from_state.value,
            issued_call_count=self._contract_count,
            done_call_receipt_sha256s=roots,
            artifact_set_sha256=artifact_set_sha256,
            artifact_count=artifact_count,
            stored_bytes=stored_bytes,
            inventory_validated=inventory_validated,
        )

    def close(self) -> PrivateGenerationIdentity | IncompleteCaptureIdentity:
        """Release the writer lock, preserving sealed or explicit incomplete state."""

        with self._lock:
            if self._closed:
                identity = self._generation_identity or self._incomplete_identity
                assert identity is not None
                return identity
            try:
                if self._state is not CaptureSessionState.SEALED:
                    closed_from_state = self._state
                    self._incomplete_identity = self._build_incomplete_identity(
                        closed_from_state=closed_from_state
                    )
                    self._state = CaptureSessionState.INCOMPLETE
            finally:
                self._store.close()
                self._closed = True
            identity = self._generation_identity or self._incomplete_identity
            assert identity is not None
            return identity
