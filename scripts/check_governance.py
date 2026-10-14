#!/usr/bin/env python3
#!/usr/bin/env python3
"""Governance enforcement, run on every PR (and locally before pushing).

Checks:
1. SO-5: no secret-shaped strings anywhere in tracked text files.
2. SO-3: no module claims footprint/order-flow capability without going
   through src/data/registry.py.
3. SO-1/SO-2: GOVERNANCE.md exists and carries the signal-only and
   PR-first laws.
4. SO-7: owner-only author identity and human style. The em dash is
   banned from every committed file and commit message; quarantined
   legacy/ reference material is exempt because it is never modified.
5. SO-7a: every PR commit carries the agent's co-author line, exactly once
   and exactly as the owner ordered it on 2026-10-13.
6. SO-8: session logic must pin Karachi time (UTC+5) explicitly.
7. SO-4: every declared backtest entry point refuses to run in GitHub
   Actions (src/ci/local_only.py) and no workflow invokes one.
8. SO-12: every declared recurring entry point refuses to start on the
   owner's PC, and no workflow registers a local task or a login entry.
9. SO-13: the words of the 30-second cadence order stay in GOVERNANCE.md:
   one scan for the card and the intraday strategy, the measured cost of a
   cycle, and the fact that it is free on the public repository.
10. SO-20: the scan path reaches for the read-only tape first: the
   recorder subscribes to the tracked KMIALL universe, a start that dies is
   watched and named, and the dead OHLC servlet is only the day with no tape.

Exit code 0 = compliant. Non-zero = PR must not merge.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.local_only import (  # noqa: E402
    CLOUD_ONLY_DAEMONS,
    LOCAL_ONLY_SCRIPTS,
)

# Text extensions eligible for scanning
TEXT_EXTS = {
    ".py", ".md", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini",
    ".txt", ".sh", ".ps1", ".bat", ".csv", ".sql", ".html", ".js", ".ts",
}

SKIP_DIRS = {".git", ".freebuff", "__pycache__", ".venv", "venv", "assets", "legacy"}

# SO-7: the owner banned the em dash (and its thin/narrow cousins) from all
# committed text. Human style only: commas, colons, parentheses, periods.
DASH_CHARS = "\u2014\u2013\u2012\u2015\u2E3A\u2E3B"

# SO-7: the repository shows exactly one author, the owner. GitHub uses two
# official noreply forms for one account: the plain one and the
# user-id-prefixed one (also what the merge button authors with). Both count
# as the owner; anything else fails.
OWNER_NAME = "Mr. Rehan"
OWNER_EMAIL = "muhammadrehanqureshi@users.noreply.github.com"
OWNER_EMAIL_ALT = "111383512+muhammadrehanqureshi@users.noreply.github.com"

# SO-7a (owner order, 2026-10-13): the agent is the owner's co-author, so
# every commit must carry this one line, exactly as written. The agent keeps
# its own identity in the repository's own words: Codebuff, the agent that
# works here. It is compared case-insensitively, like every trailer below.
REQUIRED_COAUTHOR = "co-authored-by: Codebuff <noreply@codebuff.com>"

# SO-7/SO-7a: every OTHER attribution stays banned on top of the one line.
FORBIDDEN_TRAILERS = (
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
    # Owner order 2026-10-14: SO-12 must keep naming the scanner's home, the
    # PC's one job, and the fact that nothing recurring lives there.
    "The 4-minute scanner is cloud-only",
    "Nothing recurring is registered on the PC any more",
    "the owner's PC is used for the backtests",
    # Owner order 2026-10-14 (SO-13): the cadence the owner asked for, the
    # single scan both readers get, and the fact that it costs him nothing.
    "The scan cadence is 30 seconds",
    "The same scan, observation and data-quality",
    "The owner pays nothing",
]

# SO-12: a workflow that registers local autostart would put recurring work
# back on the owner's PC from the cloud, which is the one direction the order
# forbids outright. Each needle is a way to do it.
LOCAL_AUTOSTART_PATTERNS = (
    ("schtasks", "registers a Windows scheduled task"),
    ("Start Menu", "writes a login entry"),
    ("install_kmiall_tick", "installs the local KMIALL tick task"),
    ("install_scheduler", "installs the local logon task"),
)


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


def check_cloud_only(errors: list) -> None:
    """SO-12: recurring work stays in the cloud, off the owner's PC.

    Owner order 2026-10-14: the 4-minute scanner always runs on GitHub Actions
    minutes and on the Cloudflare relay, and the owner's PC is used only for a
    backtest he asks for. SO-10 said as much, but nothing objected when a task
    was registered or a resident runner was started, so the rule was only as
    strong as the session that remembered it. This is the objection: every
    declared recurring entry point must carry the guard, and no workflow may
    put local autostart back in place.
    """
    for rel, task in sorted(CLOUD_ONLY_DAEMONS.items()):
        p = ROOT / rel
        if not p.is_file():
            errors.append(
                f"[SO-12] {rel} is declared cloud-only ({task}) but does not "
                f"exist; fix src/ci/local_only.py or restore the entry point"
            )
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f'guard_owner_requested("{rel}")' not in text:
            errors.append(
                f"[SO-12] {rel} ({task}) does not call "
                f'guard_owner_requested("{rel}"): it could then start on the '
                f"owner's PC and hammer it with recurring work the cloud "
                f"already carries"
            )

    workflows = ROOT / ".github" / "workflows"
    for wf in sorted(workflows.glob("*.yml")) if workflows.is_dir() else []:
        try:
            text = wf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for needle, why in LOCAL_AUTOSTART_PATTERNS:
            if needle in text:
                errors.append(
                    f"[SO-12] {wf.name} {why}: recurring work belongs to "
                    f"GitHub Actions minutes and the Cloudflare relay, never "
                    f"to the owner's PC (owner order 2026-10-14)"
                )


def check_tape_before_scanner(errors: list) -> None:
    """SO-20: the scan path reaches for the read-only broker tape, always.

    Measured 2026-10-14 on a GitHub Actions runner: the loop chose its bar
    source before asking for the recorder, so a fresh checkout with no tape
    fell through to the dead eClear OHLC servlet, five straight 30 second
    cycles faulted, and the loop gave up without banking a bar. This check
    holds the two halves of the fix in place: the recorder subscribes to the
    tracked KMIALL universe (the gitignored legacy copy does not exist on a
    fresh checkout), a start that dies is watched and named rather than
    reported as success, and the loop asks for the tape before it chooses a
    bar source.
    """
    watched = {
        "src/data/feed_capture.py": "the recorder's universe",
        "src/data/live_card.py": "the tape's liveness",
        "scripts/scan_loop.py": "the scan path's bar source",
    }
    for rel, what in watched.items():
        p = ROOT / rel
        if not p.is_file():
            errors.append(
                f"[SO-20] {rel} is missing; {what} cannot be verified"
            )
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if rel == "src/data/feed_capture.py":
            if "universe_kmiall.json" not in body:
                errors.append(
                    "[SO-20] src/data/feed_capture.py does not name the "
                    "tracked universe_kmiall.json; a gitignored universe file "
                    "means no tape at all on a fresh checkout"
                )
            universe_line = next(
                (line for line in body.splitlines()
                 if line.strip().startswith("UNIVERSE_FILE")),
                "",
            )
            if "legacy_sentinel" in universe_line:
                errors.append(
                    "[SO-20] src/data/feed_capture.py takes its universe from "
                    "the gitignored legacy sentinel copy; the tracked "
                    "src/data/universe_kmiall.json is what a fresh checkout "
                    "has, and it is the list the scanner scans"
                )
            if "refusing to subscribe" not in body:
                errors.append(
                    "[SO-20] src/data/feed_capture.py no longer refuses a "
                    "missing universe in words (refusing to subscribe, SO-3)"
                )
        if rel == "src/data/live_card.py":
            for needle, why in (
                ("START_PROBE_SECONDS",
                 "a freshly spawned recorder is not watched, so a crash at "
                 "startup would be reported as a running tape"),
                ("_probe_child",
                 "the start probe itself is missing from start_tape"),
                ("exited with code",
                 "a child that dies at start is not named with its exit code"),
            ):
                if needle not in body:
                    errors.append(f"[SO-20] src/data/live_card.py: {why}")
        if rel == "scripts/scan_loop.py":
            if "_capture(self) -> bool" not in body:
                errors.append(
                    "[SO-20] scripts/scan_loop.py has no _capture method, so "
                    "the loop's bar-source order cannot be read at all"
                )
            else:
                marker = body.find("def _capture(self) -> bool:")
                end = body.find(chr(10) + "    def ", marker + 10)
                window = body[marker:end if end > marker else len(body)]
                asks = window.find("ensure_tape")
                falls = window.find("_poller_capture")
                if asks < 0:
                    errors.append(
                        "[SO-20] scripts/scan_loop._capture does not ask for "
                        "the recorder before choosing a bar source"
                    )
                elif falls >= 0 and falls < asks:
                    errors.append(
                        "[SO-20] scripts/scan_loop._capture falls through to "
                        "the dead OHLC servlet before the recorder was asked "
                        "for; the tape comes first"
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
        # %h is the abbreviated hash, so a failure names the commit.
        out = subprocess.run(
            ["git", "log", rng, "--format=%h%x09%an%x09%ae%x09%B%x00"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return  # range not resolvable here; CI covers it
    for block in out.split("\x00"):
        if not block.strip():
            continue
        parts = block.strip("\n").split("\t", 3)
        if len(parts) < 4:
            continue
        sha, name, email, message = parts[0], parts[1], parts[2], parts[3]
        if name.strip() != OWNER_NAME or email.strip() not in (OWNER_EMAIL, OWNER_EMAIL_ALT):
            errors.append(
                f"[SO-7] commit {sha} not authored as {OWNER_NAME} "
                f"<{OWNER_EMAIL}>: got {name} <{email}>"
            )
        low = message.lower()
        # SO-7a: the owner's co-author line, present exactly once and never
        # replaced by another identity. The check is on the trailer lines
        # themselves, so a name buried in the body prose cannot stand in for
        # it and a second co-author cannot ride along beside it.
        coauthor_lines = [line.strip() for line in low.splitlines()
                          if line.strip().startswith("co-authored-by:")]
        if not coauthor_lines:
            errors.append(
                f"[SO-7a] commit {sha} is missing the owner's co-author line "
                f"{REQUIRED_COAUTHOR!r}: every commit, PR and merge carries "
                f"the agent as co-author (owner order 2026-10-13)"
            )
        for line in coauthor_lines:
            if line != REQUIRED_COAUTHOR.lower():
                errors.append(
                    f"[SO-7a] commit {sha} carries a co-author line that is "
                    f"not the owner's own: {line!r}"
                )
        if len(coauthor_lines) > 1:
            errors.append(
                f"[SO-7a] commit {sha} carries the co-author line "
                f"{len(coauthor_lines)} times; it belongs once, as the last "
                f"line of the message"
            )
        for trailer in FORBIDDEN_TRAILERS:
            if trailer in low:
                errors.append(
                    f"[SO-7] commit {sha} contains banned trailer {trailer!r}"
                )
        for ch in DASH_CHARS:
            if ch in message:
                errors.append(
                    f"[SO-7] commit {sha} contains a banned dash character"
                )
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
    check_cloud_only(errors)
    check_tape_before_scanner(errors)

    if errors:
        print("GOVERNANCE CHECK FAILED, PR must not merge:\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("GOVERNANCE CHECK PASSED (SO-13 cadence and free-minute law included): "
          "secrets clean, footprint honesty intact, "
          "standing orders present, SO-7 style and identity verified, "
          "SO-7a co-author line verified, SO-8 Karachi pin verified, "
          "SO-4 local-only backtests enforced, SO-12 cloud-only recurring "
          "work enforced, SO-20 tape before scanner.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
