from __future__ import annotations

import json
from pathlib import Path

import duckdb


def _layer_from_prefix(table_name: str) -> str:
    """Derive the logical layer from a table name prefix."""
    if table_name.startswith("raw_"):
        return "raw"
    if table_name.startswith("stg_"):
        return "staging"
    if table_name.startswith("dim_"):
        return "dimension"
    if table_name.startswith("fact_"):
        return "fact"
    if table_name.startswith("bridge_"):
        return "bridge"
    if table_name.startswith("agg_"):
        return "aggregate"
    if table_name.startswith("analytics_"):
        return "analytics"
    return "other"


class TableProfileGenerator:
    """Generate per-table profile data from a DuckDB database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def generate(self) -> list[dict]:
        """Return per-table profile data."""
        if not self.db_path.exists():
            return []

        con = duckdb.connect(str(self.db_path), read_only=True)
        try:
            tables_result = con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()

            if not tables_result:
                return []

            profiles: list[dict] = []
            for (table_name,) in tables_result:
                row_count_result = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
                row_count = row_count_result[0] if row_count_result else 0

                columns_result = con.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = ? ORDER BY ordinal_position",
                    [table_name],
                ).fetchall()

                columns: list[dict] = []
                for col_name, col_type in columns_result:
                    if row_count > 0:
                        null_result = con.execute(
                            f'SELECT COUNT(*) FILTER (WHERE "{col_name}" IS NULL) '
                            f'* 100.0 / COUNT(*) FROM "{table_name}"'
                        ).fetchone()
                        null_pct = round(null_result[0], 2) if null_result else 0.0
                    else:
                        null_pct = 0.0

                    columns.append(
                        {
                            "name": col_name,
                            "type": col_type,
                            "nullPct": null_pct,
                        }
                    )

                profiles.append(
                    {
                        "table": table_name,
                        "layer": _layer_from_prefix(table_name),
                        "rowCount": row_count,
                        "columnCount": len(columns),
                        "columns": columns,
                    }
                )

            return profiles
        finally:
            con.close()


def generate_table_profile_json(db_path: str | Path) -> str:
    """Generate a JSON string of table profile data."""
    generator = TableProfileGenerator(db_path)
    profiles = generator.generate()
    return json.dumps(profiles, indent=2, sort_keys=False)
