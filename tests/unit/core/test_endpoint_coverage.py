from __future__ import annotations

import ast
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


def _write_play_by_play_extractor(project_root: Path) -> None:
    stats_dir = project_root / "src" / "nbadb" / "extract" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "__init__.py").write_text("", encoding="utf-8")
    (stats_dir / "play_by_play_extractors.py").write_text(
        """
from nba_api.stats.endpoints import PlayByPlayV3
from nbadb.extract.base import BaseExtractor


class PlayByPlayExtractor(BaseExtractor):
    endpoint_name = "play_by_play"

    async def extract(self, **params):
        return self._from_nba_api(PlayByPlayV3, **params)
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


def _write_sample_staging_schemas(project_root: Path) -> None:
    staging_dir = project_root / "src" / "nbadb" / "schemas" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "__init__.py").write_text("", encoding="utf-8")
    (staging_dir / "stg_foo.py").write_text(
        """
class StagingFooSchema:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_contract_staging_schema(project_root: Path) -> None:
    staging_dir = project_root / "src" / "nbadb" / "schemas" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "__init__.py").write_text("", encoding="utf-8")
    (staging_dir / "stg_foo.py").write_text(
        """
class _FooBaseSchema:
    foo_id: int


class StagingFooSchema(_FooBaseSchema):
    team_id: int


class StagingFooSingleSchema(_FooBaseSchema):
    foo_id: int
    team_id: int
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_contract_staging_schema_with_aliases(project_root: Path) -> None:
    staging_dir = project_root / "src" / "nbadb" / "schemas" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "__init__.py").write_text("", encoding="utf-8")
    (staging_dir / "stg_foo.py").write_text(
        """
import pandera.polars as pa


class StagingFooSchema:
    fg3a: int
    fg3a_rank: int
    pass_: int = pa.Field(alias="pass")
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_contract_staging_schema_with_imported_mixin(project_root: Path) -> None:
    schemas_dir = project_root / "src" / "nbadb" / "schemas"
    staging_dir = schemas_dir / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "__init__.py").write_text("", encoding="utf-8")
    (schemas_dir / "_foo_common.py").write_text(
        """
class _FooMetricMixin:
    metric_value: int
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (staging_dir / "stg_foo.py").write_text(
        """
from nbadb.schemas._foo_common import _FooMetricMixin


class StagingFooSchema(_FooMetricMixin):
    foo_id: int
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_open_contract_staging_schema(project_root: Path) -> None:
    staging_dir = project_root / "src" / "nbadb" / "schemas" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "__init__.py").write_text("", encoding="utf-8")
    (staging_dir / "stg_foo.py").write_text(
        """
class _OpenStagingSchema:
    @classmethod
    def validate(cls, data, *args, **kwargs):
        return data


class StagingFooSchema(_OpenStagingSchema):
    foo_id: int
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_open_passthrough_contract_staging_schema(project_root: Path) -> None:
    staging_dir = project_root / "src" / "nbadb" / "schemas" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "__init__.py").write_text("", encoding="utf-8")
    (staging_dir / "stg_foo.py").write_text(
        """
class _OpenPassthroughSchema:
    @classmethod
    def validate(cls, data, *args, **kwargs):
        return data


class StagingFooSchema(_OpenPassthroughSchema):
    foo_id: int
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


def test_staging_result_set_shape_helper_classifies_multi_result_entries() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    assert (
        EndpointCoverageGenerator._staging_result_set_shape(
            StagingEntry("foo", "stg_foo", "season")
        )
        == "single_result"
    )
    assert (
        EndpointCoverageGenerator._staging_result_set_shape(
            StagingEntry("foo", "stg_foo", "season", result_set_index=0, use_multi=True)
        )
        == "multi_result_primary"
    )
    assert (
        EndpointCoverageGenerator._staging_result_set_shape(
            StagingEntry("foo", "stg_foo", "season", result_set_index=3, use_multi=True)
        )
        == "multi_result_secondary"
    )


def test_season_type_value_gaps_flags_missing_supported_season_types() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    entries = [
        StagingEntry(
            "foo_endpoint",
            "stg_foo_primary",
            "season",
            season_type_capability="supported",
            supported_season_types=("Regular Season", "Playoffs"),
        ),
        StagingEntry(
            "foo_endpoint",
            "stg_foo_secondary",
            "season",
            season_type_capability="supported",
        ),
    ]

    assert EndpointCoverageGenerator._season_type_value_gaps(entries, "historical_backfill") == [
        "supported_season_types_missing"
    ]


def test_season_type_value_gaps_flags_mixed_supported_season_types() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    entries = [
        StagingEntry(
            "foo_endpoint",
            "stg_foo_regular",
            "season",
            season_type_capability="supported",
            supported_season_types=("Regular Season",),
        ),
        StagingEntry(
            "foo_endpoint",
            "stg_foo_playoffs",
            "season",
            season_type_capability="supported",
            supported_season_types=("Playoffs",),
        ),
    ]

    assert EndpointCoverageGenerator._season_type_value_gaps(entries, "historical_backfill") == [
        "supported_season_types_mixed"
    ]


def test_build_artifacts_includes_staging_result_set_shape_breakdown(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_sample_transforms(project_root)
    staging_entries = [
        StagingEntry("foo_endpoint", "stg_foo", "season"),
        StagingEntry(
            "gap_endpoint",
            "stg_gap_primary",
            "game",
            result_set_index=0,
            use_multi=True,
        ),
        StagingEntry(
            "gap_endpoint",
            "stg_gap_detail",
            "game",
            result_set_index=1,
            use_multi=True,
        ),
    ]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint", "GapEndpoint"},
        runtime_version="shape-test-runtime",
    )

    model_ownership = artifacts["summary"]["model_ownership"]
    assert model_ownership["staging_result_set_shape_breakdown"] == {
        "multi_result_primary": 1,
        "multi_result_secondary": 1,
        "single_result": 1,
    }


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
    support_matrix_payload = json.loads(written["support_matrix"].read_text(encoding="utf-8"))
    support_summary_payload = json.loads(written["support_summary"].read_text(encoding="utf-8"))
    temporal_support_ledger_payload = json.loads(
        written["temporal_support_ledger"].read_text(encoding="utf-8")
    )
    endpoint_adequacy_payload = json.loads(
        written["endpoint_adequacy_scorecard"].read_text(encoding="utf-8")
    )
    support_report_text = written["support_report"].read_text(encoding="utf-8")
    extraction_matrix_payload = json.loads(written["extraction_matrix"].read_text(encoding="utf-8"))
    extraction_summary_payload = json.loads(
        written["extraction_summary"].read_text(encoding="utf-8")
    )
    extraction_report_text = written["extraction_report"].read_text(encoding="utf-8")
    full_extraction_definition = json.loads(
        written["full_extraction_definition"].read_text(encoding="utf-8")
    )
    endpoint_adequacy_report_text = written["endpoint_adequacy_report"].read_text(encoding="utf-8")

    assert "matrix" in matrix_payload
    assert "coverage" in summary_payload
    assert "Endpoint Coverage Report" in report_text
    assert "Star Schema Coverage" in report_text
    assert "| Param Pattern |" in report_text
    assert "matrix" in support_matrix_payload
    assert "gap_endpoint_count" in support_summary_payload
    assert "ledger" in temporal_support_ledger_payload
    assert "summary" in temporal_support_ledger_payload
    assert "Endpoint Support Matrix" in support_report_text
    assert "matrix" in extraction_matrix_payload
    assert "extractable_endpoint_count" in extraction_summary_payload
    assert "Endpoint Extraction Contract" in extraction_report_text
    assert "ready_for_full_backfill" in full_extraction_definition
    assert "Temporal Support Ledger" in support_report_text
    assert "scorecard" in endpoint_adequacy_payload
    assert "Endpoint Adequacy Scorecard" in endpoint_adequacy_report_text
    assert "Strict Build Contract" in report_text


def test_build_artifacts_emits_endpoint_adequacy_scorecard(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_play_by_play_extractor(project_root)
    _write_sample_transforms(project_root)
    _write_sample_staging_schemas(project_root)
    _write_sample_star_schemas(project_root)
    staging_entries = [
        StagingEntry("foo_endpoint", "stg_foo", "season"),
        StagingEntry("gap_endpoint", "stg_gap", "game"),
        StagingEntry("play_by_play", "stg_play_by_play_video_available", "game"),
        StagingEntry("staging_only", "stg_only", "player"),
    ]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint", "PlayByPlayV3"},
        runtime_version="test-runtime",
    )

    scorecard = artifacts["endpoint_adequacy_scorecard"]
    rows = {row["endpoint_name"]: row for row in scorecard["scorecard"]}

    assert rows["foo_endpoint"]["adequacy_status"] == "adequate"
    assert rows["foo_endpoint"]["downstream_status"] == "modeled"
    assert rows["gap_endpoint"]["adequacy_status"] == "runtime_gap"
    assert rows["gap_endpoint"]["downstream_status"] == "unowned"
    assert rows["play_by_play"]["adequacy_status"] == "gap"
    assert rows["play_by_play"]["downstream_status"] == "excluded"

    summary = scorecard["summary"]
    assert summary["endpoint_count"] >= 5
    assert summary["adequate_endpoint_count"] == 1
    assert summary["downstream_modeled_endpoint_count"] == 1
    assert summary["downstream_passthrough_only_endpoint_count"] == 0
    assert summary["downstream_compatibility_reference_only_endpoint_count"] == 0
    assert summary["downstream_excluded_endpoint_count"] == 1
    assert summary["downstream_unowned_endpoint_count"] == 2


def test_write_endpoint_adequacy_scorecard_only_emits_scorecard_pair(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_play_by_play_extractor(project_root)
    _write_sample_transforms(project_root)
    _write_sample_staging_schemas(project_root)
    _write_sample_star_schemas(project_root)

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[
            StagingEntry("foo_endpoint", "stg_foo", "season"),
            StagingEntry("gap_endpoint", "stg_gap", "game"),
            StagingEntry("play_by_play", "stg_play_by_play_video_available", "game"),
        ],
    )
    destination = tmp_path / "out"

    written = generator.write_endpoint_adequacy_scorecard(
        output_dir=destination,
        runtime_endpoint_classes={"FooEndpoint", "PlayByPlayV3"},
        runtime_version="test-runtime",
    )

    assert set(written) == {"endpoint_adequacy_scorecard", "endpoint_adequacy_report"}
    assert written["endpoint_adequacy_scorecard"].exists()
    assert written["endpoint_adequacy_report"].exists()
    assert not (destination / "endpoint-support-summary.json").exists()
    assert not (destination / "endpoint-coverage-summary.json").exists()


def test_build_artifacts_distinguishes_passthrough_only_downstream_status(
    tmp_path: Path,
) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_sample_staging_schemas(project_root)
    star_dir = project_root / "src" / "nbadb" / "schemas" / "star"
    facts_dir = project_root / "src" / "nbadb" / "transform" / "facts"
    star_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = project_root / "src" / "nbadb" / "schemas" / "staging"
    facts_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    (star_dir / "__init__.py").write_text("", encoding="utf-8")
    (facts_dir / "__init__.py").write_text("", encoding="utf-8")
    (staging_dir / "__init__.py").write_text("", encoding="utf-8")
    (staging_dir / "stg_gap.py").write_text(
        """
class StagingGapSchema:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (star_dir / "fact_gap.py").write_text(
        """
class FactGapSchema:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (facts_dir / "fact_gap_passthrough.py").write_text(
        """
from nbadb.transform.base import make_passthrough

FactGapTransformer = make_passthrough("fact_gap", "stg_gap")
""".strip()
        + "\n",
        encoding="utf-8",
    )

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("gap_endpoint", "stg_gap", "game")],
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"GapEndpoint"},
        runtime_version="test-runtime",
    )

    rows = {row["endpoint_name"]: row for row in artifacts["matrix"]}
    assert rows["gap_endpoint"]["model_status"] == "passthrough_only"

    support_rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}
    assert support_rows["gap_endpoint"]["contract_status"] == "complete"
    assert support_rows["gap_endpoint"]["downstream_status"] == "passthrough_only"

    scorecard_rows = {
        row["endpoint_name"]: row for row in artifacts["endpoint_adequacy_scorecard"]["scorecard"]
    }
    assert scorecard_rows["gap_endpoint"]["adequacy_status"] == "passthrough_only"


