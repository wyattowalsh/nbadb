from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

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


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _is_numeric_type(data_type: str) -> bool:
    normalized = data_type.upper()
    return any(
        token in normalized
        for token in (
            "BIGINT",
            "DECIMAL",
            "DOUBLE",
            "FLOAT",
            "HUGEINT",
            "INTEGER",
            "REAL",
            "SMALLINT",
            "TINYINT",
            "UBIGINT",
            "UINTEGER",
            "USMALLINT",
            "UTINYINT",
        )
    )


def _is_temporal_type(data_type: str) -> bool:
    normalized = data_type.upper()
    return normalized.startswith(("DATE", "TIME", "TIMESTAMP"))


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


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
                quoted_table = _quote_identifier(table_name)
                row_count_result = con.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()
                row_count = row_count_result[0] if row_count_result else 0

                columns_result = con.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = ? ORDER BY ordinal_position",
                    [table_name],
                ).fetchall()

                columns: list[dict] = []
                for col_name, col_type in columns_result:
                    quoted_col = _quote_identifier(col_name)
                    if row_count > 0:
                        null_result = con.execute(
                            f"SELECT "
                            f"COUNT(*) FILTER (WHERE {quoted_col} IS NULL), "
                            f"COUNT(DISTINCT {quoted_col}) "
                            f"FROM {quoted_table}"
                        ).fetchone()
                        null_count = int(null_result[0]) if null_result else 0
                        distinct_count = int(null_result[1]) if null_result else 0
                        null_pct = round(null_count * 100.0 / row_count, 2)
                    else:
                        null_count = 0
                        distinct_count = 0
                        null_pct = 0.0

                    profile = {
                        "name": col_name,
                        "type": col_type,
                        "nullPct": null_pct,
                        "nonNullCount": row_count - null_count,
                        "distinctCount": distinct_count,
                    }

                    if row_count > 0 and distinct_count > 0:
                        if _is_numeric_type(col_type):
                            stats = con.execute(
                                f"SELECT MIN({quoted_col}), MAX({quoted_col}), "
                                f"quantile_cont({quoted_col}, 0.5), "
                                f"quantile_cont({quoted_col}, 0.95) "
                                f"FROM {quoted_table}"
                            ).fetchone()
                            if stats:
                                profile.update(
                                    {
                                        "min": _json_value(stats[0]),
                                        "max": _json_value(stats[1]),
                                        "p50": _json_value(stats[2]),
                                        "p95": _json_value(stats[3]),
                                    }
                                )
                        elif _is_temporal_type(col_type):
                            stats = con.execute(
                                f"SELECT MIN({quoted_col}), MAX({quoted_col}) FROM {quoted_table}"
                            ).fetchone()
                            if stats:
                                profile.update(
                                    {
                                        "min": _json_value(stats[0]),
                                        "max": _json_value(stats[1]),
                                    }
                                )
                        elif distinct_count <= 20:
                            top_rows = con.execute(
                                f"SELECT {quoted_col} AS value, COUNT(*) AS count "
                                f"FROM {quoted_table} "
                                f"WHERE {quoted_col} IS NOT NULL "
                                f"GROUP BY {quoted_col} "
                                f"ORDER BY count DESC, value ASC "
                                f"LIMIT 5"
                            ).fetchall()
                            profile["topValues"] = [
                                {"value": _json_value(value), "count": int(count)}
                                for value, count in top_rows
                            ]

                    columns.append(profile)

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
