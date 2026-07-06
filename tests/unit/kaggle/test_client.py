from __future__ import annotations

from unittest.mock import patch

import pytest

from nbadb.kaggle.client import KaggleClient


def test_sync_duckdb_replaces_stale_local_duckdb_when_only_sqlite_downloaded(tmp_path) -> None:
    sqlite_path = tmp_path / "nba.sqlite"
    duckdb_path = tmp_path / "nba.duckdb"
    sqlite_path.write_bytes(b"sqlite")
    duckdb_path.write_bytes(b"stale")

    with patch.object(KaggleClient, "_seed_duckdb_from_sqlite") as seed:
        KaggleClient._sync_duckdb_after_download(tmp_path, copied_names={"nba.sqlite"})

    assert not duckdb_path.exists()
    seed.assert_called_once_with(sqlite_path, duckdb_path)


def test_sync_duckdb_keeps_downloaded_duckdb(tmp_path) -> None:
    sqlite_path = tmp_path / "nba.sqlite"
    duckdb_path = tmp_path / "nba.duckdb"
    sqlite_path.write_bytes(b"sqlite")
    duckdb_path.write_bytes(b"fresh")

    with patch.object(KaggleClient, "_seed_duckdb_from_sqlite") as seed:
        KaggleClient._sync_duckdb_after_download(
            tmp_path,
            copied_names={"nba.sqlite", "nba.duckdb"},
        )

    assert duckdb_path.read_bytes() == b"fresh"
    seed.assert_not_called()


def test_sync_duckdb_ignores_stale_local_sqlite_when_sqlite_not_downloaded(tmp_path) -> None:
    sqlite_path = tmp_path / "nba.sqlite"
    duckdb_path = tmp_path / "nba.duckdb"
    sqlite_path.write_bytes(b"stale-sqlite")
    duckdb_path.write_bytes(b"current-duckdb")

    with patch.object(KaggleClient, "_seed_duckdb_from_sqlite") as seed:
        KaggleClient._sync_duckdb_after_download(tmp_path, copied_names={"csv"})

    assert duckdb_path.read_bytes() == b"current-duckdb"
    seed.assert_not_called()


def test_ensure_metadata_fails_when_data_dir_is_missing(tmp_path) -> None:
    missing_dir = tmp_path / "missing"

    with pytest.raises(FileNotFoundError, match="Metadata data_dir does not exist"):
        KaggleClient().ensure_metadata(missing_dir)

    assert not missing_dir.exists()
