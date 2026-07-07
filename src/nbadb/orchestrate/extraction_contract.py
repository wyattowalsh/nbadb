from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type FinalLaneOutcome = Literal[
    "complete",
    "needs_resume",
    "contract_blocked",
    "pipeline_failure",
]

type ExtractionExclusionClass = Literal[
    "permanently_unsupported",
    "upstream_bug_blocked",
    "contract_not_modeled_yet",
    "intentionally_deferred",
]

type EndpointSupportRuleClassification = Literal["contract_blocked"]


@dataclass(frozen=True, slots=True)
class ExtractionExclusion:
    endpoint_name: str
    classification: ExtractionExclusionClass
    reason: str
    owner: str
    revalidation_path: str
    scope: str = "full_extraction"

    def to_dict(self) -> dict[str, str]:
        return {
            "endpoint_name": self.endpoint_name,
            "classification": self.classification,
            "reason": self.reason,
            "owner": self.owner,
            "revalidation_path": self.revalidation_path,
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class EndpointSupportRule:
    endpoint_name: str
    pattern: str | None
    classification: EndpointSupportRuleClassification
    reason: str
    evidence: str
    revalidation_command: str
    season_start: int | None = None
    season_end: int | None = None

    def matches(
        self,
        *,
        endpoint_name: str,
        patterns: tuple[str, ...],
        season_start: int | None,
        season_end: int | None,
    ) -> bool:
        if endpoint_name != self.endpoint_name:
            return False
        if self.pattern is not None and self.pattern not in patterns:
            return False
        if self.season_start is None and self.season_end is None:
            return True
        if season_start is None or season_end is None:
            return False
        rule_start = self.season_start if self.season_start is not None else season_start
        rule_end = self.season_end if self.season_end is not None else season_end
        return rule_start <= season_start and season_end <= rule_end

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "endpoint_name": self.endpoint_name,
            "pattern": self.pattern,
            "classification": self.classification,
            "reason": self.reason,
            "evidence": self.evidence,
            "revalidation_command": self.revalidation_command,
            "season_start": self.season_start,
            "season_end": self.season_end,
        }


FULL_EXTRACTION_EXCLUSIONS: tuple[ExtractionExclusion, ...] = (
    ExtractionExclusion(
        endpoint_name="team_historical_leaders",
        classification="upstream_bug_blocked",
        reason=(
            "The live TeamHistoricalLeaders endpoint currently returns invalid JSON for "
            "valid franchise IDs, so full historical extraction is blocked upstream."
        ),
        owner="extract",
        revalidation_path=(
            "Revalidate after nba_api or upstream NBA Stats fixes the response shape for "
            "current franchise IDs."
        ),
    ),
)

FULL_EXTRACTION_EXCLUSIONS_BY_ENDPOINT: dict[str, ExtractionExclusion] = {
    exclusion.endpoint_name: exclusion for exclusion in FULL_EXTRACTION_EXCLUSIONS
}

EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS: tuple[str, ...] = (
    "common_playoff_series",
    "draft_board",
    "draft_combine_drill_results",
    "draft_combine_non_stationary_shooting",
    "draft_combine_player_anthro",
    "draft_combine_spot_shooting",
    "draft_combine_stats",
    "draft_history",
    "ist_standings",
    "league_season_matchups",
    "player_career_by_college",
    "player_index",
    "player_streak_finder",
    "playoff_picture",
    "schedule",
    "schedule_int",
    "shot_chart_league_wide",
    "team_game_streak_finder",
)

