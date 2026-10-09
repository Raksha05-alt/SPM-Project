import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import {
  cancelEvent,
  completeEvent,
  confirmEvent,
  listCoordinators,
  reassignEvent,
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

/** SCRUM-58 confirm, SCRUM-56 cancel / complete, SCRUM-53 reassign. */
export function EventActions({ event }: { event: EventRequest }) {
  const queryClient = useQueryClient();
  const [panel, setPanel] = useState<"cancel" | "reassign" | null>(null);
  const [reason, setReason] = useState("");
  const [coordinator, setCoordinator] = useState("");
  const [choiceError, setChoiceError] = useState<string | null>(null);

  function onDone(updated: EventRequest) {
    queryClient.setQueryData(["event", event.id], updated);
    void queryClient.invalidateQueries({ queryKey: ["my-events"] });
    void queryClient.invalidateQueries({ queryKey: ["queue"] });
    void queryClient.invalidateQueries({ queryKey: ["event-history", event.id] });
    setPanel(null);
  }

  const confirm = useMutation({ mutationFn: () => confirmEvent(event.id), onSuccess: onDone });
  const complete = useMutation({ mutationFn: () => completeEvent(event.id), onSuccess: onDone });
  const cancel = useMutation({
    mutationFn: () => cancelEvent(event.id, reason.trim()),
    onSuccess: onDone,
  });
  const reassign = useMutation({
    mutationFn: () => reassignEvent(event.id, Number(coordinator)),
    onSuccess: onDone,
  });

  const coordinators = useQuery({
    queryKey: ["coordinators"],
    queryFn: listCoordinators,
    enabled: panel === "reassign",
  });

  const closed = CLOSED.includes(event.status);
  const error = confirm.error ?? complete.error ?? cancel.error ?? reassign.error;
  const missing = missingOf(confirm.error);

  function open(which: "cancel" | "reassign") {
    for (const m of [confirm, complete, cancel, reassign]) m.reset();
    setReason("");
    setCoordinator("");
    setChoiceError(null);
    setPanel(which);
  }

  function submitReassign() {
    if (!coordinator) {
      setChoiceError("Choose a coordinator.");
      return;
    }
    setChoiceError(null);
    reassign.mutate();
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

      {panel === "cancel" && (
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
            <button type="button" onClick={() => setPanel(null)} className={secondary}>
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

      {panel === "reassign" && (
        <div className="mb-4 rounded-lg border border-slate-200 bg-white p-6">
          <h2 className="mb-3 text-sm font-semibold text-navy-700">Reassign event</h2>
          <label htmlFor="reassign-coordinator" className="mb-1 block text-sm font-medium">
            New coordinator
          </label>
          <select
            id="reassign-coordinator"
            className={inputClass}
            value={coordinator}
            onChange={(e) => setCoordinator(e.target.value)}
          >
            <option value="">Choose a coordinator</option>
            {(coordinators.data ?? [])
              .filter((c) => c.id !== event.coordinator)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                  {c.available ? "" : " (unavailable)"}
                </option>
              ))}
          </select>
          {choiceError && (
            <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
              {choiceError}
            </p>
          )}
          <div className="mt-4 flex justify-end gap-3">
            <button type="button" onClick={() => setPanel(null)} className={secondary}>
              Back
            </button>
            <button
              type="button"
              onClick={submitReassign}
              disabled={reassign.isPending}
              className={primary}
            >
              Confirm reassignment
            </button>
          </div>
        </div>
      )}

      {panel === null && (
        <div className="flex flex-wrap justify-end gap-3">
          <button
            type="button"
            onClick={() => open("cancel")}
            className="rounded-md border border-rose-300 bg-white px-4 py-2 text-sm font-medium text-rose-800 hover:bg-rose-50"
          >
            Cancel event
          </button>
          <button type="button" onClick={() => open("reassign")} className={secondary}>
            Reassign
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
