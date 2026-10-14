"""Week 7 change 5 - defence in depth when a Lead reassigns an event mid-request.

The permission class lets the assigned coordinator through; a Lead may then hand
the event to someone else before the coordinator's decision takes its row lock.
Every service re-checks the assignment under the lock, and the view turns the
refusal into an audited 403, leaving the event unchanged.
"""

import pytest
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events import views
from apps.events.models import ClarificationRequest
from apps.safety.tests.helpers import approve_safety
from apps.venues.tests.helpers import book
from conftest import make_event, make_venue


def reassigned_before(service, event, other):
    """Wrap ``service`` so the event changes hands just before it runs."""

    def wrapper(target, *args, **kwargs):
        type(event).objects.filter(pk=event.pk).update(coordinator=other)
        return service(target, *args, **kwargs)

    return wrapper


CASES = [
    ("approve", "approve_event", EventStatus.SUBMITTED, {}),
    ("reject", "reject_event", EventStatus.SUBMITTED, {"reason": "No"}),
    ("request-clarification", "request_clarification", EventStatus.SUBMITTED, {"message": "?"}),
    ("resume-review", "resume_review", EventStatus.UNDER_REVIEW, {}),
    ("cancel", "cancel_event", EventStatus.PLANNING, {}),
    ("complete", "complete_event", EventStatus.CONFIRMED, {}),
    ("confirm", "confirm_event", EventStatus.PLANNING, {}),
    ("comment", "add_clarification_comment", EventStatus.UNDER_REVIEW, {"message": "Noted"}),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "service", "status", "payload"), CASES)
def test_a_decision_after_reassignment_is_refused_and_audited(
    signed_in_coordinator,
    monkeypatch,
    organiser,
    coordinator,
    second_coordinator,
    path,
    service,
    status,
    payload,
):
    past = {}
    if status == EventStatus.CONFIRMED:
        # Completion needs an event that has already taken place.
        now = timezone.now()
        past = {
            "preferred_start": now - timezone.timedelta(hours=3),
            "preferred_end": now - timezone.timedelta(hours=1),
        }
    event = make_event(organiser, status=status, coordinator=coordinator, **past)
    ClarificationRequest.objects.create(event=event, message="What size?")
    if service == "confirm_event":
        book(event, make_venue())
        approve_safety(event)
    monkeypatch.setattr(
        views, service, reassigned_before(getattr(views, service), event, second_coordinator)
    )

    response = signed_in_coordinator.post(f"/api/events/{event.pk}/{path}/", payload, format="json")

    assert response.status_code == 403, response.data
    event.refresh_from_db()
    assert event.status == status
    if path != "resume-review":
        assert AuditLog.objects.filter(actor=coordinator, allowed=False).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "approve",
        "reject",
        "request-clarification",
        "confirm",
        "complete",
        "assign",
        "resume-review",
    ],
)
def test_an_organiser_cannot_take_staff_actions_on_their_own_draft(
    signed_in_organiser, complete_draft, coordinator, path
):
    response = signed_in_organiser.post(
        f"/api/events/{complete_draft.pk}/{path}/",
        {"reason": "x", "message": "x", "coordinator": coordinator.pk},
        format="json",
    )

    assert response.status_code == 403
    complete_draft.refresh_from_db()
    assert complete_draft.is_draft


@pytest.mark.django_db
def test_a_client_cannot_read_planning_readiness(signed_in_organiser, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)

    assert signed_in_organiser.get(f"/api/events/{event.pk}/readiness/").status_code == 403


@pytest.mark.django_db
def test_a_safety_check_request_after_reassignment_is_refused(
    signed_in_coordinator, monkeypatch, organiser, coordinator, second_coordinator
):
    from apps.safety import views as safety_views

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    book(event, make_venue())
    monkeypatch.setattr(
        safety_views,
        "request_check",
        reassigned_before(safety_views.request_check, event, second_coordinator),
    )

    response = signed_in_coordinator.post(
        f"/api/events/{event.pk}/safety-checks/", {}, format="json"
    )

    assert response.status_code == 403
    assert not event.safety_checks.exists()


