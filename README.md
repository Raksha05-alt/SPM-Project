# ConnectSphere — SCRUM-8: Save an event request as a draft

This local Raksha branch contains the draft story (US-03.1), extracted from
Jerom at d981448. It includes saving incomplete or empty drafts, confirmation,
listing, reopening, editing and deleting drafts, and organisation privacy.

Because Raksha started with only a README, this includes the required Django /
React scaffold, session login, organisation permissions, database migrations,
shared event schema/status labels, demo data and supporting tests. Shared
migrations are preserved for compatibility with the source branch.

Submission actions, the coordinator queue screen/API, status-vocabulary API,
unrelated event stories, future empty apps and architecture assets are excluded.
Coordinators can sign in but cannot access drafts. The draft privacy test checks
the coordinator event list; the full queue belongs to its separate story.
Seeded submitted records are retained as privacy/read-only fixtures, and are
not shown in the organiser draft list.

## Windows setup

Requirements: Docker Desktop running, Python 3.12+, Node 20+.
Run from the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
docker compose -p spm-raksha up -d
cd api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo_data
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

In a second PowerShell terminal from the repository root:

```powershell
cd web
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1
```

Open http://localhost:5173 and sign in with `organiser@acme.example` /
`connectsphere-demo`. The second organisation uses `organiser@globex.example`
with the same password. Coordinator: `coordinator@connectsphere.example`.

Both `.env.example` and Docker use host port **5433**. Keep `.env` at the
repository root, not in `api`. If 5433 is occupied, change both the Docker host
port and `POSTGRES_PORT` in `.env`. The container port stays 5432.

## Verification

```powershell
# In api
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
# In web
npm.cmd run test
npm.cmd run build
```

The draft form also fixes local date/time display, adds a delete action, and
clears cached requests when switching accounts. Dependencies remain pinned to
the source lockfiles; npm reports existing dependency vulnerabilities.
No remote push is part of this setup.
