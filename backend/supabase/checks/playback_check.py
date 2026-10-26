"""Prove migration 20261011000019 (flight_plans, flight_traces: what playback
needs beyond telemetry) against a running database, beside results_check.py.

Operators A and B, and a viewer V. A flies a flight. Checks BOTH directions —
what must be allowed and what must be refused (rls-and-grants.txt: a test that
only checks denial proves nothing):

  A uploads the plan as flown and trace rows for A's flight; a re-send is
  ignored, never an update; B and V read both (everyone's flights play back);
  B cannot upload for A's flight — refused BY THE POLICY, not "permission
  denied", so the grant is there; V cannot upload; anonymous reads nothing;
  nobody updates or deletes a row; the flight list's embed says which flights
  have a plan; deleting the flight takes its plan and trace with it.

Then the agent's REAL client (dronedeck.sync.cloud.SupabaseCloud) as A, over
2 500 telemetry and 2 500 trace rows — past PostgREST's 1 000-row page — and
playback.load_cloud on what it reads back.

Runs against the LOCAL stack (`cd backend && supabase start`), with the agent's
venv for the second half. Creates its own users and rows and deletes them
after. Exit code 0 = every check held.

    backend/agent/.venv/bin/python backend/supabase/checks/playback_check.py
"""
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))

from results_check import (  # noqa: E402
    ANON,
    API,
    PREFER,
    call,
    check,
    cleanup,
    results,
    sql,
    user,
)

IGNORE = {"Prefer": "resolution=ignore-duplicates,return=representation"}
T0 = datetime(2026, 10, 11, 10, 0, 0, tzinfo=UTC)
ROWS = 2500


def plan(flight):
    return {"flight_id": flight,
            "mission": {"id": "m1", "name": "Pump check", "room_id": "lab", "home": [0, 0],
                        "points": [], "cruise_height_m": 0.4, "return_to_start": True},
            "room": {"id": "lab", "name": "Lab"}, "moves": []}


def trace(flight, seq):
    return {"flight_id": flight, "seq": seq,
            "recorded_at": (T0 + timedelta(seconds=seq / 10)).isoformat(),
            "control_state": "flying", "keys": None, "target_x_m": 0.1,
            "target_y_m": 0.2, "target_height_m": 0.4, "drift_m": 0.03,
            "height_error_m": 0.01, "values": {"stateEstimate.x": 0.1}}


def main():
    tag = uuid.uuid4().hex[:8]
    a_id, a = user(f"pb-a-{tag}@check.local", "operator")
    b_id, b = user(f"pb-b-{tag}@check.local", "operator")
    v_id, v = user(f"pb-v-{tag}@check.local", "viewer")
    session, flight = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        call("POST", "/rest/v1/sessions", a, {"id": session, "operator_id": a_id})
        status, body = call("POST", "/rest/v1/flights", a,
                            {"id": flight, "session_id": session, "created_by": a_id,
                             "status": "completed", "mode": "auto"}, PREFER)
        assert status == 201, body

        status, _ = call("POST", "/rest/v1/flight_plans", a, plan(flight), PREFER)
        check("A uploads the plan as flown for A's flight", status == 201, status)
        status, _ = call("POST", "/rest/v1/flight_traces", a,
                         [trace(flight, s) for s in (1, 2, 3)], PREFER)
        check("A uploads trace rows for A's flight", status == 201, status)
        status, _ = call("POST", "/rest/v1/flight_plans?on_conflict=flight_id", a,
                         {**plan(flight), "moves": [{"point_id": "P9"}]}, IGNORE)
        _, kept = call("GET", f"/rest/v1/flight_plans?flight_id=eq.{flight}", a)
        check("a re-sent plan is ignored, never an update",
              status in (200, 201) and len(kept) == 1 and kept[0]["moves"] == [],
              f"{status} {kept}")
        status, _ = call("POST", "/rest/v1/flight_traces?on_conflict=flight_id,seq", a,
                         [trace(flight, 2)], IGNORE)
        _, rows = call("GET", f"/rest/v1/flight_traces?flight_id=eq.{flight}&select=seq", a)
        check("a re-sent trace row changes nothing", status in (200, 201) and len(rows) == 3,
              f"{status} {len(rows)}")

        for who, token in (("B", b), ("V", v)):
            s1, p = call("GET", f"/rest/v1/flight_plans?flight_id=eq.{flight}", token)
            s2, t = call("GET", f"/rest/v1/flight_traces?flight_id=eq.{flight}", token)
            check(f"{who} reads A's plan and trace (everyone's flights play back)",
                  s1 == 200 and len(p) == 1 and s2 == 200 and len(t) == 3, f"{s1} {s2}")

        status, body = call("POST", "/rest/v1/flight_plans", b, plan(flight), PREFER)
        check("B cannot upload a plan for A's flight — by the policy, not the grant",
              status == 403 and "row-level security" in str(body), f"{status} {body}")
        status, body = call("POST", "/rest/v1/flight_traces", b, [trace(flight, 9)], PREFER)
        check("B cannot upload a trace for A's flight — by the policy",
              status == 403 and "row-level security" in str(body), f"{status} {body}")
        status, _ = call("POST", "/rest/v1/flight_traces", v, [trace(flight, 10)], PREFER)
        check("V, a viewer, cannot upload", status in (401, 403), status)

        status, body = call("GET", f"/rest/v1/flight_plans?flight_id=eq.{flight}", ANON)
        check("anonymous reads no plan", status in (401, 403) or body == [], f"{status}")
        status, body = call("GET", f"/rest/v1/flight_traces?flight_id=eq.{flight}", ANON)
        check("anonymous reads no trace", status in (401, 403) or body == [], f"{status}")

        status, _ = call("PATCH", f"/rest/v1/flight_plans?flight_id=eq.{flight}", a,
                         {"moves": [{"point_id": "X"}]}, PREFER)
        _, kept = call("GET", f"/rest/v1/flight_plans?flight_id=eq.{flight}", a)
        check("A cannot edit the plan", status in (401, 403) and kept[0]["moves"] == [],
              status)
        status, _ = call("DELETE", f"/rest/v1/flight_traces?flight_id=eq.{flight}", a, None,
                         PREFER)
        _, rows = call("GET", f"/rest/v1/flight_traces?flight_id=eq.{flight}&select=seq", a)
        check("A cannot delete the trace", status in (401, 403) and len(rows) == 3, status)

        status, listed = call("GET", f"/rest/v1/flights?id=eq.{flight}"
                                     "&select=id,operator_email,flight_plans(flight_id)", b)
        check("the flight list's embed says the flight has a plan",
              status == 200 and listed and listed[0]["flight_plans"], f"{status} {listed}")

        real_client(a_id, f"pb-a-{tag}@check.local", session)

        sql(f"delete from public.flights where id = '{flight}'")
        left = sql(f"select (select count(*) from public.flight_plans where flight_id = "
                   f"'{flight}') + (select count(*) from public.flight_traces where "
                   f"flight_id = '{flight}')")
        check("deleting the flight takes its plan and trace with it", left == "0", left)
    finally:
        cleanup([a_id, b_id, v_id], [session])

    print(f"\n{sum(results)}/{len(results)} checks held")
    return 0 if all(results) else 1