EARLY_1946_1949_SEASON_CONTRACT_BLOCKED_ENDPOINTS: tuple[str, ...] = (
    "dunk_score_leaders",
    "fantasy_widget",
    "gravity_leaders",
    "homepage_leaders",
    "homepage_v2",
    "leaders_tiles",
    "league_dash_lineups",
    "league_dash_opp_pt_shot",
    "league_dash_player_bio",
    "league_dash_player_clutch",
    "league_dash_player_pt_shot",
    "league_dash_player_shot_locations",
    "league_dash_player_stats",
    "league_dash_pt_defend",
    "league_dash_pt_stats",
    "league_dash_pt_team_defend",
    "league_dash_team_clutch",
    "league_dash_team_pt_shot",
    "league_dash_team_shot_locations",
    "league_dash_team_stats",
    "league_hustle_player",
    "league_hustle_team",
    "league_lineup_viz",
    "league_standings",
    "matchups_rollup",
    "player_estimated_metrics",
)

SEASON_ENDPOINTS_SUPPORTED_FROM_1997: tuple[str, ...] = (
    "common_playoff_series",
    "draft_board",
    "draft_combine_drill_results",
    "draft_combine_non_stationary_shooting",
    "draft_combine_player_anthro",
    "draft_combine_spot_shooting",
    "draft_combine_stats",
    "draft_history",
    "league_season_matchups",
    "player_index",
    "schedule",
    "shot_chart_league_wide",
)

SEASON_ENDPOINTS_UNSUPPORTED_AFTER_1969: tuple[str, ...] = (
    "player_career_by_college",
    "team_game_streak_finder",
)

SHOT_CHART_PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_1996: tuple[str, ...] = ("shot_chart_detail",)

PLAYER_DASHBOARD_PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_1996: tuple[str, ...] = (
    "player_dashboard_clutch",
    "player_dashboard_game_splits",
    "player_dashboard_general_splits",
    "player_dashboard_last_n_games",
    "player_dashboard_shooting_splits",
    "player_dashboard_team_performance",
    "player_dashboard_year_over_year",
    "player_dash_game_splits",
    "player_dash_general_splits",
    "player_dash_last_n_games",
    "player_dash_shooting_splits",
    "player_dash_team_perf",
    "player_dash_yoy",
    "player_streak_finder",
)

PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_1996: tuple[str, ...] = (
    *SHOT_CHART_PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_1996,
    *PLAYER_DASHBOARD_PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_1996,
)

PLAYER_TRACKING_PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_2013: tuple[str, ...] = (
    "player_dash_pt_pass",
    "player_dash_pt_reb",
    "player_dash_pt_shot_defend",
    "player_dash_pt_shots",
)

PLAYER_SEASON_FULL_EXTRACTION_UNSUPPORTED_ENDPOINTS: tuple[str, ...] = ("player_next_games",)


def _early_season_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="season",
        classification="contract_blocked",
        reason=(
            "NBA Stats returned no usable season-level result sets for "
            "1946-47 through 1960-61 in full extraction; throwing endpoints "
            "exhausted all retries and the lane persisted zero rows."
        ),
        evidence=(
            "GitHub Actions full-extraction runs 28414935130 and 28416663358 "
            "lane historical-season-no-season-type-1946-1948; job 84201081366 "
            "reported 48 TransientError failures across 16 endpoints and zero "
            "rows for the 18-endpoint lane. Run 28417686426 job 84204162837 "
            "reproduced the same 48-failure zero-row pattern for "
            "historical-season-no-season-type-1949-1951. Run 28418322335 "
            "job 84206096326 reproduced the same 48-failure zero-row pattern "
            "for historical-season-no-season-type-1952-1954. Run 28418877674 "
            "job 84207757226 reproduced the same 48-failure zero-row pattern "
            "for historical-season-no-season-type-1955-1957. Run 28419517277 "
            "job 84209629787 reproduced the same 48-failure zero-row pattern "
            "for historical-season-no-season-type-1958-1960."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern season "
            f"--endpoint {endpoint_name} --seasons 1946:1960 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1946,
        season_end=1960,
    )


