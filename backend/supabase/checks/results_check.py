"""Prove migration 20261009000016 (pipeline results) against a running
database (notifications: notifications_check.py, beside this).

Operators A and B, and a viewer V. Checks that A uploads a flight's result
and findings; B and V read them; V cannot write either; anonymous reads
nothing; re-uploading replaces; an operator retracts a finding.

Runs against the LOCAL stack (`cd backend && supabase start`): it sets each
user's role in SQL through the database container, since not even
service_role may update profiles over the API here. Creates its own users and
rows and deletes them after. Exit code 0 = every check held.

    python backend/supabase/checks/pipeline_check.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

API = os.environ.get("SUPABASE_API", "http://127.0.0.1:54321")
ANON = os.environ.get("SUPABASE_ANON", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0")
SERVICE = os.environ.get("SUPABASE_SERVICE", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU")
PREFER = {"Prefer": "return=representation"}
UPSERT = {"Prefer": "resolution=merge-duplicates,return=representation"}


def call(method, path, token, body=None, headers=None):
    request = urllib.request.Request(f"{API}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
    request.add_header("apikey", SERVICE if token == SERVICE else ANON)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        request.add_header(k, v)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


#: The local stack's database container. Roles are set in SQL: this project
#: revokes the platform's default privileges, so not even service_role may
#: update profiles over the API (20260916000004) — a role PATCH is refused.
DB_CONTAINER = os.environ.get("SUPABASE_DB_CONTAINER", "supabase_db_backend")


def set_role(uid, role):
    import subprocess
    subprocess.run(["docker", "exec", DB_CONTAINER, "psql", "-U", "postgres", "-d", "postgres",
                    "-qtc", f"update public.profiles set role = '{role}' where id = '{uid}'"],
                   check=True, capture_output=True)
    out = subprocess.run(["docker", "exec", DB_CONTAINER, "psql", "-U", "postgres", "-d",
                          "postgres", "-qtAc",
                          f"select role from public.profiles where id = '{uid}'"],
                         check=True, capture_output=True, text=True).stdout.strip()
    assert out == role, f"could not make {uid} a {role}: it is {out!r}"


def user(email, role):
    status, body = call("POST", "/auth/v1/admin/users", SERVICE,
                        {"email": email, "password": "check-pipeline-1", "email_confirm": True})
    assert status in (200, 201), body
    uid = body["id"]
    set_role(uid, role)
    _, token = call("POST", "/auth/v1/token?grant_type=password", ANON,
                    {"email": email, "password": "check-pipeline-1"})
    return uid, token["access_token"]


results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if not ok else ""))


def finding(fid, flight, session, severity):
    return {"id": fid, "flight_id": flight, "session_id": session, "signal": "temperature",
            "severity": severity, "title": f"Warmer than expected ({severity})",
            "sentence": "From 0:42 to 0:55, near P2, …", "start_index": 420, "end_index": 550,
            "t_start_s": 42.0, "t_end_s": 55.0, "unit": "C", "observed": 33.0,
            "expected": 31.1, "delta": 1.9, "z": 9.4, "point_ids": ["P2"],
            "evidence_frames": [12, 13], "image_support": "cannot_tell",
            "image_note": "2 readable frames…", "pipeline_version": "2"}


def main():
    tag = uuid.uuid4().hex[:8]
    a_id, a = user(f"res-a-{tag}@check.local", "operator")
    b_id, b = user(f"res-b-{tag}@check.local", "operator")
    v_id, v = user(f"res-v-{tag}@check.local", "viewer")
    session, flight, fid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    try:
        call("POST", "/rest/v1/sessions", a, {"id": session, "operator_id": a_id})
        call("POST", "/rest/v1/flights", a, {"id": flight, "session_id": session,
                                             "created_by": a_id})
        result = {"flight_id": flight, "session_id": session, "pipeline_version": "2",
                  "stages": {"clean": "robust@1"}, "created_at": "2026-10-09T08:00:00Z",
                  "points": [], "findings_count": 1, "worst_severity": "warning"}
        status, _ = call("POST", "/rest/v1/pipeline_results?on_conflict=flight_id", a, result,
                         UPSERT)
        check("an operator uploads a flight's result", status in (200, 201), status)
        status, _ = call("POST", "/rest/v1/pipeline_results?on_conflict=flight_id", a,
                         {**result, "findings_count": 3}, UPSERT)
        check("uploading again replaces it", status in (200, 201), status)
        _, rows = call("GET", f"/rest/v1/pipeline_results?flight_id=eq.{flight}", b)
        check("another operator reads it", rows and rows[0]["findings_count"] == 3, rows)
        _, rows = call("GET", f"/rest/v1/pipeline_results?flight_id=eq.{flight}", v)
        check("a viewer reads it", len(rows) == 1, rows)
        status, _ = call("POST", "/rest/v1/pipeline_results?on_conflict=flight_id", v, result,
                         UPSERT)
        check("a viewer cannot write a result", status in (401, 403), status)
        status, rows = call("GET", f"/rest/v1/pipeline_results?flight_id=eq.{flight}", ANON)
        check("anonymous reads nothing", status in (401, 403) or rows == [], (status, rows))
        status, _ = call("POST", "/rest/v1/pipeline_findings?on_conflict=id", a,
                         [finding(fid, flight, session, "warning")], UPSERT)
        check("an operator uploads findings", status in (200, 201), status)
        status, _ = call("POST", "/rest/v1/pipeline_findings?on_conflict=id", v,
                         [finding(str(uuid.uuid4()), flight, session, "info")], UPSERT)
        check("a viewer cannot write a finding", status in (401, 403), status)
        _, rows = call("GET", f"/rest/v1/pipeline_findings?id=eq.{fid}", v)
        check("a viewer reads the findings", len(rows) == 1, rows)
        status, _ = call("DELETE", f"/rest/v1/pipeline_findings?id=eq.{fid}", v)
        _, rows = call("GET", f"/rest/v1/pipeline_findings?id=eq.{fid}", a)
        check("a viewer cannot retract a finding", len(rows) == 1, (status, rows))
        status, _ = call("DELETE", f"/rest/v1/pipeline_findings?id=eq.{fid}", a)
        _, rows = call("GET", f"/rest/v1/pipeline_findings?id=eq.{fid}", a)
        check("an operator retracts a finding", rows == [], (status, rows))
    finally:
        call("DELETE", f"/rest/v1/flights?id=eq.{flight}", SERVICE)
        call("DELETE", f"/rest/v1/sessions?id=eq.{session}", SERVICE)
        for uid in (a_id, b_id, v_id):
            call("DELETE", f"/auth/v1/admin/users/{uid}", SERVICE)
    print(f"\n  {sum(results)}/{len(results)} held")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
