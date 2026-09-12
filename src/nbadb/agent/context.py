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
            conn.execute("SET enable_external_access = false")
            return get_user_tables(conn)

    def get_columns(self, table_name: str) -> list[tuple[str, str]]:
        with duckdb.connect(str(self._path), read_only=True) as conn:
            conn.execute("SET enable_external_access = false")
            result = conn.execute(
                "SELECT column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_name = ? "
                "ORDER BY ordinal_position",
                [table_name],
            ).fetchall()
            return [(row[0], row[1]) for row in result]

    def build_prompt_context(self, question: str | None = None, *, table_cap: int = 8) -> str:
        """Build a ranked, bounded schema pack (not a full warehouse dump)."""
        tables = self.get_tables()
        if not tables:
            return "No tables found in the database."

        lines: list[str] = [
            "NBA rules:",
            "- season_year looks like 2024-25",
            "- filter season_type (default: Regular Season) for season-grain tables",
            "- dim_player / dim_team_history are SCD2: use is_current = TRUE for present-day names",
            "- fact_box_score_* is team-level; fact_player_game_* is player-level",
        ]

        ranked_tables: list[str] = []
        if question:
            export = load_agent_catalog_export()
            entries = self._catalog.relevant_entries(question, limit=table_cap)
            if entries:
                lines.append("\nRelevant semantic hints:")
                for entry in entries:
                    lines.append(f"- {entry.name}: {entry.description}")
                    for caveat in entry.scd2_notes():
                        lines.append(f"  Caveat: {caveat}")
                    for table in entry.tables:
                        if table in tables and table not in ranked_tables:
                            ranked_tables.append(table)
            export_lines = self._catalog.export_context_lines(question, export=export)
            if export_lines:
                lines.append("\nExport grain context:")
                for line in export_lines[:table_cap]:
                    lines.append(f"- {line}")

        if not ranked_tables:
            # Prefer star-ish tables first, then any remaining up to cap.
            preferred = [
                t
                for t in tables
                if t.startswith(("dim_", "fact_", "agg_", "analytics_", "bridge_"))
            ]
            ranked_tables = preferred[:table_cap] or tables[:table_cap]
        else:
            ranked_tables = ranked_tables[:table_cap]

        scd2_present = sorted(_SCD2_TABLES.intersection(tables))
        if scd2_present:
            lines.append("\nSCD2 join guidance:")
            for table in scd2_present:
                lines.append(f"- {table}: {_SCD2_GUIDANCE[table]}")

        lines.append("\nTop tables and columns:")
        # One connection for all column lookups.
        with duckdb.connect(str(self._path), read_only=True) as conn:
            conn.execute("SET enable_external_access = false")
            for table in ranked_tables:
                result = conn.execute(
                    "SELECT column_name, data_type "
                    "FROM information_schema.columns "
                    "WHERE table_name = ? "
                    "ORDER BY ordinal_position",
                    [table],
                ).fetchall()
                col_strs = [f"  - {name} ({dtype})" for name, dtype in result[:24]]
                lines.append(f"\n{table}:")
                lines.extend(col_strs)
        return "\n".join(lines)
