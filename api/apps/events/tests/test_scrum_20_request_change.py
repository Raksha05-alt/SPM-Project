"""SCRUM-20 - Request a change to an event (Sprint 4 gate INTAKE).

As an Event Organiser, I want to request a change to a submitted event, so that
its arrangements can reflect my updated requirements. Week 9: organisers cannot
edit after submission and a confirmed event cannot be edited directly, so a
change request is their only route.

Case IDs follow the Sprint 4 guide: S4-20-<case>. AC5's real decisions arrive
with SCRUM-78 (ASSESS); here the decision fields are shown as stored.
"""

import datetime
from unittest import mock

import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import EquipmentPlan, EquipmentRequest, EquipmentType
from apps.events.change_requests import ChangeRequestError, request_change, source_snapshot
from apps.events.models import ChangeRequestStatus, EventChangeRequest, EventFieldChange
from apps.notifications.models import Notification, NotificationKind
from apps.notifications.services import destination
from apps.venues.models import VenueBooking
from apps.venues.tests.conftest import make_venue
from conftest import make_event

WHAT = "Move the conference to the following Monday and allow 150 guests."
WHY = "Our keynote speaker can only attend that day."
NEW_START = (timezone.now() + datetime.timedelta(days=60)).replace(
    hour=1, minute=0, second=0, microsecond=0
)
NEW_END = NEW_START + datetime.timedelta(hours=8)


def url(event):
    return f"/api/events/{event.pk}/change-requests/"


@pytest.fixture
def submitted(organiser, coordinator):
    """A submitted event assigned to Cora."""
    return make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)


@pytest.fixture
def confirmed(organiser, coordinator):
    return make_event(
        organiser, status=EventStatus.CONFIRMED, coordinator=coordinator, name="Gala Dinner"
    )


@pytest.fixture
def organiser_api(api, organiser):
    api.force_authenticate(organiser)
    return api


def post(api, event, **body):
    body.setdefault("description", WHAT)
    body.setdefault("reason", WHY)
    return api.post(url(event), body, format="json")


def notices():
    return Notification.objects.filter(kind=NotificationKind.CHANGE_REQUESTED)


def booking_for(event, organiser_user):
    venue = make_venue(name=f"Hall {event.pk}", capacity=200)
    return VenueBooking.objects.create(
        event=event,
        venue=venue,
        starts_at=event.preferred_start,
        ends_at=event.preferred_end,
        attendance=100,
        requested_by=organiser_user,
    )


def equipment_for(event, user):
    plan, _ = EquipmentPlan.objects.get_or_create(event=event)
    item, _ = EquipmentType.objects.get_or_create(
        code="PROJECTOR", defaults={"name": "Projector", "total_quantity": 10}
    )
    return EquipmentRequest.objects.create(
        plan=plan, equipment_type=item, quantity=2, requested_by=user
    )


# S4-20-01 - AC1: the organiser states what to change and why, with typed values.


@pytest.mark.django_db
@pytest.mark.parametrize(
    "event_status",
    [
        EventStatus.SUBMITTED,
        EventStatus.UNDER_REVIEW,
        EventStatus.APPROVED,
        EventStatus.PLANNING,
        EventStatus.CONFIRMED,
    ],
)
def test_s4_20_01_ac1_a_submitted_or_confirmed_event_takes_a_change_request(
    organiser_api, organiser, coordinator, event_status
):
    event = make_event(organiser, status=event_status, coordinator=coordinator)

    response = post(organiser_api, event)

    assert response.status_code == 201
    saved = EventChangeRequest.objects.get(event=event)
    assert (saved.description, saved.reason) == (WHAT, WHY)
    assert saved.source_status == event_status


@pytest.mark.django_db
def test_s4_20_01_ac1_proposed_values_are_saved_typed_and_exactly(
    organiser_api, organiser, confirmed
):
    response = post(
        organiser_api,
        confirmed,
        proposed_values={
            "preferred_start": NEW_START.isoformat(),
            "preferred_end": NEW_END.isoformat(),
            "expected_attendance": 150,
            "required_layout": "THEATRE",
        },
    )

    assert response.status_code == 201
    saved = EventChangeRequest.objects.get(event=confirmed)
    assert saved.proposed_values["expected_attendance"] == 150
    assert saved.proposed_values["required_layout"] == "THEATRE"
    assert datetime.datetime.fromisoformat(saved.proposed_values["preferred_start"]) == NEW_START
    assert datetime.datetime.fromisoformat(saved.proposed_values["preferred_end"]) == NEW_END
    assert saved.requested_by == organiser
    assert saved.revision == 1


