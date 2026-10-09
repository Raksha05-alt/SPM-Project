import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { STATUS_LABELS, fetchQueueByStatus } from "../api/planning";
import { ApprovalNote } from "../components/ApprovalNote";
import { StatusBadge } from "../components/StatusBadge";
import type { EventStatus } from "../types";

/** SCRUM-57 - the statuses an item in the queue can have. */
const FILTERS: EventStatus[] = [
  "SUBMITTED",
  "UNDER_REVIEW",
  "APPROVED",
  "PLANNING",
  "CONFIRMED",
  "COMPLETED",
  "CANCELLED",
];

function StatusFilter({
  options,
  selected,
  onChange,
}: {
  options: EventStatus[];
  selected: EventStatus[];
  onChange: (next: EventStatus[]) => void;
}) {
  return (
    <fieldset className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
      <legend className="mb-1 w-full text-xs font-medium uppercase tracking-wide text-slate-500">
        Filter by status
      </legend>
      {options.map((status) => (
        <label key={status} className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={selected.includes(status)}
            onChange={() =>
              onChange(
                selected.includes(status)
                  ? selected.filter((s) => s !== status)
                  : [...selected, status],
              )
            }
          />
          {STATUS_LABELS[status]}
        </label>
      ))}
      {selected.length > 0 && (
        <button type="button" onClick={() => onChange([])} className="text-navy-700 underline">
          Clear filter
        </button>
      )}
    </fieldset>
  );
}

export function CoordinatorQueue() {
  const [statuses, setStatuses] = useState<EventStatus[]>([]);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["queue", statuses],
    queryFn: () => fetchQueueByStatus(statuses),
    placeholderData: (previous) => previous,
  });

  if (isLoading) return <p className="text-slate-500">Loading the queue…</p>;
  if (isError) return <p role="alert">We could not load the queue.</p>;

  const rows = data ?? [];

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h1 className="mb-1 text-2xl font-semibold text-navy-700">Incoming event requests</h1>
        <Link to="/coordinator/mine" className="text-sm text-navy-700 underline">
          My assigned events
        </Link>
      </div>
      <p className="mb-6 text-sm text-slate-500">Oldest submission first.</p>

      <StatusFilter options={FILTERS} selected={statuses} onChange={setStatuses} />

      {/* US-04.1 AC5 - an empty queue is an empty state, not an error. */}
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          {statuses.length
            ? "No events match the selected statuses."
            : "Nothing is waiting for ConnectSphere right now."}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">Client</th>
                <th className="px-4 py-3">Preferred date</th>
                <th className="px-4 py-3">Attending</th>
                <th className="px-4 py-3">Submitted</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Coordinator</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="px-4 py-3 font-medium text-navy-700">
                    <Link to={`/coordinator/events/${row.id}`} className="hover:underline">
                      {row.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{row.organisation_name}</td>
                  <td className="px-4 py-3">
                    {row.preferred_start
                      ? new Date(row.preferred_start).toLocaleDateString("en-SG")
                      : "—"}
                  </td>
                  <td className="px-4 py-3">{row.expected_attendance ?? "—"}</td>
                  <td className="px-4 py-3">
                    {row.submitted_at
                      ? new Date(row.submitted_at).toLocaleString("en-SG")
                      : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge
                      status={row.status}
                      label={row.status_label}
                      title={row.status_description}
                    />
                    <ApprovalNote approvedBy={row.approved_by_name} approvedAt={row.approved_at} />
                  </td>
                  <td className="px-4 py-3">
                    {row.coordinator_name ?? (row.assignment_requires_attention
                      ? "Unassigned — staff action needed"
                      : "Not assigned")}
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
