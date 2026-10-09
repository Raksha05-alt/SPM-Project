"""SCRUM-71 (US-11.1) - flag venues that do not meet the event's requirements."""

from datetime import time

import pytest

from apps.accounts.models import Role, User
from apps.core.statuses import EventStatus
from conftest import make_event, make_venue


def check(api, venue, event):
    return api.get(f"/api/venues/{venue.pk}/suitability/", {"event": event.pk})


@pytest.fixture
def event(organiser, coordinator):
    return make_event(
        organiser,
        status=EventStatus.APPROVED,
        coordinator=coordinator,
        expected_attendance=120,
        required_layout="THEATRE",
        accessibility_needs="Two wheelchair users",
    )


@pytest.mark.django_db
def test_ac1_attendance_above_capacity_is_flagged_with_the_reason(signed_in_coordinator, event):
    small = make_venue(name="Small", capacity=100)

    response = check(signed_in_coordinator, small, event)

    assert response.data["suitable"] is False
    assert response.data["warnings"] == [
        "Expected attendance of 120 exceeds the venue's capacity of 100."
    ]


@pytest.mark.django_db
def test_ac1_attendance_equal_to_capacity_is_suitable(signed_in_coordinator, event):
    exact = make_venue(name="Exact", capacity=120)

    response = check(signed_in_coordinator, exact, event)

    assert response.data["suitable"] is True


@pytest.mark.django_db
def test_ac2_a_missing_layout_is_flagged_with_the_reason(signed_in_coordinator, event):
    venue = make_venue(name="Classroom only", layouts=["CLASSROOM"])

    response = check(signed_in_coordinator, venue, event)

    assert response.data["warnings"] == ["The venue does not support the Theatre layout."]


@pytest.mark.django_db
def test_ac2_missing_accessibility_is_flagged_with_the_reason(signed_in_coordinator, event):
    venue = make_venue(name="Stairs only", wheelchair_access=False)

    response = check(signed_in_coordinator, venue, event)

    assert response.data["suitable"] is False
    assert "step-free access" in response.data["warnings"][0]


@pytest.mark.django_db
def test_ac3_timing_outside_operating_hours_is_flagged_with_the_reason(
    signed_in_coordinator, event
):
    venue = make_venue(name="Late opener", opens_at=time(12, 0), closes_at=time(20, 0))

    response = check(signed_in_coordinator, venue, event)

    assert response.data["suitable"] is False
    assert response.data["warnings"] == [
        "The event's timing falls outside the venue's operating hours "
        "(12:00-20:00 (Mon, Tue, Wed, Thu, Fri, Sat, Sun))."
    ]


@pytest.mark.django_db
def test_ac3_a_venue_without_recorded_hours_is_flagged(signed_in_coordinator, event):
    venue = make_venue(name="Unknown hours", opens_at=None, closes_at=None)

    response = check(signed_in_coordinator, venue, event)

    assert "not recorded" in response.data["warnings"][0]


@pytest.mark.django_db
def test_ac5_a_venue_meeting_every_requirement_has_no_warnings(signed_in_coordinator, event, venue):
    response = check(signed_in_coordinator, venue, event)

    assert response.status_code == 200
    assert response.data["suitable"] is True
    assert response.data["warnings"] == []
    assert all(c["matches"] for c in response.data["checks"])


@pytest.mark.django_db
def test_an_out_of_service_venue_is_unsuitable(signed_in_coordinator, event):
    venue = make_venue(name="Closed", is_active=False)

    response = check(signed_in_coordinator, venue, event)

    assert response.data["warnings"] == ["Closed is out of service."]


@pytest.mark.django_db
def test_requirements_the_event_does_not_state_are_not_checked(
    signed_in_coordinator, organiser, coordinator
):
    plain = make_event(organiser, status=EventStatus.APPROVED, coordinator=coordinator)
    venue = make_venue(name="Bare", layouts=[], wheelchair_access=None)

    response = check(signed_in_coordinator, venue, plain)

    criteria = [c["criterion"] for c in response.data["checks"]]
    assert criteria == ["Operational status", "Capacity", "Operating hours"]


@pytest.mark.django_db
def test_suitability_needs_an_event(signed_in_coordinator, venue):
    response = signed_in_coordinator.get(f"/api/venues/{venue.pk}/suitability/")

    assert response.status_code == 400


@pytest.mark.django_db
def test_a_clients_draft_cannot_be_checked(signed_in_coordinator, venue, complete_draft):
    response = check(signed_in_coordinator, venue, complete_draft)

    assert response.status_code == 403


@pytest.mark.django_db
def test_only_coordinators_check_suitability(api, venue_staff, venue, event):
    api.force_authenticate(venue_staff)

    response = check(api, venue, event)

    assert response.status_code == 403


def test_facility_requirements_are_reported_when_missing(db):
    from apps.venues.suitability import assess, unmet

    venue = make_venue(name="Basic", facilities=["Projector"])

    reasons = unmet(assess(venue, {"facilities": ["projector", "Stage"]}))

    assert reasons == ["Missing facilities: Stage."]
    assert User.objects.filter(role=Role.EVENT_COORDINATOR).count() == 0
