from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import nbadb.contracts.independent_stats_value_decoder as decoder_module
from nbadb.contracts.independent_stats_value_decoder import (
    CUSTOM_NESTED_ENDPOINT_IDS,
    CUSTOM_NESTED_RESULT_ROUTE_COUNT,
    DecodedObservedStatsResponseV1,
    DecodedObservedStatsResultV1,
    DecodedStatsResultV1,
    IndependentStatsValueDecoderError,
    decode_observed_lossless_stats_response,
    decode_observed_lossless_stats_value_rows,
    decode_stats_value_rows,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_runtime_contracts,
)
from nbadb.extract.nba_api_adapter import (
    rederive_raw_authority_stats_fallback,
    rederive_raw_authority_unknown_stats_response,
)

_GENERIC_ROOTS = {
    "BoxScoreAdvancedV3": "boxScoreAdvanced",
    "BoxScoreDefensiveV2": "boxScoreDefensive",
    "BoxScoreFourFactorsV3": "boxScoreFourFactors",
    "BoxScoreHustleV2": "boxScoreHustle",
    "BoxScoreMiscV3": "boxScoreMisc",
    "BoxScorePlayerTrackV3": "boxScorePlayerTrack",
    "BoxScoreScoringV3": "boxScoreScoring",
    "BoxScoreUsageV3": "boxScoreUsage",
}
_TEAM_FIELDS = ("teamId", "teamCity", "teamName", "teamTricode", "teamSlug")
_PLAYER_FIELDS = (
    "personId",
    "firstName",
    "familyName",
    "nameI",
    "playerSlug",
    "position",
    "comment",
    "jerseyNum",
)
_BROADCASTER_TYPES = (
    "nationalBroadcasters",
    "nationalRadioBroadcasters",
    "nationalOttBroadcasters",
    "homeTvBroadcasters",
    "homeRadioBroadcasters",
    "homeOttBroadcasters",
    "awayTvBroadcasters",
    "awayRadioBroadcasters",
    "awayOttBroadcasters",
)


def _contract(endpoint_id: str):
    return pinned_runtime_contracts()[endpoint_id]


def _headers(endpoint_id: str) -> dict[str, tuple[str, ...]]:
    return {
        result.result_set_name: result.expected_columns
        for result in _contract(endpoint_id).result_sets
        if result.result_set_name is not None
    }


def _pins(endpoint_id: str) -> dict[str, str]:
    return {
        "endpoint_id": endpoint_id,
        "endpoint_contract_sha256": endpoint_contract_sha256(_contract(endpoint_id)),
        "provider_authority_sha256": expected_nba_api_provider_authority()["authority_sha256"],
    }


def _decode(endpoint_id: str, payload: object) -> tuple[DecodedStatsResultV1, ...]:
    return decode_stats_value_rows(
        **_pins(endpoint_id),
        parser_input=json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode(),
    )


def _decode_observed(endpoint_id: str, payload: object) -> tuple[DecodedObservedStatsResultV1, ...]:
    return decode_observed_lossless_stats_value_rows(
        **_pins(endpoint_id),
        parser_input=json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode(),
    )


