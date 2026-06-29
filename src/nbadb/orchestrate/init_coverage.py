from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nbadb.orchestrate.discovery import GameDiscoveryResult, PlayerTeamSeasonDiscoveryResult


class InitDiscoveryCoverageError(RuntimeError):
    """Raised when full-init discovery cannot prove requested coverage."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True, slots=True)
class InitDiscoveryCoverageReport:
    errors: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise InitDiscoveryCoverageError(self.errors)


def validate_game_discovery(result: GameDiscoveryResult) -> list[str]:
    if result.is_complete:
        return []
    missing = sorted(result.requested_combos - result.covered_combos)
    return [f"incomplete game discovery; missing season/season_type combos: {missing}"]


def validate_player_team_discovery(result: PlayerTeamSeasonDiscoveryResult) -> list[str]:
    if result.is_complete:
        return []
    missing = sorted(result.requested_pairs - result.covered_pairs)
    return [f"incomplete player-team-season discovery; missing pairs: {missing}"]


def validate_required_ids(label: str, values: list[int]) -> list[str]:
    return [] if values else [f"{label} discovery returned no ids"]


def build_init_discovery_report(
    *,
    game_result: GameDiscoveryResult,
    player_ids: list[int],
    team_ids: list[int],
    current_team_ids: list[int],
    player_team_result: PlayerTeamSeasonDiscoveryResult,
) -> InitDiscoveryCoverageReport:
    errors: list[str] = []
    errors.extend(validate_game_discovery(game_result))
    errors.extend(validate_required_ids("player", player_ids))
    errors.extend(validate_required_ids("team", team_ids))
    errors.extend(validate_required_ids("current-team", current_team_ids))
    errors.extend(validate_player_team_discovery(player_team_result))
    return InitDiscoveryCoverageReport(errors=errors)
