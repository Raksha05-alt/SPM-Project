import { formatSgt } from "../dateTime";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { listBookingInbox } from "../api/venueBookings";
import { BookingDecision } from "../components/venues/BookingDecision";
import { VenueReviews } from "../components/venues/VenueReviews";

const FILTERS: [string, string][] = [
  ["PENDING", "Waiting for review"],
  ["HELD", "Active holds"],
  ["EXPIRED", "Expired holds"],
  ["DISRUPTED", "Disrupted bookings"],
  ["", "All requests"],
];

/** SCRUM-11 AC4 - Venue Staff see the booking requests sent to them; SCRUM-72 - and decide them. */
export function VenueBookingInbox() {
  const [status, setStatus] = useState("PENDING");
  const { data, isLoading, isError } = useQuery({
    queryKey: ["venue-booking-inbox", status],
    queryFn: () => listBookingInbox(status || undefined),
    refetchInterval: status !== "PENDING" ? 15_000 : false,
  });
  const rows = data ?? [];

  return (
    <div>
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold text-navy-700">Booking requests</h1>
        <Link to="/venues" className="text-sm text-navy-700 underline">
          Back to venues
        </Link>
      </div>
      <label className="mb-4 flex items-center gap-2 text-sm">
        Show
        <select
          aria-label="Show requests"
          className="rounded-md border border-slate-300 px-2 py-1"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          {FILTERS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>

      {status === "" && [...new Set(rows.map((booking) => booking.event))].map((eventId) => (
        <VenueReviews key={eventId} eventId={eventId} />
      ))}

      {isLoading && <p className="text-slate-500">Loading booking requests…</p>}
      {isError && <p role="alert">We could not load the booking requests.</p>}
      {!isLoading && !isError && rows.length === 0 && (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          No booking requests to show.
        </p>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Venue</th>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">When</th>
                <th className="px-4 py-3">Requirements</th>
                <th className="px-4 py-3">Requested by</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Decision</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {rows.map((b) => (
                <tr key={b.id}>
                  <td className="px-4 py-3 font-medium text-navy-700">{b.venue_name}</td>
                  <td className="px-4 py-3">
                    {b.event_name}<span className="block text-xs">{b.session_name ?? "Main programme"}</span>
                    <span className="block text-xs text-slate-500">{b.organisation_name}</span>
                  </td>
                  <td className="px-4 py-3">
                    {formatSgt(b.starts_at)} –{" "}
                    {formatSgt(b.ends_at)}
                    {b.buffer_review && (
                      <span className="block text-xs text-slate-500">
                        Including setup/turnaround: {formatSgt(b.buffer_review.occupied_starts_at)}
                        {" to "}{formatSgt(b.buffer_review.occupied_ends_at)}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {b.attendance} people{b.layout_name ? ` · ${b.layout_name}` : ""}
                    {b.required_facilities.length > 0 && (
                      <span className="block text-xs">{b.required_facilities.join(", ")}</span>
                    )}
                    {b.wheelchair_access_required && (
                      <span className="block text-xs">Wheelchair access required</span>
                    )}
                    {b.accessibility_notes && (
                      <span className="block text-xs text-slate-500">{b.accessibility_notes}</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {b.requested_by_name}
                    <span className="block text-xs text-slate-500">
                      {formatSgt(b.requested_at)}
                    </span>
                  </td>
                  <td className="px-4 py-3">{b.status_label}</td>
                  <td className="px-4 py-3">
                    <BookingDecision booking={b} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
