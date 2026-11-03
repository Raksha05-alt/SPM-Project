import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { getVenue } from "../api/venues";
import type { Venue } from "../types";

const NOT_PROVIDED = "Not provided";

function accessibility(venue: Venue): string | null {
  const parts = [];
  if (venue.wheelchair_access !== null) {
    parts.push(venue.wheelchair_access ? "Wheelchair accessible" : "Not wheelchair accessible");
  }
  if (venue.accessibility_notes) parts.push(venue.accessibility_notes);
  return parts.length ? parts.join(". ") : null;
}

function Detail({ label, value }: { label: string; value: string | null }) {
  // SCRUM-9 AC3 - missing information is named, never left blank.
  return (
    <div className="border-b border-slate-100 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
      <dt className="text-sm font-medium text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm sm:col-span-2 sm:mt-0">
        {value ? (
          <span className="text-slate-800">{value}</span>
        ) : (
          <span className="font-medium text-amber-700">{NOT_PROVIDED}</span>
        )}
      </dd>
    </div>
  );
}

/** SCRUM-9 AC2 to AC4 - everything Venue Staff need to answer a venue request. */
export function VenueDetail() {
  const id = Number(useParams().id);
  const {
    data: venue,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["venues", id],
    queryFn: () => getVenue(id),
  });

  if (isLoading) return <p className="text-slate-500">Loading venue…</p>;
  if (error || !venue) {
    return (
      <p role="alert">
        {error instanceof ApiError && error.status === 404
          ? "That venue does not exist."
          : "We could not load this venue."}
      </p>
    );
  }

  const inService = venue.operational_status === "In service";

  return (
    <div>
      <Link to="/venues" className="text-sm text-navy-700 underline">
        Back to venues
      </Link>
      <div className="mb-6 mt-2 flex flex-wrap items-baseline gap-3">
        <h1 className="text-2xl font-semibold text-navy-700">{venue.name}</h1>
        <span
          className={
            "rounded-full px-3 py-1 text-xs font-medium " +
            (inService ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-800")
          }
        >
          {venue.operational_status}
        </span>
      </div>

      {venue.missing_information.length > 0 && (
        <p role="note" className="mb-6 rounded-md bg-amber-50 p-3 text-sm text-amber-800">
          Not provided yet: {venue.missing_information.join(", ")}.
        </p>
      )}

      <dl className="rounded-lg border border-slate-200 bg-white px-6">
        <Detail label="Location" value={venue.location || null} />
        <Detail label="Maximum capacity" value={`${venue.capacity} people`} />
        <Detail label="Facilities" value={venue.facilities.join(", ") || null} />
        <Detail label="Accessibility information" value={accessibility(venue)} />
        <Detail label="Emergency access" value={venue.emergency_access || null} />
        <Detail label="Known restrictions" value={venue.known_restrictions || null} />
        <Detail label="Supported room layouts" value={venue.layout_labels.join(", ") || null} />
        <Detail label="Operating hours" value={venue.operating_hours} />
      </dl>
      <p className="mt-3 text-xs text-slate-500">
        Last updated {new Date(venue.updated_at).toLocaleString("en-SG")}
        {venue.updated_by_name ? ` by ${venue.updated_by_name}` : ""}
      </p>
    </div>
  );
}
