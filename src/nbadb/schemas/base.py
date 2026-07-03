from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

import pandera.polars as pa
from loguru import logger

_CAMEL_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE_2 = re.compile(r"([a-z0-9])([A-Z])")

_DEFAULT_FK_REFS = {
    "arena_id": "dim_arena.arena_id",
    "ast_person_id": "dim_player.player_id",
    "away_team_id": "dim_team.team_id",
    "blk_person_id": "dim_player.player_id",
    "close_def_person_id": "dim_player.player_id",
    "game_id": "dim_game.game_id",
    "home_team_id": "dim_team.team_id",
    "opponent_team_id": "dim_team.team_id",
    "pass_teammate_player_id": "dim_player.player_id",
    "person_id": "dim_player.player_id",
    "player_id": "dim_player.player_id",
    "pts_person_id": "dim_player.player_id",
    "reb_person_id": "dim_player.player_id",
    "stl_person_id": "dim_player.player_id",
    "team_id": "dim_team.team_id",
    "vs_player_id": "dim_player.player_id",
}

_STAR_FK_REF_ALIASES = {
    "staging_arena.arena_id": "dim_arena.arena_id",
    "staging_game_log.game_id": "dim_game.game_id",
    "staging_game.game_id": "dim_game.game_id",
    "staging_official.official_id": "dim_official.official_id",
    "staging_player.person_id": "dim_player.player_id",
    "staging_player.player_id": "dim_player.player_id",
    "staging_team.team_id": "dim_team.team_id",
}

_SCHEMA_METADATA_POLICY_ATTR = "__schema_metadata_policy__"


class _SchemaMetadataPolicy(TypedDict):
    default_source_prefix: str | None
    source_overrides: dict[str, str]
    fk_refs: dict[str, str]
    literal_fields: set[str]
    audit_fields: set[str]
    auto_fk: bool


def _camel_to_snake(name: str) -> str:
    interim = _CAMEL_RE_1.sub(r"\1_\2", name)
    return _CAMEL_RE_2.sub(r"\1_\2", interim).lower()


def _schema_table_name(schema_cls: type[BaseSchema]) -> str:
    return _camel_to_snake(schema_cls.__name__.removesuffix("Schema"))


def _schema_metadata_policy(
    *,
    default_source_prefix: str | None = None,
    source_overrides: dict[str, str] | None = None,
    fk_refs: dict[str, str] | None = None,
    literal_fields: Iterable[str] | None = None,
    audit_fields: Iterable[str] | None = None,
    auto_fk: bool = False,
) -> Callable[[type[BaseSchema]], type[BaseSchema]]:
    """Attach a metadata policy that is applied when ``to_schema`` is built."""

    policy: _SchemaMetadataPolicy = {
        "default_source_prefix": default_source_prefix,
        "source_overrides": dict(source_overrides or {}),
        "fk_refs": dict(fk_refs or {}),
        "literal_fields": set(literal_fields or ()),
        "audit_fields": set(audit_fields or ()),
        "auto_fk": auto_fk,
    }

    def decorator(schema_cls: type[BaseSchema]) -> type[BaseSchema]:
        existing = cast(
            "_SchemaMetadataPolicy | None",
            getattr(schema_cls, _SCHEMA_METADATA_POLICY_ATTR, None),
        )
        if existing is not None:
            policy["source_overrides"] = {
                **existing.get("source_overrides", {}),
                **policy["source_overrides"],
            }
            policy["fk_refs"] = {**existing.get("fk_refs", {}), **policy["fk_refs"]}
            policy["literal_fields"] |= set(existing.get("literal_fields", ()))
            policy["audit_fields"] |= set(existing.get("audit_fields", ()))
            policy["auto_fk"] = bool(existing.get("auto_fk")) or policy["auto_fk"]
            policy["default_source_prefix"] = policy["default_source_prefix"] or existing.get(
                "default_source_prefix"
            )
        setattr(schema_cls, _SCHEMA_METADATA_POLICY_ATTR, policy)
        return schema_cls

    return decorator


