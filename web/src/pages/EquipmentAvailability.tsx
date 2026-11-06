import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { getEquipmentAvailability, listEquipmentInbox } from "../api/equipment";
import { fetchMyEvents } from "../api/events";
import { useAuth } from "../auth/AuthContext";
import { inputClass } from "../components/Field";
import { EquipmentHoldersPanel } from "../components/equipment/EquipmentHoldersPanel";
import type { EquipmentAvailabilityRow } from "../types";

/** An ISO instant as a datetime-local value in the viewer's time zone. */
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function when(iso: string) {
  return new Date(iso).toLocaleString("en-SG");
}

const STATUS_LABEL: Record<EquipmentAvailabilityRow["status"], string> = {
  AVAILABLE: "Available",
  PARTIAL: "Partly available",
  UNAVAILABLE: "Unavailable",
};

const STATUS_STYLE: Record<EquipmentAvailabilityRow["status"], string> = {
  AVAILABLE: "bg-emerald-50 text-emerald-800",
  PARTIAL: "bg-amber-50 text-amber-900",
  UNAVAILABLE: "bg-rose-50 text-rose-800",
};

/** AC1 - choose an event: Technical Support from their inbox, a coordinator from their own. */
function EventPicker() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isTech = user?.role === "TECH_SUPPORT";
  const events = useQuery({
    queryKey: ["availability-events", user?.role],
    queryFn: async () =>
      isTech
        ? (await listEquipmentInbox()).map((e) => ({ id: e.id, name: e.name }))
        : (await fetchMyEvents()).map((e) => ({ id: e.id, name: e.name })),
  });

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold text-navy-700">Equipment availability</h1>
      <p className="mb-6 text-sm text-slate-600">Choose an event to check its equipment.</p>
      {events.isLoading && <p className="text-slate-500">Loading events…</p>}
      {events.isError && <p role="alert">We could not load your events.</p>}
      {events.data && events.data.length === 0 && (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          {isTech ? "No event has equipment requested yet." : "No events are assigned to you."}
        </p>
      )}
      {events.data && events.data.length > 0 && (
        <label className="block max-w-md text-sm font-medium">
          Event
          <select
            className={`${inputClass} mt-1`}
            defaultValue=""
            onChange={(e) => e.target.value && navigate(`/equipment/availability/${e.target.value}`)}
          >
            <option value="">Choose an event…</option>
            {events.data.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name || `Event ${e.id}`}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}

function OutOfAction({ row }: { row: EquipmentAvailabilityRow }) {
  if (!row.unavailable.length) return null;
  return (
    <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
      {row.unavailable.map((u, i) => (
        <li key={i}>
          {u.quantity} {u.cause_label.toLowerCase()}: {u.reason}
          {" · "}
          {u.expected_return_at
            ? `expected back ${when(u.expected_return_at)}`
            : "return date not recorded"}
        </li>
      ))}
    </ul>
  );
}

/**
 * SCRUM-12 - Technical Support (or the event's coordinator) check how much of
 * each equipment type is available for the event period, what is out of action
 * and why, and whether the requested quantities can be supplied. SCRUM-76 -
 * selecting a held or out-of-action type shows who is holding it.
 */
export function EquipmentAvailabilityPage() {
  const { id } = useParams();
  const eventId = Number(id);
  const [draft, setDraft] = useState<{ starts_at: string; ends_at: string } | null>(null);
  const [period, setPeriod] = useState<{ starts_at: string; ends_at: string } | undefined>();
  // SCRUM-76 - the equipment type whose holders are shown.
  const [selected, setSelected] = useState<number | null>(null);

  const { data, isFetching, error } = useQuery({
    queryKey: ["equipment-availability", eventId, period],
    queryFn: () => getEquipmentAvailability(eventId, period),
    enabled: Number.isFinite(eventId),
  });

  if (!id) return <EventPicker />;

  const shown = draft ?? (data ? {
    starts_at: toLocalInput(data.period.starts_at),
    ends_at: toLocalInput(data.period.ends_at),
  } : null);
  const errorText =
    error instanceof ApiError
      ? ((error.body as { period?: string[] } | null)?.period?.[0] ?? error.message)
      : error
        ? "We could not check the equipment."
        : null;

  function check() {
    if (!shown) return;
    setPeriod({
      starts_at: new Date(shown.starts_at).toISOString(),
      ends_at: new Date(shown.ends_at).toISOString(),
    });
  }

  return (
    <div>
      <Link to="/equipment/availability" className="text-sm text-navy-700 underline">
        ← Choose another event
      </Link>
      <h1 className="mb-1 mt-4 text-2xl font-semibold text-navy-700">Equipment availability</h1>
      {data && <p className="mb-6 text-sm text-slate-600">{data.event.name}</p>}

      <form
        aria-label="Period"
        className="mb-6 flex flex-wrap items-end gap-4 rounded-lg border border-slate-200 bg-white p-4"
        onSubmit={(e) => {
          e.preventDefault();
          check();
        }}
      >
        <label className="text-sm font-medium">
          From
          <input
            type="datetime-local"
            className={`${inputClass} mt-1`}
            value={shown?.starts_at ?? ""}
            onChange={(e) => setDraft({ ends_at: shown?.ends_at ?? "", starts_at: e.target.value })}
          />
        </label>
        <label className="text-sm font-medium">
          To
          <input
            type="datetime-local"
            className={`${inputClass} mt-1`}
            value={shown?.ends_at ?? ""}
            onChange={(e) => setDraft({ starts_at: shown?.starts_at ?? "", ends_at: e.target.value })}
          />
        </label>
        <button
          type="submit"
          disabled={isFetching || !shown?.starts_at || !shown?.ends_at}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
        >
          Check availability
        </button>
      </form>

      {isFetching && <p className="text-slate-500">Checking equipment…</p>}
      {errorText && !isFetching && (
        <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {errorText}
        </p>
      )}

      {data && !isFetching && (
        <>
          <p className="mb-3 text-sm text-slate-600">
            {when(data.period.starts_at)} – {when(data.period.ends_at)}
          </p>
          {data.shortfalls.length > 0 && (
            <section
              aria-label="Shortfalls"
              className="mb-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900"
            >
              <p className="font-medium">Not enough equipment for this event:</p>
              <ul className="mt-1 list-disc pl-5">
                {data.shortfalls.map((s) => (
                  <li key={s.name}>
                    {s.name}: requested {s.requested}, short by {s.short_by}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">Equipment</th>
                  <th className="px-4 py-3">Total</th>
                  <th className="px-4 py-3">Out of action</th>
                  <th className="px-4 py-3">Reserved by other events</th>
                  <th className="px-4 py-3">Available</th>
                  <th className="px-4 py-3">Requested</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.equipment.map((row) => (
                  <tr key={row.equipment_type} aria-label={row.name}>
                    <td className="px-4 py-3 font-medium text-navy-700">
                      {row.name}
                      {!row.in_service && (
                        <span className="block text-xs font-normal text-slate-500">
                          No longer offered
                        </span>
                      )}
                      <OutOfAction row={row} />
                    </td>
                    <td className="px-4 py-3">{row.total_quantity}</td>
                    <td className="px-4 py-3">{row.unavailable_quantity}</td>
                    <td className="px-4 py-3">
                      {row.reserved_for_other_events}
                      {(row.reserved_for_other_events > 0 || row.unavailable_quantity > 0) && (
                        <button
                          type="button"
                          onClick={() => setSelected(row.equipment_type)}
                          className="mt-1 block text-xs text-navy-700 underline"
                          aria-label={`See who is holding ${row.name}`}
                        >
                          See who is holding it
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3 font-semibold">{row.available_quantity}</td>
                    <td className="px-4 py-3">
                      {row.requested_quantity ?? "—"}
                      {row.reserved_for_this_event > 0 && (
                        <span className="block text-xs text-slate-500">
                          {row.reserved_for_this_event} already reserved for this event
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[row.status]}`}
                      >
                        {STATUS_LABEL[row.status]}
                      </span>
                      {row.shortfall > 0 && (
                        <span className="mt-1 block text-xs font-semibold text-rose-800">
                          Short by {row.shortfall}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {selected !== null && (
            <EquipmentHoldersPanel
              key={`${selected}-${data.period.starts_at}-${data.period.ends_at}`}
              eventId={eventId}
              equipmentTypeId={selected}
              period={data.period}
              onClose={() => setSelected(null)}
            />
          )}
        </>
      )}
    </div>
  );
}
