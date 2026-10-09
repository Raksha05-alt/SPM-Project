import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import {
  approveBooking,
  listBookings,
  listVenues,
  rejectBooking,
  reviewBooking,
} from "../../api/venues";
import type { BookingConflict, RejectInput, VenueBooking } from "../../api/venues";
import { Field, inputClass } from "../../components/Field";
import { VenueNav, formatDateTime, fromLocalInput } from "./VenueCatalogue";

const secondaryButton =
  "rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50";
const primaryButton =
  "rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50";

function conflictsOf(error: unknown): BookingConflict[] {
  if (!(error instanceof ApiError)) return [];
  return (error.body as { conflicts?: BookingConflict[] } | null)?.conflicts ?? [];
}

function ConflictList({ conflicts }: { conflicts: BookingConflict[] }) {
  return (
    <ul className="mt-1 list-inside list-disc">
      {conflicts.map((c) => (
        <li key={c.booking}>
          {c.event_name} · {formatDateTime(c.start)} – {formatDateTime(c.end)}
        </li>
      ))}
    </ul>
  );
}

function BookingSummary({ booking }: { booking: VenueBooking }) {
  return (
    <>
      <h3 className="text-base font-semibold text-navy-700">{booking.event_name}</h3>
      <p className="text-sm text-slate-600">
        {booking.venue_name} · {formatDateTime(booking.start)} – {formatDateTime(booking.end)}
      </p>
      <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm text-slate-800 sm:grid-cols-2">
        <div>
          <dt className="inline text-slate-500">Attendance: </dt>
          <dd className="inline">{booking.attendance}</dd>
        </div>
        <div>
          <dt className="inline text-slate-500">Layout: </dt>
          <dd className="inline">{booking.layout_label || "No preference"}</dd>
        </div>
        <div>
          <dt className="inline text-slate-500">Facilities: </dt>
          <dd className="inline">{booking.facilities.join(", ") || "—"}</dd>
        </div>
        <div>
          <dt className="inline text-slate-500">Accessibility: </dt>
          <dd className="inline">{booking.accessibility_needs || "—"}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="inline text-slate-500">Notes: </dt>
          <dd className="inline">{booking.notes || "—"}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="inline text-slate-500">Requested by: </dt>
          <dd className="inline">{booking.requested_by_name ?? "—"}</dd>
        </div>
      </dl>
    </>
  );
}

