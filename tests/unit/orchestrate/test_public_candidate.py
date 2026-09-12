from __future__ import annotations

import csv
import sqlite3
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.orchestrate.public_candidate import (
    CandidateRelationSpec,
    PublicCandidateError,
    build_public_candidate,
)

if TYPE_CHECKING:
    from pathlib import Path


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "private.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE TABLE public_relation (z_label VARCHAR, a_id BIGINT)")
        connection.execute("INSERT INTO public_relation VALUES ('alpha', 1), ('beta', 2)")
        connection.execute("CREATE TABLE undeclared_relation (secret VARCHAR)")
        connection.execute("INSERT INTO undeclared_relation VALUES ('private')")
        connection.execute("CREATE TABLE raw_nba_api_parser_input_object (stored_payload BLOB)")
        connection.execute("INSERT INTO raw_nba_api_parser_input_object VALUES (from_hex('0102'))")
        connection.execute("CHECKPOINT")
    return path


def test_builds_fresh_allowlist_candidate_and_excludes_private_source(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    target = tmp_path / "candidate"

    build = build_public_candidate(
        source_duckdb=source,
        target_root=target,
        relation_specs=(CandidateRelationSpec("public_relation", "curated"),),
    )

    assert build.root == target
    assert [entry.table_name for entry in build.disposition.relation_entries] == ["public_relation"]
    assert build.disposition.relation_entries[0].ordered_columns == ("a_id", "z_label")
    assert (target / "public-data-disposition.json").is_file()
    assert (target / "nba.duckdb").is_file()
    assert (target / "nba.sqlite").is_file()
    assert (target / "csv/public_relation.csv").is_file()
    assert (target / "parquet/public_relation.parquet").is_file()

    with duckdb.connect(str(target / "nba.duckdb"), read_only=True) as connection:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        duckdb_rows = connection.execute(
            "SELECT a_id, z_label FROM public_relation ORDER BY a_id"
        ).fetchall()
        parquet_rows = connection.execute(
            "SELECT a_id, z_label FROM read_parquet(?) ORDER BY a_id",
            [str(target / "parquet/public_relation.parquet")],
        ).fetchall()
    assert names == {"public_relation"}
    assert duckdb_rows == parquet_rows == [(1, "alpha"), (2, "beta")]

    with sqlite3.connect(target / "nba.sqlite") as connection:
        sqlite_rows = connection.execute(
            "SELECT a_id, z_label FROM public_relation ORDER BY a_id"
        ).fetchall()
    assert sqlite_rows == duckdb_rows

    with (target / "csv/public_relation.csv").open(newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert csv_rows == [
        {"a_id": "1", "z_label": "alpha"},
        {"a_id": "2", "z_label": "beta"},
    ]
    paths = {entry.path for entry in build.disposition.resource_entries}
    assert paths == {
        "nba.duckdb",
        "nba.sqlite",
        "csv/public_relation.csv",
        "parquet/public_relation.parquet",
    }
    assert not any("raw_nba_api_parser_input_object" in path for path in paths)
    assert "undeclared_relation" not in names


def test_rejects_every_private_exact_four_relation() -> None:
    private_names = (
        "raw_nba_api_parser_input_object",
        "raw_nba_api_request_observation",
        "raw_nba_api_result_occurrence",
        "raw_nba_api_observation_route_landing",
    )
    for table_name in private_names:
        with pytest.raises(PublicCandidateError, match="private provider-body"):
            CandidateRelationSpec(table_name, "raw")


def test_rejects_existing_target_root(tmp_path: Path) -> None:
    source = _source(tmp_path)
    target = tmp_path / "candidate"
    target.mkdir()
    with pytest.raises(PublicCandidateError, match="must not already exist"):
        build_public_candidate(
            source_duckdb=source,
            target_root=target,
            relation_specs=(CandidateRelationSpec("public_relation", "curated"),),
        )


def test_rejects_binary_public_relation(tmp_path: Path) -> None:
    source = tmp_path / "binary.duckdb"
    with duckdb.connect(str(source)) as connection:
        connection.execute("CREATE TABLE binary_relation (payload BLOB)")
        connection.execute("CHECKPOINT")
    with pytest.raises(PublicCandidateError, match="binary physical type"):
        build_public_candidate(
            source_duckdb=source,
            target_root=tmp_path / "candidate",
            relation_specs=(CandidateRelationSpec("binary_relation", "curated"),),
        )


def test_requires_sorted_unique_positive_allowlist(tmp_path: Path) -> None:
    source = _source(tmp_path)
    with pytest.raises(PublicCandidateError, match="at least one"):
        build_public_candidate(
            source_duckdb=source,
            target_root=tmp_path / "empty",
            relation_specs=(),
        )
    with pytest.raises(PublicCandidateError, match="unique and sorted"):
        build_public_candidate(
            source_duckdb=source,
            target_root=tmp_path / "duplicate",
            relation_specs=(
                CandidateRelationSpec("public_relation", "curated"),
                CandidateRelationSpec("public_relation", "curated"),
            ),
        )
