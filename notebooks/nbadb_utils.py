"""Shared utilities for nbadb companion notebooks."""
from __future__ import annotations

import atexit
from pathlib import Path

import duckdb
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
from IPython.display import HTML, display

# ---------------------------------------------------------------------------
# Color palette — canonical union of all notebook variants
# ---------------------------------------------------------------------------
COLORS = {
    "primary": "#C8102E",
    "secondary": "#1D428A",
    "accent": "#FDB927",
    "positive": "#00A651",
    "negative": "#C8102E",
    "neutral": "#999999",
    "dark": "#2D2926",
    "light": "#F5F5F0",
    "purple": "#552583",
    "teal": "#00897B",
    "orange": "#FF6B35",
    "bg": "#FAFAFA",
    # Classification-specific (draft combine)
    "bust": "#E53935",
    "rotation": "#FDD835",
    "starter": "#43A047",
    "star": "#1E88E5",
}

ARCHETYPE_COLORS = [
    COLORS["primary"],
    COLORS["secondary"],
    COLORS["accent"],
    COLORS["positive"],
    COLORS["purple"],
    COLORS["teal"],
    COLORS["orange"],
    COLORS["neutral"],
]

# ---------------------------------------------------------------------------
# Plotly template
# ---------------------------------------------------------------------------
TEMPLATE = go.layout.Template(
    layout=go.Layout(
        font=dict(family="Inter, system-ui, sans-serif", size=12, color=COLORS["dark"]),
        plot_bgcolor="white",
        paper_bgcolor=COLORS["bg"],
        colorway=[
            COLORS["primary"],
            COLORS["secondary"],
            COLORS["accent"],
            COLORS["positive"],
            COLORS["purple"],
            COLORS["teal"],
            COLORS["orange"],
        ],
        xaxis=dict(gridcolor="#E0E0E0", zerolinecolor="#E0E0E0"),
        yaxis=dict(gridcolor="#E0E0E0", zerolinecolor="#E0E0E0"),
    )
)
pio.templates["nba"] = TEMPLATE
pio.templates.default = "nba"

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------
DB_PATHS = [
    Path("/kaggle/input/basketball/nba.duckdb"),
    Path("../nbadb/nba.duckdb"),
]


