from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from functools import cache
from inspect import Parameter, signature
from typing import Any, ClassVar

import polars as pl
from loguru import logger

from nbadb.core.errors import ResponseContractError
from nbadb.core.errors import ValidationError as NbaDbValidationError
from nbadb.core.extraction_failures import (
    classify_exception,
    is_transport_error,
    safe_root_error_type,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    owned_contract_sha256,
    pinned_endpoint_contract,
    pinned_live_endpoint_contract,
    pinned_static_dataset_contract,
)
from nbadb.extract.landing_projection import (
    _to_snake_case as _projected_to_snake_case,
)
from nbadb.extract.landing_projection import (
    apply_live_snapshot_contract,
    live_payload_to_frame,
    normalize_live_landing_frame,
)
from nbadb.extract.live_lossless import NbaApiLiveLosslessLanding
from nbadb.extract.nba_api_adapter import (
    NbaApiCaptureContract,
    NbaApiLosslessFallback,
    NbaApiPayload,
    NbaApiUnknownResponse,
    fetch_live_payloads,
    fetch_stats_packets,
    fetch_stats_payload,
)
from nbadb.extract.raw_request_capture import (
    RawRequestCaptureContextV2,
    RawRequestCaptureSink,
    RawRequestCaptureSnapshotV2,
    wrap_raw_request_capture_contract,
)
from nbadb.extract.raw_schema_registry import get_raw_schema

_BOX_SCORE_TRADITIONAL_COMMON_COLUMN_ALIASES = {
    "assists": "ast",
    "blocks": "blk",
    "field_goals_attempted": "fga",
    "field_goals_made": "fgm",
    "field_goals_percentage": "fg_pct",
    "fouls_personal": "pf",
    "free_throws_attempted": "fta",
    "free_throws_made": "ftm",
    "free_throws_percentage": "ft_pct",
    "minutes": "min",
    "points": "pts",
    "rebounds_defensive": "dreb",
    "rebounds_offensive": "oreb",
    "rebounds_total": "reb",
    "steals": "stl",
    "team_tricode": "team_abbreviation",
    "three_pointers_attempted": "fg3a",
    "three_pointers_made": "fg3m",
    "three_pointers_percentage": "fg3_pct",
    "turnovers": "tov",
}

_BOX_SCORE_TRADITIONAL_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        **_BOX_SCORE_TRADITIONAL_COMMON_COLUMN_ALIASES,
        "person_id": "player_id",
        "plus_minus_points": "plus_minus",
        "position": "start_position",
    },
    1: _BOX_SCORE_TRADITIONAL_COMMON_COLUMN_ALIASES,
    2: {
        **_BOX_SCORE_TRADITIONAL_COMMON_COLUMN_ALIASES,
        "plus_minus_points": "plus_minus",
    },
}

_BOX_SCORE_PLAYER_IDENTITY_ALIASES = {
    "person_id": "player_id",
    "team_tricode": "team_abbreviation",
}

_BOX_SCORE_TEAM_IDENTITY_ALIASES = {
    "team_tricode": "team_abbreviation",
}

_BOX_SCORE_ADVANCED_COLUMN_ALIASES = {
    "assist_percentage": "ast_pct",
    "assist_ratio": "ast_ratio",
    "assist_to_turnover": "ast_tov",
    "defensive_rating": "def_rating",
    "defensive_rebound_percentage": "dreb_pct",
    "effective_field_goal_percentage": "efg_pct",
    "estimated_defensive_rating": "e_def_rating",
    "estimated_net_rating": "e_net_rating",
    "estimated_offensive_rating": "e_off_rating",
    "estimated_pace": "e_pace",
    "estimated_usage_percentage": "e_usg_pct",
    "offensive_rating": "off_rating",
    "offensive_rebound_percentage": "oreb_pct",
    "possessions": "poss",
    "rebound_percentage": "reb_pct",
    "true_shooting_percentage": "ts_pct",
    "turnover_ratio": "tov_pct",
    "usage_percentage": "usg_pct",
}

_BOX_SCORE_ADVANCED_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        **_BOX_SCORE_PLAYER_IDENTITY_ALIASES,
        **_BOX_SCORE_ADVANCED_COLUMN_ALIASES,
        "minutes": "min",
    },
    1: {
        **_BOX_SCORE_TEAM_IDENTITY_ALIASES,
        **_BOX_SCORE_ADVANCED_COLUMN_ALIASES,
        "estimated_team_turnover_percentage": "tm_tov_pct",
        "minutes": "min",
    },
}

_BOX_SCORE_MISC_COLUMN_ALIASES = {
    "blocks": "blk",
    "blocks_against": "blka",
    "fouls_drawn": "pfd",
    "fouls_personal": "pf",
    "minutes": "min",
    "opp_points_fast_break": "opp_fbps",
    "opp_points_off_turnovers": "opp_pts_off_tov",
    "opp_points_paint": "opp_pitp",
    "opp_points_second_chance": "opp_second_chance_pts",
    "points_fast_break": "fbps",
    "points_off_turnovers": "pts_off_tov",
    "points_paint": "pitp",
    "points_second_chance": "second_chance_pts",
}

_BOX_SCORE_MISC_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        **_BOX_SCORE_PLAYER_IDENTITY_ALIASES,
        **_BOX_SCORE_MISC_COLUMN_ALIASES,
    },
    1: {
        **_BOX_SCORE_TEAM_IDENTITY_ALIASES,
        **_BOX_SCORE_MISC_COLUMN_ALIASES,
    },
}

