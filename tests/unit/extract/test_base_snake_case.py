from __future__ import annotations

from nbadb.extract.base import _to_snake_case


class TestToSnakeCase:
    def test_camel_case(self) -> None:
        assert _to_snake_case("gameId") == "game_id"

    def test_upper_snake_case(self) -> None:
        assert _to_snake_case("GAME_ID") == "game_id"

    def test_long_camel_case(self) -> None:
        assert _to_snake_case("effectiveFieldGoalPercentage") == "effective_field_goal_percentage"

    def test_mixed_camel(self) -> None:
        assert _to_snake_case("teamTricode") == "team_tricode"

    def test_single_word_lower(self) -> None:
        assert _to_snake_case("pts") == "pts"

    def test_single_word_upper(self) -> None:
        assert _to_snake_case("PTS") == "pts"

    def test_number_in_name(self) -> None:
        assert _to_snake_case("fg3Pct") == "fg3_pct"

    def test_already_snake_case(self) -> None:
        assert _to_snake_case("game_id") == "game_id"

    def test_empty_string(self) -> None:
        assert _to_snake_case("") == ""
