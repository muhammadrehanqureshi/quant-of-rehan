# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Quant of Rehan Windows terminal.

One-dir on purpose: startup stays fast and the EXE is not re-extracted to
%TEMP% on every launch. The executable is still a normal double-click app.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent   # spec lives in packaging/, parent is the repo root
ICON = ROOT / "assets" / "quant-of-rehan.ico"

analysis = Analysis(
    [str(ROOT / "src" / "desktop" / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "src" / "data" / "universe_kmiall.json"), "src/data")],
    hiddenimports=[
        "src.data.feed_capture",
        "src.data.broker_market",
        "src.data.tick_volume",
        "src.data.order_flow",
        "src.data.live_card",
        "src.data.sessions",
        "src.data.market_snapshot",
        "src.data.volume_split",
        "src.data.registry",
        "src.data.tape_bars",
        "src.data.capture_health",
        "src.signals.trade_state",
        "src.signals.scanner",
        "scripts.intraday_pipeline",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PySide6.Qt3DCore",
        "PySide6.QtQuick",
        "tkinter",
        "matplotlib",
        "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="QuantOfRehan",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON) if ICON.is_file() else None,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="QuantOfRehan",
)
