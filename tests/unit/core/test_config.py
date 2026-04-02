from __future__ import annotations

from pathlib import Path

import pytest

from nbadb.core.config import NbaDbSettings, get_settings


@pytest.fixture(autouse=False)
def clear_settings_cache():
    yield
    get_settings.cache_clear()


class TestNbaDbSettingsDefaults:
    def test_default_data_dir(self) -> None:
        assert NbaDbSettings().data_dir == Path("nbadb")

    def test_default_db_paths_validator(self) -> None:
        settings = NbaDbSettings()
        assert settings.sqlite_path == Path("nbadb") / "nba.sqlite"
        assert settings.duckdb_path == Path("nbadb") / "nba.duckdb"


class TestNbaDbSettingsCustom:
    def test_custom_data_dir_updates_db_paths(self) -> None:
        settings = NbaDbSettings(data_dir=Path("/tmp/test"))
        assert settings.sqlite_path == Path("/tmp/test/nba.sqlite")
        assert settings.duckdb_path == Path("/tmp/test/nba.duckdb")

    def test_explicit_sqlite_path_not_overridden(self) -> None:
        settings = NbaDbSettings(sqlite_path=Path("/custom/my.db"))
        assert settings.sqlite_path == Path("/custom/my.db")


class TestGetSettings:
    def test_get_settings_cached(self, clear_settings_cache: None) -> None:
        a = get_settings()
        b = get_settings()
        assert id(a) == id(b)

    def test_get_settings_cache_clear(self, clear_settings_cache: None) -> None:
        a = get_settings()
        get_settings.cache_clear()
        b = get_settings()
        assert id(a) != id(b)
