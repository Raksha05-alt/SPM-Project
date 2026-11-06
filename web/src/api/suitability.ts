import { request } from "./client";
import type { EventSuitability } from "../types";

/** SCRUM-71 - check every venue against an event's requirements. */
export function getEventSuitability(
  eventId: number,
  facilities: string[] = [],
  wheelchair = false,
) {
  const params = new URLSearchParams();
  facilities.forEach((f) => params.append("facilities", f));
  if (wheelchair) params.set("wheelchair", "true");
  const query = params.toString();
  return request<EventSuitability>(
    `/api/events/${eventId}/venue-suitability/${query ? `?${query}` : ""}`,
  );
}
