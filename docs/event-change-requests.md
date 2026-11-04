# Event change requests (SCRUM-20, Sprint 4 gate INTAKE)

Organisers cannot edit an event after submission, and a confirmed event cannot be
edited directly (Week 9 clarifications). A **change request** is their only route.
It records what should change and why; it never edits the event.

## The shared contract

`apps.events.models.EventChangeRequest`, created only by
`apps.events.change_requests.request_change()`:

| Field | Meaning |
| --- | --- |
| `event`, `requested_by`, `requested_at` | The event, the organiser who asked, and when. |
| `description`, `reason` | What should change and why. Both required (database check constraints too). |
| `proposed_values` | Typed new values for `PROPOSABLE_FIELDS` only: `name`, `purpose`, `description`, `preferred_start`, `preferred_end`, `expected_attendance`, `required_layout`, `accessibility_needs`, `equipment_notes`. Validated with the same rules as an event edit (`EventRequestSerializer`); datetimes stored as ISO 8601. Registration policy is not changed here (SCRUM-21/81). |
| `target_bookings`, `target_equipment_requests` | IDs of **this event's own** venue bookings and equipment requests the change concerns. Anything else is refused. |
| `source_values`, `source_digest`, `source_status` | The event's editable values when the request was made, a SHA-256 digest of them (`source_snapshot(event)`), and the event status. A later step compares the current digest to detect a stale request. |
| `revision` | Revision of the request itself (starts at 1). |
| `status` | `PENDING` → `APPROVED` / `REJECTED` (SCRUM-78). |
| `decided_by`, `decided_at`, `decision_reason` | The decision (SCRUM-78). A rejection needs a reason; a decided request has a time. |

Plain text is never executed: only `proposed_values` and the target IDs are
machine-readable, and an apply step (SCRUM-80) must re-validate them against the
event's current state under the shared locks.

## Rules

- Raised by the event's own organisation only, for **Submitted, Awaiting
  Clarification, Approved, Planning or Confirmed** events. Drafts are edited
  directly; Rejected, Cancelled and Completed events refuse (AC4).
- The event row is locked first. Nothing is saved when any check fails, and every
  problem is named (`proposed_values.<field>` keys for proposed values).
- The assigned coordinator is notified through `apps.notifications.services.notify`
  (kind `CHANGE_REQUESTED`, occurrence `change-request:<id>`). While the event is
  unassigned, the active Leads are notified instead.
- Creating a request records no field-change history (SCRUM-60): nothing has changed
  yet. History is written when an approved change is applied (SCRUM-80).

## API

- `GET /api/events/<id>/change-requests/` - newest first, with `proposed_changes`
  (each field's value at request time and the proposed value, readable). Readers: the
  event's organisation, its assigned coordinator, Leads.
- `POST /api/events/<id>/change-requests/` - organiser only; returns the Pending
  request and a receipt message.

## Assessment and decision (SCRUM-59/78, gate ASSESS)

- **Significance (SCRUM-59 AC1).** `significant` is set when a request is made: it
  proposes `SIGNIFICANT_FIELDS` (date, time, attendance, layout, accessibility,
  equipment notes) or names an arrangement. The event's stage does not matter.
  Migration `events/0016` classifies requests made before the field existed.
- **`apps.events.impact.assess_change(change)`** - read-only; never reserves,
  releases, approves or marks anything reviewed. It composes the published
  providers: SCRUM-66 `impact_of` (suitability, such as attendance above capacity),
  SCRUM-70 `venue_conflicts` (clashes at the proposed time, buffered and
  hold-aware), SCRUM-12 `available_quantity` (equipment stock at the proposed time,
  without venue buffers) and SCRUM-21/81 `capacity_of` / `waiting_list`. It returns
  `venue_bookings` (approved and live held), `equipment`, `registrations`,
  `warnings`, `no_impact` with a plain `summary`, and `stale` (the event changed
  since the request).
- **`apps.events.change_requests.decide_change(change, actor, decision, reason)`** -
  the assigned coordinator only, under the event then request locks; `APPROVE` or
  `REJECT` with a required reason. A stale request, or one on a Cancelled/Completed
  event, cannot be approved (it can be rejected). Records `status`, `decided_*` and
  notifies the organiser (`CHANGE_DECIDED`, occurrence `change-decision:<id>`). An
  approved **significant** change also tells the Venue Staff and Technical Support
  whose arrangements it affects (occurrence `change-approved:<id>:venue|technical`).
  **The decision moves nothing**: no booking, reservation, registration or event field.

API: `GET /api/change-requests/<id>/impact/` (assigned coordinator, Leads) and
`POST /api/change-requests/<id>/decide/` (`{"decision": "APPROVE"|"REJECT", "reason": "..."}`;
400 for a missing reason, 409 for an already-decided or stale request).

## For later gates

- **SCRUM-66 (Jerom), SCRUM-70 (Adilah):** read `proposed_values` and the targets
  to assess suitability and conflicts.
- **SCRUM-80 (Shalika):** apply an **Approved** request under the shared locks after
  checking `source_digest` is still current, through staff review
  (`record_period_reviews`, `record_reviews`) and a fresh Safety check. SCRUM-59
  AC4 (arrangements marked for review) and AC5 (back to Planning, new Safety check)
  complete there.
