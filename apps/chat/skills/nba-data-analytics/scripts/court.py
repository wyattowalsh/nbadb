"""NBA court visualization helpers for shot charts and zone analysis.

Usage in run_python::

    from court import draw_court, shot_chart, shot_heatmap, zone_chart, compare_shots
"""

from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Arc, Circle, Rectangle

# ------------------------------------------------------------------
# Court dimensions (NBA coordinates: 1/10th of a foot)
# ------------------------------------------------------------------

COURT_WIDTH = 500  # -250 to 250
COURT_HEIGHT = 470  # -50 to 420
HOOP_X, HOOP_Y = 0, 0
THREE_PT_RADIUS = 237.5
THREE_PT_CORNER_Y = 87.5  # where corner 3 meets arc
PAINT_WIDTH = 160
PAINT_HEIGHT = 190
FT_CIRCLE_RADIUS = 60
RESTRICTED_RADIUS = 40
BACKBOARD_WIDTH = 60
HOOP_RADIUS = 7.5

_BG_COLOR = "#141a2e"

# Zone centroid lookup for zone_chart ---------------------------------

_ZONE_CENTROIDS: dict[tuple[str, str], tuple[float, float]] = {
    ("Restricted Area", ""): (0, 25),
    ("In The Paint (Non-RA)", "Center(C)"): (0, 100),
    ("In The Paint (Non-RA)", "Left Side(L)"): (-70, 100),
    ("In The Paint (Non-RA)", "Right Side(R)"): (70, 100),
    ("Mid-Range", "Center(C)"): (0, 180),
    ("Mid-Range", "Left Side Center(LC)"): (-120, 180),
    ("Mid-Range", "Right Side Center(RC)"): (120, 180),
    ("Mid-Range", "Left Side(L)"): (-170, 100),
    ("Mid-Range", "Right Side(R)"): (170, 100),
    ("Left Corner 3", ""): (-220, 30),
    ("Right Corner 3", ""): (220, 30),
    ("Above the Break 3", "Center(C)"): (0, 300),
    ("Above the Break 3", "Left Side Center(LC)"): (-150, 280),
    ("Above the Break 3", "Right Side Center(RC)"): (150, 280),
    ("Above the Break 3", "Left Side(L)"): (-200, 200),
    ("Above the Break 3", "Right Side(R)"): (200, 200),
    ("Backcourt", ""): (0, 400),
}


# ------------------------------------------------------------------
# draw_court
# ------------------------------------------------------------------


