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
export type BookingStatus = "PENDING" | "APPROVED" | "REJECTED" | "WITHDRAWN";

export interface VenueBooking {
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
  status_label: string;
  status_changed_at: string;
  requested_by_name: string | null;
  requested_at: string;
  decided_by_name: string | null;
  decided_at: string | null;
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
