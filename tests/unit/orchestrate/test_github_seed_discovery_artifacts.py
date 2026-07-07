from __future__ import annotations

import json
import types
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "scripts" / "seed_discovery_artifacts.py"
)
MODULE_CODE = compile(MODULE_PATH.read_text(encoding="utf-8"), str(MODULE_PATH), "exec")


def _load_module():
    module = types.ModuleType("github_seed_discovery_artifacts")
    module.__file__ = str(MODULE_PATH)
    exec(MODULE_CODE, module.__dict__)
    return module


def test_player_discovery_scopes_include_per_season_and_aggregate_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "season_range",
        lambda start=1946, end=None: [
            f"{year}-{str(year + 1)[-2:]}" for year in range(start, (end or start) + 1)
        ],
    )

    scopes = module.player_discovery_scopes(
        {
            "lanes": [
                {
                    "patterns": ["player_season"],
                    "season_start": 1946,
                    "season_end": 1947,
                    "resume_only": False,
                },
                {
                    "patterns": ["team_season"],
                    "season_start": 1946,
                    "season_end": 1947,
                    "resume_only": False,
                },
            ]
        }
    )

    assert [(scope.kind, scope.seasons, scope.variant) for scope in scopes] == [
        ("player_ids_all", ("1946-47",), "historical"),
        ("player_ids_all", ("1947-48",), "historical"),
        ("player_ids_all", ("1946-47", "1947-48"), "historical"),
    ]


def test_player_discovery_scopes_skip_resume_only_lanes() -> None:
    module = _load_module()

    assert (
        module.player_discovery_scopes(
            {
                "lanes": [
                    {
                        "patterns": ["player_season"],
                        "season_start": 1946,
                        "season_end": 1946,
                        "resume_only": True,
                    }
                ]
            }
        )
        == ()
    )


def test_seed_player_discovery_artifacts_reuses_per_season_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "patterns": ["player_season"],
                        "season_start": 1946,
                        "season_end": 1947,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        def __init__(self, _registry: object) -> None:
            self.calls: list[str] = []

        async def discover_all_player_ids(self, *, season: str | None = None) -> list[int]:
            assert season is not None
            self.calls.append(season)
            return [int(season[:4])]

    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=tmp_path / "data" / "nba.duckdb",
        )
    )

    assert summary["failure_count"] == 0
    assert summary["seeded_count"] == 3
    assert sorted(item["count"] for item in summary["seeded"]) == [1, 1, 2]
