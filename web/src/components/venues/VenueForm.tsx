import { useState } from "react";
import { ApiError } from "../../api/client";
import type { VenueInput } from "../../api/venues";
import type { Venue } from "../../types";
import { Field, inputClass } from "../Field";

const LAYOUTS: [string, string][] = [
  ["CLASSROOM", "Classroom"],
  ["THEATRE", "Theatre"],
  ["BOARDROOM", "Boardroom"],
  ["BANQUET", "Banquet"],
  ["EXHIBITION", "Exhibition"],
];

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const EMPTY: VenueInput = {
  name: "",
  location: "",
  capacity: 0,
  facilities: [],
  layouts: [],
  wheelchair_access: null,
  accessibility_notes: "",
  opens_at: null,
  closes_at: null,
  operating_days: [0, 1, 2, 3, 4, 5, 6],
  in_service: true,
};

type Errors = Record<string, string>;

function toInput(venue: Venue | null): VenueInput {
  if (!venue) return EMPTY;
  const {
    id: _id,
    layout_labels: _l,
    operating_hours: _h,
    created_by_name: _c,
    updated_by_name: _u,
    created_at: _ca,
    updated_at: _ua,
    ...rest
  } = venue;
  return {
    ...rest,
    opens_at: venue.opens_at?.slice(0, 5) ?? null,
    closes_at: venue.closes_at?.slice(0, 5) ?? null,
  };
}

/** Turn a DRF 400 body ({field: [message]}) into one message per field. */
export function fieldErrors(error: unknown): Errors {
  if (!(error instanceof ApiError) || error.status !== 400) return {};
  const body = (error.body ?? {}) as Record<string, unknown>;
  return Object.fromEntries(
    Object.entries(body).map(([key, value]) => [
      key,
      Array.isArray(value) ? String(value[0]) : String(value),
    ]),
  );
}

export function VenueForm({
  venue,
  saving,
  error,
  onSave,
  onCancel,
}: {
  venue: Venue | null;
  saving: boolean;
  error: unknown;
  onSave: (input: VenueInput) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<VenueInput>(() => toInput(venue));
  const [facilities, setFacilities] = useState(form.facilities.join(", "));
  const errors = fieldErrors(error);
  const set = <K extends keyof VenueInput>(key: K, value: VenueInput[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const toggle = (list: string[] | number[], item: string | number) =>
    (list as (string | number)[]).includes(item)
      ? (list as (string | number)[]).filter((x) => x !== item)
      : [...list, item];

  function submit(event: React.FormEvent) {
    event.preventDefault();
    onSave({
      ...form,
      facilities: facilities
        .split(",")
        .map((f) => f.trim())
        .filter(Boolean),
      opens_at: form.opens_at || null,
      closes_at: form.closes_at || null,
    });
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-lg border border-slate-200 bg-white p-6"
      aria-label="Venue details"
    >
      <h2 className="mb-4 text-lg font-semibold text-navy-700">
        {venue ? `Edit ${venue.name}` : "New venue"}
      </h2>
      {error && !(error instanceof ApiError && error.status === 400) ? (
        <p role="alert" className="mb-4 text-sm text-rose-700">
          {error instanceof ApiError && error.status === 403
            ? "Only Venue Staff can create or edit venues."
            : "We could not save the venue."}
        </p>
      ) : null}

      <div className="grid gap-x-6 sm:grid-cols-2">
        <Field label="Name" htmlFor="v-name" error={errors.name}>
          <input
            id="v-name"
            className={inputClass}
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </Field>
        <Field label="Location" htmlFor="v-location" error={errors.location}>
          <input
            id="v-location"
            className={inputClass}
            value={form.location}
            onChange={(e) => set("location", e.target.value)}
          />
        </Field>
        <Field label="Maximum capacity" htmlFor="v-capacity" error={errors.capacity}>
          <input
            id="v-capacity"
            type="number"
            className={inputClass}
            value={form.capacity}
            onChange={(e) => set("capacity", Number(e.target.value))}
          />
        </Field>
        <Field
          label="Facilities"
          htmlFor="v-facilities"
          hint="Separate with commas"
          error={errors.facilities}
        >
          <input
            id="v-facilities"
            className={inputClass}
            value={facilities}
            onChange={(e) => setFacilities(e.target.value)}
          />
        </Field>
        <Field label="Opens at" htmlFor="v-opens" error={errors.opens_at}>
          <input
            id="v-opens"
            type="time"
            className={inputClass}
            value={form.opens_at ?? ""}
            onChange={(e) => set("opens_at", e.target.value)}
          />
        </Field>
        <Field label="Closes at" htmlFor="v-closes" error={errors.closes_at}>
          <input
            id="v-closes"
            type="time"
            className={inputClass}
            value={form.closes_at ?? ""}
            onChange={(e) => set("closes_at", e.target.value)}
          />
        </Field>
      </div>

      <fieldset className="mb-4">
        <legend className="mb-1 text-sm font-medium text-slate-700">Operating days</legend>
        <div className="flex flex-wrap gap-3 text-sm">
          {DAYS.map((day, index) => (
            <label key={day} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={form.operating_days.includes(index)}
                onChange={() =>
                  set("operating_days", (toggle(form.operating_days, index) as number[]).sort())
                }
              />
              {day}
            </label>
          ))}
        </div>
        {errors.operating_days && (
          <p role="alert" className="mt-1 text-xs text-rose-700">
            {errors.operating_days}
          </p>
        )}
      </fieldset>

      <fieldset className="mb-4">
        <legend className="mb-1 text-sm font-medium text-slate-700">Supported room layouts</legend>
        <div className="flex flex-wrap gap-3 text-sm">
          {LAYOUTS.map(([value, label]) => (
            <label key={value} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={form.layouts.includes(value)}
                onChange={() => set("layouts", toggle(form.layouts, value) as string[])}
              />
              {label}
            </label>
          ))}
        </div>
        {errors.layouts && (
          <p role="alert" className="mt-1 text-xs text-rose-700">
            {errors.layouts}
          </p>
        )}
      </fieldset>

      <Field label="Wheelchair access" htmlFor="v-wheelchair">
        <select
          id="v-wheelchair"
          className={inputClass}
          value={form.wheelchair_access === null ? "" : String(form.wheelchair_access)}
          onChange={(e) =>
            set("wheelchair_access", e.target.value === "" ? null : e.target.value === "true")
          }
        >
          <option value="">Not recorded</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </Field>
      <Field
        label="Accessibility information"
        htmlFor="v-access"
        error={errors.accessibility_notes}
      >
        <textarea
          id="v-access"
          className={inputClass}
          value={form.accessibility_notes}
          onChange={(e) => set("accessibility_notes", e.target.value)}
        />
      </Field>

      <label className="mb-4 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.in_service}
          onChange={(e) => set("in_service", e.target.checked)}
        />
        In service
      </label>

      <div className="flex gap-3">
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save venue"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
