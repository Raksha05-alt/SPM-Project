"""SCRUM-51 acceptance criteria and assignment boundary regressions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus, InvalidTransition
from apps.events.models import EventRequest
from apps.events.services import MissingMandatoryFields, submit_event
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


def test_ac1_assigns_one_available_coordinator(signed_in_organiser, complete_draft, coordinator):
    response = signed_in_organiser.post(f"/api/events/{complete_draft.pk}/submit/")
    assert response.status_code == 200
    complete_draft.refresh_from_db()
    assert complete_draft.coordinator == coordinator
    assert response.data["coordinator"] == coordinator.pk
    assert response.data["assignment_requires_attention"] is False
    assert complete_draft.status == EventStatus.SUBMITTED
    assert complete_draft.status_history.count() == 1


def test_ac2_random_choice_uses_all_available_coordinators(complete_draft, organiser, coordinator):
    second = User.objects.create_user(
        username="second", email="second@connectsphere.example", role=Role.EVENT_COORDINATOR
    )
    with patch("apps.events.services.choice", return_value=second) as choose:
        submit_event(complete_draft, organiser)
    assert {u.pk for u in choose.call_args.args[0]} == {coordinator.pk, second.pk}
    assert complete_draft.coordinator == second


@pytest.mark.parametrize("unavailable", ["inactive", "unavailable", "wrong_role"])
def test_excludes_ineligible_users(complete_draft, organiser, coordinator, unavailable):
    if unavailable == "inactive":
        coordinator.is_active = False
    elif unavailable == "unavailable":
        coordinator.coordinator_available = False
    else:
        coordinator.role = Role.VENUE_STAFF
    coordinator.save()
    with patch("apps.events.services.choice") as choose:
        submit_event(complete_draft, organiser)
    choose.assert_not_called()
    assert complete_draft.coordinator is None
    assert complete_draft.assignment_requires_attention


def test_ac3_both_recipients_receive_persistent_notifications(
    complete_draft, organiser, coordinator
):
    submit_event(complete_draft, organiser)
    notices = Notification.objects.filter(event=complete_draft)
    assert notices.count() == 2
    assert set(notices.values_list("recipient_id", flat=True)) == {organiser.pk, coordinator.pk}
    assert coordinator.email in notices.get(recipient=organiser).message
    assert complete_draft.name in notices.get(recipient=coordinator).message


def test_ac4_organiser_can_see_name_and_contact(signed_in_organiser, complete_draft, coordinator):
    signed_in_organiser.post(f"/api/events/{complete_draft.pk}/submit/")
    response = signed_in_organiser.get(f"/api/events/{complete_draft.pk}/")
    assert response.data["coordinator_name"] == coordinator.get_full_name()
    assert response.data["coordinator_email"] == coordinator.email


def test_name_falls_back_to_email(signed_in_organiser, complete_draft, coordinator):
    coordinator.first_name = coordinator.last_name = ""
    coordinator.save()
    response = signed_in_organiser.post(f"/api/events/{complete_draft.pk}/submit/")
    assert response.data["coordinator_name"] == coordinator.email


def test_ac5_no_available_coordinator_flags_submitted_request(
    signed_in_organiser, signed_in_coordinator, complete_draft, coordinator
):
    # These fixtures share one APIClient; authenticate explicitly at each step.
    signed_in_organiser.force_authenticate(complete_draft.created_by)
    coordinator.coordinator_available = False
    coordinator.save()
    response = signed_in_organiser.post(f"/api/events/{complete_draft.pk}/submit/")
    assert response.status_code == 200
    assert response.data["status"] == EventStatus.SUBMITTED
    assert response.data["coordinator"] is None
    assert response.data["coordinator_email"] is None
    assert response.data["assignment_requires_attention"] is True
    assert Notification.objects.count() == 0
    signed_in_coordinator.force_authenticate(coordinator)
    row = signed_in_coordinator.get("/api/events/queue/").data[0]
    assert row["assignment_requires_attention"] is True
    assert row["coordinator_name"] is None


def test_incomplete_submission_does_not_assign_or_notify(incomplete_draft, organiser, coordinator):
    with pytest.raises(MissingMandatoryFields):
        submit_event(incomplete_draft, organiser)
    incomplete_draft.refresh_from_db()
    assert incomplete_draft.is_draft
    assert incomplete_draft.coordinator is None
    assert Notification.objects.count() == 0


def test_repeated_stale_submission_does_not_reassign(complete_draft, organiser, coordinator):
    stale = EventRequest.objects.get(pk=complete_draft.pk)
    submit_event(complete_draft, organiser)
    with pytest.raises(InvalidTransition):
        submit_event(stale, organiser)
    stale.refresh_from_db()
    assert stale.coordinator == coordinator
    assert stale.status_history.count() == 1
    assert Notification.objects.count() == 2


def test_notification_failure_rolls_back_entire_submission(complete_draft, organiser, coordinator):
    with patch.object(
        Notification.objects, "bulk_create", side_effect=RuntimeError("storage error")
    ):
        with pytest.raises(RuntimeError, match="storage error"):
            submit_event(complete_draft, organiser)
    complete_draft.refresh_from_db()
    assert complete_draft.is_draft
    assert complete_draft.coordinator is None
    assert complete_draft.status_history.count() == 0
    assert Notification.objects.count() == 0


def test_client_cannot_set_assignment_fields(signed_in_organiser, complete_draft, coordinator):
    response = signed_in_organiser.patch(
        f"/api/events/{complete_draft.pk}/",
        {"coordinator": coordinator.pk, "assignment_requires_attention": True},
        format="json",
    )
    assert response.status_code == 200
    complete_draft.refresh_from_db()
    assert complete_draft.coordinator is None
    assert not complete_draft.assignment_requires_attention


def test_notifications_are_recipient_only(
    api, complete_draft, organiser, coordinator, other_organiser
):
    submit_event(complete_draft, organiser)
    assert api.get("/api/notifications/").status_code == 403
    assert AuditLog.objects.get(action="GET /api/notifications/").actor is None
    for user in (organiser, coordinator, other_organiser):
        api.force_authenticate(user)
        response = api.get("/api/notifications/")
        assert response.status_code == 200
        assert len(response.data) == (0 if user == other_organiser else 1)
        assert api.post("/api/notifications/", {}, format="json").status_code == 405


@pytest.mark.django_db(transaction=True)
def test_concurrent_submissions_assign_and_notify_only_once(complete_draft, organiser, coordinator):
    barrier = Barrier(2)

    def attempt():
        close_old_connections()
        try:
            event = EventRequest.objects.get(pk=complete_draft.pk)
            user = User.objects.get(pk=organiser.pk)
            barrier.wait(timeout=10)
            try:
                submit_event(event, user)
                return "submitted"
            except InvalidTransition:
                return "refused"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["refused", "submitted"]
    complete_draft.refresh_from_db()
    assert complete_draft.coordinator == coordinator
    assert complete_draft.status_history.count() == 1
    assert Notification.objects.count() == 2
