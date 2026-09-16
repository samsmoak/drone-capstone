"""Prove a frozen sidecar actually works, before it ships inside an installer.

Bundling failures in this binary are silent. PyInstaller reports success, the
executable starts, and then the one thing that matters — reaching a USB radio,
or upgrading a WebSocket — fails on a user's laptop with a traceback they
cannot act on. Every check here exists because its absence is invisible until
hardware or a user is in the room:

  runs            the bootloader and the Python runtime are intact
  usb             libusb loaded and enumerated the bus; cflib's native
                  dependency is the one PyInstaller cannot see by itself
  health          uvicorn serves HTTP
  websocket       uvicorn's websockets implementation is bundled; it is
                  selected by string name, so nothing imports it statically

The `usb` check is the subtle one. With no dongle plugged in, a *correct*
binary reports "no drone found" and a *broken* one reports a missing libusb
backend. Both are failures of the command and both exit non-zero, so the exit
code proves nothing — this asserts on which message came back.

Run directly, or through `build_sidecar.sh`, which runs it on every build:

    python verify_sidecar.py ../../desktop/src-tauri/bin/cropwatcher-agent-<triple>
"""

from __future__ import annotations

import base64
import http.client
import socket
import subprocess
import sys
import time
from pathlib import Path

# A port unlikely to collide with an agent the developer is already running;
# verifying against a *different* process would pass while the frozen binary
# is broken.
PROBE_PORT = 8791
STARTUP_TIMEOUT_S = 20.0

# What cflib prints once libusb is loaded and it has walked the bus.
USB_REACHED = "Looking for devices"
# The correct answer when no radio is plugged in.
NO_DRONE = "no drone found"
# What a missing native dependency looks like instead.
BUNDLING_FAILURE = ("No backend available", "ModuleNotFoundError", "ImportError")


class VerificationError(RuntimeError):
    """The binary built, but does not work. Never ship past this."""


def _check_runs(binary: Path) -> str:
    result = subprocess.run(
        [str(binary), "--help"], capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise VerificationError(f"`--help` exited {result.returncode}:\n{result.stderr}")
    return "the frozen runtime starts"


def _check_usb(binary: Path) -> str:
    """`check` is expected to fail here — this asserts on *how* it fails."""
    result = subprocess.run(
        [str(binary), "check"], capture_output=True, text=True, timeout=120
    )
    output = result.stdout + result.stderr

    for marker in BUNDLING_FAILURE:
        if marker in output:
            raise VerificationError(
                f"libusb did not load — {marker!r} in output. The native library "
                f"from libusb_package was not bundled:\n{output}"
            )

    if USB_REACHED not in output:
        raise VerificationError(
            "cflib never enumerated USB, so the radio path is unproven.\n"
            f"Expected {USB_REACHED!r} in:\n{output}"
        )

    if NO_DRONE in output:
        return "libusb enumerated the bus; no radio attached (expected)"
    return "libusb enumerated the bus; a radio answered"


def _wait_for_port(port: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.25)
    raise VerificationError(f"the agent never opened port {port} within {timeout_s:.0f}s")


def _check_server(binary: Path) -> list[str]:
    """Start the frozen agent and exercise both surfaces it exposes."""
    process = subprocess.Popen(
        [str(binary), "serve", "--port", str(PROBE_PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_port(PROBE_PORT, STARTUP_TIMEOUT_S)
        results = []

        connection = http.client.HTTPConnection("127.0.0.1", PROBE_PORT, timeout=10)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            body = response.read().decode()
            if response.status != 200:
                raise VerificationError(f"/health returned {response.status}: {body}")
            if '"ok":true' not in body.replace(" ", ""):
                raise VerificationError(f"/health did not report ok: {body}")
            results.append("HTTP serves /health")
        finally:
            connection.close()

        # A raw upgrade handshake: the point is uvicorn's websockets
        # implementation answering 101, not what the socket does afterwards.
        #
        # RFC 6455 requires the key to be exactly 16 bytes before encoding.
        # A 17-byte one is rejected with a 400 that looks identical to "the
        # websockets implementation is missing" — which cost a build to tell
        # apart, hence the explicit length.
        key = base64.b64encode(b"cropwatcher1probe"[:16]).decode()
        connection = http.client.HTTPConnection("127.0.0.1", PROBE_PORT, timeout=10)
        try:
            connection.request(
                "GET",
                "/ws/manual",
                headers={
                    "Connection": "Upgrade",
                    "Upgrade": "websocket",
                    "Sec-WebSocket-Version": "13",
                    "Sec-WebSocket-Key": key,
                },
            )
            response = connection.getresponse()
            if response.status != 101:
                raise VerificationError(
                    f"WebSocket upgrade returned {response.status}, not 101 — "
                    "uvicorn's websockets implementation is probably not bundled."
                )
            results.append("WebSocket upgrades to 101")
        finally:
            connection.close()

        return results
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def verify(binary: Path) -> None:
    if not binary.exists():
        raise VerificationError(f"no such binary: {binary}")

    checks = [_check_runs(binary), _check_usb(binary), *_check_server(binary)]
    size_mb = binary.stat().st_size / 1_048_576
    for line in checks:
        print(f"  ok   {line}")
    print(f"  ok   single file, {size_mb:.0f} MB")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__)
        return 2

    try:
        verify(Path(args[0]))
    except VerificationError as e:
        print(f"\n  FAILED  {e}\n", file=sys.stderr)
        return 1

    print("\n  sidecar verified\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
