# Sprint 3 final code and test audit

Audit date: 3 November 2026. Scope: Jira Sprint 67, 21 Stories / 92 points. This report uses the live Jira criteria, current approved main and PRs #25/#26. It excludes `final_changes`, `Trial_Code` and their unapproved changes. Historical commit authorship remains intact.

## Verdict

The Sprint 3 functional candidate covers the agreed workflow, including venue decisions, real equipment reserve/amend/release/cancellation, Safety review and final confirmation. PR #25 passed review and merged first. PR #26 must pass its updated CI before merge; its current checks and eventual merge commit remain visible at [PR #26](https://github.com/Raksha05-alt/SPM-Project/pull/26). This audit does not certify formal sprint acceptance or 100% coverage.

The agreed guide section 7 still defers **SCRUM-71 AC6** (setup/turnaround warning) to Sprint 4 under SCRUM-85/87. **SCRUM-90 AC6's approved change-request producer** remains with Sprint 4 SCRUM-80; Sprint 3's actual equipment and venue producers work now. Preserve these phase handoffs. No tests or Jira completion claims cover the deferred code.

## Verified changes from this audit

- SCRUM-58/90: readiness now rechecks that each active reservation covers the current requested quantity and event period, that the type remains in service, and that undamaged usable stock still covers demand. Retired and newly damaged stock previously allowed confirmation. Four negative tests reproduced the missing guards before the fix; they now require HTTP 409, an equipment-specific gap, and no Confirmed metadata/history/notice.
- SCRUM-58: a resource-unavailable reason must be nonblank text. The old view converted null, booleans, numbers and containers to strings. Five parameter cases now require HTTP 400 and no unavailability history/notice.
- SCRUM-58: a failed network request now shows a confirmation error instead of leaving the user without feedback. The new component test failed before the fix.
- SCRUM-69/77: an additional integration test uses the real cancellation preview/action to release an approved venue, then proves staff can approve the formerly conflicting pending request. The earlier low-level cancellation fixture remains a unit test, not evidence of this full action.
- Added J4/J5 browser journeys using real HTTP/database actions: Safety requests changes, technical revision/reapproval, new Safety approval, confirmation and organiser arrangements; then release after confirmation, return to Planning, stale-confirm refusal, re-reservation, fresh Safety approval and reconfirmation. Setup uses real API actions; no response mocking or shell-written approvals. Organiser access to internal Safety data returns 403.
- Fixed the PR #26 Ruff fixture re-export imports without suppressing lint or removing assertions. Updated two Safety expectations to retain valid resource periods or require the newly explicit period gap.
- Existing J2/J3 assertions now locate the exact Planning status. The old substring-first locator could match hidden notification text on a repeated run. The final browser run uses one worker, zero retries and no skips.
- CI now measures all production frontend `src` files, excluding only tests, test mocks and setup. No coverage gate was lowered or added. The earlier five-file report was insufficient to describe project coverage.

## Execution and coverage

Final local evidence: **1,289 backend tests**, **288 frontend tests**, and **12 Chromium browser tests**, with no failures/skips in the final runs. Ruff check/format, missing-migration check, TypeScript and production build pass. PostgreSQL 16 runs in a separate temporary database/container; the user's application database remains untouched. The project-root bundle `outputs/sprint-3-final-audit-2026-11-03/` records the exact source fingerprint, individual results and raw reports. `execution-records.csv` preserves each executed parameter case; `sprint3-case-assertions.csv` points to the real fixtures/actions and expected test assertions. These execution indexes supplement the existing authored case CSVs and do not fill their pending human fields. If a rerun changes these figures, use the raw result files as authority.

Backend production application statement coverage excludes test files: **98.99%** (4409/4454); branch coverage **97.03%** (848/874). The pytest aggregate includes tests and migrations, so its roughly 99% headline alone does not establish story coverage.

Frontend production coverage: **91.40% lines/statements**, **88.76% branches**, **83.01% functions**. This covers all `src` files, including bootstrap, router, API wrappers and older features. Browser execution is reported separately and does not increase Vitest's unit coverage.

[coverage-by-file.csv](coverage-by-file.csv) lists exact uncovered production lines and branch arms. These are **open coverage gaps**, not approved exceptions: no evidence establishes that these paths cannot be tested. Notable Sprint 3 gaps include Safety alternate fact displays, catalogue/booking refusal fallbacks and parts of confirmation. Some defensive branches require an injected permission or data race to reach; bootstrap/router paths need a different test setup. Add meaningful cases or obtain a specific documented justification before claiming the course target. Do not exclude reachable code to raise a percentage.

Source fingerprint (SHA-256 of sorted production/test/CI manifest, documentation excluded): `79b8ca33ac502f3dededd87c7cf6b2423bd0326925ef348bfacefd63a797ecaf`.

## Story and criterion traceability

[acceptance-matrix.csv](acceptance-matrix.csv) maps **106 live criteria** to actual executable selectors, with the two phase boundaries explicit. Test paths in old Jira verification prose or the original guide may differ from the delivered filenames. Use the checked selectors in this matrix; a historical filename mismatch alone does not mean a test is absent. Every mapped backend test belongs to the full executed suite. Parameter cases remain distinct in the execution records.

