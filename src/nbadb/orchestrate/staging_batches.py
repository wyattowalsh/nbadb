from __future__ import annotations

import hashlib
import json
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

import polars as pl
import pyarrow as pa
import pyarrow.compute as pa_compute
import pyarrow.ipc as pa_ipc
from loguru import logger

from nbadb.core.errors import ParserInputCaptureIntegrityError, ResponseContractError
from nbadb.core.types import validate_sql_identifier
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.extract.live_lossless import (
    LIVE_LOSSLESS_SCHEMA,
    LIVE_LOSSLESS_STAGING_KEY,
    validate_live_lossless_frame,
)
from nbadb.extract.nba_api_adapter import (
    LOSSLESS_FALLBACK_SCHEMA,
    LOSSLESS_FALLBACK_STAGING_KEY,
    validate_lossless_fallback_frame,
)
from nbadb.orchestrate.staging_map import CONDITIONAL_STAGING_KEYS

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    import duckdb

_WRITE_LOCK = threading.Lock()
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
CANONICAL_FRAME_FORMAT: Final = "arrow_ipc_stream_v2_pyarrow_v5"
FRAME_CONTENT_HASH_CONTRACT: Final = "nbadb_arrow_logical_table_sha256_v2"
FRAME_SCHEMA_HASH_CONTRACT: Final = "nbadb_arrow_schema_sha256_v2"


def _require_frame_contract_ids(
    canonical_frame_format: object,
    frame_content_hash_contract: object,
    frame_schema_hash_contract: object,
    *,
    label: str,
) -> None:
    if (
        type(canonical_frame_format) is not str
        or canonical_frame_format != CANONICAL_FRAME_FORMAT
        or type(frame_content_hash_contract) is not str
        or frame_content_hash_contract != FRAME_CONTENT_HASH_CONTRACT
        or type(frame_schema_hash_contract) is not str
        or frame_schema_hash_contract != FRAME_SCHEMA_HASH_CONTRACT
    ):
        raise ParserInputCaptureIntegrityError(
            f"{label} uses stale or unsupported Arrow hash contract IDs; full restart required"
        )


