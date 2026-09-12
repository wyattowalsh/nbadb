"""Verifier-owned replay of persisted Raw V2 authority in one DuckDB snapshot.

The caller owns the connection and its transaction.  This module performs no
transaction control and creates no relations; it only replays the repository's
native Raw authority codecs and persistence verifier before sealing F.5
evidence.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Never, cast

import duckdb

from nbadb.contracts.transform_output_operation_data_authority import (
    DurableRawTerminalManifestLocatorV1,
    FullExtractionRawOperationDenominatorV1,
    OperationDataAuthorityError,
    SuccessorRawOperationDenominatorV1,
    VerifiedOperationRawSnapshotV1,
)
from nbadb.orchestrate.raw_request_manifest import (
    RawRequestAuthorityManifestV2,
    parse_raw_request_authority_manifest,
)
from nbadb.orchestrate.raw_request_store import (
    RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL,
    RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL,
    RawRequestAuthorityStore,
    RawRequestManifestAuthorityV2,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "OperationRawSnapshotVerificationError",
    "compile_verified_operation_raw_snapshot",
]

_PAGE_SIZE = 128
_MANIFEST_COLUMNS = (
    "manifest_sha256, operation_sha256, operation_json, source_sha, run_id, "
    "run_attempt, chain_id, lane_id, scope_sha256, generation, "
    "parent_manifest_sha256, route_authority_sha256, "
    "request_closure_authority_sha256, field_authority_sha256, "
    "model_authority_sha256, authority_set_sha256, receipt_count, "
    "receipt_inventory_sha256, canonical_json"
)


class OperationRawSnapshotVerificationError(ValueError):
    """The caller-owned snapshot does not exactly realize its Raw denominator."""


def _fail(message: str) -> Never:
    raise OperationRawSnapshotVerificationError(message)


def _strict_denominator(
    value: FullExtractionRawOperationDenominatorV1 | SuccessorRawOperationDenominatorV1,
) -> FullExtractionRawOperationDenominatorV1 | SuccessorRawOperationDenominatorV1:
    if type(value) is FullExtractionRawOperationDenominatorV1:
        replayed = FullExtractionRawOperationDenominatorV1.from_canonical_bytes(
            value.canonical_bytes()
        )
        if replayed != value:
            _fail("full-extraction Raw denominator differs from canonical replay")
        # The durable replay intentionally carries scalar roots only. Return the
        # original, already-validated exact DTO so its verifier-only member
        # sidecars remain available for the terminal-locator exact join.
        return value
    if type(value) is SuccessorRawOperationDenominatorV1:
        return SuccessorRawOperationDenominatorV1.from_canonical_bytes(value.canonical_bytes())
    _fail("Raw snapshot verifier requires one exact typed denominator")


def _require_exact_relations(
    connection: duckdb.DuckDBPyConnection,
    store: RawRequestAuthorityStore,
) -> None:
    expected = {
        *(item.table_name for item in store._public_table_contracts()),  # noqa: SLF001
        RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL,
        RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL,
    }
    placeholders = ",".join("?" for _ in expected)
    rows = connection.execute(
        "SELECT table_catalog, table_schema, table_name, table_type "
        "FROM information_schema.tables WHERE table_name IN (" + placeholders + ") "
        "ORDER BY table_catalog, table_schema, table_name, table_type",
        sorted(expected),
    ).fetchall()
    by_name: dict[str, list[tuple[object, ...]]] = {name: [] for name in expected}
    for row in rows:
        by_name[str(row[2])].append(tuple(row))
    if any(
        len(by_name[name]) != 1
        or str(by_name[name][0][1]) != "main"
        or str(by_name[name][0][3]).upper() != "BASE TABLE"
        for name in expected
    ):
        _fail("Raw snapshot relations are missing, shadowed, temporary, or views")
    for contract in store._public_table_contracts():  # noqa: SLF001
        store._require_public_table(contract)  # noqa: SLF001
    store._require_bundle_journal()  # noqa: SLF001
    observed = connection.execute(
        f"PRAGMA table_info('{RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL}')"
    ).fetchall()
    expected_manifest = (
        ("manifest_sha256", "VARCHAR", True, True),
        ("operation_sha256", "VARCHAR", True, False),
        ("operation_json", "VARCHAR", True, False),
        ("source_sha", "VARCHAR", True, False),
        ("run_id", "BIGINT", True, False),
        ("run_attempt", "BIGINT", True, False),
        ("chain_id", "VARCHAR", True, False),
        ("lane_id", "VARCHAR", True, False),
        ("scope_sha256", "VARCHAR", True, False),
        ("generation", "BIGINT", True, False),
        ("parent_manifest_sha256", "VARCHAR", False, False),
        ("route_authority_sha256", "VARCHAR", True, False),
        ("request_closure_authority_sha256", "VARCHAR", True, False),
        ("field_authority_sha256", "VARCHAR", True, False),
        ("model_authority_sha256", "VARCHAR", True, False),
        ("authority_set_sha256", "VARCHAR", True, False),
        ("receipt_count", "BIGINT", True, False),
        ("receipt_inventory_sha256", "VARCHAR", True, False),
        ("canonical_json", "VARCHAR", True, False),
    )
    if tuple((str(r[1]), str(r[2]).upper(), bool(r[3]), bool(r[5])) for r in observed) != (
        expected_manifest
    ):
        _fail("Raw manifest journal schema drifted")


def _require_caller_transaction(connection: duckdb.DuckDBPyConnection) -> None:
    """Prove that two reads remain inside one caller-owned transaction."""

    first = connection.execute("SELECT current_transaction_id()").fetchone()
    second = connection.execute("SELECT current_transaction_id()").fetchone()
    if (
        first is None
        or second is None
        or len(first) != 1
        or len(second) != 1
        or type(first[0]) is not int
        or type(second[0]) is not int
        or first[0] != second[0]
    ):
        _fail("Raw snapshot verification requires one caller-owned DuckDB transaction")


def _operation_authority(
    operation_json: str,
    manifest: RawRequestAuthorityManifestV2,
) -> RawRequestManifestAuthorityV2:
    try:
        payload = json.loads(operation_json)
        authority_payload = payload["authority"]
        provenance = authority_payload["compiler_provenance_sha256"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise OperationRawSnapshotVerificationError(
            "Raw manifest operation lacks exact authority provenance"
        ) from exc
    try:
        return RawRequestManifestAuthorityV2(
            source_sha=manifest.source_sha,
            run_id=manifest.run_id,
            run_attempt=manifest.run_attempt,
            chain_id=manifest.chain_id,
            lane_id=manifest.lane_id,
            scope_sha256=manifest.scope_sha256,
            route_authority_sha256=manifest.route_authority_sha256,
            request_closure_authority_sha256=manifest.request_closure_authority_sha256,
            field_authority_sha256=manifest.field_authority_sha256,
            model_authority_sha256=manifest.model_authority_sha256,
            expected_calls=manifest.expected_calls,
            compiler_provenance_sha256=cast("str", provenance),
        )
    except (TypeError, ValueError) as exc:
        raise OperationRawSnapshotVerificationError(
            "Raw manifest operation authority is not exact"
        ) from exc


def _locator(
    terminal: RawRequestAuthorityManifestV2,
    *,
    terminal_operation_sha256: str,
) -> DurableRawTerminalManifestLocatorV1:
    if not terminal.terminal_sealed or not terminal.coverage_complete:
        _fail("Raw manifest chain is partial or unsealed")
    calls = tuple(item.logical_request_sha256 for item in terminal.expected_calls)
    routes = tuple(sorted({route for item in terminal.expected_calls for route in item.route_ids}))
    canonical = terminal.canonical_bytes
    return DurableRawTerminalManifestLocatorV1._seal(  # noqa: SLF001
        source_sha=terminal.source_sha,
        run_id=terminal.run_id,
        run_attempt=terminal.run_attempt,
        chain_id=terminal.chain_id,
        lane_id=terminal.lane_id,
        scope_sha256=terminal.scope_sha256,
        route_authority_sha256=terminal.route_authority_sha256,
        request_closure_authority_sha256=terminal.request_closure_authority_sha256,
        field_authority_sha256=terminal.field_authority_sha256,
        model_authority_sha256=terminal.model_authority_sha256,
        authority_set_sha256=terminal.authority_set_sha256,
        expected_call_count=len(calls),
        expected_call_inventory_sha256=terminal.expected_request_inventory_sha256,
        route_count=len(routes),
        route_inventory_sha256=_inventory_sha256(routes),
        terminal_generation=terminal.generation,
        terminal_parent_manifest_sha256=terminal.parent_manifest_sha256,
        terminal_manifest_sha256=terminal.manifest_sha256,
        terminal_operation_sha256=terminal_operation_sha256,
        terminal_receipt_count=terminal.receipt_count,
        terminal_receipt_inventory_sha256=terminal.receipt_inventory_sha256,
        terminal_manifest_canonical_byte_length=len(canonical),
        terminal_manifest_canonical_sha256=hashlib.sha256(canonical).hexdigest(),
    )


def _inventory_sha256(values: Iterable[str]) -> str:
    payload = json.dumps(list(values), separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _load_locators(
    connection: duckdb.DuckDBPyConnection,
    store: RawRequestAuthorityStore,
) -> tuple[DurableRawTerminalManifestLocatorV1, ...]:
    result: list[DurableRawTerminalManifestLocatorV1] = []
    last: tuple[object, ...] | None = None
    seen: set[tuple[object, ...]] = set()
    while True:
        where = ""
        params: list[object] = []
        if last is not None:
            where = (
                "WHERE (source_sha,run_id,run_attempt,chain_id,lane_id,generation,manifest_sha256) "
                "> (?,?,?,?,?,?,?)"
            )
            params = list(last)
        rows = connection.execute(
            f"SELECT {_MANIFEST_COLUMNS} FROM {RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL} "
            f"{where} ORDER BY source_sha,run_id,run_attempt,chain_id,lane_id,generation,"
            f"manifest_sha256 LIMIT {_PAGE_SIZE}",
            params,
        ).fetchall()
        if not rows:
            break
        for row in rows:
            if len(row) != 19 or type(row[18]) is not str or type(row[2]) is not str:
                _fail("Raw manifest journal row is malformed")
            manifest = parse_raw_request_authority_manifest(row[18].encode())
            projected = (
                manifest.manifest_sha256,
                row[1],
                row[2],
                manifest.source_sha,
                manifest.run_id,
                manifest.run_attempt,
                manifest.chain_id,
                manifest.lane_id,
                manifest.scope_sha256,
                manifest.generation,
                manifest.parent_manifest_sha256,
                manifest.route_authority_sha256,
                manifest.request_closure_authority_sha256,
                manifest.field_authority_sha256,
                manifest.model_authority_sha256,
                manifest.authority_set_sha256,
                manifest.receipt_count,
                manifest.receipt_inventory_sha256,
                manifest.canonical_bytes.decode(),
            )
            if tuple(row) != projected:
                _fail("Raw manifest journal projections differ from canonical bytes")
            key = (
                manifest.source_sha,
                manifest.run_id,
                manifest.run_attempt,
                manifest.chain_id,
                manifest.lane_id,
            )
            if key not in seen:
                authority = _operation_authority(cast("str", row[2]), manifest)
                try:
                    chain = store._load_manifest_chain(authority)  # noqa: SLF001
                except (TypeError, ValueError) as exc:
                    raise OperationRawSnapshotVerificationError(
                        "Raw manifest chain or persisted receipt replay failed"
                    ) from exc
                if not chain:
                    _fail("Raw manifest execution has no generations")
                terminal_row = connection.execute(
                    f"SELECT operation_sha256 FROM {RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL} "
                    "WHERE manifest_sha256 = ?",
                    [chain[-1].manifest_sha256],
                ).fetchone()
                if terminal_row is None or type(terminal_row[0]) is not str:
                    _fail("Raw terminal manifest operation is absent")
                operation_sha = cast("str", terminal_row[0])
                result.append(_locator(chain[-1], terminal_operation_sha256=operation_sha))
                seen.add(key)
            last = (row[3], row[4], row[5], row[6], row[7], row[9], row[0])
    return tuple(sorted(result, key=lambda item: item.locator_sha256))


def compile_verified_operation_raw_snapshot(
    denominator: FullExtractionRawOperationDenominatorV1 | SuccessorRawOperationDenominatorV1,
    *,
    operation_sha256: str,
    source_sha: str,
    chain_id: str,
    transaction_generation: int,
    transaction_generation_identity_sha256: str,
    duckdb_snapshot_sha256: str,
    connection: duckdb.DuckDBPyConnection,
) -> VerifiedOperationRawSnapshotV1:
    """Replay one caller-owned DuckDB snapshot and seal its exact Raw evidence."""

    if type(connection) is not duckdb.DuckDBPyConnection:
        _fail("Raw snapshot verifier requires one exact DuckDB connection")
    exact = _strict_denominator(denominator)
    context = exact.operation_context
    if (
        context.operation_sha256 != operation_sha256
        or context.source_sha != source_sha
        or context.chain_id != chain_id
        or context.transaction_generation != transaction_generation
        or context.transaction_generation_identity_sha256 != transaction_generation_identity_sha256
        or context.duckdb_snapshot_sha256 != duckdb_snapshot_sha256
    ):
        _fail("Raw denominator differs from the explicit operation snapshot context")
    store = RawRequestAuthorityStore(connection)
    try:
        _require_caller_transaction(connection)
        _require_exact_relations(connection, store)
        observed = _load_locators(connection, store)
    except OperationRawSnapshotVerificationError:
        raise
    except Exception as exc:
        raise OperationRawSnapshotVerificationError("Raw snapshot replay failed closed") from exc
    if type(exact) is FullExtractionRawOperationDenominatorV1:
        if not exact.normalized_manifest_lane_sha256s:
            _fail("full-extraction raw snapshot requires verifier-only member enumeration")
        expected = tuple(member.terminal_locator for member in exact.executable_members) + (
            exact.discovery_member.terminal_locator,
            exact.live_member.terminal_locator,
        )
    else:
        successor = cast("SuccessorRawOperationDenominatorV1", exact)
        expected = (successor.delta_terminal_locator,)
    if tuple(item.locator_sha256 for item in observed) != tuple(
        sorted(item.locator_sha256 for item in expected)
    ) or {item.locator_sha256: item for item in observed} != {
        item.locator_sha256: item for item in expected
    }:
        _fail("Raw snapshot terminal groups do not exact-join the typed denominator")
    operation_kind = (
        "full_extraction" if type(exact) is FullExtractionRawOperationDenominatorV1 else "successor"
    )
    try:
        return VerifiedOperationRawSnapshotV1._seal(  # noqa: SLF001
            operation_context=context,
            operation_kind=operation_kind,
            denominator=exact,
        )
    except OperationDataAuthorityError as exc:
        raise OperationRawSnapshotVerificationError("Raw snapshot sealing failed") from exc
