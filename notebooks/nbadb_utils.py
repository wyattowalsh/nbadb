"""Shared utilities for nbadb companion notebooks."""

from __future__ import annotations

import atexit
import html as _html_mod
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
    "accent_viz": "#A07B00",  # Darker gold for WCAG-compliant data viz (3.94:1 on white)
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
            COLORS["accent_viz"],
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
        raise FileNotFoundError(f"NBA database not found. Searched: {[str(p) for p in DB_PATHS]}")
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
            f"<strong>Key Takeaway:</strong> {_html_mod.escape(text)}</div>"
        )
    )


# ---------------------------------------------------------------------------
# Court drawing — Plotly
# ---------------------------------------------------------------------------
def draw_court_plotly(line_color: str = "#999999", line_width: int = 1) -> list[dict]:
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
    shapes.append(dict(type="line", x0=-220, y0=-47.5, x1=-220, y1=92.5, **common))
    shapes.append(dict(type="line", x0=220, y0=-47.5, x1=220, y1=92.5, **common))

    # Three-point arc (SVG path — radius 237.5)
    three_arc_angle = np.linspace(np.arccos(220 / 237.5), np.pi - np.arccos(220 / 237.5), 100)
    arc_x = 237.5 * np.cos(three_arc_angle)
    arc_y = 237.5 * np.sin(three_arc_angle)
    path_3pt = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in zip(arc_x, arc_y, strict=True))
    shapes.append(dict(type="path", path=path_3pt, **common))

    return shapes


