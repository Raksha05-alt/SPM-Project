import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cancelEvent, getCancellationPreview } from "../api/cancellation";
import type { EventRequest } from "../types";
import { inputClass } from "./Field";

/** INT-03: an assigned coordinator confirms the current resource summary. */
export function EventCancellation({ event }: { event: EventRequest }) {
  const client = useQueryClient();
  const [show, setShow] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("");
  const [validation, setValidation] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const open = ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "PLANNING", "CONFIRMED"].includes(event.status) && (!event.preferred_end || new Date(event.preferred_end).getTime() > Date.now());
  const summary = useQuery({ queryKey: ["cancellation-preview", event.id], queryFn: () => getCancellationPreview(event.id), enabled: show && open, refetchOnWindowFocus: "always" });
  useEffect(() => setConfirmed(false), [summary.data?.version]);
  const action = useMutation({
    mutationFn: () => cancelEvent(event.id, summary.data!.version, reason.trim()),
    onSuccess: () => { setShow(false); setNotice("Event cancelled. Venue bookings and equipment reservations have been released."); },
    onError: () => setConfirmed(false),
    onSettled: async () => {
      await Promise.all(["event", "my-events", "queue", "equipment-plan", "equipment-inbox", "equipment-availability", "equipment-plans", "venue-bookings", "venue-booking-inbox", "venue-availability", "venue-search", "venue-shortlist", "notifications", "cancellation-preview"].map((key) => client.invalidateQueries({ queryKey: [key] })));
    },
  });
  if (!open && !notice) return null;
  return <section aria-label="Event cancellation" className="mt-6 rounded-lg border border-rose-200 bg-white p-4">
    {notice && <p role="status">{notice}</p>}
    {open && !show && <button className="text-rose-800 underline" onClick={() => setShow(true)}>Cancel event</button>}
    {show && open && <form onSubmit={(e) => {
      e.preventDefault();
      if (!confirmed || !reason.trim()) { setValidation("Confirm the resource release and enter the cancellation reason."); return; }
      if (!summary.data || summary.error || summary.isFetching) return;
      setValidation(null); action.mutate();
    }}>
      <h2 className="mb-2 font-semibold">Cancel {event.name}</h2>
      <p>This closes the event and releases its arrangements. The event and resource history will remain on record.</p>
      {summary.isLoading && <p>Loading current arrangements…</p>}
      {summary.error && <p role="alert">We could not load the current arrangements. Reload before cancelling.</p>}
      {summary.data && <div className="my-3">
        <p>{summary.data.venue_bookings.length} venue booking(s) will be withdrawn.</p>
        <ul>{summary.data.venue_bookings.map((row) => <li key={row.id}>{row.venue__name}: {row.status}</li>)}</ul>
        <p>{summary.data.equipment_reservations.length} equipment reservation(s) will be released.</p>
        <ul>{summary.data.equipment_reservations.map((row) => <li key={row.id}>{row.quantity} × {row.request__equipment_type__name}</li>)}</ul>
      </div>}
      <label className="my-3 block">Cancellation reason<textarea className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      <label className="block"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> I confirm cancellation and release of these resources.</label>
      {validation && <p role="alert">{validation}</p>}
      {action.error && <p role="alert">{action.error.message}</p>}
      <div className="mt-3 flex gap-4">
        <button type="button" className="underline" disabled={action.isPending} onClick={() => { setShow(false); setConfirmed(false); }}>Keep event</button>
        <button className="rounded bg-rose-700 px-4 py-2 text-white disabled:opacity-50" disabled={action.isPending || summary.isFetching || !summary.data || Boolean(summary.error)}>Confirm event cancellation</button>
      </div>
    </form>}
  </section>;
}
