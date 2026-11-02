"""G10/G11 integration through real request, decision and withdrawal endpoints.

Safety records below are explicit service-test preconditions; they do not claim
the later G20 Safety request/decision browser journey is implemented.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection
from django.db.migrations.executor import MigrationExecutor
from rest_framework.test import APIClient

from apps.core.models import AuditLog
from apps.events.models import EventRequest
from apps.notifications.models import Notification, NotificationKind
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.services import arrangement_version
from apps.venues.bookings import NotAssignedToEvent, withdraw_booking
from apps.venues.models import BookingStatus
from apps.venues.tests.test_scrum_11_request_booking import END, START, request_as
from apps.venues.tests.test_scrum_11_request_booking import event as event
from apps.venues.tests.test_scrum_11_request_booking import hall as hall

pytestmark = pytest.mark.django_db


def withdraw_url(booking):
    return f"/api/events/{booking.event_id}/venue-bookings/{booking.pk}/withdraw/"


def requested(api, coordinator, event, hall):
    assert request_as(api, coordinator, event, hall).status_code == 201
    return event.venue_bookings.get()


def approve(api, venue_staff, booking):
    api.force_authenticate(venue_staff)
    response = api.post(f"/api/venue-bookings/{booking.pk}/approve/", {}, format="json")
    assert response.status_code == 200
    booking.refresh_from_db()


def test_bi_01_request_approve_confirmed_withdrawal_retains_both_notices_and_history(
    api,
    coordinator,
    venue_staff,
    event,
    hall,
):
    booking = requested(api, coordinator, event, hall)
    approve(api, venue_staff, booking)
    original_decision = (booking.decided_by_id, booking.decided_at)
    api.force_authenticate(coordinator)
    period = {"starts_at": START.isoformat(), "ends_at": END.isoformat()}
    calendar = f"/api/venues/{hall.pk}/availability/"
    assert api.get(calendar, period).data["conflicts"][0]["id"] == booking.pk
    assert (
        api.post(withdraw_url(booking), {"expected_status": "APPROVED"}, format="json").status_code
        == 409
    )
    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED
    response = api.post(
        withdraw_url(booking),
        {"expected_status": "APPROVED", "confirm_release": True},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["booking"]["withdrawn_by_name"] == "Cora Coordinator"
    assert api.get(calendar, period).data["conflicts"] == []
    booking.refresh_from_db()
    assert (booking.decided_by_id, booking.decided_at) == original_decision
    assert list(booking.history.order_by("pk").values_list("to_status", flat=True)) == [
        "PENDING",
        "APPROVED",
        "WITHDRAWN",
    ]
    for kind, recipient in [
        (NotificationKind.VENUE_DECIDED, coordinator),
        (NotificationKind.VENUE_WITHDRAWN, venue_staff),
    ]:
        notice = Notification.objects.get(event=event, kind=kind)
        assert notice.recipient == recipient
        notice.full_clean()  # Both published choice values must remain valid.


def test_bi_02_pending_withdrawal_refuses_later_staff_decisions(
    api,
    coordinator,
    venue_staff,
    event,
    hall,
):
    booking = requested(api, coordinator, event, hall)
    api.force_authenticate(coordinator)
    assert (
        api.post(withdraw_url(booking), {"expected_status": "PENDING"}, format="json").status_code
        == 200
    )
    api.force_authenticate(venue_staff)
    for action in ["approve", "reject"]:
        assert (
            api.post(
                f"/api/venue-bookings/{booking.pk}/{action}/",
                {"reason": "Late decision"},
                format="json",
            ).status_code
            == 409
        )
    booking.refresh_from_db()
    assert booking.status == BookingStatus.WITHDRAWN
    assert booking.history.count() == 2
    assert not Notification.objects.filter(
        event=event, kind=NotificationKind.VENUE_DECIDED
    ).exists()


def test_bi_03_failed_withdrawal_keeps_real_approval_and_safety_snapshot(
    api,
    coordinator,
    venue_staff,
    event,
    hall,
):
    booking = requested(api, coordinator, event, hall)
    approve(api, venue_staff, booking)
    booking.event.refresh_from_db()
    check = SafetyCheck.objects.create(
        event=event,
        requested_by=coordinator,
        arrangement_version=arrangement_version(booking.event),
    )
    api.force_authenticate(coordinator)
    with (
        patch(
            "apps.notifications.models.Notification.objects.bulk_create",
            side_effect=RuntimeError("injected notification failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        api.post(
            withdraw_url(booking),
            {"expected_status": "APPROVED", "confirm_release": True},
            format="json",
        )
    booking.refresh_from_db()
    check.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED
    assert check.status == SafetyStatus.PENDING
    assert booking.history.count() == 2
    assert (
        Notification.objects.filter(event=event, kind=NotificationKind.VENUE_DECIDED).count() == 1
    )
    assert not Notification.objects.filter(
        event=event, kind=NotificationKind.VENUE_WITHDRAWN
    ).exists()
    assert (
        api.post(
            withdraw_url(booking),
            {"expected_status": "APPROVED", "confirm_release": True},
            format="json",
        ).status_code
        == 200
    )
    check.refresh_from_db()
    assert check.status == SafetyStatus.SUPERSEDED


@pytest.mark.django_db(transaction=True)
def test_bi_04_concurrent_approval_and_pending_withdrawal_have_one_winner(
    api,
    coordinator,
    venue_staff,
    event,
    hall,
):
    booking = requested(api, coordinator, event, hall)
    barrier = Barrier(2)

    def act(action):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(venue_staff if action == "approve" else coordinator)
            barrier.wait(timeout=10)
            if action == "approve":
                response = client.post(
                    f"/api/venue-bookings/{booking.pk}/approve/", {}, format="json"
                )
            else:
                response = client.post(
                    withdraw_url(booking), {"expected_status": "PENDING"}, format="json"
                )
            return response.status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(act, ["approve", "withdraw"])) == [200, 409]
    booking.refresh_from_db()
    assert booking.status in [BookingStatus.APPROVED, BookingStatus.WITHDRAWN]
    assert booking.history.count() == 2
    assert (
        Notification.objects.filter(
            event=event,
            kind__in=[NotificationKind.VENUE_DECIDED, NotificationKind.VENUE_WITHDRAWN],
        ).count()
        == 1
    )


def test_bi_05_migration_graph_has_one_leaf_and_preserves_both_notice_kinds():
    executor = MigrationExecutor(connection)
    graph = executor.loader.graph
    # One leaf, and the G10/G11 merge is part of its history. Later notice
    # kinds (e.g. SCRUM-74's 0011) add migrations after it (INT-06).
    [leaf] = graph.leaf_nodes("notifications")
    assert ("notifications", "0010_merge_booking_notice_kinds") in graph.forwards_plan(leaf)
    state = executor.loader.project_state()
    field = state.apps.get_model("notifications", "Notification")._meta.get_field("kind")
    assert dict(field.choices) == dict(Notification._meta.get_field("kind").choices)
    assert {"VENUE_DECIDED", "VENUE_WITHDRAWN"} <= set(dict(field.choices))


def test_bi_06_reassignment_after_permission_check_is_refused_and_audited(
    api,
    coordinator,
    second_coordinator,
    event,
    hall,
):
    booking = requested(api, coordinator, event, hall)

    def reassign_then_withdraw(**kwargs):
        EventRequest.objects.filter(pk=event.pk).update(coordinator=second_coordinator)
        return withdraw_booking(**kwargs)

    api.force_authenticate(coordinator)
    with patch("apps.venues.booking_views.withdraw_booking", side_effect=reassign_then_withdraw):
        response = api.post(withdraw_url(booking), {"expected_status": "PENDING"}, format="json")
    assert response.status_code == 403
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert booking.history.count() == 1
    assert not Notification.objects.filter(
        event=event, kind=NotificationKind.VENUE_WITHDRAWN
    ).exists()
    assert AuditLog.objects.filter(
        actor=coordinator,
        allowed=False,
        detail="only the current assigned coordinator may withdraw",
    ).exists()


def test_bi_07_internal_withdrawal_service_also_refuses_wrong_role(
    api,
    coordinator,
    venue_staff,
    event,
    hall,
):
    booking = requested(api, coordinator, event, hall)
    with pytest.raises(NotAssignedToEvent):
        withdraw_booking(booking=booking, actor=venue_staff, expected_status="PENDING")
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert booking.history.count() == 1
