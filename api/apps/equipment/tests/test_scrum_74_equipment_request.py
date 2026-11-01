"""SCRUM-74 - Record equipment required for an event (Sprint 3 gate G14).

As an Event Coordinator, I want to record the equipment an event requires with
quantities and technical details, so that Technical Support Staff know exactly
what to provide.

Case IDs follow the Sprint 3 guide: S3-74-<case>.
"""

from unittest import mock

import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentHistory,
    EquipmentHistoryAction,
    EquipmentPlan,
    EquipmentRequest,
    EquipmentRequestStatus,
    EquipmentType,
)
from apps.equipment.services import EquipmentRequestError, create_request
from apps.events.models import EventStatusHistory
from apps.events.services import assign_coordinator
from apps.notifications.models import Notification, NotificationKind
from apps.safety.models import SafetyStatus
from apps.safety.tests.conftest import make_check
from conftest import make_event

NOTE = "HDMI and USB-C inputs; mount at the back of the hall; spare lamp on site"


def url(event):
    return f"/api/events/{event.pk}/equipment-requests/"


INBOX = "/api/equipment/requests/"


@pytest.fixture
def gala(organiser, coordinator):
    """An Approved event assigned to Cora."""
    return make_event(
        organiser, status=EventStatus.APPROVED, coordinator=coordinator, name="Annual Gala"
    )


@pytest.fixture
def microphone(db):
    return EquipmentType.objects.create(code="MIC", name="Wireless microphone", total_quantity=6)


@pytest.fixture
def coordinator_api(api, coordinator):
    api.force_authenticate(coordinator)
    return api


def post(api, event, **body):
    return api.post(url(event), body, format="json")


def requests_for(event):
    return EquipmentRequest.objects.filter(plan__event=event)


def notices():
    return Notification.objects.filter(kind=NotificationKind.EQUIPMENT_REQUESTED)


# S3-74-01 - AC1/AC3: type, quantity and technical note saved exactly; staff see them.


@pytest.mark.django_db
def test_s3_74_01_ac1_the_coordinator_records_type_quantity_and_requirements(
    coordinator_api, gala, stock
):
    response = post(
        coordinator_api, gala, equipment_type=stock.pk, quantity=3, technical_requirements=NOTE
    )

    assert response.status_code == 201
    assert response.data["detail"] == (
        "Your request for 3 x Projector has been sent to Technical Support."
    )
    saved = requests_for(gala).get()
    assert (saved.equipment_type_id, saved.quantity, saved.technical_requirements) == (
        stock.pk,
        3,
        NOTE,
    )
    assert saved.status == EquipmentRequestStatus.REQUESTED
    body = response.data["request"]
    assert (body["id"], body["event"], body["equipment_type_name"]) == (
        saved.pk,
        gala.pk,
        "Projector",
    )


@pytest.mark.django_db
def test_s3_74_01_ac1_technical_requirements_are_optional(coordinator_api, gala, stock):
    response = post(coordinator_api, gala, equipment_type=stock.pk, quantity=1)

    assert response.status_code == 201
    assert requests_for(gala).get().technical_requirements == ""


@pytest.mark.django_db
def test_s3_74_01_ac1_null_technical_requirements_are_saved_as_empty(
    coordinator_api, gala, stock
):
    response = post(
        coordinator_api, gala, equipment_type=stock.pk, quantity=1, technical_requirements=None
    )

    assert response.status_code == 201
    assert requests_for(gala).get().technical_requirements == ""


@pytest.mark.django_db
def test_s3_74_01_ac1_surrounding_spaces_are_trimmed(coordinator_api, gala, stock):
    post(coordinator_api, gala, equipment_type=stock.pk, quantity=2, technical_requirements="  x ")

    assert requests_for(gala).get().technical_requirements == "x"


@pytest.mark.django_db
def test_s3_74_01_ac3_technical_support_see_every_item_exactly(
    api, coordinator, tech, gala, stock, microphone
):
    api.force_authenticate(coordinator)
    post(api, gala, equipment_type=stock.pk, quantity=3, technical_requirements=NOTE)
    post(api, gala, equipment_type=microphone.pk, quantity=4, technical_requirements="Lapel")

    # A fresh read as Technical Support, not the coordinator's response.
    api.force_authenticate(tech)
    rows = api.get(url(gala)).data

    assert [
        (r["equipment_type_name"], r["quantity"], r["technical_requirements"]) for r in rows
    ] == [("Projector", 3, NOTE), ("Wireless microphone", 4, "Lapel")]
    assert {r["requested_by_name"] for r in rows} == {"Cora Coordinator"}


