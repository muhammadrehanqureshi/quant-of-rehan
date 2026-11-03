"""Palette and stylesheet for the desktop terminal.

Owner order 2026-11-03: the terminal reads like the Quant of Rehan HUD he
already runs on the phone and the console: a near-black field, cyan bracket
boards, gold brand, white data in a monospaced face, green up and red down.
Flat surfaces, one-pixel borders, no rounded pills, no arc gauges. Every
rule here is a colour or a border, never a timer.
"""

from __future__ import annotations

MONO_STACK = '"Cascadia Mono", Consolas, "Courier New", monospace'
UI_STACK = '"Segoe UI", sans-serif'

PALETTE = {
    "field": "#04080C",          # window field
    "panel": "#081018",          # raised board
    "panel_edge": "#123A4A",     # cyan-black board border
    "edge_soft": "#0D2430",      # subdued border
    "header": "#060D13",         # top bar
    "ink": "#D9ECF2",            # primary text
    "bright": "#F2FBFD",         # the number itself
    "dim": "#7FA3B0",            # secondary text
    "faint": "#4E6E7A",          # labels
    "cyan": "#2BB8D9",           # HUD structure
    "cyan_hi": "#67DEED",        # HUD captions
    "green": "#2ECC71",
    "green_field": "#0D3A26",
    "red": "#E5484D",
    "red_field": "#3A1416",
    "gold": "#E0A93E",           # brand
    "gold_hi": "#F5C25B",
    "amber_hi": "#F5A623",       # lag warning
    "grid": "#0C1B24",           # table gridline
    "selection": "#0E2630",
}


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
        font-family: {UI_STACK};
        font-size: 12px;
    }}
    QLabel {{
        background: transparent;
    }}
    /* ---------------------------------------------------------- top bar */
    QFrame#topbar {{
        background: {p['header']};
        border-bottom: 1px solid {p['panel_edge']};
    }}
    QLabel#brand {{
        color: {p['gold_hi']};
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 6px;
        background: transparent;
    }}
    QLabel#brandSub {{
        color: {p['cyan']};
        font-size: 9px;
        letter-spacing: 2px;
        background: transparent;
    }}
    QLabel#clock {{
        color: {p['dim']};
        font-family: {MONO_STACK};
        font-size: 12px;
        background: transparent;
    }}
    QLabel#chip {{
        background: {p['panel']};
        border: 1px solid {p['edge_soft']};
        padding: 2px 10px;
        color: {p['dim']};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QLabel#chipLive {{
        background: {p['green_field']};
        border: 1px solid {p['green']};
        padding: 2px 10px;
        color: {p['green']};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QLabel#chipCyan {{
        background: {p['panel']};
        border: 1px solid {p['cyan']};
        padding: 2px 10px;
        color: {p['cyan_hi']};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QLabel#chipWarn {{
        background: {p['panel']};
        border: 1px solid {p['amber_hi']};
        padding: 2px 10px;
        color: {p['amber_hi']};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QLabel#chipRisk {{
        background: {p['red_field']};
        border: 1px solid {p['red']};
        padding: 2px 10px;
        color: {p['red']};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QProgressBar#sessionbar {{
        background: {p['header']};
        border: none;
        border-top: 1px solid {p['edge_soft']};
        max-height: 3px;
    }}
    QProgressBar#sessionbar::chunk {{
        background: {p['cyan']};
    }}
    /* ------------------------------------------------------------ pages */
    QLabel#pageTitle {{
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 3px;
        color: {p['cyan_hi']};
    }}
    QLabel#sectionLabel {{
        color: {p['cyan']};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 2px;
    }}
    QLabel#stat {{
        font-family: {MONO_STACK};
        font-size: 22px;
        font-weight: 600;
        color: {p['bright']};
    }}
    QLabel#statSmall {{
        font-family: {MONO_STACK};
        font-size: 14px;
        font-weight: 600;
        color: {p['bright']};
    }}
    QLabel#note {{
        color: {p['dim']};
        font-size: 11px;
    }}
    QLabel#valueMono {{
        font-family: {MONO_STACK};
        color: {p['bright']};
        font-size: 13px;
    }}
    QLabel#levelState {{
        font-family: {MONO_STACK};
        font-size: 28px;
        font-weight: 700;
        letter-spacing: 2px;
    }}
    QFrame#panel, QFrame#panel2 {{
        background: {p['panel']};
        border: 1px solid {p['edge_soft']};
        border-radius: 0px;
    }}
    QFrame#board {{
        background: {p['panel']};
        border: 1px solid {p['panel_edge']};
        border-radius: 0px;
    }}
    QFrame#boardCore {{
        background: {p['header']};
        border: 1px solid {p['panel_edge']};
        border-radius: 0px;
    }}
    /* -------------------------------------------------------------- nav */
    QListWidget#nav {{
        background: {p['field']};
        border-right: 1px solid {p['edge_soft']};
        border-top: none;
        border-bottom: none;
        border-left: none;
        outline: none;
        padding-top: 6px;
        font-size: 12px;
    }}
    QListWidget#nav::item {{
        color: {p['dim']};
        padding: 10px 16px;
        border-left: 2px solid transparent;
    }}
    QListWidget#nav::item:selected {{
        color: {p['cyan_hi']};
        background: {p['panel']};
        border-left: 2px solid {p['cyan']};
    }}
    QListWidget#nav::item:hover {{
        color: {p['ink']};
    }}
    /* ------------------------------------------------------------ tables */
    QTableWidget {{
        background: {p['panel']};
        alternate-background-color: #060D14;
        gridline-color: {p['grid']};
        border: 1px solid {p['edge_soft']};
        border-radius: 0px;
        selection-background-color: {p['selection']};
        selection-color: {p['bright']};
        font-family: {MONO_STACK};
        font-size: 12px;
    }}
    QTableWidget::item {{
        padding: 0px 6px;
    }}
    QHeaderView::section {{
        background: {p['header']};
        color: {p['faint']};
        border: none;
        border-bottom: 1px solid {p['edge_soft']};
        border-right: 1px solid {p['grid']};
        padding: 5px 6px;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1px;
        font-family: {UI_STACK};
    }}
    QTableCornerButton::section {{
        background: {p['header']};
        border: none;
    }}
    /* ------------------------------------------------------------ inputs */
    QLineEdit {{
        background: {p['panel']};
        border: 1px solid {p['edge_soft']};
        border-radius: 0px;
        padding: 5px 9px;
        color: {p['bright']};
        font-family: {MONO_STACK};
    }}
    QLineEdit:focus {{
        border: 1px solid {p['cyan']};
    }}
    QPushButton {{
        background: {p['panel']};
        border: 1px solid {p['edge_soft']};
        border-radius: 0px;
        padding: 6px 16px;
        color: {p['ink']};
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QPushButton:hover {{
        border: 1px solid {p['cyan']};
        color: {p['cyan_hi']};
    }}
    QPushButton:pressed {{
        background: {p['selection']};
    }}
    QPushButton:disabled {{
        color: {p['faint']};
        border: 1px solid {p['edge_soft']};
    }}
    QSpinBox {{
        background: {p['panel']};
        border: 1px solid {p['edge_soft']};
        color: {p['bright']};
        font-family: {MONO_STACK};
        padding: 2px;
    }}
    QCheckBox {{
        color: {p['dim']};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {p['edge_soft']};
        background: {p['panel']};
    }}
    QCheckBox::indicator:checked {{
        background: {p['cyan']};
    }}
    /* --------------------------------------------------------- status bar */
    QStatusBar {{
        background: {p['header']};
        color: {p['dim']};
        border-top: 1px solid {p['edge_soft']};
        font-size: 11px;
    }}
    QScrollBar:vertical {{
        background: {p['panel']};
        width: 10px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {p['edge_soft']};
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p['cyan']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: {p['panel']};
        height: 10px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: {p['edge_soft']};
        min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    """
