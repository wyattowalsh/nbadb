from __future__ import annotations

import json
import types
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from nbadb.orchestrate.discovery import GameDiscoveryResult, PlayerTeamSeasonDiscoveryResult
from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope, DiscoveryArtifactStore
from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore

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


def test_first_matrix_exact_scopes_match_current_manifest_cardinality(
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

    game_lanes = [
        {
            "patterns": "game" if index % 2 == 0 else "date",
            "season_start": "1946",
            "season_end": "2003",
            "season_types": "",
        }
        for index in range(8)
    ]
    game_lanes.append(
        {
            "patterns": "date",
            "season_start": "1946",
            "season_end": "1993",
            "season_types": "",
        }
    )
    cross_lanes = [
        {
            "patterns": "player_team_season",
            "season_start": "1946",
            "season_end": "2001",
            "season_types": "Regular Season",
        }
        for _index in range(4)
    ]
    cross_lanes.append(
        {
            "patterns": "player_team_season",
            "season_start": "1946",
            "season_end": "1989",
            "season_types": "Regular Season",
        }
    )
    manifest = {"github_matrix": {"include": [*game_lanes, *cross_lanes]}}

    assert 8 * 58 * 4 + 48 * 4 == 2_048
    assert len(module.game_discovery_pairs(manifest)) == 232
    assert 4 * 56 + 44 == 268
    workload_pairs = module.player_team_season_pairs(manifest)
    assert len(workload_pairs) == 56
    assert len({season for season, _season_type in workload_pairs}) == 56


def test_blank_season_types_expand_to_every_default_value() -> None:
    module = _load_module()
    pairs = module.game_discovery_pairs(
        {
            "github_matrix": {
                "include": [
                    {
                        "patterns": "game,date",
                        "season_start": "2024",
                        "season_end": "2024",
                        "season_types": "",
                    },
                    {
                        "patterns": "date",
                        "season_start": "2024",
                        "season_end": "2024",
                        "season_types": "",
                    },
                ]
            }
        }
    )

    assert pairs == tuple(("2024-25", season_type) for season_type in module.DEFAULT_SEASON_TYPES)


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


def test_player_discovery_scopes_prefers_current_matrix_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "season_range",
        lambda start=1946, end=None: [f"{start}-{str(start + 1)[-2:]}"],
    )

    scopes = module.player_discovery_scopes(
        {
            "github_matrix": {
                "include": [
                    {
                        "patterns": "player_season",
                        "season_start": "1946",
                        "season_end": "1946",
                    }
                ]
            },
            "lanes": [
                {
                    "patterns": ["player_season"],
                    "season_start": 1996,
                    "season_end": 1996,
                }
            ],
        }
    )

    assert [(scope.seasons, scope.variant) for scope in scopes] == [(("1946-47",), "historical")]


def test_game_seed_persists_only_explicitly_covered_combo_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "github_matrix": {
                    "include": [
                        {
                            "patterns": "game,date",
                            "season_start": "2024",
                            "season_end": "2024",
                            "season_types": "Regular Season,Playoffs",
                        },
                        {
                            "patterns": "date",
                            "season_start": "2024",
                            "season_end": "2024",
                            "season_types": "Regular Season",
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    requested = frozenset(
        {
            ("2024-25", "Regular Season"),
            ("2024-25", "Playoffs"),
        }
    )
    covered = frozenset({("2024-25", "Regular Season")})
    regular_frame = pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]})
    misleading_playoff_frame = pl.DataFrame({"game_id": ["002"], "game_date": ["2025-04-19"]})

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_game_ids_result(
            self,
            seasons: list[str],
            *,
            season_types: list[str],
        ) -> GameDiscoveryResult:
            self.calls.append((tuple(seasons), tuple(season_types)))
            return GameDiscoveryResult(
                game_ids=["001", "002"],
                raw=pl.concat([regular_frame, misleading_playoff_frame]),
                requested_combos=requested,
                covered_combos=covered,
                frames_by_combo={
                    ("2024-25", "Regular Season"): regular_frame,
                    ("2024-25", "Playoffs"): misleading_playoff_frame,
                },
            )

    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    duckdb_path = tmp_path / "data" / "nba.duckdb"

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )
    )

    store = DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    regular_cached = store.load_game_log_frame(
        DiscoveryArtifactScope(
            kind="league_game_log",
            seasons=("2024-25",),
            season_types=("Regular Season",),
        )
    )
    playoffs_cached = store.load_game_log_frame(
        DiscoveryArtifactScope(
            kind="league_game_log",
            seasons=("2024-25",),
            season_types=("Playoffs",),
        )
    )
    assert summary["game_combo_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["failures"][0]["missing_combos"] == [
        {"season": "2024-25", "season_type": "Playoffs"}
    ]
    assert regular_cached is not None
    assert regular_cached.to_dicts() == regular_frame.to_dicts()
    assert playoffs_cached is None
    assert FakeDiscovery.calls == [(("2024-25",), ("Regular Season", "Playoffs"))]


