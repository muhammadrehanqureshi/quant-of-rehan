"""The registry of all 100 strategies. Importing this module fills ``REGISTRY``."""

from . import strategies_1, strategies_2   # noqa: F401  (registers by decorator)
from .core import REGISTRY, Strat           # noqa: F401

assert len(REGISTRY) == 100, len(REGISTRY)
assert sorted(REGISTRY) == [f"S{i:03d}" for i in range(1, 101)]
