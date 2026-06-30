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


def _early_season_contract_gap(endpoint_name: str) -> EndpointSupportRule:
    return EndpointSupportRule(
        endpoint_name=endpoint_name,
        pattern="season",
        classification="contract_blocked",
        reason=(
            "NBA Stats returned no usable season-level result sets for "
            "1946-47 through 1951-52 in full extraction; throwing endpoints "
            "exhausted all retries and the lane persisted zero rows."
        ),
        evidence=(
            "GitHub Actions full-extraction runs 28414935130 and 28416663358 "
            "lane historical-season-no-season-type-1946-1948; job 84201081366 "
            "reported 48 TransientError failures across 16 endpoints and zero "
            "rows for the 18-endpoint lane. Run 28417686426 job 84204162837 "
            "reproduced the same 48-failure zero-row pattern for "
            "historical-season-no-season-type-1949-1951."
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns season "
            f"--endpoints {endpoint_name} --season-start 1946 --season-end 1951 --dry-run"
        ),
        season_start=1946,
        season_end=1951,
    )


FULL_EXTRACTION_SUPPORT_RULES: tuple[EndpointSupportRule, ...] = (
    *(
        _early_season_contract_gap(endpoint_name)
        for endpoint_name in EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS
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