def test_player_team_seed_deduplicates_seasons_and_rejects_uncovered_pairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "github_matrix": {
                    "include": [
                        {
                            "patterns": "player_team_season",
                            "season_start": "2024",
                            "season_end": "2025",
                            "season_types": "Regular Season",
                        },
                        {
                            "patterns": "player_team_season",
                            "season_start": "2024",
                            "season_end": "2025",
                            "season_types": "Regular Season",
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    requested = frozenset(
        {
            ("2024-25", "Regular Season"),
            ("2025-26", "Regular Season"),
        }
    )
    covered = frozenset({("2024-25", "Regular Season")})

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_player_team_season_params_result(
            self,
            seasons: list[str],
            *,
            season_types: list[str],
        ) -> PlayerTeamSeasonDiscoveryResult:
            self.calls.append((tuple(seasons), tuple(season_types)))
            return PlayerTeamSeasonDiscoveryResult(
                params=[
                    {
                        "player_id": 1,
                        "team_id": 10,
                        "season": "2024-25",
                        "season_type": "Regular Season",
                    },
                    {
                        "player_id": 2,
                        "team_id": 20,
                        "season": "2025-26",
                        "season_type": "Regular Season",
                    },
                ],
                requested_pairs=requested,
                covered_pairs=covered,
            )

    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    duckdb_path = tmp_path / "data" / "nba.duckdb"

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )
    )

    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(duckdb_path)
    coverage = store.load_coverage(
        seasons=["2024-25", "2025-26"],
        season_types=["Regular Season"],
    )
    assert summary["player_team_season_pair_count"] == 2
    assert summary["player_team_season_unique_season_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["failures"][0]["missing_pairs"] == [
        {"season": "2025-26", "season_type": "Regular Season"}
    ]
    assert coverage.covered_pairs == {("2024-25", "Regular Season")}
    assert store.load_params() == [
        {
            "player_id": 1,
            "team_id": 10,
            "season": "2024-25",
            "season_type": "Regular Season",
        }
    ]
    assert FakeDiscovery.calls == [(("2024-25", "2025-26"), ("Regular Season",))]


def test_seed_refreshes_current_season_player_game_and_workload_caches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    current = "2025-26"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "github_matrix": {
                    "include": [
                        {
                            "patterns": "player_season,game,player_team_season",
                            "season_start": "2025",
                            "season_end": "2025",
                            "season_types": "Regular Season",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    duckdb_path = tmp_path / "data" / "nba.duckdb"
    artifact_store = DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    player_scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=(current,),
        variant="historical",
    )
    game_scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=(current,),
        season_types=("Regular Season",),
    )
    artifact_store.upsert_ids(player_scope, [1], provenance="stale-test-cache")
    artifact_store.upsert_frame(
        game_scope,
        pl.DataFrame({"game_id": ["old"], "game_date": ["2025-10-21"]}),
        provenance="stale-test-cache",
    )
    workload_store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(duckdb_path)
    workload_store.upsert(
        [
            {
                "player_id": 1,
                "team_id": 10,
                "season": current,
                "season_type": "Regular Season",
            }
        ],
        seasons=[current],
        season_types=["Regular Season"],
        covered_pairs={(current, "Regular Season")},
    )
    live_game_frame = pl.DataFrame({"game_id": ["new"], "game_date": ["2026-01-02"]})

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        player_calls: list[str] = []
        game_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        workload_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_all_player_ids(self, *, season: str | None = None) -> list[int]:
            assert season is not None
            self.player_calls.append(season)
            return [1, 2]

        async def discover_game_ids_result(
            self,
            seasons: list[str],
            *,
            season_types: list[str],
        ) -> GameDiscoveryResult:
            self.game_calls.append((tuple(seasons), tuple(season_types)))
            pair = (current, "Regular Season")
            return GameDiscoveryResult(
                game_ids=["new"],
                raw=live_game_frame,
                requested_combos=frozenset({pair}),
                covered_combos=frozenset({pair}),
                frames_by_combo={pair: live_game_frame},
            )

        async def discover_player_team_season_params_result(
            self,
            seasons: list[str],
            *,
            season_types: list[str],
        ) -> PlayerTeamSeasonDiscoveryResult:
            self.workload_calls.append((tuple(seasons), tuple(season_types)))
            pair = (current, "Regular Season")
            return PlayerTeamSeasonDiscoveryResult(
                params=[
                    {
                        "player_id": 2,
                        "team_id": 20,
                        "season": current,
                        "season_type": "Regular Season",
                    }
                ],
                requested_pairs=frozenset({pair}),
                covered_pairs=frozenset({pair}),
            )

    monkeypatch.setattr(module, "current_season", lambda: current)
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(
        module,
        "player_ids_by_season_from_snapshot",
        lambda _seasons: {current: [1]},
    )

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )
    )

    assert summary["failure_count"] == 0
    assert artifact_store.load_ids(player_scope) == [1, 2]
    assert artifact_store.load_game_log_frame(game_scope).to_dicts() == (live_game_frame.to_dicts())
    assert workload_store.load_params() == [
        {
            "player_id": 2,
            "team_id": 20,
            "season": current,
            "season_type": "Regular Season",
        }
    ]
    assert FakeDiscovery.player_calls == [current]
    assert FakeDiscovery.game_calls == [((current,), ("Regular Season",))]
    assert FakeDiscovery.workload_calls == [((current,), ("Regular Season",))]


