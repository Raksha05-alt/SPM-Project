/**
 * Event Coordinator planning: editing, status actions, venues, bookings,
 * equipment, change requests, registrations and change history.
 */
import { request } from "./client";
import type { AssignedEventRow, EventRequest, EventStatus, QueueRow } from "../types";

// --- SCRUM-57 - status filters ------------------------------------------------------

function statusQuery(statuses: EventStatus[]) {
  return statuses.length ? `?status=${statuses.join(",")}` : "";
}

export const fetchQueueByStatus = (statuses: EventStatus[]) =>
  request<QueueRow[]>(`/api/events/queue/${statusQuery(statuses)}`);

export const fetchMyEventsByStatus = (statuses: EventStatus[]) =>
  request<AssignedEventRow[]>(`/api/events/mine/${statusQuery(statuses)}`);

export const STATUS_LABELS: Record<EventStatus, string> = {
  DRAFT: "Draft",
  SUBMITTED: "Submitted",
  UNDER_REVIEW: "Awaiting Clarification",
  APPROVED: "Approved",
  PLANNING: "Planning",
  CONFIRMED: "Confirmed",
  COMPLETED: "Completed",
  CANCELLED: "Cancelled",
  REJECTED: "Rejected",
};

export const LAYOUT_OPTIONS = [
  { value: "CLASSROOM", label: "Classroom" },
  { value: "THEATRE", label: "Theatre" },
  { value: "BOARDROOM", label: "Boardroom" },
  { value: "BANQUET", label: "Banquet" },
  { value: "EXHIBITION", label: "Exhibition" },
];

// --- SCRUM-61 / 59 - editing during planning ----------------------------------------

export type EventPatch = Partial<
  Pick<
    EventRequest,
    | "name"
    | "purpose"
    | "description"
    | "preferred_start"
    | "preferred_end"
    | "expected_attendance"
    | "required_layout"
    | "accessibility_needs"
    | "equipment_notes"
  >
>;

export interface SignificantChange {
  significant: boolean;
  changed_fields: string[];
  affected_arrangements: string[];
}

export type EventUpdateResult = EventRequest & { significant_change?: SignificantChange };

export const updateEvent = (id: number, patch: EventPatch) =>
  request<EventUpdateResult>(`/api/events/${id}/`, { method: "PATCH", body: patch });

// --- SCRUM-56 / 58 / 53 - status actions ---------------------------------------------

export interface MissingArrangement {
  arrangement: string;
  detail: string;
}

export interface Coordinator {
  id: number;
  name: string;
  email: string;
  available: boolean;
}

export const confirmEvent = (id: number) =>
  request<EventRequest>(`/api/events/${id}/confirm/`, { method: "POST" });

export const cancelEvent = (id: number, reason: string) =>
  request<EventRequest>(`/api/events/${id}/cancel/`, { method: "POST", body: { reason } });

export const completeEvent = (id: number) =>
  request<EventRequest>(`/api/events/${id}/complete/`, { method: "POST" });

export const reassignEvent = (id: number, coordinator: number) =>
  request<EventRequest>(`/api/events/${id}/reassign/`, {
    method: "POST",
    body: { coordinator },
  });

export const listCoordinators = () => request<Coordinator[]>("/api/coordinators/");

// --- SCRUM-60 - change history ---------------------------------------------------------

export interface ChangeLogEntry {
  id: number;
  field: string;
  previous_value: string;
  new_value: string;
  changed_by: number | null;
  changed_by_name: string | null;
  changed_at: string;
  significant: boolean;
}

export const fetchHistory = (id: number) =>
  request<ChangeLogEntry[]>(`/api/events/${id}/history/`);

// --- SCRUM-64 / 71 / 62 / 68 - venues ----------------------------------------------------

export interface VenueSearchParams {
  attendance?: number | null;
  layout?: string;
  facilities?: string;
  location?: string;
  wheelchair_access?: boolean;
  start?: string | null;
  end?: string | null;
}

export interface VenueCheck {
  criterion: string;
  matches: boolean;
  reason?: string;
}

export interface VenueSearchResult {
  id: number;
  name: string;
  location: string;
  capacity: number;
  facilities: string[];
  layout_labels: string[];
  wheelchair_access: boolean | null;
  checks: VenueCheck[];
}

export interface VenueSearchResponse {
  results: VenueSearchResult[];
  message: string;
}

