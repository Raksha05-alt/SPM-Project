/** Week 7 change 5 - the Event Coordinator Lead's queue and assignments. */
import { request } from "./client";
import type { EventRequest, EventStatus, QueueRow } from "../types";

export interface AssignmentRow extends QueueRow {
  coordinator_email: string;
  assigned_by: number | null;
  assigned_by_name: string | null;
  assigned_at: string | null;
}

export interface CoordinatorOption {
  id: number;
  name: string;
  email: string;
  available: boolean;
  active_events: number;
}

function statusQuery(statuses: EventStatus[], extra: Record<string, string> = {}) {
  const params = new URLSearchParams(extra);
  if (statuses.length) params.set("status", statuses.join(","));
  const text = params.toString();
  return text ? `?${text}` : "";
}

export const fetchUnassigned = (statuses: EventStatus[] = []) =>
  request<QueueRow[]>(`/api/events/queue/${statusQuery(statuses)}`);

export const fetchAssignments = (onlyMine: boolean, statuses: EventStatus[] = []) =>
  request<AssignmentRow[]>(
    `/api/events/assignments/${statusQuery(statuses, onlyMine ? { supervised: "mine" } : {})}`,
  );

export const listCoordinatorOptions = () => request<CoordinatorOption[]>("/api/coordinators/");

export const assignCoordinator = (eventId: number, coordinator: number) =>
  request<EventRequest>(`/api/events/${eventId}/assign/`, {
    method: "POST",
    body: { coordinator },
  });
