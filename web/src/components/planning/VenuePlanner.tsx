import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import {
  LAYOUT_OPTIONS,
  acceptSuggestion,
  addToShortlist,
  compareAvailability,
  fetchBookings,
  fetchShortlist,
  fetchSuitability,
  fieldErrorsOf,
  formatDateTime,
  fromLocalInput,
  removeFromShortlist,
  requestBooking,
  searchVenues,
  toLocalInput,
  withdrawBooking,
  type Suitability,
  type VenueBooking,
  type VenueSearchParams,
} from "../../api/planning";
import type { EventRequest } from "../../types";
import { Field, inputClass } from "../Field";

const secondary =
  "rounded-md border border-slate-300 bg-white px-3 py-1 text-sm font-medium hover:bg-slate-50 disabled:opacity-50";
const primary =
  "rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50";
const card = "mt-6 rounded-lg border border-slate-200 bg-white p-6";

function period(start: string | null, end: string | null) {
  return `${formatDateTime(start)} – ${formatDateTime(end)}`;
}

function ErrorBox({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="mb-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
      {error.message}
    </p>
  );
}

/** SCRUM-64 / 71 / 62 / 68 venues, and SCRUM-11 / 67 / 73 / 69 bookings for one event. */
export function VenuePlanner({ event }: { event: EventRequest }) {
  const [bookingVenue, setBookingVenue] = useState<{ id: number; name: string } | null>(null);

  return (
    <div>
      <VenueSearch event={event} onRequest={setBookingVenue} />
      <AvailabilityComparison event={event} />
      <Shortlist event={event} onRequest={setBookingVenue} />
      {bookingVenue && (
        <BookingForm event={event} venue={bookingVenue} onClose={() => setBookingVenue(null)} />
      )}
      <Bookings event={event} />
    </div>
  );
}

type RequestVenue = (venue: { id: number; name: string }) => void;

