import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getEventSuitability } from "../../api/suitability";
import { inputClass } from "../Field";
import type { SuitabilityRequirements } from "../../types";

/** Split "Hearing loop, Stage" into clean names, dropping blanks and repeats (any case). */
export function parseFacilities(text: string): string[] {
  const seen = new Set<string>();
  return text
    .split(",")
    .map((n) => n.trim())
    .filter((n) => {
      const key = n.toLowerCase();
      if (!n || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

type Request = { facilities: string[]; wheelchair: boolean };

function describeRequirements(r: SuitabilityRequirements): string {
  const parts = [
    r.attendance !== null ? `${r.attendance} attendees` : "attendance not set",
    r.layout_name ? `${r.layout_name} layout` : "no layout preference",
  ];
  if (r.wheelchair_access_required) parts.push("wheelchair access");
  if (r.required_facilities.length) parts.push(r.required_facilities.join(", "));
  return parts.join(" · ");
}

/**
 * SCRUM-71 - tell the assigned coordinator which venues do not appear suitable
 * for the event, and why. The API applies the rules; this only displays them.
 */
export function VenueSuitability({ eventId }: { eventId: number }) {
  const [wheelchair, setWheelchair] = useState(false);
  const [facilityText, setFacilityText] = useState("");
  const [asked, setAsked] = useState<Request | null>(null);

  const { data, isFetching, isError } = useQuery({
    queryKey: ["venue-suitability", eventId, asked],
    queryFn: () => getEventSuitability(eventId, asked!.facilities, asked!.wheelchair),
    enabled: asked !== null,
  });

  return (
    <section
      aria-label="Venue suitability"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="mb-1 text-sm font-semibold text-navy-700">Venue suitability</h2>
      <p className="mb-4 text-xs text-slate-500">
        Checks attendance against capacity, the room layout, accessibility, required facilities
        and operating hours.
      </p>

      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-medium">What the venue must also provide</legend>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={wheelchair}
            onChange={(e) => setWheelchair(e.target.checked)}
          />
          Step-free wheelchair access
        </label>
        <div>
          <label htmlFor="required-facilities" className="mb-1 block text-xs text-slate-600">
            Required facilities (comma separated)
          </label>
          <input
            id="required-facilities"
            className={inputClass}
            value={facilityText}
            onChange={(e) => setFacilityText(e.target.value)}
            placeholder="Hearing loop, Stage"
          />
        </div>
      </fieldset>

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => setAsked({ facilities: parseFacilities(facilityText), wheelchair })}
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
          <p className="mt-4 text-xs text-slate-600">
            Checked against: {describeRequirements(data.requirements)}
          </p>
          {data.venues.length === 0 ? (
            <p className="mt-4 text-sm text-slate-500">No venues have been recorded yet.</p>
          ) : (
            <ul className="mt-2 divide-y divide-slate-100">
              {data.venues.map((v) => (
                <li key={v.venue} className="py-3" aria-label={v.venue_name}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium text-slate-800">{v.venue_name}</span>
                    <span className="flex gap-2">
                      {!v.in_service && (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                          Out of service
                        </span>
                      )}
                      {v.suitable ? (
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800">
                          Suitable
                        </span>
                      ) : (
                        <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-800">
                          Not suitable
                        </span>
                      )}
                    </span>
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
          <div role="note" className="mt-4 rounded-md bg-slate-50 p-3 text-xs text-slate-600">
            <p className="font-medium">Not checked here:</p>
            <ul className="mt-1 list-disc pl-5">
              {data.not_checked.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </div>
        </>
      )}
    </section>
  );
}
