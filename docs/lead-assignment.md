# SCRUM-89 / SCRUM-53: Lead allocation and reassignment

Implementation branch: `feature/coordinator-lead-assignment`.
Base: main `5e85cffc86cd9507de386573bcd21930227d26c4`.
This is Nethren's first Sprint 3 dependency group (G01). Equipment work follows
its prerequisites under the agreed Sprint 3 implementation guide.

## Requirements and decisions

Sources checked on 26 October 2026: live Jira SCRUM-89 AC1–7 and SCRUM-53 AC1–3;
Week 7 customer changes, page 2, change 5; Week 9 G3 clarification answers D16/D18.
These replace automatic allocation and broad coordinator reads from the earlier increment.
Testing/evidence follows the Project FAQ's 19 October update, Week 4 project
instructions/testing rubric, Week 6 CI and Week 9 automated E2E guidance.

- Submission enters a Lead-only unassigned queue. It never picks a coordinator automatically.
- All active Leads can allocate and reallocate submitted events. The acting Lead
  becomes the current supervising Lead; the previous supervisor remains in history.
- The target must be an active Coordinator account. The existing explicit
  availability flag is advisory and visible to the Lead, without a workload or
  calendar calculation. This implements manual Lead selection from the G01 contract.
- Drafts are private. Completed and Cancelled events refuse allocation.
  Rejected events remain inspectable and may be reassigned because the AC excludes
  only Completed/Cancelled; reassignment never changes event status. The default
  active-events filter excludes Rejected, Completed and Cancelled.
- Coordinators can list, read and act only on their assigned events, including
  event shortlists. Search of the venue catalogue remains role-based. Leads
  inspect allocations but cannot approve, reject, clarify or edit as a coordinator.
- Notifications are persistent in-app messages. Each real allocation sends one
  notice per distinct new coordinator, previous coordinator and original submitting
  organiser. Initial allocation has two recipients; reassignment has three.
- Each change records old/new coordinator, acting Lead, previous supervising Lead,
  timestamp and revision. No endpoint edits or deletes this history. Referenced
  accounts are protected from deletion; deactivate accounts instead.

## API and data contract

Existing session authentication and CSRF apply. Add `COORDINATOR_LEAD` to role
guards; its landing page is `/lead`.

| Endpoint | Contract |
|---|---|
| GET `/api/events/unassigned/` | Lead-only, Submitted and coordinator null; oldest submission first, then ID. |
| GET `/api/events/assignments/` | Lead-only allocation overview, defaults to active events. Optional `supervised_by=me`, `active=true\|false`; invalid tokens return 400. Includes unassigned active requests. |
| GET `/api/events/coordinators/` | Active Coordinator IDs, names, emails and advisory availability flag. |
| GET `/api/events/{id}/` | Leads receive current allocation, supervisor, revision and occurrence history. Organisers receive contact details without internal history/supervisor fields. |
| POST `/api/events/{id}/assign-coordinator/` | Body `{"coordinator_id": 3, "expected_revision": 0}`. Returns current detail. 400 invalid payload/target; 403 role/private draft; 404 unknown event; 409 stale revision or closed event. |

EventRequest adds nullable `supervising_lead` and `assignment_revision` (default 0).
CoordinatorAssignment stores occurrences, unique on (event, revision).
Notifications reference an occurrence and are unique on (recipient, occurrence).
The original approval/rejection notice uniqueness remains.

Assignment locks the fresh event row, checks the observed revision and rechecks
the actor and target account. A matching current coordinator with the current
revision is a no-op. A stale revision conflicts even when its selected coordinator
happens to match again (A→B→A). Two competing Leads cannot silently overwrite each
other. The target account uses a PostgreSQL NO KEY UPDATE lock: its role/active
fields stay stable without blocking history foreign-key checks when two Leads
swap coordinators across different events. History, allocation, notifications and response construction share one
transaction. Failed history/notification/serialization writes roll back the save.
Existing audit writes retain their best-effort policy.