def _early_1946_1949_season_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="season",
        classification="contract_blocked",
        reason=(
            "NBA Stats returned no usable season-level result sets for "
            "1946-47 through 1949-50 in full extraction; this endpoint "
            "exhausted retries and persisted zero rows in its isolated lane."
        ),
        evidence=(
            "GitHub Actions full-extraction run 28710521686, chain "
            "28687179975, iteration 3, reported 26 extract lane failures for "
            "1946-1949 season endpoints. Each failed lane persisted zero rows, "
            "ended as extract-error, and reported TransientError failures with "
            "zero_row_reason=contract_gap. The failed lanes included "
            "dunk_score_leaders, fantasy_widget, gravity_leaders, homepage "
            "leaders/v2, league dash player/team tracking families, hustle, "
            "lineup, standings, matchups_rollup, and player_estimated_metrics."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern season "
            f"--endpoint {endpoint_name} --seasons 1946:1949 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1946,
        season_end=1949,
    )


def _early_1960s_season_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="season",
        classification="contract_blocked",
        reason=(
            "NBA Stats returned no usable season-level result sets for "
            "1961-62 through 1963-64 in current full extraction; throwing "
            "endpoints exhausted all retries and the lane persisted zero rows."
        ),
        evidence=(
            "GitHub Actions full-extraction run 28682995009 job 85070250088 "
            "reported 48 TransientError failures across 16 endpoints, 75 "
            "planned calls, zero rows persisted, and zero_row_reason=contract_gap "
            "for lane historical-season-no-season-type-1961-1963. The lane "
            "metadata artifact 8074754457 and DuckDB artifact 8074754314 were "
            "uploaded. Adjacent run 28682995009 lanes historical-season-no-season-"
            "type-1970-1972 and historical-season-no-season-type-1973-1975 "
            "persisted 126 and 129 rows respectively, so this support rule is "
            "bounded to 1961-1963."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern season "
            f"--endpoint {endpoint_name} --seasons 1961:1963 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1961,
        season_end=1963,
    )


def _mid_1960s_season_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="season",
        classification="contract_blocked",
        reason=(
            "NBA Stats returned no usable season-level result sets for "
            "1964-65 through 1966-67 in full extraction; throwing endpoints "
            "exhausted all retries and the lane persisted zero rows. This "
            "window remains a separate support rule because each 1960s band "
            "has independent full-extraction evidence."
        ),
        evidence=(
            "GitHub Actions full-extraction run 28420152202 job 84211483989 "
            "reported 48 TransientError failures across 16 endpoints and zero "
            "rows for lane historical-season-no-season-type-1964-1966. Run "
            "28682995009 later showed the same zero-row 48-failure pattern for "
            "historical-season-no-season-type-1961-1963 while adjacent "
            "1970-1975 lanes persisted rows, so the 1964-1966 gap remains "
            "separately bounded."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern season "
            f"--endpoint {endpoint_name} --seasons 1964:1966 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1964,
        season_end=1966,
    )


def _late_1960s_season_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="season",
        classification="contract_blocked",
        reason=(
            "NBA Stats returned no usable season-level result sets for "
            "1967-68 through 1969-70 in full extraction; throwing endpoints "
            "exhausted all retries and the lane persisted zero rows. This "
            "window remains a separate support rule because each 1960s band "
            "has independent full-extraction evidence."
        ),
        evidence=(
            "GitHub Actions full-extraction run 28421455147 job 84215408055 "
            "reported 48 TransientError failures across 16 endpoints and zero "
            "rows for lane historical-season-no-season-type-1967-1969. The "
            "lane metadata artifact had digest "
            "sha256:46d446716d9edf455c3ed21e92a12d3f9ba2d68c21bfdf9137826b13c3cf7c6e, "
            "and the lane DuckDB artifact had digest "
            "sha256:a7b210be029ae6ad59563b982d04f8c8eac0b48543383a968cfc23aa821ecc90. "
            "Run 28682995009 later showed the same zero-row 48-failure pattern "
            "for historical-season-no-season-type-1961-1963 while adjacent "
            "1970-1975 lanes persisted rows, so the 1967-1969 gap remains "
            "separately bounded."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern season "
            f"--endpoint {endpoint_name} --seasons 1967:1969 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1967,
        season_end=1969,
    )


