from __future__ import annotations

import hashlib
import json
import types
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from nbadb.orchestrate.discovery import (
    GameDiscoveryResult,
    PlayerIdDiscoveryResult,
    PlayerTeamSeasonDiscoveryResult,
)
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
            on_combo_covered=None,
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
    monkeypatch.setattr(module, "current_season", lambda: "2099-00")
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
    assert summary["status"] == "incomplete"
    assert summary["failure_type"] == "CoverageIncomplete"
    assert summary["coverage"]["requested"]["game_combo_count"] == 2
    assert summary["coverage"]["covered"]["game_combo_count"] == 1
    assert summary["coverage"]["missing"]["game_combo_count"] == 1
    assert summary["missing_units"]["game_combos"] == [
        {"season": "2024-25", "season_type": "Playoffs"}
    ]
    assert len(summary["artifacts"]["game_combo_artifacts"]) == 1
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
    monkeypatch.setattr(module, "current_season", lambda: "2099-00")
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
    assert summary["status"] == "incomplete"
    assert summary["failure_type"] == "CoverageIncomplete"
    assert summary["coverage"]["requested"]["player_team_season_pair_count"] == 2
    assert summary["coverage"]["covered"]["player_team_season_pair_count"] == 1
    assert summary["coverage"]["missing"]["player_team_season_pair_count"] == 1
    assert summary["missing_units"]["player_team_season_pairs"] == [
        {"season": "2025-26", "season_type": "Regular Season"}
    ]
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


def test_seed_attests_exact_result_failure_taxonomies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    game_pair = ("2024-25", "Playoffs")
    workload_pair = ("2025-26", "Regular Season")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "github_matrix": {
                    "include": [
                        {
                            "patterns": "player_season",
                            "season_start": "2024",
                            "season_end": "2024",
                        },
                        {
                            "patterns": "game",
                            "season_start": "2024",
                            "season_end": "2024",
                            "season_types": "Playoffs",
                        },
                        {
                            "patterns": "player_team_season",
                            "season_start": "2025",
                            "season_end": "2025",
                            "season_types": "Regular Season",
                        },
                    ]
                }
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

        async def discover_all_player_ids_result(
            self,
            *,
            season: str | None = None,
        ) -> PlayerIdDiscoveryResult:
            assert season == game_pair[0]
            return PlayerIdDiscoveryResult(
                ids=[],
                requested_season=season,
                source="common_all_players",
                failure_kind="no_data",
                failures_by_source={"common_all_players": "no_data"},
            )

        async def discover_game_ids_result(
            self,
            seasons: list[str],
            *,
            season_types: list[str],
            on_combo_covered=None,
        ) -> GameDiscoveryResult:
            assert (seasons, season_types) == ([game_pair[0]], [game_pair[1]])
            return GameDiscoveryResult(
                game_ids=[],
                raw=pl.DataFrame(),
                requested_combos=frozenset({game_pair}),
                covered_combos=frozenset(),
                failures_by_combo={game_pair: "transport"},
            )

        async def discover_player_team_season_params_result(
            self,
            seasons: list[str],
            *,
            season_types: list[str],
        ) -> PlayerTeamSeasonDiscoveryResult:
            assert (seasons, season_types) == ([workload_pair[0]], [workload_pair[1]])
            return PlayerTeamSeasonDiscoveryResult(
                params=[],
                requested_pairs=frozenset({workload_pair}),
                covered_pairs=frozenset(),
                failures_by_pair={workload_pair: "response"},
            )

    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(module, "current_season", lambda: game_pair[0])

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=tmp_path / "data" / "nba.duckdb",
        )
    )

    assert summary["status"] == "incomplete"
    assert summary["failure_type"] == "MultipleFailures"
    assert summary["failure_types"] == ["no_data", "response", "transport"]
    failures_by_kind = {failure["kind"]: failure for failure in summary["failures"]}
    assert failures_by_kind["player_ids_all"]["discovery_failures"] == [
        {"season": game_pair[0], "failure_kind": "no_data"}
    ]
    assert failures_by_kind["league_game_log"]["discovery_failures"] == [
        {
            "season": game_pair[0],
            "season_type": game_pair[1],
            "failure_kind": "transport",
        }
    ]
    assert failures_by_kind["player_team_season_workload"]["discovery_failures"] == [
        {
            "season": workload_pair[0],
            "season_type": workload_pair[1],
            "failure_kind": "response",
        }
    ]


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
            on_combo_covered=None,
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
            "discovery_errors": ["no_data"],
            "discovery_failures": [{"season": "1947-48", "failure_kind": "no_data"}],
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


