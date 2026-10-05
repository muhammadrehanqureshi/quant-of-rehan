"""
THE SENTINEL (PSX KMIALL) - private web console.

What this is
------------
A single-user, localhost-only control panel for the live bot. Start the
bot from the browser, watch its trade calls stream in, stop it without
touching a terminal - and never see the machine struggle, because the
decide cadence is configurable from here.

Why a child process, not an in-process thread
---------------------------------------------
The bot is a pipeline of module-level state (entry gate, portfolio
ledger, loggers). Running it inside the web server process would couple
two lifecycles that must stay independent: a crash in the bot must not
take the console down, and "stop the bot" must stop the bot, not the
web server. So the console spawns `python src/live.py` as a detached
child and manages its lifetime.

Security model
--------------
Binds to 127.0.0.1 only - nothing outside this machine can reach it.
An access token (auto-generated on first run, stored in
data/web_token.txt) is required on every request, so another local user
or process cannot drive the bot. This is a single-user console by
design, not a multi-user web app.

Usage
-----
    .venv/Scripts/python.exe src/web_console.py
    then open the printed URL. The token is in the URL on first launch,
    or in data/web_token.txt.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

from psx_core import paths

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

app = Flask(__name__)

BOT_SCRIPT = paths.PROJECT_ROOT / "src" / "live.py"
STOP_FILE = paths.LOGS_DIR / "bot.stop"
TOKEN_FILE = paths.DATA_DIR / "web_token.txt"
PID_FILE = paths.DATA_DIR / "web_bot.pid"

# Ring buffer of the bot's console lines, filled by a reader thread.
LINE_BUFFER: deque[str] = deque(maxlen=500)
_BUFFER_LOCK = threading.Lock()

_PROCESS: subprocess.Popen | None = None
_PROCESS_LOCK = threading.Lock()
_PROC_INFO: dict = {}  # started_at, decide_interval, python exe


def _now_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")


def _log_line(text: str) -> None:
    with _BUFFER_LOCK:
        LINE_BUFFER.append(f"{_now_str()}  {text}")


# ---------------------------------------------------------------------------
# Token: single-user access control
# ---------------------------------------------------------------------------

def _load_or_create_token() -> str:
    """A random token per installation, regenerated if missing."""
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(24)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


TOKEN = _load_or_create_token()


@app.before_request
def _check_token():
    """Every route requires the token - header, query param, or form."""
    supplied = (
        request.headers.get("X-Sentinel-Token")
        or request.args.get("token")
        or (request.form.get("token") if request.form else None)
    )
    if supplied != TOKEN:
        return jsonify(error="unauthorized"), 401
    return None


# ---------------------------------------------------------------------------
# Bot process management
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    """Is a process with this PID alive? No external dependencies."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if h:
                k.CloseHandle(h)
                return True
            return False
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_from_file() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _bot_running() -> bool:
    with _PROCESS_LOCK:
        if _PROCESS is not None and _PROCESS.poll() is None:
            return True
    # Adopt a bot started outside this console (start_live.bat, or a
    # console that died while its bot lived on): the PID file is the
    # shared truth. 2026-09-14: a manual restart while the console was
    # mid-stop produced TWO bots fighting over one portfolio book.
    pid = _pid_from_file()
    return _pid_alive(pid) if pid else False


def _reader(proc: subprocess.Popen) -> None:
    """Pump the child's stdout into the ring buffer (one line per poll)."""
    try:
        for raw in iter(proc.stdout.readline, ""):
            line = raw.rstrip("\n\r")
            if line:
                with _BUFFER_LOCK:
                    LINE_BUFFER.append(line)
    except Exception:
        pass


