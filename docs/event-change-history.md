# Event change history (SCRUM-60, gate HISTORY)

SCRUM-60 adds an **append-only before/after ledger** of changes to an event's details, and a scoped, read-only internal viewer. The SCRUM-61 edit path recorded only *which* fields changed, in the best-effort access log. It now also writes this ledger, in the same transaction as the edit.

## Model: `apps.events.models.EventFieldChange`

| Field | Meaning |
| --- | --- |
| `event` | The event that changed |
| `field` | The model field name (`name`, `expected_attendance`, `preferred_start`, ...) |
| `before`, `after` | JSON values. Datetimes are stored as ISO 8601 instants. |
| `values_recorded` | `False` only for entries imported from earlier audit records (see below) |
| `actor` | The user who made the change |
| `source` | The operation: `EVENT_EDIT` now, plus later sources such as change requests and resource reviews |
| `changed_at` | One timestamp per operation, shared by every field that operation changed |

**Append-only.** `save()` on an existing entry, `delete()`, `QuerySet.update()` and `QuerySet.delete()` all raise `AppendOnlyError`. The API has no write route.

## Writer contract (for SCRUM-20/80 and resource reviews)

```python
from apps.events.history import record_field_changes
from apps.events.models import ChangeSource

record_field_changes(event=event, before=before_dict, after=after_dict,
                     actor=user, source=ChangeSource.EVENT_EDIT)
```

- Call it **inside the business transaction**. It is mandatory history: if it fails, the action fails and rolls back (`test_ac1d`). `core.audit.record()` stays best-effort access logging and is not a substitute.
- It compares only keys present in both dicts and writes one entry per changed field. A no-op writes nothing.
- A later producer adds its own `ChangeSource` value; it does not reuse `EVENT_EDIT`.

The existing hook is `record_event_edit(event, before, user)` in `apps/events/services.py`. It is called by the event PATCH view under the event row lock, and now calls the writer with `snapshot_for_edit` before and after.

## API

`GET /api/events/<id>/change-history/` returns `{"event": id, "changes": [...]}`, newest first (`-changed_at, -pk`). Each entry has:
- `field` and `field_label`;
- raw `before`/`after` values;
- readable `before_display`/`after_display`: Singapore-time dates, catalogue layout names, Yes/No, and "Not set" for blanks;
- `values_recorded`, `actor_name`, `source`, `source_label` and `changed_at`.

| Caller | Result |
| --- | --- |
| The event's assigned coordinator, or any Coordinator Lead | 200 |
| Event Organiser, Attendee, Venue Staff, Technical Support, Safety Officer | 403, audited by `HasAnyRole` |
| Another coordinator, or any user for a draft | 403, audited with the reason |
| `POST`/`PUT`/`PATCH`/`DELETE` | 405 for permitted roles (403 for others), audited as "change history is append-only" |

Organisers keep seeing their own requests and lifecycle history; this internal field-diff history stays internal, as the guide requires.

## Earlier edits: never invented

Migration `events/0012_import_earlier_edits` reads the SCRUM-61 audit rows ("Event *id* edited", detail "Changed: a, b"). It creates one entry per named field with `values_recorded=False`, source `LEGACY_AUDIT`, and the original actor and time. The UI shows these values as *Not recorded*. Refused audit rows, events that no longer exist and other actions are skipped. Reversing the migration removes only the imported entries.

## Web

`web/src/components/ChangeHistory.tsx` appears on the coordinator event page (assigned coordinator) and the Lead event page. It is a read-only table of when, field, before, after and by. Saving an edit in `CoordinatorEventEditor` refreshes it; a fault check showed the test fails without that refresh.

## Test evidence (agent run, 3 November 2026 — not a teammate review)

Base: `origin/main` `9db1692`.

| Check | Result |
| --- | --- |
| `apps/events/tests/test_scrum_60_change_history.py` | 27 passed (20 test functions; the AC3 and AC4 role/method cases are parameterised). `history.py` and `history_views.py` have 100% statement and branch coverage. |
| Full backend suite (PostgreSQL 16) | 1316 passed; total coverage 99.59% |
| Web: lint, `vitest` with CI coverage settings, build | Clean; 295 passed; `ChangeHistory.tsx` 100% |
| Existing tests adjusted | Lead and coordinator page tests now mock the history API. They test assignment and editing, not history. |
| Playwright, all 12 journeys, `--workers=1 --retries=0` | 12 passed |
| Upgrade from the baseline | Rolled `events` back to `0010`, added a SCRUM-61-style audit row, then migrated forward. Two entries were imported (`name`, `expected_attendance`) with no values and the original actor. |
| Browser check | The coordinator edited attendance (180→150) and the name in the UI. The panel showed the exact before/after values, the user and the time, newest first, with the imported entries as *Not recorded*. The Lead saw the same five rows. The organiser's GET returned 403. |

Still to do: a teammate correctness review and a manual check in the app with demo data. SCRUM-20/80 will add their own sources through the same writer.
