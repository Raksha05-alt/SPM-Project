import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getUnreadCount, listNotifications, markNotificationRead } from "../api/notifications";
import type { AppNotification } from "../types";

/**
 * SCRUM-79/82 - the signed-in user's notification centre.
 *
 * Opening the list marks nothing read. Selecting one notice marks only that
 * notice read, then opens the screen the API says this user may open now.
 */
export function Notifications({ userId }: { userId: number }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const panel = useRef<HTMLDetailsElement>(null);
  const [noAccess, setNoAccess] = useState<number | null>(null);

  const list = useQuery({
    queryKey: ["notifications", userId],
    queryFn: listNotifications,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
  const count = useQuery({
    queryKey: ["notifications", userId, "unread"],
    queryFn: getUnreadCount,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });

  const open = useMutation({
    mutationFn: (notice: AppNotification) => markNotificationRead(notice.id),
    onSuccess: ({ notification, unread }) => {
      client.setQueryData(["notifications", userId, "unread"], { unread });
      client.setQueryData<AppNotification[]>(["notifications", userId], (old) =>
        old?.map((n) => (n.id === notification.id ? notification : n)),
      );
      if (notification.destination) {
        setNoAccess(null);
        if (panel.current) panel.current.open = false;
        navigate(notification.destination.path);
      } else {
        setNoAccess(notification.id);
      }
    },
  });

  const notices = list.data ?? [];
  const unread = count.data?.unread ?? notices.filter((n) => !n.is_read).length;

  return (
    <details ref={panel} className="relative">
      <summary className="cursor-pointer">
        Notifications
        {unread > 0 ? (
          <span className="ml-1 rounded-full bg-rose-600 px-1.5 py-0.5 text-xs font-semibold text-white">
            {unread} unread
          </span>
        ) : (
          <span className="sr-only"> (none unread)</span>
        )}
      </summary>
      <div className="absolute right-0 z-10 mt-2 max-h-96 w-96 overflow-y-auto rounded-md border border-slate-200 bg-white p-4 shadow-lg">
        {list.isLoading ? (
          <p>Loading notifications…</p>
        ) : list.isError ? (
          <p role="alert">
            We could not load notifications.{" "}
            <button type="button" className="underline" onClick={() => void list.refetch()}>
              Try again
            </button>
          </p>
        ) : notices.length === 0 ? (
          <p>No notifications yet.</p>
        ) : (
          <ul className="space-y-2" aria-label="Notifications">
            {notices.map((notice) => (
              <li key={notice.id}>
                <button
                  type="button"
                  onClick={() => open.mutate(notice)}
                  disabled={open.isPending}
                  aria-label={`${notice.is_read ? "" : "Unread: "}${notice.kind_label} - ${notice.event_name}`}
                  className={`w-full rounded-md border p-2 text-left text-sm hover:bg-slate-50 ${
                    notice.is_read ? "border-slate-100" : "border-sky-200 bg-sky-50"
                  }`}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="font-medium text-slate-800">
                      {!notice.is_read && (
                        <span aria-hidden className="mr-1 text-rose-600">
                          ●
                        </span>
                      )}
                      {notice.kind_label}
                    </span>
                    <time className="shrink-0 text-xs text-slate-500" dateTime={notice.created_at}>
                      {new Date(notice.created_at).toLocaleString("en-SG")}
                    </time>
                  </span>
                  <span className="block text-xs text-slate-500">{notice.event_name}</span>
                  <span className="mt-1 block text-slate-700">{notice.message}</span>
                </button>
                {noAccess === notice.id && (
                  <p role="status" className="mt-1 text-xs text-slate-600">
                    You no longer have access to this event. The notice is kept for your records.
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
        {open.isError && (
          <p role="alert" className="mt-2 text-sm text-rose-800">
            We could not open that notification. Try again.
          </p>
        )}
      </div>
    </details>
  );
}
