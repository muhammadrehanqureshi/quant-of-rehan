"""Palette and stylesheet for the desktop terminal: a restrained HUD.

Owner order 2026-11-03: JARVIS mood, trading terminal first, lightweight
always. That means a charcoal field, hairline panel borders, one restrained
accent set (green up, red risk, cyan data, amber brand) and thin arc gauges
on the Overview page. No full-screen animations, no per-frame repaints, no
decorative noise: every heuristic here is a colour or a stroke, not a timer.
"""

from __future__ import annotations

PALETTE = {
    "field": "#0A0D11",          # near black, the terminal's own field
    "panel": "#111720",          # raised panel
    "panel_edge": "#1E2833",     # hairline border
    "ink": "#E6EDF3",            # primary ink
    "dim": "#8C99A6",            # secondary ink
    "faint": "#5A6673",          # labels
    "green": "#3BB273",          # bullish
    "red": "#E05B5B",            # bearish and risk
    "cyan": "#4A9C95",           # data accents (inherited from the brand palette)
    "amber": "#D9A441",          # brand gold
    "amber_hi": "#F8CE66",
    "grid": "#16202B",           # table gridline
    "selection": "#17242F",      # selected row field
}

#: The HUD glow, as a small alpha ellipse instead of a shader: one radial
#: gradient per gauge is cheap and paints once, not on a timer.
GLOW_ALPHA = 38


def stylesheet() -> str:
    """The window's Qt stylesheet, built from the palette above."""
    p = PALETTE
    return f"""
    QMainWindow, QWidget#root {{
        background: {p['field']};
        color: {p['ink']};
    }}
    QWidget {{
        color: {p['ink']};
        font-family: "Segoe UI";
        font-size: 12px;
    }}
    QLabel#brand {{
        color: {p['amber_hi']};
        font-size: 20px;
        font-weight: 600;
        letter-spacing: 3px;
    }}
    QLabel#brandSub {{
        color: {p['faint']};
        font-size: 10px;
        letter-spacing: 2px;
    }}
    QLabel#pageTitle {{
        font-size: 16px;
        font-weight: 600;
        letter-spacing: 1px;
        color: {p['ink']};
    }}
    QLabel#sectionLabel {{
        color: {p['faint']};
        font-size: 10px;
        letter-spacing: 2px;
    }}
    QLabel#value {{
        font-size: 22px;
        font-weight: 600;
    }}
    QLabel#dim {{
        color: {p['dim']};
    }}
    QLabel#pill {{
        border: 1px solid {p['panel_edge']};
        border-radius: 10px;
        padding: 3px 10px;
        color: {p['dim']};
        background: {p['panel']};
    }}
    QLabel#pillLive {{
        border: 1px solid {p['green']};
        border-radius: 10px;
        padding: 3px 10px;
        color: {p['green']};
        background: {p['panel']};
    }}
    QLabel#pillRisk {{
        border: 1px solid {p['red']};
        border-radius: 10px;
        padding: 3px 10px;
        color: {p['red']};
        background: {p['panel']};
    }}
    QFrame#panel {{
        background: {p['panel']};
        border: 1px solid {p['panel_edge']};
        border-radius: 6px;
    }}
    QFrame#hairline {{
        background: {p['panel_edge']};
        max-height: 1px;
        border: none;
    }}
    QListWidget#nav {{
        background: {p['field']};
        border: none;
        outline: none;
        padding-top: 8px;
    }}
    QListWidget#nav::item {{
        color: {p['dim']};
        padding: 9px 14px;
        border-left: 2px solid transparent;
        letter-spacing: 1px;
    }}
    QListWidget#nav::item:selected {{
        color: {p['amber_hi']};
        background: {p['panel']};
        border-left: 2px solid {p['amber']};
    }}
    QListWidget#nav::item:hover {{
        color: {p['ink']};
    }}
    QTableWidget {{
        background: {p['panel']};
        alternate-background-color: #0E141B;
        gridline-color: {p['grid']};
        border: 1px solid {p['panel_edge']};
        border-radius: 6px;
        selection-background-color: {p['selection']};
        selection-color: {p['ink']};
    }}
    QHeaderView::section {{
        background: {p['field']};
        color: {p['faint']};
        border: none;
        border-bottom: 1px solid {p['panel_edge']};
        padding: 6px;
        font-size: 10px;
        letter-spacing: 1px;
    }}
    QLineEdit {{
        background: {p['panel']};
        border: 1px solid {p['panel_edge']};
        border-radius: 5px;
        padding: 6px 9px;
        color: {p['ink']};
    }}
    QLineEdit:focus {{
        border: 1px solid {p['cyan']};
    }}
    QPushButton {{
        background: {p['panel']};
        border: 1px solid {p['panel_edge']};
        border-radius: 5px;
        padding: 6px 14px;
        color: {p['ink']};
        letter-spacing: 1px;
    }}
    QPushButton:hover {{
        border: 1px solid {p['amber']};
        color: {p['amber_hi']};
    }}
    QStatusBar {{
        background: {p['field']};
        color: {p['faint']};
        border-top: 1px solid {p['panel_edge']};
    }}
    QCheckBox {{
        color: {p['dim']};
        spacing: 8px;
    }}
    """
