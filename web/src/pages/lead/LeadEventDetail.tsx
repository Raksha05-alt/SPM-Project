import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { getEvent } from "../../api/events";
import { StatusBadge } from "../../components/StatusBadge";
import type { EventRequest } from "../../types";
import { AssignCoordinator, LeadNav } from "./AssignCoordinator";

function when(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("en-SG") : "—";
}

interface AssignmentEntry {
  id: number;
  previous_coordinator_name: string | null;
  coordinator_name: string | null;
  changed_by_name: string;
  changed_at: string;
}

/** Week 7 change 5 - the basic event information a Lead reviews before assigning. */
export function LeadEventDetail() {
  const { id } = useParams();
  const eventId = Number(id);
  const queryClient = useQueryClient();
  const { data: event, isLoading, isError } = useQuery({
    queryKey: ["lead", "event", eventId],
    queryFn: () => getEvent(eventId),
  });

  if (isLoading) return <p className="text-slate-500">Loading the event…</p>;
  if (isError || !event) return <p role="alert">We could not load this event.</p>;

  const history = ((event as unknown as { assignment_history?: AssignmentEntry[] })
    .assignment_history ?? []) as AssignmentEntry[];
  const closed = ["COMPLETED", "CANCELLED", "REJECTED"].includes(event.status);

  return (
    <div>
      <LeadNav />
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-navy-700">{event.name}</h1>
          <p className="text-sm text-slate-500">
            {event.organisation_name} · raised by {event.created_by_name}
          </p>
        </div>
        <StatusBadge status={event.status} label={event.status_label} />
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-6 text-sm">
        <dl className="grid gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase text-slate-500">Purpose</dt>
            <dd>{event.purpose || "—"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Expected attendance</dt>
            <dd>{event.expected_attendance ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Preferred period</dt>
            <dd>
              {when(event.preferred_start)} – {when(event.preferred_end)}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Layout</dt>
            <dd>{event.required_layout_label || "No preference"}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-xs uppercase text-slate-500">Accessibility and equipment</dt>
            <dd>
              {[event.accessibility_needs, event.equipment_notes].filter(Boolean).join(" · ") ||
                "—"}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Coordinator</dt>
            <dd>
              {event.coordinator_name ?? "Not assigned"}
              {event.assigned_by_name && (
                <span className="block text-xs text-slate-500">
                  Assigned by {event.assigned_by_name} · {when(event.assigned_at)}
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-slate-500">Submitted</dt>
            <dd>{when(event.submitted_at)}</dd>
          </div>
        </dl>
      </section>

      {!closed && (
        <section
          aria-label="Assignment"
          className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
        >
          <h2 className="mb-3 text-sm font-semibold text-navy-700">
            {event.coordinator ? "Reassign this event" : "Assign a coordinator"}
          </h2>
          <AssignCoordinator
            eventId={event.id}
            eventName={event.name}
            current={event.coordinator}
            onAssigned={(updated) =>
              queryClient.setQueryData<EventRequest>(["lead", "event", eventId], updated)
            }
          />
        </section>
      )}

      {history.length > 0 && (
        <section className="mt-6 rounded-lg border border-slate-200 bg-white p-6 text-sm">
          <h2 className="mb-3 text-sm font-semibold text-navy-700">Assignment history</h2>
          <ul className="space-y-1">
            {history.map((h) => (
              <li key={h.id}>
                {h.previous_coordinator_name ? `${h.previous_coordinator_name} → ` : ""}
                {h.coordinator_name} · by {h.changed_by_name} · {when(h.changed_at)}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
