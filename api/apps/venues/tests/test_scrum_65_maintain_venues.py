"""SCRUM-65 (US-08.1) - maintain venue records."""

import pytest
from django.utils import timezone

from apps.core.models import AuditLog
from apps.venues.models import Venue
from conftest import make_venue

VENUES = "/api/venues/"

NEW_VENUE = {
    "name": "Skyline Room",
    "location": "Level 30, Tower One",
    "capacity": 80,
    "facilities": ["Projector", "Hearing loop"],
    "layouts": ["BOARDROOM", "CLASSROOM"],
    "wheelchair_access": True,
    "accessibility_notes": "Step-free access from lift lobby B.",
    "opens_at": "08:00",
    "closes_at": "22:00",
    "operating_days": [0, 1, 2, 3, 4],
}


@pytest.mark.django_db
def test_ac1_venue_staff_record_every_venue_detail(signed_in_venue_staff, venue_staff):
    response = signed_in_venue_staff.post(VENUES, NEW_VENUE, format="json")

    assert response.status_code == 201
    venue = Venue.objects.get(name="Skyline Room")
    assert venue.location == "Level 30, Tower One"
    assert venue.capacity == 80
    assert venue.facilities == ["Projector", "Hearing loop"]
    assert venue.layouts == ["CLASSROOM", "BOARDROOM"]
    assert venue.wheelchair_access is True
    assert venue.accessibility_notes.startswith("Step-free")
    assert f"{venue.opens_at:%H:%M}-{venue.closes_at:%H:%M}" == "08:00-22:00"
    assert venue.operating_days == [0, 1, 2, 3, 4]
    assert venue.created_by == venue_staff


@pytest.mark.django_db
def test_ac2_an_update_is_saved_with_the_user_and_timestamp(
    signed_in_venue_staff, venue_staff, venue
):
    before = timezone.now()

    response = signed_in_venue_staff.patch(
        f"{VENUES}{venue.pk}/", {"capacity": 180, "location": "Level 3"}, format="json"
    )

    assert response.status_code == 200
    venue.refresh_from_db()
    assert venue.capacity == 180
    assert venue.updated_by == venue_staff
    assert venue.updated_at >= before
    assert response.data["updated_by_name"] == "Vera Venue"
    assert AuditLog.objects.filter(
        actor=venue_staff, allowed=True, object_type="Venue", object_id=str(venue.pk)
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("capacity", [0, -5])
def test_ac3_a_zero_or_negative_capacity_is_blocked_with_a_reason(
    signed_in_venue_staff, venue, capacity
):
    created = signed_in_venue_staff.post(VENUES, {**NEW_VENUE, "capacity": capacity}, format="json")
    updated = signed_in_venue_staff.patch(
        f"{VENUES}{venue.pk}/", {"capacity": capacity}, format="json"
    )

    assert created.status_code == 400
    assert "capacity" in created.data
    assert updated.status_code == 400
    venue.refresh_from_db()
    assert venue.capacity == 150


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["coordinator", "tech_staff"])
def test_ac4_internal_staff_who_are_not_venue_staff_cannot_create_or_edit(
    api, request, venue, fixture_name
):
    user = request.getfixturevalue(fixture_name)
    api.force_authenticate(user)

    created = api.post(VENUES, NEW_VENUE, format="json")
    updated = api.patch(f"{VENUES}{venue.pk}/", {"capacity": 10}, format="json")

    assert created.status_code == 403
    assert updated.status_code == 403
    assert not Venue.objects.filter(name="Skyline Room").exists()
    venue.refresh_from_db()
    assert venue.capacity == 150
    assert AuditLog.objects.filter(actor=user, allowed=False).count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["organiser", "attendee"])
def test_ac4_external_users_cannot_create_venues(api, request, fixture_name):
    api.force_authenticate(request.getfixturevalue(fixture_name))

    response = api.post(VENUES, NEW_VENUE, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_venues_cannot_be_deleted_through_the_api(signed_in_venue_staff, venue):
    response = signed_in_venue_staff.delete(f"{VENUES}{venue.pk}/")

    assert response.status_code == 405
    assert Venue.objects.filter(pk=venue.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,value",
    [
        ("operating_days", [7]),
        ("operating_days", "weekdays"),
        ("facilities", "Projector"),
        ("facilities", [1, 2]),
        ("layouts", ["IGLOO"]),
    ],
)
def test_malformed_venue_details_are_refused(signed_in_venue_staff, field, value):
    response = signed_in_venue_staff.post(VENUES, {**NEW_VENUE, field: value}, format="json")

    assert response.status_code == 400
    assert field in response.data


@pytest.mark.django_db
def test_closing_time_must_follow_opening_time(signed_in_venue_staff):
    response = signed_in_venue_staff.post(
        VENUES, {**NEW_VENUE, "opens_at": "18:00", "closes_at": "09:00"}, format="json"
    )

    assert response.status_code == 400
    assert "closes_at" in response.data


@pytest.mark.django_db
def test_venue_names_are_unique(signed_in_venue_staff):
    make_venue(name="Skyline Room")

    response = signed_in_venue_staff.post(VENUES, NEW_VENUE, format="json")

    assert response.status_code == 400
    assert "name" in response.data