_BOX_SCORE_SCORING_COLUMN_ALIASES = {
    "minutes": "min",
    "percentage_assisted2pt": "pct_ast_2pm",
    "percentage_assisted3pt": "pct_ast_3pm",
    "percentage_assisted_fgm": "pct_ast_fgm",
    "percentage_field_goals_attempted2pt": "pct_fga_2pt",
    "percentage_field_goals_attempted3pt": "pct_fga_3pt",
    "percentage_points2pt": "pct_pts_2pt",
    "percentage_points3pt": "pct_pts_3pt",
    "percentage_points_fast_break": "pct_pts_fb",
    "percentage_points_free_throw": "pct_pts_ft",
    "percentage_points_midrange2pt": "pct_pts_2pt_mr",
    "percentage_points_off_turnovers": "pct_pts_off_tov",
    "percentage_points_paint": "pct_pts_pitp",
    "percentage_unassisted2pt": "pct_uast_2pm",
    "percentage_unassisted3pt": "pct_uast_3pm",
    "percentage_unassisted_fgm": "pct_uast_fgm",
}

_BOX_SCORE_SCORING_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        **_BOX_SCORE_PLAYER_IDENTITY_ALIASES,
        **_BOX_SCORE_SCORING_COLUMN_ALIASES,
    },
    1: {
        **_BOX_SCORE_TEAM_IDENTITY_ALIASES,
        **_BOX_SCORE_SCORING_COLUMN_ALIASES,
    },
}

_BOX_SCORE_USAGE_COLUMN_ALIASES = {
    "minutes": "min",
    "percentage_assists": "pct_ast",
    "percentage_blocks": "pct_blk",
    "percentage_blocks_allowed": "pct_blka",
    "percentage_field_goals_attempted": "pct_fga",
    "percentage_field_goals_made": "pct_fgm",
    "percentage_free_throws_attempted": "pct_fta",
    "percentage_free_throws_made": "pct_ftm",
    "percentage_personal_fouls": "pct_pf",
    "percentage_personal_fouls_drawn": "pct_pfd",
    "percentage_points": "pct_pts",
    "percentage_rebounds_defensive": "pct_dreb",
    "percentage_rebounds_offensive": "pct_oreb",
    "percentage_rebounds_total": "pct_reb",
    "percentage_steals": "pct_stl",
    "percentage_three_pointers_attempted": "pct_fg3a",
    "percentage_three_pointers_made": "pct_fg3m",
    "percentage_turnovers": "pct_tov",
    "usage_percentage": "usg_pct",
}

_BOX_SCORE_USAGE_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        **_BOX_SCORE_PLAYER_IDENTITY_ALIASES,
        **_BOX_SCORE_USAGE_COLUMN_ALIASES,
    },
    1: {
        **_BOX_SCORE_TEAM_IDENTITY_ALIASES,
        **_BOX_SCORE_USAGE_COLUMN_ALIASES,
    },
}

_BOX_SCORE_PLAYER_TRACK_COLUMN_ALIASES = {
    "assists": "ast",
    "contested_field_goal_percentage": "cfg_pct",
    "contested_field_goals_attempted": "cfga",
    "contested_field_goals_made": "cfgm",
    "defended_at_rim_field_goal_percentage": "dfg_pct",
    "defended_at_rim_field_goals_attempted": "dfga",
    "defended_at_rim_field_goals_made": "dfgm",
    "distance": "dist",
    "field_goal_percentage": "fg_pct",
    "free_throw_assists": "ftast",
    "minutes": "min",
    "rebound_chances_defensive": "drbc",
    "rebound_chances_offensive": "orbc",
    "rebound_chances_total": "rbc",
    "secondary_assists": "sast",
    "speed": "spd",
    "touches": "tchs",
    "uncontested_field_goals_attempted": "ufga",
    "uncontested_field_goals_made": "ufgm",
    "uncontested_field_goals_percentage": "ufg_pct",
}

_BOX_SCORE_PLAYER_TRACK_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        **_BOX_SCORE_PLAYER_IDENTITY_ALIASES,
        **_BOX_SCORE_PLAYER_TRACK_COLUMN_ALIASES,
        "passes": "pass",
    },
    1: {
        **_BOX_SCORE_TEAM_IDENTITY_ALIASES,
        **_BOX_SCORE_PLAYER_TRACK_COLUMN_ALIASES,
    },
}

_BOX_SCORE_DEFENSIVE_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        **_BOX_SCORE_PLAYER_IDENTITY_ALIASES,
        "matchup_field_goal_percentage": "def_fg_pct",
        "matchup_field_goals_attempted": "def_fga",
        "matchup_field_goals_made": "def_fgm",
        "matchup_minutes": "matchup_min",
        "partial_possessions": "partial_poss",
        "player_points": "player_pts",
    },
    1: {
        **_BOX_SCORE_TEAM_IDENTITY_ALIASES,
        "minutes": "min",
    },
}

_BOX_SCORE_FOUR_FACTORS_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        **_BOX_SCORE_PLAYER_IDENTITY_ALIASES,
        "minutes": "min",
    },
    1: {
        **_BOX_SCORE_TEAM_IDENTITY_ALIASES,
        "minutes": "min",
    },
}

_BOX_SCORE_HUSTLE_COLUMN_ALIASES = {
    "contested_shots2pt": "contested_shots_2pt",
    "contested_shots3pt": "contested_shots_3pt",
    "loose_balls_recovered_total": "loose_balls_recovered",
    "minutes": "min",
    "screen_assist_points": "screen_ast_pts",
}

_BOX_SCORE_HUSTLE_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        **_BOX_SCORE_PLAYER_IDENTITY_ALIASES,
        **_BOX_SCORE_HUSTLE_COLUMN_ALIASES,
    },
    1: {
        **_BOX_SCORE_TEAM_IDENTITY_ALIASES,
        **_BOX_SCORE_HUSTLE_COLUMN_ALIASES,
    },
}