@pytest.mark.django_db
def test_s4_20_01_ac1_the_source_snapshot_records_the_event_as_it_was(organiser_api, confirmed):
    values, digest = source_snapshot(confirmed)

    post(organiser_api, confirmed, proposed_values={"expected_attendance": 150})

    saved = EventChangeRequest.objects.get(event=confirmed)
    assert saved.source_values == values
    assert saved.source_values["expected_attendance"] == 120
    assert saved.source_digest == digest
    assert len(digest) == 64


@pytest.mark.django_db
def test_s4_20_01_the_digest_changes_when_the_event_changes(confirmed):
    _, before = source_snapshot(confirmed)
    confirmed.expected_attendance = 121
    confirmed.save()

    _, after = source_snapshot(confirmed)

    assert before != after


@pytest.mark.django_db
def test_s4_20_01_ac1_the_response_shows_current_and_proposed_values(organiser_api, confirmed):
    response = post(organiser_api, confirmed, proposed_values={"expected_attendance": 150})

    [row] = response.data["change_request"]["proposed_changes"]
    assert row == {
        "field": "expected_attendance",
        "label": "Expected attendance",
        "current": "120",
        "proposed": "150",
    }


@pytest.mark.django_db
def test_s4_20_01_ac1_the_events_own_arrangements_can_be_referenced(
    organiser_api, organiser, coordinator, confirmed
):
    booking = booking_for(confirmed, coordinator)
    line = equipment_for(confirmed, coordinator)

    response = post(
        organiser_api,
        confirmed,
        target_bookings=[booking.pk, booking.pk],
        target_equipment_requests=[line.pk],
    )

    assert response.status_code == 201
    saved = EventChangeRequest.objects.get(event=confirmed)
    assert (saved.target_bookings, saved.target_equipment_requests) == ([booking.pk], [line.pk])


@pytest.mark.django_db
def test_s4_20_01_ac1_proposed_values_are_optional(organiser_api, confirmed):
    response = post(organiser_api, confirmed)

    assert response.status_code == 201
    assert EventChangeRequest.objects.get(event=confirmed).proposed_values == {}


@pytest.mark.django_db
def test_s4_20_01_ac1_another_member_of_the_organisation_can_request(api, acme, confirmed):
    colleague = User.objects.create_user(
        username="colleague@acme.example",
        email="colleague@acme.example",
        role=Role.EVENT_ORGANISER,
        organisation=acme,
    )
    api.force_authenticate(colleague)

    assert post(api, confirmed).status_code == 201
    assert EventChangeRequest.objects.get(event=confirmed).requested_by == colleague


# S4-20-02 - AC2: Pending against the event, and the assigned coordinator notified.


@pytest.mark.django_db
def test_s4_20_02_ac2_the_request_is_pending_and_a_receipt_is_shown(organiser_api, confirmed):
    response = post(organiser_api, confirmed)

    assert response.data["detail"] == "Your change request has been sent and is Pending review."
    body = response.data["change_request"]
    assert (body["status"], body["status_label"]) == (ChangeRequestStatus.PENDING, "Pending")
    assert [row["id"] for row in organiser_api.get(url(confirmed)).data] == [body["id"]]


@pytest.mark.django_db
def test_s4_20_02_ac2_the_assigned_coordinator_is_notified_once(
    organiser_api, organiser, coordinator, lead, confirmed
):
    post(organiser_api, confirmed)

    [notice] = notices()
    change = EventChangeRequest.objects.get(event=confirmed)
    assert notice.recipient == coordinator
    assert notice.event == confirmed
    assert notice.occurrence == f"CHANGE_REQUESTED:change-request:{change.pk}"
    assert notice.message == (f'Ada Organiser requested a change to "Gala Dinner": {WHAT}')
    # The notice opens the coordinator's event page, where the request is shown.
    assert destination(notice, coordinator).path == f"/coordinator/events/{confirmed.pk}"


