"""Original SCRUM-68: persistence, fresh assessments, ownership and failure paths."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import IntegrityError, close_old_connections, transaction
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.venues.models import VenueBlock, VenueShortlistEntry
from apps.venues.tests.test_scrum_64_filter_venues import PERIOD, searchable_venue
from conftest import make_event

pytestmark = pytest.mark.django_db


def url(event, venue=None):
    base = f"/api/events/{event.pk}/venue-shortlist/"
    return f"{base}{venue.pk}/" if venue else base


@pytest.fixture
def planning_event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)


@pytest.fixture
def other_coordinator(db):
    return User.objects.create_user(
        username="other-coordinator", email="other@cs.example", role=Role.EVENT_COORDINATOR
    )


def add(api, event, venue, criteria=None):
    return api.post(url(event), {"venue_id": venue.pk, "criteria": criteria or {}}, format="json")


def test_ac1_add_persists_against_the_event_and_reopens_through_a_fresh_client(
    signed_in_coordinator, planning_event, coordinator
):
    venue = searchable_venue()
    response = add(signed_in_coordinator, planning_event, venue, {"attendance": 60, **PERIOD})
    assert response.status_code == 201
    saved = VenueShortlistEntry.objects.get(event=planning_event, venue=venue)
    assert saved.created_by == coordinator
    assert saved.search_criteria["attendance"] == 60
    fresh = APIClient()
    fresh.force_authenticate(coordinator)
    reopened = fresh.get(url(planning_event))
    assert reopened.status_code == 200
    assert reopened.data["entries"][0]["id"] == saved.pk
    assert reopened.data["entries"][0]["match"]["venue"]["name"] == venue.name
    assert AuditLog.objects.filter(
        actor=coordinator, action=f"POST {url(planning_event)}", allowed=True
    ).exists()


def test_ac1_repeated_add_is_idempotent_and_preserves_saved_criteria(
    signed_in_coordinator, planning_event
):
    venue = searchable_venue()
    first = add(signed_in_coordinator, planning_event, venue, {"attendance": 30})
    second = add(signed_in_coordinator, planning_event, venue, {"attendance": 60})
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.data["id"] == second.data["id"]
    assert VenueShortlistEntry.objects.count() == 1
    assert second.data["search_criteria"]["attendance"] == 30


def test_database_constraint_prevents_duplicate_event_venue_entries(planning_event, coordinator):
    venue = searchable_venue()
    VenueShortlistEntry.objects.create(event=planning_event, venue=venue, created_by=coordinator)
    with pytest.raises(IntegrityError), transaction.atomic():
        VenueShortlistEntry.objects.create(
            event=planning_event, venue=venue, created_by=coordinator
        )


def test_ac2_remove_deletes_only_that_events_entry(
    signed_in_coordinator, planning_event, organiser, coordinator
):
    venue = searchable_venue()
    other = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    add(signed_in_coordinator, planning_event, venue)
    add(signed_in_coordinator, other, venue)
    assert signed_in_coordinator.delete(url(planning_event, venue)).status_code == 204
    assert signed_in_coordinator.get(url(planning_event)).data["entries"] == []
    assert VenueShortlistEntry.objects.filter(event=other, venue=venue).exists()


def test_ac3_reopen_rechecks_current_venue_data_against_saved_filters(
    signed_in_coordinator, planning_event
):
    venue = searchable_venue()
    criteria = {"attendance": 60, "layout": "THEATRE", "facilities": ["Projector"]}
    assert add(signed_in_coordinator, planning_event, venue, criteria).status_code == 201
    venue.capacity = 59
    venue.layouts = []
    venue.save()
    match = signed_in_coordinator.get(url(planning_event)).data["entries"][0]["match"]
    results = {item["key"]: item["result"] for item in match["criteria"]}
    assert results["attendance"] == results["layout"] == "UNMET"
    assert results["facilities"] == "MATCH"
    assert results["booking_availability"] == "UNVERIFIED"
    assert match["matches_recorded_requirements"] is False
    assert match["venue"]["capacity"] == 59


def test_ac4_out_of_service_venue_is_flagged_on_reopen_without_deleting_saved_entry(
    signed_in_coordinator, planning_event
):
    venue = searchable_venue()
    add(signed_in_coordinator, planning_event, venue)
    venue.in_service = False
    venue.save(update_fields=["in_service"])
    match = signed_in_coordinator.get(url(planning_event)).data["entries"][0]["match"]
    assert match["availability_status"] == "UNAVAILABLE"
    assert match["criteria"][0]["result"] == "UNMET"
    assert VenueShortlistEntry.objects.count() == 1


def test_empty_shortlist_is_a_valid_empty_state(signed_in_coordinator, planning_event):
    response = signed_in_coordinator.get(url(planning_event))
    assert response.status_code == 200
    assert response.data["entries"] == []
    assert response.data["can_edit"] is True
    assert response.data["availability_integrated"] is False
    assert response.data["date_blocks_integrated"] is True


def test_unassigned_coordinator_can_read_submitted_event_but_cannot_modify_shortlist(
    api, other_coordinator, planning_event, coordinator
):
    venue = searchable_venue()
    entry = VenueShortlistEntry.objects.create(
        event=planning_event, venue=venue, created_by=coordinator
    )
    api.force_authenticate(other_coordinator)
    assert api.get(url(planning_event)).status_code == 200
    assert api.get(url(planning_event)).data["can_edit"] is False
    assert add(api, planning_event, venue).status_code == 403
    assert api.delete(url(planning_event, venue)).status_code == 403
    assert VenueShortlistEntry.objects.filter(pk=entry.pk).exists()
    assert AuditLog.objects.filter(actor=other_coordinator, allowed=False).count() == 2


@pytest.mark.parametrize(
    "fixture_name", ["organiser", "other_organiser", "attendee", "venue_staff", "tech_staff"]
)
def test_non_coordinators_cannot_read_or_write_shortlists(
    api, request, fixture_name, planning_event
):
    venue = searchable_venue()
    api.force_authenticate(request.getfixturevalue(fixture_name))
    assert api.get(url(planning_event)).status_code == 403
    assert add(api, planning_event, venue).status_code == 403
    assert api.delete(url(planning_event, venue)).status_code == 403
    assert not VenueShortlistEntry.objects.exists()


def test_anonymous_access_is_refused(api, planning_event):
    assert api.get(url(planning_event)).status_code == 403


def test_draft_events_stay_private_even_to_coordinators(
    signed_in_coordinator, organiser, coordinator
):
    draft = make_event(organiser, coordinator=coordinator)
    venue = searchable_venue()
    assert signed_in_coordinator.get(url(draft)).status_code == 403
    assert add(signed_in_coordinator, draft, venue).status_code == 403


@pytest.mark.parametrize(
    "status", [EventStatus.CANCELLED, EventStatus.COMPLETED, EventStatus.REJECTED]
)
def test_terminal_event_shortlists_are_read_only(signed_in_coordinator, planning_event, status):
    venue = searchable_venue()
    add(signed_in_coordinator, planning_event, venue)
    planning_event.status = status
    planning_event.save(update_fields=["status"])
    assert signed_in_coordinator.get(url(planning_event)).data["can_edit"] is False
    assert add(signed_in_coordinator, planning_event, venue).status_code == 400
    assert signed_in_coordinator.delete(url(planning_event, venue)).status_code == 400
    assert VenueShortlistEntry.objects.count() == 1


@pytest.mark.parametrize(
    "criteria", [{"attendance": 61}, {"layout": "BANQUET"}, {"facilities": ["Stage"]}]
)
def test_venue_that_no_longer_matches_cannot_be_added(
    signed_in_coordinator, planning_event, criteria
):
    assert (
        add(signed_in_coordinator, planning_event, searchable_venue(), criteria).status_code == 400
    )
    assert not VenueShortlistEntry.objects.exists()


def test_out_of_service_venue_cannot_be_added(signed_in_coordinator, planning_event):
    assert (
        add(signed_in_coordinator, planning_event, searchable_venue(in_service=False)).status_code
        == 400
    )


def test_invalid_nested_criteria_are_rejected(signed_in_coordinator, planning_event):
    assert (
        add(
            signed_in_coordinator, planning_event, searchable_venue(), {"attendance": 0}
        ).status_code
        == 400
    )


def test_unknown_event_venue_and_entry_are_not_found(signed_in_coordinator, planning_event):
    venue = searchable_venue()
    assert signed_in_coordinator.get("/api/events/999999/venue-shortlist/").status_code == 404
    assert (
        signed_in_coordinator.post(
            url(planning_event), {"venue_id": 999999}, format="json"
        ).status_code
        == 400
    )
    assert signed_in_coordinator.delete(url(planning_event, venue)).status_code == 404


def test_list_uses_constant_query_count(
    signed_in_coordinator, planning_event, coordinator, django_assert_num_queries
):
    for index in range(5):
        VenueShortlistEntry.objects.create(
            event=planning_event,
            venue=searchable_venue(name=f"Room {index}"),
            created_by=coordinator,
        )
    with django_assert_num_queries(3):
        response = signed_in_coordinator.get(url(planning_event))
    assert len(response.data["entries"]) == 5


def test_ac4_real_staff_block_flags_saved_entry_and_changes_refresh_without_removal(
    signed_in_coordinator, planning_event, venue_staff
):
    venue = searchable_venue()
    assert add(signed_in_coordinator, planning_event, venue, PERIOD).status_code == 201
    staff = APIClient()
    staff.force_authenticate(venue_staff)
    blocks = f"/api/venues/{venue.pk}/blocks/"
    created = staff.post(
        blocks,
        {
            "reason": "Air conditioning repair",
            "starts_at": PERIOD["start"],
            "ends_at": PERIOD["end"],
        },
        format="json",
    )
    assert created.status_code == 201
    reopened = signed_in_coordinator.get(url(planning_event))
    entry = reopened.data["entries"][0]
    assert parse_datetime(entry["search_criteria"]["start"]) == parse_datetime(PERIOD["start"])
    assert entry["match"]["availability_status"] == "UNAVAILABLE"
    assert entry["match"]["matches_recorded_requirements"] is False
    criterion = next(c for c in entry["match"]["criteria"] if c["key"] == "date_blocks")
    assert criterion["result"] == "UNMET"
    assert criterion["message"] == "Blocked: Air conditioning repair"
    assert VenueShortlistEntry.objects.filter(event=planning_event, venue=venue).exists()
    item = f"{blocks}{created.data['id']}/"
    assert (
        staff.patch(
            item,
            {"starts_at": "2027-03-02T01:00:00Z", "ends_at": "2027-03-02T09:00:00Z"},
            format="json",
        ).status_code
        == 200
    )
    assert (
        signed_in_coordinator.get(url(planning_event)).data["entries"][0]["match"][
            "availability_status"
        ]
        == "UNVERIFIED"
    )
    assert staff.delete(item).status_code == 204
    cleared = signed_in_coordinator.get(url(planning_event)).data["entries"][0]["match"]
    assert cleared["matches_recorded_requirements"] is True
    assert next(c for c in cleared["criteria"] if c["key"] == "date_blocks")["result"] == "MATCH"
    assert (
        next(c for c in cleared["criteria"] if c["key"] == "booking_availability")["result"]
        == "UNVERIFIED"
    )


def test_block_added_after_search_prevents_stale_shortlist_add(
    signed_in_coordinator, planning_event
):
    venue = searchable_venue()
    assert signed_in_coordinator.get("/api/venues/search/", PERIOD).data["results"]
    VenueBlock.objects.create(
        venue=venue, reason="Inspection", starts_at=PERIOD["start"], ends_at=PERIOD["end"]
    )
    assert add(signed_in_coordinator, planning_event, venue, PERIOD).status_code == 400
    assert not VenueShortlistEntry.objects.exists()
    assert not AuditLog.objects.filter(action=f"POST {url(planning_event)}", allowed=True).exists()


def test_ac4_without_saved_dates_rechecks_event_period_without_rewriting_saved_filters(
    signed_in_coordinator, planning_event
):
    planning_event.preferred_start = parse_datetime(PERIOD["start"])
    planning_event.preferred_end = parse_datetime(PERIOD["end"])
    planning_event.save()
    venue = searchable_venue()
    assert add(signed_in_coordinator, planning_event, venue).status_code == 201
    VenueBlock.objects.create(
        venue=venue, reason="Inspection", starts_at=PERIOD["start"], ends_at=PERIOD["end"]
    )
    entry = signed_in_coordinator.get(url(planning_event)).data["entries"][0]
    assert entry["search_criteria"] == {"facilities": []}
    assert entry["match"]["availability_status"] == "UNAVAILABLE"


def test_no_search_or_event_dates_does_not_invent_a_checked_period(
    signed_in_coordinator, planning_event
):
    planning_event.preferred_start = None
    planning_event.preferred_end = None
    planning_event.save()
    venue = searchable_venue()
    assert add(signed_in_coordinator, planning_event, venue).status_code == 201
    match = signed_in_coordinator.get(url(planning_event)).data["entries"][0]["match"]
    assert match["availability_status"] == "UNVERIFIED"
    assert "date_blocks" not in [c["key"] for c in match["criteria"]]


def test_response_failure_rolls_back_new_entry_and_success_audit(
    signed_in_coordinator, planning_event
):
    venue = searchable_venue()
    with (
        patch(
            "apps.venues.discovery_serializers.VenueShortlistEntrySerializer.to_representation",
            side_effect=RuntimeError("response failure"),
        ),
        pytest.raises(RuntimeError, match="response failure"),
    ):
        add(signed_in_coordinator, planning_event, venue)
    assert not VenueShortlistEntry.objects.exists()
    assert not AuditLog.objects.filter(action=f"POST {url(planning_event)}", allowed=True).exists()


def test_delete_failure_rolls_back_removal_and_success_audit(signed_in_coordinator, planning_event):
    venue = searchable_venue()
    add(signed_in_coordinator, planning_event, venue)
    original_delete = VenueShortlistEntry.delete

    def failing_delete(entry):
        original_delete(entry)
        raise RuntimeError("delete failure")

    with (
        patch.object(VenueShortlistEntry, "delete", failing_delete),
        pytest.raises(RuntimeError, match="delete failure"),
    ):
        signed_in_coordinator.delete(url(planning_event, venue))
    assert VenueShortlistEntry.objects.filter(event=planning_event, venue=venue).exists()
    assert not AuditLog.objects.filter(
        action=f"DELETE {url(planning_event, venue)}", allowed=True
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_adds_create_only_one_entry(planning_event, coordinator):
    venue = searchable_venue()
    barrier = Barrier(2)

    def attempt():
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(User.objects.get(pk=coordinator.pk))
            barrier.wait(timeout=10)
            return add(client, planning_event, venue).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: attempt(), range(2)))
    assert sorted(statuses) == [200, 201]
    assert VenueShortlistEntry.objects.count() == 1
