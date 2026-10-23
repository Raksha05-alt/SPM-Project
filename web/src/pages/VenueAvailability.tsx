import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listVenues } from "../api/venues";
import { getAvailability, getBlocks, getBlockHistory, saveBlock, removeBlock, findAvailableVenues } from "../api/availability";
import type { VenueBlock } from "../api/availability";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const inputClass = "block rounded border border-slate-300 p-2 text-sm";
const buttonClass = "rounded border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50";
// Inputs are explicitly Singapore wall time, independent of the browser timezone.
const singapore = (value: string) => `${value.length === 16 ? `${value}:00` : value}+08:00`;
const localInput = (value: string) => new Date(new Date(value).getTime() + 8 * 3600000).toISOString().slice(0, 16);
const display = (value: string) => new Date(value).toLocaleString("en-SG", { timeZone: "Asia/Singapore" });

export function VenueAvailability() {
  const { user } = useAuth();
  const staff = user?.role === "VENUE_STAFF";
  const client = useQueryClient();
  const [venueId, setVenueId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [period, setPeriod] = useState<{ start: string; end: string } | null>(null);
  const [editing, setEditing] = useState<number>();
  const [reason, setReason] = useState("");
  const [blockStart, setBlockStart] = useState("");
  const [blockEnd, setBlockEnd] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [searchPeriod, setSearchPeriod] = useState<{ start: string; end: string } | null>(null);
  const search = useQuery({ queryKey: ["venue-availability", "search", searchPeriod],
    queryFn: () => findAvailableVenues(singapore(searchPeriod!.start), singapore(searchPeriod!.end)),
    enabled: !!searchPeriod, staleTime: 0,
  });
  const venues = useQuery({ queryKey: ["venues"], queryFn: listVenues });
  const id = Number(venueId);
  const blocks = useQuery({ queryKey: ["venue-blocks", id], queryFn: () => getBlocks(id), enabled: !!id });
  const history = useQuery({ queryKey: ["venue-block-history", id], queryFn: () => getBlockHistory(id), enabled: !!id && staff });
  const result = useQuery({
    queryKey: ["venue-availability", id, period],
    queryFn: () => getAvailability(id, singapore(period!.start), singapore(period!.end)),
    enabled: !!id && !!period, staleTime: 0,
  });

  function reset() { setEditing(undefined); setReason(""); setBlockStart(""); setBlockEnd(""); }
  function edit(block: VenueBlock) {
    setEditing(block.id); setReason(block.reason);
    setBlockStart(localInput(block.starts_at)); setBlockEnd(localInput(block.ends_at));
    setError(""); setNotice("");
  }
  async function mutate(action: () => Promise<unknown>, message: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      await action(); reset(); setNotice(message);
      await Promise.all(["venues", "venue-blocks", "venue-block-history", "venue-availability"].map(
        key => client.invalidateQueries({ queryKey: [key] }),
      ));
    } catch (err) {
      setError(err instanceof ApiError ? JSON.stringify(err.body) : "Could not save the change. Please retry.");
    } finally { setBusy(false); }
  }

  return <div className="space-y-6">
    <Link to={staff ? "/venues" : "/coordinator"} className="text-navy-700 underline">Back</Link>
    <h1 className="text-2xl font-semibold text-navy-700">Venue availability</h1>
    <p className="text-sm text-slate-600">All dates and times use Singapore time (UTC+08:00). End times are exclusive.</p>
    <form className="flex flex-wrap items-end gap-4" onSubmit={e => {
      e.preventDefault();
      if (searchPeriod?.start === start && searchPeriod?.end === end) void search.refetch();
      else setSearchPeriod({ start, end });
    }}>
      <label>Search start<input className={inputClass} type="datetime-local" required value={start} onChange={e => setStart(e.target.value)} /></label>
      <label>Search end<input className={inputClass} type="datetime-local" required min={start} value={end} onChange={e => setEnd(e.target.value)} /></label>
      <button className={buttonClass}>Find available venues</button>
    </form>
    {search.isFetching && <p role="status">Searching...</p>}
    {search.isError && <p role="alert">Could not search. Check the dates and retry.</p>}
    {search.data && !search.isError && !search.isFetching && <section aria-label="Available venues">
      <h2 className="text-lg font-semibold">Available venues</h2>
      {search.data.length === 0 && <p>No venues available for this period.</p>}
      {search.data.map(v => <button key={v.id} className={buttonClass} onClick={() => { setVenueId(String(v.id)); setPeriod(searchPeriod); reset(); }}>{v.name}</button>)}
    </section>}
    {venues.isError && <p role="alert">Could not load venues. Refresh to retry.</p>}
    <label className="block">Venue
      <select className={inputClass} disabled={busy} value={venueId} onChange={e => { setVenueId(e.target.value); setPeriod(null); reset(); setError(""); setNotice(""); }}>
        <option value="">Select a venue</option>
        {venues.data?.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
      </select>
    </label>
    {id > 0 && <>
      <form className="flex flex-wrap items-end gap-4" onSubmit={e => {
        e.preventDefault();
        if (period?.start === start && period?.end === end) void result.refetch();
        else setPeriod({ start, end });
      }}>
        <label>Period start<input className={inputClass} type="datetime-local" required value={start} onChange={e => setStart(e.target.value)} /></label>
        <label>Period end<input className={inputClass} type="datetime-local" required min={start} value={end} onChange={e => setEnd(e.target.value)} /></label>
        <button className={buttonClass}>Check availability</button>
      </form>
      {result.isFetching && <p role="status">Checking availability...</p>}
      {result.isError && <p role="alert">Could not check availability. Enter an end after the start and retry.</p>}
      {result.data && !result.isError && !result.isFetching && <section aria-label="Availability result" className="rounded border bg-white p-4">
        <p className="font-semibold capitalize">{result.data.status}</p>
        <p>{display(result.data.starts_at)} to {display(result.data.ends_at)}</p>
        {result.data.blocks.map(b => <p key={b.id}>Blocked: {b.reason} ({display(b.starts_at)} to {display(b.ends_at)})</p>)}
      </section>}
      <section aria-label="Venue blocks" className="space-y-3">
        <h2 className="text-lg font-semibold">Blocked periods</h2>
        {blocks.isError && <p role="alert">Could not load blocked periods.</p>}
        {blocks.data?.length === 0 && <p>No blocked periods recorded.</p>}
        {blocks.data?.map(b => <div key={b.id} className="rounded border bg-white p-3">
          <p className="font-medium">{b.reason}</p><p>{display(b.starts_at)} to {display(b.ends_at)}</p>
          {staff && <div className="mt-2 flex gap-2">
            <button className={buttonClass} disabled={busy} onClick={() => edit(b)}>Edit</button>
            <button className={buttonClass} disabled={busy} onClick={() => void mutate(() => removeBlock(id, b.id), "Block removed.")}>Remove</button>
          </div>}
        </div>)}
      </section>
      {staff && <form aria-label="Block venue" className="space-y-3 rounded border bg-white p-4" onSubmit={e => {
        e.preventDefault(); void mutate(() => saveBlock(id, { reason, starts_at: singapore(blockStart), ends_at: singapore(blockEnd) }, editing), editing ? "Block updated." : "Block saved.");
      }}>
        <h2 className="text-lg font-semibold">{editing ? "Edit block" : "Block venue"}</h2>
        <label className="block">Reason<textarea className={inputClass} required value={reason} onChange={e => setReason(e.target.value)} /></label>
        <label className="block">Block start<input className={inputClass} type="datetime-local" required value={blockStart} onChange={e => setBlockStart(e.target.value)} /></label>
        <label className="block">Block end<input className={inputClass} type="datetime-local" required min={blockStart} value={blockEnd} onChange={e => setBlockEnd(e.target.value)} /></label>
        <button className={buttonClass} disabled={busy}>{busy ? "Saving..." : "Save block"}</button>
        {editing && <button type="button" className={buttonClass} disabled={busy} onClick={reset}>Cancel edit</button>}
      </form>}
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      {staff && <section aria-label="Block history">
        <h2 className="text-lg font-semibold">Block history</h2>
        {history.isError && <p role="alert">Could not load block history.</p>}
        {history.data?.map(h => <p key={h.id}>{h.action}: {h.reason} ({display(h.starts_at)} to {display(h.ends_at)}) — {h.actor_name}, {display(h.created_at)}</p>)}
      </section>}
    </>}
  </div>;
}
