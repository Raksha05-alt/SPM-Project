"""SCRUM-60 (US-07.3) - see who changed event information and when."""

from datetime import datetime

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.events.models import EventChangeLog, ImmutableRecord
from conftest import make_event


def history_url(event):
    return f"/api/events/{event.pk}/history/"


@pytest.fixture
def planning_event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)


@pytest.mark.django_db
def test_ac1_each_change_shows_field_previous_and_new_value_user_and_time(
    signed_in_coordinator, planning_event
):
    signed_in_coordinator.patch(
        f"/api/events/{planning_event.pk}/", {"expected_attendance": 150}, format="json"
    )

    response = signed_in_coordinator.get(history_url(planning_event))

    assert response.status_code == 200
    [entry] = response.data
    assert entry["field"] == "expected_attendance"
    assert entry["previous_value"] == "120"
    assert entry["new_value"] == "150"
    assert entry["changed_by_name"] == "Cora Coordinator"
    assert entry["changed_at"]


@pytest.mark.django_db
def test_ac1_dates_and_flags_are_recorded_readably(signed_in_coordinator, planning_event):
    new_start = planning_event.preferred_start + timezone.timedelta(days=1)
    signed_in_coordinator.patch(
        f"/api/events/{planning_event.pk}/",
        {
            "preferred_start": new_start.isoformat(),
            "preferred_end": (new_start + timezone.timedelta(hours=2)).isoformat(),
            "registration_required": True,
        },
        format="json",
    )

    entries = {e.field: e for e in EventChangeLog.objects.filter(event=planning_event)}
    assert datetime.fromisoformat(entries["preferred_start"].new_value) == new_start
    assert entries["registration_required"].previous_value == "No"
    assert entries["registration_required"].new_value == "Yes"


@pytest.mark.django_db
def test_ac1_unchanged_fields_are_not_recorded(signed_in_coordinator, planning_event):
    signed_in_coordinator.patch(
        f"/api/events/{planning_event.pk}/",
        {"name": planning_event.name, "purpose": "New purpose"},
        format="json",
    )

    fields = list(
        EventChangeLog.objects.filter(event=planning_event).values_list("field", flat=True)
    )
    assert fields == ["purpose"]


@pytest.mark.django_db
def test_ac1_a_client_correction_after_clarification_is_recorded(
    signed_in_organiser, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.UNDER_REVIEW, coordinator=coordinator)

    signed_in_organiser.patch(f"/api/events/{event.pk}/", {"purpose": "Clarified"}, format="json")

    entry = EventChangeLog.objects.get(event=event)
    assert entry.changed_by == organiser


@pytest.mark.django_db
def test_ac1_edits_to_a_private_draft_are_not_recorded(signed_in_organiser, incomplete_draft):
    signed_in_organiser.patch(
        f"/api/events/{incomplete_draft.pk}/", {"name": "Still drafting"}, format="json"
    )

    assert not EventChangeLog.objects.filter(event=incomplete_draft).exists()


@pytest.mark.django_db
def test_ac2_entries_are_listed_most_recent_first(signed_in_coordinator, planning_event):
    url = f"/api/events/{planning_event.pk}/"
    signed_in_coordinator.patch(url, {"purpose": "First"}, format="json")
    signed_in_coordinator.patch(url, {"purpose": "Second"}, format="json")

    response = signed_in_coordinator.get(history_url(planning_event))

    assert [e["new_value"] for e in response.data] == ["Second", "First"]


@pytest.mark.django_db
def test_ac3_an_organiser_cannot_open_the_internal_change_history(
    signed_in_organiser, planning_event
):
    response = signed_in_organiser.get(history_url(planning_event))

    assert response.status_code == 403


@pytest.mark.django_db
def test_ac3_an_attendee_cannot_open_the_internal_change_history(
    api, attendee, organiser, coordinator
):
    event = make_event(organiser, status=EventStatus.CONFIRMED, coordinator=coordinator)
    api.force_authenticate(attendee)

    response = api.get(history_url(event))

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["put", "patch", "delete", "post"])
def test_ac4_the_history_cannot_be_edited_or_deleted_through_the_api(
    signed_in_coordinator, planning_event, method
):
    response = getattr(signed_in_coordinator, method)(history_url(planning_event), {})

    assert response.status_code == 405


@pytest.mark.django_db
def test_ac4_a_history_row_cannot_be_edited_or_deleted_in_code(coordinator, planning_event):
    entry = EventChangeLog.objects.create(
        event=planning_event,
        field="name",
        previous_value="a",
        new_value="b",
        changed_by=coordinator,
    )
    entry.new_value = "tampered"

    with pytest.raises(ImmutableRecord):
        entry.save()
    with pytest.raises(ImmutableRecord):
        entry.delete()
    assert EventChangeLog.objects.get(pk=entry.pk).new_value == "b"