@pytest.mark.django_db
def test_s4_20_02_ac2_each_request_is_its_own_notice(organiser_api, coordinator, confirmed):
    post(organiser_api, confirmed)
    post(organiser_api, confirmed, description="Also add a second projector.")

    assert notices().filter(recipient=coordinator).count() == 2


@pytest.mark.django_db
def test_s4_20_02_ac2_while_unassigned_the_active_leads_are_notified(
    organiser_api, organiser, lead
):
    second = User.objects.create_user(
        username="lead2", email="lead2@example.com", role=Role.EVENT_COORDINATOR_LEAD
    )
    User.objects.create_user(
        username="gone",
        email="gone@example.com",
        role=Role.EVENT_COORDINATOR_LEAD,
        is_active=False,
    )
    event = make_event(organiser, status=EventStatus.SUBMITTED)

    response = post(organiser_api, event)

    assert response.data["detail"] == (
        "Your change request has been sent to ConnectSphere and is Pending review."
    )
    assert sorted(n.recipient_id for n in notices()) == sorted([lead.pk, second.pk])
    notice = notices().get(recipient=lead)
    assert destination(notice, lead).path == f"/lead/events/{event.pk}"


@pytest.mark.django_db
def test_s4_20_02_the_organiser_is_not_sent_their_own_notice(organiser_api, organiser, confirmed):
    post(organiser_api, confirmed)

    assert not notices().filter(recipient=organiser).exists()


@pytest.mark.django_db
def test_s4_20_02_a_failed_notice_leaves_no_request(organiser, confirmed):
    with (
        mock.patch("apps.notifications.services.notify", side_effect=RuntimeError("down")),
        pytest.raises(RuntimeError),
    ):
        request_change(event=confirmed, requested_by=organiser, description=WHAT, reason=WHY)

    assert not EventChangeRequest.objects.exists()


# S4-20-03 - AC3: a change request with no description is not submitted.


@pytest.mark.django_db
@pytest.mark.parametrize("description", ["", "   ", None], ids=["empty", "spaces", "null"])
def test_s4_20_03_ac3_a_missing_description_is_refused(
    organiser_api, coordinator, confirmed, description
):
    response = post(organiser_api, confirmed, description=description)

    assert response.status_code == 400
    assert response.data["description"] == ["Enter a description of the change."]
    assert not EventChangeRequest.objects.exists()
    assert not notices().exists()


@pytest.mark.django_db
def test_s4_20_03_ac3_an_omitted_description_is_refused(api, organiser, confirmed):
    api.force_authenticate(organiser)

    response = api.post(url(confirmed), {"reason": WHY}, format="json")

    assert response.status_code == 400
    assert response.data["description"] == ["Enter a description of the change."]


@pytest.mark.django_db
@pytest.mark.parametrize("reason", ["", "  ", None], ids=["empty", "spaces", "null"])
def test_s4_20_03_ac1_the_reason_is_required_too(organiser_api, confirmed, reason):
    response = post(organiser_api, confirmed, reason=reason)

    assert response.status_code == 400
    assert response.data["reason"] == ["Enter the reason for the change."]
    assert not EventChangeRequest.objects.exists()


@pytest.mark.django_db
def test_s4_20_03_every_problem_is_named_together(organiser_api, confirmed):
    response = post(
        organiser_api,
        confirmed,
        description=["not", "text"],
        reason="",
        proposed_values={"expected_attendance": 0},
    )

    assert response.status_code == 400
    assert response.data["detail"] == "The change request could not be sent."
    assert response.data["description"] == ["A description of the change must be text."]
    assert response.data["reason"] == ["Enter the reason for the change."]
    assert response.data["proposed_values.expected_attendance"] == [
        "Expected attendance must be at least one person."
    ]


@pytest.mark.django_db
def test_s4_20_03_surrounding_spaces_are_trimmed(organiser_api, confirmed):
    post(organiser_api, confirmed, description=f"  {WHAT}  ", reason=f" {WHY}\n")

    saved = EventChangeRequest.objects.get(event=confirmed)
    assert (saved.description, saved.reason) == (WHAT, WHY)


