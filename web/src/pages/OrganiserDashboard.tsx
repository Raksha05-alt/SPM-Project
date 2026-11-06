import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listOrganiserEvents } from "../api/events";
import { StatusBadge } from "../components/StatusBadge";
import type { EventRequest } from "../types";

function formatDateTime(value: string) {
  return new Date(value).toLocaleString("en-SG");
}

/**
 * SCRUM-45 - every request of the organiser's organisation, with its coordinator.
 * SCRUM-48 - saved drafts together, each with when it was last saved.
 * The API scopes both lists to the organisation (``?group=drafts|submitted``).
 */
export function OrganiserDashboard() {
  const drafts = useQuery({
    queryKey: ["events", "drafts"],
    queryFn: () => listOrganiserEvents("drafts"),
  });
  const submitted = useQuery({
    queryKey: ["events", "submitted"],
    queryFn: () => listOrganiserEvents("submitted"),
  });

  if (drafts.isLoading || submitted.isLoading) {
    return <p className="text-slate-500">Loading your event requests…</p>;
  }
  if (drafts.isError || submitted.isError) {
    return <p role="alert">We could not load your event requests.</p>;
  }

  const draftRows = drafts.data ?? [];
  const submittedRows = submitted.data ?? [];

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

      {draftRows.length === 0 && submittedRows.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          You have no event requests yet. Start one and save it as a draft whenever you like.
        </p>
      ) : (
        <>
          <Section
            title="Drafts"
            rows={draftRows}
            empty="You have no saved drafts."
            detail={(row) => `Last saved ${formatDateTime(row.updated_at)}`}
          />
          <Section
            title="Sent to ConnectSphere"
            rows={submittedRows}
            empty="Nothing has been sent to ConnectSphere yet."
            detail={(row) =>
              row.coordinator_name
                ? `Coordinator: ${row.coordinator_name}`
                : "Coordinator: not yet assigned"
            }
          />
        </>
      )}
    </div>
  );
}

function Section({
  title,
  rows,
  empty,
  detail,
}: {
  title: string;
  rows: EventRequest[];
  empty: string;
  detail: (row: EventRequest) => string;
}) {
  return (
    <section aria-label={title} className="mb-8">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500">
          {empty}
        </p>
      ) : (
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
                  {row.preferred_start ? formatDateTime(row.preferred_start) : "No date yet"}
                  {row.expected_attendance ? ` · ${row.expected_attendance} attending` : ""}
                </p>
                <p className="text-xs text-slate-500">{detail(row)}</p>
              </div>
              <StatusBadge
                status={row.status}
                label={row.status_label}
                title={row.status_description}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
