import { request } from "./client";
import type { EventRequest, EventStatus } from "../types";

/** SCRUM-58 AC5 - what the client can rely on once the event is confirmed. */
export interface ConfirmedArrangements {
  venues: Array<{ venue: string; location: string; start: string; end: string }>;
  equipment: Array<{ equipment: string; quantity: number }>;
}

/** The extra fields the API sends the organiser on a submitted event. */
export interface OrganiserEvent extends EventRequest {
  cancellation_reason?: string;
  confirmed_arrangements?: ConfirmedArrangements | null;
}

export type ChangeRequestStatus = "PENDING" | "APPROVED" | "REJECTED";

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
  status: ChangeRequestStatus;
  status_display: string;
  requested_by_name: string | null;
  created_at: string;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_reason: string;
}

export interface ChangeRequestInput {
  description: string;
  reason?: string;
  proposed_start?: string | null;
  proposed_end?: string | null;
  proposed_attendance?: number | null;
  proposed_layout?: string;
  proposed_accessibility_needs?: string;
  proposed_equipment_notes?: string;
}

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

export interface EventRegistrations {
  capacity: number | null;
  registered_count: number;
  waitlist_count: number;
  places_left: number | null;
  registrations: EventRegistration[];
}

/** SCRUM-45 / SCRUM-57 - the organisation's events, optionally narrowed by status. */
export const listOrganiserEvents = (statuses: EventStatus[] = []) =>
  request<OrganiserEvent[]>(
    statuses.length ? `/api/events/?status=${statuses.join(",")}` : "/api/events/",
  );

export const getOrganiserEvent = (id: number) => request<OrganiserEvent>(`/api/events/${id}/`);

export const cancelEvent = (id: number, reason: string) =>
  request<OrganiserEvent>(`/api/events/${id}/cancel/`, { method: "POST", body: { reason } });

export const listChangeRequests = (eventId: number) =>
  request<ChangeRequest[]>(`/api/events/${eventId}/change-requests/`);

export const createChangeRequest = (eventId: number, input: ChangeRequestInput) =>
  request<ChangeRequest>(`/api/events/${eventId}/change-requests/`, {
    method: "POST",
    body: input,
  });

export const getEventRegistrations = (eventId: number) =>
  request<EventRegistrations>(`/api/events/${eventId}/registrations/`);