_BOX_SCORE_SUMMARY_V2_COLUMN_ALIASES_BY_RESULT_INDEX = {
    6: {
        "jersey_num": "jersey_number",
    },
}

_BOX_SCORE_SUMMARY_V3_COLUMN_ALIASES_BY_RESULT_INDEX = {
    8: {
        "pt_xyzavailable": "pt_xyz_available",
    },
}

_COMMON_ALL_PLAYERS_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        "rosterstatus": "roster_status",
    },
}

_COMMON_PLAYER_INFO_COLUMN_ALIASES_BY_RESULT_INDEX = {
    1: {
        "rosterstatus": "roster_status",
    },
}

_COMMON_PLAYOFF_SERIES_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        "game_num": "game_number",
        "visitor_team_id": "away_team_id",
    },
}

_PLAY_BY_PLAY_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        "video_available_flag": "video_available",
    },
}

_SCOREBOARD_V2_COLUMN_ALIASES_BY_RESULT_INDEX = {
    1: {
        "returntoplay": "return_to_play",
        "standingsdate": "standings_date",
    },
    8: {
        "standingsdate": "standings_date",
    },
}

_SYNERGY_PLAY_TYPES_COLUMN_ALIASES_BY_RESULT_INDEX = {
    0: {
        "ft_poss_pct": "ft_pct_adjust",
        "plusone_poss_pct": "plusone_pct",
        "score_poss_pct": "score_pct",
        "sf_poss_pct": "sf_pct",
        "tov_poss_pct": "to_pct",
    },
}

_COLUMN_ALIASES_BY_ENDPOINT_AND_RESULT_INDEX = {
    "BoxScoreAdvancedV3": _BOX_SCORE_ADVANCED_COLUMN_ALIASES_BY_RESULT_INDEX,
    "BoxScoreDefensiveV2": _BOX_SCORE_DEFENSIVE_COLUMN_ALIASES_BY_RESULT_INDEX,
    "BoxScoreFourFactorsV3": _BOX_SCORE_FOUR_FACTORS_COLUMN_ALIASES_BY_RESULT_INDEX,
    "BoxScoreHustleV2": _BOX_SCORE_HUSTLE_COLUMN_ALIASES_BY_RESULT_INDEX,
    "BoxScoreMiscV3": _BOX_SCORE_MISC_COLUMN_ALIASES_BY_RESULT_INDEX,
    "BoxScorePlayerTrackV3": _BOX_SCORE_PLAYER_TRACK_COLUMN_ALIASES_BY_RESULT_INDEX,
    "BoxScoreScoringV3": _BOX_SCORE_SCORING_COLUMN_ALIASES_BY_RESULT_INDEX,
    "BoxScoreSummaryV2": _BOX_SCORE_SUMMARY_V2_COLUMN_ALIASES_BY_RESULT_INDEX,
    "BoxScoreSummaryV3": _BOX_SCORE_SUMMARY_V3_COLUMN_ALIASES_BY_RESULT_INDEX,
    "BoxScoreTraditionalV3": _BOX_SCORE_TRADITIONAL_COLUMN_ALIASES_BY_RESULT_INDEX,
    "BoxScoreUsageV3": _BOX_SCORE_USAGE_COLUMN_ALIASES_BY_RESULT_INDEX,
    "CommonAllPlayers": _COMMON_ALL_PLAYERS_COLUMN_ALIASES_BY_RESULT_INDEX,
    "CommonPlayerInfo": _COMMON_PLAYER_INFO_COLUMN_ALIASES_BY_RESULT_INDEX,
    "CommonPlayoffSeries": _COMMON_PLAYOFF_SERIES_COLUMN_ALIASES_BY_RESULT_INDEX,
    "PlayByPlay": _PLAY_BY_PLAY_COLUMN_ALIASES_BY_RESULT_INDEX,
    "PlayByPlayV3": _PLAY_BY_PLAY_COLUMN_ALIASES_BY_RESULT_INDEX,
    "ScoreboardV2": _SCOREBOARD_V2_COLUMN_ALIASES_BY_RESULT_INDEX,
    "SynergyPlayTypes": _SYNERGY_PLAY_TYPES_COLUMN_ALIASES_BY_RESULT_INDEX,
}

# nba_api kwargs that carry the season_type value (checked in priority order)
_SEASON_TYPE_KEYS = (
    "season_type_all_star",
    "season_type_playoffs",
    "season_type",
    "season_type_nullable",
    "season_type_all_star_nullable",
)

_SEASON_YEAR_KEYS = (
    "season",
    "season_nullable",
    "season_year",
)

_LEAGUE_ID_KEYS = (
    "league_id",
    "league_id_nullable",
)

_REQUEST_SCOPE_ALIAS_GROUPS = (
    _LEAGUE_ID_KEYS,
    _SEASON_TYPE_KEYS,
)

_PROVIDER_TRANSPORT_PARAMETERS = frozenset(
    {
        "get_request",
        "headers",
        "proxy",
        "timeout",
    }
)


def _extract_season_type(kwargs: Mapping[str, Any]) -> str | None:
    """Extract the season_type value from nba_api kwargs.

    Returns the season_type string if found, None otherwise (e.g. game-level
    endpoints that don't use season_type).
    """
    for key in _SEASON_TYPE_KEYS:
        if key in kwargs:
            val = kwargs[key]
            return val if val else None
    return None


