from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, ClassVar, Self, cast

__all__ = [
    "CHECKPOINT_CONTRACT_SCHEMA_VERSION",
    "CheckpointArtifactReceipt",
    "CheckpointBuild",
    "CheckpointContractError",
    "CheckpointCoverageIdentity",
    "CheckpointIdentity",
    "CheckpointState",
    "CheckpointTransaction",
    "CheckpointTransitionError",
    "LaneCoverageIdentity",
]

CHECKPOINT_CONTRACT_SCHEMA_VERSION = 1


class CheckpointContractError(ValueError):
    """Raised when checkpoint provenance is incomplete or inconsistent."""


class CheckpointTransitionError(CheckpointContractError):
    """Raised when a checkpoint transaction attempts an illegal state transition."""


class CheckpointState(StrEnum):
    CANDIDATE = "candidate"
    BUILT = "built"
    UPLOADED_VERIFIED = "uploaded_verified"
    COMMITTED = "committed"


def _require_exact_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise CheckpointContractError(f"{field_name} must be a nonempty exact string")
    return value


def _require_sha256(value: object, *, field_name: str, prefixed: bool = False) -> str:
    raw = _require_exact_text(value, field_name=field_name)
    expected_length = 71 if prefixed else 64
    if len(raw) != expected_length:
        raise CheckpointContractError(f"{field_name} must be a lowercase SHA-256")
    if prefixed:
        if not raw.startswith("sha256:"):
            raise CheckpointContractError(f"{field_name} must be a lowercase SHA-256")
        raw_hex = raw.removeprefix("sha256:")
    else:
        raw_hex = raw
    if any(character not in "0123456789abcdef" for character in raw_hex):
        raise CheckpointContractError(f"{field_name} must be a lowercase SHA-256")
    return raw


def _require_source_sha(value: object, *, field_name: str = "source_sha") -> str:
    raw = _require_exact_text(value, field_name=field_name)
    if len(raw) != 40 or any(character not in "0123456789abcdef" for character in raw):
        raise CheckpointContractError(f"{field_name} must be a 40-character lowercase commit SHA")
    return raw


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise CheckpointContractError(f"{field_name} must be a positive integer")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if unexpected:
        details.append("unexpected=" + ",".join(unexpected))
    raise CheckpointContractError(f"{label} fields are invalid: {'; '.join(details)}")


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CheckpointContractError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise CheckpointContractError(f"{field_name} keys must be strings")
    return cast("Mapping[str, object]", value)


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True, order=True)
class LaneCoverageIdentity:
    """Stable lane identity; scheduling and dispatch fields intentionally do not appear."""

    lane_id: str
    coverage_units_hash: str

    def __post_init__(self) -> None:
        _require_exact_text(self.lane_id, field_name="lane_id")
        _require_sha256(self.coverage_units_hash, field_name="coverage_units_hash")

    def to_dict(self) -> dict[str, str]:
        return {
            "lane_id": self.lane_id,
            "coverage_units_hash": self.coverage_units_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset({"lane_id", "coverage_units_hash"}),
            label="lane coverage identity",
        )
        return cls(
            lane_id=_require_exact_text(payload["lane_id"], field_name="lane_id"),
            coverage_units_hash=_require_sha256(
                payload["coverage_units_hash"],
                field_name="coverage_units_hash",
            ),
        )


