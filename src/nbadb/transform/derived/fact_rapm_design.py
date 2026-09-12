from __future__ import annotations

from typing import ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer

RAPM_DESIGN_VERSION = "rapm_long_form_v1"


class FactRapmDesignTransformer(BaseTransformer):
    """Expand exact, response-complete stints into an unfitted RAPM design.

    Each player gets one long-form row with a +1 home or -1 away indicator.
    This table deliberately contains no fitted coefficient and no regularization
    choice; downstream analysts retain authority over the model specification.
    """

    output_table: ClassVar[str] = "fact_rapm_design"
    depends_on: ClassVar[list[str]] = ["fact_lineup_stint"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        rows: list[dict[str, object]] = []
        for stint in staging["fact_lineup_stint"].collect().to_dicts():
            if (
                not stint["lineup_is_exact"]
                or not stint["response_is_complete"]
                or int(stint["source_possession_count"]) == 0
            ):
                continue
            response = stint.get("home_net_points")
            if response is None:
                continue
            player_ids_by_side = {
                side: [int(value) for value in str(stint[f"{side}_player_ids"]).split(",")]
                for side in ("home", "away")
            }
            if set(player_ids_by_side["home"]).intersection(player_ids_by_side["away"]):
                raise ValueError("fact_rapm_design: exact home and away lineups are not disjoint")
            for side, sign in (("home", 1.0), ("away", -1.0)):
                team_id = int(stint[f"{side}_team_id"])
                player_ids = player_ids_by_side[side]
                if len(player_ids) != 5 or len(set(player_ids)) != 5:
                    raise ValueError(
                        "fact_rapm_design: exact lineup payload no longer contains five players"
                    )
                for player_id in player_ids:
                    rows.append(
                        {
                            "design_row_id": f"{stint['stint_id']}:{player_id}",
                            "game_id": str(stint["game_id"]),
                            "stint_id": str(stint["stint_id"]),
                            "stint_number": int(stint["stint_number"]),
                            "player_id": player_id,
                            "team_id": team_id,
                            "team_side": side,
                            "design_value": sign,
                            "response_home_net_points": int(response),
                            "exposure_seconds": float(stint["duration_seconds"]),
                            "source_possession_count": int(stint["source_possession_count"]),
                            "first_source_action_number": int(stint["first_source_action_number"]),
                            "last_source_action_number": int(stint["last_source_action_number"]),
                            "lineup_is_exact": True,
                            "response_is_complete": True,
                            "is_ambiguous": False,
                            "ambiguity_reason": None,
                            "lineup_algorithm_version": str(stint["algorithm_version"]),
                            "design_version": RAPM_DESIGN_VERSION,
                        }
                    )
        return pl.DataFrame(rows, schema=_OUTPUT_SCHEMA, orient="row")


_OUTPUT_SCHEMA = pl.Schema(
    {
        "design_row_id": pl.String,
        "game_id": pl.String,
        "stint_id": pl.String,
        "stint_number": pl.Int64,
        "player_id": pl.Int64,
        "team_id": pl.Int64,
        "team_side": pl.String,
        "design_value": pl.Float64,
        "response_home_net_points": pl.Int64,
        "exposure_seconds": pl.Float64,
        "source_possession_count": pl.Int64,
        "first_source_action_number": pl.Int64,
        "last_source_action_number": pl.Int64,
        "lineup_is_exact": pl.Boolean,
        "response_is_complete": pl.Boolean,
        "is_ambiguous": pl.Boolean,
        "ambiguity_reason": pl.String,
        "lineup_algorithm_version": pl.String,
        "design_version": pl.String,
    }
)


__all__ = ["FactRapmDesignTransformer", "RAPM_DESIGN_VERSION"]
