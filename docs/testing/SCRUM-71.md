# SCRUM-71 - Flag venues that do not meet the event's requirements

Owner: Jerom. Branch: `feature/venue-suitability`. Sprint 3 gate **G07**.

History: the first slice (commit `17f8b79`, 23 October 2026) was built on main `156fc22` and covered the original AC1–AC5. For G07, current main `9b33974` (G02–G06) was merged in on 1 November 2026, and the assessment was reconciled with the layout catalogue (SCRUM-91), the shared operating-hours rule and assigned-coordinator ownership (SCRUM-89).

## Scope in Sprint 3

| AC | Sprint 3 obligation | Status in this gate |
| --- | --- | --- |
| AC1 | Attendance above capacity is flagged with the reason | Implemented and tested |
| AC2 | Unsupported layout or a missing required accessibility facility is flagged with the reason | Implemented and tested |
| AC3 | Timing outside operating hours is flagged with the reason | Implemented and tested |
| AC4 | Requesting an unsuitable venue is blocked, stating the unmet requirements | **Guard published and tested** (`ensure_suitable`, using the booking request's stored requirements). The request endpoint is SCRUM-11 (Shalika, **G09**), which must call it; the end-to-end refusal test completes there. Not passed yet |
| AC5 | A venue meeting every requirement is suitable with no warnings | Implemented and tested |
| AC6 | Buffer-only warning (Week 7 change 1) | **Scheduled for Sprint 4** (SCRUM-85). Not implemented and not passed |

The verification checklist's `buffer_warnings` belongs to that Sprint 4 work.

## Shared contract

Module: `api/apps/venues/suitability.py`.

| Name | Meaning | Who calls it |
| --- | --- | --- |
| `Requirements.for_event(event, required_facilities=(), wheelchair_access_required=False)` | The event's attendance, layout and preferred period, plus what the coordinator says is required | The coordinator's check (this gate) |
| `Requirements.for_booking(booking)` | A booking request's stored attendance, layout, required facilities, wheelchair access and period. Also accepts cleaned values before saving | SCRUM-11 request action (G09), SCRUM-72 decisions (G10) |
| `assess(venue, requirements, labels=None)` | Every unmet requirement, as `Reason(requirement, message)`, in a fixed order | All of the above; SCRUM-66 later |
| `ensure_suitable(venue, requirements)` | AC4 guard: raises `VenueUnsuitable` (with `.reasons`) unless suitable. Call it inside the action's transaction, after locking the venue row | G09 request, G10 decision |
| `check_suitability(event, venue, ...)` | Convenience wrapper for an event | Existing callers |

**Requirement codes:** `CAPACITY`, `LAYOUT`, `ACCESSIBILITY` (wheelchair access), `FACILITY` (each required facility), `OPERATING_HOURS`.

### Rules

- **Capacity** equal to attendance fits.
- **Layouts** are catalogue codes. Reasons use the layout's current name, a retired layout already on an event is still assessed, and a newly added layout works like any other.
- **Wheelchair access** is met when the venue records it, or when the venue's access is unrecorded but its facilities list "Wheelchair access". A venue recorded as without access is not suitable. Typing "Wheelchair access" as a facility is the same requirement as the checkbox.
- **Required facilities** match ignoring case and surrounding spaces. Free-text accessibility notes are kept for staff and are not interpreted.
- **Operating hours** come from `apps.venues.availability.operating_hours_problem`, the one rule now shared by availability, discovery and suitability. It uses Singapore time; opening and closing times are inclusive; one second outside fails; unrecorded hours, closed days, overnight and reversed periods fail. `within_operating_hours` is now `operating_hours_problem(...) is None`. Its yes/no answer is unchanged, except that a reversed period now fails.
- **Suitability is not availability.** Bookings, blocks and out-of-service status are not suitability reasons. The API says so (`not_checked`) and shows `in_service` beside each result.

## API

`GET /api/events/<event_id>/venue-suitability/` (every venue) and `.../<venue_id>/` (one venue).

- **Query:** `facilities` (repeated or comma-separated) and `wheelchair=true|false`. Any other `wheelchair` value gets a 400.
- **Response:** `requirements` (what was checked, with the layout's current name), `not_checked`, and for each venue `suitable`, `reasons` and `in_service`.
- **Access:** only the event's currently assigned coordinator. Other coordinators, reassigned coordinators, Leads, Organisers, Attendees, Venue Staff, Technical Support, Safety Officers, anonymous callers and drafts are refused with 403, and each refusal is audited. Unknown events and venues return 404.

**UI:** the "Venue suitability" panel on the assigned coordinator's event page. It has a wheelchair checkbox and a required-facilities box, and shows what was checked, each venue's reasons, an "Out of service" tag and a "Not checked here" note.

## Test evidence

Records: [`test-cases/S3-SCRUM-71-suitability.csv`](../test-cases/S3-SCRUM-71-suitability.csv). API tests: `api/apps/venues/tests/test_scrum_71_suitability.py`. Component tests: `web/src/components/venues/VenueSuitability.test.tsx`.

Run on 1 November 2026 by Claude (AI assistant) for Jerom, on local PostgreSQL 16, Python 3.12 and Node 22 (CI uses Node 20). The base was main `9b33974` merged into this branch. This is an agent run, not a teammate's correctness review.

| Check | Result |
| --- | --- |
| `manage.py check`, `makemigrations --check`, `ruff check .`, `ruff format --check .` | Clean |
| Venue and safety suites | 412 passed |
| Full backend suite (`pytest --cov-branch`) | 795 passed; `suitability.py`, `suitability_views.py`, `availability.py`, `discovery.py` 100% statements and branches; production-only coverage 99% |
| `npm run lint`, `npm run test`, `npm run build` | Clean; 142 tests passed; build succeeded |
| Agent browser check (Chromium, real API and database; event assigned through the real Lead assignment service) | Assigned coordinator ran the check with wheelchair access and two facilities; every reason and the "Not checked here" note shown; a second coordinator got 403 |
| Seeded fault: capacity `<=` changed to `<` | Caught by the capacity-60-equal case and AC5 |
| Seeded fault: hours boundary `<` changed to `<=` | Caught by the exactly-opening-to-closing case |
| Seeded fault: assigned-coordinator check removed | Caught by the other-coordinator and reassigned-coordinator cases |

### Not yet done

- **AC4 end-to-end refusal** through the SCRUM-11 request endpoint: Blocked until G09.
- **J2 browser journey** (`web/e2e/sprint3-venue-planning.spec.ts`): Blocked until G09/G10 exist.
- **Teammate code and test review**, and a team member's manual check with demo data: pending.
- **AC6:** scheduled for Sprint 4 (SCRUM-85).