def draw_court(
    ax: plt.Axes | None = None,
    color: str = "white",
    lw: float = 1.5,
    outer_lines: bool = False,
) -> plt.Axes:
    """Draw an NBA half-court on *ax* and return it.

    Parameters
    ----------
    ax : matplotlib Axes, optional
        Axes to draw on.  When *None* a new figure (12 x 11) is created
        with a dark background.
    color : str
        Line / element colour.
    lw : float
        Line width.
    outer_lines : bool
        If *True*, draw the outer boundary rectangle.
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 11))
        fig.set_facecolor(_BG_COLOR)
        ax.set_facecolor(_BG_COLOR)

    # Hoop
    hoop = Circle(
        (HOOP_X, HOOP_Y),
        radius=HOOP_RADIUS,
        linewidth=lw,
        color=color,
        fill=False,
        zorder=5,
    )
    ax.add_patch(hoop)

    # Backboard
    backboard = Line2D(
        [-BACKBOARD_WIDTH / 2, BACKBOARD_WIDTH / 2],
        [-7.5, -7.5],
        linewidth=lw,
        color=color,
        zorder=5,
    )
    ax.add_line(backboard)

    # Paint (outer box)
    paint = Rectangle(
        (-PAINT_WIDTH / 2, -47.5),
        PAINT_WIDTH,
        PAINT_HEIGHT,
        linewidth=lw,
        edgecolor=color,
        facecolor="none",
        zorder=3,
    )
    ax.add_patch(paint)

    # Free-throw circle (upper half — visible)
    ft_arc_upper = Arc(
        (0, PAINT_HEIGHT - 47.5),
        FT_CIRCLE_RADIUS * 2,
        FT_CIRCLE_RADIUS * 2,
        theta1=0,
        theta2=180,
        linewidth=lw,
        color=color,
        zorder=3,
    )
    ax.add_patch(ft_arc_upper)

    # Free-throw circle (lower half — dashed)
    ft_arc_lower = Arc(
        (0, PAINT_HEIGHT - 47.5),
        FT_CIRCLE_RADIUS * 2,
        FT_CIRCLE_RADIUS * 2,
        theta1=180,
        theta2=360,
        linewidth=lw,
        color=color,
        linestyle="dashed",
        zorder=3,
    )
    ax.add_patch(ft_arc_lower)

    # Restricted area arc
    restricted = Arc(
        (0, 0),
        RESTRICTED_RADIUS * 2,
        RESTRICTED_RADIUS * 2,
        theta1=0,
        theta2=180,
        linewidth=lw,
        color=color,
        zorder=3,
    )
    ax.add_patch(restricted)

    # Three-point arc
    three_arc = Arc(
        (0, 0),
        THREE_PT_RADIUS * 2,
        THREE_PT_RADIUS * 2,
        theta1=22,
        theta2=158,
        linewidth=lw,
        color=color,
        zorder=3,
    )
    ax.add_patch(three_arc)

    # Three-point corner lines
    ax.add_line(
        Line2D(
            [-220, -220],
            [-47.5, THREE_PT_CORNER_Y],
            linewidth=lw,
            color=color,
            zorder=3,
        )
    )
    ax.add_line(
        Line2D(
            [220, 220],
            [-47.5, THREE_PT_CORNER_Y],
            linewidth=lw,
            color=color,
            zorder=3,
        )
    )

    # Center court arc (half-moon at y=420)
    center_arc = Arc(
        (0, 420),
        FT_CIRCLE_RADIUS * 2,
        FT_CIRCLE_RADIUS * 2,
        theta1=180,
        theta2=360,
        linewidth=lw,
        color=color,
        zorder=3,
    )
    ax.add_patch(center_arc)

    # Half-court line
    ax.add_line(
        Line2D(
            [-250, 250],
            [420, 420],
            linewidth=lw,
            color=color,
            zorder=3,
        )
    )

    # Outer boundary
    if outer_lines:
        boundary = Rectangle(
            (-250, -47.5),
            COURT_WIDTH,
            COURT_HEIGHT - 2.5,
            linewidth=lw,
            edgecolor=color,
            facecolor="none",
            zorder=3,
        )
        ax.add_patch(boundary)

    # Axes configuration
    ax.set_xlim(-250, 250)
    ax.set_ylim(-50, 420)
    ax.set_aspect("equal")
    ax.axis("off")

    return ax


# ------------------------------------------------------------------
# shot_chart
# ------------------------------------------------------------------


def shot_chart(
    df: Any,
    x_col: str = "loc_x",
    y_col: str = "loc_y",
    made_col: str = "shot_made_flag",
    title: str = "",
    ax: plt.Axes | None = None,
) -> plt.Figure:
    """Scatter plot of made/missed shots on an NBA court.

    Parameters
    ----------
    df : DataFrame
        Must contain *x_col*, *y_col*, and *made_col* columns.
    title : str
        Chart title.
    ax : matplotlib Axes, optional
        Axes to draw on.
    """
    ax = draw_court(ax)
    fig = ax.get_figure()

    if len(df) > 0:
        made = df[df[made_col] == 1]
        missed = df[df[made_col] == 0]

        ax.scatter(
            made[x_col],
            made[y_col],
            c="green",
            marker="o",
            s=15,
            alpha=0.6,
            label="Made",
            zorder=10,
        )
        ax.scatter(
            missed[x_col],
            missed[y_col],
            c="red",
            marker="x",
            s=15,
            alpha=0.4,
            label="Missed",
            zorder=10,
        )

    if title:
        ax.set_title(title, fontsize=16, color="white", pad=10)

    ax.legend(
        loc="upper right",
        fontsize=9,
        facecolor=_BG_COLOR,
        edgecolor="white",
        labelcolor="white",
    )

    plt.show()
    return fig


# ------------------------------------------------------------------
# shot_heatmap
# ------------------------------------------------------------------


def shot_heatmap(
    df: Any,
    x_col: str = "loc_x",
    y_col: str = "loc_y",
    title: str = "",
    bins: int = 25,
    ax: plt.Axes | None = None,
) -> plt.Figure:
    """Hexbin heatmap of shot density on an NBA court.

    Parameters
    ----------
    df : DataFrame
        Must contain *x_col* and *y_col* columns.
    bins : int
        Hex grid size (passed to *gridsize*).
    """
    ax = draw_court(ax)
    fig = ax.get_figure()

    if len(df) > 0:
        hb = ax.hexbin(
            df[x_col],
            df[y_col],
            gridsize=bins,
            cmap="YlOrRd",
            mincnt=1,
            alpha=0.7,
            zorder=2,
        )
        fig.colorbar(hb, ax=ax, shrink=0.6, label="Shot count")

    if title:
        ax.set_title(title, fontsize=16, color="white", pad=10)

    plt.show()
    return fig


# ------------------------------------------------------------------
# zone_chart
# ------------------------------------------------------------------


def zone_chart(
    df: Any,
    zone_col: str = "zone_basic",
    area_col: str = "zone_area",
    fg_pct_col: str = "fg_pct",
    league_avg_col: str = "league_avg_fg_pct",
    title: str = "",
) -> plt.Figure:
    """Zone-based shooting chart coloured by FG% relative to league average.

    Parameters
    ----------
    df : DataFrame
        One row per zone.  Must contain *zone_col*, *area_col*,
        *fg_pct_col*, and *league_avg_col*.
    """
    ax = draw_court()
    fig = ax.get_figure()

    if len(df) > 0:
        for _, row in df.iterrows():
            zone_key = (str(row[zone_col]), str(row[area_col]))
            centroid = _ZONE_CENTROIDS.get(zone_key)
            if centroid is None:
                continue

            x, y = centroid
            fg_pct = float(row[fg_pct_col])
            league_avg = float(row[league_avg_col])

            colour = "#2ecc71" if fg_pct >= league_avg else "#e74c3c"

            # Circle size proportional to attempts (if column present), else fixed
            radius = 25

            circle = Circle(
                (x, y),
                radius=radius,
                facecolor=colour,
                edgecolor="white",
                linewidth=1,
                alpha=0.75,
                zorder=10,
            )
            ax.add_patch(circle)

            # Label with FG%
            ax.text(
                x,
                y,
                f"{fg_pct:.1%}" if fg_pct <= 1 else f"{fg_pct:.1f}%",
                ha="center",
                va="center",
                fontsize=7,
                fontweight="bold",
                color="white",
                zorder=11,
            )

    if title:
        ax.set_title(title, fontsize=16, color="white", pad=10)

    plt.show()
    return fig


# ------------------------------------------------------------------
# compare_shots
# ------------------------------------------------------------------


def compare_shots(
    df1: Any,
    df2: Any,
    name1: str = "Player 1",
    name2: str = "Player 2",
    x_col: str = "loc_x",
    y_col: str = "loc_y",
    title: str = "",
    bins: int = 25,
) -> plt.Figure:
    """Side-by-side heatmap comparison of two players' shot distributions.

    Parameters
    ----------
    df1, df2 : DataFrame
        Shot data for each player.
    name1, name2 : str
        Labels for each subplot.
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 11))
    fig.set_facecolor(_BG_COLOR)

    for ax, df, name in [(ax1, df1, name1), (ax2, df2, name2)]:
        draw_court(ax)
        if len(df) > 0:
            hb = ax.hexbin(
                df[x_col],
                df[y_col],
                gridsize=bins,
                cmap="YlOrRd",
                mincnt=1,
                alpha=0.7,
                zorder=2,
            )
            fig.colorbar(hb, ax=ax, shrink=0.6, label="Shot count")
        ax.set_title(name, fontsize=14, color="white", pad=10)

    if title:
        fig.suptitle(title, fontsize=18, color="white", y=0.98)

    plt.show()
    return fig
