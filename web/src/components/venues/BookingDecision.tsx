import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { approveBooking, rejectBooking, updateHoldExpiry } from "../../api/venueBookings";
import { listVenues } from "../../api/venues";
import { SuggestedAlternative } from "./SuggestedAlternative";
import { formatSgt } from "../../dateTime";
import type { VenueBooking } from "../../types";

/** The server's explanation of a refused decision, with each reason it gave. */
function refusal(error: unknown): string[] {
  if (!(error instanceof ApiError)) return ["The decision could not be recorded. Try again."];
  const body = (error.body ?? {}) as {
    detail?: string;
    reason?: string[];
    suggestion?: string[];
    starts_at?: string[];
    ends_at?: string[];
    hold_until?: string[];
    status?: string | string[];
    venue?: string[];
    event?: string[];
    reasons?: string[];
    unmet_requirements?: { message: string }[];
  };
  return [
    body.detail ?? "The decision could not be recorded.",
    ...(body.reason ?? []),
    ...(body.suggestion ?? []),
    ...(body.starts_at ?? []),
    ...(body.ends_at ?? []),
    ...(body.hold_until ?? []),
    ...(Array.isArray(body.status) ? body.status : []),
    ...(body.venue ?? []),
    ...(body.event ?? []),
    ...(body.reasons ?? []),
    ...(body.unmet_requirements ?? []).map((r) => r.message),
  ];
}

function singaporeInput(value: string): string {
  return value ? new Date(Date.parse(value) + 8 * 3_600_000).toISOString().slice(0, 16) : "";
}

