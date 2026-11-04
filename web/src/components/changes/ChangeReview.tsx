import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { decideChange, getChangeImpact } from "../../api/changeRequests";
import type { ChangeAssessment, ChangeRequest } from "../../types";
import { Field, inputClass } from "../Field";

function when(start: string, end: string) {
  return `${new Date(start).toLocaleString("en-SG")} – ${new Date(end).toLocaleTimeString("en-SG")}`;
}

/** The field name of a refusal, or the general message. */
function refusalOf(error: unknown): { reason?: string; message?: string } {
  if (!(error instanceof ApiError)) return { message: "We could not record the decision." };
  const body = (error.body ?? {}) as Record<string, unknown>;
  const first = (value: unknown) => (Array.isArray(value) ? String(value[0]) : undefined);
  if (error.status === 400 && body.reason) return { reason: first(body.reason) };
  const other = first(body.decision) ?? first(body.event);
  return { message: other ?? error.message };
}

function Impact({ assessment }: { assessment: ChangeAssessment }) {
  if (assessment.no_impact) {
    // SCRUM-78 AC4 - no impact is stated clearly.
    return <p className="text-sm text-emerald-800">{assessment.summary}</p>;
  }
  return (
    <div className="space-y-3 text-sm">
      <p>{assessment.summary}</p>
      {assessment.warnings.length > 0 && (
        <ul aria-label="Warnings" className="list-inside list-disc rounded bg-amber-50 p-3 text-amber-900">
          {assessment.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      {assessment.venue_bookings.length > 0 && (
        <div>
          <h4 className="font-medium text-navy-700">Venue bookings</h4>
          <ul className="mt-1 space-y-1">
            {assessment.venue_bookings.map((row) => (
              <li key={row.booking}>
                {row.venue} ({row.session}, {row.status_label}): {when(row.starts_at, row.ends_at)}
                {row.proposed_starts_at && row.proposed_ends_at && (
                  <> → {when(row.proposed_starts_at, row.proposed_ends_at)}</>
                )}
                {/* SCRUM-78 AC2 / AC3 */}
                {row.unsuitable && <span className="ml-2 font-medium text-rose-700">Potentially unsuitable</span>}
                {row.conflicts.length > 0 && (
                  <span className="ml-2 font-medium text-rose-700">Conflicts with another booking</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {assessment.equipment.length > 0 && (
        <div>
          <h4 className="font-medium text-navy-700">Equipment</h4>
          <ul className="mt-1 space-y-1">
            {assessment.equipment.map((row) => (
              <li key={row.request}>
                {row.quantity} x {row.equipment_type} ({row.status_label}): {row.reasons.join(" ")}
                {row.shortfall ? (
                  <span className="ml-2 font-medium text-rose-700">{row.shortfall} short</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {assessment.registrations.affected && (
        <div>
          <h4 className="font-medium text-navy-700">Registrations</h4>
          <p>
            {assessment.registrations.registered} registered, {assessment.registrations.waitlisted}{" "}
            on the waiting list.
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * SCRUM-78 - the assigned coordinator opens a Pending change request, sees what
 * it would affect (read-only) and approves or rejects it with a reason. The
 * decision moves no arrangement; an approved change is applied under SCRUM-80.
 */
export function ChangeReview({ change, eventId }: { change: ChangeRequest; eventId: number }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const impact = useQuery({
    queryKey: ["change-impact", change.id],
    queryFn: () => getChangeImpact(change.id),
    enabled: open,
  });
  const decide = useMutation({
    mutationFn: (decision: "APPROVE" | "REJECT") => decideChange(change.id, decision, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["change-requests", eventId] });
    },
    onError: () => {
      // A stale or changed request comes back with a fresh assessment.
      void queryClient.invalidateQueries({ queryKey: ["change-impact", change.id] });
    },
  });
  const refusal = decide.error ? refusalOf(decide.error) : null;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-2 text-sm font-medium text-navy-700 underline"
      >
        Review impact
      </button>
    );
  }

  return (
    <div
      role="region"
      aria-label={`Review of change request ${change.id}`}
      className="mt-3 rounded border border-slate-200 bg-slate-50 p-3"
    >
      <h3 className="mb-2 text-sm font-semibold text-navy-700">What this change would affect</h3>
      {impact.isLoading && <p className="text-sm text-slate-500">Assessing the change…</p>}
      {impact.isError && <p role="alert">We could not assess this change.</p>}
      {impact.data && (
        <>
          {impact.data.stale && (
            <p role="alert" className="mb-2 rounded bg-rose-50 p-2 text-sm text-rose-800">
              The event has changed since this was requested. It can be rejected, not approved.
            </p>
          )}
          <Impact assessment={impact.data} />
        </>
      )}

      <div className="mt-4">
        {refusal?.message && (
          <p role="alert" className="mb-2 text-sm text-rose-800">
            {refusal.message}
          </p>
        )}
        <Field label="Reason for your decision" htmlFor={`decision-reason-${change.id}`} error={refusal?.reason}>
          <textarea
            id={`decision-reason-${change.id}`}
            className={inputClass}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <div className="flex gap-3">
          <button
            type="button"
            disabled={decide.isPending || impact.data?.stale}
            onClick={() => decide.mutate("APPROVE")}
            className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Approve change
          </button>
          <button
            type="button"
            disabled={decide.isPending}
            onClick={() => decide.mutate("REJECT")}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm"
          >
            Reject change
          </button>
        </div>
      </div>
    </div>
  );
}
