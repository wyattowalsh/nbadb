from __future__ import annotations

from nbadb.orchestrate.seasons import (
    current_season,
    recent_seasons,
    season_range,
    season_string,
)


class TestSeasons:
    def test_season_string_standard(self) -> None:
        assert season_string(2024) == "2024-25"

    def test_season_string_century_boundary(self) -> None:
        assert season_string(1999) == "1999-00"

    def test_season_string_first_season(self) -> None:
        assert season_string(1946) == "1946-47"

    def test_season_range_default_starts_1946(self) -> None:
        r = season_range(end=1948)
        assert r == ["1946-47", "1947-48", "1948-49"]

    def test_season_range_custom(self) -> None:
        r = season_range(start=2020, end=2022)
        assert r == ["2020-21", "2021-22", "2022-23"]

    def test_season_range_single(self) -> None:
        r = season_range(start=2024, end=2024)
        assert r == ["2024-25"]

    def test_recent_seasons_count(self) -> None:
        r = recent_seasons(3)
        assert len(r) == 3

    def test_current_season_format(self) -> None:
        s = current_season()
        assert len(s) == 7  # "YYYY-YY"
        assert "-" in s
