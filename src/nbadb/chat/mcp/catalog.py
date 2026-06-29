from __future__ import annotations

from typing import Any

from nbadb.chat.catalog import default_catalog, export_table_index, load_agent_catalog_export


def search_catalog(query: str, *, limit: int = 12) -> list[dict[str, Any]]:
    catalog = default_catalog()
    export = load_agent_catalog_export()
    export_tables = export_table_index(export)
    hits: list[dict[str, Any]] = []
    for entry in catalog.entries:
        if not entry.matches(query):
            continue
        tables = []
        for table in entry.tables:
            metadata = export_tables.get(table, {})
            tables.append(
                {
                    "table": table,
                    "grain": metadata.get("grain"),
                    "agent_intents": metadata.get("agent_intents", []),
                }
            )
        hits.append(
            {
                "name": entry.name,
                "description": entry.description,
                "route": entry.route,
                "tables": tables,
            }
        )
        if len(hits) >= limit:
            break
    return hits
