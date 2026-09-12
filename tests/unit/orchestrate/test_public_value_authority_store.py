"""Hostile persistence tests for the five pre-operation W2 public relations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import duckdb
import pytest

import nbadb.orchestrate.public_value_authority_store as store_module
from nbadb.contracts.live_lossless_value_authority import LIVE_LOSSLESS_NODE_SCHEMA_SHA256
from nbadb.contracts.public_table_value_projection import (
    RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
    RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
    RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
)
from nbadb.contracts.stats_lossless_value_authority import (
    STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
)
from nbadb.orchestrate.public_value_authority_store import (
    PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL,
    PUBLIC_VALUE_AUTHORITY_TABLES,
    PublicValueAuthorityPersistenceError,
    PublicValueAuthorityStore,
)
from nbadb.schemas.raw.nba_api_live_lossless_node import RawNbaApiLiveLosslessNodeSchema
from nbadb.schemas.raw.nba_api_result_cell import RawNbaApiResultCellSchema
from nbadb.schemas.raw.nba_api_route_field_landing import (
    RawNbaApiRouteFieldLandingSchema,
)
from nbadb.schemas.raw.nba_api_stats_lossless_record import (
    RawNbaApiStatsLosslessRecordSchema,
)
from nbadb.schemas.raw.nba_api_value_representation import (
    RawNbaApiValueRepresentationSchema,
)
from tests.unit.contracts.test_public_table_value_projection import (
    _fixed_zero_fixture,
    _live_fixture,
    _rectangular_fixture,
    _reseal_result_row,
    _reseal_route_row,
    _residual_fixture,
    _route_row,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import pandera.polars as pa

    from nbadb.contracts.value_projection_plan import ValueProjectionPlanV1


def _candidate(
    kind: str = "fixed_zero",
) -> dict[str, object]:
    if kind == "fixed_zero":
        plan = _fixed_zero_fixture()
        result_rows: tuple[dict[str, object], ...] = ()
        stats_rows: tuple[dict[str, object], ...] = ()
        live_rows: tuple[dict[str, object], ...] = ()
    elif kind == "rectangular":
        plan, result_rows = _rectangular_fixture()
        stats_rows = ()
        live_rows = ()
    elif kind == "stats":
        plan, stats_rows = _residual_fixture()
        result_rows = ()
        live_rows = ()
    elif kind == "live":
        plan, live_rows = _live_fixture()
        result_rows = ()
        stats_rows = ()
    else:
        raise AssertionError(kind)
    route_rows = tuple(
        _route_row(plan, unit_ordinal=ordinal, landing_field_ordinal=ordinal)
        for ordinal in range(plan.expected_unit_count)
    )
    return {
        "plan": plan,
        "expected_plan_sha256": plan.plan_sha256,
        "expected_raw_authority_bundle_sha256": plan.raw_authority_bundle_sha256,
        "expected_ownership_receipt_sha256": plan.ownership_receipt_sha256,
        "result_cell_schema_sha256": RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
        "result_cell_rows": result_rows,
        "stats_lossless_schema_sha256": STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
        "stats_lossless_rows": stats_rows,
        "live_lossless_schema_sha256": LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
        "live_lossless_rows": live_rows,
        "value_representation_schema_sha256": (RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256),
        "value_representation_rows": tuple(item.to_row() for item in plan.assignments),
        "route_field_landing_schema_sha256": (RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256),
        "route_field_landing_rows": route_rows,
    }


def _schema_contracts() -> tuple[tuple[str, str, type[pa.DataFrameModel]], ...]:
    return (
        (PUBLIC_VALUE_AUTHORITY_TABLES[0], "cell_sha256", RawNbaApiResultCellSchema),
        (
            PUBLIC_VALUE_AUTHORITY_TABLES[1],
            "record_sha256",
            RawNbaApiStatsLosslessRecordSchema,
        ),
        (
            PUBLIC_VALUE_AUTHORITY_TABLES[2],
            "record_sha256",
            RawNbaApiLiveLosslessNodeSchema,
        ),
        (
            PUBLIC_VALUE_AUTHORITY_TABLES[3],
            "assignment_sha256",
            RawNbaApiValueRepresentationSchema,
        ),
        (
            PUBLIC_VALUE_AUTHORITY_TABLES[4],
            "landing_field_sha256",
            RawNbaApiRouteFieldLandingSchema,
        ),
    )


@pytest.mark.parametrize("kind", ("fixed_zero", "rectangular", "stats", "live"))
def test_persists_every_representation_and_rebuilds_projection_from_readback(
    kind: str,
) -> None:
    connection = duckdb.connect(":memory:")
    store = PublicValueAuthorityStore(connection)
    candidate = _candidate(kind)

    first = store.persist_candidate(**candidate)
    second = store.persist_candidate(**candidate)

    assert first.inserted is True
    assert first.replayed is False
    assert second.inserted is False
    assert second.replayed is True
    assert second.authority == first.authority
    assert (
        second.authority.receipt.raw_authority_bundle_sha256
        == candidate["expected_raw_authority_bundle_sha256"]
    )


def test_fixed_zero_keeps_three_mandatory_relations_present_and_empty() -> None:
    connection = duckdb.connect(":memory:")
    result = PublicValueAuthorityStore(connection).persist_candidate(**_candidate())

    assert result.authority.receipt.result_cell_row_count == 0
    assert result.authority.receipt.stats_lossless_row_count == 0
    assert result.authority.receipt.live_lossless_row_count == 0
    assert result.authority.receipt.value_representation_row_count == 1
    assert result.authority.receipt.route_field_landing_row_count == 1
    for table in PUBLIC_VALUE_AUTHORITY_TABLES[:3]:
        assert connection.execute(f'SELECT count(*) FROM "{table}"').fetchone() == (0,)


def test_all_five_empty_is_not_a_valid_mandatory_candidate() -> None:
    candidate = _candidate()
    candidate["value_representation_rows"] = ()
    candidate["route_field_landing_rows"] = ()

    with pytest.raises(PublicValueAuthorityPersistenceError):
        PublicValueAuthorityStore(duckdb.connect(":memory:")).persist_candidate(**candidate)


def test_duckdb_tables_exactly_match_order_types_nullability_and_primary_keys() -> None:
    connection = duckdb.connect(":memory:")
    PublicValueAuthorityStore(connection).persist_candidate(**_candidate("live"))

    for table, key, schema_type in _schema_contracts():
        expected = [
            (
                name,
                "BIGINT" if column.dtype.type.__name__ == "Int64" else "VARCHAR",
                not column.nullable or name == key,
                name == key,
            )
            for name, column in schema_type.to_schema().columns.items()
        ]
        actual = [
            (str(row[1]), str(row[2]).upper(), bool(row[3]), bool(row[5]))
            for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()
        ]
        assert actual == expected


class _FailAfterFirstInsertStore(PublicValueAuthorityStore):
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        super().__init__(connection)
        self._inserts = 0

    def _insert_relation(self, relation: Any) -> None:
        super()._insert_relation(relation)
        if relation.rows:
            self._inserts += 1
            if self._inserts == 1:
                raise RuntimeError("authorization Bearer should-never-be-visible")


def test_one_transaction_rolls_back_all_five_tables_and_private_journal() -> None:
    connection = duckdb.connect(":memory:")
    with pytest.raises(
        PublicValueAuthorityPersistenceError,
        match="candidate transaction failed",
    ) as captured:
        _FailAfterFirstInsertStore(connection).persist_candidate(**_candidate("rectangular"))

    assert "Bearer" not in str(captured.value)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert not tables.intersection(
        {*PUBLIC_VALUE_AUTHORITY_TABLES, PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}
    )


def test_same_bundle_different_valid_route_bytes_is_a_collision() -> None:
    connection = duckdb.connect(":memory:")
    store = PublicValueAuthorityStore(connection)
    candidate = _candidate()
    store.persist_candidate(**candidate)
    changed = deepcopy(candidate)
    route = dict(cast("tuple[dict[str, object], ...]", candidate["route_field_landing_rows"])[0])
    route["raw_route_landing_sha256"] = "d" * 64
    changed["route_field_landing_rows"] = (_reseal_route_row(route),)

    with pytest.raises(PublicValueAuthorityPersistenceError, match="collides"):
        store.persist_candidate(**changed)


def test_partial_preexisting_keyed_row_fails_closed_without_a_journal() -> None:
    connection = duckdb.connect(":memory:")
    candidate = _candidate()
    original = PublicValueAuthorityStore(connection)
    original.persist_candidate(**candidate)
    connection.execute(f'DELETE FROM "{PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}"')

    with pytest.raises(PublicValueAuthorityPersistenceError, match="partial pre-existing"):
        original.persist_candidate(**candidate)


def test_reordered_ordered_child_inventory_fails_before_write() -> None:
    candidate = _candidate("rectangular")
    rows = cast("tuple[dict[str, object], ...]", candidate["result_cell_rows"])
    assert len(rows) > 1
    candidate["result_cell_rows"] = tuple(reversed(rows))

    with pytest.raises(PublicValueAuthorityPersistenceError, match="ordered plan inventory"):
        PublicValueAuthorityStore(duckdb.connect(":memory:")).persist_candidate(**candidate)


def test_duplicate_primary_key_is_rejected_before_write() -> None:
    candidate = _candidate("rectangular")
    rows = cast("tuple[dict[str, object], ...]", candidate["result_cell_rows"])
    candidate["result_cell_rows"] = (rows[0], rows[0], *rows[1:])

    with pytest.raises(PublicValueAuthorityPersistenceError):
        PublicValueAuthorityStore(duckdb.connect(":memory:")).persist_candidate(**candidate)


def test_duplicate_header_ordinal_is_rejected_by_exact_projection() -> None:
    candidate = _candidate("rectangular")
    rows = [
        dict(item) for item in cast("tuple[dict[str, object], ...]", candidate["result_cell_rows"])
    ]
    assert len(rows) > 1
    rows[1]["header_ordinal"] = rows[0]["header_ordinal"]
    rows[1]["header_name"] = rows[0]["header_name"]
    rows[1] = _reseal_result_row(rows[1])
    candidate["result_cell_rows"] = tuple(rows)

    with pytest.raises(PublicValueAuthorityPersistenceError):
        PublicValueAuthorityStore(duckdb.connect(":memory:")).persist_candidate(**candidate)


def test_duplicate_landing_ordinal_is_rejected_by_strict_schema() -> None:
    candidate = _candidate("rectangular")
    plan = cast("ValueProjectionPlanV1", candidate["plan"])
    assert plan.expected_unit_count > 1
    rows = [
        _route_row(plan, unit_ordinal=0, landing_field_ordinal=0),
        _route_row(plan, unit_ordinal=1, landing_field_ordinal=0),
    ]
    candidate["route_field_landing_rows"] = tuple(rows)

    with pytest.raises(PublicValueAuthorityPersistenceError, match="exact public schema"):
        PublicValueAuthorityStore(duckdb.connect(":memory:")).persist_candidate(**candidate)


def test_table_schema_drift_fails_closed_and_rolls_back_new_siblings() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute('CREATE TABLE "raw_nba_api_result_cell" (cell_sha256 VARCHAR PRIMARY KEY)')

    with pytest.raises(PublicValueAuthorityPersistenceError, match="schema drifted"):
        PublicValueAuthorityStore(connection).persist_candidate(**_candidate())

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert tables == {"raw_nba_api_result_cell"}


def test_store_refuses_caller_owned_transaction_without_altering_caller_state() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE sentinel(value BIGINT)")
    connection.execute("BEGIN TRANSACTION")
    connection.execute("INSERT INTO sentinel VALUES (7)")

    with pytest.raises(PublicValueAuthorityPersistenceError, match="caller-owned"):
        PublicValueAuthorityStore(connection).persist_candidate(**_candidate())

    connection.execute("COMMIT")
    assert connection.execute("SELECT * FROM sentinel").fetchall() == [(7,)]
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert tables == {"sentinel"}


def test_real_begin_then_keyboard_interrupt_rolls_back_and_restores_autocommit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = PublicValueAuthorityStore(connection)
    original_begin = store._begin_transaction

    def begin_then_interrupt() -> None:
        original_begin()
        raise KeyboardInterrupt

    monkeypatch.setattr(store, "_begin_transaction", begin_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        store.persist_candidate(**_candidate())

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert not tables.intersection(
        {*PUBLIC_VALUE_AUTHORITY_TABLES, PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}
    )
    connection.execute("BEGIN TRANSACTION")
    connection.execute("ROLLBACK")


def test_mid_transaction_keyboard_interrupt_rolls_back_every_candidate_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = PublicValueAuthorityStore(connection)
    original_insert = store._insert_relation
    inserted = False

    def insert_then_interrupt(relation: Any) -> None:
        nonlocal inserted
        original_insert(relation)
        if relation.rows and not inserted:
            inserted = True
            raise KeyboardInterrupt

    monkeypatch.setattr(store, "_insert_relation", insert_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        store.persist_candidate(**_candidate("rectangular"))

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert not tables.intersection(
        {*PUBLIC_VALUE_AUTHORITY_TABLES, PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}
    )
    connection.execute("BEGIN TRANSACTION")
    connection.execute("ROLLBACK")


def test_actual_commit_then_raise_is_fail_closed_and_exact_replay_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = PublicValueAuthorityStore(connection)
    candidate = _candidate()
    original_commit = store._commit_transaction

    def commit_then_raise() -> None:
        original_commit()
        raise RuntimeError("private-ambiguous-commit-detail")

    monkeypatch.setattr(store, "_commit_transaction", commit_then_raise)
    with pytest.raises(
        PublicValueAuthorityPersistenceError,
        match="candidate transaction failed",
    ) as captured:
        store.persist_candidate(**candidate)
    assert "private-ambiguous" not in str(captured.value)
    assert connection.execute(
        'SELECT count(*) FROM "raw_nba_api_value_representation"'
    ).fetchone() == (1,)
    assert connection.execute(
        f'SELECT count(*) FROM "{PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}"'
    ).fetchone() == (1,)

    monkeypatch.setattr(store, "_commit_transaction", original_commit)
    replay = store.persist_candidate(**candidate)
    assert replay.replayed is True
    assert (
        replay.authority.receipt.raw_authority_bundle_sha256
        == candidate["expected_raw_authority_bundle_sha256"]
    )


def test_unprovable_rollback_poison_closes_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = PublicValueAuthorityStore(connection)

    def interrupt_after_begin() -> None:
        connection.execute("BEGIN TRANSACTION")
        raise KeyboardInterrupt

    monkeypatch.setattr(store, "_begin_transaction", interrupt_after_begin)
    monkeypatch.setattr(store, "_rollback", lambda _interruption: False)
    monkeypatch.setattr(store, "_probe_clean_transaction_state", lambda: False)

    with pytest.raises(KeyboardInterrupt):
        store.persist_candidate(**_candidate())
    with pytest.raises(PublicValueAuthorityPersistenceError, match="poisoned"):
        store.persist_candidate(**_candidate())
    with pytest.raises(duckdb.ConnectionException):
        connection.execute("SELECT 1")


@pytest.mark.parametrize(
    "mode",
    ("missing_primary_key", "extra_index", "extra_unique", "extra_check"),
)
def test_exact_constraint_and_index_contract_rejects_drift(mode: str) -> None:
    connection = duckdb.connect(":memory:")
    candidate = _candidate()
    PublicValueAuthorityStore(connection).persist_candidate(**candidate)
    table = PUBLIC_VALUE_AUTHORITY_TABLES[3]
    if mode in {"extra_index", "extra_unique"}:
        connection.execute(
            f"CREATE {'UNIQUE ' if mode == 'extra_unique' else ''}"
            f'INDEX "unexpected_index" ON "{table}" ("unit_ordinal")'
        )
    else:
        connection.execute(f'ALTER TABLE "{table}" RENAME TO "authority_original"')
        schema = RawNbaApiValueRepresentationSchema.to_schema()
        definitions = [
            f'"{name}" '
            f"{'BIGINT' if column.dtype.type.__name__ == 'Int64' else 'VARCHAR'}"
            + ("" if column.nullable else " NOT NULL")
            for name, column in schema.columns.items()
        ]
        if mode != "missing_primary_key":
            definitions.append('PRIMARY KEY ("assignment_sha256")')
        if mode == "extra_check":
            definitions.append('CHECK ("schema_version" = 1)')
        connection.execute(f'CREATE TABLE "{table}" ({", ".join(definitions)})')
        connection.execute(f'INSERT INTO "{table}" SELECT * FROM "authority_original"')
        connection.execute('DROP TABLE "authority_original"')

    with pytest.raises(PublicValueAuthorityPersistenceError, match="schema drifted"):
        PublicValueAuthorityStore(connection).persist_candidate(**candidate)


def test_temporary_shadow_table_is_never_accepted_as_public_authority() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute(
        'CREATE TEMP TABLE "raw_nba_api_result_cell" (cell_sha256 VARCHAR PRIMARY KEY)'
    )

    with pytest.raises(PublicValueAuthorityPersistenceError, match="schema drifted"):
        PublicValueAuthorityStore(connection).persist_candidate(**_candidate())

    rows = connection.execute(
        "SELECT database_name, temporary FROM duckdb_tables() "
        "WHERE table_name = 'raw_nba_api_result_cell'"
    ).fetchall()
    assert rows == [("temp", True)]


def test_candidate_journal_extra_index_is_contract_drift() -> None:
    connection = duckdb.connect(":memory:")
    candidate = _candidate()
    PublicValueAuthorityStore(connection).persist_candidate(**candidate)
    connection.execute(
        f'CREATE INDEX "journal_extra_index" '
        f'ON "{PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}" ("candidate_sha256")'
    )

    with pytest.raises(PublicValueAuthorityPersistenceError, match="journal schema drifted"):
        PublicValueAuthorityStore(connection).persist_candidate(**candidate)


def test_relation_inventory_bound_is_checked_before_schema_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = store_module._contracts()
    limited = tuple(
        replace(item, maximum_rows=0)
        if item.table_name == "raw_nba_api_value_representation"
        else item
        for item in contracts
    )
    monkeypatch.setattr(store_module, "_contracts", lambda: limited)

    with pytest.raises(PublicValueAuthorityPersistenceError, match="exceeds"):
        PublicValueAuthorityStore(duckdb.connect(":memory:")).persist_candidate(**_candidate())


@pytest.mark.parametrize("corruption", ("delete", "mutate", "foreign"))
def test_post_commit_missing_mutated_or_foreign_readback_never_returns_success(
    corruption: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = PublicValueAuthorityStore(connection)
    original_commit: Callable[[], None] = store._commit_transaction

    def commit_then_corrupt() -> None:
        original_commit()
        if corruption == "delete":
            connection.execute('DELETE FROM "raw_nba_api_value_representation"')
        elif corruption == "mutate":
            connection.execute(
                "UPDATE \"raw_nba_api_route_field_landing\" SET route_id = 'mutated_public_route'"
            )
        else:
            connection.execute(
                'INSERT INTO "raw_nba_api_route_field_landing" '
                "SELECT schema_version, repeat('f', 64), landing_field_ordinal + 1, "
                "route_receipt_ordinal, raw_authority_bundle_sha256, "
                "route_landing_receipt_sha256, raw_route_landing_sha256, "
                "observation_sha256, route_ordinal, route_id, staging_key, unit_sha256, "
                "unit_ordinal, unit_kind, occurrence_sha256, occurrence_ordinal, "
                "assignment_sha256, source_input_kind, representation_kind, row_kind, "
                "field_ordinal, field_name, field_authority_sha256, field_origin, "
                'logical_type_sha256 FROM "raw_nba_api_route_field_landing" LIMIT 1'
            )

    monkeypatch.setattr(store, "_commit_transaction", commit_then_corrupt)

    with pytest.raises(PublicValueAuthorityPersistenceError):
        store.persist_candidate(**_candidate())


def test_same_key_different_table_bytes_fails_exact_replay() -> None:
    connection = duckdb.connect(":memory:")
    store = PublicValueAuthorityStore(connection)
    candidate = _candidate()
    store.persist_candidate(**candidate)
    connection.execute(
        "UPDATE \"raw_nba_api_route_field_landing\" SET route_id = 'different_content_same_key'"
    )

    with pytest.raises(PublicValueAuthorityPersistenceError, match="replay differs"):
        store.persist_candidate(**candidate)


def test_secret_shaped_invalid_row_is_sanitized_and_never_persisted() -> None:
    candidate = _candidate("rectangular")
    rows = [
        dict(item) for item in cast("tuple[dict[str, object], ...]", candidate["result_cell_rows"])
    ]
    rows[0]["header_name"] = "authorization Bearer super-secret-value-1234567890"
    rows[0] = _reseal_result_row(rows[0])
    candidate["result_cell_rows"] = tuple(rows)

    with pytest.raises(PublicValueAuthorityPersistenceError) as captured:
        PublicValueAuthorityStore(duckdb.connect(":memory:")).persist_candidate(**candidate)

    assert "authorization" not in str(captured.value).lower()
    assert "secret-value" not in str(captured.value).lower()
    assert captured.value.__cause__ is None


def test_wrong_external_schema_pin_fails_before_any_ddl() -> None:
    connection = duckdb.connect(":memory:")
    candidate = _candidate()
    candidate["result_cell_schema_sha256"] = "0" * 64

    with pytest.raises(PublicValueAuthorityPersistenceError, match="schema pins differ"):
        PublicValueAuthorityStore(connection).persist_candidate(**candidate)

    assert connection.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchone() == (0,)
