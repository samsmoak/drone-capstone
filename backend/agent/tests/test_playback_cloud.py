"""Playback from Supabase (migration 20261011000019): the plan as flown and the
control trace uploaded by the syncer (sync/flight_playback.py), read back by
playback.load_cloud — a flight from Supabase plays EXACTLY as it does from the
files — the flight list merging this laptop's flights with everyone's, and the
API choosing this laptop first, Supabase for the rest."""

from __future__ import annotations

import json

import pytest

from dronedeck import playback
from dronedeck.api import rest
from dronedeck.sync import flight_playback
from dronedeck.sync.outbox import Kind, Outbox
from dronedeck.sync.syncer import Syncer, read_rows_after
from tests.test_api import auth, client  # noqa: F401  (the fixture)
from tests.test_playback import FLIGHT, LAST, write_flight
from tests.test_sync import FakeCloud

OTHER = "c3d4e5f6-0000-4000-8000-000000000003"     # a flight flown on another computer


def flight_record(outbox: Outbox, root, flight_id: str = FLIGHT, *, sent: bool = True,
                  mode: str = "auto") -> None:
    outbox.put(Kind.FLIGHT, flight_id, {
        "id": flight_id, "session_id": "s1", "started_at": "2026-10-11T10:00:00+00:00",
        "ended_at": "2026-10-11T10:00:24+00:00", "status": "completed", "mode": mode,
        "rows_written": LAST, "_sent": sent,
    })


def uploaded(root, outbox: Outbox, cloud: FakeCloud, flight_id: str = FLIGHT) -> None:
    """What reaches Supabase for a flight: its telemetry (the syncer's own
    parsing of the CSV) and, through _send_playback, its plan and trace."""
    files = playback.files_of(root, flight_id)
    cloud.insert_telemetry(list(read_rows_after(files.csv, None)))
    cloud.flights.append({"id": flight_id, "mode": "auto",
                          "started_at": "2026-10-11T10:00:00+00:00",
                          "operator_email": "ada@example.com", "operator_name": "Ada"})
    flight_playback.queue(outbox, flight_id)
    Syncer(outbox, lambda: cloud, sleep=lambda s: None, data_root=root)._send_playback(cloud)


@pytest.fixture
def rig(tmp_path):
    root = tmp_path / "data"
    write_flight(root)
    outbox = Outbox(tmp_path / "outbox")
    flight_record(outbox, root)
    return root, outbox, FakeCloud()


# ── the upload ────────────────────────────────────────────────────────────


def test_the_plan_and_every_trace_row_reach_supabase(rig):
    root, outbox, cloud = rig
    uploaded(root, outbox, cloud)
    kept = json.loads((root / "sessions" / "s1" / "missions" / f"{FLIGHT}.json").read_text())
    assert cloud.plans[FLIGHT]["mission"] == kept["mission"]
    assert cloud.plans[FLIGHT]["room"] == kept["room"]
    assert cloud.plans[FLIGHT]["moves"] == kept["moves"]
    assert sorted(cloud.traces[FLIGHT]) == list(range(1, LAST + 2))
    row = cloud.traces[FLIGHT][141]                       # seq 141 = the trace's t 14.0 s
    assert row["keys"] == "ArrowUp" and row["control_state"] == "flying"
    assert row["target_x_m"] == -1.0 and row["height_error_m"] == pytest.approx(0.03)
    assert row["values"]["stateEstimate.z"] == pytest.approx(1.83)   # nothing dropped
    assert outbox.get(Kind.PLAYBACK, FLIGHT)["_sent"] is True


def test_it_waits_for_the_flight_row(rig):
    root, outbox, cloud = rig
    flight_record(outbox, root, sent=False)               # the flight's row not up yet
    flight_playback.queue(outbox, FLIGHT)
    Syncer(outbox, lambda: cloud, data_root=root)._send_playback(cloud)
    assert not hasattr(cloud, "plans") and not hasattr(cloud, "traces")
    assert not outbox.get(Kind.PLAYBACK, FLIGHT).get("_sent")


