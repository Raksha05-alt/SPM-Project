# Feature group workflow

Use a short-lived branch for one coherent feature change or verification task. Group closely related stories only when the resulting change remains small enough to review and test properly. A feature group is not a permanent branch for the rest of the project.

## Names and ownership

- Use `feature/<group>` for feature work, `fix/<group>-<issue>` for a focused defect, and `docs/<topic>` for documentation-only work. Add a story key or short slice name when several independent branches belong to the same group.
- Include every affected SCRUM key in the commit messages and pull request description. Keep each story's acceptance criteria and test evidence separate even when several stories share a branch.
- Choose a branch owner to coordinate the work and open the pull request. More than one person may contribute commits. The branch also inherits earlier commits from everyone who contributed to its base; that is normal.
- Jira assignees identify responsibility for stories, not sole authorship of every line in a branch. Preserve original Git authors, dates and history.
- Use a separate branch for an independent change, even if the same person owns both changes. Do not put all of one person's tickets into a permanent personal branch.

## Current reverse engineering baseline

The agreed starting point is main commit `e50c746e3f8892128e25d0f2baadc27f8e0a0521`. This is a historical implementation baseline, not a claim that all current release requirements are complete.

The feature branches below start at that exact existing commit. They contain the whole application, not isolated copies of selected files. Creating them does not introduce new application commits or change the original authorship and dates. Their future diffs should concern only the selected feature group. Until actual work is committed, their diff against the baseline is empty.

`Trial_Code`, `final_changes`, and code added after the baseline are excluded from this reverse engineering pass. The later `c3e46ea` venue helper is preserved on its original branch but is not included here. Do not merge, cherry-pick, or delete excluded work without a separate instruction.

## Initial feature groups

These are the areas present in the approved implementation. The Jira responsibility column records current story assignees, not exclusive commit ownership or a reassignment. A branch owner should be agreed when work starts.

| Branch | Stories | Jira responsibility | Verification scope |
|---|---|---|---|
| `feature/account-access` | SCRUM-1, SCRUM-6 | Jerom | Session login/logout, role access, organisation boundaries and refusal auditing |
| `feature/event-request-intake` | SCRUM-7, SCRUM-15 | Adilah: 7; Shalika: 15 | Create a request, validate its details, submit and protect it after submission |
| `feature/draft-requests` | SCRUM-8 | Raksha | Save incomplete drafts, reopen stored values, restrict access and manage supported draft actions |
| `feature/request-review` | SCRUM-47, SCRUM-49, SCRUM-50, SCRUM-52 | Nethren: 47; Shalika: 49; Adilah: 50, 52 | Submitted queue, clarification/resubmission, approval, rejection and review decisions racing with client edits |
| `feature/coordinator-assignment` | SCRUM-51, SCRUM-54 | Nethren: 51; Shalika: 54 | Baseline automatic assignment, availability flag, assignment messages/contact details and assigned-event list |
| `feature/event-status` | SCRUM-55, SCRUM-56 | Nethren: 55; Raksha: 56 | Status vocabulary, public/internal visibility, timestamps and the implemented transition checks |

SCRUM-56 has only partial baseline coverage; putting it in a group does not mark it complete. Likewise, these groups do not establish that every acceptance criterion or the final Definition of Done has been met. Broader venue, equipment, registration and change-request features have no delivered implementation in this selected baseline and are not represented as completed feature branches.

## Original implementation evidence

Use the original commits and test files when documenting the earlier work. A few useful starting points are listed below; these are pointers, not an exhaustive authorship analysis.

| Group | Original commits reachable from the baseline | Existing executable evidence |
|---|---|---|
| Account access | `ad23019`, `2137b60`, `7364463` | `api/apps/accounts/tests/test_us_01_1_sign_in.py`, `test_us_01_2_role_based_access.py`; `web/src/auth/RequireRole.test.tsx` |
| Request intake | `93a3819`, `a225deb`, `49ab818` | `api/apps/events/tests/test_us_02_1_create_request.py`, `test_us_02_2_submit_request.py`; `web/e2e/draft-submit-queue.spec.ts` |
| Draft requests | `93a3819`, `7995002` | `api/apps/events/tests/test_us_03_1_save_draft.py`; the draft/save part of the browser journey |
| Request review | `44e68ab`, `972558f`, `35223d3`, `e039440`, `67b401d` | `api/apps/events/tests/test_us_04_1_coordinator_queue.py`, `test_request_clarification.py`, `test_approve_request.py`, `test_scrum_52_reject_request.py`, `test_concurrent_decisions.py` |
| Coordinator assignment | `fe65b30`, `0234cd7`, `60c2e01` | `api/apps/events/tests/test_scrum_51_assignment.py`, `test_scrum_54_assigned_events.py`; assignment/list component tests |
| Event status | `93a3819`, `44e68ab` | `api/apps/events/tests/test_us_06_1_event_status.py`, `test_services.py`; `api/apps/core/tests/test_status_machine.py` |

Shared modules and cross-feature regression tests may support more than one group. Reference them from each relevant case; do not duplicate or relocate code just to make folders or branches appear exclusive.

## Working on a group

1. Inspect the current branch and local changes. Preserve another developer's work. Fetch before selecting a base; do not silently adopt a newer or excluded baseline for this reverse engineering task.
2. Switch to the relevant group branch. If someone is already using it for a different change, agree ownership or create a smaller group-and-story branch from the agreed base.
3. Map each story and acceptance criterion to its implementation, original commits and existing tests. Record gaps honestly. Existing code remains existing code; documentation and tests written now have their actual current dates.
4. Add only the documentation, test improvements or justified fixes needed for that scope. Keep unrelated edits out of the commit. Do not reconstruct earlier development with new commits or dates.
5. Run the relevant tests and proportionate regression checks. Record the exact build, environment, actual results and evidence. Do not label a proposed, missing or blocked test as passed.
6. Open a small pull request with the purpose, branch owner, affected SCRUM keys, verification and any remaining limitations. Obtain a teammate's review and passing checks before merging into protected main. This guide does not change GitHub protection settings.
7. After the actual change is merged, retire its short-lived branch when safe. Start the next coherent change on a fresh branch, rather than keeping the same bucket open indefinitely.

## Preserved branches

The initial transition creates new feature-group references; it does not rename or delete the older personal branches. `Jerom`, `Adilah` and `Shalika` point to history already included in the baseline. `Raksha` contains a divergent draft implementation and `Nethren` contains the excluded venue helper, so neither is interchangeable with the new baseline branches.

Keep all original branches, including the excluded integration branches, until their unique commits, active pull requests and local checkouts have been checked and deletion has been explicitly approved. Do not force-push or rewrite them to make earlier development appear to have used the new workflow.

The feature-group references were introduced on 15 October 2026. They are organisation for current and future verification work, not evidence that those branches existed in an earlier sprint.

## Course basis

Week 5 Communicating Design and Collaborating on Code, slides 45 and 52, recommends small coherent pull requests, short-lived branches, review, passing checks and frequent integration. The Week 5 lab, pages 5-6, demonstrates the branch, review, merge and deletion loop. The exact branch names and initial feature groups above are this project's chosen convention, not a separate naming mandate from the course.
