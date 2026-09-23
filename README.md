# SPM-Project
SPM Project


## Adilah: US-02.1 ? Create an event request

Extracted from local `Jerom` (d981448) for the four creation acceptance criteria:
enter event details, reject non-positive attendance, reject past start dates,
and show the created request with its current status in the organiser list.
New requests start in `Draft`, matching the source implementation.

This slice includes shared React/Django setup, session sign-in, organisation
access checks, and the existing database schema needed by creation. Shared
models/migrations retain their original schema for compatibility. It does not
expose submission, reopening/editing/deleting drafts, coordinator queues, or
status transitions.

### Run locally

1. Run `docker compose up -d` from the repository root.
2. In `api`, create/activate a Python virtual environment, run
   `pip install -r requirements.txt`, then `python manage.py migrate`.
3. Use an existing Event Organiser account linked to a client organisation.
   For a fresh database, run `python manage.py createsuperuser`, start
   `python manage.py runserver`, and use `/admin/` to create a client
   organisation and a user with the Event Organiser role linked to it.
4. Start the API with `python manage.py runserver`.
5. In `web`, run `npm ci` and `npm run dev`. Open http://localhost:5173,
   sign in as the organiser, and select **New event request**.

Venue requirements use the source's room-layout selection; registration
requirements use its registration-required checkbox.

### Verify this slice

- API: `python -m pytest apps/events/tests/test_us_02_1_create_request.py`
- Web: `npm run build` and `npm test`

The API suite is scoped to this story; the full-source coverage gate is not
carried over because unrelated stories and their tests are excluded.