def test_an_interrupted_trace_resumes_from_its_cursor(rig, monkeypatch):
    root, outbox, cloud = rig
    monkeypatch.setattr(flight_playback, "BATCH", 100)
    calls = {"n": 0}
    original = cloud.insert_flight_traces

    def flaky(rows):
        calls["n"] += 1
        if calls["n"] == 2:
            from dronedeck.sync.cloud import CloudError
            raise CloudError("the network dropped")
        original(rows)

    cloud.insert_flight_traces = flaky
    flight_playback.queue(outbox, FLIGHT)
    syncer = Syncer(outbox, lambda: cloud, data_root=root)
    with pytest.raises(Exception, match="network"):
        syncer._send_playback(cloud)
    assert outbox.get(Kind.PLAYBACK, FLIGHT)["uploaded_through"] == 100
    assert outbox.get(Kind.PLAYBACK, FLIGHT)["plan_sent"] is True
    syncer._send_playback(cloud)
    assert sorted(cloud.traces[FLIGHT]) == list(range(1, LAST + 2))
    assert len(cloud.plans) == 1


def test_a_refused_flight_is_given_up_not_retried_forever(rig):
    root, outbox, cloud = rig
    cloud.refuse = {FLIGHT}
    flight_playback.queue(outbox, FLIGHT)
    Syncer(outbox, lambda: cloud, data_root=root)._send_playback(cloud)
    assert outbox.get(Kind.PLAYBACK, FLIGHT)["_sent"] is True


def test_a_flight_whose_files_are_gone_is_given_up(rig, tmp_path):
    root, outbox, cloud = rig
    flight_record(outbox, root, OTHER)
    flight_playback.queue(outbox, OTHER)
    Syncer(outbox, lambda: cloud, data_root=root)._send_playback(cloud)
    assert outbox.get(Kind.PLAYBACK, OTHER)["_sent"] is True


def test_queueing_is_once_and_past_flights_are_found(rig):
    root, outbox, cloud = rig
    assert flight_playback.queue_past_flights(outbox) == [FLIGHT]
    outbox.update(Kind.PLAYBACK, FLIGHT, lambda p: p.__setitem__("uploaded_through", 7))
    flight_playback.queue(outbox, FLIGHT)                 # again: keeps the cursor
    assert outbox.get(Kind.PLAYBACK, FLIGHT)["uploaded_through"] == 7
    assert flight_playback.queue_past_flights(outbox) == []
    outbox.put(Kind.FLIGHT, OTHER, {"id": OTHER, "ended_at": None})   # still flying
    assert flight_playback.queue_past_flights(outbox) == []


# ── the same flight, from either copy ─────────────────────────────────────


def test_a_flight_from_supabase_plays_exactly_as_from_the_files(rig):
    root, outbox, cloud = rig
    uploaded(root, outbox, cloud)
    here = playback.load(root, FLIGHT)
    there = playback.load_cloud(cloud, FLIGHT)
    assert here.source == playback.THIS_COMPUTER and there.source == playback.SUPABASE
    for field in ("duration_s", "temp_unit", "samples", "control", "gaps", "events",
                  "moves", "report", "truncated"):
        assert getattr(there, field) == getattr(here, field), field
    assert there.mission is not None and here.mission is not None
    assert there.mission.to_dict() == here.mission.to_dict()
    assert there.room is not None and here.room is not None
    assert there.room.to_dict() == here.room.to_dict()


def test_before_its_trace_and_plan_are_uploaded_it_still_plays_and_says_why(rig):
    root, outbox, cloud = rig
    cloud.insert_telemetry(list(read_rows_after(playback.files_of(root, FLIGHT).csv, None)))
    p = playback.load_cloud(cloud, FLIGHT)
    assert len(p.samples) > 0 and p.control == [] and p.mission is None
    assert any("has none until that computer uploads it" in n for n in p.notes)
    assert any("has not uploaded it yet" in n for n in p.notes)


def test_a_flight_nobody_has_is_said_in_words():
    with pytest.raises(playback.PlaybackError, match="no readings in Supabase"):
        playback.load_cloud(FakeCloud(), OTHER)


def test_this_laptop_first_then_supabase_then_a_reason(rig, tmp_path):
    root, outbox, cloud = rig
    uploaded(root, outbox, cloud)
    assert playback.load_any(root, FLIGHT, lambda: cloud).source == playback.THIS_COMPUTER
    elsewhere = tmp_path / "another-laptop"
    elsewhere.mkdir()
    assert playback.load_any(elsewhere, FLIGHT, lambda: cloud).source == playback.SUPABASE
    with pytest.raises(playback.PlaybackError, match="Sign in"):
        playback.load_any(elsewhere, FLIGHT, lambda: None)