def test_build_artifacts_emits_temporal_support_ledger(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    stats_dir = project_root / "src" / "nbadb" / "extract" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "__init__.py").write_text("", encoding="utf-8")
    (stats_dir / "temporal_extractors.py").write_text(
        """
from nba_api.stats.endpoints import BlockedSeason, HistoricalSeason
from nbadb.extract.base import BaseExtractor


class HistoricalSeasonExtractor(BaseExtractor):
    endpoint_name = "historical_season"

    async def extract(self, **params):
        return self._from_nba_api(HistoricalSeason, **params)


class BlockedSeasonExtractor(BaseExtractor):
    endpoint_name = "blocked_season"

    async def extract(self, **params):
        return self._from_nba_api(BlockedSeason, **params)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[
            StagingEntry(
                "historical_season",
                "stg_historical_season",
                "season",
                season_type_capability="supported",
                supported_season_types=("Regular Season", "Playoffs"),
                min_season=2001,
            ),
            StagingEntry(
                "blocked_season",
                "stg_blocked_season",
                "player_team_season",
                season_type_capability="blocked",
                min_season=2010,
            ),
        ],
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"HistoricalSeason", "BlockedSeason"},
        runtime_version="test-runtime",
    )

    ledger = artifacts["temporal_support_ledger"]
    rows = {row["ledger_key"]: row for row in ledger["ledger"]}

    assert ledger["summary"]["endpoint_count"] == 2
    assert ledger["summary"]["ledger_row_count"] == 3
    assert ledger["summary"]["support_window_count"] == 2
    assert ledger["summary"]["season_type_row_count"] == 2
    assert ledger["summary"]["untracked_season_type_row_count"] == 1
    assert ledger["summary"]["season_type_capability_breakdown"] == {
        "blocked": 1,
        "supported": 2,
    }

    supported_regular = rows["historical_season:stg_historical_season:Regular Season:0"]
    assert supported_regular["historical_start_season"] == 2001
    assert supported_regular["season_type_capability"] == "supported"
    assert supported_regular["supported_season_types"] == [
        "Regular Season",
        "Playoffs",
    ]
    assert supported_regular["transform_outputs"] == []

    blocked_row = rows["blocked_season:stg_blocked_season:all:0"]
    assert blocked_row["season_type"] is None
    assert blocked_row["season_type_capability"] == "blocked"
    assert blocked_row["historical_start_season"] == 2010


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

    support_rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}
    assert support_rows["player_compare"]["earliest_supported_season"] is None
    assert support_rows["player_compare"]["contract_status"] == "gap"
    assert "staging_contract_missing" in support_rows["player_compare"]["contract_gaps"]


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


def test_support_matrix_reads_staging_schema_from_project_root(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_sample_transforms(project_root)
    _write_sample_star_schemas(project_root)
    _write_sample_staging_schemas(project_root)
    staging_entries = [StagingEntry("foo_endpoint", "stg_foo", "season")]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="test-runtime",
    )

    support_rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}
    assert support_rows["foo_endpoint"]["contract_status"] == "complete"
    assert support_rows["foo_endpoint"]["input_schema_missing_staging_keys"] == []


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
    assert model_ownership["analytically_modeled_staging_entries"] == 0
    assert model_ownership["passthrough_only_staging_entries"] == 0
    assert model_ownership["compatibility_reference_only_staging_entries"] == 2
    assert model_ownership["model_excluded_staging_entries"] == 0
    assert model_ownership["model_unowned_staging_entries"] == 0
    assert model_ownership["compatibility_reference_staging_entries_detail"] == [
        {
            "staging_key": "stg_pvp_player_info",
            "endpoint_name": "player_vs_player",
            "reason": (
                "Duplicate player bio packet is retained as a compatibility/reference "
                "surface; the analytical model uses canonical player dimensions."
            ),
            "transform_outputs": [],
        },
        {
            "staging_key": "stg_pvp_vs_player_info",
            "endpoint_name": "player_vs_player",
            "reason": (
                "Duplicate opposing-player bio packet is retained as a "
                "compatibility/reference surface; the analytical model uses canonical "
                "player dimensions."
            ),
            "transform_outputs": [],
        },
    ]
    assert model_ownership["excluded_staging_entries_detail"] == []

    support_rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}
    assert support_rows["player_vs_player"]["contract_status"] == "gap"
    assert support_rows["player_vs_player"]["downstream_status"] == "compatibility_reference_only"
    assert len(support_rows["player_vs_player"]["downstream_reasons"]) == 2
    assert "model_excluded" not in support_rows["player_vs_player"]["contract_gaps"]
    assert "transform_contract_missing" in support_rows["player_vs_player"]["contract_gaps"]


def test_build_artifacts_does_not_mark_consumed_excluded_staging_keys_as_model_excluded(
    tmp_path: Path,
) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    stats_dir = project_root / "src" / "nbadb" / "extract" / "stats"
    facts_dir = project_root / "src" / "nbadb" / "transform" / "facts"
    schemas_dir = project_root / "src" / "nbadb" / "schemas" / "star"
    stats_dir.mkdir(parents=True, exist_ok=True)
    facts_dir.mkdir(parents=True, exist_ok=True)
    schemas_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "__init__.py").write_text("", encoding="utf-8")
    (facts_dir / "__init__.py").write_text("", encoding="utf-8")
    (schemas_dir / "__init__.py").write_text("", encoding="utf-8")
    (stats_dir / "play_by_play_extractors.py").write_text(
        """
from nba_api.stats.endpoints import PlayByPlayV3
from nbadb.extract.base import BaseExtractor


class PlayByPlayExtractor(BaseExtractor):
    endpoint_name = "play_by_play"

    async def extract(self, **params):
        return self._from_nba_api(PlayByPlayV3, **params)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (facts_dir / "fact_play_video_flag.py").write_text(
        """
from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayVideoFlagTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_play_video_flag"
    depends_on: ClassVar[list[str]] = ["stg_play_by_play_video_available"]
    _SQL: ClassVar[str] = "SELECT 1 AS x"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (schemas_dir / "fact_play_video_flag.py").write_text(
        """
class FactPlayVideoFlagSchema:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[
            StagingEntry("play_by_play", "stg_play_by_play_video_available", "game"),
        ],
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"PlayByPlayV3"},
        runtime_version="strict-runtime",
    )

    support_rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}
    assert "model_excluded" not in support_rows["play_by_play"]["contract_gaps"]


