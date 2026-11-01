import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { listEventBookings, requestVenue, withdrawVenue } from "../../api/venueBookings";
import { listVenues } from "../../api/venues";
import type { EventRequest } from "../../types";
import { toLocalInput } from "../CoordinatorEventEditor";
import { Field, inputClass } from "../Field";
import { selectableLayouts, useLayouts } from "../layouts/useLayouts";

/** Statuses in which a venue can be requested; the API enforces the same rule. */
const OPEN_TO_REQUESTS = ["APPROVED", "PLANNING"];

type Refusal =
  | { kind: "fields"; detail: string; fields: Record<string, string> }
  | { kind: "reasons"; detail: string; reasons: string[] }
  | { kind: "other"; detail: string };

/** Turn the API's refusal into something the coordinator can act on. */
export function describeRefusal(error: unknown): Refusal {
  if (!(error instanceof ApiError)) return { kind: "other", detail: "We could not send the request." };
  const body = (error.body ?? {}) as Record<string, unknown>;
  if (Array.isArray(body.unmet_requirements)) {
    return {
      kind: "reasons",
      detail: error.message,
      reasons: (body.unmet_requirements as { message: string }[]).map((r) => r.message),
    };
  }
  if (Array.isArray(body.reasons)) {
    return { kind: "reasons", detail: error.message, reasons: body.reasons as string[] };
  }
  if (error.status === 400) {
    const fields = Object.fromEntries(
      Object.entries(body)
        .filter(([key]) => key !== "detail")
        .map(([key, value]) => [key, Array.isArray(value) ? String(value[0]) : String(value)]),
    );
    return { kind: "fields", detail: error.message, fields };
  }
  return { kind: "other", detail: error.message };
}

function initialForm(event: EventRequest) {
  return {
    venue: "",
    starts_at: toLocalInput(event.preferred_start),
    ends_at: toLocalInput(event.preferred_end),
    attendance: event.expected_attendance?.toString() ?? "",
    layout: event.required_layout ?? "",
    facilities: "",
    wheelchair: false,
    notes: event.accessibility_needs ?? "",
  };
}

