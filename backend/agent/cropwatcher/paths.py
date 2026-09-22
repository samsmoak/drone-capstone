"""Where the agent keeps files on the operator's machine.

Flight CSVs used to go to a *relative* ``organized_flights/`` folder. Run from a
terminal in the repo that works; run as the desktop app's sidecar the working
directory is ``/``, which is read-only, and the first flight's CSV write — the
one write that "cannot fail" (CLAUDE.md #6) — would have failed.

Everything now lives in the per-user application data folder:

    macOS    ~/Library/Application Support/CropWatcher
    Windows  %APPDATA%\\CropWatcher
    Linux    $XDG_DATA_HOME/CropWatcher  (default ~/.local/share)

``CROPWATCHER_DATA_DIR`` overrides it, for tests and for a lab laptop that wants
flights on a specific disk.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "CropWatcher"


def data_dir() -> Path:
    override = os.environ.get("CROPWATCHER_DATA_DIR", "").strip()
    if override:
        root = Path(override).expanduser()
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def flights_dir() -> Path:
    path = data_dir() / "flights"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file() -> Path:
    """Where the agent writes its log.

    The desktop app spawns the agent as a sidecar and discards its stdout, so
    when something failed inside it there was nothing to read: an operator saw
    "Could not reach the flight agent" and the reason was gone with the
    process. A file survives the crash that produced it.
    """
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path / "agent.log"


def outbox_dir() -> Path:
    """Records waiting to reach Supabase. Emptied by the sync as they land."""
    path = data_dir() / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cflib_cache_dir() -> Path:
    """cflib's TOC cache. Also used to be relative (``./.cache``)."""
    path = data_dir() / "cflib-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path
