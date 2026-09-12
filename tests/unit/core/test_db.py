from __future__ import annotations

import hashlib
import threading
from dataclasses import replace
from unittest.mock import MagicMock, patch

import duckdb
import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from nbadb.core import db as db_module
from nbadb.core.db import (
    DBManager,
    DuckDBLockError,
    TransformOutputAuthorityPersistenceError,
    TransformOutputAuthorityPersistenceState,
)


@pytest.fixture()
def db(tmp_path):
    return DBManager(
        sqlite_path=tmp_path / "test.sqlite",
        duckdb_path=tmp_path / "test.duckdb",
    )


@pytest.fixture()
def initialized_db(db):
    db.init()
    yield db
    db.close()


class TestDBManagerInit:
    def test_init_creates_files(self, db, tmp_path):
        db.init()
        db.close()
        assert (tmp_path / "test.sqlite").exists()
        assert (tmp_path / "test.duckdb").exists()

    def test_init_retries_duckdb_lock_then_succeeds(self, db):
        mock_conn = MagicMock()
        lock_error = duckdb.IOException('IO Error: Could not set lock on file "/tmp/test.duckdb"')

        with (
            patch("nbadb.core.db.duckdb.connect", side_effect=[lock_error, mock_conn]),
            patch("nbadb.core.db.time.sleep") as mock_sleep,
        ):
            db.init()
        try:
            assert db.duckdb is mock_conn
            mock_sleep.assert_called_once_with(0.5)
        finally:
            db.close()

    def test_init_raises_helpful_error_after_repeated_duckdb_lock_conflicts(self, db):
        lock_error = duckdb.IOException(
            'IO Error: Could not set lock on file "/tmp/test.duckdb": Conflicting lock is held'
        )

        with (
            patch("nbadb.core.db.duckdb.connect", side_effect=lock_error),
            patch("nbadb.core.db.time.sleep") as mock_sleep,
        ):
            try:
                with pytest.raises(DuckDBLockError, match="DuckDB database is locked"):
                    db.init()
            finally:
                db.close()

        assert mock_sleep.call_count == 3

    def test_engine_returns_after_init(self, initialized_db):
        assert initialized_db.engine is not None
        assert isinstance(initialized_db.engine, Engine)

    def test_duckdb_returns_after_init(self, initialized_db):
        assert initialized_db.duckdb is not None

    def test_engine_before_init_raises(self, db):
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = db.engine

    def test_duckdb_before_init_raises(self, db):
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = db.duckdb


