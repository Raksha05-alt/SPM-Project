import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import {
  cancelEvent,
  createChangeRequest,
  getEventRegistrations,
  listChangeRequests,
  type ChangeRequestInput,
  type ConfirmedArrangements,
} from "../../api/organiser";
import type { EventRequest, EventStatus } from "../../types";
import { Field, inputClass } from "../Field";

/** The submitted event, plus the organiser-only fields the API adds to it. */
export type FollowUpEvent = Pick<EventRequest, "id" | "status" | "registration_required"> & {
  cancellation_reason?: string;
  confirmed_arrangements?: ConfirmedArrangements | null;
};

/** SCRUM-20 AC4 - closed events cannot be changed; SCRUM-56 - nor cancelled again. */
const CLOSED: EventStatus[] = ["DRAFT", "CANCELLED", "COMPLETED", "REJECTED"];

const LAYOUTS: Record<string, string> = {
  CLASSROOM: "Classroom",
  THEATRE: "Theatre",
  BOARDROOM: "Boardroom",
  BANQUET: "Banquet",
  EXHIBITION: "Exhibition",
};

function formatDateTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("en-SG") : "—";
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong.";
}

const sectionClass = "mt-6 rounded-lg border border-slate-200 bg-white p-6";
const headingClass = "mb-3 text-lg font-semibold text-navy-700";
const primaryButton =
  "rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600";
const secondaryButton =
  "rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50";

export function EventFollowUp({ event }: { event: FollowUpEvent }) {
  const open = !CLOSED.includes(event.status);
  return (
    <div>
      {event.confirmed_arrangements && (
        <Arrangements arrangements={event.confirmed_arrangements} />
      )}
      {event.status === "CANCELLED" && (
        <section
          aria-label="Cancellation"
          className="mt-6 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
        >
          <p className="font-medium">This event has been cancelled.</p>
          {event.cancellation_reason && <p className="mt-1">Reason: {event.cancellation_reason}</p>}
        </section>
      )}
      <ChangeRequests eventId={event.id} canRaise={open} />
      {event.registration_required && <Registrations eventId={event.id} />}
      {open && <CancelEvent eventId={event.id} />}
    </div>
  );
}

