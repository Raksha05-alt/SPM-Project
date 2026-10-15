import { request } from "./client";
import type { Venue } from "../types";

export type VenueInput = Omit<
  Venue,
  | "id"
  | "layout_labels"
  | "operating_hours"
  | "created_by_name"
  | "updated_by_name"
  | "created_at"
  | "updated_at"
>;

export const listVenues = () => request<Venue[]>("/api/venues/");

export const createVenue = (venue: VenueInput) =>
  request<Venue>("/api/venues/", { method: "POST", body: venue });

export const updateVenue = (id: number, venue: Partial<VenueInput>) =>
  request<Venue>(`/api/venues/${id}/`, { method: "PATCH", body: venue });
