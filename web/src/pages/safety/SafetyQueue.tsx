import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listSafetyChecks } from "../../api/safety";
import { SafetyStatusBadge, formatDateTime } from "../../components/safety/SafetyStatusBadge";
import type { SafetyStatus } from "../../types";

type View = "pending" | "all";
const FILTERS: Record<View, SafetyStatus[]> = { pending: ["PENDING"], all: [] };

/** SCRUM-90 - the Safety Officer's queue of operational safety checks. */
export function SafetyQueue() {
  const [view, setView] = useState<View>("pending");
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["safety-checks", view],
    queryFn: () => listSafetyChecks(FILTERS[view]),
    refetchOnWindowFocus: true,
  });

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold text-navy-700">Operational safety checks</h1>
      <p className="mb-6 text-sm text-slate-500">
        Events whose venue and technical arrangements are in place. An event cannot be confirmed
        until its current check is approved.
      </p>

      <div role="tablist" aria-label="Which checks" className="mb-4 flex gap-2 text-sm">
        {(["pending", "all"] as View[]).map((v) => (
          <button
            key={v}
            role="tab"
            type="button"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={`rounded-md px-3 py-1.5 ${
              view === v ? "bg-navy-700 text-white" : "border border-slate-300 bg-white"
            }`}
          >
            {v === "pending" ? "Awaiting decision" : "All checks"}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-slate-500">Loading safety checks…</p>}
      {isError && (
        <p role="alert">
          We could not load the safety checks.{" "}
          <button type="button" className="underline" onClick={() => void refetch()}>
            Try again
          </button>
        </p>
      )}
      {data && data.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
          {view === "pending" ? "No safety checks are waiting for a decision." : "No safety checks yet."}
        </p>
      )}
      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">Event date</th>
                <th className="px-4 py-3">Coordinator</th>
                <th className="px-4 py-3">Requested</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.map((check) => (
                <tr key={check.id} className="border-t border-slate-100">
                  <td className="px-4 py-3">
                    <Link to={`/safety/checks/${check.id}`} className="font-medium text-navy-700 underline">
                      {check.event_name}
                    </Link>
                    <div className="text-xs text-slate-500">{check.organisation_name}</div>
                  </td>
                  <td className="px-4 py-3">{formatDateTime(check.event_start)}</td>
                  <td className="px-4 py-3">{check.coordinator_name ?? "—"}</td>
                  <td className="px-4 py-3">{formatDateTime(check.requested_at)}</td>
                  <td className="px-4 py-3">
                    <SafetyStatusBadge status={check.status} label={check.status_display} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
