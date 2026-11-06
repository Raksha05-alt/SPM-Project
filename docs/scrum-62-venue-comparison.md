# SCRUM-62: compare venue availability

Branch: `feature/venue-availability-comparison` (G19 in the Sprint 3 guide).

Open **Venue availability**, then use **Compare availability across venues**.
Enter a start and end in Singapore time. Every venue is listed, with a text
status and green, amber or red styling. Free segments account for opening hours,
service status, recorded blocks and approved bookings. Refresh comparison rereads
current data; returning focus also refetches through TanStack Query.

`GET /api/venues/compare-availability/?starts_at=...&ends_at=...` uses the existing
calendar permissions: Coordinator and Venue Staff only. Responses expose generic
obstruction reasons and free segments, without other events' identities or private
block notes. Pending requests do not reserve a venue. Holds and buffers remain
Sprint 4 work. Existing single-venue and available-only endpoints are preserved.

## Acceptance case specifications

Executable backend selectors are in
`api/apps/venues/tests/test_scrum_62_compare_availability.py`.

| Case | Preconditions/action | Expected outcome | Selector |
| --- | --- | --- | --- |
| S3-SCRUM-62-01 / AC1 | Compare rooms with overlapping 10:00–10:45 and 10:30–11:00 blocks over 09:00–13:00; add a free room | Every room retained; free room available for whole period | `test_ac1_ac2_ac3_union_segments_and_all_statuses` |
| S3-SCRUM-62-02 / AC2 | Same partial room and another blocked over 09:00–13:00 | Partial room free 09:00–10:00 and 11:00–13:00; fully blocked room has no free segments | same selector |
| S3-SCRUM-62-03 / AC3 | Compare before adding free room; also compare empty catalogue | Explicit no-whole-period-availability message | same selector; `test_invalid_empty_and_operating_hours` |
| S3-SCRUM-62-04 / AC4 | Organiser, attendee and technical staff call endpoint; coordinator reads occupied room | Forbidden roles receive 403; permitted response contains no event/booking IDs or private block notes | `test_ac4_forbidden`; other comparison cases |
| S3-SCRUM-62-05 / freshness | Request and approve booking through HTTP; compare; withdraw with explicit release confirmation; compare again | Pending does not occupy; approved occupies; adjacency stays free; withdrawal restores full availability | `test_ac1_ac4_ac5_real_approval_and_withdrawal` |
| S3-SCRUM-62-06 / validation | Missing/reversed dates; 07:00–09:00 at room opening 08:00; out-of-service room | 400; partial with 08:00–09:00 free; unavailable | `test_invalid_empty_and_operating_hours` |

Frontend selector: `web/src/pages/VenueComparison.test.tsx` verifies statuses,
segments, no-match message, Singapore request timestamps and refreshed results.

Specification and agent execution: 2 November 2026, uncommitted working tree.
Focused backend suite: 6 passed. Frontend comparison and existing availability:
8 passed. Production frontend build and changed-Python Ruff checks passed.
Coverage is unmeasured. Human correctness review, manual demo-data walkthrough,
PR review, CI and PO acceptance remain pending; no completion of those steps is claimed.
