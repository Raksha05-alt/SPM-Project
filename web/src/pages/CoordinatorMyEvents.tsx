import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { approveEvent } from "../api/events";
import { STATUS_LABELS, fetchMyEventsByStatus } from "../api/planning";
import { ApprovalNote } from "../components/ApprovalNote";
import { StatusBadge } from "../components/StatusBadge";
import type { EventStatus } from "../types";

/** Statuses a coordinator can approve from; the API enforces the same rule. */
const REVIEWABLE: EventStatus[] = ["SUBMITTED", "UNDER_REVIEW"];

/** SCRUM-57 - the statuses an assigned event can have. */
const FILTERS: EventStatus[] = [
  "SUBMITTED",
  "UNDER_REVIEW",
  "APPROVED",
  "PLANNING",
  "CONFIRMED",
  "COMPLETED",
  "CANCELLED",
  "REJECTED",
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

export function CoordinatorMyEvents() {
  const [statuses, setStatuses] = useState<EventStatus[]>([]);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["my-events", statuses],
    queryFn: () => fetchMyEventsByStatus(statuses),
    placeholderData: (previous) => previous,
  });
  const queryClient = useQueryClient();
  const approve = useMutation({
    mutationFn: approveEvent,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["my-events"] });
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
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

      {approve.isError && (
        <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {approve.error.message}
        </p>
      )}

      <StatusFilter options={FILTERS} selected={statuses} onChange={setStatuses} />

      {/* SCRUM-54 AC3 - no assigned events is an empty state, not an error. */}
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          {statuses.length
            ? "No events match the selected statuses."
            : "You have no assigned events right now."}
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
                <th className="px-4 py-3">
                  <span className="sr-only">Decision</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {rows.map((row) => (
                <tr key={row.id} className={row.requires_action ? "bg-amber-50/40" : undefined}>
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
                  <td className="px-4 py-3">
                    <StatusBadge
                      status={row.status}
                      label={row.status_label}
                      title={row.status_description}
                    />
                    <ApprovalNote approvedBy={row.approved_by_name} approvedAt={row.approved_at} />
                  </td>
                  <td className="px-4 py-3">
                    {row.requires_action && (
                      <span className="mr-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-amber-900">
                        Action needed
                      </span>
                    )}
                    {row.next_action}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {REVIEWABLE.includes(row.status) && (
                      <button
                        type="button"
                        onClick={() => approve.mutate(row.id)}
                        disabled={approve.isPending}
                        className="rounded-md bg-navy-700 px-3 py-1 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
                        aria-label={`Approve ${row.name}`}
                      >
                        Approve
                      </button>
                    )}
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
