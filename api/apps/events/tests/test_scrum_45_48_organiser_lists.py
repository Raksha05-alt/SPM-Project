"""SCRUM-45 - View my organisation's event requests.
SCRUM-48 - Find and continue my saved drafts.

Case IDs follow the Sprint 3 guide: S3-SCRUM-45-<case> and S3-SCRUM-48-<case>.
"""

import datetime

import pytest
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest
from conftest import _make_user, make_event

EVENTS = "/api/events/"
DRAFTS = "/api/events/?group=drafts"
SUBMITTED = "/api/events/?group=submitted"


def detail_url(event):
    return f"/api/events/{event.pk}/"


@pytest.fixture
def colleague(acme):
    """A second organiser in the same client organisation."""
    from apps.accounts.models import Role

    return _make_user("colleague@acme.example", Role.EVENT_ORGANISER, acme, "Col", "League")


# S3-SCRUM-45-01 - AC1: every organisation request with name, date, status, coordinator.


@pytest.mark.django_db
def test_s3_45_01_ac1_every_request_of_the_organisation_is_listed(
    signed_in_organiser, organiser, colleague, coordinator
):
    assigned = make_event(
        organiser, status=EventStatus.APPROVED, coordinator=coordinator, name="Partner Summit"
    )
    unassigned = make_event(colleague, status=EventStatus.SUBMITTED, name="Board Dinner")

    rows = {row["id"]: row for row in signed_in_organiser.get(SUBMITTED).data}

    assert set(rows) == {assigned.pk, unassigned.pk}
    row = rows[assigned.pk]
    assert row["name"] == "Partner Summit"
    assert datetime.datetime.fromisoformat(row["preferred_start"]) == assigned.preferred_start
    assert (row["status"], row["status_label"]) == (EventStatus.APPROVED, "Approved")
    assert row["coordinator_name"] == "Cora Coordinator"
    # An explicit unassigned state, not a missing field.
    assert rows[unassigned.pk]["coordinator_name"] is None
    # Internal approval details stay hidden from the client.
    assert "approved_by_name" not in row


@pytest.mark.django_db
def test_s3_45_01_ac1_submitted_requests_are_newest_first(signed_in_organiser, organiser):
    now = timezone.now()
    older = make_event(
        organiser, status=EventStatus.SUBMITTED, submitted_at=now - datetime.timedelta(days=2)
    )
    newer = make_event(organiser, status=EventStatus.SUBMITTED, submitted_at=now)

    ids = [row["id"] for row in signed_in_organiser.get(SUBMITTED).data]

    assert ids == [newer.pk, older.pk]


# S3-SCRUM-45-02 - AC2: other organisations' requests never appear or open.


@pytest.mark.django_db
@pytest.mark.parametrize("url", [EVENTS, DRAFTS, SUBMITTED])
def test_s3_45_02_ac2_other_organisations_are_absent(
    signed_in_organiser, organiser, other_organiser, url
):
    mine = make_event(organiser, status=EventStatus.SUBMITTED)
    make_event(other_organiser, status=EventStatus.SUBMITTED, name="Globex Launch")
    make_event(other_organiser, name="Globex Draft")

    rows = signed_in_organiser.get(url).data

    assert all(row["organisation_name"] == "Acme Pte Ltd" for row in rows)
    assert "Globex" not in str(rows)
    if url != DRAFTS:
        assert mine.pk in [row["id"] for row in rows]


@pytest.mark.django_db
def test_s3_45_02_ac2_opening_another_organisations_request_is_refused(
    signed_in_organiser, organiser, other_organiser
):
    theirs = make_event(other_organiser, status=EventStatus.SUBMITTED, name="Globex Launch")

    response = signed_in_organiser.get(detail_url(theirs))

    assert response.status_code == 403
    assert "Globex Launch" not in str(response.data)
    assert AuditLog.objects.filter(actor=organiser, allowed=False).exists()


# S3-SCRUM-45-03 - AC3: a genuinely empty organisation gets an empty list, not an error.


@pytest.mark.django_db
@pytest.mark.parametrize("url", [EVENTS, DRAFTS, SUBMITTED])
def test_s3_45_03_ac3_no_requests_gives_an_empty_list(signed_in_organiser, other_organiser, url):
    make_event(other_organiser, status=EventStatus.SUBMITTED)

    response = signed_in_organiser.get(url)

    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_s3_45_03_an_unknown_group_is_a_clear_error(signed_in_organiser):
    response = signed_in_organiser.get("/api/events/?group=archived")

    assert response.status_code == 400
    assert "group" in response.data


# S3-SCRUM-45-04 - AC4: selecting a request opens its full details.


