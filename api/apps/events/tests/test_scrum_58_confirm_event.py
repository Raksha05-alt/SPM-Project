"""SCRUM-58 - Confirm an event after essential arrangements are complete (gate G22).

As an Event Coordinator, I want to confirm an event after its essential
arrangements are approved, so that the Event Organiser and Attendees can rely
on a complete event plan.

Arrangements are made through the real actions (SCRUM-11/72 venue, SCRUM-74/16
equipment, SCRUM-90 safety), using the SCRUM-90 test helpers.
Case IDs follow the Sprint 3 guide: S3-SCRUM-58-<case>.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentHistoryAction, EquipmentType
from apps.equipment.services import create_request
from apps.events.confirmation import (
    ConfirmationBlocked,
    ConfirmationRefused,
    confirm_event,
    readiness,
)
from apps.events.models import EventStatusHistory
from apps.notifications.models import Notification, NotificationKind
from apps.safety.models import SafetyStatus
from apps.safety.services import decide, request_check
from apps.safety.tests.conftest import (  # noqa: F401 - fixtures used by name
    approve_equipment,
    approve_venue,
    make_venue,
)
from apps.safety.tests.conftest import (
    planning_event as planning_event,
)
from apps.safety.tests.conftest import (
    ready_event as ready_event,
)
from apps.safety.tests.conftest import (
    safety_officer as safety_officer,
)
from apps.safety.tests.conftest import (
    tech as tech,
)
from apps.safety.tests.conftest import (
    venue as venue,
)
from apps.venues.bookings import reject_booking, request_booking
from apps.venues.models import VenueBlock

SAFETY_MISSING = "Operational safety check: no approved check."


def readiness_url(event):
    return f"/api/events/{event.pk}/readiness/"


def confirm_url(event):
    return f"/api/events/{event.pk}/confirm/"


def arrangements_url(event):
    return f"/api/events/{event.pk}/confirmed-arrangements/"


def unavailable_url(item):
    return f"/api/equipment/requests/{item.pk}/unavailable/"


@pytest.fixture
def approved_event(ready_event, coordinator, safety_officer):  # noqa: F811
    """Venue, equipment and the Operational Safety Check are all approved."""
    check = request_check(ready_event, coordinator)
    decide(check, safety_officer, SafetyStatus.APPROVED)
    ready_event.refresh_from_db()
    return ready_event


@pytest.fixture
def coordinator_api(api, coordinator):
    api.force_authenticate(coordinator)
    return api


def notices(kind):
    return Notification.objects.filter(kind=kind)


# S3-SCRUM-58-01 - AC1/AC4/AC5: a complete event is confirmed and the organiser told.


@pytest.mark.django_db
def test_s3_58_01_ac1_ac4_the_coordinator_confirms_a_complete_event(
    coordinator_api, approved_event, coordinator
):
    ready = coordinator_api.get(readiness_url(approved_event)).data
    assert ready["can_confirm"] is True
    assert ready["missing"] == []
    assert all(item["ready"] for item in ready["items"])

    response = coordinator_api.post(confirm_url(approved_event), {}, format="json")

    assert response.status_code == 200
    approved_event.refresh_from_db()
    assert approved_event.status == EventStatus.CONFIRMED
    # AC4 - the coordinator and the timestamp are recorded.
    assert approved_event.confirmed_by == coordinator
    assert approved_event.confirmed_at == approved_event.status_changed_at
    history = EventStatusHistory.objects.filter(event=approved_event).first()
    assert (history.from_status, history.to_status, history.changed_by) == (
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
        coordinator,
    )
    assert response.data["event"]["confirmed_by_name"] == "Cora Coordinator"


@pytest.mark.django_db
def test_s3_58_01_ac5_the_organiser_is_notified_and_sees_the_arrangements(
    api,
    approved_event,
    coordinator,
    organiser,
    venue,  # noqa: F811
):
    confirm_event(approved_event, coordinator)

    # SCRUM-79 AC4 also tells the involved staff; this is the organiser's notice.
    notice = notices(NotificationKind.EVENT_CONFIRMED).get(recipient=organiser)
    assert notice.recipient == organiser
    assert "is confirmed" in notice.message
    assert "Harbour Hall" in notice.message
    assert "2 x Projector" in notice.message

    api.force_authenticate(organiser)
    data = api.get(arrangements_url(approved_event)).data
    assert [v["venue"] for v in data["venues"]] == ["Harbour Hall"]
    assert data["venues"][0]["layout"] == "Theatre"
    assert data["equipment"] == [{"equipment": "Projector", "quantity": 2}]
    assert data["safety_approved_at"] is not None
    assert data["confirmed_by_name"] == "Cora Coordinator"
    # Staff notes are not part of the organiser's view.
    assert "technical_requirements" not in str(data)


@pytest.mark.django_db
def test_s3_58_01_ac5_another_organisation_cannot_see_the_arrangements(
    api, approved_event, coordinator, other_organiser
):
    confirm_event(approved_event, coordinator)
    api.force_authenticate(other_organiser)

    assert api.get(arrangements_url(approved_event)).status_code == 403
    assert AuditLog.objects.filter(actor=other_organiser, allowed=False).exists()


@pytest.mark.django_db
def test_s3_58_01_ac5_arrangements_are_not_shown_before_confirmation(
    api, approved_event, organiser
):
    api.force_authenticate(organiser)

    assert api.get(arrangements_url(approved_event)).status_code == 404


# S3-SCRUM-58-02 - AC2: each missing item blocks confirmation and is listed.


def assert_not_confirmed(event):
    event.refresh_from_db()
    assert event.status == EventStatus.PLANNING
    assert event.confirmed_by is None and event.confirmed_at is None
    assert not EventStatusHistory.objects.filter(
        event=event, to_status=EventStatus.CONFIRMED
    ).exists()
    assert not notices(NotificationKind.EVENT_CONFIRMED).exists()


@pytest.mark.django_db
def test_s3_58_02_ac2_without_a_safety_approval_the_check_is_listed(
    coordinator_api,
    ready_event,  # noqa: F811
):
    response = coordinator_api.post(confirm_url(ready_event), {}, format="json")

    assert response.status_code == 409
    assert response.data["missing"] == [SAFETY_MISSING]
    assert_not_confirmed(ready_event)


@pytest.mark.django_db
def test_s3_58_02_ac2_a_pending_safety_check_is_listed(
    coordinator_api,
    ready_event,
    coordinator,  # noqa: F811
):
    request_check(ready_event, coordinator)

    response = coordinator_api.post(confirm_url(ready_event), {}, format="json")

    assert response.data["missing"] == [
        "Operational safety check: still awaiting a Safety Officer."
    ]
    assert_not_confirmed(ready_event)


@pytest.mark.django_db
def test_s3_58_02_ac2_with_nothing_arranged_every_item_is_listed(
    coordinator_api,
    planning_event,  # noqa: F811
):
    response = coordinator_api.post(confirm_url(planning_event), {}, format="json")

    assert response.status_code == 409
    assert response.data["missing"] == [
        "Venue: no venue booking has been approved by Venue Staff.",
        "Technical: the equipment plan has not been approved by Technical Support.",
        SAFETY_MISSING,
    ]
    assert response.data["readiness"]["can_confirm"] is False
    assert_not_confirmed(planning_event)


@pytest.mark.django_db
def test_s3_58_02_ac2_a_venue_awaiting_a_decision_is_listed(
    coordinator_api,
    planning_event,
    venue,
    coordinator,
    tech,  # noqa: F811
):
    request_booking(
        event=planning_event,
        venue=venue,
        requested_by=coordinator,
        starts_at=planning_event.preferred_start,
        ends_at=planning_event.preferred_end,
        attendance=120,
        layout="THEATRE",
    )
    approve_equipment(planning_event, tech)

    missing = coordinator_api.post(confirm_url(planning_event), {}, format="json").data["missing"]

    assert "Venue: the booking request for Harbour Hall is still awaiting Venue Staff." in missing
    assert "Venue: no venue booking has been approved by Venue Staff." in missing
    assert_not_confirmed(planning_event)


@pytest.mark.django_db
def test_s3_58_02_ac2_equipment_not_reserved_is_listed(
    coordinator_api,
    planning_event,
    venue,
    venue_staff,
    coordinator,  # noqa: F811
):
    approve_venue(planning_event, venue, venue_staff)
    mic, _ = EquipmentType.objects.get_or_create(
        code="MIC", defaults={"name": "Microphone", "total_quantity": 5}
    )
    create_request(
        event=planning_event, requested_by=coordinator, equipment_type=mic.pk, quantity=3
    )

    missing = coordinator_api.post(confirm_url(planning_event), {}, format="json").data["missing"]

    assert "Equipment: 3 x Microphone is requested but not reserved." in missing
    assert_not_confirmed(planning_event)


@pytest.mark.django_db
def test_s3_58_02_ac2_a_block_added_after_safety_approval_blocks_confirmation(
    coordinator_api,
    approved_event,
    venue,  # noqa: F811
):
    VenueBlock.objects.create(
        venue=venue,
        reason="Flood repairs",
        starts_at=approved_event.preferred_start,
        ends_at=approved_event.preferred_end,
    )

    response = coordinator_api.post(confirm_url(approved_event), {}, format="json")

    assert response.status_code == 409
    assert (
        "Venue: Harbour Hall is blocked during the booked period (Flood repairs)."
        in (response.data["missing"])
    )
    assert_not_confirmed(approved_event)


@pytest.mark.django_db
def test_s3_58_02_ac2_a_venue_taken_out_of_service_blocks_confirmation(
    coordinator_api,
    approved_event,
    venue,  # noqa: F811
):
    venue.in_service = False
    venue.save(update_fields=["in_service"])

    response = coordinator_api.post(confirm_url(approved_event), {}, format="json")

    assert "Venue: Harbour Hall is out of service." in response.data["missing"]
    assert_not_confirmed(approved_event)


# S3-SCRUM-58-03 - AC3: an unavailable resource reaches the organiser with its reason.


@pytest.mark.django_db
def test_s3_58_03_ac3_a_rejected_venue_tells_the_organiser_why(
    planning_event,
    venue,
    venue_staff,
    coordinator,
    organiser,  # noqa: F811
):
    booking = request_booking(
        event=planning_event,
        venue=venue,
        requested_by=coordinator,
        starts_at=planning_event.preferred_start,
        ends_at=planning_event.preferred_end,
        attendance=120,
        layout="THEATRE",
    )

    reject_booking(booking, venue_staff, "Hall closed for renovation.")

    notice = notices(NotificationKind.RESOURCE_UNAVAILABLE).get()
    assert notice.recipient == organiser
    assert "Reason: Hall closed for renovation." in notice.message
    assert "not confirmed" in notice.message
    ready = readiness(planning_event)
    assert ready["unavailable"] == [
        "Venue: Venue Staff rejected Harbour Hall: Hall closed for renovation."
    ]
    assert ready["can_confirm"] is False
    with pytest.raises(ConfirmationBlocked):
        confirm_event(planning_event, coordinator)
    assert_not_confirmed(planning_event)


@pytest.fixture
def unreserved_item(planning_event, coordinator):  # noqa: F811
    mic, _ = EquipmentType.objects.get_or_create(
        code="MIC", defaults={"name": "Microphone", "total_quantity": 5}
    )
    item = create_request(
        event=planning_event, requested_by=coordinator, equipment_type=mic.pk, quantity=3
    )
    item.refresh_from_db()
    return item


@pytest.mark.django_db
def test_s3_58_03_ac3_unavailable_equipment_tells_the_organiser_why(
    api,
    tech,
    unreserved_item,
    planning_event,
    organiser,
    coordinator,  # noqa: F811
):
    api.force_authenticate(tech)

    response = api.post(
        unavailable_url(unreserved_item), {"reason": "All units out for repair."}, format="json"
    )

    assert response.status_code == 200
    entry = unreserved_item.history.get(action=EquipmentHistoryAction.UNAVAILABLE)
    assert (entry.reason, entry.actor) == ("All units out for repair.", tech)
    notice = notices(NotificationKind.RESOURCE_UNAVAILABLE).get()
    assert notice.recipient == organiser
    assert "3 x Microphone cannot be provided" in notice.message
    assert "Reason: All units out for repair." in notice.message
    assert notices(NotificationKind.EQUIPMENT_UPDATED).filter(recipient=coordinator).exists()
    assert readiness(planning_event)["unavailable"] == [
        "Equipment: Technical Support recorded 3 x Microphone as unavailable: "
        "All units out for repair."
    ]
    assert_not_confirmed(planning_event)


@pytest.mark.django_db
@pytest.mark.parametrize("body", [{}, {"reason": "   "}])
def test_s3_58_03_ac3_unavailable_needs_a_reason(api, tech, unreserved_item, body):  # noqa: F811
    api.force_authenticate(tech)

    response = api.post(unavailable_url(unreserved_item), body, format="json")

    assert response.status_code == 400
    assert not unreserved_item.history.filter(action=EquipmentHistoryAction.UNAVAILABLE).exists()
    assert not notices(NotificationKind.RESOURCE_UNAVAILABLE).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["coordinator", "organiser", "venue_staff"])
def test_s3_58_03_only_technical_support_record_unavailability(api, unreserved_item, request, who):
    api.force_authenticate(request.getfixturevalue(who))

    response = api.post(unavailable_url(unreserved_item), {"reason": "No."}, format="json")

    assert response.status_code == 403
    assert not notices(NotificationKind.RESOURCE_UNAVAILABLE).exists()


# S3-SCRUM-58-04 - authority: only the assigned coordinator, only from Planning.


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["second_coordinator", "organiser", "lead", "venue_staff"])
def test_s3_58_04_only_the_assigned_coordinator_confirms(api, approved_event, request, who):
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    assert api.post(confirm_url(approved_event), {}, format="json").status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()
    assert_not_confirmed(approved_event)


@pytest.mark.django_db
def test_s3_58_04_a_reassigned_coordinator_can_no_longer_confirm(
    approved_event, coordinator, second_coordinator
):
    approved_event.coordinator = second_coordinator
    approved_event.save(update_fields=["coordinator"])

    from apps.events.services import NotAssignedCoordinator

    with pytest.raises(NotAssignedCoordinator):
        confirm_event(approved_event, coordinator)
    assert_not_confirmed(approved_event)


@pytest.mark.django_db
def test_s3_58_04_the_payload_cannot_forge_the_confirmer(
    coordinator_api, approved_event, coordinator, lead
):
    coordinator_api.post(
        confirm_url(approved_event),
        {"confirmed_by": lead.pk, "confirmed_at": "2020-01-01T00:00:00Z"},
        format="json",
    )

    approved_event.refresh_from_db()
    assert approved_event.confirmed_by == coordinator
    assert approved_event.confirmed_at.year > 2020


@pytest.mark.django_db
def test_s3_58_04_a_confirmed_event_cannot_be_confirmed_twice(approved_event, coordinator):
    confirm_event(approved_event, coordinator)

    with pytest.raises(ConfirmationRefused, match="already confirmed"):
        confirm_event(approved_event, coordinator)
    confirmed = notices(NotificationKind.EVENT_CONFIRMED)
    assert confirmed.filter(recipient=approved_event.created_by).count() == 1
    # One notice per recipient (organiser and the involved staff), never two.
    assert confirmed.count() == confirmed.values("recipient").distinct().count()


@pytest.mark.django_db
@pytest.mark.parametrize("status", [EventStatus.APPROVED, EventStatus.CANCELLED])
def test_s3_58_04_only_a_planning_event_is_confirmed(coordinator_api, approved_event, status):
    approved_event.status = status
    approved_event.save(update_fields=["status"])

    assert coordinator_api.post(confirm_url(approved_event), {}, format="json").status_code == 409
    approved_event.refresh_from_db()
    assert approved_event.status == status


@pytest.mark.django_db
def test_s3_58_04_readiness_is_for_the_assigned_coordinator(
    api, approved_event, second_coordinator, lead
):
    api.force_authenticate(second_coordinator)
    assert api.get(readiness_url(approved_event)).status_code == 403
    api.force_authenticate(lead)
    assert api.get(readiness_url(approved_event)).status_code == 200


# S3-SCRUM-58-05 - stale and concurrent confirmations cannot bypass the checks.


@pytest.mark.django_db
def test_s3_58_05_a_change_after_safety_approval_requires_a_new_check(
    coordinator_api,
    approved_event,
    tech,  # noqa: F811
):
    # A new reserved equipment line changes the arrangement version.
    approve_equipment(approved_event, tech, quantity=1, name="Speaker")

    response = coordinator_api.post(confirm_url(approved_event), {}, format="json")

    assert response.status_code == 409
    assert any("Operational safety check" in item for item in response.data["missing"])
    assert_not_confirmed(approved_event)


@pytest.mark.django_db
def test_s3_58_05_a_failed_notice_leaves_no_confirmation(approved_event, coordinator):
    from unittest import mock

    with (
        # Every notice is written by the shared SCRUM-79 writer's bulk_create.
        mock.patch.object(Notification.objects, "bulk_create", side_effect=RuntimeError("down")),
        pytest.raises(RuntimeError),
    ):
        confirm_event(approved_event, coordinator)
    assert_not_confirmed(approved_event)


@pytest.mark.django_db(transaction=True)
def test_s3_58_05_concurrent_confirmations_confirm_once(
    organiser,
    coordinator,
    lead,
    venue_staff,
    safety_officer,
    tech,  # noqa: F811
):
    if connection.vendor != "postgresql":
        pytest.skip("Row locks require PostgreSQL")
    from apps.safety.tests.conftest import daytime_period
    from conftest import make_event

    start, end = daytime_period()
    event = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        supervising_lead=lead,
        required_layout="THEATRE",
        preferred_start=start,
        preferred_end=end,
    )
    approve_venue(event, make_venue(), venue_staff)
    approve_equipment(event, tech)
    decide(request_check(event, coordinator), safety_officer, SafetyStatus.APPROVED)
    barrier = Barrier(2)

    def attempt(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                confirm_event(event, coordinator)
                return "confirmed"
            except ConfirmationRefused:
                return "refused"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["confirmed", "refused"]
    confirmed = Notification.objects.filter(kind=NotificationKind.EVENT_CONFIRMED)
    assert confirmed.filter(recipient=organiser).count() == 1
    assert confirmed.count() == confirmed.values("recipient").distinct().count()


@pytest.mark.django_db
@pytest.mark.parametrize("actor_fixture", ["lead", "coordinator"])
def test_scrum58_readiness_hides_draft_arrangements(api, planning_event, actor_fixture, request):
    planning_event.status = EventStatus.DRAFT
    planning_event.save(update_fields=["status"])
    actor = request.getfixturevalue(actor_fixture)
    api.force_authenticate(actor)
    response = api.get(readiness_url(planning_event))
    assert response.status_code == 403
    assert response.data["detail"] == "This event is not available."
    assert AuditLog.objects.filter(
        actor=actor, allowed=False, detail="drafts are not visible"
    ).exists()


@pytest.mark.django_db
def test_scrum58_arrangements_refuse_the_previous_coordinator(
    api, approved_event, coordinator, second_coordinator
):
    confirm_event(approved_event, coordinator)
    approved_event.coordinator = second_coordinator
    approved_event.save(update_fields=["coordinator"])
    api.force_authenticate(coordinator)
    response = api.get(arrangements_url(approved_event))
    assert response.status_code == 403
    assert "assigned" in str(response.data["detail"])
    assert "venues" not in response.data
    assert AuditLog.objects.filter(
        actor=coordinator, allowed=False, detail="event is not assigned to this coordinator"
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("invalid", ["event_closed", "request_withdrawn"])
def test_scrum58_unavailability_refuses_closed_events_or_withdrawn_requests(
    api, unreserved_item, tech, invalid
):
    from apps.equipment.models import EquipmentRequestStatus

    if invalid == "event_closed":
        unreserved_item.plan.event.status = EventStatus.CANCELLED
        unreserved_item.plan.event.save(update_fields=["status"])
    else:
        unreserved_item.status = EquipmentRequestStatus.WITHDRAWN
        unreserved_item.save(update_fields=["status"])
    api.force_authenticate(tech)
    response = api.post(
        unavailable_url(unreserved_item), {"reason": "No stock available."}, format="json"
    )
    assert response.status_code == 409
    assert not unreserved_item.history.filter(action=EquipmentHistoryAction.UNAVAILABLE).exists()
    assert not Notification.objects.filter(kind=NotificationKind.RESOURCE_UNAVAILABLE).exists()
