import { request } from "./client";
import type {
  EventSafetyState,
  SafetyCheck,
  SafetyCheckDetail,
  SafetyDecision,
  SafetyStatus,
} from "../types";

/** SCRUM-90 - Operational Safety Check endpoints. */
export const listSafetyChecks = (statuses: SafetyStatus[] = []) =>
  request<SafetyCheck[]>(
    statuses.length
      ? `/api/safety-checks/?status=${statuses.map(encodeURIComponent).join(",")}`
      : "/api/safety-checks/",
  );

export const getSafetyCheck = (id: number) =>
  request<SafetyCheckDetail>(`/api/safety-checks/${id}/`);

export const decideSafetyCheck = (id: number, decision: SafetyDecision, comment: string) =>
  request<SafetyCheckDetail>(`/api/safety-checks/${id}/decide/`, {
    method: "POST",
    body: { decision, comment },
  });

export const getEventSafety = (eventId: number) =>
  request<EventSafetyState>(`/api/events/${eventId}/safety-checks/`);

export const requestSafetyCheck = (eventId: number, note: string) =>
  request<SafetyCheckDetail>(`/api/events/${eventId}/safety-checks/`, {
    method: "POST",
    body: { note },
  });
