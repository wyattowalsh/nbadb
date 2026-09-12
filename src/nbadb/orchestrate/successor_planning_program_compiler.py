"""Typed semantic storage and compilation for successor planning.

The planning runtime and the deterministic program driver share this module as
the sole authority for the normalized semantic tables stored in the private
planning DuckDB.  Values never appear in the path-free planning manifest or in
member envelopes: they are reloaded here from the descriptor-bound database,
strictly normalized, and hashed again before they can influence a provider
dispatch.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Final, cast

from nbadb.contracts.staging_route_contract import (
    StagingRouteContract,
    staging_route_contract_bundle,
)
from nbadb.core.types import VIDEO_CONTEXT_MEASURES, classify_season_type_availability
from nbadb.orchestrate.cume_workload_contract import CumeEntityKind, CumeWorkloadValue
from nbadb.orchestrate.extraction_contract import matching_support_rules
from nbadb.orchestrate.planning import (
    CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT,
    PLAYER_TEAM_SEASON_WORKLOAD_ENDPOINTS,
    cume_workload_execution_params,
    executable_entries_by_pattern,
)
from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDataMember,
    PlanningDispatchPhase,
    SealedProviderDispatch,
    canonical_planning_json_bytes,
    canonical_planning_sha256,
)
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticDescriptor,
    PlanningSemanticKind,
)
from nbadb.orchestrate.successor_update_contract import (
    CallMutability,
    RequestedRouteScope,
    SuccessorUpdateMode,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    import duckdb

__all__ = [
    "SUCCESSOR_PLANNING_PROGRAM_COMPILER_SCHEMA_VERSION",
    "SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE",
    "SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE",
    "PlanningSemanticMemberAuthority",
    "PlanningSemanticPartitionValues",
    "CompiledSuccessorPlanningProgram",
    "SuccessorPlanningSemanticWriteTransaction",
    "SuccessorPlanningProgramCompilerError",
    "compile_successor_planning_program",
    "install_successor_planning_semantic_schema",
    "read_successor_planning_semantic_registry",
    "successor_planning_database_schema_sha256",
    "successor_planning_semantic_write_transaction",
    "write_successor_planning_semantic_partition",
]

SUCCESSOR_PLANNING_PROGRAM_COMPILER_SCHEMA_VERSION: Final = 2
SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE: Final = "_successor_planning_semantic_partitions_v2"
SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE: Final = "_successor_planning_semantic_values_v2"

_MAX_VALUE_JSON_BYTES: Final = 4 * 1024
_MAX_PARTITION_JSON_BYTES: Final = 4 * 1024
_MAX_VALUES_PER_PARTITION: Final = 5_000_000
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_GAME_ID_RE = re.compile(r"[0-9]{10}")
_GAME_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TYPED_ZERO_REASON_RE = re.compile(r"[a-z0-9][a-z0-9_]{0,127}")

_PARTITIONS_DDL = f"""
CREATE TABLE IF NOT EXISTS {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE} (
    descriptor_identity_sha256 VARCHAR PRIMARY KEY,
    producing_scope_identity_sha256 VARCHAR NOT NULL,
    semantic_kind VARCHAR NOT NULL,
    partition_json VARCHAR NOT NULL,
    semantic_schema_sha256 VARCHAR NOT NULL,
    semantic_content_sha256 VARCHAR NOT NULL,
    value_count UBIGINT NOT NULL,
    typed_zero_reason_code VARCHAR
)
"""
_VALUES_DDL = f"""
CREATE TABLE IF NOT EXISTS {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE} (
    descriptor_identity_sha256 VARCHAR NOT NULL,
    ordinal UBIGINT NOT NULL,
    value_json VARCHAR NOT NULL,
    PRIMARY KEY (descriptor_identity_sha256, ordinal)
)
"""

_PARTITION_COLUMNS: Final = (
    ("descriptor_identity_sha256", "VARCHAR", True),
    ("producing_scope_identity_sha256", "VARCHAR", True),
    ("semantic_kind", "VARCHAR", True),
    ("partition_json", "VARCHAR", True),
    ("semantic_schema_sha256", "VARCHAR", True),
    ("semantic_content_sha256", "VARCHAR", True),
    ("value_count", "UBIGINT", True),
    ("typed_zero_reason_code", "VARCHAR", False),
)
_VALUE_COLUMNS: Final = (
    ("descriptor_identity_sha256", "VARCHAR", True),
    ("ordinal", "UBIGINT", True),
    ("value_json", "VARCHAR", True),
)

_VALUE_FIELDS: Final[dict[PlanningSemanticKind, tuple[tuple[str, str], ...]]] = {
    PlanningSemanticKind.GAME_DATE_INDEX: (
        ("game_date", "ascii_date"),
        ("game_id", "ascii_game_id"),
    ),
    PlanningSemanticKind.SEASON_PLAYER_UNIVERSE: (("player_id", "positive_int"),),
    PlanningSemanticKind.SEASON_TEAM_UNIVERSE: (("team_id", "positive_int"),),
    PlanningSemanticKind.CURRENT_TEAM_UNIVERSE: (("team_id", "positive_int"),),
    PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION: (
        ("player_id", "positive_int"),
        ("team_id", "positive_int"),
    ),
    PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS: (("game_id", "ascii_game_id"),),
    PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS: (("game_id", "ascii_game_id"),),
    PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS: (("game_id", "ascii_game_id"),),
    PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA: (),
}
_CUME_KINDS: Final = frozenset(
    {
        PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
        PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
    }
)
_AUXILIARY_TYPED_ZERO_REASON: Final = "no_derived_semantic_values"
_CURRENT_TEAM_ONLY_ENDPOINTS: Final = frozenset(
    {"team_details", "team_historical_leaders", "team_info_common"}
)
_LIVE_DERIVED_ENDPOINTS: Final = (
    "live_odds",
    "live_play_by_play",
    "live_box_score",
)


class SuccessorPlanningProgramCompilerError(RuntimeError):
    """Raised when semantic database authority is incomplete or ambiguous."""


def _require_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise SuccessorPlanningProgramCompilerError(f"{field_name} must be a lowercase SHA-256")
    return value


def _strict_canonical_object(encoded: object, *, label: str, max_bytes: int) -> dict[str, object]:
    if not isinstance(encoded, str):
        raise SuccessorPlanningProgramCompilerError(f"{label} must be canonical JSON text")
    try:
        raw = encoded.encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise SuccessorPlanningProgramCompilerError(f"{label} must be ASCII JSON") from exc
    if not raw or len(raw) > max_bytes:
        raise SuccessorPlanningProgramCompilerError(f"{label} byte length is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise SuccessorPlanningProgramCompilerError(
                    f"{label} contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise SuccessorPlanningProgramCompilerError(
            f"{label} contains non-finite JSON value {value}"
        )

    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except SuccessorPlanningProgramCompilerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SuccessorPlanningProgramCompilerError(f"{label} is not strict JSON") from exc
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise SuccessorPlanningProgramCompilerError(f"{label} must be a string-keyed object")
    payload = cast("dict[str, object]", decoded)
    try:
        canonical = canonical_planning_json_bytes(payload)
    except (TypeError, ValueError, RecursionError) as exc:
        raise SuccessorPlanningProgramCompilerError(f"{label} values are invalid") from exc
    if canonical != raw:
        raise SuccessorPlanningProgramCompilerError(f"{label} is not canonical JSON")
    return payload


def _canonical_text(payload: Mapping[str, object], *, label: str, max_bytes: int) -> str:
    try:
        encoded = canonical_planning_json_bytes(dict(payload))
    except (TypeError, ValueError, RecursionError) as exc:
        raise SuccessorPlanningProgramCompilerError(f"{label} values are invalid") from exc
    if not encoded or len(encoded) > max_bytes:
        raise SuccessorPlanningProgramCompilerError(f"{label} byte length is invalid")
    return encoded.decode("ascii")


def _positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise SuccessorPlanningProgramCompilerError(f"{field_name} must be a positive integer")
    return value


def _game_id(value: object) -> str:
    if not isinstance(value, str) or _GAME_ID_RE.fullmatch(value) is None:
        raise SuccessorPlanningProgramCompilerError(
            "semantic game_id must be an exact ten-digit string"
        )
    return value


def _game_date(value: object) -> str:
    if not isinstance(value, str) or _GAME_DATE_RE.fullmatch(value) is None:
        raise SuccessorPlanningProgramCompilerError(
            "semantic game_date must use exact ASCII YYYY-MM-DD"
        )
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise SuccessorPlanningProgramCompilerError(
            "semantic game_date must use exact ASCII YYYY-MM-DD"
        ) from exc
    if parsed.isoformat() != value:
        raise SuccessorPlanningProgramCompilerError(
            "semantic game_date must use exact ASCII YYYY-MM-DD"
        )
    return value


def _normalize_value(
    semantic_kind: PlanningSemanticKind,
    value: Mapping[str, object],
) -> dict[str, object]:
    fields = _VALUE_FIELDS[semantic_kind]
    expected = {name for name, _token in fields}
    if set(value) != expected:
        raise SuccessorPlanningProgramCompilerError(
            f"{semantic_kind.value} semantic value fields are invalid"
        )
    result: dict[str, object] = {}
    for name, token in fields:
        raw = value[name]
        if token == "positive_int":
            result[name] = _positive_int(raw, field_name=f"semantic {name}")
        elif token == "ascii_game_id":
            result[name] = _game_id(raw)
        elif token == "ascii_date":
            result[name] = _game_date(raw)
        else:  # pragma: no cover - closed module-owned table above
            raise AssertionError(f"unknown semantic value token {token}")
    return result


def _value_sort_key(
    semantic_kind: PlanningSemanticKind,
    value: Mapping[str, object],
) -> tuple[object, ...]:
    return tuple(value[name] for name, _token in _VALUE_FIELDS[semantic_kind])


def _normalize_values(
    semantic_kind: PlanningSemanticKind,
    values: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    if not isinstance(values, Sequence) or isinstance(values, str | bytes | bytearray):
        raise SuccessorPlanningProgramCompilerError(
            "semantic values must be a bounded ordered sequence"
        )
    if len(values) > _MAX_VALUES_PER_PARTITION:
        raise SuccessorPlanningProgramCompilerError("semantic value count exceeds the hard limit")
    if semantic_kind is PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA and values:
        raise SuccessorPlanningProgramCompilerError("auxiliary semantic partitions must be empty")
    normalized: list[dict[str, object]] = []
    seen: set[bytes] = set()
    for value in values:
        if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
            raise SuccessorPlanningProgramCompilerError(
                "semantic value must be a string-keyed object"
            )
        item = _normalize_value(semantic_kind, value)
        encoded = canonical_planning_json_bytes(item)
        if len(encoded) > _MAX_VALUE_JSON_BYTES:
            raise SuccessorPlanningProgramCompilerError(
                "semantic value exceeds the hard byte limit"
            )
        if encoded in seen:
            if semantic_kind in _CUME_KINDS:
                raise SuccessorPlanningProgramCompilerError(
                    "cumulative semantic values contain duplicate game IDs"
                )
            continue
        seen.add(encoded)
        normalized.append(item)
    if semantic_kind not in _CUME_KINDS:
        normalized.sort(key=lambda item: _value_sort_key(semantic_kind, item))
    return tuple(normalized)


def _semantic_schema_sha256(semantic_kind: PlanningSemanticKind) -> str:
    return canonical_planning_sha256(
        {
            "domain": "nbadb.successor-planning-semantic.schema.v2",
            "semantic_kind": semantic_kind.value,
            "fields": [
                {"name": name, "type": type_token}
                for name, type_token in _VALUE_FIELDS[semantic_kind]
            ],
        }
    )


def _semantic_content_sha256(
    *,
    semantic_kind: PlanningSemanticKind,
    partition: Mapping[str, object],
    producing_scope_identity_sha256: str,
    values: Sequence[Mapping[str, object]],
) -> str:
    return canonical_planning_sha256(
        {
            "domain": "nbadb.successor-planning-semantic-content.v2",
            "semantic_kind": semantic_kind.value,
            "partition": dict(partition),
            "producing_scope_identity_sha256": producing_scope_identity_sha256,
            "values": [dict(item) for item in values],
        }
    )


def _table_info(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
) -> tuple[tuple[str, str, bool, bool], ...]:
    try:
        rows = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    except Exception as exc:  # pragma: no cover - backend class is not stable API
        raise SuccessorPlanningProgramCompilerError(
            f"cannot inspect semantic table {table_name}"
        ) from exc
    return tuple((str(row[1]), str(row[2]).upper(), bool(row[3]), bool(row[5])) for row in rows)


def _validate_table_schema(connection: duckdb.DuckDBPyConnection) -> None:
    expected = (
        (SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE, _PARTITION_COLUMNS, {0}),
        (SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE, _VALUE_COLUMNS, {0, 1}),
    )
    for table_name, columns, primary_indexes in expected:
        observed = _table_info(connection, table_name)
        expected_observed = tuple(
            (name, data_type, not_null, index in primary_indexes)
            for index, (name, data_type, not_null) in enumerate(columns)
        )
        if observed != expected_observed:
            raise SuccessorPlanningProgramCompilerError(
                f"semantic table {table_name} differs from exact schema v2"
            )


def successor_planning_database_schema_sha256(
    connection: duckdb.DuckDBPyConnection,
) -> str:
    """Measure the complete observed private planning DuckDB schema.

    The digest binds every non-internal schema, table, ordered column, type,
    nullability, default, and constraint.  Opaque journal/staging tables are
    therefore retained as exact database identity without becoming compiler
    semantics.  External views and attached user databases fail closed.
    """

    try:
        databases = connection.execute(
            """
            SELECT database_name, path, type, readonly, encrypted
            FROM duckdb_databases()
            WHERE NOT internal
            ORDER BY database_name
            """
        ).fetchall()
        current_row = connection.execute("SELECT current_database()").fetchone()
        if current_row is None:
            raise SuccessorPlanningProgramCompilerError(
                "planning database current identity is unavailable"
            )
        current_name = current_row[0]
        if len(databases) != 1 or databases[0][0] != current_name:
            raise SuccessorPlanningProgramCompilerError(
                "planning database has an attached non-internal database"
            )
        views = connection.execute(
            """
            SELECT database_name, schema_name, view_name, temporary, sql, is_bound
            FROM duckdb_views()
            WHERE NOT internal
            ORDER BY database_name, schema_name, view_name
            """
        ).fetchall()
        if views:
            raise SuccessorPlanningProgramCompilerError(
                "planning database contains a non-internal view"
            )
        schemas = connection.execute(
            """
            SELECT schema_name
            FROM duckdb_schemas()
            WHERE database_name = current_database()
            ORDER BY database_name, schema_name
            """
        ).fetchall()
        tables = connection.execute(
            """
            SELECT schema_name, table_name, temporary,
                   has_primary_key, column_count, index_count,
                   check_constraint_count
            FROM duckdb_tables()
            WHERE NOT internal AND database_name = current_database()
            ORDER BY database_name, schema_name, table_name
            """
        ).fetchall()
        columns = connection.execute(
            """
            SELECT schema_name, table_name, column_name,
                   column_index, column_default, is_nullable, data_type,
                   character_maximum_length, numeric_precision,
                   numeric_precision_radix, numeric_scale
            FROM duckdb_columns()
            WHERE NOT internal AND database_name = current_database()
            ORDER BY database_name, schema_name, table_name, column_index
            """
        ).fetchall()
        constraints = connection.execute(
            """
            SELECT schema_name, table_name, constraint_index,
                   constraint_type, constraint_text, expression,
                   constraint_column_indexes, constraint_column_names,
                   referenced_table, referenced_column_names
            FROM duckdb_constraints()
            WHERE database_name = current_database()
            ORDER BY database_name, schema_name, table_name, constraint_index
            """
        ).fetchall()
    except SuccessorPlanningProgramCompilerError:
        raise
    except Exception as exc:  # pragma: no cover - backend class is not stable API
        raise SuccessorPlanningProgramCompilerError(
            "cannot inspect complete planning database schema"
        ) from exc

    def json_value(value: object) -> object:
        if isinstance(value, tuple | list):
            return [json_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): json_value(item) for key, item in sorted(value.items())}
        if value is None or isinstance(value, str | int | float | bool):
            return value
        return str(value)

    return canonical_planning_sha256(
        {
            "domain": "nbadb.successor-planning-database-schema.v2",
            "schemas": [list(map(json_value, row)) for row in schemas],
            "tables": [list(map(json_value, row)) for row in tables],
            "columns": [list(map(json_value, row)) for row in columns],
            "constraints": [list(map(json_value, row)) for row in constraints],
        }
    )


def install_successor_planning_semantic_schema(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Install and exact-validate the two normalized semantic tables."""

    try:
        connection.execute(_PARTITIONS_DDL)
        connection.execute(_VALUES_DDL)
    except Exception as exc:  # pragma: no cover - backend class is not stable API
        raise SuccessorPlanningProgramCompilerError(
            "cannot install successor planning semantic schema v2"
        ) from exc
    _validate_table_schema(connection)


