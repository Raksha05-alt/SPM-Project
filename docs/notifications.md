# Notification centre (SCRUM-79 / SCRUM-82, gate NOTIFY)

The existing `apps.notifications` inbox now has read state, an unread count, typed destinations and **one shared writer**. Every Sprint 4 producer calls that writer. There is no second inbox and no email: in-app delivery is the release-1 channel.

## The writer contract (for every producer)

```python
from apps.notifications.models import NotificationKind, NotificationTarget
from apps.notifications.services import notify, status_occurrence

notify(
    event=event,                       # the event the notice is about
    kind=NotificationKind.EVENT_CONFIRMED,
    occurrence=status_occurrence(event),   # a stable business occurrence, see below
    recipients=[organiser, *staff_ids],    # users, user ids or None; de-duplicated
    message='"Partner Summit" is confirmed. ...',  # public, recipient-appropriate text
    target_type=NotificationTarget.SAFETY_CHECK,   # optional, with target_id
    target_id=check.pk,
    skip=actor,                        # optional: leave out the person who acted
)
```

- **Call it inside your business transaction.** The notice commits or rolls back with the action. `test_w3` proves a later failure leaves no notice.
- **The occurrence comes from a persisted record**, so a retry produces the same key:

  | Occurrence | Source |
  | --- | --- |
  | `status_occurrence(event)` | The row `transition_event` just wrote (`event-status:<id>`) |
  | `f"assignment:{assignment.pk}"` | The assignment occurrence |
  | `f"clarification:{c.pk}"`, `f"clarification-note:{note.pk}"` | The clarification or note row |
  | `booking_occurrence(booking)` | `apps.venues.bookings`: the latest booking-history row |
  | `f"equipment-history:{entry.pk}"` / `plan_occurrence(event)` | The equipment history row the action wrote |
  | `f"safety-check:{check.pk}:requested"` and similar | The safety check |

  Never use a random or time-based key: a replay would then look new.
- **Uniqueness is recipient + kind + occurrence.** The stored key is `"<KIND>:<occurrence>"`, enforced by `unique_notice_per_recipient_occurrence`. Replaying an action never duplicates a notice. A *later* genuine occurrence of the same kind on the same event, such as a reallocation or a re-confirmation, notifies again. The older `unique_notification_per_kind` constraint (one Approved/Rejected notice per event) and `unique_assignment_notice_recipient` are kept.
- A missing or blank occurrence raises `MissingOccurrence`.
- Notices written before Sprint 4 keep `occurrence = ""` and are never back-filled with invented values.

All existing producers now use the writer: submission, assignment, decisions, clarifications, venue request/decision/withdrawal, equipment request/update/unavailable, confirmation, cancellation and Safety.

## SCRUM-79 recipients

| AC | Action | Recipients |
| --- | --- | --- |
| 1 | Organiser submits | Every **active Coordinator Lead** (kind `SUBMITTED`) |
| 1 | Lead assigns or reassigns | New coordinator, previous coordinator and the requester (`ASSIGNMENT`), once per assignment |
| 2 | Approve / reject / ask for clarification | Event Organiser, with the reason or question |
| 3 | Venue Staff approve / reject a booking | The event's current coordinator, or else the requester, with any reason |
| 4 | Coordinator confirms | Event Organiser, **plus the active Venue Staff who approved its bookings and the Technical Support who reserved its equipment or approved its current plan**. Uninvolved staff get nothing. |
| 5 | Every notice | Event id and name, kind label, message and `created_at` |

**AC1 interpretation (record with the PO before closing SCRUM-79).** The literal criterion says the *assigned coordinator* is notified on submission. Since Week 7 change 5 (implemented in SCRUM-89), submissions enter the unassigned Lead queue. So the Leads are notified on submission, and the coordinator is notified on assignment. Auto-assignment is not restored. No Jira text was changed.

## SCRUM-82 API

| Method and path | Behaviour |
| --- | --- |
| `GET /api/notifications/` | The signed-in user's own notices, newest first (`-created_at, -pk`). Fields: `id`, `event`, `event_name`, `kind`, `kind_label`, `message`, `created_at`, `read_at`, `is_read`, `destination`. Listing marks nothing read. |
| `GET /api/notifications/unread-count/` | `{"unread": n}` |
| `POST /api/notifications/<id>/read/` | Marks that one notice read and returns it with the new count. Idempotent: `read_at` keeps its first value. Another user's notice, or an unknown id, returns **404**. |

### Destinations are decided on every read

`destination` is computed from the recipient's **current** role and relationship to the event, mirroring each screen's own permission rule. A retained notice never grants access.

| Recipient now | Opens |
| --- | --- |
| Organiser of the event's organisation | `/organiser/requests/<event>` |
| The event's **currently assigned** coordinator | `/coordinator/events/<event>` |
| Coordinator Lead (event not a draft) | `/lead/events/<event>` |
| Safety Officer | `/safety/checks/<check>` when the notice targets an existing check of that event; otherwise `/safety` |
| Venue Staff | `/venues/requests` |
| Technical Support | `/equipment/plans/<event>` |
| Attendee, once the event is attendee-visible | `/events` |
| Anyone else: reassigned coordinator, changed role, another organisation, inactive account, internal staff on a draft | `null`. The UI keeps the notice and says the user no longer has access. |

## Web

`web/src/components/Notifications.tsx`:
- The header shows "*n* unread", taken from the count endpoint.
- Opening the panel lists notices and marks nothing.
- Selecting a notice marks only that one read and updates the count and list from the response, then navigates to its destination. With no destination, the user is told they no longer have access.

## Migration

`notifications/0015_notification_centre` adds:
- `occurrence`, `target_type`, `target_id` and `read_at`;
- the `SUBMITTED` kind;
- a partial unique constraint and a partial unread index.

Existing rows upgrade with a blank occurrence and are left unread. `kind` stays at `max_length=20`, and every kind fits.

## Test evidence (agent run, 3 November 2026 — not a teammate review)

Base: `origin/main` `9db1692`.

| Check | Result |
| --- | --- |
| `apps/notifications/tests/test_scrum_79_event_notifications.py` and `test_scrum_82_manage_notifications.py` | 38 passed. `services.py`, `views.py` and `serializers.py` have 100% statement and branch coverage. |
| Full backend suite (PostgreSQL 16) | 1327 passed; total coverage 99.62% |
| Seven existing tests adjusted | Four rollback tests now patch the writer's `bulk_create`. The withdrawal rollback test now has a Venue Staff recipient. Three confirmation tests count the organiser's notice, because AC4 adds the involved staff. |
| Web: lint, `vitest`, build | Clean; 294 tests passed |
| Playwright, all 12 journeys, `--workers=1 --retries=0` | 12 passed. `draft-submit-queue` updated for the new header and list labels. |
| Browser check through real actions | Organiser submits; the Lead sees 1 unread and opens it at `/lead/events/3` (count 0). The Lead assigns; the coordinator opens the assignment notice. The coordinator approves; the organiser sees 2 unread, opens the approval at `/organiser/requests/3` and is left with 1. After reassignment, the old coordinator's retained notice opens nothing and says why. |

Local note: the container's Chromium build differs from the one pinned by `@playwright/test` 1.49, so the journeys ran with a local, uncommitted config that sets `executablePath`. CI uses its own installed browser.

Still to do: a teammate correctness review, the PO acceptance record for the AC1 interpretation, and manual checks in the app with demo data.
