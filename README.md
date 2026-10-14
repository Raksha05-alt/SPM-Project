# ConnectSphere Event Planning and Venue Booking System

IS212 Software Project Management, AY 2026-27 T1. First release, built with Scrum
over four sprints. It implements every story in the Jira backlog for the original
requirements (Week 1 briefing and Week 4 instructions), the six Week 7 customer
changes, and the answers from the Week 9 clarification session. See
[Week 7 change analysis](docs/week-7-changes.md) for the change descriptions,
the new and superseded acceptance criteria, story points and design notes.

## What works today

| Area | Stories |
|---|---|
| Sign-in, roles, access control, audit log, account details | US-01.1, US-01.2, SCRUM-1, SCRUM-2 |
| Event requests: create, drafts, submit, organiser lists | US-02.1, US-02.2, US-03.1, SCRUM-45, SCRUM-48 |
| Review: queue, approve, reject, clarification | US-04.1, SCRUM-49, SCRUM-50, SCRUM-52 |
| Coordinators: my events (assignment is now by the Lead) | SCRUM-53, SCRUM-54 |
| Status: plain-language status, permitted transitions, filters, cancel, complete | US-06.1, SCRUM-55, SCRUM-56, SCRUM-57 |
| Event information: edits during planning, change history, significant changes | SCRUM-59, SCRUM-60, SCRUM-61 |
| Venue catalogue, facilities, blocks | SCRUM-5, SCRUM-9, SCRUM-13, SCRUM-65 |
| Venue availability, comparison, search, suitability, shortlist | SCRUM-17, SCRUM-62, SCRUM-64, SCRUM-66, SCRUM-68, SCRUM-71 |
| Venue bookings: request, approve or reject, suggest, withdraw, conflicts | SCRUM-11, SCRUM-67, SCRUM-69, SCRUM-70, SCRUM-72, SCRUM-73 |
| Equipment: requests, availability, holders, reservations, release | SCRUM-12, SCRUM-16, SCRUM-74, SCRUM-75, SCRUM-76, SCRUM-77 |
| Confirming an event | SCRUM-58 |
| Change requests and staff review | SCRUM-20, SCRUM-78, SCRUM-80 |
| Attendee registration, withdrawal, capacity, waiting list | SCRUM-14, SCRUM-19, SCRUM-21, SCRUM-81 |
| Notifications | SCRUM-18, SCRUM-79, SCRUM-82 |

**Week 7 changes and Week 9 clarifications**

| Change | What it adds |
|---|---|
| CR1 Setup and turnaround | Per-venue buffers. A booking occupies the venue from start - setup to end + turnaround in availability, search and conflict checks. Bookings that become problematic are flagged, never removed. |
| CR2 Venue unavailable | Categorised blocks or switching a venue out of service mark future bookings **Disrupted**. Coordinators and clients are notified, a confirmed event returns to Planning, and the coordinator requests a replacement. |
| CR3 Multiple venues | Several bookings per event, one per session, each checked and approved on its own. Withdrawing one leaves the rest. |
| CR4 Tentative holds | Venue Staff approve as a hold with an expiry they choose and can change. The coordinator confirms the hold. It expires at the deadline, with a warning 24h before and a notice on expiry. |
| CR5 Event Coordinator Lead | No auto-assignment. Submitted requests wait in the Lead's unassigned queue, and the Lead assigns and reassigns. Coordinators see only their own events. |
| CR6 Operational Safety Check | Once the venue and equipment are in place, the coordinator requests a check. The Safety Officer approves, rejects or requests changes, and the event cannot be confirmed until it is approved. Any later change needs a new check. |
| Clarifications | Room layout catalogue (add, edit, retire, delete). Offline clarification recorded as notes. Organisers edit drafts only. Coordinators edit until Confirmed, then through a change request. |

Backend tests are named after the acceptance criteria they prove
(`test_scrum_NN_*.py`, `test_acN_...`), so each criterion can be traced to a test.
Equipment types are maintained in the Django admin (`/admin/`); the demo seed
creates a starter set.

