import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import {
  LAYOUT_OPTIONS,
  fieldErrorsOf,
  fromLocalInput,
  toLocalInput,
  updateEvent,
  type EventPatch,
  type SignificantChange,
} from "../../api/planning";
import type { EventRequest } from "../../types";
import { Field, inputClass } from "../Field";

type Form = {
  name: string;
  purpose: string;
  description: string;
  preferred_start: string;
  preferred_end: string;
  expected_attendance: string;
  required_layout: string;
  accessibility_needs: string;
  equipment_notes: string;
};

function formFrom(event: EventRequest): Form {
  return {
    name: event.name,
    purpose: event.purpose,
    description: event.description,
    preferred_start: toLocalInput(event.preferred_start),
    preferred_end: toLocalInput(event.preferred_end),
    expected_attendance: event.expected_attendance?.toString() ?? "",
    required_layout: event.required_layout,
    accessibility_needs: event.accessibility_needs,
    equipment_notes: event.equipment_notes,
  };
}

/** Only the fields the coordinator actually changed are sent. */
function patchFrom(form: Form, original: Form): EventPatch {
  const patch: EventPatch = {};
  const text = [
    "name",
    "purpose",
    "description",
    "required_layout",
    "accessibility_needs",
    "equipment_notes",
  ] as const;
  for (const key of text) if (form[key] !== original[key]) patch[key] = form[key];
  if (form.preferred_start !== original.preferred_start)
    patch.preferred_start = fromLocalInput(form.preferred_start);
  if (form.preferred_end !== original.preferred_end)
    patch.preferred_end = fromLocalInput(form.preferred_end);
  if (form.expected_attendance !== original.expected_attendance)
    patch.expected_attendance = form.expected_attendance ? Number(form.expected_attendance) : null;
  return patch;
}

/** SCRUM-61 edit during planning; SCRUM-59 warn about a significant change. */
export function EventEditPanel({ event }: { event: EventRequest }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Form>(() => formFrom(event));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [outcome, setOutcome] = useState<SignificantChange | "saved" | null>(null);

  const save = useMutation({
    mutationFn: (patch: EventPatch) => updateEvent(event.id, patch),
    onSuccess: (updated) => {
      const { significant_change, ...rest } = updated;
      queryClient.setQueryData(["event", event.id], rest);
      void queryClient.invalidateQueries({ queryKey: ["event-history", event.id] });
      const change = significant_change;
      setOutcome(
        change && (change.significant || change.affected_arrangements.length > 0)
          ? change
          : "saved",
      );
      setEditing(false);
    },
    onError: (error) => {
      if (error instanceof ApiError) setErrors(fieldErrorsOf(error.body));
    },
  });

  function set<K extends keyof Form>(key: K, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function open() {
    setForm(formFrom(event));
    setErrors({});
    setOutcome(null);
    save.reset();
    setEditing(true);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const found: Record<string, string> = {};
    if (!form.name.trim()) found.name = "Enter the event name.";
    if (form.expected_attendance && Number(form.expected_attendance) < 1)
      found.expected_attendance = "Expected attendance must be at least one person.";
    if (
      form.preferred_start &&
      form.preferred_end &&
      new Date(form.preferred_end) <= new Date(form.preferred_start)
    )
      found.preferred_end = "The event must end after it starts.";
    setErrors(found);
    if (Object.keys(found).length) return;
    const patch = patchFrom(form, formFrom(event));
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      return;
    }
    save.mutate(patch);
  }

  return (
    <section
      aria-label="Edit event details"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-navy-700">Event details</h2>
        {!editing && (
          <button
            type="button"
            onClick={open}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
          >
            Edit event details
          </button>
        )}
      </div>

      {outcome === "saved" && <p className="mt-3 text-sm text-emerald-800">Changes saved.</p>}
      {outcome && outcome !== "saved" && (
        <div
          role="alert"
          className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
        >
          <p className="font-semibold">
            Significant change: {outcome.changed_fields.join(", ")}.
          </p>
          {outcome.affected_arrangements.length > 0 ? (
            <>
              <p className="mt-1">These arrangements are affected and have been sent for review:</p>
              <ul className="mt-1 list-disc pl-5">
                {outcome.affected_arrangements.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          ) : (
            <p className="mt-1">No existing arrangements are affected.</p>
          )}
        </div>
      )}

      {editing && (
        <form onSubmit={submit} noValidate className="mt-4">
          {save.error && Object.keys(errors).length === 0 && (
            <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
              {save.error.message}
            </p>
          )}
          <Field label="Event name" htmlFor="edit-name" error={errors.name}>
            <input
              id="edit-name"
              className={inputClass}
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
            />
          </Field>
          <Field label="Purpose" htmlFor="edit-purpose" error={errors.purpose}>
            <input
              id="edit-purpose"
              className={inputClass}
              value={form.purpose}
              onChange={(e) => set("purpose", e.target.value)}
            />
          </Field>
          <Field label="Description" htmlFor="edit-description" error={errors.description}>
            <textarea
              id="edit-description"
              rows={3}
              className={inputClass}
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Start" htmlFor="edit-start" error={errors.preferred_start}>
              <input
                id="edit-start"
                type="datetime-local"
                className={inputClass}
                value={form.preferred_start}
                onChange={(e) => set("preferred_start", e.target.value)}
              />
            </Field>
            <Field label="End" htmlFor="edit-end" error={errors.preferred_end}>
              <input
                id="edit-end"
                type="datetime-local"
                className={inputClass}
                value={form.preferred_end}
                onChange={(e) => set("preferred_end", e.target.value)}
              />
            </Field>
            <Field
              label="Expected attendance"
              htmlFor="edit-attendance"
              error={errors.expected_attendance}
            >
              <input
                id="edit-attendance"
                type="number"
                min={1}
                className={inputClass}
                value={form.expected_attendance}
                onChange={(e) => set("expected_attendance", e.target.value)}
              />
            </Field>
            <Field label="Room layout" htmlFor="edit-layout" error={errors.required_layout}>
              <select
                id="edit-layout"
                className={inputClass}
                value={form.required_layout}
                onChange={(e) => set("required_layout", e.target.value)}
              >
                <option value="">No preference</option>
                {LAYOUT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field
            label="Accessibility needs"
            htmlFor="edit-accessibility"
            error={errors.accessibility_needs}
          >
            <textarea
              id="edit-accessibility"
              rows={2}
              className={inputClass}
              value={form.accessibility_needs}
              onChange={(e) => set("accessibility_needs", e.target.value)}
            />
          </Field>
          <Field
            label="Equipment and technical requirements"
            htmlFor="edit-equipment"
            error={errors.equipment_notes}
          >
            <textarea
              id="edit-equipment"
              rows={2}
              className={inputClass}
              value={form.equipment_notes}
              onChange={(e) => set("equipment_notes", e.target.value)}
            />
          </Field>
          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
            >
              Discard
            </button>
            <button
              type="submit"
              disabled={save.isPending}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
            >
              Save changes
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
