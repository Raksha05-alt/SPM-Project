import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { approveEvent, getEvent } from "../api/events";
import { useAuth } from "../auth/AuthContext";
import { ApprovalNote } from "../components/ApprovalNote";
import { StatusBadge } from "../components/StatusBadge";
import type { EventStatus } from "../types";

const LAYOUT_LABELS: Record<string, string> = {
  CLASSROOM: "Classroom",
  THEATRE: "Theatre",
  BOARDROOM: "Boardroom",
  BANQUET: "Banquet",
  EXHIBITION: "Exhibition",
};

/** Statuses a coordinator can approve from; the API enforces the same rule. */
const REVIEWABLE: EventStatus[] = ["SUBMITTED", "UNDER_REVIEW"];

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("en-SG") : "—";
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 whitespace-pre-line text-sm text-slate-800">{children}</dd>
    </div>
  );
}

export function CoordinatorEventDetail() {
  const { id } = useParams();
  const eventId = Number(id);
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const { data: event, isLoading, isError } = useQuery({
    queryKey: ["event", eventId],
    queryFn: () => getEvent(eventId),
  });

  const approve = useMutation({
    mutationFn: approveEvent,
    onSuccess: (updated) => {
      queryClient.setQueryData(["event", eventId], updated);
      void queryClient.invalidateQueries({ queryKey: ["my-events"] });
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  if (isLoading) return <p className="text-slate-500">Loading the event…</p>;
  if (isError || !event) return <p role="alert">We could not load this event.</p>;

  const canApprove = event.coordinator === user?.id && REVIEWABLE.includes(event.status);

  return (
    <div>
      <div className="mb-4 flex gap-4 text-sm">
        <Link to="/coordinator/mine" className="text-navy-700 underline">
          ← My assigned events
        </Link>
        <Link to="/coordinator" className="text-navy-700 underline">
          Incoming requests
        </Link>
      </div>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-navy-700">{event.name}</h1>
          <p className="text-sm text-slate-500">
            {event.organisation_name} · raised by {event.created_by_name}
          </p>
        </div>
        <div className="text-right">
          <StatusBadge
            status={event.status}
            label={event.status_label}
            title={event.status_description}
          />
          <p className="mt-1 text-xs text-slate-500">{event.status_description}</p>
          <ApprovalNote
            approvedBy={event.approved_by_name ?? null}
            approvedAt={event.approved_at ?? null}
          />
        </div>
      </div>

      {approve.isError && (
        <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {approve.error.message}
        </p>
      )}

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <dl className="grid gap-6 sm:grid-cols-2">
          <Detail label="Purpose">{event.purpose || "—"}</Detail>
          <Detail label="Expected attendance">{event.expected_attendance ?? "—"}</Detail>
          <Detail label="Preferred start">{formatDateTime(event.preferred_start)}</Detail>
          <Detail label="Preferred end">{formatDateTime(event.preferred_end)}</Detail>
          <Detail label="Required room layout">
            {LAYOUT_LABELS[event.required_layout] ?? "No preference"}
          </Detail>
          <Detail label="Registration required">
            {event.registration_required ? "Yes" : "No"}
          </Detail>
          <div className="sm:col-span-2">
            <Detail label="Description">{event.description || "—"}</Detail>
          </div>
          <div className="sm:col-span-2">
            <Detail label="Accessibility needs">{event.accessibility_needs || "—"}</Detail>
          </div>
          <div className="sm:col-span-2">
            <Detail label="Equipment and technical requirements">
              {event.equipment_notes || "—"}
            </Detail>
          </div>
          <Detail label="Coordinator">
            {event.coordinator_name ?? "Not assigned"}
            {event.coordinator_email && (
              <>
                {" · "}
                <a className="text-navy-700 underline" href={`mailto:${event.coordinator_email}`}>
                  {event.coordinator_email}
                </a>
              </>
            )}
          </Detail>
          <Detail label="Submitted">{formatDateTime(event.submitted_at)}</Detail>
        </dl>
      </section>

      {canApprove && (
        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={() => approve.mutate(event.id)}
            disabled={approve.isPending}
            className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
          >
            Approve request
          </button>
        </div>
      )}
    </div>
  );
}
