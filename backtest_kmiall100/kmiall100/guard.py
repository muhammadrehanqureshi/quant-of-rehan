"""Keep the owner's PC out of it.

Standing order SO-21 in the QoR repository: backtests run on GitHub Actions
minutes, never on the owner's machine. This module is that rule in code.

* ``require_cloud()``: the runner refuses to start unless it is inside a GitHub
  Actions job (``GITHUB_ACTIONS=true``) or another cloud box that sets
  ``KMIALL_CLOUD=1``. There is no flag that overrides it on the command line, so a
  stray local run cannot happen by accident. A deliberate one needs the
  environment variable ``KMIALL_ALLOW_LOCAL=1`` set by hand, and even then the
  process runs one worker at lowest priority with a hard duty cycle cap.
* ``pin_threads()``: before numpy loads, pin every maths library to one thread so a
  stray BLAS call cannot fan out across all cores.
* ``lowest_priority()``: Windows idle class or POSIX nice 19.
* ``Throttle``: a CPU duty cycle cap, the same token bucket idea as the repository's
  resource governor. Only used in the deliberate local case.
"""

from __future__ import annotations

import os
import sys
import time


def is_cloud() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("KMIALL_CLOUD") == "1"


def local_allowed() -> bool:
    return os.environ.get("KMIALL_ALLOW_LOCAL") == "1"


def pin_threads(n: int = 1) -> None:
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
              "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS"):
        os.environ[k] = str(n)


def lowest_priority() -> None:
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00000040)  # IDLE
        else:
            os.nice(19)
    except Exception:
        pass


def require_cloud() -> str:
    """Returns 'cloud' or 'local'. Exits with code 3 when a local run was not explicitly allowed."""
    if is_cloud():
        return "cloud"
    if local_allowed():
        pin_threads(1)
        lowest_priority()
        return "local"
    sys.stderr.write(
        "REFUSED: this backtest only runs in the cloud (GitHub Actions). Your PC is not used.\n"
        "Dispatch the 'kmiall100-backtest' workflow instead. (A deliberate local run needs\n"
        "KMIALL_ALLOW_LOCAL=1 in the environment, and then it runs at lowest priority on one core.)\n")
    sys.exit(3)


class Throttle:
    """Keep the process at or under ``cap`` (a fraction) of one core, averaged over its life."""

    def __init__(self, cap: float = 0.05):
        self.cap = max(0.01, min(1.0, cap))
        self.t0 = time.perf_counter()
        self.c0 = time.process_time()

    def checkpoint(self) -> None:
        used = time.process_time() - self.c0
        allow = self.cap * (time.perf_counter() - self.t0)
        if used > allow:
            time.sleep(min(30.0, (used - allow) / self.cap))
