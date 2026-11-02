# SCRUM-75: amend or withdraw equipment requests

Branch: `feature/equipment-request-amendment`, based on main `6bfb7b0` (G16b).
No commits or pushes were made during implementation.

The assigned, active coordinator can amend quantity/technical requirements or
withdraw a request from the event's Equipment plan. Mutations require the displayed
`expected_revision`; concurrent or stale submissions refuse with HTTP 409.
Confirmed events require the later approved-change workflow; terminal/elapsed events
and former coordinators cannot change requests.

POST `/api/equipment/requests/{id}/amend/` takes `expected_revision`, `quantity`
(positive integer) and `technical_requirements` (text). POST
`/api/equipment/requests/{id}/withdraw/` takes `expected_revision`.
Both return the fresh equipment plan, including retained request change history.

Event, equipment type, plan, request and reservation locks follow the shared order.
Reducing a reserved quantity retains the remaining active reservation and releases
only the difference. Increasing a reserved quantity checks current capacity, releases
the old reservation and returns the request to Technical Support for reservation.
Changing requirements retains reserved units but supersedes technical approval.
Technical Support can approve retained reservations with
POST `/api/events/{id}/approve-revised-equipment/` and `expected_revision`;
this rechecks stock and every outstanding reservation before recording approval.
Withdrawals release active reservations and retain the request as Withdrawn.
Actual changes advance the plan, supersede Safety checks, record before/after values,
actor and timestamp, and notify active Technical Support in the same transaction.
Submitting identical values does not create history, notices or invalidate approvals.

No schema changes are required. Existing availability, reservation, release,
notification and Safety services are reused. Other features remain in their existing
modules. The browser equipment journey now exercises reserve, amend, reload,
withdraw, request again and reserve before the existing cancellation assertions.

Acceptance mapping:

| Case | Expected result | Executable test |
| --- | --- | --- |
| S3-SCRUM-75-01 / AC1,4 | 5 becomes 3 with exact revised HDMI note, staff notice and dated actor/history | `test_s75_01*` |
| S3-SCRUM-75-02 / AC2 | Stock 8, reserve 5: availability 3; amend to 3: availability 5 | `test_s75_02*` |
| S3-SCRUM-75-03 / AC3 | Withdraw releases once, retains request and history | `test_s75_03*` |
| S3-SCRUM-75-04 / validation | Zero, negative, fraction, boolean, string and null refuse without changes | `test_s75_04*` |
| S3-SCRUM-75-05 / permission | Technical staff, other coordinator, organiser, Lead and attendee refuse | `test_s75_05*` |
| S3-SCRUM-75-06 / stale, capacity | Stale revision and overstock increase preserve reservation | `test_s75_06*` |
| S3-SCRUM-75-07 / atomicity | Notification failure rolls back request, reservation, revision, history and notices | `test_s75_07*` |
| S3-SCRUM-75-08 / requirements | Requirements-only change retains units; identical replay has no side effects | `test_s75_08*` |
| S3-SCRUM-75-09 / lifecycle | Confirmed, Completed and Cancelled events refuse direct amendment/withdrawal | `test_s75_09*` |
| S3-SCRUM-75-10 / increase | 5 becomes 7 awaiting staff reservation; actual reserve persists 7 | `test_s75_10*` |
| S3-SCRUM-75-11 / isolation | Reducing/withdrawing first event preserves second event's two reserved units | `test_s75_11*` |
| S3-SCRUM-75-13 / reapproval | Only technical staff reapprove a current, fully reserved revised plan | `test_s75_13*` |
| S3-SCRUM-75-14 / rechecks | Pending requests or lost stock refuse reapproval | `test_s75_14*` |
| S3-SCRUM-75-15 / input | Malformed payload, invalid requirements/revision and withdrawn edits refuse | `test_s75_15*` |
| S3-SCRUM-75-16 / empty plan | Reapproval without requests returns a controlled refusal | `test_s75_16*` |
| S3-SCRUM-75-17 / freshness | Previously loaded coordinator and elapsed-event edits refuse | `test_s75_17*` |
| S3-SCRUM-75-12 / concurrency | Parallel amend/withdraw at same revision: exactly one succeeds | `test_s75_12*` |

Tests are in `api/apps/equipment/tests/test_scrum_75_amend_or_withdraw.py`.
Specifications and implementation: Codex, 2 November 2026, Singapore time.
Actual teammate correctness review, manual teammate walkthrough, PR CI, PO acceptance
and merge remain pending. Local execution is additional evidence, not those approvals.
See the execution results below for checks actually performed.

Local execution on 2 November 2026 (Codex; working tree based on `6bfb7b0`):

- Ruff lint and formatting: passed for all 194 backend source files. Existing
  inaccessible pytest cache directories were omitted from file enumeration.
- Django system check and missing-migration check: passed; no new migration.
- Equipment regression: 322 passed on PostgreSQL 16 in the dedicated
  `spm-scrum75-tests` container, port 55475. JUnit:
  `api/test-results/scrum75-equipment.xml`.
- Equipment production code, excluding tests/migrations: 100% statements and
  branches in `api/test-results/scrum75-equipment-coverage.json`.
  The focused command also inherits the global `--cov=apps` setting, so its
  all-app aggregate is not the equipment-only figure and is not a full-suite gate.
- Full frontend regression: 241 passed with V8 coverage and one worker; final
  focused UI/API tests: 29 passed after adding the history display assertion.
  Changed UI/API modules have 100% statement coverage; equipment amendment
  controls have 100% branch coverage. `EquipmentPlan.tsx` has 97.7% branch
  coverage in the focused run; its line 101 null/missing-history-value fallbacks
  are not all exercised by unit fixtures. No reachable code was excluded.
- Final TypeScript check and production build: passed.
- Full equipment browser journey, including technical reapproval: passed against
  the real API/database. `web/test-results/scrum75-browser.xml`.

Test artifacts are ignored by Git. Teammate review and PR CI remain pending.

Final acceptance rerun: 29 SCRUM-75 tests passed, including the explicit
Safety confirmation-gap assertion. JUnit: `api/test-results/scrum75-focused.xml`.
Final complete browser regression: all 10 passed (one worker, no retries).
Evidence: `web/test-results/scrum75-all-browser.xml` and
`web/test-results/scrum75-all-browser.json`.

Full backend CI-equivalent regression: **1,150 passed**, aggregate statement/branch
coverage **98.07%**, clearing the configured 80% gate. JUnit:
`api/test-results/scrum75-junit.xml`; coverage:
`api/test-results/scrum75-coverage.json`.
Production-only backend coverage excluding tests/migrations: 98.18% statements
and 95.96% branches. This broad run began before the final extra
acceptance cases were added; the final 29-case SCRUM-75 rerun and 322-case
equipment regression cover the completed equipment implementation.
