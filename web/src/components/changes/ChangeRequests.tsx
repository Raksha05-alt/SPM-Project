import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { listChangeRequests, requestChange } from "../../api/changeRequests";
import type { EventStatus } from "../../types";
import { Field, inputClass } from "../Field";
import { selectableLayouts, useLayouts } from "../layouts/useLayouts";
import { ChangeProgress } from "./ChangeProgress";
import { ChangeReview } from "./ChangeReview";

/** Statuses that accept a change request; the API enforces the same rule. */
const OPEN_TO_CHANGE_REQUESTS: EventStatus[] = [
  "SUBMITTED",
  "UNDER_REVIEW",
  "APPROVED",
  "PLANNING",
  "CONFIRMED",
];

const EMPTY = {
  description: "",
  reason: "",
  preferred_start: "",
  preferred_end: "",
  expected_attendance: "",
  required_layout: "",
  accessibility_needs: "",
  equipment_notes: "",
};

type Form = typeof EMPTY;

/** Only the proposed values the organiser actually filled in, typed for the API. */
export function proposedValues(form: Form): Record<string, string | number | null> {
  const values: Record<string, string | number | null> = {};
  if (form.preferred_start) values.preferred_start = new Date(form.preferred_start).toISOString();
  if (form.preferred_end) values.preferred_end = new Date(form.preferred_end).toISOString();
  if (form.expected_attendance !== "") values.expected_attendance = Number(form.expected_attendance);
  if (form.required_layout) values.required_layout = form.required_layout;
  if (form.accessibility_needs.trim()) values.accessibility_needs = form.accessibility_needs;
  if (form.equipment_notes.trim()) values.equipment_notes = form.equipment_notes;
  return values;
}

/** One message per field from a 400 ("proposed_values.x" keys map to field x). */
export function changeRefusal(error: unknown): { detail: string; fields: Record<string, string> } {
  if (!(error instanceof ApiError)) return { detail: "We could not send the request.", fields: {} };
  if (error.status !== 400) return { detail: error.message, fields: {} };
  const body = (error.body ?? {}) as Record<string, unknown>;
  const fields = Object.fromEntries(
    Object.entries(body)
      .filter(([key]) => key !== "detail")
      .map(([key, value]) => [
        key.replace(/^proposed_values\./, ""),
        Array.isArray(value) ? String(value[0]) : String(value),
      ]),
  );
  return { detail: error.message, fields };
}

/**
 * SCRUM-20 - an event's change requests, with their status and any decision
 * (AC5). The organiser (``canRequest``) can raise one for a submitted or
 * confirmed event (AC1); staff see the same list read-only.
 */
