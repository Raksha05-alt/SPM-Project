# SCRUM-64/68: venue discovery and event shortlists

This is the original Sprint 2 record. SCRUM-89 now restricts event and shortlist
reads to the assigned coordinator; see [Lead allocation](lead-assignment.md).
The original broader-read tests remain in Git history.

Implementation and agent-executed integration verification: 26 October 2026.
Branch: `feature/venue-discovery`.
Base: updated main `3322649d409f577a100f972160f90e1a7e311bce`, including Raksha's venue catalogue, Shalika's layouts (PR #5) and Adilah's date blocks/availability (PR #6).
The checks below cover the local implementation on that base. The team still needs peer review, branch CI and a merge to main. No remote push or Jira completion forms part of this verification.

## Completion boundary

This slice implements search against recorded venue requirements, date-block integration and persistent event shortlists. Booking/hold occupancy remains a dependency of SCRUM-64's full availability criterion.

| Story / original criterion | Current evidence | Status |
| --- | --- | --- |
| SCRUM-64 AC1: combine date/time, attendance, layout and facilities | API/UI combine supplied filters using the merged layout helper and shared Singapore hours/date-block rules. Overlapping blocks exclude a venue; adjacent blocks permit it. | Date blocks integrated; booking/hold occupancy outstanding |
| SCRUM-64 AC2: capacity, including equality | API boundary cases 59/60/61 for attendance 60; browser uses exact capacity 60. | Implemented and tested |
| SCRUM-64 AC3: required layout | API excludes a venue without the selected agreed-list layout. | Implemented and tested |
| SCRUM-64 AC4: omit empty filters | Empty optional fields do not constrain results. Start/end together form one optional period filter; a half-entered period returns a validation error. | Implemented and tested |
| SCRUM-64 AC5: no matches | Empty API result and readable UI no-match message. | Implemented and tested |
| SCRUM-64 AC6: refuse Organiser/Attendee access | API refusals and auditing; guarded routes; browser checks for both roles. | Implemented and tested |
| SCRUM-68 AC1: save against event and reopen | Database entry, fresh-client GET, browser reload; unique event/venue constraint and concurrent-add test. | Implemented and tested |
| SCRUM-68 AC2: remove | Event-scoped deletion, persisted fresh read, browser reload. | Implemented and tested |
| SCRUM-68 AC3: matching/unmet criteria | Save search criteria; recompute each assessment against current venue records on every GET. | Implemented and tested |
| SCRUM-68 AC4: flag a venue that becomes blocked | Real Venue Staff create/edit/delete operations refresh the saved entry's assessment. An overlapping block shows UNAVAILABLE with its reason, without removing the entry. | Implemented and tested |

Keep SCRUM-64 open until booking/hold occupancy works against real records. SCRUM-68's listed original criteria now have executable evidence; the team still needs correctness review and its remaining Definition of Done checks before marking it Done. Statement coverage does not establish missing requirements or team acceptance.

## Try the implemented slice

Follow README setup using the team's SPM database, then run `python manage.py migrate` in `api/`. Migration `venues.0002_venueshortlistentry` adds the shortlist table and its unique constraint. `venues.0003_merge_blocks_and_shortlist` joins it with Adilah's `0002_venueblockhistory_venueblock`. Both existing migration names remain intact; the merge adds no schema operations. Django applied the full graph to a fresh PostgreSQL database during this verification.

1. Sign in as an organiser, create a valid new request and submit it. Automatic assignment supplies its coordinator under the original SCRUM-51 workflow.
2. Sign in as that coordinator. Open the event, then **Venue search and shortlist**. The header also offers standalone **Venue search**.
3. Search by attendance, layout, required facilities and an optional complete start/end period. The form starts with the event's dates, attendance and layout. Enter structured facility names; the application does not infer them from free-text equipment notes.
4. Add a candidate to the shortlist and reload. Remove it and reload to verify persistence.
5. As Venue Staff, use **Venue availability** to create a block over that period. Reload the coordinator's screen: search excludes the blocked room, and its saved shortlist entry remains with the reason. Edit the block to another day or remove it, then reload to see the updated assessment. Taking a venue out of service also flags its saved entry. Restore shared demo data after testing.

Historical seeded requests may have no coordinator. Their shortlists stay read-only. Submit a new request to exercise automatic assignment; this slice does not add manual assignment or rewrite seed ownership.

The amber notice and each UNVERIFIED result describe a real integration gap. A shortlist entry does not reserve a venue or approve a booking.

## API contract

All new endpoints require an authenticated Event Coordinator. Existing staff catalogue endpoints and Venue Staff write permissions remain unchanged.

| Method and path | Contract |
| --- | --- |
| `GET /api/venues/search/` | Optional `attendance`, `layout`, repeated `facilities`, and paired ISO-8601 `start`/`end`. Returns `results`, normalized `criteria`, `date_blocks_integrated: true`, `availability_integrated: false` and a `limitation` message. |
| `GET /api/events/<event_id>/venue-shortlist/` | Returns `event_id`, server-derived `can_edit`, `entries`, both capability flags and the availability limitation. Each entry includes saved `search_criteria` and a fresh `match`. |
| `POST /api/events/<event_id>/venue-shortlist/` | Body `{ "venue_id": 3, "criteria": { "attendance": 60, "facilities": ["Projector"] } }`. Returns 201 for a new entry or 200 for an existing one. Repeated adds preserve the saved criteria. |
| `DELETE /api/events/<event_id>/venue-shortlist/<venue_id>/` | Removes only this event/venue entry. Returns 204; unknown entries return 404. |

A match contains the venue, criterion results (`MATCH`, `UNMET`, `UNVERIFIED`), `matches_recorded_requirements`, and `availability_status` (`UNAVAILABLE` or `UNVERIFIED`). It never returns AVAILABLE while booking/hold checks are missing.

Start/end accept offsets and normalize through Django's timezone handling. Evaluate operating days and hours in `Asia/Singapore`. Permit an event exactly at opening/closing boundaries. Reject periods extending outside those hours, spanning closed overnight hours, or using an unrecorded schedule. This follows the current venue schema's same-day opening/closing representation; it does not add overnight opening support.

Compare facility names after whitespace trimming and case folding, and require all supplied facilities. Keep layout values from the existing `RoomLayout` agreed list. Exclude out-of-service venues from candidate searches. With no period entered, do not apply the operating-hours criterion.

Use half-open block intervals: a block ending at the search start, or starting at its end, does not overlap. Reuse `availability()` and `within_operating_hours()` from the merged availability implementation. Batch-prefetch blocks for each request so these checks and venue serialization avoid one query per result.

Saved criteria describe the search used when adding an entry. Reassess against fresh venue data; do not cache the original result. If a saved entry has no search dates, assess date blocks against its event's preferred period, when recorded. Keep the saved criteria unchanged and explain this fallback on screen. Without either period, report no date-block assessment. An omitted search period still leaves search results unconstrained by date. These are explicit implementation choices, covered by tests. Re-run search after changing event requirements; this slice does not rewrite saved attendance/layout/facility filters.

## Permissions and consistency decisions

- Preserve baseline coordinator reads of submitted, non-draft events. This does not introduce the later Lead/assigned-only visibility rules.
- Restrict shortlist mutations to the coordinator assigned to the event, matching the existing owner-controlled review actions. This is the implementation's planning-write policy, not an amendment to an old Jira criterion.
- Refuse draft access. Completed, Cancelled and Rejected events have read-only shortlists.
- Resolve permission decisions through permission classes. Audit refused writes after rolling back their mutation transaction so the refusal record survives.
- Lock the event row during add/remove. Re-read and lock the venue before assessing a new addition, using the same venue-row lock as staff block writes. Reject a new addition if staff blocked it after the search. Enforce uniqueness in PostgreSQL and handle repeated requests. Roll back entry changes and success-audit records when mutation/response construction fails.
- Use joined venue/user reads to avoid a query per result. Tests check constant query counts for search and shortlist retrieval.
- After either a successful or failed client mutation, refetch the shortlist. A lost response can follow a committed save; the UI must not claim the server made no change.

## Test-case map

Paths below are relative to the repository root. Backend function selectors belong to `api/apps/venues/tests/`. Tests use the real PostgreSQL database except injected failure paths. Expected capacities, dates, status and persisted values come from fixtures and the original criteria, not production matching calculations.

| Case ID | Preconditions / input and action | Independent expected result | Executable selector |
| --- | --- | --- | --- |
| VD64-01 | Coordinator; rooms differing in capacity, layout, facilities, hours/status; submit all filters | Only the recorded-data match; availability remains UNVERIFIED | `test_scrum_64_filter_venues.py::test_ac1_supplied_filters_are_combined` |
| VD64-02 | Attendance 60; room capacity 59, 60, 61; search | Exclude 59; include 60 and 61 | `test_ac2_capacity_boundary_includes_exact_capacity` in the same file |
| VD64-03 | Classroom-only room; request Theatre | Exclude room | `test_ac3_unsupported_layout_is_excluded` |
| VD64-04 | Leave period/layout/attendance/facilities empty; search | Omitted criteria do not exclude a venue | `test_ac4_omitted_or_empty_filters_do_not_exclude_on_that_basis`, `test_ac4_other_filters_still_apply_when_layout_and_period_are_omitted` |
| VD64-05 | Enter attendance above available capacities | HTTP 200 empty results; UI names no match | `test_ac5_no_matches_returns_an_empty_result_not_a_server_error`; component test `SCRUM-64 AC5` |
| VD64-06 | Non-coordinator or anonymous direct request | HTTP 403, no venue disclosure, refusal audit | `test_ac6_only_coordinators_can_search`, `test_anonymous_search_is_refused_and_audited`; browser role cases |
| VD64-07 | Invalid capacity/layout/date; incomplete, equal or reversed period | HTTP 400; no venue mutation | `test_invalid_filters_return_validation_errors_without_mutation` |
| VD64-08 | Required facilities with whitespace/case duplicates and one absent facility | Normalize duplicates; require all distinct facilities | `test_facility_names_are_trimmed_case_insensitive_and_all_required` |
| VD64-09 | Singapore weekday/time boundaries, closed weekend, overnight interval and missing hours | Include exact opening/closing; exclude unsupported periods | `test_event_period_uses_singapore_operating_days_and_exact_hour_boundaries`, `test_missing_hours_cannot_establish_a_match_for_a_supplied_period` |
| VD68-01 | Assigned coordinator adds a venue; new API client reads event shortlist | Persist event/venue/creator/criteria and return same entry | `test_scrum_68_shortlist.py::test_ac1_add_persists_against_the_event_and_reopens_through_a_fresh_client` |
| VD68-02 | Add same event/venue twice or concurrently | One row; one 201 and one 200; retain original criteria | `test_ac1_repeated_add_is_idempotent_and_preserves_saved_criteria`, `test_concurrent_adds_create_only_one_entry`, database uniqueness test |
| VD68-03 | Same room shortlisted for two events; remove from one | Remove only chosen event's entry; fresh read empty there | `test_ac2_remove_deletes_only_that_events_entry` |
| VD68-04 | Save capacity/layout/facility filters; lower venue capacity and remove layout; reopen | Capacity/layout UNMET; retained facility MATCH; no deletion | `test_ac3_reopen_rechecks_current_venue_data_against_saved_filters` |
| VD68-05 | Save entry; Venue Staff takes room out of service; reopen | UNAVAILABLE with explanation; retain saved entry | `test_ac4_out_of_service_venue_is_flagged_on_reopen_without_deleting_saved_entry`; real browser journey |
| VD64-10 | Search 1 March 2027, 09:00–17:00 Singapore; create overlapping, adjacent and other-day blocks | Exclude overlaps, including one second; include adjacent and other-day blocks | `test_ac1_real_blocks_exclude_overlaps_but_not_adjacent_or_other_dates` (seven parameter cases) |
| VD64-11 | Venue Staff creates a block, moves it to another day, moves it back, then deletes it | Search excludes, includes, excludes, then includes the room | `test_ac1_staff_block_create_edit_and_remove_refresh_search_results` |
| VD64-12 | Currently blocked venue; omit search period | Return room as a candidate without applying a date filter; show current operational status | `test_ac4_no_period_does_not_apply_temporal_filter_even_if_venue_is_currently_blocked` |
| VD68-11 | Save entry; staff creates, edits and removes a real overlapping block | Retain entry/criteria; explain block; refresh assessment after each change | `test_ac4_real_staff_block_flags_saved_entry_and_changes_refresh_without_removal`; component test `SCRUM-68 AC4`; real browser journey |
| VD68-12 | Staff blocks venue after search, before a new shortlist POST | HTTP 400; no entry or success audit | `test_block_added_after_search_prevents_stale_shortlist_add` |
| VD68-13 | Save without search dates; event has dates; staff blocks that period | Flag against event period without rewriting saved filters | `test_ac4_without_saved_dates_rechecks_event_period_without_rewriting_saved_filters` |
| VD68-14 | Neither event nor saved search has dates | Keep UNVERIFIED; do not claim date-block validation | `test_no_search_or_event_dates_does_not_invent_a_checked_period` |
| VD68-06 | Different coordinator reads, adds, deletes | Read allowed under baseline; writes 403 and audited | `test_unassigned_coordinator_can_read_submitted_event_but_cannot_modify_shortlist` |
| VD68-07 | Draft, terminal event, forbidden role or anonymous caller | No unauthorized mutation; read-only terminal state | Draft/terminal/non-coordinator/anonymous cases in `test_scrum_68_shortlist.py` |
| VD68-08 | Room changes before adding; invalid nested filters or nonexistent resources | Reject invalid/unmatched addition; return validation/not-found result | `test_venue_that_no_longer_matches_cannot_be_added`, out-of-service/invalid/unknown-resource cases |
| VD68-09 | Fail response construction after insert or fail deletion after removing row | Transaction restores pre-action entries; no false success audit | `test_response_failure_rolls_back_new_entry_and_success_audit`, `test_delete_failure_rolls_back_removal_and_success_audit` |
| VD68-10 | Client save/delete fails, or save commits but response is lost | Explain uncertainty; refetch server state; do not announce success | Failure/lost-response component tests in `web/src/pages/VenueDiscovery.test.tsx` |
| VD-PERF | Five venues/entries, creator/updater metadata and real blocks | Constant query count: search 2, shortlist 3 | `test_search_queries_do_not_grow_per_venue`, `test_ac1_block_search_uses_constant_queries_with_multiple_real_blocks`, `test_list_uses_constant_query_count` |
| VD-E2E | Real accounts/API/PostgreSQL; create venue and request, filter exact capacity, save/reload, create/edit/remove block, change service status, remove/reload | Search excludes the blocked room; saved entry persists with reason; fresh reads reflect edits/removal | `web/e2e/venue-discovery.spec.ts`: search/persist/recheck blocks/status/remove journey |

API wrapper tests in `web/src/api/venueDiscovery.test.ts` cover repeated facility encoding, omitted filters and event-scoped paths. Component tests also cover default event filters, clearing, empty results, validation, search retry, read-only controls, event/shortlist load failures and standalone search.

### Case still blocked by a missing dependency

| Case ID | Setup/action | Required expected result | Dependency |
| --- | --- | --- | --- |
| VD64-B01 | Add a real overlapping confirmed booking or original tentative hold; search its period, then change/remove it | Exclude occupied rooms and reflect changes/removal using the shared availability contract | Real booking/hold persistence and occupancy integration |

VD64-B01 has not executed or passed. The former date-block dependency cases now execute through VD64-10/11, VD68-11 and VD-E2E. Do not add fake booking records or an always-available stub to claim the remaining case passes.

## Verification record

Agent executed these checks on 26 October 2026 against the local working tree based on `3322649`, using Python 3.12.13, Django 5.1.15, PostgreSQL 16 in a dedicated disposable container, and local Node 23.6.0. The repository CI targets Node 20; no CI run exists for this unpushed implementation yet. No shared development database participated in these runs.

| Check | Actual result |
| --- | --- |
| Complete backend `pytest` | 372 passed, including 77 discovery/shortlist cases |
| Configured aggregate statement coverage | 99.70% (3,661/3,672 statements); configured 80% gate passed |
| Production backend statement coverage, excluding tests/migrations | 99.25% (1,328/1,338 statements) |
| Four new discovery backend modules | 100% statement coverage (169/169 statements); branch coverage not measured |
| Django system and missing-migration checks | Passed; no missing migrations |
| Ruff lint and formatting | Passed |
| Frontend type check / Vitest / production build | Passed; 97 tests, including 20 discovery/API tests |
| Full existing plus new Playwright suite against real API/database | 7 passed, including 3 new discovery browser cases |
| Whitespace/conflict-marker check | Passed for the implementation changes |
| Peer review, CI on this branch, main merge, team walkthrough/demo | Not performed; do not tick these as complete |

The coverage configuration includes tests/migrations. The separate production number above excludes both. Ten uncovered production statements remain in existing event models/views, notification models and the two block-model string representations; one additional missed line belongs to an existing concurrent test. The new discovery modules have no missed statements. Frontend coverage and backend branch coverage were not measured. Passing tests and statement coverage do not establish full course-rubric acceptance.

The focused integration run exposed a test comparing UTC and Singapore strings for the same instant; it now compares parsed timestamps. The first browser run assumed all search results would disappear after blocking one room. Reload restores event defaults, so other unblocked rooms can remain; the corrected assertion checks the target room's absence and its retained shortlist entry. The final full runs above pass after those test corrections. No assertion was relaxed to permit a blocked target room.

Execution artifacts live outside the checkout under `../outputs/venue-discovery-integration-2026-10-26/`: `api.xml`, `web.xml`, `e2e.xml` and `api-coverage.json`. JUnit contains individual test names, parameter instances, timestamps and actual outcomes. `test-execution-register.csv` lists the 100 discovery/shortlist test instances (77 API, 20 frontend and 3 browser), their selectors, final implementation commit and agent run/check records. Use the input/oracle descriptions in this map with those records and executable assertions. Build reference: local implementation on base `3322649`; the final Git commit identifies the review candidate. The agent inspected and ran these tests on 26 October 2026. **Human correctness reviewer/date and the team's browser walkthrough remain pending for each case.** Record actual reviewers and dates after they check the cases; agent execution does not fill those fields.

## Integration handoff

Adilah's merged SCRUM-13/17 date-block implementation now supplies the shared checks used inside `assess_venue` for both search and fresh shortlist reads. The local integration adds request-scoped prefetch support to that service and the venue serializer; direct availability calls keep their existing overlap rules. All existing availability/block tests pass alongside the new integration cases.

Once the booking workflow exists, extend the shared availability contract to account for real confirmed bookings and original tentative holds. Replace the UNVERIFIED booking criterion with its result, filter occupied rooms, and update the capability flag and UI copy together. Execute VD64-B01 before claiming complete availability.

Keep original tentative-hold occupancy distinct from SCRUM-88's later expiry/reminder workflow. Do not add buffers, multi-venue allocation, Lead assignment, Safety review or editable layout-catalogue rules in this phase.

Search now calls Shalika's merged `supporting_layout()` queryset helper. It introduces no competing layout catalogue or Venue model replacement.

Shared-model changes in this slice add the `VenueShortlistEntry` table alongside the merged block models. Excluded branches/code and the unrelated local `docs/branch-test-review.md` remain untouched. Recovery stash `d351b5e48c1e6decc7c4b07fb72c4b82d551ef6e` preserves the local work from before main integration; keep it until the team confirms the result.
