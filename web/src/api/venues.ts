import { request } from "./client";
import type { Venue } from "../types";

export type VenueInput = Omit<
  Venue,
  | "id"
  | "layout_labels"
  | "operating_hours"
  | "operational_status"
  | "missing_information"
  | "created_by_name"
  | "updated_by_name"
  | "created_at"
  | "updated_at"
> & {
  /** INT-02 - remove a layout even though approved bookings use it. */
  confirm_layout_removal?: boolean;
};

/** INT-02 - one approved booking that uses a layout being removed (409 body). */
export type AffectedBooking = {
  booking: number;
  event: number;
  event_name: string;
  layout: string;
  layout_name: string;
  starts_at: string;
  ends_at: string;
};

export const listVenues = () => request<Venue[]>("/api/venues/");

/** SCRUM-5 AC3 - only the venues that have recorded this layout as supported. */
export const listVenuesSupportingLayout = (layout: string) =>
  request<Venue[]>(`/api/venues/?layout=${encodeURIComponent(layout)}`);

export const getVenue = (id: number) => request<Venue>(`/api/venues/${id}/`);

export const createVenue = (venue: VenueInput) =>
  request<Venue>("/api/venues/", { method: "POST", body: venue });

export const updateVenue = (id: number, venue: Partial<VenueInput>) =>
  request<Venue>(`/api/venues/${id}/`, { method: "PATCH", body: venue });