@dataclass(slots=True)
class SuccessorPlanningSemanticWriteTransaction:
    """Capability proving the caller owns the active semantic write transaction."""

    connection: duckdb.DuckDBPyConnection
    _active: bool = True

    def require_active(self) -> duckdb.DuckDBPyConnection:
        if not self._active:
            raise SuccessorPlanningProgramCompilerError(
                "semantic write transaction is no longer active"
            )
        return self.connection


@contextmanager
def successor_planning_semantic_write_transaction(
    connection: duckdb.DuckDBPyConnection,
) -> Iterator[SuccessorPlanningSemanticWriteTransaction]:
    """Own one transaction shared by staging, journal, and semantic writes.

    Runtime callers must perform the provider-call staging replacement and
    journal completion on ``transaction.connection`` inside this same context.
    A failure in any step rolls back every semantic partition/value row rather
    than leaving partial authority in the database snapshot.
    """

    try:
        connection.execute("BEGIN TRANSACTION")
    except Exception as exc:  # pragma: no cover - backend class is not stable API
        raise SuccessorPlanningProgramCompilerError(
            "cannot begin successor planning semantic write transaction"
        ) from exc
    transaction = SuccessorPlanningSemanticWriteTransaction(connection=connection)
    try:
        yield transaction
    except BaseException:
        transaction._active = False
        try:
            connection.execute("ROLLBACK")
        except Exception as rollback_exc:  # pragma: no cover - catastrophic backend state
            raise SuccessorPlanningProgramCompilerError(
                "cannot roll back successor planning semantic write transaction"
            ) from rollback_exc
        raise
    else:
        transaction._active = False
        try:
            connection.execute("COMMIT")
        except Exception as exc:  # pragma: no cover - backend class is not stable API
            with suppress(Exception):
                connection.execute("ROLLBACK")
            raise SuccessorPlanningProgramCompilerError(
                "cannot commit successor planning semantic write transaction"
            ) from exc


