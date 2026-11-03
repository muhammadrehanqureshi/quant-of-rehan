"""Quant of Rehan desktop terminal: a stand-alone Windows client.

The terminal is a monitoring and signal-review client for the same backend
this repository already runs: the read-only Eclear feed capture, the market
session law, the order-flow layer and the local session record. It never
places an order (SO-1) and it holds no broker credential of its own: the
feed socket needs none, and the capture is the same read-only recorder the
cloud loop uses.

Modules:
    bridge       Qt free data functions (tested in CI without PySide6)
    theme        palette and stylesheet strings (Qt free)
    feed_worker  the read-only capture thread (PySide6)
    main_window  the terminal window (PySide6)
    app          the entry point

The data dependency is declared where the law lives, src/data/registry.py:
footprint is UNAVAILABLE, so the terminal shows top-of-book proxies only.
"""
