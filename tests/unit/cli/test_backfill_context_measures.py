from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from nbadb.cli.app import app

_BUILD_SETTINGS = "nbadb.cli.commands.backfill._build_settings"
_RUN_PIPELINE = "nbadb.cli.commands.backfill._run_pipeline"

runner = CliRunner()


def test_run_parses_context_measures_csv() -> None:
    with (
        patch(_BUILD_SETTINGS, return_value=MagicMock()),
        patch(_RUN_PIPELINE) as mock_run_pipeline,
    ):
        result = runner.invoke(
            app,
            ["backfill", "run", "--context-measures", "AST, PTS,AST"],
        )

    assert result.exit_code == 0, result.output
    assert mock_run_pipeline.call_args is not None
    operation = mock_run_pipeline.call_args.args[1]
    orchestrator = MagicMock()
    operation(orchestrator)
    assert orchestrator.run_backfill.call_args is not None
    assert orchestrator.run_backfill.call_args.kwargs["context_measures"] == ["AST", "PTS"]


def test_run_rejects_invalid_or_empty_context_measures() -> None:
    cases = [
        ("NOT_A_MEASURE", ("Unknown video context measure(s):", "NOT_A_MEASURE")),
        ("", ("context_measures cannot be empty",)),
    ]

    for raw, messages in cases:
        result = runner.invoke(
            app,
            ["backfill", "run", "--context-measures", raw],
        )

        assert result.exit_code != 0
        assert all(message in result.output for message in messages)
