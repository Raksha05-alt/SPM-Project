import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { updateEvent } from "../api/events";
import type { EventDraft } from "../api/events";
import { fieldErrors } from "./venues/VenueForm";
import { Field, inputClass } from "./Field";
import { selectableLayouts, useLayouts } from "./layouts/useLayouts";
import type { EventRequest } from "../types";

type Draft = Required<
  Pick<
    EventDraft,
    | "name"
    | "purpose"
    | "description"
    | "preferred_start"
    | "preferred_end"
    | "expected_attendance"
    | "required_layout"
    | "accessibility_needs"
    | "equipment_notes"
    | "registration_required"
  >
>;

/** An ISO instant as the browser's local "YYYY-MM-DDTHH:mm" for a datetime-local input. */
export function toLocalInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

function draftOf(event: EventRequest): Draft {
  return {
    name: event.name,
    purpose: event.purpose,
    description: event.description,
    preferred_start: event.preferred_start,
    preferred_end: event.preferred_end,
    expected_attendance: event.expected_attendance,
    required_layout: event.required_layout,
    accessibility_needs: event.accessibility_needs,
    equipment_notes: event.equipment_notes,
    registration_required: event.registration_required,
  };
}

/** Only the fields the coordinator actually changed, so an untouched save changes nothing. */
export function changedFields(event: EventRequest, draft: Draft): EventDraft {
  const original = draftOf(event);
  const changes: EventDraft = {};
  for (const key of Object.keys(draft) as (keyof Draft)[]) {
    const before = original[key];
    const after = draft[key];
    const same =
      key === "preferred_start" || key === "preferred_end"
        ? (before ? new Date(before as string).getTime() : null) ===
          (after ? new Date(after as string).getTime() : null)
        : before === after;
    if (!same) (changes as Record<string, unknown>)[key] = after;
  }
  return changes;
}

/** SCRUM-61 - the assigned coordinator updates the request as planning progresses. */
export function CoordinatorEventEditor({
  event,
  onSaved,
  onCancel,
}: {
  event: EventRequest;
  onSaved: (updated: EventRequest) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(event));
  const { layouts } = useLayouts();
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const save = useMutation({
    mutationFn: () => updateEvent(event.id, changedFields(event, draft)),
    onSuccess: onSaved,
  });
  const errors = fieldErrors(save.error);

  return (
    <section
      aria-label="Edit event details"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="mb-1 text-sm font-semibold text-navy-700">Edit event details</h2>
      <p className="mb-4 text-xs text-slate-500">
        Changes are saved for everyone working on this event. Changing the date, time or
        attendance means any approved safety check must be requested again.
      </p>
      {save.error && Object.keys(errors).length === 0 && (
        <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {save.error.message}
        </p>
      )}
      <div className="grid gap-x-6 sm:grid-cols-2">
        <Field label="Event name" htmlFor="edit-name" error={errors.name}>
          <input
            id="edit-name"
            className={inputClass}
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </Field>
        <Field label="Purpose" htmlFor="edit-purpose" error={errors.purpose}>
          <input
            id="edit-purpose"
            className={inputClass}
            value={draft.purpose}
            onChange={(e) => set("purpose", e.target.value)}
          />
        </Field>
        <Field label="Preferred start" htmlFor="edit-start" error={errors.preferred_start}>
          <input
            id="edit-start"
            type="datetime-local"
            className={inputClass}
            value={toLocalInput(draft.preferred_start)}
            onChange={(e) => set("preferred_start", fromLocalInput(e.target.value))}
          />
        </Field>
        <Field label="Preferred end" htmlFor="edit-end" error={errors.preferred_end}>
          <input
            id="edit-end"
            type="datetime-local"
            className={inputClass}
            value={toLocalInput(draft.preferred_end)}
            onChange={(e) => set("preferred_end", fromLocalInput(e.target.value))}
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
            className={inputClass}
            value={draft.expected_attendance ?? ""}
            onChange={(e) =>
              set("expected_attendance", e.target.value === "" ? null : Number(e.target.value))
            }
          />
        </Field>
        <Field label="Required room layout" htmlFor="edit-layout" error={errors.required_layout}>
          <select
            id="edit-layout"
            className={inputClass}
            value={draft.required_layout}
            onChange={(e) => set("required_layout", e.target.value)}
          >
            <option value="">No preference</option>
            {selectableLayouts(layouts, [event.required_layout]).map((layout) => (
              <option key={layout.code} value={layout.code}>
                {layout.is_active ? layout.name : `${layout.name} (retired)`}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="Description" htmlFor="edit-description" error={errors.description}>
        <textarea
          id="edit-description"
          className={inputClass}
          value={draft.description}
          onChange={(e) => set("description", e.target.value)}
        />
      </Field>
      <Field label="Accessibility needs" htmlFor="edit-access" error={errors.accessibility_needs}>
        <textarea
          id="edit-access"
          className={inputClass}
          value={draft.accessibility_needs}
          onChange={(e) => set("accessibility_needs", e.target.value)}
        />
      </Field>
      <Field label="Equipment and technical requirements" htmlFor="edit-equipment">
        <textarea
          id="edit-equipment"
          className={inputClass}
          value={draft.equipment_notes}
          onChange={(e) => set("equipment_notes", e.target.value)}
        />
      </Field>
      <label className="mb-4 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={draft.registration_required}
          onChange={(e) => set("registration_required", e.target.checked)}
        />
        Attendees will need to register for this event
      </label>
      <div className="flex justify-end gap-3">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
        >
          Save changes
        </button>
      </div>
    </section>
  );
}
