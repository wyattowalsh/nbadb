from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from nbadb.cli.app import app
from nbadb.core.nba_api_contract import NbaApiContractDiscoveryError
from nbadb.core.provider_boundary import ProviderBoundaryError, ProviderBoundaryIssue

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_GENERATOR_PATH = "nbadb.cli.commands.extract_completeness.EndpointCoverageGenerator"
_RUNTIME_DISCOVERY_PATH = (
    "nbadb.cli.commands.extract_completeness.discover_runtime_endpoint_contracts"
)
_PROVIDER_BOUNDARY_PATH = "nbadb.cli.commands.extract_completeness.require_provider_boundary"


@pytest.fixture(autouse=True)
def _stable_runtime_discovery(request: pytest.FixtureRequest) -> None:
    patcher = patch(_RUNTIME_DISCOVERY_PATH, return_value={"PinnedEndpoint": object()})
    patcher.start()
    request.addfinalizer(patcher.stop)


def _artifact_paths(tmp_path: Path, coverage: dict[str, int]) -> dict[str, Path]:
    matrix_path = tmp_path / "endpoint-coverage-matrix.json"
    summary_path = tmp_path / "endpoint-coverage-summary.json"
    report_path = tmp_path / "endpoint-coverage-report.md"
    extraction_summary_path = tmp_path / "endpoint-extraction-summary.json"
    extraction_report_path = tmp_path / "endpoint-extraction-report.md"
    full_extraction_definition_path = tmp_path / "full-extraction-definition.json"

    matrix_path.write_text('{"matrix": []}\n', encoding="utf-8")
    summary_path.write_text(json.dumps({"coverage": coverage}) + "\n", encoding="utf-8")
    report_path.write_text("# Endpoint Coverage Report\n", encoding="utf-8")
    extraction_summary_path.write_text("{}\n", encoding="utf-8")
    extraction_report_path.write_text("# Endpoint Extraction Contract\n", encoding="utf-8")
    full_extraction_definition_path.write_text("{}\n", encoding="utf-8")
    return {
        "matrix": matrix_path,
        "summary": summary_path,
        "report": report_path,
        "extraction_summary": extraction_summary_path,
        "extraction_report": extraction_report_path,
        "full_extraction_definition": full_extraction_definition_path,
    }


def test_extract_completeness_prints_summary_and_uses_output_dir(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 5,
            "runtime_gap": 1,
            "staging_only": 1,
            "extractor_only": 0,
            "source_only": 0,
        },
    )
    summary_payload = {
        "coverage": {
            "covered": 5,
            "runtime_gap": 1,
            "staging_only": 1,
            "extractor_only": 0,
            "source_only": 0,
        },
        "extraction_contract": {
            "in_scope_endpoint_count": 6,
            "extractable_endpoint_count": 4,
            "partial_endpoint_count": 1,
            "blocked_endpoint_count": 1,
            "excluded_endpoint_count": 2,
            "season_type_contract_open_count": 1,
            "ready_for_full_backfill": False,
        },
        "model_ownership": {
            "stats_endpoint_count": 4,
            "analytically_modeled_stats_endpoints": 1,
            "passthrough_only_stats_endpoints": 2,
            "compatibility_reference_only_stats_endpoints": 1,
            "model_excluded_stats_endpoints": 1,
            "model_unowned_stats_endpoints": 0,
            "staging_entry_count": 9,
            "analytically_modeled_staging_entries": 2,
            "passthrough_only_staging_entries": 4,
            "compatibility_reference_only_staging_entries": 1,
            "model_excluded_staging_entries": 1,
            "model_unowned_staging_entries": 1,
        },
        "star_schema_coverage": {
            "transform_output_count": 5,
            "schema_backed_transform_outputs": 3,
            "schema_missing_transform_outputs": 2,
            "schema_only_table_count": 1,
        },
    }
    written["summary"].write_text(json.dumps(summary_payload) + "\n", encoding="utf-8")
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mock_generator.return_value.build_artifacts.assert_called_once_with()
    mock_generator.return_value.write_artifacts.assert_called_once()
    assert "in_scope=6" in result.output
    assert "extractable=4" in result.output
    assert "partial=1" in result.output
    assert "blocked=1" in result.output
    assert "excluded=2" in result.output
    assert "season_type_open=1" in result.output
    assert "ready_for_full_backfill=False" in result.output
    assert "stats_endpoints=4" in result.output
    assert "modeled_endpoints=1" in result.output
    assert "passthrough_endpoints=2" in result.output
    assert "compatibility_reference_endpoints=1" in result.output
    assert "model_excluded_endpoints=1" in result.output
    assert "model_unowned_endpoints=0" in result.output
    assert "staging_entries=9" in result.output
    assert "modeled=2" in result.output
    assert "passthrough=4" in result.output
    assert "compatibility_reference=1" in result.output
    assert "model_excluded=1" in result.output
    assert "model_unowned=1" in result.output
    assert "Star schema coverage:" in result.output
    assert "transform_outputs=5" in result.output
    assert "schema_backed=3" in result.output
    assert "schema_missing=2" in result.output
    assert "schema_only=1" in result.output


