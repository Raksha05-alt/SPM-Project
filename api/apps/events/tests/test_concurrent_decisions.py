"""Coordinator decisions must survive edits already in progress.

Since the Week 9 clarification only the coordinator edits a submitted request
(on the client's behalf), so the edit in flight is the coordinator's own, for
example from a second browser tab. The row-lock protection is unchanged.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import OperationalError, close_old_connections, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest, EventStatusHistory
from apps.events.serializers import EventRequestSerializer
from apps.events.views import EventRequestViewSet
from apps.notifications.models import Notification, NotificationKind
from conftest import make_event

REASON = "The requested date is unavailable."


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["patch", "put"])
@pytest.mark.parametrize(
    ("decision", "expected_status", "notification_kind", "edit_status"),
    [
        # A rejected request is closed, so the late edit is refused and audited.
        ("reject", EventStatus.REJECTED, NotificationKind.REJECTED, 403),
        # An approved one is still editable; the edit saves without undoing the decision.
        ("approve", EventStatus.APPROVED, NotificationKind.APPROVED, 200),
    ],
)
def test_decision_finishing_before_pending_edit_is_preserved_and_edit_is_audited(
    api,
    organiser,
    coordinator,
    monkeypatch,
    method,
    decision,
    expected_status,
    notification_kind,
    edit_status,
):
    event = make_event(organiser, status=EventStatus.UNDER_REVIEW, coordinator=coordinator)
    coordinator_client = APIClient()
    coordinator_client.force_authenticate(coordinator)
    original_perform_update = EventRequestViewSet.perform_update

    def decide_before_pending_edit(view, serializer):
        # The edit has passed the initial permission check and validation, but
        # its save has not started. Commit a decision through a second client.
        response = coordinator_client.post(
            f"/api/events/{event.pk}/{decision}/", {"reason": REASON}, format="json"
        )
        assert response.status_code == 200
        return original_perform_update(view, serializer)

    monkeypatch.setattr(EventRequestViewSet, "perform_update", decide_before_pending_edit)
    api.force_authenticate(coordinator)
    data = {"description": "Pending changes"}
    if method == "put":
        data.update(
            name=event.name,
            purpose=event.purpose,
            preferred_start=event.preferred_start.isoformat(),
            preferred_end=event.preferred_end.isoformat(),
            expected_attendance=event.expected_attendance,
        )
    response = getattr(api, method)(f"/api/events/{event.pk}/", data, format="json")

    assert response.status_code == edit_status, response.data
    event.refresh_from_db()
    assert event.status == expected_status
    assert event.description == ("" if edit_status == 403 else "Pending changes")
    if decision == "reject":
        assert event.rejection_reason == REASON
        assert event.rejected_by == coordinator
        assert event.rejected_at == event.status_changed_at
    else:
        assert event.approved_by == coordinator
        assert event.approved_at == event.status_changed_at
    assert EventStatusHistory.objects.filter(event=event, to_status=expected_status).count() == 1
    assert Notification.objects.filter(event=event, kind=notification_kind).count() == 1
    refused = AuditLog.objects.filter(
        actor=coordinator, action=f"{method.upper()} /api/events/{event.pk}/", allowed=False
    )
    assert refused.exists() == (edit_status == 403)


@pytest.mark.django_db
def test_partial_date_edit_is_validated_against_the_latest_saved_end(
    api, organiser, coordinator, monkeypatch
):
    event = make_event(organiser, status=EventStatus.UNDER_REVIEW, coordinator=coordinator)
    new_start = event.preferred_start + timezone.timedelta(hours=2)
    new_end = event.preferred_start + timezone.timedelta(hours=1)
    original_perform_update = EventRequestViewSet.perform_update

    def shorten_event_before_pending_edit(view, serializer):
        EventRequest.objects.filter(pk=event.pk).update(preferred_end=new_end)
        return original_perform_update(view, serializer)

    monkeypatch.setattr(EventRequestViewSet, "perform_update", shorten_event_before_pending_edit)
    api.force_authenticate(coordinator)
    response = api.patch(
        f"/api/events/{event.pk}/", {"preferred_start": new_start.isoformat()}, format="json"
    )

    assert response.status_code == 400
    assert "preferred_end" in response.data
    original_start = event.preferred_start
    event.refresh_from_db()
    assert event.preferred_start == original_start
    assert event.preferred_end == new_end


@pytest.mark.django_db(transaction=True)
def test_pending_edit_holds_the_event_lock_until_saved_then_rejection_preserves_changes(
    api, organiser, coordinator, monkeypatch
):
    event = make_event(organiser, status=EventStatus.UNDER_REVIEW, coordinator=coordinator)
    original_update = EventRequestSerializer.update

    def competing_writer_is_blocked():
        close_old_connections()
        try:
            with transaction.atomic():
                EventRequest.objects.select_for_update(nowait=True).get(pk=event.pk)
            return False
        except OperationalError as exc:
            # PostgreSQL lock_not_available, rather than an unrelated DB error.
            assert exc.__cause__.sqlstate == "55P03"
            return True
        finally:
            close_old_connections()

    def save_while_another_writer_attempts_to_lock(serializer, instance, validated_data):
        # Use a separate PostgreSQL connection to check that a decision cannot
        # acquire this row between the edit's permission check and save.
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(competing_writer_is_blocked).result(timeout=10)
        return original_update(serializer, instance, validated_data)

    monkeypatch.setattr(
        EventRequestSerializer, "update", save_while_another_writer_attempts_to_lock
    )
    api.force_authenticate(coordinator)
    response = api.patch(
        f"/api/events/{event.pk}/", {"description": "Updated equipment requirements"}, format="json"
    )
    assert response.status_code == 200

    coordinator_client = APIClient()
    coordinator_client.force_authenticate(coordinator)
    decision = coordinator_client.post(
        f"/api/events/{event.pk}/reject/", {"reason": REASON}, format="json"
    )
    assert decision.status_code == 200
    event.refresh_from_db()
    assert event.status == EventStatus.REJECTED
    assert event.description == "Updated equipment requirements"
    assert event.rejection_reason == REASON
    assert event.rejected_by == coordinator
    assert Notification.objects.filter(event=event, kind=NotificationKind.REJECTED).count() == 1
