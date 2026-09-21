# ConnectSphere Event Planning and Venue Booking System

IS212 Software Project Management, AY 2026-27 T1. First release, built with Scrum
over four sprints. This repository is the Sprint 1 slice.

## What works today

Sprint 1 delivered one thin vertical slice through the whole stack:

| Story | What it does |
|---|---|
| US-01.1 | Sign in and land on the view for your role |
| US-01.2 | Access is restricted by role and by relationship to an event |
| US-02.1 | An Event Organiser creates an event request |
| US-02.2 | An Event Organiser submits a completed request |
| US-03.1 | An Event Organiser saves an incomplete request as a draft |
| US-04.1 | An Event Coordinator sees submitted requests in a queue |
| US-06.1 | Every event shows its current status in plain language |

Venues, equipment, registration, change requests and notifications arrive in
sprints 2 to 4. Their Django apps exist but are deliberately empty, so that the
repository structure matches the C4 level 3 component diagram in `docs/c4`.

## Running it

You need Docker, Python 3.12 and Node 20.

```bash
# 1. Database
docker compose up -d

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
cd api  && pytest                 # 70 tests, coverage gate at 80%
cd web  && npm run test           # 10 tests
cd web  && npm run e2e            # Playwright, needs api + web running
```

Backend tests are named after the acceptance criteria they verify. Open
`api/apps/events/tests/test_us_03_1_save_draft.py` and you will find
`test_ac1_...` through `test_ac6_...`, matching the six criteria on US-03.1 in
the product backlog. That mapping is what feeds the traceability matrix.

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
