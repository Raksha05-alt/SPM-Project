"""SCRUM-18 - be notified when a confirmed event changes.

Everything that makes the event and its attendees is real: venue and
equipment approved through the SCRUM-11/72/74/16 actions, the Safety check
requested and approved, the event confirmed through SCRUM-58; the organiser
opens registration through SCRUM-81's ``set_policy``; attendees register,
withdraw and join the waiting list through SCRUM-21/14/19. Cancellation runs
through the real SCRUM-77 endpoint.

AC1/AC2 through a real date/time/venue change close later: no action applies
such a change to a confirmed event until DISRUPTION (SCRUM-86) and APPLY
(SCRUM-80) call ``notify_attendees_of_change``. The ``c``-prefixed cases test
that published callback with real persisted events and registrations.
"""

import datetime
from unittest import mock

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.events.confirmation import confirm_event
from apps.events.impact import (
    describe_for_attendees,
    notify_attendees_of_change,
    registered_attendees,
)
from apps.events.models import EventStatusHistory
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.services import join_waitlist, register, set_policy, withdraw
from apps.safety.models import SafetyStatus
from apps.safety.services import decide, request_check
from apps.safety.tests.conftest import approve_equipment, approve_venue
from apps.safety.tests.conftest import planning_event as planning_event  # noqa: F401
from apps.safety.tests.conftest import safety_officer as safety_officer  # noqa: F401
from apps.safety.tests.conftest import tech as tech  # noqa: F401
from apps.safety.tests.conftest import venue as venue  # noqa: F401
from conftest import _make_user, make_event

pytestmark = pytest.mark.django_db


def attendee_user(name):
    return _make_user(f"{name.lower()}@example.com", Role.ATTENDEE, None, name, "Attendee")


def sign_up(event, user):
    return register(event=event, attendee=user, full_name=user.get_full_name(), email=user.email)


@pytest.fixture
def confirmed(planning_event, venue, venue_staff, tech, coordinator, safety_officer, organiser):
    """A really confirmed event with open registration for two places, a waiting
    list, Ana and Ben registered, Cal withdrawn and Dee waiting."""
    approve_venue(planning_event, venue, venue_staff)
    approve_equipment(planning_event, tech)
    decide(request_check(planning_event, coordinator), safety_officer, SafetyStatus.APPROVED)
    event = confirm_event(planning_event, coordinator)
    now = timezone.now()
    set_policy(
        event=event,
        actor=organiser,
        enabled=True,
        opens_at=now - datetime.timedelta(hours=1),
        closes_at=now + datetime.timedelta(days=7),
        capacity=2,
        waitlist_enabled=True,
    )
    ana, ben, cal, dee = (attendee_user(n) for n in ("Ana", "Ben", "Cal", "Dee"))
    sign_up(event, ana)
    cal_registration = sign_up(event, cal)
    withdraw(registration=cal_registration, actor=cal, confirm=True)
    sign_up(event, ben)
    join_waitlist(event=event, attendee=dee, full_name="Dee Attendee", email=dee.email)
    event.refresh_from_db()
    return event, {"ana": ana, "ben": ben, "cal": cal, "dee": dee}


def notices(kind):
    return Notification.objects.filter(kind=kind)


def attendee_notices(kind, people):
    ids = {p.pk for p in people.values()}
    return notices(kind).filter(recipient_id__in=ids)


def cancel(api, coordinator, event, reason="Client withdrew funding."):
    api.force_authenticate(coordinator)
    preview = api.get(f"/api/events/{event.pk}/cancellation-preview/")
    assert preview.status_code == 200, preview.data
    return api.post(
        f"/api/events/{event.pk}/cancel/",
        {"expected_version": preview.data["version"], "confirm_cancel": True, "reason": reason},
        format="json",
    )


# --------------------------------------------------------------------------
# AC3/AC4 - who counts as registered
# --------------------------------------------------------------------------


def test_ac3a_only_attendees_registered_for_the_event_are_recipients(confirmed):
    event, people = confirmed

    assert registered_attendees(event) == sorted([people["ana"].pk, people["ben"].pk])


def test_ac4a_withdrawn_and_waitlisted_attendees_are_not_recipients(confirmed):
    event, people = confirmed

    recipients = registered_attendees(event)
    assert people["cal"].pk not in recipients  # withdrew
    assert people["dee"].pk not in recipients  # only on the waiting list


def test_ac4b_another_events_registrants_are_not_recipients(confirmed, organiser):
    event, people = confirmed
    other = make_event(organiser, name="Other Summit")

    assert registered_attendees(other) == []


def test_ac4c_deactivated_attendees_are_not_recipients(confirmed):
    event, people = confirmed
    people["ben"].is_active = False
    people["ben"].save(update_fields=["is_active"])

    assert registered_attendees(event) == [people["ana"].pk]


