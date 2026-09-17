"""Staying signed in between launches.

The desktop app used to start signed out every time. What makes that
unnecessary is the Supabase *refresh token*: it can be exchanged for a fresh
session without the password, and it is revoked by signing out.

Stored in the app data folder with owner-only permissions (0600). Not in the OS
keychain: that would add a native dependency to the bundled agent for a lab
laptop, and anyone who can read this user's files can already use this user's
session. Signing out deletes the file and revokes the token server-side.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path

from cropwatcher.paths import data_dir

log = logging.getLogger(__name__)

FILENAME = "session.json"


def _path(root: Path | None = None) -> Path:
    return (root or data_dir()) / FILENAME


def save(refresh_token: str, email: str, *, root: Path | None = None) -> None:
    path = _path(root)
    temp = path.with_suffix(".json.tmp")
    # Created 0600 from the start, so the token is never briefly world-readable.
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"refresh_token": refresh_token, "email": email}, f)
    os.replace(temp, path)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def load(*, root: Path | None = None) -> tuple[str, str] | None:
    """(refresh_token, email), or None when nothing usable is stored."""
    path = _path(root)
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        log.warning("stored sign-in is unreadable — ignoring it")
        return None
    token, email = raw.get("refresh_token"), raw.get("email")
    if not isinstance(token, str) or not token or not isinstance(email, str):
        return None
    return token, email


def clear(*, root: Path | None = None) -> None:
    with contextlib.suppress(FileNotFoundError):
        _path(root).unlink()
