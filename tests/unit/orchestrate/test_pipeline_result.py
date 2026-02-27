from __future__ import annotations

from nbadb.orchestrate import PipelineResult


class TestPipelineResult:
    def test_defaults(self) -> None:
        r = PipelineResult()
        assert r.tables_updated == 0
        assert r.rows_total == 0
        assert r.duration_seconds == 0.0
        assert r.failed_extractions == 0
        assert r.errors == []

    def test_custom_values(self) -> None:
        r = PipelineResult(
            tables_updated=10,
            rows_total=5000,
            duration_seconds=30.5,
        )
        assert r.tables_updated == 10
        assert r.rows_total == 5000
