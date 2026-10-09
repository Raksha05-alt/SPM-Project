"""SCRUM-13 (US-09.2) - block a venue as unavailable."""

import pytest
from django.utils import timezone

from apps.core.models import AuditLog
from apps.venues.models import VenueBlock
from apps.venues.tests.helpers import block, iso
from conftest import future_at


def blocks_url(venue):
    return f"/api/venues/{venue.pk}/blocks/"


@pytest.mark.django_db
def test_ac1_venue_staff_block_a_venue_with_a_reason_and_period(
    signed_in_venue_staff, venue_staff, venue
):
    start, end = future_at(5, 0), future_at(8, 0)

    response = signed_in_venue_staff.post(
        blocks_url(venue),
        {"start": iso(start), "end": iso(end), "reason": "Ceiling repairs"},
        format="json",
    )

    assert response.status_code == 201
    saved = VenueBlock.objects.get(venue=venue)
    assert (saved.start, saved.end, saved.reason) == (start, end, "Ceiling repairs")
    assert saved.created_by == venue_staff


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload,field",
    [
        ({"reason": ""}, "reason"),
        ({"reason": "   "}, "reason"),
        ({"end_offset_days": -1}, "end"),
    ],
)
def test_ac1_a_block_needs_a_reason_and_must_end_after_it_starts(
    signed_in_venue_staff, venue, payload, field
):
    start = future_at(5, 0)
    end = future_at(5 + payload.pop("end_offset_days", 1), 0)

    response = signed_in_venue_staff.post(
        blocks_url(venue),
        {"start": iso(start), "end": iso(end), "reason": "Repairs", **payload},
        format="json",
    )

    assert response.status_code == 400
    assert field in response.data


@pytest.mark.django_db
def test_ac2_a_blocked_venue_is_shown_as_blocked(signed_in_venue_staff, venue):
    now = timezone.now()
    block(venue, now - timezone.timedelta(hours=1), now + timezone.timedelta(hours=5))

    response = signed_in_venue_staff.get(f"/api/venues/{venue.pk}/")

    assert response.data["operational_status"] == "Blocked"
    listed = signed_in_venue_staff.get(blocks_url(venue))
    assert listed.data[0]["reason"] == "Maintenance"


@pytest.mark.django_db
def test_ac3_a_blocked_venue_is_not_offered_in_a_search_for_the_block_period(
    api, coordinator, venue
):
    from conftest import make_venue

    free = make_venue(name="Free Room")
    block(venue, future_at(10, 0), future_at(11, 0))
    api.force_authenticate(coordinator)

    response = api.get(
        "/api/venues/search/", {"start": iso(future_at(10, 9)), "end": iso(future_at(10, 12))}
    )

    assert [row["id"] for row in response.data["results"]] == [free.pk]


@pytest.mark.django_db
def test_ac5_a_block_that_has_ended_no_longer_affects_availability(signed_in_venue_staff, venue):
    now = timezone.now()
    block(venue, now - timezone.timedelta(days=5), now - timezone.timedelta(days=1))

    detail = signed_in_venue_staff.get(f"/api/venues/{venue.pk}/")
    diary = signed_in_venue_staff.get(
        f"/api/venues/{venue.pk}/availability/",
        {"start": iso(future_at(1, 9)), "end": iso(future_at(1, 17))},
    )

    assert detail.data["operational_status"] == "In service"
    assert [s["status"] for s in diary.data["segments"]] == ["AVAILABLE"]


@pytest.mark.django_db
def test_ac6_editing_a_block_takes_effect_and_records_user_and_time(
    signed_in_venue_staff, venue_staff, venue
):
    existing = block(venue, future_at(5, 0), future_at(6, 0))
    before = timezone.now()

    response = signed_in_venue_staff.patch(
        f"/api/venue-blocks/{existing.pk}/",
        {"end": iso(future_at(7, 0)), "reason": "Repairs overran"},
        format="json",
    )

    assert response.status_code == 200
    existing.refresh_from_db()
    assert existing.end == future_at(7, 0)
    assert existing.updated_by == venue_staff
    assert existing.updated_at >= before
    assert AuditLog.objects.filter(
        actor=venue_staff, action=f"PATCH /api/venue-blocks/{existing.pk}/"
    ).exists()


@pytest.mark.django_db
def test_ac6_removing_a_block_takes_effect_and_keeps_who_removed_it(
    signed_in_venue_staff, venue_staff, venue
):
    existing = block(venue, future_at(5, 0), future_at(6, 0))

    response = signed_in_venue_staff.delete(f"/api/venue-blocks/{existing.pk}/")

    assert response.status_code == 204
    existing.refresh_from_db()
    assert existing.removed_by == venue_staff
    assert existing.removed_at is not None
    assert signed_in_venue_staff.get(blocks_url(venue)).data == []
    assert AuditLog.objects.filter(
        actor=venue_staff, action=f"DELETE /api/venue-blocks/{existing.pk}/"
    ).exists()


@pytest.mark.django_db
def test_only_venue_staff_can_create_or_change_blocks(api, coordinator, venue):
    existing = block(venue, future_at(5, 0), future_at(6, 0))
    api.force_authenticate(coordinator)

    created = api.post(
        blocks_url(venue),
        {"start": iso(future_at(8, 0)), "end": iso(future_at(9, 0)), "reason": "x"},
        format="json",
    )
    edited = api.patch(f"/api/venue-blocks/{existing.pk}/", {"reason": "y"}, format="json")

    assert created.status_code == 403
    assert edited.status_code == 403
    assert api.get(blocks_url(venue)).status_code == 200
