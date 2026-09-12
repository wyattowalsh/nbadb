"""Independent body/bodyless value projection authority for W2.

This module is the value-bearing peer of the public-table projector.  It reads
only exact Raw Authority V2 parser bytes or exact declared-bodyless packet
bytes, independently decodes those bytes, applies the value-free projection
plan, and emits the shared :mod:`nbadb.contracts.value_projection` DTOs.  It
never imports staging, extractor parser output, public relation rows, or the
public-table projector.

Declared-bodyless packet DTOs intentionally do not embed their payload.  The
builder therefore requires the immutable packet bytes as an exact ordered
tuple and revalidates both packet and readback receipts against those bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, ClassVar, Final, Never, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

from nbadb.contracts.body_blob_inventory import (
    BodyBlobAuthorityError,
    BodyBlobInventoryReadbackReceiptV1,
    BodyBlobInventoryV1,
    validate_body_blob_inventory,
)
from nbadb.contracts.declared_bodyless_packet_types import (
    DeclaredBodylessPacketReadbackReceiptV1,
    DeclaredBodylessPacketV1,
    validate_declared_bodyless_packet_bytes,
    validate_declared_bodyless_packet_readback_receipt,
)
from nbadb.contracts.independent_live_value_decoder import (
    DecodedLiveFieldCellV1,
    DecodedLiveNodeV1,
    DecodedLiveResponseV1,
    DecodedLiveResultOccurrenceV1,
    DecodedLiveResultSetV1,
    decode_live_value_response,
    validate_decoded_live_response,
)
from nbadb.contracts.independent_static_value_decoder import (
    DecodedStaticResponseV1,
    decode_static_value_response,
    validate_decoded_static_response,
)
from nbadb.contracts.independent_stats_projection_decoder import (
    DecodedStatsProjectionRecordV1,
    DecodedStatsProjectionResponseV1,
    DecodedStatsProjectionResultV1,
    decode_stats_projection_response,
    validate_decoded_stats_projection_response,
)
from nbadb.contracts.lossless_ownership import (
    LosslessOwnershipAuthorityV1,
    LosslessOwnershipError,
    build_lossless_ownership_authority,
)
from nbadb.contracts.raw_request_authority import (
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    decode_parser_input_object,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.value_projection import (
    MAX_VALUE_PROJECTION_ITEMS,
    MAX_VALUE_PROJECTION_OBSERVATIONS,
    MAX_VALUE_PROJECTION_PARTITIONS,
    VALUE_PROJECTION_COORDINATE_FIELDS_V1,
    BodyValueProjectionReceiptV1,
    ValueProjectionItemV1,
    ValueProjectionPartitionV1,
    ValueProjectionReceiptV1,
)
from nbadb.contracts.value_projection_plan import (
    ValueProjectionPlanOccurrenceV1,
    ValueProjectionPlanSourceRecordV1,
    ValueProjectionPlanV1,
    validate_value_projection_plan,
)

__all__ = [
    "DECLARED_BODYLESS_PROJECTION_AUTHORITY_SCHEMA_VERSION",
    "INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256",
    "INDEPENDENT_BODY_VALUE_PROJECTION_SCHEMA_VERSION",
    "DeclaredBodylessProjectionAuthorityV1",
    "IndependentBodyValueProjectionBuilderError",
    "IndependentBodyValueProjectionV1",
    "build_declared_bodyless_projection_authority",
    "build_independent_body_value_projection",
]


INDEPENDENT_BODY_VALUE_PROJECTION_SCHEMA_VERSION: Final = 1
DECLARED_BODYLESS_PROJECTION_AUTHORITY_SCHEMA_VERSION: Final = 1
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_MAX_INT64: Final = (1 << 63) - 1
_MAX_KNOWN_SECRETS: Final = 128
_MAX_KNOWN_SECRET_BYTES: Final = 4096
_DECLARED_AUTHORITY_KIND: Final = "nbadb_declared_bodyless_projection_authority_v1"
_DECLARED_PACKET_ROOT_KIND: Final = "nbadb_declared_bodyless_projection_packets_v1"
_DECLARED_READBACK_ROOT_KIND: Final = "nbadb_declared_bodyless_projection_readbacks_v1"
_DECLARED_PAYLOAD_ROOT_KIND: Final = "nbadb_declared_bodyless_projection_payloads_v1"
_DECLARED_OBSERVATION_ROOT_KIND: Final = "nbadb_declared_bodyless_projection_observations_v1"
_NO_VALUE_OVERRIDE: Final = object()

_POLICY_PAYLOAD: Final = {
    "schema_version": 1,
    "kind": "nbadb_independent_body_value_projection_policy_v1",
    "source_order": "value_projection_plan_observation_and_source_record_order_v1",
    "stats_decoder": "nbadb_independent_stats_projection_decoder_v1",
    "static_decoder": "nbadb_independent_static_value_decoder_v1",
    "live_decoder": "nbadb_independent_live_value_decoder_v1",
    "container_policy": "nonempty_json_containers_are_structural_nodes_v1",
    "bodyless_payload_seam": "exact_ordered_immutable_packet_bytes_v1",
}


class IndependentBodyValueProjectionBuilderError(ValueError):
    """Exact source evidence cannot form one independent body projection."""


def _fail(message: str) -> Never:
    raise IndependentBodyValueProjectionBuilderError(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (MemoryError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("independent body projection cannot encode canonical JSON")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256: Final = _canonical_sha256(_POLICY_PAYLOAD)


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _nonnegative(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{label} must be one bounded exact nonnegative integer")
    return value


def _pin_sha_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > MAX_VALUE_PROJECTION_OBSERVATIONS:
        _fail(f"{label} must be one bounded exact tuple")
    return tuple(_sha256(item, label=label) for item in value)


def _ordered_root(*, kind: str, bundle: str, values: tuple[str, ...], maximum: int) -> str:
    if type(values) is not tuple or len(values) > maximum:
        _fail("independent body projection ordered-root inventory is over-bound")
    digest = hashlib.sha256()
    digest.update(b"nbadb-value-projection-length-framed-root-v1\x00")

    def feed(raw: bytes) -> None:
        digest.update(len(raw).to_bytes(8, byteorder="big", signed=False))
        digest.update(raw)

    feed(b"1")
    feed(kind.encode("utf-8"))
    feed(_sha256(bundle, label="ordered-root bundle").encode("ascii"))
    feed(str(len(values)).encode("ascii"))
    for ordinal, identity in enumerate(values):
        feed(str(ordinal).encode("ascii"))
        feed(_sha256(identity, label="ordered-root item").encode("ascii"))
    return digest.hexdigest()


def _legacy_root(*, kind: str, values: tuple[str, ...]) -> str:
    return _canonical_sha256(
        {"count": len(values), "items": list(values), "kind": kind, "schema_version": 1}
    )


def _known_secret_bytes(value: object) -> tuple[bytes, ...]:
    if type(value) not in {list, tuple}:
        _fail("known-secret inventory must be one bounded exact sequence")
    exact = cast("list[object] | tuple[object, ...]", value)
    if len(exact) > _MAX_KNOWN_SECRETS:
        _fail("known-secret inventory exceeds its bound")
    output: list[bytes] = []
    for item in exact:
        if type(item) is str:
            try:
                encoded = item.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                _fail("known-secret inventory contains invalid text")
        elif type(item) is bytes:
            encoded = item
        else:
            _fail("known-secret inventory contains a foreign exact type")
        if not encoded or len(encoded) > _MAX_KNOWN_SECRET_BYTES:
            _fail("known-secret inventory contains an invalid entry")
        output.append(encoded)
    return tuple(output)


def _reject_known_secrets(payload: bytes, *, secrets: tuple[bytes, ...]) -> None:
    if any(secret in payload for secret in secrets):
        _fail("independent body projection source contains known-secret material")


@dataclass(frozen=True, slots=True)
class DeclaredBodylessProjectionAuthorityV1:
    """Deterministic aggregate over all exact declared-bodyless source evidence."""

    authority_sha256: str
    raw_authority_bundle_sha256: str
    packet_count: int
    packet_root_sha256: str
    readback_count: int
    readback_root_sha256: str
    payload_count: int
    payload_root_sha256: str
    payload_byte_count: int
    observation_count: int
    observation_root_sha256: str

    schema_version: ClassVar[int] = DECLARED_BODYLESS_PROJECTION_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = _DECLARED_AUTHORITY_KIND

    def __post_init__(self) -> None:
        for name in (
            "authority_sha256",
            "raw_authority_bundle_sha256",
            "packet_root_sha256",
            "readback_root_sha256",
            "payload_root_sha256",
            "observation_root_sha256",
        ):
            _sha256(getattr(self, name), label=name)
        for name, maximum in (
            ("packet_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("readback_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("payload_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("payload_byte_count", _MAX_INT64),
            ("observation_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
        ):
            _nonnegative(getattr(self, name), label=name, maximum=maximum)
        if not (
            self.packet_count == self.readback_count == self.payload_count == self.observation_count
        ):
            _fail("declared-bodyless aggregate denominators differ")
        if (self.payload_count == 0) != (self.payload_byte_count == 0):
            _fail("declared-bodyless aggregate byte zero proof differs")
        if self.packet_count == 0:
            empty_roots = (
                (
                    self.packet_root_sha256,
                    _ordered_root(
                        kind=_DECLARED_PACKET_ROOT_KIND,
                        bundle=self.raw_authority_bundle_sha256,
                        values=(),
                        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
                    ),
                ),
                (
                    self.readback_root_sha256,
                    _ordered_root(
                        kind=_DECLARED_READBACK_ROOT_KIND,
                        bundle=self.raw_authority_bundle_sha256,
                        values=(),
                        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
                    ),
                ),
                (
                    self.payload_root_sha256,
                    _ordered_root(
                        kind=_DECLARED_PAYLOAD_ROOT_KIND,
                        bundle=self.raw_authority_bundle_sha256,
                        values=(),
                        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
                    ),
                ),
                (
                    self.observation_root_sha256,
                    _ordered_root(
                        kind=_DECLARED_OBSERVATION_ROOT_KIND,
                        bundle=self.raw_authority_bundle_sha256,
                        values=(),
                        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
                    ),
                ),
            )
            if any(observed != expected for observed, expected in empty_roots):
                _fail("empty declared-bodyless aggregate roots differ from exact replay")
        if self.authority_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("declared-bodyless aggregate identity differs from exact replay")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "authority_sha256"
            },
        }


def _build_declared_bodyless_projection_authority(
    *,
    raw_authority_bundle_sha256: object,
    packets: object,
    expected_packet_authority_sha256s: object,
    readbacks: object,
    expected_readback_receipt_sha256s: object,
    packet_bytes: object,
    expected_observation_sha256s: object,
    expected_observation_record_sha256s: object,
    known_secrets: Sequence[str | bytes] = (),
) -> DeclaredBodylessProjectionAuthorityV1:
    """Revalidate and aggregate one exact ordered declared-bodyless inventory."""

    bundle = _sha256(raw_authority_bundle_sha256, label="declared-bodyless bundle")
    packet_pins = _pin_sha_tuple(
        expected_packet_authority_sha256s, label="declared-bodyless packet pin"
    )
    readback_pins = _pin_sha_tuple(
        expected_readback_receipt_sha256s, label="declared-bodyless readback pin"
    )
    observation_pins = _pin_sha_tuple(
        expected_observation_sha256s, label="declared-bodyless observation pin"
    )
    observation_record_pins = _pin_sha_tuple(
        expected_observation_record_sha256s,
        label="declared-bodyless observation-record pin",
    )
    if (
        type(packets) is not tuple
        or type(readbacks) is not tuple
        or type(packet_bytes) is not tuple
    ):
        _fail("declared-bodyless aggregate inputs must be exact tuples")
    packet_values = packets
    readback_values = readbacks
    payload_values = packet_bytes
    denominator = len(packet_pins)
    if denominator > MAX_VALUE_PROJECTION_OBSERVATIONS or any(
        len(value) != denominator
        for value in (
            readback_pins,
            observation_pins,
            observation_record_pins,
            packet_values,
            readback_values,
            payload_values,
        )
    ):
        _fail("declared-bodyless aggregate denominators differ")
    if any(type(item) is not DeclaredBodylessPacketV1 for item in packet_values):
        _fail("declared-bodyless aggregate contains a foreign packet DTO")
    if any(type(item) is not DeclaredBodylessPacketReadbackReceiptV1 for item in readback_values):
        _fail("declared-bodyless aggregate contains a foreign readback DTO")
    if any(type(item) is not bytes for item in payload_values):
        _fail("declared-bodyless aggregate contains foreign packet bytes")
    if (
        len(set(packet_pins)) != denominator
        or len(set(readback_pins)) != denominator
        or len(set(observation_pins)) != denominator
        or len(set(observation_record_pins)) != denominator
    ):
        _fail("declared-bodyless aggregate contains duplicate authority identities")
    secrets = _known_secret_bytes(known_secrets)
    exact_packets: list[DeclaredBodylessPacketV1] = []
    exact_readbacks: list[DeclaredBodylessPacketReadbackReceiptV1] = []
    payload_ids: list[str] = []
    observation_ids: list[str] = []
    byte_count = 0
    for packet, readback, payload, packet_pin, readback_pin, observation, record in zip(
        cast("tuple[DeclaredBodylessPacketV1, ...]", packet_values),
        cast("tuple[DeclaredBodylessPacketReadbackReceiptV1, ...]", readback_values),
        cast("tuple[bytes, ...]", payload_values),
        packet_pins,
        readback_pins,
        observation_pins,
        observation_record_pins,
        strict=True,
    ):
        _reject_known_secrets(payload, secrets=secrets)
        try:
            exact_packet = validate_declared_bodyless_packet_bytes(
                packet,
                packet_bytes=payload,
                expected_observation_sha256=observation,
                expected_observation_record_sha256=record,
                expected_packet_authority_sha256=packet_pin,
                known_secrets=known_secrets,
            )
            exact_readback = validate_declared_bodyless_packet_readback_receipt(
                readback,
                packet=exact_packet,
                readback_bytes=payload,
                store_namespace_sha256=readback.store_namespace_sha256,
                expected_packet_authority_sha256=packet_pin,
                expected_receipt_sha256=readback_pin,
                known_secrets=known_secrets,
            )
            if (
                type(exact_packet) is not DeclaredBodylessPacketV1
                or exact_packet != packet
                or exact_packet.packet_authority_sha256 != packet_pin
                or type(exact_readback) is not DeclaredBodylessPacketReadbackReceiptV1
                or exact_readback != readback
                or exact_readback.receipt_sha256 != readback_pin
            ):
                _fail("declared-bodyless aggregate source replay returned foreign evidence")
        except Exception:  # noqa: BLE001 - collapse the untrusted packet replay boundary
            _fail("declared-bodyless aggregate failed exact source replay")
        if (
            exact_packet.observation_sha256 != observation
            or exact_packet.observation_record_sha256 != record
            or exact_readback.observation_sha256 != observation
            or exact_readback.observation_record_sha256 != record
        ):
            _fail("declared-bodyless aggregate source order differs")
        exact_packets.append(exact_packet)
        exact_readbacks.append(exact_readback)
        payload_ids.append(hashlib.sha256(payload).hexdigest())
        observation_ids.append(
            _canonical_sha256(
                {
                    "schema_version": 1,
                    "kind": "nbadb_declared_bodyless_projection_observation_v1",
                    "raw_authority_bundle_sha256": bundle,
                    "observation_sha256": observation,
                    "observation_record_sha256": record,
                    "packet_authority_sha256": packet_pin,
                    "readback_receipt_sha256": readback_pin,
                    "payload_sha256": payload_ids[-1],
                    "payload_byte_count": len(payload),
                }
            )
        )
        byte_count += len(payload)
        if byte_count > _MAX_INT64:
            _fail("declared-bodyless aggregate byte count exceeds its bound")
    values: dict[str, object] = {
        "raw_authority_bundle_sha256": bundle,
        "packet_count": denominator,
        "packet_root_sha256": _ordered_root(
            kind=_DECLARED_PACKET_ROOT_KIND,
            bundle=bundle,
            values=tuple(item.packet_authority_sha256 for item in exact_packets),
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
        ),
        "readback_count": denominator,
        "readback_root_sha256": _ordered_root(
            kind=_DECLARED_READBACK_ROOT_KIND,
            bundle=bundle,
            values=tuple(item.receipt_sha256 for item in exact_readbacks),
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
        ),
        "payload_count": denominator,
        "payload_root_sha256": _ordered_root(
            kind=_DECLARED_PAYLOAD_ROOT_KIND,
            bundle=bundle,
            values=tuple(payload_ids),
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
        ),
        "payload_byte_count": byte_count,
        "observation_count": denominator,
        "observation_root_sha256": _ordered_root(
            kind=_DECLARED_OBSERVATION_ROOT_KIND,
            bundle=bundle,
            values=tuple(observation_ids),
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
        ),
    }
    identity = {
        "schema_version": DECLARED_BODYLESS_PROJECTION_AUTHORITY_SCHEMA_VERSION,
        "kind": _DECLARED_AUTHORITY_KIND,
        **values,
    }
    return DeclaredBodylessProjectionAuthorityV1(
        authority_sha256=_canonical_sha256(identity), **cast("Any", values)
    )


def build_declared_bodyless_projection_authority(
    *,
    raw_authority_bundle_sha256: object,
    packets: object,
    expected_packet_authority_sha256s: object,
    readbacks: object,
    expected_readback_receipt_sha256s: object,
    packet_bytes: object,
    expected_observation_sha256s: object,
    expected_observation_record_sha256s: object,
    known_secrets: Sequence[str | bytes] = (),
) -> DeclaredBodylessProjectionAuthorityV1:
    """Revalidate and aggregate one exact ordered declared-bodyless inventory."""

    return _build_declared_bodyless_projection_authority(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        packets=packets,
        expected_packet_authority_sha256s=expected_packet_authority_sha256s,
        readbacks=readbacks,
        expected_readback_receipt_sha256s=expected_readback_receipt_sha256s,
        packet_bytes=packet_bytes,
        expected_observation_sha256s=expected_observation_sha256s,
        expected_observation_record_sha256s=expected_observation_record_sha256s,
        known_secrets=known_secrets,
    )


def _replay_declared_bodyless_authority(
    value: object,
) -> DeclaredBodylessProjectionAuthorityV1:
    if type(value) is not DeclaredBodylessProjectionAuthorityV1:
        _fail("declared-bodyless aggregate has a foreign exact DTO")
    try:
        exact = DeclaredBodylessProjectionAuthorityV1(
            **{
                item.name: getattr(value, item.name)
                for item in fields(DeclaredBodylessProjectionAuthorityV1)
            }
        )
    except Exception:  # noqa: BLE001 - collapse the untrusted DTO replay boundary
        _fail("declared-bodyless aggregate failed exact DTO replay")
    if exact != value:
        _fail("declared-bodyless aggregate differs from its exact DTO replay")
    return exact


@dataclass(frozen=True, slots=True)
class IndependentBodyValueProjectionV1:
    """Exact body receipt plus the independently reconstructed shared projection."""

    receipt: BodyValueProjectionReceiptV1
    projection: ValueProjectionReceiptV1
    partitions: tuple[ValueProjectionPartitionV1, ...]
    items: tuple[ValueProjectionItemV1, ...]
    declared_bodyless_authority: DeclaredBodylessProjectionAuthorityV1

    def __post_init__(self) -> None:
        if (
            type(self.receipt) is not BodyValueProjectionReceiptV1
            or type(self.projection) is not ValueProjectionReceiptV1
            or type(self.partitions) is not tuple
            or type(self.items) is not tuple
            or type(self.declared_bodyless_authority) is not DeclaredBodylessProjectionAuthorityV1
            or len(self.partitions) > MAX_VALUE_PROJECTION_PARTITIONS
            or len(self.items) > MAX_VALUE_PROJECTION_ITEMS
            or any(type(item) is not ValueProjectionPartitionV1 for item in self.partitions)
            or any(type(item) is not ValueProjectionItemV1 for item in self.items)
        ):
            _fail("independent body projection aggregate has a foreign child")
        try:
            receipt = BodyValueProjectionReceiptV1.from_row(self.receipt.to_row())
            projection = ValueProjectionReceiptV1.from_row(self.projection.to_row())
            partitions = tuple(
                ValueProjectionPartitionV1.from_row(item.to_row()) for item in self.partitions
            )
            items = tuple(ValueProjectionItemV1.from_row(item.to_row()) for item in self.items)
            declared = _replay_declared_bodyless_authority(self.declared_bodyless_authority)
        except Exception:  # noqa: BLE001 - collapse the untrusted child replay boundary
            _fail("independent body projection aggregate failed exact child replay")
        if (
            receipt != self.receipt
            or projection != self.projection
            or partitions != self.partitions
            or items != self.items
            or declared != self.declared_bodyless_authority
            or receipt.projection_sha256 != projection.projection_sha256
            or receipt.projection_partition_count != len(partitions)
            or receipt.projection_item_count != len(items)
            or projection.partition_count != len(partitions)
            or projection.item_count != len(items)
            or receipt.declared_bodyless_authority_sha256
            != self.declared_bodyless_authority.authority_sha256
            or receipt.body_projection_policy_sha256
            != INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256
        ):
            _fail("independent body projection aggregate differs from its exact receipt")


@dataclass(frozen=True, slots=True)
class _MaterializedRecord:
    observation_sha256: str
    occurrence_sha256: str | None
    record_kind: str
    coordinate: dict[str, object]
    value_shape: dict[str, object]
    source_identity_sha256: str


def _empty_coordinate() -> dict[str, object]:
    return {name: None for name in VALUE_PROJECTION_COORDINATE_FIELDS_V1}


def _result_path(occurrence: ValueProjectionPlanOccurrenceV1) -> str:
    if occurrence.result_path is not None:
        return occurrence.result_path
    if occurrence.provider_result_ordinal is not None:
        return f"$.resultSets[{occurrence.provider_result_ordinal}]"
    if occurrence.canonical_result_ordinal is not None:
        return f"$.expectedResults[{occurrence.canonical_result_ordinal}]"
    if occurrence.expected_result_ordinal is not None:
        return f"$.expectedResults[{occurrence.expected_result_ordinal}]"
    _fail("independent body projection occurrence lacks a deterministic result path")


def _result_coordinate(occurrence: ValueProjectionPlanOccurrenceV1) -> dict[str, object]:
    coordinate = _empty_coordinate()
    coordinate.update(
        {
            "result_name": occurrence.result_name,
            "result_duplicate_ordinal": occurrence.result_duplicate_ordinal,
            "provider_result_ordinal": occurrence.provider_result_ordinal,
            "expected_result_ordinal": occurrence.expected_result_ordinal,
            "canonical_result_ordinal": occurrence.canonical_result_ordinal,
            "result_path": _result_path(occurrence),
            "container_kind": occurrence.container_kind,
            "result_presence": occurrence.result_presence,
        }
    )
    return coordinate


def _decode_canonical_value(value: str) -> object:
    if type(value) is not str or not value:
        _fail("independent body projection canonical value is absent")
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, MemoryError, RecursionError, TypeError, ValueError):
        _fail("independent body projection canonical value failed decoding")
    if _canonical_bytes(decoded).decode("utf-8") != value:
        _fail("independent body projection canonical value is noncanonical")
    return decoded


def _node_value_shape(
    *, presence_kind: str, value_kind: str, canonical_json: str | None
) -> dict[str, object]:
    if presence_kind == "missing":
        return {"value_state": "missing", "missing_presence_kind": "missing"}
    if canonical_json is None:
        if presence_kind == "present" and value_kind in {"array", "object"}:
            return {
                "value_state": "structural_container",
                "structural_value_kind": value_kind,
            }
        _fail("independent body projection node has incomplete value material")
    return {"value": _decode_canonical_value(canonical_json)}


def _stats_occurrence_index(
    occurrences: tuple[ValueProjectionPlanOccurrenceV1, ...],
) -> dict[
    tuple[str, int, int | None, int | None, int | None],
    ValueProjectionPlanOccurrenceV1,
]:
    output: dict[
        tuple[str, int, int | None, int | None, int | None],
        ValueProjectionPlanOccurrenceV1,
    ] = {}
    for item in occurrences:
        key = (
            item.result_name,
            item.result_duplicate_ordinal,
            item.provider_result_ordinal,
            item.expected_result_ordinal,
            item.canonical_result_ordinal,
        )
        if key in output:
            _fail("independent stats plan contains a duplicate occurrence lookup key")
        output[key] = item
    return output


def _occurrence_for_stats_result(
    occurrence_index: dict[
        tuple[str, int, int | None, int | None, int | None],
        ValueProjectionPlanOccurrenceV1,
    ],
    *,
    result_name: str,
    result_duplicate_ordinal: int,
    provider_result_ordinal: int | None,
    expected_result_ordinal: int | None,
    canonical_result_ordinal: int | None,
) -> ValueProjectionPlanOccurrenceV1:
    keys = dict.fromkeys(
        (
            (
                result_name,
                result_duplicate_ordinal,
                provider_result_ordinal,
                expected_result_ordinal,
                canonical_result_ordinal,
            ),
            (
                result_name,
                result_duplicate_ordinal,
                provider_result_ordinal,
                None,
                canonical_result_ordinal,
            ),
            (
                result_name,
                result_duplicate_ordinal,
                provider_result_ordinal,
                expected_result_ordinal,
                None,
            ),
            (result_name, result_duplicate_ordinal, provider_result_ordinal, None, None),
        )
    )
    candidates = {
        item.occurrence_sha256: item
        for key in keys
        if (item := occurrence_index.get(key)) is not None
    }
    if len(candidates) != 1:
        _fail("independent stats decoding cannot identify one exact planned occurrence")
    return next(iter(candidates.values()))


def _stats_record_material(
    record: DecodedStatsProjectionRecordV1,
    *,
    observation_sha256: str,
    occurrence: ValueProjectionPlanOccurrenceV1,
    rectangular: bool,
    value_override: object = _NO_VALUE_OVERRIDE,
) -> _MaterializedRecord:
    coordinate = _result_coordinate(occurrence)
    if rectangular:
        if record.record_kind != "cell":
            _fail("rectangular stats material contains a non-cell record")
        coordinate.update(
            {
                "header_name": record.header_name,
                "header_ordinal": record.header_ordinal,
                "header_duplicate_ordinal": record.header_duplicate_ordinal,
                "row_ordinal": record.row_ordinal,
                "row_duplicate_ordinal": record.row_duplicate_ordinal,
                "row_value_sha256": record.row_value_sha256,
                "cell_ordinal": record.cell_ordinal,
                "value_duplicate_ordinal": record.value_duplicate_ordinal,
            }
        )
    else:
        if record.header_ordinal is not None:
            coordinate.update(
                {
                    "header_reference_kind": record.header_reference_kind,
                    "header_name": record.header_name,
                    "header_ordinal": record.header_ordinal,
                    "header_value_sha256": record.header_value_sha256,
                    "header_duplicate_ordinal": record.header_duplicate_ordinal,
                }
            )
        if record.row_ordinal is not None:
            coordinate.update(
                {
                    "row_ordinal": record.row_ordinal,
                    "row_duplicate_ordinal": record.row_duplicate_ordinal,
                    "row_value_sha256": record.row_value_sha256,
                }
            )
        if record.record_kind == "cell":
            coordinate.update(
                {
                    "cell_ordinal": record.cell_ordinal,
                    "value_duplicate_ordinal": record.value_duplicate_ordinal,
                }
            )
    return _MaterializedRecord(
        observation_sha256=observation_sha256,
        occurrence_sha256=occurrence.occurrence_sha256,
        record_kind=record.record_kind,
        coordinate=coordinate,
        value_shape={
            "value": (
                _decode_canonical_value(record.canonical_json)
                if value_override is _NO_VALUE_OVERRIDE
                else value_override
            )
        },
        source_identity_sha256=record.record_sha256,
    )


def _stats_target_result_declaration(
    decoded: DecodedStatsProjectionResultV1,
) -> dict[str, object]:
    """Rebuild the canonical stats-lossless declaration from decoder bytes."""

    raw_declaration = _decode_canonical_value(decoded.records[0].canonical_json)
    if type(raw_declaration) is not dict:
        _fail("independent stats result declaration is not one exact object")
    expected_headers = raw_declaration.get("expected_headers")
    if expected_headers is not None and (
        type(expected_headers) is not list
        or any(type(item) is not str for item in cast("list[object]", expected_headers))
    ):
        _fail("independent stats expected-header declaration is invalid")
    raw_headers = _decode_canonical_value(decoded.raw_headers_json)
    raw_rows = _decode_canonical_value(decoded.raw_rows_json)
    if decoded.presence == "missing":
        anomaly_codes: tuple[str, ...] = ()
        normalized_output_sha256 = _canonical_sha256({"headers": expected_headers, "rows": []})
        header_record_count = 0
    else:
        reasons: set[str] = set()
        header_values = cast("list[object]", raw_headers) if type(raw_headers) is list else []
        observed_names = tuple(item if type(item) is str else None for item in header_values)
        if type(raw_headers) is not list or any(item is None for item in observed_names):
            reasons.add("unsupported_header_shape")
        observed_headers = tuple(item for item in observed_names if item is not None)
        if len(set(observed_headers)) != len(observed_headers):
            reasons.add("duplicate_header")
        if expected_headers is not None:
            expected = tuple(cast("list[str]", expected_headers))
            expected_counter = Counter(expected)
            observed_counter = Counter(observed_headers)
            if observed_counter - expected_counter:
                reasons.add("additive_header")
            if expected_counter - observed_counter:
                reasons.add("removed_header")
            if expected_counter == observed_counter and expected != observed_headers:
                reasons.add("reordered_header")
        if type(raw_rows) is not list:
            reasons.add("unsupported_row_container")
        else:
            widths: set[int] = set()
            kinds_by_ordinal: dict[int, set[str]] = {}
            for raw_row in cast("list[object]", raw_rows):
                if type(raw_row) is not list:
                    reasons.add("non_sequence_row")
                    continue
                row = cast("list[object]", raw_row)
                widths.add(len(row))
                if len(row) != len(observed_names):
                    reasons.add("ragged_row")
                for ordinal, cell in enumerate(row):
                    kind = (
                        "null"
                        if cell is None
                        else "boolean"
                        if type(cell) is bool
                        else "integer"
                        if type(cell) is int
                        else "number"
                        if type(cell) is float
                        else "string"
                        if type(cell) is str
                        else "array"
                        if type(cell) is list
                        else "object"
                        if type(cell) is dict
                        else "foreign"
                    )
                    if kind != "null":
                        kinds_by_ordinal.setdefault(ordinal, set()).add(kind)
            if len(widths) > 1:
                reasons.add("ragged_row")
            if any(len(kinds) > 1 for kinds in kinds_by_ordinal.values()):
                reasons.add("heterogeneous_column")
        anomaly_codes = tuple(sorted(reasons))
        normalized_output_sha256 = _canonical_sha256(
            {
                "headers": raw_headers,
                "rows": raw_rows,
                "anomalies": list(anomaly_codes),
            }
        )
        header_record_count = decoded.header_record_count
    return {
        "anomaly_codes": list(anomaly_codes),
        "expected_headers": expected_headers,
        "header_record_count": header_record_count,
        "normalized_output_sha256": normalized_output_sha256,
        "presence": decoded.presence,
        "raw_cell_count": decoded.cell_count,
        "raw_row_occurrence_count": decoded.raw_row_occurrence_count,
        "sequence_row_count": decoded.sequence_row_count,
    }


def _stats_residual_material(
    response: DecodedStatsProjectionResponseV1,
    *,
    observation_sha256: str,
) -> tuple[_MaterializedRecord, ...]:
    output = [
        _MaterializedRecord(
            observation_sha256=observation_sha256,
            occurrence_sha256=None,
            record_kind="response",
            coordinate=_empty_coordinate(),
            value_shape={"value_state": "absent"},
            source_identity_sha256=response.canonical_payload_sha256,
        )
    ]
    for node in response.residual_nodes:
        coordinate = _empty_coordinate()
        coordinate.update(
            {
                "node_ordinal": node.node_ordinal,
                "parent_node_ordinal": node.parent_node_ordinal,
                "json_path": node.json_path,
                "parent_json_path": node.parent_json_path,
                "depth": node.depth,
                "object_key": node.object_key,
                "object_key_ordinal": node.object_key_ordinal,
                "array_ordinal": node.array_ordinal,
            }
        )
        output.append(
            _MaterializedRecord(
                observation_sha256=observation_sha256,
                occurrence_sha256=None,
                record_kind="json_node",
                coordinate=coordinate,
                value_shape=_node_value_shape(
                    presence_kind=node.presence_kind,
                    value_kind=node.value_kind,
                    canonical_json=node.canonical_json,
                ),
                source_identity_sha256=node.node_sha256,
            )
        )
    return tuple(output)


def _materialize_stats(
    *,
    observation: RequestObservationV2,
    parser_input: bytes,
    occurrence_plans: tuple[ValueProjectionPlanOccurrenceV1, ...],
    source_plans: tuple[ValueProjectionPlanSourceRecordV1, ...],
) -> tuple[tuple[_MaterializedRecord, ...], dict[int, tuple[dict[str, object], ...]], str]:
    try:
        decoded_source = decode_stats_projection_response(
            parser_input,
            endpoint_id=observation.attempt.endpoint_id,
            endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
            provider_authority_sha256=observation.attempt.provider_authority_sha256,
        )
        decoded = validate_decoded_stats_projection_response(
            decoded_source,
            parser_input_bytes=parser_input,
        )
        if (
            type(decoded) is not DecodedStatsProjectionResponseV1
            or decoded != decoded_source
            or decoded.endpoint_id != observation.attempt.endpoint_id
            or decoded.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256
            or decoded.provider_authority_sha256 != observation.attempt.provider_authority_sha256
            or decoded.parser_input_sha256 != hashlib.sha256(parser_input).hexdigest()
            or decoded.parser_input_length != len(parser_input)
        ):
            _fail("independent stats decoder differs from exact source bytes")
    except Exception:  # noqa: BLE001 - collapse the untrusted decoder boundary
        _fail("independent stats body decoding failed")
    occurrence_index = _stats_occurrence_index(occurrence_plans)
    pending: list[_MaterializedRecord] = []
    slots: dict[int, tuple[dict[str, object], ...]] = {}
    for result in decoded.results:
        occurrence = _occurrence_for_stats_result(
            occurrence_index,
            result_name=result.result_name,
            result_duplicate_ordinal=result.result_duplicate_ordinal,
            provider_result_ordinal=result.provider_result_ordinal,
            expected_result_ordinal=result.expected_result_ordinal,
            canonical_result_ordinal=result.canonical_result_ordinal,
        )
        if occurrence.representation_kind == "rectangular_result_cells_v1":
            records = tuple(item for item in result.records if item.record_kind == "cell")
            rectangular = True
        elif occurrence.representation_kind == "stats_lossless_records_v1":
            records = result.records[:3] if result.presence == "missing" else result.records
            rectangular = False
            raw_slots = _decode_canonical_value(result.ordered_header_slots_json)
            if type(raw_slots) is not list or any(type(item) is not dict for item in raw_slots):
                _fail("independent stats header-slot inventory is invalid")
            slots[occurrence.partition_ordinal] = (
                ()
                if result.presence == "missing"
                else tuple(cast("dict[str, object]", item) for item in raw_slots)
            )
        else:
            _fail("stats body was assigned a foreign result representation")
        declaration = (
            _NO_VALUE_OVERRIDE if rectangular else _stats_target_result_declaration(result)
        )
        pending.extend(
            _stats_record_material(
                record,
                observation_sha256=observation.attempt.observation_sha256,
                occurrence=occurrence,
                rectangular=rectangular,
                value_override=(
                    declaration if not rectangular and record_ordinal == 0 else _NO_VALUE_OVERRIDE
                ),
            )
            for record_ordinal, record in enumerate(records)
        )
    if any(item.occurrence_sha256 is None for item in source_plans):
        pending.extend(
            _stats_residual_material(
                decoded,
                observation_sha256=observation.attempt.observation_sha256,
            )
        )
    return tuple(pending), slots, decoded.canonical_payload_sha256


def _materialize_static(
    *,
    observation: RequestObservationV2,
    packet_bytes: bytes,
    occurrence_plans: tuple[ValueProjectionPlanOccurrenceV1, ...],
) -> tuple[_MaterializedRecord, ...]:
    if len(occurrence_plans) != 1:
        _fail("static bodyless source does not have one exact result occurrence")
    occurrence = occurrence_plans[0]
    try:
        decoded_source = decode_static_value_response(
            packet_bytes,
            dataset_id=observation.attempt.endpoint_id,
            endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
        )
        decoded = validate_decoded_static_response(decoded_source)
        if (
            type(decoded) is not DecodedStaticResponseV1
            or decoded != decoded_source
            or decoded.dataset_id != observation.attempt.endpoint_id
            or decoded.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256
            or decoded.parser_input_sha256 != hashlib.sha256(packet_bytes).hexdigest()
            or decoded.parser_input_length != len(packet_bytes)
        ):
            _fail("independent static packet decoder differs from exact source bytes")
    except Exception:  # noqa: BLE001 - collapse the untrusted decoder boundary
        _fail("independent static packet decoding failed")
    if (
        decoded.result_name != occurrence.result_name
        or decoded.provider_result_ordinal != occurrence.provider_result_ordinal
        or decoded.canonical_result_ordinal != occurrence.canonical_result_ordinal
        or decoded.container_kind != occurrence.container_kind
        or decoded.field_count != occurrence.header_count
        or decoded.record_count != occurrence.row_count
        or decoded.cell_count != occurrence.cell_count
    ):
        _fail("independent static decoding differs from the exact planned occurrence")
    header_duplicates: dict[int, int] = {}
    seen_headers: dict[str, int] = {}
    for field in decoded.fields:
        header_duplicates[field.ordinal] = seen_headers.get(field.name, 0)
        seen_headers[field.name] = seen_headers.get(field.name, 0) + 1
    output: list[_MaterializedRecord] = []
    for cell in decoded.cells:
        coordinate = _result_coordinate(occurrence)
        record = decoded.records[cell.record_ordinal]
        coordinate.update(
            {
                "header_name": cell.field_name,
                "header_ordinal": cell.field_ordinal,
                "header_duplicate_ordinal": header_duplicates[cell.field_ordinal],
                "row_ordinal": cell.record_ordinal,
                "row_duplicate_ordinal": record.duplicate_record_ordinal,
                "row_value_sha256": record.values_sha256,
                "cell_ordinal": cell.cell_ordinal,
                "value_duplicate_ordinal": cell.duplicate_value_ordinal,
            }
        )
        output.append(
            _MaterializedRecord(
                observation_sha256=observation.attempt.observation_sha256,
                occurrence_sha256=occurrence.occurrence_sha256,
                record_kind="cell",
                coordinate=coordinate,
                value_shape={"value": _decode_canonical_value(cell.canonical_json)},
                source_identity_sha256=cell.cell_sha256,
            )
        )
    return tuple(output)


def _live_occurrence_index(
    occurrence_plans: tuple[ValueProjectionPlanOccurrenceV1, ...],
) -> dict[int, ValueProjectionPlanOccurrenceV1]:
    output: dict[int, ValueProjectionPlanOccurrenceV1] = {}
    for item in occurrence_plans:
        ordinal = item.canonical_result_ordinal
        if ordinal is None:
            continue
        if ordinal in output:
            _fail("independent live plan contains a duplicate result ordinal")
        output[ordinal] = item
    return output


def _live_occurrence(
    *,
    result_ordinal: object,
    occurrence_index: dict[int, ValueProjectionPlanOccurrenceV1],
) -> ValueProjectionPlanOccurrenceV1 | None:
    if result_ordinal is None:
        return None
    if type(result_ordinal) is not int:
        _fail("independent live decoded result ordinal is invalid")
    occurrence = occurrence_index.get(result_ordinal)
    if occurrence is None:
        _fail("independent live decoding cannot identify one exact planned occurrence")
    return occurrence


def _live_material(
    *,
    observation_sha256: str,
    occurrence: ValueProjectionPlanOccurrenceV1 | None,
    record_kind: str,
    payload: dict[str, object],
    source_identity_sha256: str,
    occurrence_node_keys: set[int],
) -> _MaterializedRecord:
    coordinate = _empty_coordinate() if occurrence is None else _result_coordinate(occurrence)
    if record_kind == "result_declaration":
        coordinate.update(
            {
                "declaration_parent_result_name": payload["parent_result_set_name"],
                "declaration_parent_field_name": payload["parent_field_name"],
            }
        )
        value_shape: dict[str, object] = {"value_state": "absent"}
    elif record_kind == "result_occurrence":
        coordinate.update(
            {
                "node_ordinal": payload["node_ordinal"],
                "json_path": payload["json_path"],
                "result_occurrence_global_ordinal": payload["global_ordinal"],
                "result_occurrence_ordinal": payload["occurrence_ordinal"],
                "result_occurrence_parent_result_name": payload["parent_result_set_name"],
                "result_occurrence_parent_result_ordinal": payload["parent_result_set_ordinal"],
                "result_occurrence_presence_kind": payload["presence_kind"],
                "result_occurrence_row_count": payload["row_count"],
                "decoder_value_sha256": payload["value_sha256"],
            }
        )
        value_shape = {"value_state": "absent"}
    elif record_kind == "node":
        coordinate.update(
            {
                "node_ordinal": payload["node_ordinal"],
                "parent_node_ordinal": payload["parent_node_ordinal"],
                "json_path": payload["json_path"],
                "parent_json_path": payload["parent_json_path"],
                "depth": payload["depth"],
                "object_key": payload["object_key"],
                "object_key_ordinal": payload["object_key_ordinal"],
                "array_ordinal": payload["array_ordinal"],
            }
        )
        if occurrence is not None:
            coordinate.update(
                {
                    "row_ordinal": payload["result_set_row_ordinal"],
                    "context_result_name": payload["result_set_name"],
                    "context_result_ordinal": payload["result_set_ordinal"],
                    "context_result_occurrence": payload["result_set_occurrence"],
                    "known_contract_field": payload["known_contract_field"],
                    "decoder_value_sha256": payload["value_sha256"],
                    "matches_result_occurrence": cast("int", payload["node_ordinal"])
                    in occurrence_node_keys,
                }
            )
        value_shape = _node_value_shape(
            presence_kind=cast("str", payload["presence_kind"]),
            value_kind=cast("str", payload["value_kind"]),
            canonical_json=cast("str | None", payload["canonical_json"]),
        )
    elif record_kind == "field_cell":
        coordinate.update(
            {
                "field_name": payload["field_name"],
                "field_ordinal": payload["field_ordinal"],
                "row_ordinal": payload["owner_row_ordinal"],
                "cell_ordinal": payload["cell_ordinal"],
                "value_duplicate_ordinal": None,
                "node_ordinal": payload["node_ordinal"],
                "json_path": payload["concrete_json_path"],
                "key_presence": payload["key_presence"],
                "owner_result_name": payload["owner_result_set_name"],
                "owner_result_ordinal": payload["owner_result_set_ordinal"],
                "owner_result_occurrence": payload["owner_result_set_occurrence"],
                "context_result_name": payload["context_result_set_name"],
                "context_result_ordinal": payload["context_result_set_ordinal"],
                "context_result_occurrence": payload["context_result_set_occurrence"],
                "known_contract_field": True,
                "decoder_value_sha256": payload["value_sha256"],
            }
        )
        value_shape = _node_value_shape(
            presence_kind=cast("str", payload["presence_kind"]),
            value_kind=cast("str", payload["value_kind"]),
            canonical_json=cast("str | None", payload["canonical_json"]),
        )
    else:
        _fail("independent live decoding contains a foreign record kind")
    return _MaterializedRecord(
        observation_sha256=observation_sha256,
        occurrence_sha256=None if occurrence is None else occurrence.occurrence_sha256,
        record_kind=record_kind,
        coordinate=coordinate,
        value_shape=value_shape,
        source_identity_sha256=source_identity_sha256,
    )


def _materialize_live(
    *,
    observation: RequestObservationV2,
    parser_input: bytes,
    occurrence_plans: tuple[ValueProjectionPlanOccurrenceV1, ...],
) -> tuple[tuple[_MaterializedRecord, ...], str]:
    try:
        decoded_source = decode_live_value_response(
            parser_input,
            endpoint_id=observation.attempt.endpoint_id,
            endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
        )
        decoded = validate_decoded_live_response(decoded_source)
        if (
            type(decoded) is not DecodedLiveResponseV1
            or decoded != decoded_source
            or decoded.endpoint_id != observation.attempt.endpoint_id
            or decoded.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256
            or decoded.parser_input_sha256 != hashlib.sha256(parser_input).hexdigest()
            or decoded.parser_input_length != len(parser_input)
        ):
            _fail("independent live body decoder differs from exact source bytes")
    except Exception:  # noqa: BLE001 - collapse the untrusted decoder boundary
        _fail("independent live body decoding failed")
    occurrence_index = _live_occurrence_index(occurrence_plans)
    occurrence_node_keys = {item.node_ordinal for item in decoded.result_occurrences}
    output: list[_MaterializedRecord] = []
    inventories: tuple[tuple[str, tuple[object, ...]], ...] = (
        ("result_declaration", cast("tuple[object, ...]", decoded.result_sets)),
        ("result_occurrence", cast("tuple[object, ...]", decoded.result_occurrences)),
        ("node", cast("tuple[object, ...]", decoded.nodes)),
        ("field_cell", cast("tuple[object, ...]", decoded.field_cells)),
    )
    digest_names = {
        "result_declaration": "result_set_sha256",
        "result_occurrence": "occurrence_sha256",
        "node": "node_sha256",
        "field_cell": "cell_sha256",
    }
    for record_kind, inventory in inventories:
        for item in inventory:
            if record_kind == "result_declaration":
                if type(item) is not DecodedLiveResultSetV1:
                    _fail("independent live result declaration has a foreign DTO")
                payload = item.to_dict()
                result_ordinal = payload["ordinal"]
            elif record_kind == "result_occurrence":
                if type(item) is not DecodedLiveResultOccurrenceV1:
                    _fail("independent live result occurrence has a foreign DTO")
                payload = item.to_dict()
                result_ordinal = payload["result_set_ordinal"]
            elif record_kind == "node":
                if type(item) is not DecodedLiveNodeV1:
                    _fail("independent live node has a foreign DTO")
                payload = item.to_dict()
                result_ordinal = payload["result_set_ordinal"]
            else:
                if type(item) is not DecodedLiveFieldCellV1:
                    _fail("independent live field cell has a foreign DTO")
                payload = item.to_dict()
                result_ordinal = payload["owner_result_set_ordinal"]
            occurrence = _live_occurrence(
                result_ordinal=result_ordinal,
                occurrence_index=occurrence_index,
            )
            output.append(
                _live_material(
                    observation_sha256=observation.attempt.observation_sha256,
                    occurrence=occurrence,
                    record_kind=record_kind,
                    payload=payload,
                    source_identity_sha256=cast("str", payload[digest_names[record_kind]]),
                    occurrence_node_keys=occurrence_node_keys,
                )
            )
    return tuple(output), decoded.response_sha256


def _ownership_receipt_row(plan: ValueProjectionPlanV1) -> dict[str, object]:
    result = tuple(
        item for item in plan.ownership_partitions if item.partition_kind == "result_occurrence"
    )
    residual = tuple(
        item for item in plan.ownership_partitions if item.partition_kind == "response_residual"
    )
    fixed = tuple(
        item for item in plan.ownership_partitions if item.partition_kind == "response_fixed_zero"
    )
    fixed_ids = tuple(cast("str", item.fixed_zero_landing_sha256) for item in fixed)
    return {
        "schema_version": 1,
        "receipt_sha256": plan.ownership_receipt_sha256,
        "raw_authority_bundle_sha256": plan.raw_authority_bundle_sha256,
        "expected_unit_count": plan.expected_unit_count,
        "expected_unit_inventory_sha256": plan.expected_unit_inventory_sha256,
        "expected_unit_root_sha256": plan.expected_unit_authority_root_sha256,
        "representation_assignment_count": plan.assignment_count,
        "representation_assignment_root_sha256": plan.ownership_assignment_root_sha256,
        "observation_count": plan.observation_count,
        "observation_root_sha256": plan.ownership_observation_root_sha256,
        "partition_count": plan.partition_count,
        "partition_root_sha256": plan.ownership_partition_root_sha256,
        "result_occurrence_partition_count": len(result),
        "zero_result_occurrence_partition_count": sum(item.record_count == 0 for item in result),
        "result_occurrence_record_count": sum(item.record_count for item in result),
        "response_residual_partition_count": len(residual),
        "positive_response_residual_partition_count": sum(
            item.record_count > 0 for item in residual
        ),
        "zero_response_residual_partition_count": sum(item.record_count == 0 for item in residual),
        "response_residual_record_count": sum(item.record_count for item in residual),
        "response_fixed_zero_partition_count": len(fixed),
        "fixed_zero_landing_root_sha256": _legacy_root(
            kind="nbadb_lossless_fixed_zero_landings_v1", values=fixed_ids
        ),
        "binding_count": plan.binding_count,
        "binding_root_sha256": plan.ownership_binding_root_sha256,
        "source_record_count": plan.source_record_count,
        "source_record_root_sha256": plan.ownership_source_record_root_sha256,
    }


def _replay_ownership(
    value: object,
    *,
    expected_bundle: str,
    expected_receipt: str,
) -> LosslessOwnershipAuthorityV1:
    if type(value) is not LosslessOwnershipAuthorityV1:
        _fail("independent body projection ownership has a foreign exact DTO")
    try:
        exact = build_lossless_ownership_authority(
            raw_authority_bundle_sha256=expected_bundle,
            expected_unit_inventory=value.expected_unit_inventory,
            representation_assignments=value.representation_assignments,
            observations=value.observations,
            partitions=value.partitions,
            bindings=value.bindings,
        )
    except (AttributeError, LosslessOwnershipError, MemoryError, RecursionError, TypeError):
        _fail("independent body projection ownership failed exact replay")
    if type(exact) is not LosslessOwnershipAuthorityV1:
        _fail("independent body projection ownership replay returned a foreign DTO")
    if exact != value or exact.receipt.receipt_sha256 != expected_receipt:
        _fail("independent body projection ownership differs from its external pin")
    return exact


def _replay_body_blob_readback(
    value: object,
) -> BodyBlobInventoryReadbackReceiptV1:
    if type(value) is not BodyBlobInventoryReadbackReceiptV1:
        _fail("independent body projection body readback has a foreign exact DTO")
    try:
        exact = BodyBlobInventoryReadbackReceiptV1(
            **{
                item.name: getattr(value, item.name)
                for item in fields(BodyBlobInventoryReadbackReceiptV1)
            }
        )
    except (
        AttributeError,
        BodyBlobAuthorityError,
        IndependentBodyValueProjectionBuilderError,
        MemoryError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        _fail("independent body projection body readback failed exact DTO replay")
    if exact != value:
        _fail("independent body projection body readback differs from exact DTO replay")
    return exact


def _assert_plan_matches_ownership(
    plan: ValueProjectionPlanV1, ownership: LosslessOwnershipAuthorityV1
) -> None:
    pairs = (
        (plan.expected_units, ownership.expected_unit_inventory.units),
        (plan.assignments, ownership.representation_assignments),
        (plan.ownership_observations, ownership.observations),
        (plan.ownership_partitions, ownership.partitions),
        (plan.ownership_bindings, ownership.bindings),
    )
    if any(
        tuple(item.to_row() for item in left) != tuple(item.to_row() for item in right)
        for left, right in pairs
    ):
        _fail("independent body projection plan differs from central ownership")


def _item_kwargs(
    source: ValueProjectionPlanSourceRecordV1,
    *,
    partition_item_ordinal: int,
) -> dict[str, object]:
    return {
        "raw_authority_bundle_sha256": source.raw_authority_bundle_sha256,
        "ownership_binding_sha256": source.binding_sha256,
        "ownership_binding_ordinal": source.binding_ordinal,
        "source_record_sha256": source.source_record_sha256,
        "observation_record_sha256": source.observation_record_sha256,
        "observation_sha256": source.observation_sha256,
        "observation_ordinal": source.observation_ordinal,
        "ownership_partition_sha256": source.partition_sha256,
        "partition_ordinal": source.partition_ordinal,
        "unit_sha256": source.unit_sha256,
        "unit_ordinal": source.unit_ordinal,
        "assignment_sha256": source.assignment_sha256,
        "source_input_kind": source.source_input_kind,
        "representation_kind": source.representation_kind,
        "unit_kind": source.unit_kind,
        "occurrence_sha256": source.occurrence_sha256,
        "occurrence_ordinal": source.occurrence_ordinal,
        "global_item_ordinal": source.source_record_plan_ordinal,
        "partition_item_ordinal": partition_item_ordinal,
        "record_kind": source.projection_record_kind,
    }


def build_independent_body_value_projection(
    raw_bundle: object,
    *,
    expected_raw_authority_bundle_sha256: object,
    ownership_authority: object,
    expected_ownership_receipt_sha256: object,
    plan: object,
    expected_plan_sha256: object,
    body_blob_inventory: object,
    expected_body_blob_inventory_sha256: object,
    body_blob_inventory_readback_receipt: object,
    expected_body_blob_inventory_readback_receipt_sha256: object,
    declared_bodyless_packets: object,
    expected_declared_bodyless_packet_authority_sha256s: object,
    declared_bodyless_readback_receipts: object,
    expected_declared_bodyless_readback_receipt_sha256s: object,
    declared_bodyless_packet_bytes: object,
    known_secrets: Sequence[str | bytes] = (),
) -> IndependentBodyValueProjectionV1:
    """Build the complete independent body projection from immutable source bytes."""

    expected_bundle = _sha256(
        expected_raw_authority_bundle_sha256, label="expected Raw Authority bundle"
    )
    expected_ownership = _sha256(
        expected_ownership_receipt_sha256, label="expected ownership receipt"
    )
    expected_plan = _sha256(expected_plan_sha256, label="expected projection plan")
    expected_inventory = _sha256(
        expected_body_blob_inventory_sha256, label="expected body-blob inventory"
    )
    expected_body_readback = _sha256(
        expected_body_blob_inventory_readback_receipt_sha256,
        label="expected body-blob readback",
    )
    packet_pins = _pin_sha_tuple(
        expected_declared_bodyless_packet_authority_sha256s,
        label="expected declared-bodyless packet",
    )
    readback_pins = _pin_sha_tuple(
        expected_declared_bodyless_readback_receipt_sha256s,
        label="expected declared-bodyless readback",
    )
    secrets = _known_secret_bytes(known_secrets)
    if type(raw_bundle) is not RawRequestAuthorityBundleV2:
        _fail("independent body projection Raw authority has a foreign exact DTO")
    if type(ownership_authority) is not LosslessOwnershipAuthorityV1:
        _fail("independent body projection ownership has a foreign exact DTO")
    if type(plan) is not ValueProjectionPlanV1:
        _fail("independent body projection plan has a foreign exact DTO")
    if type(body_blob_inventory) is not BodyBlobInventoryV1:
        _fail("independent body projection body inventory has a foreign exact DTO")
    if type(body_blob_inventory_readback_receipt) is not BodyBlobInventoryReadbackReceiptV1:
        _fail("independent body projection body readback has a foreign exact DTO")
    if (
        type(declared_bodyless_packets) is not tuple
        or type(declared_bodyless_readback_receipts) is not tuple
        or type(declared_bodyless_packet_bytes) is not tuple
    ):
        _fail("independent body projection bodyless inputs must be exact tuples")
    if (
        len(packet_pins) != len(readback_pins)
        or len(packet_pins) != len(declared_bodyless_packets)
        or len(packet_pins) != len(declared_bodyless_readback_receipts)
        or len(packet_pins) != len(declared_bodyless_packet_bytes)
        or len(declared_bodyless_packets) > MAX_VALUE_PROJECTION_OBSERVATIONS
    ):
        _fail("independent body projection bodyless denominators differ")
    if any(type(item) is not DeclaredBodylessPacketV1 for item in declared_bodyless_packets):
        _fail("independent body projection contains a foreign bodyless packet DTO")
    if any(
        type(item) is not DeclaredBodylessPacketReadbackReceiptV1
        for item in declared_bodyless_readback_receipts
    ):
        _fail("independent body projection contains a foreign bodyless readback DTO")
    if any(type(item) is not bytes for item in declared_bodyless_packet_bytes):
        _fail("independent body projection contains foreign bodyless packet bytes")
    packet_inputs = cast("tuple[DeclaredBodylessPacketV1, ...]", declared_bodyless_packets)
    readback_inputs = cast(
        "tuple[DeclaredBodylessPacketReadbackReceiptV1, ...]",
        declared_bodyless_readback_receipts,
    )
    bodyless_payload_inputs = cast("tuple[bytes, ...]", declared_bodyless_packet_bytes)
    try:
        if (
            raw_bundle.bundle_sha256 != expected_bundle
            or ownership_authority.receipt.receipt_sha256 != expected_ownership
            or plan.plan_sha256 != expected_plan
            or plan.raw_authority_bundle_sha256 != expected_bundle
            or plan.ownership_receipt_sha256 != expected_ownership
            or body_blob_inventory.inventory_sha256 != expected_inventory
            or body_blob_inventory_readback_receipt.receipt_sha256 != expected_body_readback
            or tuple(item.packet_authority_sha256 for item in packet_inputs) != packet_pins
            or tuple(item.receipt_sha256 for item in readback_inputs) != readback_pins
        ):
            _fail("independent body projection input differs from its external pin")
    except IndependentBodyValueProjectionBuilderError:
        raise
    except (AttributeError, TypeError):
        _fail("independent body projection input fields are invalid")
    try:
        bundle = validate_raw_request_authority_bundle(raw_bundle)
        if (
            type(bundle) is not RawRequestAuthorityBundleV2
            or bundle != raw_bundle
            or bundle.bundle_sha256 != expected_bundle
        ):
            _fail("independent body projection Raw authority differs from exact replay")
        bundle.require_complete_terminal_selection()
        exact_plan = validate_value_projection_plan(
            plan,
            expected_plan_sha256=expected_plan,
            expected_raw_authority_bundle_sha256=expected_bundle,
            expected_ownership_receipt_sha256=expected_ownership,
        )
        if (
            type(exact_plan) is not ValueProjectionPlanV1
            or exact_plan != plan
            or exact_plan.plan_sha256 != expected_plan
        ):
            _fail("independent body projection plan differs from exact replay")
        ownership = _replay_ownership(
            ownership_authority,
            expected_bundle=expected_bundle,
            expected_receipt=expected_ownership,
        )
        _assert_plan_matches_ownership(exact_plan, ownership)
        inventory = validate_body_blob_inventory(
            body_blob_inventory,
            bundle=bundle,
            expected_raw_authority_bundle_sha256=expected_bundle,
            expected_inventory_sha256=expected_inventory,
            known_secrets=known_secrets,
        )
        if (
            type(inventory) is not BodyBlobInventoryV1
            or inventory != body_blob_inventory
            or inventory.inventory_sha256 != expected_inventory
        ):
            _fail("independent body projection body inventory differs from exact replay")
        supplied_body_readback = _replay_body_blob_readback(body_blob_inventory_readback_receipt)
        rebuilt_body_readback = BodyBlobInventoryReadbackReceiptV1.build(
            inventory=inventory,
            file_readbacks=supplied_body_readback.file_readbacks,
            observation_readbacks=supplied_body_readback.observation_readbacks,
            store_namespace_sha256=supplied_body_readback.store_namespace_sha256,
            expected_raw_authority_bundle_sha256=expected_bundle,
            expected_inventory_sha256=expected_inventory,
        )
        if type(rebuilt_body_readback) is not BodyBlobInventoryReadbackReceiptV1:
            _fail("independent body projection body readback replay returned a foreign DTO")
        exact_body_readback = _replay_body_blob_readback(rebuilt_body_readback)
        if (
            exact_body_readback != supplied_body_readback
            or exact_body_readback.receipt_sha256 != expected_body_readback
        ):
            _fail("independent body projection body readback differs from exact replay")
    except Exception:  # noqa: BLE001 - collapse the entire untrusted child replay boundary
        _fail("independent body projection authority replay failed")

    parser_sources = tuple(
        item
        for item in exact_plan.observation_sources
        if item.source_input_kind == "parser_input_body"
    )
    bodyless_sources = tuple(
        item
        for item in exact_plan.observation_sources
        if item.source_input_kind == "declared_bodyless_packet"
    )
    file_readback_by_descriptor = {
        item.descriptor_sha256: item for item in rebuilt_body_readback.file_readbacks
    }
    selected_readback_by_observation = {
        item.observation_sha256: item
        for item in rebuilt_body_readback.observation_readbacks
        if item.selection == "selected_terminal"
    }
    if len(selected_readback_by_observation) != len(parser_sources):
        _fail("independent body projection selected readback denominator differs")
    parser_source_proofs = []
    for source in parser_sources:
        observation_readback = selected_readback_by_observation.get(source.observation_sha256)
        file_readback = (
            None
            if observation_readback is None
            else file_readback_by_descriptor.get(observation_readback.descriptor_sha256)
        )
        if (
            observation_readback is None
            or file_readback is None
            or observation_readback.observation_record_sha256 != source.observation_record_sha256
            or source.body_blob_sha256 != file_readback.blob_sha256
            or source.body_blob_readback_sha256 != observation_readback.receipt_sha256
            or source.parser_input_object_sha256 != file_readback.parser_input_object_sha256
            or source.payload_sha256 != file_readback.response_sha256
            or source.payload_byte_count != file_readback.uncompressed_bytes
        ):
            _fail("independent body projection plan differs from exact body readback")
        parser_source_proofs.append((source, observation_readback, file_readback))
    if len(bodyless_sources) != len(packet_pins):
        _fail("independent body projection plan/bodyless denominator differs")
    declared_authority = _replay_declared_bodyless_authority(
        _build_declared_bodyless_projection_authority(
            raw_authority_bundle_sha256=expected_bundle,
            packets=packet_inputs,
            expected_packet_authority_sha256s=packet_pins,
            readbacks=readback_inputs,
            expected_readback_receipt_sha256s=readback_pins,
            packet_bytes=bodyless_payload_inputs,
            expected_observation_sha256s=tuple(
                item.observation_sha256 for item in bodyless_sources
            ),
            expected_observation_record_sha256s=tuple(
                item.observation_record_sha256 for item in bodyless_sources
            ),
            known_secrets=known_secrets,
        )
    )
    for source, packet, readback, payload in zip(
        bodyless_sources,
        packet_inputs,
        readback_inputs,
        bodyless_payload_inputs,
        strict=True,
    ):
        if (
            source.bodyless_packet_sha256 != packet.packet_authority_sha256
            or source.bodyless_readback_sha256 != readback.receipt_sha256
            or source.payload_sha256 != hashlib.sha256(payload).hexdigest()
            or source.payload_byte_count != len(payload)
        ):
            _fail("independent body projection bodyless source differs from the exact plan")

    observations_by_sha = {
        item.attempt.observation_sha256: item
        for item in bundle.observations
        if item.lifecycle == "selected_terminal"
    }
    objects_by_sha = {item.object_sha256: item for item in bundle.objects}
    if len(observations_by_sha) != exact_plan.observation_count or len(objects_by_sha) != len(
        bundle.objects
    ):
        _fail("independent body projection Raw source inventory is duplicate or incomplete")
    occurrence_lists: dict[str, list[ValueProjectionPlanOccurrenceV1]] = {
        item.observation_sha256: [] for item in exact_plan.observation_sources
    }
    source_lists: dict[str, list[ValueProjectionPlanSourceRecordV1]] = {
        item.observation_sha256: [] for item in exact_plan.observation_sources
    }
    if len(occurrence_lists) != len(exact_plan.observation_sources):
        _fail("independent body projection contains duplicate observation sources")
    for occurrence in exact_plan.occurrence_plans:
        target = occurrence_lists.get(occurrence.observation_sha256)
        if target is None:
            _fail("independent body projection occurrence references a foreign observation")
        target.append(occurrence)
    for source_record in exact_plan.source_record_plans:
        target = source_lists.get(source_record.observation_sha256)
        if target is None:
            _fail("independent body projection source record references a foreign observation")
        target.append(source_record)
    occurrence_by_observation = {key: tuple(value) for key, value in occurrence_lists.items()}
    source_by_observation = {key: tuple(value) for key, value in source_lists.items()}
    positive_residual_partition_by_observation: dict[str, int] = {}
    for partition in exact_plan.ownership_partitions:
        if partition.partition_kind != "response_residual" or partition.record_count == 0:
            continue
        if partition.observation_sha256 in positive_residual_partition_by_observation:
            _fail("independent body projection has duplicate positive response residuals")
        positive_residual_partition_by_observation[partition.observation_sha256] = (
            partition.partition_ordinal
        )
    bodyless_payload_by_observation = dict(
        zip(
            (item.observation_sha256 for item in bodyless_sources),
            bodyless_payload_inputs,
            strict=True,
        )
    )

    materialized: list[_MaterializedRecord] = []
    stats_slots: dict[int, tuple[dict[str, object], ...]] = {}
    residual_outputs: dict[int, str] = {}
    independent_source_ids: set[tuple[str, str]] = set()
    for source in exact_plan.observation_sources:
        observation = observations_by_sha.get(source.observation_sha256)
        if (
            observation is None
            or observation.observation_record_sha256 != source.observation_record_sha256
        ):
            _fail("independent body projection plan references a foreign Raw observation")
        occurrence_plans = occurrence_by_observation[source.observation_sha256]
        source_plans = source_by_observation[source.observation_sha256]
        if source.source_input_kind == "parser_input_body":
            object_sha = source.parser_input_object_sha256
            body = None if object_sha is None else objects_by_sha.get(object_sha)
            if type(body) is not ParserInputObjectV2:
                _fail("independent body projection parser source is missing")
            try:
                parser_input = decode_parser_input_object(body)
                if type(parser_input) is not bytes:
                    _fail("independent body projection parser replay returned foreign bytes")
            except Exception:  # noqa: BLE001 - collapse the untrusted Raw object boundary
                _fail("independent body projection parser source failed exact replay")
            _reject_known_secrets(parser_input, secrets=secrets)
            if (
                source.payload_sha256 != hashlib.sha256(parser_input).hexdigest()
                or source.payload_byte_count != len(parser_input)
                or source.payload_sha256 != body.response_sha256
            ):
                _fail("independent body projection parser bytes differ from the exact plan")
            if source.source_family == "stats":
                records, observation_slots, residual_output = _materialize_stats(
                    observation=observation,
                    parser_input=parser_input,
                    occurrence_plans=occurrence_plans,
                    source_plans=source_plans,
                )
                stats_slots.update(observation_slots)
            elif source.source_family == "live":
                records, residual_output = _materialize_live(
                    observation=observation,
                    parser_input=parser_input,
                    occurrence_plans=occurrence_plans,
                )
            else:
                _fail("parser-input source has a foreign family")
        else:
            payload = bodyless_payload_by_observation.get(source.observation_sha256)
            if payload is None or source.source_family != "static":
                _fail("declared-bodyless source has a foreign family or missing bytes")
            records = _materialize_static(
                observation=observation,
                packet_bytes=payload,
                occurrence_plans=occurrence_plans,
            )
            residual_output = hashlib.sha256(payload).hexdigest()
        if len(records) != len(source_plans):
            _fail("independent body decoding source-record denominator differs from the plan")
        for decoded_record, source_plan in zip(records, source_plans, strict=True):
            if (
                decoded_record.observation_sha256 != source_plan.observation_sha256
                or decoded_record.occurrence_sha256 != source_plan.occurrence_sha256
                or decoded_record.record_kind != source_plan.projection_record_kind
            ):
                _fail("independent body decoding source-record order differs from the plan")
            source_identity_key = (
                decoded_record.observation_sha256,
                decoded_record.source_identity_sha256,
            )
            if source_identity_key in independent_source_ids:
                _fail("independent body decoding contains a duplicate source identity")
            independent_source_ids.add(source_identity_key)
        materialized.extend(records)
        residual_partition_ordinal = positive_residual_partition_by_observation.get(
            source.observation_sha256
        )
        if residual_partition_ordinal is not None:
            residual_outputs[residual_partition_ordinal] = residual_output

    if len(materialized) != len(exact_plan.source_record_plans):
        _fail("independent body projection materialized record inventory is incomplete")
    partition_by_ordinal = {
        item.partition_ordinal: item for item in exact_plan.ownership_partitions
    }
    occurrence_by_partition = {item.partition_ordinal: item for item in exact_plan.occurrence_plans}
    assignment_by_sha = {item.assignment_sha256: item for item in exact_plan.assignments}
    observation_by_ordinal = {
        item.observation_ordinal: item for item in exact_plan.ownership_observations
    }
    partition_local: dict[int, int] = {
        item.partition_ordinal: 0 for item in exact_plan.ownership_partitions
    }
    live_field_duplicates: dict[tuple[int, int, str], int] = {}
    live_cell_ordinals: dict[int, int] = {
        item.partition_ordinal: 0 for item in exact_plan.ownership_partitions
    }
    items: list[ValueProjectionItemV1] = []
    for source, decoded_record in zip(exact_plan.source_record_plans, materialized, strict=True):
        partition = partition_by_ordinal[source.partition_ordinal]
        coordinate = dict(decoded_record.coordinate)
        if (
            source.source_relation_kind == "live_lossless_node_v1"
            and source.projection_record_kind == "field_cell"
        ):
            field_ordinal = cast("int", coordinate["field_ordinal"])
            value_digest = cast("str", coordinate["decoder_value_sha256"])
            duplicate_key = (source.partition_ordinal, field_ordinal, value_digest)
            duplicate_ordinal = live_field_duplicates.get(duplicate_key, 0)
            coordinate["value_duplicate_ordinal"] = duplicate_ordinal
            live_field_duplicates[duplicate_key] = duplicate_ordinal + 1
            coordinate["cell_ordinal"] = live_cell_ordinals[source.partition_ordinal]
            live_cell_ordinals[source.partition_ordinal] += 1
        local = partition_local[source.partition_ordinal]
        try:
            item = ValueProjectionItemV1.build(
                **cast("Any", _item_kwargs(source, partition_item_ordinal=local)),
                coordinate=coordinate,
                **cast("Any", decoded_record.value_shape),
            )
            if type(item) is not ValueProjectionItemV1:
                _fail("independent body item builder returned a foreign DTO")
            exact_item = ValueProjectionItemV1.from_row(item.to_row())
            if exact_item != item:
                _fail("independent body item differs from exact DTO replay")
            item = exact_item
        except Exception:  # noqa: BLE001 - collapse the untrusted item-builder boundary
            _fail("independent body source cannot form its exact projection item")
        items.append(item)
        partition_local[source.partition_ordinal] = local + 1

    items_by_partition: dict[int, list[ValueProjectionItemV1]] = {
        item.partition_ordinal: [] for item in exact_plan.ownership_partitions
    }
    for item in items:
        items_by_partition[item.partition_ordinal].append(item)
    partitions: list[ValueProjectionPartitionV1] = []
    for partition in exact_plan.ownership_partitions:
        partition_items = tuple(items_by_partition[partition.partition_ordinal])
        occurrence = occurrence_by_partition.get(partition.partition_ordinal)
        assignment = (
            None
            if partition.assignment_sha256 is None
            else assignment_by_sha[partition.assignment_sha256]
        )
        values: dict[str, object] = {
            "raw_authority_bundle_sha256": expected_bundle,
            "ownership_partition_sha256": partition.partition_sha256,
            "observation_record_sha256": partition.observation_record_sha256,
            "observation_sha256": partition.observation_sha256,
            "observation_ordinal": partition.observation_ordinal,
            "partition_ordinal": partition.partition_ordinal,
            "observation_partition_ordinal": partition.observation_partition_ordinal,
            "partition_kind": partition.partition_kind,
            "source_input_kind": observation_by_ordinal[
                partition.observation_ordinal
            ].source_input_kind,
            "items": partition_items,
            "occurrence_sha256": partition.occurrence_sha256,
            "occurrence_ordinal": partition.occurrence_ordinal,
            "unit_sha256": partition.unit_sha256,
            "unit_ordinal": partition.unit_ordinal,
            "assignment_sha256": partition.assignment_sha256,
            "representation_kind": None if assignment is None else assignment.representation_kind,
            "fixed_zero_landing_sha256": partition.fixed_zero_landing_sha256,
        }
        if occurrence is not None:
            values.update(
                {
                    "result_name": occurrence.result_name,
                    "result_duplicate_ordinal": occurrence.result_duplicate_ordinal,
                    "provider_result_ordinal": occurrence.provider_result_ordinal,
                    "expected_result_ordinal": occurrence.expected_result_ordinal,
                    "canonical_result_ordinal": occurrence.canonical_result_ordinal,
                    "result_path": _result_path(occurrence),
                    "container_kind": occurrence.container_kind,
                    "result_presence": occurrence.result_presence,
                    "row_count": occurrence.row_count,
                    "cell_count": occurrence.cell_count,
                    "representation_output_sha256": occurrence.representation_output_sha256,
                }
            )
            if occurrence.representation_kind == "stats_lossless_records_v1":
                slot_inventory = stats_slots.get(partition.partition_ordinal)
                if slot_inventory is None:
                    _fail("independent stats partition lacks its decoded header slots")
                values.update(
                    {
                        "ordered_header_slots": slot_inventory,
                        "header_record_count": sum(
                            item.record_kind == "header" for item in partition_items
                        ),
                        "header_slot_count": len(slot_inventory),
                    }
                )
            else:
                values.update(
                    {
                        "ordered_headers": occurrence.ordered_headers(),
                        "header_count": occurrence.header_count,
                    }
                )
            if occurrence.representation_kind == "live_lossless_nodes_v1":
                values.update(
                    {
                        "field_count": occurrence.header_count,
                        "node_count": sum(item.record_kind == "node" for item in partition_items),
                    }
                )
        elif partition.record_count > 0:
            output = residual_outputs.get(partition.partition_ordinal)
            if output is None:
                _fail("independent response residual lacks its decoder output")
            values.update(
                {
                    "node_count": sum(
                        item.record_kind in {"node", "json_node"} for item in partition_items
                    ),
                    "representation_output_sha256": output,
                }
            )
        try:
            built_partition = ValueProjectionPartitionV1.build(**cast("Any", values))
            if type(built_partition) is not ValueProjectionPartitionV1:
                _fail("independent body partition builder returned a foreign DTO")
            exact_partition = ValueProjectionPartitionV1.from_row(built_partition.to_row())
            if exact_partition != built_partition:
                _fail("independent body partition differs from exact DTO replay")
            partitions.append(exact_partition)
        except Exception:  # noqa: BLE001 - collapse the untrusted partition-builder boundary
            _fail("independent body source cannot form its exact projection partition")

    exact_items = tuple(items)
    exact_partitions = tuple(partitions)
    try:
        projection = ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=expected_bundle,
            ownership_receipt_row=_ownership_receipt_row(exact_plan),
            expected_unit_rows=tuple(item.to_row() for item in exact_plan.expected_units),
            representation_assignment_rows=tuple(item.to_row() for item in exact_plan.assignments),
            ownership_observation_rows=tuple(
                item.to_row() for item in exact_plan.ownership_observations
            ),
            ownership_partition_rows=tuple(
                item.to_row() for item in exact_plan.ownership_partitions
            ),
            ownership_binding_rows=tuple(item.to_row() for item in exact_plan.ownership_bindings),
            partitions=exact_partitions,
            items=exact_items,
        )
        if type(projection) is not ValueProjectionReceiptV1:
            _fail("independent body projection builder returned a foreign DTO")
        exact_projection = ValueProjectionReceiptV1.from_row(projection.to_row())
        if exact_projection != projection:
            _fail("independent body projection differs from exact DTO replay")
        projection = exact_projection
        receipt = BodyValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=expected_bundle,
            body_projection_policy_sha256=INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256,
            body_blob_inventory_sha256=rebuilt_body_readback.inventory_sha256,
            declared_bodyless_authority_sha256=declared_authority.authority_sha256,
            expected_projection_sha256=projection.projection_sha256,
            projection=projection,
            body_blob_sha256s=tuple(
                file_readback.blob_sha256
                for _source, _observation_readback, file_readback in parser_source_proofs
            ),
            body_blob_readback_sha256s=tuple(
                observation_readback.receipt_sha256
                for _source, observation_readback, _file_readback in parser_source_proofs
            ),
            parser_input_object_sha256s=tuple(
                file_readback.parser_input_object_sha256
                for _source, _observation_readback, file_readback in parser_source_proofs
            ),
            body_blob_byte_count=sum(
                file_readback.uncompressed_bytes
                for _source, _observation_readback, file_readback in parser_source_proofs
            ),
            bodyless_packet_sha256s=tuple(
                cast("str", item.bodyless_packet_sha256) for item in bodyless_sources
            ),
            bodyless_readback_sha256s=tuple(
                cast("str", item.bodyless_readback_sha256) for item in bodyless_sources
            ),
            bodyless_packet_byte_count=sum(item.payload_byte_count for item in bodyless_sources),
            observation_source_sha256s=tuple(
                item.source_sha256 for item in exact_plan.observation_sources
            ),
        )
        if type(receipt) is not BodyValueProjectionReceiptV1:
            _fail("independent body receipt builder returned a foreign DTO")
        exact_receipt = BodyValueProjectionReceiptV1.from_row(receipt.to_row())
        if exact_receipt != receipt:
            _fail("independent body receipt differs from exact DTO replay")
        receipt = exact_receipt
    except Exception:  # noqa: BLE001 - collapse the untrusted aggregate-builder boundary
        _fail("independent body projection aggregate construction failed")
    return IndependentBodyValueProjectionV1(
        receipt=receipt,
        projection=projection,
        partitions=exact_partitions,
        items=exact_items,
        declared_bodyless_authority=declared_authority,
    )
