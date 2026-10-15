import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { createVenue, listVenues, updateVenue, type VenueInput } from "../api/venues";
import { VenueForm } from "../components/venues/VenueForm";
import type { Venue } from "../types";

type Editing = { venue: Venue | null } | null;

/**
 * SCRUM-9 - the catalogue of ConnectSphere venues.
 * SCRUM-65 - Venue Staff create and update them here.
 */
export function VenueCatalogue() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({ queryKey: ["venues"], queryFn: listVenues });
  const [editing, setEditing] = useState<Editing>(null);
  const [saved, setSaved] = useState<Venue | null>(null);

  const save = useMutation({
    mutationFn: (input: VenueInput) =>
      editing?.venue ? updateVenue(editing.venue.id, input) : createVenue(input),
    onSuccess: (venue) => {
      setSaved(venue);
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: ["venues"] });
    },
  });

  function open(venue: Venue | null) {
    save.reset();
    setSaved(null);
    setEditing({ venue });
  }

  if (isLoading) return <p className="text-slate-500">Loading venues…</p>;
  if (isError) return <p role="alert">We could not load the venues.</p>;

  const rows = data ?? [];

  return (
    <div>
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold text-navy-700">Venues</h1>
        <button
          type="button"
          onClick={() => open(null)}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white"
        >
          Add venue
        </button>
      </div>

      {saved && (
        <div role="status" className="mb-6 rounded-md bg-emerald-50 p-4 text-sm text-emerald-800">
          <p>
            Saved {saved.name}
            {saved.updated_by_name ? ` by ${saved.updated_by_name}` : ""} at{" "}
            {new Date(saved.updated_at).toLocaleString("en-SG")}.
          </p>
        </div>
      )}

      {editing && (
        <div className="mb-8">
          <VenueForm
            key={editing.venue?.id ?? "new"}
            venue={editing.venue}
            saving={save.isPending}
            error={save.error}
            onSave={(input) => save.mutate(input)}
            onCancel={() => setEditing(null)}
          />
        </div>
      )}

      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          No venues yet. Add the first one.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Venue</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">Capacity</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Last updated</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {rows.map((venue) => (
                <tr key={venue.id}>
                  <td className="px-4 py-3 font-medium text-navy-700">
                    <Link to={`/venues/${venue.id}`} className="hover:underline">
                      {venue.name}
                    </Link>
                    {venue.missing_information.length > 0 && (
                      <p className="text-xs font-normal text-amber-700">
                        {venue.missing_information.length} detail
                        {venue.missing_information.length === 1 ? "" : "s"} not provided
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">{venue.location || "—"}</td>
                  <td className="px-4 py-3">{venue.capacity}</td>
                  <td className="px-4 py-3">{venue.operational_status}</td>
                  <td className="px-4 py-3 text-slate-500">
                    {new Date(venue.updated_at).toLocaleString("en-SG")}
                    {venue.updated_by_name ? ` by ${venue.updated_by_name}` : ""}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => open(venue)}
                      className="text-navy-700 underline"
                      aria-label={`Edit ${venue.name}`}
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
