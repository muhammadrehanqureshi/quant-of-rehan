"""
Tests for signal delivery (src/notify.py).

Covers: event extraction from the decision log + book, BUY/EXIT
formatting, SIGNALS.md rendering, dedup ledger round-trip, and that a
second deliver() run never re-sends (idempotence).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import notify


# --------------------------------------------------------------------------
# notify: event extraction
# --------------------------------------------------------------------------

@pytest.fixture()
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "ROOT", tmp_path)
    monkeypatch.setattr(notify, "NOTIFIED_PATH", tmp_path / "data" / "notified.json")
    monkeypatch.setattr(notify, "SIGNALS_PATH", tmp_path / "SIGNALS.md")
    monkeypatch.setattr(notify, "DECISIONS_LOG", tmp_path / "logs" / "decisions.jsonl")
    monkeypatch.setattr(notify, "PORTFOLIO_PATH", tmp_path / "data" / "portfolio.json")
    return tmp_path


def _write_decision_log(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def _write_book(path, positions):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(positions), encoding="utf-8")


def test_collect_events_finds_enter_and_exit(isolated_paths):
    # A live BUY: today's decision row with the book holding the
    # position OPEN right now (the v3.0.0 law - OPEN-now is the only
    # local vouch, and the row must be from the current trading day).
    now_iso = datetime.now(timezone.utc).isoformat()
    _write_decision_log(
        isolated_paths / "logs" / "decisions.jsonl",
        [
            {"action": "STAND_ASIDE", "reason": "no edge", "timestamp": "2026-09-15T04:00:00+00:00"},
            {
                "action": "ENTER",
                "symbol": "KEL",
                "price": 6.67,
                "profit_target_price": 6.80,
                "profit_target_pct": 2.0,
                "quantity": 1500,
                "score": 0.55,
                "timestamp": now_iso,
            },
        ],
    )
    _write_book(
        isolated_paths / "data" / "portfolio.json",
        [
            {
                "symbol": "KEL",
                "status": "OPEN",
                "entry_price": 6.67,
                "entry_date": datetime.now(timezone.utc).astimezone(notify.PKT).date().isoformat(),
            },
        ],
    )
    events = notify.collect_events()
    kinds = {(e["kind"], e["fields"].get("symbol")) for e in events}
    assert ("BUY", "KEL") in kinds
    # STAND_ASIDE must never become an event; OPEN positions are not exits.
    assert len(events) == 1


def test_buy_without_book_truth_is_a_zombie_never_delivered(isolated_paths):
    """The Sep-22 KEL card, reproduced: a decision row whose numbers come
    from a CLOSED, six-day-old book position. No OPEN row vouches for it
    and its entry date is not today - it must produce no BUY event."""
    _write_decision_log(
        isolated_paths / "logs" / "decisions.jsonl",
        [
            {
                "action": "ENTER",
                "symbol": "KEL",
                "price": 6.67,
                "profit_target_price": 6.80,
                "quantity": 14950,
                "score": 0.511,
                "timestamp": "2026-09-22T09:12:00+00:00",
            },
        ],
    )
    _write_book(
        isolated_paths / "data" / "portfolio.json",
        [
            {
                "symbol": "KEL",
                "status": "CLOSED",
                "entry_price": 6.67,
                "entry_date": "2026-09-15",
                "exit_date": "2026-09-15",
                "exit_price": 6.62,
            },
        ],
    )
    events = notify.collect_events()
    assert [e for e in events if e["kind"] == "BUY"] == []


def test_same_day_closed_row_never_vouches_a_buy(isolated_paths):
    """The Sep-23 09:19 UTC zombie shape: the decision row is from TODAY
    (fresh timestamp), so the today-only seal passes it - but the close-
    out already flipped the book row to CLOSED before the delivery ran.
    Under the old 'entry_date == today also vouches' rule the dead card
    delivered; under the OPEN-now law it must not."""
    fresh_ts = datetime.now(timezone.utc).isoformat()
    _write_decision_log(
        isolated_paths / "logs" / "decisions.jsonl",
        [
            {
                "action": "ENTER",
                "symbol": "KEL",
                "price": 6.67,
                "profit_target_price": 6.80,
                "quantity": 14950,
                "score": 0.511,
                "timestamp": fresh_ts,
            },
        ],
    )
    _write_book(
        isolated_paths / "data" / "portfolio.json",
        [
            {
                "symbol": "KEL",
                "status": "CLOSED",
                "entry_price": 6.67,
                "entry_date": datetime.now(timezone.utc)
                .astimezone(notify.PKT)
                .date()
                .isoformat(),
                "exit_date": datetime.now(timezone.utc)
                .astimezone(notify.PKT)
                .date()
                .isoformat(),
                "exit_reason": "End of session (cloud close)",
            },
        ],
    )
    events = notify.collect_events()
    assert [e for e in events if e["kind"] == "BUY"] == []


def test_github_book_truth_outranks_a_stale_local_book(isolated_paths, monkeypatch):
    """A OneDrive-stale local book still lists KEL OPEN, but the committed
    GitHub book says CLOSED: delivery must trust GitHub and refuse the
    zombie. (The Sep-23 card was exactly this - a local pass vouching a
    position the rest of the world had already closed.)"""
    fresh_ts = datetime.now(timezone.utc).isoformat()
    _write_decision_log(
        isolated_paths / "logs" / "decisions.jsonl",
        [
            {
                "action": "ENTER",
                "symbol": "KEL",
                "price": 6.67,
                "profit_target_price": 6.80,
                "quantity": 14950,
                "score": 0.511,
                "timestamp": fresh_ts,
            },
        ],
    )
    _write_book(
        isolated_paths / "data" / "portfolio.json",
        [
            {"symbol": "KEL", "status": "OPEN", "entry_price": 6.67},
        ],
    )
    # GitHub answers: the committed book holds the position CLOSED.
    monkeypatch.setattr(
        notify,
        "_github_book_keys",
        lambda repo, token: (set(), True),
    )
    events = notify.collect_events("o/r", "tok")
    assert [e for e in events if e["kind"] == "BUY"] == []


def test_github_unreachable_falls_back_to_local_book(isolated_paths, monkeypatch):
    """Offline (GitHub API down, no token): the local book remains the
    only witness - an OPEN local row still vouches today's BUY so a
    GitHub outage cannot silence a real signal."""
    fresh_ts = datetime.now(timezone.utc).isoformat()
    _write_decision_log(
        isolated_paths / "logs" / "decisions.jsonl",
        [
            {
                "action": "ENTER",
                "symbol": "KEL",
                "price": 6.67,
                "profit_target_price": 6.80,
                "quantity": 14950,
                "score": 0.511,
                "timestamp": fresh_ts,
            },
        ],
    )
    _write_book(
        isolated_paths / "data" / "portfolio.json",
        [
            {"symbol": "KEL", "status": "OPEN", "entry_price": 6.67},
        ],
    )
    monkeypatch.setattr(
        notify, "_github_book_keys", lambda repo, token: (set(), False)
    )
    events = notify.collect_events("", "")
    buys = [e for e in events if e["kind"] == "BUY"]
    assert len(buys) == 1


def test_deliver_passes_credentials_into_collection(isolated_paths, monkeypatch):
    """deliver() must hand its repo/token to collect_events so the GitHub
    book-truth check actually runs in production (the Sep-23 zombie was
    deliverable partly because collection never saw the credentials)."""
    seen = {}

    def fake_collect(repo, token):
        seen["repo"], seen["token"] = repo, token
        return []

    monkeypatch.setattr(notify, "collect_events", fake_collect)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    notify.deliver("muhammadrehanqureshi/the-sentinel", "tok123")
    assert seen == {
        "repo": "muhammadrehanqureshi/the-sentinel",
        "token": "tok123",
    }


def test_format_buy_contains_trade_facts(isolated_paths):
    event = {
        "kind": "BUY",
        "fields": {
            "symbol": "KEL",
            "price": 6.67,
            "profit_target_price": 6.80,
            "profit_target_pct": 2.0,
            "quantity": 1500,
            "score": 0.55,
            "timestamp": "2026-09-15T05:35:42+00:00",
        },
    }
    text = notify.format_event(event)
    assert "BUY KEL" in text
    assert "6.67" in text and "6.8" in text
    assert "not an order" in text


def test_format_exit_shows_result(isolated_paths):
    event = {
        "kind": "EXIT",
        "fields": {
            "symbol": "CNERGY",
            "entry_price": 12.88,
            "exit_price": 12.62,
            "pnl_pct": -2.02,
            "exit_reason": "stop",
            "exit_date": "2026-09-15",
        },
    }
    text = notify.format_event(event)
    assert "EXIT CNERGY" in text
    assert "-2.02%" in text


# --------------------------------------------------------------------------
# notify: dedup ledger + idempotence
# --------------------------------------------------------------------------

def test_second_deliver_never_resends(isolated_paths, monkeypatch):
    # Fresh event: the staleness guard seals BUYs older than 20 minutes
    # (the Sep-21 zombie), so the dedup test must exercise a live one.
    from datetime import datetime, timezone

    fresh_ts = datetime.now(timezone.utc).isoformat()
    _write_decision_log(
        isolated_paths / "logs" / "decisions.jsonl",
        [
            {
                "action": "ENTER",
                "symbol": "KEL",
                "price": 6.67,
                "profit_target_price": 6.8,
                "quantity": 14950,
                "score": 0.511,
                "timestamp": fresh_ts,
            }
        ],
    )
    # The book-truth gate demands a matching OPEN row (today's entry).
    _write_book(
        isolated_paths / "data" / "portfolio.json",
        [
            {
                "symbol": "KEL",
                "status": "OPEN",
                "entry_price": 6.67,
                "entry_date": datetime.now(timezone.utc)
                .astimezone(notify.PKT)
                .date()
                .isoformat(),
            }
        ],
    )
    sent = []

    def fake_api(url, token, payload, method="POST"):
        sent.append(payload["body"] if payload else None)
        return 201, {"number": 1}

    monkeypatch.setattr(notify, "_api", fake_api)
    monkeypatch.setattr(notify, "ensure_issue", lambda repo, token: 7)

    first = notify.deliver("o/r", "tok")
    assert first["sent"] == 1 and len(sent) == 1

    second = notify.deliver("o/r", "tok")
    assert second["sent"] == 0 and second["pending"] == 0
    assert len(sent) == 1  # no duplicate comment


def test_signals_md_lists_todays_events(isolated_paths, monkeypatch):
    # The log page lists TODAY's signals - build the fake event at the
    # real current date so the test cannot rot at midnight (it did:
    # hardcoded 2026-09-15 started failing the next morning).
    from datetime import datetime, timezone

    today_ts = datetime.now(timezone.utc).isoformat()
    _write_decision_log(
        isolated_paths / "logs" / "decisions.jsonl",
        [
            {
                "action": "ENTER",
                "symbol": "KEL",
                "price": 6.67,
                "profit_target_price": 6.8,
                "quantity": 14950,
                "score": 0.511,
                "timestamp": today_ts,
            }
        ],
    )
    _write_book(
        isolated_paths / "data" / "portfolio.json",
        [
            {
                "symbol": "KEL",
                "status": "OPEN",
                "entry_price": 6.67,
                "entry_date": datetime.now(timezone.utc)
                .astimezone(notify.PKT)
                .date()
                .isoformat(),
            }
        ],
    )
    # deliver() renders and writes SIGNALS.md even with no credentials.
    notify.deliver("", "", dry_run=True)
    events = notify.collect_events()
    md = notify.render_signals_md(events, notify._load_notified())
    assert "KEL" in md and "BUY" in md
    assert (isolated_paths / "SIGNALS.md").exists()


def test_status_md_renders_liveness_and_ledger(isolated_paths, monkeypatch):
    # STATUS.md must answer "is the bot working?" at a glance: alive +
    # latest decision + the open book + the running win rate.
    now = datetime.now(timezone.utc)
    (isolated_paths / "data").mkdir(exist_ok=True)
    (isolated_paths / "data" / "heartbeat.json").write_text(
        json.dumps({"utc": now.isoformat(), "source": "cloud_bot"}),
        encoding="utf-8",
    )
    (isolated_paths / "data" / "portfolio.json").write_text(
        json.dumps(
            [
                {
                    "symbol": "KEL",
                    "status": "open",
                    "entry_price": 6.67,
                    "target_price": 6.80,
                    "trailing_stop_price": 6.60,
                },
                {"symbol": "OLD1", "status": "profit", "pnl_pct": 2.1},
                {"symbol": "OLD2", "status": "stop", "pnl_pct": -1.4},
                {"symbol": "OLD3", "status": "profit", "pnl_pct": 0.8},
            ]
        ),
        encoding="utf-8",
    )
    (isolated_paths / "logs").mkdir(exist_ok=True)
    (isolated_paths / "logs" / "decisions.jsonl").write_text(
        json.dumps(
            {
                "timestamp": now.isoformat(),
                "action": "STAND_ASIDE",
                "reason": "Rule 11: index below its 20-session average",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    page = notify.render_status_md(now=now)
    assert "✅ alive" in page
    assert "STAND_ASIDE" in page
    assert "KEL" in page
    assert "67%" in page  # 2 of 3 closed trades won
    assert "book is flat" not in page


def test_status_md_survives_empty_repo(isolated_paths):
    # A bare checkout: no heartbeat, no book, no decisions. The page
    # must still render - warnings and dashes, never an exception.
    page = notify.render_status_md()
    assert "no heartbeat recorded yet" in page

