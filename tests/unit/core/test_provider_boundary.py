from __future__ import annotations

from pathlib import Path

import pytest

from nbadb.core.provider_boundary import (
    ProviderBoundaryError,
    provider_boundary_issues,
    require_provider_boundary,
)


def _write(root: Path, relative: str, source: str) -> None:
    path = root / "src" / "nbadb" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_live_tree_keeps_provider_imports_and_types_inside_boundary() -> None:
    project_root = Path(__file__).parents[3]

    assert provider_boundary_issues(project_root) == ()
    require_provider_boundary(project_root)


def test_provider_import_outside_boundary_fails_with_exact_location(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "orchestrate/leak.py",
        "from nba_api.stats.endpoints import LeagueGameLog\n",
    )

    issues = provider_boundary_issues(tmp_path)

    assert [(item.relative_path, item.line, item.rule, item.symbol) for item in issues] == [
        (
            "orchestrate/leak.py",
            1,
            "provider_import_outside_boundary",
            "nba_api.stats.endpoints.LeagueGameLog",
        )
    ]
    with pytest.raises(ProviderBoundaryError, match="orchestrate/leak.py:1"):
        require_provider_boundary(tmp_path)


def test_provider_star_import_and_upstream_annotation_fail_even_in_extract(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "extract/leak.py",
        "from nba_api.stats.endpoints import *\n"
        "from nba_api.stats.library.http import NBAStatsResponse\n"
        "def leaked(value: NBAStatsResponse) -> NBAStatsResponse:\n"
        "    return value\n",
    )

    issues = provider_boundary_issues(tmp_path)

    assert {item.rule for item in issues} == {
        "provider_private_import_outside_adapter",
        "provider_star_import",
        "upstream_type_annotation",
    }
    assert sum(item.rule == "upstream_type_annotation" for item in issues) == 1


def test_provider_transport_or_static_internals_are_adapter_only(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "extract/stats/leak.py",
        "from nba_api.stats.library.http import NBAStatsResponse\n"
        "from nba_api.stats.static import players\n",
    )

    issues = provider_boundary_issues(tmp_path)

    assert [(item.rule, item.symbol) for item in issues] == [
        (
            "provider_private_import_outside_adapter",
            "nba_api.stats.library.http.NBAStatsResponse",
        ),
        (
            "provider_private_import_outside_adapter",
            "nba_api.stats.static.players",
        ),
    ]


def test_exact_fixture_generator_may_replay_provider_parser_but_neighbors_may_not(
    tmp_path: Path,
) -> None:
    source = (
        "import nba_api.live.nba.endpoints as live_endpoints\n"
        "import nba_api.stats.endpoints as stats_endpoints\n"
        "from nba_api.library.http import NBAResponse\n"
        "from nba_api.stats.library.http import NBAStatsResponse\n"
    )
    _write(tmp_path, "contracts/fixture_manifest.py", source)

    assert provider_boundary_issues(tmp_path) == ()

    _write(tmp_path, "contracts/fixture_manifest_copy.py", source)
    issues = provider_boundary_issues(tmp_path)

    assert {item.relative_path for item in issues} == {"contracts/fixture_manifest_copy.py"}
    assert {item.rule for item in issues} == {
        "provider_import_outside_boundary",
        "provider_private_import_outside_adapter",
    }


def test_missing_or_unreadable_source_fails_closed(tmp_path: Path) -> None:
    issues = provider_boundary_issues(tmp_path)

    assert len(issues) == 1
    assert issues[0].rule == "source_root_missing"