# ── the list ──────────────────────────────────────────────────────────────


def test_the_list_merges_each_flight_once_newest_first(rig):
    root, outbox, cloud = rig
    sessions = [{"id": "s1", "operator_email": "me@example.com", "operator_name": None,
                 "flights": [{"id": FLIGHT, "mode": "auto", "program": "mission",
                              "started_at": "2026-10-11T10:00:00+00:00"}]}]
    cloud_rows = [
        {"id": FLIGHT, "mode": "auto", "started_at": "2026-10-11T10:00:00+00:00",
         "operator_email": "me@example.com", "operator_name": "Me", "has_plan": True},
        {"id": OTHER, "mode": "manual", "started_at": "2026-10-11T11:00:00+00:00",
         "operator_email": "ada@example.com", "operator_name": "Ada", "has_plan": False},
    ]
    listed = playback.list_flights(root, sessions, cloud_rows, lambda f: "uploading")
    assert [f["id"] for f in listed] == [OTHER, FLIGHT]
    mine, theirs = listed[1], listed[0]
    assert mine["source"] == playback.THIS_COMPUTER and mine["on_this_computer"]
    assert mine["in_supabase"] and mine["upload"] == "uploading"
    assert mine["operator_name"] == "Me"                  # filled from Supabase
    assert mine["has_plan"] is True
    assert theirs["source"] == playback.SUPABASE and not theirs["on_this_computer"]
    assert theirs["upload"] is None
    only_auto = playback.list_flights(root, sessions, cloud_rows, lambda f: None, mode="auto")
    assert [f["id"] for f in only_auto] == [FLIGHT]


def test_signed_out_the_list_is_this_laptops_flights(rig):
    root, _, _ = rig
    sessions = [{"id": "s1", "flights": [{"id": FLIGHT, "mode": "auto"}]}]
    listed = playback.list_flights(root, sessions, None, lambda f: None)
    assert [(f["id"], f["in_supabase"], f["has_plan"]) for f in listed] == [(FLIGHT, False, True)]


# ── the API ───────────────────────────────────────────────────────────────


class TestApi:
    def test_the_list_needs_the_token(self, client):  # noqa: F811
        assert client.get("/history/flights").status_code == 401

    def test_signed_out_it_lists_this_laptop_and_says_why_not_more(self, client):  # noqa: F811
        body = client.get("/history/flights", headers=auth(client)).json()
        assert body["cloud"] == "signed_out" and body["flights"] == []

    def test_signed_in_it_lists_everyones_and_plays_one_from_supabase(
            self, client, tmp_path, monkeypatch):  # noqa: F811
        cloud = FakeCloud()
        root = tmp_path / "elsewhere"
        write_flight(root)
        outbox = Outbox(tmp_path / "ob")
        flight_record(outbox, root)
        uploaded(root, outbox, cloud)
        monkeypatch.setattr(rest, "_signed_in_cloud", lambda: cloud)
        body = client.get("/history/flights", headers=auth(client)).json()
        assert body["cloud"] == "ok"
        assert [(f["id"], f["source"], f["operator_name"]) for f in body["flights"]] == \
            [(FLIGHT, "supabase", "Ada")]
        played = client.get(f"/history/flights/{FLIGHT}/playback", headers=auth(client)).json()
        assert played["source"] == "supabase" and played["mission"]["id"] == "m1"
        assert played["room"]["id"] == "lab" and len(played["samples"]) > 0

    def test_supabase_unreachable_is_a_503_in_words(self, client, monkeypatch):  # noqa: F811
        cloud = FakeCloud()
        from dronedeck.sync.cloud import CloudError
        cloud.fail_with = CloudError("could not read the flight's readings: ConnectError")
        monkeypatch.setattr(rest, "_signed_in_cloud", lambda: cloud)
        response = client.get(f"/history/flights/{OTHER}/playback", headers=auth(client))
        assert response.status_code == 503
        assert "Supabase could not be reached" in response.json()["detail"]
        listed = client.get("/history/flights", headers=auth(client)).json()
        assert listed["cloud"] == "error" and "ConnectError" in listed["cloud_error"]
