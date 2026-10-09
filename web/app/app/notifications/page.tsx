import Link from "next/link";
import { getNotifications, isOperator } from "@/lib/queries";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, StatusBadge } from "@/components/ui/states";
import { LocalTime } from "@/components/ui/local-time";
import { NOTIFICATIONS } from "@/lib/routes";
import { MarkAllRead, OpenNotification } from "./actions";

export const metadata = { title: "Notifications" };

/** One page of the history. */
const PAGE = 50;

/**
 * Every notification the signed-in operator has had, newest first, kept until
 * read and after (migration 20261009000017): each a finding of warning or
 * worse in a processed flight, with the agent's words, linking to it. Paged
 * back by time (?before=), never cut off.
 */
export default async function NotificationsPage(props: PageProps<"/app/notifications">) {
  const { before } = await props.searchParams;
  const cursor = typeof before === "string" ? before : undefined;
  const [operator, notes] = await Promise.all([isOperator(), getNotifications(PAGE + 1, cursor)]);
  const rows = notes.rows.slice(0, PAGE);
  const older = notes.rows.length > PAGE ? rows[rows.length - 1]?.created_at : undefined;
  const unread = rows.filter((n) => !n.read_at).length;

  return (
    <div className="space-y-8">
      <PageHeader title="Notifications"
                  description="Findings of warning or worse in a processed flight — kept until you read them." />
      {!operator ? (
        <EmptyState title="Notifications are for operators"
                    hint="A viewer account sees every session and flight, but is not notified." />
      ) : !notes.migrated ? (
        <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">
          Notifications are not on the web yet: the database has no notifications table. Apply migration
          20261009000017_notifications.sql.
        </p>
      ) : rows.length === 0 ? (
        <EmptyState title={cursor ? "Nothing older" : "No notifications yet"}
                    hint="When a processed flight has a finding of warning or worse, it lands here and stays until you read it." />
      ) : (
        <>
          {unread > 0 && !cursor && <MarkAllRead unread={unread} />}
          <ul className="space-y-3">
            {rows.map((n) => (
              <li key={n.id}
                  className={`rounded-lg border bg-[var(--surface)] p-4 ${n.read_at ? "border-[var(--border)]" : "border-[var(--primary)]"}`}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className={`text-base ${n.read_at ? "" : "font-semibold"}`}>
                    {!n.read_at && <span className="mr-2 rounded bg-[var(--primary)] px-1.5 py-0.5 text-xs font-semibold text-[var(--on-primary)]">Unread</span>}
                    {n.title}
                  </p>
                  <StatusBadge status={n.severity === "critical" ? "critical" : "serious"}
                               label={n.severity === "critical" ? "Critical" : "Warning"} />
                </div>
                <p className="mt-2 text-sm">{n.body}</p>
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="text-[var(--muted)]"><LocalTime iso={n.created_at} /></span>
                  <OpenNotification notification={n} />
                </div>
              </li>
            ))}
          </ul>
          {older && (
            <p>
              <Link href={`${NOTIFICATIONS}?before=${encodeURIComponent(older)}`}
                    className="inline-flex min-h-11 items-center underline underline-offset-4">
                Older notifications
              </Link>
            </p>
          )}
        </>
      )}
    </div>
  );
}