export function searchVenues(params: VenueSearchParams) {
  const query = new URLSearchParams();
  if (params.attendance) query.set("attendance", String(params.attendance));
  if (params.layout) query.set("layout", params.layout);
  if (params.facilities?.trim()) query.set("facilities", params.facilities.trim());
  if (params.location?.trim()) query.set("location", params.location.trim());
  if (params.wheelchair_access) query.set("wheelchair_access", "true");
  if (params.start) query.set("start", params.start);
  if (params.end) query.set("end", params.end);
  const text = query.toString();
  return request<VenueSearchResponse>(`/api/venues/search/${text ? `?${text}` : ""}`);
}

export interface Suitability {
  venue: number;
  venue_name: string;
  event: number;
  suitable: boolean;
  checks: VenueCheck[];
  warnings: string[];
}

export const fetchSuitability = (venueId: number, eventId: number) =>
  request<Suitability>(`/api/venues/${venueId}/suitability/?event=${eventId}`);

export interface AvailabilitySegment {
  start: string;
  end: string;
  status: string;
  label: string;
  detail: string;
  event: number | null;
  event_name: string | null;
}

export interface VenueAvailabilityRow {
  venue: number;
  venue_name: string;
  capacity: number;
  overall: "AVAILABLE" | "PARTIAL" | "BLOCKED" | "UNAVAILABLE";
  overall_label: string;
  segments: AvailabilitySegment[];
}

export interface AvailabilityComparison {
  start: string;
  end: string;
  venues: VenueAvailabilityRow[];
  none_available: boolean;
  message: string;
}

