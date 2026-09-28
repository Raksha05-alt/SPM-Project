# SCRUM-51: automatic coordinator assignment

## Scope and branch

Story: SCRUM-51, assigned to Nethren Balamurugan in Sprint 2; 5 points, Medium.
Implementation branch: `Nethren`.
Includes Jerom's latest `7364463` access-control/audit changes. Merge conflicts
in the README, event permissions wiring, and access-control tests were resolved
by preserving the attendee-safe serializer/status filtering from Nethren and
the newer anonymous-refusal auditing from Jerom. The completed work is on
`Nethren`; `main`, `Dev`, and `Jerom` were not changed.
No other Sprint 2 implementation was assigned to Nethren when Jira was checked
on 28 September 2026. This does not mean the rest of Sprint 2 is implemented.

Sources inspected: the current Jira story; official Week 4 Project Instructions;
the live Customer Meeting document and G3G4G5 Week2 Clarification (SESSION 1)
sheet in the registered PROJECT Drive folder. The session 2 sheet contains
questions, not answered availability rules. Session 1 permits in-app notifications
and excludes experience-based assignment. Customer Meeting specifies random
assignment based on availability, one coordinator per event.

## Behaviour and acceptance tests

| Criterion | Implementation | Evidence |
|---|---|---|
| AC1: exactly one available coordinator after valid submission | Single coordinator FK, assigned inside the submission transaction | `test_ac1_assigns_one_available_coordinator` |
| AC2: random selection without seniority | `secrets.choice` over all active, available Coordinators; no seniority field or ordering preference | `test_ac2_random_choice_uses_all_available_coordinators` checks the eligible pool and selected result |
| AC3: notify organiser and assigned coordinator | Two persistent messages, committed with the submission; authenticated recipient-only inbox | `test_ac3_both_recipients_receive_persistent_notifications`, Notifications component tests, browser journey |
| AC4: organiser sees name and contact | Read-only coordinator name and email in event details, email link in submitted request screen | `test_ac4_organiser_can_see_name_and_contact`, CoordinatorAssignment component tests, browser journey |
| AC5: none available | Keep Submitted, coordinator null, persist attention flag, show staff-action warning in queue | `test_ac5_no_available_coordinator_flags_submitted_request`, queue and CoordinatorAssignment component tests |

Backend tests: `api/apps/events/tests/test_scrum_51_assignment.py`.
Browser test: `web/e2e/draft-submit-queue.spec.ts` extends the existing journey.
It checks organiser contact details and both users' notification inboxes against
a real API and PostgreSQL database with one seeded coordinator.

Additional regression tests cover inactive/wrong-role/unavailable accounts,
incomplete requests, stale repeated submissions, real concurrent submissions,
notification failure rollback, recipient isolation, and client attempts to set
assignment fields. The event row lock protects only submission; this does not
claim that future review/edit services already have concurrency protection.

## Confirmed implementation decisions

Availability is implemented as `User.is_active` plus a staff-admin-managed
`coordinator_available` flag. It defaults to true, preserving eligibility of
existing active coordinator accounts. No supplied answer defines capacity,
working hours, leave calendars, or event-date conflicts for coordinators. This
was confirmed by Nethren on 28 September 2026 as the team's implementation
choice. It is not a claim that the customer prescribed this exact policy.

The organiser notified is the submitting user. Contact details mean email,
because the existing account model has no phone number. Notifications are
in-app, not email delivery. No unread/read management or reassignment workflow
is included. Broader notification types will need a separate uniqueness policy;
the current table contains only assignment messages, one per event/recipient.

## Running and reviewing

Apply migrations, seed demo accounts, and start the API and web using README
instructions. Set the root `.env` database port to the actual host-mapped port.
For the no-available case, use an administrator account to disable **Coordinator
available** for every coordinator. New submissions then stay Submitted with a
visible staff-action flag. Existing seeded submitted events are not backfilled
and do not produce retrospective assignment messages.

Tests must use a dedicated database: pytest creates/deletes its test database.
Run backend pytest, Ruff lint/format checks, migration drift checks, frontend
type checks/unit tests/production build, and the browser test. These are
verification evidence, not a claim that all possible bugs are absent. Team
review and user validation are still needed before declaring the story Done.

## Verified results — 28 September 2026

After integrating Jerom's latest branch: 114 backend tests passed, including
15 SCRUM-51 tests; 26 frontend tests passed. Ruff lint and formatting checks,
frontend type checks and production build passed. All migrations applied to a
fresh PostgreSQL 16 database and no migration drift was detected. The real
browser assignment/notification journey passed both before integration and
against the merged version.

The reported pytest coverage is 99.80%; its configured denominator includes
test files and migrations, so it should not be presented as production-code-only
coverage. Dependency deprecation warnings are present (Django/Python, React
Router); these did not fail the checks. One existing status migration was
formatted without changing its operations to satisfy the CI formatting gate.
