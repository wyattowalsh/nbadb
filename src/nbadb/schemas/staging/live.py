from __future__ import annotations

import datetime as dt  # noqa: TC003

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class _LiveSnapshotMetadataMixin(BaseSchema):
    snapshot_at: dt.datetime = pa.Field(metadata={"description": "UTC snapshot timestamp"})
    snapshot_date: dt.date = pa.Field(metadata={"description": "UTC snapshot date"})
    source_endpoint: str = pa.Field(metadata={"description": "Live endpoint or packet name"})
    payload_json: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Serialized raw live payload for the row"},
    )


class StagingLiveScoreBoardSchema(_LiveSnapshotMetadataMixin):
    game_id: str | None = pa.Field(nullable=True, metadata={"description": "Live game id"})
    game_status: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Live game status code"},
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Live game status label"},
    )


class StagingLiveOddsSchema(_LiveSnapshotMetadataMixin):
    game_id: str | None = pa.Field(nullable=True, metadata={"description": "Live game id"})


class StagingLivePlayByPlaySchema(_LiveSnapshotMetadataMixin):
    game_id: str | None = pa.Field(nullable=True, metadata={"description": "Live game id"})
    action_number: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Live action number within the game"},
    )
    period: int | None = pa.Field(nullable=True, metadata={"description": "Live game period"})
    clock: str | None = pa.Field(nullable=True, metadata={"description": "Live game clock"})
    team_id: int | None = pa.Field(nullable=True, metadata={"description": "Team id"})
    person_id: int | None = pa.Field(nullable=True, metadata={"description": "Person id"})
    action_type: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Live action type"},
    )
    sub_type: str | None = pa.Field(nullable=True, metadata={"description": "Live action subtype"})
    description: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Live action description"},
    )
    score_home: str | None = pa.Field(nullable=True, metadata={"description": "Home score"})
    score_away: str | None = pa.Field(nullable=True, metadata={"description": "Away score"})
    shot_result: str | None = pa.Field(nullable=True, metadata={"description": "Shot result"})
    points_total: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Points scored on the action"},
    )
    action_id: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Live action id"},
    )


class StagingLiveBoxScoreGameDetailsSchema(_LiveSnapshotMetadataMixin):
    game_id: str | None = pa.Field(nullable=True, metadata={"description": "Live game id"})
    game_status: int | None = pa.Field(
        nullable=True,
        metadata={"description": "Live game status code"},
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Live game status label"},
    )


class StagingLiveBoxScoreArenaSchema(_LiveSnapshotMetadataMixin):
    game_id: str | None = pa.Field(nullable=True, metadata={"description": "Live game id"})
    arena_name: str | None = pa.Field(nullable=True, metadata={"description": "Arena name"})


class StagingLiveBoxScoreOfficialsSchema(_LiveSnapshotMetadataMixin):
    game_id: str | None = pa.Field(nullable=True, metadata={"description": "Live game id"})
    person_id: int | None = pa.Field(nullable=True, metadata={"description": "Official person id"})


class _StagingLiveBoxScoreTeamStatsSchema(_LiveSnapshotMetadataMixin):
    game_id: str | None = pa.Field(nullable=True, metadata={"description": "Live game id"})
    team_id: int | None = pa.Field(nullable=True, metadata={"description": "Team id"})
    score: int | None = pa.Field(nullable=True, metadata={"description": "Live team score"})


class StagingLiveBoxScoreTeamStatsHomeSchema(_StagingLiveBoxScoreTeamStatsSchema):
    pass


class StagingLiveBoxScoreTeamStatsAwaySchema(_StagingLiveBoxScoreTeamStatsSchema):
    pass


class _StagingLiveBoxScorePlayerStatsSchema(_LiveSnapshotMetadataMixin):
    game_id: str | None = pa.Field(nullable=True, metadata={"description": "Live game id"})
    person_id: int | None = pa.Field(nullable=True, metadata={"description": "Player person id"})
    points: int | None = pa.Field(nullable=True, metadata={"description": "Live player points"})


class StagingLiveBoxScorePlayerStatsHomeSchema(_StagingLiveBoxScorePlayerStatsSchema):
    pass


class StagingLiveBoxScorePlayerStatsAwaySchema(_StagingLiveBoxScorePlayerStatsSchema):
    pass
