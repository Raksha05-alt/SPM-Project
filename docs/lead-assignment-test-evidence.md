# SCRUM-89 / SCRUM-53 test evidence

Agent execution: 26 October 2026. Branch `feature/coordinator-lead-assignment`,
based on main `5e85cffc86cd9507de386573bcd21930227d26c4`.
Tested application/test source SHA256:
`1bd476db9e5d218f23c0bb31e8f5f0e53673e94a2b12cc3ad8e047f4b20ee81a`.
The source manifest identifies every measured source file without including secrets.

## Results

| Check | Actual outcome |
|---|---|
| Full backend suite, PostgreSQL 16 / Python 3.12 | 431 passed; includes real row-lock concurrency, access, persistence and rollback tests. |
| Full frontend unit/component suite | 116 passed. |
| Full Playwright suite, real seeded API/database | 7 passed, no skips or retries; includes Lead allocation and reassignment, old-owner refusal, organiser contact/notices and venue integration. |
| TypeScript + Vite production build | Passed. |
| Ruff lint and format checks | Passed. |
| Missing migration check | No changes detected. |
| Fresh database migration | All migrations applied successfully. |
| Upgrade from prior schema | Existing owner and notice preserved; no fabricated history; first real Lead reassignment stored previous owner and three notices. |
| Diff whitespace check | Passed. |

These are local agent checks, not GitHub CI results or a teammate's correctness review.
The database was a separate disposable PostgreSQL container; the project database was untouched.

## Measured coverage

Coverage percentages describe executable code, not acceptance completeness.

| Scope | Statement / line | Branch |
|---|---:|---:|
| Backend `assign_coordinator` and `submit_event` service functions | 100% | 100% |
| Four new Lead view actions: unassigned, assignments, coordinators, assign_coordinator | 100% | 100% |
| New `lead_serializers.py` | 100% | No conditional branches reported |
| `accounts/models.py`, event permissions and shortlist permissions | 100% | 100% of reported branches |
| Frontend `LeadDashboard.tsx`, `LeadEventDetail.tsx`, `leadAssignments.ts`, `AuthProvider.tsx` | 100% statements/lines/functions | 100% |
| Wider backend application code (excluding tests, migrations and admin) | 1,446 / 1,457 = 99.25% | 223 / 228 = 97.81% |

The repository's default combined report includes test files; its 99.59% combined
figure is **not** the production coverage claim. The measured frontend scope is
the four modules named above, not the whole frontend repository. Route/nav wiring
and the changed coordinator views are additionally exercised by the real browser suite.

The wider backend gaps remain in earlier code: ClarificationRequest and venue/
notification string representations; the defensive unassigned coordinator-name
serializer branch; the legacy clarification-resubmission branch with no owner;
the submit HTTP conflict handler; and three non-coordinator decision guards that
the permission layer rejects earlier. They are not new Lead allocation logic.
They are not inherently impossible to unit-test; closing those wider historical
gaps is outside this feature group, so this report does not claim whole-repository
100% coverage. Confirmed-state assignment is tested at service/API level; the
future event-confirmation and equipment workflows are not claimed as integrated here.

## Individual records and raw evidence

Local evidence directory:
`/Users/Mac/Documents/Codex/Projects/SPM/outputs/lead-assignment-2026-10-26/`.

- `individual-test-cases.csv`: 93 separate records for the new backend/submission,
  Lead UI/client/cache and changed browser journeys. Parameter variants have
  separate IDs. Each record includes story/AC, input, preconditions, action,
  expected result, executable selector, agent check, run outcome, source
  fingerprint and blank team reviewer/date fields.
  The same records are versioned at [SCRUM-89-53.csv](test-cases/SCRUM-89-53.csv)
  so teammates can access them after pulling this branch.
- `pytest.xml`, `vitest.json`, `playwright.json`: machine-readable full-suite results.
- `backend-coverage.json`, `frontend-coverage.json`,
  `frontend-coverage-summary.json`: coverage details.
- `source-manifest.json`: tested file hashes and baseline.
- `backend-run.log`, `frontend-run.log`, `build.log`: execution logs.

The application source fingerprint identifies this tested build before commit;
it is not a claim that the old main commit contains these changes.
The local coverage provider was installed without changing package.json or the
lockfile. Run normal tests with `pytest`, `npm test` and `npm run e2e`;
V8 coverage additionally needs `@vitest/coverage-v8@2.1.8` available locally.

## Team review before Done

Peer review and branch CI remain required before integration. A team member must
check test correctness, perform the generated E2E journey themselves as required
by the FAQ, and record their name/date and which cases they checked. This record
does not fabricate those checks or product acceptance.

To check the main journey: submit a complete organiser request and confirm it is
unassigned; inspect it as either Lead; assign Cora; check organiser contact and
recipient notifications; reassign Casey; confirm Cora loses direct and queue
access while Casey can open it. Review closed-event conflicts and stale-screen
responses against the automated case records. Do not mark future integration
criteria complete until the dependent endpoints run against these ownership rules.
