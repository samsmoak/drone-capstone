"""Supabase connection and the mission queue.

The agent only ever makes **outbound** calls. It polls for work rather than
listening for it, because the laptop sits behind a router with no public
address — a push design would need port forwarding on every site the drone
is deployed to.

The queue is defined as a protocol so the polling loop can be tested against a
fake. The parts worth testing — claim exactly once, always report an outcome,
never strand a mission — are logic, not network behaviour.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Required configuration is missing. Raised at startup, never mid-flight."""


@dataclass(frozen=True)
class Settings:
    """Agent configuration.

    The agent signs in as a **real operator account** using the anon key, and
    acts as `authenticated` under RLS. It deliberately does NOT use the
    service-role key.

    That matters because this agent ships inside a desktop installer. A
    service-role key embedded there would hand every person who downloads the
    app unrestricted access to the database, and it would bypass every policy
    in the RLS migration. The anon key is designed to be public; the operator's
    password is theirs and stays on their machine.

    It also makes actions attributable: a claimed mission traces to a person,
    not to an anonymous superuser.
    """

    url: str
    anon_key: str
    email: str
    password: str
    agent_id: str

    @classmethod
    def from_env(cls) -> Settings:
        """Read configuration, failing loudly and specifically.

        Missing config must stop the agent at startup with a message naming the
        variable. Discovering it when a flight tries to upload means the flight
        is already in the air.
        """
        values = {
            "SUPABASE_URL": os.environ.get("SUPABASE_URL", "").strip(),
            "SUPABASE_ANON_KEY": os.environ.get("SUPABASE_ANON_KEY", "").strip(),
            "CROPWATCHER_EMAIL": os.environ.get("CROPWATCHER_EMAIL", "").strip(),
            "CROPWATCHER_PASSWORD": os.environ.get("CROPWATCHER_PASSWORD", ""),
        }

        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfigError(
                f"missing environment variable(s): {', '.join(missing)}. "
                f"Copy .env.example to .env and fill them in."
            )

        if os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
            log.warning(
                "SUPABASE_SERVICE_ROLE_KEY is set but will not be used. The agent "
                "signs in as an operator so it stays subject to RLS; a service-role "
                "key must never ship inside the desktop installer."
            )

        # Default to the machine name so a claimed mission can be traced back
        # to the laptop holding it.
        agent_id = os.environ.get("CROPWATCHER_AGENT_ID", "").strip() or os.uname().nodename

        return cls(
            url=values["SUPABASE_URL"],
            anon_key=values["SUPABASE_ANON_KEY"],
            email=values["CROPWATCHER_EMAIL"],
            password=values["CROPWATCHER_PASSWORD"],
            agent_id=agent_id,
        )


@dataclass
class QueuedMission:
    """A mission claimed from the queue."""

    id: str
    name: str
    type: str
    plan: dict[str, Any]


class MissionQueue(Protocol):
    """What the poller needs. Implemented by Supabase, faked in tests."""

    def claim_next(self) -> QueuedMission | None: ...

    def mark_running(self, mission_id: str, flight_id: str | None) -> None: ...

    def mark_done(self, mission_id: str) -> None: ...

    def mark_failed(self, mission_id: str, error: str) -> None: ...

    def release_stale(self) -> int: ...


class SupabaseQueue:
    """The real queue, backed by Postgres."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client if client is not None else _make_client(settings)

    def claim_next(self) -> QueuedMission | None:
        response = self._client.rpc(
            "claim_next_mission", {"agent_id": self.settings.agent_id}
        ).execute()

        row = response.data
        if not row:
            return None
        if isinstance(row, list):
            row = row[0] if row else None
        if not row or not row.get("id"):
            return None

        return QueuedMission(
            id=row["id"],
            name=row.get("name", "mission"),
            type=row.get("type", "waypoint"),
            plan=row.get("plan") or {},
        )

    def mark_running(self, mission_id: str, flight_id: str | None) -> None:
        self._update(mission_id, {"status": "running", "flight_id": flight_id})

    def mark_done(self, mission_id: str) -> None:
        self._update(mission_id, {"status": "done", "error": None})

    def mark_failed(self, mission_id: str, error: str) -> None:
        # Truncated: the column is text, but a full traceback in a status field
        # makes the mission list unreadable in the dashboard.
        self._update(mission_id, {"status": "failed", "error": error[:500]})

    def release_stale(self) -> int:
        response = self._client.rpc("release_stale_claims", {}).execute()
        return int(response.data or 0)

    def _update(self, mission_id: str, values: dict[str, Any]) -> None:
        values["updated_at"] = "now()"
        self._client.table("missions").update(values).eq("id", mission_id).execute()


class AuthError(RuntimeError):
    """Sign-in failed. Raised at startup so it cannot surprise a flight."""


def _make_client(settings: Settings) -> Any:
    """Create a client and sign in as the operator.

    Sign-in happens once, here, rather than lazily on first use: a bad password
    should stop the agent before it claims work, not after.
    """
    try:
        from supabase import create_client
    except ImportError as e:  # pragma: no cover
        raise ConfigError(
            "the supabase package is not installed — pip install -e '.[dev]'"
        ) from e

    client = create_client(settings.url, settings.anon_key)

    try:
        client.auth.sign_in_with_password(
            {"email": settings.email, "password": settings.password}
        )
    except Exception as e:
        # Never echo the password, and do not include the raw provider error,
        # which can contain the submitted credentials.
        raise AuthError(
            f"could not sign in as {settings.email}. Check CROPWATCHER_EMAIL "
            f"and CROPWATCHER_PASSWORD, and that the account exists with the "
            f"'operator' role. ({type(e).__name__})"
        ) from None

    log.info("signed in as %s (agent %s)", settings.email, settings.agent_id)
    return client
