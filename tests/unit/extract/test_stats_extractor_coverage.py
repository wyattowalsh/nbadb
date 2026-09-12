"""Coverage and schedule extractor tests split from the typed registry module."""

from __future__ import annotations

import json

import polars as pl
import pytest

from nbadb.extract.stats.box_summary import BoxScoreSummaryExtractor, BoxScoreSummaryV3Extractor
from nbadb.extract.stats.draft import (
    DraftBoardExtractor,
    DraftCombineDrillResultsExtractor,
    DraftCombineNonStationaryShootingExtractor,
    DraftCombinePlayerAnthroExtractor,
    DraftCombineSpotShootingExtractor,
)
from nbadb.extract.stats.hustle import (
    HustleStatsBoxScoreExtractor,
    LeagueHustlePlayerExtractor,
    LeagueHustleTeamExtractor,
)
from nbadb.extract.stats.matchups import LeagueSeasonMatchupsExtractor
from nbadb.extract.stats.misc import (
    DunkScoreLeadersExtractor,
    GravityLeadersExtractor,
    TeamGameStreakFinderExtractor,
    VideoDetailsAssetExtractor,
    VideoDetailsExtractor,
)
from nbadb.extract.stats.play_by_play import PlayByPlayV2Extractor
from nbadb.extract.stats.player_college import PlayerCareerByCollegeExtractor
from nbadb.extract.stats.player_game_log import (
    PlayerGameLogsV2Extractor,
    PlayerGameStreakFinderExtractor,
    PlayerStreakFinderExtractor,
)
from nbadb.extract.stats.player_info import PlayerAwardsExtractor, PlayerCareerStatsExtractor
from nbadb.extract.stats.player_tracking import (
    PlayerDashPtPassExtractor,
    PlayerDashPtRebExtractor,
    PlayerDashPtShotDefendExtractor,
    PlayerDashPtShotsExtractor,
)
from nbadb.extract.stats.schedule import ScheduleIntExtractor
from nbadb.extract.stats.shots import ShotChartLineupExtractor
from nbadb.extract.stats.team_info import CommonTeamRosterExtractor
from nbadb.extract.stats.team_tracking import (
    TeamDashPtPassExtractor,
    TeamDashPtRebExtractor,
    TeamDashPtShotsExtractor,
)
from nbadb.orchestrate.cume_workload_contract import CumeEntityKind, CumeWorkloadValue
from tests.unit.extract.test_stats_extractor_behaviors import TestMiscLeadersExtractors
from tests.unit.extract.test_stats_extractors import _ALL_EXTRACTORS


