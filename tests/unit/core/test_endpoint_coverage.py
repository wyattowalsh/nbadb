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


def _write_runtime_alias_extractors(project_root: Path) -> None:
    stats_dir = project_root / "src" / "nbadb" / "extract" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "__init__.py").write_text("", encoding="utf-8")
    (stats_dir / "runtime_alias_extractors.py").write_text(
        """
from nba_api.stats.endpoints import (
    BoxScoreTraditionalV3,
    LeagueStandingsV3,
    PlayByPlayV3,
    VideoDetails,
    VideoDetailsAsset,
    VideoEvents,
    VideoStatus,
)
from nbadb.extract.base import BaseExtractor


class BoxScoreTraditionalExtractor(BaseExtractor):
    endpoint_name = "box_score_traditional"

    async def extract(self, **params):
        return self._from_nba_api(BoxScoreTraditionalV3, **params)


class LeagueStandingsExtractor(BaseExtractor):
    endpoint_name = "league_standings"

    async def extract(self, **params):
        return self._from_nba_api(LeagueStandingsV3, **params)


class PlayByPlayExtractor(BaseExtractor):
    endpoint_name = "play_by_play"

    async def extract(self, **params):
        return self._from_nba_api(PlayByPlayV3, **params)


class VideoStatusExtractor(BaseExtractor):
    endpoint_name = "video_status"

    async def extract(self, **params):
        return self._from_nba_api(VideoStatus, **params)


class VideoEventsExtractor(BaseExtractor):
    endpoint_name = "video_events"

    async def extract(self, **params):
        return self._from_nba_api(VideoEvents, **params)


class VideoDetailsExtractor(BaseExtractor):
    endpoint_name = "video_details"

    async def extract(self, **params):
        return self._from_nba_api(VideoDetails, **params)


class VideoDetailsAssetExtractor(BaseExtractor):
    endpoint_name = "video_details_asset"

    async def extract(self, **params):
        return self._from_nba_api(VideoDetailsAsset, **params)
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_static_and_live_extractors(project_root: Path) -> None:
    static_dir = project_root / "src" / "nbadb" / "extract" / "static"
    live_dir = project_root / "src" / "nbadb" / "extract" / "live"
    static_dir.mkdir(parents=True, exist_ok=True)
    live_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "__init__.py").write_text("", encoding="utf-8")
    (live_dir / "__init__.py").write_text("", encoding="utf-8")
    (static_dir / "static_extractors.py").write_text(
        """
from nba_api.stats.static import players as static_players, teams as static_teams
from nbadb.extract.base import BaseExtractor


class StaticPlayersExtractor(BaseExtractor):
    endpoint_name = "static_players"

    async def extract(self, **params):
        return static_players.get_players()


class StaticTeamsExtractor(BaseExtractor):
    endpoint_name = "static_teams"

    async def extract(self, **params):
        return static_teams.get_teams()
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (live_dir / "live_extractors.py").write_text(
        """
from nba_api.live.nba.endpoints import BoxScore, ScoreBoard
from nbadb.extract.base import BaseExtractor


class LiveBoxScoreExtractor(BaseExtractor):
    endpoint_name = "live_box_score"

    async def extract(self, **params):
        return self._from_nba_live(BoxScore, "game_details", game_id=params["game_id"])


class LiveScoreBoardExtractor(BaseExtractor):
    endpoint_name = "live_score_board"

    async def extract(self, **params):
        return self._from_nba_live(ScoreBoard, "games")
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_sample_transforms(project_root: Path) -> None:
    facts_dir = project_root / "src" / "nbadb" / "transform" / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    (facts_dir / "__init__.py").write_text("", encoding="utf-8")
    (facts_dir / "fact_foo.py").write_text(
        """
from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactFooTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_foo"
    depends_on: ClassVar[list[str]] = ["stg_foo"]
    _SQL: ClassVar[str] = "SELECT 1 AS x"
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_additional_sample_transform(project_root: Path) -> None:
    derived_dir = project_root / "src" / "nbadb" / "transform" / "derived"
    derived_dir.mkdir(parents=True, exist_ok=True)
    (derived_dir / "__init__.py").write_text("", encoding="utf-8")
    (derived_dir / "agg_bar.py").write_text(
        """
from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggBarTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_bar"
    depends_on: ClassVar[list[str]] = ["stg_foo"]
    _SQL: ClassVar[str] = "SELECT 1 AS x"
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_sample_star_schemas(project_root: Path) -> None:
    star_dir = project_root / "src" / "nbadb" / "schemas" / "star"
    star_dir.mkdir(parents=True, exist_ok=True)
    (star_dir / "__init__.py").write_text("", encoding="utf-8")
    (star_dir / "fact_foo.py").write_text(
        """
class FactFooSchema:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (star_dir / "bridge_unused.py").write_text(
        """
class BridgeUnusedSchema:
    pass
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
    assert "Star Schema Coverage" in report_text
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
    assert rows["player_game_log"]["model_status"] == "unowned"
    assert rows["team_game_log"]["model_status"] == "unowned"
    model_ownership = artifacts["summary"]["model_ownership"]
    assert model_ownership["model_excluded_stats_endpoints"] == 0
    assert model_ownership["model_unowned_stats_endpoints"] == 2


def test_build_artifacts_summary_includes_zero_model_contract_counts(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_sample_transforms(project_root)
    staging_entries = [StagingEntry("foo_endpoint", "stg_foo", "season")]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="test-runtime",
    )

    model_ownership = artifacts["summary"]["model_ownership"]
    assert model_ownership["model_excluded_stats_endpoints"] == 0
    assert model_ownership["model_unowned_stats_endpoints"] == 0
    assert model_ownership["excluded_stats_endpoints"] == []
    assert model_ownership["unowned_stats_endpoints"] == []


def test_build_artifacts_reports_star_schema_coverage(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_sample_transforms(project_root)
    _write_additional_sample_transform(project_root)
    _write_sample_star_schemas(project_root)
    staging_entries = [StagingEntry("foo_endpoint", "stg_foo", "season")]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="test-runtime",
    )

    star_schema_coverage = artifacts["summary"]["star_schema_coverage"]
    assert star_schema_coverage["transform_output_count"] == 2
    assert star_schema_coverage["schema_backed_transform_outputs"] == 1
    assert star_schema_coverage["schema_missing_transform_outputs"] == 1
    assert star_schema_coverage["schema_only_table_count"] == 1
    assert star_schema_coverage["schema_backed_breakdown"] == {"facts": 1}
    assert star_schema_coverage["schema_missing_breakdown"] == {"derived": 1}
    assert star_schema_coverage["schema_only_breakdown"] == {"bridges": 1}
    assert star_schema_coverage["schema_backed_outputs"] == ["fact_foo"]
    assert star_schema_coverage["schema_missing_outputs"] == ["agg_bar"]
    assert star_schema_coverage["schema_only_tables"] == ["bridge_unused"]


def test_build_artifacts_counts_explicit_staging_key_exclusions(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    (project_root / "src" / "nbadb").mkdir(parents=True, exist_ok=True)
    staging_entries = [
        StagingEntry(
            "player_vs_player",
            "stg_pvp_player_info",
            "player",
            result_set_index=2,
            use_multi=True,
        ),
        StagingEntry(
            "player_vs_player",
            "stg_pvp_vs_player_info",
            "player",
            result_set_index=9,
            use_multi=True,
        ),
    ]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"PlayerVsPlayer"},
        runtime_version="test-runtime",
    )

    model_ownership = artifacts["summary"]["model_ownership"]
    assert model_ownership["transform_owned_staging_entries"] == 0
    assert model_ownership["model_excluded_staging_entries"] == 2
    assert model_ownership["model_unowned_staging_entries"] == 0
    assert model_ownership["excluded_staging_entries_detail"] == [
        {
            "staging_key": "stg_pvp_player_info",
            "endpoint_name": "player_vs_player",
            "reason": (
                "Duplicate player bio packet; the analytical model uses the canonical "
                "player dimensions instead of matchup-scoped profile copies."
            ),
        },
        {
            "staging_key": "stg_pvp_vs_player_info",
            "endpoint_name": "player_vs_player",
            "reason": (
                "Duplicate opposing-player bio packet; the analytical model uses the "
                "canonical player dimensions instead of matchup-scoped profile copies."
            ),
        },
    ]


def test_build_artifacts_detects_runtime_refs_from_helper_wrappers(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    stats_dir = project_root / "src" / "nbadb" / "extract" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "__init__.py").write_text("", encoding="utf-8")
    (stats_dir / "wrapped_extractors.py").write_text(
        """
from nba_api.stats.endpoints import PlayerDashboardByGameSplits
from nbadb.extract.base import BaseExtractor


def _extract_dashboard_frame(extractor, endpoint_cls, **params):
    return extractor._from_nba_api(endpoint_cls, **params)


class PlayerDashGameSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dash_game_splits"

    async def extract(self, **params):
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByGameSplits,
            player_id=params["player_id"],
            season=params["season"],
        )
""".strip()
        + "\n",
        encoding="utf-8",
    )
    staging_entries = [
        StagingEntry(
            "player_dash_game_splits",
            "stg_player_dash_game_splits",
            "player",
        )
    ]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"PlayerDashboardByGameSplits"},
        runtime_version="test-runtime",
    )

    row = next(
        row for row in artifacts["matrix"] if row["endpoint_name"] == "player_dash_game_splits"
    )
    assert row["coverage_status"] == "covered"
    assert row["runtime_refs"] == ["PlayerDashboardByGameSplits"]


def test_normalizes_runtime_aliases_and_covers_video_endpoints(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_runtime_alias_extractors(project_root)
    staging_entries = [
        StagingEntry("box_score_traditional", "stg_box_score_traditional", "game"),
        StagingEntry("league_standings", "stg_league_standings", "season"),
        StagingEntry("play_by_play", "stg_play_by_play", "game"),
        StagingEntry("video_details", "stg_video_details", "player_team_season"),
        StagingEntry("video_details_asset", "stg_video_details_asset", "player_team_season"),
        StagingEntry("video_status", "stg_video_status", "date"),
        StagingEntry("video_events", "stg_video_events", "game"),
    ]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={
            "BoxScoreTraditionalV2",
            "BoxScoreAdvancedV2",
            "BoxScoreMiscV2",
            "BoxScoreScoringV2",
            "BoxScoreUsageV2",
            "BoxScoreFourFactorsV2",
            "LeagueStandings",
            "PlayByPlay",
            "VideoDetails",
            "VideoDetailsAsset",
            "VideoEvents",
            "VideoStatus",
        },
        runtime_version="alias-test-runtime",
    )

    rows = {row["endpoint_name"]: row for row in artifacts["matrix"]}
    assert rows["box_score_traditional"]["coverage_status"] == "covered"
    assert rows["league_standings"]["coverage_status"] == "covered"
    assert rows["play_by_play"]["coverage_status"] == "covered"
    assert rows["video_details"]["coverage_status"] == "covered"
    assert rows["video_details_asset"]["coverage_status"] == "covered"
    assert rows["video_events"]["coverage_status"] == "covered"
    assert rows["video_status"]["coverage_status"] == "covered"
    assert rows["video_status"]["model_status"] == "excluded"
    assert rows["video_status"]["model_exclusion_reason"] is not None


def test_build_artifacts_includes_static_live_surfaces_and_model_ownership(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_static_and_live_extractors(project_root)
    _write_sample_transforms(project_root)
    staging_entries = [StagingEntry("foo_endpoint", "stg_foo", "season")]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_static_surfaces={"players", "teams"},
        runtime_live_endpoint_classes={"BoxScore", "ScoreBoard", "Odds"},
        runtime_version="full-runtime",
    )

    rows = {(row["source_kind"], row["endpoint_name"]): row for row in artifacts["matrix"]}
    assert rows[("stats", "foo_endpoint")]["coverage_status"] == "covered"
    assert rows[("stats", "foo_endpoint")]["transform_present"] is True
    assert rows[("stats", "foo_endpoint")]["transform_outputs"] == ["fact_foo"]
    assert rows[("static", "static_players")]["coverage_status"] == "covered"
    assert rows[("static", "static_teams")]["coverage_status"] == "covered"
    assert rows[("live", "live_box_score")]["coverage_status"] == "covered"
    assert rows[("live", "live_score_board")]["coverage_status"] == "covered"
    assert rows[("live", "live_odds")]["coverage_status"] == "source_only"

    coverage = artifacts["summary"]["coverage"]
    assert coverage["covered"] == 5
    assert coverage["source_only"] == 1

    source_breakdown = {row["source_kind"]: row for row in artifacts["summary"]["source_breakdown"]}
    assert source_breakdown["stats"]["covered"] == 1
    assert source_breakdown["static"]["covered"] == 2
    assert source_breakdown["live"]["covered"] == 2
    assert source_breakdown["live"]["source_only"] == 1

    model_ownership = artifacts["summary"]["model_ownership"]
    assert model_ownership["staging_entry_count"] == 1
    assert model_ownership["transform_owned_staging_entries"] == 1
    assert model_ownership["model_excluded_staging_entries"] == 0
    assert model_ownership["model_unowned_staging_entries"] == 0
    assert model_ownership["transform_owned_stats_endpoints"] == 1
    assert model_ownership["model_excluded_stats_endpoints"] == 0
    assert model_ownership["model_unowned_stats_endpoints"] == 0
