from __future__ import annotations

from nbadb.chat.memory import MemoryStore


def test_memory_store_round_trip_preference_and_trajectory(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")

    preference = store.remember_preference("theme", "dark", notes="ui")
    assert preference.key == "theme"
    assert store.list_preferences()[0].value == "dark"

    trajectory = store.save_trajectory(
        "leaderboard",
        {
            "grain": "player-season",
            "sql_hash": "abc123",
            "chosen_surfaces": ["table"],
            "tags": ["scoring"],
        },
        session_id="sess-1",
    )
    assert trajectory.archetype == "leaderboard"

    hits = store.search_trajectories("scoring", limit=5)
    assert hits
    assert hits[0].sql_hash == "abc123"

    assert store.forget_preference("theme") is True
    assert store.list_preferences() == []