def _first_request_scope_value(
    kwargs: Mapping[str, Any],
    keys: tuple[str, ...],
) -> object | None:
    """Return the first explicit nonempty request-scope value."""

    for key in keys:
        value = kwargs.get(key)
        if value is not None and value != "":
            return value
    return None


def _inject_request_scope_columns(
    df: pl.DataFrame,
    kwargs: Mapping[str, Any],
) -> pl.DataFrame:
    """Retain model-critical request dimensions absent from provider rows.

    Many season-scoped ``nba_api`` result sets omit the season and league that
    selected them.  Without these dimensions, identical entity rows from
    different requests collide in staging and cannot support truthful
    historical or multi-competition models.  Provider-returned columns remain
    authoritative and are never overwritten.
    """

    additions: list[pl.Expr] = []
    season_year = _first_request_scope_value(kwargs, _SEASON_YEAR_KEYS)
    season_type = _extract_season_type(kwargs)
    league_id = _first_request_scope_value(kwargs, _LEAGUE_ID_KEYS)
    if season_year is not None and "season_year" not in df.columns:
        additions.append(pl.lit(season_year).alias("season_year"))
    if season_type is not None and "season_type" not in df.columns:
        additions.append(pl.lit(season_type).alias("season_type"))
    if league_id is not None and "league_id" not in df.columns:
        additions.append(pl.lit(league_id).alias("league_id"))
    return df.with_columns(additions) if additions else df


@cache
def _provider_constructor_parameters(endpoint_cls: type) -> frozenset[str]:
    """Return explicitly declared public constructor parameters.

    Request forwarding is intentionally constrained to names declared by the
    pinned ``nba_api`` endpoint class.  A generic ``**kwargs`` parameter is not
    authority to forward runner/control-plane fields to the provider.
    """

    try:
        parameters = signature(endpoint_cls).parameters.values()
    except (TypeError, ValueError):
        return frozenset()
    return frozenset(
        parameter.name
        for parameter in parameters
        if parameter.kind
        in {
            Parameter.POSITIONAL_OR_KEYWORD,
            Parameter.KEYWORD_ONLY,
        }
        and parameter.name not in _PROVIDER_TRANSPORT_PARAMETERS
    )


def _explicit_alias_value(
    params: Mapping[str, Any],
    aliases: tuple[str, ...],
) -> object | None:
    """Resolve one semantic request value and reject contradictory aliases."""

    present = tuple(
        (name, params[name])
        for name in aliases
        if name in params and params[name] is not None and params[name] != ""
    )
    if not present:
        return None
    first_value = present[0][1]
    if any(value != first_value for _, value in present[1:]):
        raise ResponseContractError("logical request contains conflicting scope aliases")
    return first_value


def _forward_explicit_provider_parameters(
    endpoint_cls: type,
    kwargs: dict[str, Any],
    logical_params: Mapping[str, Any],
) -> dict[str, Any]:
    """Forward planner parameters accepted by the exact provider endpoint.

    Endpoint wrappers remain free to normalize or derive parameters.  This
    boundary fills only omitted constructor arguments and rejects a wrapper
    value that conflicts with the explicit logical request.  It prevents
    ``nba_api`` defaults (notably ``league_id='00'``) from silently narrowing
    a multi-competition extraction.
    """

    accepted = _provider_constructor_parameters(endpoint_cls)
    if not accepted or not logical_params:
        return kwargs

    forwarded = dict(kwargs)
    for name in sorted(accepted):
        if name in logical_params and name not in _PROVIDER_TRANSPORT_PARAMETERS:
            requested = logical_params[name]
            if name in forwarded and forwarded[name] != requested:
                raise ResponseContractError(
                    "extractor wrapper changed an explicit provider request parameter"
                )
            forwarded.setdefault(name, requested)

    for aliases in _REQUEST_SCOPE_ALIAS_GROUPS:
        requested = _explicit_alias_value(logical_params, aliases)
        if requested is None:
            continue
        targets = tuple(name for name in aliases if name in accepted)
        for target in targets:
            if target in forwarded and forwarded[target] != requested:
                raise ResponseContractError(
                    "extractor wrapper changed an explicit request-scope parameter"
                )
        if not any(target in forwarded for target in targets) and targets:
            forwarded[targets[0]] = requested
    return forwarded


def _to_snake_case(name: str) -> str:
    """Convert any column name style to snake_case.

    Handles UPPER_SNAKE_CASE (e.g., GAME_ID -> game_id),
    all-uppercase nba_api stat shorthands (e.g., FG3M -> fg3m),
    camelCase (e.g., gameId -> game_id), and mixed cases.
    """
    return _projected_to_snake_case(name)


def _canonicalize_endpoint_column_name(
    endpoint_cls_name: str,
    result_set_index: int,
    name: str,
) -> str:
    snake_name = _to_snake_case(name)
    aliases_by_index = _COLUMN_ALIASES_BY_ENDPOINT_AND_RESULT_INDEX.get(endpoint_cls_name)
    if aliases_by_index is None:
        return snake_name
    return aliases_by_index.get(result_set_index, {}).get(snake_name, snake_name)


def is_retryable_error(exc: Exception) -> bool:
    """Return True if *exc* looks transient and worth retrying."""
    return is_transport_error(exc)


def _coerce_snapshot_at(value: object | None) -> datetime:
    """Normalize snapshot inputs to a timezone-aware UTC datetime."""
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    raise TypeError(f"snapshot_at must be a date or datetime, got {type(value).__name__}")