export const compareAvailability = (start: string, end: string) =>
  request<AvailabilityComparison>(
    `/api/venues/availability/?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  );

export interface ShortlistEntry {
  venue: number;
  venue_name: string;
  capacity: number;
  location: string;
  satisfied: string[];
  not_satisfied: { criterion: string; reason: string }[];
  no_longer_available: boolean;
  added_at: string;
}

export const fetchShortlist = (eventId: number) =>
  request<ShortlistEntry[]>(`/api/events/${eventId}/shortlist/`);

export const addToShortlist = (eventId: number, venue: number) =>
  request<ShortlistEntry>(`/api/events/${eventId}/shortlist/`, {
    method: "POST",
    body: { venue },
  });

export const removeFromShortlist = (eventId: number, venue: number) =>
  request<void>(`/api/events/${eventId}/shortlist/${venue}/`, { method: "DELETE" });

// --- SCRUM-11 / 67 / 73 / 69 / 66 / 70 - venue bookings ------------------------------------

export interface BookingConflict {
  booking: number;
  event: number;
  event_name: string;
  start: string;
  end: string;
}

export type BookingStatus = "PENDING" | "APPROVED" | "REJECTED" | "WITHDRAWN" | "RELEASED";

export interface VenueBooking {
  id: number;
  event: number;
  event_name: string;
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
  review_outcome: string;
  conflicts: BookingConflict[];
  created_at: string;
}

export interface BookingRequestInput {
  event: number;
  venue: number;
  start: string;
  end: string;
  attendance: number | null;
  layout: string;
  facilities: string[];
  accessibility_needs: string;
  notes: string;
}

export const fetchBookings = (eventId: number) =>
  request<VenueBooking[]>(`/api/venue-bookings/?event=${eventId}`);

export const requestBooking = (input: BookingRequestInput) =>
  request<VenueBooking>("/api/venue-bookings/", { method: "POST", body: input });

export const withdrawBooking = (id: number, confirm: boolean) =>
  request<VenueBooking>(`/api/venue-bookings/${id}/withdraw/`, {
    method: "POST",
    body: { confirm },
  });

export const acceptSuggestion = (id: number) =>
  request<VenueBooking>(`/api/venue-bookings/${id}/accept-suggestion/`, { method: "POST" });

// --- SCRUM-74 / 75 / 12 - equipment ---------------------------------------------------------

export interface EquipmentType {
  id: number;
  name: string;
  category: string;
  total_quantity: number;
}

export interface EquipmentChange {
  description: string;
  changed_by_name: string | null;
  changed_at: string;
}

export interface EquipmentRequest {
  id: number;
  event: number;
  equipment_type: number;
  equipment_name: string;
  quantity: number;
  technical_requirements: string;
  status: "REQUESTED" | "RESERVED" | "UNAVAILABLE" | "WITHDRAWN";
  status_display: string;
  reserved_quantity: number;
  requested_by_name: string | null;
  created_at: string;
  unavailable_reason: string;
  review_required: boolean;
  review_reason: string;
  changes: EquipmentChange[];
}

export interface EquipmentRequestInput {
  event: number;
  equipment_type: number;
  quantity: number;
  technical_requirements: string;
}

export interface EquipmentAvailabilityRow {
  equipment: number;
  name: string;
  available_quantity: number;
  requested_quantity?: number;
  reserved_for_this_event?: number;
  shortfall?: number;
  status: string;
}

export interface EquipmentAvailability {
  event: number | null;
  start: string;
  end: string;
  results: EquipmentAvailabilityRow[];
}

export const listEquipmentTypes = () => request<EquipmentType[]>("/api/equipment/");

export const fetchEquipmentRequests = (eventId: number) =>
  request<EquipmentRequest[]>(`/api/equipment-requests/?event=${eventId}`);

export const createEquipmentRequest = (input: EquipmentRequestInput) =>
  request<EquipmentRequest>("/api/equipment-requests/", { method: "POST", body: input });

export const amendEquipmentRequest = (
  id: number,
  changes: { quantity: number; technical_requirements: string },
) =>
  request<EquipmentRequest>(`/api/equipment-requests/${id}/`, {
    method: "PATCH",
    body: changes,
  });

export const withdrawEquipmentRequest = (id: number) =>
  request<EquipmentRequest>(`/api/equipment-requests/${id}/withdraw/`, { method: "POST" });

export const fetchEquipmentAvailability = (eventId: number) =>
  request<EquipmentAvailability>(`/api/equipment/availability/?event=${eventId}`);

// --- SCRUM-78 - change requests ----------------------------------------------------------------

export interface ChangeImpact {
  changed_fields: string[];
  venue_bookings: {
    booking: number;
    venue: string;
    status: string;
    current_start: string;
    current_end: string;
    new_start: string;
    new_end: string;
    potentially_unsuitable: boolean;
    issues: string[];
    conflicts: { event: number | null; event_name: string; start: string; end: string }[];
  }[];
  equipment: {
    request: number;
    equipment: string;
    quantity: number;
    reserved_quantity: number;
    available_in_new_period?: number;
    issues: string[];
  }[];
  registrations: { registered: number; waitlisted: number; issues: string[] } | null;
  has_impact: boolean;
  message: string | null;
}

export interface ChangeRequest {
  id: number;
  event: number;
  description: string;
  reason: string;
  proposed_start: string | null;
  proposed_end: string | null;
  proposed_attendance: number | null;
  proposed_layout: string;
  proposed_accessibility_needs: string;
  proposed_equipment_notes: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  status_display: string;
  requested_by_name: string | null;
  created_at: string;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_reason: string;
  impact?: ChangeImpact;
}

export const fetchChangeRequests = (eventId: number) =>
  request<ChangeRequest[]>(`/api/events/${eventId}/change-requests/`);

export const fetchChangeRequest = (id: number) =>
  request<ChangeRequest>(`/api/change-requests/${id}/`);

export const approveChangeRequest = (id: number, reason: string) =>
  request<ChangeRequest>(`/api/change-requests/${id}/approve/`, {
    method: "POST",
    body: { reason },
  });

export const rejectChangeRequest = (id: number, reason: string) =>
  request<ChangeRequest>(`/api/change-requests/${id}/reject/`, {
    method: "POST",
    body: { reason },
  });

// --- SCRUM-14 AC5 / SCRUM-19 AC4 - registrations -------------------------------------------------

export interface EventRegistration {
  id: number;
  full_name: string;
  email: string;
  accessibility_needs: string;
  status: "REGISTERED" | "WAITLISTED" | "WITHDRAWN";
  status_display: string;
  registered_at: string | null;
  waitlisted_at: string | null;
  withdrawn_at: string | null;
}

export interface RegistrationSummary {
  capacity: number | null;
  registered_count: number;
  waitlist_count: number;
  places_left: number | null;
  registrations: EventRegistration[];
}

export const fetchRegistrations = (eventId: number) =>
  request<RegistrationSummary>(`/api/events/${eventId}/registrations/`);

// --- helpers ------------------------------------------------------------------------------------

export function formatDateTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("en-SG") : "—";
}

/** An ISO timestamp as the local value a datetime-local input expects. */
export function toLocalInput(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

/** A datetime-local input value as an ISO timestamp, or null when empty. */
export function fromLocalInput(value: string) {
  return value ? new Date(value).toISOString() : null;
}

const NOT_FIELDS = new Set(["detail", "unmet", "missing", "warning", "conflicts", "blocks"]);

/** Field errors from a DRF 400 body, first message per field. */
export function fieldErrorsOf(body: unknown): Record<string, string> {
  const errors: Record<string, string> = {};
  if (body && typeof body === "object") {
    for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
      if (NOT_FIELDS.has(key)) continue;
      if (Array.isArray(value) && typeof value[0] === "string") errors[key] = value[0];
      else if (typeof value === "string") errors[key] = value;
    }
  }
  return errors;
}