def _sync_before_start() -> str | None:
    """Pull the cloud bookkeeping commits before spawning the bot.

    The cloud close-out pushes commits every evening; when this machine
    comes back online, its checkout is behind and the next local commit
    would conflict. Syncing BEFORE start keeps the book straight. Any
    failure is reported but never blocks the start (offline trading is
    better than no trading); a dirty tree is left alone.
    """
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(paths.PROJECT_ROOT), capture_output=True, text=True,
            timeout=20,
        )
        if r.returncode != 0 or r.stdout.strip():
            return "sync skipped: local changes present (uncommitted)"
        r = subprocess.run(
            ["git", "pull", "--rebase", "--autostash", "origin", "master"],
            cwd=str(paths.PROJECT_ROOT), capture_output=True, text=True,
            timeout=120,
        )
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0:
            if "Already up to date" in out or "Current branch" in out:
                return "sync: already up to date"
            return f"sync: pulled cloud updates ({out.strip()[:120]})"
        return f"sync FAILED (bot starting anyway): {out.strip()[:150]}"
    except Exception as exc:  # noqa: BLE001
        return f"sync skipped ({exc}) - bot starting anyway"


def _start_bot(decide_interval: float) -> tuple[bool, str]:
    global _PROCESS, _PROC_INFO
    if _bot_running():
        return False, "Bot is already running."
    if STOP_FILE.exists():
        STOP_FILE.unlink(missing_ok=True)
    _log_line(_sync_before_start())
    python = sys.executable
    cmd = [
        python, str(BOT_SCRIPT),
        "--decide-interval", f"{decide_interval:g}",
    ]
    LINE_BUFFER.clear()
    _log_line(f"Starting The Sentinel (decide every {decide_interval:.0f}s)...")
    # BELOW_NORMAL_PRIORITY_CLASS at creation: the market-watching bot
    # must never outrank the owner's desktop (2026-09-14).
    creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if os.name == "nt":
        creation |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)
    proc = subprocess.Popen(
        cmd,
        cwd=str(paths.PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creation,
    )
    with _PROCESS_LOCK:
        _PROCESS = proc
        _PROC_INFO = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "decide_interval": decide_interval,
            "pid": proc.pid,
            "python": python,
        }
    threading.Thread(target=_reader, args=(proc,), daemon=True).start()
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    return True, f"Bot started (PID {proc.pid})."


def _stop_bot() -> tuple[bool, str]:
    global _PROCESS
    if not _bot_running():
        # A bot started outside the console may still be alive - the
        # stop file reaches it too (it checks every loop pass).
        STOP_FILE.touch()
        return True, "No console-managed bot running; stop file written."
    STOP_FILE.touch()
    with _PROCESS_LOCK:
        proc = _PROCESS
        adopted_pid = None if proc else _pid_from_file()
    _log_line("Stop requested - the bot exits after its current cycle...")

    def _finish_cleanup() -> None:
        with _PROCESS_LOCK:
            _PROCESS = None
        STOP_FILE.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
        _log_line("Bot stopped.")

    def _stop_worker() -> None:
        try:
            if proc is not None:
                proc.wait(timeout=90)
                _log_line("Bot stopped cleanly.")
            elif adopted_pid:
                # A bot we did not spawn: cooperate first, then escalate.
                for _ in range(90):
                    if not _pid_alive(adopted_pid):
                        break
                    time.sleep(1)
                if _pid_alive(adopted_pid):
                    _log_line("Graceful window elapsed - terminating.")
                    try:
                        subprocess.run(
                            ["taskkill", "/PID", str(adopted_pid)],
                            capture_output=True, timeout=15, check=False,
                        )
                        for _ in range(15):
                            if not _pid_alive(adopted_pid):
                                break
                            time.sleep(1)
                    except Exception:  # noqa: BLE001
                        pass
                    if _pid_alive(adopted_pid):
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(adopted_pid)],
                            capture_output=True, timeout=15, check=False,
                        )
                        _log_line("Bot killed.")
                    else:
                        _log_line("Bot stopped.")
            else:
                _log_line("No bot found; stop file written anyway.")
        except Exception as exc:  # noqa: BLE001
            _log_line(f"Stop worker error: {exc}")
        finally:
            _finish_cleanup()

    # Run the wait in the background: the HTTP reply returns instantly,
    # the page stays responsive, and the dashboard reflects progress.
    threading.Thread(target=_stop_worker, daemon=True).start()
    return True, "Stop requested - the bot exits within a minute."


