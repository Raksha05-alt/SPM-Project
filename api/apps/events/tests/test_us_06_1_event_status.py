"""US-06.1 - See an event's current status."""

import pytest

from apps.core.statuses import INTERNAL_STATUSES, EventStatus

STATUSES = "/api/event-statuses/"


@pytest.mark.django_db
def test_ac1_an_event_shows_its_current_status(signed_in_organiser, complete_draft):
    response = signed_in_organiser.get(f"/api/events/{complete_draft.pk}/")

    assert response.status_code == 200
    assert response.data["status"] == EventStatus.DRAFT
    assert response.data["status_label"] == "Draft"


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
def test_ac4_an_attendee_is_not_shown_internal_planning_statuses(api, attendee, coordinator):
    api.force_authenticate(attendee)
    external = api.get(STATUSES)

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