def test_aggregate_only_player_seed_refreshes_stale_current_season_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    seasons = ("2024-25", "2025-26")
    current = seasons[-1]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"github_matrix": {"include": [{"patterns": "player"}]}}),
        encoding="utf-8",
    )
    duckdb_path = tmp_path / "data" / "nba.duckdb"
    store = DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    aggregate_scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=seasons,
        variant="historical",
    )
    store.upsert_ids(aggregate_scope, [10, 20], provenance="stale-aggregate-cache")

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        targeted_calls: list[str] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_all_player_ids(self, *, season: str | None = None) -> list[int]:
            assert season is not None
            self.targeted_calls.append(season)
            return [20, 30]

    monkeypatch.setattr(module, "season_range", lambda start=1946, end=None: list(seasons))
    monkeypatch.setattr(module, "current_season", lambda: current)
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(
        module,
        "player_ids_by_season_from_snapshot",
        lambda _seasons: {"2024-25": [10], current: [20]},
    )

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )
    )

    current_scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=(current,),
        variant="historical",
    )
    assert summary["scope_count"] == 1
    assert summary["failure_count"] == 0
    assert FakeDiscovery.targeted_calls == [current]
    assert store.load_ids(current_scope) == [20, 30]
    assert store.load_ids(aggregate_scope) == [10, 20, 30]


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
    monkeypatch.setattr(module, "player_ids_by_season_from_snapshot", lambda _seasons: {})

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=tmp_path / "data" / "nba.duckdb",
        )
    )

    assert summary["failure_count"] == 0
    assert summary["seeded_count"] == 3
    assert sorted(item["count"] for item in summary["seeded"]) == [1, 1, 2]


def test_seed_player_discovery_artifacts_snapshot_seeds_single_seasons(
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
            return None

        async def discover_all_player_ids_by_season(
            self,
            seasons: list[str],
        ) -> dict[str, list[int]]:
            raise AssertionError(f"live bulk discovery should not run: {seasons}")

        async def discover_all_player_ids(self, *, season: str | None = None) -> list[int]:
            raise AssertionError(f"targeted discovery should not run: {season}")

    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(
        module,
        "player_ids_by_season_from_snapshot",
        lambda seasons: {
            "1946-47": [1, 2],
            "1947-48": [2, 3],
        },
    )

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=tmp_path / "data" / "nba.duckdb",
        )
    )

    assert summary["failure_count"] == 0
    assert summary["seeded_count"] == 3
    assert sorted(item["count"] for item in summary["seeded"]) == [2, 2, 3]


def test_seed_player_discovery_artifacts_snapshot_hydrates_all_seasons_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    seasons = ("1946-47", "1947-48")
    ids_by_season = {
        "1946-47": [1, 2],
        "1947-48": [2, 3],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"lanes": [{"patterns": ["player"]}]}),
        encoding="utf-8",
    )
    snapshot_calls: list[tuple[str, ...]] = []

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        live_calls: list[tuple[str, ...]] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_all_player_ids_by_season(
            self,
            requested_seasons: list[str],
        ) -> dict[str, list[int]]:
            self.live_calls.append(tuple(requested_seasons))
            return ids_by_season

        async def discover_all_player_ids(self, *, season: str | None = None) -> list[int]:
            assert season is not None
            self.live_calls.append((season,))
            return ids_by_season[season]

    def snapshot_ids(requested_seasons: list[str]) -> dict[str, list[int]]:
        snapshot_calls.append(tuple(requested_seasons))
        return ids_by_season

    monkeypatch.setattr(module, "season_range", lambda start=1946, end=None: list(seasons))
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(module, "player_ids_by_season_from_snapshot", snapshot_ids)
    duckdb_path = tmp_path / "data" / "nba.duckdb"
    aggregate_scope = module.DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=seasons,
        variant="historical",
    )
    store = module.DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    store.upsert_ids(aggregate_scope, [999], provenance="legacy-partial")

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )
    )

    for season, expected_ids in ids_by_season.items():
        scope = module.DiscoveryArtifactScope(
            kind="player_ids_all",
            seasons=(season,),
            variant="historical",
        )
        assert store.load_ids(scope) == expected_ids
    assert store.load_ids(aggregate_scope) == [1, 2, 3]
    assert summary["failure_count"] == 0
    assert snapshot_calls == [seasons]
    assert FakeDiscovery.live_calls == []


