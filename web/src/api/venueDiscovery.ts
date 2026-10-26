import { request } from "./client";
import type { Venue } from "../types";

export interface VenueSearchCriteria {
  start?: string;
  end?: string;
  attendance?: number;
  layout?: string;
  facilities?: string[];
}

export interface VenueCriterion {
  key: string;
  label: string;
  result: "MATCH" | "UNMET" | "UNVERIFIED";
  message: string;
}

export interface VenueMatch {
  venue: Venue;
  criteria: VenueCriterion[];
  matches_recorded_requirements: boolean;
  availability_status: "UNAVAILABLE" | "UNVERIFIED";
}

export interface VenueSearchResult {
  results: VenueMatch[];
  criteria: VenueSearchCriteria;
  availability_integrated: boolean;
  date_blocks_integrated: boolean;
  limitation: string;
}

export interface ShortlistEntry {
  id: number;
  created_at: string;
  search_criteria: VenueSearchCriteria;
  match: VenueMatch;
}

export interface EventShortlist {
  event_id: number;
  can_edit: boolean;
  entries: ShortlistEntry[];
  availability_integrated: boolean;
  date_blocks_integrated: boolean;
  limitation: string;
}

export function searchVenues(criteria: VenueSearchCriteria): Promise<VenueSearchResult> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(criteria)) {
    if (Array.isArray(value)) value.forEach((item) => params.append(key, item));
    else if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return request<VenueSearchResult>(`/api/venues/search/?${params}`);
}

export const getVenueShortlist = (eventId: number) =>
  request<EventShortlist>(`/api/events/${eventId}/venue-shortlist/`);

export const addVenueToShortlist = (
  eventId: number,
  venueId: number,
  criteria: VenueSearchCriteria,
) =>
  request<ShortlistEntry>(`/api/events/${eventId}/venue-shortlist/`, {
    method: "POST",
    body: { venue_id: venueId, criteria },
  });

export const removeVenueFromShortlist = (eventId: number, venueId: number) =>
  request<void>(`/api/events/${eventId}/venue-shortlist/${venueId}/`, { method: "DELETE" });
