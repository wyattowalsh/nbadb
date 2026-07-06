from __future__ import annotations

from nbadb.chat.catalog import CatalogEntry, SemanticCatalog
from nbadb.chat.mcp import catalog as catalog_tools
from nbadb.chat.mcp import memory as memory_tools
from nbadb.chat.memory import MemoryStore


def test_mcp_memory_tools_round_trip(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")

    preference = memory_tools.remember_preference(
        store,
        "default_metric",
        "points",
        session_id="sess-1",
        notes="leaderboard default",
    )
    assert preference.key == "default_metric"
    assert preference.session_id == "sess-1"
    assert memory_tools.list_preferences(store)[0].value == "points"

    trajectory = memory_tools.save_trajectory(
        store,
        "leaderboard",
        {"tags": ["scoring"], "sql_hash": "abc123"},
        session_id="sess-1",
    )
    assert trajectory.sql_hash == "abc123"
    assert memory_tools.search_trajectories(store, "scoring")[0].sql_hash == "abc123"
    assert (
        memory_tools.forget_memory(
            store,
            "default_metric",
            session_id="sess-1",
            confirm=True,
        )
        is True
    )


def test_mcp_memory_mutations_require_session_scope(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")

    for call in (
        lambda: memory_tools.remember_preference(store, "metric", "points"),
        lambda: memory_tools.save_trajectory(store, "leaderboard", {"sql_hash": "abc123"}),
        lambda: memory_tools.forget_memory(store, "metric", confirm=True),
    ):
        try:
            call()
        except ValueError as exc:
            assert "session_id" in str(exc)
        else:
            raise AssertionError("expected memory mutation to require session_id")


def test_mcp_memory_forget_requires_explicit_confirmation(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    memory_tools.remember_preference(store, "default_metric", "points", session_id="sess-1")

    try:
        memory_tools.forget_memory(store, "default_metric", session_id="sess-1")
    except ValueError as exc:
        assert "confirm=True" in str(exc)
    else:
        raise AssertionError("expected forget_memory to require confirm=True")


def test_mcp_catalog_search_includes_export_metadata(monkeypatch) -> None:
    catalog = SemanticCatalog(
        entries=(
            CatalogEntry(
                name="player season scoring",
                description="Season scoring leaders.",
                tables=("agg_player_season",),
                aliases=("scoring",),
                route="player_season_scoring",
                sql_template="SELECT 1",
            ),
        )
    )
    monkeypatch.setattr(catalog_tools, "default_catalog", lambda: catalog)
    monkeypatch.setattr(
        catalog_tools,
        "load_agent_catalog_export",
        lambda: {
            "tables": [
                {
                    "table": "agg_player_season",
                    "grain": "player-season",
                    "agent_intents": ["scoring"],
                }
            ]
        },
    )

    hits = catalog_tools.search_catalog("scoring")

    assert hits == [
        {
            "name": "player season scoring",
            "description": "Season scoring leaders.",
            "route": "player_season_scoring",
            "tables": [
                {
                    "table": "agg_player_season",
                    "grain": "player-season",
                    "agent_intents": ["scoring"],
                }
            ],
        }
    ]