@dataclass(frozen=True, slots=True)
class PlanningSemanticMemberAuthority:
    """One committed member plus the route and receipt that produced it."""

    member: PlanningDataMember
    producing_scope: RequestedRouteScope
    logical_call_receipt_sha256: str
    provider_authority_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.member, PlanningDataMember):
            raise SuccessorPlanningProgramCompilerError("semantic authority member is invalid")
        if not isinstance(self.producing_scope, RequestedRouteScope):
            raise SuccessorPlanningProgramCompilerError(
                "semantic authority producing scope is invalid"
            )
        if self.member.producing_scope_sha256 != self.producing_scope.identity_sha256:
            raise SuccessorPlanningProgramCompilerError(
                "semantic authority member differs from its producing scope"
            )
        _require_sha256(
            self.logical_call_receipt_sha256,
            field_name="logical_call_receipt_sha256",
        )
        _require_sha256(
            self.provider_authority_sha256,
            field_name="provider_authority_sha256",
        )
        route = staging_route_contract_bundle().by_route_id.get(self.producing_scope.route_id)
        if (
            route is None
            or route.endpoint_name != self.producing_scope.endpoint_name
            or route.contract_sha256 != self.producing_scope.route_contract_sha256
            or route.provider_authority_sha256 != self.provider_authority_sha256
        ):
            raise SuccessorPlanningProgramCompilerError(
                "semantic authority differs from current route provider authority"
            )

    @property
    def member_identity_sha256(self) -> str:
        return self.member.identity_sha256

    @property
    def descriptor_identity_sha256(self) -> str:
        return self.member.semantic.identity_sha256


@dataclass(frozen=True, slots=True)
class PlanningSemanticPartitionValues:
    """Revalidated database values for one exact committed semantic member."""

    authority: PlanningSemanticMemberAuthority
    values: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.authority, PlanningSemanticMemberAuthority):
            raise SuccessorPlanningProgramCompilerError(
                "semantic partition member authority is invalid"
            )
        normalized = _normalize_values(self.authority.member.semantic.semantic_kind, self.values)
        if tuple(dict(item) for item in self.values) != normalized:
            raise SuccessorPlanningProgramCompilerError(
                "semantic partition values are not in canonical database order"
            )
        object.__setattr__(
            self,
            "values",
            tuple(MappingProxyType(dict(item)) for item in normalized),
        )