Existing coordinator decisions and shortlist writes use the same event-row lock
and recheck ownership. A reassignment after their first permission check is
therefore refused and audited. Client caches clear on sign-out/sign-in;
event pages recheck when focused and after failed decisions. This does not add
push messaging: an idle browser can show old data until its next refresh, but the
server refuses access and actions from the old owner immediately.

## Migration and demo

Apply migrations normally, then run `python manage.py seed_demo_data`.
New demo logins are `lead@connectsphere.example`, `lead2@connectsphere.example`
and `coordinator2@connectsphere.example`; password `connectsphere-demo`.
Existing demo accounts and credentials are preserved.

Fresh installs and upgrades from the previous accounts/events/notifications
schema were checked with PostgreSQL 16. Existing owners and notices remain;
legacy assignments start at revision 0 without invented history or supervisors.
The first subsequent Lead allocation records the real old owner and acting Lead.

## Acceptance traceability

| Story / AC | Executable evidence |
|---|---|
| 89 AC1: submit unassigned | `test_scrum_51_assignment.py`: complete/incomplete/repeated and concurrent submission regressions. |
| 89 AC2: shared Lead-only queue | `test_ac1_ac2_unassigned_queue_in_oldest_order_for_all_leads`; `test_ac2_non_leads_refused_and_audited`; Lead dashboard tests; browser journey checks both Leads. |
| 89 AC3: manual allocation and contact | `test_ac3_assignment_persists_history_contact_and_notices`; active/invalid target, payload and rollback tests; Lead form and browser tests. |
| 89 AC4 / 53 AC1, AC3: reassign, refuse closed events | `test_ac4_reassignment_a_b_a_keeps_notices_and_previous_supervisor`; status, no-op/stale, competing-Lead and cross-event owner-swap deadlock tests. Confirmed-status fixture tests allocation permission only, without claiming an event-confirmation integration test. |
| 89 AC5 / 53 AC1: current owner only | `test_ac5_previous_owner_loses_list_detail_actions_shortlist`; stale-service and mid-request decision tests; amended original queue/read/shortlist regressions; browser previous-owner denial and new-owner access. |
| 89 AC6: allocation and supervision filters | `test_ac6_allocation_filters_and_validation`; `test_lead_lists_do_not_query_history_per_event`; dashboard filter tests. |
| 89 AC7 / 53 AC1–2: notices and immutable history | A→B→A persistence/recipient tests; database uniqueness/protected account tests; read-only history; form tests and browser refresh. |

Backend selectors are in
`api/apps/events/tests/test_cr_05_lead_assignment.py`, unless another file is named.
Frontend selectors are in `web/src/pages/lead/LeadAssignments.test.tsx`,
`web/src/api/leadAssignments.test.ts`, `web/src/auth/AuthProvider.test.tsx`.
The browser journey is `web/e2e/draft-submit-queue.spec.ts`; venue integration is
`web/e2e/venue-discovery.spec.ts`. None of these browser tests mocks the API.

Execution totals, production-code coverage and individual case records are in
[test evidence](lead-assignment-test-evidence.md). Original automatic-allocation
assertions were replaced only where the customer change superseded them; original
versions remain in Git history.

## Integration and review

The implementation stays on its feature branch until peer review and branch CI
pass. Merge G01 to main first, then each dependent teammate pulls main into their
own feature branch and tests against it. Future owner-controlled endpoints must
use `event.coordinator_id`, recheck under the same event row lock and audit refusals.
Do not allow access through previous history or notification ownership.

This implementation supplies role, allocation and ownership contracts. Teammates
must test their new booking/equipment actions against them when those actions
exist; this branch does not prove future integration.

Team correctness review, the FAQ's team-performed browser check and acceptance
remain pending. Agent execution is verification evidence, not team sign-off.
No Jira completion or main merge is implied.
