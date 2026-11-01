# SCRUM-67: Withdraw a venue booking request

Branch: `feature/venue-booking-withdrawal`, updated by fast-forward from `origin/main` at `6d47e91`. No commit or push performed.

Assigned coordinators can withdraw Pending or Approved requests from the event's Venue requests table. Approved withdrawal displays a confirmation warning; cancelling sends no request. The API requires the status the user saw and explicit confirmation for Approved records. It rereads assignment/status under event, venue and booking locks. Terminal bookings and closed events refuse changes.

`POST /api/events/<event_id>/venue-bookings/<booking_id>/withdraw/`

Body: `{"expected_status": "APPROVED", "confirm_release": true}`. Pending withdrawal uses `expected_status: "PENDING"` and does not require confirmation. A stale status or missing approved confirmation returns 409. Wrong roles/assignment return 403. Cross-event booking IDs return 404.

The existing transition service retains actor/time/history, releases occupancy by changing status, and supersedes Safety checks when an Approved arrangement changes. Staff receive durable `VENUE_WITHDRAWN` notifications in the same transaction. Withdrawal actor/time are exposed from retained history without replacing the original staff decision. Apply the new notification-choice migration during normal setup; development data was not migrated or seeded by this task.

## Acceptance cases

Executable cases live in `api/apps/venues/tests/test_scrum_67_withdraw_booking.py`:

| Case | Preconditions/action | Independent expected outcome |
| --- | --- | --- |
| S3-SCRUM-67-01 | Assigned coordinator withdraws real Pending API request; repeats | Withdrawn, exactly one notice per active Venue Staff, original history retained; repeat 409 |
| S3-SCRUM-67-02 | Withdraw approved 10:00–12:00 booking; another booking starts at 12:00 | First obstruction disappears from fresh availability; other booking remains approved/obstructing |
| S3-SCRUM-67-03 | Approved withdrawal without confirmation, then with confirmation | First 409 leaves Approved; confirmed action succeeds. UI cancel sends no API mutation |
| S3-SCRUM-67-04 | Read successful withdrawal | Displayed actor and parsed timestamp equal durable history values |
| S3-SCRUM-67-05 | Wrong coordinator/role, stale status, rejected booking, cancelled event; inject notification failure | Refuse invalid actions; failures roll back booking/history/Safety effects |

Specification and agent execution date: 1 November 2026, Singapore time. Human correctness review, manual browser walkthrough, PO acceptance and CI remain pending. No teammate review is claimed.

## Integration boundary

Latest main lacks the guide's G10 SCRUM-72 staff-decision endpoint/UI. Approved preconditions therefore use the existing real `transition_booking` contract in PostgreSQL tests. These fixtures do not prove the missing staff-decision journey. Full J2/J5 request ? staff approval ? withdrawal browser verification remains blocked until G10 is merged. Concurrency execution and owned-code coverage measurement remain pending; the implementation uses the published shared lock order.

## Agent verification results (1 November 2026)

- Final SCRUM-67 PostgreSQL suite: 8 passed, 17.84 seconds.
- Booking request, overlap, Safety contract and withdrawal regression selection: 112 passed, 217.46 seconds (collected before the last two withdrawal cases were added).
- VenuePlanner component suite: 7 passed, including approved confirmation/cancel.
- Frontend type check and production build: passed.
- Django system check, migration consistency check, changed Python lint and Git whitespace check: passed.
- Coverage was disabled for these focused executions; no coverage percentage is claimed.
- One overlapping test invocation encountered a test-database collision; the final 8-case run was executed sequentially and passed.

All runs used the local uncommitted working tree over main `6d47e91`. Tests used Django's PostgreSQL test database. No development database seed or migration was run. Human review/browser execution and full G10-dependent integration remain pending.
