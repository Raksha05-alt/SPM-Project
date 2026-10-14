# Week 7 customer changes and Week 9 clarifications

This is the change analysis for the six Week 7 customer changes and for the
answers ConnectSphere staff gave in the Week 9 clarification session. It follows
the course *Guide to Managing Changes*: change description, effect on the product
backlog, acceptance criteria, story points, design, then tests.

Branch: `feature/week7-customer-changes`.

## 1. Change descriptions

| # | Change | Why ConnectSphere needs it | Type |
|---|---|---|---|
| CR1 | Venue setup and turnaround time | Comparing only advertised times double-books rooms that are still being prepared or reset | New requirement |
| CR2 | Venue becomes unavailable after booking | Maintenance, equipment failure, renovation or safety problems arrive after events are booked | New requirement |
| CR3 | Multiple venues for one event | Conferences use one auditorium plus breakout rooms | New requirement; it also corrects the single-venue assumption in SCRUM-58 and SCRUM-59 |
| CR4 | Tentative venue holds expire | Staff hold rooms while coordinators finalise arrangements, and holds must not last forever | New requirement |
| CR5 | Event Coordinator Lead role | Requests go to an unassigned queue, and a Lead assigns and reassigns them | New requirement that **supersedes** SCRUM-51 auto-assignment |
| CR6 | Operational Safety Check | A Safety Officer must approve before an event can be confirmed | New requirement |
| CL1 | Room layout catalogue | "Should have the capability to add, edit, delete" | Clarification of SCRUM-9 / SCRUM-65 |
| CL2 | Clarification is offline, recorded in the system | "The system should have a means for recording the comments" | Clarification of SCRUM-49 |
| CL3 | Organisers cannot edit after submission | "All edits must be requested through the Coordinator" | Correction of US-03.1 / SCRUM-49 behaviour |
| CL4 | Coordinators edit until Confirmed | "Once an event is Confirmed, information fields cannot be changed directly" | Clarification of SCRUM-61 |

### Clarification answers and how we applied them

| Question (summarised) | Answer | Implementation |
|---|---|---|
| Who sets the hold expiry? Is there a maximum? | Venue Staff decide per venue, and they set and update it | Staff enter `hold_until` when approving and can change it with `update-hold`. The system only requires it to be in the future and before the booking starts. |
| When does a hold start? | After venue approval | Approving "as tentative hold" creates status **Held** |
| Who completes a hold? | Venue Staff approve, then the coordinator confirms | `confirm-hold` (coordinator) turns Held into Approved |
| Does a pending request block the slot? | No. A hold does, until it expires | Only Held and Approved reserve a venue (`HOLDING_STATUSES`). Pending requests show on the calendar as "requested" and do not reduce availability. |
| How long before expiry is the coordinator warned? | Not specified ("before or when") | We chose a warning **24 hours before expiry** (`HOLD_WARNING_HOURS`, configurable) and a second notice at expiry |
| Do setup and turnaround apply to equipment? | No, not in Release 1 | Buffers apply to venues only |
| Must buffers fit inside opening hours? | Venue Staff decide | Staff see a warning, not a refusal |
| Can sessions of one event overlap? | Yes. Parallel tracks use separate venue requests | One booking per session (`session_name`). Bookings of the **same** event in the same room do not need a buffer between them, but must not overlap. |
| Venue problem on a Confirmed event? | Notify, agree offline, revert to planning or change review | The disrupted booking puts a Confirmed event back to **Planning**. The coordinator and client are notified. |
| Does a safety Reject end the event? | No, it returns to planning, the same as Request changes | Both decisions keep the event in Planning and require a new check |
| Is Confirmed before or after safety approval? | After. The coordinator confirms once every approval is in | `confirm_event` refuses while the safety check is not approved |
| Who sends the event to the Safety Officer? | The coordinator, as with venue and technical approval | "Request safety check" appears once the venue and equipment are in place |
| Does the Safety Officer enter data? | No, they approve based on their own checks | They see a read-only fact sheet and choose a decision with a comment |
| Can coordinators see other coordinators' or unassigned events? | No. Leads see everything, and coordinators see only their own | Querysets are scoped per role, and cross-access returns an audited 403 |
| More than one Lead? | Supported, and every Lead sees every unassigned event | Leads are a role, not a single user |
| Whom does a Lead supervise? | The coordinators they allocated | `assigned_by` records the supervising Lead; `/lead/assignments?supervised=mine` filters on it |
| Can a Lead reassign after arrangements are confirmed? | Yes | Reassignment is allowed in every open status |
| Auto-assignment? | "No more system auto-assignment" | Removed |
| Re-check after a change to a confirmed event? | Yes. It goes through the change process, and all checks are needed again | `arrangements_changed()` supersedes the safety check and returns the event to Planning |
| Who cancels one venue of several? | The coordinator, and the others stay intact | Withdrawing one booking never touches the others |

## 2. Product backlog