def test_seed_player_discovery_artifacts_bulk_fills_snapshot_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    seasons = ("1946-47", "1947-48")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"lanes": [{"patterns": ["player"]}]}),
        encoding="utf-8",
    )

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        bulk_calls: list[tuple[str, ...]] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_all_player_ids_by_season(
            self,
            requested_seasons: list[str],
        ) -> dict[str, list[int]]:
            self.bulk_calls.append(tuple(requested_seasons))
            return {"1947-48": [2, 3]}

        async def discover_all_player_ids(self, *, season: str | None = None) -> list[int]:
            raise AssertionError(f"targeted discovery should not run: {season}")

    monkeypatch.setattr(module, "season_range", lambda start=1946, end=None: list(seasons))
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(
        module,
        "player_ids_by_season_from_snapshot",
        lambda _seasons: {"1946-47": [1, 2]},
    )
    duckdb_path = tmp_path / "data" / "nba.duckdb"

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )
    )

    aggregate_scope = module.DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=seasons,
        variant="historical",
    )
    store = module.DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    assert summary["failure_count"] == 0
    assert store.load_ids(aggregate_scope) == [1, 2, 3]
    assert FakeDiscovery.bulk_calls == [("1947-48",)]


def test_seed_player_discovery_artifacts_rejects_partial_aggregate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    seasons = ("1946-47", "1947-48")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"lanes": [{"patterns": ["player"]}]}),
        encoding="utf-8",
    )

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        targeted_calls: list[str] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_all_player_ids_by_season(
            self,
            _requested_seasons: list[str],
        ) -> dict[str, list[int]]:
            return {}

        async def discover_all_player_ids(self, *, season: str | None = None) -> list[int]:
            assert season is not None
            self.targeted_calls.append(season)
            return []

    monkeypatch.setattr(module, "season_range", lambda start=1946, end=None: list(seasons))
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(
        module,
        "player_ids_by_season_from_snapshot",
        lambda _seasons: {"1946-47": [1, 2]},
    )
    duckdb_path = tmp_path / "data" / "nba.duckdb"

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )
    )

    aggregate_scope = module.DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=seasons,
        variant="historical",
    )
    store = module.DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    assert summary["failure_count"] == 1
    assert summary["failures"] == [
        {
            "kind": "player_ids_all",
            "seasons": list(seasons),
            "reason": "incomplete_season_coverage",
            "missing_seasons": ["1947-48"],
            "resolved_season_count": 1,
            "requested_season_count": 2,
        }
    ]
    assert store.load_ids(aggregate_scope) == []
    assert FakeDiscovery.targeted_calls == ["1947-48"]


def test_seed_player_discovery_artifacts_bulk_seeds_single_seasons(
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
        fallback_calls: list[str] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_all_player_ids_by_season(
            self,
            seasons: list[str],
        ) -> dict[str, list[int]]:
            assert sorted(seasons) == ["1946-47", "1947-48"]
            return {
                "1946-47": [1, 2],
                "1947-48": [2, 3],
            }

        async def discover_all_player_ids(self, *, season: str | None = None) -> list[int]:
            assert season is not None
            self.fallback_calls.append(season)
            return [int(season[:4])]

    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(module, "player_ids_by_season_from_snapshot", lambda _seasons: {})

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=tmp_path / "data" / "nba.duckdb",
        )
    )

    assert summary["failure_count"] == 0
    assert summary["seeded_count"] == 3
    assert sorted(item["count"] for item in summary["seeded"]) == [2, 2, 3]
    assert FakeDiscovery.fallback_calls == []


def test_seed_player_discovery_artifacts_seeds_single_seasons_concurrently(
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
                        "season_end": 1948,
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
        active = 0
        max_active = 0

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_all_player_ids(self, *, season: str | None = None) -> list[int]:
            assert season is not None
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
            try:
                await module.asyncio.sleep(0.01)
                return [int(season[:4])]
            finally:
                type(self).active -= 1

    monkeypatch.setenv(module.DISCOVERY_SEED_CONCURRENCY_ENV, "3")
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(module, "player_ids_by_season_from_snapshot", lambda _seasons: {})

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=tmp_path / "data" / "nba.duckdb",
        )
    )

    assert summary["failure_count"] == 0
    assert summary["seeded_count"] == 4
    assert FakeDiscovery.max_active > 1
