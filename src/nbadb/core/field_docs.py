from __future__ import annotations

import re

_CAMEL_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE_2 = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD_RE = re.compile(r"[^A-Za-z0-9]+")

_TOKEN_LABELS = {
    "id": "ID",
    "nba": "NBA",
    "wnba": "WNBA",
    "api": "API",
    "fgm": "field goals made",
    "fga": "field goals attempted",
    "fg": "field goal",
    "fg2m": "two-point field goals made",
    "fg2a": "two-point field goals attempted",
    "fg2": "two-point field goal",
    "fg3m": "three-point field goals made",
    "fg3a": "three-point field goals attempted",
    "fg3": "three-point field goal",
    "ftm": "free throws made",
    "fta": "free throws attempted",
    "ft": "free throw",
    "pct": "percentage",
    "oreb": "offensive rebounds",
    "dreb": "defensive rebounds",
    "reb": "rebounds",
    "ast": "assists",
    "stl": "steals",
    "blk": "blocks",
    "tov": "turnovers",
    "pf": "personal fouls",
    "pts": "points",
    "min": "minutes",
    "gp": "games played",
    "w": "wins",
    "l": "losses",
    "wl": "win-loss",
    "url": "URL",
    "utc": "UTC",
    "et": "ET",
    "pt": "player tracking",
    "xyz": "XYZ",
}

_FIELD_DESCRIPTIONS = {
    "game_id": "Unique NBA game identifier.",
    "gameid": "Unique NBA game identifier.",
    "team_id": "Unique NBA team identifier.",
    "teamid": "Unique NBA team identifier.",
    "player_id": "Unique NBA player identifier.",
    "person_id": "Unique NBA person identifier.",
    "personid": "Unique NBA person identifier.",
    "league_id": "NBA league identifier.",
    "season": "NBA season label.",
    "season_year": "NBA season label.",
    "season_id": "NBA season identifier.",
    "season_type": "NBA season phase, such as regular season or playoffs.",
    "game_date": "Game date.",
    "game_time": "Game time.",
    "team_name": "Team name.",
    "team_city": "Team city.",
    "team_abbreviation": "Team abbreviation.",
    "team_tricode": "Three-letter team code.",
    "player_name": "Player name.",
    "full_name": "Full name.",
    "first_name": "First name.",
    "family_name": "Family name.",
    "last_name": "Last name.",
    "jersey_num": "Jersey number.",
    "position": "Player position.",
    "minutes": "Minutes played.",
    "min": "Minutes played.",
    "fgm": "Field goals made.",
    "fga": "Field goals attempted.",
    "fg_pct": "Field goal percentage.",
    "fg2m": "Two-point field goals made.",
    "fg2a": "Two-point field goals attempted.",
    "fg2_pct": "Two-point field goal percentage.",
    "fg3m": "Three-point field goals made.",
    "fg3a": "Three-point field goals attempted.",
    "fg3_pct": "Three-point field goal percentage.",
    "ftm": "Free throws made.",
    "fta": "Free throws attempted.",
    "ft_pct": "Free throw percentage.",
    "oreb": "Offensive rebounds.",
    "dreb": "Defensive rebounds.",
    "reb": "Total rebounds.",
    "ast": "Assists.",
    "stl": "Steals.",
    "blk": "Blocks.",
    "tov": "Turnovers.",
    "pf": "Personal fouls.",
    "pts": "Points scored.",
    "plus_minus": "Point differential while the player or team was on court.",
    "rank": "Rank within the result set.",
    "gp": "Games played.",
    "w": "Wins.",
    "l": "Losses.",
    "wl_pct": "Win-loss percentage.",
    "video_available_flag": "Video availability flag.",
    "pt_available": "Player-tracking availability flag.",
    "pt_xyz_available": "Player-tracking XYZ availability flag.",
    "wh_status": "Wagering hub status flag.",
    "hustle_status": "Hustle data availability flag.",
    "historical_status": "Historical data availability flag.",
}


def _snake_name(name: str) -> str:
    interim = _CAMEL_RE_1.sub(r"\1_\2", name)
    interim = _CAMEL_RE_2.sub(r"\1_\2", interim)
    return _NON_WORD_RE.sub("_", interim).strip("_").lower()


def humanize_field_name(name: str) -> str:
    """Return a readable label for a contract or schema field name."""
    snake_name = _snake_name(name)
    if not snake_name:
        return "Value"
    if snake_name in _FIELD_DESCRIPTIONS:
        return _FIELD_DESCRIPTIONS[snake_name].removesuffix(".")
    tokens = [_TOKEN_LABELS.get(token, token) for token in snake_name.split("_") if token]
    label = " ".join(tokens).strip()
    if not label:
        return "Value"
    return label[:1].upper() + label[1:]


def generated_field_description(
    name: str,
    *,
    table_name: str | None = None,
    endpoint: str | None = None,
    result_set: str | None = None,
    json_path: str | None = None,
    tier: str | None = None,
) -> str:
    """Build a deterministic fallback description when authored metadata is absent."""
    snake_name = _snake_name(name)
    if snake_name in _FIELD_DESCRIPTIONS:
        return _FIELD_DESCRIPTIONS[snake_name]

    label = humanize_field_name(name)
    if json_path:
        return f"{label} value at {json_path} in the live NBA API payload."
    if endpoint and result_set:
        return f"{label} value from the {endpoint}.{result_set} NBA API result set."
    if endpoint:
        return f"{label} value from the {endpoint} NBA API endpoint."
    if table_name and tier:
        return f"{label} value in the {tier} table {table_name}."
    if table_name:
        return f"{label} value in {table_name}."
    return f"{label} value."


def resolved_field_description(
    explicit_description: object,
    name: str,
    *,
    table_name: str | None = None,
    endpoint: str | None = None,
    result_set: str | None = None,
    json_path: str | None = None,
    tier: str | None = None,
) -> tuple[str, str]:
    """Return a non-empty field description plus its provenance."""
    if isinstance(explicit_description, str) and explicit_description.strip():
        return explicit_description.strip(), "metadata"
    return (
        generated_field_description(
            name,
            table_name=table_name,
            endpoint=endpoint,
            result_set=result_set,
            json_path=json_path,
            tier=tier,
        ),
        "generated",
    )
