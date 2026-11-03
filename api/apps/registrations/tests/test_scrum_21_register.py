"""SCRUM-21 - Register for an event.

As an Event Attendee, I want to register for a confirmed event during its
registration period, so that I can secure a place.

Case IDs follow the Sprint 4 guide: S4-21-<case>.
"""

import datetime

import pytest

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.events.confirmation import confirm_event
from apps.notifications.models import Notification, NotificationKind
from apps.registrations.models import (
    Registration,
    RegistrationHistory,
    RegistrationStatus,
)
from apps.registrations.services import (
    AlreadyRegistered,
    RegistrationRefused,
    register,
    set_policy,
)
from apps.registrations.tests.conftest import details, open_policy
from apps.safety.models import SafetyStatus
from apps.safety.services import decide, request_check
from apps.safety.tests.conftest import (  # noqa: F401 - fixtures used by name
    planning_event,
    ready_event,  # noqa: F811
    safety_officer,
    tech,
    venue,
)


def register_url(event):
    return f"/api/events/{event.pk}/registration/"


MINE = "/api/registrations/mine/"


@pytest.fixture
def attendee_api(api, attendee):
    api.force_authenticate(attendee)
    return api


# S4-21-01 - AC1: a confirmed, enabled and open event records the registration.


@pytest.mark.django_db
def test_s4_21_01_ac1_registering_records_it_and_confirms(attendee_api, attendee, confirmed_event):
    open_policy(confirmed_event)

    response = attendee_api.post(
        register_url(confirmed_event),
        details(attendee, accessibility_requirements="Wheelchair space"),
        format="json",
    )

    assert response.status_code == 201
    assert response.data["detail"] == 'You are registered for "Harbour Gala".'
    registration = Registration.objects.get()
    assert (registration.event, registration.attendee, registration.status) == (
        confirmed_event,
        attendee,
        RegistrationStatus.REGISTERED,
    )
    assert (registration.full_name, registration.email) == ("Andy Attendee", "attendee@example.com")
    assert registration.accessibility_requirements == "Wheelchair space"
    history = RegistrationHistory.objects.get(registration=registration)
    assert (history.from_status, history.to_status, history.actor) == (
        "",
        RegistrationStatus.REGISTERED,
        attendee,
    )
    notice = Notification.objects.get(kind=NotificationKind.REGISTERED)
    assert notice.recipient == attendee
    assert "You are registered" in notice.message
    summary = attendee_api.get(register_url(confirmed_event)).data
    assert summary["my_status"] == RegistrationStatus.REGISTERED
    assert summary["remaining"] == 49


# S4-21-02 - AC2: missing required information is named and nothing is saved.


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides,missing",
    [
        ({"full_name": ""}, ["full_name"]),
        ({"email": "   "}, ["email"]),
        ({"full_name": "", "email": ""}, ["full_name", "email"]),
        ({"email": "not-an-email"}, ["email"]),
    ],
)
def test_s4_21_02_ac2_missing_information_is_named(
    attendee_api, attendee, confirmed_event, overrides, missing
):
    open_policy(confirmed_event)

    response = attendee_api.post(
        register_url(confirmed_event), details(attendee, **overrides), format="json"
    )

    assert response.status_code == 400
    assert response.data["missing"] == missing
    for field in missing:
        assert field in response.data
    assert not Registration.objects.exists()
    assert not Notification.objects.filter(kind=NotificationKind.REGISTERED).exists()


# S4-21-03 - AC3: a second attempt is refused and the existing registration shown.


@pytest.mark.django_db
def test_s4_21_03_ac3_registering_twice_shows_the_existing_registration(
    attendee_api, attendee, confirmed_event
):
    open_policy(confirmed_event)
    first = attendee_api.post(register_url(confirmed_event), details(attendee), format="json")

    again = attendee_api.post(
        register_url(confirmed_event), details(attendee, full_name="Another Name"), format="json"
    )

    assert again.status_code == 409
    assert again.data["registration"]["id"] == first.data["registration"]["id"]
    assert again.data["registration"]["full_name"] == "Andy Attendee"
    assert Registration.objects.count() == 1


@pytest.mark.django_db
def test_s4_21_03_ac3_the_service_refuses_a_duplicate(attendee, confirmed_event):
    open_policy(confirmed_event)
    existing = register(event=confirmed_event, attendee=attendee, **details(attendee))

    with pytest.raises(AlreadyRegistered) as caught:
        register(event=confirmed_event, attendee=attendee, **details(attendee))
    assert caught.value.registration == existing


# S4-21-04 - AC4: my events show status and the confirmed date, time and venue.


@pytest.mark.django_db
def test_s4_21_04_ac4_my_events_show_status_and_confirmed_details(
    api,
    attendee,
    organiser,
    coordinator,
    ready_event,  # noqa: F811
    safety_officer,  # noqa: F811
):
    # The real SCRUM-58 journey: venue and equipment approved, safety approved, confirmed.
    decide(request_check(ready_event, coordinator), safety_officer, SafetyStatus.APPROVED)
    confirm_event(ready_event, coordinator)
    set_policy(event=ready_event, actor=organiser, enabled=True, capacity=100)
    register(event=ready_event, attendee=attendee, **details(attendee))
    api.force_authenticate(attendee)

    rows = api.get(MINE).json()

    assert len(rows) == 1
    row = rows[0]
    assert (row["status"], row["status_label"]) == (RegistrationStatus.REGISTERED, "Registered")
    event = row["event_details"]
    assert event["status"] == EventStatus.CONFIRMED
    assert datetime.datetime.fromisoformat(event["starts_at"]) == ready_event.preferred_start
    assert datetime.datetime.fromisoformat(event["ends_at"]) == ready_event.preferred_end
    assert [v["venue"] for v in event["venues"]] == ["Harbour Hall"]
    assert event["venues"][0]["location"] == "Level 2, Marina Wing"
    # Internal safety information is not part of the attendee's view.
    assert "emergency" not in str(row).lower()


