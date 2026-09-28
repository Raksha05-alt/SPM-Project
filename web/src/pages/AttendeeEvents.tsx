import { useQuery } from "@tanstack/react-query";
import { listAttendeeEvents } from "../api/events";
import { StatusBadge } from "../components/StatusBadge";

export function AttendeeEvents() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["attendee-events"],
    queryFn: listAttendeeEvents,
  });

  if (isLoading) return <p className="text-slate-500">Loading events…</p>;
  if (isError) return <p role="alert">We could not load the events.</p>;

  const events = data ?? [];

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold text-navy-700">Events</h1>
      <p className="mb-6 text-sm text-slate-500">Confirmed and recently concluded events.</p>

      {events.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          There are no confirmed events to show right now.
        </p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {events.map((event) => (
            <li key={event.id} className="px-4 py-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="font-medium text-navy-700">{event.name}</h2>
                  <p className="mt-1 text-sm text-slate-600">{event.status_description}</p>
                  <p className="mt-2 text-xs text-slate-500">
                    {event.preferred_start
                      ? new Date(event.preferred_start).toLocaleString("en-SG")
                      : "Date to be confirmed"}
                    {event.status_changed_at
                      ? ` · Status updated ${new Date(event.status_changed_at).toLocaleString("en-SG")}`
                      : ""}
                  </p>
                </div>
                <StatusBadge
                  status={event.status}
                  label={event.status_label}
                  title={event.status_description}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