/** SCRUM-72 AC3 / SCRUM-73 - reject with a reason, optionally suggesting an alternative. */
function RejectForm({
  booking,
  onDecided,
  onCancel,
}: {
  booking: VenueBooking;
  onDecided: (booking: VenueBooking) => void;
  onCancel: () => void;
}) {
  const prefix = `reject-${booking.id}`;
  const [reason, setReason] = useState("");
  const [venue, setVenue] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [note, setNote] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  const { data: venues } = useQuery({ queryKey: ["venues"], queryFn: listVenues });

  const reject = useMutation({
    mutationFn: (acknowledge: boolean) => {
      const input: RejectInput = {
        reason: reason.trim(),
        suggested_venue: venue ? Number(venue) : null,
        suggested_start: fromLocalInput(start),
        suggested_end: fromLocalInput(end),
        suggestion_note: note.trim(),
      };
      if (acknowledge) input.acknowledge_warning = true;
      return rejectBooking(booking.id, input);
    },
    onSuccess: onDecided,
    onError: (error) => {
      // SCRUM-73 AC4 - the suggested venue is taken; staff may send it anyway.
      const body = error instanceof ApiError ? (error.body as { warning?: boolean } | null) : null;
      setWarning(body?.warning ? error.message : null);
    },
  });

  function confirm() {
    // SCRUM-72 AC3 - the API also refuses a rejection without a reason.
    if (!reason.trim()) {
      setReasonError("Enter a reason for the rejection.");
      return;
    }
    setReasonError(null);
    reject.mutate(false);
  }

  const refusal = reject.error && !warning ? reject.error.message : null;

  return (
    <section
      aria-label="Reject booking request"
      className="mt-4 rounded-lg border border-rose-200 bg-white p-4"
    >
      <Field label="Reason for rejection" htmlFor={`${prefix}-reason`} error={reasonError ?? undefined}>
        <textarea
          id={`${prefix}-reason`}
          rows={2}
          className={inputClass}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Suggested venue (optional)" htmlFor={`${prefix}-venue`}>
          <select
            id={`${prefix}-venue`}
            className={inputClass}
            value={venue}
            onChange={(e) => setVenue(e.target.value)}
          >
            <option value="">No venue suggestion</option>
            {venues?.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Suggested start (optional)" htmlFor={`${prefix}-start`}>
          <input
            id={`${prefix}-start`}
            type="datetime-local"
            className={inputClass}
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </Field>
        <Field label="Suggested end (optional)" htmlFor={`${prefix}-end`}>
          <input
            id={`${prefix}-end`}
            type="datetime-local"
            className={inputClass}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </Field>
      </div>
      <Field label="Suggestion note (optional)" htmlFor={`${prefix}-note`}>
        <input
          id={`${prefix}-note`}
          className={inputClass}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </Field>
      {refusal && (
        <p role="alert" className="mb-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {refusal}
        </p>
      )}
      {warning && (
        <div role="alert" className="mb-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          <p>{warning}</p>
          <button
            type="button"
            onClick={() => reject.mutate(true)}
            disabled={reject.isPending}
            className="mt-2 rounded-md bg-rose-700 px-4 py-2 text-sm font-medium text-white hover:bg-rose-800 disabled:opacity-50"
          >
            Send anyway
          </button>
        </div>
      )}
      <div className="flex justify-end gap-3">
        <button type="button" onClick={onCancel} className={secondaryButton}>
          Cancel
        </button>
        <button
          type="button"
          onClick={confirm}
          disabled={reject.isPending}
          className="rounded-md bg-rose-700 px-4 py-2 text-sm font-medium text-white hover:bg-rose-800 disabled:opacity-50"
        >
          Confirm rejection
        </button>
      </div>
    </section>
  );
}

function PendingRequest({ booking }: { booking: VenueBooking }) {
  const [decided, setDecided] = useState<VenueBooking | null>(null);
  const [showReject, setShowReject] = useState(false);

  function onDecided(updated: VenueBooking) {
    setDecided(updated);
    setShowReject(false);
  }

  const approve = useMutation({ mutationFn: approveBooking, onSuccess: onDecided });
  const refusedConflicts = conflictsOf(approve.error);

  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <BookingSummary booking={booking} />

      {/* SCRUM-69 - conflicting confirmed bookings, named by event. */}
      {!decided && booking.conflicts.length > 0 && (
        <div className="mt-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          <p className="font-medium">Conflicts with confirmed bookings:</p>
          <ConflictList conflicts={booking.conflicts} />
        </div>
      )}

      {approve.error && (
        <div role="alert" className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          <p>{approve.error.message}</p>
          {refusedConflicts.length > 0 && <ConflictList conflicts={refusedConflicts} />}
        </div>
      )}

      {decided ? (
        <p role="status" className="mt-3 text-sm text-slate-700">
          {decided.status_display} by {decided.decided_by_name ?? "—"} on{" "}
          {formatDateTime(decided.decided_at)}
          {decided.rejection_reason && `. Reason: ${decided.rejection_reason}`}
          {decided.suggested_venue_name && `. Suggested: ${decided.suggested_venue_name}`}
        </p>
      ) : showReject ? (
        <RejectForm booking={booking} onDecided={onDecided} onCancel={() => setShowReject(false)} />
      ) : (
        <div className="mt-3 flex justify-end gap-3">
          <button
            type="button"
            onClick={() => setShowReject(true)}
            className="rounded-md border border-rose-300 bg-white px-4 py-2 text-sm font-medium text-rose-800 hover:bg-rose-50"
          >
            Reject
          </button>
          <button
            type="button"
            onClick={() => approve.mutate(booking.id)}
            disabled={approve.isPending}
            className={primaryButton}
          >
            Approve
          </button>
        </div>
      )}
    </li>
  );
}

