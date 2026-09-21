"""US-03.1 - Save an event request as a draft."""

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.events.models import EventRequest

EVENTS = "/api/events/"


@pytest.mark.django_db
def test_ac1_saving_stores_the_request_as_a_draft_and_confirms_it(signed_in_organiser):
    response = signed_in_organiser.post(EVENTS, {"name": "Partner briefing"}, format="json")

    assert response.status_code == 201
    assert response.data["status"] == EventStatus.DRAFT
    assert response.data["status_label"] == "Draft"
    assert response.data["id"] is not None


@pytest.mark.django_db
def test_ac2_a_request_with_empty_fields_still_saves(signed_in_organiser):
    response = signed_in_organiser.post(EVENTS, {}, format="json")

    assert response.status_code == 201
    assert response.data["status"] == EventStatus.DRAFT
    assert set(response.data["missing_mandatory_fields"]) == {
        "name",
        "purpose",
        "preferred_start",
        "preferred_end",
        "expected_attendance",
    }


@pytest.mark.django_db
def test_ac3_reopening_a_draft_shows_every_value_unchanged(signed_in_organiser):
    start = timezone.now() + timezone.timedelta(days=21)
    created = signed_in_organiser.post(
        EVENTS,
        {
            "name": "Q4 Engineering Workshop",
            "purpose": "Internal upskilling",
            "expected_attendance": 40,
            "preferred_start": start.isoformat(),
            "accessibility_needs": "Wheelchair access",
        },
        format="json",
    )

    reopened = signed_in_organiser.get(f"{EVENTS}{created.data['id']}/")

    assert reopened.status_code == 200
    assert reopened.data["name"] == "Q4 Engineering Workshop"
    assert reopened.data["purpose"] == "Internal upskilling"
    assert reopened.data["expected_attendance"] == 40
    assert reopened.data["accessibility_needs"] == "Wheelchair access"
    assert reopened.data["preferred_start"] is not None


@pytest.mark.django_db
def test_ac4_a_draft_never_appears_in_the_coordinator_queue(
    signed_in_coordinator, complete_draft, submitted_event
):
    response = signed_in_coordinator.get(f"{EVENTS}queue/")

    assert response.status_code == 200
    ids = [row["id"] for row in response.data]
    assert complete_draft.pk not in ids
    assert submitted_event.pk in ids


@pytest.mark.django_db
def test_ac5_a_user_outside_my_organisation_cannot_open_my_draft(
    api, other_organiser, complete_draft
):
    api.force_authenticate(other_organiser)

    assert api.get(f"{EVENTS}{complete_draft.pk}/").status_code == 403


@pytest.mark.django_db
def test_ac6_deleting_a_draft_removes_it_from_my_list(signed_in_organiser, complete_draft):
    delete = signed_in_organiser.delete(f"{EVENTS}{complete_draft.pk}/")

    assert delete.status_code == 204
    assert not EventRequest.objects.filter(pk=complete_draft.pk).exists()
    assert signed_in_organiser.get(EVENTS).data == []


@pytest.mark.django_db
def test_a_submitted_request_cannot_be_deleted(signed_in_organiser, submitted_event):
    response = signed_in_organiser.delete(f"{EVENTS}{submitted_event.pk}/")

    assert response.status_code == 403
    assert EventRequest.objects.filter(pk=submitted_event.pk).exists()


@pytest.mark.django_db
def test_a_draft_can_be_edited_and_reloaded(signed_in_organiser, incomplete_draft):
    patch = signed_in_organiser.patch(
        f"{EVENTS}{incomplete_draft.pk}/",
        {"name": "Now it has a name", "expected_attendance": 75},
        format="json",
    )

    assert patch.status_code == 200
    assert patch.data["name"] == "Now it has a name"
    assert patch.data["expected_attendance"] == 75
