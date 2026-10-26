import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { getEvent } from "../api/events";
import {
  addVenueToShortlist,
  getVenueShortlist,
  removeVenueFromShortlist,
  searchVenues,
  type VenueMatch,
  type VenueSearchCriteria,
} from "../api/venueDiscovery";
import { useAuth } from "../auth/AuthContext";
import { Field, inputClass } from "../components/Field";
import type { EventRequest } from "../types";

const LAYOUTS = ["CLASSROOM", "THEATRE", "BOARDROOM", "BANQUET", "EXHIBITION"];
const EMPTY = { start: "", end: "", attendance: "", layout: "", facilities: "" };

function localInput(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function initialForm(event?: EventRequest) {
  return {
    ...EMPTY,
    start: localInput(event?.preferred_start),
    end: localInput(event?.preferred_end),
    attendance: event?.expected_attendance?.toString() ?? "",
    layout: event?.required_layout ?? "",
  };
}

function toCriteria(form: typeof EMPTY): VenueSearchCriteria {
  if (Boolean(form.start) !== Boolean(form.end)) {
    throw new Error("Enter both event start and end, or leave both empty.");
  }
  if (form.start && new Date(form.end) <= new Date(form.start)) {
    throw new Error("Event end must be after its start.");
  }
  const attendance = form.attendance === "" ? undefined : Number(form.attendance);
  if (attendance !== undefined && (!Number.isInteger(attendance) || attendance < 1)) {
    throw new Error("Enter a positive whole number for attendance.");
  }
  return {
    ...(form.start
      ? { start: new Date(form.start).toISOString(), end: new Date(form.end).toISOString() }
      : {}),
    ...(attendance !== undefined ? { attendance } : {}),
    ...(form.layout ? { layout: form.layout } : {}),
    facilities: form.facilities
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  };
}

function errorText(error: unknown) {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    const detail = (error.body as { detail?: string | string[] }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.join(" ");
  }
  return "We could not confirm this change. Refresh the page to check the saved shortlist.";
}

function MatchDetails({ match }: { match: VenueMatch }) {
  return (
    <>
      <p className="text-sm text-slate-600">
        {match.venue.location || "Location not recorded"} · Capacity {match.venue.capacity}
      </p>
      {match.availability_status === "UNAVAILABLE" ? (
        <p className="mt-2 font-medium text-rose-700">No longer available for these criteria</p>
      ) : (
        <p className="mt-2 text-sm text-amber-800">Availability not verified</p>
      )}
      {!match.matches_recorded_requirements && (
        <p className="text-sm font-medium text-rose-700">No longer matches the saved search.</p>
      )}
      <ul aria-label={`Criteria for ${match.venue.name}`} className="mt-3 space-y-1 text-sm">
        {match.criteria.map((criterion) => (
          <li key={criterion.key}>
            <span className={criterion.result === "UNMET" ? "font-medium text-rose-700" : ""}>
              {criterion.result === "MATCH"
                ? "Met"
                : criterion.result === "UNMET"
                  ? "Not met"
                  : "Not checked"}
              : {criterion.label}.
            </span>{" "}
            {criterion.message}
          </li>
        ))}
      </ul>
    </>
  );
}

export function VenueDiscovery({ event }: { event?: EventRequest }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [form, setForm] = useState(() => initialForm(event));
  const [criteria, setCriteria] = useState<VenueSearchCriteria>(() =>
    toCriteria(initialForm(event)),
  );
  const [validationError, setValidationError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const search = useQuery({
    queryKey: ["venue-search", user?.id, criteria],
    queryFn: () => searchVenues(criteria),
  });
  const shortlistKey = ["venue-shortlist", event?.id, user?.id];
  const shortlist = useQuery({
    queryKey: shortlistKey,
    queryFn: () => getVenueShortlist(event!.id),
    enabled: Boolean(event),
  });
  const add = useMutation({
    mutationFn: (venueId: number) => addVenueToShortlist(event!.id, venueId, search.data!.criteria),
    onSuccess: () => {
      setNotice("Venue saved to this event's shortlist.");
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: shortlistKey }),
  });
  const remove = useMutation({
    mutationFn: (venueId: number) => removeVenueFromShortlist(event!.id, venueId),
    onSuccess: () => {
      setNotice("Venue removed from this event's shortlist.");
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: shortlistKey }),
  });
  const set = (key: keyof typeof EMPTY, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));
  const busy = add.isPending || remove.isPending;
  const canEdit = shortlist.data?.can_edit === true;
  const savedIds = new Set(shortlist.data?.entries.map((entry) => entry.match.venue.id));

  function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const next = toCriteria(form);
      setValidationError(null);
      if (JSON.stringify(next) === JSON.stringify(criteria)) void search.refetch();
      else setCriteria(next);
    } catch (error) {
      setValidationError((error as Error).message);
    }
  }

  return (
    <div>
      {event && (
        <Link to={`/coordinator/events/${event.id}`} className="text-sm text-navy-700 underline">
          Back to {event.name}
        </Link>
      )}
      <h1 className="mb-2 mt-2 text-2xl font-semibold text-navy-700">
        Venue search{event ? " and shortlist" : ""}
      </h1>
      <p className="mb-4 text-sm text-slate-600">
        {event
          ? `Planning for ${event.name}. Filters start with the event requirements; you can change or clear them.`
          : "Open an event to save a shortlist against it."}
      </p>
      <p role="note" className="mb-6 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
        {search.data?.limitation ??
          "Recorded date-specific blocks and operating hours are checked for a supplied period. Booking and hold occupancy is not integrated yet; verify booking availability with Venue Staff."}
      </p>
      <form
        aria-label="Venue search filters"
        onSubmit={submit}
        className="mb-8 rounded-lg border border-slate-200 bg-white p-6"
      >
        <div className="grid gap-x-6 sm:grid-cols-2">
          <Field label="Event start (your local time)" htmlFor="search-start">
            <input
              id="search-start"
              type="datetime-local"
              className={inputClass}
              value={form.start}
              onChange={(e) => set("start", e.target.value)}
            />
          </Field>
          <Field label="Event end (your local time)" htmlFor="search-end">
            <input
              id="search-end"
              type="datetime-local"
              className={inputClass}
              value={form.end}
              onChange={(e) => set("end", e.target.value)}
            />
          </Field>
          <Field label="Expected attendance" htmlFor="search-attendance">
            <input
              id="search-attendance"
              type="number"
              className={inputClass}
              value={form.attendance}
              onChange={(e) => set("attendance", e.target.value)}
            />
          </Field>
          <Field label="Required room layout" htmlFor="search-layout">
            <select
              id="search-layout"
              className={inputClass}
              value={form.layout}
              onChange={(e) => set("layout", e.target.value)}
            >
              <option value="">Any layout</option>
              {LAYOUTS.map((layout) => (
                <option key={layout} value={layout}>
                  {layout[0] + layout.slice(1).toLowerCase()}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Required facilities"
            htmlFor="search-facilities"
            hint="Separate facility names with commas."
          >
            <input
              id="search-facilities"
              className={inputClass}
              value={form.facilities}
              onChange={(e) => set("facilities", e.target.value)}
            />
          </Field>
        </div>
        {validationError && (
          <p role="alert" className="mb-3 text-sm text-rose-700">
            {validationError}
          </p>
        )}
        <div className="flex gap-3">
          <button
            type="submit"
            disabled={search.isFetching}
            className="rounded-md bg-navy-700 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            Search venues
          </button>
          <button
            type="button"
            className="text-sm text-navy-700 underline"
            onClick={() => {
              setForm(EMPTY);
              setCriteria({ facilities: [] });
              setValidationError(null);
            }}
          >
            Clear filters
          </button>
        </div>
      </form>

      <section aria-label="Search results">
        <h2 className="mb-3 text-lg font-semibold">Venue candidates</h2>
        {search.isPending ? (
          <p>Loading venue candidates…</p>
        ) : search.isError ? (
          <p role="alert">
            We could not load venue search results.{" "}
            <button type="button" className="underline" onClick={() => void search.refetch()}>
              Try again
            </button>
          </p>
        ) : search.data.results.length === 0 ? (
          <p>No venue matched the filters you entered.</p>
        ) : (
          <ul className="space-y-4">
            {search.data.results.map((match) => (
              <li key={match.venue.id} className="rounded-lg border border-slate-200 bg-white p-5">
                <h3 className="mb-1 font-semibold">{match.venue.name}</h3>
                <MatchDetails match={match} />
                {event && (
                  <button
                    type="button"
                    disabled={!canEdit || busy || savedIds.has(match.venue.id)}
                    className="mt-3 rounded-md border border-slate-300 px-3 py-1 text-sm disabled:opacity-50"
                    onClick={() => {
                      setNotice(null);
                      add.reset();
                      remove.reset();
                      add.mutate(match.venue.id);
                    }}
                  >
                    {savedIds.has(match.venue.id) ? "Shortlisted" : `Shortlist ${match.venue.name}`}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {event && (
        <section aria-label="Saved shortlist" className="mt-8">
          <h2 className="mb-2 text-lg font-semibold">Saved shortlist</h2>
          <p className="mb-3 text-sm text-slate-600">
            Each entry shows its saved search criteria against current venue records. Re-run the
            search if the event requirements change. Date checks use the saved search period,
            or the event's period when no dates were saved.
          </p>
          {notice && (
            <p role="status" className="mb-3 text-sm text-emerald-800">
              {notice}
            </p>
          )}
          {(add.error || remove.error) && (
            <p role="alert" className="mb-3 text-sm text-rose-700">
              {errorText(add.error ?? remove.error)}
            </p>
          )}
          {shortlist.isPending ? (
            <p>Loading shortlist…</p>
          ) : shortlist.isError ? (
            <p role="alert">
              We could not load this event's shortlist.{" "}
              <button type="button" className="underline" onClick={() => void shortlist.refetch()}>
                Refresh shortlist
              </button>
            </p>
          ) : (
            <>
              {!canEdit && (
                <p className="mb-3 text-sm text-slate-600">
                  This shortlist is read-only. Only the assigned coordinator can change it while the
                  event is open.
                </p>
              )}
              {shortlist.data?.entries.length === 0 && <p>No venues shortlisted yet.</p>}
              <ul className="space-y-4">
                {shortlist.data?.entries.map((entry) => (
                  <li key={entry.id} className="rounded-lg border border-slate-200 bg-white p-5">
                    <h3 className="mb-1 font-semibold">{entry.match.venue.name}</h3>
                    <MatchDetails match={entry.match} />
                    <button
                      type="button"
                      disabled={!canEdit || busy}
                      className="mt-3 text-sm text-rose-700 underline disabled:opacity-50"
                      onClick={() => {
                        setNotice(null);
                        add.reset();
                        remove.reset();
                        remove.mutate(entry.match.venue.id);
                      }}
                    >
                      Remove {entry.match.venue.name}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
    </div>
  );
}

export function VenueDiscoveryPage() {
  const id = useParams().id;
  const eventId = Number(id);
  const event = useQuery({
    queryKey: ["event", eventId],
    queryFn: () => getEvent(eventId),
    enabled: Boolean(id),
  });
  if (!id) return <VenueDiscovery />;
  if (event.isPending) return <p>Loading event requirements…</p>;
  if (event.isError) return <p role="alert">We could not load this event.</p>;
  return <VenueDiscovery key={event.data.id} event={event.data} />;
}
