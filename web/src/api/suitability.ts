import { request } from "./client";
import type { EventSuitability } from "../types";

/** SCRUM-71 - check every venue against an event's requirements. */
export function getEventSuitability(eventId: number, facilities: string[] = []) {
  const query = facilities.length
    ? `?${facilities.map((f) => `facilities=${encodeURIComponent(f)}`).join("&")}`
    : "";
  return request<EventSuitability>(`/api/events/${eventId}/venue-suitability/${query}`);
}