def write_successor_planning_semantic_partition(
    transaction: SuccessorPlanningSemanticWriteTransaction,
    *,
    producing_scope: RequestedRouteScope,
    semantic_kind: PlanningSemanticKind,
    partition: Mapping[str, object],
    values: Sequence[Mapping[str, object]],
    typed_zero_reason_code: str | None,
) -> PlanningSemanticDescriptor:
    """Normalize and append one exact semantic partition to the planning DB."""

    if not isinstance(transaction, SuccessorPlanningSemanticWriteTransaction):
        raise SuccessorPlanningProgramCompilerError(
            "semantic writes require a caller-owned transaction capability"
        )
    connection = transaction.require_active()
    if not isinstance(producing_scope, RequestedRouteScope):
        raise SuccessorPlanningProgramCompilerError("producing_scope must be exact route authority")
    if not isinstance(semantic_kind, PlanningSemanticKind):
        raise SuccessorPlanningProgramCompilerError("semantic_kind is invalid")
    if not isinstance(partition, Mapping) or not all(isinstance(key, str) for key in partition):
        raise SuccessorPlanningProgramCompilerError("semantic partition must be an object")
    normalized_values = _normalize_values(semantic_kind, values)
    if normalized_values:
        if typed_zero_reason_code is not None:
            raise SuccessorPlanningProgramCompilerError(
                "nonempty semantic partition cannot claim typed zero"
            )
    else:
        expected_reason = (
            _AUXILIARY_TYPED_ZERO_REASON
            if semantic_kind is PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA
            else typed_zero_reason_code
        )
        if (
            not isinstance(expected_reason, str)
            or _TYPED_ZERO_REASON_RE.fullmatch(expected_reason) is None
            or typed_zero_reason_code != expected_reason
        ):
            raise SuccessorPlanningProgramCompilerError(
                "empty semantic partition requires its exact typed-zero reason"
            )
    descriptor = PlanningSemanticDescriptor.from_partition(
        semantic_kind=semantic_kind,
        partition=partition,
        semantic_schema_sha256=_semantic_schema_sha256(semantic_kind),
        semantic_content_sha256=_semantic_content_sha256(
            semantic_kind=semantic_kind,
            partition=partition,
            producing_scope_identity_sha256=producing_scope.identity_sha256,
            values=normalized_values,
        ),
        value_count=len(normalized_values),
        typed_zero_reason_code=typed_zero_reason_code,
    )
    partition_json = _canonical_text(
        descriptor.partition,
        label="semantic partition",
        max_bytes=_MAX_PARTITION_JSON_BYTES,
    )
    try:
        connection.execute(
            f"""
            INSERT INTO {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE}
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                descriptor.identity_sha256,
                producing_scope.identity_sha256,
                semantic_kind.value,
                partition_json,
                descriptor.semantic_schema_sha256,
                descriptor.semantic_content_sha256,
                descriptor.value_count,
                descriptor.typed_zero_reason_code,
            ],
        )
        for ordinal, value in enumerate(normalized_values):
            connection.execute(
                f"""
                INSERT INTO {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE} VALUES (?, ?, ?)
                """,
                [
                    descriptor.identity_sha256,
                    ordinal,
                    _canonical_text(
                        value,
                        label="semantic value",
                        max_bytes=_MAX_VALUE_JSON_BYTES,
                    ),
                ],
            )
    except Exception as exc:  # pragma: no cover - backend class is not stable API
        raise SuccessorPlanningProgramCompilerError(
            "cannot append successor planning semantic partition"
        ) from exc
    return descriptor


def read_successor_planning_semantic_registry(
    connection: duckdb.DuckDBPyConnection,
    *,
    authorities: tuple[PlanningSemanticMemberAuthority, ...],
) -> tuple[PlanningSemanticPartitionValues, ...]:
    """Reconcile the complete semantic registry with committed member authority."""

    _validate_table_schema(connection)
    if type(authorities) is not tuple or not authorities:
        raise SuccessorPlanningProgramCompilerError(
            "semantic registry requires nonempty committed authority"
        )
    if any(not isinstance(item, PlanningSemanticMemberAuthority) for item in authorities):
        raise SuccessorPlanningProgramCompilerError("semantic registry authority is invalid")
    by_descriptor = {item.descriptor_identity_sha256: item for item in authorities}
    if len(by_descriptor) != len(authorities):
        raise SuccessorPlanningProgramCompilerError(
            "semantic registry contains duplicate descriptor authority"
        )
    try:
        partition_rows = connection.execute(
            f"""
            SELECT descriptor_identity_sha256, producing_scope_identity_sha256,
                   semantic_kind, partition_json, semantic_schema_sha256,
                   semantic_content_sha256, value_count, typed_zero_reason_code
            FROM {SUCCESSOR_PLANNING_SEMANTIC_PARTITIONS_TABLE}
            ORDER BY descriptor_identity_sha256
            """
        ).fetchall()
        value_rows = connection.execute(
            f"""
            SELECT descriptor_identity_sha256, ordinal, value_json
            FROM {SUCCESSOR_PLANNING_SEMANTIC_VALUES_TABLE}
            ORDER BY descriptor_identity_sha256, ordinal
            """
        ).fetchall()
    except Exception as exc:  # pragma: no cover - backend class is not stable API
        raise SuccessorPlanningProgramCompilerError(
            "cannot read successor planning semantic registry"
        ) from exc
    observed_descriptors = {str(row[0]) for row in partition_rows}
    if observed_descriptors != set(by_descriptor) or len(partition_rows) != len(by_descriptor):
        raise SuccessorPlanningProgramCompilerError(
            "semantic partition registry differs from committed member authority"
        )
    values_by_descriptor: dict[str, list[tuple[int, dict[str, object]]]] = {}
    for raw_descriptor, raw_ordinal, raw_json in value_rows:
        descriptor_identity = _require_sha256(
            raw_descriptor,
            field_name="semantic value descriptor identity",
        )
        if descriptor_identity not in by_descriptor:
            raise SuccessorPlanningProgramCompilerError(
                "semantic values contain a foreign or orphan descriptor"
            )
        if type(raw_ordinal) is not int or raw_ordinal < 0:
            raise SuccessorPlanningProgramCompilerError("semantic value ordinal is invalid")
        decoded = _strict_canonical_object(
            raw_json,
            label="semantic value",
            max_bytes=_MAX_VALUE_JSON_BYTES,
        )
        values_by_descriptor.setdefault(descriptor_identity, []).append((raw_ordinal, decoded))

    result: list[PlanningSemanticPartitionValues] = []
    for row in partition_rows:
        descriptor_identity = _require_sha256(row[0], field_name="semantic descriptor identity")
        authority = by_descriptor[descriptor_identity]
        descriptor = authority.member.semantic
        if row[1] != authority.producing_scope.identity_sha256:
            raise SuccessorPlanningProgramCompilerError(
                "semantic partition producing scope differs from committed authority"
            )
        if row[2] != descriptor.semantic_kind.value:
            raise SuccessorPlanningProgramCompilerError(
                "semantic partition kind differs from committed authority"
            )
        partition = _strict_canonical_object(
            row[3],
            label="semantic partition",
            max_bytes=_MAX_PARTITION_JSON_BYTES,
        )
        if partition != descriptor.partition:
            raise SuccessorPlanningProgramCompilerError(
                "semantic partition body differs from committed descriptor"
            )
        if (
            row[4] != descriptor.semantic_schema_sha256
            or row[5] != descriptor.semantic_content_sha256
            or row[6] != descriptor.value_count
            or row[7] != descriptor.typed_zero_reason_code
            or descriptor.semantic_schema_sha256
            != _semantic_schema_sha256(descriptor.semantic_kind)
        ):
            raise SuccessorPlanningProgramCompilerError(
                "semantic partition identities or count differ from committed descriptor"
            )
        indexed = values_by_descriptor.get(descriptor_identity, [])
        ordinals = [ordinal for ordinal, _value in indexed]
        if ordinals != list(range(len(indexed))) or len(indexed) != descriptor.value_count:
            raise SuccessorPlanningProgramCompilerError(
                "semantic value ordinals or count differ from committed descriptor"
            )
        raw_values = tuple(value for _ordinal, value in indexed)
        normalized = _normalize_values(descriptor.semantic_kind, raw_values)
        if tuple(dict(value) for value in raw_values) != normalized:
            raise SuccessorPlanningProgramCompilerError(
                "semantic values differ from canonical order or normalization"
            )
        expected_content = _semantic_content_sha256(
            semantic_kind=descriptor.semantic_kind,
            partition=partition,
            producing_scope_identity_sha256=authority.producing_scope.identity_sha256,
            values=normalized,
        )
        if expected_content != descriptor.semantic_content_sha256:
            raise SuccessorPlanningProgramCompilerError(
                "semantic content digest differs from reloaded database values"
            )
        rebuilt = PlanningSemanticDescriptor.from_partition(
            semantic_kind=descriptor.semantic_kind,
            partition=partition,
            semantic_schema_sha256=descriptor.semantic_schema_sha256,
            semantic_content_sha256=expected_content,
            value_count=len(normalized),
            typed_zero_reason_code=descriptor.typed_zero_reason_code,
        )
        if rebuilt.identity_sha256 != descriptor_identity:
            raise SuccessorPlanningProgramCompilerError(
                "semantic descriptor identity differs after database readback"
            )
        result.append(
            PlanningSemanticPartitionValues(
                authority=authority,
                values=tuple(normalized),
            )
        )
    return tuple(sorted(result, key=lambda item: item.authority.descriptor_identity_sha256))


@dataclass(frozen=True, slots=True)
class CompiledSuccessorPlanningProgram:
    """One canonical phase-local requested-scope and dispatch program."""

    phase: PlanningDispatchPhase
    requested_route_scopes: tuple[RequestedRouteScope, ...]
    sealed_dispatches: tuple[SealedProviderDispatch, ...]

    schema_version: ClassVar[int] = SUCCESSOR_PLANNING_PROGRAM_COMPILER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.phase not in {
            PlanningDispatchPhase.PLANNING_WAVE_1,
            PlanningDispatchPhase.UPDATE,
        }:
            raise SuccessorPlanningProgramCompilerError(
                "compiled program phase must be wave 1 or update"
            )
        scopes = self.requested_route_scopes
        if (
            type(scopes) is not tuple
            or not scopes
            or any(not isinstance(scope, RequestedRouteScope) for scope in scopes)
            or scopes != tuple(sorted(scopes, key=lambda scope: scope.identity_sha256))
            or len({scope.identity_sha256 for scope in scopes}) != len(scopes)
        ):
            raise SuccessorPlanningProgramCompilerError(
                "compiled requested route scope inventory is not canonical"
            )
        dispatches = self.sealed_dispatches
        if (
            type(dispatches) is not tuple
            or not dispatches
            or any(dispatch.phase is not self.phase for dispatch in dispatches)
            or len({dispatch.identity_sha256 for dispatch in dispatches}) != len(dispatches)
        ):
            raise SuccessorPlanningProgramCompilerError(
                "compiled sealed dispatch inventory is invalid"
            )
        scope_by_id = {scope.identity_sha256: scope for scope in scopes}
        dispatched: list[str] = []
        for dispatch in dispatches:
            if not dispatch.dependency_identity_sha256s:
                raise SuccessorPlanningProgramCompilerError(
                    "compiled dispatch must bind exact semantic members"
                )
            for position, scope_id in enumerate(dispatch.requested_scope_identity_sha256s):
                scope = scope_by_id.get(scope_id)
                if (
                    scope is None
                    or scope.endpoint_name != dispatch.endpoint_name
                    or scope.parameters != dispatch.parameters
                    or scope.route_id != dispatch.staging_route_ids[position]
                ):
                    raise SuccessorPlanningProgramCompilerError(
                        "compiled dispatch differs from requested scope authority"
                    )
                dispatched.append(scope_id)
        if len(dispatched) != len(set(dispatched)) or set(dispatched) != set(scope_by_id):
            raise SuccessorPlanningProgramCompilerError(
                "compiled dispatches do not exactly cover requested scopes"
            )


@dataclass(slots=True)
class _PendingLogicalCall:
    endpoint_name: str
    parameters: dict[str, Any]
    routes: dict[str, StagingRouteContract]
    dependency_identity_sha256s: set[str]
    planning_mirror_authority: bool = False


def _semantic_key(item: PlanningSemanticPartitionValues) -> tuple[object, ...]:
    descriptor = item.authority.member.semantic
    return (descriptor.semantic_kind, *descriptor.partition_items)


def _index_semantic_registry(
    registry: tuple[PlanningSemanticPartitionValues, ...],
) -> dict[PlanningSemanticKind, tuple[PlanningSemanticPartitionValues, ...]]:
    if type(registry) is not tuple or not registry:
        raise SuccessorPlanningProgramCompilerError(
            "program compilation requires a nonempty semantic registry"
        )
    result: dict[PlanningSemanticKind, list[PlanningSemanticPartitionValues]] = {}
    keys: set[tuple[object, ...]] = set()
    member_identities: set[str] = set()
    for item in registry:
        if not isinstance(item, PlanningSemanticPartitionValues):
            raise SuccessorPlanningProgramCompilerError(
                "program semantic registry contains an invalid value"
            )
        key = _semantic_key(item)
        if key in keys:
            raise SuccessorPlanningProgramCompilerError(
                "program semantic registry contains duplicate partition authority"
            )
        member_identity = item.authority.member_identity_sha256
        if member_identity in member_identities:
            raise SuccessorPlanningProgramCompilerError(
                "one planning member cannot authorize multiple semantic partitions"
            )
        keys.add(key)
        member_identities.add(member_identity)
        result.setdefault(item.authority.member.semantic.semantic_kind, []).append(item)
    return {
        kind: tuple(
            sorted(
                values,
                key=lambda item: item.authority.descriptor_identity_sha256,
            )
        )
        for kind, values in result.items()
    }


def _route_surface() -> dict[str, dict[str, tuple[StagingRouteContract, ...]]]:
    bundle = staging_route_contract_bundle()
    result: dict[str, dict[str, list[StagingRouteContract]]] = {}
    seen: set[str] = set()
    for pattern, entries in executable_entries_by_pattern().items():
        for entry in entries:
            route_id = f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
            route = bundle.by_route_id.get(route_id)
            if (
                route is None
                or route.endpoint_name != entry.endpoint_name
                or route.param_pattern != pattern
            ):
                raise SuccessorPlanningProgramCompilerError(
                    "executable staging surface differs from current route authority"
                )
            if route_id in seen:
                raise SuccessorPlanningProgramCompilerError(
                    "executable staging surface contains a duplicate route"
                )
            seen.add(route_id)
            result.setdefault(pattern, {}).setdefault(route.endpoint_name, []).append(route)
    return {
        pattern: {
            endpoint: tuple(sorted(routes, key=lambda route: route.ordinal))
            for endpoint, routes in endpoints.items()
        }
        for pattern, endpoints in result.items()
    }


def _all_current_endpoint_routes(endpoint_name: str) -> tuple[StagingRouteContract, ...]:
    routes = tuple(
        route
        for route in staging_route_contract_bundle().routes
        if route.endpoint_name == endpoint_name
    )
    if not routes:
        raise SuccessorPlanningProgramCompilerError(
            f"derived endpoint {endpoint_name!r} has no current route authority"
        )
    return tuple(sorted(routes, key=lambda route: route.ordinal))


def _season_start(season: str) -> int:
    try:
        return int(season[:4])
    except (TypeError, ValueError, IndexError) as exc:
        raise SuccessorPlanningProgramCompilerError(
            "compiled semantic season is not exact YYYY-YY"
        ) from exc


def _route_is_supported(
    route: StagingRouteContract,
    *,
    season: str | None,
    season_type: str | None,
) -> bool:
    if season is None:
        start = None
    else:
        start = _season_start(season)
        if route.min_season is not None and start < route.min_season:
            return False
    if route.season_type_capability == "supported":
        if start is None or season_type is None:
            return False
        if season_type not in route.supported_season_types:
            return False
        if classify_season_type_availability(start, season_type) != "supported":
            return False
    elif season_type is not None:
        return False
    return not any(
        rule.classification == "contract_blocked"
        for rule in matching_support_rules(
            endpoint_name=route.endpoint_name,
            patterns=(route.param_pattern,),
            season_start=start,
            season_end=start,
        )
    )


def _parameters_key(endpoint_name: str, parameters: Mapping[str, Any]) -> tuple[str, str]:
    return (
        endpoint_name,
        canonical_planning_sha256(
            {
                "domain": "nbadb.successor-planning-compiler.logical-parameters.v2",
                "parameters": dict(parameters),
            }
        ),
    )


def _add_call(
    pending: dict[tuple[str, str], _PendingLogicalCall],
    *,
    endpoint_name: str,
    parameters: Mapping[str, Any],
    routes: tuple[StagingRouteContract, ...],
    dependency_identity_sha256s: Sequence[str],
    skip_existing: bool = False,
    planning_mirror_authority: bool = False,
) -> None:
    if not routes:
        return
    dependencies = {
        _require_sha256(value, field_name="compiled semantic member dependency")
        for value in dependency_identity_sha256s
    }
    if not dependencies:
        raise SuccessorPlanningProgramCompilerError(
            f"compiled logical call {endpoint_name!r} lacks semantic authority"
        )
    key = _parameters_key(endpoint_name, parameters)
    existing = pending.get(key)
    if existing is not None and skip_existing:
        return
    if existing is not None and existing.planning_mirror_authority:
        if any(route.route_id not in existing.routes for route in routes):
            raise SuccessorPlanningProgramCompilerError(
                "derived logical call widens a mandatory planning mirror"
            )
        return
    if existing is not None and planning_mirror_authority:
        raise SuccessorPlanningProgramCompilerError(
            "mandatory planning mirror collides with an earlier derived call"
        )
    if existing is None:
        pending[key] = _PendingLogicalCall(
            endpoint_name=endpoint_name,
            parameters=dict(parameters),
            routes={route.route_id: route for route in routes},
            dependency_identity_sha256s=dependencies,
            planning_mirror_authority=planning_mirror_authority,
        )
        return
    if existing.parameters != dict(parameters):
        raise SuccessorPlanningProgramCompilerError("compiled logical parameter identity collides")
    for route in routes:
        other = existing.routes.get(route.route_id)
        if other is not None and other.contract_sha256 != route.contract_sha256:
            raise SuccessorPlanningProgramCompilerError(
                "compiled logical call route contract collides"
            )
        existing.routes[route.route_id] = route
    existing.dependency_identity_sha256s.update(dependencies)


def _add_planning_redispatches(
    pending: dict[tuple[str, str], _PendingLogicalCall],
    *,
    request: SuccessorPlanningRequest,
    registry: tuple[PlanningSemanticPartitionValues, ...],
) -> None:
    scopes_by_call: dict[tuple[str, str], list[RequestedRouteScope]] = {}
    for scope in request.requested_planning_scopes:
        scopes_by_call.setdefault((scope.endpoint_name, scope.scope_sha256), []).append(scope)
    members_by_scope: dict[str, set[str]] = {}
    for item in registry:
        scope_id = item.authority.producing_scope.identity_sha256
        members_by_scope.setdefault(scope_id, set()).add(item.authority.member_identity_sha256)
    current = staging_route_contract_bundle().by_route_id
    for (_endpoint, _scope_digest), scopes in sorted(
        scopes_by_call.items(),
        key=lambda item: min(scope.identity_sha256 for scope in item[1]),
    ):
        first = scopes[0]
        routes: list[StagingRouteContract] = []
        dependencies: set[str] = set()
        for scope in scopes:
            if scope.mutability is not CallMutability.MUTABLE:
                continue
            route = current.get(scope.route_id)
            if (
                route is None
                or route.endpoint_name != scope.endpoint_name
                or route.contract_sha256 != scope.route_contract_sha256
            ):
                raise SuccessorPlanningProgramCompilerError(
                    "planning re-dispatch route differs from current authority"
                )
            scope_members = members_by_scope.get(scope.identity_sha256)
            if not scope_members:
                raise SuccessorPlanningProgramCompilerError(
                    "planning re-dispatch lacks every emitted member dependency"
                )
            routes.append(route)
            dependencies.update(scope_members)
        _add_call(
            pending,
            endpoint_name=first.endpoint_name,
            parameters=first.parameters,
            routes=tuple(sorted(routes, key=lambda route: route.ordinal)),
            dependency_identity_sha256s=tuple(sorted(dependencies)),
            planning_mirror_authority=True,
        )

    wave_1_by_call: dict[tuple[str, str], list[PlanningSemanticPartitionValues]] = {}
    for item in registry:
        if item.authority.member.wave_index != 1:
            continue
        scope = item.authority.producing_scope
        if scope.mutability is not CallMutability.MUTABLE:
            raise SuccessorPlanningProgramCompilerError(
                "wave 1 semantic authority must retain mutable foundation scope"
            )
        wave_1_by_call.setdefault((scope.endpoint_name, scope.scope_sha256), []).append(item)
    for (_endpoint, _scope_digest), items in sorted(
        wave_1_by_call.items(),
        key=lambda item: min(value.authority.producing_scope.identity_sha256 for value in item[1]),
    ):
        first = items[0].authority.producing_scope
        routes: dict[str, StagingRouteContract] = {}
        dependencies: set[str] = set()
        for item in items:
            scope = item.authority.producing_scope
            if (
                scope.endpoint_name != first.endpoint_name
                or scope.scope_sha256 != first.scope_sha256
                or scope.parameters != first.parameters
            ):
                raise SuccessorPlanningProgramCompilerError(
                    "wave 1 semantic logical-call authority is inconsistent"
                )
            route = current.get(scope.route_id)
            if (
                route is None
                or route.endpoint_name != scope.endpoint_name
                or route.contract_sha256 != scope.route_contract_sha256
            ):
                raise SuccessorPlanningProgramCompilerError(
                    "wave 1 planning re-dispatch route differs from current authority"
                )
            routes[route.route_id] = route
            dependencies.add(item.authority.member_identity_sha256)
        _add_call(
            pending,
            endpoint_name=first.endpoint_name,
            parameters=first.parameters,
            routes=tuple(sorted(routes.values(), key=lambda route: route.ordinal)),
            dependency_identity_sha256s=tuple(sorted(dependencies)),
            planning_mirror_authority=True,
        )


def _member_ids(items: Sequence[PlanningSemanticPartitionValues]) -> tuple[str, ...]:
    return tuple(sorted(item.authority.member_identity_sha256 for item in items))


def _partition_map(
    items: Sequence[PlanningSemanticPartitionValues],
    *keys: str,
) -> dict[tuple[object, ...], PlanningSemanticPartitionValues]:
    result: dict[tuple[object, ...], PlanningSemanticPartitionValues] = {}
    for item in items:
        partition = item.authority.member.semantic.partition
        key = tuple(partition[name] for name in keys)
        if key in result:
            raise SuccessorPlanningProgramCompilerError(
                "semantic partition join key contains duplicate authority"
            )
        result[key] = item
    return result


def _add_historical_endpoint_call(
    pending: dict[tuple[str, str], _PendingLogicalCall],
    *,
    endpoint_name: str,
    routes: tuple[StagingRouteContract, ...],
    base_parameters: Mapping[str, Any],
    season: str,
    season_type: str | None,
    dependencies: Sequence[str],
) -> None:
    supported_routes = tuple(
        route
        for route in routes
        if _route_is_supported(route, season=season, season_type=season_type)
    )
    if not supported_routes:
        return
    parameters = {**base_parameters, "season": season}
    if season_type is not None:
        parameters["season_type"] = season_type
    _add_call(
        pending,
        endpoint_name=endpoint_name,
        parameters=parameters,
        routes=supported_routes,
        dependency_identity_sha256s=dependencies,
    )


def _compile_wave_1_calls(
    *,
    semantic: dict[PlanningSemanticKind, tuple[PlanningSemanticPartitionValues, ...]],
) -> dict[tuple[str, str], _PendingLogicalCall]:
    pending: dict[tuple[str, str], _PendingLogicalCall] = {}
    game_by_pair = _partition_map(
        semantic.get(PlanningSemanticKind.GAME_DATE_INDEX, ()),
        "season",
        "season_type",
    )
    players_by_season = _partition_map(
        semantic.get(PlanningSemanticKind.SEASON_PLAYER_UNIVERSE, ()),
        "season",
    )
    teams_by_season = _partition_map(
        semantic.get(PlanningSemanticKind.SEASON_TEAM_UNIVERSE, ()),
        "season",
    )
    for (season, season_type), game_item in sorted(game_by_pair.items()):
        assert isinstance(season, str) and isinstance(season_type, str)
        player_item = players_by_season.get((season,))
        if player_item is not None:
            for value in player_item.values:
                player_id = cast("int", value["player_id"])
                _add_historical_endpoint_call(
                    pending,
                    endpoint_name="cume_stats_player_games",
                    routes=_all_current_endpoint_routes("cume_stats_player_games"),
                    base_parameters={"player_id": player_id},
                    season=season,
                    season_type=season_type,
                    dependencies=_member_ids((player_item, game_item)),
                )
        team_item = teams_by_season.get((season,))
        if team_item is not None:
            for value in team_item.values:
                team_id = cast("int", value["team_id"])
                _add_historical_endpoint_call(
                    pending,
                    endpoint_name="cume_stats_team_games",
                    routes=_all_current_endpoint_routes("cume_stats_team_games"),
                    base_parameters={"team_id": team_id},
                    season=season,
                    season_type=season_type,
                    dependencies=_member_ids((team_item, game_item)),
                )
    if not pending:
        raise SuccessorPlanningProgramCompilerError(
            "sealed wave 0 semantic partitions derive no wave 1 calls"
        )
    return pending


def _compile_update_calls(
    *,
    request: SuccessorPlanningRequest,
    registry: tuple[PlanningSemanticPartitionValues, ...],
    semantic: dict[PlanningSemanticKind, tuple[PlanningSemanticPartitionValues, ...]],
) -> dict[tuple[str, str], _PendingLogicalCall]:
    pending: dict[tuple[str, str], _PendingLogicalCall] = {}
    _add_planning_redispatches(pending, request=request, registry=registry)
    surface = _route_surface()
    auxiliary = semantic.get(PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA, ())
    if not auxiliary:
        raise SuccessorPlanningProgramCompilerError(
            "update program requires an auxiliary request/program authority"
        )
    auxiliary_dependencies = _member_ids(auxiliary)

    if request.mode is SuccessorUpdateMode.MONTHLY:
        for endpoint, routes in surface.get("static", {}).items():
            _add_call(
                pending,
                endpoint_name=endpoint,
                parameters={},
                routes=routes,
                dependency_identity_sha256s=auxiliary_dependencies,
                skip_existing=True,
            )
    elif request.mode is not SuccessorUpdateMode.DAILY:
        raise SuccessorPlanningProgramCompilerError("compiled update mode must be daily or monthly")

    game_items = semantic.get(PlanningSemanticKind.GAME_DATE_INDEX, ())
    game_by_pair = _partition_map(game_items, "season", "season_type")
    game_by_season: dict[str, list[PlanningSemanticPartitionValues]] = {}
    games_by_id: dict[str, list[PlanningSemanticPartitionValues]] = {}
    dates_by_value: dict[str, list[PlanningSemanticPartitionValues]] = {}
    daily_cutoff_date = request.cutoff_utc[:10]
    for item in game_items:
        season = cast("str", item.authority.member.semantic.partition["season"])
        game_by_season.setdefault(season, []).append(item)
        for value in item.values:
            game_date = cast("str", value["game_date"])
            if request.mode is SuccessorUpdateMode.DAILY and game_date < daily_cutoff_date:
                continue
            games_by_id.setdefault(cast("str", value["game_id"]), []).append(item)
            dates_by_value.setdefault(game_date, []).append(item)

    for endpoint, routes in surface.get("season", {}).items():
        supported_capability = {route.season_type_capability for route in routes}
        if supported_capability == {"supported"}:
            for (season, season_type), item in sorted(game_by_pair.items()):
                assert isinstance(season, str) and isinstance(season_type, str)
                _add_historical_endpoint_call(
                    pending,
                    endpoint_name=endpoint,
                    routes=routes,
                    base_parameters={},
                    season=season,
                    season_type=season_type,
                    dependencies=_member_ids((item,)),
                )
        elif supported_capability <= {"not_applicable"}:
            for season, items in sorted(game_by_season.items()):
                _add_historical_endpoint_call(
                    pending,
                    endpoint_name=endpoint,
                    routes=routes,
                    base_parameters={},
                    season=season,
                    season_type=None,
                    dependencies=_member_ids(items),
                )
        else:
            raise SuccessorPlanningProgramCompilerError(
                f"season endpoint {endpoint!r} has mixed season-type authority"
            )

    for endpoint, routes in surface.get("game", {}).items():
        for game_id, items in sorted(games_by_id.items()):
            supported_routes: list[StagingRouteContract] = []
            retained_items: dict[str, PlanningSemanticPartitionValues] = {}
            for route in routes:
                route_items = tuple(
                    item
                    for item in items
                    if _route_is_supported(
                        route,
                        season=cast("str", item.authority.member.semantic.partition["season"]),
                        season_type=(
                            cast(
                                "str",
                                item.authority.member.semantic.partition["season_type"],
                            )
                            if route.season_type_capability == "supported"
                            else None
                        ),
                    )
                )
                if route_items:
                    supported_routes.append(route)
                    retained_items.update(
                        (item.authority.member_identity_sha256, item) for item in route_items
                    )
            _add_call(
                pending,
                endpoint_name=endpoint,
                parameters={"game_id": game_id},
                routes=tuple(supported_routes),
                dependency_identity_sha256s=_member_ids(tuple(retained_items.values())),
            )
    for endpoint, routes in surface.get("date", {}).items():
        for game_date, items in sorted(dates_by_value.items()):
            supported_routes = []
            retained_items = {}
            for route in routes:
                route_items = tuple(
                    item
                    for item in items
                    if _route_is_supported(
                        route,
                        season=cast("str", item.authority.member.semantic.partition["season"]),
                        season_type=(
                            cast(
                                "str",
                                item.authority.member.semantic.partition["season_type"],
                            )
                            if route.season_type_capability == "supported"
                            else None
                        ),
                    )
                )
                if route_items:
                    supported_routes.append(route)
                    retained_items.update(
                        (item.authority.member_identity_sha256, item) for item in route_items
                    )
            _add_call(
                pending,
                endpoint_name=endpoint,
                parameters={"game_date": game_date},
                routes=tuple(supported_routes),
                dependency_identity_sha256s=_member_ids(tuple(retained_items.values())),
            )

    player_items = semantic.get(PlanningSemanticKind.SEASON_PLAYER_UNIVERSE, ())
    players_by_season = _partition_map(player_items, "season")
    players_by_id: dict[int, list[PlanningSemanticPartitionValues]] = {}
    for item in player_items:
        for value in item.values:
            players_by_id.setdefault(cast("int", value["player_id"]), []).append(item)
    for endpoint, routes in surface.get("player", {}).items():
        for player_id, items in sorted(players_by_id.items()):
            _add_call(
                pending,
                endpoint_name=endpoint,
                parameters={"player_id": player_id},
                routes=routes,
                dependency_identity_sha256s=_member_ids(items),
            )

    team_items = semantic.get(PlanningSemanticKind.SEASON_TEAM_UNIVERSE, ())
    teams_by_season = _partition_map(team_items, "season")
    teams_by_id: dict[int, list[PlanningSemanticPartitionValues]] = {}
    for item in team_items:
        for value in item.values:
            teams_by_id.setdefault(cast("int", value["team_id"]), []).append(item)
    current_items = semantic.get(PlanningSemanticKind.CURRENT_TEAM_UNIVERSE, ())
    current_by_id: dict[int, list[PlanningSemanticPartitionValues]] = {}
    for item in current_items:
        for value in item.values:
            current_by_id.setdefault(cast("int", value["team_id"]), []).append(item)
    for endpoint, routes in surface.get("team", {}).items():
        inventory = current_by_id if endpoint in _CURRENT_TEAM_ONLY_ENDPOINTS else teams_by_id
        for team_id, items in sorted(inventory.items()):
            _add_call(
                pending,
                endpoint_name=endpoint,
                parameters={"team_id": team_id},
                routes=routes,
                dependency_identity_sha256s=_member_ids(items),
            )

    for pattern, universe_by_season, entity_key, excluded in (
        (
            "player_season",
            players_by_season,
            "player_id",
            frozenset(
                {
                    "cume_stats_player_games",
                    "cume_stats_player",
                }
            ),
        ),
        (
            "team_season",
            teams_by_season,
            "team_id",
            frozenset(
                {
                    "cume_stats_team_games",
                    "cume_stats_team",
                }
            ),
        ),
    ):
        for endpoint, routes in surface.get(pattern, {}).items():
            if endpoint in excluded:
                continue
            capability = {route.season_type_capability for route in routes}
            for (season,), universe in sorted(universe_by_season.items()):
                assert isinstance(season, str)
                entity_values = universe.values
                if capability == {"supported"}:
                    pairs = [
                        (pair, game) for pair, game in game_by_pair.items() if pair[0] == season
                    ]
                    for (_pair_season, season_type), game in sorted(pairs):
                        assert isinstance(season_type, str)
                        for value in entity_values:
                            _add_historical_endpoint_call(
                                pending,
                                endpoint_name=endpoint,
                                routes=routes,
                                base_parameters={entity_key: value[entity_key]},
                                season=season,
                                season_type=season_type,
                                dependencies=_member_ids((universe, game)),
                            )
                elif capability <= {"not_applicable"}:
                    season_games = game_by_season.get(season, [])
                    if not season_games:
                        continue
                    for value in entity_values:
                        _add_historical_endpoint_call(
                            pending,
                            endpoint_name=endpoint,
                            routes=routes,
                            base_parameters={entity_key: value[entity_key]},
                            season=season,
                            season_type=None,
                            dependencies=_member_ids((universe, *season_games)),
                        )
                else:
                    raise SuccessorPlanningProgramCompilerError(
                        f"{pattern} endpoint {endpoint!r} has mixed season-type authority"
                    )

    affiliations = semantic.get(PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION, ())
    video_routes = surface.get("player_team_season", {})
    if set(video_routes) - PLAYER_TEAM_SEASON_WORKLOAD_ENDPOINTS:
        raise SuccessorPlanningProgramCompilerError(
            "player-team-season surface contains a non-workload endpoint"
        )
    for item in affiliations:
        partition = item.authority.member.semantic.partition
        season = cast("str", partition["season"])
        season_type = cast("str", partition["season_type"])
        dependencies = _member_ids((item,))
        for endpoint, routes in video_routes.items():
            supported_video_routes = tuple(
                route
                for route in routes
                if _route_is_supported(route, season=season, season_type=season_type)
            )
            for value in item.values:
                for context_measure in VIDEO_CONTEXT_MEASURES:
                    _add_call(
                        pending,
                        endpoint_name=endpoint,
                        parameters={
                            "player_id": value["player_id"],
                            "team_id": value["team_id"],
                            "season": season,
                            "season_type": season_type,
                            "context_measure": context_measure,
                        },
                        routes=supported_video_routes,
                        dependency_identity_sha256s=dependencies,
                    )

    for kind, dependent_endpoint, entity_kind in (
        (
            PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
            "cume_stats_player",
            CumeEntityKind.PLAYER,
        ),
        (
            PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
            "cume_stats_team",
            CumeEntityKind.TEAM,
        ),
    ):
        for item in semantic.get(kind, ()):
            if not item.values:
                continue
            descriptor = item.authority.member.semantic
            partition = descriptor.partition
            entity_key = f"{entity_kind.value}_id"
            workload = CumeWorkloadValue.complete(
                entity_kind=entity_kind,
                entity_id=cast("int", partition[entity_key]),
                season=cast("str", partition["season"]),
                season_type=cast("str", partition["season_type"]),
                game_ids=tuple(cast("str", value["game_id"]) for value in item.values),
                foundation_receipt_sha256=item.authority.logical_call_receipt_sha256,
                provider_authority_sha256=item.authority.provider_authority_sha256,
            )
            expected_foundation = CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT[dependent_endpoint]
            if item.authority.producing_scope.endpoint_name != expected_foundation:
                raise SuccessorPlanningProgramCompilerError(
                    "cumulative semantic member differs from its foundation endpoint"
                )
            _add_call(
                pending,
                endpoint_name=dependent_endpoint,
                parameters=cume_workload_execution_params(workload),
                routes=_all_current_endpoint_routes(dependent_endpoint),
                dependency_identity_sha256s=_member_ids((item,)),
            )

    active = semantic.get(PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS, ())
    for item in active:
        if not item.values:
            continue
        dependencies = _member_ids((item,))
        _add_call(
            pending,
            endpoint_name="live_odds",
            parameters={},
            routes=_all_current_endpoint_routes("live_odds"),
            dependency_identity_sha256s=dependencies,
        )
        for value in item.values:
            game_id = cast("str", value["game_id"])
            for endpoint in _LIVE_DERIVED_ENDPOINTS[1:]:
                _add_call(
                    pending,
                    endpoint_name=endpoint,
                    parameters={"game_id": game_id},
                    routes=_all_current_endpoint_routes(endpoint),
                    dependency_identity_sha256s=dependencies,
                )
    return pending


def _expected_wave_0_semantic_keys(
    request: SuccessorPlanningRequest,
) -> set[tuple[str, PlanningSemanticKind, tuple[tuple[str, object], ...]]]:
    result: set[tuple[str, PlanningSemanticKind, tuple[tuple[str, object], ...]]] = set()
    seasons: set[str] = set()
    common_team_scope: str | None = None
    for scope in request.requested_planning_scopes:
        parameters = scope.parameters
        if scope.endpoint_name == "league_game_log":
            season = cast("str", parameters["season"])
            season_type = cast("str", parameters["season_type"])
            seasons.add(season)
            descriptor = PlanningSemanticDescriptor.from_partition(
                semantic_kind=PlanningSemanticKind.GAME_DATE_INDEX,
                partition={"season": season, "season_type": season_type},
                semantic_schema_sha256="0" * 64,
                semantic_content_sha256="0" * 64,
                value_count=0,
                typed_zero_reason_code="shape_only",
            )
            result.add(
                (
                    scope.identity_sha256,
                    PlanningSemanticKind.GAME_DATE_INDEX,
                    descriptor.partition_items,
                )
            )
        elif scope.endpoint_name == "player_game_logs":
            season = cast("str", parameters["season"])
            season_type = cast("str", parameters["season_type"])
            descriptor = PlanningSemanticDescriptor.from_partition(
                semantic_kind=PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION,
                partition={"season": season, "season_type": season_type},
                semantic_schema_sha256="0" * 64,
                semantic_content_sha256="0" * 64,
                value_count=0,
                typed_zero_reason_code="shape_only",
            )
            result.add(
                (
                    scope.identity_sha256,
                    PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION,
                    descriptor.partition_items,
                )
            )
        elif scope.endpoint_name == "common_all_players":
            season = cast("str", parameters["season"])
            raw_current = parameters["is_only_current_season"]
            if type(raw_current) is not int or raw_current not in {0, 1}:
                raise SuccessorPlanningProgramCompilerError(
                    "planning player scope current-only flag is invalid"
                )
            descriptor = PlanningSemanticDescriptor.from_partition(
                semantic_kind=PlanningSemanticKind.SEASON_PLAYER_UNIVERSE,
                partition={"season": season, "current_only": bool(raw_current)},
                semantic_schema_sha256="0" * 64,
                semantic_content_sha256="0" * 64,
                value_count=0,
                typed_zero_reason_code="shape_only",
            )
            result.add(
                (
                    scope.identity_sha256,
                    PlanningSemanticKind.SEASON_PLAYER_UNIVERSE,
                    descriptor.partition_items,
                )
            )
        elif scope.endpoint_name == "common_team_years":
            if common_team_scope is not None and common_team_scope != scope.identity_sha256:
                raise SuccessorPlanningProgramCompilerError(
                    "planning request has more than one team-year result route"
                )
            common_team_scope = scope.identity_sha256
        elif scope.endpoint_name == "live_score_board":
            descriptor = PlanningSemanticDescriptor.from_partition(
                semantic_kind=PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
                partition={"as_of_utc": request.as_of_utc},
                semantic_schema_sha256="0" * 64,
                semantic_content_sha256="0" * 64,
                value_count=0,
                typed_zero_reason_code="shape_only",
            )
            result.add(
                (
                    scope.identity_sha256,
                    PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
                    descriptor.partition_items,
                )
            )
        else:
            raise SuccessorPlanningProgramCompilerError(
                "planning request contains an unsupported root endpoint"
            )
    if common_team_scope is None:
        raise SuccessorPlanningProgramCompilerError(
            "planning request lacks common_team_years authority"
        )
    for season in seasons:
        descriptor = PlanningSemanticDescriptor.from_partition(
            semantic_kind=PlanningSemanticKind.SEASON_TEAM_UNIVERSE,
            partition={"season": season},
            semantic_schema_sha256="0" * 64,
            semantic_content_sha256="0" * 64,
            value_count=0,
            typed_zero_reason_code="shape_only",
        )
        result.add(
            (
                common_team_scope,
                PlanningSemanticKind.SEASON_TEAM_UNIVERSE,
                descriptor.partition_items,
            )
        )
    for kind, partition in (
        (PlanningSemanticKind.CURRENT_TEAM_UNIVERSE, {"as_of_utc": request.as_of_utc}),
        (PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA, {}),
    ):
        descriptor = PlanningSemanticDescriptor.from_partition(
            semantic_kind=kind,
            partition=partition,
            semantic_schema_sha256="0" * 64,
            semantic_content_sha256="0" * 64,
            value_count=0,
            typed_zero_reason_code="shape_only",
        )
        result.add((common_team_scope, kind, descriptor.partition_items))
    return result


def _validate_compiler_topology(
    *,
    request: SuccessorPlanningRequest,
    registry: tuple[PlanningSemanticPartitionValues, ...],
    phase: PlanningDispatchPhase,
) -> None:
    expected_wave_0 = _expected_wave_0_semantic_keys(request)
    observed_wave_0 = {
        (
            item.authority.producing_scope.identity_sha256,
            item.authority.member.semantic.semantic_kind,
            item.authority.member.semantic.partition_items,
        )
        for item in registry
        if item.authority.member.wave_index == 0
    }
    if observed_wave_0 != expected_wave_0:
        raise SuccessorPlanningProgramCompilerError(
            "wave 0 semantic inventory differs from exact planning request topology"
        )
    invalid_wave = tuple(
        item
        for item in registry
        if item.authority.member.wave_index
        not in ({0} if phase is PlanningDispatchPhase.PLANNING_WAVE_1 else {0, 1})
    )
    if invalid_wave:
        raise SuccessorPlanningProgramCompilerError(
            "semantic registry contains a member from an inadmissible wave"
        )
    wave_1 = tuple(item for item in registry if item.authority.member.wave_index == 1)
    if phase is PlanningDispatchPhase.PLANNING_WAVE_1:
        if wave_1:
            raise SuccessorPlanningProgramCompilerError(
                "wave 1 derivation cannot consume wave 1 semantic members"
            )
        return
    foundation_program = _seal_pending_program(
        phase=PlanningDispatchPhase.PLANNING_WAVE_1,
        pending=_compile_wave_1_calls(
            semantic=_index_semantic_registry(
                tuple(item for item in registry if item.authority.member.wave_index == 0)
            )
        ),
    )
    expected_foundations = {
        scope.identity_sha256: scope for scope in foundation_program.requested_route_scopes
    }
    observed_foundations: set[str] = set()
    kind_by_endpoint = {
        "cume_stats_player_games": PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
        "cume_stats_team_games": PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
    }
    for item in wave_1:
        scope = item.authority.producing_scope
        expected_kind = kind_by_endpoint.get(scope.endpoint_name)
        descriptor = item.authority.member.semantic
        expected_scope = expected_foundations.get(scope.identity_sha256)
        if (
            expected_kind is None
            or descriptor.semantic_kind is not expected_kind
            or expected_scope is None
            or descriptor.partition != expected_scope.parameters
        ):
            raise SuccessorPlanningProgramCompilerError(
                "wave 1 semantic member differs from compiler-derived foundation topology"
            )
        if scope.identity_sha256 in observed_foundations:
            raise SuccessorPlanningProgramCompilerError(
                "wave 1 semantic inventory duplicates one foundation scope"
            )
        observed_foundations.add(scope.identity_sha256)
    if observed_foundations != set(expected_foundations):
        raise SuccessorPlanningProgramCompilerError(
            "wave 1 semantic inventory does not exactly cover foundation scopes"
        )


def _seal_pending_program(
    *,
    phase: PlanningDispatchPhase,
    pending: dict[tuple[str, str], _PendingLogicalCall],
) -> CompiledSuccessorPlanningProgram:
    if not pending:
        raise SuccessorPlanningProgramCompilerError("compiled planning program is empty")
    dispatches: list[SealedProviderDispatch] = []
    scopes_by_id: dict[str, RequestedRouteScope] = {}
    for call in pending.values():
        routes = tuple(sorted(call.routes.values(), key=lambda route: route.ordinal))
        if not routes:
            raise SuccessorPlanningProgramCompilerError(
                "compiled logical call has no exact result routes"
            )
        if (
            len({route.param_pattern for route in routes}) != 1
            or len({route.provider_authority_sha256 for route in routes}) != 1
            or len({route.provider_endpoint_id for route in routes}) != 1
        ):
            raise SuccessorPlanningProgramCompilerError(
                "compiled logical call routes differ in pattern or provider authority"
            )
        scopes = tuple(
            RequestedRouteScope.from_parameters(
                endpoint_name=route.endpoint_name,
                route_id=route.route_id,
                route_contract_sha256=route.contract_sha256,
                parameters=call.parameters,
                mutability=CallMutability.MUTABLE,
            )
            for route in routes
        )
        for scope in scopes:
            existing = scopes_by_id.get(scope.identity_sha256)
            if existing is not None and existing.to_dict() != scope.to_dict():
                raise SuccessorPlanningProgramCompilerError(
                    "compiled requested route scope identity collides"
                )
            scopes_by_id[scope.identity_sha256] = scope
        dispatches.append(
            SealedProviderDispatch.from_parameters(
                phase=phase,
                endpoint_name=call.endpoint_name,
                requested_scope_identity_sha256s=tuple(scope.identity_sha256 for scope in scopes),
                parameters=call.parameters,
                pattern=routes[0].param_pattern,
                staging_route_ids=tuple(route.route_id for route in routes),
                dependency_identity_sha256s=tuple(sorted(call.dependency_identity_sha256s)),
            )
        )
    dispatches.sort(key=lambda dispatch: min(dispatch.requested_scope_identity_sha256s))
    return CompiledSuccessorPlanningProgram(
        phase=phase,
        requested_route_scopes=tuple(
            sorted(scopes_by_id.values(), key=lambda scope: scope.identity_sha256)
        ),
        sealed_dispatches=tuple(dispatches),
    )


def compile_successor_planning_program(
    *,
    request: SuccessorPlanningRequest,
    semantic_registry: tuple[PlanningSemanticPartitionValues, ...],
    phase: PlanningDispatchPhase,
) -> CompiledSuccessorPlanningProgram:
    """Compile one exact phase from partition-local, revalidated semantics.

    No provider, wall clock, global flattened ID list, or legacy extraction-plan
    builder participates.  Every emitted logical call binds the canonical union
    of the exact member identities used in its partition-local joins.
    """

    if not isinstance(request, SuccessorPlanningRequest):
        raise SuccessorPlanningProgramCompilerError(
            "program compilation requires a SuccessorPlanningRequest"
        )
    _validate_compiler_topology(
        request=request,
        registry=semantic_registry,
        phase=phase,
    )
    semantic = _index_semantic_registry(semantic_registry)
    if phase is PlanningDispatchPhase.PLANNING_WAVE_1:
        pending = _compile_wave_1_calls(semantic=semantic)
    elif phase is PlanningDispatchPhase.UPDATE:
        pending = _compile_update_calls(
            request=request,
            registry=semantic_registry,
            semantic=semantic,
        )
    else:
        raise SuccessorPlanningProgramCompilerError(
            "compiler phase must be planning wave 1 or update"
        )
    return _seal_pending_program(phase=phase, pending=pending)
