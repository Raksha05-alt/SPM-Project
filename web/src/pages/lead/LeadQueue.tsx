import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchUnassigned } from "../../api/lead";
import { StatusBadge } from "../../components/StatusBadge";
import { AssignCoordinator, LeadNav } from "./AssignCoordinator";

function date(value: string | null) {
  return value ? new Date(value).toLocaleDateString("en-SG") : "—";
}

/**
 * US-04.1 / Week 7 change 5 - newly submitted requests wait here, oldest first,
 * until an Event Coordinator Lead assigns them. Every Lead sees the same queue.
 */
export function LeadQueue() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["lead", "queue"],
    queryFn: () => fetchUnassigned(),
  });

  if (isLoading) return <p className="text-slate-500">Loading the queue…</p>;
  if (isError) return <p role="alert">We could not load the unassigned requests.</p>;
  const rows = data ?? [];

  return (
    <div>
      <LeadNav />
      <h1 className="mb-1 text-2xl font-semibold text-navy-700">Unassigned requests</h1>
      <p className="mb-6 text-sm text-slate-500">
        Oldest first. Review the basic information and assign a coordinator.
      </p>
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          Every submitted request has a coordinator.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">Client</th>
                <th className="px-4 py-3">Preferred date</th>
                <th className="px-4 py-3">Attendance</th>
                <th className="px-4 py-3">Submitted</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Coordinator</th>
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
                  <td className="px-4 py-3">{date(row.preferred_start)}</td>
                  <td className="px-4 py-3">{row.expected_attendance ?? "—"}</td>
                  <td className="px-4 py-3">{date(row.submitted_at)}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={row.status} label={row.status_label} />
                  </td>
                  <td className="px-4 py-3">
                    <AssignCoordinator eventId={row.id} eventName={row.name} current={null} />
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
