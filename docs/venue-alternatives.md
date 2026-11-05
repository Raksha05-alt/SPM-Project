# Venue alternatives

US-73 in the imported board corresponds to SCRUM-73 in Git history.

Venue Staff can include another venue, another period, or both when rejecting a pending request. The existing reason, deciding staff member, time and status history remain on the original request. A suggestion occupies no room.

The rejection form checks the proposed venue against the shared suitability and buffered availability rules. A booked, live-held, blocked or out-of-service suggestion returns a warning before the rejection or notice is saved. Staff can choose another alternative or remove the suggestion and send the rejection alone.

The assigned coordinator sees the proposal beside the rejection reason. Accepting it calls the normal booking-request service with the proposed venue and period, the same session, inherited requirements and any original replacement link. It creates a Pending request and notifies Venue Staff. Acceptance rechecks assignment, session, event state, suitability and current availability under the shared event and venue locks.

An existing accepted request makes a retry return that request. A new request for the same session, an elapsed suggested period, a closed event or a removed session prevents a stale acceptance. The original rejection retains the accepted request reference.

## API

- POST `/api/venue-bookings/<id>/reject/` accepts `reason` and optional `suggestion`.
- The suggestion may contain `venue`, both `starts_at` and `ends_at`, or all three. Omitted values use the original booking. At least one value must change.
- Booking responses include nullable `suggestion` with `venue`, `venue_name`, `starts_at`, `ends_at` and nullable accepted `booking`.
- POST `/api/venue-bookings/<id>/accept-suggestion/` returns the new or previously created request.
- Venue migration 0013 adds the typed proposal and accepted-request link. Existing rows receive null values and keep their current behavior.

## Evidence

The case records in `docs/test-cases/S4-SCRUM-73-venue-alternatives.csv` map the four acceptance criteria and validation cases to executable tests. The real browser journey covers a blocked proposal warning, rejection with a usable alternative, the coordinator's view and acceptance into a new Pending request. Team review and the team's own browser check remain to be recorded.
