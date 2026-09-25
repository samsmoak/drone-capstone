"""Sign-in always answers the window in time, and never leaves half a session.

The window's fetch gives up after about 60 s of silence and can then only say
"The flight agent is running but did not answer /auth/sign-in" — which is what
an Intel Mac showed on 2026-09-25. The profile read after the auth call could
wait 120 s (PostgREST's default), and nothing bounded the first import of the
Supabase library. These pin the deadline that replaced that silence.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from cropwatcher.sync import cloud as cloud_module
from cropwatcher.sync.cloud import AuthError, CloudTimeout, SupabaseCloud

DEADLINE = 0.3


class FakeQuery:
    def __init__(self, row, fail=None):
        self._row, self._fail = row, fail

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self._fail:
            raise self._fail
        return SimpleNamespace(data=self._row)


class FakeAuth:
    def __init__(self, delay=0.0, fail=None):
        self.delay, self.fail = delay, fail
        self.signed_out: list = []
        self.finished = threading.Event()

    def sign_in_with_password(self, credentials):
        time.sleep(self.delay)
        self.finished.set()
        if self.fail:
            raise self.fail
        return SimpleNamespace(user=SimpleNamespace(id="user-1", email=credentials["email"]))

    def refresh_session(self, token):
        return self.sign_in_with_password({"email": "ada@example.com"})

    def sign_out(self, options=None):
        self.signed_out.append(options)


class FakeClient:
    def __init__(self, auth, profile_fail=None):
        self.auth = auth
        self._profile_fail = profile_fail

    def table(self, _name):
        row = {"email": "ada@example.com", "full_name": "Ada", "role": "operator"}
        return FakeQuery(row, self._profile_fail)


def make(delay=0.0, fail=None, profile_fail=None):
    auth = FakeAuth(delay, fail)
    return SupabaseCloud("https://x.supabase.co", "key",
                         client=FakeClient(auth, profile_fail), deadline_s=DEADLINE), auth


class TestDeadline:
    def test_a_prompt_sign_in_returns_the_operator(self):
        cloud, _ = make()
        operator = cloud.sign_in("ada@example.com", "pw")
        assert operator.role == "operator" and cloud.operator == operator

    def test_a_hung_sign_in_answers_at_the_deadline_with_a_reason(self):
        cloud, _ = make(delay=5.0)
        started = time.monotonic()
        with pytest.raises(CloudTimeout) as error:
            cloud.sign_in("ada@example.com", "pw")
        assert time.monotonic() - started < DEADLINE + 1.0     # not the 5 s the call took
        assert "did not answer" in str(error.value) and "firewall" in str(error.value)

    def test_a_timeout_is_an_auth_error_so_existing_callers_show_it(self):
        assert issubclass(CloudTimeout, AuthError)

    def test_a_second_attempt_waits_for_the_first_to_end(self):
        cloud, _ = make(delay=1.0)
        with pytest.raises(CloudTimeout):
            cloud.sign_in("ada@example.com", "pw")
        with pytest.raises(CloudTimeout, match="still waiting"):
            cloud.sign_in("ada@example.com", "pw")

    def test_a_late_success_is_discarded_on_this_computer_only(self):
        """Nobody is waiting for it, so it must not leave a session behind —
        and "local", because the default scope signs the account out of every
        device, the website included."""
        cloud, auth = make(delay=0.8)
        with pytest.raises(CloudTimeout):
            cloud.sign_in("ada@example.com", "pw")
        assert auth.finished.wait(3)
        deadline = time.monotonic() + 3
        while not auth.signed_out and time.monotonic() < deadline:
            time.sleep(0.02)
        assert auth.signed_out == [{"scope": "local"}]
        assert cloud.operator is None

    def test_after_a_late_attempt_ends_signing_in_works_again(self):
        cloud, auth = make(delay=0.6)
        with pytest.raises(CloudTimeout):
            cloud.sign_in("ada@example.com", "pw")
        assert auth.finished.wait(3)
        time.sleep(0.1)
        auth.delay = 0.0
        assert cloud.sign_in("ada@example.com", "pw").email == "ada@example.com"

    def test_a_refusal_inside_the_deadline_keeps_its_own_message(self):
        cloud, _ = make(fail=RuntimeError("Invalid login credentials"))
        with pytest.raises(AuthError, match="Check the email and password") as error:
            cloud.sign_in("ada@example.com", "pw")
        assert not isinstance(error.value, CloudTimeout)
        assert "Invalid login" not in str(error.value)          # never the raw provider text

    def test_restore_is_bounded_too(self):
        cloud, _ = make(delay=5.0)
        with pytest.raises(CloudTimeout):
            cloud.restore("refresh-abc")


class TestProfileRead:
    def test_an_unreadable_profile_is_a_plain_error_and_no_half_session(self):
        cloud, auth = make(profile_fail=TimeoutError("read timed out"))
        with pytest.raises(AuthError, match="profile could not be read") as error:
            cloud.sign_in("ada@example.com", "pw")
        assert "TimeoutError" in str(error.value)
        assert auth.signed_out == [{"scope": "local"}] and cloud.operator is None


class TestClientCreation:
    def test_a_client_that_will_not_build_is_a_plain_auth_error(self, monkeypatch, caplog):
        """It used to escape as an unexpected error, which the window could not
        read. Now it says what failed, and the log keeps the traceback."""
        cloud = SupabaseCloud("https://x.supabase.co", "key", deadline_s=DEADLINE)

        def boom():
            raise ImportError("Using http2=True, but the 'h2' package is not installed")
        monkeypatch.setattr(cloud, "_connect", boom)
        with pytest.raises(AuthError, match="could not start on this computer") as error:
            cloud.sign_in("ada@example.com", "pw")
        assert "ImportError" in str(error.value) and not isinstance(error.value, CloudTimeout)
        assert any("could not be created" in r.getMessage() and r.exc_info
                   for r in caplog.records)

    def test_restore_says_the_same(self, monkeypatch):
        cloud = SupabaseCloud("https://x.supabase.co", "key", deadline_s=DEADLINE)
        monkeypatch.setattr(cloud, "_connect", lambda: (_ for _ in ()).throw(OSError("x")))
        with pytest.raises(AuthError, match="could not start"):
            cloud.restore("refresh-abc")


class TestWarm:
    def test_not_configured_loads_nothing(self, monkeypatch):
        called = []
        cloud = SupabaseCloud("", "")
        monkeypatch.setattr(cloud, "_connect", lambda: called.append(1))
        cloud.warm()
        assert called == []

    def test_configured_builds_the_client_once(self, monkeypatch):
        import sys
        from types import ModuleType

        made = []
        fake = ModuleType("supabase")
        fake.create_client = lambda url, key: made.append((url, key)) or object()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "supabase", fake)
        cloud = SupabaseCloud("https://x.supabase.co", "key")
        cloud.warm()
        cloud.warm()
        assert made == [("https://x.supabase.co", "key")]

    def test_a_failure_to_load_is_logged_not_raised(self, monkeypatch, caplog):
        cloud = SupabaseCloud("https://x.supabase.co", "key")

        def boom():
            raise OSError("disk")
        monkeypatch.setattr(cloud, "_connect", boom)
        cloud.warm()
        assert any("could not prepare" in r.getMessage() for r in caplog.records)


def test_the_deadline_leaves_room_before_the_window_gives_up():
    """WebKit's fetch gives up after ~60 s of silence; the agent answers first."""
    assert cloud_module.SIGN_IN_DEADLINE_S <= 30
