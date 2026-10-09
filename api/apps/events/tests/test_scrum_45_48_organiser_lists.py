"""SCRUM-45 (US-02.3) view my organisation's requests, SCRUM-48 (US-03.2) find my drafts."""

from datetime import datetime

import pytest

from apps.core.statuses import EventStatus
from conftest import make_event

EVENTS = "/api/events/"


@pytest.mark.django_db
def test_scrum45_ac1_every_request_of_my_organisation_is_listed_with_its_summary(
    signed_in_organiser, organiser, coordinator
):
    submitted = make_event(organiser, status=EventStatus.SUBMITTED, coordinator=coordinator)
    draft = make_event(organiser, complete=False)

    response = signed_in_organiser.get(EVENTS)

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.data}
    assert set(rows) == {submitted.pk, draft.pk}
    row = rows[submitted.pk]
    assert row["name"] == "Regional Partner Conference"
    assert row["preferred_start"] is not None
    assert row["status_label"] == "Submitted"
    assert row["coordinator_name"] == "Cora Coordinator"
    assert rows[draft.pk]["coordinator_name"] is None


@pytest.mark.django_db
def test_scrum45_ac1_colleagues_requests_from_the_same_organisation_are_included(
    signed_in_organiser, acme
):
    from apps.accounts.models import Role, User

    colleague = User.objects.create_user(
        username="colleague@acme.example",
        email="colleague@acme.example",
        password="x",
        role=Role.EVENT_ORGANISER,
        organisation=acme,
    )
    theirs = make_event(colleague, status=EventStatus.SUBMITTED)

    response = signed_in_organiser.get(EVENTS)

    assert theirs.pk in {row["id"] for row in response.data}


@pytest.mark.django_db
def test_scrum45_ac2_other_organisations_requests_do_not_appear(
    signed_in_organiser, other_organiser
):
    make_event(other_organiser, status=EventStatus.SUBMITTED)

    response = signed_in_organiser.get(EVENTS)

    assert response.data == []


@pytest.mark.django_db
def test_scrum45_ac3_no_requests_gives_an_empty_list_not_an_error(signed_in_organiser):
    response = signed_in_organiser.get(EVENTS)

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_scrum45_ac4_selecting_a_request_shows_its_full_details(
    signed_in_organiser, submitted_event
):
    response = signed_in_organiser.get(f"{EVENTS}{submitted_event.pk}/")

    assert response.status_code == 200
    assert response.data["purpose"] == "Annual partner briefing"
    assert response.data["expected_attendance"] == 120
    # Internal approval details stay hidden from the client.
    assert "approved_by_name" not in response.data


@pytest.mark.django_db
def test_scrum45_ac4_another_clients_request_cannot_be_opened(
    api, other_organiser, submitted_event
):
    api.force_authenticate(other_organiser)

    response = api.get(f"{EVENTS}{submitted_event.pk}/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_scrum48_ac1_drafts_are_distinguishable_from_submitted_requests(
    signed_in_organiser, organiser
):
    make_event(organiser, status=EventStatus.SUBMITTED)
    make_event(organiser, complete=False)

    response = signed_in_organiser.get(EVENTS, {"status": "DRAFT"})

    assert [row["status"] for row in response.data] == [EventStatus.DRAFT]
    assert response.data[0]["is_editable"] is True


@pytest.mark.django_db
def test_scrum48_ac2_reopening_a_draft_continues_from_the_saved_values(
    signed_in_organiser, organiser
):
    draft = make_event(organiser, complete=False, name="Half-written", purpose="Training")

    response = signed_in_organiser.get(f"{EVENTS}{draft.pk}/")

    assert response.data["name"] == "Half-written"
    assert response.data["purpose"] == "Training"
    assert response.data["preferred_start"] is None


@pytest.mark.django_db
def test_scrum48_ac3_each_draft_shows_when_it_was_last_saved(signed_in_organiser, incomplete_draft):
    signed_in_organiser.patch(
        f"{EVENTS}{incomplete_draft.pk}/", {"name": "Updated name"}, format="json"
    )
    incomplete_draft.refresh_from_db()

    response = signed_in_organiser.get(EVENTS, {"status": "DRAFT"})

    shown = datetime.fromisoformat(response.data[0]["updated_at"])
    assert shown == incomplete_draft.updated_at


@pytest.mark.django_db
def test_scrum48_ac4_no_drafts_gives_an_empty_list_not_an_error(signed_in_organiser, organiser):
    make_event(organiser, status=EventStatus.SUBMITTED)

    response = signed_in_organiser.get(EVENTS, {"status": "DRAFT"})

    assert response.status_code == 200
    assert response.data == []
