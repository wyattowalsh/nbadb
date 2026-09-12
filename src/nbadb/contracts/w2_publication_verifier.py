"""Pure exact-six publication verification for one W2 Raw bundle.

The verifier consumes only strict public relation rows, one externally pinned
Raw Request Authority V2 bundle, and the externally pinned W2 operation row.
It performs no persistence, staging, parser, extraction, or publication work.
Rows for unrelated bundles may coexist in the supplied table inventories; the
receipt covers exactly the rows whose immutable authorities bind them to the
requested bundle.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Any, ClassVar, Final, Never, Self, cast

from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_COLUMNS,
    LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
    MAX_LIVE_LOSSLESS_RECORDS,
    LiveLosslessNodeRecordV1,
)
from nbadb.contracts.public_table_value_projection import (
    RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
    RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
    RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
)
from nbadb.contracts.public_value_types import (
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.raw_request_authority import (
    MAX_AUTHORITY_ROWS,
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
)
from nbadb.contracts.raw_request_observation_order import (
    canonical_raw_request_observations,
)
from nbadb.contracts.raw_result_cell_authority import (
    RawNbaApiResultCellV2,
    RawResultCellPublicTableProofV2,
    validate_raw_result_cell_public_table,
)
from nbadb.contracts.route_field_landing_authority import (
    MAX_ROUTE_FIELD_LANDING_ROWS,
    RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS,
    RawNbaApiRouteFieldLandingV1,
)
from nbadb.contracts.stats_lossless_value_authority import (
    MAX_STATS_LOSSLESS_RECORDS,
    STATS_LOSSLESS_RECORD_COLUMNS,
    STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
    StatsLosslessRecordV1,
)
from nbadb.contracts.w2_operation import (
    W2OperationKeyV1,
    W2OperationReceiptV1,
)
from nbadb.schemas.raw.nba_api_w2_operation import (
    RAW_NBA_API_W2_OPERATION_COLUMNS,
    RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
)

__all__ = [
    "MAX_W2_PUBLICATION_INPUT_ROWS",
    "W2_PUBLICATION_VERIFICATION_SCHEMA_VERSION",
    "W2PublicationVerificationReceiptV1",
    "W2PublicationVerifierError",
    "verify_w2_publication",
]


W2_PUBLICATION_VERIFICATION_SCHEMA_VERSION: Final = 1
MAX_W2_PUBLICATION_INPUT_ROWS: Final = 14_000_000

_MAX_RESULT_CELL_ROWS: Final = 2_000_000
_MAX_RECEIPT_BYTES: Final = 256 * 1024
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT_KIND: Final = "nbadb_w2_publication_verification_receipt_v1"
_SCHEMA_ROOT_KIND: Final = "nbadb_w2_publication_schema_inventory_v1"
_SELECTED_OBSERVATION_ROOT_KIND: Final = "nbadb_w2_publication_selected_observation_inventory_v1"
_RELATION_INVENTORY_ROOT_KIND: Final = "nbadb_w2_publication_relation_inventory_v1"
_PUBLIC_RELATION_ROOT_KINDS: Final = {
    "result_cell": "nbadb_public_projection_result_cell_rows_v1",
    "stats_lossless": "nbadb_public_projection_stats_lossless_rows_v1",
    "live_lossless": "nbadb_public_projection_live_lossless_rows_v1",
    "value_representation": "nbadb_public_projection_value_representation_rows_v1",
    "route_field_landing": "nbadb_public_projection_route_field_landing_rows_v1",
}
_CANONICAL_RELATION_ORDER: Final = (
    "result_cell",
    "stats_lossless",
    "live_lossless",
    "value_representation",
    "route_field_landing",
    "w2_operation",
)
_RESULT_CELL_COLUMNS: Final = (
    "schema_version",
    *(item.name for item in fields(RawNbaApiResultCellV2)),
)
_VALUE_REPRESENTATION_COLUMNS: Final = (
    "schema_version",
    *(item.name for item in fields(ValueRepresentationAssignmentV1)),
)


class W2PublicationVerifierError(ValueError):
    """One exact-six W2 publication candidate failed closed verification."""


class _InternalVerifierError(Exception):
    """A sanitized verifier-owned failure, never raised across the public API."""


def _fail(message: str) -> Never:
    raise _InternalVerifierError(message) from None


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _count(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{label} must be one bounded exact nonnegative integer")
    return value


def _canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (MemoryError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("W2 publication evidence cannot be canonically encoded")
    if not encoded or len(encoded) > maximum_bytes:
        _fail("W2 publication evidence exceeds its canonical byte bound")
    return encoded


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(value, maximum_bytes=_MAX_RECEIPT_BYTES)
    ).hexdigest()


def _length_framed_root(
    *,
    prefix: bytes,
    kind: str,
    scopes: tuple[str, ...],
    values: tuple[str, ...],
    include_schema_version: bool,
) -> str:
    if type(prefix) is not bytes or not prefix or type(kind) is not str or not kind:
        _fail("W2 publication ordered-root domain is invalid")
    if type(scopes) is not tuple or type(values) is not tuple:
        _fail("W2 publication ordered-root inventory has a foreign exact type")
    if len(values) > MAX_W2_PUBLICATION_INPUT_ROWS:
        _fail("W2 publication ordered-root inventory exceeds its explicit bound")
    digest = hashlib.sha256()
    digest.update(prefix)

    def feed(raw: bytes) -> None:
        digest.update(len(raw).to_bytes(8, "big", signed=False))
        digest.update(raw)

    if include_schema_version:
        feed(b"1")
    feed(kind.encode("utf-8", errors="strict"))
    for scope in scopes:
        feed(_sha256(scope, label="ordered-root scope").encode("ascii"))
    feed(str(len(values)).encode("ascii"))
    for ordinal, value in enumerate(values):
        feed(str(ordinal).encode("ascii"))
        feed(_sha256(value, label="ordered-root item").encode("ascii"))
    return digest.hexdigest()


def _public_relation_root(*, kind: str, bundle: str, values: tuple[str, ...]) -> str:
    """Independently reproduce the frozen public-projection relation root."""

    return _length_framed_root(
        prefix=b"nbadb-public-table-value-projection-root-v1\x00",
        kind=kind,
        scopes=(bundle,),
        values=values,
        include_schema_version=False,
    )


def _evidence_root(*, kind: str, scopes: tuple[str, ...], values: tuple[str, ...]) -> str:
    return _length_framed_root(
        prefix=b"nbadb-w2-publication-verification-root-v1\x00",
        kind=kind,
        scopes=scopes,
        values=values,
        include_schema_version=True,
    )


def _exact_equal(left: object, right: object) -> bool:
    """Compare only exact built-in graphs without invoking caller equality."""

    if type(left) is not type(right):
        return False
    if left is None:
        return True
    if type(left) in {bool, int, float, str, bytes}:
        return bool(left == right)
    if type(left) is tuple:
        left_tuple = left
        right_tuple = cast("tuple[object, ...]", right)
        return len(left_tuple) == len(right_tuple) and all(
            _exact_equal(a, b) for a, b in zip(left_tuple, right_tuple, strict=True)
        )
    if type(left) is list:
        left_list = cast("list[object]", left)
        right_list = cast("list[object]", right)
        return len(left_list) == len(right_list) and all(
            _exact_equal(a, b) for a, b in zip(left_list, right_list, strict=True)
        )
    if type(left) is dict:
        left_map = cast("dict[object, object]", left)
        right_map = cast("dict[object, object]", right)
        if tuple(left_map) != tuple(right_map) or any(type(key) is not str for key in left_map):
            return False
        return all(_exact_equal(left_map[key], right_map[key]) for key in left_map)
    return False


def _strict_inventory(
    value: object,
    *,
    label: str,
    maximum: int,
) -> tuple[object, ...]:
    effective_maximum = min(maximum, MAX_W2_PUBLICATION_INPUT_ROWS)
    if type(value) is not tuple or len(value) > effective_maximum:
        _fail(f"{label} must be one bounded exact tuple")
    return value


def _strict_row_columns(
    value: object,
    *,
    columns: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"{label} lacks its exact ordered columns")
    mapping = cast("dict[object, object]", value)
    if any(type(key) is not str for key in mapping) or tuple(mapping) != columns:
        _fail(f"{label} lacks its exact ordered columns")
    return cast("dict[str, object]", value)


def _replay_dataclass_row(
    value: object,
    *,
    columns: tuple[str, ...],
    row_type: type[object],
    label: str,
) -> object:
    row = _strict_row_columns(value, columns=columns, label=label)
    from_row = cast("Any", row_type).from_row
    rebuilt = from_row(row)
    if type(rebuilt) is not row_type:
        _fail(f"{label} replay returned a foreign exact DTO")
    replayed_row = rebuilt.to_row()  # type: ignore[attr-defined]
    if not _exact_equal(row, replayed_row):
        _fail(f"{label} differs after exact DTO replay")
    return rebuilt


def _replay_raw_bundle(
    raw_bundle: object,
    *,
    expected_bundle_sha256: str,
) -> RawRequestAuthorityBundleV2:
    if type(raw_bundle) is not RawRequestAuthorityBundleV2:
        _fail("W2 publication requires one exact Raw Authority V2 bundle")
    bundle = raw_bundle
    if _sha256(bundle.bundle_sha256, label="Raw Authority V2 bundle") != (expected_bundle_sha256):
        _fail("Raw Authority V2 bundle differs from its external pin")
    inventories = (
        (bundle.objects, ParserInputObjectV2, "parser-input object"),
        (bundle.observations, RequestObservationV2, "request observation"),
        (bundle.occurrences, ResultOccurrenceV2, "result occurrence"),
        (bundle.landings, ObservationRouteLandingV2, "route landing"),
    )
    for inventory, expected_type, label in inventories:
        if (
            type(inventory) is not tuple
            or len(inventory) > MAX_AUTHORITY_ROWS
            or any(type(item) is not expected_type for item in inventory)
        ):
            _fail(f"Raw Authority V2 {label} inventory is foreign or over-bound")
    if any(type(item.attempt) is not RequestAttemptIdentityV2 for item in bundle.observations):
        _fail("Raw Authority V2 request attempt inventory has a foreign exact DTO")

    object_bytes = tuple(item.to_canonical_bytes() for item in bundle.objects)
    observation_bytes = tuple(item.to_canonical_bytes() for item in bundle.observations)
    occurrence_bytes = tuple(item.to_canonical_bytes() for item in bundle.occurrences)
    landing_bytes = tuple(item.to_canonical_bytes() for item in bundle.landings)
    rebuilt = RawRequestAuthorityBundleV2.build(
        objects=tuple(ParserInputObjectV2.from_canonical_bytes(item) for item in object_bytes),
        observations=tuple(
            RequestObservationV2.from_canonical_bytes(item) for item in observation_bytes
        ),
        occurrences=tuple(
            ResultOccurrenceV2.from_canonical_bytes(item) for item in occurrence_bytes
        ),
        landings=tuple(
            ObservationRouteLandingV2.from_canonical_bytes(item) for item in landing_bytes
        ),
    )
    if type(rebuilt) is not RawRequestAuthorityBundleV2 or (
        rebuilt.bundle_sha256 != expected_bundle_sha256
    ):
        _fail("Raw Authority V2 replay differs from its external bundle pin")
    rebuilt_bytes = (
        tuple(item.to_canonical_bytes() for item in rebuilt.objects),
        tuple(item.to_canonical_bytes() for item in rebuilt.observations),
        tuple(item.to_canonical_bytes() for item in rebuilt.occurrences),
        tuple(item.to_canonical_bytes() for item in rebuilt.landings),
    )
    if rebuilt_bytes != (
        object_bytes,
        observation_bytes,
        occurrence_bytes,
        landing_bytes,
    ):
        _fail("Raw Authority V2 canonical replay drifted")
    rebuilt.require_complete_terminal_selection()
    return rebuilt


def _canonical_timestamp(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is not UTC:
        _fail("W2 publication live snapshot authority is not exact UTC")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _raw_observation_order_key(observation: RequestObservationV2) -> tuple[object, ...]:
    attempt = observation.attempt
    page_discriminator = 0 if attempt.page_ordinal is None else 1
    page_ordinal = 0 if attempt.page_ordinal is None else attempt.page_ordinal
    return (
        attempt.logical_invocation_sha256,
        attempt.semantic_request_sha256,
        attempt.provider_call_ordinal,
        page_discriminator,
        page_ordinal,
        attempt.provider_call_role,
        attempt.provider_call_sha256,
        attempt.retry_ordinal,
        attempt.request_ordinal,
        attempt.observation_sha256,
    )


@dataclass(frozen=True, slots=True)
class W2PublicationVerificationReceiptV1:
    """Bounded evidence that one bundle's exact six public rows close."""

    verification_receipt_sha256: str
    raw_authority_bundle_sha256: str
    operation_key_sha256: str
    operation_receipt_sha256: str
    schema_inventory_sha256: str
    selected_observation_count: int
    selected_observation_root_sha256: str
    result_cell_schema_sha256: str
    result_cell_row_count: int
    result_cell_row_root_sha256: str
    stats_lossless_schema_sha256: str
    stats_lossless_row_count: int
    stats_lossless_row_root_sha256: str
    live_lossless_schema_sha256: str
    live_lossless_row_count: int
    live_lossless_row_root_sha256: str
    value_representation_schema_sha256: str
    value_representation_row_count: int
    value_representation_row_root_sha256: str
    route_field_landing_schema_sha256: str
    route_field_landing_row_count: int
    route_field_landing_row_root_sha256: str
    w2_operation_schema_sha256: str
    w2_operation_row_count: int
    relation_row_count: int
    publication_row_count: int
    relation_inventory_sha256: str

    schema_version: ClassVar[int] = W2_PUBLICATION_VERIFICATION_SCHEMA_VERSION
    kind: ClassVar[str] = _RECEIPT_KIND

    def __post_init__(self) -> None:
        try:
            for item in fields(self):
                value = getattr(self, item.name)
                if item.name.endswith("_sha256"):
                    _sha256(value, label=item.name)
                elif item.name.endswith("_count"):
                    _count(
                        value,
                        label=item.name,
                        maximum=MAX_W2_PUBLICATION_INPUT_ROWS,
                    )
            if self.w2_operation_row_count != 1:
                _fail("W2 publication receipt requires exactly one operation row")
            relation_count = (
                self.result_cell_row_count
                + self.stats_lossless_row_count
                + self.live_lossless_row_count
                + self.value_representation_row_count
                + self.route_field_landing_row_count
            )
            if (
                self.relation_row_count != relation_count
                or self.publication_row_count != relation_count + self.w2_operation_row_count
            ):
                _fail("W2 publication receipt row-count algebra is inconsistent")
            expected_schemas = (
                (self.result_cell_schema_sha256, RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256),
                (self.stats_lossless_schema_sha256, STATS_LOSSLESS_RECORD_SCHEMA_SHA256),
                (self.live_lossless_schema_sha256, LIVE_LOSSLESS_NODE_SCHEMA_SHA256),
                (
                    self.value_representation_schema_sha256,
                    RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
                ),
                (
                    self.route_field_landing_schema_sha256,
                    RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
                ),
                (self.w2_operation_schema_sha256, RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256),
            )
            if any(actual != expected for actual, expected in expected_schemas):
                _fail("W2 publication receipt schema inventory differs from exact-six authority")
            if self.verification_receipt_sha256 != _canonical_sha256(self.identity_payload()):
                _fail("W2 publication receipt digest differs from its exact evidence")
        except _InternalVerifierError as exc:
            raise W2PublicationVerifierError(str(exc)) from None

    @classmethod
    def build(cls, **values: object) -> Self:
        if cls is not W2PublicationVerificationReceiptV1:
            raise W2PublicationVerifierError(
                "W2 publication receipt builder requires its exact DTO type"
            ) from None
        expected = {item.name for item in fields(cls) if item.name != "verification_receipt_sha256"}
        if any(type(name) is not str for name in values) or set(values) != expected:
            raise W2PublicationVerifierError(
                "W2 publication receipt fields are missing or additive"
            ) from None
        payload = {"schema_version": cls.schema_version, "kind": cls.kind, **values}
        try:
            return cls(
                verification_receipt_sha256=_canonical_sha256(payload),
                **cast("Any", values),
            )
        except W2PublicationVerifierError:
            raise
        except Exception:
            raise W2PublicationVerifierError(
                "W2 publication receipt failed exact construction"
            ) from None

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "verification_receipt_sha256"
            },
        }

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        if cls is not W2PublicationVerificationReceiptV1 or type(value) is not dict:
            raise W2PublicationVerifierError(
                "W2 publication receipt row has a foreign exact type"
            ) from None
        row = cast("dict[object, object]", value)
        expected = ("schema_version", *(item.name for item in fields(cls)))
        if any(type(key) is not str for key in row) or tuple(row) != expected:
            raise W2PublicationVerifierError(
                "W2 publication receipt row has a foreign ordered shape"
            ) from None
        if type(row["schema_version"]) is not int or row["schema_version"] != (cls.schema_version):
            raise W2PublicationVerifierError(
                "W2 publication receipt row schema version is invalid"
            ) from None
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except W2PublicationVerifierError:
            raise
        except Exception:
            raise W2PublicationVerifierError(
                "W2 publication receipt row failed exact replay"
            ) from None

    def canonical_bytes(self) -> bytes:
        try:
            return _canonical_json_bytes(self.to_row(), maximum_bytes=_MAX_RECEIPT_BYTES)
        except _InternalVerifierError as exc:
            raise W2PublicationVerifierError(str(exc)) from None


