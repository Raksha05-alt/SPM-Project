"""SCRUM-82 - view and manage my notifications.

Read state is recipient-only, opening the list marks nothing read, and the
screen a notice opens is decided from the recipient's access *now*.
"""

import datetime

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind, NotificationTarget
from apps.notifications.services import (
    MissingOccurrence,
    destination,
    notify,
    status_occurrence,
)
from apps.safety.services import request_check
from conftest import _make_user, make_event

pytestmark = pytest.mark.django_db
LIST = "/api/notifications/"
COUNT = "/api/notifications/unread-count/"


def read_url(notice):
    return f"/api/notifications/{notice.pk}/read/"


def send(event, recipient, occurrence, kind=NotificationKind.EQUIPMENT_UPDATED, **extra):
    [notice] = notify(
        event=event,
        kind=kind,
        occurrence=occurrence,
        recipients=[recipient],
        message=f"{kind} about {event.name}",
        **extra,
    )
    return Notification.objects.get(recipient=recipient, occurrence=f"{kind}:{occurrence}")


@pytest.fixture
def event(organiser, coordinator):
    return make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator)


# --------------------------------------------------------------------------
# AC1 - my notices, most recent first
# --------------------------------------------------------------------------


def test_ac1_only_my_notices_are_listed_most_recent_first(api, event, organiser, coordinator):
    older = send(event, organiser, "a")
    newer = send(event, organiser, "b")
    Notification.objects.filter(pk=older.pk).update(
        created_at=timezone.now() - datetime.timedelta(hours=1)
    )
    send(event, coordinator, "c")
    api.force_authenticate(organiser)

    data = api.get(LIST).data

    assert [n["id"] for n in data] == [newer.pk, older.pk]


def test_ac1b_equal_times_still_list_newest_first(api, event, organiser):
    first, second = send(event, organiser, "a"), send(event, organiser, "b")
    Notification.objects.update(created_at=timezone.now())
    api.force_authenticate(organiser)

    assert [n["id"] for n in api.get(LIST).data] == [second.pk, first.pk]


def test_ac1c_signed_out_users_see_nothing(api):
    assert api.get(LIST).status_code in (401, 403)
    assert api.get(COUNT).status_code in (401, 403)


# --------------------------------------------------------------------------
# AC2 - opening a notice marks it read and the count goes down
# --------------------------------------------------------------------------


def test_ac2a_opening_a_notice_marks_only_it_read(api, event, organiser):
    first, second = send(event, organiser, "a"), send(event, organiser, "b")
    api.force_authenticate(organiser)
    assert api.get(COUNT).data == {"unread": 2}

    response = api.post(read_url(first))

    assert response.status_code == 200
    assert response.data["unread"] == 1
    assert response.data["notification"]["is_read"] is True
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.read_at is not None and second.read_at is None
    assert api.get(COUNT).data == {"unread": 1}


def test_ac2b_listing_marks_nothing_read(api, event, organiser):
    send(event, organiser, "a")
    api.force_authenticate(organiser)

    api.get(LIST)
    api.get(LIST)

    assert api.get(COUNT).data == {"unread": 1}
    assert api.get(LIST).data[0]["is_read"] is False


def test_ac2c_opening_again_changes_nothing(api, event, organiser):
    notice = send(event, organiser, "a")
    api.force_authenticate(organiser)
    api.post(read_url(notice))
    notice.refresh_from_db()
    first_read = notice.read_at

    response = api.post(read_url(notice))

    assert response.status_code == 200 and response.data["unread"] == 0
    notice.refresh_from_db()
    assert notice.read_at == first_read


def test_ac2d_no_one_can_mark_someone_elses_notice(api, event, organiser, coordinator):
    theirs = send(event, coordinator, "a")
    api.force_authenticate(organiser)

    assert api.post(read_url(theirs)).status_code == 404
    assert api.post("/api/notifications/999999/read/").status_code == 404
    theirs.refresh_from_db()
    assert theirs.read_at is None


# --------------------------------------------------------------------------
# AC3 - a notice opens its event, subject to my access now
# --------------------------------------------------------------------------


def destination_for(api, user, notice):
    api.force_authenticate(user)
    [data] = [n for n in api.get(LIST).data if n["id"] == notice.pk]
    return data["destination"]


