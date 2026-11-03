"""Quant of Rehan desktop terminal: entry point.

Usage:
    python -m src.desktop.app            # the terminal
    python -m src.desktop.app --smoke    # build the window offscreen and exit
    python -m src.desktop.app --no-feed  # window without starting the feed

--smoke exists so packaging and CI can prove the window builds and its
timer ticks without a display, without touching the broker socket.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def window_icon_path() -> Path | None:
    """The bundled ico, wherever the runtime is running from."""
    from pathlib import Path as _Path

    if getattr(sys, "frozen", False):
        candidate = _Path(getattr(sys, "_MEIPASS", "") or "") / "assets" \
            / "quant-of-rehan.ico"
    else:
        candidate = _Path(__file__).resolve().parents[2] / "assets" \
            / "quant-of-rehan.ico"
    return candidate if candidate.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quant of Rehan terminal")
    parser.add_argument("--smoke", action="store_true",
                        help="construct the window offscreen, then exit")
    parser.add_argument("--no-feed", action="store_true",
                        help="do not start the read-only feed")
    args = parser.parse_args(argv)

    if args.smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    if getattr(sys, "frozen", False):
        # A frozen build must not write the day's tape inside its own
        # install directory. The capture root moves to %APPDATA% before any
        # data module is imported, and the recorder constants follow it.
        data_dir = (Path(os.environ.get("APPDATA") or str(Path.home()))
                    / "QuantOfRehan" / "data")
        os.environ["QOR_CAPTURE_DIR"] = str(data_dir / "feed_capture")
        data_dir.mkdir(parents=True, exist_ok=True)

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    if getattr(sys, "frozen", False):
        from pathlib import Path as _Path

        from src.data import feed_capture

        feed_capture.CAPTURE_DIR = _Path(os.environ["QOR_CAPTURE_DIR"])
        feed_capture.STATUS_PATH = feed_capture.CAPTURE_DIR / "status.json"

    from src.desktop.main_window import MainWindow

    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("Quant of Rehan")
    application.setOrganizationName("QuantOfRehan")
    icon = window_icon_path()
    if icon is not None:
        application.setWindowIcon(QIcon(str(icon)))
    window = MainWindow(start_feed=not (args.no_feed or args.smoke))
    window.show()

    if args.smoke:
        QTimer.singleShot(1200, application.quit)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
