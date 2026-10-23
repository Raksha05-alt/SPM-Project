from unittest.mock import patch

import pytest
from django.utils.dateparse import parse_datetime

from apps.venues.models import VenueBlock, VenueBlockHistory

pytestmark = pytest.mark.django_db
PAYLOAD = {
    "reason": "Maintenance",
    "starts_at": "2026-11-02T10:00:00+08:00",
    "ends_at": "2026-11-02T12:00:00+08:00",
}


def url(venue):
    return f"/api/venues/{venue.pk}/blocks/"


def test_create_edit_remove_retains_history(signed_in_venue_staff, venue, venue_staff):
    api = signed_in_venue_staff
    response = api.post(url(venue), PAYLOAD, format="json")
    assert response.status_code == 201
    block = VenueBlock.objects.get(pk=response.data["id"])
    assert block.reason == "Maintenance"
    assert block.starts_at == parse_datetime(PAYLOAD["starts_at"])
    detail = f"{url(venue)}{block.pk}/"
    assert (
        api.patch(
            detail, {"reason": "Renovation", "ends_at": "2026-11-02T13:00:00+08:00"}, format="json"
        ).status_code
        == 200
    )
    assert api.get(url(venue)).data[0]["reason"] == "Renovation"
    assert api.delete(detail).status_code == 204
    assert not VenueBlock.objects.exists()
    history = list(VenueBlockHistory.objects.order_by("created_at", "pk"))
    assert [h.action for h in history] == ["created", "updated", "removed"]
    assert [h.reason for h in history] == ["Maintenance", "Renovation", "Renovation"]
    assert all(h.actor == venue_staff and h.created_at for h in history)
    assert api.get(f"{url(venue)}history/").data[0]["action"] == "removed"


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": "  "},
        {"ends_at": PAYLOAD["starts_at"]},
        {"starts_at": PAYLOAD["ends_at"]},
        {"ends_at": "invalid"},
    ],
)
def test_invalid_create_has_no_side_effects(signed_in_venue_staff, venue, changes):
    assert (
        signed_in_venue_staff.post(url(venue), PAYLOAD | changes, format="json").status_code == 400
    )
    assert not VenueBlock.objects.exists()
    assert not VenueBlockHistory.objects.exists()


@pytest.mark.parametrize("role", ["coordinator", "organiser", "attendee", "tech_staff"])
def test_forbidden_writers(api, request, venue, role):
    api.force_authenticate(request.getfixturevalue(role))
    assert api.post(url(venue), PAYLOAD, format="json").status_code == 403
    assert not VenueBlock.objects.exists()
    block = VenueBlock.objects.create(venue=venue, **PAYLOAD)
    detail = f"{url(venue)}{block.pk}/"
    assert api.patch(detail, {"reason": "Changed"}, format="json").status_code == 403
    assert api.delete(detail).status_code == 403
    block.refresh_from_db()
    assert block.reason == "Maintenance"
    assert not VenueBlockHistory.objects.exists()


def test_invalid_edit_preserves_block(signed_in_venue_staff, venue):
    api = signed_in_venue_staff
    block = api.post(url(venue), PAYLOAD, format="json").data
    assert (
        api.patch(
            f"{url(venue)}{block['id']}/", {"ends_at": PAYLOAD["starts_at"]}, format="json"
        ).status_code
        == 400
    )
    assert VenueBlock.objects.get().ends_at == parse_datetime(PAYLOAD["ends_at"])
    assert VenueBlockHistory.objects.count() == 1


def test_transaction_rolls_back_if_history_fails(signed_in_venue_staff, venue):
    with patch(
        "apps.venues.availability_views.snapshot", side_effect=RuntimeError("history failed")
    ):
        with pytest.raises(RuntimeError):
            signed_in_venue_staff.post(url(venue), PAYLOAD, format="json")
    assert not VenueBlock.objects.exists()


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_edit_remove_rolls_back_if_history_fails(signed_in_venue_staff, venue, method):
    block = VenueBlock.objects.create(venue=venue, **PAYLOAD)
    with patch(
        "apps.venues.availability_views.snapshot", side_effect=RuntimeError("history failed")
    ):
        with pytest.raises(RuntimeError):
            getattr(signed_in_venue_staff, method)(
                f"{url(venue)}{block.pk}/", {"reason": "Changed"}, format="json"
            )
    block.refresh_from_db()
    assert block.reason == "Maintenance"


def test_current_status_and_expiry(signed_in_venue_staff, venue):
    api = signed_in_venue_staff
    api.post(url(venue), PAYLOAD, format="json")
    with patch(
        "apps.venues.serializers.timezone.now", return_value=parse_datetime(PAYLOAD["starts_at"])
    ):
        assert api.get(f"/api/venues/{venue.pk}/").data["operational_status"] == "Blocked"
    with patch(
        "apps.venues.serializers.timezone.now", return_value=parse_datetime(PAYLOAD["ends_at"])
    ):
        assert api.get(f"/api/venues/{venue.pk}/").data["operational_status"] == "In service"


def test_block_cannot_be_changed_through_other_venue(signed_in_venue_staff, venue):
    from apps.venues.tests.conftest import make_venue

    api = signed_in_venue_staff
    block = api.post(url(venue), PAYLOAD, format="json").data
    other = make_venue(name="Other")
    assert api.delete(f"{url(other)}{block['id']}/").status_code == 404
    assert VenueBlock.objects.count() == 1


def test_search_excludes_blocked_venue_and_refreshes(signed_in_coordinator, open_venue):
    api = signed_in_coordinator
    params = {key: PAYLOAD[key] for key in ("starts_at", "ends_at")}

    def search():
        return api.get("/api/venues/available/", params)

    assert [v["id"] for v in search().data] == [open_venue.pk]
    block = VenueBlock.objects.create(venue=open_venue, **PAYLOAD)
    assert search().data == []
    block.delete()
    assert [v["id"] for v in search().data] == [open_venue.pk]
