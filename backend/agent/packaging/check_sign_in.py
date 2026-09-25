"""Prove a frozen agent can sign in to Supabase — the path an Intel Mac lost.

On 2026-09-25 the app on an Intel Mac opened, its agent answered, and every
sign-in ended in "The flight agent is running but did not answer" while the
same code signed in on an M4. Nothing checked the sign-in path of a frozen
agent: verify_sidecar.py stays offline on purpose, so it can run on any build.
This is its online companion, run by CI on every machine it installs on, and
by hand on a machine where sign-in fails:

    .venv/bin/python packaging/check_sign_in.py <path to cropwatcher-agent>
    e.g. /Applications/CropWatcher.app/Contents/MacOS/cropwatcher-agent

It signs in with an account that does not exist. The correct answer is the
agent's own refusal — HTTP 409, "Could not sign in as …" — because that means
the agent loaded the Supabase client, reached Supabase, and was told no. Any
other answer fails, with the agent's own output printed.

Needs the internet. The Supabase URL and publishable key are read from
desktop/src-tauri/src/lib.rs, where the app compiles them in, so this checks
the project the app actually uses. The publishable key is public by design.
"""

from __future__ import annotations

import http.client
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from verify_sidecar import (  # noqa: E402
    VerificationError,
    _kill_tree,
    _port_open,
    _probe_env,
    _stop_like_the_app,
    _tail,
    _wait_for_port,
)

PORT = 8793
TOKEN = "check-sign-in"
LIB_RS = HERE.parent.parent.parent / "desktop" / "src-tauri" / "src" / "lib.rs"
# A domain reserved for examples (RFC 2606): this account can never exist.
PROBE_EMAIL = "cropwatcher-sign-in-check@example.com"
REFUSED = "Could not sign in as"
# The agent answers within its own deadline (SIGN_IN_DEADLINE_S, 25 s); this
# only has to outlast it.
REQUEST_TIMEOUT_S = 60


def project() -> tuple[str, str]:
    """The Supabase URL and publishable key the app compiles in."""
    source = LIB_RS.read_text()
    url = re.search(r'const SUPABASE_URL: &str = "([^"]+)"', source)
    key = re.search(r'const SUPABASE_ANON_KEY: &str = "([^"]+)"', source)
    if not url or not key:
        raise VerificationError(f"could not read SUPABASE_URL / SUPABASE_ANON_KEY from {LIB_RS}")
    return url.group(1), key.group(1)


def check(binary: Path) -> str:
    binary = binary.resolve()
    if not binary.exists():
        raise VerificationError(f"no such binary: {binary}")
    if _port_open(PORT):
        raise VerificationError(f"port {PORT} is already in use; stop whatever holds it")
    url, key = project()

    with tempfile.TemporaryDirectory(prefix="cropwatcher-sign-in-",
                                     ignore_cleanup_errors=True) as work:
        env = _probe_env(str(Path(work) / "data"))
        env.update(CROPWATCHER_AGENT_TOKEN=TOKEN, SUPABASE_URL=url, SUPABASE_ANON_KEY=key)
        log_path = Path(work) / "agent.log"
        with open(log_path, "w") as log:
            process = subprocess.Popen(
                [str(binary), "serve", "--port", str(PORT), "--exit-with-parent"],
                stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, env=env,
                start_new_session=sys.platform != "win32",
            )
        try:
            _wait_for_port(process, PORT, log_path)
            started = time.monotonic()
            connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=REQUEST_TIMEOUT_S)
            try:
                connection.request(
                    "POST", "/auth/sign-in",
                    body=json.dumps({"email": PROBE_EMAIL, "password": "not-a-real-password"}),
                    headers={"Content-Type": "application/json", "X-Agent-Token": TOKEN,
                             "Origin": "tauri://localhost"},
                )
                response = connection.getresponse()
                body = response.read().decode(errors="replace")
            except OSError as e:
                raise VerificationError(
                    f"the sign-in request got no answer ({type(e).__name__}: {e}). "
                    f"The agent's output:\n{_tail(log_path)}"
                ) from None
            finally:
                connection.close()
            took = time.monotonic() - started

            try:
                detail = json.loads(body).get("detail", body)
            except ValueError:
                detail = body
            if response.status != 409 or not str(detail).startswith(REFUSED):
                raise VerificationError(
                    f"sign-in answered HTTP {response.status} after {took:.1f}s: {detail}\n"
                    f"Expected 409 \"{REFUSED} …\" — Supabase refusing an account that "
                    f"does not exist. The agent's output:\n{_tail(log_path)}"
                )
            cors = response.getheader("access-control-allow-origin")
            if cors != "tauri://localhost":
                raise VerificationError(
                    f"sign-in answered without the window's CORS header ({cors!r}); the "
                    f"window could not read it."
                )
            _stop_like_the_app(process, PORT)
            return f"Supabase reached and refused the probe account in {took:.1f}s (HTTP 409)"
        finally:
            _kill_tree(process)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        result = check(Path(args[0]))
    except VerificationError as e:
        print(f"\n  FAILED  {e}\n", file=sys.stderr)
        return 1
    print(f"  ok   {result}\n\n  sign-in verified\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