@pytest.mark.django_db
def test_s3_45_04_ac4_selecting_a_request_opens_its_details(
    signed_in_organiser, colleague, coordinator
):
    event = make_event(
        colleague,
        status=EventStatus.PLANNING,
        coordinator=coordinator,
        name="Partner Summit",
        description="Annual partner day with breakout rooms.",
    )

    data = signed_in_organiser.get(detail_url(event)).data

    assert data["id"] == event.pk
    assert data["description"] == "Annual partner day with breakout rooms."
    assert data["coordinator_name"] == "Cora Coordinator"
    assert data["is_editable"] is False


# S3-SCRUM-48-01 - AC1: drafts are listed together, apart from submitted requests.


@pytest.mark.django_db
def test_s3_48_01_ac1_drafts_are_grouped_apart_from_submitted_requests(
    signed_in_organiser, organiser
):
    first = make_event(organiser, name="Draft one")
    second = make_event(organiser, complete=False)
    sent = make_event(organiser, status=EventStatus.SUBMITTED, name="Sent one")

    drafts = signed_in_organiser.get(DRAFTS).data
    submitted = signed_in_organiser.get(SUBMITTED).data

    assert {row["id"] for row in drafts} == {first.pk, second.pk}
    assert all(row["status"] == EventStatus.DRAFT for row in drafts)
    assert [row["id"] for row in submitted] == [sent.pk]
    # Neither group drops anything from the whole list.
    everything = {row["id"] for row in signed_in_organiser.get(EVENTS).data}
    assert everything == {first.pk, second.pk, sent.pk}


# S3-SCRUM-48-02 - AC2: opening a draft continues from the saved values.


@pytest.mark.django_db
def test_s3_48_02_ac2_a_draft_reopens_with_its_saved_values(api, organiser):
    start = (timezone.now() + datetime.timedelta(days=40)).replace(microsecond=0)
    api.force_authenticate(organiser)
    created = api.post(
        EVENTS,
        {
            "name": "Harbour Gala",
            "purpose": "Client appreciation",
            "preferred_start": start.isoformat(),
            "preferred_end": (start + datetime.timedelta(hours=4)).isoformat(),
            "expected_attendance": 85,
        },
        format="json",
    ).data

    # A fresh session, as when the organiser comes back later.
    api.force_authenticate(None)
    api.force_authenticate(organiser)
    listed = api.get(DRAFTS).data
    assert [row["id"] for row in listed] == [created["id"]]
    reopened = api.get(detail_url(EventRequest(pk=created["id"]))).data

    assert reopened["name"] == "Harbour Gala"
    assert reopened["purpose"] == "Client appreciation"
    assert datetime.datetime.fromisoformat(reopened["preferred_start"]) == start
    assert reopened["expected_attendance"] == 85
    assert reopened["is_editable"] is True
    edited = api.patch(detail_url(EventRequest(pk=created["id"])), {"expected_attendance": 90})
    assert edited.status_code == 200
    assert edited.data["expected_attendance"] == 90


# S3-SCRUM-48-03 - AC3: each draft shows when it was last saved.


@pytest.mark.django_db
def test_s3_48_03_ac3_the_last_saved_time_updates_on_each_save(signed_in_organiser, organiser):
    draft = make_event(organiser, name="Draft one")
    first = signed_in_organiser.get(DRAFTS).data[0]["updated_at"]

    signed_in_organiser.patch(detail_url(draft), {"name": "Draft one, revised"}, format="json")
    second = signed_in_organiser.get(DRAFTS).data[0]

    assert datetime.datetime.fromisoformat(second["updated_at"]) > datetime.datetime.fromisoformat(
        first
    )
    draft.refresh_from_db()
    assert datetime.datetime.fromisoformat(second["updated_at"]) == draft.updated_at


@pytest.mark.django_db
def test_s3_48_03_drafts_are_most_recently_saved_first(signed_in_organiser, organiser):
    older = make_event(organiser, name="Older")
    newer = make_event(organiser, name="Newer")
    EventRequest.objects.filter(pk=older.pk).update(
        updated_at=timezone.now() - datetime.timedelta(days=3)
    )

    ids = [row["id"] for row in signed_in_organiser.get(DRAFTS).data]

    assert ids == [newer.pk, older.pk]


# S3-SCRUM-48-04 - AC4: no drafts gives an empty state, even with submitted requests.


@pytest.mark.django_db
def test_s3_48_04_ac4_no_drafts_gives_an_empty_list(signed_in_organiser, organiser):
    make_event(organiser, status=EventStatus.SUBMITTED)

    response = signed_in_organiser.get(DRAFTS)

    assert response.status_code == 200
    assert response.data == []
    assert len(signed_in_organiser.get(SUBMITTED).data) == 1


@pytest.mark.django_db
def test_s3_48_04_drafts_never_reach_connectsphere_staff(api, organiser, coordinator, lead):
    make_event(organiser, name="Private draft")

    for user in (coordinator, lead):
        api.force_authenticate(user)
        assert "Private draft" not in str(api.get(EVENTS).data)
