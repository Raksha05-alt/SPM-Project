import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchAvailability,
  fetchHolders,
  listEquipmentRequests,
  type AvailabilityPeriod,
  type AvailabilityRow,
} from "../../api/equipment";
import { Field, inputClass } from "../../components/Field";
import { EquipmentNav } from "./EquipmentRequests";

function formatDateTime(value: string) {
  return new Date(value).toLocaleString("en-SG");
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString("en-SG");
}

/** SCRUM-76 - the events holding a piece of equipment, and why any is out of service. */
function Holders({ row, period }: { row: AvailabilityRow; period: AvailabilityPeriod }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["equipment-holders", row.equipment, period],
    queryFn: () => fetchHolders(row.equipment, period),
  });

  if (isLoading) return <p className="text-sm text-slate-500">Loading who holds it…</p>;
  if (error)
    return (
      <p role="alert" className="text-sm text-rose-800">
        {error.message}
      </p>
    );
  if (!data) return null;

  return (
    <div aria-label={`Holders of ${data.name}`} className="text-sm text-slate-700">
      {data.holding_events.length === 0 ? (
        <p>No events hold this equipment in the period.</p>
      ) : (
        <ul className="space-y-1">
          {data.holding_events.map((h, index) => (
            <li key={`${h.event}-${index}`}>
              <span className="font-medium">{h.event_name}</span> ({h.event_status}) holds{" "}
              {h.quantity}, {formatDateTime(h.start)} – {formatDateTime(h.end)}
              {h.coordinator_name && <> · coordinator {h.coordinator_name}</>}
            </li>
          ))}
        </ul>
      )}
      {data.out_of_service_quantity > 0 && (
        <p className="mt-2">
          {data.out_of_service_quantity} out of service
          {data.out_of_service_reason && <>: {data.out_of_service_reason}</>}
          {data.expected_return && <> · expected back {formatDate(data.expected_return)}</>}
        </p>
      )}
    </div>
  );
}

export function EquipmentAvailability() {
  const [mode, setMode] = useState<"event" | "period">("event");
  const [eventId, setEventId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [period, setPeriod] = useState<AvailabilityPeriod | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  // Events to choose from: those with equipment requests.
  const { data: requests } = useQuery({
    queryKey: ["equipment-requests"],
    queryFn: () => listEquipmentRequests(),
  });
  const events = new Map<number, string>();
  for (const r of requests ?? []) events.set(r.event, r.event_name);

  const availability = useQuery({
    queryKey: ["equipment-availability", period],
    queryFn: () => fetchAvailability(period as AvailabilityPeriod),
    enabled: period !== null,
  });

  function check(e: React.FormEvent) {
    e.preventDefault();
    setSelected(null);
    if (mode === "event") {
      if (!eventId) {
        setFormError("Choose an event.");
        return;
      }
      setFormError(null);
      setPeriod({ event: Number(eventId) });
      return;
    }
    if (!start || !end) {
      setFormError("Enter both a start and an end.");
      return;
    }
    if (new Date(end) <= new Date(start)) {
      setFormError("The end must be after the start.");
      return;
    }
    setFormError(null);
    setPeriod({ start: new Date(start).toISOString(), end: new Date(end).toISOString() });
  }

  const data = availability.data;
  const forEvent = data?.event != null;

  return (
    <div>
      <EquipmentNav />
      <h1 className="mb-6 text-2xl font-semibold text-navy-700">Equipment availability</h1>

      <form
        onSubmit={check}
        noValidate
        className="mb-6 rounded-lg border border-slate-200 bg-white p-6"
      >
        <fieldset className="mb-4 flex gap-6 text-sm">
          <legend className="mb-2 font-medium text-slate-700">Check availability for</legend>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="mode"
              checked={mode === "event"}
              onChange={() => setMode("event")}
            />
            An event
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="mode"
              checked={mode === "period"}
              onChange={() => setMode("period")}
            />
            A period
          </label>
        </fieldset>

        {mode === "event" ? (
          <Field label="Event" htmlFor="availability-event">
            <select
              id="availability-event"
              className={inputClass}
              value={eventId}
              onChange={(e) => setEventId(e.target.value)}
            >
              <option value="">Choose an event</option>
              {[...events.entries()].map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Start" htmlFor="availability-start">
              <input
                id="availability-start"
                type="datetime-local"
                className={inputClass}
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </Field>
            <Field label="End" htmlFor="availability-end">
              <input
                id="availability-end"
                type="datetime-local"
                className={inputClass}
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </Field>
          </div>
        )}

        {formError && (
          <p role="alert" className="mb-4 text-xs font-medium text-rose-700">
            {formError}
          </p>
        )}
        <div className="flex justify-end">
          <button
            type="submit"
            className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600"
          >
            Check availability
          </button>
        </div>
      </form>

      {availability.isFetching && <p className="text-slate-500">Checking availability…</p>}
      {availability.error && (
        <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {availability.error.message}
        </p>
      )}

      {data && (
        <section className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-6">
          <p className="mb-3 text-sm text-slate-600">
            {formatDateTime(data.start)} – {formatDateTime(data.end)}
          </p>
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-2">Equipment</th>
                <th>Total</th>
                <th>Out of service</th>
                <th>Reserved elsewhere</th>
                <th>Available</th>
                {forEvent && <th>Requested</th>}
                {forEvent && <th>Shortfall</th>}
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.results.map((row) => {
                const short = (row.shortfall ?? 0) > 0;
                const unavailable = row.available_quantity === 0 || short;
                return (
                  <tr key={row.equipment} className="border-t border-slate-100 align-top">
                    <td className="py-2">
                      <span className="font-medium text-slate-800">{row.name}</span>
                      <span className="block text-xs text-slate-500">{row.category}</span>
                      {selected === row.equipment && period && (
                        <div className="mt-2">
                          <Holders row={row} period={period} />
                        </div>
                      )}
                    </td>
                    <td>{row.total_quantity}</td>
                    <td>{row.out_of_service_quantity}</td>
                    <td>{row.reserved_for_other_events}</td>
                    <td className="font-medium">{row.available_quantity}</td>
                    {forEvent && <td>{row.requested_quantity ?? 0}</td>}
                    {forEvent && (
                      <td className={short ? "font-semibold text-rose-700" : ""}>
                        {row.shortfall ?? 0}
                      </td>
                    )}
                    <td className={unavailable ? "font-semibold text-rose-700" : "text-slate-700"}>
                      {row.status}
                    </td>
                    <td className="text-right">
                      {unavailable && (
                        <button
                          type="button"
                          onClick={() =>
                            setSelected(selected === row.equipment ? null : row.equipment)
                          }
                          className="text-navy-700 underline"
                        >
                          Who holds {row.name}?
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