@pytest.mark.parametrize(
    ("role", "path"),
    [
        (Role.EVENT_COORDINATOR_LEAD, "/lead/events/{event}"),
        (Role.VENUE_STAFF, "/venues/requests"),
        (Role.TECHNICAL_SUPPORT, "/equipment/plans/{event}"),
        (Role.SAFETY_OFFICER, "/safety"),
    ],
)
def test_ac3a_each_role_opens_its_own_screen(api, event, role, path):
    user = _make_user(f"{role.lower()}@x.example", role)
    notice = send(event, user, "a")

    assert destination_for(api, user, notice)["path"] == path.format(event=event.pk)


def test_ac3b_organiser_and_assigned_coordinator_open_the_event(api, event, organiser, coordinator):
    assert destination_for(api, organiser, send(event, organiser, "a"))["path"] == (
        f"/organiser/requests/{event.pk}"
    )
    assert destination_for(api, coordinator, send(event, coordinator, "b"))["path"] == (
        f"/coordinator/events/{event.pk}"
    )


def test_ac3c_a_safety_notice_opens_its_check(api, ready_event, coordinator, safety_officer):
    check = request_check(ready_event, coordinator)
    notice = Notification.objects.get(
        recipient=safety_officer, kind=NotificationKind.SAFETY_REQUESTED
    )

    assert notice.target_type == NotificationTarget.SAFETY_CHECK
    assert destination_for(api, safety_officer, notice) == {
        "path": f"/safety/checks/{check.pk}",
        "label": "Open the safety check",
    }


def test_ac3d_a_reassigned_coordinator_keeps_the_notice_but_not_the_access(
    api, event, coordinator, second_coordinator
):
    notice = send(event, coordinator, "a")
    event.coordinator = second_coordinator
    event.save(update_fields=["coordinator"])

    assert destination_for(api, coordinator, notice) is None
    # The retained notice grants nothing: the event itself stays closed to them.
    assert api.get(f"/api/events/{event.pk}/").status_code in (403, 404)


def test_ac3e_a_role_change_removes_the_destination(api, event, coordinator):
    notice = send(event, coordinator, "a")
    coordinator.role = Role.ATTENDEE
    coordinator.save(update_fields=["role"])

    # A Planning event is not visible to attendees.
    assert destination_for(api, coordinator, notice) is None


def test_ac3f_attendees_open_events_once_they_are_visible(api, organiser, attendee):
    planning = make_event(organiser, status=EventStatus.PLANNING)
    confirmed = make_event(organiser, status=EventStatus.CONFIRMED)

    assert destination_for(api, attendee, send(planning, attendee, "a")) is None
    assert destination_for(api, attendee, send(confirmed, attendee, "b"))["path"] == "/events"


def test_ac3g_another_organisations_event_opens_nothing(api, event, other_organiser):
    assert destination_for(api, other_organiser, send(event, other_organiser, "a")) is None


def test_ac3h_a_stale_safety_target_falls_back_to_the_queue(api, event, safety_officer):
    notice = send(
        event,
        safety_officer,
        "a",
        target_type=NotificationTarget.SAFETY_CHECK,
        target_id=987654,
    )

    assert destination_for(api, safety_officer, notice)["path"] == "/safety"


def test_ac3i_drafts_open_nothing_for_internal_staff(api, organiser, lead):
    draft = make_event(organiser)

    assert destination_for(api, lead, send(draft, lead, "a")) is None


# --------------------------------------------------------------------------
# AC4 - no notices is an empty list, not an error
# --------------------------------------------------------------------------


def test_ac4_no_notices_is_an_empty_list(api, organiser):
    api.force_authenticate(organiser)

    assert api.get(LIST).status_code == 200
    assert api.get(LIST).data == []
    assert api.get(COUNT).data == {"unread": 0}


def test_ac3j_an_inactive_account_opens_nothing(event, coordinator):
    notice = send(event, coordinator, "a")
    coordinator.is_active = False

    assert destination(notice, coordinator) is None


def test_w6_an_event_without_status_history_has_no_status_occurrence(organiser):
    with pytest.raises(MissingOccurrence):
        status_occurrence(make_event(organiser))
