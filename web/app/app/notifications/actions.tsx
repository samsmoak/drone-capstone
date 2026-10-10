"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import type { NotificationRow } from "@/lib/queries";
import { markAllNotificationsRead, markNotificationRead } from "@/lib/mutations";
import { notificationHref, useNotifications } from "@/components/operator/notifications";

/** "Open": go to the finding, and mark the notification read on the way. */
export function OpenNotification({ notification }: { notification: NotificationRow }) {
  const shared = useNotifications();
  return (
    <Link href={notificationHref(notification)}
          onClick={() => {
            if (notification.read_at) return;
            if (shared) shared.markRead(notification.id);
            else void markNotificationRead(notification.id);
          }}
          className="inline-flex min-h-11 items-center underline underline-offset-4">
      Open the finding
    </Link>
  );
}

export function MarkAllRead({ unread }: { unread: number }) {
  const shared = useNotifications();
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex flex-wrap items-center gap-3">
      <button type="button" disabled={pending}
              onClick={() => {
                if (shared) {
                  // The action revalidates this page itself when it lands.
                  shared.markAllRead();
                  return;
                }
                startTransition(async () => {
                  const result = await markAllNotificationsRead();
                  if (!result.ok) setError(result.error);
                  router.refresh();
                });
              }}
              className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-4 text-sm font-medium hover:bg-[var(--surface-2)] disabled:opacity-50">
        Mark all {unread} read
      </button>
      {error && <p role="alert" className="text-sm text-[var(--status-critical)]">{error}</p>}
    </div>
  );
}
