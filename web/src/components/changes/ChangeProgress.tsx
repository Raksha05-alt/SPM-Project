import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { applyChange, getChangeHistory, keepOriginal } from "../../api/changeRequests";
import type { ChangeHistory, ChangeRequest } from "../../types";
import { Field, inputClass } from "../Field";

function period(values: Record<string, unknown>) {
  const start = values.starts_at as string | null | undefined;
  const end = values.ends_at as string | null | undefined;
  if (!start || !end) return null;
  return `${new Date(start).toLocaleString("en-SG")} – ${new Date(end).toLocaleTimeString("en-SG")}`;
}

function message(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return fallback;
  const body = (error.body ?? {}) as { reason?: string[]; problems?: string[] };
  if (body.reason) return body.reason[0];
  return [error.message, ...(body.problems ?? [])].join(" ");
}

/** SCRUM-80 AC5 - the decision, each arrangement's outcome and who recorded it. */
export function HistoryDetails({ history }: { history: ChangeHistory }) {
  return (
    <div className="space-y-2 text-sm">
      {history.decision.decided_by && (
        <p>
          Approved by {history.decision.decided_by}
          {history.decision.reason ? `: ${history.decision.reason}` : ""}
        </p>
      )}
      {history.applied_by && <p>Sent for staff review by {history.applied_by}.</p>}
      {history.arrangements.length > 0 && (
        <ul aria-label="Arrangement outcomes" className="space-y-1">
          {history.arrangements.map((item) => (
            <li key={item.id}>
              <span className="font-medium">{item.name}</span> ({item.kind_label}):{" "}
              {period(item.before) && period(item.proposed) !== period(item.before) && (
                <>
                  {period(item.before)} → {period(item.proposed)}.{" "}
                </>
              )}
              <span className="font-medium">{item.outcome_label}</span>
              {item.reviewed_by && (
                <>
                  {" "}
                  by {item.reviewed_by}
                  {item.review_reason ? `: ${item.review_reason}` : ""}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {history.completion_note && <p>{history.completion_note}</p>}
    </div>
  );
}

/**
 * SCRUM-80 - after approval: the coordinator applies the change (staff then
 * review each affected arrangement), follows each outcome, and - if staff
 * cannot accommodate it - records that the original arrangement is kept.
 */
export function ChangeProgress({
  change,
  eventId,
  canDecide,
}: {
  change: ChangeRequest;
  eventId: number;
  canDecide: boolean;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const showHistory = change.status !== "APPROVED";
  const history = useQuery({
    queryKey: ["change-history", change.id],
    queryFn: () => getChangeHistory(change.id),
    enabled: showHistory,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["change-requests", eventId] });
    void queryClient.invalidateQueries({ queryKey: ["change-history", change.id] });
    void queryClient.invalidateQueries({ queryKey: ["event", eventId] });
  };
  const apply = useMutation({ mutationFn: () => applyChange(change.id), onSuccess: refresh });
  const keep = useMutation({ mutationFn: () => keepOriginal(change.id, reason), onSuccess: refresh });
  const refused = history.data?.arrangements.some((item) => item.outcome === "NOT_ACCOMMODATED");

  return (
    <div className="mt-3 space-y-2">
      {canDecide && change.status === "APPROVED" && (
        <div>
          {apply.isError && (
            <p role="alert" className="mb-2 text-sm text-rose-800">
              {message(apply.error, "We could not apply the change.")}
            </p>
          )}
          <button
            type="button"
            disabled={apply.isPending}
            onClick={() => apply.mutate()}
            className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Apply change
          </button>
          <p className="mt-1 text-xs text-slate-500">
            Staff review each affected arrangement; nothing changes until they accept.
          </p>
        </div>
      )}
      {apply.isSuccess && (
        <p role="status" className="text-sm text-emerald-800">
          {apply.data.detail}
        </p>
      )}

      {showHistory && (
        <section
          aria-label={`History of change request ${change.id}`}
          className="rounded border border-slate-200 bg-slate-50 p-3"
        >
          <h3 className="mb-1 text-sm font-semibold text-navy-700">History</h3>
          {history.isLoading && <p className="text-sm text-slate-500">Loading the history…</p>}
          {history.isError && <p role="alert">We could not load the history.</p>}
          {history.data && <HistoryDetails history={history.data} />}
        </section>
      )}

      {canDecide && change.status === "IN_REVIEW" && refused && (
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="mb-2">
            Staff cannot accommodate this change. The current arrangement stays in place. Agree the
            next step with the organiser: keep the original, negotiate another option, or cancel and
            ask for a new request.
          </p>
          {keep.isError && (
            <p role="alert" className="mb-2 text-rose-800">
              {message(keep.error, "We could not record the outcome.")}
            </p>
          )}
          <Field label="What was agreed with the organiser" htmlFor={`keep-reason-${change.id}`}>
            <textarea
              id={`keep-reason-${change.id}`}
              className={inputClass}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          <button
            type="button"
            disabled={keep.isPending}
            onClick={() => keep.mutate()}
            className="rounded-md border border-slate-300 bg-white px-4 py-2"
          >
            Keep the original arrangement
          </button>
        </div>
      )}
    </div>
  );
}
