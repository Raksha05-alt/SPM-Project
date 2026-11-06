"""SCRUM-60 - see who changed event information and when.

Edits go through the real PATCH /api/events/<id>/ action (SCRUM-61); the
history is read through GET /api/events/<id>/change-history/.
"""

import datetime
import importlib
from unittest import mock

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.history import jsonable, record_field_changes
from apps.events.history_views import _display
from apps.events.models import AppendOnlyError, ChangeSource, EventFieldChange
from conftest import _make_user, make_event

pytestmark = pytest.mark.django_db
SGT = datetime.timezone(datetime.timedelta(hours=8))
START = datetime.datetime(2027, 3, 1, 9, 0, tzinfo=SGT)


def history_url(event):
    return f"/api/events/{event.pk}/change-history/"


@pytest.fixture
def event(organiser, coordinator, lead):
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        supervising_lead=lead,
        name="Partner Summit",
        expected_attendance=120,
        preferred_start=START,
        preferred_end=START + datetime.timedelta(hours=6),
        required_layout="THEATRE",
        registration_required=False,
    )


def edit(api, user, event, **changes):
    api.force_authenticate(user)
    response = api.patch(f"/api/events/{event.pk}/", changes, format="json")
    assert response.status_code == 200, response.data
    return response


def changes(api, user, event):
    api.force_authenticate(user)
    response = api.get(history_url(event))
    assert response.status_code == 200, response.data
    return response.data["changes"]


# --------------------------------------------------------------------------
# AC1 - field, previous value, new value, user and time
# --------------------------------------------------------------------------


def test_ac1a_each_change_shows_the_field_both_values_the_user_and_time(api, event, coordinator):
    before = timezone.now()
    edit(api, coordinator, event, name="Partner Summit 2027", expected_attendance=150)

    entries = {e["field"]: e for e in changes(api, coordinator, event)}

    assert set(entries) == {"name", "expected_attendance"}
    name = entries["name"]
    assert (name["field_label"], name["before_display"], name["after_display"]) == (
        "Name",
        "Partner Summit",
        "Partner Summit 2027",
    )
    assert (entries["expected_attendance"]["before"], entries["expected_attendance"]["after"]) == (
        120,
        150,
    )
    assert name["actor_name"] == "Cora Coordinator"
    assert name["source"] == ChangeSource.EVENT_EDIT
    assert name["values_recorded"] is True
    assert datetime.datetime.fromisoformat(name["changed_at"]) >= before


def test_ac1b_dates_layouts_flags_and_blanks_are_shown_readably(api, event, coordinator):
    edit(
        api,
        coordinator,
        event,
        preferred_start=(START + datetime.timedelta(hours=1)).isoformat(),
        required_layout="BANQUET",
        registration_required=True,
        accessibility_needs="Two wheelchair users.",
    )

    entries = {e["field"]: e for e in changes(api, coordinator, event)}

    assert entries["preferred_start"]["before_display"] == "01 Mar 2027, 09:00"
    assert entries["preferred_start"]["after_display"] == "01 Mar 2027, 10:00"
    # Stored as an ISO instant (UTC), shown in Singapore time.
    assert datetime.datetime.fromisoformat(entries["preferred_start"]["before"]) == START
    assert (
        entries["required_layout"]["before_display"],
        entries["required_layout"]["after_display"],
    ) == (
        "Theatre",
        "Banquet",
    )
    assert entries["registration_required"]["after_display"] == "Yes"
    assert entries["accessibility_needs"]["before_display"] == "Not set"


def test_ac1c_a_save_that_changes_nothing_records_nothing(api, event, coordinator):
    edit(api, coordinator, event, name="Partner Summit", expected_attendance=120)

    assert changes(api, coordinator, event) == []
    assert not EventFieldChange.objects.exists()


def test_ac1d_a_failure_to_record_history_rolls_the_edit_back(api, event, coordinator):
    api.force_authenticate(coordinator)
    with (
        mock.patch.object(
            EventFieldChange.objects, "bulk_create", side_effect=RuntimeError("history down")
        ),
        pytest.raises(RuntimeError),
    ):
        api.patch(f"/api/events/{event.pk}/", {"name": "Lost edit"}, format="json")

    event.refresh_from_db()
    assert event.name == "Partner Summit"
    assert not AuditLog.objects.filter(action=f"Event {event.pk} edited").exists()


# --------------------------------------------------------------------------
# AC2 - most recent first
# --------------------------------------------------------------------------


def test_ac2_entries_are_listed_most_recent_first(api, event, coordinator, lead):
    edit(api, coordinator, event, name="Second name")
    earlier = EventFieldChange.objects.get()
    edit(api, coordinator, event, name="Third name")

    data = changes(api, lead, event)

    assert [e["after"] for e in data] == ["Third name", "Second name"]
    assert data[1]["id"] == earlier.pk


def test_ac2b_one_edit_shares_one_time_and_lists_newest_entry_first(event, coordinator):
    entries = record_field_changes(
        event=event,
        before={"name": "A", "purpose": "B"},
        after={"name": "C", "purpose": "D"},
        actor=coordinator,
    )

    assert len({e.changed_at for e in entries}) == 1
    assert list(event.field_changes.values_list("field", flat=True)) == ["purpose", "name"]


# --------------------------------------------------------------------------
# AC3 - organisers and attendees are refused; access follows the event
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role",
    [
        Role.EVENT_ORGANISER,
        Role.ATTENDEE,
        Role.VENUE_STAFF,
        Role.TECHNICAL_SUPPORT,
        Role.SAFETY_OFFICER,
    ],
)
def test_ac3a_roles_without_planning_access_are_refused_and_audited(api, event, role, acme):
    user = _make_user(
        f"{role.lower()}@x.example", role, acme if role == Role.EVENT_ORGANISER else None
    )
    api.force_authenticate(user)

    assert api.get(history_url(event)).status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


