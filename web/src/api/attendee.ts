import { request } from "./client";
import type { AttendeeEvent } from "../types";

export interface VenueSlot {
  name: string;
  location: string;
  start: string;
  end: string;
}

export type RegistrationStatus = "REGISTERED" | "WAITLISTED" | "WITHDRAWN";

/** SCRUM-21 / SCRUM-81 / SCRUM-19 - an event as an Attendee sees it. */
export interface AttendeeEventRow extends AttendeeEvent {
  registration_capacity: number | null;
  registration_opens_at: string | null;
  registration_closes_at: string | null;
  places_left: number | null;
  registration_message: string | null;
  waitlist_offered: boolean;
  my_registration: { id: number; status: RegistrationStatus; status_display: string } | null;
  venues: VenueSlot[];
}

export interface RegistrationInput {
  full_name: string;
  email: string;
  accessibility_needs: string;
}

export interface MyRegistration {
  id: number;
  event: number;
  event_name: string;
  event_start: string | null;
  event_end: string | null;
  event_status: string;
  venues: VenueSlot[];
  full_name: string;
  email: string;
  accessibility_needs: string;
  status: RegistrationStatus;
  status_display: string;
  registered_at: string | null;
  waitlisted_at: string | null;
  place_offered_at: string | null;
  withdrawn_at: string | null;
}

/** SCRUM-14 - shown before the Attendee confirms a withdrawal. */
export interface WithdrawalSummary {
  event: string;
  start: string | null;
  end: string | null;
  status: string;
}

export const listOpenEvents = () => request<AttendeeEventRow[]>("/api/events/");

export const registerForEvent = (eventId: number, input: RegistrationInput) =>
  request<MyRegistration>(`/api/events/${eventId}/registrations/`, {
    method: "POST",
    body: input,
  });

export const joinWaitlist = (eventId: number, input: RegistrationInput) =>
  request<MyRegistration>(`/api/events/${eventId}/waitlist/`, { method: "POST", body: input });

export const listMyRegistrations = () => request<MyRegistration[]>("/api/registrations/");

/** Without confirm the API answers 409 with a summary; with it, the withdrawal happens. */
export const withdrawRegistration = (id: number, confirm: boolean) =>
  request<MyRegistration>(`/api/registrations/${id}/withdraw/`, {
    method: "POST",
    body: confirm ? { confirm: true } : {},
  });