def _verify_w2_publication(
    *,
    raw_authority_bundle: object,
    expected_raw_authority_bundle_sha256: object,
    result_cell_rows: object,
    expected_result_cell_schema_sha256: object,
    stats_lossless_rows: object,
    expected_stats_lossless_schema_sha256: object,
    live_lossless_rows: object,
    expected_live_lossless_schema_sha256: object,
    value_representation_rows: object,
    expected_value_representation_schema_sha256: object,
    route_field_landing_rows: object,
    expected_route_field_landing_schema_sha256: object,
    w2_operation_rows: object,
    expected_w2_operation_schema_sha256: object,
    expected_operation_key_sha256: object,
    expected_operation_receipt_sha256: object,
) -> W2PublicationVerificationReceiptV1:
    # External authorities are all pinned before any caller-controlled inventory
    # or Raw bundle child is traversed.
    bundle_pin = _sha256(
        expected_raw_authority_bundle_sha256,
        label="expected Raw Authority V2 bundle",
    )
    result_schema = _sha256(
        expected_result_cell_schema_sha256,
        label="expected result-cell schema",
    )
    stats_schema = _sha256(
        expected_stats_lossless_schema_sha256,
        label="expected stats-lossless schema",
    )
    live_schema = _sha256(
        expected_live_lossless_schema_sha256,
        label="expected live-lossless schema",
    )
    assignment_schema = _sha256(
        expected_value_representation_schema_sha256,
        label="expected value-representation schema",
    )
    route_schema = _sha256(
        expected_route_field_landing_schema_sha256,
        label="expected route-field landing schema",
    )
    operation_schema = _sha256(
        expected_w2_operation_schema_sha256,
        label="expected W2 operation schema",
    )
    operation_key_pin = _sha256(
        expected_operation_key_sha256,
        label="expected W2 operation key",
    )
    operation_receipt_pin = _sha256(
        expected_operation_receipt_sha256,
        label="expected W2 operation receipt",
    )
    exact_schemas = (
        (result_schema, RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256),
        (stats_schema, STATS_LOSSLESS_RECORD_SCHEMA_SHA256),
        (live_schema, LIVE_LOSSLESS_NODE_SCHEMA_SHA256),
        (assignment_schema, RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256),
        (route_schema, RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256),
        (operation_schema, RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256),
    )
    if any(actual != expected for actual, expected in exact_schemas):
        _fail("W2 publication schema pins differ from the exact-six schema authority")

    raw_result_rows = _strict_inventory(
        result_cell_rows,
        label="result-cell row inventory",
        maximum=_MAX_RESULT_CELL_ROWS,
    )
    raw_stats_rows = _strict_inventory(
        stats_lossless_rows,
        label="stats-lossless row inventory",
        maximum=MAX_STATS_LOSSLESS_RECORDS,
    )
    raw_live_rows = _strict_inventory(
        live_lossless_rows,
        label="live-lossless row inventory",
        maximum=MAX_LIVE_LOSSLESS_RECORDS,
    )
    raw_assignment_rows = _strict_inventory(
        value_representation_rows,
        label="value-representation row inventory",
        maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    )
    raw_route_rows = _strict_inventory(
        route_field_landing_rows,
        label="route-field landing row inventory",
        maximum=MAX_ROUTE_FIELD_LANDING_ROWS,
    )
    raw_operation_rows = _strict_inventory(
        w2_operation_rows,
        label="W2 operation row inventory",
        maximum=MAX_W2_PUBLICATION_INPUT_ROWS,
    )

    bundle = _replay_raw_bundle(
        raw_authority_bundle,
        expected_bundle_sha256=bundle_pin,
    )
    selected = canonical_raw_request_observations(
        bundle.observations,
        selection="selected_terminal",
    )
    expected_selected_ids = {
        item.attempt.observation_sha256
        for item in bundle.observations
        if item.lifecycle == "selected_terminal"
    }
    if (
        type(selected) is not tuple
        or not selected
        or any(
            type(item) is not RequestObservationV2 or item.lifecycle != "selected_terminal"
            for item in selected
        )
        or {item.attempt.observation_sha256 for item in selected} != expected_selected_ids
        or tuple(_raw_observation_order_key(item) for item in selected)
        != tuple(sorted(_raw_observation_order_key(item) for item in selected))
    ):
        _fail("W2 publication selected terminal observation inventory is invalid")
    selected_by_sha = {item.attempt.observation_sha256: item for item in selected}
    if len(selected_by_sha) != len(selected):
        _fail("W2 publication selected observation inventory repeats one identity")
    selected_order = {
        item.attempt.observation_sha256: ordinal for ordinal, item in enumerate(selected)
    }
    all_observation_ids = {item.attempt.observation_sha256 for item in bundle.observations}
    all_occurrence_by_sha = {item.occurrence_sha256: item for item in bundle.occurrences}
    if len(all_occurrence_by_sha) != len(bundle.occurrences):
        _fail("W2 publication Raw occurrence inventory repeats one identity")
    selected_occurrences = tuple(
        item for item in bundle.occurrences if item.observation_sha256 in selected_by_sha
    )
    selected_occurrence_by_sha = {item.occurrence_sha256: item for item in selected_occurrences}
    objects_by_sha = {item.object_sha256: item for item in bundle.objects}
    if len(objects_by_sha) != len(bundle.objects):
        _fail("W2 publication parser-input inventory repeats one identity")
    raw_landing_by_sha = {item.landing_sha256: item for item in bundle.landings}
    if len(raw_landing_by_sha) != len(bundle.landings):
        _fail("W2 publication Raw route inventory repeats one identity")
    selected_raw_landings = tuple(
        item for item in bundle.landings if item.observation_sha256 in selected_by_sha
    )
    raw_landing_by_observation_route: dict[tuple[str, str], ObservationRouteLandingV2] = {}
    live_snapshot_by_observation: dict[str, str] = {}
    for item in selected_raw_landings:
        landing_key = (item.observation_sha256, item.route_id)
        if landing_key in raw_landing_by_observation_route:
            _fail("W2 publication Raw route inventory repeats one observation route")
        raw_landing_by_observation_route[landing_key] = item
        if item.live_snapshot_at is not None:
            snapshot = _canonical_timestamp(item.live_snapshot_at)
            prior_snapshot = live_snapshot_by_observation.setdefault(
                item.observation_sha256,
                snapshot,
            )
            if prior_snapshot != snapshot:
                _fail("W2 publication live observation has inconsistent snapshot authority")

    exact_result_rows = tuple(
        cast(
            "RawNbaApiResultCellV2",
            _replay_dataclass_row(
                row,
                columns=_RESULT_CELL_COLUMNS,
                row_type=RawNbaApiResultCellV2,
                label="result-cell row",
            ),
        )
        for row in raw_result_rows
    )
    target_result_rows: list[RawNbaApiResultCellV2] = []
    for row in exact_result_rows:
        touches_bundle = (
            row.observation_sha256 in all_observation_ids
            or row.occurrence_sha256 in all_occurrence_by_sha
        )
        if not touches_bundle:
            continue
        occurrence = selected_occurrence_by_sha.get(row.occurrence_sha256)
        if (
            row.observation_sha256 not in selected_by_sha
            or occurrence is None
            or occurrence.observation_sha256 != row.observation_sha256
        ):
            _fail("result-cell row has nonterminal or cross-observation bundle membership")
        target_result_rows.append(row)
    result_proof = validate_raw_result_cell_public_table(
        observations=selected,
        occurrences=selected_occurrences,
        cells=tuple(target_result_rows),
    )
    if (
        type(result_proof) is not RawResultCellPublicTableProofV2
        or type(result_proof.cells) is not tuple
        or tuple(item.cell_sha256 for item in result_proof.cells)
        != tuple(item.cell_sha256 for item in target_result_rows)
    ):
        _fail("result-cell authority differs after exact Raw ownership replay")

    exact_stats_rows = tuple(
        cast(
            "StatsLosslessRecordV1",
            _replay_dataclass_row(
                row,
                columns=STATS_LOSSLESS_RECORD_COLUMNS,
                row_type=StatsLosslessRecordV1,
                label="stats-lossless row",
            ),
        )
        for row in raw_stats_rows
    )
    target_stats_rows: list[StatsLosslessRecordV1] = []
    for row in exact_stats_rows:
        touches_bundle = row.raw_authority_bundle_sha256 == bundle_pin
        if not touches_bundle and (
            row.observation_sha256 in all_observation_ids
            or row.occurrence_sha256 in all_occurrence_by_sha
        ):
            _fail("stats-lossless row crosses its explicit Raw bundle authority")
        if touches_bundle:
            target_stats_rows.append(row)

    next_stats_global: dict[str, int] = {}
    next_stats_occurrence: dict[str, int] = {}
    next_stats_residual: dict[str, int] = {}
    seen_stats_ids: set[str] = set()
    previous_stats_observation = -1
    for row in target_stats_rows:
        observation = selected_by_sha.get(row.observation_sha256)
        if observation is None or observation.attempt.source_family != "stats":
            _fail("stats-lossless row references a nonterminal or foreign-family observation")
        observation_position = selected_order[row.observation_sha256]
        if observation_position < previous_stats_observation:
            _fail("stats-lossless rows are not in canonical observation order")
        previous_stats_observation = observation_position
        expected_global = next_stats_global.get(row.observation_sha256, 0)
        if row.global_record_ordinal != expected_global:
            _fail("stats-lossless record ordinals are not canonical and contiguous")
        next_stats_global[row.observation_sha256] = expected_global + 1
        if row.record_sha256 in seen_stats_ids:
            _fail("stats-lossless rows contain a duplicate record identity")
        seen_stats_ids.add(row.record_sha256)
        attempt = observation.attempt
        body_object = (
            None
            if observation.body_object_sha256 is None
            else objects_by_sha.get(observation.body_object_sha256)
        )
        raw_landing = raw_landing_by_observation_route.get((row.observation_sha256, row.route_id))
        if (
            row.observation_record_sha256 != observation.observation_record_sha256
            or row.provider_authority_sha256 != attempt.provider_authority_sha256
            or row.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
            or row.parameters_sha256 != attempt.safe_parameters_sha256
            or row.endpoint_id != attempt.endpoint_id
            or body_object is None
            or row.parser_input_sha256 != body_object.response_sha256
            or observation.capture_response_receipt_sha256 is None
            or row.response_receipt_sha256 != observation.capture_response_receipt_sha256
            or raw_landing is None
            or row.route_authority_sha256 != raw_landing.route_authority_sha256
            or row.committed_receipt_sha256 != raw_landing.receipt_root_sha256
        ):
            _fail("stats-lossless row differs from exact Raw observation authority")
        if row.owner_kind == "result_occurrence":
            occurrence = selected_occurrence_by_sha.get(cast("str", row.occurrence_sha256))
            if occurrence is None or occurrence.observation_sha256 != row.observation_sha256:
                _fail("stats-lossless row references a missing or cross-observation occurrence")
            expected_occurrence_ordinal = next_stats_occurrence.get(
                occurrence.occurrence_sha256,
                0,
            )
            if row.occurrence_record_ordinal != expected_occurrence_ordinal:
                _fail("stats-lossless occurrence record ordinals are not contiguous")
            next_stats_occurrence[occurrence.occurrence_sha256] = expected_occurrence_ordinal + 1
        else:
            expected_residual_ordinal = next_stats_residual.get(row.observation_sha256, 0)
            if row.response_record_ordinal != expected_residual_ordinal:
                _fail("stats-lossless residual record ordinals are not contiguous")
            next_stats_residual[row.observation_sha256] = expected_residual_ordinal + 1

    exact_live_rows = tuple(
        cast(
            "LiveLosslessNodeRecordV1",
            _replay_dataclass_row(
                row,
                columns=LIVE_LOSSLESS_NODE_COLUMNS,
                row_type=LiveLosslessNodeRecordV1,
                label="live-lossless row",
            ),
        )
        for row in raw_live_rows
    )
    target_live_rows: list[LiveLosslessNodeRecordV1] = []
    for row in exact_live_rows:
        touches_bundle = row.raw_authority_bundle_sha256 == bundle_pin
        if not touches_bundle and (
            row.observation_sha256 in all_observation_ids
            or row.raw_occurrence_sha256 in all_occurrence_by_sha
        ):
            _fail("live-lossless row crosses its explicit Raw bundle authority")
        if touches_bundle:
            target_live_rows.append(row)

    live_selected = tuple(item for item in selected if item.attempt.source_family == "live")
    live_observation_order = {
        item.attempt.observation_sha256: ordinal for ordinal, item in enumerate(live_selected)
    }
    next_live_observation_record: dict[str, int] = {}
    seen_live_ids: set[str] = set()
    for expected_global, row in enumerate(target_live_rows):
        observation = selected_by_sha.get(row.observation_sha256)
        if observation is None or observation.attempt.source_family != "live":
            _fail("live-lossless row references a nonterminal or foreign-family observation")
        attempt = observation.attempt
        expected_observation_ordinal = live_observation_order.get(row.observation_sha256)
        expected_local = next_live_observation_record.get(row.observation_sha256, 0)
        if (
            row.global_record_ordinal != expected_global
            or row.observation_ordinal != expected_observation_ordinal
            or row.observation_record_ordinal != expected_local
        ):
            _fail("live-lossless rows are not in canonical record order")
        next_live_observation_record[row.observation_sha256] = expected_local + 1
        if row.record_sha256 in seen_live_ids:
            _fail("live-lossless rows contain a duplicate record identity")
        seen_live_ids.add(row.record_sha256)
        body_object = (
            None
            if observation.body_object_sha256 is None
            else objects_by_sha.get(observation.body_object_sha256)
        )
        snapshot = live_snapshot_by_observation.get(row.observation_sha256)
        if (
            row.observation_record_sha256 != observation.observation_record_sha256
            or row.attempt_sha256 != attempt.attempt_sha256
            or row.semantic_request_sha256 != attempt.semantic_request_sha256
            or row.logical_invocation_sha256 != attempt.logical_invocation_sha256
            or row.provider_call_sha256 != attempt.provider_call_sha256
            or row.request_surface_sha256 != attempt.request_surface_sha256
            or row.runtime_contract_sha256 != attempt.runtime_contract_sha256
            or row.provider_authority_sha256 != attempt.provider_authority_sha256
            or row.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
            or row.source_sha != attempt.source_sha
            or row.run_id != attempt.run_id
            or row.run_attempt != attempt.run_attempt
            or row.chain_id != attempt.chain_id
            or row.lane_id != attempt.lane_id
            or row.endpoint_id != attempt.endpoint_id
            or row.provider_call_ordinal != attempt.provider_call_ordinal
            or row.page_ordinal != attempt.page_ordinal
            or row.provider_call_role != attempt.provider_call_role
            or row.retry_ordinal != attempt.retry_ordinal
            or row.request_ordinal != attempt.request_ordinal
            or body_object is None
            or row.parser_input_sha256 != body_object.response_sha256
            or row.parser_input_length != body_object.uncompressed_bytes
            or observation.capture_response_receipt_sha256 is None
            or row.capture_response_receipt_sha256 != observation.capture_response_receipt_sha256
            or row.route_landings_sha256 != observation.route_landings_sha256
            or row.raw_result_occurrences_sha256 != observation.result_occurrences_sha256
            or snapshot is None
            or row.live_snapshot_at != snapshot
        ):
            _fail("live-lossless row differs from exact Raw observation authority")
        if row.raw_occurrence_sha256 is not None:
            occurrence = selected_occurrence_by_sha.get(row.raw_occurrence_sha256)
            if (
                occurrence is None
                or occurrence.observation_sha256 != row.observation_sha256
                or row.ownership_occurrence_ordinal != occurrence.occurrence_ordinal
            ):
                _fail("live-lossless row references a missing or cross-observation occurrence")

    exact_assignment_rows = tuple(
        cast(
            "ValueRepresentationAssignmentV1",
            _replay_dataclass_row(
                row,
                columns=_VALUE_REPRESENTATION_COLUMNS,
                row_type=ValueRepresentationAssignmentV1,
                label="value-representation row",
            ),
        )
        for row in raw_assignment_rows
    )
    target_assignments = tuple(
        row for row in exact_assignment_rows if row.raw_authority_bundle_sha256 == bundle_pin
    )
    assignment_by_sha: dict[str, ValueRepresentationAssignmentV1] = {}
    assignment_by_unit: dict[str, ValueRepresentationAssignmentV1] = {}
    for ordinal, row in enumerate(target_assignments):
        if (
            row.unit_ordinal != ordinal
            or row.assignment_sha256 in assignment_by_sha
            or row.unit_sha256 in assignment_by_unit
        ):
            _fail("value-representation rows are reordered, sparse, or duplicated")
        assignment_by_sha[row.assignment_sha256] = row
        assignment_by_unit[row.unit_sha256] = row
    for row in exact_assignment_rows:
        if row.raw_authority_bundle_sha256 != bundle_pin and (
            row.assignment_sha256 in assignment_by_sha or row.unit_sha256 in assignment_by_unit
        ):
            _fail("value-representation row crosses its explicit Raw bundle authority")

    exact_route_rows = tuple(
        cast(
            "RawNbaApiRouteFieldLandingV1",
            _replay_dataclass_row(
                row,
                columns=RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS,
                row_type=RawNbaApiRouteFieldLandingV1,
                label="route-field landing row",
            ),
        )
        for row in raw_route_rows
    )
    target_route_rows = tuple(
        row for row in exact_route_rows if row.raw_authority_bundle_sha256 == bundle_pin
    )
    seen_route_ids: set[str] = set()
    seen_route_semantics: set[tuple[object, ...]] = set()
    covered_assignments: set[str] = set()
    covered_observations: set[str] = set()
    for ordinal, row in enumerate(target_route_rows):
        semantic_key = (
            row.route_landing_receipt_sha256,
            row.raw_route_landing_sha256,
            row.unit_sha256,
            row.row_kind,
            row.field_ordinal,
        )
        if (
            row.landing_field_ordinal != ordinal
            or row.landing_field_sha256 in seen_route_ids
            or semantic_key in seen_route_semantics
        ):
            _fail("route-field landing rows are reordered, sparse, or duplicated")
        seen_route_ids.add(row.landing_field_sha256)
        seen_route_semantics.add(semantic_key)
        observation = selected_by_sha.get(row.observation_sha256)
        raw_landing = raw_landing_by_sha.get(row.raw_route_landing_sha256)
        assignment = assignment_by_sha.get(row.assignment_sha256)
        if (
            observation is None
            or raw_landing is None
            or raw_landing.observation_sha256 != row.observation_sha256
            or raw_landing.route_ordinal != row.route_ordinal
            or raw_landing.route_id != row.route_id
            or raw_landing.staging_key != row.staging_key
            or assignment is None
            or assignment.unit_sha256 != row.unit_sha256
            or assignment.unit_ordinal != row.unit_ordinal
            or assignment.source_input_kind != row.source_input_kind
            or assignment.representation_kind != row.representation_kind
        ):
            _fail("route-field landing row differs from Raw route or assignment authority")
        if row.unit_kind == "result_occurrence":
            occurrence = selected_occurrence_by_sha.get(cast("str", row.occurrence_sha256))
            if (
                occurrence is None
                or occurrence.observation_sha256 != row.observation_sha256
                or row.occurrence_ordinal != occurrence.occurrence_ordinal
            ):
                _fail("route-field landing references a missing or cross-observation occurrence")
        covered_assignments.add(row.assignment_sha256)
        covered_observations.add(row.observation_sha256)
    if covered_assignments != set(assignment_by_sha):
        _fail("route-field landing rows do not cover the exact assignment denominator")
    if covered_observations != set(selected_by_sha):
        _fail("route-field landing rows do not cover the selected observation denominator")
    for row in exact_route_rows:
        if row.raw_authority_bundle_sha256 != bundle_pin and (
            row.observation_sha256 in all_observation_ids
            or row.raw_route_landing_sha256 in raw_landing_by_sha
            or row.occurrence_sha256 in all_occurrence_by_sha
            or row.assignment_sha256 in assignment_by_sha
            or row.unit_sha256 in assignment_by_unit
        ):
            _fail("route-field landing row crosses its explicit Raw bundle authority")

    route_bindings = {
        (
            row.observation_sha256,
            row.occurrence_sha256,
            row.route_id,
            row.representation_kind,
        )
        for row in target_route_rows
    }
    result_route_bindings = {
        (observation_sha256, occurrence_sha256, representation_kind)
        for (
            observation_sha256,
            occurrence_sha256,
            _route_id,
            representation_kind,
        ) in route_bindings
    }
    for row in target_result_rows:
        if (
            row.observation_sha256,
            row.occurrence_sha256,
            "rectangular_result_cells_v1",
        ) not in result_route_bindings:
            _fail("result-cell row lacks an exact route-representation binding")
    for row in target_stats_rows:
        representation = (
            "stats_lossless_records_v1"
            if row.owner_kind == "result_occurrence"
            else "response_lossless_records_v1"
        )
        if (
            row.observation_sha256,
            row.occurrence_sha256,
            row.route_id,
            representation,
        ) not in route_bindings:
            _fail("stats-lossless row lacks an exact route-representation binding")
    for row in target_live_rows:
        assignment = assignment_by_sha.get(row.representation_assignment_sha256)
        if (
            assignment is None
            or assignment.unit_sha256 != row.expected_unit_sha256
            or assignment.unit_ordinal != row.expected_unit_ordinal
            or assignment.source_input_kind != row.source_input_kind
            or assignment.representation_kind != row.representation_kind
            or assignment.assignment_sha256 not in covered_assignments
        ):
            _fail("live-lossless row lacks an exact assignment and route binding")

    exact_operations: list[W2OperationReceiptV1] = []
    for raw_row in raw_operation_rows:
        row = _strict_row_columns(
            raw_row,
            columns=RAW_NBA_API_W2_OPERATION_COLUMNS,
            label="W2 operation row",
        )
        row_receipt = _sha256(
            row["operation_receipt_sha256"],
            label="candidate W2 operation receipt",
        )
        row_key = _sha256(
            row["operation_key_sha256"],
            label="candidate W2 operation key",
        )
        row_bundle = _sha256(
            row["raw_authority_bundle_sha256"],
            label="candidate W2 operation Raw bundle",
        )
        row_schema = _sha256(
            row["w2_operation_schema_sha256"],
            label="candidate W2 operation schema",
        )
        rebuilt = W2OperationReceiptV1.from_row(
            row,
            expected_operation_receipt_sha256=row_receipt,
            expected_operation_key_sha256=row_key,
            expected_raw_authority_bundle_sha256=row_bundle,
            expected_w2_operation_schema_sha256=row_schema,
        )
        if type(rebuilt) is not W2OperationReceiptV1 or not _exact_equal(
            row,
            rebuilt.to_row(),
        ):
            _fail("W2 operation row differs after exact DTO replay")
        touches_target = (
            row_bundle == bundle_pin
            or row_key == operation_key_pin
            or row_receipt == operation_receipt_pin
        )
        exact_target = (
            row_bundle == bundle_pin
            and row_key == operation_key_pin
            and row_receipt == operation_receipt_pin
            and row_schema == operation_schema
        )
        if touches_target and not exact_target:
            _fail("W2 operation row crosses its external bundle, key, or receipt pins")
        if exact_target:
            exact_operations.append(rebuilt)
    if len(exact_operations) != 1:
        _fail("W2 publication requires exactly one externally pinned operation row")
    operation = exact_operations[0]
    operation_key = W2OperationKeyV1.build(bundle.observations)
    if (
        type(operation_key) is not W2OperationKeyV1
        or operation_key.operation_key_sha256 != operation_key_pin
        or operation.operation_attempt_count != operation_key.operation_attempt_count
        or operation.operation_attempt_root_sha256 != operation_key.operation_attempt_root_sha256
    ):
        _fail("W2 operation key differs from the exact Raw attempt authority")

    relation_identities = {
        "result_cell": tuple(item.cell_sha256 for item in target_result_rows),
        "stats_lossless": tuple(item.record_sha256 for item in target_stats_rows),
        "live_lossless": tuple(item.record_sha256 for item in target_live_rows),
        "value_representation": tuple(item.assignment_sha256 for item in target_assignments),
        "route_field_landing": tuple(item.landing_field_sha256 for item in target_route_rows),
    }
    relation_roots = {
        name: _public_relation_root(
            kind=_PUBLIC_RELATION_ROOT_KINDS[name],
            bundle=bundle_pin,
            values=identities,
        )
        for name, identities in relation_identities.items()
    }
    operation_relation_fields = (
        (
            "result_cell",
            "result_cell_schema_sha256",
            "result_cell_row_count",
            "result_cell_row_root_sha256",
            result_schema,
        ),
        (
            "stats_lossless",
            "stats_lossless_schema_sha256",
            "stats_lossless_row_count",
            "stats_lossless_row_root_sha256",
            stats_schema,
        ),
        (
            "live_lossless",
            "live_lossless_schema_sha256",
            "live_lossless_row_count",
            "live_lossless_row_root_sha256",
            live_schema,
        ),
        (
            "value_representation",
            "value_representation_schema_sha256",
            "value_representation_row_count",
            "value_representation_row_root_sha256",
            assignment_schema,
        ),
        (
            "route_field_landing",
            "route_field_landing_schema_sha256",
            "route_field_landing_row_count",
            "route_field_landing_row_root_sha256",
            route_schema,
        ),
    )
    for name, schema_field, count_field, root_field, expected_schema in operation_relation_fields:
        if (
            getattr(operation, schema_field) != expected_schema
            or getattr(operation, count_field) != len(relation_identities[name])
            or getattr(operation, root_field) != relation_roots[name]
        ):
            _fail("W2 operation relation count, root, or schema differs from exact rows")

    schema_by_relation = {
        "result_cell": result_schema,
        "stats_lossless": stats_schema,
        "live_lossless": live_schema,
        "value_representation": assignment_schema,
        "route_field_landing": route_schema,
        "w2_operation": operation_schema,
    }
    schema_inventory = tuple(schema_by_relation[name] for name in _CANONICAL_RELATION_ORDER)
    schema_inventory_sha256 = _evidence_root(
        kind=_SCHEMA_ROOT_KIND,
        scopes=(bundle_pin,),
        values=schema_inventory,
    )
    selected_observation_root_sha256 = _evidence_root(
        kind=_SELECTED_OBSERVATION_ROOT_KIND,
        scopes=(bundle_pin,),
        values=tuple(item.observation_record_sha256 for item in selected),
    )
    evidence_by_relation = {
        **relation_roots,
        "w2_operation": operation_receipt_pin,
    }
    relation_inventory_sha256 = _evidence_root(
        kind=_RELATION_INVENTORY_ROOT_KIND,
        scopes=(bundle_pin, operation_key_pin),
        values=tuple(evidence_by_relation[name] for name in _CANONICAL_RELATION_ORDER),
    )
    relation_row_count = sum(len(values) for values in relation_identities.values())
    receipt = W2PublicationVerificationReceiptV1.build(
        raw_authority_bundle_sha256=bundle_pin,
        operation_key_sha256=operation_key_pin,
        operation_receipt_sha256=operation_receipt_pin,
        schema_inventory_sha256=schema_inventory_sha256,
        selected_observation_count=len(selected),
        selected_observation_root_sha256=selected_observation_root_sha256,
        result_cell_schema_sha256=result_schema,
        result_cell_row_count=len(relation_identities["result_cell"]),
        result_cell_row_root_sha256=relation_roots["result_cell"],
        stats_lossless_schema_sha256=stats_schema,
        stats_lossless_row_count=len(relation_identities["stats_lossless"]),
        stats_lossless_row_root_sha256=relation_roots["stats_lossless"],
        live_lossless_schema_sha256=live_schema,
        live_lossless_row_count=len(relation_identities["live_lossless"]),
        live_lossless_row_root_sha256=relation_roots["live_lossless"],
        value_representation_schema_sha256=assignment_schema,
        value_representation_row_count=len(relation_identities["value_representation"]),
        value_representation_row_root_sha256=relation_roots["value_representation"],
        route_field_landing_schema_sha256=route_schema,
        route_field_landing_row_count=len(relation_identities["route_field_landing"]),
        route_field_landing_row_root_sha256=relation_roots["route_field_landing"],
        w2_operation_schema_sha256=operation_schema,
        w2_operation_row_count=1,
        relation_row_count=relation_row_count,
        publication_row_count=relation_row_count + 1,
        relation_inventory_sha256=relation_inventory_sha256,
    )
    if type(receipt) is not W2PublicationVerificationReceiptV1:
        _fail("W2 publication receipt builder returned a foreign exact DTO")
    replayed_receipt = W2PublicationVerificationReceiptV1.from_row(receipt.to_row())
    if type(replayed_receipt) is not W2PublicationVerificationReceiptV1 or (
        not _exact_equal(receipt.to_row(), replayed_receipt.to_row())
    ):
        _fail("W2 publication receipt differs after exact DTO replay")
    return replayed_receipt


