"""SCRUM-65 - As Venue Staff, I want to create and update venue records, so that
the catalogue reflects the venues ConnectSphere actually operates.
"""

import pytest
from django.utils import timezone

from apps.core.models import AuditLog
from apps.venues.models import Venue
from apps.venues.tests.conftest import make_venue

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


# AC1 -------------------------------------------------------------------------


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
    assert venue.accessibility_notes == "Step-free access from lift lobby B."
    assert f"{venue.opens_at:%H:%M}-{venue.closes_at:%H:%M}" == "08:00-22:00"
    assert venue.operating_days == [0, 1, 2, 3, 4]
    assert venue.created_by == venue_staff
    assert venue.in_service is True


@pytest.mark.django_db
def test_ac1_the_response_describes_the_venue_in_staff_terms(signed_in_venue_staff):
    response = signed_in_venue_staff.post(VENUES, NEW_VENUE, format="json")

    assert response.data["layout_labels"] == ["Classroom", "Boardroom"]
    assert response.data["operating_hours"] == "08:00-22:00 (Mon, Tue, Wed, Thu, Fri)"
    assert response.data["created_by_name"] == "Vera Venue"


@pytest.mark.django_db
def test_ac1_only_name_and_capacity_are_required(signed_in_venue_staff):
    response = signed_in_venue_staff.post(VENUES, {"name": "Annex", "capacity": 10}, format="json")

    assert response.status_code == 201
    venue = Venue.objects.get(name="Annex")
    assert venue.operating_days == [0, 1, 2, 3, 4, 5, 6]
    assert response.data["operating_hours"] is None


@pytest.mark.django_db
def test_ac1_a_venue_needs_a_name_and_a_capacity(signed_in_venue_staff):
    response = signed_in_venue_staff.post(VENUES, {"location": "Somewhere"}, format="json")

    assert response.status_code == 400
    assert "name" in response.data
    assert response.data["capacity"] == ["Enter the venue's maximum capacity."]


# AC2 -------------------------------------------------------------------------


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
    assert venue.location == "Level 3"
    assert venue.updated_by == venue_staff
    assert venue.updated_at >= before
    assert response.data["updated_by_name"] == "Vera Venue"
    assert response.data["updated_at"] is not None


@pytest.mark.django_db
def test_ac2_every_create_and_update_is_written_to_the_audit_log(
    signed_in_venue_staff, venue_staff, venue
):
    signed_in_venue_staff.post(VENUES, NEW_VENUE, format="json")
    signed_in_venue_staff.patch(f"{VENUES}{venue.pk}/", {"capacity": 120}, format="json")

    created = Venue.objects.get(name="Skyline Room")
    rows = AuditLog.objects.filter(actor=venue_staff, allowed=True, object_type="Venue")
    assert set(rows.values_list("object_id", flat=True)) == {str(created.pk), str(venue.pk)}


@pytest.mark.django_db
def test_ac2_a_full_update_replaces_the_record(signed_in_venue_staff, venue_staff, venue):
    response = signed_in_venue_staff.put(
        f"{VENUES}{venue.pk}/", {**NEW_VENUE, "name": "Harbour Hall"}, format="json"
    )

    assert response.status_code == 200
    venue.refresh_from_db()
    assert venue.capacity == 80
    assert venue.updated_by == venue_staff


@pytest.mark.django_db
def test_ac2_updating_a_venue_that_does_not_exist_is_not_found(signed_in_venue_staff):
    response = signed_in_venue_staff.patch(f"{VENUES}9999/", {"capacity": 5}, format="json")

    assert response.status_code == 404


# AC3 -------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("capacity", [0, -1, -5])
def test_ac3_a_zero_or_negative_capacity_is_blocked_with_a_reason(
    signed_in_venue_staff, venue, capacity
):
    created = signed_in_venue_staff.post(VENUES, {**NEW_VENUE, "capacity": capacity}, format="json")
    updated = signed_in_venue_staff.patch(
        f"{VENUES}{venue.pk}/", {"capacity": capacity}, format="json"
    )

    assert created.status_code == 400
    assert created.data["capacity"] == ["Capacity must be at least one person."]
    assert updated.status_code == 400
    assert updated.data["capacity"] == ["Capacity must be at least one person."]
    assert not Venue.objects.filter(name="Skyline Room").exists()
    venue.refresh_from_db()
    assert venue.capacity == 150


