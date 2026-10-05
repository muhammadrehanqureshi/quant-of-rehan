"""
Tests for the Ctrl+C handling in the live runner.

Covers `live._request_stop`:
  * first Ctrl+C with "y"  -> graceful stop flag set;
  * first Ctrl+C with ""/n -> bot continues (no flag);
  * second Ctrl+C while a graceful stop is pending -> KeyboardInterrupt;
  * second Ctrl+C while the Y/N prompt is open -> KeyboardInterrupt;
  * non-interactive stdin (EOFError) -> treated as confirmed (graceful);
  * `main` maps a force-quit KeyboardInterrupt to exit code 130.
"""

from __future__ import annotations

import builtins
import pytest

import live


@pytest.fixture(autouse=True)
def _reset_stop_flags():
    """Each test starts from a clean stop state."""
    live._STOP_REQUESTED = False
    live._CONFIRM_PENDING = False
    yield
    live._STOP_REQUESTED = False
    live._CONFIRM_PENDING = False


def _press(answer: str | None, stdin_error: Exception | None = None) -> None:
    """Simulate one SIGINT with a mocked interactive prompt."""

    def _input(prompt: str = "") -> str:
        if stdin_error is not None:
            raise stdin_error
        if answer is None:
            raise EOFError
        return answer

    real_input = builtins.input
    builtins.input = _input  # type: ignore[assignment]
    try:
        live._request_stop(2, None)  # 2 = SIGINT, frame unused
    finally:
        builtins.input = real_input  # type: ignore[assignment]


def test_first_ctrl_c_y_requests_graceful_stop(capsys):
    _press("y")
    assert live._STOP_REQUESTED is True
    assert live._CONFIRM_PENDING is False
    out = capsys.readouterr().out
    # Note: input() writes its prompt to the real console (C level), so
    # the question itself never appears in capsys - assert on the
    # handler's own prints instead.
    assert "Stopping after the current step" in out


def test_first_ctrl_c_n_continues(capsys):
    _press("n")
    assert live._STOP_REQUESTED is False
    assert "Continuing." in capsys.readouterr().out


def test_first_ctrl_c_empty_declines(capsys):
    # Bare Enter on [y/N] means No - the bot keeps running.
    _press("")
    assert live._STOP_REQUESTED is False
    assert "Continuing." in capsys.readouterr().out


def test_second_ctrl_c_force_quits(capsys):
    _press("y")  # graceful stop pending
    with pytest.raises(KeyboardInterrupt):
        live._request_stop(2, None)  # second press: force quit now
    assert "Force quit." in capsys.readouterr().out


def test_ctrl_c_during_open_prompt_force_quits(capsys):
    # The prompt is open (user hasn't answered): a second SIGINT must
    # force-quit immediately instead of nesting another prompt.
    live._CONFIRM_PENDING = True
    with pytest.raises(KeyboardInterrupt):
        live._request_stop(2, None)
    assert "Force quit." in capsys.readouterr().out


def test_non_interactive_stdin_defaults_to_graceful_stop(capsys):
    _press(None, stdin_error=EOFError)
    assert live._STOP_REQUESTED is True


def test_main_maps_force_quit_to_exit_130(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "parse_args", lambda argv=None: types_namespace())
    monkeypatch.setattr(live.paths, "ensure_dirs", lambda: None)
    monkeypatch.setattr(live.paths, "enable_utf8_stdout", lambda: None)

    def _raise(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(live, "run_live", _raise)
    assert live.main([]) == 130


def types_namespace():
    import argparse

    return argparse.Namespace(
        ignore_schedule=False, dry_run=False, test=False,
        timeout=30.0, collect_interval=5.0, decide_interval=60.0,
    )
