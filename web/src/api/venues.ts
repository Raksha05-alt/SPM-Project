import { request } from "./client";

/** A layout code from the catalogue (Week 7 clarification), e.g. "THEATRE". */
export type VenueLayout = string;

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
  /** Week 7 change 1 - minutes before and after each booking. */
  setup_minutes: number;
  turnaround_minutes: number;
  /** Week 7 change 6 - emergency access and known restrictions. */
  safety_notes: string;
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
  setup_minutes: number;
  turnaround_minutes: number;
  safety_notes: string;
  is_active: boolean;
}

/** What saving a venue reports back (Week 7 changes 1 and 2). */
export interface SavedVenue extends Venue {
  disrupted_bookings?: VenueBooking[];
  flagged_bookings?: VenueBooking[];
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

/** Week 7 change 2 - why a venue is temporarily unavailable. */
export type BlockCategory =
  | "MAINTENANCE"
  | "EQUIPMENT_FAILURE"
  | "RENOVATION"
  | "SAFETY"
  | "INTERNAL"
  | "OTHER";

export interface VenueBlock {
  id: number;
  venue: number;
  venue_name: string;
  start: string;
  end: string;
  category?: BlockCategory;
  category_label?: string;
  reason: string;
  /** Present on a newly created block: the bookings it disrupted. */
  affected_bookings?: VenueBooking[];
  created_by_name: string | null;
  created_at: string;
  updated_by_name: string | null;
  updated_at: string;
}

export interface BlockInput {
  start: string;
  end: string;
  category?: BlockCategory;
  reason: string;
}

export type SegmentStatus =
  | "AVAILABLE"
  | "REQUESTED"
  | "TENTATIVE"
  | "CONFIRMED"
  | "BLOCKED"
  | "UNAVAILABLE";

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

export type BookingStatus =
  | "PENDING"
  | "HELD"
  | "APPROVED"
  | "REJECTED"
  | "WITHDRAWN"
  | "RELEASED"
  | "EXPIRED"
  | "DISRUPTED";

/** SCRUM-69 - a booking of another event that overlaps this one, including
 * setup and turnaround time (Week 7 change 1). */
export interface BookingConflict {
  booking: number;
  event: number;
  event_name: string;
  session_name?: string;
  status?: string;
  start: string;
  end: string;
  occupied_from?: string;
  occupied_until?: string;
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
  occupied_from?: string;
  occupied_until?: string;
  setup_minutes?: number;
  turnaround_minutes?: number;
  session_name?: string;
  attendance: number;
  layout: string;
  layout_label: string;
  facilities: string[];
  accessibility_needs: string;
  notes: string;
  status: BookingStatus;
  status_display: string;
  coordinator_name?: string | null;
  hold_expires_at?: string | null;
  hold_set_by_name?: string | null;
  hold_expired?: boolean;
  disrupted_at?: string | null;
  disruption_reason?: string;
  buffer_warnings?: string[];
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
  request<SavedVenue>(`/api/venues/${id}/`, {
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

/** SCRUM-72 / Week 7 change 4 - give ``holdUntil`` to approve as a tentative hold. */
export const approveBooking = (id: number, holdUntil?: string | null) =>
  request<VenueBooking>(`/api/venue-bookings/${id}/approve/`, {
    method: "POST",
    body: holdUntil ? { hold_until: holdUntil } : {},
  });

/** Week 7 change 4 - Venue Staff change when a hold expires. */
export const updateHold = (id: number, holdUntil: string) =>
  request<VenueBooking>(`/api/venue-bookings/${id}/update-hold/`, {
    method: "POST",
    body: { hold_until: holdUntil },
  });

export const listBookingsByStatus = (statuses: BookingStatus[]) =>
  request<VenueBooking[]>(`/api/venue-bookings/?status=${statuses.join(",")}`);

export const rejectBooking = (id: number, input: RejectInput) =>
  request<VenueBooking>(`/api/venue-bookings/${id}/reject/`, { method: "POST", body: input });

export const reviewBooking = (id: number, input: ReviewInput) =>
  request<VenueBooking>(`/api/venue-bookings/${id}/review/`, { method: "POST", body: input });
