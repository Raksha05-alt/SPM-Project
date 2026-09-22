import pytest

from apps.core.statuses import EventStatus


@pytest.mark.django_db
def test_coordinator_cannot_read_edit_or_delete_a_draft(signed_in_coordinator, complete_draft):
    url = f"/api/events/{complete_draft.pk}/"
    assert signed_in_coordinator.get(url).status_code == 403
    assert signed_in_coordinator.patch(url, {"name": "Changed"}).status_code == 403
    assert signed_in_coordinator.delete(url).status_code == 403


@pytest.mark.django_db
def test_other_organisation_cannot_list_edit_or_delete_draft(api, other_organiser, complete_draft):
    api.force_authenticate(other_organiser)
    url = f"/api/events/{complete_draft.pk}/"
    assert api.get("/api/events/").data == []
    assert api.patch(url, {"name": "Changed"}).status_code == 403
    assert api.delete(url).status_code == 403


@pytest.mark.django_db
def test_saving_cannot_submit_or_reassign_a_draft(signed_in_organiser, other_organiser):
    response = signed_in_organiser.post("/api/events/", {
        "status": "SUBMITTED", "organisation": other_organiser.organisation_id,
        "created_by": other_organiser.pk,
    }, format="json")
    assert response.status_code == 201
    assert response.data["status"] == EventStatus.DRAFT
    assert response.data["organisation"] != other_organiser.organisation_id
    assert response.data["submitted_at"] is None


@pytest.mark.django_db
def test_submission_action_is_not_in_this_slice(signed_in_organiser, complete_draft):
    assert signed_in_organiser.post(f"/api/events/{complete_draft.pk}/submit/").status_code == 404
