import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchAssignments } from "../../api/lead";
import { StatusBadge } from "../../components/StatusBadge";
import { AssignCoordinator, LeadNav } from "./AssignCoordinator";

/**
 * Week 7 change 5 - every coordinator assignment and active event, with the ones the
 * signed-in Lead assigned (and so supervises) a click away.
 */
export function LeadAssignments() {
  const [onlyMine, setOnlyMine] = useState(false);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["lead", "assignments", onlyMine],
    queryFn: () => fetchAssignments(onlyMine),
    placeholderData: (previous) => previous,
  });
  const rows = data ?? [];

  return (
    <div>
      <LeadNav />
      <h1 className="mb-1 text-2xl font-semibold text-navy-700">All assignments</h1>
      <p className="mb-4 text-sm text-slate-500">Active events and who coordinates them.</p>
      <label className="mb-4 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />
        Only events I assigned (under my supervision)
      </label>
      {isLoading && <p className="text-slate-500">Loading assignments…</p>}
      {isError && <p role="alert">We could not load the assignments.</p>}
      {data && rows.length === 0 && (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          No active assignments.
        </p>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">Client</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Coordinator</th>
                <th className="px-4 py-3">Assigned by</th>
                <th className="px-4 py-3">Reassign</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="px-4 py-3 font-medium text-navy-700">
                    <Link to={`/lead/events/${row.id}`} className="hover:underline">
                      {row.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{row.organisation_name}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={row.status} label={row.status_label} />
                  </td>
                  <td className="px-4 py-3">
                    {row.coordinator_name}
                    <span className="block text-xs text-slate-500">{row.coordinator_email}</span>
                  </td>
                  <td className="px-4 py-3">
                    {row.assigned_by_name ?? "—"}
                    {row.assigned_at && (
                      <span className="block text-xs text-slate-500">
                        {new Date(row.assigned_at).toLocaleString("en-SG")}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <AssignCoordinator
                      eventId={row.id}
                      eventName={row.name}
                      current={row.coordinator}
                    />
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
