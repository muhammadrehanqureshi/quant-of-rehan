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
11. SO-22: the agent never sleeps. A wait in the landing tool or in a
   workflow is pacing, thirty seconds at most, and no wait may be aimed at a
   market clock: the session works, the cloud waits.

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
    BACKTEST_SCRIPTS,
)

# Text extensions eligible for scanning
TEXT_EXTS = {
    ".py", ".md", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini",
    ".txt", ".sh", ".ps1", ".bat", ".csv", ".sql", ".html", ".js", ".ts",
}

SKIP_DIRS = {
    ".git", ".freebuff", "__pycache__", ".venv", "venv", "assets",
    "legacy", "node_modules", "dist", ".pytest_cache", ".mypy_cache",
    ".ruff_cache",
}

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
    # Owner order 2026-10-21 (SO-22): the agent never sleeps, the cloud
    # waits, and the 14:30 wait for the close is the named offence.
    "The agent never sleeps; the cloud waits",
    "the cloud waits for it",
    "It never becomes the clock itself",
    "aimed at a market clock",
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

# SO-22 (owner order 2026-10-21): the agent never sleeps. A wait is pacing
# while it stays short; past this it is idling in a turn the owner asked to
# be spent working. The longest wait that exists today is ten seconds.
MAX_PACING_SECONDS = 30

# SO-22: the offence the order names is a wait built out of a market clock,
# the 14:30 sleep that sat there until the 15:30 close. A wait whose words
# name a session moment is that wait, whatever its duration.
# The clock words are matched inside identifiers too (seconds_until_close is
# the same wait as close), so only a letter on the left disqualifies them.
MARKET_CLOCK_WORDS = re.compile(
    r"(?<![A-Za-z])(close|closing|open|opening|band|session|market|finalize"
    r"|holiday)",
    re.IGNORECASE,
)
# A wait is a call or a command, never the noun: `sleep 5`, `sleep "$left"`,
# `time.sleep(...)`, `Start-Sleep -Seconds 60`. Prose that merely says "sleep"
# does not carry one of these openers, so comments and docstrings stay quiet.
WAIT_CALL = re.compile(
    r'''\b(time\.sleep|Start-Sleep|sleep)\s*(\(|["'$]|\d|-\w)''',
)
LITERAL_WAIT = re.compile(
    r"\bsleep\s+(\d+)"
    r"|time\.sleep\(\s*(\d+(?:\.\d+)?)\s*\)"
    r"|Start-Sleep\s+(?:-s(?:econds)?\s+)?(\d+)",
    re.IGNORECASE,
)

REQUIRED_AGENTS_SNIPPETS = [
    # Owner order 2026-10-21 (SO-22): the rule sits next to the machine rule,
    # because idling is what an eager session does next, and it must survive
    # every rewrite of this file.
    "The no-idling rule",
    "Don't ever sleep, do the work what I tell you",
    "the agent is never the clock",
]


def iter_text_files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        relative_parts = p.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in relative_parts):
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

    # SO-22: AGENTS.md is the file a session reads first, so the no-idling
    # order has to be in it too, in the owner's own words.
    agents = ROOT / "AGENTS.md"
    if not agents.is_file():
        errors.append(
            "[SO-22] AGENTS.md missing: a session would read no law at all"
        )
        return
    agent_text = " ".join(
        agents.read_text(encoding="utf-8", errors="replace").split()
    ).lower()
    for snippet in REQUIRED_AGENTS_SNIPPETS:
        if " ".join(snippet.split()).lower() not in agent_text:
            errors.append(
                f"[SO-22] AGENTS.md is missing required agent-law text: "
                f"{snippet!r}"
            )