def _domain_separated_sha256(contract_id: str, payload: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(b"nbadb-contract\x00")
    digest.update(contract_id.encode("ascii", errors="strict"))
    digest.update(b"\x00")
    digest.update(payload)
    return digest.hexdigest()


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ParserInputCaptureIntegrityError(f"{label} must be a lowercase SHA-256")
    return value


def _require_nonnegative_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ParserInputCaptureIntegrityError(f"{label} must be a nonnegative integer")
    return value


def _validate_persisted_lossless_fallback(frame: pl.DataFrame) -> None:
    if frame.columns != list(LOSSLESS_FALLBACK_SCHEMA) or dict(frame.schema) != (
        LOSSLESS_FALLBACK_SCHEMA
    ):
        raise ParserInputCaptureIntegrityError("lossless fallback frame failed its fixed contract")
    receipts = frame.get_column("response_receipt_sha256").drop_nulls().unique().to_list()
    if len(receipts) != 1 or not isinstance(receipts[0], str):
        raise ParserInputCaptureIntegrityError(
            "lossless fallback persistence requires one response receipt"
        )
    try:
        validate_lossless_fallback_frame(
            frame,
            expected_response_receipt_sha256=receipts[0],
        )
    except ResponseContractError as exc:
        raise ParserInputCaptureIntegrityError(
            "lossless fallback frame failed its fixed contract"
        ) from exc


def _validate_persisted_live_lossless(
    frame: pl.DataFrame,
    batch: StagingFrameBatch,
) -> None:
    """Validate every receipt-local live tree and its typed route authority."""

    from nbadb.contracts.staging_route_contract import (
        admit_conditional_live_lossless_route,
    )
    from nbadb.schemas.registry import get_input_schema

    if frame.columns != list(LIVE_LOSSLESS_SCHEMA) or dict(frame.schema) != (LIVE_LOSSLESS_SCHEMA):
        raise ParserInputCaptureIntegrityError("live-lossless frame failed its fixed node contract")
    binding = batch.receipt_binding
    endpoint_name = batch.metadata.source_endpoint_name
    route_mapping = dict(batch.result_route_ids_by_staging_key)
    if (
        binding is None
        or endpoint_name is None
        or len(route_mapping) != len(batch.result_route_ids_by_staging_key)
        or LIVE_LOSSLESS_STAGING_KEY not in route_mapping
    ):
        raise ParserInputCaptureIntegrityError(
            "live-lossless persistence requires exact source and receipt authority"
        )
    conditional_pairs = tuple(
        (key, route_id)
        for key, route_id in route_mapping.items()
        if key in CONDITIONAL_STAGING_KEYS
    )
    if conditional_pairs != (
        (LIVE_LOSSLESS_STAGING_KEY, route_mapping[LIVE_LOSSLESS_STAGING_KEY]),
    ):
        raise ParserInputCaptureIntegrityError(
            "live-lossless persistence cannot mix conditional route families"
        )
    static_route_ids = tuple(
        sorted(
            route_id
            for key, route_id in route_mapping.items()
            if key not in CONDITIONAL_STAGING_KEYS
        )
    )
    try:
        admission = admit_conditional_live_lossless_route(
            endpoint_name=endpoint_name,
            static_route_ids=static_route_ids,
            conditional_route_ids=(route_mapping[LIVE_LOSSLESS_STAGING_KEY],),
            provider_authority_sha256=binding.provider_authority_sha256,
        )
    except ValueError as exc:
        raise ParserInputCaptureIntegrityError(
            "live-lossless persistence route lacks typed live authority"
        ) from exc
    if frame.is_empty():
        raise ParserInputCaptureIntegrityError("live-lossless persistence requires response nodes")
    for column_name, expected_value in (
        ("provider_authority_sha256", admission.provider_authority_sha256),
        ("endpoint_contract_sha256", admission.endpoint_contract_sha256),
        ("endpoint_id", admission.provider_endpoint_id),
        ("endpoint_slug", admission.provider_endpoint_slug),
    ):
        if frame.get_column(column_name).unique().to_list() != [expected_value]:
            raise ParserInputCaptureIntegrityError(
                "live-lossless frame differs from its typed live authority"
            )
    request_parameters = frame.get_column("request_parameters_json").unique().to_list()
    try:
        request_parameters_sha256 = (
            admission.logical_parameters_sha256(request_parameters[0])
            if len(request_parameters) == 1 and isinstance(request_parameters[0], str)
            else None
        )
    except ValueError as exc:
        raise ParserInputCaptureIntegrityError(
            "live-lossless frame request scope differs from its typed live authority"
        ) from exc
    if request_parameters_sha256 != binding.logical_parameters_sha256:
        raise ParserInputCaptureIntegrityError(
            "live-lossless frame request scope differs from its logical-call receipt"
        )
    receipt_frames = frame.partition_by(
        "response_receipt_sha256",
        maintain_order=True,
    )
    if not receipt_frames:
        raise ParserInputCaptureIntegrityError("live-lossless frame has no response receipt")
    try:
        for receipt_frame in receipt_frames:
            receipts = receipt_frame.get_column("response_receipt_sha256").unique().to_list()
            snapshots = receipt_frame.get_column("snapshot_at").unique().to_list()
            if (
                len(receipts) != 1
                or not isinstance(receipts[0], str)
                or len(snapshots) != 1
                or snapshots[0] is None
            ):
                raise ParserInputCaptureIntegrityError(
                    "live-lossless response receipt or snapshot is ambiguous"
                )
            validate_live_lossless_frame(
                receipt_frame,
                expected_response_receipt_sha256=receipts[0],
                expected_result_set_count=admission.expected_result_set_count,
                expected_snapshot_at=snapshots[0],
                expected_endpoint_id=admission.provider_endpoint_id,
                expected_endpoint_slug=admission.provider_endpoint_slug,
            )
    except ResponseContractError as exc:
        raise ParserInputCaptureIntegrityError(
            "live-lossless frame failed its fixed node contract"
        ) from exc
    schema_cls = get_input_schema(LIVE_LOSSLESS_STAGING_KEY)
    if schema_cls is None:
        raise ParserInputCaptureIntegrityError("live-lossless staging schema is unavailable")
    try:
        normalized = schema_cls.validate(frame)
    except Exception as exc:
        raise ParserInputCaptureIntegrityError(
            "live-lossless frame failed its exact staging schema"
        ) from exc
    if (
        not isinstance(normalized, pl.DataFrame)
        or normalized.columns != frame.columns
        or dict(normalized.schema) != dict(frame.schema)
    ):
        raise ParserInputCaptureIntegrityError(
            "live-lossless staging validation changed its fixed schema"
        )


@dataclass(frozen=True, slots=True)
class StagingChunkMetadata:
    run_mode: str
    lane_id: str
    pattern: str
    chunk_index: int
    params_digest: str
    entries_digest: str
    source_endpoint_name: str | None = None
    source_params_digest: str | None = None

    @property
    def source_label(self) -> str:
        return f"{self.run_mode}:{self.pattern}:{self.lane_id}:{self.chunk_index}"


@dataclass(frozen=True, slots=True)
class StagingFrameBatch:
    frames: dict[str, pl.DataFrame]
    metadata: StagingChunkMetadata
    expected_staging_keys: tuple[str, ...] = ()
    dedupe_materialized: bool = False
    replace_existing_chunk: bool = False
    receipt_binding: LogicalCallReceiptBinding | None = None
    result_route_ids_by_staging_key: tuple[tuple[str, str], ...] = ()
    successor_generation_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class SourceScopeReplacementAttestation:
    """Durable proof that one route-local source scope was freshly replaced."""

    successor_generation_sha256: str
    source_scope_sha256: str
    staging_key: str
    canonical_frame_format: str
    frame_content_hash_contract: str
    frame_schema_hash_contract: str
    prior_persisted_content_sha256: str | None
    persisted_content_sha256: str
    persisted_schema_sha256: str
    persisted_row_count: int
    logical_call_receipt_sha256: str
    provider_authority_sha256: str
    logical_parameters_sha256: str
    result_route_id: str

    def __post_init__(self) -> None:
        _require_frame_contract_ids(
            self.canonical_frame_format,
            self.frame_content_hash_contract,
            self.frame_schema_hash_contract,
            label="successor replacement",
        )
        for field_name in (
            "successor_generation_sha256",
            "source_scope_sha256",
            "persisted_content_sha256",
            "persisted_schema_sha256",
            "logical_call_receipt_sha256",
            "provider_authority_sha256",
            "logical_parameters_sha256",
        ):
            if _SHA256_RE.fullmatch(str(getattr(self, field_name))) is None:
                raise ParserInputCaptureIntegrityError(
                    f"successor replacement {field_name} must be a lowercase SHA-256"
                )
        if self.prior_persisted_content_sha256 is not None and (
            _SHA256_RE.fullmatch(self.prior_persisted_content_sha256) is None
        ):
            raise ParserInputCaptureIntegrityError(
                "successor replacement prior content must be a lowercase SHA-256 or null"
            )
        validate_sql_identifier(self.staging_key)
        if (
            isinstance(self.persisted_row_count, bool)
            or not isinstance(self.persisted_row_count, int)
            or self.persisted_row_count < 0
        ):
            raise ParserInputCaptureIntegrityError(
                "successor replacement row count must be nonnegative"
            )
        if not self.result_route_id:
            raise ParserInputCaptureIntegrityError(
                "successor replacement result route ID must be nonempty"
            )

    @property
    def replacement_sha256(self) -> str:
        payload = {
            "successor_generation_sha256": self.successor_generation_sha256,
            "source_scope_sha256": self.source_scope_sha256,
            "staging_key": self.staging_key,
            "canonical_frame_format": self.canonical_frame_format,
            "frame_content_hash_contract": self.frame_content_hash_contract,
            "frame_schema_hash_contract": self.frame_schema_hash_contract,
            "prior_persisted_content_sha256": self.prior_persisted_content_sha256,
            "persisted_content_sha256": self.persisted_content_sha256,
            "persisted_schema_sha256": self.persisted_schema_sha256,
            "persisted_row_count": self.persisted_row_count,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "logical_parameters_sha256": self.logical_parameters_sha256,
            "result_route_id": self.result_route_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class StagingPersistResult:
    staging_tables: int = 0
    rows_persisted: int = 0
    chunks_inserted: int = 0
    chunks_replayed: int = 0
    replacement_attestations: tuple[SourceScopeReplacementAttestation, ...] = ()


@dataclass(frozen=True, slots=True, order=True)
class CommittedStagingChunkReceiptV2:
    """Read-after-commit authority for one receipt-bound staging route.

    The row is reconstructed from ``_staging_chunk_journal`` only after the
    store-owned transaction commits.  It deliberately binds both the logical
    provider call and the exact persisted frame/schema so callers cannot turn
    an in-memory callback into terminal request-closure evidence.
    """

    chunk_id: str
    staging_key: str
    canonical_frame_format: str
    frame_content_hash_contract: str
    frame_schema_hash_contract: str
    content_hash: str
    persisted_row_count: int
    persisted_content_sha256: str
    persisted_schema_sha256: str
    logical_call_receipt_sha256: str
    provider_authority_sha256: str
    logical_parameters_sha256: str
    result_route_id: str

    def __post_init__(self) -> None:
        _require_frame_contract_ids(
            self.canonical_frame_format,
            self.frame_content_hash_contract,
            self.frame_schema_hash_contract,
            label="committed staging receipt",
        )
        if type(self.chunk_id) is not str or not self.chunk_id:
            raise ParserInputCaptureIntegrityError(
                "committed staging receipt chunk ID must be nonempty exact text"
            )
        if type(self.staging_key) is not str:
            raise ParserInputCaptureIntegrityError(
                "committed staging receipt staging key must be exact text"
            )
        validate_sql_identifier(self.staging_key)
        _require_sha256(self.content_hash, label="committed staging receipt content hash")
        _require_nonnegative_int(
            self.persisted_row_count,
            label="committed staging receipt row count",
        )
        for field_name in (
            "persisted_content_sha256",
            "persisted_schema_sha256",
            "logical_call_receipt_sha256",
            "provider_authority_sha256",
            "logical_parameters_sha256",
        ):
            _require_sha256(
                getattr(self, field_name),
                label=f"committed staging receipt {field_name}",
            )
        if type(self.result_route_id) is not str or not self.result_route_id:
            raise ParserInputCaptureIntegrityError(
                "committed staging receipt route ID must be nonempty"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": "committed_staging_chunk_receipt_v2",
            "chunk_id": self.chunk_id,
            "staging_key": self.staging_key,
            "canonical_frame_format": self.canonical_frame_format,
            "frame_content_hash_contract": self.frame_content_hash_contract,
            "frame_schema_hash_contract": self.frame_schema_hash_contract,
            "content_hash": self.content_hash,
            "persisted_row_count": self.persisted_row_count,
            "persisted_content_sha256": self.persisted_content_sha256,
            "persisted_schema_sha256": self.persisted_schema_sha256,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "logical_parameters_sha256": self.logical_parameters_sha256,
            "result_route_id": self.result_route_id,
        }

    @property
    def receipt_root_sha256(self) -> str:
        return _canonical_sha256(self.identity_payload())


# Transitional import name for existing consumers.  It is the exact V2 class,
# not a V1 parser or an evidence-upgrade path.
CommittedStagingChunkReceipt = CommittedStagingChunkReceiptV2


def _require_receipt_route_matches_staging(receipt: CommittedStagingChunkReceiptV2) -> None:
    try:
        _, route_staging_key, raw_result_index = receipt.result_route_id.rsplit(":", 2)
        result_index = int(raw_result_index)
    except (TypeError, ValueError):
        raise ParserInputCaptureIntegrityError(
            "committed staging receipt route ID is malformed"
        ) from None
    if (
        route_staging_key != receipt.staging_key
        or result_index < 0
        or raw_result_index != str(result_index)
    ):
        raise ParserInputCaptureIntegrityError(
            "committed staging receipt route ID differs from its staging key"
        )


def _validated_committed_receipt(value: object) -> CommittedStagingChunkReceiptV2:
    if type(value) is not CommittedStagingChunkReceiptV2:
        raise ParserInputCaptureIntegrityError(
            "committed staging readback requires the exact receipt type"
        )
    return CommittedStagingChunkReceiptV2(
        chunk_id=value.chunk_id,
        staging_key=value.staging_key,
        canonical_frame_format=value.canonical_frame_format,
        frame_content_hash_contract=value.frame_content_hash_contract,
        frame_schema_hash_contract=value.frame_schema_hash_contract,
        content_hash=value.content_hash,
        persisted_row_count=value.persisted_row_count,
        persisted_content_sha256=value.persisted_content_sha256,
        persisted_schema_sha256=value.persisted_schema_sha256,
        logical_call_receipt_sha256=value.logical_call_receipt_sha256,
        provider_authority_sha256=value.provider_authority_sha256,
        logical_parameters_sha256=value.logical_parameters_sha256,
        result_route_id=value.result_route_id,
    )


@dataclass(frozen=True, slots=True)
class CommittedStagingFrameReadbackV2:
    """Immutable, independently rehashed bytes for one committed chunk frame."""

    committed_receipt: CommittedStagingChunkReceiptV2
    canonical_frame_format: Literal["arrow_ipc_stream_v2_pyarrow_v5"]
    frame_content_hash_contract: Literal["nbadb_arrow_logical_table_sha256_v2"]
    frame_schema_hash_contract: Literal["nbadb_arrow_schema_sha256_v2"]
    canonical_frame_bytes: bytes
    canonical_frame_sha256: str
    canonical_frame_size_bytes: int
    recomputed_frame_schema_sha256: str
    recomputed_frame_content_hash: str
    recomputed_persisted_content_sha256: str
    row_count: int
    readback_receipt_sha256: str

    def __post_init__(self) -> None:
        receipt = _validated_committed_receipt(self.committed_receipt)
        _require_receipt_route_matches_staging(receipt)
        _require_frame_contract_ids(
            self.canonical_frame_format,
            self.frame_content_hash_contract,
            self.frame_schema_hash_contract,
            label="committed staging readback",
        )
        if (
            self.canonical_frame_format != receipt.canonical_frame_format
            or self.frame_content_hash_contract != receipt.frame_content_hash_contract
            or self.frame_schema_hash_contract != receipt.frame_schema_hash_contract
        ):
            raise ParserInputCaptureIntegrityError(
                "committed staging readback contract IDs differ from its receipt"
            )
        if type(self.canonical_frame_bytes) is not bytes:
            raise ParserInputCaptureIntegrityError(
                "committed staging readback frame bytes must be immutable bytes"
            )
        _require_sha256(
            self.canonical_frame_sha256,
            label="committed staging readback canonical frame digest",
        )
        _require_nonnegative_int(
            self.canonical_frame_size_bytes,
            label="committed staging readback canonical frame size",
        )
        for field_name in (
            "recomputed_frame_schema_sha256",
            "recomputed_frame_content_hash",
            "recomputed_persisted_content_sha256",
            "readback_receipt_sha256",
        ):
            _require_sha256(
                getattr(self, field_name),
                label=f"committed staging readback {field_name}",
            )
        _require_nonnegative_int(
            self.row_count,
            label="committed staging readback row count",
        )

        frame = _decode_canonical_frame_bytes(self.canonical_frame_bytes)
        if _canonical_frame_bytes(frame) != self.canonical_frame_bytes:
            raise ParserInputCaptureIntegrityError(
                "committed staging readback bytes are not canonical Arrow IPC"
            )
        canonical_sha256 = hashlib.sha256(self.canonical_frame_bytes).hexdigest()
        schema_sha256 = frame_schema_hash(frame)
        content_sha256 = frame_content_hash(frame)
        if (
            self.canonical_frame_sha256 != canonical_sha256
            or self.canonical_frame_size_bytes != len(self.canonical_frame_bytes)
            or self.recomputed_frame_schema_sha256 != schema_sha256
            or self.recomputed_frame_content_hash != content_sha256
            or self.recomputed_persisted_content_sha256 != content_sha256
            or self.row_count != frame.height
            or receipt.persisted_row_count != frame.height
            or receipt.persisted_schema_sha256 != schema_sha256
            or receipt.content_hash != content_sha256
            or receipt.persisted_content_sha256 != content_sha256
        ):
            raise ParserInputCaptureIntegrityError(
                "committed staging readback differs from its canonical frame or receipt"
            )
        if self.readback_receipt_sha256 != _canonical_sha256(self.identity_payload()):
            raise ParserInputCaptureIntegrityError(
                "committed staging readback receipt digest does not match its identity"
            )

    def identity_payload(self) -> dict[str, object]:
        receipt_payload = self.committed_receipt.identity_payload()
        receipt_payload["receipt_root_sha256"] = self.committed_receipt.receipt_root_sha256
        return {
            "schema_version": 2,
            "kind": "committed_staging_frame_readback_v2",
            "committed_receipt": receipt_payload,
            "canonical_frame_format": self.canonical_frame_format,
            "frame_content_hash_contract": self.frame_content_hash_contract,
            "frame_schema_hash_contract": self.frame_schema_hash_contract,
            "canonical_frame_sha256": self.canonical_frame_sha256,
            "canonical_frame_size_bytes": self.canonical_frame_size_bytes,
            "recomputed_frame_schema_sha256": self.recomputed_frame_schema_sha256,
            "recomputed_frame_content_hash": self.recomputed_frame_content_hash,
            "recomputed_persisted_content_sha256": (self.recomputed_persisted_content_sha256),
            "row_count": self.row_count,
        }

    @classmethod
    def build(
        cls,
        *,
        committed_receipt: CommittedStagingChunkReceiptV2,
        frame: pl.DataFrame,
    ) -> CommittedStagingFrameReadbackV2:
        receipt = _validated_committed_receipt(committed_receipt)
        if not isinstance(frame, pl.DataFrame):
            raise ParserInputCaptureIntegrityError(
                "committed staging readback requires a Polars frame"
            )
        canonical_bytes = _canonical_frame_bytes(frame)
        canonical_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
        content_sha256 = frame_content_hash(frame)
        values: dict[str, object] = {
            "committed_receipt": receipt,
            "canonical_frame_format": CANONICAL_FRAME_FORMAT,
            "frame_content_hash_contract": FRAME_CONTENT_HASH_CONTRACT,
            "frame_schema_hash_contract": FRAME_SCHEMA_HASH_CONTRACT,
            "canonical_frame_bytes": canonical_bytes,
            "canonical_frame_sha256": canonical_sha256,
            "canonical_frame_size_bytes": len(canonical_bytes),
            "recomputed_frame_schema_sha256": frame_schema_hash(frame),
            "recomputed_frame_content_hash": content_sha256,
            "recomputed_persisted_content_sha256": content_sha256,
            "row_count": frame.height,
        }
        provisional = cls(
            **values,
            readback_receipt_sha256=_canonical_sha256(_frame_readback_identity_payload(values)),
        )
        return provisional


def _frame_readback_identity_payload(values: dict[str, object]) -> dict[str, object]:
    receipt = _validated_committed_receipt(values["committed_receipt"])
    receipt_payload = receipt.identity_payload()
    receipt_payload["receipt_root_sha256"] = receipt.receipt_root_sha256
    return {
        "schema_version": 2,
        "kind": "committed_staging_frame_readback_v2",
        "committed_receipt": receipt_payload,
        "canonical_frame_format": values["canonical_frame_format"],
        "frame_content_hash_contract": values["frame_content_hash_contract"],
        "frame_schema_hash_contract": values["frame_schema_hash_contract"],
        "canonical_frame_sha256": values["canonical_frame_sha256"],
        "canonical_frame_size_bytes": values["canonical_frame_size_bytes"],
        "recomputed_frame_schema_sha256": values["recomputed_frame_schema_sha256"],
        "recomputed_frame_content_hash": values["recomputed_frame_content_hash"],
        "recomputed_persisted_content_sha256": values["recomputed_persisted_content_sha256"],
        "row_count": values["row_count"],
    }


def _validated_frame_readback(value: object) -> CommittedStagingFrameReadbackV2:
    if type(value) is not CommittedStagingFrameReadbackV2:
        raise ParserInputCaptureIntegrityError(
            "occurrence partition requires the exact committed readback type"
        )
    return CommittedStagingFrameReadbackV2(
        committed_receipt=value.committed_receipt,
        canonical_frame_format=value.canonical_frame_format,
        frame_content_hash_contract=value.frame_content_hash_contract,
        frame_schema_hash_contract=value.frame_schema_hash_contract,
        canonical_frame_bytes=value.canonical_frame_bytes,
        canonical_frame_sha256=value.canonical_frame_sha256,
        canonical_frame_size_bytes=value.canonical_frame_size_bytes,
        recomputed_frame_schema_sha256=value.recomputed_frame_schema_sha256,
        recomputed_frame_content_hash=value.recomputed_frame_content_hash,
        recomputed_persisted_content_sha256=value.recomputed_persisted_content_sha256,
        row_count=value.row_count,
        readback_receipt_sha256=value.readback_receipt_sha256,
    )


@dataclass(frozen=True, slots=True)
class CommittedStagingRowSliceV2:
    """One storage-only row interval in an exact committed readback."""

    schema_version: int
    canonical_frame_format: str
    frame_content_hash_contract: str
    frame_schema_hash_contract: str
    readback_receipt_sha256: str
    receipt_root_sha256: str
    route_id: str
    staging_key: str
    slice_order_ordinal: int
    start_row_ordinal: int
    row_count: int
    slice_schema_sha256: str
    slice_content_sha256: str
    slice_receipt_sha256: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise ParserInputCaptureIntegrityError(
                "committed staging row slice schema version must be integer two"
            )
        _require_frame_contract_ids(
            self.canonical_frame_format,
            self.frame_content_hash_contract,
            self.frame_schema_hash_contract,
            label="committed staging row slice",
        )
        for field_name in (
            "readback_receipt_sha256",
            "receipt_root_sha256",
            "slice_schema_sha256",
            "slice_content_sha256",
            "slice_receipt_sha256",
        ):
            _require_sha256(
                getattr(self, field_name),
                label=f"committed staging row slice {field_name}",
            )
        if type(self.route_id) is not str or not self.route_id:
            raise ParserInputCaptureIntegrityError(
                "committed staging row slice route ID must be nonempty"
            )
        if type(self.staging_key) is not str:
            raise ParserInputCaptureIntegrityError(
                "committed staging row slice staging key must be exact text"
            )
        validate_sql_identifier(self.staging_key)
        for field_name in ("slice_order_ordinal", "start_row_ordinal", "row_count"):
            _require_nonnegative_int(
                getattr(self, field_name),
                label=f"committed staging row slice {field_name}",
            )
        if self.slice_receipt_sha256 != _canonical_sha256(self.identity_payload()):
            raise ParserInputCaptureIntegrityError(
                "committed staging row slice digest does not match its identity"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": "committed_staging_row_slice_v2",
            "canonical_frame_format": self.canonical_frame_format,
            "frame_content_hash_contract": self.frame_content_hash_contract,
            "frame_schema_hash_contract": self.frame_schema_hash_contract,
            "readback_receipt_sha256": self.readback_receipt_sha256,
            "receipt_root_sha256": self.receipt_root_sha256,
            "route_id": self.route_id,
            "staging_key": self.staging_key,
            "slice_order_ordinal": self.slice_order_ordinal,
            "start_row_ordinal": self.start_row_ordinal,
            "row_count": self.row_count,
            "slice_schema_sha256": self.slice_schema_sha256,
            "slice_content_sha256": self.slice_content_sha256,
        }

    @classmethod
    def build(
        cls,
        *,
        readback: CommittedStagingFrameReadbackV2,
        slice_order_ordinal: int,
        start_row_ordinal: int,
        row_count: int,
    ) -> CommittedStagingRowSliceV2:
        exact_readback = _validated_frame_readback(readback)
        _require_nonnegative_int(
            slice_order_ordinal,
            label="committed staging row slice order",
        )
        _require_nonnegative_int(
            start_row_ordinal,
            label="committed staging row slice start row",
        )
        _require_nonnegative_int(
            row_count,
            label="committed staging row slice row count",
        )
        if start_row_ordinal + row_count > exact_readback.row_count:
            raise ParserInputCaptureIntegrityError(
                "committed staging row slice exceeds the committed frame"
            )
        receipt = exact_readback.committed_receipt
        frame = _decode_canonical_frame_bytes(exact_readback.canonical_frame_bytes)
        slice_frame = frame.slice(start_row_ordinal, row_count)
        slice_schema_sha256 = frame_schema_hash(slice_frame)
        slice_content_sha256 = frame_content_hash(slice_frame)
        values: dict[str, object] = {
            "schema_version": 2,
            "canonical_frame_format": exact_readback.canonical_frame_format,
            "frame_content_hash_contract": exact_readback.frame_content_hash_contract,
            "frame_schema_hash_contract": exact_readback.frame_schema_hash_contract,
            "readback_receipt_sha256": exact_readback.readback_receipt_sha256,
            "receipt_root_sha256": receipt.receipt_root_sha256,
            "route_id": receipt.result_route_id,
            "staging_key": receipt.staging_key,
            "slice_order_ordinal": slice_order_ordinal,
            "start_row_ordinal": start_row_ordinal,
            "row_count": row_count,
            "slice_schema_sha256": slice_schema_sha256,
            "slice_content_sha256": slice_content_sha256,
        }
        return cls(
            schema_version=2,
            canonical_frame_format=exact_readback.canonical_frame_format,
            frame_content_hash_contract=exact_readback.frame_content_hash_contract,
            frame_schema_hash_contract=exact_readback.frame_schema_hash_contract,
            readback_receipt_sha256=exact_readback.readback_receipt_sha256,
            receipt_root_sha256=receipt.receipt_root_sha256,
            route_id=receipt.result_route_id,
            staging_key=receipt.staging_key,
            slice_order_ordinal=slice_order_ordinal,
            start_row_ordinal=start_row_ordinal,
            row_count=row_count,
            slice_schema_sha256=slice_schema_sha256,
            slice_content_sha256=slice_content_sha256,
            slice_receipt_sha256=_canonical_sha256(
                values | {"kind": "committed_staging_row_slice_v2"}
            ),
        )


def _validated_row_slice(value: object) -> CommittedStagingRowSliceV2:
    if type(value) is not CommittedStagingRowSliceV2:
        raise ParserInputCaptureIntegrityError(
            "row partition requires exact committed row-slice types"
        )
    return CommittedStagingRowSliceV2(
        schema_version=value.schema_version,
        canonical_frame_format=value.canonical_frame_format,
        frame_content_hash_contract=value.frame_content_hash_contract,
        frame_schema_hash_contract=value.frame_schema_hash_contract,
        readback_receipt_sha256=value.readback_receipt_sha256,
        receipt_root_sha256=value.receipt_root_sha256,
        route_id=value.route_id,
        staging_key=value.staging_key,
        slice_order_ordinal=value.slice_order_ordinal,
        start_row_ordinal=value.start_row_ordinal,
        row_count=value.row_count,
        slice_schema_sha256=value.slice_schema_sha256,
        slice_content_sha256=value.slice_content_sha256,
        slice_receipt_sha256=value.slice_receipt_sha256,
    )


@dataclass(frozen=True, slots=True)
class CommittedStagingRowPartitionV2:
    """Storage-only proof that exact row slices partition one readback."""

    schema_version: int
    canonical_frame_format: str
    frame_content_hash_contract: str
    frame_schema_hash_contract: str
    readback_receipt_sha256: str
    receipt_root_sha256: str
    route_id: str
    staging_key: str
    row_count: int
    slice_count: int
    slice_receipt_sha256s: tuple[str, ...]
    partition_receipt_sha256: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise ParserInputCaptureIntegrityError(
                "committed staging row partition schema version must be integer two"
            )
        _require_frame_contract_ids(
            self.canonical_frame_format,
            self.frame_content_hash_contract,
            self.frame_schema_hash_contract,
            label="committed staging row partition",
        )
        for field_name in (
            "readback_receipt_sha256",
            "receipt_root_sha256",
            "partition_receipt_sha256",
        ):
            _require_sha256(
                getattr(self, field_name),
                label=f"committed staging row partition {field_name}",
            )
        if type(self.route_id) is not str or not self.route_id:
            raise ParserInputCaptureIntegrityError(
                "committed staging row partition route ID must be nonempty"
            )
        if type(self.staging_key) is not str:
            raise ParserInputCaptureIntegrityError(
                "committed staging row partition staging key must be exact text"
            )
        validate_sql_identifier(self.staging_key)
        _require_nonnegative_int(
            self.row_count,
            label="committed staging row partition row count",
        )
        _require_nonnegative_int(
            self.slice_count,
            label="committed staging row partition slice count",
        )
        if type(self.slice_receipt_sha256s) is not tuple or any(
            type(item) is not str or _SHA256_RE.fullmatch(item) is None
            for item in self.slice_receipt_sha256s
        ):
            raise ParserInputCaptureIntegrityError(
                "committed staging row partition slice inventory must be exact SHA-256 text"
            )
        if (
            not self.slice_receipt_sha256s
            or len(self.slice_receipt_sha256s) != self.slice_count
            or len(set(self.slice_receipt_sha256s)) != len(self.slice_receipt_sha256s)
        ):
            raise ParserInputCaptureIntegrityError(
                "committed staging row partition slice inventory is incomplete or duplicated"
            )
        if self.partition_receipt_sha256 != _canonical_sha256(self.identity_payload()):
            raise ParserInputCaptureIntegrityError(
                "committed staging row partition digest does not match its identity"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": "committed_staging_row_partition_v2",
            "canonical_frame_format": self.canonical_frame_format,
            "frame_content_hash_contract": self.frame_content_hash_contract,
            "frame_schema_hash_contract": self.frame_schema_hash_contract,
            "readback_receipt_sha256": self.readback_receipt_sha256,
            "receipt_root_sha256": self.receipt_root_sha256,
            "route_id": self.route_id,
            "staging_key": self.staging_key,
            "row_count": self.row_count,
            "slice_count": self.slice_count,
            "slice_receipt_sha256s": list(self.slice_receipt_sha256s),
        }


def validate_committed_row_partition(
    readback: CommittedStagingFrameReadbackV2,
    slices: tuple[CommittedStagingRowSliceV2, ...],
) -> CommittedStagingRowPartitionV2:
    """Validate ordered, gap-free, multiplicity-preserving storage slices."""

    exact_readback = _validated_frame_readback(readback)
    if type(slices) is not tuple or not slices:
        raise ParserInputCaptureIntegrityError(
            "committed staging row partition requires a nonempty exact tuple"
        )
    exact_slices = tuple(_validated_row_slice(item) for item in slices)
    receipt = exact_readback.committed_receipt
    frame = _decode_canonical_frame_bytes(exact_readback.canonical_frame_bytes)
    row_cursor = 0
    slice_receipt_sha256s: list[str] = []
    for slice_order_ordinal, row_slice in enumerate(exact_slices):
        if (
            row_slice.canonical_frame_format != exact_readback.canonical_frame_format
            or row_slice.frame_content_hash_contract != exact_readback.frame_content_hash_contract
            or row_slice.frame_schema_hash_contract != exact_readback.frame_schema_hash_contract
            or row_slice.readback_receipt_sha256 != exact_readback.readback_receipt_sha256
            or row_slice.receipt_root_sha256 != receipt.receipt_root_sha256
            or row_slice.route_id != receipt.result_route_id
            or row_slice.staging_key != receipt.staging_key
        ):
            raise ParserInputCaptureIntegrityError(
                "committed staging row slice is foreign to its readback partition"
            )
        if row_slice.slice_order_ordinal != slice_order_ordinal:
            raise ParserInputCaptureIntegrityError(
                "committed staging row slices are reordered or incomplete"
            )
        if row_slice.start_row_ordinal != row_cursor:
            raise ParserInputCaptureIntegrityError(
                "committed staging row slices overlap or leave a row gap"
            )
        end_row = row_cursor + row_slice.row_count
        if end_row > exact_readback.row_count:
            raise ParserInputCaptureIntegrityError(
                "committed staging row slice exceeds the committed frame"
            )
        slice_frame = frame.slice(row_cursor, row_slice.row_count)
        if row_slice.slice_schema_sha256 != frame_schema_hash(
            slice_frame
        ) or row_slice.slice_content_sha256 != frame_content_hash(slice_frame):
            raise ParserInputCaptureIntegrityError(
                "committed staging row slice differs from its exact frame interval"
            )
        slice_receipt_sha256s.append(row_slice.slice_receipt_sha256)
        row_cursor = end_row

    if row_cursor != exact_readback.row_count:
        raise ParserInputCaptureIntegrityError(
            "committed staging row slices do not cover exact row multiplicity"
        )
    if len(set(slice_receipt_sha256s)) != len(slice_receipt_sha256s):
        raise ParserInputCaptureIntegrityError(
            "committed staging row inventory contains duplicate slice receipts"
        )

    slice_receipts = tuple(slice_receipt_sha256s)
    partition_values: dict[str, object] = {
        "schema_version": 2,
        "kind": "committed_staging_row_partition_v2",
        "canonical_frame_format": exact_readback.canonical_frame_format,
        "frame_content_hash_contract": exact_readback.frame_content_hash_contract,
        "frame_schema_hash_contract": exact_readback.frame_schema_hash_contract,
        "readback_receipt_sha256": exact_readback.readback_receipt_sha256,
        "receipt_root_sha256": receipt.receipt_root_sha256,
        "route_id": receipt.result_route_id,
        "staging_key": receipt.staging_key,
        "row_count": exact_readback.row_count,
        "slice_count": len(exact_slices),
        "slice_receipt_sha256s": list(slice_receipts),
    }
    return CommittedStagingRowPartitionV2(
        schema_version=2,
        canonical_frame_format=exact_readback.canonical_frame_format,
        frame_content_hash_contract=exact_readback.frame_content_hash_contract,
        frame_schema_hash_contract=exact_readback.frame_schema_hash_contract,
        readback_receipt_sha256=exact_readback.readback_receipt_sha256,
        receipt_root_sha256=receipt.receipt_root_sha256,
        route_id=receipt.result_route_id,
        staging_key=receipt.staging_key,
        row_count=exact_readback.row_count,
        slice_count=len(exact_slices),
        slice_receipt_sha256s=slice_receipts,
        partition_receipt_sha256=_canonical_sha256(partition_values),
    )


# Import-only bridges for the concurrently migrating typed-field consumer.
# Each name resolves to the exact V2 implementation; V1-shaped construction
# still fails because V2 schema/contract IDs are mandatory.
CommittedStagingFrameReadbackV1 = CommittedStagingFrameReadbackV2
CommittedStagingOccurrenceSliceV1 = CommittedStagingRowSliceV2
CommittedStagingOccurrencePartitionV1 = CommittedStagingRowPartitionV2
validate_committed_occurrence_partition = validate_committed_row_partition


def _committed_receipt_from_journal_row(
    row: tuple[object, ...],
) -> CommittedStagingChunkReceiptV2:
    if type(row) is not tuple or len(row) != 13:
        raise ParserInputCaptureIntegrityError(
            "committed staging journal lacks exact V2 contract evidence; full restart required"
        )
    try:
        return CommittedStagingChunkReceiptV2(
            chunk_id=cast("str", row[0]),
            staging_key=cast("str", row[1]),
            canonical_frame_format=cast("str", row[2]),
            frame_content_hash_contract=cast("str", row[3]),
            frame_schema_hash_contract=cast("str", row[4]),
            content_hash=cast("str", row[5]),
            persisted_row_count=cast("int", row[6]),
            persisted_content_sha256=cast("str", row[7]),
            persisted_schema_sha256=cast("str", row[8]),
            logical_call_receipt_sha256=cast("str", row[9]),
            provider_authority_sha256=cast("str", row[10]),
            logical_parameters_sha256=cast("str", row[11]),
            result_route_id=cast("str", row[12]),
        )
    except (ParserInputCaptureIntegrityError, TypeError, ValueError) as exc:
        raise ParserInputCaptureIntegrityError(
            "committed staging journal lacks exact V2 contract evidence; full restart required"
        ) from exc


class _ExistingTransactionWriter:
    """Capability valid only while its store owns the process write lock."""

    def __init__(self, store: StagingBatchStore) -> None:
        self._store = store
        self._active = True

    def persist_frame_batches(
        self,
        batches: Iterable[StagingFrameBatch],
        *,
        materialize: bool = False,
    ) -> StagingPersistResult:
        if not self._active:
            raise RuntimeError("staging transaction writer is no longer active")
        batch_list = list(batches)
        if not batch_list:
            return StagingPersistResult()
        result = self._store._persist_frame_batch_list(
            batch_list,
            materialize=materialize,
        )
        self._store._log_persist_result(result)
        return result

    def _close(self) -> None:
        self._active = False


@dataclass(frozen=True, slots=True)
class _StoredChunkJournal:
    content_hash: str
    canonical_frame_format: str | None
    frame_content_hash_contract: str | None
    frame_schema_hash_contract: str | None
    persisted_row_count: int | None
    persisted_content_sha256: str | None
    persisted_schema_sha256: str | None
    logical_call_receipt_sha256: str | None
    provider_authority_sha256: str | None
    logical_parameters_sha256: str | None
    result_route_id: str | None

    def __post_init__(self) -> None:
        _require_sha256(self.content_hash, label="stored staging chunk content hash")
        _require_frame_contract_ids(
            self.canonical_frame_format,
            self.frame_content_hash_contract,
            self.frame_schema_hash_contract,
            label="stored staging chunk",
        )

    @property
    def has_no_receipt_binding(self) -> bool:
        return all(
            value is None
            for value in (
                self.logical_call_receipt_sha256,
                self.provider_authority_sha256,
                self.logical_parameters_sha256,
                self.result_route_id,
            )
        )


def digest_jsonable(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ParserInputCaptureIntegrityError(
            "canonical Arrow schema descriptor is not strict JSON"
        ) from exc


def _arrow_field_descriptor(field: pa.Field) -> dict[str, object]:
    if not isinstance(field, pa.Field):
        raise ParserInputCaptureIntegrityError("canonical Arrow schema contains an invalid field")
    return {
        "name": field.name,
        "nullable": field.nullable,
        "type": _arrow_type_descriptor(field.type),
    }


def _arrow_type_descriptor(data_type: pa.DataType) -> dict[str, object]:
    if not isinstance(data_type, pa.DataType):
        raise ParserInputCaptureIntegrityError("canonical Arrow schema contains an invalid type")
    if isinstance(data_type, pa.ExtensionType):
        raise ParserInputCaptureIntegrityError(
            "canonical Arrow schema does not support extension types"
        )
    if pa.types.is_null(data_type):
        return {"kind": "null"}
    if pa.types.is_boolean(data_type):
        return {"kind": "boolean"}
    if pa.types.is_signed_integer(data_type):
        return {"bit_width": data_type.bit_width, "kind": "signed_integer"}
    if pa.types.is_unsigned_integer(data_type):
        return {"bit_width": data_type.bit_width, "kind": "unsigned_integer"}
    if pa.types.is_floating(data_type):
        return {"bit_width": data_type.bit_width, "kind": "floating_point"}
    if pa.types.is_decimal(data_type):
        return {
            "bit_width": data_type.bit_width,
            "kind": "decimal",
            "precision": data_type.precision,
            "scale": data_type.scale,
        }
    if pa.types.is_string(data_type):
        return {"kind": "utf8"}
    if pa.types.is_large_string(data_type):
        return {"kind": "large_utf8"}
    if pa.types.is_string_view(data_type):
        return {"kind": "utf8_view"}
    if pa.types.is_fixed_size_binary(data_type):
        return {"byte_width": data_type.byte_width, "kind": "fixed_size_binary"}
    if pa.types.is_binary(data_type):
        return {"kind": "binary"}
    if pa.types.is_large_binary(data_type):
        return {"kind": "large_binary"}
    if pa.types.is_binary_view(data_type):
        return {"kind": "binary_view"}
    if pa.types.is_date32(data_type):
        return {"kind": "date", "unit": "day"}
    if pa.types.is_date64(data_type):
        return {"kind": "date", "unit": "ms"}
    if pa.types.is_timestamp(data_type):
        return {"kind": "timestamp", "timezone": data_type.tz, "unit": data_type.unit}
    if pa.types.is_time32(data_type) or pa.types.is_time64(data_type):
        return {"kind": "time", "unit": data_type.unit}
    if pa.types.is_duration(data_type):
        return {"kind": "duration", "unit": data_type.unit}
    if pa.types.is_fixed_size_list(data_type):
        return {
            "kind": "fixed_size_list",
            "list_size": data_type.list_size,
            "value_field": _arrow_field_descriptor(data_type.value_field),
        }
    if pa.types.is_list(data_type):
        return {"kind": "list", "value_field": _arrow_field_descriptor(data_type.value_field)}
    if pa.types.is_large_list(data_type):
        return {
            "kind": "large_list",
            "value_field": _arrow_field_descriptor(data_type.value_field),
        }
    if pa.types.is_list_view(data_type):
        return {
            "kind": "list_view",
            "value_field": _arrow_field_descriptor(data_type.value_field),
        }
    if pa.types.is_large_list_view(data_type):
        return {
            "kind": "large_list_view",
            "value_field": _arrow_field_descriptor(data_type.value_field),
        }
    if pa.types.is_struct(data_type):
        return {
            "fields": [_arrow_field_descriptor(field) for field in data_type],
            "kind": "struct",
        }
    if pa.types.is_dictionary(data_type):
        return {
            "index_type": _arrow_type_descriptor(data_type.index_type),
            "kind": "dictionary",
            "ordered": data_type.ordered,
            "value_type": _arrow_type_descriptor(data_type.value_type),
        }
    if (
        pa.types.is_map(data_type)
        or pa.types.is_union(data_type)
        or pa.types.is_run_end_encoded(data_type)
    ):
        raise ParserInputCaptureIntegrityError(
            "canonical Arrow schema contains an unsupported nested type"
        )
    raise ParserInputCaptureIntegrityError("canonical Arrow schema contains an unsupported type")


def _clean_arrow_type(data_type: pa.DataType) -> pa.DataType:
    _arrow_type_descriptor(data_type)
    if pa.types.is_fixed_size_list(data_type):
        return pa.list_(
            _clean_arrow_field(data_type.value_field),
            data_type.list_size,
        )
    if pa.types.is_list(data_type):
        return pa.list_(_clean_arrow_field(data_type.value_field))
    if pa.types.is_large_list(data_type):
        return pa.large_list(_clean_arrow_field(data_type.value_field))
    if pa.types.is_list_view(data_type):
        return pa.list_view(_clean_arrow_field(data_type.value_field))
    if pa.types.is_large_list_view(data_type):
        return pa.large_list_view(_clean_arrow_field(data_type.value_field))
    if pa.types.is_struct(data_type):
        return pa.struct([_clean_arrow_field(field) for field in data_type])
    if pa.types.is_dictionary(data_type):
        return pa.dictionary(
            _clean_arrow_type(data_type.index_type),
            _clean_arrow_type(data_type.value_type),
            ordered=data_type.ordered,
        )
    return data_type


def _clean_arrow_field(field: pa.Field) -> pa.Field:
    return pa.field(
        field.name,
        _clean_arrow_type(field.type),
        nullable=field.nullable,
        metadata=None,
    )


def _arrow_schema_descriptor(schema: pa.Schema) -> dict[str, object]:
    if not isinstance(schema, pa.Schema):
        raise ParserInputCaptureIntegrityError("canonical Arrow schema is invalid")
    names = tuple(schema.names)
    if len(names) != len(set(names)):
        raise ParserInputCaptureIntegrityError("canonical Arrow schema has duplicate field names")
    return {
        "fields": [_arrow_field_descriptor(field) for field in schema],
        "schema_version": 2,
    }


def _normalize_arrow_table(table: pa.Table) -> pa.Table:
    if not isinstance(table, pa.Table):
        raise ParserInputCaptureIntegrityError("canonical Arrow input must be a PyArrow table")
    clean_schema = pa.schema(
        [_clean_arrow_field(field) for field in table.schema],
        metadata=None,
    )
    _arrow_schema_descriptor(clean_schema)
    try:
        normalized = table.cast(clean_schema, safe=True).unify_dictionaries().combine_chunks()
        arrays: list[pa.Array] = []
        for column, field in zip(normalized.columns, clean_schema, strict=True):
            chunks = list(column.chunks)
            combined = pa.array([], type=field.type) if not chunks else pa.concat_arrays(chunks)
            materialized = _materialize_arrow_array(
                combined,
                expected_type=field.type,
            )
            if materialized.offset != 0:
                raise ParserInputCaptureIntegrityError(
                    "canonical Arrow normalization retained a non-zero column offset"
                )
            arrays.append(materialized)
        return pa.Table.from_arrays(arrays, schema=clean_schema)
    except ParserInputCaptureIntegrityError:
        raise
    except Exception as exc:
        raise ParserInputCaptureIntegrityError(
            "committed staging frame could not be normalized as canonical Arrow"
        ) from exc


def _materialize_arrow_array(
    array: pa.Array,
    *,
    expected_type: pa.DataType,
) -> pa.Array:
    """Remove physical offsets and normalize nested/dictionary representation."""

    if array.type != expected_type:
        try:
            array = array.cast(expected_type, safe=True)
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "canonical Arrow array differs from its exact field type"
            ) from exc
    try:
        if pa.types.is_dictionary(expected_type):
            dictionary_array = cast("pa.DictionaryArray", array)
            if expected_type.ordered:
                indices = _materialize_arrow_array(
                    dictionary_array.indices,
                    expected_type=expected_type.index_type,
                )
                dictionary = _materialize_arrow_array(
                    dictionary_array.dictionary,
                    expected_type=expected_type.value_type,
                )
                materialized = pa.DictionaryArray.from_arrays(
                    indices,
                    dictionary,
                    ordered=True,
                )
            else:
                logical_values = _materialize_arrow_array(
                    dictionary_array.dictionary_decode(),
                    expected_type=expected_type.value_type,
                )
                encoded = logical_values.dictionary_encode()
                materialized = encoded.cast(expected_type, safe=True)
        elif pa.types.is_struct(expected_type):
            struct_array = cast("pa.StructArray", array)
            children = [
                _materialize_arrow_array(
                    struct_array.field(index),
                    expected_type=field.type,
                )
                for index, field in enumerate(expected_type)
            ]
            materialized = pa.StructArray.from_arrays(
                children,
                fields=list(expected_type),
                mask=pa.concat_arrays([struct_array.is_null()]),
            )
        elif pa.types.is_fixed_size_list(expected_type):
            list_array = cast("pa.FixedSizeListArray", array)
            value_offset = list_array.offset * expected_type.list_size
            value_count = len(list_array) * expected_type.list_size
            values = _materialize_arrow_array(
                list_array.values.slice(value_offset, value_count),
                expected_type=expected_type.value_type,
            )
            materialized = pa.FixedSizeListArray.from_arrays(
                values,
                expected_type.list_size,
                mask=pa.concat_arrays([list_array.is_null()]),
            )
        elif pa.types.is_list(expected_type) or pa.types.is_large_list(expected_type):
            list_array = cast("pa.ListArray | pa.LargeListArray", array)
            raw_offsets = list_array.offsets.to_pylist()
            base_offset = raw_offsets[0]
            normalized_offsets = [offset - base_offset for offset in raw_offsets]
            values = _materialize_arrow_array(
                list_array.values.slice(base_offset, raw_offsets[-1] - base_offset),
                expected_type=expected_type.value_type,
            )
            offsets_type = pa.int64() if pa.types.is_large_list(expected_type) else pa.int32()
            offsets = pa.array(normalized_offsets, type=offsets_type)
            array_type = (
                pa.LargeListArray if pa.types.is_large_list(expected_type) else pa.ListArray
            )
            materialized = array_type.from_arrays(
                offsets,
                values,
                type=expected_type,
                mask=pa.concat_arrays([list_array.is_null()]),
            )
        elif pa.types.is_list_view(expected_type) or pa.types.is_large_list_view(expected_type):
            raise ParserInputCaptureIntegrityError(
                "canonical Arrow normalization does not support list-view arrays"
            )
        else:
            materialized = pa.concat_arrays([array])
    except ParserInputCaptureIntegrityError:
        raise
    except Exception as exc:
        raise ParserInputCaptureIntegrityError(
            "canonical Arrow array could not be materialized deterministically"
        ) from exc
    materialized = _normalize_arrow_null_payloads(
        materialized,
        expected_type=expected_type,
    )
    if materialized.type != expected_type or materialized.offset != 0:
        raise ParserInputCaptureIntegrityError(
            "canonical Arrow array normalization changed its type or retained an offset"
        )
    return materialized


def _normalize_arrow_null_payloads(
    array: pa.Array,
    *,
    expected_type: pa.DataType,
) -> pa.Array:
    """Canonicalize physical bytes hidden beneath Arrow null validity bits."""

    if array.null_count == 0 or pa.types.is_dictionary(expected_type):
        return array
    if array.null_count == len(array):
        return pa.nulls(len(array), type=expected_type)

    valid_flags = cast("list[bool]", array.is_valid().to_pylist())
    first_valid = valid_flags.index(True)
    try:
        # Fill from an exact Arrow scalar rather than a Python value so valid
        # decimal, temporal, and floating-point bits are never narrowed.
        filled = pa_compute.fill_null(array, array[first_valid])
        normalized = pa_compute.call_function(
            "replace_with_mask",
            [
                filled,
                array.is_null(),
                pa.scalar(None, type=expected_type),
            ],
        )
        if isinstance(normalized, pa.ChunkedArray):  # pragma: no cover - Array input contract
            normalized = normalized.combine_chunks()
        if not isinstance(normalized, pa.Array):  # pragma: no cover - PyArrow kernel contract
            raise ParserInputCaptureIntegrityError(
                "canonical Arrow null normalization returned a foreign array"
            )
        return normalized
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError, TypeError):
        # Nested kernels do not implement replace_with_mask. Validity-run
        # slicing preserves exact valid bytes after child normalization; null
        # runs are replaced with canonical Arrow null arrays.
        runs: list[pa.Array] = []
        run_start = 0
        run_valid = valid_flags[0]
        for index, is_valid in enumerate(valid_flags[1:], start=1):
            if is_valid == run_valid:
                continue
            run_length = index - run_start
            runs.append(
                array.slice(run_start, run_length)
                if run_valid
                else pa.nulls(run_length, type=expected_type)
            )
            run_start = index
            run_valid = is_valid
        final_length = len(array) - run_start
        runs.append(
            array.slice(run_start, final_length)
            if run_valid
            else pa.nulls(final_length, type=expected_type)
        )
        try:
            return pa.concat_arrays(runs)
        except Exception as exc:  # pragma: no cover - canonical matrix guard
            raise ParserInputCaptureIntegrityError(
                "canonical Arrow null payloads could not be normalized"
            ) from exc


def _encode_normalized_arrow_table(table: pa.Table) -> bytes:
    arrays = [
        column.chunk(0) if column.num_chunks == 1 else pa.array([], type=field.type)
        for column, field in zip(table.columns, table.schema, strict=True)
    ]
    if any(column.num_chunks not in (0, 1) for column in table.columns):
        raise ParserInputCaptureIntegrityError(
            "canonical Arrow normalization did not produce single-chunk columns"
        )
    try:
        batch = pa.RecordBatch.from_arrays(arrays, schema=table.schema)
        sink = pa.BufferOutputStream()
        options = pa_ipc.IpcWriteOptions(
            metadata_version=pa_ipc.MetadataVersion.V5,
            use_legacy_format=False,
            compression=None,
            use_threads=False,
        )
        with pa_ipc.new_stream(sink, table.schema, options=options) as writer:
            writer.write_batch(batch)
        return sink.getvalue().to_pybytes()
    except Exception as exc:
        raise ParserInputCaptureIntegrityError(
            "committed staging frame could not be encoded as canonical Arrow IPC V5"
        ) from exc


def _read_single_arrow_batch(value: bytes) -> pa.Table:
    if type(value) is not bytes or not value:
        raise ParserInputCaptureIntegrityError(
            "committed staging frame bytes must be nonempty immutable bytes"
        )
    source = pa.BufferReader(value)
    try:
        with pa_ipc.open_stream(source) as reader:
            schema = reader.schema
            batches = list(reader)
    except Exception as exc:
        raise ParserInputCaptureIntegrityError(
            "committed staging frame bytes are not readable Arrow IPC V5"
        ) from exc
    if source.tell() != len(value) or len(batches) != 1:
        raise ParserInputCaptureIntegrityError(
            "committed staging frame must contain one exact Arrow record batch"
        )
    try:
        return pa.Table.from_batches(batches, schema=schema)
    except Exception as exc:
        raise ParserInputCaptureIntegrityError(
            "committed staging frame batch differs from its Arrow schema"
        ) from exc


def _canonical_frame_bytes(df: pl.DataFrame) -> bytes:
    if not isinstance(df, pl.DataFrame):
        raise ParserInputCaptureIntegrityError(
            "committed staging frame canonicalization requires a Polars frame"
        )
    try:
        normalized = _normalize_arrow_table(df.to_arrow())
    except ParserInputCaptureIntegrityError:
        raise
    except Exception as exc:
        raise ParserInputCaptureIntegrityError(
            "committed staging frame could not be converted to canonical Arrow"
        ) from exc
    encoded = _encode_normalized_arrow_table(normalized)
    decoded = _read_single_arrow_batch(encoded)
    if _arrow_schema_descriptor(decoded.schema) != _arrow_schema_descriptor(normalized.schema):
        raise ParserInputCaptureIntegrityError(
            "canonical Arrow IPC decode changed the logical schema descriptor"
        )
    reencoded = _encode_normalized_arrow_table(_normalize_arrow_table(decoded))
    if reencoded != encoded:
        raise ParserInputCaptureIntegrityError(
            "canonical Arrow IPC bytes are not an encode/decode fixed point"
        )
    return encoded


def frame_content_hash(df: pl.DataFrame) -> str:
    return _domain_separated_sha256(FRAME_CONTENT_HASH_CONTRACT, _canonical_frame_bytes(df))


def frame_schema_hash(df: pl.DataFrame) -> str:
    if not isinstance(df, pl.DataFrame):
        raise ParserInputCaptureIntegrityError(
            "committed staging schema hashing requires a Polars frame"
        )
    try:
        table = _normalize_arrow_table(df.to_arrow())
    except ParserInputCaptureIntegrityError:
        raise
    except Exception as exc:
        raise ParserInputCaptureIntegrityError(
            "committed staging frame could not be converted to canonical Arrow"
        ) from exc
    descriptor = _canonical_json_bytes(_arrow_schema_descriptor(table.schema))
    return _domain_separated_sha256(FRAME_SCHEMA_HASH_CONTRACT, descriptor)


def _decode_canonical_frame_bytes(value: bytes) -> pl.DataFrame:
    table = _read_single_arrow_batch(value)
    normalized = _normalize_arrow_table(table)
    if _encode_normalized_arrow_table(normalized) != value:
        raise ParserInputCaptureIntegrityError(
            "committed staging frame bytes are not canonical Arrow IPC V5"
        )
    try:
        frame = pl.from_arrow(normalized, rechunk=True)
    except Exception as exc:
        raise ParserInputCaptureIntegrityError(
            "committed staging Arrow frame cannot be converted to Polars"
        ) from exc
    if not isinstance(frame, pl.DataFrame):  # pragma: no cover - PyArrow table contract
        raise ParserInputCaptureIntegrityError(
            "committed staging Arrow frame did not produce a Polars frame"
        )
    if _canonical_frame_bytes(frame) != value:
        raise ParserInputCaptureIntegrityError(
            "committed staging Arrow frame is not a Polars round-trip fixed point"
        )
    return frame


def _quoted_csv(columns: Iterable[str]) -> str:
    return ", ".join(f'"{validate_sql_identifier(column)}"' for column in columns)


class StagingBatchStore:
    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn
        self._caller_transaction_active = False
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _staging_chunk_journal (
                chunk_id VARCHAR NOT NULL,
                staging_key VARCHAR NOT NULL,
                canonical_frame_format VARCHAR NOT NULL,
                frame_content_hash_contract VARCHAR NOT NULL,
                frame_schema_hash_contract VARCHAR NOT NULL,
                row_count BIGINT NOT NULL,
                content_hash VARCHAR NOT NULL,
                source_label VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chunk_id, staging_key)
            )
            """
        )
        for column, data_type in (
            ("canonical_frame_format", "VARCHAR"),
            ("frame_content_hash_contract", "VARCHAR"),
            ("frame_schema_hash_contract", "VARCHAR"),
            ("persisted_row_count", "BIGINT"),
            ("persisted_content_sha256", "VARCHAR"),
            ("persisted_schema_sha256", "VARCHAR"),
            ("logical_call_receipt_sha256", "VARCHAR"),
            ("provider_authority_sha256", "VARCHAR"),
            ("logical_parameters_sha256", "VARCHAR"),
            ("result_route_id", "VARCHAR"),
        ):
            self._conn.execute(
                f"ALTER TABLE _staging_chunk_journal ADD COLUMN IF NOT EXISTS {column} {data_type}"
            )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _successor_staging_replacement_journal (
                successor_generation_sha256 VARCHAR NOT NULL,
                source_scope_sha256 VARCHAR NOT NULL,
                staging_key VARCHAR NOT NULL,
                canonical_frame_format VARCHAR NOT NULL,
                frame_content_hash_contract VARCHAR NOT NULL,
                frame_schema_hash_contract VARCHAR NOT NULL,
                prior_persisted_content_sha256 VARCHAR,
                persisted_content_sha256 VARCHAR NOT NULL,
                persisted_schema_sha256 VARCHAR NOT NULL,
                persisted_row_count BIGINT NOT NULL,
                logical_call_receipt_sha256 VARCHAR NOT NULL,
                provider_authority_sha256 VARCHAR NOT NULL,
                logical_parameters_sha256 VARCHAR NOT NULL,
                result_route_id VARCHAR NOT NULL,
                replacement_sha256 VARCHAR NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (
                    successor_generation_sha256,
                    source_scope_sha256,
                    staging_key
                )
            )
            """
        )
        for column in (
            "canonical_frame_format",
            "frame_content_hash_contract",
            "frame_schema_hash_contract",
        ):
            self._conn.execute(
                "ALTER TABLE _successor_staging_replacement_journal "
                f"ADD COLUMN IF NOT EXISTS {column} VARCHAR"
            )

    def persist_frames(
        self,
        frames: dict[str, pl.DataFrame],
        *,
        metadata: StagingChunkMetadata,
        expected_staging_keys: Iterable[str] | None = None,
        materialize: bool = False,
        dedupe_materialized: bool = False,
        replace_existing_chunk: bool = False,
        receipt_binding: LogicalCallReceiptBinding | None = None,
        result_route_ids_by_staging_key: tuple[tuple[str, str], ...] = (),
        successor_generation_sha256: str | None = None,
    ) -> StagingPersistResult:
        return self.persist_frame_batches(
            [
                StagingFrameBatch(
                    frames=frames,
                    metadata=metadata,
                    expected_staging_keys=tuple(expected_staging_keys or ()),
                    dedupe_materialized=dedupe_materialized,
                    replace_existing_chunk=replace_existing_chunk,
                    receipt_binding=receipt_binding,
                    result_route_ids_by_staging_key=result_route_ids_by_staging_key,
                    successor_generation_sha256=successor_generation_sha256,
                )
            ],
            materialize=materialize,
        )

    def persist_lossless_fallback(
        self,
        frame: pl.DataFrame,
        *,
        metadata: StagingChunkMetadata,
        receipt_binding: LogicalCallReceiptBinding,
        result_route_id: str,
        materialize: bool = False,
        replace_existing_chunk: bool = False,
        successor_generation_sha256: str | None = None,
    ) -> StagingPersistResult:
        """Persist one universal fallback projection under its logical receipt.

        The frame retains the response-attempt receipt while the staging journal
        binds the universal route to the already finalized logical-call root.
        This method deliberately does not create or finalize that root.
        """

        return self.persist_frames(
            {LOSSLESS_FALLBACK_STAGING_KEY: frame},
            metadata=metadata,
            expected_staging_keys=(LOSSLESS_FALLBACK_STAGING_KEY,),
            materialize=materialize,
            replace_existing_chunk=replace_existing_chunk,
            receipt_binding=receipt_binding,
            result_route_ids_by_staging_key=((LOSSLESS_FALLBACK_STAGING_KEY, result_route_id),),
            successor_generation_sha256=successor_generation_sha256,
        )

    def persist_frame_batches(
        self,
        batches: Iterable[StagingFrameBatch],
        *,
        materialize: bool = False,
    ) -> StagingPersistResult:
        batch_list = list(batches)
        if not batch_list:
            return StagingPersistResult()
        for batch in batch_list:
            fallback_expected = LOSSLESS_FALLBACK_STAGING_KEY in (
                set(batch.frames) | set(batch.expected_staging_keys)
            )
            if fallback_expected:
                fallback = batch.frames.get(LOSSLESS_FALLBACK_STAGING_KEY)
                if fallback is None:
                    raise ParserInputCaptureIntegrityError(
                        "lossless fallback route omitted its fixed-contract frame"
                    )
                _validate_persisted_lossless_fallback(fallback)
            live_lossless_expected = LIVE_LOSSLESS_STAGING_KEY in (
                set(batch.frames) | set(batch.expected_staging_keys)
            )
            if live_lossless_expected:
                live_lossless = batch.frames.get(LIVE_LOSSLESS_STAGING_KEY)
                if live_lossless is None:
                    raise ParserInputCaptureIntegrityError(
                        "live-lossless route omitted its fixed-contract frame"
                    )
                _validate_persisted_live_lossless(live_lossless, batch)

        with _WRITE_LOCK:
            self._conn.execute("BEGIN TRANSACTION")
            try:
                result = self._persist_frame_batch_list(
                    batch_list,
                    materialize=materialize,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        self._log_persist_result(result)
        return result

    def committed_logical_call_receipts(
        self,
        binding: LogicalCallReceiptBinding,
    ) -> tuple[CommittedStagingChunkReceiptV2, ...]:
        """Read the exact committed staging inventory for one logical call.

        This query is intentionally separate from ``persist_frame_batches``.
        A caller can invoke it only after the store-owned transaction returns,
        so its result cannot accidentally certify an uncommitted callback or a
        caller-owned transaction that may still roll back.
        """

        if type(binding) is not LogicalCallReceiptBinding:
            raise ParserInputCaptureIntegrityError(
                "committed staging receipt query requires a logical-call binding"
            )
        if self._caller_transaction_active:
            raise ParserInputCaptureIntegrityError(
                "committed staging receipts are unavailable inside a caller-owned transaction"
            )
        with _WRITE_LOCK:
            if self._caller_transaction_active:
                raise ParserInputCaptureIntegrityError(
                    "committed staging receipts are unavailable inside a caller-owned transaction"
                )
            rows = self._conn.execute(
                """
                SELECT chunk_id,
                       staging_key,
                       canonical_frame_format,
                       frame_content_hash_contract,
                       frame_schema_hash_contract,
                       content_hash,
                       persisted_row_count,
                       persisted_content_sha256,
                       persisted_schema_sha256,
                       logical_call_receipt_sha256,
                       provider_authority_sha256,
                       logical_parameters_sha256,
                       result_route_id
                FROM _staging_chunk_journal
                WHERE logical_call_receipt_sha256 = $1
                ORDER BY result_route_id, staging_key, chunk_id
                """,
                [binding.logical_call_receipt_sha256],
            ).fetchall()
        receipts: list[CommittedStagingChunkReceiptV2] = []
        for row in rows:
            receipt = _committed_receipt_from_journal_row(tuple(row))
            if (
                receipt.logical_call_receipt_sha256 != binding.logical_call_receipt_sha256
                or receipt.provider_authority_sha256 != binding.provider_authority_sha256
                or receipt.logical_parameters_sha256 != binding.logical_parameters_sha256
            ):
                raise ParserInputCaptureIntegrityError(
                    "committed staging receipt differs from its logical-call authority"
                )
            receipts.append(receipt)

        route_ids = tuple(receipt.result_route_id for receipt in receipts)
        if (
            not receipts
            or route_ids != tuple(sorted(route_ids))
            or len(route_ids) != len(set(route_ids))
            or set(route_ids) != set(binding.result_route_ids)
        ):
            raise ParserInputCaptureIntegrityError(
                "committed staging receipts do not exactly cover the logical-call routes"
            )
        return tuple(receipts)

    def committed_staging_frame_readback(
        self,
        receipt: CommittedStagingChunkReceiptV2,
    ) -> CommittedStagingFrameReadbackV2:
        """Re-read and independently rehash one exact committed chunk frame.

        No caller frame and no ``_stored_chunk_frame`` fallback is accepted.
        A receipt whose internal rows are absent, reordered, schema-widened, or
        otherwise different from its journal authority fails closed.
        """

        exact_receipt = _validated_committed_receipt(receipt)
        if self._caller_transaction_active:
            raise ParserInputCaptureIntegrityError(
                "committed staging frame readback is unavailable inside an active transaction"
            )
        with _WRITE_LOCK:
            if self._caller_transaction_active:
                raise ParserInputCaptureIntegrityError(
                    "committed staging frame readback is unavailable inside an active transaction"
                )
            row = self._conn.execute(
                """
                SELECT chunk_id,
                       staging_key,
                       canonical_frame_format,
                       frame_content_hash_contract,
                       frame_schema_hash_contract,
                       content_hash,
                       persisted_row_count,
                       persisted_content_sha256,
                       persisted_schema_sha256,
                       logical_call_receipt_sha256,
                       provider_authority_sha256,
                       logical_parameters_sha256,
                       result_route_id
                FROM _staging_chunk_journal
                WHERE chunk_id = $1 AND staging_key = $2
                """,
                [exact_receipt.chunk_id, exact_receipt.staging_key],
            ).fetchone()
            if row is None:
                raise ParserInputCaptureIntegrityError(
                    "committed staging frame receipt is stale or names the wrong table"
                )
            journal_receipt = _committed_receipt_from_journal_row(tuple(row))
            if (
                journal_receipt.identity_payload() != exact_receipt.identity_payload()
                or journal_receipt.receipt_root_sha256 != exact_receipt.receipt_root_sha256
            ):
                raise ParserInputCaptureIntegrityError(
                    "committed staging frame receipt differs from its exact journal row"
                )

            internal = self._chunk_table_name(exact_receipt.staging_key)
            if not self._table_exists(internal):
                canonical_empty = pl.DataFrame()
                if (
                    exact_receipt.persisted_row_count == 0
                    and exact_receipt.persisted_schema_sha256 == frame_schema_hash(canonical_empty)
                    and exact_receipt.content_hash == frame_content_hash(canonical_empty)
                    and exact_receipt.persisted_content_sha256
                    == frame_content_hash(canonical_empty)
                ):
                    return CommittedStagingFrameReadbackV2.build(
                        committed_receipt=journal_receipt,
                        frame=canonical_empty,
                    )
                raise ParserInputCaptureIntegrityError(
                    "committed staging frame has no internal rows; "
                    "fallback reconstruction is forbidden"
                )
            columns = [name for name, _ in self._table_columns(internal)]
            metadata_columns = {
                "_nbadb_chunk_id",
                "_nbadb_chunk_index",
                "_nbadb_row_index",
            }
            if not metadata_columns.issubset(columns):
                raise ParserInputCaptureIntegrityError(
                    "committed staging internal table lacks exact chunk row authority"
                )
            metadata_rows = self._conn.execute(
                f"""
                SELECT _nbadb_chunk_id, _nbadb_chunk_index, _nbadb_row_index
                FROM {internal}
                WHERE _nbadb_chunk_id = $1
                ORDER BY _nbadb_row_index
                """,
                [exact_receipt.chunk_id],
            ).fetchall()
            if len(metadata_rows) != exact_receipt.persisted_row_count:
                raise ParserInputCaptureIntegrityError(
                    "committed staging internal row count differs from its receipt"
                )
            chunk_indexes: set[int] = set()
            for expected_row_ordinal, metadata_row in enumerate(metadata_rows):
                chunk_id, chunk_index, row_ordinal = metadata_row
                if (
                    type(chunk_id) is not str
                    or chunk_id != exact_receipt.chunk_id
                    or type(chunk_index) is not int
                    or chunk_index < 0
                    or type(row_ordinal) is not int
                    or row_ordinal != expected_row_ordinal
                ):
                    raise ParserInputCaptureIntegrityError(
                        "committed staging internal row order differs from its receipt"
                    )
                chunk_indexes.add(chunk_index)
            if len(chunk_indexes) > 1:
                raise ParserInputCaptureIntegrityError(
                    "committed staging internal rows contain multiple chunk indexes"
                )

            data_columns = [name for name in columns if name not in metadata_columns]
            if not data_columns:
                raise ParserInputCaptureIntegrityError(
                    "committed staging internal table has no typed data columns"
                )
            selected_columns = _quoted_csv(data_columns)
            frame = self._conn.execute(
                f"""
                SELECT {selected_columns}
                FROM {internal}
                WHERE _nbadb_chunk_id = $1
                ORDER BY _nbadb_row_index
                """,
                [exact_receipt.chunk_id],
            ).pl()
            return CommittedStagingFrameReadbackV2.build(
                committed_receipt=journal_receipt,
                frame=frame,
            )

    @contextmanager
    def existing_transaction_writer(self) -> Iterator[_ExistingTransactionWriter]:
        """Hold exclusive staging authority across a caller-owned transaction.

        The caller must begin and finish its database transaction inside this
        context.  Keeping the capability and process write lock alive through
        commit or rollback prevents another in-process writer from interleaving
        with staging, journal, or related authority writes.
        """

        with _WRITE_LOCK:
            if self._caller_transaction_active:
                raise RuntimeError("staging caller-owned transaction is already active")
            self._caller_transaction_active = True
            writer = _ExistingTransactionWriter(self)
            try:
                yield writer
            finally:
                writer._close()
                self._caller_transaction_active = False

    def _persist_frame_batch_list(
        self,
        batch_list: list[StagingFrameBatch],
        *,
        materialize: bool,
    ) -> StagingPersistResult:
        changed_keys: list[str] = []
        tables = rows = inserted = replayed = 0
        replacement_attestations: list[SourceScopeReplacementAttestation] = []
        for batch in batch_list:
            batch_result = self._persist_frame_batch(batch, changed_keys)
            tables += batch_result.staging_tables
            rows += batch_result.rows_persisted
            inserted += batch_result.chunks_inserted
            replayed += batch_result.chunks_replayed
            replacement_attestations.extend(batch_result.replacement_attestations)

        if materialize and changed_keys:
            self.materialize(sorted(set(changed_keys)))
        return StagingPersistResult(
            staging_tables=tables,
            rows_persisted=rows,
            chunks_inserted=inserted,
            chunks_replayed=replayed,
            replacement_attestations=tuple(replacement_attestations),
        )

    @staticmethod
    def _log_persist_result(result: StagingPersistResult) -> None:
        logger.info(
            "persisted {} staging chunk tables, {} rows ({} replayed)",
            result.staging_tables,
            result.rows_persisted,
            result.chunks_replayed,
        )

    def _persist_frame_batch(
        self,
        batch: StagingFrameBatch,
        changed_keys: list[str],
    ) -> StagingPersistResult:
        tables = rows = inserted = replayed = 0
        replacement_attestations: list[SourceScopeReplacementAttestation] = []
        expected_keys = sorted(set(batch.frames) | set(batch.expected_staging_keys))
        route_ids = self._validated_route_ids(batch, expected_keys)
        successor_generation = batch.successor_generation_sha256
        successor_binding = batch.receipt_binding
        if successor_generation is not None:
            if _SHA256_RE.fullmatch(successor_generation) is None:
                raise ParserInputCaptureIntegrityError(
                    "successor generation identity must be a lowercase SHA-256"
                )
            if not batch.replace_existing_chunk:
                raise ParserInputCaptureIntegrityError(
                    "successor staging persistence must replace its exact source scope"
                )
            if successor_binding is None:
                raise ParserInputCaptureIntegrityError(
                    "successor staging persistence requires a logical-call receipt"
                )
            if (
                batch.metadata.source_endpoint_name is None
                or batch.metadata.source_params_digest is None
            ):
                raise ParserInputCaptureIntegrityError(
                    "successor staging persistence requires exact source identity"
                )
        for staging_key in expected_keys:
            df = batch.frames.get(staging_key, pl.DataFrame())
            safe_key = validate_sql_identifier(staging_key)
            content_hash = frame_content_hash(df)
            chunk_id = self._chunk_id(safe_key, batch.metadata)
            stored_chunk_id = chunk_id
            existing = self._existing_chunk(chunk_id, safe_key)
            if existing is None:
                legacy_chunk_id = self._legacy_source_chunk_id(safe_key, batch.metadata)
                if legacy_chunk_id is not None:
                    existing = self._existing_chunk(legacy_chunk_id, safe_key)
                    if existing is not None:
                        stored_chunk_id = legacy_chunk_id
                        if successor_generation is not None:
                            pass
                        elif existing.content_hash == content_hash:
                            self._rename_chunk(
                                safe_key,
                                old_chunk_id=legacy_chunk_id,
                                new_chunk_id=chunk_id,
                            )
                            stored_chunk_id = chunk_id
                        elif batch.replace_existing_chunk:
                            self._delete_chunk(safe_key, legacy_chunk_id)
                            existing = None
                        else:
                            msg = (
                                f"staging chunk hash mismatch for {safe_key} "
                                f"{legacy_chunk_id}: {existing.content_hash} != {content_hash}"
                            )
                            raise RuntimeError(msg)

            if successor_generation is not None:
                if successor_binding is None:  # pragma: no cover - validated above
                    raise ParserInputCaptureIntegrityError(
                        "successor staging receipt disappeared during persistence"
                    )
                route_id = route_ids[safe_key]
                source_scope_sha256 = successor_binding.logical_parameters_sha256
                recorded_replacement = self._existing_successor_replacement(
                    successor_generation,
                    source_scope_sha256=source_scope_sha256,
                    staging_key=safe_key,
                )
                if recorded_replacement is not None:
                    if stored_chunk_id != chunk_id or existing is None:
                        raise ParserInputCaptureIntegrityError(
                            "successor replacement receipt lacks its canonical staging chunk"
                        )
                    self._require_matching_attestation(
                        existing,
                        successor_binding,
                        route_id,
                    )
                    self._require_replacement_matches_chunk(
                        recorded_replacement,
                        existing,
                        content_hash=content_hash,
                    )
                    replacement_attestations.append(recorded_replacement)
                    replayed += 1
                    continue

                prior_persisted_content_sha256: str | None = None
                if existing is not None:
                    self._require_complete_existing_attestation(existing)
                    prior_persisted_content_sha256 = existing.persisted_content_sha256
                    self._delete_chunk(safe_key, stored_chunk_id)
                    existing = None
            elif existing is not None:
                if existing.content_hash != content_hash:
                    if batch.replace_existing_chunk:
                        self._delete_chunk(safe_key, stored_chunk_id)
                        existing = None
                    else:
                        msg = (
                            f"staging chunk hash mismatch for {safe_key} "
                            f"{chunk_id}: {existing.content_hash} != {content_hash}"
                        )
                        raise RuntimeError(msg)
                if existing is not None:
                    if batch.receipt_binding is not None:
                        route_id = route_ids[safe_key]
                        if existing.has_no_receipt_binding:
                            persisted_frame = self._stored_chunk_frame(
                                safe_key,
                                chunk_id,
                                fallback=df,
                            )
                            self._upgrade_chunk_attestation(
                                chunk_id,
                                safe_key,
                                persisted_frame=persisted_frame,
                                receipt_binding=batch.receipt_binding,
                                result_route_id=route_id,
                            )
                        else:
                            try:
                                self._require_matching_attestation(
                                    existing,
                                    batch.receipt_binding,
                                    route_id,
                                )
                            except ParserInputCaptureIntegrityError:
                                if not batch.replace_existing_chunk:
                                    raise
                                # A successor refresh may produce byte-identical rows
                                # under a new logical-call receipt.  It is a fresh
                                # observation, not a replay of the baseline receipt.
                                self._delete_chunk(safe_key, chunk_id)
                                existing = None
                    if existing is None:
                        pass
                    else:
                        replayed += 1
                        continue

            frame_to_append = df
            if df.columns:
                frame_to_append = self._legacy_filtered_frame(safe_key, df)
                if (
                    not frame_to_append.is_empty()
                    and batch.dedupe_materialized
                    and self._table_exists(safe_key)
                ):
                    frame_to_append = self._filtered_against_table(safe_key, frame_to_append)
                self._append_chunk_frame(
                    safe_key,
                    chunk_id,
                    batch.metadata.chunk_index,
                    frame_to_append,
                )
            persisted_frame = self._stored_chunk_frame(
                safe_key,
                chunk_id,
                fallback=frame_to_append,
            )
            self._record_chunk(
                chunk_id,
                safe_key,
                row_count=df.height,
                content_hash=content_hash,
                source_label=batch.metadata.source_label,
                persisted_frame=persisted_frame,
                receipt_binding=batch.receipt_binding,
                result_route_id=route_ids.get(safe_key),
            )
            if successor_generation is not None:
                receipt_binding = successor_binding
                if receipt_binding is None:  # pragma: no cover - validated above
                    raise ParserInputCaptureIntegrityError(
                        "successor staging receipt disappeared during persistence"
                    )
                replacement = SourceScopeReplacementAttestation(
                    successor_generation_sha256=successor_generation,
                    source_scope_sha256=receipt_binding.logical_parameters_sha256,
                    staging_key=safe_key,
                    canonical_frame_format=CANONICAL_FRAME_FORMAT,
                    frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
                    frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
                    prior_persisted_content_sha256=prior_persisted_content_sha256,
                    persisted_content_sha256=frame_content_hash(persisted_frame),
                    persisted_schema_sha256=frame_schema_hash(persisted_frame),
                    persisted_row_count=persisted_frame.height,
                    logical_call_receipt_sha256=(receipt_binding.logical_call_receipt_sha256),
                    provider_authority_sha256=receipt_binding.provider_authority_sha256,
                    logical_parameters_sha256=receipt_binding.logical_parameters_sha256,
                    result_route_id=route_ids[safe_key],
                )
                self._record_successor_replacement(replacement)
                replacement_attestations.append(replacement)
            if batch.replace_existing_chunk or frame_to_append.columns:
                changed_keys.append(safe_key)
            tables += 1
            rows += frame_to_append.height
            inserted += 1
        return StagingPersistResult(
            staging_tables=tables,
            rows_persisted=rows,
            chunks_inserted=inserted,
            chunks_replayed=replayed,
            replacement_attestations=tuple(replacement_attestations),
        )

    def materialize(self, staging_keys: Iterable[str] | None = None) -> int:
        keys = list(staging_keys) if staging_keys is not None else self._chunk_staging_keys()
        count = 0
        for staging_key in keys:
            safe_key = validate_sql_identifier(staging_key)
            internal = self._chunk_table_name(safe_key)
            if not self._table_exists(internal):
                continue
            self._conn.execute(
                f"""
                CREATE OR REPLACE TABLE {safe_key} AS
                SELECT * EXCLUDE (_nbadb_chunk_id, _nbadb_chunk_index, _nbadb_row_index)
                FROM {internal}
                ORDER BY _nbadb_chunk_index, _nbadb_row_index, _nbadb_chunk_id
                """
            )
            count += 1
        return count

    def _chunk_id(
        self,
        staging_key: str,
        metadata: StagingChunkMetadata,
    ) -> str:
        if metadata.source_endpoint_name is not None and metadata.source_params_digest is not None:
            payload = {
                "staging_key": staging_key,
                "pattern": metadata.pattern,
                "source_endpoint_name": metadata.source_endpoint_name,
                "source_params_digest": metadata.source_params_digest,
            }
        else:
            payload = {
                "staging_key": staging_key,
                "run_mode": metadata.run_mode,
                "lane_id": metadata.lane_id,
                "pattern": metadata.pattern,
                "chunk_index": metadata.chunk_index,
                "params_digest": metadata.params_digest,
                "entries_digest": metadata.entries_digest,
            }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _legacy_source_chunk_id(
        self,
        staging_key: str,
        metadata: StagingChunkMetadata,
    ) -> str | None:
        if metadata.source_endpoint_name is None or metadata.source_params_digest is None:
            return None
        payload = {
            "staging_key": staging_key,
            "run_mode": metadata.run_mode,
            "pattern": metadata.pattern,
            "source_endpoint_name": metadata.source_endpoint_name,
            "source_params_digest": metadata.source_params_digest,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _existing_chunk(
        self,
        chunk_id: str,
        staging_key: str,
    ) -> _StoredChunkJournal | None:
        row = self._conn.execute(
            """
            SELECT content_hash,
                   canonical_frame_format,
                   frame_content_hash_contract,
                   frame_schema_hash_contract,
                   persisted_row_count,
                   persisted_content_sha256,
                   persisted_schema_sha256,
                   logical_call_receipt_sha256,
                   provider_authority_sha256,
                   logical_parameters_sha256,
                   result_route_id
            FROM _staging_chunk_journal
            WHERE chunk_id = $1 AND staging_key = $2
            """,
            [chunk_id, staging_key],
        ).fetchone()
        if row is None:
            return None
        return _StoredChunkJournal(
            content_hash=str(row[0]),
            canonical_frame_format=row[1],
            frame_content_hash_contract=row[2],
            frame_schema_hash_contract=row[3],
            persisted_row_count=row[4],
            persisted_content_sha256=row[5],
            persisted_schema_sha256=row[6],
            logical_call_receipt_sha256=row[7],
            provider_authority_sha256=row[8],
            logical_parameters_sha256=row[9],
            result_route_id=row[10],
        )

    def _existing_successor_replacement(
        self,
        successor_generation_sha256: str,
        *,
        source_scope_sha256: str,
        staging_key: str,
    ) -> SourceScopeReplacementAttestation | None:
        row = self._conn.execute(
            """
            SELECT canonical_frame_format,
                   frame_content_hash_contract,
                   frame_schema_hash_contract,
                   prior_persisted_content_sha256,
                   persisted_content_sha256,
                   persisted_schema_sha256,
                   persisted_row_count,
                   logical_call_receipt_sha256,
                   provider_authority_sha256,
                   logical_parameters_sha256,
                   result_route_id,
                   replacement_sha256
            FROM _successor_staging_replacement_journal
            WHERE successor_generation_sha256 = $1
              AND source_scope_sha256 = $2
              AND staging_key = $3
            """,
            [successor_generation_sha256, source_scope_sha256, staging_key],
        ).fetchone()
        if row is None:
            return None
        replacement = SourceScopeReplacementAttestation(
            successor_generation_sha256=successor_generation_sha256,
            source_scope_sha256=source_scope_sha256,
            staging_key=staging_key,
            canonical_frame_format=row[0],
            frame_content_hash_contract=row[1],
            frame_schema_hash_contract=row[2],
            prior_persisted_content_sha256=row[3],
            persisted_content_sha256=str(row[4]),
            persisted_schema_sha256=str(row[5]),
            persisted_row_count=int(row[6]),
            logical_call_receipt_sha256=str(row[7]),
            provider_authority_sha256=str(row[8]),
            logical_parameters_sha256=str(row[9]),
            result_route_id=str(row[10]),
        )
        if replacement.replacement_sha256 != row[11]:
            raise ParserInputCaptureIntegrityError(
                "successor replacement receipt digest does not match its stored evidence"
            )
        return replacement

    def _record_successor_replacement(
        self,
        replacement: SourceScopeReplacementAttestation,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO _successor_staging_replacement_journal
                (successor_generation_sha256, source_scope_sha256, staging_key,
                 canonical_frame_format, frame_content_hash_contract,
                 frame_schema_hash_contract,
                 prior_persisted_content_sha256, persisted_content_sha256,
                 persisted_schema_sha256, persisted_row_count,
                 logical_call_receipt_sha256, provider_authority_sha256,
                 logical_parameters_sha256, result_route_id, replacement_sha256)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            """,
            [
                replacement.successor_generation_sha256,
                replacement.source_scope_sha256,
                replacement.staging_key,
                replacement.canonical_frame_format,
                replacement.frame_content_hash_contract,
                replacement.frame_schema_hash_contract,
                replacement.prior_persisted_content_sha256,
                replacement.persisted_content_sha256,
                replacement.persisted_schema_sha256,
                replacement.persisted_row_count,
                replacement.logical_call_receipt_sha256,
                replacement.provider_authority_sha256,
                replacement.logical_parameters_sha256,
                replacement.result_route_id,
                replacement.replacement_sha256,
            ],
        )

    @staticmethod
    def _require_complete_existing_attestation(existing: _StoredChunkJournal) -> None:
        if existing.has_no_receipt_binding:
            raise ParserInputCaptureIntegrityError(
                "successor replacement requires a receipt-bound prior source scope"
            )
        if (
            isinstance(existing.persisted_row_count, bool)
            or not isinstance(existing.persisted_row_count, int)
            or existing.persisted_row_count < 0
            or not isinstance(existing.persisted_content_sha256, str)
            or _SHA256_RE.fullmatch(existing.persisted_content_sha256) is None
            or not isinstance(existing.persisted_schema_sha256, str)
            or _SHA256_RE.fullmatch(existing.persisted_schema_sha256) is None
            or not isinstance(existing.logical_call_receipt_sha256, str)
            or _SHA256_RE.fullmatch(existing.logical_call_receipt_sha256) is None
            or not isinstance(existing.provider_authority_sha256, str)
            or _SHA256_RE.fullmatch(existing.provider_authority_sha256) is None
            or not isinstance(existing.logical_parameters_sha256, str)
            or _SHA256_RE.fullmatch(existing.logical_parameters_sha256) is None
            or not isinstance(existing.result_route_id, str)
            or not existing.result_route_id
        ):
            raise ParserInputCaptureIntegrityError(
                "successor replacement prior source scope has incomplete attestation"
            )

    @staticmethod
    def _require_replacement_matches_chunk(
        replacement: SourceScopeReplacementAttestation,
        existing: _StoredChunkJournal,
        *,
        content_hash: str,
    ) -> None:
        if (
            existing.content_hash != content_hash
            or replacement.canonical_frame_format != existing.canonical_frame_format
            or replacement.frame_content_hash_contract != existing.frame_content_hash_contract
            or replacement.frame_schema_hash_contract != existing.frame_schema_hash_contract
            or replacement.persisted_content_sha256 != existing.persisted_content_sha256
            or replacement.persisted_schema_sha256 != existing.persisted_schema_sha256
            or replacement.persisted_row_count != existing.persisted_row_count
            or replacement.logical_call_receipt_sha256 != existing.logical_call_receipt_sha256
            or replacement.provider_authority_sha256 != existing.provider_authority_sha256
            or replacement.logical_parameters_sha256 != existing.logical_parameters_sha256
            or replacement.result_route_id != existing.result_route_id
        ):
            raise ParserInputCaptureIntegrityError(
                "successor replacement receipt does not match its persisted staging chunk"
            )

    def _record_chunk(
        self,
        chunk_id: str,
        staging_key: str,
        *,
        row_count: int,
        content_hash: str,
        source_label: str,
        persisted_frame: pl.DataFrame,
        receipt_binding: LogicalCallReceiptBinding | None,
        result_route_id: str | None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO _staging_chunk_journal
                (chunk_id, staging_key, canonical_frame_format,
                 frame_content_hash_contract, frame_schema_hash_contract,
                 row_count, content_hash, source_label,
                 persisted_row_count, persisted_content_sha256,
                 persisted_schema_sha256, logical_call_receipt_sha256,
                 provider_authority_sha256, logical_parameters_sha256,
                 result_route_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            """,
            [
                chunk_id,
                staging_key,
                CANONICAL_FRAME_FORMAT,
                FRAME_CONTENT_HASH_CONTRACT,
                FRAME_SCHEMA_HASH_CONTRACT,
                row_count,
                content_hash,
                source_label,
                persisted_frame.height,
                frame_content_hash(persisted_frame),
                frame_schema_hash(persisted_frame),
                (
                    receipt_binding.logical_call_receipt_sha256
                    if receipt_binding is not None
                    else None
                ),
                (
                    receipt_binding.provider_authority_sha256
                    if receipt_binding is not None
                    else None
                ),
                (
                    receipt_binding.logical_parameters_sha256
                    if receipt_binding is not None
                    else None
                ),
                result_route_id,
            ],
        )

    def _upgrade_chunk_attestation(
        self,
        chunk_id: str,
        staging_key: str,
        *,
        persisted_frame: pl.DataFrame,
        receipt_binding: LogicalCallReceiptBinding,
        result_route_id: str,
    ) -> None:
        self._conn.execute(
            """
            UPDATE _staging_chunk_journal
            SET canonical_frame_format = $1,
                frame_content_hash_contract = $2,
                frame_schema_hash_contract = $3,
                persisted_row_count = $4,
                persisted_content_sha256 = $5,
                persisted_schema_sha256 = $6,
                logical_call_receipt_sha256 = $7,
                provider_authority_sha256 = $8,
                logical_parameters_sha256 = $9,
                result_route_id = $10
            WHERE chunk_id = $11 AND staging_key = $12
            """,
            [
                CANONICAL_FRAME_FORMAT,
                FRAME_CONTENT_HASH_CONTRACT,
                FRAME_SCHEMA_HASH_CONTRACT,
                persisted_frame.height,
                frame_content_hash(persisted_frame),
                frame_schema_hash(persisted_frame),
                receipt_binding.logical_call_receipt_sha256,
                receipt_binding.provider_authority_sha256,
                receipt_binding.logical_parameters_sha256,
                result_route_id,
                chunk_id,
                staging_key,
            ],
        )

    @staticmethod
    def _require_matching_attestation(
        existing: _StoredChunkJournal,
        binding: LogicalCallReceiptBinding,
        result_route_id: str,
    ) -> None:
        if (
            isinstance(existing.persisted_row_count, bool)
            or not isinstance(existing.persisted_row_count, int)
            or existing.persisted_row_count < 0
            or not isinstance(existing.persisted_content_sha256, str)
            or _SHA256_RE.fullmatch(existing.persisted_content_sha256) is None
            or not isinstance(existing.persisted_schema_sha256, str)
            or _SHA256_RE.fullmatch(existing.persisted_schema_sha256) is None
            or existing.logical_call_receipt_sha256 != binding.logical_call_receipt_sha256
            or existing.provider_authority_sha256 != binding.provider_authority_sha256
            or existing.logical_parameters_sha256 != binding.logical_parameters_sha256
            or existing.result_route_id != result_route_id
        ):
            raise ParserInputCaptureIntegrityError(
                "staging chunk receipt attestation does not match the logical call"
            )

    @staticmethod
    def _validated_route_ids(
        batch: StagingFrameBatch,
        expected_keys: list[str],
    ) -> dict[str, str]:
        raw_pairs = batch.result_route_ids_by_staging_key
        if batch.receipt_binding is None:
            if raw_pairs:
                raise ParserInputCaptureIntegrityError(
                    "staging route IDs require a logical-call receipt binding"
                )
            return {}
        route_ids = dict(raw_pairs)
        if len(route_ids) != len(raw_pairs) or set(route_ids) != set(expected_keys):
            raise ParserInputCaptureIntegrityError(
                "staging route IDs do not match the expected staging keys"
            )
        if tuple(sorted(route_ids.values())) != batch.receipt_binding.result_route_ids:
            raise ParserInputCaptureIntegrityError(
                "staging route IDs do not match the logical-call receipt"
            )
        endpoint = batch.metadata.source_endpoint_name
        if endpoint is None:
            raise ParserInputCaptureIntegrityError(
                "receipt-bound staging requires a source endpoint name"
            )
        for staging_key, route_id in route_ids.items():
            try:
                route_endpoint, route_key, raw_index = route_id.rsplit(":", 2)
                result_index = int(raw_index)
            except (ValueError, TypeError):
                raise ParserInputCaptureIntegrityError(
                    "staging result route ID is malformed"
                ) from None
            if (
                route_endpoint != endpoint
                or route_key != staging_key
                or result_index < 0
                or raw_index != str(result_index)
            ):
                raise ParserInputCaptureIntegrityError(
                    "staging result route ID does not match its source route"
                )
        return route_ids

    def _stored_chunk_frame(
        self,
        staging_key: str,
        chunk_id: str,
        *,
        fallback: pl.DataFrame,
    ) -> pl.DataFrame:
        if fallback.is_empty():
            return fallback
        internal = self._chunk_table_name(staging_key)
        if not self._table_exists(internal):
            return fallback
        data_columns = [
            name
            for name, _ in self._table_columns(internal)
            if name
            not in {
                "_nbadb_chunk_id",
                "_nbadb_chunk_index",
                "_nbadb_row_index",
            }
        ]
        if not data_columns:
            return pl.DataFrame()
        columns = _quoted_csv(data_columns)
        return self._conn.execute(
            f"""
            SELECT {columns}
            FROM {internal}
            WHERE _nbadb_chunk_id = $1
            ORDER BY _nbadb_row_index
            """,
            [chunk_id],
        ).pl()

    def _rename_chunk(self, staging_key: str, *, old_chunk_id: str, new_chunk_id: str) -> None:
        if old_chunk_id == new_chunk_id:
            return
        internal = self._chunk_table_name(staging_key)
        if self._table_exists(internal):
            self._conn.execute(
                f"UPDATE {internal} SET _nbadb_chunk_id = $1 WHERE _nbadb_chunk_id = $2",
                [new_chunk_id, old_chunk_id],
            )
        self._conn.execute(
            """
            UPDATE _staging_chunk_journal
            SET chunk_id = $1
            WHERE chunk_id = $2 AND staging_key = $3
            """,
            [new_chunk_id, old_chunk_id, staging_key],
        )

    def _delete_chunk(self, staging_key: str, chunk_id: str) -> None:
        internal = self._chunk_table_name(staging_key)
        if self._table_exists(internal):
            self._conn.execute(
                f"DELETE FROM {internal} WHERE _nbadb_chunk_id = $1",
                [chunk_id],
            )
        self._conn.execute(
            """
            DELETE FROM _staging_chunk_journal
            WHERE chunk_id = $1 AND staging_key = $2
            """,
            [chunk_id, staging_key],
        )

    def _legacy_filtered_frame(self, staging_key: str, df: pl.DataFrame) -> pl.DataFrame:
        internal = self._chunk_table_name(staging_key)
        if not self._table_exists(staging_key) or self._table_exists(internal):
            return df

        temp_name = "_nbadb_legacy_chunk_tmp"
        filtered = self._filtered_against_table(staging_key, df, temp_name=temp_name)
        self._seed_legacy_table(staging_key)
        return filtered

    def _filtered_against_table(
        self,
        staging_key: str,
        df: pl.DataFrame,
        *,
        temp_name: str = "_nbadb_staging_diff_tmp",
    ) -> pl.DataFrame:
        if df.is_empty():
            return df
        if not set(df.columns).issubset(self._data_columns(staging_key)):
            return df
        self._conn.register(temp_name, df)
        try:
            columns = _quoted_csv(df.columns)
            return self._conn.execute(
                f"SELECT {columns} FROM {temp_name} EXCEPT ALL SELECT {columns} FROM {staging_key}"
            ).pl()
        finally:
            self._conn.unregister(temp_name)

    def _seed_legacy_table(self, staging_key: str) -> None:
        internal = self._chunk_table_name(staging_key)
        if self._table_exists(internal):
            return
        self._conn.execute(
            f"""
            CREATE TABLE {internal} AS
            SELECT
                -1 AS _nbadb_chunk_index,
                row_number() OVER () - 1 AS _nbadb_row_index,
                *,
                '__legacy__' AS _nbadb_chunk_id
            FROM {staging_key}
            """
        )

    def _append_chunk_frame(
        self,
        staging_key: str,
        chunk_id: str,
        chunk_index: int,
        df: pl.DataFrame,
    ) -> None:
        internal = self._chunk_table_name(staging_key)
        chunk_df = df.with_row_index("_nbadb_row_index").with_columns(
            pl.lit(chunk_index).alias("_nbadb_chunk_index"),
            pl.lit(chunk_id).alias("_nbadb_chunk_id"),
        )
        temp_name = "_nbadb_staging_chunk_tmp"
        self._conn.register(temp_name, chunk_df)
        try:
            if self._table_exists(internal):
                self._ensure_chunk_table_shape(internal, temp_name)
                target_columns = [name for name, _ in self._table_columns(internal)]
                select_columns = self._aligned_select_columns(temp_name, target_columns, internal)
                self._conn.execute(
                    f"""
                    INSERT INTO {internal} ({_quoted_csv(target_columns)})
                    SELECT {", ".join(select_columns)}
                    FROM {temp_name}
                    """
                )
            else:
                self._conn.execute(f"CREATE TABLE {internal} AS SELECT * FROM {temp_name}")
        finally:
            self._conn.unregister(temp_name)

    def _chunk_staging_keys(self) -> list[str]:
        prefix = "_staging_chunks__"
        rows = self._conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
        return sorted(
            table_name[len(prefix) :]
            for row in rows
            if (table_name := str(row[0])).startswith(prefix)
        )

    def _chunk_table_name(self, staging_key: str) -> str:
        return validate_sql_identifier(f"_staging_chunks__{staging_key}")

    def _data_columns(self, table_name: str) -> set[str]:
        return {
            name
            for name, _ in self._table_columns(table_name)
            if name
            not in {
                "_nbadb_chunk_id",
                "_nbadb_chunk_index",
                "_nbadb_row_index",
            }
        }

    def _table_columns(self, table_name: str) -> list[tuple[str, str]]:
        rows = self._conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = $1
            ORDER BY ordinal_position
            """,
            [table_name],
        ).fetchall()
        return [(str(name), str(data_type)) for name, data_type in rows]

    def _ensure_chunk_table_shape(self, internal: str, temp_name: str) -> None:
        internal_columns = dict(self._table_columns(internal))
        if "_nbadb_chunk_index" not in internal_columns:
            self._conn.execute(f"ALTER TABLE {internal} ADD COLUMN _nbadb_chunk_index BIGINT")
            self._conn.execute(
                f"UPDATE {internal} SET _nbadb_chunk_index = 0 WHERE _nbadb_chunk_index IS NULL"
            )
            internal_columns = dict(self._table_columns(internal))

        for column, data_type in self._table_columns(temp_name):
            if column not in internal_columns:
                safe_column = validate_sql_identifier(column)
                self._conn.execute(f"ALTER TABLE {internal} ADD COLUMN {safe_column} {data_type}")

    def _aligned_select_columns(
        self,
        temp_name: str,
        target_columns: list[str],
        internal: str,
    ) -> list[str]:
        temp_columns = dict(self._table_columns(temp_name))
        internal_columns = dict(self._table_columns(internal))
        select_columns: list[str] = []
        for column in target_columns:
            safe_column = validate_sql_identifier(column)
            target_type = internal_columns[column]
            if column in temp_columns:
                select_columns.append(f"CAST({safe_column} AS {target_type}) AS {safe_column}")
            else:
                select_columns.append(f"CAST(NULL AS {target_type}) AS {safe_column}")
        return select_columns

    def _table_exists(self, table_name: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = $1
            """,
            [table_name],
        ).fetchone()
        return row is not None
