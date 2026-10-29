import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import { getEventSafety, requestSafetyCheck } from "../../api/safety";
import { inputClass } from "../Field";
import { SafetyStatusBadge, decisionLine, formatDateTime } from "./SafetyStatusBadge";
import type { EventStatus } from "../../types";

const SHOWN_FOR: EventStatus[] = ["PLANNING", "CONFIRMED"];

function GapList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="mt-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
      <p className="font-medium">{title}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * SCRUM-90 AC1/AC4/AC5 - the assigned coordinator sees the event's safety
 * checks, what is still missing, and requests a (new) check.
 */
export function SafetyCheckPanel({ eventId, status }: { eventId: number; status: EventStatus }) {
  const client = useQueryClient();
  const key = ["event-safety", eventId];
  const { data, isLoading, isError } = useQuery({
    queryKey: key,
    queryFn: () => getEventSafety(eventId),
    refetchOnWindowFocus: true,
  });
  const [note, setNote] = useState("");
  const send = useMutation({
    mutationFn: () => requestSafetyCheck(eventId, note.trim()),
    onSuccess: () => setNote(""),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: key });
      void client.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  if (isLoading) return null;
  if (isError || !data) {
    return <p role="alert" className="mt-6 text-sm">We could not load the safety check.</p>;
  }
  if (!SHOWN_FOR.includes(status) && data.checks.length === 0) return null;

  const [latest, ...earlier] = data.checks;
  const refusedGaps =
    send.error instanceof ApiError
      ? ((send.error.body as { arrangement_gaps?: string[] } | null)?.arrangement_gaps ?? [])
      : [];

  return (
    <section
      aria-label="Operational safety check"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="text-sm font-semibold text-navy-700">Operational safety check</h2>

      {latest ? (
        <div className="mt-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <SafetyStatusBadge status={latest.status} label={latest.status_display} />
            <span className="text-slate-500">requested {formatDateTime(latest.requested_at)}</span>
          </div>
          {latest.decided_at && (
            <p className="mt-2">
              {latest.status_display} by {decisionLine(latest.decided_by_name, latest.decided_at)}
            </p>
          )}
          {latest.comment && (
            <p className="mt-1 whitespace-pre-line rounded-md bg-slate-50 p-2">{latest.comment}</p>
          )}
          {latest.status === "SUPERSEDED" && (
            <p className="mt-1 text-slate-600">No longer applies: {latest.superseded_reason}</p>
          )}
          {latest.is_stale && (
            <p className="mt-1 text-rose-700">
              The arrangements changed after this check. Request a new one.
            </p>
          )}
        </div>
      ) : (
        <p className="mt-2 text-sm text-slate-600">No safety check has been requested yet.</p>
      )}

      {status === "PLANNING" && data.arrangement_gaps.length > 0 && (
        <GapList title="Before you can request a check:" items={data.arrangement_gaps} />
      )}
      {data.confirmation_gaps.length > 0 && data.arrangement_gaps.length === 0 && (
        <GapList title="Still needed before confirmation:" items={data.confirmation_gaps} />
      )}

      {data.can_request && (
        <div className="mt-4">
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
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={() => send.mutate()}
              disabled={send.isPending}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
            >
              {latest ? "Request a new safety check" : "Request safety check"}
            </button>
          </div>
        </div>
      )}
      {send.error && (
        <div role="alert" className="mt-3 text-sm text-rose-800">
          <p>{send.error.message}</p>
          {refusedGaps.length > 0 && (
            <ul className="mt-1 list-disc pl-5">
              {refusedGaps.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {earlier.length > 0 && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer text-slate-600">
            Earlier checks ({earlier.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {earlier.map((c) => (
              <li key={c.id} className="rounded-md border border-slate-100 p-2">
                <SafetyStatusBadge status={c.status} label={c.status_display} />{" "}
                <span className="text-slate-500">requested {formatDateTime(c.requested_at)}</span>
                {c.decided_at && (
                  <span className="block">{decisionLine(c.decided_by_name, c.decided_at)}</span>
                )}
                {c.comment && <span className="block">{c.comment}</span>}
                {c.superseded_reason && (
                  <span className="block text-slate-500">{c.superseded_reason}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
