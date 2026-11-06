# SCRUM-12 - Check equipment availability for an event period

Owner: Jerom. Branch: `feature/equipment-availability`, from main `74248b9` (G14 merged). Sprint 3 gate **G15**; depends on G03 (PR #9) and G14 (PR #19).

The Week 9 clarification ("assume it is available if it is in the catalogue") answered a question about buffers. It does not remove the quantity and reservation criteria kept in this story. This gate implements real quantities, as the Sprint 3 guide requires, and no always-available stub.

## Rules

Module: `api/apps/equipment/services.py` (section "SCRUM-12").

| Name | Meaning |
| --- | --- |
| `available_quantity(type, starts_at, ends_at, exclude_event=None)` | Total stock, minus active damaged/maintenance records, minus overlapping active reservations of other non-cancelled events. Never below zero; 0 for a type no longer offered |
| `availability_row(type, starts_at, ends_at, requested=None, event=None)` | Available quantity, out-of-action records (cause, reason, expected return or none), quantity reserved by other events (no event details: those are SCRUM-76), quantity already reserved for this event, requested quantity, shortfall and status (`AVAILABLE`, `PARTIAL`, `UNAVAILABLE`) |
| `reserved_quantity(type, starts_at, ends_at, exclude_event=None)` | Sum of overlapping active reservations |

- **Periods** are half-open `[start, end)`. A reservation ending exactly at the start, or starting exactly at the end, does not reduce the count; a one-second overlap does. Periods must have a time zone and end after they start (`contracts.validate_period`).
- **Equipment uses the event's actual period.** Venue setup/turnaround buffers do not apply.
- **Released reservations and reservations of cancelled events never count.** An event's own reservations are not counted as unavailable to it.
- **For SCRUM-16 (G16a, Nethren):** the reservation action should lock the equipment-type rows (`contracts.lock_equipment_types`), then call `available_quantity` to refuse over-allocation, so the check and the write see the same stock.

## API and screen

`GET /api/events/<event_id>/equipment-availability/[?starts_at=&ends_at=]`

- **Period:** the event's preferred period by default, or both query values as ISO 8601 date-times with a time zone. Any other input returns a 400 with a `period` message.
- **Rows:** every offered type, plus any retired type the event still requests.
- **Shortfalls:** listed separately as well.
- **Access (AC6):** Technical Support, for events with equipment requested (the G14 scope rule), and the event's assigned coordinator. Leads, Organisers, Attendees, Venue Staff, Safety Officers, other or reassigned coordinators, anonymous callers and drafts are refused with 403. Each refusal is audited, and the 403 body names no event or reservation.

**Screen:** `/equipment/availability` lets you choose an event (Technical Support from their inbox, a coordinator from their own events). `/equipment/availability/:id` shows a period form, a shortfall panel and the availability table.

It is linked from each Technical Support inbox event ("Check availability") and from the coordinator's Equipment requests section.

## Acceptance criteria

| AC | Status |
| --- | --- |
| AC1 choose an event and period | Done and tested (API and component) |
| AC2 available quantity shown | Done and tested; 10 - 2 - 5 = 3 |
| AC3 reserved for another event shown as unavailable | Done and tested against reservation rows; **rerun through the real SCRUM-16 action at G16a** |
| AC4 damaged or under maintenance unavailable for any period | Done and tested |
| AC5 shortfall indicated | Done and tested; 4 requested against 3 available is short by 1 |
| AC6 only Technical Support or the assigned coordinator | Done and tested |

## Test evidence

Records: [`test-cases/S3-SCRUM-12-equipment-availability.csv`](../test-cases/S3-SCRUM-12-equipment-availability.csv). API tests: `api/apps/equipment/tests/test_scrum_12_equipment_availability.py`. Component tests: `web/src/pages/EquipmentAvailability.test.tsx`.

Run on 2 November 2026 by Claude (AI assistant) for Jerom, on local PostgreSQL 16, Python 3.12 and Node 22 (CI uses Node 20). This is an agent run, not a teammate's correctness review.

| Check | Result |
| --- | --- |
| `manage.py check`, `makemigrations --check` (no migration in this change), `ruff check .`, `ruff format --check .` | Clean |
| SCRUM-12 API tests | 43 passed |
| Full backend suite (`pytest --cov-branch`) | 1043 passed; `equipment/services.py` and `equipment/views.py` 100% statements and branches; production-only coverage 99% |
| `npm run lint`, `npm run test`, `npm run build` | Clean; 192 tests passed; build succeeded |
| Seeded fault: reservations added instead of subtracted | Caught (AC2/AC3 cases) |
| Seeded fault: damaged/maintenance stock ignored | Caught (AC2/AC4/AC5 cases) |
| Seeded fault: assigned-coordinator check removed | Caught (AC6 case) |
| Agent browser check (Chromium, real API and database) | Event assigned by the Lead, approved by the coordinator and 9 projectors requested, all through the real services; the seed's 2 damaged projectors give 8 available and "short by 1", with reason and return date; another coordinator and a Lead got 403 with no event details |

Two existing SCRUM-74 test files (`EquipmentInbox.test.tsx`, `EquipmentRequests.test.tsx`) now render inside a `MemoryRouter`, because those screens gained a "Check availability" link. No assertion changed.

### Not yet done

- **AC3 through the real reservation action:** rerun at G16a/G17 (the guide asks for API-driven quantity reruns then). The browser check had no reservations, because that action does not exist yet.
- **J3 browser journey:** the availability step joins `web/e2e/sprint3-equipment.spec.ts` once reservation exists.
- **Teammate code and test review**, and a team member's manual check: pending.