/** SCRUM-80 - a confirmed booking flagged because the event or venue changed. */
function ReviewItem({ booking }: { booking: VenueBooking }) {
  const prefix = `review-${booking.id}`;
  const [note, setNote] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);
  const [done, setDone] = useState<VenueBooking | null>(null);

  const review = useMutation({
    mutationFn: (accommodated: boolean) =>
      reviewBooking(booking.id, {
        accommodated,
        note: note.trim(),
        start: accommodated ? fromLocalInput(start) : null,
        end: accommodated ? fromLocalInput(end) : null,
      }),
    onSuccess: setDone,
  });

  function cannotAccommodate() {
    if (!note.trim()) {
      setNoteError("Explain why the change cannot be accommodated.");
      return;
    }
    setNoteError(null);
    review.mutate(false);
  }

  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <BookingSummary booking={booking} />
      <p className="mt-2 text-sm text-slate-800">
        <span className="text-slate-500">Why: </span>
        {booking.review_reason || "—"}
      </p>
      {(booking.review_start || booking.review_end) && (
        <p className="text-sm text-slate-800">
          <span className="text-slate-500">Requested period: </span>
          {formatDateTime(booking.review_start)} – {formatDateTime(booking.review_end)}
        </p>
      )}
      {review.error && (
        <div role="alert" className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          <p>{review.error.message}</p>
          {conflictsOf(review.error).length > 0 && (
            <ConflictList conflicts={conflictsOf(review.error)} />
          )}
        </div>
      )}
      {done ? (
        <p role="status" className="mt-3 text-sm text-slate-700">
          Reviewed by {done.reviewed_by_name ?? "—"} on {formatDateTime(done.reviewed_at)}.{" "}
          {done.review_outcome}
        </p>
      ) : (
        <div className="mt-3">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Revised start (optional)" htmlFor={`${prefix}-start`}>
              <input
                id={`${prefix}-start`}
                type="datetime-local"
                className={inputClass}
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </Field>
            <Field label="Revised end (optional)" htmlFor={`${prefix}-end`}>
              <input
                id={`${prefix}-end`}
                type="datetime-local"
                className={inputClass}
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </Field>
          </div>
          <Field label="Note" htmlFor={`${prefix}-note`} error={noteError ?? undefined}>
            <textarea
              id={`${prefix}-note`}
              rows={2}
              className={inputClass}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </Field>
          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={cannotAccommodate}
              disabled={review.isPending}
              className="rounded-md border border-rose-300 bg-white px-4 py-2 text-sm font-medium text-rose-800 hover:bg-rose-50"
            >
              Cannot accommodate
            </button>
            <button
              type="button"
              onClick={() => review.mutate(true)}
              disabled={review.isPending}
              className={primaryButton}
            >
              Accommodate
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

export function VenueBookingInbox() {
  const pending = useQuery({
    queryKey: ["venue-bookings", "PENDING"],
    queryFn: () => listBookings("PENDING"),
  });
  const approved = useQuery({
    queryKey: ["venue-bookings", "APPROVED"],
    queryFn: () => listBookings("APPROVED"),
  });
  const needsReview = approved.data?.filter((b) => b.review_required) ?? [];

  return (
    <div>
      <VenueNav />
      <h1 className="mb-6 text-2xl font-semibold text-navy-700">Booking requests</h1>

      <section aria-label="Pending requests">
        <h2 className="mb-3 text-lg font-semibold text-navy-700">Pending requests</h2>
        {pending.isLoading && <p className="text-slate-500">Loading requests…</p>}
        {pending.isError && <p role="alert">We could not load the booking requests.</p>}
        {pending.data?.length === 0 && (
          <p className="text-sm text-slate-500">No requests are waiting for a decision.</p>
        )}
        <ul className="space-y-4">
          {pending.data?.map((booking) => <PendingRequest key={booking.id} booking={booking} />)}
        </ul>
      </section>

      <section aria-label="Needs review" className="mt-8">
        <h2 className="mb-3 text-lg font-semibold text-navy-700">Needs review</h2>
        {approved.isError && <p role="alert">We could not load bookings needing review.</p>}
        {approved.data && needsReview.length === 0 && (
          <p className="text-sm text-slate-500">No confirmed bookings need review.</p>
        )}
        <ul className="space-y-4">
          {needsReview.map((booking) => (
            <ReviewItem key={booking.id} booking={booking} />
          ))}
        </ul>
      </section>
    </div>
  );
}
