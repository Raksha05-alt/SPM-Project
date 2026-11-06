import { useQuery } from "@tanstack/react-query";
import { getChangeHistory } from "../api/changeHistory";

/**
 * SCRUM-60 - the event's internal change history, most recent first.
 * Read-only: entries cannot be edited or deleted. Shown to the assigned
 * coordinator and Leads; the API refuses everyone else.
 */
export function ChangeHistory({ eventId }: { eventId: number }) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["change-history", eventId],
    queryFn: () => getChangeHistory(eventId),
  });

  return (
    <section aria-label="Change history" className="mt-6 rounded-lg border border-slate-200 bg-white p-6">
      <h2 className="mb-1 text-sm font-semibold text-navy-700">Change history</h2>
      <p className="mb-4 text-xs text-slate-500">
        Every change to the event's details, with who made it and when. Most recent first.
      </p>
      {isLoading ? (
        <p className="text-sm text-slate-500">Loading change history…</p>
      ) : isError ? (
        <p role="alert" className="text-sm text-rose-800">
          We could not load the change history.{" "}
          <button type="button" className="underline" onClick={() => void refetch()}>
            Try again
          </button>
        </p>
      ) : !data || data.changes.length === 0 ? (
        <p className="text-sm text-slate-500">No changes have been recorded.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="py-1 pr-3 font-medium">When</th>
              <th className="py-1 pr-3 font-medium">Field</th>
              <th className="py-1 pr-3 font-medium">Before</th>
              <th className="py-1 pr-3 font-medium">After</th>
              <th className="py-1 font-medium">By</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.changes.map((change) => (
              <tr key={change.id} className="align-top">
                <td className="py-2 pr-3 text-slate-600">
                  <time dateTime={change.changed_at}>
                    {new Date(change.changed_at).toLocaleString("en-SG")}
                  </time>
                </td>
                <td className="py-2 pr-3 font-medium text-slate-800">{change.field_label}</td>
                <td className={`py-2 pr-3 ${change.values_recorded ? "" : "italic text-slate-500"}`}>
                  {change.before_display}
                </td>
                <td className={`py-2 pr-3 ${change.values_recorded ? "" : "italic text-slate-500"}`}>
                  {change.after_display}
                </td>
                <td className="py-2 text-slate-600">{change.actor_name ?? "Unknown user"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
