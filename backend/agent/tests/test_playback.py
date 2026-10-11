"""Mission playback (cropwatcher/playback.py, GET /history/flights/{id}/playback):
a flight's files read back exactly, on the mission report's clock, with its
gaps and events in words — and the edges: no trace, no plan, too long, a bad
id, no token."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cropwatcher import playback
from cropwatcher.mission.review import load as load_report
from tests.mission.plans import mission, room
from tests.test_api import auth, client  # noqa: F401  (the fixture)

BASE = datetime(2026, 10, 11, 10, 0, 0, tzinfo=UTC)
FLIGHT = "b2c3d4e5-0000-4000-8000-000000000002"

# tenths of a second — a hand-built flight, every event known:
#   0      armed;  5 flying (took off)
#   40–49  base stations lost (1.0 s);  60–62 lost again (0.3 s)
#   80–130 P1 stamped (holding)
#   140    ↑ held until 150 (the operator takes over)
#   171–184  no samples at all (a gap: 1.4 s lost on the link)
#   200    landing;  230 landed;  the recording ends at 240
LAST = 240
GAP = range(171, 185)


def _lost(i: int) -> bool:
    return 40 <= i < 50 or 60 <= i < 63


def _state(i: int) -> str:
    return ("armed" if i < 5 else "flying" if i < 200 else "landing" if i < 230 else "landed")


def write_flight(root: Path, flight_id: str = FLIGHT, *, keep_plan: bool = True,
                 keep_trace: bool = True, last: int = LAST) -> None:
    day = root / "flights" / "2026-10-11"
    day.mkdir(parents=True, exist_ok=True)
    with (day / f"flight_{flight_id[:8]}_2026-10-11_10-00-00.csv").open(
            "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["index", "recorded_at", "flight_id", "temp_unit", "corrected_temp",
                    "station_pressure_hpa", "battery_v", "thrust", "x_m", "y_m", "z_m",
                    "vx_m_s", "vy_m_s", "vz_m_s", "roll_deg", "pitch_deg", "yaw_deg",
                    "lighthouse_received", "point_id"])
        for i in range(last + 1):
            if i in GAP:
                continue
            w.writerow([i, (BASE + timedelta(seconds=i / 10)).isoformat(), flight_id, "C",
                        22.5, 1013.2, 4.1 - i / 1000, 50000, -1.0 + i / 240, -1.0, 0.4,
                        0.3, 0.4, 0.0, 1.0, -1.0, 5.0, 0 if _lost(i) else 2,
                        "P1" if 80 <= i <= 130 else ""])
    if keep_trace:
        with (day / f"trace_{flight_id[:8]}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["recorded_at", "control_state", "keys", "target_height_m",
                        "target_x_m", "target_y_m", "drift_m", "stateEstimate.z",
                        "posCtl.targetZ"])
            for i in range(last + 1):
                w.writerow([(BASE + timedelta(seconds=i / 10)).isoformat(), _state(i),
                            "ArrowUp" if 140 <= i < 150 else "", 0.4, -1.0, 0.9, 0.05,
                            1.83, 1.80])
    session = root / "sessions" / "s1"
    session.mkdir(parents=True, exist_ok=True)
    meta = session / "meta.json"
    flights = json.loads(meta.read_text())["flights"] if meta.exists() else []
    meta.write_text(json.dumps({"flights": [*flights, {"id": flight_id}]}))
    if keep_plan:
        (session / "missions").mkdir(exist_ok=True)
        (session / "missions" / f"{flight_id}.json").write_text(json.dumps(
            {"flight_id": flight_id, "mission": mission().to_dict(), "room": room().to_dict(),
             "moves": [{"point_id": "P1", "distance_m": 0.1}]}))


def kinds_and_texts(p: playback.Playback) -> list[tuple[str, str]]:
    return [(e["kind"], e["text"]) for e in p.events]


# ── reading the files ─────────────────────────────────────────────────────


def test_every_sample_comes_back_exactly_on_the_reports_clock(tmp_path):
    write_flight(tmp_path)
    p = playback.load(tmp_path, FLIGHT)
    assert len(p.samples) == LAST + 1 - len(GAP)
    assert len(p.control) == LAST + 1
    first, row80 = p.samples[0], next(s for s in p.samples if s["t_s"] == pytest.approx(8.0))
    assert first["t_s"] == 0.0 and p.duration_s == pytest.approx(24.0)
    assert row80["x_m"] == pytest.approx(-1.0 + 80 / 240, abs=1e-4)
    assert row80["z_m"] == pytest.approx(0.4) and row80["point_id"] == "P1"
    assert row80["speed_m_s"] == pytest.approx(0.5)            # hypot(0.3, 0.4)
    assert row80["battery_v"] == pytest.approx(4.02) and row80["temp"] == pytest.approx(22.5)
    assert p.temp_unit == "C" and p.started_at == BASE.isoformat()
    held = next(c for c in p.control if c["t_s"] == pytest.approx(14.0))
    assert held["keys"] == "ArrowUp" and held["target"] == [-1.0, 0.9, 0.4]
    assert held["height_error_m"] == pytest.approx(0.03)
    # The report and playback agree on when things happened.
    report = load_report(tmp_path, FLIGHT)
    assert p.report == report.to_dict()


def test_the_plan_flown_and_its_room_come_back(tmp_path):
    write_flight(tmp_path)
    p = playback.load(tmp_path, FLIGHT)
    kept = json.loads((tmp_path / "sessions" / "s1" / "missions" / f"{FLIGHT}.json").read_text())
    assert p.mission is not None and p.room is not None
    assert p.mission.to_dict() == kept["mission"] and p.room.to_dict() == kept["room"]
    assert p.moves == [{"point_id": "P1", "distance_m": 0.1}]
    assert p.notes == []


def test_a_gap_in_the_samples_is_found_and_said(tmp_path):
    write_flight(tmp_path)
    p = playback.load(tmp_path, FLIGHT)
    assert p.gaps == [{"from_s": 17.0, "to_s": 18.5}]
    assert ("gap", "No samples for 1.5 s — data lost on the link") in kinds_and_texts(p)


def test_the_events_say_what_happened_in_order(tmp_path):
    write_flight(tmp_path)
    p = playback.load(tmp_path, FLIGHT)
    said = kinds_and_texts(p)
    assert said[:2] == [("state", "Armed"), ("state", "Took off")]
    assert ("hold", "Holding at P1") in said and ("hold", "P1 hold ended") in said
    assert ("keys", "Operator held ArrowUp") in said and ("keys", "Keys released") in said
    assert said[-2:] == [("state", "Landing"), ("state", "Landed")]
    times = [e["t_s"] for e in p.events]
    assert times == sorted(times)
    hold = next(e for e in p.events if e["text"] == "Holding at P1")
    assert hold["t_s"] == pytest.approx(8.0) and hold["point_id"] == "P1"


def test_each_stretch_without_base_stations_is_one_event_with_its_length(tmp_path):
    write_flight(tmp_path)
    p = playback.load(tmp_path, FLIGHT)
    lost = [e for e in p.events if e["kind"] == "position"]
    assert [e["t_s"] for e in lost] == [pytest.approx(4.0), pytest.approx(6.0)]
    assert "lost for 1.0 s" in lost[0]["text"] and "lost for 0.3 s" in lost[1]["text"]
    assert next(s for s in p.samples if s["t_s"] == pytest.approx(4.5))["positioned"] is False


def test_base_stations_lost_to_the_end_is_said(tmp_path):
    write_flight(tmp_path, last=45)                    # ends inside the first stretch
    p = playback.load(tmp_path, FLIGHT)
    assert any(e["text"].startswith("Base stations lost until the recording stops")
               for e in p.events)


def test_a_hold_cut_off_by_the_end_of_the_recording_is_said(tmp_path):
    write_flight(tmp_path, last=100)                   # ends mid-hold at P1
    p = playback.load(tmp_path, FLIGHT)
    assert ("hold", "P1 hold ended — the recording stops") in kinds_and_texts(p)


# ── the edges ─────────────────────────────────────────────────────────────


def test_no_trace_still_plays_and_says_what_is_missing(tmp_path):
    write_flight(tmp_path, keep_trace=False)
    p = playback.load(tmp_path, FLIGHT)
    assert p.control == [] and len(p.samples) > 0
    assert any("no control trace" in n for n in p.notes)
    assert not any(e["kind"] in ("state", "keys") for e in p.events)


def test_a_flight_with_no_plan_plays_over_the_default_area(tmp_path):
    write_flight(tmp_path, keep_plan=False)
    p = playback.load(tmp_path, FLIGHT)
    assert p.mission is None and p.room is None and p.report is None
    assert any("kept no plan" in n for n in p.notes)


def test_an_unreadable_plan_is_said_not_fatal(tmp_path):
    write_flight(tmp_path)
    (tmp_path / "sessions" / "s1" / "missions" / f"{FLIGHT}.json").write_text("{not json")
    p = playback.load(tmp_path, FLIGHT)
    assert p.mission is None and len(p.samples) > 0
    assert any("could not be read" in n for n in p.notes)


def test_a_flight_longer_than_playback_holds_is_cut_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(playback, "MAX_ROWS", 50)
    write_flight(tmp_path)
    p = playback.load(tmp_path, FLIGHT)
    assert len(p.samples) == 50 and len(p.control) == 50 and p.truncated
    assert any("longer than playback holds" in n for n in p.notes)


def test_an_unknown_flight_is_said_in_words(tmp_path):
    with pytest.raises(playback.PlaybackError, match="No readings"):
        playback.load(tmp_path, FLIGHT)


def test_it_never_writes(tmp_path):
    write_flight(tmp_path)
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    playback.load(tmp_path, FLIGHT)
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


# ── the API ───────────────────────────────────────────────────────────────


class TestPlaybackApi:
    def test_it_needs_the_token(self, client):  # noqa: F811
        assert client.get(f"/history/flights/{FLIGHT}/playback").status_code == 401

    def test_a_mission_flight_comes_with_its_room_and_plan_as_the_map_draws_them(
            self, client, tmp_path):  # noqa: F811
        write_flight(tmp_path)
        body = client.get(f"/history/flights/{FLIGHT}/playback", headers=auth(client)).json()
        assert body["flight_id"] == FLIGHT and body["duration_s"] == pytest.approx(24.0)
        assert body["room"]["id"] == "lab" and body["room"]["outer"]["vertices"]
        assert body["outer"] == body["room"]["outer"]
        assert body["mission"]["id"] == "m1" and "problems" in body["mission"]
        assert body["report"]["legs"][0]["to"] == "P1"
        assert len(body["samples"]) == LAST + 1 - len(GAP) and body["events"]
        assert body["gaps"] == [{"from_s": 17.0, "to_s": 18.5}]

    def test_a_flight_with_no_plan_gets_the_default_area(self, client, tmp_path):  # noqa: F811
        write_flight(tmp_path, keep_plan=False)
        body = client.get(f"/history/flights/{FLIGHT}/playback", headers=auth(client)).json()
        assert body["room"] is None and body["mission"] is None
        assert body["outer"]["vertices"] and body["outer"]["measured"] is False

    def test_an_unknown_flight_is_a_404_in_words(self, client):  # noqa: F811
        response = client.get(f"/history/flights/{FLIGHT}/playback", headers=auth(client))
        assert response.status_code == 404
        assert "No readings" in response.json()["detail"]

    @pytest.mark.parametrize("bad", ["..%2F..%2Fetc", "a.b", "x" * 65])
    def test_a_flight_id_is_never_a_path(self, client, bad):  # noqa: F811
        response = client.get(f"/history/flights/{bad}/playback", headers=auth(client))
        assert response.status_code == 404
