"""SCRUM-62 (US-09.3) - compare availability across venues for a period."""

import pytest

from apps.core.statuses import EventStatus
from apps.venues.tests.helpers import block, book, iso
from conftest import future_at, make_event, make_venue

COMPARE = "/api/venues/availability/"


def compare(api, start, end):
    return api.get(COMPARE, {"start": iso(start), "end": iso(end)})


@pytest.mark.django_db
def test_ac1_each_venues_status_for_the_period_is_shown_together(signed_in_coordinator, organiser):
    free = make_venue(name="A Free")
    partly = make_venue(name="B Partly")
    book(
        make_event(organiser, status=EventStatus.PLANNING),
        partly,
        future_at(4, 10),
        future_at(4, 11),
    )

    response = compare(signed_in_coordinator, future_at(4, 9), future_at(4, 12))

    assert response.status_code == 200
    rows = {row["venue_name"]: row for row in response.data["venues"]}
    assert rows[free.name]["overall"] == "AVAILABLE"
    assert rows[partly.name]["overall"] == "PARTIAL"
    assert len(rows[partly.name]["segments"]) == 3


@pytest.mark.django_db
def test_ac2_venues_blocked_for_the_whole_period_are_distinguished_from_partly_available(
    signed_in_coordinator,
):
    whole = make_venue(name="Whole")
    part = make_venue(name="Part")
    block(whole, future_at(4, 0), future_at(5, 0))
    block(part, future_at(4, 10), future_at(4, 11))

    response = compare(signed_in_coordinator, future_at(4, 9), future_at(4, 12))

    rows = {row["venue_name"]: row for row in response.data["venues"]}
    assert rows["Whole"]["overall"] == "BLOCKED"
    assert rows["Whole"]["overall_label"] == "Blocked for the whole period"
    assert rows["Part"]["overall"] == "PARTIAL"
    assert rows["Part"]["overall_label"] == "Partly available"


@pytest.mark.django_db
def test_ac3_no_venue_available_is_stated_clearly(signed_in_coordinator):
    block(make_venue(name="Only Room"), future_at(4, 0), future_at(5, 0))

    response = compare(signed_in_coordinator, future_at(4, 9), future_at(4, 12))

    assert response.data["none_available"] is True
    assert response.data["message"] == "No venue is available at any time in this period."
    assert len(response.data["venues"]) == 1


@pytest.mark.django_db
def test_ac3_with_no_venues_at_all_the_message_is_still_shown(signed_in_coordinator):
    response = compare(signed_in_coordinator, future_at(4, 9), future_at(4, 12))

    assert response.data["venues"] == []
    assert response.data["none_available"] is True


@pytest.mark.django_db
def test_ac3_when_something_is_available_there_is_no_warning(signed_in_coordinator, venue):
    response = compare(signed_in_coordinator, future_at(4, 9), future_at(4, 12))

    assert response.data["none_available"] is False
    assert response.data["message"] == ""


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["attendee", "organiser"])
def test_ac4_the_comparison_respects_access_rights(api, request, venue, fixture_name):
    api.force_authenticate(request.getfixturevalue(fixture_name))

    response = compare(api, future_at(4, 9), future_at(4, 12))

    assert response.status_code == 403
