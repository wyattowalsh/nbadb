from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb

from nbadb.chat.catalog import (
    SemanticCatalog,
    default_catalog,
    load_agent_catalog_export,
)

if TYPE_CHECKING:
    from pathlib import Path

_SCD2_TABLES = frozenset({"dim_player", "dim_team_history"})
_SCD2_GUIDANCE = {
    "dim_player": "Filter is_current = TRUE when joining for present-day player names.",
    "dim_team_history": "Filter is_current = TRUE when joining for present-day team identity.",
}


class SchemaContext:
    def __init__(self, duckdb_path: Path, catalog: SemanticCatalog | None = None) -> None:
        self._path = duckdb_path
        self._catalog = catalog or default_catalog()

    def get_tables(self) -> list[str]:
        from nbadb.core.db import get_user_tables

        with duckdb.connect(str(self._path), read_only=True) as conn:
            return get_user_tables(conn)

    def get_columns(self, table_name: str) -> list[tuple[str, str]]:
        with duckdb.connect(str(self._path), read_only=True) as conn:
            result = conn.execute(
                "SELECT column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_name = ? "
                "ORDER BY ordinal_position",
                [table_name],
            ).fetchall()
            return [(row[0], row[1]) for row in result]

    def build_prompt_context(self, question: str | None = None) -> str:
        tables = self.get_tables()
        if not tables:
            return "No tables found in the database."
        lines: list[str] = ["Available tables and columns:"]
        if question:
            export = load_agent_catalog_export()
            entries = self._catalog.relevant_entries(question)
            if entries:
                lines.append("\nRelevant semantic hints:")
                for entry in entries:
                    lines.append(f"- {entry.name}: {entry.description}")
                    for caveat in entry.scd2_notes():
                        lines.append(f"  Caveat: {caveat}")
            export_lines = self._catalog.export_context_lines(question, export=export)
            if export_lines:
                lines.append("\nExport grain context:")
                for line in export_lines:
                    lines.append(f"- {line}")
        scd2_present = sorted(_SCD2_TABLES.intersection(tables))
        if scd2_present:
            lines.append("\nSCD2 join guidance:")
            for table in scd2_present:
                lines.append(f"- {table}: {_SCD2_GUIDANCE[table]}")
        for table in tables:
            cols = self.get_columns(table)
            col_strs = [f"  - {name} ({dtype})" for name, dtype in cols]
            lines.append(f"\n{table}:")
            lines.extend(col_strs)
        return "\n".join(lines)
