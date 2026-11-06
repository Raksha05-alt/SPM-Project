import { request } from "./client";
import type {
  ArrangementOutcome,
  ArrangementReviewItem,
  ChangeAssessment,
  ChangeHistory,
  ChangeRequest,
} from "../types";

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

/** SCRUM-80 AC1/AC6 - the assigned coordinator starts applying an approved change. */
export const applyChange = (changeId: number) =>
  request<{ detail: string; change_request: ChangeRequest; history: ChangeHistory }>(
    `/api/change-requests/${changeId}/apply/`,
    { method: "POST" },
  );

/** SCRUM-80 AC3 - after staff could not accommodate it, keep the original arrangement. */
export const keepOriginal = (changeId: number, reason: string) =>
  request<{ detail: string; change_request: ChangeRequest }>(
    `/api/change-requests/${changeId}/keep-original/`,
    { method: "POST", body: { reason } },
  );

/** SCRUM-80 AC5 - the request, decision, each arrangement outcome and who. */
export const getChangeHistory = (changeId: number) =>
  request<ChangeHistory>(`/api/change-requests/${changeId}/history/`);

/** SCRUM-80 AC1 - the reviews waiting for this Venue Staff / Technical Support member. */
export const listArrangementReviews = (status: ArrangementOutcome | "" = "PENDING") =>
  request<ArrangementReviewItem[]>(`/api/arrangement-reviews/?status=${status}`);

/** SCRUM-80 AC2/AC3 - staff record whether they can accommodate the change. */
export const decideArrangement = (
  reviewId: number,
  outcome: "ACCOMMODATED" | "NOT_ACCOMMODATED",
  reason: string,
) =>
  request<{ detail: string; review: ArrangementReviewItem }>(
    `/api/arrangement-reviews/${reviewId}/decide/`,
    { method: "POST", body: { outcome, reason } },
  );
