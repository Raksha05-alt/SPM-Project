# Sprint 1 notes

Everything here belongs in the sprint review, not in a drawer. Each item is
something the team decided and should be able to defend.

## Test coverage exception

The coverage gate is set to 80% and the suite currently reaches **99.8%**. Two
lines are not covered, both in `api/apps/events/views.py`:

```python
except InvalidTransition as exc:
    return Response({"detail": str(exc)}, status=409)
```

This branch cannot be reached over HTTP today. `submit` is only callable on a
draft, because `CanAccessEventRequest` refuses a write to anything that is not a
draft before the view body runs, and `DRAFT -> SUBMITTED` is always a legal
transition. The branch is kept deliberately: Sprint 2 gives coordinators write
actions on non-draft events, at which point it becomes reachable and a missing
409 would surface as a 500.

Everything else, including the defence-in-depth permission branches that an
earlier check normally shadows, is covered by unit tests in
`apps/events/tests/test_edge_cases.py`.

Raise the gate to 90% at the start of Sprint 2 and to 100% at the start of
Sprint 4.

## Scope boundary to flag at the review

**US-06.1 AC4** is implemented as a read-only Attendee event list. Attendees can
see Confirmed, Completed and Cancelled events, including the plain-language
status and its latest change date. Draft, Submitted, Awaiting Clarification,
Approved, Planning and Rejected events are filtered out by the API, not only by
the interface. Registration remains in EP-18 and is outside Sprint 1.

**US-04.1** delivers only the queue. Reviewing, approving and rejecting a
request are US-04.2 to US-04.4 and belong to Sprint 2, so a coordinator can read
a submitted request but cannot yet act on it. That refusal is explicit in
`CanAccessEventRequest`, not an accident.

## Open questions for the customer

Carried forward from the backlog; none of these were answered before Sprint 1
closed, so the implementation took the least surprising option and is easy to
change.

1. Can an Event Organiser delete a draft, or must it be retained for audit?
   **Assumed:** deletion is allowed for drafts only.
2. Can everyone in a client organisation see each other's drafts, or only the
   person who created one? **Assumed:** organisation-wide visibility.
3. Which fields count as a significant change to a confirmed event? Needed
   before US-07.2 in Sprint 2.
4. Should venue search account for setup and turnaround time? Needed before
   EP-10 and EP-14 in Sprint 3.

## Decisions worth repeating in the Week 13 Q&A

- **Mandatory fields are enforced at submission, not at save.** US-03.1 AC2
  requires an incomplete draft to save. So model fields are nullable and
  `EventRequest.missing_mandatory_fields()` is the single place the submission
  rule lives. The same method feeds the API response, so the client never has to
  duplicate the rule.
- **The status machine is in `core`, the history rows are in `events`.** Venue
  bookings and equipment reservations will need the same transition logic in
  later sprints, but their history belongs with them.
- **Cross-organisation access returns 403 and writes an audit row**, rather than
  a 404. US-01.2 AC4 requires the refused attempt to be recorded, which a silent
  404 from a filtered queryset would not do.
- **The API decides where each role lands after sign-in** (`landing_path`), not
  the React router. One place to change when EP-18 adds an attendee dashboard.
