import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import { fetchReadiness, formatDateTime, type MissingArrangement } from "../../api/planning";
import { requestSafetyCheck } from "../../api/safety";
import type { SafetyCheckSummary } from "../../types";
import { inputClass } from "../Field";

const TONE: Record<string, string> = {
  PENDING: "bg-blue-50 text-blue-900",
  APPROVED: "bg-emerald-50 text-emerald-900",
  REJECTED: "bg-rose-50 text-rose-900",
  CHANGES_REQUESTED: "bg-amber-50 text-amber-900",
  SUPERSEDED: "bg-slate-100 text-slate-700",
};

function SafetyStatus({ check }: { check: SafetyCheckSummary }) {
  return (
    <div className={`rounded-md p-3 text-sm ${TONE[check.status] ?? ""}`}>
      <p className="font-medium">Operational safety check: {check.status_display}</p>
      <p className="text-xs">
        Requested {formatDateTime(check.requested_at)}
        {check.requested_by_name ? ` by ${check.requested_by_name}` : ""}
      </p>
      {check.decided_at && (
        <p className="text-xs">
          Decided {formatDateTime(check.decided_at)}
          {check.decided_by_name ? ` by ${check.decided_by_name}` : ""}
        </p>
      )}
      {check.comment && <p className="mt-1">Safety Officer: {check.comment}</p>}
      {check.status === "SUPERSEDED" && check.superseded_reason && (
        <p className="mt-1 text-xs">No longer applies: {check.superseded_reason}</p>
      )}
    </div>
  );
}

/**
 * Week 7 changes 3, 4 and 6 - everything that must be in place before the event can
 * be confirmed, and the step that sends it to the Safety Officer.
 */
export function ReadinessPanel({ eventId }: { eventId: number }) {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["readiness", eventId],
    queryFn: () => fetchReadiness(eventId),
  });
  const [note, setNote] = useState("");

  const send = useMutation({
    mutationFn: () => requestSafetyCheck(eventId, note.trim()),
    onSuccess: () => {
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["readiness", eventId] });
      void queryClient.invalidateQueries({ queryKey: ["event", eventId] });
    },
  });
  const refused =
    send.error instanceof ApiError
      ? ((send.error.body as { missing?: MissingArrangement[] } | null)?.missing ?? [])
      : [];

  return (
    <section
      aria-label="Readiness"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="mb-3 text-sm font-semibold text-navy-700">Readiness for confirmation</h2>
      {isLoading && <p className="text-sm text-slate-500">Checking the arrangements…</p>}
      {isError && (
        <p role="alert" className="text-sm text-rose-800">
          We could not check the arrangements.
        </p>
      )}
      {data && (
        <>
          {data.missing.length === 0 ? (
            <p className="mb-3 text-sm text-emerald-800">
              Every arrangement and the safety check are in place. You can confirm the event.
            </p>
          ) : (
            <ul aria-label="Outstanding" className="mb-3 list-disc pl-5 text-sm text-slate-800">
              {data.missing.map((m, i) => (
                <li key={i}>
                  <span className="font-medium">{m.arrangement}:</span> {m.detail}
                </li>
              ))}
            </ul>
          )}
          {data.safety_check && <SafetyStatus check={data.safety_check} />}
          {data.can_request_safety_check && (
            <div className="mt-4 border-t border-slate-200 pt-4">
              <p className="mb-2 text-sm text-slate-700">
                The venue and technical arrangements are in place. Send the event to the Safety
                Officer for its operational safety check.
              </p>
              <label htmlFor="safety-note" className="mb-1 block text-sm font-medium">
                Note for the Safety Officer (optional)
              </label>
              <textarea
                id="safety-note"
                rows={2}
                className={inputClass}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              {send.error && (
                <div role="alert" className="mt-2 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
                  <p>{send.error.message}</p>
                  {refused.length > 0 && (
                    <ul className="mt-1 list-disc pl-5">
                      {refused.map((m, i) => (
                        <li key={i}>{m.detail}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              <div className="mt-3 flex justify-end">
                <button
                  type="button"
                  onClick={() => send.mutate()}
                  disabled={send.isPending}
                  className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
                >
                  Request safety check
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
