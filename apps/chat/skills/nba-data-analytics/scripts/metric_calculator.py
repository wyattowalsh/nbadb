"""Common NBA metric formulas for reference and computation.

The agent can read this file to understand how to calculate advanced metrics.
"""

from __future__ import annotations


def _f(v: float | None) -> float:
    """Coerce None to 0.0 for nullable database values."""
    return 0.0 if v is None else float(v)


def true_shooting_pct(pts: float | None, fga: float | None, fta: float | None) -> float:
    """True Shooting Percentage: pts / (2 * (fga + 0.44 * fta))."""
    pts, fga, fta = _f(pts), _f(fga), _f(fta)
    denominator = 2 * (fga + 0.44 * fta)
    return pts / denominator if denominator > 0 else 0.0


def effective_fg_pct(fgm: float | None, fg3m: float | None, fga: float | None) -> float:
    """Effective Field Goal Percentage: (fgm + 0.5 * fg3m) / fga."""
    fgm, fg3m, fga = _f(fgm), _f(fg3m), _f(fga)
    return (fgm + 0.5 * fg3m) / fga if fga > 0 else 0.0


def usage_rate(
    fga: float | None,
    fta: float | None,
    tov: float | None,
    minutes: float | None,
    team_fga: float | None,
    team_fta: float | None,
    team_tov: float | None,
    team_minutes: float | None,
) -> float:
    """Usage Rate: estimates the percentage of team possessions used by a player."""
    fga, fta, tov, minutes = _f(fga), _f(fta), _f(tov), _f(minutes)
    team_fga, team_fta = _f(team_fga), _f(team_fta)
    team_tov, team_minutes = _f(team_tov), _f(team_minutes)
    if minutes == 0 or (team_fga + 0.44 * team_fta + team_tov) == 0:
        return 0.0
    return (
        100
        * ((fga + 0.44 * fta + tov) * (team_minutes / 5))
        / (minutes * (team_fga + 0.44 * team_fta + team_tov))
    )


def pace(
    team_poss: float | None,
    opp_poss: float | None,
    team_minutes: float | None,
) -> float:
    """Pace: possessions per 48 minutes."""
    team_poss, opp_poss, team_minutes = _f(team_poss), _f(opp_poss), _f(team_minutes)
    if team_minutes == 0:
        return 0.0
    return 48 * ((team_poss + opp_poss) / (2 * (team_minutes / 5)))


def offensive_rating(pts: float | None, possessions: float | None) -> float:
    """Offensive Rating: points scored per 100 possessions."""
    pts, possessions = _f(pts), _f(possessions)
    return (pts / possessions) * 100 if possessions > 0 else 0.0


def defensive_rating(opp_pts: float | None, possessions: float | None) -> float:
    """Defensive Rating: points allowed per 100 possessions."""
    opp_pts, possessions = _f(opp_pts), _f(possessions)
    return (opp_pts / possessions) * 100 if possessions > 0 else 0.0


def net_rating(off_rating: float | None, def_rating: float | None) -> float:
    """Net Rating: offensive rating minus defensive rating."""
    return _f(off_rating) - _f(def_rating)


def assist_to_turnover(ast: float | None, tov: float | None) -> float | None:
    """Assist to Turnover Ratio. Returns None for zero turnovers."""
    ast, tov = _f(ast), _f(tov)
    return ast / tov if tov > 0 else None


def rebound_pct(
    reb: float | None,
    minutes: float | None,
    team_reb: float | None,
    opp_reb: float | None,
    team_minutes: float | None,
) -> float:
    """Rebound Percentage: player's share of available rebounds."""
    reb, minutes = _f(reb), _f(minutes)
    team_reb, opp_reb, team_minutes = _f(team_reb), _f(opp_reb), _f(team_minutes)
    if minutes == 0 or (team_reb + opp_reb) == 0:
        return 0.0
    return 100 * (reb * (team_minutes / 5)) / (minutes * (team_reb + opp_reb))