def derived_output_schema(
    *,
    table_name: str | None = None,
    source_overrides: dict[str, str] | None = None,
    fk_refs: dict[str, str] | None = None,
    literal_fields: Iterable[str] | None = None,
    audit_fields: Iterable[str] | None = None,
    auto_fk: bool = True,
) -> Callable[[type[BaseSchema]], type[BaseSchema]]:
    def decorator(schema_cls: type[BaseSchema]) -> type[BaseSchema]:
        resolved_table = table_name or _schema_table_name(schema_cls)
        return _schema_metadata_policy(
            default_source_prefix=f"derived.{resolved_table}",
            source_overrides=source_overrides,
            fk_refs=fk_refs,
            literal_fields=literal_fields,
            audit_fields=audit_fields,
            auto_fk=auto_fk,
        )(schema_cls)

    return decorator


class BaseSchema(pa.DataFrameModel):
    """Two-tier validation schema.

    - Hard-fail on missing required columns and wrong data types.
    - Soft-warn and strip unexpected extra columns.

    Uses ``strict=False`` so pandera does not reject extra columns outright,
    then explicitly drops them after logging a warning.
    """

    class Config:
        coerce = True
        strict = False

    @classmethod
    def _normalize_star_fk_refs(cls, schema: Any) -> Any:
        if not cls.__module__.startswith("nbadb.schemas.star."):
            return schema

        for column in schema.columns.values():
            metadata = dict(column.metadata or {})
            fk_ref = metadata.get("fk_ref")
            if isinstance(fk_ref, str) and fk_ref in _STAR_FK_REF_ALIASES:
                metadata["fk_ref"] = _STAR_FK_REF_ALIASES[fk_ref]
                column.metadata = metadata
        return schema

    @classmethod
    def _apply_schema_metadata_policy(cls, schema: Any) -> Any:
        schema = cls._normalize_star_fk_refs(schema)
        policy = getattr(cls, _SCHEMA_METADATA_POLICY_ATTR, None)
        if policy is None:
            return schema

        default_source_prefix = policy.get("default_source_prefix")
        source_overrides = dict(policy.get("source_overrides", {}))
        fk_refs = dict(policy.get("fk_refs", {}))
        literal_fields = set(policy.get("literal_fields", ()))
        audit_fields = set(policy.get("audit_fields", ()))
        auto_fk = bool(policy.get("auto_fk"))

        for column_name, column in schema.columns.items():
            metadata = dict(column.metadata or {})
            if column_name in audit_fields and "source" not in metadata:
                metadata["source"] = f"audit.{column_name}"
            if column_name in literal_fields and "source" not in metadata:
                metadata["source"] = f"literal.{column_name}"
            if column_name in source_overrides and "source" not in metadata:
                metadata["source"] = source_overrides[column_name]

            fk_ref = fk_refs.get(column_name)
            if fk_ref is None and auto_fk:
                fk_ref = _DEFAULT_FK_REFS.get(column_name)
            existing_fk_ref = metadata.get("fk_ref")
            if (
                isinstance(existing_fk_ref, str)
                and cls.__module__.startswith("nbadb.schemas.star.")
                and existing_fk_ref in _STAR_FK_REF_ALIASES
            ):
                metadata["fk_ref"] = _STAR_FK_REF_ALIASES[existing_fk_ref]
            elif fk_ref is not None and "fk_ref" not in metadata:
                metadata["fk_ref"] = fk_ref

            if (
                default_source_prefix is not None
                and "source" not in metadata
                and "fk_ref" not in metadata
                and not column_name.endswith("_sk")
            ):
                metadata["source"] = f"{default_source_prefix}.{column_name}"

            column.metadata = metadata or None

        return schema

    @classmethod
    def to_schema(cls) -> Any:
        return cls._apply_schema_metadata_policy(super().to_schema())

    @classmethod
    def validate(  # type: ignore[override]
        cls,
        data: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        import polars as pl

        # Determine the required columns declared in this schema
        schema_obj = cls.to_schema()
        expected_columns: set[str] = set(schema_obj.columns)

        # Detect extra columns present in the data but not in the schema
        if isinstance(data, (pl.DataFrame, pl.LazyFrame)):
            if isinstance(data, pl.LazyFrame):
                actual_columns = set(data.collect_schema().names())
            else:
                actual_columns = set(data.columns)

            extra = sorted(actual_columns - expected_columns)
            if extra:
                logger.warning(
                    f"{cls.__name__}: stripping {len(extra)} unexpected column(s): {extra}"
                )
                data = data.drop(extra)

        # Pandera validates required columns + types (hard-fail)
        return super().validate(data, *args, **kwargs)


__all__ = ["BaseSchema", "derived_output_schema"]
