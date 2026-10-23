# SCRUM-71 - Flag venues that do not meet the event's requirements

Owner: Jerom. Branch: `feature/venue-suitability`, based on `main` at `156fc22`
(the approved baseline `e50c746` plus the merged SCRUM-65/SCRUM-9 venue model, PR #4).

Scope: the **original** acceptance criteria AC1-AC5 from the 7 October snapshot
(`sprint-2-implementation-guide.md`, Appendix A). The live-Jira AC6 (setup/turnaround
buffer warning) belongs to SCRUM-85 and is not implemented here.

## What was built

| Part | Location |
| --- | --- |
| Suitability rules | `api/apps/venues/suitability.py` (`check_suitability`) |
| API | `GET /api/events/<event_id>/venue-suitability/` (every venue) and `.../<venue_id>/` (one venue); optional `?facilities=` repeated or comma separated. Event Coordinators only; refusals are audited. |
| UI | "Venue suitability" section on the coordinator's event page: `web/src/components/venues/VenueSuitability.tsx` |
| API tests | `api/apps/venues/tests/test_scrum_71_suitability.py` |
| UI tests | `web/src/components/venues/VenueSuitability.test.tsx` |

## Acceptance criteria to tests

| AC | Expected behaviour | Cases (selector in the API test file unless noted) | Level | Result |
| --- | --- | --- | --- | --- |
| AC1 | Attendance above capacity is flagged with the reason | `test_ac1_attendance_above_capacity_is_flagged[one-below-capacity, exactly-capacity, one-above-capacity]`, `test_ac1_the_capacity_reason_states_both_numbers`, UI `AC1-AC2 shows each unsuitable venue…` | Unit, component | Pass |
| AC2 | Unsupported layout or missing required accessibility facility is flagged with the reason | `test_ac2_an_unsupported_layout_is_flagged_with_its_name`, `…no_layouts_recorded…`, `…no_layout_preference_is_not_checked`, `…missing_accessibility_facility_is_flagged_by_name`, `…match_regardless_of_case_or_spacing`, `…wheelchair_access_uses_the_venue_record[step-free, not-step-free, not-recorded]`, `…each_missing_facility_gets_its_own_reason`, `test_api_required_facilities_come_from_the_query[repeated, comma-separated]`, UI `AC2 sends the required accessibility facilities…` | Unit, API, component | Pass |
| AC3 | Event timing outside operating hours is flagged with the reason | `test_ac3_an_event_inside_operating_hours_passes[exactly-opening-to-closing, well-inside]`, `test_ac3_an_event_outside_operating_hours_is_flagged[starts-before-opening, ends-after-closing, closed-day, overnight]`, `…compared_in_singapore_time`, `…unrecorded_hours_cannot_confirm_the_timing[3 cases]`, `…event_without_times_is_not_checked_for_hours` | Unit | Pass |
| AC1-3 | Every unmet requirement is stated together | `test_every_unmet_requirement_is_stated_at_once` | Unit | Pass |
| AC4 | Requesting an unsuitable venue is blocked, stating the unmet requirements | **Not implemented.** No venue-request/booking action exists on `main` (SCRUM-11/72/69 are outside Sprint 2). `check_suitability` is ready to guard that action. | — | **Blocked** |
| AC5 | A venue meeting every requirement is suitable with no warnings | `test_ac5_a_venue_meeting_every_requirement_has_no_warnings`, `test_api_ac5_a_suitable_venue_has_no_reasons`, UI `AC5 shows a suitable venue with no warnings` | Unit, API, component | Pass |

Supporting checks: coordinator-only access with audited refusals for Organiser, Attendee,
Venue Staff, Technical Support and anonymous callers; drafts hidden from coordinators; unknown
venue returns 404; the check changes no venue or event record; UI does not call the API until
asked, and shows an error message when the check fails.

## Executed run

| Field | Value |
| --- | --- |
| Base SHA | `156fc22` plus this branch's commit |
| Environment | Linux, Python 3.13, PostgreSQL 16, Node 22 (CI uses Python 3.12 / Node 20) |
| Date | 23 October 2026 |
| API | `manage.py check` clean; `makemigrations --check` no changes; `ruff check` and `ruff format --check` clean; `pytest`: **274 passed**, total coverage 99.70%; `suitability.py` and `suitability_views.py` 100% |
| Web | `npm run lint` clean; `npm run test`: **71 passed**; `npm run build` succeeded |
| Not run | Playwright E2E (no SCRUM-71 journey written; AC4 journey cannot exist yet) |

## Provisional decisions awaiting the team

1. **Required accessibility facilities.** `EventRequest.accessibility_needs` is free text, so
   the coordinator enters the required facilities when running the check. "Wheelchair access"
   is met by `Venue.wheelchair_access = True`; other names must appear in `Venue.facilities`
   (case-insensitive). If the team adds a structured field to the event, only
   `required_facilities()` in the view needs to change.
2. **Unrecorded operating hours** are flagged as unsuitable, because the timing cannot be
   confirmed.
3. **Boundaries and time zone.** Starting exactly at opening and ending exactly at closing
   passes. Times are compared in `Asia/Singapore`. Overnight events and closed days fail.
4. **AC4 integration.** Agree the owner and minimum venue-request slice; that action should call
   `check_suitability` and refuse with HTTP 4xx and the reasons, creating no booking.

Not yet done for the Definition of Done: teammate PR review, merge with green CI, manual check
with demo data, and sprint-review demo.
