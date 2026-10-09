import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import { createVenue, listVenues } from "../../api/venues";
import type { AffectedBooking, Venue, VenueInput, VenueLayout } from "../../api/venues";
import { Field, inputClass } from "../../components/Field";

export const LAYOUTS: { value: VenueLayout; label: string }[] = [
  { value: "CLASSROOM", label: "Classroom" },
  { value: "THEATRE", label: "Theatre" },
  { value: "BOARDROOM", label: "Boardroom" },
  { value: "BANQUET", label: "Banquet" },
  { value: "EXHIBITION", label: "Exhibition" },
];

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("en-SG") : "—";
}

/** A datetime-local input value (local time) for an ISO timestamp. */
export function toLocalInput(value: string | Date | null) {
  if (!value) return "";
  const date = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** An ISO timestamp (with timezone) for a datetime-local input value, or null. */
export function fromLocalInput(value: string) {
  return value ? new Date(value).toISOString() : null;
}

export function VenueNav() {
  return (
    <nav className="mb-4 flex gap-4 text-sm">
      <Link to="/venues" className="text-navy-700 underline">
        Venues
      </Link>
      <Link to="/venues/bookings" className="text-navy-700 underline">
        Booking requests
      </Link>
    </nav>
  );
}

const EMPTY: VenueInput = {
  name: "",
  location: "",
  capacity: null,
  facilities: [],
  layouts: [],
  wheelchair_access: null,
  accessibility_notes: "",
  opens_at: null,
  closes_at: null,
  operating_days: [0, 1, 2, 3, 4, 5, 6],
  is_active: true,
};

function toInput(venue: Venue): VenueInput {
  return {
    name: venue.name,
    location: venue.location,
    capacity: venue.capacity,
    facilities: venue.facilities,
    layouts: venue.layouts,
    wheelchair_access: venue.wheelchair_access,
    accessibility_notes: venue.accessibility_notes,
    opens_at: venue.opens_at?.slice(0, 5) ?? null,
    closes_at: venue.closes_at?.slice(0, 5) ?? null,
    operating_days: venue.operating_days,
    is_active: venue.is_active,
  };
}

/** SCRUM-65 / SCRUM-5 - add or edit a venue; there is deliberately no delete. */
export function VenueForm({
  venue,
  save,
  onSaved,
  onCancel,
  submitLabel,
}: {
  venue?: Venue;
  save: (input: VenueInput, confirmLayoutRemoval: boolean) => Promise<Venue>;
  onSaved: (venue: Venue) => void;
  onCancel?: () => void;
  submitLabel: string;
}) {
  const [form, setForm] = useState<VenueInput>(venue ? toInput(venue) : EMPTY);
  const [facilities, setFacilities] = useState(form.facilities.join(", "));
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<string | null>(null);
  const [affected, setAffected] = useState<AffectedBooking[]>([]);

  function set<K extends keyof VenueInput>(key: K, value: VenueInput[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function toggle<T>(list: T[], value: T) {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  const mutation = useMutation({
    mutationFn: (confirm: boolean) => {
      setFieldErrors({});
      setBanner(null);
      const facilityList = facilities
        .split(",")
        .map((f) => f.trim())
        .filter(Boolean);
      return save({ ...form, facilities: facilityList }, confirm);
    },
    onSuccess: (saved) => {
      setAffected([]);
      onSaved(saved);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        // SCRUM-5 AC4 - confirmed bookings rely on a layout being removed.
        const body = error.body as { affected_bookings?: AffectedBooking[] } | null;
        setAffected(body?.affected_bookings ?? []);
        setBanner(error.message);
        return;
      }
      if (error instanceof ApiError && error.status === 400 && error.body) {
        const next: Record<string, string> = {};
        for (const [key, value] of Object.entries(error.body as Record<string, unknown>)) {
          next[key] = Array.isArray(value) ? String(value[0]) : String(value);
        }
        setFieldErrors(next);
        setBanner(next.detail ?? next.non_field_errors ?? null);
        return;
      }
      setBanner(error instanceof ApiError ? error.message : "We could not save this venue.");
    },
  });

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate(false);
      }}
      className="rounded-lg border border-slate-200 bg-white p-6"
    >
      {banner && (
        <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {banner}
        </p>
      )}
      {affected.length > 0 && (
        <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-medium">These confirmed bookings will be flagged for review:</p>
          <ul className="mt-1 list-inside list-disc">
            {affected.map((b) => (
              <li key={b.id}>
                {b.event_name} · {b.layout} · {formatDateTime(b.start)}
              </li>
            ))}
          </ul>
          <div className="mt-3 flex gap-3">
            <button
              type="button"
              onClick={() => mutation.mutate(true)}
              disabled={mutation.isPending}
              className="rounded-md bg-rose-700 px-4 py-2 text-sm font-medium text-white hover:bg-rose-800 disabled:opacity-50"
            >
              Remove layout anyway
            </button>
            <button
              type="button"
              onClick={() => {
                setAffected([]);
                setBanner(null);
              }}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
            >
              Keep layout
            </button>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="venue-name" error={fieldErrors.name}>
          <input
            id="venue-name"
            className={inputClass}
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </Field>
        <Field label="Location" htmlFor="venue-location" error={fieldErrors.location}>
          <input
            id="venue-location"
            className={inputClass}
            value={form.location}
            onChange={(e) => set("location", e.target.value)}
          />
        </Field>
        <Field label="Capacity" htmlFor="venue-capacity" error={fieldErrors.capacity}>
          <input
            id="venue-capacity"
            type="number"
            className={inputClass}
            value={form.capacity ?? ""}
            onChange={(e) => set("capacity", e.target.value === "" ? null : Number(e.target.value))}
          />
        </Field>
        <Field
          label="Facilities"
          htmlFor="venue-facilities"
          hint="Separate with commas, e.g. Projector, PA system"
          error={fieldErrors.facilities}
        >
          <input
            id="venue-facilities"
            className={inputClass}
            value={facilities}
            onChange={(e) => setFacilities(e.target.value)}
          />
        </Field>
      </div>

      <fieldset className="mb-4">
        <legend className="mb-2 text-sm font-medium text-slate-700">Supported layouts</legend>
        <div className="flex flex-wrap gap-4">
          {LAYOUTS.map((l) => (
            <label key={l.value} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.layouts.includes(l.value)}
                onChange={() => set("layouts", toggle(form.layouts, l.value))}
              />
              {l.label}
            </label>
          ))}
        </div>
        {fieldErrors.layouts && (
          <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
            {fieldErrors.layouts}
          </p>
        )}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Wheelchair access" htmlFor="venue-wheelchair">
          <select
            id="venue-wheelchair"
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
        <Field label="Accessibility notes" htmlFor="venue-accessibility">
          <input
            id="venue-accessibility"
            className={inputClass}
            value={form.accessibility_notes}
            onChange={(e) => set("accessibility_notes", e.target.value)}
          />
        </Field>
        <Field label="Opens at" htmlFor="venue-opens" error={fieldErrors.opens_at}>
          <input
            id="venue-opens"
            type="time"
            className={inputClass}
            value={form.opens_at ?? ""}
            onChange={(e) => set("opens_at", e.target.value || null)}
          />
        </Field>
        <Field label="Closes at" htmlFor="venue-closes" error={fieldErrors.closes_at}>
          <input
            id="venue-closes"
            type="time"
            className={inputClass}
            value={form.closes_at ?? ""}
            onChange={(e) => set("closes_at", e.target.value || null)}
          />
        </Field>
      </div>

      <fieldset className="mb-4">
        <legend className="mb-2 text-sm font-medium text-slate-700">Operating days</legend>
        <div className="flex flex-wrap gap-4">
          {DAYS.map((day, index) => (
            <label key={day} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.operating_days.includes(index)}
                onChange={() => set("operating_days", toggle(form.operating_days, index))}
              />
              {day}
            </label>
          ))}
        </div>
        {fieldErrors.operating_days && (
          <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
            {fieldErrors.operating_days}
          </p>
        )}
      </fieldset>

      <label className="mb-4 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.is_active}
          onChange={(e) => set("is_active", e.target.checked)}
        />
        In service
      </label>

      <div className="flex justify-end gap-3">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
          >
            Cancel
          </button>
        )}
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
        >
          {submitLabel}
        </button>
      </div>
    </form>
  );
}

