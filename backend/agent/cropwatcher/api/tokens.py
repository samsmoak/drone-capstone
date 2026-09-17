"""The local control token.

Binding to localhost keeps other machines out, but not other programs or other
websites on this machine: an unauthenticated local API that can arm a drone is
reachable from any page the operator has open. Every command therefore carries
a token that only the app which launched the agent knows.

The desktop app passes it in ``CROPWATCHER_AGENT_TOKEN`` when it spawns the
sidecar. Run from a terminal, the agent generates one and writes it to the data
folder (owner-readable), so the CLI and diagnostics can use it.

This is *local* authentication — proof the caller is the app. Who the operator
is comes from their Supabase sign-in (see :mod:`cropwatcher.session`).
"""

from __future__ import annotations

import logging
import os
import secrets
import stat

from cropwatcher.paths import data_dir

log = logging.getLogger(__name__)

ENV_VAR = "CROPWATCHER_AGENT_TOKEN"
HEADER = "X-Agent-Token"


def load_or_create_token() -> str:
    token = os.environ.get(ENV_VAR, "").strip()
    if token:
        return token

    path = data_dir() / "agent-token"
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)      # owner only
    except OSError:
        log.debug("could not restrict permissions on %s", path)
    return token
