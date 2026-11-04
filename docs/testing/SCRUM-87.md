# SCRUM-87 — multiple venue sessions

Owner: Nethren. Branch: `feature/multi-venue-sessions`. Integration gate: SESSIONS, based on green main `ef91b36375a98c7262d5cdf855b5ad313ce1d639`. Notifications/history, venue buffers and registration prerequisites were already merged through PRs #27–31.

The coordinator can request a main room and named breakout rooms for one event. Every request has its own suitability, buffered occupancy and staff decision. Required rejected/withdrawn sessions remain unresolved until replaced or explicitly removed; the main programme remains required. Replacing one room preserves the original until staff approve the replacement, then switches atomically. Other sessions and their history stay intact. Organiser, attendee, registration and Safety views identify each session and period.

Main attendance follows the event's current expected attendance. Breakout attendance and periods remain local to their booking revision. Old fixtures that gave a 60-seat main room an unrelated event attendance of 120 were aligned with this customer-change rule; their original capacity, error, layout and cancellation assertions remain intact.

## Acceptance evidence

| Criteria | Implemented and verified |
| --- | --- |
| AC1 | Stable main/breakout identities, separate named requests, one event and staff notifications |
| AC2 | Per-session capacity/layout/facility/access checks; main cannot understate event attendance |
| AC3 | Same-event same-room conflict; 30/45-minute buffers; exact 13:15 adjacency versus 13:14 conflict; real PostgreSQL concurrent approval |
| AC4 | Independent approvals/rejections; every required session must resolve before Safety/confirmation |
| AC5 | Independent withdrawal, explicit removal, protected replacement, stale/conflicting proposal refusal, atomic rollback and event-wide cancellation. Full **confirmed-change** integration remains at SCRUM-80/APPLY, as planned |
| AC6 | Both rooms and names in actual organiser/attendee browser views, safe API projection and registered-attendee UI |
| AC7 | Changed main attendance is reassessed against the new value; breakout attendance/period/requirements remain unchanged |

The executable case inventory is [S4-SCRUM-87-multiple-venues.csv](../test-cases/S4-SCRUM-87-multiple-venues.csv). It records independent expected outcomes, actual execution, selectors and pending correctness review for each new backend/component/browser case. The migration test upgrades actual old-schema approved/rejected records and verifies IDs, every stored value/timestamp and decision history.

## Verification on 4 November 2026

Executed by Codex for Nethren, using local Python 3.12, PostgreSQL 16 and Chromium. Local Node is newer than CI's Node 20; remote CI remains a separate compatibility check.

- Backend full regression: **1,530 passed**, including the first 32 session cases, with branch coverage and JUnit output.
- After adding the final shared-writer/ownership guard cases and auditing assignment-change refusal: **37 session cases passed**. Their coverage was appended to the full run. The final five cases are additional to that full-run count; they are not described as a second full regression.
- Frontend: **340 passed**, production-source coverage, TypeScript and production build passed.
- Browser: **14 passed**, real API and isolated PostgreSQL, one worker and zero retries. The new journey uses actual venue, technical, Safety and confirmation actions; it inserts no approved Safety fixture.
- Ruff check/format, missing-migration check and whitespace check passed.

The new `venues/sessions.py` service and booking API have **100% statements/branches** across these runs. All newly added executable backend lines are covered. Aggregate backend coverage includes tests/migrations, so it is not the production measure: production code excluding tests/migrations covers **5,151/5,198 statements (99.10%)** and **1,099/1,124 branches (97.78%)**. Existing uncovered layout/error/display paths remain; they are not waived by this story.

Frontend file coverage includes older shared behavior. The exact JSON records its remaining error/fallback branches; it is not claimed as 100% production coverage. Session request/removal API contracts have 100% lines/branches. Planner, attendee and registration screens have component tests plus the real browser journey. Existing error branches elsewhere are separate gaps, not evidence that every application path was exercised.

Local evidence: `/Users/Mac/Documents/Codex/Projects/SPM/outputs/sprint-4-nethren-2026-11-04/` (`scrum87-api.xml`, `scrum87-target.xml`, coverage JSON, frontend results and browser log). CI uploads the repository's standard API/web/browser evidence after a PR run.

Commands follow CI: `POSTGRES_PORT=5434 .venv/bin/pytest --cov-branch`; targeted guard run adds `--cov-append`; frontend uses `npm run lint`, `npm run build` and the CI production-source coverage arguments; browser uses `npx playwright test --workers=1 --retries=0`. Tests create their own `test_connectsphere` database. Browser uses the separate `connectsphere_s4_nethren` database; the existing preview database was not migrated.

## Integration and acceptance remaining

Publish the feature PR and wait for its CI/review before merging. Jerom's SCRUM-66 and Adilah's SCRUM-70 consume this gate through green main; Nethren's holds gate follows the agreed queue. See [the session architecture and downstream contracts](../c4/multi-venue-sessions.md).

SCRUM-87's approved-confirmed-change journey closes jointly with SCRUM-80. Hold behavior belongs to SCRUM-88. Teammate correctness review, team browser checks, sprint demonstration and PO acceptance are pending; this agent execution does not mark Jira Done or claim those human activities occurred.