class BaseExtractor(ABC):
    endpoint_name: ClassVar[str]
    category: ClassVar[str] = "default"
    _request_timeout_override: int | None = None
    _capture_contract: NbaApiCaptureContract | None = None
    _raw_request_capture_context: RawRequestCaptureContextV2 | None = None
    _raw_request_capture_sink: RawRequestCaptureSink | None = None
    _lossless_fallbacks: tuple[NbaApiLosslessFallback, ...] = ()
    _live_lossless_landings: tuple[NbaApiLiveLosslessLanding, ...] = ()
    _unknown_responses: tuple[NbaApiUnknownResponse, ...] = ()
    _runner_attempt_active: bool = False
    _logical_request_params: Mapping[str, Any] = {}

    @abstractmethod
    async def extract(self, **params: Any) -> pl.DataFrame: ...

    def set_capture_contract(self, contract: NbaApiCaptureContract | None) -> None:
        """Install an explicit per-attempt private capture contract."""

        self._lossless_fallbacks = ()
        self._live_lossless_landings = ()
        self._unknown_responses = ()
        if contract is not None and self.category == "static":
            try:
                static_contract = pinned_static_dataset_contract(self.endpoint_name)
            except ValueError as exc:
                raise ResponseContractError(
                    "static extractor lacks pinned nbadb capture authority"
                ) from exc
            contract = contract.for_endpoint_contract(owned_contract_sha256(static_contract))
        if contract is not None:
            wrapped = wrap_raw_request_capture_contract(
                contract,
                self._raw_request_capture_context,
            )
            self._raw_request_capture_sink = wrapped.sink
            contract = wrapped
        self._capture_contract = contract

    def set_raw_request_capture_context(
        self,
        context: RawRequestCaptureContextV2 | None,
    ) -> None:
        """Install explicit public authority before the private capture contract."""

        if self._capture_contract is not None:
            raise ResponseContractError(
                "public raw-request context must precede private capture installation"
            )
        self._raw_request_capture_context = context
        self._raw_request_capture_sink = None

    def begin_extraction_attempt(self) -> None:
        """Reset response-local state before one runner-owned attempt.

        Runner retries use fresh extractor instances today, but this boundary
        also makes that isolation explicit and keeps reused test or extension
        instances from carrying a fallback into a later logical call.
        """

        self._lossless_fallbacks = ()
        self._live_lossless_landings = ()
        self._unknown_responses = ()
        self._capture_contract = None
        self._raw_request_capture_context = None
        self._raw_request_capture_sink = None
        self._logical_request_params = {}
        self._runner_attempt_active = True

    def set_logical_request_params(self, params: Mapping[str, Any]) -> None:
        """Bind the runner-authorized logical request to this fresh attempt."""

        if not isinstance(params, Mapping):
            raise TypeError("logical request parameters must be a mapping")
        self._logical_request_params = dict(params)

    def lossless_fallback_snapshot(self) -> tuple[NbaApiLosslessFallback, ...]:
        """Return the fallbacks produced by the current logical attempt."""

        return self._lossless_fallbacks

    def live_lossless_landing_snapshot(self) -> tuple[NbaApiLiveLosslessLanding, ...]:
        """Return complete live node landings produced by this logical attempt.

        This is the typed integration seam for a separately admitted
        ``stg_nba_api_live_lossless_nodes`` conditional route.  It intentionally
        remains distinct from the fixed stats result-cell fallback contract.
        """

        return self._live_lossless_landings

    def unknown_response_snapshot(self) -> tuple[NbaApiUnknownResponse, ...]:
        """Return exact unknown-response observations for this logical attempt.

        These observations are the extraction-side authority for the four
        exact pinned Video endpoints whose provider result inventory is
        unknown.  They are deliberately separate from fixed relational result
        packets and from inferred schemas.
        """

        return self._unknown_responses

    def _retain_unknown_response(
        self,
        source: object,
        endpoint_cls: type,
    ) -> NbaApiUnknownResponse | None:
        """Validate and retain one adapter-owned unknown response observation."""

        observation = getattr(source, "unknown_response", None)
        if not isinstance(getattr(endpoint_cls, "__name__", None), str):
            if observation is None:
                return None
            raise ResponseContractError(
                "unnamed stats endpoint returned an unknown response observation"
            )
        try:
            contract = pinned_endpoint_contract(endpoint_cls)
            response_contract = contract.response_contract
        except (AttributeError, TypeError, ValueError) as exc:
            if observation is None:
                return None
            raise ResponseContractError(
                "unpinned stats endpoint returned an unknown response observation"
            ) from exc

        if response_contract.response_mode != "unknown_dynamic_response":
            if observation is None:
                return None
            raise ResponseContractError(
                "declared-result endpoint returned an unknown response observation"
            )
        if not isinstance(observation, NbaApiUnknownResponse):
            raise ResponseContractError(
                "unknown-response endpoint omitted its typed adapter observation"
            )
        expected_provider_authority = expected_nba_api_provider_authority()["authority_sha256"]
        if (
            observation.endpoint_id != contract.runtime_class_name
            or observation.endpoint_slug != contract.endpoint_slug
            or observation.provider_authority_sha256 != expected_provider_authority
            or observation.endpoint_contract_sha256 != endpoint_contract_sha256(contract)
            or observation.response_mode_authority_sha256 != response_contract.authority_sha256
        ):
            raise ResponseContractError(
                "unknown response observation differs from extraction authority"
            )
        if isinstance(source, NbaApiPayload) and (
            source.response_receipt_sha256 != observation.response_receipt_sha256
            or source.result_set_receipts != observation.result_set_receipts
        ):
            raise ResponseContractError(
                "unknown payload observation differs from its response receipt"
            )
        self._unknown_responses = (*self._unknown_responses, observation)
        return observation

    def _retain_live_lossless_landing(
        self,
        payloads: object,
        *,
        snapshot_at: datetime,
    ) -> None:
        landing = getattr(payloads, "live_lossless_landing", None)
        if landing is None:
            return
        if not isinstance(landing, NbaApiLiveLosslessLanding):
            raise ResponseContractError("live payload returned an invalid lossless landing")
        self._live_lossless_landings = (
            *self._live_lossless_landings,
            landing.bind_snapshot(snapshot_at),
        )

    def capture_receipt_snapshot(self):
        """Return the immutable response-receipt ledger for this extractor attempt."""

        if self._capture_contract is None:
            return None
        return self._capture_contract.receipt_snapshot()

    def raw_request_capture_snapshot(self) -> RawRequestCaptureSnapshotV2 | None:
        """Return immutable pre-transaction public evidence for this attempt."""

        if self._raw_request_capture_sink is None:
            return None
        return self._raw_request_capture_sink.snapshot()

    def _mark_raw_request_downstream_incomplete(
        self,
        exc: BaseException,
        *,
        receipt_sha256: str | None = None,
    ) -> None:
        """Fail one exact pending public response after parser success."""

        if self._raw_request_capture_sink is None:
            return
        self._raw_request_capture_sink.mark_downstream_incomplete(
            failure_class=classify_exception(exc),
            root_exception_class=safe_root_error_type(exc),
            receipt_sha256=receipt_sha256,
        )

    def _fetch_nba_api_payload(self, endpoint_cls: type, **kwargs: Any) -> NbaApiPayload:
        """Fetch an owned raw stats payload through the same capture boundary."""

        if not getattr(self, "_runner_attempt_active", False):
            self._unknown_responses = ()
        kwargs = _forward_explicit_provider_parameters(
            endpoint_cls,
            kwargs,
            self._logical_request_params,
        )
        self._inject_timeout(kwargs)
        payload = fetch_stats_payload(
            endpoint_cls,
            capture=self._stats_capture_contract(endpoint_cls),
            **kwargs,
        )
        try:
            self._retain_unknown_response(payload, endpoint_cls)
        except Exception as exc:
            self._mark_raw_request_downstream_incomplete(
                exc,
                receipt_sha256=payload.response_receipt_sha256,
            )
            raise
        return payload

    def _stats_capture_contract(self, endpoint_cls: type) -> NbaApiCaptureContract | None:
        """Bind capture to the exact pinned stats endpoint known at invocation."""

        if self._capture_contract is None:
            return None
        try:
            contract = pinned_endpoint_contract(endpoint_cls)
        except ValueError as exc:
            raise ResponseContractError(
                "stats extractor lacks pinned nbadb capture authority"
            ) from exc
        return self._capture_contract.for_endpoint_contract(endpoint_contract_sha256(contract))

    def _live_capture_contract(self, endpoint_cls: type) -> NbaApiCaptureContract | None:
        """Bind capture to the exact pinned live endpoint known at invocation."""

        if self._capture_contract is None:
            return None
        try:
            contract = pinned_live_endpoint_contract(endpoint_cls)
        except ValueError as exc:
            raise ResponseContractError(
                "live extractor lacks pinned nbadb capture authority"
            ) from exc
        return self._capture_contract.for_endpoint_contract(owned_contract_sha256(contract))

    def _validate(self, df: pl.DataFrame) -> pl.DataFrame:
        """Apply raw schema validation to extracted DataFrame.

        Looks up the schema for this endpoint in the raw schema registry and
        validates the DataFrame. Returns the validated DataFrame (may have
        columns stripped per schema config).

        If no schema is registered for this endpoint, validation is skipped.
        """
        schema_cls = get_raw_schema(self.endpoint_name)
        if schema_cls is None:
            return df

        try:
            validated = schema_cls.validate(df)
            logger.debug(f"{self.endpoint_name}: validation passed")
            return validated
        except Exception as exc:
            self._mark_raw_request_downstream_incomplete(exc)
            logger.error(f"{self.endpoint_name}: validation failed: {exc}")
            raise NbaDbValidationError(
                f"{self.endpoint_name}: raw schema validation failed"
            ) from exc

    def _inject_timeout(self, kwargs: dict[str, Any]) -> None:
        """Apply timeout override for nba_api endpoint calls.

        Per-endpoint overrides set by the runner take precedence over the
        global NBADB_REQUEST_TIMEOUT environment variable. NBADB_REQUEST_TIMEOUT_CAP
        can lower either value for hosted extraction profiles that need fail-fast
        endpoint calls.
        """
        explicit_timeout = kwargs.get("timeout")
        timeout_override: int | str | tuple[Any, Any] | None = explicit_timeout
        if timeout_override is None:
            timeout_override = self._request_timeout_override
        if timeout_override is None:
            timeout_override = os.getenv("NBADB_REQUEST_TIMEOUT")
        if timeout_override is None:
            return
        try:
            if isinstance(timeout_override, tuple):
                if len(timeout_override) != 2:
                    raise ValueError
                timeout_pair = (
                    float(timeout_override[0]),
                    float(timeout_override[1]),
                )
                if any(value <= 0 for value in timeout_pair):
                    raise ValueError
                timeout_value: int | tuple[float, float] = timeout_pair
            else:
                scalar_timeout = int(timeout_override)
                if scalar_timeout <= 0:
                    raise ValueError
                timeout_value = scalar_timeout
        except (TypeError, ValueError):
            logger.warning("invalid request timeout override={!r}; ignoring", timeout_override)
            return

        timeout_cap = os.getenv("NBADB_REQUEST_TIMEOUT_CAP")
        if timeout_cap is not None:
            try:
                timeout_cap_value = int(timeout_cap)
                if timeout_cap_value <= 0:
                    raise ValueError
                if isinstance(timeout_value, tuple):
                    timeout_value = (
                        min(timeout_value[0], float(timeout_cap_value)),
                        min(timeout_value[1], float(timeout_cap_value)),
                    )
                else:
                    timeout_value = min(timeout_value, timeout_cap_value)
            except (TypeError, ValueError):
                logger.warning("invalid request timeout cap={!r}; ignoring", timeout_cap)

        kwargs["timeout"] = timeout_value

    def _call_nba_api(self, endpoint_cls: type, **kwargs: Any) -> list[pl.DataFrame]:
        """Call nba_api endpoint and return all result sets as Polars DataFrames.

        Handles timeout injection, column snake_case normalization, and
        ``season_type`` column injection.  Shared by both single and
        multi-result helpers.
        """
        # Direct helper reuse treats each call as a new logical invocation.
        # Runner-owned attempts may contain more than one provider request, so
        # they retain every fallback observed within that one attempt.
        if not getattr(self, "_runner_attempt_active", False):
            self._lossless_fallbacks = ()
            self._unknown_responses = ()
        kwargs = _forward_explicit_provider_parameters(
            endpoint_cls,
            kwargs,
            self._logical_request_params,
        )
        self._inject_timeout(kwargs)
        packets = fetch_stats_packets(
            endpoint_cls,
            capture=self._stats_capture_contract(endpoint_cls),
            **kwargs,
        )
        receipt_candidates = {
            receipt
            for receipt in (
                *(packet.response_receipt_sha256 for packet in packets),
                getattr(
                    getattr(packets, "lossless_fallback", None),
                    "response_receipt_sha256",
                    None,
                ),
                getattr(
                    getattr(packets, "unknown_response", None),
                    "response_receipt_sha256",
                    None,
                ),
            )
            if receipt is not None
        }
        receipt_sha256 = next(iter(receipt_candidates)) if len(receipt_candidates) == 1 else None
        try:
            return self._convert_nba_api_packets(endpoint_cls, packets, kwargs)
        except Exception as exc:
            self._mark_raw_request_downstream_incomplete(
                exc,
                receipt_sha256=receipt_sha256,
            )
            raise

    def _convert_nba_api_packets(
        self,
        endpoint_cls: type,
        packets: Any,
        kwargs: Mapping[str, Any],
    ) -> list[pl.DataFrame]:
        """Convert one successfully parsed response without losing its receipt."""

        fallback = getattr(packets, "lossless_fallback", None)
        unknown_response = getattr(packets, "unknown_response", None)
        if unknown_response is not None and (fallback is not None or bool(packets)):
            raise ResponseContractError(
                "unknown response observation cannot carry fixed result packets"
            )
        self._retain_unknown_response(packets, endpoint_cls)

        if fallback is not None:
            if not isinstance(fallback, NbaApiLosslessFallback):
                raise ResponseContractError(
                    "stats packet batch returned an invalid lossless fallback"
                )
            self._lossless_fallbacks = (*self._lossless_fallbacks, fallback)

        converted_by_index: dict[int, pl.DataFrame] = {}
        endpoint_cls_name = getattr(endpoint_cls, "__name__", endpoint_cls.__class__.__name__)
        for packet in packets:
            result_set_index = packet.canonical_index
            df = packet.frame
            used_columns: set[str] = set()
            rename_map: dict[str, str] = {}
            for column_name in df.columns:
                canonical_name = _canonicalize_endpoint_column_name(
                    endpoint_cls_name,
                    result_set_index,
                    column_name,
                )
                if canonical_name in used_columns:
                    canonical_name = _to_snake_case(column_name)
                used_columns.add(canonical_name)
                rename_map[column_name] = canonical_name
            df = df.rename(rename_map)
            df = _inject_request_scope_columns(df, kwargs)
            if result_set_index in converted_by_index:
                raise ResponseContractError(
                    "stats packet batch returned duplicate canonical result indexes"
                )
            converted_by_index[result_set_index] = df

        if fallback is None:
            return [converted_by_index[index] for index in sorted(converted_by_index)]

        # Shape drift can remove a packet before or between safe packets. Keep
        # list positions aligned to canonical result indexes so multi-result
        # callers cannot route a later safe packet into the wrong wide table.
        result_count = max(
            fallback.expected_result_set_count,
            max(converted_by_index, default=-1) + 1,
        )
        return [converted_by_index.get(index, pl.DataFrame()) for index in range(result_count)]

    def _from_nba_api(self, endpoint_cls: type, **kwargs: Any) -> pl.DataFrame:
        """Call nba_api endpoint and convert to Polars DataFrame.

        The owned provider boundary returns ordered Polars packets with source
        columns. We normalize those names at this boundary and inject a
        ``season_type`` column when the endpoint was queried with one.
        Applies raw schema validation before returning.
        """
        converted = self._call_nba_api(endpoint_cls, **kwargs)
        if not converted:
            logger.warning(f"{self.endpoint_name}: no data frames returned")
            return pl.DataFrame()
        if self._lossless_fallbacks and converted[0].width == 0:
            # The fallback is the validated representation of this successful
            # response. Do not force a missing/drifted wide packet through the
            # pinned raw schema and turn preserved provider data into failure.
            return converted[0]
        return self._validate(converted[0])

    def _from_nba_api_multi(self, endpoint_cls: type, **kwargs: Any) -> list[pl.DataFrame]:
        """Call nba_api endpoint returning multiple result sets.

        Injects ``season_type`` column into each result set when applicable.
        Generic validation is intentionally skipped here because multi-result
        endpoints often return heterogeneous packets that need packet-aware
        schema selection.
        """
        return self._call_nba_api(endpoint_cls, **kwargs)

    @staticmethod
    def _live_payload_to_frame(
        payload: Any,
        *,
        field_projections: Mapping[str, str] | None = None,
    ) -> pl.DataFrame:
        return live_payload_to_frame(payload, field_projections=field_projections)

    @staticmethod
    def _apply_live_snapshot_contract(
        df: pl.DataFrame,
        *,
        source_endpoint: str,
        natural_keys: tuple[str, ...],
        snapshot_at: datetime,
        params: dict[str, Any],
    ) -> pl.DataFrame:
        return apply_live_snapshot_contract(
            df,
            source_endpoint=source_endpoint,
            natural_keys=natural_keys,
            snapshot_at=snapshot_at,
            params=params,
        )

    def _from_nba_live(
        self,
        endpoint_cls: type,
        attr: str,
        *,
        source_endpoint: str,
        natural_keys: tuple[str, ...],
        **kwargs: Any,
    ) -> pl.DataFrame:
        """Call nba_api live endpoint and convert a single dataset to Polars.

        Applies raw schema validation using source_endpoint as the lookup key.
        """
        if not getattr(self, "_runner_attempt_active", False):
            self._live_lossless_landings = ()
        snapshot_at = _coerce_snapshot_at(kwargs.pop("snapshot_at", None))
        self._inject_timeout(kwargs)
        from nbadb.extract.live.endpoints import LIVE_PACKET_CONTRACTS

        packet = next(
            contract
            for contract in LIVE_PACKET_CONTRACTS
            if contract.source_endpoint == source_endpoint
        )
        payloads = fetch_live_payloads(
            endpoint_cls,
            {attr: packet.result_set_name},
            capture=self._live_capture_contract(endpoint_cls),
            allow_additive_drift=True,
            **kwargs,
        )
        try:
            self._retain_live_lossless_landing(payloads, snapshot_at=snapshot_at)
            frame = self._live_payload_to_frame(payloads[attr])
            frame = self._apply_live_snapshot_contract(
                frame,
                source_endpoint=source_endpoint,
                natural_keys=natural_keys,
                snapshot_at=snapshot_at,
                params=kwargs,
            )
        except Exception as exc:
            self._mark_raw_request_downstream_incomplete(
                exc,
                receipt_sha256=getattr(payloads, "response_receipt_sha256", None),
            )
            raise
        # Validate using source_endpoint as the schema lookup key
        try:
            frame = normalize_live_landing_frame(frame, source_endpoint=source_endpoint)
        except Exception as exc:
            self._mark_raw_request_downstream_incomplete(
                exc,
                receipt_sha256=getattr(payloads, "response_receipt_sha256", None),
            )
            logger.error(f"{source_endpoint}: live validation failed: {exc}")
            raise NbaDbValidationError(f"{source_endpoint}: raw schema validation failed") from exc
        return frame

    def _from_nba_live_multi(
        self,
        endpoint_cls: type,
        specs: list[tuple[str, str, tuple[str, ...]]],
        *,
        field_projections_by_source: Mapping[str, Mapping[str, str]] | None = None,
        **kwargs: Any,
    ) -> list[pl.DataFrame]:
        """Call nba_api live endpoint and convert multiple datasets to Polars.

        Applies raw schema validation to each dataset using source_endpoint as the lookup key.
        """
        if not getattr(self, "_runner_attempt_active", False):
            self._live_lossless_landings = ()
        snapshot_at = _coerce_snapshot_at(kwargs.pop("snapshot_at", None))
        self._inject_timeout(kwargs)
        from nbadb.extract.live.endpoints import LIVE_PACKET_CONTRACTS

        result_sets_by_attr = {
            attr: next(
                contract.result_set_name
                for contract in LIVE_PACKET_CONTRACTS
                if contract.source_endpoint == source_endpoint
            )
            for attr, source_endpoint, _natural_keys in specs
        }
        payloads = fetch_live_payloads(
            endpoint_cls,
            result_sets_by_attr,
            capture=self._live_capture_contract(endpoint_cls),
            allow_additive_drift=True,
            **kwargs,
        )
        try:
            self._retain_live_lossless_landing(payloads, snapshot_at=snapshot_at)
        except Exception as exc:
            self._mark_raw_request_downstream_incomplete(
                exc,
                receipt_sha256=getattr(payloads, "response_receipt_sha256", None),
            )
            raise
        frames: list[pl.DataFrame] = []
        for attr, source_endpoint, natural_keys in specs:
            try:
                frame = self._live_payload_to_frame(
                    payloads[attr],
                    field_projections=(field_projections_by_source or {}).get(source_endpoint),
                )
                frame = self._apply_live_snapshot_contract(
                    frame,
                    source_endpoint=source_endpoint,
                    natural_keys=natural_keys,
                    snapshot_at=snapshot_at,
                    params=kwargs,
                )
            except Exception as exc:
                self._mark_raw_request_downstream_incomplete(
                    exc,
                    receipt_sha256=getattr(payloads, "response_receipt_sha256", None),
                )
                raise
            # Validate using source_endpoint as the schema lookup key
            try:
                frame = normalize_live_landing_frame(frame, source_endpoint=source_endpoint)
            except Exception as exc:
                self._mark_raw_request_downstream_incomplete(
                    exc,
                    receipt_sha256=getattr(payloads, "response_receipt_sha256", None),
                )
                logger.error(f"{source_endpoint}: live validation failed: {exc}")
                raise NbaDbValidationError(
                    f"{source_endpoint}: raw schema validation failed"
                ) from exc
            frames.append(frame)
        return frames
