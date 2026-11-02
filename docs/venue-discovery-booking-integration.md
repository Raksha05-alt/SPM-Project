# G12: venue discovery with booking occupancy

Owner: Nethren. Branch: `feature/venue-discovery-booking-checks`.
Base: green main `65829a71622d8059a05bc303b13654939a6d317d`, including G08 occupancy, G10 decisions and G11 withdrawal. Work and verification date: 1 November 2026, Singapore time.

This implements INT-01 from the Sprint 3 guide and the deferred booking checks for SCRUM-64/68. It addresses an original integration gap. The existing Jira stories retain their descriptions/status/history.

## Behaviour and contract

- Search, the venue calendar and saved shortlists read the existing shared occupancy service. Approved venue bookings obstruct overlapping periods. Pending, rejected, withdrawn and cancelled-event records do not. Half-open intervals permit one booking to end when the next starts.
- A successful period check returns `availability_status: AVAILABLE`. A known obstruction returns `UNAVAILABLE`; missing dates retain `UNVERIFIED`. Availability describes the supplied period and recorded resources, not a reservation or final event confirmation.
- An obstructed saved venue stays in its shortlist with the conflict reference and unmet criteria. Withdrawal removes that obstruction on a fresh read without changing the entry or its saved filters. Independent date blocks continue to apply.
- Search/shortlist responses publish `availability_integrated`, `booking_occupancy_integrated` and `date_blocks_integrated` as true. `holds_integrated` remains false for the later hold feature. A missing period never becomes checked just because the capability exists.
- The page refreshes search and shortlist data on returning focus, through **Refresh availability**, and after shortlist mutations. Submitting the same search checks both views again. Staff decisions invalidate discovery/shortlist/calendar caches, including uncertain responses where the server may have acted.
- Search results do not reserve a room. The existing locked request and approval actions recheck suitability and occupancy. Stale searches and client-supplied booking-exclusion IDs cannot bypass those checks or add an occupied candidate with a saved period.
- Existing role/assignment restrictions continue to apply. Conflict references expose IDs/periods; they do not grant access to another client's event name, description or detail endpoint.

No database migration or package/lockfile change is needed. The backend retains its bulk occupancy prefetch and the original constant-query regression cases.

## Design

The existing Venue component owns discovery, suitability and booking occupancy; the SPA and Django containers stay the same. Read paths use the common `occupying_bookings`/`availability` services rather than a separate conflict calculation.

```mermaid
sequenceDiagram
    participant Staff as Venue Staff
    participant Booking as Booking actions
    participant DB as PostgreSQL
    participant Coordinator as Coordinator
    participant Discovery as Discovery and shortlist
    Staff->>Booking: Approve pending request
    Booking->>DB: Lock, recheck and persist Approved
    Coordinator->>Discovery: Refresh saved venue
    Discovery->>DB: Read approved occupancy and blocks
    Discovery-->>Coordinator: Retain entry; show conflict
    Coordinator->>Booking: Confirm withdrawal
    Booking->>DB: Retain history and persist Withdrawn
    Coordinator->>Discovery: Refresh
    Discovery->>DB: Read current occupancy and blocks
    Discovery-->>Coordinator: Available if remaining checks pass
```

## Sources and phase boundaries

Checked live Jira SCRUM-64/68 and the registered Drive PROJECT folder, the local source index and Sprint 3 guide (G12/INT-01/J2). Week 4 Project Instructions requires coherent venue-request/booking workflows. Week 4 G3 clarification `Sheet1!C39:D39` distinguishes approved occupancy from pending requests. The later Lead model controls event visibility; this integration preserves the implemented assignment guards. Week 7/9 hold changes remain in their later phase. Slack access was unavailable.

Cancellation-read compatibility uses the existing `transition_event` service and verifies that a cancelled record stops occupying the period without deleting booking history. It does not implement or demonstrate the coordinator cancellation/resource-release API. G16b must rerun that compatibility through the real combined cancellation action. Full Safety request/decision/confirmation journeys remain G20/G21.

## Verification

- Initial new-case run: seven failures exposed the stale capability/status results; four existing booking/permission checks already passed. The implemented G12 plus original search/shortlist selection then passed **88 cases**.
- Full backend regression: **911 passed**, PostgreSQL; lint, formatting, Django migration consistency and fresh migration/seed checks passed.
- Backend discovery scope (`discovery.py`, `discovery_views.py`, `discovery_serializers.py`): **175/175 statements and 30/30 branch arcs**, with no coverage exclusions in that scope.
- Frontend: **172 tests passed**. V8 measured **100% statements, branches, functions and lines** for `VenueDiscovery.tsx` and `BookingDecision.tsx`. The existing local coverage provider required no dependency change. TypeScript/production build passed.
- Real browser regression: **nine passed**, no skips, retries or API mocks. The G12 case saves a venue, submits/approves a real booking through the APIs, refreshes the open discovery page, withdraws, refreshes again, reloads, and checks independent blocks/venue status. J2 separately covers the booking forms and approval/withdrawal UI.
- Boundary cases include exact adjacency and one-second overlap, rejected/pending requests, stale additions, forged exclusion IDs, private cross-client details, preserved filters and missing dates. UI cases cover focus/manual refresh, grouped errors, network/empty responses, cache invalidation and changed/cleared filters.

Individual new/extended case records: `test-cases/G12-venue-discovery-bookings.csv`. Raw execution logs, JUnit/browser reports and coverage files belong under the project output folder `outputs/venue-discovery-booking-integration-2026-11-01/`. The source fingerprint below binds the application/test files; documentation is outside that scope.

Source fingerprint: `c10920daf25ec5abed938fc1a1e5a09ce0670e7d78ccd61a2b1f011c77b4dac7`.

The AI assistant inspected/executed these checks for Nethren. Team correctness review, the team's own browser check and PO acceptance remain unrecorded. Passing execution and coverage do not establish those reviews.