@pytest.mark.django_db
def test_s3_74_01_ac3_the_technical_inbox_lists_the_event_and_its_items(
    api, coordinator, tech, gala, stock
):
    api.force_authenticate(coordinator)
    post(api, gala, equipment_type=stock.pk, quantity=3, technical_requirements=NOTE)

    api.force_authenticate(tech)
    [event] = api.get(INBOX).data

    assert (event["id"], event["name"], event["coordinator_name"]) == (
        gala.pk,
        "Annual Gala",
        "Cora Coordinator",
    )
    assert event["status"] == EventStatus.PLANNING
    [item] = event["equipment_requests"]
    assert (item["equipment_type_name"], item["quantity"], item["technical_requirements"]) == (
        "Projector",
        3,
        NOTE,
    )


@pytest.mark.django_db
def test_s3_74_01_ac3_the_technical_view_holds_only_what_staff_need(
    api, coordinator, tech, gala, stock
):
    api.force_authenticate(coordinator)
    post(api, gala, equipment_type=stock.pk, quantity=3)

    api.force_authenticate(tech)
    [event] = api.get(INBOX).data

    # Guide: a scoped read, not the full event record (no purpose, organisation
    # contact or other planning details).
    assert set(event) == {
        "id",
        "name",
        "status",
        "status_label",
        "preferred_start",
        "preferred_end",
        "expected_attendance",
        "coordinator_name",
        "equipment_requests",
    }


@pytest.mark.django_db
def test_s3_74_01_the_assigned_coordinator_and_leads_read_the_requests(
    api, coordinator, lead, gala, stock
):
    create_request(event=gala, requested_by=coordinator, equipment_type=stock.pk, quantity=2)

    for user in (coordinator, lead):
        api.force_authenticate(user)
        assert [r["quantity"] for r in api.get(url(gala)).data] == [2]


@pytest.mark.django_db
def test_s3_74_01_the_catalogue_offers_only_in_service_types(coordinator_api, stock, microphone):
    EquipmentType.objects.create(code="OHP", name="Overhead projector", in_service=False)

    names = [row["name"] for row in coordinator_api.get("/api/equipment/types/").data]

    assert names == ["Projector", "Wireless microphone"]


# S3-74-02 - AC2: zero, negative and non-whole quantities are refused, nothing created.


@pytest.mark.django_db
@pytest.mark.parametrize(
    "quantity",
    [0, -1, -10, 2.5, 3.0, "3", True, None, ""],
    ids=["zero", "minus-one", "minus-ten", "fraction", "float", "text", "boolean", "null", "blank"],
)
def test_s3_74_02_ac2_a_quantity_below_one_or_not_whole_is_refused(
    coordinator_api, gala, stock, quantity
):
    response = post(coordinator_api, gala, equipment_type=stock.pk, quantity=quantity)

    assert response.status_code == 400
    assert response.data["quantity"] in (
        ["The quantity must be a whole number of 1 or more."],
        ["Enter the quantity required."],
    )
    assert not EquipmentRequest.objects.exists()
    assert not EquipmentPlan.objects.exists()
    assert not notices().exists()
    gala.refresh_from_db()
    assert gala.status == EventStatus.APPROVED


@pytest.mark.django_db
def test_s3_74_02_ac2_a_missing_quantity_is_named(coordinator_api, gala, stock):
    response = post(coordinator_api, gala, equipment_type=stock.pk)

    assert response.status_code == 400
    assert response.data["quantity"] == ["Enter the quantity required."]


@pytest.mark.django_db
def test_s3_74_02_ac2_every_problem_is_named_together(coordinator_api, gala):
    response = post(coordinator_api, gala, quantity=0, technical_requirements=["not", "text"])

    assert response.status_code == 400
    assert response.data["detail"] == "The equipment request could not be saved."
    assert response.data["equipment_type"] == ["Choose the equipment type."]
    assert response.data["quantity"] == ["The quantity must be a whole number of 1 or more."]
    assert response.data["technical_requirements"] == ["Technical requirements must be text."]


