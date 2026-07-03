from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from typer.testing import CliRunner

from nbadb.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_WRITE_PATH = "nbadb.cli.commands.schema_annotation_audit.write_schema_annotation_artifacts"


def _audit_artifact(tmp_path: Path, counts: dict[str, int]) -> dict[str, Path]:
    audit_path = tmp_path / "schema-annotation-audit.json"
    audit_path.write_text(
        json.dumps({"summary": {"blocking_issue_counts": counts}}) + "\n",
        encoding="utf-8",
    )
    return {"schema_annotation_audit": audit_path}


def test_schema_annotation_audit_writes_artifacts(tmp_path: Path) -> None:
    artifacts = _audit_artifact(tmp_path, {})

    with patch(_WRITE_PATH, return_value=artifacts) as mock_write:
        result = runner.invoke(app, ["schema-annotation-audit", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mock_write.assert_called_once_with(
        output_dir=tmp_path,
        tiers=("raw", "staging", "star"),
        endpoint_analysis_docs_root=None,
        bronze_contracts_path=None,
        require_bronze_contracts=False,
    )
    assert "wrote: " in result.output
    assert "Schema annotation audit passed." in result.output


def test_schema_annotation_audit_strict_fails_on_issues(tmp_path: Path) -> None:
    artifacts = _audit_artifact(tmp_path, {"invalid_fk_count": 1})

    with patch(_WRITE_PATH, return_value=artifacts):
        result = runner.invoke(
            app,
            ["schema-annotation-audit", "--output-dir", str(tmp_path), "--strict"],
        )

    assert result.exit_code == 1
    assert "invalid_fk_count=1" in result.output


def test_schema_annotation_audit_passes_require_bronze_contracts(tmp_path: Path) -> None:
    artifacts = _audit_artifact(tmp_path, {})
    bronze_path = tmp_path / "bronze.json"

    with patch(_WRITE_PATH, return_value=artifacts) as mock_write:
        result = runner.invoke(
            app,
            [
                "schema-annotation-audit",
                "--output-dir",
                str(tmp_path),
                "--bronze-contracts-path",
                str(bronze_path),
                "--require-bronze-contracts",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_write.assert_called_once_with(
        output_dir=tmp_path,
        tiers=("raw", "staging", "star"),
        endpoint_analysis_docs_root=None,
        bronze_contracts_path=bronze_path,
        require_bronze_contracts=True,
    )
