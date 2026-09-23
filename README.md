# SPM-Project
SPM Project


## Shalika: US-02.2 - Submit an event request

Submission extracted from local `Jerom` (d981448), with the US-02.1 creation
prerequisite and shared setup from `Adilah` (a225deb).

- Complete requests move from Draft to Submitted.
- Missing or invalid information prevents submission and identifies fields.
- Success shows confirmation and the recorded submission timestamp.
- Submitted requests can be reopened but cannot be edited.

The shared authentication, organisation access checks, models, migrations and
creation screen are required to run this slice. Coordinator queues, draft deletion
and unrelated story screens are excluded. No changes were made to source branches.

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
   sign in as the organiser, and select **New event request**. Create a request, open it from the list,
   then select **Send to ConnectSphere**. You can also submit directly from the new-request form.

Venue requirements use the source's room-layout selection; registration
requirements use its registration-required checkbox.

### Verify this slice

- API: `python -m pytest apps/events/tests`
- Web: `npm run build` and `npm test`

The API suite is scoped to this story; the full-source coverage gate is not
carried over because unrelated stories and their tests are excluded.