def real_client(a_id, email, session):
    """The agent's own client, signed in as A: upload, page past 1 000 rows,
    list, and play back what it reads."""
    from dronedeck import playback
    from dronedeck.sync.cloud import SupabaseCloud

    cloud = SupabaseCloud(API, ANON)
    cloud.sign_in(email, "check-pipeline-1")
    flight = str(uuid.uuid4())
    cloud.upsert_flight({"id": flight, "session_id": session, "created_by": a_id,
                         "status": "completed", "mode": "auto",
                         "started_at": T0.isoformat()})
    telemetry = [{"flight_id": flight, "index": i, "temp_unit": "C",
                  "recorded_at": (T0 + timedelta(seconds=i / 10)).isoformat(),
                  "x_m": i / 1000, "y_m": 0.0, "z_m": 0.4, "lighthouse_received": 2}
                 for i in range(ROWS)]
    for start in range(0, ROWS, 500):
        cloud.insert_telemetry(telemetry[start:start + 500])
    traces = [trace(flight, s) for s in range(1, ROWS + 1)]
    for start in range(0, ROWS, 500):
        cloud.insert_flight_traces(traces[start:start + 500])
    cloud.insert_flight_plan(plan(flight))
    cloud.insert_flight_plan(plan(flight))                  # a re-send: ignored

    read = cloud.read_telemetry(flight, 36_001)
    check("the real client pages telemetry past 1 000 rows, in order",
          [r["index"] for r in read] == list(range(ROWS)), len(read))
    read_traces = cloud.read_flight_traces(flight, 36_001)
    check("the real client pages the trace past 1 000 rows, flattened",
          [r["seq"] for r in read_traces] == list(range(1, ROWS + 1))
          and read_traces[0]["stateEstimate.x"] == 0.1, len(read_traces))
    capped = cloud.read_telemetry(flight, 1200)
    check("a read stops at its limit", len(capped) == 1200, len(capped))
    listed = [f for f in cloud.list_flights(300) if f["id"] == flight]
    check("the real client lists the flight, with its plan and owner",
          listed and listed[0]["has_plan"] and listed[0]["operator_email"] == email, listed)
    played = playback.load_cloud(cloud, flight)
    check("playback.load_cloud plays it: every sample, the trace, the plan",
          len(played.samples) == ROWS and len(played.control) == ROWS
          and played.mission is not None and played.source == playback.SUPABASE,
          f"{len(played.samples)} {len(played.control)} {played.notes}")
    cloud.sign_out()


if __name__ == "__main__":
    sys.exit(main())