def test_build_artifacts_does_not_mark_consumed_endpoint_exclusions_as_model_excluded(
    tmp_path: Path,
) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    stats_dir = project_root / "src" / "nbadb" / "extract" / "stats"
    facts_dir = project_root / "src" / "nbadb" / "transform" / "facts"
    stats_dir.mkdir(parents=True, exist_ok=True)
    facts_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "__init__.py").write_text("", encoding="utf-8")
    (facts_dir / "__init__.py").write_text("", encoding="utf-8")
    (stats_dir / "gl_alum.py").write_text(
        """
from nba_api.stats.endpoints import BoxScoreTraditionalV3
from nbadb.extract.base import BaseExtractor


class GlAlumSimilarityExtractor(BaseExtractor):
    endpoint_name = "gl_alum_box_score_similarity_score"

    async def extract(self, **params):
        return self._from_nba_api(BoxScoreTraditionalV3, **params)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (facts_dir / "fact_gl_alum_similarity.py").write_text(
        """
from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactGlAlumSimilarityTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_gl_alum_similarity"
    depends_on: ClassVar[list[str]] = ["stg_gl_alum_box_score_similarity_score"]
    _SQL: ClassVar[str] = "SELECT 1 AS x"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[
            StagingEntry(
                "gl_alum_box_score_similarity_score",
                "stg_gl_alum_box_score_similarity_score",
                "player_team_season",
            ),
        ],
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"BoxScoreTraditionalV3"},
        runtime_version="strict-runtime",
    )

    support_rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}
    assert (
        "model_excluded" not in support_rows["gl_alum_box_score_similarity_score"]["contract_gaps"]
    )


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


def _dashboard_frame(extractor, endpoint_cls, **params):
    return extractor._from_nba_api(endpoint_cls, **params)


class PlayerDashGameSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dash_game_splits"

    async def extract(self, **params):
        return _dashboard_frame(
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
    assert rows["video_status"]["model_status"] == "compatibility_reference_only"
    assert rows["video_status"]["model_status_reasons"] != []

    support_rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}
    assert support_rows["video_status"]["contract_status"] == "gap"
    assert support_rows["video_status"]["downstream_status"] == "compatibility_reference_only"
    assert "transform_contract_missing" in support_rows["video_status"]["contract_gaps"]


def test_runtime_contract_mapping_prefers_canonical_contract_over_alias() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract

    canonical_contract = NbaApiEndpointContract(
        runtime_class_name="BoxScoreTraditionalV3",
        module_name="nba_api.stats.endpoints.boxscoretraditionalv3",
        endpoint_slug="boxscoretraditionalv3",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=(),
    )
    alias_contract = NbaApiEndpointContract(
        runtime_class_name="BoxScoreTraditionalV2",
        module_name="nba_api.stats.endpoints.boxscoretraditionalv2",
        endpoint_slug="boxscoretraditionalv2",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=(),
    )

    contracts_by_endpoint = EndpointCoverageGenerator._runtime_contracts_by_endpoint(
        {
            "BoxScoreTraditionalV3": canonical_contract,
            "BoxScoreTraditionalV2": alias_contract,
        },
        {"box_score_traditional"},
    )

    assert contracts_by_endpoint["box_score_traditional"] is canonical_contract


def test_build_artifacts_keeps_canonical_contract_for_alias_only_runtime_filter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract

    project_root = tmp_path / "project"
    _write_runtime_alias_extractors(project_root)

    canonical_contract = NbaApiEndpointContract(
        runtime_class_name="BoxScoreTraditionalV3",
        module_name="nba_api.stats.endpoints.boxscoretraditionalv3",
        endpoint_slug="boxscoretraditionalv3",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=(),
    )
    alias_contract = NbaApiEndpointContract(
        runtime_class_name="BoxScoreTraditionalV2",
        module_name="nba_api.stats.endpoints.boxscoretraditionalv2",
        endpoint_slug="boxscoretraditionalv2",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {
            "BoxScoreTraditionalV3": canonical_contract,
            "BoxScoreTraditionalV2": alias_contract,
        },
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("box_score_traditional", "stg_box_score", "game")],
    ).build_artifacts(
        runtime_endpoint_classes={"BoxScoreTraditionalV2"},
        runtime_version="alias-only-runtime",
    )

    assert artifacts["upstream_contracts"] == [
        {
            "endpoint_name": "box_score_traditional",
            "runtime_class_name": "BoxScoreTraditionalV3",
            "module_name": "nba_api.stats.endpoints.boxscoretraditionalv3",
            "endpoint_slug": "boxscoretraditionalv3",
            "parameters": [],
            "required_parameters": [],
            "nullable_parameters": [],
            "deprecated": False,
            "warnings": [],
            "result_sets": [],
        }
    ]


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
    assert model_ownership["analytically_modeled_staging_entries"] == 1
    assert model_ownership["passthrough_only_staging_entries"] == 0
    assert model_ownership["compatibility_reference_only_staging_entries"] == 0
    assert model_ownership["model_excluded_staging_entries"] == 0
    assert model_ownership["model_unowned_staging_entries"] == 0
    assert model_ownership["analytically_modeled_stats_endpoints"] == 1
    assert model_ownership["passthrough_only_stats_endpoints"] == 0
    assert model_ownership["compatibility_reference_only_stats_endpoints"] == 0
    assert model_ownership["model_excluded_stats_endpoints"] == 0
    assert model_ownership["model_unowned_stats_endpoints"] == 0


def test_build_artifacts_includes_upstream_contracts_and_diff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_contract_staging_schema(project_root)
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=("season",),
        required_parameters=("season",),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FOO_ID", "TEAM_ID", "MISSING_FIELD"),
                source="expected_data",
                confidence="high",
            ),
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=1,
                result_set_name="EmptyConditionalSet",
                expected_columns=(),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=("synthetic_warning",),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[
            StagingEntry("foo_endpoint", "stg_foo", "season", result_set_index=0, use_multi=True),
            StagingEntry("foo_endpoint", "stg_foo_single", "season"),
            StagingEntry(
                "foo_endpoint",
                "stg_foo_missing_packet",
                "season",
                result_set_index=9,
                use_multi=True,
            ),
        ],
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    assert artifacts["upstream_contracts"] == [
        {
            "endpoint_name": "foo_endpoint",
            "runtime_class_name": "FooEndpoint",
            "module_name": "nba_api.stats.endpoints.fooendpoint",
            "endpoint_slug": "fooendpoint",
            "parameters": ["season"],
            "required_parameters": ["season"],
            "nullable_parameters": [],
            "deprecated": False,
            "warnings": ["synthetic_warning"],
            "result_sets": [
                {
                    "runtime_class_name": "FooEndpoint",
                    "result_set_index": 0,
                    "result_set_name": "PrimarySet",
                    "expected_columns": ["FOO_ID", "TEAM_ID", "MISSING_FIELD"],
                    "source": "expected_data",
                    "confidence": "high",
                },
                {
                    "runtime_class_name": "FooEndpoint",
                    "result_set_index": 1,
                    "result_set_name": "EmptyConditionalSet",
                    "expected_columns": [],
                    "source": "expected_data",
                    "confidence": "high",
                },
            ],
        }
    ]
    assert artifacts["summary"]["upstream_contract"] == {
        "endpoint_contract_count": 1,
        "staging_endpoint_count": 1,
        "invalid_result_set_index_count": 1,
        "missing_result_set_staging_count": 0,
        "field_gap_count": 2,
        "empty_expected_result_set_count": 0,
        "contract_unknown_result_set_count": 0,
        "classified_contract_unknown_result_set_count": 0,
        "blocking_contract_unknown_result_set_count": 0,
        "missing_input_schema_count": 0,
    }

    diff_rows = artifacts["upstream_contract_diff"]["matrix"]
    assert [row["status"] for row in diff_rows] == [
        "field_gaps",
        "field_gaps",
        "invalid_result_set_index",
    ]
    assert diff_rows[0]["missing_columns"] == ["missing_field"]
    assert diff_rows[1]["declared_result_set_index"] == 0
    assert diff_rows[1]["missing_columns"] == ["missing_field"]
    assert diff_rows[2]["declared_result_set_index"] == 9


