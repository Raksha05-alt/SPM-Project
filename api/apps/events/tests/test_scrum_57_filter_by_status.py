"""SCRUM-57: real list requests; status filtering must follow permission scoping."""

import pytest

from apps.core.statuses import EventStatus
from conftest import make_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def events(organiser, coordinator, second_coordinator):
    own = {
        status: make_event(organiser, status=status, coordinator=coordinator, name=f"Own {status}")
        for status in (
            EventStatus.DRAFT,
            EventStatus.APPROVED,
            EventStatus.PLANNING,
            EventStatus.CONFIRMED,
        )
    }
    foreign = make_event(
        organiser,
        status=EventStatus.PLANNING,
        coordinator=second_coordinator,
        name="Other coordinator's planning",
    )
    unassigned = make_event(organiser, status=EventStatus.PLANNING, name="Unassigned planning")
    return own, foreign, unassigned


@pytest.mark.parametrize("path", ["/api/events/", "/api/events/mine/"])
@pytest.mark.parametrize(
    "query",
    [
        "status=PLANNING&status=CONFIRMED",
        "status=PLANNING,CONFIRMED",
        "status=%20PLANNING%20,,CONFIRMED&status=PLANNING",
    ],
)
def test_ac1_multiple_statuses_have_or_semantics(api, coordinator, events, path, query):
    own, _, _ = events
    api.force_authenticate(coordinator)
    response = api.get(f"{path}?{query}")
    assert response.status_code == 200
    assert {row["id"] for row in response.data} == {own["PLANNING"].pk, own["CONFIRMED"].pk}


@pytest.mark.parametrize("path", ["/api/events/", "/api/events/mine/"])
def test_ac1_single_status_preserves_action_priority(api, coordinator, events, path):
    own, _, _ = events
    api.force_authenticate(coordinator)
    response = api.get(f"{path}?status=PLANNING")
    assert [row["id"] for row in response.data] == [own["PLANNING"].pk]


@pytest.mark.parametrize("path", ["/api/events/", "/api/events/mine/"])
def test_ac2_no_matches_is_an_empty_success(api, coordinator, events, path):
    api.force_authenticate(coordinator)
    response = api.get(f"{path}?status=COMPLETED")
    assert response.status_code == 200 and response.data == []


@pytest.mark.parametrize("path", ["/api/events/", "/api/events/mine/"])
def test_invalid_status_names_the_bad_value_without_returning_events(
    api, coordinator, events, path
):
    api.force_authenticate(coordinator)
    response = api.get(f"{path}?status=PLANNING&status=NOT_A_STATUS")
    assert response.status_code == 400
    assert response.data == {"status": ["Unknown status: NOT_A_STATUS."]}


@pytest.mark.parametrize("path", ["/api/events/", "/api/events/mine/"])
def test_ac3_filters_never_reveal_other_unassigned_private_or_reassigned_events(
    api, coordinator, second_coordinator, events, path
):
    own, foreign, unassigned = events
    api.force_authenticate(coordinator)
    assert api.get(f"{path}?status=DRAFT").data == []
    type(own["PLANNING"]).objects.filter(pk=own["PLANNING"].pk).update(
        coordinator=second_coordinator
    )
    result = api.get(f"{path}?status=PLANNING&status=CONFIRMED")
    assert result.status_code == 200
    assert [r["id"] for r in result.data] == [own["CONFIRMED"].pk]
    assert not {foreign.pk, unassigned.pk, own["PLANNING"].pk}.intersection(
        r["id"] for r in result.data
    )


@pytest.mark.parametrize("query", ["", "?status=", "?status=,,"])
def test_ac4_clear_restores_every_permitted_row_and_priority(api, coordinator, events, query):
    own, _, _ = events
    api.force_authenticate(coordinator)
    assert len(api.get("/api/events/mine/?status=CONFIRMED").data) == 1
    result = api.get(f"/api/events/mine/{query}")
    assert result.status_code == 200
    assert [r["id"] for r in result.data] == [
        own["APPROVED"].pk,
        own["PLANNING"].pk,
        own["CONFIRMED"].pk,
    ]


def test_ac3_organisation_grouping_survives_filtering_and_clear(
    api, organiser, other_organiser, coordinator
):
    draft = make_event(organiser, status=EventStatus.DRAFT)
    submitted = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    make_event(other_organiser, status=EventStatus.PLANNING, coordinator=coordinator)
    api.force_authenticate(organiser)
    filtered = api.get("/api/events/?group=submitted&status=PLANNING&status=DRAFT")
    assert filtered.status_code == 200 and [r["id"] for r in filtered.data] == [submitted.pk]
    cleared = api.get("/api/events/?group=submitted")
    assert [r["id"] for r in cleared.data] == [submitted.pk]
    assert [r["id"] for r in api.get("/api/events/?group=drafts&status=DRAFT").data] == [draft.pk]


def test_ac3_attendee_cannot_recover_internal_events_with_a_filter(api, attendee, events):
    own, _, _ = events
    api.force_authenticate(attendee)
    response = api.get("/api/events/?status=PLANNING&status=CONFIRMED&status=DRAFT")
    assert response.status_code == 200 and [r["id"] for r in response.data] == [own["CONFIRMED"].pk]
    assert "purpose" not in response.data[0] and "organisation_name" not in response.data[0]


@pytest.mark.parametrize("who", ["organiser", "attendee", "lead", "venue_staff"])
def test_ac3_assigned_list_requires_coordinator_before_filter_validation(api, request, who):
    api.force_authenticate(request.getfixturevalue(who))
    assert api.get("/api/events/mine/?status=NOT_A_STATUS").status_code == 403


def test_ac3_anonymous_list_refused(api):
    assert api.get("/api/events/?status=CONFIRMED").status_code == 403


def test_filter_does_not_change_object_access_or_persist_state(api, coordinator, events):
    own, foreign, _ = events
    api.force_authenticate(coordinator)
    assert api.get(f"/api/events/{own['PLANNING'].pk}/?status=NOT_A_STATUS").status_code == 200
    assert api.get(f"/api/events/{foreign.pk}/?status=PLANNING").status_code == 403
    assert api.get("/api/events/?status=CONFIRMED").status_code == 200
    own["PLANNING"].refresh_from_db()
    assert own["PLANNING"].status == EventStatus.PLANNING
