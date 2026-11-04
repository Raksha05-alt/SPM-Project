import { request } from "./client";
import type { EventStatus } from "../types";

export type RegistrationStatus = "REGISTERED" | "WAITLISTED" | "WITHDRAWN";

/** SCRUM-21/81 - what an attendee sees about registering for one event. */
export interface RegistrationSummary {
  enabled: boolean;
  open: boolean;
  reason: string;
  reason_code: string;
  opens_at: string | null;
  closes_at: string | null;
  capacity: number | null;
  remaining: number | null;
  my_status: RegistrationStatus | null;
  my_registration: number | null;
  /** SCRUM-19 - offered only when the event is full and has a waiting list. */
  waitlist_offered: boolean;
  waitlist_position: number | null;
  waiting: number;
}

export interface RegistrationInput {
  full_name: string;
  email: string;
  accessibility_requirements: string;
}

export interface Registration {
  id: number;
  event: number;
  event_name: string;
  status: RegistrationStatus;
  status_label: string;
  full_name: string;
  email: string;
  accessibility_requirements: string;
  registered_at: string;
  withdrawn_at: string | null;
}

/** SCRUM-14 AC1 - shown before the attendee confirms a withdrawal. */
export interface WithdrawalSummary {
  registration: number;
  event: number;
  event_name: string;
  starts_at: string | null;
  ends_at: string | null;
  status: RegistrationStatus;
  releases_place: boolean;
  can_withdraw: boolean;
  reason: string;
}

/** SCRUM-21 AC4 - the confirmed date, time and venue an attendee may see. */
export interface PublicEvent {
  id: number;
  name: string;
  status: EventStatus;
  status_label: string;
  starts_at: string | null;
  ends_at: string | null;
  venues: { session_name?: string; session_kind?: "MAIN" | "BREAKOUT"; venue: string; location: string; starts_at: string; ends_at: string }[];
}

export interface MyRegistration extends Registration {
  event_details: PublicEvent;
}

/** SCRUM-81 - the organiser's registration policy and its counts. */
export interface RegistrationPolicy {
  event: number;
  enabled: boolean;
  opens_at: string | null;
  closes_at: string | null;
  manually_closed: boolean;
  capacity: number | null;
  registered: number;
  remaining: number | null;
  full: boolean;
  open: boolean;
  waitlist_enabled: boolean;
  waiting: number;
}

export type RegistrationPolicyInput = Partial<
  Pick<
    RegistrationPolicy,
    "enabled" | "opens_at" | "closes_at" | "manually_closed" | "capacity" | "waitlist_enabled"
  >
>;

export const getRegistrationSummary = (eventId: number) =>
  request<RegistrationSummary>(`/api/events/${eventId}/registration/`);

export const registerForEvent = (eventId: number, input: RegistrationInput) =>
  request<{ detail: string; registration: Registration; event: PublicEvent }>(
    `/api/events/${eventId}/registration/`,
    { method: "POST", body: input },
  );

export const listMyRegistrations = () => request<MyRegistration[]>("/api/registrations/mine/");

export const getRegistrationPolicy = (eventId: number) =>
  request<RegistrationPolicy>(`/api/events/${eventId}/registration-policy/`);

export const updateRegistrationPolicy = (eventId: number, input: RegistrationPolicyInput) =>
  request<RegistrationPolicy>(`/api/events/${eventId}/registration-policy/`, {
    method: "PUT",
    body: input,
  });

/** SCRUM-19 AC1 - join the waiting list of a full event. */
export const joinWaitlist = (eventId: number, input: RegistrationInput) =>
  request<{ detail: string; registration: Registration; position: number }>(
    `/api/events/${eventId}/waitlist/`,
    { method: "POST", body: input },
  );

export const getWithdrawalSummary = (registrationId: number) =>
  request<WithdrawalSummary>(`/api/registrations/${registrationId}/withdraw/`);

/** SCRUM-14 - confirm the withdrawal after seeing the summary. */
export const withdrawRegistration = (registrationId: number) =>
  request<{ detail: string; registration: Registration }>(
    `/api/registrations/${registrationId}/withdraw/`,
    { method: "POST", body: { confirm: true } },
  );
