from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from nbadb.core.config import NbaDbSettings, get_settings


@pytest.fixture(autouse=False)
def clear_settings_cache():
    yield
    get_settings.cache_clear()


class TestNbaDbSettingsDefaults:
    def test_default_data_dir(self) -> None:
        assert NbaDbSettings().data_dir == Path("nbadb")

    def test_default_proxy_disabled(self) -> None:
        assert NbaDbSettings(_env_file=None).proxy_enabled is False

    def test_default_strategic_flags_disabled(self) -> None:
        settings = NbaDbSettings()
        assert settings.strategic_track_ingestion_v2_enabled is False
        assert settings.strategic_track_storage_v2_enabled is False
        assert settings.strategic_track_schema_v2_enabled is False
        assert settings.strategic_track_serving_v2_enabled is False
        assert settings.strategic_phase_1_shadow_mode_enabled is False
        assert settings.strategic_phase_2_dual_write_enabled is False

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


class TestBuildProxyPool:
    def test_build_proxy_pool_disabled(self) -> None:
        from nbadb.core.proxy import build_proxy_pool

        settings = NbaDbSettings(proxy_enabled=False)
        assert build_proxy_pool(settings) is None

    def test_build_proxy_pool_enabled(self) -> None:
        from nbadb.core.proxy import build_proxy_pool

        settings = NbaDbSettings(
            proxy_enabled=True,
            proxy_urls=["http://1.2.3.4:8080"],
        )
        with patch("proxywhirl.ProxyWhirl") as mock_pw:
            mock_pw.return_value.get_pool_stats.return_value = {"total_proxies": 1}
            pool = build_proxy_pool(settings)
            assert pool is not None
