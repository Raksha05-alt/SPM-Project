import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import { acceptVenueSuggestion } from "../../api/venueBookings";
import { formatSgt } from "../../dateTime";
import type { VenueBooking } from "../../types";

/** The staff proposal remains beside its original rejection after acceptance. */
export function SuggestedAlternative({ booking, canAccept }: { booking: VenueBooking; canAccept: boolean }) {
  const client = useQueryClient();
  const accept = useMutation({
    mutationFn: () => acceptVenueSuggestion(booking.id),
    onSuccess: () => { void client.invalidateQueries(); },
    onError: () => {
      void client.invalidateQueries({ queryKey: ["venue-bookings", booking.event] });
    },
  });
  const suggestion = booking.suggestion;
  if (!suggestion) return null;
  const body = accept.error instanceof ApiError
    ? accept.error.body as {
        detail?: string;
        suggestion?: string[];
        status?: string[];
        event?: string[];
        reasons?: string[];
        unmet_requirements?: { message: string }[];
      } | null : null;
  const reasons = [
    ...(body?.suggestion ?? []), ...(body?.status ?? []), ...(body?.event ?? []),
    ...(body?.reasons ?? []), ...(body?.unmet_requirements ?? []).map((reason) => reason.message),
  ];

  return (
    <div className="mt-2 space-y-1 rounded-md border border-slate-200 p-2 text-xs">
      <p className="font-medium">Suggested alternative · {suggestion.venue_name}</p>
      <p>{formatSgt(suggestion.starts_at)} – {formatSgt(suggestion.ends_at)}</p>
      {suggestion.booking ? (
        <p>Requested as booking #{suggestion.booking}. See its current status in the venue requests.</p>
      ) : canAccept && booking.status === "REJECTED" ? (
        <button type="button" disabled={accept.isPending} className="underline disabled:opacity-50"
          onClick={() => accept.mutate()}>
          Accept and request alternative
        </button>
      ) : null}
      {accept.isError && (
        <div role="alert" className="text-red-700">
          <p>{body?.detail ?? "The alternative could not be requested. Try again."}</p>
          {reasons.map((reason) => <p key={reason}>{reason}</p>)}
        </div>
      )}
      {accept.isSuccess && <p role="status">{accept.data.detail}</p>}
    </div>
  );
}
