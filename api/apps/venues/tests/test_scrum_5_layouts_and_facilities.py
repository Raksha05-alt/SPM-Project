"""SCRUM-5 (US-08.3) - record supported room layouts and facilities."""

import pytest

from apps.core.statuses import EventStatus
from apps.venues.models import BookingStatus, VenueBooking
from conftest import make_event

VENUES = "/api/venues/"


def booking(event, venue, layout, status=BookingStatus.APPROVED):
    return VenueBooking.objects.create(
        event=event,
        venue=venue,
        start=event.preferred_start,
        end=event.preferred_end,
        attendance=100,
        layout=layout,
        status=status,
    )


@pytest.mark.django_db
def test_ac1_layouts_are_selected_from_the_agreed_list(signed_in_venue_staff, venue):
    response = signed_in_venue_staff.patch(
        f"{VENUES}{venue.pk}/",
        {"layouts": ["BANQUET", "EXHIBITION", "BANQUET"], "confirm_layout_removal": True},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["layouts"] == ["BANQUET", "EXHIBITION"]
    assert response.data["layout_labels"] == ["Banquet", "Exhibition"]


@pytest.mark.django_db
def test_ac1_a_layout_outside_the_agreed_list_is_refused(signed_in_venue_staff, venue):
    response = signed_in_venue_staff.patch(
        f"{VENUES}{venue.pk}/", {"layouts": ["CABARET"]}, format="json"
    )

    assert response.status_code == 400
    assert "layouts" in response.data


@pytest.mark.django_db
def test_ac2_facilities_including_video_and_accessibility_are_recorded(
    signed_in_venue_staff, venue
):
    response = signed_in_venue_staff.patch(
        f"{VENUES}{venue.pk}/",
        {
            "facilities": [" Video conferencing ", "Hearing loop", "video conferencing"],
            "wheelchair_access": False,
            "accessibility_notes": "Accessible toilet on level 1.",
        },
        format="json",
    )

    assert response.status_code == 200
    venue.refresh_from_db()
    assert venue.facilities == ["Video conferencing", "Hearing loop"]
    assert venue.wheelchair_access is False
    assert venue.accessibility_notes == "Accessible toilet on level 1."


@pytest.mark.django_db
def test_ac4_removing_a_layout_used_by_a_confirmed_booking_warns_which_bookings(
    signed_in_venue_staff, organiser, venue
):
    event = make_event(organiser, status=EventStatus.CONFIRMED, name="Gala Dinner")
    confirmed = booking(event, venue, "THEATRE")

    response = signed_in_venue_staff.patch(
        f"{VENUES}{venue.pk}/", {"layouts": ["CLASSROOM"]}, format="json"
    )

    assert response.status_code == 409
    [affected] = response.data["affected_bookings"]
    assert affected["id"] == confirmed.pk
    assert affected["event_name"] == "Gala Dinner"
    assert affected["layout"] == "Theatre"
    venue.refresh_from_db()
    assert "THEATRE" in venue.layouts


@pytest.mark.django_db
def test_ac4_confirming_the_removal_saves_it_and_flags_the_booking_for_review(
    signed_in_venue_staff, organiser, venue
):
    event = make_event(organiser, status=EventStatus.CONFIRMED)
    confirmed = booking(event, venue, "THEATRE")

    response = signed_in_venue_staff.patch(
        f"{VENUES}{venue.pk}/",
        {"layouts": ["CLASSROOM"], "confirm_layout_removal": True},
        format="json",
    )

    assert response.status_code == 200
    venue.refresh_from_db()
    assert venue.layouts == ["CLASSROOM"]
    confirmed.refresh_from_db()
    assert confirmed.review_required is True
    assert "Theatre" in confirmed.review_reason


@pytest.mark.django_db
def test_ac4_layouts_used_only_by_pending_or_past_bookings_do_not_warn(
    signed_in_venue_staff, organiser, venue
):
    from django.utils import timezone

    event = make_event(organiser, status=EventStatus.PLANNING)
    booking(event, venue, "THEATRE", status=BookingStatus.PENDING)
    past = booking(event, venue, "THEATRE")
    past.start = timezone.now() - timezone.timedelta(days=3)
    past.end = past.start + timezone.timedelta(hours=2)
    past.save()

    response = signed_in_venue_staff.patch(
        f"{VENUES}{venue.pk}/", {"layouts": ["CLASSROOM"]}, format="json"
    )

    assert response.status_code == 200