function accessibility(venue: Venue) {
  const access =
    venue.wheelchair_access === null
      ? null
      : venue.wheelchair_access
        ? "Wheelchair accessible"
        : "No wheelchair access";
  return [access, venue.accessibility_notes].filter(Boolean).join(" · ") || "—";
}

export function VenueCatalogue() {
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const { data: venues, isLoading, isError } = useQuery({
    queryKey: ["venues"],
    queryFn: listVenues,
  });

  return (
    <div>
      <VenueNav />
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-navy-700">Venues</h1>
        {!showAdd && (
          <button
            type="button"
            onClick={() => setShowAdd(true)}
            className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600"
          >
            Add venue
          </button>
        )}
      </div>

      {showAdd && (
        <section aria-label="Add venue" className="mb-6">
          <VenueForm
            submitLabel="Save venue"
            save={(input) => createVenue(input)}
            onSaved={() => {
              setShowAdd(false);
              void queryClient.invalidateQueries({ queryKey: ["venues"] });
            }}
            onCancel={() => setShowAdd(false)}
          />
        </section>
      )}

      {isLoading && <p className="text-slate-500">Loading venues…</p>}
      {isError && <p role="alert">We could not load the venues.</p>}
      {venues && venues.length === 0 && <p className="text-slate-500">No venues yet.</p>}

      <ul className="space-y-4">
        {venues?.map((venue) => (
          <li key={venue.id} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <Link
                to={`/venues/${venue.id}`}
                className="text-lg font-semibold text-navy-700 underline"
              >
                {venue.name}
              </Link>
              <span className="text-sm text-slate-600">{venue.operational_status}</span>
            </div>
            <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm text-slate-800 sm:grid-cols-2">
              <div>
                <dt className="inline text-slate-500">Location: </dt>
                <dd className="inline">{venue.location || "—"}</dd>
              </div>
              <div>
                <dt className="inline text-slate-500">Capacity: </dt>
                <dd className="inline">{venue.capacity}</dd>
              </div>
              <div>
                <dt className="inline text-slate-500">Layouts: </dt>
                <dd className="inline">{venue.layout_labels.join(", ") || "—"}</dd>
              </div>
              <div>
                <dt className="inline text-slate-500">Facilities: </dt>
                <dd className="inline">{venue.facilities.join(", ") || "—"}</dd>
              </div>
              <div>
                <dt className="inline text-slate-500">Accessibility: </dt>
                <dd className="inline">{accessibility(venue)}</dd>
              </div>
              <div>
                <dt className="inline text-slate-500">Hours: </dt>
                <dd className="inline">{venue.operating_hours ?? "—"}</dd>
              </div>
            </dl>
            {venue.missing_information.length > 0 && (
              <p className="mt-2 text-sm text-amber-800">
                Missing information: {venue.missing_information.join(", ")}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
