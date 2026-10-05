"""
Tests for the private web console.

The console's contract:
  * every route requires the token - no token, 401, no exceptions;
  * state reports the bot's liveness from the managed process handle;
  * start spawns `live.py` as a child with the requested decide interval
    (mocked here - no real process);
  * stop writes the cooperative stop file, waits, and cleans up;
  * stop with no managed bot still writes the stop file, so a bot
    started from a terminal is also reachable;
  * the interval is clamped to 30-300s regardless of client input.

Flask is imported with a test client; paths are redirected at tmp_path
via the standard monkeypatch so no test touches real data/logs.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("flask")

import web_console as wc


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect every file path the console uses into tmp_path."""
    data = tmp_path / "data"
    logs = tmp_path / "logs"
    data.mkdir()
    logs.mkdir()
    monkeypatch.setattr(wc.paths, "DATA_DIR", data)
    monkeypatch.setattr(wc, "TOKEN_FILE", data / "web_token.txt")
    monkeypatch.setattr(wc, "PID_FILE", data / "web_bot.pid")
    monkeypatch.setattr(wc, "STOP_FILE", logs / "bot.stop")
    monkeypatch.setattr(wc.paths, "LOGS_DIR", logs)
    # Fresh module state per test.
    monkeypatch.setattr(wc, "_PROCESS", None)
    monkeypatch.setattr(wc, "_PROC_INFO", {})
    wc.LINE_BUFFER.clear()
    client = wc.app.test_client()
    return SimpleNamespace(client=client, data=data, logs=logs, token=wc.TOKEN)


class TestAuth:
    def test_no_token_is_401(self, isolated):
        r = isolated.client.get("/api/state")
        assert r.status_code == 401

    def test_wrong_token_is_401(self, isolated):
        r = isolated.client.get("/api/state?token=nope")
        assert r.status_code == 401

    def test_header_token_ok(self, isolated):
        r = isolated.client.get(
            "/api/state", headers={"X-Sentinel-Token": isolated.token}
        )
        assert r.status_code == 200

    def test_query_token_ok(self, isolated):
        r = isolated.client.get(f"/api/state?token={isolated.token}")
        assert r.status_code == 200

    def test_index_also_protected(self, isolated):
        assert isolated.client.get("/").status_code == 401
        r = isolated.client.get(f"/?token={isolated.token}")
        assert r.status_code == 200
        assert "The Sentinel" in r.get_data(as_text=True)


class TestState:
    def test_state_when_idle(self, isolated):
        body = json.loads(
            isolated.client.get(
                f"/api/state?token={isolated.token}"
            ).get_data(as_text=True)
        )
        assert body["running"] is False
        assert body["lines"] == []
        assert "summary" in body and "decisions" in body

    def test_summary_counts_labels(self, isolated, monkeypatch):
        rows = [
            {"symbol": "A", "label": 1, "pnl_pct": 2.0},
            {"symbol": "B", "label": 0, "pnl_pct": -2.0},
            {"symbol": "C", "label": None, "pnl_pct": None},
        ]
        text = "\n".join(json.dumps(r) for r in rows) + "\n"
        (isolated.data / "outcomes.jsonl").write_text(text, encoding="utf-8")
        body = json.loads(
            isolated.client.get(
                f"/api/state?token={isolated.token}"
            ).get_data(as_text=True)
        )
        s = body["summary"]
        assert s["trades"] == 3
        assert s["wins"] == 1 and s["losses"] == 1
        assert s["win_rate"] == 0.5
        assert s["total_pnl_pct"] == 0.0


class TestStartStop:
    def test_start_spawns_child_with_interval(self, isolated, monkeypatch):
        captured = {}

        class FakeProc:
            pid = 4242
            def __init__(self):
                self.stdout = []
                self.poll = lambda: None
            def wait(self, timeout=None):
                return 0
            def terminate(self):
                pass
            def kill(self):
                pass

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return FakeProc()

        monkeypatch.setattr(wc.subprocess, "Popen", fake_popen)
        r = isolated.client.post(
            f"/api/start?token={isolated.token}",
            json={"decide_interval": 120},
        )
        body = json.loads(r.get_data(as_text=True))
        assert body["ok"] is True
        assert "--decide-interval" in captured["cmd"]
        assert captured["cmd"][captured["cmd"].index("--decide-interval") + 1] == "120"
        assert (isolated.data / "web_bot.pid").exists()

    def test_interval_clamped(self, isolated, monkeypatch):
        seen = {}

        class FakeProc:
            pid = 1
            stdout = []
            poll = lambda self: None
            def wait(self, timeout=None): return 0
            def terminate(self): pass
            def kill(self): pass

        monkeypatch.setattr(wc.subprocess, "Popen",
                            lambda cmd, **kw: seen.update(cmd=cmd) or FakeProc())
        isolated.client.post(
            f"/api/start?token={isolated.token}",
            json={"decide_interval": 5},
        )
        # 5s is below the 30s floor -> clamped up to 30.
        assert seen["cmd"][seen["cmd"].index("--decide-interval") + 1] == "30"

    def test_double_start_rejected(self, isolated, monkeypatch):
        class FakeProc:
            pid = 1
            stdout = []
            poll = lambda self: None

        monkeypatch.setattr(wc.subprocess, "Popen", lambda cmd, **kw: FakeProc())
        r1 = isolated.client.post(f"/api/start?token={isolated.token}", json={})
        r2 = isolated.client.post(f"/api/start?token={isolated.token}", json={})
        assert json.loads(r1.get_data(as_text=True))["ok"] is True
        assert r2.status_code == 409

    def test_stop_writes_file_and_cleans_up(self, isolated, monkeypatch):
        class FakeProc:
            pid = 7
            stdout = []
            poll = lambda self: None
            def wait(self, timeout=None): return 0
            def terminate(self): pass
            def kill(self): pass

        monkeypatch.setattr(wc.subprocess, "Popen", lambda cmd, **kw: FakeProc())
        isolated.client.post(f"/api/start?token={isolated.token}", json={})
        r = isolated.client.post(f"/api/stop?token={isolated.token}", json={})
        body = json.loads(r.get_data(as_text=True))
        assert body["ok"] is True
        # Stop is asynchronous (2026-09-14: a synchronous 90s wait froze
        # the page). The worker thread cleans up; wait for it to finish.
        import time as _time
        for _ in range(100):
            if not (isolated.data / "web_bot.pid").exists():
                break
            _time.sleep(0.05)
        assert not (isolated.data / "web_bot.pid").exists()
        # The stop file is consumed/cleaned by the console after a
        # managed stop completes.
        assert not (isolated.logs / "bot.stop").exists()

    def test_stop_without_bot_still_writes_file(self, isolated):
        # A bot started from a terminal is not managed here, but the
        # stop file reaches it all the same - and persists for it.
        r = isolated.client.post(f"/api/stop?token={isolated.token}", json={})
        body = json.loads(r.get_data(as_text=True))
        assert body["ok"] is True
        assert (isolated.logs / "bot.stop").exists()
