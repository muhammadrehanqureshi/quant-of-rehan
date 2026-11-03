"""Palette and stylesheet for the desktop terminal.

Owner order 2026-11-03: the terminal reads like a professional trading
desk, not a toy. Flat surfaces, one-pixel hairlines, no rounded cartoon
pills, no arc gauges. Data is set in a monospaced face so columns align;
chrome is Segoe UI. Green up, red down, gold brand, everything else is
shades of charcoal. Every rule here is a colour or a border, never a timer.
"""

from __future__ import annotations

MONO_STACK = '"Cascadia Mono", Consolas, "Courier New", monospace'
UI_STACK = '"Segoe UI", sans-serif'

PALETTE = {
    "field": "#0B0E12",          # window field
    "panel": "#10151C",          # raised surface
    "panel_edge": "#1C2530",     # hairline border
    "header": "#0E1218",         # the top bar
    "ink": "#DDE4EC",            # primary text
    "bright": "#F4F7FA",         # the number itself
    "dim": "#8A96A4",            # secondary text
    "faint": "#5C6875",          # labels and captions
    "green": "#2ECC71",
    "green_field": "#12331F",    # filled positive tile background
    "red": "#E5484D",
    "red_field": "#3A1718",      # filled negative tile background
    "gold": "#E0A93E",           # brand
    "gold_hi": "#F5C25B",
    "grid": "#151D26",           # table gridline
    "selection": "#1A2733",
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
        font-size: 14px;
        font-weight: 700;
        letter-spacing: 2px;
        background: transparent;
    }}
    QLabel#brandSub {{
        color: {p['faint']};
        font-size: 9px;
        letter-spacing: 1px;
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
        border: 1px solid {p['panel_edge']};
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
        border-top: 1px solid {p['panel_edge']};
        max-height: 4px;
    }}
    QProgressBar#sessionbar::chunk {{
        background: {p['gold']};
    }}
    /* ------------------------------------------------------------ pages */
    QLabel#pageTitle {{
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 2px;
        color: {p['ink']};
    }}
    QLabel#sectionLabel {{
        color: {p['faint']};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 2px;
    }}
    QLabel#stat {{
        font-family: {MONO_STACK};
        font-size: 24px;
        font-weight: 600;
        color: {p['bright']};
    }}
    QLabel#statSmall {{
        font-family: {MONO_STACK};
        font-size: 15px;
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
        font-size: 30px;
        font-weight: 700;
        letter-spacing: 2px;
    }}
    QFrame#panel {{
        background: {p['panel']};
        border: 1px solid {p['panel_edge']};
        border-radius: 0px;
    }}
    /* -------------------------------------------------------------- nav */
    QListWidget#nav {{
        background: {p['field']};
        border-right: 1px solid {p['panel_edge']};
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
        color: {p['bright']};
        background: {p['panel']};
        border-left: 2px solid {p['gold']};
    }}
    QListWidget#nav::item:hover {{
        color: {p['ink']};
    }}
    /* ------------------------------------------------------------ tables */
    QTableWidget {{
        background: {p['panel']};
        alternate-background-color: #0D1218;
        gridline-color: {p['grid']};
        border: 1px solid {p['panel_edge']};
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
        border-bottom: 1px solid {p['panel_edge']};
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
        border: 1px solid {p['panel_edge']};
        border-radius: 0px;
        padding: 5px 9px;
        color: {p['bright']};
        font-family: {MONO_STACK};
    }}
    QLineEdit:focus {{
        border: 1px solid {p['gold']};
    }}
    QPushButton {{
        background: {p['panel']};
        border: 1px solid {p['panel_edge']};
        border-radius: 0px;
        padding: 6px 16px;
        color: {p['ink']};
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QPushButton:hover {{
        border: 1px solid {p['gold']};
        color: {p['gold_hi']};
    }}
    QPushButton:pressed {{
        background: {p['selection']};
    }}
    QPushButton:disabled {{
        color: {p['faint']};
        border: 1px solid {p['panel_edge']};
    }}
    QSpinBox {{
        background: {p['panel']};
        border: 1px solid {p['panel_edge']};
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
        border: 1px solid {p['panel_edge']};
        background: {p['panel']};
    }}
    QCheckBox::indicator:checked {{
        background: {p['gold']};
    }}
    /* --------------------------------------------------------- status bar */
    QStatusBar {{
        background: {p['header']};
        color: {p['dim']};
        border-top: 1px solid {p['panel_edge']};
        font-size: 11px;
    }}
    QScrollBar:vertical {{
        background: {p['panel']};
        width: 10px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {p['panel_edge']};
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p['faint']};
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
        background: {p['panel_edge']};
        min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    """
