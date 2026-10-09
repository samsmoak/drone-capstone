"""Prove migration 20261009000015 (owner identity) against a running database.

Two operators, A and B. Checks that:
  1  A's session and flight carry A's name and email, stamped by the database;
  2  what A sends as operator_email is ignored — on insert and on update;
  3  a flight with no created_by takes its session's operator;
  4  B, another operator, reads A's session and flight AND sees who ran them;
  5  B still cannot read A's profile row.

Defaults to the local stack (`cd backend && supabase start`). Creates its own
users and rows and deletes them after. Exit code 0 = every check held.

    python backend/supabase/checks/owner_check.py
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


def call(method, path, token, body=None, headers=None):
    request = urllib.request.Request(f"{API}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
    request.add_header("apikey", ANON if token != SERVICE else SERVICE)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        request.add_header(k, v)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def user(email, name):
    status, body = call("POST", "/auth/v1/admin/users", SERVICE,
                        {"email": email, "password": "check-owner-1", "email_confirm": True,
                         "user_metadata": {"full_name": name}})
    assert status in (200, 201), body
    uid = body["id"]
    call("PATCH", f"/rest/v1/profiles?id=eq.{uid}", SERVICE,
         {"full_name": name, "role": "operator"})
    _, token = call("POST", "/auth/v1/token?grant_type=password", ANON,
                    {"email": email, "password": "check-owner-1"})
    return uid, token["access_token"]


results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if not ok and detail else ""))


def main():
    tag = uuid.uuid4().hex[:8]
    a_id, a = user(f"owner-a-{tag}@check.local", "Operator A")
    b_id, b = user(f"owner-b-{tag}@check.local", "Operator B")
    session, flight, orphan = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    prefer = {"Prefer": "return=representation"}
    try:
        status, rows = call("POST", "/rest/v1/sessions", a,
                            {"id": session, "operator_id": a_id,
                             "operator_email": "spoof@evil.example"}, prefer)
        check("A records a session", status == 201, rows)
        row = rows[0] if status == 201 else {}
        check("the session carries A's email, not what A sent",
              row.get("operator_email") == f"owner-a-{tag}@check.local", row)
        check("the session carries A's name", row.get("operator_name") == "Operator A", row)

        status, rows = call("POST", "/rest/v1/flights", a,
                            {"id": flight, "session_id": session, "created_by": a_id,
                             "operator_name": "Someone Else"}, prefer)
        check("A records a flight", status == 201, rows)
        check("the flight carries A, not what A sent",
              status == 201 and rows[0]["operator_name"] == "Operator A", rows)

        status, rows = call("POST", "/rest/v1/flights", a,
                            {"id": orphan, "session_id": session}, prefer)
        check("a flight with no created_by takes its session's operator",
              status == 201 and rows[0]["operator_email"] == f"owner-a-{tag}@check.local", rows)

        status, rows = call("PATCH", f"/rest/v1/sessions?id=eq.{session}", a,
                            {"operator_email": "spoof@evil.example"}, prefer)
        check("an update cannot change who ran it",
              status == 200 and rows and rows[0]["operator_email"] == f"owner-a-{tag}@check.local",
              rows)

        status, rows = call("GET", f"/rest/v1/sessions?id=eq.{session}&select=operator_email,operator_name", b)
        check("B sees who ran A's session",
              status == 200 and rows == [{"operator_email": f"owner-a-{tag}@check.local",
                                          "operator_name": "Operator A"}], rows)
        status, rows = call("GET", f"/rest/v1/flights?id=eq.{flight}&select=operator_name", b)
        check("B sees who flew A's flight", rows == [{"operator_name": "Operator A"}], rows)

        status, rows = call("GET", f"/rest/v1/profiles?id=eq.{a_id}", b)
        check("B still cannot read A's profile", status == 200 and rows == [], rows)
    finally:
        for table, rid in (("flights", orphan), ("flights", flight), ("sessions", session)):
            call("DELETE", f"/rest/v1/{table}?id=eq.{rid}", SERVICE)
        for uid in (a_id, b_id):
            call("DELETE", f"/auth/v1/admin/users/{uid}", SERVICE)
    print(f"\n  {sum(results)}/{len(results)} held")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
