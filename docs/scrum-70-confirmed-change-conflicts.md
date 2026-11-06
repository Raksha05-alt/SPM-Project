# SCRUM-70: confirmed-change conflicts

Branch: `feature/confirmed-change-conflicts`, based on main `c90125a`.

## Published integration contract

`apps.events.impact.venue_conflicts(event, proposed, target_bookings=...)` is
read-only and returns proposed periods, conflicting booking/event IDs, and an
explicit staff-review requirement. It reuses SCRUM-85 buffered half-open
occupancy. `shifted` translates sessions by the event start delta; main session
end follows the change in event duration, while breakout durations stay intact.
An explicit nonempty target list selects sessions; omitted/empty selects all
approved bookings. Confirm this period mapping when integrating ASSESS/APPLY.

Inside the approved-change transaction, **before editing event fields**, call
`period_conflicts.record_period_reviews(change_request, actor)`. It requires the
active assigned coordinator, an approved current revision and an unchanged
source snapshot, locks the event then venues, and recomputes occupancy. It saves
clear assessments as requiring staff review too, preserves original bookings,
and writes one coordinator notice per new review. Failure propagates to roll
back the caller's transaction. A replay reuses the same revision record.

`period_conflicts.review_period(review, actor, reason=...)` is the Venue Staff
callback. It checks fresh occupancy under the venue lock and records the real
actor/time/reason. A clear outcome is not a resource switch or future guarantee.
APPLY must perform suitability, block/hold eligibility and stock checks, switch
resources atomically, and invalidate Safety using its existing contract.

The existing permission-scoped venue-reviews API displays the affected period,
conflicting event IDs, and reason. Coordinator event details and Venue Staff's
“All requests” inbox display these records. Safety readiness blocks outstanding
or conflicting period reviews. Existing suitability reviews are independent.

## Deliberate integration boundary

Current main has INTAKE/SESSIONS but no ASSESS/APPLY action. This change does not
add a parallel approval/application workflow. SCRUM-78 must compose the preview;
SCRUM-80 must invoke the writer and staff callback through its real action/UI,
then complete resource replacement and fresh Safety/reconfirmation. Accordingly
SCRUM-70 remains incomplete for final end-to-end acceptance until that integration
passes (guide section 5). No preview is labelled staff-approved.

## Verification

`apps/events/tests/test_scrum_70_conflicts_after_change.py` includes pure period
mapping and persisted provider cases for conflicts, preservation, buffered
adjacency, permissions, stale source, replay and a race after preview. Approved
change rows in these tests are explicitly low-level fixtures, not evidence of
the missing SCRUM-80 producer. Run against PostgreSQL; do not substitute SQLite
for transaction/integration acceptance. Human correctness review and browser
acceptance remain pending. Migration 0015 adds records only; no booking backfill
or historical booking changes are needed.

Verification performed 4 November 2026:

- Ruff checks/format, Django system check and `git diff --check`: passed.
- Migration model comparison (`makemigrations --check --dry-run`): no changes.
  Database migration-history check could not connect; migration not applied.
- Frontend production build: passed.
- VenueReviews, VenueBookingInbox and CoordinatorEventDetail: 23 tests passed.
- Pure `shifted` cases: 3 passed.
- Seven persisted PostgreSQL cases: setup errors because localhost:5433 is
  unreachable; not passed. Docker Desktop engine is unavailable.
- Full regression, concurrency/rollback coverage, story coverage measurement,
  browser acceptance and real SCRUM-80 integration: pending.
- No commits or pushes performed.
