import type { EventRequest } from "../types";

type Rejection = Pick<
  EventRequest,
  "status" | "rejection_reason" | "rejected_at" | "rejected_by_name"
>;

/** SCRUM-52 AC3 - the rejection decision, its reason and its date. */
export function RejectionNotice({ event }: { event: Rejection }) {
  if (event.status !== "REJECTED") return null;
  return (
    <section
      aria-label="Rejection decision"
      className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
    >
      <p className="font-medium">ConnectSphere is not able to support this request.</p>
      {event.rejection_reason && (
        <p className="mt-1 whitespace-pre-line">Reason: {event.rejection_reason}</p>
      )}
      {event.rejected_at && (
        <p className="mt-1 text-xs text-rose-800">
          Decided {new Date(event.rejected_at).toLocaleString("en-SG")}
          {event.rejected_by_name ? ` by ${event.rejected_by_name}` : ""}
        </p>
      )}
    </section>
  );
}
