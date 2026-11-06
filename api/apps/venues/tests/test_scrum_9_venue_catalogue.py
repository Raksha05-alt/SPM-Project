"""SCRUM-9 - As Venue Staff, I want to see all venue information, so that I can
provide accurate venue information when handling venue requests.

Depends on SCRUM-65 (venue records).
"""

import datetime

import pytest

from apps.core.models import AuditLog
from apps.venues.tests.conftest import make_venue

VENUES = "/api/venues/"


def complete_venue(**overrides):
    data = {
        "name": "Harbour Hall",
        "location": "Level 2, Marina Wing",
        "capacity": 200,
        "facilities": ["Projector", "Stage"],
        "layouts": ["THEATRE", "BANQUET"],
        "wheelchair_access": True,
        "accessibility_notes": "Step-free entrance.",
        "opens_at": datetime.time(8),
        "closes_at": datetime.time(22),
        "operating_days": [0, 1, 2, 3, 4],
    }
    data.update(overrides)
    return make_venue(**data)


# AC1 -------------------------------------------------------------------------


@pytest.mark.django_db
def test_ac1_opening_the_catalogue_lists_every_venue(signed_in_venue_staff):
    complete_venue(name="Skyline Room")
    complete_venue(name="Garden Pavilion", in_service=False)
    complete_venue(name="Harbour Hall")

    response = signed_in_venue_staff.get(VENUES)

    assert response.status_code == 200
    assert [row["name"] for row in response.data] == [
        "Garden Pavilion",
        "Harbour Hall",
        "Skyline Room",
    ]


@pytest.mark.django_db
def test_ac1_an_empty_catalogue_is_an_empty_list(signed_in_venue_staff):
    response = signed_in_venue_staff.get(VENUES)

    assert response.status_code == 200
    assert response.data == []


# AC2 -------------------------------------------------------------------------


@pytest.mark.django_db
def test_ac2_selecting_a_venue_shows_every_described_detail(signed_in_venue_staff):
    venue = complete_venue()

    response = signed_in_venue_staff.get(f"{VENUES}{venue.pk}/")

    assert response.status_code == 200
    data = response.data
    assert data["location"] == "Level 2, Marina Wing"
    assert data["capacity"] == 200
    assert data["facilities"] == ["Projector", "Stage"]
    assert data["wheelchair_access"] is True
    assert data["accessibility_notes"] == "Step-free entrance."
    assert data["layout_labels"] == ["Theatre", "Banquet"]
    assert data["operating_hours"] == "08:00-22:00 (Mon, Tue, Wed, Thu, Fri)"


@pytest.mark.django_db
def test_ac2_a_venue_that_does_not_exist_is_not_found(signed_in_venue_staff):
    assert signed_in_venue_staff.get(f"{VENUES}9999/").status_code == 404


# AC3 -------------------------------------------------------------------------


@pytest.mark.django_db
def test_ac3_a_complete_venue_has_nothing_missing(signed_in_venue_staff):
    venue = complete_venue()

    response = signed_in_venue_staff.get(f"{VENUES}{venue.pk}/")

    assert response.data["missing_information"] == []


@pytest.mark.django_db
def test_ac3_every_missing_detail_is_named(signed_in_venue_staff):
    venue = make_venue(name="Annex", location="", facilities=[], layouts=[])

    response = signed_in_venue_staff.get(f"{VENUES}{venue.pk}/")

    assert response.data["missing_information"] == [
        "Location",
        "Facilities",
        "Accessibility information",
        "Supported room layouts",
        "Operating hours",
    ]
    assert response.data["operating_hours"] is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides,missing",
    [
        ({"location": ""}, "Location"),
        ({"facilities": []}, "Facilities"),
        ({"wheelchair_access": None, "accessibility_notes": ""}, "Accessibility information"),
        ({"layouts": []}, "Supported room layouts"),
        ({"opens_at": None}, "Operating hours"),
        ({"closes_at": None}, "Operating hours"),
        ({"operating_days": []}, "Operating hours"),
    ],
)
def test_ac3_each_detail_is_identified_when_missing(signed_in_venue_staff, overrides, missing):
    venue = complete_venue(**overrides)

    response = signed_in_venue_staff.get(f"{VENUES}{venue.pk}/")

    assert response.data["missing_information"] == [missing]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        {"wheelchair_access": False, "accessibility_notes": ""},
        {"wheelchair_access": None, "accessibility_notes": "Ramp at the east gate."},
    ],
)
def test_ac3_either_kind_of_accessibility_information_counts(signed_in_venue_staff, overrides):
    venue = complete_venue(**overrides)

    response = signed_in_venue_staff.get(f"{VENUES}{venue.pk}/")

    assert "Accessibility information" not in response.data["missing_information"]


@pytest.mark.django_db
def test_ac3_missing_information_is_also_shown_in_the_list(signed_in_venue_staff):
    make_venue(name="Annex", location="")

    response = signed_in_venue_staff.get(VENUES)

    assert "Location" in response.data[0]["missing_information"]


# AC4 -------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("in_service,label", [(True, "In service"), (False, "Out of service")])
def test_ac4_the_current_operational_status_is_shown(signed_in_venue_staff, in_service, label):
    venue = complete_venue(in_service=in_service)

    shown = signed_in_venue_staff.get(f"{VENUES}{venue.pk}/")
    listed = signed_in_venue_staff.get(VENUES)

    assert shown.data["operational_status"] == label
    assert listed.data[0]["operational_status"] == label


@pytest.mark.django_db
def test_ac4_the_status_follows_a_change_made_by_venue_staff(signed_in_venue_staff):
    venue = complete_venue()

    signed_in_venue_staff.patch(f"{VENUES}{venue.pk}/", {"in_service": False}, format="json")
    response = signed_in_venue_staff.get(f"{VENUES}{venue.pk}/")

    assert response.data["operational_status"] == "Out of service"


# AC5 -------------------------------------------------------------------------


@pytest.mark.django_db
def test_ac5_an_attendee_is_refused_the_catalogue_and_it_is_recorded(api, attendee):
    venue = complete_venue()
    api.force_authenticate(attendee)

    listed = api.get(VENUES)
    shown = api.get(f"{VENUES}{venue.pk}/")

    assert listed.status_code == 403
    assert shown.status_code == 403
    assert "Harbour Hall" not in str(listed.data)
    assert AuditLog.objects.filter(actor=attendee, allowed=False).count() == 2


@pytest.mark.django_db
def test_ac5_an_anonymous_visitor_is_refused_the_catalogue(api):
    complete_venue()

    assert api.get(VENUES).status_code == 403
