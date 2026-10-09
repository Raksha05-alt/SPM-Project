import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import {
  createBlock,
  deleteBlock,
  getAvailability,
  getVenue,
  listBlocks,
  updateBlock,
  updateVenue,
} from "../../api/venues";
import type { BlockInput, Venue, VenueBlock } from "../../api/venues";
import { Field, inputClass } from "../../components/Field";
import { VenueForm, VenueNav, formatDateTime, fromLocalInput, toLocalInput } from "./VenueCatalogue";

const DAY_MS = 24 * 60 * 60 * 1000;

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 whitespace-pre-line text-sm text-slate-800">{children}</dd>
    </div>
  );
}

function errorsFrom(error: unknown): Record<string, string> {
  if (error instanceof ApiError && error.status === 400 && error.body) {
    const next: Record<string, string> = {};
    for (const [key, value] of Object.entries(error.body as Record<string, unknown>)) {
      next[key] = Array.isArray(value) ? String(value[0]) : String(value);
    }
    return next;
  }
  return { detail: error instanceof Error ? error.message : "Something went wrong." };
}

/** SCRUM-13 - add or edit a block; start, end and reason are all required. */
function BlockForm({
  block,
  save,
  onDone,
  submitLabel,
}: {
  block?: VenueBlock;
  save: (input: BlockInput) => Promise<VenueBlock>;
  onDone: () => void;
  submitLabel: string;
}) {
  const prefix = block ? `block-${block.id}` : "block-new";
  const [start, setStart] = useState(toLocalInput(block?.start ?? null));
  const [end, setEnd] = useState(toLocalInput(block?.end ?? null));
  const [reason, setReason] = useState(block?.reason ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const mutation = useMutation({
    mutationFn: () =>
      save({ start: fromLocalInput(start)!, end: fromLocalInput(end)!, reason: reason.trim() }),
    onSuccess: () => {
      setErrors({});
      if (!block) {
        setStart("");
        setEnd("");
        setReason("");
      }
      onDone();
    },
    onError: (error) => setErrors(errorsFrom(error)),
  });

  function submit() {
    const next: Record<string, string> = {};
    if (!start) next.start = "Enter when the block starts.";
    if (!end) next.end = "Enter when the block ends.";
    if (!reason.trim()) next.reason = "Say why the venue is unavailable.";
    setErrors(next);
    if (Object.keys(next).length === 0) mutation.mutate();
  }

  return (
    <div className="rounded-md border border-slate-200 p-4">
      {errors.detail && (
        <p role="alert" className="mb-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {errors.detail}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Block start" htmlFor={`${prefix}-start`} error={errors.start}>
          <input
            id={`${prefix}-start`}
            type="datetime-local"
            className={inputClass}
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </Field>
        <Field label="Block end" htmlFor={`${prefix}-end`} error={errors.end}>
          <input
            id={`${prefix}-end`}
            type="datetime-local"
            className={inputClass}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </Field>
        <Field label="Reason" htmlFor={`${prefix}-reason`} error={errors.reason}>
          <input
            id={`${prefix}-reason`}
            className={inputClass}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={mutation.isPending}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
        >
          {submitLabel}
        </button>
      </div>
    </div>
  );
}

function Blocks({ venueId }: { venueId: number }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<number | null>(null);
  const { data: blocks } = useQuery({
    queryKey: ["venue-blocks", venueId],
    queryFn: () => listBlocks(venueId),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["venue-blocks", venueId] });
    void queryClient.invalidateQueries({ queryKey: ["venue", venueId] });
    void queryClient.invalidateQueries({ queryKey: ["venue-availability", venueId] });
  }

  const remove = useMutation({ mutationFn: deleteBlock, onSuccess: refresh });

  return (
    <section aria-label="Blocks" className="mt-6 rounded-lg border border-slate-200 bg-white p-6">
      <h2 className="mb-3 text-lg font-semibold text-navy-700">Blocks</h2>
      {remove.error && (
        <p role="alert" className="mb-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {remove.error.message}
        </p>
      )}
      {blocks && blocks.length === 0 && (
        <p className="mb-4 text-sm text-slate-500">No active blocks.</p>
      )}
      <ul className="mb-4 space-y-3">
        {blocks?.map((block) => (
          <li key={block.id} className="text-sm text-slate-800">
            {editing === block.id ? (
              <BlockForm
                block={block}
                submitLabel="Save block"
                save={(input) => updateBlock(block.id, input)}
                onDone={() => {
                  setEditing(null);
                  refresh();
                }}
              />
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {formatDateTime(block.start)} – {formatDateTime(block.end)} · {block.reason}
                </span>
                <span className="flex gap-3">
                  <button
                    type="button"
                    onClick={() => setEditing(block.id)}
                    className="text-navy-700 underline"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => remove.mutate(block.id)}
                    disabled={remove.isPending}
                    className="text-rose-700 underline"
                  >
                    Remove
                  </button>
                </span>
              </div>
            )}
          </li>
        ))}
      </ul>
      <h3 className="mb-2 text-sm font-semibold text-navy-700">Block this venue</h3>
      <BlockForm
        submitLabel="Add block"
        save={(input) => createBlock(venueId, input)}
        onDone={refresh}
      />
    </section>
  );
}

/** SCRUM-17 - the venue's diary over a chosen period (default: the next 7 days). */
function Availability({ venueId }: { venueId: number }) {
  const [initial] = useState(() => {
    const now = new Date();
    return { start: toLocalInput(now), end: toLocalInput(new Date(now.getTime() + 7 * DAY_MS)) };
  });
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [period, setPeriod] = useState(initial);

  const { data, error, isLoading } = useQuery({
    queryKey: ["venue-availability", venueId, period.start, period.end],
    queryFn: () =>
      getAvailability(venueId, fromLocalInput(period.start)!, fromLocalInput(period.end)!),
    enabled: Boolean(period.start && period.end),
  });

  return (
    <section
      aria-label="Availability"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="mb-3 text-lg font-semibold text-navy-700">Availability</h2>
      <div className="grid items-end gap-4 sm:grid-cols-3">
        <Field label="From" htmlFor="availability-start">
          <input
            id="availability-start"
            type="datetime-local"
            className={inputClass}
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </Field>
        <Field label="To" htmlFor="availability-end">
          <input
            id="availability-end"
            type="datetime-local"
            className={inputClass}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </Field>
        <div className="mb-4">
          <button
            type="button"
            onClick={() => setPeriod({ start, end })}
            className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600"
          >
            Show availability
          </button>
        </div>
      </div>
      {isLoading && <p className="text-sm text-slate-500">Loading availability…</p>}
      {error && (
        <p role="alert" className="rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {error.message}
        </p>
      )}
      {data && (
        <table className="w-full text-left text-sm text-slate-800">
          <thead className="text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="py-1">From</th>
              <th className="py-1">To</th>
              <th className="py-1">Status</th>
              <th className="py-1">Details</th>
            </tr>
          </thead>
          <tbody>
            {data.segments.map((segment) => (
              <tr key={segment.start} className="border-t border-slate-100">
                <td className="py-1">{formatDateTime(segment.start)}</td>
                <td className="py-1">{formatDateTime(segment.end)}</td>
                <td className="py-1">{segment.label}</td>
                <td className="py-1">{segment.event_name ?? segment.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function VenueDetail() {
  const { id } = useParams();
  const venueId = Number(id);
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);

  const { data: venue, isLoading, isError } = useQuery({
    queryKey: ["venue", venueId],
    queryFn: () => getVenue(venueId),
  });

  function onSaved(saved: Venue) {
    queryClient.setQueryData(["venue", venueId], saved);
    void queryClient.invalidateQueries({ queryKey: ["venues"] });
    setEditing(false);
  }

  if (isLoading) return <p className="text-slate-500">Loading the venue…</p>;
  if (isError || !venue) return <p role="alert">We could not load this venue.</p>;

  return (
    <div>
      <VenueNav />
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-navy-700">{venue.name}</h1>
          <p className="text-sm text-slate-500">{venue.operational_status}</p>
        </div>
        {!editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600"
          >
            Edit venue
          </button>
        )}
      </div>

      {editing ? (
        <VenueForm
          venue={venue}
          submitLabel="Save changes"
          save={(input, confirm) => updateVenue(venueId, input, confirm)}
          onSaved={onSaved}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <section className="rounded-lg border border-slate-200 bg-white p-6">
          <dl className="grid gap-6 sm:grid-cols-2">
            <Detail label="Location">{venue.location || "—"}</Detail>
            <Detail label="Capacity">{venue.capacity}</Detail>
            <Detail label="Layouts">{venue.layout_labels.join(", ") || "—"}</Detail>
            <Detail label="Facilities">{venue.facilities.join(", ") || "—"}</Detail>
            <Detail label="Wheelchair access">
              {venue.wheelchair_access === null ? "—" : venue.wheelchair_access ? "Yes" : "No"}
            </Detail>
            <Detail label="Accessibility notes">{venue.accessibility_notes || "—"}</Detail>
            <Detail label="Operating hours">{venue.operating_hours ?? "—"}</Detail>
            {venue.missing_information.length > 0 && (
              <Detail label="Missing information">{venue.missing_information.join(", ")}</Detail>
            )}
          </dl>
        </section>
      )}

      <Blocks venueId={venueId} />
      <Availability venueId={venueId} />
    </div>
  );
}
