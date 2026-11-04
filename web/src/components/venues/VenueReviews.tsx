import { useQuery } from "@tanstack/react-query";
import { getVenueReviews } from "../../api/venueReviews";

const FIELD_LABELS: Record<string, string> = {
  expected_attendance: "expected attendance",
  required_layout: "required layout",
  accessibility_needs: "accessibility needs",
};

/**
 * SCRUM-66 AC3 - why a booked venue was flagged after the event changed.
 * Renders nothing unless a review is open; earlier reviews stay on record.
 */
export function VenueReviews({ eventId }: { eventId: number }) {
  const { data, isError } = useQuery({
    queryKey: ["venue-reviews", eventId],
    queryFn: () => getVenueReviews(eventId),
  });

  if (isError) {
    return (
      <p role="alert" className="mt-6 text-sm text-rose-800">
        We could not check whether the booked venues still suit this event.
      </p>
    );
  }
  if (!data || data.open.length === 0) return null;

  return (
    <section
      aria-label="Venue review"
      className="mt-6 rounded-lg border border-amber-300 bg-amber-50 p-6"
    >
      <h2 className="mb-1 text-sm font-semibold text-amber-900">Venue needs review</h2>
      <p className="mb-3 text-xs text-amber-900">
        The event changed after these venues were approved. The bookings are kept, but the event
        cannot be confirmed until each one suits it again: change the event back, or withdraw the
        booking and request a venue that fits.
      </p>
      <ul className="space-y-3">
        {data.open.map((review) => (
          <li key={review.id} aria-label={review.venue} className="text-sm">
            <p className="font-medium text-slate-800">{review.venue}</p>
            <ul className="mt-1 list-disc pl-5 text-amber-900">
              {review.reasons.map((reason) => (
                <li key={reason.message}>{reason.message}</li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-slate-600">
              Flagged after the{" "}
              {review.changed_fields.map((f) => FIELD_LABELS[f] ?? f).join(" and ")} changed
              {review.raised_by_name ? ` (by ${review.raised_by_name})` : ""} ·{" "}
              <time dateTime={review.raised_at}>
                {new Date(review.raised_at).toLocaleString("en-SG")}
              </time>
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