# S4-20-04 - AC4: cancelled or completed events refuse; so do drafts and rejections.


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("event_status", "message"),
    [
        (EventStatus.CANCELLED, "A change cannot be requested for a Cancelled event."),
        (EventStatus.COMPLETED, "A change cannot be requested for a Completed event."),
        (EventStatus.REJECTED, "A change cannot be requested for a Rejected event."),
        (
            EventStatus.DRAFT,
            "This request has not been submitted yet; edit the draft instead.",
        ),
    ],
)
def test_s4_20_04_ac4_finished_rejected_or_draft_events_refuse(
    organiser_api, organiser, coordinator, event_status, message
):
    event = make_event(organiser, status=event_status, coordinator=coordinator)

    response = post(organiser_api, event)

    assert response.status_code == 400
    assert response.data["event"] == [message]
    assert not EventChangeRequest.objects.exists()
    assert not notices().exists()


# S4-20-05 - AC5: the request's status and any decision are visible on the event.


@pytest.mark.django_db
def test_s4_20_05_ac5_the_organiser_sees_status_and_decision(organiser_api, coordinator, confirmed):
    post(organiser_api, confirmed)
    # Low-level fixture: SCRUM-78 (ASSESS) records decisions through its own action.
    EventChangeRequest.objects.filter(event=confirmed).update(
        status=ChangeRequestStatus.REJECTED,
        decided_by=coordinator,
        decided_at=timezone.now(),
        decision_reason="The venue is unavailable that day.",
    )

    [row] = organiser_api.get(url(confirmed)).data

    assert (row["status"], row["status_label"]) == (ChangeRequestStatus.REJECTED, "Rejected")
    assert row["decided_by_name"] == "Cora Coordinator"
    assert row["decision_reason"] == "The venue is unavailable that day."
    assert row["decided_at"] is not None


@pytest.mark.django_db
def test_s4_20_05_ac5_a_pending_request_has_no_decision_yet(organiser_api, confirmed):
    post(organiser_api, confirmed)

    [row] = organiser_api.get(url(confirmed)).data

    assert row["status"] == ChangeRequestStatus.PENDING
    assert (row["decided_by_name"], row["decided_at"], row["decision_reason"]) == (None, None, "")
    assert row["requested_by_name"] == "Ada Organiser"


@pytest.mark.django_db
def test_s4_20_05_ac5_newest_requests_are_listed_first(organiser_api, confirmed):
    post(organiser_api, confirmed, description="First change")
    post(organiser_api, confirmed, description="Second change")

    rows = organiser_api.get(url(confirmed)).data

    assert [row["description"] for row in rows] == ["Second change", "First change"]


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["coordinator", "lead"])
def test_s4_20_05_the_assigned_coordinator_and_leads_see_the_requests(
    api, organiser, confirmed, request, who
):
    request_change(event=confirmed, requested_by=organiser, description=WHAT, reason=WHY)
    api.force_authenticate(request.getfixturevalue(who))

    rows = api.get(url(confirmed)).data

    assert [(row["description"], row["status"]) for row in rows] == [
        (WHAT, ChangeRequestStatus.PENDING)
    ]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "who", ["other_organiser", "second_coordinator", "attendee", "venue_staff"]
)
def test_s4_20_05_other_users_cannot_read_the_requests(api, organiser, confirmed, request, who):
    request_change(event=confirmed, requested_by=organiser, description=WHAT, reason=WHY)
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    assert api.get(url(confirmed)).status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


@pytest.mark.django_db
def test_s4_20_05_a_draft_is_not_visible_to_connectsphere(api, organiser, coordinator):
    draft = make_event(organiser, coordinator=coordinator)
    api.force_authenticate(coordinator)

    assert api.get(url(draft)).status_code == 403


# S4-20-06 - the event is never edited; only named fields and own resources.


