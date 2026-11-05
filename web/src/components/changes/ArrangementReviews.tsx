import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { decideArrangement, listArrangementReviews } from "../../api/changeRequests";
import type { ArrangementReviewItem } from "../../types";
import { Field, inputClass } from "../Field";

function period(values: Record<string, unknown>) {
  const start = values.starts_at as string | null | undefined;
  const end = values.ends_at as string | null | undefined;
  if (!start || !end) return "Same period";
  return `${new Date(start).toLocaleString("en-SG")} – ${new Date(end).toLocaleTimeString("en-SG")}`;
}

function refusal(error: unknown) {
  if (!(error instanceof ApiError)) return "We could not record your outcome.";
  const body = (error.body ?? {}) as { reason?: string[]; outcome?: string[]; problems?: string[] };
  if (body.reason) return body.reason[0];
  if (body.outcome) return body.outcome[0];
  return [error.message, ...(body.problems ?? [])].join(" ");
}

function ReviewItem({
  item,
  onRecorded,
}: {
  item: ArrangementReviewItem;
  onRecorded: (detail: string) => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const decide = useMutation({
    mutationFn: (outcome: "ACCOMMODATED" | "NOT_ACCOMMODATED") =>
      decideArrangement(item.id, outcome, reason),
    onSuccess: (result) => {
      // The recorded item leaves the pending list, so the section shows the receipt.
      onRecorded(result.detail);
      void queryClient.invalidateQueries({ queryKey: ["arrangement-reviews"] });
    },
  });

  return (
    <li
      aria-label={`Review of ${item.name} for ${item.event_name}`}
      className="rounded border border-slate-200 bg-white p-4 text-sm"
    >
      <p className="font-medium text-navy-700">
        {item.name}
        {item.quantity != null ? ` (${item.quantity})` : ""} – {item.event_name}
      </p>
      <p className="mt-1 text-slate-600">Approved change: {item.change_description}</p>
      <p className="mt-1">
        Current: {period(item.before)}
        {item.before.attendance != null && `, ${item.before.attendance} people`}
      </p>
      <p>
        Proposed: {period(item.proposed)}
        {item.proposed.attendance != null && `, ${item.proposed.attendance} people`}
      </p>
      {item.reasons.length > 0 && (
        <ul className="mt-1 list-inside list-disc text-amber-900">
          {item.reasons.map((reasonText) => (
            <li key={reasonText}>{reasonText}</li>
          ))}
        </ul>
      )}
      <div className="mt-3">
        {decide.isError && (
          <p role="alert" className="mb-2 text-rose-800">
            {refusal(decide.error)}
          </p>
        )}
        <Field label="Reason for your outcome" htmlFor={`outcome-reason-${item.id}`}>
          <textarea
            id={`outcome-reason-${item.id}`}
            className={inputClass}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <div className="flex gap-3">
          <button
            type="button"
            disabled={decide.isPending}
            onClick={() => decide.mutate("ACCOMMODATED")}
            className="rounded-md bg-navy-700 px-4 py-2 font-medium text-white disabled:opacity-50"
          >
            Can accommodate
          </button>
          <button
            type="button"
            disabled={decide.isPending}
            onClick={() => decide.mutate("NOT_ACCOMMODATED")}
            className="rounded-md border border-slate-300 bg-white px-4 py-2"
          >
            Cannot accommodate
          </button>
        </div>
      </div>
    </li>
  );
}

/**
 * SCRUM-80 AC1-AC3 - Venue Staff or Technical Support review each arrangement
 * an approved change affects, and record whether they can accommodate it.
 */
export function ArrangementReviews() {
  const [recorded, setRecorded] = useState<string | null>(null);
  const reviews = useQuery({
    queryKey: ["arrangement-reviews"],
    queryFn: () => listArrangementReviews("PENDING"),
  });
  const items = reviews.data ?? [];

  return (
    <section aria-label="Approved changes to review" className="mb-8">
      <h2 className="mb-3 text-lg font-semibold text-navy-700">Approved changes to review</h2>
      {recorded && (
        <p role="status" className="mb-3 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
          {recorded}
        </p>
      )}
      {reviews.isError && <p role="alert">We could not load the changes to review.</p>}
      {!reviews.isLoading && !reviews.isError && items.length === 0 && (
        <p className="text-sm text-slate-500">No approved changes are waiting for your review.</p>
      )}
      {items.length > 0 && (
        <ul className="space-y-3">
          {items.map((item) => (
            <ReviewItem key={item.id} item={item} onRecorded={setRecorded} />
          ))}
        </ul>
      )}
    </section>
  );
}