/** Venue Staff review a request and manage a tentative hold deadline. */
export function BookingDecision({ booking }: { booking: VenueBooking }) {
  const queryClient = useQueryClient();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [suggestedVenue, setSuggestedVenue] = useState(String(booking.venue));
  const [suggestedStart, setSuggestedStart] = useState(() => singaporeInput(booking.starts_at));
  const [suggestedEnd, setSuggestedEnd] = useState(() => singaporeInput(booking.ends_at));
  const venues = useQuery({
    queryKey: ["venues"],
    queryFn: listVenues,
    enabled: rejecting && suggesting,
  });
  const [editingHold, setEditingHold] = useState(false);
  const [deadline, setDeadline] = useState("");
  const pending = booking.status === "PENDING";
  const held = booking.status === "HELD";
  const done = () => {
    setEditingHold(false);
    setDeadline("");
    void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    void queryClient.invalidateQueries({ queryKey: ["readiness", booking.event] });
    setRejecting(false);
    setSuggesting(false);
    setReason("");
    void queryClient.invalidateQueries({ queryKey: ["venue-booking-inbox"] });
    void queryClient.invalidateQueries({ queryKey: ["venue-bookings", booking.event] });
    void queryClient.invalidateQueries({ queryKey: ["venue-search"] });
    void queryClient.invalidateQueries({ queryKey: ["venue-shortlist"] });
    void queryClient.invalidateQueries({ queryKey: ["venue-availability"] });
  };
  // A refused decision may mean someone else decided first, so reload the inbox.
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["venue-booking-inbox"] });
    void queryClient.invalidateQueries({ queryKey: ["venue-search"] });
    void queryClient.invalidateQueries({ queryKey: ["venue-shortlist"] });
    void queryClient.invalidateQueries({ queryKey: ["venue-availability"] });
  };
  const approve = useMutation({
    mutationFn: () => approveBooking(booking.id),
    onSuccess: done,
    onError: refresh,
  });
  const reject = useMutation({
    mutationFn: () => suggesting
      ? rejectBooking(booking.id, reason.trim(), {
          venue: Number(suggestedVenue),
          starts_at: `${suggestedStart}+08:00`,
          ends_at: `${suggestedEnd}+08:00`,
        })
      : rejectBooking(booking.id, reason.trim()),
    onSuccess: done,
    onError: refresh,
  });
  const saveHold = useMutation({
    mutationFn: () => {
      const singaporeDeadline = `${deadline}+08:00`;
      return held
        ? updateHoldExpiry(booking.id, singaporeDeadline)
        : approveBooking(booking.id, singaporeDeadline);
    },
    onSuccess: done,
    onError: refresh,
  });
  const failed = approve.error ?? reject.error ?? saveHold.error;
  const busy = approve.isPending || reject.isPending || saveHold.isPending;

  if (!pending && !held) {
    return (
      <div className="text-xs text-slate-500">
        {booking.decided_by_name && booking.decided_at && (
          <span className="block">
            {booking.decided_by_name}, {new Date(booking.decided_at).toLocaleString("en-SG")}
          </span>
        )}
        {booking.buffer_review?.warnings.map((warning) => (
          <p key={warning} role="alert" className="text-sm text-amber-800">{warning}</p>
        ))}
        {booking.decision_reason && <span className="block">Reason: {booking.decision_reason}</span>}
        <SuggestedAlternative booking={booking} canAccept={false} />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {booking.buffer_review?.warnings.map((warning) => (
        <p key={warning} role="alert" className="text-sm text-amber-800">{warning}</p>
      ))}
      {held && booking.hold_until && (
        <p className="text-xs">Hold expires {formatSgt(booking.hold_until)}</p>
      )}
      {!editingHold && !rejecting && (
        <button
          type="button"
          className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-50"
          disabled={busy}
          onClick={() => {
            saveHold.reset();
            setEditingHold(true);
          }}
        >
          {held ? "Change expiry" : "Approve as hold"}
        </button>
      )}
      {editingHold && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (deadline) saveHold.mutate();
          }}
        >
          <label className="block text-xs">
            Hold expiry (Singapore time)
            <input
              className="mt-1 block rounded-md border border-slate-300 px-2 py-1"
              type="datetime-local"
              required
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
            />
          </label>
          <p className="text-xs text-slate-500">Choose a future time before the booking starts.</p>
          <div className="flex gap-2">
            <button
              type="submit"
              className="rounded-md bg-navy-700 px-3 py-1 text-white disabled:opacity-50"
              disabled={busy || !deadline}
            >
              {held ? "Save expiry" : "Place hold"}
            </button>
            <button
              type="button"
              className="rounded-md border border-slate-300 px-3 py-1"
              disabled={busy}
              onClick={() => {
                setEditingHold(false);
                setDeadline("");
                saveHold.reset();
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      {pending && !rejecting && !editingHold && (
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded-md bg-navy-700 px-3 py-1 text-white disabled:opacity-50"
            disabled={busy}
            onClick={() => approve.mutate()}
          >
            Approve
          </button>
          <button
            type="button"
            className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-50"
            disabled={busy}
            onClick={() => setRejecting(true)}
          >
            Reject
          </button>
        </div>
      )}
      {rejecting && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (reason.trim()) reject.mutate();
          }}
        >
          <label className="block text-xs">
            Reason for rejection
            <textarea
              className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1"
              rows={2}
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={suggesting}
              onChange={(e) => { setSuggesting(e.target.checked); reject.reset(); }} />
            Suggest another venue or time
          </label>
          {suggesting && (
            <fieldset className="space-y-2 text-xs">
              <legend>Optional alternative</legend>
              <label className="block">
                Suggested venue
                <select aria-label="Suggested venue" value={suggestedVenue} required className="block w-full border border-slate-300"
                  onChange={(e) => { setSuggestedVenue(e.target.value); reject.reset(); }}>
                  <option value={booking.venue}>{booking.venue_name}</option>
                  {(venues.data ?? []).filter((venue) => venue.id !== booking.venue).map((venue) => (
                    <option key={venue.id} value={venue.id}>{venue.name}</option>
                  ))}
                </select>
              </label>
              {venues.isError && <p role="alert">Other venues could not be loaded. Retry or suggest a different time.</p>}
              <label className="block">
                Suggested start (Singapore time)
                <input type="datetime-local" required value={suggestedStart}
                  onChange={(e) => { setSuggestedStart(e.target.value); reject.reset(); }}
                  className="block border border-slate-300" />
              </label>
              <label className="block">
                Suggested end (Singapore time)
                <input type="datetime-local" required value={suggestedEnd}
                  onChange={(e) => { setSuggestedEnd(e.target.value); reject.reset(); }}
                  className="block border border-slate-300" />
              </label>
              <p>This suggestion will accompany the rejection. The coordinator must request it before staff can approve it.</p>
            </fieldset>
          )}
          <div className="flex gap-2">
            <button
              type="submit"
              className="rounded-md bg-red-700 px-3 py-1 text-white disabled:opacity-50"
              disabled={busy || !reason.trim()}
            >
              Confirm rejection
            </button>
            <button
              type="button"
              className="rounded-md border border-slate-300 px-3 py-1"
              onClick={() => {
                setRejecting(false);
                setReason("");
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      {failed && (
        <ul role="alert" className="text-xs text-red-700">
          {refusal(failed).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
