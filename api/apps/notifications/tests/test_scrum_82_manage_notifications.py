"""SCRUM-82 (US-20.3) - view and manage my notifications."""

import pytest
from django.utils import timezone

from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from conftest import make_event


def note(user, event, message="Something happened", **extra):
    return Notification.objects.create(
        recipient=user, event=event, kind=NotificationKind.STATUS_CHANGED, message=message, **extra
    )


@pytest.fixture
def event(organiser):
    return make_event(organiser, status=EventStatus.SUBMITTED)


@pytest.mark.django_db
def test_ac1_my_notifications_are_listed_newest_first(
    signed_in_organiser, organiser, coordinator, event
):
    older = note(organiser, event, "First")
    newer = note(organiser, event, "Second")
    note(coordinator, event, "Not mine")
    Notification.objects.filter(pk=older.pk).update(
        created_at=timezone.now() - timezone.timedelta(hours=1)
    )

    data = signed_in_organiser.get("/api/notifications/").data

    assert [row["id"] for row in data] == [newer.pk, older.pk]


@pytest.mark.django_db
def test_ac2_opening_an_unread_notification_marks_it_read_and_lowers_the_count(
    signed_in_organiser, organiser, event
):
    first = note(organiser, event)
    note(organiser, event)
    assert signed_in_organiser.get("/api/notifications/unread-count/").data == {"unread": 2}

    response = signed_in_organiser.post(f"/api/notifications/{first.pk}/read/")

    assert response.status_code == 200
    assert response.data["is_read"] is True
    assert response.data["unread"] == 1
    assert signed_in_organiser.get("/api/notifications/unread-count/").data == {"unread": 1}


@pytest.mark.django_db
def test_ac2_opening_it_again_keeps_the_first_read_time(signed_in_organiser, organiser, event):
    read_at = timezone.now() - timezone.timedelta(days=1)
    seen = note(organiser, event, read_at=read_at)

    response = signed_in_organiser.post(f"/api/notifications/{seen.pk}/read/")

    seen.refresh_from_db()
    assert seen.read_at == read_at
    assert response.data["unread"] == 0


@pytest.mark.django_db
def test_ac2_someone_elses_notification_cannot_be_opened(signed_in_organiser, coordinator, event):
    theirs = note(coordinator, event)

    assert signed_in_organiser.post(f"/api/notifications/{theirs.pk}/read/").status_code == 404
    theirs.refresh_from_db()
    assert theirs.read_at is None


@pytest.mark.django_db
def test_ac3_a_notification_links_to_its_event_which_still_checks_access(
    api, other_organiser, organiser, event
):
    mine = note(organiser, event)
    api.force_authenticate(organiser)

    [row] = api.get("/api/notifications/").data

    assert row["event"] == event.pk == mine.event_id
    assert api.get(f"/api/events/{row['event']}/").status_code == 200
    api.force_authenticate(other_organiser)
    assert api.get(f"/api/events/{row['event']}/").status_code == 403


@pytest.mark.django_db
def test_ac4_no_notifications_is_an_empty_list_not_an_error(signed_in_coordinator):
    response = signed_in_coordinator.get("/api/notifications/")

    assert response.status_code == 200
    assert response.data == []
    assert signed_in_coordinator.get("/api/notifications/unread-count/").data == {"unread": 0}
