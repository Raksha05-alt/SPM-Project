export type Role =
  | "ORGANISER"
  | "COORDINATOR"
  | "COORDINATOR_LEAD"
  | "VENUE_STAFF"
  | "TECH_SUPPORT"
  | "SAFETY_OFFICER"
  | "ATTENDEE";

export interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  role: Role;
  role_label: string;
  organisation: number | null;
  organisation_name: string | null;
  /** US-01.1 - where this role lands after signing in. Decided by the API. */
  landing_path: string;
}

export type EventStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "UNDER_REVIEW"
  | "APPROVED"
  | "PLANNING"
  | "CONFIRMED"
  | "COMPLETED"
  | "CANCELLED"
  | "REJECTED";

/** Week 9 clarification - a note recording what was said offline. */
export interface ClarificationComment {
  id: number;
  clarification: number;
  message: string;
  author_name: string | null;
  author_role: string | null;
  created_at: string;
}

/** SCRUM-49 - one round of a coordinator asking the client for more information. */
export interface Clarification {
  id: number;
  message: string;
  fields: string[];
  requested_by_name: string | null;
  requested_at: string;
  resolved_at: string | null;
  comments?: ClarificationComment[];
}

/** Week 7 change 6 - the state of an Operational Safety Check. */
export type SafetyStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "CHANGES_REQUESTED"
  | "SUPERSEDED";

export interface SafetyCheckSummary {
  id: number;
  event: number;
  status: SafetyStatus;
  status_display: string;
  requested_by_name: string | null;
  requested_at: string;
  request_note: string;
  decided_by_name: string | null;
  decided_at: string | null;
  comment: string;
  superseded_at: string | null;
  superseded_reason: string;
}

export interface EventRequest {
  id: number;
  name: string;
  purpose: string;
  description: string;
  preferred_start: string | null;
  preferred_end: string | null;
  expected_attendance: number | null;
  required_layout: string;
  /** Week 7 clarification - the name from the layout catalogue. */
  required_layout_label?: string;
  accessibility_needs: string;
  equipment_notes: string;
  registration_required: boolean;
  status: EventStatus;
  status_label: string;
  status_description: string;
  status_changed_at: string | null;
  submitted_at: string | null;
  organisation_name: string;
  created_by_name: string;
  coordinator: number | null;
  coordinator_name: string | null;
  coordinator_email: string | null;
  /** Week 7 change 5 - true while the request waits for a Lead to assign it. */
  assignment_requires_attention: boolean;
  assigned_at?: string | null;
  /** Internal only: the Lead who made the current assignment. */
  assigned_by_name?: string | null;
  /** Internal only: the latest Operational Safety Check. */
  safety_check?: SafetyCheckSummary | null;
  /** Approval decision - only sent to internal users. */
  approved_by_name?: string | null;
  approved_at?: string | null;
  /** SCRUM-52 - the rejection reason and date are shown to the client too. */
  rejection_reason: string;
  rejected_at: string | null;
  rejected_by_name?: string | null;
  clarifications: Clarification[];
  missing_mandatory_fields: string[];
  is_editable: boolean;
  created_at: string;
  updated_at: string;
}

export interface QueueRow {
  id: number;
  name: string;
  organisation_name: string;
  preferred_start: string | null;
  expected_attendance: number | null;
  status: EventStatus;
  status_label: string;
  status_description: string;
  submitted_at: string | null;
  coordinator: number | null;
  coordinator_name: string | null;
  assignment_requires_attention: boolean;
  approved_by_name: string | null;
  approved_at: string | null;
}

/** SCRUM-54 - one of the signed-in coordinator's own events. */
export interface AssignedEventRow extends QueueRow {
  next_action: string;
  requires_action: boolean;
}

export interface AssignmentNotification {
  id: number;
  event: number;
  message: string;
  created_at: string;
}

export interface AttendeeEvent {
  id: number;
  name: string;
  description: string;
  preferred_start: string | null;
  preferred_end: string | null;
  accessibility_needs: string;
  registration_required: boolean;
  status: "CONFIRMED" | "COMPLETED" | "CANCELLED";
  status_label: string;
  status_description: string;
  status_changed_at: string | null;
}
