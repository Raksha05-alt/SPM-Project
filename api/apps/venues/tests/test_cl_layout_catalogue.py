"""Week 9 clarification - the venue catalogue maintains room layouts, with the
capability to add, edit and delete them; their names are the team's choice.

CL-L-AC1  Venue Staff add a layout, which venues, events and bookings can then use.
CL-L-AC2  Venue Staff rename or describe a layout; its code stays fixed.
CL-L-AC3  An unused layout can be deleted; one in use cannot, but can be retired.
CL-L-AC4  A retired or unknown layout cannot be chosen for anything new.
CL-L-AC5  Only Venue Staff maintain layouts; internal users and clients read them.
"""

import pytest

from apps.events.models import ChangeRequest
from apps.venues.models import LayoutType
from conftest import make_event, make_venue

URL = "/api/layouts/"


@pytest.mark.django_db
def test_the_starter_layouts_are_seeded(signed_in_venue_staff):
    names = [row["name"] for row in signed_in_venue_staff.get(URL).data]

    assert names == ["Banquet", "Boardroom", "Classroom", "Exhibition", "Theatre"]


@pytest.mark.django_db
def test_cl_ac1_staff_add_a_layout_that_venues_and_events_can_use(
    signed_in_venue_staff, api, organiser, venue
):
    created = signed_in_venue_staff.post(
        URL, {"code": "u_shape", "name": "U-shape", "description": "Tables in a U"}, format="json"
    )
    assert created.status_code == 201, created.data
    assert created.data["code"] == "U_SHAPE"

    updated = signed_in_venue_staff.patch(
        f"/api/venues/{venue.pk}/", {"layouts": ["THEATRE", "U_SHAPE"]}, format="json"
    )
    assert updated.status_code == 200, updated.data
    assert updated.data["layout_labels"] == ["Theatre", "U-shape"]

    api.force_authenticate(organiser)
    draft = api.post(
        "/api/events/", {"name": "Workshop", "required_layout": "U_SHAPE"}, format="json"
    )
    assert draft.status_code == 201, draft.data
    assert draft.data["required_layout_label"] == "U-shape"


@pytest.mark.django_db
def test_cl_ac2_staff_rename_a_layout_and_its_label_follows(signed_in_venue_staff, venue):
    theatre = LayoutType.objects.get(code="THEATRE")

    response = signed_in_venue_staff.patch(
        f"{URL}{theatre.pk}/", {"name": "Theatre style"}, format="json"
    )

    assert response.status_code == 200
    assert (
        "Theatre style"
        in signed_in_venue_staff.get(f"/api/venues/{venue.pk}/").data["layout_labels"]
    )


@pytest.mark.django_db
def test_cl_ac2_the_code_cannot_change(signed_in_venue_staff):
    theatre = LayoutType.objects.get(code="THEATRE")

    response = signed_in_venue_staff.patch(f"{URL}{theatre.pk}/", {"code": "STAGE"}, format="json")

    assert response.status_code == 400
    theatre.refresh_from_db()
    assert theatre.code == "THEATRE"


@pytest.mark.django_db
def test_cl_ac3_an_unused_layout_can_be_deleted(signed_in_venue_staff):
    spare = LayoutType.objects.create(code="CABARET", name="Cabaret")

    assert signed_in_venue_staff.delete(f"{URL}{spare.pk}/").status_code == 204
    assert not LayoutType.objects.filter(code="CABARET").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("used_by", ["venue", "event", "change_request"])
def test_cl_ac3_a_layout_in_use_cannot_be_deleted_but_can_be_retired(
    signed_in_venue_staff, organiser, used_by
):
    layout = LayoutType.objects.create(code="CABARET", name="Cabaret")
    if used_by == "venue":
        make_venue(name="Cabaret Room", layouts=["CABARET"])
    elif used_by == "event":
        make_event(organiser, required_layout="CABARET")
    else:
        ChangeRequest.objects.create(
            event=make_event(organiser), description="x", proposed_layout="CABARET"
        )

    refused = signed_in_venue_staff.delete(f"{URL}{layout.pk}/")
    retired = signed_in_venue_staff.patch(f"{URL}{layout.pk}/", {"is_active": False}, format="json")

    assert refused.status_code == 409
    assert "Retire it" in refused.data["detail"]
    assert retired.status_code == 200
    assert LayoutType.objects.get(pk=layout.pk).is_active is False


@pytest.mark.django_db
def test_cl_ac4_a_retired_layout_cannot_be_chosen_again(
    signed_in_venue_staff, api, organiser, venue
):
    LayoutType.objects.filter(code="BANQUET").update(is_active=False)

    venue_response = signed_in_venue_staff.patch(
        f"/api/venues/{venue.pk}/", {"layouts": ["BANQUET"]}, format="json"
    )
    api.force_authenticate(organiser)
    event_response = api.post("/api/events/", {"required_layout": "BANQUET"}, format="json")

    assert venue_response.status_code == 400
    assert event_response.status_code == 400
    assert [row["code"] for row in api.get(URL).data if row["code"] == "BANQUET"] == []


@pytest.mark.django_db
def test_cl_ac4_an_unknown_layout_is_refused_for_a_booking(
    signed_in_coordinator, organiser, coordinator, venue
):
    from apps.core.statuses import EventStatus
    from apps.venues.tests.helpers import booking_payload

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)

    response = signed_in_coordinator.post(
        "/api/venue-bookings/", booking_payload(event, venue, layout="CIRCUS"), format="json"
    )

    assert response.status_code == 400
    assert "layout" in response.data


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["coordinator", "tech_staff", "organiser", "lead"])
def test_cl_ac5_only_venue_staff_maintain_layouts(api, request, role):
    api.force_authenticate(request.getfixturevalue(role))
    theatre = LayoutType.objects.get(code="THEATRE")

    assert api.get(URL).status_code == 200
    assert api.post(URL, {"code": "X", "name": "X"}, format="json").status_code == 403
    assert api.patch(f"{URL}{theatre.pk}/", {"name": "Y"}, format="json").status_code == 403
    assert api.delete(f"{URL}{theatre.pk}/").status_code == 403


@pytest.mark.django_db
def test_cl_ac5_attendees_cannot_read_layouts(api, attendee):
    api.force_authenticate(attendee)

    assert api.get(URL).status_code == 403
