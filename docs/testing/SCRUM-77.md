# SCRUM-77: equipment release and event cancellation (G16b / INT-03)

Nethren implements this phase on `feature/equipment-release`, after the reservation phase on `feature/equipment-reservations`. G15 is PR #20; G16a is PR #21. Work date: 2 November 2026, Singapore time. Merge in dependency order: availability, reservations, then release. Teammates fetch and merge reviewed main before continuing G17/G18/G20/G21.

Technical Support can release an active reservation before the event ends, with a reason and the displayed plan revision. The action records the releasing actor/time and reason, retains the original reservation, returns its request to Requested and supersedes technical approval. Staff may reserve that request again; the new reservation has its own identity. A repeated release returns 409 and cannot free the quantity twice. Released reservations stop reducing fresh availability; another event's active reservations continue to count.

The assigned coordinator can cancel a submitted or planned event through an explicit summary and confirmation. The summary names pending/approved venue bookings and active equipment reservations. A digest covers event status/assignment/dates, equipment revision and the actual resource records. The server recomputes it under the event/resource locks. A change after preview returns 409 and requires a fresh summary. The browser clears confirmation if a refreshed summary has a different digest.

Cancellation records Cancelled, withdraws venue bookings, releases equipment, withdraws open equipment requests, supersedes technical/Safety approval and notifies the organiser, coordinator and relevant staff in one transaction. It retains resource and status history. Setting Cancelled before the resource changes, inside that transaction, avoids a misleading intermediate return-to-Planning notice. A failure in a booking, release, invalidation or final notification rolls the transaction back. The cancellation UI prevents arbitrary status changes and refuses unassigned/previous coordinators and other roles. Completed, Cancelled, Rejected, private drafts and events whose end has passed refuse the action.

Manual release calls `arrangements_changed` in its own resource transaction. Cancellation reaches the same invalidation contract through booking transitions, equipment release and a final event-level call. The Safety notice distinguishes cancellation from an arrangement that needs rechecking. These tests use G04 Safety records as explicit preconditions; G20/G21 still own the complete Safety request/decision/confirmation journey.

## Endpoints and shared handoff

| Endpoint or service | Contract |
| --- | --- |
| POST `/api/equipment/reservations/{id}/release/` | Technical Support; `{expected_revision, reason}`; returns the fresh scoped equipment plan. |
| GET `/api/events/{id}/cancellation-preview/` | Assigned coordinator; current resource summary and version digest. |
| POST `/api/events/{id}/cancel/` | Assigned coordinator; `{expected_version, confirm_cancel: true, reason}`; returns Cancelled and released/withdrawn counts. |
| `equipment.releases.release_record` | G17 shared primitive. Caller holds event/type/reservation locks, advances the plan, checks actor/revision/status and supplies a reason. It retains the row and writes release history; an already released row returns False. |
| `equipment.reservations.advance_plan` | G17 supersedes technical approval, retains its evidence and advances equipment revision under the event lock. |
| `equipment.releases.release_for_cancelled_event` | Cancellation's idempotent equipment slice. The caller supplies the current assigned coordinator and the event must already be Cancelled inside the outer transaction. |

Lock order: event, venues by ID, equipment types by ID, then resource rows. G17 should recheck increases using G15's shared availability service under those stock locks and call `arrangements_changed` before committing. G18 should verify the holding list through the actual reservation and cancellation endpoints. G20/G21 should rerun complete readiness against real reservations and the current technical approval.

Migration `notifications.0013_event_cancelled_kind` adds the cancellation notice category after G16a's 0012. The equipment schema stays unchanged. The matching `@vitest/coverage-v8@2.1.8` dev dependency makes the existing coverage tooling reproducible in CI; application dependencies stay unchanged.

## Tests and execution evidence

Backend acceptance cases cover real reserve/release/re-reserve, exact released quantity, another event's retained stock, elapsed events with stale statuses, role/assignment refusals, explicit confirmation/reason/version, resource changes after preview, pending and approved venue withdrawal, no-equipment plans, replay and rollback at multiple transaction stages. The combined G16a/G16b focused run passed **90 cases**. Those new service and action-view files measured **100% statements and branches** with no exclusions.

Component tests verify reason validation, exact revision/version payloads, pending-action guards, errors, retained history, cancellation summaries and renewed consent. J3 now exercises the actual UI request/reserve/manual-release/re-reserve/cancel sequence, with actual venue request/approval API preconditions. J2 covers venue forms/decisions separately. The browser tests use the real API and PostgreSQL, one worker and zero retries.

The local full-suite attempts encountered broad timeouts under a host load average around 159. Preserve those logs as diagnostic evidence; they do not establish a passing regression. GitHub CI runs the full backend/frontend suites and the real browser suite on isolated runners. It retains per-case JUnit/JSON, scoped coverage, and failure screenshots/traces as `api-test-evidence`, `web-test-evidence` and `browser-test-evidence`. The backend/frontend coverage scopes are separate from whole-project coverage; tests and migrations in the default backend aggregate do not establish application coverage.

Individual case records: `../test-cases/S3-SCRUM-77-equipment-release.csv`. Each record identifies its executable selector. Match that selector to the same head's CI artifact for the final actual outcome, run time and build; the project output handoff also preserves expanded execution records. Correctness-reviewer/date fields remain blank for the team. The AI assistant has inspected/executed checks; team correctness review, the team's own browser walkthrough and PO acceptance remain unrecorded. Jira remains In Progress until those acceptance steps occur.

## Sources and phase

Live Jira SCRUM-77 AC1–4 and SCRUM-16 AC1–6; Sprint 3 guide G16a/G16b, INT-03 and J3/J5; Week 4 Project Instructions equipment reservation and cross-feature workflow paragraphs; G3 Week 4 `Sheet1!C45:D45` permits aggregate stock. Week 7 change 6 and G3 Week 9 `G3-5!C15:D15` require rechecking changed arrangements. Week 4 Test Cases & Software Architecture slides 9/16 and the test-design section call for positive, negative and boundary cases derived from AC; the FAQ's 19 October update requires per-case correctness checks and consistent execution evidence while permitting automation.

The cancellation action is the guide's enabling original-workflow integration, not a newly invented customer change story. Later G17 amendments, G18 holding details, G20/G21 Safety/confirmation and Sprint 4 holds/multiple venues remain their owners' work. This phase does not mark those workflows implemented.
