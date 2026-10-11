from src.data import registry  # noqa: E402  (SO-3: package-level truth source)
# src/__init__.py
#
# Makes src.* a real package namespace so the SO-3 footprint-honesty guard can
# query the data-source registry directly on src.registry (the single place
# src/data/registry.py is offered as a package-level truth source), and so the
# existing imports that already target src.* continue to resolve.
#
# Do not add new public API here. New package-level names belong in a
# dedicated submodule that already exists (for example src.config or
# src.data.registry) and is imported from where it is used.
