from __future__ import annotations

import pytest

from nbadb.agent.season_bind import (
    default_season_bind,
    extract_season_bind,
    parse_season_bind,
    previous_season_year,
    resolve_season_bind,
    validate_season_type,
    validate_season_year,
)
from nbadb.orchestrate.seasons import current_season


def test_validate_season_year() -> None:
    assert validate_season_year("2024-25") == "2024-25"
    assert validate_season_year("1999-00") == "1999-00"
    assert validate_season_year("2024-99") is None
    assert validate_season_year("2024-24") is None
    assert validate_season_year("not-a-year") is None
    assert validate_season_year("２０２４-２５") is None
    assert validate_season_year("20２４-２５") is None
    assert validate_season_year("'; DROP TABLE x; --") is None


def test_validate_season_type() -> None:
    assert validate_season_type("Regular Season") == "Regular Season"
    assert validate_season_type("Playoffs") == "Playoffs"
    assert validate_season_type("HACK") is None


def test_extract_last_season() -> None:
    bind = extract_season_bind("who led scoring last season?")
    assert bind.season_year == previous_season_year(current_season())
    assert bind.season_type is None
    assert bind.source == "extracted"


def test_extract_playoffs() -> None:
    bind = extract_season_bind("playoff scoring leaders")
    assert bind.season_type == "Playoffs"
    assert bind.source == "missing"


def test_parse_preserves_invalid_year_shaped_token() -> None:
    parsed = parse_season_bind("most points 2024-99")
    assert parsed.invalid_year_token == "2024-99"
    assert parsed.bind.season_year is None


def test_parse_invalid_year_wins_even_with_relative_phrase() -> None:
    parsed = parse_season_bind("most points 2024-99 last season")
    assert parsed.invalid_year_token == "2024-99"
    assert parsed.bind.season_year is None
    assert parsed.bind.source == "missing"


@pytest.mark.parametrize(
    "token",
    [
        "2024-9",
        "2024-025",
        "2024/25",
        "2024‐25",
        "2024‑25",
        "2024‒25",
        "2024–25",
        "2024—25",
        "2024−25",
        "2024 - 25",
        "2024\u00a0-\u00a025",
        "２０２４-２５",
        "٢٠٢٤-٢٥",
        "2024-99",
    ],
)
def test_parse_rejects_every_noncanonical_season_candidate(token: str) -> None:
    parsed = parse_season_bind(f"most points {token}")

    assert parsed.invalid_year_token == token
    assert parsed.bind.season_year is None
    assert parsed.bind.source == "missing"


@pytest.mark.parametrize(
    "question",
    [
        "most points on 2024-10-22",
        "most points on 2024/10/22",
        "most points on 2024 - 10 - 22",
        "most points on 2024-10-22T19:30:00Z",
        "most points for player2024-25",
        "most points for 2024-25season",
        "most points in 2024",
        "most points 1234-56",
    ],
)
def test_parse_excludes_dates_identifiers_and_standalone_years(question: str) -> None:
    parsed = parse_season_bind(question)

    assert parsed.invalid_year_token is None
    assert parsed.bind.season_year is None


@pytest.mark.parametrize(
    ("question", "invalid_token"),
    [
        ("most points on 2024-99-01", "2024-99"),
        ("most points on 2024/99/01", "2024/99"),
        ("most points on 2024-02-30", "2024-02"),
    ],
)
def test_parse_does_not_let_invalid_dates_mask_malformed_seasons(
    question: str,
    invalid_token: str,
) -> None:
    parsed = parse_season_bind(question)

    assert parsed.invalid_year_token == invalid_token
    assert parsed.bind.season_year is None


def test_parse_preserves_valid_season_prefix_when_following_date_is_invalid() -> None:
    parsed = parse_season_bind("most points on 2024-25-22")

    assert parsed.invalid_year_token is None
    assert parsed.bind.season_year == "2024-25"


@pytest.mark.parametrize(
    "question",
    [
        "most points 2023-24 then 2024/25 last season",
        "most points 2024/25 then 2023-24 this season",
    ],
)
def test_malformed_candidate_wins_over_valid_and_relative_years(question: str) -> None:
    parsed = parse_season_bind(question)

    assert parsed.invalid_year_token == "2024/25"
    assert parsed.bind.season_year is None
    assert parsed.bind.source == "missing"


def test_first_valid_explicit_season_is_preserved() -> None:
    parsed = parse_season_bind("most points 2021-22 then 2023-24")

    assert parsed.invalid_year_token is None
    assert parsed.bind.season_year == "2021-22"


def test_extract_explicit_year() -> None:
    bind = extract_season_bind("most points 2023-24")
    assert bind.season_year == "2023-24"


def test_explicit_year_beats_last_season() -> None:
    bind = extract_season_bind("most points 2023-24 last season")
    assert bind.season_year == "2023-24"
    assert any("explicit year" in w.lower() for w in bind.warnings)


def test_explicit_year_beats_this_season() -> None:
    bind = extract_season_bind("most points this season 2020-21")
    assert bind.season_year == "2020-21"


def test_resolve_defaults_when_required() -> None:
    bind = resolve_season_bind("who led scoring?", requires_year=True, requires_type=True)
    assert bind.season_year == current_season()
    assert bind.season_type == "Regular Season"
    assert bind.source == "default"


def test_resolve_prefers_default_year_when_provided() -> None:
    bind = resolve_season_bind(
        "who led scoring?",
        requires_year=True,
        requires_type=True,
        default_year="2022-23",
    )
    assert bind.season_year == "2022-23"
    assert bind.source == "warehouse_default"


def test_resolve_type_only_uses_warehouse_year_provenance() -> None:
    bind = resolve_season_bind(
        "playoff scoring leaders",
        requires_year=True,
        requires_type=True,
        default_year="2022-23",
    )
    assert bind.season_year == "2022-23"
    assert bind.season_type == "Playoffs"
    assert bind.source == "warehouse_default"


def test_resolve_relative_year_adds_type_only_when_required() -> None:
    typed = resolve_season_bind(
        "who led scoring last season?",
        requires_year=True,
        requires_type=True,
    )
    year_only = resolve_season_bind(
        "show the shot chart last season",
        requires_year=True,
        requires_type=False,
    )
    assert typed.season_type == "Regular Season"
    assert year_only.season_type is None


def test_resolve_rejects_invalid_default_year() -> None:
    bind = resolve_season_bind(
        "who led scoring?",
        requires_year=True,
        requires_type=False,
        default_year="2024-99",
    )
    assert bind.season_year == current_season()
    assert bind.source == "default"


@pytest.mark.parametrize(
    "question",
    [
        "most points 2024-99",
        "most points 2024/25 last season",
        "playoff scoring 2024–25",
    ],
)
def test_resolve_never_defaults_a_malformed_season_candidate(question: str) -> None:
    bind = resolve_season_bind(
        question,
        requires_year=True,
        requires_type=True,
        default_year="2023-24",
    )

    assert bind.season_year is None
    assert bind.source == "missing"


def test_default_season_bind() -> None:
    bind = default_season_bind()
    assert bind.season_type == "Regular Season"
    assert bind.season_year == current_season()
