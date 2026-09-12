from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import polars as pl
import pytest

from nbadb.kaggle.raw_value_codec import RawValueCodecError, decode_raw_value
from nbadb.load.sqlite import SQLiteLoader
from nbadb.orchestrate.raw_request_store import RAW_REQUEST_AUTHORITY_TABLES

if TYPE_CHECKING:
    from pathlib import Path


_CONVENIENCE_COLUMNS = ("binary_value", "text_value", "null_value")


def _raw_native_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ordinal": pl.Series([0, 1, 2], dtype=pl.Int64),
            "binary_value": pl.Series([None, b"", b"\x00\xff"], dtype=pl.Binary),
            "text_value": pl.Series([None, "", "Ω"], dtype=pl.String),
            "null_value": pl.Series([None, None, None], dtype=pl.Null),
            "observed_at": pl.Series(
                [
                    datetime(2026, 8, 27, 1, 2, 3, 456789, tzinfo=UTC),
                    datetime(2026, 8, 28, tzinfo=UTC),
                    datetime(2026, 8, 29, 23, 59, 59, tzinfo=UTC),
                ],
                dtype=pl.Datetime("us", "UTC"),
            ),
        }
    )


class TestSQLiteLoader:
    def test_writes_to_sqlite(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.sqlite"
        loader = SQLiteLoader(db_path)
        df = pl.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        loader.load("test_table", df)
        loaded = pl.read_database_uri(
            "SELECT * FROM test_table ORDER BY id",
            f"sqlite:///{db_path}",
            engine="adbc",
        )
        assert loaded.shape == (2, 2)

    def test_replace_mode_overwrites(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.sqlite"
        loader = SQLiteLoader(db_path)
        df1 = pl.DataFrame({"id": [1, 2, 3]})
        df2 = pl.DataFrame({"id": [10]})
        loader.load("tbl", df1)
        loader.load("tbl", df2, mode="replace")
        loaded = pl.read_database_uri(
            "SELECT COUNT(*) as cnt FROM tbl",
            f"sqlite:///{db_path}",
            engine="adbc",
        )
        assert loaded["cnt"][0] == 1

    @pytest.mark.skip(reason="adbc append may not work on all platforms")
    def test_append_mode(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.sqlite"
        loader = SQLiteLoader(db_path)
        df1 = pl.DataFrame({"id": [1]})
        loader.load("tbl", df1)
        df2 = pl.DataFrame({"id": [2]})
        loader.load("tbl", df2, mode="append")
        loaded = pl.read_database_uri(
            "SELECT COUNT(*) as cnt FROM tbl",
            f"sqlite:///{db_path}",
            engine="adbc",
        )
        assert loaded["cnt"][0] == 2

    @pytest.mark.parametrize("table", RAW_REQUEST_AUTHORITY_TABLES)
    def test_fixed_raw_tables_have_exact_decoded_convenience_parity(
        self,
        tmp_path: Path,
        table: str,
    ) -> None:
        db_path = tmp_path / "raw.sqlite"
        native = _raw_native_frame()
        loader = SQLiteLoader(db_path)

        loader.load(table, native)

        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                f"SELECT ordinal, binary_value, text_value, null_value, observed_at "
                f'FROM "{table}" ORDER BY ordinal'
            ).fetchall()
        finally:
            connection.close()
        assert [row[0] for row in rows] == native["ordinal"].to_list()
        for column_ordinal, column_name in enumerate(_CONVENIENCE_COLUMNS, start=1):
            decoded = [decode_raw_value(str(row[column_ordinal])) for row in rows]
            expected = native[column_name].to_list()
            assert decoded == expected
            assert [type(value) for value in decoded] == [type(value) for value in expected]
        assert [row[4] for row in rows] == [
            "2026-08-27T01:02:03.456789",
            "2026-08-28T00:00:00.000000",
            "2026-08-29T23:59:59.000000",
        ]

    def test_nonfixed_raw_lookalike_preserves_native_sqlite_strings(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lookalike.sqlite"
        loader = SQLiteLoader(db_path)
        loader.load(
            "raw_nba_api_shadow",
            pl.DataFrame({"value": pl.Series([None, ""], dtype=pl.String)}),
        )

        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                'SELECT typeof(value), value FROM "raw_nba_api_shadow" ORDER BY rowid'
            ).fetchall()
        finally:
            connection.close()
        assert rows == [("null", None), ("text", "")]

    def test_malformed_sqlite_convenience_value_fails_decoded_readback(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "malformed.sqlite"
        table = RAW_REQUEST_AUTHORITY_TABLES[0]
        loader = SQLiteLoader(db_path)
        loader.load(table, _raw_native_frame())

        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                f'UPDATE "{table}" SET binary_value = ? WHERE ordinal = 2',
                ('{"schema_version":1',),
            )
            encoded = connection.execute(
                f'SELECT binary_value FROM "{table}" WHERE ordinal = 2'
            ).fetchone()[0]
        finally:
            connection.close()

        with pytest.raises(RawValueCodecError):
            decode_raw_value(str(encoded))
