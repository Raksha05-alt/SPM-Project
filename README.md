# ConnectSphere Event Planning and Venue Booking System

IS212 Software Project Management, AY 2026-27 T1. First release, built with Scrum
over four sprints. The `Trial_Code` branch implements every story in the Jira
backlog for the original requirements (Week 1 briefing and Week 4 instructions).
The Week 7 customer changes are not included yet.

## What works today

| Area | Stories |
|---|---|
| Sign-in, roles, access control, audit log, account details | US-01.1, US-01.2, SCRUM-1, SCRUM-2 |
| Event requests: create, drafts, submit, organiser lists | US-02.1, US-02.2, US-03.1, SCRUM-45, SCRUM-48 |
| Review: queue, approve, reject, clarification | US-04.1, SCRUM-49, SCRUM-50, SCRUM-52 |
| Coordinators: assignment, my events, reassignment | SCRUM-51, SCRUM-53, SCRUM-54 |
| Status: plain-language status, permitted transitions, filters, cancel, complete | US-06.1, SCRUM-55, SCRUM-56, SCRUM-57 |
| Event information: edits during planning, change history, significant changes | SCRUM-59, SCRUM-60, SCRUM-61 |
| Venue catalogue, layouts, facilities, blocks | SCRUM-5, SCRUM-9, SCRUM-13, SCRUM-65 |
| Venue availability, comparison, search, suitability, shortlist | SCRUM-17, SCRUM-62, SCRUM-64, SCRUM-66, SCRUM-68, SCRUM-71 |
| Venue bookings: request, approve or reject, suggest, withdraw, conflicts | SCRUM-11, SCRUM-67, SCRUM-69, SCRUM-70, SCRUM-72, SCRUM-73 |
| Equipment: requests, availability, holders, reservations, release | SCRUM-12, SCRUM-16, SCRUM-74, SCRUM-75, SCRUM-76, SCRUM-77 |
| Confirming an event | SCRUM-58 |
| Change requests and staff review | SCRUM-20, SCRUM-78, SCRUM-80 |
| Attendee registration, withdrawal, capacity, waiting list | SCRUM-14, SCRUM-19, SCRUM-21, SCRUM-81 |
| Notifications | SCRUM-18, SCRUM-79, SCRUM-82 |

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

`seed_demo_data` creates one user per role. All of them use the password
`connectsphere-demo`.

| Email | Role |
|---|---|
| organiser@acme.example | Event Organiser (Acme Pte Ltd) |
| organiser@globex.example | Event Organiser (Globex LLP) |
| coordinator@connectsphere.example | Event Coordinator |
| venue@connectsphere.example | Venue Staff |
| tech@connectsphere.example | Technical Support Staff |
| attendee@example.com | Attendee |

Sign in as both organisers to see that neither can reach the other's events.

## Tests

```bash
cd api  && pytest                 # coverage gate at 80%
cd web  && npm run test
cd web  && npm run e2e            # Playwright, needs api + web running
```

Backend tests are named after the acceptance criteria they verify. Open
`api/apps/events/tests/test_us_03_1_save_draft.py` and you will find
`test_ac1_...` through `test_ac6_...`, matching the six criteria on US-03.1 in
the product backlog. That mapping is what feeds the traceability matrix.

### Coordinator assignment (SCRUM-51)

After applying migrations, submit a new completed request as an organiser. Open
the submitted request to see the coordinator's name and email. Both users can
open **Notifications** in the header; messages persist across sign-ins and refresh
every 30 seconds or when the window regains focus.

Availability means an active Coordinator account with **Coordinator available**
enabled in Django admin. This is an explicit availability flag, not a workload
or calendar calculation. To try the no-available case, disable it for all
coordinators and submit another request. The request remains Submitted and the
staff queue shows **Unassigned — staff action needed**. Reassignment is outside
SCRUM-51; changing availability does not retroactively assign old requests.

See [SCRUM-51 implementation and test guide](docs/scrum-51-coordinator-assignment.md)
for acceptance-criteria traceability and the confirmed implementation decisions.

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
web/
  src/api/                fetch wrapper, CSRF handling, endpoints
  src/auth/               session context and route guards
  src/pages/              one file per screen
  e2e/                    Playwright journey for the sprint goal
docs/
  c4/                     context, container and component diagrams
  adr/                    architecture decision records
  sprint-1-notes.md       deviations, deferrals and the coverage exception
```

## Conventions

- Branch names carry the Jira key: `feature/SCRUM-12-submit-draft`.
- Every pull request needs one approving review and a green pipeline.
- Access control lives in DRF permission classes, never in view bodies.
- Business rules live in `services.py`, not in serializers or views.
- Every refused request is written to `core.AuditLog`.
