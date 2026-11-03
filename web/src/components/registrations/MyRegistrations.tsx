import { useQuery } from "@tanstack/react-query";
import { listMyRegistrations } from "../../api/registrations";

function when(value: string | null) {
  return value ? new Date(value).toLocaleString("en-SG") : "To be confirmed";
}

/** SCRUM-21 AC4 - my registered events, with status and confirmed date, time and venue. */
export function MyRegistrations() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["my-registrations"],
    queryFn: listMyRegistrations,
  });

  if (isLoading) return null;
  if (isError) return <p role="alert">We could not load your registrations.</p>;
  const rows = data ?? [];

  return (
    <section aria-label="My registrations" className="mb-8">
      <h2 className="mb-2 text-lg font-semibold text-navy-700">My registrations</h2>
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-4 text-sm text-slate-500">
          You have not registered for any events yet.
        </p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white text-sm">
          {rows.map((row) => (
            <li key={row.id} className="px-4 py-3">
              <p className="font-medium text-navy-700">{row.event_name}</p>
              <p>
                {row.status_label} · {row.event_details.status_label}
              </p>
              <p className="text-slate-600">
                {when(row.event_details.starts_at)} to {when(row.event_details.ends_at)}
              </p>
              <p className="text-slate-600">
                {row.event_details.venues.length > 0
                  ? row.event_details.venues.map((v) => `${v.venue}, ${v.location}`).join("; ")
                  : "Venue to be confirmed"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