@pytest.mark.django_db
def test_s3_74_02_ac2_the_service_refuses_zero_too(coordinator, gala, stock):
    with pytest.raises(EquipmentRequestError) as refused:
        create_request(event=gala, requested_by=coordinator, equipment_type=stock.pk, quantity=0)

    assert "quantity" in refused.value.errors
    assert not EquipmentRequest.objects.exists()


# S3-74-03 - AC4: who requested and when, history, and Technical Support notified once.


@pytest.mark.django_db
def test_s3_74_03_ac4_the_requesting_user_and_time_are_recorded(
    coordinator_api, coordinator, gala, stock
):
    before = timezone.now()
    post(coordinator_api, gala, equipment_type=stock.pk, quantity=3, technical_requirements=NOTE)
    after = timezone.now()

    saved = requests_for(gala).get()
    assert saved.requested_by == coordinator
    assert before <= saved.requested_at <= after
    [entry] = EquipmentHistory.objects.filter(request=saved)
    assert (entry.action, entry.actor, entry.plan_revision) == (
        EquipmentHistoryAction.REQUESTED,
        coordinator,
        1,
    )
    assert entry.before == {}
    assert entry.after == {
        "equipment_type": stock.pk,
        "quantity": 3,
        "technical_requirements": NOTE,
        "status": EquipmentRequestStatus.REQUESTED,
    }


@pytest.mark.django_db
def test_s3_74_03_ac4_each_active_technical_support_member_is_notified_once(
    coordinator_api, tech, venue_staff, lead, gala, stock
):
    second = User.objects.create_user(
        username="tech2", email="tech2@example.com", role=Role.TECHNICAL_SUPPORT
    )
    User.objects.create_user(
        username="gone", email="gone@example.com", role=Role.TECHNICAL_SUPPORT, is_active=False
    )

    post(coordinator_api, gala, equipment_type=stock.pk, quantity=3)

    assert sorted(n.recipient_id for n in notices()) == sorted([tech.pk, second.pk])
    notice = notices().get(recipient=tech)
    assert notice.event == gala
    assert notice.message == (
        'Cora Coordinator requested 3 x Projector for "Annual Gala". Review it in Equipment.'
    )


@pytest.mark.django_db
def test_s3_74_03_ac4_a_refused_request_notifies_no_one(coordinator_api, tech, gala, stock):
    post(coordinator_api, gala, equipment_type=stock.pk, quantity=0)

    assert not notices().exists()


# S3-74-04 - AC5: only the assigned coordinator adds requests; ownership changes apply.


@pytest.mark.django_db
def test_s3_74_04_ac5_an_unassigned_coordinator_is_refused(
    api, second_coordinator, tech, gala, stock
):
    api.force_authenticate(second_coordinator)

    response = post(api, gala, equipment_type=stock.pk, quantity=3)

    assert response.status_code == 403
    assert response.data["detail"] == (
        "Only the coordinator assigned to this event can request equipment."
    )
    assert AuditLog.objects.filter(actor=second_coordinator, allowed=False).exists()
    assert not EquipmentRequest.objects.exists()
    assert not notices().exists()


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["lead", "organiser", "attendee", "venue_staff", "tech"])
def test_s3_74_04_ac5_other_roles_cannot_add_requests(api, gala, stock, request, who):
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    response = post(api, gala, equipment_type=stock.pk, quantity=3)

    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()
    assert not EquipmentRequest.objects.exists()


@pytest.mark.django_db
def test_s3_74_04_ac5_after_reassignment_only_the_new_coordinator_can_add(
    api, coordinator, second_coordinator, lead, gala, stock, microphone
):
    first = create_request(
        event=gala, requested_by=coordinator, equipment_type=stock.pk, quantity=2
    )
    gala.refresh_from_db()
    assign_coordinator(gala, second_coordinator.pk, lead, gala.assignment_revision)

    api.force_authenticate(coordinator)
    refused = post(api, gala, equipment_type=microphone.pk, quantity=1)
    api.force_authenticate(second_coordinator)
    accepted = post(api, gala, equipment_type=microphone.pk, quantity=1)

    assert refused.status_code == 403
    assert accepted.status_code == 201
    # The earlier request keeps who actually made it.
    first.refresh_from_db()
    assert first.requested_by == coordinator
    assert requests_for(gala).get(equipment_type=microphone).requested_by == second_coordinator


