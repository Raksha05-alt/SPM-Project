import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import {
  cancelEvent,
  completeEvent,
  confirmEvent,
  type MissingArrangement,
} from "../../api/planning";
import type { EventRequest, EventStatus } from "../../types";
import { inputClass } from "../Field";

const CLOSED: EventStatus[] = ["COMPLETED", "CANCELLED", "REJECTED"];

const secondary =
  "rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50";
const primary =
  "rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50";

function missingOf(error: unknown): MissingArrangement[] {
  if (!(error instanceof ApiError)) return [];
  return (error.body as { missing?: MissingArrangement[] } | null)?.missing ?? [];
}

/**
 * SCRUM-58 confirm and SCRUM-56 cancel / complete.
 *
 * Week 7 change 5 - reassignment is no longer the coordinator's: an Event
 * Coordinator Lead assigns and reassigns events.
 */
export function EventActions({ event }: { event: EventRequest }) {
  const queryClient = useQueryClient();
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");

  function onDone(updated: EventRequest) {
    queryClient.setQueryData(["event", event.id], updated);
    void queryClient.invalidateQueries({ queryKey: ["my-events"] });
    void queryClient.invalidateQueries({ queryKey: ["event-history", event.id] });
    void queryClient.invalidateQueries({ queryKey: ["readiness", event.id] });
    setCancelling(false);
  }

  const confirm = useMutation({ mutationFn: () => confirmEvent(event.id), onSuccess: onDone });
  const complete = useMutation({ mutationFn: () => completeEvent(event.id), onSuccess: onDone });
  const cancel = useMutation({
    mutationFn: () => cancelEvent(event.id, reason.trim()),
    onSuccess: onDone,
  });

  const closed = CLOSED.includes(event.status);
  const error = confirm.error ?? complete.error ?? cancel.error;
  const missing = missingOf(confirm.error);

  function openCancel() {
    for (const m of [confirm, complete, cancel]) m.reset();
    setReason("");
    setCancelling(true);
  }

  if (closed) return null;

  return (
    <section aria-label="Event actions" className="mt-6">
      {error && (
        <div role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          <p>{error.message}</p>
          {missing.length > 0 && (
            <ul className="mt-2 list-disc pl-5">
              {missing.map((m, i) => (
                <li key={i}>
                  <span className="font-medium">{m.arrangement}:</span> {m.detail}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {cancelling && (
        <div className="mb-4 rounded-lg border border-rose-200 bg-white p-6">
          <h2 className="mb-3 text-sm font-semibold text-rose-800">Cancel event</h2>
          <label htmlFor="cancel-reason" className="mb-1 block text-sm font-medium">
            Reason (optional)
          </label>
          <textarea
            id="cancel-reason"
            rows={3}
            className={inputClass}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <p className="mt-2 text-xs text-slate-500">
            Cancelling releases the venue, equipment and registrations. It cannot be undone.
          </p>
          <div className="mt-4 flex justify-end gap-3">
            <button type="button" onClick={() => setCancelling(false)} className={secondary}>
              Keep event
            </button>
            <button
              type="button"
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
              className="rounded-md bg-rose-700 px-4 py-2 text-sm font-medium text-white hover:bg-rose-800 disabled:opacity-50"
            >
              Confirm cancellation
            </button>
          </div>
        </div>
      )}

      {!cancelling && (
        <div className="flex flex-wrap justify-end gap-3">
          <button
            type="button"
            onClick={openCancel}
            className="rounded-md border border-rose-300 bg-white px-4 py-2 text-sm font-medium text-rose-800 hover:bg-rose-50"
          >
            Cancel event
          </button>
          {event.status === "CONFIRMED" && (
            <button
              type="button"
              onClick={() => complete.mutate()}
              disabled={complete.isPending}
              className={primary}
            >
              Mark completed
            </button>
          )}
          {event.status === "PLANNING" && (
            <button
              type="button"
              onClick={() => confirm.mutate()}
              disabled={confirm.isPending}
              className={primary}
            >
              Confirm event
            </button>
          )}
        </div>
      )}
    </section>
  );
}
