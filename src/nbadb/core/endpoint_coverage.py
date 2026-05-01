from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import pkgutil
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from nbadb.orchestrate.extraction_contract import FULL_EXTRACTION_EXCLUSIONS_BY_ENDPOINT
from nbadb.orchestrate.staging_map import STAGING_MAP, StagingEntry
from nbadb.schemas.registry import _INPUT_SCHEMA_ALIASES

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet

_COVERAGE_KEYS = ("covered", "runtime_gap", "staging_only", "extractor_only", "source_only")
_SOURCE_KINDS = ("stats", "static", "live")
_ENDPOINT_ADEQUACY_ARTIFACT_KEYS = (
    "endpoint_adequacy_scorecard",
    "endpoint_adequacy_report",
)
_TRANSFORM_SEMANTICS = ("modeled", "passthrough")
_DOWNSTREAM_STATUS_KEYS = (
    "modeled",
    "passthrough_only",
    "compatibility_reference_only",
    "excluded",
    "unowned",
    "not_applicable",
)
_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE_2 = re.compile(r"([a-z0-9])([A-Z])")
_DEFAULT_HISTORICAL_START_SEASON = 1946
_HISTORICAL_PARAM_PATTERNS = {
    "season",
    "game",
    "player",
    "team",
    "player_season",
    "player_team_season",
    "team_season",
    "date",
}


class _StagingStatusDetail(TypedDict):
    staging_key: str
    downstream_status: str
    downstream_reasons: list[str]
    transform_outputs: list[str]


# Legacy/alternate extractor endpoint names mapped to canonical staging names.
_ENDPOINT_ALIASES: dict[str, str] = {
    "glalum_box_score_similarity_score": "gl_alum_box_score_similarity_score",
    "home_page_leaders": "homepage_leaders",
    "home_page_v2": "homepage_v2",
    "infographic_fan_duel_player": "infographic_fanduel_player",
    "iststandings": "ist_standings",
    "league_dash_player_bio_stats": "league_dash_player_bio",
    "league_hustle_stats_player": "league_hustle_player",
    "league_hustle_stats_team": "league_hustle_team",
    "player_career_by_college_rollup": "player_college_rollup",
    "player_dash_pt_defend": "player_dash_pt_shot_defend",
    "player_dashboard_by_clutch": "player_dashboard_clutch",
    "player_dashboard_by_game_splits": "player_dash_game_splits",
    "player_dashboard_by_general_splits": "player_dash_general_splits",
    "player_dashboard_by_last_n_games": "player_dash_last_n_games",
    "player_dashboard_by_last_ngames": "player_dash_last_n_games",
    "player_dashboard_by_shooting_splits": "player_dash_shooting_splits",
    "player_dashboard_by_team_performance": "player_dash_team_perf",
    "player_dashboard_by_year_over_year": "player_dash_yoy",
    "player_dashboard_game_splits": "player_dash_game_splits",
    "player_dashboard_general_splits": "player_dash_general_splits",
    "player_dashboard_last_n_games": "player_dash_last_n_games",
    "player_dashboard_shooting_splits": "player_dash_shooting_splits",
    "player_dashboard_team_performance": "player_dash_team_perf",
    "player_dashboard_year_over_year": "player_dash_yoy",
    "player_fantasy_profile_bar_graph": "player_fantasy_profile",
    "player_game_logs": "player_game_logs_v2",
    "player_next_n_games": "player_next_games",
    "player_next_ngames": "player_next_games",
    "player_game_streak_finder": "player_streak_finder",
    "shot_chart_lineup_detail": "shot_chart_lineup",
    "schedule_league_v2": "schedule",
    "schedule_league_v2_int": "schedule_int",
    "team_and_players_vs_players": "team_and_players_vs",
    "team_dashboard_by_general_splits": "team_dashboard_general_splits",
    "team_dashboard_by_shooting_splits": "team_dashboard_shooting_splits",
    "team_year_by_year_stats": "team_year_by_year",
    "win_probability_pbp": "win_probability",
}

_RUNTIME_CLASS_ALIASES: dict[str, str] = {
    "BoxScoreTraditionalV2": "BoxScoreTraditionalV3",
    "BoxScoreAdvancedV2": "BoxScoreAdvancedV3",
    "BoxScoreMiscV2": "BoxScoreMiscV3",
    "BoxScoreScoringV2": "BoxScoreScoringV3",
    "BoxScoreUsageV2": "BoxScoreUsageV3",
    "BoxScoreFourFactorsV2": "BoxScoreFourFactorsV3",
    "LeagueStandings": "LeagueStandingsV3",
    "PlayByPlay": "PlayByPlayV3",
    "TeamAndPlayersVs": "TeamAndPlayersVsPlayers",
}

_STATIC_SURFACE_ALIASES: dict[str, str] = {
    "static_players": "players",
    "static_teams": "teams",
}

_LIVE_SURFACE_ALIASES: dict[str, str] = {
    "live_box_score": "box_score",
    "live_odds": "odds",
    "live_play_by_play": "play_by_play",
    "live_score_board": "score_board",
}

_STATIC_SURFACE_ENDPOINT_NAMES: dict[str, str] = {
    value: key for key, value in _STATIC_SURFACE_ALIASES.items()
}

_LIVE_SURFACE_ENDPOINT_NAMES: dict[str, str] = {
    value: key for key, value in _LIVE_SURFACE_ALIASES.items()
}

_MODEL_EXCLUDED_STATS_ENDPOINTS: dict[str, str] = {
    "gl_alum_box_score_similarity_score": (
        "Exploratory similarity feed is retained for extraction completeness but is not "
        "promoted into the current analytical model."
    ),
    "play_by_play_v2": (
        "Legacy play-by-play source is retained for compatibility; downstream facts and "
        "bridges use the canonical play_by_play surface."
    ),
    "player_index": (
        "Supplemental roster index feed is retained for reference; dim_player is modeled "
        "from player_info."
    ),
    "video_details": (
        "Auxiliary video metadata is retained as a source-complete landing surface and is "
        "not promoted into the current analytical model."
    ),
    "video_details_asset": (
        "Auxiliary video asset metadata is retained as a source-complete landing surface "
        "and is not promoted into the current analytical model."
    ),
    "video_events": (
        "Auxiliary video event metadata is retained as a source-complete landing surface "
        "and is not promoted into the current analytical model."
    ),
    "video_status": (
        "Auxiliary video status metadata is retained as a source-complete landing surface "
        "and is not promoted into the current analytical model."
    ),
}

_COMPATIBILITY_REFERENCE_STATS_ENDPOINTS: dict[str, str] = {
    "gl_alum_box_score_similarity_score": (
        "Exploratory similarity feed is retained as a compatibility/reference surface and "
        "is not promoted into the analytical model."
    ),
    "play_by_play_v2": (
        "Legacy play-by-play source is retained for compatibility; the analytical model "
        "uses the canonical play_by_play surface."
    ),
    "player_index": (
        "Supplemental roster index feed is retained for reference; the analytical model "
        "uses canonical player dimensions."
    ),
    "video_details": (
        "Auxiliary video metadata is retained as a compatibility/reference surface and is "
        "not promoted into the analytical model."
    ),
    "video_details_asset": (
        "Auxiliary video asset metadata is retained as a compatibility/reference surface "
        "and is not promoted into the analytical model."
    ),
    "video_events": (
        "Auxiliary video event metadata is retained as a compatibility/reference surface "
        "and is not promoted into the analytical model."
    ),
    "video_status": (
        "Auxiliary video status metadata is retained as a compatibility/reference surface "
        "and is not promoted into the analytical model."
    ),
}

_MODEL_EXCLUDED_STAGING_KEYS: dict[str, str] = {
    "stg_hustle_stats_available": (
        "Availability-only hustle flag is retained for landing completeness; modeled hustle "
        "facts use the actual box-score stat packets."
    ),
    "stg_play_by_play_video_available": (
        "Auxiliary play-by-play video flag is retained for landing completeness and is not "
        "promoted beyond the canonical play-by-play/game-context model."
    ),
    "stg_schedule_int_broadcaster": (
        "ScheduleLeagueV2Int broadcaster directory is retained for packet completeness; "
        "game-level schedule outputs already carry the modeled broadcast context."
    ),
    "stg_pvp_player_info": (
        "Duplicate player bio packet; the analytical model uses the canonical "
        "player dimensions instead of matchup-scoped profile copies."
    ),
    "stg_pvp_vs_player_info": (
        "Duplicate opposing-player bio packet; the analytical model uses the canonical "
        "player dimensions instead of matchup-scoped profile copies."
    ),
    "stg_scoreboard_win_probability": (
        "Scoreboard win-probability snapshot is retained for landing completeness; the "
        "analytical model uses the canonical win_probability surface."
    ),
    "stg_team_available_seasons": (
        "Reference-only season-availability list is retained for completeness; modeled team "
        "history and season facts already cover the analytical use cases."
    ),
}

_COMPATIBILITY_REFERENCE_STAGING_KEYS: dict[str, str] = {
    "stg_pvp_player_info": (
        "Duplicate player bio packet is retained as a compatibility/reference surface; the "
        "analytical model uses canonical player dimensions."
    ),
    "stg_pvp_vs_player_info": (
        "Duplicate opposing-player bio packet is retained as a compatibility/reference "
        "surface; the analytical model uses canonical player dimensions."
    ),
    "stg_scoreboard_win_probability": (
        "Scoreboard win-probability snapshot is retained as a compatibility/reference "
        "surface; the analytical model uses the canonical win_probability surface."
    ),
    "stg_team_available_seasons": (
        "Reference-only season-availability list is retained as a compatibility/reference "
        "surface; modeled team history and season facts cover the analytical use cases."
    ),
}


def _ownership_override_for_endpoint(endpoint_name: str) -> tuple[str | None, str | None]:
    reason = _COMPATIBILITY_REFERENCE_STATS_ENDPOINTS.get(endpoint_name)
    if reason is not None:
        return "compatibility_reference_only", reason
    reason = _MODEL_EXCLUDED_STATS_ENDPOINTS.get(endpoint_name)
    if reason is not None:
        return "excluded", reason
    return None, None


def _ownership_override_for_staging_key(staging_key: str) -> tuple[str | None, str | None]:
    reason = _COMPATIBILITY_REFERENCE_STAGING_KEYS.get(staging_key)
    if reason is not None:
        return "compatibility_reference_only", reason
    reason = _MODEL_EXCLUDED_STAGING_KEYS.get(staging_key)
    if reason is not None:
        return "excluded", reason
    return None, None


def _to_snake_case(name: str) -> str:
    return _CAMEL_RE.sub(r"\1_\2", name).lower()


def _camel_to_snake(name: str) -> str:
    interim = _CAMEL_RE_1.sub(r"\1_\2", name)
    return _CAMEL_RE_2.sub(r"\1_\2", interim).lower()


def _runtime_class_to_surface_name(name: str, known_surfaces: set[str] | None = None) -> str:
    versioned_name = _to_snake_case(name)
    unversioned_name = re.sub(r"_v\d+$", "", versioned_name)
    candidates = [
        _ENDPOINT_ALIASES.get(versioned_name, versioned_name),
        versioned_name,
        _ENDPOINT_ALIASES.get(unversioned_name, unversioned_name),
        unversioned_name,
    ]
    if known_surfaces is not None:
        for candidate in candidates:
            if candidate in known_surfaces:
                return candidate
    return candidates[0]


