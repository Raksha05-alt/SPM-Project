# SCRUM-64 decision foundation and SCRUM-68 follow-up plan

## Intent

SCRUM-64 lets Event Coordinators filter venues using explicit event requirements. A result must satisfy all supplied criteria. Empty criteria do not restrict the results. SCRUM-68 stores venue selections against an event and compares each saved selection with the same criteria when the coordinator returns.

The implementation belongs on Nethren. The starting commit is e50c746, with 176 backend tests, 43 UI tests and the draft-to-queue browser journey passing on 5 October 2026. These results describe that build, not a guarantee about future edits.

## Delivery phases

1. Derive cases from Jira criteria and the course materials; review the existing test suites.
2. Implement and verify venue filtering, including capacities, facilities, layouts, operating hours, occupied periods and denied access.
3. Implement and verify persistent event shortlists, criteria comparisons, removals and changing availability.
4. Run regression, browser and seeded-fault checks. Commit the phases with ticket-specific messages and retain the execution evidence.

## Case-design rules

- Each case names its acceptance criterion or the specific permission/integrity rule it defends.
- Preconditions and inputs specify actual capacity, dates, layout and facility values.
- Expected results come from the requirement. Tests do not calculate their expected answer by calling the production decision code.
- Capacity cases cover 119, 120 and 121 attendees against a 120-seat venue.
- Time cases cover overlapping periods and the adjacent end-equals-start boundary.
- Persistence cases open the shortlist in a separate request or browser refresh.
- Failure cases assert unchanged saved data, not only a response status.
- Automated execution reports record the build, environment, result and test identifier. Human acceptance remains unrecorded until a team member performs it.

## Scope and dependencies

The pushed branches have no venue data implementation. SCRUM-65 and SCRUM-17 remain assigned to Raksha and Adilah. The shared data-model decision is pending. Venue catalogue/calendar screens and booking approval remain separate work.

The independent decision tests below exist and passed (31 parameterized cases). They do not establish that the search endpoint, page or shortlist works. Those layers are pending the shared-data integration decision. This commit introduces no models, migrations, HTTP routes or UI changes, and neither story is complete.

Input contract: venue facts are validated by the future data adapter. Supplied search times must be paired, timezone-aware ISO timestamps with end strictly after start. Invalid search or occupied periods raise `ValueError`; an API adapter must translate that into a useful validation response. Omitted time filters impose no time restriction.

The Week 7 customer update requires configurable setup and turnaround times. This foundation does not yet expand either the requested event or persisted booking periods by those buffers. Adjacent-period tests below verify interval arithmetic only, not buffer-aware venue eligibility. Persisted availability, affected-booking flags, hold expiry, multiple bookings and role enforcement remain integration work.

| Case ID | Criterion/rule | Preconditions and data | Action | Independently expected result | Automated evidence |
|---|---|---|---|---|---|
| TC64-U01 | AC2 capacity | Active 120-seat venue; attendance 119, 120, 121 | Compare the capacity requirement | Match, match, fail respectively | `test_ac2_capacity_just_below_exactly_at_and_above` |
| TC64-U02 | AC1 AND facilities | Venue has Projector and Hearing loop; request projector; both; Projector and Stage | Compare required facilities | Match, match, fail respectively | `test_ac1_every_required_facility_must_match` |
| TC64-U03 | AC3 layout | Venue supports THEATRE; request BANQUET with attendance 100 | Compare requirements | Exclude despite sufficient capacity | `test_ac3_missing_layout_is_excluded_even_when_capacity_matches` |
| TC64-U04 | AC4 omitted criteria | Active venue, then inactive venue; no user criteria | Compare requirements | Only operational status applies; inactive fails | `test_ac4_empty_criteria_apply_only_operational_status` |
| TC64-U05 | Official search core feature | Location Central, recorded wheelchair access true, then unknown; request CENT/West and wheelchair access | Compare the supplied criteria | Case-insensitive location match; unknown access fails; West fails | `test_location_and_accessibility_filters_use_recorded_facts` |
| TC64-U06 | Operating-hour boundary | Monday venue open 08:00-20:00; requested periods 08:00-20:00, 07:59-20:00, 08:00-20:01 | Compare time requirement | Match, fail, fail respectively | `test_operating_hours_boundaries` |
| TC64-U07 | Missing/closed operating data | Unknown opening time, Sunday-only venue searched on Monday, then overnight request | Compare time requirement | Each fails operating-hour check | `test_unknown_hours_closed_day_and_overnight_period_are_unavailable` |
| TC64-U08 | Availability conflict boundary | Request 09:00-10:00; occupancy 08:00-09:00, 10:00-11:00, 08:00-09:01, 09:59-11:00, 09:00-10:00 | Compare periods | No overlap, no overlap, overlap, overlap, overlap | `test_availability_adjacent_periods_do_not_overlap` |
| TC64-U09 | Timezone consistency | Request 01:00-02:00 UTC; Singapore venue open 08:00-20:00; occupancy 09:30-10:30 Singapore | Compare hours, then occupied period | Hours pass; occupied-period check fails | `test_timezones_are_compared_as_instants_in_singapore_operating_hours` |
| TC64-U10 | Paired search endpoints | Supply only start, then only end | Compare requirements | Reject each incomplete period with `ValueError` | `test_search_requires_both_period_endpoints` |
| TC64-U11 | Valid search period | Missing timezone on start/end; malformed start; equal or reversed endpoints | Compare requirements | Reject each period, never report a suitable venue | `test_invalid_search_periods_are_not_treated_as_matching` |
| TC64-U12 | Valid occupied period | Occupancy 09:00-09:00, then 09:00-08:59 | Compare overlap against 09:00-10:00 | Reject each invalid occupied period | `test_empty_or_reversed_occupied_periods_are_rejected` |
| TC64-U13 | Explicit occupied timezone | Remove timezone from occupied start, then end | Compare overlap | Reject rather than depending on host timezone | `test_occupied_periods_cannot_depend_on_the_host_timezone` |
| TC64-U14 | AND across criteria | Venue capacity120 with THEATRE and Projector; request attendance121 with both matching features | Compare requirements | Operational/layout/facilities pass; capacity fails; overall match false | `test_ac1_a_failed_capacity_check_is_not_overridden_by_other_matches` |

