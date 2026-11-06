# ConnectSphere Event Planning and Venue Booking System

IS212 Software Project Management, AY 2026-27 T1. ConnectSphere supports
event requests, resource planning, safety approval and attendee registration.

## What works today

- Role-based sign-in, account details and event-level permissions.
- Drafts, submission, Lead assignment/reassignment and coordinator review.
- Venue records, layouts, search, shortlists, availability, booking decisions,
  alternatives, multiple sessions, setup/turnaround buffers and expiring holds.
- Equipment requests, stock availability, reservation, amendment and release.
- Safety Officer decisions and readiness checks before event confirmation.
- Approved changes with staff impact review, fresh safety checks and history.
- Registration windows and capacity, withdrawal, FIFO waiting-list notices and
  recipient-only notifications.

Leads assign submitted requests manually. SCRUM-89 replaced SCRUM-51's earlier
automatic allocation. Historical implementation notes describe their original
slices; current API behaviour and acceptance tests take precedence.

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

# 3. Hold expiry and reminder worker (new terminal, from repository root)
cd api
source .venv/bin/activate
python manage.py process_venue_holds --watch --interval 60

# 4. Web (new terminal, from repository root, http://localhost:5173)
cd web
npm ci
npm run dev
```

Open http://localhost:5173. Vite proxies everything under `/api` to Django, so
there is no CORS configuration to get wrong in development.

Keep the hold worker running alongside the API. It records overdue expiries
and sends in-app reminders once per deadline revision. Set
`VENUE_HOLD_REMINDER_HOURS` in the environment to change the 24-hour reminder
window. Venue availability frees an expired slot at the deadline. After a
restart, the worker catches up on outstanding notices and expiry history.

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
| attendee2@example.com | Attendee |
| attendee3@example.com | Attendee |
| safety@connectsphere.example | Safety Officer |

Sign in as both organisers to see that neither can reach the other's events.

## Tests

### Equipment foundation (SCRUM-16/77, G03)

Run migrations and seed_demo_data to add shared equipment records and stock
examples. Authorised staff can maintain stock and damaged/maintenance records
in Django admin. The implemented workflows include requests, stock availability, reservation,
amendment, release, cancellation and transactional Safety invalidation.
See the [equipment contract and handoff](docs/equipment-contract.md).

### Venue discovery and shortlists (SCRUM-64/68 implementation slice)

After migrating, sign in as a coordinator and use **Venue search**, or open an
assigned event and choose **Venue search and shortlist**. Filters cover recorded
capacity, layouts, facilities, operating hours, recorded date-specific blocks and
approved venue bookings. Shortlists persist per event and recheck current data
when reopened, refreshed or when you return focus to the page.

G12 uses the shared occupancy service and the real request/approval/withdrawal
actions. Available periods show **Available for this period**; missing dates
remain unverified. A booking that obstructs a saved venue leaves that entry in
the shortlist with its conflict reference. **Refresh availability** updates both
results and saved entries. Searching does not reserve the venue; staff recheck
at approval. Tentative holds occupy the venue until their deadline; the worker records
expiration and sends the coordinator a notice. See the [G12 contract and evidence](docs/venue-discovery-booking-integration.md)
and the [earlier AC/test map](docs/scrum-64-68-venue-discovery.md).

### Operational Safety Check (SCRUM-90)

Once an event in Planning has an approved venue booking and a current
Technical Support approval, its coordinator requests a safety check from the
event page. Safety Officers (`safety@connectsphere.example`) land on
**Operational safety checks**, review attendance, venues (capacity, layout,
emergency access, known restrictions, accessibility) and equipment, then
approve, request changes or reject; a comment is required for the last two.
An event cannot move to Confirmed without a current approved check, and any
later change to its venue, equipment, date, time or attendance makes the
approval stale. See the [safety check guide](docs/safety-check.md).

### Running the test suites

```bash
# Run each command from the repository root in a fresh terminal.
(cd api && pytest --cov-branch --junitxml=test-results/api-junit.xml)
(cd web && npm run lint && npm run test && npm run build)
(cd web && npx playwright install chromium)
(cd web && npx playwright test --workers=1 --retries=0 --reporter=list,json,junit,html)
```

Browser tests use real API actions, PostgreSQL and the seeded accounts. Keep the
API and hold worker running. Playwright starts the frontend when needed. Use an
isolated, disposable database: the tests create events, notifications and rooms,
and exercise account edits, cancellations and expiring holds. Do not point them
at a shared project database.

To use separate ports, set `E2E_BASE_URL=http://127.0.0.1:5174` and
`API_PROXY_TARGET=http://127.0.0.1:8001` on the Playwright command, run Django on
8001, and add `http://127.0.0.1:5174` to
`DJANGO_CSRF_TRUSTED_ORIGINS`. Run the worker with the same database environment
as Django. HTML evidence opens with `npx playwright show-report`; CI exports
JSON/JUnit and failure traces instead.

The pytest configuration enforces an 80% minimum. Report production-only line
and branch coverage separately from test/migration coverage; the course's
coverage and human-review requirements still apply.

The [testing guide](docs/testing/README.md) links the complete US case workbook, story index, packaged execution reports and coverage gaps.

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
  src/pages/              screens and browser routes
  e2e/                    real browser acceptance journeys
docs/
  c4/                     context, container and component diagrams
  adr/                    architecture decision records
  sprint-1-notes.md       deviations, deferrals and the coverage exception
```

## Conventions

- Use the agreed feature group, for example `feature/venue-discovery`; include the Jira keys in commits and PRs. See [the contribution guide](CONTRIBUTING.md) for branch scope, integration and historical feature mappings.
- Every pull request needs one approving review and a green pipeline.
- Access checks run on the server, including role and relationship checks in API permissions and domain services.
- Keep transactional business rules in their domain services.
- See the [access-control notes](docs/scrum-1-access-control-notes.md) for audit behaviour.

### Amend or withdraw equipment (SCRUM-75)

Open an assigned event, then **Equipment plan and reservations**. Before event
confirmation, the assigned coordinator can amend a request or confirm its withdrawal.
Reductions release only surplus units; withdrawal releases its reservations and keeps
its history. Technical Support receives a notification and can approve a revised
plan with retained reservations. Changed arrangements require a fresh Safety check.
See [the API and acceptance-test map](docs/scrum-75-equipment-amendment.md).
