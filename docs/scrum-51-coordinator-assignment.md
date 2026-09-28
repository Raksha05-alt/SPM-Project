# SCRUM-51: automatic coordinator assignment

## Scope and branch

Story: SCRUM-51, assigned to Nethren Balamurugan in Sprint 2; 5 points, Medium.
Feature branch: `feature/SCRUM-51-coordinator-assignment`, based on `Nethren`.
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

## Team decision to confirm

Availability is implemented as `User.is_active` plus a staff-admin-managed
`coordinator_available` flag. It defaults to true, preserving eligibility of
existing active coordinator accounts. No supplied answer defines capacity,
working hours, leave calendars, or event-date conflicts for coordinators. This
is an implementation assumption, not a confirmed customer rule; confirm it with
the team before replacing it with a workload/calendar policy.

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
