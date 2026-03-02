from __future__ import annotations

from datetime import datetime

from loguru import logger


def determine_update_mode() -> str:
    """Determine pipeline mode: daily, monthly, or full."""
    now = datetime.now()
    if 1 <= now.day <= 7:
        return "monthly"
    return "daily"


def print_summary(
    mode: str,
    tables_updated: int,
    rows_total: int,
    duration_seconds: float,
) -> None:
    """Print pipeline run summary."""
    logger.info(
        f"Pipeline complete: mode={mode}, "
        f"tables={tables_updated}, "
        f"rows={rows_total:,}, "
        f"duration={duration_seconds:.1f}s"
    )


def validate_row_counts(
    expected: dict[str, int],
    actual: dict[str, int],
    tolerance: float = 0.05,
) -> list[str]:
    """Compare expected vs actual row counts. Return list of warnings."""
    warnings: list[str] = []
    for table, exp in expected.items():
        act = actual.get(table, 0)
        if exp > 0:
            diff_pct = abs(act - exp) / exp
            if diff_pct > tolerance:
                warnings.append(f"{table}: expected ~{exp:,}, got {act:,} ({diff_pct:.1%} diff)")
    return warnings
