from __future__ import annotations

from nbadb.chat.memory import (
    FindingRecord,
    MemoryPromotionMode,
    ProfileRecord,
    TemplateRecord,
    TrajectoryRecord,
)


def test_template_record_accepts_promotion_mode() -> None:
    record = TemplateRecord(
        name="leaderboard",
        payload={"sql": "SELECT 1"},
        promotion_mode="balanced",
    )

    assert record.promotion_mode is MemoryPromotionMode.BALANCED


def test_finding_record_derives_fields_from_metadata() -> None:
    record = FindingRecord(
        title="Safe query",
        metadata={
            "tags": ["sql", "safety"],
            "entities": ["dim_player"],
            "metrics": "points",
            "sql_hash": "abc123",
            "confidence": 0.9,
        },
    )

    assert record.tags == ("sql", "safety")
    assert record.entities == ("dim_player",)
    assert record.metrics == ("points",)
    assert record.source_sql_hash == "abc123"
    assert record.confidence == 0.9


def test_profile_record_accepts_key_value() -> None:
    record = ProfileRecord(key="theme", value="dark", notes="ui preference")
    assert record.key == "theme"
    assert record.value == "dark"


def test_trajectory_record_derives_fields_from_payload() -> None:
    record = TrajectoryRecord(
        archetype="leaderboard",
        payload={
            "grain": "player-season",
            "sql_hash": "abc123",
            "chosen_surfaces": ["table"],
            "tags": "scoring",
        },
        session_id="sess-1",
    )

    assert record.grain == "player-season"
    assert record.sql_hash == "abc123"
    assert record.chosen_surfaces == ("table",)
    assert record.tags == ("scoring",)
