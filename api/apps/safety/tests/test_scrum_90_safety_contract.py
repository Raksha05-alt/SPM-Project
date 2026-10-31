"""SCRUM-90 safety contract (Sprint 3 gate G04).

Readiness predicates, the arrangement version, supersession and the
confirmation guard that every resource action and SCRUM-58 rely on. Case IDs
match docs/test-cases/S3-SCRUM-90-safety.csv.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.equipment.models import (
    EquipmentPlan,
    EquipmentRequestStatus,
    EquipmentReservation,
    TechnicalApproval,
    TechnicalApprovalStatus,
)
from apps.events.models import EventRequest, EventStatusHistory
from apps.events.services import transition_event
from apps.notifications.models import Notification, NotificationKind
from apps.safety.models import SafetyCheck, SafetyStatus
from apps.safety.services import (
    ConfirmationBlocked,
    arrangement_gaps,
    arrangement_version,
    arrangements_changed,
    confirmation_gaps,
    is_stale,
)
from apps.venues.bookings import create_booking_record, transition_booking
from apps.venues.models import BookingStatus, VenueBlock

from .conftest import approve_equipment, approve_venue, make_check, make_venue

NO_VENUE = "Venue: no venue booking has been approved by Venue Staff."
NO_TECH = "Technical: the equipment plan has not been approved by Technical Support."
NO_CHECK = "Operational safety check: no approved check."
STALE = (
    "Operational safety check: the arrangements changed after it was approved. Request a new check."
)


@pytest.fixture
def approved_check(ready_event, safety_officer):
    return make_check(ready_event, SafetyStatus.APPROVED, safety_officer)


# --------------------------------------------------------------------------
# S3-SCRUM-90-C01 arrangement_gaps - what blocks a safety request
# --------------------------------------------------------------------------


def test_c01a_an_event_with_no_arrangements_lists_venue_and_technical_gaps(planning_event):
    assert arrangement_gaps(planning_event) == [NO_VENUE, NO_TECH]


def test_c01b_a_pending_booking_is_named_and_does_not_count_as_approved(
    planning_event, venue, tech
):
    approve_equipment(planning_event, tech)
    create_booking_record(
        requested_by=planning_event.coordinator,
        event=planning_event,
        venue=venue,
        starts_at=planning_event.preferred_start,
        ends_at=planning_event.preferred_end,
        attendance=100,
    )
    assert arrangement_gaps(planning_event) == [
        NO_VENUE,
        "Venue: the booking request for Harbour Hall is still awaiting Venue Staff.",
    ]


def test_c01c_venue_and_technical_approval_together_leave_no_gaps(ready_event):
    assert arrangement_gaps(ready_event) == []


def test_c01d_an_approved_venue_that_is_out_of_service_or_blocked_is_a_gap(ready_event, venue):
    venue.in_service = False
    venue.save(update_fields=["in_service"])
    VenueBlock.objects.create(
        venue=venue,
        reason="Sprinkler repair",
        starts_at=ready_event.preferred_start + timedelta(hours=1),
        ends_at=ready_event.preferred_start + timedelta(hours=2),
    )
    assert arrangement_gaps(ready_event) == [
        "Venue: Harbour Hall is out of service.",
        "Venue: Harbour Hall is blocked during the booked period (Sprinkler repair).",
    ]


def test_c01e_a_block_ending_exactly_at_the_booking_start_is_not_a_gap(ready_event, venue):
    """Half-open intervals: [start - 2h, start) does not overlap [start, end)."""
    start = ready_event.preferred_start
    VenueBlock.objects.create(
        venue=venue, reason="Before", starts_at=start - timedelta(hours=2), ends_at=start
    )
    VenueBlock.objects.create(
        venue=venue,
        reason="After",
        starts_at=ready_event.preferred_end,
        ends_at=ready_event.preferred_end + timedelta(hours=1),
    )
    assert arrangement_gaps(ready_event) == []

    VenueBlock.objects.create(
        venue=venue,
        reason="Overlap",
        starts_at=start - timedelta(hours=1),
        ends_at=start + timedelta(seconds=1),
    )
    assert arrangement_gaps(ready_event) == [
        "Venue: Harbour Hall is blocked during the booked period (Overlap)."
    ]


def test_c01f_an_approval_of_an_older_equipment_revision_does_not_count(ready_event):
    plan = EquipmentPlan.objects.get(event=ready_event)
    plan.revision += 1
    plan.save(update_fields=["revision"])
    assert arrangement_gaps(ready_event) == [NO_TECH]


def test_c01g_requested_but_unreserved_equipment_is_named(ready_event):
    plan = EquipmentPlan.objects.get(event=ready_event)
    item = plan.requests.get()
    item.status = EquipmentRequestStatus.REQUESTED
    item.save(update_fields=["status"])
    assert arrangement_gaps(ready_event) == [
        "Equipment: 2 x Projector is requested but not reserved."
    ]


def test_c01h_a_released_reservation_is_named_even_if_the_request_still_says_reserved(
    ready_event, tech
):
    EquipmentReservation.objects.update(
        status="RELEASED", released_by=tech, released_at=timezone.now(), release_reason="Spare"
    )
    assert arrangement_gaps(ready_event) == [
        "Equipment: 2 x Projector is requested but not reserved."
    ]


def test_c01i_an_explicit_no_equipment_acknowledgement_satisfies_technical_review(
    planning_event, venue, venue_staff, tech
):
    """No fictional equipment line is needed; an empty plan alone is not enough."""
    approve_venue(planning_event, venue, venue_staff)
    plan = EquipmentPlan.objects.create(event=planning_event)
    assert arrangement_gaps(planning_event) == [NO_TECH]

    TechnicalApproval.objects.create(
        plan=plan, plan_revision=0, approved_by=tech, no_equipment_required=True
    )
    assert arrangement_gaps(planning_event) == []


def test_c01j_a_withdrawn_equipment_request_is_ignored(ready_event):
    plan = EquipmentPlan.objects.get(event=ready_event)
    plan.requests.update(status=EquipmentRequestStatus.WITHDRAWN)
    assert arrangement_gaps(ready_event) == []


# --------------------------------------------------------------------------
# S3-SCRUM-90-C02 confirmation_gaps and the fail-closed confirmation guard
# --------------------------------------------------------------------------


def test_c02a_no_check_is_listed_as_missing(ready_event):
    assert confirmation_gaps(ready_event) == [NO_CHECK]


def test_c02b_arrangement_gaps_and_the_safety_check_are_listed_together(planning_event):
    assert confirmation_gaps(planning_event) == [NO_VENUE, NO_TECH, NO_CHECK]


@pytest.mark.parametrize(
    "status, expected",
    [
        (SafetyStatus.PENDING, ["Operational safety check: still awaiting a Safety Officer."]),
        (SafetyStatus.REJECTED, [NO_CHECK]),
        (SafetyStatus.CHANGES_REQUESTED, [NO_CHECK]),
        (SafetyStatus.SUPERSEDED, [NO_CHECK]),
        (SafetyStatus.APPROVED, []),
    ],
)
def test_c02c_only_a_current_approved_check_clears_confirmation(
    ready_event, safety_officer, status, expected
):
    make_check(ready_event, status, safety_officer, comment="Reason given.")
    assert confirmation_gaps(ready_event) == expected


def test_c02d_an_approval_of_an_older_arrangement_version_is_stale(approved_check):
    event = approved_check.event
    event.expected_attendance = 180
    event.save(update_fields=["expected_attendance"])
    assert is_stale(approved_check)
    assert confirmation_gaps(event) == [STALE]


def test_c02e_confirming_without_approval_is_refused_and_nothing_is_recorded(
    ready_event, coordinator
):
    history_before = EventStatusHistory.objects.count()

    with pytest.raises(ConfirmationBlocked) as refused:
        transition_event(ready_event, EventStatus.CONFIRMED, coordinator)

    assert refused.value.missing == [NO_CHECK]
    assert "Operational safety check" in str(refused.value)
    ready_event.refresh_from_db()
    assert ready_event.status == EventStatus.PLANNING
    assert EventStatusHistory.objects.count() == history_before


def test_c02f_confirming_with_a_current_approval_is_allowed(approved_check, coordinator):
    event = transition_event(approved_check.event, EventStatus.CONFIRMED, coordinator)
    assert event.status == EventStatus.CONFIRMED


def test_c02g_a_stale_approval_cannot_confirm(approved_check, coordinator):
    event = approved_check.event
    event.preferred_start += timedelta(hours=1)
    event.save(update_fields=["preferred_start"])

    with pytest.raises(ConfirmationBlocked) as refused:
        transition_event(event, EventStatus.CONFIRMED, coordinator)
    assert refused.value.missing == [STALE]


def test_c02h_a_block_added_after_approval_prevents_confirmation(
    approved_check, venue, coordinator
):
    event = approved_check.event
    VenueBlock.objects.create(
        venue=venue,
        reason="Power shutdown",
        starts_at=event.preferred_start,
        ends_at=event.preferred_end,
    )
    with pytest.raises(ConfirmationBlocked) as refused:
        transition_event(event, EventStatus.CONFIRMED, coordinator)
    assert refused.value.missing == [
        "Venue: Harbour Hall is blocked during the booked period (Power shutdown)."
    ]


def test_c02i_other_transitions_are_not_guarded(ready_event, coordinator):
    event = transition_event(ready_event, EventStatus.CANCELLED, coordinator)
    assert event.status == EventStatus.CANCELLED


# --------------------------------------------------------------------------
# S3-SCRUM-90-C03 arrangement_version - what makes an approval stale
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    ["attendance", "start", "end", "equipment quantity", "technical approval", "reservation"],
)
def test_c03a_each_reviewed_arrangement_changes_the_version(ready_event, tech, change):
    before = arrangement_version(ready_event)
    plan = EquipmentPlan.objects.get(event=ready_event)
    if change == "attendance":
        ready_event.expected_attendance += 1
    elif change == "start":
        ready_event.preferred_start -= timedelta(minutes=30)
    elif change == "end":
        ready_event.preferred_end += timedelta(minutes=30)
    elif change == "equipment quantity":
        plan.requests.update(quantity=3)
    elif change == "technical approval":
        old = plan.technical_approvals.get()
        old.status = TechnicalApprovalStatus.SUPERSEDED
        old.superseded_at = timezone.now()
        old.save()
        TechnicalApproval.objects.create(plan=plan, plan_revision=plan.revision, approved_by=tech)
    else:
        EquipmentReservation.objects.update(
            status="RELEASED", released_by=tech, released_at=timezone.now(), release_reason="x"
        )
    ready_event.save()

    assert arrangement_version(ready_event) != before


def test_c03b_venue_booking_changes_change_the_version(ready_event, coordinator):
    before = arrangement_version(ready_event)
    booking = ready_event.venue_bookings.get()
    transition_booking(booking, BookingStatus.WITHDRAWN, coordinator)
    assert arrangement_version(ready_event) != before


def test_c03c_unrelated_edits_do_not_change_the_version(ready_event):
    before = arrangement_version(ready_event)
    ready_event.description = "New agenda wording"
    ready_event.purpose = "Leadership planning"
    ready_event.save()
    assert arrangement_version(ready_event) == before


# --------------------------------------------------------------------------
# S3-SCRUM-90-C04 arrangements_changed - supersession and return to planning
# --------------------------------------------------------------------------


def test_c04a_an_approved_check_is_superseded_and_its_decision_kept(
    approved_check, safety_officer, coordinator, tech
):
    superseded = arrangements_changed(approved_check.event, "Projectors reduced to 1.", tech)

    assert superseded.pk == approved_check.pk
    approved_check.refresh_from_db()
    assert approved_check.status == SafetyStatus.SUPERSEDED
    assert approved_check.superseded_reason == "Projectors reduced to 1."
    assert approved_check.superseded_at is not None
    assert approved_check.decided_by == safety_officer
    notices = Notification.objects.filter(kind=NotificationKind.SAFETY_SUPERSEDED)
    assert [n.recipient for n in notices] == [coordinator]
    assert "Projectors reduced to 1." in notices.get().message


def test_c04b_superseding_a_pending_check_also_tells_the_safety_officers(
    ready_event, safety_officer, second_safety_officer, coordinator
):
    make_check(ready_event)

    arrangements_changed(ready_event, "Venue changed.", coordinator)

    notified = {
        n.recipient for n in Notification.objects.filter(kind=NotificationKind.SAFETY_SUPERSEDED)
    }
    # The coordinator made the change, so is not told about it.
    assert notified == {safety_officer, second_safety_officer}


def test_c04c_with_no_current_check_nothing_is_superseded_or_sent(ready_event, coordinator):
    assert arrangements_changed(ready_event, "Anything.", coordinator) is None
    assert not Notification.objects.exists()
    ready_event.refresh_from_db()
    assert ready_event.status == EventStatus.PLANNING


def test_c04d_a_confirmed_event_returns_to_planning_with_history_audit_and_notices(
    approved_check, coordinator, organiser, venue_staff
):
    event = transition_event(approved_check.event, EventStatus.CONFIRMED, coordinator)

    arrangements_changed(event, "Harbour Hall closed for repairs.", venue_staff)

    event.refresh_from_db()
    assert event.status == EventStatus.PLANNING
    latest = EventStatusHistory.objects.filter(event=event).order_by("-pk").first()
    assert (latest.from_status, latest.to_status, latest.changed_by) == (
        EventStatus.CONFIRMED,
        EventStatus.PLANNING,
        venue_staff,
    )
    audit = AuditLog.objects.get(action=f"Event {event.pk} returned to Planning")
    assert audit.detail == "Harbour Hall closed for repairs."
    assert audit.actor == venue_staff
    reopened = Notification.objects.filter(kind=NotificationKind.PLANNING_REOPENED)
    assert {n.recipient for n in reopened} == {coordinator, organiser}

    # A reconfirmation attempt now fails until a new check is approved.
    with pytest.raises(ConfirmationBlocked) as refused:
        transition_event(event, EventStatus.CONFIRMED, coordinator)
    assert refused.value.missing == [NO_CHECK]


def test_c04e_a_repeated_change_does_not_send_duplicate_notices(approved_check, tech):
    arrangements_changed(approved_check.event, "First change.", tech)
    arrangements_changed(approved_check.event, "Second change.", tech)

    assert Notification.objects.filter(kind=NotificationKind.SAFETY_SUPERSEDED).count() == 1
    approved_check.refresh_from_db()
    assert approved_check.superseded_reason == "First change."


def test_c04f_a_failed_resource_change_rolls_back_the_supersession(approved_check, coordinator):
    event = transition_event(approved_check.event, EventStatus.CONFIRMED, coordinator)

    with pytest.raises(RuntimeError), transaction.atomic():
        arrangements_changed(event, "Change that fails later.", coordinator)
        raise RuntimeError("the resource write failed")

    approved_check.refresh_from_db()
    event.refresh_from_db()
    assert approved_check.status == SafetyStatus.APPROVED
    assert event.status == EventStatus.CONFIRMED
    assert not Notification.objects.filter(kind=NotificationKind.PLANNING_REOPENED).exists()


# --------------------------------------------------------------------------
# S3-SCRUM-90-C05 booking status changes call the invalidation (INT-04)
# --------------------------------------------------------------------------


def test_c05a_withdrawing_an_approved_booking_supersedes_and_reopens_planning(
    approved_check, coordinator
):
    event = transition_event(approved_check.event, EventStatus.CONFIRMED, coordinator)
    booking = event.venue_bookings.get(status=BookingStatus.APPROVED)

    transition_booking(booking, BookingStatus.WITHDRAWN, coordinator)

    approved_check.refresh_from_db()
    event.refresh_from_db()
    assert approved_check.status == SafetyStatus.SUPERSEDED
    assert approved_check.superseded_reason == "The booking for Harbour Hall is now withdrawn."
    assert event.status == EventStatus.PLANNING
    assert confirmation_gaps(event) == [NO_VENUE, NO_CHECK]


def test_c05b_approving_a_further_booking_supersedes_the_check(
    approved_check, coordinator, venue_staff
):
    """Approving a venue changes the reviewed arrangements, even when adding one."""
    event = approved_check.event
    old = event.venue_bookings.get(status=BookingStatus.APPROVED)
    transition_booking(old, BookingStatus.WITHDRAWN, coordinator)
    make_check(event, SafetyStatus.APPROVED, approved_check.decided_by)

    approve_venue(event, make_venue("Skyline Room"), venue_staff)

    assert event.safety_checks.filter(status=SafetyStatus.APPROVED).count() == 0


def test_c05c_rejecting_a_pending_booking_leaves_the_check_alone(
    approved_check, coordinator, venue_staff
):
    pending = create_booking_record(
        requested_by=coordinator,
        event=approved_check.event,
        venue=make_venue("Skyline Room"),
        starts_at=approved_check.event.preferred_start,
        ends_at=approved_check.event.preferred_end,
        attendance=100,
    )
    transition_booking(pending, BookingStatus.REJECTED, venue_staff, "Room too small.")

    approved_check.refresh_from_db()
    assert approved_check.status == SafetyStatus.APPROVED


# --------------------------------------------------------------------------
# S3-SCRUM-90-C06 database rules (PostgreSQL)
# --------------------------------------------------------------------------


def test_c06a_an_event_has_at_most_one_pending_or_approved_check(ready_event):
    make_check(ready_event)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_check(ready_event)


def test_c06b_a_decision_records_who_and_when(ready_event):
    with pytest.raises(IntegrityError), transaction.atomic():
        SafetyCheck.objects.create(
            event=ready_event, status=SafetyStatus.APPROVED, arrangement_version="x"
        )


@pytest.mark.parametrize("status", [SafetyStatus.REJECTED, SafetyStatus.CHANGES_REQUESTED])
def test_c06c_a_negative_decision_needs_a_comment(ready_event, safety_officer, status):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_check(ready_event, status, safety_officer, comment="")


def test_c06d_checks_are_evidence_and_block_event_deletion(planning_event):
    """The event has no bookings or equipment, so only the check protects it."""
    from django.db.models import ProtectedError

    make_check(planning_event)
    with pytest.raises(ProtectedError):
        planning_event.delete()


@pytest.mark.django_db(transaction=True)
def test_c06e_concurrent_changes_supersede_once_without_duplicate_notices(
    ready_event, safety_officer, tech
):
    make_check(ready_event, SafetyStatus.APPROVED, safety_officer)

    def change(reason):
        close_old_connections()
        try:
            with transaction.atomic():
                return arrangements_changed(
                    EventRequest.objects.get(pk=ready_event.pk), reason, tech
                )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, ["Change A", "Change B"]))

    assert sum(r is not None for r in results) == 1
    assert SafetyCheck.objects.get().status == SafetyStatus.SUPERSEDED
    assert Notification.objects.filter(kind=NotificationKind.SAFETY_SUPERSEDED).count() == 1


# --------------------------------------------------------------------------
# S3-SCRUM-90-C07 the Safety Officer role
# --------------------------------------------------------------------------


def test_c07a_safety_officers_are_internal_staff_landing_on_the_safety_queue(safety_officer):
    assert safety_officer.is_internal
    assert safety_officer.is_safety_officer
    assert safety_officer.landing_path == "/safety"


def test_c07b_the_demo_seed_supplies_a_safety_officer(db):
    from django.core.management import call_command

    from apps.accounts.models import Role, User

    call_command("seed_demo_data")
    officer = User.objects.get(email="safety@connectsphere.example")
    assert officer.role == Role.SAFETY_OFFICER
    assert officer.check_password("connectsphere-demo")


def test_c07c_a_check_describes_itself_for_admin_lists(ready_event):
    check = make_check(ready_event)
    assert str(check) == f"Safety check for event {ready_event.pk} (Awaiting Safety Officer)"
