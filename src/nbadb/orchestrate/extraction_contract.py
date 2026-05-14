from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type ExtractionExclusionClass = Literal[
    "permanently_unsupported",
    "upstream_bug_blocked",
    "contract_not_modeled_yet",
    "intentionally_deferred",
]


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
