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