def test_seed_writes_atomic_fail_closed_summary_before_discovery(
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
                            "patterns": "game",
                            "season_start": "2024",
                            "season_end": "2024",
                            "season_types": "Regular Season",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    duckdb_path = tmp_path / "data" / "nba.duckdb"
    summary_path = tmp_path / "artifacts" / "summary.json"
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    pair = ("2024-25", "Regular Season")
    empty_frame = pl.DataFrame(
        schema={"game_id": pl.String, "game_date": pl.String},
    )
    summary_replacements: list[Path] = []
    real_replace = module.os.replace

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        destination_path = Path(destination)
        if destination_path == summary_path:
            summary_replacements.append(destination_path)
        real_replace(source, destination)

    class FakeRegistry:
        def discover(self) -> None:
            initial = json.loads(summary_path.read_text(encoding="utf-8"))
            assert initial["status"] == "incomplete"
            assert initial["phase"] == "initialized"
            assert initial["manifest_path"] == str(manifest_path)
            assert initial["manifest_sha256"] == manifest_sha256
            assert initial["failure_type"] == "NotStarted"
            assert initial["failure_count"] == 1
            assert initial["coverage"]["requested"]["game_combo_count"] == 1
            assert initial["coverage"]["covered"]["game_combo_count"] == 0
            assert initial["missing_units"]["game_combos"] == [
                {"season": pair[0], "season_type": pair[1]}
            ]

    class FakeDiscovery:
        def __init__(self, _registry: object) -> None:
            return None

        async def discover_game_ids_result(
            self,
            seasons: list[str],
            *,
            season_types: list[str],
            on_combo_covered=None,
        ) -> GameDiscoveryResult:
            assert seasons == [pair[0]]
            assert season_types == [pair[1]]
            return GameDiscoveryResult(
                game_ids=[],
                raw=empty_frame,
                requested_combos=frozenset({pair}),
                covered_combos=frozenset({pair}),
                frames_by_combo={pair: empty_frame},
            )

    monkeypatch.setattr(module.os, "replace", recording_replace)
    monkeypatch.setattr(module, "current_season", lambda: "2099-00")
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
            summary_path=summary_path,
        )
    )

    assert summary["status"] == "complete"
    assert summary["manifest_path"] == str(manifest_path)
    assert summary["manifest_sha256"] == manifest_sha256
    assert summary["failure_count"] == 0
    assert summary["requested_exact_unit_count"] == 1
    assert summary["covered_exact_unit_count"] == 1
    assert summary["missing_exact_unit_count"] == 0
    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary
    assert len(summary_replacements) > 2
    assert not list(summary_path.parent.glob(f".{summary_path.name}.*.tmp"))
    artifact = summary["artifacts"]["game_combo_artifacts"][0]
    assert Path(artifact["artifact_path"]).exists()
    assert Path(artifact["manifest_path"]).exists()


def test_bootstrap_summary_attests_invalid_manifest_bytes(
    tmp_path: Path,
) -> None:
    module = _load_module()
    manifest_path = tmp_path / "manifest.json"
    manifest_bytes = b'{"lanes": [invalid-json]\n'
    manifest_path.write_bytes(manifest_bytes)
    summary_path = tmp_path / "artifacts" / "summary.json"

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=tmp_path / "data" / "nba.duckdb",
            summary_path=summary_path,
        )
    )

    assert summary["status"] == "incomplete"
    assert summary["phase"] == "planning"
    assert summary["manifest_path"] == str(manifest_path)
    assert summary["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert summary["failure_type"] == "JSONDecodeError"
    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary
    assert not list(summary_path.parent.glob(f".{summary_path.name}.*.tmp"))


def test_soft_deadline_preserves_completed_exact_player_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    seasons = ("1946-47", "1947-48")
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
    duckdb_path = tmp_path / "data" / "nba.duckdb"
    summary_path = tmp_path / "artifacts" / "summary.json"

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        calls: list[str] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_all_player_ids(self, *, season: str | None = None) -> list[int]:
            assert season is not None
            self.calls.append(season)
            if season == seasons[0]:
                return [1]
            await module.asyncio.Event().wait()
            raise AssertionError("unreachable")

    monkeypatch.setenv(module.DISCOVERY_SEED_CONCURRENCY_ENV, "1")
    monkeypatch.setattr(module, "current_season", lambda: "2099-00")
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(module, "player_ids_by_season_from_snapshot", lambda _seasons: {})

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
            summary_path=summary_path,
            deadline_seconds=0.5,
        )
    )

    first_scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=(seasons[0],),
        variant="historical",
    )
    store = DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    assert summary["status"] == "incomplete"
    assert summary["failure_type"] == "TimeoutError"
    assert summary["seeded_count"] == 1
    assert summary["seeded"] == [
        {
            "kind": "player_ids_all",
            "seasons": [seasons[0]],
            "count": 1,
        }
    ]
    assert summary["failures"] == [
        {
            "kind": "seed_run",
            "reason": "deadline_exceeded",
            "phase": "player_fallback",
            "failure_type": "TimeoutError",
        }
    ]
    assert summary["covered_units"]["player_seasons"] == [{"season": seasons[0]}]
    assert summary["missing_units"]["player_seasons"] == [{"season": seasons[1]}]
    assert summary["coverage"]["covered"]["player_scope_count"] == 1
    assert summary["coverage"]["missing"]["player_scope_count"] == 2
    assert store.load_ids(first_scope) == [1]
    assert Path(summary["artifacts"]["player_season_artifacts"][0]["artifact_path"]).exists()
    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary
    assert FakeDiscovery.calls == list(seasons)


