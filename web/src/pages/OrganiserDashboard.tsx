import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listOrganiserEvents } from "../api/organiser";
import { inputClass } from "../components/Field";
import { StatusBadge } from "../components/StatusBadge";
import type { EventStatus } from "../types";

/** SCRUM-45 / SCRUM-57 - the statuses an organiser can narrow the list to. */
const STATUS_OPTIONS: Array<{ value: EventStatus; label: string }> = [
  { value: "DRAFT", label: "Draft" },
  { value: "SUBMITTED", label: "Submitted" },
  { value: "UNDER_REVIEW", label: "Awaiting Clarification" },
  { value: "APPROVED", label: "Approved" },
  { value: "PLANNING", label: "Planning" },
  { value: "CONFIRMED", label: "Confirmed" },
  { value: "COMPLETED", label: "Completed" },
  { value: "CANCELLED", label: "Cancelled" },
  { value: "REJECTED", label: "Rejected" },
];

export function OrganiserDashboard() {
  const [status, setStatus] = useState<EventStatus | "">("");
  const { data, isLoading, isError } = useQuery({
    queryKey: ["events", "list", status],
    queryFn: () => listOrganiserEvents(status ? [status] : []),
    placeholderData: keepPreviousData,
  });

  const filter = (
    <div className="mb-6 max-w-xs">
      <label htmlFor="status-filter" className="mb-1 block text-sm font-medium text-slate-700">
        Filter by status
      </label>
      <select
        id="status-filter"
        className={inputClass}
        value={status}
        onChange={(e) => setStatus(e.target.value as EventStatus | "")}
      >
        <option value="">All statuses</option>
        {STATUS_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );

  if (isLoading) return <p className="text-slate-500">Loading your event requests…</p>;
  if (isError) return <p role="alert">We could not load your event requests.</p>;

  const events = data ?? [];
  const drafts = events.filter((e) => e.status === "DRAFT");
  const submitted = events.filter((e) => e.status !== "DRAFT");

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-navy-700">Your event requests</h1>
        <Link
          to="/organiser/requests/new"
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600"
        >
          New event request
        </Link>
      </div>

      {filter}

      {events.length === 0 && (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          {status
            ? "No event requests have this status."
            : "You have no event requests yet. Start one and save it as a draft whenever you like."}
        </p>
      )}

      {drafts.length > 0 && <Section title="Drafts" rows={drafts} />}
      {submitted.length > 0 && <Section title="Sent to ConnectSphere" rows={submitted} />}
    </div>
  );
}

function Section({
  title,
  rows,
}: {
  title: string;
  rows: Array<{
    id: number;
    name: string;
    status: "DRAFT" | "SUBMITTED" | "UNDER_REVIEW" | "APPROVED" | "PLANNING" | "CONFIRMED" | "COMPLETED" | "CANCELLED" | "REJECTED";
    status_label: string;
    status_description: string;
    preferred_start: string | null;
    expected_attendance: number | null;
  }>;
}) {
  return (
    <section className="mb-8">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {rows.map((row) => (
          <li key={row.id} className="flex items-center justify-between px-4 py-3">
            <div>
              <Link
                to={`/organiser/requests/${row.id}`}
                className="font-medium text-navy-700 hover:underline"
              >
                {row.name || "(untitled draft)"}
              </Link>
              <p className="text-xs text-slate-500">
                {row.preferred_start
                  ? new Date(row.preferred_start).toLocaleString("en-SG")
                  : "No date yet"}
                {row.expected_attendance ? ` · ${row.expected_attendance} attending` : ""}
              </p>
            </div>
            <StatusBadge
              status={row.status}
              label={row.status_label}
              title={row.status_description}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
