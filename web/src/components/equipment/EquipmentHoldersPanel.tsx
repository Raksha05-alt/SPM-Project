import { useQuery } from "@tanstack/react-query";
import { getEquipmentHolders } from "../../api/equipment";

function when(iso: string) {
  return new Date(iso).toLocaleString("en-SG");
}

/**
 * SCRUM-76 - the events holding one equipment type during the period (AC1),
 * and why any stock is out of action (AC2). What each holder shows is decided
 * by the API for the viewer's role (AC3): Technical Support see the event and
 * its coordinator; the event's coordinator sees only quantities and dates.
 */
export function EquipmentHoldersPanel({
  eventId,
  equipmentTypeId,
  period,
  onClose,
}: {
  eventId: number;
  equipmentTypeId: number;
  period: { starts_at: string; ends_at: string };
  onClose: () => void;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["equipment-holders", eventId, equipmentTypeId, period],
    queryFn: () => getEquipmentHolders(eventId, equipmentTypeId, period),
  });

  return (
    <section
      aria-label="Holding events"
      className="mt-4 rounded-lg border border-slate-200 bg-white p-5"
    >
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-navy-700">
          {data ? `Who is holding ${data.availability.name}` : "Who is holding this equipment"}
        </h2>
        <button type="button" onClick={onClose} className="text-sm text-navy-700 underline">
          Close
        </button>
      </div>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {isError && (
        <p role="alert" className="text-sm text-rose-800">
          We could not load who is holding this equipment.
        </p>
      )}

      {data && (
        <>
          {data.holders.length === 0 ? (
            <p className="text-sm text-slate-600">
              No other event has this equipment reserved for the period.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.holders.map((h) => (
                <li key={h.reservation} className="py-2 text-sm">
                  {h.event ? (
                    <>
                      <span className="font-medium text-slate-800">{h.event.name}</span>
                      <span className="text-slate-500"> · {h.event.status_label}</span>
                      {h.event.coordinator && (
                        <span className="block text-xs text-slate-600">
                          Coordinator: {h.event.coordinator.name} ·{" "}
                          <a className="underline" href={`mailto:${h.event.coordinator.email}`}>
                            {h.event.coordinator.email}
                          </a>
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="font-medium text-slate-800">Reserved by another event</span>
                  )}
                  <span className="block text-xs text-slate-600">
                    {h.quantity} held · {when(h.starts_at)} – {when(h.ends_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {data.availability.unavailable.length > 0 && (
            <div className="mt-4">
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Out of action
              </h3>
              <ul className="space-y-1 text-sm">
                {data.availability.unavailable.map((u, i) => (
                  <li key={i}>
                    {u.quantity} {u.cause_label.toLowerCase()}: {u.reason} ·{" "}
                    {u.expected_return_at
                      ? `expected back ${when(u.expected_return_at)}`
                      : "return date not recorded"}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
