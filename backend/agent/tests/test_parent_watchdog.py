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
import logging
import socket
import subprocess
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

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

        rest.exit_when_parent_closes(deadline_s=0.2)

        assert exited.wait(timeout=5)
        time.sleep(0.5)                  # past the deadline: it was disarmed
        assert events == ["end:the app closed", "exit:0"]


class TestShutdownIsBounded:
    """Closing the app must end the process even when the session will not end.

    Measured 2026-09-30: the watchdog fired, `session.end` blocked on a drone
    that had not answered for 3.7 h, and the agent held the radio for 9 h.
    """

    @pytest.fixture
    def hung_end(self, monkeypatch):
        """`session.end` blocks until released; `os._exit` is recorded instead.

        Never released on teardown: a released watchdog goes on to call
        `os._exit(0)`, and after monkeypatch undoes itself that is the real one
        — it would end the test run. The stuck thread is a daemon; leave it.
        """
        exits: list[int] = []
        exited = threading.Event()
        release = threading.Event()

        def fake_exit(code: int) -> None:
            exits.append(code)
            exited.set()

        monkeypatch.setattr(rest.os, "_exit", fake_exit)
        monkeypatch.setattr(rest.agent.session, "end", lambda reason: release.wait())
        return exits, exited, release

    def test_a_session_that_never_ends_still_exits(self, hung_end, monkeypatch):
        exits, exited, _ = hung_end
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))

        rest.exit_when_parent_closes(deadline_s=0.2)

        assert exited.wait(timeout=5), "the agent outlived its parent"
        assert exits == [1]              # forced, and the code says so

    def test_sigterm_is_bounded_too(self, hung_end, tmp_path, monkeypatch):
        """The lifespan shutdown calls the same `session.end`; serve arms it."""
        exits, _, release = hung_end
        monkeypatch.setenv("CROPWATCHER_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("CROPWATCHER_STANDBY", "0")
        monkeypatch.setattr(rest.app.state, "exit_deadline_s", 0.2, raising=False)
        # The shutdown runs on this thread, so the fake exit must unblock it.
        monkeypatch.setattr(rest.os, "_exit", lambda code: (exits.append(code), release.set()))

        shut_down = threading.Event()

        def run_the_app() -> None:
            with TestClient(rest.app):
                pass                     # leaving runs the lifespan shutdown
            shut_down.set()

        # On a thread, so a regression fails here instead of hanging the suite.
        threading.Thread(target=run_the_app, daemon=True).start()
        assert shut_down.wait(timeout=5), "SIGTERM left the agent running"
        assert exits == [1]

    def test_a_shutdown_that_finishes_is_not_cut_short(self, monkeypatch):
        exits: list[int] = []
        monkeypatch.setattr(rest.os, "_exit", exits.append)

        rest.arm_exit_deadline(0.2).set()

        time.sleep(0.5)
        assert exits == []


class TestConsoleLoggingIsDropped:
    def test_stderr_goes_and_the_log_file_stays(self, tmp_path):
        """Nothing reads stderr once the parent is gone; a write can block there."""
        logger = logging.getLogger("cropwatcher.test.console")
        console = logging.StreamHandler(sys.stderr)
        log_file = logging.FileHandler(tmp_path / "agent.log")
        logger.addHandler(console)
        logger.addHandler(log_file)
        try:
            rest._detach_console_logging()
            assert console not in logger.handlers
            assert log_file in logger.handlers
        finally:
            logger.removeHandler(console)
            logger.removeHandler(log_file)
            log_file.close()
