from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pytest

import nbadb.orchestrate.successor_transform_authority as authority_module
from nbadb.orchestrate.successor_transform_authority import (
    SuccessorTransformAuthorityError,
    _attest_exact_tables,
    build_successor_transform_attestations,
    build_transform_relation_attestations,
)


def _attest(
    connection: duckdb.DuckDBPyConnection,
    tmp_path: Path,
    table: str = "sample",
):
    observed = tmp_path.stat()
    return _attest_exact_tables(
        connection,
        (table,),
        scratch_parent=tmp_path.resolve(),
        expected_scratch_parent_identity=(observed.st_dev, observed.st_ino),
        transform_scratch_max_bytes=16 * 1024 * 1024,
    )[0]


def _attest_relations(
    connection: duckdb.DuckDBPyConnection,
    tmp_path: Path,
    relations: tuple[tuple[str, str], ...],
):
    observed = tmp_path.stat()
    return build_transform_relation_attestations(
        connection,
        relations,
        scratch_parent=tmp_path.resolve(),
        expected_scratch_parent_identity=(observed.st_dev, observed.st_ino),
        transform_scratch_max_bytes=16 * 1024 * 1024,
    )


def test_candidate_and_canonical_physical_tables_have_identical_semantic_authority(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE canonical_output (id BIGINT, label VARCHAR)")
        connection.execute("INSERT INTO canonical_output VALUES (1, 'a'), (2, 'b')")
        connection.execute("CREATE TABLE hidden_candidate AS SELECT * FROM canonical_output")
        canonical = _attest_relations(
            connection, tmp_path, (("canonical_output", "canonical_output"),)
        )[0]
        candidate = _attest_relations(
            connection, tmp_path, (("hidden_candidate", "canonical_output"),)
        )[0]
    finally:
        connection.close()

    assert candidate == canonical
    assert "hidden_candidate" not in candidate.to_dict().values()


def test_physical_rename_is_invariant_but_semantic_rename_changes_both_roots(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE physical_one (id BIGINT)")
        connection.execute("INSERT INTO physical_one VALUES (1), (2)")
        first = _attest_relations(connection, tmp_path, (("physical_one", "semantic"),))[0]
        connection.execute("ALTER TABLE physical_one RENAME TO physical_two")
        renamed_physical = _attest_relations(connection, tmp_path, (("physical_two", "semantic"),))[
            0
        ]
        renamed_semantic = _attest_relations(
            connection, tmp_path, (("physical_two", "semantic_other"),)
        )[0]
    finally:
        connection.close()

    assert renamed_physical == first
    assert renamed_semantic.table_name == "semantic_other"
    assert renamed_semantic.schema_sha256 != first.schema_sha256
    assert renamed_semantic.content_sha256 != first.content_sha256


@pytest.mark.parametrize(
    "relations,match",
    [
        ([], "exact tuple"),
        ((["sample", "semantic"],), "exact tuple"),
        ((("sample", "semantic", "extra"),), "exact tuple"),
        ((("sample", "semantic"), ("sample", "other")), "physical .* duplicated"),
        ((("sample", "semantic"), ("other", "semantic")), "semantic .* duplicated"),
    ],
)
def test_relation_authority_rejects_foreign_shapes_and_cross_maps(
    tmp_path: Path,
    relations: object,
    match: str,
) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (id BIGINT)")
        connection.execute("CREATE TABLE other (id BIGINT)")
        with pytest.raises(SuccessorTransformAuthorityError, match=match):
            _attest_relations(connection, tmp_path, relations)  # type: ignore[arg-type]
    finally:
        connection.close()


def test_relation_authority_orders_by_semantic_name_and_accepts_empty_table(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE physical_z (id BIGINT NOT NULL)")
        connection.execute("CREATE TABLE physical_a (id BIGINT NOT NULL)")
        result = _attest_relations(
            connection,
            tmp_path,
            (("physical_z", "semantic_z"), ("physical_a", "semantic_a")),
        )
    finally:
        connection.close()

    assert tuple(item.table_name for item in result) == ("semantic_a", "semantic_z")
    assert tuple(item.row_count for item in result) == (0, 0)


@pytest.mark.parametrize("relation_kind", ["missing", "view", "temporary"])
def test_relation_authority_rejects_missing_view_or_temporary_physical_relation(
    tmp_path: Path,
    relation_kind: str,
) -> None:
    connection = duckdb.connect()
    try:
        if relation_kind == "view":
            connection.execute("CREATE VIEW candidate AS SELECT 1 AS id")
        elif relation_kind == "temporary":
            connection.execute("CREATE TEMP TABLE candidate (id BIGINT)")
        with pytest.raises(
            SuccessorTransformAuthorityError,
            match="absent, ambiguous, temporary, or a view",
        ):
            _attest_relations(connection, tmp_path, (("candidate", "semantic"),))
    finally:
        connection.close()


def test_same_name_helper_is_byte_compatible_with_existing_exact_table_builder(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (id BIGINT, label VARCHAR)")
        connection.execute("INSERT INTO sample VALUES (1, 'a')")
        existing = _attest(connection, tmp_path)
        mapped = _attest_relations(connection, tmp_path, (("sample", "sample"),))[0]
    finally:
        connection.close()

    assert mapped == existing


def test_row_order_does_not_change_content_identity(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (id BIGINT, label VARCHAR)")
        connection.execute("INSERT INTO sample VALUES (2, 'b'), (1, 'a'), (3, 'c')")
        first = _attest(connection, tmp_path)
        connection.execute("DELETE FROM sample")
        connection.execute("INSERT INTO sample VALUES (3, 'c'), (2, 'b'), (1, 'a')")
        second = _attest(connection, tmp_path)
    finally:
        connection.close()

    assert first == second


def test_duplicate_row_changes_multiset_identity(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (id BIGINT, label VARCHAR)")
        connection.execute("INSERT INTO sample VALUES (1, 'a')")
        one = _attest(connection, tmp_path)
        connection.execute("INSERT INTO sample VALUES (1, 'a')")
        two = _attest(connection, tmp_path)
    finally:
        connection.close()

    assert one.row_count == 1
    assert two.row_count == 2
    assert one.content_sha256 != two.content_sha256


def test_float_special_values_and_null_are_distinct(tmp_path: Path) -> None:
    connection = duckdb.connect()
    expressions = (
        "NULL",
        "'NaN'::DOUBLE",
        "'Infinity'::DOUBLE",
        "'-Infinity'::DOUBLE",
        "0.0::DOUBLE",
        "-0.0::DOUBLE",
    )
    try:
        connection.execute("CREATE TABLE sample (value DOUBLE)")
        identities: list[str] = []
        for expression in expressions:
            connection.execute("DELETE FROM sample")
            connection.execute(f"INSERT INTO sample VALUES ({expression})")
            identities.append(_attest(connection, tmp_path).content_sha256)
    finally:
        connection.close()

    assert len(set(identities)) == len(expressions)


def test_ordered_schema_name_and_type_drift_change_identity(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (value BIGINT)")
        connection.execute("INSERT INTO sample VALUES (1)")
        integer = _attest(connection, tmp_path)
        connection.execute("DROP TABLE sample")
        connection.execute("CREATE TABLE sample (renamed DOUBLE)")
        connection.execute("INSERT INTO sample VALUES (1.0)")
        floating = _attest(connection, tmp_path)
    finally:
        connection.close()

    assert integer.schema_sha256 != floating.schema_sha256
    assert integer.content_sha256 != floating.content_sha256


def test_column_order_drift_changes_schema_identity(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (first BIGINT, second BIGINT)")
        connection.execute("INSERT INTO sample VALUES (1, 2)")
        original = _attest(connection, tmp_path)
        connection.execute("DROP TABLE sample")
        connection.execute("CREATE TABLE sample (second BIGINT, first BIGINT)")
        connection.execute("INSERT INTO sample VALUES (2, 1)")
        reordered = _attest(connection, tmp_path)
    finally:
        connection.close()

    assert original.schema_sha256 != reordered.schema_sha256


def test_column_name_only_drift_changes_schema_identity(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (value BIGINT)")
        connection.execute("INSERT INTO sample VALUES (1)")
        original = _attest(connection, tmp_path)
        connection.execute("DROP TABLE sample")
        connection.execute("CREATE TABLE sample (renamed BIGINT)")
        connection.execute("INSERT INTO sample VALUES (1)")
        renamed = _attest(connection, tmp_path)
    finally:
        connection.close()

    assert original.schema_sha256 != renamed.schema_sha256


def test_column_type_only_drift_changes_schema_identity(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (value BIGINT)")
        connection.execute("INSERT INTO sample VALUES (1)")
        integer = _attest(connection, tmp_path)
        connection.execute("DROP TABLE sample")
        connection.execute("CREATE TABLE sample (value DOUBLE)")
        connection.execute("INSERT INTO sample VALUES (1.0)")
        floating = _attest(connection, tmp_path)
    finally:
        connection.close()

    assert integer.schema_sha256 != floating.schema_sha256


def test_nested_types_fail_closed_before_row_readback(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (values INTEGER[])")
        connection.execute("INSERT INTO sample VALUES ([1, 2])")
        with pytest.raises(SuccessorTransformAuthorityError, match="nested .* unsupported"):
            _attest(connection, tmp_path)
    finally:
        connection.close()


def test_scratch_authority_must_be_absolute(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (id BIGINT)")
        with pytest.raises(SuccessorTransformAuthorityError, match="must be absolute"):
            _attest_exact_tables(
                connection,
                ("sample",),
                scratch_parent=Path("relative"),
                expected_scratch_parent_identity=(1, 1),
                transform_scratch_max_bytes=1,
            )
    finally:
        connection.close()


def test_private_scratch_is_removed_after_success(tmp_path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (id BIGINT)")
        connection.execute("INSERT INTO sample VALUES (1)")
        _attest(connection, tmp_path)
    finally:
        connection.close()

    assert not list(tmp_path.glob("nbadb-successor-transform-*"))


def test_production_builder_rejects_missing_schema_backed_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE table_000 (id BIGINT)")
    monkeypatch.setattr(
        authority_module,
        "expected_transform_output_tables",
        lambda *, include_live: frozenset({"table_000", "table_001"}),
    )
    try:
        with pytest.raises(SuccessorTransformAuthorityError, match="missing=table_001"):
            build_successor_transform_attestations(
                connection,
                scratch_parent=tmp_path.resolve(),
                expected_scratch_parent_identity=(
                    tmp_path.stat().st_dev,
                    tmp_path.stat().st_ino,
                ),
                transform_scratch_max_bytes=16 * 1024 * 1024,
            )
    finally:
        connection.close()


def test_production_builder_attests_exact_schema_backed_universe_at_any_cardinality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = frozenset({"table_000", "table_001", "table_002"})
    monkeypatch.setattr(
        authority_module,
        "expected_transform_output_tables",
        lambda *, include_live: expected,
    )
    connection = duckdb.connect()
    try:
        for table in sorted(expected):
            connection.execute(f'CREATE TABLE "{table}" (id BIGINT)')
        result = build_successor_transform_attestations(
            connection,
            scratch_parent=tmp_path.resolve(),
            expected_scratch_parent_identity=(
                tmp_path.stat().st_dev,
                tmp_path.stat().st_ino,
            ),
            transform_scratch_max_bytes=16 * 1024 * 1024,
        )
    finally:
        connection.close()

    assert len(result) == len(expected)
    assert tuple(item.table_name for item in result) == tuple(sorted(expected))
    assert all(item.row_count == 0 for item in result)


def test_transform_scratch_disables_unbound_engine_spill_and_cleans(tmp_path: Path) -> None:
    observed = tmp_path.stat()

    with authority_module._private_scratch(
        tmp_path.resolve(),
        expected_scratch_parent_identity=(observed.st_dev, observed.st_ino),
        transform_scratch_max_bytes=1,
    ) as scratch:
        assert scratch.connection.execute(
            "SELECT current_setting('temp_directory'), current_setting('max_temp_directory_size')"
        ).fetchone() == ("", "0 bytes")
        assert scratch.max_bytes == 1
        assert authority_module._require_scratch(scratch, stage="test exact boundary") == 0

    assert not list(tmp_path.glob("nbadb-successor-transform-*"))


def test_transform_scratch_rejects_foreign_authority_and_invalid_cap_before_temp(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE sample (id BIGINT)")
    observed = tmp_path.stat()
    try:
        with pytest.raises(SuccessorTransformAuthorityError, match="differs from expected"):
            _attest_exact_tables(
                connection,
                ("sample",),
                scratch_parent=tmp_path.resolve(),
                expected_scratch_parent_identity=(observed.st_dev, observed.st_ino + 1),
                transform_scratch_max_bytes=1,
            )
        with pytest.raises(SuccessorTransformAuthorityError, match="positive signed-63"):
            _attest_exact_tables(
                connection,
                ("sample",),
                scratch_parent=tmp_path.resolve(),
                expected_scratch_parent_identity=(observed.st_dev, observed.st_ino),
                transform_scratch_max_bytes=0,
            )
    finally:
        connection.close()

    assert not list(tmp_path.glob("nbadb-successor-transform-*"))


def test_transform_spill_over_cap_cleans_and_allows_reentry(tmp_path: Path) -> None:
    observed = tmp_path.stat()

    with (
        pytest.raises(SuccessorTransformAuthorityError, match="transform_scratch_max_bytes"),
        authority_module._private_scratch(
            tmp_path.resolve(),
            expected_scratch_parent_identity=(observed.st_dev, observed.st_ino),
            transform_scratch_max_bytes=1,
        ) as scratch,
    ):
        descriptor = os.open(
            "forced-spill",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=scratch.spill_descriptor,
        )
        try:
            assert os.write(descriptor, b"xx") == 2
        finally:
            os.close(descriptor)
        authority_module._require_scratch(scratch, stage="forced over-cap spill")

    assert not list(tmp_path.glob("nbadb-successor-transform-*"))
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE sample (id BIGINT)")
        connection.execute("INSERT INTO sample VALUES (1)")
        assert _attest(connection, tmp_path).row_count == 1
    finally:
        connection.close()
    assert not list(tmp_path.glob("nbadb-successor-transform-*"))


def test_transform_scratch_root_substitution_never_writes_replacement(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    held = tmp_path / "scratch-held"
    scratch.mkdir(mode=0o700)
    observed = scratch.stat()
    try:
        with (
            pytest.raises(SuccessorTransformAuthorityError, match="scratch parent changed"),
            authority_module._private_scratch(
                scratch.resolve(),
                expected_scratch_parent_identity=(observed.st_dev, observed.st_ino),
                transform_scratch_max_bytes=1024,
            ) as authority,
        ):
            scratch.rename(held)
            scratch.mkdir(mode=0o700)
            authority_module._require_scratch(authority, stage="root substitution")
        assert list(scratch.iterdir()) == []
        assert list(held.iterdir()) == []
    finally:
        scratch.rmdir()
        held.rename(scratch)


def test_disabled_transform_spill_cannot_follow_an_external_symlink(tmp_path: Path) -> None:
    scratch_parent = tmp_path / "scratch"
    external = tmp_path / "external"
    scratch_parent.mkdir(mode=0o700)
    external.mkdir(mode=0o700)
    observed = scratch_parent.stat()

    with authority_module._private_scratch(
        scratch_parent.resolve(),
        expected_scratch_parent_identity=(observed.st_dev, observed.st_ino),
        transform_scratch_max_bytes=128 * 1024 * 1024,
    ) as scratch:
        scratch.connection.execute("SET memory_limit = '10MB'")
        authority_module._require_scratch(scratch, stage="before substitution race")
        spill = scratch_parent / scratch.name / "spill"
        held = scratch_parent / scratch.name / "spill-held"
        spill.rename(held)
        spill.symlink_to(external, target_is_directory=True)
        try:
            with pytest.raises(duckdb.OutOfMemoryException):
                scratch.connection.execute(
                    "CREATE TEMP TABLE forced_spill AS "
                    "SELECT i, repeat(md5(i::VARCHAR), 4) AS payload "
                    "FROM range(1000000) AS source(i)"
                )
            assert list(external.iterdir()) == []
        finally:
            spill.unlink()
            held.rename(spill)

    assert list(external.iterdir()) == []
    assert not list(scratch_parent.glob("nbadb-successor-transform-*"))


def test_transform_cleanup_never_removes_a_post_final_proof_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE sample (id BIGINT)")
    connection.execute("INSERT INTO sample VALUES (1)")
    original = authority_module._require_named_child
    substituted_name: str | None = None
    held: Path | None = None

    def substitute_after_final_proof(
        parent_descriptor: int,
        name: str,
        descriptor: int,
        expected: tuple[int, int, int, int],
        *,
        label: str,
        stage: str,
    ) -> None:
        nonlocal substituted_name, held
        original(
            parent_descriptor,
            name,
            descriptor,
            expected,
            label=label,
            stage=stage,
        )
        if (
            substituted_name is None
            and label == "successor transform private scratch"
            and stage == "cleanup"
        ):
            current = tmp_path / name
            held = tmp_path / f"{name}-held"
            substituted_name = name
            current.rename(held)
            current.mkdir(mode=0o700)

    monkeypatch.setattr(authority_module, "_require_named_child", substitute_after_final_proof)
    try:
        with pytest.raises(SuccessorTransformAuthorityError, match="replaced at quarantine"):
            _attest(connection, tmp_path)
        assert substituted_name is not None
        assert held is not None
        replacement = held.with_name(substituted_name)
        assert replacement.is_dir()
        assert list(replacement.iterdir()) == []
        assert held.is_dir()
        replacement.rmdir()
        held.rmdir()
        assert _attest(connection, tmp_path).row_count == 1
        assert not list(tmp_path.glob("nbadb-successor-transform-*"))
    finally:
        connection.close()


def test_transform_memory_exhaustion_surfaces_disabled_spill_constraint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect()
    connection.execute("CREATE TABLE sample (id BIGINT)")
    connection.execute("INSERT INTO sample VALUES (1)")

    def exhaust_memory(_scratch, _digests) -> None:
        raise duckdb.OutOfMemoryException("synthetic exhaustion")

    monkeypatch.setattr(authority_module, "_insert_hash_batch", exhaust_memory)
    try:
        with pytest.raises(
            SuccessorTransformAuthorityError,
            match="external transform spill is disabled.*cannot be bound",
        ):
            _attest(connection, tmp_path)
    finally:
        connection.close()

    assert not list(tmp_path.glob("nbadb-successor-transform-*"))
