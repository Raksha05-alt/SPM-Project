import { request } from "./client";
import type {
  AssignedEventRow,
  AttendeeEvent,
  ClarificationComment,
  EventRequest,
  QueueRow,
} from "../types";

export type EventDraft = Partial<
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
    | "registration_required"
  >
>;

export const listEvents = () => request<EventRequest[]>("/api/events/");

export const listAttendeeEvents = () => request<AttendeeEvent[]>("/api/events/");

export const getEvent = (id: number) => request<EventRequest>(`/api/events/${id}/`);

export const createDraft = (draft: EventDraft) =>
  request<EventRequest>("/api/events/", { method: "POST", body: draft });

export const updateDraft = (id: number, draft: EventDraft) =>
  request<EventRequest>(`/api/events/${id}/`, { method: "PATCH", body: draft });

export const deleteDraft = (id: number) =>
  request<void>(`/api/events/${id}/`, { method: "DELETE" });

export const submitEvent = (id: number) =>
  request<EventRequest>(`/api/events/${id}/submit/`, { method: "POST" });

export const fetchQueue = () => request<QueueRow[]>("/api/events/queue/");

export const fetchMyEvents = () => request<AssignedEventRow[]>("/api/events/mine/");

export const approveEvent = (id: number) =>
  request<EventRequest>(`/api/events/${id}/approve/`, { method: "POST" });

export const requestClarification = (id: number, message: string, fields: string[]) =>
  request<EventRequest>(`/api/events/${id}/request-clarification/`, {
    method: "POST",
    body: { message, fields },
  });

export const rejectEvent = (id: number, reason: string) =>
  request<EventRequest>(`/api/events/${id}/reject/`, { method: "POST", body: { reason } });

/** The coordinator records the client's offline answers and resumes the review. */
export const resumeReview = (id: number) =>
  request<EventRequest>(`/api/events/${id}/resume-review/`, { method: "POST" });

/** Week 9 clarification - record what was said offline about a clarification. */
export const addClarificationNote = (id: number, message: string, clarification?: number) =>
  request<ClarificationComment>(`/api/events/${id}/comment/`, {
    method: "POST",
    body: clarification ? { message, clarification } : { message },
  });