def _decode_observed_response(endpoint_id: str, payload: object) -> DecodedObservedStatsResponseV1:
    return decode_observed_lossless_stats_response(
        **_pins(endpoint_id),
        parser_input=json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode(),
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _production_fallback(endpoint_id: str, payload: object):
    pins = _pins(endpoint_id)
    return rederive_raw_authority_stats_fallback(
        endpoint_id=endpoint_id,
        parser_input=json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode(),
        provider_authority_sha256=pins["provider_authority_sha256"],
        endpoint_contract_sha256_value=pins["endpoint_contract_sha256"],
    )


def _production_unknown(endpoint_id: str, payload: object):
    pins = _pins(endpoint_id)
    return rederive_raw_authority_unknown_stats_response(
        endpoint_id=endpoint_id,
        parser_input=json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode(),
        safe_parameters_json="{}",
        provider_authority_sha256=pins["provider_authority_sha256"],
        endpoint_contract_sha256_value=pins["endpoint_contract_sha256"],
    )


def _marker(prefix: str, fields: tuple[str, ...]) -> dict[str, object]:
    return {field: f"{prefix}:{field}" for field in fields}


def _generic_payload(endpoint_id: str) -> dict[str, object]:
    routes = _headers(endpoint_id)
    player_stats = routes["PlayerStats"][1 + len(_TEAM_FIELDS) + len(_PLAYER_FIELDS) :]
    team_stats = routes["TeamStats"][1 + len(_TEAM_FIELDS) :]

    def team(side: str) -> dict[str, object]:
        return {
            **_marker(side, _TEAM_FIELDS),
            "players": [
                {
                    **_marker(f"{side}-player", _PLAYER_FIELDS),
                    "statistics": _marker(f"{side}-player-stat", player_stats),
                }
            ],
            "statistics": _marker(f"{side}-team-stat", team_stats),
        }

    return {
        "meta": {"code": 200},
        _GENERIC_ROOTS[endpoint_id]: {
            "gameId": "game-1",
            "homeTeam": team("home"),
            "awayTeam": team("away"),
        },
    }


def _traditional_payload() -> dict[str, object]:
    endpoint_id = "BoxScoreTraditionalV3"
    routes = _headers(endpoint_id)
    player_stats = routes["PlayerStats"][1 + len(_TEAM_FIELDS) + len(_PLAYER_FIELDS) :]
    team_stats = routes["TeamStats"][1 + len(_TEAM_FIELDS) :]
    starter_stats = routes["TeamStarterBenchStats"][1 + len(_TEAM_FIELDS) : -1]

    def team(side: str) -> dict[str, object]:
        return {
            **_marker(side, _TEAM_FIELDS),
            "players": [
                {
                    **_marker(f"{side}-player", _PLAYER_FIELDS),
                    "statistics": _marker(f"{side}-player-stat", player_stats),
                }
            ],
            "statistics": _marker(f"{side}-team-stat", team_stats),
            "starters": _marker(f"{side}-starters", starter_stats),
            "bench": _marker(f"{side}-bench", starter_stats),
        }

    return {
        "meta": {"code": 200},
        "boxScoreTraditional": {
            "gameId": "game-1",
            "homeTeam": team("home"),
            "awayTeam": team("away"),
        },
    }


def _matchups_payload() -> dict[str, object]:
    headers = _headers("BoxScoreMatchupsV3")["PlayerStats"]
    player_start = headers.index("personIdOff")
    matchup_start = headers.index("personIdDef")
    stats_start = headers.index("matchupMinutes")
    team_keys = headers[1:player_start]
    player_keys = tuple(name.removesuffix("Off") for name in headers[player_start:matchup_start])
    matchup_keys = tuple(name.removesuffix("Def") for name in headers[matchup_start:stats_start])
    statistic_keys = headers[stats_start:]

    def team(side: str) -> dict[str, object]:
        return {
            **_marker(side, team_keys),
            "players": [
                {
                    **_marker(f"{side}-off", player_keys),
                    "matchups": [
                        {
                            **_marker(f"{side}-def", matchup_keys),
                            "statistics": _marker(f"{side}-stat", statistic_keys),
                        }
                    ],
                }
            ],
        }

    return {
        "meta": {"code": 200},
        "boxScoreMatchups": {
            "gameId": "game-1",
            "homeTeam": team("home"),
            "awayTeam": team("away"),
        },
    }


def _summary_payload() -> dict[str, object]:
    routes = _headers("BoxScoreSummaryV3")
    summary = _marker("summary", routes["GameSummary"])
    summary["gameId"] = "game-1"
    summary["gameEt"] = "2026-01-01T19:00:00"
    summary["duration"] = 123
    summary.update(_marker("video", routes["AvailableVideo"][1:]))
    summary["arena"] = _marker("arena", routes["ArenaInfo"][1:])
    summary["officials"] = [_marker("official", routes["Officials"][1:])]

    line_fields = routes["LineScore"]

    def team(side: str, inactive: bool) -> dict[str, object]:
        values = _marker(side, line_fields[1:8])
        values["periods"] = [{"period": number, "score": number * 10} for number in range(1, 5)]
        values["score"] = 100 if side == "home" else 90
        values["inactives"] = (
            [_marker(f"{side}-inactive", routes["InactivePlayers"][2:])] if inactive else []
        )
        return values

    summary["homeTeam"] = team("home", True)
    summary["awayTeam"] = team("away", False)
    meeting_headers = routes["LastFiveMeetings"]
    meeting = _marker("meeting", meeting_headers[:6])
    meeting["awayTeam"] = {
        "teamId": "away-id",
        "teamCity": "away-city",
        "teamName": "away-name",
        "teamTricode": "AWY",
        "score": 80,
        "wins": 1,
        "losses": 2,
    }
    meeting["homeTeam"] = {
        "teamId": "home-id",
        "teamCity": "home-city",
        "teamName": "home-name",
        "teamTricode": "HME",
        "score": 90,
        "wins": 2,
        "losses": 1,
    }
    summary["lastFiveMeetings"] = {"meetings": [meeting]}
    other_headers = routes["OtherStats"]
    summary["postgameCharts"] = {
        side: {
            **_marker(f"post-{side}", other_headers[1:5]),
            "statistics": _marker(f"post-{side}-stat", other_headers[5:]),
        }
        for side in ("homeTeam", "awayTeam")
    }
    return {"meta": {"code": 200}, "boxScoreSummary": summary}


def _gravity_payload() -> dict[str, object]:
    headers = _headers("GravityLeaders")["leaders"]
    leader = _marker("leader", headers)
    leader[headers[0]] = {"nested": [True, None, 7]}
    return {"leaders": [leader]}


def _play_by_play_payload(*, action_count: int = 1) -> dict[str, object]:
    routes = _headers("PlayByPlayV3")
    action_fields = routes["PlayByPlay"][1:]
    actions = []
    for index in range(action_count):
        action = _marker(f"action-{index}", action_fields)
        action[action_fields[0]] = index + 1
        actions.append(action)
    return {
        "meta": {"code": 200},
        "game": {"gameId": "game-1", "videoAvailable": 1, "actions": actions},
    }


def _ist_payload() -> dict[str, object]:
    headers = _headers("ISTStandings")["Standings"]
    first_game = headers.index("gameId1")
    team_keys = headers[2:first_game]
    games: list[dict[str, object]] = []
    for number in range(1, 5):
        start = headers.index(f"gameId{number}")
        end = headers.index(f"gameId{number + 1}") if number < 4 else len(headers)
        fields = tuple(name.removesuffix(str(number)) for name in headers[start:end])
        game: dict[str, object] = {}
        for index, field in enumerate(fields):
            game[field] = f"game-{number}:{field}"
            if index == 0:
                game["gameNumber"] = number
        games.append(game)
    return {
        "leagueId": "00",
        "seasonYear": "2025",
        "teams": [{**_marker("team", team_keys), "games": games}],
    }


def _schedule_payload(endpoint_id: str) -> dict[str, object]:
    routes = _headers(endpoint_id)
    headers = routes["SeasonGames"]
    home_start = headers.index("homeTeam_teamId")
    away_start = headers.index("awayTeam_teamId")
    points_start = headers.index("pointsLeaders_personId")
    first_broadcaster = min(
        headers.index(f"{name}_broadcasterScope") for name in _BROADCASTER_TYPES
    )
    scalar_keys = headers[3:home_start]
    home_keys = tuple(name.removeprefix("homeTeam_") for name in headers[home_start:away_start])
    away_keys = tuple(name.removeprefix("awayTeam_") for name in headers[away_start:points_start])
    assert away_keys == home_keys
    leader_keys = tuple(
        name.removeprefix("pointsLeaders_") for name in headers[points_start:first_broadcaster]
    )
    broadcasters: dict[str, object] = {}
    for index, broadcaster_type in enumerate(_BROADCASTER_TYPES):
        start = headers.index(f"{broadcaster_type}_broadcasterScope")
        end = (
            headers.index(f"{_BROADCASTER_TYPES[index + 1]}_broadcasterScope")
            if index + 1 < len(_BROADCASTER_TYPES)
            else len(headers)
        )
        keys = tuple(name.removeprefix(f"{broadcaster_type}_") for name in headers[start:end])
        broadcasters[broadcaster_type] = [_marker(broadcaster_type, keys)]
    game = {
        **_marker("game", scalar_keys),
        "broadcasters": broadcasters,
        "homeTeam": _marker("home", home_keys),
        "awayTeam": _marker("away", home_keys),
        "pointsLeaders": [_marker("leader", leader_keys)],
    }
    week_keys = routes["SeasonWeeks"][2:]
    root: dict[str, object] = {
        "seasonYear": "2025",
        "leagueId": "00",
        "gameDates": [{"gameDate": "2026-01-01", "games": [game]}],
        "weeks": [_marker("week", week_keys)],
    }
    if endpoint_id == "ScheduleLeagueV2Int":
        broadcaster_list_keys = routes["BroadcasterList"][2:]
        root["broadcasterList"] = [_marker("list", broadcaster_list_keys)]
    return {"meta": {"code": 200}, "leagueSchedule": root}


def _scoreboard_payload() -> dict[str, object]:
    routes = _headers("ScoreboardV3")
    game = _marker("game", routes["GameHeader"])
    game["gameId"] = "game-1"
    game["homeTeam"] = _marker("home", routes["LineScore"][1:])
    game["awayTeam"] = _marker("away", routes["LineScore"][1:])
    game["gameLeaders"] = {
        "homeLeaders": _marker("home-game-leader", routes["GameLeaders"][3:]),
        "awayLeaders": _marker("away-game-leader", routes["GameLeaders"][3:]),
    }
    game["teamLeaders"] = {
        "homeLeaders": _marker("home-team-leader", routes["TeamLeaders"][3:-1]),
        "awayLeaders": _marker("away-team-leader", routes["TeamLeaders"][3:-1]),
        "seasonLeadersFlag": 1,
    }
    broadcaster_fields = routes["Broadcasters"][2:]
    game["broadcasters"] = {
        source_name: ([_marker(source_name, broadcaster_fields)] if index == 0 else [])
        for index, source_name in enumerate(_BROADCASTER_TYPES)
    }
    scoreboard = {
        **_marker("scoreboard", routes["ScoreboardInfo"]),
        "games": [game],
    }
    return {"meta": {"code": 200}, "scoreboard": scoreboard}


def _payload_for(endpoint_id: str) -> dict[str, object]:
    if endpoint_id in _GENERIC_ROOTS:
        return _generic_payload(endpoint_id)
    if endpoint_id == "BoxScoreTraditionalV3":
        return _traditional_payload()
    if endpoint_id == "BoxScoreMatchupsV3":
        return _matchups_payload()
    if endpoint_id == "BoxScoreSummaryV3":
        return _summary_payload()
    if endpoint_id == "GravityLeaders":
        return _gravity_payload()
    if endpoint_id == "ISTStandings":
        return _ist_payload()
    if endpoint_id == "PlayByPlayV3":
        return _play_by_play_payload()
    if endpoint_id in {"ScheduleLeagueV2", "ScheduleLeagueV2Int"}:
        return _schedule_payload(endpoint_id)
    if endpoint_id == "ScoreboardV3":
        return _scoreboard_payload()
    raise AssertionError(f"missing test fixture for {endpoint_id}")


def _custom_lossless_payload(endpoint_id: str) -> dict[str, object]:
    """Return one independently reconstructable fallback body per custom identity."""

    if endpoint_id in _GENERIC_ROOTS:
        payload = _generic_payload(endpoint_id)
        boxscore = payload[_GENERIC_ROOTS[endpoint_id]]
        assert isinstance(boxscore, dict)
        home = boxscore["homeTeam"]
        assert isinstance(home, dict)
        statistics = home["statistics"]
        assert isinstance(statistics, dict)
        statistics[next(iter(statistics))] = {"x": [1]}
        return payload
    if endpoint_id == "BoxScoreTraditionalV3":
        payload = _traditional_payload()
        boxscore = payload["boxScoreTraditional"]
        assert isinstance(boxscore, dict)
        home = boxscore["homeTeam"]
        assert isinstance(home, dict)
        players = home["players"]
        assert isinstance(players, list)
        statistics = players[0]["statistics"]
        assert isinstance(statistics, dict)
        statistics[next(iter(statistics))] = {"x": [1]}
        return payload
    if endpoint_id == "BoxScoreMatchupsV3":
        payload = _matchups_payload()
        root = payload["boxScoreMatchups"]
        assert isinstance(root, dict)
        for side in ("homeTeam", "awayTeam"):
            team = root[side]
            assert isinstance(team, dict)
            team["upstreamTeamField"] = f"{side}:upstream"
        return payload
    if endpoint_id == "BoxScoreSummaryV3":
        payload = _summary_payload()
        summary = payload["boxScoreSummary"]
        assert isinstance(summary, dict)
        home = summary["homeTeam"]
        assert isinstance(home, dict)
        home["score"] = {"x": [1]}
        return payload
    if endpoint_id == "GravityLeaders":
        payload = _gravity_payload()
        leaders = payload["leaders"]
        assert isinstance(leaders, list)
        headers = _headers(endpoint_id)["leaders"]
        second = _marker("second", headers)
        second[headers[0]] = 7
        leaders.append(second)
        return payload
    if endpoint_id == "ISTStandings":
        payload = _ist_payload()
        teams = payload["teams"]
        assert isinstance(teams, list)
        team = teams[0]
        assert isinstance(team, dict)
        team["upstreamTeamField"] = "exact"
        return payload
    if endpoint_id == "PlayByPlayV3":
        payload = _play_by_play_payload(action_count=2)
        game = payload["game"]
        assert isinstance(game, dict)
        actions = game["actions"]
        assert isinstance(actions, list)
        actions[0]["actionNumber"] = {"x": [1]}
        return payload
    if endpoint_id in {"ScheduleLeagueV2", "ScheduleLeagueV2Int"}:
        payload = _schedule_payload(endpoint_id)
        root = payload["leagueSchedule"]
        assert isinstance(root, dict)
        dates = root["gameDates"]
        assert isinstance(dates, list)
        game = dates[0]["games"][0]
        assert isinstance(game, dict)
        game["upstreamGameField"] = "exact"
        return payload
    if endpoint_id == "ScoreboardV3":
        payload = _scoreboard_payload()
        scoreboard = payload["scoreboard"]
        assert isinstance(scoreboard, dict)
        games = scoreboard["games"]
        assert isinstance(games, list)
        home = games[0]["homeTeam"]
        assert isinstance(home, dict)
        home[next(iter(home))] = {"x": [1]}
        return payload
    raise AssertionError(f"missing custom lossless fixture for {endpoint_id}")


def _legacy_payload(endpoint_id: str, envelope: str = "resultSets") -> dict[str, object]:
    result_sets = []
    for result in _contract(endpoint_id).result_sets:
        assert result.result_set_name is not None
        result_sets.append(
            {
                "name": result.result_set_name,
                "headers": list(result.expected_columns),
                "rowSet": [[None for _header in result.expected_columns]],
            }
        )
    return {envelope: result_sets}


def test_custom_decoder_census_is_exactly_the_pinned_17_endpoints_and_44_routes() -> None:
    contracts = pinned_runtime_contracts()
    custom = {
        endpoint_id: contract
        for endpoint_id, contract in contracts.items()
        if contract.parser_kind == "custom_nested"
    }
    assert frozenset(custom) == CUSTOM_NESTED_ENDPOINT_IDS
    assert len(custom) == 17
    assert sum(len(contract.result_sets) for contract in custom.values()) == 44
    assert CUSTOM_NESTED_RESULT_ROUTE_COUNT == 44


@pytest.mark.parametrize("endpoint_id", sorted(CUSTOM_NESTED_ENDPOINT_IDS))
def test_every_custom_identity_observed_fallback_matches_production_receipt_order_and_digest(
    endpoint_id: str,
) -> None:
    payload = _custom_lossless_payload(endpoint_id)
    with pytest.raises(IndependentStatsValueDecoderError):
        _decode(endpoint_id, payload)

    production = _production_fallback(endpoint_id, payload)
    response = _decode_observed_response(endpoint_id, payload)
    observed = response.results
    assert production.reason_codes
    assert response.endpoint_id == endpoint_id
    assert response.endpoint_slug == _contract(endpoint_id).endpoint_slug
    assert response.response_mode == "declared_result_sets"
    assert response.provider_result_set_count == len(production.result_set_receipts)
    assert response.expected_result_set_count == len(_contract(endpoint_id).result_sets)
    assert response.reason_codes == production.reason_codes
    assert _decode_observed(endpoint_id, payload) == observed
    assert any(result.anomaly_codes for result in observed)
    assert [result.provider_ordinal for result in observed] == list(range(len(observed)))
    assert [result.result_name for result in observed] == [
        receipt.name for receipt in production.result_set_receipts
    ]
    assert [result.normalized_output_sha256 for result in observed] == [
        receipt.normalized_output_sha256 for receipt in production.result_set_receipts
    ]


@pytest.mark.parametrize("endpoint_id", sorted(CUSTOM_NESTED_ENDPOINT_IDS))
def test_every_pinned_custom_endpoint_decodes_its_complete_declared_inventory(
    endpoint_id: str,
) -> None:
    decoded = _decode(endpoint_id, _payload_for(endpoint_id))
    contract = _contract(endpoint_id)
    expected_names = {
        result.result_set_name for result in contract.result_sets if result.result_set_name
    }
    assert len(decoded) == len(contract.result_sets)
    assert {result.result_name for result in decoded} == expected_names
    assert tuple(result.provider_ordinal for result in decoded) == tuple(range(len(decoded)))
    assert all(result.duplicate_name_ordinal == 0 for result in decoded)
    assert all(
        result.ordered_headers == tuple(result.records[0]) for result in decoded if result.rows
    )


@pytest.mark.parametrize("endpoint_id", sorted(_GENERIC_ROOTS))
def test_generic_boxscore_family_preserves_provider_team_and_player_order(
    endpoint_id: str,
) -> None:
    decoded = {
        result.name: result for result in _decode(endpoint_id, _generic_payload(endpoint_id))
    }
    player = decoded["PlayerStats"]
    team = decoded["TeamStats"]
    team_id_index = player.ordered_headers.index("teamId")
    assert [row[team_id_index] for row in player.rows] == ["away:teamId", "home:teamId"]
    assert [row[team.ordered_headers.index("teamId")] for row in team.rows] == [
        "home:teamId",
        "away:teamId",
    ]


def test_traditional_family_preserves_starter_bench_and_home_away_order() -> None:
    decoded = {
        result.name: result for result in _decode("BoxScoreTraditionalV3", _traditional_payload())
    }
    labels = decoded["TeamStarterBenchStats"].ordered_headers.index("startersBench")
    assert [row[labels] for row in decoded["TeamStarterBenchStats"].rows] == [
        "Starters",
        "Bench",
        "Starters",
        "Bench",
    ]
    team_id = decoded["PlayerStats"].ordered_headers.index("teamId")
    assert [row[team_id] for row in decoded["PlayerStats"].rows] == [
        "home:teamId",
        "away:teamId",
    ]


def test_matchups_summary_gravity_ist_schedule_and_scoreboard_families_project_values() -> None:
    matchups = _decode("BoxScoreMatchupsV3", _matchups_payload())[0]
    assert matchups.row_count == 2
    assert matchups.rows[0][matchups.ordered_headers.index("personIdOff")] == ("home-off:personId")

    summary = {result.name: result for result in _decode("BoxScoreSummaryV3", _summary_payload())}
    assert summary["Officials"].row_count == 1
    assert summary["InactivePlayers"].row_count == 1
    assert summary["LastFiveMeetings"].row_count == 1
    assert (
        summary["LineScore"].rows[0][summary["LineScore"].ordered_headers.index("period4Score")]
        == 40
    )

    gravity = _decode("GravityLeaders", _gravity_payload())[0]
    assert gravity.rows[0][0] == {"nested": [True, None, 7]}

    standings = _decode("ISTStandings", _ist_payload())[0]
    assert standings.rows[0][standings.ordered_headers.index("gameId4")] == "game-4:gameId"

    schedule = {
        result.name: result
        for result in _decode("ScheduleLeagueV2", _schedule_payload("ScheduleLeagueV2"))
    }
    assert schedule["SeasonGames"].row_count == 1
    assert schedule["SeasonWeeks"].row_count == 1

    international = {
        result.name: result
        for result in _decode("ScheduleLeagueV2Int", _schedule_payload("ScheduleLeagueV2Int"))
    }
    assert international["BroadcasterList"].row_count == 1

    scoreboard = {result.name: result for result in _decode("ScoreboardV3", _scoreboard_payload())}
    assert scoreboard["LineScore"].row_count == 2
    assert scoreboard["GameLeaders"].row_count == 2
    assert scoreboard["TeamLeaders"].row_count == 2
    assert scoreboard["Broadcasters"].row_count == 1


def test_play_by_play_preserves_provider_order_canonical_ordinals_and_present_empty() -> None:
    decoded = _decode("PlayByPlayV3", _play_by_play_payload(action_count=0))
    assert [result.name for result in decoded] == ["PlayByPlay", "AvailableVideo"]
    assert [result.provider_ordinal for result in decoded] == [0, 1]
    assert [result.canonical_ordinal for result in decoded] == [1, 0]
    assert decoded[0].rows == ()
    assert decoded[1].rows == ((1,),)


@pytest.mark.parametrize("envelope", ["resultSets", "resultSet"])
def test_legacy_result_envelopes_decode_exact_pinned_headers_rows_and_records(
    envelope: str,
) -> None:
    endpoint_id = "CommonTeamYears"
    decoded = _decode(endpoint_id, _legacy_payload(endpoint_id, envelope))
    assert len(decoded) == len(_contract(endpoint_id).result_sets)
    assert all(
        result.rows == (tuple(None for _header in result.ordered_headers),) for result in decoded
    )
    assert all(tuple(result.records[0]) == result.ordered_headers for result in decoded)


def test_observed_lossless_league_game_log_additive_header_preserves_62_exact_rows() -> None:
    endpoint_id = "LeagueGameLog"
    payload = _legacy_payload(endpoint_id)
    result = payload["resultSets"][0]
    expected_headers = list(_contract(endpoint_id).result_sets[0].expected_columns)
    raw_headers = [*expected_headers, "UPSTREAM_ADDITIVE"]
    raw_rows = [[*[None for _header in expected_headers], row_ordinal] for row_ordinal in range(62)]
    result["headers"] = raw_headers
    result["rowSet"] = raw_rows

    with pytest.raises(IndependentStatsValueDecoderError, match="header order"):
        _decode(endpoint_id, payload)

    decoded = _decode_observed(endpoint_id, payload)
    assert len(decoded) == 1
    observed = decoded[0]
    assert observed.provider_ordinal == 0
    assert observed.canonical_ordinal == 0
    assert observed.duplicate_name_ordinal == 0
    assert observed.result_name == "LeagueGameLog"
    assert observed.presence == "present"
    assert observed.ordered_headers == tuple(raw_headers)
    assert observed.rows == tuple(tuple(row) for row in raw_rows)
    assert observed.row_count == 62
    assert observed.cell_count == 62 * len(raw_headers)
    assert observed.anomaly_codes == ("additive_header",)
    assert observed.normalized_output_sha256 == _canonical_sha256(
        {
            "headers": raw_headers,
            "rows": raw_rows,
            "anomalies": ["additive_header"],
        }
    )


def test_observed_response_seals_whole_league_game_log_fallback_evidence() -> None:
    endpoint_id = "LeagueGameLog"
    payload = _legacy_payload(endpoint_id)
    result = payload["resultSets"][0]
    result["headers"].append("UPSTREAM_ADDITIVE")
    result["rowSet"][0].append({"nested": [True, None]})

    response = _decode_observed_response(endpoint_id, payload)
    observed = response.results[0]
    assert response.endpoint_id == endpoint_id
    assert response.endpoint_slug == _contract(endpoint_id).endpoint_slug
    assert response.provider_result_set_count == 1
    assert response.expected_result_set_count == 1
    assert response.reason_codes == ("additive_header",)
    assert response.results_sha256 == _canonical_sha256(
        {
            "contract_id": "decoded_observed_stats_results_v1",
            "results": [
                {
                    "provider_ordinal": 0,
                    "canonical_ordinal": 0,
                    "duplicate_name_ordinal": 0,
                    "result_name": "LeagueGameLog",
                    "response_mode": "declared_result_sets",
                    "presence": "present",
                    "ordered_headers": list(observed.ordered_headers),
                    "effective_header_names": list(observed.effective_header_names),
                    "anomaly_codes": ["additive_header"],
                    "normalized_output_sha256": observed.normalized_output_sha256,
                    "raw_header_container_kind": "array",
                    "raw_row_container_kind": "array",
                    "raw_row_occurrence_count": 1,
                    "sequence_row_count": 1,
                    "cell_count": len(observed.ordered_headers),
                    "raw_headers_sha256": hashlib.sha256(
                        observed.canonical_raw_headers_json
                    ).hexdigest(),
                    "rows_sha256": hashlib.sha256(observed.canonical_rows_json).hexdigest(),
                }
            ],
        }
    )
    assert response.response_sha256 == _canonical_sha256(
        {
            "contract_id": "decoded_observed_stats_response_v1",
            "endpoint_id": endpoint_id,
            "endpoint_slug": response.endpoint_slug,
            "response_mode": "declared_result_sets",
            "provider_result_set_count": 1,
            "expected_result_set_count": 1,
            "reason_codes": ["additive_header"],
            "results_sha256": response.results_sha256,
        }
    )


def test_observed_response_preserves_mixed_raw_headers_and_nullable_effective_names() -> None:
    endpoint_id = "CommonTeamYears"
    raw_headers = ["LEAGUE_ID", {"unsupported": [1]}, "MIN_YEAR"]
    raw_rows = [["00", {"nested": True}, "1946"]]
    payload = {
        "resultSets": [
            {"name": "TeamYears", "headers": raw_headers, "rowSet": raw_rows},
        ]
    }

    production = _production_fallback(endpoint_id, payload)
    response = _decode_observed_response(endpoint_id, payload)
    observed = response.results[0]
    assert observed.raw_headers == tuple(raw_headers)
    assert observed.effective_header_names == ("LEAGUE_ID", None, "MIN_YEAR")
    assert observed.ordered_headers == ("LEAGUE_ID", "MIN_YEAR")
    assert observed.rows == (("00", {"nested": True}, "1946"),)
    assert "unsupported_header_shape" in observed.anomaly_codes
    assert response.reason_codes == production.reason_codes
    assert observed.normalized_output_sha256 == (
        production.result_set_receipts[0].normalized_output_sha256
    )

    exposed = observed.raw_headers
    assert isinstance(exposed[1], dict)
    exposed[1]["unsupported"].append("forged")
    assert observed.raw_headers == tuple(raw_headers)


@pytest.mark.parametrize(
    ("raw_headers", "container_kind"),
    [
        pytest.param({"forged": 1}, "object", id="object"),
        pytest.param("forged", "string", id="string"),
        pytest.param(None, "null", id="null"),
        pytest.param(True, "boolean", id="boolean"),
        pytest.param(7, "integer", id="integer"),
    ],
)
def test_observed_legacy_arbitrary_header_containers_match_production_fallback(
    raw_headers: object,
    container_kind: str,
) -> None:
    endpoint_id = "CommonTeamYears"
    expected_headers = tuple(_contract(endpoint_id).result_sets[0].expected_columns)
    raw_rows = [[None for _header in expected_headers]]
    payload = {
        "resultSets": [
            {"name": "TeamYears", "headers": raw_headers, "rowSet": raw_rows},
        ]
    }

    with pytest.raises(IndependentStatsValueDecoderError, match="headers must be an array"):
        _decode(endpoint_id, payload)
    production = _production_fallback(endpoint_id, payload)
    response = _decode_observed_response(endpoint_id, payload)
    observed = response.results[0]

    assert production.frame.height == 7
    assert (
        response.reason_codes
        == production.reason_codes
        == (
            "ragged_row",
            "removed_header",
            "unsupported_header_shape",
        )
    )
    assert observed.anomaly_codes == response.reason_codes
    assert observed.raw_header_container == raw_headers
    assert observed.raw_header_container_kind == container_kind
    assert observed.raw_headers == observed.fallback_header_values == ()
    assert observed.effective_header_names == observed.ordered_headers == ()
    assert observed.raw_row_container == raw_rows
    assert observed.rows == (tuple(raw_rows[0]),)
    assert observed.normalized_output_sha256 == (
        production.result_set_receipts[0].normalized_output_sha256
    )


@pytest.mark.parametrize(
    ("raw_rows", "container_kind"),
    [
        pytest.param({"forged": 1}, "object", id="object"),
        pytest.param("forged", "string", id="string"),
        pytest.param(None, "null", id="null"),
        pytest.param(True, "boolean", id="boolean"),
        pytest.param(7, "integer", id="integer"),
    ],
)
def test_observed_legacy_arbitrary_row_containers_match_production_fallback(
    raw_rows: object,
    container_kind: str,
) -> None:
    endpoint_id = "CommonTeamYears"
    raw_headers = list(_contract(endpoint_id).result_sets[0].expected_columns)
    payload = {
        "resultSets": [
            {"name": "TeamYears", "headers": raw_headers, "rowSet": raw_rows},
        ]
    }

    with pytest.raises(IndependentStatsValueDecoderError, match="rows must be an array"):
        _decode(endpoint_id, payload)
    production = _production_fallback(endpoint_id, payload)
    response = _decode_observed_response(endpoint_id, payload)
    observed = response.results[0]

    assert production.frame.height == 6
    assert response.reason_codes == production.reason_codes == ("unsupported_row_container",)
    assert observed.anomaly_codes == response.reason_codes
    assert observed.raw_row_container == raw_rows
    assert observed.raw_row_container_kind == container_kind
    assert observed.rows == observed.sequence_rows_by_ordinal == ()
    assert observed.row_count == observed.cell_count == 0
    assert observed.presence == "present_empty"
    assert observed.normalized_output_sha256 == (
        production.result_set_receipts[0].normalized_output_sha256
    )


@pytest.mark.parametrize(
    ("raw_row", "row_kind"),
    [
        pytest.param({"forged": 1}, "object", id="object"),
        pytest.param("forged", "string", id="string"),
        pytest.param(None, "null", id="null"),
        pytest.param(True, "boolean", id="boolean"),
        pytest.param(7, "integer", id="integer"),
    ],
)
def test_observed_legacy_non_sequence_rows_match_production_fallback(
    raw_row: object,
    row_kind: str,
) -> None:
    endpoint_id = "CommonTeamYears"
    raw_headers = list(_contract(endpoint_id).result_sets[0].expected_columns)
    payload = {
        "resultSets": [
            {"name": "TeamYears", "headers": raw_headers, "rowSet": [raw_row]},
        ]
    }

    with pytest.raises(IndependentStatsValueDecoderError, match="row 0 must be an array"):
        _decode(endpoint_id, payload)
    production = _production_fallback(endpoint_id, payload)
    response = _decode_observed_response(endpoint_id, payload)
    observed = response.results[0]

    assert production.frame.height == 7
    assert response.reason_codes == production.reason_codes == ("non_sequence_row",)
    assert observed.anomaly_codes == response.reason_codes
    assert observed.raw_row_container == [raw_row]
    assert observed.raw_row_container_kind == "array"
    assert decoder_module._json_value_kind(observed.rows[0]) == row_kind
    assert observed.sequence_rows_by_ordinal == ()
    assert observed.row_count == 1
    assert observed.cell_count == 0
    assert observed.presence == "present"
    assert observed.normalized_output_sha256 == (
        production.result_set_receipts[0].normalized_output_sha256
    )


@pytest.mark.parametrize(
    "nested_value",
    [
        pytest.param([1, "x"], id="mixed-array"),
        pytest.param({"a": {"b": [1, "x"]}}, id="mixed-object"),
    ],
)
def test_observed_legacy_unrepresentable_nested_values_match_production_fallback(
    nested_value: object,
) -> None:
    endpoint_id = "CommonTeamYears"
    raw_headers = list(_contract(endpoint_id).result_sets[0].expected_columns)
    raw_row = [nested_value, *[None for _header in raw_headers[1:]]]
    payload = {
        "resultSets": [
            {"name": "TeamYears", "headers": raw_headers, "rowSet": [raw_row]},
        ]
    }

    with pytest.raises(IndependentStatsValueDecoderError, match="lossless fallback"):
        _decode(endpoint_id, payload)
    production = _production_fallback(endpoint_id, payload)
    response = _decode_observed_response(endpoint_id, payload)
    observed = response.results[0]

    assert production.frame.height == 12
    assert response.reason_codes == production.reason_codes == ("unrepresentable_typed_frame",)
    assert observed.anomaly_codes == ()
    assert observed.raw_row_container == [raw_row]
    assert observed.rows == (tuple(raw_row),)
    assert observed.sequence_rows_by_ordinal == ((0, tuple(raw_row)),)
    assert observed.normalized_output_sha256 == (
        production.result_set_receipts[0].normalized_output_sha256
    )


@pytest.mark.parametrize(
    ("endpoint_id", "zero_result_name", "zero_rows", "expected_frame_height"),
    [
        pytest.param("DefenseHub", "DefenseHubStat10", [], 109, id="defense-empty"),
        pytest.param("DefenseHub", "DefenseHubStat10", [[]], 110, id="defense-one-row"),
        pytest.param("ScoreboardV2", "WinProbability", [], 237, id="scoreboard-empty"),
        pytest.param("ScoreboardV2", "WinProbability", [[]], 238, id="scoreboard-one-row"),
    ],
)
def test_observed_complete_zero_width_inventory_matches_production_fallback(
    endpoint_id: str,
    zero_result_name: str,
    zero_rows: list[list[object]],
    expected_frame_height: int,
) -> None:
    contract = _contract(endpoint_id)
    payload = {
        "resultSets": [
            {
                "name": route.result_set_name,
                "headers": list(route.expected_columns),
                "rowSet": (
                    zero_rows
                    if not route.expected_columns
                    else [[None for _header in route.expected_columns]]
                ),
            }
            for route in contract.result_sets
        ]
    }

    production = _production_fallback(endpoint_id, payload)
    response = _decode_observed_response(endpoint_id, payload)
    by_name = {result.result_name: result for result in response.results}
    zero_result = by_name[zero_result_name]

    assert production.frame.height == expected_frame_height
    assert response.reason_codes == production.reason_codes == ("unrepresentable_typed_frame",)
    assert all(result.anomaly_codes == () for result in response.results)
    assert zero_result.raw_header_container == []
    assert zero_result.raw_row_container == zero_rows
    assert zero_result.rows == tuple(tuple(row) for row in zero_rows)
    assert zero_result.row_count == len(zero_rows)
    assert [result.normalized_output_sha256 for result in response.results] == [
        receipt.normalized_output_sha256 for receipt in production.result_set_receipts
    ]


def test_observed_raw_container_accessors_are_mutation_isolated() -> None:
    raw_headers = {"nested": [1]}
    raw_rows = [{"nested": [2]}]
    payload = {
        "resultSets": [
            {"name": "TeamYears", "headers": raw_headers, "rowSet": raw_rows},
        ]
    }
    observed = _decode_observed("CommonTeamYears", payload)[0]

    exposed_headers = observed.raw_header_container
    exposed_rows = observed.raw_row_container
    assert isinstance(exposed_headers, dict)
    assert isinstance(exposed_rows, list)
    exposed_headers["nested"].append("forged")
    exposed_rows[0]["nested"].append("forged")

    assert observed.raw_header_container == raw_headers
    assert observed.raw_row_container == raw_rows


def test_observed_response_rejects_tampered_reasons_slug_canonical_index_and_digests() -> None:
    payload = _legacy_payload("CommonTeamYears")
    payload["resultSets"][0]["headers"].append("UPSTREAM_ADDITIVE")
    payload["resultSets"][0]["rowSet"][0].append(1)
    response = _decode_observed_response("CommonTeamYears", payload)
    result = response.results[0]

    common = {
        "endpoint_id": response.endpoint_id,
        "endpoint_slug": response.endpoint_slug,
        "response_mode": response.response_mode,
        "provider_result_set_count": response.provider_result_set_count,
        "expected_result_set_count": response.expected_result_set_count,
        "reason_codes": response.reason_codes,
        "results": response.results,
        "results_sha256": response.results_sha256,
        "response_sha256": response.response_sha256,
    }
    with pytest.raises(IndependentStatsValueDecoderError, match="pinned endpoint"):
        DecodedObservedStatsResponseV1(**{**common, "endpoint_slug": "forged"})
    with pytest.raises(IndependentStatsValueDecoderError, match="reasons"):
        DecodedObservedStatsResponseV1(**{**common, "reason_codes": ("removed_header",)})

    forged_result = DecodedObservedStatsResultV1(
        provider_ordinal=result.provider_ordinal,
        canonical_ordinal=None,
        duplicate_name_ordinal=result.duplicate_name_ordinal,
        result_name=result.result_name,
        response_mode=result.response_mode,
        presence=result.presence,
        ordered_headers=result.ordered_headers,
        effective_header_names=result.effective_header_names,
        anomaly_codes=result.anomaly_codes,
        normalized_output_sha256=result.normalized_output_sha256,
        _canonical_raw_headers_json=result.canonical_raw_headers_json,
        _canonical_rows_json=result.canonical_rows_json,
    )
    with pytest.raises(IndependentStatsValueDecoderError, match="canonical provider"):
        DecodedObservedStatsResponseV1(**{**common, "results": (forged_result,)})
    with pytest.raises(IndependentStatsValueDecoderError, match="result digest"):
        DecodedObservedStatsResponseV1(**{**common, "results_sha256": "0" * 64})
    with pytest.raises(IndependentStatsValueDecoderError, match="response digest"):
        DecodedObservedStatsResponseV1(**{**common, "response_sha256": "0" * 64})
    with pytest.raises(IndependentStatsValueDecoderError, match="output digest"):
        DecodedObservedStatsResultV1(
            provider_ordinal=result.provider_ordinal,
            canonical_ordinal=result.canonical_ordinal,
            duplicate_name_ordinal=result.duplicate_name_ordinal,
            result_name=result.result_name,
            response_mode=result.response_mode,
            presence=result.presence,
            ordered_headers=result.ordered_headers,
            effective_header_names=result.effective_header_names,
            anomaly_codes=result.anomaly_codes,
            normalized_output_sha256="0" * 64,
            _canonical_raw_headers_json=result.canonical_raw_headers_json,
            _canonical_rows_json=result.canonical_rows_json,
        )


def test_observed_lossless_additive_result_precedes_appended_missing_expected_result() -> None:
    additive_headers = ["UPSTREAM_KEY", "UPSTREAM_VALUE"]
    additive_rows = [[1, {"nested": [True, None, "exact"]}]]
    payload = {
        "resultSets": [
            {
                "name": "UpstreamAdditive",
                "headers": additive_headers,
                "rowSet": additive_rows,
            }
        ]
    }

    decoded = _decode_observed("CommonTeamYears", payload)
    assert [result.result_name for result in decoded] == ["UpstreamAdditive", "TeamYears"]
    additive, missing = decoded
    assert (
        additive.provider_ordinal,
        additive.canonical_ordinal,
        additive.duplicate_name_ordinal,
        additive.presence,
    ) == (0, None, 0, "present")
    assert additive.ordered_headers == tuple(additive_headers)
    assert additive.rows == ((1, {"nested": [True, None, "exact"]}),)
    assert additive.anomaly_codes == ()
    assert additive.normalized_output_sha256 == _canonical_sha256(
        {"headers": additive_headers, "rows": additive_rows, "anomalies": []}
    )

    expected_headers = tuple(_contract("CommonTeamYears").result_sets[0].expected_columns)
    assert (
        missing.provider_ordinal,
        missing.canonical_ordinal,
        missing.duplicate_name_ordinal,
        missing.presence,
    ) == (None, 0, 0, "missing")
    assert missing.ordered_headers == expected_headers
    assert missing.rows == ()
    assert missing.anomaly_codes == ()
    assert missing.normalized_output_sha256 == _canonical_sha256(
        {"headers": list(expected_headers), "rows": []}
    )


@pytest.mark.parametrize(
    ("mutation", "expected_anomalies"),
    [
        ("additive", ("additive_header",)),
        ("removed", ("removed_header",)),
        ("reordered", ("reordered_header",)),
    ],
)
def test_observed_lossless_preserves_additive_removed_and_reordered_headers(
    mutation: str,
    expected_anomalies: tuple[str, ...],
) -> None:
    endpoint_id = "CommonTeamYears"
    payload = _legacy_payload(endpoint_id)
    result = payload["resultSets"][0]
    headers = list(result["headers"])
    row = list(range(len(headers)))
    if mutation == "additive":
        headers.append("UPSTREAM_ADDITIVE")
        row.append("exact")
    elif mutation == "removed":
        headers.pop(1)
        row.pop(1)
    else:
        headers[0], headers[1] = headers[1], headers[0]
        row[0], row[1] = row[1], row[0]
    result["headers"] = headers
    result["rowSet"] = [row]

    with pytest.raises(IndependentStatsValueDecoderError, match="header order"):
        _decode(endpoint_id, payload)
    observed = _decode_observed(endpoint_id, payload)[0]
    assert observed.canonical_ordinal == 0
    assert observed.ordered_headers == tuple(headers)
    assert observed.rows == (tuple(row),)
    assert observed.anomaly_codes == expected_anomalies
    assert observed.normalized_output_sha256 == _canonical_sha256(
        {"headers": headers, "rows": [row], "anomalies": list(expected_anomalies)}
    )


def test_observed_lossless_preserves_duplicate_result_names_and_provider_order() -> None:
    payload = _legacy_payload("CommonTeamYears")
    first = payload["resultSets"][0]
    second = json.loads(json.dumps(first))
    first["rowSet"] = [[1, 2, 3, 4, 5]]
    second["rowSet"] = [[6, 7, 8, 9, 10]]
    payload["resultSets"].append(second)

    decoded = _decode_observed("CommonTeamYears", payload)
    assert [result.provider_ordinal for result in decoded] == [0, 1]
    assert [result.canonical_ordinal for result in decoded] == [None, None]
    assert [result.duplicate_name_ordinal for result in decoded] == [0, 1]
    assert [result.result_name for result in decoded] == ["TeamYears", "TeamYears"]
    assert [result.rows for result in decoded] == [
        ((1, 2, 3, 4, 5),),
        ((6, 7, 8, 9, 10),),
    ]
    assert all(result.presence == "present" for result in decoded)
    assert all(result.anomaly_codes == () for result in decoded)


def test_observed_lossless_preserves_duplicate_headers_and_ragged_heterogeneous_rows() -> None:
    duplicate_payload = _legacy_payload("CommonTeamYears")
    duplicate_result = duplicate_payload["resultSets"][0]
    duplicate_headers = list(duplicate_result["headers"])
    duplicate_headers[1] = duplicate_headers[0]
    duplicate_result["headers"] = duplicate_headers
    duplicate = _decode_observed("CommonTeamYears", duplicate_payload)[0]
    assert duplicate.ordered_headers == tuple(duplicate_headers)
    assert duplicate.ordered_headers.count(duplicate_headers[0]) == 2
    assert duplicate.anomaly_codes == (
        "additive_header",
        "duplicate_header",
        "removed_header",
    )

    ragged_payload = _legacy_payload("CommonTeamYears")
    ragged_result = ragged_payload["resultSets"][0]
    ragged_result["rowSet"] = [[1], [True, 2]]
    ragged = _decode_observed("CommonTeamYears", ragged_payload)[0]
    assert ragged.rows == ((1,), (True, 2))
    assert ragged.cell_count == 3
    assert ragged.anomaly_codes == ("heterogeneous_column", "ragged_row")


def test_observed_lossless_zero_width_distinguishes_present_empty_from_one_empty_row() -> None:
    endpoint_id = "DefenseHub"
    empty_payload = {
        "resultSets": [
            {"name": "DefenseHubStat10", "headers": [], "rowSet": []},
        ]
    }
    one_row_payload = json.loads(json.dumps(empty_payload))
    one_row_payload["resultSets"][0]["rowSet"] = [[]]

    empty = _decode_observed(endpoint_id, empty_payload)[0]
    one_row = _decode_observed(endpoint_id, one_row_payload)[0]
    assert empty.result_name == one_row.result_name == "DefenseHubStat10"
    assert empty.canonical_ordinal == one_row.canonical_ordinal == 1
    assert empty.ordered_headers == one_row.ordered_headers == ()
    assert empty.presence == "present_empty"
    assert empty.rows == ()
    assert empty.row_count == 0
    assert one_row.presence == "present"
    assert one_row.rows == ((),)
    assert one_row.row_count == 1
    assert empty.normalized_output_sha256 != one_row.normalized_output_sha256


@pytest.mark.parametrize("error_key", ["Message", "message", "error"])
def test_observed_lossless_top_level_error_without_result_envelope_fails_closed(
    error_key: str,
) -> None:
    with pytest.raises(IndependentStatsValueDecoderError, match="error envelope"):
        _decode_observed("CommonTeamYears", {error_key: "provider error"})


def test_observed_lossless_numeric_error_with_otherwise_valid_envelope_fails_closed() -> None:
    payload = _legacy_payload("CommonTeamYears")
    payload["statusCode"] = 503
    with pytest.raises(IndependentStatsValueDecoderError, match="error envelope"):
        _decode_observed("CommonTeamYears", payload)


def test_observed_unknown_dynamic_legacy_results_match_exact_production_occurrences() -> None:
    endpoint_id = "VideoEvents"
    payload = {
        "resultSets": [
            {"name": "Observed", "headers": [], "rowSet": [[]]},
            {
                "name": "Observed",
                "headers": ["A", "B"],
                "rowSet": [[1, {"nested": [True, None]}]],
            },
        ],
        "future": {"nested": [True, None]},
    }

    production = _production_unknown(endpoint_id, payload)
    response = _decode_observed_response(endpoint_id, payload)

    assert production.state == "legacy_present_nonempty"
    assert production.legacy_envelope_name == "resultSets"
    assert response.response_mode == "unknown_dynamic_response"
    assert response.provider_result_set_count == 2
    assert response.expected_result_set_count == 0
    assert response.reason_codes == ("unknown_dynamic_response",)
    assert response.results == _decode_observed(endpoint_id, payload)
    assert [result.provider_ordinal for result in response.results] == [0, 1]
    assert [result.canonical_ordinal for result in response.results] == [None, None]
    assert [result.duplicate_name_ordinal for result in response.results] == [0, 1]
    assert [result.response_mode for result in response.results] == [
        "unknown_dynamic_response",
        "unknown_dynamic_response",
    ]
    assert [result.ordered_headers for result in response.results] == [(), ("A", "B")]
    assert [result.rows for result in response.results] == [
        ((),),
        ((1, {"nested": [True, None]}),),
    ]
    assert [result.normalized_output_sha256 for result in response.results] == [
        occurrence.receipt.normalized_output_sha256 for occurrence in production.occurrences
    ]


def test_observed_unknown_dynamic_empty_legacy_envelope_preserves_zero_denominator() -> None:
    endpoint_id = "VideoDetails"
    payload = {"resultSet": []}

    production = _production_unknown(endpoint_id, payload)
    response = _decode_observed_response(endpoint_id, payload)

    assert production.state == "legacy_present_empty"
    assert production.occurrences == ()
    assert response.response_mode == "unknown_dynamic_response"
    assert response.provider_result_set_count == 0
    assert response.expected_result_set_count == 0
    assert response.reason_codes == ("unknown_dynamic_response",)
    assert response.results == ()
    assert _decode_observed(endpoint_id, payload) == ()


@pytest.mark.parametrize(
    "payload",
    [
        {"future": {"nested": [1]}},
        {"resultSets": "invalid"},
        {"resultSets": [1]},
        {"resultSets": [{"name": "Observed", "headers": {}, "rowSet": []}]},
        {"resultSets": [{"name": "Observed", "headers": [""], "rowSet": []}]},
        {"resultSets": [{"name": "Observed", "headers": ["A"], "rowSet": {}}]},
        {"resultSets": [{"name": "Observed", "headers": ["A"], "rowSet": [[]]}]},
    ],
)
def test_observed_unknown_dynamic_rejects_nonlegacy_or_malformed_occurrences(
    payload: object,
) -> None:
    with pytest.raises(IndependentStatsValueDecoderError):
        _decode_observed_response("VideoEvents", payload)


def test_observed_unknown_dynamic_rejects_false_success_and_resealed_mode_or_digest() -> None:
    endpoint_id = "VideoEvents"
    payload = {
        "code": 500,
        "resultSets": [{"name": "Observed", "headers": ["A"], "rowSet": [[1]]}],
    }
    with pytest.raises(IndependentStatsValueDecoderError, match="error envelope"):
        _decode_observed_response(endpoint_id, payload)

    payload.pop("code")
    response = _decode_observed_response(endpoint_id, payload)
    common = {
        "endpoint_id": response.endpoint_id,
        "endpoint_slug": response.endpoint_slug,
        "response_mode": response.response_mode,
        "provider_result_set_count": response.provider_result_set_count,
        "expected_result_set_count": response.expected_result_set_count,
        "reason_codes": response.reason_codes,
        "results": response.results,
        "results_sha256": response.results_sha256,
        "response_sha256": response.response_sha256,
    }
    with pytest.raises(IndependentStatsValueDecoderError):
        DecodedObservedStatsResponseV1(
            **{
                **common,
                "response_mode": "declared_result_sets",
            }
        )
    with pytest.raises(IndependentStatsValueDecoderError, match="reasons"):
        DecodedObservedStatsResponseV1(
            **{
                **common,
                "reason_codes": ("additive_result_set",),
            }
        )

    exact = response.results[0]
    object.__setattr__(exact, "normalized_output_sha256", "0" * 64)
    with pytest.raises(IndependentStatsValueDecoderError, match="output digest"):
        DecodedObservedStatsResponseV1(**common)


def test_observed_lossless_traditional_heterogeneity_matches_production_fallback() -> None:
    endpoint_id = "BoxScoreTraditionalV3"
    payload = _traditional_payload()
    root = payload["boxScoreTraditional"]
    assert isinstance(root, dict)
    home = root["homeTeam"]
    assert isinstance(home, dict)
    home_players = home["players"]
    assert isinstance(home_players, list)
    home_statistics = home_players[0]["statistics"]
    assert isinstance(home_statistics, dict)
    statistic_name = next(iter(home_statistics))
    home_statistics[statistic_name] = {"x": [1]}

    with pytest.raises(IndependentStatsValueDecoderError, match="lossless fallback"):
        _decode(endpoint_id, payload)
    production = _production_fallback(endpoint_id, payload)
    observed = _decode_observed(endpoint_id, payload)

    assert production.reason_codes == ("heterogeneous_column",)
    assert production.frame.height == 321
    assert [result.result_name for result in observed] == [
        "PlayerStats",
        "TeamStarterBenchStats",
        "TeamStats",
    ]
    assert [result.provider_ordinal for result in observed] == [0, 1, 2]
    assert [result.canonical_ordinal for result in observed] == [0, 1, 2]
    assert observed[0].anomaly_codes == ("heterogeneous_column",)
    assert observed[1].anomaly_codes == observed[2].anomaly_codes == ()
    assert [result.normalized_output_sha256 for result in observed] == [
        receipt.normalized_output_sha256 for receipt in production.result_set_receipts
    ]


@pytest.mark.parametrize(
    ("endpoint_id", "zero_result_name", "zero_canonical_ordinal"),
    [
        ("DefenseHub", "DefenseHubStat10", 1),
        ("ScoreboardV2", "WinProbability", 9),
    ],
)
def test_exact_pinned_zero_column_routes_preserve_rows_and_complete_inventory(
    endpoint_id: str,
    zero_result_name: str,
    zero_canonical_ordinal: int,
) -> None:
    contract = _contract(endpoint_id)
    one_zero_width_row = _legacy_payload(endpoint_id)
    decoded = _decode(endpoint_id, one_zero_width_row)
    by_name = {result.result_name: result for result in decoded}

    assert len(decoded) == len(contract.result_sets) == 10
    assert tuple(result.provider_ordinal for result in decoded) == tuple(range(10))
    assert {result.result_name for result in decoded} == {
        result.result_set_name for result in contract.result_sets
    }
    zero_result = by_name[zero_result_name]
    assert zero_result.canonical_ordinal == zero_canonical_ordinal
    assert zero_result.ordered_headers == ()
    assert zero_result.rows == ((),)
    assert tuple(dict(record) for record in zero_result.records) == ({},)

    nonzero_results = [result for result in decoded if result.result_name != zero_result_name]
    assert len(nonzero_results) == 9
    assert all(result.ordered_headers and result.row_count == 1 for result in nonzero_results)
    assert all(tuple(result.records[0]) == result.ordered_headers for result in nonzero_results)

    no_rows = json.loads(json.dumps(one_zero_width_row))
    zero_payload = next(
        result for result in no_rows["resultSets"] if result["name"] == zero_result_name
    )
    zero_payload["rowSet"] = []
    empty_result = {result.result_name: result for result in _decode(endpoint_id, no_rows)}[
        zero_result_name
    ]
    assert empty_result.rows == ()
    assert empty_result.row_count == 0
    assert empty_result.normalized_output_sha256 != zero_result.normalized_output_sha256


@pytest.mark.parametrize(
    ("endpoint_id", "zero_result_name"),
    [
        ("DefenseHub", "DefenseHubStat10"),
        ("ScoreboardV2", "WinProbability"),
    ],
)
def test_zero_column_routes_reject_nonempty_values_and_foreign_headers(
    endpoint_id: str,
    zero_result_name: str,
) -> None:
    nonempty_value = _legacy_payload(endpoint_id)
    zero_payload = next(
        result for result in nonempty_value["resultSets"] if result["name"] == zero_result_name
    )
    zero_payload["rowSet"] = [[1]]
    with pytest.raises(IndependentStatsValueDecoderError, match="row width"):
        _decode(endpoint_id, nonempty_value)

    foreign_headers = _legacy_payload(endpoint_id)
    zero_payload = next(
        result for result in foreign_headers["resultSets"] if result["name"] == zero_result_name
    )
    zero_payload["headers"] = ["FORGED"]
    zero_payload["rowSet"] = [[1]]
    with pytest.raises(IndependentStatsValueDecoderError, match="header order"):
        _decode(endpoint_id, foreign_headers)


def test_structured_legacy_header_grammar_is_independent_and_exact() -> None:
    headers = decoder_module._structured_legacy_headers(
        [
            {
                "name": "columns",
                "columnNames": ["ID", "FGM", "FGA", "FGM", "FGA"],
            },
            {
                "name": "Shot Zones",
                "columnNames": ["Restricted Area", "Paint"],
                "columnSpan": 2,
                "columnsToSkip": 1,
            },
        ]
    )
    assert headers == (
        "ID",
        "restricted_area_fgm",
        "restricted_area_fga",
        "paint_fgm",
        "paint_fga",
    )


def test_normalized_output_digest_matches_the_exact_contract_encoding() -> None:
    result = _decode("GravityLeaders", _gravity_payload())[0]
    expected = hashlib.sha256(
        json.dumps(
            {
                "headers": list(result.ordered_headers),
                "rows": [list(row) for row in result.rows],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    assert result.normalized_output_sha256 == expected


def test_rows_and_records_are_isolated_from_nested_json_mutation() -> None:
    result = _decode("GravityLeaders", _gravity_payload())[0]
    rows = result.rows
    nested = rows[0][0]
    assert isinstance(nested, dict)
    nested["nested"].append("forged")
    assert result.rows[0][0] == {"nested": [True, None, 7]}
    with pytest.raises(TypeError):
        result.records[0][result.ordered_headers[0]] = "forged"


@pytest.mark.parametrize(
    "body",
    [
        b'{"resultSets":[],"resultSets":[]}',
        b'{"resultSets":[],"value":NaN}',
        b'{"resultSets":[],"value":Infinity}',
        b"\xff",
        b"[]",
    ],
)
def test_duplicate_nonfinite_invalid_utf8_and_nonobject_json_fail_closed(body: bytes) -> None:
    with pytest.raises(IndependentStatsValueDecoderError):
        decode_stats_value_rows(**_pins("CommonTeamYears"), parser_input=body)


def test_unbounded_number_depth_string_and_body_fail_before_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pins = _pins("CommonTeamYears")
    with pytest.raises(IndependentStatsValueDecoderError, match="unbounded integer"):
        decode_stats_value_rows(
            **pins,
            parser_input=(b'{"resultSets":[],"value":' + b"9" * 65 + b"}"),
        )

    nested: object = None
    for _ in range(decoder_module.MAX_JSON_DEPTH + 1):
        nested = [nested]
    with pytest.raises(IndependentStatsValueDecoderError, match="depth"):
        _decode("CommonTeamYears", {"resultSets": [], "nested": nested})

    monkeypatch.setattr(decoder_module, "MAX_JSON_STRING_BYTES", 2)
    with pytest.raises(IndependentStatsValueDecoderError, match="(?:key|string)"):
        _decode("CommonTeamYears", {"resultSets": [], "value": "abc"})

    monkeypatch.setattr(decoder_module, "MAX_PARSER_INPUT_BYTES", 2)
    with pytest.raises(IndependentStatsValueDecoderError, match="bytes"):
        decode_stats_value_rows(**pins, parser_input=b"{} ")


def test_foreign_endpoint_contract_and_provider_pins_fail_closed() -> None:
    payload = json.dumps(_play_by_play_payload(), separators=(",", ":")).encode()
    pins = _pins("PlayByPlayV3")
    for field in ("endpoint_contract_sha256", "provider_authority_sha256"):
        foreign = dict(pins)
        foreign[field] = "0" * 64
        with pytest.raises(IndependentStatsValueDecoderError, match="authority pin"):
            decode_stats_value_rows(**foreign, parser_input=payload)
    with pytest.raises(IndependentStatsValueDecoderError, match="absent"):
        decode_stats_value_rows(
            endpoint_id="ForeignEndpoint",
            endpoint_contract_sha256="0" * 64,
            provider_authority_sha256=pins["provider_authority_sha256"],
            parser_input=payload,
        )


def test_public_dto_rejects_bool_ordinals_and_self_resealed_digest() -> None:
    result = _decode("GravityLeaders", _gravity_payload())[0]
    with pytest.raises(IndependentStatsValueDecoderError, match="provider ordinal"):
        DecodedStatsResultV1(
            provider_ordinal=True,
            canonical_ordinal=result.canonical_ordinal,
            duplicate_name_ordinal=0,
            result_name=result.name,
            ordered_headers=result.ordered_headers,
            normalized_output_sha256=result.normalized_output_sha256,
            _canonical_rows_json=result.canonical_rows_json,
        )
    with pytest.raises(IndependentStatsValueDecoderError, match="differs"):
        DecodedStatsResultV1(
            provider_ordinal=result.provider_ordinal,
            canonical_ordinal=result.canonical_ordinal,
            duplicate_name_ordinal=0,
            result_name=result.name,
            ordered_headers=result.ordered_headers,
            normalized_output_sha256="0" * 64,
            _canonical_rows_json=result.canonical_rows_json,
        )
    empty_digest = hashlib.sha256(b'{"headers":[],"rows":[]}').hexdigest()
    with pytest.raises(IndependentStatsValueDecoderError, match="headers"):
        DecodedStatsResultV1(
            provider_ordinal=result.provider_ordinal,
            canonical_ordinal=result.canonical_ordinal,
            duplicate_name_ordinal=0,
            result_name=result.name,
            ordered_headers=(),
            normalized_output_sha256=empty_digest,
            _canonical_rows_json=b"[]",
        )


@pytest.mark.parametrize("error_key", ["Message", "message", "error"])
def test_custom_success_body_with_top_level_error_key_fails_closed(error_key: str) -> None:
    payload = _traditional_payload()
    payload[error_key] = "provider error"
    with pytest.raises(IndependentStatsValueDecoderError, match="error envelope"):
        _decode("BoxScoreTraditionalV3", payload)


def test_legacy_ambiguous_omitted_duplicate_reordered_and_width_drift_fail_closed() -> None:
    endpoint_id = "CommonTeamYears"
    payload = _legacy_payload(endpoint_id)
    with pytest.raises(IndependentStatsValueDecoderError, match="exactly one"):
        _decode(endpoint_id, {**payload, "resultSet": payload["resultSets"]})

    with pytest.raises(IndependentStatsValueDecoderError, match="denominator"):
        _decode(endpoint_id, {"resultSets": []})

    duplicated = json.loads(json.dumps(payload))
    duplicated["resultSets"].append(dict(duplicated["resultSets"][0]))
    with pytest.raises(IndependentStatsValueDecoderError, match="duplicate"):
        _decode(endpoint_id, duplicated)

    reordered = json.loads(json.dumps(payload))
    reordered["resultSets"][0]["headers"] = list(reversed(reordered["resultSets"][0]["headers"]))
    reordered["resultSets"][0]["rowSet"][0] = list(
        reversed(reordered["resultSets"][0]["rowSet"][0])
    )
    with pytest.raises(IndependentStatsValueDecoderError, match="header order"):
        _decode(endpoint_id, reordered)

    wrong_width = json.loads(json.dumps(payload))
    wrong_width["resultSets"][0]["rowSet"][0].append(None)
    with pytest.raises(IndependentStatsValueDecoderError, match="row width"):
        _decode(endpoint_id, wrong_width)


def test_custom_ambiguous_root_dynamic_order_and_incomplete_routes_fail_closed() -> None:
    play = _play_by_play_payload()
    play["resultSets"] = []
    with pytest.raises(IndependentStatsValueDecoderError, match="ambiguous"):
        _decode("PlayByPlayV3", play)

    schedule = _schedule_payload("ScheduleLeagueV2")
    root = schedule["leagueSchedule"]
    assert isinstance(root, dict)
    dates = root["gameDates"]
    assert isinstance(dates, list)
    game = dates[0]["games"][0]
    assert isinstance(game, dict)
    broadcaster = game["broadcasters"]["nationalBroadcasters"][0]
    assert isinstance(broadcaster, dict)
    first_key = next(iter(broadcaster))
    broadcaster[first_key] = broadcaster.pop(first_key)
    with pytest.raises(IndependentStatsValueDecoderError, match="dynamic game headers"):
        _decode("ScheduleLeagueV2", schedule)

    international = _schedule_payload("ScheduleLeagueV2Int")
    international_root = international["leagueSchedule"]
    assert isinstance(international_root, dict)
    international_root.pop("broadcasterList")
    with pytest.raises(IndependentStatsValueDecoderError, match="broadcasterList"):
        _decode("ScheduleLeagueV2Int", international)


def test_preallocation_and_cumulative_output_limits_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(decoder_module, "MAX_RESULT_ROWS", 1)
    with pytest.raises(IndependentStatsValueDecoderError, match="row (?:bound|budget)"):
        _decode("PlayByPlayV3", _play_by_play_payload(action_count=2))

    monkeypatch.setattr(decoder_module, "MAX_RESULT_ROWS", 1_000_000)
    monkeypatch.setattr(decoder_module, "MAX_TOTAL_OUTPUT_CELLS", 3)
    with pytest.raises(IndependentStatsValueDecoderError, match="cell budget"):
        _decode("PlayByPlayV3", _play_by_play_payload(action_count=1))


def test_source_has_no_production_adapter_staging_or_provider_parser_import() -> None:
    source = Path(decoder_module.__file__).read_text(encoding="utf-8")
    assert "nbadb.extract.nba_api_adapter" not in source
    assert "nbadb.orchestrate.staging" not in source
    assert "nba_api.stats.endpoints._parsers" not in source
