"""
PSX KMIALL BOT
Shared core package.

Every production script imports from here instead of re-implementing
universe loading, path anchoring, session logic, or feed parsing.

Import convention for scripts under src/:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from psx_core import paths, universe, sessions, feed, storage, logs
"""

__all__ = [
    "paths",
    "universe",
    "sessions",
    "feed",
    "storage",
    "logs",
]