def _post_1969_pre_1997_season_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="season",
        classification="contract_blocked",
        reason=(
            "NBA Stats season-level extraction returned no usable result sets "
            "for this endpoint from 1970-71 through 1996-97 in full extraction, "
            "while local current-runtime probes show the endpoint is callable "
            "from the 1997-98 season."
        ),
        evidence=(
            "GitHub Actions full-extraction runs 28684723560 and 28685994721 "
            "reported repeated TransientError failures for this endpoint in "
            "historical-season-no-season-type lanes covering 1970-1972 through "
            "1994-1996, while playoff_picture in the same lanes persisted rows. "
            "A 2026-07-03 local probe against nba_api 1.11.4 verified callable "
            "1997-98 responses for this endpoint."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern season "
            f"--endpoint {endpoint_name} --seasons 1970:1996 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1970,
        season_end=1996,
    )


def _post_1969_pre_2000_schedule_int_contract_gap() -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name="schedule_int",
        pattern="season",
        classification="contract_blocked",
        reason=(
            "NBA Stats ScheduleLeagueV2Int season extraction failed for "
            "1970-71 through 1996-97 in full extraction and fails local "
            "1997-98 probing, while 2000-01 returns a usable schedule payload."
        ),
        evidence=(
            "GitHub Actions full-extraction runs 28684723560 and 28685994721 "
            "reported repeated schedule_int TransientError failures in "
            "historical-season-no-season-type lanes covering 1970-1972 through "
            "1994-1996. A 2026-07-03 local probe against nba_api 1.11.4 returned "
            "IndexError for 1997-98 and a 1,375-row multi-frame payload for "
            "2000-01."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern season "
            "--endpoint schedule_int --seasons 1970:1999 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1970,
        season_end=1999,
    )


def _post_1969_pre_2021_ist_standings_contract_gap() -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name="ist_standings",
        pattern="season",
        classification="contract_blocked",
        reason=(
            "NBA Stats IST standings are unavailable for pre-2021 seasons in "
            "the season backfill contract; legacy seasons return unusable JSON "
            "responses instead of empty result sets."
        ),
        evidence=(
            "GitHub Actions full-extraction runs 28684723560 and 28685994721 "
            "reported repeated ist_standings TransientError failures in "
            "historical-season-no-season-type lanes covering 1970-1972 through "
            "1994-1996. A 2026-07-03 local probe against nba_api 1.11.4 returned "
            "JSONDecodeError for 1997-98 through 2016-17 and a handled empty "
            "frame for 2021-22."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern season "
            "--endpoint ist_standings --seasons 1970:2020 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1970,
        season_end=2020,
    )


def _post_1969_unscoped_season_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="season",
        classification="contract_blocked",
        reason=(
            "This endpoint is not usable as an unscoped season-wide full-"
            "extraction lane after 1969-70; current-runtime probes still fail "
            "without the endpoint-specific filter context the NBA Stats API "
            "expects."
        ),
        evidence=(
            "GitHub Actions full-extraction runs 28684723560 and 28685994721 "
            "reported repeated TransientError failures for this endpoint in "
            "historical-season-no-season-type lanes covering 1970-1972 through "
            "1994-1996. A 2026-07-03 local probe against nba_api 1.11.4 found "
            "no supported candidate season from 1997-98 through 2024-25 for "
            "the unscoped season backfill call."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern season "
            f"--endpoint {endpoint_name} --seasons 1970:2025 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1970,
        season_end=None,
    )


def _pre_1996_player_season_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="player_season",
        classification="contract_blocked",
        reason=(
            "NBA Stats player-season shot-chart extraction returned no usable "
            "historical result sets before the 1996-97 season; modern seasons "
            "return the documented ShotChartDetail result-set shape."
        ),
        evidence=(
            "GitHub Actions full-extraction run 28864855855 reported "
            "pipeline_failure for all 1946-47 shot_chart_detail player-season "
            "season-type split lanes: extract_exit_code=124, zero rows persisted, "
            "161 running calls, and zero_row_reason=zero_progress_timeout. A "
            "2026-07-07 local runtime probe returned [0, 0] rows for player "
            "76007 in 1946-47, [0, 20] rows for player 2544 in 1996-97, and "
            "[1270, 20] rows for player 2544 in 2024-25."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose "
            "--pattern player_season "
            f"--endpoint {endpoint_name} --seasons 1946:1995 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1946,
        season_end=1995,
    )