class TestScheduleIntExtractor:
    @staticmethod
    def _payload() -> dict[str, object]:
        return {
            "meta": {
                "version": 1,
                "request": "http://nba.cloud/league/00/2023-24/scheduleleaguev2?Format=json",
                "time": "2025-08-11T11:51:01.511Z",
            },
            "leagueSchedule": {
                "seasonYear": "2023-24",
                "leagueId": "00",
                "gameDates": [
                    {
                        "gameDate": "10/05/2023 00:00:00",
                        "games": [
                            {
                                "gameId": "0012300001",
                                "gameCode": "20231005/DALMIN",
                                "gameStatus": 3,
                                "gameStatusText": "Final",
                                "gameSequence": 1,
                                "gameDateEst": "2023-10-05T00:00:00Z",
                                "gameTimeEst": "1900-01-01T12:00:00Z",
                                "gameDateTimeEst": "2023-10-05T12:00:00Z",
                                "gameDateUTC": "2023-10-05T04:00:00Z",
                                "gameTimeUTC": "1900-01-01T16:00:00Z",
                                "gameDateTimeUTC": "2023-10-05T16:00:00Z",
                                "awayTeamTime": "2023-10-05T11:00:00Z",
                                "homeTeamTime": "2023-10-05T11:00:00Z",
                                "day": "Thu",
                                "monthNum": 10,
                                "weekNumber": 0,
                                "weekName": "",
                                "ifNecessary": False,
                                "seriesGameNumber": "",
                                "gameLabel": "",
                                "gameSubLabel": "",
                                "seriesText": "Preseason",
                                "arenaName": "Etihad Arena",
                                "arenaState": "",
                                "arenaCity": "Abu Dhabi",
                                "postponedStatus": "N",
                                "branchLink": "https://app.link.nba.com/sTXDSduQ8Db",
                                "gameSubtype": "",
                                "isNeutral": False,
                                "homeTeam": {
                                    "teamId": 1610612750,
                                    "teamName": "Timberwolves",
                                    "teamCity": "Minnesota",
                                    "teamTricode": "MIN",
                                    "teamSlug": "timberwolves",
                                    "wins": 0,
                                    "losses": 1,
                                    "score": 99,
                                    "seed": 0,
                                },
                                "awayTeam": {
                                    "teamId": 1610612742,
                                    "teamName": "Mavericks",
                                    "teamCity": "Dallas",
                                    "teamTricode": "DAL",
                                    "teamSlug": "mavericks",
                                    "wins": 1,
                                    "losses": 0,
                                    "score": 111,
                                    "seed": 0,
                                },
                            }
                        ],
                    }
                ],
                "weeks": [
                    {
                        "weekNumber": 0,
                        "weekName": "",
                        "startDate": "2023-10-05",
                        "endDate": "2023-10-11",
                    }
                ],
                "broadcasterList": [
                    {
                        "broadcasterAbbreviation": "TNT",
                        "broadcasterDisplay": "TNT",
                        "broadcasterId": 7,
                        "regionId": 1,
                    }
                ],
            },
        }

    class _FakeResponse:
        _status_code = 200

        def __init__(self) -> None:
            self._parser_input = json.dumps(
                TestScheduleIntExtractor._payload(),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )

        def get_response(self) -> str:
            return self._parser_input

        def get_dict(self) -> dict[str, object]:
            payload = json.loads(self._parser_input)
            assert isinstance(payload, dict)
            return payload

    @pytest.mark.asyncio
    async def test_extract_all_uses_owned_nested_schedule_parser(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = ScheduleIntExtractor()

        def _fake_send_api_request(
            self,
            *,
            endpoint: str,
            parameters: dict[str, object],
            proxy: object | None = None,
            headers: object | None = None,
            timeout: object | None = None,
        ) -> TestScheduleIntExtractor._FakeResponse:
            return TestScheduleIntExtractor._FakeResponse()

        monkeypatch.setattr(
            "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
            _fake_send_api_request,
        )

        games, weeks, broadcasters = await ext.extract_all(season="2023-24")

        assert games.to_dicts() == [
            {
                "league_id": "00",
                "season_year": "2023-24",
                "game_date": "10/05/2023 00:00:00",
                "game_id": "0012300001",
                "game_code": "20231005/DALMIN",
                "game_status": 3,
                "game_status_text": "Final",
                "game_sequence": 1,
                "game_date_est": "2023-10-05T00:00:00Z",
                "game_time_est": "1900-01-01T12:00:00Z",
                "game_date_time_est": "2023-10-05T12:00:00Z",
                "game_date_utc": "2023-10-05T04:00:00Z",
                "game_time_utc": "1900-01-01T16:00:00Z",
                "game_date_time_utc": "2023-10-05T16:00:00Z",
                "away_team_time": "2023-10-05T11:00:00Z",
                "home_team_time": "2023-10-05T11:00:00Z",
                "day": "Thu",
                "month_num": 10,
                "week_number": 0,
                "week_name": "",
                "if_necessary": False,
                "series_game_number": "",
                "game_label": "",
                "game_sub_label": "",
                "series_text": "Preseason",
                "arena_name": "Etihad Arena",
                "arena_state": "",
                "arena_city": "Abu Dhabi",
                "postponed_status": "N",
                "branch_link": "https://app.link.nba.com/sTXDSduQ8Db",
                "game_subtype": "",
                "is_neutral": False,
                "home_team_team_id": 1610612750,
                "home_team_team_name": "Timberwolves",
                "home_team_team_city": "Minnesota",
                "home_team_team_tricode": "MIN",
                "home_team_team_slug": "timberwolves",
                "home_team_wins": 0,
                "home_team_losses": 1,
                "home_team_score": 99,
                "home_team_seed": 0,
                "away_team_team_id": 1610612742,
                "away_team_team_name": "Mavericks",
                "away_team_team_city": "Dallas",
                "away_team_team_tricode": "DAL",
                "away_team_team_slug": "mavericks",
                "away_team_wins": 1,
                "away_team_losses": 0,
                "away_team_score": 111,
                "away_team_seed": 0,
            }
        ]
        assert weeks.to_dicts() == [
            {
                "league_id": "00",
                "season_year": "2023-24",
                "week_number": 0,
                "week_name": "",
                "start_date": "2023-10-05",
                "end_date": "2023-10-11",
            }
        ]
        assert broadcasters.to_dicts() == [
            {
                "league_id": "00",
                "season_year": "2023-24",
                "broadcaster_abbreviation": "TNT",
                "broadcaster_display": "TNT",
                "broadcaster_id": 7,
                "region_id": 1,
            }
        ]

    @pytest.mark.asyncio
    async def test_extract_returns_first_owned_schedule_frame(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = ScheduleIntExtractor()

        def _fake_send_api_request(
            self,
            *,
            endpoint: str,
            parameters: dict[str, object],
            proxy: object | None = None,
            headers: object | None = None,
            timeout: object | None = None,
        ) -> TestScheduleIntExtractor._FakeResponse:
            return TestScheduleIntExtractor._FakeResponse()

        monkeypatch.setattr(
            "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
            _fake_send_api_request,
        )

        result = await ext.extract(season="2023-24")

        assert result.get_column("game_id").to_list() == ["0012300001"]


@pytest.mark.asyncio
async def test_shot_chart_lineup_alias_uses_documented_default_group_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = ShotChartLineupExtractor()
    captured: list[dict[str, object]] = []

    def _single(_endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
        captured.append(kwargs)
        return pl.DataFrame()

    def _multi(_endpoint_cls: type, **kwargs: object) -> list[pl.DataFrame]:
        captured.append(kwargs)
        return [pl.DataFrame(), pl.DataFrame()]

    monkeypatch.setattr(extractor, "_from_nba_api", _single)
    monkeypatch.setattr(extractor, "_from_nba_api_multi", _multi)

    await extractor.extract(season="2024-25")
    await extractor.extract_all(season="2024-25")

    assert [kwargs["group_id"] for kwargs in captured] == [0, 0]


_EXTRACT_PARAMS: dict[str, dict[str, object]] = {
    "scoreboard_v2": {"game_date": "2024-10-22"},
    "common_player_info": {"player_id": 201939},
    "player_career_stats": {"player_id": 201939},
    "player_awards": {"player_id": 201939},
    "player_profile_v2": {"player_id": 201939},
    "player_index": {"season": "2024-25"},
    "common_all_players": {"season": "2024-25"},
    "player_estimated_metrics": {"season": "2024-25"},
    "player_game_streak_finder": {"season": "2024-25"},
    "player_career_by_college": {"season": "2024-25"},
    "player_career_by_college_rollup": {"season": "2024-25"},
    "player_compare": {"player_id": 201939, "season": "2024-25"},
    "player_vs_player": {
        "player_id": 201939,
        "vs_player_id": 201566,
        "season": "2024-25",
    },
    "team_vs_player": {
        "team_id": 1610612744,
        "vs_player_id": 201939,
        "season": "2024-25",
    },
    "team_and_players_vs_players": {
        "team_id": 1610612744,
        "vs_team_id": 1610612738,
        "player_id1": 201939,
        "player_id2": 201566,
        "player_id3": 1629029,
        "player_id4": 203999,
        "player_id5": 1630162,
        "vs_player_id1": 1628369,
        "vs_player_id2": 1627759,
        "vs_player_id3": 1628401,
        "vs_player_id4": 1627732,
        "vs_player_id5": 1630202,
        "season": "2024-25",
    },
    "team_historical_leaders": {"team_id": 1610612744},
    "team_year_by_year_stats": {"team_id": 1610612744},
    "all_time_leaders_grids": {},
    "team_dash_lineups": {"team_id": 1610612744, "season": "2024-25"},
    "league_player_on_details": {"team_id": 1610612744, "season": "2024-25"},
    "cume_stats_player": {
        "workload": CumeWorkloadValue.complete(
            entity_kind=CumeEntityKind.PLAYER,
            entity_id=201939,
            season="2024-25",
            season_type="Regular Season",
            game_ids=("0022400001",),
            foundation_receipt_sha256="a" * 64,
            provider_authority_sha256="b" * 64,
        )
    },
    "cume_stats_player_games": {"player_id": 201939, "season": "2024-25"},
    "cume_stats_team": {
        "workload": CumeWorkloadValue.complete(
            entity_kind=CumeEntityKind.TEAM,
            entity_id=1610612744,
            season="2024-25",
            season_type="Regular Season",
            game_ids=("0022400001",),
            foundation_receipt_sha256="c" * 64,
            provider_authority_sha256="d" * 64,
        )
    },
    "cume_stats_team_games": {"team_id": 1610612744, "season": "2024-25"},
    "gl_alum_box_score_similarity_score": {
        "person1_id": 201939,
        "person2_id": 201566,
    },
    "player_fantasy_profile": {"player_id": 201939, "season": "2024-25"},
    "video_details": {"player_id": 201939, "team_id": 1610612744, "season": "2024-25"},
    "video_details_asset": {
        "player_id": 201939,
        "team_id": 1610612744,
        "season": "2024-25",
    },
    "league_game_finder": {"season": "2024-25"},
    "team_game_streak_finder": {"season": "2024-25"},
    "team_game_logs": {"team_id": 1610612744, "season": "2024-25"},
    "video_events": {"game_id": "0022400001", "game_event_id": 7},
    "video_status": {"game_date": "2024-10-22", "league_id": "00"},
    "hustle_stats_box_score": {"game_id": "0022400001"},
    "franchise_history": {},
    "common_team_years": {},
    "team_estimated_metrics": {"season": "2024-25"},
    "shot_chart_detail": {"season": "2024-25"},
    "shot_chart_lineup_detail": {"season": "2024-25"},
}

_CATEGORY_DEFAULTS: dict[str, dict[str, object]] = {
    "box_score": {"game_id": "0022400001"},
    "play_by_play": {"game_id": "0022400001"},
    "game_log": {"season": "2024-25"},
    "player_info": {"player_id": 201939, "season": "2024-25"},
    "team_info": {"team_id": 1610612744, "season": "2024-25"},
    "draft": {"season": "2024-25"},
    "standings": {"season": "2024-25"},
    "shots": {"player_id": 201939, "season": "2024-25"},
    "league": {"season": "2024-25"},
    "schedule": {"season": "2024-25"},
    "rotation": {"game_id": "0022400001"},
    "synergy": {"season": "2024-25"},
    "hustle": {"season": "2024-25"},
    "tracking": {"season": "2024-25"},
    "leaders": {"season": "2024-25"},
    "misc": {"season": "2024-25"},
    "franchise": {"team_id": 1610612744},
}


def _get_params(endpoint_name: str, category: str) -> dict[str, object]:
    if endpoint_name in _EXTRACT_PARAMS:
        return _EXTRACT_PARAMS[endpoint_name]
    return _CATEGORY_DEFAULTS.get(category, {"season": "2024-25"})


from nbadb.extract.stats.player_dashboard import (  # noqa: E402
    PlayerDashGameSplitsExtractor,
    PlayerDashGeneralSplitsExtractor,
    PlayerDashLastNGamesExtractor,
    PlayerDashShootingSplitsExtractor,
    PlayerDashTeamPerfExtractor,
    PlayerDashYoyExtractor,
)

_ALL_WITH_ALIASES = _ALL_EXTRACTORS + [
    (PlayerDashGameSplitsExtractor, "player_dash_game_splits", "player_info"),
    (PlayerDashGeneralSplitsExtractor, "player_dash_general_splits", "player_info"),
    (PlayerDashLastNGamesExtractor, "player_dash_last_n_games", "player_info"),
    (PlayerDashShootingSplitsExtractor, "player_dash_shooting_splits", "player_info"),
    (PlayerDashTeamPerfExtractor, "player_dash_team_perf", "player_info"),
    (PlayerDashYoyExtractor, "player_dash_yoy", "player_info"),
]


@pytest.mark.parametrize(
    "cls, endpoint_name, category",
    _ALL_WITH_ALIASES,
    ids=[t[1] for t in _ALL_WITH_ALIASES],
)
class TestExtractMethodCoverage:
    @pytest.mark.asyncio
    async def test_extract_returns_dataframe(
        self,
        cls: type,
        endpoint_name: str,
        category: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = cls()
        dummy_df = pl.DataFrame({"col": [1, 2, 3]})

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            return dummy_df

        if cls is DraftBoardExtractor:
            monkeypatch.setattr(ext, "_from_nba_api", _fake)
        elif cls is PlayByPlayV2Extractor:
            monkeypatch.setattr(
                ext,
                "_from_nba_api_multi",
                lambda endpoint_cls, **kwargs: [dummy_df, pl.DataFrame()],
            )
        elif cls is PlayerCareerStatsExtractor:
            monkeypatch.setattr(
                ext, "_from_nba_api_multi", lambda endpoint_cls, **kwargs: [dummy_df]
            )
        elif cls is ScheduleIntExtractor:
            monkeypatch.setattr(
                ext,
                "_extract_all_owned",
                lambda **kwargs: [dummy_df, pl.DataFrame()],
            )
        elif cls is CommonTeamRosterExtractor:
            monkeypatch.setattr(
                ext,
                "_from_nba_api_multi",
                lambda endpoint_cls, **kwargs: [pl.DataFrame(), dummy_df],
            )
            monkeypatch.setattr(ext, "_validate", lambda df: df)
        elif cls in {
            DraftCombineDrillResultsExtractor,
            DraftCombineNonStationaryShootingExtractor,
            DraftCombinePlayerAnthroExtractor,
            DraftCombineSpotShootingExtractor,
            LeagueSeasonMatchupsExtractor,
            PlayerAwardsExtractor,
        }:
            monkeypatch.setattr(ext, "_call_nba_api", lambda endpoint_cls, **kwargs: [dummy_df])
            monkeypatch.setattr(ext, "_validate", lambda df: df)
        elif cls is DunkScoreLeadersExtractor:
            monkeypatch.setattr(
                "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
                lambda self, **_kwargs: TestMiscLeadersExtractors._FakeResponse(
                    payload={
                        "dunks": [
                            {
                                "gameId": "0022400001",
                                "playerId": 1,
                                "dunkScore": 8.5,
                            }
                        ]
                    }
                ),
            )
        elif cls is GravityLeadersExtractor:
            monkeypatch.setattr(
                "nbadb.extract.nba_api_adapter.NbaDbStatsHTTP.send_api_request",
                lambda self, **_kwargs: TestMiscLeadersExtractors._FakeResponse(
                    payload={"leaders": [{"PLAYERID": 1, "GRAVITYSCORE": 1.5}]}
                ),
            )
        elif cls in {VideoDetailsExtractor, VideoDetailsAssetExtractor}:
            monkeypatch.setattr(
                "nbadb.extract.stats.misc._extract_video_unknown_response",
                lambda *_args, **_kwargs: dummy_df,
            )
        else:
            monkeypatch.setattr(ext, "_from_nba_api", _fake)
        params = _get_params(endpoint_name, category)
        result = await ext.extract(**params)
        assert isinstance(result, pl.DataFrame)
        if cls is PlayByPlayV2Extractor:
            assert result.equals(dummy_df)


_TEAM_PARAMS = {"team_id": 1610612744, "season": "2024-25"}
_GAME_PARAMS = {"game_id": "0022400001"}

_EXTRACT_ALL_CASES = [
    (TeamDashPtShotsExtractor, "team_dash_pt_shots_all", _TEAM_PARAMS),
    (TeamDashPtPassExtractor, "team_dash_pt_pass_all", _TEAM_PARAMS),
    (TeamDashPtRebExtractor, "team_dash_pt_reb_all", _TEAM_PARAMS),
    (BoxScoreSummaryExtractor, "box_score_summary_all", _GAME_PARAMS),
    (BoxScoreSummaryV3Extractor, "box_score_summary_v3_all", _GAME_PARAMS),
    (HustleStatsBoxScoreExtractor, "hustle_box_score_all", _GAME_PARAMS),
]


@pytest.mark.asyncio
async def test_player_awards_normalizes_blank_all_nba_team_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ext = PlayerAwardsExtractor()
    raw = pl.DataFrame(
        {
            "person_id": [77907, 77917, 201939, 78017],
            "first_name": ["Bill", "Phil", "Stephen", "John"],
            "last_name": ["Russell", "Smith", "Curry", "Doe"],
            "team": ["", "", "Golden State Warriors", ""],
            "description": [
                "NBA Champion",
                "All-Rookie Team",
                "All-NBA",
                "Hall of Fame Inductee",
            ],
            "all_nba_team_number": ["", "1", " 2 ", None],
            "season": ["1956-57", "1971-72", "2024-25", "1982"],
            "month": [None, None, None, None],
            "week": [None, None, None, None],
            "conference": ["", "", "", ""],
            "type": ["Award", "Award", "Award", "Award"],
            "subtype1": ["", "", "", ""],
            "subtype2": ["", "", "", ""],
            "subtype3": ["", "", "", ""],
        }
    )

    monkeypatch.setattr(ext, "_call_nba_api", lambda endpoint_cls, **kwargs: [raw])

    result = await ext.extract(player_id=77907)

    assert result.get_column("all_nba_team_number").to_list() == [None, 1, 2, None]


@pytest.mark.parametrize(
    "cls, test_id, params",
    _EXTRACT_ALL_CASES,
    ids=[t[1] for t in _EXTRACT_ALL_CASES],
)
class TestExtractAllMethodCoverage:
    @pytest.mark.asyncio
    async def test_extract_all_returns_list(
        self,
        cls: type,
        test_id: str,
        params: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = cls()
        dummy_dfs = [
            pl.DataFrame({"col": [1]}),
            pl.DataFrame({"col": [2]}),
        ]

        def _fake_multi(endpoint_cls: type, **kwargs: object) -> list[pl.DataFrame]:
            return dummy_dfs

        monkeypatch.setattr(ext, "_from_nba_api_multi", _fake_multi)
        result = await ext.extract_all(**params)
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(df, pl.DataFrame) for df in result)


class TestPlayerTrackingTeamId:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cls",
        [PlayerDashPtPassExtractor, PlayerDashPtRebExtractor, PlayerDashPtShotsExtractor],
        ids=["pass", "reb", "shots"],
    )
    async def test_extract_all_defaults_team_id_to_zero(
        self,
        cls: type,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = cls()
        captured: dict[str, object] = {}

        def _fake_multi(endpoint_cls: type, **kwargs: object) -> list[pl.DataFrame]:
            captured.update(kwargs)
            return [pl.DataFrame({"ok": [1]})]

        monkeypatch.setattr(ext, "_from_nba_api_multi", _fake_multi)

        await ext.extract_all(player_id=2544, season="2024-25", season_type="Playoffs")

        assert captured["team_id"] == 0
        assert captured["season_type_all_star"] == "Playoffs"

    @pytest.mark.asyncio
    async def test_shot_defend_extract_defaults_team_id_to_zero(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = PlayerDashPtShotDefendExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured.update(kwargs)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)

        await ext.extract(player_id=2544, season="2024-25", season_type="Playoffs")

        assert captured["team_id"] == 0
        assert captured["season_type_all_star"] == "Playoffs"


class TestTeamTrackingExtractAllSeasonType:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cls",
        [TeamDashPtShotsExtractor, TeamDashPtPassExtractor, TeamDashPtRebExtractor],
        ids=["shots", "pass", "reb"],
    )
    async def test_extract_all_passes_season_type(
        self,
        cls: type,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = cls()
        captured: dict[str, object] = {}

        def _fake_multi(endpoint_cls: type, **kwargs: object) -> list[pl.DataFrame]:
            captured.update(kwargs)
            return [pl.DataFrame({"ok": [1]})]

        monkeypatch.setattr(ext, "_from_nba_api_multi", _fake_multi)
        await ext.extract_all(team_id=1610612744, season="2024-25", season_type="Playoffs")
        assert captured["season_type_all_star"] == "Playoffs"


class TestHustleExtractors:
    @pytest.mark.asyncio
    async def test_league_hustle_player_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = LeagueHustlePlayerExtractor()
        dummy_df = pl.DataFrame({"col": [1]})
        monkeypatch.setattr(ext, "_from_nba_api", lambda endpoint_cls, **kw: dummy_df)
        result = await ext.extract(season="2024-25")
        assert isinstance(result, pl.DataFrame)

    @pytest.mark.asyncio
    async def test_league_hustle_team_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = LeagueHustleTeamExtractor()
        dummy_df = pl.DataFrame({"col": [1]})
        monkeypatch.setattr(ext, "_from_nba_api", lambda endpoint_cls, **kw: dummy_df)
        result = await ext.extract(season="2024-25")
        assert isinstance(result, pl.DataFrame)

    @pytest.mark.asyncio
    async def test_league_hustle_player_extract_with_season_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ext = LeagueHustlePlayerExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(season="2024-25", season_type="Playoffs")
        assert captured["season_type_all_star"] == "Playoffs"

    @pytest.mark.asyncio
    async def test_league_hustle_team_extract_with_season_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ext = LeagueHustleTeamExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        await ext.extract(season="2024-25", season_type="Playoffs")
        assert captured["season_type_all_star"] == "Playoffs"


class TestDraftCombineExtractors:
    @pytest.mark.asyncio
    async def test_draft_combine_drill_results_injects_season_before_validation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = DraftCombineDrillResultsExtractor()
        captured_call: dict[str, object] = {}
        captured_validate: dict[str, pl.DataFrame] = {}

        def _fake_call(endpoint_cls: type, **kw: object) -> list[pl.DataFrame]:
            captured_call.update(kw)
            return [pl.DataFrame({"player_id": [1]})]

        def _fake_validate(df: pl.DataFrame) -> pl.DataFrame:
            captured_validate["df"] = df
            return df

        monkeypatch.setattr(ext, "_call_nba_api", _fake_call)
        monkeypatch.setattr(ext, "_validate", _fake_validate)

        result = await ext.extract(season="2024-25")

        assert isinstance(result, pl.DataFrame)
        assert captured_call["season_year"] == 2024
        assert captured_validate["df"]["season"].to_list() == ["2024-25"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cls",
        [
            DraftCombineNonStationaryShootingExtractor,
            DraftCombinePlayerAnthroExtractor,
            DraftCombineSpotShootingExtractor,
        ],
        ids=["non_stationary", "anthro", "spot"],
    )
    async def test_draft_combine_result_extractors_inject_season_before_validation(
        self,
        cls: type,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = cls()
        captured_call: dict[str, object] = {}
        captured_validate: dict[str, pl.DataFrame] = {}

        def _fake_call(endpoint_cls: type, **kw: object) -> list[pl.DataFrame]:
            captured_call.update(kw)
            return [pl.DataFrame({"player_id": [1]})]

        def _fake_validate(df: pl.DataFrame) -> pl.DataFrame:
            captured_validate["df"] = df
            return df

        monkeypatch.setattr(ext, "_call_nba_api", _fake_call)
        monkeypatch.setattr(ext, "_validate", _fake_validate)

        result = await ext.extract(season="2024-25")

        assert isinstance(result, pl.DataFrame)
        assert captured_call["season_year"] == 2024
        assert captured_validate["df"]["season"].to_list() == ["2024-25"]


class TestMatchupExtractors:
    @pytest.mark.asyncio
    async def test_league_season_matchups_coerces_clock_minutes_before_validation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = LeagueSeasonMatchupsExtractor()
        captured_call: dict[str, object] = {}
        captured_validate: dict[str, pl.DataFrame] = {}

        def _fake_call(endpoint_cls: type, **kw: object) -> list[pl.DataFrame]:
            captured_call.update(kw)
            return [pl.DataFrame({"matchup_min": ["5:30", "2", None]})]

        def _fake_validate(df: pl.DataFrame) -> pl.DataFrame:
            captured_validate["df"] = df
            return df

        monkeypatch.setattr(ext, "_call_nba_api", _fake_call)
        monkeypatch.setattr(ext, "_validate", _fake_validate)

        result = await ext.extract(season="2024-25", season_type="Regular Season")

        assert isinstance(result, pl.DataFrame)
        assert captured_call["season"] == "2024-25"
        assert captured_call["season_type_playoffs"] == "Regular Season"
        assert captured_validate["df"]["matchup_min"].to_list() == [5.5, 2.0, None]


class TestPlayerCollegeExtractors:
    @pytest.mark.asyncio
    async def test_player_career_by_college_extract_maps_api_params(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = PlayerCareerByCollegeExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        result = await ext.extract(college="Duke", season="2024-25", season_type="Playoffs")
        assert isinstance(result, pl.DataFrame)
        assert captured["college"] == "Duke"
        assert captured["season_nullable"] == "2024-25"
        assert captured["season_type_all_star"] == "Playoffs"
        assert "season" not in captured
        assert "season_type" not in captured


class TestPlayerGameLogV2Extractors:
    @pytest.mark.asyncio
    async def test_player_game_logs_v2_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = PlayerGameLogsV2Extractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        result = await ext.extract(player_id=2544, season="2024-25", season_type="Playoffs")
        assert isinstance(result, pl.DataFrame)
        assert captured["player_id_nullable"] == 2544
        assert captured["season_nullable"] == "2024-25"
        assert captured["season_type_nullable"] == "Playoffs"

    @pytest.mark.asyncio
    async def test_player_streak_finder_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = PlayerStreakFinderExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        result = await ext.extract(player_id=2544, season="2024-25")
        assert isinstance(result, pl.DataFrame)
        assert captured["player_id_nullable"] == 2544
        assert captured["season_nullable"] == "2024-25"

    @pytest.mark.asyncio
    async def test_player_game_streak_finder_extract_maps_nullable_params(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = PlayerGameStreakFinderExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        result = await ext.extract(player_id=2544, season="2024-25", season_type="Playoffs")
        assert isinstance(result, pl.DataFrame)
        assert captured["player_id_nullable"] == 2544
        assert captured["season_nullable"] == "2024-25"
        assert captured["season_type_nullable"] == "Playoffs"
        assert "player_id" not in captured
        assert "season" not in captured
        assert "season_type" not in captured

    @pytest.mark.asyncio
    async def test_team_game_streak_finder_extract_maps_nullable_params(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = TeamGameStreakFinderExtractor()
        captured: dict[str, object] = {}

        def _fake(endpoint_cls: type, **kw: object) -> pl.DataFrame:
            captured.update(kw)
            return pl.DataFrame({"ok": [1]})

        monkeypatch.setattr(ext, "_from_nba_api", _fake)
        result = await ext.extract(team_id=1610612744, season="2024-25", season_type="Playoffs")
        assert isinstance(result, pl.DataFrame)
        assert captured["team_id_nullable"] == 1610612744
        assert captured["season_nullable"] == "2024-25"
        assert captured["season_type_nullable"] == "Playoffs"
        assert "team_id" not in captured
        assert "season" not in captured
        assert "season_type" not in captured


class TestPlayByPlayV2Extractor:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "missing_key",
        ["AvailableVideo", "PlayByPlay", "resultSet", "resultSets"],
    )
    async def test_structural_empty_payload_returns_empty_result_sets(
        self,
        monkeypatch: pytest.MonkeyPatch,
        missing_key: str,
    ) -> None:
        ext = PlayByPlayV2Extractor()

        def _fake(endpoint_cls: type, **kw: object) -> list[pl.DataFrame]:
            raise KeyError(missing_key)

        monkeypatch.setattr(ext, "_from_nba_api_multi", _fake)

        result = await ext.extract_all(game_id="0020000945")

        assert len(result) == 2
        assert all(isinstance(df, pl.DataFrame) and df.is_empty() for df in result)

    @pytest.mark.asyncio
    async def test_extract_returns_first_empty_frame_for_deprecated_payload(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = PlayByPlayV2Extractor()

        def _fake(endpoint_cls: type, **kw: object) -> list[pl.DataFrame]:
            raise KeyError("AvailableVideo")

        monkeypatch.setattr(ext, "_from_nba_api_multi", _fake)

        result = await ext.extract(game_id="0020000945")

        assert isinstance(result, pl.DataFrame)
        assert result.is_empty()

    @pytest.mark.asyncio
    async def test_extract_returns_empty_frame_when_no_result_sets(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ext = PlayByPlayV2Extractor()

        def _fake(endpoint_cls: type, **kw: object) -> list[pl.DataFrame]:
            return []

        monkeypatch.setattr(ext, "_from_nba_api_multi", _fake)

        result = await ext.extract(game_id="0020000945")

        assert isinstance(result, pl.DataFrame)
        assert result.is_empty()

    @pytest.mark.asyncio
    async def test_unexpected_keyerror_still_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ext = PlayByPlayV2Extractor()

        def _fake(endpoint_cls: type, **kw: object) -> list[pl.DataFrame]:
            raise KeyError("unexpected")

        monkeypatch.setattr(ext, "_from_nba_api_multi", _fake)

        with pytest.raises(KeyError, match="unexpected"):
            await ext.extract_all(game_id="0020000945")


class TestSynergyPlayTypesExtractor:
    @pytest.fixture
    def synergy_ext(self):
        from nbadb.extract.stats.synergy import SynergyPlayTypesExtractor

        return SynergyPlayTypesExtractor()

    def test_fetch_uses_the_shared_adapter_contract(self, synergy_ext, monkeypatch):
        captured: dict[str, object] = {}

        def _fake_from_nba_api(_endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            captured.update(kwargs)
            return pl.DataFrame({"player_id": [1]})

        monkeypatch.setattr(synergy_ext, "_from_nba_api", _fake_from_nba_api)

        result = synergy_ext._fetch_synergy_frame(
            season="2024-25",
            season_type="Regular Season",
            play_type="Isolation",
            entity_type="P",
            grouping="offensive",
        )

        assert result.to_dicts() == [{"player_id": 1}]
        assert captured == {
            "season": "2024-25",
            "play_type_nullable": "Isolation",
            "player_or_team_abbreviation": "P",
            "season_type_all_star": "Regular Season",
            "type_grouping_nullable": "offensive",
        }

    def test_adapter_failure_propagates_without_local_retry(self, synergy_ext, monkeypatch):
        def _boom(_endpoint_cls: type, **_kwargs: object) -> pl.DataFrame:
            raise KeyError("resultSet")

        monkeypatch.setattr(synergy_ext, "_from_nba_api", _boom)

        with pytest.raises(KeyError, match="resultSet"):
            synergy_ext._fetch_synergy_frame(
                season="2024-25",
                season_type="Regular Season",
                play_type="Isolation",
                entity_type="P",
                grouping="offensive",
            )

    @pytest.mark.asyncio
    async def test_known_invalid_parameter_skips_all_putbacks_combos_via_fetch_path(
        self,
        synergy_ext,
        monkeypatch,
    ):
        called_play_types: list[str] = []

        def _fake_from_nba_api(_endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
            play_type = str(kwargs["play_type_nullable"])
            called_play_types.append(play_type)
            return pl.DataFrame({"val": [1]})

        monkeypatch.setattr(synergy_ext, "_from_nba_api", _fake_from_nba_api)

        result = await synergy_ext.extract(season="2024-25")

        assert result.shape[0] == 40
        assert "Putbacks" not in called_play_types

    @pytest.mark.asyncio
    async def test_iterates_all_combinations(self, synergy_ext, monkeypatch):
        calls: list[dict] = []

        monkeypatch.setattr(
            synergy_ext,
            "_fetch_synergy_frame",
            lambda **kw: calls.append(kw) or pl.DataFrame({"val": [1]}),
        )
        result = await synergy_ext.extract(season="2024-25")

        assert len(calls) == 44
        assert "play_type" in result.columns
        assert "entity_type" in result.columns
        assert "type_grouping" in result.columns
        assert result.shape[0] == 44

    @pytest.mark.asyncio
    async def test_non_retryable_failure_propagates(self, synergy_ext, monkeypatch):
        call_count = 0

        def _fake_fetch(**kw):
            nonlocal call_count
            call_count += 1
            if call_count == 5:
                raise ValueError("test failure")
            return pl.DataFrame({"val": [1]})

        monkeypatch.setattr(synergy_ext, "_fetch_synergy_frame", _fake_fetch)

        with pytest.raises(ValueError, match="test failure"):
            await synergy_ext.extract(season="2024-25")

        assert call_count == 5

    @pytest.mark.asyncio
    async def test_retryable_failure_propagates_to_the_runner(self, synergy_ext, monkeypatch):
        calls: list[tuple[str, str, str]] = []

        def _fake_fetch(**kw):
            combo = (
                kw["play_type"],
                kw["entity_type"],
                kw["grouping"],
            )
            calls.append(combo)
            if len(calls) == 5:
                raise ConnectionError("test failure")
            return pl.DataFrame({"val": [1]})

        monkeypatch.setattr(synergy_ext, "_fetch_synergy_frame", _fake_fetch)

        with pytest.raises(ConnectionError, match="test failure"):
            await synergy_ext.extract(season="2024-25")

        assert len(calls) == 5

    @pytest.mark.asyncio
    async def test_all_empty_combinations_return_empty_frame(self, synergy_ext, monkeypatch):
        def _fake_fetch(**kw):
            return pl.DataFrame(schema={"val": pl.Int64})

        monkeypatch.setattr(synergy_ext, "_fetch_synergy_frame", _fake_fetch)

        result = await synergy_ext.extract(season="2025-26", season_type="Playoffs")

        assert result.is_empty()
