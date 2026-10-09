import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  getUnreadCount,
  listNotifications,
  markNotificationRead,
  type AppNotification,
} from "../api/notifications";
import { useAuth } from "../auth/AuthContext";
import type { Role } from "../types";

/** SCRUM-82 AC3 - where each role goes to see the event a notification is about. */
function eventLink(role: Role | undefined, eventId: number): string {
  switch (role) {
    case "ORGANISER":
      return `/organiser/requests/${eventId}`;
    case "COORDINATOR":
      return `/coordinator/events/${eventId}`;
    case "ATTENDEE":
      return "/events/mine";
    case "VENUE_STAFF":
      return "/venues/bookings";
    case "TECH_SUPPORT":
      return "/equipment";
    default:
      return "/";
  }
}

export function Notifications({ userId }: { userId: number }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const listKey = ["notifications", userId];
  const countKey = ["notifications", userId, "unread"];

  const { data = [], isLoading, isError, refetch } = useQuery({
    queryKey: listKey,
    queryFn: listNotifications,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
  const { data: count } = useQuery({
    queryKey: countKey,
    queryFn: getUnreadCount,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });

  // SCRUM-82 AC2 - opening an unread notification marks it read and the count drops.
  const markRead = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: (updated) => {
      queryClient.setQueryData<AppNotification[]>(listKey, (current = []) =>
        current.map((n) =>
          n.id === updated.id ? { ...n, read_at: updated.read_at, is_read: true } : n,
        ),
      );
      queryClient.setQueryData(countKey, { unread: updated.unread });
    },
  });

  // SCRUM-82 AC1 - newest first, whatever order the API happens to send.
  const notifications = [...data].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
  const unread = count?.unread ?? data.filter((n) => !n.is_read).length;

  return (
    <details className="relative">
      <summary className="cursor-pointer">Notifications ({unread})</summary>
      <div className="absolute right-0 z-10 mt-2 max-h-80 w-80 overflow-y-auto rounded-md border border-slate-200 bg-white p-4 shadow-lg">
        {isLoading ? (
          <p>Loading notifications…</p>
        ) : isError ? (
          <p role="alert">
            We could not load notifications.{" "}
            <button type="button" className="underline" onClick={() => void refetch()}>
              Try again
            </button>
          </p>
        ) : notifications.length === 0 ? (
          <p>No notifications yet.</p>
        ) : (
          <ul className="space-y-3" aria-label="Notifications">
            {notifications.map((notification) => (
              <li key={notification.id} className="border-b border-slate-100 pb-2">
                <Link
                  to={eventLink(user?.role, notification.event)}
                  onClick={() => {
                    if (!notification.is_read) markRead.mutate(notification.id);
                  }}
                  className={`block hover:underline ${
                    notification.is_read ? "text-slate-600" : "font-medium text-navy-700"
                  }`}
                >
                  {!notification.is_read && <span className="sr-only">Unread: </span>}
                  {notification.event_name && (
                    <span className="block text-xs uppercase tracking-wide text-slate-500">
                      {notification.event_name}
                      {notification.kind_label ? ` · ${notification.kind_label}` : ""}
                    </span>
                  )}
                  {notification.message}
                </Link>
                <time className="text-xs text-slate-500" dateTime={notification.created_at}>
                  {new Date(notification.created_at).toLocaleString("en-SG")}
                </time>
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}
