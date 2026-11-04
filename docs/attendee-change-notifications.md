# Attendee change notifications (SCRUM-18, gate ATTENDEE)

Registered attendees are told when a confirmed event they registered for is cancelled now, and when its date, time or venue changes once DISRUPTION (SCRUM-86) and APPLY (SCRUM-80) apply such changes. Notices go through the SCRUM-79 writer, so they are in-app, recipient-only, de-duplicated by occurrence and saved in the action's transaction.

## Who is notified (AC3/AC4)

`registered_attendees(event)` in `api/apps/events/impact.py` returns the active attendees whose registration for that event is **Registered** (SCRUM-21). These never receive a registered-attendee notice:
- an attendee who **withdrew** (SCRUM-14);
- an attendee who is only on the **waiting list** (SCRUM-19);
- anyone registered for another event;
- a deactivated account.

## What they are told (AC2)

`describe_for_attendees(event)` builds the event's current public details: the date and time (Singapore time), and each approved room with its location and period. It reads the same public projection as confirmed arrangements and the attendee views (`confirmed_venues`), and names the session when there are several. It never includes staff notes, decision reasons, capacities or Safety facts (`test_c3`).

## Producers

| Action | Call | Kind | Occurrence |
| --- | --- | --- | --- |
| Event cancelled: `cancel_event` (SCRUM-77), **wired now** | `notify_attendees_of_cancellation(event, occurrence=status_occurrence(event))` | `EVENT_CANCELLED` | The cancellation's status-history row |
| Confirmed event's date, time or venue changed: **DISRUPTION / APPLY call this** | `notify_attendees_of_change(event, changed=[...], occurrence=...)` | `EVENT_CHANGED` | A persisted record of the applied change, such as the change request or booking-history row |

- `changed` must be a non-empty subset of `date`, `time` and `venue`; anything else raises `ValueError` and sends nothing.
- Call both functions **inside** the action's transaction, after the change is saved, so the message describes the new state. A notice failure rolls the whole action back (`test_ac5e`).
- The cancellation notice names the event and its date. It deliberately leaves out the coordinator's cancellation reason, which is an internal note (`test_ac5b`).
- In the notification centre, the notice opens the attendee's events page (SCRUM-82 destination rules).

## Closure (guide section 5)

No action yet applies a date, time or venue change to a confirmed event: a confirmed event is not editable directly, and SCRUM-70 publishes only a preview and review writer. So AC1 and AC2 are covered here through the published callback with real persisted events and registrations (`c` cases). AC5 is covered end to end through the real cancellation endpoint. SCRUM-18 closes after DISRUPTION and APPLY call `notify_attendees_of_change` from their real actions; Jerom then verifies an actual change reaches only active registrants.

## Migration

`notifications/0020_event_changed_kind` adds `EVENT_CHANGED` to `Notification.kind` (choices only; `max_length` 20). It follows main's `0019_waitlist_kinds`. The open holds PR (#36) adds its own `notifications/0019_venue_hold_lifecycle`, so whichever of the two merges second needs a merge migration joining the leaves (no operations).

## Test evidence (agent run, 4 November 2026 — not a teammate review)

| Check | Result |
| --- | --- |
| `apps/events/tests/test_scrum_18_attendee_change_notices.py` | 20 passed (18 functions; `c6` parameterised). The SCRUM-18 section of `impact.py` has 100% statement and branch coverage. |
| Full backend suite (PostgreSQL 16) | 1671 passed; total coverage 99.54% |
| Playwright, all 15 journeys, `--workers=1 --retries=0` | 15 passed |
| Browser check through real actions | Event confirmed through the real services. The organiser opened registration; the demo attendee registered, and a second attendee registered and then withdrew. The coordinator cancelled through the API. The attendee saw "Regional Partner Conference (Thu 17 Dec 2026, 09:00 to 15:00), which you registered for, has been cancelled" without the internal reason, and opening it went to `/events`. The withdrawn attendee received nothing. |

Still to do: a teammate correctness review, the real change path after DISRUPTION and APPLY, and a manual check with demo data.
