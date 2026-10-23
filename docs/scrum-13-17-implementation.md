# SCRUM-13 and SCRUM-17 implementation notes

Implementation date: 23 October 2026. Branch: `feature/venue-availability`.

The existing branch was fast-forwarded from `e50c746` to fetched `origin/main`
`156fc22`, as the user requested. No commit or push was made. The merged venue
foundation is inherited work, not part of the new availability implementation.
`origin/feature/venue-layouts` was inspected at `fa50274`; it contains no booking
model or booking action and was not merged or copied.

The implementation guide supplied branch ownership and original story scope.
The user explicitly chose the screenshot's pending-request rule: requested
periods must eventually be displayed but remain available. After inspecting
the layouts branch, the user chose to leave booking-dependent criteria
incomplete. No booking/hold model, decision workflow, expiry job, disruption
workflow or later change-story functionality has been introduced.

## Implemented behavior

- Venue Staff create, edit and remove persisted blocks with a nonblank reason,
  start and end. Invalid intervals are refused by the API and a database check
  constraint. Writes lock the parent venue and save history in the same
  transaction; a history failure rolls back the change.
- History retains created/updated/removed snapshots, actor and timestamp even
  after block removal. The initial snapshot plus successive snapshots retain
  earlier values. History is readable through the API and staff screen.
- Catalogue responses display `Blocked` during a current block. Expired blocks
  remain in history but stop obstructing later periods. Other obstructions
  (operating hours, closed days and out-of-service status) still apply.
- Coordinators and Venue Staff can open `/venues/availability`, select a venue
  and continuous date/time range, check its status, and search for venues open
  and unblocked for that range. Staff also have block controls and history.
- API and page guards refuse Organisers and Attendees. Calendar endpoints also
  refuse Technical Support; this implementation grants access only to the
  coordinator and venue-staff roles. API refusals use the existing audit hook.

## Time and API contract

All UI input and output uses Asia/Singapore (UTC+08:00), independent of the
browser timezone. The API accepts ISO 8601 datetimes; offset-free input uses
the existing Django Singapore timezone. Ranges are half-open `[start, end)`;
an end equal to another range's start is adjacent, not overlapping. End must
be later than start. This boundary convention should be reviewed by the team.

The existing venue schema supports same-day opening and closing hours. A
continuous range spanning nights includes closed time and is unavailable.
Missing hours are treated as unavailable. An overlapping block has precedence
over the general unavailable status; block reasons and exact times are returned.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/venues/{id}/availability/?starts_at=...&ends_at=...` | Period status, available boolean, timezone and overlapping blocks |
| `GET /api/venues/available/?starts_at=...&ends_at=...` | Venues open, in service and unblocked for the period |
| `GET/POST /api/venues/{id}/blocks/` | Read blocks / staff create |
| `PATCH/DELETE /api/venues/{id}/blocks/{block_id}/` | Staff edit/remove |
| `GET /api/venues/{id}/blocks/history/` | Durable snapshots and actors |

These availability endpoints currently consider blocks and operating hours
only. They must gain the real booking/hold integration before being treated as
complete booking availability. The response is calculated afresh for each API
request; the screen refreshes after block changes and repeated checks.

## Acceptance evidence and outstanding work

| Story criterion | Implementation / executable evidence | Status |
| --- | --- | --- |
| SCRUM-13 AC1 | `test_create_edit_remove_retains_history`, `test_invalid_create_has_no_side_effects`; staff form tests | Implemented |
| SCRUM-13 AC2 | `test_current_status_and_expiry`, availability response and block reasons in UI | Implemented |
| SCRUM-13 AC3 | `test_search_excludes_blocked_venue_and_refreshes`; period-search UI test | Implemented for blocks/hours; booking occupancy remains dependent |
| SCRUM-13 AC4 | No real booking action exists in main or layouts branch | Incomplete, deferred by user |
| SCRUM-13 AC5 | `test_current_status_and_expiry`, `test_expired_block_does_not_override_other_obstructions`, boundary tests | Implemented for blocks/hours; booking occupancy remains dependent |
| SCRUM-13 AC6 | Create/edit/remove history test, invalid edit, cross-venue protection, atomic rollback tests; UI edit/remove tests | Implemented |
| SCRUM-17 AC1 | Date/time-range endpoint and screen; `test_available_and_fresh_block_updates`, UI period test | Implemented for blocks/hours |
| SCRUM-17 AC2 | Available/blocked/unavailable returned; operating-hour and block tests | Partial: real requested/tentative/confirmed records are absent |
| SCRUM-17 AC3 | Fresh block reads and cache refresh tests | Partial: booking/hold changes cannot be verified |
| SCRUM-17 AC4 | `test_boundaries`, `test_missing_hours_closed_day_and_overnight`, `test_utc_matches_singapore` | Implemented |
| SCRUM-17 AC5 | Direct API reads refused and audited; guarded page tests for both refused roles | Implemented |

The API tests are in `api/apps/venues/tests/test_scrum_13_block_venue.py` and
`test_scrum_17_venue_availability.py`; UI tests are in
`web/src/pages/VenueAvailability.test.tsx`.

## Running locally

Start the project's PostgreSQL service and run `python manage.py migrate` from
`api` before using the new endpoints. The new migration is
`0002_venueblockhistory_venueblock.py`. No migration was applied to the user's
development database during this task because PostgreSQL was unreachable and
Docker was stopped.

Sign in as Venue Staff or Event Coordinator and use the **Venue availability**
header link. Staff can create a block, check a period overlapping it, edit or
remove it, and inspect history. Coordinator search omits blocked periods.
Dates after the block ends still respect the venue's hours and service status.

Local automated verification uses a temporary in-memory SQLite database, with
the settings overridden only in the test process. Production settings are
unchanged. PostgreSQL concurrency and full database-specific verification,
real app browser acceptance, peer review and demo remain outstanding. No human
review, sprint completion, historical execution or demo is claimed.

## Verification results (23 October 2026)

- Focused SCRUM-13/17 API suites: **34 passed** using SQLite and the normal
  password hasher. Final venue regression suites: **92 passed** using SQLite
  and a faster test-process-only password hasher.
- Broader API suite using the same SQLite/test-hasher overrides: **266 passed,
  1 failed, 2 deselected**. The two excluded tests require PostgreSQL locks:
  `test_concurrent_submissions_assign_and_notify_only_once` and
  `test_pending_edit_holds_the_event_lock_until_saved_then_rejection_preserves_changes`.
- The failure was the unchanged
  `apps/core/tests/test_audit_log.py::test_rows_are_newest_first`. It passed on
  focused rerun alongside all 92 venue tests (**93 passed**). Its ordering uses
  only `-created_at`, so equal timestamps are a likely cause. Core audit code
  and tests were left untouched. The broader run is not claimed fully green.
- That broader run measured **100% statement coverage** for each of
  `availability.py`, `availability_views.py`, and `block_serializers.py`.
  The aggregate includes existing test files and is not used as an acceptance
  or production-only coverage claim.
- Complete web suite: **70 passed** across 15 files, including six new
  availability tests. TypeScript compilation and production Vite build passed.
- Ruff lint and formatting checks passed for the API application/configuration
  sources. Django system checks passed; `makemigrations --check --dry-run`
  reported no changes. `git diff --check` passed.

The long initial broad run was stopped and replaced with the test-hasher run;
no application password settings were edited. No local production database was
changed. Re-run the standard project `pytest` command against PostgreSQL before
claiming full CI or concurrency validation.