# --------------------------------------------------------------------------
# AC5 - cancellation through the real SCRUM-77 action
# --------------------------------------------------------------------------


def test_ac5a_cancelling_notifies_each_registered_attendee_once(api, confirmed, coordinator):
    event, people = confirmed

    response = cancel(api, coordinator, event)

    assert response.status_code == 200, response.data
    sent = attendee_notices(NotificationKind.EVENT_CANCELLED, people)
    assert sorted(n.recipient_id for n in sent) == sorted([people["ana"].pk, people["ben"].pk])
    history = EventStatusHistory.objects.filter(event=event).order_by("-pk").first()
    assert {n.occurrence for n in sent} == {f"EVENT_CANCELLED:event-status:{history.pk}"}


def test_ac5b_the_cancellation_notice_names_the_event_and_date_but_no_internal_reason(
    api, confirmed, coordinator
):
    event, people = confirmed

    cancel(api, coordinator, event, reason="Budget cut by the client's finance team.")

    notice = attendee_notices(NotificationKind.EVENT_CANCELLED, people).first()
    assert event.name in notice.message
    assert "has been cancelled" in notice.message
    assert "Budget cut" not in notice.message


def test_ac5c_withdrawn_and_waitlisted_attendees_hear_nothing_of_the_cancellation(
    api, confirmed, coordinator
):
    event, people = confirmed

    cancel(api, coordinator, event)

    assert not Notification.objects.filter(
        recipient__in=[people["cal"], people["dee"]], kind=NotificationKind.EVENT_CANCELLED
    ).exists()


def test_ac5d_a_replay_of_the_cancellation_notice_sends_nothing_new(api, confirmed, coordinator):
    from apps.events.impact import notify_attendees_of_cancellation
    from apps.notifications.services import status_occurrence

    event, people = confirmed
    cancel(api, coordinator, event)
    event.refresh_from_db()

    assert notify_attendees_of_cancellation(event, occurrence=status_occurrence(event)) == []
    assert attendee_notices(NotificationKind.EVENT_CANCELLED, people).count() == 2


def test_ac5e_a_failed_attendee_notice_rolls_the_whole_cancellation_back(
    api, confirmed, coordinator
):
    event, people = confirmed

    with (
        mock.patch(
            "apps.events.impact.notify", side_effect=RuntimeError("notification store down")
        ),
        pytest.raises(RuntimeError),
    ):
        cancel(api, coordinator, event)

    event.refresh_from_db()
    assert event.status == "CONFIRMED"
    assert not notices(NotificationKind.EVENT_CANCELLED).exists()


def test_ac5f_attendees_open_the_notice_on_their_events_page(api, confirmed, coordinator):
    event, people = confirmed
    cancel(api, coordinator, event)
    api.force_authenticate(people["ana"])

    listed = api.get("/api/notifications/").data
    [data] = [n for n in listed if n["kind"] == NotificationKind.EVENT_CANCELLED]

    assert listed[0]["id"] == data["id"]  # the newest notice
    assert data["destination"] == {"path": "/events", "label": "Open events"}


# --------------------------------------------------------------------------
# AC1-AC3 - the published change callback (real producers: SCRUM-86/80)
# --------------------------------------------------------------------------


def test_c1_a_change_notifies_registered_attendees_with_the_updated_details(confirmed):
    event, people = confirmed

    sent = notify_attendees_of_change(event, changed=["date", "venue"], occurrence="change:1")

    assert sorted(n.recipient_id for n in sent) == sorted([people["ana"].pk, people["ben"].pk])
    message = (
        Notification.objects.filter(recipient=people["ana"])
        .get(kind=NotificationKind.EVENT_CHANGED)
        .message
    )
    assert message.startswith(f'The date and venue of "{event.name}", which you are registered')
    assert "Updated details:" in message
    assert "Harbour Hall, Level 2, Marina Wing" in message


def test_c2_the_details_are_current_and_in_singapore_time(confirmed):
    event, _ = confirmed
    start = timezone.localtime(event.preferred_start)

    details = describe_for_attendees(event)

    assert details.startswith(f"When: {start:%a %d %b %Y, %H:%M} to ")
    assert "(Singapore time)" in details
    assert "Where: Harbour Hall, Level 2, Marina Wing (" in details


def test_c3_the_details_never_include_internal_or_safety_information(confirmed):
    event, _ = confirmed

    details = describe_for_attendees(event)

    for internal in ("fire exit", "load limit", "Approved by", "Safety", "capacity"):
        assert internal.lower() not in details.lower()


def test_c4_only_this_events_active_registrants_hear_of_a_change(confirmed, organiser):
    event, people = confirmed
    other = make_event(organiser, name="Other Summit")
    lone = attendee_user("Eve")

    notify_attendees_of_change(event, changed=["time"], occurrence="change:2")

    recipients = set(notices(NotificationKind.EVENT_CHANGED).values_list("recipient", flat=True))
    assert recipients == {people["ana"].pk, people["ben"].pk}
    assert lone.pk not in recipients
    assert registered_attendees(other) == []


