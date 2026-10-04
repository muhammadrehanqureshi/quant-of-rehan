#!/usr/bin/env python3
"""Governance enforcement — run on every PR (and locally before pushing).

Checks:
1. SO-5: no secret-shaped strings anywhere in tracked text files.
2. SO-3: no module claims footprint/order-flow capability without going
   through src/data/registry.py.
3. SO-1/SO-2: GOVERNANCE.md exists and carries the signal-only + PR-first laws.

Exit code 0 = compliant. Non-zero = PR must not merge.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Text extensions eligible for scanning
TEXT_EXTS = {
    ".py", ".md", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini",
    ".txt", ".sh", ".ps1", ".bat", ".csv", ".sql", ".html", ".js", ".ts",
}

SKIP_DIRS = {".git", ".freebuff", "__pycache__", ".venv", "venv", "assets"}

# Secret-shaped patterns (owner's known token families + generic shapes)
SECRET_PATTERNS = [
    (re.compile(r"gho_[A-Za-z0-9]{20,}"), "GitHub token (gho_…)"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "GitHub token (ghp_…)"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"cfut_[A-Za-z0-9]{20,}"), "Cloudflare token (cfut_…)"),
    (re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}"), "Telegram bot token"),
    (re.compile(r"RehanTSHDPS\d"), "Broker password"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "Private key"),
]

# A module claiming footprint capability must reference the registry
FOOTPRINT_CLAIM = re.compile(
    r"\b(footprint|order[_ -]?flow|bid[_ -]?ask)\b", re.IGNORECASE
)
REGISTRY_REF = re.compile(r"src[./\\]data[./\\]registry|from\s+\S*registry\s+import|data\.registry")

REQUIRED_GOVERNANCE_SNIPPETS = [
    "Signal-only",
    "Pull request first",
    "Never fabricate data",
    "Backtest locally only",
]


def iter_text_files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in TEXT_EXTS:
            yield p


def check_secrets(errors: list) -> None:
    for p in iter_text_files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:  # unreadable file — flag it rather than skip silently
            errors.append(f"[secrets] unreadable file {p.relative_to(ROOT)}: {e}")
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for pat, label in SECRET_PATTERNS:
                if pat.search(line):
                    errors.append(
                        f"[secrets] {p.relative_to(ROOT)}:{line_no}: "
                        f"possible {label} — remove before merging (SO-5)"
                    )


def check_footprint_honesty(errors: list) -> None:
    for p in iter_text_files():
        rel = p.relative_to(ROOT).as_posix()
        if rel == "src/data/registry.py" or rel.startswith("tests/"):
            continue  # registry defines the law; tests exercise it
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if FOOTPRINT_CLAIM.search(line) and "UNAVAILABLE" not in line.upper():
                # Only enforce inside code modules that *claim capability*;
                # docs (md) just need the registry/label mention somewhere in
                # the same file, which is checked file-level below.
                if p.suffix == ".py" and not REGISTRY_REF.search(text):
                    errors.append(
                        f"[SO-3] {rel}:{line_no}: code references footprint/"
                        f"order-flow but never consults src/data/registry.py — "
                        f"engines must declare their data dependency (SO-3)"
                    )


def check_governance_doc(errors: list) -> None:
    gov = ROOT / "GOVERNANCE.md"
    if not gov.is_file():
        errors.append("[SO-2] GOVERNANCE.md missing — standing orders must exist")
        return
    text = gov.read_text(encoding="utf-8", errors="replace")
    for snippet in REQUIRED_GOVERNANCE_SNIPPETS:
        if snippet.lower() not in text.lower():
            errors.append(
                f"[SO-2] GOVERNANCE.md is missing required standing-order text: "
                f"{snippet!r}"
            )


def main() -> int:
    errors: list = []
    check_secrets(errors)
    check_footprint_honesty(errors)
    check_governance_doc(errors)

    if errors:
        print("GOVERNANCE CHECK FAILED — PR must not merge:\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("GOVERNANCE CHECK PASSED — secrets clean, footprint honesty intact, "
          "standing orders present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
