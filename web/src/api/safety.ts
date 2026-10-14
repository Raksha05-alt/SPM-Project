/** Week 7 change 6 - Operational Safety Checks. */
import { request } from "./client";
import type { SafetyCheckSummary, SafetyStatus } from "../types";

export interface SafetyVenueFacts {
  booking: number;
  venue: string;
  session: string;
  location: string;
  capacity: number;
  attendance: number;
  layout: string;
  start: string;
  end: string;
  occupied_from: string;
  occupied_until: string;
  wheelchair_access: boolean | null;
  accessibility_notes: string;
  safety_notes: string;
}

export interface SafetyFacts {
  event: number;
  event_name: string;
  expected_attendance: number | null;
  required_layout: string;
  accessibility_needs: string;
  start: string | null;
  end: string | null;
  venues: SafetyVenueFacts[];
  equipment: { equipment: string; quantity: number; technical_requirements: string }[];
  concerns: string[];
}

export interface SafetyCheck extends SafetyCheckSummary {
  event_name: string;
  event_status: string;
  organisation_name: string;
  coordinator_name: string | null;
  facts: SafetyFacts;
  current_facts: SafetyFacts | null;
}

export type SafetyDecision = "APPROVED" | "REJECTED" | "CHANGES_REQUESTED";

export const listSafetyChecks = (statuses: SafetyStatus[] = []) =>
  request<SafetyCheck[]>(
    statuses.length ? `/api/safety-checks/?status=${statuses.join(",")}` : "/api/safety-checks/",
  );

export const getSafetyCheck = (id: number) => request<SafetyCheck>(`/api/safety-checks/${id}/`);

export const decideSafetyCheck = (id: number, decision: SafetyDecision, comment: string) =>
  request<SafetyCheck>(`/api/safety-checks/${id}/decide/`, {
    method: "POST",
    body: { decision, comment },
  });

export const eventSafetyChecks = (eventId: number) =>
  request<SafetyCheck[]>(`/api/events/${eventId}/safety-checks/`);

export const requestSafetyCheck = (eventId: number, note: string) =>
  request<SafetyCheck>(`/api/events/${eventId}/safety-checks/`, {
    method: "POST",
    body: { note },
  });