export function ChangeRequests({
  eventId,
  eventStatus,
  canRequest = false,
  canDecide = false,
}: {
  eventId: number;
  eventStatus: EventStatus;
  canRequest?: boolean;
  canDecide?: boolean;
}) {
  const queryClient = useQueryClient();
  const changes = useQuery({
    queryKey: ["change-requests", eventId],
    queryFn: () => listChangeRequests(eventId),
  });
  const open = canRequest && OPEN_TO_CHANGE_REQUESTS.includes(eventStatus);
  const { layouts } = useLayouts();
  const [form, setForm] = useState<Form>(EMPTY);
  const [receipt, setReceipt] = useState<string | null>(null);
  const set = (key: keyof Form, value: string) => setForm((current) => ({ ...current, [key]: value }));

  const send = useMutation({
    mutationFn: () =>
      requestChange(eventId, {
        description: form.description,
        reason: form.reason,
        proposed_values: proposedValues(form),
      }),
    onSuccess: (result) => {
      setReceipt(result.detail);
      setForm(EMPTY);
      void queryClient.invalidateQueries({ queryKey: ["change-requests", eventId] });
    },
  });
  const refusal = send.error ? changeRefusal(send.error) : null;
  const rows = changes.data ?? [];

  return (
    <section
      aria-label="Change requests"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="mb-3 text-sm font-semibold text-navy-700">Change requests</h2>

      {changes.isError && <p role="alert">We could not load the change requests.</p>}
      {rows.length === 0 && !changes.isLoading && !changes.isError && (
        <p className="mb-4 text-sm text-slate-500">No changes have been requested.</p>
      )}
      {rows.length > 0 && (
        <ul className="mb-4 space-y-3">
          {rows.map((change) => (
            <li
              key={change.id}
              aria-label={`Change request ${change.id}`}
              className="rounded border border-slate-200 p-4 text-sm"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-medium text-navy-700 whitespace-pre-line">{change.description}</p>
                <span className="flex items-baseline gap-2">
                  {/* SCRUM-59 AC1 - flagged when arrangements may be affected. */}
                  {change.significant && (
                    <span className="rounded bg-amber-100 px-2 text-xs font-medium text-amber-900">
                      Significant
                    </span>
                  )}
                  {/* AC5 - its current status. */}
                  <span className="font-medium">{change.status_label}</span>
                </span>
              </div>
              <p className="mt-1 text-slate-600 whitespace-pre-line">Why: {change.reason}</p>
              {change.proposed_changes.length > 0 && (
                <ul className="mt-2 list-inside list-disc text-slate-700">
                  {change.proposed_changes.map((row) => (
                    <li key={row.field}>
                      {row.label}: {row.current} → {row.proposed}
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-xs text-slate-500">
                Requested by {change.requested_by_name ?? "Deleted user"} on{" "}
                {new Date(change.requested_at).toLocaleString("en-SG")}
              </p>
              {/* AC5 - any decision made (recorded under SCRUM-78). */}
              {change.decided_at && (
                <p className="mt-1 text-xs text-slate-600">
                  {change.status_label} by {change.decided_by_name ?? "Deleted user"} on{" "}
                  {new Date(change.decided_at).toLocaleString("en-SG")}
                  {change.decision_reason ? `: ${change.decision_reason}` : ""}
                </p>
              )}
              {/* SCRUM-78 - the assigned coordinator assesses and decides. */}
              {canDecide && change.status === "PENDING" && (
                <ChangeReview change={change} eventId={eventId} />
              )}
              {/* SCRUM-80 - applying an approved change, and its history (AC5). */}
              {!["PENDING", "REJECTED"].includes(change.status) && (
                <ChangeProgress change={change} eventId={eventId} canDecide={canDecide} />
              )}
            </li>
          ))}
        </ul>
      )}

      {canRequest && !open && (
        <p className="text-sm text-slate-500">
          Changes cannot be requested for this event in its current status.
        </p>
      )}
      {open && (
        <form
          aria-label="Request a change"
          onSubmit={(e) => {
            e.preventDefault();
            setReceipt(null);
            send.mutate();
          }}
        >
          {receipt && (
            <p role="status" className="mb-4 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
              {receipt}
            </p>
          )}
          {refusal && Object.keys(refusal.fields).length === 0 && (
            <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
              {refusal.detail}
            </p>
          )}
          {refusal?.fields.event && (
            <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
              {refusal.fields.event}
            </p>
          )}
          <Field
            label="What do you want changed?"
            htmlFor="change-description"
            error={refusal?.fields.description}
          >
            <textarea
              id="change-description"
              className={inputClass}
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
            />
          </Field>
          <Field label="Why is the change needed?" htmlFor="change-reason" error={refusal?.fields.reason}>
            <textarea
              id="change-reason"
              className={inputClass}
              value={form.reason}
              onChange={(e) => set("reason", e.target.value)}
            />
          </Field>

          <fieldset className="mb-4">
            <legend className="mb-2 text-sm font-medium text-slate-700">
              New details (optional) - fill in only what should change
            </legend>
            {refusal?.fields.proposed_values && (
              <p role="alert" className="mb-2 text-xs text-rose-700">
                {refusal.fields.proposed_values}
              </p>
            )}
            <div className="grid gap-x-6 sm:grid-cols-2">
              <Field label="Proposed start" htmlFor="change-start" error={refusal?.fields.preferred_start}>
                <input
                  id="change-start"
                  type="datetime-local"
                  className={inputClass}
                  value={form.preferred_start}
                  onChange={(e) => set("preferred_start", e.target.value)}
                />
              </Field>
              <Field label="Proposed end" htmlFor="change-end" error={refusal?.fields.preferred_end}>
                <input
                  id="change-end"
                  type="datetime-local"
                  className={inputClass}
                  value={form.preferred_end}
                  onChange={(e) => set("preferred_end", e.target.value)}
                />
              </Field>
              <Field
                label="Proposed attendance"
                htmlFor="change-attendance"
                error={refusal?.fields.expected_attendance}
              >
                <input
                  id="change-attendance"
                  type="number"
                  className={inputClass}
                  value={form.expected_attendance}
                  onChange={(e) => set("expected_attendance", e.target.value)}
                />
              </Field>
              <Field
                label="Proposed layout"
                htmlFor="change-layout"
                error={refusal?.fields.required_layout}
              >
                <select
                  id="change-layout"
                  className={inputClass}
                  value={form.required_layout}
                  onChange={(e) => set("required_layout", e.target.value)}
                >
                  <option value="">No change</option>
                  {selectableLayouts(layouts).map((layout) => (
                    <option key={layout.code} value={layout.code}>
                      {layout.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field
              label="Proposed accessibility arrangements"
              htmlFor="change-accessibility"
              error={refusal?.fields.accessibility_needs}
            >
              <textarea
                id="change-accessibility"
                className={inputClass}
                value={form.accessibility_needs}
                onChange={(e) => set("accessibility_needs", e.target.value)}
              />
            </Field>
            <Field
              label="Proposed equipment needs"
              htmlFor="change-equipment"
              error={refusal?.fields.equipment_notes}
            >
              <textarea
                id="change-equipment"
                className={inputClass}
                value={form.equipment_notes}
                onChange={(e) => set("equipment_notes", e.target.value)}
              />
            </Field>
          </fieldset>
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={send.isPending}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
            >
              Send change request
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
