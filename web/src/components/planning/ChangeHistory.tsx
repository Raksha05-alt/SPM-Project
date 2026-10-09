import { useQuery } from "@tanstack/react-query";
import { fetchHistory, formatDateTime } from "../../api/planning";

const FIELD_LABELS: Record<string, string> = {
  name: "Event name",
  purpose: "Purpose",
  description: "Description",
  preferred_start: "Start",
  preferred_end: "End",
  expected_attendance: "Expected attendance",
  required_layout: "Room layout",
  accessibility_needs: "Accessibility needs",
  equipment_notes: "Equipment requirements",
  registration_required: "Registration required",
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}T/;

function display(value: string) {
  if (!value) return "—";
  return ISO_DATE.test(value) ? formatDateTime(value) : value;
}

/** SCRUM-60 - what changed, from what, to what, by whom and when. */
export function ChangeHistory({ eventId }: { eventId: number }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["event-history", eventId],
    queryFn: () => fetchHistory(eventId),
  });

  return (
    <section
      aria-label="Change history"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="mb-3 text-sm font-semibold text-navy-700">Change history</h2>
      {isLoading && <p className="text-sm text-slate-500">Loading the change history…</p>}
      {isError && (
        <p role="alert" className="text-sm text-rose-800">
          {error.message}
        </p>
      )}
      {data && data.length === 0 && (
        <p className="text-sm text-slate-500">No changes have been recorded yet.</p>
      )}
      {data && data.length > 0 && (
        <ul className="divide-y divide-slate-200 text-sm">
          {data.map((entry) => (
            <li key={entry.id} className="py-2">
              <p>
                <span className="font-medium">{FIELD_LABELS[entry.field] ?? entry.field}</span>
                {entry.significant && (
                  <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-amber-900">
                    Significant
                  </span>
                )}
              </p>
              <p className="text-slate-700">
                {display(entry.previous_value)} → {display(entry.new_value)}
              </p>
              <p className="text-xs text-slate-500">
                {entry.changed_by_name ?? "System"} · {formatDateTime(entry.changed_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