@pytest.mark.django_db
def test_s3_74_04_ac5_the_previous_coordinator_can_no_longer_read_them(
    api, coordinator, second_coordinator, lead, gala, stock
):
    create_request(event=gala, requested_by=coordinator, equipment_type=stock.pk, quantity=2)
    gala.refresh_from_db()
    assign_coordinator(gala, second_coordinator.pk, lead, gala.assignment_revision)
    api.force_authenticate(coordinator)

    assert api.get(url(gala)).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["organiser", "attendee", "venue_staff", "second_coordinator"])
def test_s3_74_04_other_users_cannot_read_the_requests(api, coordinator, gala, stock, request, who):
    create_request(event=gala, requested_by=coordinator, equipment_type=stock.pk, quantity=2)
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    assert api.get(url(gala)).status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


@pytest.mark.django_db
def test_s3_74_04_technical_support_cannot_open_an_event_without_requests(api, tech, gala):
    api.force_authenticate(tech)

    assert api.get(url(gala)).status_code == 403
    assert AuditLog.objects.filter(actor=tech, allowed=False).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["coordinator", "lead", "organiser"])
def test_s3_74_04_only_technical_support_open_the_equipment_inbox(api, request, who):
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    assert api.get(INBOX).status_code == 403


@pytest.mark.django_db
def test_s3_74_04_the_inbox_leaves_out_events_with_only_withdrawn_requests(
    api, coordinator, tech, gala, stock
):
    made = create_request(event=gala, requested_by=coordinator, equipment_type=stock.pk, quantity=2)
    EquipmentRequest.objects.filter(pk=made.pk).update(status=EquipmentRequestStatus.WITHDRAWN)
    api.force_authenticate(tech)

    assert api.get(INBOX).data == []


# S3-74-05 - unknown type, wrong event state and tampering are refused; failures roll back.


@pytest.mark.django_db
@pytest.mark.parametrize("equipment_type", [999999, "PROJECTOR", 1.5, True])
def test_s3_74_05_an_unknown_equipment_type_is_refused(
    coordinator_api, gala, stock, equipment_type
):
    response = post(coordinator_api, gala, equipment_type=equipment_type, quantity=1)

    assert response.status_code == 400
    assert "equipment_type" in response.data
    assert not EquipmentRequest.objects.exists()


@pytest.mark.django_db
def test_s3_74_05_a_retired_equipment_type_is_refused(coordinator_api, gala, stock):
    stock.in_service = False
    stock.save()

    response = post(coordinator_api, gala, equipment_type=stock.pk, quantity=1)

    assert response.status_code == 400
    assert response.data["equipment_type"] == ["Projector is no longer offered for events."]


@pytest.mark.django_db
def test_s3_74_05_a_type_already_requested_is_refused(coordinator_api, gala, stock):
    post(coordinator_api, gala, equipment_type=stock.pk, quantity=2)

    response = post(coordinator_api, gala, equipment_type=stock.pk, quantity=5)

    assert response.status_code == 400
    assert response.data["equipment_type"] == [
        "Projector is already requested for this event. Change that request instead."
    ]
    assert list(requests_for(gala).values_list("quantity", flat=True)) == [2]


@pytest.mark.django_db
def test_s3_74_05_a_withdrawn_type_can_be_requested_again(coordinator_api, gala, stock):
    post(coordinator_api, gala, equipment_type=stock.pk, quantity=2)
    requests_for(gala).update(status=EquipmentRequestStatus.WITHDRAWN)

    response = post(coordinator_api, gala, equipment_type=stock.pk, quantity=4)

    assert response.status_code == 201
    assert requests_for(gala).count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "event_status",
    [
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.CONFIRMED,
        EventStatus.COMPLETED,
        EventStatus.CANCELLED,
        EventStatus.REJECTED,
    ],
)
def test_s3_74_05_requests_need_an_approved_or_planning_event(
    coordinator_api, organiser, coordinator, stock, event_status
):
    event = make_event(organiser, status=event_status, coordinator=coordinator)

    response = post(coordinator_api, event, equipment_type=stock.pk, quantity=1)

    assert response.status_code == 400
    assert response.data["event"] == [
        "Equipment can be requested once the event is approved; "
        f"this event is {EventStatus(event_status).label}."
    ]
    assert not EquipmentRequest.objects.exists()