@pytest.mark.django_db
def test_s4_20_06_the_event_itself_is_not_changed(organiser_api, confirmed):
    before, _ = source_snapshot(confirmed)

    post(
        organiser_api,
        confirmed,
        proposed_values={"expected_attendance": 150, "preferred_start": NEW_START.isoformat()},
    )

    confirmed.refresh_from_db()
    assert source_snapshot(confirmed)[0] == before
    assert confirmed.status == EventStatus.CONFIRMED
    assert not EventFieldChange.objects.filter(event=confirmed).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field", ["status", "coordinator", "registration_required", "organisation", "venue"]
)
def test_s4_20_06_only_named_event_fields_can_be_proposed(organiser_api, confirmed, field):
    response = post(organiser_api, confirmed, proposed_values={field: "anything"})

    assert response.status_code == 400
    assert response.data["proposed_values"] == [
        f"These cannot be changed through a change request: {field}."
    ]
    assert not EventChangeRequest.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("proposed", [["expected_attendance"], "150", 150])
def test_s4_20_06_proposed_values_must_be_named_fields(organiser_api, confirmed, proposed):
    response = post(organiser_api, confirmed, proposed_values=proposed)

    assert response.status_code == 400
    assert response.data["proposed_values"] == ["Proposed values must name event fields."]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("proposed", "field", "message"),
    [
        (
            {"expected_attendance": 0},
            "expected_attendance",
            "Expected attendance must be at least one person.",
        ),
        (
            {"preferred_start": "2020-01-01T09:00:00+08:00"},
            "preferred_start",
            "The preferred start date cannot be in the past.",
        ),
        (
            {"preferred_end": "2020-01-01T09:00:00+08:00"},
            "preferred_end",
            "The event must end after it starts.",
        ),
        ({"required_layout": "CABARET"}, "required_layout", None),
        ({"name": ""}, "name", "This detail cannot be removed from the event."),
        (
            {"expected_attendance": 120},
            "expected_attendance",
            "This is already the event's current value.",
        ),
    ],
    ids=[
        "zero-attendance",
        "past-start",
        "end-before-start",
        "unknown-layout",
        "blank-name",
        "unchanged",
    ],
)
def test_s4_20_06_proposed_values_follow_the_event_rules(
    organiser_api, confirmed, proposed, field, message
):
    response = post(organiser_api, confirmed, proposed_values=proposed)

    assert response.status_code == 400
    key = f"proposed_values.{field}"
    assert key in response.data
    if message:
        assert response.data[key] == [message]
    assert not EventChangeRequest.objects.exists()


@pytest.mark.django_db
def test_s4_20_06_another_events_booking_or_equipment_is_refused(
    organiser_api, organiser, coordinator, confirmed
):
    other = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    foreign_booking = booking_for(other, coordinator)
    foreign_line = equipment_for(other, coordinator)

    response = post(
        organiser_api,
        confirmed,
        target_bookings=[foreign_booking.pk],
        target_equipment_requests=[foreign_line.pk],
    )

    assert response.status_code == 400
    assert response.data["target_bookings"] == [
        "Only this event's own venue bookings can be referenced."
    ]
    assert response.data["target_equipment_requests"] == [
        "Only this event's own equipment requests can be referenced."
    ]
    assert not EventChangeRequest.objects.exists()


@pytest.mark.django_db
def test_s4_20_06_a_stale_reference_id_is_refused(organiser_api, confirmed):
    response = post(organiser_api, confirmed, target_bookings=[999999])

    assert response.status_code == 400
    assert "target_bookings" in response.data


@pytest.mark.django_db
@pytest.mark.parametrize("ids", ["1", [True], ["1"], {"id": 1}])
def test_s4_20_06_references_must_be_lists_of_ids(organiser_api, confirmed, ids):
    response = post(organiser_api, confirmed, target_equipment_requests=ids)

    assert response.status_code == 400
    assert response.data["target_equipment_requests"] == [
        "Equipment requests must be a list of IDs."
    ]


@pytest.mark.django_db
def test_s4_20_06_an_event_in_the_body_cannot_redirect_the_request(
    organiser_api, organiser, coordinator, confirmed
):
    other = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)

    body = {"description": WHAT, "reason": WHY, "event": other.pk}
    response = organiser_api.post(url(confirmed), body, format="json")

    assert response.status_code == 201
    assert EventChangeRequest.objects.get().event == confirmed