# ---------------------------------------------------------------------------
# Read-only data for the dashboard
# ---------------------------------------------------------------------------

def _outcomes() -> list[dict]:
    f = paths.DATA_DIR / "outcomes.jsonl"
    if not f.exists():
        return []
    rows = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-50:]


def _summary() -> dict:
    rows = _outcomes()
    labeled = [r for r in rows if r.get("label") is not None]
    wins = sum(1 for r in labeled if r.get("label") == 1)
    losses = len(labeled) - wins
    total_pct = sum(float(r.get("pnl_pct") or 0.0) for r in labeled)
    return {
        "trades": len(rows),
        "labeled": len(labeled),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(labeled), 3) if labeled else None,
        "total_pnl_pct": round(total_pct, 2),
    }


def _latest_decisions(n: int = 8) -> list[dict]:
    f = paths.LOGS_DIR / "decisions.jsonl"
    if not f.exists():
        return []
    rows = []
    for line in f.read_text(encoding="utf-8").splitlines()[-400:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-n:]


# ---------------------------------------------------------------------------
# API + page
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    """The single-page console. Token goes into localStorage on load."""
    page = (paths.PROJECT_ROOT / "src" / "web_console_page.html").read_text(
        encoding="utf-8"
    )
    return page


@app.get("/api/state")
def api_state():
    with _BUFFER_LOCK:
        lines = list(LINE_BUFFER)[-120:]
    return jsonify(
        running=_bot_running(),
        proc={k: v for k, v in _PROC_INFO.items() if k != "python"},
        lines=lines,
        summary=_summary(),
        decisions=_latest_decisions(),
        market_open=_market_open_now(),
    )


def _market_open_now() -> bool:
    try:
        from psx_core import sessions
        return bool(sessions.is_open(datetime.now(timezone.utc)))
    except Exception:
        return False


@app.post("/api/start")
def api_start():
    body = request.get_json(silent=True) or {}
    try:
        interval = float(body.get("decide_interval", 60))
    except (TypeError, ValueError):
        interval = 60.0
    interval = min(300.0, max(30.0, interval))  # sane bounds
    ok, msg = _start_bot(interval)
    return jsonify(ok=ok, message=msg), (200 if ok else 409)


@app.post("/api/stop")
def api_stop():
    ok, msg = _stop_bot()
    return jsonify(ok=ok, message=msg)


_CONSOLE_LOCK_HANDLE = None


def _acquire_console_lock() -> bool:
    """Claim exclusive right to run the web console. False if one exists.

    Companion to the bot's own instance lock (2026-09-14): two consoles
    both bound port 8785 and each spawned a bot - four processes, two
    stacks, duplicated CPU. A second console must fail loudly instead.
    """
    global _CONSOLE_LOCK_HANDLE
    try:
        handle = open(paths.DATA_DIR / "console_instance.lock", "a")
    except OSError:
        return False
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError):
        handle.close()
        return False
    _CONSOLE_LOCK_HANDLE = handle
    return True


def main() -> int:
    paths.enable_utf8_stdout()
    paths.ensure_dirs()
    if not _acquire_console_lock():
        print(
            "The Sentinel console is already running - refusing to start "
            "a second console. Open the existing one in your browser "
            "(http://127.0.0.1:8785).",
            flush=True,
        )
        return 3
    port = 8785
    print("=" * 64)
    print("THE SENTINEL - private web console")
    print("=" * 64)
    print(f"Open:  http://127.0.0.1:{port}/?token={TOKEN}")
    print(f"Token: {TOKEN}   (also saved in {TOKEN_FILE.name})")
    print("Local machine only - nothing outside this PC can reach it.")
    print("=" * 64)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