def _pre_1996_player_dashboard_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="player_season",
        classification="contract_blocked",
        reason=(
            "NBA Stats player dashboard and player streak result sets return "
            "no usable historical player-season payloads before 1996-97; the "
            "same endpoints return normal result-set shapes for 1996-97 and "
            "current seasons."
        ),
        evidence=(
            "GitHub Actions full-extraction run 28867994300 reported "
            "pipeline_failure for all 1946-47 player dashboard/streak "
            "player-season lanes: extract_exit_code=124. Each lane DuckDB "
            "artifact contained 161 _extraction_journal rows still marked "
            "running, zero rows extracted, and zero staging chunks. A "
            "2026-07-07 local runtime probe with known active players returned "
            "all-zero frames for 1946-47 player 76007 and 1970-71 player "
            "76003, then nonzero frames for 1996-97 player 893 and 2024-25 "
            "player 2544 across player_dash_game_splits, "
            "player_dash_general_splits, player_dash_last_n_games, "
            "player_dash_shooting_splits, player_dash_team_perf, "
            "player_dash_yoy, player_dashboard_clutch, and "
            "player_streak_finder."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose "
            "--pattern player_season "
            f"--endpoint {endpoint_name} --seasons 1946:1995 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1946,
        season_end=1995,
    )


def _pre_2013_player_tracking_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="player_season",
        classification="contract_blocked",
        reason=(
            "NBA Stats PlayerDashPt tracking endpoints return no usable "
            "player-season tracking payloads before 2013-14; tracking "
            "payloads are available for 2013-14 and current seasons when "
            "queried with team_id=0."
        ),
        evidence=(
            "A 2026-07-07 local runtime probe against nba_api returned "
            "all-zero frames for 1946-47 player 76007 and 1996-97 player 893, "
            "then nonzero 2013-14 and 2024-25 frames for player 2544 across "
            "player_dash_pt_pass, player_dash_pt_reb, player_dash_pt_shots, "
            "and player_dash_pt_shot_defend when called with team_id=0. The "
            "same probe also found the local extractors needed to supply the "
            "nba_api-required team_id parameter."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose "
            "--pattern player_season "
            f"--endpoint {endpoint_name} --seasons 1946:2012 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1946,
        season_end=2012,
    )


def _player_next_games_historical_contract_gap() -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name="player_next_games",
        pattern="player_season",
        classification="contract_blocked",
        reason=(
            "PlayerNextNGames is an upcoming-games surface, not a reproducible "
            "historical backfill surface. Full extraction should not fan out "
            "across historical player seasons for an endpoint whose payload is "
            "defined by future schedule context."
        ),
        evidence=(
            "GitHub Actions full-extraction run 28864855855 reported "
            "pipeline_failure for all 1946-47 player_next_games player-season "
            "season-type split lanes: extract_exit_code=124, zero rows persisted, "
            "161 running calls, and zero_row_reason=zero_progress_timeout. A "
            "2026-07-07 local runtime probe returned zero rows for player 76007 "
            "in 1946-47 and zero rows for player 2544 in 2024-25, matching the "
            "endpoint's upcoming-games semantics rather than historical fact "
            "coverage."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose "
            "--pattern player_season --endpoint player_next_games "
            "--seasons 2024:2025 --summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1946,
        season_end=None,
    )


