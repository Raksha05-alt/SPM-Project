"""SCRUM-57 (US-06.3) - filter events by status."""

import pytest

from apps.core.statuses import EventStatus
from conftest import make_event

EVENTS = "/api/events/"


@pytest.fixture
def mixed_events(organiser, coordinator):
    return {
        status: make_event(organiser, status=status, coordinator=coordinator, name=status.title())
        for status in (
            EventStatus.SUBMITTED,
            EventStatus.APPROVED,
            EventStatus.PLANNING,
            EventStatus.CONFIRMED,
        )
    }


def ids(response):
    return {row["id"] for row in response.data}


@pytest.mark.django_db
def test_ac1_filtering_by_one_status_lists_only_that_status(signed_in_coordinator, mixed_events):
    response = signed_in_coordinator.get(EVENTS, {"status": "PLANNING"})

    assert response.status_code == 200
    assert ids(response) == {mixed_events[EventStatus.PLANNING].pk}


@pytest.mark.django_db
def test_ac1_filtering_by_several_statuses_lists_each_of_them(signed_in_coordinator, mixed_events):
    response = signed_in_coordinator.get(EVENTS, {"status": "approved,planning"})

    assert ids(response) == {
        mixed_events[EventStatus.APPROVED].pk,
        mixed_events[EventStatus.PLANNING].pk,
    }


@pytest.mark.django_db
def test_ac1_the_status_parameter_can_also_be_repeated(signed_in_coordinator, mixed_events):
    response = signed_in_coordinator.get(f"{EVENTS}?status=APPROVED&status=CONFIRMED")

    assert ids(response) == {
        mixed_events[EventStatus.APPROVED].pk,
        mixed_events[EventStatus.CONFIRMED].pk,
    }


@pytest.mark.django_db
def test_ac1_my_assigned_events_and_the_queue_can_be_filtered_too(
    signed_in_coordinator, mixed_events
):
    mine = signed_in_coordinator.get(f"{EVENTS}mine/", {"status": "CONFIRMED"})
    queue = signed_in_coordinator.get(f"{EVENTS}queue/", {"status": "SUBMITTED"})

    assert ids(mine) == {mixed_events[EventStatus.CONFIRMED].pk}
    assert ids(queue) == {mixed_events[EventStatus.SUBMITTED].pk}


@pytest.mark.django_db
def test_ac2_a_filter_that_matches_nothing_returns_an_empty_list(
    signed_in_coordinator, mixed_events
):
    response = signed_in_coordinator.get(EVENTS, {"status": "COMPLETED"})

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_ac3_filtering_for_drafts_never_reveals_a_clients_draft(
    signed_in_coordinator, complete_draft
):
    response = signed_in_coordinator.get(EVENTS, {"status": "DRAFT"})

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_ac3_an_organiser_filter_never_reveals_another_clients_events(
    api, other_organiser, mixed_events
):
    api.force_authenticate(other_organiser)

    response = api.get(EVENTS, {"status": "PLANNING,CONFIRMED"})

    assert response.data == []


@pytest.mark.django_db
def test_ac3_an_attendee_filter_never_reveals_internal_statuses(api, attendee, mixed_events):
    api.force_authenticate(attendee)

    response = api.get(EVENTS, {"status": "PLANNING"})

    assert response.data == []


@pytest.mark.django_db
def test_ac4_clearing_the_filter_returns_the_full_permitted_list(
    signed_in_coordinator, mixed_events
):
    response = signed_in_coordinator.get(EVENTS, {"status": ""})

    assert ids(response) == {event.pk for event in mixed_events.values()}


@pytest.mark.django_db
def test_an_unknown_status_is_reported_rather_than_ignored(signed_in_coordinator, mixed_events):
    response = signed_in_coordinator.get(EVENTS, {"status": "PLANNING,ARCHIVED"})

    assert response.status_code == 400
    assert "ARCHIVED" in str(response.data["status"])
