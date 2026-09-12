"""Season binding for catalog-driven chat/ask queries.

Values are validated against an allowlist / regex before they may enter SQL.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Literal

from nbadb.orchestrate.seasons import current_season, season_string

SeasonSource = Literal["extracted", "default", "warehouse_default", "missing"]

SEASON_TYPES: frozenset[str] = frozenset(
    {
        "Regular Season",
        "Playoffs",
        "PlayIn",
        "All Star",
        "Pre Season",
    }
)

_YEAR_RE = re.compile(r"^(19|20)([0-9]{2})-([0-9]{2})$")
_HORIZONTAL_WHITESPACE = r"[\t \u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]*"
_YEAR_SEPARATOR = r"[-/\u2010\u2011\u2012\u2013\u2014\u2212]"
_YEAR_CANDIDATE_RE = re.compile(
    rf"(?<![^\W_])"
    rf"(?P<start>\d{{4}}){_HORIZONTAL_WHITESPACE}"
    rf"(?P<separator>{_YEAR_SEPARATOR}){_HORIZONTAL_WHITESPACE}"
    rf"(?P<end>\d{{1,4}})"
    rf"(?![^\W_])"
)
_FULL_DATE_RE = re.compile(
    rf"(?<![^\W_])"
    rf"(?P<year>\d{{4}}){_HORIZONTAL_WHITESPACE}"
    rf"(?P<separator>[-/]){_HORIZONTAL_WHITESPACE}"
    rf"(?P<month>\d{{1,2}}){_HORIZONTAL_WHITESPACE}"
    rf"(?P=separator){_HORIZONTAL_WHITESPACE}(?P<day>\d{{1,2}})"
    rf"(?!\d)"
)
_DEFAULT_TYPE = "Regular Season"


@dataclass(frozen=True)
class SeasonBind:
    season_year: str | None
    season_type: str | None
    source: SeasonSource
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedSeasonBind:
    """Structured season parse with invalid year-shaped input preserved."""

    bind: SeasonBind
    invalid_year_token: str | None = None


def validate_season_year(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    match = _YEAR_RE.match(candidate)
    if not match:
        return None
    start = int(f"{match.group(1)}{match.group(2)}")
    end = int(match.group(3))
    # NBA seasons are consecutive calendar years (1999-00, 2024-25).
    if end != (start + 1) % 100:
        return None
    return candidate


def validate_season_type(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if candidate not in SEASON_TYPES:
        return None
    return candidate


def previous_season_year(season_year: str) -> str:
    start = int(season_year.split("-", 1)[0])
    return season_string(start - 1)


def _decimal_text(value: str) -> str:
    """Return ASCII decimal digits for recognition only, never acceptance."""
    return "".join(str(unicodedata.decimal(char)) for char in value)


def _date_spans(question: str) -> tuple[tuple[int, int], ...]:
    """Return valid date spans that must not be interpreted as NBA seasons."""
    spans: list[tuple[int, int]] = []
    for match in _FULL_DATE_RE.finditer(question):
        try:
            date(
                int(_decimal_text(match.group("year"))),
                int(_decimal_text(match.group("month"))),
                int(_decimal_text(match.group("day"))),
            )
        except ValueError:
            continue
        spans.append(match.span())
    return tuple(spans)


def _is_within_date(span: tuple[int, int], date_spans: tuple[tuple[int, int], ...]) -> bool:
    start, end = span
    return any(date_start <= start and end <= date_end for date_start, date_end in date_spans)


def parse_season_bind(question: str) -> ParsedSeasonBind:
    """Parse season hints without silently discarding malformed year tokens."""
    text = question.casefold()
    warnings: list[str] = []
    year: str | None = None
    invalid_year_token: str | None = None
    season_type: str | None = None
    source: SeasonSource = "missing"

    date_spans = _date_spans(question)
    for year_match in _YEAR_CANDIDATE_RE.finditer(question):
        if _is_within_date(year_match.span(), date_spans):
            continue
        if not _decimal_text(year_match.group("start")).startswith(("19", "20")):
            continue

        candidate = year_match.group(0)
        canonical = f"{year_match.group('start')}-{year_match.group('end')}"
        valid = validate_season_year(candidate) if candidate == canonical else None
        if valid is None:
            invalid_year_token = invalid_year_token or candidate
        elif year is None:
            year = valid
            source = "extracted"

    # A malformed candidate dominates valid years and relative phrases. This
    # keeps direct parser consumers fail-closed in addition to the planner's
    # explicit ``invalid_year_token`` gate.
    if invalid_year_token is not None:
        year = None
        source = "missing"

    if re.search(r"\bplay[- ]?offs?\b", text):
        season_type = "Playoffs"
    elif re.search(r"\bplay[- ]?in\b", text):
        season_type = "PlayIn"
    elif re.search(r"\ball[- ]?star\b", text):
        season_type = "All Star"
    elif re.search(r"\bpre[- ]?season\b", text):
        season_type = "Pre Season"
    elif re.search(r"\bregular\s+season\b", text):
        season_type = "Regular Season"

    # Explicit valid YYYY-YY beats relative phrases for year assignment.
    if invalid_year_token is None and year is None and re.search(r"\blast\s+season\b", text):
        year = previous_season_year(current_season())
        source = "extracted"
    elif (
        invalid_year_token is None
        and year is None
        and re.search(r"\bthis\s+season\b|\bthis\s+year\b", text)
    ):
        year = current_season()
        source = "extracted"
    elif (
        invalid_year_token is None
        and year is not None
        and re.search(r"\b(?:last|this)\s+season\b|\bthis\s+year\b", text)
    ):
        warnings.append("Ignored relative season phrase because an explicit year was present.")

    if year is None and season_type is None:
        return ParsedSeasonBind(
            SeasonBind(None, None, "missing", tuple(warnings)),
            invalid_year_token,
        )

    return ParsedSeasonBind(
        SeasonBind(
            season_year=year,
            season_type=season_type,
            source=source,
            warnings=tuple(warnings),
        ),
        invalid_year_token,
    )


def extract_season_bind(question: str) -> SeasonBind:
    """Extract season year/type hints from natural language."""
    return parse_season_bind(question).bind


def default_season_bind() -> SeasonBind:
    """Default bind: Regular Season + calendar current season."""
    return SeasonBind(
        season_year=current_season(),
        season_type=_DEFAULT_TYPE,
        source="default",
    )


def resolve_season_bind(
    question: str,
    *,
    requires_year: bool,
    requires_type: bool,
    default_year: str | None = None,
) -> SeasonBind:
    """Extract from question; fill defaults when route requires season dimensions.

    ``default_year`` is an optional preferred year (e.g. warehouse max). When
    provided and valid it is used instead of the calendar current season for
    missing year fills, and ``source`` becomes ``warehouse_default`` when that
    fill is applied from a missing extraction.
    """
    parsed = parse_season_bind(question)
    extracted = parsed.bind
    if parsed.invalid_year_token is not None:
        return extracted
    if not requires_year and not requires_type:
        return extracted

    calendar = default_season_bind()
    preferred = validate_season_year(default_year)
    year = extracted.season_year
    season_type = extracted.season_type
    source: SeasonSource = extracted.source
    warnings = list(extracted.warnings)

    if requires_year and year is None:
        if preferred is not None:
            year = preferred
            source = "warehouse_default" if extracted.source == "missing" else extracted.source
        else:
            year = calendar.season_year
            source = "default" if extracted.source == "missing" else extracted.source
    if requires_type and season_type is None:
        season_type = calendar.season_type
        if source == "missing":
            source = "default"

    year = validate_season_year(year)
    season_type = validate_season_type(season_type)

    if requires_year and year is None:
        warnings.append("Could not resolve a valid season_year.")
        return SeasonBind(None, season_type, "missing", tuple(warnings))

    return SeasonBind(year, season_type, source, tuple(warnings))
