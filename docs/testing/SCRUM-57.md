# SCRUM-57 — filter events by status

Owner: Nethren. Branch: `feature/event-status-filter`, created independently from green main `ef91b36375a98c7262d5cdf855b5ad313ce1d639`. This is the FILTER side lane; it does not depend on sessions, holds or approved changes.

The coordinator's assigned-events screen supports one or several status checkboxes, a clear action and an empty result. Filtering happens on the server after assignment/organisation/public visibility scoping. Clearing restores the entire permitted list and its existing action priority. Organisation draft/submitted grouping remains intact. No ticket description, event status, assignment or history is changed by filtering.

`GET /api/events/mine/?status=PLANNING&status=CONFIRMED` and the ordinary event list accept repeated or comma-separated values. Values have OR semantics; duplicates/whitespace/empty tokens are normalised. An absent or blank filter clears it. An unknown status returns a named 400 error. Detail access and writes keep their existing object permissions. The UI keeps clear controls available after a network refusal.

| AC | Evidence |
| --- | --- |
| AC1 | One/multiple statuses; repeated/comma keys; duplicates/whitespace; real checkbox-to-API filtering |
| AC2 | Known status with no matches returns 200/empty list; UI shows a useful empty state |
| AC3 | Other/currently reassigned/unassigned events and drafts stay hidden; organisation and attendee visibility remain enforced; real Lead reassignment is verified in the browser |
| AC4 | Clear button, last checkbox removal and absent/blank query restore the permitted list; existing action priority/grouping remain |

## Verification on 4 November 2026

Executed by Codex for Nethren. Human correctness reviews, team browser checks, sprint demo and PO acceptance remain pending.

- Full PostgreSQL regression with branch coverage and JUnit: **1,523 passed**, including 25 new filter cases.
- Full frontend regression: **334 passed**, including six new filter UI/client cases; TypeScript and production build passed.
- Full real browser regression: **14 passed**, one worker and zero retries. The new journey uses actual organiser submission, Lead assignment/reassignment, coordinator approval and venue request APIs, then checks browser filtering and current permissions.
- Ruff check/format, missing-migration check and whitespace checks passed. This story needs no migration.
- `events/filtering.py` and `CoordinatorMyEvents.tsx` reach **100% statements/branches**. The new `fetchMyEvents` query encoding/clear branches are covered. The wider shared events API file retains unrelated untested wrappers; file aggregate is not claimed as story coverage.
- The non-list pass-through in DRF's `filter_queryset` wrapper is defensive compatibility code: shipped object actions use the existing explicit `get_object` path. HTTP tests confirm that filters do not alter object access or mutate records. Broader pre-existing production coverage gaps remain separate.

[The case inventory](../test-cases/S4-SCRUM-57-status-filter.csv) records each new API/component/browser case, concrete expected outcomes, executable selector, actual run and pending correctness review. Local JUnit, coverage JSON, frontend results and browser JSON/logs are saved under `/Users/Mac/Documents/Codex/Projects/SPM/outputs/sprint-4-nethren-2026-11-04/` with the `scrum57-` prefix.

Commands follow CI: `POSTGRES_PORT=5434 .venv/bin/pytest --cov-branch`, frontend lint/build and CI production-source coverage options, and `npx playwright test --workers=1 --retries=0`. Browser tests use an isolated `connectsphere_s4_filter` database; prior executions of this journey are cleaned up through the real cancellation API. Mocked component tests complement, rather than replace, real API/browser verification.

Publish through a reviewed PR and green main. This independent side lane may merge whenever ready. SCRUM-87's SESSIONS gate and SCRUM-88/73's later merge gates remain separate. Jira is not marked Done by this agent run.