New stories, in the format we already use (Scenario 2 of the guide: the original
stories stay Done, and the new behaviour is a new story).

| Key | Story | Points |
|---|---|---|
| CR1 / US-W7.1 | As Venue Staff, I want each venue to have setup and turnaround times so that bookings do not overlap the time we need to prepare and reset the room | 5 |
| CR2 / US-W7.2 | As Venue Staff, I want to mark a booked venue unavailable so that coordinators can arrange an alternative without the event being cancelled | 8 |
| CR3 / US-W7.3 | As an Event Coordinator, I want to book several venues for one event so that a conference can use a main hall and breakout rooms | 5 |
| CR4 / US-W7.4 | As Venue Staff, I want tentative holds to expire so that a venue is not reserved indefinitely | 8 |
| CR5 / US-W7.5 | As an Event Coordinator Lead, I want to assign and reassign submitted requests so that each event has the right coordinator | 8 |
| CR6 / US-W7.6 | As a Safety Officer, I want to review the operational safety of a planned event so that it is not confirmed until it is safe | 8 |
| CL1 / US-W7.7 | As Venue Staff, I want to add, edit and delete room layouts so that the catalogue matches our rooms | 3 |
| CL2 / SCRUM-49 (updated) | Record offline clarification conversations as notes on the request | 2 (remaining work) |
| CL3+CL4 / US-03.1, SCRUM-61 (updated) | Organisers edit drafts only; coordinators edit until confirmed | 2 (remaining work) |

**Superseded acceptance criteria.** SCRUM-51 AC1, AC2 and AC5 (random automatic
assignment, assignment on submit, and the fallback when no coordinator is
available) no longer apply. The story stays Done for what it delivered. Its
regressions still pass (submission notifications, an unassigned request is
flagged for attention), and CR5 replaces the rest. The old CoordinatorQueue
screen is now the Lead queue.

**Updated criteria that remain valid.** SCRUM-58 (confirm) now also requires
every venue booking to be approved (not held, pending or disrupted) and the
safety check to be approved. SCRUM-59 (significant changes) now routes changes
to a confirmed event through a change request, which re-runs the checks. SCRUM-61
(update during planning) is limited to the assigned coordinator, and the client
cannot edit.

## 3. Acceptance criteria and tests

Every criterion is a test named after it.

| Change | Criteria | Backend test file |
|---|---|---|
| CR1 | CR1-AC1 to AC7 | `api/apps/venues/tests/test_cr_01_setup_turnaround.py` |
| CR2 | CR2-AC1 to AC7 | `api/apps/venues/tests/test_cr_02_venue_unavailable.py` |
| CR3 | CR3-AC1 to AC7 | `api/apps/venues/tests/test_cr_03_multiple_venues.py` |
| CR4 | CR4-AC1 to AC8 | `api/apps/venues/tests/test_cr_04_tentative_holds.py` |
| CR5 | CR5-AC1 to AC7 | `api/apps/events/tests/test_cr_05_lead_assignment.py`, `test_cr_05_reassigned_mid_request.py` |
| CR6 | CR6-AC1 to AC7 | `api/apps/safety/tests/test_cr_06_safety_check.py` |
| CL1 | CL-L-AC1 to AC5 | `api/apps/venues/tests/test_cl_layout_catalogue.py` |
| CL2, CL3 | SCRUM-49 AC1 to AC3 (notes, resume review, no client edit) | `api/apps/events/tests/test_request_clarification.py` |
| CL4 | SCRUM-61 AC1 and AC2, SCRUM-59 AC1 | `test_scrum_61_update_during_planning.py`, `test_scrum_59_significant_changes.py` |

The tests cover several levels:

- **Unit and functional:** the backend pytest suites above. Production code has 100% line and branch coverage, which `pytest.ini` enforces.
- **Integration:** concurrency tests on real PostgreSQL row locks. They cover two approvals racing for the same slot and a reassignment racing a coordinator's decision.
- **Frontend:** Vitest and Testing Library for the Lead queue and event, the safety queue and check, the readiness panel, the layout catalogue, hold and disruption handling in the venue planner, and the booking inbox.
- **End to end:** two Playwright journeys run against the real API.
  - `web/e2e/draft-submit-queue.spec.ts`: organiser submits, Lead assigns, coordinator sees the event.
  - `web/e2e/week7-hold-safety-confirm.spec.ts`: the full path from submit through Lead assign, approve, Harbour Hall request with buffers, tentative hold, coordinator confirming the hold, safety check request, a refused confirm, Safety Officer approval, and finally confirm.
- **Regression:** the whole original suite still runs. Tests that encoded superseded behaviour were rewritten and say so in their docstrings.

## 4. Design

### Domain and data model

