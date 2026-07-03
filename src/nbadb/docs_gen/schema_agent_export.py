"""Export star-schema consumer metadata for agent catalog generation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nbadb.core.field_docs import resolved_field_description
from nbadb.schemas.consumer_metadata import infer_consumer_metadata
from nbadb.schemas.registry import _star_schema_registry

if TYPE_CHECKING:
    from nbadb.schemas.base import BaseSchema

_CONSUMER_METADATA_ATTR = "__consumer_metadata__"


def _schema_doc(schema_cls: type[BaseSchema]) -> str:
    doc = schema_cls.__doc__ or ""
    return " ".join(doc.split())


def _column_summaries(schema_cls: type[BaseSchema], *, table_name: str) -> list[dict[str, Any]]:
    schema = schema_cls.to_schema()
    summaries: list[dict[str, Any]] = []
    for column_name, column in schema.columns.items():
        metadata = dict(column.metadata or {})
        description, description_source = resolved_field_description(
            metadata.get("description"),
            column_name,
            table_name=table_name,
            tier="star",
        )
        summaries.append(
            {
                "name": column_name,
                "description": description,
                "description_source": description_source,
                "fk_ref": metadata.get("fk_ref"),
                "source": metadata.get("source"),
            }
        )
    return summaries


def export_schema_agent_metadata() -> dict[str, Any]:
    """Build a JSON-serializable agent catalog export from star Pandera schemas."""
    tables: list[dict[str, Any]] = []
    for table_name in sorted(_star_schema_registry()):
        schema_cls = _star_schema_registry()[table_name]
        explicit = getattr(schema_cls, _CONSUMER_METADATA_ATTR, None)
        if not isinstance(explicit, dict):
            explicit = {}
        consumer = infer_consumer_metadata(
            table_name,
            schema_doc=_schema_doc(schema_cls),
            explicit=explicit,
        )
        agent_intents = consumer.get("agent_intents", ())
        if isinstance(agent_intents, list | tuple):
            intents = [str(item) for item in agent_intents]
        else:
            intents = []
        tables.append(
            {
                "table": table_name,
                "schema_class": schema_cls.__name__,
                "description": _schema_doc(schema_cls),
                "grain": consumer.get("grain"),
                "agent_intents": intents,
                "scd2_notes": consumer.get("scd2_notes"),
                "join_hints": dict(consumer.get("join_hints", {}) or {}),
                "columns": _column_summaries(schema_cls, table_name=table_name),
            }
        )
    return {
        "version": 1,
        "table_count": len(tables),
        "tables": tables,
    }


def write_schema_agent_export(path: str | None = None) -> str:
    """Serialize agent metadata export to JSON and return the payload."""
    payload = export_schema_agent_metadata()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if path is not None:
        from pathlib import Path

        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"{text}\n", encoding="utf-8")
    return text