def test_soft_deadline_preserves_completed_player_failure_bookkeeping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    seasons = ("1946-47", "1947-48")
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
        calls: list[str] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_all_player_ids_result(
            self,
            *,
            season: str | None = None,
        ) -> PlayerIdDiscoveryResult:
            assert season is not None
            self.calls.append(season)
            if season == seasons[0]:
                return PlayerIdDiscoveryResult(
                    ids=[],
                    requested_season=season,
                    source="common_all_players",
                    failure_kind="no_data",
                    failures_by_source={"common_all_players": "no_data"},
                )
            await module.asyncio.Event().wait()
            raise AssertionError("unreachable")

    monkeypatch.setenv(module.DISCOVERY_SEED_CONCURRENCY_ENV, "1")
    monkeypatch.setattr(module, "current_season", lambda: "2099-00")
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    monkeypatch.setattr(module, "player_ids_by_season_from_snapshot", lambda _seasons: {})

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=tmp_path / "data" / "nba.duckdb",
            summary_path=tmp_path / "artifacts" / "summary.json",
            deadline_seconds=0.5,
        )
    )

    assert summary["status"] == "incomplete"
    assert summary["failure_type"] == "MultipleFailures"
    assert summary["failure_types"] == ["TimeoutError", "no_data"]
    assert summary["failure_count"] == 2
    player_failure = next(
        failure for failure in summary["failures"] if failure["kind"] == "player_ids_all"
    )
    assert player_failure == {
        "kind": "player_ids_all",
        "seasons": [seasons[0]],
        "reason": "no_ids",
        "discovery_errors": ["no_data"],
        "discovery_failures": [{"season": seasons[0], "failure_kind": "no_data"}],
    }
    assert FakeDiscovery.calls == list(seasons)


def test_game_batch_fault_preserves_prior_exact_combo_without_unavailable_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    successful_pair = ("2023-24", "Playoffs")
    failed_pair = ("2024-25", "Regular Season")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "github_matrix": {
                    "include": [
                        {
                            "patterns": "game",
                            "season_start": "2023",
                            "season_end": "2023",
                            "season_types": "Playoffs",
                        },
                        {
                            "patterns": "game",
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
    successful_frame = pl.DataFrame({"game_id": ["001"], "game_date": ["2024-04-20"]})

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        def __init__(self, _registry: object) -> None:
            return None

        async def discover_game_ids_result(
            self,
            seasons: list[str],
            *,
            season_types: list[str],
            on_combo_covered=None,
        ) -> GameDiscoveryResult:
            pair = (seasons[0], season_types[0])
            if pair == failed_pair:
                raise ConnectionError("deterministic transport fault")
            assert pair == successful_pair
            return GameDiscoveryResult(
                game_ids=["001"],
                raw=successful_frame,
                requested_combos=frozenset({pair}),
                covered_combos=frozenset({pair}),
                frames_by_combo={pair: successful_frame},
            )

    monkeypatch.setattr(module, "current_season", lambda: "2099-00")
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    duckdb_path = tmp_path / "data" / "nba.duckdb"

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
            summary_path=tmp_path / "artifacts" / "summary.json",
        )
    )

    store = DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    assert summary["status"] == "incomplete"
    assert summary["failure_type"] == "ConnectionError"
    assert summary["failure_types"] == ["ConnectionError"]
    assert summary["covered_units"]["game_combos"] == [
        {"season": successful_pair[0], "season_type": successful_pair[1]}
    ]
    assert summary["missing_units"]["game_combos"] == [
        {"season": failed_pair[0], "season_type": failed_pair[1]}
    ]
    assert summary["failures"][0]["reason"] == "incomplete_combo_coverage"
    assert summary["failures"][0]["discovery_errors"] == ["ConnectionError"]
    assert "unavailable" not in json.dumps(summary).lower()
    cached = store.load_game_log_frame(
        DiscoveryArtifactScope(
            kind="league_game_log",
            seasons=(successful_pair[0],),
            season_types=(successful_pair[1],),
        )
    )
    assert cached is not None
    assert cached.to_dicts() == successful_frame.to_dicts()


def test_game_deadline_summary_retains_the_completed_batch(
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
                            "patterns": "game",
                            "season_start": "2023",
                            "season_end": "2023",
                            "season_types": "Regular Season",
                        },
                        {
                            "patterns": "game",
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

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        calls: list[tuple[str, str]] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_game_ids_result(
            self,
            seasons: list[str],
            *,
            season_types: list[str],
            on_combo_covered=None,
        ) -> GameDiscoveryResult:
            assert len(seasons) == 2
            assert season_types == ["Regular Season"]
            pair = (seasons[0], season_types[0])
            self.calls.append(pair)
            frame = pl.DataFrame({"game_id": ["001"], "game_date": ["2024-04-20"]})
            assert on_combo_covered is not None
            on_combo_covered(pair, frame)
            await module.asyncio.sleep(5)
            raise AssertionError("deadline should cancel the grouped discovery call")

    monkeypatch.setattr(module, "current_season", lambda: "2099-00")
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    duckdb_path = tmp_path / "data" / "nba.duckdb"

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
            summary_path=tmp_path / "artifacts" / "summary.json",
            deadline_seconds=0.5,
        )
    )

    completed_pair = FakeDiscovery.calls[0]
    assert summary["status"] == "incomplete"
    assert summary["failure_type"] == "TimeoutError"
    assert summary["seeded_count"] == 0
    assert summary["covered_units"]["game_combos"] == [
        {"season": completed_pair[0], "season_type": completed_pair[1]}
    ]
    cached = DiscoveryArtifactStore.from_duckdb_path(duckdb_path).load_game_log_frame(
        DiscoveryArtifactScope(
            kind="league_game_log",
            seasons=(completed_pair[0],),
            season_types=(completed_pair[1],),
        )
    )
    assert cached is not None


