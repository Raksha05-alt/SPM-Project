import { request } from "./client";
import type { EventStatus } from "../types";

export type RegistrationStatus = "REGISTERED" | "WITHDRAWN";

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
}

/** SCRUM-21 AC4 - the confirmed date, time and venue an attendee may see. */
export interface PublicEvent {
  id: number;
  name: string;
  status: EventStatus;
  status_label: string;
  starts_at: string | null;
  ends_at: string | null;
  venues: { venue: string; location: string; starts_at: string; ends_at: string }[];
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
}

export type RegistrationPolicyInput = Partial<
  Pick<RegistrationPolicy, "enabled" | "opens_at" | "closes_at" | "manually_closed" | "capacity">
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
