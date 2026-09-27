# SCRUM-1 (US-01.2) — Access restricted by role and relationship to an event

Decisions worth being able to defend in the Week 13 Q&A. Each one was a choice
with a real alternative, not an accident.

## Where the rules live

| Rule | File |
|---|---|
| Is this role allowed on this endpoint at all? | `api/apps/core/permissions.py` → `HasAnyRole` |
| Is this internal-only information? | `api/apps/core/permissions.py` → `IsInternalStaff` |
| Is this caller allowed on *this particular event*? | `api/apps/events/permissions.py` → `CanAccessEventRequest` |
| What the caller's own list may contain | `api/apps/events/views.py` → `get_queryset` |
| The UI mirror of the same rules | `web/src/auth/RequireRole.tsx` |

Access control is expressed as DRF permission classes, never as `if` statements
inside view bodies. A rule written inside one view protects one view; a
permission class protects every view that lists it, and can be tested on its own.

## Four decisions

**1. A cross-organisation attempt returns 403 and is recorded, not 404.**

The tempting alternative is to filter the queryset so the row simply is not
found. That yields a 404 and leaks nothing, which is marginally better for
secrecy. We chose 403 because AC4 requires the *attempt* to be recorded, and a
silent 404 from a filtered queryset gives us nothing to record. `get_object()`
therefore looks the row up across all rows and then asks the permission class,
so the refusal is a real decision we can log. Secrecy is preserved a different
way — see decision 2.

**2. A refusal returns only `detail`, never a fragment of the record.**

AC3 says "refused rather than partially rendered". The test
`test_ac3_a_refusal_returns_no_part_of_the_protected_record` asserts that the
403 body contains neither the event name nor its attendance, and that `detail`
is the only key. This is what stops decision 1 from leaking anything.

**3. `HasAnyRole` is listed before `IsAuthenticated`, on purpose.**

DRF stops at the first permission class that returns `False`. With
`IsAuthenticated` first, an anonymous request was refused before any class had a
chance to write an audit row — so unauthenticated probes, the ones most worth
knowing about, left no trace at all. `HasAnyRole` now handles the
unauthenticated case itself and records it. `IsAuthenticated` stays in the list
after it as defence in depth.

If anyone reorders that list, `test_ac4_an_anonymous_attempt_is_also_recorded`
fails. That is deliberate.

**4. Auditing is best-effort and can never turn a 403 into a 500.**

By the time we write an audit row, the security decision has already been made.
A failure to record it must not change what the caller sees. `audit.record()`
catches every exception, logs it, and returns `None`. The write runs inside its
own savepoint (`transaction.atomic()`) so that a failed audit write cannot
poison an enclosing transaction and roll back the caller's own work.

Both properties are tested:
`test_ac4_auditing_never_turns_a_refusal_into_a_server_error` and
`test_a_failed_audit_write_does_not_poison_the_callers_transaction`.

## The audit endpoint

`GET /api/audit/` — internal staff only, read-only, paginated.
Query parameters: `refused_only=true`, `actor=<id>`, `page`, `page_size`.

This goes slightly beyond the literal wording of AC4, which asks only that the
attempt be *recorded*. We added it because a record nobody can read is weak
evidence, and because the endpoint is itself internal planning information —
which makes AC2 demonstrable today rather than waiting for venue bookings in
Sprint 3. An Attendee or an Event Organiser asking for it gets a 403, and that
refusal is itself recorded.

It is deliberately read-only. `POST` and `DELETE` return 405. An audit row that
can be edited through the API is not evidence of anything.

**If the Product Owner disagrees that this belongs in SCRUM-1**, it is
self-contained: `apps/core/urls.py`, `apps/core/serializers.py`, the
`AuditLogListView` in `apps/core/views.py`, and the tests naming `/api/audit/`.

## Open question for the customer

Who inside ConnectSphere should be able to read the audit log? It is currently
open to all internal staff — coordinators, venue staff and technical support.
An operations-manager or administrator role would be narrower, but the briefing
names no such role, so inventing one felt worse than being slightly broad. Worth
asking at the next Q&A.

## What this story does not cover

- **Rate limiting.** Nothing throttles repeated refused attempts. Out of scope
  for the release, but worth naming if an instructor asks how you would detect a
  deliberate probe rather than a mistake.
- **Internal fields on the event record itself.** Today an Event Organiser sees
  their own event in full, which is correct. When Sprint 3 adds venue booking
  decisions and coordinator notes to that record, AC2 will need field-level
  filtering in `EventRequestSerializer`, not just endpoint-level refusal. Raise
  this in Sprint 3 planning before EP-12 and EP-13 are built.
