import type { EventRequest } from "../types";

type Assignment = Pick<
  EventRequest,
  "coordinator_name" | "coordinator_email" | "assignment_requires_attention"
>;

export function CoordinatorAssignment({ event }: { event: Assignment }) {
  return (
    <section
      aria-label="Coordinator assignment"
      className="mb-4 rounded-md border border-slate-200 bg-white p-4 text-sm"
    >
      <h2 className="mb-1 font-semibold text-navy-700">Event coordinator</h2>
      {event.coordinator_name ? (
        <>
          <p>{event.coordinator_name}</p>
          {event.coordinator_email && (
            <a className="text-navy-700 underline" href={`mailto:${event.coordinator_email}`}>
              {event.coordinator_email}
            </a>
          )}
        </>
      ) : (
        <p className="text-amber-900">
          {event.assignment_requires_attention
            ? "Your request is submitted. A ConnectSphere Event Coordinator Lead will assign your coordinator."
            : "A coordinator has not been assigned yet."}
        </p>
      )}
    </section>
  );
}