/** SCRUM-58 AC5 - the confirmed venue(s) and equipment. */
function Arrangements({ arrangements }: { arrangements: ConfirmedArrangements }) {
  return (
    <section className={sectionClass} aria-label="Confirmed arrangements">
      <h2 className={headingClass}>Confirmed arrangements</h2>
      <h3 className="text-sm font-medium text-slate-700">Venues</h3>
      {arrangements.venues.length === 0 ? (
        <p className="text-sm text-slate-500">No venue recorded.</p>
      ) : (
        <ul className="mb-3 list-inside list-disc text-sm text-slate-800">
          {arrangements.venues.map((v, i) => (
            <li key={i}>
              {v.venue}
              {v.location ? `, ${v.location}` : ""} · {formatDateTime(v.start)} to{" "}
              {formatDateTime(v.end)}
            </li>
          ))}
        </ul>
      )}
      <h3 className="text-sm font-medium text-slate-700">Equipment</h3>
      {arrangements.equipment.length === 0 ? (
        <p className="text-sm text-slate-500">No equipment reserved.</p>
      ) : (
        <ul className="list-inside list-disc text-sm text-slate-800">
          {arrangements.equipment.map((e, i) => (
            <li key={i}>
              {e.quantity} x {e.equipment}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** SCRUM-56 - cancel after a confirm step, with an optional reason. */
function CancelEvent({ eventId }: { eventId: number }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const cancel = useMutation({
    mutationFn: () => cancelEvent(eventId, reason.trim()),
    onSuccess: () => {
      setConfirming(false);
      void queryClient.invalidateQueries({ queryKey: ["events"] });
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  return (
    <section className={sectionClass}>
      <h2 className={headingClass}>Cancel this event</h2>
      {cancel.error && (
        <p role="alert" className="mb-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {errorMessage(cancel.error)}
        </p>
      )}
      {!confirming ? (
        <button type="button" className={secondaryButton} onClick={() => setConfirming(true)}>
          Cancel event
        </button>
      ) : (
        <div>
          <p className="mb-3 text-sm text-slate-700">
            Cancelling releases any arrangements and cannot be undone.
          </p>
          <Field label="Reason for cancelling (optional)" htmlFor="cancel-reason">
            <textarea
              id="cancel-reason"
              rows={2}
              className={inputClass}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </Field>
          <div className="flex gap-3">
            <button
              type="button"
              className="rounded-md bg-rose-700 px-4 py-2 text-sm font-medium text-white hover:bg-rose-600"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              Confirm cancellation
            </button>
            <button type="button" className={secondaryButton} onClick={() => setConfirming(false)}>
              Keep event
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

const EMPTY_CHANGE: ChangeRequestInput = {
  description: "",
  reason: "",
  proposed_start: null,
  proposed_end: null,
  proposed_attendance: null,
  proposed_layout: "",
  proposed_accessibility_needs: "",
  proposed_equipment_notes: "",
};

/** SCRUM-20 - raise a change request and follow its decision. */
function ChangeRequests({ eventId, canRaise }: { eventId: number; canRaise: boolean }) {
  const queryClient = useQueryClient();
  const { data = [], isLoading, isError } = useQuery({
    queryKey: ["change-requests", eventId],
    queryFn: () => listChangeRequests(eventId),
  });

  const [form, setForm] = useState<ChangeRequestInput>(EMPTY_CHANGE);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [refusal, setRefusal] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  function set<K extends keyof ChangeRequestInput>(key: K, value: ChangeRequestInput[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  const raise = useMutation({
    mutationFn: () => createChangeRequest(eventId, { ...form, description: form.description.trim() }),
    onSuccess: () => {
      setForm(EMPTY_CHANGE);
      setSent(true);
      void queryClient.invalidateQueries({ queryKey: ["change-requests", eventId] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 400 && error.body) {
        const next: Record<string, string> = {};
        for (const [key, value] of Object.entries(error.body as Record<string, unknown>)) {
          if (key === "detail") continue;
          next[key] = Array.isArray(value) ? String(value[0]) : String(value);
        }
        setErrors(next);
        if ("detail" in (error.body as object)) setRefusal(error.message);
        return;
      }
      setRefusal(errorMessage(error));
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSent(false);
    setRefusal(null);
    // SCRUM-20 AC2 - the API also refuses a change request without a description.
    if (!form.description.trim()) {
      setErrors({ description: "Describe the change you want." });
      return;
    }
    setErrors({});
    raise.mutate();
  }

  const toIso = (value: string) => (value ? new Date(value).toISOString() : null);

  return (
    <section className={sectionClass}>
      <h2 className={headingClass}>Change requests</h2>
      {isLoading ? (
        <p className="text-sm text-slate-500">Loading change requests…</p>
      ) : isError ? (
        <p role="alert" className="text-sm text-rose-800">
          We could not load the change requests.
        </p>
      ) : data.length === 0 ? (
        <p className="text-sm text-slate-500">No changes have been requested.</p>
      ) : (
        <ul aria-label="Change requests" className="mb-4 divide-y divide-slate-200">
          {data.map((change) => (
            <li key={change.id} className="py-3 text-sm">
              <div className="flex items-start justify-between gap-4">
                <p className="text-slate-800">{change.description}</p>
                <span className="whitespace-nowrap rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700">
                  {change.status_display}
                </span>
              </div>
              {change.reason && <p className="text-slate-600">Why: {change.reason}</p>}
              <p className="text-xs text-slate-500">Requested {formatDateTime(change.created_at)}</p>
              {change.decided_at && (
                <p className="mt-1 text-xs text-slate-600">
                  {change.status_display} {formatDateTime(change.decided_at)}
                  {change.decided_by_name ? ` by ${change.decided_by_name}` : ""}
                  {change.decision_reason ? ` · Reason: ${change.decision_reason}` : ""}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      {canRaise && (
        <form onSubmit={submit} noValidate className="mt-4 border-t border-slate-200 pt-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Request a change</h3>
          {sent && (
            <p role="status" className="mb-3 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-900">
              Your change request has been sent to your coordinator.
            </p>
          )}
          {refusal && (
            <p role="alert" className="mb-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
              {refusal}
            </p>
          )}
          <Field label="What should change?" htmlFor="change-description" error={errors.description}>
            <textarea
              id="change-description"
              rows={2}
              className={inputClass}
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
            />
          </Field>
          <Field label="Why (optional)" htmlFor="change-reason" error={errors.reason}>
            <input
              id="change-reason"
              className={inputClass}
              value={form.reason ?? ""}
              onChange={(e) => set("reason", e.target.value)}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="New start" htmlFor="change-start" error={errors.proposed_start}>
              <input
                id="change-start"
                type="datetime-local"
                className={inputClass}
                onChange={(e) => set("proposed_start", toIso(e.target.value))}
              />
            </Field>
            <Field label="New end" htmlFor="change-end" error={errors.proposed_end}>
              <input
                id="change-end"
                type="datetime-local"
                className={inputClass}
                onChange={(e) => set("proposed_end", toIso(e.target.value))}
              />
            </Field>
            <Field
              label="New expected attendance"
              htmlFor="change-attendance"
              error={errors.proposed_attendance}
            >
              <input
                id="change-attendance"
                type="number"
                min={1}
                className={inputClass}
                value={form.proposed_attendance ?? ""}
                onChange={(e) =>
                  set("proposed_attendance", e.target.value ? Number(e.target.value) : null)
                }
              />
            </Field>
            <Field label="New room layout" htmlFor="change-layout" error={errors.proposed_layout}>
              <select
                id="change-layout"
                className={inputClass}
                value={form.proposed_layout ?? ""}
                onChange={(e) => set("proposed_layout", e.target.value)}
              >
                <option value="">No change</option>
                {Object.entries(LAYOUTS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="New accessibility needs" htmlFor="change-accessibility">
            <input
              id="change-accessibility"
              className={inputClass}
              value={form.proposed_accessibility_needs ?? ""}
              onChange={(e) => set("proposed_accessibility_needs", e.target.value)}
            />
          </Field>
          <Field label="New equipment needs" htmlFor="change-equipment">
            <input
              id="change-equipment"
              className={inputClass}
              value={form.proposed_equipment_notes ?? ""}
              onChange={(e) => set("proposed_equipment_notes", e.target.value)}
            />
          </Field>
          <button type="submit" className={primaryButton} disabled={raise.isPending}>
            Send change request
          </button>
        </form>
      )}
    </section>
  );
}

/** SCRUM-14 AC5 / SCRUM-19 AC4 - who has registered, with counts and statuses. */
function Registrations({ eventId }: { eventId: number }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["event-registrations", eventId],
    queryFn: () => getEventRegistrations(eventId),
  });

  return (
    <section className={sectionClass}>
      <h2 className={headingClass}>Registrations</h2>
      {isLoading ? (
        <p className="text-sm text-slate-500">Loading registrations…</p>
      ) : isError || !data ? (
        <p role="alert" className="text-sm text-rose-800">
          We could not load the registrations.
        </p>
      ) : (
        <>
          <p className="mb-3 text-sm text-slate-700">
            {data.registered_count} registered
            {data.capacity !== null ? ` of ${data.capacity} places` : ""} ·{" "}
            {data.waitlist_count} on the waiting list
            {data.places_left !== null ? ` · ${data.places_left} places left` : ""}
          </p>
          {data.registrations.length === 0 ? (
            <p className="text-sm text-slate-500">Nobody has registered yet.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-2">Name</th>
                  <th className="py-2">Email</th>
                  <th className="py-2">Accessibility needs</th>
                  <th className="py-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {data.registrations.map((r) => (
                  <tr key={r.id}>
                    <td className="py-2">{r.full_name}</td>
                    <td className="py-2">{r.email}</td>
                    <td className="py-2">{r.accessibility_needs || "—"}</td>
                    <td className="py-2">{r.status_display}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
