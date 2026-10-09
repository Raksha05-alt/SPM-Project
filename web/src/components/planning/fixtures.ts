import type { EventRequest } from "../../types";

/** An event in planning, assigned to coordinator 2 - shared by the planning tests. */
export function planningEvent(overrides: Partial<EventRequest> = {}): EventRequest {
  return {
    id: 9,
    name: "Partner Summit",
    purpose: "Annual partner briefing",
    description: "Keynote and breakout sessions.",
    preferred_start: "2026-11-20T01:00:00Z",
    preferred_end: "2026-11-20T07:00:00Z",
    expected_attendance: 120,
    required_layout: "THEATRE",
    accessibility_needs: "Wheelchair access",
    equipment_notes: "Two projectors",
    registration_required: true,
    status: "PLANNING",
    status_label: "Planning",
    status_description: "Venue, equipment and other arrangements are being made.",
    status_changed_at: "2026-09-22T01:00:00Z",
    submitted_at: "2026-09-22T01:00:00Z",
    organisation_name: "Acme Pte Ltd",
    created_by_name: "Ada Organiser",
    coordinator: 2,
    coordinator_name: "Cora Coordinator",
    coordinator_email: "coordinator@connectsphere.example",
    assignment_requires_attention: false,
    rejection_reason: "",
    rejected_at: null,
    clarifications: [],
    missing_mandatory_fields: [],
    is_editable: false,
    created_at: "2026-09-21T01:00:00Z",
    updated_at: "2026-09-22T01:00:00Z",
    ...overrides,
  };
}
