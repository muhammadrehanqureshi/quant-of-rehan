#!/usr/bin/env python3
"""LOCAL-ONLY HCAR signal post-mortem and rejected-candidate target audit.

Usage on the owner's PC:
    python scripts/hcar_postmortem.py
    python scripts/hcar_postmortem.py --date 2026-10-16 --out data/forward/audit.json
    python scripts/hcar_postmortem.py --observation-cache data/forward/observation.json \
        --session-journal data/forward/session_journal.jsonl

The command reads authenticated relay observations/outcomes and local broker
MKT-FEED captures. It does not use an external OHLC or market-data fallback to
classify rejected candidates. The local daily history is used only for the
separately labeled HCAR strategy analogue.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.local_only import guard_local_only  # noqa: E402
from src.research.hcar_postmortem import main as audit_main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    guard_local_only("scripts/hcar_postmortem.py")
    return audit_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
