import { request } from "./client";
import type { EventRequest, EventStatus } from "../types";

export interface CoordinatorChoice {
  id: number;
  name: string;
  email: string;
  coordinator_available: boolean;
}

export interface LeadEventRow {
  id: number;
  name: string;
  purpose: string;
  organisation_name: string;
  status: EventStatus;
  status_label: string;
  preferred_start: string | null;
  preferred_end: string | null;
  expected_attendance: number | null;
  submitted_at: string | null;
  coordinator: number | null;
  coordinator_name: string | null;
  supervising_lead: number | null;
  supervising_lead_name: string | null;
  assignment_revision: number;
  can_assign: boolean;
}

export interface AssignmentHistory {
  id: number;
  revision: number;
  previous_coordinator: number | null;
  previous_coordinator_name: string | null;
  coordinator: number;
  coordinator_name: string;
  assigned_by: number;
  assigned_by_name: string;
  previous_supervising_lead: number | null;
  previous_supervising_lead_name: string | null;
  assigned_at: string;
}

export interface LeadEvent extends EventRequest {
  supervising_lead: number | null;
  supervising_lead_name: string | null;
  assignment_revision: number;
  assignment_history: AssignmentHistory[];
  can_assign: boolean;
}

export const listUnassignedEvents = () => request<LeadEventRow[]>("/api/events/unassigned/");

export function listAssignments(onlyMine: boolean, active: boolean) {
  const params = new URLSearchParams({ active: String(active) });
  if (onlyMine) params.set("supervised_by", "me");
  return request<LeadEventRow[]>(`/api/events/assignments/?${params}`);
}

export const listCoordinators = () => request<CoordinatorChoice[]>("/api/events/coordinators/");
export const getLeadEvent = (id: number) => request<LeadEvent>(`/api/events/${id}/`);

export const assignCoordinator = (eventId: number, coordinatorId: number, revision: number) =>
  request<LeadEvent>(`/api/events/${eventId}/assign-coordinator/`, {
    method: "POST",
    body: { coordinator_id: coordinatorId, expected_revision: revision },
  });