def test_upstream_contract_diff_uses_ingested_column_names_and_schema_aliases(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_contract_staging_schema_with_aliases(project_root)
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FG3A", "FG3A_RANK", "PASS"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    assert artifacts["summary"]["upstream_contract"]["field_gap_count"] == 0
    assert artifacts["upstream_contract_diff"]["matrix"] == [
        {
            "endpoint_name": "foo_endpoint",
            "runtime_class_name": "FooEndpoint",
            "staging_key": "stg_foo",
            "declared_result_set_index": 0,
            "upstream_result_set_name": "PrimarySet",
            "status": "ok",
            "expected_columns": ["fg3a", "fg3a_rank", "pass"],
            "missing_columns": [],
        }
    ]


def test_build_artifacts_compares_endpoint_analysis_docs_to_runtime_contracts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    runtime_contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=("season",),
        required_parameters=("season",),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FOO_ID", "RUNTIME_ONLY"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    docs_contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.docs.nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=("Season",),
        required_parameters=("Season",),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FOO_ID", "DOC_ONLY"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=1,
                result_set_name="DocOnlySet",
                expected_columns=("DOC_ID",),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": runtime_contract},
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_endpoint_analysis_doc_contracts",
        lambda _root: {"FooEndpoint": docs_contract},
    )

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        endpoint_analysis_docs_root=tmp_path / "nba_api",
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    docs_summary = artifacts["summary"]["endpoint_analysis_docs"]
    assert docs_summary["enabled"] is True
    assert docs_summary["docs_contract_count"] == 1
    assert docs_summary["docs_only_result_set_count"] == 1
    assert docs_summary["docs_field_missing_in_runtime_count"] == 1
    assert docs_summary["runtime_field_missing_in_docs_count"] == 1
    assert docs_summary["blocking_docs_contract_gap_count"] == 1
    statuses = [row["status"] for row in artifacts["endpoint_analysis_doc_diff"]["matrix"]]
    assert statuses == [
        "docs_only_result_set",
        "docs_fields_missing_in_runtime",
        "runtime_fields_missing_in_docs",
    ]


