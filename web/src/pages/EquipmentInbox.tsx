import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listEquipmentInbox } from "../api/equipment";
import { ArrangementReviews } from "../components/changes/ArrangementReviews";

function when(start: string | null, end: string | null) {
  if (!start) return "Date not set";
  const from = new Date(start).toLocaleString("en-SG");
  return end ? `${from} – ${new Date(end).toLocaleString("en-SG")}` : from;
}

/**
 * SCRUM-74 AC3 - Technical Support see every event with requested equipment,
 * with each item's quantity and technical requirements. Read-only: reserving
 * (SCRUM-16) and amending (SCRUM-75) arrive at later gates.
 */
export function EquipmentInbox() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["equipment-inbox"],
    queryFn: listEquipmentInbox,
  });
  const events = data ?? [];

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-navy-700">Equipment requests</h1>
      <p className="mb-4"><Link className="text-navy-700 underline" to="/equipment/plans">Review equipment plans</Link></p>
      {/* SCRUM-80 - approved changes waiting for Technical Support review. */}
      <ArrangementReviews />

      {isLoading && <p className="text-slate-500">Loading equipment requests…</p>}
      {isError && <p role="alert">We could not load the equipment requests.</p>}
      {!isLoading && !isError && events.length === 0 && (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          No equipment has been requested for any event.
        </p>
      )}

      {events.map((event) => (
        <section
          key={event.id}
          aria-label={event.name}
          className="mb-6 rounded-lg border border-slate-200 bg-white p-6"
        >
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-semibold text-navy-700">{event.name}</h2>
            <span className="flex items-baseline gap-3 text-sm">
              <span className="font-medium text-slate-600">{event.status_label}</span>
              <Link to={`/equipment/plans/${event.id}`} className="text-navy-700 underline">Manage reservations</Link>
              <Link
                to={`/equipment/availability/${event.id}`}
                className="text-navy-700 underline"
              >
                Check availability
              </Link>
            </span>
          </div>
          <p className="mb-4 text-sm text-slate-600">
            {when(event.preferred_start, event.preferred_end)}
            {event.expected_attendance != null && ` · ${event.expected_attendance} people`}
            {` · Coordinator: ${event.coordinator_name ?? "Not assigned"}`}
          </p>
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-2">Equipment</th>
                <th className="py-2">Quantity</th>
                <th className="py-2">Technical requirements</th>
                <th className="py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {event.equipment_requests.map((r) => (
                <tr key={r.id}>
                  <td className="py-2 font-medium text-navy-700">{r.equipment_type_name}</td>
                  <td className="py-2">{r.quantity}</td>
                  <td className="py-2 whitespace-pre-line">{r.technical_requirements || "—"}</td>
                  <td className="py-2">
                    <span className="font-medium">{r.status_label}</span>
                    <span className="block text-xs text-slate-500">
                      by {r.requested_by_name ?? "Deleted user"} on{" "}
                      {new Date(r.requested_at).toLocaleString("en-SG")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}
