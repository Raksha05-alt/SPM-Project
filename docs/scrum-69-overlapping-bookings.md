# SCRUM-69 — G08 occupancy/conflict service

Branch: `feature/venue-booking-conflicts` (implementation guide section 6).
The user explicitly requested integration from `feature/venue-suitability` and no commits/pushes. That branch was fetched and merged with `--no-commit --no-ff`; the merge remains unfinished and its imported changes are staged by Git. SCRUM-69 edits remain uncommitted.

## Implemented contract

`apps.venues.occupancy.clashes(venue, starts_at, ends_at, exclude_booking_id=None)` returns fresh Approved bookings overlapping `[start, end)`, excluding Cancelled events. Pending/Rejected/Withdrawn bookings reserve nothing. Conflict references contain only booking ID, event ID and period; no names, contacts or event requirements.

Availability/calendar reads include conflict references and report `booked` when obstructed by bookings. Venue search and saved shortlist reassessment use those same fresh checks. The availability screen identifies the conflicting event and booking. Existing unverified-workflow/hold notices remain conservative.

`transition_booking` locks event, venue, then booking before changing state. Every approval rechecks occupancy after acquiring the venue lock, serializing different requests competing for that venue. The existing history and safety invalidation remain in the same transaction. Callers must follow the same lock order; G10 must add staff authorization, suitability/date-block/hour rechecks and notifications through its real decision action. No booking schema migration or Sprint 4 hold/buffer behavior was added.

## Cases and independent expected outcomes

Executable: `api/apps/venues/tests/test_scrum_69_overlapping_bookings.py`.

| Case | Setup/action | Expected result | Current evidence |
| --- | --- | --- | --- |
| S3-SCRUM-69-01 / AC1 | Approve 10:00–12:00; inspect 11:59–13:00 | Booked; first booking/event IDs identified | Backend blocked by unavailable PostgreSQL |
| S3-SCRUM-69-02 / AC2 | Approved 10:00–12:00; query 08:00–10:00 and 12:00–13:00 | Both free | Backend blocked |
| S3-SCRUM-69-03 / AC3 | Approve first; attempt overlapping second approval | Validation refusal; second Pending, no decision/history mutation | Service test authored; HTTP action awaits G10 |
| S3-SCRUM-69-04 / AC4 | Cancel occupying event; inspect/approve second | Obstruction disappears, second can approve | Model exclusion test authored; real cancellation journey awaits INT-03 |
| S3-SCRUM-69-05 / AC5 | Two Pending requests; approve one; reread other | Initially free, then conflicting; withdrawal clears | Service test authored; request/inbox journeys await G09/G10 |
| S3-SCRUM-69-05-concurrent | Two real PostgreSQL connections approve competing requests | Exactly one Approved and one Pending | Authored; blocked by unavailable PostgreSQL |

All periods above are 1 March 2027 in Asia/Singapore. Tests use persisted records and independent expected intervals. Correctness reviewer, teammate browser walkthrough and PO acceptance remain pending.

## Verification — 1 November 2026

- Ruff checks and formatting of changed Python modules: passed.
- TypeScript `npm run lint`: passed.
- `npm run test -- src/pages/VenueAvailability.test.tsx`: 7 passed, including conflicting event display.
- Git whitespace checks on staged merge and working edits: passed.
- PostgreSQL pytest execution: blocked at setup by connection timeout to localhost:5433. Docker engine unavailable. No backend pass or coverage claim.
- No manual browser journey, commit, push, PR, main integration or Jira update performed.

Remaining integration: G09 request validation calls shared availability; G10 real staff approval/inbox runs concurrency and refusal cases; INT-03 cancellation verifies release through the real action. This is the guide's G08 slice, not a claim that the full story meets Definition of Done.
