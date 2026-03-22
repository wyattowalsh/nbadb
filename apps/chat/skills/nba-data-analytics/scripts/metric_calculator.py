"""Common NBA metric formulas for reference and computation.

The agent can read this file to understand how to calculate advanced metrics.
"""

from __future__ import annotations


def true_shooting_pct(pts: float, fga: float, fta: float) -> float:
    """True Shooting Percentage: pts / (2 * (fga + 0.44 * fta))."""
    denominator = 2 * (fga + 0.44 * fta)
    return pts / denominator if denominator > 0 else 0.0


def effective_fg_pct(fgm: float, fg3m: float, fga: float) -> float:
    """Effective Field Goal Percentage: (fgm + 0.5 * fg3m) / fga."""
    return (fgm + 0.5 * fg3m) / fga if fga > 0 else 0.0


def usage_rate(
    fga: float,
    fta: float,
    tov: float,
    minutes: float,
    team_fga: float,
    team_fta: float,
    team_tov: float,
    team_minutes: float,
) -> float:
    """Usage Rate: estimates the percentage of team possessions used by a player."""
    if minutes == 0 or (team_fga + 0.44 * team_fta + team_tov) == 0:
        return 0.0
    return 100 * (
        (fga + 0.44 * fta + tov) * (team_minutes / 5)
    ) / (minutes * (team_fga + 0.44 * team_fta + team_tov))


def pace(
    team_poss: float,
    opp_poss: float,
    team_minutes: float,
) -> float:
    """Pace: possessions per 48 minutes."""
    if team_minutes == 0:
        return 0.0
    return 48 * ((team_poss + opp_poss) / (2 * (team_minutes / 5)))


def offensive_rating(pts: float, possessions: float) -> float:
    """Offensive Rating: points scored per 100 possessions."""
    return (pts / possessions) * 100 if possessions > 0 else 0.0


def defensive_rating(opp_pts: float, possessions: float) -> float:
    """Defensive Rating: points allowed per 100 possessions."""
    return (opp_pts / possessions) * 100 if possessions > 0 else 0.0


def net_rating(off_rating: float, def_rating: float) -> float:
    """Net Rating: offensive rating minus defensive rating."""
    return off_rating - def_rating


def assist_to_turnover(ast: float, tov: float) -> float:
    """Assist to Turnover Ratio."""
    return ast / tov if tov > 0 else float("inf")


def rebound_pct(
    reb: float,
    minutes: float,
    team_reb: float,
    opp_reb: float,
    team_minutes: float,
) -> float:
    """Rebound Percentage: player's share of available rebounds."""
    if minutes == 0 or (team_reb + opp_reb) == 0:
        return 0.0
    return 100 * (reb * (team_minutes / 5)) / (minutes * (team_reb + opp_reb))
