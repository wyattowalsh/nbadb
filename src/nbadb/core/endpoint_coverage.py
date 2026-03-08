from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

from nbadb.orchestrate.staging_map import STAGING_MAP, StagingEntry

_COVERAGE_KEYS = ("covered", "runtime_gap", "staging_only", "extractor_only")

# Legacy/alternate extractor endpoint names mapped to canonical staging names.
_ENDPOINT_ALIASES: dict[str, str] = {
    "home_page_leaders": "homepage_leaders",
    "home_page_v2": "homepage_v2",
    "league_dash_player_bio_stats": "league_dash_player_bio",
    "league_hustle_stats_player": "league_hustle_player",
    "league_hustle_stats_team": "league_hustle_team",
    "player_career_by_college_rollup": "player_college_rollup",
    "player_dash_pt_defend": "player_dash_pt_shot_defend",
    "player_dashboard_game_splits": "player_dash_game_splits",
    "player_dashboard_general_splits": "player_dash_general_splits",
    "player_dashboard_last_n_games": "player_dash_last_n_games",
    "player_dashboard_shooting_splits": "player_dash_shooting_splits",
    "player_dashboard_team_performance": "player_dash_team_perf",
    "player_dashboard_year_over_year": "player_dash_yoy",
    "player_game_logs": "player_game_logs_v2",
    "player_game_streak_finder": "player_streak_finder",
    "shot_chart_lineup_detail": "shot_chart_lineup",
    "team_and_players_vs_players": "team_and_players_vs",
    "team_year_by_year_stats": "team_year_by_year",
}


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

    @staticmethod
    def _constant_string(value: ast.AST) -> str | None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        return None

    @staticmethod
    def _collect_runtime_refs(node: ast.AST) -> set[str]:
        refs: set[str] = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if not isinstance(child.func, ast.Attribute):
                continue
            if child.func.attr not in {"_from_nba_api", "_from_nba_api_multi"}:
                continue
            if not child.args:
                continue
            first_arg = child.args[0]
            if isinstance(first_arg, ast.Name):
                refs.add(first_arg.id)
            elif isinstance(first_arg, ast.Attribute):
                refs.add(first_arg.attr)
        return refs

    def _extractor_endpoint_map(self) -> dict[str, set[str]]:
        endpoint_map: dict[str, set[str]] = {}
        if not self.extract_stats_dir.exists():
            return endpoint_map

        for path in sorted(self.extract_stats_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue

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
                    elif (
                        isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and stmt.name == "extract"
                    ):
                        runtime_refs.update(self._collect_runtime_refs(stmt))

                if endpoint_name:
                    endpoint_map.setdefault(endpoint_name, set()).update(runtime_refs)

        normalized: dict[str, set[str]] = {}
        for endpoint_name, runtime_refs in endpoint_map.items():
            canonical = _ENDPOINT_ALIASES.get(endpoint_name, endpoint_name)
            normalized.setdefault(canonical, set()).update(runtime_refs)
        return normalized

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
        return classes, getattr(nba_api, "__version__", "unknown")

    def build_artifacts(
        self,
        runtime_endpoint_classes: set[str] | None = None,
        runtime_version: str | None = None,
    ) -> dict[str, Any]:
        extractor_map = self._extractor_endpoint_map()
        staging_patterns: dict[str, str] = {}
        for entry in self.staging_entries:
            canonical = _ENDPOINT_ALIASES.get(entry.endpoint_name, entry.endpoint_name)
            staging_patterns.setdefault(canonical, entry.param_pattern)

        runtime_classes = (
            set(runtime_endpoint_classes) if runtime_endpoint_classes is not None else None
        )
        if runtime_classes is None:
            runtime_classes, detected_version = self._discover_runtime_endpoint_classes()
            runtime_version = runtime_version or detected_version
        else:
            runtime_version = runtime_version or "provided"

        matrix: list[dict[str, Any]] = []

        for endpoint_name in sorted(staging_patterns):
            runtime_refs = sorted(extractor_map.get(endpoint_name, set()))
            extractor_present = endpoint_name in extractor_map
            runtime_match = bool(runtime_classes and set(runtime_refs) & runtime_classes)

            if extractor_present:
                coverage_status = (
                    "covered" if (not runtime_classes or runtime_match) else "runtime_gap"
                )
            else:
                coverage_status = "staging_only"

            matrix.append(
                {
                    "endpoint_name": endpoint_name,
                    "param_pattern": staging_patterns[endpoint_name],
                    "staging_present": True,
                    "extractor_present": extractor_present,
                    "runtime_refs": runtime_refs,
                    "runtime_match": runtime_match,
                    "coverage_status": coverage_status,
                }
            )

        for endpoint_name in sorted(set(extractor_map) - set(staging_patterns)):
            runtime_refs = sorted(extractor_map[endpoint_name])
            runtime_match = bool(runtime_classes and set(runtime_refs) & runtime_classes)
            matrix.append(
                {
                    "endpoint_name": endpoint_name,
                    "param_pattern": "extractor_only",
                    "staging_present": False,
                    "extractor_present": True,
                    "runtime_refs": runtime_refs,
                    "runtime_match": runtime_match,
                    "coverage_status": "extractor_only",
                }
            )

        coverage = {key: 0 for key in _COVERAGE_KEYS}
        heatmap: dict[str, dict[str, int | str]] = {}
        for row in matrix:
            status = row["coverage_status"]
            if status in coverage:
                coverage[status] += 1

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

        summary = {
            "runtime_version": runtime_version,
            "runtime_endpoint_class_count": len(runtime_classes),
            "staging_endpoint_count": len(staging_patterns),
            "extractor_endpoint_count": len(extractor_map),
            "coverage": coverage,
            "pattern_heatmap": [heatmap[key] for key in sorted(heatmap)],
        }

        return {"matrix": matrix, "summary": summary}

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

    def write(
        self,
        output_dir: Path | None = None,
        runtime_endpoint_classes: set[str] | None = None,
        runtime_version: str | None = None,
    ) -> dict[str, Path]:
        destination = (
            Path(output_dir)
            if output_dir is not None
            else self.project_root / "artifacts" / "endpoint-coverage"
        )
        destination.mkdir(parents=True, exist_ok=True)

        artifacts = self.build_artifacts(
            runtime_endpoint_classes=runtime_endpoint_classes,
            runtime_version=runtime_version,
        )

        matrix_path = destination / "endpoint-coverage-matrix.json"
        summary_path = destination / "endpoint-coverage-summary.json"
        report_path = destination / "endpoint-coverage-report.md"

        matrix_path.write_text(
            json.dumps({"matrix": artifacts["matrix"]}, indent=2) + "\n",
            encoding="utf-8",
        )
        summary_path.write_text(
            json.dumps(artifacts["summary"], indent=2) + "\n",
            encoding="utf-8",
        )
        report_path.write_text(self._report_text(artifacts["summary"]), encoding="utf-8")

        return {"matrix": matrix_path, "summary": summary_path, "report": report_path}


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
