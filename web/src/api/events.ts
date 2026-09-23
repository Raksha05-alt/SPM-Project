import { request } from "./client";
import type { EventRequest } from "../types";

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

export const createEvent = (event: EventDraft) =>
  request<EventRequest>("/api/events/", { method: "POST", body: event });
