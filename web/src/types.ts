export type Role =
  | "ORGANISER"
  | "COORDINATOR"
  | "COORDINATOR_LEAD"
  | "VENUE_STAFF"
  | "TECH_SUPPORT"
  | "ATTENDEE"
  | "SAFETY_OFFICER";

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

/** SCRUM-49 - one round of a coordinator asking the client for more information. */
/** SCRUM-92 - a note from an offline clarification conversation. */
export interface ClarificationNote {
  id: number;
  body: string;
  author_name: string | null;
  author_role: string | null;
  created_at: string;
}

export interface Clarification {
  id: number;
  message: string;
  fields: string[];
  requested_by_name: string | null;
  requested_at: string;
  resolved_at: string | null;
  comments: ClarificationNote[];
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
  assignment_requires_attention: boolean;
  /** Approval decision - only sent to internal users. */
  approved_by_name?: string | null;
  approved_at?: string | null;
  /** SCRUM-58 AC4 - who confirmed the event, and when. */
  confirmed_by_name?: string | null;
  confirmed_at?: string | null;
  venue_disruptions?: { booking: number; venue: string; session: string; starts_at: string; ends_at: string; status: string }[];
  /** SCRUM-52 - the rejection reason and date are shown to the client too. */
  rejection_reason: string;
  rejected_at: string | null;
  rejected_by_name?: string | null;
  clarifications: Clarification[];
  missing_mandatory_fields: string[];
  is_editable: boolean;
  created_at: string;
  /** SCRUM-61 AC4 - who last edited the request. */
  updated_by_name?: string | null;
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

/** SCRUM-79/82 - one of the signed-in user's own notices. */
export interface AppNotification {
  id: number;
  event: number;
  event_name: string;
  kind: string;
  kind_label: string;
  message: string;
  created_at: string;
  read_at: string | null;
  is_read: boolean;
  /** Decided by the API from the user's access now; null when it opens nothing. */
  destination: { path: string; label: string } | null;
}

export interface AttendeeEvent {
  venues?: { session_name: string; venue: string; location: string; starts_at: string; ends_at: string }[];
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

/** SCRUM-65 - a venue record as Venue Staff maintain it. */
export interface Venue {
  id: number;
  name: string;
  location: string;
  capacity: number;
  facilities: string[];
  layouts: string[];
  layout_labels: string[];
  wheelchair_access: boolean | null;
  accessibility_notes: string;
  /** SCRUM-90 AC2 - what the Safety Officer reviews. */
  emergency_access: string;
  known_restrictions: string;
  setup_minutes?: number;
  turnaround_minutes?: number;
  opens_at: string | null;
  closes_at: string | null;
  operating_days: number[];
  operating_hours: string | null;
  in_service: boolean;
  /** SCRUM-9 AC4. */
  operational_status: "In service" | "Out of service";
  /** SCRUM-9 AC3 - labels of details that have not been provided. */
  missing_information: string[];
  created_by_name: string | null;
  updated_by_name: string | null;
  created_at: string;
  updated_at: string;
}

/** SCRUM-91 - one entry in the room layout catalogue. */
export interface LayoutType {
  code: string;
  name: string;
  description: string;
  is_active: boolean;
  sort_order: number;
  updated_by_name: string | null;
  created_at: string;
  updated_at: string;
}

/** SCRUM-71 - a requirement a venue does not meet. */
export interface SuitabilityReason {
  requirement: "CAPACITY" | "LAYOUT" | "ACCESSIBILITY" | "FACILITY" | "OPERATING_HOURS";
  message: string;
}

/** SCRUM-71 - one venue checked against one event's requirements. */
export interface VenueSuitability {
  venue: number;
  venue_name: string;
  warnings?: string[];
  suitable: boolean;
  reasons: SuitabilityReason[];
  /** Shown beside the result; operational status is not a suitability reason. */
  in_service: boolean;
}

/** SCRUM-71 - the requirements the venues were checked against. */
export interface SuitabilityRequirements {
  attendance: number | null;
  layout: string;
  layout_name: string;
  required_facilities: string[];
  wheelchair_access_required: boolean;
  starts_at: string | null;
  ends_at: string | null;
}

export interface EventSuitability {
  event: number;
  requirements: SuitabilityRequirements;
  /** What this check does not cover, e.g. whether the venue is free. */
  not_checked: string[];
  venues: VenueSuitability[];
}

/** SCRUM-11 - a venue booking request for an event. */
export type BookingStatus = "DISRUPTED" | "PENDING" | "HELD" | "APPROVED" | "REJECTED" | "WITHDRAWN" | "EXPIRED";

export interface VenueBooking {
  session?: number;
  session_name?: string;
  session_kind?: "MAIN" | "BREAKOUT";
  session_active?: boolean;
  effective_attendance?: number;
  replaces?: number | null;
  withdrawn_by_name?: string | null;
  withdrawn_at?: string | null;
  id: number;
  event: number;
  event_name: string;
  organisation_name: string;
  venue: number;
  venue_name: string;
  starts_at: string;
  ends_at: string;
  attendance: number;
  layout: string;
  layout_name: string;
  required_facilities: string[];
  wheelchair_access_required: boolean;
  accessibility_notes: string;
  status: BookingStatus;
  hold_until?: string | null;
  status_label: string;
  status_changed_at: string;
  requested_by_name: string | null;
  requested_at: string;
  decided_by_name: string | null;
  decided_at: string | null;
  buffer_review?: { occupied_starts_at: string; occupied_ends_at: string; warnings: string[] };
  decision_reason: string;
}

/** SCRUM-74 - one catalogue equipment type a coordinator can request. */
export interface EquipmentType {
  id: number;
  code: string;
  name: string;
  description: string;
}

export type EquipmentRequestStatus = "REQUESTED" | "RESERVED" | "WITHDRAWN";

/** SCRUM-74 - one equipment line requested for an event. */
export interface EquipmentRequest {
  id: number;
  event: number;
  equipment_type: number;
  equipment_type_name: string;
  quantity: number;
  technical_requirements: string;
  status: EquipmentRequestStatus;
  status_label: string;
  requested_by_name: string | null;
  requested_at: string;
}

/** SCRUM-74 AC3 - the scoped event view Technical Support work from. */
export interface TechnicalEvent {
  id: number;
  name: string;
  status: EventStatus;
  status_label: string;
  preferred_start: string | null;
  preferred_end: string | null;
  expected_attendance: number | null;
  coordinator_name: string | null;
  equipment_requests: EquipmentRequest[];
}

/** SCRUM-12 - stock out of action regardless of the period (AC4). */
export interface EquipmentUnavailableStock {
  quantity: number;
  cause: "DAMAGED" | "MAINTENANCE";
  cause_label: string;
  reason: string;
  expected_return_at: string | null;
}

/** SCRUM-12 - one equipment type's availability for the period. */
export interface EquipmentAvailabilityRow {
  equipment_type: number;
  code: string;
  name: string;
  in_service: boolean;
  total_quantity: number;
  unavailable_quantity: number;
  unavailable: EquipmentUnavailableStock[];
  reserved_for_other_events: number;
  reserved_for_this_event: number;
  available_quantity: number;
  requested_quantity: number | null;
  shortfall: number;
  status: "AVAILABLE" | "PARTIAL" | "UNAVAILABLE";
}

/** SCRUM-12 - GET /api/events/:id/equipment-availability/ */
export interface EquipmentAvailability {
  event: { id: number; name: string; preferred_start: string | null; preferred_end: string | null };
  period: { starts_at: string; ends_at: string };
  equipment: EquipmentAvailabilityRow[];
  shortfalls: { name: string; requested: number; short_by: number }[];
}

/** SCRUM-76 - one reservation holding the equipment during the period. */
export interface EquipmentHolder {
  reservation: number;
  quantity: number;
  starts_at: string;
  ends_at: string;
  /** Technical Support only; coordinators see quantity and dates alone. */
  event?: {
    id: number;
    name: string;
    status: EventStatus;
    status_label: string;
    coordinator: { name: string; email: string } | null;
  };
}

/** SCRUM-76 - GET /api/events/:id/equipment-availability/:typeId/ */
export interface EquipmentHolders {
  period: { starts_at: string; ends_at: string };
  availability: EquipmentAvailabilityRow;
  holders: EquipmentHolder[];
}

/** SCRUM-90 - the Operational Safety Check. */
export type SafetyStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "CHANGES_REQUESTED"
  | "SUPERSEDED";

export type SafetyDecision = "APPROVED" | "REJECTED" | "CHANGES_REQUESTED";

export interface SafetyVenueFacts {
  session_name?: string;
  session_kind?: "MAIN" | "BREAKOUT";
  booking: number;
  venue: string;
  location: string;
  capacity: number;
  booked_attendance: number;
  layout: string;
  starts_at: string;
  ends_at: string;
  wheelchair_access: boolean | null;
  accessibility_notes: string;
  required_facilities: string[];
  wheelchair_access_required: boolean;
  booking_accessibility_notes: string;
  emergency_access: string;
  known_restrictions: string;
}

export interface SafetyEquipmentFacts {
  equipment: string;
  quantity: number;
  reserved_quantity: number;
  status: string;
  technical_requirements: string;
}

/** AC2 - what the Safety Officer reviews before deciding. */
export interface SafetyFacts {
  event: number;
  event_name: string;
  organisation: string;
  expected_attendance: number | null;
  starts_at: string | null;
  ends_at: string | null;
  required_layout: string;
  accessibility_needs: string;
  venues: SafetyVenueFacts[];
  equipment: SafetyEquipmentFacts[];
  technical_approval: {
    approved_by: string | null;
    approved_at: string | null;
    no_equipment_required: boolean;
    notes: string;
  } | null;
  concerns: string[];
}

export interface SafetyCheck {
  id: number;
  event: number;
  event_name: string;
  event_status: EventStatus;
  event_status_display: string;
  event_start: string | null;
  organisation_name: string;
  coordinator_name: string | null;
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
  /** A pending or approved check that no longer matches the arrangements. */
  is_stale: boolean;
}

export interface SafetyCheckDetail extends SafetyCheck {
  /** The facts when the check was requested - kept as evidence. */
  facts: SafetyFacts;
  /** For a pending check, the arrangements as they stand now. */
  current_facts: SafetyFacts | null;
}

/** GET /api/events/:id/safety-checks/ */
export interface EventSafetyState {
  checks: SafetyCheck[];
  /** Venue and technical arrangements still missing (blocks a request). */
  arrangement_gaps: string[];
  /** Everything that blocks confirmation, including the safety check. */
  confirmation_gaps: string[];
  can_request: boolean;
}

export type ChangeRequestStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "IN_REVIEW"
  | "APPLIED"
  | "ORIGINAL_KEPT";

/** SCRUM-20 - one proposed field, with its value when the request was made. */
export interface ProposedChange {
  field: string;
  label: string;
  current: string;
  proposed: string;
}

/** SCRUM-20 - an organiser's request to change a submitted or confirmed event. */
export interface ChangeRequest {
  id: number;
  event: number;
  description: string;
  reason: string;
  proposed_values: Record<string, unknown>;
  proposed_changes: ProposedChange[];
  target_bookings: number[];
  target_equipment_requests: number[];
  revision: number;
  /** SCRUM-59 AC1 - may affect arrangements (date, time, attendance, venue or equipment). */
  significant: boolean;
  status: ChangeRequestStatus;
  status_label: string;
  status_changed_at: string;
  requested_by_name: string | null;
  requested_at: string;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_reason: string;
  /** SCRUM-80 - when the approved change was applied and when it finished. */
  applied_at: string | null;
  completed_at: string | null;
  completion_note: string;
}

export type ArrangementOutcome = "PENDING" | "ACCOMMODATED" | "NOT_ACCOMMODATED";

/** SCRUM-80 - one arrangement an approved change affects, as staff review it. */
export interface ArrangementReviewItem {
  id: number;
  change_request: number;
  event: number;
  event_name: string;
  change_description: string;
  change_status: ChangeRequestStatus;
  kind: "VENUE" | "EQUIPMENT";
  name: string;
  quantity: number | null;
  before: Record<string, string | number | boolean | null>;
  proposed: Record<string, string | number | boolean | null>;
  reasons: string[];
  outcome: ArrangementOutcome;
  outcome_label: string;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_reason: string;
}

/** SCRUM-80 AC5 - a change request's history: request, decision, each outcome and who. */
export interface ChangeHistory {
  change_request: number;
  description: string;
  reason: string;
  requested_by: string | null;
  requested_at: string;
  status: ChangeRequestStatus;
  status_label: string;
  decision: { decided_by: string | null; decided_at: string | null; reason: string };
  applied_by: string | null;
  applied_at: string | null;
  completed_at: string | null;
  completion_note: string;
  arrangements: {
    id: number;
    kind: "VENUE" | "EQUIPMENT";
    kind_label: string;
    name: string;
    before: Record<string, string | number | boolean | null>;
    proposed: Record<string, string | number | boolean | null>;
    reasons: string[];
    outcome: ArrangementOutcome;
    outcome_label: string;
    reviewed_by: string | null;
    reviewed_at: string | null;
    review_reason: string;
  }[];
  field_changes: {
    field: string;
    before: unknown;
    after: unknown;
    actor: string | null;
    changed_at: string;
  }[];
}

/** SCRUM-78 - one venue booking a change may affect, with its proposed period. */
export interface AffectedBooking {
  booking: number;
  venue: string;
  session: string;
  status: string;
  status_label: string;
  starts_at: string;
  ends_at: string;
  proposed_starts_at: string | null;
  proposed_ends_at: string | null;
  rechecked_for: string[];
  unsuitable: boolean;
  unsuitable_reasons: string[];
  conflicts: { booking: number; event: number; starts_at: string; ends_at: string }[];
  referenced: boolean;
}

/** SCRUM-78 - one equipment request a change may affect. */
export interface AffectedEquipment {
  request: number;
  equipment_type: string;
  quantity: number;
  status: string;
  status_label: string;
  available_at_proposed_time: number | null;
  shortfall: number | null;
  reasons: string[];
}

/** SCRUM-59/78 - the read-only assessment of a change request. */
export interface ChangeAssessment {
  change_request: number;
  significant: boolean;
  significant_fields: string[];
  stale: boolean;
  venue_bookings: AffectedBooking[];
  equipment: AffectedEquipment[];
  registrations: {
    registered: number;
    waitlisted: number;
    capacity: number | null;
    affected: boolean;
    reasons: string[];
  };
  warnings: string[];
  no_impact: boolean;
  summary: string;
}
