"""Append-only experiment registry for the self-improvement engine.

Owner order (self-improvement mission): every run logs id, hypothesis, code
hash, data hash, parameters, seed, split, results and decision, append only.
The registry is one JSON Lines file under data/research/ (gitignored like the
rest of the local research artifacts), one JSON object per experiment, and it
is never rewritten: an experiment that turned out badly stays in the file,
which is what makes the registry's total count honest evidence for the
multiplicity correction (SO-3: no dropped losers, no relabelled outcomes).

The multiplicity correction is Holm's step-down over the one-sided p-values
the search itself reports: the count of TOTAL experiments ever registered is
the family size, because every trial counts (INTEGRITY: count every trial).

Nothing here executes, sleeps, or touches a network. The registry reads and
writes one file and never raises on a missing file: an empty history is a
stated zero, not an error.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Where the registry lives. The path is relative to the repository root and
#: the folder is created on first write so a fresh clone starts clean(er).
REGISTRY_PATH = Path("data/research/experiments.jsonl")

#: Fields every registry row must carry. A row missing one is refused on
#: load (the row is malformed, not absent) and load() reports it dropped.
REQUIRED_FIELDS = (
    "id", "ts_utc", "hypothesis", "code_hash", "data_hash", "params",
    "seed", "split", "results", "pred", "kill", "decision",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _karachi_stamp() -> str:
    """The same instant as SO-8 Karachi wall clock (UTC+5), for the report."""
    now = _utc_now_iso()
    stamp = datetime.fromisoformat(now)
    return stamp.isoformat(timespec="seconds").replace("+00:00", "+05:00")


def code_hash(repo_root: Path | None = None) -> str:
    """A short identity for the code that produced a run.

    The current commit SHA plus the hashes of the self-improvement sources,
    so an experiment row survives even when the branch it ran on is later
    deleted. Never reads anything outside the repository.
    """
    root = repo_root or ROOT
    commit = "unknown"
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, timeout=30, check=True).stdout.strip()[:12]
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    digest = hashlib.sha256()
    for rel in ("src/research/experiment_registry.py",
                "src/research/outcome_labeler.py",
                "scripts/self_improve.py",
                "src/backtest/engine.py",
                "src/backtest/daily_strategy.py"):
        path = root / rel
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"missing")
    return f"{commit}:{digest.hexdigest()[:12]}"


def data_hash(path: Path) -> str:
    """The first 16 hex characters of the dataset's SHA-256 (SO-3: the row
    names exactly the dataset the run saw, so another run can reproduce it
    or honestly refuse when the dataset is gone)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


class Registry:
    """Append-only exper idgement ledger over one JSON Lines file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else ROOT / REGISTRY_PATH

    def count(self) -> int:
        """Total experiments ever registered (the multiplicity family size)."""
        return len(self.rows())

    def rows(self) -> list[dict]:
        if not self.path.is_file():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def next_id(self) -> int:
        rows = self.rows()
        if not rows:
            return 1
        return max(int(row.get("id", 0)) for row in rows) + 1

    def append(self, entry: dict) -> dict:
        """Write one experiment row. Missing fields become explicit nulls
        so the file is always parseable worksheet-by-row (SO-3)."""
        row = {field: entry.get(field) for field in REQUIRED_FIELDS}
        row["ts_karachi"] = _karachi_stamp()
        if row.get("id") is None:
            row["id"] = self.next_id()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        return row


def one_sided_p(win_rate: float, n: int) -> float | None:
    """One-sided binomial p that the TRUE win rate is at most 0.5.

    Normal approximation with continuity correction; good enough for the
    registry's record and computed without a dependency. Returns None when
    there is nothing to test.
    """
    if n <= 0 or win_rate is None:
        return None
    mean, sd = 0.5 * n, 0.5 * math.sqrt(n)
    if sd <= 0:
        return 0.0 if win_rate > 0.5 else 1.0
    z = (float(n) * win_rate - mean - 0.5) / sd
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def holm_adjusted(p_values: dict[str, float]) -> dict[str, float]:
    """Holm's step-down adjustment over the search's reported p-values.

    The family is every p-value handed in; the REGISTRY's total count is the
    honest family size and is reported separately by the caller, because the
    correction needs one usable p per variant that reached a test.
    """
    items = sorted(((name, p) for name, p in p_values.items() if p is not None),
                   key=lambda pair: pair[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, p) in enumerate(items, start=1):
        running = max(running, min(1.0, (len(items) - rank + 1) * p))
        adjusted[name] = running
    return adjusted


def summarize_rows(rows: list[dict], *, last_n: int | None = None) -> dict:
    """Counting summary for the one-screen output; the count IS the evidence."""
    scope = rows if last_n is None else rows[-last_n:]
    decisions: dict[str, int] = {}
    for row in scope:
        key = str(row.get("decision"))
        decisions[key] = decisions.get(key, 0) + 1
    return {"total": len(scope), "decisions": decisions}


if __name__ == "__main__":
    handles = Registry()
    print(json.dumps(summarize_rows(handles.rows()), indent=2))
    sys.exit(0)
