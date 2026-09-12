"""Lossless wide landing contracts for distinct legacy provider surfaces.

The pinned ``nba_api`` contract declares these physical classes separately from
their newer counterparts.  Their headers are not type annotated upstream, so
this tier deliberately validates exact ordered column presence without coercing
provider values.  Bronze remains the byte authority; these schemas make every
declared result set queryable without guessing types or projecting it through a
different endpoint version.
"""

from __future__ import annotations

import re
from typing import ClassVar

import pandera.polars as pa

from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
from nbadb.schemas.base import BaseSchema

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
_UPPER_TOKEN_RE = re.compile(r"^[A-Z0-9_]+$")


def _to_snake_case(name: str) -> str:
    # Keep this deterministic rule aligned with the extraction boundary: NBA
    # stat tokens such as FG3M and PTS_2ND_CHANCE are already word-delimited.
    if _UPPER_TOKEN_RE.fullmatch(name):
        return name.lower()
    return _CAMEL_RE.sub(r"\1_\2", name).lower()


class _PinnedLegacyResultSetSchema(BaseSchema):
    """Build a non-coercing schema from the checked-in exact-pin authority."""

    runtime_class_name: ClassVar[str]
    result_set_name: ClassVar[str]

    @classmethod
    def to_schema(cls) -> pa.DataFrameSchema:
        from nbadb.extract.base import _canonicalize_endpoint_column_name

        contract = pinned_runtime_contracts().get(cls.runtime_class_name)
        if contract is None:
            raise ValueError("legacy staging schema endpoint is absent from pinned authority")
        matches = tuple(
            result_set
            for result_set in contract.result_sets
            if result_set.result_set_name == cls.result_set_name
        )
        if len(matches) != 1:
            raise ValueError("legacy staging schema result set is not uniquely pinned")

        result_set = matches[0]
        normalized = tuple(
            _canonicalize_endpoint_column_name(
                cls.runtime_class_name,
                result_set.result_set_index,
                column,
            )
            for column in result_set.expected_columns
        )
        if len(set(normalized)) != len(normalized):
            raise ValueError("legacy provider headers collide after snake-case normalization")

        return pa.DataFrameSchema(
            {
                normalized_name: pa.Column(
                    dtype=None,
                    nullable=True,
                    required=True,
                    metadata={
                        "source": (
                            f"{cls.runtime_class_name}.{cls.result_set_name}.{provider_name}"
                        ),
                        "description": "Exact non-coercing legacy provider landing field",
                    },
                )
                for provider_name, normalized_name in zip(
                    result_set.expected_columns, normalized, strict=True
                )
            },
            coerce=False,
            strict=False,
            ordered=True,
            name=cls.__name__,
        )


class StagingBoxScoreTraditionalV2PlayerSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreTraditionalV2"
    result_set_name = "PlayerStats"


class StagingBoxScoreTraditionalV2StarterBenchSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreTraditionalV2"
    result_set_name = "TeamStarterBenchStats"


class StagingBoxScoreTraditionalV2TeamSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreTraditionalV2"
    result_set_name = "TeamStats"


class StagingBoxScoreAdvancedV2PlayerSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreAdvancedV2"
    result_set_name = "PlayerStats"


class StagingBoxScoreAdvancedV2TeamSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreAdvancedV2"
    result_set_name = "TeamStats"


class StagingBoxScoreMiscV2PlayerSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreMiscV2"
    result_set_name = "sqlPlayersMisc"


class StagingBoxScoreMiscV2TeamSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreMiscV2"
    result_set_name = "sqlTeamsMisc"


class StagingBoxScoreScoringV2PlayerSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreScoringV2"
    result_set_name = "sqlPlayersScoring"


class StagingBoxScoreScoringV2TeamSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreScoringV2"
    result_set_name = "sqlTeamsScoring"


class StagingBoxScoreUsageV2PlayerSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreUsageV2"
    result_set_name = "sqlPlayersUsage"


class StagingBoxScoreUsageV2TeamSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreUsageV2"
    result_set_name = "sqlTeamsUsage"


class StagingBoxScoreFourFactorsV2PlayerSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreFourFactorsV2"
    result_set_name = "sqlPlayersFourFactors"


class StagingBoxScoreFourFactorsV2TeamSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "BoxScoreFourFactorsV2"
    result_set_name = "sqlTeamsFourFactors"


class StagingPlayByPlayLegacyVideoAvailableSchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "PlayByPlay"
    result_set_name = "AvailableVideo"


class StagingPlayByPlayLegacySchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "PlayByPlay"
    result_set_name = "PlayByPlay"


class StagingLeagueStandingsLegacySchema(_PinnedLegacyResultSetSchema):
    runtime_class_name = "LeagueStandings"
    result_set_name = "Standings"
