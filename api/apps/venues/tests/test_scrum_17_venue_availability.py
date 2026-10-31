from datetime import time

import pytest

from apps.core.models import AuditLog
from apps.venues.models import VenueBlock
from apps.venues.tests.test_scrum_13_block_venue import PAYLOAD

pytestmark = pytest.mark.django_db


def check(api, venue, start="2026-11-02T10:00:00+08:00", end="2026-11-02T12:00:00+08:00"):
    return api.get(f"/api/venues/{venue.pk}/availability/", {"starts_at": start, "ends_at": end})


def test_available_and_fresh_block_updates(signed_in_coordinator, open_venue):
    api, venue = signed_in_coordinator, open_venue
    assert check(api, venue).data["status"] == "available"
    block = VenueBlock.objects.create(venue=venue, **PAYLOAD)
    result = check(api, venue).data
    assert result["status"] == "blocked" and result["available"] is False
    assert result["blocks"][0]["reason"] == "Maintenance"
    block.delete()
    assert check(api, venue).data["status"] == "available"


@pytest.mark.parametrize(
    "start,end,status",
    [
        ("08:00", "10:00", "available"),
        ("12:00", "13:00", "available"),
        ("09:59", "10:01", "blocked"),
        ("11:59", "12:01", "blocked"),
        ("07:59", "08:30", "unavailable"),
        ("21:00", "22:01", "unavailable"),
        ("08:00", "22:00", "blocked"),
    ],
)
def test_boundaries(signed_in_coordinator, open_venue, start, end, status):
    VenueBlock.objects.create(venue=open_venue, **PAYLOAD)
    response = check(
        signed_in_coordinator,
        open_venue,
        f"2026-11-02T{start}:00+08:00",
        f"2026-11-02T{end}:00+08:00",
    )
    assert response.status_code == 200
    assert response.data["status"] == status


def test_expired_block_does_not_override_other_obstructions(signed_in_coordinator, open_venue):
    VenueBlock.objects.create(venue=open_venue, **PAYLOAD)
    assert check(
        signed_in_coordinator, open_venue, "2026-11-03T10:00:00+08:00", "2026-11-03T12:00:00+08:00"
    ).data["available"]
    open_venue.in_service = False
    open_venue.save()
    assert (
        check(
            signed_in_coordinator,
            open_venue,
            "2026-11-03T10:00:00+08:00",
            "2026-11-03T12:00:00+08:00",
        ).data["status"]
        == "unavailable"
    )


def test_missing_hours_closed_day_and_overnight(signed_in_coordinator, venue, open_venue):
    venue.opens_at = None
    venue.save()
    assert check(signed_in_coordinator, venue).data["status"] == "unavailable"
    venue.opens_at = time(8)
    venue.operating_days = [1]
    venue.save()
    assert check(signed_in_coordinator, venue).data["status"] == "unavailable"
    assert (
        check(
            signed_in_coordinator, venue, "2026-11-03T10:00:00+08:00", "2026-11-04T10:00:00+08:00"
        ).data["status"]
        == "unavailable"
    )


@pytest.mark.parametrize("role", ["organiser", "attendee", "tech_staff"])
def test_calendar_and_block_reads_refused_and_audited(api, request, venue, role):
    user = request.getfixturevalue(role)
    api.force_authenticate(user)
    assert check(api, venue).status_code == 403
    assert api.get(f"/api/venues/{venue.pk}/blocks/").status_code == 403
    assert api.get(f"/api/venues/{venue.pk}/blocks/history/").status_code == 403
    assert (
        api.get(
            "/api/venues/available/",
            {"starts_at": PAYLOAD["starts_at"], "ends_at": PAYLOAD["ends_at"]},
        ).status_code
        == 403
    )
    assert AuditLog.objects.filter(actor=user, allowed=False).count() == 4


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"starts_at": "oops", "ends_at": "oops"},
        {"starts_at": PAYLOAD["ends_at"], "ends_at": PAYLOAD["starts_at"]},
        {"starts_at": PAYLOAD["starts_at"], "ends_at": PAYLOAD["starts_at"]},
    ],
)
def test_invalid_period(signed_in_coordinator, venue, params):
    assert (
        signed_in_coordinator.get(f"/api/venues/{venue.pk}/availability/", params).status_code
        == 400
    )


def test_utc_matches_singapore(signed_in_coordinator, open_venue):
    assert check(
        signed_in_coordinator, open_venue, "2026-11-02T00:00:00Z", "2026-11-02T14:00:00Z"
    ).data["available"]
