# Equipment foundation (G03): execution evidence

Client work date: 27 October 2026. Branch: `feature/equipment-contract`.
Approved base: `2fee7403ea324af1c71957735523bc10dbe7fcef`.
Tested source SHA256:
`61ed547ea1da901a620f07c0cfb9bb68a33969a8fb1e9a1dbb9aeecf6feba2cc`.

## Scope and actual results

| Check | Outcome |
|---|---|
| New equipment cases | **98 passed**: input/locking contracts, models/constraints, fresh-state validation, inventory concurrency, admin requests and seed preservation. |
| Complete backend regression, Python 3.12 / PostgreSQL 16 | **529 passed**, including all 431 baseline tests. |
| Existing real API/database Playwright journeys | **7 passed**, no skips or retries. These check existing request/Lead/venue workflows after adding the schema/seed; they are not an equipment-reservation E2E claim. |
| Ruff lint and formatting | Passed. |
| Missing migrations | No changes detected. |
| Fresh schema | All migrations applied successfully. |
| Upgrade from approved main schema | Existing event, coordinator assignment, revision and notification preserved; new equipment workflow tables empty. |

Tests used a dedicated disposable PostgreSQL container and two separate test/
upgrade databases. The user's project database was not changed. Django admin
maintenance was exercised through actual authenticated HTTP/form requests; pure
workflow-model tests use real persisted records without pretending an action API exists.

The extra red-run tests reproduced stale cached plan/request validation and
invalid-FK exceptions. The final implementation rereads the related values and
returns validation errors. The final full run includes those regressions.

## Coverage measurement

The new equipment application code, including admin, contracts, inventory,
management command, models and app configuration, measured **309/309 executable
statements and 66/66 branches: 100%**. Tests and migrations are excluded from
that claim. The implementation is a foundation slice, so its coverage does not
mean the later user-story workflows exist.

For comparison, wider backend production code excluding tests, migrations and
admin measured **1,702/1,713 statements (99.36%)** and
**283/288 branches (98.26%)**. The remaining gaps are earlier event/venue string
representations, defensive serializer/decision guards and legacy submission/
clarification branches documented in the Lead assignment report. They are not
new equipment foundation code. The default combined pytest percentage includes
tests/migrations and is not used as the production-coverage claim.

No frontend source was changed and no new frontend coverage figure is claimed.
The existing browser regression suite used the real seeded backend. GitHub CI
results, when available, belong to the PR/build that actually ran them.

## Individual case records

[SCRUM-16-77-equipment-foundation.csv](test-cases/SCRUM-16-77-equipment-foundation.csv)
contains 98 executed records and 10 separately **Blocked** full-story criteria.
Each record includes:

- Case ID, related story/criterion and foundation-versus-full-story scope.
- Named fixture preconditions, parameter specification, executable test steps
  and independent assertions/expected exceptions.
- Executable selector, source fingerprint, raw execution timestamp and outcome.
- Agent inspection/execution details, with team correctness reviewer/date pending.

The future AC records are blocked on the scheduled real action/Safety/availability
dependencies. No reservation notification, Safety supersession, cancellation,
elapsed-event release refusal or complete equipment browser flow is marked passed.
Those actions belong to G14–G18 and their preceding contracts.

Raw evidence:
`/Users/Mac/Documents/Codex/Projects/SPM/outputs/equipment-foundation-2026-10-27/`.
Files include pytest.xml, backend-coverage.json, backend-run.log,
focused-run.log, validation-red-run.log, playwright.json, source-manifest.json
and individual-test-cases.csv. Source-manifest hashes identify the tested
application/tests before commit; the baseline SHA alone does not contain this work.

## Review and handoff

Team code/test correctness review, the FAQ's team-performed browser checks where
applicable, and final acceptance remain unrecorded. Agent execution is not a
teammate approval or Sprint Review. SCRUM-16/77 remain **In Progress**.

This gate is reviewable independently with schema, catalogue maintenance and
database tests. Merge it through the normal PR/main-CI process before dependent
developers pull main. The full stories remain open until their real workflows
and integration evidence meet the later gates.