| Model | Change |
|---|---|
| `accounts.User.role` | New roles `COORDINATOR_LEAD` and `SAFETY_OFFICER` (landing at `/lead` and `/safety`) |
| `venues.Venue` | `setup_minutes`, `turnaround_minutes`, `safety_notes` |
| `venues.VenueBlock` | `category`: maintenance, equipment failure, renovation, safety or other |
| `venues.VenueBooking` | `session_name`. Statuses **Held**, **Expired** and **Disrupted**. Hold fields `hold_expires_at`, `hold_set_by`, `hold_warning_sent_at`, `hold_confirmed_by/at`, `expired_at`. Disruption fields `disrupted_at`, `disruption_reason` and `replaced_by`. |
| `venues.LayoutType` (new) | A layout catalogue (code, name, description, active). It replaces the fixed enum, and the old values are seeded. |
| `events.EventRequest` | `assigned_by` (the supervising Lead), `assigned_at` |
| `events.ClarificationComment` (new) | Notes recorded against a clarification request |
| `safety.SafetyCheck` (new app) | Pending, Approved, Rejected, Changes requested or Superseded. Records requester, decision, comment and a superseded reason. At most one current check per event (partial unique constraint). |
| `notifications.NotificationKind` | Submitted, clarification comment, hold expiring, hold expired, venue unavailable, safety requested, safety decided |

Event status machine: **Confirmed → Planning** is a new permitted transition. It
is used when a venue is disrupted or an approved change alters the arrangements.

### Key rules (where they live)

- **Occupancy (CR1, CR3)** lives in `apps/venues/occupancy.py`. A booking occupies `[start - setup, end + turnaround]`. Two bookings of different events clash if the gap between their sessions is less than the earlier one's turnaround plus the later one's setup. Bookings of the same event in one room clash only if the sessions themselves overlap. Venue blocks are checked against the occupied window. Approval takes a row lock on the venue, so two approvals for one slot cannot both succeed.
- **Holds (CR4)** live in `apps/venues/bookings.py`. `holding_filter()` treats a Held booking as reserving the venue only while `hold_expires_at > now`, so an expired hold frees the slot even before housekeeping runs. `process_holds()` sends the warning and marks holds Expired. It runs when the venue, booking or confirmation screens are used, and from the management command `process_venue_holds` (schedule it every 15 minutes in production).
- **Disruption (CR2)**: a block, or switching a venue out of service, marks the affected future bookings Disrupted. A Confirmed event goes back to Planning, and the coordinator and client are notified. `replace` creates a new request linked through `replaced_by`, and the original booking and event details are kept.
- **Lead assignment (CR5)**: `submit_event` leaves the request unassigned and notifies all Leads. `assign_coordinator` is for Leads only; it records `assigned_by` and notifies the new coordinator, the previous coordinator and the client. Permission classes allow a coordinator only on events assigned to them, including reads.
- **Safety (CR6)** lives in `apps/safety/services.py`. A check can be requested only when `arrangement_gaps()` is empty. A rejection or change request leaves the event in Planning. Any later change to venue or equipment arrangements calls `arrangements_changed()`, which supersedes the current check and puts a Confirmed event back to Planning. `confirm_event` lists everything still missing: the safety check, and each venue or equipment item.

### API additions

| Endpoint | Who |
|---|---|
| `POST /api/events/{id}/assign/` (`reassign/` is an alias) | Lead |
| `GET /api/events/queue/` (unassigned), `GET /api/events/assignments/?supervised=mine`, `GET /api/coordinators/` | Lead |
| `POST /api/events/{id}/comment/`, `POST /api/events/{id}/resume-review/` | Assigned coordinator (and the client for comments) |
| `GET /api/events/{id}/readiness/` | Assigned coordinator, Lead |
| `POST /api/venue-bookings/{id}/approve/` with `hold_until`, `POST .../update-hold/` | Venue Staff |
| `POST /api/venue-bookings/{id}/confirm-hold/`, `POST .../replace/` | Assigned coordinator |
| `GET/POST /api/events/{id}/safety-checks/` | Coordinator requests, internal roles read |
| `GET /api/safety-checks/`, `POST /api/safety-checks/{id}/decide/` | Safety Officer |
| `GET/POST/PATCH/DELETE /api/layouts/` | Venue Staff write; internal roles and clients read |

### Screens

| Role | Screens |
|---|---|
| Lead | Unassigned queue (`/lead`), all assignments with a "supervised by me" filter (`/lead/assignments`), event detail with assign and reassign |
| Safety Officer | Queue (`/safety`), check detail showing the facts and the decision form |
| Coordinator | Readiness panel with safety check request, hold confirmation, disrupted booking replacement, session names, buffer warnings, clarification notes and resume review |
| Venue Staff | Buffers and safety notes on the venue form, block categories with affected bookings, approve as tentative hold, held bookings list, room layout catalogue |

## 5. Assumptions to confirm with ConnectSphere

1. The hold expiry warning goes out 24 hours before expiry. This is configurable.
2. Bookings of the same event in one room do not need setup or turnaround between them.
3. The main room follows the event's attendance; breakout rooms keep their own attendance.
4. A Safety Officer's comment is required for Reject and Request changes, and optional for Approve.
