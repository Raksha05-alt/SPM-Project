"""SCRUM-68 (US-10.2) - shortlist venues from the search results."""

import pytest

from apps.accounts.models import Role, User
from apps.core.statuses import EventStatus
from apps.venues.models import VenueShortlist
from apps.venues.tests.helpers import block, book
from conftest import PASSWORD, make_event, make_venue


def url(event):
    return f"/api/events/{event.pk}/shortlist/"


@pytest.fixture
def event(organiser, coordinator):
    return make_event(
        organiser,
        status=EventStatus.APPROVED,
        coordinator=coordinator,
        expected_attendance=120,
        required_layout="THEATRE",
    )


@pytest.mark.django_db
def test_ac1_a_shortlisted_venue_is_saved_against_the_event_and_shown_on_return(
    signed_in_coordinator, coordinator, event, venue
):
    added = signed_in_coordinator.post(url(event), {"venue": venue.pk}, format="json")
    again = signed_in_coordinator.post(url(event), {"venue": venue.pk}, format="json")

    assert added.status_code == 201
    assert again.status_code == 201
    entry = VenueShortlist.objects.get(event=event)
    assert entry.added_by == coordinator
    listed = signed_in_coordinator.get(url(event))
    assert [row["venue_name"] for row in listed.data] == ["Harbour Hall"]


@pytest.mark.django_db
def test_ac2_a_removed_venue_no_longer_appears(signed_in_coordinator, event, venue):
    signed_in_coordinator.post(url(event), {"venue": venue.pk}, format="json")

    response = signed_in_coordinator.delete(f"{url(event)}{venue.pk}/")

    assert response.status_code == 204
    assert signed_in_coordinator.get(url(event)).data == []


@pytest.mark.django_db
def test_ac3_each_venue_shows_the_criteria_it_satisfied_and_any_it_did_not(
    signed_in_coordinator, event
):
    small = make_venue(name="Small", capacity=80, layouts=["THEATRE"])
    signed_in_coordinator.post(url(event), {"venue": small.pk}, format="json")

    [row] = signed_in_coordinator.get(url(event)).data

    assert "Room layout" in row["satisfied"]
    assert row["not_satisfied"] == [
        {
            "criterion": "Capacity",
            "reason": "Expected attendance of 120 exceeds the venue's capacity of 80.",
        }
    ]


@pytest.mark.django_db
def test_ac4_a_venue_blocked_later_is_flagged_as_no_longer_available(
    signed_in_coordinator, event, venue
):
    signed_in_coordinator.post(url(event), {"venue": venue.pk}, format="json")
    before = signed_in_coordinator.get(url(event)).data[0]
    block(venue, event.preferred_start, event.preferred_end)

    after = signed_in_coordinator.get(url(event)).data[0]

    assert before["no_longer_available"] is False
    assert after["no_longer_available"] is True


@pytest.mark.django_db
def test_ac4_a_venue_booked_by_another_event_is_flagged(
    signed_in_coordinator, organiser, event, venue
):
    signed_in_coordinator.post(url(event), {"venue": venue.pk}, format="json")
    book(make_event(organiser, status=EventStatus.CONFIRMED), venue)

    assert signed_in_coordinator.get(url(event)).data[0]["no_longer_available"] is True


@pytest.mark.django_db
def test_ac4_this_events_own_booking_does_not_count_against_it(signed_in_coordinator, event, venue):
    signed_in_coordinator.post(url(event), {"venue": venue.pk}, format="json")
    book(event, venue)

    assert signed_in_coordinator.get(url(event)).data[0]["no_longer_available"] is False


@pytest.mark.django_db
def test_ac4_an_out_of_service_venue_is_flagged(signed_in_coordinator, event):
    closed = make_venue(name="Closed", is_active=False)
    signed_in_coordinator.post(url(event), {"venue": closed.pk}, format="json")

    assert signed_in_coordinator.get(url(event)).data[0]["no_longer_available"] is True


@pytest.mark.django_db
def test_only_the_assigned_coordinator_changes_the_shortlist(api, event, venue):
    other = User.objects.create_user(
        username="o@connectsphere.example",
        email="o@connectsphere.example",
        password=PASSWORD,
        role=Role.EVENT_COORDINATOR,
    )
    api.force_authenticate(other)

    added = api.post(url(event), {"venue": venue.pk}, format="json")
    removed = api.delete(f"{url(event)}{venue.pk}/")

    assert added.status_code == 403
    assert removed.status_code == 403
    assert api.get(url(event)).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["organiser", "venue_staff"])
def test_other_roles_cannot_open_the_shortlist(api, request, event, fixture_name):
    api.force_authenticate(request.getfixturevalue(fixture_name))

    assert api.get(url(event)).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("venue_value", [None, "abc", 999999])
def test_an_unknown_venue_cannot_be_shortlisted(signed_in_coordinator, event, venue_value):
    response = signed_in_coordinator.post(url(event), {"venue": venue_value}, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_removing_a_venue_that_is_not_shortlisted_is_not_found(signed_in_coordinator, event, venue):
    response = signed_in_coordinator.delete(f"{url(event)}{venue.pk}/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_an_event_without_dates_is_only_checked_for_service(
    signed_in_coordinator, organiser, coordinator, venue
):
    undated = make_event(
        organiser,
        status=EventStatus.SUBMITTED,
        coordinator=coordinator,
        preferred_start=None,
        preferred_end=None,
    )
    signed_in_coordinator.post(url(undated), {"venue": venue.pk}, format="json")

    assert signed_in_coordinator.get(url(undated)).data[0]["no_longer_available"] is False