@pytest.mark.django_db
def test_s4_20_06_another_organisation_cannot_request_a_change(api, other_organiser, confirmed):
    api.force_authenticate(other_organiser)

    response = post(api, confirmed)

    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=other_organiser, allowed=False).exists()
    assert not EventChangeRequest.objects.exists()


@pytest.mark.django_db
def test_s4_20_06_the_service_refuses_another_organisation_too(other_organiser, confirmed):
    from apps.events.change_requests import NotEventOrganiser

    with pytest.raises(NotEventOrganiser):
        request_change(event=confirmed, requested_by=other_organiser, description=WHAT, reason=WHY)


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["coordinator", "lead", "attendee", "venue_staff"])
def test_s4_20_06_only_organisers_request_changes(api, confirmed, request, who):
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    assert post(api, confirmed).status_code == 403
    assert not EventChangeRequest.objects.exists()


@pytest.mark.django_db
def test_s4_20_06_the_service_names_problems_without_saving(organiser, confirmed):
    with pytest.raises(ChangeRequestError) as refused:
        request_change(event=confirmed, requested_by=organiser, description="", reason="")

    assert set(refused.value.errors) == {"description", "reason"}
    assert not EventChangeRequest.objects.exists()


@pytest.mark.django_db
def test_s4_20_06_a_refusal_found_under_the_lock_is_still_audited(
    organiser_api, organiser, confirmed
):
    # The organiser's organisation changes after the permission check: the
    # service, which rereads under the event lock, refuses it.
    from apps.events.change_requests import NotEventOrganiser

    with mock.patch("apps.events.change_views.request_change", side_effect=NotEventOrganiser):
        response = post(organiser_api, confirmed)

    assert response.status_code == 403
    assert response.data["detail"] == "You can only request changes to your own events."
    assert AuditLog.objects.filter(
        actor=organiser,
        allowed=False,
        detail="only the event's own organisation may request a change",
    ).exists()


# Final E2E defect 3 - a double submit made two identical open requests.


@pytest.mark.django_db
def test_an_identical_open_request_is_refused_as_a_duplicate(organiser_api, confirmed):
    body = {"proposed_values": {"expected_attendance": 80}}
    first = post(organiser_api, confirmed, **body)

    second = post(organiser_api, confirmed, **body)

    assert first.status_code == 201
    assert second.status_code == 400
    assert f"#{first.data['change_request']['id']} already asks" in str(second.data)
    assert EventChangeRequest.objects.filter(event=confirmed).count() == 1


@pytest.mark.django_db
def test_the_duplicate_check_ignores_case_and_surrounding_spaces(organiser_api, confirmed):
    post(organiser_api, confirmed, description="Add a projector")

    response = post(organiser_api, confirmed, description="  add a PROJECTOR ")

    assert response.status_code == 400
    assert EventChangeRequest.objects.filter(event=confirmed).count() == 1


@pytest.mark.django_db
def test_a_different_value_is_not_a_duplicate(organiser_api, confirmed):
    post(organiser_api, confirmed, proposed_values={"expected_attendance": 80})

    response = post(organiser_api, confirmed, proposed_values={"expected_attendance": 90})

    assert response.status_code == 201
    assert EventChangeRequest.objects.filter(event=confirmed).count() == 2


@pytest.mark.django_db
def test_the_same_request_can_be_sent_again_once_the_first_is_decided(
    organiser_api, coordinator, confirmed
):
    post(organiser_api, confirmed)
    # Low-level fixture: SCRUM-78 records decisions through its own action.
    EventChangeRequest.objects.filter(event=confirmed).update(
        status=ChangeRequestStatus.REJECTED,
        decided_by=coordinator,
        decided_at=timezone.now(),
        decision_reason="Not this time.",
    )

    assert post(organiser_api, confirmed).status_code == 201


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_identical_submits_create_one_request(organiser, confirmed):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections
    from rest_framework.test import APIClient

    gate = Barrier(2)

    def send(_):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(organiser)
            gate.wait(timeout=10)
            return post(client, confirmed).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(send, range(2)))

    assert statuses == [201, 400]
    assert EventChangeRequest.objects.filter(event=confirmed).count() == 1