def get_connection(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection with Kaggle/local path fallback.

    The connection is registered with ``atexit`` for automatic cleanup.
    Callers should **not** call ``conn.close()`` manually.
    """
    db_path = next((p for p in DB_PATHS if p.exists()), None)
    if db_path is None:
        raise FileNotFoundError(
            f"NBA database not found. Searched: {[str(p) for p in DB_PATHS]}"
        )
    conn = duckdb.connect(str(db_path), read_only=read_only)
    atexit.register(conn.close)
    print(f"Connected to {db_path}")
    return conn


# ---------------------------------------------------------------------------
# Takeaway box
# ---------------------------------------------------------------------------
def takeaway(text: str) -> None:
    """Display a styled 'Key Takeaway' box in Jupyter."""
    display(
        HTML(
            f'<div style="background:#fffbe6; border-left:4px solid {COLORS["accent"]}; '
            f"padding:12px 16px; margin:16px 0; border-radius:4px; "
            f'font-size:14px; line-height:1.5;">'
            f"<strong>Key Takeaway:</strong> {text}</div>"
        )
    )


# ---------------------------------------------------------------------------
# Court drawing — Plotly
# ---------------------------------------------------------------------------
def draw_court_plotly(
    line_color: str = "#999999", line_width: int = 1
) -> list[dict]:
    """Return Plotly shape dicts for an NBA half-court.

    Coordinate system: basket at (0, 0), court extends to y=422.5.
    Units are in 1/10th of a foot (matching NBA stats loc_x / loc_y).
    """
    shapes: list[dict] = []
    common = dict(line_color=line_color, line_width=line_width, layer="below")

    # Court outline
    shapes.append(dict(type="rect", x0=-250, y0=-47.5, x1=250, y1=422.5, **common))

    # Hoop (circle, radius 7.5)
    shapes.append(dict(type="circle", x0=-7.5, y0=-7.5, x1=7.5, y1=7.5, **common))

    # Backboard
    shapes.append(dict(type="line", x0=-30, y0=-7.5, x1=30, y1=-7.5, **common))

    # Paint / key rectangle
    shapes.append(dict(type="rect", x0=-80, y0=-47.5, x1=80, y1=142.5, **common))

    # Free throw circle (center 0, 142.5 — radius 60)
    shapes.append(dict(type="circle", x0=-60, y0=82.5, x1=60, y1=202.5, **common))

    # Restricted area arc (center 0,0 — radius 40)
    restricted_arc_x = 40 * np.cos(np.linspace(0, np.pi, 60))
    restricted_arc_y = 40 * np.sin(np.linspace(0, np.pi, 60))
    path_ra = "M " + " L ".join(
        f"{x:.1f},{y:.1f}" for x, y in zip(restricted_arc_x, restricted_arc_y, strict=True)
    )
    shapes.append(dict(type="path", path=path_ra, **common))

    # Corner three lines
    shapes.append(
        dict(type="line", x0=-220, y0=-47.5, x1=-220, y1=92.5, **common)
    )
    shapes.append(
        dict(type="line", x0=220, y0=-47.5, x1=220, y1=92.5, **common)
    )

    # Three-point arc (SVG path — radius 237.5)
    three_arc_angle = np.linspace(
        np.arccos(220 / 237.5), np.pi - np.arccos(220 / 237.5), 100
    )
    arc_x = 237.5 * np.cos(three_arc_angle)
    arc_y = 237.5 * np.sin(three_arc_angle)
    path_3pt = "M " + " L ".join(
        f"{x:.1f},{y:.1f}" for x, y in zip(arc_x, arc_y, strict=True)
    )
    shapes.append(dict(type="path", path=path_3pt, **common))

    return shapes


# ---------------------------------------------------------------------------
# Court drawing — matplotlib
# ---------------------------------------------------------------------------
def draw_court_matplotlib(ax, line_color: str = "black", line_width: int = 1):
    """Draw an NBA half-court on a matplotlib Axes.

    Requires ``matplotlib`` to be importable.
    """
    import matplotlib.patches as patches
    import matplotlib.pyplot as plt
    from matplotlib.patches import Arc

    # Court outline
    court = patches.Rectangle(
        (-250, -47.5),
        500,
        470,
        linewidth=line_width,
        edgecolor=line_color,
        facecolor="#f5f5f0",
        zorder=0,
    )
    ax.add_patch(court)

    # Hoop (circle, radius 7.5)
    hoop = plt.Circle(
        (0, 0),
        7.5,
        linewidth=line_width,
        edgecolor="orange",
        facecolor="none",
        zorder=5,
    )
    ax.add_patch(hoop)

    # Backboard
    ax.plot([-30, 30], [-7.5, -7.5], color=line_color, linewidth=line_width, zorder=5)

    # Paint rectangle
    paint = patches.Rectangle(
        (-80, -47.5),
        160,
        190,
        linewidth=line_width,
        edgecolor=line_color,
        facecolor="none",
        zorder=5,
    )
    ax.add_patch(paint)

    # Free throw circle
    ft_circle = Arc(
        (0, 142.5),
        120,
        120,
        angle=0,
        theta1=0,
        theta2=180,
        linewidth=line_width,
        edgecolor=line_color,
        zorder=5,
    )
    ax.add_patch(ft_circle)
    ft_circle_dash = Arc(
        (0, 142.5),
        120,
        120,
        angle=0,
        theta1=180,
        theta2=360,
        linewidth=line_width,
        edgecolor=line_color,
        linestyle="dashed",
        zorder=5,
    )
    ax.add_patch(ft_circle_dash)

    # Restricted area arc (radius 40)
    restricted = Arc(
        (0, 0),
        80,
        80,
        angle=0,
        theta1=0,
        theta2=180,
        linewidth=line_width,
        edgecolor=line_color,
        zorder=5,
    )
    ax.add_patch(restricted)

    # Three-point arc
    three_arc = Arc(
        (0, 0),
        475,
        475,
        angle=0,
        theta1=22,
        theta2=158,
        linewidth=line_width,
        edgecolor=line_color,
        zorder=5,
    )
    ax.add_patch(three_arc)

    # Corner three lines
    ax.plot(
        [-220, -220], [-47.5, 92.5], color=line_color, linewidth=line_width, zorder=5
    )
    ax.plot(
        [220, 220], [-47.5, 92.5], color=line_color, linewidth=line_width, zorder=5
    )


# ---------------------------------------------------------------------------
# Notebook index for cross-links
# ---------------------------------------------------------------------------
NOTEBOOK_INDEX = [
    ("Part 1", "nba_mvp_predictor", "MVP Prediction with Tracking & Synergy Data"),
    ("Part 2", "nba_player_archetypes", "Data-Driven Player Archetypes (UMAP + GMM)"),
    ("Part 3", "nba_game_prediction", "Game Outcome Prediction (Stacking Ensemble)"),
    (
        "Part 4",
        "nba_draft_combine_analysis",
        "Draft Combine to Career Prediction",
    ),
    (
        "Part 5",
        "nba_defense_decoded",
        "Defense Decoded (Tracking + Hustle + Synergy PCA)",
    ),
    ("Part 6", "nba_player_dashboard", "Interactive Player Explorer"),
    (
        "Part 7",
        "nba_shot_chart_analysis",
        "Spatial Shot Analysis & 3-Point Revolution",
    ),
    (
        "Part 8",
        "nba_player_similarity",
        "Player Similarity Engine (Cosine + Manhattan)",
    ),
    (
        "Part 9",
        "nba_aging_curves",
        "Career Trajectory & Aging Curve Modeling",
    ),
    (
        "Part 10",
        "nba_play_by_play_insights",
        "Play-by-Play: Win Probability, Runs & Clutch",
    ),
]


def render_cross_links(current: str) -> str:
    """Return a markdown table of cross-links excluding the current notebook."""
    rows = "\n".join(
        f"| {part} | [{desc}](./{nb}.ipynb) | {desc} |"
        for part, nb, desc in NOTEBOOK_INDEX
        if nb != current
    )
    return (
        f"| Part | Notebook | Description |\n|---|---|---|\n{rows}"
    )