def test_extract_completeness_require_full_exits_when_noncovered(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 4,
            "runtime_gap": 1,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 1,
        },
    )
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": {
                "runtime_endpoint_class_count": 1,
                "coverage": {
                    "covered": 4,
                    "runtime_gap": 1,
                    "staging_only": 0,
                    "extractor_only": 0,
                    "source_only": 1,
                },
                "extraction_contract": {
                    "in_scope_endpoint_count": 5,
                    "extractable_endpoint_count": 3,
                    "partial_endpoint_count": 1,
                    "blocked_endpoint_count": 1,
                    "excluded_endpoint_count": 0,
                    "season_type_contract_open_count": 1,
                    "ready_for_full_backfill": False,
                },
            }
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert "require-full check failed" in result.output


def test_extract_completeness_require_full_fails_before_generation_on_boundary_issue() -> None:
    error = ProviderBoundaryError(
        (
            ProviderBoundaryIssue(
                relative_path="orchestrate/leak.py",
                line=1,
                rule="provider_import_outside_boundary",
                symbol="nba_api.fixture",
            ),
        )
    )
    with (
        patch(_GENERATOR_PATH) as mock_generator,
        patch(_PROVIDER_BOUNDARY_PATH, side_effect=error),
    ):
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert "orchestrate/leak.py:1" in result.output
    mock_generator.assert_not_called()


