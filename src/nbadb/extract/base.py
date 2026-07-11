from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, time
from typing import Any, ClassVar

import pandas as pd
import polars as pl
from loguru import logger

from nbadb.core.errors import ValidationError as NbaDbValidationError
from nbadb.core.extraction_failures import is_transport_error
from nbadb.extract.raw_schema_registry import get_raw_schema

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
_UPPER_TOKEN_RE = re.compile(r"^[A-Z0-9_]+$")

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
        "passes": "pass_",
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


def _extract_season_type(kwargs: dict[str, Any]) -> str | None:
    """Extract the season_type value from nba_api kwargs.

    Returns the season_type string if found, None otherwise (e.g. game-level
    endpoints that don't use season_type).
    """
    for key in _SEASON_TYPE_KEYS:
        if key in kwargs:
            val = kwargs[key]
            return val if val else None
    return None


def _to_snake_case(name: str) -> str:
    """Convert any column name style to snake_case.

    Handles UPPER_SNAKE_CASE (e.g., GAME_ID -> game_id),
    all-uppercase nba_api stat shorthands (e.g., FG3M -> fg3m),
    camelCase (e.g., gameId -> game_id), and mixed cases.
    """
    if _UPPER_TOKEN_RE.fullmatch(name):
        return name.lower()
    return _CAMEL_RE.sub(r"\1_\2", name).lower()


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


def _safe_from_pandas(pdf: Any) -> pl.DataFrame:
    """Convert pandas DataFrame to Polars, handling mixed-type columns.

    nba_api responses sometimes contain columns with mixed types (e.g.,
    int and None/str) that crash Arrow conversion. Falls back to coercing
    object-dtype columns to str, but logs which columns were affected.
    """
    try:
        return pl.from_pandas(pdf, nan_to_null=True, include_index=False)
    except (TypeError, ValueError, RuntimeError):
        coerced: list[str] = []
        for col in pdf.columns:
            if pdf[col].dtype == object:
                try:
                    pdf[col] = pd.to_numeric(pdf[col], errors="coerce")
                    coerced.append(col)
                except (ValueError, TypeError):
                    pdf[col] = pdf[col].astype(str)
                    coerced.append(col)
        if coerced:
            logger.warning(
                "mixed-type columns coerced during Arrow fallback: {}",
                ", ".join(coerced),
            )
        return pl.from_pandas(pdf, nan_to_null=True, include_index=False)


