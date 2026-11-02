"""SCRUM-91 - Maintain the room layout catalogue (Sprint 3 gate G05).

As Venue Staff, I want to add, edit and delete the room layouts the venue
catalogue supports, so that the layouts offered to venues, event requests and
bookings match our rooms.

Case IDs follow the Sprint 3 guide: S3-SCRUM-91-<case>.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from importlib import import_module
from threading import Event as Signal
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps as django_apps
from django.db import close_old_connections, transaction
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest
from apps.venues.bookings import BookingValidationError, create_booking_record
from apps.venues.layouts import LayoutChoiceError, claim_layouts
from apps.venues.models import LayoutType, Venue, VenueBooking
from apps.venues.tests.conftest import make_venue
from conftest import make_event

LAYOUTS = "/api/layouts/"
VENUES = "/api/venues/"
EVENTS = "/api/events/"
SGT = ZoneInfo("Asia/Singapore")


def layout_url(code, suffix=""):
    return f"{LAYOUTS}{code}/{suffix}"


def add_layout(code="CABARET", name="Cabaret", **extra):
    return LayoutType.objects.create(code=code, name=name, sort_order=99, **extra)


def book(event, venue, actor, layout):
    return create_booking_record(
        requested_by=actor,
        event=event,
        venue=venue,
        starts_at=datetime(2027, 3, 1, 10, tzinfo=SGT),
        ends_at=datetime(2027, 3, 1, 12, tzinfo=SGT),
        attendance=60,
        layout=layout,
    )


@pytest.fixture
def staff_api(api, venue_staff):
    api.force_authenticate(venue_staff)
    return api


# S3-SCRUM-91-01 - AC1: a new layout can be added and used everywhere. --------


@pytest.mark.django_db
def test_s3_91_01_the_catalogue_starts_with_the_five_agreed_layouts(staff_api):
    response = staff_api.get(LAYOUTS)

    assert response.status_code == 200
    assert [(row["code"], row["name"], row["is_active"]) for row in response.data] == [
        ("CLASSROOM", "Classroom", True),
        ("THEATRE", "Theatre", True),
        ("BOARDROOM", "Boardroom", True),
        ("BANQUET", "Banquet", True),
        ("EXHIBITION", "Exhibition", True),
    ]


@pytest.mark.django_db
def test_s3_91_01_ac1_venue_staff_add_a_layout_with_a_code_and_name(staff_api, venue_staff):
    response = staff_api.post(
        LAYOUTS,
        {"code": " cabaret ", "name": " Cabaret ", "description": "Round tables, open front."},
        format="json",
    )

    assert response.status_code == 201
    layout = LayoutType.objects.get(code="CABARET")
    assert (layout.name, layout.description, layout.is_active) == (
        "Cabaret",
        "Round tables, open front.",
        True,
    )
    assert layout.updated_by == venue_staff
    # Added after the existing layouts.
    assert staff_api.get(LAYOUTS).data[-1]["code"] == "CABARET"
    assert AuditLog.objects.filter(
        actor=venue_staff, allowed=True, action="POST /api/layouts/"
    ).exists()


@pytest.mark.django_db
def test_s3_91_01_ac1_a_new_layout_can_be_used_by_venues_events_and_bookings(
    api, venue_staff, organiser, coordinator, venue
):
    api.force_authenticate(venue_staff)
    api.post(LAYOUTS, {"code": "CABARET", "name": "Cabaret"}, format="json")

    venue_response = api.patch(
        f"{VENUES}{venue.pk}/", {"layouts": ["CABARET", "THEATRE"]}, format="json"
    )
    assert venue_response.status_code == 200
    assert venue_response.data["layouts"] == ["THEATRE", "CABARET"]
    assert venue_response.data["layout_labels"] == ["Theatre", "Cabaret"]

    api.force_authenticate(organiser)
    event_response = api.post(EVENTS, {"name": "Gala", "required_layout": "CABARET"}, format="json")
    assert event_response.status_code == 201
    assert EventRequest.objects.get(pk=event_response.data["id"]).required_layout == "CABARET"

    event = make_event(organiser, status=EventStatus.APPROVED, coordinator=coordinator)
    booking = book(event, venue, coordinator, "CABARET")
    assert VenueBooking.objects.get(pk=booking.pk).layout == "CABARET"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload, field",
    [
        ({"code": "", "name": "Cabaret"}, "code"),
        ({"code": "1CABARET", "name": "Cabaret"}, "code"),
        ({"code": "CAB ARET", "name": "Cabaret"}, "code"),
        ({"code": "C", "name": "Cabaret"}, "code"),
        ({"code": "A" * 21, "name": "Cabaret"}, "code"),
        ({"code": "THEATRE", "name": "Another theatre"}, "code"),
        ({"code": "CABARET", "name": ""}, "name"),
        ({"code": "CABARET", "name": "   "}, "name"),
        ({"code": "CABARET", "name": "theatre"}, "name"),
        ({"code": "CABARET"}, "name"),
        ({"name": "Cabaret"}, "code"),
    ],
)
def test_s3_91_01_an_invalid_or_duplicate_layout_is_refused(staff_api, payload, field):
    before = LayoutType.objects.count()

    response = staff_api.post(LAYOUTS, payload, format="json")

    assert response.status_code == 400
    assert field in response.data
    assert LayoutType.objects.count() == before


# S3-SCRUM-91-02 - AC2: renames show everywhere; the code never changes. ------


@pytest.mark.django_db
def test_s3_91_02_ac2_a_rename_is_shown_everywhere_the_layout_is_used(
    staff_api, venue, coordinator, organiser
):
    response = staff_api.patch(
        layout_url("THEATRE"),
        {"name": "Lecture theatre", "description": "Tiered rows facing a stage."},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["code"] == "THEATRE"
    assert staff_api.get(f"{VENUES}{venue.pk}/").data["layout_labels"] == ["Lecture theatre"]
    staff_api.force_authenticate(coordinator)
    search = staff_api.get("/api/venues/search/", {"layout": "THEATRE"}).data["results"]
    layout_check = next(c for c in search[0]["criteria"] if c["key"] == "layout")
    assert layout_check["message"] == "Required layout: Lecture theatre."
    # Stored references keep the code, so nothing else had to change.
    venue.refresh_from_db()
    assert venue.layouts == ["THEATRE"]


@pytest.mark.django_db
def test_s3_91_02_ac2_the_code_cannot_change(staff_api):
    response = staff_api.patch(layout_url("THEATRE"), {"code": "LECTURE"}, format="json")

    assert response.status_code == 400
    assert "code" in response.data
    assert LayoutType.objects.filter(code="THEATRE").exists()
    assert not LayoutType.objects.filter(code="LECTURE").exists()


@pytest.mark.django_db
def test_s3_91_02_resending_the_same_code_with_a_rename_is_accepted(staff_api):
    response = staff_api.patch(
        layout_url("THEATRE"), {"code": "theatre", "name": "Lecture theatre"}, format="json"
    )

    assert response.status_code == 200
    assert LayoutType.objects.get(code="THEATRE").name == "Lecture theatre"


@pytest.mark.django_db
def test_s3_91_02_a_rename_cannot_take_another_layouts_name(staff_api):
    response = staff_api.patch(layout_url("THEATRE"), {"name": "BANQUET"}, format="json")

    assert response.status_code == 400
    assert LayoutType.objects.get(code="THEATRE").name == "Theatre"


# S3-SCRUM-91-03 - AC3: delete unused layouts; refuse in-use ones, retire them. -


@pytest.mark.django_db
def test_s3_91_03_ac3_a_layout_nothing_uses_is_deleted(staff_api, venue_staff):
    add_layout()

    response = staff_api.delete(layout_url("CABARET"))

    assert response.status_code == 204
    assert not LayoutType.objects.filter(code="CABARET").exists()
    assert AuditLog.objects.filter(
        actor=venue_staff, allowed=True, action="DELETE /api/layouts/CABARET/"
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("user_of_layout", ["venue", "event", "booking"])
def test_s3_91_03_ac3_a_layout_in_use_cannot_be_deleted_and_can_be_retired(
    staff_api, organiser, coordinator, venue, user_of_layout
):
    add_layout()
    if user_of_layout == "venue":
        make_venue(name="Ballroom", layouts=["CABARET"])
    elif user_of_layout == "event":
        make_event(organiser, required_layout="CABARET")
    else:
        event = make_event(organiser, status=EventStatus.APPROVED, coordinator=coordinator)
        book(event, venue, coordinator, "CABARET")

    refused = staff_api.delete(layout_url("CABARET"))

    assert refused.status_code == 409
    assert refused.data["can_retire"] is True
    expected_usage = {"venues": 0, "event_requests": 0, "venue_bookings": 0}
    expected_usage[
        {"venue": "venues", "event": "event_requests", "booking": "venue_bookings"}[user_of_layout]
    ] = 1
    assert refused.data["usage"] == expected_usage
    assert LayoutType.objects.filter(code="CABARET").exists()

    retired = staff_api.post(layout_url("CABARET", "retire/"))

    assert retired.status_code == 200
    assert retired.data["is_active"] is False
    assert LayoutType.objects.get(code="CABARET").is_active is False


@pytest.mark.django_db
def test_s3_91_03_a_retired_layout_keeps_its_name_on_records_that_use_it(staff_api):
    add_layout()
    ballroom = make_venue(name="Ballroom", layouts=["BANQUET", "CABARET"])

    staff_api.post(layout_url("CABARET", "retire/"))

    detail = staff_api.get(f"{VENUES}{ballroom.pk}/").data
    assert detail["layouts"] == ["BANQUET", "CABARET"]
    assert detail["layout_labels"] == ["Banquet", "Cabaret"]
    assert staff_api.delete(layout_url("CABARET")).status_code == 409


@pytest.mark.django_db
def test_s3_91_03_a_retired_layout_can_be_reinstated(staff_api):
    add_layout(is_active=False)

    response = staff_api.post(layout_url("CABARET", "reinstate/"))

    assert response.status_code == 200
    assert LayoutType.objects.get(code="CABARET").is_active is True


@pytest.mark.django_db
def test_s3_91_03_the_active_list_leaves_out_retired_layouts(staff_api):
    add_layout(is_active=False)

    all_codes = [row["code"] for row in staff_api.get(LAYOUTS).data]
    active_codes = [row["code"] for row in staff_api.get(LAYOUTS, {"active": "true"}).data]

    assert "CABARET" in all_codes
    assert "CABARET" not in active_codes


# S3-SCRUM-91-04 - AC4: retired and unknown layouts cannot be chosen. ---------


@pytest.mark.django_db
@pytest.mark.parametrize("code", ["CABARET", "NO_SUCH_LAYOUT"])
def test_s3_91_04_ac4_venues_cannot_choose_a_retired_or_unknown_layout(staff_api, venue, code):
    add_layout(is_active=False)

    created = staff_api.post(
        VENUES, {"name": "New Room", "capacity": 20, "layouts": [code]}, format="json"
    )
    updated = staff_api.patch(f"{VENUES}{venue.pk}/", {"layouts": [code]}, format="json")

    assert created.status_code == 400 and "layouts" in created.data
    assert updated.status_code == 400 and "layouts" in updated.data
    assert not Venue.objects.filter(name="New Room").exists()
    venue.refresh_from_db()
    assert venue.layouts == ["THEATRE"]


@pytest.mark.django_db
@pytest.mark.parametrize("code", ["CABARET", "NO_SUCH_LAYOUT"])
def test_s3_91_04_ac4_event_requests_cannot_choose_a_retired_or_unknown_layout(
    signed_in_organiser, organiser, code
):
    add_layout(is_active=False)
    draft = make_event(organiser, required_layout="THEATRE")

    created = signed_in_organiser.post(
        EVENTS, {"name": "Gala", "required_layout": code}, format="json"
    )
    updated = signed_in_organiser.patch(
        f"{EVENTS}{draft.pk}/", {"required_layout": code}, format="json"
    )

    assert created.status_code == 400 and "required_layout" in created.data
    assert updated.status_code == 400 and "required_layout" in updated.data
    assert not EventRequest.objects.filter(name="Gala").exists()
    draft.refresh_from_db()
    assert draft.required_layout == "THEATRE"


@pytest.mark.django_db
@pytest.mark.parametrize("code", ["CABARET", "NO_SUCH_LAYOUT"])
def test_s3_91_04_ac4_bookings_cannot_choose_a_retired_or_unknown_layout(
    organiser, coordinator, venue, code
):
    add_layout(is_active=False)
    event = make_event(organiser, status=EventStatus.APPROVED, coordinator=coordinator)

    with pytest.raises(BookingValidationError) as raised:
        book(event, venue, coordinator, code)

    assert "layout" in raised.value.errors
    assert not VenueBooking.objects.exists()


@pytest.mark.django_db
def test_s3_91_04_records_already_using_a_retired_layout_can_still_be_edited(
    venue_staff, signed_in_organiser, organiser
):
    # Separate clients: the shared ``api`` client is already signed in as the organiser.
    staff_api = APIClient()
    staff_api.force_authenticate(venue_staff)
    add_layout()
    ballroom = make_venue(name="Ballroom", layouts=["CABARET"])
    draft = make_event(organiser, required_layout="CABARET")
    LayoutType.objects.filter(code="CABARET").update(is_active=False)

    venue_edit = staff_api.patch(
        f"{VENUES}{ballroom.pk}/",
        {"layouts": ["CABARET", "BANQUET"], "capacity": 90},
        format="json",
    )
    event_edit = signed_in_organiser.patch(
        f"{EVENTS}{draft.pk}/", {"required_layout": "CABARET", "name": "Gala"}, format="json"
    )

    assert venue_edit.status_code == 200
    assert venue_edit.data["layouts"] == ["BANQUET", "CABARET"]
    assert event_edit.status_code == 200
    # Removing it is fine; adding it back afterwards is refused.
    staff_api.patch(f"{VENUES}{ballroom.pk}/", {"layouts": ["BANQUET"]}, format="json")
    again = staff_api.patch(f"{VENUES}{ballroom.pk}/", {"layouts": ["CABARET"]}, format="json")
    assert again.status_code == 400


@pytest.mark.django_db
def test_s3_91_04_venue_search_refuses_an_unknown_layout(api, coordinator):
    api.force_authenticate(coordinator)

    assert api.get(VENUES, {"layout": "NO_SUCH_LAYOUT"}).status_code == 400
    assert api.get("/api/venues/search/", {"layout": "NO_SUCH_LAYOUT"}).status_code == 400


# S3-SCRUM-91-05 - AC5: Venue Staff write; internal users and Organisers read. --


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["coordinator", "lead", "tech_staff", "organiser", "attendee"])
def test_s3_91_05_ac5_only_venue_staff_can_change_the_catalogue(api, request, role):
    add_layout()
    user = request.getfixturevalue(role)
    api.force_authenticate(user)

    attempts = [
        api.post(LAYOUTS, {"code": "BOOTH", "name": "Booth"}, format="json"),
        api.patch(layout_url("CABARET"), {"name": "Renamed"}, format="json"),
        api.delete(layout_url("CABARET")),
        api.post(layout_url("CABARET", "retire/")),
    ]

    assert [r.status_code for r in attempts] == [403, 403, 403, 403]
    layout = LayoutType.objects.get(code="CABARET")
    assert (layout.name, layout.is_active) == ("Cabaret", True)
    assert not LayoutType.objects.filter(code="BOOTH").exists()
    assert AuditLog.objects.filter(actor=user, allowed=False).count() == 4


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["venue_staff", "coordinator", "lead", "tech_staff", "organiser"])
def test_s3_91_05_ac5_internal_users_and_organisers_can_read_the_list(api, request, role):
    api.force_authenticate(request.getfixturevalue(role))

    response = api.get(LAYOUTS)

    assert response.status_code == 200
    assert len(response.data) == 5
    assert api.get(layout_url("THEATRE")).data["name"] == "Theatre"


@pytest.mark.django_db
def test_s3_91_05_ac5_attendees_and_anonymous_users_cannot_read_the_list(api, attendee):
    assert api.get(LAYOUTS).status_code == 403

    api.force_authenticate(attendee)
    assert api.get(LAYOUTS).status_code == 403
    assert AuditLog.objects.filter(actor=attendee, allowed=False).exists()


# Seed migration - existing records stay readable. ---------------------------


@pytest.mark.django_db
def test_the_seed_migration_keeps_an_unexpected_stored_code_as_a_retired_layout(organiser):
    Venue.objects.create(name="Old Room", capacity=10, layouts=["U_SHAPE", "THEATRE"])
    make_event(organiser, required_layout="HOLLOW_SQUARE")
    seed = import_module("apps.venues.migrations.0006_seed_layout_catalogue").seed

    seed(django_apps, None)
    seed(django_apps, None)  # running it again changes nothing

    assert LayoutType.objects.filter(code="THEATRE").count() == 1
    u_shape = LayoutType.objects.get(code="U_SHAPE")
    assert (u_shape.name, u_shape.is_active) == ("U Shape", False)
    assert LayoutType.objects.get(code="HOLLOW_SQUARE").name == "Hollow Square"


# Races - real PostgreSQL connections; no dangling layout references. -------


@pytest.mark.django_db(transaction=True)
def test_a_delete_waits_for_a_concurrent_selection_and_then_refuses(venue_staff):
    add_layout()
    selected = Signal()

    def select_and_save():
        close_old_connections()
        try:
            with transaction.atomic():
                claim_layouts(["CABARET"])
                selected.set()
                time.sleep(1)  # the delete is now waiting on this selection
                Venue.objects.create(name="Ballroom", capacity=50, layouts=["CABARET"])
        finally:
            close_old_connections()

    def delete():
        close_old_connections()
        try:
            selected.wait(timeout=10)
            client = APIClient()
            client.force_authenticate(User.objects.get(pk=venue_staff.pk))
            return client.delete(layout_url("CABARET")).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(select_and_save)
        deleting = pool.submit(delete)
        saving.result(timeout=30)
        status = deleting.result(timeout=30)

    assert status == 409
    assert LayoutType.objects.filter(code="CABARET").exists()
    assert Venue.objects.get(name="Ballroom").layouts == ["CABARET"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("change", ["delete", "retire"])
def test_a_selection_waits_for_a_concurrent_delete_or_retire_and_then_refuses(change):
    add_layout()
    locked = Signal()

    def change_layout():
        close_old_connections()
        try:
            with transaction.atomic():
                layout = LayoutType.objects.select_for_update().get(code="CABARET")
                locked.set()
                time.sleep(1)  # the selection is now waiting on this change
                if change == "delete":
                    layout.delete()
                else:
                    layout.is_active = False
                    layout.save(update_fields=["is_active"])
        finally:
            close_old_connections()

    def select():
        close_old_connections()
        try:
            locked.wait(timeout=10)
            with transaction.atomic():
                claim_layouts(["CABARET"])
            return "selected"
        except LayoutChoiceError as exc:
            return exc.message
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        changing = pool.submit(change_layout)
        selecting = pool.submit(select)
        changing.result(timeout=30)
        outcome = selecting.result(timeout=30)

    expected = "Unknown layout: CABARET." if change == "delete" else "Retired layout: Cabaret."
    assert outcome.startswith(expected)
