# SCRUM-90 Operational Safety Check

Owner: Jerom. Story: SCRUM-90 (Week 7 customer change 6), epic SCRUM-84.
Delivered in two gates of the Sprint 3 implementation guide:

| Gate | Branch | Content | Required on main first |
| --- | --- | --- | --- |
| G04 | `feature/safety-contract` | Safety Officer role, `SafetyCheck` model, arrangement version, readiness predicates, invalidation service, fail-closed confirmation guard, booking-contract hook | G02 (PR #10, merged), G03 (equipment contract, PR #9) |
| G20 | `feature/operational-safety` | Request and decision API, Safety Officer screens, coordinator panel, venue safety information | G04, G10, G14, G16a, G17 |

## G04 shared contract

Module: `api/apps/safety/services.py`.

| Function | Meaning | Who calls it |
| --- | --- | --- |
| `arrangement_gaps(event)` | Venue and technical arrangements not yet in place, one line per real record. Empty means a safety check may be requested. | G20 request action; any readiness view |
| `confirmation_gaps(event)` | `arrangement_gaps` plus a current approved safety check. | SCRUM-58 confirm action (G21); `transition_event` |
| `arrangement_version(event)` | The version a check reviewed: date, time, attendance, approved venue bookings, current technical approval, open equipment requests and active reservations. | Stored on each check; compared by `is_stale` |
| `arrangements_changed(event, reason, actor)` | Supersedes the current check (keeping its decision) and returns a Confirmed event to Planning, with history, audit and notices. Atomic: rolls back with the caller. | Every resource action that changes arrangements (INT-04) |
| `ensure_can_confirm(event)` | Raises `ConfirmationBlocked(missing)` unless `confirmation_gaps` is empty. | `apps.events.services.transition_event` for every move to Confirmed |

### Rules

- **Arrangements in place** means every booking for the event that is not Pending, with at least one Approved, and each approved venue in service and not blocked during its booked period (half-open `[start, end)`). It also means a Technical Support approval of the current equipment-plan revision, with every open equipment request reserved by an active reservation. An explicit "no equipment required" technical approval counts; an empty plan alone does not.
- **Confirmation** additionally requires the current check to be Approved and to have reviewed the current arrangement version.
- **Stale approvals never pass.** Even if a producer forgets to call `arrangements_changed`, a different `arrangement_version` makes `confirmation_gaps` report the check as out of date.
- **Booking hook.** `apps.venues.bookings.transition_booking` calls `arrangements_changed` whenever a booking moves into or out of Approved. SCRUM-72 decisions and SCRUM-67 withdrawal get invalidation without extra code. A Pending → Rejected decision does not touch the check.
- **No generic status edit.** `CONFIRMED → PLANNING` was added to the status machine, but only `arrangements_changed` uses it. No endpoint exposes it.
- **Lock order.** Event row, venue rows by ID, equipment-type rows by ID, booking/reservation rows, then the safety check row. `arrangements_changed` re-locks the event row (a no-op when the caller already holds it). That serialises it with Safety decisions.

### Equipment producers still to integrate

The equipment foundation (G03) has no reservation, release or amendment actions yet. When those land (G16a, G16b, G17), each action must call `arrangements_changed(event, reason, actor)` inside its transaction. Until then the arrangement version still makes a changed plan's old approval stale for confirmation. A Confirmed event only returns to Planning eagerly when the action calls the service.

### Migrations

| App | Migration | Change |
| --- | --- | --- |
| accounts | `0004_safety_officer_role` | Adds `SAFETY_OFFICER` to `User.role` choices |
| notifications | `0006_safety_check_kinds` | Adds four notification kinds |
| safety | `0001_initial` | `SafetyCheck` with one-current-check, decision-actor and negative-comment constraints |

## Test evidence (G04)

Records: [`test-cases/S3-SCRUM-90-safety.csv`](test-cases/S3-SCRUM-90-safety.csv).
Tests: `api/apps/safety/tests/test_scrum_90_safety_contract.py` (49 cases).

Run on 29 October 2026 by Claude (AI assistant) for Jerom, on local PostgreSQL 16 and Python 3.12. The base was current main `3e30be9` merged with `feature/equipment-contract` `5ba646a` (PR #9), the expected main after G03. This is an agent execution, not a teammate's correctness review; the reviewer fields stay pending.

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .`, `manage.py check`, `makemigrations --check` | Clean |
| Full backend suite | 641 passed |
| `apps/safety` statements / branches | 100% / 100% |
| Production-only coverage (tests, migrations excluded), whole API | 99% (2121 statements, 12 missed; the misses are outside this change) |
| Migrations on a fresh database, and on a baseline database (main + G03, seeded with 9 users, 3 events, 4 venues) | Both applied; baseline records unchanged |
| Seeded fault: `is_stale` always False | Caught by C02-04, C02-08 |
| Seeded fault: block overlap `<` changed to `<=` | Caught by C01-05 |

## Scope boundaries

- **AC5 endpoint.** The confirm action is SCRUM-58 (Raksha, G21). G04 proves the guard at service level. The endpoint-level refusal test belongs to G21.
- **AC6 producers.** Real withdrawal (SCRUM-67, G11) and equipment actions (G16a/G17) must call the service. SCRUM-80's approved change requests are Sprint 4.
- **Design records.** The C4 diagrams in `docs/c4` still need the Safety Officer actor and `safety` component added.
