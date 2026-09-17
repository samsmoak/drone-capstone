"""Offline-first sync: nothing lost, nothing sent twice, order respected."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from cropwatcher.audit import Action, AuditLog, Result
from cropwatcher.sync.cloud import CloudError
from cropwatcher.sync.outbox import Kind, Outbox
from cropwatcher.sync.syncer import Syncer, parse_csv_row, read_rows_after

COLUMNS = ["index", "recorded_at", "flight_id", "temp_unit", "raw_temp", "z_m", "motor_m1", "event"]


def write_csv(path: Path, rows: int, flight_id: str = "flight-1") -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for i in range(rows):
            writer.writerow({
                "index": i, "recorded_at": f"2026-09-16T20:0{i % 10}:00Z", "flight_id": flight_id,
                "temp_unit": "C", "raw_temp": 30.0 + i * 0.01, "z_m": 0.3,
                "motor_m1": 41000, "event": "" if i else "takeoff",
            })
    return path


class FakeCloud:
    def __init__(self) -> None:
        self.drones: dict[str, str] = {}
        self.sessions: list[dict] = []
        self.flights: list[dict] = []
        self.audit: list[dict] = []
        self.telemetry: dict[str, dict[int, dict]] = {}
        self.uploads: list[tuple[str, Path]] = []
        self.backfills: list[tuple[str, str]] = []
        self.fail_with: Exception | None = None

    def _maybe_fail(self):
        if self.fail_with:
            raise self.fail_with

    def upsert_drone(self, hardware_id, name, uri):
        self._maybe_fail()
        self.drones[hardware_id] = f"uuid-{hardware_id}"
        return self.drones[hardware_id]

    def upsert_session(self, row):
        self._maybe_fail()
        self.sessions = [s for s in self.sessions if s["id"] != row["id"]] + [row]

    def upsert_flight(self, row):
        self._maybe_fail()
        self.flights = [f for f in self.flights if f["id"] != row["id"]] + [row]

    def insert_audit(self, rows):
        self._maybe_fail()
        known = {r["id"] for r in self.audit}
        self.audit.extend(r for r in rows if r["id"] not in known)

    def max_telemetry_index(self, flight_id):
        self._maybe_fail()
        stored = self.telemetry.get(flight_id)
        return max(stored) if stored else None

    def insert_telemetry(self, rows):
        self._maybe_fail()
        for row in rows:
            self.telemetry.setdefault(row["flight_id"], {}).setdefault(row["index"], row)

    def upload_flight_csv(self, object_path, csv_path):
        self._maybe_fail()
        self.uploads.append((object_path, csv_path))

    def request_backfill(self, flight_id, object_path):
        self.backfills.append((flight_id, object_path))


@pytest.fixture
def rig(tmp_path):
    outbox = Outbox(tmp_path / "outbox")
    cloud = FakeCloud()
    syncer = Syncer(outbox, lambda: cloud, sleep=lambda s: None)
    return outbox, cloud, syncer, tmp_path


def add_flight(outbox: Outbox, tmp_path: Path, *, flight_id="flight-1", rows=5, ended=True):
    outbox.put(Kind.DRONE, "cf-1", {
        "hardware_id": "cf-1", "name": "CropWatcher 1", "uri": "radio://0/80/2M"})
    outbox.put(Kind.SESSION, "session-1", {
        "id": "session-1", "drone_hardware_id": "cf-1", "started_at": "2026-09-16T20:00:00Z",
        "ended_at": "2026-09-16T20:30:00Z" if ended else None,
    })
    csv_path = write_csv(tmp_path / f"{flight_id}.csv", rows, flight_id)
    outbox.put(Kind.FLIGHT, flight_id, {
        "id": flight_id, "session_id": "session-1", "drone_hardware_id": "cf-1",
        "started_at": "2026-09-16T20:10:00Z",
        "ended_at": "2026-09-16T20:11:00Z" if ended else None,
        "status": "completed", "mode": "auto", "csv_path": str(csv_path), "rows_written": rows,
    })
    return csv_path


class TestCsvParsing:
    def test_types_come_back_from_the_shared_schema(self, tmp_path):
        rows = list(read_rows_after(write_csv(tmp_path / "f.csv", 2), None))
        assert rows[0]["index"] == 0 and isinstance(rows[0]["index"], int)
        assert isinstance(rows[0]["raw_temp"], float)
        assert isinstance(rows[0]["motor_m1"], int)

    def test_blank_cells_become_null_not_empty_strings(self, tmp_path):
        rows = list(read_rows_after(write_csv(tmp_path / "f.csv", 2), None))
        assert rows[1]["event"] is None

    def test_resumes_after_an_index(self, tmp_path):
        rows = list(read_rows_after(write_csv(tmp_path / "f.csv", 5), 2))
        assert [r["index"] for r in rows] == [3, 4]

    def test_unknown_columns_pass_through_as_text(self):
        assert parse_csv_row({"note": "x"})["note"] == "x"


class TestFullSync:
    def test_sends_everything_in_dependency_order(self, rig):
        outbox, cloud, syncer, tmp_path = rig
        add_flight(outbox, tmp_path, rows=5)
        status = syncer.sync_once()

        assert cloud.drones == {"cf-1": "uuid-cf-1"}
        assert cloud.sessions[0]["drone_id"] == "uuid-cf-1"
        assert cloud.flights[0]["drone_id"] == "uuid-cf-1"
        assert sorted(cloud.telemetry["flight-1"]) == [0, 1, 2, 3, 4]
        assert cloud.uploads[0][0] == "flight-1.csv.gz"
        assert cloud.backfills == [("flight-1", "flight-1.csv.gz")]
        assert status.everything_sent

    def test_local_bookkeeping_never_reaches_the_server(self, rig):
        outbox, cloud, syncer, tmp_path = rig
        add_flight(outbox, tmp_path)
        syncer.sync_once()
        assert "csv_path" not in cloud.flights[0]
        assert "drone_hardware_id" not in cloud.flights[0]
        assert "rows_written" not in cloud.flights[0]

    def test_a_second_pass_sends_nothing_again(self, rig):
        outbox, cloud, syncer, tmp_path = rig
        add_flight(outbox, tmp_path)
        syncer.sync_once()
        before = (len(cloud.uploads), len(cloud.audit), dict(cloud.telemetry["flight-1"]))
        syncer.sync_once()
        assert (len(cloud.uploads), len(cloud.audit), cloud.telemetry["flight-1"]) == before


class TestResuming:
    def test_only_missing_rows_are_sent(self, rig):
        outbox, cloud, syncer, tmp_path = rig
        add_flight(outbox, tmp_path, rows=10)
        cloud.telemetry["flight-1"] = {i: {"index": i} for i in range(4)}   # server already has 0–3
        sent: list[list[dict]] = []
        original = cloud.insert_telemetry
        cloud.insert_telemetry = lambda rows: (sent.append(list(rows)), original(rows))[1]

        syncer.sync_once()
        assert [r["index"] for batch in sent for r in batch] == [4, 5, 6, 7, 8, 9]

    def test_a_flight_still_in_the_air_keeps_streaming_and_stays_pending(self, rig):
        outbox, cloud, syncer, tmp_path = rig
        add_flight(outbox, tmp_path, rows=3, ended=False)
        status = syncer.sync_once()
        assert sorted(cloud.telemetry["flight-1"]) == [0, 1, 2]
        assert cloud.uploads == []             # the file goes up after landing
        assert status.pending_flights == 1

    def test_an_incomplete_upload_stays_pending(self, rig):
        outbox, cloud, syncer, tmp_path = rig
        add_flight(outbox, tmp_path, rows=10)
        outbox.update(Kind.FLIGHT, "flight-1", lambda p: p.update({"rows_written": 12}))
        status = syncer.sync_once()
        assert status.pending_flights == 1

    def test_a_missing_csv_still_records_the_flight(self, rig):
        outbox, cloud, syncer, tmp_path = rig
        add_flight(outbox, tmp_path)
        outbox.update(Kind.FLIGHT, "flight-1", lambda p: p.update({"csv_path": "/nope.csv"}))
        status = syncer.sync_once()
        assert cloud.flights[0]["id"] == "flight-1"
        assert status.everything_sent


class TestOffline:
    def test_signed_out_keeps_everything_local(self, rig):
        outbox, cloud, _, tmp_path = rig
        add_flight(outbox, tmp_path)
        offline = Syncer(outbox, lambda: None, sleep=lambda s: None)
        status = offline.sync_once()
        assert status.pending_flights == 1
        assert cloud.flights == []
        assert "saved on this computer" in (status.last_error or "")

    def test_a_network_failure_leaves_records_for_next_time(self, rig):
        outbox, cloud, syncer, tmp_path = rig
        add_flight(outbox, tmp_path)
        cloud.fail_with = CloudError("connection refused")
        status = syncer.sync_once()
        assert status.pending_flights == 1 and status.last_error

        cloud.fail_with = None
        assert syncer.sync_once().everything_sent
        assert sorted(cloud.telemetry["flight-1"]) == [0, 1, 2, 3, 4]


class TestAudit:
    def test_events_go_first_and_are_removed_once_stored(self, rig):
        outbox, cloud, syncer, _ = rig
        log = AuditLog(outbox, actor_id="user-1", actor_email="ada@example.com")
        log.record(Action.SESSION_START, session_id="session-1", drone_hardware_id="cf-1")
        log.record(Action.EMERGENCY_STOP, Result.ABORTED, detail={"height_m": 0.3})

        syncer.sync_once()
        assert [e["action"] for e in cloud.audit] == ["session_start", "emergency_stop"]
        assert cloud.audit[0]["actor_email"] == "ada@example.com"
        assert cloud.audit[1]["result"] == "aborted"
        assert outbox.count_pending(Kind.AUDIT) == 0

    def test_events_survive_a_failed_pass_without_duplicating(self, rig):
        outbox, cloud, syncer, _ = rig
        AuditLog(outbox, actor_id="u", actor_email="a@b.c").record(Action.SIGN_IN)
        cloud.fail_with = CloudError("offline")
        syncer.sync_once()
        assert outbox.count_pending(Kind.AUDIT) == 1

        cloud.fail_with = None
        syncer.sync_once()
        syncer.sync_once()
        assert len(cloud.audit) == 1

    def test_audit_needs_no_flight_or_session_to_exist(self, rig):
        outbox, cloud, syncer, _ = rig
        AuditLog(outbox, actor_id="u", actor_email="a@b.c").record(
            Action.GUARD_ABORT, Result.ABORTED, flight_id="never-uploaded")
        syncer.sync_once()
        assert cloud.audit[0]["flight_id"] == "never-uploaded"


class TestOutbox:
    def test_records_survive_a_restart(self, tmp_path):
        outbox = Outbox(tmp_path / "outbox")
        outbox.put(Kind.FLIGHT, "f1", {"id": "f1"})
        assert Outbox(tmp_path / "outbox").count_pending(Kind.FLIGHT) == 1

    def test_unreadable_records_are_skipped_not_fatal(self, tmp_path):
        outbox = Outbox(tmp_path / "outbox")
        outbox.put(Kind.AUDIT, "good", {"id": "good"})
        (tmp_path / "outbox" / "audit" / "broken.json").write_text("{ half written")
        assert [r.id for r in outbox.pending(Kind.AUDIT)] == ["good"]
