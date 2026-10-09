"""SCRUM-78 (US-19.2) - review a change request and assess its impact."""

import pytest

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.events.models import ChangeRequest, ChangeRequestStatus, EventChangeLog
from apps.events.tests.change_helpers import DAY, confirmed_event
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import RegistrationStatus
from apps.venues.tests.helpers import book, make_user
from conftest import make_event


@pytest.fixture
def setup(organiser, coordinator):
    return confirmed_event(organiser, coordinator)


def change_for(event, **proposed):
    return ChangeRequest.objects.create(
        event=event, requested_by=event.created_by, description="Please change", **proposed
    )


def detail(client, change):
    return client.get(f"/api/change-requests/{change.pk}/").data


@pytest.mark.django_db
def test_ac1_affected_bookings_reservations_and_registrations_are_listed(
    signed_in_coordinator, setup
):
    event = setup[0]
    change = change_for(
        event, proposed_start=event.preferred_start + DAY, proposed_end=event.preferred_end + DAY
    )

    impact = detail(signed_in_coordinator, change)["impact"]

    assert [b["venue"] for b in impact["venue_bookings"]] == ["Harbour Hall"]
    assert impact["venue_bookings"][0]["new_start"] == event.preferred_start + DAY
    assert [e["equipment"] for e in impact["equipment"]] == ["Projector"]
    assert impact["equipment"][0]["available_in_new_period"] == 5
    assert impact["registrations"] == {"registered": 1, "waitlisted": 0, "issues": []}
    assert impact["has_impact"] is True
    assert impact["message"] is None


@pytest.mark.django_db
def test_ac2_attendance_beyond_capacity_flags_the_venue(signed_in_coordinator, setup):
    change = change_for(setup[0], proposed_attendance=400)

    [booking] = detail(signed_in_coordinator, change)["impact"]["venue_bookings"]

    assert booking["potentially_unsuitable"] is True
    assert booking["issues"] == ["Expected attendance of 400 exceeds the venue's capacity of 150."]


@pytest.mark.django_db
def test_ac2_attendance_below_the_registered_count_is_mentioned(signed_in_coordinator, setup):
    event = setup[0]
    from apps.registrations.tests.conftest import fill

    fill(event, 3)
    change = change_for(event, proposed_attendance=2)

    registrations = detail(signed_in_coordinator, change)["impact"]["registrations"]

    assert registrations["registered"] == 4
    assert "more than the new expected attendance of 2" in registrations["issues"][0]


@pytest.mark.django_db
def test_ac3_a_date_that_clashes_with_another_booking_is_identified(
    signed_in_coordinator, organiser, coordinator, setup
):
    event, booking, _, _ = setup
    rival = make_event(
        organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Gala"
    )
    book(rival, booking.venue, event.preferred_start + DAY, event.preferred_end + DAY)
    change = change_for(
        event, proposed_start=event.preferred_start + DAY, proposed_end=event.preferred_end + DAY
    )

    [row] = detail(signed_in_coordinator, change)["impact"]["venue_bookings"]

    assert [c["event_name"] for c in row["conflicts"]] == ["Gala"]


@pytest.mark.django_db
def test_ac3_equipment_short_in_the_new_period_is_identified(
    signed_in_coordinator, organiser, coordinator, setup
):
    from apps.equipment.tests.conftest import hold

    event, _, item, _ = setup
    rival = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    hold(
        rival,
        item.equipment_type,
        4,
        start=event.preferred_start + DAY,
        end=event.preferred_end + DAY,
    )
    change = change_for(
        event, proposed_start=event.preferred_start + DAY, proposed_end=event.preferred_end + DAY
    )

    [row] = detail(signed_in_coordinator, change)["impact"]["equipment"]

    assert row["issues"] == ["Only 1 available in the new period; 3 needed."]