def test_docs_upstream_contract_diff_resolves_result_sets_by_schema_when_order_differs() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    docs_contract = NbaApiEndpointContract(
        runtime_class_name="BoxScoreSummaryV3",
        module_name="nba_api.docs.nba_api.stats.endpoints.boxscoresummaryv3",
        endpoint_slug="boxscoresummaryv3",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="BoxScoreSummaryV3",
                result_set_index=0,
                result_set_name="ArenaInfo",
                expected_columns=("gameId", "arenaId", "arenaName"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
            NbaApiResultSetContract(
                runtime_class_name="BoxScoreSummaryV3",
                result_set_index=1,
                result_set_name="GameSummary",
                expected_columns=("gameId", "gameCode", "gameStatusText"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )

    diff = EndpointCoverageGenerator._build_upstream_contract_diff(
        contracts_by_endpoint={"box_score_summary_v3": docs_contract},
        staging_entries_by_endpoint={
            "box_score_summary_v3": [
                StagingEntry(
                    "box_score_summary_v3",
                    "stg_summary_v3_game_summary",
                    "game",
                    result_set_index=0,
                    use_multi=True,
                ),
                StagingEntry(
                    "box_score_summary_v3",
                    "stg_arena_info",
                    "game",
                    result_set_index=1,
                    use_multi=True,
                ),
            ],
        },
        input_schema_columns={
            "stg_summary_v3_game_summary": {
                "game_id",
                "game_code",
                "game_status_text",
            },
            "stg_arena_info": {"game_id", "arena_id", "arena_name"},
        },
        input_schema_behaviors={
            "stg_summary_v3_game_summary": "closed",
            "stg_arena_info": "closed",
        },
    )

    rows = {row["staging_key"]: row for row in diff["matrix"]}
    assert diff["summary"]["field_gap_count"] == 0
    assert rows["stg_summary_v3_game_summary"]["status"] == "ok"
    assert rows["stg_summary_v3_game_summary"]["upstream_result_set_name"] == "GameSummary"
    assert rows["stg_summary_v3_game_summary"]["resolved_result_set_index"] == 1
    assert rows["stg_arena_info"]["status"] == "ok"
    assert rows["stg_arena_info"]["upstream_result_set_name"] == "ArenaInfo"
    assert rows["stg_arena_info"]["resolved_result_set_index"] == 0


def test_schema_annotation_routes_reuse_docs_result_set_remap() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    docs_contract = NbaApiEndpointContract(
        runtime_class_name="BoxScoreSummaryV3",
        module_name="nba_api.docs.nba_api.stats.endpoints.boxscoresummaryv3",
        endpoint_slug="boxscoresummaryv3",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="BoxScoreSummaryV3",
                result_set_index=0,
                result_set_name="ArenaInfo",
                expected_columns=("gameId", "arenaId", "arenaName"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
            NbaApiResultSetContract(
                runtime_class_name="BoxScoreSummaryV3",
                result_set_index=1,
                result_set_name="GameSummary",
                expected_columns=("gameId", "gameCode", "gameStatusText"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )

    provenance = EndpointCoverageGenerator._build_schema_annotation_route_provenance(
        contracts_by_endpoint={"box_score_summary_v3": docs_contract},
        staging_entries_by_endpoint={
            "box_score_summary_v3": [
                StagingEntry(
                    "box_score_summary_v3",
                    "stg_summary_v3_game_summary",
                    "game",
                    result_set_index=0,
                    use_multi=True,
                ),
                StagingEntry(
                    "box_score_summary_v3",
                    "stg_arena_info",
                    "game",
                    result_set_index=1,
                    use_multi=True,
                ),
            ]
        },
        input_schema_columns={
            "stg_summary_v3_game_summary": {
                "game_id",
                "game_code",
                "game_status_text",
            },
            "stg_arena_info": {"game_id", "arena_id", "arena_name"},
        },
        input_schema_behaviors={
            "stg_summary_v3_game_summary": "closed",
            "stg_arena_info": "closed",
        },
    )

    game_summary_routes = [
        route
        for route in provenance["routes"]
        if route["staging_key"] == "stg_summary_v3_game_summary"
    ]
    arena_routes = [
        route for route in provenance["routes"] if route["staging_key"] == "stg_arena_info"
    ]
    assert provenance["summary"] == {
        "route_field_count": 6,
        "route_status_counts": {"declared": 6},
        "blocking_route_field_count": 0,
    }
    assert {route["source_result_set_name"] for route in game_summary_routes} == {"GameSummary"}
    assert {route["source_result_set_index"] for route in game_summary_routes} == {1}
    assert {route["declared_result_set_index"] for route in game_summary_routes} == {0}
    assert {route["source_result_set_name"] for route in arena_routes} == {"ArenaInfo"}
    assert {route["source_result_set_index"] for route in arena_routes} == {0}
    assert {route["declared_result_set_index"] for route in arena_routes} == {1}


def test_schema_annotation_routes_reuse_canonical_aliases_and_open_schemas() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    schedule_contract = NbaApiEndpointContract(
        runtime_class_name="ScheduleLeagueV2",
        module_name="nba_api.docs.nba_api.stats.endpoints.scheduleleaguev2",
        endpoint_slug="scheduleleaguev2",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="ScheduleLeagueV2",
                result_set_index=0,
                result_set_name="Schedule",
                expected_columns=("gameDate",),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    synergy_contract = NbaApiEndpointContract(
        runtime_class_name="SynergyPlayTypes",
        module_name="nba_api.docs.nba_api.stats.endpoints.synergyplaytypes",
        endpoint_slug="synergyplaytypes",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="SynergyPlayTypes",
                result_set_index=0,
                result_set_name="Synergy",
                expected_columns=("TOV_POSS_PCT", "UNMODELED_VALUE"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )

    provenance = EndpointCoverageGenerator._build_schema_annotation_route_provenance(
        contracts_by_endpoint={
            "schedule": schedule_contract,
            "synergy_play_types": synergy_contract,
        },
        staging_entries_by_endpoint={
            "schedule": [StagingEntry("schedule", "stg_schedule", "season")],
            "synergy_play_types": [
                StagingEntry("synergy_play_types", "stg_synergy_play_types", "season")
            ],
        },
        input_schema_columns={
            "stg_schedule": {"game_date"},
            "stg_synergy_play_types": {"to_pct"},
        },
        input_schema_behaviors={
            "stg_schedule": "closed",
            "stg_synergy_play_types": "passthrough",
        },
    )

    routes = {route["source_column"]: route for route in provenance["routes"]}
    assert routes["gameDate"]["normalized_column"] == "game_date"
    assert routes["gameDate"]["route_status"] == "declared"
    assert routes["TOV_POSS_PCT"]["normalized_column"] == "to_pct"
    assert routes["TOV_POSS_PCT"]["route_status"] == "declared"
    assert routes["UNMODELED_VALUE"]["normalized_column"] == "unmodeled_value"
    assert routes["UNMODELED_VALUE"]["route_status"] == "open_passthrough"
    assert provenance["summary"]["blocking_route_field_count"] == 0
    assert provenance["superseded_runtime_classes"]["BoxScoreMiscV2"] == "BoxScoreMiscV3"


def test_docs_upstream_contract_diff_resolves_with_declared_index_column_aliases() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    docs_contract = NbaApiEndpointContract(
        runtime_class_name="BoxScoreSummaryV3",
        module_name="nba_api.docs.nba_api.stats.endpoints.boxscoresummaryv3",
        endpoint_slug="boxscoresummaryv3",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="BoxScoreSummaryV3",
                result_set_index=1,
                result_set_name="AvailableVideo",
                expected_columns=(
                    "gameId",
                    "videoAvailableFlag",
                    "ptAvailable",
                    "ptXYZAvailable",
                    "whStatus",
                    "hustleStatus",
                    "historicalStatus",
                ),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
            NbaApiResultSetContract(
                runtime_class_name="BoxScoreSummaryV3",
                result_set_index=8,
                result_set_name="OtherStats",
                expected_columns=("gameId", "teamId", "benchPoints"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )

    diff = EndpointCoverageGenerator._build_upstream_contract_diff(
        contracts_by_endpoint={"box_score_summary_v3": docs_contract},
        staging_entries_by_endpoint={
            "box_score_summary_v3": [
                StagingEntry(
                    "box_score_summary_v3",
                    "stg_summary_v3_available_video",
                    "game",
                    result_set_index=8,
                    use_multi=True,
                )
            ],
        },
        input_schema_columns={
            "stg_summary_v3_available_video": {
                "game_id",
                "video_available_flag",
                "pt_available",
                "pt_xyz_available",
                "wh_status",
                "hustle_status",
                "historical_status",
            }
        },
        input_schema_behaviors={"stg_summary_v3_available_video": "closed"},
    )

    row = diff["matrix"][0]
    assert diff["summary"]["field_gap_count"] == 0
    assert diff["summary"]["missing_result_set_staging_count"] == 1
    assert row["status"] == "ok"
    assert row["upstream_result_set_name"] == "AvailableVideo"
    assert row["resolved_result_set_index"] == 1
    assert "pt_xyz_available" in row["expected_columns"]


def test_docs_upstream_contract_diff_does_not_resolve_to_subset_result_set() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    docs_contract = NbaApiEndpointContract(
        runtime_class_name="SubsetEndpoint",
        module_name="nba_api.docs.nba_api.stats.endpoints.subsetendpoint",
        endpoint_slug="subsetendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="SubsetEndpoint",
                result_set_index=0,
                result_set_name="DeclaredSet",
                expected_columns=("gameId", "newField"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
            NbaApiResultSetContract(
                runtime_class_name="SubsetEndpoint",
                result_set_index=1,
                result_set_name="SubsetSet",
                expected_columns=("gameId",),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )

    diff = EndpointCoverageGenerator._build_upstream_contract_diff(
        contracts_by_endpoint={"subset_endpoint": docs_contract},
        staging_entries_by_endpoint={
            "subset_endpoint": [
                StagingEntry(
                    "subset_endpoint",
                    "stg_subset_declared",
                    "game",
                    result_set_index=0,
                    use_multi=True,
                )
            ],
        },
        input_schema_columns={"stg_subset_declared": {"game_id"}},
        input_schema_behaviors={"stg_subset_declared": "closed"},
    )

    field_gap_row = diff["matrix"][0]
    missing_staging_row = diff["matrix"][1]
    assert diff["summary"]["field_gap_count"] == 1
    assert diff["summary"]["missing_result_set_staging_count"] == 1
    assert field_gap_row["status"] == "field_gaps"
    assert field_gap_row["upstream_result_set_name"] == "DeclaredSet"
    assert field_gap_row["missing_columns"] == ["new_field"]
    assert "resolved_result_set_index" not in field_gap_row
    assert missing_staging_row["status"] == "missing_result_set_staging"
    assert missing_staging_row["upstream_result_set_name"] == "SubsetSet"


def test_build_artifacts_blocks_supplied_docs_root_with_zero_contracts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    runtime_contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": runtime_contract},
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_endpoint_analysis_doc_contracts",
        lambda _root: {},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        endpoint_analysis_docs_root=tmp_path / "empty-nba-api",
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    docs_summary = artifacts["summary"]["endpoint_analysis_docs"]
    assert docs_summary["docs_contract_discovery_failure_count"] == 1
    assert docs_summary["blocking_docs_contract_gap_count"] == 1
    assert artifacts["endpoint_analysis_doc_diff"]["matrix"][0]["status"] == (
        "docs_contract_discovery_failed"
    )


def test_upstream_contract_diff_uses_box_score_traditional_canonical_columns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_runtime_alias_extractors(project_root)
    staging_dir = project_root / "src" / "nbadb" / "schemas" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "__init__.py").write_text("", encoding="utf-8")
    (staging_dir / "stg_foo.py").write_text(
        """
class StagingFooSchema:
    game_id: str
    player_id: int
    fgm: int
""".strip()
        + "\n",
        encoding="utf-8",
    )
    contract = NbaApiEndpointContract(
        runtime_class_name="BoxScoreTraditionalV3",
        module_name="nba_api.stats.endpoints.boxscoretraditionalv3",
        endpoint_slug="boxscoretraditionalv3",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="BoxScoreTraditionalV3",
                result_set_index=0,
                result_set_name="PlayerStats",
                expected_columns=("GAME_ID", "personId", "fieldGoalsMade"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"BoxScoreTraditionalV3": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("box_score_traditional", "stg_foo", "game")],
    ).build_artifacts(
        runtime_endpoint_classes={"BoxScoreTraditionalV3"},
        runtime_version="contract-runtime",
    )

    assert artifacts["summary"]["upstream_contract"]["field_gap_count"] == 0
    assert artifacts["upstream_contract_diff"]["matrix"][0]["expected_columns"] == [
        "game_id",
        "player_id",
        "fgm",
    ]


def test_upstream_contract_diff_resolves_imported_schema_mixins(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_contract_staging_schema_with_imported_mixin(project_root)
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FOO_ID", "METRIC_VALUE"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    assert artifacts["summary"]["upstream_contract"]["field_gap_count"] == 0
    assert artifacts["upstream_contract_diff"]["matrix"][0]["status"] == "ok"


def test_upstream_field_fate_marks_open_schema_passthrough(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_open_contract_staging_schema(project_root)
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FOO_ID", "EXTRA_METRIC"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    assert artifacts["summary"]["upstream_contract"]["field_gap_count"] == 0
    assert artifacts["summary"]["upstream_field_fate"]["missing_sink_count"] == 0
    assert artifacts["summary"]["upstream_field_fate"]["sunk_passthrough_count"] == 1
    fate_by_field = {row["field_name"]: row for row in artifacts["upstream_field_fate"]["matrix"]}
    assert fate_by_field["foo_id"]["field_fate"] == "sink_declared_staging_only"
    assert fate_by_field["extra_metric"]["field_fate"] == "sunk_passthrough"
    assert fate_by_field["extra_metric"]["schema_behavior"] == "passthrough"


def test_upstream_field_fate_detects_open_passthrough_schema_base(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_open_passthrough_contract_staging_schema(project_root)
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FOO_ID", "EXTRA_METRIC"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    assert artifacts["summary"]["upstream_contract"]["field_gap_count"] == 0
    fate_by_field = {row["field_name"]: row for row in artifacts["upstream_field_fate"]["matrix"]}
    assert fate_by_field["extra_metric"]["field_fate"] == "sunk_passthrough"
    assert fate_by_field["extra_metric"]["schema_behavior"] == "passthrough"


def test_upstream_field_fate_resolves_result_sets_by_schema_when_order_differs() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    docs_contract = NbaApiEndpointContract(
        runtime_class_name="BoxScoreSummaryV3",
        module_name="nba_api.docs.nba_api.stats.endpoints.boxscoresummaryv3",
        endpoint_slug="boxscoresummaryv3",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="BoxScoreSummaryV3",
                result_set_index=0,
                result_set_name="ArenaInfo",
                expected_columns=("gameId", "arenaId", "arenaName"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
            NbaApiResultSetContract(
                runtime_class_name="BoxScoreSummaryV3",
                result_set_index=1,
                result_set_name="GameSummary",
                expected_columns=("gameId", "gameCode", "gameStatusText"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )

    fate = EndpointCoverageGenerator._build_upstream_field_fate_matrix(
        contracts_by_endpoint={"box_score_summary_v3": docs_contract},
        staging_entries_by_endpoint={
            "box_score_summary_v3": [
                StagingEntry(
                    "box_score_summary_v3",
                    "stg_summary_v3_game_summary",
                    "game",
                    result_set_index=0,
                    use_multi=True,
                ),
                StagingEntry(
                    "box_score_summary_v3",
                    "stg_arena_info",
                    "game",
                    result_set_index=1,
                    use_multi=True,
                ),
            ],
        },
        input_schema_columns={
            "stg_summary_v3_game_summary": {
                "game_id",
                "game_code",
                "game_status_text",
            },
            "stg_arena_info": {"game_id", "arena_id", "arena_name"},
        },
        input_schema_behaviors={
            "stg_summary_v3_game_summary": "closed",
            "stg_arena_info": "closed",
        },
        transform_outputs_by_staging={},
        transform_semantics_by_output={},
        transform_column_usage_by_staging={},
    )

    game_summary_rows = [
        row for row in fate["matrix"] if row["staging_key"] == "stg_summary_v3_game_summary"
    ]
    arena_rows = [row for row in fate["matrix"] if row["staging_key"] == "stg_arena_info"]
    assert fate["summary"]["invalid_result_set_count"] == 0
    assert fate["summary"]["missing_sink_count"] == 0
    assert fate["summary"]["upstream_field_count"] == 6
    assert fate["summary"]["field_fate_breakdown"] == {"sink_declared_staging_only": 6}
    assert {row["field_name"] for row in game_summary_rows} == {
        "game_id",
        "game_code",
        "game_status_text",
    }
    assert {row["upstream_result_set_name"] for row in game_summary_rows} == {"GameSummary"}
    assert {row["declared_result_set_index"] for row in game_summary_rows} == {0}
    assert {row["resolved_result_set_index"] for row in game_summary_rows} == {1}
    assert {row["field_name"] for row in arena_rows} == {
        "game_id",
        "arena_id",
        "arena_name",
    }
    assert {row["upstream_result_set_name"] for row in arena_rows} == {"ArenaInfo"}
    assert {row["declared_result_set_index"] for row in arena_rows} == {1}
    assert {row["resolved_result_set_index"] for row in arena_rows} == {0}


def test_upstream_field_fate_does_not_resolve_to_subset_result_set() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    docs_contract = NbaApiEndpointContract(
        runtime_class_name="SubsetEndpoint",
        module_name="nba_api.docs.nba_api.stats.endpoints.subsetendpoint",
        endpoint_slug="subsetendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="SubsetEndpoint",
                result_set_index=0,
                result_set_name="DeclaredSet",
                expected_columns=("gameId", "newField"),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
            NbaApiResultSetContract(
                runtime_class_name="SubsetEndpoint",
                result_set_index=1,
                result_set_name="SubsetSet",
                expected_columns=("gameId",),
                source="endpoint_analysis_docs",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )

    fate = EndpointCoverageGenerator._build_upstream_field_fate_matrix(
        contracts_by_endpoint={"subset_endpoint": docs_contract},
        staging_entries_by_endpoint={
            "subset_endpoint": [
                StagingEntry(
                    "subset_endpoint",
                    "stg_subset_declared",
                    "game",
                    result_set_index=0,
                    use_multi=True,
                )
            ],
        },
        input_schema_columns={"stg_subset_declared": {"game_id"}},
        input_schema_behaviors={"stg_subset_declared": "closed"},
        transform_outputs_by_staging={},
        transform_semantics_by_output={},
        transform_column_usage_by_staging={},
    )

    fate_by_field = {row["field_name"]: row for row in fate["matrix"]}
    assert fate["summary"]["missing_sink_count"] == 1
    assert fate["summary"]["sink_declared_staging_only_count"] == 1
    assert fate_by_field["game_id"]["field_fate"] == "sink_declared_staging_only"
    assert fate_by_field["new_field"]["field_fate"] == "missing_sink"
    assert fate_by_field["new_field"]["upstream_result_set_name"] == "DeclaredSet"
    assert fate_by_field["new_field"]["declared_result_set_index"] == 0
    assert fate_by_field["new_field"]["resolved_result_set_index"] == 0


def test_upstream_contract_diff_classifies_unknown_contract_result_sets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_open_passthrough_contract_staging_schema(project_root)
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    upstream_contract = artifacts["summary"]["upstream_contract"]
    assert upstream_contract["invalid_result_set_index_count"] == 0
    assert upstream_contract["empty_expected_result_set_count"] == 0
    assert upstream_contract["contract_unknown_result_set_count"] == 1
    assert upstream_contract["classified_contract_unknown_result_set_count"] == 0
    assert upstream_contract["blocking_contract_unknown_result_set_count"] == 1
    assert artifacts["summary"]["upstream_field_fate"]["invalid_result_set_count"] == 0
    assert artifacts["summary"]["upstream_field_fate"]["contract_unknown_result_set_count"] == 1
    assert (
        artifacts["summary"]["upstream_field_fate"]["blocking_contract_unknown_result_set_count"]
        == 1
    )
    diff_row = artifacts["upstream_contract_diff"]["matrix"][0]
    assert diff_row["status"] == "contract_unknown_result_set"
    assert diff_row["contract_unknown_classification"] == "blocking"
    assert "no static expected_data contract" in diff_row["status_reason"]


def test_upstream_contract_diff_keeps_classified_unknown_result_sets_nonblocking(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract

    project_root = tmp_path / "project"
    _write_runtime_alias_extractors(project_root)
    contract = NbaApiEndpointContract(
        runtime_class_name="VideoDetails",
        module_name="nba_api.stats.endpoints.videodetails",
        endpoint_slug="videodetails",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"VideoDetails": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("video_details", "stg_video_details", "game")],
    ).build_artifacts(
        runtime_endpoint_classes={"VideoDetails"},
        runtime_version="contract-runtime",
    )

    upstream_contract = artifacts["summary"]["upstream_contract"]
    assert upstream_contract["contract_unknown_result_set_count"] == 1
    assert upstream_contract["classified_contract_unknown_result_set_count"] == 1
    assert upstream_contract["blocking_contract_unknown_result_set_count"] == 0
    diff_row = artifacts["upstream_contract_diff"]["matrix"][0]
    assert diff_row["status"] == "contract_unknown_result_set"
    assert diff_row["contract_unknown_classification"] == "classified_non_blocking"
    assert "reference-only" in diff_row["contract_unknown_classification_reason"]


def test_upstream_field_fate_keeps_closed_schema_missing_sink(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_contract_staging_schema(project_root)
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FOO_ID", "MISSING_FIELD"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    assert artifacts["summary"]["upstream_contract"]["field_gap_count"] == 1
    assert artifacts["summary"]["upstream_field_fate"]["missing_sink_count"] == 1
    fate_by_field = {row["field_name"]: row for row in artifacts["upstream_field_fate"]["matrix"]}
    assert fate_by_field["missing_field"]["field_fate"] == "missing_sink"
    assert fate_by_field["missing_field"]["schema_behavior"] == "closed"


def test_upstream_field_fate_marks_only_referenced_columns_modeled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_contract_staging_schema(project_root)
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
    _SQL: ClassVar[str] = "SELECT foo_id FROM stg_foo"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FOO_ID", "TEAM_ID"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    fate_by_field = {row["field_name"]: row for row in artifacts["upstream_field_fate"]["matrix"]}
    assert fate_by_field["foo_id"]["field_fate"] == "modeled_column"
    assert fate_by_field["team_id"]["field_fate"] == "unmodeled_unclassified"
    assert artifacts["summary"]["upstream_field_fate"]["modeled_column_count"] == 1
    assert artifacts["summary"]["upstream_field_fate"]["unmodeled_unclassified_count"] == 1


def test_upstream_field_fate_treats_select_star_as_passthrough_not_modeling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_contract_staging_schema(project_root)
    facts_dir = project_root / "src" / "nbadb" / "transform" / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    (facts_dir / "__init__.py").write_text("", encoding="utf-8")
    (facts_dir / "fact_foo.py").write_text(
        """
from nbadb.transform.base import make_passthrough

FactFooTransformer = make_passthrough("fact_foo", "stg_foo")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FOO_ID", "TEAM_ID"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    fate_by_field = {row["field_name"]: row for row in artifacts["upstream_field_fate"]["matrix"]}
    assert fate_by_field["foo_id"]["field_fate"] == "sunk_passthrough"
    assert fate_by_field["team_id"]["field_fate"] == "sunk_passthrough"
    assert artifacts["summary"]["upstream_field_fate"]["modeled_column_count"] == 0
    assert artifacts["summary"]["upstream_field_fate"]["sunk_passthrough_count"] == 2


def test_upstream_field_fate_marks_non_introspectable_transform_usage_unknown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_contract_staging_schema(project_root)
    facts_dir = project_root / "src" / "nbadb" / "transform" / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    (facts_dir / "__init__.py").write_text("", encoding="utf-8")
    (facts_dir / "fact_foo.py").write_text(
        """
from typing import ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer


class FactFooTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_foo"
    depends_on: ClassVar[list[str]] = ["stg_foo"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return staging["stg_foo"].collect()
""".strip()
        + "\n",
        encoding="utf-8",
    )
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="FooEndpoint",
                result_set_index=0,
                result_set_name="PrimarySet",
                expected_columns=("FOO_ID", "TEAM_ID"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    fate_by_field = {row["field_name"]: row for row in artifacts["upstream_field_fate"]["matrix"]}
    assert fate_by_field["foo_id"]["field_fate"] == "model_usage_unknown"
    assert fate_by_field["team_id"]["field_fate"] == "model_usage_unknown"
    assert artifacts["summary"]["upstream_field_fate"]["model_usage_unknown_count"] == 2


def test_sql_column_usage_handles_duckdb_union_all_by_name() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    usage = EndpointCoverageGenerator._sql_column_usage_by_dependency(
        depends_on=["stg_foo", "stg_bar"],
        sql="""
            SELECT foo_id, team_id FROM stg_foo
            UNION ALL BY NAME
            SELECT bar_id, team_id FROM stg_bar
        """,
        semantics="modeled",
    )

    assert usage["stg_foo"]["usage"] == "known"
    assert usage["stg_foo"]["columns"] == {"foo_id", "team_id"}
    assert usage["stg_bar"]["usage"] == "known"
    assert usage["stg_bar"]["columns"] == {"bar_id", "team_id"}


def test_polars_column_usage_extracts_simple_staging_selects() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    tree = ast.parse(
        """
from typing import ClassVar


class DimFooTransformer:
    output_table: ClassVar[str] = "dim_foo"
    depends_on: ClassVar[list[str]] = ["stg_foo"]

    def transform(self, staging):
        foo = staging["stg_foo"]
        return foo.select("foo_id", "team_id").sort("foo_id").collect()
"""
    )
    class_node = next(node for node in tree.body if isinstance(node, ast.ClassDef))

    usage = EndpointCoverageGenerator._polars_column_usage_by_dependency(
        depends_on=["stg_foo"],
        class_node=class_node,
        semantics="modeled",
    )

    assert usage["stg_foo"]["usage"] == "known"
    assert usage["stg_foo"]["columns"] == {"foo_id", "team_id"}


def test_transform_catalog_resolves_spec_listcomp_dependencies(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    facts_dir = tmp_path / "src" / "nbadb" / "transform" / "facts"
    facts_dir.mkdir(parents=True)
    (facts_dir / "fact_detail.py").write_text(
        """
from typing import ClassVar

from nbadb.transform.base import BaseTransformer
from nbadb.transform.facts._comparison_detail import ComparisonDetailSpec


_DETAIL_SPECS: tuple[ComparisonDetailSpec, ...] = (
    ComparisonDetailSpec("stg_foo", labels={"source": "foo"}),
    ComparisonDetailSpec("stg_bar", labels={"source": "bar"}),
)


class FactDetailTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_detail"
    depends_on: ClassVar[list[str]] = [spec.staging_key for spec in _DETAIL_SPECS]

    def transform(self, staging):
        return consolidate_detail_family(
            staging,
            specs=_DETAIL_SPECS,
            output_schema={},
            passthrough_columns=("FOO_ID", "TEAM_ID"),
        )
""".strip()
        + "\n",
        encoding="utf-8",
    )

    output_map, output_tables, output_semantics, column_usage = EndpointCoverageGenerator(
        project_root=tmp_path,
    )._transform_catalog()

    assert output_tables == {"fact_detail"}
    assert output_map["stg_foo"] == {"fact_detail"}
    assert output_map["stg_bar"] == {"fact_detail"}
    assert output_semantics["fact_detail"] == "modeled"
    assert column_usage["stg_foo"]["fact_detail"]["usage"] == "known"
    assert column_usage["stg_foo"]["fact_detail"]["columns"] == {"foo_id", "team_id"}
    assert column_usage["stg_bar"]["fact_detail"]["usage"] == "known"
    assert column_usage["stg_bar"]["fact_detail"]["columns"] == {"foo_id", "team_id"}


def test_field_ownership_override_marks_reviewed_landing_fields_reference_only() -> None:
    from nbadb.core.endpoint_coverage import _field_ownership_override

    status, reason = _field_ownership_override("stg_schedule", "game_status")

    assert status == "compatibility_reference_only"
    assert reason is not None
    assert "preserved in stg_schedule" in reason


def test_upstream_field_fate_applies_field_reference_override_in_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract, NbaApiResultSetContract

    project_root = tmp_path / "project"
    staging_dir = project_root / "src" / "nbadb" / "schemas" / "staging"
    facts_dir = project_root / "src" / "nbadb" / "transform" / "facts"
    staging_dir.mkdir(parents=True, exist_ok=True)
    facts_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "__init__.py").write_text("", encoding="utf-8")
    (facts_dir / "__init__.py").write_text("", encoding="utf-8")
    (staging_dir / "schedule.py").write_text(
        """
class StagingScheduleSchema:
    game_id: str
    game_status: str
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (facts_dir / "fact_schedule.py").write_text(
        """
from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactScheduleTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_schedule"
    depends_on: ClassVar[list[str]] = ["stg_schedule"]
    _SQL: ClassVar[str] = "SELECT game_id FROM stg_schedule"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    contract = NbaApiEndpointContract(
        runtime_class_name="ScheduleLeagueV2",
        module_name="nba_api.stats.endpoints.scheduleleaguev2",
        endpoint_slug="scheduleleaguev2",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(
            NbaApiResultSetContract(
                runtime_class_name="ScheduleLeagueV2",
                result_set_index=0,
                result_set_name="Schedule",
                expected_columns=("GAME_ID", "GAME_STATUS"),
                source="expected_data",
                confidence="high",
            ),
        ),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"ScheduleLeagueV2": contract},
    )

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("schedule", "stg_schedule", "season")],
    ).build_artifacts(
        runtime_endpoint_classes={"ScheduleLeagueV2"},
        runtime_version="contract-runtime",
    )

    fate_by_field = {row["field_name"]: row for row in artifacts["upstream_field_fate"]["matrix"]}
    assert fate_by_field["game_id"]["field_fate"] == "modeled_column"
    assert fate_by_field["game_status"]["field_fate"] == "sink_declared_reference_only"
    assert "preserved in stg_schedule" in fate_by_field["game_status"]["reason"]
    fate_summary = artifacts["summary"]["upstream_field_fate"]
    assert fate_summary["sink_declared_reference_only_count"] == 1
    assert fate_summary["unmodeled_unclassified_count"] == 0


def test_model_ownership_decision_maps_do_not_overlap() -> None:
    from pathlib import Path

    import nbadb.core.endpoint_coverage as endpoint_coverage

    assert endpoint_coverage.__file__ is not None

    def _literal_dict_keys(constant_name: str) -> list[str]:
        source = Path(endpoint_coverage.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if not isinstance(node, ast.AnnAssign):
                continue
            if not isinstance(node.target, ast.Name) or node.target.id != constant_name:
                continue
            if not isinstance(node.value, ast.Dict):
                return []
            return [
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
        return []

    stats_keys = _literal_dict_keys("_MODEL_OWNERSHIP_STATS_ENDPOINTS")
    staging_keys = _literal_dict_keys("_MODEL_OWNERSHIP_STAGING_KEYS")
    assert len(stats_keys) == len(set(stats_keys))
    assert len(staging_keys) == len(set(staging_keys))
    statuses = {"compatibility_reference_only", "excluded"}
    assert {
        decision["status"]
        for decision in endpoint_coverage._MODEL_OWNERSHIP_STATS_ENDPOINTS.values()
    } <= statuses
    assert {
        decision["status"] for decision in endpoint_coverage._MODEL_OWNERSHIP_STAGING_KEYS.values()
    } <= statuses


def test_temporal_coverage_matrix_expands_supported_seasons(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_sample_staging_schemas(project_root)
    monkeypatch.setattr(endpoint_coverage, "season_range", lambda start, end=None: ["2024-25"])

    artifacts = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[
            StagingEntry(
                "foo_endpoint",
                "stg_foo",
                "season",
                season_type_capability="supported",
                supported_season_types=("Regular Season", "Playoffs"),
            )
        ],
    ).build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    matrix = artifacts["temporal_coverage_matrix"]["matrix"]
    assert [row["season_type"] for row in matrix] == ["Regular Season", "Playoffs"]
    assert {row["season"] for row in matrix} == {"2024-25"}
    assert {row["actual_status"] for row in matrix} == {"staged"}
    assert artifacts["summary"]["temporal_coverage"]["required_temporal_missing_count"] == 0


def test_build_artifacts_writes_upstream_contract_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    )
    paths = generator.write(
        output_dir=tmp_path / "artifacts",
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    assert "upstream_contracts" in paths
    assert "nba_api_upstream_contract_bundle" in paths
    assert "nba_api_bronze_contracts" in paths
    assert "endpoint_analysis_doc_contracts" in paths
    assert "endpoint_analysis_doc_diff" in paths
    assert "endpoint_analysis_doc_upstream_contract_diff" in paths
    assert "upstream_contract_diff" in paths
    assert "upstream_field_fate" in paths
    assert "temporal_coverage_matrix" in paths
    contracts_payload = json.loads(paths["upstream_contracts"].read_text(encoding="utf-8"))
    bundle_payload = json.loads(
        paths["nba_api_upstream_contract_bundle"].read_text(encoding="utf-8")
    )
    bronze_payload = json.loads(paths["nba_api_bronze_contracts"].read_text(encoding="utf-8"))
    docs_payload = json.loads(paths["endpoint_analysis_doc_contracts"].read_text(encoding="utf-8"))
    docs_diff_payload = json.loads(paths["endpoint_analysis_doc_diff"].read_text(encoding="utf-8"))
    docs_upstream_diff_payload = json.loads(
        paths["endpoint_analysis_doc_upstream_contract_diff"].read_text(encoding="utf-8")
    )
    diff_payload = json.loads(paths["upstream_contract_diff"].read_text(encoding="utf-8"))
    fate_payload = json.loads(paths["upstream_field_fate"].read_text(encoding="utf-8"))
    temporal_payload = json.loads(paths["temporal_coverage_matrix"].read_text(encoding="utf-8"))
    assert contracts_payload["contracts"][0]["endpoint_name"] == "foo_endpoint"
    assert bundle_payload["enabled"] is False
    assert len(bundle_payload["bundle_digest"]) == 64
    assert bronze_payload["enabled"] is False
    assert bronze_payload["summary"]["table_count"] == 0
    assert docs_payload["contracts"] == []
    assert docs_diff_payload["summary"]["enabled"] is False
    assert docs_upstream_diff_payload["summary"]["endpoint_contract_count"] == 0
    assert diff_payload["summary"]["endpoint_contract_count"] == 1
    assert fate_payload["summary"]["endpoint_contract_count"] == 1
    assert "matrix" in temporal_payload


def test_build_artifacts_writes_enabled_upstream_contract_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nbadb.core.endpoint_coverage as endpoint_coverage
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
    from nbadb.core.nba_api_contract import NbaApiEndpointContract

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    docs_root = tmp_path / "nba-api-upstream"
    docs_dir = docs_root / "docs" / "nba_api" / "stats" / "endpoints"
    docs_dir.mkdir(parents=True)
    (docs_dir / "fooendpoint.md").write_text(
        """# FooEndpoint

## JSON
```json
{
  "data_sets": {},
  "endpoint": "FooEndpoint",
  "nullable_parameters": [],
  "parameters": [],
  "required_parameters": [],
  "status": "success"
}
```
""",
        encoding="utf-8",
    )
    tools_dir = docs_root / "tools" / "stats"
    tools_dir.mkdir(parents=True)
    (tools_dir / "mapping.py").write_text("endpoint_list = []\n", encoding="utf-8")
    contract = NbaApiEndpointContract(
        runtime_class_name="FooEndpoint",
        module_name="nba_api.stats.endpoints.fooendpoint",
        endpoint_slug="fooendpoint",
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=(),
    )
    monkeypatch.setattr(
        endpoint_coverage,
        "discover_runtime_endpoint_contracts",
        lambda: {"FooEndpoint": contract},
    )

    paths = EndpointCoverageGenerator(
        project_root=project_root,
        endpoint_analysis_docs_root=docs_root,
        staging_entries=[StagingEntry("foo_endpoint", "stg_foo", "season")],
    ).write(
        output_dir=tmp_path / "artifacts",
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="contract-runtime",
    )

    bundle_payload = json.loads(
        paths["nba_api_upstream_contract_bundle"].read_text(encoding="utf-8")
    )
    bronze_payload = json.loads(paths["nba_api_bronze_contracts"].read_text(encoding="utf-8"))
    summary_payload = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert bundle_payload["enabled"] is True
    assert bundle_payload["source_inventory"]["parsed_stats_contract_count"] == 1
    assert bundle_payload["source_inventory"]["tools_python_file_count"] == 1
    assert bundle_payload["stats_contracts"][0]["runtime_class_name"] == "FooEndpoint"
    assert len(bundle_payload["source_file_digests"]["tools"]["tools/stats/mapping.py"]) == 64
    assert (
        summary_payload["endpoint_analysis_docs"]["source_inventory"]
        == (bundle_payload["source_inventory"])
    )
    assert (
        summary_payload["endpoint_analysis_docs"]["bundle_digest"]
        == (bundle_payload["bundle_digest"])
    )
    assert (
        summary_payload["endpoint_analysis_docs"]["bronze_contracts"] == (bronze_payload["summary"])
    )
    assert (
        summary_payload["endpoint_analysis_docs"]["bronze_contract_digest"]
        == (bronze_payload["bronze_contract_digest"])
    )


def test_build_artifacts_includes_strict_support_contract_summary(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_static_and_live_extractors(project_root)
    _write_sample_transforms(project_root)
    _write_sample_star_schemas(project_root)
    staging_entries = [
        StagingEntry(
            "foo_endpoint",
            "stg_foo",
            "season",
            season_type_capability="supported",
            supported_season_types=("Regular Season", "Playoffs"),
        ),
        StagingEntry("static_players", "stg_static_players", "static"),
    ]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_static_surfaces={"players", "teams"},
        runtime_live_endpoint_classes={"BoxScore", "ScoreBoard"},
        runtime_version="strict-runtime",
    )

    support_rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}
    assert support_rows["foo_endpoint"]["execution_semantics"] == "historical_backfill"
    assert support_rows["foo_endpoint"]["param_patterns"] == ["season"]
    assert support_rows["foo_endpoint"]["contract_status"] == "gap"
    assert support_rows["foo_endpoint"]["season_type_contract_status"] == "supported"
    assert support_rows["foo_endpoint"]["earliest_supported_season"] == 1946
    assert support_rows["foo_endpoint"]["contract_gaps"] == ["input_schema_missing"]
    assert support_rows["static_players"]["execution_semantics"] == "reference_snapshot"
    assert support_rows["static_players"]["contract_status"] == "gap"
    assert "transform_contract_missing" in support_rows["static_players"]["contract_gaps"]
    assert support_rows["live_box_score"]["execution_semantics"] == "live_snapshot"
    assert support_rows["live_box_score"]["contract_status"] == "gap"
    assert "snapshot_staging_missing" in support_rows["live_box_score"]["contract_gaps"]
    assert "snapshot_transform_missing" in support_rows["live_box_score"]["contract_gaps"]

    support_summary = artifacts["support_summary"]
    assert support_summary["complete_endpoint_count"] == 0
    assert support_summary["partial_endpoint_count"] == 0
    assert support_summary["gap_endpoint_count"] >= 3
    assert support_summary["execution_semantics_breakdown"] == {
        "historical_backfill": 3,
        "live_snapshot": 2,
        "reference_snapshot": 2,
    }
    assert support_summary["season_type_contract_breakdown"] == {
        "not_applicable": 4,
        "supported": 1,
        "untracked": 2,
    }
    assert support_summary["season_type_contract_open_count"] == 2
    assert support_summary["season_type_contract_untracked_count"] == 2
    assert "staging_only" not in support_summary["gap_breakdown"]


def test_support_matrix_merges_runtime_and_staging_param_patterns(tmp_path: Path) -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    project_root = tmp_path / "project"
    _write_sample_extractors(project_root)
    _write_sample_transforms(project_root)
    _write_sample_star_schemas(project_root)
    staging_entries = [
        StagingEntry("foo_endpoint", "stg_foo", "season"),
        StagingEntry("foo_endpoint", "stg_foo_player", "player_season"),
    ]

    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=staging_entries,
    )
    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={"FooEndpoint"},
        runtime_version="strict-runtime",
    )

    support_rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}

    assert support_rows["foo_endpoint"]["param_patterns"] == ["player_season", "season"]
    assert {
        (window["staging_key"], window["param_pattern"])
        for window in support_rows["foo_endpoint"]["support_windows"]
    } == {
        ("stg_foo", "season"),
        ("stg_foo_player", "player_season"),
    }


def test_extraction_summary_ready_for_full_backfill_requires_closed_season_type_contract() -> None:
    from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

    extraction = EndpointCoverageGenerator._build_extraction_matrix(
        support_matrix=[
            {
                "endpoint_name": "foo_endpoint",
                "source_kind": "stats",
                "execution_semantics": "historical_backfill",
                "season_type_contract_status": "untracked",
                "season_type_value_gaps": [],
                "coverage_statuses": ["covered"],
                "staging_keys": ["stg_foo"],
                "input_schema_missing_staging_keys": [],
                "param_patterns": ["season"],
                "declared_supported_season_types": [],
                "earliest_supported_season": "2024-25",
                "support_windows": [],
            }
        ]
    )

    assert extraction["summary"]["partial_endpoint_count"] == 1
    assert extraction["summary"]["season_type_contract_open_count"] == 1
    assert extraction["summary"]["ready_for_full_backfill"] is False