/** SCRUM-11 - the assigned coordinator requests a venue and follows each request's status. */
export function VenuePlanner({ event }: { event: EventRequest }) {
  const queryClient = useQueryClient();
  const withdraw = useMutation({
    mutationFn: (booking: import("../../types").VenueBooking) =>
      withdrawVenue(event.id, booking, booking.status === "APPROVED"),
    onSuccess: () => { void queryClient.invalidateQueries(); },
    onError: () => { void queryClient.invalidateQueries({ queryKey: ["venue-bookings", event.id] }); },
  });
  const bookings = useQuery({
    queryKey: ["venue-bookings", event.id],
    queryFn: () => listEventBookings(event.id),
  });
  const canRequest = OPEN_TO_REQUESTS.includes(event.status);
  const venues = useQuery({ queryKey: ["venues"], queryFn: listVenues, enabled: canRequest });
  const { layouts } = useLayouts();
  const [form, setForm] = useState(() => initialForm(event));
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const set = (key: keyof typeof form, value: string | boolean) =>
    setForm((current) => ({ ...current, [key]: value }));

  const send = useMutation({
    mutationFn: () =>
      requestVenue(event.id, {
        venue: form.venue ? Number(form.venue) : null,
        starts_at: form.starts_at ? new Date(form.starts_at).toISOString() : null,
        ends_at: form.ends_at ? new Date(form.ends_at).toISOString() : null,
        attendance: form.attendance === "" ? null : Number(form.attendance),
        layout: form.layout,
        required_facilities: form.facilities
          .split(",")
          .map((f) => f.trim())
          .filter(Boolean),
        wheelchair_access_required: form.wheelchair,
        accessibility_notes: form.notes,
      }),
    onSuccess: (result) => {
      setConfirmation(result.detail);
      void queryClient.invalidateQueries({ queryKey: ["venue-bookings", event.id] });
      // The first request on an Approved event moves it to Planning.
      void queryClient.invalidateQueries({ queryKey: ["event", event.id] });
    },
  });
  const refusal = send.error ? describeRefusal(send.error) : null;
  const fieldError = (key: string) => (refusal?.kind === "fields" ? refusal.fields[key] : undefined);

  return (
    <section aria-label="Venue requests" className="mt-6 rounded-lg border border-slate-200 bg-white p-6">
      <h2 className="mb-3 text-sm font-semibold text-navy-700">Venue requests</h2>
      {withdraw.isError && <p role="alert">{withdraw.error.message}</p>}
      {withdraw.isSuccess && <p role="status">Booking withdrawn. Venue Staff have been notified.</p>}

      {bookings.isError && <p role="alert">We could not load this event's venue requests.</p>}
      {(bookings.data ?? []).length === 0 && !bookings.isLoading && !bookings.isError && (
        <p className="mb-4 text-sm text-slate-500">No venue has been requested yet.</p>
      )}
      {(bookings.data ?? []).length > 0 && (
        <table className="mb-4 w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="py-2">Venue</th>
              <th className="py-2">When</th>
              <th className="py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {bookings.data!.map((b) => (
              <tr key={b.id}>
                <td className="py-2 font-medium text-navy-700">{b.venue_name}</td>
                <td className="py-2">
                  {new Date(b.starts_at).toLocaleString("en-SG")} –{" "}
                  {new Date(b.ends_at).toLocaleTimeString("en-SG")}
                </td>
                <td className="py-2">
                  {/* AC5 - the request's current status. */}
                  <span className="font-medium">{b.status_label}</span>
                  {b.withdrawn_at && <span className="block text-xs">
                    Withdrawn by {b.withdrawn_by_name ?? "Deleted user"} on {new Date(b.withdrawn_at).toLocaleString("en-SG")}
                  </span>}
                  {["PENDING", "APPROVED"].includes(b.status) &&
                    ["APPROVED", "PLANNING", "CONFIRMED", "UNDER_REVIEW"].includes(event.status) && (
                    <button type="button" disabled={withdraw.isPending} className="ml-3 underline"
                      aria-label={`Withdraw ${b.venue_name}`}
                      onClick={() => {
                        if (b.status === "APPROVED" && !window.confirm(
                          "This will release a confirmed venue arrangement and require a new Safety review. Withdraw this booking?",
                        )) return;
                        withdraw.mutate(b);
                      }}>Withdraw</button>
                  )}
                  {b.decided_by_name && (
                    <span className="block text-xs text-slate-500">by {b.decided_by_name}</span>
                  )}
                  {b.decision_reason && (
                    <span className="block text-xs text-slate-500">{b.decision_reason}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!canRequest ? (
        <p className="text-sm text-slate-500">
          A venue can be requested once this event has been approved.
        </p>
      ) : (
        <form
          aria-label="Request a venue"
          onSubmit={(e) => {
            e.preventDefault();
            setConfirmation(null);
            send.mutate();
          }}
        >
          {confirmation && (
            <p role="status" className="mb-4 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
              {confirmation}
            </p>
          )}
          {refusal && refusal.kind !== "fields" && (
            <div role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
              <p className="font-medium">{refusal.detail}</p>
              {refusal.kind === "reasons" && (
                <ul className="mt-1 list-inside list-disc">
                  {refusal.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <div className="grid gap-x-6 sm:grid-cols-2">
            <Field label="Venue" htmlFor="request-venue" error={fieldError("venue")}>
              <select
                id="request-venue"
                className={inputClass}
                value={form.venue}
                onChange={(e) => set("venue", e.target.value)}
              >
                <option value="">Choose a venue</option>
                {(venues.data ?? []).map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} (capacity {v.capacity})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Attendance" htmlFor="request-attendance" error={fieldError("attendance")}>
              <input
                id="request-attendance"
                type="number"
                className={inputClass}
                value={form.attendance}
                onChange={(e) => set("attendance", e.target.value)}
              />
            </Field>
            <Field label="Starts" htmlFor="request-start" error={fieldError("starts_at")}>
              <input
                id="request-start"
                type="datetime-local"
                className={inputClass}
                value={form.starts_at}
                onChange={(e) => set("starts_at", e.target.value)}
              />
            </Field>
            <Field label="Ends" htmlFor="request-end" error={fieldError("ends_at")}>
              <input
                id="request-end"
                type="datetime-local"
                className={inputClass}
                value={form.ends_at}
                onChange={(e) => set("ends_at", e.target.value)}
              />
            </Field>
            <Field label="Room layout" htmlFor="request-layout" error={fieldError("layout")}>
              <select
                id="request-layout"
                className={inputClass}
                value={form.layout}
                onChange={(e) => set("layout", e.target.value)}
              >
                <option value="">No preference</option>
                {selectableLayouts(layouts, [form.layout]).map((layout) => (
                  <option key={layout.code} value={layout.code}>
                    {layout.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Required facilities"
              htmlFor="request-facilities"
              hint="Separate with commas"
              error={fieldError("required_facilities")}
            >
              <input
                id="request-facilities"
                className={inputClass}
                value={form.facilities}
                onChange={(e) => set("facilities", e.target.value)}
              />
            </Field>
          </div>
          <label className="mb-4 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.wheelchair}
              onChange={(e) => set("wheelchair", e.target.checked)}
            />
            Wheelchair access required
          </label>
          <Field label="Accessibility needs" htmlFor="request-notes">
            <textarea
              id="request-notes"
              className={inputClass}
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
            />
          </Field>
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={send.isPending}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
            >
              Send request to Venue Staff
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
