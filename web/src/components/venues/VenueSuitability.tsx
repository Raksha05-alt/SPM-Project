import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getEventSuitability } from "../../api/suitability";
import { inputClass } from "../Field";

const WHEELCHAIR = "Wheelchair access";

/** Split "Hearing loop, Braille signage" into clean, de-duplicated names. */
export function parseFacilities(text: string, wheelchair: boolean): string[] {
  const names = text
    .split(",")
    .map((n) => n.trim())
    .filter(Boolean);
  if (wheelchair) names.unshift(WHEELCHAIR);
  const seen = new Set<string>();
  return names.filter((n) => {
    const key = n.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * SCRUM-71 - tell the coordinator which venues do not appear suitable for the
 * event, and why. The API applies the rules; this only displays them.
 */
export function VenueSuitability({ eventId }: { eventId: number }) {
  const [wheelchair, setWheelchair] = useState(false);
  const [otherFacilities, setOtherFacilities] = useState("");
  const [facilities, setFacilities] = useState<string[] | null>(null);

  const { data, isFetching, isError } = useQuery({
    queryKey: ["venue-suitability", eventId, facilities],
    queryFn: () => getEventSuitability(eventId, facilities ?? []),
    enabled: facilities !== null,
  });

  return (
    <section
      aria-label="Venue suitability"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="mb-1 text-sm font-semibold text-navy-700">Venue suitability</h2>
      <p className="mb-4 text-xs text-slate-500">
        Checks attendance, room layout, accessibility and operating hours. It does not check
        whether a venue is free.
      </p>

      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-medium">Required accessibility facilities</legend>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={wheelchair}
            onChange={(e) => setWheelchair(e.target.checked)}
          />
          Step-free wheelchair access
        </label>
        <div>
          <label htmlFor="other-facilities" className="mb-1 block text-xs text-slate-600">
            Other facilities (comma separated)
          </label>
          <input
            id="other-facilities"
            className={inputClass}
            value={otherFacilities}
            onChange={(e) => setOtherFacilities(e.target.value)}
            placeholder="Hearing loop"
          />
        </div>
      </fieldset>

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => setFacilities(parseFacilities(otherFacilities, wheelchair))}
          disabled={isFetching}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
        >
          Check venues
        </button>
      </div>

      {isFetching && <p className="mt-4 text-sm text-slate-500">Checking venues…</p>}
      {isError && !isFetching && (
        <p role="alert" className="mt-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          We could not check the venues. Try again.
        </p>
      )}

      {data && !isFetching && (
        <>
          {data.venues.length === 0 ? (
            <p className="mt-4 text-sm text-slate-500">No venues have been recorded yet.</p>
          ) : (
            <ul className="mt-4 divide-y divide-slate-100">
              {data.venues.map((v) => (
                <li key={v.venue} className="py-3" aria-label={v.venue_name}>
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-sm font-medium text-slate-800">{v.venue_name}</span>
                    {v.suitable ? (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800">
                        Suitable
                      </span>
                    ) : (
                      <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-800">
                        Not suitable
                      </span>
                    )}
                  </div>
                  {v.reasons.length > 0 && (
                    <ul className="mt-2 list-disc pl-5 text-sm text-rose-800">
                      {v.reasons.map((r) => (
                        <li key={r.message}>{r.message}</li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
