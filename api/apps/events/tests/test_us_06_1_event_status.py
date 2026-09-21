"""US-06.1 - See an event's current status."""

import pytest
from django.utils import timezone

from apps.core.statuses import INTERNAL_STATUSES, EventStatus
from conftest import make_event

STATUSES = "/api/event-statuses/"


@pytest.mark.django_db
def test_ac1_an_event_shows_its_current_status(signed_in_organiser, complete_draft):
    response = signed_in_organiser.get(f"/api/events/{complete_draft.pk}/")

    assert response.status_code == 200
    assert response.data["status"] == EventStatus.DRAFT
    assert response.data["status_label"] == "Draft"


@pytest.mark.django_db
def test_ac1_status_labels_match_the_product_vocabulary(signed_in_coordinator):
    response = signed_in_coordinator.get(STATUSES)

    assert {entry["value"]: entry["label"] for entry in response.data} == {
        EventStatus.DRAFT: "Draft",
        EventStatus.SUBMITTED: "Submitted",
        EventStatus.UNDER_REVIEW: "Awaiting Clarification",
        EventStatus.APPROVED: "Approved",
        EventStatus.PLANNING: "Planning",
        EventStatus.CONFIRMED: "Confirmed",
        EventStatus.COMPLETED: "Completed",
        EventStatus.CANCELLED: "Cancelled",
        EventStatus.REJECTED: "Rejected",
    }


@pytest.mark.django_db
def test_ac2_a_plain_language_explanation_is_available_for_the_status(
    signed_in_organiser, complete_draft
):
    detail = signed_in_organiser.get(f"/api/events/{complete_draft.pk}/")
    vocabulary = signed_in_organiser.get(STATUSES)

    assert "ConnectSphere cannot see it yet" in detail.data["status_description"]
    assert vocabulary.status_code == 200
    assert all(entry["description"] for entry in vocabulary.data)


@pytest.mark.django_db
def test_ac3_the_date_of_the_most_recent_status_change_is_shown(
    signed_in_organiser, complete_draft
):
    assert complete_draft.status_changed_at is None

    signed_in_organiser.post(f"/api/events/{complete_draft.pk}/submit/")
    response = signed_in_organiser.get(f"/api/events/{complete_draft.pk}/")

    assert response.data["status_changed_at"] is not None


@pytest.mark.django_db
def test_ac4_an_attendee_is_not_shown_internal_planning_statuses(
    api, attendee, coordinator, organiser
):
    changed_at = timezone.now()
    confirmed = make_event(
        organiser,
        status=EventStatus.CONFIRMED,
        status_changed_at=changed_at,
        description="A public partner conference.",
    )
    planning = make_event(organiser, status=EventStatus.PLANNING, name="Still being planned")

    api.force_authenticate(attendee)
    external = api.get(STATUSES)
    attendee_events = api.get("/api/events/")
    confirmed_detail = api.get(f"/api/events/{confirmed.pk}/")
    planning_detail = api.get(f"/api/events/{planning.pk}/")

    api.force_authenticate(coordinator)
    internal = api.get(STATUSES)

    external_values = {entry["value"] for entry in external.data}
    internal_values = {entry["value"] for entry in internal.data}
    assert external_values.isdisjoint(INTERNAL_STATUSES)
    assert external_values == {
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
    }
    assert internal_values == set(EventStatus.values)
    assert attendee_events.status_code == 200
    assert [event["id"] for event in attendee_events.data] == [confirmed.pk]
    assert confirmed_detail.status_code == 200
    assert confirmed_detail.data["status_label"] == "Confirmed"
    assert confirmed_detail.data["status_description"]
    assert confirmed_detail.data["status_changed_at"] is not None
    assert "organisation_name" not in confirmed_detail.data
    assert "coordinator_name" not in confirmed_detail.data
    assert planning_detail.status_code == 403


@pytest.mark.django_db
def test_ac4_an_attendee_cannot_change_a_visible_event(api, attendee, organiser):
    confirmed = make_event(organiser, status=EventStatus.CONFIRMED)
    api.force_authenticate(attendee)

    response = api.patch(
        f"/api/events/{confirmed.pk}/", {"name": "Changed by attendee"}, format="json"
    )

    assert response.status_code == 403
    confirmed.refresh_from_db()
    assert confirmed.name == "Regional Partner Conference"
