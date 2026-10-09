import { request } from "./client";

export type VenueLayout = "CLASSROOM" | "THEATRE" | "BOARDROOM" | "BANQUET" | "EXHIBITION";

export interface Venue {
  id: number;
  name: string;
  location: string;
  capacity: number;
  facilities: string[];
  layouts: VenueLayout[];
  layout_labels: string[];
  wheelchair_access: boolean | null;
  accessibility_notes: string;
  opens_at: string | null;
  closes_at: string | null;
  operating_days: number[];
  operating_hours: string | null;
  is_active: boolean;
  operational_status: string;
  missing_information: string[];
  updated_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface VenueInput {
  name: string;
  location: string;
  capacity: number | null;
  facilities: string[];
  layouts: VenueLayout[];
  wheelchair_access: boolean | null;
  accessibility_notes: string;
  opens_at: string | null;
  closes_at: string | null;
  operating_days: number[];
  is_active: boolean;
}

/** SCRUM-5 AC4 - a confirmed booking that relies on a layout being removed. */
export interface AffectedBooking {
  id: number;
  event: number;
  event_name: string;
  layout: string;
  start: string;
  end: string;
}

export interface VenueBlock {
  id: number;
  venue: number;
  venue_name: string;
  start: string;
  end: string;
  reason: string;
  created_by_name: string | null;
  created_at: string;
  updated_by_name: string | null;
  updated_at: string;
}

export interface BlockInput {
  start: string;
  end: string;
  reason: string;
}

export type SegmentStatus = "AVAILABLE" | "TENTATIVE" | "CONFIRMED" | "BLOCKED" | "UNAVAILABLE";

export interface AvailabilitySegment {
  start: string;
  end: string;
  status: SegmentStatus;
  label: string;
  detail: string;
  event: number | null;
  event_name: string | null;
}

export interface VenueAvailability {
  venue: number;
  venue_name: string;
  start: string;
  end: string;
  segments: AvailabilitySegment[];
}

export type BookingStatus = "PENDING" | "APPROVED" | "REJECTED" | "WITHDRAWN" | "RELEASED";

/** SCRUM-69 - a confirmed booking of another event that overlaps this one. */
export interface BookingConflict {
  booking: number;
  event: number;
  event_name: string;
  start: string;
  end: string;
}

export interface VenueBooking {
  id: number;
  event: number;
  event_name: string;
  event_status: string;
  venue: number;
  venue_name: string;
  start: string;
  end: string;
  attendance: number;
  layout: string;
  layout_label: string;
  facilities: string[];
  accessibility_needs: string;
  notes: string;
  status: BookingStatus;
  status_display: string;
  requested_by_name: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  rejection_reason: string;
  suggested_venue: number | null;
  suggested_venue_name: string | null;
  suggested_start: string | null;
  suggested_end: string | null;
  suggestion_note: string;
  withdrawn_by_name: string | null;
  withdrawn_at: string | null;
  review_required: boolean;
  review_reason: string;
  review_start: string | null;
  review_end: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_outcome: string;
  conflicts: BookingConflict[];
  created_at: string;
}

export interface RejectInput {
  reason: string;
  suggested_venue?: number | null;
  suggested_start?: string | null;
  suggested_end?: string | null;
  suggestion_note?: string;
  acknowledge_warning?: boolean;
}

export interface ReviewInput {
  accommodated: boolean;
  note: string;
  start?: string | null;
  end?: string | null;
}

export const listVenues = () => request<Venue[]>("/api/venues/");

export const getVenue = (id: number) => request<Venue>(`/api/venues/${id}/`);

export const createVenue = (input: VenueInput) =>
  request<Venue>("/api/venues/", { method: "POST", body: input });

export const updateVenue = (id: number, input: VenueInput, confirmLayoutRemoval = false) =>
  request<Venue>(`/api/venues/${id}/`, {
    method: "PATCH",
    body: confirmLayoutRemoval ? { ...input, confirm_layout_removal: true } : input,
  });

export const listBlocks = (venueId: number) =>
  request<VenueBlock[]>(`/api/venues/${venueId}/blocks/`);

export const createBlock = (venueId: number, input: BlockInput) =>
  request<VenueBlock>(`/api/venues/${venueId}/blocks/`, { method: "POST", body: input });

export const updateBlock = (id: number, input: BlockInput) =>
  request<VenueBlock>(`/api/venue-blocks/${id}/`, { method: "PATCH", body: input });

export const deleteBlock = (id: number) =>
  request<void>(`/api/venue-blocks/${id}/`, { method: "DELETE" });

export const getAvailability = (venueId: number, start: string, end: string) =>
  request<VenueAvailability>(
    `/api/venues/${venueId}/availability/?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  );

export const listBookings = (status: BookingStatus) =>
  request<VenueBooking[]>(`/api/venue-bookings/?status=${status}`);

export const approveBooking = (id: number) =>
  request<VenueBooking>(`/api/venue-bookings/${id}/approve/`, { method: "POST" });

export const rejectBooking = (id: number, input: RejectInput) =>
  request<VenueBooking>(`/api/venue-bookings/${id}/reject/`, { method: "POST", body: input });

export const reviewBooking = (id: number, input: ReviewInput) =>
  request<VenueBooking>(`/api/venue-bookings/${id}/review/`, { method: "POST", body: input });
