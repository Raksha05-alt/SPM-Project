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

## Applying an approved change (SCRUM-80, gate APPLY)

Statuses after approval: `IN_REVIEW` (staff are reviewing), then `APPLIED` or
`ORIGINAL_KEPT`.

1. **`apply_change(change, actor)`** (assigned coordinator; event then request
   locks). Refuses a request that is not Approved, a Cancelled/Completed event and a
   stale request (`source_digest`). Records the real SCRUM-70 period reviews
   (`record_period_reviews`, Confirmed source only) and SCRUM-66 suitability reviews
   (`record_reviews`, source `CHANGE_REQUEST`), creates one **`ArrangementReview`**
   per affected venue booking and equipment request (SCRUM-80 AC1, SCRUM-59 AC4),
   calls `arrangements_changed` (Safety superseded; Confirmed -> Planning; AC6) and
   notifies Venue Staff / Technical Support (`CHANGE_REVIEW`). **Nothing is moved.**
   A change that affects no arrangement is applied at once.
2. **`review_arrangement(review, actor, outcome, reason)`** - Venue Staff for venue
   items, Technical Support for equipment; `ACCOMMODATED` or `NOT_ACCOMMODATED` with
   a reason (who/when recorded, AC2). An accommodation is re-checked under the locks
   (current clashes, suitability, stock) and refused if it no longer fits. Venue
   outcomes also call SCRUM-70's `review_period`.
3. **The switch (AC4).** When every review is accommodated, one transaction rechecks
   the digest and every arrangement, updates the event fields (SCRUM-60 history,
   source `CHANGE_REQUEST`), each booking's period/attendance (booking history) and
   each reservation's period (equipment history), sends the equipment plan back for
   Technical Support approval (`advance_plan`), calls `arrangements_changed` and
   notifies the organiser, affected staff and registered attendees
   (`notify_attendees_of_change`, date/time).
4. **Cannot accommodate (AC3).** The originals stay; the coordinator and organiser are
   told. After agreeing it, the coordinator calls **`keep_original(change, actor,
   reason)`** -> `ORIGINAL_KEPT`; nothing is applied. Cancelling uses the existing
   cancel-event action; a new change request can be raised.
5. **History (AC5)** - `GET /api/change-requests/<id>/history/`: request, decision,
   who applied it, each arrangement's before/proposed values, outcome and reviewer,
   and the field changes recorded.

Readiness: a change `IN_REVIEW` blocks confirmation; SCRUM-70 period reviews only
block while their change is Approved or In review.

API: `POST /api/change-requests/<id>/apply/`, `POST .../keep-original/`,
`GET .../history/`, `GET /api/arrangement-reviews/?status=PENDING` (live work only:
change in review, event not cancelled/completed) and
`POST /api/arrangement-reviews/<id>/decide/`.

## For later gates

- **SCRUM-66 (Jerom), SCRUM-70 (Adilah):** APPLY is now the real producer of your
  reviews (`record_reviews`, `record_period_reviews`, `review_period`) - re-run your
  closure checks against `test_scrum_80_apply_approved_change.py`.
- **SCRUM-18 (Jerom):** APPLY calls `notify_attendees_of_change` with occurrence
  `change-applied:<id>`.
