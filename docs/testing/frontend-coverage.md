# Frontend coverage follow-up — 6 November 2026

The frontend suite passes 494 executions. The production source scope is unchanged: 7,066 lines under web/src, excluding test files, mocks and setupTests.ts. Application behaviour was not changed.

| Measurement | Main cbe3ca1 CI baseline | Coverage branch |
|---|---:|---:|
| Lines / statements | 94.67% | 99.56% (7,035 / 7,066) |
| Functions | 86.36% | 99.08% (650 / 656) |
| Branches | 91.41% | 93.23% (2,177 / 2,335) |
| Passing frontend executions | 454 | 494 |

V8 discovers additional functions and branches when previously unexecuted modules run. Their denominators therefore changed. The source-line denominator and include/exclude scope did not change. These are frontend Vitest measurements, not combined browser/backend coverage.

## Changes and evidence

- Real application startup, authentication, role guards and route integration, including delayed restoration, forbidden routes and failed-login recovery.
- Draft editing, persistence and submission; registration-policy refusal and corrected save; layout lifecycle and in-use deletion refusal.
- Attendee contact details, registration, explicit withdrawal and waiting-list clients.
- Coordinator field edits, null clearing, cancellation, save recovery and ownership refresh after a refused approval.
- Domain clients integrated with the real HTTP adapter: timezone/filter encoding, CSRF, field errors, revision conflicts and empty failures.
- Clarification-history fallbacks, operating-day selection, hold cancellation and equipment failure recovery.
- Existing venue-request, alternative-time and equipment-holder tests now exercise the previously missed inputs and close action.

The 40 new executions are grouped into nine supporting case records in the workbook. Each execution has its exact selector in [the case mapping](../test-cases/frontend-coverage-cases.csv) and [the verified run](evidence/frontend-coverage/vitest-verified.json). They supplement the existing acceptance cases rather than replacing them. The existing 12 E2E journey groups were retained; no browser specification was added or rerun in this frontend-only task.

The new App tests use real React components, providers, routing and API clients with the HTTP boundary replaced. The planning contract tests integrate domain clients and the shared HTTP adapter. They do not claim to exercise a real Django server. Existing isolated component tests and real-backend browser journeys retain their distinct purposes.

## Verification

- Full frontend suite: 494 passed, zero failures or skips.
- Coverage thresholds: passed. The configuration now requires at least 99% lines/statements, 98% functions and 93% branches whenever coverage is enabled.
- TypeScript check and production build: passed.
- Exact-body audit: 450 declarations across 66 files, no identical bodies, skip/todo/only flags, assertion-free tests or trivial constant assertions found. This static audit does not prove that semantic overlap is impossible.
- Production source code, coverage include/exclude scope and dependencies were preserved.

[The gated run](evidence/frontend-coverage/vitest-gated.json), [coverage summary](evidence/frontend-coverage/coverage-summary.json), [source fingerprint](evidence/frontend-coverage/tested-build.json) and [checksums](evidence/frontend-coverage/manifest.json) identify the tested working tree based on cbe3ca1. Earlier evidence directories retain their original runs and builds.

Run from web/:

    npm run test -- --coverage
    npm run lint
    npm run build

## Remaining coverage

31 source lines, six functions and 158 branch arms remain uncovered. The [gap register](evidence/frontend-coverage/remaining-coverage-gaps.csv) lists their exact locations. Remaining areas include draft deletion and an unused list wrapper, dialog-cancel callbacks, optional metadata/warning displays, network refusal paths, and defensive fallbacks across venue/equipment/safety pages.

These results are close to full line and function coverage; branch coverage is 93.23%. No exclusions were introduced to hide the remaining paths. Coverage is execution evidence, not proof that every possible input is correct.

Actual named teammate review and the manual browser walkthrough remain separate from automated execution. The repository workbook preserves those real-review fields. The separately requested SIM_testcase.xlsx is reference material and is not packaged as actual peer approval.
