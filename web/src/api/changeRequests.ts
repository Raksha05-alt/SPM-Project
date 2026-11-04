import { request } from "./client";
import type { ChangeAssessment, ChangeRequest } from "../types";

/** SCRUM-20 - what the organiser sends; proposed values name event fields only. */
export interface ChangeRequestInput {
  description: string;
  reason: string;
  proposed_values: Record<string, string | number | null>;
}

export const listChangeRequests = (eventId: number) =>
  request<ChangeRequest[]>(`/api/events/${eventId}/change-requests/`);

export const requestChange = (eventId: number, input: ChangeRequestInput) =>
  request<{ detail: string; change_request: ChangeRequest }>(
    `/api/events/${eventId}/change-requests/`,
    { method: "POST", body: input },
  );

/** SCRUM-59/78 - what a change request would affect; read-only. */
export const getChangeImpact = (changeId: number) =>
  request<ChangeAssessment>(`/api/change-requests/${changeId}/impact/`);

/** SCRUM-78 AC5 - the assigned coordinator approves or rejects, with a reason. */
export const decideChange = (changeId: number, decision: "APPROVE" | "REJECT", reason: string) =>
  request<{ detail: string; change_request: ChangeRequest; assessment: ChangeAssessment }>(
    `/api/change-requests/${changeId}/decide/`,
    { method: "POST", body: { decision, reason } },
  );