# ---------------------------------------------------------------------------
# Court drawing — matplotlib (sportypy)
# ---------------------------------------------------------------------------
def nba_api_to_court_coords(loc_x: np.ndarray, loc_y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Convert nba_api shot coordinates to sportypy court coordinates.

    nba_api uses 1/10th of a foot with basket at (0, 0).
    sportypy uses feet with a 90° rotation.

    Returns (x_court, y_court) in feet.
    """
    theta = 0.5 * np.pi
    x_r = (loc_x * np.cos(theta)) - (loc_y * np.sin(theta))
    y_r = (loc_x * np.sin(theta)) + (loc_y * np.cos(theta))
    return x_r / 10.0, y_r / 10.0


def draw_court_matplotlib(ax=None, display_range: str = "offense"):
    """Draw an NBA court on a matplotlib Axes using sportypy.

    Parameters
    ----------
    ax : matplotlib Axes, optional
        Target axes; creates a new figure if not provided.
    display_range : str
        Portion of court to show (``'full'``, ``'offense'``, ``'in bounds only'``).

    Returns
    -------
    matplotlib Axes with the court drawn.
    """
    from sportypy.surfaces.basketball import NBACourt

    court = NBACourt(x_trans=-41.75)
    return court.draw(ax=ax, display_range=display_range)


def shot_heatmap(
    loc_x: np.ndarray,
    loc_y: np.ndarray,
    values: np.ndarray | None = None,
    ax=None,
    display_range: str = "offense",
    cmap: str = "hot",
    alpha: float = 0.75,
    **kwargs,
):
    """Plot a shot heatmap on an NBA court using sportypy.

    Accepts raw nba_api coordinates (1/10th ft) — coordinate
    conversion is handled automatically.

    Parameters
    ----------
    loc_x, loc_y : array-like
        Shot coordinates from nba_api (LOC_X, LOC_Y).
    values : array-like, optional
        Values for coloring (e.g., 1=made, 0=missed for FG%).
    ax : matplotlib Axes, optional
        Target axes.
    display_range : str
        Court display range.
    cmap : str
        Matplotlib colormap name.
    alpha : float
        Heatmap transparency.
    **kwargs
        Additional keyword arguments passed to ``NBACourt.heatmap()``.
    """
    import matplotlib.pyplot as plt
    from sportypy.surfaces.basketball import NBACourt

    if ax is None:
        _, ax = plt.subplots(1, 1, figsize=(12, 11))

    court = NBACourt(x_trans=-41.75)
    court.draw(ax=ax, display_range=display_range)

    x_court, y_court = nba_api_to_court_coords(
        np.asarray(loc_x, dtype=float),
        np.asarray(loc_y, dtype=float),
    )

    court.heatmap(x_court, y_court, values=values, ax=ax, cmap=cmap, alpha=alpha, **kwargs)
    return ax


def shot_scatter(
    loc_x: np.ndarray,
    loc_y: np.ndarray,
    ax=None,
    display_range: str = "offense",
    **kwargs,
):
    """Plot shot locations as a scatter plot on an NBA court using sportypy.

    Accepts raw nba_api coordinates (1/10th ft).

    Parameters
    ----------
    loc_x, loc_y : array-like
        Shot coordinates from nba_api (LOC_X, LOC_Y).
    ax : matplotlib Axes, optional
        Target axes.
    display_range : str
        Court display range.
    **kwargs
        Additional keyword arguments passed to ``NBACourt.scatter()``.
    """
    import matplotlib.pyplot as plt
    from sportypy.surfaces.basketball import NBACourt

    if ax is None:
        _, ax = plt.subplots(1, 1, figsize=(12, 11))

    court = NBACourt(x_trans=-41.75)
    court.draw(ax=ax, display_range=display_range)

    x_court, y_court = nba_api_to_court_coords(
        np.asarray(loc_x, dtype=float),
        np.asarray(loc_y, dtype=float),
    )

    court.scatter(x_court, y_court, ax=ax, **kwargs)
    return ax


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
    (
        "Part 11",
        "nba_chat_with_data",
        "Chat with Data: AI-Powered NBA Analytics (Chainlit)",
    ),
]


def render_cross_links(current: str) -> str:
    """Return a markdown table of cross-links excluding the current notebook."""
    rows = "\n".join(
        f"| {part} | [{desc}](./{nb}.ipynb) | {desc} |"
        for part, nb, desc in NOTEBOOK_INDEX
        if nb != current
    )
    return f"| Part | Notebook | Description |\n|---|---|---|\n{rows}"


# ---------------------------------------------------------------------------
# Great Tables — publication-quality styled tables
# ---------------------------------------------------------------------------
def styled_table(
    df,
    title: str = "",
    subtitle: str = "",
    source_note: str = "",
):
    """Create a publication-quality NBA-themed table with Great Tables.

    Parameters
    ----------
    df : polars.DataFrame or pandas.DataFrame
        Data to display.
    title : str
        Table title.
    subtitle : str
        Table subtitle.
    source_note : str
        Footnote/source attribution.

    Returns
    -------
    great_tables.GT
        Styled GT object (renders as HTML in Jupyter).
    """
    from great_tables import GT, loc, style

    gt = GT(df)

    if title:
        gt = gt.tab_header(title=title, subtitle=subtitle or None)

    if source_note:
        gt = gt.tab_source_note(source_note)

    gt = gt.tab_options(
        heading_background_color=COLORS["secondary"],
        heading_title_font_size="16px",
        column_labels_background_color=COLORS["dark"],
        column_labels_font_weight="bold",
        table_font_names="Inter, system-ui, sans-serif",
        table_font_size="13px",
    ).tab_style(
        style=style.text(color="white"),
        locations=loc.column_labels(),
    )

    return gt


# ---------------------------------------------------------------------------
# itables — interactive DataTables in Jupyter
# ---------------------------------------------------------------------------
def interactive_table(df, page_length: int = 25, **kwargs):
    """Display an interactive searchable/sortable table in Jupyter.

    Parameters
    ----------
    df : polars.DataFrame or pandas.DataFrame
        Data to display.
    page_length : int
        Rows per page (default 25).
    **kwargs
        Additional keyword arguments passed to ``itables.show()``.
    """
    import itables

    itables.show(
        df,
        pageLength=page_length,
        scrollX=True,
        **kwargs,
    )
