"""Prove migration 20261009000017 (notifications) against a running database.

Operators A and B, and a viewer V. Checks that a WARNING finding notifies A
and B once each, a viewer not at all, an INFO one nobody; re-upserting the
same finding notifies no one again; each sees only their own; marking read is
per person; nobody can rewrite a notification's words, make one, or mark
another's read; retracting a finding takes its notifications with it; and the
table is in the Realtime publication.

Runs against the LOCAL stack (`cd backend && supabase start`), with the
helpers of results_check.py beside it. Exit code 0 = every check held.

    python backend/supabase/checks/notifications_check.py
"""
import sys
import uuid

from results_check import (
    ANON,
    PREFER,
    UPSERT,
    call,
    check,
    cleanup,
    finding,
    results,
    sql,
    user,
)


def mine(token, finding_id):
    _, rows = call("GET", f"/rest/v1/notifications?finding_id=eq.{finding_id}", token)
    return rows if isinstance(rows, list) else []


def main():
    tag = uuid.uuid4().hex[:8]
    a_id, a = user(f"note-a-{tag}@check.local", "operator")
    b_id, b = user(f"note-b-{tag}@check.local", "operator")
    v_id, v = user(f"note-v-{tag}@check.local", "viewer")
    session, flight = str(uuid.uuid4()), str(uuid.uuid4())
    warn, info = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        call("POST", "/rest/v1/sessions", a, {"id": session, "operator_id": a_id})
        call("POST", "/rest/v1/flights", a, {"id": flight, "session_id": session,
                                             "created_by": a_id})
        status, _ = call("POST", "/rest/v1/pipeline_findings?on_conflict=id", a,
                         [finding(warn, flight, session, "warning"),
                          finding(info, flight, session, "info")], UPSERT)
        check("an operator uploads findings", status in (200, 201), status)
        check("a warning notifies A", len(mine(a, warn)) == 1, mine(a, warn))
        check("a warning notifies B", len(mine(b, warn)) == 1, mine(b, warn))
        check("a viewer is not notified", mine(v, warn) == [], mine(v, warn))
        check("an info finding notifies nobody", mine(a, info) == [] and mine(b, info) == [])

        call("POST", "/rest/v1/pipeline_findings?on_conflict=id", a,
             [finding(warn, flight, session, "warning")], UPSERT)
        check("uploading the same finding again notifies no one again",
              len(mine(a, warn)) == 1 and len(mine(b, warn)) == 1)

        (note_a,) = mine(a, warn)
        (note_b,) = mine(b, warn)
        _, rows = call("GET", f"/rest/v1/notifications?id=eq.{note_b['id']}", a)
        check("A cannot read B's notification", rows == [], rows)
        status, rows = call("PATCH", f"/rest/v1/notifications?id=eq.{note_a['id']}", a,
                            {"read_at": "2026-10-09T09:00:00Z"}, PREFER)
        check("A marks their own read", status == 200 and rows and rows[0]["read_at"], rows)
        check("B's is still unread", mine(b, warn)[0]["read_at"] is None, mine(b, warn))
        status, rows = call("PATCH", f"/rest/v1/notifications?id=eq.{note_b['id']}", a,
                            {"read_at": "2026-10-09T09:00:00Z"}, PREFER)
        check("A cannot mark B's read", rows == [] and mine(b, warn)[0]["read_at"] is None,
              (status, rows))
        status, _ = call("PATCH", f"/rest/v1/notifications?id=eq.{note_a['id']}", a,
                         {"title": "rewritten"})
        check("nobody can rewrite a notification's words", status in (401, 403), status)
        status, _ = call("POST", "/rest/v1/notifications", a,
                         {"user_id": b_id, "finding_id": warn, "severity": "warning",
                          "title": "x", "body": "x"})
        check("nobody can make a notification", status in (401, 403), status)
        status, rows = call("GET", "/rest/v1/notifications", ANON)
        check("anonymous reads nothing", status in (401, 403) or rows == [], (status, rows))

        status, _ = call("DELETE", f"/rest/v1/pipeline_findings?id=eq.{warn}", a)
        check("an operator retracts a finding", status in (200, 204), status)
        check("its notifications go with it", mine(a, warn) == [] and mine(b, warn) == [])
        published = sql("select count(*) from pg_publication_tables where pubname = "
                        "'supabase_realtime' and tablename = 'notifications'")
        check("notifications reach open pages through Realtime", published == "1", published)
    finally:
        cleanup((a_id, b_id, v_id), (session,))
    print(f"\n  {sum(results)}/{len(results)} held")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
