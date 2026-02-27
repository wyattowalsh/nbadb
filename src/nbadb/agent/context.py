from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from pathlib import Path


class SchemaContext:
    def __init__(self, duckdb_path: Path) -> None:
        self._path = duckdb_path

    def get_tables(self) -> list[str]:
        with duckdb.connect(str(self._path), read_only=True) as conn:
            result = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' "
                "AND table_name NOT LIKE '\\_%' ESCAPE '\\' "
                "ORDER BY table_name"
            ).fetchall()
            return [row[0] for row in result]

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

    def build_prompt_context(self) -> str:
        tables = self.get_tables()
        if not tables:
            return "No tables found in the database."
        lines: list[str] = ["Available tables and columns:"]
        for table in tables:
            cols = self.get_columns(table)
            col_strs = [f"  - {name} ({dtype})" for name, dtype in cols]
            lines.append(f"\n{table}:")
            lines.extend(col_strs)
        return "\n".join(lines)
