import { useQuery } from "@tanstack/react-query";
import { listNotifications } from "../api/notifications";

export function Notifications({ userId }: { userId: number }) {
  const { data = [], isLoading, isError, refetch } = useQuery({
    queryKey: ["notifications", userId],
    queryFn: listNotifications,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });

  return (
    <details className="relative">
      <summary className="cursor-pointer">Notifications ({data.length})</summary>
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
        ) : data.length === 0 ? (
          <p>No notifications yet.</p>
        ) : (
          <ul className="space-y-3" aria-label="Assignment notifications">
            {data.map((notification) => (
              <li key={notification.id} className="border-b border-slate-100 pb-2">
                <p>{notification.message}</p>
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
