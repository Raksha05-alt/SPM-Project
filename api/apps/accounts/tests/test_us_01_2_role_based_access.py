"""US-01.2 (SCRUM-1) - Access restricted by role and relationship to an event.

One test per acceptance criterion, plus the cases the criteria imply but do not
spell out: an anonymous probe, and an audit write that fails.
"""

import pytest

from apps.core.models import AuditLog

EVENTS = "/api/events/"
AUDIT = "/api/audit/"


# --------------------------------------------------------------------------
# AC1 - an Event Organiser cannot reach another client organisation's event
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_ac1_an_organiser_cannot_open_another_organisations_event(
    api, other_organiser, complete_draft
):
    api.force_authenticate(other_organiser)

    response = api.get(f"{EVENTS}{complete_draft.pk}/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_ac1_another_organisations_event_is_absent_from_my_list(
    api, other_organiser, complete_draft, submitted_event
):
    """Refusing the detail view is not enough if the list view leaks the row."""
    api.force_authenticate(other_organiser)

    response = api.get(EVENTS)

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_ac1_an_organiser_cannot_edit_another_organisations_event(
    api, other_organiser, complete_draft
):
    api.force_authenticate(other_organiser)

    response = api.patch(
        f"{EVENTS}{complete_draft.pk}/", {"name": "Renamed by a stranger"}, format="json"
    )

    assert response.status_code == 403
    complete_draft.refresh_from_db()
    assert complete_draft.name == "Regional Partner Conference"


# --------------------------------------------------------------------------
# AC2 - an Attendee cannot see internal planning information
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_ac2_an_attendee_cannot_see_internal_planning_information(api, attendee, submitted_event):
    api.force_authenticate(attendee)

    assert api.get(f"{EVENTS}{submitted_event.pk}/").status_code == 403
    assert api.get(EVENTS).status_code == 403


@pytest.mark.django_db
def test_ac2_the_audit_log_is_internal_planning_information(api, attendee, organiser):
    """The audit trail records who tried to reach what. External users may not read it."""
    api.force_authenticate(attendee)
    assert api.get(AUDIT).status_code == 403

    api.force_authenticate(organiser)
    assert api.get(AUDIT).status_code == 403


@pytest.mark.django_db
def test_ac2_internal_staff_can_read_the_audit_log(api, coordinator, venue_staff):
    for user in (coordinator, venue_staff):
        api.force_authenticate(user)

        response = api.get(AUDIT)

        assert response.status_code == 200
        assert "results" in response.data


# --------------------------------------------------------------------------
# AC3 - entering an address directly is refused, not partially served
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_ac3_a_role_cannot_reach_a_restricted_url_by_entering_it_directly(
    api, venue_staff, submitted_event
):
    api.force_authenticate(venue_staff)

    assert api.get(f"{EVENTS}queue/").status_code == 403
    assert api.get(f"{EVENTS}{submitted_event.pk}/").status_code == 403


@pytest.mark.django_db
def test_ac3_a_refusal_returns_no_part_of_the_protected_record(
    api, other_organiser, complete_draft
):
    """'Refused rather than partially rendered' - the body must carry no event data."""
    api.force_authenticate(other_organiser)

    response = api.get(f"{EVENTS}{complete_draft.pk}/")

    assert response.status_code == 403
    body = str(response.data)
    assert complete_draft.name not in body
    assert str(complete_draft.expected_attendance) not in body
    assert set(response.data.keys()) == {"detail"}


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_ac3_every_method_is_refused_not_just_reads(api, attendee, submitted_event, method):
    api.force_authenticate(attendee)

    response = getattr(api, method)(f"{EVENTS}{submitted_event.pk}/")

    assert response.status_code == 403


# --------------------------------------------------------------------------
# AC4 - the refused attempt is recorded with the user, the action and the time
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_ac4_every_refusal_is_recorded_with_the_user_the_action_and_the_time(
    api, other_organiser, complete_draft
):
    assert AuditLog.objects.filter(allowed=False).count() == 0
    api.force_authenticate(other_organiser)

    api.get(f"{EVENTS}{complete_draft.pk}/")

    entry = AuditLog.objects.filter(allowed=False).get()
    assert entry.actor == other_organiser
    assert str(complete_draft.pk) == entry.object_id
    assert "GET" in entry.action
    assert entry.created_at is not None
    assert "another client organisation" in entry.detail


@pytest.mark.django_db
def test_ac4_an_anonymous_attempt_is_also_recorded(api, submitted_event):
    """A refused request by someone not signed in is the one most worth recording."""
    response = api.get(f"{EVENTS}{submitted_event.pk}/")

    assert response.status_code == 403
    entry = AuditLog.objects.filter(allowed=False).latest("created_at")
    assert entry.actor is None
    assert entry.detail == "not signed in"
    assert str(submitted_event.pk) in entry.action


@pytest.mark.django_db
def test_ac4_a_refused_read_of_the_audit_log_is_itself_recorded(api, attendee):
    api.force_authenticate(attendee)

    api.get(AUDIT)

    entry = AuditLog.objects.filter(allowed=False).latest("created_at")
    assert entry.actor == attendee
    assert "is external" in entry.detail


@pytest.mark.django_db
def test_ac4_the_recorded_refusal_can_be_read_back_through_the_api(
    api, other_organiser, complete_draft, coordinator
):
    """Recording an attempt is only half an audit trail; it has to be readable."""
    api.force_authenticate(other_organiser)
    api.get(f"{EVENTS}{complete_draft.pk}/")

    api.force_authenticate(coordinator)
    response = api.get(AUDIT, {"refused_only": "true"})

    assert response.status_code == 200
    rows = response.data["results"]
    assert len(rows) >= 1
    row = rows[0]
    assert row["allowed"] is False
    assert row["actor_name"] == "Otto Other"
    assert row["actor_role"] == "Event Organiser"
    assert "another client organisation" in row["detail"]


@pytest.mark.django_db
def test_ac4_auditing_never_turns_a_refusal_into_a_server_error(
    api, other_organiser, complete_draft, monkeypatch
):
    """If the audit write fails, the caller must still get a clean 403."""
    from apps.core import audit

    def unavailable(*args, **kwargs):
        raise RuntimeError("audit table unavailable")

    monkeypatch.setattr(audit.AuditLog.objects, "create", unavailable)
    api.force_authenticate(other_organiser)

    response = api.get(f"{EVENTS}{complete_draft.pk}/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_the_audit_log_cannot_be_altered_through_the_api(
    api, coordinator, organiser, complete_draft
):
    """Evidence that can be edited is not evidence."""
    api.force_authenticate(organiser)
    api.get(f"/api/events/{complete_draft.pk}/")

    api.force_authenticate(coordinator)
    assert api.post(AUDIT, {"action": "invented"}, format="json").status_code == 405
    assert api.delete(AUDIT).status_code == 405
