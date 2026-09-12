"""Small fail-closed SQL clause helpers for static catalog templates."""

from __future__ import annotations

from dataclasses import dataclass


class SQLShapeError(ValueError):
    """A static catalog query cannot be split without changing its meaning."""


@dataclass(frozen=True)
class FilterableSQL:
    """A SELECT split around its top-level WHERE and trailing clauses."""

    source: str
    predicate: str | None
    suffix: str


_TRAILING_CLAUSES = (
    ("group", "by"),
    ("having",),
    ("qualify",),
    ("order", "by"),
    ("limit",),
    ("offset",),
    ("fetch",),
    ("union",),
    ("intersect",),
    ("except",),
)
_SET_OPERATORS = ("union", "intersect", "except")


def _word_tokens(sql: str) -> tuple[tuple[str, int, int, int], ...]:
    """Return unquoted word tokens with source spans and parenthesis depth."""
    tokens: list[tuple[str, int, int, int]] = []
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote is not None:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth -= 1
            if depth < 0:
                raise SQLShapeError("unbalanced closing parenthesis")
            index += 1
            continue
        if char.isalnum() or char in {"_", "$"}:
            start = index
            index += 1
            while index < len(sql) and (sql[index].isalnum() or sql[index] in {"_", "$"}):
                index += 1
            tokens.append((sql[start:index].casefold(), start, index, depth))
            continue
        index += 1
    if quote is not None:
        raise SQLShapeError("unterminated quoted token")
    if depth:
        raise SQLShapeError("unbalanced opening parenthesis")
    return tuple(tokens)


def _clause_start(
    sql: str,
    clauses: tuple[tuple[str, ...], ...],
    *,
    after: int = 0,
) -> int | None:
    tokens = _word_tokens(sql)
    matches: list[int] = []
    for index, (word, start, _end, depth) in enumerate(tokens):
        if depth != 0 or start < after:
            continue
        for clause in clauses:
            if word != clause[0] or index + len(clause) > len(tokens):
                continue
            candidate = tokens[index : index + len(clause)]
            if any(token_depth != 0 for _, _, _, token_depth in candidate):
                continue
            if tuple(token_word for token_word, *_ in candidate) != clause:
                continue
            if any(
                sql[left_end:right_start].strip()
                for (_, _, left_end, _), (_, right_start, _, _) in zip(
                    candidate,
                    candidate[1:],
                    strict=False,
                )
            ):
                continue
            matches.append(start)
    return min(matches) if matches else None


def split_filterable_sql(sql: str) -> FilterableSQL:
    """Split only depth-zero clauses, rejecting malformed static SQL."""
    if not sql.strip():
        raise SQLShapeError("SQL is empty")
    trailing_start = _clause_start(sql, _TRAILING_CLAUSES)
    head = sql if trailing_start is None else sql[:trailing_start]
    suffix = "" if trailing_start is None else sql[trailing_start:].strip()
    where_start = _clause_start(head, (("where",),))
    if where_start is None:
        return FilterableSQL(source=head.strip(), predicate=None, suffix=suffix)

    where_token_end = where_start + len("where")
    source = head[:where_start].strip()
    predicate = head[where_token_end:].strip()
    if not source or not predicate:
        raise SQLShapeError("top-level WHERE is incomplete")
    return FilterableSQL(source=source, predicate=predicate, suffix=suffix)


def top_level_clause_present(sql: str, *clauses: str) -> bool:
    """Return whether any named clause begins outside quotes and parentheses."""
    clause_tokens = tuple(tuple(clause.casefold().split()) for clause in clauses)
    return _clause_start(sql, clause_tokens) is not None


def has_top_level_set_operator(sql: str) -> bool:
    """Return whether SQL has a depth-zero set operation."""
    return top_level_clause_present(sql, *_SET_OPERATORS)


def normalize_static_sql(fragment: str) -> str:
    """Token-normalize SQL while preserving quoted token bytes exactly."""
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0

    def flush_word() -> None:
        if current:
            tokens.append("".join(current).casefold())
            current.clear()

    while index < len(fragment):
        char = fragment[index]
        if quote is not None:
            current.append(char)
            if char == quote:
                if index + 1 < len(fragment) and fragment[index + 1] == quote:
                    current.append(fragment[index + 1])
                    index += 2
                    continue
                tokens.append("".join(current))
                current.clear()
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            flush_word()
            quote = char
            current.append(char)
            index += 1
            continue
        if char.isalnum() or char in {"_", "$"}:
            current.append(char)
            index += 1
            continue
        flush_word()
        if char.isspace():
            index += 1
            continue
        if index + 1 < len(fragment) and fragment[index : index + 2] in {
            "!=",
            "<=",
            "<>",
            ">=",
            "::",
            "||",
        }:
            tokens.append(fragment[index : index + 2])
            index += 2
            continue
        tokens.append(char.casefold())
        index += 1
    if quote is not None:
        raise SQLShapeError("unterminated quoted token")
    flush_word()
    return " ".join(tokens)


def normalized_visibility_rowset(sql: str) -> tuple[str, str | None]:
    """Return normalized outer FROM/JOIN source and fixed WHERE predicate."""
    shape = split_filterable_sql(sql)
    from_start = _clause_start(shape.source, (("from",),))
    if from_start is None:
        raise SQLShapeError("top-level FROM is missing")
    source = normalize_static_sql(shape.source[from_start:])
    predicate = normalize_static_sql(shape.predicate) if shape.predicate is not None else None
    return source, predicate
