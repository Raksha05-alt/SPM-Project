# SCRUM-16: equipment reservations (G16a)

Nethren implements this phase on `feature/equipment-reservations`, using main `74248b9` and Jerom's G15 availability commit `d986aa9`. PR #20 publishes G15. Work date: 2 November 2026, Singapore time.

Technical Support reserve one complete requested line for the event's current period. The action locks the event, equipment type, plan and request, checks the displayed plan revision, then calls G15's `available_quantity` under the stock lock. It refuses insufficient stock and reports the current quantity. Adjacent periods may share stock; overlapping reservations consume it. A repeated or stale action returns 409 without adding another reservation, notice or history entry. Payloads supply a revision, not an arbitrary quantity, actor or period.

The service stores the reserving actor/time, request status and immutable history. After the last requested line has a matching active reservation, it records Technical Support's approval of the current equipment revision. Another resource action supersedes the previous technical approval and retains it in history. Technical Support can explicitly approve a plan needing no equipment by acknowledging that decision and entering review notes. Empty tables alone do not establish approval.

The resource transaction also calls the G04 `arrangements_changed(event, reason, actor)` service. A current Safety check becomes Superseded, and an affected Confirmed event returns to Planning. A failure rolls back the reservation, technical approval, Safety change, history and notices together. G20/G21 will complete the real Safety/confirmation user journey; the current Safety integration tests use explicit G04 model preconditions.

## API and screen

| Endpoint | Access and result |
| --- | --- |
| GET `/api/equipment/plans/` | Technical Support; only IDs/names of events in Approved, Planning or Confirmed. Includes plans needing no equipment. |
| GET `/api/events/{id}/equipment-plan/` | Technical Support or the assigned coordinator; refuses private drafts. Current revision, scoped event dates/status, request lines, reservation history and current technical approval. |
| POST `/api/equipment/requests/{id}/reserve/` | Technical Support; `{expected_revision}`; reserves the stored requested quantity for the stored event period. |
| POST `/api/events/{id}/approve-no-equipment/` | Technical Support; `{expected_revision, acknowledged: true, notes}`; refuses outstanding requests. |

Staff reach the screen through Equipment requests → Manage reservations or Review equipment plans. The assigned coordinator follows Equipment plan and reservations from the event. Reads expose the technical fields needed for this work. Other roles cannot call the resource actions. The browser invalidates plan, availability, inbox, event and notification queries after success or refusal, and reloads the plan on focus.

Migration `notifications.0012_equipment_update_kind` adds the equipment-arrangement notice category. It does not change equipment schemas. No package or lockfile changes.

## Sources and checks

Live Jira SCRUM-16 AC1–6; Sprint 3 guide G03/G14/G15/G16a and equipment section; Week 4 Project Instructions equipment availability/reservation and cross-feature workflow paragraphs; Week 4 G3 `Sheet1!C45:D45` (aggregate quantities permitted); Week 7 change 6 and Week 9 G3 `G3-5!C15:D15` (rechecking changed arrangements). The registered Drive PROJECT folder contains the same four older items; the local later official sources govern this phase. Slack tools were unavailable.

Week 4 Test Cases & Software Architecture slides 9, 16 and test-design section require AC-derived positive, negative and boundary cases. The FAQ's 19 October update allows automation but requires per-case correctness review and execution evidence. Backend cases cover real request/reserve/availability, exact stock, damaged/maintenance stock, adjacency and one-second overlap, replay, stale revisions, roles, elapsed dates, multi-item approval, no-equipment review and concurrent transactions. UI tests cover displayed quantities, payloads, errors, pending actions, reads and retained history.

Phase-one verification: **43 backend acceptance cases passed**, and the equipment dependency baseline passed **203 cases**. **213 frontend cases passed** and production build passed. Scoped coverage: reservation service and action views 100% statements/branches; equipment-plan screen and API client 100% statements/functions/branches (V8). The initial 29-case run failed before the action endpoints existed. Full repository and real browser regression will follow G16b integration.

Individual case records: `../test-cases/S3-SCRUM-16-equipment-reservations.csv`. Reviewer/date fields stay blank for the team's correctness checks. The AI assistant executed these checks; team review, the team's browser walkthrough and PO acceptance remain unrecorded. Jira remains In Progress.

G16b on `feature/equipment-release` adds manual release and the coordinator cancellation action as a dependent phase. It must use the same locks, revision, retained history and Safety invalidation contract. Adilah's G17 amendments must also call `advance_plan` under the event lock, release surplus through the shared release primitive, and recheck increased quantities under stock locks.
