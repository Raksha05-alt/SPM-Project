# SCRUM-67: Withdraw a venue booking request

Branch: `feature/venue-booking-withdrawal`, initially based on `6d47e91`. The integration below merges the SCRUM-72 main baseline `8734ca5` while preserving both authors' commits.

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

The original eight cases preceded G10 and use `transition_booking` for approved preconditions. The added integration cases exercise the actual request, staff approval and withdrawal endpoints. The browser journey performs those actions through the UI, including cancelling and accepting the release warning. Safety records in service tests remain explicit fixture preconditions; they do not establish the later G20/G21 Safety-to-confirmation journey. Event cancellation/resource release belongs to G16b.

## Initial agent verification (1 November 2026, before G10 integration)

- Final SCRUM-67 PostgreSQL suite: 8 passed, 17.84 seconds.
- Booking request, overlap, Safety contract and withdrawal regression selection: 112 passed, 217.46 seconds (collected before the last two withdrawal cases were added).
- VenuePlanner component suite: 7 passed, including approved confirmation/cancel.
- Frontend type check and production build: passed.
- Django system check, migration consistency check, changed Python lint and Git whitespace check: passed.
- Coverage was disabled for these focused executions; no coverage percentage is claimed.
- One overlapping test invocation encountered a test-database collision; the final 8-case run was executed sequentially and passed.

All runs used the local uncommitted working tree over main `6d47e91`. Tests used Django's PostgreSQL test database. No development database seed or migration was run. Human review/browser execution and full G10-dependent integration remain pending.

## G10/G11 integration verification (1 November 2026)

The merge retains both decision and withdrawal services, routes and notifications. Migration `0010_merge_booking_notice_kinds` depends on both published `0009` migrations and preserves both choice values; neither published migration is rewritten. Upgrade checks from each head retained existing notices, 10 users and three events. Fresh migrations and `makemigrations --check` passed.

The withdrawal button now uses the actual `UNDER_REVIEW` code. The browser test uses an exact venue-cell selector because the withdrawal button also names the venue. The guide's invalid legacy dash encoding was normalized to UTF-8.

- Full local backend regression before the final two permission cases: **898 passed**. The final focused run covers all eight original withdrawal cases and seven integration cases: **15 passed**. Fresh PR CI verifies the final complete suite.
- SCRUM-67 Python scope (`withdraw_booking`, withdrawal view/input serializer and withdrawal-display helpers): **49/49 executable statements and 8/8 measured branch arcs**. This is not a whole-backend or frontend coverage claim.
- Frontend: **158 component tests passed**; type checking/production build passed.
- Real browser regression: **9 passed**, no skips, retries or mocked API responses. The earlier run exposed an ambiguous selector; the corrected final run passed all nine.
- PostgreSQL approval-versus-withdrawal race: exactly one success and one conflict refusal. Notification failure rolls back withdrawal/history/Safety supersession while preserving the original decision. An assignment changed after the initial permission check is reread and refused with an audit record.

Execution was by the AI assistant for Nethren using an isolated disposable PostgreSQL database. Individual records: `test-cases/SCRUM-67-72-integration.csv`. Team correctness review, a team member's browser check and PO acceptance remain unrecorded; agent checks do not establish them.

Tested application/test source fingerprint (excluding documentation): `17c9dcdff2e70312bb6572b6d52f0a33849c4cb5c9859330cf8b29ef384d5f72`.
