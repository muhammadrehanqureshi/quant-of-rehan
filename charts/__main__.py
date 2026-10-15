"""``python -m charts`` runs the service's command line entry point."""

from __future__ import annotations

from charts.app import main

if __name__ == "__main__":
    raise SystemExit(main())
