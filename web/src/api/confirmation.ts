import { request } from "./client";
import type { EventRequest, EventStatus } from "../types";

/** SCRUM-58 - one essential arrangement on the Readiness panel. */
export interface ReadinessItem {
  area: "Venue" | "Technical" | "Equipment" | "Safety";
  label: string;
  ready: boolean;
  detail: string;
}

export interface Readiness {
  event: number;
  status: EventStatus;
  items: ReadinessItem[];
  missing: string[];
  unavailable: string[];
  can_confirm: boolean;
  confirmed_by_name: string | null;
  confirmed_at: string | null;
}

/** SCRUM-58 AC5 - the confirmed plan the Event Organiser can rely on. */
export interface ConfirmedArrangements {
  event: number;
  status: EventStatus;
  confirmed_by_name: string | null;
  confirmed_at: string | null;
  venues: {
    session?: number;
    session_name?: string;
    session_kind?: "MAIN" | "BREAKOUT";
    venue: string;
    location: string;
    starts_at: string;
    ends_at: string;
    attendance: number;
    layout: string;
  }[];
  equipment: { equipment: string; quantity: number }[];
  safety_approved_at: string | null;
}

export const getReadiness = (eventId: number) =>
  request<Readiness>(`/api/events/${eventId}/readiness/`);

export const confirmEvent = (eventId: number) =>
  request<{ detail: string; event: EventRequest }>(`/api/events/${eventId}/confirm/`, {
    method: "POST",
    body: {},
  });

export const getConfirmedArrangements = (eventId: number) =>
  request<ConfirmedArrangements>(`/api/events/${eventId}/confirmed-arrangements/`);

/** SCRUM-58 AC3 - Technical Support record that a request cannot be met. */
export const recordEquipmentUnavailable = (requestId: number, reason: string) =>
  request<{ detail: string }>(`/api/equipment/requests/${requestId}/unavailable/`, {
    method: "POST",
    body: { reason },
  });
