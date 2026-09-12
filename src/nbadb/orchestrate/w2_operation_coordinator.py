"""Runtime admission boundary for one exact, already-captured W2 source call.

This coordinator deliberately owns only the two post-capture persistence
boundaries: the five public value relations and the scalar W2 operation row.
Raw Authority V2, committed staging frames, parser-input bodies, and declared
bodyless packets must already exist and arrive with their exact readback
evidence.  Capture closure, manifest advancement, parser-byte disposal, and
journal success remain caller responsibilities after a returned admission.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from typing import ClassVar, Never, cast

from nbadb.contracts.public_table_value_projection import (
    PublicTableValueProjectionReceiptV1,
    PublicTableValueProjectionV1,
)
from nbadb.contracts.raw_request_authority import (
    MAX_AUTHORITY_ROWS,
    RawRequestAuthorityBundleV2,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.value_projection import (
    ValueProjectionItemV1,
    ValueProjectionPartitionV1,
    ValueProjectionReceiptV1,
)
from nbadb.contracts.w2_operation import (
    W2OperationPersistenceReceiptV1,
    W2OperationReceiptV1,
    w2_committed_staging_readback_root,
)
from nbadb.contracts.w2_operation_builder import build_w2_operation
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate import w2_operation_store as w2_operation_store_module
from nbadb.orchestrate.public_value_authority_store import (
    PublicValueAuthorityStore,
    PublicValueAuthorityStoreResult,
)
from nbadb.orchestrate.raw_request_store import (
    RawRequestAuthorityPersistenceReceiptV2,
    RawRequestPersistedAttemptV2,
    logical_parameter_digests_by_provider_call,
)
from nbadb.orchestrate.staging_batches import (
    CommittedStagingChunkReceiptV2,
    CommittedStagingFrameReadbackV2,
)
from nbadb.orchestrate.w2_operation_store import W2OperationStore

__all__ = [
    "W2OperationBuildInputsV1",
    "W2OperationCoordinatorError",
    "W2SourceCallAdmissionV1",
    "W2SourceCallCandidateV1",
    "coordinate_w2_source_call",
    "verify_w2_source_call_admission",
]


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CANONICAL_ADMISSION_BYTES = 2_000_000
_MAX_KNOWN_SECRETS = 128
_MAX_KNOWN_SECRET_BYTES = 4_096
_MAX_INT64 = (1 << 63) - 1


class W2OperationCoordinatorError(RuntimeError):
    """One source call could not be admitted through exact W2 persistence."""


def _fail(message: str) -> Never:
    raise W2OperationCoordinatorError(message) from None


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("W2 source-call admission is not bounded canonical JSON")
    if len(encoded) > _MAX_CANONICAL_ADMISSION_BYTES:
        _fail("W2 source-call admission exceeds its canonical byte bound")
    return encoded


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class W2OperationBuildInputsV1:
    """Exact named inputs retained for independent W2 child reconstruction."""

    raw_bundle: object
    expected_raw_authority_bundle_sha256: object
    raw_observations: object
    committed_staging_readbacks: object
    expected_committed_staging_readback_sha256s: object
    body_value_projection_receipt: object
    expected_body_value_projection_receipt_sha256: object
    body_projection: object
    expected_body_projection_sha256: object
    body_partitions: object
    body_items: object
    ownership_receipt: object
    expected_ownership_receipt_sha256: object
    expected_unit_inventory: object
    representation_assignments: object
    ownership_observations: object
    ownership_partitions: object
    ownership_bindings: object
    result_cell_authority_receipt: object
    expected_result_cell_authority_sha256: object
    stats_lossless_authorities: object
    expected_stats_lossless_authority_sha256s: object
    live_lossless_authority: object
    expected_live_lossless_authority_receipt_sha256: object
    body_blob_inventory: object
    expected_body_blob_inventory_sha256: object
    body_blob_inventory_readback_receipt: object
    expected_body_blob_inventory_readback_receipt_sha256: object
    declared_bodyless_packets: object
    expected_declared_bodyless_packet_authority_sha256s: object
    declared_bodyless_readback_receipts: object
    expected_declared_bodyless_readback_receipt_sha256s: object
    declared_bodyless_packet_bytes: object
    plan: object
    expected_plan_sha256: object
    route_field_landing_receipt: object
    expected_route_field_landing_receipt_sha256: object
    route_landing_receipts: object
    expected_route_landing_receipt_sha256s: object
    canonical_alias_receipts: object
    expected_canonical_alias_receipt_sha256s: object
    route_field_landing_authority_rows: object
    public_table_value_projection_receipt: object
    expected_public_table_value_projection_receipt_sha256: object
    public_projection: object
    expected_public_projection_sha256: object
    public_partitions: object
    public_items: object
    value_projection_equality_receipt: object
    expected_value_projection_equality_receipt_sha256: object
    result_cell_schema_sha256: object
    result_cell_rows: object
    stats_lossless_schema_sha256: object
    stats_lossless_rows: object
    live_lossless_schema_sha256: object
    live_lossless_rows: object
    value_representation_schema_sha256: object
    value_representation_rows: object
    route_field_landing_schema_sha256: object
    route_field_landing_rows: object
    expected_w2_operation_schema_sha256: object
    known_secrets: tuple[str | bytes, ...] = ()


@dataclass(frozen=True, slots=True)
class W2SourceCallCandidateV1:
    """One prior-capture authority candidate for the W2 admission boundary."""

    logical_call_binding: LogicalCallReceiptBinding
    raw_authority_persistence_receipt: RawRequestAuthorityPersistenceReceiptV2
    expected_raw_authority_persistence_receipt_sha256: str
    operation_inputs: W2OperationBuildInputsV1


@dataclass(frozen=True, slots=True)
class W2SourceCallAdmissionV1:
    """Replay-stable admission proving both W2 persistence boundaries."""

    admission_sha256: str
    logical_call_receipt_sha256: str
    raw_authority_bundle_sha256: str
    raw_authority_persistence_receipt_sha256: str
    committed_staging_readback_count: int
    committed_staging_readback_root_sha256: str
    operation_key_sha256: str
    operation_receipt_sha256: str
    w2_operation_persistence_receipt_sha256: str
    operation: W2OperationReceiptV1
    persistence_receipt: W2OperationPersistenceReceiptV1

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_w2_source_call_admission_v1"

    def __post_init__(self) -> None:
        for name in (
            "admission_sha256",
            "logical_call_receipt_sha256",
            "raw_authority_bundle_sha256",
            "raw_authority_persistence_receipt_sha256",
            "committed_staging_readback_root_sha256",
            "operation_key_sha256",
            "operation_receipt_sha256",
            "w2_operation_persistence_receipt_sha256",
        ):
            _sha256(getattr(self, name), label=name)
        if (
            type(self.committed_staging_readback_count) is not int
            or self.committed_staging_readback_count < 1
            or self.committed_staging_readback_count > MAX_AUTHORITY_ROWS
        ):
            _fail("W2 admission staging-readback count is invalid")
        if type(self.operation) is not W2OperationReceiptV1:
            _fail("W2 admission has a foreign operation receipt")
        if type(self.persistence_receipt) is not W2OperationPersistenceReceiptV1:
            _fail("W2 admission has a foreign persistence receipt")
        try:
            exact_operation = W2OperationReceiptV1.from_row(
                self.operation.to_row(),
                expected_operation_receipt_sha256=self.operation_receipt_sha256,
                expected_operation_key_sha256=self.operation_key_sha256,
                expected_raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                expected_w2_operation_schema_sha256=(self.operation.w2_operation_schema_sha256),
            )
            exact_persistence = W2OperationPersistenceReceiptV1.from_row(
                self.persistence_receipt.to_row(),
                expected_persistence_receipt_sha256=(self.w2_operation_persistence_receipt_sha256),
                expected_operation_key_sha256=self.operation_key_sha256,
                expected_operation_receipt_sha256=self.operation_receipt_sha256,
                expected_w2_operation_schema_sha256=(self.operation.w2_operation_schema_sha256),
                expected_operation_row_sha256=hashlib.sha256(
                    exact_operation.canonical_bytes()
                ).hexdigest(),
            )
        except Exception:
            _fail("W2 admission children failed exact semantic replay")
        if (
            exact_operation != self.operation
            or exact_persistence != self.persistence_receipt
            or self.operation.committed_staging_readback_count
            != self.committed_staging_readback_count
            or self.operation.committed_staging_readback_root_sha256
            != self.committed_staging_readback_root_sha256
            or self.persistence_receipt.persistence_receipt_sha256
            != self.w2_operation_persistence_receipt_sha256
        ):
            _fail("W2 admission children differ from its exact scalar bindings")
        if self.admission_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("W2 admission digest differs from its exact semantic identity")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "raw_authority_persistence_receipt_sha256": (
                self.raw_authority_persistence_receipt_sha256
            ),
            "committed_staging_readback_count": self.committed_staging_readback_count,
            "committed_staging_readback_root_sha256": (self.committed_staging_readback_root_sha256),
            "operation_key_sha256": self.operation_key_sha256,
            "operation_receipt_sha256": self.operation_receipt_sha256,
            "w2_operation_persistence_receipt_sha256": (
                self.w2_operation_persistence_receipt_sha256
            ),
        }

    def to_dict(self) -> dict[str, object]:
        payload = {
            **self.identity_payload(),
            "admission_sha256": self.admission_sha256,
            "operation": dict(sorted(self.operation.to_row().items())),
            "persistence_receipt": dict(sorted(self.persistence_receipt.to_row().items())),
        }
        return dict(sorted(payload.items()))

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> W2SourceCallAdmissionV1:
        if cls is not W2SourceCallAdmissionV1 or type(value) is not dict:
            _fail("W2 admission replay requires one exact built-in mapping")
        payload = cast("dict[object, object]", value)
        expected = tuple(
            sorted(
                (
                    "schema_version",
                    "kind",
                    "admission_sha256",
                    "logical_call_receipt_sha256",
                    "raw_authority_bundle_sha256",
                    "raw_authority_persistence_receipt_sha256",
                    "committed_staging_readback_count",
                    "committed_staging_readback_root_sha256",
                    "operation_key_sha256",
                    "operation_receipt_sha256",
                    "w2_operation_persistence_receipt_sha256",
                    "operation",
                    "persistence_receipt",
                )
            )
        )
        if any(type(key) is not str for key in payload) or tuple(payload) != expected:
            _fail("W2 admission replay has a foreign or reordered field shape")
        row = cast("dict[str, object]", payload)
        if row["schema_version"] != cls.schema_version or row["kind"] != cls.kind:
            _fail("W2 admission replay has a foreign contract identity")
        operation_row = row["operation"]
        persistence_row = row["persistence_receipt"]
        if type(operation_row) is not dict or type(persistence_row) is not dict:
            _fail("W2 admission replay has foreign child rows")
        operation_mapping = cast("dict[str, object]", operation_row)
        persistence_mapping = cast("dict[str, object]", persistence_row)
        operation_order = ("schema_version", *(item.name for item in fields(W2OperationReceiptV1)))
        persistence_order = (
            "schema_version",
            *(item.name for item in fields(W2OperationPersistenceReceiptV1)),
        )
        if tuple(operation_mapping) != tuple(sorted(operation_order)) or tuple(
            persistence_mapping
        ) != tuple(sorted(persistence_order)):
            _fail("W2 admission replay has reordered or foreign child fields")
        try:
            operation = W2OperationReceiptV1.from_row(
                {name: operation_mapping[name] for name in operation_order},
                expected_operation_receipt_sha256=cast("str", row["operation_receipt_sha256"]),
                expected_operation_key_sha256=cast("str", row["operation_key_sha256"]),
                expected_raw_authority_bundle_sha256=cast(
                    "str", row["raw_authority_bundle_sha256"]
                ),
                expected_w2_operation_schema_sha256=cast(
                    "str", operation_mapping["w2_operation_schema_sha256"]
                ),
            )
            persistence = W2OperationPersistenceReceiptV1.from_row(
                {name: persistence_mapping[name] for name in persistence_order},
                expected_persistence_receipt_sha256=cast(
                    "str", row["w2_operation_persistence_receipt_sha256"]
                ),
                expected_operation_key_sha256=operation.operation_key_sha256,
                expected_operation_receipt_sha256=operation.operation_receipt_sha256,
                expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
                expected_operation_row_sha256=hashlib.sha256(
                    operation.canonical_bytes()
                ).hexdigest(),
            )
            admission = cls(
                admission_sha256=cast("str", row["admission_sha256"]),
                logical_call_receipt_sha256=cast("str", row["logical_call_receipt_sha256"]),
                raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
                raw_authority_persistence_receipt_sha256=cast(
                    "str", row["raw_authority_persistence_receipt_sha256"]
                ),
                committed_staging_readback_count=cast(
                    "int", row["committed_staging_readback_count"]
                ),
                committed_staging_readback_root_sha256=cast(
                    "str", row["committed_staging_readback_root_sha256"]
                ),
                operation_key_sha256=operation.operation_key_sha256,
                operation_receipt_sha256=operation.operation_receipt_sha256,
                w2_operation_persistence_receipt_sha256=(persistence.persistence_receipt_sha256),
                operation=operation,
                persistence_receipt=persistence,
            )
        except W2OperationCoordinatorError:
            raise
        except Exception:
            _fail("W2 admission child rows failed exact semantic replay")
        if admission.to_dict() != row:
            _fail("W2 admission changed during exact semantic replay")
        return admission

    @classmethod
    def from_canonical_bytes(cls, value: object) -> W2SourceCallAdmissionV1:
        if type(value) is not bytes or not value or len(value) > _MAX_CANONICAL_ADMISSION_BYTES:
            _fail("W2 admission canonical bytes are empty, foreign, or over-bound")

        def no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, member in pairs:
                if key in result:
                    _fail("W2 admission canonical bytes repeat one field")
                result[key] = member
            return result

        try:
            decoded = json.loads(
                value.decode("utf-8", errors="strict"),
                object_pairs_hook=no_duplicate_object,
            )
        except W2OperationCoordinatorError:
            raise
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            _fail("W2 admission canonical bytes are not exact JSON")
        if type(decoded) is not dict or _canonical_bytes(decoded) != value:
            _fail("W2 admission bytes are not one exact canonical mapping")
        return cls.from_dict(decoded)

    @classmethod
    def build(
        cls,
        *,
        logical_call_receipt_sha256: str,
        raw_authority_persistence_receipt_sha256: str,
        operation: W2OperationReceiptV1,
        persistence_receipt: W2OperationPersistenceReceiptV1,
    ) -> W2SourceCallAdmissionV1:
        if cls is not W2SourceCallAdmissionV1:
            _fail("W2 admission builder requires the exact contract class")
        values = {
            "logical_call_receipt_sha256": logical_call_receipt_sha256,
            "raw_authority_bundle_sha256": operation.raw_authority_bundle_sha256,
            "raw_authority_persistence_receipt_sha256": (raw_authority_persistence_receipt_sha256),
            "committed_staging_readback_count": operation.committed_staging_readback_count,
            "committed_staging_readback_root_sha256": (
                operation.committed_staging_readback_root_sha256
            ),
            "operation_key_sha256": operation.operation_key_sha256,
            "operation_receipt_sha256": operation.operation_receipt_sha256,
            "w2_operation_persistence_receipt_sha256": (
                persistence_receipt.persistence_receipt_sha256
            ),
        }
        identity = {"schema_version": cls.schema_version, "kind": cls.kind, **values}
        return cls(
            admission_sha256=_canonical_sha256(identity),
            **values,
            operation=operation,
            persistence_receipt=persistence_receipt,
        )


def _raw_attempts(bundle: RawRequestAuthorityBundleV2) -> tuple[RawRequestPersistedAttemptV2, ...]:
    logical_by_call = logical_parameter_digests_by_provider_call(bundle)
    routes: dict[str, list[str]] = {
        item.attempt.observation_sha256: [] for item in bundle.observations
    }
    for landing in bundle.landings:
        routes[landing.observation_sha256].append(landing.route_id)
    attempts = tuple(
        RawRequestPersistedAttemptV2(
            observation_sha256=item.attempt.observation_sha256,
            observation_record_sha256=item.observation_record_sha256,
            semantic_request_sha256=item.attempt.semantic_request_sha256,
            logical_invocation_sha256=item.attempt.logical_invocation_sha256,
            provider_call_sha256=item.attempt.provider_call_sha256,
            provider_call_role=item.attempt.provider_call_role,
            provider_call_ordinal=item.attempt.provider_call_ordinal,
            retry_ordinal=item.attempt.retry_ordinal,
            request_ordinal=item.attempt.request_ordinal,
            source_family=item.attempt.source_family,
            endpoint_id=item.attempt.endpoint_id,
            provider_request_sha256=item.attempt.provider_request_sha256,
            logical_parameters_sha256=logical_by_call[item.attempt.provider_call_sha256],
            safe_parameters_sha256=item.attempt.safe_parameters_sha256,
            scope_sha256=item.attempt.scope_sha256,
            lifecycle=item.lifecycle,
            outcome=item.outcome,
            route_ids=tuple(sorted(routes[item.attempt.observation_sha256])),
        )
        for item in bundle.observations
    )
    return tuple(sorted(attempts, key=lambda item: item.attempt_receipt_sha256))


def _inventory_sha256(values: tuple[str, ...], *, ordered: bool) -> str:
    materialized = values if ordered else tuple(sorted(values))
    if len(materialized) != len(set(materialized)):
        _fail("Raw persistence inventory repeats one identity")
    return _canonical_sha256(list(materialized))


def _row_inventory_sha256(
    identities: tuple[str, ...],
    rows: tuple[bytes, ...],
) -> str:
    if len(identities) != len(rows):
        _fail("Raw persistence row inventory has a foreign denominator")
    pairs = tuple(sorted(zip(identities, rows, strict=True)))
    if len(pairs) != len({identity for identity, _row in pairs}):
        _fail("Raw persistence row inventory repeats one identity")
    return _canonical_sha256(
        [
            {
                "identity": identity,
                "canonical_row_sha256": hashlib.sha256(row).hexdigest(),
            }
            for identity, row in pairs
        ]
    )


def _expected_raw_persistence_receipt(
    bundle: RawRequestAuthorityBundleV2,
    *,
    replayed: bool,
) -> RawRequestAuthorityPersistenceReceiptV2:
    attempts = _raw_attempts(bundle)
    object_ids = tuple(item.object_sha256 for item in bundle.objects)
    observation_ids = tuple(item.attempt.observation_sha256 for item in bundle.observations)
    occurrence_ids = tuple(item.occurrence_sha256 for item in bundle.occurrences)
    landing_ids = tuple(item.landing_sha256 for item in bundle.landings)
    return RawRequestAuthorityPersistenceReceiptV2(
        bundle_sha256=bundle.bundle_sha256,
        object_count=len(bundle.objects),
        observation_count=len(bundle.observations),
        occurrence_count=len(bundle.occurrences),
        landing_count=len(bundle.landings),
        object_inventory_sha256=_inventory_sha256(object_ids, ordered=False),
        observation_inventory_sha256=_inventory_sha256(observation_ids, ordered=False),
        occurrence_inventory_sha256=_inventory_sha256(occurrence_ids, ordered=False),
        landing_inventory_sha256=_inventory_sha256(landing_ids, ordered=True),
        object_rows_sha256=_row_inventory_sha256(
            object_ids,
            tuple(item.to_canonical_bytes() for item in bundle.objects),
        ),
        observation_rows_sha256=_row_inventory_sha256(
            observation_ids,
            tuple(item.to_canonical_bytes() for item in bundle.observations),
        ),
        occurrence_rows_sha256=_row_inventory_sha256(
            occurrence_ids,
            tuple(item.to_canonical_bytes() for item in bundle.occurrences),
        ),
        landing_rows_sha256=_row_inventory_sha256(
            landing_ids,
            tuple(item.to_canonical_bytes() for item in bundle.landings),
        ),
        attempts=attempts,
        attempt_count=len(attempts),
        attempt_inventory_sha256=_canonical_sha256([item.to_dict() for item in attempts]),
        replayed=replayed,
    )


def _preflight_external_pins(
    candidate: W2SourceCallCandidateV1,
    inputs: W2OperationBuildInputsV1,
) -> None:
    scalar_pins = (
        (candidate.expected_raw_authority_persistence_receipt_sha256, "Raw persistence receipt"),
        (inputs.expected_raw_authority_bundle_sha256, "Raw authority bundle"),
        (
            inputs.expected_body_value_projection_receipt_sha256,
            "body-value projection receipt",
        ),
        (inputs.expected_body_projection_sha256, "body projection"),
        (inputs.expected_ownership_receipt_sha256, "ownership receipt"),
        (inputs.expected_result_cell_authority_sha256, "result-cell authority"),
        (
            inputs.expected_live_lossless_authority_receipt_sha256,
            "live-lossless authority",
        ),
        (inputs.expected_body_blob_inventory_sha256, "body-blob inventory"),
        (
            inputs.expected_body_blob_inventory_readback_receipt_sha256,
            "body-blob readback receipt",
        ),
        (inputs.expected_plan_sha256, "value-projection plan"),
        (
            inputs.expected_route_field_landing_receipt_sha256,
            "route-field landing receipt",
        ),
        (
            inputs.expected_public_table_value_projection_receipt_sha256,
            "public-table projection receipt",
        ),
        (inputs.expected_public_projection_sha256, "public value projection"),
        (
            inputs.expected_value_projection_equality_receipt_sha256,
            "value-projection equality receipt",
        ),
        (inputs.result_cell_schema_sha256, "result-cell schema"),
        (inputs.stats_lossless_schema_sha256, "stats-lossless schema"),
        (inputs.live_lossless_schema_sha256, "live-lossless schema"),
        (inputs.value_representation_schema_sha256, "value-representation schema"),
        (inputs.route_field_landing_schema_sha256, "route-field landing schema"),
        (inputs.expected_w2_operation_schema_sha256, "W2 operation schema"),
    )
    for value, label in scalar_pins:
        _sha256(value, label=f"expected {label}")
    tuple_pins = (
        (
            inputs.expected_committed_staging_readback_sha256s,
            "committed staging readback",
        ),
        (inputs.expected_stats_lossless_authority_sha256s, "stats-lossless authority"),
        (
            inputs.expected_declared_bodyless_packet_authority_sha256s,
            "declared-bodyless packet",
        ),
        (
            inputs.expected_declared_bodyless_readback_receipt_sha256s,
            "declared-bodyless readback",
        ),
        (inputs.expected_route_landing_receipt_sha256s, "route landing receipt"),
        (inputs.expected_canonical_alias_receipt_sha256s, "canonical-alias receipt"),
    )
    for values, label in tuple_pins:
        if type(values) is not tuple or len(values) > MAX_AUTHORITY_ROWS:
            _fail(f"expected {label} pin inventory is foreign or over-bound")
        exact = tuple(
            _sha256(value, label=f"expected {label} pin {ordinal}")
            for ordinal, value in enumerate(values)
        )
        if len(exact) != len(set(exact)):
            _fail(f"expected {label} pin inventory repeats one identity")


def _preflight_raw(
    candidate: W2SourceCallCandidateV1,
) -> tuple[RawRequestAuthorityBundleV2, RawRequestAuthorityPersistenceReceiptV2]:
    pin = _sha256(
        candidate.expected_raw_authority_persistence_receipt_sha256,
        label="expected Raw persistence receipt",
    )
    inputs = candidate.operation_inputs
    if type(inputs.raw_bundle) is not RawRequestAuthorityBundleV2:
        _fail("W2 candidate requires one exact Raw Authority V2 bundle")
    bundle = inputs.raw_bundle
    try:
        exact_bundle = validate_raw_request_authority_bundle(bundle)
    except Exception:
        _fail("W2 candidate Raw Authority V2 bundle failed exact replay")
    if (
        exact_bundle != bundle
        or bundle.bundle_sha256 != inputs.expected_raw_authority_bundle_sha256
    ):
        _fail("W2 candidate Raw bundle differs from its external authority pin")
    receipt = candidate.raw_authority_persistence_receipt
    if type(receipt) is not RawRequestAuthorityPersistenceReceiptV2:
        _fail("W2 candidate has a foreign Raw persistence receipt")
    try:
        exact_receipt = RawRequestAuthorityPersistenceReceiptV2(
            **{item.name: getattr(receipt, item.name) for item in fields(type(receipt))}
        )
        expected_receipt = _expected_raw_persistence_receipt(
            bundle,
            replayed=receipt.replayed,
        )
    except Exception:
        _fail("W2 candidate Raw persistence receipt failed exact replay")
    if (
        exact_receipt != receipt
        or expected_receipt != receipt
        or receipt.receipt_sha256 != pin
        or receipt.bundle_sha256 != bundle.bundle_sha256
    ):
        _fail("W2 candidate Raw persistence receipt differs from exact bundle authority")
    return bundle, exact_receipt


def _preflight_logical_call(
    binding: object,
    bundle: RawRequestAuthorityBundleV2,
) -> LogicalCallReceiptBinding:
    if type(binding) is not LogicalCallReceiptBinding:
        _fail("W2 candidate requires one exact logical-call receipt binding")
    try:
        exact = LogicalCallReceiptBinding(
            **{item.name: getattr(binding, item.name) for item in fields(LogicalCallReceiptBinding)}
        )
    except Exception:
        _fail("W2 candidate logical-call receipt failed exact replay")
    provider_calls = {item.attempt.provider_call_sha256 for item in bundle.observations}
    selected = tuple(item for item in bundle.observations if item.lifecycle == "selected_terminal")
    if len(provider_calls) != 1 or len(selected) != 1:
        _fail("W2 source-call admission requires exactly one completed provider call")
    observation = selected[0]
    try:
        logical_by_provider_call = logical_parameter_digests_by_provider_call(bundle)
    except Exception:
        _fail("W2 candidate logical/provider parameter authority failed exact replay")
    logical_parameters_sha256 = logical_by_provider_call.get(
        observation.attempt.provider_call_sha256
    )
    if logical_parameters_sha256 is None:
        _fail("W2 candidate lacks logical parameter authority for its provider call")
    selected_landings = tuple(
        item
        for item in bundle.landings
        if item.observation_sha256 == observation.attempt.observation_sha256
    )
    route_ids = tuple(item.route_id for item in selected_landings)
    endpoint_names = {item.split(":", 1)[0] for item in route_ids}
    if (
        exact != binding
        or observation.logical_receipt_sha256 != exact.logical_call_receipt_sha256
        or logical_parameters_sha256 != exact.logical_parameters_sha256
        or observation.attempt.provider_authority_sha256 != exact.provider_authority_sha256
        or tuple(sorted(route_ids)) != exact.result_route_ids
        or len(endpoint_names) != 1
        or endpoint_names != {exact.endpoint_name}
        or any(
            item.logical_call_receipt_sha256 != exact.logical_call_receipt_sha256
            or item.logical_parameters_sha256 != exact.logical_parameters_sha256
            or item.provider_authority_sha256 != exact.provider_authority_sha256
            for item in selected_landings
        )
    ):
        _fail("W2 candidate logical-call receipt differs from selected Raw authority")
    return exact


def _preflight_readbacks(
    inputs: W2OperationBuildInputsV1,
    *,
    raw_bundle_sha256: str,
) -> tuple[CommittedStagingFrameReadbackV2, ...]:
    values = inputs.committed_staging_readbacks
    pins = inputs.expected_committed_staging_readback_sha256s
    if (
        type(values) is not tuple
        or type(pins) is not tuple
        or not values
        or len(values) > MAX_AUTHORITY_ROWS
        or len(values) != len(pins)
        or len({id(item) for item in values}) != len(values)
    ):
        _fail("W2 candidate committed staging readback inventory is invalid")
    replayed: list[CommittedStagingFrameReadbackV2] = []
    total_bytes = 0
    for ordinal, (value, raw_pin) in enumerate(zip(values, pins, strict=True)):
        pin = _sha256(raw_pin, label=f"committed staging readback pin {ordinal}")
        if type(value) is not CommittedStagingFrameReadbackV2:
            _fail("W2 candidate committed staging readback has a foreign DTO")
        try:
            receipt = value.committed_receipt
            if type(receipt) is not CommittedStagingChunkReceiptV2:
                _fail("W2 candidate committed staging receipt has a foreign DTO")
            exact_receipt = CommittedStagingChunkReceiptV2(
                **{
                    item.name: getattr(receipt, item.name)
                    for item in fields(CommittedStagingChunkReceiptV2)
                }
            )
            exact = CommittedStagingFrameReadbackV2(
                committed_receipt=exact_receipt,
                canonical_frame_format=value.canonical_frame_format,
                frame_content_hash_contract=value.frame_content_hash_contract,
                frame_schema_hash_contract=value.frame_schema_hash_contract,
                canonical_frame_bytes=value.canonical_frame_bytes,
                canonical_frame_sha256=value.canonical_frame_sha256,
                canonical_frame_size_bytes=value.canonical_frame_size_bytes,
                recomputed_frame_schema_sha256=value.recomputed_frame_schema_sha256,
                recomputed_frame_content_hash=value.recomputed_frame_content_hash,
                recomputed_persisted_content_sha256=(value.recomputed_persisted_content_sha256),
                row_count=value.row_count,
                readback_receipt_sha256=value.readback_receipt_sha256,
            )
        except W2OperationCoordinatorError:
            raise
        except Exception:
            _fail("W2 candidate committed staging readback failed exact replay")
        if exact != value or exact.readback_receipt_sha256 != pin:
            _fail("W2 candidate committed staging readback differs from its external pin")
        total_bytes += exact.canonical_frame_size_bytes
        if total_bytes > _MAX_INT64:
            _fail("W2 candidate committed staging readback bytes exceed the signed bound")
        replayed.append(exact)
    receipt_ids = tuple(item.readback_receipt_sha256 for item in replayed)
    if len(receipt_ids) != len(set(receipt_ids)) or receipt_ids != pins:
        _fail("W2 candidate committed staging readbacks are duplicated or reordered")
    # Constructing the root here proves the coordinator and the child builder
    # use the same exact ordered readback denominator before either store runs.
    w2_committed_staging_readback_root(
        raw_authority_bundle_sha256=raw_bundle_sha256,
        readback_receipt_sha256s=receipt_ids,
    )
    return tuple(replayed)


def _known_secrets(value: object) -> tuple[str | bytes, ...]:
    if type(value) is not tuple or len(value) > _MAX_KNOWN_SECRETS:
        _fail("W2 candidate known-secret inventory is invalid")
    result: list[str | bytes] = []
    for item in value:
        if type(item) is str:
            exact_item: str | bytes = item
            try:
                size = len(exact_item.encode("utf-8", errors="strict"))
            except (UnicodeError, ValueError):
                _fail("W2 candidate known-secret inventory is not exact UTF-8")
        elif type(item) is bytes:
            exact_item = item
            size = len(exact_item)
        else:
            _fail("W2 candidate known-secret inventory has a foreign member")
        if not exact_item or size > _MAX_KNOWN_SECRET_BYTES:
            _fail("W2 candidate known-secret inventory exceeds its byte bound")
        result.append(exact_item)
    return tuple(result)


def _build_operation(inputs: W2OperationBuildInputsV1) -> W2OperationReceiptV1:
    try:
        operation = build_w2_operation(
            inputs.raw_bundle,
            expected_raw_authority_bundle_sha256=inputs.expected_raw_authority_bundle_sha256,
            raw_observations=inputs.raw_observations,
            committed_staging_readbacks=inputs.committed_staging_readbacks,
            expected_committed_staging_readback_sha256s=(
                inputs.expected_committed_staging_readback_sha256s
            ),
            body_value_projection_receipt=inputs.body_value_projection_receipt,
            expected_body_value_projection_receipt_sha256=(
                inputs.expected_body_value_projection_receipt_sha256
            ),
            body_projection=inputs.body_projection,
            expected_body_projection_sha256=inputs.expected_body_projection_sha256,
            body_partitions=inputs.body_partitions,
            body_items=inputs.body_items,
            ownership_receipt=inputs.ownership_receipt,
            expected_ownership_receipt_sha256=inputs.expected_ownership_receipt_sha256,
            expected_unit_inventory=inputs.expected_unit_inventory,
            representation_assignments=inputs.representation_assignments,
            ownership_observations=inputs.ownership_observations,
            ownership_partitions=inputs.ownership_partitions,
            ownership_bindings=inputs.ownership_bindings,
            result_cell_authority_receipt=inputs.result_cell_authority_receipt,
            expected_result_cell_authority_sha256=inputs.expected_result_cell_authority_sha256,
            stats_lossless_authorities=inputs.stats_lossless_authorities,
            expected_stats_lossless_authority_sha256s=(
                inputs.expected_stats_lossless_authority_sha256s
            ),
            live_lossless_authority=inputs.live_lossless_authority,
            expected_live_lossless_authority_receipt_sha256=(
                inputs.expected_live_lossless_authority_receipt_sha256
            ),
            body_blob_inventory=inputs.body_blob_inventory,
            expected_body_blob_inventory_sha256=inputs.expected_body_blob_inventory_sha256,
            body_blob_inventory_readback_receipt=inputs.body_blob_inventory_readback_receipt,
            expected_body_blob_inventory_readback_receipt_sha256=(
                inputs.expected_body_blob_inventory_readback_receipt_sha256
            ),
            declared_bodyless_packets=inputs.declared_bodyless_packets,
            expected_declared_bodyless_packet_authority_sha256s=(
                inputs.expected_declared_bodyless_packet_authority_sha256s
            ),
            declared_bodyless_readback_receipts=inputs.declared_bodyless_readback_receipts,
            expected_declared_bodyless_readback_receipt_sha256s=(
                inputs.expected_declared_bodyless_readback_receipt_sha256s
            ),
            declared_bodyless_packet_bytes=inputs.declared_bodyless_packet_bytes,
            plan=inputs.plan,
            expected_plan_sha256=inputs.expected_plan_sha256,
            route_field_landing_receipt=inputs.route_field_landing_receipt,
            expected_route_field_landing_receipt_sha256=(
                inputs.expected_route_field_landing_receipt_sha256
            ),
            route_landing_receipts=inputs.route_landing_receipts,
            expected_route_landing_receipt_sha256s=(inputs.expected_route_landing_receipt_sha256s),
            canonical_alias_receipts=inputs.canonical_alias_receipts,
            expected_canonical_alias_receipt_sha256s=(
                inputs.expected_canonical_alias_receipt_sha256s
            ),
            route_field_landing_authority_rows=inputs.route_field_landing_authority_rows,
            public_table_value_projection_receipt=(inputs.public_table_value_projection_receipt),
            expected_public_table_value_projection_receipt_sha256=(
                inputs.expected_public_table_value_projection_receipt_sha256
            ),
            public_projection=inputs.public_projection,
            expected_public_projection_sha256=inputs.expected_public_projection_sha256,
            public_partitions=inputs.public_partitions,
            public_items=inputs.public_items,
            value_projection_equality_receipt=inputs.value_projection_equality_receipt,
            expected_value_projection_equality_receipt_sha256=(
                inputs.expected_value_projection_equality_receipt_sha256
            ),
            result_cell_schema_sha256=inputs.result_cell_schema_sha256,
            result_cell_rows=inputs.result_cell_rows,
            stats_lossless_schema_sha256=inputs.stats_lossless_schema_sha256,
            stats_lossless_rows=inputs.stats_lossless_rows,
            live_lossless_schema_sha256=inputs.live_lossless_schema_sha256,
            live_lossless_rows=inputs.live_lossless_rows,
            value_representation_schema_sha256=inputs.value_representation_schema_sha256,
            value_representation_rows=inputs.value_representation_rows,
            route_field_landing_schema_sha256=inputs.route_field_landing_schema_sha256,
            route_field_landing_rows=inputs.route_field_landing_rows,
            expected_w2_operation_schema_sha256=inputs.expected_w2_operation_schema_sha256,
            known_secrets=inputs.known_secrets,
        )
    except Exception:
        _fail("W2 source-call independent reconstruction failed")
    if type(operation) is not W2OperationReceiptV1:
        _fail("W2 source-call builder returned a foreign operation DTO")
    try:
        exact = W2OperationReceiptV1.from_row(
            operation.to_row(),
            expected_operation_receipt_sha256=operation.operation_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        )
    except Exception:
        _fail("W2 source-call operation failed exact semantic replay")
    if exact != operation or exact is operation:
        _fail("W2 source-call operation changed during independent replay")
    return exact


def _exact_public_authority(
    result: object,
    inputs: W2OperationBuildInputsV1,
) -> PublicTableValueProjectionV1:
    if type(result) is not PublicValueAuthorityStoreResult:
        _fail("public-value store returned a foreign result DTO")
    authority = result.authority
    if type(authority) is not PublicTableValueProjectionV1:
        _fail("public-value store returned a foreign projection authority")
    try:
        exact = PublicTableValueProjectionV1(
            receipt=PublicTableValueProjectionReceiptV1.from_row(authority.receipt.to_row()),
            projection=ValueProjectionReceiptV1.from_row(authority.projection.to_row()),
            partitions=tuple(
                ValueProjectionPartitionV1.from_row(item.to_row()) for item in authority.partitions
            ),
            items=tuple(ValueProjectionItemV1.from_row(item.to_row()) for item in authority.items),
        )
    except Exception:
        _fail("public-value store authority failed exact replay")
    if (
        exact != authority
        or authority.receipt != inputs.public_table_value_projection_receipt
        or authority.projection != inputs.public_projection
        or authority.partitions != inputs.public_partitions
        or authority.items != inputs.public_items
        or authority.receipt is inputs.public_table_value_projection_receipt
        or authority.projection is inputs.public_projection
        or any(
            stored is supplied
            for stored, supplied in zip(
                authority.partitions,
                cast("tuple[object, ...]", inputs.public_partitions),
                strict=True,
            )
        )
        or any(
            stored is supplied
            for stored, supplied in zip(
                authority.items,
                cast("tuple[object, ...]", inputs.public_items),
                strict=True,
            )
        )
    ):
        _fail("public-value persisted authority differs from the retained W2 witnesses")
    return exact


def coordinate_w2_source_call(
    candidate: object,
    *,
    public_value_store: object,
    operation_store: object,
) -> W2SourceCallAdmissionV1:
    """Persist and admit one exact already-captured source call.

    A failure after the five public relations commit is intentionally
    orphan-safe: a later call with the byte-identical candidate replays those
    rows and may then persist the operation.  No failure is reported as an
    admission, and no capture/journal state is advanced here.
    """

    if type(candidate) is not W2SourceCallCandidateV1:
        _fail("W2 coordinator requires one exact source-call candidate DTO")
    if type(public_value_store) is not PublicValueAuthorityStore:
        _fail("W2 coordinator requires the exact public-value store")
    if type(operation_store) is not W2OperationStore:
        _fail("W2 coordinator requires the exact operation store")
    if public_value_store._conn is not operation_store._connection:  # noqa: SLF001
        _fail("W2 coordinator stores must share one exact database connection")
    inputs = candidate.operation_inputs
    if type(inputs) is not W2OperationBuildInputsV1:
        _fail("W2 coordinator candidate has foreign build inputs")
    _preflight_external_pins(candidate, inputs)
    _known_secrets(inputs.known_secrets)
    bundle, raw_persistence = _preflight_raw(candidate)
    binding = _preflight_logical_call(candidate.logical_call_binding, bundle)
    readbacks = _preflight_readbacks(inputs, raw_bundle_sha256=bundle.bundle_sha256)
    if inputs.raw_observations != bundle.observations:
        _fail("W2 candidate observation witness differs from its Raw bundle")

    operation = _build_operation(inputs)
    expected_readback_root = w2_committed_staging_readback_root(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        readback_receipt_sha256s=tuple(item.readback_receipt_sha256 for item in readbacks),
    )
    if (
        operation.raw_authority_bundle_sha256 != bundle.bundle_sha256
        or operation.committed_staging_readback_count != len(readbacks)
        or operation.committed_staging_readback_root_sha256 != expected_readback_root
    ):
        _fail("W2 operation differs from the coordinator source/readback authority")

    try:
        public_result = public_value_store.persist_candidate(
            plan=inputs.plan,
            expected_plan_sha256=inputs.expected_plan_sha256,
            expected_raw_authority_bundle_sha256=inputs.expected_raw_authority_bundle_sha256,
            expected_ownership_receipt_sha256=inputs.expected_ownership_receipt_sha256,
            result_cell_schema_sha256=inputs.result_cell_schema_sha256,
            result_cell_rows=inputs.result_cell_rows,
            stats_lossless_schema_sha256=inputs.stats_lossless_schema_sha256,
            stats_lossless_rows=inputs.stats_lossless_rows,
            live_lossless_schema_sha256=inputs.live_lossless_schema_sha256,
            live_lossless_rows=inputs.live_lossless_rows,
            value_representation_schema_sha256=inputs.value_representation_schema_sha256,
            value_representation_rows=inputs.value_representation_rows,
            route_field_landing_schema_sha256=inputs.route_field_landing_schema_sha256,
            route_field_landing_rows=inputs.route_field_landing_rows,
        )
    except Exception:
        _fail("W2 coordinator five-relation public persistence failed")
    public_authority = _exact_public_authority(public_result, inputs)
    if (
        public_authority.receipt.receipt_sha256
        != operation.public_table_value_projection_receipt_sha256
    ):
        _fail("W2 operation differs from the committed public-value authority")

    try:
        persistence = operation_store.persist_operation(
            operation,
            expected_operation_receipt_sha256=operation.operation_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        )
    except Exception:
        _fail("W2 coordinator operation persistence failed")
    if type(persistence) is not W2OperationPersistenceReceiptV1:
        _fail("W2 operation store returned a foreign persistence receipt")
    try:
        exact_persistence = W2OperationPersistenceReceiptV1.from_row(
            persistence.to_row(),
            expected_persistence_receipt_sha256=persistence.persistence_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_operation_receipt_sha256=operation.operation_receipt_sha256,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
            expected_operation_row_sha256=hashlib.sha256(operation.canonical_bytes()).hexdigest(),
        )
    except Exception:
        _fail("W2 operation persistence receipt failed exact replay")
    if exact_persistence != persistence or exact_persistence is persistence:
        _fail("W2 operation persistence receipt changed during exact replay")

    return W2SourceCallAdmissionV1.build(
        logical_call_receipt_sha256=binding.logical_call_receipt_sha256,
        raw_authority_persistence_receipt_sha256=raw_persistence.receipt_sha256,
        operation=operation,
        persistence_receipt=exact_persistence,
    )


def verify_w2_source_call_admission(
    admission: object,
    *,
    expected_admission_sha256: object,
    expected_logical_call_receipt_sha256: object,
    expected_raw_authority_bundle_sha256: object,
    expected_raw_authority_persistence_receipt_sha256: object,
    expected_committed_staging_readback_count: object,
    expected_committed_staging_readback_root_sha256: object,
    expected_operation_key_sha256: object,
    expected_operation_receipt_sha256: object,
    expected_w2_operation_persistence_receipt_sha256: object,
    operation_store: object,
) -> W2SourceCallAdmissionV1:
    """Read-only replay one admission against its exact durable operation row.

    This is the resume/journal seam.  It deliberately delegates table shape,
    key/receipt uniqueness, row decoding, and canonical equality to the store's
    existing readback primitive; callers never duplicate private W2 SQL.  A
    public-value or staging-only candidate cannot pass because the mandatory
    operation row must already be committed and visible in autocommit state.
    """

    if type(admission) is not W2SourceCallAdmissionV1:
        _fail("W2 admission verification requires the exact admission DTO")
    if type(operation_store) is not W2OperationStore:
        _fail("W2 admission verification requires the exact operation store")
    pins = {
        "admission_sha256": _sha256(expected_admission_sha256, label="expected W2 admission"),
        "logical_call_receipt_sha256": _sha256(
            expected_logical_call_receipt_sha256,
            label="expected logical-call receipt",
        ),
        "raw_authority_bundle_sha256": _sha256(
            expected_raw_authority_bundle_sha256,
            label="expected Raw authority bundle",
        ),
        "raw_authority_persistence_receipt_sha256": _sha256(
            expected_raw_authority_persistence_receipt_sha256,
            label="expected Raw persistence receipt",
        ),
        "committed_staging_readback_root_sha256": _sha256(
            expected_committed_staging_readback_root_sha256,
            label="expected committed staging readback root",
        ),
        "operation_key_sha256": _sha256(
            expected_operation_key_sha256,
            label="expected W2 operation key",
        ),
        "operation_receipt_sha256": _sha256(
            expected_operation_receipt_sha256,
            label="expected W2 operation receipt",
        ),
        "w2_operation_persistence_receipt_sha256": _sha256(
            expected_w2_operation_persistence_receipt_sha256,
            label="expected W2 persistence receipt",
        ),
    }
    if (
        type(expected_committed_staging_readback_count) is not int
        or expected_committed_staging_readback_count < 1
        or expected_committed_staging_readback_count > MAX_AUTHORITY_ROWS
    ):
        _fail("expected committed staging readback count is invalid")
    try:
        exact = W2SourceCallAdmissionV1.from_canonical_bytes(admission.canonical_bytes())
    except Exception:
        _fail("W2 admission verification failed exact admission replay")
    if (
        exact != admission
        or exact is admission
        or any(getattr(exact, name) != expected for name, expected in pins.items())
        or exact.committed_staging_readback_count != expected_committed_staging_readback_count
    ):
        _fail("W2 admission differs from its external resume authority pins")
    try:
        # Share the store's writer mutex so the verified row cannot race a
        # repository-sanctioned W2 write on this connection.
        with w2_operation_store_module._WRITE_LOCK:  # noqa: SLF001
            operation_store._require_usable()  # noqa: SLF001
            operation_store._require_no_caller_transaction()  # noqa: SLF001
            row = operation_store._post_commit_readback(  # noqa: SLF001
                operation=exact.operation,
                canonical_operation=exact.operation.canonical_bytes(),
            )
            persistence = operation_store._build_persistence_receipt(  # noqa: SLF001
                operation=exact.operation,
                readback_row=row,
                replayed=exact.persistence_receipt.replayed,
            )
    except Exception:
        _fail("W2 admission durable operation readback failed")
    if persistence != exact.persistence_receipt or persistence is exact.persistence_receipt:
        _fail("W2 admission durable operation receipt differs")
    replay = W2SourceCallAdmissionV1.build(
        logical_call_receipt_sha256=exact.logical_call_receipt_sha256,
        raw_authority_persistence_receipt_sha256=(exact.raw_authority_persistence_receipt_sha256),
        operation=exact.operation,
        persistence_receipt=persistence,
    )
    if replay != exact or replay is exact:
        _fail("W2 admission differs after durable operation replay")
    return replay