| Story | Owner | Points | Jira at audit start | Implementation/test evidence |
| --- | --- | ---: | --- | --- |
| [SCRUM-11](https://siti-is212.atlassian.net/browse/SCRUM-11) | JANNAVARAPU SHALIKA LAKSHMI _ | 3 | Done | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-12](https://siti-is212.atlassian.net/browse/SCRUM-12) | DOMNICK JEROM _ | 5 | In Progress | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-16](https://siti-is212.atlassian.net/browse/SCRUM-16) | Nethren Balamurugan | 5 | In Progress | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-45](https://siti-is212.atlassian.net/browse/SCRUM-45) | SUNDARAM RAMASUBBU RAKSHA _ | 5 | To Do | PR #25 approved and merged as 96a61f4 |
| [SCRUM-48](https://siti-is212.atlassian.net/browse/SCRUM-48) | SUNDARAM RAMASUBBU RAKSHA _ | 3 | To Do | PR #25 approved and merged as 96a61f4 |
| [SCRUM-53](https://siti-is212.atlassian.net/browse/SCRUM-53) | Nethren Balamurugan | 3 | Done | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-58](https://siti-is212.atlassian.net/browse/SCRUM-58) | SUNDARAM RAMASUBBU RAKSHA _ | 5 | To Do | PR #26 candidate, including full Safety workflow |
| [SCRUM-61](https://siti-is212.atlassian.net/browse/SCRUM-61) | JANNAVARAPU SHALIKA LAKSHMI _ | 5 | Done | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-62](https://siti-is212.atlassian.net/browse/SCRUM-62) | SITI ADILAH BINTE SELAMAT _ | 5 | To Do | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-67](https://siti-is212.atlassian.net/browse/SCRUM-67) | SITI ADILAH BINTE SELAMAT _ | 3 | Done | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-69](https://siti-is212.atlassian.net/browse/SCRUM-69) | SITI ADILAH BINTE SELAMAT _ | 5 | Done | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-71](https://siti-is212.atlassian.net/browse/SCRUM-71) | DOMNICK JEROM _ | 3 | In Progress | AC1–5 covered; AC6 scheduled for Sprint 4 |
| [SCRUM-72](https://siti-is212.atlassian.net/browse/SCRUM-72) | SUNDARAM RAMASUBBU RAKSHA _ | 5 | Done | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-74](https://siti-is212.atlassian.net/browse/SCRUM-74) | JANNAVARAPU SHALIKA LAKSHMI _ | 5 | Done | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-75](https://siti-is212.atlassian.net/browse/SCRUM-75) | SITI ADILAH BINTE SELAMAT _ | 5 | Done | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-76](https://siti-is212.atlassian.net/browse/SCRUM-76) | DOMNICK JEROM _ | 3 | In Progress | Already on main through PR #24, including 00a3c28/eb80933/aeba603 |
| [SCRUM-77](https://siti-is212.atlassian.net/browse/SCRUM-77) | Nethren Balamurugan | 3 | In Progress | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-89](https://siti-is212.atlassian.net/browse/SCRUM-89) | Nethren Balamurugan | 8 | Done | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-90](https://siti-is212.atlassian.net/browse/SCRUM-90) | DOMNICK JEROM _ | 8 | In Progress | PR #26 candidate, including full Safety workflow |
| [SCRUM-91](https://siti-is212.atlassian.net/browse/SCRUM-91) | JANNAVARAPU SHALIKA LAKSHMI _ | 3 | Done | Present in reviewed main/candidate; see AC matrix |
| [SCRUM-92](https://siti-is212.atlassian.net/browse/SCRUM-92) | JANNAVARAPU SHALIKA LAKSHMI _ | 2 | Done | Present in reviewed main/candidate; see AC matrix |

Jira initially shows 11 Done / 6 In Progress / 4 To Do, despite several merged implementations. This audit leaves statuses, descriptions and sprint dates unchanged. An old screenshot or a green pipeline does not establish acceptance.

## Evidence still required from the team

1. Review each test's correctness, inputs and independent expected results. Record a real reviewer and review date. Existing per-case CSVs often still say PENDING or contain old local-only CI references. The current execution records supplement them; an AI run does not fill those human fields.
2. Team members must perform and check the generated browser journeys themselves, as the FAQ's 19 October update requests. Record which journeys they checked and when. The automated J1–J5 run is agent execution evidence only.
3. Review coverage-by-file.csv, close reachable gaps or document justified exceptions against the actual story code. CI's 80% aggregate backend threshold does not replace the course target.
4. Complete the team's code/test review, PO acceptance and sprint review/retrospective evidence, then reconcile Jira statuses and the sprint's stored dates. Do not mark the whole sprint accepted solely from this audit.
5. Reconcile the historical diagram exports with the current [Safety/confirmation architecture supplement](../../c4/safety-confirmation.md). The supplement describes the new actor and components; the original SVG/PNG exports retain their historical scope.

## Requirement basis

The project root's SOURCE_INDEX.md contains the exact official paths and workbook cells. This audit follows `sources/SPM/PROJECT/Project Briefs/Week 4 Project Instructions.docx` (release/test rubric), `PROJECT/IS212 Project FAQ.docx` (19 October test review/evidence update), Week 4 testing slides 21–24 and 26–32, Week 6 CI slides 37–46, Week 9 E2E slides 26–28, and the applicable G3 Week 4/9 clarification cells. Week 7 customer change 6 supplies the Safety requirement. Section 7 of `outputs/sprint-3-implementation-guide.md` supplies the approved sprint handoffs.

The registered live Drive PROJECT folder was checked at the start of the audit; its September copies do not supersede the later local October FAQ. This session has no Slack connector, so it does not claim a new #g3/#all-is212 read. No ticket history was rewritten to conceal changes or deferred work.
