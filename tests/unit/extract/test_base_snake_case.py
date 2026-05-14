from __future__ import annotations

from nbadb.extract.base import _canonicalize_endpoint_column_name, _to_snake_case


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

    def test_upper_stat_shorthand_with_number(self) -> None:
        assert _to_snake_case("FG3M") == "fg3m"

    def test_upper_rank_shorthand_with_number(self) -> None:
        assert _to_snake_case("FG3M_RANK") == "fg3m_rank"

    def test_upper_multi_token_stat_shorthand(self) -> None:
        assert _to_snake_case("PCT_AST_2PM") == "pct_ast_2pm"

    def test_already_snake_case(self) -> None:
        assert _to_snake_case("game_id") == "game_id"

    def test_empty_string(self) -> None:
        assert _to_snake_case("") == ""


class TestCanonicalizeEndpointColumnName:
    def test_box_score_traditional_player_aliases_verbose_stats(self) -> None:
        assert (
            _canonicalize_endpoint_column_name(
                "BoxScoreTraditionalV3",
                0,
                "fieldGoalsMade",
            )
            == "fgm"
        )
        assert (
            _canonicalize_endpoint_column_name(
                "BoxScoreTraditionalV3",
                0,
                "plusMinusPoints",
            )
            == "plus_minus"
        )
        assert (
            _canonicalize_endpoint_column_name("BoxScoreTraditionalV3", 0, "personId")
            == "player_id"
        )

    def test_box_score_traditional_keeps_descriptive_fields(self) -> None:
        assert (
            _canonicalize_endpoint_column_name("BoxScoreTraditionalV3", 0, "playerSlug")
            == "player_slug"
        )
        assert (
            _canonicalize_endpoint_column_name("BoxScoreTraditionalV3", 2, "teamSlug")
            == "team_slug"
        )

    def test_box_score_advanced_aliases_verbose_metrics(self) -> None:
        assert (
            _canonicalize_endpoint_column_name(
                "BoxScoreAdvancedV3",
                0,
                "estimatedOffensiveRating",
            )
            == "e_off_rating"
        )
        assert _canonicalize_endpoint_column_name("BoxScoreAdvancedV3", 1, "possessions") == "poss"
        assert (
            _canonicalize_endpoint_column_name(
                "BoxScoreAdvancedV3",
                1,
                "estimatedTeamTurnoverPercentage",
            )
            == "tm_tov_pct"
        )

    def test_box_score_misc_scoring_usage_alias_verbose_metrics(self) -> None:
        assert (
            _canonicalize_endpoint_column_name("BoxScoreMiscV3", 0, "pointsOffTurnovers")
            == "pts_off_tov"
        )
        assert (
            _canonicalize_endpoint_column_name(
                "BoxScoreScoringV3",
                1,
                "percentagePointsMidrange2pt",
            )
            == "pct_pts_2pt_mr"
        )
        assert (
            _canonicalize_endpoint_column_name(
                "BoxScoreUsageV3",
                0,
                "percentageThreePointersAttempted",
            )
            == "pct_fg3a"
        )

    def test_box_score_tracking_defense_hustle_alias_verbose_metrics(self) -> None:
        assert (
            _canonicalize_endpoint_column_name(
                "BoxScorePlayerTrackV3",
                0,
                "reboundChancesOffensive",
            )
            == "orbc"
        )
        assert (
            _canonicalize_endpoint_column_name(
                "BoxScoreDefensiveV2",
                0,
                "matchupFieldGoalsAttempted",
            )
            == "def_fga"
        )
        assert (
            _canonicalize_endpoint_column_name("BoxScoreHustleV2", 1, "contestedShots2pt")
            == "contested_shots_2pt"
        )

    def test_box_score_summary_aliases_known_contract_typos(self) -> None:
        assert (
            _canonicalize_endpoint_column_name("BoxScoreSummaryV2", 6, "jerseyNum")
            == "jersey_number"
        )
        assert (
            _canonicalize_endpoint_column_name("BoxScoreSummaryV3", 8, "ptXYZAvailable")
            == "pt_xyz_available"
        )

    def test_unconfigured_non_box_score_columns_only_snake_case(self) -> None:
        assert (
            _canonicalize_endpoint_column_name("UnconfiguredEndpoint", 0, "personId") == "person_id"
        )

    def test_common_static_aliases_known_contract_names(self) -> None:
        assert (
            _canonicalize_endpoint_column_name("CommonAllPlayers", 0, "ROSTERSTATUS")
            == "roster_status"
        )
        assert (
            _canonicalize_endpoint_column_name("CommonPlayerInfo", 1, "ROSTERSTATUS")
            == "roster_status"
        )
        assert (
            _canonicalize_endpoint_column_name("CommonPlayoffSeries", 0, "GAME_NUM")
            == "game_number"
        )
        assert (
            _canonicalize_endpoint_column_name("CommonPlayoffSeries", 0, "VISITOR_TEAM_ID")
            == "away_team_id"
        )

    def test_synergy_play_types_aliases_possession_percentage_names(self) -> None:
        assert (
            _canonicalize_endpoint_column_name("SynergyPlayTypes", 0, "FT_POSS_PCT")
            == "ft_pct_adjust"
        )
        assert _canonicalize_endpoint_column_name("SynergyPlayTypes", 0, "TOV_POSS_PCT") == "to_pct"
        assert (
            _canonicalize_endpoint_column_name("SynergyPlayTypes", 0, "PLUSONE_POSS_PCT")
            == "plusone_pct"
        )
        assert (
            _canonicalize_endpoint_column_name("SynergyPlayTypes", 0, "SCORE_POSS_PCT")
            == "score_pct"
        )
        assert _canonicalize_endpoint_column_name("SynergyPlayTypes", 0, "SF_POSS_PCT") == "sf_pct"

    def test_scoreboard_v2_aliases_standings_names(self) -> None:
        assert (
            _canonicalize_endpoint_column_name("ScoreboardV2", 1, "STANDINGSDATE")
            == "standings_date"
        )
        assert (
            _canonicalize_endpoint_column_name("ScoreboardV2", 1, "RETURNTOPLAY")
            == "return_to_play"
        )
        assert (
            _canonicalize_endpoint_column_name("ScoreboardV2", 8, "STANDINGSDATE")
            == "standings_date"
        )

    def test_play_by_play_aliases_available_video_names(self) -> None:
        assert (
            _canonicalize_endpoint_column_name("PlayByPlayV3", 0, "VIDEO_AVAILABLE_FLAG")
            == "video_available"
        )
