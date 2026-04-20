from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from nbadb.core.config import NbaDbSettings
from nbadb.orchestrate.live_snapshot import LiveSnapshotWarehouse


class _FakeDataSet:
    def __init__(self, data):
        self._data = data

    def get_dict(self):
        return self._data


class _FakeScoreBoard:
    def __init__(self, **kwargs):
        self.games = _FakeDataSet(
            [
                {"gameId": "001", "gameStatus": 2, "gameStatusText": "Q4"},
            ]
        )


class _FakeOdds:
    def __init__(self, **kwargs):
        self.games = _FakeDataSet([{"gameId": "001", "markets": []}])


class _UnexpectedOdds:
    def __init__(self, **kwargs):
        raise AssertionError("odds should not be fetched when no live games are active")


class _FakePlayByPlay:
    def __init__(self, **kwargs):
        self.actions = _FakeDataSet(
            [
                {
                    "actionNumber": 1,
                    "period": 4,
                    "clock": "PT01M00.00S",
                    "teamId": 1610612738,
                    "personId": 1,
                    "actionType": "shot",
                    "description": "Player makes jumper",
                    "pointsTotal": 2,
                    "actionId": 1001,
                }
            ]
        )


class _FakeBoxScore:
    def __init__(self, **kwargs):
        self.game_details = _FakeDataSet(
            {
                "gameId": kwargs["game_id"],
                "gameStatus": 2,
                "gameStatusText": "Q4",
            }
        )
        self.arena = _FakeDataSet({"arenaName": "Garden"})
        self.officials = _FakeDataSet([{"personId": 99}])
        self.home_team_stats = _FakeDataSet({"teamId": 1610612738, "score": 110})
        self.away_team_stats = _FakeDataSet({"teamId": 1610612737, "score": 108})
        self.home_team_player_stats = _FakeDataSet([{"personId": 1, "points": 20}])
        self.away_team_player_stats = _FakeDataSet([{"personId": 2, "points": 18}])


class _FakeFinalScoreBoard:
    def __init__(self, **kwargs):
        self.games = _FakeDataSet(
            [
                {"gameId": "001", "gameStatus": 3, "gameStatusText": "Final"},
            ]
        )


def test_live_snapshot_warehouse_appends_staging_and_star_tables(tmp_path) -> None:
    settings = NbaDbSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        formats=["duckdb"],
        sqlite_path=tmp_path / "data" / "live.sqlite",
        duckdb_path=tmp_path / "data" / "live.duckdb",
    )
    warehouse = LiveSnapshotWarehouse(settings=settings)

    first_snapshot = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
    second_snapshot = datetime(2026, 4, 17, 12, 5, tzinfo=UTC)

    with (
        patch("nbadb.extract.live.endpoints.ScoreBoard", _FakeScoreBoard),
        patch("nbadb.extract.live.endpoints.Odds", _FakeOdds),
        patch("nbadb.extract.live.endpoints.PlayByPlay", _FakePlayByPlay),
        patch("nbadb.extract.live.endpoints.BoxScore", _FakeBoxScore),
    ):
        first_result = warehouse.run(game_ids=["001"], snapshot_at=first_snapshot)
        second_result = warehouse.run(game_ids=["001"], snapshot_at=second_snapshot)

    assert first_result.game_ids == ["001"]
    assert first_result.staging_tables_persisted == 10
    assert first_result.star_tables_loaded == 8
    assert second_result.staging_tables_persisted == 10
    assert second_result.star_tables_loaded == 8

    import duckdb

    conn = duckdb.connect(str(settings.duckdb_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM stg_live_score_board").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM stg_live_play_by_play").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM fact_live_score_board").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM fact_live_odds").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM fact_live_play_by_play").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM fact_live_box_score_game").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM fact_live_box_score_arena").fetchone()[0] == 2
        assert (
            conn.execute("SELECT COUNT(*) FROM bridge_live_box_score_official").fetchone()[0] == 2
        )
        assert conn.execute("SELECT COUNT(*) FROM fact_live_box_score_team").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM fact_live_box_score_player").fetchone()[0] == 4
        snapshot_values = conn.execute(
            "SELECT DISTINCT snapshot_at FROM fact_live_score_board ORDER BY snapshot_at"
        ).fetchall()
    finally:
        conn.close()

    assert [row[0] for row in snapshot_values] == [
        first_snapshot.replace(tzinfo=None),
        second_snapshot.replace(tzinfo=None),
    ]


def test_live_snapshot_warehouse_noops_when_no_active_games(tmp_path) -> None:
    settings = NbaDbSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        formats=["duckdb"],
        sqlite_path=tmp_path / "data" / "live.sqlite",
        duckdb_path=tmp_path / "data" / "live.duckdb",
    )
    warehouse = LiveSnapshotWarehouse(settings=settings)

    with (
        patch("nbadb.extract.live.endpoints.ScoreBoard", _FakeFinalScoreBoard),
        patch("nbadb.extract.live.endpoints.Odds", _UnexpectedOdds),
    ):
        result = warehouse.run(snapshot_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC))

    assert result.game_ids == []
    assert result.staging_tables_persisted == 0
    assert result.star_tables_loaded == 0
    assert result.staging_rows_persisted == 0
    assert result.star_rows_loaded == 0