function VenueSearch({ event, onRequest }: { event: EventRequest; onRequest: RequestVenue }) {
  const queryClient = useQueryClient();
  const [criteria, setCriteria] = useState({
    attendance: event.expected_attendance?.toString() ?? "",
    layout: event.required_layout,
    facilities: "",
    location: "",
    wheelchair_access: Boolean(event.accessibility_needs.trim()),
  });
  const [checked, setChecked] = useState<Record<number, Suitability>>({});

  const search = useMutation({
    mutationFn: (params: VenueSearchParams) => searchVenues(params),
  });
  const suitability = useMutation({
    mutationFn: (venueId: number) => fetchSuitability(venueId, event.id),
    onSuccess: (result) => setChecked((c) => ({ ...c, [result.venue]: result })),
  });
  const shortlist = useMutation({
    mutationFn: (venueId: number) => addToShortlist(event.id, venueId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["shortlist", event.id] }),
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    search.mutate({
      attendance: criteria.attendance ? Number(criteria.attendance) : null,
      layout: criteria.layout,
      facilities: criteria.facilities,
      location: criteria.location,
      wheelchair_access: criteria.wheelchair_access,
      start: event.preferred_start,
      end: event.preferred_end,
    });
  }

  const fieldErrors = search.error instanceof ApiError ? fieldErrorsOf(search.error.body) : {};

  return (
    <section aria-label="Find a venue" className={card}>
      <h2 className="mb-3 text-sm font-semibold text-navy-700">Find a venue</h2>
      <form onSubmit={submit} noValidate>
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label="Attendance" htmlFor="search-attendance" error={fieldErrors.attendance}>
            <input
              id="search-attendance"
              type="number"
              min={1}
              className={inputClass}
              value={criteria.attendance}
              onChange={(e) => setCriteria({ ...criteria, attendance: e.target.value })}
            />
          </Field>
          <Field label="Layout" htmlFor="search-layout" error={fieldErrors.layout}>
            <select
              id="search-layout"
              className={inputClass}
              value={criteria.layout}
              onChange={(e) => setCriteria({ ...criteria, layout: e.target.value })}
            >
              <option value="">Any layout</option>
              {LAYOUT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Facilities" htmlFor="search-facilities" hint="Separate with commas.">
            <input
              id="search-facilities"
              className={inputClass}
              value={criteria.facilities}
              onChange={(e) => setCriteria({ ...criteria, facilities: e.target.value })}
            />
          </Field>
          <Field label="Location" htmlFor="search-location">
            <input
              id="search-location"
              className={inputClass}
              value={criteria.location}
              onChange={(e) => setCriteria({ ...criteria, location: e.target.value })}
            />
          </Field>
        </div>
        <label className="mb-4 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={criteria.wheelchair_access}
            onChange={(e) => setCriteria({ ...criteria, wheelchair_access: e.target.checked })}
          />
          Wheelchair access
        </label>
        <p className="mb-4 text-xs text-slate-500">
          Checked against the event period: {period(event.preferred_start, event.preferred_end)}
        </p>
        <button type="submit" disabled={search.isPending} className={primary}>
          Search venues
        </button>
      </form>

      <div className="mt-4">
        {search.error && Object.keys(fieldErrors).length === 0 && (
          <ErrorBox error={search.error} />
        )}
        <ErrorBox error={suitability.error ?? shortlist.error} />
        {search.data?.message && <p className="text-sm text-slate-500">{search.data.message}</p>}
        <ul className="divide-y divide-slate-200 text-sm">
          {search.data?.results.map((venue) => {
            const result = checked[venue.id];
            return (
              <li key={venue.id} className="py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-medium">{venue.name}</p>
                    <p className="text-xs text-slate-500">
                      {venue.location} · capacity {venue.capacity}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className={secondary}
                      onClick={() => suitability.mutate(venue.id)}
                      aria-label={`Check suitability of ${venue.name}`}
                    >
                      Check suitability
                    </button>
                    <button
                      type="button"
                      className={secondary}
                      onClick={() => shortlist.mutate(venue.id)}
                      aria-label={`Shortlist ${venue.name}`}
                    >
                      Shortlist
                    </button>
                    <button
                      type="button"
                      className={secondary}
                      onClick={() => onRequest({ id: venue.id, name: venue.name })}
                      aria-label={`Request ${venue.name}`}
                    >
                      Request booking
                    </button>
                  </div>
                </div>
                {result && (
                  <div className="mt-2 text-xs">
                    {result.suitable ? (
                      <p className="text-emerald-800">Suitable for this event.</p>
                    ) : (
                      <ul className="list-disc pl-5 text-rose-800">
                        {result.warnings.map((w) => (
                          <li key={w}>{w}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

function AvailabilityComparison({ event }: { event: EventRequest }) {
  const compare = useMutation({
    mutationFn: () => compareAvailability(event.preferred_start!, event.preferred_end!),
  });
  const hasPeriod = Boolean(event.preferred_start && event.preferred_end);

  return (
    <section aria-label="Venue availability" className={card}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-navy-700">Venue availability</h2>
        <button
          type="button"
          className={secondary}
          disabled={!hasPeriod || compare.isPending}
          onClick={() => compare.mutate()}
        >
          Compare availability
        </button>
      </div>
      {!hasPeriod && (
        <p className="mt-2 text-sm text-slate-500">The event has no date and time yet.</p>
      )}
      <div className="mt-3">
        <ErrorBox error={compare.error} />
        {compare.data?.message && (
          <p className="mb-2 text-sm text-slate-500">{compare.data.message}</p>
        )}
        {compare.data && compare.data.venues.length > 0 && (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-2">Venue</th>
                <th className="py-2">Capacity</th>
                <th className="py-2">Availability</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {compare.data.venues.map((row) => (
                <tr key={row.venue}>
                  <td className="py-2">{row.venue_name}</td>
                  <td className="py-2">{row.capacity}</td>
                  <td className="py-2">
                    {row.overall_label}
                    {row.overall !== "AVAILABLE" && (
                      <ul className="text-xs text-slate-500">
                        {row.segments
                          .filter((s) => s.status !== "AVAILABLE")
                          .map((s, i) => (
                            <li key={i}>
                              {s.label}
                              {s.detail ? ` (${s.detail})` : ""}: {period(s.start, s.end)}
                            </li>
                          ))}
                      </ul>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

function Shortlist({ event, onRequest }: { event: EventRequest; onRequest: RequestVenue }) {
  const queryClient = useQueryClient();
  const { data, error } = useQuery({
    queryKey: ["shortlist", event.id],
    queryFn: () => fetchShortlist(event.id),
  });
  const remove = useMutation({
    mutationFn: (venue: number) => removeFromShortlist(event.id, venue),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["shortlist", event.id] }),
  });

  return (
    <section aria-label="Shortlist" className={card}>
      <h2 className="mb-3 text-sm font-semibold text-navy-700">Shortlisted venues</h2>
      <ErrorBox error={error ?? remove.error} />
      {data && data.length === 0 && (
        <p className="text-sm text-slate-500">No venues are shortlisted yet.</p>
      )}
      <ul className="divide-y divide-slate-200 text-sm">
        {data?.map((entry) => (
          <li key={entry.venue} className="py-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-medium">
                  {entry.venue_name}
                  {entry.no_longer_available && (
                    <span className="ml-2 rounded bg-rose-100 px-1.5 py-0.5 text-xs font-semibold text-rose-900">
                      No longer available
                    </span>
                  )}
                </p>
                <p className="text-xs text-slate-500">
                  {entry.location} · capacity {entry.capacity}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className={secondary}
                  onClick={() => onRequest({ id: entry.venue, name: entry.venue_name })}
                  aria-label={`Request ${entry.venue_name}`}
                >
                  Request booking
                </button>
                <button
                  type="button"
                  className={secondary}
                  onClick={() => remove.mutate(entry.venue)}
                  aria-label={`Remove ${entry.venue_name} from shortlist`}
                >
                  Remove
                </button>
              </div>
            </div>
            <p className="mt-1 text-xs text-emerald-800">
              Satisfied: {entry.satisfied.length ? entry.satisfied.join(", ") : "none"}
            </p>
            {entry.not_satisfied.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs text-rose-800">
                {entry.not_satisfied.map((n) => (
                  <li key={n.criterion}>
                    Not satisfied – {n.criterion}
                    {n.reason ? `: ${n.reason}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function BookingForm({
  event,
  venue,
  onClose,
}: {
  event: EventRequest;
  venue: { id: number; name: string };
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    start: toLocalInput(event.preferred_start),
    end: toLocalInput(event.preferred_end),
    attendance: event.expected_attendance?.toString() ?? "",
    layout: event.required_layout,
    facilities: "",
    accessibility_needs: event.accessibility_needs,
    notes: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const submitBooking = useMutation({
    mutationFn: () =>
      requestBooking({
        event: event.id,
        venue: venue.id,
        start: fromLocalInput(form.start) ?? "",
        end: fromLocalInput(form.end) ?? "",
        attendance: form.attendance ? Number(form.attendance) : null,
        layout: form.layout,
        facilities: form.facilities
          .split(",")
          .map((f) => f.trim())
          .filter(Boolean),
        accessibility_needs: form.accessibility_needs,
        notes: form.notes,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["bookings", event.id] });
      void queryClient.invalidateQueries({ queryKey: ["event", event.id] });
      onClose();
    },
    onError: (error) => {
      if (error instanceof ApiError) setErrors(fieldErrorsOf(error.body));
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const found: Record<string, string> = {};
    if (!form.start) found.start = "Enter the date and start time.";
    if (!form.end) found.end = "Enter the date and end time.";
    if (form.start && form.end && new Date(form.end) <= new Date(form.start))
      found.end = "The end must be after the start.";
    if (!form.attendance) found.attendance = "Enter the expected attendance.";
    else if (Number(form.attendance) < 1) found.attendance = "Attendance must be at least one person.";
    setErrors(found);
    if (Object.keys(found).length === 0) submitBooking.mutate();
  }

  const unmet =
    submitBooking.error instanceof ApiError
      ? ((submitBooking.error.body as { unmet?: string[] } | null)?.unmet ?? [])
      : [];
  const set = (key: keyof typeof form, value: string) => setForm({ ...form, [key]: value });

  return (
    <section aria-label="Request a booking" className={card}>
      <h2 className="mb-3 text-sm font-semibold text-navy-700">Request {venue.name}</h2>
      {submitBooking.error && Object.keys(errors).length === 0 && (
        <div role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          <p>{submitBooking.error.message}</p>
          {unmet.length > 0 && (
            <ul className="mt-2 list-disc pl-5">
              {unmet.map((u) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <form onSubmit={submit} noValidate>
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label="Booking start" htmlFor="booking-start" error={errors.start}>
            <input
              id="booking-start"
              type="datetime-local"
              className={inputClass}
              value={form.start}
              onChange={(e) => set("start", e.target.value)}
            />
          </Field>
          <Field label="Booking end" htmlFor="booking-end" error={errors.end}>
            <input
              id="booking-end"
              type="datetime-local"
              className={inputClass}
              value={form.end}
              onChange={(e) => set("end", e.target.value)}
            />
          </Field>
          <Field label="Attendance" htmlFor="booking-attendance" error={errors.attendance}>
            <input
              id="booking-attendance"
              type="number"
              min={1}
              className={inputClass}
              value={form.attendance}
              onChange={(e) => set("attendance", e.target.value)}
            />
          </Field>
          <Field label="Layout" htmlFor="booking-layout" error={errors.layout}>
            <select
              id="booking-layout"
              className={inputClass}
              value={form.layout}
              onChange={(e) => set("layout", e.target.value)}
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
          label="Facilities needed"
          htmlFor="booking-facilities"
          hint="Separate with commas."
          error={errors.facilities}
        >
          <input
            id="booking-facilities"
            className={inputClass}
            value={form.facilities}
            onChange={(e) => set("facilities", e.target.value)}
          />
        </Field>
        <Field
          label="Accessibility needs"
          htmlFor="booking-accessibility"
          error={errors.accessibility_needs}
        >
          <textarea
            id="booking-accessibility"
            rows={2}
            className={inputClass}
            value={form.accessibility_needs}
            onChange={(e) => set("accessibility_needs", e.target.value)}
          />
        </Field>
        <Field label="Notes for Venue Staff" htmlFor="booking-notes" error={errors.notes}>
          <textarea
            id="booking-notes"
            rows={2}
            className={inputClass}
            value={form.notes}
            onChange={(e) => set("notes", e.target.value)}
          />
        </Field>
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className={secondary}>
            Discard
          </button>
          <button type="submit" disabled={submitBooking.isPending} className={primary}>
            Send booking request
          </button>
        </div>
      </form>
    </section>
  );
}

function Bookings({ event }: { event: EventRequest }) {
  const queryClient = useQueryClient();
  const { data, error } = useQuery({
    queryKey: ["bookings", event.id],
    queryFn: () => fetchBookings(event.id),
  });
  const [warning, setWarning] = useState<{ id: number; message: string } | null>(null);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["bookings", event.id] });
    void queryClient.invalidateQueries({ queryKey: ["event", event.id] });
  }

  const withdraw = useMutation({
    mutationFn: ({ id, confirm }: { id: number; confirm: boolean }) =>
      withdrawBooking(id, confirm),
    onSuccess: () => {
      setWarning(null);
      refresh();
    },
    onError: (err, { id }) => {
      // SCRUM-67 - withdrawing an approved booking needs a second, explicit step.
      if (err instanceof ApiError && (err.body as { warning?: boolean } | null)?.warning) {
        setWarning({ id, message: err.message });
      }
    },
  });
  const accept = useMutation({ mutationFn: (id: number) => acceptSuggestion(id), onSuccess: refresh });

  const actionError =
    withdraw.error && !warning ? withdraw.error : (accept.error ?? null);

  return (
    <section aria-label="Venue bookings" className={card}>
      <h2 className="mb-3 text-sm font-semibold text-navy-700">Venue bookings</h2>
      <ErrorBox error={error ?? actionError} />
      {data && data.length === 0 && (
        <p className="text-sm text-slate-500">No venue has been requested yet.</p>
      )}
      <ul className="divide-y divide-slate-200 text-sm">
        {data?.map((b) => (
          <BookingRow
            key={b.id}
            booking={b}
            warning={warning?.id === b.id ? warning.message : null}
            onWithdraw={(confirm) => withdraw.mutate({ id: b.id, confirm })}
            onKeep={() => {
              setWarning(null);
              withdraw.reset();
            }}
            onAccept={() => accept.mutate(b.id)}
            busy={withdraw.isPending || accept.isPending}
          />
        ))}
      </ul>
    </section>
  );
}

function BookingRow({
  booking: b,
  warning,
  onWithdraw,
  onKeep,
  onAccept,
  busy,
}: {
  booking: VenueBooking;
  warning: string | null;
  onWithdraw: (confirm: boolean) => void;
  onKeep: () => void;
  onAccept: () => void;
  busy: boolean;
}) {
  const hasSuggestion = Boolean(b.suggested_venue || b.suggested_start || b.suggested_end);
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            {b.venue_name} <span className="font-normal text-slate-600">· {b.status_display}</span>
          </p>
          <p className="text-xs text-slate-500">
            {period(b.start, b.end)} · {b.attendance} people
            {b.layout_label ? ` · ${b.layout_label}` : ""}
          </p>
        </div>
        {(b.status === "PENDING" || b.status === "APPROVED") && !warning && (
          <button
            type="button"
            className={secondary}
            disabled={busy}
            onClick={() => onWithdraw(false)}
            aria-label={`Withdraw ${b.venue_name}`}
          >
            Withdraw
          </button>
        )}
      </div>

      {warning && (
        <div role="alert" className="mt-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          <p>{warning}</p>
          <div className="mt-2 flex gap-2">
            <button type="button" className={secondary} onClick={onKeep}>
              Keep booking
            </button>
            <button
              type="button"
              className="rounded-md bg-rose-700 px-3 py-1 text-sm font-medium text-white hover:bg-rose-800 disabled:opacity-50"
              disabled={busy}
              onClick={() => onWithdraw(true)}
            >
              Confirm withdrawal
            </button>
          </div>
        </div>
      )}

      {b.conflicts.length > 0 && (
        <div className="mt-2 text-xs text-rose-800">
          <p className="font-medium">Conflicts with:</p>
          <ul className="list-disc pl-5">
            {b.conflicts.map((c) => (
              <li key={c.booking}>
                {c.event_name} ({period(c.start, c.end)})
              </li>
            ))}
          </ul>
        </div>
      )}

      {b.review_required && (
        <div className="mt-2 rounded-md bg-amber-50 p-2 text-xs text-amber-900">
          <p className="font-semibold">Needs review</p>
          <p>{b.review_reason}</p>
          {b.review_start && (
            <p>Review period: {period(b.review_start, b.review_end)}</p>
          )}
        </div>
      )}

      {b.status === "REJECTED" && (
        <div className="mt-2 text-xs">
          <p className="text-rose-800">Reason: {b.rejection_reason}</p>
          {hasSuggestion && (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <p>
                Suggested: {b.suggested_venue_name ?? b.venue_name}
                {(b.suggested_start || b.suggested_end) &&
                  `, ${period(b.suggested_start ?? b.start, b.suggested_end ?? b.end)}`}
                {b.suggestion_note ? ` – ${b.suggestion_note}` : ""}
              </p>
              <button type="button" className={secondary} disabled={busy} onClick={onAccept}>
                Accept suggestion
              </button>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
