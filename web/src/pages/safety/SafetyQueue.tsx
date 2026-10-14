import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listSafetyChecks } from "../../api/safety";
import type { SafetyStatus } from "../../types";

const VIEWS: { label: string; statuses: SafetyStatus[] }[] = [
  { label: "Awaiting my check", statuses: ["PENDING"] },
  { label: "Decided", statuses: ["APPROVED", "REJECTED", "CHANGES_REQUESTED"] },
  { label: "All", statuses: [] },
];

/** Week 7 change 6 - events waiting for an Operational Safety Check. */
export function SafetyQueue() {
  const [view, setView] = useState(0);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["safety-checks", view],
    queryFn: () => listSafetyChecks(VIEWS[view].statuses),
    placeholderData: (previous) => previous,
  });
  const rows = data ?? [];

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold text-navy-700">Operational safety checks</h1>
      <p className="mb-4 text-sm text-slate-500">
        Events whose venue and technical arrangements are in place. An event cannot be confirmed
        until you approve it.
      </p>
      <div role="tablist" className="mb-4 flex gap-2 text-sm">
        {VIEWS.map((v, i) => (
          <button
            key={v.label}
            type="button"
            role="tab"
            aria-selected={view === i}
            onClick={() => setView(i)}
            className={`rounded-md px-3 py-1 ${
              view === i ? "bg-navy-700 text-white" : "border border-slate-300 bg-white"
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>
      {isLoading && <p className="text-slate-500">Loading safety checks…</p>}
      {isError && <p role="alert">We could not load the safety checks.</p>}
      {data && rows.length === 0 && (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          Nothing here.
        </p>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">Client</th>
                <th className="px-4 py-3">Event date</th>
                <th className="px-4 py-3">Requested</th>
                <th className="px-4 py-3">Check</th>
                <th className="px-4 py-3">Concerns</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {rows.map((row) => {
                const facts = row.current_facts ?? row.facts;
                return (
                  <tr key={row.id}>
                    <td className="px-4 py-3 font-medium text-navy-700">
                      <Link to={`/safety/checks/${row.id}`} className="hover:underline">
                        {row.event_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3">{row.organisation_name}</td>
                    <td className="px-4 py-3">
                      {facts.start ? new Date(facts.start).toLocaleDateString("en-SG") : "—"}
                    </td>
                    <td className="px-4 py-3">
                      {new Date(row.requested_at).toLocaleString("en-SG")}
                      <span className="block text-xs text-slate-500">
                        {row.requested_by_name}
                      </span>
                    </td>
                    <td className="px-4 py-3">{row.status_display}</td>
                    <td className="px-4 py-3">
                      {(facts.concerns ?? []).length > 0 ? (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-amber-900">
                          {facts.concerns.length} to look at
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
