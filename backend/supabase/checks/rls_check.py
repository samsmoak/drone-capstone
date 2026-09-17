"""Check migration 0006's policies against a running database.

Defaults to the local stack. Point it at hosted — where the policies actually
have to hold — by setting the environment first:

    SUPABASE_API=https://<ref>.supabase.co SUPABASE_ANON=... SUPABASE_SERVICE=... \\
    CHECK_EMAIL=you@example.com CHECK_PASSWORD=... python rls_check.py

It creates and deletes its own rows, so it is safe to run against hosted.
"""
import json, os, urllib.request, uuid

API = os.environ.get("SUPABASE_API", "http://127.0.0.1:54321")
ANON = os.environ.get("SUPABASE_ANON", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0")
SERVICE = os.environ.get("SUPABASE_SERVICE", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU")
EMAIL = os.environ.get("CHECK_EMAIL", "operator@cropwatcher.local")
PASSWORD = os.environ.get("CHECK_PASSWORD", "cropwatcher")

def call(method, path, token, body=None, headers=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("apikey", ANON)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        request.add_header(k, v)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"").decode()[:120]

status, session = call("POST", "/auth/v1/token?grant_type=password", ANON,
                       {"email": EMAIL, "password": PASSWORD})
operator_token = session["access_token"]
operator_id = session["user"]["id"]
results = []

def check(label, expected, actual, detail=""):
    ok = "PASS" if actual == expected else "FAIL"
    results.append(ok)
    print(f"  [{ok}] {label:52} {actual} {detail if actual != expected else ''}")

# drones: operator may register
hw = f"cf-test-{uuid.uuid4().hex[:8]}"
code, body = call("POST", "/rest/v1/drones", operator_token,
                  {"name": "test drone", "hardware_id": hw, "uri": "radio://0/80/2M"})
check("operator registers a drone", 201, code, body)
code, drones = call("GET", f"/rest/v1/drones?hardware_id=eq.{hw}&select=id", operator_token)
drone_id = drones[0]["id"] if drones else None

# sessions
session_id = str(uuid.uuid4())
code, body = call("POST", "/rest/v1/sessions", operator_token,
                  {"id": session_id, "operator_id": operator_id, "drone_id": drone_id,
                   "agent_id": "test", "mode_at_start": "auto"})
check("operator records their own session", 201, code, body)
code, body = call("POST", "/rest/v1/sessions", operator_token,
                  {"id": str(uuid.uuid4()), "operator_id": str(uuid.uuid4())})
check("cannot record a session for someone else", 403, code, body)

# audit: own only, append-only
event_id = str(uuid.uuid4())
code, body = call("POST", "/rest/v1/audit_events", operator_token,
                  {"id": event_id, "actor_id": operator_id, "source": "desktop",
                   "action": "session_start", "result": "ok", "session_id": session_id,
                   "flight_id": str(uuid.uuid4())})   # a flight that does not exist yet
check("audit event with no flight row yet", 201, code, body)
code, body = call("POST", "/rest/v1/audit_events", operator_token,
                  {"id": str(uuid.uuid4()), "actor_id": str(uuid.uuid4()),
                   "source": "desktop", "action": "forged"})
check("cannot write history as another person", 403, code, body)
code, body = call("PATCH", f"/rest/v1/audit_events?id=eq.{event_id}", operator_token,
                  {"action": "edited"})
check("cannot edit an audit event", 403, code, body)  # privilege revoked
code, body = call("DELETE", f"/rest/v1/audit_events?id=eq.{event_id}", operator_token)
check("cannot delete an audit event", 403, code, body)
code, rows = call("GET", "/rest/v1/audit_events?select=id", operator_token)
check("operator reads the audit trail", 200, code)
code, body = call("GET", "/rest/v1/audit_events?select=id", ANON)
check("anonymous cannot read the audit trail", 401, code, body)

# re-sending the same event is harmless
code, body = call("POST", "/rest/v1/audit_events", operator_token,
                  {"id": event_id, "actor_id": operator_id, "source": "desktop", "action": "session_start"},
                  {"Prefer": "resolution=ignore-duplicates"})
check("re-sending an audit event is ignored", 201, code, body)

# telemetry duplicate protection
flight_id = str(uuid.uuid4())
code, body = call("POST", "/rest/v1/flights", operator_token,
                  {"id": flight_id, "session_id": session_id, "drone_id": drone_id,
                   "created_by": operator_id, "mode": "auto", "program": "hover-test",
                   "temp_unit": "F", "status": "completed"})
check("operator records a flight in a session", 201, code, body)
row = {"flight_id": flight_id, "index": 0, "recorded_at": "2026-09-16T20:00:00Z",
       "temp_unit": "F", "motor_m1": 41000, "vz_m_s": 0.02, "lighthouse_received": 2}
code, body = call("POST", "/rest/v1/telemetry", operator_token, row)
check("telemetry row stored", 201, code, body)
code, body = call("POST", "/rest/v1/telemetry", operator_token, row)
check("the same row twice is rejected", 409, code, body)
code, body = call("POST", "/rest/v1/telemetry?on_conflict=flight_id,index", operator_token, row,
                  {"Prefer": "resolution=ignore-duplicates"})
check("re-sending with ignore-duplicates is harmless", 201, code, body)
code, rows = call("GET", f"/rest/v1/telemetry?flight_id=eq.{flight_id}&select=index", operator_token)
check("stored exactly once", 1, len(rows))

# cleanup
for path in (f"/rest/v1/telemetry?flight_id=eq.{flight_id}", f"/rest/v1/flights?id=eq.{flight_id}",
             f"/rest/v1/audit_events?id=eq.{event_id}", f"/rest/v1/sessions?id=eq.{session_id}",
             f"/rest/v1/drones?id=eq.{drone_id}"):
    call("DELETE", path, SERVICE)

print(f"\n  {results.count('PASS')}/{len(results)} checks passed")
