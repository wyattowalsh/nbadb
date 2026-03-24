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


def game_score(
    pts: float | None,
    fgm: float | None,
    fga: float | None,
    ftm: float | None,
    fta: float | None,
    oreb: float | None,
    dreb: float | None,
    stl: float | None,
    ast: float | None,
    blk: float | None,
    pf: float | None,
    tov: float | None,
) -> float:
    """John Hollinger's Game Score: single-number game performance summary."""
    pts, fgm, fga = _f(pts), _f(fgm), _f(fga)
    ftm, fta = _f(ftm), _f(fta)
    oreb, dreb = _f(oreb), _f(dreb)
    stl, ast, blk = _f(stl), _f(ast), _f(blk)
    pf, tov = _f(pf), _f(tov)
    return (
        pts
        + 0.4 * fgm
        - 0.7 * fga
        - 0.4 * (fta - ftm)
        + 0.7 * oreb
        + 0.3 * dreb
        + stl
        + 0.7 * ast
        + 0.7 * blk
        - 0.4 * pf
        - tov
    )


def possessions(
    fga: float | None,
    fta: float | None,
    oreb: float | None,
    tov: float | None,
) -> float:
    """Estimate possessions from box score: FGA - OREB + TOV + 0.44 * FTA."""
    return _f(fga) - _f(oreb) + _f(tov) + 0.44 * _f(fta)


def per_minute(
    stat: float | None,
    minutes: float | None,
    base: float = 36,
) -> float:
    """Per-minute normalization. base=36 for per-36, base=48 for per-48."""
    stat, minutes = _f(stat), _f(minutes)
    return stat * base / minutes if minutes > 0 else 0.0


def assist_pct(
    ast: float | None,
    minutes: float | None,
    team_fgm: float | None,
    fgm: float | None,
    team_minutes: float | None,
) -> float:
    """Percentage of teammate field goals a player assisted while on floor."""
    ast, minutes = _f(ast), _f(minutes)
    team_fgm, fgm, team_minutes = _f(team_fgm), _f(fgm), _f(team_minutes)
    denom = (team_minutes / 5) * team_fgm
    if minutes == 0 or denom == 0:
        return 0.0
    adj = (minutes / (team_minutes / 5)) * team_fgm - fgm
    return 100 * ast / adj if adj > 0 else 0.0


def steal_pct(
    stl: float | None,
    minutes: float | None,
    team_poss: float | None,
    team_minutes: float | None,
) -> float:
    """Percentage of opponent possessions ending with a steal while on floor."""
    stl, minutes = _f(stl), _f(minutes)
    team_poss, team_minutes = _f(team_poss), _f(team_minutes)
    if minutes == 0 or team_poss == 0:
        return 0.0
    return 100 * (stl * (team_minutes / 5)) / (minutes * team_poss)


def block_pct(
    blk: float | None,
    minutes: float | None,
    opp_fga: float | None,
    team_minutes: float | None,
) -> float:
    """Percentage of opponent 2-point FGA blocked while on floor."""
    blk, minutes = _f(blk), _f(minutes)
    opp_fga, team_minutes = _f(opp_fga), _f(team_minutes)
    if minutes == 0 or opp_fga == 0:
        return 0.0
    return 100 * (blk * (team_minutes / 5)) / (minutes * opp_fga)


def turnover_pct(
    tov: float | None,
    fga: float | None,
    fta: float | None,
) -> float:
    """Turnover percentage: turnovers per play."""
    tov, fga, fta = _f(tov), _f(fga), _f(fta)
    denom = fga + 0.44 * fta + tov
    return 100 * tov / denom if denom > 0 else 0.0