@pytest.mark.django_db
def test_ac3_a_capacity_of_one_is_the_smallest_accepted(signed_in_venue_staff):
    response = signed_in_venue_staff.post(VENUES, {**NEW_VENUE, "capacity": 1}, format="json")

    assert response.status_code == 201


# AC4 -------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["coordinator", "tech_staff", "organiser", "attendee"])
def test_ac4_anyone_but_venue_staff_is_refused_create_and_edit(api, request, venue, fixture_name):
    user = request.getfixturevalue(fixture_name)
    api.force_authenticate(user)

    created = api.post(VENUES, NEW_VENUE, format="json")
    patched = api.patch(f"{VENUES}{venue.pk}/", {"capacity": 10}, format="json")
    replaced = api.put(f"{VENUES}{venue.pk}/", NEW_VENUE, format="json")

    assert (created.status_code, patched.status_code, replaced.status_code) == (403, 403, 403)
    assert not Venue.objects.filter(name="Skyline Room").exists()
    venue.refresh_from_db()
    assert venue.capacity == 150
    assert AuditLog.objects.filter(actor=user, allowed=False).count() == 3


@pytest.mark.django_db
def test_ac4_an_anonymous_caller_is_refused_and_recorded(api, venue):
    response = api.post(VENUES, NEW_VENUE, format="json")

    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=None, allowed=False).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["coordinator", "tech_staff", "venue_staff"])
def test_ac4_internal_staff_can_read_the_venue_records(api, request, venue, fixture_name):
    api.force_authenticate(request.getfixturevalue(fixture_name))

    listed = api.get(VENUES)
    shown = api.get(f"{VENUES}{venue.pk}/")

    assert listed.status_code == 200
    assert [row["name"] for row in listed.data] == ["Harbour Hall"]
    assert shown.data["capacity"] == 150


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["organiser", "attendee"])
def test_ac4_clients_and_attendees_cannot_read_venue_records(api, request, venue, fixture_name):
    api.force_authenticate(request.getfixturevalue(fixture_name))

    assert api.get(VENUES).status_code == 403
    assert api.get(f"{VENUES}{venue.pk}/").status_code == 403


@pytest.mark.django_db
def test_venues_cannot_be_deleted_through_the_api(signed_in_venue_staff, venue):
    response = signed_in_venue_staff.delete(f"{VENUES}{venue.pk}/")

    assert response.status_code == 405
    assert Venue.objects.filter(pk=venue.pk).exists()


# Validation of the other recorded details ------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,value",
    [
        ("operating_days", [7]),
        ("operating_days", "weekdays"),
        ("operating_days", ["Mon"]),
        ("facilities", "Projector"),
        ("facilities", [1, 2]),
        ("layouts", ["IGLOO"]),
        ("layouts", "THEATRE"),
    ],
)
def test_malformed_venue_details_are_refused(signed_in_venue_staff, field, value):
    response = signed_in_venue_staff.post(VENUES, {**NEW_VENUE, field: value}, format="json")

    assert response.status_code == 400
    assert field in response.data


@pytest.mark.django_db
def test_facilities_are_trimmed_and_deduplicated(signed_in_venue_staff):
    response = signed_in_venue_staff.post(
        VENUES,
        {**NEW_VENUE, "facilities": [" Projector ", "projector", "", "Stage"]},
        format="json",
    )

    assert response.data["facilities"] == ["Projector", "Stage"]


@pytest.mark.django_db
@pytest.mark.parametrize("opens,closes", [("18:00", "09:00"), ("09:00", "09:00")])
def test_closing_time_must_follow_opening_time(signed_in_venue_staff, opens, closes):
    response = signed_in_venue_staff.post(
        VENUES, {**NEW_VENUE, "opens_at": opens, "closes_at": closes}, format="json"
    )

    assert response.status_code == 400
    assert response.data["closes_at"] == ["Closing time must be after opening."]


@pytest.mark.django_db
def test_closing_time_is_checked_against_the_saved_opening_time(signed_in_venue_staff, venue):
    signed_in_venue_staff.patch(f"{VENUES}{venue.pk}/", {"opens_at": "10:00"}, format="json")

    response = signed_in_venue_staff.patch(
        f"{VENUES}{venue.pk}/", {"closes_at": "08:00"}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_venue_names_are_unique(signed_in_venue_staff):
    make_venue(name="Skyline Room")

    response = signed_in_venue_staff.post(VENUES, NEW_VENUE, format="json")

    assert response.status_code == 400
    assert "name" in response.data
