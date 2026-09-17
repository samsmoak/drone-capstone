"""Everything the agent says to Supabase.

The agent signs in as a **real operator account** using the anon key and acts as
`authenticated` under RLS. It deliberately does not use the service-role key:
this code ships inside a desktop installer, and a service-role key there would
hand every downloader unrestricted access and bypass every policy. It also makes
actions attributable — a flight traces to a person, not to a superuser.

Every write is **idempotent**, because the same record may be sent again after
a laptop comes back online:

- rows and records upsert on their own ids
- telemetry upserts on ``(flight_id, index)`` and ignores duplicates
- a CSV already in storage is treated as success, not an error
"""

from __future__ import annotations

import gzip
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

TELEMETRY_BUCKET = "flight-logs"
BACKFILL_FUNCTION = "import-flight-log"


class CloudError(RuntimeError):
    """Talking to Supabase failed. Always recoverable: the record stays local."""


class AuthError(RuntimeError):
    """Sign-in failed. Never carries the password or the raw provider error."""


@dataclass(frozen=True)
class Operator:
    id: str
    email: str
    full_name: str | None
    role: str

    @property
    def is_operator(self) -> bool:
        return self.role == "operator"


class Cloud(Protocol):
    """What the session and the sync need. Faked in tests."""

    def sign_in(self, email: str, password: str) -> Operator: ...
    def sign_out(self) -> None: ...
    def upsert_drone(self, hardware_id: str, name: str, uri: str) -> str: ...
    def upsert_session(self, row: dict[str, Any]) -> None: ...
    def upsert_flight(self, row: dict[str, Any]) -> None: ...
    def insert_audit(self, rows: list[dict[str, Any]]) -> None: ...
    def max_telemetry_index(self, flight_id: str) -> int | None: ...
    def insert_telemetry(self, rows: list[dict[str, Any]]) -> None: ...
    def upload_flight_csv(self, object_path: str, csv_path: Path) -> None: ...
    def request_backfill(self, flight_id: str, object_path: str) -> None: ...


