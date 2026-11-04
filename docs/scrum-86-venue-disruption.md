# SCRUM-86: venue disruption and replacement

Branch: `feature/venue-disruption-replacement`, based on fetched `origin/main` at `9f954c1`.

Venue Staff use the existing venue availability page to record a reason category,
reason and unavailable period. Creating or extending a block marks overlapping,
future Approved bookings and live Held bookings Disrupted. Overlap includes the
venue's setup and turnaround buffers and uses half-open intervals. Pending,
expired, past and terminal-event bookings are not changed.

The block, snapshots, booking history, Safety invalidation, return to Planning
and persisted notices share a transaction. Event rows are locked in ID order
before the venue. Booking membership is rechecked after the venue lock; a
concurrent addition causes a bounded transaction retry. Staff can filter the
booking inbox by Disrupted and see affected bookings on the block. Coordinators
see affected-booking identities only for their assigned events.

Original event details, session identity, booking requirements and staff decisions
are retained. Organisers see the original disrupted venue and period on the event
page, without internal block notes. Removing or shrinking a block never restores
approval. Existing registrations are preserved; the normal Planning registration
guard applies. Active registrants receive public change notices; withdrawn and
waitlisted people are excluded by the existing notification service.

A coordinator's replacement is a new Pending request linked by `replaces` to the
Disrupted booking in the same session. The venue planner supplies this link
without requiring the coordinator to select an optional checkbox. All normal
assignment, suitability, current availability and staff-decision checks apply.
A linked Held replacement is not sufficient: it must become Approved. Unresolved
disruptions appear in the existing readiness/confirmation gaps, including their
booking IDs. An approved linked replacement resolves the gap without overwriting
the original. Fresh Safety approval is required before reconfirmation.

Migration `venues.0012` adds reason categories (legacy records default to Other)
and the Disrupted booking/history choice; it does not remove existing data.
Run `python manage.py migrate` when installing the change. Development database
migrations are not applied automatically by this implementation work.

Verification selectors:

- `apps/venues/tests/test_cr_02_venue_unavailable.py`: categories, approval/hold
  disruptions, multiple events, unrelated sessions, immutable original, linked
  replacement, half-open bounds, permissions, history/notice rollback, and an
  actual PostgreSQL block/approval race.
- `apps/events/tests/test_scrum_18_attendee_change_notices.py::test_scrum_86_real_disruption_replacement_and_fresh_safety`:
  real confirmation, registration, disruption, recipient exclusions, refusal,
  replacement, fresh Safety and reconfirmation.
- `web/src/pages/VenueAvailability.test.tsx` and
  `web/src/components/venues/VenueSessions.test.tsx`: staff reason selection,
  affected bookings and automatic replacement linkage.

Automated tests do not constitute a human browser walkthrough, teammate review,
PO acceptance or proof of 100% story-owned coverage. No Jira changes, commits,
pushes or PR actions are part of this work.

Verification on 4 November 2026:

- Final focused PostgreSQL run: 17 passed, including the race, real full workflow
  and corrected discovery regression.
- Broader venue/Safety/attendee run: 705 passed; one old withdrawal-after-block
  expectation failed. That expectation was updated for Disrupted and passed in
  the final focused run. The entire broad suite was not repeated afterward.
- Full frontend suite: 366 passed; the additional organiser-history case then
  passed with its six-test file (367 unique frontend cases verified overall).
- Production build, Ruff lint/format, Django checks, migration consistency and
  Git whitespace checks passed.
- The local development database still has pending main-branch migrations in
  addition to this feature migration. Its data/schema were not changed; apply
  the repository migrations before starting the updated app.
