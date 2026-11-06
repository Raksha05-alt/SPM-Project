# Testing and execution evidence

Run commands from the repository root. The root [README](../../README.md#running-the-test-suites) explains the environment, isolated browser database and required hold worker.

| Layer | Tests | Run |
| --- | --- | --- |
| Backend unit and integration | api/apps/**/tests/ | cd api && pytest --cov-branch --junitxml=test-results/api-junit.xml |
| Frontend component and unit | web/src/**/*.test.tsx | cd web && npm run test |
| Real browser journeys | web/e2e/*.spec.ts | cd web && npx playwright test --workers=1 --retries=0 --reporter=list,json,junit,html |
| Type and build checks | web/ | cd web && npm run lint && npm run build |
| Backend style and migrations | api/ | cd api && ruff check . && ruff format --check . && python manage.py makemigrations --check --dry-run |

## Case register

The complete [workbook](../test-cases/Test_Cases_All_Sprints.xlsx) uses US-<story>-TC<number> IDs. Its 338 records cover all 62 US stories and distinguish current, historical and superseded criteria. [The story index](../test-cases/story-test-index.csv) links stories to case IDs and source modules. Exact code selectors retain their original names.

## Recorded local execution

[submission-readiness evidence](evidence/submission-readiness/) contains a 6 November 2026 local run, not a backdated sprint run:

- api-junit.xml: 1,923 passing executions.
- layout-races.xml: two subsequent passing PostgreSQL race executions.
- vitest-final.json: 454 passing frontend executions.
- browser-verified.json and browser-verified.xml: 32 passing real-browser executions, without retries.
- tested-build.json: source fingerprint and base commit for that local run.
- manifest.json: checksums of the packaged evidence.

There are 2,411 distinct recorded executions. The 12 business-journey groups are an organisation of browser coverage and may share specs; they are not additional executions. GitHub Actions runs the full backend, frontend and browser suites independently for each pull request. Use that run's commit SHA and artifacts when citing CI.

## Coverage and review limits

Production-only backend coverage was 99.14% of lines and 97.69% of branches; frontend instrumentation measured 94.55% of lines and 91.37% of branches. The backend summary excludes tests and migrations. api-coverage-final.json, frontend coverage JSON and remaining-coverage-gaps.csv retain the measurements and exact gaps.

[Coverage regression notes](coverage-gap-closure.md) explain the recovery and concurrency cases. Older sprint audit directories and SCRUM-specific notes remain historical records; their counts describe their own build.

The source audit found no exact duplicate backend test bodies across 1,217 definitions and no exact duplicate frontend bodies across 417 declarations. Parameter variants and tests at different layers can intentionally prove different outcomes; those results do not claim that semantic overlap is impossible.

Named human correctness review and the team browser walkthrough require actual confirmation. Automated execution does not complete those fields. Simulated review entries are reference material and are not packaged as actual sign-off.

The earlier dependency audit identified unresolved package advisories, including development tooling and React Router. This packaging pass does not claim dependency remediation or 100% coverage. The course FAQ does not add a separate security rubric, but deployment users should review these findings.

## Final packaging cleanup

The unused PlaceholderPage was removed after the recorded local run: it had no imports or active route and still announced future features. Historical coverage files retain that old path because they describe their actual source snapshot. [PR 44](https://github.com/Raksha05-alt/SPM-Project/pull/44) provides independent CI and coverage artifacts for the final branch head.
