from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nbadb.orchestrate.staging_map import StagingEntry

if TYPE_CHECKING:
    from pathlib import Path


def _write_sample_extractors(project_root: Path) -> None:
    stats_dir = project_root / "src" / "nbadb" / "extract" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "__init__.py").write_text("", encoding="utf-8")
    (stats_dir / "sample_extractors.py").write_text(
        """
from nba_api.stats.endpoints import ExtraEndpoint, FooEndpoint, GapEndpoint
from nbadb.extract.base import BaseExtractor


class FooExtractor(BaseExtractor):
    endpoint_name = "foo_endpoint"

    async def extract(self, **params):
        return self._from_nba_api(FooEndpoint)


class GapExtractor(BaseExtractor):
    endpoint_name = "gap_endpoint"

    async def extract(self, **params):
        return self._from_nba_api(GapEndpoint)


class ExtraExtractor(BaseExtractor):
    endpoint_name = "extractor_only"

    async def extract(self, **params):
        return self._from_nba_api(ExtraEndpoint)
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_alias_and_excluded_extractors(project_root: Path) -> None:
    stats_dir = project_root / "src" / "nbadb" / "extract" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "__init__.py").write_text("", encoding="utf-8")
    (stats_dir / "alias_extractors.py").write_text(
        """
from nba_api.stats.endpoints import HomePageLeaders, PlayerCompare
from nbadb.extract.base import BaseExtractor


class HomePageLeadersAliasExtractor(BaseExtractor):
    endpoint_name = "home_page_leaders"

    async def extract(self, **params):
        return self._from_nba_api(HomePageLeaders)


class PlayerCompareExtractor(BaseExtractor):
    endpoint_name = "player_compare"

    async def extract(self, **params):
        return self._from_nba_api(PlayerCompare)
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_player_team_game_log_extractors(project_root: Path) -> None:
    stats_dir = project_root / "src" / "nbadb" / "extract" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "__init__.py").write_text("", encoding="utf-8")
    (stats_dir / "cross_product_extractors.py").write_text(
        """
from nba_api.stats.endpoints import PlayerGameLog, TeamGameLog
from nbadb.extract.base import BaseExtractor


class PlayerGameLogExtractor(BaseExtractor):
    endpoint_name = "player_game_log"

    async def extract(self, **params):
        return self._from_nba_api(PlayerGameLog)


class TeamGameLogExtractor(BaseExtractor):
    endpoint_name = "team_game_log"

    async def extract(self, **params):
        return self._from_nba_api(TeamGameLog)
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_build_artifacts_emits_matrix_and_pattern_heatmap(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    staging_entries = [
        StagingEntry("foo_endpoint", "stg_foo", "season"),
        StagingEntry("gap_endpoint", "stg_gap", "game"),
        StagingEntry("staging_only", "stg_only", "player"),
    ]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="test-runtime",
    )

    rows = {row["endpoint_name"]: row for row in artifacts["matrix"]}
    assert rows["foo_endpoint"]["coverage_status"] == "covered"
    assert rows["gap_endpoint"]["coverage_status"] == "runtime_gap"
    assert rows["staging_only"]["coverage_status"] == "staging_only"
    assert rows["extractor_only"]["coverage_status"] == "extractor_only"

    coverage = artifacts["summary"]["coverage"]
    assert coverage["covered"] == 1
    assert coverage["runtime_gap"] == 1
    assert coverage["staging_only"] == 1
    assert coverage["extractor_only"] == 1

    heatmap = {row["param_pattern"]: row for row in artifacts["summary"]["pattern_heatmap"]}
    assert heatmap["season"]["total"] == 1
    assert heatmap["season"]["covered"] == 1
    assert heatmap["game"]["runtime_gap"] == 1
    assert heatmap["player"]["staging_only"] == 1


def test_write_outputs_machine_and_human_artifacts(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    staging_entries = [
        StagingEntry("foo_endpoint", "stg_foo", "season"),
        StagingEntry("staging_only", "stg_only", "player"),
    ]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    written = generator.write(
        output_dir=tmp_path / "out",
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="test-runtime",
    )

    matrix_payload = json.loads(written["matrix"].read_text(encoding="utf-8"))
    summary_payload = json.loads(written["summary"].read_text(encoding="utf-8"))
    report_text = written["report"].read_text(encoding="utf-8")

    assert "matrix" in matrix_payload
    assert "coverage" in summary_payload
    assert "Endpoint Coverage Report" in report_text
    assert "| Param Pattern |" in report_text


def test_build_artifacts_canonicalizes_aliases_and_keeps_extractor_only_endpoints(
    tmp_path: Path,
) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_alias_and_excluded_extractors(project_root)
    staging_entries = [StagingEntry("homepage_leaders", "stg_homepage_leaders", "season")]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"HomePageLeaders", "PlayerCompare"},
        runtime_version="test-runtime",
    )

    rows = {row["endpoint_name"]: row for row in artifacts["matrix"]}
    assert rows["homepage_leaders"]["coverage_status"] == "covered"
    assert "home_page_leaders" not in rows
    assert rows["player_compare"]["coverage_status"] == "extractor_only"
    assert artifacts["summary"]["coverage"]["extractor_only"] == 1


def test_build_artifacts_includes_player_team_game_logs_in_all_data_completeness(
    tmp_path: Path,
) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_player_team_game_log_extractors(project_root)
    staging_entries = [
        StagingEntry("player_game_log", "stg_player_game_log", "player"),
        StagingEntry("team_game_log", "stg_team_game_log", "team"),
    ]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"PlayerGameLog", "TeamGameLog"},
        runtime_version="test-runtime",
    )

    rows = {row["endpoint_name"]: row for row in artifacts["matrix"]}
    assert rows["player_game_log"]["coverage_status"] == "covered"
    assert rows["team_game_log"]["coverage_status"] == "covered"
    assert "excluded_endpoints" not in artifacts["summary"]


def test_build_artifacts_summary_omits_excluded_counts(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    staging_entries = [StagingEntry("foo_endpoint", "stg_foo", "season")]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="test-runtime",
    )

    assert "excluded_endpoint_count" not in artifacts["summary"]
    assert "excluded_endpoints" not in artifacts["summary"]
