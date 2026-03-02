from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import duckdb
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from nbadb.cli.app import app
from nbadb.orchestrate.orchestrator import PipelineResult

runner = CliRunner()

_INIT_PATH = "nbadb.cli.commands.init.Orchestrator"


def _make_result(**kwargs: object) -> PipelineResult:
    defaults: dict[str, object] = {
        "tables_updated": 2,
        "rows_total": 100,
        "duration_seconds": 0.5,
        "failed_extractions": 0,
        "errors": [],
    }
    defaults.update(kwargs)
    return PipelineResult(**defaults)  # type: ignore[arg-type]


def _make_db(path: Path) -> None:
    """Create a minimal DuckDB with one user table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    conn.execute("CREATE TABLE dim_player AS SELECT 1 AS player_id, 'Test' AS name")
    conn.close()


class TestRunQualityChecks:
    def test_quality_check_skipped_when_no_db(self, tmp_path: Path) -> None:
        """No DB file → prints skip message, no crash."""
        from nbadb.cli.commands._helpers import _run_quality_checks
        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(
            data_dir=tmp_path / "missing",
        )
        # Should not raise
        _run_quality_checks(settings)

    def test_quality_check_runs_on_populated_db(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With a real DuckDB, quality summary is printed."""
        from nbadb.cli.commands._helpers import _run_quality_checks
        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(data_dir=tmp_path)
        _make_db(settings.duckdb_path)  # type: ignore[arg-type]

        with patch("nbadb.cli.commands._helpers.typer.echo") as mock_echo:
            _run_quality_checks(settings)

        calls = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Quality:" in calls

    def test_quality_check_empty_table_reports_failure(self, tmp_path: Path) -> None:
        """Empty table triggers a warning in quality output."""
        from nbadb.cli.commands._helpers import _run_quality_checks
        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(data_dir=tmp_path)
        db_path = settings.duckdb_path
        assert db_path is not None
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(db_path))
        conn.execute("CREATE TABLE dim_empty (id INTEGER)")
        conn.close()

        messages: list[str] = []
        with patch(
            "nbadb.cli.commands._helpers.typer.echo",
            side_effect=lambda msg, **_: messages.append(str(msg)),
        ):
            _run_quality_checks(settings)

        assert any("Quality:" in m for m in messages)


class TestQualityCheckFlag:
    def test_init_quality_check_flag_calls_helper(self, tmp_path: Path) -> None:
        """--quality-check flag triggers _run_quality_checks after pipeline."""
        with (
            patch(_INIT_PATH) as mock_cls,
            patch("nbadb.cli.commands._helpers._run_quality_checks") as mock_qc,
        ):
            mock_cls.return_value.run_init = AsyncMock(return_value=_make_result())
            result = runner.invoke(app, ["init", "--quality-check", "--data-dir", str(tmp_path)])

        assert result.exit_code == 0
        mock_qc.assert_called_once()

    def test_init_without_quality_check_skips_helper(self, tmp_path: Path) -> None:
        """Without --quality-check, helper is NOT called."""
        with (
            patch(_INIT_PATH) as mock_cls,
            patch("nbadb.cli.commands._helpers._run_quality_checks") as mock_qc,
        ):
            mock_cls.return_value.run_init = AsyncMock(return_value=_make_result())
            result = runner.invoke(app, ["init", "--data-dir", str(tmp_path)])

        assert result.exit_code == 0
        mock_qc.assert_not_called()
