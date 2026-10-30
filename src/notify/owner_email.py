"""Owner email over the GitHub Actions channel (owner order 2026-10-22).

The owner decided today that notifications land as email on his GitHub
connected address (mrmrehanqureshi@gmail.com) and that the chat channel is
retired. GitHub Actions cannot reach an inbox by
itself, so the emails are carried by GitHub's own notification mail: the
transport writes each notification as a comment on the watched owner
email issue, and GitHub emails the owner the moment the comment lands.

One issue is one inbox, and its comments are the ledger: every body
starts with a marker line, so a send and a resend can never both go out.

  owner-email: <marker>

A caller marks its notification with one key per event per day (for
example ``market-open:2026-10-22`` or ``signal-buy:2026-10-22``). Before
posting, the existing comments are searched for that exact marker line;
a found marker means the notification already went out and the call is a
no-op. Late or second arrivals (a GitHub cron that fires twice, the band
loop and the market job arriving at the same minute) therefore send
exactly one email, without any stored state and without inventing one.

Nothing here waits on a clock, nothing rewords the text it is given,
and every failure is reported and never hides the delivery state.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPO = "muhammadrehanqureshi/quant-of-rehan"
ISSUE_TITLE_PREFIX = "Quant of Rehan - owner email"
API_BASE = "https://api.github.com"
TIMEOUT_S = 30.0
MAX_COMMENT_PAGES = 5

ENV_DOCS_ISSUE = "OWNER_EMAIL_ISSUE"


def token() -> str:
    """The Actions token for one run, or a working PAT for manual calls."""
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise RuntimeError(
        "github token missing: Actions supplies GITHUB_TOKEN in the job")


def repository() -> str:
    """owner/name from the workflow's own env, else the known repo."""
    return os.environ.get("GH_REPOSITORY", "").strip() or DEFAULT_REPO


def owner_email_issue() -> str:
    """The watched issue's number: the env var first, then a title search."""
    named = os.environ.get(ENV_DOCS_ISSUE, "").strip()
    if named:
        return named
    response = requests.get(
        f"{API_BASE}/repos/{repository()}/issues",
        params={"state": "all", "per_page": 100},
        headers=_headers(), timeout=TIMEOUT_S,
    )
    response.raise_for_status()
    for issue in response.json():
        if issue.get("title", "").startswith(ISSUE_TITLE_PREFIX):
            return str(issue["number"])
    raise RuntimeError(
        f"no watched issue found: open one titled "
        f"'{ISSUE_TITLE_PREFIX} ...' or set {ENV_DOCS_ISSUE}")


def _headers() -> dict:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token()}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _comment_pages(issue_no: str):
    """Yield every comment body on the watched issue, newest page first."""
    for page in range(1, MAX_COMMENT_PAGES + 1):
        response = requests.get(
            f"{API_BASE}/repos/{repository()}/issues/{issue_no}/comments",
            params={"per_page": "100", "page": str(page)},
            headers=_headers(), timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return
        for row in rows:
            yield str(row.get("body", ""))


def already_sent(issue_no: str, marker: str) -> bool:
    """True when a comment on the issue already carries this marker."""
    needle = f"owner-email: {marker}"
    for body in _comment_pages(issue_no):
        if needle in body:
            return True
    return False


MARKER_PATTERN = re.compile(r"^owner-email: (\S+)$", re.MULTILINE)


def sent_markers() -> set[str]:
    """Every marker the watched issue already carries, newest page first.

    The catch-up backstop reads the whole day's ledger in one pass so a
    single fire can price every event against the same set; `send()`
    still does its own already-sent check before posting, so this set is
    only ever an optimisation and never the guarantee.
    """
    markers: set[str] = set()
    for body in _comment_pages(owner_email_issue()):
        markers.update(MARKER_PATTERN.findall(body))
    return markers


def send(text: str, marker: str) -> bool:
    """Email one notification. Returns True only when the comment landed.

    The marker line means exactly-once across fires and across callers.
    The text itself is never edited, never prefixed, never reworded: the
    comment body is the marker line, a blank line and the text as given.
    """
    if not marker or not marker.strip() or len(marker.splitlines()) != 1:
        raise ValueError(f"unusable owner-email marker: {marker!r}")
    issue_no = owner_email_issue()
    if already_sent(issue_no, marker.strip()):
        print(f"owner email: '{marker}' already delivered; not resent")
        return False
    body = f"owner-email: {marker.strip()}\n\n{text}"
    response = requests.post(
        f"{API_BASE}/repos/{repository()}/issues/{issue_no}/comments",
        json={"body": body},
        headers=_headers(), timeout=TIMEOUT_S,
    )
    response.raise_for_status()
    return response.status_code in (200, 201)


def main(argv: list[str] | None = None) -> int:
    """Manual send: python -m src.notify.owner_email --marker m --text-file f"""
    import argparse

    parser = argparse.ArgumentParser(
        description="email one notification to the owner's watched issue")
    parser.add_argument("--marker", required=True,
                        help="one line, one event per day key")
    parser.add_argument("--text-file",
                        help="the exact notification text; - reads stdin")
    parser.add_argument("--text", help="the exact notification text inline")
    args = parser.parse_args(argv)
    source = args.text_file or "--"
    if args.text is not None:
        text = args.text
    elif source == "-":
        text = sys.stdin.read()
    elif source != "--":
        text = Path(source).read_text(encoding="utf-8").rstrip("\n")
    else:
        raise SystemExit("--text or --text-file is required")
    ok = send(text, args.marker)
    return 0 if ok is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
