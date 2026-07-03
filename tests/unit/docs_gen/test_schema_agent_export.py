from __future__ import annotations

from nbadb.docs_gen.schema_agent_export import export_schema_agent_metadata
from nbadb.schemas.star.agg_schemas import AggPlayerSeasonSchema


def test_export_includes_consumer_metadata_for_enriched_schemas() -> None:
    payload = export_schema_agent_metadata()

    assert payload["table_count"] > 0
    player_season = next(item for item in payload["tables"] if item["table"] == "agg_player_season")
    assert player_season["grain"] == "player-season"
    assert "scoring" in player_season["agent_intents"]
    assert player_season["schema_class"] == AggPlayerSeasonSchema.__name__


def test_export_covers_all_star_tables_with_grain_and_intents() -> None:
    payload = export_schema_agent_metadata()

    missing_grain = [item["table"] for item in payload["tables"] if not item.get("grain")]
    missing_intents = [item["table"] for item in payload["tables"] if not item.get("agent_intents")]
    assert missing_grain == []
    assert missing_intents == []


def test_export_covers_all_star_columns_with_descriptions() -> None:
    payload = export_schema_agent_metadata()

    columns = [column for table in payload["tables"] for column in table["columns"]]
    assert columns
    assert all(column["description"] for column in columns)
    assert all(column["description_source"] in {"metadata", "generated"} for column in columns)