def test_c5_a_replayed_change_does_not_notify_twice_but_a_later_one_does(confirmed):
    event, people = confirmed

    notify_attendees_of_change(event, changed=["time"], occurrence="change:3")
    assert notify_attendees_of_change(event, changed=["time"], occurrence="change:3") == []
    notify_attendees_of_change(event, changed=["venue"], occurrence="change:4")

    assert notices(NotificationKind.EVENT_CHANGED).filter(recipient=people["ana"]).count() == 2


@pytest.mark.parametrize("changed", [[], ["name"], ["date", "attendance"]])
def test_c6_the_callback_refuses_changes_attendees_are_not_told_about(confirmed, changed):
    event, _ = confirmed

    with pytest.raises(ValueError):
        notify_attendees_of_change(event, changed=changed, occurrence="change:5")
    assert not notices(NotificationKind.EVENT_CHANGED).exists()


def test_c7_an_event_without_registrations_notifies_nobody(organiser):
    event = make_event(organiser, status="CONFIRMED")

    assert notify_attendees_of_change(event, changed=["date"], occurrence="change:6") == []


def test_c8_periods_across_days_and_missing_details_read_clearly(organiser):
    from apps.events.impact import _period

    start = timezone.make_aware(datetime.datetime(2027, 3, 1, 22, 0))
    event = make_event(organiser, preferred_start=None, preferred_end=None)

    assert _period(start, start + datetime.timedelta(hours=4)) == (
        "Mon 01 Mar 2027, 22:00 to Tue 02 Mar 2027, 02:00"
    )
    assert describe_for_attendees(event) == (
        "When: date and time to be confirmed (Singapore time). Where: venue to be confirmed."
    )


def test_scrum_86_real_disruption_replacement_and_fresh_safety(
    api, confirmed, venue_staff, coordinator, safety_officer
):
    from apps.core.statuses import EventStatus
    from apps.venues.bookings import approve_booking, request_booking
    from apps.venues.models import BookingStatus
    from apps.venues.tests.conftest import make_venue

    event, people = confirmed
    original = event.venue_bookings.get(status=BookingStatus.APPROVED)
    api.force_authenticate(venue_staff)
    response = api.post(
        f"/api/venues/{original.venue_id}/blocks/",
        {
            "reason": "INTERNAL broken exit",
            "reason_category": "SAFETY_CONCERN",
            "starts_at": original.starts_at.isoformat(),
            "ends_at": original.ends_at.isoformat(),
        },
        format="json",
    )
    assert response.status_code == 201
    event.refresh_from_db()
    original.refresh_from_db()
    assert event.status == EventStatus.PLANNING and original.status == BookingStatus.DISRUPTED
    recipients = set(
        attendee_notices(NotificationKind.EVENT_CHANGED, people).values_list(
            "recipient_id", flat=True
        )
    )
    assert recipients == {people["ana"].pk, people["ben"].pk}
    assert all(
        "INTERNAL" not in n.message
        for n in attendee_notices(NotificationKind.EVENT_CHANGED, people)
    )
    api.force_authenticate(coordinator)
    refused = api.post(f"/api/events/{event.pk}/confirm/", {}, format="json")
    assert refused.status_code == 409
    detail = api.get(f"/api/events/{event.pk}/")
    assert detail.status_code == 200
    assert detail.data["venue_disruptions"][0]["booking"] == original.pk
    assert detail.data["venue_disruptions"][0]["venue"] == original.venue.name
    assert any(f"disrupted booking #{original.pk}" in gap for gap in refused.data["missing"])
    old = original.venue
    replacement_venue = make_venue(
        name="Replacement auditorium",
        opens_at=old.opens_at,
        closes_at=old.closes_at,
        capacity=old.capacity,
        layouts=old.layouts,
        facilities=old.facilities,
        wheelchair_access=old.wheelchair_access,
    )
    replacement = request_booking(
        event=event,
        venue=replacement_venue,
        requested_by=coordinator,
        session_id=original.session_id,
        replaces_id=original.pk,
        starts_at=original.starts_at,
        ends_at=original.ends_at,
        attendance=original.attendance,
        layout=original.layout,
        required_facilities=original.required_facilities,
        wheelchair_access_required=original.wheelchair_access_required,
    )
    approve_booking(replacement, venue_staff)
    assert api.post(f"/api/events/{event.pk}/confirm/", {}, format="json").status_code == 409
    decide(request_check(event, coordinator), safety_officer, SafetyStatus.APPROVED)
    assert api.post(f"/api/events/{event.pk}/confirm/", {}, format="json").status_code == 200
    original.refresh_from_db()
    assert original.status == BookingStatus.DISRUPTED
