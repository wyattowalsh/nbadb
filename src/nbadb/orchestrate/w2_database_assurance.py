"""Read-only, database-derived assurance for complete W2 authority.

The verifier closes one durable database over three independent boundaries:

* W2-required successful extraction-journal admissions and all nine pins;
* the separately persisted Raw Request Authority V2 exact-four bundle; and
* the exact-six W2 public relations, including the mandatory operation row.

It performs no migration, persistence, staging, extraction, or publication.
Raw Authority V2 inventory roots remain explicitly separate from the exact-six
W2 publication roots.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager, suppress
from dataclasses import dataclass, fields
from types import MethodType
from typing import TYPE_CHECKING, Any, ClassVar, Final, Never, cast

import duckdb
import polars as pl

if TYPE_CHECKING:
    from collections.abc import Iterator

from nbadb.contracts.raw_request_authority import (
    RawRequestAuthorityBundleV2,
    validate_logical_provider_parameter_join,
)
from nbadb.contracts.raw_result_cell_authority import RawNbaApiResultCellV2
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.contracts.w2_publication_verifier import (
    MAX_W2_PUBLICATION_INPUT_ROWS,
    W2PublicationVerificationReceiptV1,
    verify_w2_publication,
)
from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
from nbadb.extract.bronze import (
    canonical_parameters_payload,
    canonical_parameters_sha256,
)
from nbadb.orchestrate import public_value_authority_store as public_store_module
from nbadb.orchestrate import raw_request_store as raw_store_module
from nbadb.orchestrate import w2_operation_store as operation_store_module
from nbadb.orchestrate.public_value_authority_store import (
    PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL,
    PUBLIC_VALUE_AUTHORITY_TABLES,
)
from nbadb.orchestrate.raw_request_store import RawRequestAuthorityStore
from nbadb.orchestrate.w2_operation_coordinator import (
    W2SourceCallAdmissionV1,
    verify_w2_source_call_admission,
)
from nbadb.orchestrate.w2_operation_store import (
    RAW_NBA_API_W2_OPERATION_TABLE,
    W2OperationStore,
)
from nbadb.orchestrate.w2_publication_inventory import (
    W2PublicValueAuthorityPublicationTable,
    w2_public_value_authority_publication_tables,
)

__all__ = [
    "W2_ON_OFF_SELECTOR_KIND",
    "W2DatabaseAuthorityError",
    "W2DatabaseAuthorityReceiptV1",
    "W2OnOffDatabaseSnapshotV1",
    "W2OnOffPairSnapshotV1",
    "W2OnOffResultOwnershipV1",
    "W2OnOffSourceCallSnapshotV1",
    "verify_w2_database_authority",
    "verify_w2_on_off_database_snapshot",
]


_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_MAX_RECEIPT_BYTES: Final = 256 * 1024
_MAX_CANDIDATE_BYTES: Final = 512 * 1024 * 1024
_MAX_DATABASE_ROWS: Final = (1 << 63) - 1
_MAX_JOURNAL_ROWS: Final = MAX_W2_PUBLICATION_INPUT_ROWS
_JOURNAL_TABLES: Final = ("_extraction_journal", "_successor_extraction_journal")
_W2_EVIDENCE_COLUMNS: Final = (
    "w2_source_call_admission_sha256",
    "w2_source_call_admission_bytes",
    "raw_authority_bundle_sha256",
    "raw_authority_persistence_receipt_sha256",
    "committed_staging_readback_count",
    "committed_staging_readback_root_sha256",
    "w2_operation_key_sha256",
    "w2_operation_receipt_sha256",
    "w2_operation_persistence_receipt_sha256",
)
_JOURNAL_PROJECTION: Final = (
    ("status", "VARCHAR", True),
    ("logical_call_receipt_sha256", "VARCHAR", False),
    ("w2_required", "BOOLEAN", True),
    ("w2_source_call_admission_sha256", "VARCHAR", False),
    ("w2_source_call_admission_bytes", "BLOB", False),
    ("raw_authority_bundle_sha256", "VARCHAR", False),
    ("raw_authority_persistence_receipt_sha256", "VARCHAR", False),
    ("committed_staging_readback_count", "BIGINT", False),
    ("committed_staging_readback_root_sha256", "VARCHAR", False),
    ("w2_operation_key_sha256", "VARCHAR", False),
    ("w2_operation_receipt_sha256", "VARCHAR", False),
    ("w2_operation_persistence_receipt_sha256", "VARCHAR", False),
)
_PUBLIC_KEY_COLUMNS: Final = {
    "raw_nba_api_result_cell": "cell_sha256",
    "raw_nba_api_stats_lossless_record": "record_sha256",
    "raw_nba_api_live_lossless_node": "record_sha256",
    "raw_nba_api_value_representation": "assignment_sha256",
    "raw_nba_api_route_field_landing": "landing_field_sha256",
    "raw_nba_api_w2_operation": "operation_key_sha256",
}
_BUNDLE_COLUMNS: Final = {
    "raw_nba_api_stats_lossless_record": "raw_authority_bundle_sha256",
    "raw_nba_api_live_lossless_node": "raw_authority_bundle_sha256",
    "raw_nba_api_value_representation": "raw_authority_bundle_sha256",
    "raw_nba_api_route_field_landing": "raw_authority_bundle_sha256",
}
W2_ON_OFF_SELECTOR_KIND: Final = "team_player_on_off_exact_v1"
_W2_ON_OFF_ENDPOINTS: Final = (
    ("team_player_on_off_details", "TeamPlayerOnOffDetails"),
    ("team_player_on_off_summary", "TeamPlayerOnOffSummary"),
)
_W2_ON_OFF_PROVIDER_BY_LOGICAL: Final = dict(_W2_ON_OFF_ENDPOINTS)
_W2_ON_OFF_LOGICAL_BY_PROVIDER: Final = {
    provider: logical for logical, provider in _W2_ON_OFF_ENDPOINTS
}
_W2_ON_OFF_RUNTIME_PARAMETER_DOMAIN: Final = (
    "team_id",
    "last_n_games",
    "measure_type_detailed_defense",
    "month",
    "opponent_team_id",
    "pace_adjust",
    "per_mode_detailed",
    "period",
    "plus_minus",
    "rank",
    "season",
    "season_type_all_star",
    "date_from_nullable",
    "date_to_nullable",
    "game_segment_nullable",
    "league_id_nullable",
    "location_nullable",
    "outcome_nullable",
    "season_segment_nullable",
    "vs_conference_nullable",
    "vs_division_nullable",
)
_W2_ON_OFF_SHARED_SCOPE_FIELDS: Final = (
    "date_from_nullable",
    "date_to_nullable",
    "game_segment_nullable",
    "last_n_games",
    "league_id_nullable",
    "location_nullable",
    "measure_type_detailed_defense",
    "month",
    "opponent_team_id",
    "outcome_nullable",
    "pace_adjust",
    "per_mode_detailed",
    "period",
    "plus_minus",
    "rank",
    "season",
    "season_segment_nullable",
    "season_type_all_star",
    "team_id",
    "vs_conference_nullable",
    "vs_division_nullable",
)
_W2_ON_OFF_ROUTE_LAYOUT: Final = {
    "team_player_on_off_details": (
        (
            0,
            "OverallTeamPlayerOnOffDetails",
            "team_player_on_off_details:stg_on_off_details_overall:0",
            ("team_player_on_off_details:stg_team_dashboard_on_off:0",),
        ),
        (
            1,
            "PlayersOffCourtTeamPlayerOnOffDetails",
            "team_player_on_off_details:stg_on_off_details_off_court:1",
            (),
        ),
        (
            2,
            "PlayersOnCourtTeamPlayerOnOffDetails",
            "team_player_on_off_details:stg_on_off_details_on_court:2",
            (),
        ),
    ),
    "team_player_on_off_summary": (
        (
            0,
            "OverallTeamPlayerOnOffSummary",
            "team_player_on_off_summary:stg_on_off_summary_overall:0",
            ("team_player_on_off_summary:stg_on_off:0",),
        ),
        (
            1,
            "PlayersOffCourtTeamPlayerOnOffSummary",
            "team_player_on_off_summary:stg_on_off_summary_off_court:1",
            (),
        ),
        (
            2,
            "PlayersOnCourtTeamPlayerOnOffSummary",
            "team_player_on_off_summary:stg_on_off_summary_on_court:2",
            (),
        ),
    ),
}
_ON_OFF_JOURNAL_PROJECTION: Final = (
    ("endpoint", "VARCHAR", True),
    ("params", "VARCHAR", True),
    ("provider_authority_sha256", "VARCHAR", False),
    ("logical_parameters_sha256", "VARCHAR", False),
    ("result_route_ids_json", "VARCHAR", False),
    *_JOURNAL_PROJECTION,
)


class W2DatabaseAuthorityError(ValueError):
    """A database cannot prove complete, closed W2 authority."""


class _InternalAuthorityError(Exception):
    """One verifier-owned static failure safe to expose at the public boundary."""


def _fail(message: str) -> Never:
    raise _InternalAuthorityError(message) from None


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _count(value: object, *, label: str, maximum: int = MAX_W2_PUBLICATION_INPUT_ROWS) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{label} must be one exact bounded nonnegative integer")
    return value


def _canonical_bytes(value: object, *, maximum_bytes: int = _MAX_RECEIPT_BYTES) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (MemoryError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("W2 database authority evidence is not canonical JSON")
    if not encoded or len(encoded) > maximum_bytes:
        _fail("W2 database authority evidence exceeds its canonical byte bound")
    return encoded


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _inventory_sha256(kind: str, values: object) -> str:
    if type(values) not in {list, tuple}:
        _fail("W2 database inventory requires one exact built-in sequence")
    sequence = cast("list[object] | tuple[object, ...]", values)
    if len(sequence) > MAX_W2_PUBLICATION_INPUT_ROWS:
        _fail("W2 database inventory exceeds its explicit row bound")
    digest = hashlib.sha256()

    def feed(raw: bytes) -> None:
        digest.update(len(raw).to_bytes(8, byteorder="big", signed=False))
        digest.update(raw)

    feed(b"nbadb-w2-database-assurance-inventory-v1")
    feed(kind.encode("utf-8", errors="strict"))
    feed(str(len(sequence)).encode("ascii"))
    for ordinal, item in enumerate(sequence):
        feed(str(ordinal).encode("ascii"))
        feed(_canonical_bytes(item, maximum_bytes=_MAX_CANDIDATE_BYTES))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class W2DatabaseAuthorityReceiptV1:
    """Compact deterministic root over all closed W2 calls in one database."""

    receipt_sha256: str
    w2_required_logical_call_count: int
    w2_source_call_admission_inventory_sha256: str
    raw_authority_v2_bundle_count: int
    raw_authority_v2_bundle_inventory_sha256: str
    raw_authority_v2_persistence_receipt_inventory_sha256: str
    w2_publication_receipt_count: int
    w2_publication_receipt_inventory_sha256: str
    w2_exact_six_schema_inventory_sha256: str
    w2_relation_row_counts: tuple[tuple[str, int], ...]
    w2_relation_row_count: int
    w2_relation_inventory_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_w2_database_authority_receipt_v1"

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name.endswith("_sha256"):
                if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                    raise W2DatabaseAuthorityError(
                        f"{item.name} must be one exact lowercase SHA-256"
                    ) from None
            elif item.name.endswith("_count") and (
                type(value) is not int or value < 0 or value > _MAX_DATABASE_ROWS
            ):
                raise W2DatabaseAuthorityError(
                    f"{item.name} must be one exact bounded nonnegative integer"
                ) from None
        if type(self.w2_relation_row_counts) is not tuple or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not int
            or item[1] < 0
            or item[1] > _MAX_DATABASE_ROWS
            for item in self.w2_relation_row_counts
        ):
            raise W2DatabaseAuthorityError("W2 relation row-count inventory is malformed") from None
        names = tuple(item[0] for item in self.w2_relation_row_counts)
        if names != tuple(sorted(names)) or len(names) != 6 or len(names) != len(set(names)):
            raise W2DatabaseAuthorityError(
                "W2 relation row-count inventory is not the exact ordered six"
            ) from None
        if self.w2_relation_row_count != sum(item[1] for item in self.w2_relation_row_counts):
            raise W2DatabaseAuthorityError("W2 relation row-count algebra is invalid") from None
        if not (
            self.w2_required_logical_call_count
            == self.raw_authority_v2_bundle_count
            == self.w2_publication_receipt_count
        ):
            raise W2DatabaseAuthorityError(
                "W2 call, Raw bundle, and publication counts differ"
            ) from None
        if dict(self.w2_relation_row_counts).get(RAW_NBA_API_W2_OPERATION_TABLE) != (
            self.w2_publication_receipt_count
        ):
            raise W2DatabaseAuthorityError(
                "W2 operation row count differs from closed calls"
            ) from None
        if self.receipt_sha256 != _canonical_sha256(self.identity_payload()):
            raise W2DatabaseAuthorityError("W2 database receipt digest differs") from None

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: (
                    [
                        {"row_count": row_count, "table_name": table_name}
                        for table_name, row_count in self.w2_relation_row_counts
                    ]
                    if item.name == "w2_relation_row_counts"
                    else getattr(self, item.name)
                )
                for item in fields(self)
                if item.name != "receipt_sha256"
            },
        }

    def to_dict(self) -> dict[str, object]:
        return dict(
            sorted({**self.identity_payload(), "receipt_sha256": self.receipt_sha256}.items())
        )

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> W2DatabaseAuthorityReceiptV1:
        if cls is not W2DatabaseAuthorityReceiptV1 or type(value) is not dict:
            raise W2DatabaseAuthorityError(
                "W2 database receipt replay requires one exact built-in mapping"
            ) from None
        row = cast("dict[object, object]", value)
        expected = tuple(sorted(("schema_version", "kind", *(item.name for item in fields(cls)))))
        if any(type(key) is not str for key in row) or tuple(row) != expected:
            raise W2DatabaseAuthorityError(
                "W2 database receipt replay has a foreign ordered field shape"
            ) from None
        payload = cast("dict[str, object]", row)
        if payload["schema_version"] != cls.schema_version or payload["kind"] != cls.kind:
            raise W2DatabaseAuthorityError(
                "W2 database receipt replay has a foreign contract identity"
            ) from None
        relation_rows = payload["w2_relation_row_counts"]
        if type(relation_rows) is not list or len(relation_rows) != 6:
            raise W2DatabaseAuthorityError(
                "W2 database receipt replay lacks exact-six row counts"
            ) from None
        relation_counts: list[tuple[str, int]] = []
        for item in relation_rows:
            if type(item) is not dict or tuple(item) != ("row_count", "table_name"):
                raise W2DatabaseAuthorityError(
                    "W2 database receipt relation row is malformed"
                ) from None
            relation = cast("dict[str, object]", item)
            if type(relation["table_name"]) is not str or type(relation["row_count"]) is not int:
                raise W2DatabaseAuthorityError(
                    "W2 database receipt relation values are malformed"
                ) from None
            relation_counts.append((relation["table_name"], relation["row_count"]))
        values = {
            item.name: (
                tuple(relation_counts)
                if item.name == "w2_relation_row_counts"
                else payload[item.name]
            )
            for item in fields(cls)
        }
        try:
            return cls(**cast("Any", values))
        except W2DatabaseAuthorityError:
            raise
        except Exception:
            raise W2DatabaseAuthorityError("W2 database receipt replay failed") from None

    @classmethod
    def from_canonical_bytes(cls, value: object) -> W2DatabaseAuthorityReceiptV1:
        if type(value) is not bytes or not value or len(value) > _MAX_RECEIPT_BYTES:
            raise W2DatabaseAuthorityError(
                "W2 database receipt bytes are empty, foreign, or over-bound"
            ) from None

        def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in pairs:
                if key in result:
                    raise W2DatabaseAuthorityError(
                        "W2 database receipt bytes repeat one field"
                    ) from None
                result[key] = item
            return result

        def bounded_integer(token: str) -> int:
            if len(token) > 19:
                raise W2DatabaseAuthorityError(
                    "W2 database receipt bytes contain an over-bound integer"
                ) from None
            parsed = int(token)
            if parsed < 0 or parsed > _MAX_DATABASE_ROWS:
                raise W2DatabaseAuthorityError(
                    "W2 database receipt bytes contain an over-bound integer"
                ) from None
            return parsed

        def reject_number(_token: str) -> Never:
            raise W2DatabaseAuthorityError(
                "W2 database receipt bytes contain a non-integer number"
            ) from None

        try:
            decoded = json.loads(
                value.decode("utf-8", errors="strict"),
                object_pairs_hook=no_duplicate_keys,
                parse_int=bounded_integer,
                parse_float=reject_number,
                parse_constant=reject_number,
            )
        except W2DatabaseAuthorityError:
            raise
        except (json.JSONDecodeError, RecursionError, UnicodeDecodeError):
            raise W2DatabaseAuthorityError("W2 database receipt bytes are not exact JSON") from None
        try:
            canonical = _canonical_bytes(decoded)
        except _InternalAuthorityError:
            raise W2DatabaseAuthorityError(
                "W2 database receipt bytes are not canonical JSON"
            ) from None
        if canonical != value:
            raise W2DatabaseAuthorityError(
                "W2 database receipt bytes are not canonical JSON"
            ) from None
        return cls.from_dict(decoded)

    @classmethod
    def build(cls, **values: object) -> W2DatabaseAuthorityReceiptV1:
        if cls is not W2DatabaseAuthorityReceiptV1:
            raise W2DatabaseAuthorityError("W2 database receipt requires its exact DTO class")
        expected = {item.name for item in fields(cls) if item.name != "receipt_sha256"}
        if set(values) != expected or any(type(name) is not str for name in values):
            raise W2DatabaseAuthorityError("W2 database receipt fields are missing or additive")
        relation_counts = values["w2_relation_row_counts"]
        payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            **{
                name: (
                    [
                        {"row_count": row_count, "table_name": table_name}
                        for table_name, row_count in cast(
                            "tuple[tuple[str, int], ...]", relation_counts
                        )
                    ]
                    if name == "w2_relation_row_counts"
                    else value
                )
                for name, value in values.items()
            },
        }
        try:
            return cls(receipt_sha256=_canonical_sha256(payload), **cast("Any", values))
        except W2DatabaseAuthorityError:
            raise
        except Exception:
            raise W2DatabaseAuthorityError("W2 database receipt construction failed") from None


@dataclass(frozen=True, slots=True)
class W2OnOffResultOwnershipV1:
    """Fixed selector policy for one result occurrence and its sole landing owner."""

    ownership_sha256: str
    result_set_ordinal: int
    result_set_name: str
    occurrence_sha256: str
    declared_route_ids: tuple[str, ...]
    declared_route_contract_sha256s: tuple[str, ...]
    canonical_owner_route_id: str
    canonical_owner_route_contract_sha256: str
    canonical_owner_landing_sha256: str
    non_owning_alias_route_ids: tuple[str, ...]
    non_owning_alias_route_contract_sha256s: tuple[str, ...]

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_w2_on_off_result_ownership_v1"

    def __post_init__(self) -> None:
        try:
            _validate_on_off_result_ownership(self)
        except W2DatabaseAuthorityError:
            raise
        except Exception:
            raise W2DatabaseAuthorityError(
                "W2 on/off result ownership failed strict reconstruction"
            ) from None

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "canonical_owner_landing_sha256": self.canonical_owner_landing_sha256,
            "canonical_owner_route_contract_sha256": (self.canonical_owner_route_contract_sha256),
            "canonical_owner_route_id": self.canonical_owner_route_id,
            "declared_route_contract_sha256s": list(self.declared_route_contract_sha256s),
            "declared_route_ids": list(self.declared_route_ids),
            "non_owning_alias_route_contract_sha256s": list(
                self.non_owning_alias_route_contract_sha256s
            ),
            "non_owning_alias_route_ids": list(self.non_owning_alias_route_ids),
            "occurrence_sha256": self.occurrence_sha256,
            "result_set_name": self.result_set_name,
            "result_set_ordinal": self.result_set_ordinal,
        }


@dataclass(frozen=True, slots=True)
class W2OnOffSourceCallSnapshotV1:
    """One exact, database-derived on/off logical call retained for a pure compiler."""

    source_call_sha256: str
    journal_table_name: str
    successor_generation_sha256: str | None
    logical_endpoint_name: str
    logical_parameters_json: str
    logical_parameters_sha256: str
    shared_pair_scope_json: str
    shared_pair_scope_sha256: str
    provider_authority_sha256: str
    declared_result_route_ids: tuple[str, ...]
    declared_result_route_count: int
    declared_result_route_inventory_sha256: str
    canonical_owner_route_ids: tuple[str, ...]
    canonical_owner_route_count: int
    canonical_owner_route_inventory_sha256: str
    non_owning_alias_route_ids: tuple[str, ...]
    non_owning_alias_route_count: int
    non_owning_alias_route_inventory_sha256: str
    result_ownerships: tuple[W2OnOffResultOwnershipV1, ...]
    logical_call_receipt_sha256: str
    admission: W2SourceCallAdmissionV1
    raw_authority_bundle: RawRequestAuthorityBundleV2
    result_cells: tuple[RawNbaApiResultCellV2, ...]
    result_cell_count: int
    result_cell_inventory_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_w2_on_off_source_call_snapshot_v1"

    def __post_init__(self) -> None:
        try:
            _validate_on_off_source_call_snapshot(self)
        except W2DatabaseAuthorityError:
            raise
        except Exception:
            raise W2DatabaseAuthorityError(
                "W2 on/off source-call snapshot failed strict reconstruction"
            ) from None

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "admission_sha256": self.admission.admission_sha256,
            "journal_table_name": self.journal_table_name,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "logical_endpoint_name": self.logical_endpoint_name,
            "logical_parameters_json": self.logical_parameters_json,
            "logical_parameters_sha256": self.logical_parameters_sha256,
            "shared_pair_scope_json": self.shared_pair_scope_json,
            "shared_pair_scope_sha256": self.shared_pair_scope_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "raw_authority_bundle_sha256": self.raw_authority_bundle.bundle_sha256,
            "declared_result_route_count": self.declared_result_route_count,
            "declared_result_route_inventory_sha256": (self.declared_result_route_inventory_sha256),
            "declared_result_route_ids": list(self.declared_result_route_ids),
            "canonical_owner_route_count": self.canonical_owner_route_count,
            "canonical_owner_route_inventory_sha256": (self.canonical_owner_route_inventory_sha256),
            "canonical_owner_route_ids": list(self.canonical_owner_route_ids),
            "non_owning_alias_route_count": self.non_owning_alias_route_count,
            "non_owning_alias_route_inventory_sha256": (
                self.non_owning_alias_route_inventory_sha256
            ),
            "non_owning_alias_route_ids": list(self.non_owning_alias_route_ids),
            "result_ownership_sha256s": [item.ownership_sha256 for item in self.result_ownerships],
            "result_cell_count": self.result_cell_count,
            "result_cell_inventory_sha256": self.result_cell_inventory_sha256,
            "successor_generation_sha256": self.successor_generation_sha256,
        }


@dataclass(frozen=True, slots=True)
class W2OnOffPairSnapshotV1:
    """One exact details/summary pair in one current journal generation."""

    pair_sha256: str
    shared_pair_scope_json: str
    shared_pair_scope_sha256: str
    journal_table_name: str
    successor_generation_sha256: str | None
    provider_authority_sha256: str
    details_source_call_sha256: str
    summary_source_call_sha256: str
    declared_result_route_count: int
    declared_result_route_inventory_sha256: str
    canonical_owner_route_count: int
    canonical_owner_route_inventory_sha256: str
    non_owning_alias_route_count: int
    non_owning_alias_route_inventory_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_w2_on_off_pair_snapshot_v1"

    def __post_init__(self) -> None:
        try:
            _validate_on_off_pair_snapshot(self)
        except W2DatabaseAuthorityError:
            raise
        except Exception:
            raise W2DatabaseAuthorityError(
                "W2 on/off pair snapshot failed strict reconstruction"
            ) from None

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "pair_sha256"
            },
        }


@dataclass(frozen=True, slots=True)
class W2OnOffDatabaseSnapshotV1:
    """Immutable fixed-selector view over every admitted on/off W2 source call."""

    snapshot_sha256: str
    selector_kind: str
    database_authority: W2DatabaseAuthorityReceiptV1
    database_generation_sha256: str
    selected_pair_count: int
    selected_pair_inventory_sha256: str
    selected_logical_call_count: int
    selected_logical_call_inventory_sha256: str
    selected_observation_count: int
    selected_observation_inventory_sha256: str
    selected_occurrence_count: int
    selected_occurrence_inventory_sha256: str
    selected_result_cell_count: int
    selected_result_cell_inventory_sha256: str
    pairs: tuple[W2OnOffPairSnapshotV1, ...]
    source_calls: tuple[W2OnOffSourceCallSnapshotV1, ...]

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_w2_on_off_database_snapshot_v1"

    def __post_init__(self) -> None:
        try:
            _validate_on_off_database_snapshot(self)
        except W2DatabaseAuthorityError:
            raise
        except Exception:
            raise W2DatabaseAuthorityError(
                "W2 on/off database snapshot failed strict reconstruction"
            ) from None

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "database_authority_receipt_sha256": self.database_authority.receipt_sha256,
            "database_generation_sha256": self.database_generation_sha256,
            "selected_pair_count": self.selected_pair_count,
            "selected_pair_inventory_sha256": self.selected_pair_inventory_sha256,
            "selected_logical_call_count": self.selected_logical_call_count,
            "selected_logical_call_inventory_sha256": (self.selected_logical_call_inventory_sha256),
            "selected_observation_count": self.selected_observation_count,
            "selected_observation_inventory_sha256": (self.selected_observation_inventory_sha256),
            "selected_occurrence_count": self.selected_occurrence_count,
            "selected_occurrence_inventory_sha256": (self.selected_occurrence_inventory_sha256),
            "selected_result_cell_count": self.selected_result_cell_count,
            "selected_result_cell_inventory_sha256": (self.selected_result_cell_inventory_sha256),
            "selector_kind": self.selector_kind,
            "pair_sha256s": [item.pair_sha256 for item in self.pairs],
            "source_call_sha256s": [item.source_call_sha256 for item in self.source_calls],
        }


def _dto_error(message: str) -> Never:
    raise W2DatabaseAuthorityError(message) from None


def _dto_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _dto_error(f"{label} must be one exact lowercase SHA-256")
    return value


def _dto_count(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0 or value > MAX_W2_PUBLICATION_INPUT_ROWS:
        _dto_error(f"{label} must be one exact bounded nonnegative integer")
    return value


def _validate_route_id_tuple(value: object, *, label: str, allow_empty: bool) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or (not value and not allow_empty)
        or value != tuple(sorted(set(value)))
        or any(type(item) is not str or not item for item in value)
    ):
        _dto_error(f"{label} is not one exact canonical route-ID tuple")
    return cast("tuple[str, ...]", value)


def _validate_sha256_tuple(
    value: object,
    *,
    label: str,
    expected_count: int,
) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) != expected_count:
        _dto_error(f"{label} does not match its route inventory")
    result = value
    for item in result:
        _dto_sha256(item, label=label)
    return cast("tuple[str, ...]", result)


def _validate_on_off_result_ownership(value: W2OnOffResultOwnershipV1) -> None:
    _dto_sha256(value.ownership_sha256, label="result ownership")
    if type(value.result_set_ordinal) is not int or value.result_set_ordinal not in {0, 1, 2}:
        _dto_error("result ownership ordinal is outside the exact on/off denominator")
    if type(value.result_set_name) is not str or not value.result_set_name:
        _dto_error("result ownership name is empty or foreign")
    _dto_sha256(value.occurrence_sha256, label="result ownership occurrence")
    declared_ids = _validate_route_id_tuple(
        value.declared_route_ids,
        label="declared result-route inventory",
        allow_empty=False,
    )
    _validate_sha256_tuple(
        value.declared_route_contract_sha256s,
        label="declared route contract",
        expected_count=len(declared_ids),
    )
    if (
        type(value.canonical_owner_route_id) is not str
        or value.canonical_owner_route_id not in declared_ids
    ):
        _dto_error("result ownership canonical owner is not declared")
    _dto_sha256(
        value.canonical_owner_route_contract_sha256,
        label="canonical owner route contract",
    )
    _dto_sha256(value.canonical_owner_landing_sha256, label="canonical owner landing")
    aliases = _validate_route_id_tuple(
        value.non_owning_alias_route_ids,
        label="non-owning alias inventory",
        allow_empty=True,
    )
    _validate_sha256_tuple(
        value.non_owning_alias_route_contract_sha256s,
        label="non-owning alias route contract",
        expected_count=len(aliases),
    )
    if aliases != tuple(item for item in declared_ids if item != value.canonical_owner_route_id):
        _dto_error("result ownership aliases differ from declared non-owners")
    if value.ownership_sha256 != _canonical_sha256(value.identity_payload()):
        _dto_error("result ownership digest differs from its exact identity")


def _shared_pair_scope(parameters: dict[str, Any]) -> tuple[str, str]:
    if tuple(parameters) != _W2_ON_OFF_SHARED_SCOPE_FIELDS:
        _dto_error("on/off parameters differ from the exact shared-pair field partition")
    scope_payload = {name: parameters[name] for name in _W2_ON_OFF_SHARED_SCOPE_FIELDS}
    scope_json = _canonical_bytes(scope_payload).decode("utf-8", errors="strict")
    return (
        scope_json,
        _canonical_sha256(
            {
                "schema_version": 1,
                "kind": "nbadb_w2_on_off_shared_pair_scope_v1",
                "parameters": scope_payload,
            }
        ),
    )


def _fixed_on_off_route_contracts(endpoint_name: str) -> dict[str, Any]:
    layout = _W2_ON_OFF_ROUTE_LAYOUT.get(endpoint_name)
    if layout is None:
        _dto_error("on/off route authority received a foreign endpoint")
    route_bundle = staging_route_contract_bundle()
    runtime_by_id = pinned_runtime_contracts()
    try:
        details_runtime = runtime_by_id["TeamPlayerOnOffDetails"]
        summary_runtime = runtime_by_id["TeamPlayerOnOffSummary"]
    except KeyError:
        _dto_error("on/off pinned runtime contract is missing")
    if (
        details_runtime.parameters != _W2_ON_OFF_RUNTIME_PARAMETER_DOMAIN
        or summary_runtime.parameters != _W2_ON_OFF_RUNTIME_PARAMETER_DOMAIN
        or details_runtime.required_parameters != ("team_id",)
        or summary_runtime.required_parameters != ("team_id",)
        or details_runtime.nullable_parameters != summary_runtime.nullable_parameters
        or details_runtime.parameter_defaults != summary_runtime.parameter_defaults
        or details_runtime.parameter_query_names != summary_runtime.parameter_query_names
    ):
        _dto_error("on/off pinned runtimes differ from the exact shared 21-field domain")
    routes = tuple(item for item in route_bundle.routes if item.endpoint_name == endpoint_name)
    expected_ids = {
        route_id for _ordinal, _name, owner, aliases in layout for route_id in (owner, *aliases)
    }
    by_id = {item.route_id: item for item in routes}
    if len(routes) != 4 or set(by_id) != expected_ids:
        _dto_error("on/off declared route registry differs from the exact four")
    expected_provider = _W2_ON_OFF_PROVIDER_BY_LOGICAL[endpoint_name]
    for ordinal, result_name, owner, aliases in layout:
        for route_id in (owner, *aliases):
            route = by_id[route_id]
            parameter_names = tuple(
                sorted((*route.provider_required_parameters, *route.provider_optional_parameters))
            )
            if (
                route.provider_endpoint_id != expected_provider
                or route.canonical_result_set_ordinal != ordinal
                or route.canonical_result_set_name != result_name
                or parameter_names != _W2_ON_OFF_SHARED_SCOPE_FIELDS
                or route.provider_authority_sha256 != route_bundle.provider_authority_sha256
            ):
                _dto_error("on/off declared route differs from its fixed selector authority")
    return by_id


def _ownership_route_rows(
    ownerships: tuple[W2OnOffResultOwnershipV1, ...],
    *,
    role: str,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for ownership in ownerships:
        if role == "declared":
            route_ids = ownership.declared_route_ids
            contract_sha256s = ownership.declared_route_contract_sha256s
        elif role == "canonical_owner":
            route_ids = (ownership.canonical_owner_route_id,)
            contract_sha256s = (ownership.canonical_owner_route_contract_sha256,)
        elif role == "non_owning_alias":
            route_ids = ownership.non_owning_alias_route_ids
            contract_sha256s = ownership.non_owning_alias_route_contract_sha256s
        else:
            _dto_error("on/off ownership route role is foreign")
        rows.extend(
            {
                "result_set_ordinal": ownership.result_set_ordinal,
                "route_contract_sha256": contract_sha256,
                "route_id": route_id,
                "route_role": role,
            }
            for route_id, contract_sha256 in zip(route_ids, contract_sha256s, strict=True)
        )
    return tuple(sorted(rows, key=lambda item: cast("str", item["route_id"])))


def _route_inventory_sha256(
    ownerships: tuple[W2OnOffResultOwnershipV1, ...],
    *,
    role: str,
) -> str:
    return _inventory_sha256(
        f"nbadb_w2_on_off_{role}_route_inventory_v1",
        list(_ownership_route_rows(ownerships, role=role)),
    )


def _validate_on_off_pair_snapshot(value: W2OnOffPairSnapshotV1) -> None:
    _dto_sha256(value.pair_sha256, label="on/off pair")
    decoded = _decode_logical_parameters_json(value.shared_pair_scope_json)
    scope_json, scope_sha256 = _shared_pair_scope(decoded)
    if value.shared_pair_scope_json != scope_json or value.shared_pair_scope_sha256 != scope_sha256:
        _dto_error("on/off pair differs from its fixed shared scope")
    if value.journal_table_name not in _JOURNAL_TABLES:
        _dto_error("on/off pair has a foreign journal table")
    if value.journal_table_name == _JOURNAL_TABLES[0]:
        if value.successor_generation_sha256 is not None:
            _dto_error("baseline on/off pair carries a successor generation")
    else:
        _dto_sha256(value.successor_generation_sha256, label="on/off pair successor generation")
    for digest, label in (
        (value.provider_authority_sha256, "on/off pair provider authority"),
        (value.details_source_call_sha256, "on/off pair details source"),
        (value.summary_source_call_sha256, "on/off pair summary source"),
        (value.declared_result_route_inventory_sha256, "on/off pair declared routes"),
        (value.canonical_owner_route_inventory_sha256, "on/off pair owner routes"),
        (value.non_owning_alias_route_inventory_sha256, "on/off pair aliases"),
    ):
        _dto_sha256(digest, label=label)
    if (
        value.details_source_call_sha256 == value.summary_source_call_sha256
        or value.declared_result_route_count != 8
        or value.canonical_owner_route_count != 6
        or value.non_owning_alias_route_count != 2
    ):
        _dto_error("on/off pair does not bind exact 8/6/2 route algebra")
    if value.pair_sha256 != _canonical_sha256(value.identity_payload()):
        _dto_error("on/off pair digest differs from its exact identity")


def _source_call_sort_key(
    value: W2OnOffSourceCallSnapshotV1,
) -> tuple[str, str, str, str]:
    return (
        value.shared_pair_scope_sha256,
        value.logical_endpoint_name,
        value.logical_call_receipt_sha256,
        value.journal_table_name,
    )


def _selected_observation_rows(
    source_calls: tuple[W2OnOffSourceCallSnapshotV1, ...],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = [
        {
            "logical_call_receipt_sha256": call.logical_call_receipt_sha256,
            "observation_record_sha256": observation.observation_record_sha256,
            "observation_sha256": observation.attempt.observation_sha256,
            "raw_authority_bundle_sha256": call.raw_authority_bundle.bundle_sha256,
        }
        for call in source_calls
        for observation in call.raw_authority_bundle.observations
        if observation.lifecycle == "selected_terminal"
    ]
    rows.sort(key=lambda item: cast("str", item["observation_sha256"]))
    return tuple(rows)


def _selected_occurrence_rows(
    source_calls: tuple[W2OnOffSourceCallSnapshotV1, ...],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for call in source_calls:
        selected_ids = {
            item.attempt.observation_sha256
            for item in call.raw_authority_bundle.observations
            if item.lifecycle == "selected_terminal"
        }
        rows.extend(
            {
                "observation_sha256": occurrence.observation_sha256,
                "occurrence_sha256": occurrence.occurrence_sha256,
                "output_sha256": occurrence.output_sha256,
                "raw_authority_bundle_sha256": call.raw_authority_bundle.bundle_sha256,
            }
            for occurrence in call.raw_authority_bundle.occurrences
            if occurrence.observation_sha256 in selected_ids
        )
    return tuple(sorted(rows, key=lambda item: cast("str", item["occurrence_sha256"])))


def _selected_result_cell_rows(
    source_calls: tuple[W2OnOffSourceCallSnapshotV1, ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        sorted(
            (cell.to_row() for call in source_calls for cell in call.result_cells),
            key=lambda item: cast("str", item["cell_sha256"]),
        )
    )


def _result_ownership_identity_payload(
    *,
    result_set_ordinal: int,
    result_set_name: str,
    occurrence_sha256: str,
    declared_route_ids: tuple[str, ...],
    declared_route_contract_sha256s: tuple[str, ...],
    canonical_owner_route_id: str,
    canonical_owner_route_contract_sha256: str,
    canonical_owner_landing_sha256: str,
    non_owning_alias_route_ids: tuple[str, ...],
    non_owning_alias_route_contract_sha256s: tuple[str, ...],
) -> dict[str, object]:
    return {
        "schema_version": W2OnOffResultOwnershipV1.schema_version,
        "kind": W2OnOffResultOwnershipV1.kind,
        "canonical_owner_landing_sha256": canonical_owner_landing_sha256,
        "canonical_owner_route_contract_sha256": canonical_owner_route_contract_sha256,
        "canonical_owner_route_id": canonical_owner_route_id,
        "declared_route_contract_sha256s": list(declared_route_contract_sha256s),
        "declared_route_ids": list(declared_route_ids),
        "non_owning_alias_route_contract_sha256s": list(non_owning_alias_route_contract_sha256s),
        "non_owning_alias_route_ids": list(non_owning_alias_route_ids),
        "occurrence_sha256": occurrence_sha256,
        "result_set_name": result_set_name,
        "result_set_ordinal": result_set_ordinal,
    }


def _build_on_off_result_ownerships(
    *,
    endpoint_name: str,
    bundle: RawRequestAuthorityBundleV2,
) -> tuple[W2OnOffResultOwnershipV1, ...]:
    route_by_id = _fixed_on_off_route_contracts(endpoint_name)
    selected = tuple(item for item in bundle.observations if item.lifecycle == "selected_terminal")
    if len(selected) != 1:
        _dto_error("on/off source call requires exactly one selected Raw observation")
    observation_sha256 = selected[0].attempt.observation_sha256
    occurrences = tuple(
        item for item in bundle.occurrences if item.observation_sha256 == observation_sha256
    )
    landings = tuple(
        item for item in bundle.landings if item.observation_sha256 == observation_sha256
    )
    occurrence_by_ordinal = {item.canonical_result_ordinal: item for item in occurrences}
    landing_by_route = {item.route_id: item for item in landings}
    if (
        len(occurrences) != 3
        or len(occurrence_by_ordinal) != 3
        or set(occurrence_by_ordinal) != {0, 1, 2}
        or len(landings) != 3
        or len(landing_by_route) != 3
    ):
        _dto_error("on/off Raw bundle differs from the exact three occurrence owners")

    ownerships: list[W2OnOffResultOwnershipV1] = []
    layout = _W2_ON_OFF_ROUTE_LAYOUT[endpoint_name]
    expected_owner_ids = {item[2] for item in layout}
    if set(landing_by_route) != expected_owner_ids:
        _dto_error("on/off Raw landings contain a missing owner, alias owner, or fallback")
    for ordinal, result_name, owner_route_id, alias_route_ids in layout:
        occurrence = occurrence_by_ordinal[ordinal]
        landing = landing_by_route[owner_route_id]
        declared_route_ids = tuple(sorted((owner_route_id, *alias_route_ids)))
        non_owning_alias_route_ids = tuple(sorted(alias_route_ids))
        declared_route_contract_sha256s = tuple(
            route_by_id[route_id].contract_sha256 for route_id in declared_route_ids
        )
        non_owning_alias_route_contract_sha256s = tuple(
            route_by_id[route_id].contract_sha256 for route_id in non_owning_alias_route_ids
        )
        try:
            committed_receipts = json.loads(occurrence.committed_staging_receipts_json)
        except (json.JSONDecodeError, MemoryError, RecursionError):
            _dto_error("on/off occurrence staging receipts are not exact JSON")
        if (
            occurrence.occurrence_ordinal != ordinal
            or occurrence.result_name != result_name
            or occurrence.canonical_route_ids() != (owner_route_id,)
            or type(committed_receipts) is not list
            or len(committed_receipts) != 1
            or type(committed_receipts[0]) is not dict
            or committed_receipts[0].get("route_id") != owner_route_id
            or landing.source_occurrence_count != 1
        ):
            _dto_error("on/off occurrence or landing differs from its fixed sole owner")
        values = {
            "result_set_ordinal": ordinal,
            "result_set_name": result_name,
            "occurrence_sha256": occurrence.occurrence_sha256,
            "declared_route_ids": declared_route_ids,
            "declared_route_contract_sha256s": declared_route_contract_sha256s,
            "canonical_owner_route_id": owner_route_id,
            "canonical_owner_route_contract_sha256": route_by_id[owner_route_id].contract_sha256,
            "canonical_owner_landing_sha256": landing.landing_sha256,
            "non_owning_alias_route_ids": non_owning_alias_route_ids,
            "non_owning_alias_route_contract_sha256s": (non_owning_alias_route_contract_sha256s),
        }
        identity = _result_ownership_identity_payload(**values)
        ownerships.append(
            W2OnOffResultOwnershipV1(
                ownership_sha256=_canonical_sha256(identity),
                **values,
            )
        )
    return tuple(ownerships)


def _validate_on_off_source_call_snapshot(value: W2OnOffSourceCallSnapshotV1) -> None:
    _dto_sha256(value.source_call_sha256, label="source-call snapshot digest")
    if value.journal_table_name not in _JOURNAL_TABLES:
        _dto_error("source-call snapshot has a foreign journal table")
    if value.journal_table_name == _JOURNAL_TABLES[0]:
        if value.successor_generation_sha256 is not None:
            _dto_error("baseline source-call snapshot carries a successor generation")
    else:
        _dto_sha256(value.successor_generation_sha256, label="successor generation")
    if value.logical_endpoint_name not in _W2_ON_OFF_PROVIDER_BY_LOGICAL:
        _dto_error("source-call snapshot has a foreign fixed-selector endpoint")
    decoded_parameters = _decode_logical_parameters_json(value.logical_parameters_json)
    if canonical_parameters_sha256(decoded_parameters) != value.logical_parameters_sha256:
        _dto_error("source-call snapshot parameter digest differs from canonical parameters")
    shared_scope_json, shared_scope_sha256 = _shared_pair_scope(decoded_parameters)
    if (
        value.shared_pair_scope_json != shared_scope_json
        or value.shared_pair_scope_sha256 != shared_scope_sha256
    ):
        _dto_error("source-call snapshot differs from its fixed shared-pair scope")
    _dto_sha256(value.logical_parameters_sha256, label="logical parameter digest")
    _dto_sha256(value.provider_authority_sha256, label="provider authority")
    _dto_sha256(value.logical_call_receipt_sha256, label="logical call receipt")
    declared_ids = _validate_route_id_tuple(
        value.declared_result_route_ids,
        label="source-call declared routes",
        allow_empty=False,
    )
    owner_ids = _validate_route_id_tuple(
        value.canonical_owner_route_ids,
        label="source-call owner routes",
        allow_empty=False,
    )
    alias_ids = _validate_route_id_tuple(
        value.non_owning_alias_route_ids,
        label="source-call non-owning aliases",
        allow_empty=False,
    )
    if any(not route_id.startswith(f"{value.logical_endpoint_name}:") for route_id in declared_ids):
        _dto_error("source-call snapshot route inventory crosses endpoint wrappers")
    if (
        value.declared_result_route_count != 4
        or value.canonical_owner_route_count != 3
        or value.non_owning_alias_route_count != 1
        or len(declared_ids) != 4
        or len(owner_ids) != 3
        or len(alias_ids) != 1
        or set(owner_ids) | set(alias_ids) != set(declared_ids)
        or set(owner_ids) & set(alias_ids)
    ):
        _dto_error("source-call snapshot does not bind exact 4/3/1 route algebra")
    for count, label in (
        (value.declared_result_route_count, "source-call declared route count"),
        (value.canonical_owner_route_count, "source-call owner route count"),
        (value.non_owning_alias_route_count, "source-call alias route count"),
    ):
        _dto_count(count, label=label)
    if type(value.result_ownerships) is not tuple or any(
        type(item) is not W2OnOffResultOwnershipV1 for item in value.result_ownerships
    ):
        _dto_error("source-call snapshot lacks exact typed result ownerships")
    if tuple(item.result_set_ordinal for item in value.result_ownerships) != (0, 1, 2):
        _dto_error("source-call result ownerships are not exact ordered three")
    route_roots = (
        (
            value.declared_result_route_inventory_sha256,
            _route_inventory_sha256(value.result_ownerships, role="declared"),
        ),
        (
            value.canonical_owner_route_inventory_sha256,
            _route_inventory_sha256(value.result_ownerships, role="canonical_owner"),
        ),
        (
            value.non_owning_alias_route_inventory_sha256,
            _route_inventory_sha256(value.result_ownerships, role="non_owning_alias"),
        ),
    )
    if any(observed != expected for observed, expected in route_roots):
        _dto_error("source-call route inventory root differs from exact ownerships")
    if (
        declared_ids
        != tuple(
            sorted(
                route_id for item in value.result_ownerships for route_id in item.declared_route_ids
            )
        )
        or owner_ids
        != tuple(sorted(item.canonical_owner_route_id for item in value.result_ownerships))
        or alias_ids
        != tuple(
            sorted(
                route_id
                for item in value.result_ownerships
                for route_id in item.non_owning_alias_route_ids
            )
        )
    ):
        _dto_error("source-call flattened route inventories differ from ownerships")
    if type(value.admission) is not W2SourceCallAdmissionV1:
        _dto_error("source-call snapshot admission lacks its exact typed contract")
    if type(value.raw_authority_bundle) is not RawRequestAuthorityBundleV2:
        _dto_error("source-call snapshot Raw bundle lacks its exact typed contract")
    if type(value.result_cells) is not tuple or any(
        type(item) is not RawNbaApiResultCellV2 for item in value.result_cells
    ):
        _dto_error("source-call snapshot result cells lack exact typed contracts")
    if value.result_cells != tuple(sorted(value.result_cells, key=lambda item: item.cell_sha256)):
        _dto_error("source-call snapshot result-cell inventory is not canonical")
    _dto_count(value.result_cell_count, label="source-call result-cell count")
    if value.result_cell_count != len(value.result_cells):
        _dto_error("source-call snapshot result-cell count differs")
    expected_cell_root = _inventory_sha256(
        "nbadb_w2_on_off_source_call_result_cells_v1",
        [item.to_row() for item in value.result_cells],
    )
    if value.result_cell_inventory_sha256 != expected_cell_root:
        _dto_error("source-call snapshot result-cell inventory root differs")
    admission = value.admission
    bundle = value.raw_authority_bundle
    if (
        admission.logical_call_receipt_sha256 != value.logical_call_receipt_sha256
        or admission.raw_authority_bundle_sha256 != bundle.bundle_sha256
        or admission.operation.result_cell_row_count != value.result_cell_count
    ):
        _dto_error("source-call snapshot crosses its admission or Raw bundle")
    selected = tuple(item for item in bundle.observations if item.lifecycle == "selected_terminal")
    selected_ids = {item.attempt.observation_sha256 for item in selected}
    expected_provider_endpoint = _W2_ON_OFF_PROVIDER_BY_LOGICAL[value.logical_endpoint_name]
    bundle_routes = tuple(
        sorted(item.route_id for item in bundle.landings if item.observation_sha256 in selected_ids)
    )
    if (
        len(selected) != 1
        or bundle_routes != value.canonical_owner_route_ids
        or any(
            item.logical_receipt_sha256 != value.logical_call_receipt_sha256
            or item.attempt.endpoint_id != expected_provider_endpoint
            or item.attempt.provider_authority_sha256 != value.provider_authority_sha256
            for item in selected
        )
    ):
        _dto_error("source-call snapshot differs from selected Raw observations")
    try:
        for observation in selected:
            validate_logical_provider_parameter_join(
                observation,
                logical_endpoint_name=value.logical_endpoint_name,
                logical_parameters_sha256=value.logical_parameters_sha256,
                result_route_ids=value.canonical_owner_route_ids,
            )
    except Exception:
        _dto_error("source-call snapshot failed its logical/provider parameter join")
    occurrence_ids = {
        item.occurrence_sha256
        for item in bundle.occurrences
        if item.observation_sha256 in selected_ids
    }
    if any(
        item.observation_sha256 not in selected_ids or item.occurrence_sha256 not in occurrence_ids
        for item in value.result_cells
    ):
        _dto_error("source-call snapshot contains a foreign result cell")
    expected_ownerships = _build_on_off_result_ownerships(
        endpoint_name=value.logical_endpoint_name,
        bundle=bundle,
    )
    if expected_ownerships != value.result_ownerships:
        _dto_error("source-call ownerships differ from Raw occurrences and fixed route policy")
    if value.source_call_sha256 != _canonical_sha256(value.identity_payload()):
        _dto_error("source-call snapshot digest differs from its exact identity")


def _pair_route_inventory_sha256(
    calls: tuple[W2OnOffSourceCallSnapshotV1, W2OnOffSourceCallSnapshotV1],
    *,
    role: str,
) -> str:
    rows = [
        {
            **row,
            "logical_endpoint_name": call.logical_endpoint_name,
            "source_call_sha256": call.source_call_sha256,
        }
        for call in calls
        for row in _ownership_route_rows(call.result_ownerships, role=role)
    ]
    rows.sort(
        key=lambda item: (
            cast("str", item["logical_endpoint_name"]),
            cast("str", item["route_id"]),
        )
    )
    return _inventory_sha256(
        f"nbadb_w2_on_off_pair_{role}_route_inventory_v1",
        rows,
    )


def _build_on_off_pairs(
    source_calls: tuple[W2OnOffSourceCallSnapshotV1, ...],
) -> tuple[W2OnOffPairSnapshotV1, ...]:
    calls_by_scope: dict[str, list[W2OnOffSourceCallSnapshotV1]] = {}
    for call in source_calls:
        calls_by_scope.setdefault(call.shared_pair_scope_sha256, []).append(call)
    pairs: list[W2OnOffPairSnapshotV1] = []
    expected_endpoints = tuple(item[0] for item in _W2_ON_OFF_ENDPOINTS)
    for scope_sha256, raw_calls in sorted(calls_by_scope.items()):
        calls = tuple(sorted(raw_calls, key=lambda item: item.logical_endpoint_name))
        if (
            len(calls) != 2
            or tuple(item.logical_endpoint_name for item in calls) != expected_endpoints
            or len({item.shared_pair_scope_json for item in calls}) != 1
            or len({item.provider_authority_sha256 for item in calls}) != 1
            or len({item.journal_table_name for item in calls}) != 1
            or len({item.successor_generation_sha256 for item in calls}) != 1
        ):
            _dto_error("on/off current-generation denominator lacks one exact details/summary pair")
        details, summary = calls
        route_calls = (details, summary)
        values: dict[str, object] = {
            "shared_pair_scope_json": details.shared_pair_scope_json,
            "shared_pair_scope_sha256": scope_sha256,
            "journal_table_name": details.journal_table_name,
            "successor_generation_sha256": details.successor_generation_sha256,
            "provider_authority_sha256": details.provider_authority_sha256,
            "details_source_call_sha256": details.source_call_sha256,
            "summary_source_call_sha256": summary.source_call_sha256,
            "declared_result_route_count": sum(item.declared_result_route_count for item in calls),
            "declared_result_route_inventory_sha256": _pair_route_inventory_sha256(
                route_calls,
                role="declared",
            ),
            "canonical_owner_route_count": sum(item.canonical_owner_route_count for item in calls),
            "canonical_owner_route_inventory_sha256": _pair_route_inventory_sha256(
                route_calls,
                role="canonical_owner",
            ),
            "non_owning_alias_route_count": sum(
                item.non_owning_alias_route_count for item in calls
            ),
            "non_owning_alias_route_inventory_sha256": _pair_route_inventory_sha256(
                route_calls,
                role="non_owning_alias",
            ),
        }
        identity = {
            "schema_version": W2OnOffPairSnapshotV1.schema_version,
            "kind": W2OnOffPairSnapshotV1.kind,
            **values,
        }
        pairs.append(
            W2OnOffPairSnapshotV1(
                pair_sha256=_canonical_sha256(identity),
                **cast("Any", values),
            )
        )
    return tuple(pairs)


def _on_off_database_generation_sha256(
    *,
    database_authority: W2DatabaseAuthorityReceiptV1,
    source_calls: tuple[W2OnOffSourceCallSnapshotV1, ...],
    pairs: tuple[W2OnOffPairSnapshotV1, ...],
) -> str:
    return _canonical_sha256(
        {
            "schema_version": 1,
            "kind": "nbadb_w2_on_off_database_generation_v1",
            "database_authority_receipt_sha256": database_authority.receipt_sha256,
            "pair_sha256s": [item.pair_sha256 for item in pairs],
            "source_call_sha256s": [item.source_call_sha256 for item in source_calls],
            "successor_generation_sha256s": sorted(
                {
                    item.successor_generation_sha256
                    for item in source_calls
                    if item.successor_generation_sha256 is not None
                }
            ),
        }
    )


def _validate_on_off_database_snapshot(value: W2OnOffDatabaseSnapshotV1) -> None:
    _dto_sha256(value.snapshot_sha256, label="on/off database snapshot digest")
    if value.selector_kind != W2_ON_OFF_SELECTOR_KIND:
        _dto_error("on/off database snapshot has a foreign selector")
    if type(value.database_authority) is not W2DatabaseAuthorityReceiptV1:
        _dto_error("on/off database snapshot lacks typed global W2 authority")
    _dto_sha256(value.database_generation_sha256, label="on/off database generation")
    if (
        type(value.source_calls) is not tuple
        or not value.source_calls
        or any(type(item) is not W2OnOffSourceCallSnapshotV1 for item in value.source_calls)
    ):
        _dto_error("on/off database snapshot requires exact nonempty source calls")
    if value.source_calls != tuple(sorted(value.source_calls, key=_source_call_sort_key)):
        _dto_error("on/off database source-call inventory is not canonical")
    source_ids = tuple(item.source_call_sha256 for item in value.source_calls)
    if len(source_ids) != len(set(source_ids)):
        _dto_error("on/off database source-call inventory contains duplicates")
    selector_keys = tuple(
        (item.logical_endpoint_name, item.logical_parameters_sha256) for item in value.source_calls
    )
    if len(selector_keys) != len(set(selector_keys)):
        _dto_error("on/off database source calls overlap journals or generations")
    if (
        type(value.pairs) is not tuple
        or not value.pairs
        or any(type(item) is not W2OnOffPairSnapshotV1 for item in value.pairs)
    ):
        _dto_error("on/off database snapshot lacks exact typed pairs")
    expected_pairs = _build_on_off_pairs(value.source_calls)
    if value.pairs != expected_pairs:
        _dto_error("on/off database pairs differ from the exact source-call partition")
    if value.database_generation_sha256 != _on_off_database_generation_sha256(
        database_authority=value.database_authority,
        source_calls=value.source_calls,
        pairs=value.pairs,
    ):
        _dto_error("on/off database generation differs from its exact authorities")
    observation_rows = _selected_observation_rows(value.source_calls)
    occurrence_rows = _selected_occurrence_rows(value.source_calls)
    result_cell_rows = _selected_result_cell_rows(value.source_calls)
    inventories = (
        (
            value.selected_pair_count,
            value.selected_pair_inventory_sha256,
            value.pairs,
            "nbadb_w2_on_off_selected_pairs_v1",
            [item.identity_payload() for item in value.pairs],
        ),
        (
            value.selected_logical_call_count,
            value.selected_logical_call_inventory_sha256,
            value.source_calls,
            "nbadb_w2_on_off_selected_logical_calls_v1",
            [item.identity_payload() for item in value.source_calls],
        ),
        (
            value.selected_observation_count,
            value.selected_observation_inventory_sha256,
            observation_rows,
            "nbadb_w2_on_off_selected_observations_v1",
            list(observation_rows),
        ),
        (
            value.selected_occurrence_count,
            value.selected_occurrence_inventory_sha256,
            occurrence_rows,
            "nbadb_w2_on_off_selected_occurrences_v1",
            list(occurrence_rows),
        ),
        (
            value.selected_result_cell_count,
            value.selected_result_cell_inventory_sha256,
            result_cell_rows,
            "nbadb_w2_on_off_selected_result_cells_v1",
            list(result_cell_rows),
        ),
    )
    for count, root, sequence, kind, payloads in inventories:
        _dto_count(count, label=kind)
        if count != len(sequence) or root != _inventory_sha256(kind, payloads):
            _dto_error("on/off database snapshot count or inventory root differs")
    observation_ids = tuple(item["observation_sha256"] for item in observation_rows)
    occurrence_ids = tuple(item["occurrence_sha256"] for item in occurrence_rows)
    cell_ids = tuple(item["cell_sha256"] for item in result_cell_rows)
    if any(
        len(identities) != len(set(identities))
        for identities in (observation_ids, occurrence_ids, cell_ids)
    ):
        _dto_error("on/off database snapshot shares one nested authority identity")
    if value.snapshot_sha256 != _canonical_sha256(value.identity_payload()):
        _dto_error("on/off database snapshot digest differs from its exact identity")


@dataclass(frozen=True, slots=True)
class _CandidateRelation:
    table_name: str
    schema_sha256: str
    ordered_keys: tuple[str, ...]
    ordered_row_sha256s: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CandidateJournal:
    raw_authority_bundle_sha256: str
    plan_sha256: str
    ownership_receipt_sha256: str
    public_projection_receipt_sha256: str
    relations: tuple[_CandidateRelation, ...]


def _sql_type(dtype: pl.DataType) -> str:
    if dtype == pl.Int64:
        return "BIGINT"
    if dtype == pl.String:
        return "VARCHAR"
    _fail("W2 public relation contains an unsupported database type")


def _table_names(connection: duckdb.DuckDBPyConnection) -> frozenset[str]:
    rows = connection.execute(
        """
        SELECT table_name
        FROM duckdb_tables()
        WHERE database_name = current_database()
          AND schema_name = current_schema()
          AND NOT internal
          AND NOT temporary
        ORDER BY table_name
        """
    ).fetchall()
    if len(rows) > MAX_W2_PUBLICATION_INPUT_ROWS or any(
        len(row) != 1 or type(row[0]) is not str for row in rows
    ):
        _fail("W2 database table inventory is malformed or over-bound")
    return frozenset(cast("str", row[0]) for row in rows)


def _require_projection_schema(
    connection: duckdb.DuckDBPyConnection,
    *,
    table_name: str,
    projection: tuple[tuple[str, str, bool], ...],
) -> None:
    rows = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    by_name = {str(row[1]): (str(row[2]).upper(), bool(row[3])) for row in rows if len(row) >= 4}
    if len(by_name) != len(rows) or any(
        by_name.get(name) != (data_type, required) for name, data_type, required in projection
    ):
        _fail(f"{table_name} lacks the exact W2 assurance projection")


def _require_public_relation_schema(
    connection: duckdb.DuckDBPyConnection,
    entry: W2PublicValueAuthorityPublicationTable,
) -> None:
    key_column = _PUBLIC_KEY_COLUMNS.get(entry.table_name)
    if key_column is None:
        _fail("W2 publication registry contains a foreign table")
    schema = entry.schema_type.to_schema()
    expected = tuple(
        (
            ordinal,
            name,
            _sql_type(column.dtype.type),
            not bool(column.nullable) or name == key_column,
            name == key_column,
        )
        for ordinal, (name, column) in enumerate(schema.columns.items())
    )
    rows = connection.execute(f"PRAGMA table_info('{entry.table_name}')").fetchall()
    observed = tuple(
        (int(row[0]), str(row[1]), str(row[2]).upper(), bool(row[3]), bool(row[5])) for row in rows
    )
    if observed != expected or tuple(schema.columns) != entry.ordered_columns:
        _fail(f"{entry.table_name} schema or primary key differs from exact W2 authority")


def _candidate_journal_schema(connection: duckdb.DuckDBPyConnection) -> None:
    rows = connection.execute(
        f"PRAGMA table_info('{PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}')"
    ).fetchall()
    observed = tuple(
        (int(row[0]), str(row[1]), str(row[2]).upper(), bool(row[3]), bool(row[5])) for row in rows
    )
    if observed != (
        (0, "raw_authority_bundle_sha256", "VARCHAR", True, True),
        (1, "candidate_json", "VARCHAR", True, False),
        (2, "candidate_sha256", "VARCHAR", True, False),
    ):
        _fail("public-value candidate journal schema drifted")


def _decode_candidate(
    row: tuple[object, ...],
    *,
    entries_by_name: dict[str, W2PublicValueAuthorityPublicationTable],
) -> _CandidateJournal:
    if (
        len(row) != 3
        or type(row[0]) is not str
        or type(row[1]) is not str
        or type(row[2]) is not str
    ):
        _fail("public-value candidate journal row is malformed")
    bundle = _sha256(row[0], label="candidate Raw bundle")
    candidate_json = row[1]
    candidate_sha = _sha256(row[2], label="candidate digest")
    try:
        raw = candidate_json.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("public-value candidate journal contains invalid Unicode")
    if (
        not raw
        or len(raw) > _MAX_CANDIDATE_BYTES
        or hashlib.sha256(raw).hexdigest() != candidate_sha
    ):
        _fail("public-value candidate journal digest or byte bound is invalid")

    def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                _fail("public-value candidate journal repeats one field")
            result[key] = value
        return result

    def bounded_integer(token: str) -> int:
        if len(token) > 19:
            _fail("public-value candidate journal contains an over-bound integer")
        value = int(token)
        if value < 0 or value > _MAX_DATABASE_ROWS:
            _fail("public-value candidate journal contains an over-bound integer")
        return value

    def reject_number(_token: str) -> Never:
        _fail("public-value candidate journal contains a non-integer number")

    try:
        decoded = json.loads(
            candidate_json,
            object_pairs_hook=no_duplicate_keys,
            parse_int=bounded_integer,
            parse_float=reject_number,
            parse_constant=reject_number,
        )
    except _InternalAuthorityError:
        raise
    except (json.JSONDecodeError, RecursionError):
        _fail("public-value candidate journal is not exact JSON")
    if (
        type(decoded) is not dict
        or _canonical_bytes(decoded, maximum_bytes=_MAX_CANDIDATE_BYTES) != raw
    ):
        _fail("public-value candidate journal is not canonical JSON")
    payload = cast("dict[str, object]", decoded)
    if tuple(payload) != (
        "kind",
        "ownership_receipt_sha256",
        "plan_sha256",
        "public_table_projection_receipt_sha256",
        "raw_authority_bundle_sha256",
        "relations",
        "schema_version",
    ):
        _fail("public-value candidate journal has a foreign field shape")
    if (
        payload["schema_version"] != 1
        or payload["kind"] != "nbadb_public_value_authority_candidate_v1"
    ):
        _fail("public-value candidate journal has a foreign contract identity")
    if payload["raw_authority_bundle_sha256"] != bundle:
        _fail("public-value candidate journal bundle differs from its row key")
    relations = payload["relations"]
    if type(relations) is not list or len(relations) != 5:
        _fail("public-value candidate journal lacks the exact five pre-operation relations")
    expected_names = PUBLIC_VALUE_AUTHORITY_TABLES
    parsed_relations: list[_CandidateRelation] = []
    for expected_name, value in zip(expected_names, relations, strict=True):
        if type(value) is not dict:
            _fail("public-value candidate relation is malformed")
        relation = cast("dict[str, object]", value)
        if tuple(relation) != (
            "ordered_keys",
            "ordered_row_sha256s",
            "row_count",
            "schema_sha256",
            "table_name",
        ):
            _fail("public-value candidate relation has a foreign field shape")
        if relation["table_name"] != expected_name:
            _fail("public-value candidate relation membership or order drifted")
        entry = entries_by_name.get(expected_name)
        if entry is None or relation["schema_sha256"] != entry.schema_sha256:
            _fail("public-value candidate relation schema differs from exact W2 authority")
        row_count = _count(relation["row_count"], label="candidate relation row count")
        ordered_keys = relation["ordered_keys"]
        row_sha256s = relation["ordered_row_sha256s"]
        if (
            type(ordered_keys) is not list
            or type(row_sha256s) is not list
            or len(ordered_keys) != row_count
            or len(row_sha256s) != row_count
            or len(set(cast("list[object]", ordered_keys))) != row_count
            or any(
                type(item) is not str or _SHA256_RE.fullmatch(item) is None for item in ordered_keys
            )
            or any(
                type(item) is not str or _SHA256_RE.fullmatch(item) is None for item in row_sha256s
            )
        ):
            _fail("public-value candidate relation inventory is malformed")
        parsed_relations.append(
            _CandidateRelation(
                table_name=expected_name,
                schema_sha256=entry.schema_sha256,
                ordered_keys=tuple(cast("list[str]", ordered_keys)),
                ordered_row_sha256s=tuple(cast("list[str]", row_sha256s)),
            )
        )
    return _CandidateJournal(
        raw_authority_bundle_sha256=bundle,
        plan_sha256=_sha256(payload["plan_sha256"], label="candidate plan"),
        ownership_receipt_sha256=_sha256(
            payload["ownership_receipt_sha256"],
            label="candidate ownership receipt",
        ),
        public_projection_receipt_sha256=_sha256(
            payload["public_table_projection_receipt_sha256"],
            label="candidate public projection receipt",
        ),
        relations=tuple(parsed_relations),
    )


def _load_ordered_relation_rows(
    connection: duckdb.DuckDBPyConnection,
    *,
    entry: W2PublicValueAuthorityPublicationTable,
    relation: _CandidateRelation,
) -> tuple[dict[str, object], ...]:
    if not relation.ordered_keys:
        return ()
    columns = entry.ordered_columns
    key_column = _PUBLIC_KEY_COLUMNS[entry.table_name]
    selected = ", ".join(f'stored."{name}"' for name in columns)
    rows = connection.execute(
        f"SELECT {selected} "
        f'FROM "{entry.table_name}" AS stored '
        "INNER JOIN UNNEST(?) WITH ORDINALITY AS expected(key_value, row_ordinal) "
        f'ON stored."{key_column}" = expected.key_value '
        "ORDER BY expected.row_ordinal",
        [list(relation.ordered_keys)],
    ).fetchall()
    if len(rows) != len(relation.ordered_keys):
        _fail("W2 public relation is missing one candidate-keyed row")
    materialized = tuple(
        dict(zip(columns, cast("tuple[object, ...]", tuple(row)), strict=True)) for row in rows
    )
    if tuple(cast("str", row[key_column]) for row in materialized) != relation.ordered_keys:
        _fail("W2 public relation keyed readback order differs")
    observed_sha256s = tuple(
        hashlib.sha256(_canonical_bytes(row, maximum_bytes=_MAX_CANDIDATE_BYTES)).hexdigest()
        for row in materialized
    )
    if observed_sha256s != relation.ordered_row_sha256s:
        _fail("W2 public relation rows differ from the persisted candidate bytes")
    return materialized


def _journal_admissions(
    connection: duckdb.DuckDBPyConnection,
    *,
    table_names: frozenset[str],
    operation_store: W2OperationStore,
) -> tuple[W2SourceCallAdmissionV1, ...]:
    admissions: list[W2SourceCallAdmissionV1] = []
    projected_names = tuple(item[0] for item in _JOURNAL_PROJECTION)
    evidence_predicate = " OR ".join(f'"{name}" IS NOT NULL' for name in _W2_EVIDENCE_COLUMNS)
    for table_name in _JOURNAL_TABLES:
        if table_name not in table_names:
            continue
        column_rows = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        available_columns = {
            str(row[1]) for row in column_rows if len(row) >= 2 and type(row[1]) is str
        }
        w2_columns = {"w2_required", *_W2_EVIDENCE_COLUMNS}
        if not (available_columns & w2_columns):
            # A deliberately unmigrated legacy journal cannot carry W2
            # authority.  It remains a valid empty/non-required input only.
            continue
        if not w2_columns <= available_columns:
            _fail(f"{table_name} contains a partial W2 assurance projection")
        _require_projection_schema(
            connection,
            table_name=table_name,
            projection=_JOURNAL_PROJECTION,
        )
        rows = connection.execute(
            f"SELECT {', '.join(f'"{name}"' for name in projected_names)} "
            f'FROM "{table_name}" '
            f'WHERE "w2_required" OR {evidence_predicate} '
            "ORDER BY COALESCE(\"logical_call_receipt_sha256\", ''), "
            "         COALESCE(\"w2_source_call_admission_sha256\", '')"
        ).fetchall()
        if len(rows) > _MAX_JOURNAL_ROWS:
            _fail("W2 journal admission inventory exceeds its explicit bound")
        for raw_row in rows:
            row = tuple(raw_row)
            if len(row) != len(projected_names) or type(row[2]) is not bool:
                _fail("W2 journal authority row is malformed")
            if row[2] is False:
                _fail("W2 journal row has evidence without an exact required marker")
            if row[0] != "done":
                _fail("W2-required journal row is not durably successful")
            if type(row[1]) is not str or type(row[4]) is not bytes:
                _fail("W2 successful journal row lacks exact admission bytes")
            try:
                admission = W2SourceCallAdmissionV1.from_canonical_bytes(row[4])
                verified = verify_w2_source_call_admission(
                    admission,
                    expected_admission_sha256=row[3],
                    expected_logical_call_receipt_sha256=row[1],
                    expected_raw_authority_bundle_sha256=row[5],
                    expected_raw_authority_persistence_receipt_sha256=row[6],
                    expected_committed_staging_readback_count=row[7],
                    expected_committed_staging_readback_root_sha256=row[8],
                    expected_operation_key_sha256=row[9],
                    expected_operation_receipt_sha256=row[10],
                    expected_w2_operation_persistence_receipt_sha256=row[11],
                    operation_store=operation_store,
                )
            except Exception:
                _fail("W2 journal admission failed exact durable replay")
            if verified != admission or verified is admission:
                _fail("W2 journal admission changed during exact durable replay")
            admissions.append(verified)
    ordered = tuple(sorted(admissions, key=lambda item: item.logical_call_receipt_sha256))
    unique_inventories = (
        tuple(item.logical_call_receipt_sha256 for item in ordered),
        tuple(item.admission_sha256 for item in ordered),
        tuple(item.raw_authority_bundle_sha256 for item in ordered),
        tuple(item.operation_key_sha256 for item in ordered),
        tuple(item.operation_receipt_sha256 for item in ordered),
    )
    if any(len(values) != len(set(values)) for values in unique_inventories):
        _fail("W2 journal contains duplicate or cross-call authority identities")
    return ordered


def _decode_logical_parameters_json(value: object) -> dict[str, Any]:
    if type(value) is not str:
        _dto_error("on/off journal parameters must be exact canonical JSON text")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _dto_error("on/off journal parameters contain invalid Unicode")
    if not raw or len(raw) > _MAX_RECEIPT_BYTES:
        _dto_error("on/off journal parameters are empty or over-bound")

    def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                _dto_error("on/off journal parameters repeat one field")
            result[key] = item
        return result

    def reject_constant(_token: str) -> Never:
        _dto_error("on/off journal parameters contain a nonfinite number")

    try:
        decoded = json.loads(
            value,
            object_pairs_hook=no_duplicate_keys,
            parse_constant=reject_constant,
        )
    except W2DatabaseAuthorityError:
        raise
    except (json.JSONDecodeError, MemoryError, RecursionError):
        _dto_error("on/off journal parameters are not exact JSON")
    if type(decoded) is not dict or _canonical_bytes(decoded) != raw:
        _dto_error("on/off journal parameters are not canonical JSON")
    try:
        canonical = canonical_parameters_payload(cast("dict[str, Any]", decoded))
    except Exception:
        _dto_error("on/off journal parameters violate the public parameter contract")
    if canonical != decoded:
        _dto_error("on/off journal parameters differ from their canonical payload")
    return canonical


def _decode_result_route_ids(value: object, *, endpoint_name: str) -> tuple[str, ...]:
    if type(value) is not str:
        _dto_error("on/off journal route inventory must be exact canonical JSON text")
    try:
        raw = value.encode("utf-8", errors="strict")
        decoded = json.loads(value)
    except (json.JSONDecodeError, MemoryError, RecursionError, UnicodeEncodeError):
        _dto_error("on/off journal route inventory is not exact JSON")
    if (
        type(decoded) is not list
        or not decoded
        or any(type(item) is not str for item in decoded)
        or decoded != sorted(set(decoded))
        or any(not item.startswith(f"{endpoint_name}:") for item in decoded)
        or _canonical_bytes(decoded) != raw
    ):
        _dto_error("on/off journal route inventory is foreign or noncanonical")
    return tuple(cast("list[str]", decoded))


def _matching_on_off_journal_rows(
    connection: duckdb.DuckDBPyConnection,
    *,
    table_names: frozenset[str],
) -> tuple[dict[str, object], ...]:
    selected: list[dict[str, object]] = []
    common_names = tuple(item[0] for item in _ON_OFF_JOURNAL_PROJECTION)
    logical_endpoints = tuple(item[0] for item in _W2_ON_OFF_ENDPOINTS)
    for table_name in _JOURNAL_TABLES:
        if table_name not in table_names:
            continue
        column_rows = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        available = {str(row[1]) for row in column_rows if len(row) >= 2 and type(row[1]) is str}
        if not {"endpoint", "params"} <= available:
            _fail(f"{table_name} lacks its fixed-selector denominator columns")
        count_row = connection.execute(
            f'SELECT COUNT(*) FROM "{table_name}" WHERE "endpoint" IN (?, ?)',
            list(logical_endpoints),
        ).fetchone()
        if count_row is None or len(count_row) != 1 or type(count_row[0]) is not int:
            _fail("on/off journal denominator count is malformed")
        matching_count = cast("int", count_row[0])
        if matching_count == 0:
            continue
        if matching_count > _MAX_JOURNAL_ROWS:
            _fail("on/off journal denominator exceeds its explicit bound")
        _require_projection_schema(
            connection,
            table_name=table_name,
            projection=_ON_OFF_JOURNAL_PROJECTION,
        )
        successor = table_name == _JOURNAL_TABLES[1]
        if successor:
            _require_projection_schema(
                connection,
                table_name=table_name,
                projection=(("successor_generation_sha256", "VARCHAR", True),),
            )
        selected_names = (
            ("successor_generation_sha256", *common_names) if successor else common_names
        )
        rows = connection.execute(
            f"SELECT {', '.join(f'"{name}"' for name in selected_names)} "
            f'FROM "{table_name}" WHERE "endpoint" IN (?, ?) '
            'ORDER BY "endpoint", "params", '
            "COALESCE(\"logical_call_receipt_sha256\", '')",
            list(logical_endpoints),
        ).fetchall()
        if len(rows) != matching_count:
            _fail("on/off journal denominator changed during its locked read")
        for raw_row in rows:
            row = tuple(raw_row)
            if len(row) != len(selected_names):
                _fail("on/off journal row is malformed")
            selected.append(
                {
                    "journal_table_name": table_name,
                    "successor_generation_sha256": (row[0] if successor else None),
                    **dict(
                        zip(
                            common_names,
                            row[1:] if successor else row,
                            strict=True,
                        )
                    ),
                }
            )
    if not selected:
        _fail("W2 on/off fixed selector matched no logical calls")
    return tuple(selected)


def _load_on_off_result_cells(
    connection: duckdb.DuckDBPyConnection,
    *,
    observation_sha256s: tuple[str, ...],
) -> tuple[RawNbaApiResultCellV2, ...]:
    if not observation_sha256s:
        _fail("W2 on/off source call lacks selected observations")
    entries = {item.table_name: item for item in w2_public_value_authority_publication_tables()}
    entry = entries.get("raw_nba_api_result_cell")
    if entry is None or entry.row_model is not RawNbaApiResultCellV2:
        _fail("W2 result-cell registry differs from its typed authority")
    rows = connection.execute(
        f"SELECT {', '.join(f'"{name}"' for name in entry.ordered_columns)} "
        'FROM "raw_nba_api_result_cell" '
        "WHERE observation_sha256 IN (SELECT * FROM UNNEST(?)) "
        "ORDER BY cell_sha256",
        [list(observation_sha256s)],
    ).fetchall()
    if len(rows) > MAX_W2_PUBLICATION_INPUT_ROWS:
        _fail("W2 on/off result-cell inventory exceeds its explicit bound")
    try:
        return tuple(
            RawNbaApiResultCellV2.from_row(
                dict(zip(entry.ordered_columns, tuple(row), strict=True))
            )
            for row in rows
        )
    except Exception:
        _fail("W2 on/off result cells failed exact typed replay")


def _source_call_identity_payload(
    *,
    journal_table_name: str,
    successor_generation_sha256: str | None,
    logical_endpoint_name: str,
    logical_parameters_json: str,
    logical_parameters_sha256: str,
    shared_pair_scope_json: str,
    shared_pair_scope_sha256: str,
    provider_authority_sha256: str,
    declared_result_route_ids: tuple[str, ...],
    declared_result_route_count: int,
    declared_result_route_inventory_sha256: str,
    canonical_owner_route_ids: tuple[str, ...],
    canonical_owner_route_count: int,
    canonical_owner_route_inventory_sha256: str,
    non_owning_alias_route_ids: tuple[str, ...],
    non_owning_alias_route_count: int,
    non_owning_alias_route_inventory_sha256: str,
    result_ownerships: tuple[W2OnOffResultOwnershipV1, ...],
    logical_call_receipt_sha256: str,
    admission_sha256: str,
    raw_authority_bundle_sha256: str,
    result_cell_count: int,
    result_cell_inventory_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": W2OnOffSourceCallSnapshotV1.schema_version,
        "kind": W2OnOffSourceCallSnapshotV1.kind,
        "admission_sha256": admission_sha256,
        "journal_table_name": journal_table_name,
        "logical_call_receipt_sha256": logical_call_receipt_sha256,
        "logical_endpoint_name": logical_endpoint_name,
        "logical_parameters_json": logical_parameters_json,
        "logical_parameters_sha256": logical_parameters_sha256,
        "shared_pair_scope_json": shared_pair_scope_json,
        "shared_pair_scope_sha256": shared_pair_scope_sha256,
        "provider_authority_sha256": provider_authority_sha256,
        "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
        "declared_result_route_count": declared_result_route_count,
        "declared_result_route_inventory_sha256": declared_result_route_inventory_sha256,
        "declared_result_route_ids": list(declared_result_route_ids),
        "canonical_owner_route_count": canonical_owner_route_count,
        "canonical_owner_route_inventory_sha256": canonical_owner_route_inventory_sha256,
        "canonical_owner_route_ids": list(canonical_owner_route_ids),
        "non_owning_alias_route_count": non_owning_alias_route_count,
        "non_owning_alias_route_inventory_sha256": (non_owning_alias_route_inventory_sha256),
        "non_owning_alias_route_ids": list(non_owning_alias_route_ids),
        "result_ownership_sha256s": [item.ownership_sha256 for item in result_ownerships],
        "result_cell_count": result_cell_count,
        "result_cell_inventory_sha256": result_cell_inventory_sha256,
        "successor_generation_sha256": successor_generation_sha256,
    }


def _materialize_on_off_source_calls(
    connection: duckdb.DuckDBPyConnection,
    *,
    snapshot_transaction_id: int | None = None,
) -> tuple[W2OnOffSourceCallSnapshotV1, ...]:
    table_names = _table_names(connection)
    operation_store = W2OperationStore(connection)
    raw_store = RawRequestAuthorityStore(connection)
    if snapshot_transaction_id is not None:
        _bind_verifier_owned_snapshot_guard(
            operation_store,
            connection=connection,
            snapshot_transaction_id=snapshot_transaction_id,
        )
        _bind_verifier_owned_snapshot_guard(
            raw_store,
            connection=connection,
            snapshot_transaction_id=snapshot_transaction_id,
        )
    admissions = _journal_admissions(
        connection,
        table_names=table_names,
        operation_store=operation_store,
    )
    admission_by_receipt = {item.logical_call_receipt_sha256: item for item in admissions}
    if len(admission_by_receipt) != len(admissions):
        _fail("W2 global admission inventory repeats one logical call")
    bundles_by_receipt: dict[str, RawRequestAuthorityBundleV2] = {}
    provider_selected_receipts: set[str] = set()
    on_off_provider_ids = frozenset(_W2_ON_OFF_LOGICAL_BY_PROVIDER)
    for admission in admissions:
        try:
            bundle = raw_store.verify_persisted_receipt(
                expected_bundle_sha256=admission.raw_authority_bundle_sha256,
                expected_receipt_sha256=admission.raw_authority_persistence_receipt_sha256,
            )
        except Exception:
            _fail("W2 on/off selector could not replay one global Raw bundle")
        bundles_by_receipt[admission.logical_call_receipt_sha256] = bundle
        provider_ids = {
            item.attempt.endpoint_id
            for item in bundle.observations
            if item.lifecycle == "selected_terminal"
        }
        matching = provider_ids & on_off_provider_ids
        if matching:
            if len(provider_ids) != 1 or len(matching) != 1:
                _fail("W2 Raw bundle mixes fixed-selector and foreign provider calls")
            provider_selected_receipts.add(admission.logical_call_receipt_sha256)

    journal_rows = _matching_on_off_journal_rows(connection, table_names=table_names)
    source_calls: list[W2OnOffSourceCallSnapshotV1] = []
    journal_selected_receipts: set[str] = set()
    selector_keys: set[tuple[str, str]] = set()
    for row in journal_rows:
        endpoint_name = row["endpoint"]
        if type(endpoint_name) is not str or endpoint_name not in _W2_ON_OFF_PROVIDER_BY_LOGICAL:
            _fail("on/off journal row has a foreign logical endpoint")
        parameters = _decode_logical_parameters_json(row["params"])
        logical_parameters_json = cast("str", row["params"])
        logical_parameters_sha256 = canonical_parameters_sha256(parameters)
        shared_pair_scope_json, shared_pair_scope_sha256 = _shared_pair_scope(parameters)
        if row["logical_parameters_sha256"] != logical_parameters_sha256:
            _fail("on/off journal parameter digest differs from canonical parameters")
        provider_authority_sha256 = _sha256(
            row["provider_authority_sha256"],
            label="on/off journal provider authority",
        )
        result_route_ids = _decode_result_route_ids(
            row["result_route_ids_json"],
            endpoint_name=endpoint_name,
        )
        logical_call_receipt_sha256 = _sha256(
            row["logical_call_receipt_sha256"],
            label="on/off journal logical call receipt",
        )
        if row["status"] != "done" or row["w2_required"] is not True:
            _fail("on/off journal call is legacy, partial, or not durably W2-complete")
        admission = admission_by_receipt.get(logical_call_receipt_sha256)
        if admission is None or type(row["w2_source_call_admission_bytes"]) is not bytes:
            _fail("on/off journal call lacks one exact global W2 admission")
        try:
            replayed = W2SourceCallAdmissionV1.from_canonical_bytes(
                row["w2_source_call_admission_bytes"]
            )
            verified = verify_w2_source_call_admission(
                replayed,
                expected_admission_sha256=row["w2_source_call_admission_sha256"],
                expected_logical_call_receipt_sha256=logical_call_receipt_sha256,
                expected_raw_authority_bundle_sha256=row["raw_authority_bundle_sha256"],
                expected_raw_authority_persistence_receipt_sha256=(
                    row["raw_authority_persistence_receipt_sha256"]
                ),
                expected_committed_staging_readback_count=(row["committed_staging_readback_count"]),
                expected_committed_staging_readback_root_sha256=(
                    row["committed_staging_readback_root_sha256"]
                ),
                expected_operation_key_sha256=row["w2_operation_key_sha256"],
                expected_operation_receipt_sha256=row["w2_operation_receipt_sha256"],
                expected_w2_operation_persistence_receipt_sha256=(
                    row["w2_operation_persistence_receipt_sha256"]
                ),
                operation_store=operation_store,
            )
        except Exception:
            _fail("on/off journal call failed exact W2 admission replay")
        if verified != admission or verified is admission:
            _fail("on/off journal admission differs from the global W2 denominator")
        bundle = bundles_by_receipt[logical_call_receipt_sha256]
        result_ownerships = _build_on_off_result_ownerships(
            endpoint_name=endpoint_name,
            bundle=bundle,
        )
        declared_result_route_ids = tuple(
            sorted(route_id for item in result_ownerships for route_id in item.declared_route_ids)
        )
        canonical_owner_route_ids = tuple(
            sorted(item.canonical_owner_route_id for item in result_ownerships)
        )
        non_owning_alias_route_ids = tuple(
            sorted(
                route_id
                for item in result_ownerships
                for route_id in item.non_owning_alias_route_ids
            )
        )
        if result_route_ids != canonical_owner_route_ids:
            _fail("on/off journal routes differ from the fixed canonical owners")
        declared_result_route_inventory_sha256 = _route_inventory_sha256(
            result_ownerships,
            role="declared",
        )
        canonical_owner_route_inventory_sha256 = _route_inventory_sha256(
            result_ownerships,
            role="canonical_owner",
        )
        non_owning_alias_route_inventory_sha256 = _route_inventory_sha256(
            result_ownerships,
            role="non_owning_alias",
        )
        selected_observations = tuple(
            item for item in bundle.observations if item.lifecycle == "selected_terminal"
        )
        selected_observation_ids = tuple(
            sorted(item.attempt.observation_sha256 for item in selected_observations)
        )
        result_cells = _load_on_off_result_cells(
            connection,
            observation_sha256s=selected_observation_ids,
        )
        result_cell_inventory_sha256 = _inventory_sha256(
            "nbadb_w2_on_off_source_call_result_cells_v1",
            [item.to_row() for item in result_cells],
        )
        successor_generation = row["successor_generation_sha256"]
        if row["journal_table_name"] == _JOURNAL_TABLES[0]:
            if successor_generation is not None:
                _fail("baseline on/off journal row carries a successor generation")
        else:
            successor_generation = _sha256(
                successor_generation,
                label="on/off successor generation",
            )
        selector_key = (endpoint_name, logical_parameters_sha256)
        if selector_key in selector_keys:
            _fail("on/off journal denominator overlaps journals or generations")
        selector_keys.add(selector_key)
        if logical_call_receipt_sha256 in journal_selected_receipts:
            _fail("on/off journal denominator repeats one logical call")
        journal_selected_receipts.add(logical_call_receipt_sha256)
        identity = _source_call_identity_payload(
            journal_table_name=cast("str", row["journal_table_name"]),
            successor_generation_sha256=successor_generation,
            logical_endpoint_name=endpoint_name,
            logical_parameters_json=logical_parameters_json,
            logical_parameters_sha256=logical_parameters_sha256,
            shared_pair_scope_json=shared_pair_scope_json,
            shared_pair_scope_sha256=shared_pair_scope_sha256,
            provider_authority_sha256=provider_authority_sha256,
            declared_result_route_ids=declared_result_route_ids,
            declared_result_route_count=len(declared_result_route_ids),
            declared_result_route_inventory_sha256=(declared_result_route_inventory_sha256),
            canonical_owner_route_ids=canonical_owner_route_ids,
            canonical_owner_route_count=len(canonical_owner_route_ids),
            canonical_owner_route_inventory_sha256=(canonical_owner_route_inventory_sha256),
            non_owning_alias_route_ids=non_owning_alias_route_ids,
            non_owning_alias_route_count=len(non_owning_alias_route_ids),
            non_owning_alias_route_inventory_sha256=(non_owning_alias_route_inventory_sha256),
            result_ownerships=result_ownerships,
            logical_call_receipt_sha256=logical_call_receipt_sha256,
            admission_sha256=admission.admission_sha256,
            raw_authority_bundle_sha256=bundle.bundle_sha256,
            result_cell_count=len(result_cells),
            result_cell_inventory_sha256=result_cell_inventory_sha256,
        )
        source_calls.append(
            W2OnOffSourceCallSnapshotV1(
                source_call_sha256=_canonical_sha256(identity),
                journal_table_name=cast("str", row["journal_table_name"]),
                successor_generation_sha256=successor_generation,
                logical_endpoint_name=endpoint_name,
                logical_parameters_json=logical_parameters_json,
                logical_parameters_sha256=logical_parameters_sha256,
                shared_pair_scope_json=shared_pair_scope_json,
                shared_pair_scope_sha256=shared_pair_scope_sha256,
                provider_authority_sha256=provider_authority_sha256,
                declared_result_route_ids=declared_result_route_ids,
                declared_result_route_count=len(declared_result_route_ids),
                declared_result_route_inventory_sha256=(declared_result_route_inventory_sha256),
                canonical_owner_route_ids=canonical_owner_route_ids,
                canonical_owner_route_count=len(canonical_owner_route_ids),
                canonical_owner_route_inventory_sha256=(canonical_owner_route_inventory_sha256),
                non_owning_alias_route_ids=non_owning_alias_route_ids,
                non_owning_alias_route_count=len(non_owning_alias_route_ids),
                non_owning_alias_route_inventory_sha256=(non_owning_alias_route_inventory_sha256),
                result_ownerships=result_ownerships,
                logical_call_receipt_sha256=logical_call_receipt_sha256,
                admission=admission,
                raw_authority_bundle=bundle,
                result_cells=result_cells,
                result_cell_count=len(result_cells),
                result_cell_inventory_sha256=result_cell_inventory_sha256,
            )
        )
    if journal_selected_receipts != provider_selected_receipts:
        _fail("on/off fixed-selector journal and Raw provider denominators differ")
    return tuple(sorted(source_calls, key=_source_call_sort_key))


def _build_on_off_database_snapshot(
    *,
    database_authority: W2DatabaseAuthorityReceiptV1,
    source_calls: tuple[W2OnOffSourceCallSnapshotV1, ...],
) -> W2OnOffDatabaseSnapshotV1:
    pairs = _build_on_off_pairs(source_calls)
    observation_rows = _selected_observation_rows(source_calls)
    occurrence_rows = _selected_occurrence_rows(source_calls)
    result_cell_rows = _selected_result_cell_rows(source_calls)
    values: dict[str, object] = {
        "selector_kind": W2_ON_OFF_SELECTOR_KIND,
        "database_authority": database_authority,
        "database_generation_sha256": _on_off_database_generation_sha256(
            database_authority=database_authority,
            source_calls=source_calls,
            pairs=pairs,
        ),
        "selected_pair_count": len(pairs),
        "selected_pair_inventory_sha256": _inventory_sha256(
            "nbadb_w2_on_off_selected_pairs_v1",
            [item.identity_payload() for item in pairs],
        ),
        "selected_logical_call_count": len(source_calls),
        "selected_logical_call_inventory_sha256": _inventory_sha256(
            "nbadb_w2_on_off_selected_logical_calls_v1",
            [item.identity_payload() for item in source_calls],
        ),
        "selected_observation_count": len(observation_rows),
        "selected_observation_inventory_sha256": _inventory_sha256(
            "nbadb_w2_on_off_selected_observations_v1",
            list(observation_rows),
        ),
        "selected_occurrence_count": len(occurrence_rows),
        "selected_occurrence_inventory_sha256": _inventory_sha256(
            "nbadb_w2_on_off_selected_occurrences_v1",
            list(occurrence_rows),
        ),
        "selected_result_cell_count": len(result_cell_rows),
        "selected_result_cell_inventory_sha256": _inventory_sha256(
            "nbadb_w2_on_off_selected_result_cells_v1",
            list(result_cell_rows),
        ),
        "pairs": pairs,
        "source_calls": source_calls,
    }
    identity = {
        "schema_version": W2OnOffDatabaseSnapshotV1.schema_version,
        "kind": W2OnOffDatabaseSnapshotV1.kind,
        "database_authority_receipt_sha256": database_authority.receipt_sha256,
        **{
            key: (
                [item.source_call_sha256 for item in source_calls]
                if key == "source_calls"
                else [pair.pair_sha256 for pair in pairs]
                if key == "pairs"
                else item
            )
            for key, item in values.items()
            if key != "database_authority"
        },
    }
    identity["source_call_sha256s"] = identity.pop("source_calls")
    identity["pair_sha256s"] = identity.pop("pairs")
    return W2OnOffDatabaseSnapshotV1(
        snapshot_sha256=_canonical_sha256(identity),
        **cast("Any", values),
    )


def _current_transaction_id(connection: duckdb.DuckDBPyConnection) -> int:
    row = connection.execute("SELECT current_transaction_id()").fetchone()
    if row is None or len(row) != 1 or type(row[0]) is not int or row[0] < 0:
        _fail("DuckDB transaction identity is unavailable or malformed")
    return cast("int", row[0])


def _bind_verifier_owned_snapshot_guard(
    store: object,
    *,
    connection: duckdb.DuckDBPyConnection,
    snapshot_transaction_id: int,
) -> None:
    def require_exact_snapshot(_store: object) -> None:
        if _current_transaction_id(connection) != snapshot_transaction_id:
            _fail("verifier-owned DuckDB snapshot identity changed")

    cast("Any", store)._require_no_caller_transaction = MethodType(  # noqa: SLF001
        require_exact_snapshot,
        store,
    )


@contextmanager
def _verifier_owned_read_snapshot(
    connection: duckdb.DuckDBPyConnection,
    *,
    previous_transaction_id: int,
) -> Iterator[int]:
    owns_transaction = False
    try:
        connection.execute("BEGIN TRANSACTION")
        owns_transaction = True
        snapshot_transaction_id = _current_transaction_id(connection)
        # This is a conservative concurrency tripwire, not returned durable
        # authority.  DuckDB transaction IDs are database-global, so unrelated
        # concurrent reads may make this fail closed.
        if snapshot_transaction_id != previous_transaction_id + 1:
            _fail("DuckDB transaction activity changed before verifier snapshot admission")
        yield snapshot_transaction_id
        connection.execute("COMMIT")
        owns_transaction = False
    finally:
        if owns_transaction:
            with suppress(Exception):
                connection.execute("ROLLBACK")


def _close_snapshot_concurrency_tripwire(
    connection: duckdb.DuckDBPyConnection,
    *,
    snapshot_transaction_id: int,
) -> int:
    next_transaction_id = _current_transaction_id(connection)
    if next_transaction_id != snapshot_transaction_id + 1:
        _fail("DuckDB transaction activity changed during verifier snapshot replay")
    return next_transaction_id


def _verify_database(
    connection: duckdb.DuckDBPyConnection,
    *,
    require_w2: bool,
    expected_receipt_sha256: str | None,
    snapshot_transaction_id: int | None = None,
) -> W2DatabaseAuthorityReceiptV1:
    operation_store = W2OperationStore(connection)
    raw_store = RawRequestAuthorityStore(connection)
    if snapshot_transaction_id is not None:
        _bind_verifier_owned_snapshot_guard(
            operation_store,
            connection=connection,
            snapshot_transaction_id=snapshot_transaction_id,
        )
        _bind_verifier_owned_snapshot_guard(
            raw_store,
            connection=connection,
            snapshot_transaction_id=snapshot_transaction_id,
        )
    # Fixed acquisition order follows the durable persistence order: Raw V2,
    # public five, operation.  Every nested verifier uses the same RLocks.
    with (
        raw_store_module._WRITE_LOCK,  # noqa: SLF001
        public_store_module._WRITE_LOCK,  # noqa: SLF001
        operation_store_module._WRITE_LOCK,  # noqa: SLF001
    ):
        operation_store._require_no_caller_transaction()  # noqa: SLF001
        table_names = _table_names(connection)
        entries = w2_public_value_authority_publication_tables()
        if type(entries) is not tuple or len(entries) != 6:
            _fail("W2 publication registry does not contain exact six relations")
        entries_by_name = {item.table_name: item for item in entries}
        expected_public_tables = frozenset(entries_by_name)
        present_public_tables = expected_public_tables & table_names
        candidate_present = PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL in table_names
        has_w2_storage = bool(present_public_tables or candidate_present)

        admissions = _journal_admissions(
            connection,
            table_names=table_names,
            operation_store=operation_store,
        )
        if require_w2 and not admissions:
            _fail("W2 database assurance requires at least one closed logical call")
        if (admissions or has_w2_storage) and (
            present_public_tables != expected_public_tables or not candidate_present
        ):
            _fail("W2 database contains a partial exact-six persistence boundary")

        schema_inventory = [
            {
                "ordered_columns": list(entry.ordered_columns),
                "schema_sha256": entry.schema_sha256,
                "table_name": entry.table_name,
            }
            for entry in entries
        ]
        exact_six_schema_sha256 = _inventory_sha256(
            "nbadb_w2_database_exact_six_schema_inventory_v1",
            schema_inventory,
        )
        if present_public_tables:
            for entry in entries:
                _require_public_relation_schema(connection, entry)
            try:
                operation_store._require_table_contract()  # noqa: SLF001
            except Exception:
                _fail("W2 operation durable table contract drifted")
            _candidate_journal_schema(connection)

        candidate_rows = (
            connection.execute(
                f"SELECT raw_authority_bundle_sha256, candidate_json, candidate_sha256 "
                f'FROM "{PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}" '
                "ORDER BY raw_authority_bundle_sha256"
            ).fetchall()
            if candidate_present
            else []
        )
        if len(candidate_rows) > _MAX_JOURNAL_ROWS:
            _fail("public-value candidate inventory exceeds its explicit bound")
        candidates = tuple(
            _decode_candidate(tuple(row), entries_by_name=entries_by_name) for row in candidate_rows
        )
        candidate_by_bundle = {item.raw_authority_bundle_sha256: item for item in candidates}
        if len(candidate_by_bundle) != len(candidates):
            _fail("public-value candidate journal repeats one Raw bundle")

        admission_bundles = tuple(item.raw_authority_bundle_sha256 for item in admissions)
        if set(candidate_by_bundle) != set(admission_bundles):
            _fail("public-five candidate journal contains missing or orphan W2 bundles")
        operation_rows = (
            connection.execute(
                f"SELECT operation_key_sha256, raw_authority_bundle_sha256 "
                f'FROM "{RAW_NBA_API_W2_OPERATION_TABLE}" ORDER BY operation_key_sha256'
            ).fetchall()
            if RAW_NBA_API_W2_OPERATION_TABLE in table_names
            else []
        )
        expected_operations = {
            item.operation_key_sha256: item.raw_authority_bundle_sha256 for item in admissions
        }
        if any(
            len(row) != 2 or type(row[0]) is not str or type(row[1]) is not str
            for row in operation_rows
        ) or {cast("str", row[0]): cast("str", row[1]) for row in operation_rows} != (
            expected_operations
        ):
            _fail("W2 operation relation contains missing, changed, or orphan rows")

        bundles: dict[str, RawRequestAuthorityBundleV2] = {}
        observations_to_bundle: dict[str, str] = {}
        occurrences_to_bundle: dict[str, str] = {}
        for admission in admissions:
            try:
                bundle = raw_store.verify_persisted_receipt(
                    expected_bundle_sha256=admission.raw_authority_bundle_sha256,
                    expected_receipt_sha256=(admission.raw_authority_persistence_receipt_sha256),
                )
            except Exception:
                _fail("W2 admission Raw Authority V2 receipt failed exact durable replay")
            logical_receipts = {
                item.logical_receipt_sha256
                for item in bundle.observations
                if item.lifecycle == "selected_terminal"
            }
            if logical_receipts != {admission.logical_call_receipt_sha256}:
                _fail("W2 admission logical call differs from its selected Raw authority")
            bundles[bundle.bundle_sha256] = bundle
            for observation in bundle.observations:
                identity = observation.attempt.observation_sha256
                if identity in observations_to_bundle:
                    _fail("W2 Raw bundles share one observation identity")
                observations_to_bundle[identity] = bundle.bundle_sha256
            for occurrence in bundle.occurrences:
                if occurrence.occurrence_sha256 in occurrences_to_bundle:
                    _fail("W2 Raw bundles share one occurrence identity")
                occurrences_to_bundle[occurrence.occurrence_sha256] = bundle.bundle_sha256

        scoped_counts: dict[str, dict[str, int]] = {
            table_name: {} for table_name in PUBLIC_VALUE_AUTHORITY_TABLES
        }
        if present_public_tables:
            result_entry = entries_by_name["raw_nba_api_result_cell"]
            result_rows = connection.execute(
                f'SELECT "{_PUBLIC_KEY_COLUMNS[result_entry.table_name]}", '
                '       "observation_sha256", "occurrence_sha256" '
                f'FROM "{result_entry.table_name}"'
            ).fetchall()
            if len(result_rows) > MAX_W2_PUBLICATION_INPUT_ROWS:
                _fail("result-cell closure inventory exceeds its explicit bound")
            for row in result_rows:
                if (
                    len(row) != 3
                    or type(row[0]) is not str
                    or type(row[1]) is not str
                    or type(row[2]) is not str
                ):
                    _fail("result-cell closure inventory is malformed")
                observation_bundle = observations_to_bundle.get(cast("str", row[1]))
                occurrence_bundle = occurrences_to_bundle.get(cast("str", row[2]))
                if observation_bundle is None or observation_bundle != occurrence_bundle:
                    _fail("result-cell relation contains an orphan or cross-bundle row")
                counts = scoped_counts[result_entry.table_name]
                counts[observation_bundle] = counts.get(observation_bundle, 0) + 1
            for table_name, bundle_column in _BUNDLE_COLUMNS.items():
                rows = connection.execute(
                    f'SELECT "{bundle_column}", COUNT(*) FROM "{table_name}" '
                    f'GROUP BY "{bundle_column}" ORDER BY "{bundle_column}"'
                ).fetchall()
                counts: dict[str, int] = {}
                for row in rows:
                    if (
                        len(row) != 2
                        or type(row[0]) is not str
                        or type(row[1]) is not int
                        or row[1] < 0
                    ):
                        _fail("W2 bundle-scoped relation count is malformed")
                    bundle_sha = cast("str", row[0])
                    if bundle_sha not in bundles:
                        _fail("W2 public relation contains one orphan Raw bundle")
                    counts[bundle_sha] = cast("int", row[1])
                scoped_counts[table_name] = counts

        publication_receipts: list[W2PublicationVerificationReceiptV1] = []
        relation_totals = {entry.table_name: 0 for entry in entries}
        for admission in admissions:
            bundle_sha = admission.raw_authority_bundle_sha256
            candidate = candidate_by_bundle[bundle_sha]
            operation = admission.operation
            if (
                candidate.plan_sha256 != operation.value_projection_plan_sha256
                or candidate.ownership_receipt_sha256 != operation.lossless_ownership_receipt_sha256
                or candidate.public_projection_receipt_sha256
                != operation.public_table_value_projection_receipt_sha256
            ):
                _fail("public-five candidate journal differs from its W2 operation")
            relation_by_name = {item.table_name: item for item in candidate.relations}
            relation_rows: dict[str, tuple[dict[str, object], ...]] = {}
            for table_name in PUBLIC_VALUE_AUTHORITY_TABLES:
                relation = relation_by_name[table_name]
                if scoped_counts[table_name].get(bundle_sha, 0) != len(relation.ordered_keys):
                    _fail("W2 public relation has missing or extra bundle-scoped rows")
                rows = _load_ordered_relation_rows(
                    connection,
                    entry=entries_by_name[table_name],
                    relation=relation,
                )
                relation_rows[table_name] = rows
                relation_totals[table_name] += len(rows)
            try:
                receipt = verify_w2_publication(
                    raw_authority_bundle=bundles[bundle_sha],
                    expected_raw_authority_bundle_sha256=bundle_sha,
                    result_cell_rows=relation_rows[PUBLIC_VALUE_AUTHORITY_TABLES[0]],
                    expected_result_cell_schema_sha256=(
                        entries_by_name[PUBLIC_VALUE_AUTHORITY_TABLES[0]].schema_sha256
                    ),
                    stats_lossless_rows=relation_rows[PUBLIC_VALUE_AUTHORITY_TABLES[1]],
                    expected_stats_lossless_schema_sha256=(
                        entries_by_name[PUBLIC_VALUE_AUTHORITY_TABLES[1]].schema_sha256
                    ),
                    live_lossless_rows=relation_rows[PUBLIC_VALUE_AUTHORITY_TABLES[2]],
                    expected_live_lossless_schema_sha256=(
                        entries_by_name[PUBLIC_VALUE_AUTHORITY_TABLES[2]].schema_sha256
                    ),
                    value_representation_rows=relation_rows[PUBLIC_VALUE_AUTHORITY_TABLES[3]],
                    expected_value_representation_schema_sha256=(
                        entries_by_name[PUBLIC_VALUE_AUTHORITY_TABLES[3]].schema_sha256
                    ),
                    route_field_landing_rows=relation_rows[PUBLIC_VALUE_AUTHORITY_TABLES[4]],
                    expected_route_field_landing_schema_sha256=(
                        entries_by_name[PUBLIC_VALUE_AUTHORITY_TABLES[4]].schema_sha256
                    ),
                    w2_operation_rows=(operation.to_row(),),
                    expected_w2_operation_schema_sha256=(
                        entries_by_name[RAW_NBA_API_W2_OPERATION_TABLE].schema_sha256
                    ),
                    expected_operation_key_sha256=admission.operation_key_sha256,
                    expected_operation_receipt_sha256=admission.operation_receipt_sha256,
                )
            except Exception:
                _fail("W2 exact-six publication failed database-derived verification")
            publication_receipts.append(receipt)
            relation_totals[RAW_NBA_API_W2_OPERATION_TABLE] += 1

        ordered_publication_receipts = tuple(
            sorted(
                publication_receipts,
                key=lambda item: (item.raw_authority_bundle_sha256, item.operation_key_sha256),
            )
        )
        ordered_admissions = tuple(
            sorted(
                admissions,
                key=lambda item: (item.raw_authority_bundle_sha256, item.operation_key_sha256),
            )
        )
        relation_row_counts = tuple(sorted(relation_totals.items()))
        receipt = W2DatabaseAuthorityReceiptV1.build(
            w2_required_logical_call_count=len(ordered_admissions),
            w2_source_call_admission_inventory_sha256=_inventory_sha256(
                "nbadb_w2_database_admission_inventory_v1",
                [item.admission_sha256 for item in ordered_admissions],
            ),
            raw_authority_v2_bundle_count=len(ordered_admissions),
            raw_authority_v2_bundle_inventory_sha256=_inventory_sha256(
                "nbadb_w2_database_raw_v2_bundle_inventory_v1",
                [item.raw_authority_bundle_sha256 for item in ordered_admissions],
            ),
            raw_authority_v2_persistence_receipt_inventory_sha256=_inventory_sha256(
                "nbadb_w2_database_raw_v2_persistence_receipt_inventory_v1",
                [item.raw_authority_persistence_receipt_sha256 for item in ordered_admissions],
            ),
            w2_publication_receipt_count=len(ordered_publication_receipts),
            w2_publication_receipt_inventory_sha256=_inventory_sha256(
                "nbadb_w2_database_publication_receipt_inventory_v1",
                [item.to_row() for item in ordered_publication_receipts],
            ),
            w2_exact_six_schema_inventory_sha256=exact_six_schema_sha256,
            w2_relation_row_counts=relation_row_counts,
            w2_relation_row_count=sum(value for _name, value in relation_row_counts),
            w2_relation_inventory_sha256=_inventory_sha256(
                "nbadb_w2_database_relation_inventory_v1",
                [
                    {
                        "operation_key_sha256": item.operation_key_sha256,
                        "raw_authority_bundle_sha256": item.raw_authority_bundle_sha256,
                        "relation_inventory_sha256": item.relation_inventory_sha256,
                    }
                    for item in ordered_publication_receipts
                ],
            ),
        )
        if (
            expected_receipt_sha256 is not None
            and receipt.receipt_sha256 != expected_receipt_sha256
        ):
            _fail("W2 database authority differs from its expected receipt")
        return receipt


def verify_w2_database_authority(
    connection: object,
    *,
    require_w2: object,
    expected_receipt_sha256: object = None,
) -> W2DatabaseAuthorityReceiptV1:
    """Reconstruct and close every W2 authority boundary from database bytes."""

    if type(require_w2) is not bool:
        raise W2DatabaseAuthorityError("require_w2 must be one exact boolean") from None
    expected = None
    if expected_receipt_sha256 is not None:
        if (
            type(expected_receipt_sha256) is not str
            or _SHA256_RE.fullmatch(expected_receipt_sha256) is None
        ):
            raise W2DatabaseAuthorityError(
                "expected W2 database receipt must be one exact lowercase SHA-256"
            ) from None
        expected = expected_receipt_sha256
    if not isinstance(connection, duckdb.DuckDBPyConnection):
        raise W2DatabaseAuthorityError(
            "W2 database assurance requires a DuckDB connection"
        ) from None
    try:
        return _verify_database(
            connection,
            require_w2=require_w2,
            expected_receipt_sha256=expected,
        )
    except _InternalAuthorityError as exc:
        raise W2DatabaseAuthorityError(str(exc)) from None
    except Exception:
        raise W2DatabaseAuthorityError(
            "W2 database authority verification failed exact sanitized dependency replay"
        ) from None


def verify_w2_on_off_database_snapshot(
    connection: object,
    *,
    expected_database_receipt_sha256: object = None,
) -> W2OnOffDatabaseSnapshotV1:
    """Return the immutable complete W2 snapshot for the fixed on/off selector.

    The selector is verifier-owned.  Callers cannot supply logical-call IDs,
    predicates, SQL, routes, endpoint names, or a resolver.  Global W2 closure,
    the selected typed records, and a final global replay occur in two exact
    verifier-owned DuckDB read snapshots while the Raw/public/operation
    persistence locks remain held.  Process locks and transaction-ID tripwires
    are coordination only; durable authority is whole-receipt plus exact
    current-generation equality across those snapshots.
    """

    if not isinstance(connection, duckdb.DuckDBPyConnection):
        raise W2DatabaseAuthorityError(
            "W2 on/off database snapshot requires a DuckDB connection"
        ) from None
    expected = None
    if expected_database_receipt_sha256 is not None:
        if (
            type(expected_database_receipt_sha256) is not str
            or _SHA256_RE.fullmatch(expected_database_receipt_sha256) is None
        ):
            raise W2DatabaseAuthorityError(
                "expected W2 database receipt must be one exact lowercase SHA-256"
            ) from None
        expected = expected_database_receipt_sha256
    operation_store = W2OperationStore(connection)
    try:
        with (
            raw_store_module._WRITE_LOCK,  # noqa: SLF001
            public_store_module._WRITE_LOCK,  # noqa: SLF001
            operation_store_module._WRITE_LOCK,  # noqa: SLF001
        ):
            operation_store._require_no_caller_transaction()  # noqa: SLF001
            previous_transaction_id = _current_transaction_id(connection)
            with _verifier_owned_read_snapshot(
                connection,
                previous_transaction_id=previous_transaction_id,
            ) as initial_transaction_id:
                initial_authority = _verify_database(
                    connection,
                    require_w2=False,
                    expected_receipt_sha256=expected,
                    snapshot_transaction_id=initial_transaction_id,
                )
                initial_source_calls = _materialize_on_off_source_calls(
                    connection,
                    snapshot_transaction_id=initial_transaction_id,
                )
                initial_pairs = _build_on_off_pairs(initial_source_calls)
                initial_generation = _on_off_database_generation_sha256(
                    database_authority=initial_authority,
                    source_calls=initial_source_calls,
                    pairs=initial_pairs,
                )
            previous_transaction_id = _close_snapshot_concurrency_tripwire(
                connection,
                snapshot_transaction_id=initial_transaction_id,
            )
            with _verifier_owned_read_snapshot(
                connection,
                previous_transaction_id=previous_transaction_id,
            ) as final_transaction_id:
                final_authority = _verify_database(
                    connection,
                    require_w2=False,
                    expected_receipt_sha256=initial_authority.receipt_sha256,
                    snapshot_transaction_id=final_transaction_id,
                )
                final_source_calls = _materialize_on_off_source_calls(
                    connection,
                    snapshot_transaction_id=final_transaction_id,
                )
                final_pairs = _build_on_off_pairs(final_source_calls)
                final_generation = _on_off_database_generation_sha256(
                    database_authority=final_authority,
                    source_calls=final_source_calls,
                    pairs=final_pairs,
                )
            _close_snapshot_concurrency_tripwire(
                connection,
                snapshot_transaction_id=final_transaction_id,
            )
            if (
                final_authority != initial_authority
                or final_authority is initial_authority
                or final_source_calls != initial_source_calls
                or final_pairs != initial_pairs
                or final_generation != initial_generation
            ):
                _fail("W2 global receipt or current generation changed across snapshots")
            return _build_on_off_database_snapshot(
                database_authority=final_authority,
                source_calls=final_source_calls,
            )
    except W2DatabaseAuthorityError:
        raise
    except _InternalAuthorityError as exc:
        raise W2DatabaseAuthorityError(str(exc)) from None
    except Exception:
        raise W2DatabaseAuthorityError(
            "W2 on/off database snapshot failed exact sanitized dependency replay"
        ) from None
