# SCRUM-85: venue setup and turnaround

Branch: `feature/venue-setup-turnaround`, based on `origin/main` at `9db1692`.
No commits or pushes were made during implementation.

Venue Staff can set nonnegative whole-minute `setup_minutes` and
`turnaround_minutes` in the existing venue form. Both default to zero, preserving
existing booking behaviour. Migration `venues.0008` adds these fields without
rewriting booking rows or decisions.

`apps/venues/occupancy.py:effective_interval` defines half-open occupancy:
`[start - setup_minutes, end + turnaround_minutes)`. Both the existing and
proposed booking are expanded. Booking approvals, availability, discovery,
shortlist reassessment, comparison and Safety readiness consume these rules.
Equipment services continue using actual event times.

Booking responses include `buffer_review`: effective occupied times, fresh
conflict references and warnings. Staff see the occupied period and warnings in
the booking inbox. Existing bookings retain their status and history when a
buffer edit introduces a clash. Readiness refuses unresolved clashes.

Buffer edits lock event rows in ID order before locking the venue, recheck
booking membership, and invalidate future approved bookings' Safety assessments
through the existing transactional `arrangements_changed` service. A confirmed
event returns to Planning for fresh review. Failures roll back the venue edit.

Advertised event hours remain hard suitability constraints. If only buffers
extend outside operating hours, suitability and staff review show a warning;
staff may still approve.

Automated acceptance cases are in
`api/apps/venues/tests/test_cr_01_setup_turnaround.py`: zero/default values,
09:30-12:45 occupancy, 13:15 adjacency versus 13:14 conflict, direct/prefetched
reads, approval refusal, preserved/flagged bookings, input validation, warning-only
hours, search/shortlist/comparison consistency, permissions and rollback.
Frontend cases verify saved minute values and approval despite a buffer warning.

Local application database migrations were inspected but not applied; it also
has earlier Safety migrations pending. Run the normal `python manage.py migrate`
from `api` before using the feature locally. Test databases apply migrations.

Manual browser walkthrough, human correctness review, complete story-owned branch
coverage and PO acceptance remain pending. Automated passes do not establish those.

Verification executed on 3 November 2026:
- Existing venue regression run: 512 passed (PostgreSQL).
- SCRUM-85 acceptance suite: 17 passed (PostgreSQL).
- Combined SCRUM-85, Safety and equipment availability regression: 151 passed.
- Affected frontend component/page tests: 42 passed.
- Production frontend build, Django system check, Ruff lint/format,
  missing-migration check and Git whitespace check passed.
