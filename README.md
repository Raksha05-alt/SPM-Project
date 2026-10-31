# ConnectSphere Event Planning and Venue Booking System

IS212 Software Project Management, AY 2026-27 T1. First release, built with Scrum
over four sprints. This branch includes the Sprint 1 slice and SCRUM-51 from Sprint 2.

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
| SCRUM-51 | Assign one available coordinator on submission, notify both users, and show coordinator contact details |
| SCRUM-65 | Venue Staff create and update venue records with the user and time of each change; capacity must be at least one, and only Venue Staff may write |
| SCRUM-9 | Venue Staff open the venue catalogue and each venue's full details; missing information is named rather than left blank, and the operational status is shown. Attendees are refused |

Sprint 2 extended US-01.2 (SCRUM-1): anonymous refusals are now recorded, the
audit write can no longer turn a 403 into a 500, and `GET /api/audit/` lets
ConnectSphere staff read the recorded refusals back. See
`docs/scrum-1-access-control-notes.md`.

Venues, equipment, registration, change requests and broader notifications arrive in
sprints 2 to 4. Assignment notifications are already implemented; the other Django apps are empty so that the
repository structure matches the C4 level 3 component diagram in `docs/c4`.

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

`seed_demo_data` creates role accounts, including two Leads and two coordinators. All use the password
`connectsphere-demo`.

| Email | Role |
|---|---|
| organiser@acme.example | Event Organiser (Acme Pte Ltd) |
| organiser@globex.example | Event Organiser (Globex LLP) |
| coordinator@connectsphere.example | Event Coordinator |
| coordinator2@connectsphere.example | Event Coordinator |
| lead@connectsphere.example | Event Coordinator Lead |
| lead2@connectsphere.example | Event Coordinator Lead |
| venue@connectsphere.example | Venue Staff |
| tech@connectsphere.example | Technical Support Staff |
| attendee@example.com | Attendee |
| safety@connectsphere.example | Safety Officer |

Sign in as both organisers to see that neither can reach the other's events.

## Tests

### Equipment foundation (SCRUM-16/77, G03)

Run migrations and seed_demo_data to add shared equipment records and stock
examples. Authorised staff can maintain stock and damaged/maintenance records
in Django admin. Equipment workflows and Safety integration follow in later
gates; no request/reservation HTTP action is added here.
See the [equipment contract and handoff](docs/equipment-contract.md).

### Venue discovery and shortlists (SCRUM-64/68 implementation slice)

After migrating, sign in as a coordinator and use **Venue search**, or open an
assigned event and choose **Venue search and shortlist**. Filters cover recorded
capacity, layouts, facilities, operating hours and recorded date-specific blocks.
Shortlists persist per event and recheck current venue data when reopened.

Search and shortlist checks share the merged SCRUM-13/17 date-block rules and
SCRUM-5 layout query. Booking/hold occupancy still requires the booking workflow;
results retain an unverified availability notice. Run all migrations, including
the merge migration joining the block and shortlist tables. See the
[implementation and AC/test map](docs/scrum-64-68-venue-discovery.md) for tested
behaviour, the remaining cases and the demo procedure.

### Running the test suites

```bash
cd api  && pytest                 # coverage gate at 80%
cd web  && npm run test
cd web  && npm run e2e            # Playwright, needs api + web running
```

Backend tests are named after the acceptance criteria they verify. Open
`api/apps/events/tests/test_us_03_1_save_draft.py` and you will find
`test_ac1_...` through `test_ac6_...`, matching the six criteria on US-03.1 in
the product backlog. That mapping is what feeds the traceability matrix.

### Lead allocation and reassignment (SCRUM-89 / SCRUM-53)

After applying migrations, submit a complete request as an organiser. It remains
unassigned. Sign in as a Lead, open **Unassigned requests**, select a coordinator
and save. The organiser can then see the coordinator's name and email. Users can
open **Notifications** in the header; messages persist across sign-ins and refresh
every 30 seconds or when the window regains focus.

Leads choose from active Coordinator accounts. The existing **Coordinator available**
flag is shown for reference; allocation is manual. Inactive accounts are excluded.
Use **Assignments** to inspect all allocations or filter to events you supervise.
Open an event to change its coordinator; Completed and Cancelled events refuse changes.
The previous coordinator loses event access and receives a notification, alongside
the new coordinator and organiser. An outdated assignment form must reload before saving.

See the [Lead allocation implementation and test guide](docs/lead-assignment.md)
for API contracts, AC traceability, execution evidence and review steps.
The [SCRUM-51 guide](docs/scrum-51-coordinator-assignment.md) records the earlier
automatic-allocation behaviour that this customer change replaces.

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
    safety/               EP-21  SCRUM-90 operational safety check (docs/safety-check.md)
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

- Use short-lived feature-group branches such as `feature/account-access`; include affected SCRUM keys in commit messages and pull requests. See [the contribution guide](CONTRIBUTING.md) for the feature map, ownership and verification workflow.
- Every pull request needs one approving review and a green pipeline.
- Access control lives in DRF permission classes, never in view bodies.
- Business rules live in `services.py`, not in serializers or views.
- Every refused request is written to `core.AuditLog`.
