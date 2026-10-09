"""SCRUM-9 (US-08.2) - view the venue catalogue."""

import pytest
from django.utils import timezone

from apps.venues.models import VenueBlock
from conftest import make_venue

VENUES = "/api/venues/"


@pytest.mark.django_db
def test_ac1_the_catalogue_lists_connectspheres_venues(signed_in_venue_staff):
    make_venue(name="Harbour Hall")
    make_venue(name="Atrium")

    response = signed_in_venue_staff.get(VENUES)

    assert response.status_code == 200
    assert [row["name"] for row in response.data] == ["Atrium", "Harbour Hall"]


@pytest.mark.django_db
def test_ac2_a_selected_venue_shows_all_of_its_details(signed_in_venue_staff, venue):
    response = signed_in_venue_staff.get(f"{VENUES}{venue.pk}/")

    data = response.data
    assert data["location"] == "Level 2, Marina Building"
    assert data["capacity"] == 150
    assert data["facilities"] == ["Projector", "Video conferencing"]
    assert data["wheelchair_access"] is True
    assert data["layout_labels"] == ["Theatre", "Classroom"]
    assert data["operating_hours"] == "00:00-23:59 (Mon, Tue, Wed, Thu, Fri, Sat, Sun)"


@pytest.mark.django_db
def test_ac3_missing_information_is_identified_rather_than_left_blank(signed_in_venue_staff):
    sparse = make_venue(
        name="Store Room",
        location="",
        facilities=[],
        layouts=[],
        wheelchair_access=None,
        opens_at=None,
        closes_at=None,
    )

    response = signed_in_venue_staff.get(f"{VENUES}{sparse.pk}/")

    assert response.data["missing_information"] == [
        "Location",
        "Facilities",
        "Supported room layouts",
        "Accessibility information",
        "Operating hours",
    ]
    assert response.data["operating_hours"] is None


@pytest.mark.django_db
def test_ac3_a_complete_venue_reports_nothing_missing(signed_in_venue_staff, venue):
    response = signed_in_venue_staff.get(f"{VENUES}{venue.pk}/")

    assert response.data["missing_information"] == []


@pytest.mark.django_db
def test_ac4_the_current_operational_status_is_shown(signed_in_venue_staff, venue_staff):
    open_venue = make_venue(name="Open")
    closed = make_venue(name="Closed", is_active=False)
    blocked = make_venue(name="Blocked")
    now = timezone.now()
    VenueBlock.objects.create(
        venue=blocked,
        start=now - timezone.timedelta(hours=1),
        end=now + timezone.timedelta(days=1),
        reason="Carpet replacement",
        created_by=venue_staff,
    )

    rows = {row["name"]: row for row in signed_in_venue_staff.get(VENUES).data}

    assert rows[open_venue.name]["operational_status"] == "In service"
    assert rows[closed.name]["operational_status"] == "Out of service"
    assert rows[blocked.name]["operational_status"] == "Blocked"


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["attendee", "organiser"])
def test_ac5_attendees_and_clients_cannot_open_the_catalogue(api, request, venue, fixture_name):
    api.force_authenticate(request.getfixturevalue(fixture_name))

    assert api.get(VENUES).status_code == 403
    assert api.get(f"{VENUES}{venue.pk}/").status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["coordinator", "tech_staff"])
def test_other_internal_staff_can_read_the_catalogue(api, request, venue, fixture_name):
    api.force_authenticate(request.getfixturevalue(fixture_name))

    assert api.get(VENUES).status_code == 200