@pytest.mark.django_db
def test_s4_21_04_my_events_list_only_my_registrations(
    api, attendee, second_attendee, confirmed_event
):
    open_policy(confirmed_event)
    register(event=confirmed_event, attendee=second_attendee, **details(second_attendee))
    api.force_authenticate(attendee)

    assert api.get(MINE).data == []


# S4-21-05 - AC5: an event that is not confirmed refuses registration.


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [EventStatus.APPROVED, EventStatus.PLANNING, EventStatus.SUBMITTED]
)
def test_s4_21_05_ac5_an_unconfirmed_event_refuses_registration(
    attendee_api, attendee, confirmed_event, status
):
    open_policy(confirmed_event)
    confirmed_event.status = status
    confirmed_event.save(update_fields=["status"])

    response = attendee_api.post(register_url(confirmed_event), details(attendee), format="json")

    assert response.status_code == 403
    assert not Registration.objects.exists()
    assert AuditLog.objects.filter(actor=attendee, allowed=False).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("status", [EventStatus.CANCELLED, EventStatus.COMPLETED])
def test_s4_21_05_ac5_a_cancelled_or_finished_event_refuses(attendee, confirmed_event, status):
    open_policy(confirmed_event)
    confirmed_event.status = status
    confirmed_event.save(update_fields=["status"])

    with pytest.raises(RegistrationRefused) as caught:
        register(event=confirmed_event, attendee=attendee, **details(attendee))
    assert caught.value.code == "not_confirmed"


@pytest.mark.django_db
def test_s4_21_05_returning_to_planning_keeps_existing_registrations(attendee, confirmed_event):
    open_policy(confirmed_event)
    kept = register(event=confirmed_event, attendee=attendee, **details(attendee))
    confirmed_event.status = EventStatus.PLANNING
    confirmed_event.save(update_fields=["status"])

    kept.refresh_from_db()
    assert kept.status == RegistrationStatus.REGISTERED


@pytest.mark.django_db
def test_s4_21_05_registration_not_enabled_is_refused(attendee_api, attendee, confirmed_event):
    open_policy(confirmed_event, enabled=False)

    response = attendee_api.post(register_url(confirmed_event), details(attendee), format="json")

    assert response.status_code == 409
    assert response.data["code"] == "not_enabled"
    assert not Registration.objects.exists()


@pytest.mark.django_db
def test_s4_21_05_an_event_without_a_policy_is_refused(attendee, confirmed_event):
    with pytest.raises(RegistrationRefused) as caught:
        register(event=confirmed_event, attendee=attendee, **details(attendee))
    assert caught.value.code == "not_enabled"


# S4-21-06 - only Attendees register, and the account comes from the session.


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["organiser", "coordinator", "venue_staff", "lead"])
def test_s4_21_06_only_attendees_register(api, confirmed_event, request, who):
    open_policy(confirmed_event)
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    response = api.post(register_url(confirmed_event), details(user), format="json")

    assert response.status_code == 403
    assert not Registration.objects.exists()


@pytest.mark.django_db
def test_s4_21_06_the_payload_cannot_register_someone_else(
    attendee_api, attendee, second_attendee, confirmed_event
):
    open_policy(confirmed_event)

    attendee_api.post(
        register_url(confirmed_event),
        {**details(attendee), "attendee": second_attendee.pk, "status": "WITHDRAWN"},
        format="json",
    )

    registration = Registration.objects.get()
    assert registration.attendee == attendee
    assert registration.status == RegistrationStatus.REGISTERED


# S4-21-07 - service guards for inputs the API cannot send.


@pytest.mark.django_db
def test_s4_21_07_a_non_attendee_account_is_refused_by_the_service(organiser, confirmed_event):
    open_policy(confirmed_event)

    with pytest.raises(RegistrationRefused) as caught:
        register(event=confirmed_event, attendee=organiser, **details(organiser))
    assert caught.value.code == "not_attendee"


@pytest.mark.django_db
def test_s4_21_07_accessibility_requirements_must_be_text(attendee, confirmed_event):
    from apps.registrations.services import RegistrationIncomplete

    open_policy(confirmed_event)

    with pytest.raises(RegistrationIncomplete) as caught:
        register(
            event=confirmed_event,
            attendee=attendee,
            **details(attendee, accessibility_requirements=["wheelchair"]),
        )
    assert list(caught.value.errors) == ["accessibility_requirements"]


@pytest.mark.django_db
def test_s4_21_07_no_accessibility_requirements_is_fine(attendee, confirmed_event):
    open_policy(confirmed_event)

    registration = register(
        event=confirmed_event,
        attendee=attendee,
        **details(attendee, accessibility_requirements=None),
    )
    assert registration.accessibility_requirements == ""


@pytest.mark.django_db
def test_s4_21_07_a_cancelled_event_summary_says_it_is_not_open(attendee_api, confirmed_event):
    open_policy(confirmed_event)
    confirmed_event.status = EventStatus.CANCELLED
    confirmed_event.save(update_fields=["status"])

    summary = attendee_api.get(register_url(confirmed_event)).data
    assert (summary["open"], summary["reason_code"]) == (False, "not_confirmed")
