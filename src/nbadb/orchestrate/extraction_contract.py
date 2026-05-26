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

FULL_EXTRACTION_SUPPORT_RULES: tuple[EndpointSupportRule, ...] = (
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
            "game ids before the 2016-17 season."
        ),
        evidence=(
            "GitHub Actions full-extraction run 26276583988 lane metadata; "
            "run 26385964741 lanes historical-game-box-score-defensive-no-season-type-"
            "2006-2017-split-2014-2014 and split-2015-2015"
        ),
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_defensive "
            "--season-start 2015 --season-end 2016 --dry-run"
        ),
        season_start=1946,
        season_end=2015,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_four_factors",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA four-factors box score result sets are unavailable for legacy "
            "game ids before the 1994-95 season."
        ),
        evidence="GitHub Actions full-extraction run 26276583988 lane metadata",
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_four_factors "
            "--season-start 1993 --season-end 1994 --dry-run"
        ),
        season_start=1946,
        season_end=1993,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_matchups",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA matchup box score result sets are unavailable for legacy game "
            "ids before the 2014-15 season."
        ),
        evidence="GitHub Actions full-extraction run 26276583988 lane metadata",
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_matchups "
            "--season-start 2013 --season-end 2014 --dry-run"
        ),
        season_start=1946,
        season_end=2013,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_misc",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA miscellaneous box score result sets are unavailable for legacy "
            "game ids before the 1994-95 season."
        ),
        evidence="GitHub Actions full-extraction run 26276583988 lane metadata",
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_misc "
            "--season-start 1993 --season-end 1994 --dry-run"
        ),
        season_start=1946,
        season_end=1993,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_player_track",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA player-tracking box score result sets are unavailable for legacy "
            "game ids before the 1994-95 season."
        ),
        evidence="GitHub Actions full-extraction run 26276583988 lane metadata",
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_player_track "
            "--season-start 1993 --season-end 1994 --dry-run"
        ),
        season_start=1946,
        season_end=1993,
    ),
    EndpointSupportRule(
        endpoint_name="box_score_scoring",
        pattern="game",
        classification="contract_blocked",
        reason=(
            "NBA scoring box score result sets are unavailable for legacy game "
            "ids before the 1994-95 season."
        ),
        evidence="GitHub Actions full-extraction run 26276583988 lane metadata",
        revalidation_command=(
            "uv run nbadb extract --patterns game --endpoints box_score_scoring "
            "--season-start 1993 --season-end 1994 --dry-run"
        ),
        season_start=1946,
        season_end=1993,
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