# --- service-level guards, called directly --------------------------------------


@pytest.mark.django_db
def test_only_a_lead_assigns_even_when_calling_the_service(organiser, coordinator):
    from apps.events.services import NotPermitted, assign_coordinator

    event = make_event(organiser, status=EventStatus.SUBMITTED)

    with pytest.raises(NotPermitted):
        assign_coordinator(event, coordinator, coordinator.pk)


@pytest.mark.django_db
def test_a_draft_cannot_be_assigned_even_when_calling_the_service(
    lead, complete_draft, coordinator
):
    from apps.events.services import NotPermitted, assign_coordinator

    with pytest.raises(NotPermitted):
        assign_coordinator(complete_draft, lead, coordinator.pk)


@pytest.mark.django_db
def test_only_the_parties_comment_even_when_calling_the_service(
    organiser, other_organiser, lead, coordinator
):
    from apps.events.services import NotPermitted, add_clarification_comment

    event = make_event(organiser, status=EventStatus.UNDER_REVIEW, coordinator=coordinator)
    ClarificationRequest.objects.create(event=event, message="?")

    for outsider in (other_organiser, lead):
        with pytest.raises(NotPermitted):
            add_clarification_comment(event, outsider, "Hello")


@pytest.mark.django_db
def test_a_safety_decision_needs_a_safety_officer_even_via_the_service(organiser, coordinator):
    from apps.events.services import NotPermitted
    from apps.safety.models import SafetyCheck
    from apps.safety.services import decide

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    check = SafetyCheck.objects.create(event=event)

    with pytest.raises(NotPermitted):
        decide(check, coordinator, "APPROVED")


@pytest.mark.django_db
def test_an_expired_hold_shows_as_expired_before_it_is_processed(organiser, coordinator):
    from apps.events.confirmation import arrangement_gaps
    from apps.venues.models import BookingStatus

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    book(
        event,
        make_venue(),
        status=BookingStatus.HELD,
        hold_expires_at=timezone.now() - timezone.timedelta(minutes=5),
    )

    details = [gap["detail"] for gap in arrangement_gaps(event)]

    assert "The hold on Harbour Hall has expired." in details


@pytest.mark.django_db
def test_a_shift_that_would_invert_the_booking_falls_back_to_the_new_event_period(
    organiser, coordinator
):
    from apps.events.impact import shifted

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    booking = book(
        event,
        make_venue(),
        event.preferred_start,
        event.preferred_start + timezone.timedelta(hours=1),
    )
    old = {"preferred_start": event.preferred_start, "preferred_end": event.preferred_end}
    new = {
        "preferred_start": event.preferred_start + timezone.timedelta(hours=5),
        "preferred_end": event.preferred_start + timezone.timedelta(hours=5, minutes=30),
    }

    assert shifted(booking, old, new) == (new["preferred_start"], new["preferred_end"])


@pytest.mark.django_db
def test_records_read_naturally(organiser, coordinator, venue):
    from apps.events.models import ClarificationComment
    from apps.safety.models import SafetyCheck
    from apps.venues.models import LayoutType

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    clarification = ClarificationRequest.objects.create(event=event, message="?")
    comment = ClarificationComment.objects.create(clarification=clarification, message="ok")

    assert str(comment) == f"Comment on clarification {clarification.pk}"
    assert str(SafetyCheck.objects.create(event=event)) == (
        f"Safety check for event {event.pk} (Awaiting Safety Officer)"
    )
    assert str(LayoutType.objects.get(code="THEATRE")) == "Theatre"


