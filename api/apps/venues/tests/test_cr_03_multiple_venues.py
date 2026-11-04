"""SCRUM-87: real API decisions, immutable history, and independent session oracles."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from threading import Barrier
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.db import close_old_connections, connection
from rest_framework.test import APIClient

from apps.core.statuses import EventStatus
from apps.events.confirmation import confirmed_arrangements
from apps.events.models import EventFieldChange
from apps.notifications.models import Notification, NotificationKind
from apps.safety.services import arrangement_gaps
from apps.venues.bookings import BookingValidationError, NotAssignedToEvent, approve_booking
from apps.venues.models import BookingStatus, EventSession, SessionKind, VenueBooking
from apps.venues.sessions import remove_session
from apps.venues.suitability import Requirements, assess
from apps.venues.tests.conftest import make_venue
from conftest import make_event

pytestmark = pytest.mark.django_db
START = datetime(2027, 6, 8, 10, tzinfo=ZoneInfo("Asia/Singapore"))
END = START + timedelta(hours=2)


@pytest.fixture
def event(organiser, coordinator):
    return make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        expected_attendance=120,
        preferred_start=START,
        preferred_end=END,
    )


@pytest.fixture
def rooms(db):
    return (
        make_venue(name="Main Hall", capacity=120, opens_at=time(8), closes_at=time(22)),
        make_venue(name="Breakout Room", capacity=30, opens_at=time(8), closes_at=time(22)),
    )


def payload(venue, **overrides):
    data = {
        "venue": venue.pk,
        "starts_at": START.isoformat(),
        "ends_at": END.isoformat(),
        "attendance": 120,
        "layout": "THEATRE",
    }
    data.update(overrides)
    return data


def request(api, coordinator, event, room, **overrides):
    api.force_authenticate(coordinator)
    return api.post(
        f"/api/events/{event.pk}/venue-bookings/", payload(room, **overrides), format="json"
    )


def booking(api, coordinator, event, room, **overrides):
    result = request(api, coordinator, event, room, **overrides)
    assert result.status_code == 201, result.data
    return VenueBooking.objects.get(pk=result.data["booking"]["id"])


def breakout(api, coordinator, event, room, **overrides):
    return booking(
        api,
        coordinator,
        event,
        room,
        session_kind="BREAKOUT",
        session_name="Breakout A",
        attendance=30,
        **overrides,
    )


def approve(api, staff, item):
    api.force_authenticate(staff)
    return api.post(f"/api/venue-bookings/{item.pk}/approve/", {}, format="json")


def test_ac1_separate_named_requests_and_staff_notifications(
    api, coordinator, venue_staff, event, rooms
):
    main = booking(api, coordinator, event, rooms[0])
    other = breakout(api, coordinator, event, rooms[1])
    assert main.event_id == other.event_id == event.pk
    assert main.session_id != other.session_id
    assert [(s.name, s.kind) for s in event.venue_sessions.all()] == [
        ("Main programme", "MAIN"),
        ("Breakout A", "BREAKOUT"),
    ]
    api.force_authenticate(venue_staff)
    rows = api.get("/api/venue-bookings/").data
    assert {(r["session_name"], r["attendance"]) for r in rows} == {
        ("Main programme", 120),
        ("Breakout A", 30),
    }
    assert (
        Notification.objects.filter(
            kind=NotificationKind.VENUE_REQUESTED, recipient=venue_staff
        ).count()
        == 2
    )


@pytest.mark.parametrize("attendance,code", [(30, 201), (31, 400)])
def test_ac2_breakout_capacity_uses_own_attendance(
    api, coordinator, event, rooms, attendance, code
):
    result = request(
        api,
        coordinator,
        event,
        rooms[1],
        session_kind="BREAKOUT",
        session_name="Workshop",
        attendance=attendance,
    )
    assert result.status_code == code
    if code == 400:
        assert result.data["unmet_requirements"][0]["requirement"] == "CAPACITY"
        assert (
            not event.venue_sessions.exists()
        )  # request and newly created identity roll back together
    else:
        assert result.data["booking"]["effective_attendance"] == 30


def test_ac2_main_cannot_understate_event_attendance(api, coordinator, event, rooms):
    result = request(api, coordinator, event, rooms[1], attendance=1)
    assert result.status_code == 400
    assert "120" in result.data["unmet_requirements"][0]["message"]


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"required_facilities": ["Hearing loop"]}, "FACILITY"),
        ({"layout": "BOARDROOM"}, "layout"),
        ({"wheelchair_access_required": True}, "accessibility"),
    ],
)
def test_ac2_breakout_requirements_checked_independently(
    api, coordinator, event, rooms, changes, code
):
    result = request(
        api,
        coordinator,
        event,
        rooms[1],
        session_kind="BREAKOUT",
        session_name="Workshop",
        attendance=30,
        **changes,
    )
    assert result.status_code == 400
    assert any(
        code.upper().removesuffix("S") in r["requirement"]
        for r in result.data["unmet_requirements"]
    )


def test_ac3_same_event_same_room_overlapping_sessions_refused(
    api, coordinator, venue_staff, event, rooms
):
    main = booking(api, coordinator, event, rooms[0])
    other = breakout(api, coordinator, event, rooms[0])
    assert approve(api, venue_staff, main).status_code == 200
    response = approve(api, venue_staff, other)
    assert response.status_code == 409
    other.refresh_from_db()
    assert other.status == BookingStatus.PENDING
    assert other.history.count() == 1
    assert event.venue_bookings.filter(status="APPROVED").count() == 1


@pytest.mark.parametrize("minute,code", [(15, 201), (14, 409)])
def test_ac3_buffered_boundary_between_sessions(
    api, coordinator, venue_staff, event, rooms, minute, code
):
    room = rooms[0]
    room.setup_minutes, room.turnaround_minutes = 30, 45
    room.save()
    main = booking(api, coordinator, event, room)
    assert approve(api, venue_staff, main).status_code == 200
    start = START.replace(hour=13, minute=minute)
    result = request(
        api,
        coordinator,
        event,
        room,
        session_kind="BREAKOUT",
        session_name="Afternoon",
        attendance=30,
        starts_at=start.isoformat(),
        ends_at=(start + timedelta(hours=1)).isoformat(),
    )
    assert result.status_code == code


def test_ac4_decisions_are_independent_and_rejected_required_session_blocks_confirm(
    api, coordinator, venue_staff, event, rooms
):
    main = booking(api, coordinator, event, rooms[0])
    other = breakout(api, coordinator, event, rooms[1])
    assert approve(api, venue_staff, main).status_code == 200
    main_history = list(main.history.values())
    response = api.post(
        f"/api/venue-bookings/{other.pk}/reject/", {"reason": "Room unavailable"}, format="json"
    )
    assert response.status_code == 200
    main.refresh_from_db()
    assert main.status == BookingStatus.APPROVED and list(main.history.values()) == main_history
    assert any("Breakout A" in gap for gap in arrangement_gaps(event))
    api.force_authenticate(coordinator)
    assert api.post(f"/api/events/{event.pk}/confirm/", {}, format="json").status_code == 409
    assert api.post(f"/api/events/{event.pk}/safety-checks/", {}, format="json").status_code == 409


def test_ac4_two_rooms_approve_without_the_old_event_constraint(
    api, coordinator, venue_staff, event, rooms
):
    main = booking(api, coordinator, event, rooms[0])
    other = breakout(api, coordinator, event, rooms[1])
    for item in (main, other):
        assert approve(api, venue_staff, item).status_code == 200
    assert not [g for g in arrangement_gaps(event) if g.startswith("Venue:")]
    assert event.venue_bookings.filter(status="APPROVED").count() == 2


def test_ac5_withdrawal_preserves_other_room_and_missing_session_until_explicit_removal(
    api, coordinator, venue_staff, event, rooms
):
    main = booking(api, coordinator, event, rooms[0])
    other = breakout(api, coordinator, event, rooms[1])
    for item in (main, other):
        assert approve(api, venue_staff, item).status_code == 200
    before = list(main.history.values())
    api.force_authenticate(coordinator)
    response = api.post(
        f"/api/events/{event.pk}/venue-bookings/{other.pk}/withdraw/",
        {"expected_status": "APPROVED", "confirm_release": True},
        format="json",
    )
    assert response.status_code == 200
    assert list(main.history.values()) == before
    assert any("Breakout A" in g for g in arrangement_gaps(event))
    assert (
        api.post(
            f"/api/events/{event.pk}/venue-sessions/{other.session_id}/remove/", {}, format="json"
        ).status_code
        == 200
    )
    assert not [g for g in arrangement_gaps(event) if g.startswith("Venue:")]
    assert other.history.count() == 3
    assert EventFieldChange.objects.filter(
        event=event, field=f"venue_session:{other.session_id}:active", before=True, after=False
    ).exists()
    assert (
        api.post(
            f"/api/events/{event.pk}/venue-sessions/{main.session_id}/remove/", {}, format="json"
        ).status_code
        == 409
    )


def test_ac5_replacement_keeps_original_until_atomic_staff_decision(
    api, coordinator, venue_staff, event, rooms
):
    main = booking(api, coordinator, event, rooms[0])
    assert approve(api, venue_staff, main).status_code == 200
    new_room = make_venue(
        name="Replacement Hall", capacity=120, opens_at=time(8), closes_at=time(22)
    )
    replacement = booking(
        api, coordinator, event, new_room, session_id=main.session_id, replaces_id=main.pk
    )
    main.refresh_from_db()
    assert main.status == "APPROVED" and replacement.status == "PENDING"
    assert approve(api, venue_staff, replacement).status_code == 200
    main.refresh_from_db()
    assert (
        main.status == "WITHDRAWN"
        and main.history.last().reason
        == f"Replaced by booking {replacement.pk} for Main programme."
    )
    replacement.refresh_from_db()
    assert replacement.status == "APPROVED" and replacement.session_id == main.session_id
    assert approve(api, venue_staff, replacement).status_code == 409


def test_ac5_replacement_notification_failure_rolls_back_original_and_history(
    api, coordinator, venue_staff, event, rooms
):
    main = booking(api, coordinator, event, rooms[0])
    assert approve(api, venue_staff, main).status_code == 200
    new_room = make_venue(
        name="Replacement Hall", capacity=120, opens_at=time(8), closes_at=time(22)
    )
    replacement = booking(
        api, coordinator, event, new_room, session_id=main.session_id, replaces_id=main.pk
    )
    with (
        patch("apps.venues.bookings.notify", side_effect=RuntimeError("notice failed")),
        pytest.raises(RuntimeError),
    ):
        approve_booking(replacement, venue_staff)
    main.refresh_from_db()
    replacement.refresh_from_db()
    assert (main.status, replacement.status) == ("APPROVED", "PENDING")
    assert (main.history.count(), replacement.history.count()) == (2, 1)


def test_ac6_public_projection_includes_session_identity_and_no_internal_notes(
    api, coordinator, venue_staff, organiser, attendee, event, rooms
):
    # Low-level confirmed fixture tests disclosure only; real confirmation is in browser journey S4-SESSIONS.
    main = booking(api, coordinator, event, rooms[0])
    other = breakout(api, coordinator, event, rooms[1])
    for item in (main, other):
        assert approve(api, venue_staff, item).status_code == 200
    event.status = EventStatus.CONFIRMED
    event.save(update_fields=["status"])
    projected = confirmed_arrangements(event)
    assert [(v["session_name"], v["attendance"]) for v in projected["venues"]] == [
        ("Main programme", 120),
        ("Breakout A", 30),
    ]
    for user in (organiser, attendee):
        api.force_authenticate(user)
        response = api.get(f"/api/events/{event.pk}/confirmed-arrangements/")
        assert response.status_code == 200, response.data
        assert {v["session_name"] for v in response.data["venues"]} == {
            "Main programme",
            "Breakout A",
        }
        assert "emergency_access" not in str(response.data)
        assert "decision_reason" not in str(response.data)


def test_ac7_main_follows_event_attendance_breakout_keeps_own_period_and_requirements(
    api, coordinator, venue_staff, event, rooms
):
    main = booking(api, coordinator, event, rooms[0])
    other = breakout(api, coordinator, event, rooms[1])
    for item in (main, other):
        assert approve(api, venue_staff, item).status_code == 200
    before = (other.starts_at, other.ends_at, other.attendance, other.layout)
    api.force_authenticate(coordinator)
    response = api.patch(f"/api/events/{event.pk}/", {"expected_attendance": 121}, format="json")
    assert response.status_code == 200
    main = VenueBooking.objects.get(pk=main.pk)
    other.refresh_from_db()
    assert Requirements.for_booking(main).attendance == 121
    assert not assess(rooms[0], Requirements.for_booking(main)).suitable
    assert Requirements.for_booking(other).attendance == 30
    assert (other.starts_at, other.ends_at, other.attendance, other.layout) == before


@pytest.mark.parametrize(
    "who", ["organiser", "attendee", "second_coordinator", "lead", "venue_staff"]
)
def test_permissions_no_foreign_session_read_or_write(api, coordinator, event, rooms, request, who):
    item = booking(api, coordinator, event, rooms[0])
    user = request.getfixturevalue(who)
    api.force_authenticate(user)
    assert (
        api.post(
            f"/api/events/{event.pk}/venue-bookings/", payload(rooms[0]), format="json"
        ).status_code
        == 403
    )
    assert (
        api.post(
            f"/api/events/{event.pk}/venue-sessions/{item.session_id}/remove/", {}, format="json"
        ).status_code
        == 403
    )
    if who in ("organiser", "attendee", "second_coordinator"):
        assert api.get(f"/api/events/{event.pk}/venue-sessions/").status_code == 403


def test_foreign_session_and_duplicate_name_refused_without_orphan_records(
    api, coordinator, organiser, event, rooms
):
    foreign = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    session = EventSession.objects.create(event=foreign, kind="MAIN", name="Main programme")
    assert request(api, coordinator, event, rooms[0], session_id=session.pk).status_code == 400
    assert not event.venue_sessions.exists()
    other = breakout(api, coordinator, event, rooms[1])
    assert (
        request(
            api,
            coordinator,
            event,
            rooms[1],
            session_kind="BREAKOUT",
            session_name="breakout a",
            attendance=30,
        ).status_code
        == 400
    )
    assert event.venue_sessions.count() == 2
    assert (
        request(
            api, coordinator, event, rooms[0], session_id=other.session_id, replaces_id=99999
        ).status_code
        == 400
    )


def test_inactive_main_and_confirmed_session_changes_are_guarded(
    api, coordinator, venue_staff, event, rooms
):
    main = booking(api, coordinator, event, rooms[0])
    other = breakout(api, coordinator, event, rooms[1])
    with pytest.raises(BookingValidationError):
        remove_session(other.session, coordinator)
    event.status = EventStatus.CONFIRMED
    event.save(update_fields=["status"])
    assert request(api, coordinator, event, rooms[0]).status_code == 400
    assert approve(api, venue_staff, main).status_code == 409
    with pytest.raises(BookingValidationError):
        remove_session(other.session, coordinator)


@pytest.mark.django_db(transaction=True)
def test_ac3_concurrent_same_room_sessions_only_one_approval(
    api, coordinator, venue_staff, event, rooms
):
    assert connection.vendor == "postgresql"
    main = booking(api, coordinator, event, rooms[0])
    other = breakout(api, coordinator, event, rooms[0])
    barrier = Barrier(2)

    def decide(pk):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(venue_staff)
            barrier.wait(timeout=10)
            return client.post(f"/api/venue-bookings/{pk}/approve/", {}, format="json").status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(decide, [main.pk, other.pk]))
    assert results == [200, 409]
    assert event.venue_bookings.filter(status="APPROVED").count() == 1


@pytest.mark.django_db(transaction=True)
def test_migration_preserves_legacy_ids_decisions_timestamps_and_history(
    event, rooms, coordinator, venue_staff
):
    from django.db.migrations.executor import MigrationExecutor

    previous = [("venues", "0008_venue_setup_minutes_venue_turnaround_minutes")]
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    executor.migrate(previous)
    try:
        old = executor.loader.project_state(previous).apps
        Booking = old.get_model("venues", "VenueBooking")
        History = old.get_model("venues", "VenueBookingHistory")
        approved = Booking.objects.create(
            event_id=event.pk,
            venue_id=rooms[0].pk,
            starts_at=START,
            ends_at=END,
            attendance=120,
            status="APPROVED",
            requested_by_id=coordinator.pk,
            decided_by_id=venue_staff.pk,
            decided_at=START - timedelta(days=2),
            decision_reason="Approved with stage plan",
        )
        rejected = Booking.objects.create(
            event_id=event.pk,
            venue_id=rooms[1].pk,
            starts_at=START,
            ends_at=END,
            attendance=120,
            status="REJECTED",
            decision_reason="Too small",
        )
        history = History.objects.create(
            booking_id=approved.pk,
            from_status="PENDING",
            to_status="APPROVED",
            actor_id=venue_staff.pk,
            reason="Reviewed",
        )
        snapshots = list(Booking.objects.order_by("pk").values())
        history_snapshot = History.objects.get(pk=history.pk).__dict__.copy()
        history_snapshot.pop("_state")
        MigrationExecutor(connection).migrate(latest)
        rows = list(VenueBooking.objects.filter(pk__in=[approved.pk, rejected.pk]).order_by("pk"))
        assert len(rows) == 2 and rows[0].session_id == rows[1].session_id
        assert rows[0].session.name == "Main programme"
        for row, before in zip(rows, snapshots, strict=True):
            for field, value in before.items():
                assert getattr(row, field) == value
        from apps.venues.models import VenueBookingHistory

        assert VenueBookingHistory.objects.filter(**history_snapshot).exists()
        assert EventSession.objects.filter(event=event, kind=SessionKind.MAIN).count() == 1
    finally:
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.parametrize(
    "name,kind", [("", "BREAKOUT"), ("x" * 101, "BREAKOUT"), ("Workshop", "UNKNOWN")]
)
def test_domain_refuses_invalid_session_identity(event, name, kind):
    from apps.venues.sessions import resolve_session

    with pytest.raises(BookingValidationError):
        resolve_session(event, name=name, kind=kind)


def test_removal_permissions_idempotency_and_inactive_session_refusal(
    api, coordinator, second_coordinator, event, rooms
):
    other = breakout(api, coordinator, event, rooms[1])
    with pytest.raises(NotAssignedToEvent):
        remove_session(other.session, second_coordinator)
    api.force_authenticate(coordinator)
    assert (
        api.post(
            f"/api/events/{event.pk}/venue-bookings/{other.pk}/withdraw/",
            {"expected_status": "PENDING"},
            format="json",
        ).status_code
        == 200
    )
    remove_session(other.session, coordinator)
    before = EventFieldChange.objects.filter(event=event).count()
    remove_session(other.session, coordinator)
    assert EventFieldChange.objects.filter(event=event).count() == before
    result = request(api, coordinator, event, rooms[1], session_id=other.session_id, attendance=30)
    assert result.status_code == 400


def test_replacement_conflict_and_stale_original_leave_current_arrangements_intact(
    api, coordinator, venue_staff, event, rooms
):
    from apps.venues.bookings import withdraw_booking
    from apps.venues.models import VenueBlock

    main = booking(api, coordinator, event, rooms[0])
    assert approve(api, venue_staff, main).status_code == 200
    replacement_room = make_venue(
        name="Alternate Hall", capacity=120, opens_at=time(8), closes_at=time(22)
    )
    proposal = booking(
        api, coordinator, event, replacement_room, session_id=main.session_id, replaces_id=main.pk
    )
    block = VenueBlock.objects.create(
        venue=replacement_room, starts_at=START, ends_at=END, reason="Maintenance"
    )
    assert approve(api, venue_staff, proposal).status_code == 409
    main.refresh_from_db()
    proposal.refresh_from_db()
    assert (main.status, proposal.status) == ("APPROVED", "PENDING")
    block.delete()
    withdraw_booking(
        booking=main, actor=coordinator, expected_status="APPROVED", confirm_release=True
    )
    assert approve(api, venue_staff, proposal).status_code == 409
    proposal.refresh_from_db()
    assert proposal.status == "PENDING"


def test_two_required_sessions_cancellation_releases_both_with_history(
    api, coordinator, venue_staff, event, rooms
):
    main = booking(api, coordinator, event, rooms[0])
    other = breakout(api, coordinator, event, rooms[1])
    for item in (main, other):
        assert approve(api, venue_staff, item).status_code == 200
    api.force_authenticate(coordinator)
    preview = api.get(f"/api/events/{event.pk}/cancellation-preview/").data
    assert len(preview["venue_bookings"]) == 2
    result = api.post(
        f"/api/events/{event.pk}/cancel/",
        {
            "expected_version": preview["version"],
            "confirm_cancel": True,
            "reason": "Client cancellation",
        },
        format="json",
    )
    assert result.status_code == 200
    for item in (main, other):
        item.refresh_from_db()
        assert item.status == "WITHDRAWN" and item.history.count() == 3


def test_shared_writers_reject_foreign_session_even_without_the_http_adapter(
    api, coordinator, organiser, event, rooms
):
    from apps.venues.bookings import create_booking_record

    foreign_event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    foreign = EventSession.objects.create(event=foreign_event, name="Main programme", kind="MAIN")
    with pytest.raises(BookingValidationError):
        create_booking_record(
            event=event,
            venue=rooms[0],
            session=foreign,
            requested_by=coordinator,
            starts_at=START,
            ends_at=END,
            attendance=120,
        )
    with pytest.raises(ValueError, match="belong"):
        VenueBooking.objects.create(
            event=event,
            venue=rooms[0],
            session=foreign,
            starts_at=START,
            ends_at=END,
            attendance=120,
        )
    assert not event.venue_bookings.exists()


def test_shared_transition_cannot_bypass_one_approval_per_session(
    api, coordinator, venue_staff, event, rooms
):
    from apps.venues.bookings import transition_booking

    main = booking(api, coordinator, event, rooms[0])
    second = booking(
        api,
        coordinator,
        event,
        rooms[0],
        starts_at=(END + timedelta(hours=1)).isoformat(),
        ends_at=(END + timedelta(hours=2)).isoformat(),
    )
    assert approve(api, venue_staff, main).status_code == 200
    with pytest.raises(BookingValidationError):
        transition_booking(second, "APPROVED", venue_staff)
    assert event.venue_bookings.filter(status="APPROVED").count() == 1


def test_inactive_session_is_refused_by_both_approval_entry_points(
    api, coordinator, venue_staff, event, rooms
):
    from apps.venues.bookings import transition_booking

    other = breakout(api, coordinator, event, rooms[1])
    # Low-level suspended-session fixture: production removal refuses active requests.
    EventSession.objects.filter(pk=other.session_id).update(is_active=False)
    assert approve(api, venue_staff, other).status_code == 400
    with pytest.raises(BookingValidationError):
        transition_booking(other, "APPROVED", venue_staff)
    assert other.history.count() == 1


def test_readiness_cannot_pass_with_a_missing_main_identity(
    api, coordinator, venue_staff, event, rooms
):
    other = breakout(api, coordinator, event, rooms[1])
    assert approve(api, venue_staff, other).status_code == 200
    # Low-level malformed import fixture: an approved breakout must never stand in for main.
    EventSession.objects.filter(event=event, kind="MAIN").delete()
    assert any("main programme" in gap for gap in arrangement_gaps(event))


def test_session_list_success_and_removal_rereads_assignment(
    api, coordinator, venue_staff, second_coordinator, event, rooms
):
    from apps.core.models import AuditLog
    from apps.venues.sessions import remove_session as real_remove

    other = breakout(api, coordinator, event, rooms[1])
    response = api.get(f"/api/events/{event.pk}/venue-sessions/")
    assert response.status_code == 200
    assert [s["name"] for s in response.data] == ["Main programme", "Breakout A"]
    api.post(
        f"/api/events/{event.pk}/venue-bookings/{other.pk}/withdraw/",
        {"expected_status": "PENDING"},
        format="json",
    )

    def reassign_then_remove(session, actor):
        type(event).objects.filter(pk=event.pk).update(coordinator=second_coordinator)
        return real_remove(session, actor)

    with patch("apps.venues.sessions.remove_session", side_effect=reassign_then_remove):
        result = api.post(
            f"/api/events/{event.pk}/venue-sessions/{other.session_id}/remove/", {}, format="json"
        )
    assert result.status_code == 403
    other.session.refresh_from_db()
    assert other.session.is_active
    assert AuditLog.objects.filter(
        actor=coordinator, allowed=False, detail__contains="assignment changed"
    ).exists()
