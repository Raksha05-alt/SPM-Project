"""Submission regressions: SCRUM-89 replaces automatic allocation from SCRUM-51.

The original Sprint 2 tests remain in Git history. Contact and notices now
follow a Lead assignment, covered in test_cr_05_lead_assignment.py.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections

from apps.accounts.models import User
from apps.core.statuses import EventStatus, InvalidTransition
from apps.events.models import EventRequest
from apps.events.services import MissingMandatoryFields, submit_event
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


def test_submission_waits_for_lead_even_with_available_coordinator(
    signed_in_organiser, complete_draft, coordinator
):
    response = signed_in_organiser.post(f"/api/events/{complete_draft.pk}/submit/")
    assert response.status_code == 200
    complete_draft.refresh_from_db()
    assert complete_draft.coordinator is None
    assert complete_draft.supervising_lead is None
    assert response.data["assignment_requires_attention"] is True
    assert complete_draft.status == EventStatus.SUBMITTED
    assert complete_draft.status_history.count() == 1
    assert Notification.objects.count() == 0


def test_incomplete_submission_does_not_change_assignment(incomplete_draft, organiser):
    with pytest.raises(MissingMandatoryFields):
        submit_event(incomplete_draft, organiser)
    incomplete_draft.refresh_from_db()
    assert incomplete_draft.is_draft
    assert incomplete_draft.status_history.count() == Notification.objects.count() == 0


def test_repeated_stale_submission_does_not_transition_again(complete_draft, organiser):
    stale = EventRequest.objects.get(pk=complete_draft.pk)
    submit_event(complete_draft, organiser)
    with pytest.raises(InvalidTransition):
        submit_event(stale, organiser)
    stale.refresh_from_db()
    assert stale.coordinator is None
    assert stale.status_history.count() == 1
    assert Notification.objects.count() == 0


def test_client_cannot_set_assignment_fields(
    signed_in_organiser, complete_draft, coordinator, lead
):
    response = signed_in_organiser.patch(
        f"/api/events/{complete_draft.pk}/",
        {
            "coordinator": coordinator.pk,
            "supervising_lead": lead.pk,
            "assignment_revision": 12,
            "assignment_requires_attention": True,
        },
        format="json",
    )
    assert response.status_code == 200
    complete_draft.refresh_from_db()
    assert complete_draft.coordinator is None
    assert complete_draft.supervising_lead is None
    assert complete_draft.assignment_revision == 0
    assert not complete_draft.assignment_requires_attention


@pytest.mark.django_db(transaction=True)
def test_concurrent_submissions_transition_only_once(complete_draft, organiser):
    barrier = Barrier(2)

    def attempt(_):
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
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == ["refused", "submitted"]
    complete_draft.refresh_from_db()
    assert complete_draft.coordinator is None
    assert complete_draft.status_history.count() == 1
    assert Notification.objects.count() == 0