def verify_w2_publication(
    *,
    raw_authority_bundle: object,
    expected_raw_authority_bundle_sha256: object,
    result_cell_rows: object,
    expected_result_cell_schema_sha256: object,
    stats_lossless_rows: object,
    expected_stats_lossless_schema_sha256: object,
    live_lossless_rows: object,
    expected_live_lossless_schema_sha256: object,
    value_representation_rows: object,
    expected_value_representation_schema_sha256: object,
    route_field_landing_rows: object,
    expected_route_field_landing_schema_sha256: object,
    w2_operation_rows: object,
    expected_w2_operation_schema_sha256: object,
    expected_operation_key_sha256: object,
    expected_operation_receipt_sha256: object,
) -> W2PublicationVerificationReceiptV1:
    """Verify one bundle's exact-six W2 public rows without side effects.

    Every dependency failure, including a hostile child implementation raising
    this module's public error class, is collapsed to a fixed public boundary.
    Verifier-owned contract failures retain only static, non-value-bearing text.
    """

    try:
        return _verify_w2_publication(
            raw_authority_bundle=raw_authority_bundle,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            result_cell_rows=result_cell_rows,
            expected_result_cell_schema_sha256=expected_result_cell_schema_sha256,
            stats_lossless_rows=stats_lossless_rows,
            expected_stats_lossless_schema_sha256=expected_stats_lossless_schema_sha256,
            live_lossless_rows=live_lossless_rows,
            expected_live_lossless_schema_sha256=expected_live_lossless_schema_sha256,
            value_representation_rows=value_representation_rows,
            expected_value_representation_schema_sha256=(
                expected_value_representation_schema_sha256
            ),
            route_field_landing_rows=route_field_landing_rows,
            expected_route_field_landing_schema_sha256=(expected_route_field_landing_schema_sha256),
            w2_operation_rows=w2_operation_rows,
            expected_w2_operation_schema_sha256=expected_w2_operation_schema_sha256,
            expected_operation_key_sha256=expected_operation_key_sha256,
            expected_operation_receipt_sha256=expected_operation_receipt_sha256,
        )
    except _InternalVerifierError as exc:
        raise W2PublicationVerifierError(str(exc)) from None
    except Exception:
        raise W2PublicationVerifierError(
            "W2 publication verification failed exact sanitized dependency replay"
        ) from None
