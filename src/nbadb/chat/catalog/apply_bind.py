"""Apply validated SeasonBind values to catalog SQL templates."""

from __future__ import annotations

from nbadb.agent.season_bind import SeasonBind, validate_season_type, validate_season_year
from nbadb.chat.catalog.route_meta import RouteSeasonMeta, season_meta_for
from nbadb.chat.catalog.sql_shape import (
    SQLShapeError,
    has_top_level_set_operator,
    split_filterable_sql,
)


def apply_season_bind(
    sql: str,
    bind: SeasonBind,
    *,
    route: str | None = None,
    meta: RouteSeasonMeta | None = None,
) -> str:
    """Inject season filters before ORDER BY / GROUP BY using validated literals only."""
    route_meta = meta if meta is not None else season_meta_for(route or "")
    year = validate_season_year(bind.season_year)
    season_type = validate_season_type(bind.season_type)

    clauses: list[str] = []
    if route_meta.year_column and year:
        clauses.append(f"{route_meta.year_column} = '{year}'")
    if route_meta.type_column and season_type:
        clauses.append(f"{route_meta.type_column} = '{season_type}'")
    if not clauses:
        return sql
    if has_top_level_set_operator(sql):
        raise SQLShapeError("catalog SQL set operations cannot receive route season filters")

    filter_sql = " AND ".join(clauses)
    shape = split_filterable_sql(sql)
    predicate = filter_sql if shape.predicate is None else f"({shape.predicate}) AND {filter_sql}"
    tail = f" {shape.suffix}" if shape.suffix else ""
    return f"{shape.source} WHERE {predicate}{tail}"