def test_ac3b_the_events_own_organiser_is_refused(api, event, organiser):
    api.force_authenticate(organiser)

    assert api.get(history_url(event)).status_code == 403


def test_ac3c_another_coordinator_is_refused_and_audited(api, event, second_coordinator):
    api.force_authenticate(second_coordinator)

    assert api.get(history_url(event)).status_code == 403
    assert AuditLog.objects.filter(
        actor=second_coordinator, allowed=False, detail="event is not assigned to this coordinator"
    ).exists()


def test_ac3d_leads_and_the_assigned_coordinator_may_read(api, event, coordinator, lead):
    for user in (coordinator, lead):
        api.force_authenticate(user)
        assert api.get(history_url(event)).status_code == 200


def test_ac3e_drafts_and_unknown_events_are_closed(api, organiser, lead):
    draft = make_event(organiser)
    api.force_authenticate(lead)

    assert api.get(history_url(draft)).status_code == 403
    assert api.get("/api/events/999999/change-history/").status_code == 404


def test_ac3f_signed_out_requests_are_refused(api, event):
    assert api.get(history_url(event)).status_code in (401, 403)


# --------------------------------------------------------------------------
# AC4 - no one can edit or delete an entry
# --------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_ac4a_the_api_refuses_every_write_and_audits_it(api, event, coordinator, method):
    edit(api, coordinator, event, name="Changed")
    api.force_authenticate(coordinator)

    response = getattr(api, method)(history_url(event), {"after": "forged"}, format="json")

    assert response.status_code == 405
    assert AuditLog.objects.filter(
        actor=coordinator, allowed=False, detail="change history is append-only"
    ).exists()
    assert EventFieldChange.objects.get().after == "Changed"


def test_ac4b_organisers_cannot_write_either(api, event, organiser):
    api.force_authenticate(organiser)

    assert api.delete(history_url(event)).status_code == 403


def test_ac4c_entries_cannot_be_edited_or_deleted_in_code(event, coordinator):
    [entry] = record_field_changes(
        event=event, before={"name": "A"}, after={"name": "B"}, actor=coordinator
    )
    entry = EventFieldChange.objects.get(pk=entry.pk)

    entry.after = "forged"
    with pytest.raises(AppendOnlyError):
        entry.save()
    with pytest.raises(AppendOnlyError):
        entry.delete()
    with pytest.raises(AppendOnlyError):
        EventFieldChange.objects.filter(pk=entry.pk).update(after="forged")
    with pytest.raises(AppendOnlyError):
        EventFieldChange.objects.all().delete()
    assert EventFieldChange.objects.get(pk=entry.pk).after == "B"


def test_ac4d_there_is_no_route_to_a_single_entry(api, event, coordinator):
    edit(api, coordinator, event, name="Changed")
    entry = EventFieldChange.objects.get()
    api.force_authenticate(coordinator)

    assert api.delete(f"/api/events/{event.pk}/change-history/{entry.pk}/").status_code == 404


# --------------------------------------------------------------------------
# No invented history: earlier SCRUM-61 edits are imported as "not recorded"
# --------------------------------------------------------------------------


def test_h1_earlier_audited_edits_are_imported_without_values(api, event, coordinator, lead):
    AuditLog.objects.create(
        actor=coordinator,
        action=f"Event {event.pk} edited",
        object_type="EventRequest",
        object_id=str(event.pk),
        allowed=True,
        detail="Changed: name, expected_attendance",
    )
    AuditLog.objects.create(actor=coordinator, action="Event 999999 edited", detail="Changed: name")
    AuditLog.objects.create(actor=coordinator, action=f"Event {event.pk} confirmed", detail="")
    AuditLog.objects.create(
        actor=coordinator, action=f"Event {event.pk} edited", allowed=False, detail="Changed: name"
    )
    migration = importlib.import_module("apps.events.migrations.0012_import_earlier_edits")
    # The historical models a real `migrate` passes in.
    state = (
        MigrationExecutor(connection)
        .loader.project_state(("events", "0012_import_earlier_edits"))
        .apps
    )

    migration.forwards(state, None)

    data = changes(api, lead, event)
    assert {e["field"] for e in data} == {"name", "expected_attendance"}
    assert all(e["values_recorded"] is False for e in data)
    assert {e["before_display"] for e in data} == {"Not recorded"}
    assert {e["after_display"] for e in data} == {"Not recorded"}
    assert data[0]["source_label"] == "Earlier edit (values not recorded)"

    migration.backwards(state, None)
    assert not EventFieldChange.objects.exists()


def test_h2_values_are_stored_as_json(event):
    assert jsonable(START) == START.isoformat()
    assert jsonable(datetime.date(2027, 3, 1)) == "2027-03-01"
    assert jsonable(__import__("decimal").Decimal("1.50")) == "1.50"
    assert jsonable(7) == 7


def test_h3_an_unknown_field_keeps_its_stored_name(api, event, coordinator, lead):
    record_field_changes(
        event=event, before={"old_field": "x"}, after={"old_field": "y"}, actor=None
    )

    [entry] = changes(api, lead, event)
    assert entry["field_label"] == "Old field"
    assert entry["actor_name"] is None


def test_h4_an_unreadable_stored_date_is_shown_as_stored():
    assert _display("preferred_start", "not a date", {}) == "not a date"