@pytest.mark.django_db
def test_a_draft_submitted_twice_at_once_answers_409(
    signed_in_organiser, monkeypatch, complete_draft
):
    # The second of two simultaneous submissions finds the request already
    # submitted once it holds the lock (sprint 1 notes: the 409 branch).
    def already_submitted(event, user):
        type(event).objects.filter(pk=event.pk).update(status=EventStatus.SUBMITTED)
        return original(event, user)

    original = views.submit_event
    monkeypatch.setattr(views, "submit_event", already_submitted)

    response = signed_in_organiser.post(f"/api/events/{complete_draft.pk}/submit/")

    assert response.status_code == 409


@pytest.mark.django_db
def test_an_unknown_safety_decision_is_refused_by_the_service(
    organiser, coordinator, safety_officer
):
    from apps.safety.models import SafetyCheck
    from apps.safety.services import SafetyRefused, decide

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    check = SafetyCheck.objects.create(event=event)

    with pytest.raises(SafetyRefused):
        decide(check, safety_officer, "MAYBE", "x")


@pytest.mark.django_db
def test_leads_read_change_requests_but_cannot_raise_them(api, lead, organiser, coordinator):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    api.force_authenticate(lead)

    assert api.get(f"/api/events/{event.pk}/change-requests/").status_code == 200
    raised = api.post(
        f"/api/events/{event.pk}/change-requests/", {"description": "x"}, format="json"
    )
    assert raised.status_code == 403


@pytest.mark.django_db
def test_a_coordinator_lists_only_their_own_equipment_requests(
    signed_in_coordinator, organiser, coordinator, second_coordinator
):
    from apps.equipment.models import EquipmentType
    from apps.equipment.tests.conftest import make_request

    projector = EquipmentType.objects.create(name="Projector", total_quantity=5)
    mine = make_request(
        make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator), projector, 1
    )
    make_request(
        make_event(organiser, status=EventStatus.PLANNING, coordinator=second_coordinator),
        projector,
        1,
    )

    rows = signed_in_coordinator.get("/api/equipment-requests/").data

    assert [row["id"] for row in rows] == [mine.pk]


@pytest.mark.django_db
def test_an_out_of_service_venue_cannot_be_requested(signed_in_coordinator, organiser, coordinator):
    from apps.venues.tests.helpers import booking_payload

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    closed = make_venue(name="Closed Room", is_active=False)

    response = signed_in_coordinator.post(
        "/api/venue-bookings/", booking_payload(event, closed), format="json"
    )

    assert response.status_code == 409
    assert "out of service" in response.data["detail"]


@pytest.mark.django_db
def test_confirming_a_hold_past_its_deadline_is_refused_by_the_service(organiser, coordinator):
    from apps.venues.bookings import BookingRefused, confirm_hold
    from apps.venues.models import BookingStatus

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    held = book(
        event,
        make_venue(),
        status=BookingStatus.HELD,
        hold_expires_at=timezone.now() - timezone.timedelta(minutes=1),
    )

    with pytest.raises(BookingRefused, match="expired"):
        confirm_hold(held, coordinator)


@pytest.mark.django_db
def test_the_calendar_names_the_session_of_a_hold(signed_in_venue_staff, organiser, coordinator):
    from apps.venues.models import BookingStatus

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    room = make_venue()
    book(
        event,
        room,
        status=BookingStatus.HELD,
        hold_expires_at=timezone.now() + timezone.timedelta(days=1),
        session_name="Breakout A",
    )

    response = signed_in_venue_staff.get(
        f"/api/venues/{room.pk}/availability/",
        {"start": event.preferred_start.isoformat(), "end": event.preferred_end.isoformat()},
    )

    assert response.data["segments"][0]["detail"].endswith("- Breakout A")


@pytest.mark.django_db
def test_no_buffer_warning_without_recorded_hours(organiser, coordinator):
    from apps.venues.suitability import buffer_warnings

    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    room = make_venue(opens_at=None, closes_at=None, setup_minutes=30)

    assert buffer_warnings(book(event, room)) == []
