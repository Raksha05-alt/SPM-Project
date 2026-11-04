# Re-check venue suitability after event changes (SCRUM-66, gate SUITABILITY)

When an event's requirements change, every **approved** venue booking the change touches is re-checked with the SCRUM-71 suitability rules. If the venue no longer suits the event, the booking is flagged for review and the coordinator is notified. The booking itself is never changed or released.

## What triggers a re-check (AC4)

| Changed field | Bookings re-checked (AC5, SCRUM-87 contract) |
| --- | --- |
| `expected_attendance` | The **main programme** only. A breakout keeps its own booked attendance. |
| `required_layout` | The main programme only. A breakout keeps its own layout. |
| `accessibility_needs` | **Every** approved booking, because the needs apply to the whole event |
| Anything else (name, purpose, description, equipment notes, registration, dates) | None. No review and no notice. |

Pending requests are not re-checked here; Venue Staff's approval re-runs suitability anyway (SCRUM-72). Date and time changes belong to the conflict re-check (SCRUM-70).

**Accessibility rule.** Accessibility needs are free text. Newly stated needs are treated as requiring step-free access, so a venue whose wheelchair access is recorded as *No* or *not recorded* is flagged with SCRUM-71's wording. A venue with confirmed access is not flagged, because the text can't be judged further. An open accessibility flag stays open through later unrelated changes until the needs or the venue change.

## Service contract: `api/apps/events/impact.py`

```python
impact_of(event, proposed, *, changed=None) -> list[BookingImpact]   # read-only
record_reviews(event, impacts, actor, *, source=ChangeSource.EVENT_EDIT)  # in the action's transaction
booking_attendance(booking, event_attendance)  # main follows the event; breakout keeps its own
unsuitable(booking, requirements)              # SCRUM-71 reasons for the booked venue
```

- `impact_of` writes nothing. **SCRUM-78 (ASSESS)** can pass a change request's `proposed_values` to preview suitability, and **SCRUM-80 (APPLY)** calls `record_reviews` with its own `ChangeSource` once the change is applied.
- `record_reviews` works as follows:
  - **Newly unsuitable:** opens a `VenueReview` with the reasons and notifies the coordinator (`VENUE_REVIEW`, occurrence `venue-review:<id>`, linked to the booking).
  - **Same reasons again (a replay):** nothing new.
  - **Different reasons:** resolves the old review as "Replaced by a newer review." and opens a new one.
  - **Suitable again:** resolves the open review as "A later change means the venue suits the event again."
- **Edit hook:** `record_event_edit` (the SCRUM-61 PATCH path) calls `recheck_after_edit` in the same transaction. A notice or review failure rolls the edit back (`test_l4`).
- **Booking leaves Approved:** a `post_save` signal on `VenueBookingHistory` resolves the open review (for example "The booking was withdrawn."), in the booking action's transaction. The booking actions themselves are not edited.

## Model: `events.VenueReview`

Holds the event, booking, `reasons` (requirement and message, as SCRUM-71 words them), `changed_fields`, `source`, `raised_by`/`raised_at`, and `resolved_at`/`resolved_by`/`resolution`. There is at most one open review per booking (partial unique constraint). Reviews are resolved, never deleted.

## Where the reason is visible (AC3)

- **Coordinator event page:** an amber "Venue needs review" panel lists each flagged venue, its reasons, which requirement changed, who changed it and when. It refreshes after an edit, along with readiness and notifications.
- **`GET /api/events/<id>/venue-reviews/`:** returns `{open, history}`. The assigned coordinator, Leads and Venue Staff can read it; Organisers, Attendees, Technical Support, Safety Officers and other coordinators are refused and audited.
- **Arrangement gaps:** an open review adds "Venue: *X* needs review after the event changed. *reason*". That blocks a Safety request and confirmation, and appears in readiness. Once SESSIONS is on main, its readiness rule also marks the venue item not ready.
- **Notification:** opens the coordinator's event page (SCRUM-82 destination rules).

## Migrations

`events/0014_venue_suitability_review` (model) and `notifications/0018_venue_suitability_review` (the `VENUE_REVIEW` kind). Neither touches `venues`, so they don't collide with SESSIONS' `venues/0009`.

## Dependency on SESSIONS (PR #32) and AC5

SCRUM-66 depends on gates INTAKE (merged) and SESSIONS (PR #32, open). This branch is built on main `ef91b36`, where every booking is the main programme; `is_main` reads the session kind once it exists. AC1–AC4 are tested here.

AC5's six cases (`scrum-66-ac5-tests.patch`) need SESSIONS' real `EventSession` model and session booking endpoints, so they are committed only after PR #32 is merged and main is merged into this branch. Per the guide, a teammate's unmerged branch is not merged into this one.

**Trial verification (not pushed):** in a scratch worktree, PR #32's head `23a29d7` was merged with this branch:
- All 42 SCRUM-66 cases passed, including AC5. `impact.py` had 100% statement and branch coverage.
- 223 passed across SESSIONS' `test_cr_03_multiple_venues.py`, the confirmation and edit flows, Safety and notifications.
- The merge was clean.

Section 5 of the guide also requires the real APPLY path (SCRUM-80) to show review reasons before SCRUM-66 closes. That is checked after APPLY.

## Test evidence (agent run, 4 November 2026 — not a teammate review)

| Check | Result |
| --- | --- |
| `apps/events/tests/test_scrum_66_recheck_suitability.py` (AC1–AC4, lifecycle) | 36 passed. `impact_views.py` and `signals.py` 100%; `impact.py` 100% except line 147, the breakout branch, which AC5 covers after SESSIONS. |
| Full backend suite, PostgreSQL 16 | 1534 passed; total coverage 99.61% |
| Web: lint, vitest with CI coverage, build | Clean; 334 passed; `VenueReviews.tsx` and `venueReviews.ts` 100% |
| Playwright, all 13 journeys, `--workers=1 --retries=0` | 13 passed |
| Browser check through real actions | Venue requested and approved through the API. The coordinator raised attendance to 250 in the edit form; the panel showed "Expected attendance of 250 exceeds the venue's maximum capacity of 200", and readiness and the notification showed the same reason. Lowering attendance to 190 removed the panel and resolved the review. |

## Integration with SESSIONS on main

On 4 November, the integration branch combined Jerom's published commits with main `69a2ca8`. The committed AC5 test approved a main venue and a 30-seat breakout through the real booking services, then used the event edit endpoint to verify that attendance 201 flags only the 200-seat main venue and preserves the breakout. A second regression confirmed that clearing an event-level accessibility need resolves its review when the booking itself has no such requirement.

Codex ran 166 backend tests across SCRUM-66, SCRUM-87 and Safety on PostgreSQL. The original six trial cases above describe Jerom's unpublished patch. The committed integration cases are recorded in the case inventory.

The SCRUM-80 APPLY integration check and the team's manual verification remain pending.