@pytest.mark.parametrize(
    ("summary_section", "counter_name"),
    [
        ("upstream_contract", "field_gap_count"),
        ("upstream_contract", "invalid_result_set_index_count"),
        ("upstream_contract", "missing_result_set_staging_count"),
        ("upstream_contract", "missing_input_schema_count"),
        ("upstream_contract", "blocking_contract_unknown_result_set_count"),
        ("upstream_field_fate", "missing_sink_count"),
        ("upstream_field_fate", "model_usage_unknown_count"),
        ("upstream_field_fate", "unmodeled_unclassified_count"),
        ("temporal_coverage", "required_temporal_missing_count"),
        ("endpoint_analysis_docs", "blocking_docs_contract_gap_count"),
        ("endpoint_analysis_docs", "docs_field_gap_count"),
        ("endpoint_analysis_docs", "docs_invalid_result_set_index_count"),
        ("endpoint_analysis_docs", "docs_missing_result_set_staging_count"),
        ("endpoint_analysis_docs", "docs_missing_input_schema_count"),
        ("endpoint_analysis_docs", "docs_contract_discovery_failure_count"),
    ],
)
def test_extract_completeness_require_full_exits_for_contract_gap_counters(
    tmp_path: Path,
    summary_section: str,
    counter_name: str,
) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
    )
    summary_payload: dict[str, object] = {
        "runtime_endpoint_class_count": 1,
        "coverage": {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
        "extraction_contract": {
            "in_scope_endpoint_count": 5,
            "extractable_endpoint_count": 5,
            "partial_endpoint_count": 0,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 0,
            "ready_for_full_backfill": True,
        },
        "upstream_contract": {
            "field_gap_count": 0,
            "invalid_result_set_index_count": 0,
            "missing_result_set_staging_count": 0,
            "missing_input_schema_count": 0,
            "contract_unknown_result_set_count": 0,
            "classified_contract_unknown_result_set_count": 0,
            "blocking_contract_unknown_result_set_count": 0,
        },
        "upstream_field_fate": {
            "missing_sink_count": 0,
            "model_usage_unknown_count": 0,
            "unmodeled_unclassified_count": 0,
        },
        "temporal_coverage": {"required_temporal_missing_count": 0},
        "endpoint_analysis_docs": {
            "enabled": True,
            "provider_provenance": {"verified": True},
            "provider_evidence": {"verified": True},
            "docs_contract_count": 1,
            "runtime_endpoint_missing_docs_count": 0,
            "docs_endpoint_missing_runtime_count": 0,
            "docs_only_result_set_count": 0,
            "docs_field_missing_in_runtime_count": 0,
            "runtime_field_missing_in_docs_count": 0,
            "blocking_docs_contract_gap_count": 0,
            "docs_field_gap_count": 0,
            "docs_invalid_result_set_index_count": 0,
            "docs_missing_result_set_staging_count": 0,
            "docs_missing_input_schema_count": 0,
            "docs_contract_discovery_failure_count": 0,
        },
        "player_directory_snapshot": {
            "status": "blocked_pending_evidence",
            "integrity_verified": True,
            "authority_eligible": False,
        },
    }
    section = summary_payload[summary_section]
    if not isinstance(section, dict):
        raise AssertionError(f"{summary_section} must be an object")
    counters: dict[str, object] = {str(key): value for key, value in section.items()}
    counters[counter_name] = 1
    if counter_name == "blocking_contract_unknown_result_set_count":
        counters["contract_unknown_result_set_count"] = 1
    summary_payload[summary_section] = counters

    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert "require-full check failed" in result.output


def test_extract_completeness_require_full_exits_for_docs_field_drift(
    tmp_path: Path,
) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
    )
    summary_payload = {
        "runtime_endpoint_class_count": 1,
        "coverage": {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
        "extraction_contract": {
            "in_scope_endpoint_count": 5,
            "extractable_endpoint_count": 5,
            "partial_endpoint_count": 0,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 0,
            "ready_for_full_backfill": True,
        },
        "upstream_contract": {
            "field_gap_count": 0,
            "invalid_result_set_index_count": 0,
            "missing_result_set_staging_count": 0,
            "missing_input_schema_count": 0,
            "contract_unknown_result_set_count": 0,
            "classified_contract_unknown_result_set_count": 0,
            "blocking_contract_unknown_result_set_count": 0,
        },
        "upstream_field_fate": {
            "missing_sink_count": 0,
            "model_usage_unknown_count": 0,
            "unmodeled_unclassified_count": 0,
        },
        "temporal_coverage": {"required_temporal_missing_count": 0},
        "endpoint_analysis_docs": {
            "enabled": True,
            "provider_provenance": {"verified": True},
            "provider_evidence": {"verified": True},
            "docs_contract_count": 1,
            "runtime_endpoint_missing_docs_count": 1,
            "docs_endpoint_missing_runtime_count": 0,
            "docs_only_result_set_count": 0,
            "docs_field_missing_in_runtime_count": 1,
            "runtime_field_missing_in_docs_count": 4,
            "blocking_docs_contract_gap_count": 0,
            "docs_field_gap_count": 12,
            "docs_invalid_result_set_index_count": 0,
            "docs_missing_result_set_staging_count": 0,
            "docs_missing_input_schema_count": 0,
            "docs_contract_discovery_failure_count": 0,
        },
        "player_directory_snapshot": {"status": "verified", "integrity_verified": True},
    }

    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert "require-full check failed" in result.output
    assert "docs_field_gaps=12" in result.output
    assert "blocking_docs_contract_gaps=0" in result.output


def test_extract_completeness_require_full_exits_for_docs_tools_metadata_warning(
    tmp_path: Path,
) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
    )
    summary_payload = {
        "runtime_endpoint_class_count": 1,
        "coverage": {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
        "extraction_contract": {
            "in_scope_endpoint_count": 5,
            "extractable_endpoint_count": 5,
            "partial_endpoint_count": 0,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 0,
            "ready_for_full_backfill": True,
        },
        "upstream_contract": {
            "field_gap_count": 0,
            "invalid_result_set_index_count": 0,
            "missing_result_set_staging_count": 0,
            "missing_input_schema_count": 0,
            "contract_unknown_result_set_count": 0,
            "classified_contract_unknown_result_set_count": 0,
            "blocking_contract_unknown_result_set_count": 0,
        },
        "upstream_field_fate": {
            "missing_sink_count": 0,
            "model_usage_unknown_count": 0,
            "unmodeled_unclassified_count": 0,
        },
        "temporal_coverage": {"required_temporal_missing_count": 0},
        "endpoint_analysis_docs": {
            "enabled": True,
            "provider_provenance": {"verified": True},
            "provider_evidence": {"verified": True},
            "docs_contract_count": 1,
            "runtime_endpoint_missing_docs_count": 0,
            "docs_endpoint_missing_runtime_count": 0,
            "docs_only_result_set_count": 0,
            "docs_field_missing_in_runtime_count": 0,
            "runtime_field_missing_in_docs_count": 0,
            "blocking_docs_contract_gap_count": 0,
            "docs_field_gap_count": 0,
            "docs_invalid_result_set_index_count": 0,
            "docs_missing_result_set_staging_count": 0,
            "docs_missing_input_schema_count": 0,
            "docs_contract_discovery_failure_count": 0,
            "metadata_ledger": {"metadata_ingestion_warning_count": 1},
        },
        "player_directory_snapshot": {"status": "verified", "integrity_verified": True},
    }

    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert "metadata_warnings=1" in result.output
    assert "require-full check failed" in result.output


@pytest.mark.parametrize(
    ("metadata_ledger", "bronze_contracts", "expected_output"),
    [
        (
            {
                "tools_endpoint_missing_docs_count": 1,
                "blocking_tools_endpoint_missing_docs_count": 1,
            },
            {},
            "tools_missing_docs=1",
        ),
        (
            {
                "docs_endpoint_missing_tools_count": 1,
                "blocking_docs_endpoint_missing_tools_count": 1,
            },
            {},
            "docs_missing_tools=1",
        ),
        (
            {},
            {"zero_column_table_count": 1, "blocking_zero_column_table_count": 1},
            "bronze_zero_column_tables=1",
        ),
    ],
)
def test_extract_completeness_require_full_exits_for_docs_tools_bronze_gates(
    tmp_path: Path,
    metadata_ledger: dict[str, int],
    bronze_contracts: dict[str, int],
    expected_output: str,
) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
    )
    summary_payload = {
        "runtime_endpoint_class_count": 1,
        "coverage": {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
        "extraction_contract": {
            "in_scope_endpoint_count": 5,
            "extractable_endpoint_count": 5,
            "partial_endpoint_count": 0,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 0,
            "ready_for_full_backfill": True,
        },
        "upstream_contract": {
            "field_gap_count": 0,
            "invalid_result_set_index_count": 0,
            "missing_result_set_staging_count": 0,
            "missing_input_schema_count": 0,
            "contract_unknown_result_set_count": 0,
            "classified_contract_unknown_result_set_count": 0,
            "blocking_contract_unknown_result_set_count": 0,
        },
        "upstream_field_fate": {
            "missing_sink_count": 0,
            "model_usage_unknown_count": 0,
            "unmodeled_unclassified_count": 0,
        },
        "temporal_coverage": {"required_temporal_missing_count": 0},
        "endpoint_analysis_docs": {
            "enabled": True,
            "docs_contract_count": 1,
            "runtime_endpoint_missing_docs_count": 0,
            "docs_endpoint_missing_runtime_count": 0,
            "docs_only_result_set_count": 0,
            "docs_field_missing_in_runtime_count": 0,
            "runtime_field_missing_in_docs_count": 0,
            "blocking_docs_contract_gap_count": 0,
            "docs_field_gap_count": 0,
            "docs_invalid_result_set_index_count": 0,
            "docs_missing_result_set_staging_count": 0,
            "docs_missing_input_schema_count": 0,
            "docs_contract_discovery_failure_count": 0,
            "metadata_ledger": {
                "metadata_ingestion_warning_count": 0,
                **metadata_ledger,
            },
            "bronze_contracts": bronze_contracts,
        },
    }

    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert expected_output in result.output
    assert "require-full check failed" in result.output


def test_extract_completeness_require_full_allows_classified_docs_tools_bronze_drift(
    tmp_path: Path,
) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
    )
    summary_payload = {
        "runtime_endpoint_class_count": 1,
        "coverage": {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
        "extraction_contract": {
            "in_scope_endpoint_count": 5,
            "extractable_endpoint_count": 5,
            "partial_endpoint_count": 0,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 0,
            "ready_for_full_backfill": True,
        },
        "upstream_contract": {
            "field_gap_count": 0,
            "invalid_result_set_index_count": 0,
            "missing_result_set_staging_count": 0,
            "missing_input_schema_count": 0,
            "contract_unknown_result_set_count": 0,
            "classified_contract_unknown_result_set_count": 0,
            "blocking_contract_unknown_result_set_count": 0,
        },
        "upstream_field_fate": {
            "missing_sink_count": 0,
            "model_usage_unknown_count": 0,
            "unmodeled_unclassified_count": 0,
        },
        "temporal_coverage": {"required_temporal_missing_count": 0},
        "endpoint_analysis_docs": {
            "enabled": True,
            "provider_provenance": {"verified": True},
            "provider_evidence": {"verified": True},
            "docs_contract_count": 1,
            "runtime_endpoint_missing_docs_count": 0,
            "docs_endpoint_missing_runtime_count": 0,
            "docs_only_result_set_count": 0,
            "docs_field_missing_in_runtime_count": 0,
            "runtime_field_missing_in_docs_count": 0,
            "blocking_docs_contract_gap_count": 0,
            "docs_field_gap_count": 0,
            "docs_invalid_result_set_index_count": 0,
            "docs_missing_result_set_staging_count": 0,
            "docs_missing_input_schema_count": 0,
            "docs_contract_discovery_failure_count": 0,
            "metadata_ledger": {
                "metadata_ingestion_warning_count": 0,
                "tools_endpoint_missing_docs_count": 1,
                "docs_endpoint_missing_tools_count": 1,
                "blocking_tools_endpoint_missing_docs_count": 0,
                "blocking_docs_endpoint_missing_tools_count": 0,
            },
            "bronze_contracts": {
                "zero_column_table_count": 1,
                "blocking_zero_column_table_count": 0,
            },
        },
        "player_directory_snapshot": {"status": "verified", "integrity_verified": True},
    }

    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 0, result.output
    assert "tools_missing_docs=1" in result.output
    assert "docs_missing_tools=1" in result.output
    assert "blocking_tools_docs_mismatches=0" in result.output
    assert "blocking_bronze_zero_column_tables=0" in result.output


def test_extract_completeness_require_full_allows_classified_contract_unknowns(
    tmp_path: Path,
) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
    )
    summary_payload = {
        "runtime_endpoint_class_count": 1,
        "coverage": {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
        "extraction_contract": {
            "in_scope_endpoint_count": 5,
            "extractable_endpoint_count": 5,
            "partial_endpoint_count": 0,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 0,
            "ready_for_full_backfill": True,
        },
        "upstream_contract": {
            "field_gap_count": 0,
            "invalid_result_set_index_count": 0,
            "missing_result_set_staging_count": 0,
            "missing_input_schema_count": 0,
            "contract_unknown_result_set_count": 1,
            "classified_contract_unknown_result_set_count": 1,
            "blocking_contract_unknown_result_set_count": 0,
        },
        "upstream_field_fate": {
            "missing_sink_count": 0,
            "model_usage_unknown_count": 0,
            "unmodeled_unclassified_count": 0,
        },
        "temporal_coverage": {"required_temporal_missing_count": 0},
        "endpoint_analysis_docs": {
            "enabled": True,
            "provider_provenance": {"verified": True},
            "provider_evidence": {"verified": True},
        },
        "player_directory_snapshot": {
            "status": "blocked_pending_evidence",
            "integrity_verified": True,
            "authority_eligible": False,
        },
    }

    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 0, result.output
    assert "contract_unknown_result_sets=1" in result.output
    assert "blocking_contract_unknown_result_sets=0" in result.output


@pytest.mark.parametrize(
    "endpoint_analysis_docs",
    [
        {},
        {
            "enabled": True,
            "provider_provenance": {"verified": False},
            "provider_evidence": {"verified": False},
        },
        {
            "enabled": True,
            "provider_provenance": {"verified": True},
            "provider_evidence": {"verified": False},
        },
    ],
)
def test_extract_completeness_require_full_requires_exact_provider_authority(
    tmp_path: Path,
    endpoint_analysis_docs: dict[str, object],
) -> None:
    written = _artifact_paths(tmp_path, {"covered": 1})
    summary_payload = {
        "runtime_endpoint_class_count": 1,
        "extraction_contract": {
            "in_scope_endpoint_count": 1,
            "extractable_endpoint_count": 1,
            "partial_endpoint_count": 0,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 0,
            "ready_for_full_backfill": True,
        },
        "upstream_contract": {},
        "upstream_field_fate": {},
        "temporal_coverage": {},
        "endpoint_analysis_docs": endpoint_analysis_docs,
    }
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {"summary": summary_payload}
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert "exact provider provenance" in result.output


def test_extract_completeness_require_full_fails_closed_on_runtime_import_error() -> None:
    secret = "upstream response must not escape"
    error = NbaApiContractDiscoveryError(
        "stats_runtime_module_import",
        "nba_api.stats.endpoints.broken",
        "ImportError",
    )
    error.__cause__ = ImportError(secret)

    with (
        patch(_RUNTIME_DISCOVERY_PATH, side_effect=error),
        patch(_GENERATOR_PATH) as mock_generator,
    ):
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert (
        "nba_api contract discovery failed: stage=stats_runtime_module_import "
        'source="nba_api.stats.endpoints.broken" error_type=ImportError'
    ) in result.output
    assert secret not in result.output
    mock_generator.assert_not_called()


def test_extract_completeness_require_full_rejects_partial_runtime_inventory(
    tmp_path: Path,
) -> None:
    written = _artifact_paths(tmp_path, {"covered": 1})
    summary_payload = {"runtime_endpoint_class_count": 1}

    with (
        patch(
            _RUNTIME_DISCOVERY_PATH,
            return_value={"FirstEndpoint": object(), "SecondEndpoint": object()},
        ),
        patch(_GENERATOR_PATH) as mock_generator,
    ):
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert (
        "nba_api contract discovery failed: stage=runtime_inventory_reconciliation "
        'source="endpoint_coverage_summary" error_type=PartialDiscovery'
    ) in result.output
    mock_generator.return_value.write_artifacts.assert_not_called()


def test_extract_completeness_require_model_contract_exits_when_unowned(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
    )
    summary_payload = {
        "coverage": {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
        "extraction_contract": {
            "in_scope_endpoint_count": 5,
            "extractable_endpoint_count": 5,
            "partial_endpoint_count": 0,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 0,
            "ready_for_full_backfill": True,
        },
        "model_ownership": {
            "stats_endpoint_count": 5,
            "analytically_modeled_stats_endpoints": 3,
            "passthrough_only_stats_endpoints": 1,
            "compatibility_reference_only_stats_endpoints": 0,
            "model_excluded_stats_endpoints": 0,
            "model_unowned_stats_endpoints": 1,
            "staging_entry_count": 9,
            "analytically_modeled_staging_entries": 5,
            "passthrough_only_staging_entries": 2,
            "compatibility_reference_only_staging_entries": 0,
            "model_excluded_staging_entries": 0,
            "model_unowned_staging_entries": 2,
        },
    }
    written["summary"].write_text(json.dumps(summary_payload) + "\n", encoding="utf-8")
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-model-contract"])

    assert result.exit_code == 1
    assert "require-model-contract check failed" in result.output