@dataclass(frozen=True, slots=True)
class CheckpointCoverageIdentity:
    """Semantic coverage plus its dispatch-independent lane inventory."""

    lanes: tuple[LaneCoverageIdentity, ...]
    coverage_fingerprint: str
    lane_inventory_sha256: str = ""

    def __post_init__(self) -> None:
        if any(not isinstance(lane, LaneCoverageIdentity) for lane in self.lanes):
            raise CheckpointContractError(
                "checkpoint coverage lanes must be LaneCoverageIdentity values"
            )
        normalized = tuple(sorted(self.lanes))
        lane_ids = [lane.lane_id for lane in normalized]
        if len(lane_ids) != len(set(lane_ids)):
            raise CheckpointContractError("checkpoint coverage lane IDs must be unique")
        _require_sha256(
            self.coverage_fingerprint,
            field_name="coverage_fingerprint",
        )
        expected_inventory_sha256 = _canonical_sha256([lane.to_dict() for lane in normalized])
        if self.lane_inventory_sha256 and self.lane_inventory_sha256 != expected_inventory_sha256:
            raise CheckpointContractError(
                "checkpoint lane inventory digest does not match its lane inventory"
            )
        object.__setattr__(self, "lanes", normalized)
        object.__setattr__(
            self,
            "lane_inventory_sha256",
            expected_inventory_sha256,
        )

    @classmethod
    def from_lane_contracts(
        cls,
        lanes: Iterable[Mapping[str, object]],
        *,
        coverage_fingerprint: str,
    ) -> Self:
        """Build identity using only stable lane ID and coverage hash fields."""
        identities: list[LaneCoverageIdentity] = []
        for index, lane in enumerate(lanes):
            if not isinstance(lane, Mapping):
                raise CheckpointContractError(f"lane contract at index {index} must be an object")
            identities.append(
                LaneCoverageIdentity(
                    lane_id=_require_exact_text(
                        lane.get("lane_id"),
                        field_name=f"lane contract {index} lane_id",
                    ),
                    coverage_units_hash=_require_sha256(
                        lane.get("coverage_units_hash"),
                        field_name=f"lane contract {index} coverage_units_hash",
                    ),
                )
            )
        return cls(
            lanes=tuple(identities),
            coverage_fingerprint=coverage_fingerprint,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_fingerprint": self.coverage_fingerprint,
            "lane_inventory_sha256": self.lane_inventory_sha256,
            "lanes": [lane.to_dict() for lane in self.lanes],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "coverage_fingerprint",
                    "lane_inventory_sha256",
                    "lanes",
                }
            ),
            label="checkpoint coverage identity",
        )
        raw_lanes = payload["lanes"]
        if not isinstance(raw_lanes, list):
            raise CheckpointContractError("checkpoint coverage lanes must be a list")
        lanes = tuple(
            LaneCoverageIdentity.from_dict(
                _require_mapping(raw_lane, field_name=f"checkpoint coverage lane {index}")
            )
            for index, raw_lane in enumerate(raw_lanes)
        )
        return cls(
            lanes=lanes,
            coverage_fingerprint=_require_sha256(
                payload["coverage_fingerprint"],
                field_name="coverage_fingerprint",
            ),
            lane_inventory_sha256=_require_sha256(
                payload["lane_inventory_sha256"],
                field_name="lane_inventory_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class CheckpointIdentity:
    chain_id: str
    source_sha: str
    generation: int
    coverage: CheckpointCoverageIdentity

    def __post_init__(self) -> None:
        _require_exact_text(self.chain_id, field_name="chain_id")
        _require_source_sha(self.source_sha)
        _require_positive_int(self.generation, field_name="generation")
        if not isinstance(self.coverage, CheckpointCoverageIdentity):
            raise CheckpointContractError("coverage must be a CheckpointCoverageIdentity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "source_sha": self.source_sha,
            "generation": self.generation,
            "coverage": self.coverage.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset({"chain_id", "source_sha", "generation", "coverage"}),
            label="checkpoint identity",
        )
        return cls(
            chain_id=_require_exact_text(payload["chain_id"], field_name="chain_id"),
            source_sha=_require_source_sha(payload["source_sha"]),
            generation=_require_positive_int(payload["generation"], field_name="generation"),
            coverage=CheckpointCoverageIdentity.from_dict(
                _require_mapping(payload["coverage"], field_name="coverage")
            ),
        )


@dataclass(frozen=True, slots=True)
class CheckpointBuild:
    database_sha256: str
    report_sha256: str

    def __post_init__(self) -> None:
        _require_sha256(self.database_sha256, field_name="database_sha256")
        _require_sha256(self.report_sha256, field_name="report_sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "database_sha256": self.database_sha256,
            "report_sha256": self.report_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset({"database_sha256", "report_sha256"}),
            label="checkpoint build",
        )
        return cls(
            database_sha256=_require_sha256(
                payload["database_sha256"],
                field_name="database_sha256",
            ),
            report_sha256=_require_sha256(
                payload["report_sha256"],
                field_name="report_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class CheckpointArtifactReceipt:
    artifact_id: int
    artifact_run_id: int
    artifact_name: str
    artifact_digest: str
    artifact_size_bytes: int
    database_sha256: str
    report_sha256: str
    chain_id: str
    source_sha: str
    generation: int
    coverage_fingerprint: str
    lane_inventory_sha256: str

    def __post_init__(self) -> None:
        _require_positive_int(self.artifact_id, field_name="artifact_id")
        _require_positive_int(self.artifact_run_id, field_name="artifact_run_id")
        _require_exact_text(self.artifact_name, field_name="artifact_name")
        _require_sha256(
            self.artifact_digest,
            field_name="artifact_digest",
            prefixed=True,
        )
        _require_positive_int(self.artifact_size_bytes, field_name="artifact_size_bytes")
        _require_sha256(self.database_sha256, field_name="database_sha256")
        _require_sha256(self.report_sha256, field_name="report_sha256")
        _require_exact_text(self.chain_id, field_name="chain_id")
        _require_source_sha(self.source_sha)
        _require_positive_int(self.generation, field_name="generation")
        _require_sha256(
            self.coverage_fingerprint,
            field_name="coverage_fingerprint",
        )
        _require_sha256(
            self.lane_inventory_sha256,
            field_name="lane_inventory_sha256",
        )

    def to_dict(self) -> dict[str, str | int]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_run_id": self.artifact_run_id,
            "artifact_name": self.artifact_name,
            "artifact_digest": self.artifact_digest,
            "artifact_size_bytes": self.artifact_size_bytes,
            "database_sha256": self.database_sha256,
            "report_sha256": self.report_sha256,
            "chain_id": self.chain_id,
            "source_sha": self.source_sha,
            "generation": self.generation,
            "coverage_fingerprint": self.coverage_fingerprint,
            "lane_inventory_sha256": self.lane_inventory_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "artifact_id",
                "artifact_run_id",
                "artifact_name",
                "artifact_digest",
                "artifact_size_bytes",
                "database_sha256",
                "report_sha256",
                "chain_id",
                "source_sha",
                "generation",
                "coverage_fingerprint",
                "lane_inventory_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="checkpoint artifact receipt")
        return cls(
            artifact_id=_require_positive_int(payload["artifact_id"], field_name="artifact_id"),
            artifact_run_id=_require_positive_int(
                payload["artifact_run_id"],
                field_name="artifact_run_id",
            ),
            artifact_name=_require_exact_text(
                payload["artifact_name"],
                field_name="artifact_name",
            ),
            artifact_digest=_require_sha256(
                payload["artifact_digest"],
                field_name="artifact_digest",
                prefixed=True,
            ),
            artifact_size_bytes=_require_positive_int(
                payload["artifact_size_bytes"],
                field_name="artifact_size_bytes",
            ),
            database_sha256=_require_sha256(
                payload["database_sha256"],
                field_name="database_sha256",
            ),
            report_sha256=_require_sha256(
                payload["report_sha256"],
                field_name="report_sha256",
            ),
            chain_id=_require_exact_text(payload["chain_id"], field_name="chain_id"),
            source_sha=_require_source_sha(payload["source_sha"]),
            generation=_require_positive_int(payload["generation"], field_name="generation"),
            coverage_fingerprint=_require_sha256(
                payload["coverage_fingerprint"],
                field_name="coverage_fingerprint",
            ),
            lane_inventory_sha256=_require_sha256(
                payload["lane_inventory_sha256"],
                field_name="lane_inventory_sha256",
            ),
        )

    def validate_binding(
        self,
        *,
        identity: CheckpointIdentity,
        artifact_name: str,
        build: CheckpointBuild,
    ) -> None:
        expected: tuple[tuple[str, object, object], ...] = (
            ("artifact_name", self.artifact_name, artifact_name),
            ("database_sha256", self.database_sha256, build.database_sha256),
            ("report_sha256", self.report_sha256, build.report_sha256),
            ("chain_id", self.chain_id, identity.chain_id),
            ("source_sha", self.source_sha, identity.source_sha),
            ("generation", self.generation, identity.generation),
            (
                "coverage_fingerprint",
                self.coverage_fingerprint,
                identity.coverage.coverage_fingerprint,
            ),
            (
                "lane_inventory_sha256",
                self.lane_inventory_sha256,
                identity.coverage.lane_inventory_sha256,
            ),
        )
        mismatches = [field_name for field_name, actual, wanted in expected if actual != wanted]
        if mismatches:
            raise CheckpointContractError(
                "checkpoint artifact receipt does not match the built candidate: "
                + ", ".join(mismatches)
            )


@dataclass(frozen=True, slots=True)
class CheckpointTransaction:
    state: CheckpointState
    identity: CheckpointIdentity
    artifact_name: str
    build: CheckpointBuild | None = None
    receipt: CheckpointArtifactReceipt | None = None

    schema_version: ClassVar[int] = CHECKPOINT_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.state, CheckpointState):
            raise CheckpointContractError("state must be a CheckpointState")
        if not isinstance(self.identity, CheckpointIdentity):
            raise CheckpointContractError("identity must be a CheckpointIdentity")
        _require_exact_text(self.artifact_name, field_name="artifact_name")

        expects_build = self.state is not CheckpointState.CANDIDATE
        expects_receipt = self.state in {
            CheckpointState.UPLOADED_VERIFIED,
            CheckpointState.COMMITTED,
        }
        if (self.build is not None) != expects_build:
            raise CheckpointContractError(
                f"{self.state.value} checkpoint has an invalid build contract"
            )
        if (self.receipt is not None) != expects_receipt:
            raise CheckpointContractError(
                f"{self.state.value} checkpoint has an invalid artifact receipt"
            )
        if self.build is not None and not isinstance(self.build, CheckpointBuild):
            raise CheckpointContractError("build must be a CheckpointBuild")
        if self.receipt is not None:
            if not isinstance(self.receipt, CheckpointArtifactReceipt):
                raise CheckpointContractError("receipt must be a CheckpointArtifactReceipt")
            assert self.build is not None
            self.receipt.validate_binding(
                identity=self.identity,
                artifact_name=self.artifact_name,
                build=self.build,
            )

    @classmethod
    def candidate(
        cls,
        *,
        chain_id: str,
        source_sha: str,
        generation: int,
        artifact_name: str,
        lane_contracts: Iterable[Mapping[str, object]],
        coverage_fingerprint: str,
    ) -> Self:
        coverage = CheckpointCoverageIdentity.from_lane_contracts(
            lane_contracts,
            coverage_fingerprint=coverage_fingerprint,
        )
        return cls(
            state=CheckpointState.CANDIDATE,
            identity=CheckpointIdentity(
                chain_id=chain_id,
                source_sha=source_sha,
                generation=generation,
                coverage=coverage,
            ),
            artifact_name=artifact_name,
        )

    def mark_built(self, *, database_sha256: str, report_sha256: str) -> Self:
        self._require_state(CheckpointState.CANDIDATE, operation="mark built")
        return replace(
            self,
            state=CheckpointState.BUILT,
            build=CheckpointBuild(
                database_sha256=database_sha256,
                report_sha256=report_sha256,
            ),
        )

    def mark_uploaded_verified(self, receipt: CheckpointArtifactReceipt) -> Self:
        self._require_state(
            CheckpointState.BUILT,
            operation="mark uploaded and verified",
        )
        assert self.build is not None
        receipt.validate_binding(
            identity=self.identity,
            artifact_name=self.artifact_name,
            build=self.build,
        )
        return replace(
            self,
            state=CheckpointState.UPLOADED_VERIFIED,
            receipt=receipt,
        )

    def commit(self) -> Self:
        self._require_state(
            CheckpointState.UPLOADED_VERIFIED,
            operation="commit",
        )
        return replace(self, state=CheckpointState.COMMITTED)

    @property
    def committed_receipt(self) -> CheckpointArtifactReceipt:
        self._require_state(
            CheckpointState.COMMITTED,
            operation="read committed receipt",
        )
        assert self.receipt is not None
        return self.receipt

    def _require_state(self, expected: CheckpointState, *, operation: str) -> None:
        if self.state is expected:
            return
        raise CheckpointTransitionError(
            f"cannot {operation} checkpoint from {self.state.value}; expected {expected.value}"
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "identity": self.identity.to_dict(),
            "artifact_name": self.artifact_name,
        }
        if self.build is not None:
            payload["build"] = self.build.to_dict()
        if self.receipt is not None:
            payload["receipt"] = self.receipt.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        raw_state = _require_exact_text(payload.get("state"), field_name="state")
        try:
            state = CheckpointState(raw_state)
        except ValueError as exc:
            raise CheckpointContractError(f"unsupported checkpoint state: {raw_state}") from exc

        expected_keys = {
            "schema_version",
            "state",
            "identity",
            "artifact_name",
        }
        if state is not CheckpointState.CANDIDATE:
            expected_keys.add("build")
        if state in {CheckpointState.UPLOADED_VERIFIED, CheckpointState.COMMITTED}:
            expected_keys.add("receipt")
        _require_exact_keys(
            payload,
            expected=frozenset(expected_keys),
            label=f"{state.value} checkpoint transaction",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
        ):
            raise CheckpointContractError(
                "checkpoint transaction has an unsupported schema version"
            )

        build = (
            CheckpointBuild.from_dict(_require_mapping(payload["build"], field_name="build"))
            if state is not CheckpointState.CANDIDATE
            else None
        )
        receipt = (
            CheckpointArtifactReceipt.from_dict(
                _require_mapping(payload["receipt"], field_name="receipt")
            )
            if state in {CheckpointState.UPLOADED_VERIFIED, CheckpointState.COMMITTED}
            else None
        )
        return cls(
            state=state,
            identity=CheckpointIdentity.from_dict(
                _require_mapping(payload["identity"], field_name="identity")
            ),
            artifact_name=_require_exact_text(
                payload["artifact_name"],
                field_name="artifact_name",
            ),
            build=build,
            receipt=receipt,
        )
