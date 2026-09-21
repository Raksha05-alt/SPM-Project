import { request } from "./client";
import type { EventRequest, QueueRow } from "../types";

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
