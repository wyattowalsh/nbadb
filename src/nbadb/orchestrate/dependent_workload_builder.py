"""Pure compiler for receipt-bound, post-foundation dependent workloads."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from nbadb.orchestrate.dependent_workload_contract import (
    DependentExecutableUnit,
    DependentScopeDisposition,
    DependentWorkloadBundle,
    DependentWorkloadContractError,
    DependentWorkloadInconclusiveError,
    DependentWorkloadKind,
    FiveVsFiveOccurrence,
    FoundationAuthority,
    FoundationAuthorityKind,
    FoundationInputReceipt,
    PlayerMatchupOccurrence,
    ScopeDispositionRecord,
    SourceRowIdentity,
    TeamPlayerOccurrence,
    WorkloadScope,
    canonical_decimal,
    canonical_sha256,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

_MATCHUP_TABLE = "stg_matchup"
_AWAY_ROTATION_TABLE = "stg_rotation_away"
_HOME_ROTATION_TABLE = "stg_rotation_home"
_GAME_SCOPE_TABLE = "stg_league_game_log"
_REQUIRED_FOUNDATION_TABLES = frozenset(
    {_MATCHUP_TABLE, _AWAY_ROTATION_TABLE, _HOME_ROTATION_TABLE, _GAME_SCOPE_TABLE}
)

_COMPILER_SEMANTICS = {
    "schema_version": 2,
    "matchup_projection": (
        "one BoxScoreMatchupsV3 source row produces only its exact "
        "off_player-to-def_player and off_team-to-def_player directions"
    ),
    "reverse_policy": "never synthesize a reverse directional matchup",
    "join_policy": "never cross join affiliations, rosters, groups, or lineups",
    "lineup_policy": (
        "intersect exact away/home rotation intervals and admit only two positive "
        "teams with five distinct positive non-overlapping players per side"
    ),
    "lineup_direction_policy": (
        "emit both exact team directions for each admitted opposing-five interval; "
        "deduplicate only identical canonical provider parameter keys"
    ),
    "scope_policy": "valid empty is typed zero, invalid complete evidence is blocked",
    "scope_authority": "receipt-bound league game log rows plus exact logical parameters",
    "source_row_policy": (
        "every persisted matchup and away/home rotation row ordinal is consumed exactly "
        "once by a typed observation or an explicit blocked disposition; discovery team "
        "rows retain their exact representative game-scope ordinal"
    ),
    "endpoint_policy": (
        "execute every physical dependent endpoint, including both five-v-five aliases"
    ),
    "inconclusive_policy": "abort the whole compilation",
}
_QUERY_PLAN = (
    "resolve exact season/type/game scopes from receipt-bound stg_league_game_log rows;"
    "project stg_matchup exact off_team_id/off_player_id/def_team_id/def_player_id rows;"
    "partition stg_rotation_away and stg_rotation_home by exact game scope;"
    "prove every persisted matchup/rotation source-row ordinal is consumed exactly once;"
    "intersect adjacent source boundaries without widening or Cartesian expansion;"
    "emit exact away-to-home and home-to-away request directions"
)

DEPENDENT_WORKLOAD_COMPILER_SHA256 = canonical_sha256(_COMPILER_SEMANTICS)
DEPENDENT_WORKLOAD_QUERY_PLAN_SHA256 = canonical_sha256(_QUERY_PLAN)


class FoundationEvidenceState(StrEnum):
    COMPLETE = "complete"
    VALID_EMPTY = "valid_empty"
    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True, order=True)
class FoundationScopeEvidence:
    scope: WorkloadScope
    matchup_state: FoundationEvidenceState
    rotation_state: FoundationEvidenceState
    matchup_reason_code: str = ""
    rotation_reason_code: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.scope, WorkloadScope):
            raise DependentWorkloadContractError("foundation evidence scope is invalid")
        for label, state, reason in (
            ("matchup", self.matchup_state, self.matchup_reason_code),
            ("rotation", self.rotation_state, self.rotation_reason_code),
        ):
            if not isinstance(state, FoundationEvidenceState):
                raise DependentWorkloadContractError(
                    f"foundation {label} evidence state is invalid"
                )
            if state in {FoundationEvidenceState.BLOCKED, FoundationEvidenceState.INCONCLUSIVE}:
                _validate_reason_code(reason, label=label)
            elif reason:
                raise DependentWorkloadContractError(
                    f"foundation {label} reason is allowed only for blocked/inconclusive state"
                )


@dataclass(frozen=True, slots=True, order=True)
class DirectionalMatchupObservation:
    """One exact BoxScoreMatchupsV3 direction; no reverse is implied."""

    scope: WorkloadScope
    off_team_id: int
    off_player_id: int
    def_team_id: int
    def_player_id: int
    source_row: SourceRowIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.scope, WorkloadScope):
            raise DependentWorkloadContractError("directional matchup scope is invalid")
        for field_name in ("off_team_id", "off_player_id", "def_team_id", "def_player_id"):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise DependentWorkloadContractError(f"{field_name} must be a positive integer")
        if self.off_team_id == self.def_team_id:
            raise DependentWorkloadContractError("directional matchup teams must be distinct")
        if self.off_player_id == self.def_player_id:
            raise DependentWorkloadContractError("directional matchup players must be distinct")
        if not isinstance(self.source_row, SourceRowIdentity):
            raise DependentWorkloadContractError("directional matchup source row is invalid")


@dataclass(frozen=True, slots=True, order=True)
class RotationObservation:
    scope: WorkloadScope
    side: str
    team_id: int
    player_id: int
    interval_start: Decimal
    interval_end: Decimal
    source_row: SourceRowIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.scope, WorkloadScope):
            raise DependentWorkloadContractError("rotation scope is invalid")
        if self.side not in {"away", "home"}:
            raise DependentWorkloadContractError("rotation side must be away or home")
        for field_name in ("team_id", "player_id"):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise DependentWorkloadContractError(
                    f"rotation {field_name} must be a positive integer"
                )
        if not isinstance(self.interval_start, Decimal) or not isinstance(
            self.interval_end, Decimal
        ):
            raise DependentWorkloadContractError("rotation interval values must be Decimal")
        if (
            not self.interval_start.is_finite()
            or not self.interval_end.is_finite()
            or self.interval_start < 0
            or self.interval_end <= self.interval_start
        ):
            raise DependentWorkloadContractError("rotation interval must be finite and positive")
        if not isinstance(self.source_row, SourceRowIdentity):
            raise DependentWorkloadContractError("rotation source row is invalid")


def _validate_reason_code(value: str, *, label: str) -> None:
    if (
        not value
        or value.strip() != value
        or not value[0].isalnum()
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value)
    ):
        raise DependentWorkloadContractError(
            f"foundation {label} reason must be a stable reason code"
        )


def _receipt_lookup(
    authority: FoundationAuthority,
) -> dict[str, FoundationInputReceipt]:
    if authority.compiler_implementation_sha256 != DEPENDENT_WORKLOAD_COMPILER_SHA256:
        raise DependentWorkloadContractError("compiler implementation authority does not match")
    if authority.query_plan_sha256 != DEPENDENT_WORKLOAD_QUERY_PLAN_SHA256:
        raise DependentWorkloadContractError("compiler query-plan authority does not match")
    tables = {receipt.table_name for receipt in authority.input_receipts}
    missing = sorted(_REQUIRED_FOUNDATION_TABLES - tables)
    if missing:
        raise DependentWorkloadContractError(
            "foundation receipt inventory is missing required tables: " + ", ".join(missing)
        )
    unexpected = sorted(tables - _REQUIRED_FOUNDATION_TABLES)
    if unexpected:
        raise DependentWorkloadContractError(
            "foundation receipt inventory contains unsupported tables: " + ", ".join(unexpected)
        )
    for receipt in authority.input_receipts:
        expected_kind = (
            FoundationAuthorityKind.DISCOVERY_GENERATION
            if receipt.table_name == _GAME_SCOPE_TABLE
            else FoundationAuthorityKind.STAGING_CHUNK
        )
        if receipt.table_name in _REQUIRED_FOUNDATION_TABLES and (
            receipt.authority_kind is not expected_kind
        ):
            raise DependentWorkloadContractError(
                "foundation receipt authority kind differs from its source table"
            )
    return {receipt.identity_sha256: receipt for receipt in authority.input_receipts}


def _validate_source_row(
    source_row: SourceRowIdentity,
    *,
    receipt_lookup: dict[str, FoundationInputReceipt],
    allowed_tables: frozenset[str],
) -> FoundationInputReceipt:
    receipt = receipt_lookup.get(source_row.input_receipt_sha256)
    if receipt is None:
        raise DependentWorkloadContractError(
            "foundation observation references an unattested input receipt"
        )
    if receipt.table_name not in allowed_tables:
        raise DependentWorkloadContractError(
            "foundation observation references a receipt for the wrong source table"
        )
    if source_row.row_ordinal >= receipt.persisted_row_count:
        raise DependentWorkloadContractError(
            "foundation observation row ordinal is outside its persisted receipt"
        )
    return receipt


def _validate_observations(
    *,
    scope_evidence: tuple[FoundationScopeEvidence, ...],
    matchup_observations: tuple[DirectionalMatchupObservation, ...],
    rotation_observations: tuple[RotationObservation, ...],
    receipt_lookup: dict[str, FoundationInputReceipt],
) -> None:
    scopes = {item.scope for item in scope_evidence}
    source_rows: set[SourceRowIdentity] = set()
    ordinals_by_receipt: dict[str, set[int]] = {receipt_id: set() for receipt_id in receipt_lookup}
    for scope in scopes:
        scope_source = SourceRowIdentity(
            scope.foundation_receipt_sha256,
            scope.foundation_row_ordinal,
        )
        receipt = _validate_source_row(
            scope_source,
            receipt_lookup=receipt_lookup,
            allowed_tables=frozenset({_GAME_SCOPE_TABLE}),
        )
        if dict(receipt.logical_parameters) != {
            "season": scope.season,
            "season_type": scope.season_type,
        }:
            raise DependentWorkloadContractError(
                "foundation scope differs from its discovery receipt parameters"
            )
        if scope_source in source_rows:
            raise DependentWorkloadContractError("foundation scope source rows must be unique")
        source_rows.add(scope_source)
        ordinals_by_receipt[receipt.identity_sha256].add(scope_source.row_ordinal)
    for observation in matchup_observations:
        if observation.scope not in scopes:
            raise DependentWorkloadContractError(
                "directional matchup observation is outside declared scope"
            )
        receipt = _validate_source_row(
            observation.source_row,
            receipt_lookup=receipt_lookup,
            allowed_tables=frozenset({_MATCHUP_TABLE}),
        )
        if dict(receipt.logical_parameters) != {"game_id": observation.scope.game_id}:
            raise DependentWorkloadContractError(
                "directional matchup observation differs from its receipt game scope"
            )
        if observation.source_row in source_rows:
            raise DependentWorkloadContractError(
                "foundation observation source rows must be unique"
            )
        source_rows.add(observation.source_row)
        ordinals_by_receipt[receipt.identity_sha256].add(observation.source_row.row_ordinal)
    for observation in rotation_observations:
        if observation.scope not in scopes:
            raise DependentWorkloadContractError("rotation observation is outside declared scope")
        expected_table = (
            _AWAY_ROTATION_TABLE if observation.side == "away" else _HOME_ROTATION_TABLE
        )
        receipt = _validate_source_row(
            observation.source_row,
            receipt_lookup=receipt_lookup,
            allowed_tables=frozenset({expected_table}),
        )
        if dict(receipt.logical_parameters) != {"game_id": observation.scope.game_id}:
            raise DependentWorkloadContractError(
                "rotation observation differs from its receipt game scope"
            )
        if observation.source_row in source_rows:
            raise DependentWorkloadContractError(
                "foundation observation source rows must be unique"
            )
        source_rows.add(observation.source_row)
        ordinals_by_receipt[receipt.identity_sha256].add(observation.source_row.row_ordinal)

    _validate_exhaustive_receipt_consumption(
        scope_evidence=scope_evidence,
        receipt_lookup=receipt_lookup,
        ordinals_by_receipt=ordinals_by_receipt,
    )


def _validate_exact_receipt_ordinals(
    receipt: FoundationInputReceipt,
    *,
    observed_ordinals: set[int],
) -> None:
    # Every ordinal was already proven nonnegative, unique, and in range. Exact
    # cardinality therefore proves equality with range(persisted_row_count)
    # without allocating a second potentially large ordinal inventory.
    if len(observed_ordinals) != receipt.persisted_row_count:
        raise DependentWorkloadContractError(
            f"foundation {receipt.table_name} receipt rows were not consumed exactly"
        )


def _validate_exhaustive_receipt_consumption(
    *,
    scope_evidence: tuple[FoundationScopeEvidence, ...],
    receipt_lookup: dict[str, FoundationInputReceipt],
    ordinals_by_receipt: dict[str, set[int]],
) -> None:
    evidence_by_game: dict[str, list[FoundationScopeEvidence]] = {}
    for evidence in scope_evidence:
        evidence_by_game.setdefault(evidence.scope.game_id, []).append(evidence)

    receipts_by_game_and_table: dict[tuple[str, str], list[FoundationInputReceipt]] = {}
    for receipt in receipt_lookup.values():
        observed_ordinals = ordinals_by_receipt[receipt.identity_sha256]
        if receipt.table_name == _GAME_SCOPE_TABLE:
            # LeagueGameLog is team-grain: one game commonly has two persisted
            # team rows while WorkloadScope intentionally retains one exact
            # representative ordinal. The compiler can prove every referenced
            # ordinal but cannot manufacture a one-scope-per-team-row mapping.
            if receipt.persisted_row_count and not observed_ordinals:
                raise DependentWorkloadContractError(
                    "nonempty discovery receipt has no representative game scope"
                )
            continue
        parameters = dict(receipt.logical_parameters)
        if set(parameters) != {"game_id"} or not isinstance(parameters["game_id"], str):
            raise DependentWorkloadContractError(
                "staging foundation receipt must bind one exact game scope"
            )
        game_id = parameters["game_id"]
        matches = evidence_by_game.get(game_id, [])
        if len(matches) != 1:
            raise DependentWorkloadContractError(
                "staging foundation receipt game scope is missing or ambiguous"
            )
        receipts_by_game_and_table.setdefault((game_id, receipt.table_name), []).append(receipt)

        state = (
            matches[0].matchup_state
            if receipt.table_name == _MATCHUP_TABLE
            else matches[0].rotation_state
        )
        if state is not FoundationEvidenceState.BLOCKED:
            _validate_exact_receipt_ordinals(
                receipt,
                observed_ordinals=observed_ordinals,
            )

    for evidence in scope_evidence:
        game_id = evidence.scope.game_id
        matchup_count = len(receipts_by_game_and_table.get((game_id, _MATCHUP_TABLE), ()))
        away_count = len(receipts_by_game_and_table.get((game_id, _AWAY_ROTATION_TABLE), ()))
        home_count = len(receipts_by_game_and_table.get((game_id, _HOME_ROTATION_TABLE), ()))
        if matchup_count > 1:
            raise DependentWorkloadContractError(
                "matchup foundation scope has ambiguous persisted receipts"
            )
        if (away_count, home_count) not in {(0, 0), (1, 1)}:
            raise DependentWorkloadContractError(
                "rotation foundation scope lacks its exact paired receipts"
            )
        if (
            evidence.matchup_state
            in {
                FoundationEvidenceState.COMPLETE,
                FoundationEvidenceState.VALID_EMPTY,
            }
            and matchup_count != 1
        ):
            raise DependentWorkloadContractError(
                "complete or valid-empty matchup scope requires one exact receipt"
            )
        if evidence.rotation_state in {
            FoundationEvidenceState.COMPLETE,
            FoundationEvidenceState.VALID_EMPTY,
        } and (away_count, home_count) != (1, 1):
            raise DependentWorkloadContractError(
                "complete or valid-empty rotation scope requires exact paired receipts"
            )


def _compile_matchup_scope(
    evidence: FoundationScopeEvidence,
    observations: tuple[DirectionalMatchupObservation, ...],
) -> tuple[
    tuple[PlayerMatchupOccurrence, ...],
    tuple[TeamPlayerOccurrence, ...],
    tuple[DependentScopeDisposition, str],
]:
    state = evidence.matchup_state
    if state is FoundationEvidenceState.INCONCLUSIVE:
        raise DependentWorkloadInconclusiveError(
            f"matchup foundation evidence is inconclusive for {evidence.scope.game_id}"
        )
    if state is FoundationEvidenceState.BLOCKED:
        if observations:
            raise DependentWorkloadContractError(
                "blocked matchup scope cannot contain observed rows"
            )
        return (), (), (DependentScopeDisposition.BLOCKED, evidence.matchup_reason_code)
    if state is FoundationEvidenceState.VALID_EMPTY:
        if observations:
            raise DependentWorkloadContractError(
                "valid-empty matchup scope cannot contain observed rows"
            )
        return (), (), (DependentScopeDisposition.TYPED_ZERO, "verified_empty_matchup_rows")
    if not observations:
        raise DependentWorkloadInconclusiveError(
            f"complete matchup scope has no observed rows for {evidence.scope.game_id}"
        )

    players = tuple(
        PlayerMatchupOccurrence(
            scope=observation.scope,
            player_id=observation.off_player_id,
            player_team_id=observation.off_team_id,
            vs_player_id=observation.def_player_id,
            vs_team_id=observation.def_team_id,
            source_row=observation.source_row,
        )
        for observation in observations
    )
    teams = tuple(
        TeamPlayerOccurrence(
            scope=observation.scope,
            team_id=observation.off_team_id,
            vs_player_id=observation.def_player_id,
            vs_team_id=observation.def_team_id,
            source_row=observation.source_row,
        )
        for observation in observations
    )
    return players, teams, (DependentScopeDisposition.COMPLETE, "observed_directional_matchup")


def _compile_rotation_scope(
    evidence: FoundationScopeEvidence,
    observations: tuple[RotationObservation, ...],
) -> tuple[tuple[FiveVsFiveOccurrence, ...], tuple[DependentScopeDisposition, str]]:
    state = evidence.rotation_state
    if state is FoundationEvidenceState.INCONCLUSIVE:
        raise DependentWorkloadInconclusiveError(
            f"rotation foundation evidence is inconclusive for {evidence.scope.game_id}"
        )
    if state is FoundationEvidenceState.BLOCKED:
        if observations:
            raise DependentWorkloadContractError(
                "blocked rotation scope cannot contain observed rows"
            )
        return (), (DependentScopeDisposition.BLOCKED, evidence.rotation_reason_code)
    if state is FoundationEvidenceState.VALID_EMPTY:
        if observations:
            raise DependentWorkloadContractError(
                "valid-empty rotation scope cannot contain observed rows"
            )
        return (), (DependentScopeDisposition.TYPED_ZERO, "verified_empty_rotation_rows")
    if not observations:
        raise DependentWorkloadInconclusiveError(
            f"complete rotation scope has no observed rows for {evidence.scope.game_id}"
        )

    by_side = {
        side: tuple(observation for observation in observations if observation.side == side)
        for side in ("away", "home")
    }
    team_ids_by_side = {
        side: {observation.team_id for observation in side_observations}
        for side, side_observations in by_side.items()
    }
    if any(len(team_ids) != 1 for team_ids in team_ids_by_side.values()):
        return (), (DependentScopeDisposition.BLOCKED, "rotation_side_team_cardinality")
    away_team_id = next(iter(team_ids_by_side["away"]))
    home_team_id = next(iter(team_ids_by_side["home"]))
    if away_team_id == home_team_id:
        return (), (DependentScopeDisposition.BLOCKED, "rotation_teams_not_distinct")

    boundaries = sorted(
        {
            boundary
            for observation in observations
            for boundary in (observation.interval_start, observation.interval_end)
        }
    )
    occurrences: list[FiveVsFiveOccurrence] = []
    for interval_start, interval_end in zip(boundaries, boundaries[1:], strict=False):
        if interval_end <= interval_start:
            continue
        active = {
            side: tuple(
                observation
                for observation in by_side[side]
                if observation.interval_start <= interval_start
                and observation.interval_end >= interval_end
            )
            for side in ("away", "home")
        }
        if any(len(active[side]) != 5 for side in ("away", "home")):
            return (), (DependentScopeDisposition.BLOCKED, "rotation_interval_not_exact_five")
        player_ids = {
            side: tuple(sorted(observation.player_id for observation in active[side]))
            for side in ("away", "home")
        }
        if any(len(set(player_ids[side])) != 5 for side in ("away", "home")):
            return (), (DependentScopeDisposition.BLOCKED, "rotation_interval_duplicate_player")
        if set(player_ids["away"]) & set(player_ids["home"]):
            return (), (DependentScopeDisposition.BLOCKED, "rotation_interval_player_overlap")
        source_rows = tuple(
            observation.source_row for side in ("away", "home") for observation in active[side]
        )
        for team_side, vs_team_side in (("away", "home"), ("home", "away")):
            occurrences.append(
                FiveVsFiveOccurrence(
                    scope=evidence.scope,
                    interval_start=canonical_decimal(interval_start),
                    interval_end=canonical_decimal(interval_end),
                    team_id=(away_team_id if team_side == "away" else home_team_id),
                    team_player_ids=player_ids[team_side],
                    team_side=team_side,
                    vs_team_id=(home_team_id if vs_team_side == "home" else away_team_id),
                    vs_player_ids=player_ids[vs_team_side],
                    vs_team_side=vs_team_side,
                    source_rows=source_rows,
                )
            )
    if not occurrences:
        return (), (DependentScopeDisposition.BLOCKED, "rotation_has_no_positive_interval")
    return tuple(occurrences), (
        DependentScopeDisposition.COMPLETE,
        "observed_exact_five_v_five_both_directions",
    )


def _player_parameters(
    occurrence: PlayerMatchupOccurrence,
) -> tuple[tuple[str, int | str], ...]:
    return (
        ("season", occurrence.scope.season),
        ("season_type", occurrence.scope.season_type),
        ("player_id", occurrence.player_id),
        ("vs_player_id", occurrence.vs_player_id),
    )


def _team_parameters(
    occurrence: TeamPlayerOccurrence,
) -> tuple[tuple[str, int | str], ...]:
    return (
        ("season", occurrence.scope.season),
        ("season_type", occurrence.scope.season_type),
        ("team_id", occurrence.team_id),
        ("vs_player_id", occurrence.vs_player_id),
    )


def _lineup_parameters(
    occurrence: FiveVsFiveOccurrence,
) -> tuple[tuple[str, int | str], ...]:
    return (
        ("season", occurrence.scope.season),
        ("season_type", occurrence.scope.season_type),
        ("team_id", occurrence.team_id),
        ("vs_team_id", occurrence.vs_team_id),
        *(
            (f"player_id{index}", player_id)
            for index, player_id in enumerate(occurrence.team_player_ids, start=1)
        ),
        *(
            (f"vs_player_id{index}", player_id)
            for index, player_id in enumerate(occurrence.vs_player_ids, start=1)
        ),
    )


def _build_executable_units(
    player_occurrences: tuple[PlayerMatchupOccurrence, ...],
    team_occurrences: tuple[TeamPlayerOccurrence, ...],
    lineup_occurrences: tuple[FiveVsFiveOccurrence, ...],
) -> tuple[DependentExecutableUnit, ...]:
    grouped: dict[
        tuple[DependentWorkloadKind, tuple[tuple[str, int | str], ...]],
        set[str],
    ] = {}
    for occurrence in player_occurrences:
        key = (DependentWorkloadKind.PLAYER_MATCHUP, _player_parameters(occurrence))
        grouped.setdefault(key, set()).add(occurrence.identity_sha256)
    for occurrence in team_occurrences:
        key = (DependentWorkloadKind.TEAM_PLAYER, _team_parameters(occurrence))
        grouped.setdefault(key, set()).add(occurrence.identity_sha256)
    for occurrence in lineup_occurrences:
        key = (DependentWorkloadKind.FIVE_V_FIVE, _lineup_parameters(occurrence))
        grouped.setdefault(key, set()).add(occurrence.identity_sha256)
    return tuple(
        DependentExecutableUnit(
            kind=kind,
            parameters=parameters,
            occurrence_sha256s=tuple(sorted(occurrence_sha256s)),
        )
        for (kind, parameters), occurrence_sha256s in sorted(
            grouped.items(),
            key=lambda item: (item[0][0].value, item[0][1]),
        )
    )


def _unit_count_for_scope(
    *,
    scope: WorkloadScope,
    kind: DependentWorkloadKind,
    occurrence_ids: set[str],
    units: tuple[DependentExecutableUnit, ...],
) -> int:
    del scope  # Scope is represented by the exact occurrence set supplied by the caller.
    return sum(
        unit.kind is kind and bool(set(unit.occurrence_sha256s) & occurrence_ids) for unit in units
    )


def _disposition_record(
    *,
    scope: WorkloadScope,
    kind: DependentWorkloadKind,
    outcome: tuple[DependentScopeDisposition, str],
    occurrence_ids: set[str],
    units: tuple[DependentExecutableUnit, ...],
) -> ScopeDispositionRecord:
    disposition, reason_code = outcome
    return ScopeDispositionRecord(
        scope=scope,
        kind=kind,
        disposition=disposition,
        reason_code=reason_code,
        occurrence_count=len(occurrence_ids),
        executable_unit_count=_unit_count_for_scope(
            scope=scope,
            kind=kind,
            occurrence_ids=occurrence_ids,
            units=units,
        ),
    )


def compile_dependent_workload(
    *,
    authority: FoundationAuthority,
    scope_evidence: Sequence[FoundationScopeEvidence],
    matchup_observations: Iterable[DirectionalMatchupObservation],
    rotation_observations: Iterable[RotationObservation],
) -> DependentWorkloadBundle:
    """Compile one atomic bundle without planner, workflow, or network side effects."""

    if not isinstance(authority, FoundationAuthority):
        raise DependentWorkloadContractError("foundation authority is invalid")
    scopes = tuple(sorted(scope_evidence))
    if not scopes:
        raise DependentWorkloadContractError("dependent workload scope inventory is empty")
    scope_ids = [item.scope for item in scopes]
    if len(scope_ids) != len(set(scope_ids)):
        raise DependentWorkloadContractError("dependent workload scopes contain duplicates")

    matchups = tuple(sorted(matchup_observations))
    rotations = tuple(sorted(rotation_observations))
    receipt_lookup = _receipt_lookup(authority)
    _validate_observations(
        scope_evidence=scopes,
        matchup_observations=matchups,
        rotation_observations=rotations,
        receipt_lookup=receipt_lookup,
    )

    player_occurrences: list[PlayerMatchupOccurrence] = []
    team_occurrences: list[TeamPlayerOccurrence] = []
    lineup_occurrences: list[FiveVsFiveOccurrence] = []
    matchup_outcomes: dict[WorkloadScope, tuple[DependentScopeDisposition, str]] = {}
    rotation_outcomes: dict[WorkloadScope, tuple[DependentScopeDisposition, str]] = {}
    for evidence in scopes:
        scope_matchups = tuple(item for item in matchups if item.scope == evidence.scope)
        scope_rotations = tuple(item for item in rotations if item.scope == evidence.scope)
        players, teams, matchup_outcome = _compile_matchup_scope(evidence, scope_matchups)
        lineups, rotation_outcome = _compile_rotation_scope(evidence, scope_rotations)
        player_occurrences.extend(players)
        team_occurrences.extend(teams)
        lineup_occurrences.extend(lineups)
        matchup_outcomes[evidence.scope] = matchup_outcome
        rotation_outcomes[evidence.scope] = rotation_outcome

    player_tuple = tuple(player_occurrences)
    team_tuple = tuple(team_occurrences)
    lineup_tuple = tuple(lineup_occurrences)
    units = _build_executable_units(player_tuple, team_tuple, lineup_tuple)

    dispositions: list[ScopeDispositionRecord] = []
    for evidence in scopes:
        player_ids = {item.identity_sha256 for item in player_tuple if item.scope == evidence.scope}
        team_ids = {item.identity_sha256 for item in team_tuple if item.scope == evidence.scope}
        lineup_ids = {item.identity_sha256 for item in lineup_tuple if item.scope == evidence.scope}
        dispositions.extend(
            (
                _disposition_record(
                    scope=evidence.scope,
                    kind=DependentWorkloadKind.PLAYER_MATCHUP,
                    outcome=matchup_outcomes[evidence.scope],
                    occurrence_ids=player_ids,
                    units=units,
                ),
                _disposition_record(
                    scope=evidence.scope,
                    kind=DependentWorkloadKind.TEAM_PLAYER,
                    outcome=matchup_outcomes[evidence.scope],
                    occurrence_ids=team_ids,
                    units=units,
                ),
                _disposition_record(
                    scope=evidence.scope,
                    kind=DependentWorkloadKind.FIVE_V_FIVE,
                    outcome=rotation_outcomes[evidence.scope],
                    occurrence_ids=lineup_ids,
                    units=units,
                ),
            )
        )

    return DependentWorkloadBundle(
        authority=authority,
        player_matchup_occurrences=player_tuple,
        team_player_occurrences=team_tuple,
        five_v_five_occurrences=lineup_tuple,
        executable_units=units,
        scope_dispositions=tuple(dispositions),
    )
