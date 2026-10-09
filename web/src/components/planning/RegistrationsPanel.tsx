import { useQuery } from "@tanstack/react-query";
import { fetchRegistrations, formatDateTime } from "../../api/planning";

/** SCRUM-14 AC5 / SCRUM-19 AC4 - who has registered, who is waiting and who withdrew. */
export function RegistrationsPanel({ eventId }: { eventId: number }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["event-registrations", eventId],
    queryFn: () => fetchRegistrations(eventId),
  });

  return (
    <section
      aria-label="Registrations"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="mb-3 text-sm font-semibold text-navy-700">Registrations</h2>
      {isLoading && <p className="text-sm text-slate-500">Loading registrations…</p>}
      {isError && (
        <p role="alert" className="text-sm text-rose-800">
          {error.message}
        </p>
      )}
      {data && (
        <>
          <dl className="mb-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Capacity</dt>
              <dd>{data.capacity ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Registered</dt>
              <dd>{data.registered_count}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Waiting list</dt>
              <dd>{data.waitlist_count}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Places left</dt>
              <dd>{data.places_left ?? "—"}</dd>
            </div>
          </dl>
          {data.registrations.length === 0 ? (
            <p className="text-sm text-slate-500">No one has registered yet.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-2">Name</th>
                  <th className="py-2">Email</th>
                  <th className="py-2">Status</th>
                  <th className="py-2">Accessibility needs</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {data.registrations.map((r) => (
                  <tr key={r.id}>
                    <td className="py-2">{r.full_name}</td>
                    <td className="py-2">{r.email}</td>
                    <td className="py-2">
                      {r.status_display}
                      {r.status === "WITHDRAWN" && r.withdrawn_at && (
                        <span className="block text-xs text-slate-500">
                          {formatDateTime(r.withdrawn_at)}
                        </span>
                      )}
                    </td>
                    <td className="py-2">{r.accessibility_needs || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
