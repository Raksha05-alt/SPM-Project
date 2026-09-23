"""US-02.2 - Submit an event request."""

import pytest

from apps.core.statuses import EventStatus
from apps.events.models import EventStatusHistory


def submit_url(event):
    return f"/api/events/{event.pk}/submit/"


@pytest.mark.django_db
def test_ac1_a_complete_draft_moves_from_draft_to_submitted(signed_in_organiser, complete_draft):
    assert complete_draft.status == EventStatus.DRAFT

    response = signed_in_organiser.post(submit_url(complete_draft))

    assert response.status_code == 200
    assert response.data["status"] == EventStatus.SUBMITTED
    complete_draft.refresh_from_db()
    assert complete_draft.status == EventStatus.SUBMITTED


@pytest.mark.django_db
def test_ac2_missing_mandatory_information_blocks_submission_and_identifies_each_item(
    signed_in_organiser, incomplete_draft
):
    response = signed_in_organiser.post(submit_url(incomplete_draft))

    assert response.status_code == 400
    assert set(response.data["missing_fields"]) == {
        "name",
        "purpose",
        "preferred_start",
        "preferred_end",
        "expected_attendance",
    }
    incomplete_draft.refresh_from_db()
    assert incomplete_draft.status == EventStatus.DRAFT


@pytest.mark.django_db
def test_ac3_a_successful_submission_is_confirmed_and_timestamped(
    signed_in_organiser, complete_draft
):
    assert complete_draft.submitted_at is None

    response = signed_in_organiser.post(submit_url(complete_draft))

    assert response.status_code == 200
    assert response.data["submitted_at"] is not None
    assert response.data["status_label"] == "Submitted"
    history = EventStatusHistory.objects.get(event=complete_draft)
    assert history.from_status == EventStatus.DRAFT
    assert history.to_status == EventStatus.SUBMITTED


@pytest.mark.django_db
def test_ac4_a_submitted_request_is_read_only_to_the_client(signed_in_organiser, complete_draft):
    signed_in_organiser.post(submit_url(complete_draft))

    edit = signed_in_organiser.patch(
        f"/api/events/{complete_draft.pk}/", {"name": "Renamed after submission"}, format="json"
    )

    assert edit.status_code == 403
    complete_draft.refresh_from_db()
    assert complete_draft.name == "Regional Partner Conference"
    assert signed_in_organiser.get(f"/api/events/{complete_draft.pk}/").status_code == 200


@pytest.mark.django_db
def test_a_request_cannot_be_submitted_twice(signed_in_organiser, complete_draft):
    assert signed_in_organiser.post(submit_url(complete_draft)).status_code == 200

    second = signed_in_organiser.post(submit_url(complete_draft))

    assert second.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("field,value", [
    ("expected_attendance", 0),
    ("name", "   "),
    ("preferred_start", "past"),
    ("preferred_end", "past"),
])
def test_invalid_saved_values_block_submission(signed_in_organiser, complete_draft, field, value):
    from django.utils import timezone
    if value == "past":
        value = timezone.now() - timezone.timedelta(days=1)
    setattr(complete_draft, field, value)
    complete_draft.save()
    response = signed_in_organiser.post(submit_url(complete_draft))
    assert response.status_code == 400
    assert field in response.data or field in response.data.get("missing_fields", [])
    complete_draft.refresh_from_db()
    assert complete_draft.status == EventStatus.DRAFT
    assert complete_draft.submitted_at is None


@pytest.mark.django_db
def test_another_organisation_cannot_submit(api, other_organiser, complete_draft):
    api.force_authenticate(other_organiser)
    assert api.post(submit_url(complete_draft)).status_code == 404
    complete_draft.refresh_from_db()
    assert complete_draft.status == EventStatus.DRAFT