FULL_EXTRACTION_SUPPORT_RULES: tuple[EndpointSupportRule, ...] = (
    *(
        _early_1946_1949_season_contract_gap(endpoint_name)
        for endpoint_name in EARLY_1946_1949_SEASON_CONTRACT_BLOCKED_ENDPOINTS
    ),
    *(
        _early_season_contract_gap(endpoint_name)
        for endpoint_name in EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS
    ),
    *(
        _early_1960s_season_contract_gap(endpoint_name)
        for endpoint_name in EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS
    ),
    *(
        _mid_1960s_season_contract_gap(endpoint_name)
        for endpoint_name in EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS
    ),
    *(
        _late_1960s_season_contract_gap(endpoint_name)
        for endpoint_name in EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS
    ),
    *(
        _post_1969_pre_1997_season_contract_gap(endpoint_name)
        for endpoint_name in SEASON_ENDPOINTS_SUPPORTED_FROM_1997
    ),
    _post_1969_pre_2000_schedule_int_contract_gap(),
    _post_1969_pre_2021_ist_standings_contract_gap(),
    *(
        _post_1969_unscoped_season_contract_gap(endpoint_name)
        for endpoint_name in SEASON_ENDPOINTS_UNSUPPORTED_AFTER_1969
    ),
    *(
        _pre_1996_player_season_contract_gap(endpoint_name)
        for endpoint_name in SHOT_CHART_PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_1996
    ),
    *(
        _pre_1996_player_dashboard_contract_gap(endpoint_name)
        for endpoint_name in PLAYER_DASHBOARD_PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_1996
    ),
    *(
        _pre_2013_player_tracking_contract_gap(endpoint_name)
        for endpoint_name in PLAYER_TRACKING_PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_2013
    ),
    _player_next_games_historical_contract_gap(),
    EndpointSupportRule(
        endpoint_name="win_probability",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA win probability result sets returned no usable data for 1946-47 "
            "game ids in full extraction; the lane exhausted game calls and "
            "persisted zero rows."
        ),
        evidence=(
            "GitHub Actions full-extraction run 28422481029 job 84218364528 "
            "reported 350 win_probability failures and zero persisted rows for "
            "lane historical-game-win-probability-no-season-type-1946-1946. "
            "The lane metadata artifact had digest "
            "sha256:d0062fb92539fc19ac678208f6414acd28d958ca76ddc4c6e5ed020d3c0d51e0, "
            "and the lane DuckDB artifact had digest "
            "sha256:580ca7bed7c4ecc9a298f66211288476109e28952c27cdc4aa587ba2f7861e37."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern game "
            "--endpoint win_probability --seasons 1946:1946 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1946,
        season_end=1946,
    ),
    EndpointSupportRule(
        endpoint_name="win_probability",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA win probability result sets returned no usable data for "
            "1949-50 and 1950-51 game ids in full extraction; both lanes "
            "exhausted game calls and persisted zero rows. Adjacent 1947-48 "
            "and 1948-49 lanes completed successfully, so this gap is "
            "intentionally non-contiguous."
        ),
        evidence=(
            "GitHub Actions full-extraction run 28429968833 jobs 84242174237 "
            "and 84242176146 reported 593 and 381 win_probability failures, "
            "respectively, with zero persisted rows for lanes "
            "historical-game-win-probability-no-season-type-1949-1949 and "
            "historical-game-win-probability-no-season-type-1950-1950. "
            "The 1949 lane metadata and DuckDB artifact digests were "
            "sha256:8041baf9aa649787841db517e3106cbb8446a55589f604fa6b9bc3ed25cc83cc "
            "and "
            "sha256:4f820dcd261d9293536805ea3bb9d8f3bd531f6dad4dfaa8ac0cd6773cde2353. "
            "The 1950 lane metadata and DuckDB artifact digests were "
            "sha256:c9f8a3785b31b64a6b9814b3638d6cf86bc4dba1d2c027d0ec1deed4849ff20a "
            "and "
            "sha256:75bf342282ee6b53ef3ed44a4700df615604be7c6845d6d7f9ffc779368e2a94."
        ),
        revalidation_command=(
            "uv run nbadb backfill run --extract-only --verbose --pattern game "
            "--endpoint win_probability --seasons 1949:1950 "
            "--summary-path artifacts/extraction/extract-summary.json"
        ),
        season_start=1949,
        season_end=1950,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_advanced",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA advanced box score stats are unavailable before the 1996-97 "
            "season; legacy game ids return no usable advanced result sets."
        ),
        evidence="https://www.nba.com/stats/players/boxscores-advanced",
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_advanced "
            "--season-start 1995 --season-end 1996 --dry-run"
        ),
        season_start=1946,
        season_end=1995,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_defensive",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA defensive box score result sets are unavailable for legacy "
            "game ids before the 2017-18 season."
        ),
        evidence=(
            "GitHub Actions full-extraction run 26276583988 lane metadata; "
            "run 26385964741 lanes historical-game-box-score-defensive-no-season-type-"
            "2006-2017-split-2014-2014 and split-2015-2015; run 27196379034 "
            "lane historical-game-box-score-defensive-no-season-type-2016-2019-"
            "split-2016-2016"
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_defensive "
            "--season-start 2016 --season-end 2017 --dry-run"
        ),
        season_start=1946,
        season_end=2016,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_four_factors",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA four-factors box score result sets are unavailable for legacy "
            "game ids before the 1996-97 season."
        ),
        evidence=(
            "GitHub Actions full-extraction run 26276583988 lane metadata; "
            "run 26385964741 lanes historical-game-box-score-four-factors-no-season-type-"
            "1994-2005-split-1994-1994 and split-1995-1995"
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_four_factors "
            "--season-start 1995 --season-end 1996 --dry-run"
        ),
        season_start=1946,
        season_end=1995,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_matchups",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA matchup box score result sets are unavailable for legacy game "
            "ids before the 2016-17 season."
        ),
        evidence=(
            "GitHub Actions full-extraction run 26276583988 lane metadata; "
            "run 26480824507 lanes historical-game-box-score-matchups-no-season-type-"
            "2006-2017-split-2014-2014 and split-2015-2015"
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_matchups "
            "--season-start 2015 --season-end 2016 --dry-run"
        ),
        season_start=1946,
        season_end=2015,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_misc",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA miscellaneous box score result sets are unavailable for legacy "
            "game ids before the 1996-97 season."
        ),
        evidence=(
            "GitHub Actions full-extraction run 26276583988 lane metadata; "
            "run 26480824507 lanes historical-game-box-score-misc-no-season-type-"
            "1994-2005-split-1994-1994 and split-1995-1995"
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_misc "
            "--season-start 1995 --season-end 1996 --dry-run"
        ),
        season_start=1946,
        season_end=1995,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_player_track",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA player-tracking box score result sets are unavailable for legacy "
            "game ids before the 1996-97 season."
        ),
        evidence=(
            "GitHub Actions full-extraction run 26276583988 lane metadata; "
            "run 26480824507 lanes historical-game-box-score-player-track-no-season-type-"
            "1994-2005-split-1994-1994 and split-1995-1995"
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_player_track "
            "--season-start 1995 --season-end 1996 --dry-run"
        ),
        season_start=1946,
        season_end=1995,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_scoring",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA scoring box score result sets are unavailable for legacy game "
            "ids before the 1996-97 season."
        ),
        evidence=(
            "GitHub Actions full-extraction run 26276583988 lane metadata; "
            "run 26480824507 lanes historical-game-box-score-scoring-no-season-type-"
            "1994-2005-split-1994-1994 and split-1995-1995"
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_scoring "
            "--season-start 1995 --season-end 1996 --dry-run"
        ),
        season_start=1946,
        season_end=1995,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_usage",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA usage box score result sets are unavailable for legacy game "
            "ids before the 1994-95 season."
        ),
        evidence=(
            "GitHub Actions full-extraction run 27026599535 lanes "
            "historical-game-box-score-usage-no-season-type-1946-1949 "
            "through historical-game-box-score-usage-no-season-type-1990-1993"
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_usage "
            "--season-start 1993 --season-end 1994 --dry-run"
        ),
        season_start=1946,
        season_end=1993,
    ),
    EndpointSupportRule(
        endpoint_name="scoreboard_v2",
        pattern="date",
        classification="contract_blocked",
        reason=(
            "NBA Stats scoreboard_v2 date extraction returns no usable result "
            "sets for the 1950-51 historical season; every planned date call in "
            "the isolated lane failed with zero rows persisted."
        ),
        evidence=(
            "GitHub Actions full-extraction run 27196379034 lane "
            "historical-date-scoreboard-v2-no-season-type-1950-1953-split-1950-1950"
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns date --endpoints scoreboard_v2 "
            "--season-start 1950 --season-end 1951 --dry-run"
        ),
        season_start=1950,
        season_end=1950,
    ),
    EndpointSupportRule(
        endpoint_name="scoreboard_v2",
        pattern="date",
        classification="contract_blocked",
        reason=(
            "NBA Stats scoreboard_v2 date extraction returns no usable result "
            "sets for the 1954-55 historical season; every discovered date call "
            "in the isolated lane timed out with zero rows persisted."
        ),
        evidence=(
            "GitHub Actions full-extraction run 27449870904 job 81142844798 "
            "lane historical-date-scoreboard-v2-no-season-type-1954-1957-"
            "split-1954-1954; metadata artifact 7607134822 reported 126 "
            "_CircuitBreakerTimeoutError failures and zero rows persisted."
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns date --endpoints scoreboard_v2 "
            "--season-start 1954 --season-end 1955 --dry-run"
        ),
        season_start=1954,
        season_end=1954,
    ),
    EndpointSupportRule(
        endpoint_name="scoreboard_v2",
        pattern="date",
        classification="contract_blocked",
        reason=(
            "NBA Stats scoreboard_v2 date extraction returns no usable result "
            "sets for the 1956-57 historical season; every discovered date call "
            "in the isolated lane timed out with zero rows persisted."
        ),
        evidence=(
            "GitHub Actions full-extraction run 27449870904 job 81142844815 "
            "lane historical-date-scoreboard-v2-no-season-type-1954-1957-"
            "split-1956-1956; metadata artifact 7607238570 reported 124 "
            "_CircuitBreakerTimeoutError failures and zero rows persisted."
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns date --endpoints scoreboard_v2 "
            "--season-start 1956 --season-end 1957 --dry-run"
        ),
        season_start=1956,
        season_end=1956,
    ),
)