## Running it

You need Docker, Python 3.12 and Node 20.

```bash
# 1. Database
docker compose up -d
# Copy .env.example to .env at the repository root and match POSTGRES_PORT
# to the host port in docker-compose.yml before starting the API.

# 2. API  (http://localhost:8000)
cd api
python3.12 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver

# 3. Web  (http://localhost:5173)
cd ../web
npm ci
npm run dev
```

Open http://localhost:5173. Vite proxies everything under `/api` to Django, so
there is no CORS configuration to get wrong in development.

### Demo accounts

`seed_demo_data` creates at least one user per role. All of them use the password
`connectsphere-demo`.

| Email | Role |
|---|---|
| organiser@acme.example | Event Organiser (Acme Pte Ltd) |
| organiser@globex.example | Event Organiser (Globex LLP) |
| lead@connectsphere.example | Event Coordinator Lead |
| coordinator@connectsphere.example | Event Coordinator (Cora) |
| coordinator2@connectsphere.example | Event Coordinator (a second one, for reassignment) |
| safety@connectsphere.example | Safety Officer |
| venue@connectsphere.example | Venue Staff |
| tech@connectsphere.example | Technical Support Staff |
| attendee@example.com | Attendee |

Sign in as both organisers to see that neither can reach the other's events.

### Expiring holds

Holds stop reserving a venue the moment they expire. Warnings and the Expired
status are written whenever the booking screens are used, and by a management
command you should schedule (every 15 minutes is plenty):

```bash
python manage.py process_venue_holds
```

`HOLD_WARNING_HOURS` (default 24) sets how early the coordinator is warned.

## Tests

```bash
cd api  && pytest                 # 100% line and branch coverage of production code
cd web  && npm run test
cd web  && npm run e2e            # Playwright, needs api + web running
```

Backend tests are named after the acceptance criteria they verify. Open
`api/apps/events/tests/test_us_03_1_save_draft.py` and you will find
`test_ac1_...` through `test_ac6_...`, matching the six criteria on US-03.1 in
the product backlog. That mapping is what feeds the traceability matrix.

### Coordinator assignment (Week 7 change 5)

SCRUM-51's automatic assignment has been replaced. Submit a request as an
organiser and sign in as `lead@connectsphere.example`. The request is in the
**Unassigned** queue. Choose a coordinator and assign it. The coordinator, the
client and any previous coordinator are notified, and the Lead can reassign from
the event page at any time. The
[SCRUM-51 guide](docs/scrum-51-coordinator-assignment.md) is kept for history.

## Layout

```
api/
  config/                 settings, root urls
  apps/
    accounts/             EP-01   users, roles, session auth
    core/                 EP-06   status machine, audit log, health endpoint
    events/               EP-02 to EP-05, EP-07, EP-19
    venues/               EP-08 to EP-14   (sprints 2 and 3)
    equipment/            EP-15 to EP-17   (sprint 4)
    registrations/        EP-18            (sprint 4)
    notifications/        EP-20            (sprint 4)
    safety/               Week 7 change 6  Operational Safety Check
web/
  src/api/                fetch wrapper, CSRF handling, endpoints
  src/auth/               session context and route guards
  src/pages/              one file per screen
  e2e/                    Playwright journeys (submit -> Lead assign; hold -> safety -> confirm)
docs/
  c4/                     context, container and component diagrams
  adr/                    architecture decision records
  sprint-1-notes.md       deviations, deferrals and the coverage exception
  week-7-changes.md       Week 7 / Week 9 change analysis and traceability
```

## Conventions

- Branch names carry the Jira key: `feature/SCRUM-12-submit-draft`.
- Every pull request needs one approving review and a green pipeline.
- Access control lives in DRF permission classes, never in view bodies.
- Business rules live in `services.py`, not in serializers or views.
- Every refused request is written to `core.AuditLog`.
