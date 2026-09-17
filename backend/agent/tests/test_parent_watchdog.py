"""The agent must not outlive the desktop app that launched it.

A frozen agent is two processes, and the desktop app can only kill the outer
one — see `rest.exit_when_parent_closes`. These tests pin the replacement
signal: stdin closing. They run the real CLI in a subprocess, because the
thing under test is a process exiting, which cannot be observed in-process.

Both directions are checked. A test that only proves the agent exits would
also pass if it exited on *every* stdin close — including a developer's
terminal — so the opt-in side is asserted too.
"""

from __future__ import annotations

import io
import socket
import subprocess
import sys
import threading
import time

import pytest

from cropwatcher.api import rest

STARTUP_TIMEOUT_S = 20.0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"agent exited during startup with {process.returncode}")
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    pytest.fail(f"agent never opened port {port}")


def _start(port: int, *extra: str) -> subprocess.Popen:
    process = subprocess.Popen(
        [sys.executable, "-m", "cropwatcher.cli", "serve", "--port", str(port), *extra],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_for_port(port, process)
    return process


class TestExitWithParent:
    def test_exits_when_stdin_closes(self):
        port = _free_port()
        process = _start(port, "--exit-with-parent")
        try:
            assert process.stdin is not None
            process.stdin.close()  # what the parent dying looks like
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.kill()

    def test_keeps_running_without_the_flag(self):
        """Opt-in: `cropwatcher serve` from a shell must not die on stdin EOF."""
        port = _free_port()
        process = _start(port)
        try:
            assert process.stdin is not None
            process.stdin.close()
            time.sleep(1.5)
            assert process.poll() is None, "agent exited without --exit-with-parent"
        finally:
            process.kill()
            process.wait(timeout=10)


class TestSessionEndsOnParentLoss:
    def test_the_session_is_ended_before_exiting(self, monkeypatch):
        """This path can run mid-flight, so the drone is landed first."""
        import sys as real_sys

        events: list[str] = []
        exited = threading.Event()

        def fake_exit(code: int) -> None:
            events.append(f"exit:{code}")
            exited.set()

        monkeypatch.setattr(real_sys, "stdin", io.StringIO(""))     # immediate EOF
        monkeypatch.setattr(rest.os, "_exit", fake_exit)
        monkeypatch.setattr(rest.agent.session, "end",
                            lambda reason: events.append(f"end:{reason}"))

        rest.exit_when_parent_closes()

        assert exited.wait(timeout=5)
        assert events == ["end:the app closed", "exit:0"]
