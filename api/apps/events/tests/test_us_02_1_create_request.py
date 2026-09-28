"""US-02.1 - Create an event request."""

import pytest
from django.utils import timezone

EVENTS = "/api/events/"


def _payload(**overrides):
    start = timezone.now() + timezone.timedelta(days=30)
    data = {
        "name": "Regional Partner Conference",
        "purpose": "Annual partner briefing",
        "description": "Full day conference with breakout sessions.",
        "preferred_start": start.isoformat(),
        "preferred_end": (start + timezone.timedelta(hours=6)).isoformat(),
        "expected_attendance": 120,
        "required_layout": "THEATRE",
        "accessibility_needs": "Step-free access and a hearing loop.",
        "equipment_notes": "Two radio microphones and a projector.",
        "registration_required": True,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_ac1_an_organiser_can_record_every_field_the_customer_asked_for(signed_in_organiser):
    response = signed_in_organiser.post(EVENTS, _payload(), format="json")

    assert response.status_code == 201
    for field in (
        "name",
        "purpose",
        "description",
        "preferred_start",
        "preferred_end",
        "expected_attendance",
        "required_layout",
        "accessibility_needs",
        "equipment_notes",
        "registration_required",
    ):
        assert field in response.data
    assert response.data["expected_attendance"] == 120
    assert response.data["registration_required"] is True
    assert response.data["organisation_name"] == "Acme Pte Ltd"


@pytest.mark.django_db
def test_ac2_an_attendance_of_zero_or_less_is_rejected(signed_in_organiser):
    zero = signed_in_organiser.post(EVENTS, _payload(expected_attendance=0), format="json")
    negative = signed_in_organiser.post(EVENTS, _payload(expected_attendance=-5), format="json")

    assert zero.status_code == 400
    assert "expected_attendance" in zero.data
    assert negative.status_code == 400


@pytest.mark.django_db
def test_ac3_a_preferred_date_in_the_past_is_rejected(signed_in_organiser):
    past = timezone.now() - timezone.timedelta(days=1)

    response = signed_in_organiser.post(
        EVENTS, _payload(preferred_start=past.isoformat()), format="json"
    )

    assert response.status_code == 400
    assert "preferred_start" in response.data


@pytest.mark.django_db
def test_ac4_a_new_request_appears_in_my_list_with_its_status(signed_in_organiser):
    created = signed_in_organiser.post(EVENTS, _payload(), format="json")

    listing = signed_in_organiser.get(EVENTS)

    assert listing.status_code == 200
    ids = [row["id"] for row in listing.data]
    assert created.data["id"] in ids
    row = next(r for r in listing.data if r["id"] == created.data["id"])
    assert row["status"] == "DRAFT"
    assert row["status_label"] == "Draft"


@pytest.mark.django_db
def test_an_event_must_end_after_it_starts(signed_in_organiser):
    start = timezone.now() + timezone.timedelta(days=10)

    response = signed_in_organiser.post(
        EVENTS,
        _payload(
            preferred_start=start.isoformat(),
            preferred_end=(start - timezone.timedelta(hours=1)).isoformat(),
        ),
        format="json",
    )

    assert response.status_code == 400
    assert "preferred_end" in response.data


@pytest.mark.django_db
def test_a_coordinator_cannot_raise_a_request_on_a_clients_behalf(signed_in_coordinator):
    response = signed_in_coordinator.post(EVENTS, _payload(), format="json")

    assert response.status_code == 403
