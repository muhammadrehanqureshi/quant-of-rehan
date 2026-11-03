# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Quant of Rehan console terminal.

The console build is the shipped desk: it opens in its own console window
with the HUD drawn in text, and it reads the relay directly, so it needs no
Qt and no local capture. It is built beside the Qt build, never instead of
it, and lands in dist/QuantOfRehanConsole.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
ICON = ROOT / "assets" / "quant-of-rehan.ico"

analysis = Analysis(
    [str(ROOT / "src" / "desktop" / "tui.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ICON), "assets")] if ICON.is_file() else [],
    hiddenimports=["src.data.registry"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6",
        "tkinter",
        "matplotlib",
        "IPython",
        "numpy",
        "pandas",
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
    console=True,
    icon=str(ICON) if ICON.is_file() else None,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="QuantOfRehanConsole",
)