@pytest.mark.django_db
def test_ac4_no_impact_is_stated_clearly(signed_in_coordinator, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    change = change_for(event, proposed_attendance=90)

    impact = detail(signed_in_coordinator, change)["impact"]

    assert impact["has_impact"] is False
    assert impact["message"] == "This change does not affect any existing arrangements."


@pytest.mark.django_db
def test_ac4_withdrawn_registrations_do_not_count_as_impact(
    signed_in_coordinator, organiser, coordinator
):
    from apps.registrations.tests.conftest import enrol, make_attendee

    event = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    enrol(event, make_attendee("gone@example.com"), status=RegistrationStatus.WITHDRAWN)
    change = change_for(event, proposed_attendance=80)

    assert detail(signed_in_coordinator, change)["impact"]["registrations"] is None


@pytest.mark.django_db
@pytest.mark.parametrize(("verb", "status"), [("approve", "APPROVED"), ("reject", "REJECTED")])
def test_ac5_a_decision_records_a_reason_and_tells_the_client(
    signed_in_coordinator, coordinator, organiser, setup, verb, status
):
    change = change_for(setup[0], proposed_attendance=130)

    response = signed_in_coordinator.post(
        f"/api/change-requests/{change.pk}/{verb}/", {"reason": "Fits the plan"}, format="json"
    )

    assert response.status_code == 200, response.data
    change.refresh_from_db()
    assert (change.status, change.decision_reason, change.decided_by) == (
        status,
        "Fits the plan",
        coordinator,
    )
    note = Notification.objects.get(recipient=organiser, kind=NotificationKind.CHANGE_DECIDED)
    assert "Reason: Fits the plan" in note.message
    assert EventChangeLog.objects.filter(event=setup[0], field="Change request").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"reason": "  "}])
def test_ac5_a_decision_needs_a_reason(signed_in_coordinator, setup, payload):
    change = change_for(setup[0], proposed_attendance=130)

    response = signed_in_coordinator.post(
        f"/api/change-requests/{change.pk}/approve/", payload, format="json"
    )

    assert response.status_code == 400
    change.refresh_from_db()
    assert change.status == ChangeRequestStatus.PENDING


@pytest.mark.django_db
def test_approving_updates_the_event(signed_in_coordinator, setup):
    event = setup[0]
    change = change_for(event, proposed_attendance=130, proposed_layout="CLASSROOM")

    signed_in_coordinator.post(
        f"/api/change-requests/{change.pk}/approve/", {"reason": "OK"}, format="json"
    )

    event.refresh_from_db()
    assert (event.expected_attendance, event.required_layout) == (130, "CLASSROOM")


@pytest.mark.django_db
def test_rejecting_leaves_the_event_as_it_was(signed_in_coordinator, setup):
    event = setup[0]
    change = change_for(event, proposed_attendance=130)

    signed_in_coordinator.post(
        f"/api/change-requests/{change.pk}/reject/", {"reason": "No"}, format="json"
    )

    event.refresh_from_db()
    assert event.expected_attendance == 120


@pytest.mark.django_db
def test_a_decided_request_cannot_be_decided_again(signed_in_coordinator, setup):
    change = change_for(setup[0], status=ChangeRequestStatus.APPROVED)

    response = signed_in_coordinator.post(
        f"/api/change-requests/{change.pk}/reject/", {"reason": "x"}, format="json"
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_a_change_cannot_be_applied_to_a_cancelled_event(signed_in_coordinator, setup):
    event = setup[0]
    change = change_for(event, proposed_attendance=100)
    event.status = EventStatus.CANCELLED
    event.save()

    response = signed_in_coordinator.post(
        f"/api/change-requests/{change.pk}/approve/", {"reason": "x"}, format="json"
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_only_the_assigned_coordinator_decides(api, signed_in_organiser, setup):
    change = change_for(setup[0], proposed_attendance=100)
    approve = f"/api/change-requests/{change.pk}/approve/"

    assert signed_in_organiser.post(approve, {"reason": "x"}).status_code == 403
    api.force_authenticate(make_user("c2@connectsphere.example", Role.EVENT_COORDINATOR))
    assert api.post(approve, {"reason": "x"}).status_code == 403


@pytest.mark.django_db
def test_the_client_sees_the_request_without_the_internal_impact(signed_in_organiser, setup):
    change = change_for(setup[0], proposed_attendance=100)

    data = detail(signed_in_organiser, change)

    assert data["status_display"] == "Pending"
    assert "impact" not in data
