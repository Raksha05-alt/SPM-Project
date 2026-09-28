import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchMyEvents } from "../api/events";
import { StatusBadge } from "../components/StatusBadge";

export function CoordinatorMyEvents() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["my-events"],
    queryFn: fetchMyEvents,
  });

  if (isLoading) return <p className="text-slate-500">Loading your events…</p>;
  if (isError) return <p role="alert">We could not load your events.</p>;

  const rows = data ?? [];

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h1 className="mb-1 text-2xl font-semibold text-navy-700">My assigned events</h1>
        <Link to="/coordinator" className="text-sm text-navy-700 underline">
          Incoming requests
        </Link>
      </div>
      <p className="mb-6 text-sm text-slate-500">Events needing your action are shown first.</p>

      {/* SCRUM-54 AC3 - no assigned events is an empty state, not an error. */}
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          You have no assigned events right now.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">Client</th>
                <th className="px-4 py-3">Preferred date</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Next action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {rows.map((row) => (
                <tr key={row.id} className={row.requires_action ? "bg-amber-50/40" : undefined}>
                  <td className="px-4 py-3 font-medium text-navy-700">{row.name}</td>
                  <td className="px-4 py-3">{row.organisation_name}</td>
                  <td className="px-4 py-3">
                    {row.preferred_start
                      ? new Date(row.preferred_start).toLocaleDateString("en-SG")
                      : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge
                      status={row.status}
                      label={row.status_label}
                      title={row.status_description}
                    />
                  </td>
                  <td className="px-4 py-3">
                    {row.requires_action && (
                      <span className="mr-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-amber-900">
                        Action needed
                      </span>
                    )}
                    {row.next_action}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
