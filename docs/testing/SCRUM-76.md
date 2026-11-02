# SCRUM-76 - See which events are holding equipment I need

Owner: Jerom. Branch: `feature/equipment-holding-events`, from main `6bfb7b0` (G15, G16a and G16b merged). Sprint 3 gate **G18**; depends on G15 (SCRUM-12, PR #20), G16b (SCRUM-77, PR #22) and G17 (SCRUM-75, Adilah, PR #23).

**Merge order:** G17 (PR #23) merged on 2 November 2026 (`b5c55b9`) and was merged into this branch in `eb80933`. The one conflict, in `services.py`, kept both new sections; no names overlap. The checks were rerun afterwards (see below).

## Rules

Module: `api/apps/equipment/services.py` (section "SCRUM-76").

| Name | Meaning |
| --- | --- |
| `holding_reservations(type, starts_at, ends_at, exclude_event=None)` | The reservations SCRUM-12 subtracts: active reservations of non-cancelled events overlapping the period (half-open), earliest first, excluding the requesting event's own |
| `holders(type, starts_at, ends_at, viewer=, event=)` | The same reservations, scoped to the viewer's role (AC3) |

What each role sees about a holder:

| Viewer | Fields |
| --- | --- |
| Technical Support | Reservation id, quantity, period, and the holding event's id, name, status and coordinator name and email, so they can negotiate |
| The requesting event's assigned coordinator | Reservation id, quantity and period only. Another client's event is not theirs to see |
| Nobody | The holding event's organisation or client details |

- **Cancelled events (AC4)** are released by the real cancellation action (SCRUM-77 / INT-03). Even a still-active reservation of a cancelled event never counts, so the next availability read shows the quantity as available again.

## API and screen

`GET /api/events/<event_id>/equipment-availability/<equipment_type_id>/[?starts_at=&ends_at=]` returns the type's availability row (including out-of-action reasons and expected return, AC2) and `holders`. Access and period rules are the same as SCRUM-12: Technical Support for events with equipment requested, or the assigned coordinator. Other roles are refused with 403 and audited, and the body names no holder.

**Screen:** on the availability page, a held or out-of-action row has "See who is holding it". It opens the "Holding events" panel for the same period.

## Acceptance criteria

| AC | Status |
| --- | --- |
| AC1 holding events and their dates listed | Done; tested through real SCRUM-16 reservations |
| AC2 reason and expected return where recorded | Done and tested; an unknown return is stated |
| AC3 only the information the role permits | Done and tested (API, service and component) |
| AC4 cancelled holder's equipment available again | Done; tested through the real SCRUM-77 cancellation endpoint |

## Test evidence

Records: [`test-cases/S3-SCRUM-76-holding-events.csv`](../test-cases/S3-SCRUM-76-holding-events.csv). API tests: `api/apps/equipment/tests/test_scrum_76_holding_events.py`. Component tests: `web/src/components/equipment/EquipmentHoldersPanel.test.tsx`, plus a page test in `web/src/pages/EquipmentAvailability.test.tsx`.

Run on 2 November 2026 by Claude (AI assistant) for Jerom, on local PostgreSQL 16, Python 3.12 and Node 22 (CI uses Node 20). This is an agent run, not a teammate's correctness review.

| Check | Result |
| --- | --- |
| `manage.py check`, `makemigrations --check` (no migration in this change), `ruff check .`, `ruff format --check .` | Clean |
| SCRUM-76 API tests | 21 passed |
| Full backend suite (`pytest --cov-branch`) | 1153 passed; one line then uncovered (a holder without a coordinator), so a test was added (equipment suite rerun: 314 passed); `equipment/services.py` and `equipment/views.py` now 100% statements and branches; production-only coverage 99% |
| `npm run lint`, `npm run test`, `npm run build` | Clean; 241 tests passed; build succeeded |
| Seeded fault: holder event details shown to every role | Caught (AC3 cases) |
| Seeded fault: the event's own reservation listed as a holder | Caught (AC1 case) |
| Seeded fault: a cancelled event's reservation counted | Caught (AC4 case) |
| Agent browser check (Chromium, real API and database) | Two events were assigned, approved and given equipment requests, and one event's projectors were reserved, all through the real services. Technical Support saw the holding event, its status and its coordinator's contact; the other event's coordinator saw only "Reserved by another event" with quantity and dates. After the holding event's coordinator cancelled it through the real endpoint, the next check showed 8 available and no holders |

One SCRUM-12 page test now compares the leading number of each table cell, because the "Reserved by other events" cell also holds the new button. The expected values are unchanged.

### After merging main (G17)

Rerun on 2 November 2026 by Claude (AI assistant) on the merged branch: 1183 backend tests passed; `equipment/services.py` and `views.py` 100% statements and branches; web 248 tests passed; type check and build clean.

### Not yet done

- **J3 browser journey:** add a holding-events step to `web/e2e/sprint3-equipment.spec.ts`.
- **Teammate code and test review**, and a team member's manual check: pending.