def test_workload_deadline_summary_retains_the_completed_batch(
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
                            "season_start": "2023",
                            "season_end": "2023",
                            "season_types": "Playoffs",
                        },
                        {
                            "patterns": "player_team_season",
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

    class FakeRegistry:
        def discover(self) -> None:
            return None

    class FakeDiscovery:
        calls: list[tuple[str, str]] = []

        def __init__(self, _registry: object) -> None:
            return None

        async def discover_player_team_season_params_result(
            self,
            seasons: list[str],
            *,
            season_types: list[str],
        ) -> PlayerTeamSeasonDiscoveryResult:
            pair = (seasons[0], season_types[0])
            self.calls.append(pair)
            if len(self.calls) > 1:
                await module.asyncio.sleep(5)
            return PlayerTeamSeasonDiscoveryResult(
                params=[
                    {
                        "player_id": 1,
                        "team_id": 10,
                        "season": pair[0],
                        "season_type": pair[1],
                    }
                ],
                requested_pairs=frozenset({pair}),
                covered_pairs=frozenset({pair}),
            )

    monkeypatch.setattr(module, "current_season", lambda: "2099-00")
    monkeypatch.setattr(module, "registry", FakeRegistry())
    monkeypatch.setattr(module, "EntityDiscovery", FakeDiscovery)
    duckdb_path = tmp_path / "data" / "nba.duckdb"

    summary = module.asyncio.run(
        module.seed_player_discovery_artifacts(
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
            summary_path=tmp_path / "artifacts" / "summary.json",
            deadline_seconds=0.5,
        )
    )

    completed_pair = FakeDiscovery.calls[0]
    assert summary["status"] == "incomplete"
    assert summary["failure_type"] == "TimeoutError"
    assert summary["seeded_count"] == 1
    assert summary["seeded"][0]["covered_pair_count"] == 1
    assert summary["covered_units"]["player_team_season_pairs"] == [
        {"season": completed_pair[0], "season_type": completed_pair[1]}
    ]
    coverage = PlayerTeamSeasonWorkloadStore.from_duckdb_path(duckdb_path).load_coverage()
    assert completed_pair in coverage.covered_pairs


def test_main_returns_nonzero_for_incomplete_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "summary.json"

    async def incomplete_seed(**_kwargs: object) -> dict[str, object]:
        return {"status": "incomplete", "failure_count": 1}

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: types.SimpleNamespace(
            manifest_path=tmp_path / "manifest.json",
            duckdb_path=tmp_path / "nba.duckdb",
            summary_path=summary_path,
        ),
    )
    monkeypatch.setattr(module, "seed_player_discovery_artifacts", incomplete_seed)

    assert module.main() == 1