class TestPipelineTables:
    EXPECTED_TABLES = {
        "_pipeline_watermarks",
        "_extraction_journal",
        "_pipeline_metadata",
        "_pipeline_metrics",
        "_lane_metrics",
        "_staging_chunk_journal",
        "_transform_checkpoints",
        "_transform_metrics",
        "_schema_versions",
        "_schema_version_history",
    }

    def test_pipeline_tables_created(self, initialized_db):
        rows = initialized_db.duckdb.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
        table_names = {row[0] for row in rows}
        assert self.EXPECTED_TABLES.issubset(table_names)

    def test_metadata_table_names(self, initialized_db):
        rows = initialized_db.duckdb.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_name LIKE '\\_%' ESCAPE '\\'"
        ).fetchall()
        assert len(rows) == len(self.EXPECTED_TABLES)

    def test_receipt_attestation_columns_are_additively_created(self, initialized_db):
        def columns(table_name: str) -> list[str]:
            return [
                str(row[0])
                for row in initialized_db.duckdb.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'main' AND table_name = $1
                    ORDER BY ordinal_position
                    """,
                    [table_name],
                ).fetchall()
            ]

        assert columns("_extraction_journal") == [
            "endpoint",
            "params",
            "status",
            "started_at",
            "completed_at",
            "rows_extracted",
            "error_message",
            "retry_count",
            "logical_call_receipt_sha256",
            "provider_authority_sha256",
            "logical_parameters_sha256",
            "result_route_ids_json",
            "w2_required",
            "w2_source_call_admission_sha256",
            "w2_source_call_admission_bytes",
            "raw_authority_bundle_sha256",
            "raw_authority_persistence_receipt_sha256",
            "committed_staging_readback_count",
            "committed_staging_readback_root_sha256",
            "w2_operation_key_sha256",
            "w2_operation_receipt_sha256",
            "w2_operation_persistence_receipt_sha256",
        ]
        assert columns("_staging_chunk_journal") == [
            "chunk_id",
            "staging_key",
            "row_count",
            "content_hash",
            "source_label",
            "created_at",
            "persisted_row_count",
            "persisted_content_sha256",
            "persisted_schema_sha256",
            "logical_call_receipt_sha256",
            "provider_authority_sha256",
            "logical_parameters_sha256",
            "result_route_id",
        ]

    def test_legacy_journal_rows_are_additively_migrated_to_w2_authority(
        self,
        tmp_path,
    ):
        duckdb_path = tmp_path / "legacy.duckdb"
        connection = duckdb.connect(str(duckdb_path))
        try:
            connection.execute(
                """
                CREATE TABLE _extraction_journal (
                    endpoint VARCHAR NOT NULL,
                    params VARCHAR,
                    status VARCHAR NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    rows_extracted BIGINT,
                    error_message VARCHAR,
                    retry_count INTEGER DEFAULT 0,
                    PRIMARY KEY (endpoint, params)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO _extraction_journal
                    (endpoint, params, status, rows_extracted)
                VALUES ('legacy', '{}', 'done', 1)
                """
            )
        finally:
            connection.close()

        manager = DBManager(
            sqlite_path=tmp_path / "legacy.sqlite",
            duckdb_path=duckdb_path,
        )
        manager.init()
        try:
            row = manager.duckdb.execute(
                """
                SELECT w2_required,
                       w2_source_call_admission_sha256,
                       w2_source_call_admission_bytes,
                       raw_authority_bundle_sha256,
                       raw_authority_persistence_receipt_sha256,
                       committed_staging_readback_count,
                       committed_staging_readback_root_sha256,
                       w2_operation_key_sha256,
                       w2_operation_receipt_sha256,
                       w2_operation_persistence_receipt_sha256
                FROM _extraction_journal
                WHERE endpoint = 'legacy' AND params = '{}'
                """
            ).fetchone()
            assert row == (False, None, None, None, None, None, None, None, None, None)
            nullable = manager.duckdb.execute(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'main'
                  AND table_name = '_extraction_journal'
                  AND column_name = 'w2_required'
                """
            ).fetchone()
            assert nullable == ("NO",)
        finally:
            manager.close()


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _open_authority_manager(tmp_path, name: str = "authority") -> DBManager:
    manager = DBManager(
        sqlite_path=tmp_path / f"{name}.sqlite",
        duckdb_path=tmp_path / f"{name}.duckdb",
    )
    manager._duckdb_conn = duckdb.connect(str(manager._duckdb_path))
    return manager


def _create_authority_schema(
    connection,
    *,
    replacement_specs=(),
) -> None:
    replacements = {spec.name: spec for spec in replacement_specs}
    for spec in db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE_SPECS:
        selected = replacements.get(spec.name, spec)
        connection.execute(db_module._table_ddl(selected))


def _insert_authority(
    connection,
    *,
    generation_sequence: int,
    envelope_sha256: str,
    generation_identity_sha256: str,
    prior_envelope_sha256: str | None,
) -> None:
    canonical_bytes = b"{}\n"
    connection.execute(
        f"""
        INSERT INTO {db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE} VALUES (
            1,
            'nbadb_verified_transform_output_disposition_authority_envelope',
            ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            generation_sequence,
            prior_envelope_sha256,
            envelope_sha256,
            generation_identity_sha256,
            _sha256(f"authored-authority-{generation_sequence}"),
            canonical_bytes,
            len(canonical_bytes),
            hashlib.sha256(canonical_bytes).hexdigest(),
        ],
    )


def _insert_receipt(connection, *, suffix: str = "one") -> None:
    canonical_bytes = b"{}\n"
    connection.execute(
        f"""
        INSERT INTO {db_module._TRANSFORM_OUTPUT_RECEIPT_TABLE} VALUES (
            1,
            'nbadb_transform_output_materialization_receipt',
            ?, ?, ?, 'fact_fictional_output', ?, ?, ?, ?, ?, ?, ?,
            'primary_working_duckdb', 0, ?, ?, ?, ?, ?
        )
        """,
        [
            _sha256(f"receipt-{suffix}"),
            f"materialization/{suffix}",
            _sha256(f"transaction-{suffix}"),
            _sha256(f"entry-{suffix}"),
            _sha256(f"policy-{suffix}"),
            _sha256(f"table-{suffix}"),
            _sha256(f"schema-{suffix}"),
            _sha256(f"transform-{suffix}"),
            _sha256(f"columns-{suffix}"),
            _sha256(f"dependency-{suffix}"),
            _sha256(f"attestation-schema-{suffix}"),
            _sha256(f"attestation-content-{suffix}"),
            canonical_bytes,
            len(canonical_bytes),
            hashlib.sha256(canonical_bytes).hexdigest(),
        ],
    )


def _insert_commitment(
    connection,
    *,
    suffix: str,
    envelope_sha256: str,
    generation_identity_sha256: str,
) -> None:
    canonical_bytes = b"{}\n"
    connection.execute(
        f"""
        INSERT INTO {db_module._TRANSFORM_OUTPUT_COMMITMENT_TABLE} VALUES (
            1,
            'nbadb_transform_output_operation_commitment',
            ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?
        )
        """,
        [
            _sha256(f"commitment-{suffix}"),
            _sha256(f"operation-{suffix}"),
            _sha256(f"transaction-{suffix}"),
            envelope_sha256,
            generation_identity_sha256,
            _sha256(f"authored-authority-{suffix}"),
            _sha256(f"operation-data-evidence-{suffix}"),
            _sha256(f"bindings-{suffix}"),
            _sha256(f"roots-{suffix}"),
            canonical_bytes,
            len(canonical_bytes),
            hashlib.sha256(canonical_bytes).hexdigest(),
        ],
    )


class TestTransformOutputAuthorityPersistence:
    def test_runtime_init_does_not_auto_install_authority_tables(self, initialized_db):
        classification = initialized_db.classify_transform_output_authority_persistence()

        assert classification.state is TransformOutputAuthorityPersistenceState.MIGRATION_REQUIRED
        assert classification.reason_code == "all_absent"

    def test_all_absent_installs_exact_empty_tables_once(self, tmp_path):
        manager = _open_authority_manager(tmp_path)
        try:
            before = manager.classify_transform_output_authority_persistence()
            installed = manager.install_transform_output_authority_persistence()
            repeated = manager.install_transform_output_authority_persistence()

            assert before.state is TransformOutputAuthorityPersistenceState.MIGRATION_REQUIRED
            assert before.reason_code == "all_absent"
            assert installed.state is TransformOutputAuthorityPersistenceState.ALREADY_CURRENT
            assert installed.reason_code == "all_exact"
            assert installed.table_row_counts == tuple(
                (table_name, 0) for table_name in db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLES
            )
            assert repeated == installed
        finally:
            manager.close()

    def test_exact_catalog_has_only_the_required_constraints_and_codec_bounds(
        self,
        tmp_path,
    ):
        manager = _open_authority_manager(tmp_path)
        try:
            manager.install_transform_output_authority_persistence()
            database_name = manager.duckdb.execute("SELECT current_database()").fetchone()[0]

            for spec in db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE_SPECS:
                assert (
                    db_module._observed_columns(
                        manager.duckdb,
                        database_name=database_name,
                        table_name=spec.name,
                    )
                    == spec.columns
                )
                assert db_module._observed_constraints(
                    manager.duckdb,
                    database_name=database_name,
                    spec=spec,
                ) == db_module._expected_constraints(spec)

            assert db_module._AUTHORITY_TABLE_SPEC.foreign_keys == ()
            assert db_module._RECEIPT_TABLE_SPEC.foreign_keys == ()
            assert tuple(column.name for column in db_module._AUTHORITY_TABLE_SPEC.columns) == (
                "schema_version",
                "kind",
                "generation_sequence",
                "prior_authority_envelope_sha256",
                "authority_envelope_sha256",
                "disposition_generation_identity_sha256",
                "authored_decision_authority_sha256",
                "canonical_bytes",
                "canonical_byte_length",
                "canonical_bytes_sha256",
            )
            assert tuple(column.name for column in db_module._COMMITMENT_TABLE_SPEC.columns) == (
                "schema_version",
                "kind",
                "commitment_sha256",
                "operation_identity_sha256",
                "transaction_generation_identity_sha256",
                "authority_envelope_sha256",
                "disposition_generation_identity_sha256",
                "authored_decision_authority_sha256",
                "operation_data_evidence_sha256",
                "binding_count",
                "binding_inventory_sha256",
                "current_root_inventory_sha256",
                "canonical_bytes",
                "canonical_byte_length",
                "canonical_bytes_sha256",
            )
            assert db_module._COMMITMENT_TABLE_SPEC.foreign_keys == (
                (
                    (
                        "authority_envelope_sha256",
                        "disposition_generation_identity_sha256",
                    ),
                    db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE,
                    (
                        "authority_envelope_sha256",
                        "disposition_generation_identity_sha256",
                    ),
                ),
            )
            maximums = {
                check.semantic_id: check.expression
                for spec in db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE_SPECS
                for check in spec.checks
                if check.semantic_id.endswith("canonical_byte_length_maximum")
            }
            assert maximums == {
                "authority:canonical_byte_length_maximum": ("canonical_byte_length <= 134217728"),
                "receipt:canonical_byte_length_maximum": ("canonical_byte_length <= 4194304"),
                "commitment:canonical_byte_length_maximum": ("canonical_byte_length <= 33554433"),
            }
        finally:
            manager.close()

    def test_exact_populated_tables_reopen_without_rewrite(self, tmp_path):
        manager = _open_authority_manager(tmp_path)
        database_path = manager._duckdb_path
        envelope_one = _sha256("envelope-one")
        envelope_two = _sha256("envelope-two")
        generation_one = _sha256("generation-one")
        generation_two = _sha256("generation-two")
        try:
            manager.install_transform_output_authority_persistence()
            _insert_authority(
                manager.duckdb,
                generation_sequence=1,
                envelope_sha256=envelope_one,
                generation_identity_sha256=generation_one,
                prior_envelope_sha256=None,
            )
            _insert_authority(
                manager.duckdb,
                generation_sequence=2,
                envelope_sha256=envelope_two,
                generation_identity_sha256=generation_two,
                prior_envelope_sha256=envelope_one,
            )
            _insert_receipt(manager.duckdb)
            _insert_commitment(
                manager.duckdb,
                suffix="one",
                envelope_sha256=envelope_two,
                generation_identity_sha256=generation_two,
            )
        finally:
            manager.close()

        reopened = DBManager(
            sqlite_path=tmp_path / "reopened.sqlite",
            duckdb_path=database_path,
        )
        reopened._duckdb_conn = duckdb.connect(str(database_path))
        try:
            classification = reopened.install_transform_output_authority_persistence()
            assert classification.state is TransformOutputAuthorityPersistenceState.ALREADY_CURRENT
            assert classification.table_row_counts == (
                (db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE, 2),
                (db_module._TRANSFORM_OUTPUT_RECEIPT_TABLE, 1),
                (db_module._TRANSFORM_OUTPUT_COMMITMENT_TABLE, 1),
            )
            assert reopened.duckdb.execute(
                f"SELECT generation_sequence, prior_authority_envelope_sha256 "
                f"FROM {db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE} "
                "ORDER BY generation_sequence"
            ).fetchall() == [(1, None), (2, envelope_one)]
        finally:
            reopened.close()

    def test_chain_is_not_a_self_fk_and_composite_authority_pair_is_exact(self, tmp_path):
        manager = _open_authority_manager(tmp_path)
        envelope_one = _sha256("envelope-one")
        envelope_two = _sha256("envelope-two")
        generation_one = _sha256("generation-one")
        generation_two = _sha256("generation-two")
        try:
            manager.install_transform_output_authority_persistence()
            _insert_authority(
                manager.duckdb,
                generation_sequence=1,
                envelope_sha256=envelope_one,
                generation_identity_sha256=generation_one,
                prior_envelope_sha256=None,
            )
            _insert_authority(
                manager.duckdb,
                generation_sequence=2,
                envelope_sha256=envelope_two,
                generation_identity_sha256=generation_two,
                prior_envelope_sha256=envelope_one,
            )
            _insert_receipt(manager.duckdb, suffix="unbound")

            with pytest.raises(duckdb.ConstraintException, match="foreign key"):
                _insert_commitment(
                    manager.duckdb,
                    suffix="crossed",
                    envelope_sha256=envelope_one,
                    generation_identity_sha256=generation_two,
                )
            _insert_commitment(
                manager.duckdb,
                suffix="exact",
                envelope_sha256=envelope_two,
                generation_identity_sha256=generation_two,
            )

            foreign_keys = manager.duckdb.execute(
                """
                SELECT table_name, constraint_column_names,
                       referenced_table, referenced_column_names
                FROM duckdb_constraints()
                WHERE constraint_type = 'FOREIGN KEY'
                  AND table_name IN ($1, $2, $3)
                """,
                list(db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLES),
            ).fetchall()
            assert foreign_keys == [
                (
                    db_module._TRANSFORM_OUTPUT_COMMITMENT_TABLE,
                    [
                        "authority_envelope_sha256",
                        "disposition_generation_identity_sha256",
                    ],
                    db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE,
                    [
                        "authority_envelope_sha256",
                        "disposition_generation_identity_sha256",
                    ],
                )
            ]
        finally:
            manager.close()

    @pytest.mark.parametrize(
        ("mutation", "expected_reason"),
        [
            ("partial", "partial_table_set"),
            ("extra_column", "column_shape_mismatch"),
            ("missing_column", "column_shape_mismatch"),
            ("reordered_columns", "column_shape_mismatch"),
            ("wrong_type", "column_shape_mismatch"),
            ("wrong_nullability", "column_shape_mismatch"),
            ("wrong_default", "column_shape_mismatch"),
            ("wrong_constraint", "constraint_shape_mismatch"),
            ("wrong_version", "constraint_shape_mismatch"),
        ],
    )
    def test_incompatible_persistent_shapes_require_repair(
        self,
        tmp_path,
        mutation,
        expected_reason,
    ):
        manager = _open_authority_manager(tmp_path, mutation)
        try:
            if mutation == "partial":
                manager.duckdb.execute(db_module._TRANSFORM_OUTPUT_AUTHORITY_DDL[0][1])
            else:
                receipt = db_module._RECEIPT_TABLE_SPEC
                replacement = receipt
                if mutation == "extra_column":
                    replacement = replace(
                        receipt,
                        columns=(*receipt.columns, db_module._ColumnSpec("unexpected", "BIGINT")),
                    )
                elif mutation == "missing_column":
                    missing = "attestation_content_sha256"
                    replacement = replace(
                        receipt,
                        columns=tuple(
                            column for column in receipt.columns if column.name != missing
                        ),
                        checks=tuple(
                            check for check in receipt.checks if missing not in check.columns
                        ),
                    )
                elif mutation == "reordered_columns":
                    columns = list(receipt.columns)
                    columns[2], columns[3] = columns[3], columns[2]
                    replacement = replace(receipt, columns=tuple(columns))
                elif mutation == "wrong_type":
                    replacement = replace(
                        receipt,
                        columns=tuple(
                            replace(column, data_type="INTEGER")
                            if column.name == "attestation_row_count"
                            else column
                            for column in receipt.columns
                        ),
                    )
                elif mutation == "wrong_nullability":
                    replacement = replace(
                        receipt,
                        columns=tuple(
                            replace(column, nullable=True)
                            if column.name == "attestation_row_count"
                            else column
                            for column in receipt.columns
                        ),
                    )
                elif mutation == "wrong_default":
                    replacement = replace(
                        receipt,
                        columns=tuple(
                            replace(column, default="1")
                            if column.name == "schema_version"
                            else column
                            for column in receipt.columns
                        ),
                    )
                elif mutation in {"wrong_constraint", "wrong_version"}:
                    target = (
                        "receipt:attestation_row_count"
                        if mutation == "wrong_constraint"
                        else "receipt:schema_version"
                    )
                    expression = (
                        "attestation_row_count > 0"
                        if mutation == "wrong_constraint"
                        else "schema_version = 2"
                    )
                    replacement = replace(
                        receipt,
                        checks=tuple(
                            replace(check, expression=expression)
                            if check.semantic_id == target
                            else check
                            for check in receipt.checks
                        ),
                    )
                _create_authority_schema(manager.duckdb, replacement_specs=(replacement,))

            classification = manager.install_transform_output_authority_persistence()
            assert classification.state is TransformOutputAuthorityPersistenceState.REPAIR_REQUIRED
            assert classification.reason_code == expected_reason
        finally:
            manager.close()

    @pytest.mark.parametrize("conflict_kind", ["persistent_view", "temporary_shadow"])
    def test_view_and_temporary_shadow_conflicts_require_repair(
        self,
        tmp_path,
        conflict_kind,
    ):
        manager = _open_authority_manager(tmp_path, conflict_kind)
        try:
            if conflict_kind == "persistent_view":
                manager.duckdb.execute(
                    f"CREATE VIEW {db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE} AS SELECT 1"
                )
            else:
                _create_authority_schema(manager.duckdb)
                manager.duckdb.execute(
                    f"CREATE TEMP TABLE {db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE} "
                    "(shadow INTEGER)"
                )

            classification = manager.install_transform_output_authority_persistence()
            assert classification.state is TransformOutputAuthorityPersistenceState.REPAIR_REQUIRED
            assert classification.reason_code == "view_or_temporary_conflict"
        finally:
            manager.close()

    @pytest.mark.parametrize(
        ("object_kind", "expected_reason"),
        [
            ("persistent_table", "partial_table_set"),
            ("persistent_view", "view_or_temporary_conflict"),
            ("temporary_table", "view_or_temporary_conflict"),
            ("temporary_view", "view_or_temporary_conflict"),
        ],
    )
    def test_case_variant_authority_names_are_never_classified_absent(
        self,
        tmp_path,
        object_kind,
        expected_reason,
    ):
        manager = _open_authority_manager(tmp_path, f"case-variant-{object_kind}")
        case_variant = db_module._TRANSFORM_OUTPUT_AUTHORITY_TABLE.upper()
        try:
            if object_kind == "persistent_table":
                manager.duckdb.execute(f'CREATE TABLE "{case_variant}" (shadow INTEGER)')
            elif object_kind == "persistent_view":
                manager.duckdb.execute(f'CREATE VIEW "{case_variant}" AS SELECT 1')
            elif object_kind == "temporary_view":
                manager.duckdb.execute(f'CREATE TEMP VIEW "{case_variant}" AS SELECT 1')
            else:
                manager.duckdb.execute(f'CREATE TEMP TABLE "{case_variant}" (shadow INTEGER)')

            classification = manager.install_transform_output_authority_persistence()
            assert classification.state is TransformOutputAuthorityPersistenceState.REPAIR_REQUIRED
            assert classification.reason_code == expected_reason
        finally:
            manager.close()

    def test_caller_transaction_is_left_untouched(self, tmp_path):
        manager = _open_authority_manager(tmp_path)
        try:
            manager.duckdb.execute("BEGIN TRANSACTION")
            manager.duckdb.execute("CREATE TEMP TABLE caller_sentinel (value INTEGER)")
            manager.duckdb.execute("INSERT INTO caller_sentinel VALUES (17)")

            with pytest.raises(
                TransformOutputAuthorityPersistenceError,
                match="refuses a caller-owned",
            ) as caught:
                manager.install_transform_output_authority_persistence()

            assert caught.value.transaction_state.value == "not_started"
            assert manager.duckdb.execute("SELECT * FROM caller_sentinel").fetchall() == [(17,)]
            manager.duckdb.execute("ROLLBACK")
            assert manager.classify_transform_output_authority_persistence().state is (
                TransformOutputAuthorityPersistenceState.MIGRATION_REQUIRED
            )
        finally:
            manager.close()

    @pytest.mark.parametrize(
        "event",
        [
            "after_create_authority",
            "after_create_receipts",
            "after_create_commitments",
            "after_catalog_validation",
            "after_empty_readback",
            "before_commit",
        ],
    )
    def test_every_precommit_fault_rolls_back_and_releases_the_lock(
        self,
        tmp_path,
        event,
    ):
        manager = _open_authority_manager(tmp_path, event)

        def fail(selected_event):
            if selected_event == event:
                raise RuntimeError(f"injected {event}")

        try:
            with pytest.raises(
                TransformOutputAuthorityPersistenceError,
                match="rolled back",
            ) as caught:
                db_module._install_transform_output_authority_persistence(
                    manager,
                    fault_injector=fail,
                )

            assert caught.value.transaction_state.value == "begun"
            assert caught.value.classification is not None
            assert caught.value.classification.state is (
                TransformOutputAuthorityPersistenceState.MIGRATION_REQUIRED
            )
            assert manager.classify_transform_output_authority_persistence().state is (
                TransformOutputAuthorityPersistenceState.MIGRATION_REQUIRED
            )
            manager.duckdb.execute("BEGIN TRANSACTION")
            manager.duckdb.execute("ROLLBACK")
            assert manager.install_transform_output_authority_persistence().state is (
                TransformOutputAuthorityPersistenceState.ALREADY_CURRENT
            )
        finally:
            manager.close()

    def test_postcommit_fault_reports_committed_exact_state(self, tmp_path):
        manager = _open_authority_manager(tmp_path)

        def fail(event):
            if event == "after_commit":
                raise RuntimeError("injected after commit")

        try:
            with pytest.raises(
                TransformOutputAuthorityPersistenceError,
                match="committed but post-commit validation failed",
            ) as caught:
                db_module._install_transform_output_authority_persistence(
                    manager,
                    fault_injector=fail,
                )
            assert caught.value.transaction_state.value == "committed"
            assert caught.value.classification is not None
            assert caught.value.classification.state is (
                TransformOutputAuthorityPersistenceState.ALREADY_CURRENT
            )
            assert manager.install_transform_output_authority_persistence().state is (
                TransformOutputAuthorityPersistenceState.ALREADY_CURRENT
            )
        finally:
            manager.close()

    @pytest.mark.parametrize(
        ("commit_outcome", "expected_state", "raises"),
        [
            ("absent", TransformOutputAuthorityPersistenceState.MIGRATION_REQUIRED, True),
            ("exact", TransformOutputAuthorityPersistenceState.ALREADY_CURRENT, False),
            ("mixed", TransformOutputAuthorityPersistenceState.REPAIR_REQUIRED, True),
        ],
    )
    def test_commit_exception_reopens_and_classifies_file_backed_state(
        self,
        tmp_path,
        monkeypatch,
        commit_outcome,
        expected_state,
        raises,
    ):
        manager = _open_authority_manager(tmp_path, f"commit-{commit_outcome}")
        original_connection = manager.duckdb

        def uncertain_commit(connection):
            if commit_outcome != "absent":
                connection.execute("COMMIT")
            if commit_outcome == "mixed":
                connection.execute(f"DROP TABLE {db_module._TRANSFORM_OUTPUT_COMMITMENT_TABLE}")
            raise RuntimeError(f"uncertain {commit_outcome}")

        monkeypatch.setattr(
            db_module,
            "_commit_transform_output_authority_install",
            uncertain_commit,
        )
        try:
            if raises:
                with pytest.raises(
                    TransformOutputAuthorityPersistenceError,
                    match="commit was uncertain",
                ) as caught:
                    manager.install_transform_output_authority_persistence()
                assert caught.value.transaction_state.value == "commit_attempted"
                assert caught.value.classification is not None
                assert caught.value.classification.state is expected_state
            else:
                result = manager.install_transform_output_authority_persistence()
                assert result.state is expected_state

            assert manager.duckdb is not original_connection
            assert manager.classify_transform_output_authority_persistence().state is expected_state
            with pytest.raises(duckdb.ConnectionException):
                original_connection.execute("SELECT 1")
        finally:
            manager.close()

    def test_same_process_installers_are_serialized_by_the_module_lock(self, tmp_path):
        first_inside = threading.Event()
        release_first = threading.Event()
        second_inside = threading.Event()
        failures = []

        def install(name, *, block, entered):
            manager = _open_authority_manager(tmp_path, name)

            def observe(event):
                if event == "after_create_authority":
                    entered.set()
                    if block:
                        assert release_first.wait(5)

            try:
                db_module._install_transform_output_authority_persistence(
                    manager,
                    fault_injector=observe,
                )
            except BaseException as exc:
                failures.append(exc)
            finally:
                manager.close()

        first = threading.Thread(
            target=install,
            kwargs={"name": "lock-first", "block": True, "entered": first_inside},
        )
        second = threading.Thread(
            target=install,
            kwargs={"name": "lock-second", "block": False, "entered": second_inside},
        )
        first.start()
        assert first_inside.wait(5)
        second.start()
        assert not second_inside.wait(0.2)
        release_first.set()
        first.join(10)
        second.join(10)

        assert not first.is_alive()
        assert not second.is_alive()
        assert failures == []
        assert second_inside.is_set()


class TestSession:
    def test_session_yields_session(self, initialized_db):
        with initialized_db.session() as s:
            assert isinstance(s, Session)


class TestClose:
    def test_close_disposes_connections(self, db):
        db.init()
        db.close()  # should not raise

    def test_close_before_init_does_not_raise(self, db):
        db.close()  # _engine and _duckdb_conn are None — should be a no-op


class TestContextManager:
    def test_context_manager(self, tmp_path):
        with DBManager(
            sqlite_path=tmp_path / "cm.sqlite",
            duckdb_path=tmp_path / "cm.duckdb",
        ) as db:
            assert isinstance(db.engine, Engine)
            assert db.duckdb is not None

    def test_context_manager_files_created(self, tmp_path):
        with DBManager(
            sqlite_path=tmp_path / "cm.sqlite",
            duckdb_path=tmp_path / "cm.duckdb",
        ):
            pass
        assert (tmp_path / "cm.sqlite").exists()
        assert (tmp_path / "cm.duckdb").exists()


class TestSQLitePragmas:
    def test_sqlite_wal_mode(self, initialized_db):
        with initialized_db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).fetchone()
        assert result[0] == "wal"


class TestDoubleInit:
    def test_second_init_does_not_raise(self, db):
        db.init()
        db.init()  # second call should not error
        db.close()


class TestGetUserTables:
    def test_returns_user_tables_only(self, initialized_db):
        from nbadb.core.db import get_user_tables

        # Create a user table
        initialized_db.duckdb.execute("CREATE TABLE my_table (id INT)")
        tables = get_user_tables(initialized_db.duckdb)
        assert "my_table" in tables
        # Internal tables (prefixed with _) should be excluded
        assert all(not t.startswith("_") for t in tables)

    def test_empty_when_no_user_tables(self, initialized_db):
        from nbadb.core.db import get_user_tables

        tables = get_user_tables(initialized_db.duckdb)
        assert tables == []

    def test_sorted_output(self, initialized_db):
        from nbadb.core.db import get_user_tables

        initialized_db.duckdb.execute("CREATE TABLE z_table (id INT)")
        initialized_db.duckdb.execute("CREATE TABLE a_table (id INT)")
        tables = get_user_tables(initialized_db.duckdb)
        assert tables == sorted(tables)


class TestDBManagerDefaultPaths:
    def test_defaults_from_settings(self, tmp_path, monkeypatch):
        """DBManager uses settings defaults when paths not provided."""
        from nbadb.core.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("NBADB_SQLITE_PATH", str(tmp_path / "s.sqlite"))
        monkeypatch.setenv("NBADB_DUCKDB_PATH", str(tmp_path / "d.duckdb"))
        get_settings.cache_clear()
        db = DBManager()
        db.init()
        db.close()
        get_settings.cache_clear()
        assert (tmp_path / "s.sqlite").exists()
        assert (tmp_path / "d.duckdb").exists()

    def test_init_raises_when_sqlite_path_is_none(self, monkeypatch):
        """init() raises ValueError when sqlite_path resolves to None."""
        from unittest.mock import patch

        from nbadb.core.config import get_settings

        get_settings.cache_clear()
        mock_settings = MagicMock()
        mock_settings.sqlite_path = None
        mock_settings.duckdb_path = None
        with patch("nbadb.core.db.get_settings", return_value=mock_settings):
            db = DBManager(sqlite_path=None, duckdb_path=None)
            with pytest.raises(ValueError, match="sqlite_path required"):
                db.init()
        get_settings.cache_clear()


class TestApplySqlitePragmasBeforeInit:
    def test_pragmas_raises_before_engine(self, db):
        with pytest.raises(RuntimeError, match="not initialized"):
            db._apply_sqlite_pragmas()


class TestCreatePipelineTablesBeforeInit:
    def test_raises_before_duckdb(self, db):
        with pytest.raises(RuntimeError, match="not initialized"):
            db._create_pipeline_tables()