class EndpointCoverageGenerator:
    def __init__(
        self,
        project_root: Path | None = None,
        staging_entries: list[StagingEntry] | None = None,
    ) -> None:
        self.project_root = Path(project_root) if project_root is not None else Path.cwd()
        self.staging_entries = (
            list(staging_entries) if staging_entries is not None else list(STAGING_MAP)
        )
        self.extract_stats_dir = self.project_root / "src" / "nbadb" / "extract" / "stats"
        self.extract_static_dir = self.project_root / "src" / "nbadb" / "extract" / "static"
        self.extract_live_dir = self.project_root / "src" / "nbadb" / "extract" / "live"

    @staticmethod
    def _constant_string(value: ast.AST) -> str | None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        return None

    @classmethod
    def _constant_string_list(cls, value: ast.AST) -> list[str]:
        if not isinstance(value, (ast.List, ast.Tuple)):
            return []
        values: list[str] = []
        for element in value.elts:
            constant = cls._constant_string(element)
            if constant is not None:
                values.append(constant)
        return values

    @staticmethod
    def _call_name(value: ast.AST) -> str | None:
        if isinstance(value, ast.Name):
            return value.id
        if isinstance(value, ast.Attribute):
            return value.attr
        return None

    @classmethod
    def _generated_transform_signature(
        cls,
        value: ast.AST,
    ) -> tuple[str, list[str], str] | None:
        if not isinstance(value, ast.Call):
            return None

        call_name = cls._call_name(value.func)
        target_call = value
        if (
            call_name == "_mark_live_snapshot"
            and value.args
            and isinstance(value.args[0], ast.Call)
        ):
            target_call = value.args[0]
            call_name = cls._call_name(target_call.func)

        if call_name == "make_passthrough" and len(target_call.args) >= 2:
            output_table = cls._constant_string(target_call.args[0])
            dependency = cls._constant_string(target_call.args[1])
            if output_table is not None and dependency is not None:
                return output_table, [dependency], "passthrough"

        if call_name == "make_union" and len(target_call.args) >= 3:
            output_table = cls._constant_string(target_call.args[0])
            branches = target_call.args[2]
            dependencies: list[str] = []
            if isinstance(branches, ast.Dict):
                for branch_value in branches.values:
                    dependency = cls._constant_string(branch_value)
                    if dependency is not None:
                        dependencies.append(dependency)
            if output_table is not None and dependencies:
                return output_table, dependencies, "passthrough"

        return None

    @staticmethod
    def _merge_transform_semantics(current: str | None, new: str) -> str:
        if current == "modeled" or new == "modeled":
            return "modeled"
        return "passthrough"

    @staticmethod
    def _normalize_sql(sql: str) -> str:
        return re.sub(r"\s+", " ", sql.strip().rstrip(";")).strip().lower()

    @classmethod
    def _class_transform_semantics(cls, depends_on: list[str], sql: str | None) -> str:
        if not depends_on or not sql:
            return "modeled"

        normalized_sql = cls._normalize_sql(sql)
        if len(depends_on) == 1 and normalized_sql == f"select * from {depends_on[0].lower()}":
            return "passthrough"

        if "union all by name" not in normalized_sql:
            return "modeled"
        if any(token in normalized_sql for token in (" join ", " where ", " group by ", " with ")):
            return "modeled"
        if not all(f" from {dependency.lower()}" in normalized_sql for dependency in depends_on):
            return "modeled"
        if "select * from " in normalized_sql or "select *, " in normalized_sql:
            return "passthrough"
        return "modeled"

    @staticmethod
    def _table_name_from_schema_class_name(class_name: str) -> str:
        name = class_name.removesuffix("Schema").removesuffix("Model")
        return _camel_to_snake(name)

    @staticmethod
    def _table_family(table_name: str) -> str:
        if table_name.startswith("dim_"):
            return "dimensions"
        if table_name.startswith("bridge_"):
            return "bridges"
        if table_name.startswith("fact_"):
            return "facts"
        if table_name.startswith("agg_"):
            return "derived"
        if table_name.startswith("analytics_"):
            return "analytics"
        return "other"

    @classmethod
    def _table_family_breakdown(cls, table_names: set[str] | list[str]) -> dict[str, int]:
        breakdown: dict[str, int] = defaultdict(int)
        for table_name in sorted(table_names):
            breakdown[cls._table_family(table_name)] += 1
        return dict(sorted(breakdown.items()))

    @staticmethod
    def _collect_runtime_refs(
        node: ast.AST,
        imported_runtime_names: set[str] | None = None,
    ) -> set[str]:
        refs: set[str] = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if (
                imported_runtime_names is not None
                and isinstance(child.func, ast.Name)
                and child.func.id in imported_runtime_names
            ):
                refs.add(child.func.id)
                continue
            if isinstance(child.func, ast.Attribute):
                if child.func.attr not in {
                    "_call_nba_api",
                    "_call_nba_api_multi",
                    "_from_nba_api",
                    "_from_nba_api_multi",
                    "_from_nba_live",
                    "_from_nba_live_multi",
                }:
                    continue
                if not child.args:
                    continue
                first_arg = child.args[0]
                if isinstance(first_arg, ast.Name):
                    refs.add(first_arg.id)
                elif isinstance(first_arg, ast.Attribute):
                    refs.add(first_arg.attr)
                continue

            if not isinstance(child.func, ast.Name):
                continue
            if not child.func.id.startswith("_extract_"):
                continue
            if len(child.args) < 2:
                continue
            endpoint_arg = child.args[1]
            if isinstance(endpoint_arg, ast.Name):
                refs.add(endpoint_arg.id)
            elif isinstance(endpoint_arg, ast.Attribute):
                refs.add(endpoint_arg.attr)
        return refs

    @staticmethod
    def _module_runtime_imports(tree: ast.Module) -> set[str]:
        runtime_names: set[str] = set()
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if not module.startswith("nba_api.stats.endpoints"):
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                runtime_names.add(alias.asname or alias.name)
        return runtime_names

    def _extractor_metadata(self, extract_dir: Path) -> list[tuple[str, set[str]]]:
        metadata: list[tuple[str, set[str]]] = []
        if not extract_dir.exists():
            return metadata

        for path in sorted(extract_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue

            imported_runtime_names = self._module_runtime_imports(tree)

            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                endpoint_name: str | None = None
                runtime_refs: set[str] = set()

                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name) and target.id == "endpoint_name":
                                endpoint_name = self._constant_string(stmt.value)
                    elif isinstance(stmt, ast.AnnAssign):
                        if isinstance(stmt.target, ast.Name) and stmt.target.id == "endpoint_name":
                            endpoint_name = (
                                self._constant_string(stmt.value) if stmt.value else None
                            )
                    elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        runtime_refs.update(
                            self._collect_runtime_refs(stmt, imported_runtime_names)
                        )

                if endpoint_name:
                    metadata.append((endpoint_name, runtime_refs))
        return metadata

    def _extractor_endpoint_map(self) -> dict[str, set[str]]:
        endpoint_map: dict[str, set[str]] = {}
        for endpoint_name, runtime_refs in self._extractor_metadata(self.extract_stats_dir):
            endpoint_map.setdefault(endpoint_name, set()).update(runtime_refs)

        normalized: dict[str, set[str]] = {}
        for endpoint_name, runtime_refs in endpoint_map.items():
            canonical = _ENDPOINT_ALIASES.get(endpoint_name, endpoint_name)
            normalized.setdefault(canonical, set()).update(runtime_refs)
        return normalized

    def _static_extractor_surfaces(self) -> set[str]:
        surfaces: set[str] = set()
        for endpoint_name, _ in self._extractor_metadata(self.extract_static_dir):
            surfaces.add(
                _STATIC_SURFACE_ALIASES.get(endpoint_name, endpoint_name.removeprefix("static_"))
            )
        return surfaces

    def _live_extractor_surfaces(self) -> set[str]:
        surfaces: set[str] = set()
        for endpoint_name, runtime_refs in self._extractor_metadata(self.extract_live_dir):
            if runtime_refs:
                surfaces.update(_to_snake_case(ref) for ref in runtime_refs)
                continue
            surfaces.add(
                _LIVE_SURFACE_ALIASES.get(
                    endpoint_name,
                    endpoint_name.removeprefix("live_"),
                )
            )
        return surfaces

    def _transform_catalog(self) -> tuple[dict[str, set[str]], set[str], dict[str, str]]:
        output_map: dict[str, set[str]] = defaultdict(set)
        output_tables: set[str] = set()
        output_semantics: dict[str, str] = {}
        transform_root = self.project_root / "src" / "nbadb" / "transform"
        for subdir in ("dimensions", "facts", "derived", "views", "live"):
            current_dir = transform_root / subdir
            if not current_dir.exists():
                continue
            for path in sorted(current_dir.glob("*.py")):
                if path.name == "__init__.py":
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except (OSError, SyntaxError):
                    continue

                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        output_table: str | None = None
                        depends_on: list[str] = []
                        sql_text: str | None = None

                        for stmt in node.body:
                            if isinstance(stmt, ast.Assign):
                                for target in stmt.targets:
                                    if isinstance(target, ast.Name) and target.id == "output_table":
                                        output_table = self._constant_string(stmt.value)
                                    elif isinstance(target, ast.Name) and target.id == "depends_on":
                                        depends_on = self._constant_string_list(stmt.value)
                                    elif isinstance(target, ast.Name) and target.id == "_SQL":
                                        sql_text = self._constant_string(stmt.value)
                            elif isinstance(stmt, ast.AnnAssign):
                                if (
                                    isinstance(stmt.target, ast.Name)
                                    and stmt.target.id == "output_table"
                                ):
                                    output_table = (
                                        self._constant_string(stmt.value) if stmt.value else None
                                    )
                                elif (
                                    isinstance(stmt.target, ast.Name)
                                    and stmt.target.id == "depends_on"
                                ):
                                    depends_on = (
                                        self._constant_string_list(stmt.value) if stmt.value else []
                                    )
                                elif isinstance(stmt.target, ast.Name) and stmt.target.id == "_SQL":
                                    sql_text = (
                                        self._constant_string(stmt.value) if stmt.value else None
                                    )

                        if output_table is None:
                            continue
                        output_tables.add(output_table)
                        semantics = self._class_transform_semantics(depends_on, sql_text)
                        output_semantics[output_table] = self._merge_transform_semantics(
                            output_semantics.get(output_table),
                            semantics,
                        )
                        for dependency in depends_on:
                            output_map[dependency].add(output_table)
                        continue

                    if isinstance(node, ast.Assign):
                        signature = self._generated_transform_signature(node.value)
                        if signature is None:
                            continue
                        output_table, dependencies, semantics = signature
                        output_tables.add(output_table)
                        output_semantics[output_table] = self._merge_transform_semantics(
                            output_semantics.get(output_table),
                            semantics,
                        )
                        for dependency in dependencies:
                            output_map[dependency].add(output_table)
        return dict(output_map), output_tables, output_semantics

    def _star_schema_tables(self) -> set[str]:
        schema_dir = self.project_root / "src" / "nbadb" / "schemas" / "star"
        if not schema_dir.exists():
            return set()

        schema_tables: set[str] = set()
        for path in sorted(schema_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue

            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if node.name.startswith("_"):
                    continue
                if not node.name.endswith(("Schema", "Model")):
                    continue
                schema_tables.add(self._table_name_from_schema_class_name(node.name))
        return schema_tables

    def _schema_tables(
        self,
        *,
        schema_subdir: str,
        class_prefix: str,
        table_prefix: str,
    ) -> set[str]:
        schema_dir = self.project_root / "src" / "nbadb" / "schemas" / schema_subdir
        if not schema_dir.exists():
            return set()

        schema_tables: set[str] = set()
        for path in sorted(schema_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue

            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if node.name.startswith("_"):
                    continue
                if not node.name.endswith(("Schema", "Model")):
                    continue
                if class_prefix and not node.name.startswith(class_prefix):
                    continue
                stem = node.name.removesuffix("Schema").removesuffix("Model")
                if class_prefix:
                    stem = stem.removeprefix(class_prefix)
                schema_tables.add(f"{table_prefix}{_camel_to_snake(stem)}")
        return schema_tables

    def _staging_schema_tables(self) -> set[str]:
        return self._schema_tables(
            schema_subdir="staging",
            class_prefix="Staging",
            table_prefix="stg_",
        )

    def _raw_schema_tables(self) -> set[str]:
        return self._schema_tables(
            schema_subdir="raw",
            class_prefix="Raw",
            table_prefix="raw_",
        )

    @staticmethod
    def _input_schema_present(
        table_name: str,
        *,
        staging_schema_tables: set[str],
        raw_schema_tables: set[str],
    ) -> bool:
        if table_name in staging_schema_tables:
            return True
        alias = _INPUT_SCHEMA_ALIASES.get(table_name)
        if alias is None:
            return False
        return alias in staging_schema_tables or alias in raw_schema_tables

    @staticmethod
    def _discover_runtime_endpoint_classes() -> tuple[set[str], str]:
        try:
            import nba_api
            from nba_api.stats import endpoints
        except Exception:
            return set(), "unknown"

        classes: set[str] = set()
        for name in dir(endpoints):
            if name.startswith("_") or name == "Endpoint":
                continue
            obj = getattr(endpoints, name)
            if isinstance(obj, type):
                classes.add(name)

        package_path = getattr(endpoints, "__path__", None)
        if package_path is not None:
            for module_info in pkgutil.iter_modules(package_path):
                try:
                    module = importlib.import_module(f"{endpoints.__name__}.{module_info.name}")
                except Exception:
                    continue
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if obj.__module__ != module.__name__:
                        continue
                    if name.startswith("_") or name == "Endpoint":
                        continue
                    classes.add(name)
        return classes, getattr(nba_api, "__version__", "unknown")

    @staticmethod
    def _normalize_runtime_classes(runtime_classes: set[str]) -> set[str]:
        normalized = set(runtime_classes)
        for alias, canonical in _RUNTIME_CLASS_ALIASES.items():
            if alias in runtime_classes:
                normalized.add(canonical)
        return normalized

    @staticmethod
    def _discover_runtime_static_surfaces() -> set[str]:
        try:
            static_pkg = importlib.import_module("nba_api.stats.static")
        except Exception:
            return set()

        package_path = getattr(static_pkg, "__path__", None)
        if package_path is None:
            return set()
        return {module.name for module in pkgutil.iter_modules(package_path)}

    @staticmethod
    def _discover_runtime_live_endpoint_classes() -> set[str]:
        try:
            from nba_api.live.nba import endpoints as live_endpoints
        except Exception:
            return set()

        classes: set[str] = set()
        for name in dir(live_endpoints):
            if name.startswith("_"):
                continue
            obj = getattr(live_endpoints, name)
            if isinstance(obj, type):
                classes.add(_to_snake_case(name))
        return classes

    @staticmethod
    def _resolve_endpoint_source_kind(
        endpoint_name: str,
        rows: list[dict[str, Any]],
    ) -> str:
        if endpoint_name in _STATIC_SURFACE_ALIASES:
            return "static"
        if endpoint_name in _LIVE_SURFACE_ALIASES:
            return "live"

        source_kinds = {str(row["source_kind"]) for row in rows}
        if "live" in source_kinds:
            return "live"
        if "static" in source_kinds:
            return "static"
        return "stats"

    @staticmethod
    def _execution_semantics(source_kind: str, param_patterns: AbstractSet[str]) -> str:
        pattern_set = {str(pattern) for pattern in param_patterns}
        if source_kind == "live":
            return "live_snapshot"
        if pattern_set and pattern_set <= {"static"}:
            return "reference_snapshot"
        return "historical_backfill"

    @staticmethod
    def _season_type_contract_status(
        entries: list[StagingEntry],
        execution_semantics: str,
    ) -> str:
        if execution_semantics != "historical_backfill":
            return "not_applicable"
        if not entries:
            return "untracked"

        capabilities = {
            str(entry.season_type_capability)
            for entry in entries
            if entry.season_type_capability is not None
        }
        if not capabilities:
            return "untracked"
        if len(capabilities) == 1:
            return next(iter(capabilities))
        return "mixed"

    @staticmethod
    def _declared_supported_season_types(entries: list[StagingEntry]) -> list[str]:
        declared: list[str] = []
        for entry in entries:
            for season_type in getattr(entry, "supported_season_types", ()) or ():
                value = str(season_type)
                if value not in declared:
                    declared.append(value)
        return declared

    @staticmethod
    def _staging_result_set_shape(entry: StagingEntry) -> str:
        if not entry.use_multi:
            return "single_result"
        if entry.result_set_index == 0:
            return "multi_result_primary"
        return "multi_result_secondary"

    @classmethod
    def _season_type_value_gaps(
        cls,
        entries: list[StagingEntry],
        execution_semantics: str,
    ) -> list[str]:
        if execution_semantics != "historical_backfill" or not entries:
            return []

        supported_entries = [
            entry for entry in entries if str(entry.season_type_capability) == "supported"
        ]
        if not supported_entries:
            return []

        value_gaps: list[str] = []
        declared_sets = {
            tuple(str(value) for value in (entry.supported_season_types or ()))
            for entry in supported_entries
            if entry.supported_season_types
        }
        if any(not entry.supported_season_types for entry in supported_entries):
            value_gaps.append("supported_season_types_missing")
        if len(declared_sets) > 1:
            value_gaps.append("supported_season_types_mixed")
        return sorted(value_gaps)

    @classmethod
    def _staging_downstream_status(
        cls,
        *,
        endpoint_name: str,
        staging_key: str,
        transform_outputs_by_staging: dict[str, set[str]],
        transform_semantics_by_output: dict[str, str],
    ) -> tuple[str, list[str], list[str]]:
        outputs = sorted(transform_outputs_by_staging.get(staging_key, set()))
        status, reason = _ownership_override_for_staging_key(staging_key)
        if status is None:
            status, reason = _ownership_override_for_endpoint(endpoint_name)
        if status == "compatibility_reference_only":
            return (
                status,
                outputs,
                [str(reason)],
            )
        if status == "excluded" and not outputs:
            return "excluded", outputs, [str(reason)]
        if not outputs:
            return "unowned", [], []

        if any(
            transform_semantics_by_output.get(output, "modeled") == "modeled" for output in outputs
        ):
            return "modeled", outputs, []
        return "passthrough_only", outputs, []

    @staticmethod
    def _endpoint_downstream_status(
        *,
        source_kind: str,
        staging_statuses: list[str],
    ) -> str:
        if source_kind != "stats":
            return "not_applicable"
        if not staging_statuses:
            return "not_applicable"
        if "modeled" in staging_statuses:
            return "modeled"
        if "passthrough_only" in staging_statuses:
            return "passthrough_only"
        if "compatibility_reference_only" in staging_statuses:
            return "compatibility_reference_only"
        if "excluded" in staging_statuses:
            return "excluded"
        if "unowned" in staging_statuses:
            return "unowned"
        return "not_applicable"

    @classmethod
    def _build_support_matrix(
        cls,
        *,
        matrix: list[dict[str, Any]],
        staging_entries_by_endpoint: dict[str, list[StagingEntry]],
        transform_outputs_by_staging: dict[str, set[str]],
        transform_semantics_by_output: dict[str, str],
        staging_schema_tables: set[str],
        raw_schema_tables: set[str],
        star_schema_tables: set[str],
    ) -> dict[str, Any]:
        rows_by_endpoint: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in matrix:
            rows_by_endpoint[str(row["endpoint_name"])].append(row)

        support_matrix: list[dict[str, Any]] = []
        contract_status_breakdown: dict[str, int] = defaultdict(int)
        downstream_status_breakdown: dict[str, int] = defaultdict(int)
        execution_semantics_breakdown: dict[str, int] = defaultdict(int)
        source_kind_breakdown: dict[str, int] = defaultdict(int)
        gap_breakdown: dict[str, int] = defaultdict(int)

        for endpoint_name in sorted(rows_by_endpoint):
            endpoint_rows = rows_by_endpoint[endpoint_name]
            source_kind = cls._resolve_endpoint_source_kind(endpoint_name, endpoint_rows)
            coverage_rows = [
                row for row in endpoint_rows if str(row["source_kind"]) == source_kind
            ] or endpoint_rows
            entries = staging_entries_by_endpoint.get(endpoint_name, [])
            param_patterns = {
                str(row["param_pattern"])
                for row in coverage_rows
                if str(row["param_pattern"]) not in {"extractor_only", "live", "not_applicable"}
            }
            if not param_patterns and entries:
                param_patterns = {entry.param_pattern for entry in entries}

            execution_semantics = cls._execution_semantics(source_kind, param_patterns)
            season_type_contract_status = cls._season_type_contract_status(
                entries, execution_semantics
            )
            declared_supported_season_types = cls._declared_supported_season_types(entries)
            season_type_value_gaps = cls._season_type_value_gaps(entries, execution_semantics)

            coverage_gaps = sorted(
                {
                    str(row["coverage_status"])
                    for row in coverage_rows
                    if str(row["coverage_status"]) != "covered"
                }
            )
            staging_keys = sorted(
                {entry.staging_key for entry in entries}
                | {str(key) for row in endpoint_rows for key in row["staging_keys"]}
            )
            staging_status_details: list[_StagingStatusDetail] = [
                {
                    "staging_key": entry.staging_key,
                    "downstream_status": status,
                    "downstream_reasons": reasons,
                    "transform_outputs": outputs,
                }
                for entry in sorted(
                    entries, key=lambda item: (item.staging_key, item.result_set_index)
                )
                for status, outputs, reasons in [
                    cls._staging_downstream_status(
                        endpoint_name=endpoint_name,
                        staging_key=entry.staging_key,
                        transform_outputs_by_staging=transform_outputs_by_staging,
                        transform_semantics_by_output=transform_semantics_by_output,
                    )
                ]
            ]
            downstream_status = cls._endpoint_downstream_status(
                source_kind=source_kind,
                staging_statuses=[detail["downstream_status"] for detail in staging_status_details],
            )
            downstream_reasons = sorted(
                {
                    reason
                    for detail in staging_status_details
                    for reason in detail["downstream_reasons"]
                }
            )
            transform_outputs = sorted(
                {
                    output
                    for staging_key in staging_keys
                    for output in transform_outputs_by_staging.get(staging_key, set())
                }
                | {str(output) for row in endpoint_rows for output in row["transform_outputs"]}
            )
            input_schema_missing_staging_keys = sorted(
                entry.staging_key
                for entry in entries
                if not cls._input_schema_present(
                    entry.staging_key,
                    staging_schema_tables=staging_schema_tables,
                    raw_schema_tables=raw_schema_tables,
                )
            )
            output_schema_missing_tables = sorted(
                table_name
                for table_name in transform_outputs
                if table_name not in star_schema_tables
            )

            support_windows = [
                {
                    "staging_key": entry.staging_key,
                    "param_pattern": entry.param_pattern,
                    "result_set_index": entry.result_set_index,
                    "min_season": entry.min_season,
                    "deprecated_after": entry.deprecated_after,
                    "season_type_capability": entry.season_type_capability,
                    "supported_season_types": list(entry.supported_season_types or ()),
                    "input_schema_present": cls._input_schema_present(
                        entry.staging_key,
                        staging_schema_tables=staging_schema_tables,
                        raw_schema_tables=raw_schema_tables,
                    ),
                    **{
                        "transform_outputs": next(
                            detail["transform_outputs"]
                            for detail in staging_status_details
                            if detail["staging_key"] == entry.staging_key
                        ),
                        "downstream_status": next(
                            detail["downstream_status"]
                            for detail in staging_status_details
                            if detail["staging_key"] == entry.staging_key
                        ),
                        "downstream_reasons": next(
                            detail["downstream_reasons"]
                            for detail in staging_status_details
                            if detail["staging_key"] == entry.staging_key
                        ),
                    },
                }
                for entry in sorted(
                    entries, key=lambda item: (item.staging_key, item.result_set_index)
                )
            ]

            earliest_supported_season: int | None = None
            if execution_semantics == "historical_backfill" and entries:
                earliest_supported_season = min(
                    (entry.min_season or _DEFAULT_HISTORICAL_START_SEASON) for entry in entries
                )

            contract_gaps = list(coverage_gaps)
            contract_gaps.extend(season_type_value_gaps)
            if source_kind == "live":
                if not staging_keys:
                    contract_gaps.append("snapshot_staging_missing")
                if not transform_outputs:
                    contract_gaps.append("snapshot_transform_missing")
            else:
                if not staging_keys:
                    contract_gaps.append("staging_contract_missing")
                if downstream_status == "excluded":
                    contract_gaps.append("model_excluded")
                if not transform_outputs:
                    contract_gaps.append("transform_contract_missing")
            if input_schema_missing_staging_keys:
                contract_gaps.append("input_schema_missing")
            if output_schema_missing_tables:
                contract_gaps.append("output_schema_missing")
            contract_gaps = sorted(set(contract_gaps))

            if contract_gaps:
                contract_status = "gap"
            elif season_type_contract_status == "untracked":
                contract_status = "partial"
            else:
                contract_status = "complete"

            support_matrix.append(
                {
                    "source_kind": source_kind,
                    "endpoint_name": endpoint_name,
                    "execution_semantics": execution_semantics,
                    "coverage_statuses": coverage_gaps or ["covered"],
                    "contract_status": contract_status,
                    "contract_gaps": contract_gaps,
                    "downstream_status": downstream_status,
                    "downstream_reasons": downstream_reasons,
                    "season_type_contract_status": season_type_contract_status,
                    "declared_supported_season_types": declared_supported_season_types,
                    "season_type_value_gaps": season_type_value_gaps,
                    "param_patterns": sorted(param_patterns),
                    "staging_keys": staging_keys,
                    "transform_outputs": transform_outputs,
                    "input_schema_missing_staging_keys": input_schema_missing_staging_keys,
                    "output_schema_missing_tables": output_schema_missing_tables,
                    "staging_status_details": staging_status_details,
                    "earliest_supported_season": earliest_supported_season,
                    "support_windows": support_windows,
                }
            )

            contract_status_breakdown[contract_status] += 1
            downstream_status_breakdown[downstream_status] += 1
            execution_semantics_breakdown[execution_semantics] += 1
            source_kind_breakdown[source_kind] += 1
            for gap in contract_gaps:
                gap_breakdown[gap] += 1

        summary = {
            "endpoint_count": len(support_matrix),
            "contract_status_breakdown": dict(sorted(contract_status_breakdown.items())),
            "downstream_status_breakdown": dict(sorted(downstream_status_breakdown.items())),
            "execution_semantics_breakdown": dict(sorted(execution_semantics_breakdown.items())),
            "source_kind_breakdown": dict(sorted(source_kind_breakdown.items())),
            "season_type_contract_breakdown": dict(
                sorted(
                    {
                        status: sum(
                            1
                            for row in support_matrix
                            if row["season_type_contract_status"] == status
                        )
                        for status in sorted(
                            {str(row["season_type_contract_status"]) for row in support_matrix}
                        )
                    }.items()
                )
            ),
            "gap_breakdown": dict(sorted(gap_breakdown.items())),
            "complete_endpoint_count": contract_status_breakdown.get("complete", 0),
            "partial_endpoint_count": contract_status_breakdown.get("partial", 0),
            "gap_endpoint_count": contract_status_breakdown.get("gap", 0),
            "season_type_contract_untracked_count": sum(
                1 for row in support_matrix if row["season_type_contract_status"] == "untracked"
            ),
            "season_type_value_gap_count": sum(
                1 for row in support_matrix if row["season_type_value_gaps"]
            ),
            "season_type_contract_open_count": sum(
                1
                for row in support_matrix
                if row["season_type_contract_status"] in {"untracked", "blocked", "mixed"}
                or row["season_type_value_gaps"]
            ),
        }
        return {"matrix": support_matrix, "summary": summary}

    @classmethod
    def _build_extraction_matrix(
        cls,
        *,
        support_matrix: list[dict[str, Any]],
    ) -> dict[str, Any]:
        extraction_matrix: list[dict[str, Any]] = []
        extractability_breakdown: dict[str, int] = defaultdict(int)
        execution_semantics_breakdown: dict[str, int] = defaultdict(int)
        source_kind_breakdown: dict[str, int] = defaultdict(int)
        gap_breakdown: dict[str, int] = defaultdict(int)
        exclusion_breakdown: dict[str, int] = defaultdict(int)

        for support_row in support_matrix:
            endpoint_name = str(support_row["endpoint_name"])
            source_kind = str(support_row["source_kind"])
            execution_semantics = str(support_row["execution_semantics"])
            season_type_contract_status = str(support_row["season_type_contract_status"])
            season_type_value_gaps = [
                str(value) for value in support_row.get("season_type_value_gaps", [])
            ]
            coverage_gaps = [str(value) for value in support_row.get("coverage_statuses", [])]
            coverage_gaps = [gap for gap in coverage_gaps if gap != "covered"]

            extraction_gaps = list(coverage_gaps)
            if not support_row.get("staging_keys"):
                extraction_gaps.append("staging_contract_missing")
            if support_row.get("input_schema_missing_staging_keys"):
                extraction_gaps.append("input_schema_missing")
            if season_type_contract_status == "blocked":
                extraction_gaps.append("season_type_contract_blocked")
            elif season_type_contract_status == "mixed":
                extraction_gaps.append("season_type_contract_mixed")
            elif season_type_contract_status == "untracked":
                extraction_gaps.append("season_type_contract_untracked")
            extraction_gaps.extend(season_type_value_gaps)
            extraction_gaps = sorted(set(extraction_gaps))
            extractability_status, exclusion_detail = cls._evaluate_extraction_status(
                endpoint_name=endpoint_name,
                source_kind=source_kind,
                extraction_gaps=extraction_gaps,
            )
            if exclusion_detail is not None:
                exclusion_breakdown[str(exclusion_detail["classification"])] += 1

            extraction_matrix.append(
                {
                    "source_kind": source_kind,
                    "endpoint_name": endpoint_name,
                    "execution_semantics": execution_semantics,
                    "extractability_status": extractability_status,
                    "coverage_statuses": coverage_gaps or ["covered"],
                    "extraction_gaps": extraction_gaps,
                    "param_patterns": list(support_row.get("param_patterns", [])),
                    "season_type_contract_status": season_type_contract_status,
                    "declared_supported_season_types": list(
                        support_row.get("declared_supported_season_types", [])
                    ),
                    "season_type_value_gaps": season_type_value_gaps,
                    "staging_keys": list(support_row.get("staging_keys", [])),
                    "input_schema_missing_staging_keys": list(
                        support_row.get("input_schema_missing_staging_keys", [])
                    ),
                    "earliest_supported_season": support_row.get("earliest_supported_season"),
                    "support_windows": list(support_row.get("support_windows", [])),
                    "exclusion": exclusion_detail,
                }
            )

            extractability_breakdown[extractability_status] += 1
            execution_semantics_breakdown[execution_semantics] += 1
            source_kind_breakdown[source_kind] += 1
            for gap in extraction_gaps:
                gap_breakdown[gap] += 1

        summary = {
            "endpoint_count": len(extraction_matrix),
            "extractability_breakdown": dict(sorted(extractability_breakdown.items())),
            "execution_semantics_breakdown": dict(sorted(execution_semantics_breakdown.items())),
            "source_kind_breakdown": dict(sorted(source_kind_breakdown.items())),
            "extraction_gap_breakdown": dict(sorted(gap_breakdown.items())),
            "explicit_exclusion_breakdown": dict(sorted(exclusion_breakdown.items())),
            "extractable_endpoint_count": extractability_breakdown.get("extractable", 0),
            "partial_endpoint_count": extractability_breakdown.get("partial", 0),
            "blocked_endpoint_count": extractability_breakdown.get("blocked", 0),
            "excluded_endpoint_count": extractability_breakdown.get("excluded", 0),
            "in_scope_endpoint_count": len(extraction_matrix)
            - extractability_breakdown.get("excluded", 0),
            "season_type_contract_open_count": sum(
                1
                for row in extraction_matrix
                if row["extractability_status"] != "excluded"
                and (
                    row["season_type_contract_status"] in {"untracked", "blocked", "mixed"}
                    or row["season_type_value_gaps"]
                )
            ),
            "excluded_endpoints": [
                {
                    "endpoint_name": row["endpoint_name"],
                    **row["exclusion"],
                }
                for row in extraction_matrix
                if row["exclusion"] is not None
            ],
        }
        summary["ready_for_full_backfill"] = cls._extraction_ready_for_full_backfill(summary)
        return {"matrix": extraction_matrix, "summary": summary}

    @staticmethod
    def _full_extraction_definition_of_done(extraction_summary: dict[str, Any]) -> dict[str, Any]:
        checks = [
            {
                "name": "explicit extraction contract for every in-scope endpoint",
                "met": extraction_summary["in_scope_endpoint_count"]
                == (
                    extraction_summary["extractable_endpoint_count"]
                    + extraction_summary["partial_endpoint_count"]
                    + extraction_summary["blocked_endpoint_count"]
                ),
            },
            {
                "name": "no partially extractable endpoints remain",
                "met": extraction_summary["partial_endpoint_count"] == 0,
            },
            {
                "name": "no blocked endpoints remain in scope",
                "met": extraction_summary["blocked_endpoint_count"] == 0,
            },
            {
                "name": "season-type contract parity is fully closed",
                "met": extraction_summary["season_type_contract_open_count"] == 0,
            },
        ]
        return {
            "artifact_version": 1,
            "goal": (
                "Every in-scope nba_api endpoint has an explicit extraction contract, can be "
                "backfilled across its supported historical window, and is accounted for in "
                "auditable source-completeness reporting."
            ),
            "ready_for_full_backfill": (
                EndpointCoverageGenerator._extraction_ready_for_full_backfill(extraction_summary)
            ),
            "checks": checks,
            "current_status": extraction_summary,
        }

    @staticmethod
    def _live_extraction_exclusion(endpoint_name: str) -> dict[str, str]:
        return {
            "endpoint_name": endpoint_name,
            "classification": "intentionally_deferred",
            "reason": (
                "Live snapshot endpoints are outside the resumable historical full-"
                "extraction contract."
            ),
            "owner": "extract",
            "revalidation_path": (
                "Define a durable historical contract for live snapshot surfaces before "
                "counting them as in-scope for full extraction."
            ),
            "scope": "full_extraction",
        }

    @classmethod
    def _evaluate_extraction_status(
        cls,
        *,
        endpoint_name: str,
        source_kind: str,
        extraction_gaps: list[str],
    ) -> tuple[str, dict[str, str] | None]:
        exclusion = FULL_EXTRACTION_EXCLUSIONS_BY_ENDPOINT.get(endpoint_name)
        if exclusion is not None:
            return "excluded", exclusion.to_dict()
        if source_kind == "live":
            return "excluded", cls._live_extraction_exclusion(endpoint_name)
        if "season_type_contract_blocked" in extraction_gaps:
            return "blocked", None
        if {
            "season_type_contract_untracked",
            "season_type_contract_mixed",
            "supported_season_types_missing",
            "supported_season_types_mixed",
        } & set(extraction_gaps):
            return "partial", None
        if extraction_gaps:
            return "blocked", None
        return "extractable", None

    @staticmethod
    def _extraction_ready_for_full_backfill(extraction_summary: dict[str, Any]) -> bool:
        return (
            int(extraction_summary.get("partial_endpoint_count", 0)) == 0
            and int(extraction_summary.get("blocked_endpoint_count", 0)) == 0
            and int(extraction_summary.get("season_type_contract_open_count", 0)) == 0
        )

    @classmethod
    def _build_temporal_support_ledger(
        cls,
        support_matrix: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ledger: list[dict[str, Any]] = []
        support_window_count = 0

        for row in support_matrix:
            if row["source_kind"] != "stats" or row["execution_semantics"] != "historical_backfill":
                continue

            for window in row["support_windows"]:
                support_window_count += 1
                supported_season_types = list(window["supported_season_types"])
                season_types = supported_season_types or [None]
                for season_type in season_types:
                    ledger.append(
                        {
                            "ledger_key": (
                                f"{row['endpoint_name']}:{window['staging_key']}:"
                                f"{season_type or 'all'}:{window['result_set_index']}"
                            ),
                            "endpoint_name": row["endpoint_name"],
                            "source_kind": row["source_kind"],
                            "execution_semantics": row["execution_semantics"],
                            "param_pattern": window["param_pattern"],
                            "staging_key": window["staging_key"],
                            "result_set_index": window["result_set_index"],
                            "historical_start_season": (
                                window["min_season"] or _DEFAULT_HISTORICAL_START_SEASON
                            ),
                            "deprecated_after": window["deprecated_after"],
                            "season_type": season_type,
                            "season_type_capability": window["season_type_capability"],
                            "supported_season_types": supported_season_types,
                            "input_schema_present": window["input_schema_present"],
                            "transform_outputs": window["transform_outputs"],
                        }
                    )

        summary = {
            "endpoint_count": len({row["endpoint_name"] for row in ledger}),
            "ledger_row_count": len(ledger),
            "support_window_count": support_window_count,
            "season_type_row_count": sum(1 for row in ledger if row["season_type"] is not None),
            "untracked_season_type_row_count": sum(
                1 for row in ledger if row["season_type"] is None
            ),
            "season_type_capability_breakdown": dict(
                sorted(
                    Counter(
                        row["season_type_capability"]
                        for row in ledger
                        if row["season_type_capability"] is not None
                    ).items()
                )
            ),
        }

        return {"ledger": ledger, "summary": summary}

    @staticmethod
    def _downstream_ownership_status(row: dict[str, Any]) -> str:
        return str(row.get("downstream_status", "not_applicable"))

    @classmethod
    def _build_endpoint_adequacy_scorecard(
        cls,
        support_matrix: list[dict[str, Any]],
        support_summary: dict[str, Any],
        temporal_support_ledger: dict[str, Any],
    ) -> dict[str, Any]:
        scorecard: list[dict[str, Any]] = []
        adequacy_status_breakdown: Counter[str] = Counter()
        downstream_status_breakdown: Counter[str] = Counter()
        coverage_status_breakdown: Counter[str] = Counter()
        contract_status_breakdown: Counter[str] = Counter()
        source_kind_breakdown: Counter[str] = Counter()

        for row in support_matrix:
            coverage_statuses = list(row["coverage_statuses"])
            coverage_status = (
                coverage_statuses[0]
                if len(coverage_statuses) == 1
                else "mixed"
                if coverage_statuses
                else "covered"
            )
            downstream_status = cls._downstream_ownership_status(row)
            if coverage_status != "covered":
                adequacy_status = coverage_status
            elif row["contract_status"] != "complete":
                adequacy_status = "gap"
            elif row["source_kind"] == "stats" and downstream_status != "modeled":
                adequacy_status = downstream_status
            else:
                adequacy_status = "adequate"

            scorecard.append(
                {
                    "endpoint_name": row["endpoint_name"],
                    "source_kind": row["source_kind"],
                    "coverage_status": coverage_status,
                    "coverage_statuses": coverage_statuses,
                    "contract_status": row["contract_status"],
                    "adequacy_status": adequacy_status,
                    "downstream_status": downstream_status,
                    "execution_semantics": row["execution_semantics"],
                    "season_type_contract_status": row["season_type_contract_status"],
                    "support_window_count": len(row["support_windows"]),
                    "staging_key_count": len(row["staging_keys"]),
                    "transform_output_count": len(row["transform_outputs"]),
                    "coverage_gap_count": 0
                    if coverage_status == "covered"
                    else len(coverage_statuses),
                    "contract_gap_count": len(row["contract_gaps"]),
                    "input_schema_missing_count": len(row["input_schema_missing_staging_keys"]),
                    "output_schema_missing_count": len(row["output_schema_missing_tables"]),
                    "downstream_reason_count": len(row["downstream_reasons"]),
                    "season_type_value_gap_count": len(row["season_type_value_gaps"]),
                }
            )
            adequacy_status_breakdown[adequacy_status] += 1
            downstream_status_breakdown[downstream_status] += 1
            coverage_status_breakdown[coverage_status] += 1
            contract_status_breakdown[row["contract_status"]] += 1
            source_kind_breakdown[row["source_kind"]] += 1

        summary = {
            "endpoint_count": len(scorecard),
            "adequate_endpoint_count": adequacy_status_breakdown.get("adequate", 0),
            "coverage_gap_endpoint_count": sum(
                1 for row in scorecard if row["coverage_status"] != "covered"
            ),
            "contract_gap_endpoint_count": sum(
                1 for row in scorecard if row["contract_status"] != "complete"
            ),
            "downstream_modeled_endpoint_count": downstream_status_breakdown.get("modeled", 0),
            "downstream_passthrough_only_endpoint_count": downstream_status_breakdown.get(
                "passthrough_only", 0
            ),
            "downstream_compatibility_reference_only_endpoint_count": (
                downstream_status_breakdown.get("compatibility_reference_only", 0)
            ),
            "downstream_excluded_endpoint_count": downstream_status_breakdown.get("excluded", 0),
            "downstream_unowned_endpoint_count": downstream_status_breakdown.get("unowned", 0),
            "downstream_not_applicable_endpoint_count": downstream_status_breakdown.get(
                "not_applicable", 0
            ),
            "adequacy_status_breakdown": dict(sorted(adequacy_status_breakdown.items())),
            "coverage_status_breakdown": dict(sorted(coverage_status_breakdown.items())),
            "contract_status_breakdown": dict(sorted(contract_status_breakdown.items())),
            "downstream_status_breakdown": dict(sorted(downstream_status_breakdown.items())),
            "source_kind_breakdown": dict(sorted(source_kind_breakdown.items())),
            "support_contract": support_summary,
            "temporal_support_ledger": temporal_support_ledger["summary"],
        }
        return {"scorecard": scorecard, "summary": summary}

    def build_artifacts(
        self,
        runtime_endpoint_classes: set[str] | None = None,
        runtime_static_surfaces: set[str] | None = None,
        runtime_live_endpoint_classes: set[str] | None = None,
        runtime_version: str | None = None,
    ) -> dict[str, Any]:
        extractor_map = self._extractor_endpoint_map()
        static_extractors = self._static_extractor_surfaces()
        live_extractors = self._live_extractor_surfaces()
        (
            transform_outputs_by_staging,
            unique_outputs,
            transform_semantics_by_output,
        ) = self._transform_catalog()
        staging_schema_tables = self._staging_schema_tables()
        raw_schema_tables = self._raw_schema_tables()
        star_schema_tables = self._star_schema_tables()
        staging_entries_by_endpoint: dict[str, list[StagingEntry]] = {}
        for entry in self.staging_entries:
            canonical = _ENDPOINT_ALIASES.get(entry.endpoint_name, entry.endpoint_name)
            staging_entries_by_endpoint.setdefault(canonical, []).append(entry)

        runtime_classes = (
            set(runtime_endpoint_classes) if runtime_endpoint_classes is not None else None
        )
        if runtime_classes is None:
            runtime_classes, detected_version = self._discover_runtime_endpoint_classes()
            runtime_version = runtime_version or detected_version
        else:
            runtime_version = runtime_version or "provided"
        normalized_runtime_classes = self._normalize_runtime_classes(runtime_classes)
        known_stats_surfaces = set(staging_entries_by_endpoint) | set(extractor_map)
        runtime_stats_surfaces = {
            _runtime_class_to_surface_name(class_name, known_stats_surfaces)
            for class_name in runtime_classes
        }
        static_runtime_surfaces = (
            set(runtime_static_surfaces)
            if runtime_static_surfaces is not None
            else self._discover_runtime_static_surfaces()
        )
        live_runtime_surfaces = (
            {_to_snake_case(name) for name in runtime_live_endpoint_classes}
            if runtime_live_endpoint_classes is not None
            else self._discover_runtime_live_endpoint_classes()
        )

        matrix: list[dict[str, Any]] = []

        stats_endpoint_names = {
            endpoint_name
            for endpoint_name in (
                set(staging_entries_by_endpoint) | set(extractor_map) | runtime_stats_surfaces
            )
            if endpoint_name not in _STATIC_SURFACE_ALIASES
            and endpoint_name not in _LIVE_SURFACE_ALIASES
        }

        for endpoint_name in sorted(stats_endpoint_names):
            entries = staging_entries_by_endpoint.get(endpoint_name, [])
            runtime_refs = sorted(extractor_map.get(endpoint_name, set()))
            staging_present = bool(entries)
            extractor_present = endpoint_name in extractor_map
            runtime_present = endpoint_name in runtime_stats_surfaces
            runtime_match = bool(
                normalized_runtime_classes and set(runtime_refs) & normalized_runtime_classes
            )

            if staging_present:
                if extractor_present:
                    coverage_status = (
                        "covered" if (not runtime_present or runtime_match) else "runtime_gap"
                    )
                    if runtime_classes and (not runtime_present or not runtime_match):
                        coverage_status = "runtime_gap"
                else:
                    coverage_status = "staging_only"
            else:
                coverage_status = "extractor_only" if extractor_present else "source_only"

            staging_keys = [entry.staging_key for entry in entries]
            transform_outputs = sorted(
                {
                    output
                    for staging_key in staging_keys
                    for output in transform_outputs_by_staging.get(staging_key, set())
                }
            )
            staging_status_details: list[_StagingStatusDetail] = [
                {
                    "staging_key": entry.staging_key,
                    "downstream_status": status,
                    "transform_outputs": outputs,
                    "downstream_reasons": reasons,
                }
                for entry in entries
                for status, outputs, reasons in [
                    self._staging_downstream_status(
                        endpoint_name=endpoint_name,
                        staging_key=entry.staging_key,
                        transform_outputs_by_staging=transform_outputs_by_staging,
                        transform_semantics_by_output=transform_semantics_by_output,
                    )
                ]
            ]
            param_pattern = entries[0].param_pattern if entries else "extractor_only"
            model_status = self._endpoint_downstream_status(
                source_kind="stats",
                staging_statuses=[detail["downstream_status"] for detail in staging_status_details],
            )
            model_status_reasons = sorted(
                {
                    reason
                    for detail in staging_status_details
                    for reason in detail["downstream_reasons"]
                }
            )

            matrix.append(
                {
                    "source_kind": "stats",
                    "endpoint_name": endpoint_name,
                    "surface_name": endpoint_name,
                    "param_pattern": param_pattern,
                    "staging_present": staging_present,
                    "staging_keys": staging_keys,
                    "staging_entry_count": len(staging_keys),
                    "extractor_present": extractor_present,
                    "runtime_present": runtime_present,
                    "runtime_refs": runtime_refs,
                    "runtime_match": runtime_match,
                    "transform_outputs": transform_outputs,
                    "transform_present": bool(transform_outputs),
                    "model_status": model_status,
                    "model_status_reasons": model_status_reasons,
                    "coverage_status": coverage_status,
                }
            )

        for surface_name in sorted(static_runtime_surfaces | static_extractors):
            runtime_present = surface_name in static_runtime_surfaces
            extractor_present = surface_name in static_extractors
            endpoint_name = _STATIC_SURFACE_ENDPOINT_NAMES.get(
                surface_name,
                f"static_{surface_name}",
            )
            matrix.append(
                {
                    "source_kind": "static",
                    "endpoint_name": endpoint_name,
                    "surface_name": surface_name,
                    "param_pattern": "static",
                    "staging_present": False,
                    "staging_keys": [],
                    "staging_entry_count": 0,
                    "extractor_present": True,
                    "runtime_present": runtime_present,
                    "runtime_refs": [surface_name] if extractor_present else [],
                    "runtime_match": runtime_present and extractor_present,
                    "transform_outputs": [],
                    "transform_present": False,
                    "model_status": "not_applicable",
                    "model_status_reasons": [],
                    "coverage_status": (
                        "covered"
                        if runtime_present and extractor_present
                        else "source_only"
                        if runtime_present
                        else "extractor_only"
                    ),
                }
            )

        for row in matrix:
            if row["source_kind"] == "static":
                row["extractor_present"] = row["surface_name"] in static_extractors

        for surface_name in sorted(live_runtime_surfaces | live_extractors):
            runtime_present = surface_name in live_runtime_surfaces
            extractor_present = surface_name in live_extractors
            endpoint_name = _LIVE_SURFACE_ENDPOINT_NAMES.get(surface_name, f"live_{surface_name}")
            matrix.append(
                {
                    "source_kind": "live",
                    "endpoint_name": endpoint_name,
                    "surface_name": surface_name,
                    "param_pattern": "live",
                    "staging_present": False,
                    "staging_keys": [],
                    "staging_entry_count": 0,
                    "extractor_present": extractor_present,
                    "runtime_present": runtime_present,
                    "runtime_refs": [surface_name] if extractor_present else [],
                    "runtime_match": runtime_present and extractor_present,
                    "transform_outputs": [],
                    "transform_present": False,
                    "model_status": "not_applicable",
                    "model_status_reasons": [],
                    "coverage_status": (
                        "covered"
                        if runtime_present and extractor_present
                        else "source_only"
                        if runtime_present
                        else "extractor_only"
                    ),
                }
            )

        coverage = {key: 0 for key in _COVERAGE_KEYS}
        heatmap: dict[str, dict[str, int | str]] = {}
        for row in matrix:
            status = row["coverage_status"]
            if status in coverage:
                coverage[status] += 1

            if row["source_kind"] != "stats":
                continue
            pattern = row["param_pattern"]
            if pattern == "extractor_only":
                continue
            if pattern not in heatmap:
                heatmap[pattern] = {
                    "param_pattern": pattern,
                    "total": 0,
                    "covered": 0,
                    "runtime_gap": 0,
                    "staging_only": 0,
                }
            heatmap_row = heatmap[pattern]
            heatmap_row["total"] = int(heatmap_row["total"]) + 1
            if status in {"covered", "runtime_gap", "staging_only"}:
                heatmap_row[status] = int(heatmap_row[status]) + 1

        source_breakdown: list[dict[str, Any]] = []
        for source_kind in _SOURCE_KINDS:
            source_summary = {"source_kind": source_kind, "total": 0}
            for key in _COVERAGE_KEYS:
                source_summary[key] = 0
            for row in matrix:
                if row["source_kind"] != source_kind:
                    continue
                source_summary["total"] += 1
                status = row["coverage_status"]
                if status in _COVERAGE_KEYS:
                    source_summary[status] = int(source_summary[status]) + 1
            source_breakdown.append(source_summary)

        staging_result_set_shape_breakdown = Counter(
            self._staging_result_set_shape(entry) for entry in self.staging_entries
        )
        staging_entry_statuses: list[dict[str, Any]] = []
        for entry in self.staging_entries:
            endpoint_name = _ENDPOINT_ALIASES.get(entry.endpoint_name, entry.endpoint_name)
            status, outputs, reasons = self._staging_downstream_status(
                endpoint_name=endpoint_name,
                staging_key=entry.staging_key,
                transform_outputs_by_staging=transform_outputs_by_staging,
                transform_semantics_by_output=transform_semantics_by_output,
            )
            staging_entry_statuses.append(
                {
                    "staging_key": entry.staging_key,
                    "endpoint_name": endpoint_name,
                    "downstream_status": status,
                    "transform_outputs": outputs,
                    "reasons": reasons,
                }
            )
        staging_status_breakdown = Counter(
            row["downstream_status"] for row in staging_entry_statuses
        )
        stats_rows = [
            row for row in matrix if row["source_kind"] == "stats" and row["staging_present"]
        ]
        stats_status_breakdown = Counter(row["model_status"] for row in stats_rows)
        passthrough_stats_endpoints = [
            {
                "endpoint_name": row["endpoint_name"],
                "staging_keys": row["staging_keys"],
                "transform_outputs": row["transform_outputs"],
            }
            for row in stats_rows
            if row["model_status"] == "passthrough_only"
        ]
        compatibility_reference_stats_endpoints = [
            {
                "endpoint_name": row["endpoint_name"],
                "reason": "; ".join(row["model_status_reasons"]),
                "staging_keys": row["staging_keys"],
                "transform_outputs": row["transform_outputs"],
            }
            for row in stats_rows
            if row["model_status"] == "compatibility_reference_only"
        ]
        excluded_stats_endpoints = [
            {
                "endpoint_name": row["endpoint_name"],
                "reason": "; ".join(row["model_status_reasons"]),
                "staging_keys": row["staging_keys"],
            }
            for row in stats_rows
            if row["model_status"] == "excluded"
        ]
        unowned_stats_endpoints = [
            {
                "endpoint_name": row["endpoint_name"],
                "staging_keys": row["staging_keys"],
            }
            for row in stats_rows
            if row["model_status"] == "unowned"
        ]
        compatibility_reference_staging_entries_detail = [
            {
                "staging_key": row["staging_key"],
                "endpoint_name": row["endpoint_name"],
                "reason": "; ".join(row["reasons"]),
                "transform_outputs": row["transform_outputs"],
            }
            for row in staging_entry_statuses
            if row["downstream_status"] == "compatibility_reference_only"
        ]
        excluded_staging_entries_detail = [
            {
                "staging_key": row["staging_key"],
                "endpoint_name": row["endpoint_name"],
                "reason": "; ".join(row["reasons"]),
            }
            for row in staging_entry_statuses
            if row["downstream_status"] == "excluded"
        ]
        schema_backed_outputs = sorted(unique_outputs & star_schema_tables)
        schema_missing_outputs = sorted(unique_outputs - star_schema_tables)
        schema_only_tables = sorted(star_schema_tables - unique_outputs)

        summary = {
            "runtime_version": runtime_version,
            "runtime_endpoint_class_count": len(runtime_classes),
            "runtime_static_surface_count": len(static_runtime_surfaces),
            "runtime_live_endpoint_count": len(live_runtime_surfaces),
            "runtime_surface_count": (
                len(runtime_stats_surfaces)
                + len(static_runtime_surfaces)
                + len(live_runtime_surfaces)
            ),
            "staging_endpoint_count": len(staging_entries_by_endpoint),
            "extractor_endpoint_count": len(extractor_map),
            "extractor_static_surface_count": len(static_extractors),
            "extractor_live_endpoint_count": len(live_extractors),
            "coverage": coverage,
            "source_breakdown": source_breakdown,
            "pattern_heatmap": [heatmap[key] for key in sorted(heatmap)],
            "model_ownership": {
                "staging_entry_count": len(self.staging_entries),
                "analytically_modeled_staging_entries": staging_status_breakdown.get("modeled", 0),
                "passthrough_only_staging_entries": staging_status_breakdown.get(
                    "passthrough_only", 0
                ),
                "compatibility_reference_only_staging_entries": staging_status_breakdown.get(
                    "compatibility_reference_only", 0
                ),
                "model_excluded_staging_entries": staging_status_breakdown.get("excluded", 0),
                "model_unowned_staging_entries": staging_status_breakdown.get("unowned", 0),
                "staging_result_set_shape_breakdown": dict(
                    sorted(staging_result_set_shape_breakdown.items())
                ),
                "stats_endpoint_count": len(staging_entries_by_endpoint),
                "analytically_modeled_stats_endpoints": stats_status_breakdown.get("modeled", 0),
                "passthrough_only_stats_endpoints": stats_status_breakdown.get(
                    "passthrough_only", 0
                ),
                "compatibility_reference_only_stats_endpoints": stats_status_breakdown.get(
                    "compatibility_reference_only", 0
                ),
                "model_excluded_stats_endpoints": stats_status_breakdown.get("excluded", 0),
                "model_unowned_stats_endpoints": stats_status_breakdown.get("unowned", 0),
                "passthrough_stats_endpoints": passthrough_stats_endpoints,
                "compatibility_reference_stats_endpoints": (
                    compatibility_reference_stats_endpoints
                ),
                "excluded_stats_endpoints": excluded_stats_endpoints,
                "compatibility_reference_staging_entries_detail": (
                    compatibility_reference_staging_entries_detail
                ),
                "excluded_staging_entries_detail": excluded_staging_entries_detail,
                "unowned_stats_endpoints": unowned_stats_endpoints,
                "transform_output_count": len(unique_outputs),
            },
            "star_schema_coverage": {
                "transform_output_count": len(unique_outputs),
                "schema_backed_transform_outputs": len(schema_backed_outputs),
                "schema_missing_transform_outputs": len(schema_missing_outputs),
                "schema_only_table_count": len(schema_only_tables),
                "schema_backed_breakdown": self._table_family_breakdown(schema_backed_outputs),
                "schema_missing_breakdown": self._table_family_breakdown(schema_missing_outputs),
                "schema_only_breakdown": self._table_family_breakdown(schema_only_tables),
                "schema_backed_outputs": schema_backed_outputs,
                "schema_missing_outputs": schema_missing_outputs,
                "schema_only_tables": schema_only_tables,
            },
        }

        support_contract = self._build_support_matrix(
            matrix=matrix,
            staging_entries_by_endpoint=staging_entries_by_endpoint,
            transform_outputs_by_staging=transform_outputs_by_staging,
            transform_semantics_by_output=transform_semantics_by_output,
            staging_schema_tables=staging_schema_tables,
            raw_schema_tables=raw_schema_tables,
            star_schema_tables=star_schema_tables,
        )
        extraction_contract = self._build_extraction_matrix(
            support_matrix=support_contract["matrix"],
        )
        temporal_support_ledger = self._build_temporal_support_ledger(support_contract["matrix"])
        endpoint_adequacy_scorecard = self._build_endpoint_adequacy_scorecard(
            support_contract["matrix"],
            support_contract["summary"],
            temporal_support_ledger,
        )
        summary["support_contract"] = support_contract["summary"]
        summary["extraction_contract"] = extraction_contract["summary"]
        full_extraction_definition = self._full_extraction_definition_of_done(
            extraction_contract["summary"]
        )
        summary["support_contract"]["temporal_support_ledger"] = temporal_support_ledger["summary"]

        return {
            "matrix": matrix,
            "summary": summary,
            "support_matrix": support_contract["matrix"],
            "support_summary": support_contract["summary"],
            "extraction_matrix": extraction_contract["matrix"],
            "extraction_summary": extraction_contract["summary"],
            "full_extraction_definition": full_extraction_definition,
            "temporal_support_ledger": temporal_support_ledger,
            "endpoint_adequacy_scorecard": endpoint_adequacy_scorecard,
        }

    @staticmethod
    def _report_text(summary: dict[str, Any]) -> str:
        lines = [
            "# Endpoint Coverage Report",
            "",
            "## Coverage Summary",
            "",
            "| Status | Count |",
            "|--------|-------|",
        ]
        for key in _COVERAGE_KEYS:
            lines.append(f"| {key} | {summary['coverage'][key]} |")

        lines.extend(
            [
                "",
                "## Source Breakdown",
                "",
                (
                    "| Source | Total | Covered | Runtime Gap | Staging Only | "
                    "Extractor Only | Source Only |"
                ),
                "|--------|-------|---------|-------------|--------------|----------------|-------------|",
            ]
        )
        for row in summary["source_breakdown"]:
            lines.append(
                f"| {row['source_kind']} | {row['total']} | {row['covered']} | "
                f"{row['runtime_gap']} | {row['staging_only']} | {row['extractor_only']} | "
                f"{row['source_only']} |"
            )

        model_ownership = summary["model_ownership"]
        lines.extend(
            [
                "",
                "## Model Ownership",
                "",
                "| Metric | Count |",
                "|--------|-------|",
                f"| staging_entry_count | {model_ownership['staging_entry_count']} |",
                f"| analytically_modeled_staging_entries | "
                f"{model_ownership['analytically_modeled_staging_entries']} |",
                f"| passthrough_only_staging_entries | "
                f"{model_ownership['passthrough_only_staging_entries']} |",
                f"| compatibility_reference_only_staging_entries | "
                f"{model_ownership['compatibility_reference_only_staging_entries']} |",
                f"| model_excluded_staging_entries | "
                f"{model_ownership['model_excluded_staging_entries']} |",
                f"| model_unowned_staging_entries | "
                f"{model_ownership['model_unowned_staging_entries']} |",
                f"| stats_endpoint_count | {model_ownership['stats_endpoint_count']} |",
                f"| analytically_modeled_stats_endpoints | "
                f"{model_ownership['analytically_modeled_stats_endpoints']} |",
                f"| passthrough_only_stats_endpoints | "
                f"{model_ownership['passthrough_only_stats_endpoints']} |",
                f"| compatibility_reference_only_stats_endpoints | "
                f"{model_ownership['compatibility_reference_only_stats_endpoints']} |",
                f"| model_excluded_stats_endpoints | "
                f"{model_ownership['model_excluded_stats_endpoints']} |",
                f"| model_unowned_stats_endpoints | "
                f"{model_ownership['model_unowned_stats_endpoints']} |",
                f"| transform_output_count | {model_ownership['transform_output_count']} |",
            ]
        )
        lines.extend(
            [
                "",
                "### Staging Result-Set Shape Breakdown",
                "",
                "| Shape | Count |",
                "|-------|-------|",
            ]
        )
        for shape_name, count in model_ownership["staging_result_set_shape_breakdown"].items():
            lines.append(f"| {shape_name} | {count} |")
        if model_ownership.get("passthrough_stats_endpoints"):
            lines.extend(
                [
                    "",
                    "### Passthrough-Only Stats Endpoints",
                    "",
                    "| Endpoint | Staging Keys | Transform Outputs |",
                    "|----------|--------------|-------------------|",
                ]
            )
            for row in model_ownership["passthrough_stats_endpoints"]:
                lines.append(
                    f"| {row['endpoint_name']} | {', '.join(row['staging_keys'])} | "
                    f"{', '.join(row['transform_outputs'])} |"
                )
        if model_ownership.get("compatibility_reference_stats_endpoints"):
            lines.extend(
                [
                    "",
                    "### Compatibility/Reference-Only Stats Endpoints",
                    "",
                    "| Endpoint | Reason |",
                    "|----------|--------|",
                ]
            )
            for row in model_ownership["compatibility_reference_stats_endpoints"]:
                lines.append(f"| {row['endpoint_name']} | {row['reason']} |")
        if model_ownership["excluded_stats_endpoints"]:
            lines.extend(
                [
                    "",
                    "### Explicit Stats Model Exclusions",
                    "",
                    "| Endpoint | Reason |",
                    "|----------|--------|",
                ]
            )
            for row in model_ownership["excluded_stats_endpoints"]:
                lines.append(f"| {row['endpoint_name']} | {row['reason']} |")
        if model_ownership.get("compatibility_reference_staging_entries_detail"):
            lines.extend(
                [
                    "",
                    "### Compatibility/Reference-Only Staging Entries",
                    "",
                    "| Staging Key | Endpoint | Reason |",
                    "|-------------|----------|--------|",
                ]
            )
            for row in model_ownership["compatibility_reference_staging_entries_detail"]:
                lines.append(f"| {row['staging_key']} | {row['endpoint_name']} | {row['reason']} |")
        if model_ownership.get("excluded_staging_entries_detail"):
            lines.extend(
                [
                    "",
                    "### Explicit Staging Model Exclusions",
                    "",
                    "| Staging Key | Endpoint | Reason |",
                    "|-------------|----------|--------|",
                ]
            )
            for row in model_ownership["excluded_staging_entries_detail"]:
                lines.append(f"| {row['staging_key']} | {row['endpoint_name']} | {row['reason']} |")
        if model_ownership["unowned_stats_endpoints"]:
            lines.extend(
                [
                    "",
                    "### Unowned Stats Endpoints",
                    "",
                    "| Endpoint | Staging Keys |",
                    "|----------|--------------|",
                ]
            )
            for row in model_ownership["unowned_stats_endpoints"]:
                staging_keys = ", ".join(row["staging_keys"])
                lines.append(f"| {row['endpoint_name']} | {staging_keys} |")

        star_schema_coverage = summary.get("star_schema_coverage", {})
        if star_schema_coverage:
            lines.extend(
                [
                    "",
                    "## Star Schema Coverage",
                    "",
                    "| Metric | Count |",
                    "|--------|-------|",
                    (
                        f"| transform_output_count | "
                        f"{star_schema_coverage['transform_output_count']} |"
                    ),
                    (
                        f"| schema_backed_transform_outputs | "
                        f"{star_schema_coverage['schema_backed_transform_outputs']} |"
                    ),
                    (
                        f"| schema_missing_transform_outputs | "
                        f"{star_schema_coverage['schema_missing_transform_outputs']} |"
                    ),
                    (
                        f"| schema_only_table_count | "
                        f"{star_schema_coverage['schema_only_table_count']} |"
                    ),
                ]
            )

            family_names = sorted(
                set(star_schema_coverage["schema_backed_breakdown"])
                | set(star_schema_coverage["schema_missing_breakdown"])
                | set(star_schema_coverage["schema_only_breakdown"])
            )
            if family_names:
                lines.extend(
                    [
                        "",
                        "### Table Family Breakdown",
                        "",
                        "| Table Family | Schema-backed | Schema-missing | Schema-only |",
                        "|--------------|---------------|----------------|-------------|",
                    ]
                )
                for family_name in family_names:
                    lines.append(
                        f"| {family_name} | "
                        f"{star_schema_coverage['schema_backed_breakdown'].get(family_name, 0)} | "
                        f"{star_schema_coverage['schema_missing_breakdown'].get(family_name, 0)} | "
                        f"{star_schema_coverage['schema_only_breakdown'].get(family_name, 0)} |"
                    )

            if star_schema_coverage["schema_missing_outputs"]:
                lines.extend(
                    [
                        "",
                        "### Transform Outputs Missing Star Schemas",
                        "",
                        "| Output Table | Table Family |",
                        "|--------------|--------------|",
                    ]
                )
                for table_name in star_schema_coverage["schema_missing_outputs"]:
                    lines.append(
                        f"| {table_name} | {EndpointCoverageGenerator._table_family(table_name)} |"
                    )

            if star_schema_coverage["schema_only_tables"]:
                lines.extend(
                    [
                        "",
                        "### Schema-only Tables",
                        "",
                        "| Table | Table Family |",
                        "|-------|--------------|",
                    ]
                )
                for table_name in star_schema_coverage["schema_only_tables"]:
                    lines.append(
                        f"| {table_name} | {EndpointCoverageGenerator._table_family(table_name)} |"
                    )

        support_contract = summary.get("support_contract", {})
        if support_contract:
            lines.extend(
                [
                    "",
                    "## Strict Build Contract",
                    "",
                    "| Metric | Count |",
                    "|--------|-------|",
                    f"| endpoint_count | {support_contract['endpoint_count']} |",
                    f"| complete_endpoint_count | {support_contract['complete_endpoint_count']} |",
                    f"| partial_endpoint_count | {support_contract['partial_endpoint_count']} |",
                    f"| gap_endpoint_count | {support_contract['gap_endpoint_count']} |",
                    (
                        f"| season_type_contract_open_count | "
                        f"{support_contract['season_type_contract_open_count']} |"
                    ),
                    (
                        f"| season_type_contract_untracked_count | "
                        f"{support_contract['season_type_contract_untracked_count']} |"
                    ),
                    (
                        f"| season_type_value_gap_count | "
                        f"{support_contract['season_type_value_gap_count']} |"
                    ),
                ]
            )
            if support_contract.get("contract_status_breakdown"):
                lines.extend(
                    [
                        "",
                        "### Contract Status Breakdown",
                        "",
                        "| Status | Count |",
                        "|--------|-------|",
                    ]
                )
                for status, count in support_contract["contract_status_breakdown"].items():
                    lines.append(f"| {status} | {count} |")
            if support_contract.get("execution_semantics_breakdown"):
                lines.extend(
                    [
                        "",
                        "### Execution Semantics Breakdown",
                        "",
                        "| Semantics | Count |",
                        "|-----------|-------|",
                    ]
                )
                for semantics, count in support_contract["execution_semantics_breakdown"].items():
                    lines.append(f"| {semantics} | {count} |")
            if support_contract.get("season_type_contract_breakdown"):
                lines.extend(
                    [
                        "",
                        "### Season Type Contract Breakdown",
                        "",
                        "| Season Type Contract | Count |",
                        "|----------------------|-------|",
                    ]
                )
                for status, count in support_contract["season_type_contract_breakdown"].items():
                    lines.append(f"| {status} | {count} |")
            if support_contract.get("gap_breakdown"):
                lines.extend(
                    [
                        "",
                        "### Contract Gap Breakdown",
                        "",
                        "| Gap | Count |",
                        "|-----|-------|",
                    ]
                )
                for gap, count in support_contract["gap_breakdown"].items():
                    lines.append(f"| {gap} | {count} |")
            temporal_support_ledger = support_contract.get("temporal_support_ledger", {})
            if temporal_support_ledger:
                lines.extend(
                    [
                        "",
                        "## Temporal Support Ledger",
                        "",
                        "| Metric | Count |",
                        "|--------|-------|",
                        f"| endpoint_count | {temporal_support_ledger['endpoint_count']} |",
                        f"| ledger_row_count | {temporal_support_ledger['ledger_row_count']} |",
                        (
                            f"| support_window_count | "
                            f"{temporal_support_ledger['support_window_count']} |"
                        ),
                        (
                            f"| season_type_row_count | "
                            f"{temporal_support_ledger['season_type_row_count']} |"
                        ),
                        (
                            f"| untracked_season_type_row_count | "
                            f"{temporal_support_ledger['untracked_season_type_row_count']} |"
                        ),
                    ]
                )
                if temporal_support_ledger.get("season_type_capability_breakdown"):
                    lines.extend(
                        [
                            "",
                            "### Season Type Capability Breakdown",
                            "",
                            "| Capability | Count |",
                            "|------------|-------|",
                        ]
                    )
                    for capability, count in temporal_support_ledger[
                        "season_type_capability_breakdown"
                    ].items():
                        lines.append(f"| {capability} | {count} |")

        lines.extend(
            [
                "",
                "## Pattern Heatmap",
                "",
                "| Param Pattern | Total | Covered | Runtime Gap | Staging Only |",
                "|---------------|-------|---------|-------------|--------------|",
            ]
        )
        for row in summary["pattern_heatmap"]:
            lines.append(
                f"| {row['param_pattern']} | {row['total']} | {row['covered']} | "
                f"{row['runtime_gap']} | {row['staging_only']} |"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _support_report_text(summary: dict[str, Any]) -> str:
        lines = [
            "# Endpoint Support Matrix",
            "",
            "## Summary",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| endpoint_count | {summary['endpoint_count']} |",
            f"| complete_endpoint_count | {summary['complete_endpoint_count']} |",
            f"| partial_endpoint_count | {summary['partial_endpoint_count']} |",
            f"| gap_endpoint_count | {summary['gap_endpoint_count']} |",
            (f"| season_type_contract_open_count | {summary['season_type_contract_open_count']} |"),
            (
                f"| season_type_contract_untracked_count | "
                f"{summary['season_type_contract_untracked_count']} |"
            ),
            f"| season_type_value_gap_count | {summary['season_type_value_gap_count']} |",
        ]

        for section_name, title, value_header in (
            ("contract_status_breakdown", "Contract Status Breakdown", "Status"),
            ("downstream_status_breakdown", "Downstream Status Breakdown", "Downstream Status"),
            ("execution_semantics_breakdown", "Execution Semantics Breakdown", "Semantics"),
            ("source_kind_breakdown", "Source Kind Breakdown", "Source Kind"),
            (
                "season_type_contract_breakdown",
                "Season Type Contract Breakdown",
                "Season Type Contract",
            ),
            ("gap_breakdown", "Contract Gap Breakdown", "Gap"),
        ):
            breakdown = summary.get(section_name, {})
            if not breakdown:
                continue
            lines.extend(
                [
                    "",
                    f"## {title}",
                    "",
                    f"| {value_header} | Count |",
                    "|----------------|-------|",
                ]
            )
            for key, count in breakdown.items():
                lines.append(f"| {key} | {count} |")

        temporal_support_ledger = summary.get("temporal_support_ledger", {})
        if temporal_support_ledger:
            lines.extend(
                [
                    "",
                    "## Temporal Support Ledger",
                    "",
                    "| Metric | Count |",
                    "|--------|-------|",
                    f"| endpoint_count | {temporal_support_ledger['endpoint_count']} |",
                    f"| ledger_row_count | {temporal_support_ledger['ledger_row_count']} |",
                    (
                        f"| support_window_count | "
                        f"{temporal_support_ledger['support_window_count']} |"
                    ),
                    (
                        f"| season_type_row_count | "
                        f"{temporal_support_ledger['season_type_row_count']} |"
                    ),
                    (
                        f"| untracked_season_type_row_count | "
                        f"{temporal_support_ledger['untracked_season_type_row_count']} |"
                    ),
                ]
            )
            if temporal_support_ledger.get("season_type_capability_breakdown"):
                lines.extend(
                    [
                        "",
                        "### Season Type Capability Breakdown",
                        "",
                        "| Capability | Count |",
                        "|------------|-------|",
                    ]
                )
                for capability, count in temporal_support_ledger[
                    "season_type_capability_breakdown"
                ].items():
                    lines.append(f"| {capability} | {count} |")

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _endpoint_adequacy_scorecard_report_text(payload: dict[str, Any]) -> str:
        summary = payload["summary"]
        scorecard = payload["scorecard"]
        lines = [
            "# Endpoint Adequacy Scorecard",
            "",
            "## Summary",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| endpoint_count | {summary['endpoint_count']} |",
            f"| adequate_endpoint_count | {summary['adequate_endpoint_count']} |",
            f"| coverage_gap_endpoint_count | {summary['coverage_gap_endpoint_count']} |",
            f"| contract_gap_endpoint_count | {summary['contract_gap_endpoint_count']} |",
            (
                f"| downstream_modeled_endpoint_count | "
                f"{summary['downstream_modeled_endpoint_count']} |"
            ),
            (
                f"| downstream_passthrough_only_endpoint_count | "
                f"{summary['downstream_passthrough_only_endpoint_count']} |"
            ),
            (
                f"| downstream_compatibility_reference_only_endpoint_count | "
                f"{summary['downstream_compatibility_reference_only_endpoint_count']} |"
            ),
            (
                f"| downstream_excluded_endpoint_count | "
                f"{summary['downstream_excluded_endpoint_count']} |"
            ),
            (
                f"| downstream_unowned_endpoint_count | "
                f"{summary['downstream_unowned_endpoint_count']} |"
            ),
            (
                f"| downstream_not_applicable_endpoint_count | "
                f"{summary['downstream_not_applicable_endpoint_count']} |"
            ),
        ]

        for section_name, title, value_header in (
            ("adequacy_status_breakdown", "Adequacy Status Breakdown", "Status"),
            ("coverage_status_breakdown", "Coverage Status Breakdown", "Coverage Status"),
            ("contract_status_breakdown", "Contract Status Breakdown", "Contract Status"),
            ("downstream_status_breakdown", "Downstream Status Breakdown", "Downstream Status"),
            ("source_kind_breakdown", "Source Kind Breakdown", "Source Kind"),
        ):
            breakdown = summary.get(section_name, {})
            if not breakdown:
                continue
            lines.extend(
                [
                    "",
                    f"## {title}",
                    "",
                    f"| {value_header} | Count |",
                    "|----------------|-------|",
                ]
            )
            for key, count in breakdown.items():
                lines.append(f"| {key} | {count} |")

        lines.extend(
            [
                "",
                "## Endpoint Scorecard",
                "",
                (
                    "| Endpoint | Source | Coverage | Contract | Adequacy | Downstream | "
                    "Semantics | Season Type | Support Windows | Staging Keys | "
                    "Transform Outputs | Input Schema Missing | Output Schema Missing |"
                ),
                (
                    "|----------|--------|----------|----------|----------|------------|"
                    "-----------|-------------|-----------------|--------------|-------------------|"
                    "----------------------|-----------------------|"
                ),
            ]
        )
        for row in scorecard:
            lines.append(
                f"| {row['endpoint_name']} | {row['source_kind']} | "
                f"{row['coverage_status']} | {row['contract_status']} | "
                f"{row['adequacy_status']} | {row['downstream_status']} | "
                f"{row['execution_semantics']} | {row['season_type_contract_status']} | "
                f"{row['support_window_count']} | {row['staging_key_count']} | "
                f"{row['transform_output_count']} | {row['input_schema_missing_count']} | "
                f"{row['output_schema_missing_count']} |"
            )

        lines.extend(
            [
                "",
                "## Coverage/Support Crosswalk",
                "",
                (
                    "| Endpoint | Coverage Gaps | Contract Gaps | Downstream Reasons | "
                    "Season Type Value Gaps |"
                ),
                "|----------|---------------|---------------|------------------|-----------------------|",
            ]
        )
        for row in scorecard:
            lines.append(
                f"| {row['endpoint_name']} | {row['coverage_gap_count']} | "
                f"{row['contract_gap_count']} | {row['downstream_reason_count']} | "
                f"{row['season_type_value_gap_count']} |"
            )

        lines.extend(
            [
                "",
                "## Temporal Support Ledger",
                "",
                "| Metric | Count |",
                "|--------|-------|",
                f"| endpoint_count | {summary['temporal_support_ledger']['endpoint_count']} |",
                f"| ledger_row_count | {summary['temporal_support_ledger']['ledger_row_count']} |",
                (
                    f"| support_window_count | "
                    f"{summary['temporal_support_ledger']['support_window_count']} |"
                ),
                (
                    f"| season_type_row_count | "
                    f"{summary['temporal_support_ledger']['season_type_row_count']} |"
                ),
                (
                    f"| untracked_season_type_row_count | "
                    f"{summary['temporal_support_ledger']['untracked_season_type_row_count']} |"
                ),
            ]
        )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _extraction_report_text(
        summary: dict[str, Any],
        definition_of_done: dict[str, Any],
    ) -> str:
        lines = [
            "# Endpoint Extraction Contract",
            "",
            "## Summary",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| endpoint_count | {summary['endpoint_count']} |",
            f"| in_scope_endpoint_count | {summary['in_scope_endpoint_count']} |",
            f"| extractable_endpoint_count | {summary['extractable_endpoint_count']} |",
            f"| partial_endpoint_count | {summary['partial_endpoint_count']} |",
            f"| blocked_endpoint_count | {summary['blocked_endpoint_count']} |",
            f"| excluded_endpoint_count | {summary['excluded_endpoint_count']} |",
            (f"| season_type_contract_open_count | {summary['season_type_contract_open_count']} |"),
            f"| ready_for_full_backfill | {summary['ready_for_full_backfill']} |",
        ]

        for section_name, title, value_header in (
            ("extractability_breakdown", "Extractability Breakdown", "Status"),
            ("execution_semantics_breakdown", "Execution Semantics Breakdown", "Semantics"),
            ("source_kind_breakdown", "Source Kind Breakdown", "Source Kind"),
            ("extraction_gap_breakdown", "Extraction Gap Breakdown", "Gap"),
            ("explicit_exclusion_breakdown", "Explicit Exclusion Breakdown", "Classification"),
        ):
            breakdown = summary.get(section_name, {})
            if not breakdown:
                continue
            lines.extend(
                [
                    "",
                    f"## {title}",
                    "",
                    f"| {value_header} | Count |",
                    "|----------------|-------|",
                ]
            )
            for key, count in breakdown.items():
                lines.append(f"| {key} | {count} |")

        excluded_endpoints = summary.get("excluded_endpoints", [])
        if excluded_endpoints:
            lines.extend(
                [
                    "",
                    "## Explicit Exclusions",
                    "",
                    "| Endpoint | Classification | Owner | Reason | Revalidation Path |",
                    "|----------|----------------|-------|--------|-------------------|",
                ]
            )
            for row in excluded_endpoints:
                lines.append(
                    f"| {row['endpoint_name']} | {row['classification']} | {row['owner']} | "
                    f"{row['reason']} | {row['revalidation_path']} |"
                )

        lines.extend(
            [
                "",
                "## Full Extraction Definition of Done",
                "",
                f"Ready for full backfill: **{definition_of_done['ready_for_full_backfill']}**",
                "",
                "| Check | Met |",
                "|-------|-----|",
            ]
        )
        for check in definition_of_done["checks"]:
            lines.append(f"| {check['name']} | {check['met']} |")

        lines.append("")
        return "\n".join(lines)

    def write_artifacts(
        self,
        artifacts: dict[str, Any],
        output_dir: Path | None = None,
    ) -> dict[str, Path]:
        destination = self._coverage_output_dir(output_dir)
        return self._write_artifacts(destination=destination, artifacts=artifacts)

    def write_endpoint_adequacy_scorecard(
        self,
        output_dir: Path | None = None,
        runtime_endpoint_classes: set[str] | None = None,
        runtime_version: str | None = None,
    ) -> dict[str, Path]:
        artifacts = self.build_artifacts(
            runtime_endpoint_classes=runtime_endpoint_classes,
            runtime_version=runtime_version,
        )
        destination = self._coverage_output_dir(output_dir)
        return self._write_artifacts(
            destination=destination,
            artifacts=artifacts,
            artifact_keys=_ENDPOINT_ADEQUACY_ARTIFACT_KEYS,
        )

    def _coverage_output_dir(self, output_dir: Path | None) -> Path:
        destination = (
            Path(output_dir)
            if output_dir is not None
            else self.project_root / "artifacts" / "endpoint-coverage"
        )
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    def _write_artifacts(
        self,
        destination: Path,
        artifacts: dict[str, Any],
        artifact_keys: tuple[str, ...] | None = None,
    ) -> dict[str, Path]:
        matrix_path = destination / "endpoint-coverage-matrix.json"
        summary_path = destination / "endpoint-coverage-summary.json"
        report_path = destination / "endpoint-coverage-report.md"
        support_matrix_path = destination / "endpoint-support-matrix.json"
        support_summary_path = destination / "endpoint-support-summary.json"
        temporal_support_ledger_path = destination / "endpoint-temporal-support-ledger.json"
        support_report_path = destination / "endpoint-support-report.md"
        extraction_matrix_path = destination / "endpoint-extraction-matrix.json"
        extraction_summary_path = destination / "endpoint-extraction-summary.json"
        extraction_report_path = destination / "endpoint-extraction-report.md"
        full_extraction_definition_path = destination / "full-extraction-definition.json"
        endpoint_adequacy_scorecard_path = destination / "endpoint-adequacy-scorecard.json"
        endpoint_adequacy_report_path = destination / "endpoint-adequacy-scorecard-report.md"
        written = {
            "matrix": matrix_path,
            "summary": summary_path,
            "report": report_path,
            "support_matrix": support_matrix_path,
            "support_summary": support_summary_path,
            "temporal_support_ledger": temporal_support_ledger_path,
            "support_report": support_report_path,
            "extraction_matrix": extraction_matrix_path,
            "extraction_summary": extraction_summary_path,
            "extraction_report": extraction_report_path,
            "full_extraction_definition": full_extraction_definition_path,
            "endpoint_adequacy_scorecard": endpoint_adequacy_scorecard_path,
            "endpoint_adequacy_report": endpoint_adequacy_report_path,
        }
        selected_keys = artifact_keys or tuple(written)

        for key in selected_keys:
            if key == "matrix":
                matrix_path.write_text(
                    json.dumps({"matrix": artifacts["matrix"]}, indent=2) + "\n",
                    encoding="utf-8",
                )
            elif key == "summary":
                summary_path.write_text(
                    json.dumps(artifacts["summary"], indent=2) + "\n",
                    encoding="utf-8",
                )
            elif key == "report":
                report_path.write_text(self._report_text(artifacts["summary"]), encoding="utf-8")
            elif key == "support_matrix":
                support_matrix_path.write_text(
                    json.dumps({"matrix": artifacts["support_matrix"]}, indent=2) + "\n",
                    encoding="utf-8",
                )
            elif key == "support_summary":
                support_summary_path.write_text(
                    json.dumps(artifacts["support_summary"], indent=2) + "\n",
                    encoding="utf-8",
                )
            elif key == "temporal_support_ledger":
                temporal_support_ledger_path.write_text(
                    json.dumps(artifacts["temporal_support_ledger"], indent=2) + "\n",
                    encoding="utf-8",
                )
            elif key == "support_report":
                support_report_path.write_text(
                    self._support_report_text(artifacts["support_summary"]),
                    encoding="utf-8",
                )
            elif key == "extraction_matrix":
                extraction_matrix_path.write_text(
                    json.dumps({"matrix": artifacts["extraction_matrix"]}, indent=2) + "\n",
                    encoding="utf-8",
                )
            elif key == "extraction_summary":
                extraction_summary_path.write_text(
                    json.dumps(artifacts["extraction_summary"], indent=2) + "\n",
                    encoding="utf-8",
                )
            elif key == "extraction_report":
                extraction_report_path.write_text(
                    self._extraction_report_text(
                        artifacts["extraction_summary"],
                        artifacts["full_extraction_definition"],
                    ),
                    encoding="utf-8",
                )
            elif key == "full_extraction_definition":
                full_extraction_definition_path.write_text(
                    json.dumps(artifacts["full_extraction_definition"], indent=2) + "\n",
                    encoding="utf-8",
                )
            elif key == "endpoint_adequacy_scorecard":
                endpoint_adequacy_scorecard_path.write_text(
                    json.dumps(artifacts["endpoint_adequacy_scorecard"], indent=2) + "\n",
                    encoding="utf-8",
                )
            elif key == "endpoint_adequacy_report":
                endpoint_adequacy_report_path.write_text(
                    self._endpoint_adequacy_scorecard_report_text(
                        artifacts["endpoint_adequacy_scorecard"]
                    ),
                    encoding="utf-8",
                )
            else:
                msg = f"Unknown endpoint coverage artifact key: {key}"
                raise ValueError(msg)

        return {key: written[key] for key in selected_keys}

    def write(
        self,
        output_dir: Path | None = None,
        runtime_endpoint_classes: set[str] | None = None,
        runtime_version: str | None = None,
    ) -> dict[str, Path]:
        artifacts = self.build_artifacts(
            runtime_endpoint_classes=runtime_endpoint_classes,
            runtime_version=runtime_version,
        )
        return self.write_artifacts(artifacts, output_dir=output_dir)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate endpoint coverage artifacts.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (defaults to cwd).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for generated artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    generator = EndpointCoverageGenerator(project_root=args.project_root)
    written = generator.write(output_dir=args.output_dir)
    for path in written.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
