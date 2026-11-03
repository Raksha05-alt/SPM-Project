import { useQuery } from "@tanstack/react-query";
import { getConfirmedArrangements } from "../../api/confirmation";

function when(value: string) {
  return new Date(value).toLocaleString("en-SG");
}

/** SCRUM-58 AC5 - the Event Organiser sees the confirmed arrangements. */
export function ConfirmedArrangementsPanel({ eventId }: { eventId: number }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["confirmed-arrangements", eventId],
    queryFn: () => getConfirmedArrangements(eventId),
  });

  if (isLoading) return <p className="text-slate-500">Loading the confirmed arrangements…</p>;
  if (isError || !data) return <p role="alert">We could not load the confirmed arrangements.</p>;

  return (
    <section
      aria-label="Confirmed arrangements"
      className="mb-6 rounded-lg border border-green-200 bg-green-50 p-6 text-sm"
    >
      <h2 className="mb-2 text-lg font-semibold text-green-900">Confirmed arrangements</h2>
      {data.confirmed_at && (
        <p className="mb-3 text-green-900">
          Confirmed by {data.confirmed_by_name} on {when(data.confirmed_at)}.
        </p>
      )}
      <h3 className="font-medium">Venue</h3>
      <ul className="mb-3 list-inside list-disc">
        {data.venues.map((v) => (
          <li key={`${v.venue}-${v.starts_at}`}>
            {v.venue}, {v.location}: {when(v.starts_at)} to {when(v.ends_at)}, {v.attendance}{" "}
            people{v.layout ? `, ${v.layout}` : ""}
          </li>
        ))}
      </ul>
      <h3 className="font-medium">Equipment</h3>
      {data.equipment.length === 0 ? (
        <p className="mb-3">No equipment required.</p>
      ) : (
        <ul className="mb-3 list-inside list-disc">
          {data.equipment.map((e) => (
            <li key={e.equipment}>
              {e.quantity} × {e.equipment}
            </li>
          ))}
        </ul>
      )}
      {data.safety_approved_at && (
        <p>Operational safety check approved on {when(data.safety_approved_at)}.</p>
      )}
    </section>
  );
}
