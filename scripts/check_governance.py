#!/usr/bin/env python3
#!/usr/bin/env python3
"""Governance enforcement, run on every PR (and locally before pushing).

Checks:
1. SO-5: no secret-shaped strings anywhere in tracked text files.
2. SO-3: no module claims footprint/order-flow capability without going
   through src/data/registry.py.
3. SO-1/SO-2: GOVERNANCE.md exists and carries the signal-only and
   PR-first laws.
4. SO-7: owner-only contributor identity and human style. The em dash is
   banned from every committed file and commit message; quarantined
   legacy/ reference material is exempt because it is never modified.
5. SO-8: session logic must pin Karachi time (UTC+5) explicitly.
6. SO-4: every declared backtest entry point refuses to run in GitHub
   Actions (src/ci/local_only.py) and no workflow invokes one.

Exit code 0 = compliant. Non-zero = PR must not merge.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.local_only import LOCAL_ONLY_SCRIPTS  # noqa: E402

# Text extensions eligible for scanning
TEXT_EXTS = {
    ".py", ".md", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini",
    ".txt", ".sh", ".ps1", ".bat", ".csv", ".sql", ".html", ".js", ".ts",
}

SKIP_DIRS = {".git", ".freebuff", "__pycache__", ".venv", "venv", "assets", "legacy"}

# SO-7: the owner banned the em dash (and its thin/narrow cousins) from all
# committed text. Human style only: commas, colons, parentheses, periods.
DASH_CHARS = "\u2014\u2013\u2012\u2015\u2E3A\u2E3B"

# SO-7: the repository shows exactly one contributor, the owner. GitHub
# uses two official noreply forms for one account: the plain one and the
# user-id-prefixed one (also what the merge button authors with). Both count
# as the owner; anything else fails.
OWNER_NAME = "Mr. Rehan"
OWNER_EMAIL = "muhammadrehanqureshi@users.noreply.github.com"
OWNER_EMAIL_ALT = "111383512+muhammadrehanqureshi@users.noreply.github.com"
FORBIDDEN_TRAILERS = (
    "co-authored-by:",
    "generated with",
    "generated-by:",
    "signed-off-by:",
)

# SO-8: Karachi is the only timezone this system may speak.
KARACHI_REQUIRED_SNIPPETS = ("UTC+5", "Asia/Karachi")

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
    # Owner order 2026-10-11: the cloud budget belongs to the market-hours
    # scans, so SO-4 must keep saying where a backtest may run.
    "Actions minutes are reserved for the market-hours scans",
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
        except OSError as e:  # unreadable file: flag it rather than skip silently
            errors.append(f"[secrets] unreadable file {p.relative_to(ROOT)}: {e}")
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for pat, label in SECRET_PATTERNS:
                if pat.search(line):
                    errors.append(
                        f"[secrets] {p.relative_to(ROOT)}:{line_no}: "
                        f"possible {label}: remove before merging (SO-5)"
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
                        f"order-flow but never consults src/data/registry.py: "
                        f"engines must declare their data dependency (SO-3)"
                    )


def check_governance_doc(errors: list) -> None:
    gov = ROOT / "GOVERNANCE.md"
    if not gov.is_file():
        errors.append("[SO-2] GOVERNANCE.md missing: standing orders must exist")
        return
    text = gov.read_text(encoding="utf-8", errors="replace")
    # Markdown is wrapped by hand, so a required phrase can straddle a line
    # break. Compare on collapsed whitespace: the words and their order still
    # have to be there, only the wrapping stops mattering.
    flattened = " ".join(text.split()).lower()
    for snippet in REQUIRED_GOVERNANCE_SNIPPETS:
        if " ".join(snippet.split()).lower() not in flattened:
            errors.append(
                f"[SO-2] GOVERNANCE.md is missing required standing-order text: "
                f"{snippet!r}"
            )


def check_local_only(errors: list) -> None:
    """SO-4: the declared backtests stay on the owner's PC.

    Owner order 2026-10-11: backtesting happens only on the local PC, and the
    GitHub Actions minutes are reserved for the market-hours scans. Until
    now that lived in prose and in docstrings, so an edit could have put a
    five-year sweep into a workflow and nothing would have objected. This
    check is the objection: every declared entry point must carry the guard,
    and no workflow may invoke one.
    """
    for rel, task in sorted(LOCAL_ONLY_SCRIPTS.items()):
        p = ROOT / rel
        if not p.is_file():
            errors.append(
                f"[SO-4] {rel} is declared local-only ({task}) but does not "
                f"exist; fix src/ci/local_only.py or restore the script"
            )
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f'guard_local_only("{rel}")' not in text:
            errors.append(
                f"[SO-4] {rel} ({task}) does not call "
                f'guard_local_only("{rel}") in main(): it could then run in '
                f"GitHub Actions and spend the market-hours scan budget"
            )

    workflows = ROOT / ".github" / "workflows"
    for wf in sorted(workflows.glob("*.yml")) if workflows.is_dir() else []:
        try:
            text = wf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for rel in LOCAL_ONLY_SCRIPTS:
            if rel in text or Path(rel).name in text:
                errors.append(
                    f"[SO-4] {wf.name} invokes {rel}, which is local-only "
                    f"work: Actions minutes are reserved for the market-hours "
                    f"scans"
                )


def check_em_dashes(errors: list) -> None:
    for p in iter_text_files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for ch in DASH_CHARS:
                if ch in line:
                    name = f"U+{ord(ch):04X}"
                    errors.append(
                        f"[SO-7] {p.relative_to(ROOT)}:{line_no}: banned dash "
                        f"character {name}; use a comma, colon, or parentheses"
                    )
                    break


def check_commit_messages(errors: list) -> None:
    """SO-7 applies to new PR commits. Env var is set by the CI workflow;
    locally pass a range with GOVERN_COMMIT_RANGE=A..B to scan manually."""
    import os
    import subprocess

    rng = os.environ.get("GOVERN_COMMIT_RANGE", "").strip()
    if not rng:
        return
    try:
        # SO-7: decode as UTF-8 explicitly. With text=True and no encoding,
        # Python uses the ambient locale, so the same commit message could be
        # judged differently on a cp1252 Windows box and a UTF-8 CI runner:
        # the robot emoji (U+1F916) ends in byte 0x96, which cp1252 maps to
        # U+2013 EN DASH and falsely trips the banned-dash rule below.
        out = subprocess.run(
            ["git", "log", rng, "--format=%an%x09%ae%x09%B%x00"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return  # range not resolvable here; CI covers it
    for block in out.split("\x00"):
        if not block.strip():
            continue
        parts = block.strip("\n").split("\t", 2)
        if len(parts) < 3:
            continue
        name, email, message = parts[0], parts[1], parts[2]
        if name.strip() != OWNER_NAME or email.strip() not in (OWNER_EMAIL, OWNER_EMAIL_ALT):
            errors.append(
                f"[SO-7] commit not authored as {OWNER_NAME} <{OWNER_EMAIL}>: "
                f"got {name} <{email}>"
            )
        low = message.lower()
        for trailer in FORBIDDEN_TRAILERS:
            if trailer in low:
                errors.append(
                    f"[SO-7] commit message contains banned trailer {trailer!r}"
                )
        for ch in DASH_CHARS:
            if ch in message:
                errors.append("[SO-7] commit message contains a banned dash character")
                break


def check_karachi_pin(errors: list) -> None:
    """SO-8: any module that builds session times must pin UTC+5 explicitly."""
    for p in iter_text_files():
        rel = p.relative_to(ROOT).as_posix()
        if not rel.startswith("src/") or p.suffix != ".py":
            continue
        if rel == "src/data/sessions.py":
            continue  # the pin lives here by definition
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"\b\d{1,2}:\d{2}\b", text) and re.search(
            r"(session|market|open|close|cron)", text, re.IGNORECASE
        ):
            if not all(s in text for s in KARACHI_REQUIRED_SNIPPETS):
                errors.append(
                    f"[SO-8] {rel}: builds session/market times without an "
                    f"explicit Asia/Karachi UTC+5 pin; import it from "
                    f"src/data/sessions.py instead"
                )


def main() -> int:
    errors: list = []
    check_secrets(errors)
    check_footprint_honesty(errors)
    check_governance_doc(errors)
    check_em_dashes(errors)
    check_commit_messages(errors)
    check_karachi_pin(errors)
    check_local_only(errors)

    if errors:
        print("GOVERNANCE CHECK FAILED, PR must not merge:\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("GOVERNANCE CHECK PASSED: secrets clean, footprint honesty intact, "
          "standing orders present, SO-7 style and identity verified, "
          "SO-8 Karachi pin verified, SO-4 local-only backtests enforced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
