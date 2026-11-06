# Coverage regression checks

6 November 2026. The current local readiness build passed 1,925 backend, 454 frontend and 32 real-browser executions. The backend evidence consists of a full 1,923-case run plus two real PostgreSQL layout races, with appended coverage. No remote CI run is claimed.

Production-only backend coverage is 99.14% of lines and 97.69% of branches. Vitest measures 94.55% of frontend lines and 91.37% of branches; browser execution is not included in that instrumentation.

The six supporting regression groups in [the case CSV](../test-cases/QA-coverage-regressions.csv) cover form/queue recovery, withdrawal connectivity, hold lifecycle/worker behaviour, change-review guards, confirmation permissions and concurrent layout writes. They add 55 executions and fix six visible error/recovery gaps. The existing FIFO browser journey also checks real offline/reconnection handling.

The test workbook records each execution and assigns peer reviewers. Assignment does not establish completed review. Record the actual reviewer, review date, comments and outcome after checking each case.

Detailed local evidence and exact remaining gaps: project-root outputs/coverage-gap-closure-2026-11-06/COVERAGE-GAPS-AND-NEW-TESTS.md and remaining-coverage-gaps.csv. Remaining uncovered paths include model/admin display, some defensive booking races and frontend bootstrap/transport wiring; full coverage is not claimed.
