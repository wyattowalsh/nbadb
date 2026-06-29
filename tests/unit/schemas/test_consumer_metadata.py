from __future__ import annotations

from nbadb.schemas.consumer_metadata import infer_consumer_metadata


def test_infer_consumer_metadata_merges_explicit_overrides() -> None:
    metadata = infer_consumer_metadata(
        "agg_player_season",
        explicit={"agent_intents": ("scoring",)},
    )

    assert metadata["grain"] == "player-season"
    assert "scoring" in metadata["agent_intents"]


def test_infer_consumer_metadata_marks_scd2_dimensions() -> None:
    metadata = infer_consumer_metadata("dim_team_history")

    assert metadata["grain"] == "dimension-scd2"
    assert metadata.get("scd2_notes")
    assert "dim_team_history" in metadata.get("join_hints", {})