class BaseExtractor(ABC):
    endpoint_name: ClassVar[str]
    category: ClassVar[str] = "default"
    _request_timeout_override: int | None = None

    @abstractmethod
    async def extract(self, **params: Any) -> pl.DataFrame: ...

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
        if "timeout" in kwargs:
            return
        timeout_override: int | str | None = self._request_timeout_override
        if timeout_override is None:
            timeout_override = os.getenv("NBADB_REQUEST_TIMEOUT")
        if timeout_override is None:
            return
        try:
            timeout_value = int(timeout_override)
            if timeout_value <= 0:
                raise ValueError
        except (TypeError, ValueError):
            logger.warning("invalid request timeout override={!r}; ignoring", timeout_override)
            return

        timeout_cap = os.getenv("NBADB_REQUEST_TIMEOUT_CAP")
        if timeout_cap is not None:
            try:
                timeout_cap_value = int(timeout_cap)
                if timeout_cap_value <= 0:
                    raise ValueError
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
        season_type = _extract_season_type(kwargs)
        self._inject_timeout(kwargs)
        result = endpoint_cls(**kwargs)
        dfs = result.get_data_frames()
        converted = []
        endpoint_cls_name = getattr(endpoint_cls, "__name__", endpoint_cls.__class__.__name__)
        for result_set_index, pdf in enumerate(dfs):
            df = _safe_from_pandas(pdf)
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
            if season_type and "season_type" not in df.columns:
                df = df.with_columns(pl.lit(season_type).alias("season_type"))
            converted.append(df)
        return converted

    def _from_nba_api(self, endpoint_cls: type, **kwargs: Any) -> pl.DataFrame:
        """Call nba_api endpoint and convert to Polars DataFrame.

        nba_api returns pandas DataFrames with UPPERCASE columns.
        We lowercase all column names at this boundary and inject a
        ``season_type`` column when the endpoint was queried with one.
        Applies raw schema validation before returning.
        """
        converted = self._call_nba_api(endpoint_cls, **kwargs)
        if not converted:
            logger.warning(f"{self.endpoint_name}: no data frames returned")
            return pl.DataFrame()
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
    def _live_payload_to_frame(payload: Any) -> pl.DataFrame:
        if hasattr(payload, "get_dict"):
            payload = payload.get_dict()
        elif hasattr(payload, "data"):
            payload = payload.data

        if payload is None:
            return pl.DataFrame()
        if isinstance(payload, dict):
            records: list[dict[str, Any]] = [payload]
        elif isinstance(payload, list):
            if not payload:
                return pl.DataFrame()
            if isinstance(payload[0], dict):
                records = payload
            else:
                return pl.DataFrame({"value": payload})
        else:
            return pl.DataFrame({"value": [payload]})

        serialized_records = [json.dumps(record, sort_keys=True, default=str) for record in records]
        df = pl.from_dicts(records)
        df = df.rename({c: _to_snake_case(c) for c in df.columns})
        return df.with_columns(pl.Series("payload_json", serialized_records))

    @staticmethod
    def _apply_live_snapshot_contract(
        df: pl.DataFrame,
        *,
        source_endpoint: str,
        natural_keys: tuple[str, ...],
        snapshot_at: datetime,
        params: dict[str, Any],
    ) -> pl.DataFrame:
        missing: list[str] = []
        expressions: list[pl.Expr] = []

        for key in natural_keys:
            if key in df.columns:
                continue
            if key in params:
                expressions.append(pl.lit(params[key]).alias(key))
                continue
            if df.is_empty():
                expressions.append(pl.lit(None).alias(key))
                continue
            missing.append(key)

        if missing:
            missing_keys = ", ".join(missing)
            raise NbaDbValidationError(
                f"{source_endpoint}: live payload missing required natural keys: {missing_keys}"
            )

        expressions.extend(
            [
                pl.lit(snapshot_at).alias("snapshot_at"),
                pl.lit(snapshot_at.date()).alias("snapshot_date"),
                pl.lit(source_endpoint).alias("source_endpoint"),
            ]
        )
        if "payload_json" not in df.columns:
            expressions.append(pl.lit(None).alias("payload_json"))
        return df.with_columns(expressions)

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
        snapshot_at = _coerce_snapshot_at(kwargs.pop("snapshot_at", None))
        self._inject_timeout(kwargs)
        result = endpoint_cls(**kwargs)
        dataset = getattr(result, attr, None)
        if dataset is None:
            logger.warning(f"{self.endpoint_name}: live dataset {attr!r} was not returned")
            frame = pl.DataFrame()
        else:
            frame = self._live_payload_to_frame(dataset)
        frame = self._apply_live_snapshot_contract(
            frame,
            source_endpoint=source_endpoint,
            natural_keys=natural_keys,
            snapshot_at=snapshot_at,
            params=kwargs,
        )
        # Validate using source_endpoint as the schema lookup key
        schema_cls = get_raw_schema(source_endpoint)
        if schema_cls is not None:
            try:
                frame = schema_cls.validate(frame)
            except Exception as exc:
                logger.error(f"{source_endpoint}: live validation failed: {exc}")
                raise NbaDbValidationError(
                    f"{source_endpoint}: raw schema validation failed"
                ) from exc
        return frame

    def _from_nba_live_multi(
        self,
        endpoint_cls: type,
        specs: list[tuple[str, str, tuple[str, ...]]],
        **kwargs: Any,
    ) -> list[pl.DataFrame]:
        """Call nba_api live endpoint and convert multiple datasets to Polars.

        Applies raw schema validation to each dataset using source_endpoint as the lookup key.
        """
        snapshot_at = _coerce_snapshot_at(kwargs.pop("snapshot_at", None))
        self._inject_timeout(kwargs)
        result = endpoint_cls(**kwargs)
        frames: list[pl.DataFrame] = []
        for attr, source_endpoint, natural_keys in specs:
            dataset = getattr(result, attr, None)
            if dataset is None:
                logger.warning(f"{self.endpoint_name}: live dataset {attr!r} was not returned")
                frame = pl.DataFrame()
            else:
                frame = self._live_payload_to_frame(dataset)
            frame = self._apply_live_snapshot_contract(
                frame,
                source_endpoint=source_endpoint,
                natural_keys=natural_keys,
                snapshot_at=snapshot_at,
                params=kwargs,
            )
            # Validate using source_endpoint as the schema lookup key
            schema_cls = get_raw_schema(source_endpoint)
            if schema_cls is not None:
                try:
                    frame = schema_cls.validate(frame)
                except Exception as exc:
                    logger.error(f"{source_endpoint}: live validation failed: {exc}")
                    raise NbaDbValidationError(
                        f"{source_endpoint}: raw schema validation failed"
                    ) from exc
            frames.append(frame)
        return frames
