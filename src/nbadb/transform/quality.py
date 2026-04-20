from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

import duckdb
from loguru import logger

from nbadb.core.types import validate_sql_identifier


class CheckLayer(StrEnum):
    STRUCTURAL = "structural"
    RELATIONAL = "relational"
    STATISTICAL = "statistical"


@dataclass
class QualityResult:
    table: str
    check_type: str
    layer: CheckLayer
    passed: bool
    message: str
    details: dict | None = None


@dataclass
class DataQualityMonitor:
    conn: duckdb.DuckDBPyConnection
    results: list[QualityResult] = field(default_factory=list)

    # -- Layer 1: Structural (single-table) -----------------------------------

    def check_row_count_anomaly(
        self,
        table: str,
        current_count: int,
        historical_avg: float,
        historical_std: float,
        threshold: float = 2.0,
    ) -> QualityResult:
        if historical_std == 0:
            passed = True
        else:
            z_score = abs(current_count - historical_avg) / historical_std
            passed = z_score <= threshold
        result = QualityResult(
            table=table,
            check_type="row_count_anomaly",
            layer=CheckLayer.STRUCTURAL,
            passed=passed,
            message=(
                f"{table}: {current_count} rows "
                f"(avg={historical_avg:.0f}, std={historical_std:.0f})"
            ),
        )
        self.results.append(result)
        if not passed:
            logger.warning(result.message)
        return result

    def check_schema_drift(
        self,
        table: str,
        expected_hash: str,
        current_columns: list[str],
        current_types: list[str] | None = None,
    ) -> QualityResult:
        if current_types and len(current_types) == len(current_columns):
            pairs = sorted(zip(current_columns, current_types, strict=True))
            raw = ",".join(f"{c}:{t}" for c, t in pairs)
        else:
            raw = ",".join(sorted(current_columns))
        current_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        passed = current_hash == expected_hash
        result = QualityResult(
            table=table,
            check_type="schema_drift",
            layer=CheckLayer.STRUCTURAL,
            passed=passed,
            message=(
                f"{table}: schema {'unchanged' if passed else 'CHANGED'} "
                f"(expected={expected_hash}, got={current_hash})"
            ),
            details={"expected": expected_hash, "actual": current_hash},
        )
        self.results.append(result)
        if not passed:
            logger.warning(result.message)
        return result

    def check_null_rate(
        self,
        table: str,
        column: str,
        max_null_fraction: float = 0.0,
    ) -> QualityResult:
        validate_sql_identifier(table)
        validate_sql_identifier(column)
        query = f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE {column} IS NULL) AS nulls
            FROM {table}
        """
        row = self.conn.execute(query).fetchone()
        assert row is not None
        total, nulls = row
        fraction = nulls / total if total > 0 else 0.0
        passed = fraction <= max_null_fraction
        result = QualityResult(
            table=table,
            check_type="null_rate",
            layer=CheckLayer.STRUCTURAL,
            passed=passed,
            message=(
                f"{table}.{column}: {nulls}/{total} nulls "
                f"({fraction:.2%}, max={max_null_fraction:.2%})"
            ),
            details={
                "column": column,
                "nulls": nulls,
                "total": total,
                "fraction": fraction,
            },
        )
        self.results.append(result)
        if not passed:
            logger.warning(result.message)
        return result

    def check_uniqueness(
        self,
        table: str,
        columns: list[str],
    ) -> QualityResult:
        validate_sql_identifier(table)
        for col in columns:
            validate_sql_identifier(col)
        cols = ", ".join(columns)
        query = f"""
            SELECT COUNT(*) - COUNT(DISTINCT ({cols}))
            FROM {table}
        """
        row = self.conn.execute(query).fetchone()
        assert row is not None
        duplicates = row[0]
        passed = duplicates == 0
        result = QualityResult(
            table=table,
            check_type="uniqueness",
            layer=CheckLayer.STRUCTURAL,
            passed=passed,
            message=(f"{table}[{cols}]: {'unique' if passed else f'{duplicates} duplicates'}"),
            details={"columns": columns, "duplicates": duplicates},
        )
        self.results.append(result)
        if not passed:
            logger.warning(result.message)
        return result

    # -- Layer 2: Relational (cross-table) ------------------------------------

    def check_referential_integrity(
        self,
        fact_table: str,
        fk_column: str,
        dim_table: str,
        pk_column: str,
    ) -> QualityResult:
        validate_sql_identifier(fact_table)
        validate_sql_identifier(fk_column)
        validate_sql_identifier(dim_table)
        validate_sql_identifier(pk_column)
        query = f"""
            SELECT COUNT(*) AS orphan_count
            FROM {fact_table} f
            LEFT JOIN {dim_table} d ON f.{fk_column} = d.{pk_column}
            WHERE d.{pk_column} IS NULL AND f.{fk_column} IS NOT NULL
        """
        row = self.conn.execute(query).fetchone()
        assert row is not None
        orphans = row[0]
        passed = orphans == 0
        result = QualityResult(
            table=fact_table,
            check_type="referential_integrity",
            layer=CheckLayer.RELATIONAL,
            passed=passed,
            message=(f"{fact_table}.{fk_column} -> {dim_table}.{pk_column}: {orphans} orphans"),
            details={
                "fk": f"{fact_table}.{fk_column}",
                "pk": f"{dim_table}.{pk_column}",
                "orphans": orphans,
            },
        )
        self.results.append(result)
        if not passed:
            logger.warning(result.message)
        return result

    def check_cardinality(
        self,
        table: str,
        column: str,
        min_distinct: int = 1,
        max_distinct: int | None = None,
    ) -> QualityResult:
        validate_sql_identifier(table)
        validate_sql_identifier(column)
        query = f"SELECT COUNT(DISTINCT {column}) FROM {table}"
        row = self.conn.execute(query).fetchone()
        assert row is not None
        distinct = row[0]
        passed = distinct >= min_distinct
        if max_distinct is not None:
            passed = passed and distinct <= max_distinct
        bound_str = f">={min_distinct}"
        if max_distinct is not None:
            bound_str += f", <={max_distinct}"
        result = QualityResult(
            table=table,
            check_type="cardinality",
            layer=CheckLayer.RELATIONAL,
            passed=passed,
            message=(f"{table}.{column}: {distinct} distinct (expected {bound_str})"),
            details={
                "column": column,
                "distinct": distinct,
                "min": min_distinct,
                "max": max_distinct,
            },
        )
        self.results.append(result)
        if not passed:
            logger.warning(result.message)
        return result

    # -- Layer 3: Statistical (cross-source) ----------------------------------

    def cross_validate(
        self,
        our_table: str,
        nba_table: str,
        columns: list[str],
        tolerance: float = 0.001,
    ) -> QualityResult:
        validate_sql_identifier(our_table)
        validate_sql_identifier(nba_table)
        for col in columns:
            validate_sql_identifier(col)
        mismatches: list[str] = []
        for col in columns:
            query = f"""
                SELECT
                    ABS(COALESCE(a.val, 0) - COALESCE(b.val, 0)) AS diff
                FROM (SELECT SUM({col}) AS val FROM {our_table}) a,
                     (SELECT SUM({col}) AS val FROM {nba_table}) b
            """
            try:
                diff_row = self.conn.execute(query).fetchone()
                assert diff_row is not None
                diff = diff_row[0]
                if diff and diff > tolerance:
                    mismatches.append(f"{col}: diff={diff:.4f}")
            except (duckdb.Error, AssertionError) as e:
                mismatches.append(f"{col}: error={type(e).__name__}")
        passed = len(mismatches) == 0
        result = QualityResult(
            table=our_table,
            check_type="cross_validation",
            layer=CheckLayer.STATISTICAL,
            passed=passed,
            message=(f"{our_table} vs {nba_table}: {'OK' if passed else ', '.join(mismatches)}"),
            details={"reference": nba_table, "mismatches": mismatches},
        )
        self.results.append(result)
        if not passed:
            logger.warning(result.message)
        return result

    def check_value_range(
        self,
        table: str,
        column: str,
        min_val: float | None = None,
        max_val: float | None = None,
    ) -> QualityResult:
        validate_sql_identifier(table)
        validate_sql_identifier(column)
        query = f"SELECT MIN({column}), MAX({column}) FROM {table}"
        row = self.conn.execute(query).fetchone()
        assert row is not None
        actual_min, actual_max = row
        violations: list[str] = []
        if min_val is not None and actual_min is not None and actual_min < min_val:
            violations.append(f"min={actual_min} < {min_val}")
        if max_val is not None and actual_max is not None and actual_max > max_val:
            violations.append(f"max={actual_max} > {max_val}")
        passed = len(violations) == 0
        result = QualityResult(
            table=table,
            check_type="value_range",
            layer=CheckLayer.STATISTICAL,
            passed=passed,
            message=(
                f"{table}.{column}: "
                f"[{actual_min}, {actual_max}] "
                f"{'OK' if passed else ', '.join(violations)}"
            ),
            details={
                "column": column,
                "actual_min": actual_min,
                "actual_max": actual_max,
                "expected_min": min_val,
                "expected_max": max_val,
            },
        )
        self.results.append(result)
        if not passed:
            logger.warning(result.message)
        return result

    # -- Reporting ------------------------------------------------------------

    def results_by_layer(
        self,
        layer: CheckLayer,
    ) -> list[QualityResult]:
        return [r for r in self.results if r.layer == layer]

    def failed(self) -> list[QualityResult]:
        return [r for r in self.results if not r.passed]

    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.results),
            "passed": sum(1 for r in self.results if r.passed),
            "failed": sum(1 for r in self.results if not r.passed),
        }

    def summary_by_layer(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for layer in CheckLayer:
            layer_results = self.results_by_layer(layer)
            out[layer.value] = {
                "total": len(layer_results),
                "passed": sum(1 for r in layer_results if r.passed),
                "failed": sum(1 for r in layer_results if not r.passed),
            }
        return out

    def to_report(self) -> dict[str, object]:
        return {
            "summary": self.summary(),
            "summary_by_layer": self.summary_by_layer(),
            "results": [
                {
                    "table": r.table,
                    "check_type": r.check_type,
                    "layer": r.layer.value,
                    "passed": r.passed,
                    "message": r.message,
                    "details": r.details,
                }
                for r in self.results
            ],
        }

    def log_summary(self) -> None:
        s = self.summary()
        logger.info(f"Quality: {s['passed']}/{s['total']} passed, {s['failed']} failed")
        for layer in CheckLayer:
            ls = self.results_by_layer(layer)
            failed = sum(1 for r in ls if not r.passed)
            if ls:
                logger.info(f"  {layer.value}: {len(ls) - failed}/{len(ls)} passed")
        for r in self.failed():
            logger.warning(f"  FAIL [{r.layer.value}] {r.message}")

    # -- Quality gate for staging → transform ---------------------------------

    def run_staging_gate(
        self,
        *,
        min_tables: int = 1,
        warn_empty: bool = True,
        fail_on_empty_critical: bool = False,
        critical_tables: set[str] | None = None,
    ) -> bool:
        """Validate staging layer readiness before transform phase.

        Queries DuckDB for all ``stg_*`` tables and runs structural checks:
        - Total staging table count ≥ *min_tables*
        - Warns (or fails) on empty staging tables
        - Checks that critical tables have at least 1 row

        Returns True if the gate passes, False otherwise.
        """
        critical = critical_tables or set()
        try:
            rows = self.conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_name LIKE 'stg_%'"
            ).fetchall()
        except Exception as exc:
            logger.error("staging gate: failed to list tables: {}", type(exc).__name__)
            return False

        stg_tables = sorted(r[0] for r in rows)

        if len(stg_tables) < min_tables:
            self.results.append(
                QualityResult(
                    table="_staging_gate",
                    check_type="staging_gate",
                    layer=CheckLayer.STRUCTURAL,
                    passed=False,
                    message=f"Only {len(stg_tables)} staging tables (need ≥{min_tables})",
                )
            )
            return False

        gate_passed = True
        for table in stg_tables:
            try:
                row = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                count = row[0] if row else 0
            except Exception:
                count = -1

            if count == 0:
                is_critical = table in critical
                level = "FAIL" if (is_critical and fail_on_empty_critical) else "WARN"
                if is_critical and fail_on_empty_critical:
                    gate_passed = False
                if warn_empty or is_critical:
                    self.results.append(
                        QualityResult(
                            table=table,
                            check_type="staging_empty",
                            layer=CheckLayer.STRUCTURAL,
                            passed=level != "FAIL",
                            message=f"{table}: empty staging table ({level})",
                        )
                    )
                    if level == "FAIL":
                        logger.warning("staging gate FAIL: {} is empty", table)
                    else:
                        logger.debug("staging gate warn: {} is empty", table)

        self.results.append(
            QualityResult(
                table="_staging_gate",
                check_type="staging_gate",
                layer=CheckLayer.STRUCTURAL,
                passed=gate_passed,
                message=(
                    f"Staging gate: {len(stg_tables)} tables checked, "
                    f"{'PASS' if gate_passed else 'FAIL'}"
                ),
            )
        )
        return gate_passed