Common precondition: load the venue facts defined in `api/apps/venues/tests/test_matching.py`; each unit test constructs a fresh object and no database rows. Execution: from `api/`, run `.venv/bin/python -m pytest apps/venues/tests/test_matching.py --no-cov -q`. Actual latest result: 31 passed, Python 3.12.13, on 7 October 2026. The helper alone has 100% statement and branch coverage (46 statements, 20 branches); this is not coverage of the complete venue feature. JUnit and coverage evidence are retained in the project output directory `outputs/venue-commit-2026-10-07/`, outside this checkout. Agent execution is identified as agent execution; no human acceptance is recorded.

The 7 October pre-commit regression passed 207 backend cases (176 existing plus 31 helper cases) and 43 web cases. Backend lint/formatting, Django system and migration-drift checks, web type checking and the production build passed. The browser journey last passed earlier on 7 October during the full-repo audit; it was not rerun for this isolated, unwired helper change. Existing application defects identified in that audit remain outside this commit.

Shortlisting does not reserve a venue. Another coordinator's event and an organiser's draft must not be writable through the shortlist endpoint. Saved criteria must continue to identify mismatches when a venue's capacity, facilities or availability changes.

## Sources

- Jira SCRUM-64 and SCRUM-68, rechecked on 7 October 2026; both remain To Do.
- Week 4 Project Instructions: First Release, Deliverables 3 and 6, and Testing and traceability rubric.
- Week 7 Customer Changes, pages 1-2: buffer-aware availability and conflicts, preserve events after venue unavailability, multiple venues, expiring holds, Lead assignments and Safety Officer review. These requirements are not claimed complete by this foundation.
- Week 4 Test Cases & Software Architecture: slides 16, 21-24, 26-32 and 38-40. Use the case template and positive, negative and boundary cases.
- Week 6 Automated Testing #1; Continuous Integration: slides 21-22, 25-27, 37-46 and 54-57. Use FIRST, independently justified assertions, fault detection and the PR CI gate.
- Week 6 Lab - From Generated Tests to a CI Gate: pages 2-3. Seed plausible faults and distinguish coverage from assertions.
- Customer Meeting, live Google Doc read on 5 October 2026: venue/resource availability, coordinator responsibility and physical accessibility.
- IS212 Project FAQ, live Google Doc read on 5 October 2026: AI may execute tests; the team remains responsible for their correctness.

## Baseline findings to retain in the final report

The existing coverage setting measures `apps`, including test and migration code. Its near-100% percentages overstate coverage of the production code alone. The new verification must report its measurement scope and branch coverage rather than treat that number as proof.

The CI workflow tests backend and frontend changes on pull requests; it does not run the browser suite. Formal case specifications and execution records need to accompany the executable tests for assessment traceability.
