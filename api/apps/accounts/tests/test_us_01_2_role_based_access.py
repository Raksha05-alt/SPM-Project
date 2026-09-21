"""US-01.2 - Access restricted by role and relationship to an event."""

import pytest

from apps.core.models import AuditLog


@pytest.mark.django_db
def test_ac1_an_organiser_cannot_open_another_organisations_event(
    api, other_organiser, complete_draft
):
    api.force_authenticate(other_organiser)

    response = api.get(f"/api/events/{complete_draft.pk}/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_ac2_an_attendee_cannot_see_internal_planning_information(api, attendee, submitted_event):
    api.force_authenticate(attendee)

    assert api.get(f"/api/events/{submitted_event.pk}/").status_code == 403
    assert api.get("/api/events/").status_code == 403


@pytest.mark.django_db
def test_ac3_a_role_cannot_reach_a_restricted_url_by_entering_it_directly(
    api, venue_staff, submitted_event
):
    api.force_authenticate(venue_staff)

    assert api.get("/api/events/queue/").status_code == 403
    assert api.get(f"/api/events/{submitted_event.pk}/").status_code == 403


@pytest.mark.django_db
def test_ac4_every_refusal_is_recorded_with_the_user_the_action_and_the_time(
    api, other_organiser, complete_draft
):
    assert AuditLog.objects.filter(allowed=False).count() == 0
    api.force_authenticate(other_organiser)

    api.get(f"/api/events/{complete_draft.pk}/")

    entry = AuditLog.objects.filter(allowed=False).get()
    assert entry.actor == other_organiser
    assert str(complete_draft.pk) == entry.object_id
    assert "GET" in entry.action
    assert entry.created_at is not None
    assert "another client organisation" in entry.detail
