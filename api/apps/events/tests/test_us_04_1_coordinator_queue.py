"""US-04.1 - View the queue of submitted event requests."""

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from conftest import make_event

QUEUE = "/api/events/queue/"


@pytest.mark.django_db
def test_ac1_the_queue_shows_everything_a_coordinator_needs_to_triage(
    signed_in_coordinator, submitted_event
):
    response = signed_in_coordinator.get(QUEUE)

    assert response.status_code == 200
    row = response.data[0]
    for field in (
        "name",
        "organisation_name",
        "preferred_start",
        "expected_attendance",
        "status",
        "status_label",
        "status_description",
        "submitted_at",
    ):
        assert field in row
    assert row["organisation_name"] == "Acme Pte Ltd"
    assert row["status_description"]


@pytest.mark.django_db
def test_ac2_the_queue_is_ordered_oldest_submission_first(signed_in_coordinator, organiser):
    now = timezone.now()
    newer = make_event(
        organiser,
        status=EventStatus.SUBMITTED,
        name="Newer",
        submitted_at=now - timezone.timedelta(hours=1),
    )
    older = make_event(
        organiser,
        status=EventStatus.SUBMITTED,
        name="Older",
        submitted_at=now - timezone.timedelta(days=4),
    )

    response = signed_in_coordinator.get(QUEUE)

    ids = [row["id"] for row in response.data]
    assert ids.index(older.pk) < ids.index(newer.pk)


@pytest.mark.django_db
def test_ac3_drafts_and_rejected_requests_are_not_in_the_queue(
    signed_in_coordinator, organiser, complete_draft
):
    rejected = make_event(organiser, status=EventStatus.REJECTED, name="Rejected one")
    kept = make_event(organiser, status=EventStatus.SUBMITTED, name="Kept")

    response = signed_in_coordinator.get(QUEUE)

    ids = [row["id"] for row in response.data]
    assert complete_draft.pk not in ids
    assert rejected.pk not in ids
    assert kept.pk in ids


@pytest.mark.django_db
def test_ac4_only_a_coordinator_can_open_the_queue(api, organiser, attendee, submitted_event):
    api.force_authenticate(organiser)
    assert api.get(QUEUE).status_code == 403

    api.force_authenticate(attendee)
    assert api.get(QUEUE).status_code == 403


@pytest.mark.django_db
def test_ac5_an_empty_queue_shows_an_empty_list_rather_than_an_error(signed_in_coordinator):
    response = signed_in_coordinator.get(QUEUE)

    assert response.status_code == 200
    assert response.data == []
