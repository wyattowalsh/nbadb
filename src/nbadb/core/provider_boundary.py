"""Deterministic architecture checks for the pinned ``nba_api`` boundary.

Endpoint declarations are intentionally imported by the extraction adapter and
extractor implementations.  Provider discovery/audit modules may also inspect
the installed package.  The rest of the application must consume nbadb-owned
contracts and Polars frames instead of importing or exposing upstream objects.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_ALLOWED_EXACT_PATHS = frozenset(
    {
        "contracts/fixture_manifest.py",
        "core/endpoint_coverage.py",
        "core/model_audit.py",
        "core/nba_api_competition.py",
        "core/nba_api_competition_occurrences.py",
        "core/nba_api_provenance.py",
        "core/nba_api_runtime_contract.py",
        "core/types.py",
    }
)
_RESTRICTED_PROVIDER_PREFIXES = (
    "nba_api.library.http",
    "nba_api.live.nba.library.http",
    "nba_api.stats.library",
    "nba_api.stats.static",
    "nba_api.stats.endpoints._parsers",
    "nba_api.stats.endpoints._expected_data",
)
_RESTRICTED_PROVIDER_IMPORT_PATHS = frozenset(
    {
        "contracts/fixture_manifest.py",
        "core/endpoint_coverage.py",
        "core/nba_api_competition.py",
        "core/nba_api_runtime_contract.py",
        "core/types.py",
        "extract/nba_api_adapter.py",
    }
)


@dataclass(frozen=True, slots=True, order=True)
class ProviderBoundaryIssue:
    """One stable, path-local provider-boundary violation."""

    relative_path: str
    line: int
    rule: str
    symbol: str


class ProviderBoundaryError(ValueError):
    """The production source tree violates the pinned provider boundary."""

    def __init__(self, issues: tuple[ProviderBoundaryIssue, ...]) -> None:
        self.issues = issues
        summary = ", ".join(
            f"{issue.relative_path}:{issue.line}:{issue.rule}:{issue.symbol}" for issue in issues
        )
        super().__init__(f"nba_api provider boundary failed: {summary}")


def _is_provider_module(module: str | None) -> bool:
    return module == "nba_api" or bool(module and module.startswith("nba_api."))


def _is_allowed_import_path(relative_path: str) -> bool:
    return relative_path.startswith("extract/") or relative_path in _ALLOWED_EXACT_PATHS


def _is_restricted_provider_module(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in _RESTRICTED_PROVIDER_PREFIXES
    )


def _annotation_roots(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    roots: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            roots.add(child.id)
    return roots


def _annotations(tree: ast.AST) -> list[tuple[int, ast.AST]]:
    found: list[tuple[int, ast.AST]] = []
    for node in ast.walk(tree):
        annotation: ast.AST | None = None
        if isinstance(node, ast.AnnAssign | ast.arg):
            annotation = node.annotation
        if annotation is not None:
            found.append((int(getattr(node, "lineno", 1)), annotation))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is not None:
            found.append((int(getattr(node, "lineno", 1)), node.returns))
    return found


def _scan_file(path: Path, *, source_root: Path) -> tuple[ProviderBoundaryIssue, ...]:
    relative_path = path.relative_to(source_root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
    except (OSError, UnicodeError, SyntaxError) as exc:
        return (
            ProviderBoundaryIssue(
                relative_path=relative_path,
                line=max(1, int(getattr(exc, "lineno", 1) or 1)),
                rule="source_unreadable",
                symbol=type(exc).__name__,
            ),
        )

    issues: list[ProviderBoundaryIssue] = []
    upstream_aliases: set[str] = set()
    allowed = _is_allowed_import_path(relative_path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_provider_module(alias.name):
                    continue
                symbol = alias.name
                upstream_aliases.add(alias.asname or alias.name.split(".", 1)[0])
                if _is_restricted_provider_module(alias.name) and (
                    relative_path not in _RESTRICTED_PROVIDER_IMPORT_PATHS
                ):
                    issues.append(
                        ProviderBoundaryIssue(
                            relative_path,
                            node.lineno,
                            "provider_private_import_outside_adapter",
                            symbol,
                        )
                    )
                elif not allowed:
                    issues.append(
                        ProviderBoundaryIssue(
                            relative_path,
                            node.lineno,
                            "provider_import_outside_boundary",
                            symbol,
                        )
                    )
        elif isinstance(node, ast.ImportFrom) and _is_provider_module(node.module):
            for alias in node.names:
                symbol = f"{node.module}.{alias.name}"
                upstream_aliases.add(alias.asname or alias.name)
                if alias.name == "*":
                    issues.append(
                        ProviderBoundaryIssue(
                            relative_path,
                            node.lineno,
                            "provider_star_import",
                            symbol,
                        )
                    )
                elif _is_restricted_provider_module(node.module or "") and (
                    relative_path not in _RESTRICTED_PROVIDER_IMPORT_PATHS
                ):
                    issues.append(
                        ProviderBoundaryIssue(
                            relative_path,
                            node.lineno,
                            "provider_private_import_outside_adapter",
                            symbol,
                        )
                    )
                elif not allowed:
                    issues.append(
                        ProviderBoundaryIssue(
                            relative_path,
                            node.lineno,
                            "provider_import_outside_boundary",
                            symbol,
                        )
                    )

    if upstream_aliases:
        for line, annotation in _annotations(tree):
            leaked = sorted(_annotation_roots(annotation) & upstream_aliases)
            for symbol in leaked:
                issues.append(
                    ProviderBoundaryIssue(
                        relative_path,
                        line,
                        "upstream_type_annotation",
                        symbol,
                    )
                )
    return tuple(sorted(set(issues)))


def provider_boundary_issues(project_root: Path | str) -> tuple[ProviderBoundaryIssue, ...]:
    """Return every deterministic boundary violation in production Python source."""

    root = Path(project_root).resolve()
    source_root = root / "src" / "nbadb"
    if not source_root.is_dir():
        return (
            ProviderBoundaryIssue(
                relative_path="src/nbadb",
                line=1,
                rule="source_root_missing",
                symbol="FileNotFoundError",
            ),
        )
    issues = [
        issue
        for path in sorted(source_root.rglob("*.py"))
        if "__pycache__" not in path.parts and path.is_file() and not path.is_symlink()
        for issue in _scan_file(path, source_root=source_root)
    ]
    return tuple(sorted(issues))


def require_provider_boundary(project_root: Path | str) -> None:
    """Fail closed when upstream imports or annotations escape the allowlist."""

    issues = provider_boundary_issues(project_root)
    if issues:
        raise ProviderBoundaryError(issues)


__all__ = [
    "ProviderBoundaryError",
    "ProviderBoundaryIssue",
    "provider_boundary_issues",
    "require_provider_boundary",
]
