"""Pure provider-packet projections shared by extraction and replay.

This module deliberately depends only on Polars, core errors, and the raw-schema
registry.  It must remain below the adapter, extractor base classes, endpoint
registries, staging-route authority, and persistence layers so both the live
producer and no-network authority replay can use one projection implementation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import polars as pl

from nbadb.core.errors import ResponseContractError
from nbadb.core.errors import ValidationError as NbaDbValidationError
from nbadb.extract.raw_schema_registry import get_raw_schema

if TYPE_CHECKING:
    from datetime import datetime

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
_UPPER_TOKEN_RE = re.compile(r"^[A-Z0-9_]+$")


def _to_snake_case(name: str) -> str:
    if _UPPER_TOKEN_RE.fullmatch(name):
        return name.lower()
    return _CAMEL_RE.sub(r"\1_\2", name).lower()


def _championship_years_json() -> pl.Expr:
    return pl.concat_str(
        pl.lit("["),
        pl.col("championship_year").list.eval(pl.element().cast(pl.String)).list.join(","),
        pl.lit("]"),
    ).alias("championship_years_json")


def project_static_landing_frame(dataset_id: str, frame: pl.DataFrame) -> pl.DataFrame:
    """Project one exact pinned static packet to its final fixed staging shape."""

    if not isinstance(frame, pl.DataFrame):
        raise ResponseContractError("static landing projection requires a Polars frame")
    if dataset_id == "static_players":
        return frame.select(
            "id",
            "full_name",
            "first_name",
            "last_name",
            "is_active",
        )
    if dataset_id == "static_wnba_players":
        return frame.select(
            "id",
            "last_name",
            "first_name",
            "full_name",
            "is_active",
            pl.lit("WNBA").alias("league"),
        )
    if dataset_id == "static_teams":
        return frame.select(
            "id",
            "full_name",
            "abbreviation",
            "nickname",
            "city",
            "state",
            "year_founded",
            _championship_years_json(),
        )
    if dataset_id == "static_wnba_teams":
        return frame.select(
            "id",
            "abbreviation",
            "nickname",
            "year_founded",
            "city",
            "full_name",
            "state",
            _championship_years_json(),
            pl.lit("WNBA").alias("league"),
        )
    raise ResponseContractError("static landing projection lacks a pinned dataset contract")


def live_payload_to_frame(
    payload: Any,
    *,
    field_projections: Mapping[str, str] | None = None,
) -> pl.DataFrame:
    """Convert one selected live packet to the exact production Polars frame."""

    if hasattr(payload, "get_dict"):
        payload = payload.get_dict()
    elif hasattr(payload, "data"):
        payload = payload.data

    if payload is None:
        return pl.DataFrame()
    if isinstance(payload, dict):
        records: list[dict[str, Any]] = [payload]
    elif isinstance(payload, list):
        if not payload:
            return pl.DataFrame()
        if isinstance(payload[0], dict):
            records = payload
        else:
            return pl.DataFrame({"value": payload})
    else:
        return pl.DataFrame({"value": [payload]})

    serialized_records = [json.dumps(record, sort_keys=True, default=str) for record in records]
    projected_records: list[dict[str, Any]] = []
    for record in records:
        projected = dict(record)
        for source_path, target_column in (field_projections or {}).items():
            value: Any = record
            for path_part in source_path.split("."):
                if not isinstance(value, Mapping) or path_part not in value:
                    break
                value = value[path_part]
            else:
                projected[target_column] = value
        projected_records.append(projected)

    frame = pl.from_dicts(projected_records, infer_schema_length=None)
    frame = frame.rename({column: _to_snake_case(column) for column in frame.columns})
    return frame.with_columns(pl.Series("payload_json", serialized_records))


def apply_live_snapshot_contract(
    frame: pl.DataFrame,
    *,
    source_endpoint: str,
    natural_keys: tuple[str, ...],
    snapshot_at: datetime,
    params: Mapping[str, Any],
) -> pl.DataFrame:
    """Bind one live frame to its natural keys and exact extraction snapshot."""

    if frame.is_empty():
        empty_columns: list[pl.Series] = []
        for key in natural_keys:
            if key in frame.columns:
                continue
            if key in params:
                empty_columns.append(pl.Series(key, [params[key]]).head(0))
            else:
                empty_columns.append(pl.Series(key, [], dtype=pl.Null))
        empty_columns.extend(
            [
                pl.Series("snapshot_at", [snapshot_at]).head(0),
                pl.Series("snapshot_date", [snapshot_at.date()]).head(0),
                pl.Series("source_endpoint", [source_endpoint]).head(0),
            ]
        )
        if "payload_json" not in frame.columns:
            empty_columns.append(pl.Series("payload_json", [], dtype=pl.String))
        return frame.with_columns(empty_columns)

    missing: list[str] = []
    expressions: list[pl.Expr] = []
    for key in natural_keys:
        if key in frame.columns:
            continue
        if key in params:
            expressions.append(pl.lit(params[key]).alias(key))
            continue
        missing.append(key)
    if missing:
        missing_keys = ", ".join(missing)
        raise NbaDbValidationError(
            f"{source_endpoint}: live payload missing required natural keys: {missing_keys}"
        )

    expressions.extend(
        [
            pl.lit(snapshot_at).alias("snapshot_at"),
            pl.lit(snapshot_at.date()).alias("snapshot_date"),
            pl.lit(source_endpoint).alias("source_endpoint"),
        ]
    )
    if "payload_json" not in frame.columns:
        expressions.append(pl.lit(None).alias("payload_json"))
    return frame.with_columns(expressions)


def normalize_live_landing_frame(frame: pl.DataFrame, *, source_endpoint: str) -> pl.DataFrame:
    """Apply the exact registered raw schema used by the live producer."""

    schema_cls = get_raw_schema(source_endpoint)
    return frame if schema_cls is None else schema_cls.validate(frame)


__all__ = [
    "apply_live_snapshot_contract",
    "live_payload_to_frame",
    "normalize_live_landing_frame",
    "project_static_landing_frame",
]