@pytest.mark.django_db
def test_s3_74_05_a_draft_is_refused_and_not_readable(
    coordinator_api, organiser, coordinator, stock
):
    draft = make_event(organiser, coordinator=coordinator)

    assert post(coordinator_api, draft, equipment_type=stock.pk, quantity=1).status_code == 400
    assert coordinator_api.get(url(draft)).status_code == 403
    assert not EquipmentRequest.objects.exists()


@pytest.mark.django_db
def test_s3_74_05_an_event_or_plan_in_the_body_cannot_redirect_the_request(
    coordinator_api, organiser, coordinator, gala, stock
):
    other = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator, name="B")
    other_plan = EquipmentPlan.objects.create(event=other)

    body = {"equipment_type": stock.pk, "quantity": 1, "event": other.pk, "plan": other_plan.pk}
    response = coordinator_api.post(url(gala), body, format="json")

    assert response.status_code == 201
    assert requests_for(gala).count() == 1
    assert not requests_for(other).exists()


@pytest.mark.django_db
def test_s3_74_05_a_failed_history_write_leaves_no_request(coordinator, tech, gala, stock):
    with (
        mock.patch.object(EquipmentHistory.objects, "create", side_effect=RuntimeError("disk")),
        pytest.raises(RuntimeError),
    ):
        create_request(event=gala, requested_by=coordinator, equipment_type=stock.pk, quantity=3)

    assert not EquipmentRequest.objects.exists()
    assert not EquipmentPlan.objects.exists()
    assert not notices().exists()
    gala.refresh_from_db()
    assert gala.status == EventStatus.APPROVED


@pytest.mark.django_db
def test_s3_74_05_a_failed_notification_leaves_no_request(coordinator, tech, gala, stock):
    with (
        mock.patch.object(Notification.objects, "bulk_create", side_effect=RuntimeError("down")),
        pytest.raises(RuntimeError),
    ):
        create_request(event=gala, requested_by=coordinator, equipment_type=stock.pk, quantity=3)

    assert not EquipmentRequest.objects.exists()
    assert not EquipmentHistory.objects.exists()


# S3-74-06 - planning starts, and the change reaches the equipment plan and Safety.


@pytest.mark.django_db
def test_s3_74_06_the_first_request_starts_planning(coordinator_api, coordinator, gala, stock):
    post(coordinator_api, gala, equipment_type=stock.pk, quantity=1)

    gala.refresh_from_db()
    assert gala.status == EventStatus.PLANNING
    change = EventStatusHistory.objects.filter(event=gala).latest("pk")
    assert (change.from_status, change.to_status, change.changed_by) == (
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        coordinator,
    )


@pytest.mark.django_db
def test_s3_74_06_a_planning_event_stays_in_planning(
    coordinator_api, organiser, coordinator, stock
):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)

    assert post(coordinator_api, event, equipment_type=stock.pk, quantity=1).status_code == 201
    event.refresh_from_db()
    assert event.status == EventStatus.PLANNING
    assert not EventStatusHistory.objects.filter(event=event).exists()


@pytest.mark.django_db
def test_s3_74_06_each_request_is_a_new_equipment_plan_revision(
    coordinator_api, gala, stock, microphone
):
    post(coordinator_api, gala, equipment_type=stock.pk, quantity=1)
    post(coordinator_api, gala, equipment_type=microphone.pk, quantity=2)

    plan = EquipmentPlan.objects.get(event=gala)
    assert plan.revision == 2
    assert sorted(EquipmentHistory.objects.values_list("plan_revision", flat=True)) == [1, 2]


@pytest.mark.django_db
def test_s3_74_06_a_current_safety_check_no_longer_applies(
    coordinator_api, organiser, coordinator, stock
):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    check = make_check(event)

    post(coordinator_api, event, equipment_type=stock.pk, quantity=1)

    check.refresh_from_db()
    assert check.status == SafetyStatus.SUPERSEDED