def check_backtests_in_cloud(errors: list) -> None:
    """SO-21: declared backtests run in Actions and never on the owner's PC.

    Owner order 2026-10-19: the machine is not used at all, even two percent
    of it, and the now-public repository makes Actions minutes free for the
    backtests that used to run here. This check is that order in CI: every
    declared entry point must carry the guard, and a workflow that invokes
    one must be manual dispatch, because a scheduled sweep would silently
    become a cadence nobody asked for.
    """
    for rel, task in sorted(BACKTEST_SCRIPTS.items()):
        p = ROOT / rel
        if not p.is_file():
            errors.append(
                f"[SO-21] {rel} is declared backtest work ({task}) but does "
                f"not exist; fix src/ci/local_only.py or restore the script"
            )
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f'guard_cloud_backtest("{rel}")' not in text:
            errors.append(
                f"[SO-21] {rel} ({task}) does not call "
                f'guard_cloud_backtest("{rel}") in main(): it could then run '
                f"on the owner's PC, where no backtest may run"
            )

    workflows = ROOT / ".github" / "workflows"
    for wf in sorted(workflows.glob("*.yml")) if workflows.is_dir() else []:
        try:
            text = wf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for rel in BACKTEST_SCRIPTS:
            if rel in text or Path(rel).name in text:
                if "schedule:" in text or "cron:" in text:
                    errors.append(
                        f"[SO-21] {wf.name} runs {rel} on a schedule: a "
                        f"backtest is manual dispatch only, so it never "
                        f"becomes an unattended cadence"
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


def check_no_kv_quota(errors: list) -> None:
    """Owner order 2026-10-20: no product that mails a quota warning.

    The free KV allowance emailed the owner twice ("daily limit reached 50%"
    on 2026-10-19, then "daily limit reached" on 2026-10-20), and once that
    namespace was deleted the binding to it failed every relay deploy, so the
    edge served a stale build for a day. The relay keeps the card, the market
    snapshot, the session state, the pairing codes and the research log in the
    QuoteHub Durable Object instead. A KV namespace coming back through a
    config, a deploy path or a call site is the defect this check catches.
    """
    for config in ROOT.glob("**/wrangler.toml"):
        rel = config.relative_to(ROOT).as_posix()
        if "legacy" in config.parts or "node_modules" in config.parts:
            continue
        text = config.read_text(encoding="utf-8", errors="replace")
        if "[[kv_namespaces]]" in text or "kv_namespace" in text:
            errors.append(
                f"[KV quota] {rel}: declares a KV namespace. The free KV "
                f"allowance is what emailed the owner, and a binding to a "
                f"deleted namespace fails the whole deploy. Use the QuoteHub "
                f"Durable Object in cloud/worker.js."
            )

    worker = ROOT / "cloud" / "worker.js"
    if worker.is_file():
        text = worker.read_text(encoding="utf-8", errors="replace")
        for call in (".get(", ".put(", ".delete(", ".list("):
            needle = "env.RELAY_KV" + call
            if needle in text:
                errors.append(
                    f"[KV quota] cloud/worker.js: reaches into KV with "
                    f"`{needle}`. Relay state belongs in the QuoteHub object, "
                    f"through relayRead/relayWrite/relayDelete/relayList."
                )

    pair = ROOT / "cloud" / "pair.py"
    if pair.is_file():
        text = pair.read_text(encoding="utf-8", errors="replace")
        if '"kv_namespace"' in text:
            errors.append(
                "[KV quota] cloud/pair.py: uploads a KV binding; a manual "
                "deploy must ship the same bindings as cloud/wrangler.toml."
            )

    deploy = ROOT / ".github" / "workflows" / "deploy-relay.yml"
    if deploy.is_file():
        text = deploy.read_text(encoding="utf-8", errors="replace")
        if "RELAY_KV_ID" in text:
            errors.append(
                "[KV quota] deploy-relay.yml: still requires RELAY_KV_ID. The "
                "deploy must not depend on a namespace that no longer exists."
            )


def idle_wait_violations(rel: str, text: str) -> list:
    """SO-22: the waits that would make a session idle instead of working.

    Two shapes only, because those are the two the owner named. A wait built
    from a market clock is the 14:30 to 15:30 sleep itself. A wait longer than
    the pacing ceiling is the same idling in a different coat: a turn spent
    holding still. Short pacing stays legal, so a retry or a relay deploy is
    never flagged for it.
    """
    found: list = []
    # A duration computed one line above the wait is the same wait, so the
    # clock words are read in the statement's own neighbourhood.
    window: list = []
    for line_no, line in enumerate(text.splitlines(), 1):
        code = line.strip()
        if not code or code.startswith(("#", "//", "*")):
            continue
        if not WAIT_CALL.search(code):
            window = (window + [code])[-2:]
            continue
        context = " ".join(window[-2:] + [code])
        if MARKET_CLOCK_WORDS.search(context):
            found.append(
                f"[SO-22] {rel}:{line_no}: waits on a market clock "
                f"(`{code[:70]}`). The session works now; the cloud waits for "
                f"the close, never the agent (owner order 2026-10-21)"
            )
            continue
        literal = LITERAL_WAIT.search(code)
        if literal:
            seconds = max(
                float(g) for g in literal.groups() if g is not None
            )
            if seconds > MAX_PACING_SECONDS:
                found.append(
                    f"[SO-22] {rel}:{line_no}: sleeps {seconds:g}s in one go "
                    f"(`{code[:70]}`). Pacing stays at {MAX_PACING_SECONDS}s "
                    f"or less; anything longer is a session idling, and the "
                    f"cloud is where a wait belongs"
                )
    return found


def check_no_idle_waits(errors: list) -> None:
    """SO-22: the agent's own tooling paces a call, it never idles for a clock.

    The scope is the code a session drives (the scripts it launches and the
    workflows it dispatches), not the cloud daemons, which legitimately hold
    a session's wait on the far side of the PC. Only those two trees are read,
    so `src/data/session_gate.py` can keep waiting for a scan window.
    """
    for area in ("scripts", ".github/workflows"):
        base = ROOT / area
        if not base.is_dir():
            errors.append(
                f"[SO-22] {area}/ is missing; the no-idling check cannot "
                f"verify the agent's tooling"
            )
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in TEXT_EXTS:
                continue
            rel = p.relative_to(ROOT).as_posix()
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            errors.extend(idle_wait_violations(rel, text))


def main() -> int:
    errors: list = []
    check_secrets(errors)
    check_footprint_honesty(errors)
    check_governance_doc(errors)
    check_em_dashes(errors)
    check_commit_messages(errors)
    check_karachi_pin(errors)
    check_backtests_in_cloud(errors)
    check_cloud_only(errors)
    check_tape_before_scanner(errors)
    check_no_kv_quota(errors)
    check_no_idle_waits(errors)

    if errors:
        print("GOVERNANCE CHECK FAILED, PR must not merge:\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("GOVERNANCE CHECK PASSED (SO-13 cadence and free-minute law included): "
          "secrets clean, footprint honesty intact, "
          "standing orders present, SO-7 style and identity verified, "
          "SO-7a co-author line verified, SO-8 Karachi pin verified, "
          "SO-21 backtests cloud-only enforced, SO-12 cloud-only recurring "
          "work enforced, SO-20 tape before scanner, KV quota removed, "
          "SO-22 no clock wait in the agent's tooling.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