class SupabaseCloud:
    """The real implementation."""

    def __init__(self, url: str, anon_key: str, client: Any | None = None) -> None:
        self._url = url
        self._anon_key = anon_key
        self._client = client
        self.operator: Operator | None = None

    # ── auth ─────────────────────────────────────────────────────────────

    def _connect(self) -> Any:
        if self._client is None:
            try:
                from supabase import create_client
            except ImportError as e:  # pragma: no cover
                raise CloudError("the supabase package is not installed") from e
            self._client = create_client(self._url, self._anon_key)
        return self._client

    def sign_in(self, email: str, password: str) -> Operator:
        client = self._connect()
        try:
            response = client.auth.sign_in_with_password({"email": email, "password": password})
        except Exception as e:
            # Never echo the password or the provider's raw error, which can
            # contain the submitted credentials.
            raise AuthError(
                f"Could not sign in as {email}. Check the email and password, and that "
                f"this computer is online. ({type(e).__name__})"
            ) from None

        user = getattr(response, "user", None)
        if user is None:
            raise AuthError("Sign-in did not return a user.")
        return self._load_operator(client, user, email)

    def restore(self, refresh_token: str) -> Operator:
        """Sign back in from a stored refresh token — no password.

        Fails with AuthError when the token was revoked (signed out elsewhere)
        or expired; the caller then shows the sign-in form.
        """
        client = self._connect()
        try:
            response = client.auth.refresh_session(refresh_token)
        except Exception as e:
            raise AuthError(
                f"The saved sign-in has expired. Please sign in again. ({type(e).__name__})"
            ) from None
        user = getattr(response, "user", None)
        if user is None:
            raise AuthError("The saved sign-in has expired. Please sign in again.")
        return self._load_operator(client, user, getattr(user, "email", "") or "")

    @property
    def refresh_token(self) -> str | None:
        if self._client is None:
            return None
        session = self._client.auth.get_session()
        return getattr(session, "refresh_token", None) if session else None

    def _load_operator(self, client: Any, user: Any, email: str) -> Operator:
        profile = (
            client.table("profiles").select("*").eq("id", user.id).maybe_single().execute()
        )
        row = getattr(profile, "data", None) or {}
        operator = Operator(
            id=user.id,
            email=str(row.get("email") or getattr(user, "email", None) or email),
            full_name=row.get("full_name"),
            role=row.get("role", "viewer"),
        )
        self.operator = operator
        log.info("signed in as %s (%s)", operator.email, operator.role)
        return operator

    def sign_out(self) -> None:
        if self._client is not None:
            try:
                self._client.auth.sign_out()
            except Exception:
                log.debug("sign-out failed; clearing the local session anyway")
        self.operator = None

    @property
    def access_token(self) -> str | None:
        if self._client is None:
            return None
        session = self._client.auth.get_session()
        return getattr(session, "access_token", None) if session else None

    # ── records ──────────────────────────────────────────────────────────

    def _table(self, name: str) -> Any:
        return self._connect().table(name)

    def upsert_drone(self, hardware_id: str, name: str, uri: str) -> str:
        try:
            found = (
                self._table("drones").select("id").eq("hardware_id", hardware_id).execute()
            )
            rows = getattr(found, "data", None) or []
            if rows:
                return str(rows[0]["id"])
            created = (
                self._table("drones")
                .insert({"hardware_id": hardware_id, "name": name, "uri": uri})
                .execute()
            )
            return str((getattr(created, "data", None) or [{}])[0]["id"])
        except Exception as e:
            raise CloudError(f"could not register the drone: {type(e).__name__}") from e

    def upsert_session(self, row: dict[str, Any]) -> None:
        self._upsert("sessions", row)

    def upsert_flight(self, row: dict[str, Any]) -> None:
        self._upsert("flights", row)

    def _upsert(self, table: str, row: dict[str, Any]) -> None:
        try:
            self._table(table).upsert(row, on_conflict="id").execute()
        except Exception as e:
            raise CloudError(f"could not save the {table[:-1]} record: {type(e).__name__}") from e

    def insert_audit(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        try:
            self._table("audit_events").upsert(
                rows, on_conflict="id", ignore_duplicates=True
            ).execute()
        except Exception as e:
            raise CloudError(f"could not save audit events: {type(e).__name__}") from e

    # ── telemetry ────────────────────────────────────────────────────────

    def max_telemetry_index(self, flight_id: str) -> int | None:
        """The highest row the server already holds — the resume point.

        Asked of the server rather than tracked locally, so it survives a crash,
        a reinstall, or rows uploaded by the server-side import.
        """
        try:
            response = (
                self._table("telemetry")
                .select("index")
                .eq("flight_id", flight_id)
                .order("index", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as e:
            raise CloudError(f"could not read the upload progress: {type(e).__name__}") from e
        rows = getattr(response, "data", None) or []
        return int(rows[0]["index"]) if rows else None

    def insert_telemetry(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        try:
            self._table("telemetry").upsert(
                rows, on_conflict="flight_id,index", ignore_duplicates=True
            ).execute()
        except Exception as e:
            raise CloudError(f"could not upload telemetry: {type(e).__name__}") from e

    # ── the flight log file ──────────────────────────────────────────────

    def upload_flight_csv(self, object_path: str, csv_path: Path) -> None:
        """Upload the flight's CSV, compressed. ~150 KB for a full-battery flight."""
        try:
            payload = gzip.compress(csv_path.read_bytes())
            self._connect().storage.from_(TELEMETRY_BUCKET).upload(
                object_path, payload,
                {"content-type": "text/csv", "content-encoding": "gzip"},
            )
        except Exception as e:
            # Already there: a previous attempt succeeded and the reply was lost.
            if "Duplicate" in str(e) or "already exists" in str(e):
                log.info("flight log %s already uploaded", object_path)
                return
            raise CloudError(f"could not upload the flight log: {type(e).__name__}") from e

    def request_backfill(self, flight_id: str, object_path: str) -> None:
        """Ask the server to fill any missing rows from the uploaded file.

        Best-effort and deliberately not awaited: once the file is up, the
        server can finish the import even if this laptop closes immediately.
        """
        try:
            self._connect().functions.invoke(
                BACKFILL_FUNCTION,
                {"body": {"flight_id": flight_id, "object_path": object_path}},
            )
        except Exception as e:
            log.info("backfill request failed (%s); the laptop will finish the upload",
                     type(e).__name__)

    # ── missions queued on the web ───────────────────────────────────────

    def queued_missions(self) -> list[dict[str, Any]]:
        try:
            response = (
                self._table("missions")
                .select("*")
                .eq("status", "queued")
                .order("created_at")
                .execute()
            )
            return list(getattr(response, "data", None) or [])
        except Exception as e:
            raise CloudError(f"could not read the mission queue: {type(e).__name__}") from e

    def claim_mission(self, mission_id: str, agent_id: str) -> dict[str, Any] | None:
        try:
            response = self._connect().rpc(
                "claim_mission", {"mission_id": mission_id, "agent_id": agent_id}
            ).execute()
        except Exception as e:
            raise CloudError(f"could not claim the mission: {type(e).__name__}") from e
        data = getattr(response, "data", None)
        if isinstance(data, list):
            data = data[0] if data else None
        return data or None

    def update_mission(self, mission_id: str, values: dict[str, Any]) -> None:
        try:
            self._table("missions").update(values).eq("id", mission_id).execute()
        except Exception as e:
            raise CloudError(f"could not update the mission: {type(e).__name__}") from e