def matching_support_rules(
    *,
    endpoint_name: str,
    patterns: tuple[str, ...],
    season_start: int | None,
    season_end: int | None,
    rules: tuple[EndpointSupportRule, ...] | None = None,
) -> tuple[EndpointSupportRule, ...]:
    support_rules = FULL_EXTRACTION_SUPPORT_RULES if rules is None else rules
    return tuple(
        rule
        for rule in support_rules
        if rule.matches(
            endpoint_name=endpoint_name,
            patterns=patterns,
            season_start=season_start,
            season_end=season_end,
        )
    )


def contract_blocking_rules_for_lane(
    *,
    endpoints: tuple[str, ...],
    patterns: tuple[str, ...],
    season_start: int | None,
    season_end: int | None,
    rules: tuple[EndpointSupportRule, ...] | None = None,
) -> tuple[EndpointSupportRule, ...]:
    if not endpoints:
        return ()
    support_rules = FULL_EXTRACTION_SUPPORT_RULES if rules is None else rules
    matches: list[EndpointSupportRule] = []
    for endpoint_name in endpoints:
        endpoint_matches = tuple(
            rule
            for rule in matching_support_rules(
                endpoint_name=endpoint_name,
                patterns=patterns,
                season_start=season_start,
                season_end=season_end,
                rules=support_rules,
            )
            if rule.classification == "contract_blocked"
        )
        if not endpoint_matches:
            return ()
        matches.extend(endpoint_matches)
    return tuple(matches)
