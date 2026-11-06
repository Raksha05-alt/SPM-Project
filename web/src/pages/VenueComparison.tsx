import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { compareAvailability } from "../api/availability";

const display = (value: string) => new Date(value).toLocaleString("en-SG", { timeZone: "Asia/Singapore" });
const labels = { available: "Available for the whole period", partial: "Partly available", unavailable: "Unavailable for the whole period" };
const colors = { available: "border-green-600 bg-green-50", partial: "border-amber-600 bg-amber-50", unavailable: "border-red-600 bg-red-50" };

export function VenueComparison() {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [period, setPeriod] = useState<{ start: string; end: string } | null>(null);
  const result = useQuery({
    queryKey: ["venue-availability", "comparison", period],
    queryFn: () => compareAvailability(`${period!.start}:00+08:00`, `${period!.end}:00+08:00`),
    enabled: !!period, staleTime: 0,
  });
  return <section aria-label="Compare venue availability" className="space-y-3 rounded border p-4">
    <h2 className="text-lg font-semibold">Compare availability across venues</h2>
    <form className="flex flex-wrap items-end gap-3" onSubmit={event => {
      event.preventDefault();
      if (period?.start === start && period?.end === end) void result.refetch();
      else setPeriod({ start, end });
    }}>
      <label>Comparison start<input className="block rounded border p-2" type="datetime-local" required value={start} onChange={event => setStart(event.target.value)} /></label>
      <label>Comparison end<input className="block rounded border p-2" type="datetime-local" required min={start} value={end} onChange={event => setEnd(event.target.value)} /></label>
      <button className="rounded border px-3 py-2">Compare venues</button>
    </form>
    {result.isFetching && <p role="status">Comparing venues...</p>}
    {result.isError && <p role="alert">Could not compare venues. Enter an end after the start and retry.</p>}
    {result.data && !result.isError && !result.isFetching && <>
      <p>{display(result.data.starts_at)} to {display(result.data.ends_at)} (Singapore time)</p>
      {result.data.message && <p role="status" className="font-semibold">{result.data.message}</p>}
      <button className="rounded border px-3 py-2" onClick={() => void result.refetch()}>Refresh comparison</button>
      <ul className="space-y-3">{result.data.venues.map(venue => <li key={venue.venue_id} className={`rounded border-l-4 p-3 ${colors[venue.status]}`}>
        <h3 className="font-semibold">{venue.name}</h3>
        <p>{labels[venue.status]}</p>
        {venue.reasons.map(reason => <p key={reason}>{reason}</p>)}
        {venue.free_segments.map(segment => <p key={segment.starts_at}>Free: {display(segment.starts_at)} to {display(segment.ends_at)}</p>)}
      </li>)}</ul>
    </>}
  </section>;
}
