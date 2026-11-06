"""SCRUM-70 provider cases. Approved rows are low-level fixtures, not APPLY evidence."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.db import transaction
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.events.change_requests import source_snapshot
from apps.events.models import ChangeRequestStatus, EventChangeRequest, VenuePeriodReview
from apps.events.period_conflicts import (
    record_period_reviews,
    review_period,
    shifted,
    venue_conflicts,
)
from apps.venues.models import BookingStatus
from apps.venues.tests.conftest import open_venue as open_venue  # noqa: F401
from apps.venues.tests.conftest import venue as venue  # noqa: F401
from apps.venues.tests.test_scrum_69_overlapping_bookings import END, START, pending


@pytest.mark.parametrize(
    "kind,expected_end",
    [("MAIN", END + timedelta(days=1, hours=1)), ("BREAKOUT", END + timedelta(days=1))],
)
def test_shift_preserves_independent_session_duration(kind, expected_end):
    booking = SimpleNamespace(starts_at=START, ends_at=END, session=SimpleNamespace(kind=kind))
    event = SimpleNamespace(preferred_start=START, preferred_end=END)
    assert shifted(
        booking,
        event,
        {
            "preferred_start": (START + timedelta(days=1)).isoformat(),
            "preferred_end": (END + timedelta(days=1, hours=1)).isoformat(),
        },
    ) == (START + timedelta(days=1), expected_end)


def test_shift_refuses_nonpositive_period():
    booking = SimpleNamespace(starts_at=START, ends_at=END, session=SimpleNamespace(kind="MAIN"))
    event = SimpleNamespace(preferred_start=START, preferred_end=END)
    with pytest.raises(ValueError):
        shifted(booking, event, {"preferred_end": START.isoformat()})


@pytest.fixture
def scenario(organiser, coordinator, venue_staff, open_venue):
    booking = pending(organiser, coordinator, open_venue)
    booking.status = BookingStatus.APPROVED
    booking.save()
    event = booking.event
    event.preferred_start, event.preferred_end = START, END
    event.status = EventStatus.CONFIRMED
    event.save()
    event.refresh_from_db()
    values, digest = source_snapshot(event)
    change = EventChangeRequest.objects.create(
        event=event,
        requested_by=organiser,
        description="Move one day",
        reason="Rescheduled",
        proposed_values={
            "preferred_start": (START + timedelta(days=1)).isoformat(),
            "preferred_end": (END + timedelta(days=1)).isoformat(),
        },
        source_values=values,
        source_digest=digest,
        source_status=event.status,
        status=ChangeRequestStatus.APPROVED,
        decided_at=timezone.now(),
        decided_by=coordinator,
    )
    return booking, change


@pytest.mark.django_db
@pytest.mark.parametrize("conflict", [True, False])
def test_preview_writer_and_actual_staff_outcome(
    scenario, organiser, coordinator, venue_staff, open_venue, conflict
):
    booking, change = scenario
    if conflict:
        other = pending(
            organiser,
            coordinator,
            open_venue,
            start=START + timedelta(days=1),
            end=END + timedelta(days=1),
        )
        other.status = BookingStatus.APPROVED
        other.save()
    preview = venue_conflicts(booking.event, change.proposed_values)
    assert bool(preview[0]["conflicts"]) is conflict
    assert not VenuePeriodReview.objects.exists()
    with transaction.atomic():
        review = record_period_reviews(change, coordinator)[0]
        assert record_period_reviews(change, coordinator)[0].pk == review.pk
    assert review.reviewed_at is None  # preview/writer is never staff approval
    if conflict:
        assert review.conflicts[0]["event_id"] == other.event_id
    reviewed = review_period(review, venue_staff, reason="Checked revised period")
    assert bool(reviewed.conflicts) is conflict
    assert reviewed.reviewed_by == venue_staff
    assert reviewed.reviewed_at is not None
    booking.refresh_from_db()
    assert (booking.starts_at, booking.ends_at, booking.status) == (
        START,
        END,
        BookingStatus.APPROVED,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("offset,conflict", [(75, False), (74, True)])
def test_buffered_adjacency(scenario, organiser, coordinator, open_venue, offset, conflict):
    booking, change = scenario
    open_venue.setup_minutes, open_venue.turnaround_minutes = 30, 45
    open_venue.save()
    other = pending(
        organiser,
        coordinator,
        open_venue,
        start=END + timedelta(days=1, minutes=offset),
        end=END + timedelta(days=1, hours=3),
    )
    other.status = BookingStatus.APPROVED
    other.save()
    assert bool(venue_conflicts(booking.event, change.proposed_values)[0]["conflicts"]) is conflict


@pytest.mark.django_db
def test_permission_stale_source_and_pending_refused(scenario, organiser, coordinator):
    booking, change = scenario
    with transaction.atomic(), pytest.raises(PermissionError):
        record_period_reviews(change, organiser)
    booking.event.name = "Changed since request"
    booking.event.save()
    with transaction.atomic(), pytest.raises(ValueError, match="since"):
        record_period_reviews(change, coordinator)
    assert not VenuePeriodReview.objects.exists()


@pytest.mark.django_db
def test_staff_rechecks_race_after_preview(
    scenario, organiser, coordinator, venue_staff, open_venue
):
    booking, change = scenario
    with transaction.atomic():
        review = record_period_reviews(change, coordinator)[0]
    assert review.conflicts == []
    other = pending(
        organiser,
        coordinator,
        open_venue,
        start=START + timedelta(days=1),
        end=END + timedelta(days=1),
    )
    other.status = BookingStatus.APPROVED
    other.save()
    assert review_period(review, venue_staff, reason="Fresh check").conflicts[0]["id"] == other.pk


@pytest.mark.django_db
def test_reasons_permission_scoped(api, scenario, coordinator, venue_staff, organiser):
    booking, change = scenario
    with transaction.atomic():
        record_period_reviews(change, coordinator)
    for user, expected in [(coordinator, 200), (venue_staff, 200), (organiser, 403)]:
        api.force_authenticate(user)
        response = api.get(f"/api/events/{booking.event_id}/venue-reviews/")
        assert response.status_code == expected
        if expected == 200:
            assert "Proposed period" in response.data["open"][0]["reasons"][0]["message"]


@pytest.mark.parametrize("value", ["invalid-date", START.replace(tzinfo=None)])
def test_scrum70_shift_requires_an_aware_valid_datetime(value):
    booking = SimpleNamespace(starts_at=START, ends_at=END, session=SimpleNamespace(kind="MAIN"))
    event = SimpleNamespace(preferred_start=START, preferred_end=END)
    with pytest.raises(ValueError, match="aware date and time"):
        shifted(booking, event, {"preferred_start": value})


@pytest.mark.django_db
@pytest.mark.parametrize(
    "selection", ["unrelated_fields", "unchanged_period", "one_booking", "foreign_booking"]
)
def test_scrum70_preview_scopes_only_changed_bookings(scenario, selection):
    booking, change = scenario
    if selection == "unrelated_fields":
        assert venue_conflicts(booking.event, {"name": "Different title"}) == []
    elif selection == "unchanged_period":
        assert (
            venue_conflicts(booking.event, {"preferred_start": START, "preferred_end": END}) == []
        )
    elif selection == "foreign_booking":
        with pytest.raises(ValueError, match="this event's approved bookings"):
            venue_conflicts(
                booking.event, change.proposed_values, target_bookings=[booking.pk + 10000]
            )
    else:
        rows = venue_conflicts(booking.event, change.proposed_values, target_bookings=[booking.pk])
        assert [row["booking"] for row in rows] == [booking.pk]
    booking.refresh_from_db()
    assert (booking.starts_at, booking.ends_at) == (START, END)
    assert not VenuePeriodReview.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_scrum70_review_writer_requires_its_callers_transaction(scenario, coordinator):
    _, change = scenario
    with pytest.raises(RuntimeError, match="transaction"):
        record_period_reviews(change, coordinator)
    assert not VenuePeriodReview.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("invalid", ["pending_change", "stale_revision", "unconfirmed_source"])
def test_scrum70_writer_rejects_unapproved_stale_or_unconfirmed_changes(
    scenario, coordinator, invalid
):
    booking, change = scenario
    updates = {
        "pending_change": {"status": ChangeRequestStatus.PENDING, "decided_at": None},
        "stale_revision": {"revision": change.revision + 1},
        "unconfirmed_source": {"source_status": EventStatus.APPROVED},
    }[invalid]
    EventChangeRequest.objects.filter(pk=change.pk).update(**updates)
    with transaction.atomic(), pytest.raises(ValueError, match="approved|confirmed"):
        record_period_reviews(change, coordinator)
    booking.refresh_from_db()
    assert (booking.starts_at, booking.ends_at) == (START, END)
    assert not VenuePeriodReview.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("invalid", ["wrong_role", "inactive_staff", "blank_reason"])
def test_scrum70_staff_outcome_requires_active_staff_and_a_reason(
    scenario, coordinator, venue_staff, invalid
):
    booking, change = scenario
    with transaction.atomic():
        review = record_period_reviews(change, coordinator)[0]
    actor = coordinator if invalid == "wrong_role" else venue_staff
    if invalid == "inactive_staff":
        actor.is_active = False
        actor.save(update_fields=["is_active"])
    error = ValueError if invalid == "blank_reason" else PermissionError
    with pytest.raises(error, match="reason|active Venue Staff"):
        review_period(review, actor, reason="   " if invalid == "blank_reason" else "Checked")
    review.refresh_from_db()
    assert review.reviewed_by is None and review.reviewed_at is None
    booking.refresh_from_db()
    assert booking.status == BookingStatus.APPROVED


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid", ["already_decided", "new_revision", "change_pending", "booking_withdrawn"]
)
def test_scrum70_review_cannot_overwrite_a_decision_or_use_stale_arrangements(
    scenario, coordinator, venue_staff, invalid
):
    booking, change = scenario
    with transaction.atomic():
        review = record_period_reviews(change, coordinator)[0]
    if invalid == "already_decided":
        review_period(review, venue_staff, reason="First verified decision")
    elif invalid == "new_revision":
        EventChangeRequest.objects.filter(pk=change.pk).update(revision=change.revision + 1)
    elif invalid == "change_pending":
        EventChangeRequest.objects.filter(pk=change.pk).update(
            status=ChangeRequestStatus.PENDING, decided_at=None
        )
    else:
        booking.status = BookingStatus.WITHDRAWN
        booking.save(update_fields=["status"])
    with pytest.raises(ValueError, match="already|superseded|no longer approved"):
        review_period(review, venue_staff, reason="Replacement decision")
    review.refresh_from_db()
    assert review.review_reason == (
        "First verified decision" if invalid == "already_decided" else ""
    )
    assert bool(review.reviewed_at) is (invalid == "already_decided")
    booking.refresh_from_db()
    assert (booking.starts_at, booking.ends_at) == (START, END)
