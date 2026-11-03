import { request } from "./client";
import type { ChangeRequest } from "../types";

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
